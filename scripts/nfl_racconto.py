"""
Traduce in italiano il testo delle azioni NFL (campo `desc` di nflverse).

Riconosce le azioni tipiche: lancio completo o incompleto, intercetto, sack,
corsa, scramble, field goal, punt, kickoff, fumble, touchdown, safety,
trasformazione da due punti. Se il testo ha una forma che le regole non
riconoscono, restituisce l'originale ripulito (senza numeri di maglia e
placcatori) invece di una traduzione sbagliata.

Restituisce anche chi è protagonista (per cercare la clip della giocata).
Solo libreria standard.
"""

import re

NOME = r"[A-Z][A-Za-z'.\-]*?\.?[A-Z][A-Za-z'\-]+(?:\s(?:Jr|Sr|II|III|IV)\.?)?"

DIREZIONE_LANCIO = {"left": "a sinistra", "middle": "al centro", "right": "a destra"}
DISTANZA = {"short": "corto", "deep": "lungo"}
CORSA = {
    "left end": "sull'esterno sinistro", "right end": "sull'esterno destro",
    "left tackle": "a sinistra", "right tackle": "a destra",
    "left guard": "a sinistra, in mezzo", "right guard": "a destra, in mezzo",
    "up the middle": "centralmente", "middle": "centralmente",
}


def _cognome(n):
    """'T.Lawrence' -> 'Lawrence'; 'Am.St. Brown' -> 'St. Brown'."""
    n = n.strip()
    parti = n.split(".", 1)
    if len(parti) == 2 and len(parti[0]) <= 3 and parti[1]:
        return parti[1].strip()
    return n


def _yard(testo):
    m = re.search(r"for (-?\d+) yards?", testo)
    if m:
        return int(m.group(1))
    if "for no gain" in testo:
        return 0
    return None


def _y(n):
    if n is None:
        return ""
    if n == 0:
        return "nessun guadagno"
    return f"{n} yard" if n > 0 else f"{n} yard (perdita)"


def pulisci(desc):
    d = desc or ""
    d = re.sub(r"^\(\s*\d*:\d+\)\s*", "", d)                               # orario
    d = re.sub(r"\((?:Shotgun|No Huddle|No Huddle, Shotgun|Pistol|Run formation|Punt formation|"
               r"Field Goal formation|Kick formation)\)\s*", "", d)
    d = re.sub(r"\b\d{1,2}-(?=[A-Z])", "", d)                                # numeri di maglia
    d = re.sub(r"[A-Z][A-Za-z.'\-]+ reported in as eligible\.\s*", "", d)    # cambi di ruolo
    d = re.sub(r"\s*\[[^\]]*\]", "", d)                                      # [pressione], [sack] ...
    d = re.sub(r"^Direct snap to [A-Z][A-Za-z.'\-]+\.\s*", "", d)
    d = re.sub(r"\s*The Replay Official reviewed.*$", "", d)                # revisioni al replay
    d = re.sub(r"\s*(?:Penalty|PENALTY) on .*?declined\.", "", d)          # penalità rifiutate
    return d.strip()


def traduci(desc):
    """(testo italiano, protagonisti, tradotto?)"""
    d = pulisci(desc)
    corpo = re.sub(r"\s*\([^)]*\)", "", d)                                   # placcatori tra parentesi
    td = "TOUCHDOWN" in d
    extra = []
    if re.search(r"FUMBLES", d):
        rec = re.search(r"RECOVERED by ([A-Z]{2,3})-(" + NOME + ")", d)
        extra.append("fumble" + (f", recuperato da {_cognome(rec.group(2))} ({rec.group(1)})" if rec else ""))
    if "SAFETY" in d:
        extra.append("safety")
    fine = (", " + ", ".join(extra) if extra else "") + (": touchdown" if td else "")

    prima = corpo.split(". ")[0]
    m = re.match(r"(" + NOME + r") pass (short|deep) (left|middle|right) to (" + NOME + r")", prima)
    if m and "INTERCEPTED" not in prima and "incomplete" not in prima:
        qb, rec = _cognome(m.group(1)), _cognome(m.group(4))
        y = _yard(corpo)
        testo = f"{qb} lancia {DISTANZA[m.group(2)]} {DIREZIONE_LANCIO[m.group(3)]} per {rec}"
        return (testo + (f", {_y(y)}" if y is not None else "") + fine, [qb, rec], True)

    m = re.match(r"(" + NOME + r") pass incomplete(?: (short|deep) (left|middle|right))?(?: to (" + NOME + r"))?", corpo)
    if m:
        qb = _cognome(m.group(1))
        dove = f" {DISTANZA[m.group(2)]} {DIREZIONE_LANCIO[m.group(3)]}" if m.group(2) else ""
        per = f" per {_cognome(m.group(4))}" if m.group(4) else ""
        return (f"{qb}: lancio{dove}{per} incompleto" + fine, [qb], True)

    m = re.match(r"(" + NOME + r") pass .*?INTERCEPTED by (" + NOME + r")", corpo)
    if m:
        qb, dif = _cognome(m.group(1)), _cognome(m.group(2))
        return (f"{qb} intercettato da {dif}" + fine, [qb, dif], True)

    m = re.match(r"(" + NOME + r") sacked", corpo)
    if m:
        qb = _cognome(m.group(1))
        y = _yard(corpo)
        return (f"{qb} subisce un sack" + (f", {_y(y)}" if y is not None else "") + fine, [qb], True)

    m = re.match(r"(" + NOME + r") scrambles (left end|right end|up the middle|left tackle|right tackle|left guard|right guard)", corpo)
    if m:
        qb = _cognome(m.group(1))
        y = _yard(corpo)
        return (f"{qb} esce dalla tasca e corre {CORSA.get(m.group(2), '')}" + (f", {_y(y)}" if y is not None else "") + fine,
                [qb], True)

    m = re.match(r"(" + NOME + r") (left end|right end|left tackle|right tackle|left guard|right guard|up the middle)", corpo)
    if m:
        rb = _cognome(m.group(1))
        y = _yard(corpo)
        return (f"{rb} corre {CORSA[m.group(2)]}" + (f", {_y(y)}" if y is not None else "") + fine, [rb], True)

    m = re.match(r"(" + NOME + r") (?:to [A-Z]{2,3} \d+|ran ob|pushed ob)", corpo)
    if m and _yard(corpo) is not None and " pass " not in corpo:
        rb = _cognome(m.group(1))
        return (f"{rb} corre, {_y(_yard(corpo))}" + fine, [rb], True)

    m = re.match(r"(" + NOME + r") extra point is (GOOD|No Good|Blocked|BLOCKED)", corpo)
    if m:
        esito = "riuscita" if m.group(2) == "GOOD" else "sbagliata"
        return (f"{_cognome(m.group(1))}: trasformazione da un punto {esito}", [], True)

    m = re.match(r"(" + NOME + r") (\d+) yard field goal is (GOOD|No Good|BLOCKED)", corpo)
    if m:
        k = _cognome(m.group(1))
        esito = {"GOOD": "riuscito", "No Good": "sbagliato", "BLOCKED": "bloccato"}[m.group(3)]
        return (f"{k}: field goal da {m.group(2)} yard {esito}", [k], True)

    m = re.match(r"(" + NOME + r") punts (\d+) yards", corpo)
    if m:
        return (f"{_cognome(m.group(1))} calcia un punt da {m.group(2)} yard" + fine, [_cognome(m.group(1))], True)

    m = re.match(r"(" + NOME + r") kicks (onside|\d+ yards)", corpo)
    if m:
        cosa = "un calcio corto (onside)" if m.group(2) == "onside" else "il kickoff"
        ritorno = re.search(r"\. (" + NOME + r") to [A-Z]{2,3} \d+ for (\d+) yards", corpo)
        testo = f"{_cognome(m.group(1))} batte {cosa}"
        if ritorno:
            testo += f", ritorno di {_cognome(ritorno.group(1))} per {ritorno.group(2)} yard"
        return (testo + fine, [_cognome(m.group(1))], True)

    if "TWO-POINT CONVERSION ATTEMPT" in corpo:
        esito = "riuscita" if "ATTEMPT SUCCEEDS" in corpo else "fallita"
        return (f"Trasformazione da due punti {esito}", [], True)

    # forma non riconosciuta: testo originale ripulito, senza tradurre a caso
    return (re.sub(r"\s+", " ", corpo).strip(), [], False)
