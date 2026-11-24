"""Report what changed upstream between two calibre-web-nextgen tags that the
calibre-web-automated add-on overrides or depends on.

Usage: base-image-drift.py UPSTREAM_DIR OLD_TAG NEW_TAG REPORT

UPSTREAM_DIR is a git repository holding both tags (a depth-1 fetch of each is
enough: only their trees are compared); UPSTREAM in the environment is its
GitHub URL, for links. Writes a Markdown report to REPORT, and `drift=` (true
or false) and `refresh=` (the NOTES files whose upstream files all stayed
unchanged, space-separated) to $GITHUB_OUTPUT, or stdout. Used by
.github/workflows/base-image.yaml.

WATCHED mirrors steps 3 and 4 of .claude/skills/update-base-image/SKILL.md;
keep the two in step, and NOTES in step with the add-on's "verified against"
comments. A change here does not mean the add-on breaks, only that the bump
needs that skill's review before it is merged.
"""

import os
import subprocess
import sys

WATCHED = {
    "root/": "s6 services. `svc-calibre-web-automated/run` is overridden by the"
    " add-on (`-i $CWA_BIND_ADDRESS`), `cwa-init` and"
    " `cwa-auto-library` are dependencies of the add-on's oneshots,"
    " and a new service may need AppArmor rules",
    "Dockerfile": "the `/lsiopy` venv the add-on installs PyJWT (pyproject.toml / uv.lock) into",
    "pyproject.toml": "`cryptography` and `werkzeug` in `/lsiopy`",
    "cps/cli.py": "the `-i` bind-address flag",
    "cps/constants.py": "`CWA_PORT_OVERRIDE`",
    "cps/__init__.py": "`TRUSTED_PROXY_COUNT` / ProxyFix",
    "cps/config_sql.py": "reverse-proxy header login and split library settings the add-on writes",
    "cps/usermanagement.py": "new-user defaults `setup_access.py` mirrors",
    "cps/ub.py": "`user` / `settings` schema and migrations"
    " `setup_access.py` and its test fixtures follow",
    "cps/search_metadata.py": "metadata provider discovery `install_providers.py` relies on",
    "cps/services/Metadata.py": "the contract the add-on's arXiv provider implements",
    "cps/metadata_provider/arxiv.py": "fully replaced by the add-on's own"
    " arXiv provider, which would drop"
    " upstream's changes",
    "cps/content_server.py": "split library mode support",
    "scripts/ingest_processor.py": "split library mode in ingest",
    "scripts/auto_library.py": "must only look for metadata.db under `/calibre-library`",
}

DATABASE = r"/config/[A-Za-z0-9_./-]*\.(db|sqlite[0-9]?)"

# Add-on files (relative to the add-on) that name the upstream tag they were
# last verified against, and the WATCHED paths that verification covers. Each
# note moves to the new tag only when none of its paths changed.
NOTES = {
    "rootfs/etc/s6-overlay/s6-rc.d/svc-calibre-web-automated/run": ["root/"],
    "rootfs/opt/cwa-access/setup_access.py": ["cps/usermanagement.py"],
    "tests/test_arxiv.py": ["cps/services/Metadata.py", "Dockerfile"],
}


def git(*args, ok=(0,)):
    result = subprocess.run(
        ["git", "-C", upstream, *args],
        capture_output=True,
        text=True,
    )
    if result.returncode not in ok:
        sys.exit(f"::error::git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def databases(tag):
    # git grep exits 1 when nothing matches, which is not an error here.
    return set(
        git("grep", "-ohE", DATABASE, tag, "--", "cps", "scripts", "root", ok=(0, 1)).split()
    )


upstream, old, new, report = sys.argv[1:5]

unwatched = {path for paths in NOTES.values() for path in paths} - WATCHED.keys()
if unwatched:
    sys.exit(f"::error::NOTES covers paths missing from WATCHED: {sorted(unwatched)}")

findings = []
changed = set()
for path, why in WATCHED.items():
    stat = git("diff", "--shortstat", old, new, "--", path).strip()
    if stat:
        changed.add(path)
        findings.append(f"`{path}` ({stat}): {why}.")

added = git(
    "diff",
    "--name-only",
    "--diff-filter=A",
    old,
    new,
    "--",
    "cps/metadata_provider/",
).split()
if added:
    names = ", ".join(f"`{os.path.basename(name)}`" for name in added)
    findings.append(
        f"New built-in metadata providers: {names}. Check none clashes with a"
        " name users are likely to have used for a custom provider file."
    )

new_databases = sorted(databases(new) - databases(old))
if new_databases:
    names = ", ".join(f"`{name}`" for name in new_databases)
    findings.append(
        f"New databases under `/config`: {names}. Backups only snapshot"
        " `*.db` safely (`rootfs/opt/cwa-backup/db_snapshot.py`)."
    )

refresh = [note for note, paths in NOTES.items() if not changed & set(paths)]
kept = [note for note in NOTES if note not in refresh]

compare = f"{os.environ['UPSTREAM']}/compare/{old}...{new}"
with open(report, "w", encoding="utf-8") as handle:
    if findings:
        handle.write(
            f"Upstream changed files the add-on overrides or depends on"
            f" ([{old}...{new}]({compare})):\n\n"
        )
        handle.writelines(f"- {finding}\n" for finding in findings)
        handle.write(
            "\nBefore merging, re-diff and re-verify these as described in"
            " `.claude/skills/update-base-image/SKILL.md` (for example, ask"
            " Claude to run `/update-base-image` on this branch).\n"
        )
    else:
        handle.write(
            f"None of the upstream files the add-on overrides or depends on"
            f" changed ([{old}...{new}]({compare})), so the overrides carry"
            f" over unchanged.\n"
        )
    if refresh:
        handle.write(
            f'\nThe "verified against" notes in {", ".join(f"`{n}`" for n in refresh)}'
            f" were moved to {new}: what they cover did not change.\n"
        )
    if kept:
        handle.write(
            f'\nThe "verified against" notes in {", ".join(f"`{n}`" for n in kept)}'
            f" still name {old}, for the review to move.\n"
        )

lines = f"drift={'true' if findings else 'false'}\nrefresh={' '.join(refresh)}\n"
output = os.environ.get("GITHUB_OUTPUT")
if output:
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(lines)
else:
    sys.stdout.write(lines)
