"""Salva sul server le chiavi per pubblicare su Instagram e Facebook (PureStats, dal 28/11/2026).

Collegamento «tramite Facebook» (Pagina Facebook PureStats collegata all'account Instagram purestats).
Chiede (si vedono solo sul terminale, non finiscono in nessun file né registro): id dell'app, chiave segreta dell'app e il token breve generato con
Graph API Explorer. Poi da solo:
  1. scambia il token breve con quello lungo (60 giorni);
  2. dal token lungo prende il token della Pagina, che NON scade;
  3. trova l'id dell'account Instagram collegato alla Pagina e lo controlla (nome utente);
  4. scrive tutto nella sezione [purestats_instagram] di config.toml e controlla che il file sia valido.
Nessuna chiave viene stampata né scritta nel registro.

Uso (dalla cartella del bot Radar Assenze):  python3 strumenti/instagram_token.py
"""
import json
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CARTELLA = Path(__file__).resolve().parent.parent
CONFIG = CARTELLA / "config.toml"
GRAPH = "https://graph.facebook.com/v25.0"
SEZIONE = "purestats_instagram"


def chiama(percorso, **parametri):
    url = f"{GRAPH}/{percorso}?{urllib.parse.urlencode(parametri)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        dettaglio = err.read().decode("utf-8", "replace")
        try:
            dettaglio = json.loads(dettaglio)["error"]["message"]
        except (ValueError, KeyError):
            dettaglio = dettaglio[:300]
        sys.exit(f"Meta ha rifiutato la richiesta «{percorso.split('/')[0]}»: {dettaglio}\n"
                 "Niente è stato scritto in config.toml.")


def chiedi(testo, nascosto=True, forma=None):
    valore = re.sub(r"\s+", "", input(testo))   # visibile solo sul terminale: getpass non riceveva l'incolla
    if not valore or (forma and not re.fullmatch(forma, valore)):
        # solo la lunghezza e i tipi di carattere, mai il valore: bastano a capire cosa è andato storto
        tipi = ", ".join(n for n, r in (("cifre", r"\d"), ("lettere minuscole", r"[a-z]"), ("maiuscole", r"[A-Z]"),
                                        ("altri simboli", r"[^A-Za-z0-9]")) if re.search(r, valore)) or "niente"
        sys.exit(f"Valore non valido per «{testo.split('(')[0].strip(': ')}»: ricevuti {len(valore)} caratteri ({tipi}).\n"
                 "Niente è stato scritto in config.toml.")
    return valore


def main():
    if not CONFIG.exists():
        sys.exit(f"Non trovo {CONFIG}: lancia lo script dalla cartella del bot.")
    testo = CONFIG.read_text(encoding="utf-8")
    if re.search(rf"^\[{SEZIONE}\]\s*$", testo, re.M):
        if input(f"In config.toml c'è già [{SEZIONE}]. La sostituisco? (si/no) ").strip().lower() not in ("si", "sì", "s"):
            sys.exit("Lasciato tutto com'era.")
    app_id = chiedi("Id dell'app (numero, si vede): ", nascosto=False, forma=r"\d{6,20}")
    segreto = chiedi("Chiave segreta dell'app: ", forma=r"[0-9a-fA-F]{32}")
    breve = chiedi("Token di Graph API Explorer: ", forma=r"[A-Za-z0-9_\-]{60,}")

    lungo = chiama("oauth/access_token", grant_type="fb_exchange_token", client_id=app_id,
                   client_secret=segreto, fb_exchange_token=breve)["access_token"]
    pagine = chiama("me/accounts", fields="id,name,access_token,instagram_business_account",
                    access_token=lungo).get("data") or []
    pagine = [p for p in pagine if p.get("instagram_business_account")]
    if not pagine:
        sys.exit("Nessuna Pagina Facebook con un account Instagram collegato tra quelle autorizzate.\n"
                 "In Graph API Explorer, quando entri, spunta la Pagina PureStats e l'account Instagram. Niente è stato scritto.")
    if len(pagine) > 1:
        for i, p in enumerate(pagine, 1):
            print(f"  {i}. {p['name']}")
        pagina = pagine[int(chiedi("Quale Pagina? (numero) ", nascosto=False, forma=r"\d+")) - 1]
    else:
        pagina = pagine[0]
    ig_id = pagina["instagram_business_account"]["id"]
    token_pagina = pagina["access_token"]
    ig = chiama(ig_id, fields="username", access_token=token_pagina)
    scadenza = chiama("debug_token", input_token=token_pagina, access_token=f"{app_id}|{segreto}").get("data", {})
    permessi = set(scadenza.get("scopes") or [])
    mancano = {"instagram_basic", "instagram_content_publish", "pages_show_list", "pages_manage_posts"} - permessi

    # riscrive la sezione: via quella vecchia (fino alla sezione successiva), poi la nuova in fondo
    testo = re.sub(rf"(?ms)^\[{SEZIONE}\]\s*$.*?(?=^\[|\Z)", "", testo).rstrip() + "\n\n"
    testo += (f"[{SEZIONE}]\n"
              f'pagina_id = "{pagina["id"]}"\n'
              f'instagram_id = "{ig_id}"\n'
              f'app_id = "{app_id}"\n'
              f'app_segreto = "{segreto}"\n'
              f'token = "{token_pagina}"\n')
    tomllib.loads(testo)                                     # se non è valido si ferma prima di scrivere
    copia = CONFIG.with_suffix(".toml.prima_instagram")
    copia.write_text(CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    copia.chmod(0o600)                                       # contiene chiavi: leggibile solo dal proprietario
    CONFIG.write_text(testo, encoding="utf-8")
    CONFIG.chmod(0o600)
    scade = scadenza.get("expires_at", 0)
    print("\033[2J\033[H", end="")                          # pulisce lo schermo: chiave e token non restano visibili
    print(f"Fatto. Pagina «{pagina['name']}» collegata a Instagram @{ig.get('username')}.\n"
          f"Token della Pagina {'senza scadenza' if not scade else 'CON scadenza: va rifatto, scrivimelo'}; "
          f"config.toml valido (copia di prima in {copia.name}).")
    if mancano:
        print("ATTENZIONE: al token mancano i permessi " + ", ".join(sorted(mancano)) +
              ". Rigenera il token in Graph API Explorer aggiungendoli e rilancia lo script.")


if __name__ == "__main__":
    main()
