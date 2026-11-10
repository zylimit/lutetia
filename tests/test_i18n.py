# risk: low
"""Task 13.1: the ops dashboard speaks English and French only.
- language pick: ?lang= (en | fr) > lutetia_lang cookie > Accept-Language (by q, other languages skipped) > English
- ?lang= sets the cookie (Lax, path /, one year); other values are ignored and set nothing
- the two dictionaries have the same keys and placeholders; no CJK anywhere; /i18n/<lang>.js serves them
- the sign-in page and the notice page for non-admin accounts follow the language; anomaly texts take a lang
No database is touched (same fake as test_spa_login)."""
import dataclasses
import re
import secrets
from datetime import datetime, timezone

import pytest
from aiohttp import DummyCookieJar
from aiohttp.test_utils import TestClient, TestServer

from lutetia.config import Config
from lutetia.web import anomalies
from lutetia.web.app import WebServer
from lutetia.web.i18n import COOKIE, DICTS, EN, FR, _from_accept_language, t

PWD = {"admin": "t-" + secrets.token_hex(6), "orange": "t-" + secrets.token_hex(6)}
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


class NoDB:
    def __getattr__(self, name):
        raise AssertionError("db touched: " + name)


def make_client():
    cfg = dataclasses.replace(Config.from_env(), dashboard_pwd=PWD["admin"], orange_pwd=PWD["orange"], api_key="k-" + secrets.token_hex(8),
                              dashboard_host="127.0.0.1", login_lockout=False, session_secret="s-" + secrets.token_hex(8))
    return TestClient(TestServer(WebServer(cfg, NoDB(), NOW).build_app()), cookie_jar=DummyCookieJar())


@pytest.mark.parametrize("header,want", [
    ("fr-FR,fr;q=0.9,en;q=0.8", "fr"), ("en", "en"), ("en-GB,en;q=0.9", "en"), ("fr", "fr"),
    ("de,fr;q=0.5", "fr"), ("zh-CN,zh;q=0.9", None), ("", None), ("*", None), ("fr;q=0,en;q=0.1", "en"),
    ("en;q=0.4,fr;q=0.8", "fr"), ("fr;q=abc,en", "en"),
])
def test_accept_language_choice(header, want):
    assert _from_accept_language(header) == want


def test_dictionaries_have_the_same_keys_and_placeholders_and_no_cjk():
    assert set(EN) == set(FR)
    for key in EN:
        assert sorted(re.findall(r"\{\w+\}", EN[key])) == sorted(re.findall(r"\{\w+\}", FR[key])), key
        for d in (EN, FR):
            assert d[key].strip() and not re.search(r"[　-鿿＀-￯]", d[key]), key


def test_t_fills_placeholders_and_a_missing_key_fails_loudly():
    assert t("en", "ago.min", n=5) == "5 min" and t("fr", "ago.day", n=2) == "2 j"
    assert t("xx", "anom.ok") == "All normal"  # unknown language: English
    with pytest.raises(KeyError):
        t("en", "no.such.key")


def test_anomaly_texts_follow_lang():
    backup = {"last_ok_at": None, "last_ok_bytes": None, "latest_ok": None, "latest_at": None, "latest_error": None}
    en = anomalies.compute(NOW, [], [], [], None, [], 1400, 3.4, backup=backup)
    fr = anomalies.compute(NOW, [], [], [], None, [], 1400, 3.4, backup=backup, lang="fr")
    assert en[0]["detail"] == "no successful backup yet" and fr[0]["detail"] == "aucune sauvegarde réussie pour l’instant"
    assert anomalies.summarize(en) == "1 issue (red 1, yellow 0)" and anomalies.summarize(fr, "fr") == "1 anomalie (rouge 1, jaune 0)"
    assert anomalies.summarize(en + en) == "2 issues (red 2, yellow 0)"
    assert anomalies.summarize([], "fr") == "Tout est normal"


async def test_login_page_language_from_accept_language_and_default():
    async with make_client() as c:
        for headers, lang, title in ((None, "en", "Lutetia sign-in"), ({"Accept-Language": "en"}, "en", "Lutetia sign-in"),
                                     ({"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"}, "fr", "Connexion à Lutetia"),
                                     ({"Accept-Language": "zh-CN"}, "en", "Lutetia sign-in")):
            r = await c.get("/login", headers=headers)
            body = await r.text()
            assert r.status == 200 and '<html lang="%s">' % lang in body and "<h1>%s</h1>" % title in body, (headers, body[:200])
            assert COOKIE not in r.cookies  # nothing remembered without ?lang=


async def test_lang_query_overrides_and_sets_a_lax_year_cookie():
    async with make_client() as c:
        r = await c.get("/login?lang=fr", headers={"Accept-Language": "en"})
        body = await r.text()
        assert "Mot de passe" in body and '<html lang="fr">' in body
        m = r.cookies[COOKIE]
        assert m.value == "fr" and m["samesite"] == "Lax" and m["path"] == "/" and int(m["max-age"]) == 365 * 24 * 3600
        assert not m["httponly"]


async def test_cookie_applies_and_query_beats_cookie():
    async with make_client() as c:
        r = await c.get("/login", headers={"Cookie": COOKIE + "=fr", "Accept-Language": "en"})
        assert "Mot de passe" in await r.text()
        r = await c.get("/login?lang=en", headers={"Cookie": COOKIE + "=fr"})
        assert "Password" in await r.text() and r.cookies[COOKIE].value == "en"


@pytest.mark.parametrize("raw", ["de", "FR", "", "fr%00", "en,fr", "<script>"])
async def test_unknown_lang_values_are_ignored_and_not_remembered(raw):
    async with make_client() as c:
        r = await c.get("/login", params={"lang": raw}, headers={"Accept-Language": "fr"})
        body = await r.text()
        assert r.status == 200 and "Mot de passe" in body  # falls back to Accept-Language
        assert COOKIE not in r.cookies
        r = await c.get("/login", params={"lang": raw}, headers={"Cookie": COOKIE + "=" + raw})
        assert "Password" in await r.text() and COOKIE not in r.cookies  # bad cookie value: English


async def test_wrong_password_message_is_localised():
    async with make_client() as c:
        for lang, text in (("fr", "Nom d’utilisateur ou mot de passe incorrect"), ("en", "Wrong username or password")):
            r = await c.post("/login?lang=" + lang, data={"username": "orange", "password": "nope-" + secrets.token_hex(4), "next": ""},
                             allow_redirects=False)
            assert r.status == 401 and text in await r.text()


async def test_non_admin_notice_page_is_localised():
    async with make_client() as c:
        r = await c.post("/login", data={"username": "orange", "password": PWD["orange"], "next": ""}, allow_redirects=False)
        hdr = {"Cookie": "lutetia_session=" + r.cookies["lutetia_session"].value}
        body = await (await c.get("/dashboard/?lang=fr", headers=hdr)).text()
        assert "Le tableau de bord du projet sera bientôt disponible." in body and "Se déconnecter" in body and "Compte :" in body
        body = await (await c.get("/dashboard/", headers=hdr)).text()
        assert "The project dashboard is coming soon." in body and "Sign out" in body and "Account:" in body


async def test_header_language_switch_keeps_other_query_and_marks_current():
    async with make_client() as c:
        r = await c.post("/login", data={"username": "admin", "password": PWD["admin"], "next": ""}, allow_redirects=False)
        hdr = {"Cookie": "lutetia_session=" + r.cookies["lutetia_session"].value}
        body = await (await c.get("/dashboard/map?tracks=1&lang=fr", headers=hdr)).text()
        assert '<span aria-current="true">FR</span>' in body and "<a href=\"/dashboard/map?tracks=1&amp;lang=en\" hreflang=\"en\">EN</a>" in body
        assert 'aria-current="true">EN<' not in body and "lang=fr\" hreflang" not in body
        body = await (await c.get("/dashboard/map", headers={**hdr, "Accept-Language": "en"})).text()
        assert '<span aria-current="true">EN</span>' in body and 'href="/dashboard/map?lang=fr" hreflang="fr">FR</a>' in body


@pytest.mark.parametrize("lang", sorted(DICTS))
async def test_dictionary_script_served_per_language(lang):
    async with make_client() as c:
        r = await c.get("/i18n/%s.js" % lang)
        text = await r.text()
        assert r.status == 200 and "javascript" in r.headers["Content-Type"] and text.startswith("window.LUTETIA_I18N = {")
        assert "no-cache" in r.headers["Cache-Control"] and ("Tout est normal" in text) == (lang == "fr")
        assert (await c.get("/i18n/de.js")).status == 404


async def test_ops_scripts_load_dictionary_before_the_page_scripts():
    async with make_client() as c:
        r = await c.post("/login", data={"username": "admin", "password": PWD["admin"], "next": ""}, allow_redirects=False)
        hdr = {"Cookie": "lutetia_session=" + r.cookies["lutetia_session"].value}
        r = await c.get("/dashboard/map?lang=fr", headers=hdr)
        body = await r.text()
        assert r.status == 200 and body.index("/i18n/fr.js") < body.index("/static/i18n.js") < body.index("/static/map.js")
