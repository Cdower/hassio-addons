"""Point an add-on at a new upstream base image tag and log it.

Reads ADDON, TAG and REFRESH_REFS from the environment. Rewrites the image tag
in <addon>/Dockerfile's BUILD_FROM ARG and in every build_from entry of
<addon>/build.yaml, then records the update under the Unreleased section of
<addon>/CHANGELOG.md. If Unreleased already mentions a base image update (an
earlier one that has not been released yet), that entry's target tag is moved
forward instead of adding a second line.

With REFRESH_REFS=true, every other mention of the previous tag in the add-on
(the "verified against vX" notes in overridden files and tests) is moved to
TAG as well. The workflow sets it only when none of the upstream files the
add-on depends on changed, so those notes stay true. Used by
.github/workflows/base-image.yaml.
"""
import os
import re
import sys

addon = os.environ["ADDON"]
tag = os.environ["TAG"]
refresh_refs = os.environ.get("REFRESH_REFS") == "true"

UPSTREAM_URL = "https://github.com/new-usemame/calibre-web-nextgen"


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

# Matches the previous tag as a whole version, so v4.1.5 never hits v4.1.57.
previous_re = re.compile(rf"(?<![\w.]){re.escape(previous)}(?![\w.]*\d)")
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

changelog = os.path.join(addon, "CHANGELOG.md")
if refresh_refs:
    for root, dirs, files in os.walk(addon):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".pytest_cache")]
        for name in files:
            path = os.path.join(root, name)
            if path == changelog:
                continue
            try:
                text = read(path)
            except UnicodeDecodeError:
                continue
            text, count = previous_re.subn(tag, text)
            if count:
                write(path, text)

lines = read(changelog).splitlines()

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

link = f"[{tag}]({UPSTREAM_URL}/blob/{tag}/CHANGELOG.md)"
# Only the target is replaced, so notes a reviewer added after it survive.
target = re.compile(
    r"^(- Updated the base image from Calibre-Web NextGen \S+ to )\[[^\]]+\]\([^)]+\)"
)
existing = next(
    (i for i in range(unreleased + 1, end) if target.match(lines[i])), None
)
if existing is not None:
    lines[existing] = target.sub(rf"\g<1>{link}", lines[existing])
else:
    line = f"- Updated the base image from Calibre-Web NextGen {previous} to {link}."
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

write(changelog, "\n".join(lines).rstrip("\n") + "\n")
