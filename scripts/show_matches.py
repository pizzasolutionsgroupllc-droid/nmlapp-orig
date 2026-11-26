#!/usr/bin/env python3
"""Show name+pos+age matches and full FA insert list for review."""
import csv, sqlite3, unicodedata
from pathlib import Path

BASE     = Path(__file__).parent.parent
CSV_FILE = BASE / 'Players-2.csv'
DB       = BASE / 'data' / 'nml.db'

def norm(s):
    s = unicodedata.normalize('NFD', str(s or ''))
    out = ''
    for ch in s:
        if unicodedata.category(ch) != 'Mn':
            out += ch
    return ''.join(c for c in out.lower() if c.isalpha() or c == ' ').strip()

def int_or_none(v):
    try: return int(v) if v not in (None, '', 'None') else None
    except: return None

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row
all_players = conn.execute("SELECT id, first_name, last_name, position, age, madden_id, nml_team_id FROM players").fetchall()
teams = {t['id']: t['short_name'] for t in conn.execute("SELECT id, short_name FROM teams").fetchall()}

by_madden_id   = {}
by_name_pos_age = {}
for p in all_players:
    if p['madden_id']:
        by_madden_id[str(p['madden_id'])] = p
    key = (norm(p['first_name']), norm(p['last_name']), str(p['position'] or ''), str(p['age'] or ''))
    by_name_pos_age[key] = p

with open(CSV_FILE, newline='', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

tight_matches = []
new_fas       = []

for row in rows:
    roster_id = str(row.get('rosterId', '') or '').strip()
    fn  = norm(row.get('firstName', ''))
    ln  = norm(row.get('lastName', ''))
    pos = str(row.get('position', '') or '')
    age = str(int_or_none(row.get('age', '')) or '')
    ovr  = row.get('playerBestOvr', '?')
    name = f"{row.get('firstName')} {row.get('lastName')}"

    if roster_id and roster_id in by_madden_id:
        continue  # clean madden_id match — skip

    key = (fn, ln, pos, age)
    if key in by_name_pos_age:
        db_p     = by_name_pos_age[key]
        nml_team = teams.get(db_p['nml_team_id'], 'FA') if db_p['nml_team_id'] else 'FA'
        old_mid  = db_p['madden_id'] or 'none'
        tight_matches.append(
            f"  CSV: {name} ({pos}, OVR:{ovr})  ->  DB: {db_p['first_name']} {db_p['last_name']} | NML:{nml_team} | old_madden_id:{old_mid}"
        )
    else:
        new_fas.append(f"  {name} ({pos}, OVR:{ovr})")

conn.close()

print(f"=== NAME+POS+AGE MATCHES ({len(tight_matches)}) ===")
for t in tight_matches:
    print(t)

print(f"\n=== ALL NEW FA INSERTS ({len(new_fas)}) ===")
for fa in new_fas:
    print(fa)
