# NFL Big Data Bowl 2027 — Competition Brief

> Source: <https://www.kaggle.com/competitions/nfl-big-data-bowl-2027> (captured 2026-10-10)

## The one-line task

> "Uncover non-obvious linkages between Combine sensor tracking and regular-season NFL game performance."

Build an analytical framework that links **10 Hz NFL Scouting Combine sensor tracking** to **future
regular-season NFL game performance** — to find hidden talent, avoid draft busts, and design
position-specific development protocols.

## Format: this is a HACKATHON, not a leaderboard competition

This is the single most important structural fact. There is **no metric, no leaderboard, no
`submission.csv`, no public/private split**. Tom Bliss (host) confirmed on the forum: *"There are no
plans to launch a prediction competition this year."*

The deliverable is a **Kaggle Writeup** with an attached **public Kaggle Notebook**, judged by humans.

| | |
|---|---|
| Host | National Football League |
| Type | Featured Hackathon (no points, no medals) |
| Start | **2026-10-06** |
| Final submission | **2027-01-06**, 11:59 PM UTC |
| Judging | 2027-01-07 → 2027-01-25 |
| Results | **2027-01-26** |
| Prize pool | **$100,000** |
| Team size | max **5** |
| Submissions | **1 per team** (hackathon rule; pre-merge submissions are un-submitted on merge) |
| Winner license | Open Source (OSI-approved, must not limit commercial use) |
| Data license | CC BY-NC 4.0 — non-commercial, **do not redistribute** |

### Prize structure

- **Open Track — $45,000**: 3 × $10,000 Finalist, 3 × $5,000 Runner-Up. No eligibility restrictions.
- **University Track — $45,000**: same split. *Entirely* undergraduate teams only; verification may be required.
- **Grand Prize — $10,000**: all 6 finalists are invited to present at the 2027 NFL Scouting Combine in
  Indianapolis; one wins an extra $10,000. You cannot submit to this track directly.
  - Host clarification: prizes are awarded **before** travel planning, so a finalist who cannot travel still
    gets the finalist money — but the Indianapolis presentation **cannot be given remotely**, and a
    non-attending finalist is **ineligible for the Grand Prize**. NFL covers travel and lodging.

> Which track applies to us is an open question — see `docs/plan.md`. Open Track is the default assumption.

## Submission requirements (hard constraints)

- **≤ 2,000 words**
- **< 10 tables or figures** (i.e. at most 9 combined)
- Readable markdown, **embedded visuals**, and an attached **public Kaggle Notebook**
- Host clarification: the word/figure limits apply to **the writeup only**. An appendix inside the writeup
  and the attached notebook are **outside the count**.
- Most code belongs in the appendix or the linked notebook, not the writeup body.
- **A writeup that does not use the player tracking data is not scored.**
- Mechanics: create a Writeup (Writeups tab → New Writeup), attach the public notebook to it, submit that.
  Posting a notebook to the Discussion forum is *not* a submission (Paul Mooney, Kaggle staff).

## Scoring rubric

Two pass/fail gates first:

1. **Combine-to-NFL Linkage** — the writeup explicitly links Combine sensor tracking to regular-season NFL
   game performance.
2. **Writeup Completeness** — readable markdown + embedded visuals + attached public Kaggle Notebook.

Then four components, each scored 0–10, combined as a weighted average:

| Component | Weight | Judge's questions |
|---|---|---|
| **Football** | 30% | Could NFL teams use this **on a week-to-week basis**? Does it account for the variables that make football data complex? Are the ideas unique? |
| **Data Science** | 30% | Is the work correct? Are claims backed by data? Are the models appropriate? Are the applications innovative? |
| **Writeup** | 20% | Well-written? Easy to follow? Is the motivation (metric, player evaluation) clearly defined? |
| **Data Visualization** | 20% | Accessible? Accurate? Innovative? |

**Judges are analytics staffers from the 32 NFL teams and from player-tracking vendors.** Tom Bliss (NFL
Data Scientist) is the named judge. This is a practitioner audience, not an academic one: they reward
football usefulness and distrust unvalidated metrics.

Note the asymmetry worth exploiting: **40% of the score is writing + visualization**, which is almost
entirely under our control and is where most Kaggle-native entrants underinvest.

## Explicit guidance from the host

> "participants are encouraged to focus on **one small aspect of movement, a specific position group, or
> an individual drill**, rather than attempting to evaluate every prospect across all drills."

Example directions the host lists (non-exhaustive):

1. **Route running and coverage** — change of direction, deceleration into breaks, acceleration out of cuts
   for WR/DB, compared to in-game separation.
2. **Trench play** — first-step quickness, lateral agility, burst for OL/DL in agility drills vs. pass-rush
   or run-blocking performance.
3. **Drill translation** — sensor-based movement metrics vs. traditional drill times: where does tracking
   data add context beyond the stopwatch?
4. **Position-specific mechanics** — body control, acceleration profiles, pursuit angles vs. rookie
   performance.

## Rules that matter for how we work

- **External data is allowed** (§2.6) if it is publicly available, equally accessible to all participants,
  and free / of minimal cost. Proprietary paid datasets costing more than a prize are not reasonable.
- **AI assistance is explicitly allowed.** Kaggle staff (Paul Mooney) confirmed on the forum that a private
  cloud workspace and an AI coding assistant are both fine; external tools/models including LLMs are
  permitted under General Rules §2.6 as long as they are reasonably accessible and low cost.
- **No private code sharing** outside your team. Public sharing must go through the Kaggle forum/notebooks
  and is deemed OSI-licensed.
- **Do not redistribute the competition data** (§2.4b). Hence `data/` is gitignored in this repo.
- Winners must deliver reproducible code under an OSI-approved license.

## Participation snapshot (2026-10-10, 4 days in)

4,402 entrants · 145 participants · 145 teams · 145 submissions. Entrant count is vanity; the real field is
the ~145 teams who have actually submitted something, and it will grow sharply in December.
