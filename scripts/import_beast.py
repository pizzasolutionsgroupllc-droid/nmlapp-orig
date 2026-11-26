#!/usr/bin/env python3
"""
Import Dane Brugler's 'The Beast' 2026 NFL Draft Guide rankings into draft_prospects.

Adds two fields per prospect:
  brugler_rank  INTEGER  — overall Top 100 rank (NULL if outside Top 100)
  brugler_grade TEXT     — Brugler's round grade (e.g. '1st', '2nd-3rd', '4th-5th')

JSON source: imports/beast_rankings.json
Usage: python3 scripts/import_beast.py [--dry-run]
"""
import json, sqlite3, os, sys, re, unicodedata

DB_PATH  = os.path.join(os.path.dirname(__file__), '..', 'data', 'nml.db')
JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'imports', 'beast_rankings.json')

# Common nickname → full name mappings (for matching Beast full names to DB nicknames)
NICKNAMES = {
    'nicholas': 'nick', 'nathaniel': 'nate', 'michael': 'mike',
    'william': 'will', 'james': 'jimmy', 'robert': 'rob',
    'joseph': 'joe', 'christopher': 'chris', 'benjamin': 'ben',
    'kenneth': 'ken', 'kc': 'kevin',  # KC Concepcion → Kevin
}

def norm(name):
    if not name: return ''
    n = unicodedata.normalize('NFKD', str(name)).encode('ascii','ignore').decode('ascii')
    # Expand "J." prefix: "J.Michael" → "j michael" before stripping punctuation
    n = re.sub(r'\b([a-zA-Z])\.([a-zA-Z])', r'\1 \2', n)
    n = re.sub(r'[^a-z ]', '', n.lower())
    n = re.sub(r'\s+', ' ', n).strip()
    n = re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', n).strip()
    # Expand nicknames so Beast full names match DB short names
    parts = n.split()
    if parts and parts[0] in NICKNAMES:
        parts[0] = NICKNAMES[parts[0]]
    return ' '.join(parts)

def norm_school(s):
    return re.sub(r'[^a-z]', '', (s or '').lower())

def main():
    dry_run = '--dry-run' in sys.argv

    with open(JSON_PATH) as f:
        beast = json.load(f)
    print(f'Beast players: {len(beast)}')

    # Build lookup indexes
    by_name  = {}
    by_both  = {}
    for r in beast:
        nn = norm(r['name'])
        ns = norm_school(r.get('school', ''))
        if nn:
            by_name.setdefault(nn, r)
            by_both[(nn, ns)] = r

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    # Add brugler_grade column if missing
    existing = [row[1] for row in conn.execute("PRAGMA table_info(draft_prospects)").fetchall()]
    if 'brugler_grade' not in existing:
        conn.execute("ALTER TABLE draft_prospects ADD COLUMN brugler_grade TEXT")
        print("Added brugler_grade column")

    prospects = conn.execute(
        'SELECT id, name, school FROM draft_prospects WHERE year=2026'
    ).fetchall()
    print(f'DB prospects: {len(prospects)}')

    matched = 0
    no_match = 0
    unmatched = []

    for pid, pname, pschool in prospects:
        nn = norm(pname)
        ns = norm_school(pschool or '')
        rec = by_both.get((nn, ns)) or by_name.get(nn)

        if not rec:
            no_match += 1
            unmatched.append(pname)
            continue

        overall_rank = rec.get('overall_rank')  # None if not Top 100
        grade        = rec.get('grade') or None

        if dry_run:
            print(f'  {pname}: rank={overall_rank}, grade={grade}')
        else:
            conn.execute(
                "UPDATE draft_prospects SET brugler_rank=?, brugler_grade=?, updated_at=datetime('now') WHERE id=?",
                (overall_rank, grade, pid)
            )
        matched += 1

    if not dry_run:
        conn.commit()
    conn.close()

    print(f"\n{'[DRY RUN] Would update' if dry_run else 'Updated'}: {matched} prospects")
    print(f"No match: {no_match}")
    if unmatched:
        print(f"\nFirst 20 unmatched:")
        for n in unmatched[:20]:
            print(f"  {n}")

if __name__ == '__main__':
    main()
