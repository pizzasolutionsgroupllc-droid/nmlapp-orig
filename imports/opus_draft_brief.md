# NML Draft Suggestion Engine — Opus Briefing

**Compiled:** April 18–19, 2026  
**Purpose:** Build a "Suggested Pick" panel for the NML Mock Draft page and eventually a live draft prediction model.  
**Also see:** `imports/nfl_nml_draft_comparison.md` — full NFL vs NML positional frequency comparison, 2019–2025.

---

## 0. Core Thesis — Why NFL Data Drives NML Value

**The prediction chain that underlies everything in this engine:**

```
Prospect's NFL performance → EA Madden weekly roster updates → Player's in-game rating → NML value
```

Madden ratings are not invented. EA updates player ratings throughout the season based on real NFL performance — each week's ratings patch reflects what that player did in actual games. A rookie who earns a starting role and plays well in the NFL will see their Madden rating climb from their launch-week baseline (typically 70–76 OVR) toward 80+ within 1–2 seasons. A bust who sits on the bench or underperforms stays low and stagnates.

**This means projecting NFL success IS projecting future Madden ratings.** The entire analytical framework — combine metrics, college production, RAS scores, NFL draft capital, historical comp studies — exists to answer one question: *will this player perform well enough in the NFL that EA gives them a high Madden rating in 2–4 years?*

This is why:
- NFL combine data matters: athleticism correlates with NFL performance, which correlates with future Madden ratings
- School and draft position matter: first-round NFL picks get roster spots and reps; later picks often don't
- Historical prospect comps matter: if a player profile historically produces starting-caliber NFL players, they will likely receive consistently rising Madden ratings
- Madden position multipliers matter: even a highly-rated player at OT contributes less to NML wins than a highly-rated WR or CB because of how Madden's engine weights positions

**The suggestion engine's job** is not to pick the "best football player" — it is to identify which available prospects are most likely to become high-rated, high-impact Madden players within the NML's planning horizon (1–4 seasons).

### How NML Actually Uses Madden Ratings (Critical Context)

The NML season is built on **Week 1 launch ratings** — the first official EA roster update when the new Madden game releases (typically August). This is the snapshot the league imports to start their franchise. Those ratings are then **soft-locked** for the rest of the NML season. EA's ongoing weekly NFL performance updates during the real NFL season do NOT affect NML player ratings in real-time.

**The rating timeline:**
```
NFL Draft (April) → Madden launches (August) → EA Week 1 ratings → NML season starts
                                                       ↑
                                          This is what NML uses
```

**What this means for the development model:**
- The OVR ratings currently in the NML database are **end-of-season ratings** (post-Super Bowl EA update) — these reflect a full season of NFL performance and are higher than what players launch at
- Week 1 (launch) ratings for NFL rookies are typically **5–8 OVR points lower** than their end-of-season rating
- Example: A top-10 NFL pick averaging ~80 OVR in the database likely launched at ~73–76 OVR in Week 1
- For NML draft planning, the relevant question is: *what will this prospect's Week 1 rating be when M27 launches in August 2026?*

**In-franchise rating changes (within NML season):**
The Madden franchise mode has mechanics that independently adjust ratings from EA's external updates:
- Team morale bonus (winning): up to +5 OVR to individual players over a full season
- Individual performance bonus (high stats): up to +5 OVR for that player
- Pro Bowl / All-Pro level performance: up to another +5 OVR
- **Max in-franchise boost: ~+15 OVR** over a full NML regular season
- These changes are amplified by dev trait + age: young players with Superstar/X-Factor dev traits improve fastest; older players with Normal dev improve least or stagnate

**Dev traits** (assigned by EA at launch, not known in advance for 2026 prospects):
- X-Factor / Superstar dev → fastest rating growth, biggest in-franchise bonuses
- Star dev → moderate growth
- Normal dev → slowest growth, smallest bonuses
- Historical pattern: top-10 NFL picks tend to receive Superstar or X-Factor dev traits; late-round picks usually get Normal

**Bottom line for the suggestion engine:** When evaluating a prospect, think in two time horizons:
1. **Immediate (Year 1 NML):** What will their Week 1 launch rating be? This determines their Day 1 value.
2. **Long-term (Year 2-4 NML):** What will their end-of-season trajectory look like after proving themselves in the NFL?

---

## 1. What You're Building

The NML league needs a **draft suggestion engine** with two modes:

### Mode A — "Suggested Pick" Panel (implement first)
When a commissioner or owner is on the Mock Draft page and it's a team's pick, the system should suggest the **best available player** for that team. The suggestion should consider:
- Team's current roster weakness by position
- Historical drafting tendencies of that team
- Position scarcity in the league
- Speed premium (this league drafts speed aggressively)
- The prospect's grade/rank

### Mode B — Pick Prediction (live draft, future)
During a live draft, predict what team X will likely pick next based on their historical tendencies, remaining needs, and who's still available on the board.

---

## 2. League Context

- **Format:** Madden NFL franchise simulation league, 32 NFL teams
- **Rosters:** Real NFL players — ratings, speed, age, dev traits all come from Madden
- **Draft:** NML draft mirrors the real NFL rookie class each year. League uses picks R2–R8 (Round 1 appears to be the "real" NFL draft import — existing rookies arrive on teams pre-drafted). Rounds labeled 2–8 with up to ~32 picks per round. Round 64 = undrafted/waiver adds.
- **Draft structure:** NML has R1–R8. The `players` table in the DB only captured R2–R8 historically (R1 rookies arrive pre-rostered from Madden's NFL import). The `NML Draft Histories.xlsx` file has full R1 data. Treat R2 as the first pick in the DB-driven history; use the xlsx for R1 context.
- **Season flow:** Rosters carry year to year. Draft classes in DB: 2022, 2023, 2025 (no 2024 in DB). Full history 2019–2025 in `NML Draft Histories.xlsx`.
- **Ownership note:** Teams may change owners 1–3 times per year (between offseason and draft day). Per-team tendencies reflect the team's draft history, not necessarily a single human decision-maker. Account for this when weighting tendency_score — it's directionally useful but noisy.
- **DB tables:** `players` (all rostered + rookies), `draft_prospects` (scouting board), `draft_picks` (future pick assets), `team_needs`, `depth_chart`

---

## 3. Historical Draft Patterns

### 3A. Most Drafted Positions (across R2–R8, all 3 drafts)

By total picks across all 3 years and all rounds:

| Position | ~Total Picks | Notes |
|----------|-------------|-------|
| WR | 68 | Most drafted skill position |
| CB | 73 | Most drafted defensive position |
| DT | 62 | High volume every round |
| HB | 39 | Goes early when available |
| LEDGE | 39 | Left edge, similar to REDGE |
| REDGE | 33 | Edge rushers targeted early |
| WILL | 31 | Weakside LB, volume in mid-rounds |
| LG/RG | ~30 | Guards picked throughout |
| TE | 31 | Consistent demand |
| QB | 29 | Stocked up across rounds |
| SS | 30 | Safety demand is high |
| FS | 18 | Less volume than SS |
| MIKE | 21 | Mid-round |
| RT/LT | ~20 each | OT picked mid-to-late |

### 3B. Position Flow by Round

**R2 (top picks, premium assets):**
- WR (15), QB (11), DT (11), LEDGE (10), CB (9), RT (8), LT (8) — premium positions dominate
- HB goes R2 when elite: avg OVR 89.3, avg speed 92.3

**R3:**
- CB (15), DT (13), WR (12), TE (9) — defense gets addressed
- HB still goes: avg OVR 80.0, speed 91.0
- SS shows up: avg OVR 79.8

**R4:**
- WR (17), CB (14), REDGE (9), RG (9), WILL (8), HB (8) — biggest round for WR/CB volume
- WILL LBs start coming: speed avg 87.9

**R5–R8:**
- WR and CB never stop being drafted (every round, every team)
- HB remains in demand through R6
- Kickers (K) appear in R5+, Punters (P) in R5+

### 3C. Speed Premium (critical insight)

This league **drafts speed aggressively**. Speed ratings hold across rounds for skill positions:

| Position | R2 avg speed | R4 avg speed | R6 avg speed | Trend |
|----------|-------------|-------------|-------------|-------|
| CB | 93.8 | 91.1 | 90.7 | High floor, stays premium |
| WR | 93.0 | 91.2 | 91.2 | Speed stable — very consistent |
| HB | 92.2 | 91.2 | 90.4 | Speed barely drops round to round |
| SS | — | 88.3 | 90.3 | Speed important at S |
| FS | 89.0 | 90.0 | 88.5 | High speed expected |
| WILL | — | 87.9 | 85.2 | Speed LBs valued |
| MIKE | 87.0 | 86.8 | 88.0 | Speed matters for ILBs too |
| QB | 86.6 | 87.3 | 82.7 | Mobile QBs go earlier |
| REDGE | 85.2 | 84.4 | 85.8 | EDGE speed < 83 is a reach |
| LEDGE | 86.6 | 84.0 | 84.4 | Same as REDGE |
| TE | 86.5 | 84.5 | 82.0 | Speed TE valued early |

**Key rule:** If a skill position player (WR/HB/CB) has speed ≥ 90, teams will reach for them. If a EDGE/LB has speed ≥ 87, they go earlier than OVR suggests.

### 3D. Madden Game Engine Context — Why NML Drafting Differs from NFL

**This is the most important section for calibrating the suggestion engine correctly.**

NML owners draft to win Madden games against each other, not to mirror real NFL roster-building. The Madden engine creates specific distortions that make NML draft logic rational even when it looks wrong vs NFL norms:

**Trench positions are correctly devalued in NML:**
- Offensive line play in Madden is notoriously unrealistic. Teams can win consistently even with mediocre OL ratings because the pass protection/run blocking simulation is not faithful to real football.
- Defensive tackles and interior pass rush have similarly diminished impact in Madden vs real life.
- The NFL vs NML comparison shows NML takes OT ~7.5% of R1 picks vs NFL's 15.1% — this is **not a blind spot**, it's correct calibration to the game engine. Do NOT treat OT/G/C/DT as "undervalued sleepers" in the suggestion engine.

**Speed is the dominant skill in Madden — backed by actual NML season stats:**

*M26 NML Receiving leaders (17-game season):*
- Brian Thomas Jr.: 146 rec, **2,902 yards**, 10.9 avg, 170.7 yd/game, **33 TD**
- Nico Collins: 83 rec, 2,119 yards, 25.5 avg, 124.6 yd/game, 21 TD

*M26 NML Rushing leaders:*
- Jahmyr Gibbs: 220 att, **2,628 yards, 11.9 YPC**, 30 TD, 187.7 yd/game — elite speed (96 spd in M26)
- Antonio Gibson: 287 att, 2,394 yards, 8.3 YPC, 34 TD
- Trey Benson: 278 att, 2,295 yards, 8.3 YPC, 38 TD
- Christian McCaffrey: 267 att, 2,219 yards, 8.3 YPC, 24 TD, 60 BTK, 754 YAC
- Josh Jacobs: 336 att, 2,122 yards, **6.3 YPC**, 23 TD, 89 BTK, 762 YAC — power back, lower speed

**What these stats tell us:**
- Gibbs (96 speed) averages 11.9 YPC. Jacobs (slower, power-oriented) averages 6.3 YPC with more carries — a near-2x efficiency gap explained almost entirely by speed rating.
- Brian Thomas Jr. at 2,902 receiving yards (170/game) is physically impossible in real football but achievable in Madden when a 95-speed WR routinely creates separation. This is the ceiling for what a top-tier speed WR can produce.
- The gap between Thomas (2,902 yds) and the next WR (2,119 yds) is enormous — elite speed WRs are a different asset class.

**Owner skill caveat:** Some NML owners are significantly better at Madden than others. A skilled owner can produce strong stats with average players, and a weaker owner can underperform with elite rosters. Treat season stats as directionally meaningful (speed = production) but not purely player-driven signal. Do not over-index on stats from any single team.

**Owner playstyle is a major variable — both in stats interpretation and draft suggestions:**

NML owners have distinct passing vs. rushing tendencies that significantly affect how their players perform and what positions they should prioritize in the draft. Confirmed examples from M26:

*Las Vegas Raiders (pass-first owner, Jon):*
- 6,130 passing / 1,714 rushing — ~78% pass rate
- 67 passing TD, 14 rushing TD
- 34.1 PPG
- De'von Achane (96 speed): 199 att, 1,397 yds, **7.0 YPC**, 13 TD — same speed tier as Gibbs but lower efficiency, largely because the offense doesn't run-block or call runs as a primary scheme

*Green Bay Packers (run-first owner):*
- 3,482 passing / 3,928 rushing — ~53% rush rate
- 35 passing TD, 51 rushing TD
- **38.3 PPG** — higher scoring than the pass-first team
- Rushing volume creates more TDs and first downs (353 vs Raiders' 344)

**What this means:**
- Both playstyles can win and score points at a high level in Madden
- The same player (speed HB) produces very differently depending on the owner's scheme — Achane at 7.0 YPC pass-first vs Gibbs at 11.9 YPC run-first illustrates this clearly
- Draft suggestions should be **playstyle-aware**: recommending a premium HB to a confirmed pass-first owner is lower value than recommending one to a run-first owner, even if the player is elite
- Conversely, pass-first owners should get WR/QB suggestions weighted even higher than the base algorithm

**Playstyle classification approach (derive from game stats when available):**
- Pass-first: team pass% > 60% → boost WR madden_value by +10, reduce HB by -10
- Balanced: 45–60% pass → no adjustment
- Run-first: pass% < 45% → boost HB madden_value by +10, reduce WR by -5
- This can eventually be pulled from season stats tables; for now treat as a manual input or derive from draft history (WR-heavy drafters are likely pass-first)

**Practical implication for the suggestion engine:**
The speed bonus in the algorithm should be significant and tiered. Trench positions should have a dampened game-impact weight. The model should optimize for winning Madden games, not building an NFL-realistic roster.

---

## 4. Position Scarcity (Current League-Wide)

How rare are good players at each position right now? "Elite" = OVR 85+, "Solid" = OVR 80+.

| Position | Total | Avg OVR | Max | Elite (85+) | Elite% | Solid (80+) |
|----------|-------|---------|-----|-------------|--------|-------------|
| LT | 58 | 76.7 | 97 | 15 | 25.9% | 22 |
| QB | 80 | 72.9 | 99 | 13 | 16.2% | 18 |
| MIKE | 76 | 74.0 | 97 | 10 | 13.2% | 21 |
| HB | 131 | 76.5 | 98 | 17 | 13.0% | 36 |
| C | 47 | 74.6 | 95 | 6 | 12.8% | 12 |
| WR | 224 | 75.5 | 99 | 27 | 12.1% | 54 |
| REDGE | 94 | 74.9 | 99 | 11 | 11.7% | 17 |
| FS | 70 | 76.0 | 94 | 8 | 11.4% | 20 |
| LEDGE | 95 | 74.9 | 97 | 9 | 9.5% | 22 |
| RT | 61 | 74.4 | 99 | 6 | 9.8% | 16 |
| RG | 69 | 73.9 | 95 | 7 | 10.1% | 12 |
| DT | 157 | 74.8 | 96 | 17 | 10.8% | 34 |
| TE | 96 | 73.5 | 98 | 9 | 9.4% | 19 |
| SS | 86 | 74.7 | 93 | 8 | 9.3% | 18 |
| CB | 229 | 74.5 | 97 | 21 | 9.2% | 45 |
| LG | 66 | 73.3 | 96 | 6 | 9.1% | 11 |
| WILL | 85 | 72.9 | 90 | 4 | 4.7% | 14 |
| SAM | 23 | 70.5 | 84 | 0 | 0% | 1 |

**Scarcity tiers — adjusted for Madden game impact (not just roster rarity):**

- **Tier 1 — High scarcity + high Madden impact:** QB (rare good ones + wins games), WR 90+ speed (game-breaking), HB 90+ speed (Gibbs-tier efficiency), CB (coverage wins pass-heavy Madden games)
- **Tier 2 — Meaningful scarcity + moderate Madden impact:** EDGE with speed ≥ 86 (pass rush affects gameplay), TE that catches (TE as receiving weapon), FS/SS with speed (coverage safeties matter), MIKE/WILL with speed (LBs that cover are useful)
- **Tier 3 — Scarce by OVR metrics but low Madden impact:** LT, OT, G, C, DT — these positions have the worst OVR-to-gameplay impact ratio. A team with a 65 OVR OT can still win if their skill positions are elite. Draft only for glaring gaps, not as a premium pick.
- **Special:** SAM — almost no elite players exist, but the position has limited Madden impact. Low priority.

**Insight:** QB scarcity is real AND game-impactful — a 72 OVR QB can be the difference between winning and losing in Madden. Speed WR scarcity drives the most production (see Section 3D stats). LT has high elite% numbers but low suggestion priority because Madden doesn't reward elite OT proportionally.

---

## 5. Per-Team Draft Tendencies

Key tendencies from 3 years of NML draft history (R2–R8):

| Team | Favorite Positions | Early Round Bias | Speed Focus | Notes |
|------|--------------------|-----------------|-------------|-------|
| Arizona Cardinals | CB (5), HB (3), WILL (3) | EDGE early | avg 84.0 | CB hoarders |
| Atlanta Falcons | LG (2), CB (2) | LG, WR | 77.5 | Low volume — few picks |
| Baltimore Ravens | WR (3), CB (3) | WR, CB early | 91.4 | High-speed drafters |
| Buffalo Bills | DT (6), REDGE (3), CB (3) | REDGE, RG | 80.5 | Defense-first |
| Carolina Panthers | WR (4), LEDGE (3), MIKE (2) | WR, HB, LEDGE | 88.3 | Speed-oriented |
| Chicago Bears | CB (6), REDGE (2), WR (2) | REDGE, RT, CB | 77.0 | CB hoarders, low speed |
| Cincinnati Bengals | CB (5), WR (4), DT (3) | WR, DT, LT | 83.2 | Balanced offense/defense |
| Cleveland Browns | CB (5), HB (4), MIKE (3) | LT, DT | 83.7 | Run-game focus |
| Dallas Cowboys | HB (4), CB (3), DT (2) | CB, RT | 83.0 | HB-focused |
| Denver Broncos | CB (4), TE (3), REDGE (3) | LT, DT | 79.9 | Trenches-first early |
| Detroit Lions | HB (4), RG (3), WR (3) | RG, LEDGE | 79.1 | OL-focused early rounds |
| Green Bay Packers | WR (4), HB (4), CB (4) | LEDGE, QB | 86.6 | Balanced, volume drafters |
| Houston Texans | WR (5), DT (5), HB (3) | REDGE, CB | 79.5 | WR + DT obsession |
| Indianapolis Colts | LT (3), WR (3), REDGE (2) | No early picks | N/A | Low pick capital |
| Jacksonville Jaguars | CB (4), DT (4), WR (3) | TE, CB, QB | 83.0 | Volume in all positions |
| Kansas City Chiefs | REDGE (3), DT (3), CB (2) | WR, REDGE, TE | 85.8 | Speed-focused despite trenches |
| Las Vegas Raiders | WR (4), MIKE (3), CB (3) | MIKE, RT | 84.6 | MIKE LB obsession |
| Los Angeles Chargers | DT (2), WR (2) | WR, DT, SS | 82.7 | Low pick count |
| Los Angeles Rams | DT (3), WR (3), HB (2) | DT, HB, RT | 80.6 | Run-D focused |
| Miami Dolphins | CB (3), REDGE (2), RG (2) | CB, WR, LT | 87.8 | Speed-heavy |
| Minnesota Vikings | WR (8), DT (4), HB (4) | REDGE | 90.0 | WR obsessed, very high volume |
| New England Patriots | CB (4), RG (4), DT (3) | WR, LEDGE, CB | 84.6 | Defense + OL |
| New Orleans Saints | WR (4), TE (2), HB (2) | RG, FS, LT | 78.0 | OL + pass catchers |
| New York Giants | DT (4), HB (3), SAM (2) | CB, C, LT | 80.0 | Interior defense |
| New York Jets | QB (2), LEDGE (2), CB (2) | WR, TE, DT | 86.5 | QB-needy, EDGE rush |
| Philadelphia Eagles | WR (2), TE (2), LG (2) | RT, LT | 66.0 | OL obsessed, low speed |
| Pittsburgh Steelers | WR (6), CB (3), WILL (3) | DT, CB, WR | 81.5 | WR-heavy, defense |
| San Francisco 49ers | HB (2), CB (2), RT (2) | LEDGE, HB | 85.0 | Speed EDGE early |
| Seattle Seahawks | CB (4), WR (3), TE (2) | WR, CB, LEDGE | 82.8 | Speed WR/CB combo |
| Tampa Bay Buccaneers | CB (5), WR (2), WILL (1) | CB, QB | 86.0 | CB hoarders |
| Tennessee Titans | LEDGE (3), LG (3), WR (3) | QB, LEDGE, LG | 84.6 | OL + EDGE |
| Washington Commanders | CB (4), WR (3), LG (3) | DT, LEDGE, CB | 83.4 | Defense + OL early |

**Top "CB hoarders":** Arizona (5), Chicago (6), Tampa Bay (5) — always take CBs when available  
**Top "WR obsessed":** Minnesota (8!), Pittsburgh (6), Houston (5)  
**Speed-first drafters (avg early speed ≥ 87):** Baltimore (91.4), Minnesota (90.0), Miami (87.8), Carolina (88.3)  
**OL-first drafters:** Philadelphia, Detroit, Tennessee, New Orleans

---

## 6. Pick Capital Summary (Future Picks Owned)

Teams with most draft capital (R1+R2 picks):

| Team | Total Future Picks | R1 Picks | R2 Picks | Assessment |
|------|-------------------|----------|----------|------------|
| Las Vegas Raiders | 33 | 16 | 7 | Massive capital — rebuild mode |
| New York Jets | 34 | 1 | 2 | Volume but not top picks |
| Cincinnati Bengals | 19 | 2 | 3 | Solid capital |
| Denver Broncos | 19 | 0 | 3 | No R1s |
| Detroit Lions | 22 | 1 | 3 | Balanced |
| Indianapolis Colts | 22 | 1 | 4 | Many R2s |
| Seattle Seahawks | 19 | 6 | 2 | R1 heavy |
| Washington Commanders | 21 | 4 | 3 | Strong capital |
| New Orleans Saints | 20 | 3 | 2 | Solid |
| Kansas City Chiefs | 12 | 4 | 1 | Quality > quantity |
| New York Giants | 1 | 0 | 0 | Virtually no capital |
| Minnesota Vikings | 3 | 1 | 2 | Very few picks |

---

## 7. Team Needs (From League DB)

Only 9 teams have needs formally logged. Use these as hard constraints when they exist; fall back to roster analysis for others.

Teams with logged needs in the DB (pull from `team_needs` table at runtime — `item_type='position'` and `tier` in `['high','medium','low']`).

---

## 8. Suggestion Algorithm Design

### Step 1: Score Each Available Prospect

For each prospect still available on the board, compute a **team-fit score** for the picking team:

```
fit_score = (need_score × 0.35) + (madden_value × 0.30) + (tendency_score × 0.20) + (player_quality × 0.15)
```

Note: `madden_value` replaces the old `scarcity_score` — it combines position game-impact with player-specific speed/ability. This is the key change from the original formula: the engine should optimize for Madden performance, not NFL roster-building logic.

**need_score** (0–100):
- If position is in team_needs with tier='high': 100
- If position is in team_needs with tier='medium': 70
- If team has < 2 players at that position on roster: 80
- If team has only 1 player at that position: 95
- If team has 0 starters ≥ 80 OVR at that position (for Tier 1/2 positions): 75
- OT/G/C/DT: cap need_score at 60 even if the team is thin — Madden doesn't punish trench weakness as much
- Otherwise: 30

**madden_value** (0–100) — replaces scarcity_score:

*Position impact multiplier (apply to base before speed adjustments):*
- QB: 0.95 — wins and losses turn on QB quality in Madden
- WR: 0.90 — highest game-impact when elite; WR carries drive stats
- HB: 0.85 — speed backs (Gibbs-tier) are game-breaking; power backs less so
- CB: 0.80 — coverage CBs directly affect whether the opponent can pass
- EDGE (speed ≥ 86): 0.70 — fast pass rushers affect gameplay
- TE: 0.65 — useful as receiving weapon, less so as blocker
- S (FS/SS): 0.65 — coverage safeties matter
- LB (MIKE/WILL/SAM): 0.55 — speed LBs useful in coverage, slow LBs limited
- EDGE (speed < 86): 0.45 — slower edge rushers have limited Madden impact
- DT: 0.35 — interior pass rush rarely game-changing in Madden engine
- OT/LT/RT: 0.30 — OL impact is severely muted in Madden; teams win with mediocre OT
- G/C: 0.25 — lowest game impact; draft only for roster depth minimums

*Base madden_value = position_multiplier × 100, then adjust:*
- If QB with OVR ≥ 80: +15
- If WR/HB with speed ≥ 93 (elite burner tier — Brian Thomas/Gibbs range): +25
- If WR/HB with speed 90–92: +15
- If CB with speed ≥ 92: +15
- If EDGE with speed ≥ 88: +10
- If any Tier 3 position (OT/G/C/DT): cap madden_value at 45 regardless of OVR

**tendency_score** (0–100):
- If position is in team's top-3 historical picks: 80
- If position is team's top early-round pick AND current round ≤ 3: 90
- If position never picked by team historically: 25
- Note: tendency_score is directional but noisy due to ownership changes. Weight it as a tiebreaker more than a primary driver.
- Middle positions: 50

**player_quality** (0–100):
- Brugler grade: 1st=100, 2nd=85, 3rd=70, 4th=55, 5th=45, ungraded=50
- Consensus rank: top 10=100, 11-32=85, 33-64=70, 65-100=55, 100+=40
- Use Brugler grade if available; fall back to consensus_rank
- If neither exists, use OVR relative to position average as proxy

**Speed bonus (additional flat bonus on top of madden_value, applied to final fit_score):**
- Speed ≥ 93 at WR/HB/CB: +20 flat
- Speed 90–92 at WR/HB/CB: +12 flat
- Speed ≥ 88 at EDGE/LB/S: +8 flat
- No speed bonus for OT/G/C/DT regardless of speed rating

**Playstyle adjustment (apply last, before ranking):**

Derive or approximate the team's offensive playstyle from available data:
1. If season stats are loaded: use team pass% directly
2. If no stats: proxy from draft history — teams with top-3 WR draft frequency are likely pass-first; top-3 HB draft frequency → run-first
3. Apply adjustment to madden_value for WR and HB positions only:
   - Pass-first team (pass% > 60% OR WR is historical #1 draft position): WR madden_value +10, HB madden_value −10
   - Run-first team (pass% < 45% OR HB is historical #1 draft position): HB madden_value +10, WR madden_value −5
   - Balanced: no adjustment
4. Note: do not adjust QB, CB, EDGE, or any other position — playstyle only affects WR vs HB tradeoff

### Step 2: Rank by fit_score and return top 3

Return the top 3 suggestions with explanation text:
- "Strong need: only 1 CB on roster"
- "Team tendency: [Team] historically drafts WR in early rounds"
- "Speed premium: 93 speed WR — elite burner tier, game-breaking in Madden"
- "Madden value: QB upgrade — current starter is 71 OVR"
- "Value pick: EDGE goes later in NML than NFL — 88 speed pass rusher available"
- Note: do NOT generate reasons like "scarce position value" for OT/G/C/DT — those positions don't command premium reasoning in NML context

### Step 3: Display in Mock Draft UI

Show as a panel on the right side of the Mock Draft page (when picking):
- Ranked list: #1 suggested pick (with reason), #2, #3
- Small badge: "📊 Suggested Pick" header
- Each entry: Player name | Position | Grade | Fit reason
- Allow commissioner/owner to override and pick anything

---

## 9. Live Draft Mode (Future — Mode B)

When predicting what **another team** will pick:
- Run fit_score for the picking team across all available players
- Weight tendency_score higher (0.35) and need_score lower (0.30) — you're predicting behavior, not prescribing need
- Return top 1-3 predictions with confidence %
- Show in draft tracker as "Expected picks: WR Travis Hunter (65% likely)"
- Update in real-time as picks come off the board

---

## 10. Data Access Notes for Implementation

All data lives in the NML SQLite DB (`data/nml.db`). Key queries:

**Available prospects at any draft point:**
```sql
SELECT * FROM draft_prospects WHERE nml_round IS NULL ORDER BY consensus_rank, brugler_rank
```

**Team roster depth:**
```sql
SELECT position, COUNT(*), AVG(overall_rating), MAX(overall_rating)
FROM players WHERE nml_team_id = ? AND is_free_agent = 0
GROUP BY position
```

**Team needs:**
```sql
SELECT item_key, tier FROM team_needs WHERE team_id = ? AND item_type = 'position'
```

**Depth chart starters:**
```sql
SELECT dc.slot, p.position, p.overall_rating
FROM depth_chart dc JOIN players p ON dc.player_id = p.id
WHERE dc.user_id = ? AND dc.depth = 1
```

**Historical draft tendencies:**
```sql
SELECT position, draft_round, COUNT(*) as picks
FROM players WHERE nml_team_id = ? AND rookie_year IN (2022,2023,2025) AND draft_round != 64
GROUP BY position, draft_round ORDER BY picks DESC
```

---

## 11. Position Mapping Notes

NML uses Madden position codes. Cross-reference:
- `LEDGE` / `REDGE` = left/right defensive end (Edge rushers)
- `MIKE` = middle LB, `WILL` = weakside LB, `SAM` = strongside LB
- `LT/RT/LG/RG/C` = standard OL
- `FS/SS` = safeties
- `HB` = halfback/RB (not `RB`)
- `K` = kicker, `P` = punter, `LS` = long snapper (ignore for draft suggestions)

---

## 12. Implementation Priority

1. **Build the `get_draft_suggestion(team_id, available_prospect_ids)` Python function** in `backend/app.py`
2. **Add endpoint:** `GET /api/draft/suggest?team_id=X` — returns top 3 suggestions with reasons
3. **Frontend panel** in the Mock Draft page (already planned as Item 12 in backlog)
4. The suggestion panel should update live as mock picks are made (available pool shrinks)
5. Store team tendency cache (precompute from history) to avoid re-querying on every pick

---

## 13. Attached Data File

Full JSON dataset is at `imports/opus_draft_data.json` containing:
- `draft_history`: all 706 historical picks with position/round/OVR/speed/team
- `position_by_round`: aggregated position frequency per round
- `team_draft_tendencies`: per-team profile with top positions, early round favorites, avg speed
- `roster_depth`: current position depth per team with OVR stats
- `team_needs`: needs logged by 9 teams
- `depth_chart_starters`: 7 teams with filled depth charts
- `future_picks`: all 32 teams' owned draft pick assets
- `position_scarcity`: league-wide rarity metrics per position
- `top_prospects`: top 300 prospects with grades, age, measurables

---

## 14. Stats Calibration (Future Update)

Full NML season game stats are being compiled by the commissioner and will be added to this briefing when available. When received, use them to:
- Validate and tune the `madden_value` position multipliers against actual in-game production
- Identify any positions or archetypes that over/underperformed relative to ratings
- Adjust speed thresholds if the data shows the breakpoint is different than assumed (currently set at 90/93 for WR/HB)
- Note: stats reflect both player quality AND owner skill — normalize for opponent quality where possible

Current confirmed stats (M26 season, 17 games):

*Individual leaders:*
- WR leader: Brian Thomas Jr. — 2,902 rec yards, 33 TD (170.7/game) — validates elite-speed WR premium
- WR #2: Nico Collins — 2,119 yards, 21 TD (124.6/game)
- Rush efficiency leader: Jahmyr Gibbs — 2,628 yards, **11.9 YPC** (96 speed, run-first team) — validates speed-back premium in run scheme
- Rush volume leader: Josh Jacobs — 336 att, 2,122 yards, 6.3 YPC, 89 BTK, 762 YAC — power back, lower efficiency
- De'von Achane (96 speed, pass-first team): 199 att, 1,397 yards, **7.0 YPC**, 13 TD — same speed as Gibbs, lower YPC due to pass-first scheme

*Team-level stats (pass-first vs run-first contrast):*
- Las Vegas Raiders (pass-first, ~78% pass): 6,130 pass yds / 1,714 rush yds | 67 PTD / 14 RTD | 34.1 PPG | 344 1st downs
- Green Bay Packers (run-first, ~53% rush): 3,482 pass yds / 3,928 rush yds | 35 PTD / 51 RTD | **38.3 PPG** | 353 1st downs

Key calibration insight: run-first team scored more points — both strategies win at high levels. The Achane/Gibbs gap (7.0 vs 11.9 YPC with identical speed) shows scheme matters as much as player for HB production. Tune playstyle adjustments conservatively — don't over-penalize HBs for pass-first teams or vice versa.

---

*Ready for Opus to implement the suggestion engine. Start with the `get_draft_suggestion()` function and endpoint, then wire up the frontend panel.*

---

## 15. Trade Valuation Consistency Rule (added April 21, 2026)

When the suggestion engine or any advisory output discusses trades, a player's market value is a SINGLE anchored number that does not change based on which team is on the other side of the deal. See `imports/opus_session_input.md` → "MARKET CORRECTIONS & VALUATION RULES" for anchored values and behavioral guardrails.

Key rules in short form:
1. One asset = one market price. Apply consistently across all trade partners.
2. Pick capital uses standard NFL trade chart values. #30+#31 ≈ 1220 pts < #8 alone (1400 pts).
3. Miami Dolphins picks are discounted to late-R1 range (current AND future) — their owner always makes playoffs and cannot access lottery slots.
4. Breakout candidates on Jon's roster (Odunze, BTJ, Stingley, Graham, Fiske, McCarthy) carry a holding premium — move only for ABOVE-anchor offers.
5. If a sweetener is being proposed, verify its value is less than the value delta being solved. Never sweeten a fair deal with an asset that exceeds the delta.
