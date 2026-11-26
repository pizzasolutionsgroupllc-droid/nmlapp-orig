#!/usr/bin/env python3
"""
Scrape Matt Harmon's 2026 WR rankings from receptionperception.com
Output: imports/prospects_harmon.json
  [{ "name", "position": "WR", "harmon_wr_rank" }, ...]
"""
import requests
from bs4 import BeautifulSoup
import json, re, os, sys

URL = "https://receptionperception.com/matt-harmons-nfl-draft-prospect-wr-rankings-2021-2025-stacked/"
FALLBACK = "https://receptionperception.com/category/rankings/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

def main():
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'imports')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'prospects_harmon.json')

    print(f"Fetching Matt Harmon WR rankings: {URL}")
    r = requests.get(URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')

    prospects = []
    rank = 0

    # Look for ordered or numbered lists, tables, or paragraphs with names
    # Harmon's site uses various formats — try multiple approaches

    # Approach 1: numbered list items
    for li in soup.find_all('li'):
        txt = li.get_text(strip=True)
        m = re.match(r'^(\d+)[.)]\s*(.+)$', txt)
        if m:
            r_num = int(m.group(1))
            name = re.sub(r'\s*\(.*?\)', '', m.group(2)).strip()  # Remove (School) etc.
            name = re.split(r'\s+-\s+', name)[0].strip()  # Remove - School suffix
            if name and r_num <= 200:
                prospects.append({'harmon_wr_rank': r_num, 'name': name, 'position': 'WR'})

    # Approach 2: table rows
    if not prospects:
        for row in soup.select('table tr'):
            cells = row.find_all(['td', 'th'])
            if len(cells) < 2:
                continue
            text = [c.get_text(strip=True) for c in cells]
            try:
                r_num = int(re.sub(r'[^\d]', '', text[0]))
            except Exception:
                continue
            name = text[1] if len(text) > 1 else ''
            name = re.sub(r'\s*\(.*?\)', '', name).strip()
            if name and r_num <= 200:
                prospects.append({'harmon_wr_rank': r_num, 'name': name, 'position': 'WR'})

    # Approach 3: look for numbered paragraphs
    if not prospects:
        for p_el in soup.find_all('p'):
            txt = p_el.get_text(strip=True)
            m = re.match(r'^(\d+)[.)]\s*([A-Z][a-z]+\s+[A-Z][a-z]+)', txt)
            if m:
                r_num = int(m.group(1))
                name = m.group(2).strip()
                if r_num <= 200:
                    prospects.append({'harmon_wr_rank': r_num, 'name': name, 'position': 'WR'})

    # Filter to only 2026 prospects (remove duplicates from stacked rankings)
    # The stacked page includes multiple years — filter by looking for 2026 section
    # If we can't distinguish, just take all and let the import script handle matching
    seen = set()
    unique = []
    for p in sorted(prospects, key=lambda x: x['harmon_wr_rank']):
        n = p['name'].lower().strip()
        if n not in seen:
            seen.add(n)
            unique.append(p)

    if not unique:
        print("WARNING: No prospects found. Saving debug HTML.")
        with open(os.path.join(out_dir, 'harmon_debug.html'), 'w') as f:
            f.write(r.text)
        print("Check imports/harmon_debug.html. You may need to paste Harmon's rankings manually.")
        print("Create imports/prospects_harmon.json manually with format:")
        print('[{"name": "Tetairoa McMillan", "position": "WR", "harmon_wr_rank": 1}, ...]')
        sys.exit(0)  # Non-fatal — Harmon data is supplementary

    with open(out_path, 'w') as f:
        json.dump(unique, f, indent=2)
    print(f"✅ {len(unique)} WR prospects saved to {out_path}")

if __name__ == '__main__':
    main()
