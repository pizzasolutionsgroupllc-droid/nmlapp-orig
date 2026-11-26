"""
Draft Review Engine
-------------------
Pure functions for grading an NML draft. No Flask deps — testable standalone.

Computes:
  - NML-adjusted consensus rank (re-sorts the consensus board using Trade Grader
    position multipliers — WR worth more, OL/DT worth less, etc.)
  - Per-pick value delta (positive = steal, negative = reach)
  - Three sub-grades per team on a 1-5 scale: Value, Need, Talent
  - Final 1-5 grade per team, rolled up from the three sub-grades
  - League-wide 1-32 ranking, ties broken by sub-grade sum

Reads from the standard NML schema: draft_prospects, draft_picks, draft_selections,
trade_grade_settings, team_needs, teams, players.

Designed to be called from a one-shot seed script for now (no API key required).
A future iteration can drop an LLM call into the blurb / looking-ahead generation.
"""

import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


def normalize_name(s: Optional[str]) -> str:
    """Normalize a player/prospect name for matching across tables.

    Strips: Jr./Sr./II/III/IV suffixes, punctuation, extra whitespace.
    Lowercases. So "Rueben Bain Jr." and "Rueben Bain" both produce
    "rueben bain", and "C.J. Allen" and "CJ Allen" both produce "cj allen".
    """
    if not s:
        return ''
    n = s.lower().strip()
    # Strip suffixes (jr/sr/ii/iii/iv).
    n = re.sub(r'\s+(jr|sr|ii|iii|iv|v)\.?$', '', n)
    # Drop punctuation.
    n = re.sub(r'[^a-z\s]', '', n)
    # Collapse whitespace.
    n = re.sub(r'\s+', ' ', n).strip()
    return n

# ── Roster-based need inference ─────────────────────────────────────────────
#
# Per Jon: stated team_needs boards may have been edited mid-draft (e.g. owner
# removes "WR" after drafting one), so for grading purposes we infer needs from
# roster ratings instead. We count starter-quality players (≥ STARTER_OVR_FLOOR)
# in each broad position GROUP — so a 90-rated FS + a 70-rated SS = 2 in the S
# group (FS/SS interchangeable per depth chart). Same for OT (LT/RT), IOL
# (LG/C/RG), EDGE (LEDGE/REDGE), LB (MIKE/WILL/SAM).

STARTER_OVR_FLOOR = 75   # min OVR to count as a credible starter
NO_STARTER_FLOOR = 70    # if top player at group is below this, it's a high need

# Number of starter slots typically needed at each position group (offense in
# Shotgun 3WR, defense in 4-2 Nickel — the app's defaults).
POSITION_GROUP_STARTERS = {
    'QB':   1,
    'RB':   1,   # HB; FB optional
    'WR':   3,   # 3WR base
    'TE':   1,
    'OT':   2,   # LT + RT, interchangeable
    'IOL':  3,   # LG + C + RG, interchangeable
    'EDGE': 2,   # LEDGE + REDGE
    'DT':   2,
    'LB':   2,   # nickel base
    'CB':   3,   # CB1 + CB2 + nickel
    'S':    2,   # FS + SS, interchangeable
}


# ── Position group mapping ─────────────────────────────────────────────────
#
# draft_prospects.position uses broad scouting buckets (WR / EDGE / IOL / OT / etc.).
# trade_grade_settings stores multipliers using Madden-specific codes (LEDGE / REDGE
# / MIKE / WILL / SAM / LT / RT / LG / RG / C). We map each prospect bucket to the
# list of Madden codes that compose it and average the multipliers.

PROSPECT_TO_MADDEN_KEYS = {
    'QB':   ['pos_QB'],
    'RB':   ['pos_HB'],
    'HB':   ['pos_HB'],
    'FB':   ['pos_FB'],
    'WR':   ['pos_WR'],
    'TE':   ['pos_TE'],
    'OT':   ['pos_LT', 'pos_RT'],
    'LT':   ['pos_LT'],
    'RT':   ['pos_RT'],
    'IOL':  ['pos_LG', 'pos_RG', 'pos_C'],
    'OG':   ['pos_LG', 'pos_RG'],
    'LG':   ['pos_LG'],
    'RG':   ['pos_RG'],
    'C':    ['pos_C'],
    'EDGE': ['pos_LEDGE', 'pos_REDGE'],
    'LEDGE':['pos_LEDGE'],
    'REDGE':['pos_REDGE'],
    'DE':   ['pos_LEDGE', 'pos_REDGE'],
    'DT':   ['pos_DT'],
    'NT':   ['pos_DT'],
    'DL5T': ['pos_DT'],
    'LB':   ['pos_MIKE', 'pos_WILL', 'pos_SAM'],
    'MLB':  ['pos_MIKE'],
    'ILB':  ['pos_MIKE'],
    'OLB':  ['pos_WILL', 'pos_SAM'],
    'MIKE': ['pos_MIKE'],
    'WILL': ['pos_WILL'],
    'SAM':  ['pos_SAM'],
    'CB':   ['pos_CB'],
    'S':    ['pos_FS', 'pos_SS'],
    'FS':   ['pos_FS'],
    'SS':   ['pos_SS'],
    'K':    ['pos_K'],
    'P':    ['pos_P'],
    'LS':   ['pos_LS'],
}

# Broad position group used for grouping/display.
PROSPECT_TO_GROUP = {
    'QB':'QB', 'RB':'RB', 'HB':'RB', 'FB':'RB',
    'WR':'WR', 'TE':'TE',
    'OT':'OT', 'LT':'OT', 'RT':'OT',
    'IOL':'IOL', 'OG':'IOL', 'LG':'IOL', 'RG':'IOL', 'C':'IOL',
    'EDGE':'EDGE', 'LEDGE':'EDGE', 'REDGE':'EDGE', 'DE':'EDGE',
    'DT':'DT', 'NT':'DT', 'DL5T':'DT',
    'LB':'LB', 'MLB':'LB', 'ILB':'LB', 'OLB':'LB',
    'MIKE':'LB', 'WILL':'LB', 'SAM':'LB',
    'CB':'CB',
    'S':'S', 'FS':'S', 'SS':'S',
    'K':'K', 'P':'P', 'LS':'LS',
}


def load_position_multipliers(conn) -> Dict[str, float]:
    """Return a dict mapping each prospect-position string to its NML multiplier.

    Pulls the raw Madden-coded weights from trade_grade_settings, then for each
    broad prospect position averages the relevant Madden weights so we can
    apply a single multiplier per drafted prospect.
    """
    c = conn.cursor()
    c.execute("SELECT key, value FROM trade_grade_settings WHERE key LIKE 'pos_%'")
    raw: Dict[str, float] = {}
    for k, v in c.fetchall():
        try:
            raw[k] = float(v)
        except (TypeError, ValueError):
            continue

    out: Dict[str, float] = {}
    for prospect_pos, madden_keys in PROSPECT_TO_MADDEN_KEYS.items():
        vals = [raw[k] for k in madden_keys if k in raw]
        if not vals:
            out[prospect_pos] = 1.0
            continue
        out[prospect_pos] = sum(vals) / len(vals)
    return out


def compute_nml_adjusted_ranks(conn, year: int = 2026) -> Dict[int, Dict]:
    """Re-rank prospects using NML position multipliers.

    Lower consensus_rank = better. We divide consensus_rank by the position
    multiplier so positions NML values more (multiplier > 1) move up the board.
    Then sort everyone by adjusted score ascending and assign new integer ranks.

    Returns: { prospect_id: { 'name', 'position', 'consensus_rank',
                              'nml_adjusted_score', 'nml_rank',
                              'nfl_overall', 'pff_rank', 'espn_rank' } }
    """
    multipliers = load_position_multipliers(conn)

    c = conn.cursor()
    c.execute("""
        SELECT id, name, position, consensus_rank, nfl_overall, pff_rank, espn_rank
        FROM draft_prospects
        WHERE year = ? AND consensus_rank IS NOT NULL
    """, (year,))
    rows = c.fetchall()

    scored = []
    for pid, name, pos, cons_rank, nfl_o, pff_r, espn_r in rows:
        mult = multipliers.get(pos, 1.0)
        # Guard against degenerate multipliers.
        if mult <= 0:
            mult = 0.01
        adjusted_score = cons_rank / mult
        scored.append({
            'id': pid,
            'name': name,
            'position': pos,
            'consensus_rank': cons_rank,
            'nml_adjusted_score': adjusted_score,
            'nfl_overall': nfl_o,
            'pff_rank': pff_r,
            'espn_rank': espn_r,
            'multiplier': mult,
        })

    # Sort ascending — lowest score = best.
    scored.sort(key=lambda r: (r['nml_adjusted_score'], r['consensus_rank']))
    for i, r in enumerate(scored, start=1):
        r['nml_rank'] = i

    return {r['id']: r for r in scored}


# ── Per-pick value math ─────────────────────────────────────────────────────

def compute_value_delta(overall_pick: int, nml_rank: Optional[int]) -> Optional[int]:
    """Positive = steal (drafted later than ranked), negative = reach.

    Returns None if no NML rank is available (prospect not on consensus board).
    """
    if nml_rank is None:
        return None
    return overall_pick - nml_rank


def value_label(delta: Optional[int]) -> str:
    """Map a value delta to a human label used in pick chips."""
    if delta is None:
        return 'Unranked'
    if delta >= 5:
        return 'Steal'
    if delta <= -5:
        return 'Reach'
    return 'Even'


# ── Team-level grades ───────────────────────────────────────────────────────

def _round_weight(rd: int) -> float:
    """Higher rounds matter more for grading."""
    return {1: 1.0, 2: 0.85, 3: 0.7, 4: 0.55, 5: 0.4, 6: 0.3, 7: 0.2}.get(rd, 0.2)


def compute_value_grade(picks: List[Dict]) -> int:
    """1-5 based on round-weighted average value delta.

    Bands tightened (Apr 2026) for more visual contrast across the league.

    picks: list of dicts with 'round' and 'value_delta' keys (delta may be None).
    """
    weighted_sum = 0.0
    weight_total = 0.0
    for p in picks:
        d = p.get('value_delta')
        if d is None:
            continue
        # Cap extremes at the math layer so one outlier doesn't dominate.
        d = max(-40, min(40, d))
        w = _round_weight(p.get('round') or 7)
        weighted_sum += d * w
        weight_total += w
    if weight_total == 0:
        return 3
    avg = weighted_sum / weight_total

    if avg >= 8:
        return 5
    if avg >= 2:
        return 4
    if avg >= -3:
        return 3
    if avg >= -10:
        return 2
    return 1


def compute_need_alignment_score(picks: List[Dict], team_needs: List[Dict]) -> Optional[float]:
    """Continuous score 0-1 measuring how well picks aligned with stated needs.

    Now factors in starter-tier (per Jon: only NFL R1-R3 picks credibly fill
    a need; backup-tier picks at need positions still count, but at lower
    weight since they don't actually solve the starter problem).

    Per-pick contribution (when at a need position):
      - high-tier need + always_starter pick: 1.00
      - high-tier need + conditional_starter pick: 0.80
      - high-tier need + backup pick: 0.30
      - medium-tier need + always_starter: 0.60
      - medium-tier need + conditional_starter: 0.50
      - medium-tier need + backup: 0.20
    """
    if not picks:
        return None

    high = {n['item_key'] for n in team_needs if n.get('item_type') == 'position' and n.get('tier') == 'high'}
    med  = {n['item_key'] for n in team_needs if n.get('item_type') == 'position' and n.get('tier') == 'medium'}

    def grp(p): return PROSPECT_TO_GROUP.get(p, p)
    high_groups = {grp(p) for p in high}
    med_groups  = {grp(p) for p in med}

    if not high_groups and not med_groups:
        return None

    gap_groups = high_groups | med_groups

    weighted_alignment = 0.0
    weight_total = 0.0
    for p in picks:
        if not p.get('position'):
            continue
        g = grp(p['position'])
        w = _round_weight(p.get('round') or 7)
        tier = starter_tier(p, group_has_gap=(g in gap_groups))

        contribution = 0.0
        if g in high_groups:
            contribution = {'always_starter': 1.00, 'conditional_starter': 0.80, 'backup': 0.30}[tier]
        elif g in med_groups:
            contribution = {'always_starter': 0.60, 'conditional_starter': 0.50, 'backup': 0.20}[tier]
        # else: 0 contribution

        weighted_alignment += contribution * w
        weight_total += w

    if weight_total == 0:
        return None
    return weighted_alignment / weight_total


def compute_need_grade(picks: List[Dict], team_needs: List[Dict]) -> int:
    """Single-team Need grade fallback (used when not running the full league).

    Bands chosen to roughly match the percentile rollup the orchestrator uses.
    """
    score = compute_need_alignment_score(picks, team_needs)
    if score is None:
        return 3
    if score >= 0.55:
        return 5
    if score >= 0.40:
        return 4
    if score >= 0.25:
        return 3
    if score >= 0.10:
        return 2
    return 1


def compute_talent_grade(picks: List[Dict]) -> int:
    """1-5 based on PROJECTED rookie OVR — NFL slot + consensus rank.

    Per Jon: EA Madden assigns initial rookie OVR primarily from NFL draft
    slot, with consensus rank as a secondary signal. So Talent grade now
    measures the projected starting-OVR average of the class, weighted by
    NML round (early NML picks count more for grading because they're the
    strategic centerpieces of the class).
    """
    weighted_sum = 0.0
    weight_total = 0.0
    for p in picks:
        nfl_rd = nfl_round_from_overall(p.get('nfl_actual_slot'))
        cons = p.get('consensus_rank')
        proj_ovr = project_rookie_ovr(nfl_rd, cons)
        w = _round_weight(p.get('round') or 7)
        weighted_sum += proj_ovr * w
        weight_total += w
    if weight_total == 0:
        return 1
    avg = weighted_sum / weight_total

    if avg >= 75:
        return 5
    if avg >= 71:
        return 4
    if avg >= 67:
        return 3
    if avg >= 64:
        return 2
    return 1


def _raw_score(value_g: int, need_g: int, talent_g: int) -> float:
    """Continuous raw score used for ranking and percentile-based rollup.

    Value 35% / Need 30% / Talent 35% — feel free to tune.
    """
    return 0.35 * value_g + 0.30 * need_g + 0.35 * talent_g


def compute_final_grade(value_g: int, need_g: int, talent_g: int) -> int:
    """Single-team weighted-avg fallback. Bands roughly match the percentile
    rollup the orchestrator uses for the full-league pass.
    """
    raw = _raw_score(value_g, need_g, talent_g)
    if raw >= 4.2:
        return 5
    if raw >= 3.5:
        return 4
    if raw >= 2.5:
        return 3
    if raw >= 1.7:
        return 2
    return 1


def _assign_need_grades_by_percentile(graded: List[Dict]) -> None:
    """Rebalance Need grades across the league using percentile distribution.

    Most teams' raw alignment scores cluster in the same band, so absolute
    bands keep producing a wall of 3s. Percentile-redistribute so we get
    real differentiation. Teams with no stated needs (alignment=None) keep
    a neutral 3.
    """
    scored = [r for r in graded if r.get('need_alignment_score') is not None]
    if not scored:
        return
    scored.sort(key=lambda r: -r['need_alignment_score'])
    n = len(scored)
    cut5 = round(n * 0.15)
    cut4 = round(n * 0.37)
    cut3 = round(n * 0.63)
    cut2 = round(n * 0.85)
    cut5 = max(cut5, 1) if n >= 5 else cut5
    cut4 = max(cut4, cut5 + 1) if n >= 5 else cut4
    cut3 = max(cut3, cut4 + 1) if n >= 5 else cut3
    cut2 = max(cut2, cut3 + 1) if n >= 5 else cut2
    for i, r in enumerate(scored):
        if i < cut5:
            r['need_grade'] = 5
        elif i < cut4:
            r['need_grade'] = 4
        elif i < cut3:
            r['need_grade'] = 3
        elif i < cut2:
            r['need_grade'] = 2
        else:
            r['need_grade'] = 1


def _assign_final_grades_by_percentile(graded: List[Dict]) -> None:
    """Force a 1-5 distribution across the league so the heat map is colorful.

    Distribution targets (of teams that participated):
       top 15%   → 5
       next 22%  → 4
       middle 26% → 3
       next 22%  → 2
       bottom 15% → 1

    For 27 graded teams: ~4 fives, ~6 fours, ~7 threes, ~6 twos, ~4 ones.
    Mutates each review dict in-place to set 'final_grade'. Tie-break by
    raw weighted score, then sub-grade sum, then value grade.
    """
    if not graded:
        return
    scored = []
    for r in graded:
        raw = _raw_score(r['value_grade'], r['need_grade'], r['talent_grade'])
        r['_raw_score'] = raw
        scored.append(r)
    scored.sort(key=lambda r: (
        -r['_raw_score'],
        -(r['value_grade'] + r['need_grade'] + r['talent_grade']),
        -r['value_grade'],
    ))
    n = len(scored)
    cut5 = round(n * 0.15)
    cut4 = round(n * 0.37)
    cut3 = round(n * 0.63)
    cut2 = round(n * 0.85)
    # Guard against tiny leagues — make sure each band has at least one slot
    # if there's room.
    cut5 = max(cut5, 1) if n >= 5 else cut5
    cut4 = max(cut4, cut5 + 1) if n >= 5 else cut4
    cut3 = max(cut3, cut4 + 1) if n >= 5 else cut3
    cut2 = max(cut2, cut3 + 1) if n >= 5 else cut2
    for i, r in enumerate(scored):
        if i < cut5:
            r['final_grade'] = 5
        elif i < cut4:
            r['final_grade'] = 4
        elif i < cut3:
            r['final_grade'] = 3
        elif i < cut2:
            r['final_grade'] = 2
        else:
            r['final_grade'] = 1


# ── Orchestrator ────────────────────────────────────────────────────────────

def get_team_picks(conn, team_id: int, year: int = 2026, nml_lookup: Optional[Dict[int, Dict]] = None) -> List[Dict]:
    """Return the team's draft picks with all data needed for grading.

    Joins draft_selections → draft_picks → players → draft_prospects (by name).
    Each pick dict includes: overall_pick, round, pick_in_round, player_id,
    player_name, position (prospect bucket if available, else player), nml_rank,
    nfl_consensus_rank, nfl_actual_slot, value_delta, prospect_id.
    """
    if nml_lookup is None:
        nml_lookup = compute_nml_adjusted_ranks(conn, year)
    # Build a name index for prospect lookup using normalized names so suffix
    # variants (Jr./Sr./II/III) and punctuation differences (C.J. vs CJ) match.
    by_name = {}
    for r in nml_lookup.values():
        by_name[normalize_name(r['name'])] = r

    c = conn.cursor()
    c.execute("""
        SELECT
            dp.overall_order, dp.round, dp.round_order,
            ds.player_id, p.first_name, p.last_name, p.position AS player_pos
        FROM draft_selections ds
        JOIN draft_picks dp ON dp.id = ds.draft_pick_id
        LEFT JOIN players p ON p.id = ds.player_id
        WHERE ds.team_id = ? AND dp.year = ?
        ORDER BY dp.overall_order
    """, (team_id, year))

    picks = []
    for overall, rd, rd_order, player_id, fn, ln, ppos in c.fetchall():
        full_name = f"{fn or ''} {ln or ''}".strip()
        prospect = by_name.get(normalize_name(full_name)) if full_name else None

        if prospect:
            position = prospect['position']
            cons_rank = prospect['consensus_rank']
            nml_rank = prospect['nml_rank']
            nfl_slot = prospect['nfl_overall']
            prospect_id = prospect['id']
        else:
            position = ppos or '?'
            cons_rank = None
            nml_rank = None
            nfl_slot = None
            prospect_id = None

        delta = compute_value_delta(overall, nml_rank)

        picks.append({
            'overall_pick': overall,
            'round': rd,
            'pick_in_round': rd_order,
            'player_id': player_id,
            'player_name': full_name or '(write-in)',
            'position': position,
            'prospect_id': prospect_id,
            'consensus_rank': cons_rank,
            'nml_rank': nml_rank,
            'nfl_consensus_rank': cons_rank,
            'nfl_actual_slot': nfl_slot,
            'value_delta': delta,
        })
    return picks


def get_team_needs(conn, team_id: int) -> List[Dict]:
    """Return the team's stated needs board (raw — not used for grading)."""
    c = conn.cursor()
    c.execute("""
        SELECT item_type, item_key, tier, tier_order
        FROM team_needs WHERE team_id = ?
        ORDER BY tier_order
    """, (team_id,))
    return [
        {'item_type': r[0], 'item_key': r[1], 'tier': r[2], 'tier_order': r[3]}
        for r in c.fetchall()
    ]


def infer_team_needs(conn, team_id: int,
                     starter_floor: int = STARTER_OVR_FLOOR,
                     no_starter_floor: int = NO_STARTER_FLOOR) -> List[Dict]:
    """Auto-derive position-group needs from roster ratings.

    Counts starter-quality players (OVR ≥ starter_floor) in each broad
    position group. If a group has fewer credible starters than its slot
    count, it's flagged as a need. If the group's top player is below
    no_starter_floor, it's high need regardless of count.

    Excludes rookies (NULL overall_rating) since they haven't been rated yet.

    Returns: [{item_type:'position', item_key:<group>, tier:'high'|'medium',
               tier_order:i, inferred:True, starter_count, top_ovr}]
    """
    c = conn.cursor()
    c.execute("""
        SELECT position, overall_rating
        FROM players
        WHERE nml_team_id = ? AND overall_rating IS NOT NULL
    """, (team_id,))

    starter_count = defaultdict(int)
    top_ovr = defaultdict(int)
    for pos, ovr in c.fetchall():
        grp = PROSPECT_TO_GROUP.get(pos)
        if not grp or grp not in POSITION_GROUP_STARTERS:
            continue
        if ovr >= starter_floor:
            starter_count[grp] += 1
        if ovr > top_ovr[grp]:
            top_ovr[grp] = ovr

    inferred = []
    order = 0
    for grp, slots_needed in POSITION_GROUP_STARTERS.items():
        sc = starter_count.get(grp, 0)
        top = top_ovr.get(grp, 0)
        gap = slots_needed - sc

        # High need if no real starter at the group
        if top < no_starter_floor:
            tier = 'high'
        elif gap >= 2:
            tier = 'high'
        elif gap == 1:
            tier = 'medium'
        else:
            continue  # not a need

        inferred.append({
            'item_type': 'position',
            'item_key': grp,
            'tier': tier,
            'tier_order': order,
            'inferred': True,
            'starter_count': sc,
            'top_ovr': top,
            'slots_needed': slots_needed,
        })
        order += 1
    return inferred


# Starter quality is driven by NFL DRAFT POSITION, not NML draft slot — that's
# how EA Madden assigns initial rookie OVR. Per Jon: R1 picks land 75+, R2 picks
# 70-76 (only start if team has a real gap at the position), R3+ picks usually
# fall to backup quality (<72) — except IOL where R3 still credibly starts
# because the league tolerates lower OVR at interior OL.
#
# 'always_max_round': latest NFL round at which a pick unconditionally counts
#                     as a starter regardless of roster context.
# 'conditional_round': NFL round at which a pick counts as a starter ONLY if
#                      the team had a real roster gap at that group pre-draft.
#                      None = no conditional bump.
STARTER_RULES = {
    'QB':   {'always_max_round': 1, 'conditional_round': None},
    'WR':   {'always_max_round': 1, 'conditional_round': 2},
    'CB':   {'always_max_round': 1, 'conditional_round': 2},
    'TE':   {'always_max_round': 1, 'conditional_round': 2},
    'RB':   {'always_max_round': 1, 'conditional_round': 2},
    'EDGE': {'always_max_round': 1, 'conditional_round': 2},
    'LB':   {'always_max_round': 1, 'conditional_round': 2},
    'S':    {'always_max_round': 1, 'conditional_round': 2},
    'OT':   {'always_max_round': 2, 'conditional_round': 3},
    'DT':   {'always_max_round': 2, 'conditional_round': 3},
    'IOL':  {'always_max_round': 3, 'conditional_round': None},
}

# A top-50 consensus prospect who fell to a later NFL round gets bumped one tier
# up in starter likelihood (the "split the difference" case Jon described).
CONSENSUS_RESCUE_THRESHOLD = 50


def nfl_round_from_overall(nfl_overall: Optional[int]) -> Optional[int]:
    """Convert NFL overall pick number to NFL round (None if no slot)."""
    if not nfl_overall:
        return None
    if nfl_overall <= 32:  return 1
    if nfl_overall <= 64:  return 2
    if nfl_overall <= 100: return 3
    if nfl_overall <= 140: return 4
    if nfl_overall <= 181: return 5
    if nfl_overall <= 216: return 6
    return 7


def project_rookie_ovr(nfl_round: Optional[int], consensus_rank: Optional[int]) -> int:
    """Approximate the OVR EA Madden would assign this rookie at season start.

    Calibrated against actual Madden 26 launch ratings for the 2025 rookie
    class:
      - Travis Hunter (gen dual-pos, NFL #2, cons top-3) = 84 OVR — outlier ceiling
      - Top-3 consensus + NFL R1 typical = 81-83 (Carter 81, Jeanty 83)
      - Top-10 + NFL R1 = 79-80 (Graham 80, Walker 79, Campbell 79)
      - Top-25 + NFL R1 = 77-78 (Membou 77, Booker 77, Barron 78)
      - NFL R1 outside top-50 cons drops fast (Cam Ward 72 from NFL #1)
      - NFL R2 typical = 73-75 (Schwesinger 75, Tuten 75)
      - NFL R3 typical = 71-73
      - UDFA = low 60s
    """
    if nfl_round is None:
        if consensus_rank and consensus_rank <= 30:
            return 67
        return 60

    base_by_round = {1: 76, 2: 73, 3: 71, 4: 69, 5: 67, 6: 65, 7: 63}
    base = base_by_round.get(nfl_round, 63)

    # Consensus rank bumps — wider range to capture top-3 outliers like Hunter.
    if consensus_rank is not None:
        if consensus_rank <= 3:    base += 7    # generational tier (84 ceiling)
        elif consensus_rank <= 10: base += 4
        elif consensus_rank <= 25: base += 2
        elif consensus_rank <= 50: base += 1
        elif consensus_rank > 200: base -= 3    # deep falls take bigger hit
        elif consensus_rank > 100: base -= 2

    return max(55, min(84, base))


def starter_tier(pick: Dict, group_has_gap: bool) -> str:
    """Classify a pick as 'always_starter', 'conditional_starter', or 'backup'.

    'always_starter' = fills a starter slot regardless of roster context.
    'conditional_starter' = counts as a starter only because the roster had a gap.
    'backup' = doesn't fill a starter slot.

    Top-50 consensus prospects who fell to a later NFL round get rescued one
    tier (e.g. NFL R3 with consensus #20 → bumped from backup to conditional).
    """
    pos = pick.get('position', '')
    grp = PROSPECT_TO_GROUP.get(pos, pos)
    rules = STARTER_RULES.get(grp)
    if rules is None:
        return 'backup'  # K, P, LS — no starter inference

    nfl_rd = nfl_round_from_overall(pick.get('nfl_actual_slot'))
    cons = pick.get('consensus_rank')

    if nfl_rd is None:
        return 'backup'  # UDFA / unranked

    # Consensus rescue: top-50 prospect bumps the effective round up by one.
    effective_rd = nfl_rd
    if cons is not None and cons <= CONSENSUS_RESCUE_THRESHOLD and nfl_rd > rules['always_max_round']:
        effective_rd = nfl_rd - 1

    if effective_rd <= rules['always_max_round']:
        return 'always_starter'
    if rules['conditional_round'] is not None and effective_rd == rules['conditional_round']:
        return 'conditional_starter' if group_has_gap else 'backup'
    return 'backup'


def count_starter_fills(picks: List[Dict],
                        gap_groups: Optional[set] = None) -> Dict[str, int]:
    """Count how many starter slots each position group got filled by the draft.

    Uses NFL slot via STARTER_RULES. `gap_groups` is the set of position groups
    where the team had a roster gap pre-draft — required for conditional
    starters to count (R2 picks at most positions, R3 OT/DT, etc.).
    """
    if gap_groups is None:
        gap_groups = set()
    fills: Dict[str, int] = defaultdict(int)
    for p in picks:
        pos = p.get('position', '')
        grp = PROSPECT_TO_GROUP.get(pos, pos)
        tier = starter_tier(p, group_has_gap=(grp in gap_groups))
        if tier in ('always_starter', 'conditional_starter'):
            fills[grp] += 1
    return dict(fills)


def position_volume(picks: List[Dict]) -> Dict[str, int]:
    """Count picks per position group — used for "way more than normal" callouts.

    Per Jon: 3+ picks at a single position group is a notable concentration
    worth flagging in the blurb.
    """
    counts: Dict[str, int] = defaultdict(int)
    for p in picks:
        pos = p.get('position') or ''
        grp = PROSPECT_TO_GROUP.get(pos, pos)
        if grp in POSITION_GROUP_STARTERS:
            counts[grp] += 1
    return {k: v for k, v in counts.items() if v >= 3}


def compute_unfilled_needs(picks: List[Dict], team_needs: List[Dict]) -> List[str]:
    """Return list of position-need labels NOT credibly filled by the draft.

    Uses NFL-slot-based starter logic. A pick fills a need only if it qualifies
    as a starter (always_starter or conditional_starter where the team had a
    gap at the position pre-draft). UDFAs, unranked write-ins, and late-round
    picks at premium positions don't cancel needs.

    Only considers position-type needs at high or medium tier.
    """
    # Pre-draft gap groups = set of position groups in the needs list
    gap_groups = {
        PROSPECT_TO_GROUP.get(n['item_key'], n['item_key'])
        for n in team_needs
        if n.get('item_type') == 'position' and n.get('tier') in ('high', 'medium')
    }
    fills = dict(count_starter_fills(picks, gap_groups=gap_groups))

    out: List[str] = []
    sorted_needs = sorted(
        [n for n in team_needs
         if n.get('item_type') == 'position'
         and n.get('tier') in ('high', 'medium')],
        key=lambda n: (0 if n.get('tier') == 'high' else 1, n.get('tier_order', 99)),
    )
    for n in sorted_needs:
        grp = PROSPECT_TO_GROUP.get(n['item_key'], n['item_key'])
        if fills.get(grp, 0) > 0:
            fills[grp] -= 1
            continue
        out.append(n['item_key'])
    return out


def find_best_and_worst_pick(picks: List[Dict]) -> Tuple[Optional[int], Optional[int]]:
    """Return (best_overall_pick, worst_overall_pick) by value delta.

    Falls back to None if no picks have a delta (all unranked).
    """
    ranked = [p for p in picks if p.get('value_delta') is not None]
    if not ranked:
        return (None, None)
    best = max(ranked, key=lambda p: (p['value_delta'], -_round_weight(p['round'] or 7)))
    worst = min(ranked, key=lambda p: (p['value_delta'], _round_weight(p['round'] or 7)))
    return (best['overall_pick'], worst['overall_pick'])


def compute_team_review(conn, team_id: int, year: int = 2026,
                        nml_lookup: Optional[Dict[int, Dict]] = None) -> Dict:
    """Compute the full review for a single team. Returns a dict matching the
    draft_review_team_grades + draft_review_picks shapes (numbers only — prose
    fields are left blank for human authoring).

    Teams that traded out of every pick are flagged 'did_not_participate' and
    receive no numeric grade — they show up as a 'Did Not Participate' card
    instead of being graded against teams that drafted.
    """
    if nml_lookup is None:
        nml_lookup = compute_nml_adjusted_ranks(conn, year)

    picks = get_team_picks(conn, team_id, year, nml_lookup)
    # Use ROSTER-INFERRED needs for grading (per Jon: stated needs board may
    # have been edited mid-draft; roster ratings are ground truth).
    needs = infer_team_needs(conn, team_id)

    if not picks:
        # Team traded all their picks — no grading. Per Jon: NML teams often
        # trade for needs anyway; absence of picks is a strategic choice.
        return {
            'team_id': team_id,
            'did_not_participate': True,
            'value_grade': None,
            'need_grade': None,
            'talent_grade': None,
            'final_grade': None,
            'best_pick_overall': None,
            'worst_pick_overall': None,
            'inferred_needs': needs,
            'unfilled_needs': [n['item_key'] for n in needs
                              if n.get('tier') in ('high', 'medium')],
            'picks': [],
        }

    value_g = compute_value_grade(picks)
    need_g = compute_need_grade(picks, needs)
    need_score = compute_need_alignment_score(picks, needs)
    talent_g = compute_talent_grade(picks)
    final_g = compute_final_grade(value_g, need_g, talent_g)
    best, worst = find_best_and_worst_pick(picks)
    unfilled = compute_unfilled_needs(picks, needs)

    pos_volume = position_volume(picks)

    return {
        'team_id': team_id,
        'did_not_participate': False,
        'value_grade': value_g,
        'need_grade': need_g,
        'need_alignment_score': need_score,
        'talent_grade': talent_g,
        'final_grade': final_g,
        'best_pick_overall': best,
        'worst_pick_overall': worst,
        'inferred_needs': needs,
        'unfilled_needs': unfilled,
        'position_volume': pos_volume,
        'picks': picks,
    }


def compute_full_league_review(conn, year: int = 2026) -> List[Dict]:
    """Compute reviews for all 32 teams + assign league_rank.

    Returns list ordered by league_rank ascending.
    """
    nml_lookup = compute_nml_adjusted_ranks(conn, year)

    c = conn.cursor()
    c.execute("SELECT id, short_name FROM teams ORDER BY id")
    team_rows = c.fetchall()

    reviews = []
    for tid, sname in team_rows:
        r = compute_team_review(conn, tid, year, nml_lookup)
        r['short_name'] = sname
        reviews.append(r)

    # Split graded vs DNP so DNP teams sit at the bottom without league_rank.
    graded = [r for r in reviews if not r.get('did_not_participate')]
    dnp = [r for r in reviews if r.get('did_not_participate')]

    # Percentile-redistribute Need grade FIRST (raw alignment scores cluster
    # tightly so absolute bands don't differentiate), then re-roll the final
    # grade using the new Need values + percentile-redistribute.
    _assign_need_grades_by_percentile(graded)
    _assign_final_grades_by_percentile(graded)

    graded.sort(key=lambda r: (
        -r['final_grade'],
        -r.get('_raw_score', 0),
        -(r['value_grade'] + r['need_grade'] + r['talent_grade']),
        -r['value_grade'],
    ))
    for i, r in enumerate(graded, start=1):
        r['league_rank'] = i
        r.pop('_raw_score', None)

    # DNP teams: no rank, sorted alphabetically for stable display.
    dnp.sort(key=lambda r: r.get('short_name', ''))
    for r in dnp:
        r['league_rank'] = None

    return graded + dnp
