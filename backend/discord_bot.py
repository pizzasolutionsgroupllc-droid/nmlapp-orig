"""
Discord integration for NML League Manager
- Posts transactions to configured channels
- Sends DMs to owners for pending trade actions
- Uses Discord webhook or bot token
"""

import requests
import json
from database import get_db


def get_trade_summary(conn, trade_id):
    """
    Query trade_assets and build a formatted summary of the trade.
    Returns a string like:
    Team1 Name receive: Player Name (POS), 2027 1st (Original Team)
    Team2 Name receive: 2026 2nd (Original Team), Player Name (POS)
    """
    # Get trade with team names
    trade = conn.execute('''
        SELECT tr.id, tr.team1_id, tr.team2_id,
               t1.short_name as team1_name,
               t2.short_name as team2_name
        FROM trades tr
        JOIN teams t1 ON t1.id = tr.team1_id
        JOIN teams t2 ON t2.id = tr.team2_id
        WHERE tr.id = ?
    ''', (trade_id,)).fetchone()

    if not trade:
        return "Trade not found"

    # Get all assets for this trade
    assets = conn.execute('''
        SELECT ta.asset_type, ta.player_id, ta.pick_id, ta.from_team_id, ta.to_team_id,
               p.first_name, p.last_name, p.position,
               dp.year, dp.round, dp.round_order, dp.overall_order, t.short_name
        FROM trade_assets ta
        LEFT JOIN players p ON ta.player_id = p.id
        LEFT JOIN draft_picks dp ON ta.pick_id = dp.id
        LEFT JOIN teams t ON dp.original_owner_id = t.id
        WHERE ta.trade_id = ?
        ORDER BY ta.from_team_id, ta.asset_type
    ''', (trade_id,)).fetchall()

    if not assets:
        return "No assets in this trade"

    # Build lists for each team's receiving assets
    team1_receives = []
    team2_receives = []

    for asset in assets:
        if asset['asset_type'] == 'player' and asset['player_id']:
            # Format: "First Last (POS)"
            player_str = f"{asset['first_name']} {asset['last_name']} ({asset['position']})"
            if asset['to_team_id'] == trade['team1_id']:
                team1_receives.append(player_str)
            else:
                team2_receives.append(player_str)

        elif asset['asset_type'] == 'pick' and asset['pick_id']:
            pick_str = _fmt_pick(asset['year'], asset['round'], asset['round_order'], asset['overall_order'], asset['short_name'])
            if asset['to_team_id'] == trade['team1_id']:
                team1_receives.append(pick_str)
            else:
                team2_receives.append(pick_str)

    # Build the summary string
    lines = []
    if team1_receives:
        lines.append(f"{trade['team1_name']} receive: {', '.join(team1_receives)}")
    if team2_receives:
        lines.append(f"{trade['team2_name']} receive: {', '.join(team2_receives)}")

    return "\n\n".join(lines) if lines else "Trade with no assets"


def _ordinal(n):
    """Convert a number to ordinal (1 -> 1st, 2 -> 2nd, 3 -> 3rd, etc.)"""
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"


def _fmt_pick(year, round_num, round_order, overall_order, orig_abbrev):
    """Format a draft pick: Year Round [Round#] [Overall#] OrigTeam
    e.g. '2026 1 1 1 NYG' or '2027 2 DAL' if round/overall order unknown."""
    parts = [str(year), str(round_num)]
    if round_order:
        parts.append(str(round_order))
    if overall_order:
        parts.append(str(overall_order))
    parts.append(orig_abbrev)
    return ' '.join(parts)


DISCORD_API = 'https://discord.com/api/v10'


def get_setting(key):
    conn = get_db()
    row = conn.execute('SELECT value FROM league_settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else None


def get_headers():
    token = get_setting('discord_bot_token')
    if not token:
        return None
    return {
        'Authorization': f'Bot {token}',
        'Content-Type': 'application/json'
    }


def post_to_channel(channel_id, message):
    """Post a message to a Discord channel"""
    if not channel_id:
        return False, 'No channel ID configured'

    headers = get_headers()
    if not headers:
        return False, 'No bot token configured'

    try:
        res = requests.post(
            f'{DISCORD_API}/channels/{channel_id}/messages',
            headers=headers,
            json={'content': message},
            timeout=10
        )
        if res.status_code in (200, 201):
            return True, 'Posted successfully'
        return False, f'Discord error: {res.status_code} - {res.text}'
    except Exception as e:
        return False, str(e)


def send_dm(discord_user_id, message):
    """Send a DM to a Discord user"""
    if not discord_user_id:
        return False, 'No Discord user ID'

    headers = get_headers()
    if not headers:
        return False, 'No bot token configured'

    try:
        # Create DM channel
        dm_res = requests.post(
            f'{DISCORD_API}/users/@me/channels',
            headers=headers,
            json={'recipient_id': discord_user_id},
            timeout=10
        )
        if dm_res.status_code not in (200, 201):
            return False, f'Could not create DM channel: {dm_res.status_code}'

        dm_channel_id = dm_res.json().get('id')

        # Send message
        msg_res = requests.post(
            f'{DISCORD_API}/channels/{dm_channel_id}/messages',
            headers=headers,
            json={'content': message},
            timeout=10
        )
        if msg_res.status_code in (200, 201):
            return True, 'DM sent'
        return False, f'DM error: {msg_res.status_code}'
    except Exception as e:
        return False, str(e)


# ── Testing Mode Override ──────────────────────────────────────────────────

def get_test_override(conn=None):
    """Return override Discord user ID if testing mode is active, else None.
    Pass an open conn to avoid an extra DB round-trip."""
    if conn:
        row = conn.execute("SELECT value FROM league_settings WHERE key='test_mode_discord_id'").fetchone()
        return row['value'] if row and row['value'] else None
    return get_setting('test_mode_discord_id') or None


def _channel_label(channel_id):
    """Map a channel ID to a human-readable name using known settings keys."""
    mapping = [
        ('discord_draft_channel_id',        '#draft'),
        ('discord_trades_channel_id',       '#trades'),
        ('discord_transactions_channel_id', '#transactions'),
        ('discord_backup_channel_id',       '#backups'),
    ]
    for key, label in mapping:
        if get_setting(key) == channel_id:
            return label
    return f'channel {channel_id}'


# ── Trade Notifications ────────────────────────────────────────────────────

def notify_trade_pending(trade_id):
    """Notify Team 2 owner that they have a trade proposal waiting"""
    conn = get_db()
    trade = conn.execute('''
        SELECT tr.*,
            t1.short_name as team1_name,
            t2.short_name as team2_name,
            t2.discord_user_id as team2_discord_id,
            t2.owner_name as team2_owner
        FROM trades tr
        JOIN teams t1 ON t1.id = tr.team1_id
        JOIN teams t2 ON t2.id = tr.team2_id
        WHERE tr.id = ?
    ''', (trade_id,)).fetchone()

    if not trade or not trade['team2_discord_id']:
        conn.close()
        return False, 'No Discord ID for team 2 owner'

    trade_summary = get_trade_summary(conn, trade_id)
    override = get_test_override(conn)
    conn.close()

    msg = (
        f"🏈 **Trade Proposal from {trade['team1_name']}**\n"
        f"You have a new trade proposal waiting for your response.\n"
        f"\n{trade_summary}\n\n"
        f"Log in to NML League Manager to review and accept or reject.\n"
        f"Trade ID: #{trade_id}"
    )

    if override:
        msg = f"🧪 **[TEST — DM to: {trade['team2_name']}]**\n\n{msg}"
        return send_dm(override, msg)
    return send_dm(trade['team2_discord_id'], msg)


def notify_trade_accepted(trade_id):
    """Notify Team 1 that Team 2 accepted — needs final confirm"""
    conn = get_db()
    trade = conn.execute('''
        SELECT tr.*,
            t1.short_name as team1_name,
            t2.short_name as team2_name,
            t1.discord_user_id as team1_discord_id
        FROM trades tr
        JOIN teams t1 ON t1.id = tr.team1_id
        JOIN teams t2 ON t2.id = tr.team2_id
        WHERE tr.id = ?
    ''', (trade_id,)).fetchone()

    if not trade or not trade['team1_discord_id']:
        conn.close()
        return False, 'No Discord ID for team 1 owner'

    trade_summary = get_trade_summary(conn, trade_id)
    override = get_test_override(conn)
    conn.close()

    msg = (
        f"✅ **{trade['team2_name']} accepted your trade proposal!**\n"
        f"\n{trade_summary}\n\n"
        f"Log in to NML League Manager to give your final confirmation.\n"
        f"Trade ID: #{trade_id}"
    )

    if override:
        msg = f"🧪 **[TEST — DM to: {trade['team1_name']}]**\n\n{msg}"
        return send_dm(override, msg)
    return send_dm(trade['team1_discord_id'], msg)


def notify_trade_rejected(trade_id, rejected_by_team):
    """Notify the other team that trade was rejected"""
    conn = get_db()
    trade = conn.execute('''
        SELECT tr.*,
            t1.short_name as team1_name, t1.discord_user_id as team1_discord_id,
            t2.short_name as team2_name, t2.discord_user_id as team2_discord_id
        FROM trades tr
        JOIN teams t1 ON t1.id = tr.team1_id
        JOIN teams t2 ON t2.id = tr.team2_id
        WHERE tr.id = ?
    ''', (trade_id,)).fetchone()

    if not trade:
        conn.close()
        return False, 'Trade not found'

    trade_summary = get_trade_summary(conn, trade_id)
    override = get_test_override(conn)
    conn.close()

    if rejected_by_team == 'team2':
        notify_id = trade['team1_discord_id']
        recipient_name = trade['team1_name']
        msg = f"❌ **{trade['team2_name']} rejected your trade proposal.**\n\n{trade_summary}\n\nTrade ID: #{trade_id}"
    else:
        notify_id = trade['team2_discord_id']
        recipient_name = trade['team2_name']
        msg = f"❌ **{trade['team1_name']} cancelled the trade after your acceptance.**\n\n{trade_summary}\n\nTrade ID: #{trade_id}"

    if not notify_id and not override:
        return False, 'No Discord ID for recipient'

    if override:
        msg = f"🧪 **[TEST — DM to: {recipient_name}]**\n\n{msg}"
        return send_dm(override, msg)
    return send_dm(notify_id, msg)


def notify_trade_completed(trade_id, summary=None):
    """Notify both teams and post to trades channel"""
    conn = get_db()
    trade = conn.execute('''
        SELECT tr.*,
            t1.short_name as team1_name, t1.discord_user_id as team1_discord_id,
            t2.short_name as team2_name, t2.discord_user_id as team2_discord_id
        FROM trades tr
        JOIN teams t1 ON t1.id = tr.team1_id
        JOIN teams t2 ON t2.id = tr.team2_id
        WHERE tr.id = ?
    ''', (trade_id,)).fetchone()

    if not summary:
        summary = get_trade_summary(conn, trade_id)

    override = get_test_override(conn)
    conn.close()

    msg_dm = f"🎉 **Trade completed!**\n```\n{summary}\n```"

    if override:
        # Send both DMs to override with team labels
        send_dm(override, f"🧪 **[TEST — DM to: {trade['team1_name']}]**\n\n{msg_dm}")
        send_dm(override, f"🧪 **[TEST — DM to: {trade['team2_name']}]**\n\n{msg_dm}")
    elif trade:
        if trade['team1_discord_id']:
            send_dm(trade['team1_discord_id'], msg_dm)
        if trade['team2_discord_id']:
            send_dm(trade['team2_discord_id'], msg_dm)

    # Post to trades channel
    post_trades = get_setting('post_trades_to_discord')
    if post_trades == 'true':
        channel_id = get_setting('discord_trades_channel_id')
        channel_msg = f"🏈 **TRADE ALERT**\n```\n{summary}\n```"
        if override:
            label = _channel_label(channel_id)
            return send_dm(override, f"🧪 **[TEST — {label}]**\n\n{channel_msg}")
        return post_to_channel(channel_id, channel_msg)

    return True, 'Trade notifications sent'


# ── Transaction Notifications ──────────────────────────────────────────────

def post_transaction(tx_type, description, team_name=None):
    """Post a sign/cut/comp transaction to the transactions channel"""
    icons = {
        'sign_player': '✍️',
        'cut_player': '✂️',
        'comp_pick': '⭐',
    }

    setting_keys = {
        'sign_player': 'post_signings_to_discord',
        'cut_player': 'post_cuts_to_discord',
        'comp_pick': 'post_trades_to_discord',
    }

    should_post = get_setting(setting_keys.get(tx_type, ''))
    if should_post != 'true':
        return False, 'Posting disabled for this transaction type'

    channel_id = get_setting('discord_transactions_channel_id')
    if not channel_id and not get_test_override():
        return False, 'No transactions channel configured'

    icon = icons.get(tx_type, '📋')
    msg = f"{icon} {description}"

    override = get_test_override()
    if override:
        label = _channel_label(channel_id) if channel_id else '#transactions'
        return send_dm(override, f"🧪 **[TEST — {label}]**\n\n{msg}")
    return post_to_channel(channel_id, msg)


def delete_message(channel_id, message_id):
    """Delete a message from a Discord channel"""
    if not channel_id or not message_id:
        return False, 'Missing channel or message ID'
    token = get_setting('discord_bot_token')
    if not token:
        return False, 'No bot token configured'
    headers = {'Authorization': f'Bot {token}'}
    try:
        res = requests.delete(
            f'{DISCORD_API}/channels/{channel_id}/messages/{message_id}',
            headers=headers,
            timeout=10
        )
        if res.status_code == 204:
            return True, 'Message deleted'
        return False, f'Discord error: {res.status_code} - {res.text}'
    except Exception as e:
        return False, str(e)


def post_backup_to_discord(xlsx_bytes, filename):
    """Post backup xlsx file to the backup channel, replacing the previous backup message"""
    channel_id = get_setting('discord_backup_channel_id')
    if not channel_id:
        return False, 'No backup channel configured (set discord_backup_channel_id in settings)'

    token = get_setting('discord_bot_token')
    if not token:
        return False, 'No bot token configured'

    # Delete previous backup message so we don't fill up Discord storage
    old_msg_id = get_setting('backup_discord_message_id')
    if old_msg_id:
        delete_message(channel_id, old_msg_id)

    # Post new file as multipart (no Content-Type header — requests sets it automatically)
    headers = {'Authorization': f'Bot {token}'}
    try:
        res = requests.post(
            f'{DISCORD_API}/channels/{channel_id}/messages',
            headers=headers,
            files={
                'file': (filename, xlsx_bytes,
                         'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            },
            data={'content': f'📊 **NML League Backup** — {filename}'},
            timeout=30
        )
        if res.status_code in (200, 201):
            new_msg_id = res.json().get('id')
            # Persist message ID so next backup can delete it
            conn = get_db()
            conn.execute(
                "INSERT OR REPLACE INTO league_settings (key, value) VALUES ('backup_discord_message_id', ?)",
                (new_msg_id,)
            )
            conn.commit()
            conn.close()
            return True, 'Backup posted to Discord'
        return False, f'Discord error: {res.status_code} - {res.text}'
    except Exception as e:
        return False, str(e)


def test_connection():
    """Test Discord bot token and channel access"""
    headers = get_headers()
    if not headers:
        return {'ok': False, 'error': 'No bot token configured in settings'}

    try:
        res = requests.get(f'{DISCORD_API}/users/@me', headers=headers, timeout=10)
        if res.status_code == 200:
            bot = res.json()
            return {'ok': True, 'bot_name': bot.get('username'), 'bot_id': bot.get('id')}
        return {'ok': False, 'error': f'Invalid token: {res.status_code}'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ── Trade Block ────────────────────────────────────────────────────────────

def post_tradeblock_to_discord(team_id):
    """Build and post (or update) a team's trade block message to the tradeblock channel.
    If the team has nothing on the block, deletes any existing post and returns.
    Replaces the previous message so the channel stays clean (one post per team)."""

    channel_id = get_setting('discord_tradeblock_channel_id')
    if not channel_id:
        return False, 'No tradeblock channel configured'

    token = get_setting('discord_bot_token')
    if not token:
        return False, 'No bot token configured'

    conn = get_db()

    # ── Gather all data ──────────────────────────────────────────────────
    team = conn.execute('SELECT * FROM teams WHERE id = ?', (team_id,)).fetchone()
    if not team:
        conn.close()
        return False, 'Team not found'

    players = conn.execute('''
        SELECT first_name, last_name, position, overall_rating, age, trade_block_note
        FROM players
        WHERE nml_team_id = ? AND on_trade_block = 1 AND is_free_agent = 0
        ORDER BY position, last_name
    ''', (team_id,)).fetchall()

    picks = conn.execute('''
        SELECT dp.year, dp.round, dp.round_order, dp.overall_order,
               dp.trade_block_note, orig.abbreviation AS orig_abbrev
        FROM draft_picks dp
        JOIN teams orig ON orig.id = dp.original_owner_id
        WHERE dp.current_owner_id = ? AND dp.on_trade_block = 1
          AND NOT EXISTS (SELECT 1 FROM draft_selections ds WHERE ds.draft_pick_id = dp.id)
        ORDER BY dp.year, dp.round
    ''', (team_id,)).fetchall()

    needs_rows = conn.execute(
        "SELECT item_type, item_key, tier FROM team_needs WHERE team_id = ? ORDER BY tier, tier_order",
        (team_id,)
    ).fetchall()

    old_msg_id = team['trade_block_message_id']

    # ── Nothing on the block → delete post and bail ───────────────────────
    if not players and not picks:
        if old_msg_id:
            delete_message(channel_id, old_msg_id)
            conn.execute("UPDATE teams SET trade_block_message_id = NULL WHERE id = ?", (team_id,))
            conn.commit()
        conn.close()
        return True, 'Block is empty — post removed'

    # ── Build message text ────────────────────────────────────────────────
    team_name = team['short_name'] or team['full_name'] or 'Unknown'
    lines = [f"**{team_name} Trade Block**"]

    # Team note (read from tradeblock_note column)
    note = (team['tradeblock_note'] or '').strip()
    if note:
        lines.append(note)

    # Team needs by tier, picks formatted as YY-R (e.g. 26-1)
    def _fmt_need(item_type, item_key):
        if item_type == 'pick':
            parts = item_key.split('_')
            if len(parts) == 2:
                yr = str(parts[0])[-2:]
                return f"{yr}-{parts[1]}"
        return item_key.upper()

    tier_labels = {'high': 'High', 'medium': 'Med', 'low': 'Low'}
    tier_items = {'high': [], 'medium': [], 'low': []}
    for row in needs_rows:
        tier_items[row['tier']].append(_fmt_need(row['item_type'], row['item_key']))
    needs_parts = []
    for tier in ('high', 'medium', 'low'):
        if tier_items[tier]:
            needs_parts.append(f"{tier_labels[tier]}: {', '.join(tier_items[tier])}")
    if needs_parts:
        lines.append("**Team Needs**")
        lines.extend(needs_parts)

    # Assets
    lines.append("**Available**")
    PO = ['QB','HB','FB','WR','TE','LT','LG','C','RG','RT','DT','LEDGE','REDGE','SAM','MIKE','WILL','CB','FS','SS','K','P','LS']
    sorted_players = sorted(players, key=lambda p: (PO.index(p['position']) if p['position'] in PO else 99))
    for p in sorted_players:
        pos  = p['position'] or ''
        name = f"{p['first_name']} {p['last_name']}"
        ovr  = str(p['overall_rating']) if p['overall_rating'] else ''
        age  = str(p['age']) if p['age'] else ''
        parts = [x for x in [pos, name, ovr, age] if x]
        asset_line = ' '.join(parts)
        if p['trade_block_note']:
            asset_line += f" - {p['trade_block_note']}"
        lines.append(asset_line)

    for pk in picks:
        pick_line = _fmt_pick(pk['year'], pk['round'], pk['round_order'], pk['overall_order'], pk['orig_abbrev'])
        if pk['trade_block_note']:
            pick_line += f" - {pk['trade_block_note']}"
        lines.append(pick_line)

    message = '\n'.join(lines)

    # ── Delete old message, post new one ──────────────────────────────────
    if old_msg_id:
        delete_message(channel_id, old_msg_id)

    headers = {'Authorization': f'Bot {token}', 'Content-Type': 'application/json'}
    try:
        res = requests.post(
            f'{DISCORD_API}/channels/{channel_id}/messages',
            headers=headers,
            json={'content': message},
            timeout=10
        )
        if res.status_code in (200, 201):
            new_msg_id = res.json().get('id')
            conn.execute("UPDATE teams SET trade_block_message_id = ? WHERE id = ?", (new_msg_id, team_id))
            conn.commit()
            conn.close()
            return True, 'Trade block posted'
        conn.close()
        return False, f'Discord error: {res.status_code} - {res.text}'
    except Exception as e:
        conn.close()
        return False, str(e)


# ── Draft Notifications ────────────────────────────────────────────────────

def notify_draft_on_clock(team_id, pick_num, round_num, time_limit_seconds):
    """Notify a team that it's their turn to pick"""
    conn = get_db()
    team = conn.execute('SELECT short_name, discord_user_id FROM teams WHERE id=?', (team_id,)).fetchone()
    override = get_test_override(conn)
    conn.close()
    if not team:
        return
    recipient = override or team['discord_user_id']
    if not recipient:
        return
    minutes = time_limit_seconds // 60
    prefix = f"🧪 **[TEST — DM to: {team['short_name']}]**\n\n" if override else ""
    msg = (f"{prefix}🏈 **You're on the clock!**\n"
           f"Pick #{pick_num} | Round {round_num}\n"
           f"Time limit: {minutes} minutes\n"
           f"Log in to the NML app to submit your pick.")
    send_dm(recipient, msg)


def notify_draft_on_deck(team_id, pick_num, round_num):
    """Notify a team they're on deck (next to pick)"""
    conn = get_db()
    team = conn.execute('SELECT short_name, discord_user_id FROM teams WHERE id=?', (team_id,)).fetchone()
    override = get_test_override(conn)
    conn.close()
    if not team:
        return
    recipient = override or team['discord_user_id']
    if not recipient:
        return
    prefix = f"🧪 **[TEST — DM to: {team['short_name']}]**\n\n" if override else ""
    msg = (f"{prefix}📋 **You're on deck!**\n"
           f"Pick #{pick_num} | Round {round_num}\n"
           f"Prepare your pick — you'll be notified when it's your turn.")
    send_dm(recipient, msg)


def notify_draft_skipped(team_id, pick_num):
    """Notify a team their pick was skipped due to timer expiry"""
    conn = get_db()
    team = conn.execute('SELECT short_name, discord_user_id FROM teams WHERE id=?', (team_id,)).fetchone()
    override = get_test_override(conn)
    conn.close()
    if not team:
        return
    recipient = override or team['discord_user_id']
    if not recipient:
        return
    prefix = f"🧪 **[TEST — DM to: {team['short_name']}]**\n\n" if override else ""
    msg = (f"{prefix}⏰ **Your pick was skipped!**\n"
           f"Pick #{pick_num} timer expired.\n"
           f"You can still make this pick as a makeup pick anytime before the draft ends.")
    send_dm(recipient, msg)


def notify_draft_pick_made(team_id, player_name, position, overall_order,
                           round_num=None, round_order=None,
                           school=None, is_rookie_prospect=None, is_write_in=False,
                           _override_team_name=None, submitted_by=None):
    """Post pick announcement to the dedicated draft channel"""
    conn = get_db()
    if _override_team_name:
        full_name = _override_team_name
    else:
        team = conn.execute('SELECT full_name FROM teams WHERE id=?', (team_id,)).fetchone()
        if not team:
            conn.close()
            return
        full_name = team['full_name']
    draft_channel = conn.execute("SELECT value FROM league_settings WHERE key='discord_draft_channel_id'").fetchone()
    override = get_test_override(conn)
    conn.close()

    if not draft_channel or not draft_channel['value']:
        return

    if is_write_in or not is_rookie_prospect:
        school_part = 'FA'
    else:
        school_part = school or 'FA'

    round_part = f'Round {round_num} Pick {round_order} #{overall_order}' if round_num and round_order else f'#{overall_order}'
    msg = f"🏈 **{round_part} {full_name} {position} {player_name} {school_part}**"
    if submitted_by:
        msg += f"\n*Submitted by {submitted_by} on behalf of {full_name}*"

    if override:
        label = _channel_label(draft_channel['value'])
        send_dm(override, f"🧪 **[TEST — {label}]**\n\n{msg}")
    else:
        post_to_channel(draft_channel['value'], msg)
