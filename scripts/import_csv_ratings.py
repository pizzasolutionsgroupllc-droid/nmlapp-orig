#!/usr/bin/env python3
"""
import_csv_ratings.py
---------------------
Updates player ratings and info from a Madden franchise CSV export.
Also inserts unmatched CSV players as new free agents.

Matching order:
  1. madden_id (rosterId) — exact match only
  2. first_name + last_name + position + age — tight fallback for madden_id gaps

Updates ALL fields EXCEPT:
  nml_team_id, is_free_agent, on_trade_block, trade_block_note

Unmatched CSV players → inserted as free agents (is_free_agent=1, nml_team_id=NULL)

Usage:
  python3 import_csv_ratings.py              # dry run — shows stats, writes nothing
  python3 import_csv_ratings.py --apply      # writes to data/nml-ratings-work.db
"""

import sys
import csv
import shutil
import sqlite3
import unicodedata
import datetime
from pathlib import Path

BASE     = Path(__file__).parent.parent   # nmlapp root
SRC_DB   = BASE / 'data' / 'nml-backup-20260417-115213.db'
WORK_DB  = BASE / 'data' / 'nml-ratings-work.db'
CSV_FILE = BASE / 'Players-2.csv'

APPLY = '--apply' in sys.argv

# ── CSV column → DB column mapping ───────────────────────────────────────────
COL_MAP = {
    # Identity / bio
    'rosterId':                 'madden_id',
    'firstName':                'first_name',
    'lastName':                 'last_name',
    'position':                 'position',
    # age is NOT mapped — calculated dynamically from birth_date in the app
    'height':                   'height',
    'weight':                   'weight',
    'college':                  'college',
    'team':                     'nfl_team',
    'devTrait':                 'dev_trait',
    'jerseyNum':                'jersey_num',
    'rookieYear':               'rookie_year',
    'yearsPro':                 'years_pro',
    'draftRound':               'draft_round',
    'draftPick':                'draft_pick',
    # Contract
    'contractSalary':           'contract_salary',
    'contractLength':           'contract_length',
    'contractYearsLeft':        'contract_years_left',
    'contractBonus':            'contract_bonus',
    'capHit':                   'cap_hit',
    'capReleaseNetSavings':     'cap_release_savings',
    'capReleasePenalty':        'cap_release_penalty',
    # Overall
    'playerBestOvr':            'overall_rating',
    # General
    'speedRating':              'speed',
    'accelRating':              'acceleration',
    'agilityRating':            'agility',
    'changeOfDirectionRating':  'cod',
    'strengthRating':           'strength',
    'awareRating':              'awareness',
    'staminaRating':            'stamina',
    'injuryRating':             'injury',
    'toughRating':              'toughness',
    'jumpRating':               'jump',
    'confRating':               'confidence',
    # Ball carrier
    'carryRating':              'carry',
    'breakTackleRating':        'break_tackle',
    'jukeMoveRating':           'juke',
    'spinMoveRating':           'spin',
    'truckRating':              'truck',
    'stiffArmRating':           'stiff_arm',
    'bCVRating':                'bcv',
    'breakSackRating':          'break_sack',
    # Receiving
    'catchRating':              'catch',
    'cITRating':                'cit',
    'specCatchRating':          'spec_catch',
    'routeRunShortRating':      'route_short',
    'routeRunMedRating':        'route_med',
    'routeRunDeepRating':       'route_deep',
    'releaseRating':            'release',
    # Passing
    'throwPowerRating':         'throw_power',
    'throwAccRating':           'throw_acc',
    'throwAccShortRating':      'throw_acc_short',
    'throwAccMidRating':        'throw_acc_mid',
    'throwAccDeepRating':       'throw_acc_deep',
    'throwOnRunRating':         'throw_on_run',
    'throwUnderPressureRating': 'throw_under_pressure',
    'playActionRating':         'play_action',
    # Blocking
    'passBlockRating':          'pass_block',
    'passBlockPowerRating':     'pass_block_power',
    'passBlockFinesseRating':   'pass_block_finesse',
    'runBlockRating':           'run_block',
    'runBlockPowerRating':      'run_block_power',
    'runBlockFinesseRating':    'run_block_finesse',
    'impactBlockRating':        'impact_block',
    'leadBlockRating':          'lead_block',
    'longSnapRating':           'long_snap',
    # Defense
    'tackleRating':             'tackle',
    'hitPowerRating':           'hit_power',
    'pursuitRating':            'pursuit',
    'blockShedRating':          'block_shed',
    'powerMovesRating':         'power_moves',
    'finesseMovesRating':       'finesse_moves',
    'manCoverRating':           'man_cover',
    'zoneCoverRating':          'zone_cover',
    'pressRating':              'press',
    'playRecRating':            'play_rec',
    # Special teams
    'kickPowerRating':          'kick_power',
    'kickAccRating':            'kick_acc',
    'kickRetRating':            'kick_return',
}

# Fields never touched
NEVER_OVERWRITE = {'nml_team_id', 'is_free_agent', 'on_trade_block', 'trade_block_note'}

# String columns (everything else treated as integer)
STR_COLS = {'madden_id', 'first_name', 'last_name', 'position', 'nfl_team', 'college', 'school', 'birth_date'}

def norm(s):
    s = unicodedata.normalize('NFD', str(s or ''))
    result = ''
    for ch in s:
        if unicodedata.category(ch) != 'Mn':
            result += ch
    return ''.join(c for c in result.lower() if c.isalpha() or c == ' ').strip()

def int_or_none(v):
    try:
        return int(v) if v not in (None, '', 'None') else None
    except (ValueError, TypeError):
        return None

def build_birth_date(row):
    """Construct YYYY-MM-DD from birthYear/birthMonth/birthDay CSV fields, or None."""
    y = int_or_none(row.get('birthYear', ''))
    m = int_or_none(row.get('birthMonth', ''))
    d = int_or_none(row.get('birthDay', ''))
    if y and m and d:
        return f"{y:04d}-{m:02d}-{d:02d}"
    return None

def build_field_dict(row):
    """Build {db_col: value} from a CSV row, respecting NEVER_OVERWRITE."""
    updates = {}
    for csv_col, db_col in COL_MAP.items():
        if db_col in NEVER_OVERWRITE:
            continue
        val = row.get(csv_col, '')
        if val == '' or val is None:
            updates[db_col] = None
        elif db_col in STR_COLS:
            updates[db_col] = str(val).strip() or None
        else:
            updates[db_col] = int_or_none(val)
    # Construct birth_date from component fields
    updates['birth_date'] = build_birth_date(row)
    return updates

def main():
    if APPLY:
        shutil.copy2(SRC_DB, WORK_DB)
        print(f"Copied {SRC_DB.name} → {WORK_DB.name}")
        conn = sqlite3.connect(str(WORK_DB))
    else:
        print("=== DRY RUN (no changes written) ===")
        conn = sqlite3.connect(str(SRC_DB))

    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Build DB lookup tables
    c.execute("SELECT id, first_name, last_name, position, age, madden_id FROM players")
    all_players = c.fetchall()

    by_madden_id = {}
    by_name_pos_age = {}
    for p in all_players:
        if p['madden_id']:
            by_madden_id[str(p['madden_id'])] = p['id']
        # Tight fallback key: norm name + position + age
        tight_key = (norm(p['first_name']), norm(p['last_name']),
                     str(p['position'] or ''), str(p['age'] or ''))
        by_name_pos_age[tight_key] = p['id']

    # Read CSV
    with open(CSV_FILE, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    print(f"\nCSV rows: {len(rows)}")

    matched_id    = 0
    matched_tight = 0
    updated       = 0
    inserted      = 0
    unmatched     = []

    for row in rows:
        roster_id = str(row.get('rosterId', '') or row.get('id', '')).strip()
        fn  = norm(row.get('firstName', ''))
        ln  = norm(row.get('lastName', ''))
        pos = str(row.get('position', '') or '')
        age = str(int_or_none(row.get('age', '')) or '')

        db_id      = None
        match_type = None

        # 1. Match by madden_id
        if roster_id and roster_id in by_madden_id:
            db_id      = by_madden_id[roster_id]
            match_type = 'madden_id'
            matched_id += 1
        else:
            # 2. Tight fallback: name + position + age
            tight_key = (fn, ln, pos, age)
            if tight_key in by_name_pos_age:
                db_id      = by_name_pos_age[tight_key]
                match_type = 'tight_name'
                matched_tight += 1

        fields = build_field_dict(row)

        if db_id is not None:
            # UPDATE existing player
            set_clause = ', '.join(f'{k} = ?' for k in fields)
            vals = list(fields.values()) + [db_id]
            if APPLY:
                c.execute(
                    f"UPDATE players SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    vals
                )
            updated += 1

        else:
            # INSERT as new free agent
            unmatched.append(f"{row.get('firstName')} {row.get('lastName')} ({pos}, OVR:{row.get('playerBestOvr','?')}, {row.get('team')})")
            # Add FA-specific fields
            fields['is_free_agent'] = 1
            fields['nml_team_id']   = None
            cols   = ', '.join(fields.keys())
            placeholders = ', '.join('?' for _ in fields)
            vals = list(fields.values())
            if APPLY:
                c.execute(
                    f"INSERT INTO players ({cols}) VALUES ({placeholders})",
                    vals
                )
            inserted += 1

    # ── Report ────────────────────────────────────────────────────────────────
    print(f"\n{'APPLIED' if APPLY else 'DRY RUN'} RESULTS:")
    print(f"  Matched by madden_id      : {matched_id}")
    print(f"  Matched by name+pos+age   : {matched_tight}")
    print(f"  Total updated             : {updated}")
    print(f"  New FA inserts            : {inserted}")
    print(f"  Grand total rows touched  : {updated + inserted}")

    if unmatched:
        print(f"\nNew FA players being inserted (first 20 of {len(unmatched)}):")
        for u in unmatched[:20]:
            print(f"  + {u}")

    if APPLY:
        conn.commit()
        # Prompt for snapshot label
        snapshot_label = input("\nEnter a snapshot label for ratings history (e.g. 'M27 Week 3'), or press Enter to skip: ").strip()
        if snapshot_label:
            snapshot_date = datetime.date.today().isoformat()
            conn.execute('''
                INSERT INTO player_ratings_history
                    (player_id, overall_rating, speed, strength, awareness,
                     throw_power, throw_acc, catch, route_short, tackle,
                     block_shed, pass_block, man_cover, zone_cover,
                     snapshot_label, snapshot_date)
                SELECT id, overall_rating, speed, strength, awareness,
                       throw_power, throw_acc, catch, route_short, tackle,
                       block_shed, pass_block, man_cover, zone_cover,
                       ?, ?
                FROM players
                WHERE overall_rating IS NOT NULL
            ''', (snapshot_label, snapshot_date))
            conn.commit()
            snap_count = conn.execute('SELECT COUNT(*) FROM player_ratings_history WHERE snapshot_label=?', (snapshot_label,)).fetchone()[0]
            print(f"✅ Snapshot '{snapshot_label}' saved for {snap_count} players")
        print(f"\nDone. Work DB: {WORK_DB}")
        print("Next: start local server pointing at this DB and test before pushing to prod.")
    else:
        print("\nRun with --apply to write changes to data/nml-ratings-work.db")

    conn.close()

if __name__ == '__main__':
    main()
