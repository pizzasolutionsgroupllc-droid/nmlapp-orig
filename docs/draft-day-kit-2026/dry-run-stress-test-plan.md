# Draft Dry-Run Stress Test Plan

**Purpose:** Expose any remaining performance issues under realistic concurrent load before the real draft.

**Approach:** Option A — Snapshot + Restore. No code changes required. Testers use the real app; any activity is wiped by restoring the backup afterward.

---

## When to run

Target: **Thursday evening (April 23), 6:30-7:30 PM PT**. Pick a window that works for 4-5 testers.

- 30 min buffer before (pull backup, announce)
- 30 min buffer after (restore, verify, announce all-clear)

---

## Pre-test checklist

- [ ] Confirm 4-5 testers (Discord DM or league channel)
- [ ] Announce the window at least 2 hours in advance in Discord:

```
🧪 Stress test [START] to [END] PT tonight. PLEASE DO NOT use the app during that window — any actions you take will be wiped when I restore from backup. Thanks!
```

- [ ] Pull a fresh backup **immediately before** the test starts:

```
bash download_db.sh
```

Backup filename: ________________________________

---

## What testers should do

Send them this block (copy/paste-ready):

```
Dry-run stress test, [TIME] PT. Here's what I need from each of you for 20 minutes:

1. Log in to the app and stay logged in.
2. Every minute or so, do ONE of these — rotate through them:
   - Load All Players
   - Open Trade Center
   - Search for a player by name
   - Open another team's roster page
   - Go to the Draft Room (even though it's not running)
   - Add/remove a player from your watchlist
   - Open My Team → Depth Chart
3. If something takes more than 5 seconds to load, note the time in Discord and what you were doing.
4. If you see an error, screenshot it and post.

Goal: 4-5 of us doing this at the same time simulates a busy draft moment.
```

---

## What to monitor during the test

Keep these three windows open:

### 1. Railway Dashboard → Metrics tab
- **CPU** — should stay under 0.5 vCPU
- **Memory** — should not climb rapidly (a mild rise is fine)
- **Response Time** — p99 should stay under 3 seconds
- **Error Rate** — should stay under 2%

### 2. Railway Dashboard → Logs tab
- Watch for `database is locked` — expected occasionally, problematic if repeated
- Watch for 500 errors
- Watch for slow request warnings

### 3. Discord channel
- Watch for tester reports of slowness or errors

---

## Post-test restore

1. Check recent backups:

```
ls -lht data/backups/ | head -5
```

2. Copy your pre-test backup to the upload name:

```
cp data/backups/nml-backup-YYYYMMDD-HHMMSS.db data/nml-merged.db
```

3. Upload:

```
bash upload_merged.sh
```

4. Wait 30 seconds, then load the app and verify your own team state looks right.

5. Announce all-clear:

```
✅ Stress test complete and restored to pre-test state. Everything is back to normal. Thanks testers!
```

---

## Interpreting results

- **All metrics stayed green, no errors** → You're ready. Proceed with confidence.
- **Response time got laggy but no errors** → Expect some lag during peak draft moments. Acceptable.
- **A specific endpoint was consistently slow** → Note it and consider whether we can disable/defer that feature during the draft.
- **Errors during low concurrency** → Something is wrong. Diagnose before draft. Post in Discord for help.
- **Memory climbed and didn't recover** → Worth a restart before the real draft (already in the pre-draft checklist).
