"""
Interpretazione delle designazioni arbitrali di Ligue 1.

Fonte: deux-zero.com, pagina designazioni per giornata.
Formato reale del testo estratto:

    Vendredi 15 Août 2025 20:45 Stade Rennais FC1-0Olympique de Marseille Jérémie PIGNARD
    Samedi 16 Août 2025 17:00 RC Lens0-1Olympique Lyonnais Romain LISSORGUE

Le difficoltà sono due: squadre e risultato sono accostati senza spazi
("Stade Rennais FC1-0Olympique de Marseille"), e il nome dell'arbitro
segue la squadra ospite senza separatore. Entrambe si risolvono usando
il punteggio come ancora e l'elenco squadre come riferimento.

Questo modulo non fa richieste di rete: interpreta solo testo già
scaricato, così è collaudabile in isolamento.
"""

import re
import unicodedata

# Squadre di Ligue 1: nome esteso -> nome usato da football-data.co.uk
SQUADRE = {
    "paris saint-germain fc": "Paris SG",
    "paris saint-germain": "Paris SG",
    "paris fc": "Paris FC",
    "olympique de marseille": "Marseille",
    "olympique lyonnais": "Lyon",
    "as monaco fc": "Monaco",
    "as monaco": "Monaco",
    "losc lille": "Lille",
    "lille osc": "Lille",
    "stade rennais fc": "Rennes",
    "ogc nice": "Nice",
    "rc lens": "Lens",
    "rc strasbourg alsace": "Strasbourg",
    "rc strasbourg": "Strasbourg",
    "stade brestois 29": "Brest",
    "stade brestois": "Brest",
    "toulouse fc": "Toulouse",
    "fc nantes": "Nantes",
    "montpellier hsc": "Montpellier",
    "aj auxerre": "Auxerre",
    "angers sco": "Angers",
    "havre ac": "Le Havre",
    "le havre ac": "Le Havre",
    "fc lorient": "Lorient",
    "fc metz": "Metz",
    "as saint-etienne": "St Etienne",
    "stade de reims": "Reims",
    "clermont foot 63": "Clermont",
    "fc girondins de bordeaux": "Bordeaux",
    "estac troyes": "Troyes",
    "es troyes ac": "Troyes",
    "sc bastia": "Bastia",
    "dijon fco": "Dijon",
    "nimes olympique": "Nimes",
    "sm caen": "Caen",
    "amiens sc": "Amiens",
    "en avant guingamp": "Guingamp",
    "fc lorient bretagne sud": "Lorient",
}

MESI = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12,
}

GIORNI = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def _senza_accenti(testo):
    testo = unicodedata.normalize("NFD", testo)
    return "".join(c for c in testo if unicodedata.category(c) != "Mn").lower()


def _chiave(nome):
    k = _senza_accenti(nome)
    k = re.sub(r"[.\u2019']", "", k)
    return re.sub(r"\s+", " ", k).strip()


_INDICE = {_chiave(k): v for k, v in SQUADRE.items()}
PAROLE_GENERICHE = {
    "olympique", "stade", "football", "club", "sportive", "association",
    "racing", "sporting", "de", "du", "des", "la", "le", "les", "en", "avant",
    "fc", "as", "rc", "sc", "ac", "sm", "us", "ogc", "losc", "aj", "estac",
    "es", "sco", "osc", "hsc", "fco", "alsace", "bretagne", "sud",
}


def _indice_parole():
    """Associa le parole distintive di ogni squadra al suo nome breve.

    Le denominazioni possono variare ("Stade Brestois" contro "Stade
    Brestois 29") ma il nome della città resta e identifica la squadra.
    """
    indice = {}
    ambigue = set()
    for esteso, breve in SQUADRE.items():
        for parola in _chiave(esteso).split():
            if parola in PAROLE_GENERICHE or len(parola) < 4:
                continue
            if parola in indice and indice[parola] != breve:
                ambigue.add(parola)
            indice[parola] = breve
    for parola in ambigue:
        indice.pop(parola, None)
    return indice


_PAROLE = _indice_parole()



def normalizza_squadra(nome):
    """'Stade Rennais FC' -> 'Rennes'. None se non riconosciuta."""
    if not nome:
        return None
    k = _chiave(nome)
    if k in _INDICE:
        return _INDICE[k]
    # tolleranza su prefissi e suffissi societari
    ridotto = re.sub(r"^(fc|as|rc|sc|ac|sm|us|ogc|losc|aj|estac|es|en avant)\s+", "", k)
    ridotto = re.sub(r"\s+(fc|ac|sc|osc|sco|hsc|fco)$", "", ridotto)
    if ridotto in _INDICE:
        return _INDICE[ridotto]

    # Ultima risorsa: una parola distintiva, se appartiene a una sola squadra
    trovate = {_PAROLE[parola] for parola in k.split() if parola in _PAROLE}
    if len(trovate) == 1:
        return trovate.pop()
    return None


# Riga di designazione: giorno, data, ora, poi squadre+punteggio+arbitro accostati
RIGA = re.compile(
    r"(?P<giorno>" + "|".join(GIORNI) + r")\s+"
    r"(?P<g>\d{1,2})\s+"
    r"(?P<mese>[A-Za-zÀ-ÿ]+)\s+"
    r"(?P<a>\d{4})\s+"
    r"(?P<oh>\d{1,2}):(?P<om>\d{2})\s+"
    r"(?P<corpo>.+?)(?=\s*(?:" + "|".join(GIORNI) + r")\s+\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4}|$)",
    re.IGNORECASE | re.DOTALL,
)

# Tutte le possibili letture del punteggio, comprese quelle sovrapposte.
# Il lookahead è indispensabile: in 'Stade Brestois 293-3Lille' una ricerca
# normale troverebbe '93-3' e si fermerebbe lì, mentre la lettura corretta
# è '3-3' e comincia un carattere più avanti. Solo verificando che la parte
# precedente sia una squadra nota si distingue l'una dall'altra.
PUNTEGGIO = re.compile(r"(?=(?P<tutto>(?P<gc>\d{1,2})\s*-\s*(?P<go>\d{1,2})))")


def _dividi_corpo(corpo):
    """Da 'Stade Brestois 293-3Lille OSC Clément TURPIN' ricava
    ('Brest', 3, 3, 'Lille', 'Clément TURPIN').
    """
    for m in PUNTEGGIO.finditer(corpo):
        inizio = m.start()
        fine = inizio + len(m.group("tutto"))
        casa = normalizza_squadra(corpo[:inizio].strip())
        if not casa:
            continue
        ospite, arbitro = _dividi_ospite_arbitro(corpo[fine:].strip())
        if ospite and ospite != casa:
            return casa, int(m.group("gc")), int(m.group("go")), ospite, arbitro
    return None, None, None, None, None


# Il nome dell'arbitro ha una forma costante: nome proprio con l'iniziale
# maiuscola seguito dal cognome tutto in maiuscolo ('Jérémie PIGNARD').
# Ancorare questo schema evita che il testo che segue l'ultima partita
# della pagina — menu, piè di pagina, avvisi di copyright — venga scambiato
# per parte del nome.
NOME_ARBITRO = re.compile(
    # nome proprio, anche composto col trattino: 'Jean-Luc', 'Jérémie', 'J.'
    r"^(?P<nome>(?:[A-ZÀ-Ü][a-zà-ÿ']*(?:-[A-ZÀ-Ü]?[a-zà-ÿ']+)*\.?\s+)+"
    r"[A-ZÀ-Ü][A-ZÀ-Ü'\-]+"                            # cognome in maiuscolo
    r"(?:\s+[A-ZÀ-Ü][A-ZÀ-Ü'\-]+)*)"                   # eventuale secondo cognome
)


def _estrai_arbitro(testo):
    """Isola il nome dell'arbitro dal testo che lo segue."""
    if not testo:
        return None
    m = NOME_ARBITRO.match(testo.strip())
    return m.group("nome").strip() if m else None


def _dividi_ospite_arbitro(testo):
    """Separa 'Olympique de Marseille Jérémie PIGNARD'.

    L'arbitro è in fondo. Si provano tutti i punti di taglio e si tiene
    quello in cui la parte iniziale è una squadra riconosciuta e la parte
    finale ha la forma di un nome di arbitro.
    """
    parole = testo.split()
    if len(parole) < 2:
        return None, None

    candidati = []
    for taglio in range(1, len(parole)):
        squadra = normalizza_squadra(" ".join(parole[:taglio]))
        if not squadra:
            continue
        arbitro = _estrai_arbitro(" ".join(parole[taglio:]))
        if arbitro:
            candidati.append((len(parole) - taglio, squadra, arbitro))

    if not candidati:
        return None, None
    # preferisce il taglio che lascia il nome squadra più lungo possibile
    candidati.sort(key=lambda x: x[0])
    return candidati[0][1], candidati[0][2]


def _titolo_arbitro(nome):
    """'Jérémie PIGNARD' -> 'Jérémie Pignard'"""
    if not nome:
        return None
    parti = []
    for p in nome.split():
        if p.isupper() and len(p) > 1:
            # cognome in maiuscolo: gestisce anche i composti con trattino
            parti.append("-".join(x.capitalize() for x in p.split("-")))
        else:
            parti.append(p)
    return " ".join(parti).strip() or None


def giornata_da_testo(testo):
    m = re.search(r"(\d{1,2})\s*(?:ère|ème|e)\s*journ", testo or "", re.IGNORECASE)
    return int(m.group(1)) if m else None


# Frasi che segnalano l'inizio del piè di pagina: da lì in poi non ci sono
# più designazioni, solo elementi di contorno del sito.
FINE_CONTENUTO = re.compile(
    r"Suivez-nous|Présentation du site|Liens utiles|©\s*\d{4}|Mentions légales",
    re.IGNORECASE,
)


def analizza(testo, giornata=None):
    """Estrae le designazioni. Restituisce una lista di dizionari."""
    if not testo:
        return []

    testo = testo.replace("\u00a0", " ")
    testo = re.sub(r"[ \t]+", " ", testo)

    # scarta tutto ciò che segue l'inizio del piè di pagina
    taglio = FINE_CONTENUTO.search(testo)
    if taglio:
        testo = testo[:taglio.start()]

    risultati = []
    for m in RIGA.finditer(testo):
        mese = MESI.get(_senza_accenti(m.group("mese")))
        if not mese:
            continue

        corpo = m.group("corpo").strip()
        casa, gc, go, ospite, arbitro = _dividi_corpo(corpo)

        if not (casa and ospite):
            continue

        risultati.append({
            "giornata": giornata,
            "data": f"{int(m.group('a')):04d}-{mese:02d}-{int(m.group('g')):02d}",
            "ora": f"{int(m.group('oh')):02d}:{m.group('om')}",
            "casa": casa,
            "ospite": ospite,
            "gc": gc,
            "go": go,
            "arbitro": _titolo_arbitro(arbitro),
        })

    return risultati
