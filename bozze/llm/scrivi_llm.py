"""Prova alla cieca: gli stessi 10 articoli scritti da modelli diversi, con controllo dei fatti.

Gira in GitHub Actions (le chiavi stanno nei secret). Solo libreria standard.
Uso: python3 bozze/llm/scrivi_llm.py <scrittore>   (es. groq:openai/gpt-oss-120b, github:openai/gpt-4.1)
"""
import json, os, re, sys, time, urllib.request, urllib.error, datetime

QUI = os.path.dirname(os.path.abspath(__file__))
VERIFICATORE = "github:openai/gpt-4.1-mini"
ENDPOINT = {"groq": "https://api.groq.com/openai/v1/chat/completions",
            "github": "https://models.github.ai/inference/chat/completions"}
CHIAVE = {"groq": os.environ.get("GROQ_API_KEY", ""), "github": os.environ.get("GITHUB_TOKEN", "")}
REGISTRO = []


def log(*a):
    riga = " ".join(str(x) for x in a)
    print(riga, flush=True)
    REGISTRO.append(riga)


def chiama(modello, messaggi, temperatura=0.8, max_token=2500):
    fornitore, nome = modello.split(":", 1)
    corpo = {"model": nome, "messages": messaggi, "temperature": temperatura, "max_tokens": max_token}
    if fornitore == "groq" and "gpt-oss" in nome:
        corpo["reasoning_effort"] = "medium"
    for tentativo in range(8):
        req = urllib.request.Request(ENDPOINT[fornitore], data=json.dumps(corpo).encode(),
                                     headers={"Authorization": f"Bearer {CHIAVE[fornitore]}", "Content-Type": "application/json",
                                              "User-Agent": "PureStats/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                dati = json.loads(r.read())
                limiti = {k: v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
                if tentativo == 0 and limiti:
                    log("   limiti", modello, json.dumps(limiti))
                uso = dati.get("usage", {})
                return dati["choices"][0]["message"]["content"] or "", uso
        except urllib.error.HTTPError as e:
            testo = e.read().decode(errors="replace")[:400]
            attesa = float(e.headers.get("retry-after") or 0) or 20 * (tentativo + 1)
            log(f"   {modello}: errore {e.code} ({testo[:160]}), riprovo tra {attesa:.0f}s")
            if e.code in (400, 401, 403, 404):
                raise
            time.sleep(min(attesa + 1, 120))
        except Exception as e:
            log(f"   {modello}: errore di rete {e}, riprovo")
            time.sleep(15)
    raise RuntimeError(f"{modello}: troppi tentativi falliti")


def estrai_json(testo):
    testo = re.sub(r"<think>.*?</think>", "", testo, flags=re.S)
    m = re.search(r"\{.*\}", testo, re.S)
    if not m:
        raise ValueError("nessun JSON nella risposta")
    return json.loads(m.group(0))


GUIDA = """Sei un giornalista sportivo italiano: scrivi di football americano (NFL) per PureStats, un sito di statistiche.
Scrivi in italiano giornalistico naturale, come un buon quotidiano sportivo: frasi di lunghezza varia, lessico preciso,
nessuna formula ripetitiva, nessun punto esclamativo, nessuna domanda retorica, nessuna iperbole.

REGOLE SUI FATTI (le più importanti)
- Usa SOLO i fatti presenti nel MATERIALE. Non aggiungere nulla che non sia scritto lì: niente cause, motivazioni,
  citazioni, dichiarazioni, stati d'animo, pubblico, infortuni, storia, record, classifiche o meteo che il materiale non contiene.
- Se un fatto non c'è, non scriverlo, anche se ti sembra probabile o lo conosci per conto tuo.
- Non confondere le squadre: controlla sempre per chi gioca ogni giocatore.
- "descrizioneUfficiale" è la cronaca ufficiale in inglese: traducila e raccontala a parole tue, senza copiarla.
- "probVittoria..." serve solo a capire quanto pesa una giocata: non citare mai probabilità o percentuali.

NUMERI
- Nel testo usa solo: punteggi, bilanci (es. 4-6), data e ora. In tutto l'articolo al massimo altri 2 numeri,
  solo se rendono la storia (es. la distanza del field goal decisivo). Mai elenchi di statistiche: i numeri dei giocatori
  sono già nel riquadro accanto all'articolo.
- Il mercato (favorita, vantaggio previsto, totale) va detto solo a parole: "favoriti di poco", "nettamente favoriti",
  "ci si aspetta una partita con pochi punti". Mai consigli di scommessa, mai quote.

LINGUA
- Squadre al plurale maschile: «i Chargers», «dei Ravens», «ai 49ers». Città: Baltimora, Filadelfia, Monaco di Baviera;
  le altre col nome originale.
- Termini: touchdown, field goal, end zone, quarterback, running back, ricevitore, sack, intercetto, fumble, punt, drive,
  division, playoff, supplementari. Niente anglicismi inutili oltre a questi.
- Prima volta che citi un giocatore o un allenatore: nome e cognome. Poi solo il cognome.
- Ore: «alle 2:15 italiane». Giorni e mesi in minuscolo.

COME SCEGLIERE LA STORIA
- Leggi gli "spunti": scegli l'angolo più interessante e costruisci l'articolo intorno a quello, usandone almeno due.
- Ogni articolo deve avere un'apertura sua: non cominciare sempre con «I X battono i Y» o «I X e i Y si affrontano».
- Niente frasi fatte come «al cardiopalma», «cuore oltre l'ostacolo», «notte magica», «da incorniciare».

RISPOSTA: solo un oggetto JSON, senza altro testo: {"titolo": "...", "paragrafi": ["...", "...", ...]}
Il titolo: al massimo 12 parole, informativo, senza virgolette."""

COMPITO = {
    "anteprima": """Scrivi l'ANTEPRIMA della partita (prima del calcio d'inizio: non sai come finirà).
Lunghezza: 220-300 parole in 4-5 paragrafi.
- Primo paragrafo: chi gioca, quando (ora italiana), dove, con i bilanci delle due squadre e le serie aperte.
- Poi come arriva ciascuna squadra: stagione scorsa, momento di forma, reparti, allenatore, se c'è una storia.
- Poi chi seguire e chi manca (usa i giudizi, non le cifre).
- Chiudi con la chiave della partita e il pronostico del mercato detto a parole.""",
    "cronaca": """Scrivi la CRONACA della partita appena finita.
Lunghezza: 250-340 parole in 4-6 paragrafi.
- Primo paragrafo: il risultato, dove, e perché conta (pronostico, serie, classifica, una storia degli spunti).
- Poi racconta la partita nell'ordine in cui è andata, attraverso le giocate decisive (traducendo la cronaca ufficiale):
  chi ha segnato, chi ha perso palla, dove è girata. Usa il tempo a parole («a poco più di due minuti dalla fine»).
- Poi i protagonisti, a parole (chi ha trascinato, chi ha deciso), senza cifre.
- Chiudi con le conseguenze: bilanci aggiornati e il prossimo turno.""",
}

VERIFICA = """Sei il caporedattore: controlli un articolo prima che venga pubblicato. Hai il MATERIALE (l'unica fonte ammessa)
e l'ARTICOLO. Trova solo problemi veri:
1. "fatto": affermazioni non presenti o non deducibili dal materiale (fatti inventati, cause, citazioni, infortuni,
   storia, meteo, statistiche, giocatori attribuiti alla squadra sbagliata, punteggi o tempi sbagliati, chi ha segnato).
   Le parafrasi e i giudizi che riassumono correttamente il materiale NON sono problemi.
2. "lingua": errori di italiano (grammatica, articoli, concordanze, refusi, frasi che non si capiscono).
3. "regole": elenchi di statistiche, più di 2 numeri oltre a punteggi/bilanci/data/ora, probabilità citate, consigli di scommessa.
Rispondi solo con un oggetto JSON: {"problemi": [{"tipo": "fatto|lingua|regole", "frase": "testo esatto", "motivo": "..."}]}
Se l'articolo è corretto: {"problemi": []}"""


def compatto(m):
    """Materiale senza campi vuoti e senza spazi, per stare nei limiti di token."""
    def pulisci(x):
        if isinstance(x, dict):
            return {k: pulisci(v) for k, v in x.items() if v not in ("", None, [], {}) and k not in ("coordinateStadio",)}
        if isinstance(x, list):
            return [pulisci(v) for v in x]
        return x
    return json.dumps(pulisci(m), ensure_ascii=False, separators=(",", ":"))


def numeri_ammessi(m):
    out = set()
    testo = json.dumps(m, ensure_ascii=False)
    for t in re.findall(r"\d+(?:[.,]\d+)?", testo):
        out.add(t); out.add(t.replace(".", ","))
        try:
            out.add(str(int(float(t.replace(",", ".")))))
        except ValueError:
            pass
    for t in re.findall(r"(\d+):(\d+)", testo):
        out.add(str(int(t[0])) + ":" + t[1])
    return out


PAROLE_OK = {"NFL", "AFC", "NFC", "Super", "Bowl", "PureStats", "East", "West", "North", "South", "Week", "Pro"}


def controllo_meccanico(art, m):
    """Ogni cifra e ogni nome proprio dell'articolo devono comparire nel materiale."""
    corpo = json.dumps(m, ensure_ascii=False)
    ok = numeri_ammessi(m)
    testo = art["titolo"] + "\n" + "\n".join(art["paragrafi"])
    problemi = []
    for t in re.findall(r"\d+(?:[.,]\d+)?(?::\d+)?", testo):
        base = t.split(":")[0]
        if t not in ok and base not in ok and t.replace(",", ".") not in ok:
            problemi.append({"tipo": "fatto", "frase": t, "motivo": "numero non presente nel materiale"})
    for frase in re.split(r"(?<=[.!?:;])\s+|\n", testo):
        parole = re.findall(r"[A-Za-zÀ-ÿ'’\.\-]+", frase)
        for i, p in enumerate(parole):
            p = p.strip(".'’-")
            if i == 0 or not p or not p[0].isupper() or p in PAROLE_OK:
                continue
            if p not in corpo and p.rstrip("s") not in corpo:
                problemi.append({"tipo": "fatto", "frase": p, "motivo": "nome non presente nel materiale"})
    return problemi


def scrivi(modello, m, tipo):
    msg = [{"role": "system", "content": GUIDA},
           {"role": "user", "content": COMPITO[tipo] + "\n\nMATERIALE:\n" + compatto(m)}]
    testo, uso = chiama(modello, msg)
    return estrai_json(testo), msg, testo, uso


def verifica(art, m):
    msg = [{"role": "system", "content": VERIFICA},
           {"role": "user", "content": "MATERIALE:\n" + compatto(m) + "\n\nARTICOLO:\n" + json.dumps(art, ensure_ascii=False)}]
    testo, _ = chiama(VERIFICATORE, msg, temperatura=0.1, max_token=3000)
    return estrai_json(testo).get("problemi", [])


def correggi(modello, msg, risposta, problemi):
    msg = msg + [{"role": "assistant", "content": risposta},
                 {"role": "user", "content": "Il caporedattore ha trovato questi problemi:\n" + json.dumps(problemi, ensure_ascii=False)
                  + "\nRiscrivi l'articolo correggendo solo questi punti (togli ciò che non è nel materiale). Stesso formato JSON."}]
    testo, uso = chiama(modello, msg, temperatura=0.4)
    return estrai_json(testo)


def main():
    scrittore = sys.argv[1]
    materiale = json.load(open(os.path.join(QUI, "materiale.json")))
    risultati = {}
    for gid, v in materiale.items():
        for tipo in ("anteprima", "cronaca"):
            m = v[tipo]
            inizio = time.time()
            voce = {"scrittore": scrittore}
            try:
                art, msg, grezzo, uso = scrivi(scrittore, m, tipo)
                prob = controllo_meccanico(art, m) + verifica(art, m)
                voce["problemiPrimaStesura"] = prob
                gravi = [p for p in prob if p.get("tipo") in ("fatto", "lingua", "regole")]
                if gravi:
                    art2 = correggi(scrittore, msg, grezzo, gravi)
                    prob2 = controllo_meccanico(art2, m) + verifica(art2, m)
                    voce["problemiDopoCorrezione"] = prob2
                    art = art2
                    prob = prob2
                voce["articolo"] = art
                voce["pubblicabile"] = not [p for p in prob if p.get("tipo") == "fatto"]
                voce["parole"] = sum(len(p.split()) for p in art["paragrafi"])
            except Exception as e:
                voce["errore"] = str(e)[:500]
            voce["secondi"] = round(time.time() - inizio)
            risultati[f"{gid}|{tipo}"] = voce
            log(f"{scrittore} {gid} {tipo}: {'ERRORE ' + voce['errore'] if 'errore' in voce else ('ok' if voce['pubblicabile'] else 'NON pubblicabile')}"
                f" · prima stesura {len(voce.get('problemiPrimaStesura', []))} problemi"
                f" · dopo {len(voce.get('problemiDopoCorrezione', [])) if 'problemiDopoCorrezione' in voce else '-'}")
            if "errore" in voce and ("404" in voce["errore"] or "401" in voce["errore"] or "403" in voce["errore"]):
                break
    nome = re.sub(r"[^A-Za-z0-9]+", "_", scrittore)
    os.makedirs(os.path.join(QUI, "esiti"), exist_ok=True)
    json.dump({"scrittore": scrittore, "quando": datetime.datetime.utcnow().isoformat(), "risultati": risultati, "registro": REGISTRO},
              open(os.path.join(QUI, "esiti", nome + ".json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
