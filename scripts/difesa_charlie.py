"""Charlie, sezione Difesa (NFL): per ogni partita in arrivo, i difensori delle due squadre con
probabilità di almeno 0,5 sack (regola bet365), probabilità di almeno un intercetto e placcaggi attesi.

Formule e costanti del Protocollo 10 (data/charlie_tabelle.json, «difesa»), misurate sul 2019-2025:
- sack attesi della difesa = exp(costante + 0,6437·log ritmo attacco + 0,2577·log ritmo difesa + 0,0126·sfavorito)
  (ritmi della stagione tirati verso la lega; sfavorito = punti da sfavorito dell'attacco secondo la linea americana)
- sack del giocatore: 1 − exp(−a·(sack attesi × quota del giocatore)^b)
- intercetti: stessa forma, ×1,28 se il QB titolare avversario è fuori (l'unica assenza che conta, misurata)
- placcaggi attesi = media del giocatore × azioni attese dell'avversario / media di lega
Si ricalcola a ogni aggiornamento della sezione (anche ogni ora): quando cambia la linea o il QB avversario, la
probabilità si sposta e resta il valore precedente con il motivo, per vedere la variazione.
Solo libreria standard.
"""
from __future__ import annotations

import math
from collections import defaultdict

GRUPPI = {"DL", "LB", "DB"}
MOSTRATI = 14                    # difensori per squadra nella pagina
SOGLIA_VARIAZIONE = 0.02         # sotto i 2 punti % non si segna come variazione


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _qb_fuori(assenze: dict | None) -> str | None:
    """Nome del QB titolare fuori (peso ≥ 3 = almeno 30% della produzione), se c'è."""
    for x in ((assenze or {}).get("giocatori") or []):
        if str(x.get("ruolo", "")).upper() == "QB" and str(x.get("stato", "")).upper() in ("O", "OUT", "D", "DOUBTFUL", "INATTIVO") \
                and (x.get("peso") or 0) >= 3:
            return x.get("nome") or "QB"
    return None


def _stato_giocatore(assenze: dict | None, nome: str) -> str | None:
    n = "".join(c for c in (nome or "").lower() if c.isalnum())
    for x in ((assenze or {}).get("giocatori") or []):
        if "".join(c for c in (x.get("nome") or "").lower() if c.isalnum()) == n:
            return str(x.get("stato") or "").upper()
    return None


def _norm(n) -> str:
    return "".join(c for c in (n or "").lower() if c.isalnum())


def calcola(schede: list, righe: list, tab: dict, pressioni: dict | None = None) -> int:
    """Aggiunge sc["difesa"] alle schede NFL. `righe` = statistiche settimanali nflverse della stagione.
    `pressioni` = {(stagione, settimana, squadra, nome normalizzato): pressioni} da PFR (advstats_week_def):
    dal 16/11/2026 entrano nella quota del giocatore sui sack (Protocollo 10, aggiunta: Brier −1,4%)."""
    pressioni = pressioni or {}
    T = (tab or {}).get("difesa", {}).get("NFL")
    if not T:
        return 0
    reg = [r for r in righe if r.get("season_type") == "REG"]
    att = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])     # (gid, squadra) -> [lanci, sack subiti, intercetti, corse]
    dif = defaultdict(lambda: defaultdict(dict))        # squadra -> gid -> pid -> riga
    settimana = {}
    for r in reg:
        g, sq = r.get("game_id") or f"{r.get('season')}_{r.get('week')}_{r.get('team')}", r.get("team")
        settimana[g] = int(_f(r.get("week")))
        a = att[(g, sq)]
        a[0] += _f(r.get("attempts")); a[1] += _f(r.get("sacks_suffered"))
        a[2] += _f(r.get("passing_interceptions")); a[3] += _f(r.get("carries"))
        if r.get("position_group") in GRUPPI:
            dif[sq][g][r.get("player_id")] = r
    avversario = {}
    for (g, sq) in att:
        for (g2, sq2) in att:
            if g2 == g and sq2 != sq:
                avversario[(g, sq)] = sq2
    giochi_sq = defaultdict(list)
    for (g, sq) in att:
        giochi_sq[sq].append(g)
    tot = [sum(v[i] for v in att.values()) for i in range(4)]
    n_partite = max(len(att), 1)
    m_sack = tot[1] / max(tot[0] + tot[1], 1)
    m_int = tot[2] / max(tot[0], 1)
    lanci_lega = tot[0] / n_partite
    azioni_lega = (tot[0] + tot[1] + tot[3]) / n_partite
    S, P, I = T["sackSquadra"], T["sackGiocatore"], T["intercetti"]
    calcolate = 0
    for sc in schede:
        mk = sc.get("mercato") or {}
        nuovo = {}
        for difesa, attacco, ass_dif, ass_att in ((sc["casa"], sc["ospite"], sc.get("assenzeCasa"), sc.get("assenzeOspite")),
                                                  (sc["ospite"], sc["casa"], sc.get("assenzeOspite"), sc.get("assenzeCasa"))):
            ga, gd = giochi_sq.get(attacco, []), giochi_sq.get(difesa, [])
            if len(ga) < 2 or len(gd) < 2:
                continue
            # ritmi dell'attacco (sack concessi, intercetti lanciati) e della difesa (sack e intercetti procurati)
            la = sum(att[(g, attacco)][0] for g in ga); sa = sum(att[(g, attacco)][1] for g in ga)
            ia = sum(att[(g, attacco)][2] for g in ga); ca = sum(att[(g, attacco)][3] for g in ga)
            sd = sum(_f(r.get("def_sacks")) for g in gd for r in dif[difesa][g].values())
            opp = [att[(g, avversario[(g, difesa)])] for g in gd if (g, difesa) in avversario]
            dd = sum(o[0] + o[1] for o in opp); id_ = sum(o[2] for o in opp); ld = sum(o[0] for o in opp)
            r_att = (sa + S["tiro"] * m_sack) / (la + sa + S["tiro"])
            r_dif = (sd + S["tiro"] * m_sack) / (dd + S["tiro"])
            margine_att = mk.get("margineCasa")
            if margine_att is not None and attacco != sc["casa"]:
                margine_att = -margine_att
            sfav = -(margine_att or 0.0)
            lam_sack = math.exp(S["costante"] + S["ritmoAttacco"] * math.log(r_att / m_sack)
                                + S["ritmoDifesa"] * math.log(r_dif / m_sack) + S["sfavorito"] * sfav)
            att_int = (ia + I["tiro"] * m_int) / (la + I["tiro"])
            dif_int = (id_ + I["tiro"] * m_int) / (ld + I["tiro"])
            lanci = (la + 3 * lanci_lega) / (len(ga) + 3)
            lam_int = att_int * dif_int / m_int * lanci
            azioni = (la + sa + ca + 3 * azioni_lega) / (len(ga) + 3)
            qb = _qb_fuori(ass_att)
            # quote dei giocatori della difesa nelle sue partite
            acc = defaultdict(lambda: {"eq": 0.0, "ip": 0.0, "so": 0.0, "as": 0.0, "n": 0, "ultima": 0, "r": None})
            for g in gd:
                for pid, r in dif[difesa][g].items():
                    x = acc[pid]
                    x["eq"] += _f(r.get("def_sacks")) + P["pesoColpi"] * _f(r.get("def_qb_hits")) \
                        + P.get("pesoPressioni", 0.0) * pressioni.get(
                            (str(r.get("season")), str(int(_f(r.get("week")))), difesa, _norm(r.get("player_display_name"))), 0.0)
                    x["ip"] += _f(r.get("def_interceptions")) + I["pesoDeviati"] * _f(r.get("def_pass_defended"))
                    x["so"] += _f(r.get("def_tackles_solo")); x["as"] += _f(r.get("def_tackle_assists"))
                    x["n"] += 1
                    x["ultima"] = max(x["ultima"], settimana.get(g, 0))
                    x["r"] = r
            tot_eq = sum(x["eq"] for x in acc.values())
            tot_ip = sum(x["ip"] for x in acc.values())
            ultima_sq = max(settimana.get(g, 0) for g in gd)
            gioc = []
            for pid, x in acc.items():
                r = x["r"]
                if x["ultima"] < ultima_sq - 1:          # non gioca da più di una partita: fuori dall'elenco
                    continue
                stato = _stato_giocatore(ass_dif, r.get("player_display_name"))
                # fuori: anche lista infortunati e sospesi (come li scrive ESPN) e inattivi della lista del giorno
                if stato in ("O", "OUT", "IR", "INJURED RESERVE", "SUSPENSION", "S", "INATTIVO"):
                    continue
                grp = r.get("position_group")
                q_sack = (x["eq"] + P["tiro"] * P["mediaRuolo"][grp]) / (tot_eq + P["tiro"])
                p_sack = 1 - math.exp(-P["a"] * (lam_sack * q_sack) ** P["b"])
                q_int = (x["ip"] + I["tiroQuota"] * I["mediaRuolo"][grp] * len(gd)) / (tot_ip + I["tiroQuota"])
                p_int = (1 - math.exp(-I["a"] * (lam_int * q_int) ** I["b"])) * (I["qbRiserva"] if qb else 1.0)
                k = azioni / azioni_lega
                gioc.append({"n": r.get("player_display_name"), "id": pid, "r": r.get("position") or grp, "g": grp,
                             "sack": round(p_sack, 4), "int": round(min(p_int, 0.9), 4),
                             "tk": round((x["so"] + x["as"]) / x["n"] * k, 2), "so": round(x["so"] / x["n"] * k, 2),
                             "as": round(x["as"] / x["n"] * k, 2), "dubbio": stato in ("Q", "QUESTIONABLE", "D", "DOUBTFUL")})
            gioc.sort(key=lambda d: -(2 * d["sack"] + 3 * d["int"] + d["tk"] / 10))
            nuovo[difesa] = {"giocatori": gioc[:MOSTRATI], "sackAttesi": round(lam_sack, 2),
                             "ingressi": {"margineAttacco": margine_att, "qbAvversarioFuori": qb}}
        if nuovo:
            _variazioni(sc.get("difesa") or {}, nuovo)
            sc["difesa"] = nuovo
            calcolate += 1
    return calcolate


def _variazioni(vecchio: dict, nuovo: dict) -> None:
    """Se una probabilità si sposta di almeno 2 punti rispetto al calcolo precedente, si tengono il valore di prima
    e il motivo (linea americana mossa, QB avversario fuori o rientrato). Le variazioni restano finché non ne
    arriva un'altra, così si vedono anche ore dopo la notizia."""
    for sq, d in nuovo.items():
        v = vecchio.get(sq) or {}
        vi, ni = v.get("ingressi") or {}, d.get("ingressi") or {}
        motivi = []
        if vi and vi.get("margineAttacco") != ni.get("margineAttacco") and ni.get("margineAttacco") is not None:
            motivi.append(f"linea americana dell'attacco da {vi.get('margineAttacco')} a {ni.get('margineAttacco')}")
        if vi and bool(vi.get("qbAvversarioFuori")) != bool(ni.get("qbAvversarioFuori")):
            motivi.append(f"QB avversario {'fuori: ' + ni['qbAvversarioFuori'] if ni.get('qbAvversarioFuori') else 'di nuovo disponibile'}")
        prima = {g["id"]: g for g in v.get("giocatori") or []}
        for g in d["giocatori"]:
            p = prima.get(g["id"])
            if not p:
                continue
            for k in ("sack", "int"):
                if abs(g[k] - p[k]) >= SOGLIA_VARIAZIONE and motivi:
                    g[k + "Prima"] = p[k]
                    g["motivo"] = "; ".join(motivi)
                elif p.get(k + "Prima") is not None:          # variazione precedente ancora valida
                    g[k + "Prima"] = p[k + "Prima"]
                    g["motivo"] = p.get("motivo")
