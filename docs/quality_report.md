# Quality report: first-try results

Generated 2026-10-26 with `gpt-4.1-mini`. Command: `python -m scripts.quality_report`.

Every case ran **once**; the first result counts (no retries on quality, unlike the recordings in `demo/`, which keep the best of up to four attempts). Only infrastructure failures such as rate limits were retried.

**What a pass means:** the verifier flagged nothing, every figure in the text traces to the data, the broadcast graphic exists, a chaotic-spell text does not name just one team, and a goal headline or graphic does not call the goal the winner, the equaliser or the opener when the computed goal role says otherwise. **It does not mean the writing is good or useful.** Titles can still be generic and grammar can still slip.

## Result

- Cases: **49** (match: the synthetic demo match (seed 7), the one used while tuning the prompts and rules)
- Clean on the **first draft** (nothing flagged, no revision needed): **90% (44/49)**
- Clean **after the automatic revision**, which is what the user sees: **96% (47/49)**
- Revisions triggered: 4; the revised draft was kept in 3, the first draft in 1 (revision errors: 0).

### Why cases failed (a case can fail for more than one reason)

| Reason | Cases |
|---|---|
| wording | 1 |
| verifier | 1 |
| pipeline error | 1 |

### By audience

| Group | Clean first draft | Clean after revision |
|---|---|---|
| broadcaster | 90% (19/21) | 95% (20/21) |
| casual_fan | 100% (17/17) | 100% (17/17) |
| coach | 73% (8/11) | 91% (10/11) |

### By language

| Group | Clean first draft | Clean after revision |
|---|---|---|
| en | 90% (35/39) | 97% (38/39) |
| pt | 90% (9/10) | 90% (9/10) |

### By kind of target

| Group | Clean first draft | Clean after revision |
|---|---|---|
| big_chance | 88% (7/8) | 100% (8/8) |
| chaotic_spell | 25% (1/4) | 75% (3/4) |
| goal | 100% (12/12) | 100% (12/12) |
| player | 100% (6/6) | 100% (6/6) |
| recap | 67% (2/3) | 67% (2/3) |
| red_card | 100% (4/4) | 100% (4/4) |
| tactical_shift | 100% (12/12) | 100% (12/12) |

## Speed (live agents)

- Per explanation: median 11.1 s, slowest 35.1 s (48 runs, 2 in parallel)
- Mean per agent: Analyst 3.9 s, Narrator 2.5 s, Verifier 1.0 s, Localiser 3.7 s
- Recorded results and the selection card are instant; only a new live explanation pays this cost.

## Revised cases (the first draft was flagged and rewritten once)

- **Big chance saved – Northbridge FC / coach / en** (fixed; kept the revised draft)
  - flagged: These figures are not in the data and must not be used: 34.5, 44.5
- **Chaotic spell – 35' to 45' / broadcaster / en** (fixed; kept the revised draft)
  - flagged: headline: A chaotic spell concerns both teams, but the text names only one of them.
- **Chaotic spell – 35' to 45' / broadcaster / pt** (still flagged; kept the first draft)
  - flagged: Claim 'Both teams lose control in chaotic ten-minute spell' is not explicitly supported; the facts show Northbridge FC increased possession and pressure, not both teams losing control.
  - flagged: Claim 'Possession tilted towards Northbridge FC' is supported, but the phrase 'both teams experienced... with rapid possession changes and shorter sequences' is ambiguous and slightly imprecise; posse
  - flagged: Claim 'filure of shots and disrupted play without a change in score' is partially supported but no mention of 'flurry of shots' in facts; only number of shots during spell is mentioned (5 for home and
- **Chaotic spell – 35' to 45' / coach / en** (fixed; kept the revised draft)
  - flagged: headline: A chaotic spell concerns both teams, but the text names only one of them.

## Failing cases (after revision)

- **Chaotic spell – 35' to 45' / broadcaster / pt**
  - text: _Fase caótica entre Northbridge FC e Eastport United com controlo a favor do Northbridge | Período caótico de posse e pressão | Momento intenso com mais sequências rápidas e domínio territorial do Northbridge FC_
  - verifier: Claim 'Both teams lose control in chaotic ten-minute spell' is not explicitly supported; the facts show Northbridge FC increased possession and pressure, not both teams losing control.
  - verifier: Claim 'Possession tilted towards Northbridge FC' is supported, but the phrase 'both teams experienced... with rapid possession changes and shorter sequences' is ambiguous and slightly imprecise; possession notably shifted to Northbridge FC.
  - verifier: Claim 'filure of shots and disrupted play without a change in score' is partially supported but no mention of 'flurry of shots' in facts; only number of shots during spell is mentioned (5 for home and 1 for away), which may not justify 'flurry' term.
  - verifier: Claim 'Both teams turned the ball over more frequently' is supported by turnovers per minute increasing from 2.3 to 4.5. No issue here.
  - verifier: Claim 'This spell highlights how quickly momentum can shift and control can be lost by both teams simultaneously' is unsupported; facts show Northbridge seized more control and Eastport had reduced shots and possession.
  - wording: graphic line: A chaotic spell concerns both teams, but the text names only one of them.
- **match recap / coach / en**
  - pipeline error: Expecting ':' delimiter: line 1 column 2138 (char 2137)

Infrastructure retries (rate limit and similar, not counted as quality): 0.

## Limits of this measurement

- One synthetic match, one run per case: a different run can give a different result (the model varies).
- The checks find errors that can be detected by rules. They cannot judge clarity, usefulness or tone.
- English and Portuguese only; other languages were not measured.
- Goal-role checks apply to English text only.
