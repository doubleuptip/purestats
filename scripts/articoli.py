"""Articoli di PureStats (anteprime e cronache), scritti da Claude a partire da fatti verificati.

Comandi:
  python scripts/articoli.py fatti <game_id>                 prepara data/articoli/fatti_<game_id>.json
  python scripts/articoli.py pubblica <game_id> <tipo> <testo.json>
                                                             controlla il testo e lo pubblica in docs/articoli/
  python scripts/articoli.py foto_mancanti                   scarica da Wikimedia le foto degli stadi che mancano (nel workflow)
  python scripts/articoli.py foto                            rimette foto e crediti negli articoli pubblicati
  python scripts/articoli.py meteo_partite                   meteo di tutte le partite dei prossimi 7 giorni (docs/meteo/partite.json)
  python scripts/articoli.py meteo                           aggiorna la scheda meteo delle anteprime in arrivo
  python scripts/articoli.py scegli <nfl|college> <week> [stagione]   le 3 partite da raccontare
  python scripts/articoli.py da_fare                         anteprime (via entro 48 ore) e cronache da scrivere
  python scripts/articoli.py fatti_college <stagione> <week> "<ospite>" "<casa>"   fatti per un'anteprima college

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
import urllib.parse
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


def stadio_abituale(D: Dati, sq: str, stagione: int) -> str:
    sys.path.insert(0, str(RADICE / "scripts"))
    from nfl_indici import nome_stadio
    c = collections.Counter(nome_stadio(x["stadium"]) for x in D.cal
                            if x["home_team"] == sq and x["season"] in (str(stagione), str(stagione - 1)))
    return c.most_common(1)[0][0] if c else ""


def fatti(gid: str) -> dict:
    stagione, settimana = int(gid.split("_")[0]), int(gid.split("_")[1])
    D = Dati(stagione)
    r = next(x for x in D.cal if x["game_id"] == gid)
    casa, osp = r["home_team"], r["away_team"]
    # correzioni verificate (orario spostato dalla tv e non ancora in nflverse, sede particolare), con la fonte:
    # data/articoli/correzioni_<id>.json = {"inizioEt": "2026-11-22T16:25", "citta": "...", "fonte": "https://..."}
    corr_p = FATTI / f"correzioni_{gid}.json"
    corr = json.loads(corr_p.read_text()) if corr_p.exists() else {}
    if corr and not str(corr.get("fonte", "")).startswith("http"):
        raise SystemExit(f"{corr_p.name}: manca la fonte della correzione")
    inizio_et = (dt.datetime.fromisoformat(corr["inizioEt"]) if corr.get("inizioEt") else
                 dt.datetime.fromisoformat(f"{r['gameday']}T{r['gametime'] or '13:00'}")).replace(tzinfo=NY)
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
    from nfl_indici import nome_stadio
    coperto = STADI_NFL.get(casa, (0, 0, False))[2]
    out = {
        "id": gid, "lega": "nfl", "stagione": stagione, "settimana": settimana,
        "partita": f"{D.nomi[osp]} @ {D.nomi[casa]}", "ospite": osp, "casa": casa,
        "quando": quando, "dataIt": it.date().isoformat(), "oraIt": f"{it.hour:02d}:{it.minute:02d}",
        "inizioUtc": inizio_et.astimezone(dt.timezone.utc).isoformat(timespec="minutes"),
        "stadio": nome_stadio(r["stadium"]), "citta": corr.get("citta", ""),
        # campo neutro anche quando la squadra «di casa» gioca lontano dal suo stadio (partite all'estero)
        "campoNeutro": r["location"] == "Neutral" or nome_stadio(r["stadium"]) != stadio_abituale(D, casa, stagione),
        "coperto": coperto,
        "sfidaDiDivision": r["div_game"] == "1",
        "mercato": {"favorita": favorita, "vantaggio": abs(sp) if sp else None, "totale": num(r["total_line"], None),
                    "nota": "solo per dire chi parte favorito, a parole comuni (favoriti di poco fino a 3, favoriti, nettamente favoriti da 7,5), senza citare mercato, bookmaker, linea o totale"},
        "precedenti": prec,
        "ospiti": fatti_squadra(D, osp, casa, settimana, giorno, r["away_coach"], cl),
        "padroniDiCasa": fatti_squadra(D, casa, osp, settimana, giorno, r["home_coach"], cl),
        "colori": {"ospite": D.colori.get(osp), "casa": D.colori.get(casa)},
    }
    for k in ("ospiti", "padroniDiCasa"):          # giocatori senza nome in players.csv: fuori dai fatti
        for lista in ("cedutiInStagione", "arrivatiInStagione"):
            out[k][lista] = [x for x in out[k].get(lista) or [] if x.get("nome")]
    if out["campoNeutro"]:
        out["coperto"] = False if not corr.get("coperto") else True
    if r["home_score"] and r["away_score"]:
        out["partitaGiocata"] = fatti_partita(D, gid, r)
    FATTI.mkdir(parents=True, exist_ok=True)
    (FATTI / f"fatti_{gid}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"Fatti pronti: data/articoli/fatti_{gid}.json")
    return out


# ------------------------------------------------------------------ fatti della partita giocata (cronache)

def _tempo_sec(t: str) -> int:
    try:
        m, sec = (t or "0:0").split(":")
        return int(m) * 60 + int(sec)
    except ValueError:
        return 0


def _giocatore_partita(righe: list, sq: str, chiave: str, minimo: float = 1) -> dict | None:
    cand = [x for x in righe if x["team"] == sq and num(x[chiave]) >= minimo]
    return max(cand, key=lambda x: num(x[chiave])) if cand else None


def protagonisti(D: Dati, gid: str, sq: str) -> list[dict]:
    """I migliori della partita per una squadra, dal tabellino settimanale nflverse."""
    righe = [x for x in D.stats if x.get("game_id") == gid]
    out, presi = [], set()
    q = _giocatore_partita(righe, sq, "attempts", 5)
    if q:
        presi.add(q["player_id"])
        out.append({"ruolo": "QB", "nome": q["player_display_name"], "completiTentati": f"{int(num(q['completions']))}/{int(num(q['attempts']))}",
                    "yardLanciate": int(num(q["passing_yards"])), "tdLancio": int(num(q["passing_tds"])),
                    "intercettiSubiti": int(num(q["passing_interceptions"])), "sackSubiti": int(num(q["sacks_suffered"])),
                    "yardCorsa": int(num(q["rushing_yards"]))})
    c = _giocatore_partita([x for x in righe if x["player_id"] not in presi], sq, "rushing_yards", 10)
    if c:
        presi.add(c["player_id"])
        out.append({"ruolo": "Corse", "nome": c["player_display_name"], "posizione": c["position"], "corse": int(num(c["carries"])),
                    "yardCorsa": int(num(c["rushing_yards"])), "tdCorsa": int(num(c["rushing_tds"]))})
    for _ in range(2):
        r = _giocatore_partita([x for x in righe if x["player_id"] not in presi], sq, "receiving_yards", 20)
        if not r:
            break
        presi.add(r["player_id"])
        out.append({"ruolo": "Ricezioni", "nome": r["player_display_name"], "posizione": r["position"],
                    "ricezioni": int(num(r["receptions"])), "bersagli": int(num(r["targets"])),
                    "yardRicevute": int(num(r["receiving_yards"])), "tdRicezione": int(num(r["receiving_tds"]))})
    dif = [x for x in righe if x["team"] == sq]
    if dif:
        d = max(dif, key=lambda x: (num(x["def_sacks"]) * 3 + num(x["def_interceptions"]) * 4 + num(x["def_fumbles_forced"]) * 3
                                    + (num(x["def_tackles_solo"]) + num(x["def_tackle_assists"])) * 0.3
                                    + num(x["def_pass_defended"])))
        if num(d["def_sacks"]) or num(d["def_interceptions"]) or num(d["def_tackles_solo"]) + num(d["def_tackle_assists"]) >= 5:
            out.append({"ruolo": "Difesa", "nome": d["player_display_name"], "posizione": d["position"],
                        "placcaggi": int(num(d["def_tackles_solo"]) + num(d["def_tackle_assists"])), "sack": num(d["def_sacks"]),
                        "intercetti": int(num(d["def_interceptions"])), "fumbleForzati": int(num(d["def_fumbles_forced"])),
                        "passaggiDeviati": int(num(d["def_pass_defended"]))})
    return out


COLONNE_GIOCATORI = ("passer_player_id", "receiver_player_id", "rusher_player_id", "kicker_player_id",
                     "interception_player_id", "sack_player_id", "half_sack_1_player_id", "fumbled_1_player_id",
                     "fumble_recovery_1_player_id", "blocked_player_id", "td_player_id", "safety_player_id")


def nomi_completi(D: Dati, x: dict) -> list[str]:
    """Nome e cognome dei giocatori di un'azione (il play-by-play scrive solo «C.Stroud»)."""
    out = []
    for c in COLONNE_GIOCATORI:
        g = D.giocatori.get(x.get(c) or "")
        if g and g.get("display_name") and g["display_name"] not in out:
            out.append(g["display_name"])
    return out


def fatti_partita(D: Dati, gid: str, r: dict) -> dict:
    """Quello che è successo in campo, dal play-by-play nflverse: punteggio per quarto, marcature, momenti
    decisivi (stesso metodo della Giornata), numeri di squadra, protagonisti, esito contro la linea."""
    sys.path.insert(0, str(RADICE / "scripts"))
    import nfl_indici as NI
    import nfl_racconto
    pbp = [x for x in leggi_csv(scarica(f"pbp_{D.stagione}.csv.gz", f"{NFLVERSE}/pbp/play_by_play_{D.stagione}.csv.gz"))
           if x["game_id"] == gid]
    if not pbp:
        raise SystemExit(f"Play-by-play di {gid} non ancora pubblicato da nflverse: la cronaca deve aspettare")
    casa, osp = r["home_team"], r["away_team"]
    pc, po = int(r["home_score"]), int(r["away_score"])
    # punteggio alla fine di ogni quarto
    quarti, ultimo = {}, (0, 0)
    for x in pbp:
        if x["total_home_score"] and x["total_away_score"]:
            ultimo = (int(num(x["total_away_score"])), int(num(x["total_home_score"])))
        if x["qtr"]:
            quarti[int(x["qtr"])] = ultimo
    parziali, prima = [], (0, 0)
    for q in sorted(quarti):
        o, c = quarti[q]
        parziali.append({"quarto": "supplementare" if q == 5 else f"{q}°", "ospite": o - prima[0], "casa": c - prima[1]})
        prima = (o, c)
    # marcature: touchdown (con il punteggio dopo la trasformazione), field goal, safety
    marcature = []
    for i, x in enumerate(pbp):
        tipo = ("touchdown" if x["touchdown"] == "1" else "field goal" if x["field_goal_result"] == "made"
                else "safety" if x["safety"] == "1" else None)
        if not tipo:
            continue
        dopo = pbp[i + 1] if i + 1 < len(pbp) else x
        fonte = dopo if tipo == "touchdown" and (dopo["extra_point_attempt"] == "1" or dopo["two_point_attempt"] == "1") else x
        testo, chi, _ = nfl_racconto.traduci(x["desc"])
        squadra = x["td_team"] if tipo == "touchdown" and x["td_team"] else (x["defteam"] if tipo == "safety" else x["posteam"])
        marcature.append({"quarto": x["qtr"], "tempo": x["time"], "squadra": D.nomi.get(squadra, squadra), "tipo": tipo,
                          "azione": testo, "chi": chi, "giocatori": nomi_completi(D, x),
                          "punteggioDopo": f"{D.nomi[osp]} {int(num(fonte['total_away_score']))} - {D.nomi[casa]} {int(num(fonte['total_home_score']))}"})
    # momenti decisivi, come nella Giornata
    cand = []
    for x in pbp:
        hw, dw = num(x["vegas_home_wp"], None), num(x["vegas_home_wpa"], None)
        desc = x["desc"] or ""
        chiave = any(x[c] == "1" for c in ("touchdown", "interception", "fumble_lost", "fourth_down_failed", "safety"))
        if hw is None or dw is None or any(k in desc for k in ("No Play", "Timeout", "kneels", "END QUARTER", "END GAME")):
            continue
        if abs(dw) < NI.SOGLIA_MOMENTO and not chiave:
            continue
        peso = abs(dw) * (1.0 if (dw > 0) == (pc > po) else NI.PESO_CONTRARIO) * (NI.PESO_CHIAVE if chiave else 1.0)
        cand.append((peso, x, hw, dw))
    momenti, per_q = [], collections.Counter()
    for peso, x, hw, dw in sorted(cand, key=lambda c: -c[0]):
        if per_q[x["qtr"]] < NI.MOMENTI_PER_QUARTO and len(momenti) < NI.MOMENTI_PER_PARTITA:
            per_q[x["qtr"]] += 1
            testo, chi, _ = nfl_racconto.traduci(x["desc"])
            momenti.append({"quarto": x["qtr"], "tempo": x["time"], "squadra": D.nomi.get(x["posteam"], x["posteam"]),
                            "azione": testo, "chi": chi, "giocatori": nomi_completi(D, x),
                            "probabilitaVittoria": f"{D.nomi[casa]} da {round(hw * 100)}% a {round(max(0, min(1, hw + dw)) * 100)}%"})
    momenti.sort(key=lambda m: (int(m["quarto"]), -_tempo_sec(m["tempo"])))
    # numeri di squadra
    def numeri(sq: str) -> dict:
        az = [x for x in pbp if x["posteam"] == sq and x["play_type"] in ("pass", "run") and "No Play" not in (x["desc"] or "")]
        terzi = [x for x in pbp if x["posteam"] == sq and (x["third_down_converted"] == "1" or x["third_down_failed"] == "1")]
        quarti_d = [x for x in pbp if x["posteam"] == sq and (x["fourth_down_converted"] == "1" or x["fourth_down_failed"] == "1")]
        drive = {}
        for x in pbp:
            if x["posteam"] == sq and x["drive"] and x["drive_time_of_possession"]:
                drive[x["drive"]] = _tempo_sec(x["drive_time_of_possession"])
        poss = sum(drive.values())
        return {"yardTotali": int(sum(num(x["yards_gained"]) for x in az)),
                "yardLancio": int(sum(num(x["passing_yards"]) for x in az if x["play_type"] == "pass")),
                "yardCorsa": int(sum(num(x["rushing_yards"]) for x in az if x["play_type"] == "run")),
                "azioni": len(az), "primiDown": sum(1 for x in pbp if x["posteam"] == sq and x["first_down"] == "1"),
                "terziDown": f"{sum(1 for x in terzi if x['third_down_converted'] == '1')}/{len(terzi)}",
                "quartiDown": f"{sum(1 for x in quarti_d if x['fourth_down_converted'] == '1')}/{len(quarti_d)}",
                "palle perse": sum(1 for x in pbp if x["posteam"] == sq and (x["interception"] == "1" or x["fumble_lost"] == "1")),
                "sackSubiti": sum(1 for x in pbp if x["posteam"] == sq and x["sack"] == "1"),
                "penalita": sum(1 for x in pbp if x["penalty_team"] == sq and x["penalty"] == "1"),
                "possesso": f"{poss // 60}:{poss % 60:02d}"}
    sp, tot = num(r["spread_line"], None), num(r["total_line"], None)
    esito = {}
    if sp:
        fav, cane = (casa, osp) if sp > 0 else (osp, casa)
        scarto = (pc - po) if fav == casa else (po - pc)
        esito["linea"] = (f"{D.nomi[fav]} favoriti di {n_it(abs(sp))}: " +
                          ("hanno vinto con un margine più largo" if scarto > abs(sp) else
                           "hanno vinto ma con un margine più stretto" if scarto > 0 else "hanno perso"))
    if tot:
        esito["totale"] = f"{pc + po} punti in tutto contro un totale di {n_it(tot)}: " + ("sopra" if pc + po > tot else "sotto")
    video = ""
    try:
        g = json.loads((RADICE / "docs" / "data_nfl.json").read_text()).get("giornata") or {}
        for p in g.get("partite", []):
            if p["casa"] == casa and p["ospite"] == osp and (p.get("video") or {}).get("id"):
                video = p["video"]["id"]
    except (OSError, ValueError):
        pass
    sett = int(r["week"])
    return {"risultato": f"{D.nomi[osp]} {po} - {D.nomi[casa]} {pc}", "puntiOspite": po, "puntiCasa": pc,
            "vincitore": D.nomi[casa] if pc > po else D.nomi[osp] if po > pc else "pareggio", "scarto": abs(pc - po),
            "parziali": parziali, "marcature": marcature, "momentiDecisivi": momenti,
            "numeri": {"ospiti": numeri(osp), "padroniDiCasa": numeri(casa)},
            "protagonisti": {"ospiti": protagonisti(D, gid, osp), "padroniDiCasa": protagonisti(D, gid, casa)},
            "contoLaLinea": esito,
            "bilancioDopo": {"ospiti": bilancio(partite_giocate(D, osp, D.stagione, (D.stagione, sett + 1))),
                             "padroniDiCasa": bilancio(partite_giocate(D, casa, D.stagione, (D.stagione, sett + 1)))},
            "serieDopo": {"ospiti": serie(partite_giocate(D, osp, D.stagione, (D.stagione, sett + 1))),
                          "padroniDiCasa": serie(partite_giocate(D, casa, D.stagione, (D.stagione, sett + 1)))},
            "video": video}


# ------------------------------------------------------------------ scelta delle partite (le 3 più importanti)

def scegli_nfl(stagione: int, settimana: int, quante: int = 3, dopo_utc: dt.datetime | None = None) -> list[dict]:
    """Le partite da raccontare: squadre forti (bilancio), partita equilibrata (linea), sfida di division,
    prima serata. Regola pubblica e semplice, scritta qui: niente misure private."""
    cal = leggi_csv(scarica("games.csv", f"{NFLVERSE}/schedules/games.csv"))
    bil = collections.defaultdict(lambda: [0, 0])
    for x in cal:
        if x["season"] == str(stagione) and x["game_type"] == "REG" and x["result"] and int(x["week"]) < settimana:
            ris = int(x["result"])
            if ris:
                vince, perde = (x["home_team"], x["away_team"]) if ris > 0 else (x["away_team"], x["home_team"])
                bil[vince][0] += 1
                bil[perde][1] += 1
    out = []
    for x in cal:
        if x["season"] != str(stagione) or x["week"] != str(settimana) or x["result"]:
            continue
        inizio = dt.datetime.fromisoformat(f"{x['gameday']}T{x['gametime'] or '13:00'}").replace(tzinfo=NY)
        if dopo_utc and inizio < dopo_utc:
            continue
        pv = lambda sq: bil[sq][0] / max(1, sum(bil[sq]))
        sp = abs(num(x["spread_line"], 7.0))
        sera = inizio.hour >= 19 or inizio.weekday() in (0, 3)
        punti = 15 * (pv(x["home_team"]) + pv(x["away_team"])) + 10 * (1 - min(sp, 14) / 14) \
            + (2 if x["div_game"] == "1" else 0) + (2 if sera else 0)
        out.append({"id": x["game_id"], "partita": f"{x['away_team']} @ {x['home_team']}", "punteggio": round(punti, 1),
                    "bilanci": f"{'-'.join(map(str, bil[x['away_team']]))} / {'-'.join(map(str, bil[x['home_team']]))}",
                    "linea": sp, "division": x["div_game"] == "1", "primaSerata": sera})
    return sorted(out, key=lambda g: -g["punteggio"])[:quante]


def _college_righe() -> list[dict]:
    return leggi_csv(RADICE / "data" / "college.csv")


def _college_bilanci(righe: list, stagione: int, prima_di: str | None = None) -> dict:
    bil = collections.defaultdict(lambda: {"v": 0, "s": 0, "cv": 0, "cs": 0, "gare": []})
    for x in sorted(righe, key=lambda x: x["Data"]):
        if x["Stagione"] != str(stagione) or not x["PuntiCasa"] or (prima_di and x["Data"] >= prima_di):
            continue
        pc, po = int(x["PuntiCasa"]), int(x["PuntiOspite"])
        conf = x["ConferenzaCasa"] == x["ConferenzaOspite"] and x["Tipo"] == "regular"
        for sq, avv, fa, sub, casa in ((x["Casa"], x["Ospite"], pc, po, True), (x["Ospite"], x["Casa"], po, pc, False)):
            b = bil[sq]
            vinta = fa > sub
            b["v" if vinta else "s"] += 1
            if conf:
                b["cv" if vinta else "cs"] += 1
            b["gare"].append({"data": x["Data"], "avversario": avv, "inCasa": casa, "fatti": fa, "subiti": sub,
                              "esito": "vittoria" if vinta else "sconfitta", "tipo": x["Tipo"]})
    return bil


def scegli_college(stagione: int, settimana: int, quante: int = 3) -> list[dict]:
    """Squadre forti (SP+ e bilancio) che si affrontano in una partita equilibrata."""
    sp = {x["team"]: x for x in json.loads((RADICE / "data" / "college_sp.json").read_text())["dati"]}
    righe = _college_righe()
    bil = _college_bilanci(righe, stagione)
    out = []
    for x in righe:
        if x["Stagione"] != str(stagione) or x["Settimana"] != str(settimana) or x["PuntiCasa"]:
            continue
        a, b = sp.get(x["Ospite"]), sp.get(x["Casa"])
        if not a or not b:
            continue
        pv = lambda sq: bil[sq]["v"] / max(1, bil[sq]["v"] + bil[sq]["s"])
        ra, rb = a["rating"], b["rating"]
        punti = min(ra, rb) + 0.5 * max(ra, rb) - 0.5 * abs(ra - rb) + 15 * (pv(x["Ospite"]) + pv(x["Casa"]))
        out.append({"partita": f"{x['Ospite']} @ {x['Casa']}", "ospite": x["Ospite"], "casa": x["Casa"],
                    "punteggio": round(punti, 1), "spOspite": a["ranking"], "spCasa": b["ranking"],
                    "bilanci": f"{bil[x['Ospite']]['v']}-{bil[x['Ospite']]['s']} / {bil[x['Casa']]['v']}-{bil[x['Casa']]['s']}"})
    return sorted(out, key=lambda g: -g["punteggio"])[:quante]


# ------------------------------------------------------------------ fatti del college (anteprime)

def id_college(stagione: int, settimana: int, ospite: str, casa: str) -> str:
    pulito = lambda t: re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-")
    return f"{stagione}_{settimana:02d}_{pulito(ospite)}_{pulito(casa)}"


def fatti_college(stagione: int, settimana: int, ospite: str, casa: str) -> dict:
    """Fatti per l'anteprima di una partita del college: bilanci (anche in conference), ultime partite, punti,
    SP+ (CollegeFootballData), giocatori chiave dai tabellini ESPN completi, precedenti dal 2019."""
    sys.path.insert(0, str(RADICE / "scripts"))
    import college_indici as CI
    pub = json.loads((RADICE / "docs" / "data_college.json").read_text())
    gara = next((x for x in pub["ultimePartite"] if str(x["stagione"]) == str(stagione) and str(x["settimana"]) == str(settimana)
                 and x["casa"] == casa and x["ospite"] == ospite), None)
    if not gara:
        raise SystemExit(f"Partita {ospite} @ {casa} della week {settimana} non trovata in docs/data_college.json")
    righe = _college_righe()
    riga = next((x for x in righe if x["Stagione"] == str(stagione) and x["Settimana"] == str(settimana)
                 and x["Casa"] == casa and x["Ospite"] == ospite), {})
    bil = _college_bilanci(righe, stagione, gara["data"])
    scorsa = _college_bilanci(righe, stagione - 1)
    sp = {x["team"]: x for x in json.loads((RADICE / "data" / "college_sp.json").read_text())["dati"]}
    n_sp = len(sp)
    prest = CI._prestazioni_tabellini(stagione)
    passate = {}
    for gioc in CI._prestazioni_tabellini(stagione - 1).values():
        for pid, g in gioc.items():
            passate.setdefault(pid, {}).update(g["partite"])

    def squadra(sq: str, avv: str) -> dict:
        b = bil[sq]
        gare = b["gare"]
        serie_txt = ""
        if gare:
            k = 0
            while k < len(gare) and gare[-1 - k]["esito"] == gare[-1]["esito"]:
                k += 1
            if k >= 2:
                serie_txt = f"{k} {'vittorie' if gare[-1]['esito'] == 'vittoria' else 'sconfitte'} di fila"
        s = sp.get(sq) or {}
        giocatori = []
        scelte, n_part = CI._scelta_squadra(prest.get(sq) or {})
        for pid, gruppo in scelte:
            g = prest[sq][pid]
            pr = CI._profilo_tabellini(g["nome"], gruppo, g["partite"], passate.get(pid), n_part)
            giocatori.append({"nome": pr["nome"], "ruolo": {"QB": "quarterback", "RB": "running back", "WR": "ricevitore"}[pr["ruolo"]],
                              "misura": pr["misura"], "mediaStagione": pr["mediaStagione"], "mediaUltime3": pr["mediaUltime3"],
                              "mediaAnnoScorso": pr["mediaPassato"], "forma": pr["forma"], "nota": pr["nota"]})
            if gruppo == "QB":
                c = CI._profilo_tabellini(g["nome"], "QB corse", g["partite"], passate.get(pid), n_part)
                if (c["mediaStagione"] or 0) >= CI.SOGLIA_CORSE_QB:
                    giocatori[-1]["corseAPartita"] = c["mediaStagione"]
        sc = scorsa.get(sq)
        return {"nome": sq, "mascotte": (pub["loghi"].get(sq) or {}).get("mascotte", ""),
                "conference": riga.get("ConferenzaCasa" if sq == casa else "ConferenzaOspite", ""),
                "bilancio": f"{b['v']}-{b['s']}", "bilancioConference": f"{b['cv']}-{b['cs']}", "serieAperta": serie_txt,
                "ultimePartite": [f"{'vittoria' if x['esito'] == 'vittoria' else 'sconfitta'} {x['fatti']}-{x['subiti']} "
                                  f"{'contro' if x['inCasa'] else 'a'} {x['avversario']}" for x in gare[-5:]],
                "puntiFattiPartita": round(sum(x["fatti"] for x in gare) / len(gare), 1) if gare else None,
                "puntiSubitiPartita": round(sum(x["subiti"] for x in gare) / len(gare), 1) if gare else None,
                "spPlus": {"posizione": s.get("ranking"), "attacco": (s.get("offense") or {}).get("ranking"),
                           "difesa": (s.get("defense") or {}).get("ranking"), "squadre": n_sp,
                           "nota": "SP+ di CollegeFootballData: indice di forza; dire «tra le migliori/peggiori», non i decimali"},
                "stagioneScorsa": f"{sc['v']}-{sc['s']}" if sc else "",
                "giocatoriChiave": giocatori}
    prec = []
    for x in sorted([x for x in righe if {x["Casa"], x["Ospite"]} == {casa, ospite} and x["PuntiCasa"] and x["Data"] < gara["data"]],
                    key=lambda x: x["Data"])[-3:]:
        prec.append({"stagione": int(x["Stagione"]), "risultato": f"{x['Casa']} {x['PuntiCasa']} - {x['Ospite']} {x['PuntiOspite']}"})
    inizio = dt.datetime.fromisoformat(gara["inizio"].replace("Z", "+00:00"))
    it = inizio.astimezone(ROMA)
    quando = (f"nella notte tra {GIORNI[(it - dt.timedelta(days=1)).weekday()]} e {GIORNI[it.weekday()]} {it.day} {MESI[it.month - 1]}, "
              f"alle {it.hour}:{it.minute:02d} italiane") if it.hour < 7 else \
        f"{GIORNI[it.weekday()]} {it.day} {MESI[it.month - 1]}, alle {it.hour}:{it.minute:02d} italiane"
    stadi = json.loads((RADICE / "data" / "college_stadi.json").read_text())["squadre"]
    gid = id_college(stagione, settimana, ospite, casa)
    out = {"id": gid, "lega": "college", "stagione": stagione, "settimana": settimana, "partita": f"{ospite} @ {casa}",
           "ospite": ospite, "casa": casa, "quando": quando, "dataIt": it.date().isoformat(), "oraIt": f"{it.hour:02d}:{it.minute:02d}",
           "inizioUtc": inizio.isoformat(timespec="minutes"), "stadio": re.sub(r"\s*\(.*\)$", "", gara.get("stadio") or ""),
           "citta": (re.search(r"\(([^,)]+)", gara.get("stadio") or "") or [None, ""])[1],
           "campoNeutro": riga.get("CampoNeutro", "") not in ("", "0", "False"), "coperto": bool((stadi.get(casa) or [0, 0, False])[2]),
           "sfidaDiConference": riga.get("ConferenzaCasa") == riga.get("ConferenzaOspite"),
           "precedenti": prec, "mercato": {"favorita": "", "vantaggio": None, "totale": None},
           "ospiti": squadra(ospite, casa), "padroniDiCasa": squadra(casa, ospite),
           "colori": {"ospite": (pub["loghi"].get(ospite) or {}).get("colore"), "casa": (pub["loghi"].get(casa) or {}).get("colore")}}
    for k, sq in (("ospiti", ospite), ("padroniDiCasa", casa)):
        out[k]["soprannome"] = sq
    if riga.get("PuntiCasa"):
        p = fatti_partita_college(stagione, settimana, ospite, casa, riga)
        if p:
            out["partitaGiocata"] = p
        else:
            print("Partita giocata ma tabellino ESPN non ancora in archivio: la cronaca deve aspettare")
    FATTI.mkdir(parents=True, exist_ok=True)
    (FATTI / f"fatti_{gid}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"Fatti pronti: data/articoli/fatti_{gid}.json")
    return out



def _box(cats: dict, et: dict, cat: str, col: str, riga: list) -> float:
    lab = et.get(cat) or []
    if col not in lab or len(riga) <= 2 + lab.index(col):
        return 0.0
    return num(str(riga[2 + lab.index(col)]).split("/")[-1] if col == "C/ATT" else riga[2 + lab.index(col)])


def fatti_partita_college(stagione: int, settimana: int, ospite: str, casa: str, riga: dict) -> dict | None:
    """Cronaca del college: punteggio (college.csv), tabellino e azioni ESPN già in archivio (giocate decisive
    per probabilità di vittoria, flag, yard e azioni, punti negli ultimi due minuti), video ufficiale se c'è."""
    tab = json.loads((RADICE / "data" / f"college_tabellini_{stagione}.json").read_text())
    eid, v = next(((k, x) for k, x in tab.items() if x.get("casa") == casa and x.get("ospite") == ospite
                   and str(x.get("settimana")) == str(settimana)), (None, None))
    if not v:
        return None
    et, sq = v.get("etichette") or {}, v.get("squadre") or {}
    pc, po = int(riga["PuntiCasa"]), int(riga["PuntiOspite"])

    def protagonisti(t: str) -> list[dict]:
        c = sq.get(t) or {}
        out, presi = [], set()
        pas = max(c.get("passing") or [], key=lambda r: _box(c, et, "passing", "C/ATT", r), default=None)
        if pas:
            presi.add(pas[0])
            out.append({"ruolo": "QB", "nome": pas[1], "completiTentati": pas[2 + et["passing"].index("C/ATT")],
                        "yardLanciate": int(_box(c, et, "passing", "YDS", pas)), "tdLancio": int(_box(c, et, "passing", "TD", pas)),
                        "intercettiSubiti": int(_box(c, et, "passing", "INT", pas))})
        cor = max([r for r in c.get("rushing") or [] if r[0] not in presi], key=lambda r: _box(c, et, "rushing", "YDS", r), default=None)
        if cor and _box(c, et, "rushing", "YDS", cor) >= 10:
            presi.add(cor[0])
            out.append({"ruolo": "Corse", "nome": cor[1], "corse": int(_box(c, et, "rushing", "CAR", cor)),
                        "yardCorsa": int(_box(c, et, "rushing", "YDS", cor)), "tdCorsa": int(_box(c, et, "rushing", "TD", cor))})
        ric = sorted([r for r in c.get("receiving") or [] if r[0] not in presi], key=lambda r: -_box(c, et, "receiving", "YDS", r))
        for r in ric[:2]:
            if _box(c, et, "receiving", "YDS", r) >= 20:
                out.append({"ruolo": "Ricezioni", "nome": r[1], "ricezioni": int(_box(c, et, "receiving", "REC", r)),
                            "yardRicevute": int(_box(c, et, "receiving", "YDS", r)), "tdRicezione": int(_box(c, et, "receiving", "TD", r))})
        dif = max(c.get("defensive") or [], key=lambda r: _box(c, et, "defensive", "SACKS", r) * 3 + _box(c, et, "defensive", "TOT", r) * 0.3
                  + _box(c, et, "defensive", "TFL", r), default=None)
        if dif:
            out.append({"ruolo": "Difesa", "nome": dif[1], "placcaggi": int(_box(c, et, "defensive", "TOT", dif)),
                        "sack": _box(c, et, "defensive", "SACKS", dif), "intercetti": 0,
                        "fumbleForzati": 0, "passaggiDeviati": int(_box(c, et, "defensive", "PD", dif))})
        return out
    az = v.get("azioni") or {}
    giocate = sorted(az.get("giocate") or [], key=lambda g: -g.get("valore", 0))[:6]
    giocate.sort(key=lambda g: (int(g.get("quarto") or 0), -_tempo_sec(g.get("tempo"))))
    nomi_box = {r[1].split()[-1]: r[1] for t in sq.values() for cat in t.values() for r in cat}
    momenti = [{"quarto": g["quarto"], "tempo": g["tempo"], "squadra": g["squadra"], "azione": g["testo"],
                "evento": g.get("evento", ""), "probabilitaVittoria": f"{g['squadra']} da {g['prima']}% a {g['dopo']}%",
                "giocatori": [nomi_box[c] for c in re.findall(r"[A-Z]\.([A-Z][\w'’-]+)", g["testo"]) if c in nomi_box]}
               for g in giocate]
    numeri = {}
    for chiave, t in (("ospiti", ospite), ("padroniDiCasa", casa)):
        ya = (az.get("yardAzioni") or {}).get(t) or [None, None]
        fl = (az.get("flag") or {}).get(t) or [None, None]
        persi = sum(_box(sq.get(t) or {}, et, "fumbles", "LOST", r) for r in (sq.get(t) or {}).get("fumbles") or [])
        intercetti = sum(_box(sq.get(t) or {}, et, "passing", "INT", r) for r in (sq.get(t) or {}).get("passing") or [])
        numeri[chiave] = {"yardTotali": ya[0], "azioni": ya[1], "palle perse": int(persi + intercetti),
                          "penalita": fl[0], "yardPenalita": fl[1],
                          "puntiUltimiDueMinuti": ((az.get("due") or {}).get(t) or [None])[0]}
    righe = _college_righe()
    bil = _college_bilanci(righe, stagione)
    lin = json.loads((RADICE / "data" / "college_linee.json").read_text()).get(eid) or {}
    esito = {}
    if lin.get("margine") is not None:
        m = float(lin["margine"])          # margine atteso della squadra di casa (positivo = casa favorita)
        fav = casa if m > 0 else ospite
        scarto = (pc - po) if fav == casa else (po - pc)
        esito["linea"] = (f"{fav} favoriti di {n_it(abs(m))}: " + ("hanno vinto con un margine più largo" if scarto > abs(m)
                          else "hanno vinto ma con un margine più stretto" if scarto > 0 else "hanno perso"))
    if lin.get("totale") is not None:
        esito["totale"] = f"{pc + po} punti in tutto contro un totale di {n_it(float(lin['totale']))}: " + \
            ("sopra" if pc + po > float(lin["totale"]) else "sotto")
    vid = json.loads((RADICE / "data" / "college_video.json").read_text()).get(f"{stagione}_{settimana}_{ospite}_{casa}") or {}
    return {"risultato": f"{ospite} {po} - {casa} {pc}", "puntiOspite": po, "puntiCasa": pc,
            "vincitore": casa if pc > po else ospite, "scarto": abs(pc - po), "parziali": [], "marcature": [],
            "momentiDecisivi": momenti, "numeri": numeri,
            "protagonisti": {"ospiti": protagonisti(ospite), "padroniDiCasa": protagonisti(casa)}, "contoLaLinea": esito,
            "bilancioDopo": {"ospiti": f"{bil[ospite]['v']}-{bil[ospite]['s']}", "padroniDiCasa": f"{bil[casa]['v']}-{bil[casa]['s']}"},
            "video": vid.get("id", "") if vid.get("ufficiale") else ""}

def riquadro_college(f: dict) -> dict:
    squadre = []
    for chiave, sigla in (("ospiti", f["ospite"]), ("padroniDiCasa", f["casa"])):
        t = f[chiave]
        gioc = []
        for g in t["giocatoriChiave"]:
            dati = [[n_it(g["mediaStagione"]), g["misura"] + " a partita"]]
            if g.get("corseAPartita"):
                dati.append([n_it(g["corseAPartita"]), "yard corse a partita"])
            gioc.append({"nome": g["nome"], "ruolo": {"quarterback": "QB", "running back": "RB"}.get(g["ruolo"], "Ricevitore"),
                         "dati": dati, "stato": "", "nota": g["nota"].split(" · ")[0]})
        visti = collections.Counter()
        for g in gioc:
            visti[g["ruolo"]] += 1
            if visti[g["ruolo"]] == 2:
                g["ruolo"] += " (2°)"
        squadre.append({"sigla": sigla, "nome": sigla, "bilancio": t["bilancio"], "giocatori": gioc,
                        "punti": {"fatti": n_it(t["puntiFattiPartita"]), "subiti": n_it(t["puntiSubitiPartita"])}})
    return {"squadre": squadre, "linea": ""}


# ------------------------------------------------------------------ lavoro del giorno (per l'attività programmata)

ANTEPRIMA_ORE = 48      # l'anteprima si scrive quando mancano al massimo 48 ore al via


def _scelte(lega: str, stagione: int, settimana: int, calcola) -> list:
    """Le partite scelte di una settimana restano quelle: si calcolano una volta e si salvano."""
    p = FATTI / f"scelte_{lega}_{stagione}_{settimana:02d}.json"
    if p.exists():
        return json.loads(p.read_text())
    scelte = calcola()
    FATTI.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(scelte, ensure_ascii=False, indent=1))
    return scelte


def da_fare() -> list[dict]:
    """Anteprime da scrivere (via entro 48 ore) e cronache da scrivere (partita finita) per le partite scelte."""
    ora = dt.datetime.now(dt.timezone.utc)
    fatto = {p.stem for p in USCITA.glob("*.json")}
    out = []
    # NFL
    cal = leggi_csv(scarica("games.csv", f"{NFLVERSE}/schedules/games.csv"))
    def inizio_nfl(x):
        corr = FATTI / f"correzioni_{x['game_id']}.json"
        c = json.loads(corr.read_text()) if corr.exists() else {}
        t = c.get("inizioEt") or f"{x['gameday']}T{x['gametime'] or '13:00'}"
        return dt.datetime.fromisoformat(t).replace(tzinfo=NY).astimezone(dt.timezone.utc)
    # settimane con partite tra 4 giorni fa e le prossime 48 ore: la scelta si fa a ridosso, con i bilanci aggiornati
    vicine = {(int(x["season"]), int(x["week"])) for x in cal if x["game_type"] == "REG" and x["gameday"]
              and -4 * 86400 < (inizio_nfl(x) - ora).total_seconds() < ANTEPRIMA_ORE * 3600}
    for stag, sett in sorted(vicine):
        for g in _scelte("nfl", stag, sett, lambda: scegli_nfl(stag, sett)):
            x = next((y for y in cal if y["game_id"] == g["id"]), None)
            if not x:
                continue
            if x["result"] and f"{g['id']}_cronaca" not in fatto:
                out.append({"lega": "nfl", "tipo": "cronaca", "id": g["id"], "partita": g["partita"],
                            "fatti": f"python3 scripts/articoli.py fatti {g['id']}"})
            elif not x["result"] and f"{g['id']}_anteprima" not in fatto and \
                    dt.timedelta(0) < inizio_nfl(x) - ora <= dt.timedelta(hours=ANTEPRIMA_ORE):
                out.append({"lega": "nfl", "tipo": "anteprima", "id": g["id"], "partita": g["partita"],
                            "fatti": f"python3 scripts/articoli.py fatti {g['id']}"})
    # College
    pub = json.loads((RADICE / "docs" / "data_college.json").read_text())
    inizi = {(str(x["stagione"]), str(x["settimana"]), x["ospite"], x["casa"]): x.get("inizio") for x in pub["ultimePartite"]}
    righe = _college_righe()
    def inizio_c(x):
        t = inizi.get((x["Stagione"], x["Settimana"], x["Ospite"], x["Casa"]))
        if t and "T" in t:                      # orario fissato dalla tv
            d = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
        return dt.datetime.fromisoformat((t or x["Data"])[:10] + "T17:00").replace(tzinfo=dt.timezone.utc)
    vicine = {(int(x["Stagione"]), int(x["Settimana"])) for x in righe if x["Data"]
              and -4 * 86400 < (inizio_c(x) - ora).total_seconds() < ANTEPRIMA_ORE * 3600}
    for stag, sett in sorted(vicine):
        for g in _scelte("college", stag, sett, lambda: scegli_college(stag, sett)):
            x = next((y for y in righe if y["Stagione"] == str(stag) and y["Settimana"] == str(sett)
                      and y["Ospite"] == g["ospite"] and y["Casa"] == g["casa"]), None)
            if not x:
                continue
            gid = id_college(stag, sett, g["ospite"], g["casa"])
            cmd = f'python3 scripts/articoli.py fatti_college {stag} {sett} "{g["ospite"]}" "{g["casa"]}"'
            if x["PuntiCasa"] and f"{gid}_cronaca" not in fatto:
                out.append({"lega": "college", "tipo": "cronaca", "id": gid, "partita": g["partita"], "fatti": cmd})
            elif not x["PuntiCasa"] and f"{gid}_anteprima" not in fatto and \
                    dt.timedelta(0) < inizio_c(x) - ora <= dt.timedelta(hours=ANTEPRIMA_ORE):
                out.append({"lega": "college", "tipo": "anteprima", "id": gid, "partita": g["partita"], "fatti": cmd})
    return out


# ------------------------------------------------------------------ controllo e pubblicazione

# Pagine pubbliche senza termini da scommesse (22/11/2026): il testo non cita mercato, bookmaker, linee, totali, over/under
VIETATE = re.compile(r"mercato americano|bookmaker|scommess|\bspread\b|\bover\b|\bunder\b|contro la linea|"
                     r"linea (?:di chiusura|del mercato|d'apertura)|totale di \d|pronostic", re.I)

PAROLE_OK = {"NFL", "AFC", "NFC", "Super", "Bowl", "PureStats", "Week", "Pro", "East", "West", "North", "South"}


def controlla(testo: dict, f: dict) -> list[str]:
    """Numeri e nomi propri del testo devono comparire nei fatti. Restituisce l'elenco dei problemi."""
    corpo = json.dumps(f, ensure_ascii=False)
    numeri = set(re.findall(r"\d+(?:[.,]\d+)?", corpo))
    numeri |= {x.replace(".", ",") for x in numeri} | {x.split(".")[0] for x in numeri}
    numeri |= {n_it(int(x)) for x in re.findall(r"\b\d{4,}\b", corpo)}
    tutto = testo["titolo"] + "\n" + "\n".join(testo["paragrafi"])
    problemi = [f"termine da scommesse, da togliere: «{m.group(0)}»" for m in VIETATE.finditer(tutto)]
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


def _caselle(g: dict) -> list[list[str]]:
    r = g["ruolo"]
    if r == "QB":
        return [[g["completiTentati"], "completi"], [n_it(g["yardLanciate"]), "yard lanciate"], [str(g["tdLancio"]), "TD"],
                [str(g["intercettiSubiti"]), "intercetti"]]
    if r == "Corse":
        return [[str(g["corse"]), "corse"], [n_it(g["yardCorsa"]), "yard"], [str(g["tdCorsa"]), "TD"]]
    if r == "Ricezioni":
        return [[str(g["ricezioni"]), "ricezioni"], [n_it(g["yardRicevute"]), "yard"], [str(g["tdRicezione"]), "TD"]]
    out = [[str(g["placcaggi"]), "placcaggi"]]
    if g["sack"]:
        out.append([n_it(float(g["sack"])) if g["sack"] % 1 else str(int(g["sack"])), "sack"])
    if g["intercetti"]:
        out.append([str(g["intercetti"]), "intercetti"])
    if g["passaggiDeviati"]:
        out.append([str(g["passaggiDeviati"]), "deviati"])
    return out


def riquadro_cronaca(f: dict) -> dict:
    """Numeri della partita: squadre a confronto e i protagonisti, ruolo per ruolo."""
    p = f["partitaGiocata"]
    squadre = []
    for chiave, sigla in (("ospiti", f["ospite"]), ("padroniDiCasa", f["casa"])):
        gioc, visti = [], collections.Counter()
        for g in p["protagonisti"][chiave]:
            visti[g["ruolo"]] += 1
            ruolo = {"Corse": "Corse", "Ricezioni": "Ricezioni", "Difesa": "Difesa"}.get(g["ruolo"], g["ruolo"])
            if g["ruolo"] == "Ricezioni" and visti["Ricezioni"] == 2:
                ruolo = "Ricezioni (2°)"
            gioc.append({"nome": g["nome"], "ruolo": ruolo, "dati": _caselle(g), "stato": "", "nota": ""})
        squadre.append({"sigla": sigla, "nome": f[chiave]["soprannome"], "bilancio": p["bilancioDopo"][chiave], "giocatori": gioc})
    n = p["numeri"]
    if f["lega"] == "college":
        v = lambda d, k: "—" if d.get(k) is None else n_it(d[k])
        righe = [[et, v(n["ospiti"], k), v(n["padroniDiCasa"], k)] for et, k in
                 (("Yard totali", "yardTotali"), ("Azioni", "azioni"), ("Palle perse", "palle perse"), ("Penalità", "penalita"))]
        linea = " · ".join(x[0].upper() + x[1:] for x in p["contoLaLinea"].values())
        return {"titolo": "I numeri della partita", "sottotitolo": "ESPN", "squadre": squadre, "righeSquadra": righe,
                "linea": linea}
    righe = [["Yard totali", n_it(n["ospiti"]["yardTotali"]), n_it(n["padroniDiCasa"]["yardTotali"])],
             ["Yard su lancio", n_it(n["ospiti"]["yardLancio"]), n_it(n["padroniDiCasa"]["yardLancio"])],
             ["Yard di corsa", n_it(n["ospiti"]["yardCorsa"]), n_it(n["padroniDiCasa"]["yardCorsa"])],
             ["Primi down", str(n["ospiti"]["primiDown"]), str(n["padroniDiCasa"]["primiDown"])],
             ["Terzi down", n["ospiti"]["terziDown"], n["padroniDiCasa"]["terziDown"]],
             ["Palle perse", str(n["ospiti"]["palle perse"]), str(n["padroniDiCasa"]["palle perse"])],
             ["Possesso", n["ospiti"]["possesso"], n["padroniDiCasa"]["possesso"]]]
    quarti = [[q["quarto"], str(q["ospite"]), str(q["casa"])] for q in p["parziali"]]
    linea = " · ".join(v[0].upper() + v[1:] for v in p["contoLaLinea"].values())
    return {"titolo": "I numeri della partita", "sottotitolo": "nflverse", "squadre": squadre, "righeSquadra": righe,
            "quarti": quarti, "linea": linea}


def _slug_stadio(testo: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", testo).strip("_")


def foto_stadio(lega: str, stadio: str, casa: str) -> tuple:
    """Foto dello stadio (Wikimedia Commons, crediti in docs/articoli/stadi/crediti.json).
    NFL: per nome dello stadio, così vale anche in campo neutro (Estadio Banorte) e per le squadre che lo
    condividono; college: stadio + squadra di casa, perché nomi come «Memorial Stadium» si ripetono.
    Senza foto: stringhe vuote (la copertina usa i colori delle squadre)."""
    nome = _slug_stadio(stadio or "")
    if lega == "college":
        nome += "__" + _slug_stadio(casa or "")
    file = USCITA / "stadi" / f"{nome}.jpg"
    if not nome or not file.exists():
        print(f"nessuna foto per lo stadio «{stadio}» ({casa}): copertina con i colori delle squadre")
        return "", ""
    crediti = json.loads((USCITA / "stadi" / "crediti.json").read_text())
    return f"articoli/stadi/{file.name}", crediti.get(file.name, "")


def aggiorna_foto() -> None:
    """Rimette foto e crediti negli articoli già pubblicati (dopo aver aggiunto foto nuove)."""
    for file in sorted(USCITA.glob("*_*.json")):
        if file.name in ("indice.json",):
            continue
        art = json.loads(file.read_text())
        if "stadio" not in art:
            continue
        foto, credito = foto_stadio(art["lega"], art["stadio"], art["casa"])
        if (foto, credito) != (art.get("foto", ""), art.get("fotoCrediti", "")):
            art["foto"], art["fotoCrediti"] = foto, credito
            file.write_text(json.dumps(art, ensure_ascii=False, indent=1))
            print(f"{file.name}: foto {foto or 'nessuna'}")


WIKI_UA = {"User-Agent": "PureStats/1.0 (https://purestats.it/; statistiche sportive)"}


def _wiki(url: str, parametri: dict) -> dict:
    richiesta = urllib.request.Request(url + "?" + urllib.parse.urlencode({**parametri, "format": "json"}), headers=WIKI_UA)
    with urllib.request.urlopen(richiesta, timeout=60) as r:
        return json.loads(r.read())


def _foto_commons(lega: str, stadio: str, casa: str) -> tuple[dict, dict] | None:
    """Foto principale della voce Wikipedia dello stadio, solo se libera: (imageinfo di Commons, credito completo).
    Credito = autore, licenza, collegamento alla licenza, nome del file e pagina del file su Commons (CC BY/BY-SA
    chiedono autore, licenza e collegamento)."""
    cerca = stadio if lega == "nfl" else f"{stadio} {casa} football stadium"
    risultati = _wiki("https://en.wikipedia.org/w/api.php", {"action": "query", "list": "search", "srsearch": cerca, "srlimit": 1})
    voce = risultati["query"]["search"][0]["title"]
    pagina = list(_wiki("https://en.wikipedia.org/w/api.php", {"action": "query", "titles": voce, "prop": "pageimages",
                                                                 "piprop": "name", "redirects": 1})["query"]["pages"].values())[0]
    immagine = pagina.get("pageimage")
    if not immagine or not immagine.lower().endswith((".jpg", ".jpeg")):
        print(f"{stadio} ({casa}): la voce «{voce}» non ha una foto principale in jpg, resta la copertina a colori")
        return None
    info = list(_wiki("https://commons.wikimedia.org/w/api.php", {"action": "query", "titles": "File:" + immagine,
                      "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1400})["query"]["pages"].values())[0]
    if "imageinfo" not in info:
        print(f"{stadio} ({casa}): «{immagine}» non è su Commons (forse non libera), saltata")
        return None
    ii = info["imageinfo"][0]
    meta = ii["extmetadata"]
    licenza = meta.get("LicenseShortName", {}).get("value", "")
    if not re.search(r"CC|Public domain|PD", licenza, re.I):
        print(f"{stadio} ({casa}): licenza «{licenza}» non libera, saltata")
        return None
    autore = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", ""))).strip() or "autore non indicato"
    url_licenza = meta.get("LicenseUrl", {}).get("value", "")
    credito = {"autore": autore[:80], "licenza": licenza,
               "licenzaUrl": url_licenza if url_licenza.startswith("http") else "",
               "file": immagine, "pagina": ii.get("descriptionurl") or
               "https://commons.wikimedia.org/wiki/File:" + urllib.parse.quote(immagine.replace(" ", "_"))}
    return ii, credito


def completa_crediti(crediti: dict | None = None) -> None:
    """Crediti scritti prima del 22/11/2026 (solo «autore · licenza»): ritrova sulla stessa voce Wikipedia il file
    e aggiunge pagina del file e collegamento alla licenza. Se la voce ora mostra un'altra foto (autore diverso)
    il credito vecchio resta com'è e lo si segnala: la foto salvata va controllata a mano."""
    crediti_file = USCITA / "stadi" / "crediti.json"
    crediti = crediti if crediti is not None else json.loads(crediti_file.read_text())
    luoghi = {}
    for file in USCITA.glob("*_*.json"):
        art = json.loads(file.read_text())
        if art.get("stadio"):
            nome = _slug_stadio(art["stadio"]) + ("__" + _slug_stadio(art["casa"]) if art["lega"] == "college" else "")
            luoghi[f"{nome}.jpg"] = (art["lega"], art["stadio"], art["casa"])
    cambiati = 0
    for nome, vecchio in list(crediti.items()):
        if isinstance(vecchio, dict):
            continue
        if nome not in luoghi:
            # foto scaricate prima degli articoli (tutti gli stadi NFL): stadio dal nome del file; la ricerca su
            # Wikipedia tollera gli spazi al posto di apostrofi e trattini; college «<Stadio>__<Casa>»
            base = nome.rsplit(".", 1)[0]
            stadio, _, casa = base.partition("__")
            luoghi[nome] = ("college" if casa else "nfl", stadio.replace("_", " "), casa.replace("_", " "))
        try:
            trovata = _foto_commons(*luoghi[nome])
        except Exception as e:                                                    # noqa: BLE001
            print(f"{nome}: credito non completato ({e!r}), resta «{vecchio}»")
            continue
        if not trovata:
            continue
        credito = trovata[1]
        autore_vecchio = vecchio.split(" · ")[0].strip()
        if autore_vecchio[:40] != credito["autore"][:40]:
            print(f"ATTENZIONE {nome}: la voce ora mostra «{credito['file']}» di {credito['autore']}, la foto salvata è di "
                  f"{autore_vecchio}: credito lasciato com'era, da controllare")
            continue
        crediti[nome] = credito
        cambiati += 1
        print(f"{nome}: credito completato ({credito['file']}, {credito['licenza']})")
    if cambiati:
        crediti_file.write_text(json.dumps(dict(sorted(crediti.items())), ensure_ascii=False, indent=1))
    rimasti = [n for n, c in crediti.items() if not isinstance(c, dict)]
    if rimasti:
        print(f"Crediti ancora incompleti: {len(rimasti)} ({', '.join(rimasti[:10])})")


def foto_mancanti() -> None:
    """Scarica da Wikimedia Commons la foto dello stadio degli articoli che non ce l'hanno (gira nel workflow
    articoli-meteo: dalla sandbox Wikimedia non si raggiunge). Immagine principale della voce Wikipedia trovata
    con la ricerca «stadio + squadra di casa»; solo licenze libere (CC, pubblico dominio), autore e licenza nei crediti."""
    crediti_file = USCITA / "stadi" / "crediti.json"
    crediti = json.loads(crediti_file.read_text())
    mancanti = {}
    for file in USCITA.glob("*_*.json"):
        art = json.loads(file.read_text())
        if "stadio" in art and not art.get("foto") and art.get("stadio"):
            mancanti[(art["lega"], art["stadio"], art["casa"])] = True
    for lega, stadio, casa in mancanti:
        nome = _slug_stadio(stadio) + ("__" + _slug_stadio(casa) if lega == "college" else "")
        try:
            trovata = _foto_commons(lega, stadio, casa)
            if not trovata:
                continue
            ii, credito = trovata
            with urllib.request.urlopen(urllib.request.Request(ii.get("thumburl") or ii["url"], headers=WIKI_UA), timeout=60) as r:
                (USCITA / "stadi" / f"{nome}.jpg").write_bytes(r.read())
            crediti[f"{nome}.jpg"] = credito
            crediti_file.write_text(json.dumps(dict(sorted(crediti.items())), ensure_ascii=False, indent=1))
            print(f"{stadio} ({casa}): foto «{credito['file']}», {credito['licenza']}")
        except Exception as e:
            print(f"{stadio} ({casa}): foto non scaricata ({e!r}), resta la copertina a colori")
    completa_crediti(crediti)
    aggiorna_foto()


def pubblica(gid: str, tipo: str, file_testo: str) -> None:
    f = json.loads((FATTI / f"fatti_{gid}.json").read_text())
    # notizie della vigilia verificate sul web (infortuni, allenatori, trasferimenti), ognuna con la sua fonte:
    # data/articoli/notizie_<id>.json = [{"fatto": "...", "fonte": "https://..."}]; entrano nel controllo
    notizie = FATTI / f"notizie_{gid}.json"
    if notizie.exists():
        voci = json.loads(notizie.read_text())
        senza = [v["fatto"] for v in voci if not str(v.get("fonte", "")).startswith("http")]
        if senza:
            print("NON pubblicato: notizie senza fonte:\n  " + "\n  ".join(senza))
            sys.exit(1)
        f = dict(f, notizieVerificate=voci)
    testo = json.loads(Path(file_testo).read_text())
    problemi = controlla(testo, f)
    if problemi:
        print("NON pubblicato, da correggere:\n  " + "\n  ".join(problemi))
        sys.exit(1)
    USCITA.mkdir(parents=True, exist_ok=True)
    foto, credito = foto_stadio(f["lega"], f["stadio"], f["casa"])
    aid = f"{gid}_{tipo}"
    art = {"id": aid, "lega": f["lega"], "tipo": tipo, "stagione": f["stagione"], "settimana": f["settimana"], "ospite": f["ospite"], "casa": f["casa"],
           "dataIt": f["dataIt"], "oraIt": f["oraIt"], "inizioUtc": f["inizioUtc"], "stadio": f["stadio"],
           "campoNeutro": f["campoNeutro"], "coperto": f["coperto"],
           "bilanci": {"ospite": f["ospiti"]["bilancio"], "casa": f["padroniDiCasa"]["bilancio"]},
           "colori": f["colori"], "titolo": testo["titolo"], "paragrafi": testo["paragrafi"],
           "riquadro": riquadro_cronaca(f) if tipo == "cronaca" else riquadro_college(f) if f["lega"] == "college" else riquadro(f),
           "foto": foto, "fotoCrediti": credito, "pubblicato": dt.datetime.now(ROMA).isoformat(timespec="minutes")}
    if tipo == "cronaca":
        p = f["partitaGiocata"]
        art["punti"] = {"ospite": p["puntiOspite"], "casa": p["puntiCasa"]}
        art["bilanci"] = {"ospite": p["bilancioDopo"]["ospiti"], "casa": p["bilancioDopo"]["padroniDiCasa"]}
        art["video"] = p.get("video") or ""
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
        voci.append({k: a.get(k) for k in ("id", "lega", "tipo", "stagione", "settimana", "ospite", "casa", "dataIt", "oraIt", "titolo", "pubblicato")})
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
        if a.get("lega") == "college":
            lat, lon, _ = (json.loads((RADICE / "data" / "college_stadi.json").read_text())["squadre"].get(a["casa"])
                           or (None, None, None))
        else:
            lat, lon, _ = STADI_NFL.get(a["casa"], (None, None, None))
        if lat is None:
            continue
        m = previsione(lat, lon, inizio, "College" if a.get("lega") == "college" else "NFL")
        if not m:
            print(f"Meteo non disponibile per {a['id']}: la scheda resta com'era")
            continue
        scheda = {"tempC": m.get("tempC"), "pioggia": m.get("pioggia"), "ventoKmh": m.get("ventoKmh"), "raffKmh": m.get("raffKmh"),
                  "fonte": m.get("fonte"), "aggiornato": ora.astimezone(ROMA).isoformat(timespec="minutes")}
        scheda["impatto"] = "nessuno (al coperto)" if a.get("coperto") else impatto(scheda)
        a["meteo"] = scheda
        p.write_text(json.dumps(a, ensure_ascii=False, indent=1))
        print(f"Meteo aggiornato per {a['id']}: {scheda}")


METEO_PARTITE = RADICE / "docs" / "meteo" / "partite.json"


def meteo_partite() -> None:
    """Meteo pubblico di TUTTE le partite NFL e college dei prossimi 7 giorni (21/11/2026, scelta di Valerio), con la
    stessa regola d'impatto generica degli articoli (non le misure di Charlie). NWS + Open-Meteo, gratis.
    Per non chiamare le fonti più del necessario una previsione si rifà ogni 3 ore, ogni ora nelle 12 ore prima del via.
    Niente meteo in campo neutro (lo stadio non è quello di casa); stadi coperti segnati come tali."""
    sys.path.insert(0, str(RADICE / "scripts"))
    from contesto import STADI_NFL, meteo as previsione
    ora = dt.datetime.now(dt.timezone.utc)
    vecchio = json.loads(METEO_PARTITE.read_text()) if METEO_PARTITE.exists() else {}
    out = {"aggiornato": ora.astimezone(ROMA).isoformat(timespec="minutes"), "nfl": {}, "college": {},
           "fonti": "NWS (National Weather Service) e Open-Meteo"}
    # NFL: partite da giocare dall'archivio del sito; campo neutro = stadio diverso da quello abituale della squadra
    nfl = list(csv.DictReader(io.StringIO((RADICE / "data" / "nfl.csv").read_text())))
    abituale = {}
    for r in nfl:
        if r["Stagione"] in (str(ora.year), str(ora.year - 1)):
            abituale.setdefault(r["Casa"], collections.Counter())[r["Stadio"]] += 1
    partite = []
    for r in nfl:
        if r["PuntiCasa"] or not r["Data"]:
            continue
        inizio = dt.datetime.fromisoformat(f"{r['Data']}T{r['Ora'] or '13:00'}").replace(tzinfo=NY).astimezone(dt.timezone.utc)
        solito = abituale.get(r["Casa"], collections.Counter()).most_common(1)
        neutro = bool(solito) and r["Stadio"] != solito[0][0]
        lat, lon, coperto = STADI_NFL.get(r["Casa"], (None, None, None))
        coperto = coperto or r.get("Copertura") in ("dome", "closed")
        partite.append(("nfl", f"{r['Stagione']}|{r['Settimana']}|{r['Casa']}|{r['Ospite']}", inizio, lat, lon, coperto, neutro))
    # College: calendario ESPN del sito (data_college.json), campo neutro da data/college.csv
    stadi = json.loads((RADICE / "data" / "college_stadi.json").read_text())["squadre"]
    neutri = {(r["Stagione"], r["Settimana"], r["Casa"], r["Ospite"]) for r in
              csv.DictReader(io.StringIO((RADICE / "data" / "college.csv").read_text())) if r.get("CampoNeutro") in ("1", "True", "true")}
    for p in json.loads((RADICE / "docs" / "data_college.json").read_text()).get("ultimePartite", []):
        if p.get("pc") is not None or not p.get("inizio"):
            continue
        inizio = dt.datetime.fromisoformat(p["inizio"].replace("Z", "+00:00"))
        if inizio.tzinfo is None:
            inizio = inizio.replace(tzinfo=dt.timezone.utc)      # l'inizio ESPN è in UTC
        lat, lon, coperto = stadi.get(p["casa"]) or (None, None, None)
        neutro = (p["stagione"], p["settimana"], p["casa"], p["ospite"]) in neutri
        partite.append(("college", f"{p['stagione']}|{p['settimana']}|{p['casa']}|{p['ospite']}", inizio, lat, lon, coperto, neutro))
    nuove = rifatte = 0
    for lega, chiave, inizio, lat, lon, coperto, neutro in partite:
        if inizio < ora - dt.timedelta(hours=4) or inizio - ora > dt.timedelta(days=7):
            continue
        prima = (vecchio.get(lega) or {}).get(chiave)
        if neutro:
            out[lega][chiave] = {"campoNeutro": True}
            continue
        if lat is None:
            continue                                    # stadio sconosciuto (squadre FCS): niente meteo
        if prima and prima.get("tempC") is not None:
            eta = ora - dt.datetime.fromisoformat(prima["aggiornato"])
            if eta < dt.timedelta(hours=3) and not (inizio - ora < dt.timedelta(hours=12) and eta >= dt.timedelta(minutes=50)):
                out[lega][chiave] = prima                # previsione ancora fresca: nessuna chiamata
                continue
        if inizio < ora:
            if prima:
                out[lega][chiave] = prima                # partita in corso: resta l'ultima previsione
            continue
        m = previsione(lat, lon, inizio, "College" if lega == "college" else "NFL")
        if not m or m.get("tempC") is None:
            if prima:
                out[lega][chiave] = prima
            print(f"meteo non disponibile per {lega} {chiave}: resta la previsione precedente, se c'era")
            continue
        scheda = {"tempC": m.get("tempC"), "pioggia": m.get("pioggia"), "ventoKmh": m.get("ventoKmh"),
                  "raffKmh": m.get("raffKmh"), "fonte": m.get("fonte"), "aggiornato": ora.isoformat(timespec="minutes")}
        scheda["coperto"] = bool(coperto)
        scheda["impatto"] = "coperto" if coperto else impatto(scheda)
        out[lega][chiave] = scheda
        rifatte += 1
    METEO_PARTITE.parent.mkdir(parents=True, exist_ok=True)
    METEO_PARTITE.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"meteo delle partite: {len(out['nfl'])} NFL e {len(out['college'])} college, {rifatte} previsioni rifatte")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "fatti":
        fatti(sys.argv[2])
    elif len(sys.argv) >= 5 and sys.argv[1] == "pubblica":
        pubblica(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) >= 2 and sys.argv[1] == "da_fare":
        lavori = da_fare()
        print(json.dumps(lavori, ensure_ascii=False, indent=1) if lavori else "Niente da fare oggi.")
    elif len(sys.argv) >= 4 and sys.argv[1] == "scegli":
        lega, sett = sys.argv[2], int(sys.argv[3])
        stag = int(sys.argv[4]) if len(sys.argv) >= 5 else dt.date.today().year
        for g in (scegli_nfl(stag, sett) if lega == "nfl" else scegli_college(stag, sett)):
            print(json.dumps(g, ensure_ascii=False))
    elif len(sys.argv) >= 6 and sys.argv[1] == "fatti_college":
        fatti_college(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5])
    elif len(sys.argv) >= 2 and sys.argv[1] == "meteo":
        meteo()
    elif len(sys.argv) >= 2 and sys.argv[1] == "meteo_partite":
        meteo_partite()
    elif len(sys.argv) >= 2 and sys.argv[1] == "foto":
        aggiorna_foto()
    elif len(sys.argv) >= 2 and sys.argv[1] == "foto_mancanti":
        foto_mancanti()
    else:
        print(__doc__)
