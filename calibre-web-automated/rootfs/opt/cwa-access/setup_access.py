# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
#
# Reconcile Calibre-Web's reverse-proxy header login with the add-on's
# Cloudflare Access options, and pre-create CWA users for `access_users`.
#
# Runs as a pre-start oneshot, so it edits /config/app.db directly with
# stdlib sqlite3 instead of importing cps (which would drag in the whole
# Flask app and its migrations). Every write is guarded by PRAGMA
# table_info introspection: if upstream changes the schema we log a
# warning and leave the database untouched rather than block startup.
#
# Usage:
#   setup_access.py enable [--db PATH]    # emails on stdin, one per line
#   setup_access.py disable [--db PATH]   # exit 1 if the flag could not be cleared
#   setup_access.py warn-if-enabled [--db PATH]

import re
import secrets
import sqlite3
import sys

DEFAULT_DB = "/config/app.db"
HEADER_NAME = "X-Remote-User"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")

# Columns the INSERT relies on; all exist in every app.db since well before
# the pinned base image (v4.0.6 seeds them in empty_library/app.db).
REQUIRED_USER_COLS = {
    "name", "email", "password", "role", "locale", "sidebar_view",
    "default_language", "denied_tags", "allowed_tags",
    "denied_column_value", "allowed_column_value",
}
REQUIRED_SETTINGS_COLS = {
    "config_allow_reverse_proxy_header_login",
    "config_reverse_proxy_login_header_name",
}


def log(msg):
    print(f"[cwa-access-setup] {msg}", flush=True)


def table_cols(con, table):
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def _random_password():
    # Well-formed but unguessable hash so the account cannot be used with a
    # password. Upstream's own external-auth users get password='' (also
    # unusable: check_password_hash fails on it), which is our fallback.
    try:
        from werkzeug.security import generate_password_hash
    except ImportError:
        return ""
    return generate_password_hash(secrets.token_urlsafe(32))


def create_users(con, emails):
    user_cols = table_cols(con, "user")
    missing = REQUIRED_USER_COLS - user_cols
    if missing:
        log(f"user table is missing columns {sorted(missing)} — "
            "skipping user creation (upstream schema changed?)")
        return

    cur = con.execute("SELECT * FROM settings LIMIT 1")
    settings_row = cur.fetchone()
    settings = (
        dict(zip([d[0] for d in cur.description], settings_row))
        if settings_row else {}
    )

    for raw in emails:
        email = raw.strip().lower()
        if not email:
            continue
        if not EMAIL_RE.match(email):
            log(f"skipping invalid access_users entry: {raw!r}")
            continue
        if con.execute(
            "SELECT 1 FROM user WHERE lower(name) = ?", (email,)
        ).fetchone():
            continue

        # Mirror upstream create_authenticated_user() defaults
        # (cps/usermanagement.py @ v4.0.6).
        row = {
            "name": email,
            "email": email,
            "password": _random_password(),
            "role": settings.get("config_default_role") or 0,
            "sidebar_view": settings.get("config_default_show") or 1,
            "locale": settings.get("config_default_locale") or "en",
            "default_language": settings.get("config_default_language") or "all",
            "denied_tags": settings.get("config_denied_tags") or "",
            "allowed_tags": settings.get("config_allowed_tags") or "",
            "denied_column_value": settings.get("config_denied_column_value") or "",
            "allowed_column_value": settings.get("config_allowed_column_value") or "",
        }
        # Migration-added columns: only set the ones this app.db already has
        # (a freshly seeded app.db has not run CWA's migrations yet).
        for col, val in (
            ("kindle_mail", ""),
            ("kindle_mail_subject", ""),
            ("view_settings", "{}"),
            ("kobo_only_shelves_sync", 0),
            ("theme", 1),
            ("hardcover_token", ""),
            ("auto_send_enabled", 0),
            ("allow_additional_ereader_emails", 1),
        ):
            if col in user_cols:
                row[col] = val

        columns = ", ".join(row)
        placeholders = ", ".join(f":{k}" for k in row)
        try:
            con.execute(
                f"INSERT INTO user ({columns}) VALUES ({placeholders})", row
            )
            con.commit()
            log(f"created CWA user '{email}'")
        except sqlite3.Error as exc:
            con.rollback()
            log(f"could not create user '{email}': {exc} — skipping")


def enable(con, emails):
    missing = REQUIRED_SETTINGS_COLS - table_cols(con, "settings")
    if missing:
        log(f"settings table is missing columns {sorted(missing)} — "
            "cannot enable reverse-proxy header login (upstream schema changed?)")
        return 1
    con.execute(
        "UPDATE settings SET config_allow_reverse_proxy_header_login = 1, "
        "config_reverse_proxy_login_header_name = ?",
        (HEADER_NAME,),
    )
    con.commit()
    log(f"reverse-proxy header login enabled (header: {HEADER_NAME})")
    create_users(con, emails)
    return 0


def disable(con):
    if "config_allow_reverse_proxy_header_login" not in table_cols(con, "settings"):
        log("settings table has no reverse-proxy column — nothing to disable")
        return 0
    con.execute("UPDATE settings SET config_allow_reverse_proxy_header_login = 0")
    con.commit()
    log("reverse-proxy header login disabled")
    return 0


def warn_if_enabled(con):
    if "config_allow_reverse_proxy_header_login" not in table_cols(con, "settings"):
        return 0
    row = con.execute(
        "SELECT config_allow_reverse_proxy_header_login FROM settings LIMIT 1"
    ).fetchone()
    if row and row[0]:
        log("WARNING: reverse-proxy header login is enabled in app.db but "
            "Cloudflare Access mode is off — CWA is directly exposed, so "
            "anyone who can reach it can impersonate users by sending the "
            "login header. Disable it in CWA's admin settings unless another "
            "trusted auth proxy is in front.")
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] not in ("enable", "disable", "warn-if-enabled"):
        log("usage: setup_access.py enable|disable|warn-if-enabled [--db PATH]")
        return 2
    mode = argv[1]
    db = DEFAULT_DB
    if "--db" in argv:
        db = argv[argv.index("--db") + 1]

    try:
        con = sqlite3.connect(db, timeout=30)
    except sqlite3.Error as exc:
        log(f"cannot open {db}: {exc}")
        return 1
    try:
        if mode == "enable":
            emails = [line for line in sys.stdin.read().splitlines() if line.strip()]
            return enable(con, emails)
        if mode == "disable":
            return disable(con)
        return warn_if_enabled(con)
    except sqlite3.Error as exc:
        log(f"database error on {db}: {exc}")
        return 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
