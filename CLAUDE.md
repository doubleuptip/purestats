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

## Sezione privata Matchup, NFL e College (duelli.html)

- Contesto (scripts/contesto.py): assenze college da CFBDepth (robots consente, solo stato/ruolo/peso, mai le note),
  NFL da ESPN (riserva nflverse injuries, spesso una settimana indietro); meteo NWS + Open-Meteo; forza squadre dalle azioni. `aggiorna_contesto.py` rifà solo
  assenze e meteo (workflow update-contesto.yml, ogni ora giovedì-domenica). Percentuali e meteo: misure del 13/11

- Prossimo turno, indici, giocatori chiave e duelli attacco-difesa stanno **solo** in
  `docs/duelli_nfl.dat` e `docs/duelli_college.dat`, cifrati con il secret `DUELLI_PASSWORD`
  e aperti da `docs/duelli.html` con la password (pulsante MATCHUP nel sito; il file resta duelli.html perché il bot ne usa l'indirizzo)
- `fetch_nfl.py` / `fetch_college.py` scrivono questi blocchi in `data/privato_<lega>.json`
  (in .gitignore, mai committato); subito dopo, nello stesso workflow, `fetch_duelli.py <lega>`
  li unisce e li cifra. Il repository è pubblico: nessun dato della sezione in chiaro
- `scripts/reparti.py` calcola i reparti dal play-by-play (nflverse per l'NFL, cfbfastR per il college,
  gratuiti e senza chiave) con le definizioni e le tarature verificate sullo storico 2019–2025: conta solo
  la difesa avversaria; la forma delle ultime 3 partite non è un segnale. Le tarature (TARATURA_*) vanno
  rifatte con lo stesso metodo se cambiano le definizioni
- Punteggio atteso (misura del 14/11, stima 2019–22 e prova 2023–25): fattore campo NFL +1,95 e college +2,96
  (zero in campo neutro: NFL dalla colonna location di nflverse, college da CampoNeutro in data/college.csv),
  totale college corretto di −3,54, margine college dalle norme corrette per le difese affrontate.
  Provate e scartate: correzione avversari ripetuta (SRS, peggiora il college) e z-score dei giocatori
- Cambio password: aggiornare il secret e rilanciare i workflow NFL e College
- College, fonti (dal 14/11/2026): calendario, risultati, campo neutro, linee e tabellini da ESPN
  (`scripts/espn_college.py`, gratis, senza chiave; id partite e nomi squadre uguali a CollegeFootballData).
  CollegeFootballData (1.000 chiamate al mese, chiave condivisa con il bot) solo per SP+ al massimo ogni
  6 giorni (`data/college_sp.json`) e loghi una volta a stagione. Stadi per il meteo: `data/college_stadi.json`
  (nessuna chiamata). Tabellini e linee chiuse restano in `data/college_giocatori.json` e `data/college_linee.json`

## Fonti a credito (chiamate limitate)

Prima di scrivere o lanciare qualunque script o workflow che usa una fonte con un limite di chiamate
(CollegeFootballData, OddsPapi, YouTube, prop-line): contare per iscritto chiamate per giro × giri al mese,
confrontarle con il limite e con quelle rimaste, e dirlo prima di lanciare. I dati che non cambiano (stadi,
loghi, stagioni concluse) si scaricano una volta e si salvano nel repository.

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

- Chiave CollegeFootballData esaurita a metà novembre 2026: gli stadi college venivano richiesti a ogni giro
  orario, l'archivio dei giocatori non era salvato e si riscaricava a ogni esecuzione (circa 30 chiamate),
  l'archivio partite (scritto senza intestazione) riscaricava ogni volta 5 stagioni, e un test sullo storico
  è stato lanciato senza contare le chiamate rimaste

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
