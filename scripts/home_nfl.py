"""
Home NFL: i blocchi calcolati che la pagina principale non può fare da sola. Scrive docs/home_nfl.json.

  · corsa: probabilità di andare ai playoff di ogni squadra (scripts/nfl_playoff.corsa, 4.000 simulazioni del resto
    della stagione regolare con le linee del mercato) e le partite rimaste che pesano di più sui playoff
    («decisive»: quanto cambia la probabilità delle due squadre tra vittoria e sconfitta);
  · ranking PureStats: margine atteso contro una squadra media, metà dai risultati (margini corretti per la forza
    degli avversari) e metà dall'EPA per azione corretto per gli avversari (indici di nfl_indici, se il giro li ha
    calcolati); movimento rispetto alla fine della settimana prima;
  · il meglio della week: giocata (probabilità di vittoria aggiunta, dalla Giornata), giocatore (punti fantasy
    standard nflverse), squadra (EPA della Giornata). Si mostra l'ultima week completa; finché non c'è, quella in corso;
  · accadde oggi: per oggi e i 3 giorni dopo, la partita più importante giocata in quella data dal 1999.
Nessun segnale di valore: niente linee contro quote, niente Charlie. Fonti nflverse (CC-BY 4.0), gratis.
Ogni blocco che fallisce resta com'era nel file precedente. Solo libreria standard.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nfl_playoff                                                       # noqa: E402
from nfl_indici import PARTITE_URL, SQUADRE_URL, GIOCATORI_URL, scarica, _ora_italiana   # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
USCITA = RADICE / "docs" / "home_nfl.json"
PUBBLICO = RADICE / "docs" / "data_nfl.json"
PRIVATO = RADICE / "data" / "privato_nfl.json"
N_DECISIVE = 8
GIORNI_ACCADDE = 4
PESO_TURNO = {"SB": 400, "CON": 300, "DIV": 200, "WC": 150}
NOME_TURNO = {"SB": "Super Bowl", "CON": "finale di conference", "DIV": "turno di division", "WC": "wild card"}
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def leggi(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------------------------------------- corsa ai playoff
def corsa(partite: str, squadre: str, stagione_righe: list[dict]) -> dict:
    c = nfl_playoff.corsa(partite, squadre)
    if not c:
        return {}
    bilancio = defaultdict(lambda: [0, 0, 0])
    for r in stagione_righe:
        if r["game_type"] != "REG" or num(r["result"]) is None:
            continue
        m = num(r["result"])
        casa, osp = r["home_team"], r["away_team"]
        i = 0 if m > 0 else 1 if m < 0 else 2
        bilancio[casa][i] += 1
        bilancio[osp][{0: 1, 1: 0, 2: 2}[i]] += 1
    lista = [{"squadra": s, "conference": c["conference"][s], "division": c["division"][s], "p": p,
              "bilancio": "-".join(str(x) for x in bilancio[s][:2]) + (f"-{bilancio[s][2]}" if bilancio[s][2] else "")}
             for s, p in c["squadre"].items()]
    lista.sort(key=lambda x: (-x["p"], x["squadra"]))
    decisive = []
    for g in c["partite"]:
        lati = {}
        peso = 0.0
        for lato in ("casa", "ospite"):
            esito = g["esito" + lato.capitalize()]
            v, p = esito["seVince"], esito["sePerde"]
            if v is None or p is None:
                continue
            peso += v - p
            lati["esito" + lato.capitalize()] = {"seVince": v, "sePerde": p, "ora": c["squadre"][g[lato]]}
        if len(lati) < 2:
            continue
        decisive.append({"settimana": g["settimana"], "casa": g["casa"], "ospite": g["ospite"],
                         **_ora_italiana(g["data"], g["ora"]), "pCasa": g["pCasa"], "peso": round(peso, 4), **lati})
    decisive.sort(key=lambda x: -x["peso"])
    return {"stagione": c["stagione"], "settimana": c["settimana"], "simulazioni": c["simulazioni"],
            "squadre": lista, "decisive": decisive[:N_DECISIVE]}


# ---------------------------------------------------------------------------------------------- ranking
def ranking(stagione_righe: list[dict], indici: dict | None, vecchio: dict) -> dict:
    giocate = [{"casa": r["home_team"], "ospite": r["away_team"], "linea": num(r["result"]),
                "neutro": r.get("location") == "Neutral"}
               for r in stagione_righe if r["game_type"] == "REG" and num(r["result"]) is not None]
    if len(giocate) < 32:
        return {}
    forza, _campo = nfl_playoff._forze(giocate)       # margini al posto delle linee: risultati corretti per avversari
    epa = {}
    if indici and indici.get("squadre"):
        epa = {s["squadra"]: s.get("puntiPartita") for s in indici["squadre"] if s.get("puntiPartita") is not None}
    righe = []
    for s, f in forza.items():
        punti = (f + epa[s]) / 2 if s in epa else f
        righe.append((s, round(punti, 1), round(f, 1), epa.get(s)))
    righe.sort(key=lambda x: -x[1])
    ultima = max(int(r["week"]) for r in stagione_righe if r["game_type"] == "REG" and num(r["result"]) is not None)
    storico = dict(vecchio.get("storico", {}))
    prima = storico.get(str(ultima - 1))
    lista = []
    for i, (s, punti, ris, e) in enumerate(righe, 1):
        mov = None
        if prima and s in prima:
            mov = prima.index(s) + 1 - i
        lista.append({"pos": i, "squadra": s, "punti": punti, "risultati": ris, "epa": e, "mov": mov})
    storico[str(ultima)] = [s for s, *_ in righe]
    for k in sorted(storico, key=int)[:-4]:
        storico.pop(k)
    return {"settimana": ultima, "conEpa": bool(epa), "squadre": lista, "storico": storico,
            "nota": "Margine atteso in punti contro una squadra media: metà dai risultati, metà dall'EPA per azione, "
                    "entrambi corretti per la forza degli avversari." if epa else
                    "Margine atteso in punti contro una squadra media, dai risultati corretti per la forza degli "
                    "avversari."}


# ---------------------------------------------------------------------------------------------- il meglio della week
def _riga_giocatore(r: dict) -> str:
    pezzi = []
    py, ptd, pint = num(r.get("passing_yards")) or 0, num(r.get("passing_tds")) or 0, num(r.get("passing_interceptions")) or 0
    ry, rtd = num(r.get("rushing_yards")) or 0, num(r.get("rushing_tds")) or 0
    rec, ricy, ricd = num(r.get("receptions")) or 0, num(r.get("receiving_yards")) or 0, num(r.get("receiving_tds")) or 0
    if py:
        pezzi.append(f"{py:.0f} yard lanciate" + (f", {ptd:.0f} TD" if ptd else "") + (f", {pint:.0f} INT" if pint else ""))
    if ry >= 20 or rtd:
        pezzi.append(f"{ry:.0f} yard di corsa" + (f", {rtd:.0f} TD" if rtd else ""))
    if rec:
        pezzi.append(f"{rec:.0f} ricezioni per {ricy:.0f} yard" + (f", {ricd:.0f} TD" if ricd else ""))
    return " · ".join(pezzi)


def giocatore_settimana(testo: str | None, settimana: int) -> dict | None:
    if not testo:
        return None
    migliore = None
    for r in csv.DictReader(io.StringIO(testo)):
        if r.get("week") != str(settimana) or r.get("season_type", "REG") not in ("REG", "POST"):
            continue
        fp = num(r.get("fantasy_points"))
        if fp is not None and (migliore is None or fp > migliore[0]):
            migliore = (fp, r)
    if not migliore:
        return None
    fp, r = migliore
    return {"nome": r.get("player_display_name") or r.get("player_name"), "ruolo": r.get("position"),
            "squadra": r.get("team"), "avversario": r.get("opponent_team"), "punti": round(fp, 1),
            "riga": _riga_giocatore(r)}


def meglio(G: dict, giocatori: str | None, vecchio: dict) -> dict:
    if not G or not G.get("settimana"):
        return vecchio.get("meglio") or {}
    w = int(G["settimana"])
    prec = vecchio.get("meglio") or {}
    if not G.get("completa") and prec.get("completa") and int(prec.get("settimana", 0)) == w - 1:
        return prec                                   # la week in corso è appena iniziata: resta la precedente
    giocate = (G.get("giocate") or {}).get("attacco", []) + (G.get("giocate") or {}).get("difesa", [])
    giocata = max(giocate, key=lambda x: x.get("valore") or 0) if giocate else None
    if giocata:
        p = next((x for x in G.get("partite", []) if giocata.get("partita", "").endswith(f"_{x['ospite']}_{x['casa']}")), None)
        giocata = {**giocata, "video": (p or {}).get("video"), "highlights": (p or {}).get("highlights"),
                   "casa": (p or {}).get("casa"), "ospite": (p or {}).get("ospite"), "stadio": (p or {}).get("stadio")}
    att = ((G.get("squadreSettimana") or {}).get("attacchi") or [])
    squadra = max(att, key=lambda x: x.get("netto") or -9) if att else None
    return {"settimana": w, "stagione": G.get("stagione"), "completa": bool(G.get("completa")),
            "partite": sum(1 for x in G.get("partite", []) if x.get("pc") is not None), "giocata": giocata,
            "giocatore": giocatore_settimana(giocatori, w), "squadra": squadra}


# ---------------------------------------------------------------------------------------------- accadde oggi
def accadde(righe: list[dict], oggi: dt.date, nomi: dict) -> dict:
    per_giorno = defaultdict(list)
    for r in righe:
        if num(r.get("result")) is None or not r.get("gameday"):
            continue
        per_giorno[r["gameday"][5:]].append(r)
    out = {}
    for d in range(GIORNI_ACCADDE):
        g = oggi + dt.timedelta(days=d)
        chiave = g.strftime("%m-%d")
        cand = [r for r in per_giorno.get(chiave, []) if int(r["gameday"][:4]) < g.year]
        if not cand:
            continue
        def punteggio(r):
            tot = (num(r["home_score"]) or 0) + (num(r["away_score"]) or 0)
            return (PESO_TURNO.get(r["game_type"], 0) + tot + 10 * (r.get("overtime") == "1")
                    + 5 * (abs(num(r["result"]) or 0) <= 3))
        r = max(cand, key=punteggio)
        tot = (num(r["home_score"]) or 0) + (num(r["away_score"]) or 0)
        anno = int(r["gameday"][:4])
        record = max(cand, key=lambda x: (num(x["home_score"]) or 0) + (num(x["away_score"]) or 0)) is r
        note = []
        if r["game_type"] in NOME_TURNO:
            note.append(NOME_TURNO[r["game_type"]])
        if r.get("overtime") == "1":
            note.append("ai supplementari")
        if record and len(cand) > 1 and r["game_type"] == "REG":
            note.append(f"la partita con più punti giocata il {g.day} {MESI[g.month - 1]} dal 1999 ({tot:.0f})")
        out[chiave] = {"data": r["gameday"], "anni": g.year - anno, "stagione": int(r["season"]),
                       "settimana": int(r["week"]), "tipo": r["game_type"], "casa": r["home_team"],
                       "ospite": r["away_team"], "nomeCasa": nomi.get(r["home_team"]), "nomeOspite": nomi.get(r["away_team"]), "pc": int(num(r["home_score"])), "po": int(num(r["away_score"])),
                       "qbCasa": r.get("home_qb_name") or None, "qbOspite": r.get("away_qb_name") or None,
                       "allenatoreCasa": r.get("home_coach") or None, "allenatoreOspite": r.get("away_coach") or None,
                       "stadio": r.get("stadium") or None, "note": note}
    return out


# ---------------------------------------------------------------------------------------------- main
def main() -> int:
    vecchio = leggi(USCITA)
    out = dict(vecchio)
    out.pop("errori", None)
    partite = scarica(PARTITE_URL, "calendario nflverse")
    squadre = scarica(SQUADRE_URL, "anagrafica squadre")
    righe = list(csv.DictReader(io.StringIO(partite))) if partite else []
    if not righe:
        print("Home NFL: calendario nflverse non scaricato, il file resta com'era.")
        return 0
    stagione = max(int(r["season"]) for r in righe)
    st = [r for r in righe if int(r["season"]) == stagione]
    errori = []

    try:
        c = corsa(partite, squadre or "", st) if squadre else {}
        if c:
            out["corsa"] = c
            print(f"Home NFL: corsa ai playoff, {len(c['squadre'])} squadre, {len(c['decisive'])} partite decisive "
                  f"(settimana {c['settimana']}).")
        else:
            print("Home NFL: corsa ai playoff non calcolata (stagione regolare finita o anagrafica mancante).")
    except Exception as e:                                                   # noqa: BLE001
        errori.append(f"corsa: {e}")

    try:
        indici = leggi(PRIVATO).get("indici")
        r = ranking(st, indici, vecchio.get("ranking") or {})
        if r:
            out["ranking"] = r
            print(f"Home NFL: ranking dopo la week {r['settimana']} ({'risultati + EPA' if r['conEpa'] else 'solo risultati'}).")
    except Exception as e:                                                   # noqa: BLE001
        errori.append(f"ranking: {e}")

    try:
        G = leggi(PUBBLICO).get("giornata") or {}
        giocatori = scarica(GIOCATORI_URL.format(s=G.get("stagione") or stagione), "giocatori della settimana") if G else None
        m = meglio(G, giocatori, vecchio)
        if m:
            out["meglio"] = m
            print(f"Home NFL: il meglio della week {m.get('settimana')} ({'completa' if m.get('completa') else 'in corso'}).")
    except Exception as e:                                                   # noqa: BLE001
        errori.append(f"meglio: {e}")

    try:
        oggi = dt.datetime.now(dt.timezone.utc).date()
        nomi = {r["team_abbr"]: r["team_name"] for r in csv.DictReader(io.StringIO(squadre or ""))}
        out["accadde"] = accadde(righe, oggi - dt.timedelta(days=1), nomi)
        print(f"Home NFL: accadde oggi per {len(out['accadde'])} giorni.")
    except Exception as e:                                                   # noqa: BLE001
        errori.append(f"accadde: {e}")

    for e in errori:
        print(f"Home NFL: blocco non aggiornato, resta il precedente — {e}")
    out["aggiornato"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    out["fonte"] = "nflverse (CC-BY 4.0): calendario, risultati, linee, statistiche dei giocatori"
    tmp = USCITA.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(USCITA)
    return 0


if __name__ == "__main__":
    sys.exit(main())
