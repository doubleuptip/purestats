"""
NFL — squadre già fuori dai playoff (Protocollo 11, gruppo B), per l'indizio di Charlie.

Stesso metodo della misura: si parte dai risultati veri e si simulano 4.000 volte le partite di stagione regolare
ancora da giocare. Probabilità di vittoria dalla linea (normale, deviazione 13,5 punti); le partite delle settimane
successive non hanno ancora una linea: la si ricava dalle linee di chiusura già note della stagione (forza di ogni
squadra secondo il mercato più fattore campo, minimi quadrati con un piccolo freno). Playoff: per conference le 4
vincitrici di division e le 3 migliori tra le altre per vittorie; spareggi con gli scontri diretti nella division,
poi a caso (come nella misura: gli spareggi ufficiali completi non sono riprodotti).

Una squadra è «già fuori» nella partita se la probabilità di playoff è sotto il 2% e la partita non la cambia
(differenza tra vittoria e sconfitta al massimo 2 punti percentuali). Misurato dalla settimana 12: prima niente.
Solo libreria standard.
"""
from __future__ import annotations

import csv
import io
import math
import random
from collections import defaultdict

SIM = 4000
DEVIAZIONE = 13.5
SETTIMANA_MINIMA = 12
SOGLIA_P = 0.02
SOGLIA_POSTA = 0.02


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _forze(giocate: list[dict]) -> tuple[dict, float]:
    """Forza di ogni squadra secondo le linee di chiusura della stagione: linea ≈ campo + forza casa − forza ospite."""
    righe = [(g["casa"], g["ospite"], g["linea"], g["neutro"]) for g in giocate if g["linea"] is not None]
    forza = defaultdict(float)
    campo = 1.5
    for _ in range(60):
        resid = [l - (0 if n else campo) - (forza[c] - forza[o]) for c, o, l, n in righe]
        nn = [r for r, (_c, _o, _l, n) in zip(resid, righe) if not n]
        if nn:
            campo += sum(nn) / len(nn)
        somma, conta = defaultdict(float), defaultdict(int)
        for c, o, l, n in righe:
            r = l - (0 if n else campo) - (forza[c] - forza[o])
            somma[c] += r
            somma[o] -= r
            conta[c] += 1
            conta[o] += 1
        for t in conta:
            forza[t] += somma[t] / (conta[t] + 2.0)           # freno: poche partite, forza vicina alla media
        media = sum(forza.values()) / max(1, len(forza))
        for t in forza:
            forza[t] -= media
    return dict(forza), campo


def _playoff(vittorie, h2h, squadre_conf, division, posti_wc, rnd):
    per_div = defaultdict(list)
    for s in squadre_conf:
        per_div[division[s]].append(s)
    dentro = set()
    for ss in per_div.values():
        ss.sort(key=lambda s: (-vittorie[s], -sum(h2h.get((s, o), 0) for o in ss), rnd.random()))
        dentro.add(ss[0])
    resto = sorted((s for s in squadre_conf if s not in dentro), key=lambda s: (-vittorie[s], rnd.random()))
    dentro.update(resto[:posti_wc])
    return dentro


def stato(testo_partite: str, testo_squadre: str, sim: int = SIM, seme: int = 11) -> dict:
    """{"settimana": W, "partite": {"OSP@CASA": {"casa": {p, posta, fuori}, "ospite": {...}}}} per le partite ancora
    da giocare della settimana in corso (stagione regolare, dalla settimana 12). {} se non si applica."""
    conf, division = {}, {}
    for r in csv.DictReader(io.StringIO(testo_squadre)):
        a = (r.get("team_abbr") or "").strip()
        if a and r.get("team_conf") and r.get("team_division"):
            conf[a], division[a] = r["team_conf"], r["team_division"]
    tutte = []
    for r in csv.DictReader(io.StringIO(testo_partite)):
        if r.get("game_type") != "REG":
            continue
        pc, po = _num(r.get("home_score")), _num(r.get("away_score"))
        tutte.append({"stagione": int(r["season"]), "settimana": int(r["week"]), "casa": r["home_team"],
                      "ospite": r["away_team"], "linea": _num(r.get("spread_line")),
                      "neutro": r.get("location") == "Neutral",
                      "margine": None if pc is None or po is None else pc - po})
    if not tutte:
        return {}
    stagione = max(g["stagione"] for g in tutte)
    st = [g for g in tutte if g["stagione"] == stagione]
    future = [g for g in st if g["margine"] is None]
    if not future:
        return {}
    W = min(g["settimana"] for g in future)
    if W < SETTIMANA_MINIMA:
        return {}
    squadre = sorted({g["casa"] for g in st} | {g["ospite"] for g in st})
    if any(s not in conf for s in squadre):
        mancanti = [s for s in squadre if s not in conf]
        raise ValueError(f"squadre senza conference/division: {', '.join(mancanti)}")
    posti_wc = 2 if stagione <= 2019 else 3
    per_conf = defaultdict(list)
    for s in squadre:
        per_conf[conf[s]].append(s)

    forza, campo = _forze([g for g in st if g["margine"] is not None])
    base, h2h0 = defaultdict(float), defaultdict(float)
    for g in st:
        if g["margine"] is None:
            continue
        c, o, m = g["casa"], g["ospite"], g["margine"]
        if m > 0:
            base[c] += 1
            h2h0[(c, o)] += 1
        elif m < 0:
            base[o] += 1
            h2h0[(o, c)] += 1
        else:
            base[c] += .5
            base[o] += .5
    pcasa = []
    for g in future:
        linea = g["linea"]
        if linea is None:                                  # settimane future: linea stimata dal mercato
            linea = (0 if g["neutro"] else campo) + forza.get(g["casa"], 0.0) - forza.get(g["ospite"], 0.0)
        pcasa.append(_phi(linea / DEVIAZIONE))
    settimana = [i for i, g in enumerate(future) if g["settimana"] == W]
    cont = {(i, s): [0, 0, 0, 0] for i in settimana for s in (future[i]["casa"], future[i]["ospite"])}
    dentro_tot = defaultdict(int)
    rnd = random.Random(seme)
    for _ in range(sim):
        v = {t: base.get(t, 0.0) for t in squadre}
        h2h = dict(h2h0)
        vince = {}
        for i, g in enumerate(future):
            c, o = g["casa"], g["ospite"]
            w, l = (c, o) if rnd.random() < pcasa[i] else (o, c)
            v[w] += 1
            h2h[(w, l)] = h2h.get((w, l), 0) + 1
            vince[i] = w
        dentro = set()
        for ss in per_conf.values():
            dentro |= _playoff(v, h2h, ss, division, posti_wc, rnd)
        for t in dentro:
            dentro_tot[t] += 1
        for i in settimana:
            for s in (future[i]["casa"], future[i]["ospite"]):
                x = cont[(i, s)]
                if vince[i] == s:
                    x[1] += 1
                    x[0] += s in dentro
                else:
                    x[3] += 1
                    x[2] += s in dentro
    partite = {}
    for i in settimana:
        g = future[i]
        lati = {}
        for lato, s in (("casa", g["casa"]), ("ospite", g["ospite"])):
            x = cont[(i, s)]
            posta = x[0] / x[1] - x[2] / x[3] if x[1] and x[3] else None
            p = dentro_tot[s] / sim
            lati[lato] = {"p": round(p, 4), "posta": None if posta is None else round(posta, 4),
                          "fuori": p < SOGLIA_P and posta is not None and posta <= SOGLIA_POSTA}
        partite[f"{g['ospite']}@{g['casa']}"] = lati
    return {"stagione": stagione, "settimana": W, "simulazioni": sim, "partite": partite}
