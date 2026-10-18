# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
#
# Offline tests for the backup snapshot helper
# (rootfs/opt/cwa-backup/db_snapshot.py).
#
# Run directly:   python3 calibre-web-automated/tests/test_db_snapshot.py
# Or via pytest:  pytest calibre-web-automated/tests/test_db_snapshot.py

import contextlib
import importlib.util
import io
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.dirname(HERE)
SNAPSHOT_PATH = os.path.join(ADDON_ROOT, "rootfs", "opt", "cwa-backup", "db_snapshot.py")

spec = importlib.util.spec_from_file_location("cwa_db_snapshot", SNAPSHOT_PATH)
db_snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db_snapshot)


def rows(path):
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("SELECT v FROM t ORDER BY v")]
    finally:
        con.close()


class DbSnapshotTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = os.path.join(tmp.name, "data")
        self.addon_config = os.path.join(tmp.name, "addon_config")
        self.library = os.path.join(self.addon_config, "calibre-library")
        os.makedirs(self.data)
        os.makedirs(self.library)
        self.roots = [self.data, self.addon_config, os.path.join(tmp.name, "missing")]
        self.quiet = contextlib.redirect_stdout(io.StringIO())

    def make_db(self, path, values, wal=False):
        con = sqlite3.connect(path)
        if wal:
            con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE t (v INTEGER)")
        con.executemany("INSERT INTO t VALUES (?)", [(v,) for v in values])
        con.commit()
        return con

    def test_snapshot_captures_uncheckpointed_wal_data(self):
        app_db = os.path.join(self.data, "app.db")
        writer = self.make_db(app_db, [1, 2], wal=True)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO t VALUES (3)")
        writer.commit()

        # A plain copy of the database file (what the Supervisor's tar does)
        # misses everything still in the -wal file — here, the whole table.
        torn = os.path.join(self.data, "torn-copy")
        shutil.copyfile(app_db, torn)
        with self.assertRaises(sqlite3.OperationalError):
            rows(torn)

        made = db_snapshot.create(self.roots)
        self.assertEqual(made, [app_db + db_snapshot.SUFFIX])
        self.assertEqual(rows(app_db + db_snapshot.SUFFIX), [1, 2, 3])

    def test_finds_databases_in_all_roots_and_skips_non_sqlite(self):
        self.make_db(os.path.join(self.data, "app.db"), [1]).close()
        self.make_db(os.path.join(self.data, "cwa.db"), [2]).close()
        self.make_db(os.path.join(self.library, "metadata.db"), [3]).close()
        open(os.path.join(self.data, "gdrive.db"), "wb").close()  # empty
        with open(os.path.join(self.data, "notes.db"), "w") as fh:
            fh.write("not sqlite")
        self.make_db(os.path.join(self.data, "app.sqlite"), [4]).close()

        made = db_snapshot.create(self.roots)
        self.assertEqual(sorted(made), sorted(
            p + db_snapshot.SUFFIX for p in (
                os.path.join(self.data, "app.db"),
                os.path.join(self.data, "cwa.db"),
                os.path.join(self.library, "metadata.db"),
            )
        ))

    def test_restore_replaces_torn_database_and_drops_stale_side_files(self):
        app_db = os.path.join(self.data, "app.db")
        self.make_db(app_db, [1, 2]).close()
        db_snapshot.create(self.roots)

        # Simulate what a restored backup holds: a damaged live copy plus
        # stale WAL/SHM files next to it.
        with open(app_db, "r+b") as fh:
            fh.seek(100)
            fh.write(b"\xff" * 64)
        for side in db_snapshot.SIDE_FILES:
            with open(app_db + side, "wb") as fh:
                fh.write(b"stale")

        with self.quiet:
            self.assertEqual(db_snapshot.restore(self.roots), [app_db])
        self.assertEqual(rows(app_db), [1, 2])
        for side in db_snapshot.SIDE_FILES:
            self.assertFalse(os.path.exists(app_db + side))
        self.assertEqual(db_snapshot.find_snapshots(self.roots), [])

    def test_restore_without_snapshots_changes_nothing(self):
        app_db = os.path.join(self.data, "app.db")
        self.make_db(app_db, [1]).close()
        self.assertEqual(db_snapshot.restore(self.roots), [])
        self.assertEqual(rows(app_db), [1])

    def test_discard_removes_listed_snapshots_and_list(self):
        self.make_db(os.path.join(self.data, "app.db"), [1]).close()
        db_snapshot.create(self.roots)
        self.assertEqual(db_snapshot.discard(self.roots), 1)
        self.assertEqual(db_snapshot.find_snapshots(self.roots), [])
        self.assertFalse(os.path.exists(db_snapshot.list_path(self.roots)))
        self.assertTrue(os.path.exists(os.path.join(self.data, "app.db")))

    def test_create_lists_its_snapshots_and_sweeps_strays(self):
        app_db = os.path.join(self.data, "app.db")
        self.make_db(app_db, [1]).close()
        stray_tmp = os.path.join(self.library, "metadata.db" + db_snapshot.TMP_SUFFIX)
        stray = os.path.join(self.library, "gone.db" + db_snapshot.SUFFIX)
        for path in (stray_tmp, stray):
            open(path, "w").close()
        made = db_snapshot.create(self.roots)
        self.assertEqual(db_snapshot.read_list(self.roots), made)
        self.assertFalse(os.path.exists(stray_tmp))
        self.assertFalse(os.path.exists(stray))

    def test_restore_without_list_does_not_touch_stray_snapshots(self):
        # No list means a normal start: nothing is walked or restored, even
        # if a snapshot file happens to be lying around.
        app_db = os.path.join(self.data, "app.db")
        self.make_db(app_db, [1]).close()
        stray = app_db + db_snapshot.SUFFIX
        self.make_db(stray, [99]).close()
        self.assertEqual(db_snapshot.restore(self.roots), [])
        self.assertEqual(rows(app_db), [1])

    def test_restore_ignores_entries_outside_roots_and_missing_snapshots(self):
        app_db = os.path.join(self.data, "app.db")
        self.make_db(app_db, [1]).close()
        outside_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside_dir)
        outside = os.path.join(outside_dir, "x.db" + db_snapshot.SUFFIX)
        open(outside, "w").close()
        with open(db_snapshot.list_path(self.roots), "w") as fh:
            fh.write(f"{outside}\n")
            fh.write(f"{app_db + db_snapshot.SUFFIX}\n")  # listed, but missing
            fh.write(f"{os.path.join(self.data, 'not-a-snapshot')}\n")
        with self.quiet:
            self.assertEqual(db_snapshot.restore(self.roots), [])
        self.assertTrue(os.path.exists(outside))
        self.assertEqual(rows(app_db), [1])
        self.assertFalse(os.path.exists(db_snapshot.list_path(self.roots)))

    def test_create_replaces_stale_snapshots(self):
        app_db = os.path.join(self.data, "app.db")
        self.make_db(app_db, [1]).close()
        db_snapshot.create(self.roots)
        con = sqlite3.connect(app_db)
        con.execute("INSERT INTO t VALUES (2)")
        con.commit()
        con.close()
        db_snapshot.create(self.roots)
        self.assertEqual(rows(app_db + db_snapshot.SUFFIX), [1, 2])

    def test_failed_create_leaves_no_snapshots(self):
        self.make_db(os.path.join(self.data, "app.db"), [1]).close()
        # Valid SQLite header, garbage body: the backup API fails on it.
        with open(os.path.join(self.data, "zz-broken.db"), "wb") as fh:
            fh.write(db_snapshot.SQLITE_HEADER + b"\x01" * 4000)

        with self.assertRaises(sqlite3.Error):
            db_snapshot.create(self.roots)
        self.assertEqual(db_snapshot.find_snapshots(self.roots), [])
        self.assertEqual(db_snapshot.find_snapshots(self.roots, db_snapshot.TMP_SUFFIX), [])
        self.assertFalse(os.path.exists(db_snapshot.list_path(self.roots)))

    def test_main_create_failure_exits_nonzero(self):
        with open(os.path.join(self.data, "broken.db"), "wb") as fh:
            fh.write(db_snapshot.SQLITE_HEADER + b"\x01" * 4000)
        with self.quiet, mock.patch.object(db_snapshot, "drop_privileges"):
            self.assertEqual(db_snapshot.main(["create", self.data]), 1)


if __name__ == "__main__":
    unittest.main()
