"""
Linee di chiusura dei bowl delle stagioni passate da ESPN (si lancia a mano, una volta sola; gratis, senza chiave).

Uso:  python scripts/storico_linee_bowl.py 2019-2025

Per ogni partita di postseason già nell'archivio dei tabellini legge la linea pre-partita ESPN (una richiesta a
partita, circa 40 a stagione) e la salva in data/college_linee_bowl.json ({id: {stagione, casa, ospite, margine,
totale, fornitore, puntiCasa, puntiOspite}}). Le partite già salvate non si richiedono. I punteggi arrivano dal
calendario della postseason, una richiesta a stagione: in data/college.csv mancano per molti bowl 2019-2022.
Serve alla misura delle rinunce ai bowl (Protocollo 12): cfbfastR ha le linee dei bowl solo dal 2023.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import espn_college  # noqa: E402
from fetch_college import carica_tabellini  # noqa: E402
from storico_tabellini import stagioni_richieste  # noqa: E402

FILE = Path(__file__).resolve().parent.parent / "data" / "college_linee_bowl.json"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    stagioni = stagioni_richieste(sys.argv[1])
    dati = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    nuove = mancanti = punteggi = 0
    for s in stagioni:
        for gid, v in carica_tabellini(s).items():
            if v.get("tipo") != "postseason" or gid in dati:
                continue
            l = espn_college.linea(gid)
            time.sleep(0.5)
            if not l:
                mancanti += 1
                continue
            dati[gid] = {"stagione": s, "casa": v.get("casa"), "ospite": v.get("ospite"), **l}
            nuove += 1
        senza_punti = [g for g, x in dati.items() if x.get("stagione") == s and "puntiCasa" not in x]
        if senza_punti:
            post = espn_college.partite_settimana(s, 1, "postseason")
            if post is None:
                print(f"  stagione {s}: calendario della postseason non letto, punteggi rimandati")
            else:
                per_id = {p["id"]: p for p in post if p.get("finita") and p.get("PuntiCasa") != ""}
                for g in senza_punti:
                    p = per_id.get(g)
                    if p:
                        dati[g]["puntiCasa"], dati[g]["puntiOspite"] = int(p["PuntiCasa"]), int(p["PuntiOspite"])
                        punteggi += 1
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(dati, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
        os.replace(tmp, FILE)
        print(f"  stagione {s}: linee dei bowl in archivio {sum(1 for x in dati.values() if x['stagione'] == s)}")
    print(f"Linee nuove {nuove}, bowl senza linea ESPN {mancanti}, punteggi aggiunti {punteggi}. "
          f"{espn_college.riepilogo()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
