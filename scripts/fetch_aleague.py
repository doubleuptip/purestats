"""
Archivio A-League — statistiche arbitrali.

Fonte: Ultimate A-League, tramite la sua API privata. L'accesso è stato
concesso per le sole sezioni arbitrali ed è soggetto a due condizioni,
riportate qui perché chi metterà mano a questo file le conosca:

  1. Non abusare dell'API: poche richieste, e conservare i dati invece di
     riscaricarli. Per questo l'archivio si aggiorna una volta a settimana
     e mantiene quanto già ottenuto.
  2. Citare Ultimate A-League come fonte, come previsto dalla loro licenza.
     L'attribuzione compare nella pagina, non solo in questo file.

Autenticazione: apiId come parametro nell'indirizzo, la chiave segreta
come intestazione APICONSUMERSECRET. Entrambe vengono lette dai secret
del repository e non compaiono mai nel codice o nei registri.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

RADICE = Path(__file__).resolve().parent.parent
ARCHIVIO = RADICE / "data" / "aleague_arbitri.json"
USCITA = RADICE / "docs" / "data_aleague.json"

BASE = "https://api.ultimatealeague.com/1.0"
UA = "Mozilla/5.0 (compatible; PureStats/1.0)"
PAUSA = 1.5


def credenziali():
    """Legge le credenziali dai secret del repository."""
    api_id = os.environ.get("UAL_API_ID", "").strip()
    segreto = os.environ.get("UAL_API_SECRET", "").strip()
    if not (api_id and segreto):
        print("ERRORE: credenziali mancanti.")
        print("Servono i secret UAL_API_ID e UAL_API_SECRET.")
        raise SystemExit(1)
    return api_id, segreto


def chiama(percorso, **parametri):
    """Esegue una richiesta all'API.

    L'identificativo va nell'indirizzo, la chiave segreta nell'intestazione:
    è il meccanismo indicato da Ultimate A-League.
    """
    api_id, segreto = credenziali()
    parametri["apiId"] = api_id
    url = f"{BASE}/{percorso.strip('/')}/?{urlencode(parametri)}"

    # nel registro l'identificativo non deve comparire
    visibile = {k: v for k, v in parametri.items() if k != "apiId"}
    print(f"  GET /{percorso.strip('/')}/ {visibile if visibile else ''}")

    richiesta = Request(url, headers={
        "User-Agent": UA,
        "APICONSUMERSECRET": segreto,
        "Accept": "application/json",
    })
    try:
        with urlopen(richiesta, timeout=45) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        print(f"    HTTP {e.code}")
        if e.code == 401:
            print("    Credenziali non accettate: controlla i due secret.")
        elif e.code == 403:
            print("    Endpoint non compreso nei permessi concessi.")
        elif e.code == 429:
            print("    Troppe richieste: rallentare.")
        return None
    except URLError as e:
        print(f"    Rete: {e.reason}")
        return None
    except json.JSONDecodeError as e:
        print(f"    Risposta non interpretabile: {e}")
        return None


def carica_archivio():
    if not ARCHIVIO.exists():
        return {}
    try:
        return json.loads(ARCHIVIO.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def salva_archivio(dati):
    ARCHIVIO.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVIO.write_text(json.dumps(dati, ensure_ascii=False, indent=2),
                        encoding="utf-8")


def _elenco(risposta):
    """La risposta può essere una lista o un oggetto che la contiene."""
    if isinstance(risposta, list):
        return risposta
    if isinstance(risposta, dict):
        for chiave in ("data", "results", "items", "statistics", "referees"):
            if isinstance(risposta.get(chiave), list):
                return risposta[chiave]
    return []


def _campo(voce, *nomi, predefinito=None):
    for nome in nomi:
        if isinstance(voce, dict) and voce.get(nome) not in (None, ""):
            return voce[nome]
    return predefinito


def _numero(valore):
    try:
        return int(float(str(valore).strip().replace(",", "")))
    except (ValueError, TypeError, AttributeError):
        return 0


# Le quattro classifiche arbitrali, indicate da Justin di Ultimate A-League.
# Ognuna restituisce tutti gli arbitri: quattro chiamate bastano a costruire
# l'intero quadro, senza interrogare i singoli.
#
# Struttura di una voce:
#   type=app  -> total_matches
#   type=tc   -> total_bookings, average, total_matches
#   type=yc   -> come sopra, riferito ai soli gialli
#   type=rc   -> come sopra, riferito ai soli rossi
CLASSIFICHE = [
    ("app", "cartellini", None),
    ("tc",  "cartellini", "mediaCartellini"),
    ("yc",  "gialli",     "mediaGialli"),
    ("rc",  "rossi",      "mediaRossi"),
]


def leggi_stagione(stagione=None, escludi_finali=True):
    """Costruisce il quadro arbitrale unendo le quattro classifiche.

    Le medie non vengono ricalcolate: l'API le fornisce già, ed è la
    fonte a sapere quali partite conta e quali no.
    """
    arbitri = {}

    for tipo, campo, campo_media in CLASSIFICHE:
        parametri = {"cat": "r", "type": tipo}
        if stagione:
            parametri["season"] = stagione
        if escludi_finali:
            parametri["excludeFinals"] = "true"

        risposta = chiama("statistics", **parametri)
        if risposta is None:
            print(f"    {tipo}: nessun dato")
            continue

        voci = _elenco(risposta)
        letti = 0
        for voce in voci:
            nome = _campo(voce, "name", "fullName", "displayName")
            if not nome:
                continue
            nome = str(nome).strip()
            scheda = arbitri.setdefault(nome, {"nome": nome})

            identificativo = _campo(voce, "id")
            if identificativo is not None:
                scheda.setdefault("id", identificativo)

            # le presenze compaiono in tutte le risposte
            partite = _numero(_campo(voce, "total_matches", predefinito=0))
            if partite:
                scheda["partite"] = partite

            # la nazionalità arriva come elenco di oggetti
            nazioni = _campo(voce, "nationality", predefinito=[])
            if isinstance(nazioni, list) and nazioni:
                paese = nazioni[0].get("name") if isinstance(nazioni[0], dict) else None
                if paese:
                    scheda.setdefault("nazionalita", paese)

            if tipo != "app":
                scheda[campo] = _numero(_campo(voce, "total_bookings", predefinito=0))
                media = _campo(voce, "average")
                if media is not None:
                    try:
                        scheda[campo_media] = round(float(media), 2)
                    except (ValueError, TypeError):
                        pass
            letti += 1

        con_valore = sum(1 for a in arbitri.values()
                         if a.get("partite") or a.get(campo))
        print(f"    {tipo}: {letti} arbitri, {con_valore} con un valore")

        time.sleep(PAUSA)

    return arbitri


def calcola(arbitri):
    """Completa le schede e ordina per severità."""
    elenco = []
    for scheda in arbitri.values():
        partite = scheda.get("partite", 0)
        gialli = scheda.get("gialli", 0)
        rossi = scheda.get("rossi", 0)
        cartellini = scheda.get("cartellini", gialli + rossi)

        # Se una media manca — capita per i rossi, che l'API restituisce
        # solo per chi ne ha assegnati — la si ricava dalle presenze.
        def media(valore_noto, totale):
            if valore_noto is not None:
                return valore_noto
            return round(totale / partite, 2) if partite else None

        elenco.append({
            "nome": scheda["nome"],
            "id": scheda.get("id"),
            "nazionalita": scheda.get("nazionalita"),
            "partite": partite,
            "gialli": gialli,
            "rossi": rossi,
            "cartellini": cartellini,
            "mediaGialli": media(scheda.get("mediaGialli"), gialli),
            "mediaRossi": media(scheda.get("mediaRossi"), rossi),
            "mediaCartellini": media(scheda.get("mediaCartellini"), cartellini),
        })

    elenco.sort(key=lambda a: (-(a["mediaCartellini"] or 0), a["nome"]))
    return elenco


def stagioni_richieste():
    """Le stagioni da interrogare, oltre al complessivo.

    Il formato accettato dall'API non è documentato: si indica con la
    variabile STAGIONI_ALEAGUE, per esempio '2025-26,2024-25'. Senza,
    si scarica il solo dato complessivo.
    """
    grezzo = os.environ.get("STAGIONI_ALEAGUE", "").strip()
    if not grezzo:
        return []
    return [s.strip() for s in grezzo.replace(";", ",").split(",") if s.strip()]


def main():
    print("=" * 58)
    print("ARCHIVIO A-LEAGUE — ARBITRI")
    print("=" * 58)

    archivio = carica_archivio()

    print("\nClassifiche complessive")
    arbitri = leggi_stagione(None)

    # Le singole stagioni servono a ricostruire l'andamento nel tempo.
    # Ogni stagione costa quattro chiamate, quindi si richiedono solo
    # quelle indicate esplicitamente.
    per_stagione = {}
    for stagione in stagioni_richieste():
        print(f"\nStagione {stagione}")
        dati_stagione = leggi_stagione(stagione)
        if not dati_stagione:
            print("  Nessun dato: forse il formato della stagione non è corretto.")
            continue
        per_stagione[stagione] = calcola(dati_stagione)

    if not arbitri:
        print("\nNessun dato ottenuto: conservo l'archivio precedente.")
        if not archivio.get("arbitri"):
            raise SystemExit(1)
        elenco = archivio["arbitri"]
    else:
        elenco = calcola(arbitri)

    # allega a ciascun arbitro il proprio andamento per stagione
    if per_stagione:
        for scheda in elenco:
            storico = []
            for stagione, elenco_stagione in per_stagione.items():
                voce = next((a for a in elenco_stagione
                             if a["nome"] == scheda["nome"]), None)
                if voce and voce.get("partite"):
                    storico.append({
                        "stagione": stagione,
                        "partite": voce["partite"],
                        "gialli": voce["gialli"], "rossi": voce["rossi"],
                        "cartellini": voce["cartellini"],
                        "mediaCartellini": voce["mediaCartellini"],
                        "mediaGialli": voce["mediaGialli"],
                        "mediaRossi": voce["mediaRossi"],
                    })
            storico.sort(key=lambda x: x["stagione"], reverse=True)
            scheda["perStagione"] = storico

    dati = {
        "aggiornato": datetime.now(timezone.utc).isoformat(),
        "campionato": "A-League",
        "fonte": "Ultimate A-League",
        "attribuzione": "Dati forniti da Ultimate A-League "
                        "(ultimatealeague.com), usati con permesso.",
        "stagioni": sorted(per_stagione.keys(), reverse=True),
        "arbitri": elenco,
    }

    salva_archivio(dati)
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    USCITA.write_text(json.dumps(dati, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    print(f"\nArbitri in archivio: {len(elenco)}")
    for a in elenco[:5]:
        print(f"  {a['nome']:24} {a['partite']:3} PG · "
              f"{a['mediaCartellini']} cart/partita "
              f"({a['gialli']}G {a['rossi']}R)")
    print(f"\n\u2713 Scritto {USCITA}")


if __name__ == "__main__":
    main()
