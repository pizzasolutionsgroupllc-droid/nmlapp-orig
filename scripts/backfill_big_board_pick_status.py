#!/usr/bin/env python3
"""
Backfill draft_prospects.nml_team_id / nml_round / nml_pick for picks that
were already submitted before the Big Board sync was wired into /api/draft/pick.

Walks every draft_selections row, finds the matching draft_prospects row using
the same tiered matcher used by the live endpoint (name → position → school →
birth_date), and UPDATEs the prospect so the Big Board lights up retroactively.

Usage:
    python3 scripts/backfill_big_board_pick_status.py [DB_PATH]

If DB_PATH is omitted, defaults to data/nml.db relative to the repo root.

Safe to re-run. Will not overwrite a prospect that already has the same
team/round/pick assigned. Will overwrite if the existing values disagree
(latest pick wins) — this lets the script self-heal mismatches.

NOTE: Like the production push workflow, never run this directly against
production while the live app is writing. Either (1) run against local
data/nml.db while the local Flask app is stopped, or (2) run against a
downloaded backup, then upload via the standard upload_merged.sh flow.
"""

import sqlite3
import sys
from pathlib import Path


def find_match(conn, player_row):
    """Tiered match: name (required) → position → school → birth_date.
    Returns target draft_prospects.id, or None if no name match found."""
    if not player_row:
        return None
    full_name = f"{(player_row['first_name'] or '').strip()} {(player_row['last_name'] or '').strip()}".strip()
    if not full_name:
        return None
    cands = conn.execute(
        "SELECT id, position, school, birth_date FROM draft_prospects "
        "WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))",
        (full_name,)
    ).fetchall()
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]['id']
    p_pos    = (player_row['position']   or '').strip().upper()
    p_school = (player_row['school']     or '').strip().lower()
    p_birth  = (player_row['birth_date'] or '').strip()
    best_id, best_score = None, -1
    for c in cands:
        score = 0
        c_pos    = (c['position']   or '').strip().upper()
        c_school = (c['school']     or '').strip().lower()
        c_birth  = (c['birth_date'] or '').strip()
        if p_pos    and c_pos    and p_pos    == c_pos:    score += 1000
        if p_school and c_school and p_school == c_school: score += 100
        if p_birth  and c_birth  and p_birth  == c_birth:  score += 10
        if score > best_score:
            best_score, best_id = score, c['id']
    return best_id


def main():
    repo_root = Path(__file__).resolve().parent.parent
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1]).resolve()
    else:
        db_path = repo_root / 'data' / 'nml.db'

    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}")
        sys.exit(1)

    print(f"Opening DB: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT ds.player_id,
               ds.team_id,
               dp.round,
               dp.round_order,
               dp.overall_order
          FROM draft_selections ds
          JOIN draft_picks dp ON dp.id = ds.draft_pick_id
         WHERE ds.player_id IS NOT NULL
         ORDER BY dp.overall_order ASC
    """).fetchall()

    total       = len(rows)
    matched     = 0
    no_match    = 0
    already_set = 0
    overwrote   = 0
    miss_log    = []

    for r in rows:
        player = conn.execute(
            "SELECT id, first_name, last_name, position, school, birth_date "
            "FROM players WHERE id=?",
            (r['player_id'],)
        ).fetchone()
        if not player:
            no_match += 1
            miss_log.append(f"  pick #{r['overall_order']}: player_id={r['player_id']} not in players table")
            continue

        target = find_match(conn, player)
        if target is None:
            no_match += 1
            miss_log.append(
                f"  pick #{r['overall_order']}: no draft_prospects match for "
                f"{player['first_name']} {player['last_name']} ({player['position']}, {player['school']})"
            )
            continue

        existing = conn.execute(
            "SELECT nml_team_id, nml_round, nml_pick FROM draft_prospects WHERE id=?",
            (target,)
        ).fetchone()

        new_vals = (r['team_id'], r['round'], r['round_order'])
        old_vals = (existing['nml_team_id'], existing['nml_round'], existing['nml_pick'])

        if old_vals == new_vals:
            already_set += 1
            continue

        if any(v is not None for v in old_vals):
            overwrote += 1

        conn.execute(
            "UPDATE draft_prospects SET nml_team_id=?, nml_round=?, nml_pick=? WHERE id=?",
            (*new_vals, target)
        )
        matched += 1

    conn.commit()
    conn.close()

    print()
    print(f"Total picks scanned       : {total}")
    print(f"Updated this run          : {matched}")
    print(f"  (of which overwrote old): {overwrote}")
    print(f"Already correct (no-op)   : {already_set}")
    print(f"No match found            : {no_match}")
    if miss_log:
        print()
        print("Misses (review and add to draft_prospects manually if needed):")
        for line in miss_log[:50]:
            print(line)
        if len(miss_log) > 50:
            print(f"  ... and {len(miss_log) - 50} more")


if __name__ == '__main__':
    main()
