"""FastAPI service: match data, analytics and the multi-agent explanation endpoints."""
import json
import random
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics as an
from .adapters import from_statsbomb
from .agents import AUDIENCES, LANGUAGES, run_pipeline
from .agents import explain as run_explain
from .generator import generate_match
from .schema import Match

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Match Insights Engine")

MATCHES: dict[str, Match] = {}
MOMENTS: dict[str, list[dict]] = {}
CACHE: dict[tuple, dict] = {}


def register(match: Match) -> Match:
    MATCHES[match.id] = match
    MOMENTS[match.id] = an.detect_moments(match)
    return match


register(generate_match(7))


def get_match(match_id: str) -> Match:
    if match_id not in MATCHES:
        raise HTTPException(404, f"Unknown match '{match_id}'")
    return MATCHES[match_id]


def payload(match: Match) -> dict:
    return {
        "id": match.id, "source": match.source, "competition": match.competition,
        "home": match.home.model_dump(), "away": match.away.model_dump(),
        "summary": an.match_summary(match),
        "momentum": an.momentum(match), "xg": an.xg_timeline(match),
        "possession": an.possession_windows(match),
        "moments": MOMENTS[match.id],
        "events": [
            {"id": e.id, "t": round(e.t / 60, 2), "side": e.side, "type": e.type, "x": e.x, "y": e.y,
             "ex": e.end_x, "ey": e.end_y, "outcome": e.outcome, "xg": e.xg, "player": e.player_name,
             "seq": e.sequence_id}
            for e in match.events
        ],
    }


@app.get("/api/config")
def config() -> dict:
    return {"audiences": list(AUDIENCES), "languages": LANGUAGES, "matches": list(MATCHES)}


@app.get("/api/match/{match_id}")
def read_match(match_id: str) -> dict:
    return payload(get_match(match_id))


@app.post("/api/match/synthetic")
def new_synthetic(seed: int | None = None) -> dict:
    seed = seed if seed is not None else random.randint(1, 10_000)
    return payload(register(generate_match(seed)))


@app.post("/api/match/upload")
async def upload(file: UploadFile) -> dict:
    """Load a real event feed (StatsBomb-style JSON) through the adapter."""
    try:
        raw = json.loads(await file.read())
        match = from_statsbomb(raw, match_id=f"upload-{len(MATCHES)}")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(422, f"Could not parse the event feed: {exc}") from exc
    return payload(register(match))


class ExplainRequest(BaseModel):
    match_id: str
    moment_id: str | None = None  # None = whole-match recap
    audience: str = "casual_fan"
    language: str = "en"


def resolve(req: ExplainRequest) -> tuple[Match, dict | None, tuple]:
    if req.audience not in AUDIENCES or req.language not in LANGUAGES:
        raise HTTPException(422, "Unknown audience or language")
    match = get_match(req.match_id)
    moment = None
    if req.moment_id is not None:
        moment = next((m for m in MOMENTS[req.match_id] if m["id"] == req.moment_id), None)
        if moment is None:
            raise HTTPException(404, "Unknown moment")
    return match, moment, (req.match_id, req.moment_id, req.audience, req.language)


@app.post("/api/explain")
async def explain(req: ExplainRequest) -> dict:
    match, moment, key = resolve(req)
    if key in CACHE:
        return {**CACHE[key], "cached": True}
    try:
        result = await run_explain(match, moment, MOMENTS[req.match_id], req.audience, req.language)
    except Exception as exc:  # model/auth/network failures surface as a readable 502
        raise HTTPException(502, f"The agent pipeline failed: {exc}") from exc
    CACHE[key] = result
    return {**result, "cached": False}


@app.post("/api/explain/stream")
async def explain_stream(req: ExplainRequest) -> StreamingResponse:
    """Same as /api/explain, but streams one JSON object per line as each agent starts and finishes."""
    match, moment, key = resolve(req)

    async def lines():
        if key in CACHE:
            yield json.dumps({"event": "result", "result": {**CACHE[key], "cached": True}}) + "\n"
            return
        try:
            async for ev in run_pipeline(match, moment, MOMENTS[req.match_id], req.audience, req.language):
                if ev["event"] == "result":
                    CACHE[key] = ev["result"]
                    ev = {"event": "result", "result": {**ev["result"], "cached": False}}
                yield json.dumps(ev) + "\n"
        except Exception as exc:
            yield json.dumps({"event": "error", "message": f"The agent pipeline failed: {exc}"}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
