import sqlite3
import os
import secrets

DB_PATH = os.environ.get('DB_PATH') or os.path.join(os.path.dirname(__file__), '..', 'data', 'nml.db')

def get_db():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    except sqlite3.DatabaseError as e:
        print(f"[STARTUP] DB malformed or unreadable: {e} — renaming and recreating")
        if os.path.exists(DB_PATH):
            os.rename(DB_PATH, DB_PATH + '.corrupted')
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

def generate_trade_token(conn, trade_id, team_id, action):
    """Create a single-use Discord magic-link token. Returns the token string."""
    from datetime import datetime, timedelta
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=48)).isoformat()
    conn.execute(
        'INSERT INTO trade_tokens (trade_id, token, action, team_id, expires_at) VALUES (?,?,?,?,?)',
        (trade_id, token, action, team_id, expires_at)
    )
    return token

def init_db():
    conn = get_db()
    c = conn.cursor()

    # ── Teams ──────────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL UNIQUE,
        short_name TEXT NOT NULL,
        abbreviation TEXT NOT NULL UNIQUE,
        owner_name TEXT,
        discord_username TEXT,
        discord_tag TEXT,
        discord_user_id TEXT,
        pending_role TEXT NOT NULL DEFAULT 'owner',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    # Add pending_role to existing databases that predate this column
    try:
        c.execute("ALTER TABLE teams ADD COLUMN pending_role TEXT NOT NULL DEFAULT 'owner'")
    except Exception:
        pass

    # Add rookie prospect columns to players
    for sql in [
        "ALTER TABLE players ADD COLUMN is_rookie_prospect INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE players ADD COLUMN school TEXT",
        "ALTER TABLE players ADD COLUMN on_trade_block INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE players ADD COLUMN trade_block_note TEXT",
    ]:
        try:
            c.execute(sql)
        except Exception:
            pass

    # Add trade block support to draft_picks + team needs to teams + madden IDs
    for sql in [
        "ALTER TABLE draft_picks ADD COLUMN on_trade_block INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE draft_picks ADD COLUMN trade_block_note TEXT",
        "ALTER TABLE teams ADD COLUMN team_needs TEXT",
        "ALTER TABLE teams ADD COLUMN madden_team_id INTEGER",
        "ALTER TABLE teams ADD COLUMN trade_block_message_id TEXT",
        "ALTER TABLE teams ADD COLUMN tradeblock_note TEXT",
        # Rejection reason stored on trades that were auto-rejected
        # (e.g. because a pick in the offer was used in the draft)
        "ALTER TABLE trades ADD COLUMN rejection_reason TEXT",
    ]:
        try:
            c.execute(sql)
        except Exception:
            pass

    # Migrate legacy team_needs text column → tradeblock_note (one-time, safe to re-run)
    try:
        c.execute("""
            UPDATE teams
            SET tradeblock_note = team_needs
            WHERE team_needs IS NOT NULL
              AND team_needs != ''
              AND (tradeblock_note IS NULL OR tradeblock_note = '')
        """)
    except Exception:
        pass

    # Add Madden player ratings + contract + draft data columns
    for sql in [
        # Core athleticism
        "ALTER TABLE players ADD COLUMN speed INTEGER",
        "ALTER TABLE players ADD COLUMN acceleration INTEGER",
        "ALTER TABLE players ADD COLUMN agility INTEGER",
        "ALTER TABLE players ADD COLUMN cod INTEGER",
        "ALTER TABLE players ADD COLUMN strength INTEGER",
        "ALTER TABLE players ADD COLUMN awareness INTEGER",
        "ALTER TABLE players ADD COLUMN stamina INTEGER",
        "ALTER TABLE players ADD COLUMN injury INTEGER",
        "ALTER TABLE players ADD COLUMN toughness INTEGER",
        "ALTER TABLE players ADD COLUMN jump INTEGER",
        # Ball carrier
        "ALTER TABLE players ADD COLUMN carry INTEGER",
        "ALTER TABLE players ADD COLUMN break_tackle INTEGER",
        "ALTER TABLE players ADD COLUMN juke INTEGER",
        "ALTER TABLE players ADD COLUMN spin INTEGER",
        "ALTER TABLE players ADD COLUMN truck INTEGER",
        "ALTER TABLE players ADD COLUMN stiff_arm INTEGER",
        "ALTER TABLE players ADD COLUMN bcv INTEGER",
        # Receiving
        "ALTER TABLE players ADD COLUMN catch INTEGER",
        "ALTER TABLE players ADD COLUMN cit INTEGER",
        "ALTER TABLE players ADD COLUMN spec_catch INTEGER",
        "ALTER TABLE players ADD COLUMN route_short INTEGER",
        "ALTER TABLE players ADD COLUMN route_med INTEGER",
        "ALTER TABLE players ADD COLUMN route_deep INTEGER",
        "ALTER TABLE players ADD COLUMN release INTEGER",
        # QB passing
        "ALTER TABLE players ADD COLUMN throw_power INTEGER",
        "ALTER TABLE players ADD COLUMN throw_acc INTEGER",
        "ALTER TABLE players ADD COLUMN throw_acc_short INTEGER",
        "ALTER TABLE players ADD COLUMN throw_acc_mid INTEGER",
        "ALTER TABLE players ADD COLUMN throw_acc_deep INTEGER",
        "ALTER TABLE players ADD COLUMN throw_on_run INTEGER",
        "ALTER TABLE players ADD COLUMN throw_under_pressure INTEGER",
        "ALTER TABLE players ADD COLUMN play_action INTEGER",
        # Blocking
        "ALTER TABLE players ADD COLUMN pass_block INTEGER",
        "ALTER TABLE players ADD COLUMN pass_block_power INTEGER",
        "ALTER TABLE players ADD COLUMN pass_block_finesse INTEGER",
        "ALTER TABLE players ADD COLUMN run_block INTEGER",
        "ALTER TABLE players ADD COLUMN run_block_power INTEGER",
        "ALTER TABLE players ADD COLUMN run_block_finesse INTEGER",
        "ALTER TABLE players ADD COLUMN impact_block INTEGER",
        "ALTER TABLE players ADD COLUMN lead_block INTEGER",
        "ALTER TABLE players ADD COLUMN long_snap INTEGER",
        # Special teams
        "ALTER TABLE players ADD COLUMN kick_power INTEGER",
        "ALTER TABLE players ADD COLUMN kick_acc INTEGER",
        "ALTER TABLE players ADD COLUMN kick_return INTEGER",
        # Defense
        "ALTER TABLE players ADD COLUMN tackle INTEGER",
        "ALTER TABLE players ADD COLUMN hit_power INTEGER",
        "ALTER TABLE players ADD COLUMN pursuit INTEGER",
        "ALTER TABLE players ADD COLUMN block_shed INTEGER",
        "ALTER TABLE players ADD COLUMN power_moves INTEGER",
        "ALTER TABLE players ADD COLUMN finesse_moves INTEGER",
        "ALTER TABLE players ADD COLUMN break_sack INTEGER",
        "ALTER TABLE players ADD COLUMN man_cover INTEGER",
        "ALTER TABLE players ADD COLUMN zone_cover INTEGER",
        "ALTER TABLE players ADD COLUMN press INTEGER",
        "ALTER TABLE players ADD COLUMN play_rec INTEGER",
        "ALTER TABLE players ADD COLUMN confidence INTEGER",
        # Contract data
        "ALTER TABLE players ADD COLUMN contract_salary INTEGER",
        "ALTER TABLE players ADD COLUMN contract_bonus INTEGER",
        "ALTER TABLE players ADD COLUMN contract_length INTEGER",
        "ALTER TABLE players ADD COLUMN contract_years_left INTEGER",
        "ALTER TABLE players ADD COLUMN cap_hit INTEGER",
        "ALTER TABLE players ADD COLUMN cap_release_savings INTEGER",
        "ALTER TABLE players ADD COLUMN cap_release_penalty INTEGER",
        # Draft / background
        "ALTER TABLE players ADD COLUMN draft_round INTEGER",
        "ALTER TABLE players ADD COLUMN draft_pick INTEGER",
        "ALTER TABLE players ADD COLUMN rookie_year INTEGER",
        "ALTER TABLE players ADD COLUMN years_pro INTEGER",
        "ALTER TABLE players ADD COLUMN college TEXT",
        "ALTER TABLE players ADD COLUMN height INTEGER",
        "ALTER TABLE players ADD COLUMN weight INTEGER",
        "ALTER TABLE players ADD COLUMN jersey_num INTEGER",
        "ALTER TABLE players ADD COLUMN dev_trait INTEGER",
        # Birth date stored as ISO text (YYYY-MM-DD). When present, age is always
        # computed from this rather than from the stored age column.
        "ALTER TABLE players ADD COLUMN birth_date TEXT",
    ]:
        try:
            c.execute(sql)
        except Exception:
            pass

    # ── Player Abilities ───────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS player_abilities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
        ability_name TEXT NOT NULL,
        ability_type TEXT NOT NULL DEFAULT 'superstar',  -- 'xfactor' or 'superstar'
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_player_abilities_player_id ON player_abilities(player_id)")
    except Exception:
        pass

    # One-time owner name patches
    for short_name, owner in [('Falcons', 'Matt'), ('Lions', 'Maas'), ('Panthers', 'Michael')]:
        c.execute("UPDATE teams SET owner_name = ? WHERE short_name = ? AND (owner_name IS NULL OR owner_name = '')",
                  (owner, short_name))

    # ── Users ──────────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id TEXT UNIQUE,
        discord_username TEXT,
        discord_tag TEXT,
        display_name TEXT,
        role TEXT NOT NULL DEFAULT 'owner',  -- commissioner, assistant_commissioner, owner, readonly
        team_id INTEGER REFERENCES teams(id),
        avatar_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP
    )''')

    # ── Players ────────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        madden_id TEXT UNIQUE,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        position TEXT NOT NULL,
        age INTEGER,
        overall_rating INTEGER,
        projected_ovr INTEGER,  -- fallback OVR for rookies before Madden ratings load
        nfl_team TEXT,
        nml_team_id INTEGER REFERENCES teams(id),  -- NULL = free agent
        is_free_agent INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES users(id)
    )''')

    # Migration: add projected_ovr if missing (for upgrades from earlier schema).
    try:
        c.execute('ALTER TABLE players ADD COLUMN projected_ovr INTEGER')
    except sqlite3.OperationalError:
        pass  # column already exists

    # Player field update timestamps (for partial imports)
    c.execute('''CREATE TABLE IF NOT EXISTS player_field_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL REFERENCES players(id),
        field_name TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        changed_by INTEGER REFERENCES users(id)
    )''')

    # ── Draft Picks ────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS draft_picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL,
        round INTEGER NOT NULL,
        round_order INTEGER,          -- NULL for future year picks
        overall_order INTEGER,        -- NULL for future year picks
        original_owner_id INTEGER NOT NULL REFERENCES teams(id),
        current_owner_id INTEGER NOT NULL REFERENCES teams(id),
        is_comp_pick INTEGER NOT NULL DEFAULT 0,
        is_tradeable INTEGER NOT NULL DEFAULT 1,  -- comp picks default to 0
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # ── Trades ─────────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team1_id INTEGER NOT NULL REFERENCES teams(id),
        team2_id INTEGER NOT NULL REFERENCES teams(id),
        status TEXT NOT NULL DEFAULT 'pending_team2',
        -- pending_team2, rejected_team2, pending_team1_confirm, rejected_team1, completed
        proposed_by INTEGER REFERENCES users(id),
        proposed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        team2_responded_at TIMESTAMP,
        team2_responded_by INTEGER REFERENCES users(id),
        team1_confirmed_at TIMESTAMP,
        team1_confirmed_by INTEGER REFERENCES users(id),
        completed_at TIMESTAMP,
        notes TEXT
    )''')

    # Backfill proposed_by for any existing trades where it is NULL
    # team1 is always the proposer; look up their user record by team_id
    try:
        c.execute('''
            UPDATE trades SET proposed_by = (
                SELECT u.id FROM users u WHERE u.team_id = trades.team1_id LIMIT 1
            )
            WHERE proposed_by IS NULL
        ''')
    except Exception:
        pass

    c.execute('''CREATE TABLE IF NOT EXISTS trade_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER NOT NULL REFERENCES trades(id),
        asset_type TEXT NOT NULL,  -- 'player' or 'pick'
        player_id INTEGER REFERENCES players(id),
        pick_id INTEGER REFERENCES draft_picks(id),
        from_team_id INTEGER NOT NULL REFERENCES teams(id),
        to_team_id INTEGER NOT NULL REFERENCES teams(id)
    )''')

    # ── Transaction Log ────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,  -- trade, sign_player, cut_player, comp_pick, pick_generated, admin_edit
        trade_id INTEGER REFERENCES trades(id),
        player_id INTEGER REFERENCES players(id),
        pick_id INTEGER REFERENCES draft_picks(id),
        team_id INTEGER REFERENCES teams(id),
        description TEXT NOT NULL,
        discord_posted INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_by INTEGER REFERENCES users(id)
    )''')

    # ── Sessions ───────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL
    )''')

    # ── Login Codes (Discord DM verification) ──────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS login_codes (
        username_lower TEXT PRIMARY KEY,
        code TEXT NOT NULL,
        discord_user_id TEXT NOT NULL,
        expires_at TIMESTAMP NOT NULL
    )''')

    # ── Admin Audit Log ────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER REFERENCES users(id),
        action TEXT NOT NULL,
        entity_type TEXT,   -- player, team, pick, trade, settings
        entity_id INTEGER,
        old_value TEXT,
        new_value TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # ── League Settings ────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS league_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER REFERENCES users(id)
    )''')

    # Default league settings
    defaults = {
        'season_start_date': '2026-09-01',
        'season_end_date': '2027-03-01',
        'offseason_start_date': '2027-03-01',
        'draft_date': '2027-04-26',
        'trade_deadline_date': '2026-12-01',
        'roster_cap': '53',
        'trading_enabled': 'true',
        'discord_trades_channel_id': '',
        'discord_transactions_channel_id': '',
        'discord_bot_token': '',
        'post_trades_to_discord': 'true',
        'post_signings_to_discord': 'true',
        'post_cuts_to_discord': 'true',
        'current_draft_year': '2026',
        'discord_draft_channel_id': '1494025177095471204',
        'discord_backup_channel_id': '355873714358845441',
        'backup_discord_message_id': '',
        'discord_tradeblock_channel_id': '638449149813063681',
        'draft_timer_r1': '600',
        'draft_timer_r2': '420',
        'draft_timer_r3': '300',
        'draft_timer_r4': '240',
        'draft_timer_r5': '180',
        'draft_timer_r6': '180',
        'draft_timer_r7': '180',
    }
    for key, value in defaults.items():
        c.execute('INSERT OR IGNORE INTO league_settings (key, value) VALUES (?, ?)', (key, value))

    # ── Draft Session ─────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS draft_session (
        id INTEGER PRIMARY KEY,
        status TEXT DEFAULT 'pending',
        current_pick_index INTEGER DEFAULT 0,
        current_pick_started_at TIMESTAMP,
        started_at TIMESTAMP,
        completed_at TIMESTAMP
    )''')

    # ── Draft Selections (what each pick resulted in) ──────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS draft_selections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        draft_pick_id INTEGER NOT NULL REFERENCES draft_picks(id),
        team_id INTEGER NOT NULL REFERENCES teams(id),
        player_id INTEGER REFERENCES players(id),
        write_in_name TEXT,
        write_in_position TEXT,
        selected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_makeup_pick INTEGER DEFAULT 0,
        submitted_by_user_id INTEGER,
        submitted_by_name TEXT
    )''')
    # Migration: add submitted_by columns if table already exists without them
    for col, typedef in [('submitted_by_user_id', 'INTEGER'), ('submitted_by_name', 'TEXT')]:
        try:
            c.execute(f'ALTER TABLE draft_selections ADD COLUMN {col} {typedef}')
        except Exception:
            pass

    # ── Draft Makeup Queue (skipped picks waiting to be made up) ──────────────
    c.execute('''CREATE TABLE IF NOT EXISTS draft_makeup_queue (
        draft_pick_id INTEGER PRIMARY KEY REFERENCES draft_picks(id),
        team_id INTEGER NOT NULL REFERENCES teams(id),
        skipped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # ── Draft Queue (each team's pre-queued player wishlist) ──────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS draft_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        player_id INTEGER REFERENCES players(id),
        write_in_name TEXT,
        write_in_position TEXT,
        priority INTEGER NOT NULL,
        auto_submit INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # ── Team Needs Priority Board ──────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS team_needs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        item_type TEXT NOT NULL,
        item_key TEXT NOT NULL,
        tier TEXT NOT NULL,
        tier_order INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(team_id, item_key)
    )''')

    # ── Trusted Devices ────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS trusted_devices (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        device_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL
    )''')

    # ── Ideas (Feature Requests) ───────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS ideas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        submitted_by INTEGER NOT NULL REFERENCES users(id),
        status TEXT NOT NULL DEFAULT 'active',
        dismissal_reason TEXT,
        edited INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS idea_votes (
        idea_id INTEGER NOT NULL REFERENCES ideas(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        PRIMARY KEY (idea_id, user_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS trade_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER NOT NULL REFERENCES trades(id),
        token TEXT NOT NULL UNIQUE,
        action TEXT NOT NULL,
        team_id INTEGER NOT NULL,
        used INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS depth_chart (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        side TEXT NOT NULL,
        formation TEXT NOT NULL,
        slot TEXT NOT NULL,
        depth INTEGER NOT NULL DEFAULT 1,
        player_id INTEGER REFERENCES players(id),
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, side, formation, slot, depth)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS depth_chart_defaults (
        user_id INTEGER PRIMARY KEY REFERENCES users(id),
        default_defense TEXT,
        default_offense TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS dc_slot_eligibility (
        formation TEXT NOT NULL,
        slot TEXT NOT NULL,
        allowed_positions TEXT NOT NULL,
        PRIMARY KEY (formation, slot)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS user_roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        granted_by INTEGER REFERENCES users(id),
        granted_at TEXT DEFAULT (datetime('now')),
        UNIQUE(user_id, role)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
        added_at TEXT DEFAULT (datetime('now')),
        UNIQUE(user_id, player_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS player_ratings_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
        overall_rating INTEGER,
        speed INTEGER,
        strength INTEGER,
        awareness INTEGER,
        throw_power INTEGER,
        throw_acc INTEGER,
        catch INTEGER,
        route_short INTEGER,
        tackle INTEGER,
        block_shed INTEGER,
        pass_block INTEGER,
        man_cover INTEGER,
        zone_cover INTEGER,
        snapshot_label TEXT NOT NULL,
        snapshot_date TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS power_rankings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season TEXT NOT NULL,
        week_label TEXT NOT NULL,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        rank INTEGER NOT NULL,
        prev_rank INTEGER,
        score REAL NOT NULL,
        starter_ovr_score REAL,
        depth_score REAL,
        age_score REAL,
        pick_score REAL,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS power_ranking_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS draft_pick_chart (
        pick_num INTEGER PRIMARY KEY,
        value REAL NOT NULL
    )''')
    _seed_pick_chart(c)

    # ── Trade Grade Settings ───────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS trade_grade_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')

    try:
        defaults = {
            # Position multipliers (all 22 positions)
            'pos_QB': '1.3',
            'pos_WR': '1.15', 'pos_LEDGE': '1.15', 'pos_REDGE': '1.15',
            'pos_HB': '1.1', 'pos_LT': '1.1', 'pos_CB': '1.1',
            'pos_TE': '1.05',
            'pos_MIKE': '1.0',
            'pos_FS': '0.95', 'pos_SS': '0.95',
            'pos_WILL': '0.90', 'pos_SAM': '0.88',
            'pos_DT': '0.85',
            'pos_RT': '0.82', 'pos_LG': '0.80', 'pos_C': '0.80', 'pos_RG': '0.80',
            'pos_K': '0.55',
            'pos_FB': '0.50',
            'pos_P': '0.45',
            'pos_LS': '0.30',
            # Pick values by round
            'pick_1': '90', 'pick_2': '60', 'pick_3': '40', 'pick_4': '25',
            'pick_5': '16', 'pick_6': '10', 'pick_7': '6',
            # Year penalty per future year (multiplier)
            'pick_year_penalty': '0.3',
            # Grade thresholds (percent difference)
            'threshold_slight': '5', 'threshold_strong': '15', 'threshold_onesided': '30',
            # Scale multipliers
            'player_value_scale': '2.0',
            'pick_chart_scale': '0.10',
            # Speed bonus settings
            'speed_bonus_enabled': '1',
            'speed_bonus_scale': '0.15',
            'speed_bonus_positions': 'QB,HB,WR,TE,CB,FS,SS,SAM,MIKE,WILL,LEDGE,REDGE',
        }
        for k, v in defaults.items():
            c.execute('INSERT OR IGNORE INTO trade_grade_settings (key, value) VALUES (?, ?)', (k, v))
    except Exception as e:
        print(f"Warning: trade_grade_settings seed: {e}")

    # Seed power_ranking_settings defaults
    try:
        prs_defaults = {
            'weight_starter': '40',
            'weight_depth': '10',
            'weight_age': '25',
            'weight_pick': '25',
        }
        for k, v in prs_defaults.items():
            c.execute('INSERT OR IGNORE INTO power_ranking_settings (key, value) VALUES (?, ?)', (k, v))
    except Exception as e:
        print(f"Warning: power_ranking_settings seed: {e}")

    # ── Seasons & Schedule ─────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS seasons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL,
        name TEXT NOT NULL,
        is_current INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS schedule_weeks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
        week_num INTEGER NOT NULL,
        nfl_week_label TEXT,
        advance_date TEXT,
        UNIQUE(season_id, week_num)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_id INTEGER NOT NULL REFERENCES schedule_weeks(id) ON DELETE CASCADE,
        home_team_id INTEGER NOT NULL REFERENCES teams(id),
        away_team_id INTEGER NOT NULL REFERENCES teams(id),
        home_score INTEGER,
        away_score INTEGER,
        status TEXT DEFAULT 'scheduled'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS game_scheduling (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
        planned_datetime TEXT,
        stream_url TEXT,
        notes TEXT,
        posted_by_user_id INTEGER REFERENCES users(id),
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(game_id)
    )''')

    # ── NFL Draft Prospects (creator tool) ────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS draft_prospects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL DEFAULT 2026,
        name TEXT NOT NULL,
        position TEXT,
        school TEXT,
        class TEXT,
        birth_date TEXT,
        height TEXT,
        weight INTEGER,
        forty_combine REAL,
        forty_proday REAL,
        bench INTEGER,
        vertical REAL,
        broad INTEGER,
        three_cone REAL,
        shuttle REAL,
        ras REAL,
        consensus_rank INTEGER,
        pff_rank INTEGER,
        espn_rank INTEGER,
        drafttek_rank INTEGER,
        brugler_rank INTEGER,
        harmon_wr_rank INTEGER,
        thorn_ol_score REAL,
        personal_rank INTEGER,
        notes TEXT,
        nfl_team TEXT,
        nfl_round INTEGER,
        nfl_pick INTEGER,
        nfl_overall INTEGER,
        nml_team_id INTEGER REFERENCES teams(id),
        nml_round INTEGER,
        nml_pick INTEGER,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )''')
    try:
        c.execute('CREATE INDEX IF NOT EXISTS idx_draft_prospects_year ON draft_prospects(year)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_draft_prospects_pos ON draft_prospects(position)')
    except Exception:
        pass

    # ── NFL Draft History (last 20 years) ─────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS nfl_draft_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL,
        round INTEGER NOT NULL,
        pick INTEGER NOT NULL,
        overall INTEGER NOT NULL,
        nfl_team TEXT NOT NULL,
        player_name TEXT NOT NULL,
        position TEXT,
        school TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(year, overall)
    )''')
    try:
        c.execute('CREATE INDEX IF NOT EXISTS idx_nfl_draft_history_year ON nfl_draft_history(year)')
    except Exception:
        pass

    # ── Draft Board (personal prospect ranking) ────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS draft_board_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL DEFAULT 2026,
        user_id INTEGER NOT NULL REFERENCES users(id),
        prospect_id INTEGER NOT NULL REFERENCES draft_prospects(id) ON DELETE CASCADE,
        board_rank INTEGER,
        tier INTEGER,
        notes TEXT,
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(year, user_id, prospect_id)
    )''')

    # ── Mock Drafts ────────────────────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS mock_drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL DEFAULT 2026,
        user_id INTEGER NOT NULL REFERENCES users(id),
        name TEXT NOT NULL,
        is_published INTEGER NOT NULL DEFAULT 0,
        score INTEGER DEFAULT NULL,
        scored_at TEXT DEFAULT NULL,
        hit_3 INTEGER DEFAULT 0,
        hit_2 INTEGER DEFAULT 0,
        hit_1 INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS mock_draft_picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mock_draft_id INTEGER NOT NULL REFERENCES mock_drafts(id) ON DELETE CASCADE,
        overall_pick INTEGER NOT NULL,
        round INTEGER,
        pick_in_round INTEGER,
        nfl_team TEXT,
        prospect_id INTEGER REFERENCES players(id),
        prospect_name TEXT,
        position TEXT,
        notes TEXT,
        pick_points INTEGER DEFAULT NULL,
        actual_player_name TEXT DEFAULT NULL,
        actual_team TEXT DEFAULT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS nml_draft_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_year INTEGER NOT NULL DEFAULT 2026,
        overall_pick INTEGER NOT NULL,
        round INTEGER,
        pick_in_round INTEGER,
        nfl_team TEXT,
        player_id INTEGER REFERENCES players(id),
        player_name TEXT NOT NULL,
        position TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(season_year, overall_pick)
    )''')

    # ── Draft Review (NMLBot + user-published) ─────────────────────────────

    c.execute('''CREATE TABLE IF NOT EXISTS draft_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER NOT NULL DEFAULT 2026,
        author_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        author_label TEXT NOT NULL,
        is_published INTEGER NOT NULL DEFAULT 0,
        published_at TEXT DEFAULT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS draft_review_team_grades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        review_id INTEGER NOT NULL REFERENCES draft_reviews(id) ON DELETE CASCADE,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        league_rank INTEGER,
        value_grade INTEGER,
        need_grade INTEGER,
        talent_grade INTEGER,
        final_grade INTEGER,
        blurb TEXT,
        best_pick_overall INTEGER,
        worst_pick_overall INTEGER,
        best_pick_text TEXT,
        worst_pick_text TEXT,
        looking_ahead TEXT,
        unfilled_needs TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(review_id, team_id)
    )''')

    # Migration: add best_pick_text/worst_pick_text columns if missing (for upgrades from earlier schema).
    for col in ('best_pick_text', 'worst_pick_text'):
        try:
            c.execute(f'ALTER TABLE draft_review_team_grades ADD COLUMN {col} TEXT')
        except sqlite3.OperationalError:
            pass  # column already exists

    c.execute('''CREATE TABLE IF NOT EXISTS draft_review_picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        review_id INTEGER NOT NULL REFERENCES draft_reviews(id) ON DELETE CASCADE,
        team_id INTEGER NOT NULL REFERENCES teams(id),
        overall_pick INTEGER NOT NULL,
        round INTEGER,
        pick_in_round INTEGER,
        player_id INTEGER REFERENCES players(id),
        player_name TEXT,
        position TEXT,
        nml_rank INTEGER,
        nfl_consensus_rank INTEGER,
        nfl_actual_slot INTEGER,
        value_delta INTEGER,
        pick_grade INTEGER,
        note TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(review_id, overall_pick)
    )''')

    c.execute('CREATE INDEX IF NOT EXISTS idx_draft_reviews_year_pub ON draft_reviews(year, is_published)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_draft_review_team_grades_review ON draft_review_team_grades(review_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_draft_review_picks_review_team ON draft_review_picks(review_id, team_id)')

    # ── Analyst Scouting System (creator-only) ─────────────────────────────

    c.execute('''CREATE TABLE IF NOT EXISTS analysts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        affiliation TEXT,
        notes TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS analyst_position_trust (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        analyst_id INTEGER NOT NULL REFERENCES analysts(id) ON DELETE CASCADE,
        position_group TEXT NOT NULL,
        trust_weight REAL NOT NULL DEFAULT 1.0,
        is_position_expert INTEGER NOT NULL DEFAULT 0,
        auto_expert INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(analyst_id, position_group)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS analyst_rankings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        analyst_id INTEGER NOT NULL REFERENCES analysts(id) ON DELETE CASCADE,
        draft_year INTEGER NOT NULL,
        rank INTEGER NOT NULL,
        prospect_name TEXT NOT NULL,
        prospect_name_normalized TEXT,
        position TEXT,
        position_group TEXT,
        school TEXT,
        analyst_note TEXT,
        matched_prospect_id INTEGER REFERENCES draft_prospects(id),
        match_status TEXT NOT NULL DEFAULT 'unmatched',
        imported_at TEXT DEFAULT (datetime('now')),
        UNIQUE(analyst_id, draft_year, rank)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS analyst_player_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        analyst_id INTEGER NOT NULL REFERENCES analysts(id) ON DELETE CASCADE,
        draft_year INTEGER NOT NULL,
        prospect_name TEXT NOT NULL,
        prospect_name_normalized TEXT,
        position TEXT,
        school TEXT,
        injury_risk INTEGER NOT NULL DEFAULT 0,
        off_field_concern INTEGER NOT NULL DEFAULT 0,
        my_guy INTEGER NOT NULL DEFAULT 0,
        bust_risk INTEGER NOT NULL DEFAULT 0,
        sleeper INTEGER NOT NULL DEFAULT 0,
        scheme_dependent INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        matched_prospect_id INTEGER REFERENCES draft_prospects(id),
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(analyst_id, draft_year, prospect_name_normalized)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS player_nfl_performance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prospect_name TEXT NOT NULL,
        prospect_name_normalized TEXT,
        position TEXT,
        position_group TEXT,
        school TEXT,
        draft_year INTEGER,
        draft_round INTEGER,
        draft_pick INTEGER,
        nfl_team TEXT,
        nfl_season INTEGER NOT NULL,
        pfr_av INTEGER,
        pff_grade REAL,
        madden_ovr INTEGER,
        madden_game_year INTEGER,
        espn_war REAL,
        career_tier TEXT,
        matched_player_id INTEGER REFERENCES players(id),
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(prospect_name_normalized, draft_year, nfl_season)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS analyst_accuracy (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        analyst_id INTEGER NOT NULL REFERENCES analysts(id) ON DELETE CASCADE,
        draft_year INTEGER NOT NULL,
        position_group TEXT,
        hit_rate REAL,
        rank_correlation REAL,
        avg_rank_error REAL,
        sample_size INTEGER,
        computed_at TEXT DEFAULT (datetime('now')),
        UNIQUE(analyst_id, draft_year, position_group)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS consensus_rankings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        draft_year INTEGER NOT NULL,
        consensus_type TEXT NOT NULL,
        consensus_rank INTEGER NOT NULL,
        prospect_name TEXT NOT NULL,
        prospect_name_normalized TEXT,
        position TEXT,
        position_group TEXT,
        school TEXT,
        avg_rank REAL,
        rank_stddev REAL,
        analyst_count INTEGER,
        matched_prospect_id INTEGER REFERENCES draft_prospects(id),
        computed_at TEXT DEFAULT (datetime('now')),
        UNIQUE(draft_year, consensus_type, consensus_rank)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS draft_locks (
        year INTEGER PRIMARY KEY,
        locked_at TEXT DEFAULT (datetime('now')),
        locked_by_user_id INTEGER REFERENCES users(id)
    )''')

    # ── Migrations ─────────────────────────────────────────────────────────
    # Add twitch_url column to users
    try:
        c.execute('ALTER TABLE users ADD COLUMN twitch_url TEXT')
    except Exception:
        pass

    # Unique index for mock_draft_picks upsert support
    try:
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_mock_picks_unique ON mock_draft_picks(mock_draft_id, overall_pick)')
    except Exception:
        pass

    # Fix mock_draft_picks FK: was REFERENCES draft_prospects (wrong), should be REFERENCES players
    try:
        fk_rows = c.execute('PRAGMA foreign_key_list(mock_draft_picks)').fetchall()
        if any(row[2] == 'draft_prospects' for row in fk_rows):
            c.execute('''CREATE TABLE mock_draft_picks_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mock_draft_id INTEGER NOT NULL REFERENCES mock_drafts(id) ON DELETE CASCADE,
                overall_pick INTEGER NOT NULL,
                round INTEGER,
                pick_in_round INTEGER,
                nfl_team TEXT,
                prospect_id INTEGER REFERENCES players(id),
                prospect_name TEXT,
                position TEXT,
                notes TEXT
            )''')
            c.execute('''INSERT OR IGNORE INTO mock_draft_picks_v2
                (id, mock_draft_id, overall_pick, round, pick_in_round, nfl_team,
                 prospect_id, prospect_name, position, notes)
                SELECT id, mock_draft_id, overall_pick, round, pick_in_round, nfl_team,
                       NULL, prospect_name, position, notes
                FROM mock_draft_picks''')
            c.execute('DROP TABLE mock_draft_picks')
            c.execute('ALTER TABLE mock_draft_picks_v2 RENAME TO mock_draft_picks')
            c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_mock_picks_unique ON mock_draft_picks(mock_draft_id, overall_pick)')
    except Exception:
        pass

    # Draft prospect measurables expansion — combine/proday split + RAS link
    for col_def in [
        "ALTER TABLE draft_prospects ADD COLUMN ras_link TEXT",
        # Combine additions (height/weight/forty_combine/bench/vertical/broad/three_cone/shuttle already exist as combine)
        "ALTER TABLE draft_prospects ADD COLUMN ten_combine REAL",
        "ALTER TABLE draft_prospects ADD COLUMN twenty_combine REAL",
        "ALTER TABLE draft_prospects ADD COLUMN hand_combine REAL",
        "ALTER TABLE draft_prospects ADD COLUMN arm_combine REAL",
        "ALTER TABLE draft_prospects ADD COLUMN wing_combine REAL",
        # Pro day (forty_proday already exists)
        "ALTER TABLE draft_prospects ADD COLUMN height_proday TEXT",
        "ALTER TABLE draft_prospects ADD COLUMN weight_proday INTEGER",
        "ALTER TABLE draft_prospects ADD COLUMN ten_proday REAL",
        "ALTER TABLE draft_prospects ADD COLUMN twenty_proday REAL",
        "ALTER TABLE draft_prospects ADD COLUMN hand_proday REAL",
        "ALTER TABLE draft_prospects ADD COLUMN arm_proday REAL",
        "ALTER TABLE draft_prospects ADD COLUMN wing_proday REAL",
        "ALTER TABLE draft_prospects ADD COLUMN bench_proday INTEGER",
        "ALTER TABLE draft_prospects ADD COLUMN vertical_proday REAL",
        "ALTER TABLE draft_prospects ADD COLUMN broad_proday TEXT",
        "ALTER TABLE draft_prospects ADD COLUMN three_cone_proday REAL",
        "ALTER TABLE draft_prospects ADD COLUMN shuttle_proday REAL",
    ]:
        try:
            c.execute(col_def)
        except Exception:
            pass  # column already exists

    # Update trouse6 (user id=1) to creator role
    try:
        c.execute("UPDATE users SET role='creator' WHERE id=1 AND role='commissioner'")
    except Exception:
        pass

    # Populate user_roles table from users.role
    try:
        c.execute('''INSERT OR IGNORE INTO user_roles (user_id, role)
                     SELECT id, role FROM users WHERE role IS NOT NULL''')
    except Exception:
        pass

    # Fix pick_year_penalty if it's still at old value 0.1
    try:
        c.execute("UPDATE trade_grade_settings SET value='0.3' WHERE key='pick_year_penalty' AND value='0.1'")
    except Exception:
        pass

    # Bump FS and SS multipliers from 0.95 → 1.05 (league data shows safeties undervalued)
    try:
        c.execute("UPDATE trade_grade_settings SET value='1.05' WHERE key='pos_FS' AND CAST(value AS REAL) < 1.0")
        c.execute("UPDATE trade_grade_settings SET value='1.05' WHERE key='pos_SS' AND CAST(value AS REAL) < 1.0")
    except Exception:
        pass

    # Mock draft scoring columns
    for col_def in [
        "ALTER TABLE mock_drafts ADD COLUMN score INTEGER DEFAULT NULL",
        "ALTER TABLE mock_drafts ADD COLUMN scored_at TEXT DEFAULT NULL",
        "ALTER TABLE mock_drafts ADD COLUMN hit_3 INTEGER DEFAULT 0",
        "ALTER TABLE mock_drafts ADD COLUMN hit_2 INTEGER DEFAULT 0",
        "ALTER TABLE mock_drafts ADD COLUMN hit_1 INTEGER DEFAULT 0",
        "ALTER TABLE mock_draft_picks ADD COLUMN pick_points INTEGER DEFAULT NULL",
        "ALTER TABLE mock_draft_picks ADD COLUMN actual_player_name TEXT DEFAULT NULL",
        "ALTER TABLE mock_draft_picks ADD COLUMN actual_team TEXT DEFAULT NULL",
    ]:
        try:
            c.execute(col_def)
        except Exception:
            pass  # column already exists

    # Back-fill M26 Super Bowl Update ratings history baseline
    try:
        exists = conn.execute("SELECT COUNT(*) FROM player_ratings_history WHERE snapshot_label='M26 Super Bowl Update'").fetchone()[0]
        if exists == 0:
            conn.execute('''
                INSERT INTO player_ratings_history
                    (player_id, overall_rating, speed, strength, awareness,
                     throw_power, throw_acc, catch, route_short, tackle,
                     block_shed, pass_block, man_cover, zone_cover,
                     snapshot_label, snapshot_date)
                SELECT id, overall_rating, speed, strength, awareness,
                       throw_power, throw_acc, catch, route_short, tackle,
                       block_shed, pass_block, man_cover, zone_cover,
                       'M26 Super Bowl Update', '2026-04-17'
                FROM players
                WHERE overall_rating IS NOT NULL
            ''')
            print("✅ Back-filled M26 Super Bowl Update ratings history")
    except Exception as e:
        print(f"Warning: ratings history backfill: {e}")

    # ── Performance indexes (added April 23, 2026 — pre-draft readiness) ───
    # These dramatically reduce query time on hot-path endpoints when 32 users
    # are hitting the app simultaneously during the live draft. Safe to re-run
    # (IF NOT EXISTS). All target queries confirmed missing indexes via audit.
    for idx_sql in [
        # Draft hot path — called on every /api/draft/state and pick submission
        "CREATE INDEX IF NOT EXISTS idx_draft_selections_pick ON draft_selections(draft_pick_id)",
        "CREATE INDEX IF NOT EXISTS idx_draft_selections_player ON draft_selections(player_id)",
        "CREATE INDEX IF NOT EXISTS idx_draft_queue_team_auto ON draft_queue(team_id, auto_submit)",
        "CREATE INDEX IF NOT EXISTS idx_draft_picks_year_order ON draft_picks(year, overall_order)",
        # Trade Center — N+1 asset lookup + status filters
        "CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)",
        "CREATE INDEX IF NOT EXISTS idx_trades_team1 ON trades(team1_id)",
        "CREATE INDEX IF NOT EXISTS idx_trades_team2 ON trades(team2_id)",
        "CREATE INDEX IF NOT EXISTS idx_trade_assets_trade ON trade_assets(trade_id)",
        # Player search / filtering (All Players, draft pool, free agents)
        "CREATE INDEX IF NOT EXISTS idx_players_position ON players(position)",
        "CREATE INDEX IF NOT EXISTS idx_players_first_name ON players(first_name)",
        "CREATE INDEX IF NOT EXISTS idx_players_nml_team ON players(nml_team_id)",
        "CREATE INDEX IF NOT EXISTS idx_players_rookie_fa ON players(is_rookie_prospect, is_free_agent)",
        # Auth / Discord
        "CREATE INDEX IF NOT EXISTS idx_teams_discord ON teams(discord_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_trade_tokens_token ON trade_tokens(token)",
    ]:
        try:
            c.execute(idx_sql)
        except Exception:
            pass

    conn.commit()
    _seed_dc_eligibility(conn)
    _seed_analysts(conn)
    _seed_analyst_position_trust(conn)
    conn.close()
    print("✅ Database initialized successfully")


def _seed_pick_chart(c):
    """Seed draft_pick_chart with modern compressed ADP values for picks 1-260."""
    # Only seed if table is empty
    if c.execute('SELECT COUNT(*) FROM draft_pick_chart').fetchone()[0] > 0:
        return
    # Key anchor points for modern compressed chart
    anchors = {
        1:2800, 2:2580, 3:2330, 4:2130, 5:1980, 6:1850, 7:1740, 8:1640, 9:1560, 10:1490,
        11:1425, 12:1365, 13:1310, 14:1260, 15:1215, 16:1170, 17:1128, 18:1088, 19:1050, 20:1014,
        21:980, 22:947, 23:916, 24:886, 25:858, 26:830, 27:804, 28:779, 29:755, 30:731,
        31:710, 32:688, 33:668, 34:649, 35:631, 36:614, 37:597, 38:581, 39:565, 40:550,
        41:535, 42:521, 43:507, 44:494, 45:481, 46:469, 47:457, 48:445, 49:434, 50:423,
        51:413, 52:402, 53:393, 54:383, 55:374, 56:365, 57:356, 58:348, 59:340, 60:332,
        61:324, 62:316, 63:309, 64:301, 65:294, 66:287, 67:281, 68:274, 69:268, 70:262,
        71:256, 72:250, 73:244, 74:239, 75:233, 76:228, 77:222, 78:217, 79:212, 80:207,
        81:203, 82:198, 83:193, 84:189, 85:185, 86:181, 87:177, 88:173, 89:169, 90:165,
        91:161, 92:158, 93:155, 94:152, 95:149, 96:146, 97:143, 98:140, 99:137, 100:134,
        101:131, 102:128, 103:125, 104:123, 105:120, 106:118, 107:115, 108:113, 109:111, 110:109,
        111:107, 112:105, 113:103, 114:101, 115:99, 116:97, 117:95, 118:93, 119:91, 120:89,
        121:88, 122:86, 123:84, 124:83, 125:81, 126:80, 127:78, 128:77, 129:75, 130:74,
        131:72, 132:71, 133:70, 134:68, 135:67, 136:66, 137:65, 138:63, 139:62, 140:61,
        141:60, 142:59, 143:58, 144:57, 145:56, 146:55, 147:54, 148:53, 149:52, 150:51,
        151:50, 152:49, 153:48, 154:47, 155:46, 156:45, 157:44, 158:43, 159:42, 160:41,
        165:37, 170:33, 180:27, 190:21, 200:17, 210:13, 220:10, 230:8, 240:6, 250:4, 260:3
    }
    keys = sorted(anchors.keys())
    chart = {}
    for i in range(len(keys)):
        lo = keys[i]
        chart[lo] = anchors[lo]
        if i + 1 < len(keys):
            hi = keys[i+1]
            for p in range(lo+1, hi):
                t = (p - lo) / (hi - lo)
                chart[p] = round(anchors[lo] + t * (anchors[hi] - anchors[lo]), 1)
    for pick_num in range(1, 261):
        val = chart.get(pick_num, 3.0)
        c.execute('INSERT OR IGNORE INTO draft_pick_chart (pick_num, value) VALUES (?, ?)', (pick_num, val))


def _seed_dc_eligibility(conn):
    """Pre-load position eligibility rules if the table is empty."""
    existing = conn.execute('SELECT COUNT(*) FROM dc_slot_eligibility').fetchone()[0]
    if existing > 0:
        return  # Already seeded — don't overwrite admin customizations

    import json as _json

    OL   = ['LT','LG','C','RG','RT','OT']
    LB   = ['MIKE','WILL','SAM']
    LB_S = ['MIKE','WILL','SAM','FS','SS']   # nickel/dime LB slots
    DB   = ['CB','FS','SS']
    EDGE = ['LEDGE','REDGE']
    DT   = ['DT']
    DT_E = ['DT','LEDGE','REDGE']
    E_DT = ['LEDGE','REDGE','DT','MIKE','WILL','SAM']

    GLOBAL = {
        # Offense
        'QB':  ['QB'],
        'HB':  ['HB','FB','TE','WR'],
        'FB':  ['HB','FB','TE','DT'],
        'WR1': ['WR','TE','CB'],
        'WR2': ['WR','TE','CB'],
        'WR3': ['WR','TE','CB'],
        'WR4': ['WR','TE','CB'],
        'WR5': ['WR','TE','CB'],
        'TE':  ['TE','LT','RT','OT'],
        'TE1': ['TE','LT','RT','OT'],
        'TE2': ['TE','LT','RT','OT'],
        'LT':  OL, 'LG': OL, 'C': OL, 'RG': OL, 'RT': OL,
        # Defense — DL
        'LDE':  E_DT, 'RDE':  E_DT,
        'LDT':  DT_E, 'RDT':  DT_E, 'NT': DT_E,
        # Defense — LB (base: no safeties)
        'WLB':  LB, 'MLB': LB, 'SLB': LB,
        'LOLB': LB, 'ROLB': LB,
        'ILB1': LB, 'ILB2': LB,
        # Defense — DB
        'LCB': DB, 'RCB': DB, 'NB': DB,
        'FS':  ['FS','SS','CB'],
        'SS':  ['FS','SS','CB'],
        'S':   ['FS','SS','CB'],
        'LDB': DB, 'RDB': DB,
    }

    # Formation-specific overrides (only differing slots)
    OVERRIDES = {
        '4-2 Nickel': {'WLB': LB_S, 'SLB': LB_S},
        '4-1 Dime':   {'MLB': LB_S},
        '3-2 Dime':   {'WLB': LB_S, 'SLB': LB_S},
    }

    rows = [('global', slot, _json.dumps(pos)) for slot, pos in GLOBAL.items()]
    for formation, slots in OVERRIDES.items():
        for slot, pos in slots.items():
            rows.append((formation, slot, _json.dumps(pos)))

    conn.executemany(
        'INSERT OR IGNORE INTO dc_slot_eligibility (formation, slot, allowed_positions) VALUES (?,?,?)',
        rows
    )
    conn.commit()


def _seed_analysts(conn):
    """Seed the analysts table with the initial curated analyst roster."""
    analysts = [
        ('Dane Brugler',    'The Athletic',              'Publishes The Beast — most comprehensive annual draft guide; strong overall big board'),
        ('Lance Zierlein',  'NFL.com',                   'Former NFL scout; detailed scouting reports with NFL comparisons; archived back to 2016'),
        ('Daniel Jeremiah', 'NFL Network',               'Former NFL scout; strong on scheme fit, football IQ, and character evaluation'),
        ('Benjamin Solak',  'NFL Network',               'Strong QB evaluator; detailed film work on offensive skill positions'),
        ('Matt Miller',     'ESPN',                      'Solid overall board; notable track record on QB and OL'),
        ('Matt Harmon',     'Reception Perception',      'WR specialist; proprietary route-tree and reception charting methodology'),
        ('Brandon Thorn',   'Trench Warfare (Substack)', 'OL specialist; widely regarded as the best OL prospect evaluator in the business'),
        ('Todd McShay',     'ESPN',                      'Veteran analyst; broad position coverage; historical archives available'),
    ]
    for name, affiliation, notes in analysts:
        conn.execute(
            'INSERT OR IGNORE INTO analysts (name, affiliation, notes) VALUES (?,?,?)',
            (name, affiliation, notes)
        )
    conn.commit()


def _seed_analyst_position_trust(conn):
    """Seed position trust weights. Skips if already populated (admin-managed after initial seed)."""
    if conn.execute('SELECT COUNT(*) FROM analyst_position_trust').fetchone()[0] > 0:
        return

    # All 12 Big Board position groups
    POS_GROUPS = ['QB', 'RB', 'WR', 'TE', 'OT', 'OG', 'C', 'DT', 'Edge', 'LB', 'CB', 'S']

    # Known position specialists: name → {group: weight}
    # Default = 1.0; known specialist = 1.5; secondary strength = 1.2
    SPECIALISTS = {
        'Matt Harmon':     {'WR': 1.5},
        'Brandon Thorn':   {'OT': 1.5, 'OG': 1.5, 'C': 1.5},
        'Benjamin Solak':  {'QB': 1.5, 'WR': 1.2},
        'Matt Miller':     {'QB': 1.2, 'OT': 1.2, 'OG': 1.2},
        'Daniel Jeremiah': {'QB': 1.2},
    }

    analysts = {row['name']: row['id']
                for row in conn.execute('SELECT id, name FROM analysts').fetchall()}

    rows = []
    for name, analyst_id in analysts.items():
        spec = SPECIALISTS.get(name, {})
        for pg in POS_GROUPS:
            weight = spec.get(pg, 1.0)
            is_expert = 1 if weight >= 1.5 else 0
            rows.append((analyst_id, pg, weight, is_expert))

    conn.executemany(
        '''INSERT OR IGNORE INTO analyst_position_trust
           (analyst_id, position_group, trust_weight, is_position_expert)
           VALUES (?,?,?,?)''',
        rows
    )
    conn.commit()


def migrate_nfl_history_2026(conn=None):
    """One-time auto-migration: seed nfl_draft_history from draft_prospects for 2026.
    Safe to call on every startup — no-ops if 2026 rows already exist."""
    close = conn is None
    if close:
        conn = get_db()
    try:
        count = conn.execute('SELECT COUNT(*) FROM nfl_draft_history WHERE year=2026').fetchone()[0]
        if count == 0:
            rows = conn.execute('''
                SELECT year, nfl_round, nfl_pick, nfl_overall, nfl_team, name, position, school
                FROM draft_prospects
                WHERE year=2026 AND nfl_overall IS NOT NULL
                ORDER BY nfl_overall
            ''').fetchall()
            for r in rows:
                conn.execute('''
                    INSERT OR IGNORE INTO nfl_draft_history
                        (year, round, pick, overall, nfl_team, player_name, position, school)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (r['year'], r['nfl_round'], r['nfl_pick'], r['nfl_overall'],
                      r['nfl_team'] or '', r['name'],
                      r['position'] or '', r['school'] or ''))
            conn.commit()
    finally:
        if close:
            conn.close()


if __name__ == '__main__':
    init_db()
