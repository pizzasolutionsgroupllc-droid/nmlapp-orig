# Pre-Draft Checklist — Friday April 24, 2026

Work through this top to bottom. Target: done by 4:30 PM PT with a 30-min buffer before the 5 PM PT draft start. Check each box as you go.

---

## T-5 hours (12:00 PM PT)

- [ ] **Pull a fresh production backup.** This is your restore anchor if anything goes wrong.

```
bash download_db.sh
```

Note the filename (format: `data/backups/nml-backup-YYYYMMDD-HHMMSS.db`).
Backup filename: ________________________________

- [ ] **Check Railway dashboard → Metrics tab.** Note current state.
  - CPU baseline (should be near 0 vCPU at idle): _______
  - Memory baseline (current value in MB): _______
  - No red alerts or unusual patterns

- [ ] **Verify pick timers in admin Settings → Draft Timers.** Defaults:

```
R1: 600s (10 min)
R2: 420s (7 min)
R3: 300s (5 min)
R4: 240s (4 min)
R5: 180s (3 min)
R6: 180s (3 min)
R7: 180s (3 min)
```

Confirm these match what you want. Adjust if needed.

---

## T-3 hours (2:00 PM PT)

- [ ] **Dry-run stress test** (if arranged — see `dry-run-stress-test-plan.md`)

---

## T-1 hour (4:00 PM PT)

- [ ] **Pull one more fresh backup** — this is the real go-live restore anchor.

```
bash download_db.sh
```

Backup filename: ________________________________

- [ ] **Verify Discord bot is working.** Quick test:
  - Send a non-draft test message via bot admin action, or
  - Trigger a test DM to yourself from Settings
  - Confirm it appears

- [ ] **Verify Discord channels are set in Settings:**
  - Discord Draft Channel: _____________
  - Discord Transactions Channel: _____________
  - Discord Tradeblock Channel: _____________

---

## T-30 min (4:30 PM PT)

- [ ] **Restart Railway service.** This clears any stale memory/connections.
  - Railway dashboard → Deployments → Redeploy
  - Wait ~30 seconds for it to come back up
  - Load the app in a fresh tab, confirm it renders

- [ ] **Open these docs in browser tabs and keep them open:**
  - `docs/live-draft-runbook.md`
  - `docs/user-comms-templates.md`

- [ ] **Open Railway dashboard Metrics + Logs tabs** in separate windows

---

## T-10 min (4:50 PM PT)

- [ ] **Post to Discord (draft channel):**

```
🏈 Draft starts in 10 minutes. Please log in to the app now and refresh your tab so you're ready. On the clock at 5:00 PM PT sharp.
```

- [ ] **Quick sanity check** as a normal user:
  - All Players renders in under 2 sec
  - My Team renders in under 2 sec
  - Trade Center renders in under 2 sec
  - Draft Room page loads

---

## T-0 (5:00 PM PT)

- [ ] **Start the draft** from the commissioner panel

- [ ] **Watch Railway Metrics tab for the first 15 minutes.** If any of these trip, go to the runbook:
  - CPU sustained above 0.5 vCPU
  - Memory climbing rapidly
  - p99 response time above 3 sec for more than a minute
  - 5xx error rate above 2%

---

## Saturday (T-0 = 11:00 AM PT)

Repeat the T-1 hour and T-30 min sections starting at 10:00 AM PT. No need to re-test pick timers unless you changed them. One fresh backup is sufficient.

---

## Notes
- Gunicorn is running `--workers 1` (required for SQLite). Do not change this.
- If you need to rollback, see the "Recovery: restore from backup" section in `live-draft-runbook.md`.
