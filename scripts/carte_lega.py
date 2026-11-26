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
.foto{position:relative;margin:0 22px;height:600px;border-radius:18px;overflow:hidden;box-shadow:0 0 0 2px %(linea)s}
.foto img{width:100%%;height:100%%;object-fit:cover;object-position:50%% 20%%}
.foto:after{content:"";position:absolute;left:0;right:0;bottom:0;height:200px;background:linear-gradient(transparent,%(f3)s)}
/* parte bassa UGUALE in tutte le carte (26/11/2026, Valerio: stesso formato per tutte): stessa altezza e posizione */
.basso{position:absolute;left:0;right:0;bottom:46px;padding:0 30px;z-index:2}
.riga{display:flex;align-items:center;justify-content:space-between;gap:18px}
.riga>div{min-width:0}
.stemma{width:96px;height:96px;border-radius:50%%;background:#fff;flex-shrink:0;
  box-shadow:0 0 0 4px %(f2)s,0 0 0 7px %(linea)s,0 10px 24px rgba(0,0,0,.6)}
.mom{font:700 13px Inter;letter-spacing:2px;color:%(acc)s;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.basso h1{font:800 60px/0.95 "Barlow Condensed";letter-spacing:1px;text-transform:uppercase;margin-top:6px;white-space:nowrap}
.ruolo{font:700 15px Inter;letter-spacing:2px;color:%(sotto)s;margin-top:6px;text-transform:uppercase}
.det{height:104px;margin-top:12px;overflow:hidden}
.det .tit{font:800 23px "Barlow Condensed";letter-spacing:1px;color:%(acc)s;text-transform:uppercase}
.det .tit i{font-style:normal;color:%(luce)s}
.det .txt{font-size:14.5px;line-height:1.45;color:#E2ECEE;margin-top:3px}
.det .pz{font:700 11.5px Inter;letter-spacing:1px;color:%(chipt)s;margin-top:6px;text-transform:uppercase}
.dati{display:grid;grid-template-columns:repeat(4,1fr);margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,.18);text-align:center}
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


# Cornici delle carte speciali (26/11/2026, scelta di Valerio): Rara argento-ciano, Leggendaria oro, Esclusiva prisma
CORNICI = {"Rara": ("#E6F4F7", "#7FA8B3", "#FFFFFF", "#5C8794", "#9FE8F2", "#0E2A33"),
           "Leggendaria": ("#FFE7A3", "#B8860B", "#FFF4CC", "#8A6206", "#FFD45E", "#2A1D02"),
           "Esclusiva": ("#F9A8D4", "#818CF8", "#67E8F9", "#FDE68A", "#F0ABFC", "#1E1B4B")}


def css_piena(t, rarita):
    """Carta «a immagine piena» per Rara, Leggendaria ed Esclusiva: la figura occupa tutta la carta."""
    b1, b2, b3, b4, acc, scuro = CORNICI.get(rarita, CORNICI["Rara"])
    return css(t) + """
.carta.piena{background:linear-gradient(135deg,%(b1)s,%(b2)s 30%%,%(b3)s 50%%,%(b4)s 70%%,%(b1)s)}
.piena .in{background:#05090C}
.piena .sfondo{position:absolute;inset:0;width:100%%;height:100%%;object-fit:cover;object-position:50%% 22%%}
.piena .velo{position:absolute;inset:0;background:linear-gradient(180deg,rgba(3,8,12,.78) 0%%,rgba(3,8,12,0) 13%%,
  rgba(3,8,12,0) 50%%,rgba(3,10,14,.82) 66%%,rgba(3,10,14,.97) 84%%)}
.piena .alto{position:relative;z-index:2}
.piena .rar{position:absolute;z-index:3;top:60px;left:24px;font:800 15px "Barlow Condensed";letter-spacing:2.4px;
  padding:6px 13px;border-radius:99px;background:linear-gradient(135deg,%(b1)s,%(b3)s 50%%,%(b2)s);color:%(scuro)s;
  box-shadow:0 4px 14px rgba(0,0,0,.45);text-transform:uppercase}
.piena .mom,.piena .det .tit{color:%(acc)s}
.piena .stemma{box-shadow:0 0 0 4px #0A1418,0 0 0 7px %(b2)s,0 10px 24px rgba(0,0,0,.6)}
.piena .basso h1{text-shadow:0 3px 18px rgba(0,0,0,.7)}
.piena .piede{background:rgba(0,0,0,.55)}
.piena.retro .in{background:radial-gradient(120%% 80%% at 50%% 0%%,%(f1)s 0%%,%(f2)s 45%%,%(f3)s 100%%)}
.piena.retro .rt{border-bottom-color:%(b2)s}
""" % {"b1": b1, "b2": b2, "b3": b3, "b4": b4, "acc": acc, "scuro": scuro, "f1": t["f1"], "f2": t["f2"], "f3": t["f3"]}


def fronte_piena(c, nnn, ritratto, stemma):
    m = c.get("momento") or {}
    return (
        '<img class="sfondo" src="file://%s" alt=""><div class="velo"></div>'
        '<div class="alto"><img src="file://%s" alt="">LEGA DELLA TERRA UNITA<span class="st">STAGIONE %s</span></div>'
        '<div class="rar">%s%s</div>' + basso(c, stemma, testo(m.get("etichetta", "")),
        '<div class="tit">%s</div><div class="txt">%s</div>' % (testo(m.get("titolo", "")), testo(m.get("testo", "")))) +
        '<div class="piede"><span>CARTA Nº %s · PERSONAGGIO IMMAGINARIO · IMMAGINE CREATA CON AI</span>'
        '<span class="ps">PURE<i>STATS</i></span></div>'
    ) % (ritratto, BANDIERA, testo(c.get("stagione", 2187)), testo(c["rarita"]),
         (" · " + testo(m["tipo"])) if m.get("tipo") else "", nnn)


def pagina(stile, corpo, classe="carta"):
    return ('<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="file://%s"><style>%s</style>'
            '</head><body><div class="%s"><div class="in">%s</div></div></body></html>') % (FONT_CSS, stile, classe, corpo)


def fronte(c, nnn, ritratto, stemma):
    d = c["dono"]
    return (
        '<div class="alto"><img src="file://%s" alt="">LEGA DELLA TERRA UNITA<span class="st">STAGIONE %s</span></div>'
        '<div class="foto"><img src="file://%s" alt=""></div>' + basso(c, stemma, testo(c["dati_titolo"]),
        '<div class="tit">Dono · <i>%s</i></div><div class="txt">%s</div><div class="pz">%s · Prezzo: %s</div>'
        % (testo(d["nome"]), testo(d["testo"]), testo(d["usi"]), testo(d["prezzo"]))) +
        '<div class="piede"><span>CARTA Nº %s · PERSONAGGIO IMMAGINARIO · IMMAGINE CREATA CON AI</span>'
        '<span class="ps">PURE<i>STATS</i></span></div>'
    ) % (BANDIERA, testo(c.get("stagione", 2187)), ritratto, nnn)


def basso(c, stemma, sopra, dettaglio):
    """Parte bassa comune a tutte le carte: etichetta, nome e stemma sulla stessa riga, dettaglio, numeri."""
    dati = "".join('<div><b>%s</b><span>%s</span></div>' % (testo(v), testo(e)) for v, e in c["dati"])
    return ('<div class="basso"><div class="riga"><div><div class="mom">%s</div><h1>%s</h1><div class="ruolo">%s · %s</div></div>'
            '<img class="stemma" src="file://%s" alt=""></div><div class="det">%s</div><div class="dati">%s</div></div>'
            % (sopra, testo(c["nome"]), testo(c["ruolo"]), testo(c["squadra"]), stemma, dettaglio, dati)).replace("%", "%%")


def retro(c, nnn, stemma, anno):
    car = c["carriera"]
    tab = "<tr>%s</tr>" % "".join("<th>%s</th>" % testo(x) for x in car["colonne"])
    tab += "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % testo(x) for x in r) for r in car["righe"])
    parti = [
        '<div class="rt"><img src="file://%s" alt=""><div><h2>%s · %s</h2><p>%s · %s · Conference %s</p></div></div>'
        % (stemma, testo(c["nome"]), testo(c["maglia"]), testo(c["ruolo"]), testo(c["squadra"]), testo(c["conference"])),
        '<div class="storia">%s</div>' % "".join("<p>%s</p>" % testo(p) for p in c["storia"]),
        '<div class="sch">%s</div>' % "".join("<div><b>%s</b>%s</div>" % (testo(a), testo(b)) for a, b in c["schede"]),
        '<div class="car"><b>%s</b><table>%s</table></div>' % (testo(car.get("titolo", "La carriera")).upper(), tab),
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
    argomenti = [x for x in sys.argv[1:] if x != "--prova"]
    prova = "--prova" in sys.argv                       # solo le foto in /tmp, lega.json non si tocca
    if len(argomenti) != 1 or not argomenti[0].isdigit():
        sys.exit("uso: python3 scripts/carte_lega.py <numero della carta> [--prova]")
    nnn = "%03d" % int(argomenti[0])
    with open(os.path.join(CARTE_DATI, nnn + ".json"), encoding="utf-8") as f:
        c = json.load(f)
    ritratto = os.path.join(IMMAGINI, nnn + ".jpg")
    stemma = os.path.join(STEMMI, c["stemma"])
    for p, cosa in ((ritratto, "il ritratto"), (stemma, "lo stemma della squadra"), (BANDIERA, "la bandiera")):
        if not os.path.exists(p):
            sys.exit("Manca %s (%s): la carta %s non si compone" % (cosa, p, nnn))
    with open(LEGA_JSON, encoding="utf-8") as f:
        lega = json.load(f)
    tema = TEMI.get(c["squadra"], TEMI["Aurelion Tempest"])
    anno = c["uscita"][:4]
    cartella = "/tmp" if prova else USCITA
    os.makedirs(cartella, exist_ok=True)
    if c.get("rarita", "Comune") == "Comune":
        stile = css(tema)
        fotografa(pagina(stile, fronte(c, nnn, ritratto, stemma)), os.path.join(cartella, nnn + "_fronte.jpg"))
        fotografa(pagina(stile, retro(c, nnn, stemma, anno)), os.path.join(cartella, nnn + "_retro.jpg"))
    else:                                               # Rara, Leggendaria, Esclusiva: immagine piena e cornice speciale
        stile = css_piena(tema, c["rarita"])
        fotografa(pagina(stile, fronte_piena(c, nnn, ritratto, stemma), "carta piena"), os.path.join(cartella, nnn + "_fronte.jpg"))
        fotografa(pagina(stile, retro(c, nnn, stemma, anno), "carta piena retro"), os.path.join(cartella, nnn + "_retro.jpg"))
    if prova:
        print("Prova della carta %s: foto in /tmp/%s_fronte.jpg e _retro.jpg, lega.json non toccato" % (nnn, nnn))
        return

    voce = {"n": c["n"], "nome": c["nome"], "maglia": c["maglia"], "ruolo": c["ruolo"], "squadra": c["squadra"],
            "conference": c["conference"], "rarita": c.get("rarita", "Comune"), "uscita": c["uscita"],
            "dono": c["dono"]["nome"], "sintesi": c["sintesi"], "momento": (c.get("momento") or {}).get("titolo"),
            # ?v= cambia a ogni nuova foto: il browser non mostra la versione vecchia rimasta in memoria
            "fronte": "lega/carte/%s_fronte.jpg?v=%d" % (nnn, os.path.getmtime(os.path.join(USCITA, nnn + "_fronte.jpg"))),
            "retro": "lega/carte/%s_retro.jpg?v=%d" % (nnn, os.path.getmtime(os.path.join(USCITA, nnn + "_retro.jpg")))}
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
