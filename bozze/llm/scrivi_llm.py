"""Prova alla cieca: gli stessi 10 articoli scritti da modelli diversi, con controllo dei fatti.

Gira in GitHub Actions (le chiavi stanno nei secret). Solo libreria standard.
Uso: python3 bozze/llm/scrivi_llm.py <scrittore>   (es. groq:openai/gpt-oss-120b, github:openai/gpt-4.1)
"""
import json, os, re, sys, time, urllib.request, urllib.error, datetime

QUI = os.path.dirname(os.path.abspath(__file__))
# chi controlla chi: ogni scrittore ha un caporedattore diverso da sé, per stare nei limiti giornalieri gratuiti di Groq
VERIFICATORE = {"groq:openai/gpt-oss-120b": "groq:qwen/qwen3.8-27b", "groq:qwen/qwen3.8-27b": "groq:openai/gpt-oss-120b",
                "ollama:gemma3:12b": "groq:openai/gpt-oss-120b"}
ENDPOINT = {"groq": "https://api.groq.com/openai/v1/chat/completions", "ollama": "http://localhost:11434/api/chat"}
CHIAVE = {"groq": os.environ.get("GROQ_API_KEY", ""), "ollama": ""}
REGISTRO = []


def log(*a):
    riga = " ".join(str(x) for x in a)
    print(riga, flush=True)
    REGISTRO.append(riga)


def chiama(modello, messaggi, temperatura=0.8, max_token=1800):
    fornitore, nome = modello.split(":", 1)
    if fornitore == "ollama":
        corpo = {"model": nome, "messages": messaggi, "stream": False, "format": "json",
                 "options": {"temperature": temperatura, "num_ctx": 12288, "num_predict": 1500}}
    else:
        corpo = {"model": nome, "messages": messaggi, "temperature": temperatura, "max_tokens": max_token,
                 "response_format": {"type": "json_object"}}
    if fornitore == "groq" and "gpt-oss" in nome:
        corpo["reasoning_effort"] = "low"
    for tentativo in range(8):
        req = urllib.request.Request(ENDPOINT[fornitore], data=json.dumps(corpo).encode(),
                                     headers={"Authorization": f"Bearer {CHIAVE[fornitore]}", "Content-Type": "application/json",
                                              "User-Agent": "PureStats/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=1800) as r:
                dati = json.loads(r.read())
                if fornitore == "ollama":
                    return dati["message"]["content"], {"prompt": dati.get("prompt_eval_count"), "risposta": dati.get("eval_count")}
                limiti = {k: v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
                if tentativo == 0 and limiti:
                    log("   limiti", modello, json.dumps(limiti))
                uso = dati.get("usage", {})
                return dati["choices"][0]["message"]["content"] or "", uso
        except urllib.error.HTTPError as e:
            testo = e.read().decode(errors="replace")[:400]
            attesa = float(e.headers.get("retry-after") or 0) or 20 * (tentativo + 1)
            log(f"   {modello}: errore {e.code} ({testo[:160]}), riprovo tra {attesa:.0f}s")
            if e.code == 400 and "response_format" in corpo:
                corpo.pop("response_format")   # alcuni modelli non accettano la modalità JSON: si riprova senza
                continue
            if e.code in (400, 401, 403, 404):
                raise
            time.sleep(min(attesa + 1, 120))
        except Exception as e:
            log(f"   {modello}: errore di rete {e}, riprovo")
            time.sleep(15)
    raise RuntimeError(f"{modello}: troppi tentativi falliti")


def estrai_json(testo):
    testo = re.sub(r"<think>.*?</think>", "", testo or "", flags=re.S)
    i = testo.find("{")
    if i < 0:
        raise ValueError("nessun JSON nella risposta")
    oggetto, _ = json.JSONDecoder().raw_decode(testo[i:])
    return oggetto


GUIDA = """Sei un giornalista sportivo italiano: scrivi di football americano (NFL) per PureStats.
Ricevi i FATTI della partita (frasi già verificate) e alcuni SPUNTI. Con questi scrivi un articolo originale,
in italiano giornalistico naturale, come un buon quotidiano sportivo.

LA REGOLA PIÙ IMPORTANTE
- Ogni informazione dell'articolo deve venire dai FATTI o dagli SPUNTI. Non aggiungere niente che non ci sia:
  niente cause, motivazioni, citazioni, stati d'animo, pubblico, atmosfera, infortuni, storia, statistiche, record,
  classifiche, meteo, dettagli di gioco. Se ti sembra che manchi qualcosa, non inventarlo: scegli un altro angolo.
- Puoi scegliere quali fatti usare (non serve usarli tutti), metterli nell'ordine che rende meglio la storia,
  unirli, riassumerli e dirli con parole tue. Non cambiare il significato e non attribuire giocate alla squadra sbagliata.

NUMERI
- Usa solo numeri presenti nei fatti: punteggi, bilanci (4-6), data e ora. Non serve citare ogni punteggio parziale:
  scegli quelli che contano per il racconto.

STILE
- Apertura sempre diversa: scegli l'angolo più interessante tra gli spunti (una storia, un contrasto, un momento)
  e parti da lì. Evita di cominciare con «I X battono i Y» o «I X e i Y si affrontano».
- Frasi di lunghezza varia, lessico preciso, ritmo da cronaca giornalistica. Nessun punto esclamativo, nessuna domanda
  retorica, nessuna iperbole, nessun cliché («al cardiopalma», «cuore oltre l'ostacolo», «notte magica»).
- Squadre al plurale maschile: «i Chargers», «dei Ravens», «ai 49ers». Prima citazione di una persona: nome e cognome;
  poi solo il cognome. Termini: touchdown, field goal, end zone, quarterback, running back, sack, intercetto, fumble,
  division, playoff. Mai «iarde»: si dice «yard». Mai «match»: si dice «partita».
- Il mercato solo a parole («favoriti di poco»), mai quote o consigli di scommessa.

RISPOSTA: solo un oggetto JSON: {"titolo": "...", "paragrafi": ["...", "..."]}
Titolo: al massimo 12 parole, informativo, senza virgolette."""

COMPITO = {
    "anteprima": "Scrivi l'ANTEPRIMA (prima del calcio d'inizio). 200-280 parole in 4 paragrafi. "
                 "Nel primo paragrafo devono esserci quando (ora italiana), dove e i bilanci.",
    "cronaca": "Scrivi la CRONACA della partita appena finita. 230-320 parole in 4-5 paragrafi. "
               "Nel primo paragrafo il risultato e perché conta; poi la partita raccontata nei suoi momenti chiave "
               "(non un elenco di tutte le segnature); poi i protagonisti; chiudi con bilanci e prossimo turno.",
}

VERIFICA = """Sei il caporedattore. Hai i FATTI e gli SPUNTI (l'unica fonte ammessa) e l'ARTICOLO da pubblicare. Trova solo problemi veri:
1. "fatto": un'affermazione che non è nei fatti/spunti o li contraddice (fatti inventati, cause, atmosfera, statistiche,
   giocate attribuite alla squadra sbagliata, punteggi o momenti sbagliati, ordine degli eventi sbagliato).
   Riassunti e parafrasi fedeli NON sono problemi.
2. "lingua": errori di italiano (grammatica, articoli, concordanze, refusi, frasi poco chiare, anglicismi sbagliati come «iarde»).
3. "regole": quote o consigli di scommessa, probabilità.
Rispondi solo con un oggetto JSON: {"problemi": [{"tipo": "fatto|lingua|regole", "frase": "testo esatto", "motivo": "..."}]}
Se l'articolo è corretto: {"problemi": []}"""


def compatto(m):
    """I fatti e gli spunti come elenco puntato."""
    if "fatti" in m:
        return ("PARTITA: " + m["partita"] + "\nFATTI:\n" + "\n".join("- " + f for f in m["fatti"])
                + "\nSPUNTI:\n" + "\n".join("- " + f for f in m["spunti"]))
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


PAROLE_OK = {"NFL", "AFC", "NFC", "Super", "Bowl", "PureStats", "East", "West", "North", "South", "Week", "Pro",
             "Los", "Angeles", "New", "York", "England", "Orleans", "San", "Francisco", "Baltimore", "Washington", "Detroit",
             "Dallas", "Carolina", "Arizona", "Monaco", "Baviera", "Baltimora", "Arlington", "East", "Rutherford"}


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
           {"role": "user", "content": COMPITO[tipo] + "\n\n" + compatto(m)}]
    testo, uso = chiama(modello, msg)
    return estrai_json(testo), msg, testo, uso


def verifica(art, m, scrittore):
    msg = [{"role": "system", "content": VERIFICA},
           {"role": "user", "content": compatto(m) + "\n\nARTICOLO:\n" + json.dumps(art, ensure_ascii=False)}]
    testo, _ = chiama(VERIFICATORE[scrittore], msg, temperatura=0.1, max_token=1500)
    return estrai_json(testo).get("problemi", [])


def correggi(modello, msg, risposta, problemi):
    msg = msg + [{"role": "assistant", "content": risposta},
                 {"role": "user", "content": "Il caporedattore ha trovato questi problemi:\n" + json.dumps(problemi, ensure_ascii=False)
                  + "\nRiscrivi l'articolo correggendo solo questi punti (togli ciò che non è nel materiale). Stesso formato JSON."}]
    testo, uso = chiama(modello, msg, temperatura=0.4)
    return estrai_json(testo)


def main():
    scrittore = sys.argv[1]
    materiale = json.load(open(os.path.join(QUI, "fatti.json")))
    risultati = {}
    for gid, v in materiale.items():
        for tipo in ("anteprima", "cronaca"):
            m = v[tipo]
            inizio = time.time()
            voce = {"scrittore": scrittore}
            try:
                art, msg, grezzo, uso = scrivi(scrittore, m, tipo)
                prob = controllo_meccanico(art, m) + verifica(art, m, scrittore)
                voce["problemiPrimaStesura"] = prob
                gravi = [p for p in prob if p.get("tipo") in ("fatto", "lingua", "regole")]
                if gravi:
                    art2 = correggi(scrittore, msg, grezzo, gravi)
                    prob2 = controllo_meccanico(art2, m) + verifica(art2, m, scrittore)
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
