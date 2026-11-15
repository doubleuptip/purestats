"""Linee del mercato americano per Charlie: spread e totale di ogni partita dalla lista partite di ESPN
(DraftKings di solito), gratis e senza chiave, una richiesta per campionato a ogni giro.

Il «prezzo giusto» di Charlie parte da qui: la linea americana è la più efficiente (Protocollo 8), e la
probabilità di qualunque linea si ricava dagli scarti misurati sullo storico 2019-2025.
Solo libreria standard.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "purestats (statistiche personali)", "Accept": "application/json"}
SITO = {"NFL": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "College": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"}
NFL_ESPN = {"LA": "LAR", "WAS": "WSH"}          # sigle nflverse diverse da ESPN


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _json(url: str, timeout: int = 40) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


def leggi_quota(odds: list, sigla_casa: str, sigla_ospite: str) -> dict | None:
    """Dalla voce «odds» di ESPN: margine atteso della squadra di casa (positivo = casa favorita) e totale.
    Si legge il testo «KC -3.5» (chi è favorito e di quanto), che è la forma più stabile; «EVEN» = 0."""
    for o in odds or []:
        prov = ((o.get("provider") or {}).get("name") or "").strip()
        if "live" in prov.lower():
            continue
        tot = o.get("overUnder")
        det = str(o.get("details") or "").strip()
        margine = None
        if det.upper() in ("EVEN", "PK", "PICK"):
            margine = 0.0
        else:
            m = re.match(r"^([A-Za-z&.' ]+?)\s*([+-]?\d+(?:\.\d+)?)$", det)
            if m:
                chi, v = m.group(1).strip().upper(), float(m.group(2))
                if chi == (sigla_casa or "").upper():
                    margine = -v
                elif chi == (sigla_ospite or "").upper():
                    margine = v
        if margine is None and o.get("spread") is not None:
            # riserva: «spread» di ESPN è dalla parte della casa (negativo = casa favorita)
            try:
                margine = -float(o["spread"])
            except (TypeError, ValueError):
                margine = None
        try:
            tot = float(tot) if tot is not None else None
        except (TypeError, ValueError):
            tot = None
        if margine is not None or tot is not None:
            return {"margineCasa": margine, "totale": tot, "fonte": prov or "ESPN"}
    return None


def _combacia(lega: str, team: dict, nome: str) -> int:
    if lega == "NFL":
        return 10 if (team.get("abbreviation") or "").upper() == NFL_ESPN.get(nome, nome).upper() else 0
    loc, n = _norm(team.get("location") or ""), _norm(nome)
    if not loc or not n:
        return 0
    if loc == n:
        return 1000
    return len(loc) if n.startswith(loc) or loc.startswith(n) else 0


def linee(lega: str, schede: list) -> int:
    """Aggiunge a ogni scheda «mercato» = {margineCasa, totale, fonte, ora, espnId}. Restituisce quante ne ha
    trovate. Se ESPN non risponde le schede restano con la linea del giro precedente."""
    date = sorted({sc.get("inizioUtc", "")[:10] for sc in schede if sc.get("inizioUtc")})
    if not date:
        return 0
    da = datetime.fromisoformat(date[0]).date() - timedelta(days=1)
    a = datetime.fromisoformat(date[-1]).date() + timedelta(days=1)
    url = f"{SITO[lega]}?dates={da:%Y%m%d}-{a:%Y%m%d}&limit=400" + ("&groups=80" if lega == "College" else "")
    eventi = _json(url).get("events") or []
    ora = datetime.now(timezone.utc).isoformat(timespec="minutes")
    trovate = 0
    for sc in schede:
        meglio, punti = None, 0
        for e in eventi:
            c = (e.get("competitions") or [{}])[0]
            casa = next((x for x in c.get("competitors") or [] if x.get("homeAway") == "home"), {})
            osp = next((x for x in c.get("competitors") or [] if x.get("homeAway") == "away"), {})
            p1, p2 = _combacia(lega, casa.get("team") or {}, sc["casa"]), _combacia(lega, osp.get("team") or {}, sc["ospite"])
            if p1 and p2 and p1 + p2 > punti:
                meglio, punti = (e, c, casa, osp), p1 + p2
        if not meglio:
            continue
        e, c, casa, osp = meglio
        q = leggi_quota(c.get("odds"), (casa.get("team") or {}).get("abbreviation"),
                        (osp.get("team") or {}).get("abbreviation"))
        vecchio = sc.get("mercato") or {}
        nuovo = {"espnId": str(e.get("id") or vecchio.get("espnId") or "")}
        if q:
            nuovo.update(q, ora=ora)
            trovate += 1
        elif vecchio.get("totale") is not None or vecchio.get("margineCasa") is not None:
            nuovo.update({k: vecchio.get(k) for k in ("margineCasa", "totale", "fonte", "ora")})
        sc["mercato"] = nuovo
    return trovate
