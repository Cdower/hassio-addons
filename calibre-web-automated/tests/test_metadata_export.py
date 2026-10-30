# SPDX-License-Identifier: MIT
#
# Offline tests for the `metadata_db_export` exporter
# (rootfs/opt/cwa-split-library/metadata_export.py).
#
# Run directly:   python3 calibre-web-automated/tests/test_metadata_export.py
# Or via pytest:  pytest calibre-web-automated/tests/test_metadata_export.py

import contextlib
import importlib.util
import io
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.dirname(HERE)
EXPORT_PATH = os.path.join(
    ADDON_ROOT,
    "rootfs",
    "opt",
    "cwa-split-library",
    "metadata_export.py",
)

spec = importlib.util.spec_from_file_location("cwa_metadata_export", EXPORT_PATH)
metadata_export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata_export)


def titles(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute("SELECT title FROM books ORDER BY id")]
    finally:
        con.close()


class ScheduleTest(unittest.TestCase):
    def test_first_look_exports_at_once(self):
        schedule = metadata_export.Schedule(settle=60, max_delay=600)
        self.assertTrue(schedule.due("a", 0))

    def test_waits_for_changes_to_settle(self):
        schedule = metadata_export.Schedule(settle=60, max_delay=600)
        schedule.done("a")
        self.assertFalse(schedule.due("a", 10))
        self.assertFalse(schedule.due("b", 20))
        self.assertFalse(schedule.due("b", 79))
        self.assertTrue(schedule.due("b", 80))
        schedule.done("b")
        self.assertFalse(schedule.due("b", 90))

    def test_busy_library_is_exported_after_max_delay(self):
        schedule = metadata_export.Schedule(settle=60, max_delay=600)
        schedule.done("a")
        for t in range(0, 600, 30):
            self.assertFalse(schedule.due(f"s{t}", t), t)
        self.assertTrue(schedule.due("s600", 600))

    def test_change_reverted_before_export_is_not_pending(self):
        schedule = metadata_export.Schedule(settle=60, max_delay=600)
        schedule.done("a")
        schedule.due("b", 0)
        self.assertFalse(schedule.due("a", 10))
        self.assertFalse(schedule.pending("a"))
        self.assertTrue(schedule.pending("b"))

    def test_change_coming_back_after_revert_waits_to_settle(self):
        schedule = metadata_export.Schedule(settle=60, max_delay=600)
        schedule.done("a")
        schedule.due("b", 0)
        schedule.due("a", 10)
        self.assertFalse(schedule.due("b", 20))
        self.assertFalse(schedule.due("b", 79))
        self.assertTrue(schedule.due("b", 80))


class ExporterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.library = os.path.join(tmp.name, "library")
        self.books = os.path.join(tmp.name, "books")
        self.tmp = os.path.join(tmp.name, "tmp")
        for d in (self.library, self.books, self.tmp):
            os.makedirs(d)
        self.source = os.path.join(self.library, "metadata.db")
        self.target = os.path.join(self.books, "metadata.db")
        # CWA's own connection, kept open in WAL mode like the live app.
        self.cwa = sqlite3.connect(self.source)
        self.addCleanup(self.cwa.close)
        self.cwa.execute("PRAGMA journal_mode=WAL")
        self.cwa.execute("PRAGMA wal_autocheckpoint=0")
        self.cwa.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)")
        self.add("Dune")
        self.exporter = metadata_export.Exporter(self.source, self.books, self.tmp)
        self.out = io.StringIO()
        self.quiet = contextlib.redirect_stdout(self.out)

    def add(self, title):
        self.cwa.execute("INSERT INTO books (title) VALUES (?)", (title,))
        self.cwa.commit()

    def test_export_is_consistent_single_file(self):
        self.exporter.export()
        self.assertEqual(titles(self.target), ["Dune"])
        with open(self.target, "rb") as fh:
            header = fh.read(20)
        # File format bytes 18/19 are 1 for the rollback journal, 2 for WAL.
        self.assertEqual(header[18:20], b"\x01\x01")
        self.assertEqual(os.listdir(self.books), ["metadata.db"])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_export_replaces_copy_and_stale_side_files(self):
        self.exporter.export()
        self.add("Emma")
        for side in metadata_export.SIDE_FILES:
            with open(self.target + side, "wb") as fh:
                fh.write(b"stale")
        self.exporter.export()
        self.assertEqual(titles(self.target), ["Dune", "Emma"])
        self.assertEqual(os.listdir(self.books), ["metadata.db"])

    def test_warns_when_copy_was_changed_elsewhere(self):
        self.exporter.export()
        con = sqlite3.connect(self.target)
        con.execute("INSERT INTO books (title) VALUES ('Edited on desktop')")
        con.commit()
        con.close()
        with self.quiet:
            self.exporter.export()
        self.assertIn("read-only copy", self.out.getvalue())
        self.assertEqual(titles(self.target), ["Dune"])

    def test_timestamp_change_alone_is_not_an_outside_edit(self):
        # Network shares can report a file's mtime differently from what was
        # written; only real writes to the copy should be warned about.
        self.exporter.export()
        os.utime(self.target, ns=(1, 1))
        with self.quiet:
            self.exporter.export()
        self.assertNotIn("WARNING", self.out.getvalue())

    def test_export_does_not_checkpoint_the_source(self):
        # As the last connection to close, the exporter must not checkpoint
        # CWA's WAL: that changes the source and triggers a second export.
        # A copy of the live files is a WAL database with frames not yet
        # checkpointed and no connection open on it.
        source = os.path.join(self.library, "idle.db")
        shutil.copyfile(self.source, source)
        shutil.copyfile(self.source + "-wal", source + "-wal")
        self.exporter.source = source
        before = metadata_export.db_signature(source)
        self.exporter.export()
        self.assertEqual(metadata_export.db_signature(source), before)
        self.assertEqual(titles(self.target), ["Dune"])

    def test_failed_export_keeps_previous_copy(self):
        self.exporter.export()
        self.exporter.source = os.path.join(self.library, "missing.db")
        with self.assertRaises(sqlite3.Error):
            self.exporter.export()
        self.assertEqual(titles(self.target), ["Dune"])
        self.assertEqual(os.listdir(self.books), ["metadata.db"])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_run_exports_changes_and_once_more_on_stop(self):
        stop = threading.Event()
        now = [0.0]
        schedule = metadata_export.Schedule(settle=0, max_delay=0)
        thread = threading.Thread(
            target=metadata_export.run,
            args=(self.exporter, schedule, 0.01, stop, lambda: now[0]),
        )
        with self.quiet:
            thread.start()
            deadline = time.monotonic() + 5
            while not os.path.exists(self.target) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(titles(self.target), ["Dune"])
            # A change right before stopping is exported by the final pass.
            schedule.settle = schedule.max_delay = 10**9
            self.add("Emma")
            stop.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(titles(self.target), ["Dune", "Emma"])
        self.assertIn("final export", self.out.getvalue())

    def test_sigterm_makes_final_export_and_exits(self):
        proc = subprocess.Popen(
            [
                sys.executable,
                EXPORT_PATH,
                "--source",
                self.source,
                "--target-dir",
                self.books,
                "--tmp-dir",
                self.tmp,
                "--interval",
                "3600",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.addCleanup(proc.kill)
        deadline = time.monotonic() + 10
        while not os.path.exists(self.target) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(titles(self.target), ["Dune"])
        self.add("Emma")
        proc.send_signal(signal.SIGTERM)
        output, _ = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, output)
        self.assertIn("final export", output)
        self.assertEqual(titles(self.target), ["Dune", "Emma"])


if __name__ == "__main__":
    unittest.main()
