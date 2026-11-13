"""Duelli attacco contro difesa per la pagina privata docs/duelli.html.

Per ogni partita in programma (NFL e college) confronta, area per area, l'attacco di una squadra con la
difesa dell'altra: corse, passaggi, protezione del QB, giocate lunghe, zona rossa. Solo statistiche:
nessuna quota, nessuna indicazione di gioco.

I calcoli sono quelli del bot Radar Assenze (scripts/motore_duelli è una copia esatta dei suoi moduli),
così posizioni e punteggi coincidono con i messaggi Telegram.

Uso: python scripts/fetch_duelli.py nfl|college, subito dopo fetch_nfl.py / fetch_college.py nello
stesso workflow: legge il file locale data/privato_<lega>.json (prossimo turno, indici, giocatori chiave,
mai committato) e lo unisce ai duelli di reparto e ai segnali sui giocatori.

Il risultato viene CIFRATO con la password nel secret DUELLI_PASSWORD e scritto in docs/duelli_<lega>.dat.
Il repository è pubblico: i dati in chiaro non vengono mai scritti su disco né stampati nei log.
Senza password lo script si ferma senza toccare nulla.

Cifratura (verificabile, solo libreria standard):
  chiave = PBKDF2-HMAC-SHA256(password, sale casuale, ITERAZIONI) -> 64 byte: 32 cifratura + 32 controllo
  flusso = SHA-256(chiave_cifratura || nonce || contatore a 4 byte), blocco dopo blocco, in XOR coi dati
  controllo = HMAC-SHA256(chiave_controllo, nonce || dati cifrati): una password sbagliata viene riconosciuta
La pagina rifà gli stessi passaggi nel browser con WebCrypto.

Fonti: nflverse (CC-BY-SA 4.0) per l'NFL, CollegeFootballData (secret CFBD_API_KEY) per il college:
2 chiamate al massimo ogni 20 ore, il resto dei giri riusa data/duelli_cfbd.json.
Partite e loghi vengono da docs/data_<lega>.json, appena scritto dallo script del campionato.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from motore_duelli import factors as F          # noqa: E402
from motore_duelli import nfl_data as nd        # noqa: E402
from motore_duelli import ratings as R          # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
LEGHE = {"nfl": "NFL", "college": "College"}
ITERAZIONI = 200_000
CFBD = "https://api.collegefootballdata.com"
VERSIONE = 1
CACHE_CFBD = RADICE / "data" / "duelli_cfbd.json"
CACHE_ORE = 20


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


# ------------------------------------------------------------------ NFL
def statistiche_nfl(stagione: int, settimane: list[int]) -> dict[int, dict]:
    """Stesso calcolo del bot: pressione, esplosive e zona rossa dalla stagione in corso corrette per gli
    avversari; corse e passaggi dalla forza di squadra (ratings) usata dalla scheda /fb, calcolata alla
    settimana di ogni partita (solo le gare giocate prima). Restituisce {settimana: statistiche}."""
    riassunti = []
    pbp_corrente = None
    with tempfile.TemporaryDirectory() as cartella:
        for s in range(stagione - 2, stagione + 1):
            print(f"NFL: scarico il play-by-play {s} da nflverse...")
            try:
                grezzo = nd.download(nd.URL_PBP.format(s=s))
            except Exception as e:     # noqa: BLE001
                if s == stagione:
                    raise RuntimeError(f"play-by-play {s} non scaricato ({e}): senza la stagione in corso "
                                       "i duelli NFL non si possono calcolare") from e
                print(f"  stagione {s} non scaricata ({e}): la forza di squadra userà le altre")
                continue
            # Passaggio dal riassunto salvato e riletto, come fa il bot: stessi arrotondamenti, stessi numeri.
            percorso = Path(cartella) / f"tg_{s}.csv"
            nd.save_summary(nd.summarize_pbp(nd.iter_csv_gz(grezzo)), percorso)
            riassunti += nd.load_summary(percorso)
            if s == stagione:
                pbp_corrente = grezzo
    base, avversari = F.nfl_team_stats(nd.iter_csv_gz(pbp_corrente))
    base = F.adjust(base, avversari)
    out = {}
    for settimana in settimane:
        st = {k: dict(v) for k, v in base.items()}
        for squadra, r in R.build(riassunti, stagione, settimana).items():
            v = st.setdefault(squadra, {a: (None, None) for a in F.AREE} | {"_ritmo": None, "_partite": None})
            v["corse"] = (r.off_rush, -r.def_rush)
            v["passaggi"] = (r.off_pass, -r.def_pass)
        out[settimana] = st
    print(f"NFL: statistiche pronte per {len(base)} squadre (forza di squadra alle settimane {settimane}).")
    return out


# ------------------------------------------------------------------ college
def chiama_cfbd(percorso: str, chiave: str, **parametri):
    url = f"{CFBD}/{percorso}?{urllib.parse.urlencode(parametri)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {chiave}", "Accept": "application/json",
                                               "User-Agent": "purestats (statistiche personali)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def leggi_cache_cfbd(stagione: int):
    """Statistiche di stagione CFBD salvate dall'ultimo giro (sono statistiche pubbliche, non segnali).
    Valide se della stessa stagione e scaricate da meno di CACHE_ORE: i duelli girano dopo ogni
    aggiornamento NFL e college, ma SP+ cambia una volta a settimana e il budget CFBD è condiviso."""
    try:
        c = json.loads(CACHE_CFBD.read_text(encoding="utf-8"))
        eta = datetime.now(timezone.utc) - datetime.fromisoformat(c["scaricato"])
        if c.get("stagione") == stagione and eta.total_seconds() < CACHE_ORE * 3600:
            return c["sp"], c["adv"], eta
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def statistiche_college(stagione: int) -> dict:
    cache = leggi_cache_cfbd(stagione)
    if cache:
        sp, adv, eta = cache
        print(f"College: statistiche CFBD riusate (scaricate {int(eta.total_seconds() // 3600)} ore fa), 0 chiamate.")
    else:
        chiave = os.environ.get("CFBD_API_KEY", "").strip()
        if not chiave:
            print("College: secret CFBD_API_KEY non impostato, i duelli college restano vuoti in questo giro.")
            return {}
        try:
            sp = chiama_cfbd("ratings/sp", chiave, year=stagione)
            adv = chiama_cfbd("stats/season/advanced", chiave, year=stagione, excludeGarbageTime="true")
        except Exception as e:         # noqa: BLE001
            print(f"College: CollegeFootballData non ha risposto ({e}), i duelli college restano vuoti in questo giro.")
            return {}
        tmp = CACHE_CFBD.with_suffix(".tmp")
        tmp.write_text(json.dumps({"scaricato": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                   "stagione": stagione, "sp": sp, "adv": adv}, separators=(",", ":")),
                       encoding="utf-8")
        os.replace(tmp, CACHE_CFBD)
        print("College: statistiche CFBD scaricate (2 chiamate), riusate nei giri delle prossime ore.")
    st = F.college_team_stats(sp, adv)
    print(f"College: statistiche pronte per {len(st)} squadre.")
    return st


# ------------------------------------------------------------------ duelli
def duelli_partita(rk: dict, casa: str, ospite: str) -> list[dict]:
    """Tutte le aree nei due versi, anche quelle in equilibrio; la pagina decide come mostrarle."""
    out = []
    for area in F.AREE:
        r = rk.get(area) or {}
        for att, dif in ((casa, ospite), (ospite, casa)):
            if att not in r or dif not in r:
                continue
            ra, _, n = r[att]
            _, rd, _ = r[dif]
            s = F.score(ra, rd, n)
            if s is None:
                continue
            out.append({"area": area, "att": att, "dif": dif, "ra": ra, "rd": rd, "n": n, "punteggio": round(s, 3)})
    return out


# ------------------------------------------------------------------ segnali sui giocatori
# Giocatore in forma contro una difesa tra le peggiori del suo reparto -> segnale per l'attacco;
# giocatore in calo contro una difesa tra le migliori -> segnale per la difesa.
# Soglie concordate: su 32 squadre "migliori" fino alla 10ª, "peggiori" dalla 22ª; stesse proporzioni nel college.
REPARTO = {"QB": "passaggi", "WR": "passaggi", "TE": "passaggi", "RIC": "passaggi", "RB": "corse"}
NETTO = 0.40


def soglie(n: int) -> tuple[int, int]:
    return round(n * 10 / 32), n - round(n * 11 / 32) + 1


def giocatori_contro(giocatori: list, avversario: str, rk: dict) -> list[dict]:
    """Ogni giocatore chiave con la posizione della difesa avversaria nel suo reparto e l'eventuale segnale."""
    out = []
    for p in giocatori or []:
        q = dict(p)
        area = REPARTO.get(str(p.get("ruolo", "")).upper())
        r = (rk.get(area) or {}).get(avversario) if area else None
        q["segnale"] = None
        if r:
            _, rd, n = r
            migliori, peggiori = soglie(n)
            q.update({"areaDifesa": area, "rangoDifesa": rd, "squadreTotali": n})
            if p.get("forma") == "in forma" and rd >= peggiori:
                q["segnale"] = "attacco"
            elif p.get("forma") == "in calo" and rd <= migliori:
                q["segnale"] = "difesa"
        out.append(q)
    return out


def indice_squadra(indici: dict, squadra: str):
    for x in (indici or {}).get("squadre") or []:
        if x.get("squadra") == squadra:
            return {"posizione": x.get("posizione"), "netto": x.get("netto"),
                    "attacco": x.get("attacco"), "difesa": x.get("difesa")}
    return None


def scheda(campionato: str, g: dict, extra: dict | None, rk: dict, loghi: dict, indici: dict) -> dict | None:
    casa, ospite = g.get("casa"), g.get("ospite")
    duelli = duelli_partita(rk, casa, ospite)
    if not duelli:
        return None
    data, ora = orario_roma(g.get("data") or "", g.get("ora") or "")
    lc, lo = loghi.get(casa) or {}, loghi.get(ospite) or {}
    extra = extra or {}
    gc = giocatori_contro(extra.get("giocatoriCasa"), ospite, rk)
    go = giocatori_contro(extra.get("giocatoriOspite"), casa, rk)
    segnali = []
    for squadra, gruppo in ((casa, gc), (ospite, go)):
        for p in gruppo:
            if p["segnale"]:
                segnali.append({"tipo": "giocatore", "verso": p["segnale"], "squadra": squadra, "nome": p.get("nome"),
                                "ruolo": p.get("ruolo"), "forma": p.get("forma"), "misura": p.get("misura"),
                                "ultime3": p.get("mediaUltime3"), "stagione": p.get("mediaStagione"),
                                "areaDifesa": p["areaDifesa"], "rangoDifesa": p["rangoDifesa"],
                                "difesa": ospite if squadra == casa else casa})
    for d in sorted(duelli, key=lambda d: -abs(d["punteggio"])):
        if abs(d["punteggio"]) >= NETTO:
            segnali.append({"tipo": "reparto", "verso": "attacco" if d["punteggio"] > 0 else "difesa", **d})
    return {"campionato": campionato, "data": data, "ora": ora, "casa": casa, "ospite": ospite,
            "nomeCasa": lc.get("breve") or casa, "nomeOspite": lo.get("breve") or ospite,
            "logoCasa": lc.get("logo") or "", "logoOspite": lo.get("logo") or "",
            "coloreCasa": lc.get("colore") or "", "coloreOspite": lo.get("colore") or "",
            "conferenceCasa": g.get("confCasa"), "conferenceOspite": g.get("confOspite"),
            "indiceCasa": indice_squadra(indici, casa), "indiceOspite": indice_squadra(indici, ospite),
            "giocatoriCasa": gc, "giocatoriOspite": go, "segnali": segnali, "duelli": duelli}


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
        print("Manca il file privato del campionato (lo scrive fetch_{0}.py): lascio com'è la sezione "
              "pubblicata.".format(lega))
        return 1
    prossima, giornata = privato.get("prossima") or {}, pubblico.get("giornata") or {}
    # partite senza risultato: resto della giornata in corso, poi il turno successivo
    gruppi = []
    for blocco, giocatori in ((giornata, privato.get("duelliGiornata")), (prossima, prossima.get("duelli"))):
        resto = [p for p in blocco.get("partite") or [] if p.get("pc") is None]
        if resto and blocco.get("settimana") is not None:
            per_partita = {(d["casa"], d["ospite"]): d for d in giocatori or []}
            gruppi.append((int(blocco["settimana"]), resto, per_partita))
    stagione = prossima.get("stagione") or giornata.get("stagione")
    if not gruppi or not stagione:
        print(f"{campionato}: nessuna partita da giocare, la sezione resta com'è.")
        return 0

    if lega == "nfl":
        st_sett = statistiche_nfl(int(stagione), sorted({w for w, _, _ in gruppi}))
    else:
        st = statistiche_college(int(stagione))
        st_sett = {w: st for w, _, _ in gruppi}
    loghi, indici = pubblico.get("loghi") or {}, privato.get("indici") or {}
    schede, saltate = [], 0
    for w, resto, per_partita in gruppi:
        st = st_sett.get(w) or {}
        rk = F.ranks(st) if st else {}
        for g in resto:
            sc = scheda(campionato, g, per_partita.get((g["casa"], g["ospite"])), rk, loghi, indici)
            if sc:
                schede.append(sc)
            else:
                saltate += 1
    if not schede:
        print(f"{campionato}: nessuna scheda calcolata ({saltate} partite senza dati): lascio com'è il file pubblicato.")
        return 1
    schede.sort(key=lambda g: (g["data"], g["ora"] or "99", g["ospite"]))
    contenuto = {"aggiornato": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "campionato": campionato,
                 "fonti": "nflverse (CC-BY-SA 4.0)" if lega == "nfl" else "CollegeFootballData",
                 "partite": schede, "indici": indici or None,
                 "giovani": prossima.get("giovani"), "loghi": loghi}
    testo = json.dumps(contenuto, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pacchetto = cifra(testo, password)
    if decifra(pacchetto, password) != testo:
        print("Verifica della cifratura fallita: non scrivo il file.")
        return 1
    tmp = uscita.with_suffix(".tmp")
    tmp.write_text(json.dumps(pacchetto, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, uscita)          # mai un file a metà
    n_segn = sum(len(g["segnali"]) for g in schede)
    print(f"{campionato}: scritto {uscita.name}, {len(schede)} partite ({saltate} saltate), {n_segn} segnali, "
          f"{len(testo)} byte cifrati.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
