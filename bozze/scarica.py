import json, os, re, urllib.request, urllib.parse
UA={"User-Agent":"PureStats/1.0 (https://doubleuptip.github.io/purestats/; statistiche sportive)"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r: return r.read()
def pulisci(h): return re.sub(r"<[^>]+>","",h or "").strip()
def slug(t): return re.sub(r"[^A-Za-z0-9]+","_",t).strip("_")
os.makedirs("bozze/stadi",exist_ok=True); os.makedirs("bozze/wiki",exist_ok=True)
# 1) foto degli stadi: immagine principale della voce Wikipedia, solo se è su Commons (licenza libera)
STADI={"State Farm Stadium":"State Farm Stadium","Mercedes-Benz Stadium":"Mercedes-Benz Stadium","M&T Bank Stadium":"M&T Bank Stadium",
 "Highmark Stadium":"New Highmark Stadium","Bank of America Stadium":"Bank of America Stadium","Soldier Field":"Soldier Field",
 "Paycor Stadium":"Paycor Stadium","Huntington Bank Field":"Huntington Bank Field","AT&T Stadium":"AT&T Stadium",
 "Empower Field at Mile High":"Empower Field at Mile High","Ford Field":"Ford Field","Lambeau Field":"Lambeau Field",
 "Lucas Oil Stadium":"Lucas Oil Stadium","EverBank Stadium":"EverBank Stadium","GEHA Field at Arrowhead Stadium":"Arrowhead Stadium",
 "Allegiant Stadium":"Allegiant Stadium","SoFi Stadium":"SoFi Stadium","Hard Rock Stadium":"Hard Rock Stadium",
 "U.S. Bank Stadium":"U.S. Bank Stadium","Gillette Stadium":"Gillette Stadium","Caesars Superdome":"Caesars Superdome",
 "MetLife Stadium":"MetLife Stadium","Lincoln Financial Field":"Lincoln Financial Field","Acrisure Stadium":"Acrisure Stadium",
 "Levi's Stadium":"Levi's Stadium","Lumen Field":"Lumen Field","Raymond James Stadium":"Raymond James Stadium",
 "Nissan Stadium":"Nissan Stadium","Northwest Stadium":"Northwest Stadium","Estadio Banorte":"Estadio Azteca",
 "Memorial Stadium":"Memorial Stadium (Lincoln)","Neyland Stadium":"Neyland Stadium","Notre Dame Stadium":"Notre Dame Stadium"}
crediti={}
for nome, voce in STADI.items():
    try:
        q=urllib.parse.urlencode({"action":"query","titles":voce,"prop":"pageimages","piprop":"name","format":"json","redirects":1})
        pag=list(json.loads(get("https://en.wikipedia.org/w/api.php?"+q))["query"]["pages"].values())[0]
        file=pag["pageimage"]
        q=urllib.parse.urlencode({"action":"query","titles":"File:"+file,"prop":"imageinfo","iiprop":"url|extmetadata","iiurlwidth":1600,"format":"json"})
        ii=list(json.loads(get("https://commons.wikimedia.org/w/api.php?"+q))["query"]["pages"].values())[0]["imageinfo"][0]
        m=ii["extmetadata"]; f=slug(nome)+".jpg"
        open("bozze/stadi/"+f,"wb").write(get(ii.get("thumburl") or ii["url"]))
        crediti[f]={"stadio":nome,"file":file,"autore":pulisci(m.get("Artist",{}).get("value")),"licenza":m.get("LicenseShortName",{}).get("value"),"pagina":ii.get("descriptionurl")}
        print("ok",nome)
    except Exception as e: print("no",nome,e)
json.dump(crediti,open("bozze/stadi/crediti.json","w"),ensure_ascii=False,indent=1)
# 2) voci Wikipedia per le Leggende (testo wiki, licenza CC BY-SA: da citare)
VOCI=["List of NFL career passing yards leaders","List of NFL career passing touchdowns leaders",
 "List of NFL career rushing yards leaders","List of NFL career rushing touchdowns leaders",
 "List of NFL career receiving yards leaders","List of NFL career receptions leaders",
 "List of NFL career receiving touchdowns leaders","List of NFL career sacks leaders",
 "List of NFL career interceptions leaders","List of NFL head coaches with 100 wins",
 "National Football League 100th Anniversary All-Time Team","List of Super Bowl champions",
 "List of NFL tight end records","Kurt Warner","Joe Montana","Dan Marino","Tom Brady","1972 Miami Dolphins season",
 "Ice Bowl","Immaculate Reception","The Catch (American football)","Super Bowl LI","Helmet catch","Barry Sanders",
 "Jerry Rice","Lawrence Taylor","Hail Flutie","The Play (American football)","Kick Six","2007 Fiesta Bowl"]
for v in VOCI:
    try:
        q=urllib.parse.urlencode({"action":"parse","page":v,"prop":"wikitext","format":"json","redirects":1})
        d=json.loads(get("https://en.wikipedia.org/w/api.php?"+q))
        json.dump({"voce":v,"titolo":d["parse"]["title"],"wikitext":d["parse"]["wikitext"]["*"],
                   "url":"https://en.wikipedia.org/wiki/"+urllib.parse.quote(d["parse"]["title"].replace(" ","_"))},
                  open("bozze/wiki/"+slug(v)+".json","w"),ensure_ascii=False)
        print("voce ok",v)
    except Exception as e: print("voce no",v,e)
