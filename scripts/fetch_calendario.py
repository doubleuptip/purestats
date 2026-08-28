"""
Calendario delle prossime partite, per tutti i campionati.

Fonte unica: football-data.co.uk/fixtures.csv, licenza PDDL. Contiene le
gare in programma di tutte le divisioni in un solo file; qui si tengono
solo i quattro campionati seguiti.

Il file scaricato porta in testa un carattere invisibile: va decodificato
con utf-8-sig, altrimenti quel carattere resta attaccato al nome della
prima colonna e la rende irreperibile, con il risultato che nessuna riga
viene riconosciuta.

Dove disponibile, a ogni partita viene abbinato l'arbitro designato
leggendolo dagli archivi dei singoli campionati.
"""

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

RADICE = Path(__file__).resolve().parent.parent
USCITA = RADICE / "docs" / "calendario.json"

FIXTURES = "https://www.football-data.co.uk/fixtures.csv"
UA = "Mozilla/5.0 (compatible; PureStats/1.0)"

# Quanti giorni in avanti guardare
GIORNI_AVANTI = 45

CAMPIONATI = {
    "premier": {"nome": "Premier League", "codice": "E0",
                "designazioni": None},
    "serie_a": {"nome": "Serie A", "codice": "I1",
                "designazioni": "designazioni_serie_a.json"},
    "la_liga": {"nome": "LaLiga", "codice": "SP1",
                "designazioni": "designaciones_la_liga.json"},
    "ligue_1": {"nome": "Ligue 1", "codice": "F1",
                "designazioni": "designations_ligue_1.json"},
}


def scarica(url, descrizione):
    print(f"  GET {url}")
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

    for codifica in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return grezzo.decode(codifica)
        except UnicodeDecodeError:
            continue
    return grezzo.decode("utf-8", errors="replace")


def _data_iso(testo):
    """'29/08/2026' -> '2026-08-29'"""
    try:
        g, m, a = (testo or "").strip().split("/")
        a = f"20{a}" if len(a) == 2 else a
        return f"{int(a):04d}-{int(m):02d}-{int(g):02d}"
    except (ValueError, AttributeError):
        return None


def carica_designazioni(nome_file):
    """Indicizza le designazioni per (data, casa, ospite)."""
    if not nome_file:
        return {}
    percorso = RADICE / "data" / nome_file
    if not percorso.exists():
        return {}
    try:
        elenco = json.loads(percorso.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {(d.get("data"), d.get("casa"), d.get("ospite")): d
            for d in elenco if d.get("data")}


def main():
    print("=" * 58)
    print("CALENDARIO PROSSIME PARTITE")
    print("=" * 58)

    testo = scarica(FIXTURES, "fixtures.csv")
    if not testo:
        print("\nNessun dato scaricato: esco senza modificare il file.")
        raise SystemExit(1)

    oggi = datetime.now(timezone.utc).date()
    limite = (oggi + timedelta(days=GIORNI_AVANTI)).isoformat()
    oggi = oggi.isoformat()

    per_codice = {}
    totale = 0
    letti = 0
    date_viste = []
    codici_visti = set()

    for r in csv.DictReader(io.StringIO(testo)):
        codice = (r.get("Div") or "").strip()
        casa = (r.get("HomeTeam") or "").strip()
        ospite = (r.get("AwayTeam") or "").strip()
        data = _data_iso(r.get("Date"))
        if not (codice and casa and ospite and data):
            continue
        letti += 1
        date_viste.append(data)
        codici_visti.add(codice)
        if not (oggi <= data <= limite):
            continue
        per_codice.setdefault(codice, []).append({
            "data": data,
            "ora": (r.get("Time") or "").strip() or None,
            "casa": casa,
            "ospite": ospite,
        })
        totale += 1

    # Diagnostica: senza questi numeri, un calendario vuoto non dice se il
    # problema sia il filtro, il formato del file o il file stesso.
    print(f"  {letti} righe valide nel file, {len(codici_visti)} divisioni")
    if date_viste:
        print(f"  Date presenti: da {min(date_viste)} a {max(date_viste)}")
        print(f"  Finestra cercata: da {oggi} a {limite}")
    print(f"  {totale} partite dentro la finestra")

    if letti and not totale:
        print()
        print("  Il file contiene partite, ma nessuna nella finestra cercata.")
        print("  Di norma significa che non è ancora stato aggiornato per il")
        print("  turno in arrivo: viene rigenerato il venerdì pomeriggio.")
    elif not letti:
        print()
        print("  Nessuna riga leggibile: il formato del file potrebbe essere")
        print("  cambiato. Le colonne attese sono Div, Date, HomeTeam, AwayTeam.")
        intestazione = testo.splitlines()[0][:120] if testo else ""
        print(f"  Intestazione trovata: {intestazione!r}")

    risultato = {
        "aggiornato": datetime.now(timezone.utc).isoformat(),
        "fonte": "football-data.co.uk (licenza PDDL)",
        "giorniAvanti": GIORNI_AVANTI,
        "campionati": {},
    }

    print()
    for chiave, conf in CAMPIONATI.items():
        gare = sorted(per_codice.get(conf["codice"], []),
                      key=lambda x: (x["data"], x["ora"] or ""))
        designazioni = carica_designazioni(conf["designazioni"])

        con_arbitro = 0
        for g in gare:
            d = designazioni.get((g["data"], g["casa"], g["ospite"]))
            if d and d.get("arbitro"):
                g["arbitro"] = d["arbitro"]
                if d.get("var"):
                    g["var"] = d["var"]
                con_arbitro += 1

        risultato["campionati"][chiave] = {
            "nome": conf["nome"],
            "partite": gare[:40],
        }
        nota = f" · {con_arbitro} con arbitro designato" if con_arbitro else ""
        print(f"  {conf['nome']:16} {len(gare)} partite{nota}")

    # Se non c'è nulla da mostrare, si conserva il calendario precedente:
    # sovrascriverlo con un file vuoto cancellerebbe partite ancora valide.
    if totale == 0 and USCITA.exists():
        print("\n  Nessuna partita trovata: conservo il calendario precedente.")
        return

    USCITA.parent.mkdir(parents=True, exist_ok=True)
    USCITA.write_text(json.dumps(risultato, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\n✓ Scritto {USCITA}")


if __name__ == "__main__":
    main()
