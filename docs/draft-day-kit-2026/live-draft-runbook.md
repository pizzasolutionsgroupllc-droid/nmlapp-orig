# Live-Draft Runbook — What to Do If...

Keep this open during the draft. Each scenario: **symptom → quick diagnosis → action**.

---

## 1. "Draft is busy" errors spiking for multiple users

**Symptom:** Users report repeated 503 "busy" toasts when trying to submit picks or load pages.

**Diagnosis:** SQLite write contention. One slow request is holding the lock.

**Action:**
1. Give it 15 seconds — the built-in retry-with-backoff should self-heal most cases.
2. Check Railway Logs tab for `database is locked` — how frequently?
3. If persistent (more than 30 sec): **Railway → Redeploy** to clear held connections.
4. Post user comms: "Brief pause — back in 2 minutes" (see `user-comms-templates.md`).

---

## 2. Pick didn't advance after submission

**Symptom:** A team submitted a pick but the on-the-clock didn't rotate to the next team.

**Diagnosis:** `advance_pick()` hit a lock or the state is stuck.

**Action:**
1. Refresh the Draft Room page — the state may already be correct, just not displayed.
2. If still stuck: Commissioner panel → manually advance the pick.
3. Confirm the submitted player is recorded correctly before advancing.

---

## 3. Server completely unresponsive (all users frozen)

**Symptom:** Nobody can load the app. Pages hang or return 502.

**Action:**
1. Check Railway Deployments tab — has the service crashed?
2. If crashed: Railway → Redeploy.
3. If hung but not crashed: Railway → Service settings → Restart.
4. Post user comms: "Brief pause — back in 2 minutes."
5. If the DB is corrupt (you'll see malformed errors in logs): follow **Section 8 — Recovery** below.

---

## 4. User can't log in

**Symptom:** A specific user reports login failing.

**Action:**
1. Confirm their Discord username in app Settings matches their team record.
2. Have them clear cookies / do a hard refresh (**Cmd+Shift+R** / **Ctrl+Shift+R**).
3. If Discord DM isn't arriving: check Railway logs for bot errors.
4. Worst case: Admin → manually generate a magic link for them.

---

## 5. Discord bot silent (no pick announcements)

**Symptom:** Picks register in the app but no Discord messages are posting.

**Diagnosis:** Discord API rate limit, auth failure, or token issue.

**Action:**
1. Check Railway Logs tab → search for `Discord` errors.
2. Check Settings → Discord bot token is set.
3. **Bot failures do NOT block the draft.** Picks still register normally.
4. Post user comms: "Bot is lagging, picks are being recorded normally — watch the app."

---

## 6. Memory climbing steadily

**Symptom:** Railway Memory graph trending up, up, up.

**Diagnosis:** Cache not invalidating or background threads piling up.

**Action:**
1. Under 400 MB: no action, restart between rounds if convenient.
2. Over 400 MB and climbing fast: **Redeploy during a natural break** (round transition or before on-the-clock team submits).
3. Announce the restart in Discord first.

---

## 7. Timer expired but auto-advance didn't fire

**Symptom:** Timer shows 0:00 but the team is still on the clock.

**Diagnosis:** Auto-advance has a 10-second gate — it checks at most once per 10 sec. Should fire within 10 sec of expiry.

**Action:**
1. Wait 10-15 seconds — it may fire on the next gate cycle.
2. If it doesn't: Commissioner panel → manually advance (pick goes to makeup queue).
3. Post user comms: "Pick auto-advancing now — skipped to [NEXT TEAM]."

---

## 8. Recovery: restore from backup (LAST RESORT)

**Only if production DB is corrupt or clearly compromised.** You will lose any real activity since the backup.

```
cp data/backups/nml-backup-YYYYMMDD-HHMMSS.db data/nml-merged.db
bash upload_merged.sh
```

Then:
1. Wait 30 seconds for Railway to restart.
2. Load the app, confirm your own team state looks right.
3. Post user comms:

```
⚠️ We restored from the backup taken at [TIME PT]. If your last action was after that time, please re-do it.
```

---

## Vital commands (copy-paste ready)

Pull a fresh backup mid-draft (if you need a new anchor):

```
bash download_db.sh
```

Restore from backup:

```
cp data/backups/nml-backup-YYYYMMDD-HHMMSS.db data/nml-merged.db
bash upload_merged.sh
```

Check Railway logs (in Railway web UI):
Open your project → Deployments → click active deployment → View Logs

---

## Quick health thresholds during the draft

| Metric | Green | Yellow | Red (act) |
|--------|-------|--------|-----------|
| CPU | <0.5 vCPU | 0.5-1.0 | >1.0 sustained |
| Memory | <300 MB | 300-500 | >500, climbing |
| p99 latency | <2 sec | 2-5 sec | >5 sec sustained |
| 5xx rate | <1% | 1-3% | >3% |
