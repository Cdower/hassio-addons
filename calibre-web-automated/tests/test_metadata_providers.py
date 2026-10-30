# SPDX-License-Identifier: MIT
#
# Offline tests for the custom metadata-provider installer
# (rootfs/opt/cwa-metadata-providers/install_providers.py).
#
# Uses temporary directories for the source folder, the provider directory and
# the manifest. No network, no cps import.
#
# Run directly:   python3 calibre-web-automated/tests/test_metadata_providers.py
# Or via pytest:  pytest calibre-web-automated/tests/test_metadata_providers.py

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_ROOT = os.path.dirname(HERE)
INSTALLER_PATH = os.path.join(
    ADDON_ROOT, "rootfs", "opt", "cwa-metadata-providers", "install_providers.py",
)

spec = importlib.util.spec_from_file_location("cwa_install_providers", INSTALLER_PATH)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

BUILTINS = {
    "__init__.py": "",
    "google.py": "# built-in google\n",
    "arxiv.py": "# add-on arxiv overlay\n",
}


def write(path, content):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class InstallProvidersTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = os.path.join(tmp.name, "source")
        self.dest = os.path.join(tmp.name, "metadata_provider")
        self.manifest = os.path.join(tmp.name, "run", "manifest")
        os.makedirs(self.source)
        os.makedirs(os.path.join(self.dest, "__pycache__"))
        for name, content in BUILTINS.items():
            write(os.path.join(self.dest, name), content)

    def run_install(self, source="default"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            installed = installer.install(
                self.source if source == "default" else source,
                self.dest, self.manifest,
            )
        return installed, out.getvalue()

    def test_installs_new_provider(self):
        write(os.path.join(self.source, "my_source.py"), "# custom\n")
        installed, _ = self.run_install()
        self.assertEqual(installed, ["my_source.py"])
        target = os.path.join(self.dest, "my_source.py")
        self.assertEqual(read(target), "# custom\n")
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o644)
        self.assertEqual(installer.read_manifest(self.manifest), {"my_source.py"})

    def test_never_overwrites_builtin(self):
        write(os.path.join(self.source, "google.py"), "# evil twin\n")
        write(os.path.join(self.source, "arxiv.py"), "# evil twin\n")
        installed, out = self.run_install()
        self.assertEqual(installed, [])
        self.assertEqual(read(os.path.join(self.dest, "google.py")), BUILTINS["google.py"])
        self.assertEqual(read(os.path.join(self.dest, "arxiv.py")), BUILTINS["arxiv.py"])
        self.assertIn("skipping google.py", out)
        self.assertIn("skipping arxiv.py", out)

    def test_never_shadows_builtin_package(self):
        os.makedirs(os.path.join(self.dest, "helpers"))
        write(os.path.join(self.source, "helpers.py"), "# would shadow\n")
        installed, _ = self.run_install()
        self.assertEqual(installed, [])

    def test_skips_invalid_and_non_python_files(self):
        for name in ("__init__.py", "my-source.py", "1st.py", "notes.txt",
                     "._my_source.py", ".hidden.py"):
            write(os.path.join(self.source, name), "# x\n")
        os.makedirs(os.path.join(self.source, "subdir.py"))
        installed, _ = self.run_install()
        self.assertEqual(installed, [])
        self.assertEqual(
            sorted(os.listdir(self.dest)),
            sorted(list(BUILTINS) + ["__pycache__"]),
        )
        self.assertEqual(read(os.path.join(self.dest, "__init__.py")), "")

    def test_reinstall_updates_and_uninstalls(self):
        write(os.path.join(self.source, "one.py"), "# v1\n")
        write(os.path.join(self.source, "two.py"), "# two\n")
        self.run_install()

        os.remove(os.path.join(self.source, "two.py"))
        write(os.path.join(self.source, "one.py"), "# v2\n")
        installed, _ = self.run_install()

        self.assertEqual(installed, ["one.py"])
        self.assertEqual(read(os.path.join(self.dest, "one.py")), "# v2\n")
        self.assertFalse(os.path.exists(os.path.join(self.dest, "two.py")))
        self.assertEqual(installer.read_manifest(self.manifest), {"one.py"})

    def test_previously_installed_is_not_treated_as_builtin(self):
        write(os.path.join(self.source, "mine.py"), "# v1\n")
        self.run_install()
        write(os.path.join(self.source, "mine.py"), "# v2\n")
        installed, _ = self.run_install()
        self.assertEqual(installed, ["mine.py"])

    def test_no_source_removes_installed(self):
        write(os.path.join(self.source, "mine.py"), "# x\n")
        self.run_install()
        installed, _ = self.run_install(source=None)
        self.assertEqual(installed, [])
        self.assertFalse(os.path.exists(os.path.join(self.dest, "mine.py")))
        self.assertEqual(read(os.path.join(self.dest, "google.py")), BUILTINS["google.py"])
        self.assertEqual(installer.read_manifest(self.manifest), set())

    def test_manifest_cannot_delete_outside_dest(self):
        outside = os.path.join(os.path.dirname(self.dest), "outside.py")
        write(outside, "# keep\n")
        os.makedirs(os.path.dirname(self.manifest), exist_ok=True)
        write(self.manifest, "../outside.py\n")
        self.run_install()
        self.assertTrue(os.path.exists(outside))

    def test_main_rejects_missing_source(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = installer.main([
                "--source", os.path.join(self.source, "missing"),
                "--dest", self.dest, "--manifest", self.manifest,
            ])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
