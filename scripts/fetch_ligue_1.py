"""
Archivio Ligue 1 — statistiche disciplinari e designazioni arbitrali.

Due fonti:
  1. football-data.co.uk (F1.csv) — cartellini e falli di squadra.
     Licenza PDDL. Il campo arbitro esiste ma è sempre vuoto.
  2. deux-zero.com — chi arbitra ogni partita.

Nota sull'uso della seconda fonte: è un sito indipendente, non una
fonte ufficiale né sotto licenza aperta. Lo script scarica per questo
la sola giornata corrente, con una pausa fra le richieste, per un
volume di traffico equivalente a quello di una persona che consulta
il sito. Lo scaricamento dello storico è disattivato per scelta: si
attiva solo impostando GIORNATE, e conviene farlo dopo aver chiesto
il consenso al gestore del sito.

L'archivio è centrato sugli arbitri: le statistiche offensive presenti
nel CSV vengono conservate nel file ma non entrano nelle medie.
"""

import csv
import io
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import designations as dg

RADICE = Path(__file__).resolve().parent.parent
ARCHIVIO = RADICE / "data" / "ligue_1.csv"
DESIGNAZIONI = RADICE / "data" / "designations_ligue_1.json"
USCITA = RADICE / "docs" / "data_ligue_1.json"

BASE_CSV = "https://www.football-data.co.uk/mmz4281"
CODICE = "F1"
BASE_DESIG = "https://www.deux-zero.com/ligue-1/arbitrage-designations-journee/edition"
UA = "Mozilla/5.0 (compatible; PureStats/1.0)"

# Pausa fra una richiesta e l'altra al sito delle designazioni
PAUSA = 3.0

COLONNE = [
    "Stagione", "Data", "Ora", "Casa", "Ospite",
    "GolCasa", "GolOspite", "Esito",
    "Arbitro", "Giornata",
    "FalliCasa", "FalliOspite",
    "GialliCasa", "GialliOspite", "RossiCasa", "RossiOspite",
]

MAPPA = {
    "Date": "Data", "Time": "Ora", "HomeTeam": "Casa", "AwayTeam": "Ospite",
    "FTHG": "GolCasa", "FTAG": "GolOspite", "FTR": "Esito",
    "HF": "FalliCasa", "AF": "FalliOspite",
    "HY": "GialliCasa", "AY": "GialliOspite", "HR": "RossiCasa", "AR": "RossiOspite",
}


ALIAS_CSV = {
    "paris sg": "Paris SG", "paris s-g": "Paris SG", "psg": "Paris SG",
    "paris fc": "Paris FC", "st etienne": "St Etienne",
    "saint-etienne": "St Etienne", "st-etienne": "St Etienne",
    "ajaccio gfco": "Ajaccio", "le havre": "Le Havre",
}


def uniforma_squadra(nome):
    """Riporta il nome di una squadra alla forma di riferimento.

    La fonte cambia nel tempo la denominazione di alcune squadre: senza
    uniformarle la stessa partita entrerebbe due volte in archivio, con
    due chiavi diverse.
    """
    grezzo = (nome or "").strip()
    if not grezzo:
        return grezzo
    chiave = re.sub(r"\s+", " ", grezzo.lower()).strip()
    if chiave in ALIAS_CSV:
        return ALIAS_CSV[chiave]
    senza_punti = re.sub(r"\s+", " ", chiave.replace(".", "")).strip()
    return ALIAS_CSV.get(senza_punti, grezzo)


def scarica(url, descrizione, binario=False):
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

    if binario:
        return grezzo
    for codifica in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return grezzo.decode(codifica)
        except UnicodeDecodeError:
            continue
    return grezzo.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- stagioni

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


# --------------------------------------------------------------- CSV

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


# ------------------------------------------------------------ designazioni

def carica_designazioni():
    if not DESIGNAZIONI.exists():
        return []
    try:
        return json.loads(DESIGNAZIONI.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def salva_designazioni(elenco):
    indice = {}
    for d in elenco:
        k = (d.get("data"), d.get("casa"), d.get("ospite"))
        if all(k):
            indice[k] = d
    ordinate = sorted(indice.values(), key=lambda d: (d.get("data") or "", d.get("ora") or ""))
    DESIGNAZIONI.parent.mkdir(parents=True, exist_ok=True)
    DESIGNAZIONI.write_text(json.dumps(ordinate, ensure_ascii=False, indent=2), encoding="utf-8")
    return ordinate


def url_designazioni(anno):
    """Pagina delle designazioni della stagione, es. .../edition/2026-2027"""
    return f"{BASE_DESIG}/{anno}-{anno + 1}"


def _testo_da_html(html):
    """Estrae il testo visibile da una pagina, senza librerie esterne."""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|a)>", "\n", html)
    testo = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&#8211;", "-"),
                 ("&#8217;", "'"), ("&quot;", '"'), ("&lt;", "<"), ("&gt;", ">")):
        testo = testo.replace(a, b)
    testo = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), testo)
    return re.sub(r"[ \t]+", " ", testo)


def aggiorna_designazioni(anno, designazioni_note):
    """Scarica le designazioni della giornata corrente.

    Di norma esegue una sola richiesta. Lo scaricamento di più giornate
    va richiesto esplicitamente con la variabile GIORNATE, e resta a
    discrezione di chi lo attiva verificare che sia lecito farlo.
    """
    trovate = []

    giornate = os.environ.get("GIORNATE", "").strip()
    if giornate:
        elenco = [g for g in re.split(r"[,\s]+", giornate) if g.isdigit()]
        print(f"  Giornate richieste esplicitamente: {elenco}")
        print("  Verifica di avere il consenso del sito per questo volume di richieste.")
    else:
        elenco = [None]   # solo la pagina corrente

    for i, giornata in enumerate(elenco):
        if i > 0:
            time.sleep(PAUSA)
        url = url_designazioni(anno)
        if giornata:
            url += f"/journee/{giornata}"

        html = scarica(url, "designazioni")
        if not html:
            continue

        testo = _testo_da_html(html)
        try:
            estratte = dg.analizza(testo, giornata=int(giornata) if giornata else
                                   dg.giornata_da_testo(testo))
        except Exception as e:
            print(f"    Interpretazione fallita: {e}")
            continue

        valide = [d for d in estratte if d.get("arbitro") and d.get("data")]
        if valide:
            prima, ultima = valide[0]["data"], valide[-1]["data"]
            print(f"    {len(valide)} designazioni, {prima} -> {ultima}")
        else:
            print("    Nessuna designazione riconosciuta nella pagina")
        trovate.extend(valide)

    # File manuale di riserva
    manuale = RADICE / "data" / "designations.txt"
    if manuale.exists():
        testo = manuale.read_text(encoding="utf-8")
        try:
            estratte = dg.analizza(testo, giornata=dg.giornata_da_testo(testo))
            valide = [d for d in estratte if d.get("arbitro") and d.get("data")]
            if valide:
                print(f"  File manuale: {len(valide)} designazioni")
                trovate.extend(valide)
        except Exception as e:
            print(f"  File manuale non interpretabile: {e}")

    return trovate


def applica_designazioni(righe, designazioni):
    per_chiave = {}
    for d in designazioni:
        data = (d.get("data") or "").replace("-", "")
        per_chiave[(data, d.get("casa"), d.get("ospite"))] = d

    aggiornate = 0
    for r in righe:
        d = per_chiave.get((chiave_data(r), r.get("Casa"), r.get("Ospite")))
        if not d:
            continue
        if not (r.get("Arbitro") or "").strip():
            aggiornate += 1
        r["Arbitro"] = d.get("arbitro") or ""
        if d.get("giornata"):
            r["Giornata"] = str(d["giornata"])
    return aggiornate


def prossime_designazioni(designazioni, righe):
    giocate = {(chiave_data(r), r.get("Casa"), r.get("Ospite")) for r in righe}
    future = [d for d in designazioni
              if ((d.get("data") or "").replace("-", ""), d.get("casa"), d.get("ospite")) not in giocate]
    return sorted(future, key=lambda d: (d.get("data") or "", d.get("ora") or ""))


# ------------------------------------------------------------- statistiche

def num(riga, campo):
    v = (riga.get(campo) or "").strip()
    if v == "":
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def calcola_statistiche(righe, future):
    """Statistiche centrate sugli arbitri e sulla disciplina.

    Non calcola tiri, corner o altre metriche offensive: l'archivio
    serve a misurare la severità arbitrale, non il rendimento sportivo.
    """
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
        "partite": 0, "gialli": 0, "rossi": 0, "falli": 0, "conDati": 0,
        "gialliCasa": 0, "gialliOspite": 0, "partiteCasa": 0, "partiteOspite": 0,
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

        for nome, gi, ros, fa, in_casa in (
            (casa, gc, rc, fc, True), (ospite, go, ro, fo, False),
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

    def media(tot, n, cifre=2):
        return round(tot / n, cifre) if n else None

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

    return {
        "aggiornato": datetime.now(timezone.utc).isoformat(),
        "campionato": "Ligue 1",
        "fonte": "football-data.co.uk (PDDL) · designazioni deux-zero.com",
        "stagioni": sorted({r.get("Stagione", "") for r in righe if r.get("Stagione")}),
        "totalePartite": len(righe),
        "partiteConDisciplina": complete,
        "partiteConArbitro": sum(1 for r in righe if (r.get("Arbitro") or "").strip()),
        "arbitri": lista_arbitri,
        "squadre": lista_squadre,
        "ultimePartite": ultime,
        "prossimeDesignazioni": future[:20],
    }


def main():
    print("=" * 58)
    print("ARCHIVIO LIGUE 1")
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
                for campo in ("Arbitro", "Giornata"):
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
    note = carica_designazioni()
    nuove_des = aggiorna_designazioni(anno_rif, note)
    tutte_des = salva_designazioni(note + nuove_des)
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
