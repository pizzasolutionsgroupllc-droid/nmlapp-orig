# User Profile Spec

**Status:** Draft for Phase 1 (April 2026)
**Author:** Claude + Jon

---

## Purpose

Today's user profile is minimal — display name, Discord avatar, optional Twitch URL. This spec defines the full profile each user should have once Phase 1 ships, balancing identity, gaming-specific identifiers, contact, notification routing, privacy, and league-aware fields.

This doc is also forward-compatible with the Phase 2 multi-league SaaS vision — fields are split into **global** (apply to the user across all leagues they're in) vs **per-league** (apply only within a specific league).

---

## Section 1 — Identity (global)

These fields apply to the user as a person, regardless of which league they're in.

| Field | Type | Editable | Notes |
|---|---|---|---|
| `display_name` | text | yes | Already exists. What shows up across the app. |
| `first_name` | text | yes | Real first name. For game scheduling and league nights. |
| `last_name` | text | yes | Optional. |
| `email` | text | yes | Backup contact + future password reset path if Discord ever fails. Validated format. |
| `phone` | text | yes | E.164 format preferred. Used for SMS notifications. |
| `timezone` | enum (IANA) | yes | e.g. `America/Los_Angeles`. Critical for scheduling features and notification quiet hours. |
| `avatar_url` | text | yes | Already exists (Discord avatar). User can override with custom upload. |
| `bio` | text (long) | yes | Free-text "about me." Optional. |

---

## Section 2 — Discord identity (global)

| Field | Type | Editable | Notes |
|---|---|---|---|
| `discord_id` | text | no | Already exists. System-managed. |
| `discord_username` | text | no (auto-pulled) | Already exists. Global Discord handle. |
| `discord_server_nickname` | text | yes | Per-server nickname users often customize. Different from global handle. |

---

## Section 3 — Gaming identity (global)

For Madden / sports leagues. Tied to the user across leagues since people typically don't change their console identifiers.

| Field | Type | Editable | Notes |
|---|---|---|---|
| `xbox_gamertag` | text | yes | Needed for stats attribution (long-term wishlist). |
| `psn_id` | text | yes | PlayStation Network ID. |
| `steam_name` | text | yes | Per Jon's add — for PC titles or cross-game leagues. |
| `primary_console` | enum | yes | Xbox / PS5 / PC / Other. Helps cross-play coordination. |
| `stream_url` | text | yes | Renamed from `twitch_url` to be platform-agnostic (Twitch / YouTube / Kick). **Always public** per Jon — used for matchup pages. |

---

## Section 4 — League membership (per-league)

These fields are scoped per league a user belongs to. In Phase 1 there's only NML, but the schema is built to generalize.

| Field | Type | Editable | Notes |
|---|---|---|---|
| `role` | enum | by admin | Already exists (creator / commissioner / assistant_commissioner / owner / readonly). |
| `team_id` | int | by admin | Already exists. Current team ownership. |
| `joined_at` | datetime | no | Auto-tracked when user is added to a league. |
| `years_in_league` | computed | no | Derived from `joined_at` to today. Generic label, not NML-specific. Displays as "3 seasons" / "Joined 2024." |

### Team ownership history (per-league)

Per Jon's item 21 — track which teams a user has owned across time within a league.

New table: `user_team_history`

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `user_id` | FK → users | |
| `league_id` | FK → leagues (Phase 2) | Phase 1 implicitly NML. |
| `team_id` | FK → teams | |
| `started_at` | date | When they took over this team. |
| `ended_at` | date (nullable) | NULL = current. |

Profile displays it as a timeline: "Team X (2021–2023) → Team Y (2024) → Team Z (2025–present)."

---

## Section 5 — Favorite teams (per-league, sport-aware)

Per Jon's item 19 — only applies to football leagues. Multi-select. Includes both NFL and NCAA (college) teams.

New table: `user_favorite_teams`

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `user_id` | FK → users | |
| `league_id` | FK → leagues | So favorites are scoped to the league context (some leagues may disable this entirely). |
| `team_type` | enum | `nfl` / `ncaa` |
| `team_code` | text | e.g. `BAL`, `MICH` |

Profile UI shows two grids (NFL teams, NCAA teams) where users can toggle multiple selections each. Display with team logos on the profile page. Hidden entirely if the league type isn't football.

---

## Section 6 — Notification preferences (per-league)

Per Jon's items 22–27 with his refinements:

- Each notification type can route to **one or more channels simultaneously** (e.g. Discord + SMS for the same event).
- The available channels per notification type are **constrained by what the league has enabled**. If a league hasn't configured Discord at all, "Discord" isn't an option for any user in that league.
- Quiet hours **dropped** (item 28) — phone-level Do Not Disturb already handles this; batching is too much complexity for too little value.

### Channel availability (per-league)

New table: `league_notification_channels` — controls what each league offers as options.

| Column | Type | Notes |
|---|---|---|
| `league_id` | FK | |
| `channel` | enum | `discord_dm`, `sms`, `email`, `in_app` |
| `enabled` | bool | Commissioner toggles per league. |

### Per-user notification matrix

New table: `user_notification_prefs`

| Column | Type | Notes |
|---|---|---|
| `id` | PK | |
| `user_id` | FK | |
| `league_id` | FK | |
| `event_type` | enum | See list below. |
| `channel` | enum | `discord_dm` / `sms` / `email` / `in_app` |
| `enabled` | bool | One row per (event_type × channel) — multiple rows per event allowed for multi-channel delivery. |

### Event types covered

1. `trade_proposed_to_me` — your team received a trade offer.
2. `trade_accepted` — your proposed trade was accepted.
3. `trade_rejected` — your proposed trade was rejected.
4. `trade_countered` — your proposed trade got a counter-offer.
5. `watchlist_player_traded` — a player on your watchlist changed teams.
6. `commissioner_announcement` — admin posted a league-wide message.
7. `power_rankings_published` — new weekly power rankings dropped.
8. `game_scheduled` — your matchup was scheduled (future smart-scheduling feature).
9. `game_time_changed` — opponent rescheduled an existing matchup.
10. `draft_on_the_clock` — your turn in a live draft.
11. `draft_on_deck` — you're up next in a live draft.

UI: a grid on the profile page — events down the left, channels across the top, checkboxes in each cell. Channels disabled at the league level appear greyed out with a tooltip ("Discord notifications not enabled for this league").

---

## Section 7 — Privacy controls (global, but apply within league context)

Per Jon's items 31–33:

| Field | Type | Default | Notes |
|---|---|---|---|
| `privacy_show_phone` | enum | `commissioners_only` | Options: `nobody` / `commissioners_only` / `all_owners`. |
| `privacy_show_email` | enum | `commissioners_only` | Same options as above. |
| `privacy_show_stream_url` | n/a | always public | Per Jon — stream URL is intentionally always public. |

Real names (`first_name`, `last_name`) and phone/email respect these settings on any view of another user's profile.

---

## Section 8 — App preferences (global)

| Field | Type | Default | Notes |
|---|---|---|---|
| `theme` | enum | `dark` | Options: `light` / `dark` / `system`. Per Jon — default everyone to dark. |
| `time_format` | enum | `12h` | Options: `12h` / `24h`. |

Game-specific preferences like default depth chart formations stay inside the Madden league app — not part of this profile (per Jon's item 36).

---

## Section 9 — Schema summary

New / modified tables introduced by this spec:

1. **`users`** — extend with: `first_name`, `last_name`, `email`, `phone`, `timezone`, `bio`, `discord_server_nickname`, `xbox_gamertag`, `psn_id`, `steam_name`, `primary_console`, `theme`, `time_format`, `privacy_show_phone`, `privacy_show_email`. Rename `twitch_url` → `stream_url`.
2. **`user_team_history`** — new. Tracks teams owned over time per user per league.
3. **`user_favorite_teams`** — new. Multi-select NFL/NCAA team favorites.
4. **`league_notification_channels`** — new. Per-league config of available notification channels.
5. **`user_notification_prefs`** — new. Per-user × per-event × per-channel routing matrix.

---

## Section 10 — UI structure

The profile page should be tabbed for clarity:

1. **Identity** — name, contact, timezone, bio, avatar.
2. **Gaming** — Discord nickname, console IDs, primary console, stream URL.
3. **My Teams** — current team + ownership history timeline + favorite NFL/NCAA teams.
4. **Notifications** — the event × channel matrix, with disabled-channel tooltips.
5. **Privacy** — visibility toggles for phone, email.
6. **Preferences** — theme, time format.

Each tab saves independently (small forms beat one giant form). Inline validation on email and phone.

---

## Section 11 — Cross-user view

A user clicking another league member's name should see a **public profile card**:

- Avatar + display name
- Years in league + current team
- Team ownership history timeline
- Favorite NFL/NCAA teams
- Stream URL (always public)
- Real name + phone + email — only shown if their privacy settings allow it for the viewer's role

No other fields visible cross-user. No way to discover a user's notification preferences, app preferences, or contact info beyond what privacy controls explicitly permit.

---

## Section 12 — Rollout in Phase 1

This profile spec ships as part of Step 15 (Authorization model & data isolation) of the Django migration plan. The work breaks into:

1. **Migrate existing fields** as-is (display_name, avatar, twitch→stream_url).
2. **Add new columns to `users`** via Django migration. All nullable so existing users aren't broken.
3. **Create the four new tables** (history, favorites, channel availability, notification prefs).
4. **Build the tabbed profile page** with HTMX-driven save-per-tab.
5. **Build the public profile card** as a separate template, respecting privacy gates.
6. **Backfill notification prefs** with sensible defaults for existing users (Discord on for trade events, off for everything else) so no one gets spammed at launch.
7. **Backfill `joined_at`** from earliest known `last_login` for existing users (best-effort).

Estimated effort: ~3–4 focused hours, included in the Step 15 envelope.

---

## Open Questions / Future Considerations

- Should `email` ever become the primary login (vs. Discord-required)? Punting to Phase 2.
- Should public profile have a vanity URL like `/u/jvantrease`? Punting.
- Profile photo upload: store in `media/` locally, S3 in Phase 2 if going SaaS.
- Notification batching/digest mode (e.g. "send me one daily summary instead of per-event"): not in scope for Phase 1; revisit if users complain.
