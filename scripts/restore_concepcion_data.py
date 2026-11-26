#!/usr/bin/env python3
"""
One-time repair: restore missing consensus_rank + NFL slot data on KC Concepcion's
draft_prospect record. Earlier dedupe collapsed two records (KC + Kevin) and kept
the wrong field set. Source: backup from 2026-04-24 184459 (last backup before
the dedupe).

Idempotent — only updates fields that are NULL in the target record. Safe to
re-run.

Usage:
    cd /Users/j/Desktop/Claude/nmlapp
    python3 scripts/restore_concepcion_data.py                # writes to data/nml.db
    python3 scripts/restore_concepcion_data.py --db PATH      # writes to specific DB
    python3 scripts/restore_concepcion_data.py --dry-run      # show what would change
"""
import argparse
import sqlite3
import sys

# Data extracted from nml-backup-20260424-184459.db, draft_prospects record id=373
# (deleted "Kevin Concepcion" — same person as current "KC Concepcion" id=546).
RESTORE_FIELDS = {
    'consensus_rank': 24,
    'nfl_team':       'CLE',
    'nfl_round':      1,
    'nfl_pick':       24,
    'nfl_overall':    24,
}


def restore(db_path: str, dry_run: bool = False) -> None:
    print(f"DB: {db_path}")
    if dry_run:
        print("(dry run — no writes will be committed)\n")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Find the KC Concepcion target record.
    c.execute("SELECT * FROM draft_prospects WHERE LOWER(name)='kc concepcion'")
    row = c.fetchone()
    if not row:
        print("FATAL: no draft_prospect named 'KC Concepcion' found.")
        sys.exit(1)

    c.execute("PRAGMA table_info(draft_prospects)")
    cols = [col[1] for col in c.fetchall()]
    current = {cols[i]: row[i] for i in range(len(cols))}
    pid = current['id']

    print(f"Target prospect_id={pid}: {current['name']}")
    print(f"  Current values for fields we'll restore:")
    sets, args = [], []
    for k, v in RESTORE_FIELDS.items():
        cur = current.get(k)
        flag = '(empty — will set)' if cur in (None, '') else f'(already set to {cur!r} — skipping)'
        print(f"    {k:18s} → {v!r}  {flag}")
        if cur in (None, ''):
            sets.append(f'{k}=?')
            args.append(v)

    if not sets:
        print("\nNothing to restore — all target fields already have values.")
        conn.close()
        return

    print(f"\nWill update {len(sets)} field(s).")
    if not dry_run:
        sets.append("updated_at=datetime('now')")
        args.append(pid)
        c.execute(f"UPDATE draft_prospects SET {', '.join(sets)} WHERE id=?", args)
        conn.commit()

        # Verify.
        c.execute("SELECT consensus_rank, nfl_overall, nfl_round, nfl_pick, nfl_team FROM draft_prospects WHERE id=?", (pid,))
        verify = c.fetchone()
        print(f"\n✓ Verified: consensus_rank={verify[0]}, nfl_overall={verify[1]}, "
              f"nfl_round={verify[2]}, nfl_pick={verify[3]}, nfl_team={verify[4]!r}")

    conn.close()
    print("\n✅ Done.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/nml.db')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    restore(args.db, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
