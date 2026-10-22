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
