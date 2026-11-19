"""Articoli di PureStats (anteprime e cronache), scritti da Claude a partire da fatti verificati.

Comandi:
  python scripts/articoli.py fatti <game_id>                 prepara data/articoli/fatti_<game_id>.json
  python scripts/articoli.py pubblica <game_id> <tipo> <testo.json>
                                                             controlla il testo e lo pubblica in docs/articoli/
  python scripts/articoli.py meteo                           aggiorna la scheda meteo delle anteprime in arrivo

Regola: ogni numero e ogni nome dell'articolo deve comparire nei fatti (controllo meccanico in «pubblica»).
Fonti: nflverse (calendari, statistiche, giocatori, rapporto infortuni; CC-BY 4.0), meteo NWS e Open-Meteo.
Solo libreria standard. Se una fonte non risponde, il campo resta vuoto e lo script lo dice.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import gzip
import io
import json
import re
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

RADICE = Path(__file__).resolve().parent.parent
FATTI = RADICE / "data" / "articoli"
USCITA = RADICE / "docs" / "articoli"
CACHE = Path("/tmp/purestats_articoli")
UA = {"User-Agent": "PureStats/1.0 (github.com/doubleuptip/purestats)"}
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"
ROMA, NY = ZoneInfo("Europe/Rome"), ZoneInfo("America/New_York")
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]
RINOMINATI = {"Reliant Stadium": "NRG Stadium"}   # nomi vecchi nel calendario nflverse
POST = {"WC": "turno di wild card", "DIV": "turno di division", "CON": "finale di conference", "SB": "Super Bowl"}


# ------------------------------------------------------------------ dati

def scarica(nome: str, url: str) -> Path:
    """Scarica una volta per giro (cache in /tmp): i file nflverse cambiano al massimo una volta al giorno."""
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / nome
    if not p.exists() or (dt.datetime.now().timestamp() - p.stat().st_mtime) > 3 * 3600:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r:
            p.write_bytes(r.read())
    return p


def leggi_csv(p: Path) -> list[dict]:
    apri = gzip.open if p.suffix == ".gz" else open
    with apri(p, "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def n_it(x) -> str:
    if isinstance(x, float) and not x.is_integer():
        return f"{x:.1f}".replace(".", ",")
    n = int(x)
    return f"{n:,}".replace(",", ".") if abs(n) >= 1000 else str(n)


class Dati:
    def __init__(self, stagione: int):
        self.stagione = stagione
        self.cal = leggi_csv(scarica("games.csv", f"{NFLVERSE}/schedules/games.csv"))
        self.stats = leggi_csv(scarica(f"stats_{stagione}.csv.gz", f"{NFLVERSE}/stats_player/stats_player_week_{stagione}.csv.gz"))
        self.stats_prima = leggi_csv(scarica(f"stats_{stagione - 1}.csv.gz",
                                             f"{NFLVERSE}/stats_player/stats_player_week_{stagione - 1}.csv.gz"))
        self.giocatori = {r["gsis_id"]: r for r in leggi_csv(scarica("players.csv", f"{NFLVERSE}/players/players.csv"))}
        try:
            self.infortuni = leggi_csv(scarica(f"inj_{stagione}.csv", f"{NFLVERSE}/injuries/injuries_{stagione}.csv"))
        except Exception as e:                       # noqa: BLE001
            print(f"Rapporto infortuni non scaricato ({e}): l'anteprima uscirà senza assenze ufficiali")
            self.infortuni = []
        squadre = json.loads((RADICE / "docs" / "data_nfl.json").read_text())
        self.nomi = {s["nome"]: s["nomeCompleto"] for s in squadre["squadre"]}
        self.division = {s["nome"]: s["division"] for s in squadre["squadre"]}
        self.colori = {k: v.get("colore") for k, v in squadre.get("loghi", {}).items()}


def soprannome(nome_completo: str) -> str:
    return nome_completo.split()[-1]


# ------------------------------------------------------------------ fatti di squadra

def partite_giocate(D: Dati, sq: str, stagione: int, prima_di: tuple | None = None, tipi=("REG",)) -> list[dict]:
    out = []
    for r in D.cal:
        if int(r["season"]) != stagione or r["game_type"] not in tipi or not r["home_score"]:
            continue
        if prima_di and (int(r["season"]), int(r["week"])) >= prima_di:
            continue
        if sq in (r["home_team"], r["away_team"]):
            casa = r["home_team"] == sq
            mie, loro = (int(r["home_score"]), int(r["away_score"])) if casa else (int(r["away_score"]), int(r["home_score"]))
            out.append({"gid": r["game_id"], "settimana": int(r["week"]), "tipo": r["game_type"], "casa": casa,
                        "avversario": r["away_team"] if casa else r["home_team"], "fatti": mie, "subiti": loro,
                        "esito": "V" if mie > loro else "S" if mie < loro else "P"})
    return sorted(out, key=lambda g: g["settimana"])


def bilancio(gare) -> str:
    v = sum(g["esito"] == "V" for g in gare); s = sum(g["esito"] == "S" for g in gare); p = sum(g["esito"] == "P" for g in gare)
    return f"{v}-{s}" + (f"-{p}" if p else "")


def serie(gare) -> str:
    if not gare:
        return ""
    ult = gare[-1]["esito"]
    n = 0
    for g in reversed(gare):
        if g["esito"] != ult:
            break
        n += 1
    if n < 2 or ult == "P":
        return ""
    return f"{n} {'vittorie' if ult == 'V' else 'sconfitte'} di fila"


def classifiche(D: Dati, stagione: int, prima_di: tuple) -> dict:
    tutte = {}
    for sq in D.nomi:
        g = partite_giocate(D, sq, stagione, prima_di)
        if g:
            tutte[sq] = (sum(x["fatti"] for x in g) / len(g), sum(x["subiti"] for x in g) / len(g),
                         (sum(x["esito"] == "V" for x in g) + sum(x["esito"] == "P" for x in g) / 2) / len(g))
    att = {sq: i + 1 for i, sq in enumerate(sorted(tutte, key=lambda s: -tutte[s][0]))}
    dif = {sq: i + 1 for i, sq in enumerate(sorted(tutte, key=lambda s: tutte[s][1]))}
    return {"medie": tutte, "attacco": att, "difesa": dif}


def giudizio_reparto(pos: int, attacco: bool, totale: int = 32) -> str:
    if attacco:
        return ("il miglior attacco della lega" if pos == 1 else "uno degli attacchi più prolifici della lega" if pos <= 5
                else "un attacco di buon livello" if pos <= 10 else "l'attacco meno produttivo della lega" if pos == totale
                else "uno degli attacchi meno produttivi" if pos >= 27 else "un attacco nella media")
    return ("la miglior difesa della lega" if pos == 1 else "una delle difese più solide" if pos <= 5
            else "una difesa affidabile" if pos <= 10 else "la difesa più battuta della lega" if pos == totale
            else "una delle difese più battute" if pos >= 27 else "una difesa che concede molto" if pos >= 22
            else "una difesa nella media")


def stagione_scorsa(D: Dati, sq: str) -> dict:
    s = D.stagione - 1
    reg = partite_giocate(D, sq, s)
    post = partite_giocate(D, sq, s, tipi=tuple(POST))
    if not post:
        esito = "fuori dai playoff"
    elif post[-1]["esito"] == "V" and post[-1]["tipo"] == "SB":
        esito = "campioni NFL (Super Bowl vinto)"
    else:
        esito = f"eliminati nel {POST[post[-1]['tipo']]}" if post[-1]["tipo"] != "SB" else "sconfitti al Super Bowl"
    return {"bilancio": bilancio(reg), "playoff": esito}


def allenatore(D: Dati, sq: str, nome: str) -> dict:
    stagioni_qui = {r["season"] for r in D.cal if r["game_type"] == "REG" and int(r["season"]) < D.stagione
                    and ((r["home_team"] == sq and r["home_coach"] == nome) or (r["away_team"] == sq and r["away_coach"] == nome))}
    prec = ""
    for r in D.cal:
        if int(r["season"]) == D.stagione - 1 and r["game_type"] == "REG" and sq in (r["home_team"], r["away_team"]):
            prec = r["home_coach"] if r["home_team"] == sq else r["away_coach"]
            break
    return {"nome": nome, "stagione": len(stagioni_qui) + 1, "predecessore": prec if prec and prec != nome else ""}


def eta(D: Dati, pid: str, giorno: dt.date) -> int | None:
    n = (D.giocatori.get(pid) or {}).get("birth_date")
    if not n:
        return None
    b = dt.date.fromisoformat(n[:10])
    return giorno.year - b.year - ((giorno.month, giorno.day) < (b.month, b.day))


def totali(righe, chiavi) -> dict:
    tot = collections.defaultdict(collections.Counter)
    info = {}
    for r in righe:
        c = tot[r["player_id"]]
        c["partite"] += 1
        for k in chiavi:
            c[k] += num(r.get(k))
        info[r["player_id"]] = (r["player_display_name"], r["position"], r["team"])
    return tot, info


CHIAVI = ("passing_yards", "passing_tds", "passing_interceptions", "attempts", "completions", "rushing_yards", "rushing_tds",
          "carries", "receptions", "receiving_yards", "receiving_tds", "targets", "def_sacks", "def_interceptions",
          "def_tackles_solo", "def_tackle_assists")


def squadra_attuale(righe) -> dict:
    """{giocatore: squadra della sua partita più recente}: chi è stato ceduto non conta più per la vecchia squadra."""
    ult = {}
    for r in righe:
        w = int(r["week"])
        if r["player_id"] not in ult or w >= ult[r["player_id"]][0]:
            ult[r["player_id"]] = (w, r["team"])
    return {p: t for p, (w, t) in ult.items()}


def quarterback_per_partita(D: Dati, sq: str, settimana: int) -> dict:
    """Chi ha lanciato di più in ogni partita (il titolare, salvo cambi a partita in corso)."""
    per_gara = collections.defaultdict(list)
    for r in D.stats:
        if r["team"] == sq and r["season_type"] == "REG" and int(r["week"]) < settimana and num(r["attempts"]) > 0:
            per_gara[int(r["week"])].append(r)
    return {w: max(v, key=lambda r: num(r["attempts"])) for w, v in per_gara.items()}


def fatti_squadra(D: Dati, sq: str, avv: str, settimana: int, giorno: dt.date, coach: str, cl: dict) -> dict:
    prima = (D.stagione, settimana)
    gare = partite_giocate(D, sq, D.stagione, prima)
    stagione_reg = [r for r in D.stats if r["season_type"] == "REG" and int(r["week"]) < settimana]
    attuale = squadra_attuale(stagione_reg)
    righe = [r for r in stagione_reg if r["team"] == sq]
    tot, info = totali(righe, CHIAVI)
    # chi ha giocato qui ma ora è altrove (ceduto) e chi è arrivato da un'altra squadra
    passati = collections.defaultdict(set)
    for r in stagione_reg:
        passati[r["player_id"]].add(r["team"])
    ceduti = sorted({(info[p][0], info[p][1], attuale[p]) for p in tot if attuale.get(p) != sq})
    arrivati = sorted({(r["player_display_name"], r["position"], t) for r in righe for t in passati[r["player_id"]]
                       if t != sq and attuale.get(r["player_id"]) == sq})
    tot = {p: c for p, c in tot.items() if attuale.get(p) == sq}
    tutti, info_l = totali([r for r in D.stats if r["season_type"] == "REG" and int(r["week"]) < settimana], CHIAVI)
    pos_lega = {k: {p: i + 1 for i, p in enumerate(sorted(tutti, key=lambda p: -tutti[p][k]))}
                for k in ("passing_yards", "passing_tds", "rushing_yards", "receiving_yards", "def_sacks")}
    prima_tot, _ = totali([r for r in D.stats_prima if r["season_type"] == "REG"], CHIAVI)

    # quarterback: bilancio con ogni titolare
    qbs = quarterback_per_partita(D, sq, settimana)
    con_qb = collections.defaultdict(list)
    esiti = {g["settimana"]: g for g in gare}
    for w, r in qbs.items():
        if w in esiti:
            con_qb[(r["player_id"], r["player_display_name"])].append(esiti[w])
    titolari = [{"nome": n, "partiteDaTitolare": len(g), "bilancio": bilancio(g)} for (p, n), g in
                sorted(con_qb.items(), key=lambda x: -len(x[1]))]

    infortuni = {r["full_name"]: r for r in D.infortuni if r["team"] == sq and r["week"] == str(settimana)}

    def scheda_giocatore(pid, ruolo, chiave, testo_stagione):
        nome, pos, _ = info[pid]
        c, p = tot[pid], prima_tot.get(pid)
        d = {"nome": nome, "ruolo": ruolo, "posizione": pos, "stagione": testo_stagione,
             "posizioneNellaLega": pos_lega.get(chiave, {}).get(pid), "eta": eta(D, pid, giorno)}
        if p and p["partite"] >= 6 and c["partite"]:
            ora, prima_ = c[chiave] / c["partite"], p[chiave] / p["partite"]
            if prima_ > 0:
                d["rispettoAllAnnoScorso"] = ("in netto calo" if ora < prima_ * 0.8 else "in netta crescita" if ora > prima_ * 1.2
                                              else "sugli stessi livelli")
        inf = infortuni.get(nome)
        if inf:
            d["rapportoInfortuni"] = {"stato": inf["report_status"] or "", "allenamento": inf["practice_status"] or "",
                                      "infortunio": inf["report_primary_injury"] or inf["practice_primary_injury"] or ""}
        return d

    chiave_ord = lambda k, filtro=lambda p: True: sorted([p for p in tot if filtro(p) and tot[p][k] > 0], key=lambda p: -tot[p][k])
    giocatori = []
    ult = qbs.get(max(qbs)) if qbs else None
    if ult:
        p = ult["player_id"]
        c = tot[p]
        giocatori.append(scheda_giocatore(p, "quarterback (titolare nell'ultima partita)", "passing_yards",
                                          f"{n_it(c['passing_yards'])} yard su lancio, {int(c['passing_tds'])} TD, "
                                          f"{int(c['passing_interceptions'])} intercetti in {c['partite']} partite"))
    for k, ruolo, filtro, testo in (
            ("rushing_yards", "miglior corridore", lambda p: info[p][1] != "QB",
             lambda c: f"{n_it(c['rushing_yards'])} yard di corsa, {int(c['rushing_tds'])} TD"),
            ("receiving_yards", "ricevitore più produttivo", lambda p: True,
             lambda c: f"{n_it(c['receiving_yards'])} yard ricevute, {int(c['receptions'])} ricezioni, {int(c['receiving_tds'])} TD"),
            ("def_sacks", "miglior pass rusher", lambda p: True, lambda c: f"{n_it(c['def_sacks'])} sack")):
        lista = chiave_ord(k, filtro)
        for i, p in enumerate(lista[:2 if k == "receiving_yards" else 1]):
            giocatori.append(scheda_giocatore(p, ruolo if i == 0 else "secondo ricevitore più produttivo", k, testo(tot[p])))

    # assenze e dubbi ufficiali tra i giocatori che contano (i primi per uso nella squadra)
    peso = {p: tot[p]["attempts"] / 4 + tot[p]["carries"] + tot[p]["targets"] * 1.5 + tot[p]["def_sacks"] * 8
            + (tot[p]["def_tackles_solo"] + tot[p]["def_tackle_assists"]) * 0.6 for p in tot}
    importanti = {info[p][0] for p in sorted(peso, key=lambda p: -peso[p])[:22]}
    nomi_arrivati = {n for n, _, _ in arrivati}   # chi è arrivato in stagione: il suo stato è sempre una notizia
    rapporto = []
    for nome, r in infortuni.items():
        if nome in importanti or nome in nomi_arrivati or r["report_status"] in ("Out", "Doubtful"):
            rapporto.append({"nome": nome, "ruolo": r["position"], "stato": r["report_status"] or "(stato non ancora dato)",
                             "allenamento": r["practice_status"], "infortunio": r["report_primary_injury"] or r["practice_primary_injury"],
                             "giocatoreImportante": nome in importanti})

    g = cl["medie"].get(sq)
    div = sorted([s for s in D.nomi if D.division.get(s) == D.division.get(sq)],
                 key=lambda s: -(cl["medie"].get(s, (0, 0, 0))[2]))
    return {
        "squadra": D.nomi[sq], "soprannome": soprannome(D.nomi[sq]),
        "bilancio": bilancio(gare), "serieAperta": serie(gare),
        "ultimePartite": [{"settimana": x["settimana"], "avversario": D.nomi[x["avversario"]], "inCasa": x["casa"],
                           "esito": {"V": "vittoria", "S": "sconfitta", "P": "pareggio"}[x["esito"]],
                           "punteggio": f"{x['fatti']}-{x['subiti']}"} for x in gare[-4:]],
        "andamento": {"prime": bilancio(gare[: len(gare) // 2]), "ultime": bilancio(gare[len(gare) // 2:])},
        "puntiFattiPartita": round(g[0], 1) if g else None, "puntiSubitiPartita": round(g[1], 1) if g else None,
        "attacco": giudizio_reparto(cl["attacco"][sq], True), "difesa": giudizio_reparto(cl["difesa"][sq], False),
        "division": {"nome": D.division.get(sq), "posizione": f"{div.index(sq) + 1}ª su {len(div)}",
                     "capolista": D.nomi[div[0]] if div[0] != sq else ""},
        "stagioneScorsa": stagione_scorsa(D, sq),
        "allenatore": allenatore(D, sq, coach),
        "quarterbackTitolariStagione": titolari,
        "giocatoriChiave": giocatori,
        "cedutiInStagione": [{"nome": n, "ruolo": r, "oraGiocaCon": D.nomi.get(t, t)} for n, r, t in ceduti],
        "arrivatiInStagione": [{"nome": n, "ruolo": r, "daSquadra": D.nomi.get(t, t)} for n, r, t in arrivati],
        "rapportoInfortuni": rapporto,
    }


# ------------------------------------------------------------------ fatti della partita

STADI_COPERTI = None


def fatti(gid: str) -> dict:
    stagione, settimana = int(gid.split("_")[0]), int(gid.split("_")[1])
    D = Dati(stagione)
    r = next(x for x in D.cal if x["game_id"] == gid)
    casa, osp = r["home_team"], r["away_team"]
    inizio_et = dt.datetime.fromisoformat(f"{r['gameday']}T{r['gametime'] or '13:00'}").replace(tzinfo=NY)
    it = inizio_et.astimezone(ROMA)
    notte = it.hour < 7
    if notte:
        ieri = it - dt.timedelta(days=1)
        quando = f"nella notte tra {GIORNI[ieri.weekday()]} e {GIORNI[it.weekday()]} {it.day} {MESI[it.month - 1]}, alle {it.hour}:{it.minute:02d} italiane"
    else:
        quando = f"{GIORNI[it.weekday()]} {it.day} {MESI[it.month - 1]}, alle {it.hour}:{it.minute:02d} italiane"
    cl = classifiche(D, stagione, (stagione, settimana))
    giorno = inizio_et.date()
    sp = num(r["spread_line"], None) if r["spread_line"] else None
    favorita = (D.nomi[casa] if sp > 0 else D.nomi[osp]) if sp else ""
    prec = []
    for x in sorted([x for x in D.cal if {x["home_team"], x["away_team"]} == {casa, osp} and x["home_score"]
                     and (int(x["season"]), int(x["week"])) < (stagione, settimana)], key=lambda x: (int(x["season"]), int(x["week"])))[-3:]:
        hs, as_ = int(x["home_score"]), int(x["away_score"])
        prec.append({"stagione": int(x["season"]), "casa": D.nomi[x["home_team"]], "ospite": D.nomi[x["away_team"]],
                     "risultato": f"{D.nomi[x['home_team']]} {hs} - {D.nomi[x['away_team']]} {as_}"})
    sys.path.insert(0, str(RADICE / "scripts"))
    from contesto import STADI_NFL
    coperto = STADI_NFL.get(casa, (0, 0, False))[2]
    out = {
        "id": gid, "lega": "nfl", "stagione": stagione, "settimana": settimana,
        "partita": f"{D.nomi[osp]} @ {D.nomi[casa]}", "ospite": osp, "casa": casa,
        "quando": quando, "dataIt": it.date().isoformat(), "oraIt": f"{it.hour:02d}:{it.minute:02d}",
        "inizioUtc": inizio_et.astimezone(dt.timezone.utc).isoformat(timespec="minutes"),
        "stadio": RINOMINATI.get(r["stadium"], r["stadium"]), "campoNeutro": r["location"] == "Neutral", "coperto": coperto,
        "sfidaDiDivision": r["div_game"] == "1",
        "mercato": {"favorita": favorita, "vantaggio": abs(sp) if sp else None, "totale": num(r["total_line"], None),
                    "nota": "solo a parole: favoriti di poco (fino a 3), favoriti, nettamente favoriti (da 7,5); molti punti da 49,5, pochi fino a 41"},
        "precedenti": prec,
        "ospiti": fatti_squadra(D, osp, casa, settimana, giorno, r["away_coach"], cl),
        "padroniDiCasa": fatti_squadra(D, casa, osp, settimana, giorno, r["home_coach"], cl),
        "colori": {"ospite": D.colori.get(osp), "casa": D.colori.get(casa)},
    }
    FATTI.mkdir(parents=True, exist_ok=True)
    (FATTI / f"fatti_{gid}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"Fatti pronti: data/articoli/fatti_{gid}.json")
    return out


# ------------------------------------------------------------------ controllo e pubblicazione

PAROLE_OK = {"NFL", "AFC", "NFC", "Super", "Bowl", "PureStats", "Week", "Pro", "East", "West", "North", "South"}


def controlla(testo: dict, f: dict) -> list[str]:
    """Numeri e nomi propri del testo devono comparire nei fatti. Restituisce l'elenco dei problemi."""
    corpo = json.dumps(f, ensure_ascii=False)
    numeri = set(re.findall(r"\d+(?:[.,]\d+)?", corpo))
    numeri |= {x.replace(".", ",") for x in numeri} | {x.split(".")[0] for x in numeri}
    numeri |= {n_it(int(x)) for x in re.findall(r"\b\d{4,}\b", corpo)}
    tutto = testo["titolo"] + "\n" + "\n".join(testo["paragrafi"])
    problemi = []
    for t in re.findall(r"\d+(?:\.\d{3})*(?:,\d+)?", tutto):
        if t not in numeri and t.replace(".", "") not in numeri:
            problemi.append(f"numero non presente nei fatti: {t}")
    for frase in re.split(r"(?<=[.!?:;«»])\s+|\n", tutto):
        parole = re.findall(r"[A-Za-zÀ-ÿ'’.\-]+", frase)
        for i, p in enumerate(parole):
            p = p.strip(".'’-")
            if i == 0 or len(p) < 2 or not p[0].isupper() or p in PAROLE_OK:
                continue
            if p not in corpo:
                problemi.append(f"nome non presente nei fatti: {p}")
    return problemi


STATI = {"Out": "fuori", "Doubtful": "in forte dubbio", "Questionable": "da valutare"}


def _dati(g: dict) -> list[list[str]]:
    """Numeri di un giocatore in caselle [valore, etichetta] (dal testo di stagione)."""
    t = g["stagione"]
    out = []
    for val, et in re.findall(r"([\d.,]+) (yard su lancio|yard di corsa|yard ricevute|TD|intercetti|ricezioni|sack)", t):
        out.append([val, {"yard su lancio": "yard lanciate", "yard di corsa": "yard di corsa", "yard ricevute": "yard ricevute",
                          "TD": "touchdown"}.get(et, et)])
    return out


def riquadro(f: dict) -> dict:
    """Numeri della stagione divisi per squadra, per la colonna accanto all'articolo."""
    squadre = []
    for chiave, sigla in (("ospiti", f["ospite"]), ("padroniDiCasa", f["casa"])):
        t = f[chiave]
        gioc = []
        for g in t["giocatoriChiave"]:
            if g["ruolo"].startswith("secondo"):
                continue
            stato = STATI.get((g.get("rapportoInfortuni") or {}).get("stato", ""), "")
            partite = re.search(r"in (\d+) partite", g["stagione"])
            gioc.append({"nome": g["nome"], "ruolo": g["ruolo"].split(" (")[0], "dati": _dati(g), "stato": stato,
                         "nota": f"{partite.group(1)} partite" if partite else ""})
        squadre.append({"sigla": sigla, "nome": t["soprannome"], "bilancio": t["bilancio"], "giocatori": gioc,
                        "punti": {"fatti": n_it(t["puntiFattiPartita"]), "subiti": n_it(t["puntiSubitiPartita"])}})
    m = f["mercato"]
    linea = f"{soprannome(m['favorita'])} −{n_it(m['vantaggio'])} · totale {n_it(m['totale'])}" if m["favorita"] else ""
    return {"squadre": squadre, "linea": linea}


def pubblica(gid: str, tipo: str, file_testo: str) -> None:
    f = json.loads((FATTI / f"fatti_{gid}.json").read_text())
    testo = json.loads(Path(file_testo).read_text())
    problemi = controlla(testo, f)
    if problemi:
        print("NON pubblicato, da correggere:\n  " + "\n  ".join(problemi))
        sys.exit(1)
    USCITA.mkdir(parents=True, exist_ok=True)
    foto = USCITA / "stadi" / f"{f['casa']}.jpg"
    crediti = json.loads((USCITA / "stadi" / "crediti.json").read_text()) if (USCITA / "stadi" / "crediti.json").exists() else {}
    aid = f"{gid}_{tipo}"
    art = {"id": aid, "lega": f["lega"], "tipo": tipo, "settimana": f["settimana"], "ospite": f["ospite"], "casa": f["casa"],
           "dataIt": f["dataIt"], "oraIt": f["oraIt"], "inizioUtc": f["inizioUtc"], "stadio": f["stadio"],
           "campoNeutro": f["campoNeutro"], "coperto": f["coperto"],
           "bilanci": {"ospite": f["ospiti"]["bilancio"], "casa": f["padroniDiCasa"]["bilancio"]},
           "colori": f["colori"], "titolo": testo["titolo"], "paragrafi": testo["paragrafi"], "riquadro": riquadro(f),
           "foto": f"articoli/stadi/{f['casa']}.jpg" if foto.exists() else "",
           "fotoCrediti": crediti.get(f["casa"], ""), "pubblicato": dt.datetime.now(ROMA).isoformat(timespec="minutes")}
    vecchio = USCITA / f"{aid}.json"
    if vecchio.exists():
        art["meteo"] = json.loads(vecchio.read_text()).get("meteo")
    vecchio.write_text(json.dumps(art, ensure_ascii=False, indent=1))
    aggiorna_indice()
    print(f"Pubblicato: docs/articoli/{aid}.json")


def aggiorna_indice() -> None:
    voci = []
    for p in sorted(USCITA.glob("*_anteprima.json")) + sorted(USCITA.glob("*_cronaca.json")):
        a = json.loads(p.read_text())
        voci.append({k: a.get(k) for k in ("id", "lega", "tipo", "settimana", "ospite", "casa", "dataIt", "oraIt", "titolo", "pubblicato")})
    voci.sort(key=lambda v: v["pubblicato"] or "", reverse=True)
    (USCITA / "indice.json").write_text(json.dumps(voci, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ meteo delle anteprime

def impatto(m: dict) -> str:
    """Regola generica e pubblica (non le misure di Charlie): pioggia probabile e raffiche forti."""
    pioggia, raff, temp = m.get("pioggia") or 0, m.get("raffKmh") or 0, m.get("tempC")
    if raff >= 50 or (pioggia >= 70 and raff >= 35) or (temp is not None and temp <= -8):
        return "alto"
    if pioggia >= 50 or raff >= 35 or (temp is not None and temp <= 0):
        return "medio"
    return "basso"


def meteo() -> None:
    sys.path.insert(0, str(RADICE / "scripts"))
    from contesto import STADI_NFL, meteo as previsione
    ora = dt.datetime.now(dt.timezone.utc)
    for p in USCITA.glob("*_anteprima.json"):
        a = json.loads(p.read_text())
        inizio = dt.datetime.fromisoformat(a["inizioUtc"])
        if inizio < ora or inizio - ora > dt.timedelta(days=7) or a.get("campoNeutro"):
            continue
        lat, lon, _ = STADI_NFL.get(a["casa"], (None, None, None))
        if lat is None:
            continue
        m = previsione(lat, lon, inizio, "NFL")
        if not m:
            print(f"Meteo non disponibile per {a['id']}: la scheda resta com'era")
            continue
        scheda = {"tempC": m.get("tempC"), "pioggia": m.get("pioggia"), "ventoKmh": m.get("ventoKmh"), "raffKmh": m.get("raffKmh"),
                  "fonte": m.get("fonte"), "aggiornato": ora.astimezone(ROMA).isoformat(timespec="minutes")}
        scheda["impatto"] = "nessuno (al coperto)" if a.get("coperto") else impatto(scheda)
        a["meteo"] = scheda
        p.write_text(json.dumps(a, ensure_ascii=False, indent=1))
        print(f"Meteo aggiornato per {a['id']}: {scheda}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "fatti":
        fatti(sys.argv[2])
    elif len(sys.argv) >= 5 and sys.argv[1] == "pubblica":
        pubblica(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) >= 2 and sys.argv[1] == "meteo":
        meteo()
    else:
        print(__doc__)
