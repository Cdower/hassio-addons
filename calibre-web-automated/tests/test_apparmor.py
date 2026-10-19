# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
#
# Every mount init-cwa-paths makes must be allowed by apparmor.txt, or it is
# refused at runtime on AppArmor hosts (HAOS) only. Checks the bind-mount
# targets and the SMB mount point against the profile's mount rules.
#
# Run directly:   python3 calibre-web-automated/tests/test_apparmor.py
# Or via pytest:  pytest calibre-web-automated/tests/test_apparmor.py

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.dirname(HERE)
INIT_PATHS = os.path.join(
    ADDON_ROOT, "rootfs", "etc", "s6-overlay", "scripts", "init-cwa-paths",
)
PROFILE = os.path.join(ADDON_ROOT, "apparmor.txt")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class AppArmorMountRulesTest(unittest.TestCase):
    def setUp(self):
        self.script = read(INIT_PATHS)
        self.profile = read(PROFILE)

    def rules_for(self, target):
        pattern = re.compile(
            r"^\s*mount\s+(.*?)\s*->\s*" + re.escape(target.rstrip("/") + "/") + r"\s*,",
            re.M,
        )
        return [m.group(1) for m in pattern.finditer(self.profile)]

    def test_bind_targets_are_allowed(self):
        targets = re.findall(r"^\s*bind_user_path\s+\S+\s+(/\S+)\s*$", self.script, re.M)
        self.assertGreaterEqual(len(targets), 4, "parser found too few bind targets")
        for target in targets:
            rules = self.rules_for(target)
            self.assertIn("options=(rw, bind)", rules, f"no bind rule for {target}")
            # mount(8) may attach the bind through open_tree + move_mount.
            self.assertIn("options=(rw, move)", rules, f"no move rule for {target}")

    def test_smb_mount_point_is_allowed(self):
        match = re.search(r"^SMB_MOUNT_POINT=(\S+)$", self.script, re.M)
        self.assertIsNotNone(match)
        self.assertIn("fstype=cifs", self.rules_for(match.group(1)))


class SmbCapabilitiesTest(unittest.TestCase):
    # mount.cifs drops privileges with libcap-ng, putting CAP_DAC_READ_SEARCH
    # back into its permitted set. capset() refuses a capability the container
    # was never given, and the mount fails with "Unable to apply new capability
    # set." So the add-on must hold it, while AppArmor stops it being used (it
    # is what open_by_handle_at, the "Shocker" container escape, checks for).
    def test_mount_cifs_can_raise_dac_read_search(self):
        config = read(os.path.join(ADDON_ROOT, "config.yaml"))
        block = re.search(r"^privileged:\n((?:\s+-\s*\S+\n)+)", config, re.M)
        self.assertIsNotNone(block, "no privileged list in config.yaml")
        caps = re.findall(r"-\s*(\S+)", block.group(1))
        self.assertIn("SYS_ADMIN", caps)
        self.assertIn("DAC_READ_SEARCH", caps)

    def test_dac_read_search_use_is_denied(self):
        self.assertRegex(
            read(PROFILE), r"(?m)^\s*deny\s+capability\s+dac_read_search\s*,",
        )


if __name__ == "__main__":
    unittest.main()
