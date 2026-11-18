import json, urllib.request, urllib.parse, re
UA={"User-Agent":"PureStats/1.0 (https://doubleuptip.github.io/purestats/; statistiche sportive)"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r: return r.read()
def pulisci(h): return re.sub(r"<[^>]+>","",h or "").strip()
# loghi
for sq in ["was","nyg","ne","det","sf","dal","car","no"]:
    try: open(f"bozze/{sq}.png","wb").write(get(f"https://a.espncdn.com/i/teamlogos/nfl/500/{sq}.png")); print("ok",sq)
    except Exception as e: print("no",sq,e)
# anteprime video
for nome,vid in [("v_was_nyg","7UsUSgeGEqo"),("v_ne_det","u9ggzabBnEo"),("v_sf_dal","bqEz0JMZhOA"),("v_car_no","kpYlWvU7zjY")]:
    for q in ["maxresdefault","hqdefault"]:
        try: open(f"bozze/{nome}.jpg","wb").write(get(f"https://img.youtube.com/vi/{vid}/{q}.jpg")); print("ok",nome,q); break
        except Exception as e: print("no",nome,q,e)
# stadi da Wikipedia (immagine principale della voce) + crediti
crediti=json.load(open("bozze/crediti.json")) if __import__("os").path.exists("bozze/crediti.json") else {}
for voce in ["MetLife Stadium","Allianz Arena","AT&T Stadium","Caesars Superdome"]:
    try:
        q=urllib.parse.urlencode({"action":"query","titles":voce,"prop":"pageimages","piprop":"name","format":"json","redirects":1})
        pag=list(json.loads(get("https://en.wikipedia.org/w/api.php?"+q))["query"]["pages"].values())[0]
        file=pag["pageimage"]
        q=urllib.parse.urlencode({"action":"query","titles":"File:"+file,"prop":"imageinfo","iiprop":"url|extmetadata","iiurlwidth":1600,"format":"json"})
        ii=list(json.loads(get("https://commons.wikimedia.org/w/api.php?"+q))["query"]["pages"].values())[0]["imageinfo"][0]
        m=ii["extmetadata"]; nome=re.sub(r"[^A-Za-z0-9]+","_",voce)+".jpg"
        open("bozze/"+nome,"wb").write(get(ii.get("thumburl") or ii["url"]))
        crediti[nome]={"file":file,"autore":pulisci(m.get("Artist",{}).get("value")),"licenza":m.get("LicenseShortName",{}).get("value"),"pagina":ii.get("descriptionurl")}
        print("ok",voce,crediti[nome])
    except Exception as e: print("no",voce,e)
json.dump(crediti,open("bozze/crediti.json","w"),ensure_ascii=False,indent=1)
