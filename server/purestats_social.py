"""Instagram e Pagina Facebook di PureStats (dal 28/11/2026, scelta di Valerio).

Legge la coda preparata da scripts/social.py (ramo «social» del repository, pubblico), propone ogni contenuto a
Valerio in privato con il bot PureStats (immagini + didascalia + bottoni) e lo pubblica SOLO dopo il suo ✅:
  ✅ Instagram + Facebook · 📸 Solo Instagram · ❌ Scarta
I bottoni li riceve il bot (purestats_canale.py, modo «bot»), che scrive la scelta in data/social_scelte.json;
questo script, a ogni giro, la esegue e aggiorna il messaggio con il risultato e i collegamenti.
Niente scommesse né Charlie: i contenuti vengono solo dai file pubblici del sito.

Configurazione in config.toml:
  [purestats_instagram]  token (della Pagina, senza scadenza), instagram_id, pagina_id  ← strumenti/instagram_token.py
                         automatici = []   tipi da pubblicare senza chiedere (es. ["accadde"]); vuoto = chiede sempre
  [purestats_canale]     token del bot PureStats;  [telegram] chat_id di Valerio
Uso (crontab, ogni 2 minuti, con flock):
  python3 strumenti/purestats_social.py giro     propone i nuovi, esegue le scelte, segna gli scaduti
  python3 strumenti/purestats_social.py prova    controlla token e account e prova a preparare (non pubblica) un'immagine
Stato in data/social_stato.json, registro in data/social.log (ultime 300 righe).
"""
import json
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CARTELLA = Path(__file__).resolve().parent.parent
STATO = CARTELLA / "data" / "social_stato.json"
SCELTE = CARTELLA / "data" / "social_scelte.json"     # scritto dal bot quando Valerio preme un bottone
REGISTRO = CARTELLA / "data" / "social.log"
RAMO = "https://raw.githubusercontent.com/doubleuptip/purestats/social"
GRAPH = "https://graph.facebook.com/v25.0"
VIDEO = "https://graph-video.facebook.com/v25.0"
ADESSO = datetime.now(timezone.utc)
UA = {"User-Agent": "purestats-social (pubblicazione PureStats)"}
NOMI_TIPO = {"guida": "📺 Guida TV", "carte": "⭐ Carte 2187", "reel": "🎬 Reel 2187", "leggenda": "📖 Leggende",
             "anteprima": "🏈 Anteprima", "cronaca": "🏁 Cronaca", "risultati": "📊 Risultati", "accadde": "📅 Accadde oggi",
             "corsa": "📈 Corsa ai playoff"}


def scrivi(riga):
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    righe = REGISTRO.read_text(encoding="utf-8").splitlines()[-299:] if REGISTRO.exists() else []
    righe.append(f"{ADESSO:%Y-%m-%d %H:%M} UTC  {riga}")
    REGISTRO.write_text("\n".join(righe) + "\n", encoding="utf-8")


def leggi_json(p, vuoto):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return vuoto


def salva_json(p, dati):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def http(url, dati=None, intestazioni=None, corpo=None, attesa=60):
    """POST se ci sono dati o corpo, altrimenti GET. Errori HTTP → RuntimeError con il messaggio di Meta/Telegram."""
    if dati is not None:
        corpo = urllib.parse.urlencode(dati).encode()
    req = urllib.request.Request(url, data=corpo, headers={**UA, **(intestazioni or {})})
    try:
        with urllib.request.urlopen(req, timeout=attesa) as r:
            testo = r.read()
    except urllib.error.HTTPError as err:
        dettaglio = err.read().decode("utf-8", "replace")
        try:
            j = json.loads(dettaglio)
            dettaglio = (j.get("error") or {}).get("message") or j.get("description") or dettaglio
        except ValueError:
            pass
        raise RuntimeError(f"HTTP {err.code}: {str(dettaglio)[:300]}") from None
    try:
        return json.loads(testo.decode("utf-8"))
    except ValueError:
        return testo


# ------------------------------------------------------------------ Telegram (bot PureStats, chat di Valerio)
class Bot:
    def __init__(self, token, chat):
        self.base, self.chat = f"https://api.telegram.org/bot{token}/", chat

    def chiama(self, metodo, **dati):
        dati = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in dati.items()}
        return http(self.base + metodo, dati=dati).get("result")

    def proponi(self, voce, numero):
        if voce.get("video"):
            self.chiama("sendVideo", chat_id=self.chat, video=f"{RAMO}/{voce['video']}", supports_streaming="true")
        elif len(voce["immagini"]) == 1:
            self.chiama("sendPhoto", chat_id=self.chat, photo=f"{RAMO}/{voce['immagini'][0]}")
        else:
            self.chiama("sendMediaGroup", chat_id=self.chat,
                        media=[{"type": "photo", "media": f"{RAMO}/{x}"} for x in voce["immagini"][:10]])
        bottoni = {"inline_keyboard": [[{"text": "✅ Instagram + Facebook", "callback_data": f"s|e|{numero}"}],
                                       [{"text": "📸 Solo Instagram", "callback_data": f"s|i|{numero}"},
                                        {"text": "❌ Scarta", "callback_data": f"s|x|{numero}"}]]}
        scade = datetime.fromisoformat(voce["scade"]).astimezone(ZoneInfo("Europe/Rome")).strftime("%d/%m alle %H:%M")
        return self.chiama("sendMessage", chat_id=self.chat, parse_mode="HTML", reply_markup=bottoni,
                           text=f"<b>{NOMI_TIPO.get(voce['tipo'], voce['tipo'])}</b> · da pubblicare?\n"
                                f"<i>Scade il {scade}</i>\n\n{esc(voce['didascalia'])}")["message_id"]

    def esito(self, msg_id, testo_vecchio, riga):
        try:
            self.chiama("editMessageText", chat_id=self.chat, message_id=msg_id, parse_mode="HTML",
                        text=(testo_vecchio or "")[:3500] + "\n\n" + riga, disable_web_page_preview="true")
        except RuntimeError:
            self.chiama("sendMessage", chat_id=self.chat, parse_mode="HTML", text=riga)


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ------------------------------------------------------------------ Meta
class Meta:
    def __init__(self, c):
        self.token, self.ig, self.pagina = c["token"], c["instagram_id"], c["pagina_id"]

    def g(self, percorso, **parametri):
        return http(f"{GRAPH}/{percorso}?" + urllib.parse.urlencode({**parametri, "access_token": self.token}))

    def p(self, percorso, base=GRAPH, **dati):
        return http(f"{base}/{percorso}", dati={**dati, "access_token": self.token}, attesa=180)

    def aspetta(self, contenitore, massimo=300):
        """Meta prepara il contenuto in background: si aspetta FINISHED (immagini pochi secondi, video fino a minuti)."""
        fine = time.time() + massimo
        while time.time() < fine:
            st = self.g(contenitore, fields="status_code,status").get("status_code")
            if st == "FINISHED":
                return
            if st in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram non ha accettato il contenuto ({self.g(contenitore, fields='status').get('status')})")
            time.sleep(5)
        raise RuntimeError("Instagram non ha finito di preparare il contenuto in 5 minuti")

    def instagram(self, voce):
        ai = {"is_ai_generated": "true"} if voce.get("ai") else {}
        if voce.get("video"):
            dati = http(f"{RAMO}/{voce['video']}", attesa=120)
            c = self.p(f"{self.ig}/media", media_type="REELS", upload_type="resumable", caption=voce["didascalia"],
                       share_to_feed="true", **ai)
            http(c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/v25.0/{c['id']}", corpo=dati, attesa=300,
                 intestazioni={"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(len(dati))})
            contenitore = c["id"]
        elif len(voce["immagini"]) == 1:
            contenitore = self.p(f"{self.ig}/media", image_url=f"{RAMO}/{voce['immagini'][0]}", caption=voce["didascalia"], **ai)["id"]
        else:
            figli = []
            for x in voce["immagini"][:10]:
                figli.append(self.p(f"{self.ig}/media", image_url=f"{RAMO}/{x}", is_carousel_item="true")["id"])
            for f in figli:
                self.aspetta(f, 120)
            contenitore = self.p(f"{self.ig}/media", media_type="CAROUSEL", children=",".join(figli),
                                 caption=voce["didascalia"], **ai)["id"]
        self.aspetta(contenitore)
        mid = self.p(f"{self.ig}/media_publish", creation_id=contenitore)["id"]
        try:
            return self.g(mid, fields="permalink").get("permalink") or "https://www.instagram.com/purestats1/"
        except RuntimeError:
            return "https://www.instagram.com/purestats1/"

    def facebook(self, voce):
        if voce.get("video"):
            r = self.p(f"{self.pagina}/videos", base=VIDEO, file_url=f"{RAMO}/{voce['video']}", description=voce["didascalia"])
            return f"https://www.facebook.com/{r.get('id')}"
        foto = [self.p(f"{self.pagina}/photos", url=f"{RAMO}/{x}", published="false")["id"] for x in voce["immagini"][:10]]
        dati = {"message": voce["didascalia"]}
        for i, f in enumerate(foto):
            dati[f"attached_media[{i}]"] = json.dumps({"media_fbid": f})
        r = self.p(f"{self.pagina}/feed", **dati)
        return f"https://www.facebook.com/{r.get('id')}"


# ------------------------------------------------------------------ giro
def configurazione():
    cfg = tomllib.load(open(CARTELLA / "config.toml", "rb"))
    ig, can = cfg.get("purestats_instagram") or {}, cfg.get("purestats_canale") or {}
    chat = str((cfg.get("telegram") or {}).get("chat_id") or "").strip()
    mancano = [n for n, v in (("[purestats_instagram] token/instagram_id/pagina_id",
                               ig.get("token") and ig.get("instagram_id") and ig.get("pagina_id")),
                              ("[purestats_canale] token", can.get("token")), ("[telegram] chat_id", chat)) if not v]
    if mancano:
        scrivi("configurazione incompleta, manca: " + "; ".join(mancano))
        sys.exit(1)
    return ig, Bot(can["token"], chat), Meta(ig)


def pubblica(voce, dove, meta):
    """Pubblica e restituisce la riga per Telegram. Un errore su Facebook non annulla Instagram (e viceversa)."""
    righe, ok = [], False
    try:
        righe.append(f'📸 <a href="{meta.instagram(voce)}">Instagram</a>')
        ok = True
    except Exception as x:               # noqa: BLE001
        righe.append(f"⚠️ Instagram non riuscito: {esc(x)}")
        scrivi(f"{voce['chiave']}: Instagram non riuscito ({x})")
    if dove == "e":
        try:
            righe.append(f'📘 <a href="{meta.facebook(voce)}">Facebook</a>')
            ok = True
        except Exception as x:           # noqa: BLE001
            righe.append(f"⚠️ Facebook non riuscito: {esc(x)}")
            scrivi(f"{voce['chiave']}: Facebook non riuscito ({x})")
    return ok, ("✅ <b>Pubblicato</b> · " if ok else "❌ <b>Non pubblicato</b> · ") + " · ".join(righe)


def giro():
    ig, bot, meta = configurazione()
    automatici = set(ig.get("automatici") or [])
    try:
        coda = http(f"{RAMO}/coda.json?t={int(ADESSO.timestamp())}", attesa=30)
    except Exception as x:               # noqa: BLE001
        scrivi(f"coda non letta ({x}): riprovo al prossimo giro")
        return
    voci = {v["chiave"]: v for v in (coda.get("voci") if isinstance(coda, dict) else None) or []}
    stato = leggi_json(STATO, {"voci": {}, "numero": 0})
    sv = stato["voci"]

    # 1. scelte arrivate dai bottoni
    scelte = leggi_json(SCELTE, [])
    if scelte:
        SCELTE.unlink(missing_ok=True)
    per_numero = {s.get("numero"): k for k, s in sv.items()}
    for sc in scelte:
        chiave = per_numero.get(sc.get("numero"))
        s = sv.get(chiave or "")
        if not s or s["stato"] != "proposto":
            continue
        voce = voci.get(chiave)
        if sc["scelta"] == "x":
            s["stato"] = "scartato"
            bot.esito(s["msg"], s.get("testo"), "❌ Scartato")
        elif not voce or datetime.fromisoformat(voce["scade"]) <= ADESSO:
            s["stato"] = "scaduto"
            bot.esito(s["msg"], s.get("testo"), "⌛ Scaduto: non più pubblicabile")
        else:
            ok, riga = pubblica(voce, sc["scelta"], meta)
            s["stato"] = "pubblicato" if ok else "errore"
            bot.esito(s["msg"], s.get("testo"), riga)
            scrivi(f"{chiave}: {s['stato']} ({'Instagram + Facebook' if sc['scelta'] == 'e' else 'solo Instagram'})")
        s["quando"] = ADESSO.isoformat(timespec="minutes")
        salva_json(STATO, stato)

    # 2. nuovi contenuti: proposti (o pubblicati da soli se il tipo è tra gli «automatici»)
    for chiave, voce in voci.items():
        if chiave in sv or datetime.fromisoformat(voce["scade"]) <= ADESSO:
            continue
        stato["numero"] += 1
        s = sv[chiave] = {"numero": stato["numero"], "tipo": voce["tipo"], "stato": "proposto",
                          "quando": ADESSO.isoformat(timespec="minutes")}
        try:
            if voce["tipo"] in automatici:
                ok, riga = pubblica(voce, "e", meta)
                s["stato"] = "pubblicato" if ok else "errore"
                bot.chiama("sendMessage", chat_id=bot.chat, parse_mode="HTML", disable_web_page_preview="true",
                           text=f"<b>{NOMI_TIPO.get(voce['tipo'], voce['tipo'])}</b> (automatico)\n{riga}")
            else:
                s["msg"] = bot.proponi(voce, s["numero"])
                s["testo"] = (f"<b>{NOMI_TIPO.get(voce['tipo'], voce['tipo'])}</b>\n\n{esc(voce['didascalia'])}")
        except Exception as x:           # noqa: BLE001
            del sv[chiave]
            stato["numero"] -= 1
            scrivi(f"{chiave}: proposta non mandata ({x}), riprovo al prossimo giro")
            continue
        scrivi(f"{chiave}: {s['stato']}")
        salva_json(STATO, stato)

    # 3. proposte scadute senza risposta
    for chiave, s in sv.items():
        voce = voci.get(chiave)
        if s["stato"] == "proposto" and (not voce or datetime.fromisoformat(voce["scade"]) <= ADESSO):
            s["stato"] = "scaduto"
            if s.get("msg"):
                try:
                    bot.chiama("editMessageReplyMarkup", chat_id=bot.chat, message_id=s["msg"], reply_markup={"inline_keyboard": []})
                    bot.esito(s["msg"], s.get("testo"), "⌛ Scaduto senza risposta")
                except RuntimeError:
                    pass
    # stato: si tengono 30 giorni
    stato["voci"] = {k: s for k, s in sv.items()
                     if (ADESSO - datetime.fromisoformat(s["quando"])).days <= 30}
    salva_json(STATO, stato)


def prova():
    ig, bot, meta = configurazione()
    u = meta.g(meta.ig, fields="username,followers_count")
    pg = meta.g(meta.pagina, fields="name")
    print(f"Instagram @{u.get('username')} ({u.get('followers_count', 0)} follower) · Pagina Facebook «{pg.get('name')}»")
    coda = http(f"{RAMO}/coda.json", attesa=30)
    voce = next((v for v in coda.get("voci") or [] if v.get("immagini")), None) if isinstance(coda, dict) else None
    if voce:
        c = meta.p(f"{meta.ig}/media", image_url=f"{RAMO}/{voce['immagini'][0]}", is_carousel_item="true")["id"]
        meta.aspetta(c, 120)
        print(f"Instagram legge le immagini dal ramo «social»: contenitore di prova pronto (NON pubblicato, scade da solo in 24 ore)")
    else:
        print("Coda vuota o non ancora creata: controllo delle immagini rimandato")
    bot.chiama("sendMessage", chat_id=bot.chat, text="Prova PureStats social: il bot può scriverti qui. Nessun post pubblicato.")
    print("Messaggio di prova mandato su Telegram. Tutto a posto.")


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    if modo == "giro":
        giro()
    elif modo == "prova":
        try:
            prova()
        except RuntimeError as x:
            sys.exit(f"Prova non riuscita: {x}")
    else:
        print(__doc__)
