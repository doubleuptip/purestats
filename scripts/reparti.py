"""Reparti attacco contro difesa dal play-by-play, uguali per NFL (nflverse) e college (cfbfastR).

Sono le definizioni verificate sullo storico 2019–2025 (misura del 13/11/2026):
  corse      EPA per corsa
  passaggi   EPA per azione di passaggio (sack compresi)
  pressione  − quota di sack sulle azioni di passaggio (più alto = meglio per l'attacco)
  esplosive  quota di corse da 10+ yard e passaggi da 20+ yard sulle azioni
Ogni valore è corretto una volta per la forza degli avversari affrontati. Contano solo le partite giocate
PRIMA della settimana richiesta e solo le squadre con almeno MIN_PARTITE partite in attacco e in difesa.

Della prova è risultata utile la parte "difesa avversaria": quanto una difesa concede in più (o in meno)
della media del campionato. La forza dell'attacco invece è già tutta nella sua media e non aggiunge nulla.
Solo libreria standard.
"""
from __future__ import annotations

from collections import defaultdict

AREE = ("corse", "passaggi", "pressione", "esplosive")
MIN_PARTITE = 4


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _vero(x):
    return str(x).strip().upper() in ("TRUE", "1", "1.0")


# ------------------------------------------------------------------ lettura
def azioni_nflverse(righe):
    """Righe del play-by-play nflverse -> azioni (settimana, partita, attacco, difesa, tipo, epa, yard, sack)."""
    for r in righe:
        if r.get("season_type") not in ("REG", "POST") or r.get("play_type") == "no_play":
            continue
        p, ru = r.get("pass") == "1", r.get("rush") == "1"
        epa = _f(r.get("epa"))
        if not (p or ru) or epa is None or not r.get("posteam"):
            continue
        try:
            w = int(r["week"])
        except (KeyError, ValueError):
            continue
        yield (w, r.get("game_id"), r["posteam"], r.get("defteam"), "P" if p else "R", epa,
               _f(r.get("yards_gained")) or 0.0, r.get("sack") == "1")


def azioni_cfbfastr(righe):
    """Righe del play-by-play cfbfastR -> azioni, solo partite tra due squadre FBS."""
    for r in righe:
        if r.get("season_type") not in ("regular", "postseason"):
            continue
        if r.get("home_team_division") != "fbs" or r.get("away_team_division") != "fbs":
            continue
        rush, pas = _vero(r.get("rush")), _vero(r.get("pass"))
        epa = _f(r.get("EPA"))
        if not (rush or pas) or epa is None or _vero(r.get("penalty_no_play")):
            continue
        w = _f(r.get("week"))
        if w is None:
            continue
        yield (int(w), r.get("game_id"), r.get("pos_team"), r.get("def_pos_team"), "R" if rush and not pas else "P",
               epa, _f(r.get("yards_gained")) or 0.0, _vero(r.get("sack")) or _vero(r.get("sack_vec")))


# ------------------------------------------------------------------ calcolo
def aggrega(azioni) -> dict:
    """{(settimana, partita, attacco, difesa): somme}"""
    agg = defaultdict(lambda: {"nr": 0, "er": 0.0, "np": 0, "ep": 0.0, "sack": 0, "espl": 0, "az": 0})
    for w, g, o, d, tipo, epa, y, sack in azioni:
        a = agg[(w, g, o, d)]
        a["az"] += 1
        if tipo == "R":
            a["nr"] += 1
            a["er"] += epa
            a["espl"] += y >= 10
        else:
            a["np"] += 1
            a["ep"] += epa
            if sack:
                a["sack"] += 1
            else:
                a["espl"] += y >= 20
    return dict(agg)


def _valori(a) -> dict:
    return {"corse": a["er"] / a["nr"] if a["nr"] else None,
            "passaggi": a["ep"] / a["np"] if a["np"] else None,
            "pressione": -a["sack"] / a["np"] if a["np"] else None,
            "esplosive": a["espl"] / a["az"] if a["az"] else None}


def _somma(lista) -> dict:
    t = defaultdict(float)
    for a in lista:
        for k, v in a.items():
            t[k] += v
    return t


def stato(agg: dict, settimana: int) -> dict:
    """Situazione prima della settimana: per squadra valori corretti, ranghi, azioni a partita.
    {squadra: {"att": {area: v}, "dif": {area: v}, "rango_att": {...}, "rango_dif": {...},
               "pct_dif": {area: 0..1, 1 = la difesa più debole}, "scarto_dif": {area: v - media},
               "corse_pp", "passaggi_pp", "partite", "n"}}"""
    att, dif, avv_att, avv_dif = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for (w, g, o, d), a in agg.items():
        if w < settimana:
            att[o].append(a)
            dif[d].append(a)
            avv_att[o].append(d)
            avv_dif[d].append(o)
    grezzi = {}
    for t in set(att) | set(dif):
        if len(att[t]) < MIN_PARTITE or len(dif[t]) < MIN_PARTITE:
            continue
        so, sd = _somma(att[t]), _somma(dif[t])
        grezzi[t] = {"att": _valori(so), "dif": _valori(sd), "partite": len(att[t]),
                     "corse_pp": so["nr"] / len(att[t]), "passaggi_pp": so["np"] / len(att[t])}
    if len(grezzi) < 2:
        return {}
    out = {t: {"att": {}, "dif": {}, "rango_att": {}, "rango_dif": {}, "pct_dif": {}, "scarto_dif": {},
               "corse_pp": v["corse_pp"], "passaggi_pp": v["passaggi_pp"], "partite": v["partite"],
               "n": len(grezzi)} for t, v in grezzi.items()}
    for k in AREE:
        vo = {t: v["att"][k] for t, v in grezzi.items() if v["att"][k] is not None}
        vd = {t: v["dif"][k] for t, v in grezzi.items() if v["dif"][k] is not None}
        if not vo or not vd:
            continue
        lo, ld = sum(vo.values()) / len(vo), sum(vd.values()) / len(vd)
        for t in grezzi:
            dd = [vd[x] - ld for x in avv_att[t] if x in vd]      # difese affrontate dall'attacco di t
            oo = [vo[x] - lo for x in avv_dif[t] if x in vo]      # attacchi affrontati dalla difesa di t
            if t in vo:
                out[t]["att"][k] = vo[t] - (sum(dd) / len(dd) if dd else 0.0)
            if t in vd:
                out[t]["dif"][k] = vd[t] - (sum(oo) / len(oo) if oo else 0.0)
        ca = {t: out[t]["att"][k] for t in out if k in out[t]["att"]}
        cd = {t: out[t]["dif"][k] for t in out if k in out[t]["dif"]}
        md = sum(cd.values()) / len(cd)
        ra, rd = _rango({t: -v for t, v in ca.items()}), _rango(cd)   # 1 = attacco migliore / difesa migliore
        n = len(cd)
        for t in out:
            if t in ra:
                out[t]["rango_att"][k] = ra[t]
            if t in rd:
                out[t]["rango_dif"][k] = rd[t]
                out[t]["pct_dif"][k] = (rd[t] - 1) / (n - 1) if n > 1 else 0.5
                out[t]["scarto_dif"][k] = cd[t] - md   # > 0: concede più della media (debole)
    return out


def _rango(vals: dict) -> dict:
    """Posizione 1 = valore più basso; a pari merito la posizione media."""
    out = {}
    for t, v in vals.items():
        meglio = sum(1 for x in vals.values() if x < v - 1e-12)
        pari = sum(1 for x in vals.values() if abs(x - v) <= 1e-12)
        out[t] = round(meglio + (pari + 1) / 2)
    return out


def punti_difesa(st: dict, attacco: str, difesa: str) -> float | None:
    """Punti in più (o in meno) attesi per l'attacco per via della difesa che trova, rispetto a una difesa
    media: scarto di EPA concesso su corse e passaggi × azioni a partita dell'attacco.
    L'EPA è in punti, quindi la somma è già in punti (verificato sullo storico nella misura)."""
    a, d = st.get(attacco), st.get(difesa)
    if not a or not d or "corse" not in d["scarto_dif"] or "passaggi" not in d["scarto_dif"]:
        return None
    return d["scarto_dif"]["corse"] * a["corse_pp"] + d["scarto_dif"]["passaggi"] * a["passaggi_pp"]


def soglie(n: int) -> tuple[int, int]:
    """Migliori = prime round(n·10/32), peggiori = dalla posizione n − round(n·11/32) + 1."""
    return round(n * 10 / 32), n - round(n * 11 / 32) + 1


# ------------------------------------------------------------------ taratura sullo storico 2019–2025
# Misura del 13/11/2026 (play-by-play nflverse e cfbfastR, solo partite già giocate prima di ognuna).
# Punti: lo spostamento grezzo di punti_difesa si ritrova nei punteggi reali solo in parte; la pendenza
# misurata lo riporta in punti veri. "variabilita" = scarto tipico del totale / margine reale.
#   NFL      totale pendenza 0,31 ± 0,05   margine 0,20 ± 0,05   (positiva in entrambi i periodi)
#   college  totale pendenza 0,62 ± 0,03   margine 0,63 ± 0,03
# Rispetto alle linee di chiusura NFL la pendenza è ~0: i bookmaker ne tengono già conto.
# Aggiornamento 14/11/2026 (protocollo 5: stima 2019-22, prova su 2023-25 mai viste, poi stima su 2019-2025):
#   campo           vantaggio di chi gioca in casa (0 in campo neutro), stimato senza il 2020 (stadi vuoti);
#                   nelle partite in campo neutro l'effetto misurato è ≈ 0, come deve
#   costante_totale college: la somma delle due norme sovrastima il totale reale di 3,5 punti in ogni stagione
#   norma_margine   college: il margine parte dalle norme corrette per le difese affrontate (migliora la prova
#                   2023-25 di 0,17 punti); NFL: nessun miglioramento, resta la norma semplice
# Provate e scartate: correzione avversari ripetuta (SRS: nel college peggiora), z-score dei giocatori.
TARATURA_PUNTI = {
    "NFL": {"totale": 0.31, "margine": 0.20, "var_totale": 14.0, "var_margine": 13.5,
            "campo": 1.95, "costante_totale": 0.0, "norma_margine": False},
    "College": {"totale": 0.63, "margine": 0.61, "var_totale": 17.7, "var_margine": 16.7,
                "campo": 2.96, "costante_totale": -3.54, "norma_margine": True},
}
# Giocatori: yard in più passando dalla difesa migliore alla peggiore del reparto (effetto = valore ×
# (percentile − 0,5)), variabilità tipica delle yard in una partita ed errore medio della previsione.
TARATURA_GIOCATORI = {
    "NFL": {"QB": (20.0, 80.1, 62), "RB": (15.2, 37.6, 28), "WR": (5.5, 38.5, 29), "TE": (8.3, 30.6, 22)},
    "College": {"QB": (31.9, 92.7, 66), "RB": (24.1, 47.1, 35), "WR": (9.1, 42.0, 29), "TE": (7.7, 30.4, 22)},
}
