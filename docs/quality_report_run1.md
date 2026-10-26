# Quality report: first-try results

Generated 2026-10-26 with `gpt-4.1-mini`. Command: `python -m scripts.quality_report`.

Every case ran **once**; the first result counts (no retries on quality, unlike the recordings in `demo/`, which keep the best of up to four attempts). Only infrastructure failures such as rate limits were retried.

**What a pass means:** the verifier flagged nothing, every figure in the text traces to the data, the broadcast graphic exists, a chaotic-spell text does not name just one team, and a goal headline or graphic does not call the goal the winner, the equaliser or the opener when the computed goal role says otherwise. **It does not mean the writing is good or useful.** Titles can still be generic and grammar can still slip.

## Result

- Cases: **49** (match: the synthetic demo match, seed 7)
- Clean on the first try: **84% (41/49)**

### Why cases failed (a case can fail for more than one reason)

| Reason | Cases |
|---|---|
| verifier | 3 |
| wording | 3 |
| goal role | 1 |
| untraced figures | 1 |

### By audience

| Group | Clean first try |
|---|---|
| broadcaster | 76% (16/21) |
| casual_fan | 88% (15/17) |
| coach | 91% (10/11) |

### By language

| Group | Clean first try |
|---|---|
| en | 82% (32/39) |
| pt | 90% (9/10) |

### By kind of target

| Group | Clean first try |
|---|---|
| big_chance | 88% (7/8) |
| chaotic_spell | 25% (1/4) |
| goal | 75% (9/12) |
| player | 100% (6/6) |
| recap | 100% (3/3) |
| red_card | 100% (4/4) |
| tactical_shift | 92% (11/12) |

## Speed (live agents)

- Per explanation: median 11.2 s, slowest 24.9 s (49 runs, 2 in parallel)
- Mean per agent: Analyst 4.1 s, Narrator 2.2 s, Verifier 1.3 s, Localiser 3.6 s
- Recorded results and the selection card are instant; only a new live explanation pays this cost.

## Failing cases

- **Big chance saved – Eastport United / broadcaster / en**
  - verifier: 'Callum Reid's shot speed was 101.6 km/h' is supported but 'high chance quality' is subjective and not explicitly supported.
  - verifier: 'Eastport United struggled to break through a well-organized defense' is implied but not directly supported as a causal statement.
  - verifier: Graphic line 'Callum Reid's 0.33 xG shot late failed to change Northbridge's 2-1 lead' is accurate but 'late' is general and acceptable here.
- **Chaotic spell – 35' to 45' / broadcaster / en**
  - wording: headline: A chaotic spell concerns both teams, but the text names only one of them.
- **Chaotic spell – 35' to 45' / casual_fan / en**
  - wording: headline: A chaotic spell concerns both teams, but the text names only one of them.
- **Chaotic spell – 35' to 45' / coach / en**
  - wording: headline: A chaotic spell concerns both teams, but the text names only one of them.
- **Goal – Eastport United (counter-attack) / broadcaster / pt**
  - verifier: Claim that the goal was 'contra a corrente do jogo' (against the run of play) is supported by the facts indicating home control before the goal. No issue.
  - verifier: Claim about possession percentages in the stat chips matches the facts. No issue.
  - verifier: Claim about xG before the goal matches the facts. No issue.
  - verifier: Claim about the counter-attack duration of 7 seconds matches the facts. No issue.
  - verifier: Claim about the shot speed of 96 km/h matches the facts. No issue.
  - verifier: Claim about win probability for Eastport United rising to 65.6% after the goal matches the facts. No issue.
  - verifier: Narrator's line calling the goal a 'golo contra a corrente' and a rapid counter-attack is supported; 'opening goal' is as per goal_role. No issue.
  - verifier: Graphic title and line match the facts; no issue.
  - verifier: Tactical takeaway is a valid interpretation and aligns with facts.
  - verifier: Therefore, all claims are supported except the minor issue that the graphic object in the last Narrator message does not contain 'line' or 'chip' objects as required by the Instruction to check graphic title, line and chip values exactly. This is a structural omission but does not contradict facts.
- **Goal – Northbridge FC (sustained-pressure) / broadcaster / en**
  - goal role: text says 'opening goal' but the goal was: go-ahead goal (match-winning)
- **Goal – Northbridge FC (sustained-pressure) / casual_fan / en**
  - untraced figures: ['90']
- **Tactical shift – Eastport United take territorial control / broadcaster / en**
  - verifier: No player is specified for the tactical_shift event, so any implied player involvement would be unsupported.
  - verifier: The claim that Eastport United 'nearly doubled their shots and expected goals compared to the previous period' is not supported because previous shots were 1 and after were 3 (not nearly double), and xG changed from 0.02 to 0.79 (a large increase but the term 'nearly doubled' is misleading).
  - verifier: The graphic line 'Eastport United improved possession and attacking pressure after their tactical adjustment at 23 minutes' is vague but aligns with data; no strict issue here.
  - verifier: No direct claim about scoring goals, goal roles, or win probability changes was made, matching the facts.
  - verifier: The 'tactical_takeaway' summary is general and supported by the factual data change.

Infrastructure retries (rate limit and similar, not counted as quality): 0.

## Limits of this measurement

- One synthetic match, one run per case: a different run can give a different result (the model varies).
- The checks find errors that can be detected by rules. They cannot judge clarity, usefulness or tone.
- English and Portuguese only; other languages were not measured.
- Goal-role checks apply to English text only.
