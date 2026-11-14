"""
College Football da ESPN: calendario, risultati, campo neutro, linee e tabellini.

Dal 14/11/2026 sostituisce CollegeFootballData per tutto ciò che ESPN dà gratis e senza chiave
(CollegeFootballData ha 1.000 chiamate al mese condivise con il bot: resta solo per SP+ e i loghi).
Verificato prima del passaggio:
- gli id delle partite ESPN sono gli stessi di CollegeFootballData (e del play-by-play cfbfastR);
- i nomi delle squadre (team.location) sono gli stessi, compresi Hawai'i, San José State, UL Monroe;
- le settimane coincidono (2025 e 2026), e le partite 2026 settimane 1-10 sono identiche all'archivio
  (squadre, punteggi, campo neutro);
- le linee restano disponibili anche dopo la partita (core API, una richiesta per partita).

Endpoint pubblici usati (gli stessi della pagina ESPN), con una pausa tra le richieste:
  site.api.espn.com/.../college-football/scoreboard?groups=80&dates=<anno>&week=<n>&seasontype=<2|3>
  site.api.espn.com/.../college-football/summary?event=<id>                 (tabellino)
  sports.core.api.espn.com/.../college-football/events/<id>/competitions/<id>/odds   (linee)
Solo libreria standard.
"""
from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SITO = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
UA = {"User-Agent": "Mozilla/5.0 (compatible; PureStats/1.0)", "Accept": "application/json"}
PAUSA = 0.4
SETTIMANE_MAX = 16

# id della conference ESPN -> nome usato nell'archivio (gli stessi nomi di CollegeFootballData),
# verificato il 14/11/2026 sulle squadre della stagione
CONFERENZE = {
    "1": "ACC", "4": "Big 12", "5": "Big Ten", "8": "SEC", "9": "Pac-12", "12": "Conference USA",
    "15": "Mid-American", "17": "Mountain West", "18": "FBS Independents", "37": "Sun Belt",
    "151": "American Athletic",
    "20": "Big Sky", "21": "MVFC", "24": "MEAC", "25": "NEC", "27": "Patriot", "29": "Southern",
    "30": "Southland", "31": "SWAC", "32": "FCS Independents", "48": "Coastal Athletic", "177": "UAC",
    "179": "OVC",
}

chiamate = {"scoreboard": 0, "tabellini": 0, "linee": 0, "errori": 0}


def _json(url: str, tentativi: int = 3):
    """Una richiesta con pausa e qualche nuovo tentativo; None se non riesce (e lo dice)."""
    for i in range(tentativi):
        time.sleep(PAUSA * (i + 1))
        try:
            with urlopen(Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 404:
                return None
            ultimo = f"HTTP {e.code}"
        except (URLError, TimeoutError, OSError) as e:
            ultimo = f"rete: {e}"
        except json.JSONDecodeError as e:
            ultimo = f"risposta non interpretabile: {e}"
    chiamate["errori"] += 1
    print(f"    ESPN non raggiungibile per {url.split('?')[0].rsplit('/', 1)[-1]} ({ultimo}) dopo {tentativi} tentativi")
    return None


def _squadra(c: dict) -> tuple[str, str]:
    t = c.get("team") or {}
    return (t.get("location") or "").strip(), CONFERENZE.get(str(t.get("conferenceId") or ""), "")


def partite_settimana(stagione: int, settimana: int, tipo: str = "regular") -> list | None:
    """Partite di una settimana nella forma dell'archivio, più id, inizio e stato. None se ESPN non risponde."""
    st = 2 if tipo == "regular" else 3
    d = _json(f"{SITO}/scoreboard?groups=80&dates={stagione}&week={settimana}&seasontype={st}&limit=400")
    chiamate["scoreboard"] += 1
    if d is None:
        return None
    out = []
    for e in d.get("events") or []:
        c = (e.get("competitions") or [{}])[0]
        casa = next((x for x in c.get("competitors") or [] if x.get("homeAway") == "home"), None)
        ospite = next((x for x in c.get("competitors") or [] if x.get("homeAway") == "away"), None)
        if not casa or not ospite:
            continue
        (nc, cc), (no, co) = _squadra(casa), _squadra(ospite)
        if not nc or not no or "TBD" in (nc, no):          # incroci non ancora decisi (finali di conference)
            continue
        finita = bool(((c.get("status") or {}).get("type") or {}).get("completed"))
        pubblico = c.get("attendance") or 0
        out.append({
            "id": str(e.get("id")), "inizio": e.get("date") or "", "finita": finita,
            "Stagione": str(stagione), "Settimana": str(settimana), "Tipo": tipo,
            "Data": (e.get("date") or "")[:10], "Casa": nc, "Ospite": no,
            "PuntiCasa": str(int(float(casa.get("score")))) if finita and casa.get("score") not in (None, "") else "",
            "PuntiOspite": str(int(float(ospite.get("score")))) if finita and ospite.get("score") not in (None, "") else "",
            "ConferenzaCasa": cc, "ConferenzaOspite": co,
            "CampoNeutro": "1" if c.get("neutralSite") else "",
            "Stadio": ((c.get("venue") or {}).get("fullName") or "").strip(),
            "Spettatori": str(pubblico) if finita and pubblico else "",
        })
    return out


def partite_stagione(stagione: int) -> list | None:
    """Tutta la stagione: settimane 1-16 e postseason. None se ESPN non ha risposto per più di 2 settimane
    (meglio non toccare l'archivio con una stagione a metà)."""
    tutte, mancate = [], 0
    for w in range(1, SETTIMANE_MAX + 1):
        p = partite_settimana(stagione, w, "regular")
        if p is None:
            mancate += 1
            continue
        tutte += p
    post = partite_settimana(stagione, 1, "postseason")
    if post is None:
        mancate += 1
    else:
        tutte += post
    if mancate > 2:
        print(f"    ESPN: {mancate} richieste non riuscite per la stagione {stagione}: stagione non usata")
        return None
    return tutte


def linea(evento: str) -> dict | None:
    """Linea pre-partita di un evento: {"margine": margine atteso per la casa (positivo = casa favorita),
    "totale", "fornitore"}. ESPN scrive lo spread dal punto di vista della casa (−7 = casa favorita di 7),
    come CollegeFootballData. Si ignorano le quote «live» (cambiano durante la partita)."""
    d = _json(f"{CORE}/events/{evento}/competitions/{evento}/odds")
    chiamate["linee"] += 1
    if not d:
        return None
    for o in d.get("items") or []:
        nome = ((o.get("provider") or {}).get("name") or "").strip()
        if "live" in nome.lower():
            continue
        sp, ou = o.get("spread"), o.get("overUnder")
        if sp is None and ou is None:
            continue
        return {"margine": None if sp is None else -float(sp), "totale": None if ou is None else float(ou),
                "fornitore": nome}
    return None


def tabellino_completo(evento: str) -> dict | None:
    """Tabellino intero della partita, tutti i giocatori di tutte le tabelle (passaggi, corse, ricezioni,
    difesa, intercetti, fumble, calci, punt, ritorni), in forma compatta:
      {"squadre": {squadra: {categoria: [[id ESPN, nome, valore, valore, ...], ...]}},
       "etichette": {categoria: [etichetta, etichetta, ...]}}
    I valori restano testo come li scrive ESPN («24/35», «4.5»). None se ESPN non risponde."""
    d = _json(f"{SITO}/summary?event={evento}")
    chiamate["tabellini"] += 1
    if not d:
        return None
    squadre, etichette = {}, {}
    for sq in ((d.get("boxscore") or {}).get("players") or []):
        nome = ((sq.get("team") or {}).get("location") or "").strip()
        categorie = {}
        for cat in sq.get("statistics") or []:
            cn = (cat.get("name") or "").lower()
            if not cn:
                continue
            righe = []
            for a in cat.get("athletes") or []:
                at = a.get("athlete") or {}
                chi = (at.get("displayName") or "").strip()
                if chi:
                    righe.append([str(at.get("id") or ""), chi] + [str(v) for v in a.get("stats") or []])
            if righe:
                categorie[cn] = righe
                etichette.setdefault(cn, [str(x).upper() for x in cat.get("labels") or []])
        if nome:
            squadre[nome] = categorie
    return {"squadre": squadre, "etichette": etichette}


def valori_tabellino(completo: dict) -> dict:
    """Dal tabellino completo alla forma usata per i migliori della partita:
    {squadra: {(categoria, giocatore): {etichetta: valore}}}."""
    out = {}
    etichette = completo.get("etichette") or {}
    for nome, categorie in (completo.get("squadre") or {}).items():
        valori = {}
        for cn, righe in categorie.items():
            for r in righe:
                valori[(cn, r[1])] = dict(zip(etichette.get(cn) or [], r[2:]))
        out[nome] = valori
    return out


def tabellino(evento: str) -> dict | None:
    """Statistiche individuali della partita: {squadra: {(categoria, giocatore): {etichetta: valore}}},
    con le stesse categorie (passing, rushing, receiving) ed etichette (YDS, TD, INT, REC) di prima."""
    c = tabellino_completo(evento)
    return None if c is None else valori_tabellino(c)


def riepilogo() -> str:
    return (f"ESPN: {chiamate['scoreboard']} calendari, {chiamate['tabellini']} tabellini, {chiamate['linee']} linee"
            + (f", {chiamate['errori']} richieste non riuscite" if chiamate["errori"] else ""))
