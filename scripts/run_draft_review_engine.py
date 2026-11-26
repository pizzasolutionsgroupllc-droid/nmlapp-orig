#!/usr/bin/env python3
"""
Run the draft review engine against the local DB and dump the computed grades
for sanity review. No DB writes — just stdout output.

Usage:
    cd /Users/j/Desktop/Claude/nmlapp
    python3 scripts/run_draft_review_engine.py

Optional flag --json dumps machine-readable JSON (for piping into other tools).
"""
import os
import sys
import json
import sqlite3
from pathlib import Path

# Make backend importable regardless of where this is run from.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

from draft_review_engine import (  # noqa: E402
    compute_full_league_review,
    load_position_multipliers,
    compute_nml_adjusted_ranks,
    starter_tier,
    nfl_round_from_overall,
    project_rookie_ovr,
    PROSPECT_TO_GROUP,
)


def grade_color(g):
    """Return a small visual marker for the grade so 32-team output is scannable."""
    return {5: '★★★★★', 4: '★★★★ ', 3: '★★★  ', 2: '★★   ', 1: '★    '}.get(g, '?')


def fmt_value(d):
    if d is None:
        return '   ? '
    if d >= 5:
        return f'+{d:>3} 🟢'
    if d <= -5:
        return f'{d:>4} 🔴'
    return f'{d:>+4} 🟡'


def main():
    json_mode = '--json' in sys.argv
    db_path = os.environ.get('DB_PATH') or str(ROOT / 'data' / 'nml.db')
    if not os.path.exists(db_path):
        print(f"FATAL: DB not found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)

    if not json_mode:
        print(f"DB: {db_path}\n")
        mults = load_position_multipliers(conn)
        print("=== NML position multipliers (averaged from trade_grade_settings) ===")
        for grp in ['QB','RB','WR','TE','OT','IOL','EDGE','DT','LB','CB','S','K','P']:
            print(f"  {grp:6s} × {mults.get(grp, 1.0):.2f}")

        nml_lookup = compute_nml_adjusted_ranks(conn, 2026)
        print(f"\n  Total ranked prospects: {len(nml_lookup)}\n")

        # Sample top-15 to spot-check NML adjustment.
        top = sorted(nml_lookup.values(), key=lambda r: r['nml_rank'])[:15]
        print("=== Top 15 NML-adjusted board (showing position/consensus shift) ===")
        print(f"  {'NML#':>4} {'Cons#':>5} {'Δ':>4}  {'Pos':5s} {'×':>4}  Name")
        for r in top:
            shift = r['consensus_rank'] - r['nml_rank']
            shift_s = f'+{shift}' if shift > 0 else str(shift)
            print(f"  {r['nml_rank']:>4} {r['consensus_rank']:>5} {shift_s:>4}  {r['position']:5s} {r['multiplier']:.2f}  {r['name']}")
        print()

    reviews = compute_full_league_review(conn, 2026)

    if json_mode:
        print(json.dumps(reviews, indent=2))
        return

    graded = [r for r in reviews if not r.get('did_not_participate')]
    dnp = [r for r in reviews if r.get('did_not_participate')]

    print("=" * 80)
    print(" LEAGUE-WIDE DRAFT GRADES — 2026")
    print("=" * 80)
    print(f"  {'Rk':>3} {'Team':14s} {'Final':>5}   {'V':>1} {'N':>1} {'T':>1}  {'Picks':>5}   Stars")
    for r in graded:
        print(f"  {r['league_rank']:>3} {r['short_name']:14s}   {r['final_grade']}     "
              f"{r['value_grade']} {r['need_grade']} {r['talent_grade']}    "
              f"{len(r['picks']):>3}   {grade_color(r['final_grade'])}")
    if dnp:
        print(f"\n  DID NOT PARTICIPATE (traded out of all picks):")
        for r in dnp:
            unf = ', '.join(r.get('unfilled_needs', [])) or '—'
            print(f"     {r['short_name']:14s}  needs on board: {unf}")

    print()
    print("=" * 80)
    print(" PER-TEAM DETAIL")
    print("=" * 80)
    for r in graded:
        print(f"\n┌─ #{r['league_rank']:>2}  {r['short_name']:14s}  Final {r['final_grade']}/5  "
              f"(Value {r['value_grade']} · Need {r['need_grade']} · Talent {r['talent_grade']})")
        print(f"│  {'Pick':>5} {'Rd':>2} {'Player':22s} {'Pos':5s} {'Cons':>4} {'NML':>4} {'NFLrd':>5} {'projOVR':>7} {'Tier':>5}  Δ")
        # Pre-compute gap groups for starter_tier check
        gap_groups = {n['item_key'] for n in r.get('inferred_needs', []) if n.get('tier') in ('high','medium')}
        for p in r['picks']:
            cons = p.get('consensus_rank') if p.get('consensus_rank') is not None else '-'
            nml = p.get('nml_rank') if p.get('nml_rank') is not None else '-'
            nfl_slot = p.get('nfl_actual_slot')
            nfl = nfl_slot if nfl_slot is not None else '-'
            nfl_rd = nfl_round_from_overall(nfl_slot)
            nfl_rd_s = f'R{nfl_rd}' if nfl_rd else 'UDFA'
            grp = PROSPECT_TO_GROUP.get(p['position'], p['position'])
            proj = project_rookie_ovr(nfl_rd, p.get('consensus_rank'))
            tier = starter_tier(p, group_has_gap=(grp in gap_groups))
            tier_short = {'always_starter':'ST', 'conditional_starter':'CN', 'backup':'BK'}.get(tier, '?')
            best_marker = ''
            if r['best_pick_overall'] == p['overall_pick']:
                best_marker = ' ★BEST'
            elif r['worst_pick_overall'] == p['overall_pick']:
                best_marker = ' ⚠WORST'
            print(f"│  #{p['overall_pick']:>3} R{p['round']:>1} "
                  f"{p['player_name'][:22]:22s} {p['position']:5s} "
                  f"{str(cons):>4} {str(nml):>4} {nfl_rd_s:>5} {proj:>7} {tier_short:>5}  "
                  f"{fmt_value(p['value_delta'])}{best_marker}")
        if r.get('position_volume'):
            vol_s = ', '.join(f"{g}={n}" for g,n in sorted(r['position_volume'].items(), key=lambda x: -x[1]))
            print(f"│  Volume callouts (3+ at group): {vol_s}")
        if r['unfilled_needs']:
            print(f"│  Unfilled needs (likely targeted via trade): {', '.join(r['unfilled_needs'])}")
        else:
            print("│  Unfilled needs: (all addressed via draft)")

    if dnp:
        print()
        print("=" * 80)
        print(" DID NOT PARTICIPATE")
        print("=" * 80)
        for r in dnp:
            print(f"\n┌─ {r['short_name']:14s}  (no draft selections — traded out of all picks)")
            unf = r.get('unfilled_needs', [])
            if unf:
                print(f"│  Stated needs (will need to be filled via trade or FA): {', '.join(unf)}")
            else:
                print(f"│  No stated position needs on the team needs board.")

    conn.close()
    print(f"\n✅ Done. {len(reviews)} teams graded.")


if __name__ == '__main__':
    main()
