"""
Archivio NFL — statistiche di squadra e partite.

Fonte: nflverse, il progetto che pubblica i dati NFL come file CSV su
GitHub. Nessuna chiave, nessuna registrazione: i file si scaricano per
indirizzo. Licenza CC-BY-SA 4.0, con attribuzione a nflverse.

Si conservano al massimo cinque stagioni: oltre quel limite l'archivio
crescerebbe senza che i dati più antichi vengano mai consultati.
"""

import csv
import io
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

RADICE = Path(__file__).resolve().parent.parent
ARCHIVIO = RADICE / "data" / "nfl.csv"
USCITA = RADICE / "docs" / "data_nfl.json"

PARTITE = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
# Anagrafica squadre: conference e division non sono nel file partite
SQUADRE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/teams.csv"
# Statistiche per giocatore, un file per stagione, con dettaglio settimanale
GIOCATORI_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
                 "player_stats/player_stats_{stagione}.csv")
UA = "Mozilla/5.0 (compatible; PureStats/1.0)"

MAX_STAGIONI = 5

COLONNE = [
    "Stagione", "Settimana", "Tipo", "Data", "Ora",
    "Casa", "Ospite", "PuntiCasa", "PuntiOspite",
    "Stadio", "Copertura", "Superficie", "Temperatura", "Vento",
]


def scarica(url, descrizione):
    print(f"  GET {url}")
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=60) as r:
            grezzo = r.read()
    except HTTPError as e:
        print(f"    HTTP {e.code} — {descrizione}")
        return None
    except URLError as e:
        print(f"    Rete: {e.reason} — {descrizione}")
        return None

    for codifica in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return grezzo.decode(codifica)
        except UnicodeDecodeError:
            continue
    return grezzo.decode("utf-8", errors="replace")


def carica_anagrafica():
    """Conference e division di ogni squadra.

    Il file delle partite riporta solo le sigle: per raggruppare le squadre
    serve l'anagrafica, che sta in un file separato. Se non si scarica,
    l'archivio resta valido ma senza raggruppamenti.
    """
    testo = scarica(SQUADRE_URL, "anagrafica squadre")
    if not testo:
        print("    Anagrafica non disponibile: niente conference e division")
        return {}

    per_sigla = {}
    for r in csv.DictReader(io.StringIO(testo)):
        sigla = (r.get("team") or "").strip()
        if not sigla:
            continue
        divisione = (r.get("division") or "").strip()
        # 'NFC East' -> conference NFC, division East
        conference = (r.get("conf") or "").strip()
        if not conference and divisione:
            conference = divisione.split()[0]
        per_sigla[sigla] = {
            "nomeCompleto": (r.get("full") or r.get("name") or "").strip() or sigla,
            "conference": conference or None,
            "division": divisione or None,
        }
    print(f"    {len(per_sigla)} squadre in anagrafica")
    return per_sigla


# Ruoli mostrati nella scheda partita, con la statistica che li qualifica.
# Non serve l'elenco completo dei giocatori: bastano i due o tre che
# decidono la partita, quelli di cui si parla prima del calcio d'inizio.
RUOLI = [
    ("QB", "passing_yards",   "yard passate",  ["passing_tds", "interceptions"]),
    ("RB", "rushing_yards",   "yard corse",    ["rushing_tds"]),
    ("WR", "receiving_yards", "yard ricevute", ["receptions", "receiving_tds"]),
    ("TE", "receiving_yards", "yard ricevute", ["receptions", "receiving_tds"]),
]

# Quanti giocatori tenere per ruolo, per squadra e per stagione
QUANTI_PER_RUOLO = {"QB": 1, "RB": 1, "WR": 2, "TE": 1}

ETICHETTE = {
    "passing_tds": "TD", "interceptions": "INT", "rushing_tds": "TD",
    "receptions": "ric.", "receiving_tds": "TD",
}


def _decimale(valore):
    v = (valore or "").strip()
    if v in ("", "NA"):
        return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def carica_giocatori(stagioni):
    """I migliori giocatori per squadra, ruolo e stagione.

    I file di nflverse riportano una riga per giocatore per settimana:
    si sommano i valori dell'intera stagione e si tiene solo chi guida
    la propria squadra nel proprio ruolo.
    """
    per_squadra = {}

    for stagione in stagioni:
        url = GIOCATORI_URL.format(stagione=stagione)
        testo = scarica(url, f"giocatori {stagione}")
        if not testo:
            continue

        # somma per giocatore
        totali = {}
        for r in csv.DictReader(io.StringIO(testo)):
            squadra = (r.get("recent_team") or r.get("team") or "").strip()
            nome = (r.get("player_display_name") or r.get("player_name") or "").strip()
            ruolo = (r.get("position") or "").strip()
            if not (squadra and nome and ruolo):
                continue
            chiave = (squadra, nome, ruolo)
            voce = totali.setdefault(chiave, {"partite": 0})
            voce["partite"] += 1
            for campo in ("passing_yards", "passing_tds", "interceptions",
                          "rushing_yards", "rushing_tds",
                          "receiving_yards", "receptions", "receiving_tds"):
                voce[campo] = voce.get(campo, 0.0) + _decimale(r.get(campo))

        # per ogni squadra e ruolo, i migliori
        candidati = defaultdict(list)
        for (squadra, nome, ruolo), v in totali.items():
            for r_ruolo, misura, _, _ in RUOLI:
                if ruolo == r_ruolo:
                    candidati[(squadra, ruolo)].append((v.get(misura, 0.0), nome, v))

        conteggio = 0
        for (squadra, ruolo), elenco in candidati.items():
            elenco.sort(reverse=True, key=lambda x: x[0])
            quanti = QUANTI_PER_RUOLO.get(ruolo, 1)
            for valore, nome, v in elenco[:quanti]:
                if valore <= 0:
                    continue
                misura, etichetta, extra = next(
                    (m, e, x) for r, m, e, x in RUOLI if r == ruolo)
                dettagli = []
                for campo in extra:
                    n = int(v.get(campo, 0))
                    if n:
                        dettagli.append(f"{n} {ETICHETTE.get(campo, campo)}")
                per_squadra.setdefault(squadra, {}).setdefault(str(stagione), []).append({
                    "nome": nome, "ruolo": ruolo,
                    "valore": int(valore), "misura": etichetta,
                    "dettagli": dettagli, "partite": v["partite"],
                })
                conteggio += 1
        print(f"    stagione {stagione}: {conteggio} giocatori di riferimento")

    # ordine di presentazione: prima il quarterback, poi il resto
    ordine = {"QB": 0, "RB": 1, "WR": 2, "TE": 3}
    for squadra in per_squadra:
        for stagione in per_squadra[squadra]:
            per_squadra[squadra][stagione].sort(
                key=lambda g: (ordine.get(g["ruolo"], 9), -g["valore"]))
    return per_squadra


def num(valore):
    v = (valore or "").strip()
    if v in ("", "NA"):
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def stagioni_da_tenere(testo):
    """Le ultime cinque stagioni presenti nel file, la più recente per prima.

    Si ricavano dai dati e non dalla data odierna: il calendario della
    stagione entrante viene pubblicato con mesi di anticipo, e un calcolo
    basato sul mese la escluderebbe fino al primo lancio di settembre.
    """
    anni = set()
    for r in csv.DictReader(io.StringIO(testo)):
        a = num(r.get("season"))
        if a:
            anni.add(a)
    if not anni:
        return []
    piu_recente = max(anni)
    return [a for a in sorted(anni, reverse=True)
            if a > piu_recente - MAX_STAGIONI]


def normalizza(testo, stagioni_valide):
    righe = []
    for r in csv.DictReader(io.StringIO(testo)):
        stagione = num(r.get("season"))
        if stagione not in stagioni_valide:
            continue
        casa = (r.get("home_team") or "").strip()
        ospite = (r.get("away_team") or "").strip()
        if not (casa and ospite):
            continue
        righe.append({
            "Stagione": str(stagione),
            "Settimana": (r.get("week") or "").strip(),
            "Tipo": (r.get("game_type") or "").strip(),
            "Data": (r.get("gameday") or "").strip(),
            "Ora": (r.get("gametime") or "").strip(),
            "Casa": casa,
            "Ospite": ospite,
            "PuntiCasa": (r.get("home_score") or "").strip(),
            "PuntiOspite": (r.get("away_score") or "").strip(),
            "Stadio": (r.get("stadium") or "").strip(),
            "Copertura": (r.get("roof") or "").strip(),
            "Superficie": (r.get("surface") or "").strip(),
            "Temperatura": (r.get("temp") or "").strip(),
            "Vento": (r.get("wind") or "").strip(),
        })
    return righe


def salva_archivio(righe):
    righe = sorted(righe, key=lambda r: (r["Data"], r["Casa"]))
    ARCHIVIO.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVIO.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNE, extrasaction="ignore")
        w.writeheader()
        w.writerows(righe)
    return righe


def calcola_statistiche(righe, anagrafica=None, giocatori=None):
    """Aggrega per squadra e per stagione."""
    squadre = defaultdict(lambda: defaultdict(lambda: {
        "partite": 0, "vittorie": 0, "sconfitte": 0, "pareggi": 0,
        "puntiFatti": 0, "puntiSubiti": 0,
        "partiteCasa": 0, "vittorieCasa": 0,
        "partiteFuori": 0, "vittorieFuori": 0,
    }))

    giocate = 0
    for r in righe:
        pc, po = num(r.get("PuntiCasa")), num(r.get("PuntiOspite"))
        if pc is None or po is None:
            continue          # partita non ancora disputata
        giocate += 1
        stagione = r["Stagione"]

        for nome, propri, altrui, in_casa in (
            (r["Casa"], pc, po, True), (r["Ospite"], po, pc, False),
        ):
            s = squadre[nome][stagione]
            s["partite"] += 1
            s["puntiFatti"] += propri
            s["puntiSubiti"] += altrui
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

    anagrafica = anagrafica or {}
    lista = []
    for nome, per_stagione in squadre.items():
        info = anagrafica.get(nome, {})
        stagioni = []
        for stagione, s in sorted(per_stagione.items(), reverse=True):
            stagioni.append({
                "stagione": stagione,
                "partite": s["partite"],
                "vittorie": s["vittorie"], "sconfitte": s["sconfitte"],
                "pareggi": s["pareggi"],
                "percVittorie": media(s["vittorie"] * 100, s["partite"]),
                "puntiFatti": s["puntiFatti"], "puntiSubiti": s["puntiSubiti"],
                "mediaFatti": media(s["puntiFatti"], s["partite"]),
                "mediaSubiti": media(s["puntiSubiti"], s["partite"]),
                "differenza": s["puntiFatti"] - s["puntiSubiti"],
                "vittorieCasa": s["vittorieCasa"], "partiteCasa": s["partiteCasa"],
                "vittorieFuori": s["vittorieFuori"], "partiteFuori": s["partiteFuori"],
            })
        tot = {k: sum(x[k] for x in per_stagione.values())
               for k in ("partite", "vittorie", "sconfitte", "pareggi",
                         "puntiFatti", "puntiSubiti")}
        lista.append({
            "nome": nome,
            "nomeCompleto": info.get("nomeCompleto") or nome,
            "conference": info.get("conference"),
            "division": info.get("division"),
            "partite": tot["partite"], "vittorie": tot["vittorie"],
            "sconfitte": tot["sconfitte"], "pareggi": tot["pareggi"],
            "percVittorie": media(tot["vittorie"] * 100, tot["partite"]),
            "mediaFatti": media(tot["puntiFatti"], tot["partite"]),
            "mediaSubiti": media(tot["puntiSubiti"], tot["partite"]),
            "differenza": tot["puntiFatti"] - tot["puntiSubiti"],
            "perStagione": stagioni,
            "giocatori": (giocatori or {}).get(nome, {}),
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

    ultime = []
    for r in recenti:
        ultime.append({
            "stagione": r["Stagione"], "settimana": r["Settimana"],
            "tipo": r["Tipo"], "data": r["Data"], "ora": r["Ora"] or None,
            "casa": r["Casa"], "ospite": r["Ospite"],
            "pc": num(r["PuntiCasa"]), "po": num(r["PuntiOspite"]),
            "stadio": r["Stadio"] or None,
        })

    stagioni = sorted({r["Stagione"] for r in righe}, reverse=True)
    return {
        "aggiornato": datetime.now(timezone.utc).isoformat(),
        "campionato": "NFL",
        "fonte": "nflverse (CC-BY-SA 4.0)",
        "stagioni": stagioni,
        "totalePartite": len(righe),
        "partiteGiocate": giocate,
        "squadre": lista,
        "conferences": sorted({s["conference"] for s in lista if s.get("conference")}),
        "divisions": sorted({s["division"] for s in lista if s.get("division")}),
        "ultimePartite": ultime,
    }


def main():
    print("=" * 58)
    print("ARCHIVIO NFL")
    print("=" * 58)

    testo = scarica(PARTITE, "partite NFL")
    if not testo:
        print("\nNessun dato scaricato: esco senza modificare l'archivio.")
        raise SystemExit(1)

    stagioni = stagioni_da_tenere(testo)
    if not stagioni:
        print("  Nessuna stagione riconosciuta nel file.")
        raise SystemExit(1)
    print(f"  Stagioni conservate: {stagioni[-1]}–{stagioni[0]} ({len(stagioni)})")

    righe = normalizza(testo, set(stagioni))
    print(f"  {len(righe)} partite nelle stagioni conservate")
    if not righe:
        print("  Nessuna riga: il formato del file potrebbe essere cambiato.")
        raise SystemExit(1)

    print()
    anagrafica = carica_anagrafica()

    print("\nGiocatori di riferimento")
    giocatori = carica_giocatori(stagioni)

    righe = salva_archivio(righe)
    stats = calcola_statistiche(righe, anagrafica, giocatori)

    USCITA.parent.mkdir(parents=True, exist_ok=True)
    USCITA.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    print(f"\nSquadre: {len(stats['squadre'])}")
    print(f"Partite giocate: {stats['partiteGiocate']}/{stats['totalePartite']}")
    if stats["squadre"]:
        t = stats["squadre"][0]
        print(f"Miglior percentuale: {t['nome']} — {t['percVittorie']}%")
    print(f"\n✓ Scritto {USCITA}")


if __name__ == "__main__":
    main()
