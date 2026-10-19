# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
#
# Split library support for the `books_path` option: metadata.db stays in
# `library_path` (local storage) while the book folders live in `books_path`
# (typically the SMB share). Calibre-Web NextGen supports this natively
# through its "split library" settings (config_calibre_split and
# config_calibre_split_dir in app.db); ingest hands Calibre the local
# database through CALIBRE_OVERRIDE_DATABASE_PATH.
#
#   prepare  (init-cwa-paths, before CWA starts) the first time a books_path
#            is used, bring an existing metadata.db over from it: a library
#            that used to live entirely on the share keeps its database. The
#            share's copy is renamed to metadata.db.pre-split, so nothing
#            mistakes it for the live one. Records the books_path in the state
#            file; later starts with the same books_path do nothing.
#   enable   (init-cwa-split-library, after cwa-auto-library has created
#            app.db) turn split library mode on, pointing it at BOOKS_DIR.
#   disable  turn split library mode off again.
#
# Like setup_access.py this edits app.db with stdlib sqlite3 instead of
# importing cps, and checks the columns it writes exist first.
#
# Usage:
#   split_library.py prepare --library DIR --books DIR --state FILE
#   split_library.py enable --books-dir DIR [--db PATH]
#   split_library.py disable [--db PATH]

import argparse
import os
import pathlib
import shutil
import sqlite3
import sys

DEFAULT_DB = "/config/app.db"
METADATA_DB = "metadata.db"
# What the share's copy is renamed to once it has been brought over.
PRE_SPLIT_SUFFIX = ".pre-split"
# Files SQLite keeps next to a database. -shm is never copied: SQLite rebuilds
# it, and a stale one is harmful.
SIDE_FILES = ("-wal", "-shm", "-journal")
STAGING_NAME = ".cwa-split-import"
REQUIRED_SETTINGS_COLS = {"config_calibre_split", "config_calibre_split_dir"}


class SplitError(Exception):
    """A problem that must stop startup."""


def log(msg):
    print(f"[cwa-split-library] {msg}", flush=True)


def remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def read_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip() or None
    except FileNotFoundError:
        return None


def write_state(path, books_dir):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(f"{books_dir}\n")
    os.replace(tmp, path)


def connect_existing(path, timeout=30):
    """Open the existing database at path, never creating it. The path is
    percent-encoded into the URI: a raw '#', '?' or '%' in a folder name would
    otherwise end the path early (and drop mode=rw, so SQLite would create a
    stray empty file there) or decode to another name."""
    uri = pathlib.Path(os.path.abspath(path)).as_uri() + "?mode=rw"
    return sqlite3.connect(uri, uri=True, timeout=timeout)


def count_books(path):
    """Number of books in the Calibre database at path."""
    con = connect_existing(path)
    try:
        if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise SplitError(f"{path} is damaged (PRAGMA quick_check failed)")
        try:
            return con.execute("SELECT count(*) FROM books").fetchone()[0]
        except sqlite3.OperationalError as exc:
            raise SplitError(f"{path} is not a Calibre library database: {exc}")
    finally:
        con.close()


def stage(source, staging_dir):
    """Copy the database at source, with its journal or WAL, into staging_dir
    and fold the journal into it. Returns (path of the copy, its book count).

    The copy, not the original, is opened: SQLite would otherwise write a
    -shm file onto the share, and recover a hot journal there."""
    os.makedirs(staging_dir, exist_ok=True)
    staged = os.path.join(staging_dir, METADATA_DB)
    shutil.copyfile(source, staged)
    for side in ("-wal", "-journal"):
        if os.path.exists(source + side):
            shutil.copyfile(source + side, staged + side)
    books = count_books(staged)
    con = sqlite3.connect(staged)
    try:
        # Checkpoint any WAL into the file and leave a single, self-contained
        # database. CWA picks its own journal mode when it opens it.
        con.execute("PRAGMA journal_mode=DELETE")
    finally:
        con.close()
    for side in SIDE_FILES:
        remove(staged + side)
    return staged, books


def set_aside(path):
    """Rename database path (and its side files) to <path>.pre-split, without
    overwriting an earlier one. Returns the new name, or None on failure."""
    target = path + PRE_SPLIT_SUFFIX
    n = 1
    while os.path.lexists(target):
        n += 1
        target = f"{path}{PRE_SPLIT_SUFFIX}.{n}"
    try:
        os.rename(path, target)
        for side in ("-wal", "-journal"):
            if os.path.exists(path + side):
                os.rename(path + side, target + side)
        remove(path + "-shm")
    except OSError as exc:
        log(f"WARNING: could not rename {path} to {target}: {exc}. "
            "It is no longer used; delete it so it is not mistaken for the "
            "live database.")
        return None
    return target


def book_folders(directory):
    """Visible subdirectories of directory: what Calibre's book folders look
    like (one per author)."""
    try:
        return sorted(
            entry.name for entry in os.scandir(directory)
            if entry.is_dir() and not entry.name.startswith(".")
        )
    except FileNotFoundError:
        return []


def chown(path, uid, gid):
    if os.geteuid() != 0:
        return
    try:
        os.chown(path, uid, gid)
    except OSError as exc:
        log(f"WARNING: could not chown {path}: {exc}")


def prepare(library_dir, books_dir, state_path, uid=1000, gid=1000):
    books_dir = os.path.normpath(books_dir)
    if read_state(state_path) == books_dir:
        return "unchanged"

    local = os.path.join(library_dir, METADATA_DB)
    shared = os.path.join(books_dir, METADATA_DB)
    staging = os.path.join(library_dir, STAGING_NAME)
    outcome = None
    shutil.rmtree(staging, ignore_errors=True)
    try:
        local_books = count_books(local) if os.path.exists(local) else None
        if os.path.exists(shared):
            try:
                staged, shared_books = stage(shared, staging)
            except (OSError, sqlite3.Error) as exc:
                raise SplitError(f"could not read {shared}: {exc}")
            if local_books and shared_books:
                raise SplitError(
                    f"both {local} ({local_books} books) and {shared} "
                    f"({shared_books} books) hold a library, and it is not "
                    "clear which one CWA should use. Keep the one you want: "
                    f"rename or delete the other (if {shared} is the add-on's "
                    "own metadata_db_export copy, delete that one), then "
                    "restart.")
            if local_books:
                log(f"{shared} holds no books; keeping {local}")
                outcome = "kept-local"
            else:
                if local_books == 0:
                    log(f"replacing the empty library in {local}")
                    set_aside(local)
                os.replace(staged, local)
                chown(local, uid, gid)
                log(f"moved the library database from {shared} to {local} "
                    f"({shared_books} books)")
                outcome = "imported"
            renamed = set_aside(shared)
            if renamed:
                log(f"the copy left in books_path is now {renamed} and is no "
                    "longer used")
        else:
            outcome = "kept-local" if local_books is not None else "new"
            if local_books is None and book_folders(books_dir):
                log(f"WARNING: {books_dir} has folders but no {METADATA_DB}, "
                    f"and {library_dir} has none either: CWA starts a new, "
                    "empty library. Put the library's metadata.db in "
                    "library_path to use the books already there.")
        if outcome == "kept-local" and book_folders(library_dir):
            log(f"WARNING: {library_dir} still has folders "
                f"({', '.join(book_folders(library_dir)[:3])}, ...). With "
                "books_path set, CWA looks for book files only in "
                f"{books_dir}: move the book folders there.")
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    write_state(state_path, books_dir)
    return outcome


def open_app_db(db):
    # mode=rw: never create the file (see setup_access.py).
    return connect_existing(db)


def table_cols(con, table):
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def enable(con, books_dir):
    cols = table_cols(con, "settings")
    missing = REQUIRED_SETTINGS_COLS - cols
    if missing:
        log(f"settings table is missing columns {sorted(missing)} — cannot "
            "enable split library mode (upstream schema changed?)")
        return 1
    cur = con.execute(
        "UPDATE settings SET config_calibre_split = 1, "
        "config_calibre_split_dir = ?",
        (books_dir,),
    )
    if cur.rowcount < 1:
        log("settings table has no row yet — cannot enable split library mode")
        return 1
    con.commit()
    log(f"split library mode enabled: book files in {books_dir}")
    if "config_calibre_server_enabled" in cols:
        row = con.execute(
            "SELECT config_calibre_server_enabled FROM settings LIMIT 1"
        ).fetchone()
        if row and row[0]:
            log("WARNING: the Calibre content server does not support split "
                "library mode and will not start. Disable it in CWA's admin "
                "settings, or clear books_path.")
    return 0


def disable(con):
    if "config_calibre_split" not in table_cols(con, "settings"):
        log("settings table has no split library column — nothing to disable")
        return 0
    con.execute("UPDATE settings SET config_calibre_split = 0")
    con.commit()
    log("split library mode disabled")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--library", required=True)
    p.add_argument("--books", required=True)
    p.add_argument("--state", required=True)
    e = sub.add_parser("enable")
    e.add_argument("--books-dir", required=True)
    e.add_argument("--db", default=DEFAULT_DB)
    d = sub.add_parser("disable")
    d.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args(argv)

    if args.action == "prepare":
        try:
            prepare(
                args.library, args.books, args.state,
                int(os.environ.get("PUID", "1000")),
                int(os.environ.get("PGID", "1000")),
            )
        except (SplitError, OSError, sqlite3.Error) as exc:
            log(f"ERROR: {exc}")
            return 1
        return 0

    try:
        con = open_app_db(args.db)
    except sqlite3.Error as exc:
        log(f"cannot open {args.db}: {exc}")
        return 1
    try:
        if args.action == "enable":
            return enable(con, args.books_dir)
        return disable(con)
    except sqlite3.Error as exc:
        log(f"database error on {args.db}: {exc}")
        return 1
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
