# Quality report: first-try results

Generated 2026-10-26 with `gpt-4.1-mini`. Command: `python -m scripts.quality_report`.

Every case ran **once**; the first result counts (no retries on quality, unlike the recordings in `demo/`, which keep the best of up to four attempts). Only infrastructure failures such as rate limits were retried.

**What a pass means:** the verifier flagged nothing, every figure in the text traces to the data, the broadcast graphic exists, a chaotic-spell text does not name just one team, and a goal headline or graphic does not call the goal the winner, the equaliser or the opener when the computed goal role says otherwise. **It does not mean the writing is good or useful.** Titles can still be generic and grammar can still slip.

> **Held-out measurement.** No prompt or rule was changed after looking at this match. It has the same scripted story as the demo match (same minutes), only the random play and the figures differ, so it is a partly independent check, not a different football match.

## Result

- Cases: **49** (match: a different synthetic match (seed 11))
- Clean on the **first draft** (nothing flagged, no revision needed): **96% (47/49)**
- Clean **after the automatic revision**, which is what the user sees: **100% (49/49)**
- Revisions triggered: 2; the revised draft was kept in 2, the first draft in 0 (revision errors: 0).

### Why cases failed (a case can fail for more than one reason)

| Reason | Cases |
|---|---|
| none | 0 |

### By audience

| Group | Clean first draft | Clean after revision |
|---|---|---|
| broadcaster | 100% (21/21) | 100% (21/21) |
| casual_fan | 94% (16/17) | 100% (17/17) |
| coach | 91% (10/11) | 100% (11/11) |

### By language

| Group | Clean first draft | Clean after revision |
|---|---|---|
| en | 95% (37/39) | 100% (39/39) |
| pt | 100% (10/10) | 100% (10/10) |

### By kind of target

| Group | Clean first draft | Clean after revision |
|---|---|---|
| big_chance | 100% (8/8) | 100% (8/8) |
| chaotic_spell | 75% (3/4) | 100% (4/4) |
| goal | 92% (11/12) | 100% (12/12) |
| player | 100% (6/6) | 100% (6/6) |
| recap | 100% (3/3) | 100% (3/3) |
| red_card | 100% (4/4) | 100% (4/4) |
| tactical_shift | 100% (12/12) | 100% (12/12) |

## Speed (live agents)

- Per explanation: median 11.0 s, slowest 23.1 s (49 runs, 2 in parallel)
- Mean per agent: Analyst 4.2 s, Narrator 2.4 s, Verifier 1.0 s, Localiser 3.9 s
- Recorded results and the selection card are instant; only a new live explanation pays this cost.

## Revised cases (the first draft was flagged and rewritten once)

- **Chaotic spell – 35' to 45' / casual_fan / en** (fixed; kept the revised draft)
  - flagged: headline: A chaotic spell concerns both teams, but the text names only one of them.
- **Goal – Northbridge FC (set-piece) / coach / en** (fixed; kept the revised draft)
  - flagged: These figures are not in the data and must not be used: 60

## Failing cases (after revision)

None.

Infrastructure retries (rate limit and similar, not counted as quality): 0.

## Limits of this measurement

- One synthetic match, one run per case: a different run can give a different result (the model varies).
- The checks find errors that can be detected by rules. They cannot judge clarity, usefulness or tone.
- English and Portuguese only; other languages were not measured.
- Goal-role checks apply to English text only.
