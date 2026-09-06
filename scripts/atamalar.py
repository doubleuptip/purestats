"""
Interpretazione delle designazioni arbitrali della Süper Lig.

Fonte: TFF, pagina "Haftanın Programı" della federazione turca.
Formato del testo estratto:

    Trendyol Süper Lig Adnan Süvari Sezonu - 4.Hafta
    04.09.2026 Cuma  20:00
    İSTANBUL BAŞAKŞEHİR FK
    GALATASARAY A.Ş.
    (H) KADİR SAĞLAM
    (Y) MEHMET KISAL
    (Y) ESAT SANCAKTAR
    (D) FATİH TOKAÇLI

Sigle: H arbitro (hakem), Y assistenti (yardımcı), D quarto uomo
(dördüncü hakem). G e T indicano osservatori e delegati, che non servono.

La pagina contiene tutte le divisioni turche, dalla seconda serie ai
campionati regionali: va isolata la sezione della sola Süper Lig.

Il VAR non compare: la TFF lo comunica separatamente.
"""

import re
import unicodedata

# Nomi nel sito TFF -> nomi usati da football-data.co.uk.
# Le denominazioni turche cambiano ogni stagione perché incorporano lo
# sponsor (TÜMOSAN Konyaspor, Çaykur Rizespor, Corendon Alanyaspor):
# l'elenco serve da riferimento, ma il riconoscimento si appoggia
# soprattutto alle parole distintive più sotto.
SQUADRE = {
    "galatasaray": "Galatasaray",
    "fenerbahce": "Fenerbahce",
    "besiktas": "Besiktas",
    "trabzonspor": "Trabzonspor",
    "istanbul basaksehir fk": "Buyuksehyr",
    "basaksehir": "Buyuksehyr",
    "kasimpasa": "Kasimpasa",
    "konyaspor": "Konyaspor",
    "rizespor": "Rizespor",
    "gaziantep futbol kulubu": "Gaziantep",
    "gaziantep fk": "Gaziantep",
    "alanyaspor": "Alanyaspor",
    "genclerbirligi": "Genclerbirligi",
    "kocaelispor": "Kocaelispor",
    "amed sportif faaliyetler": "Amedspor",
    "amedspor": "Amedspor",
    "erzurumspor fk": "Erzurumspor",
    "erzurumspor": "Erzurumspor",
    "eyupspor": "Eyupspor",
    "samsunspor": "Samsunspor",
    "goztepe": "Goztep",
    "corum fk": "Corum",
    "antalyaspor": "Antalyaspor",
    "sivasspor": "Sivasspor",
    "kayserispor": "Kayserispor",
    "hatayspor": "Hatayspor",
    "adana demirspor": "Ad. Demirspor",
    "bodrum fk": "Bodrum",
    "pendikspor": "Pendikspor",
    "istanbulspor": "Istanbulspor",
    "ankaragucu": "Ankaragucu",
    "fatih karagumruk": "Karagumruk",
    "karagumruk": "Karagumruk",
    "giresunspor": "Giresunspor",
    "umraniyespor": "Umraniyespor",
    "besiktas as": "Besiktas",
}

# Parole troppo comuni per identificare una squadra da sole: compaiono
# nelle denominazioni societarie o sono nomi di sponsor.
GENERICHE = {
    "as", "fk", "sk", "spor", "kulubu", "futbol", "a", "s",
    "trendyol", "tumosan", "caykur", "corendon", "arca", "rams",
    "ikas", "sportif", "faaliyetler", "istanbul", "yeni",
}


def _senza_accenti(t):
    """Normalizza il turco: 'Beşiktaş' -> 'besiktas', 'İ' -> 'i'."""
    t = (t or "")
    # la I turca senza punto e la i con punto vanno ricondotte a 'i'
    t = t.replace("İ", "i").replace("I", "i").replace("ı", "i")
    t = t.replace("Ş", "s").replace("ş", "s")
    t = t.replace("Ğ", "g").replace("ğ", "g")
    t = t.replace("Ç", "c").replace("ç", "c")
    t = t.replace("Ö", "o").replace("ö", "o")
    t = t.replace("Ü", "u").replace("ü", "u")
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()


def _chiave(nome):
    k = _senza_accenti(nome)
    k = re.sub(r"[.\-'’]", " ", k)
    return re.sub(r"\s+", " ", k).strip()


_INDICE = {_chiave(k): v for k, v in SQUADRE.items()}


def _indice_parole():
    """Parole distintive: reggono i cambi di sponsor da una stagione all'altra."""
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
    """'TÜMOSAN KONYASPOR' -> 'Konyaspor'. None se sconosciuta."""
    if not nome:
        return None
    k = _chiave(nome)
    if k in _INDICE:
        return _INDICE[k]
    trovate = {_PAROLE[p] for p in k.split() if p in _PAROLE}
    return trovate.pop() if len(trovate) == 1 else None


# Intestazione di sezione: 'Trendyol Süper Lig ... - 4.Hafta'
SEZIONE = re.compile(
    r"^(?P<nome>[^\n]{5,90}?)\s*-\s*(?P<giornata>\d{1,2})\.\s*Hafta\s*$",
    re.MULTILINE | re.IGNORECASE)

# '04.09.2026' seguito dal giorno della settimana
DATA = re.compile(r"(?P<g>\d{2})\.(?P<m>\d{2})\.(?P<a>\d{4})")
ORA = re.compile(r"^\s*(?P<oh>\d{1,2}):(?P<om>\d{2})\s*$", re.MULTILINE)

# '[(H) KADİR SAĞLAM](indirizzo)' oppure '(H) KADİR SAĞLAM'
UFFICIALE = re.compile(
    r"\[?\((?P<ruolo>[HYDGT])\)\s*(?P<nome>[^\[\]()\n]+?)\s*\]?(?:\([^)]*\))?\s*$",
    re.MULTILINE)

# Le squadre compaiono come collegamenti con kulupID
SQUADRA_LINK = re.compile(r"\[(?P<nome>[^\]]+)\]\([^)]*kulupID=\d+\)")


def _minuscolo_turco(testo):
    """Abbassa il testo secondo le regole turche.

    In turco esistono due lettere i: 'I' senza punto si abbassa in 'ı',
    mentre 'İ' col punto si abbassa in 'i'. Le regole comuni le
    confondono, e il risultato sono cognomi sbagliati: Çakır diventa
    Çakir, Tokaçlı diventa Tokaçli.
    """
    fuori = []
    for c in testo:
        if c == "I":
            fuori.append("ı")
        elif c == "İ":
            fuori.append("i")
        else:
            fuori.append(c.lower())
    return "".join(fuori)


def _maiuscola_turca(c):
    """'i' -> 'İ', il ribaltamento della regola precedente."""
    return "İ" if c == "i" else c.upper()


def _titolo(nome):
    """'KADİR SAĞLAM' -> 'Kadir Sağlam', rispettando le due i turche."""
    if not nome:
        return None
    parti = []
    for p in re.sub(r"\s+", " ", nome).strip().split():
        if len(p) > 1 and p == p.upper():
            basso = _minuscolo_turco(p)
            parti.append(_maiuscola_turca(basso[0]) + basso[1:])
        else:
            parti.append(p)
    return " ".join(parti).strip() or None


def sezione(testo, categoria="Süper Lig"):
    """Isola la parte di pagina che riguarda una sola divisione.

    Il confronto è sul contenuto dell'intestazione, non sull'uguaglianza:
    il nome cambia ogni anno perché comprende sponsor e intitolazione
    della stagione ('Trendyol Süper Lig Adnan Süvari Sezonu').
    """
    voluta = _senza_accenti(categoria).strip()
    intestazioni = list(SEZIONE.finditer(testo))
    for i, m in enumerate(intestazioni):
        nome = _senza_accenti(m.group("nome"))
        # '2. Lig' non deve essere scambiata per 'Süper Lig'
        if voluta not in nome:
            continue
        if voluta == "super lig" and re.search(r"\d\.\s*lig", nome):
            continue
        fine = intestazioni[i + 1].start() if i + 1 < len(intestazioni) else len(testo)
        return testo[m.end():fine], int(m.group("giornata"))
    return "", None


def analizza(testo, categoria="Süper Lig"):
    """Estrae le designazioni della divisione indicata."""
    if not testo:
        return []

    testo = testo.replace("\u00a0", " ")
    blocco, giornata = sezione(testo, categoria)
    if not blocco:
        return []

    # ogni partita comincia con la propria data
    tagli = list(DATA.finditer(blocco))
    risultati = []

    for i, m in enumerate(tagli):
        fine = tagli[i + 1].start() if i + 1 < len(tagli) else len(blocco)
        corpo = blocco[m.end():fine]

        squadre = [normalizza_squadra(x.group("nome"))
                   for x in SQUADRA_LINK.finditer(corpo)]
        squadre = [s for s in squadre if s]
        if len(squadre) < 2 or squadre[0] == squadre[1]:
            continue

        ruoli = {}
        for u in UFFICIALE.finditer(corpo):
            ruolo = u.group("ruolo")
            nome = _titolo(u.group("nome"))
            if nome and ruolo not in ("G", "T"):
                ruoli.setdefault(ruolo, []).append(nome)

        mo = ORA.search(corpo)
        ora = f"{int(mo.group('oh')):02d}:{mo.group('om')}" if mo else None

        assistenti = ruoli.get("Y", [])
        risultati.append({
            "giornata": giornata,
            "data": f"{m.group('a')}-{m.group('m')}-{m.group('g')}",
            "ora": ora,
            "casa": squadre[0],
            "ospite": squadre[1],
            "arbitro": ruoli.get("H", [None])[0],
            "assistente1": assistenti[0] if len(assistenti) > 0 else None,
            "assistente2": assistenti[1] if len(assistenti) > 1 else None,
            "quartoUomo": ruoli.get("D", [None])[0],
            "var": None,      # la TFF lo comunica separatamente
            "avar": None,
        })

    return risultati


def diagnostica(testo, categoria="Süper Lig"):
    """Riepiloga cosa è stato riconosciuto, quando l'analisi non produce nulla."""
    righe = []
    intestazioni = [m.group("nome").strip() for m in SEZIONE.finditer(testo)]
    righe.append(f"sezioni trovate: {intestazioni[:6] or 'nessuna'}")
    blocco, giornata = sezione(testo, categoria)
    righe.append(f"sezione {categoria}: {len(blocco)} caratteri, giornata {giornata}")
    if blocco:
        righe.append(f"date nella sezione: {len(DATA.findall(blocco))}")
        righe.append(f"squadre riconoscibili: {len(SQUADRA_LINK.findall(blocco))}")
        righe.append(f"ufficiali trovati: {len(UFFICIALE.findall(blocco))}")
    else:
        righe.append(f"inizio pagina: {' '.join(testo.split())[:150]!r}")
    return righe
