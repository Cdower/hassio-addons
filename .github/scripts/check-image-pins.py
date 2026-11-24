"""Check an add-on's `test` dependency pins against its built image.

Usage: check-image-pins.py <addon>/pyproject.toml <packages.txt>

<packages.txt> lists the image's Python packages, one `name==version` per
line. Every `name==version` requirement in the `test` dependency group that
the image also ships must name the version the image has; packages the image
does not ship (pytest, say) are test-only and are skipped. Exits non-zero,
with one GitHub error annotation per mismatch, when a pin has drifted. Used
by .github/workflows/ci.yaml.
"""

import re
import sys
import tomllib


def normalise(name: str) -> str:
    """Return the PEP 503 form of a package name."""
    return re.sub(r"[-_.]+", "-", name).lower()


pyproject, packages = sys.argv[1:]

shipped = {}
with open(packages, encoding="utf-8") as handle:
    for line in handle:
        name, _, version = line.strip().partition("==")
        if version:
            shipped[normalise(name)] = version

with open(pyproject, "rb") as handle:
    group = tomllib.load(handle).get("dependency-groups", {}).get("test", [])

mismatches = 0
checked = 0
for requirement in group:
    match = re.fullmatch(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;]+)\s*", str(requirement))
    if match is None:
        continue
    name, pinned = normalise(match.group(1)), match.group(2)
    if name not in shipped:
        print(f"{name}: not in the image, test-only")
        continue
    checked += 1
    if shipped[name] == pinned:
        print(f"{name}: {pinned} matches the image")
    else:
        mismatches += 1
        print(
            f"::error file={pyproject}::The test group pins {name}=={pinned}, but the "
            f"image ships {shipped[name]}. Move the pin and run `uv lock`."
        )

if checked == 0:
    sys.exit(f"::error file={pyproject}::No test group pin matches a package in the image")
sys.exit(1 if mismatches else 0)
