"""
Archivio Serie A — statistiche di squadra e designazioni arbitrali.

Due fonti indipendenti, unite sulla coppia (data, squadre):

  1. football-data.co.uk  -> risultati, cartellini di squadra, falli, tiri
     Licenza PDDL. Il campo arbitro per la Serie A è vuoto.

  2. Designazioni arbitrali (Lega / AIA) -> chi arbitra ogni partita
     Colma esattamente la lacuna della prima fonte.

Se la seconda fonte non risponde l'archivio resta valido: si aggiorna
comunque con i dati di squadra, e le designazioni si recuperano al giro
successivo. Nessuna delle due è indispensabile all'altra.
"""

import csv
import io
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import designazioni as dz

RADICE = Path(__file__).resolve().parent.parent
ARCHIVIO = RADICE / "data" / "serie_a.csv"
DESIGNAZIONI = RADICE / "data" / "designazioni_serie_a.json"
USCITA = RADICE / "docs" / "data_serie_a.json"

BASE_CSV = "https://www.football-data.co.uk/mmz4281"
CODICE = "I1"                      # I1 = Serie A
UA = "Mozilla/5.0 (compatible; PureStats/1.0)"

# Pagine da cui leggere le designazioni. Vengono provate in ordine:
# se la prima non risponde o cambia formato, si passa alla successiva.
FONTI_DESIGNAZIONI = [
    "https://www.aia-figc.it/news/?c=9",
]

COLONNE = [
    "Stagione", "Data", "Ora", "Casa", "Ospite",
    "GolCasa", "GolOspite", "Esito",
    "GolCasaPT", "GolOspitePT", "EsitoPT",
    "Arbitro", "Giornata", "QuartoUomo", "Var", "Avar",
    "TiriCasa", "TiriOspite", "TiriPortaCasa", "TiriPortaOspite",
    "FalliCasa", "FalliOspite", "CornerCasa", "CornerOspite",
    "GialliCasa", "GialliOspite", "RossiCasa", "RossiOspite",
]

MAPPA = {
    "Date": "Data", "Time": "Ora", "HomeTeam": "Casa", "AwayTeam": "Ospite",
    "FTHG": "GolCasa", "FTAG": "GolOspite", "FTR": "Esito",
    "HTHG": "GolCasaPT", "HTAG": "GolOspitePT", "HTR": "EsitoPT",
    "HS": "TiriCasa", "AS": "TiriOspite", "HST": "TiriPortaCasa", "AST": "TiriPortaOspite",
    "HF": "FalliCasa", "AF": "FalliOspite", "HC": "CornerCasa", "AC": "CornerOspite",
    "HY": "GialliCasa", "AY": "GialliOspite", "HR": "RossiCasa", "AR": "RossiOspite",
}

# football-data usa nomi propri: li allineiamo a quelli delle designazioni
ALIAS_FOOTBALL_DATA = {
    "Milan": "Milan", "Inter": "Inter", "Juventus": "Juventus", "Roma": "Roma",
    "Napoli": "Napoli", "Lazio": "Lazio", "Atalanta": "Atalanta",
    "Fiorentina": "Fiorentina", "Bologna": "Bologna", "Torino": "Torino",
    "Udinese": "Udinese", "Genoa": "Genoa", "Cagliari": "Cagliari",
    "Lecce": "Lecce", "Verona": "Verona", "Hellas Verona": "Verona",
    "Sassuolo": "Sassuolo", "Parma": "Parma", "Como": "Como",
    "Monza": "Monza", "Venezia": "Venezia", "Empoli": "Empoli",
    "Cremonese": "Cremonese", "Pisa": "Pisa", "Frosinone": "Frosinone",
    "Salernitana": "Salernitana", "Sampdoria": "Sampdoria", "Spezia": "Spezia",
}


def uniforma_squadra(nome):
    """Riporta il nome di una squadra alla forma di riferimento."""
    grezzo = (nome or "").strip()
    if not grezzo:
        return grezzo
    if grezzo in ALIAS_FOOTBALL_DATA:
        return ALIAS_FOOTBALL_DATA[grezzo]
    minuscolo = grezzo.lower()
    for k, v in ALIAS_FOOTBALL_DATA.items():
        if k.lower() == minuscolo:
            return v
    return grezzo


def scarica(url, descrizione):
    print(f"  GET {url}")
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=60) as r:
            grezzo = r.read()
    except HTTPError as e:
        print(f"    HTTP {e.code} — {descrizione} non disponibile")
        return None
    except URLError as e:
        print(f"    Rete: {e.reason}")
        return None
    except Exception as e:
        print(f"    Errore: {e}")
        return None

    for codifica in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return grezzo.decode(codifica)
        except UnicodeDecodeError:
            continue
    return grezzo.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- statistiche

def stagioni_da_scaricare():
    esplicite = os.environ.get("STAGIONI", "").strip()
    if esplicite:
        return [s.strip() for s in esplicite.split(",") if s.strip()]
    oggi = datetime.now(timezone.utc)
    anno = oggi.year if oggi.month >= 7 else oggi.year - 1
    return [f"{str(anno)[2:]}{str(anno + 1)[2:]}"]


def etichetta_stagione(codice):
    return f"20{codice[:2]}/{codice[2:]}"


def anno_inizio(codice):
    return 2000 + int(codice[:2])


def normalizza(testo, etichetta):
    righe = []
    for grezza in csv.DictReader(io.StringIO(testo)):
        if not (grezza.get("HomeTeam") or "").strip():
            continue
        riga = {c: "" for c in COLONNE}
        riga["Stagione"] = etichetta
        for originale, nostra in MAPPA.items():
            riga[nostra] = (grezza.get(originale) or "").strip()
        for campo in ("Casa", "Ospite"):
            riga[campo] = uniforma_squadra(riga[campo])
        righe.append(riga)
    return righe


def chiave_data(riga):
    data = (riga.get("Data") or "").strip()
    try:
        g, m, a = data.split("/")
        a = f"20{a}" if len(a) == 2 else a
        return f"{a}{int(m):02d}{int(g):02d}"
    except (ValueError, AttributeError):
        return "00000000"


def chiave(riga):
    return (chiave_data(riga), riga.get("Casa"), riga.get("Ospite"))


def carica_archivio():
    if not ARCHIVIO.exists():
        return []
    with ARCHIVIO.open(encoding="utf-8", newline="") as f:
        righe = list(csv.DictReader(f))
    # tollera archivi salvati con un insieme di colonne precedente
    for r in righe:
        for c in COLONNE:
            r.setdefault(c, "")
        for campo in ("Casa", "Ospite"):
            r[campo] = uniforma_squadra(r.get(campo))
    return righe


def salva_archivio(righe):
    righe = sorted(righe, key=lambda r: (chiave_data(r), r.get("Casa") or ""))
    ARCHIVIO.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVIO.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNE, extrasaction="ignore")
        w.writeheader()
        w.writerows(righe)
    return righe


# --------------------------------------------------------------- designazioni

def carica_designazioni():
    if not DESIGNAZIONI.exists():
        return []
    try:
        return json.loads(DESIGNAZIONI.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def salva_designazioni(elenco):
    """Deduplica su (data, casa, ospite) tenendo l'ultima versione."""
    indice = {}
    for d in elenco:
        k = (d.get("data"), d.get("casa"), d.get("ospite"))
        if all(k):
            indice[k] = d
    ordinate = sorted(indice.values(), key=lambda d: (d.get("data") or "", d.get("casa") or ""))
    DESIGNAZIONI.parent.mkdir(parents=True, exist_ok=True)
    DESIGNAZIONI.write_text(json.dumps(ordinate, ensure_ascii=False, indent=2), encoding="utf-8")
    return ordinate


def _testo_da_html(html):
    """Estrae il testo visibile da una pagina, senza librerie esterne."""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", html)
    testo = re.sub(r"<[^>]+>", " ", html)
    # entità HTML più comuni
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&#8211;", "–"),
                 ("&#8217;", "'"), ("&quot;", '"'), ("&lt;", "<"), ("&gt;", ">")):
        testo = testo.replace(a, b)
    testo = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), testo)
    return re.sub(r"[ \t]+", " ", testo)


def _dentro_stagione(data_iso, anno_inizio_stagione):
    """La stagione va da luglio dell'anno di inizio a giugno dell'anno dopo."""
    if not data_iso:
        return False
    try:
        anno, mese, _ = (int(x) for x in data_iso.split("-"))
    except ValueError:
        return False
    if anno == anno_inizio_stagione and mese >= 7:
        return True
    if anno == anno_inizio_stagione + 1 and mese <= 6:
        return True
    return False


def aggiorna_designazioni(anno_riferimento):
    """Raccoglie le designazioni dal file manuale e, se possibile, dal web.

    Il file `data/designazioni.txt` è la fonte principale: i siti ufficiali
    (Lega e AIA) bloccano gli accessi automatici o non espongono i dati in
    modo utilizzabile.

    Le designazioni con date fuori dalla stagione vengono scartate: capita
    quando si incolla per errore una pagina che contiene anche notizie
    vecchie, e senza questo controllo finirebbero in archivio.
    """
    trovate = []
    scartate = []

    def raccogli(estratte, etichetta):
        buone = []
        for d in estratte:
            if not (d.get("arbitro") and d.get("data")):
                continue
            if _dentro_stagione(d["data"], anno_riferimento):
                buone.append(d)
            else:
                scartate.append(d)
        return buone

    manuale = RADICE / "data" / "designazioni.txt"
    if manuale.exists():
        testo = manuale.read_text(encoding="utf-8")
        blocchi = [b.strip() for b in re.split(r"\n\s*(?:-{3,}|={3,})\s*\n|\n\s*\n\s*\n", testo)]
        blocchi = [b for b in blocchi if len(b) > 40]
        print(f"  File designazioni.txt: {len(blocchi)} blocchi")

        # Le date esplicite vanno raccolte sull'intero file, non blocco per
        # blocco: una partita che riporta solo "Domenica" non ha nel proprio
        # blocco alcun riferimento con cui calcolare la data, mentre gli
        # altri blocchi dello stesso file lo contengono.
        ancore = dz.raccogli_date(testo, anno_riferimento)
        if ancore:
            print(f"    Date di riferimento nel file: {ancore[0]} → {ancore[-1]}")

        for i, blocco in enumerate(blocchi, 1):
            utile = "\n".join(r for r in blocco.splitlines() if not r.strip().startswith("#"))
            if len(utile.strip()) < 40:
                continue

            giornata = dz.giornata_da_testo(utile)
            try:
                estratte = dz.analizza(utile, anno_riferimento=anno_riferimento,
                                       giornata=giornata, ancore_esterne=ancore)
            except Exception as e:
                print(f"    Blocco {i}: non interpretabile ({e})")
                continue

            buone = raccogli(estratte, f"blocco {i}")
            etichetta = f"giornata {giornata}" if giornata else "giornata non indicata"
            if buone:
                prima, ultima = buone[0]["data"], buone[-1]["data"]
                print(f"    Blocco {i} ({etichetta}): {len(buone)} designazioni, {prima} → {ultima}")
            else:
                print(f"    Blocco {i} ({etichetta}): nessuna designazione valida")
                print(f"      inizio del testo: {utile.strip()[:70]!r}")
            trovate.extend(buone)
    else:
        print("  File data/designazioni.txt assente")
        print("  (senza designazioni l'archivio resta valido, ma senza arbitri)")

    if scartate:
        stagione = f"20{str(anno_riferimento)[2:]}/{str(anno_riferimento + 1)[2:]}"
        print(f"\n  ATTENZIONE: {len(scartate)} designazioni scartate perché fuori")
        print(f"  dalla stagione {stagione} (luglio {anno_riferimento} – giugno {anno_riferimento + 1}):")
        for d in scartate[:5]:
            print(f"    {d['data']}  {d['casa']}-{d['ospite']}  {d['arbitro']}")
        if len(scartate) > 5:
            print(f"    ...e altre {len(scartate) - 5}")
        print("  Probabile causa: nel file c'è testo di giornate di altre stagioni.")

    return trovate


def applica_designazioni(righe, designazioni):
    """Scrive l'arbitro nelle partite dell'archivio che lo hanno vuoto."""
    per_chiave = {}
    for d in designazioni:
        data = (d.get("data") or "").replace("-", "")
        per_chiave[(data, d.get("casa"), d.get("ospite"))] = d

    aggiornate = 0
    for r in righe:
        k = (chiave_data(r), r.get("Casa"), r.get("Ospite"))
        d = per_chiave.get(k)
        if not d:
            continue
        if not (r.get("Arbitro") or "").strip():
            aggiornate += 1
        r["Arbitro"] = d.get("arbitro") or ""
        r["QuartoUomo"] = d.get("quartoUomo") or ""
        r["Var"] = d.get("var") or ""
        r["Avar"] = d.get("avar") or ""
        if d.get("giornata"):
            r["Giornata"] = str(d["giornata"])
    return aggiornate


def prossime_designazioni(designazioni, righe):
    """Designazioni di partite non ancora presenti in archivio: le prossime."""
    giocate = {(chiave_data(r), r.get("Casa"), r.get("Ospite")) for r in righe}
    future = []
    for d in designazioni:
        data = (d.get("data") or "").replace("-", "")
        if (data, d.get("casa"), d.get("ospite")) not in giocate:
            future.append(d)
    return sorted(future, key=lambda d: (d.get("data") or "", d.get("ora") or ""))


# ------------------------------------------------------------------ statistiche

def num(riga, campo):
    v = (riga.get(campo) or "").strip()
    if v == "":
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def calcola_statistiche(righe, future):
    arbitri = defaultdict(lambda: {
        "partite": 0, "gialli": 0, "rossi": 0, "falli": 0,
        "gialliCasa": 0, "gialliOspite": 0, "conDati": 0,
        "vittorieCasa": 0, "pareggi": 0, "vittorieOspite": 0,
        "perSquadra": defaultdict(lambda: {"partite": 0, "gialli": 0, "rossi": 0}),
        "perStagione": defaultdict(lambda: {
            "partite": 0, "gialli": 0, "rossi": 0, "falli": 0,
            "gialliCasa": 0, "gialliOspite": 0}),
        "elenco": [],
    })
    squadre = defaultdict(lambda: {
        "partite": 0, "gialli": 0, "rossi": 0, "falli": 0, "tiri": 0,
        "corner": 0, "conDati": 0, "gialliCasa": 0, "gialliOspite": 0,
        "partiteCasa": 0, "partiteOspite": 0,
        "perStagione": defaultdict(lambda: {
            "partite": 0, "gialli": 0, "rossi": 0, "falli": 0, "conDati": 0,
            "gialliCasa": 0, "gialliOspite": 0,
            "partiteCasa": 0, "partiteOspite": 0}),
    })

    complete = 0
    for r in righe:
        gc, go = num(r, "GialliCasa"), num(r, "GialliOspite")
        rc, ro = num(r, "RossiCasa"), num(r, "RossiOspite")
        fc, fo = num(r, "FalliCasa"), num(r, "FalliOspite")
        tc, to = num(r, "TiriCasa"), num(r, "TiriOspite")
        cc, co = num(r, "CornerCasa"), num(r, "CornerOspite")
        casa = (r.get("Casa") or "").strip()
        ospite = (r.get("Ospite") or "").strip()
        esito = (r.get("Esito") or "").strip()

        ha_disc = None not in (gc, go, rc, ro)
        if ha_disc:
            complete += 1

        arb = (r.get("Arbitro") or "").strip()
        if arb and ha_disc:
            a = arbitri[arb]
            a["partite"] += 1
            a["conDati"] += 1
            a["gialli"] += gc + go
            a["rossi"] += rc + ro
            a["gialliCasa"] += gc
            a["gialliOspite"] += go
            if None not in (fc, fo):
                a["falli"] += fc + fo
            if esito == "H": a["vittorieCasa"] += 1
            elif esito == "D": a["pareggi"] += 1
            elif esito == "A": a["vittorieOspite"] += 1

            for sq, gi, ros in ((casa, gc, rc), (ospite, go, ro)):
                if sq:
                    ps = a["perSquadra"][sq]
                    ps["partite"] += 1; ps["gialli"] += gi; ps["rossi"] += ros

            st = (r.get("Stagione") or "").strip()
            if st:
                p = a["perStagione"][st]
                p["partite"] += 1; p["gialli"] += gc + go; p["rossi"] += rc + ro
                p["gialliCasa"] += gc; p["gialliOspite"] += go
                if None not in (fc, fo): p["falli"] += fc + fo

            a["elenco"].append({
                "_ord": chiave_data(r),
                "stagione": r.get("Stagione"), "data": r.get("Data"),
                "casa": casa, "ospite": ospite,
                "gc": num(r, "GolCasa"), "go": num(r, "GolOspite"),
                "gialliCasa": gc, "gialliOspite": go,
                "rossiCasa": rc, "rossiOspite": ro,
                "falliCasa": fc, "falliOspite": fo,
            })

        for nome, gi, ros, fa, ti, co_, in_casa in (
            (casa, gc, rc, fc, tc, cc, True),
            (ospite, go, ro, fo, to, co, False),
        ):
            if not nome:
                continue
            s = squadre[nome]
            st_sq = (r.get("Stagione") or "").strip()
            ps = s["perStagione"][st_sq] if st_sq else None
            s["partite"] += 1
            if ps is not None:
                ps["partite"] += 1
            if None not in (gi, ros):
                s["conDati"] += 1; s["gialli"] += gi; s["rossi"] += ros
                if in_casa: s["gialliCasa"] += gi; s["partiteCasa"] += 1
                else: s["gialliOspite"] += gi; s["partiteOspite"] += 1
                if ps is not None:
                    ps["conDati"] += 1; ps["gialli"] += gi; ps["rossi"] += ros
                    if in_casa: ps["gialliCasa"] += gi; ps["partiteCasa"] += 1
                    else: ps["gialliOspite"] += gi; ps["partiteOspite"] += 1
            if fa is not None:
                s["falli"] += fa
                if ps is not None: ps["falli"] += fa
            if ti is not None: s["tiri"] += ti
            if co_ is not None: s["corner"] += co_

    def media(tot, n, cifre=2):
        return round(tot / n, cifre) if n else None

    # designazioni future per arbitro
    future_per_arbitro = defaultdict(list)
    for d in future:
        if d.get("arbitro"):
            future_per_arbitro[d["arbitro"]].append(d)

    lista_arbitri = []
    for nome, a in arbitri.items():
        n = a["conDati"]
        per_squadra = sorted([
            {"squadra": sq, "partite": v["partite"], "gialli": v["gialli"],
             "rossi": v["rossi"], "media": media(v["gialli"], v["partite"])}
            for sq, v in a["perSquadra"].items()
        ], key=lambda x: (-(x["media"] or 0), x["squadra"]))

        per_stagione = sorted([
            {"stagione": st, "partite": v["partite"], "gialli": v["gialli"],
             "rossi": v["rossi"],
             "media": media(v["gialli"] + v["rossi"], v["partite"]),
             "mediaGialli": media(v["gialli"], v["partite"]),
             "mediaRossi": media(v["rossi"], v["partite"]),
             "mediaFalli": media(v["falli"], v["partite"], 1),
             "squilibrio": media(v["gialliOspite"] - v["gialliCasa"], v["partite"]),
             "mediaGialliCasa": media(v["gialliCasa"], v["partite"]),
             "mediaGialliOspite": media(v["gialliOspite"], v["partite"])}
            for st, v in a["perStagione"].items()
        ], key=lambda x: x["stagione"])

        elenco = sorted(a["elenco"], key=lambda x: x.get("_ord", ""), reverse=True)[:30]
        for p in elenco:
            p.pop("_ord", None)

        lista_arbitri.append({
            "nome": nome, "partite": a["partite"],
            "gialli": a["gialli"], "rossi": a["rossi"],
            "mediaGialli": media(a["gialli"], n),
            "mediaRossi": media(a["rossi"], n),
            "mediaCartellini": media(a["gialli"] + a["rossi"], n),
            "mediaFalli": media(a["falli"], n, 1),
            "gialliPerFallo": media(a["gialli"] / a["falli"] * 100, 1, 1) if a["falli"] else None,
            "squilibrioCasaOspite": media(a["gialliOspite"] - a["gialliCasa"], n),
            "mediaGialliCasa": media(a["gialliCasa"], n),
            "mediaGialliOspite": media(a["gialliOspite"], n),
            "vittorieCasa": a["vittorieCasa"], "pareggi": a["pareggi"],
            "vittorieOspite": a["vittorieOspite"],
            "percVittorieCasa": media(a["vittorieCasa"] * 100, n, 1),
            "perSquadra": per_squadra, "perStagione": per_stagione, "elenco": elenco,
            "prossime": sorted(future_per_arbitro.get(nome, []),
                               key=lambda d: (d.get("data") or ""))[:5],
        })
    lista_arbitri.sort(key=lambda x: (-(x["mediaCartellini"] or 0), x["nome"]))

    # Arbitri designati ma senza partite in archivio: compaiono comunque
    noti = {a["nome"] for a in lista_arbitri}
    for nome, ds in future_per_arbitro.items():
        if nome not in noti:
            lista_arbitri.append({
                "nome": nome, "partite": 0, "gialli": 0, "rossi": 0,
                "mediaGialli": None, "mediaRossi": None, "mediaCartellini": None,
                "mediaFalli": None, "gialliPerFallo": None,
                "squilibrioCasaOspite": None, "mediaGialliCasa": None,
                "mediaGialliOspite": None, "vittorieCasa": 0, "pareggi": 0,
                "vittorieOspite": 0, "percVittorieCasa": None,
                "perSquadra": [], "perStagione": [], "elenco": [],
                "prossime": sorted(ds, key=lambda d: (d.get("data") or ""))[:5],
            })

    lista_squadre = sorted([
        {"nome": nome, "partite": s["partite"], "gialli": s["gialli"], "rossi": s["rossi"],
         "mediaGialli": media(s["gialli"], s["conDati"]),
         "mediaRossi": media(s["rossi"], s["conDati"]),
         "mediaFalli": media(s["falli"], s["conDati"], 1),
         "mediaGialliCasa": media(s["gialliCasa"], s["partiteCasa"]),
         "mediaGialliOspite": media(s["gialliOspite"], s["partiteOspite"]),
         "perStagione": sorted([
             {"stagione": st, "partite": v["partite"],
              "gialli": v["gialli"], "rossi": v["rossi"],
              "mediaGialli": media(v["gialli"], v["conDati"]),
              "mediaRossi": media(v["rossi"], v["conDati"]),
              "mediaFalli": media(v["falli"], v["conDati"], 1),
              "mediaGialliCasa": media(v["gialliCasa"], v["partiteCasa"]),
              "mediaGialliOspite": media(v["gialliOspite"], v["partiteOspite"])}
             for st, v in s["perStagione"].items()], key=lambda x: x["stagione"])}
        for nome, s in squadre.items()
    ], key=lambda x: (-(x["mediaGialli"] or 0), x["nome"]))

    ultime = []
    for r in righe[-40:]:
        ultime.append({
            "stagione": r.get("Stagione"), "data": r.get("Data"),
            "casa": r.get("Casa"), "ospite": r.get("Ospite"),
            "gc": num(r, "GolCasa"), "go": num(r, "GolOspite"),
            "arbitro": (r.get("Arbitro") or "").strip(),
            "gialliCasa": num(r, "GialliCasa"), "gialliOspite": num(r, "GialliOspite"),
            "rossiCasa": num(r, "RossiCasa"), "rossiOspite": num(r, "RossiOspite"),
            "falliCasa": num(r, "FalliCasa"), "falliOspite": num(r, "FalliOspite"),
        })
    ultime.reverse()

    con_arbitro = sum(1 for r in righe if (r.get("Arbitro") or "").strip())

    return {
        "aggiornato": datetime.now(timezone.utc).isoformat(),
        "campionato": "Serie A",
        "fonte": "football-data.co.uk (PDDL) · designazioni AIA/Lega Serie A",
        "stagioni": sorted({r.get("Stagione", "") for r in righe if r.get("Stagione")}),
        "totalePartite": len(righe),
        "partiteConDisciplina": complete,
        "partiteConArbitro": con_arbitro,
        "arbitri": lista_arbitri,
        "squadre": lista_squadre,
        "ultimePartite": ultime,
        "prossimeDesignazioni": future[:20],
    }


def main():
    print("=" * 58)
    print("ARCHIVIO SERIE A")
    print("=" * 58)

    archivio = carica_archivio()
    print(f"\nArchivio esistente: {len(archivio)} partite")
    indice = {chiave(r): r for r in archivio}
    prima = len(indice)

    anno_rif = None
    for codice in stagioni_da_scaricare():
        etichetta = etichetta_stagione(codice)
        anno_rif = anno_inizio(codice)
        print(f"\nStagione {etichetta}")
        testo = scarica(f"{BASE_CSV}/{codice}/{CODICE}.csv", "statistiche")
        if testo is None:
            continue
        righe = normalizza(testo, etichetta)
        print(f"    {len(righe)} partite nel file")
        nuove = 0
        for riga in righe:
            k = chiave(riga)
            if k in indice:
                # conserva i campi arbitrali già acquisiti
                for campo in ("Arbitro", "Giornata", "QuartoUomo", "Var", "Avar"):
                    if not riga.get(campo):
                        riga[campo] = indice[k].get(campo, "")
            else:
                nuove += 1
            indice[k] = riga
        print(f"    {nuove} nuove")

    if anno_rif is None:
        oggi = datetime.now(timezone.utc)
        anno_rif = oggi.year if oggi.month >= 7 else oggi.year - 1

    print("\nDesignazioni arbitrali")
    nuove_des = aggiorna_designazioni(anno_rif)
    tutte_des = salva_designazioni(carica_designazioni() + nuove_des)
    print(f"  Archivio designazioni: {len(tutte_des)}")

    righe = list(indice.values())
    applicate = applica_designazioni(righe, tutte_des)
    if applicate:
        print(f"  Arbitro assegnato a {applicate} partite")

    righe = salva_archivio(righe)
    print(f"\nArchivio salvato: {len(righe)} partite ({len(righe) - prima:+d})")

    future = prossime_designazioni(tutte_des, righe)
    if future:
        print(f"Designazioni future: {len(future)}")
        for d in future[:3]:
            print(f"  {d['data']} {d['casa']}-{d['ospite']} → {d['arbitro']}")

    stats = calcola_statistiche(righe, future)
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    USCITA.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nArbitri: {len(stats['arbitri'])} · Squadre: {len(stats['squadre'])}")
    print(f"Partite con arbitro: {stats['partiteConArbitro']}/{stats['totalePartite']}")
    if stats["arbitri"] and stats["arbitri"][0]["partite"]:
        t = stats["arbitri"][0]
        print(f"Più severo: {t['nome']} — {t['mediaCartellini']} cartellini/partita")


if __name__ == "__main__":
    main()
