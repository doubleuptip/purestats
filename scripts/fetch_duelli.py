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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reparti as RP  # noqa: E402

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
    with apri() as fh:
        righe = csv.DictReader(fh)
        azioni = list(RP.azioni_nflverse(righe) if lega == "nfl" else RP.azioni_cfbfastr(righe))
    percorso.unlink()
    print(f"{LEGHE[lega]}: {len(azioni)} azioni di corsa e passaggio.")
    return azioni


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


def scheda(campionato: str, g: dict, extra: dict | None, st: dict, loghi: dict, indici: dict) -> dict | None:
    casa, ospite = g.get("casa"), g.get("ospite")
    if casa not in st or ospite not in st:
        return None
    data, ora = orario_roma(g.get("data") or "", g.get("ora") or "")
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
                                 "areaDifesa": p["areaDifesa"], "rangoDifesa": p["rangoDifesa"], "n": p["squadreTotali"]})
    for r in rep:
        if r["verso"]:
            # ordine tra i reparti: prima le difese più agli estremi (non entra nei 3 migliori)
            vantaggi.append({"tipo": "reparto", **r, "forza": round(abs((r["rd"] - 1) / max(r["n"] - 1, 1) - 0.5) / 100, 5)})
    vantaggi.sort(key=lambda v: (v["tipo"] != "giocatore", -v["forza"]))
    return {"campionato": campionato, "data": data, "ora": ora, "casa": casa, "ospite": ospite,
            "nomeCasa": lc.get("breve") or casa, "nomeOspite": lo.get("breve") or ospite,
            "logoCasa": lc.get("logo") or "", "logoOspite": lo.get("logo") or "",
            "coloreCasa": lc.get("colore") or "", "coloreOspite": lo.get("colore") or "",
            "conferenceCasa": g.get("confCasa"), "conferenceOspite": g.get("confOspite"),
            "indiceCasa": indice_squadra(indici, casa), "indiceOspite": indice_squadra(indici, ospite),
            "giocatoriCasa": gc, "giocatoriOspite": go, "partita": partita,
            "vantaggi": vantaggi, "reparti": rep}


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
            agg = RP.aggrega(azioni_stagione(lega, int(stagione), cartella))
        except Exception as e:     # noqa: BLE001 - fonte giù: si tiene la versione pubblicata
            print(f"{campionato}: play-by-play {stagione} non scaricato ({e}): lascio com'è la sezione pubblicata.")
            return 1
    loghi, indici = pubblico.get("loghi") or {}, privato.get("indici") or {}
    schede, saltate = [], []
    for w, resto, per_partita in gruppi:
        st = RP.stato(agg, w)
        for g in resto:
            sc = scheda(campionato, g, per_partita.get((g["casa"], g["ospite"])), st, loghi, indici)
            if sc:
                schede.append(sc)
            else:
                saltate.append(f"{g.get('ospite')} @ {g.get('casa')}")
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
