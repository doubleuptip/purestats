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
    return {"highlights": hl, "data": data, "ora": "", "casa": casa, "ospite": ospite, "pc": pc, "po": po,
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


def _apparizioni(ultime, stagioni):
    """Dall'archivio partite: per ogni squadra e giocatore, le prestazioni in ordine di settimana.

    L'archivio conserva solo i migliori di ogni partita (1 QB, 1 RB, 2 ricevitori per
    squadra): una partita in cui il giocatore non è stato tra i migliori non c'è, e
    non vale zero. Le medie sono quindi "nelle partite in cui è stato il migliore".
    Restituisce {stagione: {squadra: {(nome, gruppo): [voci]}}} con gruppo QB, RB o RIC."""
    out = {}
    for p in ultime:
        s = str(p.get("stagione"))
        if s not in stagioni or not str(p.get("settimana", "")).isdigit() or p.get("pc") is None:
            continue
        for lato, squadra in (("giocatoriCasa", p["casa"]), ("giocatoriOspite", p["ospite"])):
            for g in p.get(lato) or []:
                gruppo = "RIC" if g.get("ruolo") in ("WR", "TE") else g.get("ruolo")
                if gruppo not in ("QB", "RB", "RIC") or not g.get("nome"):
                    continue
                voce = {"settimana": int(p["settimana"]), "valore": g.get("valore") or 0,
                        "misura": g.get("misura"), "dettagli": g.get("dettagli") or []}
                out.setdefault(s, {}).setdefault(squadra, {}).setdefault((g["nome"], gruppo), []).append(voce)
    for squadre in out.values():
        for giocatori in squadre.values():
            for voci in giocatori.values():
                voci.sort(key=lambda v: v["settimana"])
    return out


def _somma_dettaglio(voci, etichetta):
    """Somma un dettaglio testuale ("2 TD", "1 INT") sulle voci date."""
    tot = 0
    for v in voci:
        for d in v["dettagli"]:
            parti = str(d).split(" ", 1)
            if len(parti) == 2 and parti[1] == etichetta:
                try:
                    tot += int(float(parti[0]))
                except ValueError:
                    pass
    return tot


def _profilo_college(nome, gruppo, voci, passate, partite_squadra):
    """Profilo nella stessa forma del confronto NFL, senza anno di corso."""
    media = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    valori = [v["valore"] for v in voci]
    passato = [v["valore"] for v in passate]
    out = {"nome": nome, "ruolo": "WR" if gruppo == "RIC" else gruppo, "misura": voci[-1]["misura"],
           "partite": len(voci), "mediaStagione": media(valori), "mediaUltime3": media(valori[-3:]),
           "mediaPassato": media(passato) if len(passato) >= 6 else None,
           "esperienza": None, "giovane": False}
    rif = out["mediaPassato"] if out["mediaPassato"] is not None else out["mediaStagione"]
    forma = None
    if rif and len(voci) >= 4:
        d = (out["mediaUltime3"] - rif) / max(rif, 1)
        forma = "in forma" if d >= 0.25 else "in calo" if d <= -0.25 else None
    out["forma"] = forma
    nota = f"migliore della squadra in {len(voci)} partite su {partite_squadra}"
    if gruppo == "QB":
        nota += f" · {_somma_dettaglio(voci, 'TD')} TD, {_somma_dettaglio(voci, 'INT')} INT"
    elif gruppo == "RIC":
        nota += f" · {_somma_dettaglio(voci, 'ric.')} ricezioni"
    out["nota"] = nota
    return out


def _duelli(prossime, ultime, stagione, difese):
    """Per ogni partita del prossimo turno, i giocatori chiave delle due squadre dall'archivio:
    il QB e il RB comparsi più spesso tra i migliori nelle ultime 3 partite, e i 2 ricevitori
    più presenti. A parità conta il rendimento. Nessuna chiamata in più."""
    s, sp = str(stagione), str(int(stagione) - 1)
    app = _apparizioni(ultime, {s, sp})
    correnti, passate = app.get(s, {}), app.get(sp, {})
    # per la stagione precedente si cerca per nome, ovunque abbia giocato (trasferimenti)
    passate_nome = {}
    for giocatori in passate.values():
        for (nome, gruppo), voci in giocatori.items():
            passate_nome.setdefault((nome, gruppo), []).extend(voci)
    duelli = []
    for g in prossime:
        lati = {}
        for lato in ("ospite", "casa"):
            giocatori = correnti.get(g[lato]) or {}
            settimane = sorted({v["settimana"] for voci in giocatori.values() for v in voci})
            ultime3 = set(settimane[-3:])
            def peso(chiave):
                voci = giocatori[chiave]
                return (-sum(1 for v in voci if v["settimana"] in ultime3), -len(voci),
                        -sum(v["valore"] for v in voci))
            scelti = []
            for gruppo, n in (("QB", 1), ("RB", 1), ("RIC", 2)):
                scelti += sorted((k for k in giocatori if k[1] == gruppo), key=peso)[:n]
            lati[lato] = [_profilo_college(nome, gruppo, giocatori[(nome, gruppo)],
                                           passate_nome.get((nome, gruppo), []), len(settimane))
                          for nome, gruppo in scelti]
        if not lati["ospite"] and not lati["casa"]:
            continue
        duelli.append({"casa": g["casa"], "ospite": g["ospite"], "data": g["data"], "ora": g["ora"],
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
                    "startDate": g["inizio"], "season": g["Stagione"], "homeConference": g["ConferenzaCasa"],
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
        gare = sorted((_riga(g) for g in righe), key=lambda g: (g["data"], g["casa"] or ""))
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
            "prestazioni": _prestazioni(ultime, stagione, w),
        }
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
