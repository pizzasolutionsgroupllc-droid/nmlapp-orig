#!/usr/bin/env python3
"""
generate_starter_analysis.py
Generates STARTER QUALITY + SUCCESSION ANALYSIS for opus_session_input.md.

Key design decisions:
  - Positional POOLS: positions are interchangeable within a group.
      OT pool:   LT + RT  (best 2 start regardless of side)
      G pool:    LG + RG
      EDGE pool: LEDGE + REDGE
      LB pool:   MIKE + WILL + SAM + MLB + OLB  (top 2 start in 4-2 Nickel)
      S pool:    FS + SS
  - Starter = highest-OVR player in the pool, NOT avg of all players
  - Formation default: Shotgun 3WR offense + 4-2 Nickel defense
    (overridden per-team by depth_chart_defaults)
  - years_pro drives breakout window detection
  - Position-specific age cliffs flag succession risk

Output: imports/starter_quality_analysis.md
Append this to opus_session_input.md — never overwrites existing content.

Usage:
    python3 scripts/generate_starter_analysis.py
"""

import sqlite3
import os
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB   = os.path.join(ROOT, 'data', 'nml.db')
OUT  = os.path.join(ROOT, 'imports', 'starter_quality_analysis.md')

# ── Position pools (positions are interchangeable within each group) ──────────
# Format: pool_key → list of DB position strings
POOLS = {
    'OT':   ['LT', 'RT'],
    'G':    ['LG', 'RG'],
    'EDGE': ['LEDGE', 'REDGE'],
    'LB':   ['MIKE', 'WILL', 'SAM', 'MLB', 'OLB'],
    'S':    ['FS', 'SS'],
}

# ── Starter OVR thresholds (flag as NEED if below) ───────────────────────────
# 4-2 Nickel: 2 LBs, 3 CBs, 2 safeties on field
# Shotgun 3WR: 3 WRs, 1 TE, 1 HB
NEED_THRESHOLD = {
    'QB':    80,
    'HB':    77,
    'WR1':   82,
    'WR2':   78,
    'WR3':   74,
    'TE':    76,
    'OT1':   80,   # best tackle
    'OT2':   76,   # 2nd tackle (other side)
    'G1':    76,
    'G2':    72,
    'C':     74,
    'EDGE1': 82,   # best edge rusher
    'EDGE2': 76,   # 2nd edge (plays the other side)
    'DT1':   76,   # DT devalued in NML — cap concern score at 60
    'DT2':   72,
    'LB1':   76,
    'LB2':   74,
    'CB1':   78,
    'CB2':   76,
    'CB3':   72,   # nickel CB
    'S1':    78,
    'S2':    76,
}

# ── Age cliffs (by POOL key or single-position key) ──────────────────────────
AGE_CLIFF = {
    'QB':   31,
    'HB':   28,
    'WR':   30,
    'TE':   30,
    'OT':   32,
    'G':    32,
    'C':    32,
    'EDGE': 30,
    'DT':   31,
    'LB':   29,
    'CB':   30,
    'S':    30,
}

# ── Breakout windows ──────────────────────────────────────────────────────────
# (min_years_pro, max_years_pro, elite_ceiling_ovr, reason)
# years_pro=0 → completing Y1/entering Y2; yp=1 → entering Y3
# Only flags players BELOW ceiling (already elite = no breakout signal needed)
BREAKOUT = {
    'WR':   (0, 2, 88,
             "Y3 WR breakout is the single strongest development pattern in football. "
             "CeeDee Lamb, Tyreek Hill, Cooper Kupp, DeAndre Hopkins, Mike Evans all broke out Y3. "
             "Current OVR SIGNIFICANTLY understates likely end-of-season value."),
    'TE':   (0, 2, 86,
             "TE Y2 production jump averages +98.5%% — largest single-year leap of any position. "
             "Elite output typically maintained through age 30. Current OVR understates trajectory."),
    'EDGE': (0, 3, 86,
             "Pass rushers take 2-3 years to develop counter moves and hand technique. "
             "Breakout often visible before Madden OVR update reflects it."),
    'LB':   (0, 3, 84,
             "LB processing speed, gap recognition, and blitz timing develop sharply Y2-Y4."),
    'CB':   (0, 3, 84,
             "DB anticipation, press timing, and zone read skills develop significantly Y2-Y4."),
    'S':    (0, 3, 84,
             "Safety instincts and coverage recognition develop significantly Y2-Y4."),
    'QB':   (1, 4, 86,
             "QBs are the slowest developers in football. Pocket passer peak is 27-30. "
             "Y3-Y5 is when scheme comprehension and pressure reads fully click."),
    'HB':   (0, 1, 86,
             "HB peak is the earliest of any skill position — Y1-Y2 prime. "
             "Hard cliff begins at 28. Buy BEFORE Y2 breakout, sell BEFORE age 28."),
    'OT':   (0, 3, 84,
             "OL development is slow — technique and strength base take 2-3 years to solidify."),
}

DEV_LABEL = {0: '', 1: '★', 2: '★★ Superstar', 3: '★★★ X-Factor'}


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_pool(conn, team_id, positions, n=2):
    """Get top-n players from a position pool, sorted OVR desc.
    Age is computed dynamically from birth_date where available,
    falling back to the static age column from the Madden import."""
    ph = ','.join('?' * len(positions))
    return conn.execute(f'''
        SELECT first_name||" "||last_name AS name,
               position, overall_rating AS ovr,
               CASE
                 WHEN birth_date IS NOT NULL
                 THEN CAST((julianday('now') - julianday(birth_date)) / 365.25 AS INTEGER)
                 ELSE age
               END AS age,
               years_pro, dev_trait
        FROM players
        WHERE nml_team_id=? AND position IN ({ph})
          AND is_free_agent=0 AND overall_rating IS NOT NULL
        ORDER BY overall_rating DESC
        LIMIT ?
    ''', [team_id] + positions + [n]).fetchall()


def fmt(p, slot_key, pool_key):
    """Format one starter row with all flags."""
    if not p:
        return "⚠️ EMPTY"

    ovr   = p['ovr'] or 0
    age   = p['age'] or 0
    yp    = p['years_pro']
    dev   = p['dev_trait'] or 0
    pos   = p['position']
    name  = p['name']

    yr_label  = f"Y{yp + 1}" if yp is not None else "Yrs?"
    dev_label = DEV_LABEL.get(dev, '')
    pos_note  = f"({pos})" if pool_key in POOLS else ""   # show actual pos for pooled slots

    base = f"{name} {pos_note}| OVR {ovr} | age {age} | {yr_label}"
    if dev_label:
        base += f" | {dev_label}"

    flags = []

    # Aging flag
    cliff = AGE_CLIFF.get(pool_key, 99)
    if age >= cliff:
        flags.append(
            f"⚠️ AGING (age {age} ≥ {cliff} cliff) — "
            f"NML owners typically hold aging starters until OVR drops; "
            f"SELL HIGH window open NOW before market wakes up"
        )

    # Breakout flag (uses pool key for position matching)
    if yp is not None and pool_key in BREAKOUT:
        bmin, bmax, bceil, reason = BREAKOUT[pool_key]
        if bmin <= yp <= bmax and ovr < bceil:
            strength = "HIGH" if dev >= 2 else "MODERATE"
            flags.append(f"🚀 BREAKOUT WINDOW ({strength} confidence) — {reason}")

    result = base
    if flags:
        result += "\n         → " + "\n         → ".join(flags)
    return result


def is_need(p, slot_key):
    t = NEED_THRESHOLD.get(slot_key, 99)
    return (not p) or ((p['ovr'] or 0) < t)


def get_trade_block(conn, team_id):
    """Return all players on the trade block for this team.
    Age computed dynamically from birth_date, falling back to static age."""
    return conn.execute('''
        SELECT first_name||" "||last_name AS name,
               position, overall_rating AS ovr,
               CASE
                 WHEN birth_date IS NOT NULL
                 THEN CAST((julianday('now') - julianday(birth_date)) / 365.25 AS INTEGER)
                 ELSE age
               END AS age,
               years_pro, dev_trait, trade_block_note
        FROM players
        WHERE nml_team_id=? AND on_trade_block=1
          AND overall_rating IS NOT NULL
        ORDER BY overall_rating DESC
    ''', (team_id,)).fetchall()


def classify_block_player(p):
    """Return signal flags for a player listed on the trade block."""
    pos   = p['position']
    ovr   = p['ovr'] or 0
    age   = p['age'] or 0
    yp    = p['years_pro']
    dev   = p['dev_trait'] or 0

    # Map single position → pool key for cliff/breakout lookup
    pos_to_pool = {}
    for pool_key, positions in POOLS.items():
        for pos_ in positions:
            pos_to_pool[pos_] = pool_key
    pool_key = pos_to_pool.get(pos, pos)

    signals = []

    # Aging signal
    cliff = AGE_CLIFF.get(pool_key, 99)
    if age >= cliff:
        signals.append(f"AGING SELLER (age {age} ≥ {cliff} cliff) — owner trying to move before OVR drops")

    # Breakout window signal (owner undervaluing)
    if yp is not None and pool_key in BREAKOUT:
        bmin, bmax, bceil, _ = BREAKOUT[pool_key]
        if bmin <= yp <= bmax and ovr < bceil:
            strength = "HIGH" if dev >= 2 else "MODERATE"
            signals.append(f"🔥 BUY ALERT — listing breakout-window player ({strength} breakout confidence). "
                           f"Owner pricing at current OVR={ovr}; future value is significantly higher")

    # No red flags = owner has a specific acquisition target
    if not signals:
        signals.append("Actively seeking trade — owner has a specific acquisition goal")

    return signals


# ── Main ──────────────────────────────────────────────────────────────────────

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

teams = conn.execute('''
    SELECT t.id, t.full_name,
           dcd.default_offense, dcd.default_defense
    FROM teams t
    LEFT JOIN users u ON u.team_id = t.id
    LEFT JOIN depth_chart_defaults dcd ON dcd.user_id = u.id
    ORDER BY t.full_name
''').fetchall()

out = []
out += [
    "# STARTER QUALITY + SUCCESSION ANALYSIS",
    f"*Generated {date.today().isoformat()} — re-run script to refresh; do NOT edit manually*",
    "",
    "## Methodology",
    "- **Starter** = highest-OVR player at each position (not average across all players)",
    "- **Positional pools** — positions are interchangeable within each group:",
    "  - OT pool: LT + RT (best 2 start regardless of side)",
    "  - G pool: LG + RG",
    "  - EDGE pool: LEDGE + REDGE (best edge rusher plays either side)",
    "  - LB pool: MIKE + WILL + SAM + MLB + OLB (top 2 start in 4-2 Nickel)",
    "  - S pool: FS + SS (top 2 safeties start regardless of label)",
    "  - Example: team with REDGE 93 + REDGE 90 + LEDGE 65 has NO edge need —",
    "    the second REDGE (90) simply starts at LE instead",
    "- **Formation defaults**: Shotgun 3WR offense + 4-2 Nickel defense unless overridden",
    "- **NEED**: starter OVR below threshold for that slot in this formation",
    "- **⚠️ AGING**: at/past position-specific decline cliff — ok NOW but succession urgent",
    "  > NML market inefficiency: most owners hold aging starters until OVR visibly drops,",
    "  > then try to sell. This is a predictable delay — SELL before Madden punishes age.",
    "- **🚀 BREAKOUT WINDOW**: player in prime development years — current OVR understates",
    "  future value. Do NOT trade in this window unless return is elite.",
    "  > Target OPPONENTS' breakout-window players before they hit peak.",
    "- **Dev Trait**: ★ Star | ★★ Superstar (accelerated OVR growth) | ★★★ X-Factor (elite trajectory)",
    "",
    "---",
    "",
]

all_breakouts    = []   # for league-wide summary at end
all_block_market = []   # for league-wide trade block section

for team in teams:
    tid   = team['id']
    tname = team['full_name']
    off   = team['default_offense'] or 'Shotgun 3WR'
    defn  = team['default_defense'] or '4-2 Nickel'

    out.append(f"### {tname}")
    out.append(f"**Formation:** OFF={off} | DEF={defn}")
    out.append("")

    t_needs = []
    t_aging = []
    t_break = []
    t_block = get_trade_block(conn, tid)

    def row(label, p, slot_key, pool_key):
        out.append(f"  {label:<8} {fmt(p, slot_key, pool_key)}")
        if is_need(p, slot_key):
            t_needs.append(f"{slot_key}(OVR={(p['ovr'] if p else 'none')},need≥{NEED_THRESHOLD.get(slot_key,'?')})")
        if p:
            cliff = AGE_CLIFF.get(pool_key, 99)
            if (p['age'] or 0) >= cliff:
                t_aging.append(f"{slot_key}:{p['name']}({p['ovr']},age {p['age']})")
            yp = p['years_pro']
            if yp is not None and pool_key in BREAKOUT:
                bmin, bmax, bceil, _ = BREAKOUT[pool_key]
                if bmin <= yp <= bmax and (p['ovr'] or 0) < bceil:
                    t_break.append(f"{slot_key}:{p['name']}(OVR {p['ovr']},Y{yp+1})")
                    all_breakouts.append((tname, slot_key, p, pool_key))

    # ── OFFENSE ───────────────────────────────────────────────────────────────
    out.append("**Offense:**")

    qb = get_pool(conn, tid, ['QB'], 1)
    row('QB', qb[0] if qb else None, 'QB', 'QB')

    hb = get_pool(conn, tid, ['HB'], 1)
    row('HB', hb[0] if hb else None, 'HB', 'HB')

    wrs = get_pool(conn, tid, ['WR'], 4)
    row('WR1', wrs[0] if len(wrs) > 0 else None, 'WR1', 'WR')
    row('WR2', wrs[1] if len(wrs) > 1 else None, 'WR2', 'WR')
    row('WR3', wrs[2] if len(wrs) > 2 else None, 'WR3', 'WR')

    te = get_pool(conn, tid, ['TE'], 1)
    row('TE', te[0] if te else None, 'TE', 'TE')

    ots = get_pool(conn, tid, POOLS['OT'], 2)
    row('OT1', ots[0] if len(ots) > 0 else None, 'OT1', 'OT')
    row('OT2', ots[1] if len(ots) > 1 else None, 'OT2', 'OT')

    gs = get_pool(conn, tid, POOLS['G'], 2)
    row('G1', gs[0] if len(gs) > 0 else None, 'G1', 'G')
    row('G2', gs[1] if len(gs) > 1 else None, 'G2', 'G')

    c = get_pool(conn, tid, ['C'], 1)
    row('C', c[0] if c else None, 'C', 'C')

    out.append("")

    # ── DEFENSE (4-2 Nickel) ──────────────────────────────────────────────────
    out.append("**Defense (4-2 Nickel):**")

    edges = get_pool(conn, tid, POOLS['EDGE'], 2)
    row('EDGE1', edges[0] if len(edges) > 0 else None, 'EDGE1', 'EDGE')
    row('EDGE2', edges[1] if len(edges) > 1 else None, 'EDGE2', 'EDGE')

    dts = get_pool(conn, tid, ['DT'], 2)
    row('DT1', dts[0] if len(dts) > 0 else None, 'DT1', 'DT')
    row('DT2', dts[1] if len(dts) > 1 else None, 'DT2', 'DT')

    lbs = get_pool(conn, tid, POOLS['LB'], 2)
    row('LB1', lbs[0] if len(lbs) > 0 else None, 'LB1', 'LB')
    row('LB2', lbs[1] if len(lbs) > 1 else None, 'LB2', 'LB')

    cbs = get_pool(conn, tid, ['CB'], 4)
    row('CB1', cbs[0] if len(cbs) > 0 else None, 'CB1', 'CB')
    row('CB2', cbs[1] if len(cbs) > 1 else None, 'CB2', 'CB')
    row('CB3', cbs[2] if len(cbs) > 2 else None, 'CB3', 'CB')

    ss = get_pool(conn, tid, POOLS['S'], 2)
    row('S1', ss[0] if len(ss) > 0 else None, 'S1', 'S')
    row('S2', ss[1] if len(ss) > 1 else None, 'S2', 'S')

    out.append("")

    # ── Summary ───────────────────────────────────────────────────────────────
    out.append("**Summary:**")
    if t_needs:
        out.append(f"  NEEDS:    {' | '.join(t_needs)}")
    else:
        out.append("  NEEDS:    None — all starter slots above threshold")
    if t_aging:
        out.append(f"  AGING:    {' | '.join(t_aging)} — SELL HIGH before market wakes up")
    if t_break:
        out.append(f"  BREAKOUT: {' | '.join(t_break)} — hold; OVR understates value")

    # Trade block — cross-referenced with aging/breakout flags
    if t_block:
        out.append("  TRADE BLOCK:")
        for bp in t_block:
            dev_s = {0:'', 1:'★', 2:'★★ Superstar', 3:'★★★ X-Factor'}.get(bp['dev_trait'] or 0, '')
            note  = f" | note: \"{bp['trade_block_note']}\"" if bp['trade_block_note'] else ""
            base  = f"    {bp['name']} ({bp['position']}, OVR {bp['ovr']}, age {bp['age']}){' '+dev_s if dev_s else ''}{note}"
            out.append(base)
            for sig in classify_block_player(bp):
                out.append(f"      → {sig}")
            all_block_market.append((tname, bp))

    out.append("")
    out.append("---")
    out.append("")


# ── League-wide trade block market ───────────────────────────────────────────
out += [
    "## LEAGUE-WIDE TRADE BLOCK MARKET",
    "*All players currently listed for trade across the league.*",
    "*Cross-referenced with aging cliffs and breakout windows — the most actionable intel.*",
    "",
    "| Team | Player | Pos | OVR | Age | Yr | Dev | Signal | Ask |",
    "|------|--------|-----|-----|-----|----|-----|--------|-----|",
]

# Sort: breakout buys first (🔥), then aging sellers, then neutral
def block_sort(e):
    tname, bp = e
    sigs = classify_block_player(bp)
    has_buy    = any('BUY ALERT' in s for s in sigs)
    has_aging  = any('AGING' in s for s in sigs)
    dev = bp['dev_trait'] or 0
    return (0 if has_buy else (1 if has_aging else 2), -dev, -(bp['ovr'] or 0))

all_block_market.sort(key=block_sort)

for tname, bp in all_block_market:
    dev   = bp['dev_trait'] or 0
    yp    = bp['years_pro']
    yr    = f"Y{(yp or 0)+1}"
    dev_s = {0:'Normal', 1:'★ Star', 2:'★★ Superstar', 3:'★★★ X-Factor'}.get(dev,'?')
    sigs  = classify_block_player(bp)
    note  = bp['trade_block_note'] or '—'
    if any('BUY ALERT' in s for s in sigs):
        signal = "🔥 BUY (breakout window)"
    elif any('AGING' in s for s in sigs):
        signal = "⚠️ AGING SELLER"
    else:
        signal = "Actively seeking trade"
    out.append(f"| {tname} | {bp['name']} | {bp['position']} | {bp['ovr']} | {bp['age']} | {yr} | {dev_s} | {signal} | {note} |")

out += [
    "",
    "> **Reading the signals:**",
    "> - 🔥 BUY: owner listing a player in their breakout window — price reflects today's OVR, value will be higher",
    "> - ⚠️ AGING SELLER: owner trying to move before Madden punishes age — buy only at deep discount",
    "> - Actively seeking trade: owner has a specific acquisition target, may accept creative packages",
    "",
    "---",
    "",
]

# ── League-wide breakout buy targets ─────────────────────────────────────────
out += [
    "## LEAGUE-WIDE BREAKOUT BUY TARGETS",
    "*Players on other teams in their prime development window —*",
    "*buy BEFORE the owner realizes what they have (most will price based on current OVR).*",
    "",
    "| Team | Slot | Player | Pos | OVR | Age | Yr | Dev | Confidence |",
    "|------|------|--------|-----|-----|-----|----|-----|------------|",
]

def sort_key(e):
    tname, slot, p, pk = e
    return (-(p['dev_trait'] or 0), p['years_pro'] or 0)

all_breakouts.sort(key=sort_key)

for tname, slot, p, pk in all_breakouts:
    dev   = p['dev_trait'] or 0
    yp    = p['years_pro'] or 0
    dev_s = {0: 'Normal', 1: '★ Star', 2: '★★ Superstar', 3: '★★★ X-Factor'}.get(dev, '?')
    conf  = "HIGH" if dev >= 2 else "MODERATE"
    yr    = f"Y{yp+1}"
    out.append(f"| {tname} | {slot} | {p['name']} | {p['position']} | {p['ovr']} | {p['age']} | {yr} | {dev_s} | {conf} |")

out += [
    "",
    "> **Trade Strategy**: Price their players based on where they'll be in 1-2 seasons, not current OVR.",
    "> Most NML owners anchor to current rating — that's the gap you exploit.",
    "> Superstar/X-Factor dev = accelerated Madden OVR gains. Highest leverage targets.",
    "",
]

with open(OUT, 'w') as f:
    f.write('\n'.join(out))

print(f"✅ Written to {OUT}")
print("   Review, then append to opus_session_input.md")
conn.close()
