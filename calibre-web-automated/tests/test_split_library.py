# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
#
# Offline tests for the `books_path` split library helper
# (rootfs/opt/cwa-split-library/split_library.py).
#
# Run directly:   python3 calibre-web-automated/tests/test_split_library.py
# Or via pytest:  pytest calibre-web-automated/tests/test_split_library.py

import contextlib
import importlib.util
import io
import os
import sqlite3
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.dirname(HERE)
SPLIT_PATH = os.path.join(
    ADDON_ROOT, "rootfs", "opt", "cwa-split-library", "split_library.py",
)

spec = importlib.util.spec_from_file_location("cwa_split_library", SPLIT_PATH)
split_library = importlib.util.module_from_spec(spec)
spec.loader.exec_module(split_library)


def make_library(path, titles, wal=False):
    """A minimal Calibre metadata.db: just the books table prepare() reads."""
    con = sqlite3.connect(path)
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)")
    con.executemany("INSERT INTO books (title) VALUES (?)", [(t,) for t in titles])
    con.commit()
    return con


def titles(path):
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("SELECT title FROM books ORDER BY id")]
    finally:
        con.close()


class PrepareTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.library = os.path.join(tmp.name, "addon_config", "calibre-library")
        self.books = os.path.join(tmp.name, "smb", "calibre-library")
        os.makedirs(self.library)
        os.makedirs(self.books)
        self.state = os.path.join(tmp.name, "state")
        self.local = os.path.join(self.library, "metadata.db")
        self.shared = os.path.join(self.books, "metadata.db")
        self.out = io.StringIO()
        self.quiet = contextlib.redirect_stdout(self.out)

    def prepare(self):
        with self.quiet:
            return split_library.prepare(self.library, self.books, self.state)

    def test_imports_share_library_and_sets_share_copy_aside(self):
        make_library(self.shared, ["Dune", "Emma"]).close()
        self.assertEqual(self.prepare(), "imported")
        self.assertEqual(titles(self.local), ["Dune", "Emma"])
        self.assertFalse(os.path.exists(self.shared))
        self.assertEqual(titles(self.shared + ".pre-split"), ["Dune", "Emma"])
        self.assertEqual(split_library.read_state(self.state),
                         (self.library, self.books))
        self.assertFalse(os.path.exists(
            os.path.join(self.library, split_library.STAGING_NAME)))

    def test_import_carries_uncheckpointed_wal(self):
        writer = make_library(self.shared, ["Dune"], wal=True)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO books (title) VALUES ('Emma')")
        writer.commit()
        self.assertTrue(os.path.exists(self.shared + "-wal"))

        self.assertEqual(self.prepare(), "imported")
        self.assertEqual(titles(self.local), ["Dune", "Emma"])
        for side in split_library.SIDE_FILES:
            self.assertFalse(os.path.exists(self.local + side))
        # The imported copy is a single file, not left in WAL mode.
        con = sqlite3.connect(self.local)
        try:
            self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        finally:
            con.close()

    def test_replaces_empty_local_library(self):
        make_library(self.local, []).close()
        make_library(self.shared, ["Dune"]).close()
        self.assertEqual(self.prepare(), "imported")
        self.assertEqual(titles(self.local), ["Dune"])
        self.assertEqual(titles(self.local + ".pre-split"), [])

    def test_keeps_local_library_over_empty_share_copy(self):
        make_library(self.local, ["Dune"]).close()
        make_library(self.shared, []).close()
        self.assertEqual(self.prepare(), "kept-local")
        self.assertEqual(titles(self.local), ["Dune"])
        self.assertTrue(os.path.exists(self.shared + ".pre-split"))

    def test_refuses_two_libraries_and_records_nothing(self):
        make_library(self.local, ["Dune"]).close()
        make_library(self.shared, ["Emma"]).close()
        with self.assertRaises(split_library.SplitError):
            self.prepare()
        self.assertEqual(titles(self.local), ["Dune"])
        self.assertEqual(titles(self.shared), ["Emma"])
        self.assertIsNone(split_library.read_state(self.state))

    def test_same_books_path_is_not_prepared_twice(self):
        make_library(self.shared, ["Dune"]).close()
        self.prepare()
        # E.g. the add-on's own metadata_db_export copy appearing later.
        make_library(self.shared, ["Emma"]).close()
        self.assertEqual(self.prepare(), "unchanged")
        self.assertEqual(titles(self.local), ["Dune"])
        self.assertEqual(titles(self.shared), ["Emma"])

    def test_trailing_slash_counts_as_same_books_path(self):
        self.prepare()
        with self.quiet:
            self.assertEqual(
                split_library.prepare(self.library, self.books + "/", self.state),
                "unchanged")

    def test_nothing_anywhere_starts_new_library(self):
        self.assertEqual(self.prepare(), "new")
        self.assertFalse(os.path.exists(self.local))
        self.assertEqual(split_library.read_state(self.state),
                         (self.library, self.books))

    def test_warns_about_book_folders_without_a_database(self):
        os.makedirs(os.path.join(self.books, "Frank Herbert", "Dune (1)"))
        self.prepare()
        self.assertIn("starts a new, empty library", self.out.getvalue())

    def test_warns_about_book_folders_left_in_library_path(self):
        make_library(self.local, ["Dune"]).close()
        os.makedirs(os.path.join(self.library, "Frank Herbert"))
        os.makedirs(os.path.join(self.library, ".calnotes"))
        self.assertEqual(self.prepare(), "kept-local")
        self.assertIn("move the book folders", self.out.getvalue())
        self.assertIn("Frank Herbert", self.out.getvalue())
        self.assertNotIn(".calnotes", self.out.getvalue())

    def test_set_aside_never_overwrites_an_earlier_copy(self):
        make_library(self.shared + ".pre-split", ["Old"]).close()
        make_library(self.shared, ["Dune"]).close()
        self.prepare()
        self.assertEqual(titles(self.shared + ".pre-split"), ["Old"])
        self.assertEqual(titles(self.shared + ".pre-split.2"), ["Dune"])

    def test_not_a_calibre_database_fails(self):
        con = sqlite3.connect(self.shared)
        con.execute("CREATE TABLE t (v)")
        con.commit()
        con.close()
        with self.assertRaises(split_library.SplitError):
            self.prepare()
        self.assertTrue(os.path.exists(self.shared))
        self.assertFalse(os.path.exists(self.local))

    def test_paths_with_uri_metacharacters(self):
        # '#', '?' and '%' are URI syntax; the path must not be cut short.
        self.library = os.path.join(os.path.dirname(self.library), "lib #1 ?x %41")
        os.makedirs(self.library)
        self.local = os.path.join(self.library, "metadata.db")
        make_library(self.local, ["Dune"]).close()
        self.assertEqual(self.prepare(), "kept-local")
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.library))),
                         ["calibre-library", "lib #1 ?x %41"])

    def move_library(self):
        """Point library_path at a new, empty folder, keeping books_path."""
        self.old_library, self.old_local = self.library, self.local
        self.library = os.path.join(os.path.dirname(self.library), "moved-library")
        os.makedirs(self.library)
        self.local = os.path.join(self.library, "metadata.db")

    def test_library_path_change_moves_the_database(self):
        make_library(self.shared, ["Dune"]).close()
        self.prepare()
        # metadata_db_export's copy, a little behind the live database.
        make_library(self.shared, []).close()
        con = sqlite3.connect(self.local)
        con.execute("INSERT INTO books (title) VALUES ('Emma')")
        con.commit()
        con.close()

        self.move_library()
        self.assertEqual(self.prepare(), "moved")
        self.assertEqual(titles(self.local), ["Dune", "Emma"])
        self.assertFalse(os.path.exists(self.old_local))
        self.assertEqual(titles(self.old_local + ".moved"), ["Dune", "Emma"])
        # The export copy is left for the exporter to replace.
        self.assertEqual(titles(self.shared), [])
        self.assertEqual(split_library.read_state(self.state),
                         (self.library, self.books))

    def test_library_path_change_restores_export_when_old_folder_is_gone(self):
        make_library(self.shared, ["Dune"]).close()
        self.prepare()
        make_library(self.shared, ["Dune", "Emma"]).close()  # the export copy
        self.move_library()
        os.remove(self.old_local)
        self.assertEqual(self.prepare(), "restored-export")
        self.assertEqual(titles(self.local), ["Dune", "Emma"])
        self.assertIn("metadata_db_export copy", self.out.getvalue())

    def test_library_path_change_to_an_existing_library_keeps_it(self):
        make_library(self.shared, ["Dune"]).close()
        self.prepare()
        os.remove(self.local)
        self.move_library()
        make_library(self.local, ["Emma"]).close()
        self.assertEqual(self.prepare(), "kept-local")
        self.assertEqual(titles(self.local), ["Emma"])

    def test_library_path_change_with_libraries_in_both_folders_fails(self):
        make_library(self.shared, ["Dune"]).close()
        self.prepare()
        self.move_library()
        make_library(self.local, ["Emma"]).close()
        with self.assertRaises(split_library.SplitError):
            self.prepare()
        self.assertEqual(titles(self.old_local), ["Dune"])
        self.assertEqual(titles(self.local), ["Emma"])
        self.assertEqual(split_library.read_state(self.state),
                         (self.old_library, self.books))

    def test_library_path_change_with_no_database_anywhere_warns(self):
        make_library(self.shared, ["Dune"]).close()
        self.prepare()
        os.remove(self.local)
        self.move_library()
        self.assertEqual(self.prepare(), "new")
        self.assertFalse(os.path.exists(self.local))
        self.assertIn("starts a new, empty library", self.out.getvalue())

    def test_unreadable_state_is_treated_as_first_setup(self):
        with open(self.state, "w") as fh:
            fh.write("/old/single-line/format\n")
        make_library(self.shared, ["Dune"]).close()
        self.assertEqual(self.prepare(), "imported")
        self.assertEqual(titles(self.local), ["Dune"])

    def test_main_reports_failure(self):
        with open(self.shared, "wb") as fh:
            fh.write(b"SQLite format 3\x00" + b"\x01" * 4000)
        with self.quiet:
            self.assertEqual(split_library.main([
                "prepare", "--library", self.library, "--books", self.books,
                "--state", self.state,
            ]), 1)
        self.assertIn("ERROR", self.out.getvalue())


class SettingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = os.path.join(tmp.name, "app.db")
        con = sqlite3.connect(self.db)
        con.execute(
            "CREATE TABLE settings (id INTEGER PRIMARY KEY, "
            "config_calibre_dir TEXT, config_calibre_split BOOLEAN, "
            "config_calibre_split_dir TEXT, config_calibre_server_enabled BOOLEAN)"
        )
        con.execute(
            "INSERT INTO settings VALUES (1, '/calibre-library', 0, NULL, 0)")
        con.commit()
        con.close()
        self.out = io.StringIO()
        self.quiet = contextlib.redirect_stdout(self.out)

    def main(self, *args):
        with self.quiet:
            return split_library.main([*args, "--db", self.db])

    def settings(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(
                "SELECT config_calibre_split, config_calibre_split_dir, "
                "config_calibre_dir FROM settings").fetchone()
        finally:
            con.close()

    def test_enable_then_disable(self):
        self.assertEqual(self.main("enable", "--books-dir", "/calibre-books"), 0)
        self.assertEqual(self.settings(), (1, "/calibre-books", "/calibre-library"))
        self.assertEqual(self.main("disable"), 0)
        self.assertEqual(self.settings()[0], 0)

    def test_enable_warns_about_content_server(self):
        con = sqlite3.connect(self.db)
        con.execute("UPDATE settings SET config_calibre_server_enabled = 1")
        con.commit()
        con.close()
        self.assertEqual(self.main("enable", "--books-dir", "/calibre-books"), 0)
        self.assertIn("content server", self.out.getvalue())

    def test_enable_fails_without_split_columns(self):
        con = sqlite3.connect(self.db)
        con.execute("ALTER TABLE settings DROP COLUMN config_calibre_split_dir")
        con.commit()
        con.close()
        self.assertEqual(self.main("enable", "--books-dir", "/calibre-books"), 1)
        self.assertEqual(self.settings_split(), 0)

    def settings_split(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT config_calibre_split FROM settings").fetchone()[0]
        finally:
            con.close()

    def test_enable_fails_without_settings_row(self):
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM settings")
        con.commit()
        con.close()
        self.assertEqual(self.main("enable", "--books-dir", "/calibre-books"), 1)

    def test_missing_app_db_is_not_created(self):
        os.remove(self.db)
        self.assertEqual(self.main("enable", "--books-dir", "/calibre-books"), 1)
        self.assertFalse(os.path.exists(self.db))


if __name__ == "__main__":
    unittest.main()
