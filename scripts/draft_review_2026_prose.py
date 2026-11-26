"""
NMLBot prose for the 2026 draft review.

Authored from the engine output in mockups/draft-review-engine-output.txt
using the NFL-slot-based starter logic (Madden assigns initial rookie OVR
primarily from NFL draft round, with consensus rank as a secondary signal).

Per-pick tier classification used in this file:
  - "Day 1 starter" / always_starter: NFL R1 across all positions, plus
    R2 OL/DT and R3 IOL where the league tolerates lower rookie OVR.
  - "conditional starter": pick at a tier-2 NFL round AT a position the
    team had a real roster gap at — e.g. R2 WR for a team without a
    starting WR.
  - "backup": late-NFL-round picks projecting in the low 60s OVR, UDFAs,
    unranked write-ins. These add depth, not starters. Calibrated against
    Madden 26 launch ratings — realistic ceiling 84 (Travis Hunter,
    generational), top-3 consensus + NFL R1 = 81-83, top-10 = 79-80,
    top-25 = 77-78, NFL R2 typical = 73-75, NFL R3 typical = 71-73,
    UDFA = low 60s.

Volume callouts: 3+ picks at any single position group are flagged
("Way more than normal at WR / IOL / etc.")

Editing tips:
  - blurb is the 4-sentence pull quote shown at the top of each team card
  - best_pick_text / worst_pick_text are the green/red callout chips
  - looking_ahead is the "🔭 Looking Ahead" closing section
  - DNP teams have only `did_not_participate: True` and a `summary` line
"""

PROSE_2026 = {
    # ────────────────────────── TIER 5 (Final = 5) ──────────────────────────

    "Commanders": {
        "blurb": "Washington's five-pick draft hinges on one selection — Blake Miller at NML #65. He went NFL R1 overall, projects in the high 70s OVR, and slots in immediately as a starter at OT. The other four picks are backup-tier additions per their NFL slots; Romello Height in R4 was the highest-EV swing of the bunch (+49 NML, NFL R3) but doesn't credibly project as a Day-1 starter. Five picks, one starter, no glaring damage anywhere — efficient class building from limited capital.",
        "best_pick_text": "R4.129 — EDGE Romello Height. NML rank #80 taken at #129, a 49-slot NML steal. Projects ~71 OVR (NFL R3) — depth-leaning but a high-upside swing.",
        "worst_pick_text": "R7.199 — IOL Matt Gulbin. NML rank #212 taken at #199, a -13 NML reach. Late-seventh dart throw, low cost.",
        "looking_ahead": "QB and IOL remain inferred starter-quality holes — neither got a Day-1 starter pick. With 2027 capital still in hand and an active trade market, expect Washington to pursue a veteran arm and an interior lineman before the season opens.",
    },

    "Seahawks": {
        "blurb": "Seattle's three NFL R1 selections form one of the cleanest top-of-draft hauls of any team in the league — Jeremiyah Love at NML #1 (NFL #3), Dillon Thieneman at #11 (NFL #25), and Makai Lemon at #14 (NFL #20) all project in the 78-80 OVR range as Day-1 starters. The Taylen Green QB pick in the third was a clear reach (-16 NML, NFL R6 — backup quality) but a defensible developmental swing on a contender's roster. Day 3 added depth, with Deion Burks at #163 the headline value grab (+73 NML). A complete top-to-bottom class.",
        "best_pick_text": "R5.163 — WR Deion Burks. NML rank #90 taken at #163, a +73 steal — the largest positive value delta in the entire league.",
        "worst_pick_text": "R3.92 — QB Taylen Green. NML rank #108 taken at #92, a -16 reach. NFL R6 grade puts him in backup territory.",
        "looking_ahead": "All inferred starter slots are stocked. Seattle's pick capital and roster depth point to window-open mode — watch them as a buyer in the trade market.",
    },

    "Chargers": {
        "blurb": "One pick, one steal — Beau Stephens at R7.205 was a +38 NML swing — but the NFL R5 grade pegs him at depth-piece OVR rather than a Day-1 starter. The Final 5 grade reflects the math holding up across all three sub-grades despite the limited capital, not the actual roster impact. With QB, OT, IOL, EDGE, DT, and CB all flagged as inferred starter holes, this offseason was always going to be defined by the trade market — the draft was just one move in a longer game.",
        "best_pick_text": "R7.205 — IOL Beau Stephens. NML rank #167 taken at #205, a +38 steal and the team's only selection.",
        "worst_pick_text": "Only one pick — no negative outliers to call out.",
        "looking_ahead": "Six inferred starter holes remain (OT, IOL, QB, EDGE, DT, CB). Expect the Chargers to be one of the most active trade-market teams during the season — both 2027 picks and roster pieces are likely on the block to plug the front-end gaps.",
    },

    "Panthers": {
        "blurb": "Carolina drafted four players, three of them confident Day-1 starters. Avieon Terrell at #27 (NFL R2, ~74 OVR) and Peter Woods at #30 (NFL R1, ~77 OVR) anchor the secondary and front, and Keylan Rutledge at NML #64 came in at NFL R1 (~76 OVR) for the interior offensive line — three credible new starters from four picks is elite efficiency. The R3 TE on Boerkircher (-71 NML, NFL R2 conditional) was the obvious miss at a position that wasn't a need. The remaining hole is at WR.",
        "best_pick_text": "R1.30 — DT Peter Woods. NML rank #31 taken at #30, near-perfect on-board value at NFL R1 (~77 OVR).",
        "worst_pick_text": "R3.90 — TE Nate Boerkircher. NML rank #161 taken at #90, a -71 reach at a non-need position.",
        "looking_ahead": "WR is the lone inferred starter hole. With 1.15x positional multiplier in the NML, expect Carolina to pay up for one — either via 2027 capital or an established player swap.",
    },

    # ────────────────────────── TIER 4 (Final = 4) ──────────────────────────

    "Browns": {
        "blurb": "Cleveland used their solitary first-round pick on Kenyon Sadiq, NML rank 16 taken at #9 — a -7 NML reach, but NFL R1 grade (~78 OVR) means a confident starter at TE, a position group with no prior starter on the roster. The Final 4 grade reflects exactly the right strategic outcome from a one-pick draft: filled the most pressing need at a starter-quality slot. Four other inferred starter holes remain unaddressed.",
        "best_pick_text": "R1.9 — TE Kenyon Sadiq. NML rank #16 taken at #9 — NFL R1, projects ~78 OVR, fills the team's biggest starter hole.",
        "worst_pick_text": "Only one pick — no negative outliers to call out.",
        "looking_ahead": "Four inferred starter holes remain (IOL, EDGE, DT, S). With limited 2026 capital remaining, Cleveland's path forward runs through the trade block — and several of those positions have surplus options around the league.",
    },

    "Chiefs": {
        "blurb": "Kansas City's class produced two confident starters and a stack of late-round depth — Sonny Styles at NML #5 (NFL R1, ~80 OVR) is the headline addition at LB, and Brandon Cisse at #32 (NFL R2 conditional, ~74 OVR) fills the secondary need. From there it's R7 swings for depth — DeMonte Capehart's +64 NML grab at #226 was the best raw value play of the day-3 set, but as a NFL R7 pick he's projected backup quality. A class built to add young talent without disrupting an already-stacked roster.",
        "best_pick_text": "R7.226 — DT DeMonte Capehart. NML rank #162 taken at #226, a +64 steal at the very bottom of the seventh.",
        "worst_pick_text": "R7.220 — WR Eric McAlister. NML rank #251 taken at #220, a -31 reach on a player who didn't even hear his name in the actual NFL draft.",
        "looking_ahead": "All inferred starter holes are addressed. Roster fully loaded heading into the season — expect KC to operate as a contender, using future capital for veteran reinforcement rather than long-term builds.",
    },

    "Packers": {
        "blurb": "Green Bay's third round was the highlight — Lee Hunter at NML #78 (NFL R2, ~74 OVR) and Emmanuel McNeil-Warren at #37 (NFL R2, ~74 OVR) both project as Day-1 starters at need positions. The R2 Igbinosun selection at -40 NML was the loud miss and an NFL R2 backup-quality grade made it doubly painful. The class graded out strong on Talent (4/5) thanks to two NFL R2 starters and a string of credible R2-graded prospects taken on Day 2. The lingering issue: Need 2 because QB and IOL still have no starter answer.",
        "best_pick_text": "R3.78 — DT Lee Hunter. NML rank #55 taken at #78, a +23 NML steal. NFL R2 grade puts him in starter territory at the position.",
        "worst_pick_text": "R2.34 — CB Davison Igbinosun. NML rank #74 taken at #34, a -40 reach. Only projects as backup quality at NFL R2.",
        "looking_ahead": "QB and IOL remain inferred starter holes the draft never touched. Expect Green Bay to look hard at QB in the trade market — the position carries the highest NML positional multiplier (1.30x).",
    },

    "Jets": {
        "blurb": "The Jets took 35 players — way more than normal, and the volume callouts spike at five different position groups (CB=5, DT=5, OT=5, IOL=4, plus 3+ at LB/EDGE/S). Eight of the 35 project as starters via NFL slot: Cooper Jr. (WR, NFL R1), Hood (CB), McDonald (DT), Faulk (EDGE NFL R1, +40 NML steal), and four interior linemen as conditional R3 starters. The R4 Lorenzo Styles bust at -104 NML was the loud miss in a 35-pick haul. An aggressive roster-stocking effort that lands eight starters and a deep bench — plus surplus depth they can flip for veteran pieces.",
        "best_pick_text": "R6.189 — TE Michael Trigg. NML rank #114 taken at #189, a +75 steal that landed as backup-tier depth (NFL R6).",
        "worst_pick_text": "R4.110 — CB Lorenzo Styles Jr. NML rank #214 taken at #110, a -104 reach.",
        "looking_ahead": "LB remains the inferred starter hole — a surprising gap given the 35-pick haul. The Jets now move into asset-management mode — expect them to flip surplus depth for veteran upgrades during the season.",
    },

    "49ers": {
        "blurb": "Three picks, two confident Day-1 starters. Denzel Boston at NML #23 (NFL R2 conditional, ~74 OVR) and Anthony Hill Jr. at #51 (NFL R2, ~74 OVR) both slot in immediately at WR and LB. Malachi Fields in R2 at #59 was the third selection — NFL R3 puts him at backup quality. With only three picks the Talent grade leans on where they drafted (every selection inside the top 75) and the class projects clean Year-1 contributors. The QB hole on the roster wasn't addressed and remains the dominant offseason question.",
        "best_pick_text": "R2.51 — LB Anthony Hill Jr. NML rank #50 taken at #51, near-perfect on-board value at NFL R2.",
        "worst_pick_text": "R2.59 — WR Malachi Fields. NML rank #67 taken at #59, a small -8 NML reach. NFL R3 grade puts him in backup tier.",
        "looking_ahead": "QB is the lone inferred starter hole and the most expensive position on the NML value chart (1.30x). Expect the 49ers to be active trade pursuers at the position — premium capital available, premium target needed.",
    },

    "Raiders": {
        "blurb": "The Raiders' 29-pick class is the modern NML draft equivalent of carpet-bombing — sixteen of the 29 selections project as Day-1 starters, including a stunning fourteen NFL R1 picks at the top of the class (Mendoza QB, Delane CB, Tate WR, Downs S, Reese LB, Bailey EDGE, Simpson, Johnson, Lawrence, Price, Ioane, Fano, Banks, Freeling). They also drafted way more than normal at six different position groups (WR=4, IOL=4, plus 3+ at CB/EDGE/RB/TE) — the volume is unprecedented. The mid-rounds got ugly with reaches (Brenen Thompson -60, Kaelon Black -106), but a class anchored by 14 NFL R1 talents has a Talent grade of 5 by definition.",
        "best_pick_text": "R6.174 — RB Kaytron Allen. NML rank #133 taken at #174, a +41 steal but at NFL R6 grade so depth-tier.",
        "worst_pick_text": "R3.77 — RB Kaelon Black. NML rank #183 taken at #77, a -106 reach.",
        "looking_ahead": "Every pre-draft inferred starter hole — QB, RB, IOL, S — was filled by NFL R1 starter-quality picks. The roster is now fully stocked, and the offseason becomes about integrating the historic class. With remaining 2027 capital, expect Las Vegas to be selective in the trade market rather than reactive.",
    },

    # ────────────────────────── TIER 3 (Final = 3) ──────────────────────────

    "Cardinals": {
        "blurb": "Three picks, one elite hit. Francis Mauigoa at R1.33 (NML rank 7, NFL R1 — projects ~80 OVR) is a +26 NML steal and instantly becomes a starter on the interior offensive line. The R2 S pick on Bud Clark and the R3 QB on Cade Klubnik both went negative NML, both at backup-tier NFL grades, and they came at positions where the roster wasn't asking for help. With three inferred starter holes (OT, IOL, CB) heading in, only the IOL slot got fixed — the Mauigoa pick alone keeps the class respectable.",
        "best_pick_text": "R1.33 — IOL Francis Mauigoa. NML rank #7 taken at #33, a +26 steal. NFL R1, projects ~80 OVR.",
        "worst_pick_text": "R3.99 — QB Cade Klubnik. NML rank #131 taken at #99, a -32 reach.",
        "looking_ahead": "OT and CB still need addressing. Expect Arizona to lean into the trade market — both positions have significant value differentials in the NML, which gives the front office leverage if they have the right outgoing pieces.",
    },

    "Broncos": {
        "blurb": "Denver's R2-R3 trench rebuild produced six new starters — Kadyn Proctor RT, Akheem Mesidor EDGE, Max Iheanachor OT, Caleb Lomu OT (all NFL R1, ~77-78 OVR), plus Tyler Onyedim DL5T and Chris McClellan DT as conditional R3 starters. Volume callouts at OT=3 and LB=3 reflect the focused front-seven push. From there the rounds got rough: Klein TE at -80, Woodaz LB at -152, Bredeson RB at -108. The starter haul is what matters for Year 1 — a sturdy front-line rebuild even with the late-round noise.",
        "best_pick_text": "R3.71 — OT Caleb Lomu. NML rank #28 taken at #71, a +43 steal at NFL R1 grade — confident starter at OT.",
        "worst_pick_text": "R5.136 — LB Wade Woodaz. NML rank #288 taken at #136, a -152 reach.",
        "looking_ahead": "WR and S remain inferred starter holes. With a heavy stack of new bodies up front, expect Denver to flip surplus depth in the trade market for help in the back half of the roster.",
    },

    "Bengals": {
        "blurb": "Cincinnati's third round was the headline — Bisontis IOL (NFL R2, +28 NML, ~74 OVR) and Howell EDGE (NFL R2, +44 NML, ~74 OVR) were two clean Day-1 starter additions. Beyond those two, the rest of the 11-pick class falls to backup tier on NFL grade — Antonio Williams (R3 NFL), Skyler Bell (R4), and a pair of R4 CBs at negative NML value. The Adam Randall RB pick at -45 NML was the worst single mid-round selection. A solid hit rate on Day 2 was enough to keep the class above water.",
        "best_pick_text": "R3.79 — EDGE Cashius Howell. NML rank #35 taken at #79, a +44 steal — NFL R2 grade puts him as starter quality.",
        "worst_pick_text": "R4.124 — RB Adam Randall. NML rank #169 taken at #124, a -45 reach at a position the team didn't need.",
        "looking_ahead": "DT remains the inferred starter hole — likely a target for in-season trades or a free-agent pickup. Otherwise the class is well-rounded.",
    },

    "Vikings": {
        "blurb": "Minnesota took five wide receivers — way more than normal at any single position group — and only one of them grades as a starter (R Mason Thomas EDGE was the lone confident starter at #63). The four WR picks landed at NFL R3-R5 grades, putting them all in backup territory. Devin Moore CB at #150 was a +61 NML steal but NFL R4 grade caps him at depth. The volume + selectivity strategy worked on paper but the NFL grades say only one new starter walks in — and he's not even a WR.",
        "best_pick_text": "R5.150 — CB Devin Moore. NML rank #89 taken at #150, a +61 steal at NFL R4 grade (depth tier).",
        "worst_pick_text": "R3.74 — RB Demond Claiborne. NML rank #155 taken at #74, a -81 reach at NFL R6 grade.",
        "looking_ahead": "WR remains the inferred starter hole despite the five WR picks — none of them project as Day-1 starters by NFL grade. Expect Minnesota to seriously consider a trade-market WR addition.",
    },

    "Texans": {
        "blurb": "Houston's class produced two starters — Jacob Rodriguez at #28 (NFL R2, ~74 OVR) and Christen Miller at #61 (NFL R2, ~74 OVR) — and five backup-tier supplemental picks. The Kyle Louis pick at #127 was a +48 NML steal but his NFL R4 grade puts him at depth quality. The story isn't the picks made; it's the picks not made — TE and IOL both flagged as inferred starter holes never got addressed in seven attempts. Need 1 isn't a verdict on what they did, it's a verdict on what they ignored.",
        "best_pick_text": "R4.127 — LB Kyle Louis. NML rank #79 taken at #127, a +48 steal but NFL R4 grade caps him at backup.",
        "worst_pick_text": "R6.191 — OT Carver Willis. NML rank #232 taken at #191, a -41 reach.",
        "looking_ahead": "TE and IOL both remain inferred starter holes. With seven picks already used, the front office's only path to fixing them runs through the trade market or 2027 capital.",
    },

    "Ravens": {
        "blurb": "Baltimore's marquee selection was Jordyn Tyson at NML #8 (NFL R1, ~78 OVR) — a confident Day-1 starter at WR. Zion Young EDGE at #76 (NFL R2, ~74 OVR) is the second starter, and Albert Regis DT in R5 came in at NFL R3 conditional starter. Beyond those three the class fell apart — Wetjen WR at -70, Caden Curry EDGE at +62 NML but NFL R6 grade. Three starters from five picks is a respectable hit rate; the value math just punished them.",
        "best_pick_text": "R7.204 — EDGE Caden Curry. NML rank #142 taken at #204, a +62 steal at NFL R6 grade (depth tier).",
        "worst_pick_text": "R4.115 — WR Kaden Wetjen. NML rank #185 taken at #115, a -70 reach at NFL R4 grade.",
        "looking_ahead": "OT, IOL, and LB remain inferred starter holes. Baltimore will likely bundle 2027 capital for veterans — multiple positions with active trade availability around the league.",
    },

    "Rams": {
        "blurb": "Eleven picks, one confident starter — Emmanuel Pregnon at NML #80 (NFL R3, ~72 OVR, +29 NML) projects as a Day-1 IOL starter thanks to the position's tolerance for lower rookie OVR. Joshua Josephs EDGE at R5.145 was a +61 NML steal but NFL R4 grade puts him at backup. The R6 Dugger LB at -117 NML and the R7 Trey Smack kicker pick at -330 were the loud Day-3 misses. Volume callout at LB=3 in late rounds. Eleven picks of mixed signal: enough quiet hits to stay on grade, enough reaches to keep the verdict honest.",
        "best_pick_text": "R5.145 — EDGE Joshua Josephs. NML rank #84 taken at #145, a +61 steal but at NFL R4 grade — backup tier.",
        "worst_pick_text": "R7.198 — K Trey Smack. NML rank #528 taken at #198, a -330 reach at the league's lowest-valued position group.",
        "looking_ahead": "Roster is well-rounded across all groups. With eleven new bodies in the building, expect the Rams to settle into a development mode through the offseason.",
    },

    # ────────────────────────── TIER 2 (Final = 2) ──────────────────────────

    "Bills": {
        "blurb": "Buffalo's 14-pick haul produced two starters — T.J. Parker EDGE at NML #40 (NFL R2, ~74 OVR) and Caleb Tiernan OT at #112 (NFL R3 conditional, ~71 OVR, +40 NML). The class drafted way more than normal at CB=4 and WR=3, but most of those picks were NFL R3-R4 grade, putting them in backup tier. Stukes R1 at -30 NML was the loud reach, and the Karon Prunty -257 NML in R7 sealed the value damage. The roster gets deeper but doesn't add the quantity of starters the volume suggests.",
        "best_pick_text": "R4.112 — OT Caleb Tiernan. NML rank #72 taken at #112, a +40 steal — NFL R3 grade qualifies him as a conditional starter at OT.",
        "worst_pick_text": "R7.197 — CB Karon Prunty. NML rank #454 taken at #197, a -257 reach at the bottom of the seventh.",
        "looking_ahead": "IOL and LB remain inferred starter holes — the late-round picks at those groups don't reliably project as Day-1 starters. Buffalo's path forward is the trade market for one or two veteran upgrades, with the 14-pick depth giving them flexibility to package outgoing pieces.",
    },

    "Cowboys": {
        "blurb": "One R1 pick, one negative outcome. Germie Bernard at NML rank 49 taken at #31 came in at NFL R2 grade (~72 OVR) — backup tier in NML at WR since the team had no roster gap there. With three inferred starter holes (OT, IOL, DT) entering the offseason and zero of them touched in the draft, the Cowboys come out with a depth piece and a long offseason ahead.",
        "best_pick_text": "R1.31 — WR Germie Bernard. NML rank #49 taken at #31, the team's only selection. NFL R2 grade.",
        "worst_pick_text": "Only one pick — no negative outliers to call out separately.",
        "looking_ahead": "OT, IOL, and DT are all inferred starter-quality holes. The offseason will need to lean heavily on the trade market — Dallas has 2027 capital but is short on flexible starting-level pieces to deal.",
    },

    "Lions": {
        "blurb": "Detroit's eleven picks produced one starter — Markel Bell OT in R3 at NFL R3 conditional grade (~69 OVR). The Zavion Thomas R2 pick at -185 NML was the loudest mid-draft reach in the league, and the WR=3 / CB=3 volume callouts both produced backup-tier additions rather than starters. The Jaffer Murphy K pick at -503 NML closed the class on a low note. Need 4 because picks at least targeted the right position groups even when the value and starter-quality grades were off.",
        "best_pick_text": "R5.157 — CB Ephesians Prysock. NML rank #124 taken at #157, a +33 steal at NFL R4 grade (depth tier).",
        "worst_pick_text": "R7.211 — K Jaffer Murphy. NML rank #714 taken at #211, a -503 reach at the league's lowest-valued group.",
        "looking_ahead": "QB, WR, and LB remain inferred starter holes — none of the draft's WR or CB picks project as Day-1 starters by NFL grade. The position carries the highest positional multiplier in the NML — expect Detroit to be aggressive in the trade market.",
    },

    "Dolphins": {
        "blurb": "Miami's draft has one bright spot: De'Zhaun Stribling at #29 (NFL R2 conditional, ~71 OVR) projects as a starter at WR thanks to the team's roster gap there. The other five picks fall to backup tier — Drew Allar QB at NFL R3, Garrett Nussmeier QB at +65 NML but NFL R5 grade, Halton DT at NFL R4. The Nussmeier swing was the value highlight but his projected OVR doesn't match. Six picks, mixed signal, anchored by a single conditional starter.",
        "best_pick_text": "R4.128 — QB Garrett Nussmeier. NML rank #63 taken at #128, a +65 steal but NFL R5 grade puts him at backup quality.",
        "worst_pick_text": "R1.29 — WR De'Zhaun Stribling. NML rank #95 taken at #29, a -66 reach in the first round.",
        "looking_ahead": "Six inferred starter holes remain (DT, S, TE, OT, IOL, LB) — only the WR slot got addressed via Stribling's conditional starter status. Miami's offseason work is heavily front-loaded toward the trade market.",
    },

    "Titans": {
        "blurb": "Five Day-3 picks, all five grading at NFL R5+ — none of them project as Day-1 starters. The class targets need positions with discipline (Need 4 reflects the alignment), but every selection is a depth piece. Tanner Koziol TE at R6.192 was the closest to even-value (+2 NML). The Cruz Jr. OT pick at -88 was the obvious miss. With six inferred starter holes (WR, TE, OT, IOL, EDGE, LB), Tennessee leaves the draft with the largest hole-list of any drafting team.",
        "best_pick_text": "R6.192 — TE Tanner Koziol. NML rank #190 taken at #192, on-board value but NFL R5 grade puts him at backup tier.",
        "worst_pick_text": "R7.218 — OT Enrique Cruz Jr. NML rank #306 taken at #218, a -88 reach.",
        "looking_ahead": "Six inferred starter holes remain (WR, TE, OT, IOL, EDGE, LB). Tennessee will need to be active in both the trade market and FA at multiple positions — this is the largest remaining hole-list of any drafting team.",
    },

    "Saints": {
        "blurb": "Fifteen picks, zero starters by NFL grade. Volume callouts at WR=3 and EDGE=3 reflect the breadth of the haul, but every single one of the 15 selections projects as backup tier or worse — the class chased value at need positions but the NFL slot data says none of these players are stepping in to start. Caleb Douglas WR R2 at -142 NML was the worst single pick in the entire 2026 NML draft. Josh Cameron WR at +80 NML in R7 was the lone bright spot. The hit rate on a 15-pick class shouldn't be 0-of-15 starters.",
        "best_pick_text": "R7.216 — WR Josh Cameron. NML rank #136 taken at #216, a +80 steal but at NFL R6 grade — depth.",
        "worst_pick_text": "R2.52 — WR Caleb Douglas. NML rank #194 taken at #52, a -142 reach — the worst single pick in the entire 2026 NML draft.",
        "looking_ahead": "LB is the inferred starter hole. New Orleans has limited 2027 capital after the volume drafting — fixing it likely runs through a player-for-player swap.",
    },

    # ────────────────────────── TIER 1 (Final = 1) ──────────────────────────

    "Jaguars": {
        "blurb": "Jacksonville's seven-pick class produced zero confident starters by NFL grade. Carson Beck QB at R2.55 was a -47 NML reach — drafted in NFL R3, so backup quality at a position where R2 picks rarely start. From there the picks chased value at need positions but kept missing on the starter-quality bar — Colbie Young at -65, Will Kacmarek at -41. The one bright spot was J.C. Davis OT in R7 (+19 NML), but again at NFL R6 grade he's depth. Need 3 reflects the right intent at need positions.",
        "best_pick_text": "R7.201 — OT J.C. Davis. NML rank #182 taken at #201, a +19 steal but NFL R6 grade — depth.",
        "worst_pick_text": "R7.215 — P Ryan Eckley. NML rank #696 taken at #215, a -481 reach at the league's lowest-valued group.",
        "looking_ahead": "QB, WR, IOL, and DT remain inferred starter holes. Expect Jacksonville to be very active in the trade market — none of the draft's picks project as Day-1 starters at any of those positions.",
    },

    "Steelers": {
        "blurb": "Pittsburgh's class produced zero confident starters by NFL grade. Tacario Davis at R2.48 was a -68 NML reach and his NFL R3 grade puts him at backup. Jaishawn Barham LB at R4.114 was the cleanest hit (+28 NML) but his NFL R3 grade also puts him at backup tier. With EDGE flagged as the inferred starter hole and zero EDGE picks made in four selections, the Need grade reflects that miss directly.",
        "best_pick_text": "R4.114 — LB Jaishawn Barham. NML rank #86 taken at #114, a +28 steal but at NFL R3 grade — backup tier for LB.",
        "worst_pick_text": "R2.48 — CB Tacario Davis. NML rank #116 taken at #48, a -68 reach.",
        "looking_ahead": "EDGE remains the inferred starter hole. The position carries a 1.0 NML multiplier — expect Pittsburgh to target it in the trade market. They have the 2027 capital to do it.",
    },

    "Eagles": {
        "blurb": "Two picks, both DTs, both projecting as backup quality on a roster that already had a credible starter at the position. Zxavian Harris in R4 was a UDFA in the actual NFL draft (60 OVR projection), and Bobby Jamison-Travis at R6.194 was a -185 NML reach at NFL R6 grade. With no inferred starter holes on the roster, the two picks become depth pieces that don't change the competitive picture.",
        "best_pick_text": "R4.126 — DT Zxavian Harris. NML rank #130 taken at #126. UDFA in the NFL draft — backup quality.",
        "worst_pick_text": "R6.194 — DT Bobby Jamison-Travis. NML rank #379 taken at #194, a -185 reach at a non-need position.",
        "looking_ahead": "Roster has zero inferred starter holes — the team is in win-now mode regardless of the draft outcome. The two picks become depth pieces.",
    },

    "Colts": {
        "blurb": "One pick, six inferred starter holes still on the board. Aiden Fisher LB at R2.45 was a -109 NML reach drafted at NFL R7 grade — backup quality at a position with no clear roster justification. With QB, WR, OT, IOL, EDGE, and CB all flagged as starter-quality holes and only one pick made, the offseason was always going to be defined by the trade market, and this single selection didn't change that math.",
        "best_pick_text": "R2.45 — LB Aiden Fisher. NML rank #154 taken at #45, the team's only selection. NFL R7 grade puts him at backup.",
        "worst_pick_text": "Only one pick — Fisher's -109 NML stands as the team's headline.",
        "looking_ahead": "Six inferred starter-quality holes remain (QB, WR, OT, IOL, EDGE, CB) — the most extensive hole-list in the league. Expect Indianapolis to be the most active team in the trade market and a candidate for veteran free-agent signings.",
    },

    # ────────────────────────── DID NOT PARTICIPATE ──────────────────────────

    "Bears": {
        "did_not_participate": True,
        "summary": "Chicago traded out of every 2026 selection. Inferred starter-quality holes at IOL and LB will need to be filled via trade or free agency — the front office's path forward runs entirely through veteran acquisitions and 2027 capital.",
    },

    "Buccaneers": {
        "did_not_participate": True,
        "summary": "Tampa Bay traded all of their 2026 picks. The lone inferred starter-quality hole is at OT, where the roster has one credible starter at 86 OVR. Expect a targeted trade for a second-tier OT to round out the front, with the bulk of 2027 capital still available.",
    },

    "Falcons": {
        "did_not_participate": True,
        "summary": "Atlanta traded out of every 2026 pick. Inferred starter holes at LB and S — both positions with active trade availability around the league. The Falcons enter the season as a quiet-offseason team relying on roster continuity.",
    },

    "Giants": {
        "did_not_participate": True,
        "summary": "New York moved all of their 2026 selections. The single inferred starter hole at LB is filling-via-trade territory — a position with manageable acquisition cost and several availability candidates around the league.",
    },

    "Patriots": {
        "did_not_participate": True,
        "summary": "New England traded their entire 2026 draft for future capital and roster pieces. Four inferred starter-quality holes remain (IOL, DT, CB, S). Expect a heavy trade-market presence and possibly multiple bundle deals using 2027 picks.",
    },
}
