#!/usr/bin/env python3
"""
Live NFL Draft tracker — scrapes Wikipedia 2026 NFL Draft page.
Run this during the draft to get real-time picks.
Output: imports/nfl_draft_2026_live.json

Usage:
    python3 scripts/scrape_nfl_draft_live.py          # scrape and save
    python3 scripts/scrape_nfl_draft_live.py --import  # scrape + import to DB
"""
import requests
from bs4 import BeautifulSoup
import json, re, os, sys, sqlite3

WIKI_URL = "https://en.wikipedia.org/wiki/2026_NFL_draft"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'nml.db')

def fetch_picks():
    print(f"Fetching: {WIKI_URL}")
    r = requests.get(WIKI_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')

    picks = []
    current_round = 0

    for table in soup.find_all('table', class_='wikitable'):
        # Detect round from preceding heading
        prev = table.find_previous(['h2', 'h3'])
        if prev:
            txt = prev.get_text(strip=True)
            m = re.search(r'Round\s*(\d+)', txt, re.I)
            if m:
                current_round = int(m.group(1))

        headers = []
        for th in table.find_all('th'):
            headers.append(th.get_text(strip=True).lower())

        # Map header positions
        col = {}
        for i, h in enumerate(headers):
            if 'pick' in h and 'overall' not in h and 'round' not in h:
                col.setdefault('pick', i)
            if 'overall' in h:
                col['overall'] = i
            if 'team' in h or 'club' in h:
                col.setdefault('team', i)
            if 'player' in h or 'name' in h:
                col.setdefault('player', i)
            if 'pos' in h:
                col.setdefault('position', i)
            if 'school' in h or 'college' in h or 'source' in h:
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

            # Try to parse overall pick number
            overall_str = get('overall') or get('pick', '')
            try:
                overall = int(re.sub(r'[^\d]', '', overall_str))
            except Exception:
                continue

            pick_in_round_str = get('pick', '')
            try:
                pick_in_round = int(re.sub(r'[^\d]', '', pick_in_round_str))
            except Exception:
                pick_in_round = None

            player = get('player')
            team = get('team')
            position = get('position')
            school = get('school')

            # Skip header rows or empty
            if not player or player.lower() in ('player', 'name', ''):
                continue

            picks.append({
                'year': 2026,
                'round': current_round,
                'pick': pick_in_round,
                'overall': overall,
                'nfl_team': team,
                'player_name': player,
                'position': position,
                'school': school,
            })

    return picks

def import_to_db(picks):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    inserted = 0
    updated = 0
    for p in picks:
        existing = conn.execute(
            'SELECT id FROM nfl_draft_history WHERE year=? AND overall=?',
            (p['year'], p['overall'])
        ).fetchone()
        if existing:
            conn.execute('''
                UPDATE nfl_draft_history
                SET round=?, pick=?, nfl_team=?, player_name=?, position=?, school=?
                WHERE year=? AND overall=?
            ''', (p['round'], p['pick'], p['nfl_team'], p['player_name'],
                  p['position'], p['school'], p['year'], p['overall']))
            updated += 1
        else:
            conn.execute('''
                INSERT INTO nfl_draft_history (year, round, pick, overall, nfl_team, player_name, position, school)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (p['year'], p['round'], p['pick'], p['overall'],
                  p['nfl_team'], p['player_name'], p['position'], p['school']))
            inserted += 1

        # Also update draft_prospects table if this player is in it
        conn.execute('''
            UPDATE draft_prospects
            SET nfl_team=?, nfl_round=?, nfl_pick=?, nfl_overall=?, updated_at=datetime('now')
            WHERE year=2026 AND lower(trim(name))=lower(trim(?))
        ''', (p['nfl_team'], p['round'], p['pick'], p['overall'], p['player_name']))

    conn.commit()
    conn.close()
    print(f"✅ DB updated: {inserted} inserted, {updated} updated")

def main():
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'imports')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'nfl_draft_2026_live.json')

    picks = fetch_picks()
    print(f"Found {len(picks)} picks so far")

    with open(out_path, 'w') as f:
        json.dump(picks, f, indent=2)
    print(f"Saved to {out_path}")

    if '--import' in sys.argv:
        print("Importing to DB...")
        import_to_db(picks)

if __name__ == '__main__':
    main()
