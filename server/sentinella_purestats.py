"""Avvia la sentinella di PureStats dal server (dal 26/11/2026, scelta di Valerio).

GitHub ritarda o salta i propri orari automatici: la partita del mercoledì sera 25/11 è rimasta senza risultato
fino a mezzogiorno perché la sentinella non è mai partita. Questo script, lanciato dal crontab del server ogni
15 minuti, chiede a GitHub di avviare subito il workflow «sentinella.yml»: la richiesta diretta non viene mai
rimandata. La sentinella controlla le partite finite e lancia gli aggiornamenti solo se serve.

Configurazione in config.toml (sezione [github]):
    token = ""                       chiave GitHub con il solo permesso Actions: lettura e scrittura su purestats
    repo = "doubleuptip/purestats"
Uso:  cd <cartella del bot> && python3 strumenti/sentinella_purestats.py
Registro: data/sentinella_purestats.log (ultime 300 righe). Se la chiave è scaduta o sbagliata avvisa su Telegram
al massimo una volta al giorno.
"""
import json
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent.parent
REGISTRO = CARTELLA / "data" / "sentinella_purestats.log"
ULTIMO_AVVISO = CARTELLA / "data" / "sentinella_purestats_avviso.txt"
ADESSO = datetime.now(timezone.utc)


def scrivi(riga):
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    righe = REGISTRO.read_text(encoding="utf-8").splitlines()[-299:] if REGISTRO.exists() else []
    righe.append(f"{ADESSO:%Y-%m-%d %H:%M} UTC  {riga}")
    REGISTRO.write_text("\n".join(righe) + "\n", encoding="utf-8")


def avvisa_telegram(cfg, testo):
    """Un solo avviso ogni 24 ore, alla chat del titolare indicata in config.toml."""
    try:
        if ULTIMO_AVVISO.exists():
            prima = datetime.fromisoformat(ULTIMO_AVVISO.read_text().strip())
            if ADESSO - prima < timedelta(hours=24):
                return
        t = cfg.get("telegram", {})
        if not t.get("token") or not t.get("chat_id"):
            return
        dati = json.dumps({"chat_id": t["chat_id"], "text": testo}).encode()
        richiesta = urllib.request.Request(f"https://api.telegram.org/bot{t['token']}/sendMessage", data=dati,
                                           headers={"Content-Type": "application/json"})
        urllib.request.urlopen(richiesta, timeout=20).read()
        ULTIMO_AVVISO.write_text(ADESSO.isoformat())
    except Exception as e:                       # l'avviso è un di più: non deve mai far fallire lo script
        scrivi(f"avviso Telegram non inviato: {e}")


def main():
    cfg = tomllib.load(open(CARTELLA / "config.toml", "rb"))
    g = cfg.get("github", {})
    token, repo = (g.get("token") or "").strip(), (g.get("repo") or "doubleuptip/purestats").strip()
    if not token:
        scrivi("nessuna chiave in config.toml, sezione [github]: sentinella non avviata")
        return
    indirizzo = f"https://api.github.com/repos/{repo}/actions/workflows/sentinella.yml/dispatches"
    richiesta = urllib.request.Request(indirizzo, data=json.dumps({"ref": "main"}).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
        "User-Agent": "RadarAssenze-sentinella"})
    try:
        with urllib.request.urlopen(richiesta, timeout=30) as r:
            scrivi(f"sentinella avviata (GitHub ha risposto {r.status})")
    except urllib.error.HTTPError as e:
        motivo = {401: "chiave scaduta o sbagliata", 403: "la chiave non ha il permesso Actions in scrittura",
                  404: "repository o workflow non trovato, oppure la chiave non vede purestats"}.get(e.code, "errore di GitHub")
        scrivi(f"sentinella NON avviata: {e.code}, {motivo}")
        if e.code in (401, 403, 404):
            avvisa_telegram(cfg, f"PureStats: la sentinella dal server non parte ({motivo}). "
                                 "Controlla la chiave nella sezione [github] di config.toml.")
    except (urllib.error.URLError, TimeoutError) as e:
        scrivi(f"sentinella NON avviata: GitHub non raggiungibile ({e}); riprovo al prossimo giro")


if __name__ == "__main__":
    main()
