# -*- coding: utf-8 -*-
"""Вход «данные персонажа» (eve_sso, отдельно от «Флота») и модуль «ESS»: журнал кошелька — выплаты ESS и баунти; общий адрес возврата SSO."""
import base64
import json
import os
import unittest

import eve_sso
from helpers import TempDirs, ctx, elw, make_cfg, module

ess = module("ess")
ALL = list(eve_sso.SCOPES)


def jwt(cid, name, scp):
    body = base64.urlsafe_b64encode(json.dumps({"sub": f"CHARACTER:EVE:{cid}", "name": name, "scp": scp}).encode()).decode().rstrip("=")
    return "h." + body + ".s"


def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


class FakeEve:
    def __init__(self, scp=tuple(ALL)):
        self.scp, self.calls = list(scp), []
        self.journal = {9001: [
            {"id": 1, "date": "2026-10-20T10:00:00Z", "ref_type": "ess_escrow_transfer", "amount": 5_000_000, "context_id": 30001555,
             "context_id_type": "system_id", "description": "ESS escrow"},
            {"id": 2, "date": "2026-10-20T10:20:00Z", "ref_type": "bounty_prizes", "amount": 12_000_000, "context_id": 30001555,
             "context_id_type": "system_id"},
            {"id": 3, "date": "2026-10-20T11:00:00Z", "ref_type": "market_transaction", "amount": -1000},
        ]}

    def __call__(self, method, url, token="", form=None, body=None, timeout=20):
        self.calls.append((method, url))
        if url.endswith("/v2/oauth/token"):
            return {"access_token": jwt(9001, "Ratter One", self.scp), "expires_in": 1200, "refresh_token": "r1"}, {}
        if "/wallet/journal/" in url:
            return (self.journal[9001] if "page=1" in url else []), {"X-Pages": "1"}
        if url.endswith("/universe/names/?datasource=tranquility"):
            return [{"id": i, "name": "Isbrabata"} for i in body], {}
        raise AssertionError(url)


class TestEss(unittest.TestCase):
    def setUp(self):
        self.td = TempDirs()
        self.eve = FakeEve()
        self.auth = eve_sso.Auth(self.td.data, "abc", write, self.eve)
        self.wallet = ess.Wallet(self.td.data, self.auth, write, self.eve)

    def tearDown(self):
        self.td.cleanup()

    def login(self):
        url = self.auth.login_url("http://localhost:47322/sso/callback")
        for sc in ALL:                                                    # все доступы «данных персонажа» — одним входом
            self.assertIn(sc, url)
        self.assertNotIn("fleet", url)                                    # флот — отдельное приложение
        state = url.split("state=")[1].split("&")[0]
        self.assertTrue(self.auth.owns(state))
        return self.auth.finish("code", state)

    def test_login_sync_report(self):
        self.assertEqual(self.login(), "Ratter One")
        self.assertEqual(list(self.auth.chars), [9001])
        again = eve_sso.Auth(self.td.data, "abc", write, self.eve)           # токен сохранён (зашифрован на Windows)
        self.assertEqual(again.chars[9001]["refresh"], "r1")
        r = self.wallet.sync(now=1_792_500_000)
        self.assertEqual(r["added"], 2)                                  # только ESS и баунти, без торговли
        self.assertEqual(self.wallet.sync(now=1_792_500_100)["added"], 0)    # без дублей
        rep = self.wallet.report(0, 2_000_000_000)
        self.assertEqual((rep["ess"], rep["bounty_paid"], rep["count"]), (5_000_000, 12_000_000, 1))
        self.assertEqual(rep["payments"][0]["system"], "Isbrabata")
        self.assertEqual(self.wallet.report(0, 2_000_000_000, "Other Pilot")["ess"], 0)
        self.assertEqual(self.wallet.report(0, 1_000_000_000)["ess"], 0)     # вне периода

    def test_no_wallet_scope(self):
        self.eve.scp = ["esi-assets.read_assets.v1"]                    # кошелёк не дали — персонаж есть, кошелёк не читаем
        self.login()
        self.assertFalse(self.auth.has(9001, ess.WALLET))
        self.assertIn("кошел", self.wallet.status()[0]["error"])
        self.wallet.sync(now=1_792_500_000)
        self.assertFalse(any("/wallet/" in u for _, u in self.eve.calls))

    def test_revoked_token_removes_character(self):
        self.login()
        self.auth.access.clear()

        def deny(method, url, **kw):
            raise eve_sso.SsoError("login.eveonline.com ответил 400", 400)
        self.auth.request = deny
        with self.assertRaises(eve_sso.SsoError):
            self.auth.token(9001)
        self.assertEqual(self.auth.chars, {})


class TestSsoDispatch(unittest.TestCase):
    """Один адрес возврата /sso/callback: ответ EVE уходит модулю, который начал вход; «Флот» — по умолчанию."""

    def test_dispatch(self):
        td = TempDirs()
        try:
            cfg = make_cfg(td.logs)
            app = elw.App(cfg, td.data, elw.Watcher(cfg, td.data), None)
            fleet_ctx = ctx(app, "fleet")
            fleet_ctx.get("/sso/callback", lambda qs: "fleet")
            auth = eve_sso.install(app, write, open_url=lambda url: None)
            self.assertIs(eve_sso.install(app, write), auth)                 # один на всех
            app.cfg["esi_main_client_id"] = ""
            self.assertFalse(app.routes[("POST", "/api/eve/client")][1]({"client_id": "nope"})["ok"])
            self.assertTrue(app.routes[("POST", "/api/eve/client")][1]({"client_id": "a" * 32})["ok"])
            self.assertTrue(app.routes[("POST", "/api/eve/login")][1]({})["ok"])
            state = next(iter(auth.pending))
            mid, route = app.routes[("GET", "/sso/callback")]
            self.assertEqual(route({"state": ["other"]}), "fleet")            # чужой вход — «Флоту»
            res = route({"state": [state], "error": ["access_denied"]})       # свой — общему входу
            self.assertEqual(res.code, 400)
            st = app.routes[("GET", "/api/eve/status")][1]({})
            self.assertTrue(st["client_id_set"])
            self.assertEqual(len(st["scopes"]), len(ALL))
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
