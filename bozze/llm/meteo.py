"""Aggiunge il meteo all'ora d'inizio (Open-Meteo, gratis, senza chiave) per gli stadi all'aperto."""
import json, os, urllib.request, urllib.parse
QUI = os.path.dirname(os.path.abspath(__file__))
f = os.path.join(QUI, "materiale.json")
dati = json.load(open(f))
for gid, v in dati.items():
    m = v["anteprima"]
    c = m.get("coordinateStadio")
    if not c or m.get("coperturaStadio") != "all'aperto":
        continue
    giorno, ora = m["inizioUtc"].split("T")
    q = urllib.parse.urlencode({"latitude": c[0], "longitude": c[1], "start_date": giorno, "end_date": giorno, "timezone": "UTC",
                                "hourly": "temperature_2m,precipitation,wind_speed_10m,wind_gusts_10m,weather_code"})
    try:
        with urllib.request.urlopen("https://archive-api.open-meteo.com/v1/archive?" + q, timeout=30) as r:
            h = json.loads(r.read())["hourly"]
        i = h["time"].index(f"{giorno}T{ora[:2]}:00")
        meteo = {"temperaturaC": round(h["temperature_2m"][i]), "ventoKmh": round(h["wind_speed_10m"][i]),
                 "raffiche": round(h["wind_gusts_10m"][i]), "pioggiaMm": h["precipitation"][i],
                 "nota": "dati all'ora d'inizio; citare il meteo solo se conta (freddo, vento forte, pioggia)"}
        for t in ("anteprima", "cronaca"):
            v[t]["meteo"] = meteo
        print("meteo", gid, meteo)
    except Exception as e:
        print("meteo non disponibile per", gid, e)
json.dump(dati, open(f, "w"), ensure_ascii=False, indent=1)
