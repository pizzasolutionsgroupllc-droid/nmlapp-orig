# NML App — Feature Backlog

## 🛠 Development Process
1. Set up a DEV site so all changes can be tested prior to pushing to production.

---

## 🏠 Dashboard
2. ~~Clicking the Team count (e.g. "32") redirects to the All Teams page.~~ *(Removed — Teams section removed from dashboard; 32 never changes and All Teams is already in the nav.)*
3. ~~Clicking the Rostered Players count shows a full list of all rostered players.~~ *(Tabled — revisit when All Players nav is exposed to the full league.)*
4. Clicking a Completed Trade entry navigates to the Transactions page.

---

## 👤 My Team
5. Export roster to CSV.
6. Dropdown filters for individual positions (e.g. LG, RG) and/or position groups (e.g. OL, Secondary).
7. Display team helmet logos on the My Team page.
8. Clicking a pick year chip (e.g. "2026 (4)") scrolls down to show that team's picks — quality of life improvement.

---

## 🏈 All Teams (Other Teams)
9. Export any team's roster to CSV.
10. Filter roster by individual position and/or position group.
11. Add a "Trade For" button on player and pick rows when viewing another team's page.

---

## 🔓 Free Agents
12. Export free agent list to CSV.
13. Filter by individual position and/or position group.

---

## 🚩 Trade Block
14. Filter by team, position, and wildcard text search.
15. Post trade block listings to the Discord trade block channel when added.
16. Enforce a standard font size on trade block text submissions (formatting consistency).

---

## 🎯 Pick Tracker
17. Export to CSV.
18. Filter picks by original team owner.
19. Filter picks by current team owner.

---

## ⚖️ Compare Players
20. Add a Compare Players feature — select up to 5 players side-by-side, with a "Trade For" button on any of them.

---

## 📤 Exports & Backups
21. Weekly automated export of all app data, sent to a configurable destination (email, Google Drive, etc.).
22. Allow any user to trigger a manual full data export at any time for personal backup.
23. Add Export to CSV to every page/table that displays data.

---

## 🗃 Transactions & Audit
24. Comp Pick transaction entries should show who awarded the pick (admin name).
25. All transaction log entries should show the actor — "System", "trouse", "Ron", etc. — not just the action.

---

## 🃏 Player Cards
26. Clicking a player's name anywhere in the app opens a player card popup with full stats, ratings, and the ability to import/display a player image.

---

## 🎨 UI / UX
27. Add a color legend explaining what each color/badge means throughout the app — or make the color scheme editable by the commissioner.

---

## 🏟 Team Management
28. Handle NFL team changes — if a franchise relocates or rebrands, the app should support updating team names, abbreviations, and logos without breaking existing data.
29. Develop a Team Moves section to manage and log team relocations or rebrands.

---

## 📅 Scheduling
30. Add the ability to schedule games between teams, then display the schedule on a calendar view.

---

## 🏆 Leaderboards
31. Top 10 teams ranked by transaction type (trades completed, signings, cuts, proposals sent) — shown per current league year and all time with counts.
