"""
Home College (dal 22/11/2026, senza dati ESPN pubblicati):
  · classifica ufficiale del comitato del College Football Playoff (prima che esca, l'AP Top 25) da
    CollegeFootballData /rankings (uso commerciale consentito): 1 chiamata per giro, al massimo una ogni 20 ore e
    solo nei giorni in cui escono le classifiche (AP la domenica sera americana, CFP il martedì sera: in UTC
    domenica, lunedì, mercoledì, giovedì) → al massimo 4 chiamate a settimana, circa 17 al mese;
  · forza delle squadre «rating PureStats», calcolato qui dai risultati della stagione (data/college.csv): margine
    corretto per gli avversari (scarto limitato a 28 punti, fattore campo +2,96, zero in campo neutro, le FCS
    contano come un'unica squadra), con un piccolo freno verso la media. Nessuna chiamata, numeri nostri.
Bilanci dai risultati in archivio. Se CFBD non risponde la classifica resta quella di prima. Solo libreria standard.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

RADICE = Path(__file__).resolve().parent.parent
USCITA = RADICE / "docs" / "home_college.json"
PUBBLICO = RADICE / "docs" / "data_college.json"
PARTITE = RADICE / "data" / "college.csv"
CFBD = "https://api.collegefootballdata.com/rankings"
UA = "PureStats/1.0 (statistiche sportive)"
POLL_CFP, POLL_AP = "Playoff Committee Rankings", "AP Top 25"
CAMPO, TETTO, FRENO = 2.96, 28, 2.0


def leggi_partite(stagione: int) -> list[dict]:
    out = []
    with PARTITE.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["Stagione"] != str(stagione) or not r["PuntiCasa"] or not r["PuntiOspite"]:
                continue
            out.append({"sett": int(r["Settimana"] or 0), "tipo": r["Tipo"], "casa": r["Casa"], "ospite": r["Ospite"],
                        "pc": int(r["PuntiCasa"]), "po": int(r["PuntiOspite"]),
                        "neutro": r["CampoNeutro"].strip().lower() in ("1", "true", "si", "sì", "yes")})
    return out


def bilanci(partite: list[dict]) -> dict:
    b = {}
    for p in partite:
        for sq, f, s in ((p["casa"], p["pc"], p["po"]), (p["ospite"], p["po"], p["pc"])):
            v, sc = b.get(sq, (0, 0))
            b[sq] = (v + (f > s), sc + (f < s))
    return {k: f"{v}-{s}" for k, (v, s) in b.items()}


def rating(partite: list[dict], fbs: set[str]) -> dict:
    """Margine medio corretto per gli avversari (iterazione alla Gauss-Seidel), media FBS = 0."""
    chi = lambda x: x if x in fbs else "FCS"
    righe = [(chi(p["casa"]), chi(p["ospite"]),
              max(-TETTO, min(TETTO, p["pc"] - p["po"])) - (0 if p["neutro"] else CAMPO)) for p in partite]
    r = {t: 0.0 for c, o, _ in righe for t in (c, o)}
    for _ in range(300):
        somma = {t: 0.0 for t in r}
        conta = {t: 0 for t in r}
        for c, o, m in righe:
            somma[c] += m + r[o]; conta[c] += 1
            somma[o] += -m + r[c]; conta[o] += 1
        r = {t: somma[t] / (conta[t] + FRENO) for t in r}
        media = sum(v for t, v in r.items() if t in fbs) / max(1, sum(1 for t in r if t in fbs))
        r = {t: v - media for t, v in r.items()}
    return {t: v for t, v in r.items() if t in fbs}


def forza(partite: list[dict], fbs: set[str], bil: dict) -> dict | None:
    if not partite:
        return None
    ultima = max(p["sett"] for p in partite if p["tipo"] == "regular") if any(p["tipo"] == "regular" for p in partite) else 0
    ora = rating(partite, fbs)
    prima = rating([p for p in partite if p["tipo"] == "regular" and p["sett"] < ultima], fbs)
    pos_prima = {t: i + 1 for i, (t, _) in enumerate(sorted(prima.items(), key=lambda x: -x[1]))}
    lista = sorted(ora.items(), key=lambda x: -x[1])[:25]
    return {"settimana": ultima, "squadre": [{"pos": i + 1, "prec": pos_prima.get(t), "nome": t, "rating": round(v, 1),
                                               "bilancio": bil.get(t)} for i, (t, v) in enumerate(lista)]}


def chiama_cfbd(stagione: int, vecchio: dict) -> list | None:
    chiave = os.environ.get("CFBD_API_KEY", "").strip()
    if not chiave:
        print("Home College: CFBD_API_KEY non impostata, la classifica resta com'era.")
        return None
    ora = dt.datetime.now(dt.timezone.utc)
    if ora.weekday() not in (6, 0, 2, 3):
        print("Home College: oggi non escono classifiche, nessuna chiamata a CollegeFootballData.")
        return None
    letto = vecchio.get("lettoCfbd")
    if letto and ora - dt.datetime.fromisoformat(letto.replace("Z", "+00:00")) < dt.timedelta(hours=20):
        print(f"Home College: classifica letta da meno di 20 ore ({letto}), nessuna chiamata.")
        return None
    print("Home College: 1 chiamata a CollegeFootballData (/rankings).")
    try:
        req = Request(f"{CFBD}?{urlencode({'year': stagione})}",
                      headers={"User-Agent": UA, "Authorization": f"Bearer {chiave}", "Accept": "application/json"})
        with urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as e:
        print(f"Home College: CollegeFootballData non risponde ({type(e).__name__} {getattr(e, 'code', '')}), la classifica resta com'era.")
        return None


def classifica(dati: list, bil: dict) -> dict | None:
    """Ultima classifica CFP della stagione; se non è ancora uscita, l'ultimo AP Top 25. Posizione precedente dalla
    settimana prima dello stesso sondaggio."""
    for nome_poll, tipo, titolo in ((POLL_CFP, "cfp", "Classifica ufficiale CFP"), (POLL_AP, "ap", "AP Top 25")):
        uscite = []
        for w in dati or []:
            for poll in w.get("polls") or []:
                if poll.get("poll") == nome_poll and poll.get("ranks"):
                    uscite.append((w.get("seasonType") == "postseason", w.get("week") or 0, poll["ranks"]))
        if not uscite:
            continue
        uscite.sort()
        _, sett, ranks = uscite[-1]
        prima = {x["school"]: x["rank"] for x in uscite[-2][2]} if len(uscite) > 1 else {}
        return {"tipo": tipo, "titolo": titolo, "settimana": sett,
                "squadre": [{"pos": x["rank"], "prec": prima.get(x["school"]), "nome": x["school"],
                             "bilancio": bil.get(x["school"]), "conference": x.get("conference")}
                            for x in sorted(ranks, key=lambda x: x["rank"])][:25]}
    print("Home College: nella risposta di CollegeFootballData non c'è né la classifica CFP né l'AP.")
    return None


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
    stagione = max((int(s) for s in pubblico.get("stagioni", []) if str(s).isdigit()), default=dt.date.today().year)
    fbs = set(pubblico.get("loghi") or {})
    partite = leggi_partite(stagione)
    bil = bilanci(partite)
    out = {k: v for k, v in vecchio.items() if k not in ("fpi",)}
    dati = chiama_cfbd(stagione, vecchio)
    if dati is not None:
        out["lettoCfbd"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        c = classifica(dati, bil)
        if c:
            out["classifica"] = c
            print(f"Home College: {c['titolo']} (week {c['settimana']}), {len(c['squadre'])} squadre.")
    elif out.get("classifica"):
        for s in out["classifica"].get("squadre", []):        # bilanci aggiornati anche senza chiamata
            s["bilancio"] = bil.get(s["nome"], s.get("bilancio"))
            s.pop("logo", None)
    f = forza(partite, fbs, bil)
    if f:
        out["forza"] = f
        print(f"Home College: rating PureStats, prime 25 su {len(fbs)} squadre FBS (fino alla week {f['settimana']}).")
    out["aggiornato"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    out["fonte"] = "Classifiche CFP e AP: CollegeFootballData. Rating: PureStats dai risultati della stagione."
    tmp = USCITA.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(USCITA)
    return 0


if __name__ == "__main__":
    sys.exit(main())
