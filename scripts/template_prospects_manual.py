#!/usr/bin/env python3
"""
Template for manually entering rankings from paywalled/login-required sources:
  - Dane Brugler "The Beast" (The Athletic) → imports/prospects_brugler.json
  - Brandon Thorn (Trench Warfare) → imports/prospects_thorn.json
  - PFF Big Board → imports/prospects_pff.json (optional)

Instructions:
1. Open the source in your browser (you're logged in)
2. Find the rankings list
3. Edit the lists below and run this script to create the JSON files

Format for Brugler (overall big board rank):
    brugler_list = [
        {"name": "Cam Ward", "position": "QB", "brugler_rank": 1},
        ...
    ]

Format for Thorn (OL score 0-10, OT and IOL separate):
    thorn_list = [
        {"name": "Armand Membou", "position": "OT", "thorn_ol_score": 9.1},
        {"name": "Will Campbell", "position": "OT", "thorn_ol_score": 8.8},
        ...
    ]
"""
import json, os

IMPORTS = os.path.join(os.path.dirname(__file__), '..', 'imports')
os.makedirs(IMPORTS, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# BRUGLER — "The Beast" overall prospect rankings
# Copy from The Athletic while logged in
# ─────────────────────────────────────────────────────────────────────────────
brugler_list = [
    # {"name": "Cam Ward", "position": "QB", "school": "Miami", "brugler_rank": 1},
    # Add entries here...
]

# ─────────────────────────────────────────────────────────────────────────────
# THORN — Trench Warfare OL scores (OT and IOL combined)
# Copy from trenchwarfare.substack.com while logged in
# ─────────────────────────────────────────────────────────────────────────────
thorn_list = [
    # {"name": "Armand Membou", "position": "OT", "school": "Missouri", "thorn_ol_score": 9.1},
    # Add entries here...
]

# ─────────────────────────────────────────────────────────────────────────────
# HARMON — Reception Perception WR ranks (if scraper fails)
# ─────────────────────────────────────────────────────────────────────────────
harmon_list = [
    # {"name": "Tetairoa McMillan", "position": "WR", "harmon_wr_rank": 1},
    # Add entries here...
]

# ─────────────────────────────────────────────────────────────────────────────
# PFF Big Board (optional)
# ─────────────────────────────────────────────────────────────────────────────
pff_list = [
    # {"name": "Cam Ward", "position": "QB", "pff_rank": 1},
    # Add entries here...
]

def save(data, filename, label):
    if not data:
        print(f"⚠️  {label}: No data entered — skipping")
        return
    path = os.path.join(IMPORTS, filename)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"✅ {label}: {len(data)} entries saved to {filename}")

save(brugler_list, 'prospects_brugler.json', 'Brugler')
save(thorn_list,   'prospects_thorn.json',   'Thorn')
save(harmon_list,  'prospects_harmon.json',  'Harmon (manual)')
save(pff_list,     'prospects_pff.json',     'PFF')
print("\nRun import_prospects.py when ready to merge into DB.")
