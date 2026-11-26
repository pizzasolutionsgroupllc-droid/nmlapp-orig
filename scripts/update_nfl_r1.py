"""
update_nfl_r1.py — Thursday Night NFL Draft Tracker
=====================================================
Run this script while watching the NFL R1 draft Thursday night.
As each pick is announced, enter the player name and it logs the pick
into the draft_prospects table.

When you're done, it auto-regenerates imports/opus_session_input.md
so it's ready for Friday morning's Opus session.

Usage:
  cd /Users/j/Desktop/Claude/nmlapp
  python3 scripts/update_nfl_r1.py

Tips:
  - Type partial names — it fuzzy-matches to the prospect board
  - Type 'skip' to skip a pick number
  - Type 'done' when R1 is finished
  - Type 'show' to see all picks logged so far
  - Type 'undo' to remove the last pick
"""
import sqlite3, re, unicodedata, subprocess, sys, os

DB = os.path.join(os.path.dirname(__file__), '..', 'data', 'nml.db')

def norm(s):
    if not s: return ''
    s = str(s).lower().strip()
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^a-z0-9 ]', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def fuzzy_match(query, prospects, top_n=5):
    q = norm(query).split()
    scores = []
    for p in prospects:
        n = norm(p['name'])
        score = sum(1 for word in q if word in n)
        if score > 0:
            scores.append((score, p))
    scores.sort(key=lambda x: -x[0])
    return [p for _, p in scores[:top_n]]

def get_prospects(conn):
    c = conn.cursor()
    c.execute("""
        SELECT id, name, position, school, consensus_rank, brugler_grade,
               nfl_team, nfl_round, nfl_pick
        FROM draft_prospects
        WHERE year = 2026
        ORDER BY COALESCE(consensus_rank, 9999)
    """)
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, r)) for r in c.fetchall()]

def log_pick(conn, prospect_id, nfl_team, pick_num, overall):
    c = conn.cursor()
    c.execute("""
        UPDATE draft_prospects
        SET nfl_team=?, nfl_round=1, nfl_pick=?, nfl_overall=?
        WHERE id=?
    """, (nfl_team, pick_num, overall, prospect_id))
    conn.commit()

def clear_pick(conn, prospect_id):
    c = conn.cursor()
    c.execute("""
        UPDATE draft_prospects
        SET nfl_team=NULL, nfl_round=NULL, nfl_pick=NULL, nfl_overall=NULL
        WHERE id=?
    """, (prospect_id,))
    conn.commit()

def show_logged(conn):
    c = conn.cursor()
    c.execute("""
        SELECT nfl_overall, nfl_team, name, position, school
        FROM draft_prospects
        WHERE year=2026 AND nfl_round=1
        ORDER BY nfl_overall
    """)
    rows = c.fetchall()
    if not rows:
        print("  No picks logged yet.")
        return
    print(f"\n  {'#':<4} {'Team':<25} {'Player':<28} {'Pos':<6} School")
    print("  " + "-"*80)
    for r in rows:
        print(f"  {r[0]:<4} {r[1]:<25} {r[2]:<28} {r[3]:<6} {r[4]}")
    print(f"\n  Total logged: {len(rows)} picks\n")

def regenerate_input():
    script = os.path.join(os.path.dirname(__file__), '..', 'outputs', 'generate_opus_session.py')
    # Try bash path
    bash_script = '/sessions/gifted-compassionate-wright/mnt/outputs/generate_opus_session.py'
    try:
        result = subprocess.run(['python3', bash_script], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print("\n✅ opus_session_input.md regenerated successfully.")
            print(result.stdout.strip())
        else:
            print(f"\n⚠️  Regeneration had issues: {result.stderr[:200]}")
    except Exception as e:
        print(f"\n⚠️  Could not auto-regenerate: {e}")
        print("  Manually run: python3 outputs/generate_opus_session.py")

def main():
    conn = sqlite3.connect(DB)
    prospects = get_prospects(conn)
    available = [p for p in prospects if not p['nfl_team']]

    print("\n" + "="*60)
    print("  NML NFL R1 DRAFT TRACKER — 2026")
    print("="*60)
    print(f"  Prospects loaded: {len(prospects)} | Already taken: {len(prospects)-len(available)}")
    print("\n  Commands: type player name | 'skip N' | 'show' | 'undo' | 'done'")
    print("="*60 + "\n")

    pick_num = 1
    pick_log = []  # for undo

    while pick_num <= 32:
        print(f"\n  ── Pick #{pick_num} ──")
        raw = input("  Player name (or command): ").strip()

        if not raw:
            continue

        if raw.lower() == 'done':
            break

        if raw.lower() == 'show':
            show_logged(conn)
            continue

        if raw.lower() == 'undo':
            if pick_log:
                last = pick_log.pop()
                clear_pick(conn, last['id'])
                pick_num = last['pick_num']
                print(f"  ↩ Undone: {last['name']} (pick #{last['pick_num']})")
            else:
                print("  Nothing to undo.")
            continue

        if raw.lower().startswith('skip'):
            parts = raw.split()
            skip_to = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else pick_num + 1
            print(f"  Skipping to pick #{skip_to}")
            pick_num = skip_to
            continue

        # Fuzzy match
        matches = fuzzy_match(raw, available)
        if not matches:
            print(f"  ❌ No match found for '{raw}'. Try again.")
            continue

        if len(matches) == 1:
            player = matches[0]
        else:
            print(f"\n  Found {len(matches)} matches:")
            for i, m in enumerate(matches, 1):
                rank = f"#{m['consensus_rank']}" if m['consensus_rank'] else f"({m['brugler_grade']})"
                print(f"    {i}. {m['name']} ({m['position']}, {m['school']}) {rank}")
            choice = input("  Select (1-{}) or 0 to re-enter: ".format(len(matches))).strip()
            if not choice.isdigit() or int(choice) == 0:
                continue
            idx = int(choice) - 1
            if idx < 0 or idx >= len(matches):
                continue
            player = matches[idx]

        # Get NFL team
        nfl_team = input(f"  NFL team drafting {player['name']}: ").strip()
        if not nfl_team:
            continue

        # Confirm
        rank = f"#{player['consensus_rank']}" if player['consensus_rank'] else f"({player['brugler_grade']})"
        print(f"\n  ✅ Logging: Pick #{pick_num} — {nfl_team} selects {player['name']} ({player['position']}, {player['school']}) {rank}")
        confirm = input("  Confirm? (y/n): ").strip().lower()
        if confirm != 'y':
            continue

        log_pick(conn, player['id'], nfl_team, pick_num, pick_num)
        pick_log.append({'id': player['id'], 'name': player['name'], 'pick_num': pick_num})

        # Remove from available
        available = [p for p in available if p['id'] != player['id']]

        # Show remaining top-5 available at premium NML positions
        top_available = [p for p in available if p['position'] in ('WR','CB','QB','RB','EDGE','S') and (p['consensus_rank'] or 999) <= 50][:5]
        if top_available:
            print("  📋 Top available (skill): " + " | ".join(f"{p['name']} ({p['position']})" for p in top_available))

        pick_num += 1

    show_logged(conn)
    conn.close()

    print("\n" + "="*60)
    print("  R1 COMPLETE — Regenerating Opus input file...")
    print("="*60)
    regenerate_input()
    print("\n  ✅ Ready for Friday morning Opus session!")
    print("  File: imports/opus_session_input.md\n")

if __name__ == '__main__':
    main()
