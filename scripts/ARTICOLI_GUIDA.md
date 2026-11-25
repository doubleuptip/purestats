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

## Lavoro del giorno (attività programmata, dal 21/11/2026)
- `python3 scripts/articoli.py da_fare` dice cosa scrivere oggi: anteprime delle partite scelte che iniziano entro 48 ore
  e cronache delle partite scelte già finite. Le partite scelte (3 NFL e 3 college a settimana) si calcolano una volta,
  a ridosso della settimana, e restano in `data/articoli/scelte_<lega>_<stagione>_<week>.json`.
- College: i fatti si preparano con `fatti_college <stagione> <week> "<ospite>" "<casa>"` (comando già scritto in da_fare);
  l'id dell'articolo è quello di da_fare (spazi e simboli diventano «-»).
- Prima di scrivere, cercare sul web le notizie della vigilia (o del dopo partita): infortuni con lo stato ufficiale,
  quarterback titolare, scambi, allenatore, orario spostato dalla tv, sede particolare. Quello che serve al racconto va in
  `data/articoli/notizie_<id>.json` = [{"fatto": "...", "fonte": "https://..."}] (una fonte per ogni fatto, sennò
  `pubblica` si ferma). Orari spostati e città: `data/articoli/correzioni_<id>.json` = {"inizioEt": "AAAA-MM-GGTHH:MM",
  "citta": "...", "fonte": "https://..."}, poi rifare `fatti`.
- Se nflverse non ha ancora il play-by-play (o ESPN il tabellino del college), `fatti` lo dice: quella cronaca si
  rimanda al giorno dopo, senza inventare nulla.

## Aggiornamenti delle anteprime (dal 25/11/2026, scelta di Valerio)
- `da_fare` elenca anche le voci di tipo «aggiornamento»: anteprime già pubblicate di partite non ancora iniziate
  (mancano più di 2 ore) controllate l'ultima volta più di 18 ore fa.
- Per ognuna: rifare `fatti`, cercare sul web le novità dalla prima pubblicazione (soprattutto rapporto infortuni
  ufficiale con lo stato finale: Out, Doubtful, Questionable, Inattivo; QB titolare; orario o sede cambiati).
  - Nessuna novità che cambi il racconto: `python3 scripts/articoli.py controllato <id>_anteprima` (annota solo l'ora
    del controllo, il sito non mostra niente). Non riscrivere l'articolo per cambiare solo parole.
  - Novità vere: aggiungere i fatti nuovi con la fonte a `notizie_<id>.json`, correggere il testo dove serve (le frasi
    superate vanno riscritte, non lasciate in contraddizione) e mettere nella bozza il campo
    `"aggiornamento": "una o due frasi su cosa è cambiato"` (massimo 300 caratteri, stessi controlli del testo). Poi
    `pubblica <id> anteprima <bozza>`: resta la data della prima pubblicazione, si aggiungono data e ora
    dell'aggiornamento, la nota in cima al testo e la versione precedente consultabile in fondo.
- Senza il campo «aggiornamento» `pubblica` rifiuta di riscrivere un articolo già pubblicato.
- Nel testo non promettere aggiornamenti futuri («se arriveranno novità le scriveremo»): l'aggiornamento, se serve,
  arriva e si vede dalla data.

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
- Niente scommesse (22/11/2026, sito pubblico per Google): mai «mercato americano», bookmaker, linee, totali, over/under,
  quote, pronostici o l'esito «contro la linea» delle cronache. Chi parte favorito si può dire con parole comuni
  («partono favoriti», «nettamente favoriti», «favoriti di poco»), senza citarne la fonte. `pubblica` rifiuta i termini vietati.
  Mai segnali di Charlie o della sezione privata.
- Squadre al plurale maschile («i Texans»); prima citazione nome e cognome, poi il cognome; yard (mai iarde);
  «partita» (mai match); niente punti esclamativi, domande retoriche, cliché.
- Meteo nel testo solo se conta davvero (all'aperto, con pioggia, vento forte o freddo). Mai frasi come «il meteo non conta»
  o «si gioca al coperto»: la scheda meteo accanto all'articolo dice già tutto.
- Rapporto infortuni: dire solo ciò che dice il rapporto (stato ufficiale, o «non si è allenato» se lo stato non c'è ancora).
- Anteprima 220-300 parole in 4 paragrafi; cronaca 230-320 parole in 4-5 paragrafi.
- Cronaca: si scrive dal blocco «partitaGiocata» dei fatti (marcature, momenti decisivi, protagonisti, numeri) e dal
  contesto della vigilia (assenze, scambi, andata). Apertura sul risultato e su cosa significa; poi come si è decisa,
  con i protagonisti per nome e cognome alla prima citazione; le assenze solo se hanno pesato; in chiusura dove lascia
  le due squadre. Numeri nel testo pochi (punteggi, bilanci, un paio al massimo): il resto è nel riquadro.
