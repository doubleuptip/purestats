"""Forza delle squadre NFL dall'EPA per azione, corretta per gli avversari.

Modello per ogni partita e lato (attacco di A contro difesa di B):
    epa_per_azione = media + Att[A] - Dif[B] + casa
Pesi: numero di azioni x decadimento nel tempo (le partite vecchie contano meno, la stagione
precedente pesa poco e viene ritirata verso la media). Stima con minimi quadrati pesati e una
"spinta verso zero" (ridge), che evita forze esagerate dopo poche partite.

Passaggi e corse sono stimati a parte: il passaggio è più stabile e predittivo, la corsa più rumorosa.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Parametri: scelti con la verifica sullo storico (backtest.py), non a occhio.
HALF_LIFE_WEEKS = 16.0      # dopo 16 settimane una partita pesa la metà (verificato 2017-2021)
PREV_SEASON_FACTOR = 0.9   # la stagione prima conta quasi come la corrente (verificato 2017-2021)
RIDGE = {"pass": 300.0, "rush": 600.0}   # "azioni fittizie" a forza zero: più alto = più prudente


def week_index(season: int, week: int) -> int:
    """Tempo continuo in settimane: 22 settimane per stagione (regolare + playoff) e pausa estiva."""
    return season * 30 + week


@dataclass
class Rating:
    team: str
    off_pass: float = 0.0
    off_rush: float = 0.0
    def_pass: float = 0.0     # positivo = difesa buona (toglie EPA)
    def_rush: float = 0.0
    n_plays: float = 0.0      # azioni pesate su cui si regge (affidabilità)
    pass_rate: float = 0.58   # quota di passaggi in attacco

    def off(self) -> float:
        return self.pass_rate * self.off_pass + (1 - self.pass_rate) * self.off_rush

    def deff(self, opp_pass_rate: float = 0.58) -> float:
        return opp_pass_rate * self.def_pass + (1 - opp_pass_rate) * self.def_rush


def _fit(sides, ridge: float, iters: int = 40):
    """sides: lista di (attacco, difesa, casa, n, epa_totale, peso). Restituisce media, casa, Att, Dif."""
    teams = {s[0] for s in sides} | {s[1] for s in sides}
    att = dict.fromkeys(teams, 0.0)
    dif = dict.fromkeys(teams, 0.0)
    mu, hfa = 0.0, 0.0
    for _ in range(iters):
        # media generale e casa
        num = den = 0.0
        for a, d, h, n, e, w in sides:
            ww = n * w
            num += ww * (e / n - att[a] + dif[d] - (hfa if h else 0.0))
            den += ww
        mu = num / den if den else 0.0
        num = den = 0.0
        for a, d, h, n, e, w in sides:
            if h:
                ww = n * w
                num += ww * (e / n - mu - att[a] + dif[d])
                den += ww
        hfa = num / (den + ridge) if den else 0.0
        # attacchi
        num_a = dict.fromkeys(teams, 0.0)
        den_a = dict.fromkeys(teams, 0.0)
        for a, d, h, n, e, w in sides:
            ww = n * w
            num_a[a] += ww * (e / n - mu + dif[d] - (hfa if h else 0.0))
            den_a[a] += ww
        for t in teams:
            att[t] = num_a[t] / (den_a[t] + ridge)
        # difese
        num_d = dict.fromkeys(teams, 0.0)
        den_d = dict.fromkeys(teams, 0.0)
        for a, d, h, n, e, w in sides:
            ww = n * w
            num_d[d] += ww * -(e / n - mu - att[a] - (hfa if h else 0.0))
            den_d[d] += ww
        for t in teams:
            dif[t] = num_d[t] / (den_d[t] + ridge)
    return mu, hfa, att, dif


def build(team_games, season: int, week: int, half_life: float = HALF_LIFE_WEEKS,
          prev_factor: float = PREV_SEASON_FACTOR, ridge: dict | None = None,
          lookback_seasons: int = 2) -> dict[str, Rating]:
    """Forze usando solo le partite PRIMA di (season, week): nessuna informazione dal futuro."""
    ridge = ridge or RIDGE
    now = week_index(season, week)
    lam = math.log(2) / half_life
    pas, rus = [], []
    pr_n: dict[str, float] = {}
    pr_p: dict[str, float] = {}
    plays_w: dict[str, float] = {}
    for t in team_games:
        if (t.season, t.week) >= (season, week) or t.season < season - lookback_seasons + 1:
            continue
        w = math.exp(-lam * (now - week_index(t.season, t.week)))
        if t.season < season:
            w *= prev_factor
        if t.pass_n:
            pas.append((t.team, t.opp, t.home, t.pass_n, t.pass_epa, w))
        if t.rush_n:
            rus.append((t.team, t.opp, t.home, t.rush_n, t.rush_epa, w))
        pr_n[t.team] = pr_n.get(t.team, 0.0) + w * t.plays
        pr_p[t.team] = pr_p.get(t.team, 0.0) + w * t.pass_n
        plays_w[t.team] = plays_w.get(t.team, 0.0) + w * (t.plays + t.d_plays)
    if not pas:
        return {}
    _, _, pa, pd = _fit(pas, ridge["pass"])
    _, _, ra, rd = _fit(rus, ridge["rush"])
    out = {}
    for team in set(pa) | set(ra):
        out[team] = Rating(team, pa.get(team, 0.0), ra.get(team, 0.0), pd.get(team, 0.0), rd.get(team, 0.0),
                           plays_w.get(team, 0.0), pr_p.get(team, 0.0) / pr_n[team] if pr_n.get(team) else 0.58)
    return out


def matchup_epa(home: Rating, away: Rating) -> tuple[float, float]:
    """EPA per azione atteso per l'attacco di casa e per quello in trasferta (senza vantaggio campo)."""
    h = home.pass_rate * (home.off_pass - away.def_pass) + (1 - home.pass_rate) * (home.off_rush - away.def_rush)
    a = away.pass_rate * (away.off_pass - home.def_pass) + (1 - away.pass_rate) * (away.off_rush - home.def_rush)
    return h, a
