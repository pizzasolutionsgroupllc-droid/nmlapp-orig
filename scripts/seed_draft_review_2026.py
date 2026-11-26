#!/usr/bin/env python3
"""
Seed the NMLBot draft review for 2026 into the database.

Idempotent: deletes any existing NMLBot review for the year (and its team
grades + picks via ON DELETE CASCADE), then re-creates fresh from current
engine output + prose data.

Usage:
    cd /Users/j/Desktop/Claude/nmlapp
    python3 scripts/seed_draft_review_2026.py                 # writes to data/nml.db
    python3 scripts/seed_draft_review_2026.py --db PATH       # writes to a specific DB
    python3 scripts/seed_draft_review_2026.py --dry-run       # show what would change, no writes

Future drafts: copy this file to seed_draft_review_2027.py, swap YEAR and
update the prose import. Or generalize to take year as a CLI flag.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'scripts'))

from draft_review_engine import compute_full_league_review  # noqa: E402
from draft_review_2026_prose import PROSE_2026  # noqa: E402

YEAR = 2026
NMLBOT_LABEL = 'NMLBot'


def seed(db_path: str, dry_run: bool = False) -> None:
    print(f"DB: {db_path}")
    if dry_run:
        print("(dry run — no writes will be committed)\n")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Pre-flight: ensure best_pick_text/worst_pick_text columns exist.
    # Inline ALTER TABLE so this works even if Flask hasn't been restarted.
    c.execute("PRAGMA table_info(draft_review_team_grades)")
    cols = {row[1] for row in c.fetchall()}
    for needed in ('best_pick_text', 'worst_pick_text'):
        if needed not in cols:
            print(f"  Migrating: ADD COLUMN {needed} TEXT")
            try:
                c.execute(f'ALTER TABLE draft_review_team_grades ADD COLUMN {needed} TEXT')
            except sqlite3.OperationalError as e:
                print(f"  FATAL: could not add {needed} — {e}")
                sys.exit(2)
    conn.commit()

    # Build team_short → team_id lookup.
    c.execute("SELECT id, short_name FROM teams")
    name_to_id = {sname: tid for tid, sname in c.fetchall()}

    # Compute engine output.
    print("Computing engine output...")
    reviews = compute_full_league_review(conn, YEAR)
    print(f"  {len(reviews)} teams in computed review\n")

    # Wipe any existing NMLBot review for the year (cascades to grades + picks).
    c.execute("""
        SELECT id FROM draft_reviews
        WHERE year = ? AND author_user_id IS NULL
    """, (YEAR,))
    existing = [row[0] for row in c.fetchall()]
    if existing:
        print(f"Wiping {len(existing)} existing NMLBot review(s) for {YEAR} (cascades to grades + picks)")
        if not dry_run:
            c.execute("""
                DELETE FROM draft_reviews
                WHERE year = ? AND author_user_id IS NULL
            """, (YEAR,))

    # Create the NMLBot review row.
    if not dry_run:
        c.execute("""
            INSERT INTO draft_reviews
                (year, author_user_id, author_label, is_published, published_at)
            VALUES (?, NULL, ?, 1, datetime('now'))
        """, (YEAR, NMLBOT_LABEL))
        review_id = c.lastrowid
    else:
        review_id = -1
    print(f"Created NMLBot review id={review_id}\n")

    # Process each team.
    teams_seeded = 0
    picks_seeded = 0
    missing_prose = []

    for r in reviews:
        team_short = r['short_name']
        prose = PROSE_2026.get(team_short)
        if prose is None:
            missing_prose.append(team_short)
            prose = {}

        if r.get('did_not_participate'):
            blurb = prose.get('summary', '')
            unfilled_json = json.dumps(r.get('unfilled_needs', []))
            if not dry_run:
                c.execute("""
                    INSERT INTO draft_review_team_grades (
                        review_id, team_id, league_rank,
                        value_grade, need_grade, talent_grade, final_grade,
                        blurb, best_pick_overall, worst_pick_overall,
                        best_pick_text, worst_pick_text,
                        looking_ahead, unfilled_needs
                    ) VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, ?)
                """, (review_id, r['team_id'], blurb, unfilled_json))
            teams_seeded += 1
            continue

        unfilled_json = json.dumps(r.get('unfilled_needs', []))
        if not dry_run:
            c.execute("""
                INSERT INTO draft_review_team_grades (
                    review_id, team_id, league_rank,
                    value_grade, need_grade, talent_grade, final_grade,
                    blurb, best_pick_overall, worst_pick_overall,
                    best_pick_text, worst_pick_text,
                    looking_ahead, unfilled_needs
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                review_id, r['team_id'], r['league_rank'],
                r['value_grade'], r['need_grade'], r['talent_grade'], r['final_grade'],
                prose.get('blurb', ''),
                r['best_pick_overall'], r['worst_pick_overall'],
                prose.get('best_pick_text', ''),
                prose.get('worst_pick_text', ''),
                prose.get('looking_ahead', ''),
                unfilled_json,
            ))
        teams_seeded += 1

        # Per-pick rows.
        for p in r['picks']:
            if not dry_run:
                c.execute("""
                    INSERT INTO draft_review_picks (
                        review_id, team_id, overall_pick, round, pick_in_round,
                        player_id, player_name, position,
                        nml_rank, nfl_consensus_rank, nfl_actual_slot,
                        value_delta, pick_grade, note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """, (
                    review_id, r['team_id'],
                    p['overall_pick'], p['round'], p.get('pick_in_round'),
                    p.get('player_id'), p.get('player_name'), p.get('position'),
                    p.get('nml_rank'), p.get('nfl_consensus_rank'), p.get('nfl_actual_slot'),
                    p.get('value_delta'),
                ))
            picks_seeded += 1

    if missing_prose:
        print(f"⚠ Missing prose for: {', '.join(missing_prose)}")
        print(f"  These teams were seeded with empty blurb/text — fix in PROSE_2026 dict and re-run.\n")

    print(f"Seeded:")
    print(f"  {teams_seeded} team grades (incl. DNP)")
    print(f"  {picks_seeded} pick rows")

    if not dry_run:
        conn.commit()
        # Verification round-trip.
        c.execute("SELECT COUNT(*) FROM draft_review_team_grades WHERE review_id = ?", (review_id,))
        grades_n = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM draft_review_picks WHERE review_id = ?", (review_id,))
        picks_n = c.fetchone()[0]
        c.execute("""
            SELECT COUNT(*) FROM draft_review_team_grades
            WHERE review_id = ? AND blurb IS NOT NULL AND blurb != ''
        """, (review_id,))
        with_prose = c.fetchone()[0]
        print(f"\nVerified in DB:")
        print(f"  team_grades rows: {grades_n}")
        print(f"  picks rows:       {picks_n}")
        print(f"  rows with blurb:  {with_prose}")
    conn.close()
    print("\n✅ Done.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(ROOT / 'data' / 'nml.db'),
                    help='SQLite DB path (default: data/nml.db)')
    ap.add_argument('--dry-run', action='store_true',
                    help='Show what would change, no writes')
    args = ap.parse_args()
    seed(args.db, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
