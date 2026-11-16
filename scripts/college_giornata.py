"""
Blocchi della sezione Giornata college, dai dati della partita ESPN (summary) che scarichiamo già per i
tabellini: nessuna richiesta in più. cfbfastR arriva circa una settimana dopo, ESPN subito.

Per ogni partita (`riassunto_partita`, salvato nell'archivio dei tabellini alla voce «azioni»):
- le azioni che hanno spostato di più la probabilità di vittoria (ESPN «winprobability»), d'attacco e di difesa;
- le flag di ogni squadra (boxscore: «totalPenaltiesYards», es. «8-45»);
- i punti negli ultimi 2 minuti di ogni tempo (nel college il two-minute warning non c'è, i 2 minuti sì);
- yard e azioni di ogni squadra (per le yard per azione corrette per l'avversario).

`blocchi` mette insieme la settimana (giocate e squadre) e la stagione (2 minuti e flag) nella stessa forma
dei blocchi NFL, così la pagina li mostra con lo stesso codice. Solo libreria standard.
"""

import re
from collections import defaultdict

VERSIONE = 3                       # cambia quando cambia il calcolo: le partite si rileggono da sole
GIOCATE_PER_PARTITA = 4
GIOCATE = 5
FINESTRA = 120

ATTACCO = {"Rush", "Pass Reception", "Passing Touchdown", "Rushing Touchdown", "Pass", "Pass Completion"}
DIFESA = {"Sack": "sack", "Pass Interception Return": "intercetto", "Interception Return Touchdown": "intercetto",
          "Pass Interception": "intercetto", "Fumble Recovery (Opponent)": "fumble recuperato",
          "Fumble Return Touchdown": "fumble recuperato", "Safety": "safety"}


def _sec(clock: str) -> int | None:
    try:
        m, s = str(clock).split(":")
        return int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return None


def _due_numeri(x: str):
    """«8-45» -> (8, 45); «20-30» -> (20, 30)."""
    m = re.match(r"\s*(\d+)\s*[-/]\s*(-?\d+)", str(x or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


# ------------------------------------------------------------------ testo in italiano
DIR = {"left": "a sinistra", "middle": "al centro", "right": "a destra"}
LUNG = {"short": "corto", "deep": "lungo"}


def _pulisci(t: str) -> str:
    """Toglie orario, formazione, numeri di maglia, placcatori, calci e posizioni sul campo."""
    t = t or ""
    t = re.sub(r"^\(\d+:\d+\)\s*", "", t)
    t = re.sub(r"^(?:No Huddle-Shotgun|No Huddle|Shotgun|Pistol|Under Center)\s+", "", t)
    t = re.sub(r"#\d+\s*", "", t)
    t = re.sub(r"\s*\([^)]*\)", "", t)                       # placcatori, calcio dell'extra point
    t = re.sub(r",?\s*clock \d+:\d+.*$", "", t)
    t = re.sub(r"\s+caught at [A-Za-z]+\s?\d+,?", "", t)
    t = re.sub(r"\s+to the [A-Za-z']+\s?\d+", "", t)
    t = re.sub(r",?\s*(?:1ST DOWN|out of bounds at [A-Za-z]+\s?\d+).*$", "", t)
    return re.sub(r"\s+", " ", t).strip().rstrip(",.")


def traduci(testo: str) -> str:
    """Le forme più comuni del testo ESPN college (vecchia e nuova); altrimenti il testo ripulito."""
    td = bool(re.search(r"for a TD|TOUCHDOWN|\d+ Yd (?:pass|Run|Interception Return|Fumble Return)", testo or ""))
    t = _pulisci(testo)
    fine = ": touchdown" if td else ""
    m = re.match(r"(.+?) (\d+) Yd pass from (.+)", t)
    if m:
        return f"{m.group(3)} lancia per {m.group(1)}, {m.group(2)} yard: touchdown"
    m = re.match(r"(.+?) (\d+) Yd Run", t)
    if m:
        return f"{m.group(1)} corre, {m.group(2)} yard: touchdown"
    m = re.match(r"(.+?) (\d+) Yd Interception Return", t)
    if m:
        return f"Intercetto di {m.group(1)} riportato per {m.group(2)} yard: touchdown"
    m = re.match(r"(.+?) (\d+) Yd Fumble Return", t)
    if m:
        return f"Fumble riportato da {m.group(1)} per {m.group(2)} yard: touchdown"
    m = re.match(r"(.+?) pass complete (short|deep) (left|middle|right) to (.+?),? for (-?\d+) yards?", t)
    if m:
        return f"{m.group(1)} lancia {LUNG[m.group(2)]} {DIR[m.group(3)]} per {m.group(4)}, {m.group(5)} yard{fine}"
    m = re.match(r"(.+?) pass complete to (.+?),? for (-?\d+) y(?:ar)?ds?", t)
    if m:
        return f"{m.group(1)} lancia per {m.group(2)}, {m.group(3)} yard{fine}"
    m = re.match(r"(.+?) rush (left|middle|right) for (\d+) yards?(?: (gain|loss))?", t)
    if m:
        y = "−" + m.group(3) if m.group(4) == "loss" and m.group(3) != "0" else m.group(3)
        return f"{m.group(1)} corre {DIR[m.group(2)]}, {y} yard{fine}"
    m = re.match(r"(.+?) (?:run|rush) for (-?\d+) y(?:ar)?ds?", t)
    if m:
        return f"{m.group(1)} corre, {m.group(2)} yard{fine}"
    m = re.match(r"(.+?) (?:run|rush)(?: \w+)? for no gain", t)
    if m:
        return f"{m.group(1)} corre, nessun guadagno"
    m = re.match(r"(.+?) sacked by (.+?) for (?:a )?loss of (\d+) y", t)
    if m:
        return f"{m.group(1)} subisce un sack da {m.group(2)}, −{m.group(3)} yard"
    m = re.match(r"(.+?) sacked for (?:a )?loss of (\d+) y", t)
    if m:
        return f"{m.group(1)} subisce un sack, −{m.group(2)} yard"
    m = re.match(r"(.+?) pass (?:\w+ \w+ )?intercepted(?: by)? (.+?)(?: at| return| for|,|$)", t, re.I)
    if m:
        return f"{m.group(1)} intercettato da {m.group(2).strip()}{fine}"
    m = re.match(r"(.+?) pass incomplete(?: (short|deep) (left|middle|right))?(?: to (.+))?", t)
    if m:
        return f"{m.group(1)}: lancio incompleto" + (f" per {m.group(4)}" if m.group(4) else "")
    return t[:200]


# ------------------------------------------------------------------ una partita
def riassunto_partita(d: dict) -> dict | None:
    """Dal summary ESPN di una partita il riassunto compatto per la Giornata. None se non ci sono le azioni."""
    nomi = {}
    for t in ((d.get("boxscore") or {}).get("teams") or []):
        tm = t.get("team") or {}
        if tm.get("id"):
            nomi[str(tm["id"])] = (tm.get("location") or tm.get("displayName") or "").strip()
    casa_id = ospite_id = None
    for c in (((d.get("header") or {}).get("competitions") or [{}])[0].get("competitors") or []):
        tid = str((c.get("team") or {}).get("id") or c.get("id") or "")
        if c.get("homeAway") == "home":
            casa_id = tid
        elif c.get("homeAway") == "away":
            ospite_id = tid
        if tid and tid not in nomi:
            nomi[tid] = ((c.get("team") or {}).get("location") or "").strip()
    out = {"v": VERSIONE, "flag": {}, "yardAzioni": {}, "due": {}, "giocate": []}
    for t in ((d.get("boxscore") or {}).get("teams") or []):
        nome = nomi.get(str((t.get("team") or {}).get("id") or ""), "")
        st = {s.get("name"): s.get("displayValue") for s in t.get("statistics") or []}
        n, y = _due_numeri(st.get("totalPenaltiesYards"))
        if nome and n is not None:
            out["flag"][nome] = [n, y]
        try:
            yard = int(str(st.get("totalYards") or "").strip())
            corse = int(str(st.get("rushingAttempts") or "").strip())
            _c, tentativi = _due_numeri(st.get("completionAttempts"))
            if nome and tentativi is not None:
                out["yardAzioni"][nome] = [yard, corse + tentativi]
        except ValueError:
            pass
    if not (casa_id and ospite_id):
        return out
    casa, osp = nomi.get(casa_id, ""), nomi.get(ospite_id, "")
    # la probabilità prima di un'azione è quella dell'elemento precedente nella serie ESPN (in ordine di gioco)
    wp, prima_di, ultimo = {}, {}, 0.5
    for x in d.get("winprobability") or []:
        v = x.get("homeWinPercentage")
        if v is None:
            continue
        wp[str(x.get("playId"))], prima_di[str(x.get("playId"))] = v, ultimo
        ultimo = v
    giocate, prec = [], (0, 0)
    due = {casa: [0, 0], osp: [0, 0]}
    for drive in ((d.get("drives") or {}).get("previous") or []):
        for p in drive.get("plays") or []:
            hs, as_ = p.get("homeScore"), p.get("awayScore")
            per = (p.get("period") or {}).get("number")
            sec = _sec((p.get("clock") or {}).get("displayValue"))
            if isinstance(hs, int) and isinstance(as_, int):
                dc, do = hs - prec[0], as_ - prec[1]
                if per in (2, 4) and sec is not None and sec <= FINESTRA:
                    i = 0 if per == 2 else 1
                    if dc > 0:
                        due[casa][i] += dc
                    if do > 0:
                        due[osp][i] += do
                prec = (hs, as_)
            w = wp.get(str(p.get("id")))
            if w is None or not isinstance(per, int) or per > 4:      # supplementari: probabilità ESPN instabile
                continue
            prima = prima_di[str(p.get("id"))]
            att = str(((p.get("start") or {}).get("team") or {}).get("id") or "")
            if att not in (casa_id, ospite_id) or p.get("isPenalty"):
                continue
            tipo = ((p.get("type") or {}).get("text") or "")
            if re.search(r"kickoff|punt|field goal|extra point|timeout|end of", tipo + " " + (p.get("text") or ""), re.I):
                continue
            per_att = (w - prima) if att == casa_id else (prima - w)        # probabilità per chi attacca
            dif_id = ospite_id if att == casa_id else casa_id
            evento = DIFESA.get(tipo)
            if not evento and (p.get("start") or {}).get("down") == 4 and tipo in ATTACCO | {"Pass Incompletion"} \
                    and str(((p.get("end") or {}).get("team") or {}).get("id") or "") == dif_id:
                evento = "stop al quarto down"
            if evento and per_att < 0:
                chi, contro, valore = dif_id, att, -per_att
                pr = (1 - prima) if dif_id == ospite_id else prima
                dp = (1 - w) if dif_id == ospite_id else w
            elif tipo in ATTACCO and per_att > 0 and not p.get("isTurnover"):
                chi, contro, valore, evento = att, dif_id, per_att, ""
                pr = prima if att == casa_id else 1 - prima
                dp = w if att == casa_id else 1 - w
            else:
                continue
            testo = traduci(p.get("text") or "")
            if evento == "fumble recuperato" and "Fumble" not in testo:
                testo += ", fumble perso"
            elif evento == "stop al quarto down" and "quarto down" not in testo:
                testo += ", palla persa al quarto down"
            testo = testo.replace("−0 yard", "nessuna perdita")
            giocate.append({"tipo": "difesa" if evento else "attacco", "squadra": nomi.get(chi, ""),
                            "avversario": nomi.get(contro, ""), "quarto": str(per or ""),
                            "tempo": (p.get("clock") or {}).get("displayValue", ""),
                            "testo": testo, "yard": p.get("statYardage"),
                            "touchdown": bool(p.get("scoringPlay")) and "TD" in (p.get("text") or "").upper(),
                            "evento": evento, "valore": round(valore * 100, 1),
                            "prima": round(pr * 100), "dopo": round(dp * 100)})
    out["due"] = due
    for t in ("attacco", "difesa"):
        out["giocate"] += sorted((g for g in giocate if g["tipo"] == t), key=lambda g: -g["valore"])[:GIOCATE_PER_PARTITA]
    return out


# ------------------------------------------------------------------ settimana e stagione
def blocchi(tabellini: dict, settimana: str, fbs=None) -> dict:
    """tabellini = archivio della stagione {id: {settimana, casa, ospite, azioni, ...}}.
    fbs = insieme delle squadre di prima divisione (le altre restano fuori dalle classifiche)."""
    ok = (lambda s: s in fbs) if fbs else (lambda s: True)
    out = {}
    sett = [v for v in tabellini.values() if str(v.get("settimana")) == str(settimana) and v.get("azioni")]
    gioc = [g for v in sett for g in (v["azioni"].get("giocate") or [])]
    if gioc:
        out["giocate"] = {t: sorted((g for g in gioc if g["tipo"] == t), key=lambda g: -g["valore"])[:GIOCATE]
                          for t in ("attacco", "difesa")}
    # yard per azione: stagione (per correggere) e settimana
    fatte, concesse = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for v in tabellini.values():
        ya = (v.get("azioni") or {}).get("yardAzioni") or {}
        if len(ya) != 2:
            continue
        a, b = list(ya)
        for x, y in ((a, b), (b, a)):
            fatte[x][0] += ya[x][0]
            fatte[x][1] += ya[x][1]
            concesse[y][0] += ya[x][0]
            concesse[y][1] += ya[x][1]
    tot = [sum(v[0] for v in fatte.values()), sum(v[1] for v in fatte.values())]
    media = tot[0] / tot[1] if tot[1] else None
    righe = []
    for v in sett:
        ya = v["azioni"].get("yardAzioni") or {}
        if len(ya) != 2 or media is None:
            continue
        a, b = list(ya)
        for x, y in ((a, b), (b, a)):
            if not ok(x) or not ya[x][1] or not ya[y][1]:
                continue
            fatte_y = fatte[y][0] / fatte[y][1] if fatte[y][1] else media          # attacco avversario, stagione
            conc_y = concesse[y][0] / concesse[y][1] if concesse[y][1] else media  # difesa avversaria, stagione
            att = ya[x][0] / ya[x][1] - conc_y
            dif = fatte_y - ya[y][0] / ya[y][1]
            righe.append({"squadra": x, "nome": x, "avversario": y, "attacco": round(att, 2), "difesa": round(dif, 2),
                          "netto": round(att + dif, 2), "epaAzione": round(ya[x][0] / ya[x][1], 2),
                          "epaConcesso": round(ya[y][0] / ya[y][1], 2)})
    if righe:
        out["squadreSettimana"] = {
            "attacchi": sorted(righe, key=lambda r: -r["attacco"])[:5],
            "difese": sorted(righe, key=lambda r: -r["difesa"])[:5],
            "migliori": sorted(righe, key=lambda r: -r["netto"])[:3],
            "unita": "yard/azione",
            "nota": "Yard per azione rispetto a quelle che l'avversario concede (attacco) o produce (difesa) di "
                    "solito in stagione. Dati ESPN della partita: l'EPA college (cfbfastR) arriva una settimana dopo."}
    # stagione: ultimi 2 minuti e flag
    due = defaultdict(lambda: {"partite": 0, "f1": 0, "f2": 0, "s1": 0, "s2": 0, "punti": 0})
    flag = defaultdict(lambda: {"partite": 0, "flag": 0, "yard": 0, "subite": 0})
    for v in tabellini.values():
        az = v.get("azioni") or {}
        dd = az.get("due") or {}
        if len(dd) == 2:
            a, b = list(dd)
            for x, y in ((a, b), (b, a)):
                due[x]["partite"] += 1
                due[x]["f1"] += dd[x][0]
                due[x]["f2"] += dd[x][1]
                due[x]["s1"] += dd[y][0]
                due[x]["s2"] += dd[y][1]
        fl = az.get("flag") or {}
        if len(fl) == 2:
            a, b = list(fl)
            for x, y in ((a, b), (b, a)):
                flag[x]["partite"] += 1
                flag[x]["flag"] += fl[x][0]
                flag[x]["yard"] += fl[x][1] or 0
                flag[x]["subite"] += fl[y][0]
    # punti totali per la quota: dai punteggi finali dell'archivio non ci sono; si usano i punti in classifica
    r2 = [{"squadra": s, "nome": s, "partite": x["partite"], "fatti1": round(x["f1"] / x["partite"], 2),
           "fatti2": round(x["f2"] / x["partite"], 2), "subiti1": round(x["s1"] / x["partite"], 2),
           "subiti2": round(x["s2"] / x["partite"], 2), "quota": None,
           "netto": round((x["f1"] + x["f2"] - x["s1"] - x["s2"]) / x["partite"], 2)}
          for s, x in due.items() if x["partite"] >= 3 and ok(s)]
    if r2:
        n = sum(r["partite"] for r in r2)
        out["ultimiDueMinuti"] = {
            "squadre": sorted(r2, key=lambda r: -(r["fatti1"] + r["fatti2"])),
            "media": {k: round(sum(r[k] * r["partite"] for r in r2) / n, 2) for k in ("fatti1", "fatti2")},
            "nota": "Punti a partita segnati e subiti negli ultimi 2 minuti del primo e del secondo tempo (nel college "
                    "il two-minute warning non esiste). Sono pochi minuti a partita: come segnale va ancora misurata."}
    rf = [{"squadra": s, "nome": s, "partite": x["partite"], "flag": round(x["flag"] / x["partite"], 2),
           "yard": round(x["yard"] / x["partite"], 1), "subite": round(x["subite"] / x["partite"], 2), "tipi": []}
          for s, x in flag.items() if x["partite"] >= 3 and ok(s)]
    if rf:
        out["flag"] = {"squadre": sorted(rf, key=lambda r: -r["flag"]),
                       "media": round(sum(r["flag"] * r["partite"] for r in rf) / sum(r["partite"] for r in rf), 2),
                       "nota": "Penalità accettate a partita, dal tabellino ESPN. Gli arbitri del college non sono nei dati.",
                       "arbitri": []}
    return out
