"""Point an add-on's Dockerfile at a new Tailscale release and log it.

Reads ADDON, VERSION, SHA256_AMD64 and SHA256_ARM64 from the environment and
rewrites the TAILSCALE_VERSION and TAILSCALE_SHA256_* ARG lines in
<addon>/Dockerfile, then records the update under the Unreleased section of
<addon>/CHANGELOG.md. If Unreleased already mentions a Tailscale update (an
earlier one that has not been released yet), that entry's target version is
moved forward instead of adding a second line. Used by
.github/workflows/tailscale.yaml.
"""
import os
import re
import sys

addon = os.environ["ADDON"]
version = os.environ["VERSION"]
hashes = {
    "TAILSCALE_SHA256_AMD64": os.environ["SHA256_AMD64"],
    "TAILSCALE_SHA256_ARM64": os.environ["SHA256_ARM64"],
}

dockerfile = os.path.join(addon, "Dockerfile")
with open(dockerfile, encoding="utf-8") as handle:
    text = handle.read()

current = re.search(r'(?m)^ARG TAILSCALE_VERSION="([^"]*)"$', text)
if current is None:
    sys.exit(f"::error::No TAILSCALE_VERSION ARG found in {dockerfile}")
previous = current.group(1)

for name, value in {"TAILSCALE_VERSION": version, **hashes}.items():
    text, count = re.subn(
        rf'(?m)^ARG {name}="[^"]*"$', f'ARG {name}="{value}"', text, count=1
    )
    if count != 1:
        sys.exit(f"::error::No {name} ARG found in {dockerfile}")
with open(dockerfile, "w", encoding="utf-8") as handle:
    handle.write(text)

changelog = os.path.join(addon, "CHANGELOG.md")
with open(changelog, encoding="utf-8") as handle:
    lines = handle.read().splitlines()

unreleased = next(
    (i for i, line in enumerate(lines)
     if re.match(r"(?i)^##[ \t]+\[?unreleased\]?[ \t]*$", line)),
    None,
)
if unreleased is None:
    sys.exit(f"::error::No Unreleased section in {changelog}")
end = next(
    (i for i in range(unreleased + 1, len(lines)) if lines[i].startswith("## ")),
    len(lines),
)

entry = re.compile(
    r"^- Updated the bundled Tailscale client from (\S+) to \S+?\.$"
)
existing = next(
    (i for i in range(unreleased + 1, end) if entry.match(lines[i])), None
)
if existing is not None:
    since = entry.match(lines[existing]).group(1)
    lines[existing] = (
        f"- Updated the bundled Tailscale client from {since} to {version}."
    )
else:
    line = f"- Updated the bundled Tailscale client from {previous} to {version}."
    changed = next(
        (i for i in range(unreleased + 1, end) if lines[i] == "### Changed"), None
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

with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
    handle.write(f"previous={previous}\n")
