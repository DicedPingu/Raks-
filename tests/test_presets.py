import glob
import json
import os
import unittest

import _path  # noqa: F401
from protocol import CONTROL_CODES

PRESETS = os.path.join(_path.ROOT, "presets")
TYPES = {"button", "trigger", "stick", "dpad"}
EXPECTED = {"nes", "snes", "n64", "gamecube", "playstation", "generic"}


class PresetTests(unittest.TestCase):
    def load(self, name):
        with open(os.path.join(PRESETS, name + ".json"), encoding="utf-8") as f:
            return json.load(f)

    def test_index_lists_all_presets(self):
        idx = self.load("index")
        self.assertEqual(set(idx), EXPECTED)
        files = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(PRESETS, "*.json"))} - {"index"}
        self.assertEqual(files, EXPECTED)

    def test_presets_valid(self):
        for pid in EXPECTED:
            p = self.load(pid)
            self.assertEqual(p["id"], pid)
            self.assertTrue(p["name"])
            ids = [c["id"] for c in p["controls"]]
            self.assertEqual(len(ids), len(set(ids)), pid + ": duplicate control ids")
            for c in p["controls"]:
                self.assertIn(c["type"], TYPES, (pid, c))
                for k in ("x", "y"):
                    self.assertTrue(0 <= c[k] <= 1, (pid, c))
                self.assertTrue(0.04 <= c["size"] <= 0.8, (pid, c))
                self.assertTrue(0.1 <= c["opacity"] <= 1, (pid, c))
                if c["type"] in ("button", "trigger"):
                    self.assertIn(c["code"], CONTROL_CODES, (pid, c))
                if c["type"] == "stick":
                    self.assertIn(c["stick"], ("left", "right"))
                if c["type"] == "dpad":
                    self.assertIn(c.get("maps", "hat"), ("hat", "left", "right"))

    def test_expected_controls(self):
        def codes(pid):
            return {c.get("code") for c in self.load(pid)["controls"]}

        def types(pid):
            return [c["type"] for c in self.load(pid)["controls"]]
        self.assertEqual(codes("nes") - {None}, {"south", "east", "select", "start"})
        self.assertIn("dpad", types("nes"))
        self.assertTrue({"south", "east", "north", "west", "tl", "tr", "select", "start"} <= codes("snes"))
        self.assertIn("stick", types("n64"))
        self.assertTrue({"rs_up", "rs_down", "rs_left", "rs_right", "tl2"} <= codes("n64"))
        self.assertEqual(types("gamecube").count("stick"), 2)
        self.assertEqual(types("playstation").count("stick"), 2)
        self.assertTrue({"thumbl", "thumbr", "tl2", "tr2"} <= codes("playstation"))
        self.assertEqual(types("generic").count("stick"), 2)

    def test_client_files_exist(self):
        for f in ("index.html", "app.js", "demo.js", "styles.css", "manifest.webmanifest", "sw.js",
                  "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png", "icons/icon.svg"):
            self.assertTrue(os.path.exists(os.path.join(_path.ROOT, "client", f)), f)
        with open(os.path.join(_path.ROOT, "client", "manifest.webmanifest")) as f:
            self.assertEqual(json.load(f)["orientation"], "landscape")


if __name__ == "__main__":
    unittest.main()
