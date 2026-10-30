"""Point an add-on at a new upstream base image tag and log it.

Reads ADDON, TAG, UPSTREAM (the upstream GitHub URL, for the changelog link)
and REFRESH from the environment. Rewrites the image tag in
<addon>/Dockerfile's BUILD_FROM ARG and in every build_from entry of
<addon>/build.yaml, then records the update under the Unreleased section of
<addon>/CHANGELOG.md. If Unreleased already mentions a base image update (an
earlier one that has not been released yet), that entry's target tag is moved
forward instead of adding a second line.

REFRESH lists, space-separated and relative to the add-on, the files whose
"verified against <tag>" notes move to TAG as well: base-image-drift.py's
NOTES whose upstream files did not change. Each must name the previous tag.
Used by .github/workflows/base-image.yaml.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changelog_entry  # noqa: E402

addon = os.environ["ADDON"]
tag = os.environ["TAG"]
upstream = os.environ["UPSTREAM"]
refresh = os.environ.get("REFRESH", "").split()


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


dockerfile = os.path.join(addon, "Dockerfile")
text = read(dockerfile)
current = re.search(r'(?m)^ARG BUILD_FROM="([^":]+):([^"]+)"$', text)
if current is None:
    sys.exit(f"::error::No tagged BUILD_FROM ARG found in {dockerfile}")
image, previous = current.groups()
if previous == tag:
    sys.exit(f"::error::{dockerfile} already uses {image}:{tag}")

image_re = re.compile(rf"{re.escape(image)}:{re.escape(previous)}(?![\w.-])")

text, count = image_re.subn(f"{image}:{tag}", text)
if count != 1:
    sys.exit(f"::error::Expected one {image}:{previous} in {dockerfile}, found {count}")
write(dockerfile, text)

build = os.path.join(addon, "build.yaml")
text = read(build)
text, count = image_re.subn(f"{image}:{tag}", text)
if count == 0:
    sys.exit(f"::error::No build_from entry uses {image}:{previous} in {build}")
if re.search(rf"{re.escape(image)}:(?!{re.escape(tag)}(?![\w.-]))", text):
    sys.exit(f"::error::{build} pins {image} at a tag other than {previous}")
write(build, text)

# Matches the previous tag as a whole version, so v4.1.5 never hits v4.1.57.
previous_re = re.compile(rf"(?<![\w.]){re.escape(previous)}(?![\w.]*\d)")
for note in refresh:
    path = os.path.join(addon, note)
    text, count = previous_re.subn(tag, read(path))
    if count == 0:
        sys.exit(f"::error::{path} is listed in NOTES but does not mention {previous}")
    write(path, text)

link = f"[{tag}]({upstream}/blob/{tag}/CHANGELOG.md)"
changelog_entry.add_or_update(
    os.path.join(addon, "CHANGELOG.md"),
    re.compile(
        r"^(- Updated the base image from Calibre-Web NextGen \S+ to )\[[^\]]+\]\([^)]+\)"
    ),
    rf"\g<1>{link}",
    f"- Updated the base image from Calibre-Web NextGen {previous} to {link}.",
)
