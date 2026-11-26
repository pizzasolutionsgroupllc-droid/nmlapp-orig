# NML Draft Suggestion Engine — Opus Session Input
**Generated:** April 2026  |  **Draft Day:** Friday April 25, 2026
**NFL R1:** Thursday April 24 (results will update `nfl_team`/`nfl_round` fields when logged)

> This document is the primary input for Opus. It contains:
> 1. 2026 Prospect Board with NML Madden Value scores
> 2. 2026 Draft Pick Map (all teams)
> 3. Team Needs by team
> 4. Owner Tendency Profiles (abbreviated)
> 5. Commissioner (Jon / Raiders) context and goals
> 6. Key algorithm rules from the briefing

---
## ABOUT THE NML APP (for Opus context)

The NML League Manager is a custom-built web app (Flask/Python backend, SQLite database,
single-page JavaScript frontend) that Jon built with Claude to manage his Madden franchise league.
Jon is the commissioner. The app is live on Railway (cloud hosting) and used by all 32 league members.
All player ratings, rosters, picks, trades, and draft data come from Madden franchise exports and
manual CSV imports. Understanding what the app can do is relevant because Opus's draft suggestions
will be executed INSIDE this system.

### Current App Pages & Features

**Roster & Player Management**
  - **Dashboard** — Commissioner view: league-wide at-a-glance stats, quick links to key tools
  - **My Team** — Each owner's roster, depth chart stats, pick inventory, and watchlist
  - **All Teams** — Browse any of the 32 teams; click into Team Detail for full roster + picks + trade block note + needs
  - **All Players** — Full league player database with filters (position, team, OVR, age, speed)
  - **Free Agents** — Players not on any roster, searchable and filterable
  - **My Depth Chart** — Owners set their personal formation and starting lineup; Jon's default: 4-2 Nickel / Shotgun 3WR
  - **Roster Health** — Tracks player injury/health status (Madden injury ratings)
  - **Player Modal** — Click any player anywhere in the app to see full profile:
      OVR + all ratings, age, speed, position rank in league, trade history, rating history, watchlist toggle

**Trade System**
  - **Trade Center** (commissioner-only) — View all proposed/accepted/rejected/countered trades
  - **Propose Trade** — Any owner can propose trades; includes live Trade Value Calculator:
      Each player/pick shows individual point value; overall grade: Even / Slight / Strong / Very one-sided
  - **Transaction Log** — Full history of every trade accepted in the league, with asset details
  - **Trade Block** — All teams' publicly listed trade block assets + team needs board + tradeblock note
    Commissioner (Jon) uses 'My Block' view to manage his own assets and note
  - **Pick Tracker** — All picks R1-R7, current vs original owner, filterable by team or 'My Picks'
  - **Discord Magic Links** — When a trade is proposed, both teams receive Discord DMs with
    Accept/Reject buttons that execute the trade without logging into the app

**Draft Tools**
  - **Draft Room** — Live draft interface (see DRAFT LOGISTICS section below for full details)
  - **Prospect Board** — 2026 NFL draft prospects with NML Madden Value scores, 40-times, RAS,
    consensus ranks, Brugler grades. Visible to all logged-in owners. Commissioner-only admin tools.
  - **NFL Draft Tracker** — Thursday night R1 tracker; Jon logs NFL picks in real time;
    updates nfl_team/nfl_round on prospects, then regenerates this session input file
  - **NML Draft History** — Historical record of past NML draft picks (data import pending)
  - **NFL Draft History** — Historical NFL draft data used to build the Madden OVR development model
  - **Mock Draft** — Page exists (UI built) but not yet fully implemented

**League Intelligence**
  - **Power Rankings** — Auto-calculated weekly score (starter OVR 40pts + depth 10pts + age 25pts + pick capital 25pts)
    Commissioner triggers recalculation; snapshots stored weekly for movement tracking (↑↓=)
  - **Schedule** — League schedule mirroring NFL (17 weeks, 1 game/week per team);
    owners can set planned game date/time and stream URL per matchup
  - **Rating History** — Player OVR tracked across Madden import snapshots;
    visible in player modal as a table of OVR per snapshot label
    Current baseline: 'M26 Super Bowl Update' (April 2026)

**Admin Tools (commissioner-only)**
  - **Settings** — League settings, Trade Grader position/age/pick weights, draft timer lengths per round,
    depth chart position eligibility, Discord test mode override
  - **Madden Import** — Import player ratings from Madden franchise CSV export
  - **Import Players** — Bulk prospect import (school, position, combine data, consensus rank)
  - **Users & Teams** — Manage owner accounts, assign teams, set roles (commissioner / assistant / owner)
  - **Audit Log** — Full log of all data changes for debugging and accountability
  - **Ideas** — Internal feature wishlist/backlog page (Jon's notes to himself)

### What Does NOT Exist Yet (relevant to draft context)
  - No in-season game results / standings (Season starts September 2026 — no game data yet)
  - No draft lottery tool (not needed until 2027 offseason)
  - Mock Draft page is not fully functional yet
  - NML draft history import not yet done (past picks not tracked in DB)
  - No stats page (no game data yet)

### Data Pipeline
  - Player ratings come from Madden franchise CSV exports (manual process)
  - Current DB has 3,000+ players across all 32 teams
  - Ratings in DB = end-of-season M26 update (see CRITICAL RATINGS CALIBRATION section)
  - Draft prospects imported from scouting CSV + manual entry of combine data

---
## CORE RULES FOR THIS ENGINE

**Prediction chain:** NFL performance → EA Madden weekly updates → player rating → NML value.
Projecting NFL success IS projecting future Madden ratings. The engine ranks by projected Madden value, not NFL value.

**Position multipliers (NML Madden value weight):**
QB=0.95 | WR=0.90 | HB=0.85 | CB=0.80 | TE/S=0.65 | EDGE(fast)=0.60 | LB=0.55 | EDGE(slow)=0.45 | DT=0.35 | OT=0.30 | IOL=0.25

**Speed tiers for skill positions (WR/HB/CB/S):**
S-TIER: <4.30 forty (95+ spd, +25pts) | ELITE: <4.35 (92-94, +20pts) | GREAT: <4.40 (89-91, +12pts) | GOOD: <4.45 (86-88, +5pts)

**Speed tiers for EDGE/LB:**
ELITE: <4.45 forty (89-92 spd, +12pts) | GREAT: <4.50 (86-88, +8pts) | GOOD: <4.55 (83-85, +3pts)

**OT/IOL/DT note:** Trench positions are CORRECTLY devalued in NML. Madden does not reward OL/DT play realistically. Do NOT treat them as undervalued. Cap trench need_score at 60.

**NML position name mapping** (prospect DB → Madden):
EDGE→LEDGE/REDGE | IOL→LG/RG/C | LB→MIKE/WILL/SAM | S→SS/FS | RB→HB | DL5T→DT

**NFL Pick → Projected Madden OVR (from 960 historical matches, 2020-2025 classes):**

| Pick Range   | Yr1 avg | Yr2 avg | Yr3 avg | Yr4 avg | Typical range |
|--------------|---------|---------|---------|---------|---------------|
| Top-5        | 80      | 85      | 85      | 87      | 77–95 OVR     |
| #6-15        | 81      | 80      | 84      | 83      | 75–93 OVR     |
| #16-32       | 78      | 78      | 81      | 78      | 72–90 OVR     |
| R2 (33-64)   | 75      | 76      | 76      | 80      | 68–87 OVR     |
| R3 (65-100)  | 72      | 73      | 76      | 74      | 65–84 OVR     |
| R4+ (101+)   | 69      | 70      | 69      | 74      | 60–80 OVR     |

**By position — NFL R1 vs R2 vs R3+ avg current Madden OVR:**
| Pos   | NFL R1 avg | NFL R2 avg | NFL R3+ avg | Key insight |
|-------|-----------|-----------|------------|-------------|
| HB    | 87        | 82        | 74         | Highest raw OVR of any R1 position — Madden rewards elite HBs |
| TE    | 85        | 76        | 70         | Big R1 premium — R2+ TEs rarely reach elite OVR |
| CB    | 84        | 78        | 72         | Strong R1 value, drops off meaningfully in R2 |
| WR    | 83        | 77        | 73         | Deep position — R2 WRs still productive |
| S     | 80        | 80        | 72         | R1/R2 comparable — value in waiting |
| LB    | 80        | 79        | 70         | R1/R2 close, but R3+ drop is steep |
| EDGE  | 79        | 75        | 71         | Moderate R1 premium, speed EDGE worth more |
| OT    | 79        | 71        | 66         | Large R1 premium but LOW NML value regardless |
| QB    | 76        | 72        | 66         | Slow developers — even R1 QBs avg only 76 OVR |
| DT    | 77        | 72        | 69         | LOW NML value regardless of OVR |

> **Key takeaways:** HB and TE have the steepest R1/R2+ drop-offs — wait on these and you get dramatically worse players.
> WR and S are safer to take in R2 (still productive). QB is a slow developer — even top QBs take 2-3 seasons to hit 80+ OVR.

**⚠️ CRITICAL RATINGS CALIBRATION — READ BEFORE USING THE MODEL ABOVE:**

The OVR numbers in the development model are **end-of-season ratings** (post-Super Bowl EA update),
NOT the Week 1 launch ratings that NML actually uses. Week 1 launch ratings for rookies are
typically **5–8 OVR points lower** than the model shows.

**How NML uses Madden ratings:**
1. EA releases Madden each August with Week 1 ratings (reflects preseason + projected performance)
2. NML imports that Week 1 roster to start their franchise — players are SOFT-LOCKED at those ratings
3. EA's ongoing weekly NFL updates do NOT affect NML ratings mid-season
4. End-of-season EA update (what's in the DB now) becomes the baseline for NEXT NML season

**Practical implication:** A prospect drafted top-5 in the NFL draft will likely launch at ~73-76 OVR
in Week 1 Madden. By end of season (if they play well), they reach ~80-85 OVR. The NML cares about
both: Week 1 OVR for immediate season impact, and year 2-3 trajectory for long-term roster building.

**In-franchise rating changes (within NML season, separate from EA updates):**
Madden franchise mode has mechanics that independently boost ratings mid-NML-season:
- Team morale bonus (winning): up to +5 OVR to players on a winning team
- Individual performance (high stats for position): up to +5 OVR
- Pro Bowl / All-Pro level: up to +5 OVR
- Max in-franchise boost: ~+15 OVR over a full NML regular season
- Dev trait amplifies this: X-Factor/Superstar dev = fastest growth | Normal dev = slowest
- NML owners don't rely on these for roster planning but they affect competitive outcomes

**Dev trait note:** EA assigns dev traits at launch. Not known in advance for 2026 prospects.
Historical pattern: top-10 NFL picks → usually Superstar/X-Factor dev | Late rounds → usually Normal.

---
**⚠️ NML DRAFT LOTTERY — How pick slots actually work:**

NML R1 is a POST-LOTTERY order. The draft lottery is run before the draft, similar to NBA-style.
R2 order = pre-lottery (straight inverse finish order). R1 order = post-lottery result.
- Max slots a team can DROP in the lottery: 5 positions (a team cannot fall more than 5 spots from their pre-lottery slot)
- Max slots a team can MOVE UP: No ceiling — any team can theoretically leap to #1
- Example this year: Bears were 2nd worst team but ended up with pick #7 (moved down 5 — worst luck)
- Example this year: Pittsburgh went from pre-lottery #15 → post-lottery #9 (moved up 6 — best luck)
- IMPLICATION for future picks: A 2027 R1 from the worst team might be #1 overall OR it might be #5-6.
  Value from bad teams is still highest expected value — but with real variance. Price accordingly.
- IMPLICATION for trading future R1s: A pick from a middle-of-pack bad team (e.g. CHI 2027) has the
  same lottery upside potential as any bad team. Cannot be locked to a specific slot.

---
**AGE FRAMEWORK — Floor vs Ceiling for prospects:**

A prospect's combine numbers and college production are a FLOOR for younger players,
and CLOSE TO A CEILING for older prospects. Physical development doesn't stop at 21.

| Age Band | Development Stage | How to interpret combine/production |
|----------|-------------------|--------------------------------------|
| 20-21    | Still physically maturing — getting heavier, stronger, faster, more aware | Combine = floor. Could meaningfully exceed these numbers at NFL peak | WIDEST gap between floor and ceiling |
| 22       | Approaching peak athleticism but not there | Combine = likely floor with moderate upside | |
| 23       | Near physical peak in most measurables | Combine ≈ projection. Modest upside | |
| 24+      | Physically maxed out in most cases | Combine ≈ ceiling. What you see is mostly what you get | NARROWEST gap |

Apply this when comparing two players with similar 40-times: the 21-year-old 4.40 will likely run
4.36-4.38 at their peak NFL season. The 24-year-old 4.40 will still run 4.40 or slower at their peak.
Same combine = VERY different projected Madden ratings 2-3 years from now.

---
**JON'S ROSTER HOLD PHILOSOPHY — Universal across all positions:**

Jon applies a consistent age-based hold strategy across ALL premium positions, not just CB/WR.
The goal: draft young, hold through peak years, trade veterans at peak market value before decline.
THIS MEANS: Jon does NOT want to sell current veterans at current prices unless massively overpaid.
The plan is to hold today's veterans 2-3 more years, draft replacements now, then sell at the right age.

**Position aging curves and trade windows (sell one season before decline starts):**

| Position | Peak Age | HOLD Through | SELL Window | Notes |
|----------|----------|-------------|-------------|-------|
| RB/HB    | 24-26    | Age ≤25     | 26-27       | Earliest decline of any skill position |
| WR       | 25-27    | Age ≤26     | 27-28       | Longer window if elite route runner |
| CB       | 25-27    | Age ≤26     | 27-28       | Jon's current 3 CBs are in prime years now — hold 2 more years |
| S        | 25-27    | Age ≤26     | 27-28       | Similar to CB |
| LB/EDGE  | 25-28    | Age ≤27     | 28-29       | Pass rushers can extend into early 30s |
| QB       | 27-32    | Age ≤29     | 30+         | Latest to develop, latest to decline |
| OT/IOL   | 26-30    | Age ≤28     | 29+         | Low NML value anyway — not a priority |

**Application to Raiders current roster:**
McDuffie (94 CB, age 25): HOLD or sell ONLY for elite price — prime years ahead, do NOT sell cheap.
Stingley (92 CB, age 24): HOLD — same window. Worth 2 current R1s minimum if sold.
Sauce Gardner (90 CB, ~24): HOLD — same logic.
Jameson Williams (85 WR, ~24): HOLD. Speed demon at peak incoming years.
Rome Odunze (82 WR, ~22): HOLD unless someone pays a R1 for a 22-yr-old WR2.
Brian Thomas Jr (81 WR, ~23): HOLD.
→ NO current veteran should be sold at a discount. Jon is asset-accumulating, not liquidating.
---
## 2026 PROSPECT BOARD

**Total 2026 prospects loaded:** 200 | **NFL R1 taken:** 0 | **Available:** 200

### ⚠️ 2026 CLASS DEPTH ALERTS

**How deep is each position in this draft class? This affects urgency.**

| Position | R1-tier (top 32) | R2-tier (top 64) | Top-100 total | Verdict |
|----------|-----------------|-----------------|---------------|---------|
| OT       | 7               | 9               | 10            | Deep — but low NML value. Do not overdraft. |
| WR       | 6               | 9               | 16            | Moderate depth — 6 R1-tier. Best speed WRs go fast. |
| EDGE     | 5               | 11              | 15            | Deep — 5 R1-tier, 11 R2-tier. Can wait until R2. |
| S        | 3               | 4               | 9             | Thin — only 3 R1-tier safeties. Strike if one falls. |
| CB       | 3               | 8               | 15            | Moderate — only 3 R1-tier. Elite CBs scarce early. |
| LB       | 2               | 7               | 9             | Moderate — 2 R1-tier, 7 R2-tier. Can wait. |
| DT       | 2               | 5               | 8             | Moderate — low NML value regardless. Do not reach. |
| TE       | 1               | 2               | 4             | ⚠️ THIN — only 1 R1-tier TE (Sadiq #17). Take in R1 or wait for R3. |
| RB       | 1               | 3               | 4             | ⚠️ THIN — only 1 R1-tier RB (Love #4). Take early or wait. |
| QB       | 1               | 2               | 4             | 🚨 CRITICAL THIN — only 1 R1-tier QB (Mendoza #1). This is essentially a 1-QB class at premium level. |
| IOL      | 1               | 4               | 6             | Moderate — lowest NML value. Ignore. |

> **Bottom line for Jon's draft:** QB class is a 1-man show (Mendoza). RB is thin after Love. TE is thin after Sadiq.
> WR and EDGE are the deepest skill positions — value exists throughout the middle rounds.

### Available Prospects — NML Value Ranked

Columns: Rank | Name | Pos | School | Cons.Rank | 40-time | RAS | Age | SpeedTier | NML_Value | NFL_Status

  1. Jeremiyah Love               RB     Notre Dame             #4     40:4.36  RAS:—  Age:20.9  [GREAT        ~89-91]  NML:104.7
     Ht:6'0"  Wt:212  Hand:9.12"  Vert:—
  2. Fernando Mendoza             QB     Indiana                #1     40:—  RAS:—  Age:22.6  [?            ~?]  NML:95.0
     Ht:6'4 6/8"  Wt:236  Hand:9.50"  Vert:—
  3. Mansoor Delane               CB     LSU                    #10    40:4.38  RAS:—  Age:22.4  [GREAT        ~89-91]  NML:83.2
     Ht:5'11 6/8"  Wt:187  Hand:8.88"  Vert:—
  4. Carnell Tate                 WR     Ohio State             #7     40:4.53  RAS:—  Age:21.3  [SLOW         ~<83]  NML:82.8
     Ht:6'2 2/8"  Wt:192  Hand:10.25"  Vert:—
  5. Jermod McCoy                 CB     Tennessee              #14    40:4.40  RAS:9.7  Age:20.7  [GOOD         ~86-88]  NML:78.3
     Ht:6'0 6/8"  Wt:188  Hand:9.00"  Vert:—
  6. Makai Lemon                  WR     USC                    #12    40:4.50  RAS:—  Age:21.9  [SLOW         ~<83]  NML:75.6
     Ht:5'11 1/8"  Wt:192  Hand:8.75"  Vert:—
  7. Jordyn Tyson                 WR     Arizona State          #15    40:—  RAS:—  Age:21.7  [?            ~?]  NML:75.6
     Ht:6'2 1/8"  Wt:203  Hand:9.12"  Vert:—
  8. Omar Cooper Jr.              WR     Indiana                #22    40:4.42  RAS:9.2  Age:22.4  [GOOD         ~86-88]  NML:72.9
     Ht:6'0 1/8"  Wt:199  Hand:9.62"  Vert:37.0"
  9. Kevin Concepcion             WR     Texas A&M              #24    40:—  RAS:—  Age:22.6  [?            ~?]  NML:68.4
     Ht:—  Wt:None  Hand:—  Vert:—
 10. Denzel Boston                WR     Washington             #27    40:—  RAS:—  Age:22.4  [?            ~?]  NML:68.4
     Ht:6'3 5/8"  Wt:212  Hand:9.75"  Vert:35.0"
 11. Mike Washington Jr.          RB     Arkansas               #60    40:4.33  RAS:9.9  Age:22.8  [ELITE        ~92-94]  NML:66.3
     Ht:6'1"  Wt:223  Hand:9.25"  Vert:39.0"
     ⚠️ NML reach risk: may go as early as pick #40 (elite speed (<4.35))
 12. Arvell Reese                 LB     Ohio State             #2     40:4.46  RAS:—  Age:20.6  [GREAT        ~86-88]  NML:65.3
     Ht:6'4 1/8"  Wt:241  Hand:9.50"  Vert:—
 13. Brandon Cisse                CB     South Carolina         #44    40:4.41  RAS:9.2  Age:20.8  [GOOD         ~86-88]  NML:64.2
     Ht:5'11 6/8"  Wt:189  Hand:8.50"  Vert:41.0"
 14. Chris Brazzell               WR     Tennessee              #54    40:4.37  RAS:—  Age:22.5  [GREAT        ~89-91]  NML:63.0
     Ht:6'4"  Wt:198  Hand:9.00"  Vert:—
     ⚠️ NML reach risk: may go as early as pick #36 (great speed (<4.38), Tennessee loyalty reach)
 15. Zachariah Branch             WR     Georgia                #65    40:4.35  RAS:9.1  Age:22.1  [GREAT        ~89-91]  NML:63.0
     Ht:5'8 5/8"  Wt:177  Hand:9.00"  Vert:38.0"
 16. Dillon Thieneman             S      Oregon                 #18    40:4.35  RAS:9.7  Age:21.7  [GREAT        ~89-91]  NML:62.4
     Ht:6'0 1/8"  Wt:201  Hand:9.00"  Vert:41.0"
 17. David Bailey                 EDGE   Texas Tech             #3     40:4.50  RAS:9.7  Age:22.6  [GOOD         ~83-85]  NML:61.8
     Ht:6'3 5/8"  Wt:251  Hand:10.25"  Vert:35.0"
 18. Avieon Terrell               CB     Clemson                #32    40:4.64  RAS:4.9  Age:21.3  [SLOW         ~<83]  NML:60.8
     Ht:5'10 6/8"  Wt:186  Hand:8.62"  Vert:34.0"
 19. Caleb Downs                  S      Ohio State             #8     40:4.52  RAS:—  Age:21.4  [SLOW         ~<83]  NML:59.8
     Ht:5'11 5/8"  Wt:206  Hand:9.50"  Vert:—
 20. Sonny Styles                 LB     Ohio State             #5     40:4.46  RAS:10.0  Age:21.4  [GREAT        ~86-88]  NML:59.4
     Ht:6'5"  Wt:244  Hand:10.00"  Vert:43.5"
 21. Colton Hood                  CB     Tennessee              #34    40:4.44  RAS:9.7  Age:21.2  [GOOD         ~86-88]  NML:58.4
     Ht:5'11 5/8"  Wt:193  Hand:9.00"  Vert:40.5"
 22. Chris Johnson                CB     San Diego State        #38    40:4.40  RAS:9.8  Age:21.4  [GOOD         ~86-88]  NML:58.4
     Ht:6'0 3/8"  Wt:193  Hand:9.88"  Vert:38.0"
 23. Ty Simpson                   QB     Alabama                #33    40:—  RAS:—  Age:23.3  [?            ~?]  NML:58.1
     Ht:6'1 1/8"  Wt:211  Hand:9.38"  Vert:—
 24. Jadarian Price               RB     Notre Dame             #43    40:4.49  RAS:8.6  Age:22.5  [AVG          ~83-85]  NML:57.8
     Ht:5'10 5/8"  Wt:203  Hand:9.62"  Vert:35.0"
 25. Ted Hurst                    WR     Georgia State          #69    40:4.42  RAS:9.9  Age:21.8  [GOOD         ~86-88]  NML:56.7
     Ht:6'3 7/8"  Wt:206  Hand:9.75"  Vert:36.5"
 26. Antonio Williams             WR     Clemson                #73    40:4.41  RAS:8.6  Age:21.8  [GOOD         ~86-88]  NML:56.7
     Ht:5'11 4/8"  Wt:187  Hand:9.25"  Vert:39.5"
     ⚠️ NML reach risk: may go as early as pick #55 (Clemson loyalty reach, young prospect)
 27. Brenen Thompson              WR     Mississippi State      #113   40:4.26  RAS:—  Age:22.8  [S-TIER       ~95+]  NML:56.7
     Ht:5'9 3/8"  Wt:164  Hand:9.00"  Vert:—
     ⚠️ NML reach risk: may go as early as pick #78 (S-TIER speed (4.2Xs))
 28. Treydan Stukes               CB     Arizona                #56    40:4.33  RAS:9.9  Age:24.6  [ELITE        ~92-94]  NML:56.2
     Ht:6'0 5/8"  Wt:190  Hand:8.50"  Vert:38.0"
     ⚠️ NML reach risk: may go as early as pick #36 (elite speed (<4.35))
 29. Keionte Scott                CB     Miami (FL)             #66    40:4.33  RAS:9.7  Age:24.7  [ELITE        ~92-94]  NML:56.2
     Ht:5'11 2/8"  Wt:193  Hand:9.62"  Vert:—
     ⚠️ NML reach risk: may go as early as pick #46 (elite speed (<4.35))
 30. D'angelo Ponds               CB     Indiana                #51    40:4.36  RAS:8.2  Age:21.3  [GREAT        ~89-91]  NML:56.0
     Ht:5'8 5/8"  Wt:182  Hand:9.62"  Vert:43.5"
 31. Keldric Faulk                EDGE   Auburn                 #20    40:4.67  RAS:9.1  Age:20.6  [SLOW         ~<79]  NML:55.4
     Ht:6'5 7/8"  Wt:276  Hand:9.88"  Vert:35.0"
 32. Rueben Bain                  EDGE   Miami (FL)             #9     40:4.72  RAS:—  Age:21.6  [SLOW         ~<79]  NML:55.2
     Ht:6'2 2/8"  Wt:263  Hand:9.12"  Vert:—
 33. Bryce Lance                  WR     North Dakota State     #87    40:4.34  RAS:9.9  Age:23.7  [ELITE        ~92-94]  NML:55.1
     Ht:6'3 3/8"  Wt:204  Hand:9.25"  Vert:41.5"
     ⚠️ NML reach risk: may go as early as pick #67 (elite speed (<4.35))
 34. Kenyon Sadiq                 TE     Oregon                 #17    40:4.39  RAS:9.5  Age:21.1  [FAST-trench  ~78+]  NML:54.6
     Ht:6'3 1/8"  Wt:241  Hand:10.00"  Vert:43.5"
 35. Chris Bell                   WR     Louisville             #52    40:—  RAS:—  Age:21.9  [?            ~?]  NML:52.2
     Ht:6'1 7/8"  Wt:222  Hand:10.00"  Vert:—
 36. Germie Bernard               WR     Alabama                #55    40:4.48  RAS:9.1  Age:22.4  [AVG          ~83-85]  NML:52.2
     Ht:6'1 2/8"  Wt:206  Hand:9.88"  Vert:32.5"
 37. Malachi Fields               WR     Notre Dame             #74    40:4.61  RAS:7.5  Age:22.7  [SLOW         ~<83]  NML:52.2
     Ht:6'4 4/8"  Wt:218  Hand:9.00"  Vert:38.0"
 38. Elijah Sarratt               WR     Indiana                #75    40:4.53  RAS:6.3  Age:22.9  [SLOW         ~<83]  NML:52.2
     Ht:6'2 4/8"  Wt:210  Hand:10.00"  Vert:—
 39. Emmanuel McNeil-Warren       S      Toledo                 #23    40:4.52  RAS:9.0  Age:22.3  [SLOW         ~<83]  NML:49.4
     Ht:6'3 4/8"  Wt:201  Hand:9.25"  Vert:35.5"
 40. Deion Burks                  WR     Oklahoma               #101   40:4.30  RAS:9.1  Age:23.3  [ELITE        ~92-94]  NML:47.0
     Ht:5'9 6/8"  Wt:180  Hand:9.50"  Vert:42.5"
     ⚠️ NML reach risk: may go as early as pick #81 (elite speed (<4.35))
 41. Keith Abney II               CB     Arizona State          #70    40:4.45  RAS:6.5  Age:21.3  [AVG          ~83-85]  NML:46.4
     Ht:5'9 7/8"  Wt:187  Hand:9.75"  Vert:—
 42. T.J. Parker                  EDGE   Clemson                #28    40:4.68  RAS:9.4  Age:21.6  [SLOW         ~<79]  NML:45.6
     Ht:6'3 5/8"  Wt:263  Hand:9.50"  Vert:34.0"
 43. Drew Allar                   QB     Penn State             #97    40:—  RAS:—  Age:22.1  [?            ~?]  NML:45.6
     Ht:6'5 2/8"  Wt:228  Hand:9.88"  Vert:—
 44. Skyler Bell                  WR     UConn                  #82    40:4.40  RAS:9.8  Age:23.8  [GOOD         ~86-88]  NML:42.9
     Ht:5'11 5/8"  Wt:192  Hand:10.00"  Vert:41.0"
 45. Malachi Lawrence             EDGE   UCF                    #42    40:4.52  RAS:9.9  Age:22.8  [GOOD         ~83-85]  NML:42.6
     Ht:6'4 3/8"  Wt:253  Hand:9.25"  Vert:40.0"
 46. Malik Muhammad               CB     Texas                  #92    40:4.42  RAS:9.5  Age:21.6  [GOOD         ~86-88]  NML:42.4
     Ht:6'0"  Wt:182  Hand:9.88"  Vert:39.0"
 47. Chandler Rivers              CB     Duke                   #100   40:4.40  RAS:9.0  Age:22.5  [GOOD         ~86-88]  NML:42.4
     Ht:5'9 4/8"  Wt:185  Hand:9.50"  Vert:39.0"
 48. Garrett Nussmeier            QB     LSU                    #80    40:—  RAS:—  Age:24.2  [?            ~?]  NML:41.0
     Ht:6'1 5/8"  Wt:203  Hand:9.12"  Vert:—
 49. Zion Young                   EDGE   Missouri               #37    40:4.75  RAS:7.7  Age:22.1  [SLOW         ~<79]  NML:40.8
     Ht:6'5 6/8"  Wt:262  Hand:9.50"  Vert:—
 50. R Mason Thomas               EDGE   Oklahoma               #47    40:4.67  RAS:7.2  Age:21.7  [SLOW         ~<79]  NML:40.8
     Ht:6'2 2/8"  Wt:241  Hand:8.88"  Vert:—
 51. Jonah Coleman                RB     Washington             #89    40:—  RAS:—  Age:22.7  [?            ~?]  NML:40.8
     Ht:5'8 1/8"  Wt:220  Hand:9.12"  Vert:—
 52. De'Zhaun Stribling           WR     Mississippi            #106   40:4.36  RAS:9.6  Age:23.4  [GREAT        ~89-91]  NML:40.5
     Ht:6'2 1/8"  Wt:207  Hand:10.00"  Vert:36.0"
 53. Daylen Everette              CB     Georgia                #109   40:4.38  RAS:9.9  Age:22.0  [GREAT        ~89-91]  NML:40.0
     Ht:6'1 2/8"  Wt:196  Hand:9.62"  Vert:37.5"
 54. Eli Stowers                  TE     Vanderbilt             #50    40:4.51  RAS:9.4  Age:23.0  [FAST-trench  ~78+]  NML:39.8
     Ht:6'3 6/8"  Wt:239  Hand:9.75"  Vert:45.5"
 55. Jeff Caldwell                WR     Cincinnati             #163   40:4.31  RAS:10.0  Age:23.1  [ELITE        ~92-94]  NML:39.7
     Ht:6'5 3/8"  Wt:216  Hand:9.75"  Vert:42.0"
     ⚠️ NML reach risk: may go as early as pick #143 (elite speed (<4.35))
 56. Anthony Hill Jr.             LB     Texas                  #48    40:4.51  RAS:9.8  Age:21.2  [GOOD         ~83-85]  NML:39.1
     Ht:6'2"  Wt:238  Hand:9.62"  Vert:37.0"
 57. Akheem Mesidor               EDGE   Miami (FL)             #21    40:—  RAS:—  Age:25.1  [?            ~?]  NML:38.8
     Ht:6'3"  Wt:259  Hand:10.00"  Vert:—
 58. Davison Igbinosun            CB     Ohio State             #79    40:4.45  RAS:6.9  Age:22.0  [AVG          ~83-85]  NML:38.4
     Ht:6'2 1/8"  Wt:189  Hand:9.12"  Vert:34.0"
 59. Devin Moore                  CB     Florida                #96    40:4.50  RAS:8.5  Age:22.5  [SLOW         ~<83]  NML:38.4
     Ht:6'3 2/8"  Wt:198  Hand:8.62"  Vert:—
 60. A.J. Haulcy                  S      LSU                    #59    40:4.52  RAS:—  Age:22.3  [SLOW         ~<83]  NML:37.7
     Ht:5'11 5/8"  Wt:215  Hand:9.25"  Vert:—
 61. Max Klare                    TE     Ohio State             #71    40:—  RAS:—  Age:22.8  [?            ~?]  NML:37.7
     Ht:6'4 3/8"  Wt:246  Hand:9.12"  Vert:—
 62. Cashius Howell               EDGE   Texas A&M              #35    40:4.59  RAS:8.1  Age:23.0  [AVG          ~79-82]  NML:36.7
     Ht:6'2 4/8"  Wt:253  Hand:9.25"  Vert:32.5"
 63. Demond Claiborne             RB     Wake Forest            #164   40:4.37  RAS:7.6  Age:22.5  [GREAT        ~89-91]  NML:34.9
     Ht:5'9 6/8"  Wt:188  Hand:9.00"  Vert:—
 64. Gabe Jacas                   EDGE   Illinois               #53    40:4.65  RAS:9.6  Age:21.9  [SLOW         ~<79]  NML:34.8
     Ht:6'3 5/8"  Wt:260  Hand:10.00"  Vert:—
 65. Dani Dennis-Sutton           EDGE   Penn State             #72    40:4.63  RAS:10.0  Age:22.3  [AVG          ~79-82]  NML:34.8
     Ht:6'5 5/8"  Wt:256  Hand:10.12"  Vert:39.5"
 66. Julian Neal                  CB     Arkansas               #95    40:4.49  RAS:9.3  Age:23.2  [AVG          ~83-85]  NML:34.6
     Ht:6'1 5/8"  Wt:203  Hand:9.50"  Vert:40.0"
 67. Jalon Kilgore                S      South Carolina         #94    40:4.40  RAS:9.6  Age:21.2  [GOOD         ~86-88]  NML:34.5
     Ht:6'1 3/8"  Wt:210  Hand:9.38"  Vert:37.0"
 68. Ja'Kobi Lane                 WR     USC                    #107   40:4.47  RAS:9.4  Age:21.7  [AVG          ~83-85]  NML:34.2
     Ht:6'4 3/8"  Wt:200  Hand:10.50"  Vert:40.0"
 69. Jacob Rodriguez              LB     Texas Tech             #45    40:4.57  RAS:9.6  Age:23.6  [AVG          ~79-82]  NML:33.7
     Ht:6'1 3/8"  Wt:231  Hand:9.25"  Vert:38.5"
 70. Cole Payton                  QB     North Dakota State     #124   40:4.56  RAS:9.9  Age:23.5  [POCKET       ~72-79]  NML:32.5
     Ht:6'2 5/8"  Wt:232  Hand:10.25"  Vert:40.0"
 71. Emmett Johnson               RB     Nebraska               #110   40:4.56  RAS:5.6  Age:22.5  [SLOW         ~<83]  NML:32.3
     Ht:5'10 2/8"  Wt:202  Hand:9.75"  Vert:35.5"
 72. Jake Golday                  LB     Cincinnati             #58    40:4.62  RAS:9.8  Age:22.9  [AVG          ~79-82]  NML:31.9
     Ht:6'4 4/8"  Wt:239  Hand:9.50"  Vert:39.0"
 73. Josiah Trotter               LB     Missouri               #63    40:—  RAS:—  Age:21.0  [?            ~?]  NML:31.9
     Ht:6'1 7/8"  Wt:237  Hand:10.25"  Vert:—
 74. C.J. Allen                   LB     Georgia                #36    40:—  RAS:—  Age:—  [?            ~?]  NML:31.8
     Ht:6'0 6/8"  Wt:230  Hand:10.12"  Vert:—
 75. Derrick Moore                EDGE   Michigan               #61    40:—  RAS:—  Age:23.4  [?            ~?]  NML:31.3
     Ht:6'3 7/8"  Wt:255  Hand:9.12"  Vert:—
 76. Oscar Delp                   TE     Georgia                #83    40:4.49  RAS:9.8  Age:22.7  [FAST-trench  ~78+]  NML:31.2
     Ht:6'4 7/8"  Wt:245  Hand:9.50"  Vert:—
 77. Kamari Ramsey                S      USC                    #88    40:4.47  RAS:8.5  Age:21.7  [AVG          ~83-85]  NML:31.2
     Ht:6'0 2/8"  Wt:202  Hand:9.25"  Vert:36.0"
 78. Genesis Smith                S      Arizona                #99    40:4.50  RAS:9.8  Age:21.5  [SLOW         ~<83]  NML:31.2
     Ht:6'2 1/8"  Wt:202  Hand:8.88"  Vert:42.5"
 79. Bud Clark                    S      TCU                    #91    40:4.41  RAS:8.9  Age:24.0  [GOOD         ~86-88]  NML:31.0
     Ht:6'0 7/8"  Wt:188  Hand:9.00"  Vert:38.0"
 80. Francis Mauigoa              OT     Miami (FL)             #6     40:5.13  RAS:8.8  Age:20.9  [SLOW-trench  ~<73]  NML:30.4
     Ht:6'5 4/8"  Wt:329  Hand:10.62"  Vert:—
 81. Robert Spears-Jennings       S      Oklahoma               #193   40:4.32  RAS:8.9  Age:22.2  [ELITE        ~92-94]  NML:29.9
     Ht:6'1 7/8"  Wt:205  Hand:10.38"  Vert:35.0"
     ⚠️ NML reach risk: may go as early as pick #173 (elite speed (<4.35))
 82. Joshua Josephs               EDGE   Tennessee              #84    40:4.73  RAS:8.5  Age:22.4  [SLOW         ~<79]  NML:28.8
     Ht:6'3 1/8"  Wt:242  Hand:10.00"  Vert:—
 83. Keyron Crawford              EDGE   Auburn                 #90    40:—  RAS:—  Age:22.5  [?            ~?]  NML:28.8
     Ht:6'4 3/8"  Wt:253  Hand:9.00"  Vert:—
 84. Kyle Louis                   LB     Pittsburgh             #76    40:4.53  RAS:8.8  Age:22.1  [GOOD         ~83-85]  NML:28.1
     Ht:5'11 7/8"  Wt:220  Hand:9.50"  Vert:39.5"
 85. Zakee Wheatley               S      Penn State             #93    40:4.62  RAS:7.7  Age:24.1  [SLOW         ~<83]  NML:28.1
     Ht:6'3 1/8"  Wt:203  Hand:9.50"  Vert:32.5"
 86. Tacario Davis                CB     Washington             #131   40:4.41  RAS:8.8  Age:21.7  [GOOD         ~86-88]  NML:28.0
     Ht:6'3 7/8"  Wt:194  Hand:9.25"  Vert:37.0"
 87. VJ Payne                     S      Kansas State           #121   40:4.40  RAS:9.7  Age:22.1  [GOOD         ~86-88]  NML:27.9
     Ht:6'3 2/8"  Wt:206  Hand:9.50"  Vert:35.0"
 88. Kadyn Proctor                OT     Alabama                #19    40:5.21  RAS:8.8  Age:20.9  [SLOW-trench  ~<73]  NML:27.7
     Ht:6'6 5/8"  Wt:352  Hand:9.75"  Vert:32.5"
 89. Will Lee III                 CB     Texas A&M              #122   40:4.52  RAS:9.4  Age:23.0  [SLOW         ~<83]  NML:27.4
     Ht:6'1 4/8"  Wt:189  Hand:9.00"  Vert:42.0"
 90. Peter Woods                  DT     DL                     #29    40:—  RAS:7.6  Age:21.1  [GOOD-ath     ~85-89]  NML:26.6
     Ht:6'2 4/8"  Wt:298  Hand:9.12"  Vert:—
 91. Kayden McDonald              DT     DL                     #30    40:—  RAS:—  Age:21.1  [?            ~?]  NML:26.6
     Ht:6'2 1/8"  Wt:326  Hand:9.75"  Vert:—
 92. Cade Klubnik                 QB     Clemson                #172   40:4.69  RAS:7.5  Age:22.5  [POCKET       ~72-79]  NML:26.6
     Ht:6'2 2/8"  Wt:207  Hand:9.25"  Vert:—
     ⚠️ NML reach risk: may go as early as pick #157 (Clemson loyalty reach)
 93. Jaishawn Barham              LB     Michigan               #86    40:4.64  RAS:8.8  Age:22.2  [AVG          ~79-82]  NML:26.4
     Ht:6'3 4/8"  Wt:240  Hand:10.25"  Vert:33.0"
 94. Carson Beck                  QB     Miami (FL)             #127   40:—  RAS:—  Age:24.4  [?            ~?]  NML:25.7
     Ht:6'4 6/8"  Wt:233  Hand:10.00"  Vert:—
 95. Taylen Green                 QB     Arkansas               #137   40:4.36  RAS:10.0  Age:23.5  [MOBILE       ~85+]  NML:25.7
     Ht:6'5 7/8"  Wt:227  Hand:9.88"  Vert:43.5"
 96. Nick Singleton               RB     Penn State             #141   40:—  RAS:—  Age:22.1  [?            ~?]  NML:25.5
     Ht:6'0"  Wt:219  Hand:—  Vert:—
 97. Spencer Fano                 OT     Utah                   #11    40:4.91  RAS:9.8  Age:21.5  [AVG-trench   ~73-77]  NML:25.2
     Ht:6'5 4/8"  Wt:311  Hand:9.00"  Vert:32.0"
 98. Monroe Freeling              OT     Georgia                #13    40:4.93  RAS:10.0  Age:21.7  [AVG-trench   ~73-77]  NML:25.2
     Ht:6'7 3/8"  Wt:315  Hand:10.75"  Vert:33.5"
 99. Sam Roush                    TE     Stanford               #108   40:4.70  RAS:9.9  Age:22.6  [FAST-trench  ~78+]  NML:24.7
     Ht:6'6"  Wt:267  Hand:10.00"  Vert:38.5"
100. Justin Joly                  TE     NC State               #115   40:—  RAS:—  Age:21.8  [?            ~?]  NML:24.7
     Ht:6'3 4/8"  Wt:241  Hand:10.50"  Vert:—
101. Romello Height               EDGE   Texas Tech             #77    40:4.64  RAS:8.8  Age:25.0  [AVG          ~79-82]  NML:24.5
     Ht:6'2 6/8"  Wt:239  Hand:9.50"  Vert:39.0"
102. Charles Demmings             CB     Stephen F. Austin      #161   40:4.41  RAS:—  Age:23.1  [GOOD         ~86-88]  NML:24.5
     Ht:6'1 1/8"  Wt:193  Hand:10.12"  Vert:42.0"
103. Josh Cameron                 WR     Baylor                 #156   40:—  RAS:—  Age:23.1  [?            ~?]  NML:24.3
     Ht:6'1 4/8"  Wt:220  Hand:10.25"  Vert:—
104. Kevin Coleman Jr.            WR     Missouri               #181   40:4.49  RAS:6.4  Age:22.6  [AVG          ~83-85]  NML:24.3
     Ht:5'10 2/8"  Wt:179  Hand:9.50"  Vert:38.5"
105. Kendrick Law                 WR     Kentucky               #184   40:4.45  RAS:9.6  Age:21.9  [AVG          ~83-85]  NML:24.3
     Ht:5'11 3/8"  Wt:203  Hand:9.62"  Vert:42.0"
106. Hezekiah Masses              CB     California             #148   40:4.46  RAS:3.4  Age:21.8  [AVG          ~83-85]  NML:24.0
     Ht:6'0 5/8"  Wt:179  Hand:8.25"  Vert:31.5"
107. Jadon Canady                 CB     Oregon                 #157   40:4.47  RAS:6.6  Age:23.0  [AVG          ~83-85]  NML:24.0
     Ht:5'10 4/8"  Wt:181  Hand:9.25"  Vert:—
108. Christen Miller              DT     DL                     #46    40:—  RAS:—  Age:21.7  [?            ~?]  NML:23.8
     Ht:6'3 6/8"  Wt:321  Hand:10.00"  Vert:—
109. Adam Randall                 RB     Clemson                #179   40:4.50  RAS:9.4  Age:21.8  [SLOW         ~<83]  NML:23.8
     Ht:6'3 3/8"  Wt:232  Hand:9.75"  Vert:37.0"
     ⚠️ NML reach risk: may go as early as pick #161 (Clemson loyalty reach, young prospect)
110. Reggie Virgil                WR     Texas Tech             #197   40:4.57  RAS:7.6  Age:21.9  [SLOW         ~<83]  NML:23.4
     Ht:6'2 5/8"  Wt:187  Hand:9.25"  Vert:36.0"
111. Kaytron Allen                RB     Penn State             #140   40:—  RAS:—  Age:23.3  [?            ~?]  NML:22.9
     Ht:5'11 3/8"  Wt:216  Hand:9.50"  Vert:—
112. Blake Miller                 OT     Clemson                #25    40:5.04  RAS:9.9  Age:22.2  [SLOW-trench  ~<73]  NML:22.8
     Ht:6'6 6/8"  Wt:317  Hand:9.75"  Vert:32.0"
113. Caleb Lomu                   OT     Utah                   #26    40:4.99  RAS:9.8  Age:21.3  [AVG-trench   ~73-77]  NML:22.8
     Ht:6'6 2/8"  Wt:313  Hand:9.50"  Vert:32.5"
114. Max Iheanachor               OT     Arizona State          #31    40:4.91  RAS:9.9  Age:22.5  [AVG-trench   ~73-77]  NML:22.8
     Ht:6'5 7/8"  Wt:321  Hand:9.00"  Vert:30.5"
115. TJ Hall                      CB     Iowa                   #176   40:4.59  RAS:5.3  Age:22.0  [SLOW         ~<83]  NML:22.4
     Ht:6'0 6/8"  Wt:189  Hand:9.50"  Vert:36.0"
116. Domani Jackson               CB     Alabama                #192   40:4.41  RAS:9.0  Age:23.4  [GOOD         ~86-88]  NML:22.3
     Ht:6'0 6/8"  Wt:194  Hand:9.12"  Vert:—
117. Michael Trigg                TE     Baylor                 #120   40:—  RAS:—  Age:23.8  [?            ~?]  NML:22.2
     Ht:6'3 6/8"  Wt:240  Hand:10.50"  Vert:—
118. Ephesians Prysock            CB     Washington             #142   40:4.45  RAS:9.7  Age:23.1  [AVG          ~83-85]  NML:21.6
     Ht:6'3 3/8"  Wt:196  Hand:9.75"  Vert:39.0"
119. Caleb Banks                  DT     DL                     #39    40:5.04  RAS:9.8  Age:23.1  [SLOW-trench  ~<73]  NML:21.4
     Ht:6'6 2/8"  Wt:327  Hand:10.88"  Vert:32.0"
120. Lee Hunter                   DT     DL                     #49    40:5.18  RAS:4.1  Age:23.8  [SLOW-trench  ~<73]  NML:21.4
     Ht:6'3 4/8"  Wt:318  Hand:9.25"  Vert:21.5"
121. Olaivavega Ioane             IOL    Penn State             #16    40:—  RAS:—  Age:22.0  [?            ~?]  NML:21.0
     Ht:6'4 2/8"  Wt:320  Hand:10.50"  Vert:31.5"
122. Kaleb Elarms-Orr             LB     TCU                    #130   40:4.47  RAS:9.3  Age:22.6  [GREAT        ~86-88]  NML:20.9
     Ht:6'2"  Wt:234  Hand:9.00"  Vert:40.0"
123. Harold Perkins               LB     LSU                    #132   40:4.45  RAS:8.6  Age:21.6  [GREAT        ~86-88]  NML:20.9
     Ht:6'0 7/8"  Wt:223  Hand:8.12"  Vert:—
124. Jalen Huskey                 CB     Maryland               #190   40:4.55  RAS:7.0  Age:22.9  [SLOW         ~<83]  NML:20.8
     Ht:6'1 2/8"  Wt:196  Hand:10.25"  Vert:—
125. Domonique Orange             DT     DL                     #67    40:—  RAS:7.8  Age:22.1  [GOOD-ath     ~85-89]  NML:20.3
     Ht:6'2 3/8"  Wt:322  Hand:10.25"  Vert:—
126. Kaelon Black                 RB     Indiana                #195   40:4.45  RAS:9.1  Age:24.5  [AVG          ~83-85]  NML:19.9
     Ht:5'10"  Wt:211  Hand:—  Vert:—
127. Le'Veon Moss                 RB     Texas A&M              #198   40:4.58  RAS:6.3  Age:23.4  [SLOW         ~<83]  NML:19.9
     Ht:5'11"  Wt:203  Hand:9.50"  Vert:—
128. Eli Raridon                  TE     Notre Dame             #136   40:4.62  RAS:9.5  Age:22.2  [FAST-trench  ~78+]  NML:19.5
     Ht:6'6 1/8"  Wt:245  Hand:10.75"  Vert:36.0"
129. Jack Endries                 TE     Texas                  #154   40:4.62  RAS:8.9  Age:22.1  [FAST-trench  ~78+]  NML:19.5
     Ht:6'4 5/8"  Wt:245  Hand:9.62"  Vert:36.0"
130. L.T. Overton                 EDGE   Alabama                #111   40:4.87  RAS:2.5  Age:—  [SLOW         ~<79]  NML:19.4
     Ht:6'3"  Wt:274  Hand:10.62"  Vert:—
131. Jakobe Thomas                S      Miami (FL)             #166   40:4.57  RAS:7.3  Age:22.8  [SLOW         ~<83]  NML:18.9
     Ht:6'1 2/8"  Wt:211  Hand:10.62"  Vert:—
132. Deontae Lawson               LB     Alabama                #114   40:—  RAS:—  Age:23.2  [?            ~?]  NML:18.8
     Ht:6'2 7/8"  Wt:226  Hand:9.25"  Vert:—
133. Taurean York                 LB     Texas A&M              #149   40:4.59  RAS:5.2  Age:20.8  [AVG          ~79-82]  NML:18.2
     Ht:5'10 6/8"  Wt:226  Hand:8.50"  Vert:—
134. Anthony Lucas                EDGE   USC                    #129   40:—  RAS:—  Age:21.5  [?            ~?]  NML:18.0
     Ht:6'5 4/8"  Wt:256  Hand:10.25"  Vert:—
135. Caden Curry                  EDGE   Ohio State             #144   40:—  RAS:—  Age:22.9  [?            ~?]  NML:18.0
     Ht:6'2 6/8"  Wt:257  Hand:9.38"  Vert:—
136. Joe Royer                    TE     Cincinnati             #153   40:—  RAS:—  Age:24.2  [?            ~?]  NML:17.6
     Ht:6'5 1/8"  Wt:247  Hand:10.75"  Vert:—
137. Gennings Dunker              OT     Iowa                   #62    40:5.18  RAS:8.6  Age:23.0  [SLOW-trench  ~<73]  NML:17.4
     Ht:6'5"  Wt:319  Hand:10.00"  Vert:32.5"
138. Chase Bisontis               IOL    Texas A&M              #40    40:5.02  RAS:9.8  Age:21.9  [SLOW-trench  ~<73]  NML:17.0
     Ht:6'5 2/8"  Wt:315  Hand:9.75"  Vert:32.0"
139. Michael Taaffe               S      Texas                  #160   40:4.50  RAS:7.8  Age:23.2  [SLOW         ~<83]  NML:17.0
     Ht:5'11 7/8"  Wt:190  Hand:9.38"  Vert:—
140. Nate Boerkircher             TE     Texas A&M              #169   40:4.78  RAS:8.9  Age:24.6  [FAST-trench  ~78+]  NML:17.0
     Ht:6'5 4/8"  Wt:245  Hand:10.50"  Vert:—
141. Gracen Halton                DT     DL                     #78    40:4.82  RAS:8.4  Age:22.2  [AVG-trench   ~73-77]  NML:16.8
     Ht:6'2 5/8"  Wt:293  Hand:10.00"  Vert:36.5"
142. Darrell Jackson Jr.          DT     DL                     #85    40:—  RAS:—  Age:23.0  [?            ~?]  NML:16.8
     Ht:6'5 4/8"  Wt:315  Hand:11.00"  Vert:—
143. Keyshaun Elliott             LB     Arizona State          #133   40:4.58  RAS:8.7  Age:22.4  [AVG          ~79-82]  NML:16.5
     Ht:6'1 6/8"  Wt:231  Hand:9.25"  Vert:38.0"
144. Aiden Fisher                 LB     Indiana                #155   40:4.76  RAS:6.3  Age:22.3  [SLOW         ~<79]  NML:16.5
     Ht:6'0 7/8"  Wt:232  Hand:9.50"  Vert:—
145. Jimmy Rolder                 LB     Michigan               #159   40:—  RAS:9.5  Age:22.2  [ELITE-ath    ~90+]  NML:16.5
     Ht:6'2 4/8"  Wt:238  Hand:9.75"  Vert:36.0"
146. Marlin Klein                 TE     Michigan               #175   40:4.61  RAS:9.0  Age:23.6  [FAST-trench  ~78+]  NML:16.4
     Ht:6'6"  Wt:248  Hand:9.25"  Vert:36.0"
147. Max Llewellyn                EDGE   Iowa                   #151   40:4.81  RAS:8.2  Age:23.7  [SLOW         ~<79]  NML:16.2
     Ht:6'5 5/8"  Wt:258  Hand:9.00"  Vert:32.5"
148. Wesley Williams              EDGE   DL                     #185   40:4.89  RAS:7.5  Age:21.6  [SLOW         ~<79]  NML:16.2
     Ht:6'3 6/8"  Wt:256  Hand:9.50"  Vert:35.5"
149. Connor Lew                   IOL    Auburn                 #68    40:—  RAS:—  Age:20.6  [?            ~?]  NML:16.0
     Ht:6'3 4/8"  Wt:310  Hand:9.00"  Vert:—
150. Caleb Tiernan                OT     Northwestern           #64    40:—  RAS:9.4  Age:23.2  [ELITE-ath    ~90+]  NML:15.7
     Ht:6'7 5/8"  Wt:323  Hand:9.00"  Vert:35.5"

---
## 2026 DRAFT PICK MAP

### Round 1 Pick Assignments (slot → current owner)

  Pick # 1 → Seattle Seahawks               (from New York Giants)
  Pick # 2 → Las Vegas Raiders              (from Los Angeles Rams) ◄ RAIDERS
  Pick # 3 → Las Vegas Raiders              (from Carolina Panthers) ◄ RAIDERS
  Pick # 4 → Las Vegas Raiders              (from Indianapolis Colts) ◄ RAIDERS
  Pick # 5 → Kansas City Chiefs             (from Denver Broncos)
  Pick # 6 → Las Vegas Raiders              (from Cleveland Browns) ◄ RAIDERS
  Pick # 7 → Las Vegas Raiders              (from Chicago Bears) ◄ RAIDERS
  Pick # 8 → Baltimore Ravens               (from Arizona Cardinals)
  Pick # 9 → Cleveland Browns               (from Pittsburgh Steelers)
  Pick #10 → Las Vegas Raiders              (own) ◄ RAIDERS
  Pick #11 → San Francisco 49ers            (from Philadelphia Eagles)
  Pick #12 → Las Vegas Raiders              (from Baltimore Ravens) ◄ RAIDERS
  Pick #13 → Las Vegas Raiders              (from New York Jets) ◄ RAIDERS
  Pick #14 → Seattle Seahawks               (from Los Angeles Chargers)
  Pick #15 → Las Vegas Raiders              (from Detroit Lions) ◄ RAIDERS
  Pick #16 → Las Vegas Raiders              (from New Orleans Saints) ◄ RAIDERS
  Pick #17 → Las Vegas Raiders              (from Atlanta Falcons) ◄ RAIDERS
  Pick #18 → New York Jets                  (from New England Patriots)
  Pick #19 → Minnesota Vikings              (from Green Bay Packers)
  Pick #20 → New Orleans Saints             (from Kansas City Chiefs)
  Pick #21 → Philadelphia Eagles            (from Tampa Bay Buccaneers)
  Pick #22 → Buffalo Bills                  (from Jacksonville Jaguars)
  Pick #23 → Seattle Seahawks               (from Dallas Cowboys)
  Pick #24 → Las Vegas Raiders              (from Tennessee Titans) ◄ RAIDERS
  Pick #25 → Las Vegas Raiders              (from Buffalo Bills) ◄ RAIDERS
  Pick #26 → Las Vegas Raiders              (from San Francisco 49ers) ◄ RAIDERS
  Pick #27 → Dallas Cowboys                 (from Seattle Seahawks)
  Pick #28 → Houston Texans                 (own)
  Pick #29 → Miami Dolphins                 (own)
  Pick #30 → Carolina Panthers              (from Washington Commanders)
  Pick #31 → Carolina Panthers              (from Minnesota Vikings)
  Pick #32 → Kansas City Chiefs             (from Cincinnati Bengals)
  Pick #33 → Arizona Cardinals              (own)

### 2026 Picks Per Team (R1-R4)

  Arizona Cardinals                R1:1 | R2:1 | R3:1 | R4:0 | Total R1-R4: 3
  Atlanta Falcons                  R1:0 | R2:1 | R3:0 | R4:0 | Total R1-R4: 1
  Baltimore Ravens                 R1:1 | R2:0 | R3:1 | R4:1 | Total R1-R4: 3
  Buffalo Bills                    R1:1 | R2:0 | R3:0 | R4:0 | Total R1-R4: 1
  Carolina Panthers                R1:2 | R2:0 | R3:0 | R4:0 | Total R1-R4: 2
  Chicago Bears                    R1:0 | R2:1 | R3:1 | R4:4 | Total R1-R4: 6
  Cincinnati Bengals               R1:0 | R2:1 | R3:4 | R4:2 | Total R1-R4: 7
  Cleveland Browns                 R1:1 | R2:1 | R3:0 | R4:0 | Total R1-R4: 2
  Dallas Cowboys                   R1:1 | R2:0 | R3:0 | R4:1 | Total R1-R4: 2
  Denver Broncos                   R1:0 | R2:3 | R3:2 | R4:2 | Total R1-R4: 7
  Detroit Lions                    R1:0 | R2:1 | R3:2 | R4:0 | Total R1-R4: 3
  Green Bay Packers                R1:0 | R2:2 | R3:6 | R4:0 | Total R1-R4: 8
  Houston Texans                   R1:1 | R2:1 | R3:1 | R4:1 | Total R1-R4: 4
  Indianapolis Colts               R1:0 | R2:3 | R3:2 | R4:3 | Total R1-R4: 8
  Jacksonville Jaguars             R1:0 | R2:2 | R3:1 | R4:1 | Total R1-R4: 4
  Kansas City Chiefs               R1:2 | R2:0 | R3:0 | R4:1 | Total R1-R4: 3
  Las Vegas Raiders                R1:14 | R2:6 | R3:1 | R4:1 | Total R1-R4: 22 ◄
  Los Angeles Rams                 R1:0 | R2:1 | R3:3 | R4:2 | Total R1-R4: 6
  Miami Dolphins                   R1:1 | R2:1 | R3:2 | R4:1 | Total R1-R4: 5
  Minnesota Vikings                R1:1 | R2:2 | R3:0 | R4:0 | Total R1-R4: 3
  New Orleans Saints               R1:1 | R2:1 | R3:1 | R4:0 | Total R1-R4: 3
  New York Jets                    R1:1 | R2:1 | R3:2 | R4:6 | Total R1-R4: 10
  Philadelphia Eagles              R1:1 | R2:1 | R3:1 | R4:1 | Total R1-R4: 4
  Pittsburgh Steelers              R1:0 | R2:1 | R3:1 | R4:1 | Total R1-R4: 3
  San Francisco 49ers              R1:1 | R2:1 | R3:0 | R4:0 | Total R1-R4: 2
  Seattle Seahawks                 R1:3 | R2:0 | R3:1 | R4:2 | Total R1-R4: 6
  Tampa Bay Buccaneers             R1:0 | R2:0 | R3:0 | R4:1 | Total R1-R4: 1
  Washington Commanders            R1:0 | R2:1 | R3:0 | R4:1 | Total R1-R4: 2

---
## 2027 DRAFT PICK MAP (current ownership — picks already being traded)

⚠️ 2027 R1 slot order has NOT been determined yet (lottery not run).
Current ownership shows ORIGINAL team only — slot number is unknown until next year's lottery.
Value these picks as 'from [original team]' rather than a specific slot number.

### 2027 Pick Ownership by Team (R1 + R2)

  Washington Commanders            R1: 4 picks [(Carolina Panthers), (Minnesota Vikings), (New York Jets), (Washington Commanders)]  2 R2s ◄◄ FUTURE CAPITAL THREAT
  Seattle Seahawks                 R1: 3 picks [(Atlanta Falcons), (Green Bay Packers), (Seattle Seahawks)]  2 R2s ◄◄ FUTURE CAPITAL THREAT
  Cincinnati Bengals               R1: 2 picks [(Cincinnati Bengals), (Los Angeles Chargers)]  2 R2s
  Kansas City Chiefs               R1: 2 picks [(Kansas City Chiefs), (Tennessee Titans)]  1 R2s
  Las Vegas Raiders                R1: 2 picks [(Chicago Bears), (Las Vegas Raiders)]  1 R2s ◄ RAIDERS
  New Orleans Saints               R1: 2 picks [(New Orleans Saints), (New York Giants)]  1 R2s
  San Francisco 49ers              R1: 2 picks [(Dallas Cowboys), (San Francisco 49ers)]  1 R2s
  Arizona Cardinals                R1: 1 picks [(Arizona Cardinals)]  1 R2s
  Atlanta Falcons                  R1: 1 picks [(Denver Broncos)]  2 R2s
  Baltimore Ravens                 R1: 1 picks [(Baltimore Ravens)]  1 R2s
  Buffalo Bills                    R1: 1 picks [(Buffalo Bills)]  1 R2s
  Cleveland Browns                 R1: 1 picks [(Cleveland Browns)]  1 R2s
  Detroit Lions                    R1: 1 picks [(Detroit Lions)]  2 R2s
  Houston Texans                   R1: 1 picks [(Houston Texans)]  1 R2s
  Indianapolis Colts               R1: 1 picks [(Indianapolis Colts)]  1 R2s
  Jacksonville Jaguars             R1: 1 picks [(Jacksonville Jaguars)]  1 R2s
  Los Angeles Rams                 R1: 1 picks [(Los Angeles Rams)]  1 R2s
  Miami Dolphins                   R1: 1 picks [(Miami Dolphins)]  1 R2s
  New England Patriots             R1: 1 picks [(New England Patriots)]  
  Philadelphia Eagles              R1: 1 picks [(Philadelphia Eagles)]  1 R2s
  Pittsburgh Steelers              R1: 1 picks [(Pittsburgh Steelers)]  1 R2s
  Tampa Bay Buccaneers             R1: 1 picks [(Tampa Bay Buccaneers)]  1 R2s
  Carolina Panthers                R1: 0 picks [none]  1 R2s
  Chicago Bears                    R1: 0 picks [none]  1 R2s
  Dallas Cowboys                   R1: 0 picks [none]  1 R2s
  Los Angeles Chargers             R1: 0 picks [none]  1 R2s
  New York Jets                    R1: 0 picks [none]  1 R2s
  Tennessee Titans                 R1: 0 picks [none]  1 R2s

**Key 2027 intelligence:**
  - Washington Commanders: 4 R1 picks (Carolina Panthers, Minnesota Vikings, New York Jets, Washington Commanders) — major future capital accumulator
  - Seattle Seahawks: 3 R1 picks (Atlanta Falcons, Green Bay Packers, Seattle Seahawks) — major future capital accumulator

  Already-traded 2027 picks (current owner ← original team):
    R1: Atlanta Falcons ← Denver Broncos
    R2: Atlanta Falcons ← Denver Broncos
    R2: Cincinnati Bengals ← Green Bay Packers
    R1: Cincinnati Bengals ← Los Angeles Chargers
    R2: Detroit Lions ← New York Giants
    R1: Kansas City Chiefs ← Tennessee Titans
    R1: Las Vegas Raiders ← Chicago Bears
    R1: New Orleans Saints ← New York Giants
    R1: San Francisco 49ers ← Dallas Cowboys
    R1: Seattle Seahawks ← Atlanta Falcons
    R1: Seattle Seahawks ← Green Bay Packers
    R2: Seattle Seahawks ← New England Patriots
    R1: Washington Commanders ← Carolina Panthers
    R1: Washington Commanders ← Minnesota Vikings
    R2: Washington Commanders ← Minnesota Vikings
    R1: Washington Commanders ← New York Jets

---
## TEAM NEEDS

**Arizona Cardinals**
  Roster weakness: SS(avg 70.3), QB(avg 71.7), CB(avg 72.1), WILL(avg 72.3), WR(avg 73.9)

**Atlanta Falcons**
  Roster weakness: MIKE(avg 65.8), TE(avg 71.7), SS(avg 74.7), REDGE(avg 75.0), QB(avg 75.3)

**Baltimore Ravens**
  Roster weakness: SAM(avg 63.0), MIKE(avg 64.0), LEDGE(avg 68.0), TE(avg 71.7), FS(avg 73.3)

**Buffalo Bills**
  Roster weakness: SAM(avg 64.0), MIKE(avg 67.0), QB(avg 69.5), LEDGE(avg 70.5), WILL(avg 71.0)

**Carolina Panthers**
  Roster weakness: SAM(avg 68.0), MIKE(avg 69.0), LEDGE(avg 72.0), TE(avg 73.5), WR(avg 73.6)

**Chicago Bears**
  Roster weakness: SAM(avg 65.0), WILL(avg 67.0), FS(avg 69.0), REDGE(avg 70.0), CB(avg 72.2)

**Cincinnati Bengals**
  Roster weakness: TE(avg 72.7), WILL(avg 73.6), CB(avg 75.4), QB(avg 76.0), SS(avg 76.0)

**Cleveland Browns**
  Roster weakness: LEDGE(avg 69.0), MIKE(avg 69.8), WILL(avg 70.5), REDGE(avg 70.8), TE(avg 71.3)

**Dallas Cowboys**
  Roster weakness: SAM(avg 72.0), HB(avg 75.0), REDGE(avg 75.3), TE(avg 75.7), FS(avg 76.0)

**Denver Broncos**
  Roster weakness: WILL(avg 67.0), MIKE(avg 68.5), SS(avg 70.0), TE(avg 72.0), LEDGE(avg 72.8)

**Detroit Lions**
  Roster weakness: QB(avg 64.5), MIKE(avg 67.0), SAM(avg 68.0), WILL(avg 68.0), SS(avg 70.7)

**Green Bay Packers**
  Roster weakness: REDGE(avg 70.0), QB(avg 70.3), WILL(avg 72.0), WR(avg 74.3), SS(avg 75.5)

**Houston Texans**
  Roster weakness: TE(avg 67.8), WILL(avg 70.5), FS(avg 72.0), REDGE(avg 73.2), HB(avg 75.2)

**Indianapolis Colts**
  Roster weakness: SAM(avg 65.0), REDGE(avg 68.4), QB(avg 69.0), LEDGE(avg 69.5), CB(avg 71.0)

**Jacksonville Jaguars**
  Roster weakness: QB(avg 67.0), TE(avg 71.3), WR(avg 72.5), CB(avg 73.4), REDGE(avg 73.7)

**Kansas City Chiefs**
  Roster weakness: LEDGE(avg 66.0)

**Las Vegas Raiders**
  Roster weakness: SS(avg 63.0), QB(avg 67.0), HB(avg 71.0), WILL(avg 72.3), FS(avg 72.7)
  Formation: CB-heavy (4-2 Nickel — 3 CBs on field)

**Los Angeles Chargers**
  Roster weakness: QB(avg 65.3), SAM(avg 68.0), REDGE(avg 72.3), LEDGE(avg 73.0), CB(avg 74.3)

**Los Angeles Rams**
  Roster weakness: SAM(avg 70.0), CB(avg 70.8), FS(avg 72.0), SS(avg 72.3), MIKE(avg 74.0)

**Miami Dolphins**
  Roster weakness: TE(avg 67.2), FS(avg 67.4), MIKE(avg 67.7), LEDGE(avg 68.0), SS(avg 68.0)

**Minnesota Vikings**
  Roster weakness: MIKE(avg 69.5), LEDGE(avg 70.0), TE(avg 70.7), QB(avg 71.0), WR(avg 71.0)

**New England Patriots**
  Roster weakness: SS(avg 66.6), CB(avg 70.7), WILL(avg 72.0), LEDGE(avg 73.0), FS(avg 73.7)

**New Orleans Saints**
  Roster weakness: WILL(avg 71.4), SS(avg 71.5), TE(avg 71.5), QB(avg 73.7), REDGE(avg 74.0)

**New York Giants**
  Roster weakness: SAM(avg 69.3), TE(avg 70.3), CB(avg 70.8), QB(avg 72.5), WILL(avg 73.0)

**New York Jets**
  Roster weakness: LEDGE(avg 69.3), SS(avg 69.5), QB(avg 70.3), WILL(avg 71.5), MIKE(avg 71.7)

**Philadelphia Eagles**
  Roster weakness: SS(avg 68.0), TE(avg 68.8), WILL(avg 72.3), LEDGE(avg 73.0), WR(avg 73.1)

**Pittsburgh Steelers**
  Roster weakness: REDGE(avg 62.0), MIKE(avg 70.0), QB(avg 73.5), WR(avg 75.6), WILL(avg 76.6)

**San Francisco 49ers**
  Roster weakness: SAM(avg 66.0), WILL(avg 67.5), QB(avg 68.3), TE(avg 76.5)

**Seattle Seahawks**
  Roster weakness: WILL(avg 67.0), QB(avg 71.3), SS(avg 73.0), LEDGE(avg 74.0), MIKE(avg 74.7)
  Formation: CB-heavy (4-2 Nickel — 3 CBs on field)

**Tampa Bay Buccaneers**
  Roster weakness: SAM(avg 72.0), CB(avg 72.7), REDGE(avg 73.0), MIKE(avg 74.0), HB(avg 74.3)

**Tennessee Titans**
  Roster weakness: MIKE(avg 64.5), WILL(avg 64.5), TE(avg 68.0), QB(avg 70.0), WR(avg 70.6)

**Washington Commanders**
  Roster weakness: REDGE(avg 64.5), MIKE(avg 65.5), TE(avg 69.3), WILL(avg 70.3), QB(avg 71.0)
  Formation: CB-heavy (4-2 Nickel — 3 CBs on field)

---
## OWNER TENDENCY PROFILES (abbreviated)

Use these to predict what each team will likely draft and who they'll overpay for in trades.

**Atlanta Falcons** (R1: 0, total 2026: 1)
  Alabama superfan. Will reach for Alabama players. 7 Alabama players on roster. 3 Alabama draft picks in recent history.

**Carolina Panthers** (R1: 2, total 2026: 2)
  HUGE Clemson fan. Will reach for Clemson players at any position. 12 Clemson players currently on roster. Easy to overpay — offer them any high-quality Clemson player and they'll give up extra value.

**Chicago Bears** (R1: 0, total 2026: 13)
  Iowa/Iowa State fan, Kansas City Chiefs fan. Drafts Iowa/ISU players heavily (ISU = #1 drafted school). Pass-heavy style.

**Cleveland Browns** (R1: 1, total 2026: 3)
  UNC superfan. 11 UNC players on roster, 11 UNC draft picks 2020+. Will reach for UNC players. Strong drafter historically.

**Denver Broncos** (R1: 0, total 2026: 14)
  Arizona State / Cardinals fan. Weaker drafter, may not attend full draft — potential pick acquisition target for Jon.

**Green Bay Packers** (R1: 0, total 2026: 11)
  Run-first, Packers fan. 53% rush rate. Will target HBs and OL. No R1 picks in 2026.

**Indianapolis Colts** (R1: 0, total 2026: 15)
  0 R1 picks in 2026 but 15 total picks. Deep draft haul — will be active R2+.

**Kansas City Chiefs** (R1: 2, total 2026: 3)
  Boise State / Seahawks / Chiefs fan. Limited R1 picks in 2026.

**Las Vegas Raiders** (R1: 14, total 2026: 25)
  COMMISSIONER (Jon). 14 R1 picks. Asset accumulation strategy — drafts surplus at premium positions (WR, CB, HB), then trades excess for value. BPA drafter, no school loyalty. Proxy-drafts for absent owners. Will trade back for more picks. Current goal: flip CB/WR surplus for QB upgrade + future picks. QB (JJ McCarthy 71 OVR) is intentionally weak — traded Mahomes for picks.

**Miami Dolphins** (R1: 1, total 2026: 8)
  Good at game, poor at roster mgmt. Will take high-OVR players regardless of positional fit. Easy trade partner if you offer them a name player.

**New York Giants** (R1: 0, total 2026: 0)
  Giants fan. Jon has successfully sold overvalued players to this owner multiple times. Overpays for known names.

**New York Jets** (R1: 1, total 2026: 27)
  1 R1 pick but 27 total picks (most in league after Raiders). Very active drafter.

**Tennessee Titans** (R1: 0, total 2026: 2)
  Tennessee fan. 6 Tennessee players on roster, 7 Tennessee draft picks.

---
## RAIDERS (JON) — DRAFT STRATEGY CONTEXT

**Picks owned:** R1 slots #2, 3, 4, 6, 7, 10, 12, 13, 15, 16, 17, 24, 25, 26 (14 of 33 R1 picks)
**R2 picks:** 6 picks | **Total 2026 picks:** 25

**Current roster strengths (trade surplus):**
  - CB: 7 players including McDuffie (94 OVR), Stingley (92), Sauce Gardner (90) — 3 elite CBs is too many, at least 1-2 are trade chips
  - WR: 6 players including Jameson Williams (85), Rome Odunze (82), Brian Thomas Jr (81) — surplus at this position too
  - DT: 4 players at solid depth — Jordan Davis (82), Braden Fiske (80), Mason Graham (80)

**DEFENSIVE PHILOSOPHY — Press Man Coverage (critical for evaluating DBs):**
  Jon plays press man coverage and is poor at playing zone defense in Madden.
  This means man coverage (MCOV) and press ratings are MORE important than raw speed for DBs.
  Formation: 4-2 Nickel — 3 CBs on field simultaneously.

  The 4-DB requirement breakdown:
  - CB1, CB2, CB3: All need HIGH press + HIGH mcov. Press man on every receiver.
  - DB4 (plays SS slot): Needs 80+ mcov specifically for TE matchups. Can be CB/FS/SS.
    Example plan: If Delane + McCoy have higher mcov than Cole Bishop (current SS),
    they could legitimately start at FS/SS while keeping Bishop as backup.
  - Safety on RB: Needs 80+ mcov even though speed matters less here.

  ⚠️ MCOV LIMITATION: EA does not publish pre-draft man coverage ratings for prospects.
  These are assigned at Madden launch based on film. Best proxy available: college scheme usage.
  CBs who played primarily press/man coverage in college tend to get higher mcov.
  Delane (LSU): press-heavy scheme. McCoy (Tennessee): press-heavy scheme. Both favorable.
  Use this as soft signal only — actual mcov at launch could differ significantly.

  IMPLICATION: Jon wants MORE CBs, not fewer. Current plan is to draft 2 more this year,
  hold all 5 (McDuffie/Stingley/Sauce + 2 new), trade veterans at 27-28 when market is peak.
  DO NOT suggest trading existing CBs unless someone offers a massive overpay.

**Current roster weaknesses (true needs):**
  - QB: JJ McCarthy (71 OVR) — intentionally weak, but a developmental QB upgrade via draft is desirable
  - HB: Isaac Guerendo (73), Trevor Etienne (71), Rasheen Ali (69) — all below average
  - LEDGE: Chop Robinson (75) — only one starter-quality edge rusher
  - SS: avg OVR in the 63-70 range — the single biggest positional weakness
  - No elite WR size+speed combination yet (Brian Thomas Jr is the best at 81 OVR)
  - OL — CRITICAL GAP (3 missing starters, must be addressed via draft or trade before M27 season):
      LT: NO player — roster has Darnell Wright (RT, 87) and Amarius Mims (RT, 76) only.
          One RT will be forced to play LT (wrong side). A true LT is a must-acquire.
      LG: NO player — Alijah Vera-Tucker is RG only. Left guard spot is completely empty.
      C:  NO player — center position completely empty.
      Note: In NML, OL positions are pooled (best available starts regardless of side label),
      but having zero LT/LG/C means no depth and forces wrong-side starters everywhere.
      Drafting or trading for OL is not glamorous but is a prerequisite for a functional offense.

**QB strategy (critical context):**
  - If SEA takes Love at #1: Jon takes Mendoza at #2 (QB of the moment)
  - If SEA takes Mendoza at #1: Jon pivots — drafts 2 developmental QBs later in R1
  - Even if Jon drafts Mendoza, he is NOT fully sold on him (Mendoza is slow for modern QB)
  - Jon already acquired CHI 2027 1st (bottom-3 team historically) as part of Mahomes trade — preparing for 2027 QB class
  - Strategy: draft 2 QBs regardless (one to develop, one to flip for picks)

**Draft goals for Friday:**
  1. QB: At least 2 QBs drafted. Mendoza if SEA takes Love at #1. Otherwise 2 developmental options.
  2. WR: Carnell Tate (OSU WR factory — elite NFL production rate despite not being a speed freak)
  3. EDGE/LB hybrid: Arvell Reese (#2 overall) — LB in college, converting to EDGE like Micah Parsons. High risk/reward.
     Also want David Bailey (true EDGE speed rusher)
  4. S: Both Caleb Downs AND Dillon Thieneman — Jon wants to draft both safeties this class
  5. CB: Mansoor Delane (#1 CB target), Jermod McCoy (#2). Also like Chris Johnson, D'Angelo Ponds
  6. LB: Sonny Styles (traded away Roquan Smith in preparation). Also Jacob Rodriguez, Kaleb Elarms-Orr
  7. TE: Kenyon Sadiq (elite TE speed) — but Jon rarely throws to TE, so lower priority than WR
  8. HB: Love > Washington > Price. Speed is primary filter.
  9. Several picks = proxy picks for absent owners (traded before 53-man cut)
  10. Willing to trade back for extra picks if no compelling player available at a slot

**Trade targets (who to sell CBs/WRs to):**
  - Panthers: will overpay for anything. Especially if you can offer a Clemson player.
  - Giants: historically overpays for name players Jon has acquired cheap.
  - Broncos: limited picks, may trade a future pick for a starter-quality player now.
  - Ravens: actively seeking WR — offered a pick for Odunze (Jon declined so far)
  - Chiefs: actively discussing McDuffie trade (see Trade Intel section)
  - Any team with 0 R1 picks that needs help at WR or CB.

---
## JON'S PERSONAL DRAFT BOARD (specific targets + reasoning)

These are players Jon has flagged regardless of algorithm. Factor these heavily into Output 4.

**SIZE PREFERENCE (applies across WR/TE/CB/S):**
  Jon prefers taller players with larger hands and better vertical jump at all skill positions.
  Priority filter after speed: Height > Hand size > Vertical jump > Weight.
  Reason: Madden has a long-standing bug where two players with identical speed ratings
  actually run at slightly different speeds in open field — taller players are fractionally faster
  on long runs. Over a full season this compounds into real scoring differences.
  Also: large hands = better catch rating floor in Madden. Tall WRs with big hands score higher
  on contested catch, spec catch, and release ratings, which matter for press coverage matchups.
  Preferred profiles: WR 6'1"+ with 9.5"+ hands. TE 6'4"+ with 10"+ hands. CB 6'0"+ preferred.

### QB
  - **Fernando Mendoza** (#1, Indiana) — Top target IF SEA takes Love. Caveat: slow for modern QB.
    Jon not 100% sold even if he drafts him. Preparing 2027 QB class as backup (CHI 27 1st).
  - Any 2nd QB available: Ty Simpson, Drew Allar, Garrett Nussmeier — want 2 QBs regardless.

### WR
  - **Carnell Tate** (#7, Ohio State, 4.53 40) — Priority despite below-average speed.
    Reasoning: OSU WR coach produces elite NFL producers regardless of combine speed.
    Jon is intentionally shifting from pure speed drafting to NFL success rate.
    Historical OSU WRs: Justin Fields-era group, Jaxon Smith-Njigba, Marvin Harrison Jr.

### EDGE / LB Hybrid
  - **Arvell Reese** (#2 overall, LB, Ohio State) — Jon's highest-upside pick.
    Comp: Micah Parsons — played ILB in college, converted to EDGE in NFL, became elite.
    Reese is attempting same conversion. Risk: if conversion fails, stays LB (lower NML value).
    Upside: if conversion succeeds, becomes elite EDGE rusher (highest NML value at that position).
    Jon traded away Roquan Smith partly to make room for this type of player.
  - **David Bailey** (#3 overall, EDGE, Texas Tech, 4.50 40) — True pass rusher, more certain.

### Safety
  - **Dillon Thieneman** (#18, S, Oregon, 4.35 40 GREAT speed) — Elite safety speed.
  - **Caleb Downs** (#8, S, Ohio State, 4.52 40) — Elite prospect, slower speed tier.
  - Note: Jon wants BOTH of these safeties. Safety is a true need (SS avg low on roster).

### CB
  - **Mansoor Delane** (#10, CB, LSU, 4.38 40) — #1 CB target. GREAT speed + top-10 rank.
  - **Jermod McCoy** (#14, CB, Tennessee, 4.40 40, RAS 9.7) — #2 CB target. GOOD speed, elite RAS.
  - **Chris Johnson** (#38, CB, San Diego State, 4.40 40, RAS 9.8) — Later-round value target.
  - **D'Angelo Ponds** (#51, CB, Indiana, 4.36 40) — Hoosier connection + GREAT speed.

### LB
  - **Sonny Styles** (#5, LB, Ohio State, 4.46 40) — Jon traded Roquan Smith in preparation.
    Styles is the 'heir' LB. Jon is committed to getting him at some slot.
  - **Jacob Rodriguez** (#45, LB, Texas Tech, 4.57 40) — Later-round LB value.
  - **Kaleb Elarms-Orr** (#130, LB, TCU, 4.47 40 GREAT speed) — Speed LB late value.

### TE
  - **Kenyon Sadiq** (#17, TE, Oregon, 4.39 40) — Elite TE speed (GREAT tier). Jon likes but notes:
    a) Smaller frame = overdraft risk in NML. b) Jon barely throws to TE in his offense.
    Would prefer to use those early picks on WR. Sadiq only if falls or traded for.
  - **Oscar Delp** (#83, TE, Georgia, 4.49 40) — Backup TE target, later rounds.
  - **Eli Stowers** (#50, TE, Vanderbilt) — May convert to slot WR in NFL (watch carefully).

### HB
  - **Jeremiyah Love** (#4, RB, Notre Dame, 4.36 40) — #1 HB target. Speed + top rank.
  - **Mike Washington Jr.** (#60, RB, Arkansas, 4.33 40 ELITE) — Elite speed, later value.
  - **Jadarian Price** (#43, RB, Notre Dame, 4.49 40) — Depth option.

---
## PRE-DRAFT TRADE INTEL (known discussions as of April 19, 2026)

These are active or rumored trade discussions that may affect pick availability and board fallout.

### #1 — Seattle Seahawks at Pick #1
  Rumor: SEA is torn between RB Jeremiyah Love (future starter) and QB Fernando Mendoza (trade value).
  Impact on Jon: If SEA takes Love → Jon takes Mendoza at #2 (likely).
  If SEA takes Mendoza → Jon pivots, takes Love or best available at #2, drafts 2 dev QBs later.
  Probability: ~50/50 based on available intel.

### #2 — Baltimore Ravens at Pick #8 (WR interest)
  Ravens want a WR. Have offered a pick for Jon's WR Rome Odunze (82 OVR).
  Jon's current position: declining — would rather draft the #3 or #4 WR in this class than lose Odunze.
  However: if Ravens offer a R1 pick + something else, Jon may reconsider.
  Note: Ravens have Justin Jefferson (94) + Zay Flowers (88) already — they want WR depth, not a #1.
  Jon leverage: Ravens need WR depth more than they need Odunze specifically. Could get overpaid.

### #3 — Cleveland Browns at Pick #9 (Safety interest)
  Browns were reportedly interested in drafting a safety. They traded up from #19 → #9.
  Uncertainty: unclear if trading up changed their draft target (may now target higher position).
  Jon context: Jon owns the safety Jon wants (Downs and Thieneman). Browns at #9 could take one.
  Key risk: If Browns take Thieneman at #9, Jon's safety target pool shrinks significantly.

### #4 — Panthers Picks #30/#31 for LB Jack Campbell (Raiders)
  Panthers have discussed trading both their late R1 picks (#30, #31) to Raiders for LB Jack Campbell.
  Jon's motivation: Getting to 16 R1 picks total (maximum possible).
  Panthers motivation: Jack Campbell is a solid MLB — Panthers need LB (confirmed need).
  Status: Panthers not sure — sticker shock on giving up 2 first-rounders for a player.
  Jon leverage: Panthers will overpay for anything. Campbell is a name player. Keep pushing.
  Note: If this trade happens before draft, Jon gets picks #30+#31, giving him 16 R1 picks.
  ⚠️ VALUATION ALERT: Jon confirmed this deal is UNDERPRICED if it includes Stingley.
  Campbell alone for #30+#31 is fair. Adding Stingley (92 OVR, young, elite) would require
  MUCH more — minimum floor for Stingley alone is 2 current R1s. Do not bundle Stingley cheaply.

### #5 — Chiefs / Raiders: Trent McDuffie CB Trade
  CORRECTION: Jon approached the Chiefs — not the other way around.
  Jon's goal: accumulate 2 more R1 picks to reach 16 total first-round picks in a single draft
  (an NML record that would likely be unbreakable). Chiefs have picks #5 (via DEN) and #32 (via CIN) —
  getting both would accomplish this goal in one trade.

  Status: Active discussion. No price agreed. McDuffie listed on Raiders trade block at "$$$".

  CHIEFS INTENT — CRITICAL CORRECTION:
  Previous analysis assumed Chiefs would flip McDuffie. This is WRONG.
  The Chiefs would KEEP McDuffie as a starting CB upgrade and move their current depth.
  Evidence: Chiefs have placed Nate Hobbs (CB, 80 OVR) on trade block with note
  "Looking for draft pick(s) or can add to upgrade at corner" — this is explicit confirmation
  that they want McDuffie as a long-term STARTER, not a chip. Tariq Woolen (81 OVR) is also
  expected to be moved once McDuffie arrives.
  Post-trade Chiefs CB room would be: Witherspoon (91, age 25) + McDuffie (94, age 25) — elite CB duo locked in for 5+ years.
  They would recoup assets by trading Woolen (age 26) and/or Hobbs (age 26).

  PRICE IMPLICATION: Because Chiefs want McDuffie as a keeper (not a flip), their motivation
  to pay a premium is HIGHER than if they were treating him as a trade chip. They are buying
  a foundational piece, not renting an asset. Price accordingly — do not let them lowball.

  Jon's framing: McDuffie is surplus (has Stingley 92 + Gardner 90 as backups — 3 elite CBs).
  What Jon should demand:
    - MINIMUM to accept: both Chiefs R1 picks (#5 via DEN + #32 via CIN)
    - IDEAL: both R1s + a young player or R2 on top
    - Jon's primary goal is the 16-pick record — getting both #5 and #32 in one deal accomplishes it
    - Do NOT accept only one R1 (even #5 alone) — requires both to hit the record
    - Chiefs have 2 R1s available and strong motivation; hold firm on both

---
## CURRENT NML POSITION SCARCITY

Pos | n | avg_OVR | max | elite85 | solid80 | avg_spd
  LT       n=58   avg=76.7  max=97   elite(85+)=15   solid(80+)=22   avg_spd=69.4
  K        n=40   avg=76.6  max=88   elite(85+)=3    solid(80+)=10   avg_spd=73.6
  HB       n=131  avg=76.5  max=98   elite(85+)=17   solid(80+)=36   avg_spd=89.8
  FS       n=70   avg=76.0  max=94   elite(85+)=8    solid(80+)=20   avg_spd=88.8
  P        n=33   avg=75.8  max=86   elite(85+)=1    solid(80+)=2    avg_spd=76.1
  WR       n=224  avg=75.5  max=99   elite(85+)=27   solid(80+)=54   avg_spd=90.9
  REDGE    n=94   avg=74.9  max=99   elite(85+)=11   solid(80+)=17   avg_spd=83.5
  LEDGE    n=95   avg=74.9  max=97   elite(85+)=9    solid(80+)=22   avg_spd=82.8
  DT       n=157  avg=74.8  max=96   elite(85+)=17   solid(80+)=34   avg_spd=73.1
  SS       n=86   avg=74.7  max=93   elite(85+)=8    solid(80+)=18   avg_spd=88.7
  C        n=47   avg=74.6  max=95   elite(85+)=6    solid(80+)=12   avg_spd=68.5
  CB       n=229  avg=74.5  max=97   elite(85+)=21   solid(80+)=45   avg_spd=90.8
  RT       n=61   avg=74.4  max=99   elite(85+)=6    solid(80+)=16   avg_spd=69.2
  MIKE     n=76   avg=74.0  max=97   elite(85+)=10   solid(80+)=21   avg_spd=86.0
  RG       n=69   avg=73.9  max=95   elite(85+)=7    solid(80+)=12   avg_spd=67.7
  TE       n=96   avg=73.5  max=98   elite(85+)=9    solid(80+)=19   avg_spd=84.3
  FB       n=14   avg=73.4  max=88   elite(85+)=1    solid(80+)=3    avg_spd=82.1
  LG       n=66   avg=73.3  max=96   elite(85+)=6    solid(80+)=11   avg_spd=68.6
  WILL     n=85   avg=72.9  max=90   elite(85+)=4    solid(80+)=14   avg_spd=86.1
  QB       n=80   avg=72.9  max=99   elite(85+)=13   solid(80+)=18   avg_spd=83.1
  SAM      n=23   avg=70.5  max=84   elite(85+)=0    solid(80+)=1    avg_spd=85.3
  LS       n=23   avg=70.0  max=81   elite(85+)=0    solid(80+)=2    avg_spd=73.2

---
## DRAFT LOGISTICS & APP MECHANICS

The NML uses a custom-built web app (Flask + SQLite backend, single-page JS frontend) to run the draft.
Jon is the commissioner and has full admin control during the draft. Understanding the app mechanics
matters for strategy — especially around trading on the clock and proxy picks.

### Draft Format
  - **Linear pick order** — same as NFL (pick #1 through #247+), NOT a snake draft
  - **Timed picks** — server-enforced countdown per pick:
    - R1: 10 minutes | R2: 7 minutes | R3: 5 minutes | R4: 4 minutes | R5-R7: 3 minutes
    - Commissioner can override timer lengths in league settings before the draft
  - **All owners use the app** — picks submitted via web interface (desktop or mobile)
  - **Draft runs in real-time** — app polls every 5 seconds for state changes
  - **Discord notifications** — each pick auto-posts to the league Discord channel

### Trading During the Draft (critical for Jon's strategy)
  - **Picks CAN be traded at any time**, including while another owner is on the clock
  - When a pick changes hands mid-draft, the app immediately re-renders showing the new owner on the clock
  - This means Jon can negotiate and execute trades BETWEEN his own picks while others are drafting
  - The 10-minute R1 timer gives ample time to negotiate even while someone is on the clock
  - Jon's playbook: use the time between his picks to approach teams actively for deals
  - Example: Jon at pick #2, next pick at #3. While someone else is on the clock at an intervening pick,
    Jon can finalize trades, then submit picks back-to-back when it's his turn

### Draft Queue (for proxy picks & absent owners)
  - Every owner can pre-queue a ranked list of players before/during the draft
  - When it's their turn, the app auto-submits the first available queued player
  - **Commissioner (Jon) can toggle auto-submit for any team** — critical for proxy drafting
  - For absent owners, Jon pre-queues their picks, then those picks auto-fire when it's their turn
  - Jon typically trades most proxy-drafted players to that owner before the 53-man roster cut
  - Owners who haven't filled their queue get a 'queue is empty' warning on their clock

### Makeup Queue (expired timers)
  - If a pick timer expires without a pick being submitted, the pick goes into a 'Makeup Queue'
  - The draft advances to the next pick — makeup picks are submitted separately in parallel
  - This prevents one slow owner from stalling the entire draft
  - Commissioner sees the makeup queue and can prompt/submit for absent owners

### Commissioner-Only Controls
  - Start / Pause / Resume / Skip Pick / Reset draft
  - See all teams' queues and their auto-submit status
  - Submit picks on behalf of any team (used for proxy/absent owners)
  - Write-in any player by name+position (for players not in the DB)

### What This Means for Jon's Draft Strategy
  1. Jon doesn't need to make all trade decisions before draft day — live negotiation is part of the game
  2. With 14 consecutive picks in some stretches, Jon can work the phones (Discord DMs) aggressively
  3. Absent owners' picks go through Jon as proxy — he has full discretion on those picks
     and will trade those players to the owner before the 53-man cut, keeping asset value himself
  4. The makeup queue means if someone gets distracted, Jon can keep the draft moving
  5. Jon can use the 10-min R1 timer during other owners' picks to finalize deals in Discord

### App Features Relevant to Opus
  The app has a full **Prospect Board** (the 2026 draft board Jon built) visible to all owners.
  It includes NML Madden Value scores, position ranks, 40-times, RAS, and consensus rankings.
  All owners can see the same board — there is no information asymmetry on player data.
  The **Trade Center** (commissioner-only) shows all proposed/accepted/rejected trades in real time.
  The **Pick Tracker** shows current pick ownership for all rounds, updated live as trades happen.

---
## WHAT I NEED FROM YOU

Please produce the following four outputs, in order:

### OUTPUT 1 — Prospect Tier List (NML Madden Value)
Re-rank the top 60 available prospects by your assessed NML Madden Value.
Use the NML_Value score in this doc as a starting point but apply your own judgment.
Group into tiers: S-Tier, Tier 1, Tier 2, Tier 3.
For each player note: projected Madden speed rating range, NFL role projection, development timeline, and NML fit score.

### OUTPUT 2 — Full NML R1 Mock Draft (All 33 Picks)
Produce a complete, standalone 33-pick R1 NML mock draft table. Every pick must be listed.
Format each row as:
  #[slot] | [Current Owner] ([Original Team if traded]) | [Player Name] | [Pos] | [Reasoning — 1 sentence]

Rules:
- Use the AVAILABLE-AT-YOUR-PICK simulation and owner tendency profiles to project each pick
- Where two scenarios diverge (e.g., SEA takes Love vs Mendoza at #1), show SCENARIO A and SCENARIO B
  as separate full tables, not just a note
- Raiders picks (#2,3,4,6,7,10,12,13,15,16,17,24,25,26) must be tagged:
  KEEP if Jon should use for himself | FLIP if best used as trade currency | PROXY if use to move up
- After the table(s), add a short section: 'Notable reaches', 'Steals', and 'Surprise picks'
- NML reach risk warnings from the prospect board should factor in here

### OUTPUT 3 — Trade Value Targets
Given the Raiders' CB and WR surplus:
  a) Which teams are most likely to overpay for McDuffie (94 CB), Stingley (92 CB), or Sauce Gardner (90 CB)?
  b) What should Jon demand in return (picks, players, combos)?
  c) Which owners historically overpay and should be prioritized as trade targets?

### OUTPUT 4 — Raiders Pick-by-Pick Suggestions
For each of Jon's 14 R1 picks and 6 R2 picks, suggest:
  - Best available prospect at that slot (based on mock draft fallout)
  - Whether Jon should keep the pick, trade it, or use it as a proxy pick
  - Position priority rationale

---
*End of Opus Session Input. All data is as of April 19-24, 2026.*
*If NFL R1 results are available, nfl_team/nfl_round fields will be populated — adjust Output 1 accordingly.*
---
## FORMATION INTELLIGENCE

**Key principle:** Formation selection reveals which positions actually get snaps.
In Madden, owners fill formation slots with their best athletes regardless of position label.
A team running 4-2 Nickel needs 3 starter-quality CBs. A 3-4 team needs 4 quality LBs.
Cross-position starters (⚡) indicate athlete-over-label philosophy — draft accordingly.

Teams WITH depth charts filled: actual player-level analysis. Teams WITHOUT: inferred from roster + default formation.

**Arizona Cardinals**
  DEFENSE — 3-4 (inferred — heavy LB roster) | No DC on file — inferred from roster
    Top CBs: Dru Phillips (CB, 78), Troy Hill (CB, 76), Nazeeh Johnson (CB, 73)
    Top LBs: Robert Spillane (MIKE, 85), Azeez Al-Shaair (MIKE, 83), Teddye Buchanan (WILL, 75)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Courtland Sutton (87), Tutu Atwell (75), Dyami Brown (75), Devin Duvernay (74)
    Top HBs: Bucky Irving (86), Alvin Kamara (80)

**Atlanta Falcons**
  DEFENSE — 4-2 Nickel (inferred — more CB depth than LB) | No DC on file — inferred from roster
    Top CBs: Marlon Humphrey (CB, 87), Byron Murphy Jr (CB, 84), Tyson Campbell (CB, 79)
    Top LBs: Foyesade Oluokun (WILL, 85), Jamin Davis (MIKE, 67), Matthew Adams (MIKE, 66)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Jakobi Meyers (82), Marvin Mims Jr (78), Nelson Agholor (77), John Metchie III (73)
    Top HBs: Najee Harris (80), Jerome Ford (75)

**Baltimore Ravens**
  DEFENSE — 3-4 (inferred — heavy LB roster) | No DC on file — inferred from roster
    Top CBs: Quinyon Mitchell (CB, 89), Jamel Dean (CB, 86), Maxwell Hairston (CB, 78)
    Top LBs: Tremaine Edmunds (WILL, 82), Anthony Walker Jr (WILL, 73), Jack Gibbens (WILL, 72)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Justin Jefferson (94), Zay Flowers (88), Adam Thielen (75), Ja'Lynn Polk (73)
    Top HBs: David Montgomery (84), Ray Davis (75)

**Buffalo Bills**
  DEFENSE — 4-2 Nickel (inferred — more CB depth than LB) | No DC on file — inferred from roster
    Top CBs: Denzel Ward (CB, 93), Kenny Moore II (CB, 86), Marshon Lattimore (CB, 84)
    Top LBs: Germaine Pratt (WILL, 81), Jaylan Ford (WILL, 69), Owen Pappoe (MIKE, 67)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: DJ Moore (85), Khalil Shakir (82), Brandin Cooks (78), Ryan Flournoy (76)
    Top HBs: Javonte Williams (85), Jordan Mason (81)

**Carolina Panthers**
  DEFENSE — 4-2 Nickel: [4 DL, 2 LB, 2 CB, 3 S]
    ⚡ Cross-position starters: Isaiah Simmons (FS → NB slot, 74 OVR)
  OFFENSE — Shotgun 3WR: [1 QB, 1 HB, 3 WR, 1 TE, 5 OL]

**Chicago Bears**
  DEFENSE — 4-2 Nickel (inferred — more CB depth than LB) | No DC on file — inferred from roster
    Top CBs: Dax Hill (CB, 78), Kader Kohou (CB, 77), Ahkello Witherspoon (CB, 77)
    Top LBs: Logan Wilson (MIKE, 74), Malik Harrison (MIKE, 73), Jeffrey Bassa (WILL, 67)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Alec Pierce (84), Kendrick Bourne (77), Jalen Nailor (77), Tyquan Thornton (75)
    Top HBs: Breece Hall (86), Kareem Hunt (79)

**Cincinnati Bengals**
  DEFENSE — 4-2 Nickel (inferred — more CB depth than LB) | No DC on file — inferred from roster
    Top CBs: D.J. Reed Jr (CB, 87), DaRon Bland (CB, 82), Greg Newsome II (CB, 79)
    Top LBs: Jeremiah Owusu-Koramoah (WILL, 83), Terrel Bernard (MIKE, 83), Justin Strnad (WILL, 74)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Jauan Jennings (81), Marvin Harrison Jr (80), Xavier Worthy (79), Calvin Ridley (78)
    Top HBs: James Cook III (93), Kyle Monangai (78)

**Cleveland Browns**
  DEFENSE — 4-2 Nickel (inferred — more CB depth than LB) | No DC on file — inferred from roster
    Top CBs: Nate Wiggins (CB, 83), Kyler Gordon (CB, 82), Nahshon Wright (CB, 75)
    Top LBs: Cole Holcomb (WILL, 75), Dennis Gardeck (SAM, 74), Marte Mapu (MIKE, 71)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Garrett Wilson (86), Michael Pittman Jr (84), Josh Downs (80), Mack Hollins (77)
    Top HBs: Omarion Hampton (81), Rhamondre Stevenson (77)

**Dallas Cowboys**
  OFFENSE — Shotgun 3WR: [1 QB]

**Denver Broncos**
  DEFENSE — 3-4 (inferred — heavy LB roster) | No DC on file — inferred from roster
    Top CBs: Garrett Williams (CB, 78), Ja'Quan McMillian (CB, 76), Upton Stout (CB, 75)
    Top LBs: Blake Cashman (WILL, 81), Josey Jewell (MIKE, 75), Marcelino McCrary-Ball (WILL, 64)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Jaylen Waddle (86), Troy Franklin (79), Greg Dortch (74), Pat Bryant (72)
    Top HBs: James Conner (83), Cam Skattebo (81)

**Detroit Lions**
  DEFENSE — 3-4 (inferred — heavy LB roster) | No DC on file — inferred from roster
    Top CBs: Christian Benford (CB, 83), Rasul Douglas (CB, 82), L'Jarius Sneed (CB, 80)
    Top LBs: Drew Sanders (MIKE, 71), Smael Mondon Jr. (WILL, 69), Nathaniel Watson (SAM, 68)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: George Pickens (88), Xavier Hutchinson (73), KeAndre Lambert-Smith (70), Bryce Ford-Wheaton (68)
    Top HBs: TreVeyon Henderson (82), Brashard Smith (73)

**Green Bay Packers**
  DEFENSE — 3-4 (inferred — heavy LB roster) | No DC on file — inferred from roster
    Top CBs: Marcus Jones (CB, 82), Keisean Nixon (CB, 78), Jarrian Jones (CB, 78)
    Top LBs: Zaire Franklin (MIKE, 79), Isaiah McDuffie (SAM, 78), Malcolm Rodriguez (SAM, 74)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Jayden Reed (80), Christian Watson (79), Elijah Moore (75), Isaac TeSlaa (73)
    Top HBs: Quinshon Judkins (81), Blake Corum (78)

**Houston Texans**
  DEFENSE — 4-3 (inferred — balanced CB/LB roster) | No DC on file — inferred from roster
    Top CBs: Carlton Davis III (CB, 85), Darious Williams (CB, 76), Martin Emerson Jr (CB, 75)
    Top LBs: Jordyn Brooks (MIKE, 82), Elandon Roberts (MIKE, 76), Christian Rozeboom (WILL, 73)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Puka Nacua (97), Tyreek Hill (92), Chris Godwin Jr (82), Elic Ayomanor (77)
    Top HBs: Gus Edwards (78), Tyjae Spears (77)

**Indianapolis Colts**
  DEFENSE — 4-2 Nickel (inferred — more CB depth than LB) | No DC on file — inferred from roster
    Top CBs: James Pierre (CB, 77), Jarvis Brownlee Jr (CB, 75), Kris Abrams-Draine (CB, 73)
    Top LBs: Ivan Pace Jr (WILL, 77), Ja'Whaun Bentley (MIKE, 76), Eric Kendricks (MIKE, 76)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Tyler Boyd (76), Dontayvion Wicks (76), Ashton Dulin (72), Skyy Moore (72)
    Top HBs: Rico Dowdle (84), Ezekiel Elliott (75)

**Jacksonville Jaguars**
  DEFENSE — 3-4 (inferred — heavy LB roster) | No DC on file — inferred from roster
    Top CBs: Joey Porter (CB, 85), Zyon McCollum (CB, 81), Azareye'h Thomas (CB, 74)
    Top LBs: T.J. Edwards (MIKE, 81), Mack Wilson Sr (WILL, 79), Cedric Gray (WILL, 78)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Rashod Bateman (77), Kalif Raymond (75), Gabe Davis (73), Jacob Cowing (71)
    Top HBs: Ashton Jeanty (83), Tank Bigsby (77)

**Kansas City Chiefs**
  DEFENSE — 4-3 (inferred — balanced CB/LB roster) | No DC on file — inferred from roster
    Top CBs: Devon Witherspoon (CB, 91), Tariq Woolen (CB, 81), Nate Hobbs (CB, 80)
    Top LBs: Roquan Smith (MIKE, 93), Bobby Wagner (MIKE, 92), Zack Baun (WILL, 90)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Jaxon Smith-Njigba (95), Nico Collins (89), Cooper Kupp (84), Matthew Golden (78)
    Top HBs: Kenneth Walker III (88), Kyle Juszczyk (88)

**Las Vegas Raiders**
  DEFENSE — 4-2 Nickel [DEFAULT, no DC filled]: [4 DL, 2 LB, 3 CB, 2 S]
  📋 3 CBs on field (NB slot). Only 2 LBs. CB depth critical, LB less so.
  OFFENSE — Shotgun 3WR [DEFAULT, no DC filled]: [1 QB, 1 HB, 3 WR, 1 TE, 5 OL]
  📋 Pass-first. 3 WR starters needed. HB and TE depth matters.

**Los Angeles Chargers**
  DEFENSE — 4-3 (inferred — balanced CB/LB roster) | No DC on file — inferred from roster
    Top CBs: Jaylen Watson (CB, 79), Cor'Dale Flott (CB, 78), Joshua Williams (CB, 74)
    Top LBs: Dre Greenlaw (MIKE, 88), Alex Singleton (WILL, 84), Alex Anzalone (WILL, 80)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: DeVonta Smith (91), Rashee Rice (85), Emeka Egbuka (81), Sterling Shepard (76)
    Top HBs: Christian McCaffrey (96), Dameon Pierce (74)

**Los Angeles Rams**
  DEFENSE — 4-2 Nickel (inferred — more CB depth than LB) | No DC on file — inferred from roster
    Top CBs: Charvarius Ward (CB, 88), Sean Murphy-Bunting (CB, 78), Jack Jones (CB, 76)
    Top LBs: Bobby Okereke (MIKE, 84), Carson Schwesinger (MIKE, 82), Chad Muma (SAM, 70)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Stefon Diggs (87), Chris Olave (87), Tetairoa McMillan (83), Josh Reynolds (75)
    Top HBs: Jahmyr Gibbs (98), Joe Mixon (90)

**Miami Dolphins**
  DEFENSE — 3-4 (inferred — heavy LB roster) | No DC on file — inferred from roster
    Top CBs: Mike Jackson (CB, 79), Jaire Alexander (CB, 78), Mike Sainristil (CB, 77)
    Top LBs: Divine Deablo (WILL, 81), Sione Takitaki (SAM, 72), Tatum Bethune (MIKE, 70)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Mike Evans (91), Ricky Pearsall (80), Terrace Marshall Jr (71), Isaiah Bond (69)
    Top HBs: Aaron Jones Sr (80), Jawhar Jordan (71)

**Minnesota Vikings**
  DEFENSE — 3-3 Nickel: [3 DL, 3 LB, 3 CB, 2 S]
  OFFENSE — Shotgun 3WR: [1 QB, 1 HB, 3 WR, 1 TE, 5 OL]

**New England Patriots**
  DEFENSE — 4-2 Nickel (inferred — more CB depth than LB) | No DC on file — inferred from roster
    Top CBs: Emmanuel Moseley (CB, 76), Darrell Baker (CB, 74), Mike Ford Jr (CB, 73)
    Top LBs: Fred Warner (MIKE, 97), Nicholas Morrow (MIKE, 75), E.J. Speed (WILL, 75)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Jordan Addison (84), Jerry Jeudy (81), Quentin Johnston (80), DeAndre Hopkins (79)
    Top HBs: D'Andre Swift (85), Austin Ekeler (75)

**New Orleans Saints**
  DEFENSE — 4-3 (inferred — balanced CB/LB roster) | No DC on file — inferred from roster
    Top CBs: Darius Slay Jr (CB, 84), Chidobe Awuzie (CB, 83), Asante Samuel Jr (CB, 76)
    Top LBs: Tyrel Dodson (WILL, 77), Kyzir White (WILL, 72), Troy Andersen (WILL, 71)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Brandon Aiyuk (84), Romeo Doubs (79), Tre Tucker (78), Tim Patrick (76)
    Top HBs: J.K. Dobbins (83), Jacory Croskey-Merritt (78)

**New York Giants**
  DEFENSE — 4-2 Nickel (inferred — more CB depth than LB) | No DC on file — inferred from roster
    Top CBs: Cobie Durant (CB, 81), Paulson Adebo (CB, 78), Deonte Banks (CB, 75)
    Top LBs: Jamien Sherwood (MIKE, 77), Derrick Barnes (SAM, 74), Devin White (WILL, 73)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Davante Adams (90), Travis Hunter (82), Darius Slayton (78), Calvin Austin (76)
    Top HBs: Derrick Henry (94), Tyrone Tracy Jr (79)

**New York Jets**
  DEFENSE — 4-3 (inferred — balanced CB/LB roster) | No DC on file — inferred from roster
    Top CBs: Trevon Diggs (CB, 77), Adoree' Jackson (CB, 75), Jonathan Jones (CB, 73)
    Top LBs: Omar Speights (WILL, 78), Cody Barton (MIKE, 78), Akeem Davis-Gaither (MIKE, 72)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Amon-Ra St. Brown (96), Malik Nabers (86), Keenan Allen (83), Rondale Moore (76)
    Top HBs: Josh Jacobs (91), Reggie Gilliam (83)

**Philadelphia Eagles**
  DEFENSE — 3-4 (inferred — heavy LB roster) | No DC on file — inferred from roster
    Top CBs: Jaylon Johnson (CB, 90), Taron Johnson (CB, 84), Deommodore Lenoir (CB, 81)
    Top LBs: Lavonte David (MIKE, 85), Kaden Elliss (MIKE, 84), Matt Milano (WILL, 83)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: A.J. Brown (89), Tank Dell (79), Joshua Palmer (76), Demarcus Robinson (76)
    Top HBs: Saquon Barkley (92), Patrick Ricard (82)

**Pittsburgh Steelers**
  DEFENSE — 3-4: [3 DL, 4 LB, 2 CB, 2 S]
    ⚡ Cross-position starters: Xavier Watts (SS → RCB slot, 79 OVR) | Will Johnson (CB → SS slot, 77 OVR)
  DEFENSE — 4-2 Nickel: [3 DL, 3 LB, 3 CB, 2 S]
    ⚡ Cross-position starters: Will Johnson (CB → FS slot, 77 OVR) | Xavier Watts (SS → NB slot, 79 OVR) | Andre Cisco (FS → RCB slot, 77 OVR) | Devin Bush (WILL → RDE slot, 86 OVR) | Benjamin St-Juste (CB → SS slot, 77 OVR)
  DEFENSE — 4-3: [3 DL, 4 LB, 2 CB, 2 S]
    ⚡ Cross-position starters: Xavier Watts (SS → RCB slot, 79 OVR) | Devin Bush (WILL → RDE slot, 86 OVR) | Will Johnson (CB → SS slot, 77 OVR)
  OFFENSE — I-Form: [1 QB, 2 HB, 2 WR, 1 TE, 5 OL]
  OFFENSE — Shotgun 3WR: [1 QB, 1 HB, 3 WR, 1 TE, 5 OL]

**San Francisco 49ers**
  DEFENSE — 4-3 (inferred — balanced CB/LB roster) | No DC on file — inferred from roster
    Top CBs: Patrick Surtain II (CB, 97), A.J. Terrell Jr (CB, 88), Jahdae Barron (CB, 75)
    Top LBs: Demario Davis (MIKE, 91), Kamu Grugier-Hill (WILL, 69), Joe Andreessen (MIKE, 69)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Drake London (92), Rashid Shaheed (79), Darnell Mooney (77)
    Top HBs: Bijan Robinson (95), Tyler Allgeier (80)

**Seattle Seahawks**
  DEFENSE — 4-2 Nickel [DEFAULT]: [4 DL, 3 CB]
  OFFENSE — Shotgun 3WR: [1 QB, 1 HB, 1 TE, 5 OL]
  📋 DEF priority note (4-2 Nickel): 3 CBs on field (NB slot). Only 2 LBs. CB depth critical, LB less so.

**Tampa Bay Buccaneers**
  DEFENSE — 4-2 Nickel: [1 S]
    ⚡ Cross-position starters: Kyle Hamilton (SS → LCB slot, 93 OVR)

**Tennessee Titans**
  DEFENSE — 4-2 Nickel (inferred — more CB depth than LB) | No DC on file — inferred from roster
    Top CBs: Jalen Pitre (CB, 86), DJ Turner II (CB, 83), Alontae Taylor (CB, 77)
    Top LBs: Henry To'oTo'o (SAM, 75), James Williams Sr (MIKE, 67), Ale Kaho (WILL, 65)
  OFFENSE — Unknown formation | No DC on file
    Top WRs: Wan'Dale Robinson (83), Mecole Hardman (73), Konata Mumpfield (71), Jalin Hyatt (70)
    Top HBs: Tony Pollard (83), Michael Carter (71)

**Washington Commanders**
  DEFENSE — 3-3 Nickel: [3 DL, 3 LB, 3 CB, 2 S]
  DEFENSE — 3-4: [3 DL, 4 LB, 2 CB, 2 S]
    ⚡ Cross-position starters: Grant Delpit (SS → RCB slot, 82 OVR) | Mekhi Blackmon (CB → SS slot, 76 OVR)
  DEFENSE — 4-2 Nickel [DEFAULT]: [4 DL, 2 LB, 3 CB, 2 S]
  DEFENSE — 4-3: [2 DL, 5 LB, 2 CB, 2 S]
    ⚡ Cross-position starters: Leo Chenal (SAM → LDE slot, 84 OVR) | Grant Delpit (SS → RCB slot, 82 OVR) | Frankie Luvu (WILL → RDE slot, 79 OVR) | Mekhi Blackmon (CB → SS slot, 76 OVR)
  OFFENSE — I-Form: [1 QB, 1 HB, 2 WR, 2 TE, 5 OL]
    ⚡ Cross-position starters: Ben Sinnott (TE → FB slot, 69 OVR)
  📋 DEF priority note (4-2 Nickel): 3 CBs on field (NB slot). Only 2 LBs. CB depth critical, LB less so.

---
## AVAILABLE-AT-YOUR-PICK SIMULATION

Jon owns R1 picks at slots: **#2, 3, 4, 6, 7, 10, 12, 13, 15, 16, 17, 24, 25, 26**
Slots he does NOT own: #1, 5, 8, 9, 11, 14, 18-23, 27-33

This section shows who picks at each slot Jon doesn't own and their likely targets,
so Opus can project what's realistically available at each of Jon's picks.

### Pick-by-Pick Walkthrough

**Pick #1 — Seattle Seahawks** (from New York Giants)
  Tendency: Bills fan, solid GM. Typically values CB, WR, EDGE. Has 3 R1 picks.
  Roster weakness: WILL(avg 67.0), QB(avg 71.3), SS(avg 73.0), LEDGE(avg 74.0), MIKE(avg 74.7)
  Formation: CB-heavy (4-2 Nickel — 3 CBs on field)

**Pick #2 — LAS VEGAS RAIDERS (from Los Angeles Rams)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #3 — LAS VEGAS RAIDERS (from Carolina Panthers)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #4 — LAS VEGAS RAIDERS (from Indianapolis Colts)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #5 — Kansas City Chiefs** (from Denver Broncos)
  Tendency: Boise State lean. Limited R1 picks. Values balanced roster.
  Roster weakness: LEDGE(avg 66.0)

**Pick #6 — LAS VEGAS RAIDERS (from Cleveland Browns)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #7 — LAS VEGAS RAIDERS (from Chicago Bears)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #8 — Baltimore Ravens** (from Arizona Cardinals)
  Tendency: 1 R1 pick (from Raiders originally). Smart GM tendencies.
  Roster weakness: SAM(avg 63.0), MIKE(avg 64.0), LEDGE(avg 68.0), TE(avg 71.7), FS(avg 73.3)

**Pick #9 — Cleveland Browns** (from Pittsburgh Steelers)
  Tendency: UNC superfan. Will take UNC players. Smart drafter otherwise.
  Roster weakness: LEDGE(avg 69.0), MIKE(avg 69.8), WILL(avg 70.5), REDGE(avg 70.8), TE(avg 71.3)

**Pick #10 — LAS VEGAS RAIDERS (own)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #11 — San Francisco 49ers** (from Philadelphia Eagles)
  Tendency: Atlanta Falcons fan. 1 R1 pick.
  Roster weakness: SAM(avg 66.0), WILL(avg 67.5), QB(avg 68.3), TE(avg 76.5)

**Pick #12 — LAS VEGAS RAIDERS (from Baltimore Ravens)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #13 — LAS VEGAS RAIDERS (from New York Jets)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #14 — Seattle Seahawks** (from Los Angeles Chargers)
  Tendency: Bills fan, solid GM. Typically values CB, WR, EDGE. Has 3 R1 picks.
  Roster weakness: WILL(avg 67.0), QB(avg 71.3), SS(avg 73.0), LEDGE(avg 74.0), MIKE(avg 74.7)
  Formation: CB-heavy (4-2 Nickel — 3 CBs on field)

**Pick #15 — LAS VEGAS RAIDERS (from Detroit Lions)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #16 — LAS VEGAS RAIDERS (from New Orleans Saints)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #17 — LAS VEGAS RAIDERS (from Atlanta Falcons)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #18 — New York Jets** (from New England Patriots)
  Tendency: 27 total picks — active. Values WR, CB, QB depth.
  Roster weakness: LEDGE(avg 69.3), SS(avg 69.5), QB(avg 70.3), WILL(avg 71.5), MIKE(avg 71.7)

**Pick #19 — Minnesota Vikings** (from Green Bay Packers)
  Tendency: Vikings fan. 1 R1 pick. Balanced.
  Roster weakness: MIKE(avg 69.5), LEDGE(avg 70.0), TE(avg 70.7), QB(avg 71.0), WR(avg 71.0)

**Pick #20 — New Orleans Saints** (from Kansas City Chiefs)
  Tendency: 1 R1 pick. Run-heavy tendency. Will target HB or OL.
  Roster weakness: WILL(avg 71.4), SS(avg 71.5), TE(avg 71.5), QB(avg 73.7), REDGE(avg 74.0)

**Pick #21 — Philadelphia Eagles** (from Tampa Bay Buccaneers)
  Tendency: Bills fan, disconnected owner. One of worst teams. May reach.",
  Roster weakness: SS(avg 68.0), TE(avg 68.8), WILL(avg 72.3), LEDGE(avg 73.0), WR(avg 73.1)

**Pick #22 — Buffalo Bills** (from Jacksonville Jaguars)
  Tendency: Bills fan. 1 R1 pick (own).
  Roster weakness: SAM(avg 64.0), MIKE(avg 67.0), QB(avg 69.5), LEDGE(avg 70.5), WILL(avg 71.0)

**Pick #23 — Seattle Seahawks** (from Dallas Cowboys)
  Tendency: Bills fan, solid GM. Typically values CB, WR, EDGE. Has 3 R1 picks.
  Roster weakness: WILL(avg 67.0), QB(avg 71.3), SS(avg 73.0), LEDGE(avg 74.0), MIKE(avg 74.7)
  Formation: CB-heavy (4-2 Nickel — 3 CBs on field)

**Pick #24 — LAS VEGAS RAIDERS (from Tennessee Titans)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #25 — LAS VEGAS RAIDERS (from Buffalo Bills)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #26 — LAS VEGAS RAIDERS (from San Francisco 49ers)** ← Jon picks here
  → See Output 4 for suggestion at this slot.

**Pick #27 — Dallas Cowboys** (from Seattle Seahawks)
  Tendency: Notre Dame/South Carolina lean. Cowboys fan.
  Roster weakness: SAM(avg 72.0), HB(avg 75.0), REDGE(avg 75.3), TE(avg 75.7), FS(avg 76.0)

**Pick #28 — Houston Texans** (own)
  Tendency: 1 R1 pick. Balanced tendencies.
  Roster weakness: TE(avg 67.8), WILL(avg 70.5), FS(avg 72.0), REDGE(avg 73.2), HB(avg 75.2)

**Pick #29 — Miami Dolphins** (own)
  Tendency: Good player, poor roster mgmt. Takes high-OVR names regardless of fit.
  Roster weakness: TE(avg 67.2), FS(avg 67.4), MIKE(avg 67.7), LEDGE(avg 68.0), SS(avg 68.0)

**Pick #30 — Carolina Panthers** (from Washington Commanders)
  Tendency: Will reach for Clemson players. HUGE Clemson fan. Otherwise targets WR/CB.
  Roster weakness: SAM(avg 68.0), MIKE(avg 69.0), LEDGE(avg 72.0), TE(avg 73.5), WR(avg 73.6)

**Pick #31 — Carolina Panthers** (from Minnesota Vikings)
  Tendency: Will reach for Clemson players. HUGE Clemson fan. Otherwise targets WR/CB.
  Roster weakness: SAM(avg 68.0), MIKE(avg 69.0), LEDGE(avg 72.0), TE(avg 73.5), WR(avg 73.6)

**Pick #32 — Kansas City Chiefs** (from Cincinnati Bengals)
  Tendency: Boise State lean. Limited R1 picks. Values balanced roster.
  Roster weakness: LEDGE(avg 66.0)

**Pick #33 — Arizona Cardinals** (own)
  Tendency: 1 R1 pick. No strong pattern.
  Roster weakness: SS(avg 70.3), QB(avg 71.7), CB(avg 72.1), WILL(avg 72.3), WR(avg 73.9)

> **For Opus:** Use the above to project the board fallout at each Raiders slot.
> Note how many top skill-position prospects (QB, WR, HB, CB) are consumed before
> Jon's later picks (#24-26). The thin QB class means Mendoza is gone by pick #1.

---
## MARKET CORRECTIONS & VALUATION RULES — Updated April 20–21, 2026

This section SUPERSEDES earlier intel where it conflicts. When evaluating trades, always apply these rules first.

### A. Trade Status Updates (supersede earlier intel)

1. **Chiefs / McDuffie — WITHDRAWN.** As of April 20, 2026, Chiefs told Jon they are no longer interested in paying for McDuffie. The previously proposed framework (#5 + #32 for McDuffie) is OFF the table unless Chiefs re-initiate. Do NOT plan around this deal closing. If referenced in prior sections, treat as stale.

2. **Panthers / Campbell + Etienne for #30 + #31 — REJECTED.** Panthers rejected this exact package. Per Opus earlier analysis, Campbell alone for #30+#31 was the fair-market price — adding Etienne was already padding Jon's side, which likely reinforced their sticker-shock concern rather than solving it. Path forward: re-pitch Campbell ALONE for #30+#31 as a "clean" deal, not a sweetened one. Do NOT add Odunze, Stingley, or any other elite asset — that overpays wildly relative to the pick capital being received.

### B. CONSISTENT VALUATION RULE (highest priority)

A player's trade value is a SINGLE number anchored to market signals, not a variable that moves based on which team is buying. Apply the same asking price to every trade partner. Common violation to watch for: suggesting Player X for Team A's R1 one minute, then bundling Player X as a sweetener in a different deal worth less than that R1 — that's internally inconsistent.

**Anchored market values (use these as the floor across ALL trade conversations):**

| Asset | Market Anchor | Source |
|-------|--------------|--------|
| Rome Odunze (82 WR, ~22) | ≥ 1 current R1 (Ravens offered #8 straight up) | Confirmed offer, April 2026 |
| Trent McDuffie (94 CB, 25) | 2 current R1s (e.g. #5 + #32 tier) | Prior Chiefs offer baseline, though now off |
| Derek Stingley (92 CB, 24) | 2 current R1s minimum | Opus explicit floor |
| Sauce Gardner (90 CB, ~24) | 1 mid-R1 minimum (same HOLD logic as Stingley) | Age/position curve |
| Jameson Williams (85 WR, ~24) | 1 current R1 floor (speed-WR, peak years) | Position × age |
| Brian Thomas Jr (81 WR, ~23) | 1 current R1 floor (league's leading receiver in M26) | Production + age |
| Jack Campbell (MIKE LB) | ~2 late-R1s combined (#30 + #31 tier) | Opus-validated, already market-tested |
| Trevor Etienne (HB 71) | R5–R6 level sweetener, no more | Depth tier |

**Pick values — use a standard trade chart as reference:**
- #1–5: 1700–2200 pts
- #8: 1400
- #10: 1300
- #20: 850
- #22: 780
- #27–29: 640–680
- #30–32: 590–620

**Consistency test:** If the asking price for Player X in Deal A is "R1 pick" and in Deal B you're bundling Player X as a sweetener on top of Asset Y to get a package of picks worth LESS than "R1 pick," that's a value leak. Don't do it.

### C. Dolphins Pick Discount (new rule)

Miami's owner is **inactive at roster management but skilled at actually playing Madden**. Empirically, Miami makes the playoffs every year — meaning their R1 pick is ALWAYS a late-R1 (#25–32 range) and they cannot access lottery picks. 

**Application:**
1. Current-year Miami R1 picks trade at late-R1 value only (~640 pts for a #29-range slot). Do NOT treat them as "R1 generic" worth the same as a Panthers #30 OR a Ravens #8 — they are anchored to late-R1 specifically.
2. **Future Miami picks (2027+) carry the SAME discount** — projected again as late-R1s, not lottery-range. A Miami 2027 R1 is worth materially less than a CHI 2027 R1 or any bottom-tier team's future R1.
3. When evaluating future-pick trades: prefer picks from teams with lottery variance (bad teams) over Miami picks even at face-value R1 parity.
4. Owner characterization correction: the "bad at roster management" note in earlier intel was about his **inactivity**, not his player-evaluation ability. He values players correctly when he engages — he just engages less often. Do not assume he will take lowball offers on real assets.

### D. Breakout Candidate Register (Raiders roster)

Players where Jon should apply an upward-appreciation premium beyond current OVR when considering trades. These are DO-NOT-DISCOUNT assets.

1. **Rome Odunze** (WR, 82 OVR, ~22) — 22yo = widest floor/ceiling gap per age framework. Pass-first scheme amplifies upside. Key reason Jon declined Ravens #8. Minimum trade price: R1 + additional sweetener (not #8 alone).
2. **Brian Thomas Jr** (WR, 81 OVR, ~23) — already league-leading WR (2,902 yds, 33 TD in M26). HOLD.
3. **Derek Stingley Jr** (CB, 92 OVR, 24) — still ascending curve. 2-R1 floor.
4. **Mason Graham** (DT, 80 OVR, young) — appreciating DT; low Madden position weight but won't fetch true market because of position tax.
5. **Braden Fiske** (DT, 80 OVR, young) — same as Graham.
6. **JJ McCarthy** (QB, 71 OVR) — developmental, not a current trade asset but is an appreciating piece of the roster puzzle. Do not list as "weakness" without noting the development upside.

### E. Behavioral Guardrails for Future Sessions

1. When suggesting a trade, state the player's market anchor first, then verify the pick capital on offer meets or exceeds it. If not, flag it as a below-market trade, don't mask it with "but this team really wants him."
2. When suggesting sweeteners, verify the sweetener's value is smaller than the delta being solved. If Campbell + Odunze = 1220 + ≥1400 = ≥2620 value, do NOT offer it for picks worth only 1220.
3. When recommending a team as a trade partner, state the SINGLE asking price; do not re-price the same asset across multiple partners.
4. Breakout candidates (Section D) get a holding premium. Only move them for ABOVE-anchor offers, not at anchor.