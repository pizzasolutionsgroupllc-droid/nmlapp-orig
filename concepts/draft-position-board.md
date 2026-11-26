# Draft Position Board — Visualization Concept
*Creator-only tool. Saved April 19, 2026.*

## What It Is
A matrix grid showing, for each team at each pick slot, which players that team is likely to draft. Think of it as a "big board by team" — crossing pick position (rows) with team tendencies (columns).

## Layout
- **Rows** = pick slot number (1, 2, 3 … up to however many players deep the board goes)
- **Columns** = each NML team (or NFL team)
- **Cells** = player names stacked in priority order for that team at that slot

## Visual Rules (from the reference screenshot)
- **Yellow highlight** = the most likely pick for that team at that slot (the projected selection)
- **Strikethrough text** = player is off the board (already drafted by someone earlier in the simulation)
- Players listed top-to-bottom within a cell = priority order (team's preference if top choices are gone)
- Not every team has players at every row — columns get shorter as picks are consumed

## What It Communicates
At a glance you can see:
- Which players multiple teams are targeting at the same slot (convergence = volatility)
- How far a prospect "falls" before someone takes them
- Which picks are locks vs. open questions

## Creator Use Cases
- Personal mock draft planning — visualize which players are likely gone before your picks
- Scenario modeling — swap in Scenario A vs B and see how the board shifts
- Trade analysis — "if I move up to #4, here's what I'm likely to get vs. staying at #7"

## Implementation Sketch (future)
```
Data model:
  team_board_entry(team_id, overall_pick, player_name/prospect_id, priority, scenario_label)

Render:
  - Pull all entries for a given scenario
  - Group by overall_pick → array of (team → players[])
  - Render as CSS grid or HTML table
  - Yellow = first non-struck entry per column
  - Strikethrough = players whose name appears in earlier picks across any column

Input:
  - Creator manually enters expected player pools per team per pick slot
  - OR auto-generate from mock draft picks + prospect board rankings
```

## Reference Screenshot
Saved as: `concepts/draft-position-board-reference.png` (if you add the image here)

Teams shown in screenshot: Raiders, Jets, Cardinals, Titans, Giants, Browns, Commanders, Saints, Chiefs, Giants, Dolphins, Cowboys

Players visible: Mendoza, Reese, Bailey, Love, Styles, Tate, Fano, Mauigoa, Delane, Tyson, Downs, Bain, McCoy, Freeling, Proctor, Ioane, Lemon, Thieneman, and others.
