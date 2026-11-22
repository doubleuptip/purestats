"""Pagine statiche per Google (22/11/2026).

Il sito è una pagina unica: articoli e racconti si aprono con indirizzi #articolo=… e #leggenda=…,
che Google non indicizza come pagine separate. Questo script scrive, dagli stessi file pubblici:

  docs/a/<id>.html     una pagina per ogni articolo (docs/articoli/<id>.json)
  docs/l/<id>.html     una pagina per ogni racconto (docs/leggende/racconti.json)
  docs/sitemap.xml     elenco delle pagine da indicizzare
  docs/robots.txt      con l'indirizzo della sitemap (vale solo alla radice del dominio)
  docs/404.html        pagina «non trovata»

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
VIETATE = re.compile(r"\b(charlie|matchup|spread|bet365|snai|sisal|quota del bookmaker|over/under)\b", re.I)


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


STILE = """
:root{--fondo:#E9EDF2;--carta:#fff;--testo:#0B1428;--tenue:#5B6476;--acc:#C8102E;--bordo:#D5DBE3}
@media (prefers-color-scheme:dark){:root{--fondo:#0B1428;--carta:#121D35;--testo:#E8ECF3;--tenue:#9AA5B8;--acc:#EF4444;--bordo:#22304F}}
*{box-sizing:border-box}
body{margin:0;background:var(--fondo);color:var(--testo);font:17px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header,main,footer{max-width:760px;margin:0 auto;padding:0 16px}
header{display:flex;justify-content:space-between;align-items:center;padding-top:18px;padding-bottom:18px}
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
@media (max-width:520px){h1{font-size:24px}.corpo{padding:18px 16px 20px}}
"""


def pagina(base, percorso, titolo, desc, corpo, ld=None, immagine=None, tipo_og="article"):
    url = base + percorso
    img = immagine or base + "brand/anteprima-link-scuro.png"
    ld_txt = ""
    if ld:
        ld_txt = '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("</", "<\\/") + "</script>\n"
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
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="../icona.svg" type="image/svg+xml">
<style>{STILE}</style>
{ld_txt}</head>
<body>
<header><a class="marchio" href="../">PURE<span>STATS</span></a><a class="apri" href="../">Apri il sito →</a></header>
<main>
{corpo}
</main>
<footer>PureStats · statistiche NFL e college football · <a href="../">pagina principale</a></footer>
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
<link rel="icon" href="{radice}icona.svg" type="image/svg+xml"><style>{STILE}</style></head>
<body><header><a class="marchio" href="{radice}">PURE<span>STATS</span></a></header>
<main><article><div class="corpo"><p class="occhiello">Errore 404</p><h1>Questa pagina non esiste</h1>
<p>L'indirizzo potrebbe essere sbagliato o la pagina è stata spostata.</p>
<a class="bottone" href="{radice}">Torna a PureStats</a></div></article></main></body></html>
"""


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
        url_sitemap = [(base, oggi)]

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
            url_sitemap.append((base + f"l/{r['id']}.html", None))

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
        for cartella in ("a", "l"):
            dest = os.path.join(DOCS, cartella)
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            shutil.move(os.path.join(tmp, cartella), dest)
        for nome in ("sitemap.xml", "robots.txt", "404.html"):
            shutil.move(os.path.join(tmp, nome), os.path.join(DOCS, nome))
        print(f"Pagine statiche: {len(url_sitemap) - 1} ({len(indice)} articoli in indice, {len(racconti)} racconti), "
              f"base {base}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
