# -*- coding: utf-8 -*-
"""Настольное приложение: где лежат данные и как запускаются роли (без окон и трея)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401
import eve_log_app as app


class TestApp(unittest.TestCase):
    def test_data_dir(self):
        with mock.patch.dict(os.environ, {"EVE_DATA_DIR": ""}):
            self.assertEqual(app.data_dir(), app.HERE)                       # из исходников — рядом со скриптами
            with tempfile.TemporaryDirectory() as d, mock.patch.object(app, "FROZEN", True), mock.patch.object(app, "HERE", d):
                with mock.patch.dict(os.environ, {"LOCALAPPDATA": os.path.join(d, "local"), "XDG_DATA_HOME": os.path.join(d, "local")}):
                    self.assertEqual(app.data_dir(), os.path.join(d, "local", "EveLogHUD"))   # собранное — в профиле
                    with mock.patch.object(app.sys, "platform", "linux"), \
                            mock.patch.dict(os.environ, {"XDG_DATA_HOME": ""}), \
                            mock.patch.object(app.os.path, "expanduser", lambda p: p.replace("~", os.path.join(d, "home"))):
                        self.assertEqual(app.data_dir(), os.path.join(d, "home", ".local", "share", "EveLogHUD"))   # Linux без XDG
                    os.mkdir(os.path.join(d, "data"))
                    self.assertEqual(app.data_dir(), os.path.join(d, "data"))                 # переносной режим
        with mock.patch.dict(os.environ, {"EVE_DATA_DIR": os.path.abspath("somewhere")}):
            self.assertEqual(app.data_dir(), os.path.abspath("somewhere"))

    def test_port_and_roles(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(app.port(d), 47322)
            with open(os.path.join(d, "config.json"), "w") as f:
                json.dump({"web_port": 47999}, f)
            self.assertEqual(app.port(d), 47999)
            with open(os.path.join(d, "config.json"), "w") as f:
                f.write("{broken")
            self.assertEqual(app.port(d), 47322)
        self.assertEqual(app.role_cmd("overlay", "--demo")[-3:], [os.path.abspath(app.__file__), "--overlay", "--demo"])
        with mock.patch.object(app, "FROZEN", True):
            self.assertEqual(app.role_cmd("tracker"), [sys.executable, "--tracker"])
        self.assertFalse(app.server_up(1, timeout=0.2))                      # никого нет — не падаем

    def test_overlay_starts_when_module_enabled(self):
        """Модуль оверлея включили на вкладке «Модули» уже после запуска — оверлей запускается без перезапуска приложения."""
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"EVE_DATA_DIR": d}):
            a = app.Shell()
            avail = iter([False, False, True, True])
            stop = mock.Mock()
            stop.wait.side_effect = [False, False, False, True]
            with mock.patch.object(a, "overlay_available", side_effect=lambda: next(avail)),                     mock.patch.object(a, "ensure_tracker"), mock.patch.object(a, "set_overlay") as so:
                a.watchdog(stop)
            so.assert_called_once_with(True)                                # только на переходе «выключен → включён»
            a.prefs["overlay"] = False                                      # выключен вручную в трее — не трогаем
            avail = iter([False, True])
            stop.wait.side_effect = [False, True]
            with mock.patch.object(a, "overlay_available", side_effect=lambda: next(avail)),                     mock.patch.object(a, "ensure_tracker"), mock.patch.object(a, "set_overlay") as so:
                a.watchdog(stop)
            so.assert_not_called()


if __name__ == "__main__":
    unittest.main()
