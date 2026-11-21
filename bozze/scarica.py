import json, os, re, urllib.request, urllib.parse
UA={"User-Agent":"PureStats/1.0 (https://doubleuptip.github.io/purestats/; statistiche sportive)"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r: return r.read()
def pulisci(h): return re.sub(r"<[^>]+>","",h or "").strip()
def slug(t): return re.sub(r"[^A-Za-z0-9]+","_",t).strip("_")
os.makedirs("bozze/stadi",exist_ok=True); os.makedirs("bozze/wiki",exist_ok=True)
# Seconda passata (21/11/2026): Nissan Stadium senza immagine principale -> prima foto jpg della voce;
# voci con titolo diverso trovate con la ricerca di Wikipedia
crediti={}
for nome, voce in {"Nissan Stadium":"Nissan Stadium"}.items():
    try:
        q=urllib.parse.urlencode({"action":"query","titles":voce,"prop":"images","imlimit":50,"format":"json","redirects":1})
        imm=[i["title"][5:] for i in list(json.loads(get("https://en.wikipedia.org/w/api.php?"+q))["query"]["pages"].values())[0]["images"]]
        imm=[f for f in imm if f.lower().endswith((".jpg",".jpeg")) and "nissan" in f.lower() or "lp field" in f.lower()] or [f for f in imm if f.lower().endswith((".jpg",".jpeg"))]
        print("candidate",imm[:6])
        file=imm[0]
        q=urllib.parse.urlencode({"action":"query","titles":"File:"+file,"prop":"imageinfo","iiprop":"url|extmetadata","iiurlwidth":1600,"format":"json"})
        ii=list(json.loads(get("https://commons.wikimedia.org/w/api.php?"+q))["query"]["pages"].values())[0]["imageinfo"][0]
        m=ii["extmetadata"]; f=slug(nome)+".jpg"
        open("bozze/stadi/"+f,"wb").write(get(ii.get("thumburl") or ii["url"]))
        crediti[f]={"stadio":nome,"file":file,"autore":pulisci(m.get("Artist",{}).get("value")),"licenza":m.get("LicenseShortName",{}).get("value"),"pagina":ii.get("descriptionurl")}
        print("ok",nome,file)
    except Exception as e: print("no",nome,repr(e))
json.dump(crediti,open("bozze/stadi/crediti2.json","w"),ensure_ascii=False,indent=1)
for cerca in ["NFL head coaches 100 wins list","Helmet Catch Tyree Super Bowl XLII","NFL tight end career records"]:
    try:
        q=urllib.parse.urlencode({"action":"query","list":"search","srsearch":cerca,"srlimit":3,"format":"json"})
        titoli=[r["title"] for r in json.loads(get("https://en.wikipedia.org/w/api.php?"+q))["query"]["search"]]
        print("ricerca",cerca,titoli)
        v=titoli[0]
        q=urllib.parse.urlencode({"action":"parse","page":v,"prop":"wikitext","format":"json","redirects":1})
        d=json.loads(get("https://en.wikipedia.org/w/api.php?"+q))
        json.dump({"voce":v,"titolo":d["parse"]["title"],"wikitext":d["parse"]["wikitext"]["*"],
                   "url":"https://en.wikipedia.org/wiki/"+urllib.parse.quote(d["parse"]["title"].replace(" ","_"))},
                  open("bozze/wiki/"+slug(v)+".json","w"),ensure_ascii=False)
        print("voce ok",v)
    except Exception as e: print("voce no",cerca,repr(e))
