#!/usr/bin/env python3
"""
apply_schema_to_prod.py — Safe schema migration for production DB.

Usage:
    python3 scripts/apply_schema_to_prod.py data/nml-backup-TIMESTAMP.db

What it does:
  1. Copies the prod backup → data/nml-merged.db
  2. Runs init_db() against it — adds all new tables (CREATE TABLE IF NOT EXISTS)
     and new columns (ALTER TABLE, skips if already exists). Zero data loss.
  3. Seeds data for non-transactional tables that are empty in the backup
     but need data to function (dc_slot_eligibility, draft_pick_chart,
     draft_prospects, nfl_draft_history).

What it NEVER touches:
  trades, trade_assets, trade_tokens, transactions,
  players (ownership/ratings), draft_picks (ownership),
  teams, users, team_needs, sessions, trusted_devices,
  audit_log, depth_chart, watchlist, power_rankings, league_settings

Upload the result with:
    bash upload_merged.sh
"""

import sys
import os
import shutil
import sqlite3

# ── Argument check ────────────────────────────────────────────────────────────
if len(sys.argv) < 2:
    print("Usage: python3 scripts/apply_schema_to_prod.py data/nml-backup-TIMESTAMP.db")
    sys.exit(1)

src = sys.argv[1]
if not os.path.exists(src):
    print(f"ERROR: source file not found: {src}")
    sys.exit(1)

# Always work from the nmlapp root
script_dir = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(script_dir)
merged = os.path.join(root, 'data', 'nml-merged.db')
local  = os.path.join(root, 'data', 'nml.db')

# ── Step 1: Copy prod backup → nml-merged.db ─────────────────────────────────
print(f"[1] Copying {src} → {merged}")
shutil.copy2(src, merged)

# ── Step 2: Run init_db() against merged ─────────────────────────────────────
print("[2] Applying schema migrations (CREATE TABLE IF NOT EXISTS + ALTER TABLE)…")

# Temporarily point the backend at nml-merged.db
os.environ['DB_PATH'] = merged

# Add backend to path
sys.path.insert(0, os.path.join(root, 'backend'))
from database import init_db
init_db()
print("    Schema migrations complete.")

# ── Step 3: Seed non-transactional tables if empty in prod ───────────────────
print("[3] Checking non-transactional tables for seed data…")

# Tables where we copy ALL rows from local if the prod table is empty.
# These are purely configuration/scouting data — no transactional value.
SEED_IF_EMPTY = [
    'dc_slot_eligibility',    # depth chart position rules (config)
    'draft_pick_chart',       # pick value chart for trade grader (config)
    'draft_prospects',        # NFL scouting data (non-transactional)
    'nfl_draft_history',      # historical NFL draft results (non-transactional)
    'power_ranking_settings', # power ranking weights (config)
    'trade_grade_settings',   # trade grade weights (config)
]

merged_conn = sqlite3.connect(merged)
local_conn  = sqlite3.connect(local)

for tbl in SEED_IF_EMPTY:
    # Check if table exists in merged
    exists = merged_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
    ).fetchone()
    if not exists:
        print(f"    SKIP {tbl}: table doesn't exist in merged (schema issue?)")
        continue

    prod_count  = merged_conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
    local_count = local_conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]

    if prod_count > 0:
        print(f"    SKIP {tbl}: already has {prod_count} rows in prod — not touching")
        continue

    if local_count == 0:
        print(f"    SKIP {tbl}: empty in local too, nothing to copy")
        continue

    # Only use columns that exist in BOTH local and merged (handles schema drift)
    local_cols  = [d[0] for d in local_conn.execute(f'SELECT * FROM "{tbl}" LIMIT 0').description]
    merged_cols = [d[0] for d in merged_conn.execute(f'SELECT * FROM "{tbl}" LIMIT 0').description]
    common_cols = [c for c in local_cols if c in set(merged_cols)]

    col_list     = ','.join(f'"{c}"' for c in common_cols)
    placeholders = ','.join(['?'] * len(common_cols))
    idx          = [local_cols.index(c) for c in common_cols]

    rows = local_conn.execute(f'SELECT * FROM "{tbl}"').fetchall()
    trimmed = [tuple(r[i] for i in idx) for r in rows]

    merged_conn.executemany(
        f'INSERT OR IGNORE INTO "{tbl}" ({col_list}) VALUES ({placeholders})',
        trimmed
    )
    merged_conn.commit()
    skipped = len(local_cols) - len(common_cols)
    note = f" ({skipped} newer cols skipped)" if skipped else ""
    print(f"    SEEDED {tbl}: {local_count} rows copied from local{note}")

merged_conn.close()
local_conn.close()

# ── Done ──────────────────────────────────────────────────────────────────────
merged_size = os.path.getsize(merged) / 1024 / 1024
print(f"\n✅ Done. nml-merged.db is {merged_size:.1f} MB and ready to upload.")
print("   Run:  bash upload_merged.sh")
print()
print("TRANSACTIONAL DATA PRESERVED:")
print("  trades, trade_assets, trade_tokens, transactions,")
print("  players (ownership + ratings), draft_picks (ownership),")
print("  teams, users, team_needs, sessions, depth_chart,")
print("  watchlist, power_rankings, league_settings — all untouched.")
