"""
Interpretazione delle designazioni arbitrali di Serie A.

Le designazioni sono pubblicate come testo dalla Lega e dall'AIA in due
formati leggermente diversi:

  Lega:  PARMA – CAGLIARI (Venerdì 27/02 h. 20.45) MASSIMI (PRETI – BARONE)
         IV: COLLU, VAR: GIUA, AVAR: MAZZOLENI

  AIA:   INTER – MONZA Sabato 22/08 h. 18.30 MARINELLI DI GIOIA – PALERMO
         IV: DI MARCO VAR: GARIGLIO AVAR: MARINI

Questo modulo gestisce entrambi e restituisce dati strutturati.
Non fa richieste di rete: si limita a interpretare testo già scaricato,
così è collaudabile in isolamento.
"""

import re
import unicodedata

# Squadre di Serie A: come compaiono nelle designazioni -> nome normalizzato.
# Le designazioni usano il maiuscolo e abbreviazioni non uniformi.
SQUADRE = {
    "atalanta": "Atalanta",
    "bologna": "Bologna",
    "cagliari": "Cagliari",
    "como": "Como",
    "cremonese": "Cremonese",
    "fiorentina": "Fiorentina",
    "frosinone": "Frosinone",
    "genoa": "Genoa",
    "hellas verona": "Verona",
    "h verona": "Verona",
    "h. verona": "Verona",
    "verona": "Verona",
    "inter": "Inter",
    "juventus": "Juventus",
    "juve": "Juventus",
    "lazio": "Lazio",
    "lecce": "Lecce",
    "milan": "Milan",
    "ac milan": "Milan",
    "monza": "Monza",
    "napoli": "Napoli",
    "parma": "Parma",
    "pisa": "Pisa",
    "roma": "Roma",
    "as roma": "Roma",
    "salernitana": "Salernitana",
    "sassuolo": "Sassuolo",
    "torino": "Torino",
    "udinese": "Udinese",
    "venezia": "Venezia",
    "empoli": "Empoli",
    "sampdoria": "Sampdoria",
    "spezia": "Spezia",
}

MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

# Trattini usati come separatore fra le due squadre: normale, en dash, em dash
TRATTINI = r"[-–—]"


def _pulisci(testo):
    """Normalizza spazi e caratteri invisibili.

    Il carattere '·' viene mantenuto: è il separatore fra una partita e la
    successiva, e trasformarlo in spazio farebbe fondere il nome di un
    assistente con la squadra che segue.
    """
    testo = unicodedata.normalize("NFKC", testo)
    testo = testo.replace("\u00a0", " ")
    testo = re.sub(r"[ \t]+", " ", testo)
    return testo.strip()


def normalizza_squadra(nome):
    """'H. VERONA' -> 'Verona'. Restituisce None se non riconosciuta.

    Se il nome contiene parole in eccesso (capita quando il cognome di un
    assistente resta attaccato alla squadra successiva), prova anche con
    le sole ultime parole.
    """
    if not nome:
        return None
    base = _pulisci(nome).lower()
    base = re.sub(r"[.\u2019']", "", base)
    base = re.sub(r"\s+", " ", base).strip()
    if not base:
        return None

    parole = base.split()
    # Prova il nome intero, poi le ultime due parole, poi l'ultima
    candidati = [base]
    if len(parole) >= 2:
        candidati.append(" ".join(parole[-2:]))
    if len(parole) >= 1:
        candidati.append(parole[-1])

    for c in candidati:
        if c in SQUADRE:
            return SQUADRE[c]
        ridotto = re.sub(r"^(ac|as|ss|ssc|fc|us|uc|acf|bc)\s+", "", c)
        if ridotto in SQUADRE:
            return SQUADRE[ridotto]
    return None


def _titolo(cognome):
    """'DI BELLO' -> 'Di Bello', 'SACCHI J.L.' -> 'Sacchi J.L.'"""
    cognome = _pulisci(cognome)
    parti = []
    for p in cognome.split():
        if re.fullmatch(r"[A-Z]\.([A-Z]\.)*", p):   # iniziali puntate
            parti.append(p)
        else:
            parti.append(p.capitalize())
    return " ".join(parti)


# Coppia di squadre separate da trattino. Volutamente permissiva:
# la validazione vera avviene confrontando i nomi con l'elenco SQUADRE.
COPPIA = re.compile(
    r"\b(?P<casa>[A-ZÀ-Ü][A-ZÀ-Ü.']{1,14}(?:\s+[A-ZÀ-Ü][A-ZÀ-Ü.']{1,14})?)"
    r"\s*" + TRATTINI + r"\s*"
    r"(?P<ospite>[A-ZÀ-Ü][A-ZÀ-Ü.']{1,14}(?:\s+[A-ZÀ-Ü][A-ZÀ-Ü.']{1,14})?)\b"
)

QUANDO = re.compile(
    r"(?:(?P<giorno>Lun|Mar|Mer|Gio|Ven|Sab|Dom)[a-zì]*)?\s*"
    r"(?P<g>\d{1,2})[/.](?P<m>\d{1,2})(?:[/.](?P<a>\d{2,4}))?"
    r"(?:\s*h\.?\s*(?P<oh>\d{1,2})[.:](?P<om>\d{2}))?",
    re.IGNORECASE,
)

# Particelle che possono aprire un cognome composto italiano
PARTICELLE = {"di", "de", "dei", "del", "dal", "della", "la", "lo", "li", "da"}

# Cognomi composti noti di arbitri di Serie A, che non iniziano con particella
COMPOSTI = {
    "ferrieri caputi", "dei giudici", "la penna", "di bello", "di paolo",
    "di marco", "de marco", "lo cicero", "di cicco",
}

INIZIALI = re.compile(r"^[A-Z]\.(?:[A-Z]\.)*$")


def _cognome_arbitro(parole):
    """Decide quante parole compongono il cognome dell'arbitro.

    Nel formato AIA gli assistenti seguono senza parentesi
    ('MARINELLI DI GIOIA – PALERMO'), quindi la seconda parola va presa
    solo quando fa davvero parte del cognome.
    """
    if not parole:
        return None
    if len(parole) == 1:
        return parole[0]

    prima, seconda = parole[0], parole[1]
    coppia = f"{prima} {seconda}".lower()

    if coppia in COMPOSTI:
        return f"{prima} {seconda}"
    if prima.lower() in PARTICELLE:          # DI BELLO, LA PENNA
        return f"{prima} {seconda}"
    if INIZIALI.match(seconda):              # ROSSI M., SACCHI J.L.
        return f"{prima} {seconda}"
    return prima                             # MARINELLI (DI GIOIA è l'assistente)

VAR_RE = re.compile(r"VAR\s*:\s*([A-ZÀ-Ü][A-ZÀ-Ü.'\s]{1,24}?)(?=\s*(?:,|·|AVAR|IV|$|\n))")
AVAR_RE = re.compile(r"AVAR\s*:\s*([A-ZÀ-Ü][A-ZÀ-Ü.'\s]{1,24}?)(?=\s*(?:,|·|$|\n))")
IV_RE = re.compile(r"\bIV\s*:\s*([A-ZÀ-Ü][A-ZÀ-Ü.'\s]{1,24}?)(?=\s*(?:,|·|VAR|$|\n))")


def _data_iso_da_match(m, anno_riferimento):
    """Converte un match di QUANDO in data ISO e ora."""
    if not m:
        return None, None
    g, mese = int(m.group("g")), int(m.group("m"))
    if not (1 <= mese <= 12 and 1 <= g <= 31):
        return None, None
    anno = m.group("a")
    if anno:
        anno = int(anno)
        if anno < 100:
            anno += 2000
    else:
        # La stagione va da agosto a maggio: i mesi da gennaio a giugno
        # appartengono all'anno solare successivo a quello d'inizio
        anno = anno_riferimento if mese >= 7 else anno_riferimento + 1

    ora = None
    if m.group("oh"):
        ora = f"{int(m.group('oh')):02d}:{m.group('om')}"
    try:
        return f"{anno:04d}-{mese:02d}-{g:02d}", ora
    except ValueError:
        return None, None


def analizza(testo, anno_riferimento, giornata=None):
    """Estrae le designazioni dal testo. Restituisce una lista di dizionari.

    Procede in due fasi: prima individua le coppie di squadre riconosciute,
    poi analizza il segmento di testo che segue ciascuna. È più tollerante
    di una singola espressione regolare e non si blocca su formati inattesi.
    """
    testo = _pulisci(testo)

    # Fase 1: trova le partite valide (entrambe le squadre riconosciute)
    partite = []
    for m in COPPIA.finditer(testo):
        casa = normalizza_squadra(m.group("casa"))
        ospite = normalizza_squadra(m.group("ospite"))
        if casa and ospite and casa != ospite:
            partite.append((m.start(), m.end(), casa, ospite))

    # Fase 2: per ciascuna, analizza il testo fino alla partita successiva
    risultati = []
    for i, (inizio, fine_coppia, casa, ospite) in enumerate(partite):
        fine = partite[i + 1][0] if i + 1 < len(partite) else len(testo)
        blocco = testo[fine_coppia:fine]

        mq = QUANDO.search(blocco)
        data, ora = _data_iso_da_match(mq, anno_riferimento)

        # L'arbitro è il primo cognome dopo la data, escluse le sigle di ruolo
        dopo = blocco[mq.end():] if mq else blocco
        dopo = dopo.lstrip(" )")
        arbitro = None
        # si ferma al primo delimitatore: parentesi, trattino, sigla di ruolo
        testa = re.split(r"[(\-–—·,]|\bIV\s*:|\bVAR\s*:|\bAVAR\s*:", dopo, maxsplit=1)[0]
        parole = [p for p in testa.split() if re.match(r"^[A-ZÀ-Ü]", p)]
        parole = [p for p in parole if p not in ("IV", "VAR", "AVAR", "H")]
        if parole:
            arbitro = _titolo(_cognome_arbitro(parole))

        def cerca(regex):
            r = regex.search(blocco)
            return _titolo(r.group(1).strip()) if r else None

        risultati.append({
            "giornata": giornata,
            "data": data,
            "ora": ora,
            "casa": casa,
            "ospite": ospite,
            "arbitro": arbitro,
            "quartoUomo": cerca(IV_RE),
            "var": cerca(VAR_RE),
            "avar": cerca(AVAR_RE),
        })

    return risultati


def giornata_da_testo(testo):
    """Ricava il numero di giornata da un titolo tipo 'designazioni della 27ª'."""
    m = re.search(r"(\d{1,2})\s*[ªa°]\s*giornata", testo, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"designazioni[^0-9]{0,30}(\d{1,2})\s*[ªa°]", testo, re.IGNORECASE)
    return int(m.group(1)) if m else None
