"""Downloads free historical tennis results + bookmaker odds from
tennis-data.co.uk into a local cache. Same publisher/format family as
football-data.co.uk (see download_football_data.py): plain static file
server, one file per season, no account or API key.

ATP files: {year}/{year}.xls(x)  (2000-2012 are .xls, 2013+ are .xlsx)
WTA files: {year}w/{year}.xlsx   (WTA coverage starts 2007)
"""
import os
import time
import urllib.request
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO, "data", "tennis_data")

ATP_YEARS = list(range(2000, 2026))
WTA_YEARS = list(range(2007, 2026))


def _url_and_ext(year: int, tour: str) -> tuple[str, str]:
    ext = "xls" if (tour == "ATP" and year < 2013) else "xlsx"
    path = f"{year}/{year}.{ext}" if tour == "ATP" else f"{year}w/{year}.{ext}"
    return f"http://www.tennis-data.co.uk/{path}", ext


def download_all():
    os.makedirs(DATA_DIR, exist_ok=True)
    got, skipped, missing = 0, 0, 0
    for tour, years in (("ATP", ATP_YEARS), ("WTA", WTA_YEARS)):
        for year in years:
            url, ext = _url_and_ext(year, tour)
            fn = f"{tour}_{year}.{ext}"
            path = os.path.join(DATA_DIR, fn)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                skipped += 1
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = resp.read()
                if len(data) < 500:
                    missing += 1
                    continue
                with open(path, "wb") as f:
                    f.write(data)
                got += 1
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    missing += 1
                else:
                    print(f"  {fn}: HTTP {e.code}")
            except Exception as e:
                print(f"  {fn}: {e}")
            time.sleep(0.15)
    print(f"download_all: {got} new, {skipped} already cached, {missing} not published")


if __name__ == "__main__":
    download_all()
