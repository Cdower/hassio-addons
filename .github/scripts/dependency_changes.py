"""Describe how an add-on's shipped Python packages changed between two locks.

Dependabot's PRs move pins in pyproject.toml and uv.lock without touching the
changelog, so a release could ship different packages and say nothing about
it. The Bump workflow uses this to write that line itself, from the lock at
the previous release tag and the lock being released.
"""

import re
import tomllib


def runtime_packages(lock_text):
    """Return {name: version} for what a uv.lock installs into the image:
    the project's own dependencies and everything they pull in. Dependency
    groups (the CI-only `test` group) are left out, as the Dockerfile leaves
    them out.
    """
    packages = {package["name"]: package for package in tomllib.loads(lock_text)["package"]}
    roots = [p for p in packages.values() if "virtual" in p.get("source", {})]
    # (name, extra) pairs still to visit; extra None is the package itself. A
    # dependency written `name[extra]` also pulls in what that extra lists
    # under the package's optional-dependencies.
    pending = [dep for root in roots for dep in root.get("dependencies", [])]
    shipped = {}
    seen = set()
    while pending:
        dep = pending.pop()
        name = dep["name"]
        if name not in packages:
            continue
        for extra in (None, *dep.get("extra", [])):
            if (name, extra) in seen:
                continue
            seen.add((name, extra))
            if extra is None:
                shipped[name] = packages[name]["version"]
                pending += packages[name].get("dependencies", [])
            else:
                pending += packages[name].get("optional-dependencies", {}).get(extra, [])
    return shipped


def describe(old_lock, new_lock, already_written=""):
    """Return a changelog line for the packages that differ between two
    uv.lock texts, or None when nothing changed. A package `already_written`
    (the Unreleased notes so far) names is skipped: someone described that
    update by hand, usually with more to say.
    """
    old, new = runtime_packages(old_lock), runtime_packages(new_lock)

    def mentioned(name):
        spelled = "[-_.]".join(re.escape(part) for part in re.split(r"[-_.]+", name))
        pattern = rf"(?i)(?<![\w-]){spelled}(?![\w-])"
        return re.search(pattern, already_written) is not None

    changes = []
    for name in sorted(old.keys() | new.keys()):
        if old.get(name) == new.get(name) or mentioned(name):
            continue
        if name not in old:
            changes.append(f"{name} {new[name]} (new)")
        elif name not in new:
            changes.append(f"{name} (removed)")
        else:
            changes.append(f"{name} {old[name]} to {new[name]}")
    if not changes:
        return None
    return "- Updated the Python packages the add-on ships: " + ", ".join(changes) + "."
