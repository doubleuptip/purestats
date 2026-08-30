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
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

RADICE = Path(__file__).resolve().parent.parent
ARCHIVIO = RADICE / "data" / "college.csv"
USCITA = RADICE / "docs" / "data_college.json"

BASE = "https://api.collegefootballdata.com"
UA = "Mozilla/5.0 (compatible; PureStats/1.0)"
PAUSA = 1.0

MAX_STAGIONI = 5

COLONNE = [
    "Stagione", "Settimana", "Tipo", "Data",
    "Casa", "Ospite", "PuntiCasa", "PuntiOspite",
    "ConferenzaCasa", "ConferenzaOspite", "CampoNeutro", "Stadio", "Spettatori",
]


# Conference della prima divisione (FBS). Il college football conta oltre
# settecento squadre fra tutte le categorie: senza questo filtro la
# classifica diventerebbe illeggibile e l'archivio enorme.
#
# Si chiede all'API la sola prima divisione e in più si verifica qui la
# conference, perché nelle partite fuori categoria una delle due squadre
# appartiene comunque a una divisione inferiore.
CONFERENCE_FBS = {
    # Power conferences
    "SEC", "Big Ten", "ACC", "Big 12", "Pac-12", "Pac-10",
    # Group of Five
    "American Athletic", "American", "Mountain West", "Sun Belt",
    "Conference USA", "Mid-American", "MAC",
    # Indipendenti
    "FBS Independents", "Independent",
}


def e_prima_divisione(conferenza):
    """Vero se la conference appartiene alla prima divisione."""
    c = (conferenza or "").strip()
    return bool(c) and c in CONFERENCE_FBS


def chiave_api():
    k = os.environ.get("CFBD_API_KEY", "").strip()
    if not k:
        print("ERRORE: variabile d'ambiente CFBD_API_KEY non impostata.")
        print("La chiave gratuita si richiede su collegefootballdata.com/key")
        print("e va salvata fra i secret del repository.")
        raise SystemExit(1)
    return k


def chiama(percorso, **parametri):
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


def stagioni_da_scaricare():
    esplicite = os.environ.get("STAGIONI", "").strip()
    if esplicite:
        return [int(s) for s in esplicite.replace(",", " ").split() if s.isdigit()]
    oggi = datetime.now(timezone.utc)
    # la stagione comincia ad agosto e prende il nome dell'anno d'inizio
    corrente = oggi.year if oggi.month >= 8 else oggi.year - 1
    return list(range(corrente, corrente - MAX_STAGIONI, -1))


def normalizza(partite, stagione):
    righe = []
    scartate = 0
    for g in partite or []:
        casa = (g.get("homeTeam") or g.get("home_team") or "").strip()
        ospite = (g.get("awayTeam") or g.get("away_team") or "").strip()
        if not (casa and ospite):
            continue

        conf_casa = (g.get("homeConference") or g.get("home_conference") or "").strip()
        conf_ospite = (g.get("awayConference") or g.get("away_conference") or "").strip()
        if not (e_prima_divisione(conf_casa) or e_prima_divisione(conf_ospite)):
            scartate += 1
            continue
        data = (g.get("startDate") or g.get("start_date") or "")[:10]
        righe.append({
            "Stagione": str(stagione),
            "Settimana": str(g.get("week") or ""),
            "Tipo": (g.get("seasonType") or g.get("season_type") or "").strip(),
            "Data": data,
            "Casa": casa,
            "Ospite": ospite,
            "PuntiCasa": "" if g.get("homePoints") is None and g.get("home_points") is None
                         else str(g.get("homePoints", g.get("home_points"))),
            "PuntiOspite": "" if g.get("awayPoints") is None and g.get("away_points") is None
                           else str(g.get("awayPoints", g.get("away_points"))),
            "ConferenzaCasa": (g.get("homeConference") or g.get("home_conference") or "").strip(),
            "ConferenzaOspite": (g.get("awayConference") or g.get("away_conference") or "").strip(),
            "CampoNeutro": "1" if g.get("neutralSite") or g.get("neutral_site") else "",
            "Stadio": (g.get("venue") or "").strip(),
            "Spettatori": str(g.get("attendance") or ""),
        })
    if scartate:
        print(f"      {scartate} partite di divisioni inferiori scartate")
    return righe


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
    righe = sorted(righe, key=lambda r: (r["Data"], r["Casa"]))
    ARCHIVIO.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVIO.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNE, extrasaction="ignore")
        w.writeheader()
        w.writerows(righe)
    return righe


def chiave(r):
    return (r.get("Stagione"), r.get("Data"), r.get("Casa"), r.get("Ospite"))


def calcola_statistiche(righe):
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

    ultime = []
    for r in reversed(righe[-60:]):
        ultime.append({
            "stagione": r["Stagione"], "settimana": r["Settimana"],
            "data": r["Data"], "casa": r["Casa"], "ospite": r["Ospite"],
            "pc": num(r["PuntiCasa"]), "po": num(r["PuntiOspite"]),
            "conferenzaCasa": r.get("ConferenzaCasa") or None,
            "stadio": r.get("Stadio") or None,
        })

    return {
        "aggiornato": datetime.now(timezone.utc).isoformat(),
        "campionato": "College Football",
        "fonte": "CollegeFootballData.com",
        "stagioni": sorted({r["Stagione"] for r in righe}, reverse=True),
        "totalePartite": len(righe),
        "partiteGiocate": giocate,
        "squadre": lista,
        "conferences": sorted({s["conferenza"] for s in lista if s.get("conferenza")}),
        "ultimePartite": ultime,
    }


def main():
    print("=" * 58)
    print("ARCHIVIO COLLEGE FOOTBALL")
    print("=" * 58)

    archivio = carica_archivio()
    print(f"\nArchivio esistente: {len(archivio)} partite")
    indice = {chiave(r): r for r in archivio}
    prima = len(indice)

    stagioni = stagioni_da_scaricare()
    print(f"Stagioni da scaricare: {stagioni[-1]}–{stagioni[0]} ({len(stagioni)})")

    scaricate = 0
    for i, anno in enumerate(stagioni):
        if i:
            time.sleep(PAUSA)
        print(f"\nStagione {anno}")
        for tipo in ("regular", "postseason"):
            # 'classification' è il nome attuale del parametro; le versioni
            # precedenti usavano 'division'. Si passano entrambi: quello
            # non riconosciuto viene ignorato dal servizio.
            partite = chiama("games", year=anno, seasonType=tipo,
                             classification="fbs", division="fbs")
            if partite is None:
                continue
            righe = normalizza(partite, anno)
            nuove = sum(1 for r in righe if chiave(r) not in indice)
            for r in righe:
                indice[chiave(r)] = r
            print(f"    {tipo}: {len(righe)} partite ({nuove} nuove)")
            scaricate += len(righe)

    if not scaricate and prima == 0:
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

    stats = calcola_statistiche(righe)
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    USCITA.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                      encoding="utf-8")

    print(f"\nSquadre: {len(stats['squadre'])}")
    print(f"Partite giocate: {stats['partiteGiocate']}/{stats['totalePartite']}")
    print(f"\n✓ Scritto {USCITA}")


if __name__ == "__main__":
    main()
