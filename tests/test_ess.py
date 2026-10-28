# -*- coding: utf-8 -*-
"""Модуль «ESS»: свой вход через EVE (только кошелёк), журнал кошелька — выплаты ESS и баунти, общий адрес возврата SSO."""
import base64
import json
import os
import unittest

from helpers import TempDirs, ctx, elw, make_cfg, module

ess = module("ess")


def jwt(cid, name, scp):
    body = base64.urlsafe_b64encode(json.dumps({"sub": f"CHARACTER:EVE:{cid}", "name": name, "scp": scp}).encode()).decode().rstrip("=")
    return "h." + body + ".s"


def write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


class FakeEve:
    def __init__(self, scp=("esi-wallet.read_character_wallet.v1",)):
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
        self.auth = ess.Auth(self.td.data, "abc", write, self.eve)
        self.wallet = ess.Wallet(self.td.data, self.auth, write, self.eve)

    def tearDown(self):
        self.td.cleanup()

    def login(self):
        url = self.auth.login_url("http://localhost:47322/sso/callback")
        self.assertIn("esi-wallet.read_character_wallet.v1", url)
        self.assertNotIn("fleet", url)                                    # доступы — свои, без флота
        state = url.split("state=")[1].split("&")[0]
        self.assertTrue(self.auth.owns(state))
        return self.auth.finish("code", state)

    def test_login_sync_report(self):
        self.assertEqual(self.login(), "Ratter One")
        self.assertEqual(list(self.auth.chars), [9001])
        again = ess.Auth(self.td.data, "abc", write, self.eve)           # токен сохранён (зашифрован на Windows)
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
        self.eve.scp = ["esi-fleets.read_fleet.v1"]
        with self.assertRaises(ess.EssError):
            self.login()
        self.assertEqual(self.auth.chars, {})

    def test_revoked_token_removes_character(self):
        self.login()
        self.auth.access.clear()

        def deny(method, url, **kw):
            raise ess.EssError("login.eveonline.com ответил 400", 400)
        self.auth.request = deny
        with self.assertRaises(ess.EssError):
            self.auth.token(9001)
        self.assertEqual(self.auth.chars, {})


class TestSsoDispatch(unittest.TestCase):
    """Один адрес возврата /sso/callback: ответ EVE уходит модулю, который начал вход; «Флот» — по умолчанию."""

    def test_dispatch(self):
        td = TempDirs()
        try:
            cfg = make_cfg(td.logs)
            app = elw.App(cfg, td.data, elw.Watcher(cfg, td.data), None)
            fleet_ctx, ess_ctx = ctx(app, "fleet"), ctx(app, "ess")
            fleet_ctx.get("/sso/callback", lambda qs: "fleet")
            ess_ctx.sso(lambda st: st.startswith("ess-"), lambda qs: "ess")
            mid, route = app.routes[("GET", "/sso/callback")]
            self.assertEqual(route({"state": ["ess-123"]}), "ess")
            self.assertEqual(route({"state": ["other"]}), "fleet")
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
