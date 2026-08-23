# PureStats

Archivio statistico di calcio che cresce nel tempo. Raccoglie risultati,
statistiche di squadra, cartellini e dati arbitrali per Premier League e
Serie A, li conserva su Git e li pubblica come sito statico.

Le risposte vanno scritte in **italiano**.

## Struttura

```
scripts/
  fetch_premier.py     Premier League: scarica, unisce, calcola
  fetch_serie_a.py     Serie A: come sopra + designazioni arbitrali
  designazioni.py      Interpreta il testo delle designazioni (solo parsing)
  query.py             Costruisce SQLite dal CSV ed esegue query
data/
  premier_league.csv   Archivio Premier (fonte di verità)
  serie_a.csv          Archivio Serie A (fonte di verità)
  designazioni.txt     Testo incollato a mano, una giornata per blocco
  designazioni_serie_a.json  Designazioni interpretate
docs/
  index.html           Dashboard (pagina unica, nessun build)
  data.json            Statistiche Premier calcolate
  data_serie_a.json    Statistiche Serie A calcolate
.github/workflows/     Due workflow, uno per campionato
```

## Come funziona

1. GitHub Actions esegue gli script su cadenza fissa
2. Gli script scaricano i dati, li uniscono all'archivio **senza duplicati**
3. Ricalcolano tutte le medie e scrivono i JSON in `docs/`
4. Il commit automatico aggiorna GitHub Pages

I CSV in `data/` sono la fonte di verità: sono testo, si versionano bene
e non si corrompono. Il database SQLite viene rigenerato da lì su richiesta
e non va versionato.

## Fonti dati

**football-data.co.uk** — licenza PDDL, nessuna chiave, nessun limite.
URL prevedibili: `mmz4281/<stagione>/<lega>.csv` dove stagione è `2627`
e lega è `E0` (Premier) o `I1` (Serie A).
Il campo `Referee` è popolato per l'Inghilterra, **vuoto per la Serie A**.

**Designazioni arbitrali Serie A** — inserite a mano in `data/designazioni.txt`.
Non sono automatizzabili: il sito della Lega è un'applicazione JavaScript
con endpoint non più validi, il sito AIA blocca gli accessi automatici e usa
URL con identificativi imprevedibili. Sono già stati tentati entrambi.

## Vincoli da rispettare

- **Nessuna fonte a pagamento** e nessuno scraping di siti che lo vietano.
  Sono già stati valutati e scartati: WhoScored, Transfermarkt, Opta,
  API-Football (il piano gratuito non copre questi campionati).
- **I campi vuoti restano vuoti**, non diventano zero. Un campo assente
  significa "non rilevato": trattarlo come zero falserebbe le medie.
- **Il file remoto è autorevole**: se una statistica viene corretta a
  posteriori, l'aggiornamento successivo la sistema anche in archivio.
- **La dashboard non ha build step**: HTML, CSS e JavaScript in un unico
  file, Chart.js da CDN. Va servita così com'è da GitHub Pages.
- **Niente localStorage** nella dashboard.

## Convenzioni

- Nomi di variabili, funzioni e commenti in italiano
- Solo libreria standard Python, nessuna dipendenza esterna
- Ogni script deve poter fallire senza corrompere l'archivio
- I messaggi di log devono dire cosa è successo e perché, non solo che
  qualcosa è andato storto

## Prima di considerare finito un lavoro

Verifica sempre, prima di dire che funziona:

```bash
python -c "import ast;ast.parse(open('scripts/fetch_serie_a.py').read())"
python scripts/query.py
node -e "const h=require('fs').readFileSync('docs/index.html','utf8');new Function(h.match(/<script>\n([\s\S]*?)<\/script>\s*<\/body>/)[1])"
```

Per la dashboard: aprire `docs/index.html` con Live Preview e controllare
davvero che si veda quello che deve vedersi.

## Errori già commessi, da non ripetere

- `salva_archivio` ordinava ma non restituiva la lista: le statistiche
  venivano calcolate su dati non ordinati
- Il separatore `·` sostituito da spazio faceva fondere il nome di un
  assistente con la squadra successiva
- Il filtro per data applicato a una stagione passata restituiva zero
  partite, perché la finestra cadeva fuori dal periodo giocato
- Designazioni di stagioni precedenti finite in archivio perché copiate
  da una pagina che conteneva anche notizie vecchie

## Stato attuale

- Premier League: funzionante, con arbitri
- Serie A: funzionante per le statistiche di squadra; gli arbitri
  dipendono dall'inserimento manuale delle designazioni
- Cartellini per singolo giocatore: non disponibili in nessuno dei due
  campionati con le fonti attuali
