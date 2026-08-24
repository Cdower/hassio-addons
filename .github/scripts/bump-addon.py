"""Bump one add-on's version and promote its changelog's Unreleased section.

Reads ADDON, VERSION and TODAY from the environment and rewrites
<addon>/config.yaml and <addon>/CHANGELOG.md in place. Writes a `warning`
output to GITHUB_OUTPUT describing anything the author needs to fix by hand
(an empty or missing Unreleased section), or an empty string when the bump
was clean. Used by .github/workflows/bump.yaml.
"""
import os
import re
import sys

addon = os.environ["ADDON"]
version = os.environ["VERSION"]
today = os.environ["TODAY"]

config = os.path.join(addon, "config.yaml")
with open(config, encoding="utf-8") as handle:
    text = handle.read()

# Touch only the version line, so comments and formatting survive verbatim.
new_text, count = re.subn(
    r'(?m)^(version:[ \t]*)(["\']?)[^"\'\n]*(\2)[ \t]*$',
    lambda m: f'{m.group(1)}"{version}"',
    text,
    count=1,
)
if count != 1:
    sys.exit(f"::error::No 'version:' line found in {config}")
with open(config, "w", encoding="utf-8") as handle:
    handle.write(new_text)

changelog = os.path.join(addon, "CHANGELOG.md")
heading = f"## [{version}] - {today}"
warning = ""

if not os.path.exists(changelog):
    lines = ["# Changelog", "", "## [Unreleased]", "", heading, "",
             "- TODO: describe this release before publishing.", ""]
    warning = f"{changelog} did not exist; wrote a stub"
else:
    with open(changelog, encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    unreleased = next(
        (i for i, line in enumerate(lines)
         if re.match(r"(?i)^##[ \t]+\[?unreleased\]?[ \t]*$", line)),
        None,
    )
    if unreleased is not None:
        body = lines[unreleased + 1:]
        next_heading = next(
            (i for i, line in enumerate(body) if line.startswith("## ")), len(body)
        )
        if not any(line.strip() for line in body[:next_heading]):
            warning = f"the Unreleased section in {changelog} is empty"
        lines[unreleased:unreleased + 1] = ["## [Unreleased]", "", heading]
    else:
        first = next(
            (i for i, line in enumerate(lines) if line.startswith("## ")), len(lines)
        )
        lines[first:first] = ["## [Unreleased]", "", heading, "",
                              "- TODO: describe this release before publishing.", ""]
        warning = f"{changelog} had no Unreleased section; added a placeholder entry"

with open(changelog, "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines).rstrip("\n") + "\n")

with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
    handle.write(f"warning={warning}\n")
if warning:
    print(f"::warning::{warning}")
