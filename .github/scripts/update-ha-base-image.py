"""Move an add-on to the newest Home Assistant base image for its Python.

Reads ADDON from the environment. <addon>/build.yaml names one image per
architecture, all with the same tag of the form
`<python>-alpine<alpine>-<YYYY.MM.N>` (for example
`3.13-alpine3.24-2026.08.0`). This asks the registry for each image's tags and
picks the newest release that every architecture has, keeping the Python
version (the add-on's .python-version, uv.lock and ruff's target follow it, so
that is a change to make by hand) and never moving to an older Alpine. It
then rewrites the tags in <addon>/build.yaml and the `ARG BUILD_FROM` default
in <addon>/Dockerfile, and records the update under the Unreleased section of
<addon>/CHANGELOG.md, moving an earlier unreleased entry forward rather than
adding a second one.

Writes `previous`, `latest` and `updated` to GITHUB_OUTPUT. Used by
.github/workflows/pins.yaml.
"""

import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changelog_entry  # noqa: E402

REGISTRY = "ghcr.io"
TAG = re.compile(r"(\d+\.\d+)-alpine(\d+)\.(\d+)-(\d{4})\.(\d{2})\.(\d+)")

addon = os.environ["ADDON"]


def fetch(url, token=None):
    """GET a registry URL and return the response."""
    if not url.startswith(f"https://{REGISTRY}/"):
        sys.exit(f"::error::Refusing to fetch {url}")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers)
    # The check above pins the scheme and host, so this cannot open a file: URL.
    return urllib.request.urlopen(request, timeout=30)  # nosec B310


def tags_of(repository):
    """Return every tag of a public image on the registry."""
    with fetch(f"https://{REGISTRY}/token?scope=repository:{repository}:pull") as response:
        token = json.load(response)["token"]
    tags = []
    url = f"https://{REGISTRY}/v2/{repository}/tags/list?n=1000"
    while url:
        with fetch(url, token) as response:
            tags += json.load(response).get("tags") or []
            following = re.search(r'<([^>]+)>;\s*rel="next"', response.headers.get("Link") or "")
        url = f"https://{REGISTRY}{following.group(1)}" if following else None
    return set(tags)


def release(tag):
    """Return (python, sort key) for a release tag, or None for any other tag."""
    match = TAG.fullmatch(tag)
    if match is None:
        return None
    python, *numbers = match.groups()
    alpine_major, alpine_minor, year, month, patch = map(int, numbers)
    return python, ((year, month, patch), (alpine_major, alpine_minor))


build = os.path.join(addon, "build.yaml")
with open(build, encoding="utf-8") as handle:
    build_text = handle.read()

entry = re.compile(rf"(?m)^(\s+\w+:\s*{re.escape(REGISTRY)}/)([\w./-]+):([\w.-]+)[ \t]*$")
images = entry.findall(build_text)
current_tags = {tag for _, _, tag in images}
if len(current_tags) != 1:
    sys.exit(f"::error file={build}::Expected one {REGISTRY} tag shared by every architecture")
current = current_tags.pop()
parsed = release(current)
if parsed is None:
    sys.exit(f"::error file={build}::'{current}' is not a <python>-alpine<x.y>-<release> tag")
python, current_key = parsed
alpine = current_key[1]

common = set.intersection(*(tags_of(repository) for _, repository, _ in images))
candidates = []
for tag in common:
    found = release(tag)
    if found is not None and found[0] == python and found[1][1] >= alpine:
        candidates.append((found[1], tag))
latest = max(candidates, default=(current_key, current))[1]
updated = release(latest)[1] > current_key

if updated:
    with open(build, "w", encoding="utf-8") as handle:
        handle.write(entry.sub(rf"\g<1>\g<2>:{latest}", build_text))

    dockerfile = os.path.join(addon, "Dockerfile")
    with open(dockerfile, encoding="utf-8") as handle:
        text = handle.read()
    text, count = re.subn(
        rf'(?m)^(ARG BUILD_FROM="{re.escape(REGISTRY)}/[\w./-]+):{re.escape(current)}"$',
        rf'\g<1>:{latest}"',
        text,
        count=1,
    )
    if count != 1:
        sys.exit(f"::error file={dockerfile}::No ARG BUILD_FROM default with tag {current}")
    with open(dockerfile, "w", encoding="utf-8") as handle:
        handle.write(text)

    changelog_entry.add_or_update(
        os.path.join(addon, "CHANGELOG.md"),
        re.compile(r"^(- Updated the Home Assistant base image from \S+ to )\S+?\.$"),
        rf"\g<1>{latest}.",
        f"- Updated the Home Assistant base image from {current} to {latest}.",
    )
else:
    print(f"::notice::{addon} is on the newest base image for Python {python} ({current})")

with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
    handle.write(f"previous={current}\nlatest={latest}\nupdated={str(updated).lower()}\n")
