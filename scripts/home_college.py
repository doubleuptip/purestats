"""
Home College: classifica ufficiale del College Football Playoff (comitato CFP; prima che esca, l'AP Top 25) e
probabilità di andare ai playoff e alla finale secondo l'FPI di ESPN. Scrive docs/home_college.json.

Fonti ESPN, gratis, senza chiave: 2 richieste per giro (classifiche e FPI).
  site.api.espn.com/apis/site/v2/sports/football/college-football/rankings
  site.web.api.espn.com/apis/fitt/v3/sports/football/college-football/powerindex?season=<anno>&limit=200
Le squadre si chiamano come nel resto del sito: nome ESPN dall'id del logo (gli id ESPN e CollegeFootballData
coincidono). Se ESPN non risponde o cambia forma, il blocco resta com'era. Solo libreria standard.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RADICE = Path(__file__).resolve().parent.parent
USCITA = RADICE / "docs" / "home_college.json"
PUBBLICO = RADICE / "docs" / "data_college.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; PureStats/1.0; statistiche personali)"}
CLASSIFICHE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings"
FPI = ("https://site.web.api.espn.com/apis/fitt/v3/sports/football/college-football/powerindex"
       "?region=us&lang=en&season={s}&limit=200")
# colonne della categoria «fpi» (etichette ESPN): le cerchiamo per nome, non per posizione
COL_PLAYOFF, COL_FINALE = "PLAYOFFS%", "MAKE NC%"


def scarica(url: str):
    for i in range(3):
        try:
            with urlopen(Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as e:
            ultimo = e
            time.sleep(3 * (i + 1))
    print(f"Home College: ESPN non risponde per {url.split('?')[0].rsplit('/', 1)[-1]} ({ultimo}).")
    return None


def nomi_da_id(dati: dict) -> dict:
    """id ESPN → nome usato nel sito, dal numero nell'indirizzo del logo."""
    out = {}
    for gruppo in ("loghi", "loghiExtra"):
        for nome, l in (dati.get(gruppo) or {}).items():
            m = re.search(r"/(\d+)\.png", l.get("logo") or "")
            if m:
                out.setdefault(m.group(1), nome)
    return out


def nome(team: dict, mappa: dict) -> str:
    return mappa.get(str(team.get("id"))) or team.get("location") or team.get("nickname") or team.get("displayName") or "?"


def classifica(dati: dict, mappa: dict) -> dict | None:
    if not dati:
        return None
    elenco = dati.get("rankings") or []
    scelta = next((r for r in elenco if r.get("type") == "cfp"), None) or next((r for r in elenco if r.get("type") == "ap"), None)
    if not scelta or not scelta.get("ranks"):
        return None
    squadre = []
    for r in scelta["ranks"]:
        t = r.get("team") or {}
        squadre.append({"pos": r.get("current"), "prec": r.get("previous") or None, "nome": nome(t, mappa),
                        "bilancio": r.get("recordSummary"), "conference": r.get("conference"),
                        "logo": (t.get("logos") or [{}])[0].get("href") or t.get("logo")})
    w = re.search(r"Week (\d+)", scelta.get("headline") or "")
    return {"tipo": scelta.get("type"), "titolo": "Classifica ufficiale CFP" if scelta.get("type") == "cfp" else "AP Top 25",
            "settimana": int(w.group(1)) if w else None, "data": (scelta.get("date") or "")[:10], "squadre": squadre}


def fpi(dati: dict, mappa: dict) -> dict | None:
    if not dati or not dati.get("teams"):
        return None
    cat = next((c for c in dati.get("categories", []) if c.get("name") == "fpi"), None)
    etichette = (cat or {}).get("labels") or []
    if COL_PLAYOFF not in etichette:
        print(f"Home College: FPI senza la colonna {COL_PLAYOFF}: ESPN ha cambiato forma, il blocco resta com'era.")
        return None
    ip, ifin = etichette.index(COL_PLAYOFF), (etichette.index(COL_FINALE) if COL_FINALE in etichette else None)
    lista = []
    for x in dati["teams"]:
        c = next((c for c in x.get("categories", []) if c.get("name") == "fpi"), None)
        if not c:
            continue
        v = c.get("values") or []
        if len(v) <= ip:
            continue
        t = x.get("team") or {}
        lista.append({"nome": nome(t, mappa), "conference": ((t.get("group") or {}).get("shortName")),
                      "fpi": round(v[0], 1), "playoff": round(v[ip], 1),
                      "finale": round(v[ifin], 1) if ifin is not None and len(v) > ifin else None})
    lista.sort(key=lambda x: (-x["playoff"], -x["fpi"]))
    return {"squadre": [x for x in lista if x["playoff"] >= 0.5][:25], "aggiornato": dati.get("lastUpdated")}


def main() -> int:
    vecchio = {}
    try:
        vecchio = json.loads(USCITA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        pubblico = json.loads(PUBBLICO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pubblico = {}
    mappa = nomi_da_id(pubblico)
    out = dict(vecchio)
    c = classifica(scarica(CLASSIFICHE), mappa)
    if c:
        out["classifica"] = c
        print(f"Home College: {c['titolo']} (week {c['settimana']}), {len(c['squadre'])} squadre.")
    stagione = max((int(s) for s in pubblico.get("stagioni", []) if str(s).isdigit()), default=dt.date.today().year)
    f = fpi(scarica(FPI.format(s=stagione)), mappa)
    if f:
        out["fpi"] = f
        print(f"Home College: FPI, {len(f['squadre'])} squadre con almeno lo 0,5% di playoff.")
    senza = [x["nome"] for x in (out.get("classifica") or {}).get("squadre", []) if x["nome"] not in (pubblico.get("loghi") or {})]
    if senza:
        print(f"Home College: nomi non riconosciuti nei loghi del sito: {', '.join(senza)}")
    out["aggiornato"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    out["fonte"] = "ESPN: classifica del comitato CFP e Football Power Index"
    tmp = USCITA.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(USCITA)
    return 0


if __name__ == "__main__":
    sys.exit(main())
