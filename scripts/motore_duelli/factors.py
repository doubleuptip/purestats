"""Fattori chiave: squilibri tra l'attacco di una squadra e la difesa dell'altra, solo dai dati (nessuna quota).

Ogni area ha, per ogni squadra, due valori orientati allo stesso modo: PIÙ ALTO = MEGLIO PER L'ATTACCO.
  off: quanto l'attacco della squadra produce          def: quanto la difesa della squadra concede
Classifiche: attacco 1 = il migliore; difesa 1 = la migliore (concede meno), ultima = la peggiore.
Punteggio di un incrocio (attacco A contro difesa B) = percentile attacco A + percentile "debolezza" difesa B − 1,
tra −1 (attacco tra i peggiori contro difesa tra le migliori) e +1 (il contrario). Segnale da |0,40| in su.

NFL: dal play-by-play nflverse della stagione, corretto per gli avversari affrontati (una passata).
College: CollegeFootballData, SP+ (già corretto per gli avversari) per corse, passaggi, esplosive;
statistiche avanzate per pressione (havoc), zona rossa (punti per occasione) e ritmo (azioni)."""
from __future__ import annotations

from collections import defaultdict

AREE = ("corse", "passaggi", "pressione", "esplosive", "zona_rossa")
NOMI = {"corse": "Corse", "passaggi": "Passaggi", "pressione": "Pressione sul QB", "esplosive": "Giocate esplosive",
        "zona_rossa": "Zona rossa"}
SOGLIA = 0.40
FORTE = 0.60


# ------------------------------------------------------------------ NFL dal play-by-play
def nfl_team_stats(rows) -> tuple[dict, dict]:
    """Azione per azione della stagione -> ({squadra: {area: (off, def)}, "_ritmo": azioni a partita}, avversari).
    Valori grezzi per azione; la correzione per gli avversari si fa con adjust()."""
    acc = defaultdict(lambda: defaultdict(float))
    games = defaultdict(set)
    opps = defaultdict(list)
    drives = {}
    for r in rows:
        if r.get("season_type") != "REG":
            continue
        pos, de, gid = r.get("posteam"), r.get("defteam"), r.get("game_id")
        is_pass, is_rush = r.get("pass") == "1", r.get("rush") == "1"
        if not pos or not de or not (is_pass or is_rush):
            continue
        try:
            epa = float(r.get("epa") or "nan")
            yds = float(r.get("yards_gained") or 0)
        except ValueError:
            continue
        if epa != epa:
            continue
        if gid not in games[pos]:
            games[pos].add(gid)
            opps[pos].append(de)
        games[de].add(gid)
        a, d = acc[pos], acc[de]
        a["plays"] += 1
        kind = "pass" if is_pass else "rush"
        a[f"o_{kind}_n"] += 1
        a[f"o_{kind}_epa"] += epa
        d[f"d_{kind}_n"] += 1
        d[f"d_{kind}_epa"] += epa
        boom = (yds >= 20) if is_pass else (yds >= 10)
        a["o_boom"] += boom
        d["d_boom"] += boom
        if is_pass:
            press = r.get("sack") == "1" or r.get("qb_hit") == "1"
            a["o_press"] += press
            d["d_press"] += press
        dk = (gid, r.get("fixed_drive") or r.get("drive"))
        try:
            yl = float(r.get("yardline_100") or 100)
        except ValueError:
            yl = 100
        if dk[1] and yl <= 20:
            drives[dk] = (pos, de, r.get("fixed_drive_result") == "Touchdown")
    for pos, de, td in drives.values():
        acc[pos]["o_rz"] += 1
        acc[pos]["o_rz_td"] += td
        acc[de]["d_rz"] += 1
        acc[de]["d_rz_td"] += td
    out = {}
    for t, a in acc.items():
        g = max(1, len(games[t]))

        def q(n, k):
            return a[n] / a[k] if a[k] else None
        out[t] = {
            "corse": (q("o_rush_epa", "o_rush_n"), q("d_rush_epa", "d_rush_n")),
            "passaggi": (q("o_pass_epa", "o_pass_n"), q("d_pass_epa", "d_pass_n")),
            "pressione": (_neg(q("o_press", "o_pass_n")), _neg(q("d_press", "d_pass_n"))),
            "esplosive": (a["o_boom"] / max(1, a["o_pass_n"] + a["o_rush_n"]),
                          a["d_boom"] / max(1, a["d_pass_n"] + a["d_rush_n"])),
            "zona_rossa": (q("o_rz_td", "o_rz"), q("d_rz_td", "d_rz")),
            "_ritmo": a["plays"] / g,
            "_partite": len(games[t]),
        }
    return out, dict(opps)


def _neg(x):
    return -x if x is not None else None


def adjust(stats: dict, opps: dict) -> dict:
    """Una passata di correzione per gli avversari: all'attacco si toglie quanto le difese affrontate erano più deboli
    della media; alla difesa quanto gli attacchi affrontati erano più forti della media."""
    out = {t: dict(v) for t, v in stats.items()}
    for area in AREE:
        offs = [v[area][0] for v in stats.values() if v[area][0] is not None]
        defs = [v[area][1] for v in stats.values() if v[area][1] is not None]
        if not offs or not defs:
            continue
        lo, ld = sum(offs) / len(offs), sum(defs) / len(defs)
        for t, v in stats.items():
            o, d = v[area]
            avv = [x for x in opps.get(t, []) if x in stats]
            dd = [stats[x][area][1] - ld for x in avv if stats[x][area][1] is not None]
            oo = [stats[x][area][0] - lo for x in avv if stats[x][area][0] is not None]
            if o is not None and dd:
                o -= sum(dd) / len(dd)
            if d is not None and oo:
                d -= sum(oo) / len(oo)
            out[t][area] = (o, d)
    return out


# ------------------------------------------------------------------ college da CollegeFootballData
def _g(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    try:
        return float(d) if d is not None else None
    except (TypeError, ValueError):
        return None


def college_team_stats(sp: list, adv: list) -> dict:
    """SP+ (/ratings/sp) e statistiche avanzate (/stats/season/advanced) -> {squadra: {area: (off, def)}}.
    SP+ difesa: valori più alti = difesa peggiore, già orientati come serve."""
    out: dict[str, dict] = {}
    for r in sp or []:
        t = r.get("team")
        if not t or t == "nationalAverages":
            continue
        o, d = r.get("offense") or {}, r.get("defense") or {}
        out[t] = {"corse": (_g(o, "rushing"), _g(d, "rushing")),
                  "passaggi": (_g(o, "passing"), _g(d, "passing")),
                  "esplosive": (_g(o, "explosiveness"), _g(d, "explosiveness")),
                  "pressione": (None, None), "zona_rossa": (None, None),
                  "_ritmo": _g(o, "pace"), "_partite": None}
    for r in adv or []:
        t = r.get("team")
        if not t:
            continue
        v = out.setdefault(t, {a: (None, None) for a in AREE} | {"_ritmo": None, "_partite": None})
        o, d = r.get("offense") or {}, r.get("defense") or {}
        v["pressione"] = (_neg(_g(o, "havoc", "total")), _neg(_g(d, "havoc", "total")))
        v["zona_rossa"] = (_g(o, "pointsPerOpportunity"), _g(d, "pointsPerOpportunity"))
        if v.get("_ritmo") is None:
            v["_ritmo"] = _g(o, "plays")
        if v["corse"] == (None, None):
            v["corse"] = (_g(o, "rushingPlays", "ppa"), _g(d, "rushingPlays", "ppa"))
        if v["passaggi"] == (None, None):
            v["passaggi"] = (_g(o, "passingPlays", "ppa"), _g(d, "passingPlays", "ppa"))
    return out


# ------------------------------------------------------------------ classifiche e incroci
def ranks(stats: dict) -> dict:
    """{area: {squadra: (rank attacco, rank difesa, n)}}; difesa 1 = la migliore (concede meno)."""
    out = {}
    for area in AREE + ("_ritmo",):
        if area == "_ritmo":
            vals = {t: v.get("_ritmo") for t, v in stats.items() if v.get("_ritmo") is not None}
            order = sorted(vals, key=lambda t: -vals[t])
            out[area] = {t: (i + 1, None, len(order)) for i, t in enumerate(order)}
            continue
        offs = {t: v[area][0] for t, v in stats.items() if v.get(area) and v[area][0] is not None}
        defs = {t: v[area][1] for t, v in stats.items() if v.get(area) and v[area][1] is not None}
        ro = _rank({t: -x for t, x in offs.items()})
        rd = _rank(defs)
        n = max(len(ro), len(rd))
        out[area] = {t: (ro.get(t), rd.get(t), n) for t in set(ro) | set(rd)}
    return out


def _rank(vals: dict) -> dict:
    """Posizione 1 = valore più basso; a pari merito la posizione media (valori tutti uguali: tutti a metà)."""
    out = {}
    for t, v in vals.items():
        meglio = sum(1 for x in vals.values() if x < v - 1e-12)
        pari = sum(1 for x in vals.values() if abs(x - v) <= 1e-12)
        out[t] = round(meglio + (pari + 1) / 2)
    return out


def score(ro: int | None, rd: int | None, n: int) -> float | None:
    if not ro or not rd or n < 2:
        return None
    return (1 - (ro - 1) / (n - 1)) + (rd - 1) / (n - 1) - 1


def matchup(rk: dict, home: str, away: str) -> list[dict]:
    """Incroci con |punteggio| ≥ SOGLIA, dal più netto. Ogni voce: area, att, dif, punteggio, ranghi."""
    out = []
    for area in AREE:
        r = rk.get(area) or {}
        for att, dif in ((home, away), (away, home)):
            if att not in r or dif not in r:
                continue
            ro, _, n = r[att]
            _, rd, _ = r[dif]
            s = score(ro, rd, n)
            if s is not None and abs(s) >= SOGLIA:
                out.append({"area": area, "att": att, "dif": dif, "score": s, "ro": ro, "rd": rd, "n": n})
    out.sort(key=lambda x: -abs(x["score"]))
    return out


DIREZIONE = {
    ("corse", 1): "yard di corsa del RB di {att}, over di squadra {att}",
    ("corse", -1): "under di squadra {att}, poche yard di corsa {att}",
    ("passaggi", 1): "yard lanciate del QB di {att} e dei suoi ricevitori",
    ("passaggi", -1): "under yard lanciate QB {att}, under di squadra {att}",
    ("pressione", 1): "QB di {att} protetto: yard lanciate {att}",
    ("pressione", -1): "sack della difesa {dif}, under di squadra {att}",
    ("esplosive", 1): "giocate lunghe {att}: over, touchdown lunghi",
    ("esplosive", -1): "pochi big play {att}: under",
    ("zona_rossa", 1): "touchdown di {att} (non field goal), over di squadra {att}",
    ("zona_rossa", -1): "field goal più che touchdown per {att}: under di squadra {att}",
}
GRUPPI_ATT = {"corse": ("OL", "RB"), "passaggi": ("OL", "RIC"), "pressione": ("OL",), "esplosive": ("RIC", "RB"),
              "zona_rossa": ("OL", "RIC", "RB")}
GRUPPI_DIF = {"corse": ("DL", "LB"), "passaggi": ("DB", "LB"), "pressione": ("DL", "LB"), "esplosive": ("DB",),
              "zona_rossa": ("DL", "LB", "DB")}


def describe(sig: dict, nome) -> str:
    """Una riga: '• Corse — attacco KC 3° contro difesa LV 30ª su 32 (+0,87)'."""
    forza = "squilibrio forte" if abs(sig["score"]) >= FORTE else "squilibrio"
    verso = "a favore dell'attacco" if sig["score"] > 0 else "a favore della difesa"
    return (f"<b>{NOMI[sig['area']]}</b> — {forza} {verso}: attacco {nome(sig['att'])} {sig['ro']}° "
            f"contro difesa {nome(sig['dif'])} {sig['rd']}ª su {sig['n']} ({sig['score']:+.2f})")


def hint(sig: dict, nome) -> str:
    k = (sig["area"], 1 if sig["score"] > 0 else -1)
    return DIREZIONE[k].format(att=nome(sig["att"]), dif=nome(sig["dif"]))


def both_defenses(sigs: list[dict]) -> list[str]:
    """Aree dove entrambe le difese sono deboli (o entrambi gli attacchi bloccati): il segnale più netto per il totale."""
    out = []
    for area in AREE:
        s = [x for x in sigs if x["area"] == area]
        if len(s) == 2 and all(x["score"] > 0 for x in s):
            out.append(f"{NOMI[area]}: squilibrio a favore di entrambi gli attacchi → spinge verso l'over")
        elif len(s) == 2 and all(x["score"] < 0 for x in s):
            out.append(f"{NOMI[area]}: entrambi gli attacchi in difficoltà → spinge verso l'under")
    return out


def full_table(rk: dict, home: str, away: str, nome) -> list[str]:
    """Tutte le aree nei due versi, anche sotto soglia: '✅' sui segnali."""
    out = []
    for area in AREE:
        r = rk.get(area) or {}
        parti = []
        for att, dif in ((away, home), (home, away)):
            if att not in r or dif not in r:
                continue
            ro, _, n = r[att]
            _, rd, _ = r[dif]
            s = score(ro, rd, n)
            if s is None:
                continue
            seg = "✅ " if abs(s) >= SOGLIA else ""
            parti.append(f"{seg}att. {nome(att)} {ro}° vs dif. {nome(dif)} {rd}ª ({s:+.2f})")
        if parti:
            out.append(f"<b>{NOMI[area]}</b>: " + " · ".join(parti))
    return out


def pace_note(rk: dict, home: str, away: str) -> str | None:
    r = rk.get("_ritmo") or {}
    if home not in r or away not in r:
        return None
    n = r[home][2]
    m = (r[home][0] + r[away][0]) / 2
    if m <= n / 3:
        return f"ritmo alto: entrambe tra le squadre con più azioni (media {m:.0f}ª su {n}) → più occasioni"
    if m >= 2 * n / 3:
        return f"ritmo basso: poche azioni (media {m:.0f}ª su {n}) → meno occasioni, frena l'over"
    return None
