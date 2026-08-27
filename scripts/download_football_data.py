"""Downloads free historical football (soccer) results + bookmaker odds CSVs
from football-data.co.uk into a local cache.

No account, no API key, no rate-limit token needed -- it's a plain static
file server intended for exactly this kind of public download. Files are
cached to disk and re-downloaded only if missing, so re-running this script
costs zero extra network calls once the cache is warm.

Column reference (why we pick these specific fields downstream):
  PSH/PSD/PSA   = Pinnacle closing... no wait, PSH/PSD/PSA is the *opening*
                  Pinnacle price; PSCH/PSCD/PSCA is the *closing* Pinnacle
                  price (the "C" suffix marks closing throughout this
                  dataset's column scheme, e.g. B365H vs B365CH).
  Pinnacle is used preferentially because it's the recognized sharp/reference
  book in the sports-betting literature (lowest average margin, first to
  move on new information) -- the closest football equivalent to "the
  market's real price" that Polymarket's CLOB gives us directly.
"""
import os
import time
import urllib.request
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO, "data", "football_data")

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"

LEAGUES = ["E0", "E1", "SC0", "D1", "I1", "SP1", "F1", "N1", "P1"]

# football-data.co.uk season codes: "2425" = 2024/25. Pinnacle closing-line
# columns (PSCH/PSCD/PSCA) only start appearing consistently from the
# 2012/13 season onward in most leagues, so that's where we start.
SEASONS = [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(2012, 2025)]


def download_all():
    os.makedirs(DATA_DIR, exist_ok=True)
    got, skipped, missing = 0, 0, 0
    for league in LEAGUES:
        for season in SEASONS:
            fn = f"{league}_{season}.csv"
            path = os.path.join(DATA_DIR, fn)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                skipped += 1
                continue
            url = BASE_URL.format(season=season, league=league)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = resp.read()
                if len(data) < 200:  # empty/placeholder page, not a real CSV
                    missing += 1
                    continue
                with open(path, "wb") as f:
                    f.write(data)
                got += 1
                if got % 20 == 0:
                    print(f"  downloaded {got} so far ...", flush=True)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    missing += 1
                else:
                    print(f"  {fn}: HTTP {e.code}")
            except Exception as e:
                print(f"  {fn}: {e}")
            time.sleep(0.15)  # be a polite, low-rate client against a static file host
    print(f"\ndownload_all: {got} new, {skipped} already cached, {missing} not published (delisted league/season)")


if __name__ == "__main__":
    download_all()
