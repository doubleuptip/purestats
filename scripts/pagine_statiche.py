"""Pagine statiche per Google (22/11/2026).

Il sito è una pagina unica: articoli e racconti si aprono con indirizzi #articolo=… e #leggenda=…,
che Google non indicizza come pagine separate. Questo script scrive, dagli stessi file pubblici:

  docs/a/<id>.html     una pagina per ogni articolo (docs/articoli/<id>.json)
  docs/l/<id>.html     una pagina per ogni racconto (docs/leggende/racconti.json)
  docs/sitemap.xml     elenco delle pagine da indicizzare
  docs/robots.txt      con l'indirizzo della sitemap (vale solo alla radice del dominio)
  docs/404.html        pagina «non trovata»
  docs/archivio.html   tutti gli articoli e i racconti, dal più recente (25/11/2026)
  docs/chi-siamo.html  chi fa il sito, fonti, come sono fatti gli articoli (25/11/2026)
  docs/nfl/...         pagine NFL (25/11/2026, solo NFL: il college dopo il passaggio a CollegeFootballData):
                       week/<stagione>-<N>.html, squadre/<sigla>.html, classifica.html, calendario.html

Le pagine NFL leggono solo file pubblici già in docs/ (data_nfl.json, home_nfl.json, tv_italia.json, stemmi.json,
indici di articoli e racconti): nessuna fonte nuova, nessuna chiamata. Ogni pagina nuova ha dateModified, e la data
(anche il lastmod della sitemap) cambia SOLO se il contenuto è cambiato rispetto al file già scritto: i giri ripetuti
non cambiano nulla. Si rifanno nel workflow NFL (update-nfl.yml) e in pagine-statiche.yml.

L'indirizzo di base viene da docs/CNAME (dominio proprio) o, se manca, da quello di GitHub Pages:
aggiungendo il CNAME le pagine si aggiornano da sole al giro successivo.

Legge SOLO file già pubblici (articoli e racconti): niente dati della parte privata. Un controllo si
ferma se nel testo compaiono parole della parte privata (Charlie, Matchup, spread...).
Scrive tutto in una cartella temporanea e sostituisce i file solo se è andato tutto bene.

Uso: python scripts/pagine_statiche.py
"""
import html
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(RADICE, "docs")
BASE_GITHUB = "https://doubleuptip.github.io/purestats/"
VIETATE = re.compile(r"\b(charlie|matchup|spread|bet365|snai|sisal|bookmaker|mercato americano|scommess\w*|over/under|contro la linea)\b", re.I)


def base_sito():
    """Dominio proprio da docs/CNAME, altrimenti l'indirizzo di GitHub Pages (sempre con / finale)."""
    try:
        with open(os.path.join(DOCS, "CNAME"), encoding="utf-8") as f:
            dominio = f.read().strip()
        if dominio:
            return "https://" + dominio.strip("/") + "/"
    except FileNotFoundError:
        pass
    return BASE_GITHUB


def leggi_json(percorso):
    with open(percorso, encoding="utf-8") as f:
        return json.load(f)


def e(testo):
    return html.escape(str(testo or ""), quote=True)


def descrizione(paragrafi, massimo=155):
    testo = " ".join(paragrafi or []).strip()
    if len(testo) <= massimo:
        return testo
    taglio = testo[:massimo].rsplit(" ", 1)[0]
    return taglio.rstrip(",.;:") + "…"


def nomi_squadre():
    """Sigla → nome completo dai dati pubblici del sito (NFL e college)."""
    nomi = {}
    for lega, file in (("nfl", "data_nfl.json"), ("college", "data_college.json")):
        try:
            dati = leggi_json(os.path.join(DOCS, file))
        except (FileNotFoundError, json.JSONDecodeError) as err:
            print(f"Avviso: {file} non leggibile ({err}), uso le sigle al posto dei nomi.")
            continue
        for s in dati.get("squadre") or []:
            if s.get("nome"):
                nomi[(lega, s["nome"])] = s.get("nomeCompleto") or s["nome"]
    return nomi


def credito_foto(c):
    if not c:
        return ""
    if isinstance(c, str):
        return "Foto dello stadio: " + e(c)
    autore, lic = e(c.get("autore")), e(c.get("licenza"))
    if c.get("licenzaUrl"):
        lic = f'<a href="{e(c["licenzaUrl"])}" rel="license noopener">{lic}</a>'
    testo = f"Foto dello stadio: {autore} · {lic}"
    if c.get("pagina"):
        testo += f' · <a href="{e(c["pagina"])}" rel="noopener">Wikimedia Commons</a>'
    return testo


# Tema (22/11/2026, scelta di Valerio): scuro per tutti, bottone per il chiaro, scelta ricordata in localStorage
# «purestats_tema» (stesso codice di index.html, duelli.html, accesso.html e privacy.html).
TEMA_TESTA = '<meta name="theme-color" content="#0B0F1A" id="coloreTema">\n<script>/* Tema (22/11/2026, scelta di Valerio): scuro per tutti; il bottone passa al chiaro e la scelta resta su questo dispositivo (localStorage «purestats_tema», seconda eccezione alla regola). */\n(function(){var t="scuro";try{if(localStorage.getItem("purestats_tema")==="chiaro")t="chiaro"}catch(e){}document.documentElement.dataset.tema=t;if(t==="chiaro")document.getElementById("coloreTema").content="#E9EDF2"})();\nfunction cambiaTema(){var r=document.documentElement,t=r.dataset.tema==="chiaro"?"scuro":"chiaro";r.dataset.tema=t;try{localStorage.setItem("purestats_tema",t)}catch(e){}document.getElementById("coloreTema").content=t==="chiaro"?"#E9EDF2":"#0B0F1A";document.dispatchEvent(new Event("tema"))}</script>\n'
TEMA_BOTTONE = '<button type="button" class="tema-btn" onclick="cambiaTema()" aria-label="Passa dal tema scuro al chiaro e viceversa" title="Tema chiaro / scuro"><svg class="t-sole" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg><svg class="t-luna" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7z"/></svg></button>'

STILE = """
:root{--fondo:#E9EDF2;--carta:#fff;--testo:#0B1428;--tenue:#5B6476;--acc:#C8102E;--bordo:#D5DBE3}
html:not([data-tema="chiaro"]){--fondo:#0B1428;--carta:#121D35;--testo:#E8ECF3;--tenue:#9AA5B8;--acc:#EF4444;--bordo:#22304F}
*{box-sizing:border-box}
body{margin:0;background:var(--fondo);color:var(--testo);font:17px/1.65 Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header,main,footer{max-width:760px;margin:0 auto;padding:0 16px}
body.largo header,body.largo main,body.largo footer{max-width:900px}
h1,h2,.marchio{font-family:"Barlow Condensed",Inter,sans-serif;letter-spacing:.01em}
html[data-tema="chiaro"] h1,html[data-tema="chiaro"] h2,html[data-tema="chiaro"] .marchio{font-family:Archivo,Inter,sans-serif;letter-spacing:0}
header{display:flex;justify-content:space-between;align-items:center;gap:14px;padding-top:18px;padding-bottom:18px}
.apri{margin-left:auto}
.tema-btn{flex:none;width:34px;height:34px;border-radius:50%;border:1px solid currentColor;background:transparent;color:inherit;display:inline-flex;align-items:center;justify-content:center;cursor:pointer;padding:0;margin:0;opacity:.55;transition:opacity .15s}.tema-btn:hover,.tema-btn:focus-visible{opacity:1}.tema-btn svg{width:17px;height:17px;display:block}html:not([data-tema="chiaro"]) .t-luna,html[data-tema="chiaro"] .t-sole{display:none}
.marchio{font-weight:800;letter-spacing:.06em;color:var(--testo);text-decoration:none;font-size:20px}
.marchio span{color:var(--acc)}
.apri{color:var(--acc);font-weight:600;text-decoration:none;font-size:15px}
article{background:var(--carta);border:1px solid var(--bordo);border-radius:14px;overflow:hidden}
.copertina{height:10px}
.foto{width:100%;max-height:340px;object-fit:cover;display:block}
.corpo{padding:22px 24px 26px}
.occhiello{color:var(--acc);font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;margin:0 0 6px}
h1{font-size:30px;line-height:1.2;margin:0 0 10px}
.info{color:var(--tenue);font-size:14px;margin:0 0 18px}
.punteggio{font-size:22px;font-weight:800;margin:0 0 14px}
p{margin:0 0 16px}
.numeri{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:8px 0 20px;padding:0;list-style:none}
.numeri li{border:1px solid var(--bordo);border-radius:10px;padding:10px 12px;font-size:14px;color:var(--tenue)}
.numeri b{display:block;font-size:24px;color:var(--testo)}
.piede{font-size:13px;color:var(--tenue);border-top:1px solid var(--bordo);padding-top:14px;margin-top:8px}
.piede a,.corpo a{color:var(--acc)}
.bottone{display:inline-block;margin:6px 0 18px;padding:10px 16px;border-radius:10px;background:var(--acc);color:#fff!important;text-decoration:none;font-weight:600}
footer{color:var(--tenue);font-size:13px;padding-top:22px;padding-bottom:30px}
footer a{color:var(--tenue)}
h2{font-size:22px;line-height:1.25;margin:26px 0 10px}
.naviga{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:14px;margin:0 0 16px}
.naviga a{color:var(--acc);text-decoration:none;font-weight:600}
.elenco{list-style:none;padding:0;margin:0 0 8px}
.elenco li{border-top:1px solid var(--bordo);padding:10px 0}
.elenco li:first-child{border-top:0}
.elenco a{color:var(--testo);font-weight:600;text-decoration:none}
.elenco a:hover{color:var(--acc)}
.elenco small{display:block;color:var(--tenue);font-size:13px}
.gara{display:grid;grid-template-columns:1fr auto;gap:4px 12px;align-items:center}
.squadre-gara{display:flex;flex-direction:column;gap:4px}
.sq{display:flex;align-items:center;gap:8px;font-weight:600}
.sq a{color:var(--testo);text-decoration:none}
.sq a:hover{color:var(--acc)}
.sq.vince{font-weight:800}
.sq .pt{margin-left:auto;font-variant-numeric:tabular-nums;font-weight:800;min-width:2ch;text-align:right}
.st{display:inline-block;width:26px;height:26px;flex:none}
.st svg{width:100%;height:100%;display:block}
.st.grande{width:72px;height:72px}
.quando{color:var(--tenue);font-size:13px;text-align:right}
.dett{grid-column:1/-1;color:var(--tenue);font-size:13px;display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center}
.dett a{color:var(--acc)}
.bollino{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.04em;padding:2px 7px;border-radius:999px;border:1px solid var(--acc);color:var(--acc)}
.tabella{width:100%;border-collapse:collapse;font-size:15px;font-variant-numeric:tabular-nums;margin:0 0 10px}
.tabella th{font-size:12px;color:var(--tenue);text-align:right;font-weight:600;padding:6px 6px;border-bottom:1px solid var(--bordo)}
.tabella td{text-align:right;padding:8px 6px;border-bottom:1px solid var(--bordo)}
.tabella th:first-child,.tabella td:first-child{text-align:left}
.tabella td:first-child a{color:var(--testo);text-decoration:none;font-weight:600;display:inline-flex;align-items:center;gap:8px}
.tabella td:first-child a:hover{color:var(--acc)}
.scorri{overflow-x:auto}
.testa-squadra{display:flex;align-items:center;gap:16px;margin:0 0 12px}
.testa-squadra h1{margin:0}
.nota{color:var(--tenue);font-size:14px}
@media (max-width:520px){h1{font-size:24px}.corpo{padding:18px 16px 20px}.tabella{font-size:14px}.tabella .facolt{display:none}.gara{grid-template-columns:1fr}.quando{text-align:left;grid-row:2}.st.grande{width:56px;height:56px}}
"""


def radice_di(percorso):
    """Prefisso relativo per tornare alla radice del sito da una pagina («a/x.html» → «../»)."""
    return "../" * percorso.count("/")


def pagina(base, percorso, titolo, desc, corpo, ld=None, immagine=None, tipo_og="article", apri=None,
           fonti=None, largo=False):
    """Pagina completa. «apri» = indirizzo nel sito (relativo alla radice, es. «#vista=partite»);
    «fonti» = riga delle fonti nel piede; largo = colonna più ampia (tabelle)."""
    url = base + percorso
    r = radice_di(percorso)
    img = immagine or base + "brand/anteprima-link-scuro.png"
    ld_txt = ""
    if ld:
        ld_txt = '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("</", "<\\/") + "</script>\n"
    piede_fonti = f"<br>{fonti}" if fonti else ""
    modificato = '<br>Pagina aggiornata il @@MODIFICATO_IT@@' if "@@MODIFICATO@@" in json.dumps(ld or {}) else ""
    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(titolo)} · PureStats</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:type" content="{tipo_og}">
<meta property="og:site_name" content="PureStats">
<meta property="og:title" content="{e(titolo)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{e(img)}">
<meta property="og:locale" content="it_IT">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{r}icona.svg" type="image/svg+xml">
<link href="{r}font/font.css" rel="stylesheet">
{TEMA_TESTA}<style>{STILE}</style>
{ld_txt}</head>
<body{' class="largo"' if largo else ''}>
<header><a class="marchio" href="{r}">PURE<span>STATS</span></a><a class="apri" href="{r}{e(apri or '')}">Apri nel sito →</a>{TEMA_BOTTONE}</header>
<main>
{corpo}
</main>
<footer>PureStats · statistiche NFL e college football · <a href="{r}">pagina principale</a> · <a href="{r}nfl/calendario.html">calendario NFL</a> · <a href="{r}nfl/classifica.html">classifica NFL</a> · <a href="{r}archivio.html">archivio</a> · <a href="{r}chi-siamo.html">chi siamo</a> · <a href="{r}privacy.html">privacy</a>{piede_fonti}{modificato}</footer>
</body>
</html>
"""


def pagina_articolo(base, a, nomi):
    lega = a.get("lega", "nfl")
    nome = lambda s: nomi.get((lega, s), s)
    ospite, casa = nome(a.get("ospite")), nome(a.get("casa"))
    tipo = "Cronaca" if a.get("tipo") == "cronaca" else "Anteprima"
    campionato = "College football" if lega == "college" else "NFL"
    sett = f" · Week {a['settimana']}" if a.get("settimana") else ""
    quando = ""
    if a.get("dataIt"):
        g = datetime.strptime(a["dataIt"], "%Y-%m-%d").strftime("%d/%m/%Y")
        quando = f" · {g}" + (f", ore {e(a['oraIt'])} italiane" if a.get("oraIt") else "")
    luogo = f" · {e(a['stadio'])}" if a.get("stadio") else ""
    punteggio = ""
    if a.get("punti"):
        p = a["punti"]
        punteggio = f'<p class="punteggio">{e(ospite)} {e(p.get("ospite"))} – {e(p.get("casa"))} {e(casa)}</p>'
    paragrafi = "\n".join(f"<p>{e(x)}</p>" for x in a.get("paragrafi") or [])
    c = a.get("colori") or {}
    striscia = f'<div class="copertina" style="background:linear-gradient(90deg,{e(c.get("ospite","#0B1428"))} 50%,{e(c.get("casa","#C8102E"))} 50%)"></div>'
    foto = f'<img class="foto" src="../{e(a["foto"])}" alt="{e(a.get("stadio") or "Stadio")}" loading="lazy">' if a.get("foto") else ""
    video = ""
    if a.get("video"):
        video = f'<a class="bottone" href="https://www.youtube.com/watch?v={e(a["video"])}" rel="noopener">▶ Highlights su YouTube</a>'
    fonte = "ESPN e SP+ (CollegeFootballData)" if lega == "college" else "nflverse (CC BY 4.0)"
    pubbl = a.get("pubblicato", "")
    corpo = f"""<article>
{striscia}{foto}
<div class="corpo">
<p class="occhiello">{tipo} · {campionato}{sett}</p>
<h1>{e(a.get("titolo"))}</h1>
<p class="info">{e(ospite)} @ {e(casa)}{quando}{luogo}</p>
{punteggio}
{paragrafi}
{video}
<a class="bottone" href="../#articolo={e(a["id"])}">Leggi su PureStats con meteo e numeri</a>
<div class="piede">Articolo scritto con l'aiuto di Claude (Anthropic) su dati {fonte}, verificati prima della pubblicazione.
{credito_foto(a.get("fotoCrediti"))}</div>
</div>
</article>"""
    titolo = a.get("titolo") or f"{ospite} @ {casa}"
    desc = descrizione(a.get("paragrafi"))
    immagine = base + a["foto"] if a.get("foto") else None
    ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": titolo[:110],
          "description": desc, "inLanguage": "it", "datePublished": pubbl,
          "author": {"@type": "Organization", "name": "PureStats"},
          "publisher": {"@type": "Organization", "name": "PureStats"},
          "mainEntityOfPage": base + f"a/{a['id']}.html"}
    if immagine:
        ld["image"] = [immagine]
    return pagina(base, f"a/{a['id']}.html", titolo, desc, corpo, ld, immagine)


def pagina_racconto(base, r):
    col = r.get("colori") or ["#0B1428", "#C8102E"]
    numeri = "".join(f"<li><b>{e(n[0])}</b>{e(n[1])}</li>" for n in r.get("numeri") or [] if len(n) >= 2)
    paragrafi = [f"<p>{e(x)}</p>" for x in r.get("paragrafi") or []]
    v = r.get("video") or {}
    if v.get("url"):
        bott = f'<a class="bottone" href="{e(v["url"])}" rel="noopener">▶ Guarda il video · {e(v.get("fonte") or "")}</a>'
        paragrafi.insert(len(paragrafi) // 2, bott)
    fonti = " · ".join(f'<a href="{e(f.get("url"))}" rel="noopener">{e(f.get("titolo"))}</a>' for f in r.get("fonti") or [])
    campionato = "College football" if r.get("lega") == "college" else "NFL"
    corpo = f"""<article>
<div class="copertina" style="height:14px;background:linear-gradient(90deg,{e(col[0])},{e(col[-1])})"></div>
<div class="corpo">
<p class="occhiello">Leggende · {campionato}{(" · " + e(r["anni"])) if r.get("anni") else ""}</p>
<h1>{e(r.get("titolo"))}</h1>
<p class="info">{e(r.get("occhiello"))}{(" · " + e(r["sottoGrande"])) if r.get("sottoGrande") else ""}</p>
{f'<ul class="numeri">{numeri}</ul>' if numeri else ""}
{chr(10).join(paragrafi)}
<a class="bottone" href="../#leggenda={e(r["id"])}">Leggi su PureStats con il grafico</a>
<div class="piede">Fonti: {fonti or "—"}. Testo di PureStats; le voci Wikipedia sono CC BY-SA.</div>
</div>
</article>"""
    desc = descrizione(r.get("paragrafi"))
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": (r.get("titolo") or "")[:110],
          "description": desc, "inLanguage": "it",
          "author": {"@type": "Organization", "name": "PureStats"},
          "mainEntityOfPage": base + f"l/{r['id']}.html"}
    return pagina(base, f"l/{r['id']}.html", r.get("titolo") or r["id"], desc, corpo, ld)


def pagina_404(base):
    # servita a qualunque profondità: i collegamenti sono assoluti
    radice = re.sub(r"^https://[^/]+", "", base)
    return f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pagina non trovata · PureStats</title><meta name="robots" content="noindex">
<link rel="icon" href="{radice}icona.svg" type="image/svg+xml"><link href="{radice}font/font.css" rel="stylesheet">{TEMA_TESTA}<style>{STILE}</style></head>
<body><header><a class="marchio" href="{radice}">PURE<span>STATS</span></a>{TEMA_BOTTONE}</header>
<main><article><div class="corpo"><p class="occhiello">Errore 404</p><h1>Questa pagina non esiste</h1>
<p>L'indirizzo potrebbe essere sbagliato o la pagina è stata spostata.</p>
<a class="bottone" href="{radice}">Torna a PureStats</a> <a href="{radice}archivio.html">Archivio</a> · <a href="{radice}privacy.html">Privacy</a></div></article></main></body></html>
"""


# ---------------------------------------------------------------------------------------------------------------
# Pagine NFL, archivio e Chi siamo (25/11/2026, scelta di Valerio del 22/11: solo NFL, il college a dicembre)
# ---------------------------------------------------------------------------------------------------------------

# Controllo più severo per le pagine nuove (testo scritto da noi): nessun termine da scommesse.
VIETATE_NUOVE = re.compile(r"\b(linea|linee|totali?|over|under|quot[ae]|favorit[aeio]|bookmaker|mercato|"
                           r"scommess\w*|spread|charlie|matchup|bet365|snai|sisal|pronostic\w*)\b", re.I)
SEGNAPOSTO = "@@MODIFICATO@@"
SEGNAPOSTO_IT = "@@MODIFICATO_IT@@"
FONTE_NFL = 'Dati: <a href="https://github.com/nflverse" rel="noopener">nflverse</a> (CC BY 4.0) · orari italiani calcolati da PureStats'
FONTE_TV = 'TV in Italia: notizie di DAZN Italia'
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
GIORNI_BREVI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]
TURNI_PLAYOFF = {"WC": "Wild Card", "DIV": "Divisional round", "CON": "Finali di conference", "SB": "Super Bowl"}


def controlla_nuova(testo, dove):
    """Pagine nuove: testo senza CSS, cercando anche i termini da scommesse più comuni."""
    pulito = re.sub(r"<style>.*?</style>", " ", testo, flags=re.S)
    pulito = re.sub(r"<script>/\* Tema.*?</script>", " ", pulito, flags=re.S)
    m = VIETATE_NUOVE.search(pulito) or VIETATE.search(pulito)
    if m:
        raise SystemExit(f"Fermato: «{m.group(0)}» in {dove}. Le pagine pubbliche non devono contenere "
                         "termini della parte privata o delle scommesse; nessun file è stato cambiato.")


def _lum(colore):
    h = (colore or "#555555").lstrip("#")
    try:
        c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError:
        c = [1 / 3] * 3
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


class Stemmi:
    """Stemma PureStats «opzione B, pastiglia a due toni» come svgStemma in index.html (mai loghi ufficiali)."""

    def __init__(self, dati):
        self.dati = dati or {}
        self.n = 0

    def svg(self, sigla, grande=False):
        x = self.dati.get(sigla) or {}
        sig, c1, c2 = x.get("s") or sigla, x.get("c1") or "#555555", x.get("c2") or "#FFFFFF"
        t = "#111827" if _lum(c1) > 0.42 else "#FFFFFF"
        n = len(sig)
        self.n += 1
        ident = f"st{self.n}"
        fs = 44 if n <= 2 else 38 if n == 3 else 30 if n == 4 else 25
        y = 65 if n <= 2 else 63 if n == 3 else 61
        b = c2
        if abs(_lum(b) - _lum(c1)) < 0.06:
            b = "#111827" if _lum(c1) > 0.5 else "#FFFFFF"
        return (f'<span class="st{" grande" if grande else ""}"><svg viewBox="0 0 100 100" aria-hidden="true">'
                f'<defs><clipPath id="{ident}"><circle cx="50" cy="50" r="46"/></clipPath></defs>'
                f'<g clip-path="url(#{ident})"><rect width="100" height="100" fill="{e(c1)}"/>'
                f'<path d="M100 58 L100 100 L30 100 Z" fill="{e(b)}"/></g>'
                f'<circle cx="50" cy="50" r="46" fill="none" stroke="{e(b)}" stroke-width="4"/>'
                f'<text x="50" y="{y}" text-anchor="middle" font-family="\'Barlow Condensed\',sans-serif" font-weight="800" '
                f'font-size="{fs}" fill="{t}" letter-spacing="-1">{e(sig)}</text></svg></span>')


def data_lunga(data_it):
    d = datetime.strptime(data_it, "%Y-%m-%d")
    return f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month - 1]} {d.year}"


def data_breve(data_it):
    d = datetime.strptime(data_it, "%Y-%m-%d")
    return f"{GIORNI_BREVI[d.weekday()]} {d.day:02d}/{d.month:02d}"


def quando_it(p, breve=True):
    if not p.get("dataIt"):
        return "data da definire"
    giorno = data_breve(p["dataIt"]) if breve else data_lunga(p["dataIt"])
    return giorno + (f", ore {p['oraIt']}" if p.get("oraIt") else ", orario da definire")


def inizio_iso(p):
    """Inizio con il fuso di Roma (ora legale compresa); senza zoneinfo o senza ora resta solo la data."""
    if not p.get("dataIt"):
        return None
    if not p.get("oraIt"):
        return p["dataIt"]
    try:
        from zoneinfo import ZoneInfo
        d = datetime.strptime(p["dataIt"] + " " + p["oraIt"], "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("Europe/Rome"))
        return d.isoformat()
    except Exception:
        return p["dataIt"]


def giocata(p):
    return p.get("pc") is not None and p.get("po") is not None


def nome_turno(tipo, settimana):
    return f"Week {settimana}" if tipo == "REG" else TURNI_PLAYOFF.get(tipo, f"Turno {settimana}")


class DatiNFL:
    """Tutto quello che serve alle pagine NFL, dai file pubblici già in docs/."""

    def __init__(self, indice_articoli):
        self.d = leggi_json(os.path.join(DOCS, "data_nfl.json"))
        try:
            self.tv = leggi_json(os.path.join(DOCS, "tv_italia.json")).get("settimane") or {}
        except (FileNotFoundError, json.JSONDecodeError) as err:
            print(f"Avviso: tv_italia.json non leggibile ({err}): pagine senza i bollini DAZN.")
            self.tv = {}
        try:
            self.stemmi = Stemmi(leggi_json(os.path.join(DOCS, "stemmi.json")).get("nfl"))
        except (FileNotFoundError, json.JSONDecodeError) as err:
            print(f"Avviso: stemmi.json non leggibile ({err}): stemmi grigi con la sola sigla.")
            self.stemmi = Stemmi({})
        self.squadre = {s["nome"]: s for s in self.d.get("squadre") or []}
        tutte = self.d.get("ultimePartite") or []
        self.stagione = max((p["stagione"] for p in tutte), default=None)
        self.partite = sorted([p for p in tutte if p["stagione"] == self.stagione],
                              key=lambda p: (int(p["settimana"]), p.get("dataIt") or "9", p.get("oraIt") or "99:99",
                                             p["ospite"]))
        self.settimane = []
        for p in self.partite:
            if p["settimana"] not in self.settimane:
                self.settimane.append(p["settimana"])
        # week in corso = la prima con partite ancora da giocare; le pagine arrivano fino a lei
        self.in_corso = next((w for w in self.settimane if any(not giocata(p) for p in self.della(w))), None)
        ultima = self.settimane.index(self.in_corso) if self.in_corso else len(self.settimane) - 1
        self.con_pagina = self.settimane[:ultima + 1]
        self.articoli = {}
        for a in indice_articoli:
            if a.get("lega", "nfl") != "nfl":
                continue
            chiave = (str(a.get("stagione")), str(a.get("settimana")), a.get("ospite"), a.get("casa"))
            self.articoli.setdefault(chiave, []).append(a)

    def della(self, settimana):
        return [p for p in self.partite if p["settimana"] == settimana]

    def tipo_di(self, settimana):
        return (self.della(settimana) or [{}])[0].get("tipo", "REG")

    def nome(self, sigla):
        return (self.squadre.get(sigla) or {}).get("nomeCompleto") or sigla

    def inclusa_dazn(self, p):
        s = self.tv.get(f"{p['stagione']}|{p['settimana']}") or {}
        return bool((s.get("incluse") or {}).get(f"{p['ospite']}@{p['casa']}"))

    def articoli_di(self, p):
        return self.articoli.get((p["stagione"], p["settimana"], p["ospite"], p["casa"]), [])

    def stagione_di(self, sigla):
        s = self.squadre.get(sigla) or {}
        return next((x for x in s.get("perStagione") or [] if x.get("stagione") == self.stagione), None)

    def ordine(self, sigle):
        """Ordine del sito (vista Classifica): % vittorie, poi differenza punti, poi nome."""
        def chiave(sig):
            x = self.stagione_di(sig) or {}
            return (-(x.get("percVittorie") or 0), -(x.get("differenza") or 0), sig)
        return sorted(sigle, key=chiave)


def riga_gara(n, p, r, con_week=False):
    """Una partita: squadre con stemma, punteggio se giocata, data e ora italiane, bollino DAZN, articoli."""
    fatta = giocata(p)
    righe = []
    for lato, punti, avv in (("ospite", p.get("po"), p.get("pc")), ("casa", p.get("pc"), p.get("po"))):
        sig = p[lato]
        vince = fatta and punti > avv
        pt = f'<span class="pt">{e(punti)}</span>' if fatta else ""
        righe.append(f'<div class="sq{" vince" if vince else ""}">{n.stemmi.svg(sig)}'
                     f'<a href="{r}nfl/squadre/{e(sig)}.html">{e(n.nome(sig))}</a>'
                     f'{"" if lato == "ospite" else " <small class=nota>(casa)</small>"}{pt}</div>')
    stato = "Finale" if fatta else quando_it(p)
    dett = []
    if fatta:
        dett.append(e(quando_it(p)))
    if con_week:
        w = p["settimana"]
        if w in n.con_pagina:
            dett.append(f'<a href="{r}nfl/week/{e(n.stagione)}-{e(w)}.html">{e(nome_turno(p.get("tipo", "REG"), w))}</a>')
        else:
            dett.append(e(nome_turno(p.get("tipo", "REG"), w)))
    if p.get("stadio"):
        dett.append(e(p["stadio"]))
    if n.inclusa_dazn(p):
        dett.append('<span class="bollino" title="Inclusa anche negli abbonamenti DAZN Sports, Full e Family">INCLUSA IN DAZN</span>')
    for a in sorted(n.articoli_di(p), key=lambda a: a.get("tipo") != "anteprima"):
        etichetta = "Leggi la cronaca" if a.get("tipo") == "cronaca" else "Leggi l'anteprima"
        dett.append(f'<a href="{r}a/{e(a["id"])}.html">{etichetta}</a>')
    return (f'<li class="gara"><div class="squadre-gara">{"".join(righe)}</div>'
            f'<div class="quando">{e(stato)}</div><div class="dett">{" · ".join(dett)}</div></li>')


def evento_ld(n, p, base):
    ev = {"@type": "SportsEvent", "name": f"{n.nome(p['ospite'])} @ {n.nome(p['casa'])}", "sport": "American football",
          "awayTeam": {"@type": "SportsTeam", "name": n.nome(p["ospite"]), "url": base + f"nfl/squadre/{p['ospite']}.html"},
          "homeTeam": {"@type": "SportsTeam", "name": n.nome(p["casa"]), "url": base + f"nfl/squadre/{p['casa']}.html"}}
    if inizio_iso(p):
        ev["startDate"] = inizio_iso(p)
    if p.get("stadio"):
        ev["location"] = {"@type": "Place", "name": p["stadio"]}
    return ev


def ld_pagina(base, percorso, tipo, nome, desc, **altro):
    ld = {"@context": "https://schema.org", "@type": tipo, "name": nome, "description": desc, "inLanguage": "it",
          "url": base + percorso, "dateModified": SEGNAPOSTO,
          "isPartOf": {"@type": "WebSite", "name": "PureStats", "url": base},
          "publisher": {"@type": "Organization", "name": "PureStats", "url": base}}
    ld.update(altro)
    return ld


def naviga(n, r, attuale=None):
    voci = [("nfl/calendario.html", "Calendario"), ("nfl/classifica.html", "Classifica")]
    if n.in_corso:
        voci.append((f"nfl/week/{n.stagione}-{n.in_corso}.html", f"Week {n.in_corso}"))
    voci.append(("archivio.html", "Articoli e racconti"))
    return '<nav class="naviga" aria-label="NFL">' + "".join(
        f'<a href="{r}{e(h)}">{e(t)}</a>' for h, t in voci if h != attuale) + "</nav>"


def pagina_week(base, n, w):
    percorso = f"nfl/week/{n.stagione}-{w}.html"
    r = radice_di(percorso)
    partite = n.della(w)
    turno = nome_turno(n.tipo_di(w), w)
    fatte = [p for p in partite if giocata(p)]
    titolo = f"NFL {turno} {n.stagione}: risultati e orari italiani"
    if len(fatte) == len(partite):
        stato = f"Tutte le {len(partite)} partite giocate."
    elif fatte:
        stato = f"{len(fatte)} partite giocate su {len(partite)}."
    else:
        stato = f"{len(partite)} partite in programma."
    giorni = sorted({p["dataIt"] for p in partite if p.get("dataIt")})
    periodo = f"dal {data_lunga(giorni[0])} al {data_lunga(giorni[-1])}" if len(giorni) > 1 else (
        f"il {data_lunga(giorni[0])}" if giorni else "")
    desc = (f"Tutte le partite della {turno} NFL {n.stagione} con data e ora italiane"
            + (", punteggi" if fatte else "") + ", articoli e partite incluse in DAZN. " + stato)
    i = n.settimane.index(w)
    prima = n.settimane[i - 1] if i > 0 else None
    dopo = n.settimane[i + 1] if i + 1 < len(n.settimane) and n.settimane[i + 1] in n.con_pagina else None
    frecce = []
    if prima:
        frecce.append(f'<a href="{r}nfl/week/{n.stagione}-{prima}.html">← {e(nome_turno(n.tipo_di(prima), prima))}</a>')
    if dopo:
        frecce.append(f'<a href="{r}nfl/week/{n.stagione}-{dopo}.html">{e(nome_turno(n.tipo_di(dopo), dopo))} →</a>')
    con_dazn = any(n.inclusa_dazn(p) for p in partite)
    nota_tv = ("In Italia tutte le partite NFL si vedono su DAZN con NFL Game Pass"
               + ("; il bollino «Inclusa in DAZN» segna quelle comprese anche negli abbonamenti DAZN Sports, Full e Family."
                  if con_dazn else "."))
    corpo = f"""<article><div class="corpo">
<p class="occhiello">NFL · Stagione {e(n.stagione)}</p>
<h1>{e(turno)} {e(n.stagione)}: risultati e orari italiani</h1>
<p class="info">{e(periodo)} · {e(stato)} Orari in ora italiana.</p>
{naviga(n, r)}
<ul class="elenco">{"".join(riga_gara(n, p, r) for p in partite)}</ul>
<p class="nota">{e(nota_tv)}</p>
<nav class="naviga">{"".join(frecce)}</nav>
</div></article>"""
    ld = ld_pagina(base, percorso, "CollectionPage", titolo, desc, mainEntity={
        "@type": "ItemList", "numberOfItems": len(partite),
        "itemListElement": [{"@type": "ListItem", "position": k + 1, "item": evento_ld(n, p, base)}
                            for k, p in enumerate(partite)]})
    return percorso, pagina(base, percorso, titolo, desc, corpo, ld, tipo_og="website", apri="#vista=partite",
                            fonti=FONTE_NFL + " · " + FONTE_TV)


def pagina_squadra(base, n, sig):
    percorso = f"nfl/squadre/{sig}.html"
    r = radice_di(percorso)
    s = n.squadre[sig]
    nome = n.nome(sig)
    st = n.stagione_di(sig) or {}
    sue = [p for p in n.partite if sig in (p["casa"], p["ospite"])]
    fatte = [p for p in sue if giocata(p)]
    future = [p for p in sue if not giocata(p)]
    div = s.get("division") or ""
    compagne = n.ordine([x for x, y in n.squadre.items() if y.get("division") == div]) if div else []
    pos = compagne.index(sig) + 1 if sig in compagne else None
    bil = ""
    if st:
        bil = f"{st.get('vittorie', 0)}-{st.get('sconfitte', 0)}" + (f"-{st['pareggi']}" if st.get("pareggi") else "")
    numeri = []
    if st:
        numeri = [(bil, "bilancio (vinte-perse" + ("-pari)" if st.get("pareggi") else ")")),
                  (st.get("puntiFatti"), f"punti fatti · {numIt(st.get('mediaFatti'))} a partita"),
                  (st.get("puntiSubiti"), f"punti subiti · {numIt(st.get('mediaSubiti'))} a partita"),
                  (("+" if (st.get("differenza") or 0) > 0 else "") + str(st.get("differenza")), "differenza punti")]
        if st.get("partiteCasa") is not None:
            numeri.append((f"{st.get('vittorieCasa')}/{st.get('partiteCasa')}", "vinte in casa"))
        if st.get("partiteFuori") is not None:
            numeri.append((f"{st.get('vittorieFuori')}/{st.get('partiteFuori')}", "vinte in trasferta"))
        if pos:
            numeri.append((f"{pos}ª", f"nella {div}"))
    lis = "".join(f"<li><b>{e(a)}</b>{e(b)}</li>" for a, b in numeri if a is not None)
    ultime = list(reversed(fatte))[:5]
    prossime = future[:5]
    articoli = sorted({a["id"]: a for p in sue for a in n.articoli_di(p)}.values(),
                      key=lambda a: a.get("pubblicato") or "", reverse=True)
    storia = "".join(
        f"<tr><td>{e(x['stagione'])}</td><td>{e(x.get('vittorie'))}-{e(x.get('sconfitte'))}"
        f"{'-' + e(x['pareggi']) if x.get('pareggi') else ''}</td><td>{numIt(x.get('mediaFatti'))}</td>"
        f"<td>{numIt(x.get('mediaSubiti'))}</td><td>{('+' if (x.get('differenza') or 0) > 0 else '') + str(x.get('differenza'))}</td></tr>"
        for x in s.get("perStagione") or [])
    div_righe = "".join(
        f'<li><a href="{r}nfl/squadre/{e(x)}.html">{e(n.nome(x))}</a> <small>{e(bilancio(n, x))}</small></li>'
        for x in compagne if x != sig)
    titolo = f"{nome}: risultati, calendario e orari italiani {n.stagione}"
    desc = (f"{nome} nella stagione NFL {n.stagione}" + (f": bilancio {bil}, {st.get('puntiFatti')} punti fatti e "
            f"{st.get('puntiSubiti')} subiti" if st else "") + ". Ultime partite, prossime partite in ora italiana e articoli.")
    corpo = f"""<article><div class="corpo">
<p class="occhiello">NFL · {e(div)} · Stagione {e(n.stagione)}</p>
<div class="testa-squadra">{n.stemmi.svg(sig, grande=True)}<h1>{e(nome)}</h1></div>
{naviga(n, r)}
{f'<ul class="numeri">{lis}</ul>' if lis else ''}
<h2>Ultime partite</h2>
{f'<ul class="elenco">{"".join(riga_gara(n, p, r, True) for p in ultime)}</ul>' if ultime else '<p class="nota">Nessuna partita giocata in questa stagione.</p>'}
<h2>Prossime partite</h2>
{f'<ul class="elenco">{"".join(riga_gara(n, p, r, True) for p in prossime)}</ul>' if prossime else '<p class="nota">Nessuna partita in programma.</p>'}
{('<h2>Articoli</h2><ul class="elenco">' + "".join(f'<li><a href="{r}a/{e(a["id"])}.html">{e(a.get("titolo"))}</a><small>{"Cronaca" if a.get("tipo") == "cronaca" else "Anteprima"} · Week {e(a.get("settimana"))}</small></li>' for a in articoli) + '</ul>') if articoli else ''}
{f'<h2>La {e(div)}</h2><ul class="elenco">{div_righe}</ul>' if div_righe else ''}
<h2>Stagione per stagione</h2>
<div class="scorri"><table class="tabella"><thead><tr><th>Stagione</th><th>V-S</th><th>Punti fatti a partita</th><th>Punti subiti a partita</th><th>Differenza</th></tr></thead><tbody>{storia}</tbody></table></div>
<p class="nota">Stagioni presenti nell'archivio PureStats ({e(n.d['stagioni'][-1] if n.d.get('stagioni') else '')}–{e(n.stagione)}).</p>
</div></article>"""
    ld = ld_pagina(base, percorso, "ProfilePage", titolo, desc, mainEntity={
        "@type": "SportsTeam", "name": nome, "sport": "American football", "url": base + percorso,
        "memberOf": {"@type": "SportsOrganization", "name": f"NFL · {div}" if div else "NFL"}},
        subjectOf=[evento_ld(n, p, base) for p in prossime[:3]])
    return percorso, pagina(base, percorso, titolo, desc, corpo, ld, tipo_og="website",
                            apri=f"#squadra={sig}", fonti=FONTE_NFL + " · " + FONTE_TV)


def numIt(x):
    if x is None:
        return "—"
    t = f"{float(x):.1f}".replace(".", ",")
    return t[:-2] if t.endswith(",0") else t


def bilancio(n, sig):
    st = n.stagione_di(sig) or {}
    if not st:
        return ""
    return f"{st.get('vittorie', 0)}-{st.get('sconfitte', 0)}" + (f"-{st['pareggi']}" if st.get("pareggi") else "")


def tabella_classifica(n, r, sigle):
    righe = []
    for k, sig in enumerate(n.ordine(sigle), 1):
        st = n.stagione_di(sig) or {}
        dif = st.get("differenza")
        righe.append(
            f'<tr><td><a href="{r}nfl/squadre/{e(sig)}.html">{n.stemmi.svg(sig)}{e(n.nome(sig))}</a></td>'
            f"<td>{e(st.get('vittorie'))}</td><td>{e(st.get('sconfitte'))}</td><td class=\"facolt\">{e(st.get('pareggi'))}</td>"
            f"<td>{numIt(st.get('percVittorie'))}</td><td class=\"facolt\">{e(st.get('puntiFatti'))}</td>"
            f"<td class=\"facolt\">{e(st.get('puntiSubiti'))}</td><td>{('+' if (dif or 0) > 0 else '') + str(dif) if dif is not None else '—'}</td></tr>")
    return ('<div class="scorri"><table class="tabella"><thead><tr><th>Squadra</th><th>V</th><th>S</th>'
            '<th class="facolt">P</th><th>% V</th><th class="facolt">PF</th><th class="facolt">PS</th><th>Diff</th>'
            '</tr></thead><tbody>' + "".join(righe) + "</tbody></table></div>")


def pagina_classifica(base, n):
    percorso = "nfl/classifica.html"
    r = radice_di(percorso)
    conf = n.d.get("conferences") or sorted({s.get("conference") for s in n.squadre.values() if s.get("conference")})
    blocchi = []
    for c in conf:
        dentro = [x for x, s in n.squadre.items() if s.get("conference") == c]
        divs = [d for d in (n.d.get("divisions") or []) if d.startswith(c)] or sorted(
            {n.squadre[x].get("division") for x in dentro})
        blocchi.append(f'<h2>{e(c)}</h2>' + "".join(
            f'<h3 class="occhiello" style="margin-top:16px">{e(d)}</h3>' +
            tabella_classifica(n, r, [x for x in dentro if n.squadre[x].get("division") == d]) for d in divs)
            + f'<h3 class="occhiello" style="margin-top:16px">{e(c)} · tutte le squadre</h3>' + tabella_classifica(n, r, dentro))
    titolo = f"Classifica NFL {n.stagione} per division e conference"
    desc = (f"Classifica NFL {n.stagione}: le 8 division e le due conference AFC e NFC con vittorie, sconfitte, "
            "percentuale di vittorie e punti fatti e subiti. Aggiornata dopo ogni giornata.")
    corpo = f"""<article><div class="corpo">
<p class="occhiello">NFL · Stagione {e(n.stagione)}</p>
<h1>Classifica NFL {e(n.stagione)}</h1>
<p class="info">V vinte · S perse · P pareggi · % V percentuale di vittorie · PF e PS punti fatti e subiti · Diff differenza punti.</p>
{naviga(n, r, percorso)}
{"".join(blocchi)}
<p class="nota">Ordine come nella pagina Classifica del sito: percentuale di vittorie, poi differenza punti. Gli spareggi ufficiali della NFL (scontri diretti, risultati nella division e nella conference) non sono applicati: a pari bilancio l'ordine può essere diverso da quello ufficiale.</p>
</div></article>"""
    ld = ld_pagina(base, percorso, "CollectionPage", titolo, desc, mainEntity={
        "@type": "ItemList", "numberOfItems": len(n.squadre),
        "itemListElement": [{"@type": "ListItem", "position": k + 1, "name": n.nome(x),
                             "url": base + f"nfl/squadre/{x}.html"} for k, x in enumerate(n.ordine(list(n.squadre)))]})
    return percorso, pagina(base, percorso, titolo, desc, corpo, ld, tipo_og="website", apri="#vista=squadre",
                            fonti=FONTE_NFL, largo=True)


def pagina_calendario(base, n):
    percorso = "nfl/calendario.html"
    r = radice_di(percorso)
    if n.in_corso:
        i = n.settimane.index(n.in_corso)
        settimane = n.settimane[i:i + 2]
    else:
        settimane = n.settimane[-1:]
    blocchi, eventi = [], []
    for w in settimane:
        partite = n.della(w)
        eventi += partite
        turno = nome_turno(n.tipo_di(w), w)
        tit = (f'<a href="{r}nfl/week/{e(n.stagione)}-{e(w)}.html">{e(turno)}</a>' if w in n.con_pagina else e(turno))
        per_giorno = {}
        for p in partite:
            per_giorno.setdefault(p.get("dataIt") or "", []).append(p)
        giorni = "".join(
            f'<h3 class="occhiello" style="margin-top:14px">{e(data_lunga(g) if g else "Data da definire")}</h3>'
            f'<ul class="elenco">{"".join(riga_gara(n, p, r) for p in ps)}</ul>' for g, ps in per_giorno.items())
        blocchi.append(f"<h2>{tit}</h2>{giorni}")
    nomi_w = " e ".join(nome_turno(n.tipo_di(w), w) for w in settimane)
    titolo = f"Calendario NFL {n.stagione} in ora italiana: {nomi_w}"
    desc = (f"Calendario NFL in ora italiana: tutte le partite della {nomi_w} {n.stagione} con giorno, orario, stadio "
            "e partite incluse in DAZN.")
    corpo = f"""<article><div class="corpo">
<p class="occhiello">NFL · Stagione {e(n.stagione)}</p>
<h1>Calendario NFL in ora italiana</h1>
<p class="info">La week in corso e la prossima, giorno per giorno. Orari in ora italiana.</p>
{naviga(n, r, percorso)}
{"".join(blocchi)}
<p class="nota">In Italia tutte le partite NFL si vedono su DAZN con NFL Game Pass; il bollino «Inclusa in DAZN» segna quelle comprese anche negli abbonamenti DAZN Sports, Full e Family, quando DAZN le ha annunciate.</p>
</div></article>"""
    ld = ld_pagina(base, percorso, "CollectionPage", titolo, desc, mainEntity={
        "@type": "ItemList", "numberOfItems": len(eventi),
        "itemListElement": [{"@type": "ListItem", "position": k + 1, "item": evento_ld(n, p, base)}
                            for k, p in enumerate(eventi)]})
    return percorso, pagina(base, percorso, titolo, desc, corpo, ld, tipo_og="website", apri="#vista=partite",
                            fonti=FONTE_NFL + " · " + FONTE_TV)


def pagina_archivio(base, articoli, racconti, nomi):
    percorso = "archivio.html"
    voci_a = sorted(articoli, key=lambda a: a.get("pubblicato") or "", reverse=True)
    voci_r = sorted(racconti, key=lambda x: x.get("pubblicato") or "", reverse=True)

    def quando(x):
        p = (x.get("pubblicato") or "")[:10]
        return data_lunga(p) if re.match(r"\d{4}-\d\d-\d\d$", p) else ""

    def riga_a(a):
        lega = a.get("lega", "nfl")
        camp = "College football" if lega == "college" else "NFL"
        tipo = "Cronaca" if a.get("tipo") == "cronaca" else "Anteprima"
        sq = f"{nomi.get((lega, a.get('ospite')), a.get('ospite'))} @ {nomi.get((lega, a.get('casa')), a.get('casa'))}"
        sett = f" · Week {a['settimana']}" if a.get("settimana") else ""
        q = quando(a)
        return (f'<li><a href="a/{e(a["id"])}.html">{e(a.get("titolo"))}</a>'
                f'<small>{tipo} · {camp}{e(sett)} · {e(sq)}{(" · " + e(q)) if q else ""}</small></li>')

    def riga_r(x):
        camp = "College football" if x.get("lega") == "college" else "NFL"
        q = quando(x)
        return (f'<li><a href="l/{e(x["id"])}.html">{e(x.get("titolo"))}</a>'
                f'<small>Leggende · {camp}{(" · " + e(x["anni"])) if x.get("anni") else ""}{(" · " + e(q)) if q else ""}</small></li>')

    titolo = "Archivio: articoli e racconti di PureStats"
    desc = (f"Tutti gli articoli di PureStats ({len(voci_a)} tra anteprime e cronache di NFL e college football) e i "
            f"{len(voci_r)} racconti delle Leggende, dal più recente.")
    corpo = f"""<article><div class="corpo">
<p class="occhiello">Archivio</p>
<h1>Articoli e racconti</h1>
<p class="info">Dal più recente. {len(voci_a)} articoli · {len(voci_r)} racconti delle Leggende.</p>
<nav class="naviga"><a href="nfl/calendario.html">Calendario NFL</a><a href="nfl/classifica.html">Classifica NFL</a><a href="chi-siamo.html">Chi siamo</a></nav>
<h2>Articoli</h2>
<ul class="elenco">{"".join(riga_a(a) for a in voci_a)}</ul>
<h2>Leggende</h2>
<ul class="elenco">{"".join(riga_r(x) for x in voci_r)}</ul>
</div></article>"""
    elementi = [base + f"a/{a['id']}.html" for a in voci_a] + [base + f"l/{x['id']}.html" for x in voci_r]
    ld = ld_pagina(base, percorso, "CollectionPage", titolo, desc, mainEntity={
        "@type": "ItemList", "numberOfItems": len(elementi),
        "itemListElement": [{"@type": "ListItem", "position": k + 1, "url": u} for k, u in enumerate(elementi)]})
    return percorso, pagina(base, percorso, titolo, desc, corpo, ld, tipo_og="website", apri="#vista=articoli")


def pagina_chi_siamo(base):
    percorso = "chi-siamo.html"
    titolo = "Chi siamo"
    desc = ("PureStats è un sito italiano di statistiche su NFL e college football: chi lo cura, da dove vengono i dati "
            "e come sono fatti gli articoli.")
    corpo = """<article><div class="corpo">
<p class="occhiello">PureStats</p>
<h1>Chi siamo</h1>
<p>PureStats è un sito italiano di statistiche sul football americano: la NFL e il college football. Lo cura
Valerio La Rocca, che ne è il titolare. Per scrivere: <a href="mailto:info@purestats.it">info@purestats.it</a>.</p>
<h2>Cosa trovi</h2>
<p>Risultati e calendario di ogni settimana con gli orari italiani, le classifiche, le statistiche di squadre e
giocatori partita per partita, il riassunto della giornata, anteprime e cronache delle partite più importanti e la
sezione Leggende, con i record e i racconti delle grandi storie del football. Il sito non chiede registrazioni e non
ha pubblicità.</p>
<h2>Da dove vengono i dati</h2>
<p>I dati della NFL (calendario, risultati, statistiche, azione per azione) vengono da
<a href="https://github.com/nflverse" rel="noopener">nflverse</a>, un progetto aperto distribuito con licenza
CC BY 4.0. Le medie, le classifiche e gli orari italiani sono calcolati da PureStats su questi dati. I numeri e le
carriere delle Leggende vengono dalle voci di Wikipedia (CC BY-SA), citate in ogni racconto; per i giocatori dal 1999
li confrontiamo con i dati di nflverse. Le foto degli stadi vengono da Wikimedia Commons, solo con licenze libere, e
ogni foto riporta autore e licenza. Le fonti del college football sono elencate nella pagina principale, in «Fonti e
condizioni d'uso». Gli stemmi delle squadre sono disegnati da PureStats con sigla e colori: il sito non usa i loghi
ufficiali.</p>
<h2>Come sono fatti gli articoli</h2>
<p>Anteprime e cronache sono scritte con l'aiuto di Claude, l'intelligenza artificiale di Anthropic, partendo da un
elenco di fatti preparato dai dati. Prima della pubblicazione ogni numero e ogni nome viene controllato su quei dati,
e le notizie (infortuni, cambi di formazione) sulle fonti citate: un articolo che contiene un numero o un nome che non
torna non viene pubblicato. Ogni articolo è firmato PureStats e porta la data di pubblicazione.</p>
<h2>Dove trovare tutto</h2>
<p><a href="archivio.html">Archivio di articoli e racconti</a> · <a href="nfl/calendario.html">Calendario NFL in ora
italiana</a> · <a href="nfl/classifica.html">Classifica NFL</a> · <a href="privacy.html">Informativa privacy</a></p>
</div></article>"""
    ld = ld_pagina(base, percorso, "AboutPage", titolo + " · PureStats", desc, mainEntity={
        "@type": "Organization", "name": "PureStats", "url": base, "email": "info@purestats.it",
        "logo": base + "icona-512.png", "founder": {"@type": "Person", "name": "Valerio La Rocca"}})
    return percorso, pagina(base, percorso, titolo, desc, corpo, ld, tipo_og="website", apri="")


def con_data(percorso, testo, oggi):
    """Mette la data di modifica: quella del file già scritto se il contenuto è identico, altrimenti oggi."""
    vecchio_file = os.path.join(DOCS, percorso)
    if os.path.exists(vecchio_file):
        with open(vecchio_file, encoding="utf-8") as f:
            vecchio = f.read()
        m = re.search(r'"dateModified": "(\d{4}-\d\d-\d\d)"', vecchio)
        if m and metti_data(testo, m.group(1)) == vecchio:
            return vecchio, m.group(1)
    return metti_data(testo, oggi), oggi


def metti_data(testo, data):
    g = datetime.strptime(data, "%Y-%m-%d")
    return testo.replace(SEGNAPOSTO_IT, f"{g.day:02d}/{g.month:02d}/{g.year}").replace(SEGNAPOSTO, data)


def pagine_nuove(base, indice, racconti, nomi):
    """Tutte le pagine nuove come lista (percorso, testo con segnaposto della data)."""
    pagine = [pagina_archivio(base, indice, racconti, nomi), pagina_chi_siamo(base)]
    try:
        n = DatiNFL(indice)
    except (FileNotFoundError, json.JSONDecodeError) as err:
        raise SystemExit(f"Fermato: data_nfl.json non leggibile ({err}); nessun file è stato cambiato.")
    if not n.partite:
        raise SystemExit("Fermato: data_nfl.json non ha partite della stagione in corso; nessun file è stato cambiato.")
    for w in n.con_pagina:
        pagine.append(pagina_week(base, n, w))
    for sig in sorted(n.squadre):
        pagine.append(pagina_squadra(base, n, sig))
    pagine.append(pagina_classifica(base, n))
    pagine.append(pagina_calendario(base, n))
    print(f"Pagine NFL: stagione {n.stagione}, {len(n.con_pagina)} week (in corso: {n.in_corso}), "
          f"{len(n.squadre)} squadre, classifica e calendario.")
    return pagine


def controlla(testo, dove):
    m = VIETATE.search(testo)
    if m:
        raise SystemExit(f"Fermato: «{m.group(0)}» in {dove}. Le pagine pubbliche non devono contenere "
                         "termini della parte privata o delle scommesse; nessun file è stato cambiato.")


def main():
    base = base_sito()
    nomi = nomi_squadre()
    oggi = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    indice = leggi_json(os.path.join(DOCS, "articoli", "indice.json"))
    racconti = leggi_json(os.path.join(DOCS, "leggende", "racconti.json")).get("racconti") or []

    tmp = tempfile.mkdtemp(prefix="pagine_")
    try:
        os.makedirs(os.path.join(tmp, "a"))
        os.makedirs(os.path.join(tmp, "l"))
        url_sitemap = [(base + "privacy.html", None)]

        for voce in indice:
            percorso = os.path.join(DOCS, "articoli", voce["id"] + ".json")
            if not os.path.exists(percorso):
                print(f"Avviso: {voce['id']} è nell'indice ma il file manca, saltato.")
                continue
            a = leggi_json(percorso)
            testo = pagina_articolo(base, a, nomi)
            controlla(" ".join([a.get("titolo") or ""] + (a.get("paragrafi") or [])), f"articolo {a['id']}")
            with open(os.path.join(tmp, "a", a["id"] + ".html"), "w", encoding="utf-8") as f:
                f.write(testo)
            url_sitemap.append((base + f"a/{a['id']}.html", (a.get("pubblicato") or oggi)[:10]))

        for r in racconti:
            controlla(" ".join([r.get("titolo") or ""] + (r.get("paragrafi") or [])), f"racconto {r['id']}")
            with open(os.path.join(tmp, "l", r["id"] + ".html"), "w", encoding="utf-8") as f:
                f.write(pagina_racconto(base, r))
            url_sitemap.append((base + f"l/{r['id']}.html", (r.get("pubblicato") or "")[:10] or None))

        # pagine nuove (25/11/2026): la data cambia solo se il contenuto è cambiato
        nuove = pagine_nuove(base, indice, racconti, nomi)
        for percorso, testo in nuove:
            controlla_nuova(testo, percorso)
            testo, data = con_data(percorso, testo, oggi)
            dest = os.path.join(tmp, percorso)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(testo)
            url_sitemap.append((base + percorso, data))
        # pagina principale: la data più recente fra le pagine (niente data nuova a ogni giro)
        url_sitemap.insert(0, (base, max(d for _, d in url_sitemap if d)))

        righe = "\n".join(f"  <url><loc>{html.escape(u)}</loc>" + (f"<lastmod>{d}</lastmod>" if d else "") + "</url>"
                          for u, d in url_sitemap)
        with open(os.path.join(tmp, "sitemap.xml"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + righe + "\n</urlset>\n")
        with open(os.path.join(tmp, "robots.txt"), "w", encoding="utf-8") as f:
            f.write("User-agent: *\nAllow: /\n\nSitemap: " + base + "sitemap.xml\n")
        with open(os.path.join(tmp, "404.html"), "w", encoding="utf-8") as f:
            f.write(pagina_404(base))

        # tutto pronto: si sostituiscono le cartelle e i file
        for cartella in ("a", "l", "nfl"):
            dest = os.path.join(DOCS, cartella)
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            shutil.move(os.path.join(tmp, cartella), dest)
        for nome in ("sitemap.xml", "robots.txt", "404.html", "archivio.html", "chi-siamo.html"):
            shutil.move(os.path.join(tmp, nome), os.path.join(DOCS, nome))
        cambiate = sum(1 for _, d in url_sitemap[1:] if d == oggi)
        print(f"Pagine statiche: {len(url_sitemap) - 1} ({len(indice)} articoli in indice, {len(racconti)} racconti, "
              f"{len(nuove)} pagine nuove di cui {sum(1 for p, _ in nuove if p.startswith('nfl/'))} NFL), base {base}. "
              f"Con data di oggi nella sitemap: {cambiate}.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
