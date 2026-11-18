import json, urllib.request, urllib.parse, os
UA={"User-Agent":"PureStats/1.0 (statistiche personali; contatto via GitHub doubleuptip)"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r: return r.read()
out={}
for titolo in ["M&T Bank Stadium", "SoFi Stadium"]:
    q=urllib.parse.urlencode({"action":"query","format":"json","prop":"pageimages","piprop":"name","titles":titolo})
    d=json.loads(get("https://en.wikipedia.org/w/api.php?"+q)); p=next(iter(d["query"]["pages"].values()))
    nome=p.get("pageimage"); 
    q=urllib.parse.urlencode({"action":"query","format":"json","prop":"imageinfo","iiprop":"url|extmetadata","iiurlwidth":1600,"titles":"File:"+nome})
    d=json.loads(get("https://commons.wikimedia.org/w/api.php?"+q)); p=next(iter(d["query"]["pages"].values()))
    ii=p["imageinfo"][0]; m=ii.get("extmetadata",{})
    f="bozze/"+titolo.replace(" ","_").replace("&","e")+".jpg"
    open(f,"wb").write(get(ii["thumburl"]))
    out[titolo]={"file":nome,"autore":m.get("Artist",{}).get("value"),"licenza":m.get("LicenseShortName",{}).get("value"),"url":ii.get("descriptionurl")}
json.dump(out,open("bozze/crediti.json","w"),indent=1,ensure_ascii=False); print(out)
