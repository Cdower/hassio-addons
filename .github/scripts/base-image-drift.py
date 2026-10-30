"""Report what changed upstream between two calibre-web-nextgen tags that the
calibre-web-automated add-on overrides or depends on.

Usage: base-image-drift.py UPSTREAM_DIR OLD_TAG NEW_TAG REPORT

UPSTREAM_DIR is a git repository holding both tags (a depth-1 fetch of each is
enough: only their trees are compared). Writes a Markdown report to REPORT and
`drift=true|false` to $GITHUB_OUTPUT (or stdout). Used by
.github/workflows/base-image.yaml.

WATCHED mirrors steps 3 and 4 of .claude/skills/update-base-image/SKILL.md;
keep the two in step. A change here does not mean the add-on breaks, only
that the bump needs that skill's review before it is merged.
"""
import os
import re
import subprocess
import sys

UPSTREAM_URL = "https://github.com/new-usemame/calibre-web-nextgen"

WATCHED = {
    "root/": "s6 services. `svc-calibre-web-automated/run` is overridden by the"
             " add-on (`-i $CWA_BIND_ADDRESS`), `cwa-init` and"
             " `cwa-auto-library` are dependencies of the add-on's oneshots,"
             " and a new service may need AppArmor rules",
    "Dockerfile": "the `/lsiopy` venv the add-on pip-installs PyJWT into",
    "pyproject.toml": "`cryptography` and `werkzeug` in `/lsiopy`",
    "cps/cli.py": "the `-i` bind-address flag",
    "cps/constants.py": "`CWA_PORT_OVERRIDE`",
    "cps/__init__.py": "`TRUSTED_PROXY_COUNT` / ProxyFix",
    "cps/config_sql.py": "reverse-proxy header login and split library"
                         " settings the add-on writes",
    "cps/usermanagement.py": "new-user defaults `setup_access.py` mirrors",
    "cps/ub.py": "`user` / `settings` schema and migrations"
                 " `setup_access.py` and its test fixtures follow",
    "cps/search_metadata.py": "metadata provider discovery"
                              " `install_providers.py` relies on",
    "cps/services/Metadata.py": "the contract the add-on's arXiv provider"
                                " implements",
    "cps/metadata_provider/arxiv.py": "fully replaced by the add-on's own"
                                      " arXiv provider, which would drop"
                                      " upstream's changes",
    "cps/content_server.py": "split library mode support",
    "scripts/ingest_processor.py": "split library mode in ingest",
    "scripts/auto_library.py": "must only look for metadata.db under"
                               " `/calibre-library`",
}

DATABASE = r"/config/[A-Za-z0-9_./-]*\.(db|sqlite[0-9]?)"


def git(*args):
    result = subprocess.run(
        ["git", "-C", upstream, *args], capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(f"::error::git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def databases(tag):
    # git grep exits 1 when nothing matches, which is not an error here.
    found = subprocess.run(
        ["git", "-C", upstream, "grep", "-ohE", DATABASE, tag, "--",
         "cps", "scripts", "root"],
        capture_output=True, text=True,
    )
    if found.returncode not in (0, 1):
        sys.exit(f"::error::git grep failed: {found.stderr.strip()}")
    return set(found.stdout.split())


upstream, old, new, report = sys.argv[1:5]

findings = []
for path, why in WATCHED.items():
    stat = git("diff", "--shortstat", old, new, "--", path).strip()
    if stat:
        findings.append(f"`{path}` ({stat}): {why}.")

added = git(
    "diff", "--name-only", "--diff-filter=A", old, new,
    "--", "cps/metadata_provider/",
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

compare = f"{UPSTREAM_URL}/compare/{old}...{new}"
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
            " Claude to run `/update-base-image` on this branch). The"
            " \"verified against\" version references in the add-on's"
            " comments were left at the previous tag for that review to"
            " move.\n"
        )
    else:
        handle.write(
            f"None of the upstream files the add-on overrides or depends on"
            f" changed ([{old}...{new}]({compare})), so the overrides carry"
            f" over unchanged and the \"verified against\" version references"
            f" in the add-on's comments were moved to {new}.\n"
        )

line = f"drift={'true' if findings else 'false'}\n"
output = os.environ.get("GITHUB_OUTPUT")
if output:
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(line)
else:
    sys.stdout.write(line)
