"""Contenuti per Instagram e Facebook (PureStats, dal 28/11/2026, scelta di Valerio).

Prepara le immagini (1080×1350) e i reel dai dati PUBBLICI del sito e le mette in una coda; il server le propone a
Valerio su Telegram e le pubblica solo dopo il suo ✅ (server/purestats_social.py). Niente scommesse, niente Charlie,
niente linee: solo i dati che il sito mostra a tutti.

Contenuti (una volta ciascuno, chiave in «fatti»):
  guida|<data>            guida «NFL in TV in Italia» dalle 9 di oggi alle 9 di domani (giorni con partite)
  carte|<data>            le carte 2187 uscite oggi (fronte e retro) + reel della prima carta (8 secondi, si gira)
  leggenda|<id>           racconto nuovo delle Leggende (copertina, numeri, grafico, chiusura)
  anteprima|<id>          anteprima NFL nuova (copertina con lo stadio, chi c'è in campo, meteo e link)
  cronaca|<id>            cronaca NFL nuova (risultato, protagonisti)
  risultati|<st>|<week>   risultati di una week NFL completa (copertina, punteggi, migliori)
  accadde|<data>          accadde oggi (partita più importante della data dal 1999)
  corsa|<st>|<week>       corsa ai playoff AFC e NFC (dalla week 10)

Uso:  python3 scripts/social.py <cartella del ramo «social»> [--prova]
Il workflow social.yml porta la cartella del ramo «social» (coda.json + file degli ultimi 7 giorni), lancia lo
script e ripubblica il ramo da zero (un solo commit: la storia non cresce). Con --prova rifà tutto in /tmp senza
guardare «fatti». Solo Chrome senza finestra e ffmpeg (presenti sui server di GitHub), libreria standard Python.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pagine_statiche import Stemmi, VIETATE_NUOVE  # noqa: E402

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(RADICE, "docs")
ROMA, EST = ZoneInfo("Europe/Rome"), ZoneInfo("America/New_York")
ADESSO = (datetime.fromisoformat(os.environ["SOCIAL_ADESSO"]) if os.environ.get("SOCIAL_ADESSO")   # prove
          else datetime.now(timezone.utc))
OGGI = ADESSO.astimezone(ROMA).date()
GIORNI_TENUTI = 7                         # file sul ramo «social»; le chiavi in «fatti» restano 60 giorni
FIRMA_AI = "Personaggio immaginario · immagine creata con AI"
ORO = "#E8B64C"
GIORNI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]
LOGO = ('<svg class="logo" viewBox="84 96 350 272"><g fill="#F5F7FB"><rect x="110" y="285" width="44" height="51" rx="5"/>'
        '<rect x="174" y="248" width="44" height="88" rx="5"/><rect x="302" y="164" width="44" height="172" rx="5"/>'
        '<rect x="90" y="344" width="337" height="16" rx="5"/></g><g fill="#EF4444" stroke="#EF4444">'
        '<rect x="238" y="208" width="44" height="128" rx="5"/><rect x="366" y="104" width="44" height="232" rx="5"/>'
        '<polyline points="95,172 133,172 150,147 170,190 190,116 210,186 228,162 258,162" fill="none" stroke-width="13" '
        'stroke-linejoin="round" stroke-linecap="round"/><circle cx="262" cy="163" r="13"/></g></svg>')
e = lambda x: html.escape(str(x))


def leggi(percorso, vuoto=None):
    try:
        with open(os.path.join(R, percorso), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as x:
        print(f"{percorso} non letto ({x}): i contenuti che ne dipendono saltano questo giro")
        return vuoto


D = leggi("data_nfl.json", {}) or {}
H = leggi("home_nfl.json", {}) or {}
ST = Stemmi((leggi("stemmi.json", {}) or {}).get("nfl"))
NOMI = {k: v.get("breve") or k for k, v in (D.get("loghi") or {}).items()}


def nome(s):
    return NOMI.get(s) or s


def quando(data_it):
    d = datetime.strptime(data_it, "%Y-%m-%d")
    return f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month - 1]}"


def inizio(p):
    try:
        return datetime.fromisoformat(f"{p['data']}T{p.get('ora') or '13:00'}").replace(tzinfo=EST).astimezone(timezone.utc)
    except (KeyError, ValueError):
        return None


def stemma(s, px):
    return ST.svg(s).replace('class="st"', f'class="st" style="width:{px}px;height:{px}px"')


# ------------------------------------------------------------------ impaginazione e foto
BASE = """<!DOCTYPE html><html><head><meta charset="utf-8"><link rel="stylesheet" href="file://%s/font/font.css"><style>
*{margin:0;padding:0;box-sizing:border-box}
body{width:%dpx;height:%dpx;overflow:hidden;background:#0B0F1A;color:#F5F7FB;font-family:Inter,sans-serif;position:relative}
.testa{position:absolute;top:0;left:0;right:0;display:flex;align-items:center;gap:16px;padding:44px 64px 0}
.logo{width:62px;height:48px}.marca{font:800 34px 'Barlow Condensed';letter-spacing:2px}.marca i{font-style:normal;color:#EF4444}
.etic{margin-left:auto;font:700 20px Inter;letter-spacing:3px;color:#A3ADC2;text-transform:uppercase}
.piede{position:absolute;left:64px;right:64px;bottom:48px;display:flex;justify-content:space-between;align-items:center;
 font:700 22px Inter;letter-spacing:2px;color:#A3ADC2;text-transform:uppercase}.piede b{color:#F5F7FB}
.piede .pag{display:flex;gap:8px}.piede .pag span{width:12px;height:12px;border-radius:6px;background:#232C42}
.piede .pag span.on{background:#EF4444;width:34px}
h1{font:800 104px/0.92 'Barlow Condensed';text-transform:uppercase;letter-spacing:1px}
.rosso{color:#EF4444}.sotto{font:600 30px/1.35 Inter;color:#A3ADC2}
.st{display:inline-block;width:64px;height:64px}.st svg{width:100%%;height:100%%}
%s</style></head><body>%s</body></html>"""


def testata(etichetta, colore=""):
    st = f' style="color:{colore}"' if colore else ""
    return f'<div class="testa">{LOGO}<div class="marca">PURE<i>STATS</i></div><div class="etic"{st}>{e(etichetta)}</div></div>'


def piede(n, tot):
    pag = "".join(f'<span class="{"on" if i == n else ""}"></span>' for i in range(1, tot + 1)) if tot > 1 else ""
    return f'<div class="piede"><div><b>purestats.it</b> · link in bio</div><div class="pag">{pag}</div></div>'


def chrome():
    for n in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(n):
            return n
    sys.exit("Chrome non trovato: serve per fotografare le immagini")


def fotografa(destinazione, css, corpo, larghezza=1080, altezza=1350):
    """Una pagina HTML → JPEG. Si ferma se Chrome non produce un'immagine credibile."""
    with tempfile.TemporaryDirectory() as t:
        sorgente, foto = os.path.join(t, "p.html"), os.path.join(t, "p.jpeg")
        with open(sorgente, "w", encoding="utf-8") as f:
            f.write(BASE % (R, larghezza, altezza, css, corpo))
        r = subprocess.run([chrome(), "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                            "--allow-file-access-from-files", f"--window-size={larghezza},{altezza}",
                            "--virtual-time-budget=4000", "--screenshot=" + foto, "file://" + sorgente],
                           capture_output=True, text=True, timeout=120)
        if not os.path.exists(foto) or os.path.getsize(foto) < 15000:
            raise RuntimeError(f"Chrome non ha prodotto {os.path.basename(destinazione)}: {r.stderr[-300:]}")
        shutil.move(foto, destinazione)


# ------------------------------------------------------------------ contenuti
class Voce:
    """Un contenuto da proporre: chiave unica, slide da fotografare, didascalia, scadenza."""

    def __init__(self, chiave, tipo, titolo, scade, didascalia, ai=False):
        self.chiave, self.tipo, self.titolo, self.scade, self.didascalia, self.ai = chiave, tipo, titolo, scade, didascalia, ai
        self.slide = []          # (css, corpo)
        self.video = None        # funzione(destinazione)

    def cartella(self):
        return re.sub(r"[^A-Za-z0-9_-]+", "_", self.chiave)


def tag(*t):
    return " ".join("#" + x for x in t[:5])          # Instagram: al massimo 5 hashtag


def guida():
    da = datetime(OGGI.year, OGGI.month, OGGI.day, 9, tzinfo=ROMA)
    ps = sorted([(inizio(p), p) for p in D.get("ultimePartite") or [] if p.get("pc") is None and inizio(p)
                 and da <= inizio(p).astimezone(ROMA) < da + timedelta(days=1)], key=lambda x: x[0])
    if not ps or ADESSO >= ps[0][0]:
        return []
    tv = (leggi("tv_italia.json", {}) or {}).get("settimane") or {}
    righe, giorno = "", None
    for t, p in ps:
        loc = t.astimezone(ROMA)
        if loc.date() != giorno:
            giorno = loc.date()
            righe += f'<div class="gg">{e(quando(giorno.isoformat()))}{" · notte" if loc.hour < 6 else ""}</div>'
        inc = f'{p["ospite"]}@{p["casa"]}' in ((tv.get(f'{p["stagione"]}|{int(p["settimana"])}') or {}).get("incluse") or {})
        righe += (f'<div class="r"><div class="ora">{loc:%H:%M}</div><div class="sq">{ST.svg(p["ospite"])}<span class="n">'
                  f'{e(nome(p["ospite"]))}</span><span class="at">@</span>{ST.svg(p["casa"])}<span class="n">{e(nome(p["casa"]))}'
                  f'</span></div><span class="bol{" in" if inc else ""}">{"✓ Inclusa in DAZN" if inc else "NFL Game Pass"}</span></div>')
    alto = 67 if len(ps) > 8 else 82
    css = f""".tit{{position:absolute;top:140px;left:64px;right:64px}}.tit h1{{font-size:92px}}
.lista{{position:absolute;top:305px;left:64px;right:64px}}
.gg{{font:800 28px 'Barlow Condensed';letter-spacing:3px;color:#EF4444;text-transform:uppercase;margin:10px 0 6px}}
.r{{display:flex;align-items:center;gap:22px;height:{alto}px;border-top:1px solid #232C42}}
.ora{{font:800 40px 'Barlow Condensed';width:100px}}.sq{{display:flex;align-items:center;gap:12px;flex:1}}
.sq .st{{width:48px;height:48px}}.n{{font:700 28px Inter}}.at{{color:#A3ADC2;font:600 24px Inter;margin:0 4px}}
.bol{{font:700 18px Inter;letter-spacing:1px;padding:9px 14px;border-radius:10px;background:#1B2338;color:#A3ADC2;white-space:nowrap}}
.bol.in{{background:#EF4444;color:#fff}}"""
    sett = int(ps[0][1]["settimana"])
    v = Voce(f"guida|{OGGI.isoformat()}", "guida", f"Guida TV {quando(OGGI.isoformat())}", ps[0][0],
             f"📺 La NFL in TV in Italia: {quando(OGGI.isoformat()).lower()}, week {sett}.\n"
             f"Tutte su DAZN con NFL Game Pass; in rosso quelle incluse anche negli abbonamenti DAZN. Orari italiani.\n\n"
             f"Statistiche, anteprime e cronache su purestats.it (link in bio)\n\n{tag('NFL', 'NFLItalia', 'DAZN', 'FootballAmericano', 'PureStats')}")
    v.slide.append((css, testata(f"Guida TV · Week {sett}") + '<div class="tit"><h1>La NFL in TV <span class="rosso">in Italia</span></h1>'
                    '<div class="sotto" style="margin-top:14px">Tutte su DAZN con NFL Game Pass · orari italiani</div></div>'
                    f'<div class="lista">{righe}</div>' + piede(1, 1)))
    return [v]


def carte():
    lega = leggi("lega/lega.json", {}) or {}
    if not lega.get("pubblica"):
        return []
    oggi = [c for c in lega.get("carte") or [] if c.get("uscita") == OGGI.isoformat() and c.get("fronte")]
    if not oggi:
        return []
    css = f""".cop{{position:absolute;inset:0;background:radial-gradient(circle at 50% 45%,#3B2A0C 0,#0B0F1A 62%)}}
.k{{position:absolute;top:150px;left:64px;right:64px;display:flex;justify-content:space-between;align-items:flex-end}}
.k h1{{font-size:78px}}.k h1 span{{color:{ORO}}}.k .n{{font:800 30px 'Barlow Condensed';letter-spacing:3px;color:{ORO};border:2px solid {ORO};padding:8px 18px;border-radius:30px}}
.carta{{position:absolute;left:50%;top:300px;transform:translateX(-50%);height:820px;border-radius:26px;box-shadow:0 30px 80px rgba(0,0,0,.6),0 0 0 2px rgba(232,182,76,.35)}}
.sotto2{{position:absolute;left:64px;right:64px;top:1150px;text-align:center;font:600 25px/1.4 Inter;color:#C9D1E0}}
.ai{{position:absolute;left:64px;right:64px;top:1222px;text-align:center;font:600 18px Inter;letter-spacing:1px;color:#8A93A8}}"""
    oggi = oggi[:5]                                   # carosello: al massimo 10 immagini (fronte + retro)
    nomi = ", ".join(f'{c["nome"]} ({c["ruolo"]}, {c["squadra"]})' for c in oggi)
    v = Voce(f"carte|{OGGI.isoformat()}", "carte", f"Carte 2187 del {OGGI:%d/%m}", ADESSO + timedelta(days=2),
             f"⭐ 2187 · Lega della Terra Unita: {'la nuova carta' if len(oggi) == 1 else 'le nuove carte'} di oggi.\n{nomi}.\n\n"
             f"Il campionato di football del 2187 corre insieme alla stagione NFL: storie, Doni e carte su purestats.it "
             f"(link in bio).\n\n{FIRMA_AI}.\n\n{tag('2187', 'PureStats', 'FootballAmericano', 'Fantascienza', 'NFLItalia')}", ai=True)
    tot = 2 * len(oggi)
    for c in oggi:
        for lato in ("fronte", "retro"):
            img = f"file://{R}/" + c[lato].split("?")[0]
            testo = f'{e(c["nome"])} · {e(c["ruolo"])} · {e(c["squadra"])}' if lato == "fronte" else e(c.get("sintesi") or "")
            v.slide.append((css, '<div class="cop"></div>' + testata("2187 · Lega della Terra Unita", ORO) +
                            f'<div class="k"><h1>{"Nuova carta" if lato == "fronte" else "Il retro"} <span>2187</span></h1>'
                            f'<div class="n">Nº {c["n"]:03d} · {e(c.get("rarita") or "Comune")}</div></div><img class="carta" src="{img}">'
                            f'<div class="sotto2">{testo}</div><div class="ai">{FIRMA_AI}</div>' + piede(len(v.slide) + 1, tot)))
    c = oggi[0]
    r = Voce(f"reel|carta|{c['n']}", "reel", f"Reel carta Nº {c['n']:03d}", ADESSO + timedelta(days=2),
             f"⭐ Nuova carta 2187 · Nº {c['n']:03d}: {c['nome']}, {c['ruolo']} dei {c['squadra']}.\n{c.get('sintesi') or ''}\n\n"
             f"Tutte le carte su purestats.it (link in bio).\n\n{FIRMA_AI}.\n\n{tag('2187', 'PureStats', 'FootballAmericano', 'Fantascienza')}", ai=True)
    r.video = lambda dest, c=c: reel_carta(c, dest)
    return [v, r]


def reel_carta(c, dest):
    """Reel 1080×1920 di 8 secondi con solo ffmpeg: la carta entra dal basso, a 3,4 s si gira (fronte → retro)."""
    if not shutil.which("ffmpeg") and os.environ.get("GITHUB_ACTIONS"):
        # i server di GitHub (Ubuntu 24.04) non hanno più ffmpeg: si installa solo nei giri che fanno un reel
        print("ffmpeg mancante: lo installo per il reel")
        subprocess.run("sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg >/dev/null", shell=True, check=True, timeout=600)
    with tempfile.TemporaryDirectory() as t:
        fondo = os.path.join(t, "fondo.jpg")
        css = f""".t{{position:absolute;top:150px;left:0;right:0;text-align:center;font:800 120px/0.9 'Barlow Condensed';text-transform:uppercase}}
.t span{{color:{ORO}}}.s{{position:absolute;top:290px;left:0;right:0;text-align:center;font:700 30px Inter;letter-spacing:4px;color:{ORO};text-transform:uppercase}}
.p{{position:absolute;bottom:250px;left:0;right:0;text-align:center;font:800 54px 'Barlow Condensed';letter-spacing:2px}}.p i{{font-style:normal;color:#EF4444}}
.ai{{position:absolute;bottom:190px;left:0;right:0;text-align:center;font:600 24px Inter;color:#8A93A8}}
body{{background:radial-gradient(circle at 50% 45%,#3B2A0C 0,#0B0F1A 60%)}}"""
        fotografa(fondo, css, f'<div class="t">Nuova carta <span>2187</span></div><div class="s">Nº {c["n"]:03d} · {e(c["nome"])}</div>'
                              f'<div class="p">PURE<i>STATS</i>.IT · LINK IN BIO</div><div class="ai">{FIRMA_AI}</div>', 1080, 1920)
        fr, rt = (os.path.join(R, c[k].split("?")[0]) for k in ("fronte", "retro"))
        ch, cw = 1180, 843                              # carta 1125×1575 portata a 1180 di altezza
        giro = "abs(cos((t-3.4)*PI))"
        filtro = (f"[1:v]scale={cw}:{ch},format=rgba[f0];[2:v]scale={cw}:{ch},format=rgba[r0];"
                  f"[f0]scale=w='max(2,if(lt(t,3.4),{cw},{cw}*{giro}))':h={ch}:eval=frame[f];"
                  f"[r0]scale=w='max(2,if(lt(t,4.4),{cw}*{giro},{cw}))':h={ch}:eval=frame[r];"
                  f"[0:v][f]overlay=x='(W-w)/2':y='380+if(lt(t,0.8),700*pow(1-t/0.8,3),0)':enable='lt(t,3.9)':eval=frame[a];"
                  f"[a][r]overlay=x='(W-w)/2':y=380:enable='gte(t,3.9)':eval=frame,format=yuv420p[v]")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", "8", "-framerate", "30", "-i", fondo,
                        "-loop", "1", "-t", "8", "-framerate", "30", "-i", fr, "-loop", "1", "-t", "8", "-framerate", "30", "-i", rt,
                        "-filter_complex", filtro, "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-r", "30", "-movflags", "+faststart", dest], check=True, timeout=300)


def leggende():
    rr = leggi("leggende/racconti.json", []) or []
    rr = rr if isinstance(rr, list) else rr.get("racconti", [])
    out = []
    for r in rr:
        try:
            pub = datetime.fromisoformat(r.get("pubblicato") or "")
        except ValueError:
            continue
        if not (timedelta(0) <= ADESSO - pub <= timedelta(days=3)) or not r.get("numeri"):
            continue
        c1, c2 = (r.get("colori") or ["#1B2338", "#EF4444"])[:2]
        lega = "College" if r.get("lega") == "college" else "NFL"
        v = Voce(f"leggenda|{r['id']}", "leggenda", r["titolo"], ADESSO + timedelta(days=3),
                 f"📖 Leggende · {r['titolo']}.\n{r.get('occhiello') or ''}\n\nIl racconto completo, con il grafico e il video, "
                 f"su purestats.it (link in bio).\n\n{tag(lega, 'Leggende', 'StoriaNFL' if lega == 'NFL' else 'CollegeFootball', 'FootballAmericano', 'PureStats')}")
        tot = 4 if r.get("grafico", {}).get("tipo") == "stagione" else 3
        css1 = f""".cop{{position:absolute;inset:0;background:linear-gradient(150deg,{c1} 0%,#0B1E2A 62%,{c2} 140%)}}
.big{{position:absolute;right:-20px;top:90px;font:800 900px/0.8 'Barlow Condensed';color:transparent;-webkit-text-stroke:5px rgba(255,255,255,.35)}}
.anni{{position:absolute;left:64px;top:170px;font:800 30px 'Barlow Condensed';letter-spacing:3px;background:rgba(0,0,0,.35);padding:10px 22px;border-radius:30px}}
.vetro{{position:absolute;left:48px;right:48px;bottom:130px;background:rgba(11,15,26,.55);backdrop-filter:blur(18px);border:1px solid rgba(255,255,255,.18);border-radius:30px;padding:44px 48px}}
.vetro .k{{font:800 24px Inter;letter-spacing:4px;color:#F5F7FB;opacity:.8;text-transform:uppercase}}.vetro h1{{font-size:88px;margin:12px 0 18px}}
.vetro p{{font:500 29px/1.4 Inter;color:#E5EAF2}}"""
        v.slide.append((css1, f'<div class="cop"></div><div class="big">{e(r.get("grande") or "")}</div>' + testata("Leggende") +
                        f'<div class="anni">{e(r.get("anni") or "")}{" · " + e(r["sottoGrande"]) if r.get("sottoGrande") else ""}</div>'
                        f'<div class="vetro"><div class="k">Leggende · i racconti</div><h1>{e(r["titolo"])}</h1><p>{e(r.get("occhiello") or "")}</p></div>'
                        + piede(1, tot)))
        num = "".join(f'<div class="n"><b>{e(a)}</b><span>{e(b)}</span></div>' for a, b in r["numeri"][:4])
        css2 = f""".tit{{position:absolute;top:150px;left:64px}}.tit h1{{font-size:96px}}
.griglia{{position:absolute;top:400px;left:64px;right:64px;display:grid;grid-template-columns:1fr 1fr;gap:26px}}
.n{{background:#131A2B;border:1px solid #232C42;border-left:8px solid {c1};border-radius:24px;padding:40px 36px;height:330px;display:flex;flex-direction:column;justify-content:flex-end}}
.n b{{font:800 110px/0.9 'Barlow Condensed'}}.n span{{font:600 25px/1.35 Inter;color:#A3ADC2;margin-top:12px}}"""
        v.slide.append((css2, testata("Leggende · i numeri") + '<div class="tit"><h1>La storia<br><span class="rosso">in numeri</span></h1></div>'
                        f'<div class="griglia">{num}</div>' + piede(2, tot)))
        g = r.get("grafico") or {}
        if g.get("tipo") == "stagione" and g.get("barre"):
            mx = max(b[1] for b in g["barre"]) or 1
            barre = "".join(f'<div class="b{" on" if b[2] else ""}"><em>{e(b[1])}</em><div style="height:{b[1] / mx * 560:.0f}px"></div>'
                            f'<span>{e(str(b[0])[-2:])}</span></div>' for b in g["barre"])
            fonte = (g.get("fonte") or {}).get("titolo") or ""
            css3 = """.tit{position:absolute;top:150px;left:64px;right:64px}.tit h1{font-size:80px}
.graf{position:absolute;left:64px;right:64px;top:440px;height:700px;display:flex;align-items:flex-end;gap:10px}
.b{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%}
.b div{width:100%;background:#2A3550;border-radius:8px 8px 0 0}.b.on div{background:#EF4444}
.b em{font:800 26px 'Barlow Condensed';font-style:normal;color:#A3ADC2;margin-bottom:8px}.b.on em{color:#fff;font-size:44px}
.b span{font:700 19px Inter;color:#A3ADC2;margin-top:12px}.b.on span{color:#fff}
.fonte{position:absolute;left:64px;right:64px;top:1190px;font:500 19px Inter;color:#6B7690}"""
            v.slide.append((css3, testata("Leggende · il grafico") + f'<div class="tit"><h1>{e(g.get("titolo") or "")}</h1></div>'
                            f'<div class="graf">{barre}</div><div class="fonte">{"Fonte: " + e(fonte) if fonte else ""}</div>' + piede(3, tot)))
        css4 = f""".cop{{position:absolute;inset:0;background:radial-gradient(circle at 50% 35%,{c1}55 0,#0B0F1A 62%)}}
.c{{position:absolute;left:64px;right:64px;top:380px;text-align:center}}.c h1{{font-size:120px}}
.btn{{display:inline-block;margin-top:70px;background:#EF4444;color:#fff;font:800 40px 'Barlow Condensed';letter-spacing:2px;padding:24px 54px;border-radius:18px;box-shadow:0 14px 40px rgba(239,68,68,.35)}}"""
        v.slide.append((css4, '<div class="cop"></div>' + testata("Leggende") + '<div class="c"><h1>La storia<br><span class="rosso">completa</span></h1>'
                        '<div class="btn">PURESTATS.IT · LINK IN BIO</div></div>' + piede(tot, tot)))
        out.append(v)
    return out


def articoli():
    out = []
    for a in leggi("articoli/indice.json", []) or []:
        if a.get("lega") != "nfl" or a.get("tipo") not in ("anteprima", "cronaca"):
            continue
        try:
            pub = datetime.fromisoformat(a.get("pubblicato") or "")
        except ValueError:
            continue
        if not (timedelta(0) <= ADESSO - pub <= timedelta(days=2)):
            continue
        x = leggi(f"articoli/{a['id']}.json")
        if not x:
            continue
        try:
            via = datetime.fromisoformat(x["inizioUtc"])
        except (KeyError, ValueError):
            via = ADESSO + timedelta(days=1)
        if x["tipo"] == "anteprima" and via > ADESSO + timedelta(hours=1):
            out.append(anteprima(x, via))
        elif x["tipo"] == "cronaca" and x.get("punti"):
            out.append(cronaca(x))
    return out


def credito(x):
    cr = x.get("fotoCrediti") or {}
    return f'Foto: {cr.get("autore", "")} · {cr.get("licenza", "")} · Wikimedia Commons' if cr else ""


def anteprima(a, via):
    o, c = a["ospite"], a["casa"]
    v = Voce(f"anteprima|{a['id']}", "anteprima", a["titolo"], via - timedelta(minutes=30),
             f"🏈 L'anteprima · {nome(o)} @ {nome(c)}\n{a['titolo']}.\n{quando(a['dataIt'])} alle {a['oraIt']} (ora italiana), "
             f"{a['stadio']}.\n\nL'anteprima completa su purestats.it (link in bio).\n\n"
             f"{tag('NFL', 'NFLItalia', nome(o).replace(' ', ''), nome(c).replace(' ', ''), 'PureStats')}")
    foto = f"file://{R}/{a['foto']}" if a.get("foto") else ""
    css1 = f""".img{{position:absolute;inset:0;background:{"url('" + foto + "') center/cover" if foto else f"linear-gradient(150deg,{a['colori']['ospite']},#0B0F1A 55%,{a['colori']['casa']})"}}}
.vel{{position:absolute;inset:0;background:linear-gradient(180deg,rgba(11,15,26,.55) 0,rgba(11,15,26,.2) 30%,rgba(11,15,26,.92) 62%,#0B0F1A 100%)}}
.sq{{position:absolute;left:64px;right:64px;top:470px;display:flex;align-items:center;gap:22px;background:rgba(11,15,26,.78);border-radius:26px;padding:22px 28px}}
.sq .vs{{font:800 46px 'Barlow Condensed';color:#A3ADC2}}.sq .b{{font:800 40px/1.05 'Barlow Condensed';text-transform:uppercase}}
.sq .b span{{display:block;font:700 22px Inter;color:#C9D1E0;text-transform:none}}
.k{{position:absolute;left:64px;right:64px;top:690px}}.k .q{{font:800 26px Inter;letter-spacing:4px;color:#EF4444;text-transform:uppercase}}
.k h1{{font-size:84px;margin:14px 0 22px}}.k .w{{font:700 28px Inter;color:#C9D1E0}}
.cr{{position:absolute;right:64px;top:118px;font:500 15px Inter;color:rgba(255,255,255,.75)}}"""
    bil = a.get("bilanci") or {}
    v.slide.append((css1, '<div class="img"></div><div class="vel"></div>' + testata(f"Anteprima · Week {a['settimana']}") +
                    f'<div class="cr">{e(credito(a))}</div><div class="sq">{stemma(o, 120)}<div class="b">{e(nome(o))}<span>{e(bil.get("ospite", ""))}</span></div>'
                    f'<div class="vs">@</div>{stemma(c, 120)}<div class="b">{e(nome(c))}<span>{e(bil.get("casa", ""))}</span></div></div>'
                    f'<div class="k"><div class="q">L\'anteprima</div><h1>{e(a["titolo"])}</h1>'
                    f'<div class="w">{e(quando(a["dataIt"]))} · {e(a["oraIt"])} · {e(a["stadio"])}</div></div>' + piede(1, 3)))
    col = ""
    for s in (a.get("riquadro") or {}).get("squadre") or []:
        gg = "".join(f'<div class="g{" fuori" if g.get("stato") else ""}"><div class="r">{e(g["ruolo"])}'
                     f'{" · <b>" + e(g["stato"]) + "</b>" if g.get("stato") else ""}</div><div class="nm">{e(g["nome"])}</div>'
                     f'<div class="d">{" · ".join(e(x) + " " + e(t) for x, t in g["dati"])}</div></div>' for g in s["giocatori"][:3])
        pt = s.get("punti") or {}
        col += (f'<div class="col"><div class="tt">{stemma(s["sigla"], 64)}<div><b>{e(s["nome"])}</b><span>{e(s.get("bilancio", ""))}'
                f'{" · " + e(pt["fatti"]) + " punti fatti, " + e(pt["subiti"]) + " subiti a partita" if pt else ""}</span></div></div>{gg}</div>')
    css2 = """.tit{position:absolute;top:150px;left:64px}.tit h1{font-size:88px}
.due{position:absolute;top:390px;left:64px;right:64px;display:grid;grid-template-columns:1fr 1fr;gap:24px}
.col{background:#131A2B;border:1px solid #232C42;border-radius:24px;padding:28px}
.tt{display:flex;gap:16px;align-items:center;margin-bottom:12px}.tt b{display:block;font:800 40px 'Barlow Condensed';text-transform:uppercase}
.tt span{font:600 17px/1.3 Inter;color:#A3ADC2}
.g{border-top:1px solid #232C42;padding:18px 0}.r{font:700 16px Inter;letter-spacing:2px;color:#A3ADC2;text-transform:uppercase}
.r b{color:#fff;background:#EF4444;padding:2px 8px;border-radius:6px}.g.fuori .nm{text-decoration:line-through;text-decoration-color:#EF4444}
.nm{font:800 36px/1.1 'Barlow Condensed';text-transform:uppercase;margin:4px 0}.d{font:600 19px/1.35 Inter;color:#C9D1E0}"""
    v.slide.append((css2, testata(f"{o} @ {c}") + '<div class="tit"><h1>Chi c\'è<br><span class="rosso">in campo</span></h1></div>'
                    f'<div class="due">{col}</div>' + piede(2, 3)))
    m = a.get("meteo") or {}
    css3 = """.cop{position:absolute;inset:0;background:radial-gradient(circle at 50% 30%,#1B2338 0,#0B0F1A 62%)}
.met{position:absolute;top:220px;left:64px;right:64px;background:#131A2B;border:1px solid #232C42;border-radius:26px;padding:40px 44px}
.met .q{font:800 24px Inter;letter-spacing:4px;color:#EF4444;text-transform:uppercase}.met .v{display:flex;gap:56px;margin-top:20px}
.met b{display:block;font:800 76px 'Barlow Condensed'}.met span{font:700 18px Inter;letter-spacing:2px;color:#A3ADC2;text-transform:uppercase}
.c{position:absolute;left:64px;right:64px;top:700px;text-align:center}.c h1{font-size:110px}
.btn{display:inline-block;margin-top:50px;background:#EF4444;color:#fff;font:800 40px 'Barlow Condensed';letter-spacing:2px;padding:24px 54px;border-radius:18px}"""
    if a.get("coperto"):
        met = f'<div class="met"><div class="q">{e(a["stadio"])}</div><div class="v"><div><b>Coperto</b><span>si gioca al chiuso</span></div></div></div>'
    elif m.get("tempC") is not None:
        met = (f'<div class="met"><div class="q">Il meteo a {e(a["stadio"])}</div><div class="v"><div><b>{e(m["tempC"])}°</b><span>gradi</span></div>'
               f'<div><b>{e(m.get("ventoKmh", "–"))}</b><span>km/h di vento</span></div><div><b>{e(m.get("pioggia", "–"))}%</b><span>pioggia</span></div></div></div>')
    else:
        met = ""
    v.slide.append((css3, '<div class="cop"></div>' + testata("Meteo e anteprima") + met +
                    '<div class="c"><h1>L\'anteprima<br><span class="rosso">completa</span></h1><div class="btn">PURESTATS.IT · LINK IN BIO</div></div>' + piede(3, 3)))
    return v


def cronaca(a):
    o, c, p = a["ospite"], a["casa"], a["punti"]
    vo = p["ospite"] > p["casa"]
    v = Voce(f"cronaca|{a['id']}", "cronaca", a["titolo"], ADESSO + timedelta(days=2),
             f"🏁 Finale · {nome(o)} {p['ospite']}, {nome(c)} {p['casa']}\n{a['titolo']}.\n\nLa cronaca completa, i numeri e gli "
             f"highlights su purestats.it (link in bio).\n\n{tag('NFL', 'NFLItalia', nome(o).replace(' ', ''), nome(c).replace(' ', ''), 'PureStats')}")
    foto = f"file://{R}/{a['foto']}" if a.get("foto") else ""
    css1 = f""".img{{position:absolute;inset:0;background:{"url('" + foto + "') center/cover" if foto else "#131A2B"}}}
.vel{{position:absolute;inset:0;background:linear-gradient(180deg,rgba(11,15,26,.7) 0,rgba(11,15,26,.6) 30%,rgba(11,15,26,.96) 58%,#0B0F1A 100%)}}
.ris{{position:absolute;left:64px;right:64px;top:350px;background:rgba(11,15,26,.8);border-radius:30px;padding:30px 20px;display:grid;grid-template-columns:1fr auto 1fr;align-items:center}}
.lato{{display:flex;flex-direction:column;align-items:center;gap:14px;font:800 34px 'Barlow Condensed';text-transform:uppercase;color:#A3ADC2}}.lato.v{{color:#fff}}
.pt{{font:800 190px/1 'Barlow Condensed';display:flex;gap:30px}}.pt .p{{color:#6B7690}}.pt .v{{color:#fff}}.pt i{{font-style:normal;color:#4B5563}}
.fin{{position:absolute;left:0;right:0;top:262px;text-align:center;font:800 26px Inter;letter-spacing:5px;color:#EF4444}}
.k{{position:absolute;left:64px;right:64px;top:720px}}.k h1{{font-size:80px}}.k .w{{font:700 26px Inter;color:#C9D1E0;margin-top:20px}}
.cr{{position:absolute;right:64px;top:118px;font:500 15px Inter;color:rgba(255,255,255,.75)}}"""
    v.slide.append((css1, '<div class="img"></div><div class="vel"></div>' + testata(f"Cronaca · Week {a['settimana']}") +
                    f'<div class="cr">{e(credito(a))}</div><div class="fin">FINALE</div>'
                    f'<div class="ris"><div class="lato{" v" if vo else ""}">{stemma(o, 130)}{e(nome(o))}</div>'
                    f'<div class="pt"><span class="{"v" if vo else "p"}">{p["ospite"]}</span><i>–</i><span class="{"p" if vo else "v"}">{p["casa"]}</span></div>'
                    f'<div class="lato{"" if vo else " v"}">{stemma(c, 130)}{e(nome(c))}</div></div>'
                    f'<div class="k"><h1>{e(a["titolo"]).replace("-", "‑")}</h1><div class="w">{e(quando(a["dataIt"]))} · {e(a["stadio"])}</div></div>' + piede(1, 2)))
    righe = ""
    for s in (a.get("riquadro") or {}).get("squadre") or []:
        for g in s["giocatori"][:3]:
            righe += (f'<div class="g">{stemma(s["sigla"], 56)}<div class="t"><div class="nm">{e(g["nome"])}</div><div class="r">{e(g["ruolo"])}</div></div>'
                      f'<div class="d">{"".join(f"<div><b>{e(x)}</b><span>{e(t)}</span></div>" for x, t in g["dati"][:3])}</div></div>')
    css2 = """.tit{position:absolute;top:150px;left:64px}.tit h1{font-size:88px}
.lista{position:absolute;top:390px;left:64px;right:64px}
.g{display:flex;align-items:center;gap:20px;border-top:1px solid #232C42;padding:18px 0}.t{flex:1}
.nm{font:800 34px/1.05 'Barlow Condensed';text-transform:uppercase}.r{font:700 15px Inter;letter-spacing:2px;color:#A3ADC2;text-transform:uppercase;margin-top:4px}
.d{display:flex;gap:26px;text-align:right}.d b{display:block;font:800 40px/1 'Barlow Condensed'}.d span{font:600 14px Inter;color:#A3ADC2;text-transform:uppercase;letter-spacing:1px}"""
    v.slide.append((css2, testata(f"{o} {p['ospite']} – {p['casa']} {c}") +
                    '<div class="tit"><h1>I protagonisti<br><span class="rosso">della partita</span></h1></div>' + f'<div class="lista">{righe}</div>' + piede(2, 2)))
    return v


def risultati():
    tutte = [p for p in D.get("ultimePartite") or [] if p.get("tipo", "REG") == "REG"]
    if not tutte:
        return []
    st = max(str(p["stagione"]) for p in tutte)
    out = []
    for w in sorted({int(p["settimana"]) for p in tutte if str(p["stagione"]) == st})[-2:]:
        ps = sorted([p for p in tutte if str(p["stagione"]) == st and int(p["settimana"]) == w], key=lambda p: inizio(p) or ADESSO)
        if not ps or any(p.get("pc") is None for p in ps):
            continue
        fine = max(inizio(p) or ADESSO for p in ps) + timedelta(hours=4)
        if not (timedelta(0) <= ADESSO - fine <= timedelta(days=3)):
            continue
        tot = sum(p["pc"] + p["po"] for p in ps)
        vicine = sum(1 for p in ps if abs(p["pc"] - p["po"]) <= 8)
        v = Voce(f"risultati|{st}|{w}", "risultati", f"Risultati week {w}", ADESSO + timedelta(days=3),
                 f"🏈 NFL, week {w}: tutti i risultati e i migliori della settimana.\n\nClassifica, statistiche e cronache su "
                 f"purestats.it (link in bio).\n\n{tag('NFL', 'NFLItalia', 'FootballAmericano', 'PureStats')}")
        css1 = """.cop{position:absolute;inset:0;background:radial-gradient(circle at 80% 20%,#3A1618 0,#0B0F1A 60%)}
.big{position:absolute;right:-30px;top:120px;font:800 760px/0.8 'Barlow Condensed';color:transparent;-webkit-text-stroke:3px #232C42}
.tit{position:absolute;left:64px;right:64px;bottom:250px}.tit h1{font-size:150px}
.num{position:absolute;left:64px;right:64px;bottom:120px;display:flex;gap:56px}
.num b{display:block;font:800 64px 'Barlow Condensed'}.num span{font:700 19px Inter;letter-spacing:2px;color:#A3ADC2;text-transform:uppercase}"""
        media = f"{tot / len(ps):.1f}".replace(".", ",")
        v.slide.append((css1, f'<div class="cop"></div><div class="big">{w}</div>' + testata("Risultati") +
                        f'<div class="tit"><div class="sotto">NFL · stagione {st}</div><h1>Week {w}<br><span class="rosso">i risultati</span></h1></div>'
                        f'<div class="num"><div><b>{len(ps)}</b><span>partite</span></div><div><b>{media}</b><span>punti a partita</span></div>'
                        f'<div><b>{vicine}</b><span>decise da 8 punti o meno</span></div></div>' + piede(1, 3)))
        alto = 78 if len(ps) <= 13 else 66
        righe = ""
        for p in ps:
            a_, b_ = p["po"] > p["pc"], p["pc"] > p["po"]
            righe += (f'<div class="r"><div class="lato">{ST.svg(p["ospite"])}<span class="n{" v" if a_ else ""}">{e(nome(p["ospite"]))}</span></div>'
                      f'<div class="pt"><b class="{"v" if a_ else ""}">{p["po"]}</b><i>–</i><b class="{"v" if b_ else ""}">{p["pc"]}</b></div>'
                      f'<div class="lato dx"><span class="n{" v" if b_ else ""}">{e(nome(p["casa"]))}</span>{ST.svg(p["casa"])}</div></div>')
        css2 = f""".lista{{position:absolute;top:150px;left:64px;right:64px}}
.r{{display:grid;grid-template-columns:1fr 210px 1fr;align-items:center;height:{alto}px;border-top:1px solid #232C42}}
.lato{{display:flex;align-items:center;gap:14px}}.lato.dx{{justify-content:flex-end}}.lato .st{{width:50px;height:50px}}
.n{{font:600 27px Inter;color:#A3ADC2}}.n.v{{color:#F5F7FB;font-weight:800}}
.pt{{display:flex;justify-content:center;gap:14px;font:800 46px 'Barlow Condensed';color:#A3ADC2}}.pt b.v{{color:#F5F7FB}}.pt i{{font-style:normal;color:#4B5563}}"""
        v.slide.append((css2, testata(f"Week {w} · punteggi") + f'<div class="lista">{righe}</div>' + piede(2, 3)))
        mig = {}
        for p in ps:
            for lato, sq in (("giocatoriCasa", p["casa"]), ("giocatoriOspite", p["ospite"])):
                for g in p.get(lato) or []:
                    if g.get("misura") in ("yard passate", "yard corse", "yard ricevute") and g["valore"] > mig.get(g["misura"], ({"valore": -1},))[0]["valore"]:
                        mig[g["misura"]] = (g, sq)
        schede = ""
        for misura, titolo in (("yard passate", "Il lancio"), ("yard corse", "La corsa"), ("yard ricevute", "La ricezione")):
            if misura not in mig:
                continue
            g, sq = mig[misura]
            schede += (f'<div class="sc">{stemma(sq, 96)}<div class="t"><div class="ti">{titolo}</div><div class="nm">{e(g["nome"])}</div>'
                       f'<div class="dt">{e(nome(sq))} · {e(g.get("ruolo", ""))}{" · " + e(", ".join(g["dettagli"])) if g.get("dettagli") else ""}</div></div>'
                       f'<div class="v"><b>{e(g["valore"])}</b><span>{e(misura)}</span></div></div>')
        css3 = """.tit{position:absolute;top:150px;left:64px}.tit h1{font-size:96px}
.lista{position:absolute;top:470px;left:64px;right:64px;display:flex;flex-direction:column;gap:30px}
.sc{display:flex;align-items:center;gap:28px;background:#131A2B;border:1px solid #232C42;border-radius:26px;padding:34px 36px}
.t{flex:1}.ti{font:800 24px 'Barlow Condensed';letter-spacing:3px;color:#EF4444;text-transform:uppercase}
.nm{font:800 46px/1.05 'Barlow Condensed';text-transform:uppercase;margin-top:4px}.dt{font:600 21px Inter;color:#A3ADC2;margin-top:6px}
.v{text-align:right}.v b{display:block;font:800 84px/0.9 'Barlow Condensed'}.v span{font:700 17px Inter;letter-spacing:2px;color:#A3ADC2;text-transform:uppercase}"""
        v.slide.append((css3, testata(f"Week {w} · migliori") + '<div class="tit"><h1>I migliori<br><span class="rosso">della week</span></h1></div>'
                        f'<div class="lista">{schede}</div>' + piede(3, 3)))
        out.append(v)
    return out


def accadde():
    x = (H.get("accadde") or {}).get(f"{OGGI:%m-%d}")
    if not x:
        return []
    a, m, g = x["data"].split("-")
    vc = x["pc"] > x["po"]
    note = x.get("note") or []
    nota = note[-1] if note else ""
    nota = re.sub(r"^la partita", "La partita", nota)
    v = Voce(f"accadde|{OGGI.isoformat()}", "accadde", f"Accadde oggi {OGGI:%d/%m}",
             datetime(OGGI.year, OGGI.month, OGGI.day, 23, 59, tzinfo=ROMA),
             f"📅 Accadde oggi, {int(g)} {MESI[int(m) - 1]} {a}: {x['nomeOspite']} {x['po']}, {x['nomeCasa']} {x['pc']}.\n"
             f"{nota[:1].upper() + nota[1:] + '.' if nota else ''}\n\nOgni giorno una partita dalla storia della NFL su purestats.it "
             f"(link in bio).\n\n{tag('NFL', 'StoriaNFL', 'AccaddeOggi', 'PureStats')}")
    css = """.cop{position:absolute;inset:0;background:radial-gradient(circle at 20% 15%,#3A1618 0,#0B0F1A 55%)}
.data{position:absolute;top:150px;left:64px;right:64px}.data .q{font:800 26px Inter;letter-spacing:5px;color:#EF4444}
.data h1{font-size:124px;margin-top:8px}.data .an{font:700 30px Inter;color:#A3ADC2;margin-top:6px}
.ris{position:absolute;left:64px;right:64px;top:540px;background:#131A2B;border:1px solid #232C42;border-radius:28px;padding:40px 44px}
.r{display:flex;align-items:center;gap:24px;padding:14px 0}.r .n{flex:1;font:800 48px 'Barlow Condensed';text-transform:uppercase;color:#A3ADC2}
.r .p{font:800 96px/1 'Barlow Condensed';color:#6B7690}.r.v .n,.r.v .p{color:#fff}.r .qb{font:600 19px Inter;color:#8A93A8;text-transform:none}
.note{position:absolute;left:64px;right:64px;top:1000px;font:600 38px/1.35 Inter;color:#C9D1E0}"""
    riga = lambda s, n, qb, pt, vv: (f'<div class="r{" v" if vv else ""}">{stemma(s, 90)}<div class="n">{e(n)}'
                                     f'{"<div class=qb>QB " + e(qb) + "</div>" if qb else ""}</div><div class="p">{pt}</div></div>')
    v.slide.append((css, '<div class="cop"></div>' + testata("Accadde oggi") +
                    f'<div class="data"><div class="q">ACCADDE OGGI</div><h1>{int(g)} {MESI[int(m) - 1]} {a}</h1>'
                    f'<div class="an">{x["anni"]} anni fa · {e(x.get("stadio", ""))}</div></div>'
                    f'<div class="ris">{riga(x["ospite"], x["nomeOspite"], x.get("qbOspite"), x["po"], not vc)}'
                    f'{riga(x["casa"], x["nomeCasa"], x.get("qbCasa"), x["pc"], vc)}</div>'
                    f'<div class="note">{e(nota[:1].upper() + nota[1:]) + "." if nota else ""}</div>' + piede(1, 1)))
    return [v]


def corsa():
    cs = H.get("corsa") or {}
    if not cs.get("squadre") or int(cs.get("settimana") or 0) < 10:
        return []
    w = int(cs["settimana"])
    v = Voce(f"corsa|{cs['stagione']}|{w}", "corsa", f"Corsa ai playoff week {w}", ADESSO + timedelta(days=3),
             f"📈 La corsa ai playoff dopo la week {w}: la probabilità di ogni squadra di entrare, da "
             f"{cs.get('simulazioni', 4000):,} simulazioni del resto della stagione.".replace(",", ".") +
             f"\n\nClassifiche e partite decisive su purestats.it (link in bio).\n\n{tag('NFL', 'NFLPlayoffs', 'NFLItalia', 'PureStats')}")
    for i, conf in enumerate(("AFC", "NFC"), 1):
        sq = sorted([s for s in cs["squadre"] if s["conference"] == conf], key=lambda s: -s["p"])
        righe = ""
        for n, s in enumerate(sq, 1):
            pc = s["p"] * 100
            et = "dentro" if pc >= 99.95 else "fuori" if pc == 0 else "<1%" if pc < 1 else ">99%" if pc > 99 else f"{pc:.0f}%"
            righe += (f'<div class="r{" taglio" if n == 7 else ""}"><div class="pos">{n}</div>{stemma(s["squadra"], 44)}<div class="nm">'
                      f'{e(nome(s["squadra"]))}<span>{e(s.get("bilancio", ""))}</span></div><div class="bar"><div style="width:{max(pc, 0.6):.1f}%"></div>'
                      f'</div><div class="pc">{et}</div></div>')
        css = """.tit{position:absolute;top:140px;left:64px;right:64px}.tit h1{font-size:84px}
.lista{position:absolute;top:350px;left:64px;right:64px}
.r{display:flex;align-items:center;gap:16px;height:54px}.r.taglio{border-bottom:2px dashed #EF4444;margin-bottom:6px}
.pos{width:34px;font:800 26px 'Barlow Condensed';color:#6B7690}.nm{width:300px;font:700 25px Inter}.nm span{font:600 19px Inter;color:#8A93A8;margin-left:10px}
.bar{flex:1;height:16px;background:#1B2338;border-radius:8px;overflow:hidden}.bar div{height:100%;background:#EF4444;border-radius:8px}
.pc{width:110px;text-align:right;font:800 30px 'Barlow Condensed'}
.nota{position:absolute;left:64px;right:64px;top:1240px;font:500 18px Inter;color:#6B7690}"""
        v.slide.append((css, testata(f"Corsa ai playoff · Week {w}") +
                        f'<div class="tit"><h1>Corsa ai playoff <span class="rosso">{conf}</span></h1><div class="sotto" style="margin-top:8px">'
                        f'Probabilità di entrare · {cs.get("simulazioni", 4000):,} simulazioni del resto della stagione'.replace(",", ".") + '</div></div>'
                        f'<div class="lista">{righe}</div><div class="nota">Tratteggio rosso: i 7 posti dei playoff. Calcolo PureStats sui risultati nflverse.</div>'
                        + piede(i, 2)))
    return [v]


# ------------------------------------------------------------------ coda
def controlla(v):
    """Nessun termine da scommesse nelle didascalie e nelle slide (stessa regola delle pagine pubbliche)."""
    testo = v.didascalia + " " + re.sub(r"<[^>]+>|\{[^}]*\}", " ", " ".join(c for _s, c in v.slide))
    trovati = sorted({m.group(0).lower() for m in VIETATE_NUOVE.finditer(testo)})
    return trovati


def main():
    argomenti = [a for a in sys.argv[1:] if not a.startswith("--")]
    prova = "--prova" in sys.argv
    if len(argomenti) != 1:
        sys.exit("uso: python3 scripts/social.py <cartella del ramo social> [--prova]")
    ramo = tempfile.mkdtemp(prefix="social_prova_") if prova else argomenti[0]
    os.makedirs(ramo, exist_ok=True)
    percorso_coda = os.path.join(ramo, "coda.json")
    try:
        with open(percorso_coda, encoding="utf-8") as f:
            coda = json.load(f)
    except (OSError, ValueError):
        coda = {"voci": [], "fatti": {}}
    fatti = coda.get("fatti") or {}
    voci_nuove, saltati = [], []
    for produttore in (guida, carte, leggende, articoli, risultati, accadde, corsa):
        try:
            candidati = produttore()
        except Exception as x:                     # noqa: BLE001 - un tipo che fallisce non ferma gli altri
            print(f"{produttore.__name__}: dati non leggibili ({type(x).__name__}: {x}), salto questo tipo")
            continue
        for v in candidati:
            if v.chiave in fatti and not prova:
                continue
            if v.scade <= ADESSO:
                continue
            vietate = controlla(v)
            if vietate:
                print(f"{v.chiave}: NON preparato, contiene termini vietati nella parte pubblica: {', '.join(vietate)}")
                continue
            cart = os.path.join(ramo, v.cartella())
            os.makedirs(cart, exist_ok=True)
            try:
                immagini = []
                for i, (css, corpo) in enumerate(v.slide, 1):
                    dest = os.path.join(cart, f"{i}.jpg")
                    fotografa(dest, css, corpo)
                    immagini.append(f"{v.cartella()}/{i}.jpg")
                video = None
                if v.video:
                    v.video(os.path.join(cart, "reel.mp4"))
                    video = f"{v.cartella()}/reel.mp4"
            except Exception as x:                 # noqa: BLE001
                shutil.rmtree(cart, ignore_errors=True)
                saltati.append(v.chiave)
                print(f"{v.chiave}: immagini non riuscite ({x}), riprovo al prossimo giro")
                continue
            voci_nuove.append({"chiave": v.chiave, "tipo": v.tipo, "titolo": v.titolo, "immagini": immagini, "video": video,
                               "didascalia": v.didascalia, "ai": v.ai, "creato": ADESSO.isoformat(timespec="minutes"),
                               "scade": v.scade.astimezone(timezone.utc).isoformat(timespec="minutes")})
            fatti[v.chiave] = ADESSO.isoformat(timespec="minutes")
            print(f"{v.chiave}: pronto ({len(immagini)} immagini{', reel' if video else ''})")
    if prova:
        print(f"Prova: file in {ramo}, coda non toccata")
        return
    # pulizia: via le voci (e i loro file) più vecchie di GIORNI_TENUTI, «fatti» tenuti 60 giorni
    limite = ADESSO - timedelta(days=GIORNI_TENUTI)
    tenute = [x for x in coda.get("voci") or [] if datetime.fromisoformat(x["creato"]) >= limite] + voci_nuove
    cartelle = {x["immagini"][0].split("/")[0] if x["immagini"] else (x["video"] or "/").split("/")[0] for x in tenute}
    for nome_c in os.listdir(ramo):
        p = os.path.join(ramo, nome_c)
        if os.path.isdir(p) and nome_c not in cartelle and not nome_c.startswith("."):
            shutil.rmtree(p)
    fatti = {k: t for k, t in fatti.items() if datetime.fromisoformat(t) >= ADESSO - timedelta(days=60)}
    if not voci_nuove and len(tenute) == len(coda.get("voci") or []) and coda.get("voci") is not None:
        print("Nessuna novità: il ramo «social» resta com'è")
        return
    open(os.environ.get("SOCIAL_SEGNALE", os.path.join(tempfile.gettempdir(), "social_cambiato")), "w").close()
    with open(percorso_coda + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"aggiornato": ADESSO.isoformat(timespec="minutes"), "voci": tenute, "fatti": fatti}, f, ensure_ascii=False, indent=1)
    os.replace(percorso_coda + ".tmp", percorso_coda)
    print(f"Coda: {len(voci_nuove)} nuove, {len(tenute)} in tutto" + (f", {len(saltati)} da riprovare" if saltati else ""))


if __name__ == "__main__":
    main()
