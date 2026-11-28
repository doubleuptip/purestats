"""Duelli «Uno contro uno» della pagina Matchup (28/11/2026, scelta di Valerio): materiale da leggere a vista,
NON entra nelle probabilità di Charlie (Protocollo 13: contro il mercato non aggiunge informazione).

Si riempie mentre fetch_duelli legge il play-by-play (nessun download in più) e per ogni partita prepara:
  reparti   le quattro aree di reparti.py (valori e posizioni) più terzi down e zona rossa (NFL), nei due versi
  squilibri i confronti con la distanza di classifica più grande (attacco forte contro difesa debole o viceversa)
  stile     ritmo (azioni a partita), quota di passaggi nelle situazioni neutre, lanci lunghi (NFL)
  mappe     NFL: per i 3 ricevitori più cercati di ogni squadra, quota dei loro bersagli in 9 zone del campo
            (profondità × lato) contro le yard per bersaglio concesse dalla difesa avversaria nelle stesse zone;
            per l'RB principale, corse per direzione contro le yard per corsa concesse per direzione
I sostituti degli assenti (NFL) si calcolano con gli snap (sostituti_nfl), dopo le assenze.
Valori e posizioni: solo partite giocate PRIMA della settimana della partita; posizione 1 = la migliore.
Solo libreria standard.
"""
from __future__ import annotations

import csv
import io
import unicodedata
import urllib.request
from collections import defaultdict

PROF = (("lungo", 20, 999), ("medio", 10, 20), ("corto", -99, 10))
LATI = ("left", "middle", "right")
DIREZIONI = ("left", "middle", "right")
MIN_ZONA = 8            # bersagli o corse minime della difesa in una zona per darle una posizione
RICEVITORI = 3          # ricevitori con la mappa per squadra
SNAP = "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{s}.csv"
UA = {"User-Agent": "purestats (statistiche personali)"}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _vero(x):
    return str(x).strip().upper() in ("TRUE", "1", "1.0")


def _zona(air, lato):
    if air is None or lato not in LATI:
        return None
    for nome, lo, hi in PROF:
        if lo <= air < hi:
            return f"{nome}_{lato}"
    return None


class Raccolta:
    """Passa le righe del play-by-play (nflverse o cfbfastR) e annota per settimana e squadra."""

    def __init__(self, lega: str):
        self.lega = lega
        # (settimana, attacco, difesa, partita) -> contatori
        self.sq = defaultdict(lambda: defaultdict(float))
        self.rz = {}                      # (partita, drive) -> [settimana, attacco, difesa, td]
        self.ric = defaultdict(lambda: defaultdict(float))     # (settimana, squadra, giocatore) -> {zona: n, "y_"+zona}
        self.dz = defaultdict(lambda: defaultdict(float))      # (settimana, difesa) -> {zona: n, "y_"+zona}
        self.nomi = {}

    def passa(self, righe):
        for r in righe:
            try:
                if self.lega == "nfl":
                    self._nfl(r)
                else:
                    self._college(r)
            except (KeyError, ValueError, TypeError):
                pass
            yield r

    # -------------------------------------------------------------- NFL (nflverse)
    def _nfl(self, r):
        if r.get("season_type") != "REG" or r.get("play_type") not in ("pass", "run"):
            return
        if "No Play" in (r.get("desc") or "") or r.get("two_point_attempt") == "1":
            return
        w, o, d, g = int(float(r["week"])), r["posteam"], r["defteam"], r["game_id"]
        c = self.sq[(w, o, d, g)]
        c["az"] += 1
        y = _f(r.get("yards_gained")) or 0.0
        giu = _f(r.get("down"))
        if giu == 3:
            c["t3"] += 1
            c["t3ok"] += r.get("first_down") == "1" or r.get("touchdown") == "1"
        wp, hs = _f(r.get("wp")), _f(r.get("half_seconds_remaining"))
        if giu in (1, 2) and wp is not None and 0.2 <= wp <= 0.8 and (hs or 0) > 120:
            c["neu"] += 1
            c["neuP"] += r.get("qb_dropback") == "1"
        yl = _f(r.get("yardline_100"))
        dr = r.get("fixed_drive") or r.get("drive")
        if yl is not None and yl <= 20 and dr not in ("", "NA", None):
            k = (g, dr)
            if k not in self.rz:
                self.rz[k] = [w, o, d, 0]
            if r.get("touchdown") == "1" and r.get("td_team") == o:
                self.rz[k][3] = 1
        if r["play_type"] == "pass":
            air = _f(r.get("air_yards"))
            if air is not None and r.get("pass_attempt") == "1" and r.get("sack") != "1":
                c["lanci"] += 1
                c["lunghi"] += air >= 20
            z = _zona(air, r.get("pass_location"))
            rid = r.get("receiver_player_id")
            if z and rid not in ("", "NA", None):
                rr = self.ric[(w, o, rid)]
                rr[z] += 1
                rr["y_" + z] += y
                dd = self.dz[(w, d)]
                dd[z] += 1
                dd["y_" + z] += y
                self.nomi[rid] = r.get("receiver_player_name") or self.nomi.get(rid, "")
        elif r.get("rusher_player_id") not in ("", "NA", None) and r.get("qb_scramble") != "1":
            lo = r.get("run_location")
            if lo in DIREZIONI:
                rid = r["rusher_player_id"]
                rr = self.ric[(w, o, rid)]
                rr["c_" + lo] += 1
                rr["cy_" + lo] += y
                dd = self.dz[(w, d)]
                dd["c_" + lo] += 1
                dd["cy_" + lo] += y
                self.nomi[rid] = r.get("rusher_player_name") or self.nomi.get(rid, "")

    # -------------------------------------------------------------- college (cfbfastR): niente zone né zona rossa
    def _college(self, r):
        if r.get("season_type") not in ("regular", "postseason"):
            return
        if r.get("home_team_division") != "fbs" or r.get("away_team_division") != "fbs":
            return
        rush, pas = _vero(r.get("rush")), _vero(r.get("pass"))
        if not (rush or pas) or _vero(r.get("penalty_no_play")):
            return
        w = _f(r.get("week"))
        if w is None:
            return
        o, d, g = r.get("pos_team"), r.get("def_pos_team"), r.get("game_id")
        c = self.sq[(int(w), o, d, g)]
        c["az"] += 1
        giu, dist, y = _f(r.get("down")), _f(r.get("distance")), _f(r.get("yards_gained")) or 0.0
        if giu == 3 and dist is not None:
            c["t3"] += 1
            c["t3ok"] += y >= dist
        sd = _f(r.get("pos_score_diff_start"))
        if giu in (1, 2) and sd is not None and abs(sd) <= 10:
            c["neu"] += 1
            c["neuP"] += pas and not rush

    # -------------------------------------------------------------- calcolo per una settimana
    def stato(self, settimana: int) -> dict:
        """Terzi down, zona rossa e stile per squadra, con le partite prima della settimana; valori corretti una
        volta per gli avversari (come reparti.stato) e posizioni (1 = la migliore)."""
        att, dif, avv_att, avv_dif = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float)), \
            defaultdict(list), defaultdict(list)
        partite = defaultdict(set)
        for (w, o, d, g), c in self.sq.items():
            if w >= settimana:
                continue
            for k, v in c.items():
                att[o][k] += v
                dif[d][k] += v
            avv_att[o].append(d)          # una chiave = una partita in un verso
            avv_dif[d].append(o)
            partite[o].add(g)
        for k, (w, o, d, td) in self.rz.items():
            if w >= settimana:
                continue
            att[o]["rz"] += 1
            att[o]["rztd"] += td
            dif[d]["rz"] += 1
            dif[d]["rztd"] += td
        squadre = [t for t in att if len(partite[t]) >= 4 and t in dif]
        if len(squadre) < 2:
            return {}
        out = {t: {"att": {}, "dif": {}, "rango_att": {}, "rango_dif": {}, "stile": {}, "rango_stile": {},
                   "partite": len(partite[t])} for t in squadre}
        quote = {"terzi": ("t3ok", "t3"), "rossa": ("rztd", "rz")}
        for area, (num, den) in quote.items():
            vo = {t: att[t][num] / att[t][den] for t in squadre if att[t][den] >= 5}
            vd = {t: dif[t][num] / dif[t][den] for t in squadre if dif[t][den] >= 5}
            if len(vo) < 2 or len(vd) < 2:
                continue
            lo, ld = sum(vo.values()) / len(vo), sum(vd.values()) / len(vd)
            for t in squadre:
                dd = [vd[x] - ld for x in avv_att[t] if x in vd]
                oo = [vo[x] - lo for x in avv_dif[t] if x in vo]
                if t in vo:
                    out[t]["att"][area] = vo[t] - (sum(dd) / len(dd) if dd else 0.0)
                if t in vd:
                    out[t]["dif"][area] = vd[t] - (sum(oo) / len(oo) if oo else 0.0)
            ra = _rango({t: -out[t]["att"][area] for t in out if area in out[t]["att"]})
            rd = _rango({t: out[t]["dif"][area] for t in out if area in out[t]["dif"]})   # concede meno = migliore
            for t in out:
                if t in ra:
                    out[t]["rango_att"][area] = ra[t]
                if t in rd:
                    out[t]["rango_dif"][area] = rd[t]
        # stile: solo descrizione, nessuna «migliore»: posizione 1 = il valore più alto
        for nome, fn in (("ritmo", lambda a, t: a["az"] / len(partite[t])),
                         ("neutrePass", lambda a, t: a["neuP"] / a["neu"] if a["neu"] >= 30 else None),
                         ("lunghi", lambda a, t: a["lunghi"] / a["lanci"] if a["lanci"] >= 50 else None)):
            v = {t: fn(att[t], t) for t in squadre}
            v = {t: x for t, x in v.items() if x is not None}
            if len(v) < 2:
                continue
            rk = _rango({t: -x for t, x in v.items()})
            for t, x in v.items():
                out[t]["stile"][nome] = x
                out[t]["rango_stile"][nome] = rk[t]
        return out

    def zone(self, settimana: int) -> tuple[dict, dict, dict]:
        """(ricevitori {(squadra, id): {zona: n, y_zona}}, difese {difesa: {...}}, lega {zona: (n, y)}) prima di w.
        La squadra di un giocatore è quella della sua partita più recente (i ceduti passano alla nuova)."""
        ric, ult = defaultdict(lambda: defaultdict(float)), {}
        for (w, o, rid), v in self.ric.items():
            if w >= settimana:
                continue
            for k, x in v.items():
                ric[rid][k] += x
            if w >= ult.get(rid, (0, ""))[0]:
                ult[rid] = (w, o)
        dz = defaultdict(lambda: defaultdict(float))
        lega = defaultdict(float)
        for (w, d), v in self.dz.items():
            if w >= settimana:
                continue
            for k, x in v.items():
                dz[d][k] += x
                lega[k] += x
        per_sq = {(ult[rid][1], rid): v for rid, v in ric.items() if rid in ult}
        return per_sq, dz, lega


def _rango(vals: dict) -> dict:
    """Posizione 1 = valore più basso; a pari merito la posizione media."""
    out = {}
    for t, v in vals.items():
        meglio = sum(1 for x in vals.values() if x < v - 1e-12)
        pari = sum(1 for x in vals.values() if abs(x - v) <= 1e-12)
        out[t] = round(meglio + (pari + 1) / 2)
    return out


ZONE = [f"{p}_{l}" for p, _a, _b in PROF for l in LATI]


def _mappa_ricevitore(v: dict, difesa: str, dz: dict, lega: dict, rango_zona: dict) -> dict | None:
    tot = sum(v.get(z, 0) for z in ZONE)
    if tot < 15:
        return None
    celle = []
    for z in ZONE:
        n_d = dz.get(difesa, {}).get(z, 0)
        ypt = dz[difesa]["y_" + z] / n_d if n_d >= MIN_ZONA else None
        lt = lega.get(z, 0)
        celle.append({"z": z, "q": round(v.get(z, 0) / tot, 3), "n": int(v.get(z, 0)),
                      "ypt": round(v["y_" + z] / v[z], 1) if v.get(z) else None,
                      "dYpt": round(ypt, 1) if ypt is not None else None, "dN": int(n_d),
                      "lYpt": round(lega["y_" + z] / lt, 1) if lt else None,
                      "dRango": rango_zona.get(z, {}).get(difesa)})
    return {"bersagli": int(tot), "celle": celle}


def _mappa_corse(v: dict, difesa: str, dz: dict, lega: dict, rango_dir: dict) -> dict | None:
    tot = sum(v.get("c_" + x, 0) for x in DIREZIONI)
    if tot < 25:
        return None
    celle = []
    for x in DIREZIONI:
        n_d = dz.get(difesa, {}).get("c_" + x, 0)
        lt = lega.get("c_" + x, 0)
        celle.append({"z": x, "q": round(v.get("c_" + x, 0) / tot, 3), "n": int(v.get("c_" + x, 0)),
                      "ypc": round(v["cy_" + x] / v["c_" + x], 1) if v.get("c_" + x) else None,
                      "dYpc": round(dz[difesa]["cy_" + x] / n_d, 1) if n_d >= MIN_ZONA else None, "dN": int(n_d),
                      "lYpc": round(lega["cy_" + x] / lt, 1) if lt else None,
                      "dRango": rango_dir.get(x, {}).get(difesa)})
    return {"corse": int(tot), "celle": celle}


def partita(rac: Raccolta, st_rep: dict, st_dz: dict, zone: tuple | None, casa: str, ospite: str,
            nomi: dict, aree: tuple) -> dict | None:
    """Il blocco «duelli» di una partita. st_rep = reparti.stato, st_dz = Raccolta.stato della stessa settimana."""
    if casa not in st_rep or ospite not in st_rep:
        return None
    n = st_rep[casa]["n"]
    reparti, squilibri = [], []
    for att, dif in ((ospite, casa), (casa, ospite)):
        for area in aree + ("terzi", "rossa"):
            if area in aree:
                a, d = st_rep.get(att), st_rep.get(dif)
            else:
                a, d = st_dz.get(att), st_dz.get(dif)
            if not a or not d or area not in a["rango_att"] or area not in d["rango_dif"]:
                continue
            nn = len([1 for x in (st_rep if area in aree else st_dz).values() if area in x["rango_dif"]]) or n
            ra, rd = a["rango_att"][area], d["rango_dif"][area]
            reparti.append({"area": area, "att": att, "dif": dif, "ra": ra, "rd": rd, "n": nn,
                            "va": round(a["att"][area], 4), "vd": round(d["dif"][area], 4)})
            # distanza di classifica: attacco tra i primi contro difesa tra gli ultimi (o il contrario)
            dist = rd - ra
            if abs(dist) >= round(nn * 0.4):
                squilibri.append({"area": area, "att": att, "dif": dif, "ra": ra, "rd": rd, "n": nn,
                                  "verso": "attacco" if dist > 0 else "difesa", "distanza": abs(dist)})
    squilibri.sort(key=lambda s: -s["distanza"] / s["n"])
    stile = {}
    for sq in (ospite, casa):
        s = st_dz.get(sq)
        if s and s["stile"]:
            stile[sq] = {k: {"v": round(v, 3), "r": s["rango_stile"][k], "n": len(st_dz)} for k, v in s["stile"].items()}
    out = {"reparti": reparti, "squilibri": squilibri[:3], "stile": stile}
    if zone:
        ric, dz, lega = zone
        rango_zona = {}
        for z in ZONE:
            vals = {d: v["y_" + z] / v[z] for d, v in dz.items() if v.get(z, 0) >= MIN_ZONA}
            rango_zona[z] = _rango(vals)                 # 1 = concede meno yard per bersaglio
        rango_dir = {}
        for x in DIREZIONI:
            vals = {d: v["cy_" + x] / v["c_" + x] for d, v in dz.items() if v.get("c_" + x, 0) >= MIN_ZONA}
            rango_dir[x] = _rango(vals)
        mappe = []
        for sq, avv in ((ospite, casa), (casa, ospite)):
            cand = sorted(((sum(v.get(z, 0) for z in ZONE), rid, v) for (s, rid), v in ric.items() if s == sq),
                          key=lambda t: -t[0])
            for _, rid, v in cand[:RICEVITORI]:
                m = _mappa_ricevitore(v, avv, dz, lega, rango_zona)
                if m:
                    mappe.append({"tipo": "ricevitore", "squadra": sq, "difesa": avv, "id": rid,
                                  "nome": nomi.get(rid) or rac.nomi.get(rid, rid), "nDif": len(rango_zona[ZONE[0]]), **m})
            corse = sorted(((sum(v.get("c_" + x, 0) for x in DIREZIONI), rid, v) for (s, rid), v in ric.items()
                            if s == sq), key=lambda t: -t[0])
            for tot, rid, v in corse[:1]:
                m = _mappa_corse(v, avv, dz, lega, rango_dir)
                if m:
                    mappe.append({"tipo": "corse", "squadra": sq, "difesa": avv, "id": rid,
                                  "nome": nomi.get(rid) or rac.nomi.get(rid, rid), "nDif": len(rango_dir["middle"]), **m})
        out["mappe"] = mappe
    return out


# ------------------------------------------------------------------ sostituti (NFL, snap nflverse/PFR)
def _norm(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode().lower()
    for x in (" jr.", " sr.", " iii", " ii", " iv", ".", "'", "-"):
        s = s.replace(x, "" if x in (".", "'") else " ")
    return " ".join(s.split())


GRUPPO = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE"}
TITOLARI = {"QB": 1, "RB": 1, "WR": 3, "TE": 1}


def snap_nfl(stagione: int) -> list:
    req = urllib.request.Request(SNAP.format(s=stagione), headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        testo = r.read().decode("utf-8")
    return [x for x in csv.DictReader(io.StringIO(testo)) if x.get("game_type") == "REG"]


def sostituti_nfl(schede: list, snap: list) -> int:
    """Per ogni assente (non «gioca») di ruolo QB/RB/WR/TE: chi ne prende gli snap. Prima le partite già giocate
    senza di lui (chi è cresciuto di più rispetto alle partite con lui), altrimenti il compagno di reparto con più
    snap in stagione dopo i titolari. Scrive sc["sostituti"] = [{assente, ruolo, squadra, sostituto, ...}]."""
    per = defaultdict(lambda: defaultdict(dict))      # (squadra) -> nome normalizzato -> {settimana: (pct, nome, ruolo)}
    for x in snap:
        try:
            w, pct = int(x["week"]), float(x.get("offense_pct") or 0)
        except ValueError:
            continue
        pct = pct * 100 if pct <= 1.0 else pct          # nflverse la scrive come frazione
        if x.get("position") not in GRUPPO:
            continue
        per[x["team"]][_norm(x["player"])][w] = (pct, x["player"], GRUPPO[x["position"]])
    n = 0
    for sc in schede:
        out = []
        for sq, chiave in ((sc["casa"], "assenzeCasa"), (sc["ospite"], "assenzeOspite")):
            ass = (sc.get(chiave) or {}).get("giocatori") or []
            gioc = per.get(sq) or per.get({"LA": "LAR", "LAR": "LA"}.get(sq, ""), {})
            if not gioc:
                continue
            settimane = sorted({w for v in gioc.values() for w in v})
            for a in ass:
                if str(a.get("stato", "")).upper() == "ATTIVO":
                    continue
                k = _norm(a.get("nome", ""))
                if k not in gioc:
                    continue
                righe = gioc[k]
                ruolo = next(iter(righe.values()))[2]
                media_a = sum(p for p, _n, _r in righe.values()) / len(righe)
                if media_a < 25:        # non era un titolare: nessun sostituto da mostrare
                    continue
                senza = [w for w in settimane if w not in righe or righe[w][0] < 5]
                con = [w for w in settimane if w in righe and righe[w][0] >= 25]
                cand = []
                for kk, v in gioc.items():
                    if kk == k or next(iter(v.values()))[2] != ruolo:
                        continue
                    nome = next(iter(v.values()))[1]
                    if senza and con:
                        ps = [v[w][0] for w in senza if w in v]
                        pc = [v.get(w, (0,))[0] for w in con]
                        if ps:
                            cand.append((sum(ps) / len(ps) - sum(pc) / len(pc), nome, sum(pc) / len(pc),
                                         sum(ps) / len(ps), len(ps), "senza"))
                    else:
                        tutte = [p for p, _n, _r in v.values()]
                        cand.append((sum(tutte) / len(settimane), nome, sum(tutte) / len(settimane), None, 0, "stagione"))
                if not cand:
                    continue
                cand.sort(key=lambda t: -t[0])
                # senza partite giocate senza di lui: restano titolari i primi (titolari − 1) compagni per snap,
                # il sostituto è il successivo (WR: il 4° ricevitore della squadra prende il posto, non il 2°)
                c = cand[0] if cand[0][5] == "senza" else (cand[TITOLARI.get(ruolo, 1) - 1] if len(cand) >= TITOLARI.get(ruolo, 1) else cand[-1])
                out.append({"assente": a.get("nome"), "ruolo": ruolo, "squadra": sq, "snapAssente": round(media_a),
                            "sostituto": c[1], "prima": round(c[2]), "dopo": round(c[3]) if c[3] is not None else None,
                            "partiteSenza": c[4], "base": c[5], "stato": a.get("statoIt") or a.get("stato") or ""})
        sc["sostituti"] = out
        n += bool(out)
    return n


# ------------------------------------------------------------------ Next Gen Stats e copertura (NFL, 28/11/2026)
NGS = "https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_{t}.csv.gz"
ADV_DEF = "https://github.com/nflverse/nflverse-data/releases/download/pfr_advstats/advstats_week_def_{s}.csv"
GIOCATORI = "https://github.com/nflverse/nflverse-data/releases/download/players/players.csv"
MIN_BERSAGLI_DB = 20     # bersagli minimi in copertura per dare una posizione a un difensore
SIGLE_NGS = {"LAR": "LA"}


def _scarica(url: str, gz: bool = False) -> str:
    import gzip as _gz
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        dati = r.read()
    return (_gz.decompress(dati) if gz else dati).decode("utf-8")


def _media_pesata(righe, campo, peso):
    s = n = 0.0
    for r in righe:
        v, p = _f(r.get(campo)), _f(r.get(peso))
        if v is not None and p:
            s += v * p
            n += p
    return (s / n, n) if n else (None, 0)


def ngs_nfl(stagione: int) -> dict:
    """{"ric": {gsis: {sep, cush, n}}, "qb": {gsis: {ttt, n, nome, squadra}}, "rb": {gsis: {ryoe, n}}} della
    stagione: riga «settimana 0» (totale ufficiale NGS) se c'è, altrimenti media delle settimane pesata sui volumi.
    Posizioni (1 = valore più alto, tranne il tempo di lancio: 1 = il più rapido) tra chi ha abbastanza azioni."""
    out = {}
    for tipo, chiave, campi, peso, minimo in (("receiving", "ric", ("avg_separation", "avg_cushion"), "targets", 20),
                                             ("passing", "qb", ("avg_time_to_throw",), "attempts", 100),
                                             ("rushing", "rb", ("rush_yards_over_expected_per_att",), "rush_attempts", 50)):
        righe = [r for r in csv.DictReader(io.StringIO(_scarica(NGS.format(t=tipo), gz=True)))
                 if r.get("season") == str(stagione) and r.get("season_type") == "REG"]
        per = defaultdict(list)
        for r in righe:
            per[r["player_gsis_id"]].append(r)
        d = {}
        for gid, rr in per.items():
            tot = [r for r in rr if r.get("week") == "0"]
            sett = [r for r in rr if r.get("week") != "0"]
            base = tot or sett
            vals = {}
            for c in campi:
                v, n = _media_pesata(base, c, peso)
                vals[c] = v
            n = sum(_f(r.get(peso)) or 0 for r in base)
            ult = max(sett, key=lambda r: int(r["week"]))["team_abbr"] if sett else base[0].get("team_abbr")
            ult = SIGLE_NGS.get(ult, ult)                 # NGS scrive LAR, il play-by-play LA
            d[gid] = {**vals, "n": n, "nome": base[0].get("player_display_name"), "squadra": ult}
        for c in campi:
            qual = {g: v[c] for g, v in d.items() if v[c] is not None and v["n"] >= minimo}
            rk = _rango({g: (x if c == "avg_time_to_throw" else -x) for g, x in qual.items()})
            for g in d:
                d[g]["r_" + c] = rk.get(g)
                d[g]["q_" + c] = len(qual)
        out[chiave] = d
    return out


def copertura_nfl(stagione: int) -> dict:
    """Pro Football Reference via nflverse (advstats_week_def; solo parte cifrata): per squadra i difensori della
    secondaria con bersagli, yard e passer rating concessi in copertura, e le pressioni della difesa a partita.
    {"db": {squadra: [...]}, "pressioni": {squadra: (a partita, posizione, n)}}"""
    pos = {}
    for r in csv.DictReader(io.StringIO(_scarica(GIOCATORI))):
        if r.get("pfr_id"):
            pos[r["pfr_id"]] = r.get("position") or r.get("position_group") or ""
    per = defaultdict(lambda: {"t": 0.0, "c": 0.0, "y": 0.0, "td": 0.0, "int": 0.0, "pr": 0.0, "squadra": "", "w": -1,
                               "nome": ""})
    press, partite = defaultdict(float), defaultdict(set)
    for r in csv.DictReader(io.StringIO(_scarica(ADV_DEF.format(s=stagione)))):
        if r.get("game_type") not in ("REG", None, ""):
            continue
        sq, w = r.get("team"), int(float(r.get("week") or 0))
        press[sq] += _f(r.get("def_pressures")) or 0
        partite[sq].add(r.get("game_id"))
        t = _f(r.get("def_targets")) or 0
        if not t:
            continue
        x = per[r.get("pfr_player_id")]
        x["t"] += t
        x["c"] += _f(r.get("def_completions_allowed")) or 0
        x["y"] += _f(r.get("def_yards_allowed")) or 0
        x["td"] += _f(r.get("def_receiving_td_allowed")) or 0
        x["int"] += _f(r.get("def_ints")) or 0
        x["pr"] += (_f(r.get("def_passer_rating_allowed")) or 0) * t
        x["nome"] = r.get("pfr_player_name") or x["nome"]
        if w >= x["w"]:
            x["squadra"], x["w"] = sq, w
    db = {pid: x for pid, x in per.items() if pos.get(pid, "") in ("CB", "S", "FS", "SS", "DB")}
    qual = {pid: x["y"] / x["t"] for pid, x in db.items() if x["t"] >= MIN_BERSAGLI_DB}
    rk = _rango(qual)                                # 1 = concede meno yard per bersaglio
    squadre = defaultdict(list)
    for pid, x in db.items():
        squadre[x["squadra"]].append({"nome": x["nome"], "ruolo": {"FS": "S", "SS": "S"}.get(pos.get(pid), pos.get(pid)),
                                      "bersagli": int(x["t"]), "ypt": round(x["y"] / x["t"], 1),
                                      "concesse": round(x["c"] / x["t"] * 100), "td": int(x["td"]), "int": int(x["int"]),
                                      "rating": round(x["pr"] / x["t"], 1), "rango": rk.get(pid), "n": len(qual)})
    for sq in squadre:
        squadre[sq] = sorted(squadre[sq], key=lambda d: -d["bersagli"])[:4]
    pp = {sq: press[sq] / len(partite[sq]) for sq in press if partite[sq]}
    rkp = _rango({sq: -v for sq, v in pp.items()})   # 1 = più pressioni a partita
    return {"db": dict(squadre), "pressioni": {sq: (round(v, 1), rkp[sq], len(pp)) for sq, v in pp.items()}}


def arricchisci_nfl(schede: list, stagione: int) -> int:
    """Aggiunge ai duelli NFL: separazione e cushion sulle mappe dei ricevitori, yard oltre l'atteso sulle corse,
    tempo di lancio del QB contro le pressioni della difesa, la secondaria avversaria. Ogni pezzo può mancare."""
    ngs, cop = {}, {}
    try:
        ngs = ngs_nfl(stagione)
    except Exception as e:     # noqa: BLE001
        print(f"NFL: Next Gen Stats non lette ({e}): duelli senza separazione e tempo di lancio.")
    try:
        cop = copertura_nfl(stagione)
    except Exception as e:     # noqa: BLE001
        print(f"NFL: copertura PFR non letta ({e}): duelli senza secondaria e pressioni.")
    n = 0
    for sc in schede:
        D = sc.get("duelli")
        if not D:
            continue
        for m in D.get("mappe") or []:
            if m["tipo"] == "ricevitore":
                x = (ngs.get("ric") or {}).get(m["id"])
                if x and x.get("avg_separation") is not None and x["n"] >= 10:
                    m["sep"] = round(x["avg_separation"], 1)
                    m["sepRango"], m["sepN"] = x.get("r_avg_separation"), x.get("q_avg_separation")
                    m["cush"] = round(x["avg_cushion"], 1) if x.get("avg_cushion") is not None else None
            else:
                x = (ngs.get("rb") or {}).get(m["id"])
                v = x and x.get("rush_yards_over_expected_per_att")
                if v is not None and x["n"] >= 25:
                    m["ryoe"] = round(v, 2)
                    m["ryoeRango"], m["ryoeN"] = x.get("r_rush_yards_over_expected_per_att"), x.get("q_rush_yards_over_expected_per_att")
        qb = {}
        for sq, avv in ((sc["ospite"], sc["casa"]), (sc["casa"], sc["ospite"])):
            cand = [(v["n"], g, v) for g, v in (ngs.get("qb") or {}).items() if v.get("squadra") == sq]
            riga = {}
            if cand:
                _, g, v = max(cand, key=lambda t: t[0])
                if v.get("avg_time_to_throw") is not None:
                    riga.update({"nome": v["nome"], "ttt": round(v["avg_time_to_throw"], 2),
                                 "tttRango": v.get("r_avg_time_to_throw"), "tttN": v.get("q_avg_time_to_throw")})
            p = (cop.get("pressioni") or {}).get(avv)
            if p:
                riga.update({"pressioniAvv": p[0], "pressioniRango": p[1], "pressioniN": p[2]})
            if riga:
                qb[sq] = riga
        if qb:
            D["qb"] = qb
        sec = {sq: (cop.get("db") or {}).get(sq) for sq in (sc["ospite"], sc["casa"])}
        sec = {k: v for k, v in sec.items() if v}
        if sec:
            D["secondaria"] = sec
        n += 1
    return n
