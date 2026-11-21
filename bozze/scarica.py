import urllib.request, os
UA={"User-Agent":"Mozilla/5.0 (compatible; PureStats/1.0; statistiche personali)","Accept-Language":"it-IT,it;q=0.9"}
os.makedirs("bozze/dazn",exist_ok=True)
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r: return r.status, r.read()
B="https://www.dazn.com/it-IT/news/"
for nome,url in [("robots.txt","https://www.dazn.com/robots.txt"),
                 ("elenco1.html",B+"competition/nfl-game-pass/wy3kluvb4efae1of0d8146c1"),
                 ("elenco2.html",B+"competition/nfl-game-pass/wy3kluvb4efae1of0d8146c1/2"),
                 ("elenco3.html",B+"competition/nfl-game-pass/wy3kluvb4efae1of0d8146c1/3"),
                 ("cinque11.html",B+"football-americano/nfl-messico-week-11-partite-da-non-perdere-game-pass-49ers-lions/gqercpnd38n1ita83rc8ip24"),
                 ("colts.html",B+"football-americano/colts-texans-nfl-diretta-week-11-notizie-orario-data-pronostico/en06i4t2ypfl1gchk5ytel6i7"),
                 ("week1.html",B+"football-americano/nfl-riparte-su-dazn-sfide-da-non-perdere-incluse-in-full-family-e-sports/1b3ymhjwzfy911vgyentqz2qe8"),
                 ("sitemap.xml","https://www.dazn.com/sitemap.xml")]:
    try: s,d=get(url); open("bozze/dazn/"+nome,"wb").write(d); print("ok",nome,s,len(d))
    except Exception as e: print("no",nome,e)
