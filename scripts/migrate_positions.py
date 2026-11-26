"""
migrate_positions.py
--------------------
Converts legacy/generic position values in the players table to the
canonical values the NML app now uses.

Conversions:
  RB  → HB
  DL  → DT

Run this against the prod backup before uploading:
  python3 scripts/migrate_positions.py data/backups/<latest-backup>.db
"""

import sqlite3
import sys

if len(sys.argv) < 2:
    print("Usage: python3 scripts/migrate_positions.py <path-to-db>")
    sys.exit(1)

db_path = sys.argv[1]
print(f"Connecting to: {db_path}")

conn = sqlite3.connect(db_path)

conversions = [
    ("RB", "HB"),
    ("DL", "DT"),
]

for old, new in conversions:
    cur = conn.execute(
        "UPDATE players SET position=? WHERE position=?", (new, old)
    )
    print(f"  {old} → {new}: {cur.rowcount} rows updated")

conn.commit()
conn.close()
print("Done. DB saved.")
