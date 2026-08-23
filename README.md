# PureStats — Premier League

Archivio statistico che cresce da solo, partita dopo partita.
Medie arbitrali, disciplinari di squadra e statistiche di gioco.

## Come funziona

```
GitHub Actions (lunedì e giovedì)
        │
        ├─ scarica E0.csv da football-data.co.uk
        ├─ lo unisce a data/premier_league.csv senza duplicati
        ├─ ricalcola tutte le medie
        └─ committa le modifiche
                │
                └─ GitHub Pages pubblica docs/index.html
```

Nessuna chiave API. Nessun limite di richieste. Nessun account da creare.

## Setup

**1. Carica i file** in un repository GitHub **pubblico**
(GitHub Pages richiede un repo pubblico sul piano gratuito).

**2. Permessi di scrittura**
Settings → Actions → General → Workflow permissions → **Read and write permissions** → Save

**3. Attiva Pages**
Settings → Pages → Source: Deploy from a branch → Branch `main`, cartella `/docs`

**4. Primo caricamento**
Actions → *Aggiorna archivio Premier League* → Run workflow

Da qui in avanti si aggiorna da solo.

## Caricare lo storico

Di default scarica solo la stagione in corso. Per partire con anni di dati:

Settings → Secrets and variables → Actions → tab **Variables** → New variable
- Name: `STAGIONI`
- Value: `2021,2122,2223,2324,2425,2526,2627`

Poi rilancia il workflow. Sono circa 2.500 partite, 2 MB. Fatto una volta, puoi
rimuovere la variabile: l'archivio resta e continua a crescere.

## Interrogare i dati

L'archivio è un CSV. Lo script `query.py` lo trasforma in SQLite:

```bash
python scripts/query.py                  # riepilogo
python scripts/query.py --esempi         # query di esempio
python scripts/query.py "SELECT ..."     # query libera
```

Tabella `partite`, più tre viste già pronte:

| Vista | Cosa contiene |
|---|---|
| `prestazioni` | una riga per squadra per partita (casa e trasferta separate) |
| `medie_arbitri` | partite dirette, medie cartellini e falli, squilibrio casa/trasferta |
| `medie_squadre` | medie disciplinari e di gioco per squadra |

Esempio:

```sql
SELECT arbitro, partite, media_gialli, squilibrio_ospite
FROM medie_arbitri
WHERE partite >= 5
ORDER BY media_gialli DESC;
```

## Cosa contiene l'archivio

Per ogni partita: data, squadre, risultato finale e primo tempo, **arbitro**,
tiri, tiri in porta, falli, corner, cartellini gialli e rossi (per squadra).

**Non contiene** i cartellini attribuiti al singolo giocatore: la fonte non li fornisce.
Per quelli serve un provider a pagamento.

Le quote dei bookmaker presenti nel file originale vengono scartate.

## Note sui dati

I campi statistici vuoti significano "non rilevato", non "zero". Le medie
li escludono dal calcolo invece di trattarli come zeri, così una partita
senza dati non abbassa artificialmente la media di un arbitro.

Il file remoto è sempre considerato autorevole: se una statistica viene
corretta a posteriori, l'aggiornamento successivo la sistema anche in archivio.

## Fonte

[football-data.co.uk](https://www.football-data.co.uk/englandm.php) di Joseph Buchdahl.
Dati distribuiti sotto Public Domain Dedication and License (PDDL).

Il campo arbitro è popolato per i campionati inglesi. Per la Serie A la stessa
fonte lo lascia vuoto: servirà una fonte dedicata.

## Spazio occupato

Circa 250 KB per stagione nel CSV. Il limite consigliato da GitHub è 1 GB:
spazio per qualche migliaio di stagioni.
