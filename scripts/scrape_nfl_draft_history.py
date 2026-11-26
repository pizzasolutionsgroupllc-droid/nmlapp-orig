#!/usr/bin/env python3
"""
Scrape historical NFL Draft results (2006-2025) from Wikipedia.
Output: imports/nfl_draft_history.json
Then imports directly to DB.

Usage:
    python3 scripts/scrape_nfl_draft_history.py
"""
import requests
from bs4 import BeautifulSoup
import json, re, os, sys, sqlite3, time

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'nml.db')
YEARS = list(range(2006, 2026))  # 20 years

def fetch_year(year):
    url = f"https://en.wikipedia.org/wiki/{year}_NFL_draft"
    print(f"  Fetching {year}: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"    ERROR: {e}")
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    picks = []
    current_round = 0

    for table in soup.find_all('table', class_='wikitable'):
        prev = table.find_previous(['h2', 'h3'])
        if prev:
            txt = prev.get_text(strip=True)
            m = re.search(r'Round\s*(\d+)', txt, re.I)
            if m:
                current_round = int(m.group(1))

        headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
        col = {}
        for i, h in enumerate(headers):
            if 'overall' in h:
                col['overall'] = i
            if 'pick' in h and 'overall' not in h:
                col.setdefault('pick', i)
            if 'team' in h or 'club' in h:
                col.setdefault('team', i)
            if 'player' in h or 'name' in h:
                col.setdefault('player', i)
            if 'pos' in h:
                col.setdefault('position', i)
            if 'school' in h or 'college' in h:
                col.setdefault('school', i)

        for row in table.find_all('tr')[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 3:
                continue
            text = [c.get_text(strip=True) for c in cells]

            def get(key, default=''):
                idx = col.get(key)
                if idx is None or idx >= len(text):
                    return default
                return text[idx]

            overall_str = get('overall') or get('pick', '')
            try:
                overall = int(re.sub(r'[^\d]', '', overall_str))
            except Exception:
                continue

            pick_str = get('pick', '')
            try:
                pick = int(re.sub(r'[^\d]', '', pick_str))
            except Exception:
                pick = None

            player = get('player')
            team = get('team')
            position = get('position')
            school = get('school')

            if not player or player.lower() in ('player', 'name', ''):
                continue

            picks.append({
                'year': year,
                'round': current_round,
                'pick': pick,
                'overall': overall,
                'nfl_team': team,
                'player_name': player,
                'position': position,
                'school': school,
            })

    return picks

def main():
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'imports')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'nfl_draft_history.json')

    all_picks = []
    for year in YEARS:
        picks = fetch_year(year)
        print(f"    → {len(picks)} picks")
        all_picks.extend(picks)
        time.sleep(0.5)

    print(f"\nTotal: {len(all_picks)} picks across {len(YEARS)} years")

    with open(out_path, 'w') as f:
        json.dump(all_picks, f, indent=2)
    print(f"Saved to {out_path}")

    print("Importing to DB...")
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    inserted = 0
    for p in all_picks:
        try:
            conn.execute('''
                INSERT OR IGNORE INTO nfl_draft_history
                    (year, round, pick, overall, nfl_team, player_name, position, school)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (p['year'], p['round'], p['pick'], p['overall'],
                  p['nfl_team'], p['player_name'], p['position'], p['school']))
            inserted += 1
        except Exception as e:
            print(f"  DB error: {e}")
    conn.commit()
    conn.close()
    print(f"✅ {inserted} rows imported to nfl_draft_history table")

if __name__ == '__main__':
    main()
