# -*- coding: utf-8 -*-
"""Логика страницы: прогоняет tests/dashboard_logic.test.js в Node в нескольких часовых поясах."""
import os
import shutil
import subprocess
import unittest

from helpers import HERE

NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "Node.js не найден — логика страницы не проверена")
class TestDashboardLogic(unittest.TestCase):
    def run_tz(self, tz):
        env = dict(os.environ, TZ=tz)
        r = subprocess.run([NODE, os.path.join(HERE, "dashboard_logic.test.js")], capture_output=True,
                           env=env, timeout=60)
        out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
        self.assertEqual(r.returncode, 0, out)
        self.assertIn("tests passed", out)

    def test_moscow(self):
        self.run_tz("Europe/Moscow")

    def test_new_york_dst(self):
        self.run_tz("America/New_York")

    def test_utc(self):
        self.run_tz("UTC")


if __name__ == "__main__":
    unittest.main()
