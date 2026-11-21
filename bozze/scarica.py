import json, os, re, urllib.request, urllib.parse
UA={"User-Agent":"PureStats/1.0 (https://doubleuptip.github.io/purestats/; statistiche sportive)"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r: return r.read()
def pulisci(h): return re.sub(r"<[^>]+>","",h or "").strip()
def slug(t): return re.sub(r"[^A-Za-z0-9]+","_",t).strip("_")
os.makedirs("bozze/stadi",exist_ok=True); os.makedirs("bozze/wiki",exist_ok=True)
# Terza passata (21/11/2026): Nissan Stadium dalla ricerca su Commons
crediti={}
q=urllib.parse.urlencode({"action":"query","list":"search","srsearch":"Nissan Stadium Nashville filetype:bitmap","srnamespace":6,"srlimit":15,"format":"json"})
titoli=[r["title"][5:] for r in json.loads(get("https://commons.wikimedia.org/w/api.php?"+q))["query"]["search"]]
print("candidate",titoli)
for file in titoli:
    try:
        if not file.lower().endswith((".jpg",".jpeg")): continue
        q=urllib.parse.urlencode({"action":"query","titles":"File:"+file,"prop":"imageinfo","iiprop":"url|extmetadata|size","iiurlwidth":1600,"format":"json"})
        ii=list(json.loads(get("https://commons.wikimedia.org/w/api.php?"+q))["query"]["pages"].values())[0]["imageinfo"][0]
        if ii.get("width",0)<1200 or ii.get("width",0)<ii.get("height",0): continue
        m=ii["extmetadata"]; f="Nissan_Stadium.jpg"
        open("bozze/stadi/"+f,"wb").write(get(ii.get("thumburl") or ii["url"]))
        crediti[f]={"stadio":"Nissan Stadium","file":file,"autore":pulisci(m.get("Artist",{}).get("value")),"licenza":m.get("LicenseShortName",{}).get("value"),"pagina":ii.get("descriptionurl")}
        print("ok",file); break
    except Exception as e: print("no",file,repr(e))
json.dump(crediti,open("bozze/stadi/crediti2.json","w"),ensure_ascii=False,indent=1)
