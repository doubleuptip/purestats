"""
Archivio Premier League — costruzione incrementale.

Scarica il CSV di football-data.co.uk, lo unisce all'archivio locale
senza creare duplicati, e ricalcola le medie di arbitri, squadre e partite.

Fonte: https://www.football-data.co.uk/englandm.php
Licenza dei dati: Public Domain Dedication and License (PDDL)

Nessuna chiave API, nessun limite di richieste.
"""

import csv
import io
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

RADICE = Path(__file__).resolve().parent.parent
ARCHIVIO = RADICE / "data" / "premier_league.csv"
USCITA = RADICE / "docs" / "data.json"

BASE = "https://www.football-data.co.uk/mmz4281"
CODICE_LEGA = "E0"          # E0 = Premier League
UA = "Mozilla/5.0 (compatible; PureStats/1.0)"

# Colonne che teniamo. Le quote dei bookmaker vengono scartate:
# non servono e farebbero pesare l'archivio inutilmente.
COLONNE = [
    "Stagione", "Data", "Ora", "Casa", "Ospite",
    "GolCasa", "GolOspite", "Esito",
    "GolCasaPT", "GolOspitePT", "EsitoPT",
    "Arbitro",
    "TiriCasa", "TiriOspite", "TiriPortaCasa", "TiriPortaOspite",
    "FalliCasa", "FalliOspite", "CornerCasa", "CornerOspite",
    "GialliCasa", "GialliOspite", "RossiCasa", "RossiOspite",
]

# Mappa colonna originale -> nostra colonna
MAPPA = {
    "Date": "Data", "Time": "Ora", "HomeTeam": "Casa", "AwayTeam": "Ospite",
    "FTHG": "GolCasa", "FTAG": "GolOspite", "FTR": "Esito",
    "HTHG": "GolCasaPT", "HTAG": "GolOspitePT", "HTR": "EsitoPT",
    "Referee": "Arbitro",
    "HS": "TiriCasa", "AS": "TiriOspite", "HST": "TiriPortaCasa", "AST": "TiriPortaOspite",
    "HF": "FalliCasa", "AF": "FalliOspite", "HC": "CornerCasa", "AC": "CornerOspite",
    "HY": "GialliCasa", "AY": "GialliOspite", "HR": "RossiCasa", "AR": "RossiOspite",
}

NUMERICHE = [
    "GolCasa", "GolOspite", "GolCasaPT", "GolOspitePT",
    "TiriCasa", "TiriOspite", "TiriPortaCasa", "TiriPortaOspite",
    "FalliCasa", "FalliOspite", "CornerCasa", "CornerOspite",
    "GialliCasa", "GialliOspite", "RossiCasa", "RossiOspite",
]


def stagioni_da_scaricare():
    """Restituisce i codici stagione da scaricare, es. ['2627'].

    Di default solo la stagione corrente. Impostando la variabile
    STAGIONI si possono scaricare più annate: STAGIONI="2425,2526,2627"
    """
    esplicite = os.environ.get("STAGIONI", "").strip()
    if esplicite:
        return [s.strip() for s in esplicite.split(",") if s.strip()]

    oggi = datetime.now(timezone.utc)
    anno = oggi.year if oggi.month >= 7 else oggi.year - 1
    return [f"{str(anno)[2:]}{str(anno + 1)[2:]}"]


def etichetta_stagione(codice):
    """'2627' -> '2026/27'"""
    return f"20{codice[:2]}/{codice[2:]}"


def scarica(codice_stagione):
    url = f"{BASE}/{codice_stagione}/{CODICE_LEGA}.csv"
    print(f"  GET {url}")
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=60) as r:
            grezzo = r.read()
    except HTTPError as e:
        print(f"    HTTP {e.code} — file non ancora pubblicato o inesistente")
        return None
    except URLError as e:
        print(f"    Rete non raggiungibile: {e.reason}")
        return None

    # I file usano codifiche miste a seconda dell'annata
    for codifica in ("utf-8-sig", "latin-1"):
        try:
            return grezzo.decode(codifica)
        except UnicodeDecodeError:
            continue
    return grezzo.decode("utf-8", errors="replace")


def normalizza(testo, etichetta):
    """Converte il CSV originale nel nostro formato."""
    righe = []
    lettore = csv.DictReader(io.StringIO(testo))

    for grezza in lettore:
        # Le righe vuote in coda ai file sono frequenti
        if not (grezza.get("HomeTeam") or "").strip():
            continue

        riga = {c: "" for c in COLONNE}
        riga["Stagione"] = etichetta

        for originale, nostra in MAPPA.items():
            valore = (grezza.get(originale) or "").strip()
            riga[nostra] = valore

        # I campi statistici mancanti diventano stringa vuota, non zero:
        # zero significherebbe "zero cartellini", vuoto significa "non rilevato"
        righe.append(riga)

    return righe


def chiave(riga):
    """Identifica univocamente una partita."""
    return (riga["Stagione"], riga["Data"], riga["Casa"], riga["Ospite"])


def carica_archivio():
    if not ARCHIVIO.exists():
        return []
    with ARCHIVIO.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def salva_archivio(righe):
    def ordinamento(r):
        try:
            g, m, a = r["Data"].split("/")
            a = f"20{a}" if len(a) == 2 else a
            return (a, m, g, r["Casa"])
        except (ValueError, AttributeError):
            return ("", "", "", r.get("Casa", ""))

    righe = sorted(righe, key=ordinamento)
    ARCHIVIO.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVIO.open("w", encoding="utf-8", newline="") as f:
        scrittore = csv.DictWriter(f, fieldnames=COLONNE)
        scrittore.writeheader()
        scrittore.writerows(righe)


def num(riga, campo):
    """Legge un campo numerico, None se assente."""
    v = (riga.get(campo) or "").strip()
    if v == "":
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def calcola_statistiche(righe):
    """Costruisce le aggregazioni per la dashboard."""

    arbitri = defaultdict(lambda: {
        "partite": 0, "gialli": 0, "rossi": 0, "falli": 0,
        "gialliCasa": 0, "gialliOspite": 0, "conDati": 0,
        "rigori": 0, "vittorieCasa": 0, "pareggi": 0, "vittorieOspite": 0,
        "perSquadra": defaultdict(lambda: {"partite": 0, "gialli": 0, "rossi": 0}),
        "perStagione": defaultdict(lambda: {
            "partite": 0, "gialli": 0, "rossi": 0, "falli": 0,
            "gialliCasa": 0, "gialliOspite": 0,
        }),
        "elenco": [],
    })
    squadre = defaultdict(lambda: {
        "partite": 0, "gialli": 0, "rossi": 0, "falli": 0,
        "tiri": 0, "corner": 0, "conDati": 0,
        "gialliCasa": 0, "gialliOspite": 0, "partiteCasa": 0, "partiteOspite": 0,
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

        ha_disciplina = None not in (gc, go, rc, ro)
        if ha_disciplina:
            complete += 1

        # --- arbitri ---
        arb = (r.get("Arbitro") or "").strip()
        if arb and ha_disciplina:
            a = arbitri[arb]
            a["partite"] += 1
            a["conDati"] += 1
            a["gialli"] += gc + go
            a["rossi"] += rc + ro
            a["gialliCasa"] += gc
            a["gialliOspite"] += go
            if None not in (fc, fo):
                a["falli"] += fc + fo

            if esito == "H":
                a["vittorieCasa"] += 1
            elif esito == "D":
                a["pareggi"] += 1
            elif esito == "A":
                a["vittorieOspite"] += 1

            for squadra, gialli, rossi in ((casa, gc, rc), (ospite, go, ro)):
                if not squadra:
                    continue
                ps = a["perSquadra"][squadra]
                ps["partite"] += 1
                ps["gialli"] += gialli
                ps["rossi"] += rossi

            stag = (r.get("Stagione") or "").strip()
            if stag:
                pst = a["perStagione"][stag]
                pst["partite"] += 1
                pst["gialli"] += gc + go
                pst["rossi"] += rc + ro
                pst["gialliCasa"] += gc
                pst["gialliOspite"] += go
                if None not in (fc, fo):
                    pst["falli"] += fc + fo

            a["elenco"].append({
                "stagione": r.get("Stagione"), "data": r.get("Data"),
                "casa": casa, "ospite": ospite,
                "gc": num(r, "GolCasa"), "go": num(r, "GolOspite"),
                "gialliCasa": gc, "gialliOspite": go,
                "rossiCasa": rc, "rossiOspite": ro,
                "falliCasa": fc, "falliOspite": fo,
            })

        # --- squadre ---
        for nome, gialli, rossi, falli, tiri, corner, in_casa in (
            (casa, gc, rc, fc, tc, cc, True),
            (ospite, go, ro, fo, to, co, False),
        ):
            if not nome:
                continue
            s = squadre[nome]
            s["partite"] += 1
            if None not in (gialli, rossi):
                s["conDati"] += 1
                s["gialli"] += gialli
                s["rossi"] += rossi
                if in_casa:
                    s["gialliCasa"] += gialli
                    s["partiteCasa"] += 1
                else:
                    s["gialliOspite"] += gialli
                    s["partiteOspite"] += 1
            if falli is not None:
                s["falli"] += falli
            if tiri is not None:
                s["tiri"] += tiri
            if corner is not None:
                s["corner"] += corner

    def media(tot, n, cifre=2):
        return round(tot / n, cifre) if n else None

    lista_arbitri = []
    for nome, a in arbitri.items():
        n = a["conDati"]

        per_squadra = sorted(
            [
                {
                    "squadra": sq,
                    "partite": v["partite"],
                    "gialli": v["gialli"],
                    "rossi": v["rossi"],
                    "media": media(v["gialli"], v["partite"]),
                }
                for sq, v in a["perSquadra"].items()
            ],
            key=lambda x: (-(x["media"] or 0), x["squadra"]),
        )

        per_stagione = sorted(
            [
                {
                    "stagione": st,
                    "partite": v["partite"],
                    "gialli": v["gialli"],
                    "rossi": v["rossi"],
                    "media": media(v["gialli"] + v["rossi"], v["partite"]),
                    "mediaGialli": media(v["gialli"], v["partite"]),
                    "mediaRossi": media(v["rossi"], v["partite"]),
                    "mediaFalli": media(v["falli"], v["partite"], 1),
                    "squilibrio": media(v["gialliOspite"] - v["gialliCasa"], v["partite"]),
                    "mediaGialliCasa": media(v["gialliCasa"], v["partite"]),
                    "mediaGialliOspite": media(v["gialliOspite"], v["partite"]),
                }
                for st, v in a["perStagione"].items()
            ],
            key=lambda x: x["stagione"],
        )

        elenco = sorted(a["elenco"], key=lambda x: x["stagione"] or "", reverse=True)[:30]

        lista_arbitri.append({
            "nome": nome,
            "partite": a["partite"],
            "gialli": a["gialli"],
            "rossi": a["rossi"],
            "mediaGialli": media(a["gialli"], n),
            "mediaRossi": media(a["rossi"], n),
            "mediaCartellini": media(a["gialli"] + a["rossi"], n),
            "mediaFalli": media(a["falli"], n, 1),
            "gialliPerFallo": media(a["gialli"] / a["falli"] * 100, 1, 1) if a["falli"] else None,
            "squilibrioCasaOspite": media(a["gialliOspite"] - a["gialliCasa"], n),
            "mediaGialliCasa": media(a["gialliCasa"], n),
            "mediaGialliOspite": media(a["gialliOspite"], n),
            "vittorieCasa": a["vittorieCasa"],
            "pareggi": a["pareggi"],
            "vittorieOspite": a["vittorieOspite"],
            "percVittorieCasa": media(a["vittorieCasa"] * 100, n, 1),
            "perSquadra": per_squadra,
            "perStagione": per_stagione,
            "elenco": elenco,
        })
    lista_arbitri.sort(key=lambda x: (-(x["mediaCartellini"] or 0), x["nome"]))

    lista_squadre = []
    for nome, s in squadre.items():
        n = s["conDati"]
        lista_squadre.append({
            "nome": nome,
            "partite": s["partite"],
            "gialli": s["gialli"],
            "rossi": s["rossi"],
            "mediaGialli": media(s["gialli"], n),
            "mediaRossi": media(s["rossi"], n),
            "mediaFalli": media(s["falli"], n, 1),
            "mediaTiri": media(s["tiri"], n, 1),
            "mediaCorner": media(s["corner"], n, 1),
            "mediaGialliCasa": media(s["gialliCasa"], s["partiteCasa"]),
            "mediaGialliOspite": media(s["gialliOspite"], s["partiteOspite"]),
            "falliPerGiallo": media(s["falli"], s["gialli"], 1) if s["gialli"] else None,
        })
    lista_squadre.sort(key=lambda x: (-(x["mediaGialli"] or 0), x["nome"]))

    # ultime partite, per la vista risultati
    ultime = []
    for r in righe[-40:]:
        ultime.append({
            "stagione": r.get("Stagione"),
            "data": r.get("Data"),
            "casa": r.get("Casa"),
            "ospite": r.get("Ospite"),
            "gc": num(r, "GolCasa"),
            "go": num(r, "GolOspite"),
            "arbitro": (r.get("Arbitro") or "").strip(),
            "gialliCasa": num(r, "GialliCasa"),
            "gialliOspite": num(r, "GialliOspite"),
            "rossiCasa": num(r, "RossiCasa"),
            "rossiOspite": num(r, "RossiOspite"),
            "falliCasa": num(r, "FalliCasa"),
            "falliOspite": num(r, "FalliOspite"),
            "tiriCasa": num(r, "TiriCasa"),
            "tiriOspite": num(r, "TiriOspite"),
            "cornerCasa": num(r, "CornerCasa"),
            "cornerOspite": num(r, "CornerOspite"),
        })
    ultime.reverse()

    stagioni = sorted({r.get("Stagione", "") for r in righe if r.get("Stagione")})

    return {
        "aggiornato": datetime.now(timezone.utc).isoformat(),
        "campionato": "Premier League",
        "fonte": "football-data.co.uk (licenza PDDL)",
        "stagioni": stagioni,
        "totalePartite": len(righe),
        "partiteConDisciplina": complete,
        "arbitri": lista_arbitri,
        "squadre": lista_squadre,
        "ultimePartite": ultime,
    }


def main():
    print("=" * 58)
    print("ARCHIVIO PREMIER LEAGUE")
    print("=" * 58)

    archivio = carica_archivio()
    print(f"\nArchivio esistente: {len(archivio)} partite")

    indice = {chiave(r): r for r in archivio}
    prima = len(indice)
    scaricato_qualcosa = False

    for codice in stagioni_da_scaricare():
        etichetta = etichetta_stagione(codice)
        print(f"\nStagione {etichetta}")

        testo = scarica(codice)
        if testo is None:
            continue

        righe = normalizza(testo, etichetta)
        scaricato_qualcosa = True
        print(f"    {len(righe)} partite nel file")

        nuove = aggiornate = 0
        for riga in righe:
            k = chiave(riga)
            if k not in indice:
                nuove += 1
            elif indice[k] != riga:
                aggiornate += 1
            indice[k] = riga   # il file remoto è sempre la versione autorevole

        print(f"    {nuove} nuove · {aggiornate} aggiornate")

    if not scaricato_qualcosa and prima == 0:
        print("\nNessun dato scaricato e archivio vuoto: esco senza scrivere.")
        sys.exit(1)

    tutte = list(indice.values())
    salva_archivio(tutte)
    print(f"\nArchivio salvato: {len(tutte)} partite ({len(tutte) - prima:+d})")

    stats = calcola_statistiche(tutte)
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    USCITA.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Statistiche: {len(stats['arbitri'])} arbitri · {len(stats['squadre'])} squadre")
    print(f"Partite con dati disciplinari: {stats['partiteConDisciplina']}/{stats['totalePartite']}")

    if stats["arbitri"]:
        top = stats["arbitri"][0]
        print(f"Più severo: {top['nome']} — {top['mediaCartellini']} cartellini/partita")


if __name__ == "__main__":
    main()
