"""
College Football — giornata, prossimo turno e indici di forza.

Usato da fetch_college.py, con la stessa forma dei blocchi NFL, così la
dashboard li mostra con le stesse viste:

- giornata: l'ultima settimana giocata, con la linea di chiusura del
  mercato (chi l'ha battuta, over o under), le sorprese più grandi e le
  migliori prestazioni individuali (prese dall'archivio giocatori, senza
  chiamate in più).
- prossima: il turno successivo con linee e totali, e il confronto tra i
  giocatori chiave (QB, RB, 2 ricevitori) preso dall'archivio, con la
  difesa SP+ dell'avversaria. Nessuna chiamata in più.
- indici: SP+ calcolato da CollegeFootballData (attacco, difesa, totale).
  Non si calcola in proprio: nel college le conference si incontrano poco
  e un indice corretto per gli avversari con pochi dati sarebbe fragile;
  SP+ usa l'azione per azione completa, che il piano gratuito non permette
  di scaricare.

Chiamate a CollegeFootballData (dal 14/11/2026): SP+ al massimo una volta ogni 6 giorni
(data/college_sp.json) e 1 a stagione per i loghi (data/college_squadre.json). Le linee arrivano da
ESPN, una richiesta per partita; quelle delle partite finite restano in data/college_linee.json.
Solo libreria standard.
"""

import html
import json
import os
import re
import statistics
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

RADICE = Path(__file__).resolve().parent.parent
SQUADRE = RADICE / "data" / "college_squadre.json"
ARCHIVIO_VIDEO = RADICE / "data" / "college_video.json"
# La chiave YouTube è la stessa della NFL (10.000 unità al giorno, 100 per ricerca, fino a 6.000 per la NFL):
# il college si ferma a 30 ricerche per esecuzione. Le partite trovate restano in archivio e non costano più.
MAX_RICERCHE_VIDEO = 30
# Canali verificati: network e conference che hanno i diritti delle partite. Si confronta il nome del canale.
CANALI_VERIFICATI = ("espn", "espn college football", "cbs sports", "cbs sports college football", "fox sports",
                     "fox college football", "nbc sports", "peacock", "big ten network", "sec network",
                     "acc digital network", "acc network", "big 12 conference", "mountain west",
                     "sun belt conference", "conference usa", "mac sports", "mid american conference",
                     "american athletic conference", "pac 12", "cw sports")


def _linea(gioco):
    """Linea e totale: il consenso se c'è, altrimenti la mediana dei fornitori.
    Restituisce (margine atteso per la casa, totale), con il margine positivo se la casa è favorita."""
    linee = gioco.get("lines") or []
    cons = [l for l in linee if (l.get("provider") or "").lower() == "consensus"]
    scelte = cons or linee
    sp = [l.get("spread") for l in scelte if l.get("spread") is not None]
    ou = [l.get("overUnder") for l in scelte if l.get("overUnder") is not None]
    # CollegeFootballData scrive lo spread dal punto di vista della casa: -7 = casa favorita di 7
    margine = -statistics.median(sp) if sp else None
    return margine, (statistics.median(ou) if ou else None)


def _riga(g):
    margine, totale = _linea(g)
    pc, po = g.get("homeScore"), g.get("awayScore")
    casa, ospite = g.get("homeTeam"), g.get("awayTeam")
    fav = None if margine in (None, 0) else (casa if margine > 0 else ospite)
    chi = tot = scarto = None
    if pc is not None and po is not None and margine is not None:
        d = (pc - po) - margine
        chi = casa if d > 0 else ospite if d < 0 else None
        scarto = round(abs(d), 1)
    if pc is not None and po is not None and totale is not None:
        t = pc + po
        tot = "over" if t > totale else "under" if t < totale else "pari"
    data = (g.get("startDate") or "")[:10]
    hl = None
    if pc is not None and po is not None:
        from urllib.parse import quote_plus
        mesi = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                "October", "November", "December"]
        d = (g.get("startDate") or "")[:10]
        try:
            a, me, gg = (int(x) for x in d.split("-"))
            quando = f"{mesi[me - 1]} {gg}, {a}"
        except ValueError:
            quando = f"{g.get('season')}"
        hl = "https://www.youtube.com/results?search_query=" + quote_plus(
            f"{ospite} vs {casa} football highlights {quando}")
    ora_it = {}
    inizio = g.get("startDate") or ""
    if len(inizio) > 10:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            t = datetime.fromisoformat(inizio.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Rome"))
            ora_it = {"dataIt": t.strftime("%Y-%m-%d"), "oraIt": t.strftime("%H:%M"), "inizio": inizio}
        except (ValueError, KeyError):
            pass
    return {"highlights": hl, "data": data, "ora": "", **ora_it, "casa": casa, "ospite": ospite, "pc": pc, "po": po,
            "favorita": fav, "linea": None if margine is None else abs(margine), "totaleLinea": totale,
            "battutaDa": chi, "totaleEsito": tot, "scartoLinea": scarto, "stadio": "",
            "confCasa": g.get("homeConference"), "confOspite": g.get("awayConference")}


def _prestazioni(ultime, stagione, settimana):
    """Migliori prestazioni della settimana dall'archivio partite (nessuna chiamata)."""
    gruppi = {"QB": [], "RB": [], "RIC": []}
    for p in ultime:
        if str(p.get("stagione")) != str(stagione) or str(p.get("settimana")) != str(settimana):
            continue
        for lato, squadra, avv in (("giocatoriCasa", p["casa"], p["ospite"]), ("giocatoriOspite", p["ospite"], p["casa"])):
            for g in p.get(lato) or []:
                voce = {"nome": g["nome"], "ruolo": g["ruolo"], "squadra": squadra, "avversario": avv,
                        "valore": g["valore"], "dettagli": " · ".join(g.get("dettagli") or [])}
                gruppi["RIC" if g["ruolo"] in ("WR", "TE") else g["ruolo"]].append(voce)
    top = lambda x: sorted(x, key=lambda v: -v["valore"])[:5]
    return {"lanci": top(gruppi.get("QB", [])), "corse": top(gruppi.get("RB", [])), "ricezioni": top(gruppi["RIC"])}


def _prestazioni_complete(ultime, stagione, settimana):
    out = _prestazioni(ultime, stagione, settimana)
    try:
        out.update(_difesa_college(stagione, settimana))
    except Exception as e:      # noqa: BLE001 - la difesa è un di più: i leader d'attacco escono lo stesso
        print(f"  Leader difensivi college non calcolati ({type(e).__name__}: {e})")
    return out


def _difesa_college(stagione, settimana):
    """Leader difensivi della settimana dai tabellini ESPN già in archivio (nessuna chiamata): sack, intercetti,
    placcaggi, passaggi deviati. ESPN non riporta i fumble forzati nel college."""
    from fetch_college import carica_tabellini

    def n(x):
        try:
            return float(str(x).split("/")[-1])
        except ValueError:
            return 0.0
    gioc = {}
    for v in carica_tabellini(int(stagione)).values():
        if str(v.get("settimana")) != str(settimana) or v.get("tipo") != "regular":
            continue
        et = v.get("etichette") or {}
        squadre = list((v.get("squadre") or {}).keys())
        for sq, cats in (v.get("squadre") or {}).items():
            avv = next((x for x in squadre if x != sq), "")
            for cat in ("defensive", "interceptions"):
                lab = et.get(cat) or []
                for r in cats.get(cat) or []:
                    x = gioc.setdefault((sq, r[0]), {"nome": r[1], "squadra": sq, "avversario": avv})
                    for i, l in enumerate(lab):
                        if len(r) > 2 + i:
                            x[cat[:3] + l] = n(r[2 + i])

    def top(col, extra):
        lista = []
        for x in gioc.values():
            v = x.get(col, 0)
            if v > 0:
                fmt = lambda z: (str(int(z)) if float(z).is_integer() else str(z)).replace(".", ",")
                lista.append({"nome": x["nome"], "squadra": x["squadra"], "avversario": x["avversario"],
                              "valore": int(v) if float(v).is_integer() else round(v, 1),
                              "dettagli": " · ".join(f"{fmt(x[c])} {lab}" for c, lab in extra if x.get(c, 0) > 0)})
        return sorted(lista, key=lambda v: -v["valore"])[:5]
    return {"sack": top("defSACKS", (("defQB HUR", "pressioni sul QB"), ("defTFL", "placcaggi con perdita"))),
            "intercetti": top("intINT", (("intYDS", "yard di ritorno"), ("intTD", "TD"), ("defPD", "passaggi deviati"))),
            "placcaggi": top("defTOT", (("defSOLO", "da solo"), ("defTFL", "con perdita"))),
            "deviati": top("defPD", (("intINT", "intercetti"),))}


# QB che corre: sopra questa media di yard di corsa (nette, i sack nel college tolgono yard) il QB ha anche la
# riga delle corse. Misura del 19/11/2026 sui QB titolari 2019-2025: l'effetto della difesa sulle corse c'è già
# tra 15 e 30 yard (17,5 yard dalla difesa migliore alla peggiore, variabilità 30): il 51% dei titolari è sopra.
SOGLIA_CORSE_QB = 15


def _prestazioni_tabellini(stagione):
    """Dai tabellini ESPN completi: {squadra: {id: {"nome", "partite": {settimana: {lanci, ylanci, td, int,
    corse, ycorse, tdcorse, ric, yric, tdric}}}}} della stagione regolare. Tutti i giocatori di ogni partita,
    non solo i migliori: le medie sono su tutte le partite giocate."""
    from fetch_college import carica_tabellini

    def n(x):
        try:
            return float(str(x).split("/")[-1])
        except (TypeError, ValueError):
            return 0.0

    colonne = {"passing": {"C/ATT": "lanci", "YDS": "ylanci", "TD": "td", "INT": "int"},
               "rushing": {"CAR": "corse", "YDS": "ycorse", "TD": "tdcorse"},
               "receiving": {"REC": "ric", "YDS": "yric", "TD": "tdric"}}
    out = {}
    for v in carica_tabellini(stagione).values():
        if v.get("tipo") != "regular" or not str(v.get("settimana", "")).isdigit():
            continue
        w = int(v["settimana"])
        et = v.get("etichette") or {}
        for sq, cats in (v.get("squadre") or {}).items():
            for cat, mappa in colonne.items():
                lab = et.get(cat) or []
                for riga in cats.get(cat) or []:
                    pid = str(riga[0] or riga[1])
                    g = out.setdefault(sq, {}).setdefault(pid, {"nome": riga[1], "partite": {}})
                    voce = g["partite"].setdefault(w, {})
                    for col, chiave in mappa.items():
                        if col in lab and len(riga) > 2 + lab.index(col):
                            voce[chiave] = voce.get(chiave, 0.0) + n(riga[2 + lab.index(col)])   # C/ATT: i tentati
    return out


# misura mostrata per ogni scelta: (gruppo, ruolo mostrato, chiave del valore, misura, partite che contano)
_MISURE = {"QB": ("ylanci", "yard passate", "lanci"), "QB corse": ("ycorse", "yard corse", "lanci"),
           "RB": ("ycorse", "yard corse", "corse"), "RIC": ("yric", "yard ricevute", "ric")}


def _profilo_tabellini(nome, gruppo, partite, passate, partite_squadra):
    """Profilo nella stessa forma del confronto NFL, dalle partite in cui il giocatore ha giocato nel suo ruolo."""
    chiave, misura, conta = _MISURE[gruppo]
    media = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    giocate = [partite[w] for w in sorted(partite) if partite[w].get(conta)]
    valori = [x.get(chiave, 0.0) for x in giocate]
    vecchie = [x for x in (passate or {}).values() if x.get(conta)]
    passato = [x.get(chiave, 0.0) for x in vecchie]
    out = {"nome": nome, "ruolo": "WR" if gruppo == "RIC" else gruppo, "misura": misura,
           "partite": len(valori), "mediaStagione": media(valori), "mediaUltime3": media(valori[-3:]),
           "mediaPassato": media(passato) if len(passato) >= 6 else None,
           "esperienza": None, "giovane": False}
    rif = out["mediaPassato"] if out["mediaPassato"] is not None else out["mediaStagione"]
    forma = None
    if rif and len(valori) >= 4:
        d = (out["mediaUltime3"] - rif) / max(rif, 1)
        forma = "in forma" if d >= 0.25 else "in calo" if d <= -0.25 else None
    out["forma"] = forma
    somma = lambda k: int(sum(x.get(k, 0.0) for x in giocate))
    nota = f"{len(valori)} partite su {partite_squadra}"
    if gruppo == "QB":
        nota += f" · {somma('td')} TD, {somma('int')} INT"
    elif gruppo == "QB corse":
        nota += f" · {somma('corse')} corse, {somma('tdcorse')} TD"
    elif gruppo == "RB":
        nota += f" · {somma('corse')} corse, {somma('tdcorse')} TD"
    else:
        nota += f" · {somma('ric')} ricezioni, {somma('tdric')} TD"
    out["nota"] = nota
    return out


def _scelta_squadra(giocatori):
    """Giocatori chiave dal ruolo vero in campo (i tabellini del college non hanno la posizione):
    QB = chi ha lanciato di più nelle ultime 3 partite della squadra; RB = chi ha corso di più, escluso il QB e
    chi lancia più di quanto corra; 2 ricevitori per ricezioni. Nessun nome due volte. A parità conta la stagione."""
    settimane = sorted({w for g in giocatori.values() for w in g["partite"]})
    ultime3 = set(settimane[-3:])

    def peso(pid, k):
        p = giocatori[pid]["partite"]
        return (-sum(x.get(k, 0.0) for w, x in p.items() if w in ultime3), -sum(x.get(k, 0.0) for x in p.values()))

    def tot(pid, k):
        return sum(x.get(k, 0.0) for x in giocatori[pid]["partite"].values())

    presi, scelte = set(), []
    qb = sorted((p for p in giocatori if tot(p, "lanci") > 0), key=lambda p: peso(p, "lanci"))[:1]
    for p in qb:
        presi.add(p)
        scelte.append((p, "QB"))
    rb = sorted((p for p in giocatori if p not in presi and tot(p, "corse") > 0 and tot(p, "lanci") <= tot(p, "corse")),
                key=lambda p: peso(p, "corse"))[:1]
    for p in rb:
        presi.add(p)
        scelte.append((p, "RB"))
    for p in sorted((p for p in giocatori if p not in presi and tot(p, "ric") > 0), key=lambda p: peso(p, "ric"))[:2]:
        presi.add(p)
        scelte.append((p, "RIC"))
    return scelte, len(settimane)


def _duelli(prossime, ultime, stagione, difese):
    """Per ogni partita del prossimo turno, i giocatori chiave delle due squadre dai tabellini ESPN completi
    (dal 19/11/2026; prima dall'archivio dei migliori, che faceva comparire un QB che corre anche come RB).
    Il QB che corre almeno SOGLIA_CORSE_QB yard a partita ha anche la riga «QB corse». Nessuna chiamata in più."""
    correnti = _prestazioni_tabellini(int(stagione))
    # per la stagione precedente si cerca per id ESPN, ovunque abbia giocato (trasferimenti)
    passate = {}
    for giocatori in _prestazioni_tabellini(int(stagione) - 1).values():
        for pid, g in giocatori.items():
            passate.setdefault(pid, {}).update(g["partite"])
    duelli = []
    for g in prossime:
        lati = {}
        for lato in ("ospite", "casa"):
            giocatori = correnti.get(g[lato]) or {}
            scelte, n_partite = _scelta_squadra(giocatori)
            profili = []
            for pid, gruppo in scelte:
                nome, partite = giocatori[pid]["nome"], giocatori[pid]["partite"]
                profili.append(_profilo_tabellini(nome, gruppo, partite, passate.get(pid), n_partite))
                if gruppo == "QB":
                    corse = _profilo_tabellini(nome, "QB corse", partite, passate.get(pid), n_partite)
                    if (corse["mediaStagione"] or 0) >= SOGLIA_CORSE_QB:
                        profili.append(corse)
            lati[lato] = profili
        if not lati["ospite"] and not lati["casa"]:
            continue
        duelli.append({"casa": g["casa"], "ospite": g["ospite"], "data": g["data"], "ora": g["ora"],
                       "dataIt": g.get("dataIt"), "oraIt": g.get("oraIt"),
                       "favorita": g["favorita"], "linea": g["linea"], "totaleLinea": g["totaleLinea"],
                       "confCasa": g.get("confCasa"), "confOspite": g.get("confOspite"),
                       "difesaCasa": difese.get(g["casa"]), "difesaOspite": difese.get(g["ospite"]),
                       "giocatoriOspite": lati["ospite"], "giocatoriCasa": lati["casa"]})
    return duelli


def _loghi(chiama, stagione):
    """Loghi e colori: una chiamata a stagione, poi dall'archivio."""
    salvati = {}
    if SQUADRE.exists():
        try:
            salvati = json.loads(SQUADRE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            salvati = {}
    # dalla 2026 si conserva anche la mascotte (serve a riconoscere i titoli dei video): un archivio senza
    # mascotte si aggiorna una volta sola
    con_mascotte = any("mascotte" in v for v in (salvati.get("squadre") or {}).values())
    if salvati.get("stagione") == stagione and salvati.get("squadre") and con_mascotte:
        print(f"  Loghi {stagione}: dall'archivio, nessuna chiamata")
        return salvati["squadre"]
    dati = chiama("teams/fbs", year=stagione)
    if not dati:
        return salvati.get("squadre") or {}
    squadre = {}
    for t in dati:
        loghi = [u for u in (t.get("logos") or []) if isinstance(u, str) and u.startswith("https://")]
        squadre[t.get("school")] = {"logo": loghi[0] if loghi else None, "colore": t.get("color"),
                                    "breve": t.get("school"), "mascotte": t.get("mascot") or ""}
    SQUADRE.parent.mkdir(parents=True, exist_ok=True)
    SQUADRE.write_text(json.dumps({"stagione": stagione, "squadre": squadre}, ensure_ascii=False), encoding="utf-8")
    return squadre


def _norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def _nomi(squadra, loghi):
    """Modi in cui un titolo può chiamare la squadra: nome della scuola e mascotte. Con la parentesi
    («Miami (OH)») il nome da solo è ambiguo e non basta: serve la forma completa o la mascotte."""
    nomi = {_norm(squadra)}
    if "(" in squadra:
        nomi.add(_norm(squadra.replace("(OH)", "(Ohio)").replace("(FL)", "(Florida)")))
    else:
        nomi.add(_norm(squadra))
    m = _norm((loghi.get(squadra) or {}).get("mascotte"))
    if m:
        nomi.add(m)
    return {n for n in nomi if len(n) >= 3}


def _nomina(testo, nomi):
    """Il titolo nomina la squadra? «Ohio» non vale dentro «Ohio State», «Michigan» non dentro «Michigan State»."""
    t = f" {_norm(testo)} "
    for n in nomi:
        for m in re.finditer(rf" {re.escape(n)} ", t):
            dopo = t[m.end():]
            if not (dopo.startswith("state ") or dopo.startswith("st ")) or n.endswith(" state"):
                return True
    return False


def video_college(giornata, loghi):
    """Highlights su YouTube per ogni partita giocata della giornata. Prima i canali verificati (network,
    conference, canali delle due squadre); se nessuno ha il video, un video il cui titolo nomina entrambe le
    squadre, segnato come non ufficiale. Altrimenti resta il link di ricerca. Senza chiave non fa nulla."""
    chiave = os.environ.get("YOUTUBE_API_KEY", "").strip()
    archivio = {}
    if ARCHIVIO_VIDEO.exists():
        try:
            archivio = json.loads(ARCHIVIO_VIDEO.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            archivio = {}
    adesso = datetime.now(timezone.utc)
    fatte = 0
    # prima le partite tra due squadre FBS, poi quelle con una sola; le partite tra squadre FCS non si cercano
    # (quasi mai hanno highlights pubblicati e consumerebbero ricerche): resta il link di ricerca
    fbs = lambda g: (g["casa"] in loghi) + (g["ospite"] in loghi)
    for g in sorted(giornata["partite"], key=lambda g: -fbs(g)):
        if g["pc"] is None:
            continue
        gid = f"{giornata['stagione']}_{int(giornata['settimana']):02d}_{g['ospite']}_{g['casa']}"
        voce = archivio.get(gid)
        if voce and voce.get("id"):
            for k in ("titolo", "canale", "etichetta"):        # archivio scritto prima della correzione
                if voce.get(k):
                    voce[k] = html.unescape(voce[k])
            g["video"] = voce
            continue
        if not chiave or fatte >= MAX_RICERCHE_VIDEO or not fbs(g):
            continue
        # ricerca senza risultato: si riprova al giro successivo, ma non prima di 12 ore
        if voce and voce.get("cercato") and adesso - datetime.fromisoformat(voce["cercato"]) < timedelta(hours=12):
            continue
        nomi_o, nomi_c = _nomi(g["ospite"], loghi), _nomi(g["casa"], loghi)
        params = {"part": "snippet", "type": "video", "maxResults": 10, "order": "relevance",
                  "q": f"{g['ospite']} vs {g['casa']} football highlights",
                  "publishedAfter": f"{g['data']}T00:00:00Z", "key": chiave}
        fatte += 1
        try:
            with urlopen(Request("https://www.googleapis.com/youtube/v3/search?" + urlencode(params),
                                 headers={"User-Agent": "PureStats"}), timeout=30) as r:
                risultati = json.loads(r.read().decode()).get("items") or []
        except HTTPError as e:
            print(f"  Video college {gid}: YouTube ha risposto {e.code}"
                  + (" (quota giornaliera esaurita: riprovo al prossimo aggiornamento)" if e.code == 403 else ""))
            if e.code == 403:
                break
            continue
        except (URLError, TimeoutError) as e:
            print(f"  Video college {gid}: ricerca non riuscita ({e}); resta il link di ricerca")
            continue
        verificato = altro = None
        for it in risultati:
            sn = it.get("snippet") or {}
            # YouTube restituisce i titoli con le entità HTML («Ragin&#39; Cajuns»)
            titolo, canale = html.unescape(sn.get("title") or ""), html.unescape(sn.get("channelTitle") or "")
            vid = (it.get("id") or {}).get("videoId")
            # entrambe le squadre nel titolo ed è un video di highlights (non conferenze stampa o anteprime)
            if not vid or "highlight" not in titolo.lower() or not (_nomina(titolo, nomi_o) and _nomina(titolo, nomi_c)):
                continue
            c = _norm(canale)
            ufficiale = any(c == v or c.startswith(v + " ") for v in CANALI_VERIFICATI) \
                or _nomina(canale, nomi_o) or _nomina(canale, nomi_c)
            voce = {"id": vid, "titolo": titolo, "canale": canale, "ufficiale": ufficiale}
            if ufficiale and not verificato:
                verificato = voce
            elif not ufficiale and not altro:
                altro = voce
        scelto = verificato or altro
        if scelto:
            scelto["etichetta"] = (f"Highlights · {canale_breve(scelto['canale'])}" if scelto["ufficiale"]
                                   else f"Highlights non ufficiali · {canale_breve(scelto['canale'])}") + " · si apre su YouTube"
            archivio[gid] = scelto
            g["video"] = scelto
            print(f"  Video college {gid}: {scelto['titolo']} ({scelto['canale']}"
                  + ("" if scelto["ufficiale"] else ", non ufficiale") + ")")
        else:
            archivio[gid] = {"cercato": adesso.isoformat()}
            print(f"  Video college {gid}: nessun video affidabile per ora; resta il link di ricerca")
    if fatte:
        print(f"  Video college: {fatte} ricerche YouTube in questa esecuzione (massimo {MAX_RICERCHE_VIDEO})")
    ARCHIVIO_VIDEO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVIO_VIDEO.with_suffix(".tmp")
    tmp.write_text(json.dumps(archivio, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ARCHIVIO_VIDEO)


def canale_breve(c):
    return c if len(c) <= 30 else c[:29] + "…"


LINEE = RADICE / "data" / "college_linee.json"
SP = RADICE / "data" / "college_sp.json"
SP_GIORNI = 6          # SP+ cambia una volta a settimana: si chiede a CollegeFootballData al massimo ogni 6 giorni


def _carica(percorso):
    try:
        return json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _salva(percorso, dati):
    percorso.parent.mkdir(parents=True, exist_ok=True)
    tmp = percorso.with_suffix(".tmp")
    tmp.write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, percorso)


def _gare_espn(partite, settimana, linee):
    """Partite ESPN di una settimana nella forma che _riga si aspetta (la stessa di CollegeFootballData).
    La linea di una partita finita si legge una volta e poi resta in data/college_linee.json; quella di una
    partita da giocare si rilegge a ogni giro (si muove)."""
    import espn_college
    out = []
    for g in partite:
        if g["Settimana"] != str(settimana) or g["Tipo"] != "regular":
            continue
        voce = linee.get(g["id"])
        if not (voce and voce.get("chiusa")):
            nuova = espn_college.linea(g["id"])
            if nuova:
                voce = {**nuova, "chiusa": bool(g["finita"])}
                linee[g["id"]] = voce
        pc = int(g["PuntiCasa"]) if g["PuntiCasa"] != "" else None
        po = int(g["PuntiOspite"]) if g["PuntiOspite"] != "" else None
        lines = []
        if voce and (voce.get("margine") is not None or voce.get("totale") is not None):
            lines = [{"provider": "consensus", "spread": None if voce.get("margine") is None else -voce["margine"],
                      "overUnder": voce.get("totale")}]
        out.append({"homeTeam": g["Casa"], "awayTeam": g["Ospite"], "homeScore": pc, "awayScore": po,
                    "startDate": g["inizio"] if g.get("orarioValido", True) else g["inizio"][:10], "season": g["Stagione"], "homeConference": g["ConferenzaCasa"],
                    "awayConference": g["ConferenzaOspite"], "lines": lines})
    return out


def _sp_settimanale(chiama, stagione):
    """SP+ da CollegeFootballData al massimo una volta ogni SP_GIORNI giorni; altrimenti l'ultimo salvato."""
    salvato = _carica(SP)
    adesso = datetime.now(timezone.utc)
    if salvato.get("stagione") == stagione and salvato.get("dati"):
        eta = adesso - datetime.fromisoformat(salvato["letto"])
        if eta < timedelta(days=SP_GIORNI):
            print(f"  SP+: salvato {eta.days} giorni fa, nessuna chiamata")
            return salvato["dati"]
    sp = chiama("ratings/sp", year=stagione)
    if sp:
        _salva(SP, {"stagione": stagione, "letto": adesso.isoformat(), "dati": sp})
        return sp
    if salvato.get("stagione") == stagione and salvato.get("dati"):
        print("  SP+: CollegeFootballData non ha risposto, resta l'ultimo salvato")
        return salvato["dati"]
    return None


def calcola(chiama, stats, stagione, partite_espn=None):
    """Blocchi aggiuntivi per data_college.json. Ogni blocco può mancare senza invalidare gli altri.
    Con partite_espn (la stagione letta da ESPN) le linee arrivano da ESPN e CollegeFootballData serve solo
    per SP+ (una volta a settimana) e i loghi (una volta a stagione)."""
    ultime = stats.get("ultimePartite") or []
    giocate = [int(p["settimana"]) for p in ultime
               if str(p.get("stagione")) == str(stagione) and p.get("pc") is not None and str(p.get("settimana", "")).isdigit()]
    out = {"loghi": _loghi(chiama, stagione), "giornata": None, "prossima": None, "indici": None}
    if not giocate:
        return out
    w = max(giocate)
    linee = _carica(LINEE)
    righe = _gare_espn(partite_espn, w, linee) if partite_espn else chiama("lines", year=stagione, week=w, seasonType="regular")
    if righe:
        # per orario d'inizio (ESPN dà l'ora in UTC); senza ora in fondo alla giornata
        gare = sorted((_riga(g) for g in righe), key=lambda g: ((g.get("inizio") if len(g.get("inizio") or "") > 10
                                                                  else g["data"] + "T99"), g["casa"] or ""))
        con_linea = [g for g in gare if g["scartoLinea"] is not None]
        out["giornata"] = {
            "stagione": stagione, "settimana": w,
            "completa": all(g["pc"] is not None for g in gare),
            "partite": gare,
            "sorprese": [{"casa": g["casa"], "ospite": g["ospite"], "scarto": g["scartoLinea"], "battutaDa": g["battutaDa"]}
                         for g in sorted(con_linea, key=lambda g: -g["scartoLinea"])[:5]],
            "riepilogo": {"partite": sum(1 for g in gare if g["pc"] is not None),
                          "favoriteCoperte": sum(1 for g in gare if g["battutaDa"] and g["battutaDa"] == g["favorita"]),
                          "over": sum(1 for g in gare if g["totaleEsito"] == "over"),
                          "under": sum(1 for g in gare if g["totaleEsito"] == "under")},
            "prestazioni": _prestazioni_complete(ultime, stagione, w),
        }
        try:            # Giornata (dal 16/11/2026): giocate, squadre della week, ultimi 2 minuti, flag (dati ESPN)
            import json as _json
            import college_giornata
            from pathlib import Path as _Path
            f = _Path(__file__).resolve().parent.parent / "data" / f"college_tabellini_{stagione}.json"
            tab = _json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
            fbs = {x.get("nome") or x.get("squadra") for x in stats.get("squadre") or []} - {None}
            b = college_giornata.blocchi(tab, str(w), fbs or None)
            out["giornata"].update(b)
            print(f"  Giornata college: {sum(len(v) for v in (b.get('giocate') or {}).values())} giocate, "
                  f"squadre della week {'sì' if b.get('squadreSettimana') else 'no'}, "
                  f"ultimi 2 minuti {len((b.get('ultimiDueMinuti') or {}).get('squadre') or [])} squadre, "
                  f"flag {len((b.get('flag') or {}).get('squadre') or [])} squadre")
        except Exception as e:      # i blocchi nuovi non devono mai bloccare il resto
            print(f"  Blocchi della Giornata college non calcolati: {type(e).__name__}: {e}")
        try:
            video_college(out["giornata"], out["loghi"] or {})
        except (KeyError, TypeError, ValueError, OSError) as e:
            # i video sono un di più: senza, resta il link di ricerca
            print(f"  Video college non cercati: {e!r}. Restano i link di ricerca.")
    prossime = _gare_espn(partite_espn, w + 1, linee) if partite_espn else chiama("lines", year=stagione, week=w + 1, seasonType="regular")
    if partite_espn:
        _salva(LINEE, linee)
    if prossime:
        out["prossima"] = {"stagione": stagione, "settimana": w + 1,
                           "partite": sorted((_riga(g) for g in prossime), key=lambda g: (g["data"], g["casa"] or ""))}
    sp = _sp_settimanale(chiama, stagione)
    if sp:
        conf = {s["nome"]: s.get("conference") for s in stats.get("squadre") or []}
        # attacco e difesa rispetto alla media FBS, entrambi "più alto = meglio"
        # (in SP+ la difesa sono punti concessi: si confronta con la media al contrario)
        validi = [r for r in sp if r.get("team") in conf]
        med_att = statistics.mean([(r.get("offense") or {}).get("rating") for r in validi
                                   if (r.get("offense") or {}).get("rating") is not None] or [0])
        med_dif = statistics.mean([(r.get("defense") or {}).get("rating") for r in validi
                                   if (r.get("defense") or {}).get("rating") is not None] or [0])
        squadre = []
        for r in sp:
            nome = r.get("team")
            if not nome or nome == "nationalAverages" or nome not in conf:
                continue
            att = (r.get("offense") or {}).get("rating")
            dif = (r.get("defense") or {}).get("rating")
            if r.get("rating") is None:
                continue
            squadre.append({"squadra": nome, "nome": nome, "conference": conf.get(nome),
                            "netto": round(r["rating"], 1),
                            "attacco": None if att is None else round(att - med_att, 1),
                            "difesa": None if dif is None else round(med_dif - dif, 1),
                            "puntiPartita": round(r["rating"], 1)})
        squadre.sort(key=lambda s: -s["netto"])
        for i, s in enumerate(squadre, 1):
            s["posizione"] = i
        out["indici"] = {
            "stagione": stagione, "squadre": squadre, "quarterback": [], "decimali": 1,
            "etichette": {"titolo": "SP+ (CollegeFootballData)",
                          "sotto": "Punti di vantaggio su una squadra media in campo neutro. Attacco e difesa rispetto alla media FBS: più alto = meglio",
                          "netto": "SP+"},
            "nota": "SP+ è calcolato da CollegeFootballData sull'azione per azione completa; qui è riportato com'è."}
    if out["prossima"]:
        # difesa SP+ di ogni squadra (rispetto alla media FBS, più alto = meglio), se disponibile
        difese = {s["squadra"]: s["difesa"] for s in ((out["indici"] or {}).get("squadre") or [])}
        try:
            out["prossima"]["duelli"] = _duelli(out["prossima"]["partite"], ultime, stagione, difese)
        except (KeyError, TypeError, ValueError) as e:
            # il confronto è un di più: se l'archivio ha una forma inattesa resta la lista partite
            print(f"  Confronto giocatori college non calcolato: {e!r}. Resta l'elenco delle partite.")
    if out["giornata"]:
        # giocatori chiave anche per le partite ancora da giocare della giornata in corso (sezione duelli)
        difese = {s["squadra"]: s["difesa"] for s in ((out["indici"] or {}).get("squadre") or [])}
        resto = [g for g in out["giornata"]["partite"] if g["pc"] is None]
        if resto:
            try:
                out["giornata"]["duelli"] = _duelli(resto, ultime, stagione, difese)
            except (KeyError, TypeError, ValueError) as e:
                print(f"  Confronto giocatori della giornata in corso non calcolato: {e!r}.")
    return out
