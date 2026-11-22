"""
Stemmi delle squadre (21-22/11/2026, scelta di Valerio: opzione C «monogramma con banda»). Al posto dei loghi
ufficiali (marchi delle squadre, presi da ESPN e CollegeFootballData) il sito disegna uno stemma nostro: quadrato
arrotondato nel colore principale, banda nel secondo colore, sigla della squadra. Qui si preparano solo sigle e colori:
il disegno lo fa la pagina (`stemma` in index.html e duelli.html), così resta nitido a ogni misura.

Fonti:
  · NFL: anagrafica squadre nflverse (teams_colors_logos.csv: team_abbr, team_color, team_color2), gratis;
  · college: CollegeFootballData /teams (school, abbreviation, color, alternateColor), UNA chiamata per giro
    (uso commerciale consentito dalle condizioni di CFBD). Si lancia a mano (workflow stemmi.yml) e una volta l'anno.
Squadre college che CFBD non ha: sigla ricavata dal nome, banda bianca. Se una fonte non risponde, la sua parte
resta com'era nel file precedente. Scrive docs/stemmi.json. Solo libreria standard.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

RADICE = Path(__file__).resolve().parent.parent
USCITA = RADICE / "docs" / "stemmi.json"
NFL_URL = "https://github.com/nflverse/nflverse-data/releases/download/teams/teams_colors_logos.csv"
CFBD_URL = "https://api.collegefootballdata.com/teams"
UA = "PureStats/1.0 (statistiche personali)"
ESCLUSE_NFL = {"AFC", "NFC", "NFL"}


def scarica(url: str, intestazioni: dict | None = None) -> bytes | None:
    try:
        with urlopen(Request(url, headers={"User-Agent": UA, **(intestazioni or {})}), timeout=60) as r:
            return r.read()
    except Exception as e:                                                    # noqa: BLE001
        print(f"Stemmi: {url.split('?')[0]} non scaricato ({e}).")
        return None


def colore(x: str | None) -> str | None:
    x = (x or "").strip()
    if not x:
        return None
    x = x if x.startswith("#") else "#" + x
    return x.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", x) else None


def sigla_da_nome(nome: str) -> str:
    parole = [p for p in re.split(r"[\s\-&()'.]+", nome) if p]
    if len(parole) == 1:
        return parole[0][:4].upper()
    return "".join(p[0] for p in parole if p[0].isalnum())[:4].upper()


def nfl() -> dict | None:
    testo = scarica(NFL_URL)
    if not testo:
        return None
    out = {}
    for r in csv.DictReader(io.StringIO(testo.decode("utf-8"))):
        a = r.get("team_abbr", "").strip()
        if not a or a in ESCLUSE_NFL:
            continue
        out[a] = {"s": a, "c1": colore(r.get("team_color")) or "#555555", "c2": colore(r.get("team_color2")) or "#FFFFFF"}
    print(f"Stemmi: NFL {len(out)} squadre da nflverse.")
    return out


def college(nomi_sito: set[str]) -> dict | None:
    chiave = os.environ.get("CFBD_API_KEY", "").strip()
    if not chiave:
        print("Stemmi: CFBD_API_KEY non impostata, le sigle college restano quelle del file precedente.")
        return None
    print("Stemmi: 1 chiamata a CollegeFootballData (/teams).")
    dati = scarica(CFBD_URL, {"Authorization": f"Bearer {chiave}", "Accept": "application/json"})
    if not dati:
        return None
    out = {}
    for t in json.loads(dati):
        nome = (t.get("school") or "").strip()
        if not nome:
            continue
        sig = re.sub(r"[^A-Za-z0-9&]", "", t.get("abbreviation") or "")[:5].upper() or sigla_da_nome(nome)
        out[nome] = {"s": sig, "c1": colore(t.get("color")) or "#555555",
                     "c2": colore(t.get("alternateColor")) or "#FFFFFF"}
    mancanti = sorted(n for n in nomi_sito if n not in out)
    if mancanti:
        print(f"Stemmi: {len(mancanti)} squadre del sito non trovate su CFBD (sigla dal nome): {', '.join(mancanti[:20])}")
    print(f"Stemmi: college {len(out)} squadre da CollegeFootballData.")
    return out


def main() -> int:
    vecchio = {}
    if USCITA.exists():
        try:
            vecchio = json.loads(USCITA.read_text(encoding="utf-8"))
        except ValueError:
            print("Stemmi: docs/stemmi.json illeggibile, lo rifaccio da capo.")
    nomi = set()
    try:
        d = json.loads((RADICE / "docs" / "data_college.json").read_text(encoding="utf-8"))
        nomi = set(d.get("loghi", {})) | set(d.get("loghiExtra", {}))
    except (OSError, ValueError):
        pass
    out = {"nota": "Stemmi PureStats: sigla e colori della squadra, disegno nostro (nessun logo ufficiale).",
           "nfl": nfl() or vecchio.get("nfl", {}),
           "college": college(nomi) or vecchio.get("college", {})}
    # squadre del sito che non hanno ancora uno stemma: sigla dal nome, colore del sito se c'è
    try:
        for n in nomi:
            if n not in out["college"]:
                c = (d.get("loghi", {}).get(n) or d.get("loghiExtra", {}).get(n) or {}).get("colore")
                out["college"][n] = {"s": sigla_da_nome(n), "c1": colore(c) or "#555555", "c2": "#FFFFFF"}
    except NameError:
        pass
    tmp = USCITA.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(USCITA)
    print(f"Stemmi: scritto docs/stemmi.json (NFL {len(out['nfl'])}, college {len(out['college'])}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
