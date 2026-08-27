"""
Archivio LaLiga — statistiche disciplinari e designazioni arbitrali.

A differenza della Serie A, qui le designazioni sono recuperabili in
automatico: la RFEF pubblica PDF con URL costruibile a tavolino e testo
perfettamente strutturato.

Due fonti:
  1. football-data.co.uk (SP1.csv) — cartellini e falli di squadra.
     Licenza PDDL. Non contiene la colonna arbitro.
  2. PDF del Comité Técnico de Árbitros — chi arbitra ogni partita.

L'archivio è centrato sugli arbitri: le statistiche offensive presenti
nel CSV vengono conservate nel file ma non entrano nelle medie.
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
import designaciones as dg

RADICE = Path(__file__).resolve().parent.parent
ARCHIVIO = RADICE / "data" / "la_liga.csv"
DESIGNAZIONI = RADICE / "data" / "designaciones_la_liga.json"
USCITA = RADICE / "docs" / "data_la_liga.json"

BASE_CSV = "https://www.football-data.co.uk/mmz4281"
CODICE = "SP1"
BASE_PDF = "https://rfef.es/sites/default/files"
UA = "Mozilla/5.0 (compatible; PureStats/1.0)"

# I PDF hanno un file per ogni giorno di gara della giornata
GIORNI = ["viernes", "sabado", "domingo", "lunes", "jueves", "martes", "miercoles"]

COLONNE = [
    "Stagione", "Data", "Ora", "Casa", "Ospite",
    "GolCasa", "GolOspite", "Esito",
    "Arbitro", "Giornata", "QuartoUomo", "Var", "Avar",
    "FalliCasa", "FalliOspite",
    "GialliCasa", "GialliOspite", "RossiCasa", "RossiOspite",
]

MAPPA = {
    "Date": "Data", "Time": "Ora", "HomeTeam": "Casa", "AwayTeam": "Ospite",
    "FTHG": "GolCasa", "FTAG": "GolOspite", "FTR": "Esito",
    "HF": "FalliCasa", "AF": "FalliOspite",
    "HY": "GialliCasa", "AY": "GialliOspite", "HR": "RossiCasa", "AR": "RossiOspite",
}


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


def url_pdf(anno, giornata, giorno):
    """Costruisce l'indirizzo del PDF ufficiale.

    Esempio reale:
    designaciones_1a_division_masculina_-_temp_2026-27_-_jornada_2_sabado.pdf
    """
    temp = f"{anno}-{str(anno + 1)[2:]}"
    return (f"{BASE_PDF}/designaciones_1a_division_masculina_-_temp_{temp}"
            f"_-_jornada_{giornata}_{giorno}.pdf")


def giornate_da_cercare(designazioni_note, anno):
    """Decide quali giornate provare a scaricare.

    Riparte dall'ultima giornata già acquisita e prova le successive:
    evita di ripetere ogni volta il download di tutto lo storico.
    """
    esplicite = os.environ.get("GIORNATE", "").strip()
    if esplicite:
        return [int(g) for g in re.split(r"[,\s]+", esplicite) if g.isdigit()]

    note = {d.get("giornata") for d in designazioni_note if d.get("giornata")}
    inizio = max(note) if note else 1
    # ricontrolla l'ultima nota (potrebbero essere usciti altri giorni)
    # e guarda le tre successive
    return list(range(inizio, inizio + 4))


def aggiorna_designazioni(anno, designazioni_note):
    """Scarica e interpreta i PDF delle designazioni."""
    trovate = []
    giornate = giornate_da_cercare(designazioni_note, anno)
    print(f"  Giornate da controllare: {giornate}")

    for giornata in giornate:
        per_giornata = 0
        for giorno in GIORNI:
            dati = scarica(url_pdf(anno, giornata, giorno),
                           f"giornata {giornata} {giorno}", binario=True)
            if not dati:
                continue
            try:
                testo = dg.testo_da_pdf(dati)
            except Exception as e:
                print(f"    PDF illeggibile: {e}")
                continue

            estratte = dg.analizza(testo, giornata=dg.giornata_da_testo(testo) or giornata)
            valide = [d for d in estratte if d.get("arbitro") and d.get("data")]

            # Conta le intestazioni di partita presenti nel PDF: se sono più
            # delle designazioni riconosciute, qualche squadra non è in elenco
            attese = len(dg.INTESTAZIONE.findall(testo))
            if attese > len(estratte):
                print(f"    ATTENZIONE: nel PDF ci sono {attese} partite ma ne "
                      f"riconosco {len(estratte)}")
                for riga in dg.righe_non_riconosciute(testo):
                    print(f"      squadre non in elenco: {riga}")

            if valide:
                print(f"    Giornata {giornata} {giorno}: {len(valide)} designazioni")
                trovate.extend(valide)
                per_giornata += len(valide)

        if per_giornata == 0:
            print(f"    Giornata {giornata}: nessun PDF disponibile")

    # File manuale di riserva, se un giorno il formato cambiasse
    manuale = RADICE / "data" / "designaciones.txt"
    if manuale.exists():
        testo = manuale.read_text(encoding="utf-8")
        estratte = dg.analizza(testo)
        valide = [d for d in estratte if d.get("arbitro") and d.get("data")]
        if valide:
            print(f"  File manuale: {len(valide)} designazioni")
            trovate.extend(valide)

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
        r["QuartoUomo"] = d.get("quartoUomo") or ""
        r["Var"] = d.get("var") or ""
        r["Avar"] = d.get("avar") or ""
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
        "campionato": "LaLiga",
        "fonte": "football-data.co.uk (PDDL) · designazioni RFEF/CTA",
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
    print("ARCHIVIO LALIGA")
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

    print("\nDesignazioni arbitrali (RFEF)")
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
