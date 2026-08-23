
"""
Recupera dati da API-Football e genera docs/data.json per la dashboard.

Eseguito automaticamente da GitHub Actions.
La chiave API viene letta dalla variabile d'ambiente API_FOOTBALL_KEY
(configurata come GitHub Secret, mai scritta nel codice).

Budget richieste: il piano gratuito consente 100 chiamate/giorno.
Lo script è calibrato per restare sotto quel limite.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE_URL = "https://v3.football.api-sports.io"
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "data.json"

# ID campionati su API-Football
CAMPIONATI = {
    "serie_a":    {"id": 135, "nome": "Serie A",        "paese": "Italia"},
    "premier":    {"id": 39,  "nome": "Premier League", "paese": "Inghilterra"},
    "ligue1":     {"id": 61,  "nome": "Ligue 1",        "paese": "Francia"},
    "laliga":     {"id": 140, "nome": "LaLiga",         "paese": "Spagna"},
    "bundesliga": {"id": 78,  "nome": "Bundesliga",     "paese": "Germania"},
}

# Quante partite concluse arricchire con eventi dettagliati, per campionato.
# Ogni partita arricchita costa 1 chiamata extra: tienilo basso per il piano free.
MAX_DETTAGLIO = int(os.environ.get("MAX_DETTAGLIO", "3"))

# Contatore globale per non sforare la quota
chiamate_fatte = 0
MAX_CHIAMATE = int(os.environ.get("MAX_CHIAMATE", "90"))


class QuotaEsaurita(Exception):
    pass


def api_get(endpoint, **params):
    """Esegue una chiamata all'API con gestione errori e conteggio quota."""
    global chiamate_fatte

    if chiamate_fatte >= MAX_CHIAMATE:
        raise QuotaEsaurita(f"Raggiunto il limite locale di {MAX_CHIAMATE} chiamate")

    chiave = os.environ.get("API_FOOTBALL_KEY")
    if not chiave:
        print("ERRORE: variabile d'ambiente API_FOOTBALL_KEY non impostata", file=sys.stderr)
        sys.exit(1)

    url = f"{BASE_URL}/{endpoint}?{urlencode(params)}"
    req = Request(url, headers={"x-apisports-key": chiave})

    try:
        with urlopen(req, timeout=30) as r:
            dati = json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        print(f"  ! HTTP {e.code} su {endpoint} {params}", file=sys.stderr)
        return None
    except URLError as e:
        print(f"  ! Rete non raggiungibile: {e.reason}", file=sys.stderr)
        return None

    chiamate_fatte += 1

    # API-Football restituisce gli errori dentro il corpo, non come HTTP error
    errori = dati.get("errors")
    if errori:
        # errors può essere {} (nessun errore) o un dict/list popolato
        if isinstance(errori, dict) and errori:
            print(f"  ! API: {errori}", file=sys.stderr)
            return None
        if isinstance(errori, list) and errori:
            print(f"  ! API: {errori}", file=sys.stderr)
            return None

    time.sleep(0.4)  # cortesia verso il rate limit al minuto
    return dati.get("response", [])


def stagione_corrente():
    """La stagione europea è indicata con l'anno di inizio."""
    oggi = datetime.now(timezone.utc)
    return oggi.year if oggi.month >= 7 else oggi.year - 1


def estrai_statistiche(stats_raw):
    """Converte la risposta /fixtures/statistics nel formato della dashboard."""
    mappa = {
        "Ball Possession": "poss",
        "Total Shots": "tiri",
        "Shots on Goal": "porta",
        "Corner Kicks": "corner",
        "Fouls": "falli",
        "Yellow Cards": "gialli",
        "Red Cards": "rossi",
        "Offsides": "fuori",
    }
    out = {}
    for blocco in stats_raw or []:
        squadra_id = blocco.get("team", {}).get("id")
        valori = {}
        for voce in blocco.get("statistics", []):
            chiave = mappa.get(voce.get("type"))
            if not chiave:
                continue
            v = voce.get("value")
            if v is None:
                v = 0
            elif isinstance(v, str) and v.endswith("%"):
                v = int(v.rstrip("%") or 0)
            valori[chiave] = v
        # garantisce che tutte le chiavi esistano
        for k in mappa.values():
            valori.setdefault(k, 0)
        out[squadra_id] = valori
    return out


def estrai_cartellini(eventi_raw):
    """Estrae i cartellini con nome del giocatore dal timeline eventi."""
    cartellini = []
    for e in eventi_raw or []:
        if e.get("type") != "Card":
            continue
        cartellini.append({
            "minuto": (e.get("time") or {}).get("elapsed"),
            "squadra": (e.get("team") or {}).get("name"),
            "giocatore": (e.get("player") or {}).get("name"),
            "tipo": "rosso" if "Red" in (e.get("detail") or "") else "giallo",
            "motivo": e.get("comments"),
        })
    return cartellini


def elabora_campionato(chiave, meta, stagione):
    """Recupera partite, statistiche ed eventi per un campionato."""
    print(f"\n=== {meta['nome']} ===")

    oggi = datetime.now(timezone.utc).date()
    da = oggi - timedelta(days=14)
    a = oggi + timedelta(days=14)

    partite_raw = api_get(
        "fixtures",
        league=meta["id"], season=stagione,
        **{"from": da.isoformat(), "to": a.isoformat()},
    )

    if partite_raw is None:
        print("  Nessun dato recuperato (verifica piano/stagione)")
        return {**meta, "stagione": stagione, "concluse": [], "inCorso": [],
                "prossime": [], "errore": "dati non disponibili"}

    concluse, in_corso, prossime = [], [], []

    for p in partite_raw:
        fx = p.get("fixture", {})
        squadre = p.get("teams", {})
        gol = p.get("goals", {})
        stato = (fx.get("status") or {}).get("short", "")

        base = {
            "id": fx.get("id"),
            "data": fx.get("date"),
            "casa": (squadre.get("home") or {}).get("name"),
            "ospite": (squadre.get("away") or {}).get("name"),
            "arbitro": fx.get("referee"),
        }

        if stato in ("FT", "AET", "PEN"):
            concluse.append({**base, "gc": gol.get("home"), "go": gol.get("away")})
        elif stato in ("1H", "2H", "HT", "ET", "LIVE"):
            in_corso.append({**base, "gc": gol.get("home"), "go": gol.get("away"),
                             "minuto": (fx.get("status") or {}).get("elapsed")})
        elif stato == "NS":
            prossime.append(base)

    concluse.sort(key=lambda x: x["data"] or "", reverse=True)
    prossime.sort(key=lambda x: x["data"] or "")

    print(f"  {len(concluse)} concluse · {len(in_corso)} in corso · {len(prossime)} in programma")

    # Arricchisce solo le partite più recenti, per rispettare la quota
    for partita in concluse[:MAX_DETTAGLIO]:
        fid = partita["id"]
        if not fid:
            continue
        try:
            stats = api_get("fixtures/statistics", fixture=fid)
            eventi = api_get("fixtures/events", fixture=fid)
        except QuotaEsaurita as e:
            print(f"  ! {e} — arricchimento interrotto")
            break

        if stats:
            per_squadra = estrai_statistiche(stats)
            valori = list(per_squadra.values())
            if len(valori) == 2:
                partita["stats"] = {"casa": valori[0], "osp": valori[1]}

        if eventi:
            partita["cartellini"] = estrai_cartellini(eventi)

        print(f"  + dettagli: {partita['casa']} {partita['gc']}-{partita['go']} {partita['ospite']}")

    return {
        **meta,
        "stagione": stagione,
        "concluse": concluse[:12],
        "inCorso": in_corso,
        "prossime": prossime[:10],
    }


def main():
    stagione = int(os.environ.get("STAGIONE", stagione_corrente()))
    print(f"Stagione: {stagione} | Budget: {MAX_CHIAMATE} chiamate | Dettaglio: {MAX_DETTAGLIO}/lega")

    risultato = {
        "aggiornato": datetime.now(timezone.utc).isoformat(),
        "stagione": stagione,
        "fonte": "API-Football (api-sports.io)",
        "campionati": {},
    }

    for chiave, meta in CAMPIONATI.items():
        try:
            risultato["campionati"][chiave] = elabora_campionato(chiave, meta, stagione)
        except QuotaEsaurita as e:
            print(f"\n! {e} — interrompo qui, i dati raccolti vengono comunque salvati")
            break
        except Exception as e:  # non far fallire l'intero job per un campionato
            print(f"  ! Errore su {meta['nome']}: {e}", file=sys.stderr)
            risultato["campionati"][chiave] = {**meta, "errore": str(e),
                                               "concluse": [], "inCorso": [], "prossime": []}

    risultato["chiamateUsate"] = chiamate_fatte

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(risultato, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✓ Scritto {OUTPUT} — {chiamate_fatte} chiamate usate")


if __name__ == "__main__":
    main()
