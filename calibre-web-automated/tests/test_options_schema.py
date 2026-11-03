# SPDX-License-Identifier: MIT
#
# Guard rail for config.yaml's options schema: an option added after the
# add-on's first release has to be optional ("?"). The Supervisor validates
# the whole stored options dict on every save and refuses one that is missing
# a non-optional option, but it never adds a new option to an existing
# install's options.json -- so a required option added later makes the config
# page unsaveable ("Missing option '<name>' in root ...") for everyone who
# installed the add-on before it existed.
#
# Run directly:   python3 calibre-web-automated/tests/test_options_schema.py
# Or via pytest:  pytest calibre-web-automated/tests/test_options_schema.py

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.dirname(HERE)
CONFIG = os.path.join(ADDON_ROOT, "config.yaml")

# The options the add-on's first release already required. They are in every
# install's options.json, so they are the only ones that may stay required.
REQUIRED_SINCE_FIRST_RELEASE = frozenset(
    {"library_path", "ingest_path", "network_share_mode", "trusted_proxy_count"}
)


def block(name):
    """The top-level `name:` mapping from config.yaml, as {option: raw value}.

    Reads config.yaml with regexes rather than PyYAML, which the test
    environment does not install (see pyproject.toml). A list option
    (`access_users`) carries its type on the following `- <type>` line and
    comes back as that element type, because that is what the Supervisor
    checks a missing list option against.
    """
    with open(CONFIG, encoding="utf-8") as fh:
        text = fh.read()
    body = re.search(rf"^{name}:\n((?:[ \t].*\n|\n)*)", text, re.MULTILINE)
    assert body, f"no {name}: block in {CONFIG}"
    entries = {}
    key = None
    for line in body.group(1).splitlines():
        match = re.match(r"^ {2}([a-z0-9_]+):[ \t]*(.*?)\s*$", line)
        if match:
            key = match.group(1)
            entries[key] = match.group(2)
            continue
        nested = re.match(r"^ {4}-[ \t]*(\S.*?)\s*$", line)
        if nested and key and not entries[key]:
            entries[key] = nested.group(1)
    return entries


class OptionsSchemaTest(unittest.TestCase):
    def setUp(self):
        self.schema = block("schema")
        self.options = block("options")
        self.assertIn("library_path", self.schema, "parser found no schema options")

    def test_options_added_after_the_first_release_are_optional(self):
        for option, kind in self.schema.items():
            # Every option has to reach the "?" check below: skipping the ones
            # the parser cannot type is how `access_users` stayed required
            # unnoticed. A nested option that is not a list of a scalar type
            # cannot be made optional at all, so failing here is correct.
            self.assertTrue(
                kind,
                f"the parser found no type for {option}; teach block() to read "
                "it (and check the Supervisor can treat it as optional at all)",
            )
            if option in REQUIRED_SINCE_FIRST_RELEASE:
                self.assertFalse(
                    kind.endswith("?"),
                    f"{option} is required in every install's options.json; "
                    "drop it from REQUIRED_SINCE_FIRST_RELEASE if it is now optional",
                )
                continue
            self.assertTrue(
                kind.endswith("?"),
                f"{option} is a required option the add-on did not always have, "
                "so saving the config fails on installs that predate it. Make it "
                f"optional ({kind}?) and default it where it is read.",
            )

    def test_every_required_option_ships_with_a_default(self):
        # A fresh install gets exactly the `options:` block, so each required
        # option must be in it or the add-on is unsaveable out of the box.
        for option in REQUIRED_SINCE_FIRST_RELEASE:
            self.assertIn(option, self.schema, f"{option} is no longer in the schema")
            self.assertIn(option, self.options, f"{option} is required but has no default")

    def test_every_default_is_a_known_option(self):
        for option in self.options:
            self.assertIn(option, self.schema, f"{option} has a default but no schema")


if __name__ == "__main__":
    unittest.main()
