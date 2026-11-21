"""Charlie, touchdown di un giocatore (NFL, dal 21/11/2026): probabilità che segni almeno un touchdown.

Misura del 21/11/2026 sul play-by-play nflverse 2019-2025 (stima 2019-22, prova 2023-25), giocatori con almeno
una corsa o un bersaglio nella partita e almeno 2 partite giocate prima nella stagione:
- touchdown attesi della squadra = A · punti attesi della squadra + B   (punti attesi dalla linea americana:
  casa = (totale + margine) / 2, ospite = (totale − margine) / 2)
- quota del giocatore = 0,3 · quota delle occasioni vicino alla meta (corse e bersagli dentro le 10 yard)
                      + 0,3 · quota dei touchdown della squadra + 0,4 · quota dei palloni toccati (corse + bersagli),
  sulle partite giocate nella stagione, con la stagione scorsa che pesa 0,3 per partita, tirata verso la media del
  ruolo con 2 partite di peso
- probabilità = 1 − e^(−C · touchdown attesi della squadra · quota del giocatore)
Brier sulla prova 0,1592 contro 0,1728 di chi dà a tutti la frequenza media (−7,9%); calibrata tra il 10% e il 60%,
un po' bassa sotto il 10% (prevista 7,6%, vera 10,0%). Confronto con le quote dei bookmaker: non fatto (ESPN non
dà le quote dei touchdown, 21/11/2026), quindi affidabilità C.
Conta solo i touchdown di corsa e su ricezione (non i ritorni né quelli della difesa).
Solo libreria standard.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

A, B, C = 0.129, -0.483, 0.95
PESI = (0.3, 0.3, 0.4)                  # occasioni vicino alla meta, touchdown, palloni toccati
K_RUOLO = 2.0                           # partite di peso della media del ruolo
PESO_SCORSA = 0.3                       # una partita della stagione scorsa vale 0,3 partite di questa
PRIOR = {"RB": (0.1975, 0.1424, 0.1907), "QB": (0.1018, 0.0915, 0.0596), "WR": (0.07, 0.1052, 0.09),
         "TE": (0.0724, 0.0841, 0.0617), "FB": (0.0445, 0.0338, 0.0316)}
MOSTRATI = 12                           # giocatori per squadra nella pagina
RADICE = Path(__file__).resolve().parent.parent


class Raccolta:
    """Passa le righe del play-by-play e intanto annota, per partita, squadra e giocatore:
    corse, corse dentro le 10 yard, bersagli, bersagli dentro le 10 yard, touchdown (corsa + ricezione), nome."""

    def __init__(self):
        self.gio = defaultdict(lambda: [0, 0, 0, 0, 0, 0.0, ""])
        self.sett = {}

    def passa(self, righe):
        for r in righe:
            try:
                if r.get("season_type") == "REG" and r.get("play_type") in ("pass", "run") \
                        and "No Play" not in (r.get("desc") or ""):
                    self._azione(r)
            except (KeyError, ValueError):
                pass
            yield r

    def _azione(self, r):
        g, t = r["game_id"], r["posteam"]
        self.sett[g] = int(float(r["week"]))
        yl = float(r["yardline_100"]) if r.get("yardline_100") not in ("", "NA", None) else 99.0
        if r["play_type"] == "run" and r.get("rusher_player_id") not in ("", "NA", None):
            v = self.gio[(g, t, r["rusher_player_id"])]
            v[0] += 1
            v[1] += yl <= 10
            v[4] += r.get("rush_touchdown") == "1"
            v[6] = r.get("rusher_player_name") or v[6]
        if r["play_type"] == "pass" and r.get("receiver_player_id") not in ("", "NA", None):
            v = self.gio[(g, t, r["receiver_player_id"])]
            v[2] += 1
            v[3] += yl <= 10
            v[4] += r.get("pass_touchdown") == "1" and r.get("complete_pass") == "1"
            v[6] = r.get("receiver_player_name") or v[6]

    def righe(self) -> list:
        """[game_id, squadra, giocatore, corse, corse10, bersagli, bersagli10, td, yard, nome] (stesso formato
        dell'archivio della stagione scorsa, data/td_nfl_<stagione>.json)."""
        return [[g, t, p] + list(v) for (g, t, p), v in self.gio.items()]


def _quote(righe: list) -> tuple[dict, dict]:
    """Per giocatore: liste delle partite con (occasioni10, td, palloni) del giocatore e della squadra."""
    squ = defaultdict(lambda: [0, 0, 0])
    for g, t, p, car, c10, tgt, t10, td, *_ in righe:
        s = squ[(g, t)]
        s[0] += c10 + t10
        s[1] += td
        s[2] += car + tgt
    per = defaultdict(list)
    for g, t, p, car, c10, tgt, t10, td, _yd, nome in righe:
        s = squ[(g, t)]
        per[p].append({"g": g, "t": t, "o": c10 + t10, "td": td, "h": car + tgt, "so": s[0], "std": s[1], "sh": s[2],
                       "nome": nome})
    return per, squ


def _rapporti(xs: list) -> tuple:
    so, sd, sh = (sum(x[k] for x in xs) for k in ("so", "std", "sh"))
    return (sum(x["o"] for x in xs) / so if so else 0.0, sum(x["td"] for x in xs) / sd if sd else 0.0,
            sum(x["h"] for x in xs) / sh if sh else 0.0)


def quota_giocatore(questa: list, scorsa: list, ruolo: str) -> tuple[float, float]:
    """(quota del giocatore nei touchdown della squadra, partite di peso)."""
    n, a = len(questa), _rapporti(questa) if questa else (0.0, 0.0, 0.0)
    if scorsa:
        b, m = _rapporti(scorsa), len(scorsa) * PESO_SCORSA
        a = tuple((n * x + m * y) / (n + m) for x, y in zip(a, b)) if n + m else b
        n += m
    pr = PRIOR.get(ruolo, (0.02, 0.02, 0.02))
    sh = [(n * x + K_RUOLO * y) / (n + K_RUOLO) for x, y in zip(a, pr)]
    return sum(w * x for w, x in zip(PESI, sh)), n


def calcola(schede: list, corrente: list, scorsa: list, ruoli: dict, nomi: dict, attuale: dict) -> int:
    """Aggiunge sc["touchdown"] = {squadra: [{id, n, r, quota, partite}]} alle schede NFL.
    `attuale` = {id giocatore: squadra della sua partita più recente} (i ceduti passano alla nuova squadra).
    La probabilità la calcola la pagina con la linea americana del momento (punti attesi della squadra)."""
    per, _ = _quote(corrente)
    per_scorsa, _ = _quote(scorsa) if scorsa else ({}, None)
    fatte = 0
    for sc in schede:
        blocco = {}
        for sq in (sc.get("casa"), sc.get("ospite")):
            lista = []
            for p, partite in per.items():
                if attuale.get(p) != sq or len(partite) < 2:
                    continue
                q, n = quota_giocatore(partite, per_scorsa.get(p, []), ruoli.get(p, ""))
                lista.append({"id": p, "n": nomi.get(p) or partite[-1]["nome"], "r": ruoli.get(p, ""),
                              "quota": round(q, 4), "partite": len(partite)})
            lista.sort(key=lambda x: -x["quota"])
            if lista:
                blocco[sq] = lista[:MOSTRATI]
        if blocco:
            sc["touchdown"] = blocco
            fatte += 1
    return fatte


def archivio_scorsa(stagione: int) -> list:
    """Righe della stagione precedente, salvate una volta nel repository (data/td_nfl_<stagione>.json)."""
    p = RADICE / "data" / f"td_nfl_{stagione}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
