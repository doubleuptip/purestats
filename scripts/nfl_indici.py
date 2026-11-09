"""
NFL — giornata, prossimo turno e indici di forza.

Usato da fetch_nfl.py. Tre blocchi in più nel file della dashboard:

- giornata: l'ultima settimana giocata della stagione in corso. Risultati
  con la linea di chiusura del mercato (chi l'ha battuta, over o under),
  le sorprese più grandi rispetto alla linea e le migliori prestazioni
  individuali.
- prossima: il turno successivo, con data, linea e totale del mercato.
- indici: forza delle squadre calcolata dall'EPA (punti attesi aggiunti da
  ogni azione), corretta per la forza degli avversari, con le partite
  recenti che pesano di più; classifica dei quarterback per EPA a lancio.

Sono dati statistici e di mercato pubblici. Non contengono giocate né
segnalazioni di valore.

Fonte: nflverse (CC-BY-SA 4.0). Solo libreria standard.
"""

import csv
import gzip
import re

import nfl_racconto
import io
import math
from collections import defaultdict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REL = "https://github.com/nflverse/nflverse-data/releases/download"
PARTITE_URL = f"{REL}/schedules/games.csv"
SQUADRE_URL = f"{REL}/teams/teams_colors_logos.csv"
PBP_URL = REL + "/pbp/play_by_play_{s}.csv.gz"
GIOCATORI_URL = REL + "/stats_player/stats_player_week_{s}.csv"
UA = "Mozilla/5.0 (compatible; PureStats/1.0)"

EMIVITA_SETTIMANE = 16.0     # dopo 16 settimane una partita pesa la metà
PESO_STAGIONE_PRIMA = 0.9    # la stagione precedente conta quasi come la corrente
PRUDENZA = {"pass": 300.0, "rush": 600.0}   # azioni "fittizie" a forza zero: evita classifiche estreme
MIN_LANCI_QB = 100


def scarica(url, descrizione, tentativi=3):
    """Scarica un file; GitHub a volte risponde 504: si riprova. None se non disponibile."""
    import time
    for i in range(tentativi):
        print(f"  GET {url}")
        try:
            with urlopen(Request(url, headers={"User-Agent": UA}), timeout=180) as r:
                dati = r.read()
            if dati[:2] == b"\x1f\x8b":
                dati = gzip.decompress(dati)
            testo = dati.decode("utf-8", "replace")
            if testo.lstrip().startswith("<"):
                print(f"    risposta non valida (pagina HTML) — {descrizione}, riprovo")
            else:
                return testo
        except (HTTPError, URLError, TimeoutError) as e:
            print(f"    {e} — {descrizione}, tentativo {i + 1}")
        time.sleep(5 * (i + 1))
    print(f"    {descrizione}: non disponibile, il blocco resterà vuoto")
    return None


def f(x):
    try:
        return float(x) if x not in (None, "", "NA") else None
    except ValueError:
        return None


# ------------------------------------------------------------------ anagrafica
def anagrafica():
    """{sigla: nome, nome breve, conference, division, logo, colore}."""
    testo = scarica(SQUADRE_URL, "anagrafica squadre")
    if not testo:
        return {}
    out = {}
    for r in csv.DictReader(io.StringIO(testo)):
        sigla = (r.get("team_abbr") or "").strip()
        if sigla:
            out[sigla] = {
                "nomeCompleto": r.get("team_name") or sigla,
                "breve": r.get("team_nick") or sigla,
                "conference": r.get("team_conf") or None,
                "division": r.get("team_division") or None,
                "logo": r.get("team_logo_espn") or None,
                "colore": r.get("team_color") or None,
            }
    return out


# ------------------------------------------------------------------ partite con linee
def partite():
    testo = scarica(PARTITE_URL, "partite con linee di mercato")
    if not testo:
        return []
    out = []
    for r in csv.DictReader(io.StringIO(testo)):
        out.append({
            "stagione": int(r["season"]), "settimana": int(r["week"]), "tipo": r.get("game_type", ""),
            "data": r.get("gameday", ""), "ora": r.get("gametime", ""),
            "casa": r["home_team"], "ospite": r["away_team"],
            "pc": f(r.get("home_score")), "po": f(r.get("away_score")),
            # positivo = casa favorita (convenzione nflverse, verificata sui risultati)
            "linea": f(r.get("spread_line")), "totale": f(r.get("total_line")),
            "stadio": r.get("stadium", ""), "copertura": r.get("roof", ""),
        })
    return out


def _esito_linea(p):
    """Chi ha battuto la linea e se il totale è andato sopra o sotto."""
    if p["pc"] is None or p["linea"] is None:
        return None, None
    scarto = (p["pc"] - p["po"]) - p["linea"]
    chi = p["casa"] if scarto > 0 else p["ospite"] if scarto < 0 else None
    tot = None
    if p["totale"] is not None:
        t = p["pc"] + p["po"]
        tot = "over" if t > p["totale"] else "under" if t < p["totale"] else "pari"
    return chi, tot


def _riga(p, info):
    chi, tot = _esito_linea(p)
    fav = None
    if p["linea"] is not None and p["linea"] != 0:
        fav = p["casa"] if p["linea"] > 0 else p["ospite"]
    return {
        "data": p["data"], "ora": p["ora"], "casa": p["casa"], "ospite": p["ospite"],
        "pc": None if p["pc"] is None else int(p["pc"]), "po": None if p["po"] is None else int(p["po"]),
        "favorita": fav, "linea": None if p["linea"] is None else abs(p["linea"]),
        "totaleLinea": p["totale"], "battutaDa": chi, "totaleEsito": tot,
        "scartoLinea": None if p["pc"] is None or p["linea"] is None else round(abs((p["pc"] - p["po"]) - p["linea"]), 1),
        "stadio": p["stadio"],
    }


def giornata_e_prossima(tutte, info):
    if not tutte:
        return None, None
    stagione = max(p["stagione"] for p in tutte)
    st = [p for p in tutte if p["stagione"] == stagione]
    settimane = sorted({p["settimana"] for p in st})
    # una settimana è "giocata" appena si è disputata almeno una partita: la giornata in corso si
    # mostra subito, con le gare che mancano segnate come da giocare
    giocate = [w for w in settimane if any(p["pc"] is not None for p in st if p["settimana"] == w)]
    giorn = prossima = None
    if giocate:
        w = giocate[-1]
        gare = [_riga(p, info) for p in st if p["settimana"] == w]
        gare.sort(key=lambda g: (g["data"], g["ora"]))
        sorprese = sorted([g for g in gare if g["scartoLinea"] is not None], key=lambda g: -g["scartoLinea"])[:3]
        battute_fav = sum(1 for g in gare if g["battutaDa"] and g["battutaDa"] == g["favorita"])
        over = sum(1 for g in gare if g["totaleEsito"] == "over")
        giorn = {"stagione": stagione, "settimana": w, "partite": gare,
                 "sorprese": [{"casa": g["casa"], "ospite": g["ospite"], "scarto": g["scartoLinea"],
                               "battutaDa": g["battutaDa"]} for g in sorprese],
                 "completa": all(g["pc"] is not None for g in gare),
                 "riepilogo": {"partite": sum(1 for g in gare if g["pc"] is not None), "favoriteCoperte": battute_fav, "over": over,
                               "under": sum(1 for g in gare if g["totaleEsito"] == "under")}}
    future = [w for w in settimane if w not in giocate]
    if future:
        w = future[0]
        gare = sorted((_riga(p, info) for p in st if p["settimana"] == w), key=lambda g: (g["data"], g["ora"]))
        prossima = {"stagione": stagione, "settimana": w, "partite": gare}
    return giorn, prossima


# ------------------------------------------------------------------ migliori prestazioni
def prestazioni(stagione, settimana):
    testo = scarica(GIOCATORI_URL.format(s=stagione), f"giocatori {stagione}")
    if not testo:
        return {}
    righe = [r for r in csv.DictReader(io.StringIO(testo))
             if (r.get("week") or "") == str(settimana) and r.get("position") in ("QB", "RB", "WR", "TE")]
    def top(col, ruoli, extra, n=5):
        lista = []
        for r in righe:
            if r.get("position") not in ruoli:
                continue
            v = f(r.get(col)) or 0
            if v <= 0:
                continue
            lista.append({"nome": r.get("player_display_name") or r.get("player_name"), "ruolo": r.get("position"),
                          "squadra": r.get("team"), "avversario": r.get("opponent_team"), "valore": int(v),
                          "dettagli": " · ".join(f"{int(f(r.get(c)) or 0)} {lab}" for c, lab in extra if (f(r.get(c)) or 0) > 0)})
        return sorted(lista, key=lambda x: -x["valore"])[:n]
    return {
        "lanci": top("passing_yards", ("QB",), (("passing_tds", "TD"), ("passing_interceptions", "INT"))),
        "corse": top("rushing_yards", ("QB", "RB", "WR", "TE"), (("carries", "corse"), ("rushing_tds", "TD"))),
        "ricezioni": top("receiving_yards", ("RB", "WR", "TE"), (("receptions", "ricezioni"), ("receiving_tds", "TD"))),
    }


# ------------------------------------------------------------------ indici di forza (EPA)
MOMENTI_PER_PARTITA = 5


def _riassunto_pbp(stagione, settimana_momenti=None, momenti=None):
    """Per squadra e partita: azioni ed EPA in attacco e in difesa, passaggi e corse separati; EPA dei QB.
    Se `settimana_momenti` è indicata, raccoglie in `momenti` le azioni che hanno spostato di più la
    probabilità di vittoria in ogni partita di quella settimana (i momenti decisivi)."""
    testo = scarica(PBP_URL.format(s=stagione), f"azioni {stagione}")
    if not testo:
        return [], {}
    sq = {}
    qb = defaultdict(lambda: [0, 0.0, "", ""])
    for r in csv.DictReader(io.StringIO(testo)):
        if settimana_momenti is not None and momenti is not None and r.get("week") == str(settimana_momenti):
            wpa, hw, hwp = f(r.get("wpa")), f(r.get("home_wp")), f(r.get("home_wp_post"))
            desc = r.get("desc") or ""
            if (wpa is not None and hw is not None and hwp is not None and desc
                    and not any(x in desc for x in ("No Play", "Timeout", "kneels", "END QUARTER", "END GAME"))):
                # tolgo dal testo l'orario e le indicazioni di formazione, già mostrati o inutili
                desc = re.sub(r"^\(\d+:\d+\)\s*", "", desc)
                desc = re.sub(r"\((?:Shotgun|No Huddle|No Huddle, Shotgun|Pistol|Run formation)\)\s*", "", desc)
                testo, chi, _ = nfl_racconto.traduci(r["desc"])
                momenti[r["game_id"]].append({
                    "quarto": r.get("qtr"), "tempo": r.get("time"), "squadra": r.get("posteam"),
                    "descrizione": desc[:220], "testo": testo[:220], "chi": chi,
                    "yard": f(r.get("yards_gained")), "touchdown": r.get("touchdown") == "1",
                    "casaPrima": round(hw * 100), "casaDopo": round(hwp * 100), "peso": abs(hwp - hw)})
        if r.get("season_type") not in ("REG", "POST"):
            continue
        tipo = "pass" if r.get("pass") == "1" else "rush" if r.get("rush") == "1" else None
        epa = f(r.get("epa"))
        att, dif = r.get("posteam"), r.get("defteam")
        if not tipo or epa is None or not att or not dif:
            continue
        k = (r["game_id"], att)
        if k not in sq:
            sq[k] = {"settimana": int(r["week"]), "stagione": stagione, "att": att, "dif": dif,
                     "casa": r.get("home_team") == att, "pass": [0, 0.0], "rush": [0, 0.0]}
        sq[k][tipo][0] += 1
        sq[k][tipo][1] += epa
        if tipo == "pass" and r.get("passer_player_id"):
            q = qb[r["passer_player_id"]]
            q[0] += 1
            q[1] += epa
            q[2] = r.get("passer_player_name") or q[2]
            q[3] = att
    return list(sq.values()), qb


def _stima(lati, prudenza, giri=40):
    """Minimi quadrati pesati: epa = media + Att[a] - Dif[d]. Restituisce Att, Dif."""
    squadre = {x[0] for x in lati} | {x[1] for x in lati}
    A = dict.fromkeys(squadre, 0.0)
    D = dict.fromkeys(squadre, 0.0)
    mu = 0.0
    for _ in range(giri):
        num = den = 0.0
        for a, d, n, e, w in lati:
            num += n * w * (e / n - A[a] + D[d])
            den += n * w
        mu = num / den if den else 0.0
        na, da, nd, dd = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float)
        for a, d, n, e, w in lati:
            na[a] += n * w * (e / n - mu + D[d])
            da[a] += n * w
        for t in squadre:
            A[t] = na[t] / (da[t] + prudenza)
        for a, d, n, e, w in lati:
            nd[d] += n * w * -(e / n - mu - A[a])
            dd[d] += n * w
        for t in squadre:
            D[t] = nd[t] / (dd[t] + prudenza)
    return A, D


def indici(stagione, info, settimana_momenti=None, momenti=None):
    corrente, qb = _riassunto_pbp(stagione, settimana_momenti, momenti)
    if not corrente:
        return None
    precedente, _ = _riassunto_pbp(stagione - 1)
    ora = stagione * 30 + max(x["settimana"] for x in corrente) + 1
    lam = math.log(2) / EMIVITA_SETTIMANE
    lati = {"pass": [], "rush": []}
    quota_pass = defaultdict(lambda: [0, 0])
    for x in precedente + corrente:
        w = math.exp(-lam * (ora - (x["stagione"] * 30 + x["settimana"])))
        if x["stagione"] < stagione:
            w *= PESO_STAGIONE_PRIMA
        for tipo in ("pass", "rush"):
            n, e = x[tipo]
            if n:
                lati[tipo].append((x["att"], x["dif"], n, e, w))
        if x["stagione"] == stagione:
            quota_pass[x["att"]][0] += x["pass"][0]
            quota_pass[x["att"]][1] += x["pass"][0] + x["rush"][0]
    pa, pd = _stima(lati["pass"], PRUDENZA["pass"])
    ra, rd = _stima(lati["rush"], PRUDENZA["rush"])
    squadre = []
    for t in sorted(set(pa) | set(ra)):
        qp = quota_pass[t][0] / quota_pass[t][1] if quota_pass[t][1] else 0.58
        att = qp * pa.get(t, 0) + (1 - qp) * ra.get(t, 0)
        dif = 0.58 * pd.get(t, 0) + 0.42 * rd.get(t, 0)
        squadre.append({"squadra": t, "nome": (info.get(t) or {}).get("nomeCompleto", t),
                        "attacco": round(att, 3), "difesa": round(dif, 3), "netto": round(att + dif, 3),
                        "attPass": round(pa.get(t, 0), 3), "attCorsa": round(ra.get(t, 0), 3),
                        "difPass": round(pd.get(t, 0), 3), "difCorsa": round(rd.get(t, 0), 3)})
    squadre.sort(key=lambda s: -s["netto"])
    for i, s in enumerate(squadre, 1):
        s["posizione"] = i
    # punti a partita equivalenti: circa 125 azioni a partita per le due squadre insieme, ~62 a testa
    for s in squadre:
        s["puntiPartita"] = round(s["netto"] * 62, 1)
    qbs = [{"nome": v[2], "squadra": v[3], "lanci": v[0], "epaLancio": round(v[1] / v[0], 3)}
           for v in qb.values() if v[0] >= MIN_LANCI_QB]
    qbs.sort(key=lambda q: -q["epaLancio"])
    return {"stagione": stagione, "squadre": squadre, "quarterback": qbs[:32],
            "nota": "EPA = punti attesi aggiunti per azione. Forza corretta per gli avversari; "
                    "le partite recenti pesano di più e la stagione precedente conta un po' meno. "
                    "puntiPartita = margine indicativo contro una squadra media."}


def calcola(info=None):
    """Blocchi aggiuntivi per data_nfl.json. Ogni blocco può mancare senza invalidare gli altri."""
    info = info or anagrafica()
    tutte = partite()
    giorn, prossima = giornata_e_prossima(tutte, info)
    if giorn:
        giorn["prestazioni"] = prestazioni(giorn["stagione"], giorn["settimana"])
        for g in giorn["partite"]:
            if g["pc"] is not None:
                g["highlights"] = link_highlights((info.get(g["ospite"]) or {}).get("nomeCompleto", g["ospite"]),
                                                  (info.get(g["casa"]) or {}).get("nomeCompleto", g["casa"]),
                                                  g["data"])
    if prossima:
        try:
            duelli, giovani = anteprima(prossima, prossima["stagione"])
            prossima["duelli"] = duelli
            prossima["giovani"] = giovani
        except Exception as e:      # l'anteprima non deve mai bloccare il resto
            print(f"  Anteprima non calcolata: {type(e).__name__}: {e}")
    stagione = max((p["stagione"] for p in tutte if p["pc"] is not None), default=None)
    momenti = defaultdict(list)
    sett = giorn["settimana"] if giorn and giorn["stagione"] == stagione else None
    ind = indici(stagione, info, sett, momenti) if stagione else None
    if giorn and momenti:
        # abbinamento alla partita con la sigla nflverse del game_id: <stagione>_<settimana>_<ospite>_<casa>
        for g in giorn["partite"]:
            gid = f"{giorn['stagione']}_{int(giorn['settimana']):02d}_{g['ospite']}_{g['casa']}"
            scelti = sorted(momenti.get(gid, []), key=lambda m: -m["peso"])[:MOMENTI_PER_PARTITA]
            scelti.sort(key=lambda m: (int(m["quarto"] or 0), -_secondi(m["tempo"])))
            for m in scelti:
                m.pop("peso", None)
            if scelti:
                g["momenti"] = scelti
    # video dopo i momenti decisivi: servono per cercare le clip dei touchdown
    if giorn:
        try:
            video_ufficiali(giorn, info)
        except Exception as e:      # i video non devono mai bloccare il resto
            print(f"  Video non cercati: {type(e).__name__}: {e}")
    return {"anagrafica": info, "giornata": giorn, "prossima": prossima, "indici": ind}


# ------------------------------------------------------------------ highlights
MESI_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]


def _secondi(tempo):
    try:
        m, sec = (tempo or "0:0").split(":")
        return int(m) * 60 + int(sec)
    except ValueError:
        return 0


def link_highlights(ospite_nome, casa_nome, data_iso):
    """Ricerca su YouTube degli highlights ufficiali, con la data esatta della partita (i titoli dei video
    NFL la riportano in inglese, es. "November 8, 2026"): riduce i risultati di stagioni passate.
    È un link di ricerca, non un video preciso: per quello servirebbe la chiave gratuita di YouTube."""
    from urllib.parse import quote_plus
    try:
        a, me, g = (int(x) for x in data_iso.split("-"))
        quando = f"{MESI_EN[me - 1]} {g}, {a}"
    except (ValueError, AttributeError, IndexError):
        quando = data_iso or ""
    q = f"{ospite_nome} vs. {casa_nome} highlights {quando} NFL"
    return "https://www.youtube.com/results?search_query=" + quote_plus(q)


# ------------------------------------------------------------------ prossimo turno: duelli e giovani
PLAYERS_URL = f"{REL}/players/players.csv"
ETICHETTA_ANNO = {0: "Rookie", 1: "2° anno", 2: "3° anno"}


def _esperienza():
    """{gsis_id: stagione da rookie}."""
    testo = scarica(PLAYERS_URL, "anagrafica giocatori")
    if not testo:
        return {}
    out = {}
    for r in csv.DictReader(io.StringIO(testo)):
        rs = (r.get("rookie_season") or r.get("draft_year") or "").strip()
        if r.get("gsis_id") and rs.isdigit():
            out[r["gsis_id"]] = int(rs)
    return out


def _settimane(stagione):
    """Righe settimanali dei giocatori di una stagione (solo regular season e playoff)."""
    testo = scarica(GIOCATORI_URL.format(s=stagione), f"giocatori {stagione}")
    if not testo:
        return []
    return [r for r in csv.DictReader(io.StringIO(testo))
            if r.get("position") in ("QB", "RB", "WR", "TE") and r.get("season_type", "REG") in ("REG", "POST")]


def _misura(ruolo):
    return {"QB": ("passing_yards", "yard lanciate"), "RB": ("rushing_yards", "yard di corsa")}.get(
        ruolo, ("receiving_yards", "yard ricevute"))


def _profilo(pid, righe_correnti, righe_passate, rookie, stagione):
    """Rendimento del giocatore: stagione, ultime 3, stagioni precedenti, esperienza, forma."""
    cur = sorted((r for r in righe_correnti if r["player_id"] == pid), key=lambda r: int(r["week"]))
    if not cur:
        return None
    r0 = cur[-1]
    ruolo = r0["position"]
    col, cosa = _misura(ruolo)
    val = lambda rs: [f(r.get(col)) or 0 for r in rs]
    stag = val(cur)
    ult3 = val(cur[-3:])
    passate = val([r for r in righe_passate if r["player_id"] == pid])
    media = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    out = {"nome": r0.get("player_display_name") or r0.get("player_name"), "ruolo": ruolo, "squadra": r0.get("team"),
           "misura": cosa, "partite": len(cur), "mediaStagione": media(stag), "mediaUltime3": media(ult3),
           "mediaPassato": media(passate) if len(passate) >= 6 else None}
    if ruolo == "QB":
        att = sum(f(r.get("attempts")) or 0 for r in cur)
        epa = sum(f(r.get("passing_epa")) or 0 for r in cur)
        att3 = sum(f(r.get("attempts")) or 0 for r in cur[-3:])
        epa3 = sum(f(r.get("passing_epa")) or 0 for r in cur[-3:])
        attp = sum(f(r.get("attempts")) or 0 for r in righe_passate if r["player_id"] == pid)
        epap = sum(f(r.get("passing_epa")) or 0 for r in righe_passate if r["player_id"] == pid)
        out.update({"epaLancio": round(epa / att, 3) if att >= 30 else None,
                    "epaLancioUltime3": round(epa3 / att3, 3) if att3 >= 30 else None,
                    "epaLancioPassato": round(epap / attp, 3) if attp >= 150 else None,
                    "td": int(sum(f(r.get("passing_tds")) or 0 for r in cur)),
                    "int": int(sum(f(r.get("passing_interceptions")) or 0 for r in cur))})
    anni = stagione - rookie[pid] if pid in rookie else None
    out["esperienza"] = ETICHETTA_ANNO.get(anni) if anni is not None and anni <= 2 else (f"{anni + 1}° anno" if anni is not None else None)
    out["giovane"] = anni is not None and anni <= 2
    # forma: ultime 3 rispetto al riferimento (stagioni passate se ci sono, altrimenti la stagione in corso)
    rif = out["mediaPassato"] if out["mediaPassato"] is not None else out["mediaStagione"]
    forma = None
    if rif and out["mediaUltime3"] is not None and len(cur) >= 4:
        d = (out["mediaUltime3"] - rif) / max(rif, 1)
        forma = "in forma" if d >= 0.25 else "in calo" if d <= -0.25 else None
    out["forma"] = forma
    return out


def _chiave_squadra(righe, squadra):
    """Giocatori chiave nelle ultime 3 partite della squadra: QB con più lanci, RB con più corse,
    i 2 ricevitori con più bersagli."""
    sett = sorted({int(r["week"]) for r in righe if r.get("team") == squadra})[-3:]
    uso = defaultdict(float)
    ruoli = {}
    for r in righe:
        if r.get("team") != squadra or int(r["week"]) not in sett:
            continue
        p = r["position"]
        uso[r["player_id"]] += f(r.get("attempts") if p == "QB" else r.get("carries") if p == "RB" else r.get("targets")) or 0
        ruoli[r["player_id"]] = p
    scelta = []
    for ruolo, n in (("QB", 1), ("RB", 1)):
        scelta += sorted((p for p in uso if ruoli[p] == ruolo), key=lambda p: -uso[p])[:n]
    scelta += sorted((p for p in uso if ruoli[p] in ("WR", "TE")), key=lambda p: -uso[p])[:2]
    return scelta


def anteprima(prossima, stagione):
    """Per ogni partita del prossimo turno: confronto tra i giocatori chiave, con esperienza e forma.
    Più i giovani (rookie, 2° e 3° anno) che spiccano in tutta la lega."""
    if not prossima:
        return None, None
    rookie = _esperienza()
    correnti = _settimane(stagione)
    passate = []
    for s in (stagione - 1, stagione - 2):
        passate += _settimane(s)
    if not correnti:
        return None, None
    duelli = []
    for g in prossima["partite"]:
        lati = {}
        for lato in ("ospite", "casa"):
            ids = _chiave_squadra(correnti, g[lato])
            lati[lato] = [p for p in (_profilo(i, correnti, passate, rookie, stagione) for i in ids) if p]
        duelli.append({"casa": g["casa"], "ospite": g["ospite"], "data": g["data"], "ora": g["ora"],
                       "favorita": g["favorita"], "linea": g["linea"], "totaleLinea": g["totaleLinea"],
                       "giocatoriOspite": lati["ospite"], "giocatoriCasa": lati["casa"]})
    # giovani che spiccano
    per_giocatore = defaultdict(list)
    for r in correnti:
        per_giocatore[r["player_id"]].append(r)
    giovani = {"QB": [], "RB": [], "RIC": []}
    for pid, rs in per_giocatore.items():
        if pid not in rookie or stagione - rookie[pid] > 2 or len(rs) < 4:
            continue
        p = _profilo(pid, correnti, passate, rookie, stagione)
        if not p:
            continue
        if p["ruolo"] == "QB":
            if p.get("epaLancio") is not None and sum(f(r.get("attempts")) or 0 for r in rs) >= 100:
                giovani["QB"].append(p)
        else:
            giovani["RB" if p["ruolo"] == "RB" else "RIC"].append(p)
    giovani["QB"].sort(key=lambda p: -p["epaLancio"])
    giovani["RB"].sort(key=lambda p: -(p["mediaStagione"] or 0))
    giovani["RIC"].sort(key=lambda p: -(p["mediaStagione"] or 0))
    return duelli, {k: v[:5] for k, v in giovani.items()}


# ------------------------------------------------------------------ video ufficiali (YouTube)
import json as _json
import os as _os
from pathlib import Path as _Path

CANALE_NFL = "UCDVYQ4Zhbm3S2dlz7P1GBDg"      # canale YouTube ufficiale della NFL
ARCHIVIO_VIDEO = _Path(__file__).resolve().parent.parent / "data" / "nfl_video.json"
MAX_RICERCHE = 30                            # per tipo (partite e clip): al massimo 6.000 delle 10.000 unità giornaliere


def video_ufficiali(giornata, info):
    """Per ogni partita giocata, il video degli highlights sul canale ufficiale NFL.
    Una ricerca per partita, poi resta in archivio: le partite già trovate non costano più nulla.
    Senza chiave (secret YOUTUBE_API_KEY) non fa nulla e resta il link di ricerca."""
    chiave = _os.environ.get("YOUTUBE_API_KEY", "").strip()
    archivio = {}
    if ARCHIVIO_VIDEO.exists():
        try:
            archivio = _json.loads(ARCHIVIO_VIDEO.read_text(encoding="utf-8"))
        except _json.JSONDecodeError:
            archivio = {}
    fatte = 0
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from urllib.parse import urlencode
    adesso = _dt.now(_tz.utc)
    for g in giornata["partite"]:
        if g["pc"] is None:
            continue
        gid = f"{giornata['stagione']}_{int(giornata['settimana']):02d}_{g['ospite']}_{g['casa']}"
        voce = archivio.get(gid)
        if voce and voce.get("id"):
            g["video"] = voce
            continue
        if not chiave or fatte >= MAX_RICERCHE:
            continue
        # se una ricerca non ha trovato nulla si riprova dopo 6 ore (il video esce qualche ora dopo la partita)
        if voce and voce.get("cercato") and adesso - _dt.fromisoformat(voce["cercato"]) < _td(hours=6):
            continue
        osp = (info.get(g["ospite"]) or {}).get("breve") or g["ospite"]
        casa = (info.get(g["casa"]) or {}).get("breve") or g["casa"]
        params = {"part": "snippet", "channelId": CANALE_NFL, "type": "video", "maxResults": 5, "order": "relevance",
                  "q": f"{osp} vs. {casa} highlights", "publishedAfter": f"{g['data']}T00:00:00Z", "key": chiave}
        fatte += 1
        try:
            with urlopen(Request("https://www.googleapis.com/youtube/v3/search?" + urlencode(params),
                                 headers={"User-Agent": UA}), timeout=30) as r:
                risultati = _json.loads(r.read().decode()).get("items") or []
        except (HTTPError, URLError, TimeoutError) as e:
            print(f"  Video {gid}: ricerca non riuscita ({e}); resta il link di ricerca")
            continue
        scelto = None
        for it in risultati:
            titolo = (it.get("snippet") or {}).get("title") or ""
            t = titolo.lower()
            # deve nominare entrambe le squadre ed essere un video di highlights, non un'intervista
            if osp.lower() in t and casa.lower() in t and "highlight" in t:
                scelto = {"id": (it.get("id") or {}).get("videoId"), "titolo": titolo}
                break
        if scelto and scelto["id"]:
            archivio[gid] = scelto
            g["video"] = scelto
            print(f"  Video {gid}: {scelto['titolo']}")
        else:
            archivio[gid] = {"cercato": adesso.isoformat()}
            print(f"  Video {gid}: non ancora pubblicato o titolo non riconosciuto; riprovo più tardi")
    # clip delle singole giocate: solo touchdown, una ricerca per giocata, poi in archivio
    clip_fatte = 0
    for g in giornata["partite"]:
        gid = f"{giornata['stagione']}_{int(giornata['settimana']):02d}_{g['ospite']}_{g['casa']}"
        for m in g.get("momenti") or []:
            if not m.get("touchdown") or not m.get("chi"):
                continue
            chiave_m = f"{gid}|{m['quarto']}|{m['tempo']}"
            voce = archivio.get(chiave_m)
            if voce and voce.get("id"):
                m["clip"] = voce
                continue
            if not chiave or clip_fatte >= MAX_RICERCHE or (voce and voce.get("cercato")
                                                             and adesso - _dt.fromisoformat(voce["cercato"]) < _td(hours=12)):
                continue
            autore = m["chi"][-1]                     # chi segna: il ricevitore nei lanci, chi corre nelle corse
            yard = int(m["yard"]) if m.get("yard") is not None else None
            fine = (_dt.fromisoformat(g["data"]) + _td(days=4)).strftime("%Y-%m-%dT00:00:00Z")
            params = {"part": "snippet", "channelId": CANALE_NFL, "type": "video", "maxResults": 5,
                      "q": f"{autore} {yard}-yard touchdown" if yard else f"{autore} touchdown",
                      "publishedAfter": f"{g['data']}T00:00:00Z", "publishedBefore": fine, "key": chiave}
            clip_fatte += 1
            try:
                with urlopen(Request("https://www.googleapis.com/youtube/v3/search?" + urlencode(params),
                                     headers={"User-Agent": UA}), timeout=30) as r:
                    risultati = _json.loads(r.read().decode()).get("items") or []
            except (HTTPError, URLError, TimeoutError) as e:
                print(f"  Clip {chiave_m}: ricerca non riuscita ({e})")
                continue
            scelto = None
            for it in risultati:
                titolo = (it.get("snippet") or {}).get("title") or ""
                t = titolo.lower()
                # il titolo deve nominare chi ha segnato e le yard (o almeno "TD"/"touchdown"),
                # e non essere il video intero della partita
                if (autore.lower() in t and ("touchdown" in t or " td" in t)
                        and (yard is None or str(yard) in t) and "game highlights" not in t):
                    scelto = {"id": (it.get("id") or {}).get("videoId"), "titolo": titolo}
                    break
            if scelto and scelto["id"]:
                archivio[chiave_m] = scelto
                m["clip"] = scelto
                print(f"  Clip {chiave_m}: {scelto['titolo']}")
            else:
                archivio[chiave_m] = {"cercato": adesso.isoformat()}
                vicini = " | ".join(((it.get("snippet") or {}).get("title") or "")[:70] for it in risultati[:3])
                print(f"  Clip {chiave_m} ({params['q']}): nessuna corrispondenza. Primi risultati: {vicini or 'nessuno'}")
    if clip_fatte:
        print(f"  Ricerche clip dei touchdown: {clip_fatte}")

    ARCHIVIO_VIDEO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVIO_VIDEO.with_suffix(".tmp")
    tmp.write_text(_json.dumps(archivio, ensure_ascii=False, indent=0), encoding="utf-8")
    _os.replace(tmp, ARCHIVIO_VIDEO)
    if fatte:
        print(f"  Ricerche YouTube in questo aggiornamento: {fatte} (circa {fatte * 100} unità su 10.000 al giorno)")
