#!/usr/bin/env python3
"""
Populate `players.projected_ovr` for rookies whose Madden OVR isn't loaded yet.

Targets rows where:
  - players.overall_rating IS NULL
  - There's a matching draft_prospects row by name (case-insensitive)
  - The prospect has either nfl_overall or consensus_rank (otherwise we can't
    project meaningfully)

Idempotent — safe to re-run. Existing projected_ovr values are overwritten
with the latest computation.

Usage:
    cd /Users/j/Desktop/Claude/nmlapp
    python3 scripts/populate_projected_ovr.py                 # writes to data/nml.db
    python3 scripts/populate_projected_ovr.py --db PATH       # writes to a specific DB
    python3 scripts/populate_projected_ovr.py --dry-run       # show what would change

When real Madden ratings drop in September, the standard import workflow
overwrites overall_rating directly. The frontend prefers overall_rating over
projected_ovr, so the projection auto-deactivates without needing a script.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

from draft_review_engine import (  # noqa: E402
    project_rookie_ovr,
    nfl_round_from_overall,
    normalize_name,
)


def populate(db_path: str, dry_run: bool = False) -> None:
    print(f"DB: {db_path}")
    if dry_run:
        print("(dry run — no writes will be committed)\n")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Ensure column exists (idempotent migration).
    c.execute("PRAGMA table_info(players)")
    cols = {row[1] for row in c.fetchall()}
    if 'projected_ovr' not in cols:
        print("  Migrating: ADD COLUMN projected_ovr INTEGER")
        try:
            c.execute('ALTER TABLE players ADD COLUMN projected_ovr INTEGER')
            conn.commit()
        except sqlite3.OperationalError as e:
            print(f"  FATAL: could not add projected_ovr — {e}")
            sys.exit(2)

    # Build a normalized-name index of prospects with usable projection data.
    c.execute("""
        SELECT id, name, nfl_overall, consensus_rank
        FROM draft_prospects
        WHERE nfl_overall IS NOT NULL OR consensus_rank IS NOT NULL
    """)
    prospect_index = {}
    for pid, name, nfl_o, cons in c.fetchall():
        nname = normalize_name(name)
        if nname:
            prospect_index[nname] = (nfl_o, cons)

    # Find rookies (NULL overall_rating) and match via normalized name.
    c.execute("""
        SELECT id, first_name, last_name, position
        FROM players
        WHERE overall_rating IS NULL
    """)
    rookies = c.fetchall()

    candidates = []
    for pid, fn, ln, pos in rookies:
        full = f"{fn or ''} {ln or ''}".strip()
        nname = normalize_name(full)
        match = prospect_index.get(nname) if nname else None
        if match:
            nfl_o, cons = match
            candidates.append((pid, fn, ln, pos, nfl_o, cons))
    print(f"\nCandidates: {len(candidates)} rookies with NULL OVR + matched prospect data")

    updated = 0
    skipped = 0
    sample_rows = []
    for pid, fn, ln, pos, nfl_overall, cons_rank in candidates:
        nfl_round = nfl_round_from_overall(nfl_overall)
        proj = project_rookie_ovr(nfl_round, cons_rank)
        if proj is None:
            skipped += 1
            continue
        if not dry_run:
            c.execute("UPDATE players SET projected_ovr = ? WHERE id = ?", (proj, pid))
        updated += 1
        if len(sample_rows) < 8:
            slot_str = f"NFL #{nfl_overall}" if nfl_overall else "UDFA"
            cons_str = f"cons #{cons_rank}" if cons_rank else "no cons"
            sample_rows.append(
                f"  {fn} {ln} ({pos}, {slot_str}, {cons_str}) → projected {proj}"
            )

    if sample_rows:
        print("\nSample updates:")
        for r in sample_rows:
            print(r)
        if updated > len(sample_rows):
            print(f"  … plus {updated - len(sample_rows)} more")

    print(f"\nSummary:")
    print(f"  updated: {updated}")
    print(f"  skipped: {skipped}")

    if not dry_run:
        conn.commit()
        # Verify with a quick aggregate.
        c.execute("""
            SELECT COUNT(*) FROM players
            WHERE projected_ovr IS NOT NULL AND overall_rating IS NULL
        """)
        total_proj = c.fetchone()[0]
        print(f"\n  Total players with projected_ovr (and NULL real OVR): {total_proj}")
    conn.close()
    print("\n✅ Done.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(ROOT / 'data' / 'nml.db'))
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    populate(args.db, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
