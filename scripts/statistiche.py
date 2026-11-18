"""
Statistiche pubbliche (18/11/2026): prepara i dati della vista «Statistiche» (giocatori e squadre, NFL e College).

Uso:  python scripts/statistiche.py nfl            stagione in corso
      python scripts/statistiche.py college 2019-2026

Scrive docs/stats/<lega>_<stagione>_<categoria>.json, uno per categoria (passaggi, corse, ricezioni, difesa, calci,
punt, ritorni), che la pagina scarica solo quando servono, e docs/stats/indice_<lega>.json con stagioni e week disponibili.
Ogni file: {"basi": [nomi], "max": [basi da prendere come massimo], "giocatori": {id: [nome, ruolo]},
"squadre": [nomi], "righe": [[id, week, n° squadra, n° avversario, valori...]]}. Una riga per giocatore e partita: la pagina somma per
periodo (stagione, ultime week, una week) e calcola i valori derivati (percentuali, medie, rating).
Le squadre si ottengono sommando i giocatori (fatte) e gli avversari (concesse).

Fonti, senza chiamate in più: NFL statistiche settimanali nflverse (CC-BY 4.0, stesso file dei leader della
Giornata); College tabellini ESPN già in archivio (data/college_tabellini_<stagione>.json). Solo stagione regolare.
Le pressioni (Pro Football Reference) NON entrano: non si possono ripubblicare.
Solo libreria standard; se una stagione non si scarica, i file di prima restano.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
USCITA = RADICE / "docs" / "stats"
sys.path.insert(0, str(Path(__file__).resolve().parent))

# NFL: categoria → (colonne nflverse, colonne da prendere come massimo, condizione per tenere la riga)
NFL = {
    "passaggi": (["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered",
                  "passing_first_downs", "passing_epa"], [], "attempts"),
    "corse": (["carries", "rushing_yards", "rushing_tds", "rushing_first_downs", "rushing_fumbles_lost", "rushing_epa"],
              [], "carries"),
    "ricezioni": (["targets", "receptions", "receiving_yards", "receiving_tds", "receiving_yards_after_catch",
                   "receiving_first_downs", "receiving_epa"], [], "targets|receptions"),
    "difesa": (["def_tackles_solo", "def_tackle_assists", "def_tackles_for_loss", "def_sacks", "def_qb_hits",
                "def_interceptions", "def_pass_defended", "def_fumbles_forced", "def_tds"], [], "*"),
    "calci": (["fg_made", "fg_att", "fg_long", "pat_made", "pat_att"], ["fg_long"], "fg_att|pat_att"),
    "punt": (["pt_att", "pt_yards", "pt_net_yards", "pt_inside_20", "pt_touchback", "pt_long"], ["pt_long"], "pt_att"),
    "ritorni": (["punt_returns", "punt_return_yards", "kickoff_returns", "kickoff_return_yards", "special_teams_tds"],
                [], "punt_returns|kickoff_returns"),
}
# College (tabellini ESPN): categoria → (basi, massimi, [(tabella ESPN, etichetta, base)])
COLLEGE = {
    "passaggi": (["cmp", "att", "yds", "td", "int"], [],
                 [("passing", "C/ATT", "cmp/att"), ("passing", "YDS", "yds"), ("passing", "TD", "td"),
                  ("passing", "INT", "int")]),
    "corse": (["car", "yds", "td", "lungo"], ["lungo"],
              [("rushing", "CAR", "car"), ("rushing", "YDS", "yds"), ("rushing", "TD", "td"),
               ("rushing", "LONG", "lungo")]),
    "ricezioni": (["rec", "yds", "td", "lungo"], ["lungo"],
                  [("receiving", "REC", "rec"), ("receiving", "YDS", "yds"), ("receiving", "TD", "td"),
                   ("receiving", "LONG", "lungo")]),
    "difesa": (["tot", "solo", "tfl", "sack", "hur", "int", "intyds", "pd", "td"], [],
               [("defensive", "TOT", "tot"), ("defensive", "SOLO", "solo"), ("defensive", "TFL", "tfl"),
                ("defensive", "SACKS", "sack"), ("defensive", "QB HUR", "hur"), ("defensive", "PD", "pd"),
                ("defensive", "TD", "td"), ("interceptions", "INT", "int"), ("interceptions", "YDS", "intyds")]),
    "calci": (["fgm", "fga", "lungo", "xpm", "xpa", "pts"], ["lungo"],
              [("kicking", "FG", "fgm/fga"), ("kicking", "LONG", "lungo"), ("kicking", "XP", "xpm/xpa"),
               ("kicking", "PTS", "pts")]),
    "punt": (["n", "yds", "in20", "tb", "lungo"], ["lungo"],
             [("punting", "NO", "n"), ("punting", "YDS", "yds"), ("punting", "IN 20", "in20"),
              ("punting", "TB", "tb"), ("punting", "LONG", "lungo")]),
    "ritorni": (["pr", "pry", "kr", "kry", "td"], [],
                [("puntreturns", "NO", "pr"), ("puntreturns", "YDS", "pry"), ("puntreturns", "TD", "td"),
                 ("kickreturns", "NO", "kr"), ("kickreturns", "YDS", "kry"), ("kickreturns", "TD", "td")]),
}


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _corto(v: float):
    return int(v) if float(v).is_integer() else round(v, 2)


def _scrivi(lega: str, stagione: int, categoria: str, basi: list, massimi: list, giocatori: dict, righe: list) -> int:
    USCITA.mkdir(parents=True, exist_ok=True)
    righe.sort(key=lambda r: (r[1], r[0]))
    usati = {r[0] for r in righe}
    # squadre come numeri (indice in «squadre»): i nomi ripetuti a ogni riga pesavano più dei valori
    squadre = sorted({r[2] for r in righe} | {r[3] for r in righe})
    pos = {n: i for i, n in enumerate(squadre)}
    righe = [[r[0], r[1], pos[r[2]], pos[r[3]]] + r[4:] for r in righe]
    dati = {"lega": lega, "stagione": stagione, "categoria": categoria, "basi": basi, "max": massimi,
            "squadre": squadre, "giocatori": {k: v for k, v in giocatori.items() if k in usati}, "righe": righe}
    p = USCITA / f"{lega}_{stagione}_{categoria}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(dati, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)
    return p.stat().st_size


def nfl(stagione: int, testo: str | None = None) -> list[int] | None:
    if testo is None:
        import nfl_indici
        testo = nfl_indici.scarica(nfl_indici.GIOCATORI_URL.format(s=stagione), f"giocatori {stagione}")
    if not testo:
        print(f"NFL {stagione}: statistiche nflverse non scaricate, restano i file di prima.")
        return None
    righe_csv = [r for r in csv.DictReader(io.StringIO(testo)) if r.get("season_type") == "REG"]
    giocatori, settimane = {}, set()
    pesi = []
    for cat, (basi, massimi, cond) in NFL.items():
        righe = []
        for r in righe_csv:
            v = [_num(r.get(c)) for c in basi]
            tieni = any(x for x in v) if cond == "*" else any(_num(r.get(c)) > 0 for c in cond.split("|"))
            if not tieni:
                continue
            pid = r["player_id"]
            giocatori[pid] = [r.get("player_display_name") or r.get("player_name") or "", r.get("position") or ""]
            w = int(r["week"])
            settimane.add(w)
            righe.append([pid, w, r.get("team") or "", r.get("opponent_team") or ""] + [_corto(x) for x in v])
        pesi.append(_scrivi("nfl", stagione, cat, basi, massimi, giocatori, righe))
    print(f"NFL {stagione}: {len(giocatori)} giocatori, week {min(settimane, default=0)}-{max(settimane, default=0)}, "
          f"{sum(pesi) // 1024} KB in {len(pesi)} file.")
    return sorted(settimane)


def college(stagione: int) -> list[int] | None:
    from fetch_college import carica_tabellini
    tab = carica_tabellini(stagione)
    if not tab:
        print(f"College {stagione}: tabellini non trovati, restano i file di prima.")
        return None
    giocatori, settimane, pesi = {}, set(), []
    for cat, (basi, massimi, mappa) in COLLEGE.items():
        per_riga = {}
        for v in tab.values():
            if v.get("tipo") != "regular":
                continue
            try:
                w = int(v.get("settimana"))
            except (TypeError, ValueError):
                continue
            et = v.get("etichette") or {}
            squadre = list((v.get("squadre") or {}).keys())
            for sq, cats in (v.get("squadre") or {}).items():
                avv = next((x for x in squadre if x != sq), "")
                for tabella, etichetta, base in mappa:
                    lab = et.get(tabella) or []
                    if etichetta not in lab:
                        continue
                    i = lab.index(etichetta)
                    for r in cats.get(tabella) or []:
                        if len(r) <= 2 + i:
                            continue
                        chiave = (str(r[0]), w, sq)
                        riga = per_riga.setdefault(chiave, [str(r[0]), w, sq, avv] + [0] * len(basi))
                        giocatori[str(r[0])] = [r[1], ""]
                        grezzo = str(r[2 + i])
                        parti = base.split("/")
                        valori = grezzo.split("/") if len(parti) == 2 else [grezzo]
                        for b, x in zip(parti, valori):
                            j = basi.index(b)
                            n = _num(x)
                            riga[4 + j] = max(riga[4 + j], n) if b in massimi else riga[4 + j] + n
                        settimane.add(w)
        righe = [r[:4] + [_corto(x) for x in r[4:]] for r in per_riga.values() if any(r[4:])]
        pesi.append(_scrivi("college", stagione, cat, basi, massimi, giocatori, righe))
    print(f"College {stagione}: {len(giocatori)} giocatori, week {min(settimane, default=0)}-{max(settimane, default=0)}, "
          f"{sum(pesi) // 1024} KB in {len(pesi)} file.")
    return sorted(settimane)


def aggiorna_indice(lega: str, stagione: int, settimane: list[int]) -> None:
    """Un indice per campionato (indice_<lega>.json): i workflow NFL e College non si pestano i piedi."""
    p = USCITA / f"indice_{lega}.json"
    try:
        voce = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        voce = {"stagioni": [], "settimane": {}}
    voce["settimane"][str(stagione)] = settimane
    voce["stagioni"] = sorted({int(s) for s in voce["settimane"]}, reverse=True)
    voce["categorie"] = list((NFL if lega == "nfl" else COLLEGE).keys())
    voce["aggiornato"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    p.write_text(json.dumps(voce, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("nfl", "college"):
        print("Uso: python scripts/statistiche.py nfl|college [stagione|da-a]")
        return 2
    lega = argv[0]
    adesso = datetime.now(timezone.utc)
    corrente = adesso.year if adesso.month >= 3 else adesso.year - 1
    if len(argv) > 1 and "-" in argv[1]:
        a, b = map(int, argv[1].split("-"))
        stagioni = range(a, b + 1)
    else:
        stagioni = [int(argv[1])] if len(argv) > 1 else [corrente]
    errori = 0
    for s in stagioni:
        try:
            settimane = nfl(s) if lega == "nfl" else college(s)
        except Exception as e:                       # noqa: BLE001 - una stagione non ferma le altre
            print(f"{lega} {s}: statistiche non preparate ({type(e).__name__}: {e}); restano i file di prima.")
            settimane = None
        if settimane:
            aggiorna_indice(lega, s, settimane)
        else:
            errori += 1
    return 1 if errori == len(list(stagioni)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
