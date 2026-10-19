# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
#
# Install user-supplied Calibre-Web metadata providers next to the built-in
# ones, without ever replacing a built-in.
#
# Upstream discovers providers by importing every file in
# cps/metadata_provider/ (cps/search_metadata.py), so installing one is just
# copying a .py file in. The image's own providers (and the add-on's arxiv.py
# overlay) live in the same directory, so a custom file that shares a name with
# one of them is skipped instead of copied: built-ins are never overwritten.
#
# Files this script installed are recorded in a manifest. On the next run they
# are removed first, so deleting a provider from the source folder uninstalls
# it, and a provider we installed is never mistaken for a built-in.
#
# Runs as root from a pre-start oneshot. Copies are root-owned 0644, so CWA
# (running as `abc`) can import them but not rewrite them.
#
# Usage:
#   install_providers.py [--source DIR] [--dest DIR] [--manifest FILE]
#
# Without --source, only the previously installed providers are removed.

import argparse
import os
import re
import shutil
import sys
import tempfile

DEFAULT_DEST = "/app/calibre-web-automated/cps/metadata_provider"
# Kept in the container's writable layer, like DEFAULT_DEST, so both share a
# lifetime. On /run (a tmpfs) it would vanish on a container restart while the
# installed files stayed, and they would then be mistaken for built-ins.
DEFAULT_MANIFEST = "/var/lib/cwa-metadata-providers/manifest"

# Must be importable as cps.metadata_provider.<stem>.
MODULE_FILE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.py$")


def log(msg):
    print(f"[cwa-metadata-providers] {msg}", flush=True)


def remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def read_manifest(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return {line.strip() for line in fh if line.strip()}
    except FileNotFoundError:
        return set()


def write_manifest(path, names):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for name in sorted(names):
            fh.write(f"{name}\n")


def remove_previous(dest, manifest_names):
    for name in sorted(manifest_names):
        # The manifest is ours, but never follow it outside dest.
        if os.path.basename(name) == name:
            remove(os.path.join(dest, name))


def taken_stems(dest):
    """Module names already provided by the image (files or packages)."""
    stems = set()
    for entry in os.listdir(dest):
        if entry.endswith(".py"):
            stems.add(entry[:-3])
        elif os.path.isdir(os.path.join(dest, entry)):
            stems.add(entry)
    return stems


def copy_into(src, dest_dir, name):
    # Write to a temp file in the same directory, then rename, so CWA never
    # sees a half-written module.
    fd, tmp = tempfile.mkstemp(dir=dest_dir, prefix=".install-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
            shutil.copyfileobj(inp, out)
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(dest_dir, name))
    except BaseException:
        remove(tmp)
        raise


def install(source, dest, manifest):
    """Install providers from source into dest; return the installed names."""
    previous = read_manifest(manifest)
    if previous:
        remove_previous(dest, previous)
        # Record the removal before installing anything, so a failure part-way
        # through cannot leave a stale manifest naming files that are now gone.
        write_manifest(manifest, set())

    if source is None:
        return []

    taken = taken_stems(dest)
    installed = []
    for name in sorted(os.listdir(source)):
        path = os.path.join(source, name)
        # Dotfiles include macOS `._foo.py` resource forks that SMB shares
        # collect; they are never providers, so skip them without noise.
        if name.startswith(".") or not os.path.isfile(path):
            continue
        if not name.endswith(".py"):
            log(f"ignoring {name}: not a .py file")
            continue
        if name == "__init__.py" or not MODULE_FILE_RE.match(name):
            log(f"skipping {name}: not a valid Python module name")
            continue
        if name[:-3] in taken:
            log(f"skipping {name}: a built-in provider with that name "
                "already exists and is never overwritten — rename the file")
            continue
        try:
            copy_into(path, dest, name)
        except OSError as err:
            log(f"could not install {name}: {err}")
            continue
        installed.append(name)
        # Record each file as soon as it lands so the manifest always covers
        # everything we put in dest.
        write_manifest(manifest, installed)
    return installed


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source")
    parser.add_argument("--dest", default=DEFAULT_DEST)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    if args.source is not None and not os.path.isdir(args.source):
        log(f"source {args.source} is not a directory")
        return 1

    installed = install(args.source, args.dest, args.manifest)
    if args.source is None:
        return 0
    if installed:
        log(f"installed {len(installed)} custom provider(s): "
            + ", ".join(installed))
    else:
        log(f"no custom providers found in {args.source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
