"""Dati NFL da nflverse (file pubblici su GitHub, licenza CC-BY-SA 4.0, nessuna chiave).

Dal "azione per azione" si tiene solo un riassunto per squadra e partita: è tutto quello che serve
alla forza delle squadre e occupa poche centinaia di KB a stagione invece di decine di MB.
"""
from __future__ import annotations

import csv
import gzip
import io
import logging
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger("radar.football")

REL = "https://github.com/nflverse/nflverse-data/releases/download"
URL_GAMES = f"{REL}/schedules/games.csv"
URL_TEAMS = f"{REL}/teams/teams_colors_logos.csv"
URL_PBP = REL + "/pbp/play_by_play_{s}.csv.gz"
URL_INJ = REL + "/injuries/injuries_{s}.csv"
URL_DEPTH = REL + "/depth_charts/depth_charts_{s}.csv"
URL_STATS = REL + "/stats_player/stats_player_week_{s}.csv"
URL_SNAPS = REL + "/snap_counts/snap_counts_{s}.csv"
URL_ROSTER = REL + "/weekly_rosters/roster_weekly_{s}.csv"
URL_DRAFT = f"{REL}/draft_picks/draft_picks.csv"
UA = {"User-Agent": "radar-assenze (statistiche personali)"}


def download(url: str, timeout: int = 300, tries: int = 4) -> bytes:
    """GitHub a volte risponde 504 o una pagina d'errore: si riprova e si rifiuta l'HTML al posto del CSV."""
    import time
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                data = r.read()
            if data[:2] == b"\x1f\x8b" or not data.lstrip()[:1] == b"<":
                return data
            last = RuntimeError(f"risposta non valida (pagina HTML) da {url}")
        except Exception as e:      # noqa: BLE001 - si riprova e poi si rilancia l'ultimo errore
            last = e
        time.sleep(5 * (i + 1))
    raise last


def read_csv(data: bytes) -> list[dict]:
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return list(csv.DictReader(io.StringIO(data.decode("utf-8", "replace"))))


def fnum(x) -> float | None:
    try:
        return float(x) if x not in (None, "", "NA") else None
    except ValueError:
        return None


# ---------------------------------------------------------------- partite
@dataclass
class NflGame:
    game_id: str
    season: int
    week: int
    game_type: str          # REG, WC, DIV, CON, SB
    gameday: str
    gametime: str
    home: str
    away: str
    home_score: float | None
    away_score: float | None
    spread_line: float | None   # positivo = casa favorita (verificato sui dati)
    total_line: float | None
    home_ml: float | None
    away_ml: float | None
    roof: str
    surface: str
    temp: float | None
    wind: float | None
    home_rest: float | None
    away_rest: float | None
    div_game: bool
    location: str           # Home o Neutral
    espn: str
    stadium_id: str
    home_qb: str
    away_qb: str

    @property
    def played(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    @property
    def margin(self) -> float | None:
        return self.home_score - self.away_score if self.played else None

    @property
    def total(self) -> float | None:
        return self.home_score + self.away_score if self.played else None


def parse_games(rows: list[dict]) -> list[NflGame]:
    out = []
    for r in rows:
        out.append(NflGame(
            game_id=r["game_id"], season=int(r["season"]), week=int(r["week"]), game_type=r["game_type"],
            gameday=r["gameday"], gametime=r.get("gametime", ""), home=r["home_team"], away=r["away_team"],
            home_score=fnum(r.get("home_score")), away_score=fnum(r.get("away_score")),
            spread_line=fnum(r.get("spread_line")), total_line=fnum(r.get("total_line")),
            home_ml=fnum(r.get("home_moneyline")), away_ml=fnum(r.get("away_moneyline")),
            roof=r.get("roof", ""), surface=r.get("surface", ""), temp=fnum(r.get("temp")), wind=fnum(r.get("wind")),
            home_rest=fnum(r.get("home_rest")), away_rest=fnum(r.get("away_rest")),
            div_game=r.get("div_game") == "1", location=r.get("location", ""), espn=r.get("espn", ""),
            stadium_id=r.get("stadium_id", ""), home_qb=r.get("home_qb_id", ""), away_qb=r.get("away_qb_id", ""),
        ))
    return out


# ---------------------------------------------------------------- riassunto azione per azione
@dataclass
class TeamGame:
    """Una squadra in una partita: attacco e difesa, solo azioni di gioco vere (passaggi e corse)."""
    game_id: str
    season: int
    week: int
    team: str
    opp: str
    home: bool
    pass_n: int = 0
    pass_epa: float = 0.0
    rush_n: int = 0
    rush_epa: float = 0.0
    succ: int = 0
    d_pass_n: int = 0
    d_pass_epa: float = 0.0
    d_rush_n: int = 0
    d_rush_epa: float = 0.0
    d_succ: int = 0
    qb: dict = field(default_factory=dict)        # passatore -> (giocate, epa)

    @property
    def plays(self) -> int:
        return self.pass_n + self.rush_n

    @property
    def d_plays(self) -> int:
        return self.d_pass_n + self.d_rush_n


def summarize_pbp(rows, wp_range: tuple[float, float] | None = None) -> dict[tuple[str, str], TeamGame]:
    """Azione per azione -> {(game_id, squadra): TeamGame}.
    `wp_range` (es. (0.05, 0.95)): tiene solo le azioni giocate quando la partita era ancora aperta,
    misurata dalla probabilità di vittoria di chi attacca. None = tutte le azioni."""
    out: dict[tuple[str, str], TeamGame] = {}
    for r in rows:
        if r.get("season_type") not in ("REG", "POST"):
            continue
        is_pass, is_rush = r.get("pass") == "1", r.get("rush") == "1"
        if not (is_pass or is_rush):
            continue
        epa = fnum(r.get("epa"))
        if wp_range:
            wp = fnum(r.get("wp"))
            if wp is None or not (wp_range[0] <= wp <= wp_range[1]):
                continue
        pos, de = r.get("posteam"), r.get("defteam")
        if epa is None or not pos or not de:
            continue
        gid = r["game_id"]
        season, week = int(r["season"]), int(r["week"])
        home = r.get("home_team") == pos
        a = out.get((gid, pos))
        if a is None:
            a = out[(gid, pos)] = TeamGame(gid, season, week, pos, de, home)
        d = out.get((gid, de))
        if d is None:
            d = out[(gid, de)] = TeamGame(gid, season, week, de, pos, not home)
        ok = r.get("success") == "1"
        if is_pass:
            a.pass_n += 1
            a.pass_epa += epa
            d.d_pass_n += 1
            d.d_pass_epa += epa
            qb = r.get("passer_player_id") or ""
            if qb:
                n, e = a.qb.get(qb, (0, 0.0))
                a.qb[qb] = (n + 1, e + epa)
        else:
            a.rush_n += 1
            a.rush_epa += epa
            d.d_rush_n += 1
            d.d_rush_epa += epa
        a.succ += ok
        d.d_succ += ok
    return out


def iter_csv_gz(path_or_bytes):
    """Legge un CSV (anche compresso) riga per riga, senza tenere tutto in memoria."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        raw = io.BytesIO(path_or_bytes)
        f = gzip.open(raw, "rt", encoding="utf-8", errors="replace") if path_or_bytes[:2] == b"\x1f\x8b" \
            else io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
    else:
        f = gzip.open(path_or_bytes, "rt", encoding="utf-8", errors="replace") if str(path_or_bytes).endswith(".gz") \
            else open(path_or_bytes, encoding="utf-8", errors="replace")
    with f:
        yield from csv.DictReader(f)


TG_FIELDS = ["game_id", "season", "week", "team", "opp", "home", "pass_n", "pass_epa", "rush_n", "rush_epa", "succ",
             "d_pass_n", "d_pass_epa", "d_rush_n", "d_rush_epa", "d_succ", "qb"]


def save_summary(tg: dict, path) -> None:
    import os
    tmp = str(path) + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(TG_FIELDS)
        for t in sorted(tg.values(), key=lambda x: (x.season, x.week, x.game_id, x.team)):
            qb = ";".join(f"{k}:{n}:{e:.3f}" for k, (n, e) in sorted(t.qb.items(), key=lambda kv: -kv[1][0]))
            w.writerow([t.game_id, t.season, t.week, t.team, t.opp, int(t.home), t.pass_n, f"{t.pass_epa:.3f}",
                        t.rush_n, f"{t.rush_epa:.3f}", t.succ, t.d_pass_n, f"{t.d_pass_epa:.3f}", t.d_rush_n,
                        f"{t.d_rush_epa:.3f}", t.d_succ, qb])
    os.replace(tmp, path)          # mai un file a metà


def load_summary(path) -> list[TeamGame]:
    out = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            qb = {}
            for part in filter(None, r["qb"].split(";")):
                k, n, e = part.rsplit(":", 2)
                qb[k] = (int(n), float(e))
            out.append(TeamGame(r["game_id"], int(r["season"]), int(r["week"]), r["team"], r["opp"], r["home"] == "1",
                                int(r["pass_n"]), float(r["pass_epa"]), int(r["rush_n"]), float(r["rush_epa"]),
                                int(r["succ"]), int(r["d_pass_n"]), float(r["d_pass_epa"]), int(r["d_rush_n"]),
                                float(r["d_rush_epa"]), int(r["d_succ"]), qb))
    return out
