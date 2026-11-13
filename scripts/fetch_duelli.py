"""Sezione privata NFL e College: partite, giocatori chiave, reparti e vantaggi dati dalle difese.

Uso: python scripts/fetch_duelli.py nfl|college, subito dopo fetch_nfl.py / fetch_college.py nello stesso
workflow: legge il file locale data/privato_<lega>.json (prossimo turno, indici, giocatori chiave, mai
committato), scarica il play-by-play della stagione e calcola con scripts/reparti.py:
  - per ogni reparto (corse, passaggi, pressione, giocate lunghe) la posizione di attacco e difesa;
  - i vantaggi: difesa tra le peggiori (vantaggio per l'attacco) o tra le migliori (vantaggio per la difesa);
  - per ogni giocatore chiave la previsione di yard: media della stagione + effetto della difesa che trova;
  - margine e totale attesi per effetto delle due difese, in punti tarati sullo storico 2019–2025;
  - la "forza" di ogni vantaggio (effetto diviso la variabilità normale) per la classifica dei migliori.
Solo statistiche: nessuna quota, nessuna indicazione di gioco. I bookmaker tengono già conto di tutto questo
(verificato sulle linee NFL di chiusura): i vantaggi sono un quadro per il giudizio, non un vantaggio sulla quota.

Il risultato viene CIFRATO con la password nel secret DUELLI_PASSWORD e scritto in docs/duelli_<lega>.dat.
Il repository è pubblico: i dati in chiaro non vengono mai scritti su disco né stampati nei log.
Senza password lo script si ferma senza toccare nulla.

Cifratura (verificabile, solo libreria standard):
  chiave = PBKDF2-HMAC-SHA256(password, sale casuale, ITERAZIONI) -> 64 byte: 32 cifratura + 32 controllo
  flusso = SHA-256(chiave_cifratura || nonce || contatore a 4 byte), blocco dopo blocco, in XOR coi dati
  controllo = HMAC-SHA256(chiave_controllo, nonce || dati cifrati): una password sbagliata viene riconosciuta
La pagina rifà gli stessi passaggi nel browser con WebCrypto.

Fonti (gratuite, nessuna chiave): play-by-play nflverse (CC-BY-SA 4.0) per l'NFL e cfbfastR
(sportsdataverse-data) per il college.
"""
from __future__ import annotations

import base64
import csv
from collections import defaultdict
import gzip
import hashlib
import hmac
import io
import json
import os
import secrets
import shutil
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reparti as RP  # noqa: E402
import contesto as C  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
LEGHE = {"nfl": "NFL", "college": "College"}
ITERAZIONI = 200_000
VERSIONE = 2
PBP = {"nfl": "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{s}.csv.gz",
       "college": "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/cfbfastR_cfb_pbp/play_by_play_{s}.csv"}
UA = {"User-Agent": "purestats (statistiche personali)"}
REPARTO_GIOCATORE = {"QB": "passaggi", "WR": "passaggi", "TE": "passaggi", "RIC": "passaggi", "RB": "corse"}
csv.field_size_limit(10**8)



# ------------------------------------------------------------------ cifratura
def cifra(testo: bytes, password: str) -> dict:
    sale, nonce = secrets.token_bytes(16), secrets.token_bytes(16)
    chiave = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sale, ITERAZIONI, dklen=64)
    k_cif, k_mac = chiave[:32], chiave[32:]
    flusso = bytearray()
    contatore = 0
    while len(flusso) < len(testo):
        flusso += hashlib.sha256(k_cif + nonce + contatore.to_bytes(4, "big")).digest()
        contatore += 1
    cifrato = bytes(a ^ b for a, b in zip(testo, flusso))
    mac = hmac.new(k_mac, nonce + cifrato, hashlib.sha256).digest()
    b64 = lambda x: base64.b64encode(x).decode("ascii")
    return {"versione": VERSIONE, "iterazioni": ITERAZIONI, "sale": b64(sale), "nonce": b64(nonce),
            "mac": b64(mac), "dati": b64(cifrato)}


def decifra(pacchetto: dict, password: str) -> bytes:
    """Usata solo per verificare il file appena scritto (stessa procedura della pagina)."""
    d = lambda k: base64.b64decode(pacchetto[k])
    chiave = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), d("sale"), pacchetto["iterazioni"], dklen=64)
    nonce, cifrato = d("nonce"), d("dati")
    if not hmac.compare_digest(hmac.new(chiave[32:], nonce + cifrato, hashlib.sha256).digest(), d("mac")):
        raise ValueError("controllo non superato")
    flusso = bytearray()
    i = 0
    while len(flusso) < len(cifrato):
        flusso += hashlib.sha256(chiave[:32] + nonce + i.to_bytes(4, "big")).digest()
        i += 1
    return bytes(a ^ b for a, b in zip(cifrato, flusso))


# ------------------------------------------------------------------ partite e orari
def leggi_json(percorso: Path) -> dict:
    try:
        return json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"Non riesco a leggere {percorso.name} ({e}): quel campionato resta senza duelli in questo giro.")
        return {}


def orario_roma(data: str, ora: str) -> tuple[str, str]:
    """Data e ora come le scrive PureStats (ora della costa est USA) -> data e ora italiane.
    Senza ora resta solo la data."""
    if not data:
        return "", ""
    if not ora:
        return data, ""
    try:
        from zoneinfo import ZoneInfo
        t = datetime.fromisoformat(f"{data}T{ora}").replace(tzinfo=ZoneInfo("America/New_York"))
        t = t.astimezone(ZoneInfo("Europe/Rome"))
        return t.strftime("%Y-%m-%d"), t.strftime("%H:%M")
    except Exception:                # noqa: BLE001 - fuso non disponibile: si lascia l'ora originale
        return data, ora




# ------------------------------------------------------------------ play-by-play
def azioni_stagione(lega: str, stagione: int, cartella: str) -> list:
    """Scarica il play-by-play della stagione su disco (il college pesa ~400 MB) e lo riduce alle azioni."""
    url = PBP[lega].format(s=stagione)
    percorso = Path(cartella) / f"pbp_{lega}_{stagione}"
    print(f"{LEGHE[lega]}: scarico il play-by-play {stagione}...")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=600) as r, open(percorso, "wb") as out:
        shutil.copyfileobj(r, out, length=1 << 20)
    apri = (lambda: io.TextIOWrapper(gzip.open(percorso), encoding="utf-8", newline="")) if lega == "nfl" \
        else (lambda: open(percorso, encoding="utf-8", newline=""))
    punti = {}
    with apri() as fh:
        righe = _con_punti(csv.DictReader(fh), lega, punti)
        azioni = list(RP.azioni_nflverse(righe) if lega == "nfl" else RP.azioni_cfbfastr(righe))
    percorso.unlink()
    print(f"{LEGHE[lega]}: {len(azioni)} azioni di corsa e passaggio, {len(punti)} partite con il punteggio.")
    return azioni, punti


def _con_punti(righe, lega: str, punti: dict):
    """Lascia passare le righe e intanto annota il punteggio finale di ogni partita:
    {game_id: {"w": settimana, squadra: punti}}. NFL: home_score/away_score (finali, su ogni riga);
    college: il massimo dei punti visti per squadra nella partita (i punti non scendono mai)."""
    for r in righe:
        g = r.get("game_id")
        try:
            if lega == "nfl":
                if r.get("season_type") in ("REG", "POST") and g not in punti and r.get("home_score") not in ("", "NA", None):
                    punti[g] = {"w": int(float(r["week"])), r["home_team"]: float(r["home_score"]),
                                r["away_team"]: float(r["away_score"])}
            elif r.get("pos_team") and r.get("def_pos_team"):
                d = punti.setdefault(g, {"w": int(float(r["week"]))})
                for sq, col in ((r["pos_team"], "pos_team_score"), (r["def_pos_team"], "def_pos_team_score")):
                    v = RP._f(r.get(col))
                    if v is not None:
                        d[sq] = max(d.get(sq, 0.0), v)
        except (KeyError, ValueError):
            pass
        yield r


def norma_punti(punti: dict, settimana: int) -> dict:
    """Punti segnati in media da ogni squadra nelle partite PRIMA della settimana (la «norma» della verifica)."""
    fatti = defaultdict(list)
    for d in punti.values():
        if d.get("w", 99) >= settimana:
            continue
        for sq, v in d.items():
            if sq != "w":
                fatti[sq].append(v)
    return {sq: sum(v) / len(v) for sq, v in fatti.items() if len(v) >= RP.MIN_PARTITE}


# ------------------------------------------------------------------ scheda partita
def reparti_partita(st: dict, casa: str, ospite: str) -> list[dict]:
    """Ogni reparto nei due versi, con posizioni e verdetto basato sulla difesa (la parte verificata)."""
    out = []
    for area in RP.AREE:
        for att, dif in ((ospite, casa), (casa, ospite)):
            a, d = st.get(att), st.get(dif)
            if not a or not d or area not in d["rango_dif"] or area not in a["rango_att"]:
                continue
            n = d["n"]
            migl, pegg = RP.soglie(n)
            rd = d["rango_dif"][area]
            verso = "attacco" if rd >= pegg else "difesa" if rd <= migl else None
            out.append({"area": area, "att": att, "dif": dif, "ra": a["rango_att"][area], "rd": rd, "n": n,
                        "verso": verso})
    return out


# ------------------------------------------------------------------ giudizio scritto
# Parole per lo sbilanciamento, relative al campionato: sotto la mediana delle coppie possibili = lieve,
# fino all'85° percentile = moderato, oltre = forte (misurato il 13/11 su tutte le coppie NFL 2026 sett. 11
# e college 2026 sett. 13). Il college ha valori più alti perché le squadre sono molto più diverse.
SCALA = {"NFL": {"totale": (0.10, 0.20), "margine": (0.07, 0.14)},
         "College": {"totale": (0.20, 0.43), "margine": (0.22, 0.45)}}
# Percentuali MISURATE sullo storico 2019-2025 (misure/percentuali.py e percentuali_gioc.py, 13/11):
# quante volte la partita è finita dalla parte indicata dalle difese rispetto alla norma delle due squadre,
# per livello di sbilanciamento (1.409 partite NFL, 2.979 college). Contro la linea di chiusura NFL: 47-51%.
PCT_PARTITA = {"NFL": {"totale": {"lieve": 50, "moderato": 57, "forte": 63},
                       "margine": {"lieve": 56, "moderato": 56, "forte": 56}},
               "College": {"totale": {"lieve": 57, "moderato": 63, "forte": 73},
                           "margine": {"lieve": 56, "moderato": 61, "forte": 73}}}
# Giocatori (9.997 prestazioni NFL, 19.924 college): con la difesa tra le peggiori, % di partite SOPRA la sua media;
# con la difesa tra le migliori, % di partite SOTTO la sua media. Le yard sono sbilanciate (poche partite enormi
# alzano la media), quindi di solito si sta sotto la media più spesso che sopra.
PCT_GIOCATORE = {"NFL": {"QB": (52, 53), "RB": (51, 61), "WR": (43, 60), "TE": (48, 61)},
                 "College": {"QB": (51, 59), "RB": (54, 60), "WR": (45, 61), "TE": (45, 67)}}
GIOCO = {"corse": "il gioco di corse", "passaggi": "il gioco sui passaggi", "pressione": "la protezione del QB",
         "esplosive": "le giocate lunghe"}
DIFESA = {"corse": "difesa contro le corse", "passaggi": "difesa sui passaggi", "pressione": "pressione sul QB",
          "esplosive": "difesa sulle giocate lunghe"}


def _num(x, dec=1):
    return f"{abs(x):.{dec}f}".replace(".", ",")


def parola(campionato: str, tipo: str, forza: float) -> str:
    basso, alto = SCALA[campionato][tipo]
    return "lieve" if forza < basso else "moderato" if forza < alto else "forte"


def giudizio(campionato: str, s: dict) -> str:
    """Due-quattro frasi dai numeri della scheda, sempre uguali per gli stessi numeri (niente AI esterna)."""
    nome = {s["casa"]: s["nomeCasa"], s["ospite"]: s["nomeOspite"]}
    frasi = []
    P = s.get("partita")
    if P and P.get("attesoCasa") is not None:
        ac, ao = P["attesoCasa"], P["attesoOspite"]
        nc, no = P["normaCasa"], P["normaOspite"]
        if abs(ac - ao) < 1:
            chi = "partita alla pari"
        else:
            fav = s["casa"] if ac > ao else s["ospite"]
            chi = f"{nome[fav]} avanti di {_num(ac - ao)}"
        frasi.append(f"Punteggio atteso dai numeri: {nome[s['ospite']]} {round(ao)} – {nome[s['casa']]} {round(ac)} "
                     f"({chi}; di solito segnano {_num(no)} e {_num(nc)}, senza vantaggio del campo).")
    if P:
        t = P["totale"]
        if abs(t) < 0.5:
            frasi.append("Per le difese il totale è in linea con la norma delle due squadre.")
        else:
            liv = parola(campionato, "totale", P["forzaTotale"])
            frasi.append(f"Partita spinta verso {'più' if t > 0 else 'meno'} punti del solito: {'+' if t > 0 else '−'}"
                         f"{_num(t)} rispetto alla norma delle due squadre, sbilanciamento {liv} (nello storico "
                         f"{PCT_PARTITA[campionato]['totale'][liv]}% delle volte {'sopra' if t > 0 else 'sotto'} la norma).")
        m = P["margine"]
        if abs(m) < 0.5:
            frasi.append("Sul margine le due difese si equivalgono.")
        else:
            fav = s["casa"] if m > 0 else s["ospite"]
            liv = parola(campionato, "margine", P["forzaMargine"])
            frasi.append(f"Sul margine le difese favoriscono {nome[fav]} di {_num(m)} punti rispetto alla norma "
                         f"(sbilanciamento {liv}, nello storico {PCT_PARTITA[campionato]['margine'][liv]}% delle volte "
                         f"da quella parte).")
    # assenze: chi è colpito di più (peso totale delle assenze; college con la posizione nazionale)
    for lato, sq in (("assenzeOspite", s["ospite"]), ("assenzeCasa", s["casa"])):
        a = s.get(lato)
        if not a or not a.get("giocatori"):
            continue
        fuori = [g for g in a["giocatori"] if g["stato"].upper() in ("O", "OFS", "OUT", "D", "DOUBTFUL", "S")]
        nomi = ", ".join(f"{g['nome']} ({g['ruolo']})" for g in fuori[:3])
        nuovi = [g for g in a["giocatori"] if g.get("nuovo")]
        pezzi = []
        if campionato == "College" and a.get("rango"):
            pezzi.append(f"assenze tra le più pesanti d'America ({int(a['rango'])}ª su 138, {int(a['n'] or 0)} in lista)"
                         if a["rango"] <= 15 else f"{int(a['n'] or 0)} in lista, peso delle assenze {int(a['rango'])}ª su 138")
        elif a.get("impatto"):
            pezzi.append(f"assenti per circa il {round(a['impatto'] * 10)}% della produzione")
        if nomi:
            pezzi.append("fuori " + nomi)
        if nuovi:
            pezzi.append(f"novità della settimana: {', '.join(g['nome'] for g in nuovi[:3])}")
        if pezzi:
            frasi.append(f"{nome[sq]}: " + "; ".join(pezzi) + ".")
    m = s.get("meteo")
    if m and m.get("coperto"):
        frasi.append("Stadio coperto: il meteo non conta.")
    elif m:
        if m.get("effetto"):
            frasi.append(f"Meteo: {m['effetto']['testo']}.")
        elif m.get("tempC") is not None and m["tempC"] <= 0:
            frasi.append(f"Meteo: {m['tempC']} °C, vento debole; il freddo da solo nello storico non sposta i punti.")
    fc, fo = s.get("forzaCasa"), s.get("forzaOspite")
    if fc and fo:
        n = fc["n"]
        for att, dif, sa, sd in ((fc, fo, s["casa"], s["ospite"]), (fo, fc, s["ospite"], s["casa"])):
            ra, rd = att["att"]["rango_successo"], dif["dif"]["rango_successo"]
            if ra <= n * 0.2 and rd >= n * 0.65:
                frasi.append(f"Incastro favorevole: l'attacco di {nome[sa]} è {ra}° per success rate, la difesa di "
                             f"{nome[sd]} {rd}ª su {n}.")
            elif ra >= n * 0.75 and rd <= n * 0.25:
                frasi.append(f"Incastro sfavorevole: l'attacco di {nome[sa]} è {ra}° per success rate contro una difesa "
                             f"{rd}ª su {n}.")
    netti = [r for r in s.get("reparti") or [] if r["verso"]]
    if netti:
        r = max(netti, key=lambda r: abs((r["rd"] - 1) / max(r["n"] - 1, 1) - 0.5))
        dove = "tra le più deboli" if r["verso"] == "attacco" else "tra le migliori"
        frasi.append(f"Il confronto più netto: {GIOCO[r['area']]} di {nome.get(r['att'], r['att'])} contro la "
                     f"{DIFESA[r['area']]} di {nome.get(r['dif'], r['dif'])}, {r['rd']}ª su {r['n']}, {dove}.")
    gioc = [v for v in s.get("vantaggi") or [] if v["tipo"] == "giocatore" and v.get("effetto") is not None]
    if gioc:
        v = max(gioc, key=lambda v: v["forza"])
        frasi.append(f"Tra i giocatori spicca {v['nome']} ({v['ruolo']}, {nome.get(v['squadra'], v['squadra'])}): "
                     f"{round(v['previsione'])} {v.get('misura') or 'yard'} previste contro una media di "
                     f"{round(v['media'])} ({'+' if v['effetto'] > 0 else '−'}{_num(v['effetto'])} per la difesa che trova"
                     + (f"; nello storico {v['pct']}% delle volte {'sopra' if v['verso'] == 'attacco' else 'sotto'} la sua media"
                        if v.get("pct") else "") + ").")
    if not frasi:
        return ""
    frasi.append("È una lettura della partita, non un consiglio: contro la linea del bookmaker queste indicazioni "
                 "finiscono dalla parte giusta circa una volta su due.")
    return " ".join(frasi)


def giocatori_contro(campionato: str, giocatori: list, avversario: str, st: dict) -> list[dict]:
    """Previsione di yard = media della stagione + effetto della difesa avversaria nel suo reparto."""
    out = []
    tar = RP.TARATURA_GIOCATORI[campionato]
    for p in giocatori or []:
        q = dict(p)
        ruolo = str(p.get("ruolo", "")).upper()
        ruolo = "WR" if ruolo == "RIC" else ruolo
        area = REPARTO_GIOCATORE.get(ruolo)
        d = st.get(avversario)
        q.update({"previsione": None, "effetto": None, "forza": 0.0, "vantaggio": None, "errore": None})
        if area and d and area in d["rango_dif"] and ruolo in tar and p.get("mediaStagione") is not None:
            pieno, variab, errore = tar[ruolo]
            rd, n = d["rango_dif"][area], d["n"]
            migl, pegg = RP.soglie(n)
            effetto = pieno * (d["pct_dif"][area] - 0.5)
            verso = "attacco" if rd >= pegg else "difesa" if rd <= migl else None
            pa, pd = PCT_GIOCATORE[campionato][ruolo]
            q["pct"] = pa if verso == "attacco" else pd if verso == "difesa" else None
            q.update({"areaDifesa": area, "rangoDifesa": rd, "squadreTotali": n,
                      "effetto": round(effetto, 1), "previsione": round(p["mediaStagione"] + effetto),
                      "errore": errore, "forza": round(abs(effetto) / variab, 3),
                      "vantaggio": "attacco" if rd >= pegg else "difesa" if rd <= migl else None})
        out.append(q)
    return out


def indice_squadra(indici: dict, squadra: str):
    for x in (indici or {}).get("squadre") or []:
        if x.get("squadra") == squadra:
            return {"posizione": x.get("posizione"), "netto": x.get("netto"),
                    "attacco": x.get("attacco"), "difesa": x.get("difesa")}
    return None


def scheda(campionato: str, g: dict, extra: dict | None, st: dict, loghi: dict, indici: dict,
           norma: dict | None = None) -> dict | None:
    casa, ospite = g.get("casa"), g.get("ospite")
    if casa not in st or ospite not in st:
        return None
    data, ora = orario_roma(g.get("data") or "", g.get("ora") or "")
    inizio = C.kickoff_utc(g.get("data") or "", g.get("ora") or "")
    lc, lo = loghi.get(casa) or {}, loghi.get(ospite) or {}
    extra = extra or {}
    gc = giocatori_contro(campionato, extra.get("giocatoriCasa"), ospite, st)
    go = giocatori_contro(campionato, extra.get("giocatoriOspite"), casa, st)
    tp = RP.TARATURA_PUNTI[campionato]
    pc, po = RP.punti_difesa(st, casa, ospite), RP.punti_difesa(st, ospite, casa)
    partita = None
    if pc is not None and po is not None:
        tot, marg = tp["totale"] * (pc + po), tp["margine"] * (pc - po)
        partita = {"totale": round(tot, 1), "margine": round(marg, 1),
                   "forzaTotale": round(abs(tot) / tp["var_totale"], 3),
                   "forzaMargine": round(abs(marg) / tp["var_margine"], 3),
                   "puntiCasa": round(tp["totale"] * pc, 1), "puntiOspite": round(tp["totale"] * po, 1)}
        for tipo, forza in (("totale", partita["forzaTotale"]), ("margine", partita["forzaMargine"])):
            liv = parola(campionato, tipo, forza)
            partita["livello" + tipo.capitalize()] = liv
            partita["pct" + tipo.capitalize()] = PCT_PARTITA[campionato][tipo][liv]
        # punteggio atteso = punti segnati di solito + effetto delle difese diviso tra le due squadre in modo che
        # somma e differenza rispettino le tarature di totale e margine. Senza vantaggio del campo.
        if norma and casa in norma and ospite in norma:
            partita.update({"normaCasa": round(norma[casa], 1), "normaOspite": round(norma[ospite], 1),
                            "attesoCasa": round(norma[casa] + (tot + marg) / 2, 1),
                            "attesoOspite": round(norma[ospite] + (tot - marg) / 2, 1)})
    rep = reparti_partita(st, casa, ospite)
    # vantaggi in evidenza: giocatori con difesa agli estremi, poi reparti agli estremi
    vantaggi = []
    for squadra, gruppo in ((casa, gc), (ospite, go)):
        for p in gruppo:
            if p["vantaggio"]:
                vantaggi.append({"tipo": "giocatore", "verso": p["vantaggio"], "squadra": squadra,
                                 "difesa": ospite if squadra == casa else casa, "nome": p.get("nome"),
                                 "ruolo": p.get("ruolo"), "misura": p.get("misura"), "media": p.get("mediaStagione"),
                                 "previsione": p["previsione"], "effetto": p["effetto"], "forza": p["forza"],
                                 "areaDifesa": p["areaDifesa"], "rangoDifesa": p["rangoDifesa"], "n": p["squadreTotali"],
                                 "pct": p.get("pct")})
    for r in rep:
        if r["verso"]:
            # ordine tra i reparti: prima le difese più agli estremi (non entra nei 3 migliori)
            vantaggi.append({"tipo": "reparto", **r, "forza": round(abs((r["rd"] - 1) / max(r["n"] - 1, 1) - 0.5) / 100, 5)})
    vantaggi.sort(key=lambda v: (v["tipo"] != "giocatore", -v["forza"]))
    out = {"campionato": campionato, "data": data, "ora": ora, "casa": casa, "ospite": ospite,
           "inizioUtc": inizio.isoformat() if inizio else None,
            "nomeCasa": lc.get("breve") or casa, "nomeOspite": lo.get("breve") or ospite,
            "logoCasa": lc.get("logo") or "", "logoOspite": lo.get("logo") or "",
            "coloreCasa": lc.get("colore") or "", "coloreOspite": lo.get("colore") or "",
            "conferenceCasa": g.get("confCasa"), "conferenceOspite": g.get("confOspite"),
            "indiceCasa": indice_squadra(indici, casa), "indiceOspite": indice_squadra(indici, ospite),
            "giocatoriCasa": gc, "giocatoriOspite": go, "partita": partita,
            "vantaggi": vantaggi, "reparti": rep}
    out["giudizio"] = giudizio(campionato, out)
    return out


# ------------------------------------------------------------------ contesto: forza, assenze, meteo
ASSENTI_MOSTRATI = 6


def _assenze_brevi(d: dict | None) -> dict | None:
    if not d:
        return None
    gio = [g for g in d.get("giocatori") or [] if g.get("stato", "").upper() not in ("P", "PROBABLE", "A")]
    return {**{k: d.get(k) for k in ("n", "nuovi", "impatto", "rango")}, "giocatori": gio[:ASSENTI_MOSTRATI],
            "altri": max(0, len(gio) - ASSENTI_MOSTRATI)}


def quote_produzione_nfl(stagione: int) -> dict:
    """{gsis: (quota delle yard di squadra, ruolo)} dalla stagione nflverse: pesa l'assenza di un giocatore NFL.
    QB: quota dei lanci della squadra; gli altri: quota delle yard da corsa e ricezione."""
    url = f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{stagione}.csv"
    righe = list(csv.DictReader(io.StringIO(C._get(url, 120))))
    tot = defaultdict(lambda: [0.0, 0.0])
    gio = defaultdict(lambda: [0.0, 0.0, "", ""])
    for r in righe:
        if r.get("season_type") != "REG":
            continue
        att, yds = (RP._f(r.get("attempts")) or 0), (RP._f(r.get("rushing_yards")) or 0) + (RP._f(r.get("receiving_yards")) or 0)
        tot[r["team"]][0] += att
        tot[r["team"]][1] += max(yds, 0)
        x = gio[r["player_id"]]
        x[0] += att
        x[1] += max(yds, 0)
        x[2], x[3] = r.get("position") or "", r["team"]
    out, per_nome = {}, {}
    nomi = {r["player_id"]: r.get("player_display_name") or "" for r in righe}
    for pid, (att, yds, pos, team) in gio.items():
        t = tot[team]
        q = (att / t[0]) if pos == "QB" and t[0] else (yds / t[1] if t[1] else 0.0)
        out[pid] = (round(q, 3), pos)
        per_nome[(team, C.norm(nomi.get(pid, "")))] = round(q, 3)
    out["__per_nome__"] = per_nome
    return out


def arricchisci(campionato: str, lega: str, schede: list, forza: dict, stagione: int, settimana: int) -> None:
    """Aggiunge forza delle squadre, assenze e meteo alle schede e rifà il giudizio. Ogni pezzo può mancare."""
    for sc in schede:
        sc["forzaCasa"], sc["forzaOspite"] = forza.get(sc["casa"]), forza.get(sc["ospite"])
    aggiorna_contesto(campionato, lega, schede, stagione, settimana)


def aggiorna_contesto(campionato: str, lega: str, schede: list, stagione: int, settimana: int) -> None:
    """Assenze e meteo: si rifanno anche da soli (scripts/aggiorna_contesto.py) senza ricalcolare tutta la sezione."""
    ora = datetime.now(timezone.utc)
    # gentilezza verso le fonti: ogni ora solo le partite delle prossime 48 ore, ogni 6 ore tutta la settimana
    finestra = timedelta(days=8) if ora.hour % 6 == 0 or os.environ.get("CONTESTO_TUTTO") else timedelta(hours=48)
    vicine = [sc for sc in schede if sc.get("inizioUtc")
              and timedelta(hours=-4) < datetime.fromisoformat(sc["inizioUtc"]) - ora < finestra]
    squadre = {x for sc in vicine for x in (sc["casa"], sc["ospite"])}
    if lega == "college":
        inf = C.infortuni_college(squadre)
        stadi = C.stadi_college(os.environ.get("CFBD_API_KEY", "").strip(), stagione)
    else:
        # il rapporto infortuni NFL è per settimana: ogni partita prende quello della sua settimana
        per_sett, quote = {}, {}
        try:
            quote = quote_produzione_nfl(stagione)
        except Exception as e:     # noqa: BLE001
            print(f"NFL: produzione dei giocatori non letta ({e}): assenze senza peso")
        espn = None
        try:
            espn = C.infortuni_nfl_espn(quote.get("__per_nome__", {}))
            print(f"Infortuni NFL: rapporto ESPN corrente, {len(espn)} squadre")
        except Exception as e:     # noqa: BLE001
            print(f"Infortuni NFL: ESPN non letto ({e}): uso nflverse, che può essere in ritardo di una settimana")
        for w in {int(sc.get("settimana") or settimana) for sc in vicine}:
            per_sett[w] = espn if espn is not None else C.infortuni_nfl(stagione, w, quote)
        inf = {}
        stadi = C.STADI_NFL
    for sc in vicine:
        fonte = inf if lega == "college" else per_sett.get(int(sc.get("settimana") or settimana), {})
        sc["assenzeCasa"], sc["assenzeOspite"] = _assenze_brevi(fonte.get(sc["casa"])), _assenze_brevi(fonte.get(sc["ospite"]))
        s = stadi.get(sc["casa"])
        if s and s[2]:
            sc["meteo"] = {"coperto": True}
        elif s:
            sc["meteo"] = C.meteo(s[0], s[1], datetime.fromisoformat(sc["inizioUtc"]))
        sc["contestoAggiornato"] = ora.isoformat(timespec="minutes")
        sc["giudizio"] = giudizio(campionato, sc)
    n_ass = sum(1 for sc in vicine for k in ("assenzeCasa", "assenzeOspite") if sc.get(k))
    print(f"{campionato}: contesto aggiornato per {len(vicine)} partite (assenze per {n_ass} squadre, "
          f"meteo {sum(1 for sc in vicine if sc.get('meteo'))}).")


def main() -> int:
    lega = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    if lega not in LEGHE:
        print("Uso: python scripts/fetch_duelli.py nfl|college")
        return 1
    campionato = LEGHE[lega]
    uscita = RADICE / "docs" / f"duelli_{lega}.dat"
    password = os.environ.get("DUELLI_PASSWORD", "")
    if not password:
        print("DUELLI_PASSWORD non impostata nei secret: non scrivo nulla, perché il repository è pubblico "
              "e la sezione privata non deve finire in chiaro.")
        return 0
    if len(password) < 8:
        print("DUELLI_PASSWORD troppo corta (meno di 8 caratteri): non scrivo nulla. Usa una password più lunga.")
        return 1

    pubblico = leggi_json(RADICE / "docs" / f"data_{lega}.json")
    privato = leggi_json(RADICE / "data" / f"privato_{lega}.json")
    if not privato:
        print(f"Manca il file privato del campionato (lo scrive fetch_{lega}.py): lascio com'è la sezione pubblicata.")
        return 1
    prossima, giornata = privato.get("prossima") or {}, pubblico.get("giornata") or {}
    gruppi = []   # partite senza risultato: resto della giornata in corso, poi il turno successivo
    for blocco, giocatori in ((giornata, privato.get("duelliGiornata")), (prossima, prossima.get("duelli"))):
        resto = [p for p in blocco.get("partite") or [] if p.get("pc") is None]
        if resto and blocco.get("settimana") is not None:
            per_partita = {(d["casa"], d["ospite"]): d for d in giocatori or []}
            gruppi.append((int(blocco["settimana"]), resto, per_partita))
    stagione = prossima.get("stagione") or giornata.get("stagione")
    if not gruppi or not stagione:
        print(f"{campionato}: nessuna partita da giocare, la sezione resta com'è.")
        return 0

    with tempfile.TemporaryDirectory() as cartella:
        try:
            azioni, punti = azioni_stagione(lega, int(stagione), cartella)
            agg = RP.aggrega(azioni)
        except Exception as e:     # noqa: BLE001 - fonte giù: si tiene la versione pubblicata
            print(f"{campionato}: play-by-play {stagione} non scaricato ({e}): lascio com'è la sezione pubblicata.")
            return 1
    loghi, indici = pubblico.get("loghi") or {}, privato.get("indici") or {}
    schede, saltate = [], []
    for w, resto, per_partita in gruppi:
        st = RP.stato(agg, w)
        norma = norma_punti(punti, w)
        for g in resto:
            sc = scheda(campionato, g, per_partita.get((g["casa"], g["ospite"])), st, loghi, indici, norma)
            if sc:
                sc["settimana"] = w
                schede.append(sc)
            else:
                saltate.append(f"{g.get('ospite')} @ {g.get('casa')}")
    os.environ["CONTESTO_TUTTO"] = "1"          # il calcolo completo prende tutta la settimana
    try:
        arricchisci(campionato, lega, schede, C.forza_squadre(azioni), int(stagione),
                    max(w for w, _r, _p in gruppi))
    except Exception as e:     # noqa: BLE001 - il contesto non deve mai fermare la sezione
        print(f"{campionato}: contesto (assenze, meteo, forza) non calcolato ({e}): schede senza contesto.")
    if saltate:
        print(f"{campionato}: {len(saltate)} partite senza dati di reparto (meno di {RP.MIN_PARTITE} partite giocate "
              f"o squadra fuori FBS), es. {', '.join(saltate[:5])}")
    if not schede:
        print(f"{campionato}: nessuna scheda calcolata: lascio com'è il file pubblicato.")
        return 1
    schede.sort(key=lambda g: (g["data"], g["ora"] or "99", g["ospite"]))
    contenuto = {"aggiornato": datetime.now(timezone.utc).isoformat(timespec="seconds"), "versione": VERSIONE,
                 "campionato": campionato,
                 "fonti": "nflverse (CC-BY-SA 4.0)" if lega == "nfl" else "cfbfastR / sportsdataverse",
                 "partite": schede, "indici": indici or None, "giovani": prossima.get("giovani"), "loghi": loghi}
    testo = json.dumps(contenuto, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pacchetto = cifra(testo, password)
    if decifra(pacchetto, password) != testo:
        print("Verifica della cifratura fallita: non scrivo il file.")
        return 1
    tmp = uscita.with_suffix(".tmp")
    tmp.write_text(json.dumps(pacchetto, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, uscita)          # mai un file a metà
    n_v = sum(len(g["vantaggi"]) for g in schede)
    print(f"{campionato}: scritto {uscita.name}, {len(schede)} partite, {n_v} vantaggi, {len(testo)} byte cifrati.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
