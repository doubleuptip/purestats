"""
Cifra i dati del calcio prima della pubblicazione (dal 17/11/2026: il calcio lo vede solo Valerio).

Uso:  python scripts/cifra_pagine.py docs/data.json [docs/data_serie_a.json ...]

Per ogni file: lo cifra con la password del secret DUELLI_PASSWORD (stesso metodo di Matchup, scripts/fetch_duelli.py),
scrive accanto il .dat, controlla di saperlo riaprire e cancella il .json in chiaro. Il repository è pubblico:
se la password manca o la cifratura non riesce, il .json in chiaro viene cancellato comunque e il .dat di prima
resta com'è (la pagina continua a mostrare i dati precedenti), e lo script esce con errore.
Solo libreria standard.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_duelli import cifra, decifra  # noqa: E402


def main(percorsi: list[str]) -> int:
    password = os.environ.get("DUELLI_PASSWORD", "")
    errori = 0
    for p in map(Path, percorsi):
        if not p.exists():
            print(f"{p.name}: non c'è (lo script del campionato non l'ha scritto in questo giro), niente da cifrare.")
            continue
        dat = p.with_suffix(".dat")
        try:
            if len(password) < 8:
                raise RuntimeError("DUELLI_PASSWORD mancante o più corta di 8 caratteri nei secret")
            testo = p.read_bytes()
            json.loads(testo)                                   # pubblico solo un JSON valido
            pacchetto = cifra(testo, password)
            if decifra(pacchetto, password) != testo:
                raise RuntimeError("il file cifrato non si riapre uguale")
            temporaneo = dat.with_suffix(".dat.tmp")
            temporaneo.write_text(json.dumps(pacchetto, separators=(",", ":")), encoding="utf-8")
            temporaneo.replace(dat)
            print(f"{p.name} → {dat.name}: cifrato ({len(testo) // 1024} KB), il chiaro non viene pubblicato.")
        except Exception as e:                                 # noqa: BLE001 - mai pubblicare il chiaro
            errori += 1
            print(f"{p.name}: NON cifrato ({e}). Il file in chiaro viene cancellato e resta il {dat.name} di prima.")
        finally:
            p.unlink(missing_ok=True)
    return 1 if errori else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scripts/cifra_pagine.py docs/<file>.json [...]")
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
