import os
import json
import secrets
import time
import random
import requests
from functools import wraps
from flask import request, jsonify, session
from database import get_db

# ── Discord OAuth Config ───────────────────────────────────────────────────
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET = os.environ.get('DISCORD_CLIENT_SECRET', '')
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN', '')
DISCORD_REDIRECT_URI = os.environ.get('DISCORD_REDIRECT_URI', 'http://localhost:5000/auth/callback')

DISCORD_API = 'https://discord.com/api/v10'
DISCORD_OAUTH_URL = 'https://discord.com/oauth2/authorize'
DISCORD_TOKEN_URL = f'{DISCORD_API}/oauth2/token'

ROLE_HIERARCHY = {
    'creator': 5,
    'commissioner': 4,
    'assistant_commissioner': 3,
    'owner': 2,
    'readonly': 1
}

# ── Session token store (persisted in SQLite) ─────────────────────────────
SESSION_TTL_DAYS = 30

def create_session(user_id):
    token = secrets.token_urlsafe(32)
    conn = get_db()
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, datetime('now', '+30 days'))",
        (token, user_id)
    )
    conn.commit()
    conn.close()
    return token

# ── Trusted Device tokens (1-year, stored in SQLite) ─────────────────────

def _parse_device_name(ua):
    """Turn a User-Agent string into a friendly device label."""
    if not ua:
        return 'Unknown Device'
    if 'iPhone' in ua:       os_name = 'iPhone'
    elif 'iPad' in ua:       os_name = 'iPad'
    elif 'Android' in ua:    os_name = 'Android'
    elif 'Macintosh' in ua:  os_name = 'Mac'
    elif 'Windows' in ua:    os_name = 'Windows'
    elif 'Linux' in ua:      os_name = 'Linux'
    else:                    os_name = 'Unknown'
    if 'Edg/' in ua or 'Edge/' in ua:              browser = 'Edge'
    elif 'Chrome/' in ua and 'Safari' in ua:        browser = 'Chrome'
    elif 'Firefox/' in ua:                          browser = 'Firefox'
    elif 'Safari/' in ua:                           browser = 'Safari'
    else:                                           browser = 'Browser'
    return f'{browser} on {os_name}'


def create_device_token(user_id, device_name):
    """Create a 1-year trusted device token. Returns the token string."""
    token = secrets.token_urlsafe(48)
    conn = get_db()
    conn.execute(
        """INSERT INTO trusted_devices (token, user_id, device_name, expires_at)
           VALUES (?, ?, ?, datetime('now', '+365 days'))""",
        (token, user_id, device_name)
    )
    conn.commit()
    conn.close()
    return token


def verify_device_token(device_token):
    """Validate a trusted device token. Returns (session_token, error_message).
    Updates last_used_at on success so we can show the user when each device was active."""
    if not device_token:
        return None, 'No device token provided'
    conn = get_db()
    row = conn.execute(
        """SELECT * FROM trusted_devices
           WHERE token = ? AND expires_at > datetime('now')""",
        (device_token,)
    ).fetchone()
    if not row:
        conn.close()
        return None, 'Device token invalid or expired'
    user_id = row['user_id']
    conn.execute(
        "UPDATE trusted_devices SET last_used_at = CURRENT_TIMESTAMP WHERE token = ?",
        (device_token,)
    )
    conn.commit()
    conn.close()
    session_token = create_session(user_id)
    return session_token, None


def get_user_from_token(token):
    if not token:
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT user_id FROM sessions WHERE token = ? AND expires_at > datetime('now')",
        (token,)
    ).fetchone()
    if not row:
        conn.close()
        return None
    user = conn.execute('SELECT * FROM users WHERE id = ?', (row['user_id'],)).fetchone()
    conn.close()
    return dict(user) if user else None

def delete_session(token):
    conn = get_db()
    conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
    conn.commit()
    conn.close()

def cleanup_expired_sessions():
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE expires_at <= datetime('now')")
    conn.commit()
    conn.close()

def get_current_user():
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return get_user_from_token(auth[7:])
    return None

# ── Auth decorators ────────────────────────────────────────────────────────
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated

def require_role(min_role):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({'error': 'Authentication required'}), 401
            user_level = ROLE_HIERARCHY.get(user['role'], 0)
            required_level = ROLE_HIERARCHY.get(min_role, 0)
            if user_level < required_level:
                return jsonify({'error': f'Requires {min_role} role or higher'}), 403
            request.current_user = user
            return f(*args, **kwargs)
        return decorated
    return decorator

def is_admin(user):
    return user and user['role'] in ('creator', 'commissioner', 'assistant_commissioner')

def is_creator(user):
    return user and user['role'] == 'creator'

def can_manage_team(user, team_id):
    """User can manage a team if they're admin or own that team"""
    if is_admin(user):
        return True
    return user and user.get('team_id') == team_id

# ── Discord OAuth Flow ─────────────────────────────────────────────────────
def get_oauth_url(state):
    params = {
        'client_id': DISCORD_CLIENT_ID,
        'redirect_uri': DISCORD_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'identify',
        'state': state
    }
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    return f'{DISCORD_OAUTH_URL}?{query}'

def exchange_code(code):
    """Exchange OAuth code for access token"""
    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': DISCORD_REDIRECT_URI,
    }
    res = requests.post(DISCORD_TOKEN_URL, data=data)
    if not res.ok:
        return None
    return res.json()

def get_discord_user(access_token):
    """Get Discord user info from access token"""
    res = requests.get(f'{DISCORD_API}/users/@me',
                       headers={'Authorization': f'Bearer {access_token}'})
    if not res.ok:
        return None
    return res.json()

def upsert_user(discord_user):
    """Create or update user from Discord profile, return our user record"""
    conn = get_db()
    discord_id = discord_user['id']
    username = discord_user.get('username', '')
    discriminator = discord_user.get('discriminator', '0')
    display_name = discord_user.get('global_name') or username
    avatar = discord_user.get('avatar')
    avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar}.png" if avatar else None

    existing = conn.execute('SELECT * FROM users WHERE discord_id = ?', (discord_id,)).fetchone()

    if existing:
        conn.execute('''UPDATE users SET discord_username=?, discord_tag=?, display_name=?,
            avatar_url=?, last_login=CURRENT_TIMESTAMP WHERE discord_id=?''',
            (username, discriminator, display_name, avatar_url, discord_id))
        user_id = existing['id']
    else:
        # New user — check if a team has a pending_role pre-assigned for this Discord ID
        team_row = conn.execute(
            "SELECT id, pending_role FROM teams WHERE discord_user_id = ?", (discord_id,)
        ).fetchone()
        assigned_role = team_row['pending_role'] if team_row else 'readonly'
        assigned_team = team_row['id'] if team_row else None
        c = conn.execute('''INSERT INTO users (discord_id, discord_username, discord_tag, display_name, avatar_url, role, team_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (discord_id, username, discriminator, display_name, avatar_url, assigned_role, assigned_team))
        user_id = c.lastrowid

    conn.commit()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return dict(user)

# ── Discord Bot Messaging ──────────────────────────────────────────────────
def send_discord_message(channel_id, content):
    """Post a message to a Discord channel via bot (respects testing mode override)"""
    from discord_bot import get_test_override, _channel_label, send_dm as bot_send_dm
    bot_token = DISCORD_BOT_TOKEN
    if not bot_token:
        return False

    override = get_test_override()
    if override:
        label = _channel_label(channel_id) if channel_id else '#channel'
        success, _ = bot_send_dm(override, f"🧪 **[TEST — {label}]**\n\n{content}")
        return success

    if not channel_id:
        return False
    try:
        res = requests.post(
            f'{DISCORD_API}/channels/{channel_id}/messages',
            headers={'Authorization': f'Bot {bot_token}', 'Content-Type': 'application/json'},
            json={'content': content}
        )
        return res.ok
    except Exception:
        return False

def send_discord_dm(discord_user_id, content):
    """Send a DM to a Discord user via bot"""
    bot_token = DISCORD_BOT_TOKEN
    if not bot_token or not discord_user_id:
        return False
    try:
        # Create DM channel
        dm_res = requests.post(
            f'{DISCORD_API}/users/@me/channels',
            headers={'Authorization': f'Bot {bot_token}', 'Content-Type': 'application/json'},
            json={'recipient_id': discord_user_id}
        )
        if not dm_res.ok:
            return False
        channel_id = dm_res.json()['id']
        # Send message
        msg_res = requests.post(
            f'{DISCORD_API}/channels/{channel_id}/messages',
            headers={'Authorization': f'Bot {bot_token}', 'Content-Type': 'application/json'},
            json={'content': content}
        )
        return msg_res.ok
    except Exception:
        return False

# ── Discord Code Login ─────────────────────────────────────────────────────

def request_verification_code(username):
    """Generate a 6-digit code and send via Discord DM. Returns (success, error_message)."""
    conn = get_db()
    username_lower = username.lower().strip()
    discord_user_id = None

    # First check users table
    user = conn.execute(
        'SELECT * FROM users WHERE lower(discord_username) = ?', (username_lower,)
    ).fetchone()
    if user and user['team_id']:
        team = conn.execute(
            'SELECT discord_user_id FROM teams WHERE id = ?', (user['team_id'],)
        ).fetchone()
        if team:
            discord_user_id = team['discord_user_id']

    # Fall back to teams table (ghost users who haven't logged in yet)
    if not discord_user_id:
        team = conn.execute(
            'SELECT discord_user_id FROM teams WHERE lower(discord_username) = ?', (username_lower,)
        ).fetchone()
        if team:
            discord_user_id = team['discord_user_id']

    if not discord_user_id:
        conn.close()
        return False, 'Username not found or no Discord ID on file. Contact the commissioner.'

    # Generate 6-digit numeric code and store in DB (5 min expiry)
    code = str(random.randint(100000, 999999))
    conn.execute(
        '''INSERT OR REPLACE INTO login_codes (username_lower, code, discord_user_id, expires_at)
           VALUES (?, ?, ?, datetime('now', '+5 minutes'))''',
        (username_lower, code, discord_user_id)
    )
    conn.commit()
    conn.close()

    msg = (
        f"🔐 **NML Login Code**\n"
        f"Your verification code is: **{code}**\n"
        f"This code expires in 5 minutes. Do not share it with anyone."
    )
    from discord_bot import send_dm as bot_send_dm
    success, err = bot_send_dm(discord_user_id, msg)
    if not success:
        return False, f'Could not send Discord DM: {err}. Make sure the bot token is configured in Settings and that the bot can message you.'

    return True, None


def verify_login_code(username, code, device_name=None):
    """Verify the code and return (session_token, device_token, error_message)."""
    username_lower = username.lower().strip()
    conn = get_db()
    entry = conn.execute(
        "SELECT * FROM login_codes WHERE username_lower = ? AND expires_at > datetime('now')",
        (username_lower,)
    ).fetchone()

    if not entry:
        conn.close()
        return None, None, 'No valid code found for this username. It may have expired — please request a new one.'
    if entry['code'] != code.strip():
        conn.close()
        return None, None, 'Incorrect code. Please try again.'

    # Code is valid — delete it so it can't be reused
    conn.execute('DELETE FROM login_codes WHERE username_lower = ?', (username_lower,))

    user = conn.execute(
        'SELECT * FROM users WHERE lower(discord_username) = ?', (username_lower,)
    ).fetchone()

    if user:
        user_id = user['id']
        conn.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user_id,))
        conn.commit()
    else:
        # Ghost user — create their account now
        team = conn.execute(
            'SELECT * FROM teams WHERE lower(discord_username) = ?', (username_lower,)
        ).fetchone()
        if not team:
            conn.close()
            return None, None, 'User account could not be created. Contact the commissioner.'
        role = team['pending_role'] if team['pending_role'] else 'owner'
        c = conn.execute(
            '''INSERT INTO users (discord_id, discord_username, display_name, role, team_id)
               VALUES (?, ?, ?, ?, ?)''',
            (entry['discord_user_id'], username, username, role, team['id'])
        )
        user_id = c.lastrowid
        conn.commit()

    conn.close()
    session_token = create_session(user_id)
    dev_token = create_device_token(user_id, device_name or 'Unknown Device')
    return session_token, dev_token, None


def notify_trade_action(trade, action, recipient_team_id):
    """Send a Discord DM to the relevant owner about a trade action (respects testing mode override)"""
    from discord_bot import get_trade_summary, get_test_override, send_dm as bot_send_dm
    from database import generate_trade_token

    conn = get_db()
    team = conn.execute('SELECT * FROM teams WHERE id = ?', (recipient_team_id,)).fetchone()
    if not team or not team['discord_user_id']:
        conn.close()
        return

    t1 = conn.execute('SELECT short_name FROM teams WHERE id = ?', (trade['team1_id'],)).fetchone()
    t2 = conn.execute('SELECT short_name FROM teams WHERE id = ?', (trade['team2_id'],)).fetchone()

    # Get trade summary with full details
    trade_id = trade.get('id')
    trade_summary = get_trade_summary(conn, trade_id) if trade_id else ""
    trade_summary_with_linebreak = f"\n{trade_summary}\n\n" if trade_summary else "\n"

    # Generate magic-link tokens for proposed (team2 accept/reject)
    discord_links = ''
    if action == 'proposed' and trade_id:
        _rail = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '').rstrip('/')
        _env  = os.environ.get('APP_URL', '').rstrip('/')
        base  = (f'https://{_rail}' if _rail else _env) or 'http://127.0.0.1:8080'
        accept_token = generate_trade_token(conn, trade_id, recipient_team_id, 'accept')
        reject_token = generate_trade_token(conn, trade_id, recipient_team_id, 'reject')
        conn.commit()
        accept_url = f"{base}/api/trades/{trade_id}/discord-respond?token={accept_token}&action=accept"
        reject_url = f"{base}/api/trades/{trade_id}/discord-respond?token={reject_token}&action=reject"
        counter_url = f"{base}/?view=propose&counter_of={trade_id}"
        discord_links = (
            f"[Accept](<{accept_url}>) · [Reject](<{reject_url}>) · [Counter-offer](<{counter_url}>)"
        )

    override = get_test_override(conn)
    conn.close()

    APP_URL = os.environ.get('APP_URL', 'https://nmlapp-production.up.railway.app')
    trade_link = f"{APP_URL}/?view=trades&id={trade_id}" if trade_id else APP_URL

    # Append trade notes if present
    notes_text = trade.get('notes', '') or ''
    notes_block = f"**Note:** {notes_text}\n" if notes_text.strip() else ''

    messages = {
        'proposed': f"{t1['short_name']} has proposed a trade with {t2['short_name']}.{trade_summary_with_linebreak}{notes_block}{discord_links}",
        'accepted_awaiting_confirm': f"✅ **Trade Accepted — Your Confirmation Needed**\n{t2['short_name']} accepted your trade proposal.{trade_summary_with_linebreak}{notes_block}\n🔗 {trade_link}",
        'rejected_team2': f"❌ **Trade Rejected**\n{t2['short_name']} rejected the trade proposal from {t1['short_name']}.{trade_summary_with_linebreak}",
        'rejected_team1': f"❌ **Trade Cancelled**\n{t1['short_name']} cancelled the trade with {t2['short_name']}.{trade_summary_with_linebreak}",
        'cancelled_by_team1': f"🚫 **Trade Proposal Withdrawn**\n{t1['short_name']} withdrew their trade proposal to {t2['short_name']} before you responded.{trade_summary_with_linebreak}",
        'completed': f"🏈 **Trade Completed!**\n{t1['short_name']} — {t2['short_name']} trade has been processed.{trade_summary_with_linebreak}Check the transaction log for full details.\n🔗 {trade_link}",
        'countered': f"↩️ **Trade Counter-Offer**\n{t2['short_name']} has sent a counter-offer on the trade with {t1['short_name']}.{trade_summary_with_linebreak}{notes_block}[Open NML](<{APP_URL}/>)",
        'auto_rejected_pick_used': f"🏈 **Trade Auto-Rejected**\nYour pending trade between {t1['short_name']} and {t2['short_name']} was automatically rejected because a pick in the offer was just used in the draft.{trade_summary_with_linebreak}{notes_block}If you'd like to propose a new trade, head over to the app.\n🔗 {APP_URL}/?view=trades",
    }

    msg = messages.get(action)
    if not msg:
        return

    if override:
        recipient_name = team['short_name'] or team['owner_name'] or 'owner'
        print(f"[Discord] TEST override active — sending DM to {override} (for {recipient_name}), action={action}")
        ok, err = bot_send_dm(override, f"🧪 **[TEST — DM to: {recipient_name}]**\n\n{msg}")
        print(f"[Discord] DM result: ok={ok}, err={err}")
    else:
        print(f"[Discord] Sending DM to team discord_user_id={team['discord_user_id']}, action={action}")
        send_discord_dm(team['discord_user_id'], msg)
