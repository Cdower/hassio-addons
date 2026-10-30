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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changelog_entry  # noqa: E402

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
changelog_entry.add_or_update(
    changelog,
    re.compile(r"^(- Updated the bundled Tailscale client from \S+ to )\S+?\.$"),
    rf"\g<1>{version}.",
    f"- Updated the bundled Tailscale client from {previous} to {version}.",
)
