"""Aggiornamento leggero della sezione Matchup: rifà solo assenze e meteo (e il giudizio) delle partite dei
prossimi giorni, senza riscaricare il play-by-play. Apre il file cifrato, aggiorna, verifica e lo riscrive.
Uso: python scripts/aggiorna_contesto.py nfl|college   (password nel secret DUELLI_PASSWORD)
Se qualcosa va storto il file pubblicato resta com'è."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fetch_duelli as FD  # noqa: E402

LEGHE = {"nfl": "NFL", "college": "College"}


def main() -> int:
    lega = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    if lega not in LEGHE:
        print("Uso: aggiorna_contesto.py nfl|college")
        return 2
    password = os.environ.get("DUELLI_PASSWORD", "")
    if len(password) < 8:
        print("DUELLI_PASSWORD assente o troppo corta: non tocco niente.")
        return 0
    uscita = Path(__file__).resolve().parent.parent / "docs" / f"duelli_{lega}.dat"
    if not uscita.exists():
        print(f"{uscita.name} non esiste ancora: lo crea fetch_duelli.py.")
        return 0
    try:
        dati = json.loads(FD.decifra(json.loads(uscita.read_text(encoding="utf-8")), password))
    except Exception as e:     # noqa: BLE001
        print(f"{uscita.name} non si apre ({e}): password cambiata o file rovinato, non tocco niente.")
        return 1
    schede = dati.get("partite") or []
    stagione = datetime.now(timezone.utc).year if datetime.now(timezone.utc).month >= 3 else datetime.now(timezone.utc).year - 1
    settimana = max([int(x.get("settimana") or 0) for x in schede] or [0]) or FD_settimana(schede)
    FD.aggiorna_contesto(LEGHE[lega], lega, schede, stagione, settimana)
    dati["contestoAggiornato"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    testo = json.dumps(dati, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pacchetto = FD.cifra(testo, password)
    if FD.decifra(pacchetto, password) != testo:
        print("Verifica della cifratura fallita: non scrivo il file.")
        return 1
    tmp = uscita.with_suffix(".tmp")
    tmp.write_text(json.dumps(pacchetto, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, uscita)
    print(f"{LEGHE[lega]}: {uscita.name} aggiornato (assenze e meteo).")
    return 0


def FD_settimana(schede) -> int:
    """Settimana NFL dal calendario nflverse se le schede non la portano (serve per il rapporto infortuni)."""
    try:
        import csv, io
        righe = csv.DictReader(io.StringIO(FD.C._get("https://github.com/nflverse/nfldata/raw/master/data/games.csv", 60)))
        oggi = datetime.now(timezone.utc).date().isoformat()
        prossime = [r for r in righe if r.get("gameday", "") >= oggi and r.get("game_type") == "REG"]
        return int(min(prossime, key=lambda r: r["gameday"])["week"]) if prossime else 0
    except Exception:          # noqa: BLE001
        return 0


if __name__ == "__main__":
    sys.exit(main())
