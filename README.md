# Match Insights Engine

Microsoft Premier League Hackathon ("Inside the Game") entry.
Turns **synthetic football events** into **explainable match intelligence**: ingest events, compute
statistics, explain *why* a moment matters, render it on screen, and personalise it per audience and language.

## How it works

```
Synthetic generator ─┐
                     ├─► canonical event schema ─► analytics (deterministic) ─► tools
StatsBomb-style feed ─┘      (app/schema.py)         (app/analytics.py)           │
                                                                                   ▼
        Analyst ──► Narrator ──► Verifier ──► Localiser ──► numeric guard ──► FastAPI ──► HTML UI
        (tools)     (why it      (checks      (audience +    (deterministic)    (streams agent
                    matters)     claims)      language)                         progress)
```

- **Numbers are never LLM-generated.** Possession, xG, win probability, sequence type (counter-attack,
  sustained pressure, set piece) are computed in `app/analytics.py`. The Analyst agent calls those as tools
  and the later agents may only restate its findings.
- **Four agents** in a `SequentialBuilder` workflow (Microsoft Agent Framework) on a Microsoft Foundry model
  deployment. The UI streams each agent's progress and exposes the tool calls and timings.
- **Two layers of grounding.** The Verifier agent checks every claim against the facts; a deterministic numeric
  guard (`app/grounding.py`) then checks that each figure in the final text can be traced to the data. In an
  adversarial test the Verifier alone missed some planted wrong figures, which is why the guard exists.
  Derived figures (a difference, a sum) are reported as untraced rather than silently accepted.
- **Control vs chaos and tactical shifts.** Each 5-minute window is classified as home control, away control,
  balanced or chaotic (control = possession + field tilt; chaos = possession changing hands far more often than
  the match average). The 10-minute swings in territory and press height are detected as tactical shifts and
  linked to the goal or red card that *preceded* them. Both appear as explainable moments.
- **Player spotlight and pass quality.** `app/players.py` computes progressive passes, a 0-1 pass-quality score,
  chances created, shot speed and a formula-based impact score (formula in the module docstring and shown in the
  UI: it is explicitly *not* a human rating). Selecting a player draws their passes and shots, and the same
  four-agent pipeline explains them, with tools to compare the player against teammates and opponents.
- **Goal roles are computed, not inferred.** `goal_role` labels each goal (opening, equaliser, go-ahead,
  match-winning...) from the score line. Early on, a spotlight called an equaliser "the winning goal" and the
  Verifier approved it, so the role is now handed to the agents as a fact and the Verifier checks against it.
- **Broadcast view.** For the current selection (a moment, a player or the whole match) the agents also write an
  on-screen lower third: a news-style title, one on-air sentence and three figures, drawn over the replay with a
  scorebug, a tag, a win-probability bar and a verification mark. The *Narrator* writes the graphic, so the
  Verifier and the numeric guard check it like any other text; the Localiser translates it. Deep link:
  `/?moment=m7&broadcast=1`. An incomplete graphic is never cached.
- **Audiences:** casual fan, coach, broadcaster. **Languages:** EN, PT, ES, FR, DE, IT.
- **Real data:** only `app/schema.py` is read downstream. `app/adapters.py` converts a StatsBomb-style
  event feed into that schema (upload it with *Load real event feed*). It is tested against a small fixture
  (`tests/`), not against a full real match.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
az login --use-device-code          # authentication is keyless (Azure CLI credential)
copy .env.example .env              # then set your Foundry project endpoint and deployment name
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000. Deep link to a moment: `/?moment=m1`.

Tests: `.\.venv\Scripts\python -m pytest tests -q`

## Running without Azure (recorded demo)

The agents need an Azure sign-in and a Foundry deployment. So that anyone can still run the project, the repository
includes `demo/explanations.json`: **79 explanations recorded earlier by the real agents** for the synthetic demo
match (seed 7). They cover every key moment and the match recap (casual fan, coach and broadcaster in English;
casual fan and broadcaster in Portuguese) and the six highest-impact players of each team (casual fan and
broadcaster, English). The broadcast view works from them too.

```powershell
$env:DEMO_ONLY = "1"      # never contacts Azure (bash: DEMO_ONLY=1)
python -m uvicorn app.main:app --port 8000
```

- Without `DEMO_ONLY` the app tries the live agents and **falls back to the recordings by itself** if Azure
  sign-in is unavailable. The header badge says *Live agents* or *Recorded demo*, and every recorded result is
  labelled as such. Nothing recorded is ever presented as live.
- An unrecorded combination (for example coach in French) shows the recorded English version with a notice. A new
  synthetic match or an uploaded feed has no recordings, so it needs the live agents and says so clearly.
- Each recording is tied to a fingerprint of the demo match. If the generator or analytics change, the old
  recordings are ignored rather than attached to the wrong facts. To re-record, sign in with `az login` and run
  `python -m scripts.pregenerate` (resumable; retries until a result is verified, fully traced and, for the
  broadcaster, has its graphic; throttled on purpose, because three parallel pipelines hit the deployment's rate limit).
- Recordings are the best of up to four attempts, so they show the system at its best, not its average. Measuring
  the average is a separate job.

Tests: `pip install -r requirements-dev.txt`, then `python -m pytest tests -q`.

## Configuration

Everything model-related is in `.env` (copy `.env.example`):

```
FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
FOUNDRY_MODEL=<deployment name>
```

- **Another model:** deploy it in Foundry, put its deployment name in `FOUNDRY_MODEL`, restart. No code change.
- **Another Azure account or project:** `az login` with that account, set the new endpoint, restart.
- **Another model provider:** the client is created in one place, `client()` in `app/agents.py`.
- All four agents share one model today; a stronger model for the Verifier only is a small change, not done.
- Authentication is the Azure CLI credential (`az login`), which suits a local demo. A hosted deployment
  would use a managed identity instead; that is not implemented.

## Using real match data

Use **Load real event feed** in the UI (or `POST /api/match/upload`). The format is detected from the content.

| Format | Adapter | Status |
|---|---|---|
| StatsBomb-style event JSON | `from_statsbomb` | Written from the documented layout; tested on a small fixture only |
| Opta F24 XML | `from_opta_f24` | Structure, end-coordinate qualifiers and the corner flag checked against the open-source `socceraction` parser; event type ids from a secondary source; tested on a hand-made fixture, never on a real feed |

Things to know before trusting real data:
- **Opta card qualifiers are unconfirmed.** The adapter assumes 31 = yellow, 32 = second yellow, 33 = red.
- **F24 carries no player names and no xG** that could be confirmed: players appear as `Player <id>` and xG comes
  from this project's distance/angle model, not from the provider.
- Opta has no possession id, so sequences are derived (a new team on the ball, a gap over 12 s, or a ball won).
- Windows with too little play (under 10 passes per 5 minutes) are never reported as chaotic and cannot
  produce a tactical shift, so a sparse or gappy feed does not invent events.
- Thresholds for chaos and tactical shifts were tuned on the synthetic match and need recalibrating on real data.
- Extra time and shoot-outs are not modelled (the analysis assumes about 93 minutes; Opta period 5 is ignored).
- Feeds are untrusted input: XML is parsed with `defusedxml`.
- **The hackathon requires synthetic data**, so the demo should use the synthetic match. Do not commit real
  match files to this repository; provider data carries its own licence terms.

To support another provider, write a function that returns a `Match` (see `app/schema.py`) and call it from the
upload endpoint in `app/main.py`.

## Layout

| Path | Purpose |
|---|---|
| `app/schema.py` | Canonical Pydantic event model |
| `app/generator.py` | Seeded synthetic match with a scripted story |
| `app/analytics.py` | Stats, xG, momentum, win probability, key-moment detection |
| `app/agents.py` | Analyst / Narrator / Localiser agents and tools |
| `app/adapters.py` | Real-data adapter (StatsBomb-style) |
| `app/main.py` | FastAPI endpoints |
| `static/` | HTML, CSS and JS frontend |
