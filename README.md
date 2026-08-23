FootballStats
Dashboard statistiche calcio per Serie A, Premier League, Ligue 1, LaLiga e Bundesliga.
I dati si aggiornano da soli tramite GitHub Actions: nessun copia-incolla manuale.
Come funziona
Codice
Setup in 5 passi
1. Ottieni la chiave API
Registrati su api-football.com (piano gratuito, nessuna carta
richiesta) e copia la chiave dalla dashboard. Il piano gratuito dà 100 richieste al giorno,
più che sufficienti: lo script ne usa circa 35 per esecuzione.
2. Crea il repository
Carica questi file in un nuovo repository GitHub (può essere privato).
3. Salva la chiave come Secret
Nel repository: Settings → Secrets and variables → Actions → New repository secret
Name: API_FOOTBALL_KEY
Secret: la tua chiave
La chiave non va mai scritta nei file del repository. Il workflow la legge dai Secrets,
dove resta cifrata e invisibile anche nei log.
4. Attiva GitHub Pages
Settings → Pages → Source: Deploy from a branch → Branch: main, cartella /docs
Dopo un minuto la dashboard sarà su https://<tuo-utente>.github.io/<nome-repo>/
5. Lancia il primo aggiornamento
Actions → Aggiorna dati calcio → Run workflow
Controlla i log: se vedi errori 403 o "Nessun dato recuperato", il piano gratuito
non copre la stagione richiesta (vedi sotto).
Se la stagione corrente non è disponibile
Il piano gratuito di API-Football limita le stagioni accessibili. Per verificare:
Bash
Se la stagione corrente non è inclusa, puoi lavorare su una stagione precedente
modificando la variabile STAGIONE nel workflow:
Yaml
Configurazione
Variabili d'ambiente impostabili nel workflow:
Variabile
Default
Cosa fa
STAGIONE
anno corrente
Stagione da scaricare
MAX_CHIAMATE
90
Tetto di sicurezza sulle chiamate API
MAX_DETTAGLIO
3
Partite per campionato da arricchire con eventi e statistiche
Alzare MAX_DETTAGLIO dà più dati ma consuma più quota: ogni partita arricchita
costa 2 chiamate (statistiche + eventi).
Frequenza di aggiornamento
Il cron è impostato su 0 6,23 * * * (08:00 e 01:00 ora italiana). Per cambiarlo,
modifica .github/workflows/update-data.yml. Puoi sempre lanciare un aggiornamento
manuale dal tab Actions.
Nota: GitHub sospende i workflow schedulati nei repository pubblici inattivi da 60 giorni.
Basta un commit qualsiasi per riattivarli.
Struttura
Codice
Fonte dati
API-Football di API-Sports. Verifica i loro termini
di servizio per l'uso che intendi farne, in particolare se pubblichi il sito.
