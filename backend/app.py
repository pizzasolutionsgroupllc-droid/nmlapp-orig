from flask import Flask, jsonify, request, g, redirect, send_file
from flask_cors import CORS
from flask_compress import Compress
from database import get_db, init_db, generate_trade_token, migrate_nfl_history_2026
from auth import (require_auth, require_role, get_current_user, is_admin, is_creator,
                  can_manage_team, create_session, upsert_user,
                  get_oauth_url, exchange_code, get_discord_user,
                  send_discord_message, send_discord_dm, notify_trade_action,
                  ROLE_HIERARCHY)
from importer import validate_import, commit_import, generate_import_template
from discord_bot import (notify_draft_on_clock, notify_draft_on_deck,
                         notify_draft_skipped, notify_draft_pick_made)
import json
import io
import os
import re
import secrets
import threading
import unicodedata
from datetime import datetime, timezone, date as date_type

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB — needed for Madden JSON exports
app.config['COMPRESS_MIMETYPES'] = ['application/json', 'text/html', 'text/css', 'application/javascript']
app.config['COMPRESS_LEVEL'] = 6
app.config['COMPRESS_MIN_SIZE'] = 1000
CORS(app, supports_credentials=True)
Compress(app)

# Initialize DB on startup (works for both direct run and gunicorn)
init_db()
migrate_nfl_history_2026()  # one-time: seed nfl_draft_history from draft_prospects for 2026

# True when running locally — either explicitly set or no Railway domain present
IS_LOCAL_DEV = os.environ.get('LOCAL_DEV_MODE') == 'true' or not os.environ.get('RAILWAY_PUBLIC_DOMAIN')

# ── Simple in-memory cache (safe with 1 Gunicorn worker) ──────────────────
_CACHE = {}
_CACHE_TTL = 300  # 5 minutes

def _cache_get(key):
    entry = _CACHE.get(key)
    if not entry:
        return None
    if (datetime.now(timezone.utc) - entry['ts']).total_seconds() > _CACHE_TTL:
        del _CACHE[key]
        return None
    return entry['data']

def _cache_set(key, data):
    _CACHE[key] = {'ts': datetime.now(timezone.utc), 'data': data}

def _cache_bust(prefix='players_'):
    for k in list(_CACHE.keys()):
        if k.startswith(prefix):
            del _CACHE[k]

def _fire_and_forget(fn, *args, **kwargs):
    """Run fn in a background daemon thread — used to fire Discord notifications
    without blocking the HTTP response."""
    def run():
        try:
            fn(*args, **kwargs)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def _auto_reject_trades_for_pick(conn, pick_id, player_name=''):
    """When a draft pick is used, auto-reject any trades still in a pending
    status (pending_team2 / pending_team1_confirm) that include this pick.
    Notifies both teams via Discord DM. Caller is responsible for conn.commit().

    Returns list of rejected trade ids (for logging / debugging)."""
    affected = conn.execute('''
        SELECT DISTINCT t.id as trade_id, t.team1_id, t.team2_id, t.notes,
               dp.round as pick_round, dp.year as pick_year,
               orig.abbreviation as pick_orig_abbrev
        FROM trades t
        JOIN trade_assets ta ON ta.trade_id = t.id
        JOIN draft_picks dp ON dp.id = ta.pick_id
        JOIN teams orig ON orig.id = dp.original_owner_id
        WHERE ta.asset_type = 'pick' AND ta.pick_id = ?
          AND t.status IN ('pending_team2', 'pending_team1_confirm')
    ''', (pick_id,)).fetchall()

    rejected_ids = []
    for t in affected:
        pick_label = f"{t['pick_round']}-{t['pick_orig_abbrev']}-{t['pick_year']}"
        reason = f"Pick {pick_label} was used in the draft" + (f" to select {player_name}" if player_name else "")
        conn.execute(
            "UPDATE trades SET status = 'rejected_team2', rejection_reason = ? WHERE id = ?",
            (reason, t['trade_id'])
        )
        # Notify both teams via Discord (non-blocking)
        trade_record = {
            'id': t['trade_id'],
            'team1_id': t['team1_id'],
            'team2_id': t['team2_id'],
            'notes': t['notes'] or ''
        }
        _fire_and_forget(notify_trade_action, trade_record, 'auto_rejected_pick_used', t['team1_id'])
        _fire_and_forget(notify_trade_action, trade_record, 'auto_rejected_pick_used', t['team2_id'])
        rejected_ids.append(t['trade_id'])

    return rejected_ids

# ── Helpers ────────────────────────────────────────────────────────────────

def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def compute_age(player_dict):
    """
    If the player has a birth_date (ISO string YYYY-MM-DD), compute their
    current age and overwrite the stored 'age' value so the frontend always
    shows the correct number. Falls back to the stored age when birth_date
    is absent or unparseable.
    """
    bd = player_dict.get('birth_date')
    if bd:
        try:
            dob = date_type.fromisoformat(bd)
            today = date_type.today()
            age = today.year - dob.year - (
                (today.month, today.day) < (dob.month, dob.day)
            )
            player_dict['age'] = age
        except (ValueError, TypeError):
            pass
    return player_dict


def rows_to_list(rows):
    return [dict(r) for r in rows]

def get_setting(key):
    conn = get_db()
    row = conn.execute('SELECT value FROM league_settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else None

def log_audit(user_id, action, entity_type, entity_id, old_val, new_val):
    conn = get_db()
    conn.execute('''INSERT INTO audit_log (user_id, action, entity_type, entity_id, old_value, new_value)
        VALUES (?, ?, ?, ?, ?, ?)''',
        (user_id, action, entity_type, entity_id,
         json.dumps(old_val) if old_val else None,
         json.dumps(new_val) if new_val else None))
    conn.commit()
    conn.close()

# ── Auth Routes ───────────────────────────────────────────────────────────

_oauth_states = {}  # state -> True (simple CSRF protection)

@app.route('/auth/login')
def auth_login():
    state = secrets.token_urlsafe(16)
    _oauth_states[state] = True
    url = get_oauth_url(state)
    # If Discord not configured, return mock login info
    if not os.environ.get('DISCORD_CLIENT_ID'):
        return jsonify({
            'error': 'Discord OAuth not configured yet',
            'setup_required': True,
            'instructions': 'Set DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, and DISCORD_BOT_TOKEN environment variables'
        }), 503
    return redirect(url)

@app.route('/auth/callback')
def auth_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    if not code or state not in _oauth_states:
        return jsonify({'error': 'Invalid OAuth callback'}), 400
    del _oauth_states[state]

    token_data = exchange_code(code)
    if not token_data:
        return jsonify({'error': 'Failed to exchange code'}), 400

    discord_user = get_discord_user(token_data['access_token'])
    if not discord_user:
        return jsonify({'error': 'Failed to get Discord user'}), 400

    user = upsert_user(discord_user)
    session_token = create_session(user['id'])
    # Redirect to frontend with token
    return redirect(f'/?token={session_token}')

@app.route('/auth/mock-login', methods=['POST'])
def mock_login():
    """Dev/setup endpoint: create a session without Discord OAuth.
    Used during initial setup before Discord bot is configured."""
    data = request.json or {}
    username = data.get('username', 'admin')
    username = data.get('username', 'admin')
    discord_id = data.get('discord_id', 'mock_' + username)
    role = data.get('role', 'commissioner')

    conn = get_db()
    existing = conn.execute('SELECT * FROM users WHERE discord_id = ?', (discord_id,)).fetchone()
    if existing:
        user_id = existing['id']
        conn.execute('UPDATE users SET role = ?, last_login = CURRENT_TIMESTAMP WHERE id = ?', (role, user_id))
    else:
        c = conn.execute('''INSERT INTO users (discord_id, discord_username, display_name, role)
            VALUES (?, ?, ?, ?)''', (discord_id, username, username, role))
        user_id = c.lastrowid
    conn.commit()
    conn.close()

    token = create_session(user_id)
    return jsonify({'token': token, 'user_id': user_id, 'role': role})

@app.route('/auth/request-code', methods=['POST'])
def auth_request_code():
    data = request.json or {}
    username = data.get('username', '').strip()
    if not username:
        return jsonify({'error': 'Username required'}), 400
    from auth import request_verification_code
    success, error = request_verification_code(username)
    if not success:
        return jsonify({'error': error}), 400
    return jsonify({'success': True})


@app.route('/auth/verify-code', methods=['POST'])
def auth_verify_code():
    data = request.json or {}
    username = data.get('username', '').strip()
    code = data.get('code', '').strip()
    if not username or not code:
        return jsonify({'error': 'Username and code required'}), 400
    from auth import verify_login_code, _parse_device_name
    ua = request.headers.get('User-Agent', '')
    device_name = _parse_device_name(ua)
    session_token, device_token, error = verify_login_code(username, code, device_name)
    if not session_token:
        return jsonify({'error': error}), 400
    return jsonify({'token': session_token, 'device_token': device_token})


@app.route('/auth/device-login', methods=['POST'])
def auth_device_login():
    """Exchange a trusted device token for a new session token — no PIN needed."""
    data = request.json or {}
    device_token = data.get('device_token', '').strip()
    from auth import verify_device_token
    session_token, error = verify_device_token(device_token)
    if not session_token:
        return jsonify({'error': error}), 401
    return jsonify({'token': session_token})


@app.route('/auth/dev-login', methods=['POST'])
def auth_dev_login():
    """Dev-only endpoint: log in as creator without Discord OAuth."""
    if not IS_LOCAL_DEV:
        return jsonify({'error': 'Not available in production'}), 403

    conn = get_db()
    creator = conn.execute('SELECT * FROM users WHERE role = ?', ('creator',)).fetchone()
    conn.close()

    if not creator:
        return jsonify({'error': 'No creator user found'}), 404

    creator_dict = dict(creator)
    session_token = create_session(creator_dict['id'])
    return jsonify({'token': session_token, 'user': creator_dict})


@app.route('/auth/impersonate/<int:user_id>', methods=['POST'])
def auth_impersonate(user_id):
    """Dev-only endpoint: impersonate another user as creator."""
    if not IS_LOCAL_DEV:
        return jsonify({'error': 'Not available in production'}), 403

    user = get_current_user()
    if not user or user['role'] != 'creator':
        return jsonify({'error': 'Requires creator role'}), 403

    conn = get_db()
    target_user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()

    if not target_user:
        return jsonify({'error': 'User not found'}), 404

    target_dict = dict(target_user)
    session_token = create_session(target_dict['id'])
    return jsonify({'token': session_token, 'user': target_dict})


@app.route('/api/my-devices')
@require_auth
def my_devices():
    """Return the current user's trusted devices."""
    user = request.current_user
    conn = get_db()
    rows = conn.execute(
        """SELECT token, device_name, created_at, last_used_at, expires_at
           FROM trusted_devices WHERE user_id = ? ORDER BY last_used_at DESC""",
        (user['id'],)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/my-devices/<token>', methods=['DELETE'])
@require_auth
def delete_my_device(token):
    """Revoke one of the current user's trusted devices."""
    user = request.current_user
    conn = get_db()
    result = conn.execute(
        "DELETE FROM trusted_devices WHERE token = ? AND user_id = ?",
        (token, user['id'])
    )
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        return jsonify({'error': 'Device not found'}), 404
    return jsonify({'success': True})


@app.route('/api/admin/users/<int:user_id>/devices', methods=['DELETE'])
@require_role('creator')
def admin_revoke_user_devices(user_id):
    """Commissioner: revoke ALL trusted devices for a specific user."""
    conn = get_db()
    result = conn.execute("DELETE FROM trusted_devices WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'revoked': result.rowcount})


@app.route('/api/dev/write-import', methods=['POST'])
def dev_write_import():
    """Dev-only: write JSON data directly to imports/ folder from Chrome extraction."""
    import os
    # Only allow from localhost
    if request.remote_addr not in ('127.0.0.1', '::1', 'localhost'):
        return jsonify({'error': 'Local only'}), 403
    data = request.get_json() or {}
    filename = data.get('filename', '')
    records  = data.get('records', [])
    # Sanitize filename — only allow alphanumeric, underscore, hyphen, dot
    import re
    if not filename or not re.match(r'^[\w\-]+\.json$', filename):
        return jsonify({'error': 'Invalid filename'}), 400
    imports_dir = os.path.join(os.path.dirname(__file__), '..', 'imports')
    os.makedirs(imports_dir, exist_ok=True)
    out_path = os.path.join(imports_dir, filename)
    import json
    # Append to existing file if it exists, else create
    existing = []
    if os.path.exists(out_path):
        with open(out_path) as f:
            try: existing = json.load(f)
            except: existing = []
    combined = existing + records
    with open(out_path, 'w') as f:
        json.dump(combined, f, indent=2)
    return jsonify({'ok': True, 'written': len(records), 'total': len(combined), 'file': filename})


@app.route('/auth/me')
@require_auth
def auth_me():
    user = request.current_user
    conn = get_db()
    team = None
    if user.get('team_id'):
        t = conn.execute('SELECT id, full_name, short_name, abbreviation FROM teams WHERE id = ?',
                        (user['team_id'],)).fetchone()
        team = dict(t) if t else None
    conn.close()
    return jsonify({**user, 'team': team})

@app.route('/auth/logout', methods=['POST'])
def auth_logout():
    from auth import delete_session
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        delete_session(auth[7:])
    return jsonify({'success': True})

# ── Users ──────────────────────────────────────────────────────────────────

@app.route('/api/users', methods=['GET'])
@require_role('assistant_commissioner')
def get_users():
    conn = get_db()
    # "Online" = has an active session created in the last hour
    recent = conn.execute(
        "SELECT DISTINCT user_id FROM sessions WHERE created_at > datetime('now', '-1 hour') AND expires_at > datetime('now')"
    ).fetchall()
    active_user_ids = {r['user_id'] for r in recent}
    # All users who have logged in
    users = rows_to_list(conn.execute('''SELECT u.*, t.full_name as team_name, t.short_name as team_short_name, t.abbreviation as team_abbrev
        FROM users u LEFT JOIN teams t ON t.id = u.team_id''').fetchall())

    # Teams with a discord ID assigned but the owner hasn't logged in yet
    # Exclude teams that already have a user linked to them (by discord_id or team_id)
    ghost_teams = rows_to_list(conn.execute('''
        SELECT t.id as team_id, t.full_name as team_name, t.short_name as team_short_name, t.abbreviation as team_abbrev,
               t.owner_name as display_name, t.discord_username, t.discord_tag,
               t.discord_user_id as discord_id, t.pending_role
        FROM teams t
        WHERE t.discord_user_id IS NOT NULL AND t.discord_user_id != ''
          AND t.discord_user_id NOT IN (
              SELECT discord_id FROM users WHERE discord_id IS NOT NULL
          )
          AND t.id NOT IN (
              SELECT team_id FROM users WHERE team_id IS NOT NULL
          )
    ''').fetchall())

    # Fetch all user_roles
    all_roles = conn.execute('SELECT user_id, role FROM user_roles').fetchall()
    roles_by_user = {}
    for r in all_roles:
        roles_by_user.setdefault(r['user_id'], []).append(r['role'])
    conn.close()

    result = []
    for u in users:
        u['is_online'] = u['id'] in active_user_ids
        # Attach roles list: use roles from user_roles table, fall back to single role column
        u['roles'] = roles_by_user.get(u['id'], [u['role']] if u.get('role') else [])
        result.append(u)
    for t in ghost_teams:
        t['id'] = None
        t['role'] = t.get('pending_role', 'owner')
        t['is_online'] = False
        t['roles'] = [t['role']]
        result.append(t)

    return jsonify(result)

@app.route('/api/users/<int:user_id>', methods=['PATCH'])
@require_role('assistant_commissioner')
def update_user(user_id):
    data = request.json
    allowed = ['role', 'team_id', 'display_name']
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'No valid fields'}), 400

    conn = get_db()
    old = row_to_dict(conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone())
    sets = ', '.join(f'{k} = ?' for k in updates)
    conn.execute(f'UPDATE users SET {sets} WHERE id = ?', list(updates.values()) + [user_id])
    conn.commit()
    new = row_to_dict(conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone())
    conn.close()
    log_audit(request.current_user['id'], 'update_user', 'user', user_id, old, new)
    return jsonify(new)

@app.route('/api/users/<int:user_id>/roles', methods=['POST'])
@require_role('assistant_commissioner')
def add_user_role(user_id):
    current = get_current_user()
    data = request.get_json()
    role = data.get('role', '').strip()
    valid_roles = ['creator', 'commissioner', 'assistant_commissioner', 'owner', 'readonly']
    if role not in valid_roles:
        return jsonify({'error': 'Invalid role'}), 400
    # Only creator can grant the creator role
    if role == 'creator' and not is_creator(current):
        return jsonify({'error': 'Only a creator can grant the creator role'}), 403
    conn = get_db()
    conn.execute('INSERT OR IGNORE INTO user_roles (user_id, role) VALUES (?, ?)', (user_id, role))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/users/<int:user_id>/roles/<role>', methods=['DELETE'])
@require_role('assistant_commissioner')
def remove_user_role(user_id, role):
    conn = get_db()
    conn.execute('DELETE FROM user_roles WHERE user_id=? AND role=?', (user_id, role))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/teams/<int:team_id>/pending-role', methods=['PATCH'])
@require_role('assistant_commissioner')
def set_pending_role(team_id):
    """Pre-assign a role for a team owner before they log in."""
    data = request.json or {}
    role = data.get('role')
    valid_roles = ('commissioner', 'assistant_commissioner', 'owner', 'readonly')
    if role not in valid_roles:
        return jsonify({'error': 'Invalid role'}), 400
    conn = get_db()
    conn.execute('UPDATE teams SET pending_role = ? WHERE id = ?', (role, team_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'team_id': team_id, 'pending_role': role})

@app.route('/api/teams/<int:team_id>/assign-owner', methods=['POST'])
@require_role('assistant_commissioner')
def assign_team_owner(team_id):
    """Assign a Discord user to a team, updating team discord fields"""
    data = request.json
    discord_user_id = data.get('discord_user_id')
    discord_username = data.get('discord_username')
    discord_tag = data.get('discord_tag')
    owner_name = data.get('owner_name')

    conn = get_db()
    old = row_to_dict(conn.execute('SELECT * FROM teams WHERE id = ?', (team_id,)).fetchone())
    conn.execute('''UPDATE teams SET discord_user_id=?, discord_username=?, discord_tag=?,
        owner_name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?''',
        (discord_user_id, discord_username, discord_tag, owner_name, team_id))

    # Link user record to team if they exist
    if discord_user_id:
        conn.execute('UPDATE users SET team_id=?, role=? WHERE discord_id=? AND role=?',
                     (team_id, 'owner', discord_user_id, 'readonly'))

    conn.commit()
    new = row_to_dict(conn.execute('SELECT * FROM teams WHERE id = ?', (team_id,)).fetchone())
    conn.close()
    log_audit(request.current_user['id'], 'assign_team_owner', 'team', team_id, old, new)
    return jsonify(new)

# ── Import Routes ──────────────────────────────────────────────────────────

@app.route('/api/import/template')
def download_template():
    """Download blank Excel import template"""
    template_bytes = generate_import_template()
    return send_file(
        io.BytesIO(template_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='NML_Player_Import_Template.xlsx'
    )

@app.route('/api/import/validate', methods=['POST'])
@require_role('assistant_commissioner')
def import_validate():
    """Validate Excel file and return preview before committing"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    team_id = request.form.get('team_id')
    file_bytes = file.read()

    result = validate_import(file_bytes, target_team_id=int(team_id) if team_id else None)
    return jsonify(result)

@app.route('/api/import/commit', methods=['POST'])
@require_role('assistant_commissioner')
def import_commit():
    """Commit a previously validated import"""
    data = request.json
    players = data.get('players', [])
    if not players:
        return jsonify({'error': 'No players to import'}), 400

    result = commit_import(players, imported_by_user_id=request.current_user['id'])
    log_audit(request.current_user['id'], 'bulk_import', 'player', None, None,
              {'created': result['created'], 'updated': result['updated']})

    conn = get_db()
    conn.execute('''INSERT INTO transactions (type, description, discord_posted)
        VALUES ('admin_edit', ?, 0)''',
        (f"Bulk import: {result['created']} players created, {result['updated']} updated",))
    conn.commit()
    conn.close()
    return jsonify(result)

# ── Madden Import Helpers ─────────────────────────────────────────────────

def _norm(name):
    """Normalize a player name for fuzzy matching."""
    n = re.sub(r"[.'\-]", '', name.lower().strip())
    return re.sub(r'\s+', ' ', n)

def _norm_no_suffix(name):
    return re.sub(r'\s+(jr|sr|ii|iii|iv|v)$', '', _norm(name))

def _build_player_lookups(conn):
    """Return three dicts for fast player lookup from DB."""
    rows = conn.execute(
        'SELECT id, first_name, last_name, position, madden_id, nml_team_id FROM players'
    ).fetchall()
    by_id, by_name, by_name_ns = {}, {}, {}
    for p in rows:
        d = dict(p)
        if d['madden_id']:
            by_id[str(d['madden_id'])] = d
        full = d['first_name'] + ' ' + d['last_name']
        by_name.setdefault(_norm(full), []).append(d)
        by_name_ns.setdefault(_norm_no_suffix(full), []).append(d)
    return by_id, by_name, by_name_ns

def _pick_name_match(hits, pos):
    """Return single DB player from name hits, using position as tiebreaker."""
    if len(hits) == 1:
        return hits[0]
    exact = [h for h in hits if h['position'] == pos]
    if len(exact) == 1:
        return exact[0]
    OL = {'LT','RT','LG','RG','C','OT','OG'}
    LB = {'LOLB','ROLB','MLB','WILL','MIKE','SAM','LB'}
    if pos in OL:
        g = [h for h in hits if h['position'] in OL]
        if len(g) == 1: return g[0]
    if pos in LB:
        g = [h for h in hits if h['position'] in LB]
        if len(g) == 1: return g[0]
    return None

# ── Madden Import: Roster & ID Sync ───────────────────────────────────────

@app.route('/api/import/madden-roster', methods=['POST'])
@require_role('assistant_commissioner')
def import_madden_roster():
    """
    Import teams.json from the Madden companion app export.
    Pass ?dry_run=0 to commit; default is preview only.
    Returns a summary of changes (new madden IDs, team moves, new players).
    """
    dry_run = request.args.get('dry_run', '1') != '0'

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    try:
        data = json.loads(request.files['file'].read().decode('utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object (teams.json format)')
    except Exception as e:
        return jsonify({'error': f'Invalid file: {e}'}), 400

    conn = get_db()

    # Build Madden team ID → NML team lookup
    team_rows = conn.execute(
        'SELECT id, abbreviation, madden_team_id FROM teams WHERE madden_team_id IS NOT NULL'
    ).fetchall()
    team_by_madden  = {str(r['madden_team_id']): r['id']           for r in team_rows}
    team_abbrev     = {r['id']: r['abbreviation']                  for r in team_rows}

    by_id, by_name, by_name_ns = _build_player_lookups(conn)
    used_rids = set(by_id.keys())  # rosterIds already assigned — prevent double-assign

    new_ids, team_changes, new_players = [], [], []
    no_change = 0
    pending_updates = []   # (db_id, new_madden_id_or_None, new_nml_team_id_or_None)
    pending_inserts = []   # dicts of new player data

    for madden_tid, team_data in data.items():
        nml_tid = team_by_madden.get(str(madden_tid))
        if nml_tid is None:
            continue  # unknown Madden team — skip

        for rid, p in team_data.get('roster', {}).items():
            rid  = str(rid)
            fn   = p.get('firstName', '').strip()
            ln   = p.get('lastName',  '').strip()
            pos  = p.get('position',  '')
            full = fn + ' ' + ln

            # ── Find matching DB player ───────────────────────────────────
            db_p = by_id.get(rid)
            new_rid = None

            if db_p is None:
                # Name-match fallback (only for players without a madden_id)
                hits = by_name.get(_norm(full)) or by_name_ns.get(_norm_no_suffix(full), [])
                db_p = _pick_name_match(hits, pos)
                if db_p and not db_p['madden_id'] and rid not in used_rids:
                    new_rid = rid   # will assign this madden_id

            if db_p is None:
                # Genuinely new player
                if rid not in used_rids:
                    new_players.append({'name': full, 'position': pos,
                                        'team': team_abbrev.get(nml_tid, str(nml_tid)),
                                        'nml_team_id': nml_tid, 'madden_id': rid})
                    pending_inserts.append({'madden_id': rid, 'first_name': fn,
                                            'last_name': ln, 'position': pos,
                                            'nml_team_id': nml_tid})
                continue

            # ── Compare vs DB ────────────────────────────────────────────
            assign_id    = new_rid
            assign_team  = nml_tid if str(db_p.get('nml_team_id') or '') != str(nml_tid) else None

            if assign_id:
                used_rids.add(rid)
                new_ids.append({'name': full, 'position': pos,
                                'team': team_abbrev.get(nml_tid, str(nml_tid))})
            if assign_team:
                from_abbrev = team_abbrev.get(db_p.get('nml_team_id'), '—')
                to_abbrev   = team_abbrev.get(nml_tid, str(nml_tid))
                team_changes.append({'name': full, 'position': pos,
                                     'from_team': from_abbrev, 'to_team': to_abbrev})

            if assign_id or assign_team:
                pending_updates.append((db_p['id'], assign_id, assign_team))
            else:
                no_change += 1

    if not dry_run:
        for db_id, new_mid, new_tid in pending_updates:
            if new_mid:
                conn.execute('UPDATE players SET madden_id = ? WHERE id = ?', (new_mid, db_id))
            if new_tid:
                conn.execute('UPDATE players SET nml_team_id = ? WHERE id = ?', (new_tid, db_id))
        for np in pending_inserts:
            conn.execute(
                '''INSERT OR IGNORE INTO players
                   (madden_id, first_name, last_name, position, nml_team_id, is_free_agent)
                   VALUES (?, ?, ?, ?, ?, 0)''',
                (np['madden_id'], np['first_name'], np['last_name'],
                 np['position'], np['nml_team_id'])
            )
        conn.commit()
        log_audit(request.current_user['id'], 'madden_roster_import', 'player', None, None,
                  {'new_ids': len(new_ids), 'team_changes': len(team_changes),
                   'new_players': len(new_players)})

    conn.close()
    return jsonify({
        'dry_run':            dry_run,
        'new_ids':            new_ids,
        'new_ids_count':      len(new_ids),
        'team_changes':       team_changes,
        'team_changes_count': len(team_changes),
        'new_players':        new_players,
        'new_players_count':  len(new_players),
        'no_change_count':    no_change,
    })


# ── Madden Import: Ratings Sync ────────────────────────────────────────────

@app.route('/api/import/madden-ratings', methods=['POST'])
@require_role('assistant_commissioner')
def import_madden_ratings():
    """
    Import roster.json from the Madden companion app export.
    Updates overall_rating, age, and position for players matched by madden_id.
    Pass ?dry_run=0 to commit; default is preview only.
    """
    dry_run = request.args.get('dry_run', '1') != '0'

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    try:
        data = json.loads(request.files['file'].read().decode('utf-8'))
        if not isinstance(data, list):
            raise ValueError('Expected a JSON array (roster.json format)')
    except Exception as e:
        return jsonify({'error': f'Invalid file: {e}'}), 400

    conn = get_db()
    by_id, _, _ = _build_player_lookups(conn)

    rating_changes, no_change, not_found = [], 0, 0
    pending_updates = []

    for p in data:
        rid = str(p.get('rosterId', p.get('id', '')))
        if not rid:
            continue

        db_p = by_id.get(rid)
        if db_p is None:
            not_found += 1
            continue

        new_ovr = p.get('playerBestOvr')
        new_age = p.get('age')
        new_pos = p.get('position', db_p['position'])

        changed = (
            (new_ovr is not None and new_ovr != db_p.get('overall_rating')) or
            (new_age is not None and new_age != db_p.get('age')) or
            (new_pos and new_pos != db_p['position'])
        )

        if changed:
            fn = db_p['first_name']; ln = db_p['last_name']
            rating_changes.append({
                'name':    fn + ' ' + ln,
                'position': db_p['position'],
                'old_ovr': db_p.get('overall_rating'), 'new_ovr': new_ovr,
                'old_age': db_p.get('age'),            'new_age': new_age,
            })
            pending_updates.append((new_ovr, new_age, new_pos, db_p['id']))
        else:
            no_change += 1

    if not dry_run:
        for new_ovr, new_age, new_pos, db_id in pending_updates:
            conn.execute(
                'UPDATE players SET overall_rating = ?, age = ?, position = ? WHERE id = ?',
                (new_ovr, new_age, new_pos, db_id)
            )
        conn.commit()
        log_audit(request.current_user['id'], 'madden_ratings_import', 'player', None, None,
                  {'updated': len(rating_changes), 'not_found': not_found})

    conn.close()
    return jsonify({
        'dry_run':              dry_run,
        'rating_changes':       rating_changes,
        'rating_changes_count': len(rating_changes),
        'no_change_count':      no_change,
        'not_found_count':      not_found,
    })


# ── Madden ID Migration (one-time) ────────────────────────────────────────

@app.route('/api/admin/apply-madden-ids', methods=['POST'])
@require_role('assistant_commissioner')
def apply_madden_ids():
    """
    One-time migration: applies pre-computed madden_id / madden_team_id mappings
    from migration_madden_ids.py to the production database.
    Safe to run multiple times (idempotent).
    """
    try:
        import importlib.util, os
        migration_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migration_madden_ids.py')
        spec = importlib.util.spec_from_file_location('migration_madden_ids', migration_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        PLAYER_MADDEN_IDS = mod.PLAYER_MADDEN_IDS
        TEAM_MADDEN_IDS   = mod.TEAM_MADDEN_IDS
        PLAYER_RATINGS    = getattr(mod, 'PLAYER_RATINGS', {})
    except Exception as e:
        return jsonify({'error': f'Failed to load migration file: {e}'}), 500

    try:
        conn = get_db()
        players_updated = 0
        teams_updated = 0
        ratings_updated = 0

        for db_id, madden_id in PLAYER_MADDEN_IDS.items():
            conn.execute('UPDATE players SET madden_id = ? WHERE id = ?', (madden_id, db_id))
            players_updated += 1

        for nml_tid, madden_tid in TEAM_MADDEN_IDS.items():
            conn.execute('UPDATE teams SET madden_team_id = ? WHERE id = ?', (madden_tid, nml_tid))
            teams_updated += 1

        for db_id, r in PLAYER_RATINGS.items():
            conn.execute('''
                UPDATE players SET
                    overall_rating=:overall_rating,
                    speed=:speed, acceleration=:acceleration, agility=:agility, cod=:cod,
                    strength=:strength, awareness=:awareness, stamina=:stamina,
                    injury=:injury, toughness=:toughness, jump=:jump,
                    carry=:carry, break_tackle=:break_tackle, juke=:juke, spin=:spin,
                    truck=:truck, stiff_arm=:stiff_arm, bcv=:bcv,
                    catch=:catch, cit=:cit, spec_catch=:spec_catch,
                    route_short=:route_short, route_med=:route_med, route_deep=:route_deep,
                    release=:release,
                    throw_power=:throw_power, throw_acc=:throw_acc,
                    throw_acc_short=:throw_acc_short, throw_acc_mid=:throw_acc_mid,
                    throw_acc_deep=:throw_acc_deep, throw_on_run=:throw_on_run,
                    throw_under_pressure=:throw_under_pressure, play_action=:play_action,
                    pass_block=:pass_block, pass_block_power=:pass_block_power,
                    pass_block_finesse=:pass_block_finesse, run_block=:run_block,
                    run_block_power=:run_block_power, run_block_finesse=:run_block_finesse,
                    impact_block=:impact_block, lead_block=:lead_block, long_snap=:long_snap,
                    kick_power=:kick_power, kick_acc=:kick_acc, kick_return=:kick_return,
                    tackle=:tackle, hit_power=:hit_power, pursuit=:pursuit,
                    block_shed=:block_shed, power_moves=:power_moves, finesse_moves=:finesse_moves,
                    break_sack=:break_sack, man_cover=:man_cover, zone_cover=:zone_cover,
                    press=:press, play_rec=:play_rec, confidence=:confidence,
                    contract_salary=:contract_salary, contract_bonus=:contract_bonus,
                    contract_length=:contract_length, contract_years_left=:contract_years_left,
                    cap_hit=:cap_hit, cap_release_savings=:cap_release_savings,
                    cap_release_penalty=:cap_release_penalty,
                    draft_round=:draft_round, draft_pick=:draft_pick,
                    rookie_year=:rookie_year, years_pro=:years_pro,
                    college=:college, height=:height, weight=:weight,
                    jersey_num=:jersey_num, dev_trait=:dev_trait
                WHERE id=:db_id
            ''', {**r, 'db_id': db_id})
            ratings_updated += 1

        conn.commit()
        conn.close()
    except Exception as e:
        return jsonify({'error': f'Database update failed: {e}'}), 500

    try:
        log_audit(request.current_user['id'], 'apply_madden_ids_migration', 'player', None, None,
                  {'players_updated': players_updated, 'teams_updated': teams_updated,
                   'ratings_updated': ratings_updated})
    except Exception:
        pass  # don't fail on audit logging

    return jsonify({
        'success': True,
        'players_updated': players_updated,
        'teams_updated': teams_updated,
        'ratings_updated': ratings_updated,
    })


# ── Teams ──────────────────────────────────────────────────────────────────

@app.route('/api/teams', methods=['GET'])
def get_teams():
    conn = get_db()
    teams = conn.execute('''
        SELECT t.*,
            (SELECT COUNT(*) FROM players WHERE nml_team_id = t.id AND is_free_agent = 0) as roster_count
        FROM teams t ORDER BY t.short_name
    ''').fetchall()
    conn.close()
    return jsonify(rows_to_list(teams))

@app.route('/api/teams/<int:team_id>', methods=['GET'])
def get_team(team_id):
    conn = get_db()
    team = conn.execute('SELECT * FROM teams WHERE id = ?', (team_id,)).fetchone()
    if not team:
        return jsonify({'error': 'Team not found'}), 404

    players = conn.execute('''
        SELECT p.*,
               (SELECT ability_type FROM player_abilities
                WHERE player_id = p.id
                ORDER BY CASE ability_type WHEN 'xfactor' THEN 0 ELSE 1 END
                LIMIT 1) as top_ability_type,
               ndr.overall_pick as nml_draft_overall
        FROM players p
        LEFT JOIN nml_draft_results ndr ON ndr.player_id = p.id
        WHERE p.nml_team_id = ? AND p.is_free_agent = 0
        ORDER BY p.position, p.first_name
    ''', (team_id,)).fetchall()

    # Exclude picks that have already been used in the draft (NOT EXISTS against draft_selections).
    # Once a pick is used, it should disappear from roster, tradeblock, and any ownership view.
    picks_2026 = conn.execute('''
        SELECT dp.*, t.abbreviation as orig_abbrev, t.short_name as orig_name
        FROM draft_picks dp
        JOIN teams t ON t.id = dp.original_owner_id
        WHERE dp.current_owner_id = ? AND dp.year = 2026
          AND NOT EXISTS (SELECT 1 FROM draft_selections ds WHERE ds.draft_pick_id = dp.id)
        ORDER BY dp.round, dp.round_order
    ''', (team_id,)).fetchall()

    picks_2027 = conn.execute('''
        SELECT dp.*, t.abbreviation as orig_abbrev, t.short_name as orig_name
        FROM draft_picks dp
        JOIN teams t ON t.id = dp.original_owner_id
        WHERE dp.current_owner_id = ? AND dp.year = 2027
          AND NOT EXISTS (SELECT 1 FROM draft_selections ds WHERE ds.draft_pick_id = dp.id)
        ORDER BY dp.round
    ''', (team_id,)).fetchall()

    recent_transactions = conn.execute('''
        SELECT * FROM transactions WHERE team_id = ?
        ORDER BY created_at DESC LIMIT 20
    ''', (team_id,)).fetchall()

    # Only show pending trades to the involved teams and commissioners
    _viewer = get_current_user()
    _can_see_pending = (
        _viewer is not None and (
            _viewer['role'] in ('creator', 'commissioner', 'assistant_commissioner') or
            _viewer.get('team_id') == team_id
        )
    )
    if _can_see_pending:
        pending_trades = conn.execute('''
            SELECT tr.id, tr.status, tr.team1_id, tr.team2_id,
                   t1.short_name as team1_name, t2.short_name as team2_name
            FROM trades tr
            JOIN teams t1 ON t1.id = tr.team1_id
            JOIN teams t2 ON t2.id = tr.team2_id
            WHERE (tr.team1_id = ? OR tr.team2_id = ?)
              AND tr.status IN ('pending_team2', 'pending_team1_confirm')
            ORDER BY tr.proposed_at DESC
        ''', (team_id, team_id)).fetchall()
    else:
        pending_trades = []

    conn.close()
    return jsonify({
        'team': row_to_dict(team),
        'players': rows_to_list(players),
        'picks_2026': rows_to_list(picks_2026),
        'picks_2027': rows_to_list(picks_2027),
        'recent_transactions': rows_to_list(recent_transactions),
        'pending_trades': rows_to_list(pending_trades),
    })

@app.route('/api/teams/<int:team_id>', methods=['PATCH'])
def update_team(team_id):
    data = request.json
    allowed = ['owner_name', 'discord_username', 'discord_tag', 'discord_user_id', 'tradeblock_note']
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'No valid fields'}), 400

    conn = get_db()
    old = row_to_dict(conn.execute('SELECT * FROM teams WHERE id = ?', (team_id,)).fetchone())
    sets = ', '.join(f'{k} = ?' for k in updates)
    conn.execute(f'UPDATE teams SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                 list(updates.values()) + [team_id])
    conn.commit()
    new = row_to_dict(conn.execute('SELECT * FROM teams WHERE id = ?', (team_id,)).fetchone())
    conn.close()
    log_audit(None, 'update_team', 'team', team_id, old, new)
    return jsonify(new)

# ── Team Needs ─────────────────────────────────────────────────────────────

# Canonical position order (QB through LS)
POSITION_ORDER = [
    'QB', 'HB', 'FB', 'WR', 'TE',
    'LT', 'LG', 'C', 'RG', 'RT', 'OT',
    'LEDGE', 'REDGE', 'DT',
    'MIKE', 'SAM', 'WILL',
    'CB', 'SS', 'FS',
    'K', 'P', 'LS'
]


def get_active_pick_years():
    """Return (current_year, future_year) based on draft progress and league calendar."""
    import datetime
    conn = get_db()
    # Get all years that have picks in DB
    years = [r['year'] for r in conn.execute(
        'SELECT DISTINCT year FROM draft_picks ORDER BY year'
    ).fetchall()]
    conn.close()
    if not years:
        now = datetime.datetime.now()
        return now.year, now.year + 1
    current_year = years[0]
    future_year = years[1] if len(years) > 1 else current_year + 1
    return current_year, future_year


def is_current_year_draft_complete(year):
    """True if all picks for the given year have been selected."""
    conn = get_db()
    total = conn.execute(
        'SELECT COUNT(*) as c FROM draft_picks WHERE year = ?', (year,)
    ).fetchone()['c']
    made = conn.execute('''
        SELECT COUNT(*) as c FROM draft_selections ds
        JOIN draft_picks dp ON ds.draft_pick_id = dp.id
        WHERE dp.year = ?
    ''', (year,)).fetchone()['c']
    conn.close()
    return total > 0 and made >= total


@app.route('/api/teams/<int:team_id>/needs', methods=['GET'])
def get_team_needs(team_id):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM team_needs WHERE team_id = ? ORDER BY tier, tier_order',
        (team_id,)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/teams/<int:team_id>/needs', methods=['POST'])
@require_auth
def save_team_needs(team_id):
    user = request.current_user
    # Only the team owner or admin can edit
    if not can_manage_team(user, team_id) and not is_admin(user):
        return jsonify({'error': 'Not authorized'}), 403

    data = request.json or {}
    needs = data.get('needs', [])

    conn = get_db()
    # Replace all needs for this team
    conn.execute('DELETE FROM team_needs WHERE team_id = ?', (team_id,))
    for item in needs:
        item_type = item.get('item_type')
        item_key = item.get('item_key')
        tier = item.get('tier')
        tier_order = item.get('tier_order', 0)
        if item_type not in ('position', 'pick') or not item_key or tier not in ('high', 'medium', 'low'):
            continue
        conn.execute(
            '''INSERT INTO team_needs (team_id, item_type, item_key, tier, tier_order)
               VALUES (?, ?, ?, ?, ?)''',
            (team_id, item_type, item_key, tier, tier_order)
        )
    conn.commit()
    rows = conn.execute(
        'SELECT * FROM team_needs WHERE team_id = ? ORDER BY tier, tier_order',
        (team_id,)
    ).fetchall()
    conn.close()
    try:
        from discord_bot import post_tradeblock_to_discord
        post_tradeblock_to_discord(team_id)
    except Exception:
        pass
    return jsonify(rows_to_list(rows))


@app.route('/api/needs-config', methods=['GET'])
def get_needs_config():
    """Return the list of available positions and pick slots for the needs board."""
    conn = get_db()
    # Get positions that exist in the players table
    db_positions = set(
        r['position'] for r in conn.execute(
            'SELECT DISTINCT position FROM players WHERE position IS NOT NULL'
        ).fetchall()
    )
    conn.close()

    positions = [p for p in POSITION_ORDER if p in db_positions]

    current_year, future_year = get_active_pick_years()
    draft_complete = is_current_year_draft_complete(current_year)

    pick_slots = []
    if not draft_complete:
        for r in range(1, 8):
            pick_slots.append({'key': f'{current_year}_{r}', 'label': f'{current_year} {_ordinal(r)}', 'year': current_year, 'round': r, 'is_current': True})
    for r in range(1, 8):
        pick_slots.append({'key': f'{future_year}_{r}', 'label': f'{future_year} {_ordinal(r)}', 'year': future_year, 'round': r, 'is_current': False})

    return jsonify({'positions': positions, 'picks': pick_slots, 'current_year': current_year, 'future_year': future_year})


def _ordinal(n):
    suffix = 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f'{n}{suffix}'


# ── Players ────────────────────────────────────────────────────────────────

@app.route('/api/players', methods=['GET'])
def get_players():
    team_id = request.args.get('team_id')
    fa_only = request.args.get('fa') == 'true'
    draft_pool = request.args.get('draft_pool') == 'true'
    all_nml = request.args.get('all_nml') == 'true'
    position = request.args.get('position')
    search = request.args.get('search')

    # Cache the all_nml unfiltered list — most expensive and most frequently requested
    if all_nml and not position and not search:
        cached = _cache_get('players_all_nml')
        if cached is not None:
            return jsonify(cached)

    conn = get_db()
    query = '''SELECT p.*, t.short_name as nml_team_name, t.abbreviation as nml_team_abbrev,
               (SELECT ability_type FROM player_abilities
                WHERE player_id = p.id
                ORDER BY CASE ability_type WHEN 'xfactor' THEN 0 ELSE 1 END
                LIMIT 1) as top_ability_type
               FROM players p LEFT JOIN teams t ON t.id = p.nml_team_id WHERE 1=1'''
    params = []

    if draft_pool:
        # Rookie prospects + free agents, all unassigned (nml_team_id IS NULL)
        query += ' AND (p.is_rookie_prospect = 1 OR p.is_free_agent = 1) AND p.nml_team_id IS NULL'
    elif all_nml:
        # All players on NML teams + free agents (excludes undrafted rookie prospects)
        query += (' AND ((p.nml_team_id IS NOT NULL AND p.is_free_agent = 0)'
                  ' OR (p.is_free_agent = 1 AND (p.is_rookie_prospect = 0 OR p.is_rookie_prospect IS NULL)))')
    elif fa_only:
        query += ' AND p.is_free_agent = 1 AND (p.is_rookie_prospect = 0 OR p.is_rookie_prospect IS NULL)'
    elif team_id:
        query += ' AND p.nml_team_id = ? AND p.is_free_agent = 0'
        params.append(team_id)

    if position:
        query += ' AND p.position = ?'
        params.append(position)

    if search:
        query += ' AND (p.first_name LIKE ? OR p.last_name LIKE ?)'
        params += [f'%{search}%', f'%{search}%']

    query += ' ORDER BY p.first_name, p.last_name'
    players = conn.execute(query, params).fetchall()
    conn.close()
    result = [compute_age(dict(p)) for p in players]
    if all_nml and not position and not search:
        _cache_set('players_all_nml', result)
    return jsonify(result)

@app.route('/api/players/<int:player_id>', methods=['GET'])
def get_player(player_id):
    conn = get_db()
    player = conn.execute('''
        SELECT p.*, t.short_name as nml_team_name, t.full_name as nml_team_full_name,
               ndr.season_year as nml_draft_year, ndr.round as nml_draft_round,
               ndr.pick_in_round as nml_draft_pick, ndr.overall_pick as nml_draft_overall
        FROM players p
        LEFT JOIN teams t ON t.id = p.nml_team_id
        LEFT JOIN nml_draft_results ndr ON ndr.player_id = p.id
        WHERE p.id = ?
    ''', (player_id,)).fetchone()
    if not player:
        conn.close()
        return jsonify({'error': 'Player not found'}), 404
    result = compute_age(row_to_dict(player))
    # Attach abilities
    abilities = conn.execute(
        'SELECT ability_name, ability_type, description FROM player_abilities WHERE player_id = ? ORDER BY ability_type DESC, ability_name',
        (player_id,)
    ).fetchall()
    result['abilities'] = [row_to_dict(a) for a in abilities]
    conn.close()
    return jsonify(result)

# ── Watchlist ──────────────────────────────────────────────────────────────────

@app.route('/api/watchlist', methods=['GET'])
@require_auth
def get_watchlist():
    user = get_current_user()
    conn = get_db()
    rows = conn.execute('''
        SELECT p.id, p.first_name, p.last_name, p.position, p.overall_rating,
               p.projected_ovr,
               p.birth_date, p.nml_team_id, t.short_name as team_short_name,
               w.added_at
        FROM watchlist w
        JOIN players p ON p.id = w.player_id
        LEFT JOIN teams t ON t.id = p.nml_team_id
        WHERE w.user_id = ?
        ORDER BY p.position, COALESCE(p.overall_rating, p.projected_ovr) DESC
    ''', (user['id'],)).fetchall()
    conn.close()
    result = [compute_age(dict(r)) for r in rows]
    return jsonify(result)

@app.route('/api/watchlist/<int:player_id>', methods=['POST'])
@require_auth
def add_to_watchlist(player_id):
    user = get_current_user()
    conn = get_db()
    try:
        conn.execute('INSERT OR IGNORE INTO watchlist (user_id, player_id) VALUES (?, ?)',
                     (user['id'], player_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})

@app.route('/api/watchlist/<int:player_id>', methods=['DELETE'])
@require_auth
def remove_from_watchlist(player_id):
    user = get_current_user()
    conn = get_db()
    conn.execute('DELETE FROM watchlist WHERE user_id=? AND player_id=?',
                 (user['id'], player_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ── Schedule ──────────────────────────────────────────────────────────────────

@app.route('/api/seasons', methods=['GET'])
@require_auth
def get_seasons():
    conn = get_db()
    rows = conn.execute('SELECT * FROM seasons ORDER BY year DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/seasons', methods=['POST'])
@require_role('commissioner')
def create_season():
    data = request.get_json()
    year = data.get('year')
    name = data.get('name', f"{year} NML Season")
    conn = get_db()
    if data.get('is_current'):
        conn.execute('UPDATE seasons SET is_current=0')
    conn.execute('INSERT INTO seasons (year, name, is_current) VALUES (?, ?, ?)',
                 (year, name, 1 if data.get('is_current') else 0))
    conn.commit()
    season_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'id': season_id, 'ok': True})

@app.route('/api/seasons/<int:season_id>/weeks', methods=['GET'])
@require_auth
def get_season_weeks(season_id):
    conn = get_db()
    weeks = conn.execute('SELECT * FROM schedule_weeks WHERE season_id=? ORDER BY week_num', (season_id,)).fetchall()
    conn.close()
    return jsonify([dict(w) for w in weeks])

@app.route('/api/seasons/<int:season_id>/weeks', methods=['POST'])
@require_role('commissioner')
def create_week(season_id):
    data = request.get_json()
    conn = get_db()
    conn.execute('INSERT OR IGNORE INTO schedule_weeks (season_id, week_num, nfl_week_label, advance_date) VALUES (?,?,?,?)',
                 (season_id, data['week_num'], data.get('nfl_week_label'), data.get('advance_date')))
    conn.commit()
    week_id = conn.execute('SELECT id FROM schedule_weeks WHERE season_id=? AND week_num=?', (season_id, data['week_num'])).fetchone()[0]
    conn.close()
    return jsonify({'id': week_id, 'ok': True})

@app.route('/api/weeks/<int:week_id>/games', methods=['GET'])
@require_auth
def get_week_games(week_id):
    conn = get_db()
    games = conn.execute('''
        SELECT g.*,
               ht.short_name as home_short, ht.full_name as home_full,
               at.short_name as away_short, at.full_name as away_full,
               gs.planned_datetime, gs.stream_url, gs.notes,
               gs.posted_by_user_id,
               hu.display_name as home_owner, au.display_name as away_owner,
               hteam.discord_user_id as home_discord_id,
               ateam.discord_user_id as away_discord_id
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        LEFT JOIN game_scheduling gs ON gs.game_id = g.id
        LEFT JOIN users hu ON hu.discord_user_id = hteam.discord_user_id
        LEFT JOIN users au ON au.discord_user_id = ateam.discord_user_id
        LEFT JOIN teams hteam ON hteam.id = g.home_team_id
        LEFT JOIN teams ateam ON ateam.id = g.away_team_id
        WHERE g.week_id = ?
        ORDER BY g.id
    ''', (week_id,)).fetchall()
    conn.close()
    return jsonify([dict(g) for g in games])

@app.route('/api/weeks/<int:week_id>/games', methods=['POST'])
@require_role('commissioner')
def create_game(week_id):
    data = request.get_json()
    conn = get_db()
    conn.execute('INSERT INTO games (week_id, home_team_id, away_team_id) VALUES (?,?,?)',
                 (week_id, data['home_team_id'], data['away_team_id']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/games/<int:game_id>/schedule', methods=['POST', 'PUT'])
@require_auth
def set_game_schedule(game_id):
    user = get_current_user()
    data = request.get_json()
    conn = get_db()
    # Verify the user owns one of the teams in this game
    game = conn.execute('SELECT home_team_id, away_team_id FROM games WHERE id=?', (game_id,)).fetchone()
    if not game:
        conn.close()
        return jsonify({'error': 'Game not found'}), 404
    is_admin_user = is_admin(user)
    if not is_admin_user and user.get('team_id') not in (game['home_team_id'], game['away_team_id']):
        conn.close()
        return jsonify({'error': 'Not your game'}), 403
    conn.execute('''
        INSERT INTO game_scheduling (game_id, planned_datetime, stream_url, notes, posted_by_user_id, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(game_id) DO UPDATE SET
            planned_datetime=excluded.planned_datetime,
            stream_url=excluded.stream_url,
            notes=excluded.notes,
            posted_by_user_id=excluded.posted_by_user_id,
            updated_at=datetime('now')
    ''', (game_id, data.get('planned_datetime'), data.get('stream_url'), data.get('notes'), user['id']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/games/<int:game_id>/schedule', methods=['DELETE'])
@require_auth
def clear_game_schedule(game_id):
    user = get_current_user()
    conn = get_db()
    game = conn.execute('SELECT home_team_id, away_team_id FROM games WHERE id=?', (game_id,)).fetchone()
    if not game:
        conn.close()
        return jsonify({'error': 'Game not found'}), 404
    if not is_admin(user) and user.get('team_id') not in (game['home_team_id'], game['away_team_id']):
        conn.close()
        return jsonify({'error': 'Not your game'}), 403
    conn.execute('DELETE FROM game_scheduling WHERE game_id=?', (game_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/users/<int:user_id>/twitch', methods=['PATCH'])
@require_auth
def update_twitch_url(user_id):
    current = get_current_user()
    if current['id'] != user_id and not is_admin(current):
        return jsonify({'error': 'Forbidden'}), 403
    data = request.get_json()
    conn = get_db()
    conn.execute('UPDATE users SET twitch_url=? WHERE id=?', (data.get('twitch_url', ''), user_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ── Depth Chart ───────────────────────────────────────────────────────────────

@app.route('/api/depth-chart', methods=['GET'])
@require_auth
def get_depth_chart():
    user = get_current_user()
    conn = get_db()
    rows = conn.execute(
        'SELECT side, formation, slot, depth, player_id FROM depth_chart WHERE user_id = ?',
        (user['id'],)
    ).fetchall()
    defaults = conn.execute(
        'SELECT default_defense, default_offense FROM depth_chart_defaults WHERE user_id = ?',
        (user['id'],)
    ).fetchone()
    # Gather player info for assigned players
    pids = list({r['player_id'] for r in rows if r['player_id']})
    players = {}
    if pids:
        ph = ','.join('?' * len(pids))
        for p in conn.execute(f'SELECT id, first_name, last_name, position, overall_rating, birth_date, age FROM players WHERE id IN ({ph})', pids).fetchall():
            pd = compute_age(row_to_dict(p))
            players[p['id']] = pd
    conn.close()
    assignments = [{'side': r['side'], 'formation': r['formation'], 'slot': r['slot'],
                    'depth': r['depth'], 'player_id': r['player_id'],
                    'player': players.get(r['player_id'])} for r in rows]
    return jsonify({
        'assignments': assignments,
        'defaults': {'default_defense': defaults['default_defense'] if defaults else None,
                     'default_offense': defaults['default_offense'] if defaults else None}
    })

@app.route('/api/depth-chart/slot', methods=['PUT'])
@require_auth
def save_depth_chart_slot():
    user = get_current_user()
    data = request.get_json()
    side = data.get('side')
    formation = data.get('formation')
    slot = data.get('slot')
    depth = int(data.get('depth', 1))
    player_id = data.get('player_id')  # None = clear slot
    if not side or not formation or not slot:
        return jsonify({'error': 'side, formation, slot required'}), 400
    conn = get_db()
    if player_id is None:
        conn.execute(
            'DELETE FROM depth_chart WHERE user_id=? AND side=? AND formation=? AND slot=? AND depth=?',
            (user['id'], side, formation, slot, depth)
        )
    else:
        conn.execute(
            '''INSERT INTO depth_chart (user_id, side, formation, slot, depth, player_id, updated_at)
               VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id, side, formation, slot, depth)
               DO UPDATE SET player_id=excluded.player_id, updated_at=CURRENT_TIMESTAMP''',
            (user['id'], side, formation, slot, depth, player_id)
        )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/depth-chart/autofill', methods=['POST'])
@require_auth
def autofill_depth_chart():
    user = get_current_user()
    data = request.get_json()
    side = data.get('side')
    formation = data.get('formation')
    slots = data.get('slots', [])  # [{slot, player_id}]
    if not side or not formation or not slots:
        return jsonify({'error': 'side, formation, slots required'}), 400
    conn = get_db()
    try:
        for item in slots:
            slot = item.get('slot')
            player_id = item.get('player_id')
            if not slot or player_id is None:
                continue
            conn.execute(
                '''INSERT INTO depth_chart (user_id, side, formation, slot, depth, player_id, updated_at)
                   VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id, side, formation, slot, depth)
                   DO UPDATE SET player_id=excluded.player_id, updated_at=CURRENT_TIMESTAMP''',
                (user['id'], side, formation, slot, 1, player_id)
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 500
    conn.close()
    return jsonify({'success': True, 'count': len(slots)})

@app.route('/api/depth-chart/defaults', methods=['PUT'])
@require_auth
def save_depth_chart_defaults():
    user = get_current_user()
    data = request.get_json()
    conn = get_db()
    conn.execute(
        '''INSERT INTO depth_chart_defaults (user_id, default_defense, default_offense, updated_at)
           VALUES (?,?,?, CURRENT_TIMESTAMP)
           ON CONFLICT(user_id) DO UPDATE SET
             default_defense=excluded.default_defense,
             default_offense=excluded.default_offense,
             updated_at=CURRENT_TIMESTAMP''',
        (user['id'], data.get('default_defense'), data.get('default_offense'))
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/depth-chart/eligibility', methods=['GET'])
@require_auth
def get_dc_eligibility():
    conn = get_db()
    rows = conn.execute('SELECT formation, slot, allowed_positions FROM dc_slot_eligibility').fetchall()
    conn.close()
    result = {}
    for r in rows:
        f = r['formation']
        if f not in result:
            result[f] = {}
        result[f][r['slot']] = json.loads(r['allowed_positions'])
    return jsonify(result)

@app.route('/api/depth-chart/eligibility', methods=['PUT'])
@require_role('assistant_commissioner')
def save_dc_eligibility():
    data = request.get_json()
    formation = data.get('formation')
    rules = data.get('rules', {})
    if not formation:
        return jsonify({'error': 'formation required'}), 400
    conn = get_db()
    for slot, positions in rules.items():
        conn.execute(
            '''INSERT INTO dc_slot_eligibility (formation, slot, allowed_positions)
               VALUES (?,?,?)
               ON CONFLICT(formation, slot) DO UPDATE SET allowed_positions=excluded.allowed_positions''',
            (formation, slot, json.dumps(positions))
        )
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/players/<int:player_id>/trades', methods=['GET'])
@require_auth
def get_player_trades(player_id):
    """Return all trades this player was involved in, newest first."""
    conn = get_db()
    try:
        # Find trades where this player appears as an asset
        rows = conn.execute('''
            SELECT DISTINCT t.id, t.status, t.proposed_at, t.completed_at,
                   tf.short_name AS player_from, tt.short_name AS player_to
            FROM trade_assets ta
            JOIN trades t ON ta.trade_id = t.id
            JOIN teams tf ON ta.from_team_id = tf.id
            JOIN teams tt ON ta.to_team_id = tt.id
            WHERE ta.player_id = ? AND ta.asset_type = 'player'
            ORDER BY COALESCE(t.completed_at, t.proposed_at) DESC
        ''', (player_id,)).fetchall()

        result = []
        for row in rows:
            # Fetch all assets for this trade to show what else was in the deal
            assets = conn.execute('''
                SELECT ta.asset_type, ta.player_id, ta.pick_id,
                       ta.from_team_id, ta.to_team_id,
                       p.first_name, p.last_name, p.position,
                       dp.year, dp.round,
                       tf.short_name AS from_name,
                       tt.short_name AS to_name,
                       orig.short_name AS orig_team
                FROM trade_assets ta
                LEFT JOIN players p ON ta.player_id = p.id
                LEFT JOIN draft_picks dp ON ta.pick_id = dp.id
                LEFT JOIN teams tf ON ta.from_team_id = tf.id
                LEFT JOIN teams tt ON ta.to_team_id = tt.id
                LEFT JOIN teams orig ON dp.original_owner_id = orig.id
                WHERE ta.trade_id = ?
            ''', (row['id'],)).fetchall()

            def ordinal(n):
                return {1:'1st',2:'2nd',3:'3rd',4:'4th',5:'5th',6:'6th',7:'7th'}.get(n, f'{n}th')

            asset_list = []
            for a in assets:
                if a['asset_type'] == 'player' and a['player_id']:
                    label = f"{a['first_name']} {a['last_name']} ({a['position']})"
                elif a['asset_type'] == 'pick' and a['pick_id']:
                    label = f"{a['year']} {ordinal(a['round'])} ({a['orig_team']})"
                else:
                    continue
                asset_list.append({
                    'label': label,
                    'from_team': a['from_name'],
                    'to_team': a['to_name'],
                    'is_player': a['asset_type'] == 'player',
                    'player_id': a['player_id']
                })

            result.append({
                'trade_id': row['id'],
                'status': row['status'],
                'date': row['completed_at'] or row['proposed_at'],
                'player_from': row['player_from'],
                'player_to': row['player_to'],
                'assets': asset_list
            })

        return jsonify(result)
    finally:
        conn.close()

@app.route('/api/players/<int:player_id>/ratings-history', methods=['GET'])
@require_auth
def get_player_ratings_history(player_id):
    """Return all ratings history snapshots for a player, ordered by snapshot_date ascending."""
    conn = get_db()
    try:
        rows = conn.execute('''
            SELECT snapshot_label, snapshot_date, overall_rating,
                   speed, strength, awareness, throw_power, throw_acc,
                   catch, route_short, tackle, block_shed, pass_block,
                   man_cover, zone_cover
            FROM player_ratings_history
            WHERE player_id = ?
            ORDER BY snapshot_date ASC
        ''', (player_id,)).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/players/<int:player_id>', methods=['PATCH'])
@require_role('assistant_commissioner')
def update_player(player_id):
    user = request.current_user
    data = request.json
    allowed = ['first_name', 'last_name', 'position', 'age', 'overall_rating',
               'nfl_team', 'nml_team_id', 'is_free_agent', 'madden_id', 'birth_date']
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'No valid fields'}), 400

    conn = get_db()
    old = row_to_dict(conn.execute('SELECT * FROM players WHERE id = ?', (player_id,)).fetchone())

    # Track field-level history
    for field, new_val in updates.items():
        old_val = old.get(field)
        if str(old_val) != str(new_val):
            conn.execute('''INSERT INTO player_field_history (player_id, field_name, old_value, new_value)
                VALUES (?, ?, ?, ?)''', (player_id, field, str(old_val), str(new_val)))

    sets = ', '.join(f'{k} = ?' for k in updates)
    conn.execute(f'UPDATE players SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                 list(updates.values()) + [player_id])
    if 'position' in updates:
        conn.execute('DELETE FROM depth_chart WHERE player_id = ?', (player_id,))
    conn.commit()
    new = compute_age(row_to_dict(conn.execute('SELECT * FROM players WHERE id = ?', (player_id,)).fetchone()))
    conn.close()
    log_audit(user['id'], 'update_player', 'player', player_id, old, new)
    return jsonify(new)

@app.route('/api/players', methods=['POST'])
@require_role('assistant_commissioner')
def create_player():
    data = request.json
    required = ['first_name', 'last_name', 'position']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'Missing required field: {field}'}), 400

    conn = get_db()
    # Duplicate check
    existing = conn.execute('''SELECT id FROM players WHERE first_name = ? AND last_name = ? AND position = ?''',
        (data['first_name'], data['last_name'], data['position'])).fetchone()
    if existing:
        conn.close()
        return jsonify({'error': 'Player already exists with same name and position', 'existing_id': existing['id']}), 409

    c = conn.execute('''INSERT INTO players
        (first_name, last_name, position, age, overall_rating, nfl_team, nml_team_id, madden_id, is_free_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (data['first_name'], data['last_name'], data['position'],
         data.get('age'), data.get('overall_rating'), data.get('nfl_team'),
         data.get('nml_team_id'), data.get('madden_id'),
         1 if not data.get('nml_team_id') else 0))
    conn.commit()
    player = compute_age(row_to_dict(conn.execute('SELECT * FROM players WHERE id = ?', (c.lastrowid,)).fetchone()))
    conn.close()
    return jsonify(player), 201

# Sign / Cut player
@app.route('/api/players/<int:player_id>/sign', methods=['POST'])
@require_auth
def sign_player(player_id):
    data = request.json
    team_id = data.get('team_id')
    force = data.get('force', False)
    if not team_id:
        return jsonify({'error': 'team_id required'}), 400

    # Offseason FA pickup block
    offseason_start = get_setting('offseason_start_date')
    season_start = get_setting('season_start_date')
    today = datetime.now().strftime('%Y-%m-%d')
    if offseason_start and season_start and offseason_start <= today < season_start:
        user = request.current_user
        user_is_admin = user and user['role'] in ('creator', 'commissioner', 'assistant_commissioner')
        if not user_is_admin:
            return jsonify({
                'error': 'FA pickups are disabled during the offseason.',
                'offseason_blocked': True
            }), 403
        if not force:
            return jsonify({
                'error': 'FA pickups are disabled during the offseason. Use admin override to proceed.',
                'offseason_blocked': True,
                'admin_override_available': True
            }), 403

    conn = get_db()
    player = conn.execute('SELECT * FROM players WHERE id = ?', (player_id,)).fetchone()
    team = conn.execute('SELECT * FROM teams WHERE id = ?', (team_id,)).fetchone()
    if not player or not team:
        return jsonify({'error': 'Player or team not found'}), 404
    if not player['is_free_agent']:
        return jsonify({'error': 'Player is not a free agent'}), 400

    # Roster cap check
    cap = int(get_setting('roster_cap') or 53)
    season_end = get_setting('season_end_date')
    in_season = season_start and season_end and season_start <= today <= season_end

    if in_season:
        roster_count = conn.execute(
            'SELECT COUNT(*) as cnt FROM players WHERE nml_team_id = ? AND is_free_agent = 0',
            (team_id,)).fetchone()['cnt']
        if roster_count >= cap:
            conn.close()
            return jsonify({'error': f'Roster cap reached ({roster_count}/{cap})'}), 400

    conn.execute('UPDATE players SET nml_team_id = ?, is_free_agent = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                 (team_id, player_id))
    desc = f"{team['short_name']} signed {player['position']} {player['first_name']} {player['last_name']}"
    signer = request.current_user
    conn.execute('INSERT INTO transactions (type, player_id, team_id, description, created_by) VALUES (?, ?, ?, ?, ?)',
                 ('sign_player', player_id, team_id, desc, signer['id'] if signer else None))
    conn.commit()
    _cache_bust('players_')

    # Post to Discord transactions channel
    post_sign = conn.execute("SELECT value FROM league_settings WHERE key='post_signings_to_discord'").fetchone()
    tx_channel = conn.execute("SELECT value FROM league_settings WHERE key='discord_transactions_channel_id'").fetchone()
    if post_sign and post_sign['value'] == 'true' and tx_channel and tx_channel['value']:
        send_discord_message(tx_channel['value'], f"✍️ {desc}")

    conn.close()
    return jsonify({'success': True, 'message': desc})

@app.route('/api/players/<int:player_id>/cut', methods=['POST'])
def cut_player(player_id):
    conn = get_db()
    player = conn.execute('SELECT * FROM players WHERE id = ?', (player_id,)).fetchone()
    if not player:
        return jsonify({'error': 'Player not found'}), 404
    if player['is_free_agent']:
        return jsonify({'error': 'Player is already a free agent'}), 400

    team = conn.execute('SELECT * FROM teams WHERE id = ?', (player['nml_team_id'],)).fetchone()
    cutter = get_current_user()
    conn.execute('UPDATE players SET nml_team_id = NULL, is_free_agent = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                 (player_id,))
    conn.execute('DELETE FROM depth_chart WHERE player_id = ?', (player_id,))
    desc = f"{team['short_name']} cut {player['position']} {player['first_name']} {player['last_name']}"
    conn.execute('INSERT INTO transactions (type, player_id, team_id, description, created_by) VALUES (?, ?, ?, ?, ?)',
                 ('cut_player', player_id, team['id'], desc, cutter['id'] if cutter else None))
    conn.commit()
    _cache_bust('players_')

    # Post to Discord transactions channel
    post_cuts = conn.execute("SELECT value FROM league_settings WHERE key='post_cuts_to_discord'").fetchone()
    tx_channel = conn.execute("SELECT value FROM league_settings WHERE key='discord_transactions_channel_id'").fetchone()
    if post_cuts and post_cuts['value'] == 'true' and tx_channel and tx_channel['value']:
        send_discord_message(tx_channel['value'], f"✂️ {desc}")

    conn.close()
    return jsonify({'success': True, 'message': desc})

# ── Trade Block ───────────────────────────────────────────────────────────

@app.route('/api/trade-block', methods=['GET'])
def get_trade_block():
    """Return all players and picks currently on the trade block, with team info."""
    conn = get_db()
    players = rows_to_list(conn.execute('''
        SELECT p.*, t.short_name as nml_team_name, t.full_name as nml_team_full_name,
               (SELECT ability_type FROM player_abilities
                WHERE player_id = p.id
                ORDER BY CASE ability_type WHEN 'xfactor' THEN 0 ELSE 1 END
                LIMIT 1) as top_ability_type
        FROM players p
        JOIN teams t ON t.id = p.nml_team_id
        WHERE p.on_trade_block = 1 AND p.is_free_agent = 0
        ORDER BY t.full_name, p.position, p.first_name
    ''').fetchall())
    picks = rows_to_list(conn.execute('''
        SELECT dp.*,
               curr.short_name as nml_team_name, curr.full_name as nml_team_full_name,
               orig.abbreviation as orig_abbrev, orig.short_name as orig_name
        FROM draft_picks dp
        JOIN teams curr ON curr.id = dp.current_owner_id
        JOIN teams orig  ON orig.id  = dp.original_owner_id
        WHERE dp.on_trade_block = 1
          AND NOT EXISTS (SELECT 1 FROM draft_selections ds WHERE ds.draft_pick_id = dp.id)
        ORDER BY curr.full_name, dp.year, dp.round
    ''').fetchall())
    conn.close()
    return jsonify({'players': players, 'picks': picks})


@app.route('/api/players/<int:player_id>/trade-block', methods=['POST'])
def add_to_trade_block(player_id):
    """Put a player on the trade block. Only the team owner (or admin) can do this."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Login required'}), 401

    note = (request.json or {}).get('note', '')

    conn = get_db()
    player = conn.execute(
        'SELECT p.*, t.short_name as team_name FROM players p LEFT JOIN teams t ON t.id = p.nml_team_id WHERE p.id = ?',
        (player_id,)
    ).fetchone()

    if not player:
        conn.close()
        return jsonify({'error': 'Player not found'}), 404

    if player['is_free_agent'] or not player['nml_team_id']:
        conn.close()
        return jsonify({'error': 'Player must be on a roster to be placed on the trade block'}), 400

    # Only the team owner or admin can put their players on the block
    is_admin = ROLE_HIERARCHY.get(user.get('role', ''), 0) >= ROLE_HIERARCHY['assistant_commissioner']
    is_owner = user.get('team_id') == player['nml_team_id']
    if not is_admin and not is_owner:
        conn.close()
        return jsonify({'error': 'You can only manage your own team\'s trade block'}), 403

    conn.execute(
        'UPDATE players SET on_trade_block = 1, trade_block_note = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (note.strip() or None, player_id)
    )
    conn.commit()
    team_id_for_discord = player['nml_team_id']
    conn.close()
    try:
        from discord_bot import post_tradeblock_to_discord
        post_tradeblock_to_discord(team_id_for_discord)
    except Exception:
        pass
    return jsonify({'success': True})


@app.route('/api/players/<int:player_id>/trade-block', methods=['DELETE'])
def remove_from_trade_block(player_id):
    """Remove a player from the trade block."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Login required'}), 401

    conn = get_db()
    player = conn.execute('SELECT * FROM players WHERE id = ?', (player_id,)).fetchone()
    if not player:
        conn.close()
        return jsonify({'error': 'Player not found'}), 404

    is_admin = ROLE_HIERARCHY.get(user.get('role', ''), 0) >= ROLE_HIERARCHY['assistant_commissioner']
    is_owner = user.get('team_id') == player['nml_team_id']
    if not is_admin and not is_owner:
        conn.close()
        return jsonify({'error': 'Forbidden'}), 403

    conn.execute(
        'UPDATE players SET on_trade_block = 0, trade_block_note = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (player_id,)
    )
    conn.commit()
    team_id_for_discord = player['nml_team_id']
    conn.close()
    try:
        from discord_bot import post_tradeblock_to_discord
        post_tradeblock_to_discord(team_id_for_discord)
    except Exception:
        pass
    return jsonify({'success': True})


@app.route('/api/picks/<int:pick_id>/trade-block', methods=['POST'])
def add_pick_to_trade_block(pick_id):
    """Put a draft pick on the trade block. Only the current owner (or admin) can do this."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Login required'}), 401
    note = (request.json or {}).get('note', '')
    conn = get_db()
    pick = row_to_dict(conn.execute('SELECT * FROM draft_picks WHERE id = ?', (pick_id,)).fetchone())
    if not pick:
        conn.close()
        return jsonify({'error': 'Pick not found'}), 404
    is_admin = ROLE_HIERARCHY.get(user.get('role', ''), 0) >= ROLE_HIERARCHY['assistant_commissioner']
    is_owner = user.get('team_id') == pick['current_owner_id']
    if not is_admin and not is_owner:
        conn.close()
        return jsonify({'error': 'You can only manage your own picks'}), 403
    conn.execute(
        'UPDATE draft_picks SET on_trade_block = 1, trade_block_note = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (note.strip() or None, pick_id)
    )
    conn.commit()
    team_id_for_discord = pick['current_owner_id']
    conn.close()
    try:
        from discord_bot import post_tradeblock_to_discord
        post_tradeblock_to_discord(team_id_for_discord)
    except Exception:
        pass
    return jsonify({'success': True})


@app.route('/api/picks/<int:pick_id>/trade-block', methods=['DELETE'])
def remove_pick_from_trade_block(pick_id):
    """Remove a draft pick from the trade block."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Login required'}), 401
    conn = get_db()
    pick = row_to_dict(conn.execute('SELECT * FROM draft_picks WHERE id = ?', (pick_id,)).fetchone())
    if not pick:
        conn.close()
        return jsonify({'error': 'Pick not found'}), 404
    is_admin = ROLE_HIERARCHY.get(user.get('role', ''), 0) >= ROLE_HIERARCHY['assistant_commissioner']
    is_owner = user.get('team_id') == pick['current_owner_id']
    if not is_admin and not is_owner:
        conn.close()
        return jsonify({'error': 'Forbidden'}), 403
    conn.execute(
        'UPDATE draft_picks SET on_trade_block = 0, trade_block_note = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (pick_id,)
    )
    conn.commit()
    team_id_for_discord = pick['current_owner_id']
    conn.close()
    try:
        from discord_bot import post_tradeblock_to_discord
        post_tradeblock_to_discord(team_id_for_discord)
    except Exception:
        pass
    return jsonify({'success': True})


@app.route('/api/teams/<int:team_id>/needs', methods=['PUT'])
def update_team_needs(team_id):
    """Save a team's 'needs' blurb. Editable by the team owner or commissioners."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Login required'}), 401
    is_admin = ROLE_HIERARCHY.get(user.get('role', ''), 0) >= ROLE_HIERARCHY['assistant_commissioner']
    is_owner = user.get('team_id') == team_id
    if not is_admin and not is_owner:
        return jsonify({'error': 'Forbidden'}), 403
    text = ((request.json or {}).get('needs', '') or '').strip()[:500]
    conn = get_db()
    conn.execute(
        'UPDATE teams SET tradeblock_note = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
        (text or None, team_id)
    )
    conn.commit()
    conn.close()
    try:
        from discord_bot import post_tradeblock_to_discord
        post_tradeblock_to_discord(team_id)
    except Exception:
        pass
    return jsonify({'success': True})


# ── Draft Picks ────────────────────────────────────────────────────────────

@app.route('/api/picks', methods=['GET'])
def get_picks():
    conn = get_db()
    year = request.args.get('year')
    team_id = request.args.get('team_id')
    # By default, exclude picks that have already been used in the draft.
    # Pass ?include_used=true to get the full historical list (used by Pick
    # Tracker / admin views that want to show completed-pick state).
    include_used = request.args.get('include_used', 'false').lower() == 'true'

    query = '''SELECT dp.*,
        orig.short_name as orig_team_name, orig.abbreviation as orig_abbrev,
        curr.short_name as curr_team_name, curr.abbreviation as curr_abbrev
        FROM draft_picks dp
        JOIN teams orig ON orig.id = dp.original_owner_id
        JOIN teams curr ON curr.id = dp.current_owner_id
        WHERE 1=1'''
    params = []
    if year:
        query += ' AND dp.year = ?'
        params.append(year)
    if team_id:
        query += ' AND dp.current_owner_id = ?'
        params.append(team_id)
    if not include_used:
        query += ' AND NOT EXISTS (SELECT 1 FROM draft_selections ds WHERE ds.draft_pick_id = dp.id)'
    query += ' ORDER BY dp.year, dp.round, dp.round_order, dp.overall_order'

    picks = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify(rows_to_list(picks))

@app.route('/api/picks/<int:pick_id>', methods=['PATCH'])
def update_pick(pick_id):
    user = get_current_user()
    if not user or ROLE_HIERARCHY.get(user.get('role', ''), 0) < ROLE_HIERARCHY['assistant_commissioner']:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.json
    allowed = ['round_order', 'overall_order', 'is_tradeable']
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'error': 'No valid fields'}), 400

    conn = get_db()
    old = row_to_dict(conn.execute('SELECT * FROM draft_picks WHERE id = ?', (pick_id,)).fetchone())
    sets = ', '.join(f'{k} = ?' for k in updates)
    conn.execute(f'UPDATE draft_picks SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                 list(updates.values()) + [pick_id])
    conn.commit()
    new = row_to_dict(conn.execute('SELECT * FROM draft_picks WHERE id = ?', (pick_id,)).fetchone())
    conn.close()
    log_audit(user['id'], 'update_pick', 'pick', pick_id, old, new)
    return jsonify(new)

@app.route('/api/picks/<int:pick_id>', methods=['DELETE'])
def delete_pick(pick_id):
    user = get_current_user()
    if not user or ROLE_HIERARCHY.get(user.get('role', ''), 0) < ROLE_HIERARCHY['assistant_commissioner']:
        return jsonify({'error': 'Admin access required'}), 403

    conn = get_db()
    pick = row_to_dict(conn.execute('SELECT * FROM draft_picks WHERE id = ?', (pick_id,)).fetchone())
    if not pick:
        conn.close()
        return jsonify({'error': 'Pick not found'}), 404
    if not pick.get('is_comp_pick'):
        conn.close()
        return jsonify({'error': 'Only comp picks can be deleted'}), 400

    team = conn.execute('SELECT short_name FROM teams WHERE id = ?', (pick.get('current_owner_id'),)).fetchone()
    team_name = team['short_name'] if team else 'Unknown'
    orig = conn.execute('SELECT abbreviation FROM teams WHERE id = ?', (pick.get('original_owner_id'),)).fetchone()
    orig_abbrev = orig['abbreviation'] if orig else '?'
    desc = (f"Comp pick deleted from {team_name}: "
            f"{pick['year']} Round {pick['round']} "
            f"(Pick {pick.get('round_order','?')}, Overall {pick.get('overall_order','?')}, Orig: {orig_abbrev})")
    conn.execute('DELETE FROM draft_picks WHERE id = ?', (pick_id,))
    conn.execute('INSERT INTO transactions (type, team_id, description, created_by) VALUES (?, ?, ?, ?)',
                 ('comp_pick_deleted', pick.get('current_owner_id'), desc, user['id']))
    conn.commit()
    conn.close()
    log_audit(user['id'], 'delete_comp_pick', 'pick', pick_id, pick, None)
    return jsonify({'success': True})


@app.route('/api/picks/comp', methods=['POST'])
def award_comp_pick():
    user = get_current_user()
    if not user or ROLE_HIERARCHY.get(user.get('role', ''), 0) < ROLE_HIERARCHY['assistant_commissioner']:
        return jsonify({'error': 'Admin access required'}), 403

    data = request.json
    required = ['year', 'round', 'round_order', 'overall_order', 'team_id']
    for f in required:
        if data.get(f) is None:
            return jsonify({'error': f'Missing: {f}'}), 400

    conn = get_db()
    team = conn.execute('SELECT * FROM teams WHERE id = ?', (data['team_id'],)).fetchone()
    if not team:
        return jsonify({'error': 'Team not found'}), 404

    # Insert comp pick
    conn.execute('''INSERT INTO draft_picks
        (year, round, round_order, overall_order, original_owner_id, current_owner_id, is_comp_pick, is_tradeable)
        VALUES (?, ?, ?, ?, ?, ?, 1, 0)''',
        (data['year'], data['round'], data['round_order'], data['overall_order'],
         data['team_id'], data['team_id']))

    # Update overall_order for all picks in same year with overall_order >= new comp pick's overall_order
    # that are NOT comp picks already at that position
    conn.execute('''UPDATE draft_picks
        SET overall_order = overall_order + 1, updated_at = CURRENT_TIMESTAMP
        WHERE year = ? AND round > ? AND overall_order IS NOT NULL
        AND id != (SELECT MAX(id) FROM draft_picks)''',
        (data['year'], data['round']))

    desc = f"Comp pick awarded to {team['short_name']}: {data['year']} Round {data['round']} (Pick {data['round_order']}, Overall {data['overall_order']})"
    comp_admin = get_current_user()
    conn.execute('INSERT INTO transactions (type, team_id, description, discord_posted, created_by) VALUES (?, ?, ?, 0, ?)',
                 ('comp_pick', data['team_id'], desc, comp_admin['id'] if comp_admin else None))
    conn.commit()
    conn.close()
    log_audit(user['id'], 'award_comp_pick', 'pick', None, None, data)
    return jsonify({'success': True, 'message': desc})

# ── Trades ─────────────────────────────────────────────────────────────────

@app.route('/api/trades', methods=['GET'])
def get_trades():
    conn = get_db()
    status = request.args.get('status')
    team_id = request.args.get('team_id')
    query = '''SELECT tr.*,
        t1.short_name as team1_name, t1.abbreviation as team1_abbrev,
        t2.short_name as team2_name, t2.abbreviation as team2_abbrev
        FROM trades tr
        JOIN teams t1 ON t1.id = tr.team1_id
        JOIN teams t2 ON t2.id = tr.team2_id
        WHERE 1=1'''
    params = []

    # Privacy filter: pending trades are only visible to the involved teams and commissioners.
    # Completed/rejected trades are public.
    user = get_current_user()
    if user is None:
        # Not logged in — only show completed trades
        query += " AND tr.status = 'completed'"
    elif user['role'] not in ('creator', 'commissioner', 'assistant_commissioner'):
        # Team owner — show completed/rejected trades plus their own pending trades
        ut = user.get('team_id')
        if ut:
            query += " AND (tr.status NOT IN ('pending_team2','pending_team1_confirm') OR tr.team1_id = ? OR tr.team2_id = ?)"
            params += [ut, ut]
        else:
            query += " AND tr.status = 'completed'"
    # Commissioners see everything — no additional filter

    if status:
        query += ' AND tr.status = ?'
        params.append(status)
    if team_id:
        query += ' AND (tr.team1_id = ? OR tr.team2_id = ?)'
        params += [team_id, team_id]
    query += ' ORDER BY tr.proposed_at DESC'
    trades = conn.execute(query, params).fetchall()

    # Batch-fetch all assets for all trades in a single query (was N+1 before).
    # For dozens of trades this collapses dozens of round-trips into 1.
    trade_ids = [t['id'] for t in trades]
    assets_by_trade = {}
    if trade_ids:
        placeholders = ','.join('?' * len(trade_ids))
        assets_rows = conn.execute(f'''SELECT ta.*,
            p.first_name, p.last_name, p.position, p.overall_rating,
            dp.year as pick_year, dp.round as pick_round, dp.round_order,
            dp.overall_order, dp.is_comp_pick,
            orig.abbreviation as pick_orig_abbrev,
            ft.abbreviation as from_abbrev, tt.abbreviation as to_abbrev
            FROM trade_assets ta
            LEFT JOIN players p ON p.id = ta.player_id
            LEFT JOIN draft_picks dp ON dp.id = ta.pick_id
            LEFT JOIN teams orig ON orig.id = dp.original_owner_id
            LEFT JOIN teams ft ON ft.id = ta.from_team_id
            LEFT JOIN teams tt ON tt.id = ta.to_team_id
            WHERE ta.trade_id IN ({placeholders})''', trade_ids).fetchall()
        for row in assets_rows:
            assets_by_trade.setdefault(row['trade_id'], []).append(dict(row))

    result = []
    for trade in trades:
        t = dict(trade)
        t['assets'] = assets_by_trade.get(t['id'], [])
        result.append(t)

    conn.close()
    return jsonify(result)

@app.route('/api/trades', methods=['POST'])
@require_auth
def propose_trade():
    proposer = request.current_user
    data = request.json
    team1_id = data.get('team1_id')
    team2_id = data.get('team2_id')
    assets = data.get('assets', [])  # [{asset_type, player_id or pick_id, from_team_id, to_team_id}]

    if not team1_id or not team2_id or not assets:
        return jsonify({'error': 'team1_id, team2_id, and assets required'}), 400
    if team1_id == team2_id:
        return jsonify({'error': 'Cannot trade with yourself'}), 400

    # Authorization: proposer must own team1 (or be an admin proposing on someone's behalf)
    if not can_manage_team(proposer, team1_id):
        return jsonify({'error': 'You can only propose trades from a team you own'}), 403

    notes = data.get('notes', '') or ''
    counter_of = data.get('counter_of')  # original trade ID if this is a counter

    conn = get_db()

    # Check trading window
    trading_enabled = get_setting('trading_enabled')
    if trading_enabled != 'true':
        conn.close()
        return jsonify({'error': 'Trading is currently closed'}), 400

    # Validate asset ownership
    for asset in assets:
        if asset['asset_type'] == 'player':
            p = conn.execute('SELECT * FROM players WHERE id = ?', (asset['player_id'],)).fetchone()
            if not p or p['nml_team_id'] != asset['from_team_id']:
                conn.close()
                return jsonify({'error': f"Player {asset['player_id']} not owned by proposing team"}), 400
        elif asset['asset_type'] == 'pick':
            pk = conn.execute('SELECT * FROM draft_picks WHERE id = ?', (asset['pick_id'],)).fetchone()
            if not pk or pk['current_owner_id'] != asset['from_team_id']:
                conn.close()
                return jsonify({'error': f"Pick {asset['pick_id']} not owned by proposing team"}), 400
            if not pk['is_tradeable']:
                conn.close()
                return jsonify({'error': 'Comp picks are not tradeable'}), 400
            # Reject trades that include a pick already used in the draft
            used = conn.execute(
                'SELECT 1 FROM draft_selections WHERE draft_pick_id = ? LIMIT 1',
                (asset['pick_id'],)
            ).fetchone()
            if used:
                conn.close()
                return jsonify({'error': f"Pick has already been used in the draft and cannot be traded."}), 400

    # Cap check preview (warning only at proposal stage)
    warnings = _check_roster_caps(conn, assets)

    # Create trade — capture proposer so leaderboard can credit them
    proposer_id = proposer['id']
    c = conn.execute(
        '''INSERT INTO trades (team1_id, team2_id, status, notes, proposed_by) VALUES (?, ?, 'pending_team2', ?, ?)''',
        (team1_id, team2_id, notes, proposer_id))
    trade_id = c.lastrowid

    for asset in assets:
        conn.execute('''INSERT INTO trade_assets (trade_id, asset_type, player_id, pick_id, from_team_id, to_team_id)
            VALUES (?, ?, ?, ?, ?, ?)''',
            (trade_id, asset['asset_type'],
             asset.get('player_id'), asset.get('pick_id'),
             asset['from_team_id'], asset['to_team_id']))

    conn.commit()

    # If this is a counter-offer, cancel the original trade now that the new one is submitted
    original_trade_dict = None
    if counter_of:
        try:
            orig = conn.execute('SELECT * FROM trades WHERE id = ?', (counter_of,)).fetchone()
            if orig and orig['status'] == 'pending_team2':
                conn.execute(
                    'UPDATE trades SET status = ?, team2_responded_at = CURRENT_TIMESTAMP WHERE id = ?',
                    ('countered', counter_of)
                )
                conn.commit()
                original_trade_dict = dict(orig)
        except Exception:
            pass  # Don't fail the new trade if cleanup fails

    conn.close()

    # Notify team2 about the new proposal
    trade_record = {'id': trade_id, 'team1_id': team1_id, 'team2_id': team2_id, 'notes': notes}
    try:
        notify_trade_action(trade_record, 'proposed', team2_id)
    except Exception as e:
        print(f"[Discord] notify_trade_action 'proposed' failed: {e}")

    # If we countered an original trade, notify the original team1 (they sent the original proposal)
    if original_trade_dict:
        try:
            notify_trade_action(original_trade_dict, 'countered', original_trade_dict['team1_id'])
        except Exception:
            pass

    return jsonify({'trade_id': trade_id, 'warnings': warnings}), 201


@app.route('/api/trades/<int:trade_id>/counter', methods=['POST'])
@require_auth
def counter_trade(trade_id):
    """Team 2 counters — marks original as countered, returns assets to pre-populate new proposal"""
    conn = get_db()
    user = get_current_user()
    trade = conn.execute('SELECT * FROM trades WHERE id = ?', (trade_id,)).fetchone()

    if not trade or trade['status'] != 'pending_team2':
        conn.close()
        return jsonify({'error': 'Trade not found or not awaiting response'}), 400

    if user.get('team_id') != trade['team2_id'] and user['role'] not in ('creator', 'commissioner', 'assistant_commissioner'):
        conn.close()
        return jsonify({'error': 'Only Team 2 can counter this proposal'}), 403

    # Fetch full asset data before marking countered
    assets = conn.execute('''SELECT ta.*,
        p.first_name, p.last_name, p.position, p.overall_rating,
        dp.year as pick_year, dp.round as pick_round, dp.round_order,
        dp.overall_order, dp.is_comp_pick,
        orig.abbreviation as pick_orig_abbrev,
        ft.abbreviation as from_abbrev, tt.abbreviation as to_abbrev
        FROM trade_assets ta
        LEFT JOIN players p ON p.id = ta.player_id
        LEFT JOIN draft_picks dp ON dp.id = ta.pick_id
        LEFT JOIN teams orig ON orig.id = dp.original_owner_id
        LEFT JOIN teams ft ON ft.id = ta.from_team_id
        LEFT JOIN teams tt ON tt.id = ta.to_team_id
        WHERE ta.trade_id = ?''', (trade_id,)).fetchall()

    conn.execute('UPDATE trades SET status = ?, team2_responded_at = CURRENT_TIMESTAMP WHERE id = ?',
                 ('countered', trade_id))
    conn.commit()
    trade_dict = dict(trade)
    assets_list = rows_to_list(assets)
    conn.close()

    try:
        notify_trade_action(trade_dict, 'countered', trade_dict['team1_id'])
    except Exception:
        pass  # Never block the response due to notification failure

    return jsonify({
        'success': True,
        'original_team1_id': trade_dict['team1_id'],
        'original_team2_id': trade_dict['team2_id'],
        'assets': assets_list,
        'notes': trade_dict.get('notes', '')
    })

def _check_roster_caps(conn, assets):
    """Check if trade would cause either team to exceed roster cap during season"""
    today = datetime.now().strftime('%Y-%m-%d')
    season_start = get_setting('season_start_date')
    season_end = get_setting('season_end_date')
    cap = int(get_setting('roster_cap') or 53)

    if not (season_start <= today <= season_end):
        return []  # No cap concern in offseason

    warnings = []
    team_deltas = {}  # team_id -> delta in player count

    for asset in assets:
        if asset['asset_type'] == 'player':
            from_id = asset['from_team_id']
            to_id = asset['to_team_id']
            team_deltas[from_id] = team_deltas.get(from_id, 0) - 1
            team_deltas[to_id] = team_deltas.get(to_id, 0) + 1

    for team_id, delta in team_deltas.items():
        if delta <= 0:
            continue
        count = conn.execute(
            'SELECT COUNT(*) as cnt FROM players WHERE nml_team_id = ? AND is_free_agent = 0',
            (team_id,)).fetchone()['cnt']
        team = conn.execute('SELECT short_name FROM teams WHERE id = ?', (team_id,)).fetchone()
        new_count = count + delta
        if new_count > cap:
            warnings.append({
                'team_id': team_id,
                'team_name': team['short_name'],
                'current': count,
                'after_trade': new_count,
                'cap': cap,
                'over_by': new_count - cap
            })
    return warnings

def _discord_result_html(title, body, success):
    """Minimal HTML confirmation page shown after clicking a Discord trade link."""
    color = '#00cc88' if success else '#ff6b6b'
    app_url = _app_url()
    app_link = f'<p style="margin-top:20px"><a href="{app_url}" style="color:#00d4ff;font-size:13px;text-decoration:none">← Open NML League Manager</a></p>' if app_url else ''
    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — NML</title>
<style>
  body{{margin:0;background:#0d0f14;color:#e0e2ea;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px;box-sizing:border-box;}}
  .card{{background:#1a1d26;border:1px solid #2a2e38;border-radius:12px;padding:32px 28px;max-width:420px;width:100%;text-align:center;}}
  h1{{font-size:20px;font-weight:700;color:{color};margin:0 0 10px;}}
  p{{font-size:13px;color:#8b90a4;line-height:1.6;margin:0;}}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{body}</p>{app_link}</div></body>
</html>'''

@app.route('/api/trades/<int:trade_id>/discord-respond', methods=['GET'])
def discord_trade_respond(trade_id):
    """Show a confirmation page — does NOT process the action. Prevents Discord unfurl auto-triggering."""
    from datetime import datetime
    token_str = request.args.get('token', '')
    action    = request.args.get('action', '')

    if action not in ('accept', 'reject'):
        return _discord_result_html('Invalid Action', 'This link is not valid.', False)

    conn = get_db()
    try:
        tok = conn.execute(
            'SELECT * FROM trade_tokens WHERE token=? AND trade_id=? AND action=?',
            (token_str, trade_id, action)
        ).fetchone()
        if not tok:
            return _discord_result_html('Invalid Link', 'This link is not valid or has expired.', False)
        if tok['used']:
            return _discord_result_html('Already Used',
                'This link has already been used. Check the app for the current trade status.', False)
        if datetime.utcnow().isoformat() > tok['expires_at']:
            return _discord_result_html('Link Expired',
                'This link expired after 48 hours. Please respond via the app.', False)

        trade = conn.execute('SELECT * FROM trades WHERE id=?', (trade_id,)).fetchone()
        if not trade:
            return _discord_result_html('Trade Not Found', 'This trade no longer exists.', False)
        if trade['status'] != 'pending_team2':
            return _discord_result_html('Already Responded',
                'This trade has already been responded to. Check the app for the current status.', False)
    finally:
        conn.close()

    # Show confirmation page — action only fires when user clicks the button (POST)
    action_label = 'Accept Trade' if action == 'accept' else 'Reject Trade'
    btn_color    = '#00cc88'      if action == 'accept' else '#ff6b6b'
    warning      = '' if action == 'accept' else '<p style="font-size:12px;color:#ff9966;margin-top:8px">This cannot be undone.</p>'
    post_url     = f'/api/trades/{trade_id}/discord-respond?token={token_str}&action={action}'
    app_url      = _app_url()
    app_link     = f'<p style="margin-top:16px"><a href="{app_url}" style="color:#00d4ff;font-size:12px;text-decoration:none">← Open NML League Manager</a></p>' if app_url else ''

    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{action_label} — NML</title>
<style>
  body{{margin:0;background:#0d0f14;color:#e0e2ea;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px;box-sizing:border-box;}}
  .card{{background:#1a1d26;border:1px solid #2a2e38;border-radius:12px;padding:32px 28px;max-width:420px;width:100%;text-align:center;}}
  h1{{font-size:20px;font-weight:700;color:#e0e2ea;margin:0 0 10px;}}
  p{{font-size:13px;color:#8b90a4;line-height:1.6;margin:0;}}
  .btn{{display:inline-block;margin-top:20px;padding:12px 28px;background:{btn_color};color:#fff;
        font-size:15px;font-weight:700;border:none;border-radius:8px;cursor:pointer;width:100%;}}
  .btn:hover{{opacity:.85;}}
  .wv-note{{display:none;background:#1e2030;border:1px solid #3a3f55;border-radius:8px;padding:10px 14px;
            font-size:12px;color:#a0a8c0;margin-bottom:16px;text-align:left;}}
</style>
<script>
  // Detect Discord iOS WebView (no "Safari" in UA despite AppleWebKit)
  (function(){{
    var ua=navigator.userAgent;
    if(/iPhone|iPad/.test(ua)&&/AppleWebKit/.test(ua)&&!/Safari/.test(ua)){{
      document.addEventListener('DOMContentLoaded',function(){{
        document.getElementById('wvNote').style.display='block';
      }});
    }}
  }})();
</script>
</head>
<body><div class="card">
  <div class="wv-note" id="wvNote">⚠️ You're in Discord's browser. Accepting/rejecting will work, but to open NML afterwards copy the link below and paste it in Safari.</div>
  <h1>Trade #{trade_id}</h1>
  <p>Click the button below to confirm your response.</p>
  {warning}
  <form method="POST" action="{post_url}">
    <button class="btn" type="submit">{action_label}</button>
  </form>
  {app_link}
</div></body></html>'''

@app.route('/api/trades/<int:trade_id>/discord-respond', methods=['POST'])
def discord_trade_respond_confirm(trade_id):
    """Process accept/reject after user confirms on the GET page."""
    from datetime import datetime
    token_str = request.args.get('token', '')
    action    = request.args.get('action', '')

    if action not in ('accept', 'reject'):
        return _discord_result_html('Invalid Action', 'This link is not valid.', False)

    conn = get_db()
    try:
        tok = conn.execute(
            'SELECT * FROM trade_tokens WHERE token=? AND trade_id=? AND action=?',
            (token_str, trade_id, action)
        ).fetchone()
        if not tok:
            return _discord_result_html('Invalid Link', 'This link is not valid or has expired.', False)
        if tok['used']:
            return _discord_result_html('Already Used',
                'This link has already been used. Check the app for the current trade status.', False)
        if datetime.utcnow().isoformat() > tok['expires_at']:
            return _discord_result_html('Link Expired',
                'This link expired after 48 hours. Please respond via the app.', False)

        trade = conn.execute('SELECT * FROM trades WHERE id=?', (trade_id,)).fetchone()
        if not trade:
            return _discord_result_html('Trade Not Found', 'This trade no longer exists.', False)
        if trade['status'] != 'pending_team2':
            return _discord_result_html('Already Responded',
                'This trade has already been responded to. Check the app for the current status.', False)

        # Mark token used
        conn.execute('UPDATE trade_tokens SET used=1 WHERE id=?', (tok['id'],))
        trade_dict = dict(trade)

        if action == 'accept':
            conn.execute(
                'UPDATE trades SET status=?, team2_responded_at=CURRENT_TIMESTAMP WHERE id=?',
                ('pending_team1_confirm', trade_id)
            )
            conn.commit()
            notify_trade_action(trade_dict, 'accepted_awaiting_confirm', trade['team1_id'])
            return _discord_result_html(
                '✅ Trade Accepted',
                f'Trade #{trade_id} accepted. The other team will be notified to give final confirmation.',
                True
            )
        else:
            conn.execute(
                'UPDATE trades SET status=?, team2_responded_at=CURRENT_TIMESTAMP WHERE id=?',
                ('rejected_team2', trade_id)
            )
            conn.commit()
            notify_trade_action(trade_dict, 'rejected_team2', trade['team1_id'])
            return _discord_result_html(
                '❌ Trade Rejected',
                f'Trade #{trade_id} has been rejected. The proposing team has been notified.',
                True
            )
    finally:
        conn.close()

@app.route('/api/trades/<int:trade_id>/respond', methods=['POST'])
@require_auth
def respond_to_trade(trade_id):
    """Team 2 accepts or rejects. Team 1 (the proposer) may also call this with
    action='reject' to cancel/withdraw the proposal before team2 responds."""
    user = request.current_user
    data = request.json
    action = data.get('action')  # 'accept' or 'reject'
    if action not in ('accept', 'reject'):
        return jsonify({'error': 'action must be accept or reject'}), 400

    conn = get_db()
    trade = conn.execute('SELECT * FROM trades WHERE id = ?', (trade_id,)).fetchone()
    if not trade or trade['status'] != 'pending_team2':
        conn.close()
        return jsonify({'error': 'Trade not found or not awaiting team2 response'}), 400

    is_team2 = can_manage_team(user, trade['team2_id'])
    is_team1 = can_manage_team(user, trade['team1_id'])

    # Authorization: team2 may accept/reject; team1 may cancel (reject only).
    if not is_team2 and not is_team1:
        conn.close()
        return jsonify({'error': 'You can only respond to trades involving a team you own'}), 403

    # Team1 (proposer) cancelling their own proposal — only valid path is reject.
    # If the caller manages both teams (admin), default to acting as team2.
    if is_team1 and not is_team2:
        if action != 'reject':
            conn.close()
            return jsonify({'error': 'The proposing team can only cancel (reject) a pending trade'}), 400
        conn.execute('UPDATE trades SET status = ?, team2_responded_at = CURRENT_TIMESTAMP WHERE id = ?',
                     ('cancelled_team1', trade_id))
        conn.commit()
        notify_trade_action(dict(trade), 'cancelled_by_team1', trade['team2_id'])
        conn.close()
        return jsonify({'success': True, 'status': 'cancelled_team1'})

    # Team2 (recipient) accepting or rejecting
    if action == 'reject':
        conn.execute('UPDATE trades SET status = ?, team2_responded_at = CURRENT_TIMESTAMP WHERE id = ?',
                     ('rejected_team2', trade_id))
        conn.commit()
        notify_trade_action(dict(trade), 'rejected_team2', trade['team1_id'])
    else:
        conn.execute('UPDATE trades SET status = ?, team2_responded_at = CURRENT_TIMESTAMP WHERE id = ?',
                     ('pending_team1_confirm', trade_id))
        conn.commit()
        notify_trade_action(dict(trade), 'accepted_awaiting_confirm', trade['team1_id'])

    conn.close()
    return jsonify({'success': True, 'status': 'rejected_team2' if action == 'reject' else 'pending_team1_confirm'})

@app.route('/api/trades/<int:trade_id>/confirm', methods=['POST'])
@require_auth
def confirm_trade(trade_id):
    """Team 1 final confirm or reject"""
    user = request.current_user
    data = request.json
    action = data.get('action')
    if action not in ('confirm', 'reject'):
        return jsonify({'error': 'action must be confirm or reject'}), 400

    conn = get_db()
    trade = conn.execute('SELECT * FROM trades WHERE id = ?', (trade_id,)).fetchone()
    if not trade or trade['status'] != 'pending_team1_confirm':
        conn.close()
        return jsonify({'error': 'Trade not in correct state'}), 400

    # Authorization: only the team1 owner (or an admin) can confirm this trade
    if not can_manage_team(user, trade['team1_id']):
        conn.close()
        return jsonify({'error': 'You can only confirm trades you initiated'}), 403

    # Guard: if a transaction record already exists for this trade, it was already
    # processed (e.g. after a DB upload rolled back the trade status). Return success
    # without re-processing assets or re-posting to Discord.
    already_done = conn.execute(
        "SELECT id FROM transactions WHERE trade_id = ? AND type = 'trade' LIMIT 1",
        (trade_id,)
    ).fetchone()
    if already_done:
        conn.close()
        return jsonify({'success': True, 'status': 'completed', 'note': 'already_processed'})

    if action == 'reject':
        conn.execute('UPDATE trades SET status = ?, team1_confirmed_at = CURRENT_TIMESTAMP WHERE id = ?',
                     ('rejected_team1', trade_id))
        conn.commit()
        notify_trade_action(dict(trade), 'rejected_team1', trade['team2_id'])
        conn.close()
        return jsonify({'success': True, 'status': 'rejected_team1'})

    # Final cap check before processing
    assets = conn.execute('SELECT * FROM trade_assets WHERE trade_id = ?', (trade_id,)).fetchall()
    assets_list = [dict(a) for a in assets]
    cap_warnings = _check_roster_caps(conn, assets_list)
    hard_violations = [w for w in cap_warnings if w['over_by'] > 0]
    if hard_violations:
        conn.close()
        return jsonify({'error': 'Trade blocked: roster cap violation', 'violations': hard_violations}), 400

    # Process trade — transfer all assets
    t1 = conn.execute('SELECT * FROM teams WHERE id = ?', (trade['team1_id'],)).fetchone()
    t2 = conn.execute('SELECT * FROM teams WHERE id = ?', (trade['team2_id'],)).fetchone()
    asset_descriptions_t1 = []  # assets t1 receives
    asset_descriptions_t2 = []  # assets t2 receives

    for asset in assets_list:
        if asset['asset_type'] == 'player':
            p = conn.execute('SELECT * FROM players WHERE id = ?', (asset['player_id'],)).fetchone()
            conn.execute('UPDATE players SET nml_team_id = ?, on_trade_block = 0, trade_block_note = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                         (asset['to_team_id'], asset['player_id']))
            conn.execute('DELETE FROM depth_chart WHERE player_id = ?', (asset['player_id'],))
            desc = f"{p['position']} {p['first_name']} {p['last_name']}"
            if asset['to_team_id'] == trade['team1_id']:
                asset_descriptions_t1.append(desc)
            else:
                asset_descriptions_t2.append(desc)
        elif asset['asset_type'] == 'pick':
            pk = conn.execute('SELECT * FROM draft_picks WHERE id = ?', (asset['pick_id'],)).fetchone()
            orig = conn.execute('SELECT abbreviation FROM teams WHERE id = ?', (pk['original_owner_id'],)).fetchone()
            conn.execute('UPDATE draft_picks SET current_owner_id = ?, on_trade_block = 0, trade_block_note = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                         (asset['to_team_id'], asset['pick_id']))
            _pick_parts = [str(pk['year']), str(pk['round'])]
            if pk['round_order']: _pick_parts.append(str(pk['round_order']))
            if pk['overall_order']: _pick_parts.append(str(pk['overall_order']))
            _pick_parts.append(orig['abbreviation'])
            desc = ' '.join(_pick_parts)
            if asset['to_team_id'] == trade['team1_id']:
                asset_descriptions_t1.append(desc)
            else:
                asset_descriptions_t2.append(desc)

    # Build trade post format
    t1_receives = '\n'.join(asset_descriptions_t1) or 'Nothing'
    t2_receives = '\n'.join(asset_descriptions_t2) or 'Nothing'
    trade_desc = (
        f"{t1['short_name']} - {t2['short_name']} trade\n"
        f"{t1['short_name']} trade:\n{t2_receives}\n\n"
        f"{t2['short_name']} trade:\n{t1_receives}"
    )

    confirmer = get_current_user()
    confirmer_id = confirmer['id'] if confirmer else None
    conn.execute('UPDATE trades SET status = ?, team1_confirmed_at = CURRENT_TIMESTAMP, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
                 ('completed', trade_id))
    # Record transaction for both teams so each sees the trade in their recent activity
    conn.execute('INSERT INTO transactions (type, trade_id, team_id, description, created_by) VALUES (?, ?, ?, ?, ?)',
                 ('trade', trade_id, trade['team1_id'], trade_desc, confirmer_id))
    conn.execute('INSERT INTO transactions (type, trade_id, team_id, description, created_by) VALUES (?, ?, ?, ?, ?)',
                 ('trade', trade_id, trade['team2_id'], trade_desc, confirmer_id))
    conn.commit()
    _cache_bust('players_')

    # Notify both teams via Discord DM
    notify_trade_action(dict(trade), 'completed', trade['team1_id'])
    notify_trade_action(dict(trade), 'completed', trade['team2_id'])

    # Post to Discord trades channel
    post_trades = conn.execute("SELECT value FROM league_settings WHERE key='post_trades_to_discord'").fetchone()
    trades_channel = conn.execute("SELECT value FROM league_settings WHERE key='discord_trades_channel_id'").fetchone()
    if post_trades and post_trades['value'] == 'true' and trades_channel and trades_channel['value']:
        send_discord_message(trades_channel['value'], f"🏈 **{trade_desc}**")

    conn.close()
    return jsonify({'success': True, 'status': 'completed', 'summary': trade_desc})

# ── Transaction Log ────────────────────────────────────────────────────────

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    conn = get_db()
    tx_type = request.args.get('type')
    team_id = request.args.get('team_id')
    limit = int(request.args.get('limit', 50))
    offset = int(request.args.get('offset', 0))

    # Support comma-separated types e.g. "sign_player,cut_player"
    types = [t.strip() for t in tx_type.split(',')] if tx_type else []

    # Base SELECT — always JOIN users to get the actor's name
    base_select = '''SELECT tx.*, COALESCE(u.display_name, u.discord_username) AS actor_name
        FROM transactions tx
        LEFT JOIN users u ON u.id = tx.created_by'''

    if team_id:
        # My Transactions — show all records for this team (one trade record per team is correct here)
        query = base_select + ' WHERE tx.team_id = ?'
        params = [team_id]
        if len(types) == 1:
            query += ' AND tx.type = ?'
            params.append(types[0])
        elif len(types) > 1:
            placeholders = ','.join('?' * len(types))
            query += f' AND tx.type IN ({placeholders})'
            params.extend(types)
        query += ' ORDER BY tx.created_at DESC LIMIT ? OFFSET ?'
        params += [limit, offset]
    else:
        # All Transactions — deduplicate trades by keeping only MIN(id) per trade_id
        # so each completed trade appears exactly once
        if len(types) == 1:
            query = base_select + ''' WHERE tx.type = ?
                AND (tx.type != 'trade' OR tx.id IN (
                    SELECT MIN(id) FROM transactions WHERE type = 'trade' GROUP BY trade_id
                ))
                ORDER BY tx.created_at DESC LIMIT ? OFFSET ?'''
            params = [types[0], limit, offset]
        elif len(types) > 1:
            placeholders = ','.join('?' * len(types))
            query = base_select + f''' WHERE tx.type IN ({placeholders})
                AND (tx.type != 'trade' OR tx.id IN (
                    SELECT MIN(id) FROM transactions WHERE type = 'trade' GROUP BY trade_id
                ))
                ORDER BY tx.created_at DESC LIMIT ? OFFSET ?'''
            params = types + [limit, offset]
        else:
            query = base_select + ''' WHERE (tx.type != 'trade' OR tx.id IN (
                    SELECT MIN(id) FROM transactions WHERE type = 'trade' GROUP BY trade_id
                ))
                ORDER BY tx.created_at DESC LIMIT ? OFFSET ?'''
            params = [limit, offset]

    txs = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify(rows_to_list(txs))


@app.route('/api/transactions/<int:tx_id>', methods=['DELETE'])
@require_role('commissioner')
def delete_transaction(tx_id):
    """Hard-delete a single transaction row by ID. Commissioner only."""
    conn = get_db()
    row = conn.execute('SELECT id, type, description FROM transactions WHERE id = ?', (tx_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Transaction not found'}), 404
    conn.execute('DELETE FROM transactions WHERE id = ?', (tx_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'deleted_id': tx_id, 'type': row['type'], 'description': row['description']})


# ── My Stats ───────────────────────────────────────────────────────────────

@app.route('/api/my-stats', methods=['GET'])
def get_my_stats():
    user = get_current_user()
    if not user or not user.get('team_id'):
        return jsonify({'error': 'Login required'}), 401

    team_id = user['team_id']
    user_id = user['id']
    conn = get_db()

    # Determine current league year start from settings
    # offseason_start_date marks the beginning of the new league year (e.g. "2026-03-01")
    offseason_start = get_setting('offseason_start_date') or '2026-03-01'

    # Find all distinct league year starts (March 1 of each year) from the first transaction
    # up to today, so we can compute the denominator for averages
    from datetime import datetime, date
    today = date.today()
    year_start = datetime.strptime(offseason_start, '%Y-%m-%d').date()

    # Walk year_start forward until it exceeds today to find current league year start
    # Each league year runs exactly 12 months
    while True:
        next_year = date(year_start.year + 1, year_start.month, year_start.day)
        if next_year > today:
            break
        year_start = next_year

    current_year_start = year_start.strftime('%Y-%m-%d')

    # Count total league years (from the very first transaction or the app start)
    first_tx = conn.execute('SELECT MIN(created_at) FROM transactions').fetchone()[0]
    if first_tx:
        first_date = datetime.strptime(first_tx[:10], '%Y-%m-%d').date()
        base = datetime.strptime(offseason_start, '%Y-%m-%d').date()
        # Walk base back to find the league year that contains first_date
        while base > first_date:
            base = date(base.year - 1, base.month, base.day)
        # Count years from base to current year_start
        league_years = 0
        cursor = base
        while cursor <= year_start:
            league_years += 1
            cursor = date(cursor.year + 1, cursor.month, cursor.day)
        league_years = max(league_years, 1)
    else:
        league_years = 1

    # ── Trades completed involving this team ──
    trades_all = conn.execute('''
        SELECT COUNT(DISTINCT trade_id) FROM transactions
        WHERE type = 'trade' AND team_id = ?
    ''', (team_id,)).fetchone()[0] or 0

    trades_year = conn.execute('''
        SELECT COUNT(DISTINCT trade_id) FROM transactions
        WHERE type = 'trade' AND team_id = ? AND created_at >= ?
    ''', (team_id, current_year_start)).fetchone()[0] or 0

    # ── Proposals sent by this user (including counters) ──
    proposals_all = conn.execute('''
        SELECT COUNT(*) FROM trades WHERE proposed_by = ?
    ''', (user_id,)).fetchone()[0] or 0

    proposals_year = conn.execute('''
        SELECT COUNT(*) FROM trades WHERE proposed_by = ? AND proposed_at >= ?
    ''', (user_id, current_year_start)).fetchone()[0] or 0

    conn.close()

    def safe_avg(val, years):
        return round(val / years, 1) if years > 0 else 0.0

    return jsonify({
        'trades_this_year': trades_year,
        'trades_all_time': trades_all,
        'proposals_this_year': proposals_year,
        'proposals_all_time': proposals_all,
        'trades_per_year_avg': safe_avg(trades_all, league_years),
        'proposals_per_year_avg': safe_avg(proposals_all, league_years),
        'current_league_year_start': current_year_start,
        'league_years': league_years,
    })


@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    """League usage leaderboard — user-level, tied to discord profile. Visible to all."""
    from datetime import datetime, date
    conn = get_db()

    # Determine current league year start (same logic as my-stats)
    offseason_start = get_setting('offseason_start_date') or '2026-03-01'
    today = date.today()
    year_start = datetime.strptime(offseason_start, '%Y-%m-%d').date()
    while True:
        next_year = date(year_start.year + 1, year_start.month, year_start.day)
        if next_year > today:
            break
        year_start = next_year
    current_year_start = year_start.strftime('%Y-%m-%d')
    current_year_label = year_start.year

    # Get all users with an assigned team
    users = conn.execute('''
        SELECT u.id, u.display_name, u.discord_username, u.team_id, t.short_name as team_name
        FROM users u
        JOIN teams t ON t.id = u.team_id
        WHERE u.team_id IS NOT NULL
    ''').fetchall()

    results = []
    for u in users:
        uid = u['id']
        tid = u['team_id']
        name = u['display_name'] or u['discord_username'] or '—'
        team = u['team_name'] or '—'

        # Trades completed — deduplicated by trade_id on the team's transaction row
        trades_at = conn.execute('''
            SELECT COUNT(DISTINCT trade_id) FROM transactions
            WHERE type='trade' AND team_id=?
        ''', (tid,)).fetchone()[0] or 0
        trades_yr = conn.execute('''
            SELECT COUNT(DISTINCT trade_id) FROM transactions
            WHERE type='trade' AND team_id=? AND created_at>=?
        ''', (tid, current_year_start)).fetchone()[0] or 0

        # Signings completed — by current team
        signs_at = conn.execute('''
            SELECT COUNT(*) FROM transactions
            WHERE type='sign_player' AND team_id=?
        ''', (tid,)).fetchone()[0] or 0
        signs_yr = conn.execute('''
            SELECT COUNT(*) FROM transactions
            WHERE type='sign_player' AND team_id=? AND created_at>=?
        ''', (tid, current_year_start)).fetchone()[0] or 0

        # Proposals sent — already user-level via trades.proposed_by
        props_at = conn.execute('''
            SELECT COUNT(*) FROM trades WHERE proposed_by=?
        ''', (uid,)).fetchone()[0] or 0
        props_yr = conn.execute('''
            SELECT COUNT(*) FROM trades WHERE proposed_by=? AND proposed_at>=?
        ''', (uid, current_year_start)).fetchone()[0] or 0

        total_at = trades_at + signs_at + props_at
        total_yr = trades_yr + signs_yr + props_yr

        if total_at == 0 and total_yr == 0:
            continue

        results.append({
            'user_id': uid,
            'name': name,
            'team': team,
            'trades_yr': trades_yr, 'trades_at': trades_at,
            'signs_yr': signs_yr, 'signs_at': signs_at,
            'props_yr': props_yr, 'props_at': props_at,
            'total_yr': total_yr, 'total_at': total_at,
        })

    # League-wide totals for leaderboard column headers
    conn2 = get_db()
    league_trades_at = conn2.execute(
        "SELECT COUNT(DISTINCT trade_id) FROM transactions WHERE type='trade'"
    ).fetchone()[0] or 0
    league_trades_yr = conn2.execute(
        "SELECT COUNT(DISTINCT trade_id) FROM transactions WHERE type='trade' AND created_at >= ?",
        (current_year_start,)
    ).fetchone()[0] or 0
    league_props_at = conn2.execute(
        "SELECT COUNT(*) FROM trades"
    ).fetchone()[0] or 0
    league_props_yr = conn2.execute(
        "SELECT COUNT(*) FROM trades WHERE proposed_at >= ?",
        (current_year_start,)
    ).fetchone()[0] or 0
    league_signs_at = conn2.execute(
        "SELECT COUNT(*) FROM transactions WHERE type='sign_player'"
    ).fetchone()[0] or 0
    league_signs_yr = conn2.execute(
        "SELECT COUNT(*) FROM transactions WHERE type='sign_player' AND created_at >= ?",
        (current_year_start,)
    ).fetchone()[0] or 0
    conn2.close()

    results.sort(key=lambda x: x['total_at'], reverse=True)
    return jsonify({
        'year_label': current_year_label,
        'league_trades_yr': league_trades_yr,
        'league_trades_at': league_trades_at,
        'league_props_yr': league_props_yr,
        'league_props_at': league_props_at,
        'league_signs_yr': league_signs_yr,
        'league_signs_at': league_signs_at,
        'entries': results,  # all owners — frontend slices top 10 per metric
    })


# ── Power Rankings ─────────────────────────────────────────────────────────

@app.route('/api/power-rankings', methods=['GET'])
@require_auth
def get_power_rankings():
    conn = get_db()
    # Find most recent snapshot
    latest = conn.execute('''
        SELECT season, week_label FROM power_rankings
        ORDER BY created_at DESC LIMIT 1
    ''').fetchone()
    if not latest:
        conn.close()
        return jsonify({'rankings': [], 'week_label': None, 'season': None})
    rows = conn.execute('''
        SELECT pr.*, t.short_name, t.full_name, t.abbreviation
        FROM power_rankings pr
        JOIN teams t ON t.id = pr.team_id
        WHERE pr.season = ? AND pr.week_label = ?
        ORDER BY pr.rank ASC
    ''', (latest['season'], latest['week_label'])).fetchall()
    conn.close()
    return jsonify({
        'rankings': [dict(r) for r in rows],
        'week_label': latest['week_label'],
        'season': latest['season']
    })


@app.route('/api/power-rankings/calculate', methods=['POST'])
@require_role('commissioner')
def calculate_power_rankings():
    import datetime as dt_module
    data = request.get_json() or {}
    season = data.get('season', str(dt_module.datetime.now().year))
    week_label = data.get('week_label', f"Week of {dt_module.datetime.now().strftime('%b %d')}")

    conn = get_db()

    # Fetch settings
    tgs = {r['key']: float(r['value']) for r in conn.execute("SELECT key,value FROM trade_grade_settings").fetchall()}
    prs = {r['key']: float(r['value']) for r in conn.execute("SELECT key,value FROM power_ranking_settings").fetchall()}
    pick_chart = {r['pick_num']: r['value'] for r in conn.execute('SELECT pick_num, value FROM draft_pick_chart').fetchall()}

    player_value_scale = tgs.get('player_value_scale', 2.0)
    pick_chart_scale = tgs.get('pick_chart_scale', 0.10)

    speed_bonus_enabled = tgs.get('speed_bonus_enabled', 1) == 1
    speed_bonus_scale = tgs.get('speed_bonus_scale', 0.15)
    speed_bonus_positions = set(tgs.get('speed_bonus_positions', '').split(',')) if speed_bonus_enabled else set()

    # Load position speed stats for bonus calculation
    speed_stats = {}
    if speed_bonus_enabled:
        from collections import defaultdict
        import math
        all_rows = conn.execute('''
            SELECT position, speed FROM players
            WHERE nml_team_id IS NOT NULL AND speed IS NOT NULL
        ''').fetchall()
        pos_speeds = defaultdict(list)
        for r in all_rows:
            pos_speeds[r['position']].append(r['speed'])
        for pos, spds in pos_speeds.items():
            n = len(spds)
            if n < 2:
                continue
            mean = sum(spds) / n
            std = math.sqrt(sum((s - mean) ** 2 for s in spds) / (n - 1))
            speed_stats[pos] = {'mean': mean, 'std': max(std, 1.0)}

    weight_starter = prs.get('weight_starter', 40)
    weight_depth = prs.get('weight_depth', 10)
    weight_age = prs.get('weight_age', 25)
    weight_pick = prs.get('weight_pick', 25)

    # Helper functions
    def ovr_score(ovr):
        ovr = max(0, min(99, ovr or 0))
        return max(0, ((ovr - 50) / 49) ** 2 * 100)

    def age_mult(age):
        age = age or 27
        if age <= 21: return 1.4
        elif age == 22: return 1.3
        elif age == 23: return 1.2
        elif age <= 26: return 1.1
        elif age <= 28: return 1.0
        elif age == 29: return 0.9
        elif age == 30: return 0.8
        elif age == 31: return 0.65
        elif age == 32: return 0.5
        else: return 0.35

    def pos_mult(pos, tgs):
        return tgs.get(f'pos_{pos}', 1.0)

    def player_trade_score(p, tgs):
        compute_age(p)
        p_age = p.get('age', 27)
        base = ovr_score(p['overall_rating']) * age_mult(p_age) * pos_mult(p['position'], tgs) * player_value_scale
        # Speed bonus: relative to position average
        pos = p.get('position', '')
        spd = p.get('speed')
        if speed_bonus_enabled and pos in speed_bonus_positions and spd and pos in speed_stats:
            z = (spd - speed_stats[pos]['mean']) / speed_stats[pos]['std']
            bonus = max(0, min(z, 3.0)) * float(speed_bonus_scale)
            base = base * (1 + bonus)
        return base

    teams = conn.execute('SELECT id, short_name FROM teams ORDER BY id').fetchall()
    current_year = dt_module.datetime.now().year

    scores = []
    for team in teams:
        tid = team['id']

        # Get depth chart starters for this team
        # COALESCE: rookies whose Madden OVR isn't loaded yet count via projected_ovr.
        starters = conn.execute('''
            SELECT p.id, COALESCE(p.overall_rating, p.projected_ovr) AS overall_rating,
                   p.position, p.birth_date, p.speed
            FROM depth_chart dc
            JOIN players p ON p.id = dc.player_id
            WHERE dc.user_id IN (SELECT id FROM users WHERE team_id = ?)
        ''', (tid,)).fetchall()

        # Calculate raw starter score using trade grader formula
        raw_starter_score = 0
        starter_ages = []
        if starters:
            for s in starters:
                sd = dict(s)
                ps = player_trade_score(sd, tgs)
                raw_starter_score += ps
                starter_ages.append(sd.get('age', 27))

        if not starter_ages:
            starter_ages = [27]

        # Full roster for depth score (rookies count via projected_ovr fallback).
        roster = conn.execute('''
            SELECT id, COALESCE(overall_rating, projected_ovr) AS overall_rating,
                   position, birth_date, speed FROM players
            WHERE nml_team_id = ?
              AND COALESCE(overall_rating, projected_ovr) IS NOT NULL
        ''', (tid,)).fetchall()

        raw_depth_score = 0
        if roster:
            for r in roster:
                raw_depth_score += player_trade_score(dict(r), tgs)
            raw_depth_score = raw_depth_score / len(roster)
        else:
            raw_depth_score = ovr_score(70)

        # Age score (inverse: younger is better)
        avg_starter_age = sum(starter_ages) / len(starter_ages) if starter_ages else 27

        # Pick capital using trade grader formula
        picks = conn.execute('''
            SELECT round, year, overall_order FROM draft_picks
            WHERE current_owner_id = ? AND is_tradeable = 1
        ''', (tid,)).fetchall()

        raw_pick_score = 0
        pick_year_penalty = tgs.get('pick_year_penalty', 0.3)
        for pk in picks:
            oo = pk['overall_order']
            if oo and oo in pick_chart:
                # Current-year pick with known slot — use chart value directly, no year penalty
                raw_pick_score += pick_chart[oo] * pick_chart_scale
            else:
                # Future pick or no slot assigned — use round-based value with year penalty
                base = tgs.get(f'pick_{pk["round"]}', 6)
                year_diff = max(0, pk['year'] - current_year)
                raw_pick_score += base * ((1 - pick_year_penalty) ** year_diff)

        scores.append({
            'team_id': tid,
            'raw_starter_score': raw_starter_score,
            'raw_depth_score': raw_depth_score,
            'avg_starter_age': avg_starter_age,
            'raw_pick_score': raw_pick_score,
        })

    # Relative scaling for all components
    max_starter = max((s['raw_starter_score'] for s in scores), default=1) or 1
    max_depth = max((s['raw_depth_score'] for s in scores), default=1) or 1
    max_pick = max((s['raw_pick_score'] for s in scores), default=1) or 1
    min_age = min((s['avg_starter_age'] for s in scores), default=27)
    max_age = max((s['avg_starter_age'] for s in scores), default=27)

    for s in scores:
        s['starter_ovr_score'] = round((s['raw_starter_score'] / max_starter) * weight_starter, 2)
        s['depth_score'] = round((s['raw_depth_score'] / max_depth) * weight_depth, 2)
        age_range = (max_age - min_age) or 1
        s['age_score'] = round((1 - (s['avg_starter_age'] - min_age) / age_range) * weight_age, 2)
        s['pick_score'] = round((s['raw_pick_score'] / max_pick) * weight_pick, 2)
        s['score'] = round(s['starter_ovr_score'] + s['depth_score'] + s['age_score'] + s['pick_score'], 2)

    # Sort by score desc, assign ranks
    scores.sort(key=lambda x: x['score'], reverse=True)

    # Get previous ranks for movement
    prev = conn.execute('''
        SELECT team_id, rank FROM power_rankings
        WHERE season = ? ORDER BY created_at DESC
    ''', (season,)).fetchall()
    prev_map = {}
    for p in prev:
        if p['team_id'] not in prev_map:
            prev_map[p['team_id']] = p['rank']

    # Clear any existing snapshot for this season+week_label before inserting
    conn.execute('DELETE FROM power_rankings WHERE season=? AND week_label=?', (season, week_label))

    # Insert new snapshot
    for i, s in enumerate(scores):
        rank = i + 1
        conn.execute('''
            INSERT INTO power_rankings
            (season, week_label, team_id, rank, prev_rank, score,
             starter_ovr_score, depth_score, age_score, pick_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (season, week_label, s['team_id'], rank,
              prev_map.get(s['team_id']), s['score'],
              s['starter_ovr_score'], s['depth_score'],
              s['age_score'], s['pick_score']))

    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'count': len(scores), 'week_label': week_label})


# ── League Settings ────────────────────────────────────────────────────────

@app.route('/api/settings', methods=['GET'])
@require_role('assistant_commissioner')
def get_settings():
    conn = get_db()
    rows = conn.execute('SELECT * FROM league_settings').fetchall()
    conn.close()
    return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/settings', methods=['PATCH'])
@require_role('assistant_commissioner')
def update_settings():
    data = request.json
    conn = get_db()
    for key, value in data.items():
        conn.execute('INSERT INTO league_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP',
                     (key, str(value)))
    conn.commit()
    conn.close()
    log_audit(None, 'update_settings', 'settings', None, None, data)
    return jsonify({'success': True})

@app.route('/api/trade-grade-settings', methods=['GET'])
@require_auth
def get_trade_grade_settings():
    conn = get_db()
    rows = conn.execute('SELECT key, value FROM trade_grade_settings').fetchall()
    conn.close()
    return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/trade-grade-settings', methods=['PUT'])
@require_role('assistant_commissioner')
def put_trade_grade_settings():
    data = request.get_json()
    conn = get_db()
    for k, v in data.items():
        conn.execute('INSERT OR REPLACE INTO trade_grade_settings (key, value) VALUES (?, ?)', (k, str(v)))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/power-ranking-settings', methods=['GET'])
@require_auth
def get_power_ranking_settings():
    conn = get_db()
    rows = conn.execute('SELECT key, value FROM power_ranking_settings').fetchall()
    conn.close()
    return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/power-ranking-settings', methods=['PUT'])
@require_role('assistant_commissioner')
def put_power_ranking_settings():
    data = request.get_json()
    conn = get_db()
    for k, v in data.items():
        conn.execute('INSERT OR REPLACE INTO power_ranking_settings (key, value) VALUES (?, ?)', (k, str(v)))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/pick-chart', methods=['GET'])
@require_role('readonly')
def get_pick_chart():
    conn = get_db()
    rows = conn.execute('SELECT pick_num, value FROM draft_pick_chart ORDER BY pick_num').fetchall()
    conn.close()
    return jsonify({str(r['pick_num']): r['value'] for r in rows})

@app.route('/api/pick-chart', methods=['PUT'])
@require_role('assistant_commissioner')
def put_pick_chart():
    conn = get_db()
    data = request.get_json() or {}
    for pick_num, val in data.items():
        conn.execute('INSERT OR REPLACE INTO draft_pick_chart (pick_num, value) VALUES (?, ?)',
                     (int(pick_num), float(val)))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/pick-chart/reset', methods=['POST'])
@require_role('assistant_commissioner')
def reset_pick_chart():
    conn = get_db()
    conn.execute('DELETE FROM draft_pick_chart')
    conn.commit()
    # Re-seed with default values
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
        conn.execute('INSERT OR REPLACE INTO draft_pick_chart (pick_num, value) VALUES (?, ?)', (pick_num, val))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/position-speed-stats', methods=['GET'])
@require_role('readonly')
def get_position_speed_stats():
    conn = get_db()
    rows = conn.execute('''
        SELECT position, speed FROM players
        WHERE nml_team_id IS NOT NULL AND speed IS NOT NULL AND overall_rating IS NOT NULL
    ''').fetchall()
    conn.close()

    from collections import defaultdict
    import math
    by_pos = defaultdict(list)
    for r in rows:
        by_pos[r['position']].append(r['speed'])

    result = {}
    for pos, speeds in by_pos.items():
        n = len(speeds)
        if n < 2:
            continue
        mean = sum(speeds) / n
        variance = sum((s - mean) ** 2 for s in speeds) / (n - 1)
        std = math.sqrt(variance)
        result[pos] = {
            'mean': round(mean, 2),
            'std': round(std, 2),
            'count': n,
            'min': min(speeds),
            'max': max(speeds)
        }
    return jsonify(result)

# ── Roster Health ──────────────────────────────────────────────────────────

@app.route('/api/roster-health', methods=['GET'])
def roster_health():
    conn = get_db()
    cap = int(get_setting('roster_cap') or 53)
    teams = conn.execute('''
        SELECT t.id, t.full_name, t.short_name, t.abbreviation, t.owner_name,
            COUNT(p.id) as roster_count
        FROM teams t
        LEFT JOIN players p ON p.nml_team_id = t.id AND p.is_free_agent = 0
        GROUP BY t.id ORDER BY t.short_name
    ''').fetchall()
    conn.close()

    result = []
    for team in teams:
        t = dict(team)
        t['cap'] = cap
        t['over_cap'] = t['roster_count'] > cap
        t['under_cap'] = t['roster_count'] < cap
        result.append(t)
    return jsonify(result)

# ── Draft History ─────────────────────────────────────────────────────────

@app.route('/api/draft-history', methods=['GET'])
def get_draft_history():
    path = os.path.join(os.path.dirname(__file__), 'draft_history.json')
    with open(path) as f:
        data = json.load(f)
    # Dynamically append current draft year when completed and not already in static JSON
    conn = get_db()
    try:
        draft_year = get_current_draft_year(conn)
        year_key = str(draft_year)
        if year_key not in data:
            session = conn.execute('SELECT status FROM draft_session WHERE id=1').fetchone()
            if session and session['status'] == 'completed':
                picks = conn.execute('''
                    SELECT dp.round, dp.round_order, dp.overall_order,
                           orig.full_name AS orig_name,
                           curr.full_name AS curr_name,
                           COALESCE(ds.write_in_position, p.position, '') AS position,
                           COALESCE(ds.write_in_name,
                                    p.first_name || ' ' || p.last_name, '') AS player_name,
                           COALESCE(p.school, '') AS school
                    FROM draft_picks dp
                    JOIN teams orig ON orig.id = dp.original_owner_id
                    JOIN teams curr ON curr.id = dp.current_owner_id
                    LEFT JOIN draft_selections ds ON ds.draft_pick_id = dp.id
                    LEFT JOIN players p ON p.id = ds.player_id
                    WHERE dp.year = ?
                    ORDER BY dp.overall_order ASC
                ''', (draft_year,)).fetchall()
                if picks:
                    data[year_key] = [
                        [r['round'], r['round_order'], r['overall_order'],
                         r['orig_name'], r['curr_name'],
                         r['position'], r['player_name'], r['school']]
                        for r in picks
                    ]
    finally:
        conn.close()
    return jsonify(data)

# ── Audit Log ──────────────────────────────────────────────────────────────

@app.route('/api/audit', methods=['GET'])
def get_audit():
    conn = get_db()
    rows = conn.execute('''SELECT al.*, u.discord_username
        FROM audit_log al LEFT JOIN users u ON u.id = al.user_id
        ORDER BY al.created_at DESC LIMIT 100''').fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))

# ── Trading Window Status ──────────────────────────────────────────────────

@app.route('/api/trading-status', methods=['GET'])
def trading_status():
    today = datetime.now().strftime('%Y-%m-%d')
    offseason_start = get_setting('offseason_start_date')
    draft_date = get_setting('draft_date')
    season_start = get_setting('season_start_date')
    trade_deadline = get_setting('trade_deadline_date')
    trading_enabled = get_setting('trading_enabled')

    if trading_enabled == 'false':
        window = 'closed_manual'
    elif offseason_start <= today < draft_date:
        window = 'offseason'
    elif season_start <= today <= trade_deadline:
        window = 'in_season'
    else:
        window = 'dead_period'

    return jsonify({
        'window': window,
        'trading_enabled': trading_enabled == 'true',
        'today': today,
        'offseason_start': offseason_start,
        'draft_date': draft_date,
        'season_start': season_start,
        'trade_deadline': trade_deadline,
    })

@app.route('/api/trades/cap-check', methods=['POST'])
def cap_check():
    """Preview cap impact of a trade without creating it"""
    data = request.json
    assets = data.get('assets', [])
    conn = get_db()
    warnings = _check_roster_caps(conn, assets)
    conn.close()
    return jsonify({'warnings': warnings})


@app.route('/api/discord/test', methods=['GET'])
def test_discord():
    """Test Discord bot token validity"""
    import discord_bot
    result = discord_bot.test_connection()
    return jsonify(result)


@app.route('/api/discord/test-draft-channel', methods=['POST'])
@require_role('assistant_commissioner')
def test_draft_channel():
    """Send a test pick announcement to the draft channel"""
    import discord_bot
    try:
        discord_bot.notify_draft_pick_made(
            team_id=None,
            player_name='Marcus Webb',
            position='WR',
            overall_order=71,
            round_num=3,
            round_order=7,
            school='Florida State',
            is_rookie_prospect=True,
            is_write_in=False,
            _override_team_name='Chicago Bears'
        )
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/discord/members', methods=['GET'])
@require_role('assistant_commissioner')
def get_discord_members():
    """Fetch all members from the NML Discord server for the matching UI"""
    import requests as req
    token = get_setting('discord_bot_token')
    if not token:
        return jsonify({'error': 'No bot token configured'}), 400

    headers = {'Authorization': f'Bot {token}'}
    DAPI = 'https://discord.com/api/v10'

    # Derive guild_id from one of the configured channel IDs
    channel_id = get_setting('discord_trades_channel_id') or get_setting('discord_transactions_channel_id')
    if not channel_id:
        return jsonify({'error': 'No Discord channel configured — add one in Settings first'}), 400

    ch_res = req.get(f'{DAPI}/channels/{channel_id}', headers=headers, timeout=10)
    if not ch_res.ok:
        return jsonify({'error': f'Could not reach Discord API: {ch_res.status_code}'}), 502
    guild_id = ch_res.json().get('guild_id')
    if not guild_id:
        return jsonify({'error': 'Could not determine Discord server ID from channel'}), 500

    # Fetch up to 1000 members (requires Server Members Intent enabled)
    members_res = req.get(
        f'{DAPI}/guilds/{guild_id}/members?limit=1000',
        headers=headers, timeout=15
    )
    if not members_res.ok:
        if members_res.status_code == 403:
            return jsonify({'error': 'Server Members Intent not enabled. Enable it in the Discord Developer Portal under Bot → Privileged Gateway Intents.'}), 403
        return jsonify({'error': f'Discord error: {members_res.status_code}'}), 502

    raw = members_res.json()
    members = []
    for m in raw:
        u = m.get('user', {})
        if u.get('bot'):
            continue  # skip bots
        members.append({
            'discord_id': u.get('id'),
            'username': u.get('username'),
            'display_name': m.get('nick') or u.get('global_name') or u.get('username'),
            'avatar': f"https://cdn.discordapp.com/avatars/{u['id']}/{u['avatar']}.png" if u.get('avatar') else None,
        })

    members.sort(key=lambda x: (x['display_name'] or '').lower())

    # Also return current team→discord_id mappings so UI can show what's already linked
    conn = get_db()
    teams = conn.execute(
        'SELECT id, short_name, full_name, owner_name, discord_user_id, discord_username FROM teams ORDER BY full_name'
    ).fetchall()
    conn.close()

    return jsonify({
        'members': members,
        'teams': [dict(t) for t in teams],
        'guild_id': guild_id,
    })


@app.route('/api/sync-display-names', methods=['POST'])
@require_role('assistant_commissioner')
def sync_display_names():
    """Fetch server nicknames from Discord and update user display_name.
    Nicknames are expected in the format 'Team/Name' (e.g. 'Raiders/Jon').
    The part after the last '/' is used as the display name.
    If there is no '/', the full nickname is used.
    Users with no nickname set are skipped.
    """
    import requests as req
    token = get_setting('discord_bot_token')
    if not token:
        return jsonify({'error': 'No bot token configured'}), 400

    headers = {'Authorization': f'Bot {token}'}
    DAPI = 'https://discord.com/api/v10'

    channel_id = get_setting('discord_trades_channel_id') or get_setting('discord_transactions_channel_id')
    if not channel_id:
        return jsonify({'error': 'No Discord channel configured — add one in Settings first'}), 400

    ch_res = req.get(f'{DAPI}/channels/{channel_id}', headers=headers, timeout=10)
    if not ch_res.ok:
        return jsonify({'error': f'Could not reach Discord API: {ch_res.status_code}'}), 502

    guild_id = ch_res.json().get('guild_id')
    if not guild_id:
        return jsonify({'error': 'Could not determine Discord server ID'}), 500

    members_res = req.get(f'{DAPI}/guilds/{guild_id}/members?limit=1000', headers=headers, timeout=15)
    if not members_res.ok:
        return jsonify({'error': f'Discord members error: {members_res.status_code}'}), 502

    conn = get_db()
    updated = 0
    skipped = 0
    details = []

    for m in members_res.json():
        u = m.get('user', {})
        if u.get('bot'):
            continue
        discord_id = u.get('id')
        nick = m.get('nick')  # server-specific nickname e.g. "Raiders/Jon"
        if not nick:
            skipped += 1
            continue

        # Parse name from "Team/Name" — take everything after the last "/"
        name = nick.split('/')[-1].strip()
        if not name:
            skipped += 1
            continue

        result = conn.execute(
            'UPDATE users SET display_name = ? WHERE discord_id = ?',
            (name, discord_id)
        )
        if result.rowcount > 0:
            updated += 1
            details.append({'discord_id': discord_id, 'nick': nick, 'name': name})

    conn.commit()
    conn.close()

    return jsonify({
        'updated': updated,
        'skipped': skipped,
        'details': details,
    })


@app.route('/api/discord/link-team', methods=['POST'])
@require_role('assistant_commissioner')
def link_discord_to_team():
    """Link a Discord user ID to a team"""
    data = request.json
    team_id = data.get('team_id')
    discord_id = data.get('discord_id')
    discord_username = data.get('discord_username')
    display_name = data.get('display_name')

    if not team_id or not discord_id:
        return jsonify({'error': 'team_id and discord_id required'}), 400

    conn = get_db()
    conn.execute(
        '''UPDATE teams SET discord_user_id = ?, discord_username = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?''',
        (discord_id, discord_username, team_id)
    )
    # Also update the users table if this Discord user has already logged in
    conn.execute(
        '''UPDATE users SET team_id = ? WHERE discord_id = ? AND team_id IS NULL''',
        (team_id, discord_id)
    )
    conn.commit()
    conn.close()
    log_audit(None, 'link_discord', 'teams', team_id, None, {'discord_id': discord_id, 'username': discord_username})
    return jsonify({'success': True})


@app.route('/api/discord/unlink-team', methods=['POST'])
@require_role('assistant_commissioner')
def unlink_discord_from_team():
    """Remove Discord link from a team"""
    data = request.json
    team_id = data.get('team_id')
    if not team_id:
        return jsonify({'error': 'team_id required'}), 400

    conn = get_db()
    conn.execute(
        '''UPDATE teams SET discord_user_id = NULL, discord_username = NULL, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?''', (team_id,)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/discord/link-teams-bulk', methods=['POST'])
@require_role('assistant_commissioner')
def link_teams_bulk():
    """Link multiple teams to Discord users in one request.
    Body: { links: [{team_id, discord_id, discord_username, display_name}, ...] }
    Unlinked teams (discord_id=null) will be cleared.
    """
    data = request.json or {}
    links = data.get('links', [])
    if not isinstance(links, list):
        return jsonify({'error': 'links must be an array'}), 400

    conn = get_db()
    updated = 0
    cleared = 0
    errors = []
    audit_entries = []  # collect audits, write after commit to avoid lock contention

    for item in links:
        team_id = item.get('team_id')
        discord_id = item.get('discord_id')
        discord_username = item.get('discord_username')

        if not team_id:
            continue

        try:
            if discord_id:
                conn.execute(
                    '''UPDATE teams SET discord_user_id = ?, discord_username = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?''',
                    (discord_id, discord_username, team_id)
                )
                # Also update users table if this person already logged in
                conn.execute(
                    '''UPDATE users SET team_id = ? WHERE discord_id = ? AND team_id IS NULL''',
                    (team_id, discord_id)
                )
                audit_entries.append((team_id, discord_id, discord_username))
                updated += 1
            else:
                conn.execute(
                    '''UPDATE teams SET discord_user_id = NULL, discord_username = NULL, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?''', (team_id,)
                )
                cleared += 1
        except Exception as e:
            errors.append({'team_id': team_id, 'error': str(e)})

    conn.commit()
    conn.close()

    # Write audit logs after commit so they don't compete for the write lock
    for (team_id, discord_id, discord_username) in audit_entries:
        log_audit(None, 'link_discord', 'teams', team_id, None,
                  {'discord_id': discord_id, 'username': discord_username})

    return jsonify({'success': True, 'updated': updated, 'cleared': cleared, 'errors': errors})


# ── Draft ─────────────────────────────────────────────────────────────────

_DRAFT_TIMER_DEFAULTS = {1: 600, 2: 420, 3: 300, 4: 240, 5: 180, 6: 180, 7: 180}

def get_draft_timer_secs(conn, round_num):
    row = conn.execute("SELECT value FROM league_settings WHERE key=?",
                       (f'draft_timer_r{round_num}',)).fetchone()
    if row and row['value']:
        return max(60, min(900, int(row['value'])))  # clamp 1–15 min
    return _DRAFT_TIMER_DEFAULTS.get(round_num, 180)

def get_current_draft_year(conn):
    row = conn.execute("SELECT value FROM league_settings WHERE key='current_draft_year'").fetchone()
    return int(row['value']) if row else 2026

def get_draft_pick_by_index(conn, draft_year, index):
    return conn.execute('''
        SELECT dp.* FROM draft_picks dp
        WHERE dp.year = ?
        ORDER BY dp.overall_order ASC
        LIMIT 1 OFFSET ?
    ''', (draft_year, index)).fetchone()

# Timer-expiry check gate: with 32 users polling /api/draft/state every ~5 sec,
# this check does not need to run on every single call. Throttle it so at most
# one expiry check runs per _TIMER_CHECK_INTERVAL seconds across all callers.
# Worst case: auto-advance fires a few seconds later than it would otherwise.
_last_timer_check = {'ts': None}
_TIMER_CHECK_INTERVAL = 10  # seconds

def check_timer_expiry(conn):
    """If active pick timer has expired, auto-advance. Called on every GET /api/draft/state,
    but throttled to _TIMER_CHECK_INTERVAL seconds to reduce DB load under concurrent polling."""
    now = datetime.now(timezone.utc)
    last = _last_timer_check.get('ts')
    if last and (now - last).total_seconds() < _TIMER_CHECK_INTERVAL:
        return False
    _last_timer_check['ts'] = now
    session = conn.execute("SELECT * FROM draft_session WHERE status='active'").fetchone()
    if not session:
        return False
    draft_year = get_current_draft_year(conn)
    pick = get_draft_pick_by_index(conn, draft_year, session['current_pick_index'])
    if not pick:
        return False
    if conn.execute('SELECT id FROM draft_selections WHERE draft_pick_id=?', (pick['id'],)).fetchone():
        return False  # already picked
    round_num = pick['round']
    timer_sec = get_draft_timer_secs(conn, round_num)
    started = datetime.fromisoformat(session['current_pick_started_at']).replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    if elapsed >= timer_sec:
        advance_pick(conn, skipped=True)
        return True
    return False

def advance_pick(conn, skipped=False):
    """Advance to next pick. Handles skips, makeup queue, auto-submit, Discord notifications."""
    session = conn.execute("SELECT * FROM draft_session WHERE status='active'").fetchone()
    if not session:
        return
    draft_year = get_current_draft_year(conn)

    if skipped:
        pick = get_draft_pick_by_index(conn, draft_year, session['current_pick_index'])
        if pick:
            try:
                conn.execute('INSERT OR IGNORE INTO draft_makeup_queue (draft_pick_id, team_id) VALUES (?,?)',
                             (pick['id'], pick['current_owner_id']))
            except Exception:
                pass
            _fire_and_forget(notify_draft_skipped, pick['current_owner_id'], pick['overall_order'])

    new_index = session['current_pick_index'] + 1
    total = conn.execute('SELECT COUNT(*) as c FROM draft_picks WHERE year=?', (draft_year,)).fetchone()['c']

    if new_index >= total:
        conn.execute("UPDATE draft_session SET status='completed', completed_at=datetime('now') WHERE status='active'")
        conn.commit()
        return

    conn.execute('''UPDATE draft_session SET current_pick_index=?, current_pick_started_at=datetime('now')
                    WHERE status='active' ''', (new_index,))
    conn.commit()

    new_pick = get_draft_pick_by_index(conn, draft_year, new_index)
    if not new_pick:
        return

    team_id = new_pick['current_owner_id']
    round_num = new_pick['round']
    timer_sec = get_draft_timer_secs(conn, round_num)

    # Auto-submit from queue if team has auto_submit on.
    # Loop through queue in priority order until we find a valid candidate
    # (player not already drafted + player record exists). Skip/clean any
    # orphaned or already-drafted entries we encounter.
    while True:
        queue_item = conn.execute('''SELECT * FROM draft_queue WHERE team_id=? AND auto_submit=1
                                     ORDER BY priority ASC LIMIT 1''', (team_id,)).fetchone()
        if not queue_item:
            break  # No more queue items — fall through to normal on-clock notify

        # Write-in queue entry — always valid (no dupe check possible)
        if queue_item['write_in_name'] and not queue_item['player_id']:
            conn.execute('''INSERT INTO draft_selections
                            (draft_pick_id, team_id, write_in_name, write_in_position, selected_at, submitted_by_name)
                            VALUES (?,?,?,?,datetime('now'),?)''',
                         (new_pick['id'], team_id, queue_item['write_in_name'], queue_item['write_in_position'], 'Auto-pick (queue)'))
            conn.execute('DELETE FROM draft_queue WHERE id=?', (queue_item['id'],))
            conn.execute('UPDATE draft_picks SET on_trade_block = 0, trade_block_note = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (new_pick['id'],))
            conn.commit()
            _fire_and_forget(notify_draft_pick_made, team_id, queue_item['write_in_name'], queue_item['write_in_position'],
                             new_pick['overall_order'], round_num=new_pick['round'],
                             round_order=new_pick['round_order'], is_write_in=True)
            advance_pick(conn)
            return

        # Player queue entry — validate before committing
        if queue_item['player_id']:
            # Dupe guard: has this player already been drafted?
            already = conn.execute('SELECT id FROM draft_selections WHERE player_id=?',
                                   (queue_item['player_id'],)).fetchone()
            if already:
                # Player drafted elsewhere — remove from this queue and try next entry
                conn.execute('DELETE FROM draft_queue WHERE id=?', (queue_item['id'],))
                conn.commit()
                continue

            player = conn.execute('SELECT * FROM players WHERE id=?', (queue_item['player_id'],)).fetchone()
            if not player:
                # Orphaned queue entry — clean and try next
                conn.execute('DELETE FROM draft_queue WHERE id=?', (queue_item['id'],))
                conn.commit()
                continue

            # Valid pick — commit it (parity with regular /api/draft/pick path)
            conn.execute('''INSERT INTO draft_selections
                            (draft_pick_id, team_id, player_id, selected_at, submitted_by_name)
                            VALUES (?,?,?,datetime('now'),?)''',
                         (new_pick['id'], team_id, player['id'], 'Auto-pick (queue)'))
            conn.execute('UPDATE players SET nml_team_id=?, is_free_agent=0, is_rookie_prospect=0 WHERE id=?',
                         (team_id, player['id']))
            # Sync Big Board: mark matching draft_prospects row as drafted (non-blocking)
            _sync_big_board_for_pick(conn, player, team_id, new_pick['round'], new_pick['round_order'])
            # Remove this player from ALL teams' queues (they're no longer draftable)
            conn.execute('DELETE FROM draft_queue WHERE player_id=?', (player['id'],))
            # Auto-reject pending trades that include this now-used pick
            _auto_reject_trades_for_pick(conn, new_pick['id'], f"{player['first_name']} {player['last_name']}")
            conn.execute('UPDATE draft_picks SET on_trade_block = 0, trade_block_note = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (new_pick['id'],))
            conn.commit()
            _cache_bust('players_')
            _fire_and_forget(notify_draft_pick_made, team_id, f"{player['first_name']} {player['last_name']}",
                             player['position'], new_pick['overall_order'],
                             round_num=new_pick['round'], round_order=new_pick['round_order'],
                             school=player['school'], is_rookie_prospect=player['is_rookie_prospect'])
            advance_pick(conn)
            return

        # Malformed queue entry (neither player_id nor write-in) — clean and try next
        conn.execute('DELETE FROM draft_queue WHERE id=?', (queue_item['id'],))
        conn.commit()

    # Notify on-clock team and on-deck team
    _fire_and_forget(notify_draft_on_clock, team_id, new_pick['overall_order'], round_num, timer_sec)
    next_pick = get_draft_pick_by_index(conn, draft_year, new_index + 1)
    if next_pick:
        _fire_and_forget(notify_draft_on_deck, next_pick['current_owner_id'], next_pick['overall_order'], next_pick['round'])


@app.route('/api/draft/state', methods=['GET'])
def get_draft_state():
    conn = get_db()
    try:
        check_timer_expiry(conn)
        session = conn.execute('SELECT * FROM draft_session WHERE id=1').fetchone()
        draft_year = get_current_draft_year(conn)

        picks = conn.execute('''
            SELECT dp.id, dp.round, dp.round_order, dp.overall_order, dp.is_comp_pick,
                   dp.current_owner_id, curr.short_name as team_name, curr.abbreviation as team_abbrev,
                   orig.short_name as orig_name,
                   ds.player_id, ds.write_in_name, ds.write_in_position, ds.selected_at, ds.is_makeup_pick,
                   ds.submitted_by_name,
                   p.first_name, p.last_name, p.position, p.school, p.is_rookie_prospect
            FROM draft_picks dp
            JOIN teams curr ON curr.id = dp.current_owner_id
            JOIN teams orig ON orig.id = dp.original_owner_id
            LEFT JOIN draft_selections ds ON ds.draft_pick_id = dp.id
            LEFT JOIN players p ON p.id = ds.player_id
            WHERE dp.year = ?
            ORDER BY dp.overall_order ASC
        ''', (draft_year,)).fetchall()

        picks_list = rows_to_list(picks)

        if not session:
            conn.close()
            return jsonify({'status': 'pending', 'picks': picks_list,
                            'current_pick_index': 0, 'draft_year': draft_year})

        current_pick_index = session['current_pick_index']
        current_pick = None
        next_pick = None
        time_remaining = None

        if session['status'] == 'active' and current_pick_index < len(picks_list):
            current = picks_list[current_pick_index]
            if not current.get('selected_at'):
                round_num = current['round']
                timer_sec = get_draft_timer_secs(conn, round_num)
                # SQLite datetime('now') stores UTC — parse as UTC and compare to UTC now
                started = datetime.fromisoformat(session['current_pick_started_at']).replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                time_remaining = max(0, timer_sec - elapsed)
                current_pick = {**current, 'time_remaining_seconds': time_remaining, 'timer_total_seconds': timer_sec}
            upcoming_picks = [picks_list[i] for i in range(current_pick_index + 1, min(current_pick_index + 6, len(picks_list))) if not picks_list[i].get('selected_at')]
            next_pick = upcoming_picks[0] if upcoming_picks else None

        # Source of truth for who owns the makeup pick is draft_picks.current_owner_id
        # (handles picks that were traded after being skipped — the stored dmq.team_id
        # may be stale post-trade). We alias current_owner_id back as team_id so the
        # frontend can keep using mq.team_id without changes.
        makeup_queue = rows_to_list(conn.execute('''
            SELECT dmq.draft_pick_id, dmq.skipped_at,
                   dp.current_owner_id AS team_id,
                   t.short_name,
                   dp.overall_order AS pick_num,
                   dp.round
            FROM draft_makeup_queue dmq
            JOIN draft_picks dp ON dp.id = dmq.draft_pick_id
            JOIN teams t ON t.id = dp.current_owner_id
        ''').fetchall())

        conn.close()
        return jsonify({
            'status': session['status'],
            'current_pick_index': current_pick_index,
            'picks': picks_list,
            'current_pick': current_pick,
            'next_pick': next_pick,
            'upcoming_picks': upcoming_picks if session['status'] == 'active' else [],
            'makeup_queue': makeup_queue,
            'draft_year': draft_year,
        })
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/draft/players', methods=['GET'])
def get_draft_players():
    """Return players available to be drafted: rookie prospects + free agents (non-rookie)."""
    search = request.args.get('search', '')
    position = request.args.get('position', '')

    # Short-TTL cache for unfiltered queries (the live-draft hot path).
    # With 32 users polling every ~5 seconds, this collapses 32 queries into
    # 1 query every 5 seconds. Keyed under 'players_' prefix so the existing
    # _cache_bust('players_') invalidation on pick/sign/cut picks it up.
    cache_key = None
    if not search and not position:
        cache_key = 'players_draft_available'
        entry = _CACHE.get(cache_key)
        if entry and (datetime.now(timezone.utc) - entry['ts']).total_seconds() <= 5:
            return jsonify(entry['data'])

    conn = get_db()
    try:
        # ---- Part 1: rookie prospects + free agents from `players` table ----
        query = '''SELECT p.*, t.short_name as nml_team_name
                   FROM players p LEFT JOIN teams t ON t.id = p.nml_team_id
                   WHERE (p.is_rookie_prospect = 1 OR (p.is_free_agent = 1 AND (p.is_rookie_prospect = 0 OR p.is_rookie_prospect IS NULL)))
                   AND p.id NOT IN (SELECT player_id FROM draft_selections WHERE player_id IS NOT NULL)'''
        params = []
        if search:
            # Standard substring match + alphanumeric-only fuzzy match (handles
            # typos like "McAllister" vs "McAlister" and "van lanen" vs "Van Lanen").
            search_norm = ''.join(c for c in search.lower() if c.isalnum())
            query += ''' AND (
                p.first_name LIKE ? OR p.last_name LIKE ? OR p.position LIKE ? OR p.school LIKE ?
                OR REPLACE(REPLACE(REPLACE(LOWER(p.first_name||p.last_name),' ',''),'-',''),'.','') LIKE ?
            )'''
            params += [f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%', f'%{search_norm}%']
        if position:
            query += ' AND p.position = ?'
            params.append(position)
        query += ' ORDER BY p.is_rookie_prospect DESC, p.position, p.first_name'
        players = conn.execute(query, params).fetchall()
        result = rows_to_list(players)

        # ---- Part 2: draft_prospects that have NO matching players row ----
        # These are prospects scouted on the Big Board but not in Madden yet.
        # Returned with id = -prospect_id (negative marker). The pick handler
        # detects negative IDs and promotes the prospect to a players row.
        prospect_query = '''
            SELECT dp.id as pid, dp.name, dp.position, dp.school, dp.year
            FROM draft_prospects dp
            WHERE dp.year = (SELECT MAX(year) FROM draft_prospects)
              AND NOT EXISTS (
                  SELECT 1 FROM players p
                  WHERE LOWER(p.first_name||' '||p.last_name) = LOWER(dp.name)
              )
              AND NOT EXISTS (
                  SELECT 1 FROM draft_selections ds
                  WHERE ds.write_in_name = dp.name
              )
        '''
        prospect_params = []
        if search:
            search_norm = ''.join(c for c in search.lower() if c.isalnum())
            prospect_query += ''' AND (
                dp.name LIKE ? OR dp.position LIKE ? OR dp.school LIKE ?
                OR REPLACE(REPLACE(REPLACE(LOWER(dp.name),' ',''),'-',''),'.','') LIKE ?
            )'''
            prospect_params += [f'%{search}%', f'%{search}%', f'%{search}%', f'%{search_norm}%']
        if position:
            prospect_query += ' AND dp.position = ?'
            prospect_params.append(position)
        prospect_query += ' ORDER BY dp.consensus_rank IS NULL, dp.consensus_rank, dp.name'
        prospects = conn.execute(prospect_query, prospect_params).fetchall()

        for pr in prospects:
            full = (pr['name'] or '').strip()
            parts = full.split(None, 1)
            fn = parts[0] if parts else ''
            ln = parts[1] if len(parts) > 1 else ''
            result.append({
                'id': -pr['pid'],   # negative = "this is a prospect, not a player yet"
                'first_name': fn,
                'last_name': ln,
                'position': pr['position'] or '',
                'school': pr['school'] or '',
                'is_rookie_prospect': 1,
                'is_free_agent': 0,
                'nml_team_id': None,
                'nml_team_name': None,
                'overall_rating': None,
                'age': None,
                '_source': 'prospect',  # frontend can label these differently if it wants
            })

        conn.close()
        if cache_key:
            _cache_set(cache_key, result)
        return jsonify(result)
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/draft/start', methods=['POST'])
@require_role('commissioner')
def start_draft():
    conn = get_db()
    try:
        draft_year = get_current_draft_year(conn)
        picks = conn.execute('SELECT * FROM draft_picks WHERE year=? ORDER BY overall_order ASC', (draft_year,)).fetchall()
        if not picks:
            conn.close()
            return jsonify({'error': 'No draft picks found for current year'}), 400
        existing = conn.execute('SELECT * FROM draft_session WHERE id=1').fetchone()
        if existing and existing['status'] == 'active':
            conn.close()
            return jsonify({'error': 'Draft already active'}), 400
        conn.execute('''INSERT OR REPLACE INTO draft_session (id, status, current_pick_index, current_pick_started_at, started_at)
                        VALUES (1, 'active', 0, datetime('now'), datetime('now'))''')
        conn.commit()
        first = picks[0]
        second = picks[1] if len(picks) > 1 else None
        _fire_and_forget(notify_draft_on_clock, first['current_owner_id'], first['overall_order'], first['round'], get_draft_timer_secs(conn, first['round']))
        if second:
            _fire_and_forget(notify_draft_on_deck, second['current_owner_id'], second['overall_order'], second['round'])
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/draft/pause', methods=['POST'])
@require_role('commissioner')
def pause_draft():
    conn = get_db()
    conn.execute("UPDATE draft_session SET status='paused' WHERE status='active'")
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/draft/resume', methods=['POST'])
@require_role('commissioner')
def resume_draft():
    conn = get_db()
    conn.execute("UPDATE draft_session SET status='active', current_pick_started_at=datetime('now') WHERE status='paused'")
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/draft/skip', methods=['POST'])
@require_role('commissioner')
def skip_pick():
    conn = get_db()
    try:
        advance_pick(conn, skipped=True)
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/draft/reset', methods=['POST'])
@require_role('commissioner')
def reset_draft():
    conn = get_db()
    conn.execute('DELETE FROM draft_selections')
    conn.execute('DELETE FROM draft_makeup_queue')
    conn.execute('DELETE FROM draft_queue')
    conn.execute("UPDATE draft_session SET status='pending', current_pick_index=0, current_pick_started_at=NULL, started_at=NULL, completed_at=NULL WHERE id=1")
    conn.commit()
    conn.close()
    return jsonify({'success': True})


_BB_SUFFIX_RE = re.compile(r'\s+(jr|sr|ii|iii|iv|v)\.?$', re.IGNORECASE)
_BB_PUNCT_RE  = re.compile(r"[.,'\-]")
_BB_WS_RE     = re.compile(r'\s+')


def _bb_norm_name(s):
    """Normalize a person's name for matching: lowercase, strip accents,
    drop suffixes (Jr/Sr/II/III/IV/V), drop punctuation, collapse whitespace."""
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = _BB_SUFFIX_RE.sub('', s)
    s = _BB_PUNCT_RE.sub('', s)
    s = _BB_WS_RE.sub(' ', s).strip()
    return s


def _bb_last_token(s):
    parts = _bb_norm_name(s).split()
    return parts[-1] if parts else ''


def _bb_find_prospect(conn, player_row):
    """Tiered match for a drafted player against draft_prospects.
       Tier 1: exact normalized full name.
       Tier 2: same last name + same position.
       Tier 3: same last name only.
       Within each tier, score: position(+1000) > school(+100) > birth_date(+10).
       Returns (prospect_id, tier, candidates_list) or (None, 'no_match', candidates_at_lastname).
       candidates_list is the rows considered at the chosen tier (for diagnostics)."""
    if not player_row:
        return None, 'no_match', []
    fn = (player_row['first_name'] or '').strip()
    ln = (player_row['last_name']  or '').strip()
    full = f"{fn} {ln}".strip()
    if not full:
        return None, 'no_match', []

    p_norm   = _bb_norm_name(full)
    p_last   = _bb_last_token(ln or full)
    p_pos    = (player_row['position']   or '').strip().upper()
    p_school = (player_row['school']     or '').strip().lower()
    p_birth  = (player_row['birth_date'] or '').strip()

    rows = conn.execute(
        "SELECT id, name, position, school, birth_date, nml_team_id "
        "FROM draft_prospects"
    ).fetchall()

    enriched = []
    for c in rows:
        c_pos    = (c['position']   or '').strip().upper()
        c_school = (c['school']     or '').strip().lower()
        c_birth  = (c['birth_date'] or '').strip()
        score = 0
        if p_pos    and c_pos    and p_pos    == c_pos:    score += 1000
        if p_school and c_school and p_school == c_school: score += 100
        if p_birth  and c_birth  and p_birth  == c_birth:  score += 10
        enriched.append({
            'id': c['id'], 'name': c['name'],
            'norm': _bb_norm_name(c['name']),
            'last': _bb_last_token(c['name']),
            'position': c['position'], 'school': c['school'],
            'birth_date': c['birth_date'], 'nml_team_id': c['nml_team_id'],
            'score': score,
            'pos_match': bool(p_pos and c_pos and p_pos == c_pos),
        })

    # Tier 1: exact normalized name
    t1 = [e for e in enriched if e['norm'] and e['norm'] == p_norm]
    if t1:
        best = max(t1, key=lambda x: x['score'])
        return best['id'], ('exact_norm' if len(t1) == 1 else 'exact_norm_scored'), t1

    # Tier 2: last name + position (must agree on position to avoid false positives)
    if p_last and p_pos:
        t2 = [e for e in enriched if e['last'] == p_last and e['pos_match']]
        if t2:
            best = max(t2, key=lambda x: x['score'])
            return best['id'], ('lastname_pos' if len(t2) == 1 else 'lastname_pos_scored'), t2

    # No tier hit: return last-name candidates (any position) as audit suggestions only.
    # We deliberately do NOT auto-match on last-name alone — that produced false matches
    # (e.g. drafted player "X Rutledge" mistakenly linked to Keylan Rutledge's prospect row).
    suggestions = [e for e in enriched if p_last and e['last'] == p_last]
    return None, 'no_match', suggestions


def _sync_big_board_for_pick(conn, player_row, team_id, round_num, round_order):
    """When an NML team drafts a player, mark the matching draft_prospects
    row so the Big Board lights up. Uses tiered fuzzy matcher. Wrapped so a
    sync failure can never block the actual pick."""
    try:
        target_id, _tier, _cands = _bb_find_prospect(conn, player_row)
        if target_id is None:
            return
        conn.execute(
            "UPDATE draft_prospects SET nml_team_id=?, nml_round=?, nml_pick=? WHERE id=?",
            (team_id, round_num, round_order, target_id)
        )
    except Exception:
        # Never block a pick on a Big Board sync failure
        pass


def _promote_prospect_to_player(conn, prospect_id, team_id, round_num=None, round_order=None):
    """Create a players row from a draft_prospects row, then sync the prospect
    record. Used when a team drafts a prospect that exists only on the Big
    Board (no Madden/players record yet). Returns (new_player_id, player_dict).

    Idempotent: if a players row already exists for this prospect (matched by
    name+position+school), reuses it instead of creating a duplicate.
    """
    prospect = conn.execute(
        'SELECT * FROM draft_prospects WHERE id=?', (prospect_id,)
    ).fetchone()
    if not prospect:
        raise ValueError(f'Prospect {prospect_id} not found')

    # Split full name into first / last (everything after first space = last)
    full_name = (prospect['name'] or '').strip()
    parts = full_name.split(None, 1)
    first_name = parts[0] if parts else ''
    last_name = parts[1] if len(parts) > 1 else ''
    position = prospect['position'] or ''
    school = prospect['school'] or ''

    # Idempotency check: existing players row with same first+last+school?
    existing = conn.execute(
        'SELECT * FROM players WHERE first_name=? AND last_name=? AND (school=? OR school IS NULL) COLLATE NOCASE',
        (first_name, last_name, school)
    ).fetchone()

    if existing:
        # Reuse — just make sure flags reflect the draft
        conn.execute(
            'UPDATE players SET nml_team_id=?, is_free_agent=0, is_rookie_prospect=0, school=COALESCE(school, ?) WHERE id=?',
            (team_id, school, existing['id'])
        )
        new_player_id = existing['id']
    else:
        cur = conn.execute(
            '''INSERT INTO players
               (first_name, last_name, position, school, college,
                height, weight, nml_team_id, is_free_agent, is_rookie_prospect)
               VALUES (?,?,?,?,?,?,?,?,0,0)''',
            (first_name, last_name, position, school, school,
             None, prospect['weight'], team_id)
        )
        new_player_id = cur.lastrowid

    # Sync the prospect record so the Big Board lights up
    if round_num is not None and round_order is not None:
        conn.execute(
            'UPDATE draft_prospects SET nml_team_id=?, nml_round=?, nml_pick=? WHERE id=?',
            (team_id, round_num, round_order, prospect_id)
        )
    else:
        conn.execute(
            'UPDATE draft_prospects SET nml_team_id=? WHERE id=?',
            (team_id, prospect_id)
        )

    player = conn.execute('SELECT * FROM players WHERE id=?', (new_player_id,)).fetchone()
    return new_player_id, player


@app.route('/api/draft/pick', methods=['POST'])
@require_auth
def submit_draft_pick():
    conn = get_db()
    try:
        user = get_current_user()
        data = request.json or {}
        player_id = data.get('player_id')
        write_in_name = (data.get('write_in_name') or '').strip()
        write_in_position = (data.get('write_in_position') or '').strip()
        is_makeup = data.get('is_makeup', False)

        session = conn.execute("SELECT * FROM draft_session WHERE status='active'").fetchone()
        if not session:
            conn.close()
            return jsonify({'error': 'Draft is not active'}), 400

        draft_year = get_current_draft_year(conn)

        if is_makeup:
            # Look up the makeup pick. If the client sends a specific draft_pick_id
            # (e.g. an admin submitting on behalf of another team, or when multiple
            # makeup picks are pending), use it directly. Auth is still enforced
            # below via pick.current_owner_id + is_comm check.
            requested_pick_id = data.get('draft_pick_id')
            if requested_pick_id:
                makeup = conn.execute('''
                    SELECT dmq.* FROM draft_makeup_queue dmq
                    JOIN draft_picks dp ON dp.id = dmq.draft_pick_id
                    WHERE dmq.draft_pick_id = ?
                    LIMIT 1
                ''', (requested_pick_id,)).fetchone()
            else:
                # Fallback: look up by the pick's CURRENT owner (works when the
                # logged-in user IS the team with a makeup pick pending).
                makeup = conn.execute('''
                    SELECT dmq.* FROM draft_makeup_queue dmq
                    JOIN draft_picks dp ON dp.id = dmq.draft_pick_id
                    WHERE dp.current_owner_id = ?
                    LIMIT 1
                ''', (user['team_id'],)).fetchone()
            if not makeup:
                conn.close()
                return jsonify({'error': 'No makeup pick available'}), 400
            pick = conn.execute('SELECT * FROM draft_picks WHERE id=?', (makeup['draft_pick_id'],)).fetchone()
            if not pick:
                conn.close()
                return jsonify({'error': 'Makeup pick not found'}), 400
            is_comm = user['role'] in ('creator', 'commissioner', 'assistant_commissioner')
            if not is_comm and user.get('team_id') != pick['current_owner_id']:
                conn.close()
                return jsonify({'error': 'Not your pick'}), 403
            # Capture submitter context for makeup picks too
            mu_proxy_user_id = user['id']
            mu_proxy_name = f"{user.get('first_name','')} {user.get('last_name','')}".strip() or user.get('username','')
            if player_id:
                # Negative ID = prospect-only record (Big Board, no Madden row yet).
                # Promote it to a real players row first.
                if player_id < 0:
                    new_id, _ = _promote_prospect_to_player(
                        conn, -player_id, pick['current_owner_id'],
                        pick['round'], pick['round_order']
                    )
                    player_id = new_id
                conn.execute('''INSERT INTO draft_selections
                                (draft_pick_id, team_id, player_id, is_makeup_pick, submitted_by_user_id, submitted_by_name)
                                VALUES (?,?,?,1,?,?)''',
                             (pick['id'], pick['current_owner_id'], player_id, mu_proxy_user_id, mu_proxy_name))
                player = conn.execute('SELECT * FROM players WHERE id=?', (player_id,)).fetchone()
                if player:
                    conn.execute('UPDATE players SET nml_team_id=?, is_free_agent=0, is_rookie_prospect=0 WHERE id=?',
                                 (pick['current_owner_id'], player_id))
                    # Sync Big Board (parity with regular pick path)
                    _sync_big_board_for_pick(conn, player, pick['current_owner_id'], pick['round'], pick['round_order'])
                    # Remove this player from ALL teams' draft queues
                    conn.execute('DELETE FROM draft_queue WHERE player_id=?', (player_id,))
                    # Auto-reject pending trades that include this now-used pick
                    _auto_reject_trades_for_pick(conn, pick['id'], f"{player['first_name']} {player['last_name']}")
                    _fire_and_forget(notify_draft_pick_made, pick['current_owner_id'], f"{player['first_name']} {player['last_name']}", player['position'], pick['overall_order'],
                                     round_num=pick['round'], round_order=pick['round_order'],
                                     school=player['school'], is_rookie_prospect=player['is_rookie_prospect'])
            elif write_in_name:
                conn.execute('''INSERT INTO draft_selections
                                (draft_pick_id, team_id, write_in_name, write_in_position, is_makeup_pick, submitted_by_user_id, submitted_by_name)
                                VALUES (?,?,?,?,1,?,?)''',
                             (pick['id'], pick['current_owner_id'], write_in_name, write_in_position, mu_proxy_user_id, mu_proxy_name))
                _fire_and_forget(notify_draft_pick_made, pick['current_owner_id'], write_in_name, write_in_position, pick['overall_order'],
                                 round_num=pick['round'], round_order=pick['round_order'], is_write_in=True)
            else:
                conn.close()
                return jsonify({'error': 'No player or write-in provided'}), 400
            conn.execute('DELETE FROM draft_makeup_queue WHERE draft_pick_id=?', (pick['id'],))
            conn.execute('UPDATE draft_picks SET on_trade_block = 0, trade_block_note = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (pick['id'],))
            conn.commit()
            _cache_bust('players_')
            conn.close()
            return jsonify({'success': True})

        # Regular pick
        current_pick = get_draft_pick_by_index(conn, draft_year, session['current_pick_index'])
        if not current_pick:
            conn.close()
            return jsonify({'error': 'No current pick'}), 400
        is_comm = user['role'] in ('creator', 'commissioner', 'assistant_commissioner')
        if not is_comm and user.get('team_id') != current_pick['current_owner_id']:
            conn.close()
            return jsonify({'error': 'Not your pick'}), 403
        if conn.execute('SELECT id FROM draft_selections WHERE draft_pick_id=?', (current_pick['id'],)).fetchone():
            conn.close()
            return jsonify({'error': 'Pick already submitted'}), 400

        # Always capture who submitted this pick. proxy_name (for the
        # notification's "submitted_by" field) only fires when an admin is
        # acting on behalf of another team — but the DB record always
        # captures the submitting user.
        admin_proxy = is_comm and user.get('team_id') != current_pick['current_owner_id']
        submitter_user_id = user['id']
        submitter_name = f"{user.get('first_name','')} {user.get('last_name','')}".strip() or user.get('username','')
        proxy_name = submitter_name if admin_proxy else None

        if player_id:
            # Negative ID = prospect-only record (Big Board, no Madden row yet).
            # Promote it to a real players row first.
            if player_id < 0:
                new_id, _ = _promote_prospect_to_player(
                    conn, -player_id, current_pick['current_owner_id'],
                    current_pick['round'], current_pick['round_order']
                )
                player_id = new_id
            player = conn.execute('SELECT * FROM players WHERE id=?', (player_id,)).fetchone()
            if not player:
                conn.close()
                return jsonify({'error': 'Player not found'}), 404
            conn.execute('''INSERT INTO draft_selections
                            (draft_pick_id, team_id, player_id, selected_at, submitted_by_user_id, submitted_by_name)
                            VALUES (?,?,?,datetime('now'),?,?)''',
                         (current_pick['id'], current_pick['current_owner_id'], player_id, submitter_user_id, submitter_name))
            conn.execute('UPDATE players SET nml_team_id=?, is_free_agent=0, is_rookie_prospect=0 WHERE id=?',
                         (current_pick['current_owner_id'], player_id))
            # Sync Big Board: mark matching draft_prospects row as drafted (non-blocking)
            _sync_big_board_for_pick(conn, player, current_pick['current_owner_id'],
                                     current_pick['round'], current_pick['round_order'])
            # Remove this player from ALL teams' draft queues (prevents auto-submit from re-drafting)
            conn.execute('DELETE FROM draft_queue WHERE player_id=?', (player_id,))
            # Auto-reject any pending trades that include this now-used pick (notifies both teams)
            _auto_reject_trades_for_pick(conn, current_pick['id'], f"{player['first_name']} {player['last_name']}")
            _fire_and_forget(notify_draft_pick_made, current_pick['current_owner_id'], f"{player['first_name']} {player['last_name']}", player['position'], current_pick['overall_order'],
                             round_num=current_pick['round'], round_order=current_pick['round_order'],
                             school=player['school'], is_rookie_prospect=player['is_rookie_prospect'],
                             submitted_by=proxy_name)
        elif write_in_name:
            conn.execute('''INSERT INTO draft_selections
                            (draft_pick_id, team_id, write_in_name, write_in_position, selected_at, submitted_by_user_id, submitted_by_name)
                            VALUES (?,?,?,?,datetime('now'),?,?)''',
                         (current_pick['id'], current_pick['current_owner_id'], write_in_name, write_in_position, submitter_user_id, submitter_name))
            _fire_and_forget(notify_draft_pick_made, current_pick['current_owner_id'], write_in_name, write_in_position, current_pick['overall_order'],
                             round_num=current_pick['round'], round_order=current_pick['round_order'], is_write_in=True,
                             submitted_by=proxy_name)
        else:
            conn.close()
            return jsonify({'error': 'No player or write-in provided'}), 400

        conn.execute('UPDATE draft_picks SET on_trade_block = 0, trade_block_note = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (current_pick['id'],))
        conn.commit()
        _cache_bust('players_')
        advance_pick(conn)
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        msg = str(e)
        if 'locked' in msg.lower():
            return jsonify({'error': 'Draft is busy — please try again in a moment'}), 503
        return jsonify({'error': msg}), 500


@app.route('/api/draft/queue', methods=['GET'])
@require_auth
def get_draft_queue():
    conn = get_db()
    user = get_current_user()
    team_id = user.get('team_id')
    if not team_id:
        conn.close()
        return jsonify([])
    items = conn.execute('''SELECT dq.*, p.first_name, p.last_name, p.position, p.overall_rating, p.projected_ovr, p.is_rookie_prospect
                            FROM draft_queue dq LEFT JOIN players p ON p.id = dq.player_id
                            WHERE dq.team_id=?
                            AND (dq.player_id IS NULL OR dq.player_id NOT IN (
                                SELECT player_id FROM draft_selections WHERE player_id IS NOT NULL
                            ))
                            ORDER BY dq.priority ASC''', (team_id,)).fetchall()
    auto_submit = conn.execute('SELECT auto_submit FROM draft_queue WHERE team_id=? LIMIT 1', (team_id,)).fetchone()
    conn.close()
    return jsonify({
        'items': rows_to_list(items),
        'auto_submit': bool(auto_submit and auto_submit['auto_submit'])
    })


@app.route('/api/draft/queue', methods=['POST'])
@require_auth
def save_draft_queue():
    conn = get_db()
    user = get_current_user()
    team_id = user.get('team_id')
    if not team_id:
        conn.close()
        return jsonify({'error': 'No team assigned'}), 400
    data = request.json or {}
    items = data.get('items', [])
    is_comm = user.get('role') in ('creator', 'commissioner', 'assistant_commissioner')
    # Only admins can change the auto_submit flag; owners' queues preserve existing value
    if is_comm:
        auto_submit = data.get('auto_submit', False)
    else:
        existing = conn.execute('SELECT auto_submit FROM draft_queue WHERE team_id=? LIMIT 1', (team_id,)).fetchone()
        auto_submit = bool(existing and existing['auto_submit']) if existing else False
    conn.execute('DELETE FROM draft_queue WHERE team_id=?', (team_id,))
    for i, item in enumerate(items):
        player_id = item.get('player_id')
        write_in_name = item.get('write_in_name')
        write_in_position = item.get('write_in_position')
        conn.execute('''INSERT INTO draft_queue (team_id, player_id, write_in_name, write_in_position, priority, auto_submit)
                        VALUES (?,?,?,?,?,?)''',
                     (team_id, player_id, write_in_name, write_in_position, i + 1, 1 if auto_submit else 0))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/draft/queue/admin', methods=['GET'])
@require_auth
def get_all_queue_status():
    """Admin: return auto-submit status + queue count for every team that has a queue."""
    user = get_current_user()
    if user.get('role') not in ('creator', 'commissioner', 'assistant_commissioner'):
        return jsonify({'error': 'Admin only'}), 403
    conn = get_db()
    rows = conn.execute('''
        SELECT t.id as team_id, t.short_name,
               MAX(dq.auto_submit) as auto_submit,
               COUNT(dq.id) as queue_count
        FROM teams t
        JOIN draft_queue dq ON dq.team_id = t.id
        GROUP BY t.id, t.short_name
        ORDER BY t.short_name ASC
    ''').fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/draft/queue/admin/toggle', methods=['POST'])
@require_auth
def admin_toggle_auto_submit():
    """Admin: flip auto_submit on/off for any team's queue."""
    user = get_current_user()
    if user.get('role') not in ('creator', 'commissioner', 'assistant_commissioner'):
        return jsonify({'error': 'Admin only'}), 403
    data = request.json or {}
    team_id = data.get('team_id')
    auto_submit = bool(data.get('auto_submit'))
    if not team_id:
        return jsonify({'error': 'team_id required'}), 400
    conn = get_db()
    conn.execute('UPDATE draft_queue SET auto_submit=? WHERE team_id=?',
                 (1 if auto_submit else 0, team_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'team_id': team_id, 'auto_submit': auto_submit})


@app.route('/api/draft/queue/<int:player_id>', methods=['DELETE'])
@require_auth
def remove_from_draft_queue(player_id):
    conn = get_db()
    user = get_current_user()
    team_id = user.get('team_id')
    conn.execute('DELETE FROM draft_queue WHERE team_id=? AND player_id=?', (team_id, player_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/draft/pick/<int:draft_pick_id>', methods=['DELETE'])
@require_auth
def clear_draft_pick(draft_pick_id):
    """Admin: clear a completed draft selection and revert the player to their pre-draft state."""
    user = get_current_user()
    if user.get('role') not in ('creator', 'commissioner', 'assistant_commissioner'):
        return jsonify({'error': 'Admin only'}), 403
    conn = get_db()
    try:
        sel = conn.execute('SELECT * FROM draft_selections WHERE draft_pick_id=?', (draft_pick_id,)).fetchone()
        if not sel:
            conn.close()
            return jsonify({'error': 'No selection found for this pick'}), 404

        player_id = sel['player_id']
        conn.execute('DELETE FROM draft_selections WHERE draft_pick_id=?', (draft_pick_id,))

        if player_id:
            # Determine original state by checking school field:
            # players with a school were rookie prospects; without are free agents
            player = conn.execute('SELECT school FROM players WHERE id=?', (player_id,)).fetchone()
            if player and player['school']:
                conn.execute('UPDATE players SET nml_team_id=NULL, is_free_agent=0, is_rookie_prospect=1 WHERE id=?', (player_id,))
            else:
                conn.execute('UPDATE players SET nml_team_id=NULL, is_free_agent=1, is_rookie_prospect=0 WHERE id=?', (player_id,))

        # Put the pick slot into the makeup queue so the team can re-pick.
        # Note: draft_makeup_queue has no 'id' column — draft_pick_id is the PK.
        pick = conn.execute('SELECT * FROM draft_picks WHERE id=?', (draft_pick_id,)).fetchone()
        if pick:
            existing_mu = conn.execute('SELECT draft_pick_id FROM draft_makeup_queue WHERE draft_pick_id=?', (draft_pick_id,)).fetchone()
            if not existing_mu:
                conn.execute('INSERT INTO draft_makeup_queue (draft_pick_id, team_id) VALUES (?,?)',
                             (draft_pick_id, pick['current_owner_id']))

        conn.commit()
        _cache_bust('players_')
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


# ── Ideas (Feature Requests) ───────────────────────────────────────────────

FEATURE_REQUESTS_CHANNEL = '1494346388652167228'
ADMIN_VOTE_WEIGHT = 3

def _app_url():
    """Return the public app URL, trying Railway's built-in domain first."""
    # Railway automatically sets RAILWAY_PUBLIC_DOMAIN on deployed services
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN') or os.environ.get('APP_URL', '')
    domain = domain.rstrip('/')
    if domain and not domain.startswith('http'):
        domain = f'https://{domain}'
    return domain

def _idea_link(idea_id):
    base = _app_url()
    return f"{base}/#ideas-{idea_id}" if base else f"Idea #{idea_id}"

def _idea_vote_score(conn, idea_id):
    """Calculate weighted vote score for an idea."""
    rows = conn.execute('''
        SELECT u.role FROM idea_votes iv
        JOIN users u ON u.id = iv.user_id
        WHERE iv.idea_id = ?
    ''', (idea_id,)).fetchall()
    score = 0
    for r in rows:
        score += ADMIN_VOTE_WEIGHT if ROLE_HIERARCHY.get(r['role'], 0) >= ROLE_HIERARCHY['assistant_commissioner'] else 1
    return score

def _format_idea(conn, idea, current_user_id=None):
    submitter = conn.execute('SELECT display_name, discord_username FROM users WHERE id = ?', (idea['submitted_by'],)).fetchone()
    score = _idea_vote_score(conn, idea['id'])
    voted = False
    if current_user_id:
        voted = conn.execute('SELECT 1 FROM idea_votes WHERE idea_id=? AND user_id=?', (idea['id'], current_user_id)).fetchone() is not None
    return {
        'id': idea['id'],
        'title': idea['title'],
        'body': idea['body'],
        'submitted_by': idea['submitted_by'],
        'submitter_name': (submitter['display_name'] or submitter['discord_username']) if submitter else 'Unknown',
        'status': idea['status'],
        'dismissal_reason': idea['dismissal_reason'],
        'edited': bool(idea['edited']),
        'created_at': idea['created_at'],
        'updated_at': idea['updated_at'],
        'score': score,
        'voted': voted,
    }

@app.route('/api/ideas', methods=['GET'])
def get_ideas():
    user = get_current_user()
    uid = user['id'] if user else None
    conn = get_db()
    rows = conn.execute('SELECT * FROM ideas ORDER BY updated_at DESC').fetchall()
    ideas = [_format_idea(conn, dict(r), uid) for r in rows]
    conn.close()
    # Sort active + in_progress by score desc; completed + dismissed by updated_at (already done)
    active     = sorted([i for i in ideas if i['status'] == 'active'],      key=lambda x: -x['score'])
    in_prog    = sorted([i for i in ideas if i['status'] == 'in_progress'], key=lambda x: -x['score'])
    completed  = [i for i in ideas if i['status'] == 'completed']
    dismissed  = [i for i in ideas if i['status'] == 'dismissed']
    return jsonify({'active': active, 'in_progress': in_prog, 'completed': completed, 'dismissed': dismissed})

@app.route('/api/ideas', methods=['POST'])
def create_idea():
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Login required'}), 401
    if not user.get('team_id'):
        return jsonify({'error': 'You must be assigned to a team to submit ideas'}), 403
    data = request.json or {}
    title = (data.get('title') or '').strip()
    body  = (data.get('body')  or '').strip()
    if not title:
        return jsonify({'error': 'Title is required'}), 400
    if not body:
        return jsonify({'error': 'Description is required'}), 400

    conn = get_db()
    cur = conn.execute(
        'INSERT INTO ideas (title, body, submitted_by) VALUES (?, ?, ?)',
        (title, body, user['id'])
    )
    idea_id = cur.lastrowid
    conn.commit()
    idea = _format_idea(conn, dict(conn.execute('SELECT * FROM ideas WHERE id=?', (idea_id,)).fetchone()), user['id'])
    conn.close()

    # Discord: post to feature-requests channel
    link = _idea_link(idea_id)
    send_discord_message(FEATURE_REQUESTS_CHANNEL,
        f"💡 **New Idea: {title}**\n{link}")

    return jsonify(idea), 201

@app.route('/api/ideas/<int:idea_id>', methods=['PATCH'])
def update_idea(idea_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Login required'}), 401

    conn = get_db()
    idea = conn.execute('SELECT * FROM ideas WHERE id=?', (idea_id,)).fetchone()
    if not idea:
        conn.close()
        return jsonify({'error': 'Idea not found'}), 404
    idea = dict(idea)

    is_admin_user = ROLE_HIERARCHY.get(user.get('role', ''), 0) >= ROLE_HIERARCHY['assistant_commissioner']
    is_submitter = idea['submitted_by'] == user['id']

    data = request.json or {}

    # Status change — admin only
    new_status = data.get('status')
    if new_status and new_status != idea['status']:
        if not is_admin_user:
            conn.close()
            return jsonify({'error': 'Admin access required to change status'}), 403
        if new_status == 'dismissed':
            reason = (data.get('dismissal_reason') or '').strip()
            if not reason:
                conn.close()
                return jsonify({'error': 'Dismissal reason is required'}), 400
            conn.execute('UPDATE ideas SET status=?, dismissal_reason=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                         (new_status, reason, idea_id))
        else:
            conn.execute('UPDATE ideas SET status=?, dismissal_reason=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                         (new_status, idea_id))
        conn.commit()

        updated = dict(conn.execute('SELECT * FROM ideas WHERE id=?', (idea_id,)).fetchone())
        conn.close()

        # Discord notifications on complete or dismiss
        link = _idea_link(idea_id)
        if new_status == 'completed':
            msg = f"✅ **Idea Completed: {idea['title']}**\n{link}"
            send_discord_message(FEATURE_REQUESTS_CHANNEL, msg)
            # DM submitter
            submitter = conn if False else get_db().execute(
                'SELECT discord_id FROM users WHERE id=?', (idea['submitted_by'],)).fetchone()
            if submitter and submitter['discord_id']:
                send_discord_dm(submitter['discord_id'],
                    f"✅ Your idea **\"{idea['title']}\"** has been marked as completed! Check it out: {link}")
        elif new_status == 'dismissed':
            reason = data.get('dismissal_reason', '').strip()
            msg = f"🚫 **Idea Dismissed: {idea['title']}**\nReason: {reason}\n{link}"
            send_discord_message(FEATURE_REQUESTS_CHANNEL, msg)
            # DM submitter
            db2 = get_db()
            submitter = db2.execute('SELECT discord_id FROM users WHERE id=?', (idea['submitted_by'],)).fetchone()
            if submitter and submitter['discord_id']:
                send_discord_dm(submitter['discord_id'],
                    f"Your idea **\"{idea['title']}\"** was dismissed.\nReason: {reason}\n{link}")
            db2.close()

        return jsonify(_format_idea(get_db(), updated, user['id']))

    # Edit title/body — submitter or admin, not allowed when completed/dismissed
    if 'title' in data or 'body' in data:
        if not (is_submitter or is_admin_user):
            conn.close()
            return jsonify({'error': 'Not authorized to edit this idea'}), 403
        if idea['status'] in ('completed', 'dismissed'):
            conn.close()
            return jsonify({'error': 'Cannot edit a completed or dismissed idea'}), 400
        new_title = (data.get('title') or idea['title']).strip()
        new_body  = (data.get('body')  or idea['body']).strip()
        conn.execute('UPDATE ideas SET title=?, body=?, edited=1, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                     (new_title, new_body, idea_id))
        conn.commit()

    updated = dict(conn.execute('SELECT * FROM ideas WHERE id=?', (idea_id,)).fetchone())
    result = _format_idea(conn, updated, user['id'])
    conn.close()
    return jsonify(result)

@app.route('/api/ideas/<int:idea_id>/vote', methods=['POST'])
def toggle_vote(idea_id):
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Login required'}), 401
    if not user.get('team_id'):
        return jsonify({'error': 'You must be assigned to a team to vote'}), 403

    conn = get_db()
    idea = conn.execute('SELECT * FROM ideas WHERE id=?', (idea_id,)).fetchone()
    if not idea:
        conn.close()
        return jsonify({'error': 'Idea not found'}), 404

    existing = conn.execute('SELECT 1 FROM idea_votes WHERE idea_id=? AND user_id=?', (idea_id, user['id'])).fetchone()
    if existing:
        conn.execute('DELETE FROM idea_votes WHERE idea_id=? AND user_id=?', (idea_id, user['id']))
        voted = False
    else:
        conn.execute('INSERT INTO idea_votes (idea_id, user_id) VALUES (?, ?)', (idea_id, user['id']))
        voted = True
    conn.commit()
    score = _idea_vote_score(conn, idea_id)
    conn.close()
    return jsonify({'voted': voted, 'score': score})

@app.route('/api/ideas/<int:idea_id>/reset-votes', methods=['POST'])
def reset_votes(idea_id):
    user = get_current_user()
    if not user or ROLE_HIERARCHY.get(user.get('role', ''), 0) < ROLE_HIERARCHY['assistant_commissioner']:
        return jsonify({'error': 'Admin access required'}), 403
    conn = get_db()
    idea = conn.execute('SELECT id FROM ideas WHERE id=?', (idea_id,)).fetchone()
    if not idea:
        conn.close()
        return jsonify({'error': 'Idea not found'}), 404
    conn.execute('DELETE FROM idea_votes WHERE idea_id=?', (idea_id,))
    conn.commit()
    conn.close()
    log_audit(user['id'], 'reset_idea_votes', 'idea', idea_id, None, None)
    return jsonify({'success': True, 'score': 0})


# ── DB Download/Upload (commissioner only) ────────────────────────────────
@app.route('/admin/download-db', methods=['GET'])
def download_db():
    from database import DB_PATH
    from flask import send_file
    # Accept either a logged-in commissioner session OR the DB_UPLOAD_TOKEN header
    token = request.headers.get('X-Upload-Token', '')
    expected = os.environ.get('DB_UPLOAD_TOKEN', '')
    token_ok = expected and token == expected
    if not token_ok:
        # Fall back to checking logged-in commissioner role
        user = get_current_user()
        if not user or ROLE_HIERARCHY.get(user.get('role', ''), 0) < ROLE_HIERARCHY['commissioner']:
            return jsonify({'error': 'Unauthorized'}), 401
    return send_file(DB_PATH, as_attachment=True, download_name='nml-backup.db',
                     mimetype='application/octet-stream')

@app.route('/admin/upload-db', methods=['POST'])
def upload_db():
    import shutil
    token = request.headers.get('X-Upload-Token', '')
    expected = os.environ.get('DB_UPLOAD_TOKEN', '')
    if not expected or token != expected:
        return jsonify({'error': 'Unauthorized'}), 401
    f = request.files.get('db')
    if not f:
        return jsonify({'error': 'No file'}), 400
    from database import DB_PATH
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    tmp = DB_PATH + '.upload'
    f.save(tmp)
    shutil.move(tmp, DB_PATH)
    # Remove stale WAL/SHM files so SQLite doesn't replay old transactions on top of the new DB
    for ext in ('-wal', '-shm'):
        stale = DB_PATH + ext
        if os.path.exists(stale):
            os.remove(stale)
    return jsonify({'success': True, 'message': 'Database replaced successfully'})

@app.route('/')
@app.route('/app')
@app.route('/nml-app.html')
def serve_frontend():
    base_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    html_path = os.path.join(base_dir, 'nml-app.html')
    print(f"[DEBUG] base_dir  = {base_dir}")
    print(f"[DEBUG] html_path = {html_path}")
    print(f"[DEBUG] exists    = {os.path.exists(html_path)}")
    if os.path.exists(html_path):
        from flask import send_from_directory
        return send_from_directory(base_dir, 'nml-app.html')
    return f'nml-app.html not found — looking at: {html_path}', 404


# ── League Data Backup ────────────────────────────────────────────────────────

def generate_backup_xlsx():
    """Generate a multi-sheet Excel backup of all important league data."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from datetime import datetime

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default blank sheet

    HDR_FONT = Font(bold=True, color='FFFFFF')
    HDR_FILL = PatternFill('solid', fgColor='1a1a2e')

    def style_header_row(ws):
        for cell in ws[1]:
            cell.font = HDR_FONT
            cell.fill = HDR_FILL
            cell.alignment = Alignment(horizontal='center')

    def auto_width(ws):
        for col in ws.columns:
            max_len = max((len(str(c.value or '')) for c in col), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)

    conn = get_db()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M PT')

    # ── Sheet 1: Players ────────────────────────────────────────────────────
    ws = wb.create_sheet('Players')
    ws.append(['Name', 'Position', 'Team', 'OVR', 'Age', 'Dev Trait',
               'Salary', 'Yrs Left', 'Cap Hit', 'Jersey #', 'Yrs Pro',
               'NFL Team', 'Height', 'Weight', 'Is FA'])
    style_header_row(ws)

    DEV_LABELS = {0: '', 1: 'Normal', 2: 'Star', 3: 'Superstar', 4: 'X-Factor'}
    players = conn.execute('''
        SELECT p.first_name || ' ' || p.last_name AS name,
               p.position,
               COALESCE(t.short_name, 'Free Agent') AS team,
               p.overall_rating, p.age,
               p.dev_trait,
               p.contract_salary, p.contract_years_left, p.cap_hit,
               p.jersey_num, p.years_pro, p.nfl_team,
               p.height, p.weight,
               CASE WHEN p.is_free_agent = 1 OR p.nml_team_id IS NULL THEN 'Yes' ELSE 'No' END AS is_fa
        FROM players p
        LEFT JOIN teams t ON p.nml_team_id = t.id
        ORDER BY t.short_name NULLS LAST, p.position, p.overall_rating DESC
    ''').fetchall()
    for p in players:
        row = list(p)
        row[5] = DEV_LABELS.get(row[5] or 0, '')  # dev_trait → label
        ws.append(row)
    auto_width(ws)
    ws.freeze_panes = 'A2'

    # ── Sheet 2: Draft Picks ─────────────────────────────────────────────────
    ws = wb.create_sheet('Draft Picks')
    ws.append(['Year', 'Round', 'Overall #', 'Original Team', 'Current Owner',
               'Type', 'Used?', 'Player Drafted', 'Position Drafted'])
    style_header_row(ws)

    picks = conn.execute('''
        SELECT dp.year,
               dp.round,
               dp.overall_order,
               ot.short_name AS orig_team,
               ct.short_name AS curr_team,
               CASE WHEN dp.is_comp_pick = 1 THEN 'Comp' ELSE 'Regular' END AS pick_type,
               CASE WHEN ds.id IS NOT NULL THEN 'Yes' ELSE 'No' END AS used,
               COALESCE(p.first_name || ' ' || p.last_name, ds.write_in_name, '') AS player_drafted,
               COALESCE(p.position, ds.write_in_position, '') AS pos_drafted
        FROM draft_picks dp
        LEFT JOIN teams ot ON dp.original_owner_id = ot.id
        LEFT JOIN teams ct ON dp.current_owner_id = ct.id
        LEFT JOIN draft_selections ds ON ds.draft_pick_id = dp.id
        LEFT JOIN players p ON ds.player_id = p.id
        ORDER BY dp.year, dp.round, dp.overall_order NULLS LAST
    ''').fetchall()
    for pk in picks:
        ws.append(list(pk))
    auto_width(ws)
    ws.freeze_panes = 'A2'

    # ── Sheet 3: Trades ──────────────────────────────────────────────────────
    ws = wb.create_sheet('Trades')
    ws.append(['Trade #', 'Date Completed', 'Team 1', 'Team 2',
               'Team 1 Received', 'Team 2 Received', 'Notes'])
    style_header_row(ws)

    trades = conn.execute('''
        SELECT tr.id,
               COALESCE(tr.completed_at, tr.team1_confirmed_at) AS completed,
               t1.short_name AS team1,
               t2.short_name AS team2,
               tr.notes
        FROM trades tr
        JOIN teams t1 ON t1.id = tr.team1_id
        JOIN teams t2 ON t2.id = tr.team2_id
        WHERE tr.status = 'completed'
        ORDER BY completed DESC
    ''').fetchall()

    for tr in trades:
        assets = conn.execute('''
            SELECT ta.asset_type, ta.to_team_id,
                   ta.from_team_id,
                   p.first_name || ' ' || p.last_name AS player_name,
                   p.position,
                   dp.year, dp.round,
                   ot.short_name AS orig_team
            FROM trade_assets ta
            LEFT JOIN players p ON ta.player_id = p.id
            LEFT JOIN draft_picks dp ON ta.pick_id = dp.id
            LEFT JOIN teams ot ON dp.original_owner_id = ot.id
            WHERE ta.trade_id = ?
        ''', (tr['id'],)).fetchall()

        team1_gets, team2_gets = [], []
        trade_row = conn.execute(
            'SELECT team1_id, team2_id FROM trades WHERE id = ?', (tr['id'],)
        ).fetchone()

        for a in assets:
            if a['asset_type'] == 'player':
                label = f"{a['player_name']} ({a['position']})"
            else:
                label = f"{a['year']} {a['round']}{'st' if a['round']==1 else 'nd' if a['round']==2 else 'rd' if a['round']==3 else 'th'} ({a['orig_team']})"
            if a['to_team_id'] == trade_row['team1_id']:
                team1_gets.append(label)
            else:
                team2_gets.append(label)

        completed = str(tr['completed'] or '')[:10]
        ws.append([
            tr['id'],
            completed,
            tr['team1'],
            tr['team2'],
            ', '.join(team1_gets) or '—',
            ', '.join(team2_gets) or '—',
            tr['notes'] or ''
        ])
    auto_width(ws)
    ws.freeze_panes = 'A2'

    # ── Sheet 4: Team Rosters + Cap ──────────────────────────────────────────
    ws = wb.create_sheet('Team Rosters & Cap')
    ws.append(['Team', 'Player', 'Position', 'OVR', 'Age', 'Dev Trait',
               'Salary', 'Yrs Left', 'Cap Hit'])
    style_header_row(ws)

    rosters = conn.execute('''
        SELECT t.short_name AS team,
               p.first_name || ' ' || p.last_name AS player,
               p.position, p.overall_rating, p.age, p.dev_trait,
               p.contract_salary, p.contract_years_left, p.cap_hit
        FROM players p
        JOIN teams t ON p.nml_team_id = t.id
        WHERE p.is_free_agent = 0 AND p.nml_team_id IS NOT NULL
        ORDER BY t.short_name, p.position, p.overall_rating DESC
    ''').fetchall()
    for r in rosters:
        row = list(r)
        row[5] = DEV_LABELS.get(row[5] or 0, '')
        ws.append(row)
    auto_width(ws)
    ws.freeze_panes = 'A2'

    conn.close()

    # Add generated timestamp as a named range / doc property
    wb.properties.description = f'NML League Backup — generated {now_str}'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


@app.route('/api/admin/backup-xlsx')
@require_role('assistant_commissioner')
def download_backup_xlsx():
    """Download the latest league data backup as an Excel file."""
    from datetime import datetime
    buf = generate_backup_xlsx()
    filename = f"nml_backup_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


# ── Draft Suite ──────────────────────────────────────────────────────────────

DRAFT_YEAR = 2026

def _norm_name(name):
    """Normalize player name for fuzzy matching."""
    import unicodedata, re
    if not name: return ''
    name = unicodedata.normalize('NFKD', str(name)).encode('ascii','ignore').decode('ascii')
    name = re.sub(r'[^a-z ]', '', name.lower())
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', name).strip()
    return name

# ── Prospect Board ────────────────────────────────────────────────────────────

@app.route('/api/draft-prospects', methods=['GET'])
@require_auth
def get_draft_prospects():
    year   = request.args.get('year', DRAFT_YEAR, type=int)
    pos    = request.args.get('position', '')
    q      = request.args.get('q', '').strip()
    limit  = request.args.get('limit', 500, type=int)
    offset = request.args.get('offset', 0, type=int)

    conn = get_db()
    sql  = 'SELECT dp.*, t.full_name AS nml_team_name FROM draft_prospects dp LEFT JOIN teams t ON dp.nml_team_id = t.id WHERE dp.year=?'
    params = [year]
    if pos:
        sql += ' AND dp.position=?'; params.append(pos)
    if q:
        sql += ' AND dp.name LIKE ?'; params.append(f'%{q}%')
    sql += ' ORDER BY COALESCE(dp.personal_rank, dp.consensus_rank, dp.drafttek_rank, 9999), dp.name LIMIT ? OFFSET ?'
    params += [limit, offset]
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/draft-prospects/<int:pid>', methods=['GET'])
@require_auth
def get_draft_prospect(pid):
    conn = get_db()
    row  = conn.execute('SELECT dp.*, t.full_name AS nml_team_name FROM draft_prospects dp LEFT JOIN teams t ON dp.nml_team_id = t.id WHERE dp.id=?', (pid,)).fetchone()
    conn.close()
    if not row: return jsonify({'error': 'Not found'}), 404
    return jsonify(dict(row))


@app.route('/api/draft-prospects/<int:pid>', methods=['PATCH'])
@require_role('creator')
def update_draft_prospect(pid):
    data    = request.get_json() or {}
    allowed = {'personal_rank','notes','position','school','birth_date',
               'height','weight','forty_combine','forty_proday','bench',
               'vertical','broad','three_cone','shuttle','ras','ras_link',
               'ten_combine','twenty_combine','hand_combine','arm_combine','wing_combine',
               'height_proday','weight_proday','ten_proday','twenty_proday',
               'hand_proday','arm_proday','wing_proday','bench_proday',
               'vertical_proday','broad_proday','three_cone_proday','shuttle_proday',
               'consensus_rank','pff_rank','espn_rank','drafttek_rank',
               'brugler_rank','harmon_wr_rank','thorn_ol_score',
               'nfl_team','nfl_round','nfl_pick','nfl_overall',
               'nml_team_id','nml_round','nml_pick'}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates: return jsonify({'error': 'Nothing to update'}), 400
    conn = get_db()
    # Capture state before update so undo can remove the old nfl_draft_history row
    old_row = conn.execute('SELECT * FROM draft_prospects WHERE id=?', (pid,)).fetchone() \
              if 'nfl_overall' in updates else None
    sets = ', '.join(f'{k}=?' for k in updates)
    conn.execute(f"UPDATE draft_prospects SET {sets}, updated_at=datetime('now') WHERE id=?",
                 list(updates.values()) + [pid])
    # Sync to nfl_draft_history when nfl_overall changes
    if 'nfl_overall' in updates:
        new_overall = updates.get('nfl_overall')
        if new_overall:
            prospect = conn.execute('SELECT * FROM draft_prospects WHERE id=?', (pid,)).fetchone()
            conn.execute('''
                INSERT INTO nfl_draft_history
                    (year, round, pick, overall, nfl_team, player_name, position, school)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(year, overall) DO UPDATE SET
                    round=excluded.round, pick=excluded.pick,
                    nfl_team=excluded.nfl_team, player_name=excluded.player_name,
                    position=excluded.position, school=excluded.school
            ''', (prospect['year'], prospect['nfl_round'], prospect['nfl_pick'],
                  prospect['nfl_overall'], prospect['nfl_team'] or '',
                  prospect['name'], prospect['position'] or '', prospect['school'] or ''))
        else:
            # Pick cleared (undo) — remove from history using the old overall
            if old_row and old_row['nfl_overall']:
                conn.execute('DELETE FROM nfl_draft_history WHERE year=? AND overall=?',
                             (old_row['year'], old_row['nfl_overall']))
    conn.commit()
    row = conn.execute('SELECT dp.*, t.full_name AS nml_team_name FROM draft_prospects dp LEFT JOIN teams t ON dp.nml_team_id = t.id WHERE dp.id=?', (pid,)).fetchone()
    conn.close()
    return jsonify(dict(row))


@app.route('/api/draft-prospects', methods=['POST'])
@require_role('creator')
def create_draft_prospect():
    """Add a single prospect manually."""
    data = request.get_json() or {}
    name = data.get('name','').strip()
    if not name: return jsonify({'error': 'name required'}), 400
    year = data.get('year', DRAFT_YEAR)
    conn = get_db()
    cur = conn.execute('''INSERT INTO draft_prospects (year,name,position,school,birth_date,
        height,weight,consensus_rank,personal_rank,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (year, name, data.get('position',''), data.get('school',''),
         data.get('birth_date'), data.get('height'), data.get('weight'),
         data.get('consensus_rank'), data.get('personal_rank'), data.get('notes')))
    conn.commit()
    row = conn.execute('SELECT * FROM draft_prospects WHERE id=?', (cur.lastrowid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


# ── Draft Board (personal rankings) ──────────────────────────────────────────

@app.route('/api/draft-board', methods=['GET'])
@require_role('creator')
def get_draft_board():
    year = request.args.get('year', DRAFT_YEAR, type=int)
    conn = get_db()
    cur = get_current_user()
    rows = conn.execute('''
        SELECT dbe.*, dp.name, dp.position, dp.school, dp.consensus_rank,
               dp.ras, dp.birth_date, dp.height, dp.weight,
               dp.forty_combine, dp.forty_proday,
               dp.ten_combine, dp.ten_proday,
               dp.arm_combine, dp.arm_proday,
               dp.bench, dp.bench_proday,
               dp.shuttle, dp.shuttle_proday,
               dp.three_cone,
               dp.harmon_wr_rank, dp.thorn_ol_score, dp.brugler_rank,
               dp.espn_rank, dp.drafttek_rank,
               dp.nfl_team, dp.nfl_round, dp.nfl_overall,
               dp.nml_team_id, dp.nml_round, dp.nml_pick,
               t.full_name AS nml_team_name, t.short_name AS nml_team_short
        FROM draft_board_entries dbe
        JOIN draft_prospects dp ON dbe.prospect_id = dp.id
        LEFT JOIN teams t ON dp.nml_team_id = t.id
        WHERE dbe.year=? AND dbe.user_id=?
        ORDER BY dbe.tier, COALESCE(dbe.board_rank, 9999), dp.name
    ''', (year, cur['id'])).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/draft-board/<int:prospect_id>', methods=['PUT'])
@require_role('creator')
def upsert_draft_board_entry(prospect_id):
    data = request.get_json() or {}
    year = data.get('year', DRAFT_YEAR)
    cur = get_current_user()
    conn = get_db()
    conn.execute('''INSERT INTO draft_board_entries (year, user_id, prospect_id, board_rank, tier, notes, updated_at)
        VALUES (?,?,?,?,?,?,datetime('now'))
        ON CONFLICT(year,user_id,prospect_id) DO UPDATE SET
            board_rank=excluded.board_rank,
            tier=excluded.tier,
            notes=excluded.notes,
            updated_at=datetime('now')''',
        (year, cur['id'], prospect_id,
         data.get('board_rank'), data.get('tier'), data.get('notes','')))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/draft-board/<int:prospect_id>', methods=['DELETE'])
@require_role('creator')
def delete_draft_board_entry(prospect_id):
    year = request.args.get('year', DRAFT_YEAR, type=int)
    cur = get_current_user()
    conn = get_db()
    conn.execute('DELETE FROM draft_board_entries WHERE year=? AND user_id=? AND prospect_id=?',
                 (year, cur['id'], prospect_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/draft-board/populate', methods=['POST'])
@require_role('creator')
def populate_draft_board():
    """Auto-populate the big board from consensus rankings."""
    BB_POS_GROUP = {
        'QB':'QB',
        'HB':'RB','RB':'RB','FB':'RB',
        'WR':'WR',
        'TE':'TE',
        'OT':'OT','LT':'OT','RT':'OT',
        'OG':'OG','LG':'OG','RG':'OG','IOL':'OG',
        'C':'C',
        'DT':'DT','NT':'DT','IDL':'DT',
        'EDGE':'Edge','LE':'Edge','RE':'Edge','LEDGE':'Edge','REDGE':'Edge','DE':'Edge',
        'LB':'LB','MLB':'LB','ILB':'LB','OLB':'LB','LOLB':'LB','ROLB':'LB',
        'CB':'CB',
        'FS':'S','SS':'S','S':'S','DB':'S',
    }
    def rank_to_tier(rank):
        if rank is None: return 11
        if rank <= 5:   return 1
        if rank <= 32:  return 2
        if rank <= 64:  return 3
        if rank <= 100: return 4
        if rank <= 140: return 5
        if rank <= 180: return 6
        if rank <= 220: return 7
        if rank <= 260: return 8
        if rank <= 300: return 9
        if rank <= 350: return 10
        return 11

    data = request.get_json() or {}
    year           = data.get('year', DRAFT_YEAR)
    overwrite      = data.get('overwrite', False)
    consensus_type = data.get('consensus_type', None)   # None → use draft_prospects.consensus_rank
    cur  = get_current_user()
    conn = get_db()

    if overwrite:
        conn.execute('DELETE FROM draft_board_entries WHERE year=? AND user_id=?', (year, cur['id']))

    # ── Build rank lookup ─────────────────────────────────────────────────────
    # If a consensus_type is specified and data exists in consensus_rankings, use it.
    # Keys: prospect_id → consensus_rank. Falls back per-prospect to draft_prospects.consensus_rank.
    consensus_rank_override = {}
    if consensus_type:
        cr_rows = conn.execute(
            '''SELECT cr.consensus_rank, cr.matched_prospect_id
               FROM consensus_rankings cr
               WHERE cr.draft_year=? AND cr.consensus_type=? AND cr.matched_prospect_id IS NOT NULL''',
            (year, consensus_type)
        ).fetchall()
        consensus_rank_override = {r['matched_prospect_id']: r['consensus_rank'] for r in cr_rows}

    prospects = conn.execute(
        "SELECT id, position, consensus_rank FROM draft_prospects WHERE year=? AND (position IS NULL OR position NOT IN ('K','P','LS'))",
        (year,)
    ).fetchall()

    inserted = 0
    for p in prospects:
        pos = (p['position'] or '').strip().upper()
        if pos not in BB_POS_GROUP:
            continue
        # Use consensus_rankings override if available, else fall back to draft_prospects column
        eff_rank   = consensus_rank_override.get(p['id'], p['consensus_rank'])
        tier       = rank_to_tier(eff_rank)
        board_rank = eff_rank or 9999
        try:
            conn.execute(
                '''INSERT OR IGNORE INTO draft_board_entries
                   (year, user_id, prospect_id, tier, board_rank, updated_at)
                   VALUES (?,?,?,?,?,datetime('now'))''',
                (year, cur['id'], p['id'], tier, board_rank)
            )
            inserted += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    source = f'{consensus_type} consensus ({len(consensus_rank_override)} overrides)' if consensus_rank_override else 'draft_prospects.consensus_rank'
    return jsonify({'ok': True, 'inserted': inserted, 'source': source})


# ── Mock Drafts ───────────────────────────────────────────────────────────────

@app.route('/api/mock-drafts', methods=['GET'])
@require_auth
def get_mock_drafts():
    year = request.args.get('year', DRAFT_YEAR, type=int)
    cur = get_current_user()
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM mock_drafts WHERE year=? AND user_id=? ORDER BY updated_at DESC',
        (year, cur['id'])).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/mock-drafts', methods=['POST'])
@require_auth
def create_mock_draft():
    data = request.get_json() or {}
    name = data.get('name','').strip() or 'Mock Draft'
    year = data.get('year', DRAFT_YEAR)
    cur = get_current_user()
    conn = get_db()
    cur_row = conn.execute('''INSERT INTO mock_drafts (year, user_id, name, is_published)
        VALUES (?,?,?,0)''', (year, cur['id'], name))
    conn.commit()
    row = conn.execute('SELECT * FROM mock_drafts WHERE id=?', (cur_row.lastrowid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route('/api/mock-drafts/<int:mid>', methods=['GET'])
@require_auth
def get_mock_draft(mid):
    conn = get_db()
    md   = conn.execute('''
        SELECT md.*, u.display_name as username, u.discord_id,
               t.short_name as team_short_name, t.full_name as team_full_name
        FROM mock_drafts md
        JOIN users u ON u.id = md.user_id
        LEFT JOIN teams t ON t.id = u.team_id
        WHERE md.id=?
    ''', (mid,)).fetchone()
    if not md: conn.close(); return jsonify({'error': 'Not found'}), 404
    cur = get_current_user()
    # Only owner can see their own mock; non-owners can only see published
    if md['user_id'] != cur['id'] and not md['is_published']:
        conn.close(); return jsonify({'error': 'Forbidden'}), 403
    picks = conn.execute('''
        SELECT mdp.*,
               curr.short_name as current_owner_name,
               COALESCE(p.school, p.college) as school
        FROM mock_draft_picks mdp
        LEFT JOIN draft_picks dp ON dp.year=? AND dp.overall_order=mdp.overall_pick
        LEFT JOIN teams curr ON curr.id=dp.current_owner_id
        LEFT JOIN players p ON p.id=mdp.prospect_id
        WHERE mdp.mock_draft_id=?
        ORDER BY mdp.overall_pick
    ''', (DRAFT_YEAR, mid,)).fetchall()
    conn.close()
    return jsonify({'mock': dict(md), 'picks': [dict(p) for p in picks]})


@app.route('/api/mock-drafts/<int:mid>', methods=['PATCH'])
@require_auth
def update_mock_draft(mid):
    cur = get_current_user()
    conn = get_db()
    md   = conn.execute('SELECT * FROM mock_drafts WHERE id=?', (mid,)).fetchone()
    if not md: conn.close(); return jsonify({'error': 'Not found'}), 404
    if md['user_id'] != cur['id']:
        conn.close(); return jsonify({'error': 'Forbidden'}), 403
    data    = request.get_json() or {}
    allowed = {'name', 'is_published'}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates: conn.close(); return jsonify({'error': 'Nothing to update'}), 400

    was_published = bool(md['is_published'])
    now_published  = bool(updates.get('is_published', was_published))

    sets = ', '.join(f'{k}=?' for k in updates)
    conn.execute(f"UPDATE mock_drafts SET {sets}, updated_at=datetime('now') WHERE id=?",
                 list(updates.values()) + [mid])
    conn.commit()
    row = conn.execute('SELECT * FROM mock_drafts WHERE id=?', (mid,)).fetchone()
    conn.close()

    # Fire Discord notification when newly published
    if not was_published and now_published:
        try:
            _notify_mock_draft_published(dict(row), cur)
        except Exception as e:
            print(f"[Discord] mock draft publish notification failed: {e}")

    return jsonify(dict(row))


@app.route('/api/mock-drafts/<int:mid>', methods=['DELETE'])
@require_auth
def delete_mock_draft(mid):
    cur = get_current_user()
    conn = get_db()
    md   = conn.execute('SELECT user_id FROM mock_drafts WHERE id=?', (mid,)).fetchone()
    if not md: conn.close(); return jsonify({'error': 'Not found'}), 404
    if md['user_id'] != cur['id']:
        conn.close(); return jsonify({'error': 'Forbidden'}), 403
    conn.execute('DELETE FROM mock_draft_picks WHERE mock_draft_id=?', (mid,))
    conn.execute('DELETE FROM mock_drafts WHERE id=?', (mid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/mock-drafts/<int:mid>/picks', methods=['PUT'])
@require_auth
def upsert_mock_pick(mid):
    """Upsert a single pick. Body: {overall_pick, round, pick_in_round, nfl_team, prospect_id, prospect_name, position, notes}"""
    cur = get_current_user()
    conn = get_db()
    md   = conn.execute('SELECT user_id FROM mock_drafts WHERE id=?', (mid,)).fetchone()
    if not md: conn.close(); return jsonify({'error': 'Not found'}), 404
    if md['user_id'] != cur['id']:
        conn.close(); return jsonify({'error': 'Forbidden'}), 403
    data    = request.get_json() or {}
    overall = data.get('overall_pick')
    if not overall: conn.close(); return jsonify({'error': 'overall_pick required'}), 400
    vals = (data.get('round'), data.get('pick_in_round'), data.get('nfl_team',''),
            data.get('prospect_id'), data.get('prospect_name',''),
            data.get('position',''), data.get('notes',''))
    existing = conn.execute(
        'SELECT id FROM mock_draft_picks WHERE mock_draft_id=? AND overall_pick=?',
        (mid, overall)).fetchone()
    if existing:
        conn.execute('''UPDATE mock_draft_picks SET
            round=?, pick_in_round=?, nfl_team=?, prospect_id=?,
            prospect_name=?, position=?, notes=?
            WHERE mock_draft_id=? AND overall_pick=?''',
            vals + (mid, overall))
    else:
        conn.execute('''INSERT INTO mock_draft_picks
            (mock_draft_id, overall_pick, round, pick_in_round, nfl_team, prospect_id, prospect_name, position, notes)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (mid, overall) + vals)
    conn.execute("UPDATE mock_drafts SET updated_at=datetime('now') WHERE id=?", (mid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/mock-drafts/<int:mid>/picks/<int:overall>', methods=['DELETE'])
@require_auth
def delete_mock_pick(mid, overall):
    cur = get_current_user()
    conn = get_db()
    md   = conn.execute('SELECT user_id FROM mock_drafts WHERE id=?', (mid,)).fetchone()
    if not md: conn.close(); return jsonify({'error': 'Not found'}), 404
    if md['user_id'] != cur['id']:
        conn.close(); return jsonify({'error': 'Forbidden'}), 403
    conn.execute('DELETE FROM mock_draft_picks WHERE mock_draft_id=? AND overall_pick=?', (mid, overall))
    conn.execute("UPDATE mock_drafts SET updated_at=datetime('now') WHERE id=?", (mid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/mock-drafts/<int:mid>/reset', methods=['POST'])
@require_auth
def reset_mock_draft(mid):
    """Clear all picks from a mock draft (keeps the mock itself)."""
    cur = get_current_user()
    conn = get_db()
    md   = conn.execute('SELECT user_id FROM mock_drafts WHERE id=?', (mid,)).fetchone()
    if not md: conn.close(); return jsonify({'error': 'Not found'}), 404
    if md['user_id'] != cur['id']:
        conn.close(); return jsonify({'error': 'Forbidden'}), 403
    conn.execute('DELETE FROM mock_draft_picks WHERE mock_draft_id=?', (mid,))
    conn.execute("UPDATE mock_drafts SET updated_at=datetime('now') WHERE id=?", (mid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


def _notify_mock_draft_published(mock, user):
    """Post a Discord message to the general channel when a mock draft is published."""
    conn = get_db()
    team = conn.execute(
        "SELECT short_name FROM teams WHERE discord_user_id=?", (user.get('discord_id',''),)
    ).fetchone()
    channel_row = conn.execute(
        "SELECT value FROM league_settings WHERE key='discord_mockdraft_channel_id'"
    ).fetchone()
    notify_row = conn.execute(
        "SELECT value FROM league_settings WHERE key='discord_mockdraft_notify'"
    ).fetchone()
    conn.close()

    if notify_row and notify_row['value'] != 'true':
        return  # notifications disabled

    channel_id = (channel_row['value'] if channel_row and channel_row['value'] else None) or '172745930951360512'
    owner_label = user.get('display_name') or user.get('discord_username') or 'Unknown'
    if team and team['short_name']:
        owner_label = f"{owner_label}-{team['short_name']}"

    app_url = _app_url()
    mock_name = mock.get('name', 'Mock Draft')
    mock_id   = mock.get('id', '')

    if app_url:
        link_url = f"{app_url}/?mock={mock_id}"
        msg = f"{owner_label} just published a new mock draft - [{mock_name}]({link_url})"
    else:
        msg = f"{owner_label} just published a new mock draft - {mock_name}"

    send_discord_message(channel_id, msg)


@app.route('/api/mock-drafts/published', methods=['GET'])
@require_auth
def get_published_mock_drafts():
    """All published mock drafts across all users, with owner + team info."""
    year = request.args.get('year', DRAFT_YEAR, type=int)
    conn = get_db()
    try:
        rows = conn.execute('''
            SELECT md.id, md.year, md.user_id, md.name, md.is_published,
                   md.created_at, md.updated_at,
                   COALESCE(md.score, NULL) as score,
                   COALESCE(md.hit_3, 0) as hit_3,
                   COALESCE(md.hit_2, 0) as hit_2,
                   COALESCE(md.hit_1, 0) as hit_1,
                   COALESCE(md.scored_at, NULL) as scored_at,
                   u.display_name as username, u.discord_username, u.discord_id,
                   t.short_name as team_short_name, t.full_name as team_full_name
            FROM mock_drafts md
            JOIN users u ON u.id = md.user_id
            LEFT JOIN teams t ON t.id = u.team_id
            WHERE md.is_published = 1 AND md.year = ?
            ORDER BY md.updated_at DESC
        ''', (year,)).fetchall()
    except Exception as e:
        print(f"[published mocks] ERROR: {e}")
        conn.close()
        return jsonify([])
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/mock-drafts/consensus', methods=['GET'])
@require_auth
def get_mock_draft_consensus():
    """For each pick slot, return the most-mocked player across all published mocks."""
    year  = request.args.get('year', DRAFT_YEAR, type=int)
    limit = request.args.get('limit', 6, type=int)
    conn  = get_db()

    total_mocks = conn.execute(
        'SELECT COUNT(*) FROM mock_drafts WHERE is_published=1 AND year=?', (year,)
    ).fetchone()[0]

    if total_mocks == 0:
        conn.close()
        return jsonify({'total_mocks': 0, 'picks': []})

    rows = conn.execute('''
        SELECT
            mdp.overall_pick,
            mdp.pick_in_round,
            mdp.nfl_team,
            mdp.prospect_name,
            mdp.position,
            p.school,
            COUNT(*) as pick_count
        FROM mock_draft_picks mdp
        JOIN mock_drafts md ON md.id = mdp.mock_draft_id
        LEFT JOIN players p ON p.id = mdp.prospect_id
        WHERE md.is_published = 1 AND md.year = ?
          AND mdp.prospect_name IS NOT NULL AND mdp.prospect_name != ''
        GROUP BY mdp.overall_pick, mdp.prospect_id
        ORDER BY mdp.overall_pick ASC, pick_count DESC
    ''', (year,)).fetchall()

    # Keep only the top pick per slot
    seen  = set()
    picks = []
    for row in rows:
        op = row['overall_pick']
        if op not in seen:
            seen.add(op)
            d = dict(row)
            d['total_mocks'] = total_mocks
            picks.append(d)

    conn.close()
    return jsonify({'total_mocks': total_mocks, 'picks': picks[:limit]})


@app.route('/api/admin/mock-drafts/unpublish-all', methods=['POST'])
@require_auth
@require_role('commissioner')
def admin_unpublish_all_mocks():
    """Commissioner: unpublish all mocks for a given year."""
    data = request.get_json() or {}
    year = data.get('year', DRAFT_YEAR)
    conn = get_db()
    conn.execute("UPDATE mock_drafts SET is_published=0 WHERE year=?", (year,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/admin/mock-drafts/<int:mid>/unpublish', methods=['POST'])
@require_auth
@require_role('commissioner')
def admin_unpublish_mock(mid):
    """Commissioner: unpublish a single mock draft."""
    conn = get_db()
    conn.execute("UPDATE mock_drafts SET is_published=0 WHERE id=?", (mid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ─── Draft Review (NMLBot + future user-published) ────────────────────────

@app.route('/api/draft-reviews', methods=['GET'])
@require_auth
def list_draft_reviews():
    """List all visible draft reviews for a year.

    Visible = NMLBot reviews (always) + user reviews that are published OR
    authored by the current user. Sorted: NMLBot first, then by published_at desc
    (chronological — published reviews appear in publish order).
    """
    year = request.args.get('year', DRAFT_YEAR, type=int)
    cur = get_current_user()
    conn = get_db()
    rows = conn.execute('''
        SELECT dr.*, u.display_name AS author_display_name, u.discord_id AS author_discord_id
        FROM draft_reviews dr
        LEFT JOIN users u ON u.id = dr.author_user_id
        WHERE dr.year = ?
          AND (dr.author_user_id IS NULL
               OR dr.is_published = 1
               OR dr.author_user_id = ?)
        ORDER BY
          CASE WHEN dr.author_user_id IS NULL THEN 0 ELSE 1 END,
          dr.published_at ASC,
          dr.created_at ASC
    ''', (year, cur['id'])).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d['is_nmlbot'] = (d.get('author_user_id') is None)
        out.append(d)
    return jsonify(out)


@app.route('/api/draft-reviews/<int:rid>', methods=['GET'])
@require_auth
def get_draft_review(rid):
    """Fetch a single draft review with all team grades + picks.

    Visibility: NMLBot reviews and published reviews are visible to anyone.
    Drafts (unpublished user reviews) are only visible to their author.
    """
    cur = get_current_user()
    conn = get_db()
    rev = conn.execute('''
        SELECT dr.*, u.display_name AS author_display_name, u.discord_id AS author_discord_id
        FROM draft_reviews dr
        LEFT JOIN users u ON u.id = dr.author_user_id
        WHERE dr.id = ?
    ''', (rid,)).fetchone()
    if not rev:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    rev = dict(rev)
    is_nmlbot = (rev.get('author_user_id') is None)
    if (not is_nmlbot
            and not rev.get('is_published')
            and rev.get('author_user_id') != cur['id']):
        conn.close()
        return jsonify({'error': 'Forbidden'}), 403

    rev['is_nmlbot'] = is_nmlbot

    # Pull team grades (joined with team name).
    grade_rows = conn.execute('''
        SELECT g.*, t.short_name AS team_short_name, t.full_name AS team_full_name
        FROM draft_review_team_grades g
        JOIN teams t ON t.id = g.team_id
        WHERE g.review_id = ?
        ORDER BY
          CASE WHEN g.league_rank IS NULL THEN 1 ELSE 0 END,
          g.league_rank ASC,
          t.short_name ASC
    ''', (rid,)).fetchall()

    # Pull all picks for this review in one query, group by team.
    pick_rows = conn.execute('''
        SELECT * FROM draft_review_picks
        WHERE review_id = ?
        ORDER BY team_id, overall_pick
    ''', (rid,)).fetchall()
    picks_by_team = {}
    for p in pick_rows:
        d = dict(p)
        picks_by_team.setdefault(d['team_id'], []).append(d)

    team_grades = []
    for g in grade_rows:
        d = dict(g)
        # Parse JSON-encoded unfilled_needs back into a list.
        try:
            d['unfilled_needs'] = json.loads(d['unfilled_needs']) if d.get('unfilled_needs') else []
        except (TypeError, ValueError):
            d['unfilled_needs'] = []
        d['did_not_participate'] = (d.get('final_grade') is None)
        d['picks'] = picks_by_team.get(d['team_id'], [])
        team_grades.append(d)

    rev['team_grades'] = team_grades
    conn.close()
    return jsonify(rev)


@app.route('/api/draft-reviews', methods=['POST'])
@require_auth
def create_draft_review():
    """Create a new user review for the year. Clones the NMLBot review's
    grades + picks as a starting baseline so the user only edits what they
    disagree with. One review per user per year — repeat calls return 409.
    """
    data = request.get_json() or {}
    year = int(data.get('year', DRAFT_YEAR))
    cur = get_current_user()
    conn = get_db()
    # Enforce one-per-user-per-year.
    existing = conn.execute('''
        SELECT id FROM draft_reviews
        WHERE year=? AND author_user_id=?
    ''', (year, cur['id'])).fetchone()
    if existing:
        conn.close()
        return jsonify({'error': 'You already have a review for this year', 'id': existing['id']}), 409

    # Find the NMLBot review to clone from.
    src = conn.execute('''
        SELECT id FROM draft_reviews
        WHERE year=? AND author_user_id IS NULL
        ORDER BY id LIMIT 1
    ''', (year,)).fetchone()
    if not src:
        conn.close()
        return jsonify({'error': 'NMLBot review not found for that year — cannot clone'}), 404

    label = (cur.get('display_name') or cur.get('discord_username') or 'User').strip()[:64]
    cur_row = conn.execute('''
        INSERT INTO draft_reviews (year, author_user_id, author_label, is_published)
        VALUES (?, ?, ?, 0)
    ''', (year, cur['id'], label))
    new_id = cur_row.lastrowid

    # Clone team grades from NMLBot.
    conn.execute('''
        INSERT INTO draft_review_team_grades (
            review_id, team_id, league_rank,
            value_grade, need_grade, talent_grade, final_grade,
            blurb, best_pick_overall, worst_pick_overall,
            best_pick_text, worst_pick_text,
            looking_ahead, unfilled_needs
        )
        SELECT
            ?, team_id, league_rank,
            value_grade, need_grade, talent_grade, final_grade,
            blurb, best_pick_overall, worst_pick_overall,
            best_pick_text, worst_pick_text,
            looking_ahead, unfilled_needs
        FROM draft_review_team_grades
        WHERE review_id = ?
    ''', (new_id, src['id']))

    # Clone picks (per-pick rows — useful to keep so the user's review is self-contained).
    conn.execute('''
        INSERT INTO draft_review_picks (
            review_id, team_id, overall_pick, round, pick_in_round,
            player_id, player_name, position,
            nml_rank, nfl_consensus_rank, nfl_actual_slot,
            value_delta, pick_grade, note
        )
        SELECT
            ?, team_id, overall_pick, round, pick_in_round,
            player_id, player_name, position,
            nml_rank, nfl_consensus_rank, nfl_actual_slot,
            value_delta, pick_grade, note
        FROM draft_review_picks
        WHERE review_id = ?
    ''', (new_id, src['id']))

    conn.commit()
    row = conn.execute('SELECT * FROM draft_reviews WHERE id=?', (new_id,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route('/api/draft-reviews/<int:rid>', methods=['PATCH'])
@require_auth
def update_draft_review(rid):
    """Update a user's own review (publish/unpublish, rename label).

    Whitelisted fields: is_published, author_label.
    Author check enforced — users can't touch others' reviews or NMLBot's.
    """
    data = request.get_json() or {}
    cur = get_current_user()
    conn = get_db()
    rev = conn.execute('SELECT * FROM draft_reviews WHERE id=?', (rid,)).fetchone()
    if not rev:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    if rev['author_user_id'] != cur['id']:
        conn.close()
        return jsonify({'error': 'Forbidden'}), 403

    sets, args = [], []
    if 'is_published' in data:
        new_state = 1 if data['is_published'] else 0
        sets.append('is_published=?')
        args.append(new_state)
        if new_state == 1 and not rev['published_at']:
            sets.append("published_at=datetime('now')")
    if 'author_label' in data:
        sets.append('author_label=?')
        args.append(str(data['author_label'])[:64])
    if not sets:
        conn.close()
        return jsonify({'error': 'No editable fields supplied'}), 400
    sets.append("updated_at=datetime('now')")
    args.append(rid)
    conn.execute(f'UPDATE draft_reviews SET {", ".join(sets)} WHERE id=?', args)
    conn.commit()
    row = conn.execute('SELECT * FROM draft_reviews WHERE id=?', (rid,)).fetchone()
    conn.close()
    return jsonify(dict(row))


@app.route('/api/draft-reviews/<int:rid>', methods=['DELETE'])
@require_auth
def delete_draft_review(rid):
    """Delete a user's own review (cascades to grades + picks)."""
    cur = get_current_user()
    conn = get_db()
    rev = conn.execute('SELECT * FROM draft_reviews WHERE id=?', (rid,)).fetchone()
    if not rev:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    if rev['author_user_id'] != cur['id']:
        conn.close()
        return jsonify({'error': 'Forbidden'}), 403
    conn.execute('DELETE FROM draft_reviews WHERE id=?', (rid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/draft-review-team-grades/<int:gid>', methods=['PATCH'])
@require_auth
def update_draft_review_team_grade(gid):
    """Update a single team's grade row in a user's review.

    Whitelisted fields: value_grade, need_grade, talent_grade, final_grade,
    blurb, best_pick_overall, worst_pick_overall, best_pick_text,
    worst_pick_text, looking_ahead, unfilled_needs.

    Auth: the parent review's author_user_id must match current user. NMLBot
    rows (author_user_id IS NULL) are NEVER editable via this endpoint.
    """
    data = request.get_json() or {}
    cur = get_current_user()
    conn = get_db()
    row = conn.execute('''
        SELECT g.*, dr.author_user_id, dr.id AS review_id
        FROM draft_review_team_grades g
        JOIN draft_reviews dr ON dr.id = g.review_id
        WHERE g.id = ?
    ''', (gid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    if row['author_user_id'] is None or row['author_user_id'] != cur['id']:
        conn.close()
        return jsonify({'error': 'Forbidden'}), 403

    allowed_int = {'value_grade', 'need_grade', 'talent_grade', 'final_grade',
                   'best_pick_overall', 'worst_pick_overall'}
    allowed_text = {'blurb', 'best_pick_text', 'worst_pick_text', 'looking_ahead'}
    sets, args = [], []
    for k, v in data.items():
        if k in allowed_int:
            sets.append(f'{k}=?')
            args.append(int(v) if v is not None else None)
        elif k in allowed_text:
            sets.append(f'{k}=?')
            args.append(str(v) if v is not None else None)
        elif k == 'unfilled_needs':
            # Stored as JSON-encoded list of strings.
            try:
                if isinstance(v, list):
                    payload = json.dumps([str(x)[:32] for x in v])
                elif isinstance(v, str):
                    parsed = json.loads(v)
                    payload = json.dumps([str(x)[:32] for x in parsed])
                else:
                    payload = '[]'
                sets.append('unfilled_needs=?')
                args.append(payload)
            except (TypeError, ValueError):
                pass
    # Validate grade ranges 1-5 (where set).
    grade_keys = {'value_grade', 'need_grade', 'talent_grade', 'final_grade'}
    for k in grade_keys:
        if k in data and data[k] is not None:
            try:
                n = int(data[k])
                if n < 1 or n > 5:
                    conn.close()
                    return jsonify({'error': f'{k} must be 1-5'}), 400
            except (TypeError, ValueError):
                conn.close()
                return jsonify({'error': f'{k} must be an integer'}), 400
    if not sets:
        conn.close()
        return jsonify({'error': 'No editable fields supplied'}), 400
    sets.append("updated_at=datetime('now')")
    args.append(gid)
    conn.execute(f'UPDATE draft_review_team_grades SET {", ".join(sets)} WHERE id=?', args)
    # Bump parent review's updated_at too.
    conn.execute("UPDATE draft_reviews SET updated_at=datetime('now') WHERE id=?", (row['review_id'],))
    conn.commit()
    out = conn.execute('SELECT * FROM draft_review_team_grades WHERE id=?', (gid,)).fetchone()
    conn.close()
    res = dict(out)
    try:
        res['unfilled_needs'] = json.loads(res['unfilled_needs']) if res.get('unfilled_needs') else []
    except (TypeError, ValueError):
        res['unfilled_needs'] = []
    return jsonify(res)


# ─── End Draft Review ─────────────────────────────────────────────────────


@app.route('/api/nml-draft-results', methods=['GET'])
@require_auth
def get_nml_draft_results():
    """Return entered actual NML draft results for scoring."""
    year = request.args.get('year', DRAFT_YEAR, type=int)
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM nml_draft_results WHERE season_year=? ORDER BY overall_pick', (year,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/nml-draft-results', methods=['POST'])
@require_auth
@require_role('commissioner')
def upsert_nml_draft_result():
    """Commissioner: upsert one actual NML draft pick result."""
    data    = request.get_json() or {}
    year    = data.get('season_year', DRAFT_YEAR)
    overall = data.get('overall_pick')
    if not overall:
        return jsonify({'error': 'overall_pick required'}), 400
    conn = get_db()
    conn.execute('''
        INSERT INTO nml_draft_results
            (season_year, overall_pick, round, pick_in_round, nfl_team, player_id, player_name, position)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(season_year, overall_pick) DO UPDATE SET
            round=excluded.round, pick_in_round=excluded.pick_in_round,
            nfl_team=excluded.nfl_team, player_id=excluded.player_id,
            player_name=excluded.player_name, position=excluded.position
    ''', (year, overall, data.get('round'), data.get('pick_in_round'),
          data.get('nfl_team', ''), data.get('player_id'), data.get('player_name', ''), data.get('position', '')))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/admin/mock-drafts/score', methods=['POST'])
@require_auth
@require_role('commissioner')
def score_mock_drafts():
    """Score all published mocks against actual NML draft results.
    3pts = exact slot + player, 2pts = right player + right team (traded slot),
    1pt = player drafted in R1 by any team, 0 = miss."""
    data = request.get_json() or {}
    year = data.get('year', DRAFT_YEAR)
    conn = get_db()

    actual_rows = conn.execute(
        'SELECT * FROM nml_draft_results WHERE season_year=?', (year,)
    ).fetchall()
    if not actual_rows:
        conn.close()
        return jsonify({'error': 'No actual draft results entered for this year yet'}), 400

    # Build lookups
    actual_by_slot   = {}  # overall_pick → result row
    actual_by_player = {}  # player_name.lower() → result row
    for row in actual_rows:
        d = dict(row)
        actual_by_slot[d['overall_pick']] = d
        if d['player_name']:
            actual_by_player[d['player_name'].lower().strip()] = d

    mocks = conn.execute(
        'SELECT id FROM mock_drafts WHERE is_published=1 AND year=?', (year,)
    ).fetchall()

    scored_count = 0
    for mock_row in mocks:
        mid   = mock_row['id']
        picks = conn.execute(
            'SELECT * FROM mock_draft_picks WHERE mock_draft_id=? ORDER BY overall_pick', (mid,)
        ).fetchall()

        total_score = hit_3 = hit_2 = hit_1 = 0

        for pick in picks:
            op           = pick['overall_pick']
            mocked_name  = (pick['prospect_name'] or '').lower().strip()
            mocked_team  = (pick['nfl_team'] or '').strip()

            if not mocked_name:
                conn.execute('''UPDATE mock_draft_picks SET pick_points=0,
                    actual_player_name=NULL, actual_team=NULL
                    WHERE mock_draft_id=? AND overall_pick=?''', (mid, op))
                continue

            actual_slot   = actual_by_slot.get(op)
            actual_name   = (actual_slot['player_name'] if actual_slot else '').lower().strip()
            player_actual = actual_by_player.get(mocked_name)

            pts = 0
            if actual_slot and actual_name == mocked_name:
                pts = 3; hit_3 += 1
            elif player_actual and mocked_team and (player_actual.get('nfl_team') or '').strip() == mocked_team:
                pts = 2; hit_2 += 1
            elif player_actual:
                pts = 1; hit_1 += 1

            actual_display = actual_slot['player_name'] if actual_slot else None
            actual_team    = (actual_slot.get('nfl_team') or '') if actual_slot else None

            conn.execute('''UPDATE mock_draft_picks SET pick_points=?, actual_player_name=?, actual_team=?
                WHERE mock_draft_id=? AND overall_pick=?''',
                (pts, actual_display, actual_team, mid, op))

            total_score += pts

        conn.execute('''UPDATE mock_drafts SET score=?, hit_3=?, hit_2=?, hit_1=?,
            scored_at=datetime('now') WHERE id=?''',
            (total_score, hit_3, hit_2, hit_1, mid))
        scored_count += 1

    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'scored': scored_count})


# ── NFL Draft History ─────────────────────────────────────────────────────────

@app.route('/api/nfl-draft-history', methods=['GET'])
@require_auth
def get_nfl_draft_history():
    year  = request.args.get('year', type=int)
    team  = request.args.get('team', '').strip()
    pos   = request.args.get('position', '').strip()
    q     = request.args.get('q', '').strip()
    limit = request.args.get('limit', 500, type=int)
    off   = request.args.get('offset', 0, type=int)

    conn   = get_db()
    sql    = 'SELECT * FROM nfl_draft_history WHERE 1=1'
    params = []
    if year: sql += ' AND year=?'; params.append(year)
    if team: sql += ' AND nfl_team=?'; params.append(team)
    if pos:  sql += ' AND position=?'; params.append(pos)
    if q:    sql += ' AND player_name LIKE ?'; params.append(f'%{q}%')
    sql += ' ORDER BY year DESC, overall LIMIT ? OFFSET ?'
    params += [limit, off]
    rows = conn.execute(sql, params).fetchall()

    # Year list for tabs
    years = [r[0] for r in conn.execute('SELECT DISTINCT year FROM nfl_draft_history ORDER BY year DESC').fetchall()]
    conn.close()
    return jsonify({'picks': [dict(r) for r in rows], 'years': years})


@app.route('/api/nfl-draft-update', methods=['POST'])
@require_role('creator')
def update_nfl_draft_live():
    """Scrape Wikipedia for current 2026 NFL Draft picks and update DB."""
    import requests as req
    from bs4 import BeautifulSoup
    import re

    year = DRAFT_YEAR
    url  = f'https://en.wikipedia.org/wiki/{year}_NFL_draft'
    try:
        r = req.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        r.raise_for_status()
    except Exception as e:
        return jsonify({'error': str(e)}), 502

    soup = BeautifulSoup(r.text, 'html.parser')
    picks = []
    current_round = 0

    for table in soup.find_all('table', class_='wikitable'):
        prev = table.find_previous(['h2','h3'])
        if prev:
            m = re.search(r'Round\s*(\d+)', prev.get_text(), re.I)
            if m: current_round = int(m.group(1))

        headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
        col = {}
        for i, h in enumerate(headers):
            if 'overall' in h: col['overall'] = i
            if 'pick' in h and 'overall' not in h: col.setdefault('pick', i)
            if 'team' in h or 'club' in h: col.setdefault('team', i)
            if 'player' in h or 'name' in h: col.setdefault('player', i)
            if 'pos' in h: col.setdefault('position', i)
            if 'school' in h or 'college' in h: col.setdefault('school', i)

        for row in table.find_all('tr')[1:]:
            cells = row.find_all(['td','th'])
            if len(cells) < 3: continue
            text = [c.get_text(strip=True) for c in cells]
            def get(key, default=''):
                idx = col.get(key)
                return text[idx] if idx is not None and idx < len(text) else default
            try:
                overall = int(re.sub(r'[^\d]','', get('overall') or get('pick','')))
            except Exception:
                continue
            player = get('player')
            if not player or player.lower() in ('player','name',''): continue
            picks.append({'year': year, 'round': current_round,
                          'pick': None, 'overall': overall,
                          'nfl_team': get('team'), 'player_name': player,
                          'position': get('position'), 'school': get('school')})

    if not picks:
        return jsonify({'error': 'No picks found — draft may not have started yet'}), 404

    conn = get_db()
    inserted = updated = 0
    for p in picks:
        existing = conn.execute('SELECT id FROM nfl_draft_history WHERE year=? AND overall=?',
                                (p['year'], p['overall'])).fetchone()
        if existing:
            conn.execute('''UPDATE nfl_draft_history SET nfl_team=?, player_name=?, position=?, school=?
                WHERE year=? AND overall=?''',
                (p['nfl_team'], p['player_name'], p['position'], p['school'], p['year'], p['overall']))
            updated += 1
        else:
            conn.execute('''INSERT OR IGNORE INTO nfl_draft_history
                (year, round, pick, overall, nfl_team, player_name, position, school)
                VALUES (?,?,?,?,?,?,?,?)''',
                (p['year'], p['round'], p['pick'], p['overall'],
                 p['nfl_team'], p['player_name'], p['position'], p['school']))
            inserted += 1

        # Match to draft_prospects and fill NFL result fields
        norm = _norm_name(p['player_name'])
        prospect = conn.execute('''SELECT id FROM draft_prospects
            WHERE year=? AND lower(trim(name)) LIKE ?''', (year, f'%{norm[:8]}%')).fetchone()
        if prospect:
            conn.execute('''UPDATE draft_prospects SET nfl_team=?, nfl_round=?, nfl_overall=?,
                updated_at=datetime('now') WHERE id=?''',
                (p['nfl_team'], p['round'], p['overall'], prospect['id']))

    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'inserted': inserted, 'updated': updated, 'total': len(picks)})


# ── Analyst Scouting System (creator-only) ────────────────────────────────────

@app.route('/api/analysts', methods=['GET'])
@require_role('creator')
def get_analysts():
    conn = get_db()
    rows = conn.execute('''
        SELECT a.id, a.name, a.affiliation, a.notes, a.active,
               GROUP_CONCAT(apt.position_group || ':' || apt.trust_weight || ':' ||
                            apt.is_position_expert || ':' || apt.auto_expert, '|') as trust_data
        FROM analysts a
        LEFT JOIN analyst_position_trust apt ON apt.analyst_id = a.id
        GROUP BY a.id ORDER BY a.id
    ''').fetchall()
    analysts = []
    for r in rows:
        a = dict(r)
        trust = {}
        if a.get('trust_data'):
            for chunk in a['trust_data'].split('|'):
                parts = chunk.split(':')
                if len(parts) == 4:
                    trust[parts[0]] = {
                        'weight': float(parts[1]),
                        'is_expert': int(parts[2]),
                        'auto_expert': int(parts[3]),
                    }
        a['position_trust'] = trust
        del a['trust_data']
        analysts.append(a)
    conn.close()
    return jsonify(analysts)


@app.route('/api/analysts', methods=['POST'])
@require_role('creator')
def create_analyst():
    data = request.get_json() or {}
    name        = (data.get('name') or '').strip()
    affiliation = (data.get('affiliation') or '').strip()
    notes       = (data.get('notes') or '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    conn = get_db()
    try:
        cur = conn.execute(
            'INSERT INTO analysts (name, affiliation, notes) VALUES (?,?,?)',
            (name, affiliation or None, notes or None)
        )
        analyst_id = cur.lastrowid
        # Seed trust rows for all position groups at weight 1.0
        pos_groups = ['QB','RB','WR','TE','OT','OG','C','DT','Edge','LB','CB','S']
        conn.executemany(
            'INSERT OR IGNORE INTO analyst_position_trust (analyst_id, position_group) VALUES (?,?)',
            [(analyst_id, pg) for pg in pos_groups]
        )
        conn.commit()
        return jsonify({'ok': True, 'id': analyst_id})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 400
    finally:
        conn.close()


@app.route('/api/analysts/<int:aid>', methods=['PATCH'])
@require_role('creator')
def update_analyst(aid):
    data    = request.get_json() or {}
    allowed = {'name', 'affiliation', 'notes', 'active'}
    fields  = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return jsonify({'error': 'no valid fields'}), 400
    conn = get_db()
    sets = ', '.join(f'{k}=?' for k in fields)
    conn.execute(f'UPDATE analysts SET {sets} WHERE id=?', list(fields.values()) + [aid])
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/analyst-position-trust', methods=['GET'])
@require_role('creator')
def get_analyst_position_trust():
    conn = get_db()
    rows = conn.execute('''
        SELECT apt.*, a.name as analyst_name
        FROM analyst_position_trust apt
        JOIN analysts a ON a.id = apt.analyst_id
        ORDER BY a.id, apt.position_group
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/analyst-position-trust/<int:aid>/<pg>', methods=['PATCH'])
@require_role('creator')
def update_analyst_position_trust(aid, pg):
    data = request.get_json() or {}
    allowed = {'trust_weight', 'is_position_expert'}
    fields  = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return jsonify({'error': 'no valid fields'}), 400
    fields['updated_at'] = 'datetime(\'now\')'
    conn = get_db()
    sets = ', '.join(f'{k}=?' for k in fields if k != 'updated_at')
    sets += ", updated_at=datetime('now')"
    vals = [v for k, v in fields.items() if k != 'updated_at']
    conn.execute(
        f'UPDATE analyst_position_trust SET {sets} WHERE analyst_id=? AND position_group=?',
        vals + [aid, pg]
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/analyst-rankings', methods=['GET'])
@require_role('creator')
def get_analyst_rankings():
    year      = request.args.get('year', type=int)
    analyst_id = request.args.get('analyst_id', type=int)
    status    = request.args.get('status')   # 'unmatched' | 'flagged' | 'matched'
    pos_group = request.args.get('pos_group')
    if not year:
        return jsonify({'error': 'year required'}), 400
    conn  = get_db()
    where = ['ar.draft_year = ?']
    params = [year]
    if analyst_id:
        where.append('ar.analyst_id = ?')
        params.append(analyst_id)
    if status:
        where.append('ar.match_status = ?')
        params.append(status)
    if pos_group:
        where.append('ar.position_group = ?')
        params.append(pos_group)
    rows = conn.execute(f'''
        SELECT ar.*, a.name as analyst_name
        FROM analyst_rankings ar
        JOIN analysts a ON a.id = ar.analyst_id
        WHERE {' AND '.join(where)}
        ORDER BY ar.analyst_id, ar.rank
    ''', params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/analyst-rankings/<int:rid>/match', methods=['PATCH'])
@require_role('creator')
def patch_analyst_ranking_match(rid):
    """Manually link an unmatched ranking row to a draft_prospect id."""
    data = request.get_json() or {}
    prospect_id = data.get('prospect_id')
    if prospect_id is None:
        return jsonify({'error': 'prospect_id required'}), 400
    conn = get_db()
    conn.execute(
        "UPDATE analyst_rankings SET matched_prospect_id=?, match_status='manual' WHERE id=?",
        (prospect_id, rid)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/analyst-player-notes', methods=['GET'])
@require_role('creator')
def get_analyst_player_notes():
    """
    Get analyst notes/tags for a prospect.
    Query params: year (required), prospect_name (required) OR prospect_id.
    Returns notes from all analysts, with rolled-up tag summary.
    """
    year          = request.args.get('year', type=int)
    prospect_name = request.args.get('prospect_name', '').strip()
    prospect_id   = request.args.get('prospect_id', type=int)
    if not year:
        return jsonify({'error': 'year required'}), 400
    conn  = get_db()
    where = ['apn.draft_year = ?']
    params = [year]
    if prospect_id:
        where.append('apn.matched_prospect_id = ?')
        params.append(prospect_id)
    elif prospect_name:
        where.append('apn.prospect_name LIKE ?')
        params.append(f'%{prospect_name}%')
    else:
        return jsonify({'error': 'prospect_name or prospect_id required'}), 400

    rows = conn.execute(f'''
        SELECT apn.*, a.name as analyst_name
        FROM analyst_player_notes apn
        JOIN analysts a ON a.id = apn.analyst_id
        WHERE {' AND '.join(where)}
        ORDER BY a.id
    ''', params).fetchall()
    conn.close()

    notes = [dict(r) for r in rows]
    tags  = ['injury_risk', 'off_field_concern', 'my_guy', 'bust_risk', 'sleeper', 'scheme_dependent']
    summary = {t: sum(1 for n in notes if n.get(t)) for t in tags}
    return jsonify({'notes': notes, 'summary': summary})


@app.route('/api/consensus-rankings', methods=['GET'])
@require_role('creator')
def get_consensus_rankings():
    year  = request.args.get('year', type=int)
    ctype = request.args.get('type', 'industry')
    pg    = request.args.get('pos_group')
    if not year:
        return jsonify({'error': 'year required'}), 400
    conn  = get_db()
    where = ['draft_year=?', 'consensus_type=?']
    params = [year, ctype]
    if pg:
        where.append('position_group=?')
        params.append(pg)
    rows = conn.execute(
        f'SELECT * FROM consensus_rankings WHERE {" AND ".join(where)} ORDER BY consensus_rank',
        params
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/analyst-accuracy', methods=['GET'])
@require_role('creator')
def get_analyst_accuracy():
    pg   = request.args.get('pos_group')
    conn = get_db()
    where  = []
    params = []
    if pg:
        where.append('aa.position_group=?')
        params.append(pg)
    clause = f'WHERE {" AND ".join(where)}' if where else ''
    rows = conn.execute(f'''
        SELECT aa.*, a.name as analyst_name
        FROM analyst_accuracy aa
        JOIN analysts a ON a.id = aa.analyst_id
        {clause}
        ORDER BY aa.position_group, aa.rank_correlation DESC
    ''', params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/admin/run-accuracy-engine', methods=['POST'])
@require_role('creator')
def trigger_accuracy_engine():
    """Run the accuracy engine in-process and return results."""
    import subprocess, sys
    script = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'run_accuracy_engine.py')
    result = subprocess.run(
        [sys.executable, script, '--apply'],
        capture_output=True, text=True, timeout=120
    )
    ok = result.returncode == 0
    return jsonify({
        'ok': ok,
        'output': result.stdout[-3000:] if result.stdout else '',
        'error':  result.stderr[-1000:] if result.stderr else '',
    })


@app.route('/api/admin/run-consensus-engine', methods=['POST'])
@require_role('creator')
def trigger_consensus_engine():
    """Run the consensus engine for a given year."""
    data = request.get_json() or {}
    year = data.get('year')
    if not year:
        return jsonify({'error': 'year required'}), 400
    import subprocess, sys
    script = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'run_consensus_engine.py')
    result = subprocess.run(
        [sys.executable, script, '--year', str(year), '--apply'],
        capture_output=True, text=True, timeout=120
    )
    ok = result.returncode == 0
    return jsonify({
        'ok': ok,
        'output': result.stdout[-3000:] if result.stdout else '',
        'error':  result.stderr[-1000:] if result.stderr else '',
    })


# ── Pick Ownership ────────────────────────────────────────────────────────────

@app.route('/api/pick-ownership', methods=['GET'])
@require_auth
def get_pick_ownership():
    year = request.args.get('year', 2026, type=int)
    conn = get_db()
    teams = conn.execute('SELECT id, short_name, abbreviation FROM teams ORDER BY short_name').fetchall()
    rows = conn.execute('''
        SELECT current_owner_id, round, COUNT(*) as cnt
        FROM draft_picks WHERE year = ?
        GROUP BY current_owner_id, round
    ''', (year,)).fetchall()
    lookup = {}
    for row in rows:
        tid = row['current_owner_id']
        if tid not in lookup:
            lookup[tid] = {}
        lookup[tid][row['round']] = row['cnt']
    lock = conn.execute('SELECT locked_at FROM draft_locks WHERE year = ?', (year,)).fetchone()
    result = []
    for t in teams:
        tid = t['id']
        rds = lookup.get(tid, {})
        result.append({
            'team_id': tid,
            'short_name': t['short_name'],
            'abbrev': t['abbreviation'],
            'total': sum(rds.values()),
            'r1': rds.get(1, 0), 'r2': rds.get(2, 0), 'r3': rds.get(3, 0),
            'r4': rds.get(4, 0), 'r5': rds.get(5, 0), 'r6': rds.get(6, 0),
            'r7': rds.get(7, 0)
        })
    return jsonify({
        'year': year,
        'locked': lock is not None,
        'locked_at': lock['locked_at'] if lock else None,
        'teams': result
    })


@app.route('/api/admin/lock-draft-year', methods=['POST'])
@require_role('commissioner')
def lock_draft_year():
    data = request.get_json() or {}
    year = data.get('year')
    if not year:
        return jsonify({'error': 'year required'}), 400
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO draft_locks (year, locked_at, locked_by_user_id) VALUES (?, datetime('now'), ?)",
        (year, session.get('user_id'))
    )
    conn.commit()
    return jsonify({'ok': True, 'year': year})


# ── Nightly Backup Scheduler ──────────────────────────────────────────────────

@app.route('/api/admin/run-backup-now', methods=['POST'])
@require_role('assistant_commissioner')
def trigger_backup_now():
    """Manually trigger the nightly backup — posts xlsx to Discord backup channel."""
    _run_nightly_backup()
    return jsonify({'ok': True, 'message': 'Backup triggered — check Discord.'})


@app.route('/api/admin/relink-write-ins', methods=['POST'])
@require_role('creator')
def relink_write_ins():
    """One-shot backfill: walk every draft_selections row that's a write-in
    (player_id IS NULL) and try to link it to a real players row. If the
    matching record only exists in draft_prospects, promote it to a players
    row first.

    SAFETY: Idempotent — already-linked picks are skipped. Returns a JSON
    report of every action taken (and every row that couldn't be matched)."""
    def _norm(s):
        return ''.join(c for c in (s or '').lower() if c.isalnum())

    def _lev(a, b):
        """Levenshtein distance — small implementation, no external dep."""
        if len(a) < len(b):
            a, b = b, a
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            curr = [i] + [0] * len(b)
            for j, cb in enumerate(b, 1):
                curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb))
            prev = curr
        return prev[-1]

    # Optional position fix-ups — keys are normalized full names that should
    # have their players.position updated after linking.
    POSITION_FIXUPS = {
        'colevanlanen': 'LT',
    }

    conn = get_db()
    try:
        write_ins = conn.execute('''
            SELECT ds.id as sel_id, ds.draft_pick_id, ds.team_id,
                   ds.write_in_name, ds.write_in_position, ds.is_makeup_pick,
                   dp.overall_order, dp.round, dp.round_order
              FROM draft_selections ds
              JOIN draft_picks dp ON dp.id = ds.draft_pick_id
             WHERE ds.player_id IS NULL
               AND ds.write_in_name IS NOT NULL
               AND ds.write_in_name != ''
             ORDER BY dp.overall_order ASC
        ''').fetchall()

        report = {'linked': [], 'skipped': [], 'failed': []}

        for r in write_ins:
            wi_name = (r['write_in_name'] or '').strip()
            wi_norm = _norm(wi_name)
            sel_id = r['sel_id']
            team_id = r['team_id']
            entry = {
                'sel_id': sel_id,
                'pick': r['overall_order'],
                'write_in': wi_name,
                'team_id': team_id,
            }

            if not wi_norm:
                report['failed'].append({**entry, 'reason': 'empty name'})
                continue

            new_player_id = None
            source = None

            # Pre-compute candidate lists once
            player_cands = conn.execute(
                'SELECT id, first_name, last_name, position FROM players'
            ).fetchall()
            prospect_cands = conn.execute(
                'SELECT id, name FROM draft_prospects WHERE year = (SELECT MAX(year) FROM draft_prospects)'
            ).fetchall()

            # 1. Exact normalized match in players (handles Van Lanen, McAlister)
            for cand in player_cands:
                if _norm(f"{cand['first_name']}{cand['last_name']}") == wi_norm:
                    new_player_id = cand['id']
                    source = 'existing_players_exact'
                    break

            # 2. Exact normalized match in draft_prospects (promote)
            if new_player_id is None:
                for pr in prospect_cands:
                    if _norm(pr['name']) == wi_norm:
                        try:
                            new_id, _ = _promote_prospect_to_player(
                                conn, pr['id'], team_id, r['round'], r['round_order']
                            )
                            new_player_id = new_id
                            source = f'promoted_from_prospect_{pr["id"]}_exact'
                        except Exception as e:
                            report['failed'].append({**entry, 'reason': f'promote failed: {e}'})
                            new_player_id = -1
                        break

            # 3. Fuzzy match (Levenshtein ≤ 2) — handles typos like
            #    "Murphey" vs "Murphy" and "McAllister" vs "McAlister".
            #    Tolerance scales with name length to avoid false matches.
            if new_player_id is None:
                tol = max(1, min(2, len(wi_norm) // 6))
                best = None  # (distance, kind, id, label)
                for cand in player_cands:
                    cn = _norm(f"{cand['first_name']}{cand['last_name']}")
                    if not cn:
                        continue
                    d = _lev(wi_norm, cn)
                    if d <= tol and (best is None or d < best[0]):
                        best = (d, 'players', cand['id'],
                                f"{cand['first_name']} {cand['last_name']}")
                for pr in prospect_cands:
                    cn = _norm(pr['name'])
                    if not cn:
                        continue
                    d = _lev(wi_norm, cn)
                    if d <= tol and (best is None or d < best[0]):
                        best = (d, 'prospect', pr['id'], pr['name'])

                if best is not None:
                    if best[1] == 'players':
                        new_player_id = best[2]
                        source = f'existing_players_fuzzy(d={best[0]},matched_to=\"{best[3]}\")'
                    else:
                        try:
                            new_id, _ = _promote_prospect_to_player(
                                conn, best[2], team_id, r['round'], r['round_order']
                            )
                            new_player_id = new_id
                            source = f'promoted_from_prospect_{best[2]}_fuzzy(d={best[0]},matched_to=\"{best[3]}\")'
                        except Exception as e:
                            report['failed'].append({**entry, 'reason': f'promote failed: {e}'})
                            new_player_id = -1

            if new_player_id is None:
                report['failed'].append({**entry, 'reason': 'no match in players or draft_prospects'})
                continue
            if new_player_id == -1:
                continue  # already logged

            # Apply optional position fixup before linking
            if wi_norm in POSITION_FIXUPS:
                conn.execute(
                    'UPDATE players SET position=? WHERE id=?',
                    (POSITION_FIXUPS[wi_norm], new_player_id)
                )

            # Update the selection: link player, clear write-in fields
            conn.execute('''
                UPDATE draft_selections
                   SET player_id=?, write_in_name=NULL, write_in_position=NULL
                 WHERE id=?
            ''', (new_player_id, sel_id))

            # Mark player as drafted onto the team
            conn.execute('''
                UPDATE players
                   SET nml_team_id=?, is_free_agent=0, is_rookie_prospect=0
                 WHERE id=?
            ''', (team_id, new_player_id))

            # Sync Big Board (tiered matcher)
            player = conn.execute('SELECT * FROM players WHERE id=?', (new_player_id,)).fetchone()
            if player:
                _sync_big_board_for_pick(
                    conn, player, team_id, r['round'], r['round_order']
                )

            report['linked'].append({
                **entry,
                'new_player_id': new_player_id,
                'source': source,
                'position_fixup': POSITION_FIXUPS.get(wi_norm),
            })

        conn.commit()
        _cache_bust('players_')
        conn.close()
        return jsonify({
            'ok': True,
            'totals': {
                'scanned': len(write_ins),
                'linked': len(report['linked']),
                'failed': len(report['failed']),
            },
            'detail': report,
        })
    except Exception as e:
        conn.close()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/admin/sync-big-board-now', methods=['POST', 'GET'])
@require_role('assistant_commissioner')
def sync_big_board_now():
    """Walks every draft_selections row and populates draft_prospects
    (nml_team_id / nml_round / nml_pick) using the fuzzy tiered matcher.

    SAFETY: Only writes to draft_prospects. Never touches draft_selections,
    draft_picks, players, trades, or any other transactional table.
    Idempotent — safe to run multiple times."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT ds.player_id, ds.team_id, dp.round, dp.round_order, dp.overall_order
              FROM draft_selections ds
              JOIN draft_picks dp ON dp.id = ds.draft_pick_id
             WHERE ds.player_id IS NOT NULL
             ORDER BY dp.overall_order ASC
        """).fetchall()

        total = len(rows); matched = 0; no_match = 0
        already_set = 0;   overwrote = 0; misses = []

        for r in rows:
            player = conn.execute(
                "SELECT id, first_name, last_name, position, school, birth_date "
                "FROM players WHERE id=?", (r['player_id'],)
            ).fetchone()
            if not player:
                no_match += 1
                misses.append(f"pick #{r['overall_order']}: player_id={r['player_id']} not in players table")
                continue

            target_id, tier, _cands = _bb_find_prospect(conn, player)
            if target_id is None:
                no_match += 1
                misses.append(
                    f"pick #{r['overall_order']}: no match for "
                    f"{(player['first_name'] or '').strip()} {(player['last_name'] or '').strip()} "
                    f"({player['position']}, {player['school']})"
                )
                continue

            existing = conn.execute(
                "SELECT nml_team_id, nml_round, nml_pick FROM draft_prospects WHERE id=?",
                (target_id,)
            ).fetchone()
            new_vals = (r['team_id'], r['round'], r['round_order'])
            old_vals = (existing['nml_team_id'], existing['nml_round'], existing['nml_pick'])

            if old_vals == new_vals:
                already_set += 1
                continue
            if any(v is not None for v in old_vals):
                overwrote += 1

            conn.execute(
                "UPDATE draft_prospects SET nml_team_id=?, nml_round=?, nml_pick=? WHERE id=?",
                (*new_vals, target_id)
            )
            matched += 1

        conn.commit()
        return jsonify({
            'ok': True,
            'total_picks_scanned': total,
            'updated_this_run':    matched,
            'overwrote_existing':  overwrote,
            'already_correct':     already_set,
            'no_match':            no_match,
            'misses':              misses[:50],
            'misses_truncated':    max(0, len(misses) - 50),
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/admin/big-board-audit', methods=['GET'])
@require_role('assistant_commissioner')
def big_board_audit():
    """Read-only diagnostic. For each submitted pick, returns:
       - drafted player + pick info
       - matched prospect (id/name/tier) if any
       - close candidates that COULD be the right match (suggestions)
       - duplicate-prospect warnings (other rows with same normalized name).
    Use this to drive manual link/merge decisions in the UI."""
    conn = get_db()
    try:
        # All prospects, normalized once for duplicate detection
        all_p = conn.execute(
            "SELECT id, name, position, school, birth_date, nml_team_id, nml_round, nml_pick "
            "FROM draft_prospects"
        ).fetchall()
        norm_index = {}
        for p in all_p:
            n = _bb_norm_name(p['name'])
            if not n: continue
            norm_index.setdefault(n, []).append(p)

        rows = conn.execute("""
            SELECT ds.player_id, ds.team_id, dp.round, dp.round_order, dp.overall_order,
                   t.short_name AS team_short, t.full_name AS team_name
              FROM draft_selections ds
              JOIN draft_picks dp ON dp.id = ds.draft_pick_id
              LEFT JOIN teams t ON t.id = ds.team_id
             WHERE ds.player_id IS NOT NULL
             ORDER BY dp.overall_order ASC
        """).fetchall()

        out = []
        for r in rows:
            player = conn.execute(
                "SELECT id, first_name, last_name, position, school, birth_date "
                "FROM players WHERE id=?", (r['player_id'],)
            ).fetchone()
            entry = {
                'overall':  r['overall_order'],
                'round':    r['round'],
                'round_pk': r['round_order'],
                'team_id':  r['team_id'],
                'team':     r['team_short'] or r['team_name'] or '',
                'player_id': r['player_id'],
            }
            if not player:
                entry.update({
                    'player': '(unknown)', 'position': '', 'school': '', 'birth_date': '',
                    'match': None, 'tier': 'no_player_row',
                    'candidates': [], 'duplicates': [],
                })
                out.append(entry); continue

            entry.update({
                'player':   f"{(player['first_name'] or '').strip()} {(player['last_name'] or '').strip()}".strip(),
                'position': player['position'] or '',
                'school':   player['school']   or '',
                'birth_date': player['birth_date'] or '',
            })

            target_id, tier, cands = _bb_find_prospect(conn, player)
            if target_id:
                m = next((c for c in cands if c['id'] == target_id), None)
                entry['match'] = {
                    'prospect_id': target_id,
                    'prospect_name': (m['name'] if m else ''),
                    'prospect_position': (m['position'] if m else ''),
                    'prospect_school':   (m['school']   if m else ''),
                }
                entry['tier'] = tier
                # Other candidates considered at the chosen tier (potential duplicates)
                entry['candidates'] = [
                    {'id': c['id'], 'name': c['name'], 'position': c['position'],
                     'school': c['school'], 'nml_team_id': c['nml_team_id']}
                    for c in cands if c['id'] != target_id
                ][:5]
            else:
                entry['match'] = None
                entry['tier']  = 'no_match'
                entry['candidates'] = [
                    {'id': c['id'], 'name': c['name'], 'position': c['position'],
                     'school': c['school'], 'nml_team_id': c['nml_team_id']}
                    for c in cands
                ][:8]

            # Duplicate detection — two passes:
            #   1) any OTHER prospect with the same normalized full name (formatting variants)
            #   2) any OTHER prospect with the same last name + same position (nickname / alt-name variants)
            suspects = []
            seen = set()
            if entry['match']:
                seen.add(entry['match']['prospect_id'])
                ref_name = entry['match']['prospect_name']
                ref_pos  = (entry['match']['prospect_position'] or '').strip().upper()
            else:
                ref_name = entry['player']
                ref_pos  = (entry['position'] or '').strip().upper()
            ref_norm = _bb_norm_name(ref_name)
            ref_last = _bb_last_token(ref_name)
            # Pass 1: exact normalized name match
            if ref_norm and ref_norm in norm_index:
                for p in norm_index[ref_norm]:
                    if p['id'] in seen: continue
                    suspects.append(p); seen.add(p['id'])
            # Pass 2: same last name + same position (catches Kevin vs KC, etc.)
            if ref_last and ref_pos:
                for p in all_p:
                    if p['id'] in seen: continue
                    if _bb_last_token(p['name']) == ref_last and (p['position'] or '').strip().upper() == ref_pos:
                        suspects.append(p); seen.add(p['id'])
            entry['duplicates'] = [
                {'id': p['id'], 'name': p['name'], 'position': p['position'],
                 'school': p['school'], 'nml_team_id': p['nml_team_id']}
                for p in suspects
            ]

            out.append(entry)

        # Summary counts
        n_matched = sum(1 for e in out if e.get('match'))
        n_unmatched = sum(1 for e in out if not e.get('match'))
        n_with_dups = sum(1 for e in out if e.get('duplicates'))

        return jsonify({
            'ok': True,
            'total_picks':   len(out),
            'matched':       n_matched,
            'unmatched':     n_unmatched,
            'with_duplicates': n_with_dups,
            'picks':         out,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/admin/big-board-link', methods=['POST'])
@require_role('assistant_commissioner')
def big_board_link():
    """Manually link a drafted player to a specific draft_prospects row.
    Body: {player_id, prospect_id}. Looks up the player's pick and writes
    nml_team_id/round/nml_pick onto the chosen prospect."""
    data = request.json or {}
    player_id   = data.get('player_id')
    prospect_id = data.get('prospect_id')
    if not player_id or not prospect_id:
        return jsonify({'ok': False, 'error': 'player_id and prospect_id required'}), 400
    conn = get_db()
    try:
        sel = conn.execute("""
            SELECT ds.team_id, dp.round, dp.round_order
              FROM draft_selections ds
              JOIN draft_picks dp ON dp.id = ds.draft_pick_id
             WHERE ds.player_id = ?
             ORDER BY dp.overall_order DESC LIMIT 1
        """, (player_id,)).fetchone()
        if not sel:
            return jsonify({'ok': False, 'error': 'player has no draft_selections row'}), 404
        if not conn.execute("SELECT 1 FROM draft_prospects WHERE id=?", (prospect_id,)).fetchone():
            return jsonify({'ok': False, 'error': 'prospect not found'}), 404
        conn.execute(
            "UPDATE draft_prospects SET nml_team_id=?, nml_round=?, nml_pick=? WHERE id=?",
            (sel['team_id'], sel['round'], sel['round_order'], prospect_id)
        )
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/admin/big-board-unlink-prospect', methods=['POST'])
@require_role('assistant_commissioner')
def big_board_unlink_prospect():
    """Clear nml_team_id / nml_round / nml_pick on a single prospect so the
    next sync re-evaluates it. Use to undo a bad fuzzy match.
    Body: {prospect_id}."""
    data = request.json or {}
    prospect_id = data.get('prospect_id')
    if not prospect_id:
        return jsonify({'ok': False, 'error': 'prospect_id required'}), 400
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM draft_prospects WHERE id=?", (prospect_id,)).fetchone():
            return jsonify({'ok': False, 'error': 'prospect not found'}), 404
        conn.execute(
            "UPDATE draft_prospects SET nml_team_id=NULL, nml_round=NULL, nml_pick=NULL WHERE id=?",
            (prospect_id,)
        )
        conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/admin/big-board-reset-and-resync', methods=['POST'])
@require_role('assistant_commissioner')
def big_board_reset_and_resync():
    """Clears nml_team_id / nml_round / nml_pick on ALL draft_prospects rows,
    then re-runs the sync. Use to recover from prior wrong matches once the
    matcher logic has been tightened. Only writes to draft_prospects."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE draft_prospects SET nml_team_id=NULL, nml_round=NULL, nml_pick=NULL"
        )
        rows = conn.execute("""
            SELECT ds.player_id, ds.team_id, dp.round, dp.round_order, dp.overall_order
              FROM draft_selections ds
              JOIN draft_picks dp ON dp.id = ds.draft_pick_id
             WHERE ds.player_id IS NOT NULL
             ORDER BY dp.overall_order ASC
        """).fetchall()
        total = len(rows); matched = 0; no_match = 0; misses = []
        for r in rows:
            player = conn.execute(
                "SELECT id, first_name, last_name, position, school, birth_date "
                "FROM players WHERE id=?", (r['player_id'],)
            ).fetchone()
            if not player:
                no_match += 1
                misses.append(f"pick #{r['overall_order']}: player_id={r['player_id']} not in players")
                continue
            target_id, _tier, _cands = _bb_find_prospect(conn, player)
            if target_id is None:
                no_match += 1
                misses.append(
                    f"pick #{r['overall_order']}: no match for "
                    f"{(player['first_name'] or '').strip()} {(player['last_name'] or '').strip()} "
                    f"({player['position']}, {player['school']})"
                )
                continue
            conn.execute(
                "UPDATE draft_prospects SET nml_team_id=?, nml_round=?, nml_pick=? WHERE id=?",
                (r['team_id'], r['round'], r['round_order'], target_id)
            )
            matched += 1
        conn.commit()
        return jsonify({
            'ok': True,
            'total_picks_scanned': total,
            'matched':             matched,
            'no_match':            no_match,
            'misses':              misses[:50],
            'misses_truncated':    max(0, len(misses) - 50),
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/admin/big-board-merge-prospects', methods=['POST'])
@require_role('assistant_commissioner')
def big_board_merge_prospects():
    """Collapse a duplicate draft_prospects row into a kept one.
    Body: {keep_id, drop_id}. Removes the dropped prospect (and any of its
    user big-board placements) so the kept prospect becomes the canonical
    record. SAFETY: only touches draft_prospects + draft_board_entries."""
    data = request.json or {}
    keep_id = data.get('keep_id')
    drop_id = data.get('drop_id')
    if not keep_id or not drop_id or keep_id == drop_id:
        return jsonify({'ok': False, 'error': 'keep_id and drop_id required and must differ'}), 400
    conn = get_db()
    try:
        keep = conn.execute("SELECT id, name, nml_team_id, nml_round, nml_pick FROM draft_prospects WHERE id=?", (keep_id,)).fetchone()
        drop = conn.execute("SELECT id, name, nml_team_id, nml_round, nml_pick FROM draft_prospects WHERE id=?", (drop_id,)).fetchone()
        if not keep or not drop:
            return jsonify({'ok': False, 'error': 'one or both prospects not found'}), 404

        # If dropped row had Big Board pick attribution and kept row didn't, transfer it
        if drop['nml_team_id'] and not keep['nml_team_id']:
            conn.execute(
                "UPDATE draft_prospects SET nml_team_id=?, nml_round=?, nml_pick=? WHERE id=?",
                (drop['nml_team_id'], drop['nml_round'], drop['nml_pick'], keep_id)
            )

        # Remove user big-board placements for the dropped prospect (kept row may already be on their boards)
        conn.execute("DELETE FROM draft_board_entries WHERE prospect_id=?", (drop_id,))
        # Drop the duplicate prospect row
        conn.execute("DELETE FROM draft_prospects WHERE id=?", (drop_id,))
        conn.commit()
        return jsonify({'ok': True, 'kept': keep['name'], 'dropped': drop['name']})
    except Exception as e:
        conn.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        conn.close()

def _run_nightly_backup():
    """Generate the backup xlsx and post it to the configured Discord channel."""
    from discord_bot import post_backup_to_discord
    from datetime import datetime
    try:
        buf = generate_backup_xlsx()
        filename = f"nml_backup_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
        ok, msg = post_backup_to_discord(buf.read(), filename)
        print(f'[Backup] {datetime.now().strftime("%Y-%m-%d %H:%M")} — {"OK" if ok else "FAILED"}: {msg}')
    except Exception as e:
        print(f'[Backup] ERROR: {e}')


def _start_backup_scheduler():
    """Start the APScheduler in a background thread.
    Uses a file lock so only one worker runs it under gunicorn --preload."""
    try:
        import fcntl, tempfile, atexit
        from apscheduler.schedulers.background import BackgroundScheduler
        import pytz

        lock_path = os.path.join(tempfile.gettempdir(), 'nml_backup_scheduler.lock')
        lock_fh = open(lock_path, 'w')
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)  # non-blocking; raises if locked

        scheduler = BackgroundScheduler(timezone=pytz.timezone('America/Los_Angeles'))
        scheduler.add_job(_run_nightly_backup, 'cron', hour=2, minute=0,
                          id='nightly_backup', replace_existing=True)
        scheduler.start()
        atexit.register(scheduler.shutdown)
        print('[Backup] Scheduler started — nightly at 2:00 AM Pacific')
    except (IOError, OSError):
        pass  # Another worker already holds the lock — skip
    except ImportError:
        print('[Backup] APScheduler not installed — skipping scheduler')


_start_backup_scheduler()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
