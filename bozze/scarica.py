import urllib.request, os
UA={"User-Agent":"Mozilla/5.0 (compatible; PureStats/1.0; statistiche personali)"}
os.makedirs("bozze/espn",exist_ok=True)
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r: return r.status, r.read()
for nome,url in [("rankings.json","https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings"),
                 ("fpi_fitt.json","https://site.web.api.espn.com/apis/fitt/v3/sports/football/college-football/powerindex?region=us&lang=en&season=2026&limit=200"),
                 ("fpi_core.json","https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/seasons/2026/powerindex?limit=200"),
                 ("dazn_robots.txt","https://www.dazn.com/robots.txt")]:
    try: s,d=get(url); open("bozze/espn/"+nome,"wb").write(d); print("ok",nome,s,len(d))
    except Exception as e: print("no",nome,e)
