# Attack plan

Status as of **2026-10-10**. 88 days to the 2027-01-06 deadline.

---

## The shape of the submission

One position group × one drill family × one per-opportunity outcome, framed as
**incremental value over draft slot**, named in scout language, and proven with a
held-out draft class.

> *"Controlling for `draft_overall_pick`, position and exposure, this 10 Hz-derived trait
> still moves outcome Y by Z (95% CI …), and neither `forty`, `three_cone` nor
> `ngs_final_score` captures it."*

That sentence is the whole competition. Everything else is support.

---

## Where we are

### Done

- Competition, rules, rubric and host clarifications captured → `competition-brief.md`
- All 9 files / 158 columns documented, annotated where the shipped data disagrees with
  the published dictionary → `data-dictionary.md`
- Known data traps catalogued from the forum and from the engineering research →
  `data-quirks.md`
- Research fan-out: winning patterns, judging craft, drill mechanics, external data,
  presentation conventions → `research-brief.md`
- Library: ingest, kinematics, Combine features, in-game outcomes, reliability, modelling,
  figure system
- `scripts/00_audit_raw.py` re-derives every data claim from the shipped files
- Synthetic fixtures reproduce the real schema *and* its quirks, so the pipeline runs
  end-to-end before the download

### Blocked

- **No competition data.** Needs a Kaggle account that has joined the hackathon plus an
  API token. Everything below step 1 waits on this.

---

## Sequence

### 1 · Get the data and audit it — *blocked on Kaggle access*

```
make data && make parquet && make audit
```

Then read `reports/data_audit.md` and settle these, because several ranked ideas live or
die on the answers:

| Question | Why it decides something |
|---|---|
| **Are there any QBs in the cohort?** The documented `nfl_position` list has no QB. | Changes how much of the public QB-evaluation literature (nfelo included) transfers at all |
| How many prospects have **BALL frames** in `GAUNTLET_DRILL`? | 54 players reported. Below ~40 usable, research question #1 is dead |
| Is the **2024 back-pedal truncation** real? | If yes, idea #3 runs on two draft classes, not three |
| Real counts per position group | Every sample-size estimate in the brief is 🔍 unverified |
| Does `dir` match the 0° = +y convention? | Check 9 of the audit answers this empirically |
| Do tracked 40 times really run ~0.3 s slow? | Determines whether tracked and official times can ever be shown together |

### 2 · Pick the research question — *on the evidence, after step 1*

Decided: we choose once the audit is in. The ranked slate going in:

- **Lead: #3 — DB "transition tax" → `cushion`.** Best signal-to-noise, largest n (122
  DB), and predicting a *coaching decision* rather than a noisy per-play outcome is the
  clever move. Narrative: *the Combine predicted how his own DB coach would play him.*
- **Headline figure: #1 — gauntlet speed-retention → YAC over expected**, *if* the BALL
  coverage survives the audit. Highest novelty in the field; best single image available.
- **Support: #2 — brake vs arc, route-conditional.** The most *explanatory* result: it
  says why twenty years of three-cone studies found nothing.

### 3 · Build the metric

Feature extraction → reliability (ICC across `attempt`) → standardize within
`(drill_name, draft_year)` → residualize against `forty` / `ten_yd_split` / weight →
model against the outcome with partial pooling → leave-one-draft-class-out validation →
nested ladder against `ngs_final_score`.

Name it in scout language. "Transition tax", "change-of-direction debt",
"burst-to-balance" — something that survives being said out loud in a draft room.

### 4 · Figures

Nine slots, one theme function, all through `viz.py`. The plan is in the brief; the two
that matter most:

- **The draft-slot-adjusted effect plot.** Answers the only objection that matters.
- **The same athlete's Combine drill trace beside his NFL in-game trace**, same units,
  same code path. No prior Big Data Bowl could produce that image. Build it early.

### 5 · Write

2,000 words against the published skeleton. Draft the 110-word lede *before* the model is
finished — if "trait / effect + CI / decision changed" cannot be filled with specifics,
the scope is still too wide.

### 6 · Ship

Public notebook · Media Gallery cover image · writeup **submitted, not left in draft** ·
under 2,000 words · fewer than 10 figures · tracking data actually used.

---

## Decisions made

- **Open Track.** $45,000: three finalists at $10,000, three runners-up at $5,000.
  University Track is out of scope.
- **The research question waits on the audit.** Several candidates live or die on facts
  only the data can settle, so `reports/data_audit.md` now opens with a
  *"Decisions this audit settles"* table answering exactly those questions.

## Still open

1. **Kaggle access.** Join the hackathon, then `.venv/bin/kaggle auth login`. Everything
   downstream is blocked on this.
2. **GitHub auth.** Commits are local; `git push -u origin main` needs credentials.
3. **Team.** Max 5, one submission. Is anyone else joining?
4. **A football voice.** One quoted sentence from someone who has coached or played the
   position is disproportionately persuasive to this panel. Do we know anyone?

## Risks

| Risk | Mitigation |
|---|---|
| Combine signal does not survive draft-slot adjustment | The honest null is still publishable here; design the writeup so a null is a finding, not a failure |
| Sample too small for the chosen group | Compute minimum detectable effect **before** looking, and say so in the writeup |
| 2024 back-pedal truncation kills idea #3 | Fall back to two classes and report sensitivity; or pivot to #1/#2 |
| Gauntlet BALL coverage too thin for idea #1 | Demote to an appendix figure |
| Crowded angle — WR gauntlet and DB drills are already being posted publicly | The route-conditional interaction (#2) and the deployment framing (#3) are not what others are doing |
| No internet in the judging notebook | Bake every external join into an attached Kaggle Dataset |
