# SPDX-License-Identifier: MIT
#
# One-way export of the local metadata.db into `books_path` (the
# `metadata_db_export` option), so the folder on the NAS stays a complete
# Calibre library: NAS backups capture the database with the books, and
# Calibre desktop can open the folder (read-only: the next export replaces
# whatever it changed).
#
# Runs as a longrun next to CWA. Every --interval seconds it looks at
# metadata.db and its -wal file; once they have changed and then stayed
# unchanged for --settle seconds (or --max-delay seconds have passed since
# the first unexported change, so a busy library is still exported), it
# writes a fresh copy:
#
#   1. SQLite's online backup API copies the live database to a local
#      temporary file (consistent, without blocking CWA), switched to the
#      rollback journal so the copy is a single file that is safe to open
#      on a network share.
#   2. That file is copied next to the target and renamed over
#      <books_path>/metadata.db, so readers never see a half-written file.
#
# Never the other way round: the local database is always the live one.
# On SIGTERM (add-on stop) it makes a last export if anything changed, so
# the copy on the share is current once the add-on has stopped.
#
# Usage:
#   metadata_export.py --source DB --target-dir DIR
#                      [--interval S] [--settle S] [--max-delay S]
#                      [--tmp-dir DIR]

import argparse
import contextlib
import os
import pathlib
import shutil
import signal
import sqlite3
import sys
import tempfile
import threading
import time

METADATA_DB = "metadata.db"
TMP_NAME = ".metadata.db.cwa-export.tmp"
SIDE_FILES = ("-wal", "-shm", "-journal")


def log(msg):
    print(f"[cwa-metadata-export] {msg}", flush=True)


def remove(path):
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)


def file_signature(path):
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_size)


def header(path):
    """SQLite's 100-byte file header. Its file change counter (bytes 24-27)
    moves on every write another program makes in rollback-journal mode, and
    switching to WAL changes bytes 18-19. Unlike mtime, which network shares
    report with varying precision, it reads back exactly as written."""
    try:
        with open(path, "rb") as fh:
            return fh.read(100)
    except FileNotFoundError:
        return None


def db_signature(path):
    """Changes whenever the database at path does: CWA's writes land in the
    -wal file first, checkpoints in the database file."""
    return (file_signature(path), file_signature(path + "-wal"))


class Schedule:
    """Decides when a change is due for export. Times are in seconds."""

    def __init__(self, settle, max_delay):
        self.settle = settle
        self.max_delay = max_delay
        # None: nothing exported yet, so the first look exports at once.
        self.exported = None
        self.seen = None
        self.changed_at = None
        self.pending_since = None

    def due(self, signature, now):
        if self.exported is None:
            return True
        if signature == self.exported:
            # Forget the reverted change too, so if it comes back it waits
            # the full settle time again.
            self.seen = signature
            self.pending_since = None
            return False
        if signature != self.seen:
            self.seen = signature
            self.changed_at = now
        if self.pending_since is None:
            self.pending_since = now
        return (now - self.changed_at >= self.settle
                or now - self.pending_since >= self.max_delay)

    def done(self, signature):
        """signature: what the database looked like when the export began,
        so a change made during the export is picked up by the next one."""
        self.exported = signature
        self.seen = signature
        self.pending_since = None

    def pending(self, signature):
        return signature != self.exported


class Exporter:
    def __init__(self, source, target_dir, tmp_dir=None):
        self.source = source
        self.target = os.path.join(target_dir, METADATA_DB)
        self.target_tmp = os.path.join(target_dir, TMP_NAME)
        self.tmp_dir = tmp_dir
        # The target's header and size after our last export, to notice
        # something else writing to it.
        self.written = None

    def snapshot(self, path):
        uri = pathlib.Path(os.path.abspath(self.source)).as_uri() + "?mode=rw"
        src = sqlite3.connect(uri, uri=True, timeout=60)
        try:
            # Closing the last connection to a WAL database checkpoints it and
            # deletes the -wal file, which changes db_signature() and would
            # trigger a second, identical export. A reader has no business
            # checkpointing CWA's database, so don't.
            no_ckpt = getattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE", None)
            if no_ckpt is not None:
                src.setconfig(no_ckpt, True)
            dst = sqlite3.connect(path)
            try:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
            finally:
                dst.close()
        finally:
            src.close()

    def export(self):
        if self.written is not None and self.target_state() != self.written:
            log(f"WARNING: {self.target} was changed by something other than "
                "this add-on; replacing it. It is a read-only copy: make "
                "changes in CWA.")
        fd, local_tmp = tempfile.mkstemp(
            prefix="metadata-export-", suffix=".db", dir=self.tmp_dir)
        os.close(fd)
        try:
            self.snapshot(local_tmp)
            try:
                shutil.copyfile(local_tmp, self.target_tmp)
                with open(self.target_tmp, "rb+") as fh:
                    os.fsync(fh.fileno())
                # A -wal or journal left next to the old copy would be applied
                # to the new one by the next reader.
                for side in SIDE_FILES:
                    remove(self.target + side)
                os.replace(self.target_tmp, self.target)
            except BaseException:
                remove(self.target_tmp)
                raise
        finally:
            remove(local_tmp)
        self.written = self.target_state()

    def target_state(self):
        try:
            size = os.path.getsize(self.target)
        except FileNotFoundError:
            return None
        return (header(self.target), size)


def run(exporter, schedule, interval, stop, clock=time.monotonic):
    def attempt(signature):
        try:
            exporter.export()
        except (sqlite3.Error, OSError) as exc:
            log(f"export to {exporter.target} failed, will retry: {exc}")
            return False
        schedule.done(signature)
        return True

    waiting = False
    while True:
        signature = db_signature(exporter.source)
        if signature[0] is None:
            if not waiting:
                log(f"{exporter.source} does not exist yet; waiting for it")
            waiting = True
        else:
            waiting = False
            if schedule.due(signature, clock()) and attempt(signature):
                log(f"exported {exporter.source} to {exporter.target}")
        if stop.wait(interval):
            break

    signature = db_signature(exporter.source)
    if signature[0] is not None and schedule.pending(signature) and attempt(signature):
        log(f"final export to {exporter.target} done")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--settle", type=float, default=60)
    parser.add_argument("--max-delay", type=float, default=600)
    parser.add_argument("--tmp-dir", default=None)
    args = parser.parse_args(argv)

    # Take SIGTERM/SIGINT in a thread of their own rather than in a signal
    # handler: Event.set() takes the Event's non-reentrant lock, which the
    # main thread briefly holds inside stop.wait(), so setting it from a
    # handler can deadlock -- and s6 would then kill the process without the
    # final export.
    stop = threading.Event()
    stop_signals = {signal.SIGTERM, signal.SIGINT}
    signal.pthread_sigmask(signal.SIG_BLOCK, stop_signals)

    def wait_for_stop_signal():
        signal.sigwait(stop_signals)
        stop.set()

    threading.Thread(target=wait_for_stop_signal, daemon=True).start()

    log(f"exporting {args.source} to {args.target_dir} after each change "
        f"(checked every {args.interval:g}s)")
    run(
        Exporter(args.source, args.target_dir, args.tmp_dir),
        Schedule(args.settle, args.max_delay),
        args.interval,
        stop,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
