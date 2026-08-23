import json, os, sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = "https://v3.football.api-sports.io"
LEGHE = {135: "Serie A", 39: "Premier League", 61: "Ligue 1", 140: "LaLiga", 78: "Bundesliga"}

def chiama(endpoint, **params):
    chiave = os.environ.get("API_FOOTBALL_KEY")
    if not chiave:
        print("ERRORE: API_FOOTBALL_KEY non impostata")
        sys.exit(1)
    url = f"{BASE}/{endpoint}"
    if params:
        url += "?" + urlencode(params)
    try:
        with urlopen(Request(url, headers={"x-apisports-key": chiave}), timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode('utf-8')[:300]}")
        return None
    except URLError as e:
        print(f"  Rete: {e.reason}")
        return None

print("=" * 50)
print("[1] STATO ACCOUNT")
st = chiama("status")
if st:
    r = st.get("response") or {}
    sub = r.get("subscription") or {}
    req = r.get("requests") or {}
    print(f"  Piano:          {sub.get('plan')}")
    print(f"  Attivo:         {sub.get('active')}")
    print(f"  Richieste oggi: {req.get('current')} / {req.get('limit_day')}")
    if st.get("errors"):
        print(f"  ERRORI: {st['errors']}")
else:
    print("  Nessuna risposta")
    sys.exit(1)

print("\n[2] STAGIONI DISPONIBILI")
tutte = set()
comuni = None
for lid, nome in LEGHE.items():
    d = chiama("leagues", id=lid)
    if not d or d.get("errors"):
        print(f"  {nome}: {d.get('errors') if d else 'nessuna risposta'}")
        continue
    resp = d.get("response") or []
    if not resp:
        print(f"  {nome}: non accessibile")
        continue
    stagioni = resp[0].get("seasons") or []
    anni = sorted(s.get("year") for s in stagioni if s.get("year"))
    con_eventi = sorted(
        s.get("year") for s in stagioni
        if ((s.get("coverage") or {}).get("fixtures") or {}).get("events")
    )
    tutte.update(anni)
    comuni = set(anni) if comuni is None else comuni & set(anni)
    print(f"\n  {nome} (id {lid})")
    print(f"    Accessibili:     {anni or 'NESSUNA'}")
    print(f"    Con eventi:      {con_eventi or 'nessuna'}")

print("\n" + "=" * 50)
print("VERDETTO")
if not tutte:
    print("Nessuna stagione accessibile: piano insufficiente.")
else:
    c = sorted(comuni or [])
    print(f"Disponibili:  {sorted(tutte)}")
    print(f"Comuni a tutti: {c or 'nessuna'}")
    print(f"\n>>> Usa STAGIONE: '{max(c) if c else max(tutte)}'")
