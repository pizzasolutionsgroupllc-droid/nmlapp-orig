#!/usr/bin/env python3
"""
Scrape NFLMockDraftDatabase 2026 Consensus Big Board
Output: imports/prospects_consensus.json
  [{ "name", "position", "school", "consensus_rank" }, ...]
"""
import requests
from bs4 import BeautifulSoup
import json, time, sys, os

URLS = [
    "https://www.nflmockdraftdatabase.com/big-boards/2026/consensus-big-board-2026",
    "https://www.fantasypros.com/nfl/rankings/rookies.php",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

def fetch_url(url, session):
    r = session.get(url, headers=HEADERS, timeout=20, allow_redirects=True, max_redirects=10)
    r.raise_for_status()
    return r

def main():
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'imports')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'prospects_consensus.json')

    session = requests.Session()
    session.max_redirects = 10

    r = None
    for URL in URLS:
        try:
            print(f"Fetching: {URL}")
            r = fetch_url(URL, session)
            break
        except Exception as e:
            print(f"  Failed ({e}), trying next source...")
            r = None

    if r is None:
        print("All sources failed. Try running scrape_prospects_drafttek.py instead for rankings.")
        sys.exit(1)

    soup = BeautifulSoup(r.text, 'html.parser')

    prospects = []
    # NFLMockDraftDatabase uses a table with rows for each prospect
    rows = soup.select('table tbody tr, .big-board-row, .prospect-row')
    if not rows:
        # Fallback: try any table rows
        rows = soup.select('tr')

    rank = 0
    for row in rows:
        cells = row.find_all(['td', 'th'])
        if len(cells) < 2:
            continue
        text = [c.get_text(strip=True) for c in cells]

        # Try to find rank number in first cell
        try:
            r_num = int(text[0])
        except (ValueError, IndexError):
            continue

        rank = r_num
        # Name is usually 2nd cell, position 3rd, school 4th
        name = text[1] if len(text) > 1 else ''
        position = text[2] if len(text) > 2 else ''
        school = text[3] if len(text) > 3 else ''

        if name:
            prospects.append({
                'consensus_rank': rank,
                'name': name,
                'position': position,
                'school': school,
            })

    if not prospects:
        print("WARNING: No prospects found — site structure may have changed.")
        print("Saving raw HTML to imports/consensus_debug.html for inspection.")
        with open(os.path.join(out_dir, 'consensus_debug.html'), 'w') as f:
            f.write(r.text if hasattr(r, 'text') else '')
        sys.exit(1)

    with open(out_path, 'w') as f:
        json.dump(prospects, f, indent=2)
    print(f"✅ {len(prospects)} prospects saved to {out_path}")

if __name__ == '__main__':
    main()
