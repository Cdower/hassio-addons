# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
#
# Offline tests for the Cloudflare Access app.db reconciler
# (rootfs/opt/cwa-access/setup_access.py).
#
# The fixture database mirrors the core `user` and `settings` schema of the
# calibre-web-nextgen base image's app.db BEFORE the app's own migrations add
# columns like `theme` (setup_access must handle both, since it introspects
# columns), plus a migrated variant. No network, no cps import.
#
# Run directly:   python3 calibre-web-automated/tests/test_access_users.py
# Or via pytest:  pytest calibre-web-automated/tests/test_access_users.py

import importlib.util
import io
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.dirname(HERE)
SETUP_PATH = os.path.join(ADDON_ROOT, "rootfs", "opt", "cwa-access", "setup_access.py")

spec = importlib.util.spec_from_file_location("cwa_setup_access", SETUP_PATH)
setup_access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_access)

# Core `user` columns (pre-migration: no theme/hardcover_token/
# kindle_mail_subject/opds_only_shelves_sync/...).
SEEDED_USER_SQL = """
CREATE TABLE user (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(64) UNIQUE,
    email VARCHAR(120) UNIQUE,
    role SMALLINT,
    password VARCHAR,
    kindle_mail VARCHAR(120),
    locale VARCHAR(2),
    sidebar_view INTEGER,
    default_language VARCHAR(3),
    denied_tags VARCHAR,
    allowed_tags VARCHAR,
    denied_column_value VARCHAR,
    allowed_column_value VARCHAR,
    view_settings JSON,
    kobo_only_shelves_sync INTEGER
)
"""

SETTINGS_SQL = """
CREATE TABLE settings (
    id INTEGER NOT NULL PRIMARY KEY,
    config_default_role SMALLINT,
    config_default_show INTEGER,
    config_default_locale VARCHAR,
    config_default_language VARCHAR,
    config_denied_tags VARCHAR,
    config_allowed_tags VARCHAR,
    config_denied_column_value VARCHAR,
    config_allowed_column_value VARCHAR,
    config_allow_reverse_proxy_header_login BOOLEAN,
    config_reverse_proxy_login_header_name VARCHAR
)
"""


def _make_db(path, migrated=False):
    con = sqlite3.connect(path)
    user_sql = SEEDED_USER_SQL
    if migrated:
        user_sql = user_sql.replace(
            "    kobo_only_shelves_sync INTEGER\n",
            "    kobo_only_shelves_sync INTEGER,\n"
            "    hardcover_token VARCHAR,\n"
            "    opds_only_shelves_sync INTEGER DEFAULT 0,\n"
            "    theme INTEGER DEFAULT 0,\n"
            "    kindle_mail_subject VARCHAR(256),\n"
            "    auto_send_enabled BOOLEAN DEFAULT 0,\n"
            "    allow_additional_ereader_emails BOOLEAN DEFAULT 1\n",
        )
    con.execute(user_sql)
    con.execute(SETTINGS_SQL)
    con.execute(
        "INSERT INTO settings (config_default_role, config_default_show, "
        "config_default_locale, config_default_language, "
        "config_allow_reverse_proxy_header_login) VALUES (0, 262143, 'en', 'all', 0)"
    )
    con.execute(
        "INSERT INTO user (name, email, role, password) "
        "VALUES ('admin', 'admin@example.org', 479, 'pbkdf2:whatever')"
    )
    con.commit()
    con.close()


def _run(mode, db, emails=()):
    argv = ["setup_access.py", mode, "--db", db]
    with mock.patch.object(setup_access.sys, "stdin", io.StringIO("\n".join(emails))):
        return setup_access.main(argv)


class SetupAccessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "app.db")

    def _query(self, sql):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def test_enable_sets_flags_and_creates_users(self):
        _make_db(self.db)
        rc = _run("enable", self.db, ["Alice@Gmail.com", "bob@icloud.com"])
        self.assertEqual(rc, 0)
        flag, header = self._query(
            "SELECT config_allow_reverse_proxy_header_login, "
            "config_reverse_proxy_login_header_name FROM settings"
        )[0]
        self.assertEqual(flag, 1)
        self.assertEqual(header, "X-Remote-User")
        rows = self._query(
            "SELECT name, email, role, sidebar_view, locale, default_language "
            "FROM user WHERE name != 'admin' ORDER BY name"
        )
        self.assertEqual(
            rows,
            [
                ("alice@gmail.com", "alice@gmail.com", 0, 262143, "en", "all"),
                ("bob@icloud.com", "bob@icloud.com", 0, 262143, "en", "all"),
            ],
        )
        # Password must be non-empty (unusable random hash) or '' fallback —
        # never a guessable value. With werkzeug installed we expect a hash.
        (password,) = self._query(
            "SELECT password FROM user WHERE name = 'alice@gmail.com'"
        )[0]
        self.assertTrue(password == "" or ":" in password)

    def test_enable_is_idempotent_and_case_insensitive(self):
        _make_db(self.db)
        self.assertEqual(_run("enable", self.db, ["alice@gmail.com"]), 0)
        self.assertEqual(_run("enable", self.db, ["ALICE@gmail.com"]), 0)
        (count,) = self._query(
            "SELECT COUNT(*) FROM user WHERE lower(name) = 'alice@gmail.com'"
        )[0]
        self.assertEqual(count, 1)

    def test_invalid_emails_skipped(self):
        _make_db(self.db)
        rc = _run(
            "enable",
            self.db,
            [
                "not-an-email",
                "two@at@signs",
                "with space@x.com",
                "a@b:8080",
                "unicode@exämple.com",
                "",
                "ok@example.com",
            ],
        )
        self.assertEqual(rc, 0)
        rows = self._query("SELECT name FROM user WHERE name != 'admin'")
        self.assertEqual(rows, [("ok@example.com",)])

    def test_migrated_schema_gets_extra_defaults(self):
        _make_db(self.db, migrated=True)
        self.assertEqual(_run("enable", self.db, ["alice@gmail.com"]), 0)
        rows = self._query(
            "SELECT theme, kobo_only_shelves_sync, opds_only_shelves_sync, "
            "auto_send_enabled, allow_additional_ereader_emails "
            "FROM user WHERE name = 'alice@gmail.com'"
        )
        self.assertEqual(rows, [(1, 0, 0, 0, 1)])

    def test_user_schema_mismatch_skips_creation_but_enables_login(self):
        _make_db(self.db)
        con = sqlite3.connect(self.db)
        con.execute("ALTER TABLE user RENAME COLUMN sidebar_view TO sidebar_view_x")
        con.commit()
        con.close()
        rc = _run("enable", self.db, ["alice@gmail.com"])
        self.assertEqual(rc, 0)  # never blocks startup
        (flag,) = self._query(
            "SELECT config_allow_reverse_proxy_header_login FROM settings"
        )[0]
        self.assertEqual(flag, 1)
        rows = self._query("SELECT name FROM user WHERE name != 'admin'")
        self.assertEqual(rows, [])

    def test_settings_schema_mismatch_fails_without_writing(self):
        _make_db(self.db)
        con = sqlite3.connect(self.db)
        con.execute(
            "ALTER TABLE settings RENAME COLUMN "
            "config_allow_reverse_proxy_header_login TO nope"
        )
        con.commit()
        con.close()
        rc = _run("enable", self.db, ["alice@gmail.com"])
        self.assertEqual(rc, 1)  # sentinel must not be written
        rows = self._query("SELECT name FROM user WHERE name != 'admin'")
        self.assertEqual(rows, [])

    def test_disable_clears_flag(self):
        _make_db(self.db)
        self.assertEqual(_run("enable", self.db), 0)
        self.assertEqual(_run("disable", self.db), 0)
        (flag,) = self._query(
            "SELECT config_allow_reverse_proxy_header_login FROM settings"
        )[0]
        self.assertEqual(flag, 0)

    def test_warn_if_enabled_never_fails(self):
        _make_db(self.db)
        self.assertEqual(_run("warn-if-enabled", self.db), 0)
        self.assertEqual(_run("enable", self.db), 0)
        self.assertEqual(_run("warn-if-enabled", self.db), 0)

    def test_missing_db_returns_error(self):
        rc = _run("enable", os.path.join(self.tmp.name, "nope", "app.db"))
        self.assertEqual(rc, 1)

    def test_duplicate_email_different_name_skipped(self):
        # UNIQUE(email) violation must be caught per-user, not crash the run.
        _make_db(self.db)
        con = sqlite3.connect(self.db)
        con.execute(
            "INSERT INTO user (name, email, role, password) "
            "VALUES ('olduser', 'alice@gmail.com', 0, 'x')"
        )
        con.commit()
        con.close()
        rc = _run("enable", self.db, ["alice@gmail.com", "bob@icloud.com"])
        self.assertEqual(rc, 0)
        rows = self._query("SELECT name FROM user ORDER BY id")
        self.assertEqual(rows, [("admin",), ("olduser",), ("bob@icloud.com",)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
