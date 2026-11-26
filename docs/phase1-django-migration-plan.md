# Phase 1 Migration Plan — Flask → Django Re-Foundation

**Status:** Draft for review (April 2026)
**Author:** Claude + Jon (drafting in Cowork)

---

## Overview

Phase 1 re-founds NML on the Django stack used at Jon's work, while keeping the app **single-tenant** (just the NML league) and **hosted on Railway**. The goal is feature parity with the current Flask app, on the modern stack, with cleanly organized code, ready for multi-tenant work in Phase 2.

### In scope

- Flask → Django 5.2
- SQLite → Postgres in production (SQLite stays in development)
- Vanilla JS in `nml-app.html` → Django templates + HTMX
- Hand-written CSS → Tailwind (via CDN, like work)
- Monolithic `app.py` → Django apps (modular)
- Add Docker, Sentry, GitHub Actions
- All existing features ship with full parity

### Not in scope (deferred to later phases)

- Multi-tenancy (Phase 2 — using the work team's middleware pattern)
- Sport abstraction (Phase 3)
- Billing / SaaS UI (Phase 4)
- Oracle Cloud + Kubernetes (Phase 5 — defer until needed or wanted for practice)
- Any new features beyond what currently exists
- Visual redesign of the UI (we replicate the current look in Tailwind, then redesign later if desired)

---

## Target Architecture

### Project layout

```
nmlapp/
├── config/                 # Django settings: base.py, dev.py, prod.py, test.py
├── core/                   # Base models, middleware, utilities, permissions
├── accounts/               # User, profile, Discord OAuth, roles
├── leagues/                # League entity (just NML in Phase 1; foundation for Phase 2)
├── teams/                  # Team, owner relationships, depth charts
├── players/                # Player, ratings, prospects, watchlist, ratings history
├── trades/                 # Trades, assets, magic links, trade grader
├── drafts/                 # Mock drafts, big board, NFL tracker, draft history
├── rankings/               # Power rankings + snapshots
├── transactions/           # Transaction log, free-agent moves, etc.
├── notifications/          # Discord bot, email digests, alerts
├── importer/               # CSV/XLSX imports (replaces backend/importer.py)
├── templates/              # Django HTML templates (HTMX-driven)
├── static/                 # CSS, JS, images
├── media/                  # User-uploaded files (logos, avatars)
├── kubernetes/             # Placeholder for Phase 5 K8s manifests
└── .github/workflows/      # GitHub Actions CI/CD
```

### Stack mapped to current code

| Current | Target | Notes |
|---|---|---|
| Python 3 / Flask | Python 3.13+ / Django 5.2 | Direct upgrade |
| `app.py` (5,400 lines) | Django apps (one per domain) | Modular split |
| Raw SQL via `sqlite3` | Django ORM | Auto-generated migrations |
| `database.py` | Django models + `migrations/` | Schema as code |
| SQLite (always) | SQLite (dev) / Postgres 15+ (prod) | Same as work team |
| `auth.py` | Django built-in auth + `accounts/` app | Session-based, no JWTs |
| `nml-app.html` (9,200 lines) | Django templates + HTMX | One template per page |
| Hand-written CSS | Tailwind via CDN | Utility-first |
| `discord_bot.py` | `notifications/` app + `django-tasks` | Background jobs in DB |
| `importer.py` | `importer/` app | Same logic, Django-native |
| `Procfile` (gunicorn) | Same gunicorn + `Dockerfile` | Containerized |
| Manual push to Railway | GitHub Actions → Railway | Automated CI/CD |
| `print` / Flask logs | Sentry | Error monitoring |
| pip / venv | uv | Faster, modern tooling |
| (no linter) | Ruff | Auto-format on save |
| (no tests) | pytest + pytest-django | Tests for new code; backfill critical paths |

---

## Migration Sequence

Each step is mergeable on its own. The live Flask app stays running and untouched until the final cutover step.

### Step 1: Scaffold + tooling
Set up the Django project, install uv, configure Ruff and pytest, set up dev/prod settings split, initialize git workflow. No app code yet.

### Step 2: Database models
Define Django ORM models that mirror the existing SQLite schema exactly. Every existing column becomes a Django field with the right type and constraints. No data migrated yet — just the schema.

### Step 3: Data migration script
Write a one-time script that reads from the existing SQLite database and writes into the new Django models. Run against a dev copy first; verify row counts and integrity. Production cutover uses the same script later.

### Step 4: Auth and accounts
Migrate user auth to Django's built-in auth system. Wire up Discord OAuth. Verify login/logout, role checks (commissioner / assistant_commissioner / owner), session persistence.

### Step 5: Read-only player & team views
Build the All Players, All Teams, Team Detail, and Player Modal pages on Django + HTMX. Read-only first — no writes yet. Confirms the template + HTMX pattern works for the most-used views.

### Step 6: Teams module (writes)
CRUD for teams, owner assignment, depth chart edits, tradeblock notes, team needs. Verify writes go through cleanly.

### Step 7: Players module (writes)
Roster moves, watchlist, ratings updates, prospect management.

### Step 8: Trades module
Proposals, accept/reject, magic links from Discord, trade grader, trade history.

### Step 9: Drafts module
Mock drafts, big board (with drag-and-drop via HTMX + Sortable.js), NFL tracker, draft prospects.

### Step 10: Rankings, transactions, notifications
Power rankings calculation, transaction log, Discord bot via django-tasks.

### Step 11: CSV/XLSX importer
Migrate the existing importer logic into a Django app.

### Step 12: Tailwind styling pass
Replace the current CSS with Tailwind utility classes. Match the current visual design as closely as possible — no redesign in this phase.

### Step 13: Docker, Sentry, GitHub Actions
Containerize, hook up error monitoring, automate deploys.

### Step 14: Anti-copy & legal protections
Three small but worthwhile additions before cutover:
- **Site-wide footer** in the base template with copyright line: `© 2026 NML — All rights reserved.` plus a link to the Terms page.
- **Terms of Service page** (simple Django template at `/terms`) covering: private league use only, no scraping/copying/reverse-engineering, no redistribution of league data, account use is non-transferable. Plain language, one page.
- **Rate limiting** using `django-ratelimit` (or Django's built-in cache-backed throttling). Sensible defaults: ~60 requests/minute per IP on read endpoints, ~20/minute on write endpoints, ~5/minute on auth/login endpoints. Returns HTTP 429 when exceeded. Logged so we can spot abuse.

These don't stop a determined copier but they raise the floor: legal teeth via the Terms, attribution via the footer, and automated bot deterrence via rate limits. Skipping fancy obfuscation/DRM by design — high effort, low return.

### Step 15: Authorization model & data isolation
Defending against authenticated insiders (league members trying to see another member's trade ideas, watchlists, or creator-only data). The Flask audit (April 2026) confirmed several endpoints currently rely on UI-only role gates or have no auth at all — Django rebuild fixes this systemically.

- **Default-deny permission decorators** on every view. Standard set: `@login_required`, `@team_owner_required(team_id)`, `@trade_party_required(trade_id)`, `@commissioner_required`, `@creator_required`. No view ships without one.
- **Queryset filtering at the source** — list endpoints physically cannot return another user's records. Example: `Trade.objects.visible_to(request.user)` returns only trades where the user is commissioner OR owner of either involved team. Same pattern for watchlists, mock drafts, big board entries.
- **Object-level ownership checks** with 404 (not 403) responses for unauthorized access — doesn't even confirm the record exists.
- **Settings page + all subtabs** locked to commissioner role server-side, not just hidden in the UI. Includes league settings, trade grader weights, depth chart eligibility, role assignment, importer, backup trigger, test_mode_discord_id.
- **User profile completeness pass** — current profile is minimal (display name, avatar, twitch URL). Decide what additional fields each user should see/edit on their own profile (e.g. notification preferences, default formation, contact prefs) and build the profile page properly. Each user only ever sees/edits their own profile; admins can view all via admin panel.
- **Privilege escalation patches** — assistant_commissioner cannot grant themselves commissioner role. Role changes logged.
- **Authorization test suite** — for every sensitive endpoint, write a "User B logs in and tries to access User A's stuff" test that asserts denial. Becomes part of the test-as-we-go discipline. This is the regression-proof safety net.
- **Lightweight audit log table** — who, when, what action, what record. Records sensitive actions (trade respond, role change, settings save, viewing another user's data via admin). Not user-visible — for forensic use only.

### Step 16: Production cutover
Per Decision 4: thorough local smoke-test of every page on the new Django version. Take a fresh snapshot of production data. Run the data migration against it on a staging deployment. Verify. Pick a low-traffic window. Deploy the Django version to Railway alongside Flask. Switch traffic. Keep Flask version available on Railway for 48 hours for instant rollback. Retire Flask after the soak window.

---

## What Stays vs. What Changes

### Stays the same

- **Domain logic and business rules** — trade grader formula, power rankings formula, depth chart eligibility rules, draft pick value tables, sorting rules (always `first_name`), commissioner-only gates, etc.
- **Database schema (with cleanup)** — existing tables and columns map to Django models 1:1; we may rename a few inconsistent columns but no schema redesign.
- **The single-page-app feel** — HTMX preserves the "click without full page reload" experience. Users won't notice a difference in feel.
- **Discord bot logic** — same DMs, same magic-link flow, same backup bot. Just wired through django-tasks instead of standalone scripts.
- **CSV import logic** — existing import behavior preserved.
- **Railway hosting** — no infrastructure migration in Phase 1.

### Changes

- **Framework** — Flask → Django.
- **Routing** — Flask `@app.route` → Django `urls.py` per app.
- **Database access** — raw SQL → Django ORM (huge readability win, also auto-generates migrations).
- **Frontend** — `nml-app.html` becomes ~30 small templates, one per page or partial. HTMX handles dynamic updates.
- **Auth** — custom `auth.py` → Django's built-in auth.
- **File structure** — monolithic `app.py` → focused Django apps.
- **Tooling** — pip → uv. No linter → Ruff. No tests → pytest.
- **Containerization** — `Procfile` only → `Dockerfile` + `docker-compose.yml`.
- **CI/CD** — manual push → GitHub Actions on every commit.
- **Error monitoring** — print/logs → Sentry.

---

## Effort Estimates (Focused Work Hours)

These are realistic estimates for synchronous Cowork pair-programming, not industry team estimates. Each line item assumes I've read the existing code and we're working through it together with no external dependencies blocking.

| Step | Estimate | Notes |
|---|---|---|
| 1. Scaffold + tooling | 1–2 hours | Mostly mechanical; uv/Ruff/pytest configs |
| 2. Database models | 4–6 hours | ~30 tables to translate |
| 3. Data migration script | 2–3 hours | Plus testing against snapshot |
| 4. Auth + accounts | 3–5 hours | Discord OAuth is the unknown |
| 5. Read-only views | 4–6 hours | Players, teams, modal |
| 6. Teams module (writes) | 3–4 hours | CRUD + depth chart |
| 7. Players module (writes) | 3–4 hours | Roster, watchlist, ratings |
| 8. Trades module | 5–7 hours | Largest single domain |
| 9. Drafts module | 4–6 hours | Big board drag-drop is the tricky bit |
| 10. Rankings + transactions + notifications | 3–4 hours | Mostly logic moves |
| 11. CSV importer | 2 hours | Direct port |
| 12. Tailwind styling pass | 6–10 hours | Volume of pages, but mechanical |
| 13. Docker + Sentry + Actions | 2–3 hours | One-time setup |
| 14. Anti-copy & legal protections | 1–2 hours | Footer + Terms page + rate limiting |
| 15. Authorization model & data isolation | 5–7 hours | Permissions, queryset filtering, audit log, profile pass, auth tests |
| 16. Production cutover | 2–3 hours | Including verification time |
| **Subtotal (no tests)** | **50–74 focused hours** | |
| Test-as-we-go overhead | +30–40% across all steps | Per Decision 2 |
| **Total with test-as-we-go** | **66–102 focused hours** | |

In Cowork session terms, that's roughly **8–12 long focused sessions** (assuming ~6–8 productive hours per session). Could compress further if we run hot.

The biggest unknowns that could expand scope:

- Discord OAuth integration with Django (vs. our current custom flow)
- Drag-and-drop on the big board with HTMX (need to evaluate Sortable.js + HTMX patterns)
- Migrating any data that has tricky constraints or weird historical values

If any of these blow up, I'll flag it the moment we hit it instead of silently grinding.

---

## Risks & Mitigations

1. **Risk:** Data migration loses or corrupts data.
   **Mitigation:** Always work from a snapshot. Test the migration script against multiple snapshots before touching prod. Keep Flask version live during cutover for instant rollback.

2. **Risk:** Discord bot integration breaks during migration.
   **Mitigation:** Migrate the bot logic last (Step 10), after the rest is stable. Keep the existing bot running until the new one is verified.

3. **Risk:** HTMX patterns don't cover something the current vanilla JS does (e.g., the big board drag-drop, complex modal interactions).
   **Mitigation:** Spike each tricky interaction first before committing to the pattern. HTMX has well-documented escape hatches (Alpine.js for client-side state, hx-ws for live updates, etc.).

4. **Risk:** Tailwind utility classes feel verbose vs. current hand-written CSS.
   **Mitigation:** Use Tailwind's `@apply` directive for repeated patterns. Match work team's approach — they handle it fine.

5. **Risk:** Live users hit issues during cutover.
   **Mitigation:** Cutover at a low-traffic time. Have rollback ready. Communicate downtime in advance via Discord.

---

## Resolved Decisions (locked in April 2026)

1. **Visual design — preserve current look, with select free-win polish from the new framework.**
   No redesign. But during migration we take advantage of these "free wins" that don't change visual identity:
   - Django admin panel (auto-generated superuser UI for all tables)
   - Built-in pagination on long list pages
   - HTMX loading indicators (automatic spinners during slow operations)
   - Inline form validation with field-level error rendering
   - Proper default 404 / 500 error pages
   - Django Debug Toolbar in dev for catching slow queries proactively

2. **Test coverage — test-as-we-go, not backfill.**
   Every business logic function (trade grader, power rankings, pick value, etc.) gets unit tests. Every API endpoint gets request/response shape tests. Every model gets constraint/validation tests. Critical flows (login, propose trade, accept trade, mock draft save) get integration tests. Adds roughly 30–40% to each step's time, but no production surprises is worth it.

3. **Branch strategy — same repo, new branch.**
   Separate `django` branch off `main`. Live Flask code untouched on `main` until cutover. After cutover, Flask version gets tagged for rollback reference, Django branch merges to `main`. Parallel deployment (both versions running on Railway during cutover) happens regardless of branch choice — that's the cutover process, not the branch process.

4. **Cutover — local testing only, careful window, fast rollback.**
   No trusted-user soak. Heavy reliance on the test suite from Decision 2 plus thorough local manual smoke-testing of every page before deploying. Cutover during a low-traffic window. Database snapshot immediately before. Flask version stays available on Railway for 48 hours post-cutover for instant rollback.

5. **Custom JS — full HTMX conversion goal.**
   Convert everything possible. Big-board drag-drop will use HTMX + Sortable.js as the first attempt (standard pattern). If that doesn't feel clean, treat it as a concrete question for the work devops team: "What pattern do you use for drag-and-drop reordering in HTMX apps?" Goal is to learn that team's standard pattern even for the rare cases.

---

## Sequencing Note: When the Multi-Tenancy Reference Code Arrives

Phase 2 (multi-tenant) builds on Phase 1, but doesn't block it. We do not need the work team's multi-tenancy middleware code to start Phase 1 — single-tenant Django works fine on its own. When Jon gets that code, we save it as a reference for Phase 2 planning. No urgency.

---

## Out of Scope (Explicit Deferrals)

- Multi-tenancy
- Sport abstraction
- Stripe / billing
- Oracle Cloud / Kubernetes migration
- Visual redesign of UI
- New features (stats page, schedule page, league activity feed, etc.) beyond what's already shipped
- Mobile native app (web stays mobile-responsive)
- Internationalization
- Public landing/marketing site
