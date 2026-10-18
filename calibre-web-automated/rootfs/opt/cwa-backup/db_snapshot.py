# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
#
# Consistent SQLite copies for Home Assistant add-on backups.
#
# The Supervisor backs an add-on up by tarring its /data and addon_config
# folders while the add-on keeps running. It knows nothing about SQLite, so a
# database being written during the tar (or one in WAL mode, whose recent
# changes sit in a separate -wal file) can land in the backup torn. CWA keeps
# app.db, cwa.db and the Calibre library's metadata.db in those folders.
#
#   create   (config.yaml `backup_pre`)  copy every SQLite *.db under the
#            roots to "<name>.db.cwa-snapshot" with SQLite's online backup
#            API, which yields a consistent copy of a live database.
#   discard  (config.yaml `backup_post`) delete the snapshots again.
#   restore  (add-on start, before CWA runs) if snapshots are present, the
#            add-on is starting from a restored backup: put each snapshot in
#            place of its database, which may be the torn copy.
#
# The live databases are deliberately NOT excluded from the backup: when the
# add-on is stopped the Supervisor skips `backup_pre`, so no snapshots exist
# and the (then consistent) live files are the only copy.
#
# A snapshot only survives outside a backup if the add-on stops between
# `backup_pre` and `backup_post`; the next start then rolls those databases
# back to the moment the backup began, losing at most the changes made while
# it ran.
#
# Usage:
#   db_snapshot.py {create,discard,restore} [ROOT ...]
# ROOTs default to /data and /addon_config; missing roots are skipped.

import argparse
import os
import sqlite3
import sys

DEFAULT_ROOTS = ("/data", "/addon_config")
SUFFIX = ".cwa-snapshot"
TMP_SUFFIX = SUFFIX + ".tmp"
SQLITE_HEADER = b"SQLite format 3\x00"
# Files SQLite keeps next to a database; stale ones must not be applied to a
# restored snapshot.
SIDE_FILES = ("-wal", "-shm", "-journal")


def log(msg):
    print(f"[cwa-db-snapshot] {msg}", flush=True)


def walk_files(roots):
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for name in sorted(filenames):
                yield os.path.join(dirpath, name)


def is_sqlite(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


def find_databases(roots):
    return [
        path for path in walk_files(roots)
        if path.endswith(".db") and not os.path.islink(path) and is_sqlite(path)
    ]


def find_snapshots(roots, suffix=SUFFIX):
    return [path for path in walk_files(roots) if path.endswith(suffix)]


def remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def drop_privileges():
    # Opening a WAL database can create its -wal/-shm files. Created by root,
    # CWA (running as PUID:PGID) could no longer write them, so do the work as
    # that user. The snapshots then also carry the right owner.
    if os.geteuid() != 0:
        return
    uid = int(os.environ.get("PUID", "1000"))
    gid = int(os.environ.get("PGID", "1000"))
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)


def snapshot(path):
    target = path + SUFFIX
    tmp = path + TMP_SUFFIX
    remove(tmp)
    # Not opened read-only: a WAL database whose -shm file is gone (SQLite
    # removes it when the last connection closes) cannot be read that way.
    # Reading never modifies the database.
    src = sqlite3.connect(path, timeout=60)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    os.replace(tmp, target)
    return target


def discard(roots):
    removed = 0
    for path in find_snapshots(roots) + find_snapshots(roots, TMP_SUFFIX):
        remove(path)
        removed += 1
    return removed


def create(roots):
    # Leftovers from an interrupted run must not end up in this backup.
    discard(roots)
    made = []
    try:
        for path in find_databases(roots):
            made.append(snapshot(path))
    except BaseException:
        # A half-made set must not survive: on the next start it would roll
        # back the databases that did get a snapshot.
        for path in made:
            remove(path)
        discard(roots)
        raise
    return made


def restore(roots):
    restored = []
    for snap in find_snapshots(roots):
        db = snap[: -len(SUFFIX)]
        for side in SIDE_FILES:
            remove(db + side)
        os.replace(snap, db)
        restored.append(db)
    for tmp in find_snapshots(roots, TMP_SUFFIX):
        remove(tmp)
    return restored


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "discard", "restore"))
    parser.add_argument("roots", nargs="*", default=list(DEFAULT_ROOTS))
    args = parser.parse_args(argv)

    if args.action == "create":
        drop_privileges()
        try:
            made = create(args.roots)
        except (sqlite3.Error, OSError) as err:
            log(f"snapshot failed, backup aborted: {err}")
            return 1
        log(f"snapshotted {len(made)} database(s) for backup")
    elif args.action == "discard":
        log(f"removed {discard(args.roots)} backup snapshot(s)")
    else:
        for db in restore(args.roots):
            log(f"restored {db} from its backup snapshot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
