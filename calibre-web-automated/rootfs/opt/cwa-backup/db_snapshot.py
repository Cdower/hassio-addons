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
#            The snapshots made are listed, last of all, in
#            "<first root>/.cwa-backup-snapshots".
#   discard  (config.yaml `backup_post`) delete the listed snapshots and the
#            list.
#   restore  (add-on start, before CWA runs) if the list is present, the
#            add-on is starting from a restored backup: put each listed
#            snapshot in place of its database, which may be the torn copy.
#            Without the list it returns at once, so a normal start never
#            walks the library.
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
# Written once every snapshot is in place, so a list always names a complete
# set. Lives in the first root (/data), which is in every backup.
LIST_NAME = ".cwa-backup-snapshots"


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


def scan(roots):
    """One walk of the roots: (SQLite databases, snapshot and temp files)."""
    databases, snapshots = [], []
    for path in walk_files(roots):
        if path.endswith((SUFFIX, TMP_SUFFIX)):
            snapshots.append(path)
        elif path.endswith(".db") and not os.path.islink(path) and is_sqlite(path):
            databases.append(path)
    return databases, snapshots


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
    try:
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
    except BaseException:
        remove(tmp)
        raise
    return target


def list_path(roots):
    return os.path.join(roots[0], LIST_NAME)


def write_list(roots, snapshots):
    path = list_path(roots)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for snap in snapshots:
            fh.write(f"{snap}\n")
    os.replace(tmp, path)


def read_list(roots):
    """Listed snapshots, or None when there is no list."""
    try:
        with open(list_path(roots), encoding="utf-8") as fh:
            entries = [line.rstrip("\n") for line in fh if line.strip()]
    except FileNotFoundError:
        return None
    # The list comes from a backup: only act on snapshot files inside a root.
    real_roots = [os.path.realpath(root) for root in roots]
    valid = []
    for entry in entries:
        real = os.path.realpath(entry)
        if entry.endswith(SUFFIX) and any(
            os.path.commonpath([real, root]) == root for root in real_roots
        ):
            valid.append(entry)
        else:
            log(f"ignoring unexpected entry in snapshot list: {entry!r}")
    return valid


def remove_list(roots):
    remove(list_path(roots))
    remove(list_path(roots) + ".tmp")


def discard(roots):
    """Delete the listed snapshots and the list; return how many."""
    listed = read_list(roots) or []
    for path in listed:
        remove(path)
    remove_list(roots)
    return len(listed)


def create(roots):
    databases, leftovers = scan(roots)
    # Leftovers from an interrupted run must not end up in this backup.
    remove_list(roots)
    for path in leftovers:
        remove(path)
    made = []
    try:
        for path in databases:
            made.append(snapshot(path))
        write_list(roots, made)
    except BaseException:
        # A half-made set must not survive: on the next start it would roll
        # back the databases that did get a snapshot.
        for path in made:
            remove(path)
        remove_list(roots)
        raise
    return made


def restore(roots):
    listed = read_list(roots)
    if listed is None:
        return []
    restored = []
    for snap in listed:
        if not os.path.isfile(snap):
            log(f"listed snapshot {snap} is missing; leaving its database as is")
            continue
        db = snap[: -len(SUFFIX)]
        for side in SIDE_FILES:
            remove(db + side)
        os.replace(snap, db)
        restored.append(db)
    remove_list(roots)
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
