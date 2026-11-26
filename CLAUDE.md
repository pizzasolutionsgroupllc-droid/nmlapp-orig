# CLAUDE.md — Working Instructions for NML App Project

## About the User
- Name: Jon (jvantrease83@gmail.com)
- Not a developer or coder — avoid assuming technical knowledge
- Uses Cowork (Claude desktop app) to manage this project
- Token-conscious: working on a personal license, so efficiency matters

---

## Communication Rules (ALWAYS follow these)

1. **Numbered bullets** — Always present information, options, and feedback using numbered bullets so Jon can reply with "option 2" or "1 looks good" etc.

2. **Copy-friendly commands & URLs** — Whenever a command, URL, or value needs to be entered somewhere, format it in a code block so it's easy to click-copy. Never bury commands inside paragraphs.

3. **Expert guidance** — Proactively offer best-practice suggestions, flag risks, and explain tradeoffs in plain language. Think like a senior developer + strategist who translates for a non-technical stakeholder.

4. **No code without confirmation** — Never write or modify code until Jon explicitly confirms. He may still be thinking through an idea and wants to make sure details fit his broader plans before any implementation begins. Talk through the approach first.

5. **Confirm before high-token actions** — Stop and get explicit approval before starting any task that will use significant tokens: multi-file edits, large generations, agent spawning, extensive research, etc.

---

## Project: NML League Manager

### Stack
- **Backend:** Python / Flask (`backend/app.py`)
- **Frontend:** Single-page HTML/JS (`nml-app.html`)
- **Flask serves both API and frontend on port 8080** (no separate file server needed)

### How to Start the App
```
# Single terminal — Flask serves everything
cd /Users/j/Desktop/Claude/nmlapp/backend && PORT=8080 python3 app.py
```
```
# Browser
http://127.0.0.1:8080/nml-app.html
```
Note: Port 5000 is blocked on macOS by AirPlay Receiver — always use PORT=8080.

### Current Status (as of April 2026)
- **Production is LIVE on Railway** — real league members are using it, trades are actively happening
- **Data is real** — treat all production data as sensitive
- **Discord bot is active** — posting to league channels, DMs working
- **ngrok** — abandoned, not part of current architecture

### Known Issues / Backlog Status
1. ✅ **Nightly backup bot** — FIXED: Discord permission fixed, manual trigger at `/api/admin/run-backup-now`
2. ✅ **Mobile UX** — FIXED: drawer nav, player list+detail panel on all pages, My Team layout
3. ✅ **Dead space / sizing pass** — FIXED: global CSS sizing, fit-content cards, spacer columns, column widths
4. ✅ **Discord link behavior** — FIXED: in-app browser detection banner with Copy Link button
5. ✅ **Trade Center commissioner-only** — FIXED: only commissioner sees Trade Center in nav and dashboard
6. ✅ **Discord Accept/Reject magic links** — FIXED (April 2026): full implementation shipped to production
7. ✅ **All Players / Draft Prospects** — FIXED: exposed to all logged-in users, C badge removed
8. ✅ **Mock Draft saves / DB locked** — FIXED (April 2026): gunicorn reduced to 1 worker (SQLite single-writer); mock_draft_picks FK was pointing at draft_prospects (wrong), migrated to players; ON CONFLICT upsert replaced with SELECT+INSERT/UPDATE
9. ✅ **Team switcher dropdown** — SHIPPED (April 2026): dropdown on team detail page to jump between teams without going back to All Teams grid. Populated from `S.teams`, sorted alphabetically by `short_name`, current team pre-selected. Desktop: lives in `#tdSwitcher` inside `#subnavRow` (right of subnav tabs). Mobile: lives in `#tdSwitcherMob` inside `#mobSubnavRow` (right of mobile subnav tabs). Both cleared by `nav()` on every page change. `#tright` is hidden on BOTH desktop and mobile — never write nav UI there.

### Feature Backlog (in priority order — work through these in sequence)

**Upcoming Features (confirmed April 2026 — implement in this order):**

- **Item A — Trade Value Calculator** ✅ SHIPPED
  - Live "trade grade" panel on Propose Trade screen, updates as assets are added/removed
  - Score formula per player: base_score(OVR) × age_multiplier × position_multiplier
    - OVR curve: 99=100pts, scales down (not linear — 80 OVR ≈ 45pts, 70 OVR ≈ 25pts)
    - Age multipliers: ≤21=1.4, 22=1.3, 23=1.2, 24-26=1.1, 27-28=1.0, 29=0.9, 30=0.8, 31=0.65, 32=0.5, 33+=0.35
    - Position multipliers (defaults): QB=1.3, WR/EDGE=1.15, LT/CB=1.1, all others=1.0
  - Pick score by round: 1st=90, 2nd=60, 3rd=40, 4th=25, 5th=16, 6th=10, 7th=6
    - Year penalty: current year ×1.0, +1yr ×0.9, +2yr ×0.8, etc.
  - Grade output: Side A total vs Side B total → "Even" / "Slight advantage X" / "Strong advantage X" / "Very one-sided"
    - Thresholds: <5% diff = Even, 5-15% = Slight, 15-30% = Strong, >30% = Very one-sided
  - Each asset shows its individual point value in the panel
  - Settings: new "Trade Grader" tab in Admin Settings — position multipliers, age breakpoints, pick values all tunable
  - DB: `trade_grade_settings` table for weight storage (key/value like league_settings)

- **Item B — League Activity Feed** ❌ Declined
  - Would duplicate the existing Transaction Log — not building

- **Item C — Team Power Rankings** ✅ SHIPPED
  - Fully automatic calculation, no manual input required (future: commissioner article/blurb layer)
  - Score formula (100 pts total):
    - Starter OVR (40pts): avg OVR of depth chart starters for each team
    - Roster depth (10pts): avg OVR of full roster
    - Age score (25pts): inverse of avg starter age (younger starters = higher score)
    - Pick capital (25pts): sum of pick values using same round/year formula as Item A
  - Stored weekly in DB — snapshots enable movement tracking (↑↓=)
  - Display: ranked table, rank # + team name + score + movement indicator + score breakdown on hover/tap
  - Commissioner triggers calculation manually (button in admin) or on a schedule
  - DB: `power_rankings (id, season, week_label, team_id, rank, prev_rank, score, starter_ovr_score, depth_score, age_score, pick_score, created_at)`

- **Item D — Player Watchlist** ✅ SHIPPED
  - DB: `watchlist (id, user_id, player_id, added_at, UNIQUE(user_id, player_id))`
  - Backend: GET/POST/DELETE `/api/watchlist` and `/api/watchlist/<player_id>`
  - Player modal: "👁 Watch" / "👁 Watching" toggle button
  - My Team page: "My Watchlist" card — position, name, OVR, age, current team; click opens modal
  - Fully private — no other user can see another's watchlist

- **Item E — Trade Analyzer History** ✅ SHIPPED
  - Requires `player_ratings_history` table (foundation piece built first)
  - DB: `player_ratings_history (id, player_id, overall_rating, speed, strength, awareness, [~10 key ratings], snapshot_label, snapshot_date, created_at)`
  - Back-fill on build: current ratings → snapshot_label="M26 Super Bowl Update", snapshot_date=2026-04-17
  - Future imports: script prompts for a label (e.g. "M27 Week 3") and auto-snapshots all players
  - Player modal: "Rating History" section — table of OVR per snapshot label
  - Trade Analyzer page: each completed trade shows OVR trajectory of all traded players since trade date
  - For traded picks: once pick is used in draft, links to drafted player's subsequent OVR history
  - League context: M26 Super Bowl Update is the baseline (April 2026). M27 incremental imports start September 2026.

- **Item F — Madden Franchise Sync** — Deferred / Context noted
  - League plays on Xbox + PS5 (cross-play). PC banned due to mod cheat risk.
  - Jon to revisit PC play argument with league leaders later — Claude to help draft that case.
  - Manual CSV import remains the data pipeline for now.

- **Item G — Stats Page** — Deferred (no game data until September 2026)

- **Item I — Draft Lottery Tool** — Deferred (not needed until start of 2027 season)
  - Pre-lottery order: generated from NFL tiebreaker rules applied to final season records
  - Lottery pool: worst 18 non-playoff teams; weighted % chance for #1 pick (worst team = best odds)
  - Draw format: teams selected one at a time from 18→1 (best lottery record → worst), assigning pick slots
  - Round 1 order: lottery result. Round 2: pre-lottery order. Rounds 3–7: pre-lottery order with same-record rotation
  - Commissioner tool — runs and records the lottery result; assigns final pick slots for round 1
  - Context: revisit at start of 2027 offseason (roughly early 2027)
  - Tabs: Season / All-Time / Year-by-Year
  - Sections: Top 15 per major stat + team stats
  - Data entry method TBD — revisit when season starts

- **Item H — Schedule + Game Scheduling** ✅ Confirmed
  - League mirrors exact NFL regular season schedule (32 teams, 17 weeks, 1 game/week)
  - Usually 1-2 weeks behind NFL; playoffs follow NFL seeding rules ("Power Bowl" = championship)
  - Rosters and draft picks carry over year to year — not a fresh start each season
  - DB: `seasons (id, year, name, is_current)`, `schedule_weeks (id, season_id, week_num, nfl_week_label, advance_date)`, `games (id, week_id, home_team_id, away_team_id, home_score, away_score, status)`, `game_scheduling (id, game_id, planned_datetime, stream_url, posted_by_user_id, updated_at)`
  - `users.twitch_url TEXT` column added to user profile
  - Commissioner builds schedule manually (UI to enter matchups week by week) or CSV import of NFL schedule
  - Each owner can click their matchup and set: planned date/time + stream URL
  - Schedule page: week selector, 16 matchup cards per week showing teams + planned time + 🎮 stream link
  - Future: results entry (home/away score) to feed standings
**Item 3 — Player positional ranking** ✅ SHIPPED
- Player modal shows rank among all NML players at their position (e.g. "WR #4 in the league")

**Item 4 — Trade history per player** ✅ SHIPPED
- Player modal shows full trade history section with status chips, date, teams, assets
- Backend: `GET /api/players/<id>/trades` — joins trade_assets → trades → teams
- Frontend: `loadPlayerTradeHistory(playerId)` — renders into `#pmTradeHistory` div

**Item 5 — My Depth Chart page** ✅ SHIPPED (April 17, 2026)
- New page for each owner to view/set their personal depth chart
- Field grid view, formation tabs (offense + defense), click-to-assign picker, auto-fill starters, D1 duplicate prevention, Set as Default, landing view editable directly
- Default formations: 4-2 Nickel (defense) and Shotgun 3WR (offense) for users who haven't set their own
- DB tables: `depth_chart`, `depth_chart_defaults`, `dc_slot_eligibility` (seeded with positional rules)
- Endpoints: `GET/PUT /api/depth-chart`, `GET/PUT /api/depth-chart/slot`, `GET/PUT /api/depth-chart/defaults`, `GET/PUT /api/depth-chart/eligibility`
- Admin settings card: "Depth Chart Position Eligibility" — formation tabs with position toggles, save/clear per formation
- Mobile: CSS tightened so 8-col grid fits portrait on 375px+ phones; landscape on modern iPhones gets full desktop layout
- Slot renames: LOLB→WLB, ROLB→SLB (3-3 Nickel); LDB→NB1, RDB→NB2 (4-1 Dime, 3-2 Dime)
- NB1/NB2 in DC_POS: `['CB','FS','SS']` eligibility
- Still to do (minor): fine-tune individual position column placements within some formations

**Item 6 — Dashboard + My Team reorganization** ✅ SHIPPED (April 18, 2026)
- Pick Tracker: 👤 My Picks toggle tab — filters table to current user's picks; stat card clicks on My Team navigate here with filter pre-activated
- My Team page: picks cards clickable → navigates to Pick Tracker with My Picks filter active; removed Recent Transactions, Team Needs, Team Note
- DB: `teams.tradeblock_note TEXT` column added via migration in `database.py`
- Backend: `tradeblock_note` added to allowed fields in PATCH `/api/teams/{id}` (app.py)

**Item 6b — My Block + Team Detail tradeblock view** ✅ SHIPPED (April 18, 2026)
- Trade Block page: "👤 My Block" toggle button in header (team owners only) switches to personal editable view:
  - 📋 Tradeblock Note — editable textarea, saved to `teams.tradeblock_note`
  - Team Needs board — fully editable (uses refactored `loadTeamNeedsBoard` with `targetId` param)
  - 🚩 My Assets table — players/picks on block with Remove + Edit Note buttons per row
  - "+ Add Player" picker — user's roster not on block, sorted by position then OVR desc
  - "+ Add Pick" picker — user's picks not on block, sorted by round then orig team name
- All Teams → Team Detail: Tradeblock Note + Team Needs shown read-only below roster/picks for every team
- Dashboard: removed Tradeblock/Needs/Note sections (now live in Trade Block My Block view)
- Architecture: `loadTeamNeedsBoard(tid, canEdit, targetId)` + `renderNeedsBoard()` use `_nd.targetId` for flexible rendering
- New functions: `renderMyBlock`, `mbAddPlayer`, `mbAddPick`, `tbEditNote`, `tbRemoveMB`, `saveMBNote`, `toggleMBPicker`

**Item 7 — NFL Draft Tracker** ✅ SHIPPED (April 2026)
- Full 257-pick live draft board for the 2026 NFL Draft
- All pick slots pre-loaded with correct NFL team assignments (actual 2026 order, all 7 rounds)
- Auto-fill: enter overall # → round/pick-in-round/NFL team fill automatically
- Prospect search: searches `draft_prospects` table, fixed dropdown visible above card (position:fixed)
- Record Pick saves to `draft_prospects` (nfl_overall, nfl_round, nfl_pick, nfl_team fields)
- Single-click undo (↩) per pick — clears all nfl_* fields
- Draft board: full 257-slot grid with round separators, filter by round/search
- `NT_PICKS` constant in frontend — full 2026 NFL pick order including comp picks R3-R7
- Creator-role endpoint: `PATCH /api/draft-prospects/<id>` allows nfl_overall/round/pick/team
- Round breakpoints: R1:1-32, R2:33-64, R3:65-100, R4:101-140, R5:141-181, R6:182-216, R7:217-257

**Item 8 — Mock Draft** ✅ SHIPPED (April 2026)
- Per-user mock drafts: create/rename/delete, named freely
- Board uses NML R1 pick slots as scaffolding (`/api/picks?year=2026`)
- Prospect picker searches cached `/api/players?draft_pool=true` list
- Picks saved to `mock_draft_picks` table (prospect_id REFERENCES players, not draft_prospects)
- Optimistic UI: pick shows immediately, saves in background
- Notes per pick (inline editable), clear (✕) and reassign (✏️) buttons
- DB: `mock_drafts (id, year, user_id, name, is_published, created_at, updated_at)`
- DB: `mock_draft_picks (id, mock_draft_id, overall_pick, round, pick_in_round, nfl_team, prospect_id→players, prospect_name, position, notes)`

**Personal Big Board** ✅ SHIPPED (April 22, 2026)
- Creator-only sub-tab under Draft (appears first in creator subnav)
- Horizontal grid: 12 position columns × 11 tier rows (1, 1-2, 2, 2-3, 3, 3-4, 4, 4-5, 5-6, 6-7, UDFA)
- Position group mapping: QB | RB(HB/RB/FB) | WR | TE | OT(OT/LT/RT) | OG(OG/LG/RG/IOL) | C | DT(DT/NT) | Edge(EDGE/LE/RE/LEDGE/REDGE/DE) | LB(LB/MLB/ILB/OLB/LOLB/ROLB) | CB | S(FS/SS/S)
- Player cards: RAS/10-split/40 for skill positions; Arm/Bench/SS for OL (OT/OG/C)
- Populate from consensus rankings: tier cutoffs Rank 1–5→T1, 6–32→T2, 33–64→T3... 351+→UDFA
- Drag-and-drop: within-cell reorder (card-level, top/bottom half detection, blue insert line) + cross-tier moves (cell-level, appends at end of target tier)
- Click any card → opens prospect modal
- "Reset & Repopulate" clears board and rebuilds from consensus
- Endpoints: `GET /api/draft-board` (expanded with ten/arm/bench/shuttle fields), `POST /api/draft-board/populate`, `PUT /api/draft-board/<id>`, `DELETE /api/draft-board/<id>`
- DB: uses existing `draft_board_entries (year, user_id, prospect_id, tier, board_rank, notes)`

**Prospect Modal improvements** ✅ SHIPPED (April 22, 2026)
- **Best Measurables** section (green header): always shows all 13 fields regardless of data
  - `bestMax()` for Hands/Arm/Wing/Vertical/Broad/Bench (larger = better)
  - `bestTimed()` for 10/20/40/3-Cone/Shuttle (lower = better)
  - `bestMeas()` (combine preferred) for Height/Weight
- Combine and Pro Day sections also always show all 13 fields (no more hiding empty rows)
- Field order: Height · Weight · Hands · Arm · Wing · Vertical · Broad · 10 Yd · 20 Yd · 40 Yd · 3-Cone · Shuttle · Bench
- Position badge clickable for creator (✎ icon) — inline edit saves to `draft_prospects.position`, invalidates big board cache

**Nav fixes** ✅ SHIPPED (April 22, 2026)
- Draft Room removed from creator gate — now visible to all logged-in owners, no badge
- Creator subnav order: Big Board → Prospect Board → NFL Tracker → NFL History
- `big-board` added to section map and page titles object

### Ratings Update (COMPLETED — April 2026)
- Source file: `Players-2.csv` (Madden franchise export, root of nmlapp folder)
- Script: `scripts/import_csv_ratings.py` — matches by madden_id, tight name+pos+age fallback
- Work DB: `data/nml-ratings-work.db` — used as staging; 3,077 players after duplicate cleanup
- `birth_date` populated for 2,389 players from CSV `birthDay/birthMonth/birthYear` fields
- `age` removed from COL_MAP — calculated dynamically at runtime via `compute_age()` in app.py
- **SHIPPED**: Merged and uploaded to production April 17, 2026

### Ratings Push Workflow (safe process — learned the hard way)
The local Flask app is ALWAYS running. SQLite WAL locks on `data/nml.db` corrupt any file written to that path while the app is active.

**NEVER write merge output to `data/nml.db`** — always use `data/nml-merged.db`.

Correct sequence:
1. `bash download_db.sh` — downloads prod snapshot to `data/backups/nml-backup-TIMESTAMP.db`
2. `python3 scripts/push_ratings_to_prod.py data/backups/nml-backup-TIMESTAMP.db --local=data/nml-ratings-work.db` — merges into `data/nml-merged.db`
3. `bash upload_merged.sh` — uploads `nml-merged.db` (NOT `nml.db`) to prod

**Gunicorn workers — MUST be 1:** SQLite is single-writer. Running `--workers 2` causes `database is locked` errors across ALL endpoints whenever any write is in-flight. Procfile must always have `--workers 1`. Do not increase this without switching to PostgreSQL.

If production DB ever becomes malformed and the app crashes (502):
- The upload endpoint goes down with the app — `upload_db.sh` won't work
- Fix: push a code patch to `database.py` `get_db()` making it resilient (auto-rename corrupt file, create fresh schema)
- Once app restarts with empty schema, immediately upload the backup via `upload_merged.sh`
- Recovery patch already in place in `get_db()` as of April 17, 2026

### Discord Magic Links — Technical Notes (April 2026)
- `trade_tokens` table in `database.py` — single-use tokens with 48hr expiry
- `generate_trade_token(conn, trade_id, team_id, action)` lives in `database.py` (not app.py — avoids circular import)
- `notify_trade_action(trade, action, recipient_team_id)` in `auth.py` — generates tokens for 'proposed' action, sends DM
- `GET /api/trades/<id>/discord-respond?token=X&action=accept|reject` in `app.py` — validates token, executes action, returns HTML page
- URL resolution order: `RAILWAY_PUBLIC_DOMAIN` env var → `APP_URL` env var → `http://127.0.0.1:8080` (local fallback)
- Test override: set `test_mode_discord_id` in league_settings via admin panel — routes all DMs to that Discord user ID
- Settings save uses `INSERT OR REPLACE` upsert (not bare UPDATE) to handle new keys

### Sorting Rule — ALWAYS first_name, never last_name
**Every player list, search result, and table in the app must sort by `first_name`, not `last_name`.** This applies to:
- All SQL `ORDER BY` clauses in `app.py` (use `first_name` not `last_name`)
- All JS `.sort()` comparators in `nml-app.html` (use `a.first_name.localeCompare(b.first_name)`)
- Any new endpoint or table added in the future

Whenever writing or reviewing any sort on player data, check for `last_name` and replace with `first_name`.

### Key Patterns
- `nmlTableRender(id, cols, rows, rerenderFn)` — shared table renderer used across the app
- `width:fit-content;max-width:100%` — pattern for compact card frames
- `showPlayerModal(player_id)` — existing player modal function (target for positional rank + trade history additions)
- `isComm = S.user && S.user.role === 'commissioner'` — commissioner check (assistant_commissioner does NOT get this)
- `isAdmin = S.user && ['commissioner','assistant_commissioner'].includes(S.user.role)` — admin check

### Project Structure
- `backend/app.py` — Flask API (~5,400+ lines)
- `backend/auth.py` — Auth, Discord DMs, notify_trade_action
- `backend/database.py` — DB init, schema, generate_trade_token
- `backend/discord_bot.py` — Bot send functions, get_trade_summary, test_connection
- `backend/importer.py` — CSV/XLSX import validator (imported directly by app.py — must stay in backend/)
- `backend/migration_madden_ids.py` — Madden ID migration (dynamically loaded by app.py — must stay in backend/)
- `data/nml.db` — Live local SQLite DB
- `data/nml-merged.db` — Staging DB for upload workflow (never write to nml.db directly)
- `data/nml-ratings-work.db` — Ratings import staging DB
- `data/backups/` — Dated prod snapshots (nml-backup-TIMESTAMP.db)
- `nml-app.html` — Single-page frontend (~9,200+ lines)
- `scripts/` — Active utility and import scripts
- `scripts/archive/` — Completed one-off scripts (debug, one-time fixes)
- `imports/` — Source data files (xlsx, csv, json)
- `mockups/` — HTML prototype files
- `docs/` — Reference documents and owner guide

### Development Rules
- **Always test locally first** — never push untested changes to production
- **Be surgical** — change only what's needed, assess ripple effects first
- **No circular imports** — database.py is safe to import from anywhere; app.py imports auth.py at top level
- ngrok is NOT part of the stack — ignore any references to it

---

### Long-Term Feature Wishlist (not yet scoped — capture only)

These are confirmed future desires from Jon. No implementation details decided yet — revisit and spec out each one when the time comes.

- **Season & Historical Stats** — Per-player, per-team, and per-owner stat pages. Requires tying each user's in-game gamertag to their app profile so game data can be attributed correctly. No game data until September 2026.

- **Smart Game Scheduling** — In-app scheduling for weekly matchups. Each user sets a default weekly availability window (e.g. Mon/Wed/Fri evenings), can edit as things come up. App detects overlapping windows between opponents and surfaces suggested times. Each game slot includes a link to the user's streaming handle (Twitch/YouTube etc.). Related to Item H (Schedule) already in backlog.

- **Pick'em Page** — Weekly pick'em for each matchup with odds. Multiple tabs: one AI-generated picks tab, plus additional tabs for any league member who wants to post their own weekly card with notes per game.

- **Weekly Game Summaries** — AI-generated write-up for each completed game. Pulled from score + player stat data once that pipeline exists.

- **Yearly Awards Page** — End-of-season awards with three versions side by side: (1) Madden in-game awards tab, (2) AI-generated awards, (3) league-voted awards done in-app.

- **Franchise → App Transaction Sync** — When a player/pick is cut, signed, or traded inside the Madden franchise, that action automatically mirrors into the NML app. Requires solving the PC/franchise sync problem (Item F) or finding an alternative data bridge from Xbox/PS5 franchise.

---

## Development Philosophy
- **Never break existing functionality** — always assess impact on current features before proposing changes
- **Incremental improvements** — small, confirmed steps over large rewrites
- **Test before declaring done** — suggest verification steps after any change
- **Token efficiency** — use agents and targeted reads; confirm scope before large tasks
