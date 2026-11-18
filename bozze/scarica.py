import urllib.request
UA={"User-Agent":"PureStats/1.0 (statistiche personali)"}
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r: return r.read()
for nome,url in [("lac.png","https://a.espncdn.com/i/teamlogos/nfl/500/lac.png"),("bal.png","https://a.espncdn.com/i/teamlogos/nfl/500/bal.png"),
                 ("video.jpg","https://img.youtube.com/vi/iXTg27Lenug/maxresdefault.jpg")]:
    try: open("bozze/"+nome,"wb").write(get(url)); print("ok",nome)
    except Exception as e: print("no",nome,e)
