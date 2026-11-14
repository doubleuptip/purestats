"""
Storico dei tabellini completi College da ESPN, per le stagioni passate (si lancia a mano, una volta sola).

Uso:  python scripts/storico_tabellini.py 2019-2025     (oppure una stagione: 2024)

Per ogni stagione legge il calendario ESPN (17 richieste) e il tabellino di ogni partita conclusa con almeno
una squadra FBS (regular season e postseason, circa 800 richieste), e li salva in
data/college_tabellini_<stagione>.json. ESPN è gratis e senza chiave; con la pausa tra le richieste serve
circa un secondo a partita. Le partite già in archivio non si richiedono: se il giro si interrompe, rilanciato
riparte da dove era arrivato. Le stagioni concluse non cambiano più: dopo questo giro non si toccano.
Serve allo storico delle assenze (un titolare che sparisce dal tabellino) e alle statistiche dei giocatori.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import espn_college  # noqa: E402
from fetch_college import (carica_tabellini, e_prima_divisione, salva_tabellini,  # noqa: E402
                           scheda_tabellino, stagione_corrente)


def stagioni_richieste(testo: str) -> list[int]:
    testo = (testo or "").strip()
    if "-" in testo:
        a, b = (int(x) for x in testo.split("-", 1))
        return list(range(min(a, b), max(a, b) + 1))
    return [int(testo)] if testo else []


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    try:
        stagioni = stagioni_richieste(sys.argv[1])
    except ValueError:
        print(f"Stagioni non valide: «{sys.argv[1]}» (esempio: 2019-2025)")
        return 2
    corrente = stagione_corrente()
    if corrente in stagioni:
        # la stagione in corso la aggiorna già fetch_college.py a ogni giro
        print(f"La stagione {corrente} è in corso: la aggiorna fetch_college.py, qui la salto")
        stagioni.remove(corrente)
    esito = 0
    for anno in stagioni:
        partite = espn_college.partite_stagione(anno)
        if partite is None:
            print(f"Stagione {anno}: calendario ESPN non letto, la salto (si può rilanciare)")
            esito = 1
            continue
        tabellini = carica_tabellini(anno)
        da_leggere = [g for g in partite if g.get("finita") and str(g["id"]) not in tabellini
                      and (e_prima_divisione(g["ConferenzaCasa"]) or e_prima_divisione(g["ConferenzaOspite"]))]
        print(f"Stagione {anno}: {len(partite)} partite in calendario, {len(tabellini)} tabellini già in archivio, "
              f"{len(da_leggere)} da leggere")
        fallite = 0
        for n, g in enumerate(da_leggere, 1):
            completo = espn_college.tabellino_completo(g["id"])
            if completo is None:
                fallite += 1
                continue
            tabellini[str(g["id"])] = scheda_tabellino(g, completo)
            if n % 100 == 0:
                salva_tabellini(anno, tabellini)
                print(f"    {n}/{len(da_leggere)} letti")
        salva_tabellini(anno, tabellini)
        vuoti = sum(1 for v in tabellini.values() if not v.get("squadre"))
        print(f"Stagione {anno}: {len(tabellini)} partite in archivio"
              + (f", {vuoti} senza tabellino su ESPN" if vuoti else "")
              + (f", {fallite} non lette (rilanciare per riprovarle)" if fallite else ""))
        if fallite:
            esito = 1
    print(espn_college.riepilogo())
    return esito


if __name__ == "__main__":
    sys.exit(main())
