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
  NFL da ESPN (riserva nflverse injuries, spesso una settimana indietro); meteo NWS + Open-Meteo, effetto del vento
  misurato per campionato (NFL avviso da 15 mph; college nessun effetto sotto 20 mph, sopra solo 14 casi), niente
  meteo in campo neutro (lo stadio non è quello di casa); forza squadre dalle azioni. `aggiorna_contesto.py` rifà solo
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
  (nessuna chiamata). Linee chiuse in `data/college_linee.json`; i migliori di ogni partita (scheda pubblica)
  in `data/college_giocatori.json`
- Tabellini college completi (dal 14/11/2026): tutti i giocatori di ogni partita, tutte le tabelle ESPN (passaggi,
  corse, ricezioni, difesa, calci, ritorni), in `data/college_tabellini_<stagione>.json`, una partita per riga
  (`[id ESPN, nome, valori...]` + etichette per categoria). La stagione in corso la aggiorna fetch_college.py
  (partite mancanti e finite da meno di 3 giorni); le passate si scaricano una volta con
  `scripts/storico_tabellini.py 2019-2025` (workflow College lanciato a mano, campo «tabellini_storico»:
  circa 800 richieste ESPN a stagione, gratis). Servono allo storico delle assenze (chi sparisce dal tabellino)

## Charlie (scheda nella pagina Matchup, dal 15/11/2026)

- Il prezzo giusto contro la quota del bookmaker italiano, due modalità: Partite (spread, totale, punti di una
  squadra) e Giocatori (prop). Tutto in `docs/duelli.html`, calcolato nel browser sui dati cifrati.
- Partite: probabilità dalla linea del mercato americano (`scripts/mercato.py`: DraftKings dalla lista partite ESPN,
  una richiesta per giro, aggiornata anche ogni ora dal contesto) e dagli scarti risultato − linea 2019-2025
  (`data/charlie_tabelle.json`, Protocollo 8). Il punteggio atteso della scheda Matchup NON entra: contro la linea
  di chiusura non aggiunge informazione. Assenze solo con i numeri del Protocollo 7 (spostamento della linea se non
  si è ancora mossa; indizi QB fresco e ricevitore college), vento solo con l'effetto misurato.
- Linea d'apertura (dal 15/11/2026): dalla stessa voce ESPN (pointSpread.home.open.line, total.over.open.line),
  nessuna chiamata in più. Charlie mostra apertura → ora e, per ogni assenza, se la notizia è probabilmente già nel
  prezzo; spunta da sola «linea non ancora mossa» solo con linea ferma e notizia della settimana (Valerio controlla).
- Prop americane (dal 15/11/2026): `mercato.prop_usa` legge da ESPN («propBets» della casa della linea, di solito
  DraftKings; 1-2 richieste per partita, gratis) la linea principale di yard lanciate/corsa/ricevute, ricezioni e
  tentativi, con l'apertura; id ESPN → gsis da players.csv di nflverse. Principale = la linea presente due volte
  (over e under); con le quote (ESPN BET 2023-25) quella più vicina alla parità. Se i campi bet365 sono vuoti
  Charlie usa questa al 50% (affidabilità B). Niente prop dei difensori su ESPN. Lo storico 2025 ha anche le quote.
- Inattivi (dal 16/11/2026): `mercato.inattivi` legge la lista del giorno ESPN (competitors/<squadra>/roster,
  didNotPlay) entro 2 ore e mezza dal via, 2 richieste per partita, gratis; ESPN lì scrive solo il cognome: nome e
  ruolo dall'id ESPN con players.csv nflverse. `fetch_duelli.applica_inattivi`: in dubbio non inattivo → ATTIVO
  («gioca», ✅), inattivo → INATTIVO (assenza confermata, ⛔); inattivi fuori dal rapporto solo se producono.
- «Il tuo giudizio» (dal 16/11/2026): comando da −10 a +10 punti di probabilità con il motivo, in tutte le
  modalità; la carta mostra Charlie e Charlie con giudizio; il codice per il bot finisce con
  `_g<p|m><punti><motivo>` (o linea offensiva, a assenze, m meteo, v motivazioni, x altro).
- Giocatori: riferimento bet365.it (linea e quote over/under inserite a mano, senza margine) e forma della
  statistica per spostarsi alla linea italiana (Protocollo 9: affidabilità A yard ricevute, di corsa, ricezioni,
  tentativi di corsa; C yard lanciate e college). Indizio: under yard di corsa NFL. Elenco giocatori in
  `giocatoriProp` (nflverse per l'NFL, tabellini ESPN per il college).
- Le quote italiane (Snai, Sisal, ePlay24, Planetwin365, Lottomatica, Bet365) le inserisce Valerio: non si leggono in
  automatico. Bottone «Registra»: collegamento al bot (secret CHARLIE_BOT con il nome del bot) che tiene il registro
  e controlla esito e linea di chiusura (`/charlie` nel bot). Senza il secret il testo si copia da incollare.
- Difesa NFL (Giocatori → Difesa, solo bet365): `scripts/difesa_charlie.py` calcola per ogni difensore probabilità di
  almeno 0,5 sack (regola bet365), di almeno un intercetto e placcaggi attesi, con le formule del Protocollo 10
  (ritmi di attacco e difesa, andamento atteso dalla linea americana, quota del giocatore; intercetti ×1,28 con il QB
  titolare avversario fuori). Le assenze della linea offensiva NON entrano: sui sack non hanno effetto misurabile.
  Si ricalcola anche ogni ora: se una notizia sposta un numero di 2+ punti resta il valore di prima con il motivo.
  Dal 16/11/2026 la quota sui sack conta anche le pressioni PFR (advstats_week_def via nflverse, `pressioni_nfl`):
  quota = (sack + 0,3·colpi + 1,0·pressioni + 27·media ruolo) / (totale + 27), curva a = 1,05, b = 0,90
  (Protocollo 10, aggiunta: Brier sulla prova 2023-25 da 0,09418 a 0,09289). Le pressioni arrivano circa una
  settimana dopo; nomi abbinati per stagione, settimana, squadra e nome normalizzato.
- Le tabelle si rifanno con `misure/tabelle_charlie.py` (fuori dal repository) quando cambiano le misure.

## Calendario e Matchup (dal 16/11/2026)

- Stile unico per tutto il sito (calcio compreso): tema `fb` sempre attivo (Inter per il testo, Archivo in chiaro e
  Barlow Condensed in scuro per i titoli, colori --fb-*). Le regole usano `var(--f-testo)` e `var(--f-tit)`; i colori
  nel JavaScript (FLUO, MUTED, ... e i grafici) si leggono dal tema con `aggiornaColori()`. Le misure piccole scritte
  nel codice delle viste del calcio (font-size 8-11px) sono portate a 12-14px dal CSS.

- Calendario week per week ordinato per orario d'inizio, con data e ora italiane (`dataIt`, `oraIt`): NFL dall'ora
  della costa est di nflverse, college dall'inizio ESPN in UTC (solo le stagioni lette da ESPN nel giro).
- Matchup: ogni partita è un riquadro chiuso (classe `riquadro`: striscia con i colori delle squadre, bordo,
  testata su fondo diverso). Attenzione: la classe `partita` esiste già per un altro uso.

## Giornata NFL (dal 16/11/2026)

- `scripts/nfl_giornata.py` (Raccolta): legge il play-by-play nflverse nello stesso passaggio di nfl_indici
  (`_riassunto_pbp(..., raccolta)`), nessun download in più. Blocchi in `giornata`: `giocate` (5 attacco e 5 difesa, dal 16/11/2026
  per WPA di chi le fa; difesa = sack, intercetto, fumble recuperato, stop al quarto down, safety; niente special
  team), `squadreSettimana` (EPA/azione corretto con le stime degli indici: attacco = EPA − (media − difesa
  avversaria), difesa = (media + attacco avversario) − EPA concesso), `ultimiDueMinuti` (punti dopo il two-minute
  warning, stagione) e `flag` (penalità accettate per squadra e per capo arbitro, colonna referee dei calendari).
- Le carte delle partite mostrano data e ora italiane (`dataIt`, `oraIt`) anche in Giornata e Prossimo turno.
- College (dal 16/11/2026): cfbfastR arriva circa una settimana dopo, quindi la Giornata college usa il summary ESPN
  già scaricato per i tabellini (`college_giornata.riassunto_partita`, voce «azioni» nell'archivio dei tabellini:
  giocate per probabilità di vittoria ESPN, flag dal boxscore, punti negli ultimi 2 minuti, yard e azioni).
  Squadre della week in yard per azione corrette per l'avversario (non EPA). Le partite già in archivio senza
  «azioni» si rileggono una volta, al massimo 800 per giro (RILETTURE_AZIONI); al cambio di college_giornata.VERSIONE si rileggono, gratis.

- Impaginazione della Giornata (16/11/2026, scelta di Valerio: «A» con la testata di «B»): numeri della week
  (partite, favorite oltre la linea, over/under, sorpresa) e podio delle 3 squadre; tabellone con tutte le partite in
  schede uguali (`schedaTabellone`: niente anteprima grande del video, «▶ Highlights» e momenti nel piede); sotto, le
  sezioni a schede una alla volta (`sezioniGiornata`, `schedaGiornata`): Giocate, Squadre, Leader, Sorprese, Ultimi 2
  minuti, Flag. Sempre a tutta larghezza o in due/tre metà uguali: niente buchi. Tasto «torna su» in tutte le pagine.
- Indizi di Charlie (16/11/2026), sempre da spuntare, affidabilità C:
  · squadra già fuori dai playoff (NFL, dalla settimana 12): `scripts/nfl_playoff.py` simula 4.000 volte il resto
    della stagione (linee note; per le settimane future linea stimata dalle forze di mercato), «fuori» = probabilità
    sotto 2% e partita che non la cambia (≤ 2 punti). −1,5 punti sulla linea alla squadra fuori (Protocollo 11, B).
  · rinunce ai bowl (college, partite dal 13/12): titolari della stagione dai tabellini (`titolari_college`, pesi
    QB 3, RB e 3 ricevitori 1, 3 difensori 0,5); Valerio spunta chi ha annunciato la rinuncia; −1 punto per punto di
    peso (Protocollo 12: conferma 2019-22 non superata). Il bot (5.9.8) avvisa delle rinunce da ESPN college.
- Leader della Giornata (16/11/2026): anche la difesa. NFL dalle stesse statistiche settimanali nflverse (sack,
  intercetti, placcaggi + assist, fumble forzati, passaggi deviati) e pressioni PFR (advstats_week_def) dell'ultima
  week pubblicata, con l'avviso «week N, non questa» perché arrivano circa 7 giorni dopo. College dai tabellini ESPN
  in archivio (`college_indici._difesa_college`: sack, intercetti, placcaggi, deviati; ESPN non dà i fumble forzati).
- Charlie, Giocatori → Difesa → «Sack di squadra (over/under)» (16/11/2026): Poisson sui sack attesi della difesa
  con la correzione della prova 2023-25 (+4% oltre 2,2 attesi, +9% oltre 3,0); il bot 5.9.8 chiude la giocata
  sommando i sack della squadra nel tabellino ESPN (stat «sq», sigla nflverse; LA→LAR, WAS→WSH).
- Logo (16/11/2026, disegno di Valerio): simbolo vettoriale nel codice delle pagine (`logo-simbolo`, barre +
  battito) e scritta PURE/STATS con i caratteri del sito; colori `--logo-testo` / `--logo-rosso` (di notte rosso
  acceso #EF4444 per il contrasto). Icona della scheda `docs/icona.svg` (giorno/notte), schermata Home
  `docs/icona-180.png` (ricavata da rsvg-convert). Marchio completo in `docs/brand/` (logo orizzontale e simbolo
  trasparenti, anteprima dei link 1200×630, foto profilo 1080, copertina 1500×500, chiaro e scuro), `favicon.ico`,
  `icona-192/512.png` e `manifest.webmanifest`; anteprima dei link (og:image) = brand/anteprima-link-scuro.png.
  Si rifanno con `misure/genera_marchio.py` (Archivo e Inter installati, larghezze misurate con Pillow).

## Calcio e Matchup solo per Valerio (dal 17/11/2026)

- Il sito si apre su NFL; per tutti si vedono solo NFL e College FB. Calcio (tutti i campionati e il calendario) e il
  pulsante MATCHUP compaiono solo con il collegamento privato `https://doubleuptip.github.io/purestats/#k=<password>`
  (stessa password di Matchup, secret DUELLI_PASSWORD). La pagina legge la chiave, la toglie subito dalla barra degli
  indirizzi (history.replaceState) e la tiene solo in memoria; la passa a duelli.html (`#NFL&k=...`), che si apre da
  solo, e il logo di duelli.html riporta alla pagina principale già sbloccata. Chiave sbagliata: il calcio resta nascosto.
- I dati del calcio sono pubblicati solo cifrati: ogni workflow del calcio lancia `scripts/cifra_pagine.py docs/<file>.json`
  (stesso metodo di fetch_duelli.cifra), che scrive il .dat, lo verifica e cancella sempre il .json in chiaro; i .json
  del calcio sono in .gitignore. Senza password il chiaro non esce e resta il .dat precedente.
- Restano pubblici gli archivi grezzi in data/ (CSV di football-data.co.uk, già pubblici alla fonte).
- Il logo della pagina principale è un collegamento: riporta alla pagina iniziale (`tornaHome`).
- Accesso ricordato (17/11/2026, scelta di Valerio): `docs/accesso.html`, pagina non collegata da nessun menu, controlla
  la password su un file cifrato e la salva in localStorage (`purestats_accesso`) su quel dispositivo; index.html e
  duelli.html la leggono e si aprono già sbloccati. Anche il collegamento #k= la salva al primo uso. «ESCI» (nel menu
  e in Matchup) la toglie; se la password cambia, quella ricordata si cancella da sola. È l'UNICA eccezione alla
  regola «niente localStorage».

## Aggiornamenti a fine partita (dal 17/11/2026, scelta di Valerio)

- Principio: i controlli gratis vanno il più vicino possibile alla fine degli eventi, con riserve se saltano.
- `.github/workflows/sentinella.yml` ogni 15 minuti nelle finestre di gioco lancia `scripts/sentinella.py`: partite
  finite su ESPN (1 richiesta per campionato) senza punteggio sul sito → lancia update-nfl/update-college. NFL solo
  quando il play-by-play nflverse (rilascio pbp) e il calendario (nfldata games.csv) sono aggiornati dopo la fine
  stimata (inizio + 3h15); mai due giri insieme, pausa 30 min (NFL) / 60 min (college) se la fonte non ha ancora la
  partita. Lancia con GITHUB_TOKEN (workflow_dispatch è permesso).
- Riserve fisse alle 07:00 e 07:30 italiane (06:00/06:30 UTC) dopo le notti di gioco. Orari scritti per l'ora solare:
  con l'ora legale vanno anticipati di un'ora.

## Statistiche pubbliche (dal 18/11/2026)

- Vista «STATISTICHE» nella pagina principale (NFL e College): giocatori o squadre (fatte/concesse), stagione, periodo
  (tutta, ultime 3/5 week, una week), squadra, totali o a partita, ricerca, 7 categorie, tabella ordinabile con la
  colonna del nome ferma, scheda del giocatore (numeri con posizione nella lega, grafico, partite). Dati a richiesta:
  `docs/stats/<lega>_<stagione>_<categoria>.json` + `indice_<lega>.json`, preparati da `scripts/statistiche.py`
  (una riga per giocatore e partita; squadre come numeri; somme e derivati nel browser, `ST_COL`). Stagione in corso
  a ogni giro dei workflow NFL e College; storico 2019-2025 fatto una volta. Solo stagione regolare.
- Fonti: NFL nflverse (CC-BY 4.0, va citato), College tabellini ESPN. Le pressioni PFR non si ripubblicano: tolte
  anche dai leader della Giornata, restano solo per Charlie (cifrato).

## Articoli (dal 19/11/2026, scelta di Valerio)

- Anteprime e cronache delle 3 partite NFL e 3 college più importanti della settimana (playoff o cartello), scritte
  da Claude (attività programmate dell'abbonamento: nessuna API a pagamento; GitHub Models è chiuso, Gemini gratis
  vietato agli utenti UE, Mistral gratis senza chiavi API, Groq gratuito scrive un italiano non all'altezza).
- Metodo: `scripts/articoli.py fatti <game_id>` prepara i fatti verificati (nflverse) in `data/articoli/`; Claude scrive
  dalla guida `scripts/ARTICOLI_GUIDA.md`; `pubblica` rifiuta numeri e nomi che non sono nei fatti e scrive
  `docs/articoli/<id>.json` + `indice.json`. Il workflow `articoli-meteo.yml` aggiorna la scheda meteo (NWS/Open-Meteo,
  regola d'impatto generica e pubblica, non le misure di Charlie). Foto degli stadi in `docs/articoli/stadi/` (Wikimedia,
  crediti in `crediti.json`).
- Sito: menu ARTICOLI, articolo con impaginazione B (testo a sinistra, colonna con meteo e numeri), collegamento
  «Leggi l'anteprima/la cronaca» dalle schede partita, indirizzo diretto `#articolo=<id>`.

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
- **Niente localStorage** nella dashboard, tranne la chiave dell'accesso privato (`purestats_accesso`).

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

- 17/11/2026 sera: ESPN ha risposto per un giro con tutte le partite college alla stessa data (1993-01-31) e gli
  stessi spettatori; l'archivio li ha presi per buoni (il giro dopo li ha corretti). Da allora
  `espn_college.risposta_plausibile` scarta le settimane con date fuori stagione o tutte uguali e l'archivio resta
  com'era. Orari non fissati dalla tv (`timeValid` falso): solo la data, la pagina scrive «orario da definire».
  Loghi delle squadre FCS dalle risposte ESPN in `loghiExtra` (non in `loghi`, che serve a riconoscere le FBS).

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

- 19/11/2026: Josh Downs (ceduto ai Chiefs il 10/11) compariva ancora tra i giocatori dei Colts nell'articolo, perché
  la squadra si prendeva da tutte le righe della stagione. Da allora la squadra di un giocatore è quella della sua
  partita più recente (`articoli.squadra_attuale`, e lo stesso in `nfl_indici._chiave_squadra`,
  `fetch_duelli.giocatori_prop` e `fetch_duelli.quote_produzione_nfl`): i ceduti passano alla nuova squadra.

- 19/11/2026: nel college Gael Ochoa (Rice) compariva come QB e come RB nel bot e in Matchup, perché i tabellini ESPN
  danno il migliore per categoria (passaggi, corse, ricezioni), non il ruolo: il QB che corre diventava anche «RB»
  (17 squadre su 138, titolari dei bowl 19, ruoli prop 4). Da allora `college_indici._duelli` sceglie dai tabellini
  completi (QB = più lanci nelle ultime 3, RB = più corse escluso il QB, nessun nome due volte, medie su tutte le
  partite giocate) e il QB con almeno 15 yard di corsa a partita ha la riga «QB corse» (taratura «QB CORSE»,
  misura del 19/11); stesso principio in `titolari_college` e `giocatori_prop`; sul sito, nelle schede partita del
  college, le etichette sono PASS / CORSA / RIC.

## Stato attuale

- Premier League: funzionante, con arbitri
- Serie A: funzionante per le statistiche di squadra; gli arbitri
  dipendono dall'inserimento manuale delle designazioni
- Cartellini per singolo giocatore: non disponibili in nessuno dei due
  campionati con le fonti attuali

## Da controllare

- Dicembre 2026, rinunce ai bowl: i titolari si contano sull'intera stagione (Protocollo 12), quindi una squadra
  che ha cambiato QB a metà anno ha ancora il vecchio come titolare (Rice: Jacurri Brown, ora ricevitore; gioca
  Gael Ochoa). Prima di spuntare le rinunce, controllare a mano le squadre che hanno cambiato QB.

## Da fare da sabato 21/11/2026 (dopo il rinnovo dell'abbonamento, ore 5)

0. PER PRIMA COSA (scelta di Valerio del 20/11): momenti decisivi della Giornata NFL (nfl_indici._riassunto_pbp e
   la scelta in fondo a calcola): oggi usano home_wp «neutra» (Colts-Texans 26-3: Texans 57% al primo snap con 12,5
   di linea, tutti e 5 i momenti nel 1° quarto, anche passaggi senza peso). Correzione: vegas_home_wp /
   vegas_home_wp_post di nflverse, più peso alle azioni verso il risultato finale (touchdown, palle perse, quarti
   down fermati), al massimo 2 momenti per quarto. Poi la cronaca di Colts-Texans (2026_11_IND_HOU) come prova di
   tutte le cronache: serve prima in articoli.py la preparazione dei fatti dal play-by-play.
   Subito dopo, una riga: in fetch_duelli.py (circa riga 425) «assenze tra le più pesanti d'America (12ª su 138,
   12 in lista)» diventa «assenze tra le più pesanti del college: 12ª squadra su 138, 12 giocatori in lista»
   (Valerio l'aveva letto come un nome di giocatore).
1. Articoli, fase 2: scelta automatica delle 3 partite NFL (posta playoff da nfl_playoff + partite di cartello) e
   3 college (classificate / corsa ai playoff); cronache dal play-by-play con il video YouTube a metà testo; foto di
   tutti gli stadi NFL da Wikimedia con i crediti; college in articoli.py; attività programmate ricorrenti (martedì
   cronache dom/lun + anteprima del giovedì, venerdì cronaca del giovedì, sabato anteprime NFL e college, domenica
   cronache college).
2. Sezione «LEGGENDE» (nome scelto al posto di «Hall of Fame», marchio del museo di Canton), stile del template
   mostrato il 19/11: menu accanto ad ARTICOLI; racconto in evidenza con il numero di maglia grande nei colori della
   squadra (niente foto dei giocatori); «I più grandi» per ruolo (QB, RB, WR, TE, difesa, allenatori) in due elenchi:
   Record (dati) e I più grandi (criteri dichiarati: titoli, MVP, All-Pro, record, Canton, squadra dei 100 anni NFL);
   Dinastie come linea del tempo (Steelers '70, 49ers '80, Cowboys '90, Patriots 2001-19, Dolphins di Shula e il 1972);
   schede «Mai battuto». Fonti: nflverse (dal 1999, draft con Hall of Fame, rose), Wikipedia per le carriere prima
   del 1999 (da citare), niente Pro Football Reference (vieta la raccolta). Video solo da canali ufficiali NFL / NFL
   Films, scelti a mano, incorporati con youtube-nocookie, senza API.
   Ordine: struttura + classifiche (2 sessioni), poi racconti 2-3 a sessione o con attività programmata, poi college.
   Racconti: Kurt Warner; Joe Montana (record, The Catch 1982, drive del Super Bowl XXIII); Dan Marino e il 1984;
   Brady-Belichick a New England; i più grandi TE e RB; Ice Bowl 1967; Immaculate Reception 1972; Dolphins 1972
   imbattuti; rimonta da 28-3 nel Super Bowl LI; presa di Tyree (Super Bowl XLII, fine del 18-0); Barry Sanders che
   si ritira al massimo; Jerry Rice; Lawrence Taylor. College: Hail Mary di Flutie 1984, «The Play» Cal-Stanford 1982,
   Kick Six 2013, Boise State al Fiesta Bowl 2007.
3. Ogni fatto e record va riverificato prima di pubblicare (stesso metodo degli articoli).
4. Charlie, touchdown di un giocatore (richiesta del 19/11: Sisal, Snai, Planetwin365 lo quotano, bet365.it no).
   Verificato il 19/11: ESPN propBets elenca «Anytime Touchdown Scorer» (tipo 31) ma SENZA quote (current/open
   vuoti); bet365.com non si legge in automatico. Quindi: probabilità di Charlie dai dati = 1 − e^(−λ), λ = touchdown
   attesi della squadra (dal totale e dallo spread americani) × quota del giocatore (corse e bersagli vicino alla meta,
   touchdown fatti, ristretti verso la media del ruolo), tarata e provata su 2019-2025 (Brier, stima 2019-22, prova
   2023-25) e confrontata con le quote ESPN BET 2023-25 se l'archivio le ha. Nella pagina: statistica «Touchdown
   (sì)», quota italiana inserita a mano, campo facoltativo per una quota estera (bet365.com o altra) letta da
   Valerio; affidabilità decisa dalla prova. Poi college con cfbfastR.
