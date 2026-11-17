"""
Sentinella (17/11/2026): fa partire l'aggiornamento NFL o College appena una partita è finita e i dati sono pronti,
invece di aspettare un orario fisso. Gira ogni 15 minuti nelle finestre di gioco (.github/workflows/sentinella.yml);
gli orari fissi dei workflow restano come riserva.

Per ogni campionato:
1. ESPN (gratis, una richiesta): partite finite ieri e oggi (ora USA).
2. Una partita finita è «da aggiornare» se nella Giornata pubblicata (docs/data_<lega>.json) non c'è ancora il suo
   punteggio. Si guardano solo le partite finite nelle ultime 18 ore.
3. NFL: la Giornata usa nflverse, quindi si aspetta che il play-by-play (rilascio GitHub) e il calendario con i
   punteggi siano stati aggiornati dopo la fine della partita. College: i dati vengono da ESPN, pronti subito.
4. Se serve, lancia il workflow, ma mai se ce n'è già uno in coda o in corso, né se ne è partito uno dopo che i dati
   erano pronti da meno di PAUSA minuti (così una partita che la fonte non ha ancora non fa girare tutto a vuoto).

Solo libreria standard. Scrive sul registro cosa ha visto e perché lancia o non lancia.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
REPO = os.environ.get("GITHUB_REPOSITORY", "doubleuptip/purestats")
TOKEN = os.environ.get("GH_TOKEN", "")
ADESSO = datetime.now(timezone.utc)
DURATA = timedelta(hours=3, minutes=15)          # una partita dura circa 3 ore: fine stimata = inizio + 3h15
FINESTRA = timedelta(hours=18)
ESPN_NFL_CORTE = {"LA": "LAR", "WAS": "WSH"}      # sigle nflverse → ESPN dove sono diverse

LEGHE = {
    "nfl": {"espn": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={d}",
            "workflow": "update-nfl.yml", "pausa": 30},
    "college": {"espn": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
                        "?groups=80&dates={d}&limit=300",
                "workflow": "update-college.yml", "pausa": 60},
}


def leggi(url: str, github: bool = False):
    intest = {"User-Agent": "purestats (statistiche personali)"}
    if github:
        intest["Accept"] = "application/vnd.github+json"
        if TOKEN:
            intest["Authorization"] = f"Bearer {TOKEN}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=intest), timeout=30) as r:
        return json.load(r)


def ora(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def finite_espn(lega: str) -> list[dict]:
    """Partite finite ieri e oggi (date USA) con inizio e squadre (sigla per l'NFL, nome per il college)."""
    giorni = sorted({(ADESSO - timedelta(hours=h)).strftime("%Y%m%d") for h in (5, 29)})
    eventi = []
    for g in giorni:                                  # un giorno per richiesta (data USA della partita)
        url = LEGHE[lega]["espn"].format(d=g)
        try:
            eventi += leggi(url).get("events") or []
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"ESPN ha risposto {e.code} a {url}") from e
    out = []
    for ev in eventi:
        comp = (ev.get("competitions") or [{}])[0]
        if not ((comp.get("status") or ev.get("status") or {}).get("type") or {}).get("completed"):
            continue
        sq = {}
        for c in comp.get("competitors") or []:
            t = c.get("team") or {}
            sq[c.get("homeAway")] = (t.get("abbreviation") if lega == "nfl" else t.get("location")) or ""
        if sq.get("home") and sq.get("away") and ev.get("date"):
            out.append({"casa": sq["home"], "ospite": sq["away"], "inizio": ora(ev["date"]), "nome": ev.get("shortName", "")})
    return [p for p in out if ADESSO - (p["inizio"] + DURATA) <= FINESTRA]


def punteggi_pubblicati(lega: str) -> set[tuple[str, str]]:
    try:
        d = json.loads((RADICE / "docs" / f"data_{lega}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"{lega}: dati pubblicati non leggibili ({e}): considero tutte le partite da aggiornare.")
        return set()
    fatte = set()
    for p in (d.get("giornata") or {}).get("partite") or []:
        if p.get("pc") is None or p.get("po") is None:
            continue
        casa, osp = p.get("casa", ""), p.get("ospite", "")
        if lega == "nfl":
            casa, osp = ESPN_NFL_CORTE.get(casa, casa), ESPN_NFL_CORTE.get(osp, osp)
        fatte.add((casa, osp))
    return fatte


def nflverse_pronto() -> datetime | None:
    """Ultimo aggiornamento comune di play-by-play e calendario nflverse (il più vecchio dei due)."""
    stagione = ADESSO.year if ADESSO.month >= 3 else ADESSO.year - 1
    rel = leggi("https://api.github.com/repos/nflverse/nflverse-data/releases/tags/pbp", github=True)
    pbp = None
    pagina, assets = 1, rel.get("assets") or []
    while True:
        for a in assets:
            if a.get("name", "").startswith(f"play_by_play_{stagione}."):
                t = ora(a["updated_at"])
                pbp = t if pbp is None or t > pbp else pbp
        if len(assets) < 100:
            break
        pagina += 1
        assets = leggi(f"https://api.github.com/repos/nflverse/nflverse-data/releases/{rel['id']}/assets"
                       f"?per_page=100&page={pagina}", github=True)
    com = leggi("https://api.github.com/repos/nflverse/nfldata/commits?path=data/games.csv&per_page=1", github=True)
    cal = ora(com[0]["commit"]["committer"]["date"]) if com else None
    if pbp is None or cal is None:
        print(f"NFL: aggiornamenti nflverse non trovati (play-by-play {pbp}, calendario {cal}).")
        return None
    print(f"NFL: nflverse aggiornato · play-by-play {pbp:%d/%m %H:%M} UTC · calendario {cal:%d/%m %H:%M} UTC.")
    return min(pbp, cal)


def corse(workflow: str) -> list[dict]:
    return leggi(f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/runs?per_page=5", github=True)\
        .get("workflow_runs") or []


def lancia(workflow: str) -> None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/dispatches",
        data=json.dumps({"ref": "main"}).encode(), method="POST",
        headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {TOKEN}",
                 "User-Agent": "purestats-sentinella"})
    with urllib.request.urlopen(req, timeout=30):
        pass


def controlla(lega: str) -> None:
    cfg = LEGHE[lega]
    finite = finite_espn(lega)
    fatte = punteggi_pubblicati(lega)
    mancanti = [p for p in finite if (p["casa"], p["ospite"]) not in fatte]
    print(f"{lega}: {len(finite)} partite finite nelle ultime 18 ore, {len(mancanti)} senza punteggio sul sito"
          + (": " + ", ".join(p["nome"] for p in mancanti[:8]) if mancanti else "."))
    if not mancanti:
        return
    fine = min(p["inizio"] + DURATA for p in mancanti)
    pronti = fine
    if lega == "nfl":
        agg = nflverse_pronto()
        if agg is None or agg < fine:
            print(f"NFL: nflverse non ha ancora i dati della partita finita verso le {fine:%H:%M} UTC: aspetto.")
            return
        pronti = agg
    for c in corse(cfg["workflow"]):
        if c.get("status") in ("queued", "in_progress", "waiting", "requested", "pending"):
            print(f"{lega}: un aggiornamento è già in corso ({c.get('event')}): non ne lancio un altro.")
            return
        partito = ora(c["created_at"])
        if partito >= pronti and ADESSO - partito < timedelta(minutes=cfg["pausa"]):
            print(f"{lega}: aggiornamento già partito alle {partito:%H:%M} UTC con i dati pronti; "
                  f"riprovo tra {cfg['pausa']} minuti se manca ancora qualcosa.")
            return
    if not TOKEN:
        print(f"{lega}: servirebbe un aggiornamento, ma manca il token per lanciarlo.")
        return
    lancia(cfg["workflow"])
    print(f"{lega}: LANCIATO l'aggiornamento ({cfg['workflow']}).")


def main() -> int:
    if os.environ.get("PROVA") == "true":            # prova a mano: legge nflverse e la coda, non lancia niente
        print("PROVA:", nflverse_pronto(), [(c.get("status"), c.get("created_at")) for c in corse("update-nfl.yml")[:2]])
        return 0
    errori = 0
    for lega in LEGHE:
        try:
            controlla(lega)
        except Exception as e:                     # noqa: BLE001 - un campionato non ferma l'altro
            errori += 1
            print(f"{lega}: controllo non riuscito ({type(e).__name__}: {e}); riprovo al prossimo giro.")
    return 1 if errori == len(LEGHE) else 0


if __name__ == "__main__":
    sys.exit(main())
