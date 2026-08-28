"""
Lettura dei feed RSS e classificazione delle notizie.

Dai feed si prendono solo titolo, data, fonte e collegamento: il testo
degli articoli resta sui siti che li pubblicano. È la differenza fra un
aggregatore e una riproduzione non autorizzata, e qui conta più che
altrove — le testate giornalistiche tutelano i propri contenuti con
molta più determinazione di quanto facciano i siti di statistiche.

Nessuna dipendenza esterna: la libreria standard di Python sa già
leggere XML.
"""

import html
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# Parole che identificano il tipo di notizia. L'ordine conta: una notizia
# sulle formazioni che nomina anche un infortunato resta una notizia sulle
# formazioni, perché è quella la sua funzione per chi legge.
CATEGORIE = [
    ("formazioni", [
        "probabili formazioni", "probabile formazione", "formazioni ufficiali",
        "formazione ufficiale", "le scelte di", "chi gioca", "undici titolare",
        "verso ", "ballottaggio",
    ]),
    ("infortuni", [
        "infortun", "indisponibil", "squalificat", "lesione", "distorsione",
        "stop per", "out per", "salta la", "salterà", "in dubbio",
        "recupero", "recuperato", "torna a disposizione", "ai box",
    ]),
    ("mercato", [
        "calciomercato", "ufficiale:", "firma", "rinnovo", "acquisto",
        "cessione", "prestito", "trattativa",
    ]),
]


def _senza_accenti(testo):
    testo = unicodedata.normalize("NFD", testo or "")
    return "".join(c for c in testo if unicodedata.category(c) != "Mn").lower()


def classifica(titolo, sommario=""):
    """Assegna una categoria alla notizia, o 'generale' se nessuna calza."""
    testo = _senza_accenti(f"{titolo} {sommario}")
    for nome, parole in CATEGORIE:
        for p in parole:
            if _senza_accenti(p) in testo:
                return nome
    return "generale"


def _testo(elemento):
    if elemento is None:
        return ""
    return html.unescape((elemento.text or "").strip())


def _pulisci_html(testo):
    """Toglie i tag dal sommario, che spesso ne contiene."""
    testo = re.sub(r"<[^>]+>", " ", testo or "")
    testo = html.unescape(testo)
    return re.sub(r"\s+", " ", testo).strip()


def _data_iso(testo):
    """Converte la data di un feed in formato ISO."""
    if not testo:
        return None
    try:
        d = parsedate_to_datetime(testo)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    for formato in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.strptime(testo.strip(), formato)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def analizza_feed(xml_grezzo, fonte):
    """Estrae le notizie da un feed RSS o Atom.

    Restituisce titolo, sommario breve, collegamento, data e fonte.
    Il sommario viene troncato: serve a capire di cosa parla la notizia,
    non a sostituire la lettura dell'articolo.
    """
    if not xml_grezzo:
        return []

    try:
        radice = ET.fromstring(xml_grezzo)
    except ET.ParseError:
        return []

    notizie = []
    spazi = {"atom": "http://www.w3.org/2005/Atom",
             "dc": "http://purl.org/dc/elements/1.1/"}

    # RSS classico
    elementi = radice.findall(".//item")
    if elementi:
        for it in elementi:
            titolo = _testo(it.find("title"))
            collegamento = _testo(it.find("link"))
            if not titolo or not collegamento:
                continue
            sommario = _pulisci_html(_testo(it.find("description")))
            data = _data_iso(_testo(it.find("pubDate")) or
                             _testo(it.find("dc:date", spazi)))
            notizie.append({
                "titolo": titolo,
                "sommario": sommario[:220],
                "collegamento": collegamento,
                "data": data,
                "fonte": fonte,
                "categoria": classifica(titolo, sommario),
            })
        return notizie

    # Formato Atom
    for it in radice.findall("atom:entry", spazi) or radice.findall(".//{*}entry"):
        titolo = _testo(it.find("atom:title", spazi)) or _testo(it.find("{*}title"))
        col = it.find("atom:link", spazi)
        if col is None:
            col = it.find("{*}link")
        collegamento = col.get("href") if col is not None else ""
        if not titolo or not collegamento:
            continue
        sommario = _pulisci_html(
            _testo(it.find("atom:summary", spazi)) or _testo(it.find("{*}summary")))
        data = _data_iso(_testo(it.find("atom:updated", spazi)) or
                         _testo(it.find("{*}updated")))
        notizie.append({
            "titolo": titolo,
            "sommario": sommario[:220],
            "collegamento": collegamento,
            "data": data,
            "fonte": fonte,
            "categoria": classifica(titolo, sommario),
        })
    return notizie


def riguarda(notizia, squadre, parole_campionato):
    """Decide se una notizia riguarda un dato campionato.

    Il criterio è la presenza del nome di una squadra o di un termine
    che identifica il campionato. Senza questo filtro le notizie di
    mercato inonderebbero tutte le sezioni.
    """
    testo = _senza_accenti(f"{notizia.get('titolo','')} {notizia.get('sommario','')}")
    for p in parole_campionato:
        if _senza_accenti(p) in testo:
            return True
    for s in squadre:
        s = _senza_accenti(s)
        if len(s) < 3:
            continue
        if re.search(r"\b" + re.escape(s) + r"\b", testo):
            return True
    return False


def deduplica(notizie):
    """Toglie i doppioni: la stessa notizia compare su più feed."""
    visti = {}
    for n in notizie:
        chiave = _senza_accenti(n["titolo"])[:80]
        if chiave not in visti:
            visti[chiave] = n
    ordinate = sorted(visti.values(), key=lambda x: x.get("data") or "", reverse=True)
    return ordinate


def smonta_sommario(notizie):
    """Toglie il sommario prima di salvare.

    Il testo del sommario serve a classificare la notizia e a capire di
    quale campionato parli, ma è materiale della testata: si usa durante
    l'elaborazione e non finisce nell'archivio. Restano titolo, data,
    fonte e collegamento, che è quanto un aggregatore può mostrare.
    """
    for n in notizie:
        n.pop("sommario", None)
    return notizie
