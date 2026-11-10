"""Ops dashboard languages: English and French only (Spec v1.13 "interface language"). The language comes from `?lang=` (which also
sets the `lutetia_lang` cookie), else that cookie, else Accept-Language, else English. Server templates call t(lang, key, **vars);
the static scripts get the whole dictionary of the chosen language from /i18n/<lang>.js (see page() in html.py and static/i18n.js);
it is a separate file so the page text itself stays exactly what the user reads.
Placeholders are `{name}`; static/i18n.js fills them the same way, so keep them plain (no format specs, no literal braces)."""
import json
from typing import Dict, Optional

from aiohttp import web

LANGS = ("en", "fr")
DEFAULT_LANG = "en"
COOKIE = "lutetia_lang"
COOKIE_MAX_AGE = 365 * 24 * 3600

EN: Dict[str, str] = {
    "hdr.account": "Account:", "hdr.logout": "Sign out", "nav.board": "← Dashboard", "nav.map": "Map",
    "login.title": "Lutetia sign-in", "login.user": "Username", "login.password": "Password",
    "login.remember": "Keep me signed in for 30 days", "login.submit": "Sign in",
    "login.locked": "Too many attempts, please try again later", "login.wrong": "Wrong username or password",
    "soon.text": "The project dashboard is coming soon.", "soon.open": "Open the project dashboard",
    "dev.notfound": "Device not found", "dash.title": "Lutetia dashboard",
    "sec.devices": "Devices", "sec.sensors": "Latest readings", "sec.gps": "Last positions", "sec.collector": "Collector status",
    "sec.latest": "Latest reports", "sec.attrs": "Attributes", "sec.positions": "Recent positions",
    "col.name": "Name", "col.type": "Type", "col.online": "Expected online", "col.last": "Last stored", "col.age": "Age",
    "col.status": "Status", "col.time": "Time", "col.value": "Value", "col.raw": "Raw value", "col.updated": "Updated",
    "col.calls": "Calls (24 h)", "yes": "yes", "no": "no", "state.stale": "STALE",
    "ago.min": "{n} min", "ago.hour": "{n} h", "ago.day": "{n} d",
    "kind.collector": "Collector", "kind.stale": "Offline", "kind.low_volt": "Low voltage", "kind.alarm": "Alarm",
    "kind.push": "Push channel", "kind.backup": "Backup", "kind.quota": "Quota", "kind.login": "Logins",
    "anom.title": "Anomalies · {summary}", "anom.ok": "All normal", "anom.summary": "{n} issues (red {red}, yellow {yellow})",
    "anom.summary1": "{n} issue (red {red}, yellow {yellow})",
    "d.never_stored": "never stored", "d.stale": "last stored {h} h ago", "d.volt": "voltage {v} V",
    "d.quota": "GPS51 24 h {n} / {budget}", "d.login": "Dingtek logged in {n} times in 24 h",
    "d.push": "push positions silent for {m} min (limit {lim} min)",
    "d.backup_never": "no successful backup yet", "d.backup_old": "{h} h since the last successful backup (limit {lim} h)",
    "d.backup_fail": "latest backup failed: {err}", "d.no_err": "no error message",
    "d.col_never": "collector has never reported a heartbeat",
    "d.col_stale": "collector heartbeat not updated for {m} min {s} s (limit {lim} s)",
    "cl.never": "Collector has never reported a heartbeat", "cl.ws_off": "WS disabled", "cl.ws_on": "WS connected",
    "cl.ws_down": "WS disconnected", "cl.polling": "polling", "cl.push": "push",
    "cl.stale": "Collector heartbeat is stale, last known ({at}): {state}",
    "cl.fresh": "Collector heartbeat: {at} ({age} s ago) · {state}", "time.paris": "{t} Paris time",
    "rec.none": "The collector has not reported a heartbeat yet",
    "rec.stale": "Receiver counters below are the last known values (collector heartbeat is stale)",
    "info.started": "Web started {t}", "info.generated": "Generated {t}", "info.failed": "Refresh failed {t}",
    "bk.none": "Last backup: none", "bk.line": "Last backup: {at} · {size}",
    "map.title": "Location map", "map.tracks": "Last 7 days' tracks", "map.last": "Last positions only",
    "map.base": "Base map", "pos.none": "No position yet", "pos.noneyet": "no position", "load.failed": "Failed to load",
    "dev.sub": "Type {type} · expected online {online} · last stored {last} · age {age}",
    "dev.days7": "7 days", "dev.days30": "30 days", "chart.volt": "Voltage (V)", "chart.temperature": "Temperature",
    "chart.rsrp": "Signal rsrp (dBm)", "chart.hourly": "30 days, hourly average",
    "chart.truncated": "Showing the latest 1500 points only",
    "gps.stats": "Odometer {km} · moving {moving} · last position {t} · source {origin}",
    "pop.last": "Last time {v}", "pop.speed": "Speed {v}", "pop.odo": "Odometer {v}", "pop.moving": "Moving {v}",
    "pop.volt": "Voltage {v}", "pop.temp": "Temperature {v}", "pop.manhole": "Manhole",
    "kind.dingtek": "Dingtek manhole", "kind.gps51": "GPS51 tracker", "gps.nokm": "—",
}

FR: Dict[str, str] = {
    "hdr.account": "Compte :", "hdr.logout": "Se déconnecter", "nav.board": "← Tableau de bord", "nav.map": "Carte",
    "login.title": "Connexion à Lutetia", "login.user": "Nom d’utilisateur", "login.password": "Mot de passe",
    "login.remember": "Rester connecté pendant 30 jours", "login.submit": "Se connecter",
    "login.locked": "Trop de tentatives, réessayez plus tard", "login.wrong": "Nom d’utilisateur ou mot de passe incorrect",
    "soon.text": "Le tableau de bord du projet sera bientôt disponible.", "soon.open": "Ouvrir le tableau de bord du projet",
    "dev.notfound": "Appareil introuvable", "dash.title": "Tableau de bord Lutetia",
    "sec.devices": "Appareils", "sec.sensors": "Dernières mesures", "sec.gps": "Dernières positions", "sec.collector": "État du collecteur",
    "sec.latest": "Derniers rapports", "sec.attrs": "Attributs", "sec.positions": "Positions récentes",
    "col.name": "Nom", "col.type": "Type", "col.online": "Attendu en ligne", "col.last": "Dernier enregistrement", "col.age": "Ancienneté",
    "col.status": "Statut", "col.time": "Heure", "col.value": "Valeur", "col.raw": "Valeur brute", "col.updated": "Mis à jour",
    "col.calls": "Appels (24 h)", "yes": "oui", "no": "non", "state.stale": "OBSOLÈTE",
    "ago.min": "{n} min", "ago.hour": "{n} h", "ago.day": "{n} j",
    "kind.collector": "Collecteur", "kind.stale": "Hors ligne", "kind.low_volt": "Tension basse", "kind.alarm": "Alarme",
    "kind.push": "Canal push", "kind.backup": "Sauvegarde", "kind.quota": "Quota", "kind.login": "Connexions",
    "anom.title": "Anomalies · {summary}", "anom.ok": "Tout est normal", "anom.summary": "{n} anomalies (rouge {red}, jaune {yellow})",
    "anom.summary1": "{n} anomalie (rouge {red}, jaune {yellow})",
    "d.never_stored": "jamais enregistré", "d.stale": "dernier enregistrement il y a {h} h", "d.volt": "tension {v} V",
    "d.quota": "GPS51 24 h : {n} / {budget}", "d.login": "Dingtek : {n} connexions en 24 h",
    "d.push": "aucune position reçue en push depuis {m} min (seuil {lim} min)",
    "d.backup_never": "aucune sauvegarde réussie pour l’instant", "d.backup_old": "{h} h depuis la dernière sauvegarde réussie (seuil {lim} h)",
    "d.backup_fail": "dernière sauvegarde en échec : {err}", "d.no_err": "aucun message d’erreur",
    "d.col_never": "le collecteur n’a jamais envoyé de battement",
    "d.col_stale": "battement du collecteur non mis à jour depuis {m} min {s} s (seuil {lim} s)",
    "cl.never": "Le collecteur n’a jamais envoyé de battement", "cl.ws_off": "WS désactivé", "cl.ws_on": "WS connecté",
    "cl.ws_down": "WS déconnecté", "cl.polling": "interrogation", "cl.push": "push",
    "cl.stale": "Battement du collecteur périmé, dernier état connu ({at}) : {state}",
    "cl.fresh": "Battement du collecteur : {at} (il y a {age} s) · {state}", "time.paris": "{t} heure de Paris",
    "rec.none": "Le collecteur n’a pas encore envoyé de battement",
    "rec.stale": "Les compteurs du récepteur ci-dessous sont les dernières valeurs connues (battement du collecteur périmé)",
    "info.started": "Web démarré {t}", "info.generated": "Généré {t}", "info.failed": "Échec de l’actualisation {t}",
    "bk.none": "Dernière sauvegarde : aucune", "bk.line": "Dernière sauvegarde : {at} · {size}",
    "map.title": "Carte des positions", "map.tracks": "Traces des 7 derniers jours", "map.last": "Dernières positions seulement",
    "map.base": "Fond de carte", "pos.none": "Aucune position pour l’instant", "pos.noneyet": "aucune position", "load.failed": "Échec du chargement",
    "dev.sub": "Type {type} · attendu en ligne : {online} · dernier enregistrement {last} · ancienneté {age}",
    "dev.days7": "7 jours", "dev.days30": "30 jours", "chart.volt": "Tension (V)", "chart.temperature": "Température",
    "chart.rsrp": "Signal rsrp (dBm)", "chart.hourly": "30 jours, moyenne horaire",
    "chart.truncated": "Seuls les 1500 derniers points sont affichés",
    "gps.stats": "Compteur {km} · en mouvement : {moving} · dernière position {t} · source {origin}",
    "pop.last": "Dernière heure {v}", "pop.speed": "Vitesse {v}", "pop.odo": "Compteur {v}", "pop.moving": "En mouvement : {v}",
    "pop.volt": "Tension {v}", "pop.temp": "Température {v}", "pop.manhole": "Regard",
    "kind.dingtek": "Regard Dingtek", "kind.gps51": "Traceur GPS51", "gps.nokm": "—",
}

DICTS: Dict[str, Dict[str, str]] = {"en": EN, "fr": FR}


def t(lang: str, key: str, **kw: object) -> str:
    """Text of `key` in `lang`. An unknown key raises KeyError: a missing translation is a bug, not something to hide."""
    text = DICTS[lang if lang in DICTS else DEFAULT_LANG][key]
    return text.format(**kw) if kw else text


def _from_accept_language(header: str) -> Optional[str]:
    """First English / French tag by quality (ties keep header order); other languages are skipped. None when there is none."""
    ranked = []
    for pos, part in enumerate(header.split(",")):
        tag, _, params = part.strip().partition(";")
        q = 1.0
        for p in params.split(";"):
            name, _, val = p.strip().partition("=")
            if name == "q":
                try:
                    q = float(val)
                except ValueError:
                    q = 0.0
        primary = tag.strip().lower().split("-")[0]
        if primary in LANGS and q > 0:
            ranked.append((-q, pos, primary))
    return min(ranked)[2] if ranked else None


def pick_lang(request: web.Request) -> str:
    """?lang= (en | fr; other values ignored) > lutetia_lang cookie > Accept-Language > English."""
    for cand in (request.query.get("lang"), request.cookies.get(COOKIE)):
        if cand in LANGS:
            return cand  # type: ignore[return-value]
    return _from_accept_language(request.headers.get("Accept-Language", "")) or DEFAULT_LANG


def remember_lang(resp: web.StreamResponse, request: web.Request) -> None:
    """A valid `?lang=` is remembered for a year; called for every response from app.security_headers."""
    lang = request.query.get("lang")
    if lang in LANGS:
        resp.set_cookie(COOKIE, lang, max_age=COOKIE_MAX_AGE, path="/", samesite="Lax")


async def dictionary_js(request: web.Request) -> web.Response:
    """GET /i18n/<lang>.js: `window.LUTETIA_I18N = {...}`. Not language-negotiated (the language is in the path); no-cache so a
    changed dictionary is never served stale after a deploy."""
    lang = request.match_info["lang"]
    if lang not in DICTS:
        raise web.HTTPNotFound(text="unknown language")
    body = "window.LUTETIA_I18N = %s;\n" % json.dumps(DICTS[lang], ensure_ascii=False)
    return web.Response(text=body, content_type="application/javascript", headers={"Cache-Control": "no-cache"})


def register_i18n(app: web.Application) -> None:
    app.router.add_get("/i18n/{lang}.js", dictionary_js)
