"""
Interpretazione delle designazioni arbitrali di LaLiga (Primera División).

Fonte: PDF ufficiali del Comité Técnico de Árbitros pubblicati dalla RFEF.
Formato reale del testo estratto dal PDF:

    22-08-2026 Athletic Club Sevilla FC 17:00
    Árbitro:César Soto 4º Árbitro:Francisco Crespo
    A. Asistente 1: Carlos Álvarez VAR: Valentín Pizarro
    A. Asistente 2: Rubén Becerril AVAR: Adrián Cordero
    Oficial Informador: Carlos Delgado

La difficoltà principale è separare le due squadre: compaiono una dopo
l'altra senza separatore. Si risolve confrontando con l'elenco ufficiale
delle squadre, provando tutti i punti di taglio possibili.

Questo modulo non fa richieste di rete: interpreta solo testo già
scaricato, così è collaudabile in isolamento.
"""

import re
import unicodedata

# Squadre di Primera División: nome nel PDF -> nome usato da football-data.co.uk.
# I PDF usano la denominazione societaria completa, i CSV una forma abbreviata.
SQUADRE = {
    "athletic club": "Ath Bilbao",
    "club atletico de madrid": "Ath Madrid",
    "atletico de madrid": "Ath Madrid",
    "fc barcelona": "Barcelona",
    "real betis balompie": "Betis",
    "rc celta de vigo": "Celta",
    "rcd espanyol de barcelona": "Espanol",
    "elche cf": "Elche",
    "getafe cf": "Getafe",
    "girona fc": "Girona",
    "levante ud": "Levante",
    "rcd mallorca": "Mallorca",
    "ca osasuna": "Osasuna",
    "rayo vallecano": "Vallecano",
    "rayo vallecano de madrid": "Vallecano",
    "real madrid cf": "Real Madrid",
    "real oviedo": "Oviedo",
    "real sociedad": "Sociedad",
    "real sociedad de futbol": "Sociedad",
    "sevilla fc": "Sevilla",
    "valencia cf": "Valencia",
    "villarreal cf": "Villarreal",
    "deportivo alaves": "Alaves",
    "ud las palmas": "Las Palmas",
    "cd leganes": "Leganes",
    "real valladolid cf": "Valladolid",
    "cadiz cf": "Cadiz",
    "ud almeria": "Almeria",
    "granada cf": "Granada",
    "rcd espanyol": "Espanol",
    "sd huesca": "Huesca",
    "sd eibar": "Eibar",
    "cd tenerife": "Tenerife",
    "burgos cf": "Burgos",
    "racing de santander": "Santander",
    "real racing club": "Santander",
    "real zaragoza": "Zaragoza",
    "sporting de gijon": "Sp Gijon",
    "rc deportivo de la coruna": "La Coruna",
    "deportivo de la coruna": "La Coruna",
    "rc deportivo": "La Coruna",
    "real racing club": "Santander",
    "racing de santander": "Santander",
    "real oviedo": "Oviedo",
    "cd castellon": "Castellon",
    "cd mirandes": "Mirandes",
    "sd eibar": "Eibar",
    "cd leganes": "Leganes",
    "ud almeria": "Almeria",
    "sporting de gijon": "Sp Gijon",
    "real sporting de gijon": "Sp Gijon",
    "cd tenerife": "Tenerife",
    "albacete balompie": "Albacete",
    "fc andorra": "Andorra",
    "sd huesca": "Huesca",
    "cordoba cf": "Cordoba",
    "ad ceuta fc": "Ceuta",
    "real valladolid cf": "Valladolid",
    "real zaragoza": "Zaragoza",
    "burgos cf": "Burgos",
    "malaga cf": "Malaga",
}


def _senza_accenti(testo):
    """'Alavés' -> 'alaves' — per confronti robusti."""
    testo = unicodedata.normalize("NFD", testo)
    testo = "".join(c for c in testo if unicodedata.category(c) != "Mn")
    return testo.lower()


def _chiave(nome):
    k = _senza_accenti(nome)
    k = re.sub(r"[.\u2019']", "", k)
    return re.sub(r"\s+", " ", k).strip()


# Indice per confronto: chiave normalizzata -> nome breve
_INDICE = {_chiave(k): v for k, v in SQUADRE.items()}
# Parole generiche che compaiono in molte denominazioni societarie e che da
# sole non identificano nessuna squadra.
PAROLE_GENERICHE = {
    "real", "club", "de", "del", "la", "las", "los", "cf", "fc", "rc", "rcd",
    "cd", "ud", "sd", "ca", "ac", "atletico", "deportivo", "sociedad",
    "balompie", "futbol", "union", "sporting", "racing", "unido", "sad",
}


def _indice_parole():
    """Associa le parole distintive di ogni squadra al suo nome breve.

    Serve come ultima risorsa quando la denominazione nel PDF non coincide
    con nessuna di quelle in elenco: 'Real Racing Club de Santander' non
    corrisponde a niente parola per parola, ma contiene 'santander', che
    appartiene a una squadra sola.
    """
    indice = {}
    ambigue = set()
    for nome_esteso, breve in SQUADRE.items():
        for parola in _chiave(nome_esteso).split():
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
    """'RCD Espanyol de Barcelona' -> 'Espanol'. None se non riconosciuta."""
    if not nome:
        return None
    k = _chiave(nome)
    if k in _INDICE:
        return _INDICE[k]
    # tolleranza: prova togliendo suffissi e prefissi societari
    ridotto = re.sub(r"^(cf|fc|rc|rcd|cd|ud|sd|ca|club)\s+", "", k)
    ridotto = re.sub(r"\s+(cf|fc|rc|rcd|cd|ud|sd|ca)$", "", ridotto)
    if ridotto in _INDICE:
        return _INDICE[ridotto]

    # Ultima risorsa: cerca una parola distintiva. Una denominazione può
    # variare nella forma ("Real Racing Club de Santander" contro "Racing
    # de Santander") ma il nome della città o della società resta.
    trovate = {_PAROLE[parola] for parola in k.split() if parola in _PAROLE}
    if len(trovate) == 1:
        return trovate.pop()
    return None


def _dividi_squadre(testo):
    """Separa 'Athletic Club Sevilla FC' in ('Ath Bilbao', 'Sevilla').

    Le due squadre sono accostate senza separatore, quindi si provano
    tutti i punti di taglio e si tiene quello in cui entrambe le metà
    corrispondono a squadre note.
    """
    parole = testo.split()
    if len(parole) < 2:
        return None, None

    # Preferisce i tagli che lasciano entrambe le parti riconoscibili;
    # a parità, quello più equilibrato (evita accoppiamenti fortuiti).
    candidati = []
    for taglio in range(1, len(parole)):
        casa = normalizza_squadra(" ".join(parole[:taglio]))
        ospite = normalizza_squadra(" ".join(parole[taglio:]))
        if casa and ospite and casa != ospite:
            squilibrio = abs(taglio - (len(parole) - taglio))
            candidati.append((squilibrio, casa, ospite))

    if not candidati:
        return None, None
    candidati.sort(key=lambda x: x[0])
    return candidati[0][1], candidati[0][2]


# Riga di apertura partita: data, squadre accostate, orario
INTESTAZIONE = re.compile(
    r"(?P<g>\d{2})-(?P<m>\d{2})-(?P<a>\d{4})\s+"
    r"(?P<squadre>.+?)\s+"
    r"(?P<oh>\d{1,2}):(?P<om>\d{2})\s*$",
    re.MULTILINE,
)

ARBITRO = re.compile(r"[ÁA]rbitro\s*:\s*(?P<nome>[^\n]+?)(?=\s+4[ºo°]\s*[ÁA]rbitro|$)", re.MULTILINE)
QUARTO = re.compile(r"4[ºo°]\s*[ÁA]rbitro\s*:\s*(?P<nome>[^\n]+?)\s*$", re.MULTILINE)
VAR = re.compile(r"(?<!A)VAR\s*:\s*(?P<nome>[^\n]+?)\s*$", re.MULTILINE)
AVAR = re.compile(r"AVAR\s*:\s*(?P<nome>[^\n]+?)\s*$", re.MULTILINE)
ASSIST1 = re.compile(r"A\.\s*Asistente\s*1\s*:\s*(?P<nome>[^\n]+?)(?=\s+VAR\s*:|$)", re.MULTILINE)
ASSIST2 = re.compile(r"A\.\s*Asistente\s*2\s*:\s*(?P<nome>[^\n]+?)(?=\s+AVAR\s*:|$)", re.MULTILINE)

GIORNATA = re.compile(r"Jornada\s*-?\s*(\d{1,2})", re.IGNORECASE)
STAGIONE = re.compile(r"TEMPORADA\s+(\d{4})-(\d{4})", re.IGNORECASE)


def _pulisci_nome(nome):
    """Toglie spazi e code spurie dal nome di un ufficiale di gara."""
    if not nome:
        return None
    nome = re.sub(r"\s+", " ", nome).strip(" :-")
    # taglia eventuali etichette rimaste attaccate
    nome = re.split(r"\s+(?:4[ºo°]|VAR|AVAR|A\.\s*Asistente|Oficial)", nome)[0]
    return nome.strip() or None


def giornata_da_testo(testo):
    m = GIORNATA.search(testo or "")
    return int(m.group(1)) if m else None


def stagione_da_testo(testo):
    """'TEMPORADA 2026-2027' -> 2026 (anno di inizio)."""
    m = STAGIONE.search(testo or "")
    return int(m.group(1)) if m else None


def analizza(testo, giornata=None):
    """Estrae le designazioni dal testo del PDF."""
    if not testo:
        return []

    testo = testo.replace("\u00a0", " ")
    if giornata is None:
        giornata = giornata_da_testo(testo)

    intestazioni = list(INTESTAZIONE.finditer(testo))
    risultati = []

    for i, m in enumerate(intestazioni):
        casa, ospite = _dividi_squadre(m.group("squadre"))
        if not casa or not ospite:
            continue

        # il blocco arriva fino alla partita successiva
        fine = intestazioni[i + 1].start() if i + 1 < len(intestazioni) else len(testo)
        blocco = testo[m.end():fine]

        def cerca(regex):
            r = regex.search(blocco)
            return _pulisci_nome(r.group("nome")) if r else None

        risultati.append({
            "giornata": giornata,
            "data": f"{m.group('a')}-{m.group('m')}-{m.group('g')}",
            "ora": f"{int(m.group('oh')):02d}:{m.group('om')}",
            "casa": casa,
            "ospite": ospite,
            "arbitro": cerca(ARBITRO),
            "quartoUomo": cerca(QUARTO),
            "var": cerca(VAR),
            "avar": cerca(AVAR),
            "assistente1": cerca(ASSIST1),
            "assistente2": cerca(ASSIST2),
        })

    return risultati


def testo_da_pdf(dati_binari):
    """Estrae il testo da un PDF. Richiede pypdf."""
    import io
    from pypdf import PdfReader

    lettore = PdfReader(io.BytesIO(dati_binari))
    return "\n".join((p.extract_text() or "") for p in lettore.pages)


def righe_non_riconosciute(testo):
    """Elenca le intestazioni di partita le cui squadre non sono in elenco.

    Serve a segnalare subito quando una squadra promossa o rinominata manca
    dalla tabella SQUADRE: senza questo avviso la partita sparirebbe in
    silenzio e ci si accorgerebbe della lacuna solo guardando la dashboard.
    """
    fuori = []
    for m in INTESTAZIONE.finditer(testo.replace("\u00a0", " ")):
        casa, ospite = _dividi_squadre(m.group("squadre"))
        if not (casa and ospite):
            fuori.append(m.group("squadre").strip())
    return fuori
