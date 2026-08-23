"""
Costruisce un database SQLite interrogabile a partire dall'archivio CSV.

Uso:
    python scripts/query.py                      # crea il DB e mostra un riepilogo
    python scripts/query.py "SELECT ..."         # esegue una query SQL
    python scripts/query.py --esempi             # mostra query di esempio

Il database viene rigenerato ogni volta dal CSV, che resta la fonte
di verità: è testo, si versiona bene su Git e non si corrompe.
"""

import csv
import sqlite3
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
ARCHIVIO = RADICE / "data" / "premier_league.csv"
DB = RADICE / "data" / "premier_league.db"

INTERI = {
    "GolCasa", "GolOspite", "GolCasaPT", "GolOspitePT",
    "TiriCasa", "TiriOspite", "TiriPortaCasa", "TiriPortaOspite",
    "FalliCasa", "FalliOspite", "CornerCasa", "CornerOspite",
    "GialliCasa", "GialliOspite", "RossiCasa", "RossiOspite",
}

SCHEMA = """
DROP TABLE IF EXISTS partite;
CREATE TABLE partite (
    id              INTEGER PRIMARY KEY,
    stagione        TEXT,
    data            TEXT,
    ora             TEXT,
    casa            TEXT,
    ospite          TEXT,
    gol_casa        INTEGER,
    gol_ospite      INTEGER,
    esito           TEXT,
    arbitro         TEXT,
    tiri_casa       INTEGER,
    tiri_ospite     INTEGER,
    tiri_porta_casa   INTEGER,
    tiri_porta_ospite INTEGER,
    falli_casa      INTEGER,
    falli_ospite    INTEGER,
    corner_casa     INTEGER,
    corner_ospite   INTEGER,
    gialli_casa     INTEGER,
    gialli_ospite   INTEGER,
    rossi_casa      INTEGER,
    rossi_ospite    INTEGER
);
CREATE INDEX idx_arbitro  ON partite(arbitro);
CREATE INDEX idx_casa     ON partite(casa);
CREATE INDEX idx_ospite   ON partite(ospite);
CREATE INDEX idx_stagione ON partite(stagione);

-- Vista: una riga per squadra per partita, comoda per le medie
DROP VIEW IF EXISTS prestazioni;
CREATE VIEW prestazioni AS
    SELECT stagione, data, arbitro, casa AS squadra, ospite AS avversario,
           'casa' AS campo, gol_casa AS gol, gol_ospite AS gol_subiti,
           gialli_casa AS gialli, rossi_casa AS rossi, falli_casa AS falli,
           tiri_casa AS tiri, corner_casa AS corner
    FROM partite
    UNION ALL
    SELECT stagione, data, arbitro, ospite AS squadra, casa AS avversario,
           'ospite' AS campo, gol_ospite AS gol, gol_casa AS gol_subiti,
           gialli_ospite AS gialli, rossi_ospite AS rossi, falli_ospite AS falli,
           tiri_ospite AS tiri, corner_ospite AS corner
    FROM partite;

-- Vista: medie per arbitro
DROP VIEW IF EXISTS medie_arbitri;
CREATE VIEW medie_arbitri AS
    SELECT arbitro,
           COUNT(*) AS partite,
           ROUND(AVG(gialli_casa + gialli_ospite), 2) AS media_gialli,
           ROUND(AVG(rossi_casa  + rossi_ospite),  2) AS media_rossi,
           ROUND(AVG(falli_casa  + falli_ospite),  1) AS media_falli,
           ROUND(AVG(gialli_ospite - gialli_casa), 2) AS squilibrio_ospite
    FROM partite
    WHERE arbitro <> '' AND gialli_casa IS NOT NULL
    GROUP BY arbitro;

-- Vista: medie per squadra
DROP VIEW IF EXISTS medie_squadre;
CREATE VIEW medie_squadre AS
    SELECT squadra,
           COUNT(*) AS partite,
           ROUND(AVG(gialli), 2) AS media_gialli,
           ROUND(AVG(rossi),  2) AS media_rossi,
           ROUND(AVG(falli),  1) AS media_falli,
           ROUND(AVG(tiri),   1) AS media_tiri
    FROM prestazioni
    WHERE gialli IS NOT NULL
    GROUP BY squadra;
"""

ESEMPI = [
    ("Arbitri più severi (almeno 3 partite)",
     "SELECT arbitro, partite, media_gialli, media_rossi FROM medie_arbitri "
     "WHERE partite >= 3 ORDER BY media_gialli DESC LIMIT 10"),

    ("Squadre più ammonite",
     "SELECT squadra, partite, media_gialli, media_falli FROM medie_squadre "
     "ORDER BY media_gialli DESC LIMIT 10"),

    ("Arbitri che puniscono di più le trasferte",
     "SELECT arbitro, partite, squilibrio_ospite FROM medie_arbitri "
     "WHERE partite >= 3 ORDER BY squilibrio_ospite DESC LIMIT 10"),

    ("Come si comporta una squadra con ciascun arbitro",
     "SELECT arbitro, COUNT(*) AS partite, ROUND(AVG(gialli),2) AS media_gialli "
     "FROM prestazioni WHERE squadra = 'Arsenal' AND arbitro <> '' "
     "GROUP BY arbitro ORDER BY media_gialli DESC"),

    ("Partite più nervose",
     "SELECT data, casa, ospite, arbitro, "
     "gialli_casa + gialli_ospite AS gialli, rossi_casa + rossi_ospite AS rossi "
     "FROM partite WHERE gialli_casa IS NOT NULL "
     "ORDER BY gialli DESC, rossi DESC LIMIT 10"),

    ("Differenza casa/trasferta per squadra",
     "SELECT squadra, campo, COUNT(*) AS partite, ROUND(AVG(gialli),2) AS media_gialli "
     "FROM prestazioni WHERE gialli IS NOT NULL GROUP BY squadra, campo "
     "ORDER BY squadra, campo"),
]


def esegui_schema(conn):
    """Esegue lo schema un'istruzione alla volta.

    executescript() in blocco può interrompersi in silenzio su alcune
    versioni di SQLite; così sappiamo esattamente cosa fallisce.
    """
    istruzioni = [s.strip() for s in SCHEMA.split(";") if s.strip()]
    for istruzione in istruzioni:
        # salta i blocchi di soli commenti
        righe_vive = [r for r in istruzione.splitlines()
                      if r.strip() and not r.strip().startswith("--")]
        if not righe_vive:
            continue
        try:
            conn.execute(istruzione)
        except sqlite3.Error as e:
            prima_riga = righe_vive[0][:70]
            print(f"  ! Schema fallito su: {prima_riga}")
            print(f"    {e}")
            raise
    conn.commit()

    # verifica che le viste esistano davvero
    presenti = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('view','table')")}
    attese = {"partite", "prestazioni", "medie_arbitri", "medie_squadre"}
    mancanti = attese - presenti
    if mancanti:
        raise sqlite3.OperationalError(
            f"oggetti non creati: {', '.join(sorted(mancanti))}")


def costruisci():
    if not ARCHIVIO.exists():
        print(f"Archivio non trovato: {ARCHIVIO}")
        print("Esegui prima: python scripts/fetch_premier.py")
        sys.exit(1)

    # Riparte sempre da zero: il CSV è la fonte di verità
    if DB.exists():
        DB.unlink()

    conn = sqlite3.connect(DB)
    esegui_schema(conn)

    def intero(v):
        v = (v or "").strip()
        if v == "":
            return None
        try:
            return int(float(v))
        except ValueError:
            return None

    with ARCHIVIO.open(encoding="utf-8", newline="") as f:
        righe = list(csv.DictReader(f))

    conn.executemany("""
        INSERT INTO partite (stagione, data, ora, casa, ospite, gol_casa, gol_ospite,
            esito, arbitro, tiri_casa, tiri_ospite, tiri_porta_casa, tiri_porta_ospite,
            falli_casa, falli_ospite, corner_casa, corner_ospite,
            gialli_casa, gialli_ospite, rossi_casa, rossi_ospite)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [
        (
            r.get("Stagione"), r.get("Data"), r.get("Ora"),
            r.get("Casa"), r.get("Ospite"),
            intero(r.get("GolCasa")), intero(r.get("GolOspite")),
            r.get("Esito"), (r.get("Arbitro") or "").strip(),
            intero(r.get("TiriCasa")), intero(r.get("TiriOspite")),
            intero(r.get("TiriPortaCasa")), intero(r.get("TiriPortaOspite")),
            intero(r.get("FalliCasa")), intero(r.get("FalliOspite")),
            intero(r.get("CornerCasa")), intero(r.get("CornerOspite")),
            intero(r.get("GialliCasa")), intero(r.get("GialliOspite")),
            intero(r.get("RossiCasa")), intero(r.get("RossiOspite")),
        )
        for r in righe
    ])
    conn.commit()
    return conn, len(righe)


def mostra(conn, sql):
    cur = conn.execute(sql)
    colonne = [d[0] for d in cur.description]
    righe = cur.fetchall()

    if not righe:
        print("  (nessun risultato)")
        return

    larghezze = [max(len(str(c)), *(len(str(r[i])) for r in righe))
                 for i, c in enumerate(colonne)]
    print("  " + " | ".join(str(c).ljust(w) for c, w in zip(colonne, larghezze)))
    print("  " + "-+-".join("-" * w for w in larghezze))
    for r in righe:
        print("  " + " | ".join(str(v if v is not None else "").ljust(w)
                                for v, w in zip(r, larghezze)))


def main():
    conn, n = costruisci()
    print(f"Database creato: {DB} ({n} partite)\n")

    argomenti = sys.argv[1:]

    if argomenti and argomenti[0] == "--esempi":
        for titolo, sql in ESEMPI:
            print(f"\n### {titolo}")
            print(f"    {sql}\n")
        return

    if argomenti:
        try:
            mostra(conn, " ".join(argomenti))
        except sqlite3.Error as e:
            print(f"Errore SQL: {e}")
            sys.exit(1)
        return

    # Riepilogo predefinito. Non deve far fallire il workflow:
    # se l'archivio è appena nato alcune query possono non dare risultati.
    for titolo, sql in ESEMPI[:3]:
        print(f"### {titolo}")
        try:
            mostra(conn, sql)
        except sqlite3.Error as e:
            print(f"  (query non riuscita: {e})")
        print()

    print("Altre query: python scripts/query.py --esempi")
    print('Query libera:  python scripts/query.py "SELECT * FROM partite LIMIT 5"')


if __name__ == "__main__":
    main()
