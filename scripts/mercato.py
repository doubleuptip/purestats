"""Linee del mercato americano per Charlie: spread e totale di ogni partita dalla lista partite di ESPN
(DraftKings di solito), gratis e senza chiave, una richiesta per campionato a ogni giro.

Dalla stessa voce si legge anche la linea d'apertura (dal 15/11/2026): Charlie mostra di quanto si è mossa
la linea e suggerisce se una notizia è già dentro la quota.

Il «prezzo giusto» di Charlie parte da qui: la linea americana è la più efficiente (Protocollo 8), e la
probabilità di qualunque linea si ricava dagli scarti misurati sullo storico 2019-2025.
Solo libreria standard.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "purestats (statistiche personali)", "Accept": "application/json"}
SITO = {"NFL": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "College": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"}
NFL_ESPN = {"LA": "LAR", "WAS": "WSH"}          # sigle nflverse diverse da ESPN


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def _json(url: str, timeout: int = 40) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


def leggi_quota(odds: list, sigla_casa: str, sigla_ospite: str) -> dict | None:
    """Dalla voce «odds» di ESPN: margine atteso della squadra di casa (positivo = casa favorita) e totale.
    Si legge il testo «KC -3.5» (chi è favorito e di quanto), che è la forma più stabile; «EVEN» = 0."""
    for o in odds or []:
        prov = ((o.get("provider") or {}).get("name") or "").strip()
        if "live" in prov.lower():
            continue
        tot = o.get("overUnder")
        det = str(o.get("details") or "").strip()
        margine = None
        if det.upper() in ("EVEN", "PK", "PICK"):
            margine = 0.0
        else:
            m = re.match(r"^([A-Za-z&.' ]+?)\s*([+-]?\d+(?:\.\d+)?)$", det)
            if m:
                chi, v = m.group(1).strip().upper(), float(m.group(2))
                if chi == (sigla_casa or "").upper():
                    margine = -v
                elif chi == (sigla_ospite or "").upper():
                    margine = v
        if margine is None and o.get("spread") is not None:
            # riserva: «spread» di ESPN è dalla parte della casa (negativo = casa favorita)
            try:
                margine = -float(o["spread"])
            except (TypeError, ValueError):
                margine = None
        try:
            tot = float(tot) if tot is not None else None
        except (TypeError, ValueError):
            tot = None
        if margine is not None or tot is not None:
            out = {"margineCasa": margine, "totale": tot, "fonte": prov or "ESPN"}
            if (o.get("provider") or {}).get("id"):
                out["casa"] = str(o["provider"]["id"])
            ap = apertura(o)
            if ap:
                out["apertura"] = ap
            return out
    return None


def _numero_linea(v) -> float | None:
    """«-1.5», «+2.5», «o48.5», «u48.5», «PK» → numero (None se non si legge)."""
    t = str(v or "").strip().lower().lstrip("ou")
    if t in ("pk", "pick", "even", "ev"):
        return 0.0
    try:
        return float(t)
    except ValueError:
        return None


def apertura(o: dict) -> dict | None:
    """Linea d'apertura dalla voce «odds» della lista partite ESPN (stessa richiesta, nessuna chiamata in più):
    pointSpread.home.open.line («-1.5»: negativo = casa favorita) e total.over.open.line («o48.5»).
    {margineCasa, totale} con le stesse convenzioni della linea attuale; None se ESPN non la dà."""
    ps = ((o.get("pointSpread") or {}).get("home") or {}).get("open") or {}
    tt = ((o.get("total") or {}).get("over") or {}).get("open") or {}
    m, t = _numero_linea(ps.get("line")), _numero_linea(tt.get("line"))
    if m is None and t is None:
        return None
    return {"margineCasa": None if m is None else -m, "totale": t}


def _combacia(lega: str, team: dict, nome: str) -> int:
    if lega == "NFL":
        return 10 if (team.get("abbreviation") or "").upper() == NFL_ESPN.get(nome, nome).upper() else 0
    loc, n = _norm(team.get("location") or ""), _norm(nome)
    if not loc or not n:
        return 0
    if loc == n:
        return 1000
    return len(loc) if n.startswith(loc) or loc.startswith(n) else 0


def linee(lega: str, schede: list) -> int:
    """Aggiunge a ogni scheda «mercato» = {margineCasa, totale, fonte, ora, espnId}. Restituisce quante ne ha
    trovate. Se ESPN non risponde le schede restano con la linea del giro precedente."""
    # per settimana (dates=<stagione>&week=…): un intervallo di date lungo ESPN NFL lo rifiuta (400)
    settimane = set()
    for sc in schede:
        if not sc.get("inizioUtc") or sc.get("settimana") in (None, ""):
            continue
        d = datetime.fromisoformat(sc["inizioUtc"])
        settimane.add((d.year if d.month >= 3 else d.year - 1, int(sc["settimana"])))
    eventi, errori = [], []
    for stagione, w in sorted(settimane):
        url = (f"{SITO[lega]}?dates={stagione}&seasontype=2&week={w}&limit=400"
               + ("&groups=80" if lega == "College" else ""))
        try:
            eventi += _json(url).get("events") or []
        except Exception as e:     # noqa: BLE001 - una settimana che non risponde non ferma le altre
            errori.append(f"settimana {w}: {e}")
    if errori and not eventi:
        raise RuntimeError("; ".join(errori))
    ora = datetime.now(timezone.utc).isoformat(timespec="minutes")
    trovate = 0
    for sc in schede:
        meglio, punti = None, 0
        for e in eventi:
            c = (e.get("competitions") or [{}])[0]
            casa = next((x for x in c.get("competitors") or [] if x.get("homeAway") == "home"), {})
            osp = next((x for x in c.get("competitors") or [] if x.get("homeAway") == "away"), {})
            p1, p2 = _combacia(lega, casa.get("team") or {}, sc["casa"]), _combacia(lega, osp.get("team") or {}, sc["ospite"])
            if p1 and p2 and p1 + p2 > punti:
                meglio, punti = (e, c, casa, osp), p1 + p2
        if not meglio:
            continue
        e, c, casa, osp = meglio
        q = leggi_quota(c.get("odds"), (casa.get("team") or {}).get("abbreviation"),
                        (osp.get("team") or {}).get("abbreviation"))
        vecchio = sc.get("mercato") or {}
        nuovo = {"espnId": str(e.get("id") or vecchio.get("espnId") or ""),
                 "idCasa": str((casa.get("team") or {}).get("id") or vecchio.get("idCasa") or ""),
                 "idOspite": str((osp.get("team") or {}).get("id") or vecchio.get("idOspite") or "")}
        if q:
            nuovo.update(q, ora=ora)
            trovate += 1
        elif vecchio.get("totale") is not None or vecchio.get("margineCasa") is not None:
            nuovo.update({k: vecchio.get(k) for k in ("margineCasa", "totale", "fonte", "ora", "apertura", "casa") if k in vecchio})
        sc["mercato"] = nuovo
    return trovate


# ---------------------------------------------------------------- prop dei giocatori (dal 15/11/2026)
CORE = {"NFL": "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl",
        "College": "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"}
# tipi ESPN delle prop → statistiche di Charlie (stessi nomi di STAT_PROP nella pagina)
TIPI_PROP = {"8": "yardLanciate", "12": "yardCorsa", "13": "yardRicevute", "14": "ricezioni", "11": "tentativiCorsa"}


def linea_principale(voci: list) -> dict | None:
    """Tra le voci di un giocatore per una statistica sceglie la linea principale. ESPN mette la principale due
    volte (over e under) e le linee alternative una volta sola, a scaletta; quando ci sono le quote (ESPN BET,
    2023-2025) la principale è quella con le quote più vicine alla parità. {l, ap} oppure None."""
    con_quote = []
    for v in voci:
        cur = v.get("current") or {}
        q = cur.get("over") or cur.get("under")
        if q and q.get("decimal"):
            con_quote.append((abs(float(q["decimal"]) - 1.91), v))
    if con_quote:
        v = min(con_quote, key=lambda t: t[0])[1]
    else:
        conta = {}
        for v in voci:
            x = ((v.get("current") or {}).get("target") or {}).get("value")
            if x is not None:
                conta.setdefault(float(x), []).append(v)
        doppie = [(x, vv) for x, vv in conta.items() if len(vv) == 2]
        if len(doppie) != 1:          # nessuna coppia o più coppie: non si sa quale sia la principale
            return None
        v = doppie[0][1][0]
    l = ((v.get("current") or {}).get("target") or {}).get("value")
    ap = ((v.get("open") or {}).get("target") or {}).get("value")
    if l is None:
        return None
    return {"l": float(l), "ap": None if ap is None else float(ap)}


def prop_usa(lega: str, schede: list, traduci: dict | None = None) -> int:
    """Linee principali del mercato americano (la casa della linea di partita, di solito DraftKings) per le prop
    dei giocatori, dalla pagina «propBets» di ESPN: gratis, 1-2 richieste per partita. Scrive
    sc["propUSA"] = {ora, fonte, linee: {id giocatore: {statistica: {l, ap}}}}; l'id è quello di giocatoriProp
    (gsis per l'NFL, tradotto da «traduci» = {id ESPN: gsis}; ESPN per il college). Restituisce le partite lette.
    Se ESPN non risponde la scheda tiene le linee del giro precedente."""
    ora = datetime.now(timezone.utc).isoformat(timespec="minutes")
    lette = 0
    for sc in schede:
        mk = sc.get("mercato") or {}
        eid = mk.get("espnId")
        if not eid:
            continue
        casa = mk.get("casa") or "100"
        voci, pagina, pagine = [], 1, 1
        try:
            while pagina <= pagine and pagina <= 4:
                d = _json(f"{CORE[lega]}/events/{eid}/competitions/{eid}/odds/{casa}/propBets?limit=1000&page={pagina}")
                voci += d.get("items") or []
                pagine = int(d.get("pageCount") or 1)
                pagina += 1
        except Exception as e:     # noqa: BLE001 - una partita che non risponde non ferma le altre
            print(f"{lega}: prop ESPN non lette per {sc.get('ospite')} @ {sc.get('casa')} ({e})")
            continue
        gruppi = {}
        for v in voci:
            stat = TIPI_PROP.get(str((v.get("type") or {}).get("id")))
            rif = (v.get("athlete") or {}).get("$ref") or ""
            m = re.search(r"/athletes/(\d+)", rif)
            if stat and m:
                gruppi.setdefault((m.group(1), stat), []).append(v)
        linee = {}
        for (aid, stat), vv in gruppi.items():
            pid = (traduci or {}).get(aid, aid) if lega == "NFL" else aid
            if lega == "NFL" and traduci is not None and aid not in traduci:
                continue
            lp = linea_principale(vv)
            if lp:
                linee.setdefault(pid, {})[stat] = lp
        if linee:
            sc["propUSA"] = {"ora": ora, "fonte": mk.get("fonte") or "ESPN", "linee": linee}
            lette += 1
    return lette


# ---------------------------------------------------------------- inattivi (dal 16/11/2026)
def lista_del_giorno(lega: str, espn_id: str, id_squadra: str) -> dict | None:
    """Lista dei giocatori della partita (core API ESPN, competitors/<squadra>/roster): prima del via ha già
    il segno didNotPlay per gli inattivi, che le squadre pubblicano 90 minuti prima (come immagine sui social:
    qui arrivano come dati). ESPN qui scrive solo il cognome: si tiene anche l'id ESPN del giocatore, che si
    traduce in nome completo e ruolo con players.csv di nflverse. {inattivi: [[cognome, id]], attivi: [[...]]}
    oppure None se la lista non è ancora uscita (nessun inattivo segnato: ogni squadra ne dichiara sempre)."""
    d = _json(f"{CORE[lega]}/events/{espn_id}/competitions/{espn_id}/competitors/{id_squadra}/roster")
    inattivi, attivi = [], []
    for v in d.get("entries") or []:
        nome, pid = v.get("displayName") or "", str(v.get("playerId") or "")
        if not nome and not pid:
            continue
        (inattivi if v.get("didNotPlay") else attivi).append([nome, pid])
    if not inattivi:
        return None
    return {"inattivi": inattivi, "attivi": attivi}


def inattivi(lega: str, schede: list) -> int:
    """Per le partite NFL che iniziano entro 2 ore e mezza (o iniziate da meno di mezz'ora) legge la lista del
    giorno delle due squadre: 2 richieste per partita, gratis. Scrive sc["inattivi"] = {ora, casa, ospite}
    (casa/ospite come lista_del_giorno). Una volta letta non si richiede più. Restituisce le partite lette."""
    adesso = datetime.now(timezone.utc)
    lette = 0
    for sc in schede:
        mk = sc.get("mercato") or {}
        if (sc.get("inattivi") or {}).get("casa") and (sc.get("inattivi") or {}).get("ospite"):
            continue
        if not (sc.get("inizioUtc") and mk.get("espnId") and mk.get("idCasa") and mk.get("idOspite")):
            continue
        manca = datetime.fromisoformat(sc["inizioUtc"]) - adesso
        if not timedelta(minutes=-30) < manca < timedelta(minutes=150):
            continue
        try:
            casa = lista_del_giorno(lega, mk["espnId"], mk["idCasa"])
            osp = lista_del_giorno(lega, mk["espnId"], mk["idOspite"])
        except Exception as e:     # noqa: BLE001 - una partita che non risponde non ferma le altre
            print(f"{lega}: lista del giorno non letta per {sc.get('ospite')} @ {sc.get('casa')} ({e})")
            continue
        if casa or osp:
            sc["inattivi"] = {"ora": adesso.isoformat(timespec="minutes"), "casa": casa, "ospite": osp}
            lette += 1
    return lette
