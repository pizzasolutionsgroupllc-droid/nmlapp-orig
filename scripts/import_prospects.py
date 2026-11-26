#!/usr/bin/env python3
"""
Merge all scraped prospect JSON files into the draft_prospects DB table.
Run this after all scraper scripts have completed.

Files merged (in order):
  imports/prospects_consensus.json    → name, position, school, consensus_rank
  imports/prospects_measurables.json  → height, weight, forty_*, bench, vertical, broad, three_cone, shuttle
  imports/prospects_ras.json          → ras
  imports/prospects_drafttek.json     → drafttek_rank
  imports/prospects_espn.json         → espn_rank       (optional)
  imports/prospects_harmon.json       → harmon_wr_rank  (optional, WR only)
  imports/prospects_thorn.json        → thorn_ol_score  (optional, OL only)
  imports/prospects_brugler.json      → brugler_rank    (optional)

Usage:
    python3 scripts/import_prospects.py [--year 2026] [--clear]
    --year   Draft year (default: 2026)
    --clear  Delete existing prospects for this year before import
"""
import json, os, sys, sqlite3, re, unicodedata

YEAR = 2026
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'nml.db')
IMPORTS = os.path.join(os.path.dirname(__file__), '..', 'imports')

def norm(name):
    """Normalize player name for fuzzy matching."""
    if not name:
        return ''
    name = unicodedata.normalize('NFKD', str(name))
    name = name.encode('ascii', 'ignore').decode('ascii')
    name = re.sub(r'[^a-z ]', '', name.lower())
    name = re.sub(r'\s+', ' ', name).strip()
    # Remove suffixes
    name = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', name).strip()
    return name

def load_json(filename):
    path = os.path.join(IMPORTS, filename)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)

def build_index(data, key='name'):
    """Build {normalized_name: record} index."""
    idx = {}
    for rec in data:
        n = norm(rec.get(key, ''))
        if n:
            idx[n] = rec
    return idx

def main():
    year = YEAR
    clear = '--clear' in sys.argv
    for arg in sys.argv[1:]:
        if arg.startswith('--year='):
            year = int(arg.split('=')[1])
        elif arg == '--year' and sys.argv.index(arg) + 1 < len(sys.argv):
            year = int(sys.argv[sys.argv.index(arg) + 1])

    print(f"Importing prospects for year {year}")

    # Load all data sources
    consensus  = build_index(load_json('prospects_consensus.json'))
    measurable = build_index(load_json('prospects_measurables.json'))
    ras_data   = build_index(load_json('prospects_ras.json'))
    drafttek   = build_index(load_json('prospects_drafttek.json'))
    espn       = build_index(load_json('prospects_espn.json'))
    harmon     = build_index(load_json('prospects_harmon.json'))
    thorn      = build_index(load_json('prospects_thorn.json'))
    brugler    = build_index(load_json('prospects_brugler.json'))

    # Master list = consensus (most complete) + any extras from other sources
    all_names = set(consensus.keys())
    for idx in [measurable, ras_data, drafttek, espn, harmon, thorn, brugler]:
        all_names.update(idx.keys())

    print(f"Total unique prospects across all sources: {len(all_names)}")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    if clear:
        conn.execute('DELETE FROM draft_prospects WHERE year=?', (year,))
        print(f"Cleared existing {year} prospects")

    inserted = 0
    updated = 0

    for nname in all_names:
        c = consensus.get(nname, {})
        m = measurable.get(nname, {})
        ra = ras_data.get(nname, {})
        dt = drafttek.get(nname, {})
        ep = espn.get(nname, {})
        ha = harmon.get(nname, {})
        th = thorn.get(nname, {})
        br = brugler.get(nname, {})

        name      = c.get('name') or m.get('name') or ra.get('name') or dt.get('name') or nname
        position  = c.get('position') or m.get('position') or dt.get('position') or ''
        school    = c.get('school') or m.get('school') or dt.get('school') or ''

        row = {
            'year': year,
            'name': name,
            'position': position,
            'school': school,
            # measurables: prefer combine data, fall back to DraftTek height/weight
            'height': m.get('height') or dt.get('height'),
            'weight': m.get('weight') or dt.get('weight'),
            'forty_combine': m.get('forty_combine'),
            'forty_proday': m.get('forty_proday'),
            'bench': m.get('bench'),
            'vertical': m.get('vertical'),
            'broad': m.get('broad'),
            'three_cone': m.get('three_cone'),
            'shuttle': m.get('shuttle'),
            'ras': ra.get('ras'),
            'consensus_rank': c.get('consensus_rank'),
            'pff_rank': None,  # PFF populated separately
            'espn_rank': ep.get('espn_rank'),
            'drafttek_rank': dt.get('drafttek_rank'),
            'brugler_rank': br.get('brugler_rank'),
            'harmon_wr_rank': ha.get('harmon_wr_rank'),
            'thorn_ol_score': th.get('thorn_ol_score'),
        }

        # Check if exists
        existing = conn.execute(
            'SELECT id FROM draft_prospects WHERE year=? AND lower(trim(name))=lower(trim(?))',
            (year, name)
        ).fetchone()

        if existing:
            sets = ', '.join(f"{k}=?" for k in row if k not in ('year', 'name') and row[k] is not None)
            vals = [row[k] for k in row if k not in ('year', 'name') and row[k] is not None]
            if sets:
                conn.execute(
                    f"UPDATE draft_prospects SET {sets}, updated_at=datetime('now') WHERE id=?",
                    vals + [existing[0]]
                )
            updated += 1
        else:
            cols = ', '.join(row.keys())
            placeholders = ', '.join(['?'] * len(row))
            conn.execute(
                f'INSERT INTO draft_prospects ({cols}) VALUES ({placeholders})',
                list(row.values())
            )
            inserted += 1

    conn.commit()
    conn.close()
    print(f"\n✅ Done: {inserted} inserted, {updated} updated")
    print(f"Run the app and navigate to the Prospect Board to see your data.")

if __name__ == '__main__':
    main()
