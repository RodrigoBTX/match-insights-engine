# Quality report: first-try results

Generated 2026-10-26 with `gpt-4.1-mini`. Command: `python -m scripts.quality_report`.

Every case ran **once**; the first result counts (no retries on quality, unlike the recordings in `demo/`, which keep the best of up to four attempts). Only infrastructure failures such as rate limits were retried.

**What a pass means:** the verifier flagged nothing, every figure in the text traces to the data, the broadcast graphic exists, a chaotic-spell text does not name just one team, and a goal headline or graphic does not call the goal the winner, the equaliser or the opener when the computed goal role says otherwise. **It does not mean the writing is good or useful.** Titles can still be generic and grammar can still slip.


> **Read this first.** This is the **second** run. The first run ([quality_report_run1.md](quality_report_run1.md): 84%, 41/49) exposed failures that were then fixed (the Verifier prompt, which listed supported claims as issues and still asked for figure cards that are now computed, and a stricter chaotic-spell rule). The fixes were made after seeing those failures, on the same 49 cases, so this run shows whether the fixes work, **not** the quality on unseen cases. The chaotic spell is still the weak spot: 2 of 4 cases fail.

## Result

- Cases: **49** (match: the synthetic demo match, seed 7)
- Clean on the first try: **96% (47/49)**

### Why cases failed (a case can fail for more than one reason)

| Reason | Cases |
|---|---|
| wording | 2 |

### By audience

| Group | Clean first try |
|---|---|
| broadcaster | 95% (20/21) |
| casual_fan | 94% (16/17) |
| coach | 100% (11/11) |

### By language

| Group | Clean first try |
|---|---|
| en | 97% (38/39) |
| pt | 90% (9/10) |

### By kind of target

| Group | Clean first try |
|---|---|
| big_chance | 100% (8/8) |
| chaotic_spell | 50% (2/4) |
| goal | 100% (12/12) |
| player | 100% (6/6) |
| recap | 100% (3/3) |
| red_card | 100% (4/4) |
| tactical_shift | 100% (12/12) |

## Speed (live agents)

- Per explanation: median 10.6 s, slowest 26.0 s (49 runs, 2 in parallel)
- Mean per agent: Analyst 3.9 s, Narrator 2.1 s, Verifier 1.1 s, Localiser 3.7 s
- Recorded results and the selection card are instant; only a new live explanation pays this cost.

## Failing cases

- **Chaotic spell – 35' to 45' / broadcaster / pt**
  - text: _Fase caótica entre os minutos 35 e 45 com domínio do Northbridge FC | Fase caótica entre os minutos 35 e 45 | Posse, sequências e perdas de bola durante esta fase intensa de jogo._
  - wording: headline: A chaotic spell concerns both teams, but the text names only one of them.
  - wording: explanation: A chaotic spell concerns both teams, but the text names only one of them.
- **Chaotic spell – 35' to 45' / casual_fan / en**
  - text: _Northbridge FC fights back fiercely in chaotic spell_
  - wording: headline: A chaotic spell concerns both teams, but the text names only one of them.

Infrastructure retries (rate limit and similar, not counted as quality): 0.

## Limits of this measurement

- One synthetic match, one run per case: a different run can give a different result (the model varies).
- The checks find errors that can be detected by rules. They cannot judge clarity, usefulness or tone.
- English and Portuguese only; other languages were not measured.
- Goal-role checks apply to English text only.
