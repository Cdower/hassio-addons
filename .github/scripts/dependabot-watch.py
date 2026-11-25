"""Check Dependabot's recent update runs against .github/dependabot.yml.

Usage: dependabot-watch.py CONFIG PREVIOUS RUNS

CONFIG is .github/dependabot.yml as JSON; PREVIOUS is the same file as it
stood at the start of the window, as JSON (`{}` if it did not exist yet).
RUNS lists Dependabot's completed update runs in the window, newest first,
one `name<TAB>conclusion<TAB>url` per line. Exits non-zero, with one GitHub
error annotation each, when the latest run of an update failed, when an
update in CONFIG has no run in the window, or when there are no runs at all.
Writes a table of every update to $GITHUB_STEP_SUMMARY, or stdout. Used by
.github/workflows/dependabot-watch.yaml.

How Dependabot names its runs, as seen in this repository's run list:
"<ecosystem> in <directory> - Update #<id>", where <ecosystem> is the
updater's name (`github_actions`, not the config's `github-actions`) and the
root directory is `/.`. A security update or a rebase of one PR adds
" for <packages>" after the directory and writes the root as `/`. A grouped
entry is named the same way; the group name does not appear. How an entry
with `directories:` is named had not been seen when this was written: it is
taken to be the directories joined with ", " in one run, or one run per
directory, and the entry counts as having run only once every one of its
directories has. An entry whose runs are named some other way is reported
as not running, which is loud rather than silent; fix the matching here.
"""

import fnmatch
import json
import os
import re
import sys

FAILED = {"failure", "timed_out", "startup_failure"}
# Only these schedules are sure to run inside the workflow's 8-day window.
CHECKED_INTERVALS = {"daily", "weekly"}


def ecosystem(name: str) -> str:
    """Return the updater name Dependabot puts in a run's name."""
    return name.strip().replace("-", "_")


def directory(path: str) -> str:
    """Return one spelling of a directory: `/.`, `/` and `/x/` are `/` and `/x`."""
    path = path.strip()
    if path.endswith("/."):
        path = path[:-2]
    return "/" + path.strip("/")


def update_of(run_name: str) -> tuple[str, str, frozenset[str]]:
    """Return a run's update as (label, ecosystem, directories).

    The parts that vary between runs of one update (the packages, the run
    id) are dropped and the directories normalised, so a security update
    and a scheduled run of the same update are one update, and a failed
    one-off run is superseded by the next run that succeeds.
    """
    label = re.sub(r"( for .*)? - Update #[0-9]+$", "", run_name)
    eco, sep, dirs = label.partition(" in ")
    if not sep:
        return label, label, frozenset()
    return label, ecosystem(eco), frozenset(directory(d) for d in dirs.split(",") if d.strip())


def entries(config: dict) -> list[tuple[str, list[str], str, str]]:
    """Return (ecosystem, directories, label, interval) for every update in a config."""
    found = []
    for update in config.get("updates") or []:
        dirs = update.get("directories") or [update.get("directory", "/")]
        eco = update.get("package-ecosystem", "")
        interval = (update.get("schedule") or {}).get("interval", "")
        label = f"{eco} in {', '.join(dirs)}"
        found.append((ecosystem(eco), [directory(d) for d in dirs], label, interval))
    return found


def covers(pattern: str, path: str) -> bool:
    """Whether a config directory (which may be a glob) covers a run's directory."""
    return path == pattern or fnmatch.fnmatchcase(path, pattern)


def main() -> int:
    config_path, previous_path, runs_path = sys.argv[1:]
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle) or {}
    with open(previous_path, encoding="utf-8") as handle:
        previous = json.load(handle) or {}

    # (ecosystem, directories) -> (label, conclusion, url); runs come newest
    # first, so the first run seen for each update is its latest.
    latest = {}
    with open(runs_path, encoding="utf-8") as handle:
        for line in handle:
            name, conclusion, url = line.rstrip("\n").split("\t")
            label, eco, dirs = update_of(name)
            latest.setdefault((eco, dirs), (label, conclusion, url))

    if not latest:
        print(
            "::error::No Dependabot update ran in the last 8 days. Is"
            " Dependabot still enabled, and .github/dependabot.yml valid?"
        )
        return 1

    # Directories each ecosystem already had at the start of the window. An
    # update for one of these has had a whole weekly check to run in; one
    # added since may not have run yet, so it is let off until next week.
    before = {(eco, d) for eco, dirs, _, _ in entries(previous) for d in dirs}

    failed = 0
    rows = []
    for label, conclusion, url in latest.values():
        rows.append(f"| {label} | [{conclusion}]({url}) |")
        if conclusion in FAILED:
            print(f"::error::Dependabot's latest '{label}' run ended in {conclusion}: {url}")
            failed = 1

    for eco, dirs, label, interval in entries(config):
        if interval not in CHECKED_INTERVALS:
            print(
                f"::notice::'{label}' runs {interval or 'on no schedule'}, so a"
                " run is not expected in every 8-day window; not checked."
            )
            continue
        # A run belongs to this entry when all of its directories are the
        # entry's, whether Dependabot names one run after all of them or
        # runs each directory on its own.
        covered = set()
        for run_eco, run_dirs in latest:
            if run_eco != eco or not run_dirs:
                continue
            if all(any(covers(p, d) for p in dirs) for d in run_dirs):
                covered |= {p for p in dirs for d in run_dirs if covers(p, d)}
        missing = [d for d in dirs if d not in covered]
        if not missing:
            continue
        new = [d for d in missing if (eco, d) not in before]
        old = [d for d in missing if (eco, d) in before]
        if old:
            print(
                f"::error::Dependabot's '{label}' update has not run in the last"
                f" 8 days (no run for {', '.join(old)}), so it is getting no"
                " updates. Is it still scheduled? Check Insights -> Dependency"
                " graph -> Dependabot."
            )
            rows.append(f"| {label} | **no run** for {', '.join(old)} |")
            failed = 1
        if new:
            print(
                f"::notice::'{label}' is new since the last check and has not run"
                f" yet for {', '.join(new)}; it is checked from next week."
            )
            rows.append(f"| {label} | not run yet (new) for {', '.join(new)} |")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = ["### Latest Dependabot update runs", "", "| Update | Result |", "| --- | --- |"]
    text = "\n".join(lines + rows) + "\n"
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return failed


if __name__ == "__main__":
    sys.exit(main())
