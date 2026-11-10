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

Chiamate per aggiornamento: 3 (linee della settimana giocata, linee della
prossima, SP+), più 1 a stagione per i loghi, conservati in archivio.
Solo libreria standard.
"""

import json
import statistics
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
SQUADRE = RADICE / "data" / "college_squadre.json"


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
    if salvati.get("stagione") == stagione and salvati.get("squadre"):
        print(f"  Loghi {stagione}: dall'archivio, nessuna chiamata")
        return salvati["squadre"]
    dati = chiama("teams/fbs", year=stagione)
    if not dati:
        return salvati.get("squadre") or {}
    squadre = {}
    for t in dati:
        loghi = [u for u in (t.get("logos") or []) if isinstance(u, str) and u.startswith("https://")]
        squadre[t.get("school")] = {"logo": loghi[0] if loghi else None, "colore": t.get("color"),
                                    "breve": t.get("school")}
    SQUADRE.parent.mkdir(parents=True, exist_ok=True)
    SQUADRE.write_text(json.dumps({"stagione": stagione, "squadre": squadre}, ensure_ascii=False), encoding="utf-8")
    return squadre


def calcola(chiama, stats, stagione):
    """Blocchi aggiuntivi per data_college.json. Ogni blocco può mancare senza invalidare gli altri."""
    ultime = stats.get("ultimePartite") or []
    giocate = [int(p["settimana"]) for p in ultime
               if str(p.get("stagione")) == str(stagione) and p.get("pc") is not None and str(p.get("settimana", "")).isdigit()]
    out = {"loghi": _loghi(chiama, stagione), "giornata": None, "prossima": None, "indici": None}
    if not giocate:
        return out
    w = max(giocate)
    righe = chiama("lines", year=stagione, week=w, seasonType="regular")
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
    prossime = chiama("lines", year=stagione, week=w + 1, seasonType="regular")
    if prossime:
        out["prossima"] = {"stagione": stagione, "settimana": w + 1,
                           "partite": sorted((_riga(g) for g in prossime), key=lambda g: (g["data"], g["casa"] or ""))}
    sp = chiama("ratings/sp", year=stagione)
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
    return out
