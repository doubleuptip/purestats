# Articoli PureStats: guida per chi scrive (Claude)

Gli articoli li scrive Claude, uno per uno, partendo SOLO dai fatti preparati dallo script.
Ogni settimana: 3 partite NFL e 3 college, anteprima prima del via e cronaca dopo.

## Procedura per una partita
1. `python3 scripts/articoli.py fatti <game_id>` → `data/articoli/fatti_<game_id>.json`
2. Leggere TUTTO il file dei fatti. Scrivere il testo in `data/articoli/bozza_<game_id>_<tipo>.json`
   nel formato `{"titolo": "...", "paragrafi": ["...", "..."]}`.
3. `python3 scripts/articoli.py pubblica <game_id> <tipo> data/articoli/bozza_<game_id>_<tipo>.json`
   Il controllo rifiuta numeri e nomi che non sono nei fatti: correggere il testo, mai i fatti.
4. Controllo di realtà (Valerio, 19/11/2026: «servono dati sempre veri e confermati»): con una ricerca web verificare
   che cessioni, arrivi, quarterback titolare e assenze citati siano confermati da fonti giornalistiche recenti, e che
   non manchi un movimento importante. Se i dati nflverse sono indietro o in contrasto, NON pubblicare quella frase:
   toglierla o aspettare l'aggiornamento, e segnalarlo a Valerio nel riepilogo.
5. Rileggere il testo da caporedattore (fatti, italiano, regole sotto), poi commit e push su main.
   Il meteo lo aggiorna da solo il workflow «Articoli - meteo delle anteprime».

## Cosa raccontare (indicazioni di Valerio, 18/11/2026)
- Si parte dall'ATTUALITÀ: come stanno andando le squadre, momento positivo o negativo, chi cerca riscatto,
  cosa è cambiato con un'assenza (es. una squadra crollata da quando manca il quarterback titolare),
  giocatori in calo o in crescita rispetto all'anno scorso, l'età quando spiega un calo.
- Cessioni e arrivi della stagione («cedutiInStagione», «arrivatiInStagione») fanno parte dell'attualità: una squadra
  che smobilita o che si rinforza è una notizia. I giocatori ceduti non compaiono più tra i giocatori della vecchia squadra.
- Curiosità (parentele, ex) solo se toccano davvero la partita. Mai come apertura.
- Ogni giudizio deve poggiare su un dato dei fatti (es. «in netto calo rispetto all'anno scorso», «primo nella lega per sack»).
  Niente opinioni a sensazione («non può fare miracoli»).
- Testo armonioso, che non sembri scritto da un'intelligenza artificiale: paragrafi collegati, frasi di lunghezza varia,
  nessuno schema fisso, nessun elenco travestito da frase.

## Regole fisse
- Solo fatti presenti nel file: niente cause, citazioni, atmosfera, storia, statistiche o meteo inventati.
- Numeri: punteggi, bilanci, data e ora; al massimo un paio di altri se rendono la storia. Le statistiche stanno nel riquadro.
- Mercato solo a parole («nettamente favoriti», «favoriti di poco»), mai quote né consigli di scommessa.
  Mai segnali di Charlie o della sezione privata.
- Squadre al plurale maschile («i Texans»); prima citazione nome e cognome, poi il cognome; yard (mai iarde);
  «partita» (mai match); niente punti esclamativi, domande retoriche, cliché.
- Rapporto infortuni: dire solo ciò che dice il rapporto (stato ufficiale, o «non si è allenato» se lo stato non c'è ancora).
- Anteprima 220-300 parole in 4 paragrafi; cronaca 230-320 parole in 4-5 paragrafi.
