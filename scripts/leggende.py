"""Leggende di PureStats (NFL): record di carriera, «I più grandi», dinastie.

Fonti: Wikipedia (testo delle voci, CC BY-SA: citata in pagina con il collegamento) per le carriere complete, anche
prima del 1999; nflverse (CC-BY 4.0) per verificare e aggiornare i giocatori della sua epoca (dal 1999).
Niente Pro Football Reference (vieta la raccolta).

Comandi:
  python scripts/leggende.py aggiorna                 scarica le voci Wikipedia e le statistiche nflverse, poi costruisce
  python scripts/leggende.py costruisci <cartella>    costruisce da voci già scaricate (file <voce>.json con «wikitext»)

Uscita: docs/leggende/leggende.json. Ogni record porta la data di aggiornamento della voce («Through Week N»);
per i giocatori dal 1999 il numero viene confrontato con nflverse: i giocatori in attività prendono il valore nflverse
(più fresco), per i ritirati una differenza viene scritta nel registro e segnata nel file.
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
USCITA = RADICE / "docs" / "leggende" / "leggende.json"
CARTELLA_WIKI = RADICE / "data" / "leggende_wiki"          # in .gitignore: si riscarica a ogni giro
CARTELLA_NFLVERSE = RADICE / "data" / "leggende_nflverse"  # in .gitignore
UA = {"User-Agent": "PureStats/1.0 (https://doubleuptip.github.io/purestats/; statistiche sportive)"}
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"
PRIMA_STAGIONE_NFLVERSE = 1999
QUANTI = 10

VOCI = {
    "passaggi_yard": "List of NFL career passing yards leaders",
    "passaggi_td": "List of NFL career passing touchdowns leaders",
    "corse_yard": "List of NFL career rushing yards leaders",
    "corse_td": "List of NFL career rushing touchdowns leaders",
    "ricezioni_yard": "List of NFL career receiving yards leaders",
    "ricezioni": "List of NFL career receptions leaders",
    "ricezioni_td": "List of NFL career receiving touchdowns leaders",
    "sack": "List of NFL career sacks leaders",
    "intercetti": "List of NFL career interceptions leaders",
    "allenatori": "List of NFL head coach wins leaders",
    "centenario": "National Football League 100th Anniversary All-Time Team",
    "super_bowl": "List of Super Bowl champions",
}

# Che cosa misura ogni classifica: titolo, colonna del valore nella voce, colonna nflverse per la verifica
CLASSIFICHE = {
    "passaggi_yard": ("Yard lanciate", ("Yds", "Yards"), "passing_yards"),
    "passaggi_td": ("Touchdown lanciati", ("TDs", "Touchdowns", "TD"), "passing_tds"),
    "corse_yard": ("Yard di corsa", ("Yards", "Yds"), "rushing_yards"),
    "corse_td": ("Touchdown di corsa", ("Touchdowns", "TDs"), "rushing_tds"),
    "ricezioni_yard": ("Yard ricevute", ("Yards", "Yds"), "receiving_yards"),
    "ricezioni": ("Ricezioni", ("Receptions",), "receptions"),
    "ricezioni_td": ("Touchdown su ricezione", ("Touchdowns", "TDs"), "receiving_tds"),
    "sack": ("Sack (ufficiali dal 1982)", ("Sacks",), "def_sacks"),
    "intercetti": ("Intercetti", ("Ints", "Interceptions"), "def_interceptions"),
    "allenatori": ("Vittorie in stagione regolare", ("Career wins", "Wins"), None),
}

RUOLI_RECORD = {
    "QB": ["passaggi_yard", "passaggi_td"],
    "RB": ["corse_yard", "corse_td"],
    "WR": ["ricezioni_yard", "ricezioni", "ricezioni_td"],
    "TE": ["ricezioni_yard", "ricezioni", "ricezioni_td"],   # le stesse classifiche, solo i tight end
    "DIF": ["sack", "intercetti"],
    "ALL": ["allenatori"],
}

# Dinastie: finestre e protagonisti scelti da noi (dichiarati in pagina); titoli e finali dalla voce dei Super Bowl
DINASTIE = [
    {"id": "dolphins72", "nome": "I Dolphins di Shula", "squadra": "MIA", "franchigia": "Miami Dolphins",
     "dal": 1971, "al": 1973, "allenatore": "Don Shula", "qb": "Bob Griese",
     "nota": "Nel 1972 l'unica stagione perfetta della storia NFL: 17 vittorie e nessuna sconfitta."},
    {"id": "steelers70", "nome": "Gli Steelers degli anni '70", "squadra": "PIT", "franchigia": "Pittsburgh Steelers",
     "dal": 1974, "al": 1979, "allenatore": "Chuck Noll", "qb": "Terry Bradshaw",
     "nota": "Quattro Super Bowl in sei stagioni con la difesa «Steel Curtain»."},
    {"id": "49ers80", "nome": "I 49ers di Walsh e Montana", "squadra": "SF", "franchigia": "San Francisco 49ers",
     "dal": 1981, "al": 1994, "allenatore": "Bill Walsh, poi George Seifert", "qb": "Joe Montana, poi Steve Young",
     "nota": "Cinque Super Bowl e nessuna finale persa."},
    {"id": "cowboys90", "nome": "I Cowboys degli anni '90", "squadra": "DAL", "franchigia": "Dallas Cowboys",
     "dal": 1992, "al": 1995, "allenatore": "Jimmy Johnson, poi Barry Switzer", "qb": "Troy Aikman",
     "nota": "Tre Super Bowl in quattro stagioni con Aikman, Emmitt Smith e Michael Irvin."},
    {"id": "patriots", "nome": "I Patriots di Belichick e Brady", "squadra": "NE", "franchigia": "New England Patriots",
     "dal": 2001, "al": 2019, "allenatore": "Bill Belichick", "qb": "Tom Brady",
     "nota": "Diciannove stagioni insieme: sei Super Bowl vinti e nove finali."},
]

ONORI = [  # (chiave, espressione sulla riga degli onori della voce del centenario)
    ("superBowl", r"Super Bowl champion"),
    ("campionatiNfl", r"(?<!AA)(?<!A)NFL champion"),
    ("campionatiAfl", r"AFL champion"),
    ("campionatiAafc", r"AAFC champion"),
    ("mvp", r"(?<!Super Bowl )(?<!Pro Bowl )(?:Most Valuable Player|MVP)"),
    ("superBowlMvp", r"Super Bowl MVP"),
    ("allPro", r"First-team All-(?:Pro|AFL|AAFC)"),
    ("proBowl", r"Pro Bowl(?:er)?|AFL All-Star|NFL All-Star"),
    ("difensoreAnno", r"Defensive Player of the Year"),
    ("attaccanteAnno", r"Offensive Player of the Year"),
    ("allenatoreAnno", r"AP NFL Coach of the Year"),
]


# ---------------------------------------------------------------- scaricamento

def _scarica(url: str, tentativi: int = 3) -> bytes:
    for t in range(tentativi):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                return r.read()
        except Exception as e:
            if t == tentativi - 1:
                raise
            print(f"  {url}: {e!r}, riprovo")
            time.sleep(5)


def scarica_wiki(cartella: Path) -> None:
    cartella.mkdir(parents=True, exist_ok=True)
    for chiave, voce in VOCI.items():
        q = urllib.parse.urlencode({"action": "parse", "page": voce, "prop": "wikitext|revid", "format": "json", "redirects": 1})
        d = json.loads(_scarica("https://en.wikipedia.org/w/api.php?" + q))
        if "parse" not in d:
            raise SystemExit(f"Wikipedia non ha restituito la voce «{voce}»: {d.get('error')}")
        titolo = d["parse"]["title"]
        (cartella / f"{chiave}.json").write_text(json.dumps({
            "voce": voce, "titolo": titolo, "revisione": d["parse"].get("revid"), "wikitext": d["parse"]["wikitext"]["*"],
            "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(titolo.replace(" ", "_"))}, ensure_ascii=False))
        print(f"voce «{titolo}» scaricata")
        time.sleep(1)


def scarica_nflverse(cartella: Path, ultima: int) -> None:
    cartella.mkdir(parents=True, exist_ok=True)
    for s in range(PRIMA_STAGIONE_NFLVERSE, ultima + 1):
        f = cartella / f"stats_player_reg_{s}.csv"
        if f.exists() and s < ultima:
            continue  # stagioni concluse: si scaricano una volta
        try:
            f.write_bytes(_scarica(f"{NFLVERSE}/stats_player/stats_player_reg_{s}.csv"))
        except Exception as e:
            print(f"nflverse stagione {s} non scaricata ({e!r}): i giocatori di quella stagione non si verificano")
    f = cartella / "players.csv"
    f.write_bytes(_scarica(f"{NFLVERSE}/players/players.csv"))


# ---------------------------------------------------------------- lettura delle tabelle di Wikipedia

def _pulisci(c: str) -> str:
    c = re.sub(r"<ref[^>]*/>", "", c)
    c = re.sub(r"<ref[^>]*>.*?</ref>", "", c, flags=re.S)
    c = re.sub(r"<!--.*?-->", "", c, flags=re.S)
    c = re.sub(r"<br\s*/?>", "; ", c, flags=re.I)
    c = re.sub(r"\{\{sort ?name\|([^|}]*)\|([^|}]*)(\|[^}]*)?\}\}", r"\1 \2", c, flags=re.I)
    c = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", c, flags=re.I)
    c = re.sub(r"\{\{(dagger|double-dagger)[^}]*\}\}", lambda m: "†" if m.group(1).lower() == "dagger" else "‡", c, flags=re.I)
    # template con anni (NFL year, nfly, ...): restano gli anni
    for _ in range(3):
        c = re.sub(r"\{\{(?:NFL ?year|nfly|nfl season|AFL year)\|(\d{4})\|(\d{4}|present)[^{}]*\}\}", r"\1–\2", c, flags=re.I)
        c = re.sub(r"\{\{(?:NFL ?year|nfly|nfl season|AFL year)\|(\d{4})[^{}]*\}\}", r"\1", c, flags=re.I)
        c = re.sub(r"\{\{(?:tooltip|abbr)\|([^|}]*)\|[^{}]*\}\}", r"\1", c, flags=re.I)
        c = re.sub(r"\{\{sort\|[^|{}]*\|([^{}]*)\}\}", r"\1", c, flags=re.I)
        c = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", c)
        c = re.sub(r"\{\{[^{}]*\}\}", "", c)
    c = re.sub(r"'''?", "", c)
    c = re.sub(r"<[^>]+>", "", c)
    c = re.sub(r"\b\d+px\b", "", c)
    return re.sub(r"\s+", " ", html.unescape(c)).strip(" ;")


def _attributi(cella: str) -> tuple[str, str]:
    """«rowspan=2 style=... | testo» → (attributi, testo); i | dentro [[ ]] e {{ }} non contano."""
    prof = 0
    for i, ch in enumerate(cella):
        if ch in "[{":
            prof += 1
        elif ch in "]}":
            prof -= 1
        elif ch == "|" and prof == 0 and not cella[i + 1:i + 2] == "|":
            if "=" in cella[:i] or not cella[:i].strip():
                return cella[:i], cella[i + 1:]
            return "", cella
    return "", cella


def _tabelle(w: str) -> list[str]:
    out, i = [], 0
    while (a := w.find("{|", i)) >= 0:
        b = w.find("\n|}", a)
        if b < 0:
            break
        out.append(w[a:b])
        i = b + 3
    return out


def _righe(t: str) -> tuple[list[str], list[list[dict]]]:
    """Intestazione e righe di una tabella; ogni cella è {"t": testo, "a": attributi} con i rowspan già distribuiti."""
    blocchi = re.split(r"\n\|-[^\n]*", t)
    intestazione, dati, sospese = [], [], {}
    for bl in blocchi[1:]:
        celle = []
        for riga in bl.split("\n"):
            riga = riga.rstrip()
            if not riga or riga.startswith(("|+", "|}")):
                continue
            if riga[0] not in "|!":
                if celle:
                    celle[-1] = (celle[-1][0], celle[-1][1] + " " + riga)
                continue
            for pezzo in re.split(r"\|\||!!", riga[1:]):
                celle.append((riga[0], pezzo))
        if not celle:
            continue
        if all(tipo == "!" for tipo, _ in celle) and not dati and not intestazione:
            intestazione = [_pulisci(_attributi(p)[1]) for _, p in celle]
            continue
        riga, col, k = [], 0, 0
        while k < len(celle) or col in sospese:
            if col in sospese:
                v, n = sospese[col]
                riga.append(v)
                if n > 1:
                    sospese[col] = (v, n - 1)
                else:
                    del sospese[col]
                col += 1
                continue
            att, testo = _attributi(celle[k][1])
            k += 1
            v = {"t": _pulisci(testo), "a": att, "grezzo": testo}
            m = re.search(r"rowspan\s*=\s*\"?(\d+)", att)
            if m and int(m.group(1)) > 1:
                sospese[col] = (v, int(m.group(1)) - 1)
            riga.append(v)
            col += 1
        dati.append(riga)
    return intestazione, dati


def _legenda(w: str) -> dict:
    """Simboli della voce: quale segna la Hall of Fame e quale i giocatori in attività."""
    simboli = {"hof": set(), "attivo": set()}
    testo = _pulisci(w[:6000]) + " " + _pulisci(w)
    for s in ["†", "‡", "^", "*", "#", "+", "§"]:
        e = re.escape(s)
        if re.search(e + r"\s*(?:\||:|–|-|=)?\s*(?:Inducted into the |Elected to the |Member of the |Denotes (?:a )?(?:member of the |player inducted into the )?)?Pro Football Hall of Fame", testo):
            simboli["hof"].add(s)
        if re.search(e + r"\s*(?:\||:|–|-|=)?\s*(?:Denotes (?:a )?player who is still )?[Aa]ctive", testo):
            simboli["attivo"].add(s)
    return simboli


def _numero(t: str) -> float | None:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", t or "")
    return float(m.group(0).replace(",", "")) if m else None


def _norm(nome: str) -> str:
    nome = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    nome = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", nome.lower())
    return re.sub(r"[^a-z]", "", nome)


def classifica(voce: dict, chiave: str) -> dict:
    """Le prime righe della tabella principale (Rank, giocatore, valore), con squadre e simboli."""
    w = voce["wikitext"]
    leg = _legenda(w)
    titolo, colonne_valore, _ = CLASSIFICHE[chiave]
    righe, intest = [], None
    for t in _tabelle(w):
        cap, dati = _righe(t)
        if chiave == "allenatori" and not cap and dati and dati[-1] and dati[-1][0]["t"] == "Rank":
            cap = [c["t"] for c in dati[-1]]
            dati = dati[:-1]
        if not cap or cap[0] != "Rank":
            continue
        primo = _numero(dati[0][0]["t"]) if dati and dati[0] else None
        if intest is None and primo == 1:
            intest = cap
        elif intest and righe and primo is not None and primo > righe[-1]["pos"]:
            pass  # la stessa classifica continua in un'altra tabella (es. ricezioni oltre il 18° posto)
        else:
            if intest:
                break
            continue
        for r in dati:
            if len(r) < len(cap) - 1:
                continue
            cel = dict(zip(cap, r))
            pos = _numero(cel["Rank"]["t"])
            if pos is None:
                continue
            nome_c = cel.get("Player") or cel.get("Coach")
            val_c = next((cel[c] for c in colonne_valore if c in cel), None)
            if not nome_c or not val_c or _numero(val_c["t"]) is None:
                continue
            grezzo = nome_c["t"]
            stile = (nome_c["a"] + " " + cel["Rank"]["a"]).lower()
            simboli = set(re.findall(r"[†‡^*#+§]", grezzo))
            nome = re.sub(r"[†‡^*#+§]", "", grezzo).strip()
            squadra_c = next((cel[c] for c in cel if c.startswith(("Team", "Seasons by team"))), None)
            ruolo_c = cel.get("Position") or cel.get("Pos.")
            if righe and righe[-1]["nome"] == nome and righe[-1]["pos"] == pos:
                if squadra_c and squadra_c["t"] not in righe[-1]["squadre"]:
                    righe[-1]["squadre"].append(squadra_c["t"])
                continue
            righe.append({
                "pos": int(pos), "nome": nome, "valore": _numero(val_c["t"]),
                "squadre": [squadra_c["t"]] if squadra_c else [],
                "ruolo": ruolo_c["t"] if ruolo_c else "",
                "hof": bool(simboli & leg["hof"]) or "ffff99" in stile,
                "attivo": bool(simboli & leg["attivo"]) or "cfecec" in stile,
            })
        if intest is None:
            continue
    m = re.search(r"''(?:Updated )?([Tt]hrough[^'\n]*|[Aa]s of[^'\n]*)''", w)
    aggiornata = _pulisci(m.group(1)) if m else ""
    return {"chiave": chiave, "titolo": titolo, "righe": righe, "aggiornataWiki": aggiornata,
            "fonte": {"titolo": voce["titolo"], "url": voce["url"]}}


# ---------------------------------------------------------------- verifica con nflverse

def carica_nflverse(cartella: Path) -> tuple[dict, dict, int]:
    """Totali di carriera in stagione regolare dal 1999 per giocatore (nome normalizzato) e prima stagione nota."""
    totali, ultima = {}, 0
    for f in sorted(cartella.glob("stats_player_reg_*.csv")):
        s = int(re.search(r"(\d{4})", f.name).group(1))
        ultima = max(ultima, s)
        for r in csv.DictReader(io.StringIO(f.read_text())):
            k = (_norm(r["player_display_name"]), r["player_id"])
            t = totali.setdefault(k, {"nome": r["player_display_name"], "stagioni": set(), "ruolo": r["position"]})
            t["stagioni"].add(s)
            for col in ("passing_yards", "passing_tds", "rushing_yards", "rushing_tds", "receiving_yards",
                        "receptions", "receiving_tds", "def_sacks", "def_interceptions"):
                try:
                    t[col] = t.get(col, 0) + float(r.get(col) or 0)
                except ValueError:
                    pass
    debutti = {}
    pf = cartella / "players.csv"
    if pf.exists():
        for r in csv.DictReader(io.StringIO(pf.read_text())):
            debutti.setdefault(_norm(r["display_name"]), []).append(
                {"id": r["gsis_id"], "ruolo": r["position"], "debutto": int(r["rookie_season"] or 0) or None,
                 "ultima": int(r["last_season"] or 0) or None})
    return totali, debutti, ultima


def verifica(cl: dict, totali: dict, debutti: dict, ultima: int) -> None:
    col = CLASSIFICHE[cl["chiave"]][2]
    if not col:
        return
    for r in cl["righe"]:
        n = _norm(r["nome"])
        cand = [v for (k, _), v in totali.items() if k == n and col in v]
        if len(cand) != 1:
            continue
        t = cand[0]
        info = [d for d in debutti.get(n, []) if d["id"]]
        debutto = min((d["debutto"] for d in info if d["debutto"]), default=None)
        if not debutto or debutto < PRIMA_STAGIONE_NFLVERSE:
            continue  # carriera iniziata prima del 1999: nflverse ne ha solo una parte
        valore = round(t[col], 1)
        # I numeri ufficiali (Elias, ripresi da Wikipedia) e quelli ricostruiti azione per azione da nflverse
        # differiscono di poco (correzioni a posteriori): resta il numero ufficiale, nflverse controlla che sia lui.
        scarto = abs(valore - r["valore"])
        if scarto <= max(2, 0.005 * r["valore"]) or (ultima in t["stagioni"] and valore >= r["valore"]):
            r["verifica"] = "nflverse"
        else:
            r["verifica"] = "diversa"
            r["valoreNflverse"] = valore
            print(f"ATTENZIONE {cl['titolo']}: {r['nome']} {r['valore']:g} su Wikipedia, {valore:g} su nflverse: da controllare")


# ---------------------------------------------------------------- «I più grandi»: squadra del centenario NFL

RUOLI_CENTENARIO = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE",
                    "DE": "DIF", "DT": "DIF", "LB": "DIF", "CB": "DIF", "S": "DIF"}


def _conta_onori(testo: str) -> dict:
    out = {}
    for pezzo in re.split(r",\s*(?![^()]*\))", testo):
        pezzo = pezzo.strip()
        for chiave, espr in ONORI:
            if re.search(espr, pezzo):
                m = re.match(r"(\d+)\s*[×x]\s", pezzo)
                out[chiave] = out.get(chiave, 0) + (int(m.group(1)) if m else 1)
                break
    m = re.search(r"Hall of Fame \((\d{4})\)", testo)
    if m:
        out["hof"] = int(m.group(1))
    out["titoli"] = sum(out.get(k, 0) for k in ("superBowl", "campionatiNfl", "campionatiAfl", "campionatiAafc"))
    return out


def centenario(voce: dict) -> dict:
    grandi = {}
    for t in _tabelle(voce["wikitext"]):
        _, dati = _righe(t)
        for r in dati:
            testi = [c["t"] for c in r]
            if len(testi) == 4 and testi[0] in RUOLI_CENTENARIO:
                ruolo, nome, squadre, onori = testi
            elif len(testi) == 3 and re.search(r"Coach of the Year|champion", testi[2]):
                ruolo, (nome, squadre, onori) = "ALL", testi
            else:
                continue
            gr = RUOLI_CENTENARIO.get(ruolo, ruolo)
            grandi.setdefault(gr, []).append({
                "nome": re.sub(r"[†‡^*]", "", nome).strip(), "ruolo": ruolo,
                "squadre": [s.strip() for s in re.findall(r"[^()]+\([^)]*\)", squadre)] or [squadre],
                "onori": _conta_onori(onori)})
    return {"gruppi": grandi, "fonte": {"titolo": voce["titolo"], "url": voce["url"]}}


# ---------------------------------------------------------------- Super Bowl e dinastie

def super_bowl(voce: dict) -> list[dict]:
    w = voce["wikitext"]
    i = w.find("|+ Super Bowl championships")
    tabella = w[i:w.find("\n|}", i)]
    out = []
    for blocco in re.split(r"\n\|-[^\n]*", tabella):
        num = re.search(r"\[\[Super Bowl ([IVXLC]+|50)\|", blocco)
        stag = re.search(r"\[\[(\d{4}) (?:NFL|American Football League) season", blocco)
        squadre = re.findall(r"\{\{Sort\|[^|]*\|\[\[\d{4} ([^|\]]+?) season\|([^\]]+)\]\]", blocco)
        punti = re.findall(r"\n\|\s*(?:'''(\d+)'''|(\d+))\s*(?=\n)", blocco)
        if not (num and stag and len(squadre) >= 2 and len(punti) >= 2):
            continue
        p = [int(a or b) for a, b in punti[:2]]
        out.append({"sb": num.group(1), "stagione": int(stag.group(1)),
                    "vincitrice": squadre[0][1], "franchigiaV": squadre[0][0],
                    "perdente": squadre[1][1], "franchigiaP": squadre[1][0], "punti": p})
    return out


def _stessa_franchigia(nome_stagione: str, franchigia: str) -> bool:
    # le voci di stagione usano il nome dell'epoca («1972 Miami Dolphins season»): basta l'ultimo nome
    return nome_stagione.split()[-1] == franchigia.split()[-1]


def dinastie(finali: list[dict]) -> list[dict]:
    out = []
    for d in DINASTIE:
        partite = [f for f in finali if d["dal"] <= f["stagione"] <= d["al"]
                   and (_stessa_franchigia(f["franchigiaV"], d["franchigia"]) or _stessa_franchigia(f["franchigiaP"], d["franchigia"]))]
        vinte = [f for f in partite if _stessa_franchigia(f["franchigiaV"], d["franchigia"])]
        out.append({**d, "finali": [{"sb": f["sb"], "stagione": f["stagione"],
                                     "vinta": f in vinte,
                                     "avversario": f["perdente"] if f in vinte else f["vincitrice"],
                                     "punteggio": f"{max(f['punti'])}-{min(f['punti'])}" if f in vinte else f"{min(f['punti'])}-{max(f['punti'])}"}
                                    for f in partite],
                    "titoli": len(vinte)})
        print(f"dinastia {d['nome']}: {len(vinte)} Super Bowl vinti su {len(partite)} finali")
    return out


# ---------------------------------------------------------------- costruzione

def costruisci(cartella_wiki: Path, cartella_nflverse: Path) -> None:
    voci = {}
    for chiave, voce in VOCI.items():
        f = cartella_wiki / f"{chiave}.json"
        if not f.exists():  # nomi dei file scaricati dal ramo delle bozze
            f = cartella_wiki / (re.sub(r"[^A-Za-z0-9]+", "_", voce).strip("_") + ".json")
        if not f.exists():
            alt = list(cartella_wiki.glob("*coach*wins*.json")) if chiave == "allenatori" else []
            if not alt:
                raise SystemExit(f"manca la voce «{voce}» in {cartella_wiki}: niente da costruire, il file resta com'era")
            f = alt[0]
        voci[chiave] = json.loads(f.read_text())
    totali, debutti, ultima = carica_nflverse(cartella_nflverse) if cartella_nflverse.exists() else ({}, {}, 0)
    if not totali:
        print("statistiche nflverse assenti: record senza verifica")

    classifiche = {}
    for chiave in CLASSIFICHE:
        cl = classifica(voci[chiave], chiave)
        if len(cl["righe"]) < QUANTI:
            raise SystemExit(f"{cl['titolo']}: solo {len(cl['righe'])} righe lette dalla voce, forse è cambiata la tabella")
        verifica(cl, totali, debutti, ultima)
        cl["righe"].sort(key=lambda r: -r["valore"])
        classifiche[chiave] = cl
        print(f"{cl['titolo']}: {len(cl['righe'])} righe, aggiornata «{cl['aggiornataWiki']}»")

    def ruolo_te(r):
        if r.get("ruolo"):
            return "tight end" in r["ruolo"].lower() or r["ruolo"].upper() == "TE"
        return any(d["ruolo"] == "TE" for d in debutti.get(_norm(r["nome"]), []))

    record = {}
    for ruolo, chiavi in RUOLI_RECORD.items():
        record[ruolo] = []
        for chiave in chiavi:
            cl = classifiche[chiave]
            righe = [r for r in cl["righe"] if ruolo_te(r)] if ruolo == "TE" else cl["righe"]
            righe = [dict(r) for r in righe[:QUANTI]]
            for i, r in enumerate(righe):   # a pari merito stessa posizione
                r["pos"] = righe[i - 1]["pos"] if i and r["valore"] == righe[i - 1]["valore"] else i + 1
            if righe:
                record[ruolo].append({**{k: cl[k] for k in ("chiave", "titolo", "aggiornataWiki", "fonte")},
                                      "righe": righe,
                                      "nota": "tight end tra i primi della classifica di carriera" if ruolo == "TE" else ""})

    grandi = centenario(voci["centenario"])
    finali = super_bowl(voci["super_bowl"])
    if len(finali) < 50:
        raise SystemExit(f"lette solo {len(finali)} finali di Super Bowl dalla voce: il file resta com'era")
    uscita = {
        "aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "record": record,
        "grandi": grandi,
        "dinastie": dinastie(finali),
        "superBowl": finali,
        "fonti": [{"titolo": v["titolo"], "url": v["url"]} for v in voci.values()],
        "licenze": "Testi e numeri da Wikipedia (CC BY-SA 4.0); verifiche dal 1999 con nflverse (CC-BY 4.0).",
    }
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    USCITA.write_text(json.dumps(uscita, ensure_ascii=False, indent=1))
    print(f"scritto {USCITA.relative_to(RADICE)}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "aggiorna":
        scarica_wiki(CARTELLA_WIKI)
        scarica_nflverse(CARTELLA_NFLVERSE, dt.date.today().year if dt.date.today().month >= 9 else dt.date.today().year - 1)
        costruisci(CARTELLA_WIKI, CARTELLA_NFLVERSE)
    elif len(sys.argv) >= 3 and sys.argv[1] == "costruisci":
        costruisci(Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) >= 4 else CARTELLA_NFLVERSE)
    else:
        print(__doc__)
