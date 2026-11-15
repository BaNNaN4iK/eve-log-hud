# -*- coding: utf-8 -*-
"""Удаление программы: только собранная программа, только свои папки, скрипт удаления."""
import os
import sys
import tempfile
import unittest
from unittest import mock

from helpers import TempDirs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uninstall  # noqa: E402


class TestUninstall(unittest.TestCase):
    def fake_app(self):
        root = tempfile.mkdtemp(prefix="elw_un_")
        prog = os.path.join(root, "EveLogHUD")
        os.makedirs(os.path.join(prog, "_internal"))
        return prog

    def test_refuses_from_sources(self):
        t = TempDirs()
        self.addCleanup(t.cleanup)
        self.assertIsNone(uninstall.program_dir())                          # тесты — не собранная программа
        ok, msg = uninstall.start(t.data, True)
        self.assertFalse(ok)
        self.assertIn("исходник", msg)
        self.assertFalse(os.path.exists(os.path.join(t.data, uninstall.QUIT_FLAG)))

    def test_program_dir_frozen(self):
        prog = self.fake_app()
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", os.path.join(prog, uninstall.EXE)):
            self.assertEqual(uninstall.program_dir(), prog)
        os.rmdir(os.path.join(prog, "_internal"))
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", os.path.join(prog, uninstall.EXE)):
            self.assertIsNone(uninstall.program_dir())                      # без _internal — не наша папка
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", os.path.join(prog, "other.exe")):
            self.assertIsNone(uninstall.program_dir())

    def test_safe_data_dir(self):
        prog = self.fake_app()
        self.assertTrue(uninstall.safe_data_dir(os.path.join("C:\\Users\\X\\AppData\\Local", "EveLogHUD"), prog))
        self.assertTrue(uninstall.safe_data_dir(os.path.join(prog, "data"), prog))
        self.assertFalse(uninstall.safe_data_dir("C:\\Users\\X\\Documents", prog))

    def test_scripts(self):
        w = uninstall._script_win("C:\\Games\\EveLogHUD", "C:\\Users\\X\\AppData\\Local\\EveLogHUD")
        self.assertIn('rmdir /s /q "C:\\Games\\EveLogHUD"', w)
        self.assertIn('rmdir /s /q "C:\\Users\\X\\AppData\\Local\\EveLogHUD"', w)
        self.assertIn('del "%~f0"', w)
        self.assertNotIn("AppData", uninstall._script_win("C:\\Games\\EveLogHUD", None))   # данные оставить
        sh = uninstall._script_sh("/opt/EveLogHUD", None)
        self.assertIn("rm -rf '/opt/EveLogHUD'", sh)
        self.assertEqual(sh.count("rm -rf"), 1)
