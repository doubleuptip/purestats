"""
Notizie e calendario futuro per tutti i campionati.

Due fonti:
  1. football-data.co.uk/fixtures.csv — prossime partite di tutti i
     campionati in un unico file. Licenza PDDL.
  2. Feed RSS di testate italiane — titoli, sommari brevi e collegamenti.

Sui feed vale una regola precisa: si prendono titolo, data, fonte e link,
mai il testo dell'articolo. I feed sono pubblicati apposta per essere
ripresi in questo modo, e il collegamento riporta il lettore sul sito che
ha prodotto la notizia.

I feed che non rispondono vengono segnalati e saltati: se una testata
cambia indirizzo, le altre continuano a funzionare.
"""

import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import news as nw

RADICE = Path(__file__).resolve().parent.parent
USCITA = RADICE / "docs"

FIXTURES = "https://www.football-data.co.uk/fixtures.csv"
UA = "Mozilla/5.0 (compatible; PureStats/1.0)"
PAUSA = 1.5

# Feed candidati. Vengono provati tutti: quelli che non rispondono
# sono segnalati nel log e ignorati, senza fermare l'aggiornamento.
FEED = [
    ("TMW", "https://www.tuttomercatoweb.com/rss"),
    ("TMW Serie A", "https://www.tuttomercatoweb.com/rss/serie-a"),
    ("TMW Estero", "https://www.tuttomercatoweb.com/rss/calcio-estero"),
    ("Calciomercato", "https://www.calciomercato.com/rss"),
    ("Virgilio Sport", "https://sport.virgilio.it/feed/"),
    ("Virgilio Serie A", "https://sport.virgilio.it/calcio/serie-a/feed/"),
]

# Ogni campionato: codice nel file calendario, squadre e parole che lo
# identificano nei titoli delle notizie.
CAMPIONATI = {
    "premier": {
        "nome": "Premier League", "codice": "E0", "file": "news_premier.json",
        "parole": ["premier league", "inghilterra", "calcio inglese"],
        "squadre": ["Arsenal", "Chelsea", "Liverpool", "Man City", "Man United",
                    "Tottenham", "Newcastle", "Aston Villa", "Brighton", "Everton",
                    "Fulham", "Brentford", "Bournemouth", "Crystal Palace",
                    "Nott'm Forest", "Leeds", "Sunderland", "Ipswich", "Wolves",
                    "Burnley", "Coventry", "Hull City"],
    },
    "serie_a": {
        "nome": "Serie A", "codice": "I1", "file": "news_serie_a.json",
        "parole": ["serie a", "campionato italiano"],
        "squadre": ["Inter", "Milan", "Juventus", "Napoli", "Roma", "Lazio",
                    "Atalanta", "Fiorentina", "Bologna", "Torino", "Udinese",
                    "Genoa", "Cagliari", "Lecce", "Verona", "Sassuolo", "Parma",
                    "Como", "Monza", "Venezia", "Cremonese", "Pisa", "Frosinone"],
    },
    "la_liga": {
        "nome": "LaLiga", "codice": "SP1", "file": "news_la_liga.json",
        "parole": ["liga", "spagna", "calcio spagnolo"],
        "squadre": ["Barcellona", "Barcelona", "Real Madrid", "Atletico",
                    "Siviglia", "Sevilla", "Valencia", "Villarreal", "Betis",
                    "Athletic", "Real Sociedad", "Celta", "Osasuna", "Getafe",
                    "Girona", "Mallorca", "Alaves", "Espanyol", "Elche",
                    "Levante", "Oviedo", "Malaga"],
    },
    "ligue_1": {
        "nome": "Ligue 1", "codice": "F1", "file": "news_ligue_1.json",
        "parole": ["ligue 1", "francia", "calcio francese"],
        "squadre": ["Paris Saint-Germain", "PSG", "Marsiglia", "Marseille",
                    "Lione", "Lyon", "Monaco", "Lilla", "Lille", "Rennes",
                    "Nizza", "Nice", "Lens", "Strasburgo", "Strasbourg",
                    "Brest", "Tolosa", "Toulouse", "Nantes", "Auxerre",
                    "Angers", "Le Havre", "Lorient", "Metz"],
    },
}


def scarica(url, descrizione):
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=45) as r:
            grezzo = r.read()
    except HTTPError as e:
        print(f"    HTTP {e.code} — {descrizione}")
        return None
    except URLError as e:
        print(f"    Rete: {e.reason} — {descrizione}")
        return None
    except Exception as e:
        print(f"    Errore: {e} — {descrizione}")
        return None
    for codifica in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return grezzo.decode(codifica)
        except UnicodeDecodeError:
            continue
    return grezzo.decode("utf-8", errors="replace")


# ------------------------------------------------------------- calendario

def _data_iso(testo):
    """'29/08/2026' -> '2026-08-29'"""
    try:
        g, m, a = (testo or "").strip().split("/")
        a = f"20{a}" if len(a) == 2 else a
        return f"{int(a):04d}-{int(m):02d}-{int(g):02d}"
    except (ValueError, AttributeError):
        return None


def scarica_calendario():
    """Prossime partite di tutti i campionati, raggruppate per codice."""
    print("\nCalendario futuro")
    testo = scarica(FIXTURES, "fixtures.csv")
    if not testo:
        return {}

    per_lega = {}
    righe = 0
    for r in csv.DictReader(io.StringIO(testo)):
        div = (r.get("Div") or "").strip()
        casa = (r.get("HomeTeam") or "").strip()
        if not div or not casa:
            continue
        data = _data_iso(r.get("Date"))
        if not data:
            continue
        per_lega.setdefault(div, []).append({
            "data": data,
            "ora": (r.get("Time") or "").strip() or None,
            "casa": casa,
            "ospite": (r.get("AwayTeam") or "").strip(),
        })
        righe += 1

    for div in per_lega:
        per_lega[div].sort(key=lambda x: (x["data"], x["ora"] or ""))
    print(f"  {righe} partite in programma, {len(per_lega)} campionati")
    return per_lega


# ---------------------------------------------------------------- notizie

def scarica_notizie():
    """Legge tutti i feed disponibili e restituisce le notizie."""
    print("\nFeed RSS")
    tutte = []
    funzionanti = 0

    for fonte, url in FEED:
        if funzionanti > 0:
            time.sleep(PAUSA)
        xml = scarica(url, fonte)
        if not xml:
            continue
        estratte = nw.analizza_feed(xml, fonte)
        if estratte:
            funzionanti += 1
            print(f"  {fonte}: {len(estratte)} notizie")
            tutte.extend(estratte)
        else:
            print(f"  {fonte}: risposta non interpretabile come feed")

    if not funzionanti:
        print("  Nessun feed disponibile")
    return nw.deduplica(tutte)


def per_campionato(notizie, conf):
    """Filtra e raggruppa le notizie di un campionato per categoria."""
    sue = [n for n in notizie if nw.riguarda(n, conf["squadre"], conf["parole"])]
    # il sommario ha esaurito la sua funzione: serviva a classificare
    # e a riconoscere il campionato, non va conservato
    sue = nw.smonta_sommario([dict(n) for n in sue])
    gruppi = {"formazioni": [], "infortuni": [], "mercato": [], "generale": []}
    for n in sue:
        gruppi.setdefault(n["categoria"], []).append(n)
    return sue, gruppi


def carica_esistente(percorso):
    """Legge il file già presente, per conservare le parti non aggiornate."""
    if not percorso.exists():
        return {}
    try:
        return json.loads(percorso.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def unisci(vecchie, nuove, giorni=4):
    """Fonde le notizie nuove con quelle già presenti.

    Un feed mostra solo gli ultimi articoli: senza questa fusione, una
    notizia uscita ieri sparirebbe dall'archivio appena il feed la fa
    scorrere. Le voci più vecchie del limite indicato vengono scartate,
    perché una probabile formazione di due settimane fa non serve a nessuno.
    """
    limite = (datetime.now(timezone.utc) - timedelta(days=giorni)).isoformat()
    per_link = {}
    for n in list(vecchie or []) + list(nuove or []):
        link = n.get("collegamento")
        if not link:
            continue
        if (n.get("data") or "9999") < limite:
            continue
        per_link[link] = n          # la versione nuova prevale
    return sorted(per_link.values(), key=lambda x: x.get("data") or "", reverse=True)


def main():
    modo = os.environ.get("MODO", "completo").strip().lower()
    if modo not in ("completo", "rapido"):
        modo = "completo"

    print("=" * 58)
    print(f"NOTIZIE E CALENDARIO — modalità: {modo}")
    print("=" * 58)
    if modo == "rapido":
        print("Aggiorno solo formazioni e infortuni; il resto resta com'è.")

    # Il calendario cambia di rado: si scarica solo nell'esecuzione completa
    calendario = scarica_calendario() if modo == "completo" else {}

    notizie = scarica_notizie()
    print(f"\nNotizie totali dopo deduplica: {len(notizie)}")

    oggi = datetime.now(timezone.utc).date().isoformat()
    limite = (datetime.now(timezone.utc).date() + timedelta(days=45)).isoformat()

    # Categorie da aggiornare a ogni frequenza. Formazioni e infortuni
    # invecchiano in poche ore, il mercato e le notizie generali no.
    RAPIDE = ("formazioni", "infortuni")
    TUTTE = ("formazioni", "infortuni", "mercato", "generale")

    USCITA.mkdir(parents=True, exist_ok=True)
    for chiave, conf in CAMPIONATI.items():
        percorso = USCITA / conf["file"]
        esistente = carica_esistente(percorso)
        sue, gruppi = per_campionato(notizie, conf)

        dati = dict(esistente)
        dati["aggiornato"] = datetime.now(timezone.utc).isoformat()
        dati["nome"] = conf["nome"]
        dati["fonte"] = "football-data.co.uk (PDDL) · feed RSS delle testate"
        dati["modo"] = modo

        # calendario: solo nell'esecuzione completa, altrimenti si conserva
        if modo == "completo":
            prossime = [p for p in calendario.get(conf["codice"], [])
                        if p.get("data") and oggi <= p["data"] <= limite]
            dati["calendario"] = prossime[:30]
            dati["calendarioAggiornato"] = dati["aggiornato"]

        categorie = RAPIDE if modo == "rapido" else TUTTE
        for cat in categorie:
            giorni = 3 if cat in RAPIDE else 7
            dati[cat] = unisci(esistente.get(cat), gruppi.get(cat, []), giorni)[:20]

        # assicura che le chiavi esistano comunque
        for cat in TUTTE:
            dati.setdefault(cat, [])
        dati.setdefault("calendario", [])

        percorso.write_text(json.dumps(dati, ensure_ascii=False, indent=2),
                            encoding="utf-8")

        print(f"\n{conf['nome']}")
        if modo == "completo":
            print(f"  {len(dati['calendario'])} partite in programma")
        aggiornate = " · ".join(f"{c}: {len(dati[c])}" for c in categorie)
        print(f"  {aggiornate}")


if __name__ == "__main__":
    main()
