#!/usr/bin/env python3
"""
push_ratings_to_prod.py
-----------------------
Safely merges player STATS from the local DB into the production DB.

What it copies:
  - All Madden attribute columns (speed, catch, tackle, etc.)
  - overall_rating, position, nfl_team, birth_date, age
  - player_abilities rows

What it NEVER touches (NML league data):
  - nml_team_id       ← which NML team owns the player
  - is_free_agent     ← NML free agent status
  - contract_salary   ← NML contract
  - cap_hit
  - contract_length
  - contract_years_left
  - jersey_num        ← NML jersey number
  - draft_round / draft_pick / rookie_year / years_pro  ← NML draft history

Usage:
  1. Download production DB first:
       bash download_db.sh
     (saves to data/nml-backup-TIMESTAMP.db)

  2. Run this script, pointing at the downloaded file:
       python3 push_ratings_to_prod.py data/nml-backup-20260417-XXXXXX.db

  3. Upload the merged file:
       bash upload_db.sh
     (uploads data/nml.db — the script writes merged output there)
"""

import sys
import os
import shutil
import sqlite3
from datetime import datetime

# ── Columns that come from Madden ratings and are safe to overwrite ───────────
STAT_COLS = [
    # General
    "speed", "acceleration", "strength", "agility", "awareness",
    "jump", "injury", "stamina", "toughness",
    # Ball carrier
    "carry", "break_tackle", "truck", "cod", "bcv",
    "stiff_arm", "spin", "juke", "break_sack",
    # Receiving
    "catch", "spec_catch", "cit", "route_short", "route_med", "route_deep", "release",
    # Passing
    "throw_power", "throw_under_pressure", "throw_acc_short",
    "throw_acc_mid", "throw_acc_deep", "throw_on_run", "play_action",
    # Blocking
    "pass_block", "pass_block_power", "pass_block_finesse",
    "run_block", "run_block_power", "run_block_finesse",
    "impact_block", "lead_block",
    # Defense
    "play_rec", "pursuit", "tackle", "hit_power", "block_shed",
    "power_moves", "finesse_moves", "man_cover", "zone_cover", "press",
    # Kicking
    "kick_power", "kick_acc", "kick_return",
    # Meta — player profile, NOT NML assignments
    "overall_rating",
    "position",
    "nfl_team",
    "birth_date",
    "age",
    "dev_trait",
]

# ── Columns that belong to the NML — NEVER overwrite these ───────────────────
NML_COLS = {
    "nml_team_id", "is_free_agent",
    "contract_salary", "cap_hit", "contract_length", "contract_years_left",
    "jersey_num",
    "draft_round", "draft_pick", "rookie_year", "years_pro",
}


def get_cols(conn, table="players"):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def merge(prod_path: str, local_path: str, output_path: str, dry_run: bool = False):
    print(f"\n{'DRY RUN — ' if dry_run else ''}Merging ratings from local → production\n")
    print(f"  Local:      {local_path}")
    print(f"  Production: {prod_path}")
    print(f"  Output:     {output_path}\n")

    # Work on a copy of production so we never corrupt the original
    if not dry_run:
        shutil.copy2(prod_path, output_path)
        print(f"✓ Copied production DB to {output_path}")

    local  = sqlite3.connect(local_path);  local.row_factory  = sqlite3.Row
    merged = sqlite3.connect(output_path); merged.row_factory = sqlite3.Row

    # ── Run pending schema migrations on the merged (prod copy) DB ────────────
    # Production may be behind local if Railway hasn't restarted yet.
    # We apply the same ALTER TABLE migrations that database.py would run.
    pending_migrations = [
        "ALTER TABLE players ADD COLUMN birth_date TEXT",
        "ALTER TABLE players ADD COLUMN cod INTEGER",
        "ALTER TABLE players ADD COLUMN bcv INTEGER",
        "ALTER TABLE players ADD COLUMN throw_acc_short INTEGER",
        "ALTER TABLE players ADD COLUMN throw_acc_mid INTEGER",
        "ALTER TABLE players ADD COLUMN throw_acc_deep INTEGER",
        "ALTER TABLE players ADD COLUMN throw_on_run INTEGER",
        "ALTER TABLE players ADD COLUMN throw_under_pressure INTEGER",
        "ALTER TABLE players ADD COLUMN play_action INTEGER",
        "ALTER TABLE players ADD COLUMN pass_block_power INTEGER",
        "ALTER TABLE players ADD COLUMN pass_block_finesse INTEGER",
        "ALTER TABLE players ADD COLUMN run_block_power INTEGER",
        "ALTER TABLE players ADD COLUMN run_block_finesse INTEGER",
        "ALTER TABLE players ADD COLUMN lead_block INTEGER",
        "ALTER TABLE players ADD COLUMN kick_power INTEGER",
        "ALTER TABLE players ADD COLUMN kick_acc INTEGER",
        "ALTER TABLE players ADD COLUMN kick_return INTEGER",
        "ALTER TABLE players ADD COLUMN hit_power INTEGER",
        "ALTER TABLE players ADD COLUMN pursuit INTEGER",
        "ALTER TABLE players ADD COLUMN block_shed INTEGER",
        "ALTER TABLE players ADD COLUMN power_moves INTEGER",
        "ALTER TABLE players ADD COLUMN finesse_moves INTEGER",
        "ALTER TABLE players ADD COLUMN break_sack INTEGER",
        "ALTER TABLE players ADD COLUMN man_cover INTEGER",
        "ALTER TABLE players ADD COLUMN zone_cover INTEGER",
        "ALTER TABLE players ADD COLUMN play_rec INTEGER",
        "ALTER TABLE players ADD COLUMN press INTEGER",
        "ALTER TABLE players ADD COLUMN impact_block INTEGER",
        "ALTER TABLE players ADD COLUMN long_snap INTEGER",
        "ALTER TABLE players ADD COLUMN confidence INTEGER",
    ]
    if not dry_run:
        migrated = []
        for sql in pending_migrations:
            try:
                merged.execute(sql)
                merged.commit()
                migrated.append(sql.split("COLUMN ")[1].split()[0])
            except Exception:
                pass  # column already exists — fine
        if migrated:
            print(f"✓ Applied {len(migrated)} missing schema migrations: {', '.join(migrated)}")

    # Only update columns that actually exist in the production DB (after migrations)
    prod_cols  = get_cols(merged)
    local_cols = get_cols(local)
    safe_cols  = [c for c in STAT_COLS if c in prod_cols and c in local_cols]

    print(f"Stat columns to sync: {len(safe_cols)}")
    print(f"NML columns protected: {', '.join(sorted(NML_COLS & prod_cols))}\n")

    # ── 1. Update existing players ────────────────────────────────────────────
    local_players = {
        row["id"]: dict(row)
        for row in local.execute("SELECT * FROM players").fetchall()
    }
    prod_ids = {
        row[0]
        for row in merged.execute("SELECT id FROM players").fetchall()
    }

    updated = 0
    inserted = 0
    name_matched = 0   # existed in prod under a different ID — stats still synced

    for pid, lp in local_players.items():
        if pid in prod_ids:
            # Player exists in production by ID — update only stat cols
            set_parts = [f"{c} = ?" for c in safe_cols if lp.get(c) is not None]
            vals      = [lp[c] for c in safe_cols if lp.get(c) is not None]
            if set_parts:
                sql = f"UPDATE players SET {', '.join(set_parts)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
                if not dry_run:
                    merged.execute(sql, vals + [pid])
                updated += 1
        else:
            # ID not in production — check if player already exists by name
            existing = merged.execute(
                "SELECT id FROM players WHERE LOWER(first_name)=LOWER(?) AND LOWER(last_name)=LOWER(?)",
                (lp.get("first_name",""), lp.get("last_name",""))
            ).fetchone()
            if existing:
                # Player exists in prod under a different ID — update their stats using prod ID
                prod_id = existing[0]
                set_parts = [f"{c} = ?" for c in safe_cols if lp.get(c) is not None]
                vals      = [lp[c] for c in safe_cols if lp.get(c) is not None]
                if set_parts:
                    sql = f"UPDATE players SET {', '.join(set_parts)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
                    if not dry_run:
                        merged.execute(sql, vals + [prod_id])
                name_matched += 1
                continue

            # Genuinely new player — insert as FA, NML cols left NULL
            # Only insert columns that exist in the (migrated) output DB
            insert_cols = [c for c in local_cols
                           if c not in NML_COLS
                           and c not in ("id", "created_at", "updated_at", "madden_id")
                           and c in prod_cols
                           and lp.get(c) is not None]
            placeholders = ", ".join("?" for _ in insert_cols)
            col_names    = ", ".join(insert_cols)
            vals         = [lp[c] for c in insert_cols]
            sql = f"INSERT INTO players ({col_names}) VALUES ({placeholders})"
            if not dry_run:
                merged.execute(sql, vals)
            inserted += 1

    if not dry_run:
        merged.commit()

    print(f"Players updated by ID:          {updated}")
    print(f"Players updated by name match:  {name_matched}  (existed in prod under different ID)")
    print(f"New FA players inserted:        {inserted}\n")

    # ── 2. Ensure player_abilities table exists in merged DB ─────────────────
    tables = {r[0] for r in merged.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "player_abilities" not in tables:
        print("Creating player_abilities table in merged DB...")
        if not dry_run:
            merged.execute("""
                CREATE TABLE IF NOT EXISTS player_abilities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL,
                    ability_name TEXT NOT NULL,
                    ability_type TEXT NOT NULL DEFAULT 'superstar',
                    description TEXT,
                    FOREIGN KEY(player_id) REFERENCES players(id)
                )""")
            merged.commit()
        print("✓ player_abilities table created")

    # ── 3. Sync player_abilities rows ─────────────────────────────────────────
    _sync_abilities(local, merged, set(local_players.keys()) & prod_ids, dry_run)

    local.close()
    merged.close()

    if dry_run:
        print("DRY RUN complete — no files were modified.")
    else:
        print(f"\n✓ Merged DB written to: {output_path}")
        print("  Next step: bash upload_db.sh  (it uploads data/nml.db)")


def _sync_abilities(local, merged, player_ids_in_both, dry_run):
    tables = {r[0] for r in merged.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "player_abilities" not in tables:
        print("⚠  player_abilities table not in production — skipping")
        return
    ab_rows = local.execute("SELECT * FROM player_abilities").fetchall()
    ab_count = len(ab_rows)
    if ab_count == 0:
        print("Abilities: 0 rows in local DB — nothing to sync")
        return
    if not dry_run:
        # Clear existing abilities for players we're updating, then re-insert
        merged.execute("DELETE FROM player_abilities WHERE player_id IN (SELECT id FROM players)")
        for row in ab_rows:
            r = dict(row)
            merged.execute(
                "INSERT OR IGNORE INTO player_abilities (player_id, ability_name, ability_type, description) VALUES (?, ?, ?, ?)",
                (r["player_id"], r["ability_name"], r["ability_type"], r.get("description", ""))
            )
        merged.commit()
    print(f"Abilities synced: {ab_count} rows")


if __name__ == "__main__":
    OUTPUT_DB = "data/nml-merged.db"   # final merged file — what upload_merged.sh will push

    # Parse args: positional = prod DB path; --local= = override local source
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run   = "--dry-run" in sys.argv
    local_override = next((a.split("=",1)[1] for a in sys.argv if a.startswith("--local=")), None)

    if not args:
        print(__doc__)
        print("ERROR: provide path to downloaded production DB as argument.")
        print("  python3 push_ratings_to_prod.py data/nml-backup-XXXXXX.db")
        print("  python3 push_ratings_to_prod.py data/nml-backup-XXXXXX.db --local=data/nml-local-snapshot-XXXXXX.db")
        sys.exit(1)

    prod_db  = args[0]
    local_db = local_override or "data/nml.db"

    for path, label in [(prod_db, "Production"), (local_db, "Local")]:
        if not os.path.exists(path):
            print(f"ERROR: {label} file not found: {path}")
            sys.exit(1)

    if prod_db == local_db:
        print("ERROR: production and local paths are the same file.")
        sys.exit(1)

    # ── Snapshot local DB so merge() can read it safely ──────────────────────
    # merge() writes its output to OUTPUT_DB (= data/nml.db by default).
    # If local_db IS output_db, snapshot it first so it isn't overwritten mid-merge.
    if os.path.realpath(local_db) == os.path.realpath(OUTPUT_DB):
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        local_snapshot = f"data/nml-local-snapshot-{ts}.db"
        shutil.copy2(local_db, local_snapshot)
        if not dry_run:
            print(f"✓ Local DB snapshot saved to: {local_snapshot}")
        local_source = local_snapshot
    else:
        local_source = local_db   # already a separate file — use directly

    merge(prod_db, local_source, OUTPUT_DB, dry_run=dry_run)
