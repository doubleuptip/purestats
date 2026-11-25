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
- Touchdown di un giocatore (Giocatori → Touchdown, NFL, dal 21/11/2026, `scripts/td_charlie.py`): probabilità di
  almeno un touchdown di corsa o su ricezione = 1 − e^(−0,95 · (0,129 · punti attesi − 0,483) · quota del giocatore);
  punti attesi dalla linea americana del momento (nel browser); quota = 0,3 occasioni dentro le 10 yard + 0,3 touchdown
  + 0,4 palloni toccati (stagione; la scorsa pesa 0,3 a partita, da data/td_nfl_<stagione>.json; verso la media del
  ruolo con 2 partite). Misura 2019-2025: Brier prova 0,1592 contro 0,1728 (−7,9%), affidabilità C (ESPN non dà le
  quote dei touchdown: nessun confronto col mercato). Quota italiana a mano, estera facoltativa (margine 8% tolto, pesa
  metà). Raccolta nello stesso passaggio del play-by-play di fetch_duelli. Bot 5.9.10: stat «td», chiude sommando i TD
  di corsa, ricezione e ritorni del tabellino ESPN. A fine stagione salvare data/td_nfl_<stagione>.json.
- Le tabelle si rifanno con `misure/tabelle_charlie.py` (fuori dal repository) quando cambiano le misure.

## Calendario e Matchup (dal 16/11/2026)

- Tema (22/11/2026, scelta di Valerio): scuro per tutti; bottone tondo sole/luna (`tema-btn`, `cambiaTema()`) in alto a
  destra in index, duelli, accesso, privacy e in tutte le pagine statiche (TEMA_TESTA / TEMA_BOTTONE in
  pagine_statiche.py). Script in <head> che mette `data-tema` su <html> prima del disegno; le regole scure hanno il
  prefisso `html:not([data-tema="chiaro"])` (niente più prefers-color-scheme); al cambio parte l'evento «tema»
  (index: aggiornaColori + render). Scelta ricordata in localStorage `purestats_tema`. Il calcio resta col suo stile.
- Stile unico per tutto il sito (calcio compreso): tema `fb` sempre attivo (Inter per il testo, Archivo in chiaro e
  Barlow Condensed in scuro per i titoli, colori --fb-*). Le regole usano `var(--f-testo)` e `var(--f-tit)`; i colori
  nel JavaScript (FLUO, MUTED, ... e i grafici) si leggono dal tema con `aggiornaColori()`. Le misure piccole scritte
  nel codice delle viste del calcio (font-size 8-11px) sono portate a 12-14px dal CSS.

- Menu (23/11/2026, scelta di Valerio): la voce PARTITE si chiama CALENDARIO in tutto il sito (vista interna sempre
  «partite», bottone `n-par`). Nel calcio prende il posto del vecchio CALENDARIO: la stessa vista mostra prima le
  prossime partite (vCalendario, calendario.dat) e sotto i risultati (vPartite); il vecchio bottone `n-cal` è tolto e
  «calendario» porta a «partite».
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
  acceso #EF4444 per il contrasto). Dal 21/11/2026 (scelta di Valerio) anche bottoni e accenti notturni usano #EF4444
  (prima arancione #FF8A3D) in index.html, duelli.html e accesso.html: stesso rosso del logo giorno e notte. Icona della scheda `docs/icona.svg` (giorno/notte), schermata Home
  `docs/icona-180.png` (ricavata da rsvg-convert). Marchio completo in `docs/brand/` (logo orizzontale e simbolo
  trasparenti, anteprima dei link 1200×630, foto profilo 1080, copertina 1500×500, chiaro e scuro), `favicon.ico`,
  `icona-192/512.png` e `manifest.webmanifest`; anteprima dei link (og:image) = brand/anteprima-link-scuro.png.
  Si rifanno con `misure/genera_marchio.py` (Archivo e Inter installati, larghezze misurate con Pillow).

## Calcio e Matchup solo per Valerio (dal 17/11/2026)

- Il sito si apre su NFL (pagina HOME); per tutti si vedono solo NFL e College FB. Calcio (tutti i campionati e il calendario) e il
  pulsante MATCHUP compaiono solo con il collegamento privato `https://purestats.it/#k=<password>` (prima doubleuptip.github.io/purestats, che ora rimanda qui)
  (stessa password di Matchup, secret DUELLI_PASSWORD). La pagina legge la chiave, la toglie subito dalla barra degli
  indirizzi (history.replaceState) e la tiene solo in memoria; la passa a duelli.html (`#NFL&k=...`), che si apre da
  solo, e il logo di duelli.html riporta alla pagina principale già sbloccata. Chiave sbagliata: il calcio resta nascosto.
- I dati del calcio sono pubblicati solo cifrati: ogni workflow del calcio lancia `scripts/cifra_pagine.py docs/<file>.json`
  (stesso metodo di fetch_duelli.cifra), che scrive il .dat, lo verifica e cancella sempre il .json in chiaro; i .json
  del calcio sono in .gitignore. Senza password il chiaro non esce e resta il .dat precedente.
- Restano pubblici gli archivi grezzi in data/ (CSV di football-data.co.uk, già pubblici alla fonte).
- Pagina pubblica senza la parola calcio (22/11/2026): titolo, descrizioni (meta, og, manifest) solo NFL e college;
  in «Fonti e condizioni d'uso» le fonti del calcio (quarto campo true in FONTI) si vedono solo con l'accesso privato.
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
- Menu unico (21/11/2026, scelta di Valerio): nel football niente più SQUADRE; STATISTICHE ha le schede «Squadre»
  (Classifica = la vecchia pagina SQUADRE con la scheda di ogni squadra · Fatte · Concesse) e «Giocatori»
  (`testataStat`, `schedaStat`, `ultimaStat`). Classifica ordinata per % vittorie e differenza. NFL e College si
  aprono sulla HOME (dal 21/11/2026), la prima scheda a sinistra del menu. Il calcio tiene il suo menu SQUADRE.
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
- Cronache (dal 21/11/2026): a partita giocata `fatti` aggiunge «partitaGiocata» dal play-by-play nflverse (punteggio per
  quarto, marcature con nome e cognome, momenti decisivi con lo stesso metodo della Giornata, numeri di squadra,
  protagonisti dal tabellino settimanale, esito contro linea e totale solo a parole, bilancio dopo, id del video);
  `pubblica <id> cronaca` mette punteggio, video a metà testo e il riquadro «I numeri della partita» (riquadro_cronaca).
  Se nflverse non ha ancora il play-by-play della partita, `fatti` si ferma e lo dice.
- Attività programmata «PureStats: articoli del giorno» (dal 21/11/2026, ogni giorno alle 11:47 italiane, sessione
  nuova): `articoli.py da_fare` → per ogni voce fatti, verifica web (notizie_<id>.json / correzioni_<id>.json con fonte),
  bozza, pubblica, commit; meteo lanciato se ci sono anteprime. College: `fatti_college` (SP+, tabellini ESPN; cronache
  dalle «azioni» ESPN in archivio, video solo se ufficiale). Scelta: `scegli_nfl` / `scegli_college` (bilanci, SP+,
  linea, division, prima serata), salvata in scelte_<lega>_<stagione>_<week>.json.
- Aggiornamenti delle anteprime (25/11/2026, scelta di Valerio): `da_fare` propone le voci «aggiornamento» (anteprima
  pubblicata, partita fra più di 2 ore, ultimo controllo oltre 18 ore fa). Novità vere → bozza con il campo
  «aggiornamento» (nota ≤ 300 caratteri) e `pubblica`: restano `pubblicato`, si aggiungono `aggiornato`,
  `aggiornamenti` [{quando, nota}] e `versioni` (testo precedente); senza novità `articoli.py controllato <id>_anteprima`
  (campo `controllato`, non visibile). Sito: firma «Pubblicato … · Aggiornato …», riquadro rosso «Aggiornamento ·
  data, ora» in cima al testo, «Versione del …» in fondo (`quandoIt`); pagine statiche con le stesse date,
  dateModified e lastmod della sitemap = aggiornato. Regole in ARTICOLI_GUIDA, «Aggiornamenti delle anteprime».
- Momenti decisivi (21/11/2026): probabilità di vittoria dal mercato (vegas_home_wp/vegas_home_wpa), sotto 3 punti solo
  azioni chiave, peso pieno verso il risultato finale, al massimo 2 per quarto (nfl_indici, costanti MOMENTI_*).
- Foto degli stadi (21/11/2026): `docs/articoli/stadi/<Stadio>.jpg` per l'NFL (vale anche in campo neutro),
  `<Stadio>__<Casa>.jpg` per il college (i nomi come «Memorial Stadium» si ripetono); crediti in `crediti.json`. Quelle
  che mancano le scarica `articoli.py foto_mancanti` nel workflow articoli-meteo (Wikimedia Commons, solo licenze libere;
  dalla sandbox non si raggiunge); senza foto la copertina usa i colori delle squadre. Video: solo anteprima che apre
  YouTube, perché la NFL blocca la visione dei suoi video dentro altri siti.
- Meteo di tutte le partite (21/11/2026, scelta di Valerio): `articoli.py meteo_partite` nel workflow articoli-meteo scrive
  `docs/meteo/partite.json` (NFL e college, prossimi 7 giorni, chiave stagione|week|casa|ospite) con la regola d'impatto
  generica degli articoli; previsione rifatta ogni 3 ore, ogni ora nelle 12 ore prima del via; niente meteo in campo
  neutro; stadi coperti segnati. Nelle schede delle partite da giocare (`meteoPartita`).
- Sito: menu ARTICOLI, articolo con impaginazione B (testo a sinistra, colonna con meteo e numeri), collegamento
  «Leggi l'anteprima/la cronaca» dalle schede partita, indirizzo diretto `#articolo=<id>`.

## Pagine statiche e dominio (dal 22/11/2026)

- Dominio purestats.it ATTIVO dal 22/11/2026 (OVH, nameserver dns200/ns200.anycast.me; zona: 4 A 185.199.108-111.153,
  4 AAAA 2606:50c0:8000-8003::153, www CNAME doubleuptip.github.io.; tolti i record di parcheggio OVH). docs/CNAME =
  purestats.it; il vecchio indirizzo github.io/purestats rimanda qui da solo.
- `scripts/pagine_statiche.py` (workflow pagine-statiche.yml, a ogni push di articoli, racconti, CNAME o dello script):
  una pagina HTML per articolo (`docs/a/<id>.html`) e per racconto (`docs/l/<id>.html`) con canonical, og e dati
  strutturati, più `sitemap.xml`, `robots.txt` e `404.html`. Indirizzo di base da `docs/CNAME`, altrimenti GitHub
  Pages. Legge solo file pubblici; si ferma se trova termini della parte privata o delle scommesse. Le pagine
  rimandano al sito con `#articolo=` / `#leggenda=`.
- Pagine NFL, archivio e Chi siamo (25/11/2026, scelta di Valerio del 22/11; solo NFL, il college a dicembre dopo il
  passaggio a CollegeFootballData): lo stesso `pagine_statiche.py` scrive `docs/archivio.html` (tutti gli articoli e
  racconti, dal più recente), `docs/chi-siamo.html`, `docs/nfl/week/<stagione>-<N>.html` (week giocate e quella in corso:
  orari italiani, punteggi, bollino «Inclusa in DAZN», anteprima/cronaca), `docs/nfl/squadre/<sigla>.html` (32, sigle
  di data_nfl.json: i Rams sono LA; stemma PureStats in SVG come svgStemma, mai loghi), `docs/nfl/classifica.html`
  (division e conference, ordine del sito: % vittorie e differenza, senza spareggi ufficiali) e `docs/nfl/calendario.html`
  (week in corso e prossima). Legge solo data_nfl.json, tv_italia.json, stemmi.json e gli indici di articoli e racconti.
  `controlla_nuova` (VIETATE_NUOVE) rifiuta anche linea, totale, over/under, quote, favorite, mercato. dateModified e
  lastmod della sitemap cambiano SOLO se il contenuto della pagina cambia (`con_data` confronta col file già scritto):
  i giri ripetuti non cambiano nulla. Si rifanno nel workflow NFL (passo prima del commit: i commit con GITHUB_TOKEN non
  lanciano pagine-statiche.yml) e in pagine-statiche.yml. «Apri nel sito» usa `#vista=<partite|squadre|articoli…>` e
  `#squadra=<sigla>` (index.html, VISTA_DAL_LINK / SQUADRA_DAL_LINK). Piede di index.html: ARCHIVIO e CHI SIAMO.
  Chi siamo va riletto da Valerio (può aggiungere 2-3 righe sue).
- Alla prima attivazione del dominio: docs/CNAME con `purestats.it`, og:url/og:image di index.html sul nuovo
  dominio, User-Agent degli script (articoli, leggende, tv_italia) e indirizzo di duelli.html nel bot. Le chiavi
  ricordate (localStorage) valgono per dominio: su purestats.it Valerio rifà l'accesso una volta.

## Leggende (dal 21/11/2026, scelta di Valerio)

- Menu LEGGENDE (solo NFL) accanto ad ARTICOLI, tre schede: «I più grandi» (squadra del centenario NFL, 2019, giuria di
  26 votanti, ordinabile per All-Pro, titoli, MVP, Pro Bowl; per gli allenatori titoli e allenatore dell'anno AP),
  «Record» (prime 10 di carriera in stagione regolare per ruolo; TE = i tight end presenti nelle classifiche dei
  ricevitori) e «Dinastie» (finestre e protagonisti scelti da noi in `leggende.DINASTIE`, finali dalla voce dei Super Bowl).
- `scripts/leggende.py aggiorna` (workflow leggende.yml, mercoledì 06:17 UTC): voci Wikipedia via API (citate, CC BY-SA)
  + stats_player_reg nflverse 1999-oggi; scrive `docs/leggende/leggende.json`. I numeri restano quelli ufficiali di
  Wikipedia; nflverse li conferma per i giocatori dal 1999 (✓ in pagina, tolleranza 2 o 0,5%: le statistiche
  ricostruite azione per azione differiscono di poco da quelle ufficiali). Una differenza più grande finisce nel
  registro come «ATTENZIONE ... da controllare». Se una voce cambia struttura lo script si ferma e il file resta com'era.
- Racconti (21/11/2026): `docs/leggende/racconti.json` scritto a mano (id, titolo, occhiello, grande = numero di maglia
  o cifra simbolo, colori della squadra dell'epoca, numeri, paragrafi, fonti). «In evidenza» in cima alla pagina cambia ogni giorno; indirizzo diretto `#leggenda=<id>`. Ogni fatto si verifica sulla voce Wikipedia citata (scaricata
  dal ramo bozze, workflow bozze.yml) prima di pubblicare; testo nostro, niente frasi copiate. Fatti: Kurt Warner,
  Joe Montana, Dolphins 1972, rimonta 28-3 (Super Bowl LI), presa di Tyree (Super Bowl XLII), Barry Sanders, Dan Marino e il 1984.
- Data di pubblicazione dei racconti (25/11/2026, Valerio): campo «pubblicato» (2026-11-25T09:26+01:00, come gli articoli);
  nella Home «Da leggere» mette le carte dalla più recente, racconto compreso (senza «pubblicato» conta come il più nuovo).
- «Mai battuto»: per ogni classifica il detentore e il migliore ancora in attività con la distanza (`maiBattuti` in
  leggende.json), più la stagione perfetta 17-0 dei Dolphins.
- Video (21/11/2026): ogni racconto ha «Guarda il video» a metà testo, un collegamento (non incorporato) a una pagina
  ufficiale: NFL.com (NFL Throwback, NFL Films, A Football Life) per la NFL; ESPN o il sito dell'università per il college.
  Si sceglie con WebSearch e si controlla con WebFetch che la pagina esista (YouTube non si legge dalla sandbox).
- College (21/11/2026): LEGGENDE anche nel College FB, solo la scheda Racconti (campo «lega» nei racconti; id «college-…»):
  Hail Flutie 1984, The Play 1982, Kick Six 2013, Boise State al Fiesta Bowl 2007. Il collegamento diretto a un
  racconto dell'altro campionato cambia campionato da solo (`LEG_SEGUI`).
- Un racconto nuovo ogni mercoledì (scelta di Valerio): attività programmata «PureStats: racconto delle Leggende».
- Copertine e grafici (21/11/2026, scelta di Valerio «A + E + F» tra sei proposte): ogni racconto ha una copertina
  (`legCopertina`: sfumatura nei due «colori», «grande» enorme in contorno, «LEGGENDE · Nº», anni in pastiglia, titolo
  su vetro smerigliato) usata in lista, in evidenza, in testa al racconto e nella Home; niente foto né maglie. Nel
  racconto aperto, sotto i numeri, «La carriera/partita/stagione in un grafico» (`legGrafico`, campo «grafico» in
  racconti.json): carriera = tappe (linea del tempo, verticale su telefono); partita = differenza di punteggio minuto
  per minuto (dal 1999 play-by-play nflverse, prima marcature della voce Wikipedia); sequenza = marcature in ordine
  quando la fonte non dà i minuti (Flutie, The Play); stagione = barre (Dolphins 1972, Sanders). Ogni grafico cita la
  sua fonte. L'attività del mercoledì prepara anche il grafico del racconto nuovo.

## Home (dal 21/11/2026, scelta di Valerio: opzione C «più professionale»)

- HOME è la prima voce del menu e la pagina d'apertura di NFL e College (`vHome`, funzioni `...H`). NFL: striscia della
  week con conto alla rovescia (ora italiana con `istanteRoma`), partita della settimana (articolo più recente) e ultima
  partita, poi (ordine scelto da Valerio il 21/11) In TV in Italia, da leggere, storia (accadde oggi, mai battuto,
  dinastie: le ultime due cambiano ogni giorno), dal College, il meglio della week, la corsa (playoff AFC/NFC + ranking),
  la strada verso i playoff (partite decisive + meteo). College: striscia con le partite delle squadre in classifica, apertura, da leggere, classifica CFP e rating PureStats, il meglio, dalla NFL.
- Icone delle sezioni (21/11/2026, disegni di Valerio fatti con Gemini, piatti su fondo bianco): `docs/icone/<nome>_base.png`
  e `_rosso.png`, due maschere 128 px ricavate togliendo il bianco e separando il rosso; `iconaH(nome)` le colora con
  `--fb-text` e `--fb-acc`, quindi seguono da sole tema chiaro e scuro. tv, giornale, clessidra, casco, freccia,
  grafico, barre.
- Testata della pagina STATISTICHE: `docs/icone/statistiche_testata.jpg` (immagine di Valerio). La maglia disegnata
  per i racconti è stata tolta il 21/11/2026 (poco professionale secondo Valerio): vedi Leggende, copertine.
- `scripts/home_nfl.py` (workflow NFL, dopo fetch_duelli) → `docs/home_nfl.json`: corsa ai playoff con
  `nfl_playoff.corsa` (stessa simulazione di Charlie, tutte le partite rimaste; `stato` di Charlie invariato, verificato
  identico), partite decisive (somma dei salti vittoria/sconfitta), ranking (metà margini corretti per gli avversari,
  metà EPA degli indici se il giro li ha; movimento dalla settimana prima, `storico` nel file), il meglio della week
  (giocata dalla Giornata, giocatore per punti fantasy standard nflverse, squadra EPA; resta l'ultima week completa finché
  quella nuova ha solo il giovedì), accadde oggi (partita più importante della data dal 1999: turno di playoff, punti,
  supplementari, finale punto a punto).
- `scripts/home_college.py` (workflow College) → `docs/home_college.json`: classifica CFP (prima che esca, AP) e FPI
  ESPN (playoff %, finale %), 2 richieste ESPN gratis; nomi delle squadre dall'id nel logo. Il 22/11 era passato a
  CollegeFootballData + rating PureStats, ma la chiave CFBD esaurita fermava gli aggiornamenti: il 23/11 Valerio ha
  deciso di tornare a ESPN per tutti i dati college («il sito non ha ancora AdSense»); il rating PureStats resta nella
  storia git (commit d32ae69) se servirà.
- TV in Italia (`scripts/tv_italia.py`, workflow NFL) → `docs/tv_italia.json`. Tutte le partite NFL con NFL Game Pass su
  DAZN (bollino DAZN); cinque a settimana incluse anche negli abbonamenti DAZN Sports, Full e Family (conferma di Valerio,
  abbonato): Thursday Night, una delle 19:00, una delle 22:05/22:25, Sunday Night, Monday Night. Le partite con il via tra
  00:30 e 04:30 italiane sono incluse per regola; le due della domenica dall'articolo settimanale di DAZN Italia «… cinque
  partite da non perdere della Week N in ogni fascia oraria» (elenco notizie NFL Game Pass, robots.txt permette
  /it-IT/news; titoletti «X vs. Y» seguiti da «Kick-off Italia»), se manca dalle anteprime «… diretta su DAZN». Ogni
  articolo si legge una volta (`letti`). Prime Video non trasmette la NFL in Italia: nessun bollino.
- Da controllare: se l'articolo DAZN delle cinque partite esce ogni settimana (trovato per la Week 11). Se manca spesso,
  riserva da fare: comando nel bot per segnarle a mano (serve un token GitHub nel config.toml del server).

## Stemmi, highlights e crediti delle foto (dal 22/11/2026, scelta di Valerio)

- Nessun logo ufficiale nel sito (marchi delle squadre): `stemma()` in index.html e duelli.html disegna lo stemma
  PureStats «opzione B, pastiglia a due toni» (scelta di Valerio il 22/11, dopo la C: cerchio nel colore principale,
  spicchio in basso a destra e anello nel secondo colore, sigla in Barlow Condensed; clipPath con id unico STEMMA_N). Sigle e colori in `docs/stemmi.json` da `scripts/stemmi.py` (workflow stemmi.yml: a mano e il 1° agosto rifà tutto; quando
  cambia lo script e ogni lunedì chiama CFBD solo se le sigle college non vengono ancora da lì, `fonteCollege`):
  NFL da nflverse, college dall'elenco squadre ESPN (2 richieste gratis, dal 23/11), riserva CollegeFootballData /teams. Errori dell'ultimo giro in
  `ultimiErrori` dentro stemmi.json (i log dei workflow non si leggono da fuori). Squadre che mancano: sigla dalle
  iniziali del nome, banda bianca. I campi `logo` nei dati restano ma il sito non li usa.
- Highlights senza anteprima (niente fotogrammi NFL da i.ytimg.com): bottone `bottoneHighlights` che apre YouTube.
- Foto degli stadi: crediti completi in `docs/articoli/stadi/crediti.json` (autore, licenza, licenzaUrl, file, pagina
  Commons); `creditoFoto` li mostra nella copertina e in fondo all'articolo (con collegamenti) e sulle copertine della
  Home (testo). `articoli.py foto_mancanti` scrive già il formato completo e `completa_crediti` aggiorna quelli vecchi
  in testo (stessa voce Wikipedia; se l'autore non coincide lo segnala «ATTENZIONE» e non tocca nulla).

## Pubblico e privato: fonti separate (22/11/2026, scelta di Valerio)

- Parte privata (Matchup, Charlie, bot Radar Assenze): resta su ESPN (mercato.py, contesto.py, fetch_duelli.py,
  tabellini per chiudere le giocate). È cifrata o sul server: va bene così.
- Parte pubblica (pagine del sito in chiaro): solo fonti che ne permettono la ripubblicazione (nflverse,
  CollegeFootballData, Wikimedia, calcoli nostri). Quando si sposta il college pubblico da ESPN, ESPN continua ad
  alimentare la parte cifrata e il bot.
- Matchup usa anche lui gli stemmi PureStats (Valerio: «lascia così»).

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
  file, Chart.js e caratteri ospitati sul sito (docs/vendor, docs/font: niente CDN esterni). Va servita così com'è da GitHub Pages.
- **Niente localStorage** nella dashboard, tranne la chiave dell'accesso privato (`purestats_accesso`) e la scelta
  del tema (`purestats_tema`, «chiaro»/«scuro», dal 22/11/2026, citata nella pagina privacy).

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

- 22/11/2026: la Giornata del college era vuota (week 14, 3 partite da giocare). Causa: fetch_college conservava il
  punteggio già in archivio con la chiave (tipo, casa, ospite), ma nel Pac-12 a 8 squadre la stessa partita si gioca due
  volte: il risultato della prima finiva sulla seconda, futura, e la Giornata prendeva la week più alta con un risultato.
  Da allora la chiave ha anche la data, nessun risultato copiato su una partita futura, e `college_indici.calcola` sceglie
  l'ultima week con almeno metà delle partite giocate.

## Stato attuale

- Premier League: funzionante, con arbitri
- Serie A: funzionante per le statistiche di squadra; gli arbitri
  dipendono dall'inserimento manuale delle designazioni
- Cartellini per singolo giocatore: non disponibili in nessuno dei due
  campionati con le fonti attuali

## Da controllare

- IN CANTIERE (21/11/2026, Valerio: «ne riparliamo più in là»): apertura al pubblico, Google e monetizzazione onesta
  (solo traffico e Google AdSense; mai scommesse, mai affiliazioni, niente scorciatoie). Verifica fatta il 21/11, rischi
  in ordine:
  1. Dati ESPN pubblicati (college quasi tutto, FPI e percentuali playoff, classifiche, loghi dal CDN ESPN): le
     condizioni Disney/ESPN vietano accesso automatico, uso commerciale e ripubblicazione. Sostituto: CollegeFootballData
     (uso commerciale consentito anche con pubblicità; quota 1.000 chiamate/mese condivisa col bot: stima 200-250 al mese
     in stagione + circa 250 una tantum per lo storico, da ricontare prima di lanciare). DECISO il 23/11 (Valerio): per
     ora tutti i dati college restano su ESPN, compresi classifica e FPI; loghi no (restano gli stemmi PureStats).
     Da riprendere prima di AdSense. La sentinella college oggi interroga ESPN ogni 15 minuti: con CFBD aggiornamenti a orari
     stimati + riserve. Charlie e bot usano ESPN in privato (rischio solo blocco): decidere se spostarli.
  2. FATTO il 22/11: pagine pubbliche senza termini da scommesse. In index.html linee, totali, over/under, «Favorite
     oltre la linea», Sorprese e «Contro la linea» delle cronache si vedono solo con l'accesso privato (`privato()`);
     la Giornata pubblica mostra partite, punti a partita, partite decise da 8 punti o meno, vittoria più larga.
     Articoli e racconti riscritti senza «mercato americano»/bookmaker/punti di vantaggio; `articoli.controlla` e
     `pagine_statiche.py` rifiutano quei termini (ARTICOLI_GUIDA aggiornata). Nei racconti: «partono favoriti», mai
     i punti di vantaggio. I dati grezzi (linee nei JSON pubblici) restano: da spostare con il college (punto 1).
  3. FATTO il 22/11: loghi sostituiti dagli stemmi PureStats (vedi «Stemmi, highlights e crediti»).
  4. FATTO il 22/11: crediti completi delle foto degli stadi (autore, licenza con collegamento, pagina Commons).
  5. Privacy: FATTO il 22/11 caratteri e Chart.js sul sito (docs/font/font.css + woff2 latin/latin-ext da @fontsource,
     docs/vendor/chart.umd.min.js 4.4.1 con integrity; li scrive il workflow risorse-locali.yml con
     scripts/risorse_locali.py, da rilanciare solo se cambiano caratteri o versione: se cambia Chart.js aggiornare
     l'integrity in index.html da docs/vendor/integrita.json). index, duelli e accesso non chiamano più server esterni;
     anteprime YouTube e loghi ESPN già tolti. Pagina privacy FATTA il 22/11: `docs/privacy.html` (titolare Valerio
     La Rocca, info@purestats.it, casella Zimbra OVH), collegata dal piede di index.html, delle pagine statiche e della
     404, in sitemap. Da aggiornare PRIMA di aggiungere pubblicità o statistiche (oggi dice: niente cookie, analisi,
     pubblicità). Resta: banner di consenso certificato prima di AdSense.
  6. FATTO il 22/11: nflverse-data è CC BY 4.0 (LICENSE.md letto; nflreadr: «NFL data ... belong to their respective
     owners»); FTN è CC-BY-SA ma non lo usiamo, PFR/NGS/QBR senza licenza (PFR solo nel privato). Footer corretto.
  7. DECISO il 22/11 (Valerio: «restano, non creano problemi»): bollini DAZN letti in automatico come oggi, anche con
     la pubblicità (condizioni lette: uso «personale e non commerciale», nessun divieto di robot).
  8. DECISO il 22/11: i vecchi dati del calcio restano nella storia git (in chiaro fino al 17/11, medie da CSV pubblici).
  FATTO il 25/11: pagine statiche NFL (Chi siamo, archivio, week, squadre, classifica, calendario; college a dicembre).
  In attesa (Valerio: «aspetta», 22/11): GoatCounter; commercialista prima dei dati di pagamento AdSense (lo fa Valerio). Piano nel documento
  https://claude.ai/artifact/UBgHBMkY3GmWwFTGFMd4Xa
  Altro emerso: titolo della pagina «PureStats · Premier League» e descrizione che cita calcio/linee/arbitri (da
  correggere per vista); articoli e racconti con indirizzi #… non indicizzabili da Google (servono pagine HTML statiche
  per ogni articolo e racconto, sitemap.xml, robots.txt, 404, Search Console); AdSense richiede un dominio proprio
  (non *.github.io): Valerio lo compra, Claude prepara la configurazione DNS; password di Matchup lunga (14+ caratteri),
  perché i file cifrati sono pubblici. Nessun errore JavaScript né file mancante nelle viste (controllo del 21/11).
  Ordine proposto: messa in regola → Google (pagine statiche, sitemap) → dominio → AdSense con traffico.


- Dicembre 2026, rinunce ai bowl: i titolari si contano sull'intera stagione (Protocollo 12), quindi una squadra
  che ha cambiato QB a metà anno ha ancora il vecchio come titolare (Rice: Jacurri Brown, ora ricevitore; gioca
  Gael Ochoa). Prima di spuntare le rinunce, controllare a mano le squadre che hanno cambiato QB.

## Da fare da sabato 21/11/2026 (dopo il rinnovo dell'abbonamento, ore 5)

1. Sezione «LEGGENDE»: struttura, classifiche, «Mai battuto» e i primi 3 racconti fatti il 21/11 (vedi sopra); restano gli
   altri racconti e il college. (nome scelto al posto di «Hall of Fame», marchio del museo di Canton), stile del template
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
2. Ogni fatto e record va riverificato prima di pubblicare (stesso metodo degli articoli).
