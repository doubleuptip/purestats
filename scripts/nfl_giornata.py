"""
Blocchi della sezione Giornata NFL calcolati dal play-by-play di nflverse (gratis, nessuna chiave):

- le 10 migliori giocate d'attacco e le 10 di difesa della settimana, ordinate per quanto hanno spostato la
  probabilità di vittoria (WPA) di chi le ha fatte; testo in italiano da nfl_racconto;
- le squadre della settimana: attacco e difesa in EPA per azione corretti per la forza dell'avversario
  (stesse stime degli indici), migliori attacchi, migliori difese e le 3 migliori squadre;
- i punti negli ultimi 2 minuti di ogni tempo (dopo il two-minute warning), fatti e subiti, stagione in corso;
- le flag: per squadra (commesse e subite, yard, tipi più frequenti) e per capo arbitro (colonna referee dei
  calendari nflverse).

Il file del play-by-play si legge una volta sola: `Raccolta.aggiungi` riceve ogni riga mentre nfl_indici la
scorre per i suoi conti. Solo libreria standard.
"""

from collections import Counter, defaultdict

import nfl_racconto

GIOCATE = 5
MIN_AZIONI_SETTIMANA = 35          # sotto, una partita (es. interrotta) non entra nelle squadre della settimana
FINESTRA = 120                     # secondi: il two-minute warning

TIPI_FLAG = {
    "Offensive Holding": "holding in attacco", "Defensive Holding": "holding in difesa",
    "False Start": "falsa partenza", "Defensive Pass Interference": "interferenza in difesa",
    "Offensive Pass Interference": "interferenza in attacco", "Delay of Game": "ritardo di gioco",
    "Unnecessary Roughness": "gioco violento", "Roughing the Passer": "fallo sul quarterback",
    "Defensive Offside": "fuorigioco in difesa", "Neutral Zone Infraction": "invasione della zona neutra",
    "Illegal Block Above the Waist": "blocco illegale", "Illegal Formation": "formazione illegale",
    "Face Mask": "maschera", "Encroachment": "invasione", "Illegal Contact": "contatto illegale",
    "Unsportsmanlike Conduct": "comportamento antisportivo", "Taunting": "provocazione",
    "Illegal Use of Hands": "uso illegale delle mani", "Intentional Grounding": "lancio a terra volontario",
    "Too Many Men on Field": "troppi uomini in campo", "Illegal Shift": "spostamento illegale",
    "Horse Collar Tackle": "placcaggio al colletto", "Ineligible Downfield Pass": "uomo non eleggibile avanti",
}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _uno(r, campo):
    return (r.get(campo) or "") in ("1", "1.0", "TRUE", "True")


class Raccolta:
    """Accumula, riga per riga, quello che serve ai blocchi della Giornata."""

    def __init__(self, stagione: int, settimana: int | None):
        self.stagione, self.settimana = stagione, settimana
        self.candidati = {"attacco": [], "difesa": []}
        self.epa = {}                                   # (game_id, squadra) -> [azioni, epa, avversario]
        self.punti_prima = {}                           # game_id -> (casa, ospite) punti alla riga precedente
        self.finestre = defaultdict(lambda: {"fatti1": 0, "subiti1": 0, "fatti2": 0, "subiti2": 0})
        self.flag = defaultdict(lambda: {"flag": 0, "yard": 0, "subite": 0, "tipi": Counter()})
        self.flag_partita = defaultdict(lambda: {"casa": 0, "ospite": 0, "yard": 0, "casaSq": "", "ospiteSq": ""})
        self.partite_squadra = defaultdict(set)
        self.epa_lega = [0, 0.0]                        # azioni ed EPA di tutta la stagione: media della lega

    # ------------------------------------------------------------------ riga per riga
    def aggiungi(self, r: dict) -> None:
        if r.get("season_type") not in ("REG", "POST"):
            return
        gid, casa, osp = r.get("game_id", ""), r.get("home_team", ""), r.get("away_team", "")
        if casa:
            self.partite_squadra[casa].add(gid)
            self.partite_squadra[osp].add(gid)
        if (_uno(r, "pass") or _uno(r, "rush")) and _f(r.get("epa")) is not None:
            self.epa_lega[0] += 1
            self.epa_lega[1] += _f(r.get("epa"))
        self._punti_finali_di_tempo(r, gid, casa, osp)
        self._flag(r, gid, casa, osp)
        if self.settimana is not None and r.get("week") == str(self.settimana):
            self._giocata(r)
            self._epa_settimana(r)

    def _punti_finali_di_tempo(self, r, gid, casa, osp):
        hc, ho = _f(r.get("total_home_score")), _f(r.get("total_away_score"))
        if hc is None or ho is None:
            return
        pc, po = self.punti_prima.get(gid, (0.0, 0.0))
        self.punti_prima[gid] = (hc, ho)
        dc, do = hc - pc, ho - po
        if dc <= 0 and do <= 0:
            return
        qtr, sec = r.get("qtr"), _f(r.get("half_seconds_remaining"))
        if sec is None or sec > FINESTRA or qtr not in ("2", "4"):
            return
        t = "1" if qtr == "2" else "2"
        if dc > 0:
            self.finestre[casa]["fatti" + t] += dc
            self.finestre[osp]["subiti" + t] += dc
        if do > 0:
            self.finestre[osp]["fatti" + t] += do
            self.finestre[casa]["subiti" + t] += do

    def _flag(self, r, gid, casa, osp):
        if not _uno(r, "penalty"):
            return
        desc = r.get("desc") or ""
        if "declined" in desc.lower():                  # rifiutata: nessun effetto sul gioco
            return
        sq = r.get("penalty_team") or ""
        if not sq:
            return
        yard = _f(r.get("penalty_yards")) or 0
        altra = osp if sq == casa else casa
        x = self.flag[sq]
        x["flag"] += 1
        x["yard"] += yard
        x["tipi"][r.get("penalty_type") or "altro"] += 1
        self.flag[altra]["subite"] += 1
        p = self.flag_partita[gid]
        p["casaSq"], p["ospiteSq"] = casa, osp
        p["casa" if sq == casa else "ospite"] += 1
        p["yard"] += yard

    def _giocata(self, r):
        wpa = _f(r.get("wpa"))
        att, dif = r.get("posteam") or "", r.get("defteam") or ""
        if wpa is None or not att or not dif or r.get("play_type") in ("no_play", "kickoff", "punt", "field_goal",
                                                                         "extra_point", "qb_kneel", "qb_spike", ""):
            return
        desc = r.get("desc") or ""
        if "Timeout" in desc or "END QUARTER" in desc:
            return
        difensiva = _uno(r, "sack") or _uno(r, "interception") or _uno(r, "fumble_lost") \
            or _uno(r, "fourth_down_failed") or _uno(r, "safety")
        if wpa > 0 and not difensiva:
            tipo, squadra, avv, valore = "attacco", att, dif, wpa
        elif wpa < 0 and difensiva:
            tipo, squadra, avv, valore = "difesa", dif, att, -wpa
        else:
            return
        hw, hwp = _f(r.get("home_wp")), _f(r.get("home_wp_post"))
        prima = dopo = None
        if hw is not None and hwp is not None:
            casa = r.get("home_team") == squadra
            prima, dopo = (hw, hwp) if casa else (1 - hw, 1 - hwp)
        testo, _chi, _ = nfl_racconto.traduci(desc)
        self.candidati[tipo].append({
            "squadra": squadra, "avversario": avv, "quarto": r.get("qtr"), "tempo": r.get("time"),
            "testo": (testo or desc)[:220], "yard": _f(r.get("yards_gained")),
            "touchdown": _uno(r, "touchdown") or _uno(r, "return_touchdown"),
            "evento": ("intercetto" if _uno(r, "interception") else "sack" if _uno(r, "sack")
                       else "fumble recuperato" if _uno(r, "fumble_lost") else "stop al quarto down"
                       if _uno(r, "fourth_down_failed") else "safety" if _uno(r, "safety") else ""),
            "valore": round(valore * 100, 1),
            "prima": None if prima is None else round(prima * 100), "dopo": None if dopo is None else round(dopo * 100),
            "partita": r.get("game_id")})

    def _epa_settimana(self, r):
        if not (_uno(r, "pass") or _uno(r, "rush")):
            return
        epa, att, dif = _f(r.get("epa")), r.get("posteam"), r.get("defteam")
        if epa is None or not att or not dif:
            return
        x = self.epa.setdefault((r["game_id"], att), [0, 0.0, dif])
        x[0] += 1
        x[1] += epa

    # ------------------------------------------------------------------ risultati
    def migliori_giocate(self) -> dict:
        out = {}
        for tipo, lista in self.candidati.items():
            scelte = sorted(lista, key=lambda g: -g["valore"])[:GIOCATE]
            out[tipo] = scelte
        return out

    def media_lega(self) -> float | None:
        return self.epa_lega[1] / self.epa_lega[0] if self.epa_lega[0] else None

    def squadre_settimana(self, squadre_indici: list, media_lega: float | None, nomi: dict) -> dict | None:
        """Attacco e difesa della settimana corretti per l'avversario con le stime degli indici:
        attacco = EPA/azione − (media − difesa avversaria); difesa = (media + attacco avversario) − EPA concesso."""
        if not self.epa or media_lega is None:
            return None
        forza = {s["squadra"]: s for s in squadre_indici or []}
        concesso = {}
        for (gid, att), (n, tot, dif) in self.epa.items():
            concesso[(gid, dif)] = (n, tot, att)
        righe = []
        for (gid, sq), (n, tot, avv) in self.epa.items():
            c = concesso.get((gid, sq))
            if n < MIN_AZIONI_SETTIMANA or not c or c[0] < MIN_AZIONI_SETTIMANA:
                continue
            fa, fd = forza.get(avv, {}), forza.get(avv, {})
            att = tot / n - (media_lega - (fd.get("difesa") or 0))
            dif = (media_lega + (fa.get("attacco") or 0)) - c[1] / c[0]
            righe.append({"squadra": sq, "nome": (nomi.get(sq) or {}).get("nomeCompleto", sq), "avversario": avv,
                          "attacco": round(att, 3), "difesa": round(dif, 3), "netto": round(att + dif, 3),
                          "epaAzione": round(tot / n, 3), "epaConcesso": round(c[1] / c[0], 3), "partita": gid})
        if not righe:
            return None
        return {"attacchi": sorted(righe, key=lambda x: -x["attacco"])[:5],
                "difese": sorted(righe, key=lambda x: -x["difesa"])[:5],
                "migliori": sorted(righe, key=lambda x: -x["netto"])[:3],
                "nota": "EPA per azione corretto per la forza dell'avversario (stesse stime degli indici): "
                        "+0,10 vuol dire circa 6 punti in più di una squadra media contro lo stesso avversario."}

    def ultimi_due_minuti(self, punti_stagione: dict, nomi: dict) -> dict | None:
        """punti_stagione = {squadra: [partite, punti fatti, punti subiti]} dalle partite finite."""
        righe = []
        for sq, x in self.finestre.items():
            n, pf, ps = punti_stagione.get(sq, [0, 0, 0])
            if not n:
                continue
            f1, f2, s1, s2 = x["fatti1"], x["fatti2"], x["subiti1"], x["subiti2"]
            righe.append({"squadra": sq, "nome": (nomi.get(sq) or {}).get("nomeCompleto", sq), "partite": n,
                          "fatti1": round(f1 / n, 2), "fatti2": round(f2 / n, 2),
                          "subiti1": round(s1 / n, 2), "subiti2": round(s2 / n, 2),
                          "quota": round((f1 + f2) / pf * 100, 1) if pf else None,
                          "netto": round((f1 + f2 - s1 - s2) / n, 2)})
        if not righe:
            return None
        n_tot = sum(r["partite"] for r in righe)
        media = {k: round(sum(r[k] * r["partite"] for r in righe) / n_tot, 2) for k in ("fatti1", "fatti2")}
        righe.sort(key=lambda r: -(r["fatti1"] + r["fatti2"]))
        return {"squadre": righe, "media": media,
                "nota": "Punti a partita segnati e subiti dopo il two-minute warning (ultimi 2 minuti) del primo e "
                        "del secondo tempo; quota = parte dei punti della squadra fatta in quei minuti. "
                        "Sono pochi minuti a partita: come segnale per giocare va ancora misurata."}

    def flag_squadre(self, nomi: dict) -> dict | None:
        righe = []
        for sq, x in self.flag.items():
            n = len(self.partite_squadra.get(sq, ()))
            if not n:
                continue
            righe.append({"squadra": sq, "nome": (nomi.get(sq) or {}).get("nomeCompleto", sq), "partite": n,
                          "flag": round(x["flag"] / n, 2), "yard": round(x["yard"] / n, 1),
                          "subite": round(x["subite"] / n, 2),
                          "tipi": [[TIPI_FLAG.get(t, t), c] for t, c in x["tipi"].most_common(3)]})
        if not righe:
            return None
        righe.sort(key=lambda r: -r["flag"])
        media = round(sum(r["flag"] * r["partite"] for r in righe) / sum(r["partite"] for r in righe), 2)
        return {"squadre": righe, "media": media,
                "nota": "Penalità accettate a partita (le rifiutate non contano). Se in un'azione ci sono più flag, "
                        "nflverse ne registra una sola."}

    def flag_arbitri(self, arbitri: dict) -> list | None:
        """arbitri = {game_id: capo arbitro} dai calendari nflverse."""
        per = defaultdict(lambda: [0, 0, 0, 0.0])          # partite, flag casa, flag ospite, yard
        vuota = {"casa": 0, "ospite": 0, "yard": 0}
        for gid in self.punti_prima:                       # tutte le partite lette, anche quelle senza flag
            a = arbitri.get(gid)
            if not a:
                continue
            p = self.flag_partita.get(gid, vuota)
            x = per[a]
            x[0] += 1
            x[1] += p["casa"]
            x[2] += p["ospite"]
            x[3] += p["yard"]
        righe = [{"arbitro": a, "partite": n, "flag": round((c + o) / n, 1), "casa": round(c / n, 1),
                  "ospite": round(o / n, 1), "yard": round(y / n, 1)}
                 for a, (n, c, o, y) in per.items() if n >= 2]
        righe.sort(key=lambda r: -r["flag"])
        return righe or None
