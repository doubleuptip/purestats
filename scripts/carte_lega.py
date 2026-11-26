#!/usr/bin/env python3
"""Carte della Lega della Terra Unita (sezione 2187, dal 26/11/2026, scelta di Valerio).

Compone il fronte e il retro di una carta dai suoi dati e li fotografa con Chrome senza finestra.

  python3 scripts/carte_lega.py <numero>       es. 1 oppure 001

Legge:   lega/carte/<NNN>.json       dati della carta (nome, Dono, storia, numeri...)
         lega/immagini/<NNN>.jpg     ritratto generato da Valerio con Gemini
         lega/stemmi/<file>.png      stemma della squadra (campo «stemma»)
         docs/lega/bandiera.png      bandiera dell'Alba
Scrive:  docs/lega/carte/<NNN>_fronte.jpg e <NNN>_retro.jpg
         docs/lega/lega.json         voce della carta nell'elenco «carte» (aggiunta o aggiornata)

Se qualcosa manca o Chrome non risponde lo script si ferma prima di toccare lega.json:
l'elenco pubblicato resta com'era.
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARTE_DATI = os.path.join(RADICE, "lega", "carte")
IMMAGINI = os.path.join(RADICE, "lega", "immagini")
STEMMI = os.path.join(RADICE, "lega", "stemmi")
USCITA = os.path.join(RADICE, "docs", "lega", "carte")
LEGA_JSON = os.path.join(RADICE, "docs", "lega", "lega.json")
BANDIERA = os.path.join(RADICE, "docs", "lega", "bandiera.png")
FONT_CSS = os.path.join(RADICE, "docs", "font", "font.css")

# Colori della carta per squadra: bordo metallico, fondo, accento. Le squadre senza voce usano quelli dei Tempest.
TEMI = {
    "Aurelion Tempest": {"b1": "#E0A27A", "b2": "#9C5A34", "b3": "#F1C29C", "b4": "#8A4B2A", "linea": "#C98A62",
                         "acc": "#E7B18C", "f1": "#1E5560", "f2": "#0E2F38", "f3": "#081A20",
                         "sotto": "#9FD3DA", "luce": "#5EE6E0", "chip": "#163E47", "chipt": "#BFE7EA"},
}


def chrome():
    for nome in ("google-chrome", "chromium", "chromium-browser"):
        p = shutil.which(nome)
        if p:
            return p
    sys.exit("Chrome non trovato: serve per fotografare la carta (google-chrome o chromium)")


def testo(s):
    """Testo sicuro con **grassetto** e *corsivo piccolo*."""
    s = html.escape(str(s), quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"\*(.+?)\*", r"<i>\1</i>", s)


def css(t):
    return """*{box-sizing:border-box;margin:0;padding:0}
body{background:%(b2)s;font-family:Inter,sans-serif;width:750px;height:1050px;overflow:hidden}
.carta{width:750px;height:1050px;border-radius:30px;padding:8px;background:linear-gradient(145deg,%(b1)s,%(b2)s 40%%,%(b3)s 60%%,%(b4)s)}
.in{width:100%%;height:100%%;border-radius:24px;overflow:hidden;position:relative;background:radial-gradient(120%% 80%% at 50%% 0%%,%(f1)s 0%%,%(f2)s 45%%,%(f3)s 100%%);color:#F3F7F8}
.alto{display:flex;align-items:center;gap:12px;padding:18px 24px 14px;font:700 15px Inter;letter-spacing:2.2px}
.alto img{height:30px;border-radius:3px;box-shadow:0 0 0 1px rgba(255,255,255,.25)}
.alto .st{margin-left:auto;color:%(acc)s}
.foto{position:relative;margin:0 22px;height:540px;border-radius:18px;overflow:hidden;box-shadow:0 0 0 2px %(linea)s}
.foto img{width:100%%;height:100%%;object-fit:cover;object-position:50%% 20%%}
.foto:after{content:"";position:absolute;left:0;right:0;bottom:0;height:200px;background:linear-gradient(transparent,%(f3)s)}
.logo{position:absolute;right:34px;top:526px;width:116px;height:116px;border-radius:50%%;box-shadow:0 0 0 5px %(f2)s,0 0 0 8px %(linea)s,0 10px 24px rgba(0,0,0,.6);z-index:3;background:#fff}
.nome{padding:20px 30px 0;position:relative;z-index:2}
.nome h1{font:800 60px/0.95 "Barlow Condensed";letter-spacing:1px;text-transform:uppercase}
.nome p{font:700 16px Inter;letter-spacing:2px;color:%(sotto)s;margin-top:8px;text-transform:uppercase}
.dono{margin:18px 30px 0;padding:14px 16px;border-radius:14px;background:rgba(10,30,36,.75);border:1px solid %(linea)s}
.dono b{font:800 21px "Barlow Condensed";letter-spacing:1.6px;color:%(acc)s;text-transform:uppercase}
.dono b i{font-style:normal;color:%(luce)s}
.dono p{font-size:14.5px;line-height:1.45;margin-top:4px;color:#DDE8EA}
.ch{display:flex;gap:8px;margin-top:9px}.ch span{font:700 11.5px Inter;letter-spacing:1px;padding:5px 9px;border-radius:99px;background:%(chip)s;color:%(chipt)s;text-transform:uppercase}
.dcap{margin:16px 30px 0;font:700 11.5px Inter;letter-spacing:2px;color:#8FA9AE;text-align:center;text-transform:uppercase}
.dati{display:grid;grid-template-columns:repeat(4,1fr);margin:6px 30px 0;text-align:center}
.dati div{border-right:1px solid rgba(255,255,255,.15)}.dati div:last-child{border:0}
.dati b{display:block;font:800 36px "Barlow Condensed";color:#fff}.dati span{font:600 11px Inter;letter-spacing:1.3px;color:#9FB9BE;text-transform:uppercase}
.piede{position:absolute;left:0;right:0;bottom:0;display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 24px;font:600 11px Inter;letter-spacing:1.2px;color:#8FA9AE;background:rgba(0,0,0,.35)}
.piede .ps{font:800 17px "Barlow Condensed";letter-spacing:1.5px;color:#fff;white-space:nowrap}.piede .ps i{font-style:normal;color:#EF4444}
.rt{display:flex;align-items:center;gap:16px;padding:26px 30px 18px;border-bottom:1px solid %(linea)s}
.rt img{width:84px;height:84px;border-radius:50%%;background:#fff;box-shadow:0 0 0 3px %(linea)s}
.rt h2{font:800 44px/1 "Barlow Condensed";text-transform:uppercase}.rt p{font:700 13px Inter;letter-spacing:1.8px;color:%(sotto)s;margin-top:6px;text-transform:uppercase}
.storia{padding:18px 30px 0;font-size:15.5px;line-height:1.55;color:#E2ECEE}
.storia p{margin-bottom:11px}.storia p b{color:%(acc)s}
.sch{margin:6px 30px 0;display:grid;grid-template-columns:1fr 1fr;gap:10px}
.sch div{background:rgba(10,30,36,.75);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:10px 12px;font-size:13px;color:#BFD3D6}
.sch div b{display:block;font:800 18px "Barlow Condensed";letter-spacing:1px;color:#fff;margin-bottom:2px;text-transform:uppercase}
.car{margin:12px 30px 0;background:rgba(10,30,36,.75);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:10px 14px}
.car b{font:800 16px "Barlow Condensed";letter-spacing:1.4px;color:%(acc)s}
.car table{width:100%%;border-collapse:collapse;margin-top:6px;font-size:14px}.car th{font:600 11px Inter;letter-spacing:1px;color:#8FA9AE;text-align:right;padding:4px 0}.car th:first-child,.car td:first-child{text-align:left}
.car td{text-align:right;padding:5px 0;border-top:1px solid rgba(255,255,255,.08);color:#E2ECEE}.car td i{font-style:normal;font-size:11px;color:%(luce)s}
.riv{margin:12px 30px 0;padding:12px 14px;border-radius:12px;background:linear-gradient(90deg,rgba(239,68,68,.18),rgba(239,68,68,.04));border-left:3px solid #EF4444;font-size:14px;line-height:1.45}
.riv b{font:800 16px "Barlow Condensed";letter-spacing:1.4px;color:#FCA5A5;display:block;text-transform:uppercase}
.cit{margin:18px 30px 0;font:600 italic 19px/1.4 Inter;color:#F3F7F8;padding-left:16px;border-left:3px solid %(linea)s}.cit span{display:block;font:500 12.5px Inter;font-style:normal;color:#8FA9AE;margin-top:6px}
""" % t


def pagina(stile, corpo):
    return ('<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="file://%s"><style>%s</style>'
            '</head><body><div class="carta"><div class="in">%s</div></div></body></html>') % (FONT_CSS, stile, corpo)


def fronte(c, nnn, ritratto, stemma):
    d = c["dono"]
    dati = "".join('<div><b>%s</b><span>%s</span></div>' % (testo(v), testo(e)) for v, e in c["dati"])
    return (
        '<div class="alto"><img src="file://%s" alt="">LEGA DELLA TERRA UNITA<span class="st">STAGIONE %s</span></div>'
        '<div class="foto"><img src="file://%s" alt=""></div><img class="logo" src="file://%s" alt="">'
        '<div class="nome"><h1>%s</h1><p>%s · %s</p></div>'
        '<div class="dono"><b>Dono · <i>%s</i></b><p>%s</p><div class="ch"><span>%s</span><span>Prezzo: %s</span></div></div>'
        '<div class="dcap">%s</div><div class="dati">%s</div>'
        '<div class="piede"><span>CARTA Nº %s · PERSONAGGIO IMMAGINARIO · IMMAGINE CREATA CON AI</span>'
        '<span class="ps">PURE<i>STATS</i></span></div>'
    ) % (BANDIERA, testo(c.get("stagione", 2187)), ritratto, stemma, testo(c["nome"]), testo(c["ruolo"]),
         testo(c["squadra"]), testo(d["nome"]), testo(d["testo"]), testo(d["usi"]), testo(d["prezzo"]),
         testo(c["dati_titolo"]), dati, nnn)


def retro(c, nnn, stemma, anno):
    car = c["carriera"]
    tab = "<tr>%s</tr>" % "".join("<th>%s</th>" % testo(x) for x in car["colonne"])
    tab += "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % testo(x) for x in r) for r in car["righe"])
    parti = [
        '<div class="rt"><img src="file://%s" alt=""><div><h2>%s · %s</h2><p>%s · %s · Conference %s</p></div></div>'
        % (stemma, testo(c["nome"]), testo(c["maglia"]), testo(c["ruolo"]), testo(c["squadra"]), testo(c["conference"])),
        '<div class="storia">%s</div>' % "".join("<p>%s</p>" % testo(p) for p in c["storia"]),
        '<div class="sch">%s</div>' % "".join("<div><b>%s</b>%s</div>" % (testo(a), testo(b)) for a, b in c["schede"]),
        '<div class="car"><b>LA CARRIERA</b><table>%s</table></div>' % tab,
    ]
    if c.get("rivale"):
        parti.append('<div class="riv"><b>%s</b>%s</div>' % (testo(c["rivale"]["titolo"]), testo(c["rivale"]["testo"])))
    if c.get("citazione"):
        parti.append('<div class="cit">«%s»<span>— %s</span></div>' % (testo(c["citazione"]["testo"]),
                                                                      testo(c["citazione"]["fonte"])))
    parti.append('<div class="piede"><span>CARTA Nº %s · PERSONAGGIO IMMAGINARIO · IMMAGINE CREATA CON AI · © PURESTATS %s'
                 '</span><span class="ps">PURE<i>STATS</i></span></div>' % (nnn, anno))
    return "".join(parti)


def fotografa(html_testo, destinazione):
    """Fotografa la carta (750×1050 a 1,5×, senza margini: gli angoli tondi li taglia il sito) e salva in JPEG. Il file vecchio si sostituisce solo a foto riuscita."""
    with tempfile.TemporaryDirectory() as cartella:
        sorgente = os.path.join(cartella, "carta.html")
        foto = os.path.join(cartella, "carta.jpeg")
        with open(sorgente, "w", encoding="utf-8") as f:
            f.write(html_testo)
        comando = [chrome(), "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                   "--allow-file-access-from-files", "--force-device-scale-factor=1.5", "--window-size=750,1050",
                   "--virtual-time-budget=4000", "--screenshot=" + foto, "file://" + sorgente]
        r = subprocess.run(comando, capture_output=True, text=True, timeout=120)
        if not os.path.exists(foto) or os.path.getsize(foto) < 20000:
            sys.exit("Chrome non ha prodotto la foto di %s (codice %s): %s" % (destinazione, r.returncode, r.stderr[-400:]))
        shutil.move(foto, destinazione)


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit("uso: python3 scripts/carte_lega.py <numero della carta>")
    nnn = "%03d" % int(sys.argv[1])
    with open(os.path.join(CARTE_DATI, nnn + ".json"), encoding="utf-8") as f:
        c = json.load(f)
    ritratto = os.path.join(IMMAGINI, nnn + ".jpg")
    stemma = os.path.join(STEMMI, c["stemma"])
    for p, cosa in ((ritratto, "il ritratto"), (stemma, "lo stemma della squadra"), (BANDIERA, "la bandiera")):
        if not os.path.exists(p):
            sys.exit("Manca %s (%s): la carta %s non si compone" % (cosa, p, nnn))
    with open(LEGA_JSON, encoding="utf-8") as f:
        lega = json.load(f)
    stile = css(TEMI.get(c["squadra"], TEMI["Aurelion Tempest"]))
    anno = c["uscita"][:4]
    os.makedirs(USCITA, exist_ok=True)
    fotografa(pagina(stile, fronte(c, nnn, ritratto, stemma)), os.path.join(USCITA, nnn + "_fronte.jpg"))
    fotografa(pagina(stile, retro(c, nnn, stemma, anno)), os.path.join(USCITA, nnn + "_retro.jpg"))

    voce = {"n": c["n"], "nome": c["nome"], "maglia": c["maglia"], "ruolo": c["ruolo"], "squadra": c["squadra"],
            "conference": c["conference"], "rarita": c.get("rarita", "Comune"), "uscita": c["uscita"],
            "dono": c["dono"]["nome"], "sintesi": c["sintesi"],
            "fronte": "lega/carte/%s_fronte.jpg" % nnn, "retro": "lega/carte/%s_retro.jpg" % nnn}
    carte = [x for x in lega.get("carte", []) if x["n"] != c["n"]] + [voce]
    lega["carte"] = sorted(carte, key=lambda x: x["n"])
    temporaneo = LEGA_JSON + ".tmp"
    with open(temporaneo, "w", encoding="utf-8") as f:
        json.dump(lega, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(temporaneo, LEGA_JSON)
    print("Carta %s (%s) composta: fronte e retro in docs/lega/carte, voce aggiornata in lega.json (%d carte)"
          % (nnn, c["nome"], len(lega["carte"])))


if __name__ == "__main__":
    main()
