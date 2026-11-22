"""Caratteri e Chart.js ospitati sul sito (22/11/2026, privacy: niente Google Fonts né jsDelivr).

Si lancia una volta dal workflow risorse-locali.yml (dalla sandbox npm non si raggiunge), dopo
`npm pack` dei pacchetti elencati in PACCHETTI nella cartella passata come argomento. Scrive:

  docs/font/<file>.woff2   solo i sottoinsiemi latin e latin-ext dei pesi usati dal sito
  docs/font/font.css       le @font-face con unicode-range (il browser scarica solo ciò che serve)
  docs/vendor/chart.umd.min.js   Chart.js 4.4.1 (stessa versione di prima)
  docs/vendor/integrita.json     hash sha384 per l'attributo integrity

Fonti: pacchetti @fontsource (licenza SIL Open Font License) e chart.js (MIT) dal registro npm.
Uso: python scripts/risorse_locali.py <cartella con i .tgz>
"""
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(RADICE, "docs", "font")
VENDOR = os.path.join(RADICE, "docs", "vendor")

# famiglia → (prefisso del pacchetto .tgz, pesi usati nel sito)
CARATTERI = {
    "inter": [400, 500, 600, 700, 800],
    "archivo": [600, 800],
    "barlow-condensed": [600, 700, 800],
    "teko": [400, 500, 600, 700],
    "jetbrains-mono": [400, 500, 700],
}
SOTTOINSIEMI = ("latin", "latin-ext")


def sha384(percorso):
    with open(percorso, "rb") as f:
        return "sha384-" + base64.b64encode(hashlib.sha384(f.read()).digest()).decode()


def estrai(tgz, dest):
    with tarfile.open(tgz) as t:
        for m in t.getmembers():
            if m.name.startswith("/") or ".." in m.name:
                raise SystemExit(f"Percorso sospetto nel pacchetto {tgz}: {m.name}")
        t.extractall(dest, filter="data")
    return os.path.join(dest, "package")


def main(cartella):
    tmp = tempfile.mkdtemp(prefix="risorse_")
    nuovo_font = os.path.join(tmp, "font")
    nuovo_vendor = os.path.join(tmp, "vendor")
    os.makedirs(nuovo_font)
    os.makedirs(nuovo_vendor)
    pacchetti = os.listdir(cartella)
    css = ["/* Caratteri ospitati da PureStats (pacchetti @fontsource, licenza SIL Open Font License 1.1). */"]
    for fam, pesi in CARATTERI.items():
        tgz = [p for p in pacchetti if p.startswith(f"fontsource-{fam}-") and p.endswith(".tgz")]
        if len(tgz) != 1:
            raise SystemExit(f"Manca il pacchetto di {fam} (trovati: {tgz}): nessun file è stato cambiato.")
        pkg = estrai(os.path.join(cartella, tgz[0]), os.path.join(tmp, fam))
        for peso in pesi:
            sorgente = os.path.join(pkg, f"{peso}.css")
            with open(sorgente, encoding="utf-8") as f:
                testo = f.read()
            blocchi = re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*\{.*?\})", testo, re.S)
            trovati = 0
            for sotto, blocco in blocchi:
                # i commenti sono del tipo «inter-latin-ext-400-normal»
                m = re.match(rf"{re.escape(fam)}-(.+)-{peso}-normal$", sotto)
                if not m or m.group(1) not in SOTTOINSIEMI:
                    continue
                file = re.search(r"url\(\./files/([\w.-]+\.woff2)\)", blocco)
                if not file:
                    continue
                shutil.copy(os.path.join(pkg, "files", file.group(1)), os.path.join(nuovo_font, file.group(1)))
                # solo woff2 (tutti i browser attuali), indirizzo relativo a font.css
                blocco = re.sub(r"src:[^;]+;", f"src: url(./{file.group(1)}) format('woff2');", blocco)
                css.append(blocco)
                trovati += 1
            if trovati != len(SOTTOINSIEMI):
                raise SystemExit(f"{fam} {peso}: trovati {trovati} sottoinsiemi invece di {len(SOTTOINSIEMI)}; "
                                 "struttura del pacchetto cambiata, nessun file è stato cambiato.")
    with open(os.path.join(nuovo_font, "font.css"), "w", encoding="utf-8") as f:
        f.write("\n".join(css) + "\n")

    tgz = [p for p in pacchetti if p == "chart.js-4.4.1.tgz"]
    if not tgz:
        raise SystemExit("Manca chart.js-4.4.1.tgz: nessun file è stato cambiato.")
    pkg = estrai(os.path.join(cartella, tgz[0]), os.path.join(tmp, "chart"))
    shutil.copy(os.path.join(pkg, "dist", "chart.umd.js"), os.path.join(nuovo_vendor, "chart.umd.min.js"))
    with open(os.path.join(nuovo_vendor, "integrita.json"), "w", encoding="utf-8") as f:
        json.dump({"chart.umd.min.js": sha384(os.path.join(nuovo_vendor, "chart.umd.min.js")),
                   "font.css": sha384(os.path.join(nuovo_font, "font.css"))}, f, indent=1)

    for nuovo, dest in ((nuovo_font, FONT), (nuovo_vendor, VENDOR)):
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.move(nuovo, dest)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Risorse locali: {len(os.listdir(FONT)) - 1} file di caratteri, Chart.js 4.4.1 in docs/vendor.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python scripts/risorse_locali.py <cartella con i .tgz>")
    main(sys.argv[1])
