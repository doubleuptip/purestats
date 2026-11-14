"""
Archivio College Football — statistiche di squadra e partite.

Fonte: CollegeFootballData.com, tramite la sua API REST. Richiede una
chiave gratuita, che si ottiene indicando un indirizzo email e che va
conservata fra i secret del repository, mai nel codice.

Il piano gratuito ha un limite mensile di chiamate: lo script ne fa due
per stagione, quindi dieci in tutto, e conserva le stagioni già scaricate
invece di riprenderle ogni volta.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import espn_college

RADICE = Path(__file__).resolve().parent.parent
ARCHIVIO = RADICE / "data" / "college.csv"
ARCHIVIO_GIOCATORI = RADICE / "data" / "college_giocatori.json"
# Tabellini completi (tutti i giocatori di ogni partita), un file per stagione: base per lo storico delle
# assenze (chi c'era e chi mancava) e per tutte le statistiche dei giocatori. Le stagioni concluse non cambiano.
CARTELLA_DATI = RADICE / "data"
USCITA = RADICE / "docs" / "data_college.json"

BASE = "https://api.collegefootballdata.com"
UA = "Mozilla/5.0 (compatible; PureStats/1.0)"

MAX_STAGIONI = 5

COLONNE = [
    "Stagione", "Settimana", "Tipo", "Data",
    "Casa", "Ospite", "PuntiCasa", "PuntiOspite",
    "ConferenzaCasa", "ConferenzaOspite", "CampoNeutro", "Stadio", "Spettatori",
]


# Conference ammesse. Il college football conta oltre settecento squadre
# fra tutte le categorie: senza questo elenco il calendario si riempirebbe
# di incontri fra scuole di seconda e terza divisione.
#
# Una partita entra in archivio se ALMENO UNA delle due squadre appartiene
# a queste conference. Il criterio più stretto, che ne richiedeva due,
# cancellava anche le sfide contro avversari di categoria inferiore: ma
# quelle contano per la squadra maggiore, e toglierle significava perderne
# le statistiche. Restano escluse solo le partite fra due squadre minori,
# che sono quelle che riempivano il calendario senza interessare nessuno.
CONFERENCE_AMMESSE = {
    "ACC", "Atlantic Coast Conference",
    "American Athletic", "American", "The American",
    "Big 12", "Big Twelve",
    "Big Ten", "Big 10",
    "Conference USA", "C-USA",
    "Mountain West", "Mountain West Conference", "MWC",
    "Pac-12", "Pac 12", "Pacific 12",
    "Sun Belt", "Sun Belt Conference",
    "SEC", "Southeastern Conference",
    "Mid-American", "MAC",
    "FBS Independents", "Independent", "Independents",
}

# Confronto senza distinzione fra maiuscole e spazi, perché la stessa
# conference compare scritta in modi diversi a seconda della stagione.
_AMMESSE = {" ".join(c.lower().split()) for c in CONFERENCE_AMMESSE}


def e_prima_divisione(conferenza):
    """Vero se la conference è fra quelle seguite."""
    c = " ".join((conferenza or "").lower().split())
    return bool(c) and c in _AMMESSE


def chiave_api():
    return os.environ.get("CFBD_API_KEY", "").strip()


def chiama(percorso, **parametri):
    """CollegeFootballData: dal 14/11/2026 solo per SP+ (una volta a settimana) e loghi (una volta a stagione).
    Calendario, risultati, linee e tabellini arrivano da ESPN (espn_college.py)."""
    if not chiave_api():
        print(f"  CollegeFootballData non usato per {percorso}: CFBD_API_KEY non impostata")
        return None
    url = f"{BASE}/{percorso}?{urlencode(parametri)}"
    print(f"  GET {url}")
    richiesta = Request(url, headers={
        "User-Agent": UA,
        "Authorization": f"Bearer {chiave_api()}",
        "Accept": "application/json",
    })
    try:
        with urlopen(richiesta, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        corpo = ""
        try:
            corpo = e.read().decode("utf-8")[:200]
        except Exception:
            pass
        print(f"    HTTP {e.code} {corpo}")
        if e.code in (401, 403):
            print("    La chiave non è valida o non è autorizzata.")
        elif e.code == 429:
            print("    Limite di chiamate raggiunto per questo mese.")
        return None
    except URLError as e:
        print(f"    Rete: {e.reason}")
        return None
    except json.JSONDecodeError as e:
        print(f"    Risposta non interpretabile: {e}")
        return None


def num(valore):
    if valore is None or valore == "":
        return None
    try:
        return int(float(valore))
    except (ValueError, TypeError):
        return None


def stagione_corrente():
    oggi = datetime.now(timezone.utc)
    # la stagione comincia ad agosto e prende il nome dell'anno d'inizio
    return oggi.year if oggi.month >= 8 else oggi.year - 1


def stagioni_forzate():
    """Stagioni da riscaricare comunque, indicate con la variabile STAGIONI."""
    esplicite = os.environ.get("STAGIONI", "").strip()
    return [int(s) for s in esplicite.replace(",", " ").split() if s.isdigit()]


def stagioni_da_scaricare():
    forzate = stagioni_forzate()
    if forzate:
        return forzate
    corrente = stagione_corrente()
    return list(range(corrente, corrente - MAX_STAGIONI, -1))


# Sotto questa soglia una stagione passata si considera incompleta e viene
# riscaricata: una stagione intera di prima divisione conta circa ottocento
# partite, quindi un archivio più povero segnala un download interrotto.
MINIMO_PARTITE_STAGIONE = 400


# Ruoli mostrati nella scheda partita. Nel college le statistiche arrivano
# raggruppate per categoria (passing, rushing, receiving) invece che per
# ruolo del giocatore: si prende il migliore di ogni categoria.
CATEGORIE_GIOCATORI = [
    ("passing",   "YDS", "QB", "yard passate",  ["TD", "INT"]),
    ("rushing",   "YDS", "RB", "yard corse",    ["TD"]),
    ("receiving", "YDS", "WR", "yard ricevute", ["REC", "TD"]),
]

QUANTI_PER_CATEGORIA = {"QB": 1, "RB": 1, "WR": 2}

ETICHETTE = {"TD": "TD", "INT": "INT", "REC": "ric."}

# Con 0 le statistiche dei giocatori non si leggono (tabellini ESPN, una richiesta per partita).
STAGIONI_CON_GIOCATORI = int(os.environ.get("STAGIONI_GIOCATORI", "2"))


def _numero(valore):
    """Le statistiche arrivano come testo, a volte con formati misti."""
    testo = str(valore or "").strip().replace(",", "")
    if not testo:
        return 0
    # 'passing YDS' può arrivare come '312'; 'C/ATT' come '24/35'
    if "/" in testo:
        testo = testo.split("/")[0]
    try:
        return int(float(testo))
    except ValueError:
        return 0


def carica_archivio_giocatori():
    if not ARCHIVIO_GIOCATORI.exists():
        return {}
    try:
        dati = json.loads(ARCHIVIO_GIOCATORI.read_text(encoding="utf-8"))
        return dati if isinstance(dati, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def salva_archivio_giocatori(dati):
    ARCHIVIO_GIOCATORI.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVIO_GIOCATORI.with_suffix(".tmp")
    tmp.write_text(json.dumps(dati, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ARCHIVIO_GIOCATORI)          # mai un archivio a metà


def file_tabellini(stagione):
    return CARTELLA_DATI / f"college_tabellini_{stagione}.json"


def carica_tabellini(stagione):
    """{id partita: {settimana, tipo, inizio, casa, ospite, squadre, etichette}} della stagione."""
    f = file_tabellini(stagione)
    if not f.exists():
        return {}
    try:
        dati = json.loads(f.read_text(encoding="utf-8"))
        return dati if isinstance(dati, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        # un file illeggibile non si sovrascrive alla cieca: si ferma tutto e lo si guarda
        raise SystemExit(f"Archivio tabellini {f.name} illeggibile ({e}): non lo tocco, va controllato")


def salva_tabellini(stagione, dati):
    f = file_tabellini(stagione)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    # una partita per riga: il file resta leggibile e Git salva solo le righe cambiate
    righe = [f"{json.dumps(k)}:{json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
             for k, v in sorted(dati.items())]
    tmp.write_text("{\n" + ",\n".join(righe) + "\n}\n", encoding="utf-8")
    os.replace(tmp, f)                            # mai un archivio a metà


def scheda_tabellino(g, completo):
    """La voce dell'archivio per una partita: i dati della partita più il tabellino completo."""
    return {"settimana": str(g["Settimana"]), "tipo": g.get("Tipo") or "regular", "inizio": g.get("inizio") or "",
            "casa": g["Casa"], "ospite": g["Ospite"],
            "squadre": completo.get("squadre") or {}, "etichette": completo.get("etichette") or {}}


def _scegli(valori):
    """I migliori della squadra nella partita: 1 QB, 1 RB, 2 ricevitori, dalle statistiche per categoria."""
    scelti = []
    for cat, misura, ruolo, etichetta, extra in CATEGORIE_GIOCATORI:
        candidati = []
        for (nome_cat, atleta), stat in valori.items():
            if nome_cat != cat:
                continue
            valore = _numero(stat.get(misura))
            if valore <= 0:
                continue
            dettagli = []
            for campo in extra:
                n = _numero(stat.get(campo))
                if n:
                    dettagli.append(f"{n} {ETICHETTE.get(campo, campo)}")
            candidati.append({"nome": atleta, "ruolo": ruolo, "valore": valore, "misura": etichetta,
                              "dettagli": dettagli})
        candidati.sort(key=lambda g: -g["valore"])
        scelti.extend(candidati[:QUANTI_PER_CATEGORIA.get(ruolo, 1)])
    return scelti


def _ricostruisci_giocatori():
    """Prima esecuzione dopo il passaggio a ESPN: l'archivio dei giocatori non era salvato nel repository e si
    riscaricava a ogni giro. Si ricostruisce dall'ultima pagina pubblicata (nessuna chiamata)."""
    pagina = RADICE / "docs" / "data_college.json"
    try:
        dati = json.loads(pagina.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for p in dati.get("ultimePartite") or []:
        for lato, sq in (("giocatoriCasa", p.get("casa")), ("giocatoriOspite", p.get("ospite"))):
            if p.get(lato) and sq:
                out.setdefault(str(p["stagione"]), {}).setdefault(str(p["settimana"]), {})[sq] = p[lato]
    if out:
        print(f"  Archivio giocatori ricostruito dalla pagina pubblicata: stagioni {sorted(out)}")
    return out


def carica_giocatori(stagioni, forzate=(), partite_espn=None):
    """I migliori giocatori di ogni partita, per categoria, dai tabellini ESPN (una richiesta per partita, gratis).

    Restituisce: {stagione: {settimana: {squadra: [giocatori]}}}, salvato in data/college_giocatori.json.
    Della stagione in corso si chiedono solo le partite finite che mancano e quelle finite da meno di 3 giorni
    (i tabellini possono ancora essere corretti). La prima volta la stagione in corso si riprende tutta da ESPN,
    così i nomi dei giocatori sono scritti in un solo modo per tutta la stagione (ESPN e CollegeFootballData
    a volte li scrivono diversamente). Le stagioni concluse restano come sono.
    """
    per_partita = carica_archivio_giocatori() or _ricostruisci_giocatori()
    fonti = per_partita.setdefault("_fonte", {})
    if STAGIONI_CON_GIOCATORI <= 0 or not partite_espn:
        print("  Statistiche giocatori: nessuna partita ESPN da leggere")
        return per_partita
    adesso = datetime.now(timezone.utc)
    for stagione, partite in sorted(partite_espn.items()):
        s = str(stagione)
        tutta = fonti.get(s) != "espn" or int(stagione) in forzate
        if tutta:
            print(f"    stagione {s}: ripresa tutta da ESPN (nomi uniformi)")
        # ripresa completa: si lavora su un archivio nuovo e si sostituisce il vecchio solo se tutto è riuscito
        archivio = {} if tutta else per_partita.setdefault(s, {})
        tabellini = carica_tabellini(s)
        da_leggere = []
        for g in partite:
            if not g.get("finita") or g.get("Tipo") != "regular":
                continue
            w = g["Settimana"]
            presenti = archivio.get(w, {})
            fbs = [sq for sq, conf in ((g["Casa"], g["ConferenzaCasa"]), (g["Ospite"], g["ConferenzaOspite"]))
                   if e_prima_divisione(conf)]
            try:
                recente = adesso - datetime.fromisoformat(g["inizio"].replace("Z", "+00:00")) < timedelta(days=3)
            except ValueError:
                recente = False
            if fbs and (recente or str(g["id"]) not in tabellini or any(sq not in presenti for sq in fbs)):
                da_leggere.append((g, fbs))
        trovate = fallite = 0
        for n, (g, fbs) in enumerate(da_leggere, 1):
            completo = espn_college.tabellino_completo(g["id"])
            if completo is None:
                fallite += 1
                continue
            # anche un tabellino vuoto si segna (ESPN a volte non lo ha per le FCS): non si richiede a ogni giro;
            # nei primi 3 giorni dopo la partita si rilegge comunque
            tabellini[str(g["id"])] = scheda_tabellino(g, completo)
            if n % 100 == 0:
                salva_tabellini(s, tabellini)         # ogni 100 partite: un errore a metà non perde il lavoro
            tab = espn_college.valori_tabellino(completo)
            for sq in fbs:
                scelti = _scegli(tab.get(sq) or {})
                if scelti:
                    archivio.setdefault(g["Settimana"], {})[sq] = scelti
                    trovate += len(scelti)
        if tutta and not fallite:
            per_partita[s] = archivio
            fonti[s] = "espn"
        elif tutta:
            for w, squadre in archivio.items():          # riuscita a metà: si aggiunge, senza togliere nulla
                per_partita.setdefault(s, {}).setdefault(w, {}).update(squadre)
        if da_leggere:
            salva_tabellini(s, tabellini)
        print(f"    stagione {s}: {len(da_leggere)} tabellini richiesti, {trovate} prestazioni di rilievo, "
              f"{len(tabellini)} partite nell'archivio completo"
              + (f", {fallite} non riusciti (si riprovano al prossimo giro)" if fallite else ""))
    return per_partita


def carica_archivio():
    """Legge l'archivio applicando anche a esso il filtro sulle conference.

    Filtrare solo ciò che si scarica non basta: le partite salvate prima
    che il filtro esistesse resterebbero per sempre, perché a ogni giro
    l'archivio viene ricaricato e riscritto così com'è.
    """
    if not ARCHIVIO.exists():
        return []
    with ARCHIVIO.open(encoding="utf-8", newline="") as f:
        # Fino al 14/11/2026 l'archivio veniva scritto senza riga d'intestazione: letto con DictReader, la prima
        # partita diventava l'intestazione e tutte le altre restavano senza colonne (e venivano scartate).
        # Si accettano entrambe le forme; da ora si scrive sempre con l'intestazione.
        con_intestazione = f.readline().startswith("Stagione,")
        f.seek(0)
        grezze = list(csv.DictReader(f) if con_intestazione else csv.DictReader(f, fieldnames=COLONNE))

    righe = []
    scartate = 0
    for r in grezze:
        for c in COLONNE:
            r.setdefault(c, "")
        if not (e_prima_divisione(r.get("ConferenzaCasa"))
                or e_prima_divisione(r.get("ConferenzaOspite"))):
            scartate += 1
            continue
        righe.append(r)

    if scartate:
        print(f"  {scartate} partite rimosse dall'archivio "
              f"(fuori dalle conference seguite)")
    return righe


def salva_archivio(righe):
    righe = sorted(righe, key=lambda r: (r["Data"], r["Casa"]))
    ARCHIVIO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVIO.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNE, extrasaction="ignore")
        w.writeheader()
        w.writerows(righe)
    os.replace(tmp, ARCHIVIO)        # mai un archivio a metà
    return righe


def _settimana(r):
    """La settimana come numero, per confronti e ordinamenti."""
    try:
        return int(float(r.get("Settimana") or 0))
    except (ValueError, TypeError):
        return 0


def chiave(r):
    """Cosa identifica una partita, una volta per tutte.

    La data NON ne fa parte, ed è il punto. CollegeFootballData corregge
    l'orario d'inizio dopo che la partita è stata giocata, e l'orario è in
    UTC: per gli incontri serali della costa occidentale lo scarto fa
    cambiare il giorno. Con la data nella chiave la stessa partita entrava
    due volte — una vuota, con il giorno previsto, e una con il punteggio —
    e la prima restava in archivio per sempre.

    Stagione, tipo, settimana e squadre invece non cambiano mai.
    """
    return (str(r.get("Stagione") or ""),
            (r.get("Tipo") or "").strip().lower(),
            _settimana(r),
            (r.get("Casa") or "").strip(),
            (r.get("Ospite") or "").strip())


def _con_risultato(r):
    return num(r.get("PuntiCasa")) is not None and num(r.get("PuntiOspite")) is not None


def unisci_doppioni(righe):
    """Tiene una sola riga per partita, preferendo quella con il punteggio.

    Serve a ripulire una volta per tutte i doppioni lasciati dalla chiave
    precedente. A regime non ne trova più.
    """
    migliori = {}
    ordine = []
    uniti = 0
    for r in righe:
        k = chiave(r)
        if k not in migliori:
            migliori[k] = r
            ordine.append(k)
            continue
        uniti += 1
        vecchia = migliori[k]
        if _con_risultato(r) and not _con_risultato(vecchia):
            migliori[k] = r
        elif _con_risultato(r) == _con_risultato(vecchia) and r.get("Data", "") > vecchia.get("Data", ""):
            migliori[k] = r
    return [migliori[k] for k in ordine], uniti


def calcola_statistiche(righe, giocatori=None):
    squadre = defaultdict(lambda: defaultdict(lambda: {
        "partite": 0, "vittorie": 0, "sconfitte": 0, "pareggi": 0,
        "puntiFatti": 0, "puntiSubiti": 0,
        "partiteCasa": 0, "vittorieCasa": 0,
        "partiteFuori": 0, "vittorieFuori": 0,
        "conferenza": "",
    }))

    giocate = 0
    for r in righe:
        pc, po = num(r.get("PuntiCasa")), num(r.get("PuntiOspite"))
        if pc is None or po is None:
            continue
        giocate += 1
        stagione = r["Stagione"]
        for nome, propri, altrui, in_casa, conf in (
            (r["Casa"], pc, po, True, r.get("ConferenzaCasa")),
            (r["Ospite"], po, pc, False, r.get("ConferenzaOspite")),
        ):
            # In archivio restano anche gli avversari di categoria inferiore,
            # perché la partita conta per la squadra di prima divisione. In
            # classifica però non compaiono: non è il loro campionato.
            if not e_prima_divisione(conf):
                continue
            s = squadre[nome][stagione]
            s["partite"] += 1
            s["puntiFatti"] += propri
            s["puntiSubiti"] += altrui
            if conf:
                s["conferenza"] = conf
            vinta = propri > altrui
            if propri == altrui:
                s["pareggi"] += 1
            elif vinta:
                s["vittorie"] += 1
            else:
                s["sconfitte"] += 1
            if in_casa:
                s["partiteCasa"] += 1
                s["vittorieCasa"] += 1 if vinta else 0
            else:
                s["partiteFuori"] += 1
                s["vittorieFuori"] += 1 if vinta else 0

    def media(tot, n, cifre=1):
        return round(tot / n, cifre) if n else None

    lista = []
    for nome, per_stagione in squadre.items():
        stagioni = []
        for stagione, s in sorted(per_stagione.items(), reverse=True):
            stagioni.append({
                "stagione": stagione, "conferenza": s["conferenza"] or None,
                "partite": s["partite"], "vittorie": s["vittorie"],
                "sconfitte": s["sconfitte"], "pareggi": s["pareggi"],
                "percVittorie": media(s["vittorie"] * 100, s["partite"]),
                "mediaFatti": media(s["puntiFatti"], s["partite"]),
                "mediaSubiti": media(s["puntiSubiti"], s["partite"]),
                "differenza": s["puntiFatti"] - s["puntiSubiti"],
                "vittorieCasa": s["vittorieCasa"], "partiteCasa": s["partiteCasa"],
                "vittorieFuori": s["vittorieFuori"], "partiteFuori": s["partiteFuori"],
            })
        tot = {k: sum(x[k] for x in per_stagione.values())
               for k in ("partite", "vittorie", "sconfitte", "pareggi",
                         "puntiFatti", "puntiSubiti")}
        recente = stagioni[0] if stagioni else {}
        lista.append({
            "nome": nome,
            "nomeCompleto": nome,
            "conference": recente.get("conferenza"),
            "conferenza": recente.get("conferenza"),
            "partite": tot["partite"], "vittorie": tot["vittorie"],
            "sconfitte": tot["sconfitte"], "pareggi": tot["pareggi"],
            "percVittorie": media(tot["vittorie"] * 100, tot["partite"]),
            "mediaFatti": media(tot["puntiFatti"], tot["partite"]),
            "mediaSubiti": media(tot["puntiSubiti"], tot["partite"]),
            "differenza": tot["puntiFatti"] - tot["puntiSubiti"],
            "perStagione": stagioni,
        })
    lista.sort(key=lambda x: (-(x["percVittorie"] or 0), x["nome"]))

    # Ordinate come si legge un calendario: stagione, poi settimana dalla
    # prima all'ultima. La settimana va confrontata come numero, altrimenti
    # la 10 finirebbe prima della 9 e i raggruppamenti risulterebbero sfasati.
    def ordine(r):
        try:
            settimana = int(r.get("Settimana") or 0)
        except ValueError:
            settimana = 0
        return (r.get("Stagione") or "", settimana, r.get("Data") or "")

    # Tutte le partite delle stagioni conservate: la pagina filtra per anno,
    # quindi limitarle qui significherebbe mostrare calendari incompleti.
    recenti = sorted(righe, key=ordine)

    giocatori = giocatori or {}

    def prestazioni(squadra, stagione, settimana):
        return ((giocatori.get(str(stagione), {}) or {})
                .get(str(settimana), {}) or {}).get(squadra, [])[:5]

    ultime = []
    for r in recenti:
        ultime.append({
            "stagione": r["Stagione"], "settimana": r["Settimana"],
            "data": r["Data"], "casa": r["Casa"], "ospite": r["Ospite"],
            "pc": num(r["PuntiCasa"]), "po": num(r["PuntiOspite"]),
            "conferenzaCasa": r.get("ConferenzaCasa") or None,
            "stadio": r.get("Stadio") or None,
            "giocatoriCasa": prestazioni(r["Casa"], r["Stagione"], r["Settimana"]),
            "giocatoriOspite": prestazioni(r["Ospite"], r["Stagione"], r["Settimana"]),
        })

    return {
        "aggiornato": datetime.now(timezone.utc).isoformat(),
        "campionato": "College Football",
        "fonte": "ESPN (calendario, risultati, tabellini) · CollegeFootballData (SP+)",
        "stagioni": sorted({r["Stagione"] for r in righe}, reverse=True),
        "totalePartite": len(righe),
        "partiteGiocate": giocate,
        "squadre": lista,
        "conferences": sorted({s["conferenza"] for s in lista if s.get("conferenza")}),
        "ultimePartite": ultime,
    }



PRIVATO = Path(__file__).resolve().parent.parent / "data" / "privato_college.json"


def salva_privato(extra):
    """Blocchi della sezione privata (prossimo turno, indici, giocatori della giornata in corso).
    Il file è in .gitignore: lo legge fetch_duelli.py nello stesso workflow e lo cifra."""
    giornata = extra.get("giornata") or {}
    privato = {"prossima": extra.get("prossima"), "indici": extra.get("indici"),
               "duelliGiornata": giornata.pop("duelli", None)}
    PRIVATO.parent.mkdir(parents=True, exist_ok=True)
    tmp = PRIVATO.with_suffix(".tmp")
    tmp.write_text(json.dumps(privato, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PRIVATO)

def main():
    print("=" * 58)
    print("ARCHIVIO COLLEGE FOOTBALL")
    print("=" * 58)

    archivio = carica_archivio()
    print(f"\nArchivio esistente: {len(archivio)} partite")

    archivio, uniti = unisci_doppioni(archivio)
    if uniti:
        print(f"  {uniti} doppioni uniti (stessa partita con due date): "
              f"restano {len(archivio)} partite")

    indice = {chiave(r): r for r in archivio}
    prima = len(indice)

    corrente = stagione_corrente()
    forzate = set(stagioni_forzate())
    stagioni = stagioni_da_scaricare()
    print(f"Stagioni in archivio: {stagioni[-1]}–{stagioni[0]} ({len(stagioni)})")

    # Quante partite risultano già archiviate per ciascuna stagione: serve a
    # capire quali sono complete.
    quante = defaultdict(int)
    for r in archivio:
        quante[str(r.get("Stagione"))] += 1

    scaricate = 0
    partite_espn = {}
    for anno in stagioni:
        # Una stagione passata non cambia più: se è già in archivio per
        # intero non la si richiede. Con STAGIONI si forza comunque.
        if (anno < corrente and anno not in forzate
                and quante[str(anno)] >= MINIMO_PARTITE_STAGIONE):
            print(f"\nStagione {anno}: conclusa, {quante[str(anno)]} partite "
                  f"dall'archivio, nessuna chiamata")
            continue
        print(f"\nStagione {anno} (ESPN)")
        righe_espn = espn_college.partite_stagione(anno)
        if not righe_espn:
            print(f"    nessuna partita da ESPN: la stagione {anno} resta com'è in archivio")
            continue
        righe_espn = [r for r in righe_espn
                      if e_prima_divisione(r["ConferenzaCasa"]) or e_prima_divisione(r["ConferenzaOspite"])]
        vecchie = {k: r for k, r in indice.items() if k[0] == str(anno)}
        if vecchie and len(righe_espn) < 0.8 * len(vecchie):
            print(f"    ESPN ha {len(righe_espn)} partite contro {len(vecchie)} in archivio: risposta incompleta, "
                  "si aggiungono solo le partite nuove e i punteggi, senza togliere nulla")
            sostituisci = False
        else:
            sostituisci = True
        # il punteggio già in archivio non si perde se ESPN, per qualunque motivo, non lo ha
        con_punti = {(r["Tipo"], r["Casa"], r["Ospite"]): r for r in vecchie.values() if _con_risultato(r)}
        if sostituisci:
            # la stagione in corso si riprende com'è su ESPN: una partita spostata di settimana non resta doppia
            for k in vecchie:
                del indice[k]
        nuove = 0
        for r in righe_espn:
            riga = {c: r.get(c, "") for c in COLONNE}
            vecchia = con_punti.get((riga["Tipo"], riga["Casa"], riga["Ospite"]))
            if not _con_risultato(riga) and vecchia:
                riga["PuntiCasa"], riga["PuntiOspite"] = vecchia["PuntiCasa"], vecchia["PuntiOspite"]
            k = chiave(riga)
            if k not in vecchie:
                nuove += 1
            indice[k] = riga
        print(f"    {len(righe_espn)} partite ({nuove} nuove o spostate di settimana), "
              f"{sum(1 for r in righe_espn if r['PuntiCasa'] != '')} con il risultato")
        scaricate += len(righe_espn)
        partite_espn[anno] = righe_espn

    if not scaricate and prima == 0 and not uniti:
        print("\nNessun dato scaricato e archivio vuoto: esco.")
        raise SystemExit(1)

    # tiene solo le stagioni più recenti
    tenute = {str(a) for a in stagioni}
    tutte = [r for r in indice.values() if r.get("Stagione") in tenute]
    scartate = len(indice) - len(tutte)
    if scartate:
        print(f"\n{scartate} partite di stagioni oltre il limite di {MAX_STAGIONI} anni: scartate")

    righe = salva_archivio(tutte)
    print(f"Archivio salvato: {len(righe)} partite ({len(righe) - prima:+d})")

    print("\nGiocatori di riferimento")
    giocatori = carica_giocatori(stagioni, forzate, partite_espn)
    salva_archivio_giocatori(giocatori)

    stats = calcola_statistiche(righe, giocatori)

    # Giornata, prossimo turno e indici: 3 chiamate (più 1 a stagione per i loghi).
    # Blocchi aggiuntivi: se non riescono, l'archivio si aggiorna lo stesso.
    print("\nGiornata, prossimo turno e indici")
    try:
        import college_indici
        extra = college_indici.calcola(chiama, stats, corrente, partite_espn.get(corrente))
        # Prossimo turno, indici e giocatori chiave vanno solo nella sezione privata (cifrata da
        # fetch_duelli.py): qui restano in un file locale che non viene mai committato.
        for k in ("giornata", "loghi"):
            stats[k] = extra.get(k)
        salva_privato(extra)
    except Exception as e:
        print(f"  Blocchi aggiuntivi non calcolati: {type(e).__name__}: {e}. L'archivio è comunque aggiornato.")

    USCITA.parent.mkdir(parents=True, exist_ok=True)
    USCITA.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    print(f"\n{espn_college.riepilogo()}")
    print(f"\nSquadre: {len(stats['squadre'])}")
    print(f"Partite giocate: {stats['partiteGiocate']}/{stats['totalePartite']}")
    print(f"\n✓ Scritto {USCITA}")


if __name__ == "__main__":
    main()
