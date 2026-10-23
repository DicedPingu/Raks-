import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

import _path  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "package_release.py")


def run(*args):
    return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True)


class ReleasePackageTest(unittest.TestCase):
    def test_bundle_contents_and_checksums(self):
        from server import VERSION
        with tempfile.TemporaryDirectory() as out:
            r = run("--out", out, "--tag", "v" + VERSION)
            self.assertEqual(r.returncode, 0, r.stderr)
            base = "raks-" + VERSION
            with tarfile.open(os.path.join(out, base + ".tar.gz")) as t:
                names = t.getnames()
            with zipfile.ZipFile(os.path.join(out, base + ".zip")) as z:
                self.assertEqual(sorted(z.namelist()), sorted(names))
            for need in ("host/raks_host.py", "client/index.html", "presets/index.json", "run.sh", "install.sh",
                         "config.json", "LICENSE", "README.md", "VERSION"):
                self.assertIn("%s/%s" % (base, need), names)
            self.assertFalse([n for n in names if "/tests/" in n or "__pycache__" in n or n.endswith(".pyc")])
            sums = open(os.path.join(out, "SHA256SUMS.txt")).read()
            self.assertIn(base + ".tar.gz", sums)
            self.assertIn(base + ".zip", sums)

    def test_tag_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as out:
            self.assertNotEqual(run("--out", out, "--tag", "v99.0.0").returncode, 0)


if __name__ == "__main__":
    unittest.main()
