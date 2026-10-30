"""Add or update one line under a changelog's Unreleased section.

Shared by update-tailscale.py and update-base-image.py, which run with
`python3 -I` and so import it by putting this directory on sys.path first.
"""
import re
import sys

UNRELEASED = re.compile(r"(?i)^##[ \t]+\[?unreleased\]?[ \t]*$")


def add_or_update(changelog, pattern, replacement, line):
    """Rewrite the Unreleased line matching `pattern` with `replacement`
    (as for re.sub), or, if none matches, add `line` under ### Changed.

    Updating in place keeps one entry per dependency while a run of updates
    stays unreleased, and only the matched part changes, so anything a
    reviewer appended to the line survives.
    """
    with open(changelog, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    unreleased = next(
        (i for i, text in enumerate(lines) if UNRELEASED.match(text)), None
    )
    if unreleased is None:
        sys.exit(f"::error::No Unreleased section in {changelog}")
    end = next(
        (i for i in range(unreleased + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )

    existing = next(
        (i for i in range(unreleased + 1, end) if pattern.match(lines[i])), None
    )
    if existing is not None:
        lines[existing] = pattern.sub(replacement, lines[existing])
    else:
        changed = next(
            (i for i in range(unreleased + 1, end) if lines[i] == "### Changed"),
            None,
        )
        if changed is not None:
            # Append after the last bullet of the existing Changed list.
            stop = next(
                (i for i in range(changed + 1, end) if lines[i].startswith("### ")),
                end,
            )
            last = max(
                (i for i in range(changed + 1, stop) if lines[i].strip()),
                default=changed + 1,
            )
            lines[last + 1:last + 1] = [line]
        else:
            # Keep a Changelog orders Changed after Added and before the rest.
            later = ("### Deprecated", "### Removed", "### Fixed", "### Security")
            at = next(
                (i for i in range(unreleased + 1, end) if lines[i] in later), end
            )
            lines[at:at] = ["### Changed", "", line, ""]
            if lines[at - 1].strip():
                lines[at:at] = [""]

    with open(changelog, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip("\n") + "\n")
