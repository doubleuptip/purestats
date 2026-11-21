"""
NFL in TV in Italia: quali partite della settimana sono incluse negli abbonamenti DAZN (Sports, Full, Family).

Tutte le partite si vedono con NFL Game Pass (su DAZN): questo non cambia e lo scrive la pagina. In più gli abbonamenti
DAZN includono cinque partite a settimana: Thursday Night, una delle 19:00, una delle 22:05/22:25, Sunday Night e
Monday Night (conferma di Valerio, abbonato, 21/11/2026).

Da dove si sa quali:
  · le partite in prima serata americana (via tra l'01:00 e le 04:30 italiane: Thursday, Sunday e Monday Night) sono
    incluse per regola, senza bisogno di leggere niente («regola»);
  · le due della domenica pomeriggio le annuncia DAZN Italia ogni settimana nelle sue notizie NFL, nell'articolo
    «... le cinque partite da non perdere della Week N in ogni fascia oraria» («articolo»); se manca, valgono le
    anteprime della singola partita «... diretta su DAZN» («anteprima»).
Pagine lette: l'elenco delle notizie NFL Game Pass di DAZN Italia (robots.txt permette /it-IT/news) e gli articoli
che servono, una volta sola ciascuno (gli indirizzi già letti restano nel file). Gratis, senza chiave.

Scrive docs/tv_italia.json: {"aggiornato", "fonte", "settimane": {"2026|11": {"incluse": {"IND@HOU": "regola", ...},
"articolo": url | null, "titolo": ..., "controllato": ...}}, "letti": [url, ...]}
Se DAZN non risponde o la pagina cambia forma, il file resta com'era (le partite in prima serata si segnano comunque).
Solo libreria standard.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

RADICE = Path(__file__).resolve().parent.parent
USCITA = RADICE / "docs" / "tv_italia.json"
DATI = RADICE / "docs" / "data_nfl.json"
BASE = "https://www.dazn.com"
ELENCO = BASE + "/it-IT/news/competition/nfl-game-pass/wy3kluvb4efae1of0d8146c1"
PAGINE_ELENCO = 3                      # le notizie di circa una settimana e mezza
UA = "Mozilla/5.0 (compatible; PureStats/1.0; statistiche personali, https://doubleuptip.github.io/purestats/)"
NOTTE = ("00:30", "04:30")             # ora italiana del via delle partite in prima serata americana
MAX_LETTI = 300


def scarica(url: str) -> str | None:
    try:
        with urlopen(Request(url, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"}), timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:                                   # noqa: BLE001
        print(f"DAZN: {url} non scaricata ({e}).")
        return None


def testo_righe(pagina: str) -> list[str]:
    corpo = re.sub(r"<script.*?</script>|<style.*?</style>", "", pagina, flags=re.S)
    return [r.strip() for r in html.unescape(re.sub(r"<[^>]+>", "\n", corpo)).split("\n") if r.strip()]


def nomi_squadre(loghi: dict) -> dict:
    """{parola minuscola: sigla}: il soprannome («Texans», «49ers») di ogni squadra."""
    out = {}
    for sigla, l in loghi.items():
        b = (l.get("breve") or "").strip().lower()
        if b and len(sigla) <= 3:
            out[b] = sigla
    return out


def squadre_in(testo: str, nomi: dict) -> list[str]:
    t = " " + re.sub(r"[^a-z0-9]+", " ", testo.lower()) + " "
    trovate = [(t.index(f" {n} "), s) for n, s in nomi.items() if f" {n} " in t]
    return [s for _, s in sorted(trovate)]


def partite_settimana(dati: dict) -> tuple[str, int, list[dict]]:
    """Stagione e settimana in corso (la prima con partite ancora da giocare) e le sue partite."""
    tutte = [p for p in dati["ultimePartite"] if p.get("tipo", "REG") in ("REG", "WC", "DIV", "CON", "SB")]
    stagione = max(p["stagione"] for p in tutte)
    st = [p for p in tutte if p["stagione"] == stagione]
    da_giocare = [p for p in st if p.get("pc") is None]
    if not da_giocare:
        return stagione, 0, []
    w = min(int(p["settimana"]) for p in da_giocare)
    return stagione, w, [p for p in st if int(p["settimana"]) == w]


def chiave(p: dict) -> str:
    return f"{p['ospite']}@{p['casa']}"


def in_notte(p: dict) -> bool:
    o = p.get("oraIt") or ""
    return bool(o) and NOTTE[0] <= o <= NOTTE[1]


def domenica_pomeriggio(p: dict) -> bool:
    try:
        giorno = dt.date.fromisoformat(p["dataIt"]).weekday()
    except (KeyError, ValueError):
        return False
    return giorno == 6 and (p.get("oraIt") or "") >= "18:00"


def da_articolo(pagina: str, partite: list[dict], nomi: dict) -> tuple[str, list[str]]:
    """Titolo e partite citate come «X vs. Y» nei titoletti seguiti da «Kick-off Italia»."""
    righe = testo_righe(pagina)
    titolo = next((r for r in righe if "da non perdere" in r.lower()), "").split(" | ")[0]
    coppie = {frozenset((p["casa"], p["ospite"])): chiave(p) for p in partite}
    trovate = []
    for i, r in enumerate(righe):
        if not r.lower().startswith("kick-off italia"):
            continue
        for j in range(i - 1, max(-1, i - 4), -1):           # il titoletto è subito sopra
            s = squadre_in(righe[j], nomi)
            k = coppie.get(frozenset(s[:2])) if len(s) >= 2 else None
            if k:
                trovate.append(k)
                break
    return titolo, list(dict.fromkeys(trovate))


def collegamenti(pagina: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r'href="(/it-IT/news/football-americano/[^"?#]+)"', pagina)))


def aggiorna() -> int:
    if not DATI.exists():
        print("TV Italia: manca docs/data_nfl.json, niente da fare.")
        return 0
    dati = json.loads(DATI.read_text(encoding="utf-8"))
    vecchio = {}
    if USCITA.exists():
        try:
            vecchio = json.loads(USCITA.read_text(encoding="utf-8"))
        except ValueError:
            print("TV Italia: docs/tv_italia.json illeggibile, lo riscrivo da capo.")
    settimane = vecchio.get("settimane", {})
    letti = list(vecchio.get("letti", []))
    stagione, w, partite = partite_settimana(dati)
    if not partite:
        print("TV Italia: nessuna partita NFL da giocare, niente da fare.")
        return 0
    nomi = nomi_squadre(dati.get("loghi", {}))
    sk = f"{stagione}|{w}"
    voce = settimane.get(sk, {"incluse": {}, "articolo": None, "titolo": None})
    validi = {chiave(p) for p in partite}
    voce["incluse"] = {k: v for k, v in voce.get("incluse", {}).items() if k in validi}
    for p in partite:                                        # prima serata americana: incluse per regola
        if in_notte(p):
            voce["incluse"].setdefault(chiave(p), "regola")

    if not voce.get("articolo"):
        nuovi = []
        for n in range(1, PAGINE_ELENCO + 1):
            pagina = scarica(ELENCO if n == 1 else f"{ELENCO}/{n}")
            if pagina is None:
                break
            nuovi += [u for u in collegamenti(pagina) if u not in letti and u not in nuovi]
            if n == 1 and not collegamenti(pagina):
                print("TV Italia: l'elenco delle notizie DAZN non ha collegamenti riconoscibili: la pagina è cambiata?")
                break
            time.sleep(1)
        # 1) l'articolo delle cinque partite
        for u in [u for u in nuovi if "da-non-perdere" in u]:
            pagina = scarica(BASE + u)
            if pagina is None:
                continue
            letti.append(u)
            titolo, trovate = da_articolo(pagina, partite, nomi)
            if len(trovate) >= 3:                            # è l'articolo di questa settimana
                voce["articolo"], voce["titolo"] = BASE + u, titolo
                voce["incluse"] = {k: v for k, v in voce["incluse"].items() if v == "regola"}
                for k in trovate:
                    voce["incluse"][k] = "articolo"
                print(f"TV Italia: week {w}, articolo DAZN trovato ({len(trovate)} partite): {', '.join(trovate)}.")
                break
            print(f"TV Italia: {u} non riguarda la week {w} ({len(trovate)} partite riconosciute), scartato.")
            time.sleep(1)
        # 2) se manca, le anteprime della singola partita della domenica pomeriggio
        if not voce.get("articolo"):
            pomeriggio = {frozenset((p["casa"], p["ospite"])): chiave(p) for p in partite if domenica_pomeriggio(p)}
            for u in nuovi:
                if "diretta" not in u and "come-vedere" not in u:
                    continue
                s = squadre_in(u.rsplit("/", 1)[0].replace("-", " "), nomi)
                k = pomeriggio.get(frozenset(s[:2])) if len(s) >= 2 else None
                if k and k not in voce["incluse"]:
                    voce["incluse"][k] = "anteprima"
                    print(f"TV Italia: week {w}, {k} dall'anteprima DAZN {BASE + u}.")
                letti.append(u)
    voce["controllato"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    settimane[sk] = voce
    # si tengono solo le ultime 6 settimane
    for k in sorted(settimane, key=lambda x: (x.split("|")[0], int(x.split("|")[1])))[:-6]:
        settimane.pop(k)
    out = {"aggiornato": voce["controllato"],
           "fonte": "DAZN Italia, notizie NFL (dazn.com/it-IT/news); tutte le partite con NFL Game Pass",
           "settimane": settimane, "letti": letti[-MAX_LETTI:]}
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    tmp = USCITA.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(USCITA)
    stati = {}
    for v in voce["incluse"].values():
        stati[v] = stati.get(v, 0) + 1
    print(f"TV Italia: week {w}, partite incluse in DAZN {len(voce['incluse'])} ({stati}); "
          f"articolo {'trovato' if voce.get('articolo') else 'non ancora uscito'}.")
    return 0


if __name__ == "__main__":
    sys.exit(aggiorna())
