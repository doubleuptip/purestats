"""Contesto della partita per la sezione Matchup: assenze, meteo, forza delle squadre.

Fonti (verificate il 13/11/2026, robots.txt rispettato):
- Infortuni college: CFBDepth (cfbdepth.com, robots: tutto consentito), scheda pubblica «Injury/Status» di ognuna
  delle 138 squadre FBS. Si tengono stato, ruolo, valutazione, peso dell'assenza, data e «novità», mai le note.
- Infortuni NFL: nflverse injuries_<stagione>.csv (CC-BY).
- Meteo: NWS api.weather.gov (servizio meteo ufficiale USA, previsione oraria a 7 giorni, gratuito) con Open-Meteo
  (gratuito non commerciale, CC-BY 4.0) per raffiche e come riserva.
- Stadi: CollegeFootballData /teams (coordinate e stadio coperto) per il college, tabella fissa per l'NFL.
Ogni funzione può fallire senza fermare la sezione: in quel caso il campo resta vuoto (mai inventato).
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import os
import re
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "PureStats/1.0 (github.com/doubleuptip/purestats; uso personale)",
      "Accept": "application/json,text/plain,*/*"}


def _get(url: str, timeout: int = 40, intestazioni: dict | None = None) -> str:
    req = urllib.request.Request(url, headers={**UA, **(intestazioni or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def norm(nome: str) -> str:
    s = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("state", "st").replace("saint", "st")
    return re.sub(r"[^a-z0-9]", "", s)


# ------------------------------------------------------------------ infortuni college (CFBDepth)
CFBD_ALIAS = {norm(a): norm(b) for a, b in {
    "Miami": "Miami (FL)", "Miami (OH)": "Miami OH", "Ole Miss": "Mississippi", "UConn": "Connecticut",
    "Hawai'i": "Hawaii", "San José State": "San Jose State", "UL Monroe": "Louisiana Monroe",
    "Southern Miss": "Southern Mississippi", "UTSA": "UT San Antonio", "App State": "Appalachian State",
    "Sam Houston": "Sam Houston State", "UMass": "Massachusetts", "FIU": "Florida International",
    "FAU": "Florida Atlantic", "NC State": "North Carolina State", "USF": "South Florida",
    "UCF": "Central Florida", "SMU": "Southern Methodist", "TCU": "Texas Christian", "BYU": "Brigham Young",
    "UNLV": "Nevada Las Vegas", "UTEP": "Texas El Paso", "LSU": "Louisiana State",
}.items()}

STATI_CFB = {"O": "Fuori", "OFS": "Fuori per la stagione", "Q": "In dubbio", "D": "Probabilmente fuori",
             "P": "Probabile", "GTD": "Decisione all'ultimo", "S": "Sospeso"}


def _registro_cfbdepth() -> list[dict]:
    js = _get("https://cfbdepth.com/team-pages/team-config.js")
    m = re.search(r"window\.CFB_TEAMS\s*=\s*(\[.*?\]);?\s*$", js, re.S) or re.search(r"=\s*(\[.*\])", js, re.S)
    return json.loads(m.group(1))


def _num(x):
    try:
        return float(str(x).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _leggi_scheda_infortuni(s: dict) -> dict | None:
    url = f"https://cfbdepth.com/team-pages/api/sheets/{s['spreadsheetId']}/data?gid={s['injuryReport']}"
    j = json.loads(_get(url))
    if not j.get("success"):
        return None
    righe = [[v for v in r.values()] for r in j.get("rows") or []]
    out = {"n": None, "nuovi": None, "impatto": None, "rango": None, "giocatori": []}
    intest = None
    for r in righe:
        vals = [str(v).strip() for v in r]
        piene = [v for v in vals if v]
        # sotto la lista ci sono altre tabelle: ci si ferma alla prima riga vuota o al numero del riepilogo
        if intest is not None and (not piene or (out["n"] and len(out["giocatori"]) >= out["n"])):
            break
        if not piene:
            continue
        if "Impact Rank:" in vals:            # riga di riepilogo: #: 17 · # New: 4 · Impact: 38 · Impact Rank: 3
            def dopo(etichetta):
                try:
                    return _num(vals[vals.index(etichetta) + 1])
                except (ValueError, IndexError):
                    return None
            out.update({"n": dopo("#:"), "nuovi": dopo("# New:"), "impatto": dopo("Impact:"),
                        "rango": dopo("Impact Rank:")})
            continue
        if "Player Name" in vals and "Status" in vals:
            intest = {k: vals.index(k) for k in ("Player Name", "Status", "Pos", "New", "Rating", "Impact",
                                                  "Update Date") if k in vals}
            continue
        if intest and vals[intest["Player Name"]] and vals[intest["Status"]]:
            g = {"nome": vals[intest["Player Name"]], "stato": vals[intest["Status"]],
                 "ruolo": vals[intest.get("Pos", 0)] if "Pos" in intest else "",
                 "nuovo": vals[intest["New"]].upper() == "TRUE" if "New" in intest else False,
                 "valutazione": _num(vals[intest["Rating"]]) if "Rating" in intest else None,
                 "peso": _num(vals[intest["Impact"]]) if "Impact" in intest else None,
                 "data": vals[intest["Update Date"]] if "Update Date" in intest else ""}
            g["statoIt"] = STATI_CFB.get(g["stato"].upper(), g["stato"])
            out["giocatori"].append(g)
    out["giocatori"].sort(key=lambda g: (-(g["peso"] or 0), -(g["valutazione"] or 0)))
    return out


def infortuni_college(squadre: set[str], pausa: float = 2.0) -> dict:
    """{squadra cfbfastR: scheda infortuni} per le squadre richieste. Una richiesta per squadra, con pausa."""
    try:
        reg = _registro_cfbdepth()
    except Exception as e:                   # noqa: BLE001
        print(f"Infortuni college: registro CFBDepth non letto ({e}): niente assenze in questo giro.")
        return {}
    per_nome = {}
    for s in reg:
        for k in (s.get("schoolName"), s.get("fullName"), s.get("abbreviation")):
            if k:
                per_nome.setdefault(norm(k), s)
    out, mancanti = {}, []
    for sq in sorted(squadre):
        s = per_nome.get(norm(sq)) or per_nome.get(CFBD_ALIAS.get(norm(sq), "-"))
        if not s:
            mancanti.append(sq)
            continue
        try:
            d = _leggi_scheda_infortuni(s)
            if d:
                out[sq] = d
        except Exception as e:               # noqa: BLE001
            print(f"Infortuni college: {sq} non letto ({e})")
        time.sleep(pausa)
    print(f"Infortuni college: {len(out)} squadre lette da CFBDepth"
          + (f", non abbinate: {', '.join(mancanti[:8])}" if mancanti else ""))
    return out


# ------------------------------------------------------------------ infortuni NFL (nflverse)
STATI_NFL = {"Out": "Fuori", "Doubtful": "Probabilmente fuori", "Questionable": "In dubbio"}


def infortuni_nfl(stagione: int, settimana: int, quota: dict) -> dict:
    """{squadra: scheda} dall'ultimo rapporto nflverse della settimana. `quota` = {gsis: (quota produzione, ruolo)}
    per pesare l'assenza come quota delle yard della squadra."""
    url = f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{stagione}.csv"
    try:
        righe = list(csv.DictReader(io.StringIO(_get(url, 60))))
    except Exception as e:                   # noqa: BLE001
        print(f"Infortuni NFL: file nflverse non letto ({e})")
        return {}
    settimane = sorted({int(r["week"]) for r in righe if str(r.get("week", "")).isdigit()})
    print(f"Infortuni NFL: file con le settimane {settimane[-3:] if settimane else 'nessuna'}, cerco la {settimana}")
    out = {}
    for r in righe:
        if str(r.get("week")) != str(settimana) or r.get("report_status") not in STATI_NFL:
            continue
        if r.get("game_type") and r.get("game_type") not in ("REG", "POST", "WC", "DIV", "CON", "SB"):
            continue
        q, _ = quota.get(r.get("gsis_id"), (0.0, ""))
        d = out.setdefault(r["team"], {"n": 0, "nuovi": None, "impatto": 0.0, "rango": None, "giocatori": []})
        d["n"] += 1
        peso = round(q * 10, 1)                       # 10 = tutta la produzione della squadra
        if r["report_status"] in ("Out", "Doubtful"):
            d["impatto"] = round(d["impatto"] + peso, 1)
        d["giocatori"].append({"nome": r.get("full_name"), "stato": r["report_status"],
                               "statoIt": STATI_NFL[r["report_status"]], "ruolo": r.get("position"),
                               "nuovo": False, "valutazione": None, "peso": peso,
                               "data": (r.get("date_modified") or "")[:10]})
    for d in out.values():
        d["giocatori"].sort(key=lambda g: -(g["peso"] or 0))
    return out


NFL_NOMI = {"Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
            "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
            "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
            "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
            "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
            "Los Angeles Rams": "LA", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
            "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
            "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
            "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
            "Tennessee Titans": "TEN", "Washington Commanders": "WAS"}
STATI_ESPN = {"OUT": "Fuori", "DOUBTFUL": "Probabilmente fuori", "QUESTIONABLE": "In dubbio",
              "INJURED RESERVE": "Fuori (lista infortunati)", "SUSPENSION": "Sospeso"}


def infortuni_nfl_espn(quota_nome: dict) -> dict:
    """Rapporto infortuni corrente da ESPN (tutta la lega in una richiesta), pesato sulla produzione:
    quota_nome = {(sigla, nome normalizzato): quota}. «Nuovo» = aggiornato negli ultimi 3 giorni e fuori."""
    j = json.loads(_get("https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries", 60))
    oggi = datetime.now(timezone.utc).date()
    out = {}
    for t in j.get("injuries") or []:
        sigla = NFL_NOMI.get(t.get("displayName", ""))
        if not sigla:
            continue
        for e in t.get("injuries") or []:
            stato = str(e.get("status") or "").upper()
            if stato not in STATI_ESPN:
                continue
            a = e.get("athlete") or {}
            nome = a.get("displayName", "")
            pos = a.get("position") if isinstance(a.get("position"), dict) else {}
            q = quota_nome.get((sigla, norm(nome)), 0.0)
            data = str(e.get("date") or "")[:10]
            try:
                recente = (oggi - datetime.fromisoformat(data).date()).days <= 3
            except ValueError:
                recente = False
            d = out.setdefault(sigla, {"n": 0, "nuovi": 0, "impatto": 0.0, "rango": None, "giocatori": []})
            peso = round(q * 10, 1)
            fuori = stato in ("OUT", "DOUBTFUL", "INJURED RESERVE", "SUSPENSION")
            nuovo = recente and stato in ("OUT", "DOUBTFUL")
            d["n"] += 1
            d["nuovi"] += nuovo
            if fuori:
                d["impatto"] = round(d["impatto"] + peso, 1)
            d["giocatori"].append({"nome": nome, "stato": stato, "statoIt": STATI_ESPN[stato],
                                   "ruolo": (pos or {}).get("abbreviation", ""), "nuovo": nuovo,
                                   "valutazione": None, "peso": peso, "data": data})
    if not out:
        raise ValueError("rapporto ESPN vuoto o formato cambiato")
    for d in out.values():
        d["giocatori"].sort(key=lambda g: -(g["peso"] or 0))
    return out


# ------------------------------------------------------------------ stadi e meteo
# Stadi NFL: (latitudine, longitudine, coperto). Coperto = tetto fisso o di solito chiuso: niente meteo.
STADI_NFL = {
    "ARI": (33.5277, -112.2626, True), "ATL": (33.7554, -84.4008, True), "BAL": (39.2780, -76.6227, False),
    "BUF": (42.7738, -78.7870, False), "CAR": (35.2258, -80.8528, False), "CHI": (41.8623, -87.6167, False),
    "CIN": (39.0955, -84.5161, False), "CLE": (41.5061, -81.6995, False), "DAL": (32.7473, -97.0945, True),
    "DEN": (39.7439, -105.0201, False), "DET": (42.3400, -83.0456, True), "GB": (44.5013, -88.0622, False),
    "HOU": (29.6847, -95.4107, True), "IND": (39.7601, -86.1639, True), "JAX": (30.3239, -81.6373, False),
    "KC": (39.0489, -94.4839, False), "LV": (36.0909, -115.1833, True), "LAC": (33.9535, -118.3392, True),
    "LA": (33.9535, -118.3392, True), "MIA": (25.9580, -80.2389, False), "MIN": (44.9737, -93.2575, True),
    "NE": (42.0909, -71.2643, False), "NO": (29.9511, -90.0812, True), "NYG": (40.8135, -74.0745, False),
    "NYJ": (40.8135, -74.0745, False), "PHI": (39.9008, -75.1675, False), "PIT": (40.4468, -80.0158, False),
    "SF": (37.4030, -121.9700, False), "SEA": (47.5952, -122.3316, False), "TB": (27.9759, -82.5033, False),
    "TEN": (36.1665, -86.7713, False), "WAS": (38.9077, -76.8645, False),
}


def stadi_college(chiave: str = "", anno: int = 0) -> dict:
    """{squadra: (lat, lon, coperto)} dal file data/college_stadi.json (stadi di casa, scaricati una volta sola:
    gli stadi non cambiano durante la stagione). Nessuna chiamata. I parametri restano per compatibilità."""
    percorso = Path(__file__).resolve().parent.parent / "data" / "college_stadi.json"
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8")).get("squadre") or {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"Stadi college non letti da {percorso.name} ({e}): meteo college assente in questo giro.")
        return {}
    return {sq: (float(v[0]), float(v[1]), bool(v[2])) for sq, v in dati.items()}


def _mph(testo: str) -> float | None:
    n = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(testo or ""))]
    return max(n) if n else None


def meteo(lat: float, lon: float, inizio_utc: datetime) -> dict | None:
    """Meteo all'ora del calcio d'inizio: NWS (ufficiale USA) per vento e temperatura, Open-Meteo per raffiche
    e pioggia (e come riserva). Solo entro 7 giorni. Temperatura in °C, vento in km/h e mph."""
    if inizio_utc - datetime.now(timezone.utc) > timedelta(days=7):
        return None
    out = {"fonte": None}
    try:
        p = json.loads(_get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", 30))
        ore = json.loads(_get(p["properties"]["forecastHourly"], 30))["properties"]["periods"]
        best = min(ore, key=lambda o: abs((datetime.fromisoformat(o["startTime"]) - inizio_utc).total_seconds()))
        out.update({"fonte": "NWS", "tempF": best.get("temperature"), "ventoMph": _mph(best.get("windSpeed")),
                    "direzione": best.get("windDirection"), "cielo": best.get("shortForecast"),
                    "pioggia": (best.get("probabilityOfPrecipitation") or {}).get("value")})
    except Exception as e:                   # noqa: BLE001
        print(f"Meteo NWS non letto per {lat},{lon} ({e}): uso Open-Meteo")
    try:
        u = (f"https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}"
             "&hourly=temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation_probability"
             "&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone=UTC&forecast_days=8")
        try:
            h = json.loads(_get(u, 30))["hourly"]
        except Exception:                    # noqa: BLE001 - a volte la prima connessione scade: un secondo tentativo
            time.sleep(3)
            h = json.loads(_get(u, 45))["hourly"]
        idx = min(range(len(h["time"])), key=lambda i: abs(
            (datetime.fromisoformat(h["time"][i]).replace(tzinfo=timezone.utc) - inizio_utc).total_seconds()))
        out["raffiche"] = h["wind_gusts_10m"][idx]
        if out["fonte"] is None:
            out.update({"fonte": "Open-Meteo", "tempF": h["temperature_2m"][idx], "ventoMph": h["wind_speed_10m"][idx],
                        "pioggia": h["precipitation_probability"][idx]})
    except Exception as e:                   # noqa: BLE001
        print(f"Meteo Open-Meteo non letto per {lat},{lon} ({e})")
    if out["fonte"] is None:
        return None
    if out.get("tempF") is not None:
        out["tempC"] = round((float(out["tempF"]) - 32) * 5 / 9)
    if out.get("ventoMph") is not None:
        out["ventoKmh"] = round(float(out["ventoMph"]) * 1.609)
    if out.get("raffiche") is not None:
        out["raffiche"] = round(float(out["raffiche"]))
        out["raffKmh"] = round(out["raffiche"] * 1.609)
    out["effetto"] = effetto_meteo(out.get("ventoMph"), out.get("tempF"))
    return out


# Misura del 13/11 (misure/meteo_nfl.py): 3.585 partite NFL all'aperto 2006-2025, punti reali − linea di chiusura.
EFFETTO_VENTO = [(0, 10, None), (10, 15, (-0.4, 55)), (15, 20, (-1.6, 56)), (20, 999, (-0.6, 54))]


def effetto_meteo(vento: float | None, temp_f: float | None) -> dict | None:
    if vento is None:
        return None
    for a, b, e in EFFETTO_VENTO:
        if a <= vento < b:
            if not e:
                return None
            testo = (f"vento {round(vento)} mph ({round(vento * 1.609)} km/h): nello storico NFL "
                     f"{e[0]:+.1f}".replace(".", ",").replace("-", "−") + f" punti rispetto alla linea, under {e[1]}% delle volte")
            if vento >= 15 and temp_f is not None and temp_f < 40:
                testo += " (con il freddo sotto i 4 °C: under 62%, su poche partite)"
            return {"punti": e[0], "under": e[1], "testo": testo}
    return None


def kickoff_utc(data: str, ora: str) -> datetime | None:
    """Data e ora della partita in ET (come nei calendari) → UTC."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromisoformat(f"{data}T{ora or '12:00'}").replace(
            tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    except Exception:                        # noqa: BLE001
        return None


# ------------------------------------------------------------------ forza delle squadre (dalle azioni di gioco)
def forza_squadre(azioni, min_azioni: int = 150) -> dict:
    """Success rate (azioni con EPA > 0, la definizione di nflverse) ed EPA per azione, in attacco e concessi in
    difesa, su corse e passaggi; con la posizione tra le squadre (1 = la migliore, in difesa = chi concede meno)."""
    acc = {}
    for _w, _g, o, d, tipo, epa, _y, _s in azioni:
        for sq, lato in ((o, "att"), (d, "dif")):
            a = acc.setdefault(sq, {"att": [0, 0, 0.0, 0, 0.0, 0, 0.0], "dif": [0, 0, 0.0, 0, 0.0, 0, 0.0]})[lato]
            a[0] += 1
            a[1] += epa > 0
            a[2] += epa
            if tipo == "P":
                a[3] += 1
                a[4] += epa
            else:
                a[5] += 1
                a[6] += epa
    base = {}
    for sq, v in acc.items():
        if v["att"][0] < min_azioni or v["dif"][0] < min_azioni:
            continue
        r = {}
        for lato in ("att", "dif"):
            n, ok, e, npas, epas, ncor, ecor = v[lato]
            r[lato] = {"successo": ok / n, "epa": e / n, "epaPass": epas / npas if npas else None,
                       "epaCorsa": ecor / ncor if ncor else None}
        base[sq] = r
    for lato, verso in (("att", -1), ("dif", 1)):          # attacco: più alto = meglio; difesa: più basso = meglio
        for k in ("successo", "epa", "epaPass", "epaCorsa"):
            ordine = sorted((sq for sq in base if base[sq][lato][k] is not None),
                            key=lambda sq: verso * base[sq][lato][k])
            for i, sq in enumerate(ordine, 1):
                base[sq][lato]["rango_" + k] = i
    n = len(base)
    for sq, r in base.items():
        r["n"] = n
        for lato in ("att", "dif"):
            for k in ("successo", "epa", "epaPass", "epaCorsa"):
                if r[lato][k] is not None:
                    r[lato][k] = round(r[lato][k], 3)
    return base
