"""Canale Telegram ufficiale PureStats e bot dei comandi (dal 28/11/2026, scelta di Valerio).

Nel canale escono, una volta sola ciascuno: la guida «In TV in Italia» alle 9 nei giorni di partita NFL, gli avvisi
meteo che contano, gli articoli nuovi (anteprime e cronache NFL e college), gli aggiornamenti delle anteprime (una volta
per ogni aggiornamento, con la nota), i racconti delle Leggende e le carte 2187.
Il bot risponde ai comandi /tv /meteo /articoli /leggende /carte /sito /aiuto SOLO a Valerio (chat_id della sezione
[telegram] di Radar Assenze, scelta del 28/11/2026: niente comandi pubblici, nessun rischio di raffiche di messaggi);
gli altri vengono ignorati senza risposta.
Legge SOLO i file pubblici di purestats.it: niente Matchup, niente Charlie, niente scommesse (Decreto Dignità art. 9).
È un bot diverso da Radar Assenze, che resta privato.

Configurazione in config.toml (sezione [purestats_canale]; [canale] è già usata dal bot Radar Assenze):
    token = ""                 token del bot pubblico «PureStats» creato con @BotFather
    canale = "@nomecanale"     il canale (il bot deve esserne amministratore)
Uso (dalla cartella del bot Radar Assenze, crontab dell'utente ubuntu):
    python3 strumenti/purestats_canale.py avvisi     ogni 15 minuti: manda le novità nel canale
    python3 strumenti/purestats_canale.py bot        ogni minuto: risponde ai comandi (attesa fino a 50 secondi)
    python3 strumenti/purestats_canale.py configura  una volta: elenco dei comandi e descrizione del bot
    python3 strumenti/purestats_canale.py prova      mostra i messaggi senza mandarli
Al primo giro di «avvisi» segna come già visto tutto ciò che è già pubblicato: niente raffica di messaggi vecchi.
Stato in data/canale_stato.json, registro in data/canale.log (ultime 300 righe).
"""
import html
import json
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CARTELLA = Path(__file__).resolve().parent.parent
STATO = CARTELLA / "data" / "canale_stato.json"
STATO_BOT = CARTELLA / "data" / "canale_bot.json"     # separato: «bot» e «avvisi» girano insieme
SCELTE_SOCIAL = CARTELLA / "data" / "social_scelte.json"   # bottoni di Instagram/Facebook (purestats_social.py)
REGISTRO = CARTELLA / "data" / "canale.log"
SITO = "https://purestats.it"
ROMA, EST = ZoneInfo("Europe/Rome"), ZoneInfo("America/New_York")
ADESSO = datetime.now(timezone.utc)
ORA_GUIDA = 9                        # guida TV alle 9 italiane (scelta di Valerio)
UA = {"User-Agent": "purestats-canale (canale ufficiale PureStats)"}
FIRMA = "Personaggio immaginario · immagine creata con AI"


def scrivi(riga):
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    righe = REGISTRO.read_text(encoding="utf-8").splitlines()[-299:] if REGISTRO.exists() else []
    righe.append(f"{ADESSO:%Y-%m-%d %H:%M} UTC  {riga}")
    REGISTRO.write_text("\n".join(righe) + "\n", encoding="utf-8")


def pubblico(percorso):
    """Un file pubblico del sito (sempre fresco). Con CANALE_LOCALE=<cartella docs> legge da disco (prove)."""
    import os
    if os.environ.get("CANALE_LOCALE"):
        return json.loads((Path(os.environ["CANALE_LOCALE"]) / percorso).read_text(encoding="utf-8"))
    req = urllib.request.Request(f"{SITO}/{percorso}?t={int(ADESSO.timestamp())}", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def e(x):
    return html.escape(str(x or ""), quote=False)


class Telegram:
    def __init__(self, token):
        self.token = token

    def chiama(self, metodo, dati, attesa=30):
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/{metodo}",
                                     data=json.dumps(dati).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=attesa + 10) as r:
            return json.loads(r.read().decode("utf-8"))

    def testo(self, chat, t):
        return self.chiama("sendMessage", {"chat_id": chat, "text": t, "parse_mode": "HTML",
                                           "link_preview_options": {"is_disabled": True}})

    def foto(self, chat, url, didascalia):
        return self.chiama("sendPhoto", {"chat_id": chat, "photo": url, "caption": didascalia, "parse_mode": "HTML"})


# ------------------------------------------------------------------ nomi, date, fasce
NOMI = {}


def nome(sigla):
    return NOMI.get(sigla) or sigla


def quando(data_it, ora_it):
    try:
        d = datetime.fromisoformat(f"{data_it}T{ora_it or '12:00'}")
    except ValueError:
        return f"{data_it} {ora_it or ''}".strip()
    giorni = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
    return f"{giorni[d.weekday()]} {d:%d/%m}" + (f" · {ora_it}" if ora_it else "")


def inizio_utc(p):
    """Inizio della partita NFL in UTC dall'ora della costa est (data, ora di nflverse)."""
    try:
        t = datetime.fromisoformat(f"{p['data']}T{p.get('ora') or '13:00'}").replace(tzinfo=EST)
        return t.astimezone(timezone.utc)
    except (KeyError, ValueError):
        return None


def fascia(t_utc):
    t = t_utc.astimezone(EST)
    g, h, m, d = t.weekday(), t.hour, t.month, t.day
    if m == 12 and d == 25:
        return "Natale"
    if m == 11 and g == 3 and 22 <= d <= 28:
        return "Thanksgiving"
    if m == 11 and g == 4 and 23 <= d <= 29:
        return "Black Friday"
    if g == 3:
        return "Thursday Night Football"
    if g == 0:
        return "Monday Night Football"
    if g == 6:
        return "Sunday Night Football" if h >= 19 else ""
    return "partita in notturna" if h >= 19 else ""


# ------------------------------------------------------------------ messaggi
def guida_tv(dati_nfl, tv, giorno=None):
    """Partite NFL dalle 9 di oggi alle 9 di domani (ora italiana). None se non ce ne sono."""
    oggi = (giorno or ADESSO.astimezone(ROMA)).date()
    da = datetime(oggi.year, oggi.month, oggi.day, ORA_GUIDA, tzinfo=ROMA)
    a = da + timedelta(days=1)
    partite = []
    for p in dati_nfl.get("ultimePartite") or []:
        t = inizio_utc(p)
        if t and da <= t.astimezone(ROMA) < a and p.get("pc") is None:
            partite.append((t, p))
    if not partite:
        return None
    partite.sort(key=lambda x: x[0])
    righe = []
    for t, p in partite:
        sett = (tv.get("settimane") or {}).get(f"{p['stagione']}|{int(p['settimana'])}") or {}
        incl = f"{p['ospite']}@{p['casa']}" in (sett.get("incluse") or {})
        f = fascia(t)
        righe.append(f"{'✅' if incl else '▫️'} <b>{t.astimezone(ROMA):%H:%M}</b> {e(nome(p['ospite']))} @ {e(nome(p['casa']))}"
                     + (f" · <i>{e(f)}</i>" if f else ""))
    giorni = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
    return (f"📺 <b>NFL in TV in Italia · {giorni[oggi.weekday()]} {oggi:%d/%m}</b>\n\n" + "\n".join(righe)
            + "\n\nTutte su NFL Game Pass (DAZN) · ✅ incluse anche negli abbonamenti DAZN\n"
            + f"Orari italiani · {SITO}")


def meteo_rilevante(meteo, dati_nfl, dati_college, articoli, ore=36, livelli=("alto",)):
    """[(chiave, testo)] delle partite nelle prossime `ore` con impatto del meteo nei livelli dati.
    NFL tutte; college solo quelle con un articolo (le partite di cartello)."""
    out = []
    con_articolo = {(a.get("stagione"), a.get("settimana"), a.get("casa"), a.get("ospite")) for a in articoli
                    if a.get("lega") == "college"}
    for lega, dati in (("nfl", dati_nfl), ("college", dati_college)):
        for p in (dati or {}).get("ultimePartite") or []:
            if p.get("pc") is not None:
                continue
            k = f"{p['stagione']}|{int(p['settimana'])}|{p['casa']}|{p['ospite']}"
            m = ((meteo or {}).get(lega) or {}).get(k)
            if not m or m.get("coperto") or m.get("impatto") not in livelli:
                continue
            if lega == "college" and (int(p["stagione"]), int(p["settimana"]), p["casa"], p["ospite"]) not in con_articolo:
                continue
            try:
                t = datetime.fromisoformat(f"{p['dataIt']}T{p.get('oraIt') or '12:00'}").replace(tzinfo=ROMA)
            except (KeyError, ValueError):
                continue
            if not (ADESSO <= t <= ADESSO + timedelta(hours=ore)):
                continue
            pezzi = []
            if m.get("ventoKmh") is not None:
                pezzi.append(f"vento {m['ventoKmh']} km/h" + (f", raffiche {m['raffKmh']}" if m.get("raffKmh") else ""))
            if m.get("pioggia"):
                pezzi.append(f"pioggia {m['pioggia']}%")
            if m.get("tempC") is not None:
                pezzi.append(f"{m['tempC']} °C")
            sigla = "NFL" if lega == "nfl" else "College"
            testo = (f"🌬️ <b>Meteo · {e(nome(p['ospite']) if lega == 'nfl' else p['ospite'])} @ "
                     f"{e(nome(p['casa']) if lega == 'nfl' else p['casa'])}</b> ({sigla})\n"
                     f"{e(quando(p['dataIt'], p.get('oraIt')))} · impatto <b>{e(m['impatto'])}</b>\n" + " · ".join(pezzi))
            out.append((f"meteo|{k}|{m['impatto']}", testo))
    return out


def msg_articolo(a):
    tipo = "🏁 Cronaca" if a.get("tipo") == "cronaca" else "📰 Anteprima"
    lega = "NFL" if a.get("lega") == "nfl" else "College"
    sq = f"{nome(a['ospite'])} @ {nome(a['casa'])}" if a.get("lega") == "nfl" else f"{a.get('ospite')} @ {a.get('casa')}"
    return (f"{tipo} {lega} · {e(sq)}\n<b>{e(a.get('titolo'))}</b>\n"
            + (f"{e(quando(a.get('dataIt'), a.get('oraIt')))}\n" if a.get("tipo") != "cronaca" else "")
            + f"{SITO}/a/{a['id']}.html")


def msg_aggiornamento(a):
    """Anteprima aggiornata con una novità vera (25/11/2026): la nota dell'ultimo aggiornamento e il collegamento.
    La nota sta nel file dell'articolo, non nell'indice: si legge solo quando c'è davvero da mandare."""
    lega = "NFL" if a.get("lega") == "nfl" else "College"
    sq = f"{nome(a['ospite'])} @ {nome(a['casa'])}" if a.get("lega") == "nfl" else f"{a.get('ospite')} @ {a.get('casa')}"
    nota = ""
    try:
        nota = ((pubblico(f"articoli/{a['id']}.json").get("aggiornamenti") or [{}])[-1].get("nota") or "").strip()
    except Exception as x:               # noqa: BLE001 - senza nota il messaggio esce lo stesso
        scrivi(f"nota dell'aggiornamento di {a['id']} non letta: {x}")
    return (f"🔄 Aggiornamento · Anteprima {lega} · {e(sq)}\n<b>{e(a.get('titolo'))}</b>\n"
            + (f"{e(nota)}\n" if nota else "")
            + f"{e(quando(a.get('dataIt'), a.get('oraIt')))}\n{SITO}/a/{a['id']}.html")


def msg_racconto(r):
    lega = "College" if r.get("lega") == "college" else "NFL"
    return f"📜 Leggende {lega}\n<b>{e(r.get('titolo'))}</b>\n{e(r.get('occhiello'))}\n{SITO}/l/{r['id']}.html"


def msg_carta(c):
    return (f"🃏 <b>2187 · Nº {int(c['n']):03d} {e(c.get('nome'))}</b>\n"
            f"{e(c.get('ruolo'))} · {e(c.get('squadra'))} · {e(c.get('rarita'))}\n"
            f"{e(c.get('sintesi'))}\n<i>{FIRMA}</i>\n{SITO}/#carta={int(c['n'])}")


def carte_uscite(lega_json):
    oggi = ADESSO.astimezone(ROMA).date().isoformat()
    return [c for c in lega_json.get("carte") or [] if (c.get("uscita") or "") <= oggi] if lega_json.get("pubblica") else []


# ------------------------------------------------------------------ dati del sito
def carica():
    d = {}
    for chiave, perc in (("nfl", "data_nfl.json"), ("college", "data_college.json"), ("tv", "tv_italia.json"),
                         ("meteo", "meteo/partite.json"), ("articoli", "articoli/indice.json"),
                         ("racconti", "leggende/racconti.json"), ("lega", "lega/lega.json")):
        try:
            d[chiave] = pubblico(perc)
        except Exception as x:       # noqa: BLE001 - un file che manca toglie solo i suoi messaggi
            scrivi(f"{perc} non letto: {x}")
            d[chiave] = {} if chiave not in ("articoli",) else []
    for sigla, v in ((d.get("nfl") or {}).get("loghi") or {}).items():
        NOMI[sigla] = v.get("breve") or sigla
    r = d.get("racconti")
    d["racconti"] = r if isinstance(r, list) else (r or {}).get("racconti", [])
    return d


def novita(d):
    """[(chiave, tipo, contenuto)] di tutto ciò che il canale deve mandare adesso, in ordine."""
    out = []
    ora = ADESSO.astimezone(ROMA)
    if ora.hour >= ORA_GUIDA:
        g = guida_tv(d.get("nfl") or {}, d.get("tv") or {})
        if g:
            out.append((f"tv|{ora.date().isoformat()}", "testo", g))
    for k, t in meteo_rilevante(d.get("meteo"), d.get("nfl"), d.get("college"), d.get("articoli") or []):
        out.append((k, "testo", t))
    for a in sorted(d.get("articoli") or [], key=lambda x: x.get("pubblicato") or ""):
        out.append((f"articolo|{a['id']}", "testo", msg_articolo(a)))
        if a.get("aggiornato") and a.get("tipo") == "anteprima":
            # chiave con l'ora: ogni nuovo aggiornamento esce una volta; il testo si prepara solo se serve (lambda)
            out.append((f"agg|{a['id']}|{a['aggiornato']}", "testo", lambda a=a: msg_aggiornamento(a)))
    for r in sorted(d.get("racconti") or [], key=lambda x: x.get("pubblicato") or ""):
        out.append((f"racconto|{r['id']}", "testo", msg_racconto(r)))
    for c in sorted(carte_uscite(d.get("lega") or {}), key=lambda x: x["n"]):
        out.append((f"carta|{c['n']}", "foto", (f"{SITO}/{c['fronte']}", msg_carta(c))))
    return out


def leggi_stato():
    try:
        return json.loads(STATO.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def salva_stato(s):
    STATO.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATO.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATO)


# ------------------------------------------------------------------ modalità
def avvisi(cfg, prova=False):
    c = cfg.get("purestats_canale", {})
    if not prova and (not c.get("token") or not c.get("canale")):
        scrivi("manca la sezione [purestats_canale] (token, canale) in config.toml: niente avvisi")
        return
    d = carica()
    stato = leggi_stato()
    visti = set(stato.get("visti") or [])
    tutte = novita(d)
    if prova:
        for k, tipo, x in tutte:
            if callable(x) and k not in visti:
                x = x()
            print(("GIÀ VISTO " if k in visti else "NUOVO ") + k + "\n" + (x if tipo == "testo" and isinstance(x, str)
                  else x[1] if tipo == "foto" else "(testo preparato solo all'invio)") + "\n")
        return
    if not stato:
        # primo giro: quello che è già sul sito non si rimanda; la guida TV di oggi e il meteo sì
        stato = {"visti": [k for k, _t, _x in tutte if not k.startswith(("tv|", "meteo|"))], "inizio": ADESSO.isoformat()}
        salva_stato(stato)
        scrivi(f"primo giro: {len(stato['visti'])} contenuti già pubblicati segnati come visti")
        visti = set(stato["visti"])
    if not stato.get("aggiornamenti_dal"):
        # avvisi degli aggiornamenti attivati il 28/11/2026: quelli già fatti prima non si mandano
        visti |= {k for k, _t, _x in tutte if k.startswith("agg|")}
        stato["aggiornamenti_dal"] = ADESSO.isoformat()
    tg = Telegram(c["token"])
    mandati = 0
    for k, tipo, x in tutte:
        if k in visti:
            continue
        if callable(x):
            x = x()
        try:
            tg.testo(c["canale"], x) if tipo == "testo" else tg.foto(c["canale"], x[0], x[1])
        except urllib.error.HTTPError as err:
            scrivi(f"{k}: Telegram ha risposto {err.code} ({err.read().decode('utf-8', 'replace')[:200]})")
            if err.code in (401, 403):
                break                    # token sbagliato o bot non amministratore: inutile continuare
            continue
        except Exception as err:         # noqa: BLE001
            scrivi(f"{k}: non mandato ({err})")
            continue
        visti.add(k)
        mandati += 1
    stato["visti"] = sorted(visti)[-3000:]
    salva_stato(stato)
    if mandati:
        scrivi(f"mandati {mandati} messaggi nel canale")


AIUTO = ("Ciao! Sono il bot di <b>PureStats</b>, statistiche NFL e college football.\n\n"
         "/tv · le partite NFL in TV in Italia\n/meteo · il meteo che conta nelle prossime 48 ore\n"
         "/articoli · le ultime anteprime e cronache\n/leggende · gli ultimi racconti\n"
         "/carte · le ultime carte di 2187\n/sito · il sito\n\nGli avvisi arrivano anche nel canale ufficiale.")
COMANDI = [("tv", "Partite NFL in TV in Italia"), ("meteo", "Meteo che conta nelle prossime 48 ore"),
           ("articoli", "Ultime anteprime e cronache"), ("leggende", "Ultimi racconti delle Leggende"),
           ("carte", "Ultime carte di 2187"), ("sito", "Il sito PureStats"), ("aiuto", "Cosa posso fare")]


def risposta(comando, d):
    if comando in ("start", "aiuto", "help"):
        return AIUTO
    if comando == "sito":
        return f"🏈 {SITO}"
    if comando == "tv":
        oggi = ADESSO.astimezone(ROMA)
        for i in range(0, 8):                 # oggi, altrimenti il prossimo giorno di partita
            g = guida_tv(d.get("nfl") or {}, d.get("tv") or {}, oggi + timedelta(days=i))
            if g:
                return g
        return "Nessuna partita NFL nei prossimi giorni."
    if comando == "meteo":
        m = meteo_rilevante(d.get("meteo"), d.get("nfl"), d.get("college"), d.get("articoli") or [], ore=48,
                            livelli=("alto", "medio"))
        return "\n\n".join(t for _k, t in m) if m else "🌤️ Nessuna partita con meteo che conta nelle prossime 48 ore."
    if comando == "articoli":
        a = sorted(d.get("articoli") or [], key=lambda x: x.get("pubblicato") or "", reverse=True)[:5]
        return "\n\n".join(msg_articolo(x) for x in a) if a else "Nessun articolo per ora."
    if comando == "leggende":
        r = sorted(d.get("racconti") or [], key=lambda x: x.get("pubblicato") or "", reverse=True)[:3]
        return "\n\n".join(msg_racconto(x) for x in r) if r else "Nessun racconto per ora."
    if comando == "carte":
        c = sorted(carte_uscite(d.get("lega") or {}), key=lambda x: -x["n"])[:3]
        return "\n\n".join(msg_carta(x) for x in c) if c else "Nessuna carta per ora."
    return None


def bot(cfg):
    """Un giro: aspetta i messaggi fino a 50 secondi, risponde ai comandi, esce (il crontab lo rilancia ogni minuto)."""
    c = cfg.get("purestats_canale", {})
    if not c.get("token"):
        return
    titolare = str((cfg.get("telegram") or {}).get("chat_id") or "").strip()
    if not titolare:
        scrivi("bot: manca chat_id in [telegram]: nessuno può usare i comandi")
    tg = Telegram(c["token"])
    try:
        stato = json.loads(STATO_BOT.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        stato = {}
    try:
        r = tg.chiama("getUpdates", {"offset": stato.get("offset", 0), "timeout": 50,
                                     "allowed_updates": ["message", "callback_query"]}, attesa=50)
    except Exception as err:             # noqa: BLE001
        scrivi(f"bot: getUpdates non riuscito ({err})")
        return
    aggiornamenti = r.get("result") or []
    if not aggiornamenti:
        return
    d = None
    for u in aggiornamenti:
        stato["offset"] = u["update_id"] + 1
        if u.get("callback_query"):
            scelta_social(tg, u["callback_query"], titolare)
            continue
        m = u.get("message") or {}
        testo = (m.get("text") or "").strip()
        chat = m.get("chat") or {}
        if not testo.startswith("/") or chat.get("type") != "private" or str(chat.get("id")) != titolare:
            continue                     # solo Valerio: gli altri messaggi si scartano senza rispondere
        comando = testo[1:].split()[0].split("@")[0].lower()
        if d is None:
            d = carica()
        t = risposta(comando, d) or AIUTO
        try:
            tg.testo(m["chat"]["id"], t)
        except Exception as err:         # noqa: BLE001
            scrivi(f"bot: risposta a /{comando} non mandata ({err})")
    STATO_BOT.parent.mkdir(parents=True, exist_ok=True)
    STATO_BOT.write_text(json.dumps({"offset": stato["offset"]}), encoding="utf-8")


def scelta_social(tg, cq, titolare):
    """Bottoni ✅/📸/❌ delle proposte Instagram-Facebook: la scelta va in social_scelte.json, la esegue
    purestats_social.py al suo giro (entro 2 minuti). Solo Valerio; i bottoni spariscono subito (niente doppio clic)."""
    dati = (cq.get("data") or "").split("|")
    msg = cq.get("message") or {}
    if str((cq.get("from") or {}).get("id")) != titolare or len(dati) != 3 or dati[0] != "s" or dati[1] not in ("e", "i", "x"):
        try:
            tg.chiama("answerCallbackQuery", {"callback_query_id": cq["id"]})    # niente rotellina infinita
        except Exception:                # noqa: BLE001
            pass
        return
    try:
        scelte = json.loads(SCELTE_SOCIAL.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        scelte = []
    scelte.append({"numero": int(dati[2]), "scelta": dati[1], "quando": ADESSO.isoformat(timespec="minutes")})
    SCELTE_SOCIAL.parent.mkdir(parents=True, exist_ok=True)
    tmp = SCELTE_SOCIAL.with_suffix(".tmp")
    tmp.write_text(json.dumps(scelte), encoding="utf-8")
    tmp.replace(SCELTE_SOCIAL)
    avviso = {"e": "Pubblico su Instagram e Facebook…", "i": "Pubblico solo su Instagram…", "x": "Scartato"}[dati[1]]
    # il giro di pubblicazione parte subito, senza aspettare il crontab (stesso lucchetto: mai due giri insieme)
    try:
        subprocess.Popen(["flock", "-n", "/tmp/purestats_social.lock", sys.executable,
                          str(Path(__file__).resolve().parent / "purestats_social.py"), "giro"],
                         cwd=CARTELLA, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as err:
        scrivi(f"bot: giro social non lanciato subito ({err}), parte col crontab")
    try:
        tg.chiama("answerCallbackQuery", {"callback_query_id": cq["id"], "text": avviso})
        tg.chiama("editMessageReplyMarkup", {"chat_id": msg["chat"]["id"], "message_id": msg["message_id"],
                                             "reply_markup": {"inline_keyboard": []}})   # bottoni via: niente doppio tocco
    except Exception as err:             # noqa: BLE001 - la scelta è già salvata
        scrivi(f"bot: conferma del bottone non mostrata ({err})")


def configura(cfg):
    """Menu dei comandi visibile solo nella chat di Valerio; per gli altri il bot rimanda al canale e al sito."""
    tg = Telegram(cfg["purestats_canale"]["token"])
    titolare = str((cfg.get("telegram") or {}).get("chat_id") or "").strip()
    tg.chiama("deleteMyCommands", {})                       # nessun menu per gli altri
    if titolare:
        tg.chiama("setMyCommands", {"commands": [{"command": k, "description": v} for k, v in COMANDI],
                                    "scope": {"type": "chat", "chat_id": int(titolare)}})
    tg.chiama("setMyDescription", {"description": "Bot del canale ufficiale PureStats (t.me/purestats1): "
                                                  "statistiche NFL e college football su purestats.it"})
    tg.chiama("setMyShortDescription", {"short_description": "Canale ufficiale: t.me/purestats1 · purestats.it"})
    print("Menu dei comandi solo per il titolare" + ("" if titolare else " (manca chat_id: nessun menu)")
          + "; descrizione del bot impostata.")


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    cfg = tomllib.load(open(CARTELLA / "config.toml", "rb")) if (CARTELLA / "config.toml").exists() else {}
    if modo == "avvisi":
        avvisi(cfg)
    elif modo == "prova":
        avvisi(cfg, prova=True)
    elif modo == "bot":
        bot(cfg)
    elif modo == "configura":
        configura(cfg)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
