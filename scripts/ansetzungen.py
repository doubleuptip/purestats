"""
Interpretazione delle designazioni arbitrali di Bundesliga.

Fonte: DFB Datencenter, pagina delle designazioni. Formato del testo:

    ###### Bundesliga
    Spieltag 1
    Freitag, 28.08.2026 20:30 Uhr
    Bayern München
    - : -
    VfB Stuttgart
    [Sören Storks (SR)] [Thorben Siewer (SR-A. 1)] [Christian Bandurski (SR-A. 2)]
    [Dr. Robin Braun (4. Offizieller)] [Tobias Welz (VA)] [Patrick Hanslbauer (VA-A)]

La pagina contiene anche 2. Bundesliga, 3. Liga, Regionalliga e i campionati
femminili: va isolata la sola sezione della Bundesliga, altrimenti si
mescolerebbero categorie diverse.

Sigle: SR arbitro, SR-A. assistenti, VA e VA-A la coppia video.
"""

import datetime
import re
import unicodedata

# Nomi nel Datencenter -> nomi usati da football-data.co.uk
SQUADRE = {
    "bayern munchen": "Bayern Munich",
    "rb leipzig": "RB Leipzig",
    "eintracht frankfurt": "Ein Frankfurt",
    "werder bremen": "Werder Bremen",
    "sc freiburg": "Freiburg",
    "fc augsburg": "Augsburg",
    "1 fc heidenheim": "Heidenheim",
    "vfl wolfsburg": "Wolfsburg",
    "bayer leverkusen": "Leverkusen",
    "bayer 04 leverkusen": "Leverkusen",
    "tsg hoffenheim": "Hoffenheim",
    "1 fc union berlin": "Union Berlin",
    "vfb stuttgart": "Stuttgart",
    "fc st pauli": "St Pauli",
    "borussia dortmund": "Dortmund",
    "1 fsv mainz 05": "Mainz",
    "1 fc koln": "FC Koln",
    "borussia monchengladbach": "M'gladbach",
    "hamburger sv": "Hamburg",
    "sv elversberg": "Elversberg",
    "fc schalke 04": "Schalke 04",
    "sc paderborn 07": "Paderborn",
    "holstein kiel": "Holstein Kiel",
    "vfl bochum": "Bochum",
    "1 fc nurnberg": "Nurnberg",
    "hertha bsc": "Hertha",
    "sv darmstadt 98": "Darmstadt",
    "fc ingolstadt": "Ingolstadt",
    "arminia bielefeld": "Bielefeld",
    "1 fc kaiserslautern": "Kaiserslautern",
    "fortuna dusseldorf": "Dusseldorf",
    "hannover 96": "Hannover",
}

# Parole troppo comuni per identificare una squadra da sole
GENERICHE = {
    "fc", "sv", "sc", "vfl", "vfb", "tsg", "fsv", "bsc", "sg", "spvgg",
    "borussia", "eintracht", "bayer", "1", "04", "05", "07", "96", "98",
    "ii", "berlin", "munchen",
}

MESI_ORDINE = None  # le date sono numeriche, non serve mappa mesi


def _senza_accenti(t):
    t = unicodedata.normalize("NFD", t.replace("ß", "ss"))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


def _chiave(nome):
    k = _senza_accenti(nome or "")
    k = re.sub(r"[.\-']", " ", k)
    return re.sub(r"\s+", " ", k).strip()


_INDICE = {_chiave(k): v for k, v in SQUADRE.items()}


def _indice_parole():
    """Parole distintive: una squadra rinominata resta riconoscibile."""
    ind, ambigue = {}, set()
    for esteso, breve in SQUADRE.items():
        for p in _chiave(esteso).split():
            if p in GENERICHE or len(p) < 4:
                continue
            if p in ind and ind[p] != breve:
                ambigue.add(p)
            ind[p] = breve
    for p in ambigue:
        ind.pop(p, None)
    return ind


_PAROLE = _indice_parole()


def normalizza_squadra(nome):
    """'Borussia Mönchengladbach' -> \"M'gladbach\". None se sconosciuta."""
    if not nome:
        return None
    k = _chiave(nome)
    if k in _INDICE:
        return _INDICE[k]
    trovate = {_PAROLE[p] for p in k.split() if p in _PAROLE}
    return trovate.pop() if len(trovate) == 1 else None


# Nomi delle categorie presenti nella pagina. Servono a delimitare la
# sezione della Bundesliga: comincia dove compare il suo nome e finisce
# dove ne comincia un'altra.
CATEGORIE = [
    "2. Bundesliga", "3. Liga", "Regionalliga", "Frauen-Bundesliga",
    "Google Pixel Frauen-Bundesliga", "DFB-Pokal", "Junioren", "A-Junioren",
    "B-Junioren", "Bundesliga",
]

# L'intestazione può presentarsi come titolo in formato testuale
# ('###### Bundesliga') o come riga a sé stante, a seconda di come il
# contenuto viene convertito in testo. Si accettano entrambe le forme.
def _intestazioni(testo):
    """Elenca le categorie trovate, con la posizione nel testo."""
    trovate = []
    for m in re.finditer(r"^[ \t]*#{0,6}[ \t]*(?P<nome>[^\n]{3,60}?)[ \t]*$",
                         testo, re.MULTILINE):
        nome = m.group("nome").strip()
        pulito = _senza_accenti(nome)
        for categoria in CATEGORIE:
            if pulito == _senza_accenti(categoria):
                trovate.append((m.start(), m.end(), categoria))
                break
    return trovate


def sezione_bundesliga(testo):
    """Isola la parte di pagina che riguarda la sola Bundesliga.

    La pagina elenca tutte le categorie del calcio tedesco, dalla seconda
    divisione ai campionati femminili: senza questo taglio finirebbero in
    archivio partite di competizioni diverse.
    """
    intestazioni = _intestazioni(testo)
    for i, (inizio, fine_int, nome) in enumerate(intestazioni):
        if nome != "Bundesliga":
            continue
        fine = intestazioni[i + 1][0] if i + 1 < len(intestazioni) else len(testo)
        return testo[fine_int:fine]
    return ""


GIORNATA = re.compile(r"Spieltag\s+(\d{1,2})")

# 'Freitag, 28.08.2026 20:30 Uhr'
QUANDO = re.compile(
    r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag),\s*"
    r"(?P<g>\d{2})\.(?P<m>\d{2})\.(?P<a>\d{4})\s+"
    r"(?P<oh>\d{1,2}):(?P<om>\d{2})\s*Uhr")

# '[Sören Storks (SR)](indirizzo)' oppure 'Sören Storks (SR)'
UFFICIALE = re.compile(
    r"\[?(?P<nome>[^\[\]()]+?)\s*\((?P<ruolo>SR|SR-A\.\s*1|SR-A\.\s*2|"
    r"4\.\s*Offizieller|VA|VA-A)\)\]?")


def _pulisci(nome):
    n = re.sub(r"\s+", " ", (nome or "")).strip(" :-|")
    return n or None


def analizza(testo):
    """Estrae le designazioni della Bundesliga dal testo della pagina."""
    if not testo:
        return []

    blocco = sezione_bundesliga(testo)
    if not blocco:
        return []

    # Ogni partita comincia con una data: si divide lì
    tagli = list(QUANDO.finditer(blocco))
    risultati = []

    for i, m in enumerate(tagli):
        fine = tagli[i + 1].start() if i + 1 < len(tagli) else len(blocco)
        corpo = blocco[m.end():fine]

        # La giornata è l'ultima dichiarata prima di questa partita
        precedente = blocco[:m.start()]
        mg = None
        for x in GIORNATA.finditer(precedente):
            mg = x
        giornata = int(mg.group(1)) if mg else None

        # Le due squadre stanno prima e dopo il segnaposto del risultato
        parti = re.split(r"^\s*-\s*:\s*-\s*$", corpo, maxsplit=1, flags=re.MULTILINE)
        if len(parti) != 2:
            continue

        def prima_squadra(frammento, dal_fondo=False):
            righe = [r.strip() for r in frammento.splitlines() if r.strip()]
            if dal_fondo:
                righe.reverse()
            for r in righe:
                # toglie i riferimenti alle immagini
                pulita = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", r)
                pulita = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", pulita)
                sq = normalizza_squadra(pulita)
                if sq:
                    return sq
            return None

        casa = prima_squadra(parti[0], dal_fondo=True)
        ospite = prima_squadra(parti[1])
        if not casa or not ospite or casa == ospite:
            continue

        ruoli = {}
        for u in UFFICIALE.finditer(corpo):
            chiave = re.sub(r"\s+", " ", u.group("ruolo")).strip()
            ruoli.setdefault(chiave, _pulisci(u.group("nome")))

        try:
            data = f"{int(m.group('a')):04d}-{int(m.group('m')):02d}-{int(m.group('g')):02d}"
            datetime.date.fromisoformat(data)
        except ValueError:
            continue

        risultati.append({
            "giornata": giornata,
            "data": data,
            "ora": f"{int(m.group('oh')):02d}:{m.group('om')}",
            "casa": casa,
            "ospite": ospite,
            "arbitro": ruoli.get("SR"),
            "assistente1": ruoli.get("SR-A. 1"),
            "assistente2": ruoli.get("SR-A. 2"),
            "quartoUomo": ruoli.get("4. Offizieller"),
            "var": ruoli.get("VA"),
            "avar": ruoli.get("VA-A"),
        })

    return risultati


def diagnostica(testo):
    """Riepiloga cosa è stato riconosciuto nella pagina.

    Serve quando l'analisi non produce nulla: distingue fra pagina non
    scaricata, sezione non individuata e partite non interpretate.
    """
    righe = []
    intestazioni = _intestazioni(testo)
    righe.append(f"categorie individuate: {[c for _, _, c in intestazioni] or 'nessuna'}")

    blocco = sezione_bundesliga(testo)
    righe.append(f"sezione Bundesliga: {len(blocco)} caratteri")
    if blocco:
        righe.append(f"date trovate nella sezione: {len(QUANDO.findall(blocco))}")
        righe.append(f"ufficiali di gara trovati: {len(UFFICIALE.findall(blocco))}")
        estratto = " ".join(blocco.split())[:150]
        righe.append(f"inizio sezione: {estratto!r}")
    else:
        estratto = " ".join(testo.split())[:150]
        righe.append(f"inizio pagina: {estratto!r}")
    return righe
