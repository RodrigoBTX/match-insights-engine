"""FastAPI service: match data, analytics and the multi-agent explanation endpoints."""
import asyncio
import json
import random
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics as an
from . import players as pl
from xml.etree.ElementTree import ParseError  # raised by defusedxml for malformed XML

from .adapters import from_opta_f24, from_statsbomb
from .agents import AUDIENCES, LANGUAGES, reset_client, run_pipeline, warm_up
from .agents import explain as run_explain
from .generator import generate_match
from .schema import Match

STATIC = Path(__file__).resolve().parent.parent / "static"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    asyncio.create_task(asyncio.to_thread(warm_up))  # in the background: do not delay startup
    yield


app = FastAPI(title="Match Insights Engine", lifespan=lifespan)

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


def players_payload(match: Match) -> list[dict]:
    return pl.overview(match)


def payload(match: Match) -> dict:
    return {
        "id": match.id, "source": match.source, "competition": match.competition,
        "home": match.home.model_dump(), "away": match.away.model_dump(),
        "summary": an.match_summary(match),
        "momentum": an.momentum(match), "xg": an.xg_timeline(match),
        "possession": an.possession_windows(match),
        "control": an.control_windows(match),
        "players": players_payload(match),
        "moments": MOMENTS[match.id],
        "events": [
            {"id": e.id, "t": round(e.t / 60, 2), "side": e.side, "type": e.type, "x": e.x, "y": e.y,
             "ex": e.end_x, "ey": e.end_y, "outcome": e.outcome, "xg": e.xg, "player": e.player_name,
             "pid": e.player_id, "prog": e.type == "pass" and e.outcome == "complete"
                                         and pl.gain(e) >= pl.PROGRESSIVE_GAIN_M,
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
    """Load a real event feed through an adapter: Opta F24 XML or StatsBomb-style JSON, detected from the content."""
    data = await file.read()
    match_id = f"upload-{len(MATCHES)}"
    try:
        if data.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<"):
            match = from_opta_f24(data, match_id=match_id)
        else:
            match = from_statsbomb(json.loads(data), match_id=match_id)
    except (ValueError, KeyError, TypeError, AttributeError, ParseError) as exc:
        raise HTTPException(422, f"Could not parse the event feed: {exc}") from exc
    return payload(register(match))


class ExplainRequest(BaseModel):
    match_id: str
    moment_id: str | None = None  # None (and no player_id) = whole-match recap
    player_id: int | None = None  # set = player spotlight
    audience: str = "casual_fan"
    language: str = "en"


def resolve(req: ExplainRequest) -> tuple[Match, dict | None, dict | None, tuple]:
    if req.audience not in AUDIENCES or req.language not in LANGUAGES:
        raise HTTPException(422, "Unknown audience or language")
    match = get_match(req.match_id)
    moment = player = None
    if req.player_id is not None:
        player = pl.player_facts(match, req.player_id)
        if player is None:
            raise HTTPException(404, "Unknown or inactive player")
    elif req.moment_id is not None:
        moment = next((m for m in MOMENTS[req.match_id] if m["id"] == req.moment_id), None)
        if moment is None:
            raise HTTPException(404, "Unknown moment")
    return match, moment, player, (req.match_id, req.moment_id, req.player_id, req.audience, req.language)


@app.post("/api/explain")
async def explain(req: ExplainRequest) -> dict:
    match, moment, player, key = resolve(req)
    if key in CACHE:
        return {**CACHE[key], "cached": True}
    for attempt in (1, 2):
        try:
            result = await run_explain(match, moment, MOMENTS[req.match_id], req.audience, req.language, player)
            break
        except Exception as exc:  # model/auth/network failures surface as a readable 502
            if attempt == 1 and "Azure CLI" in str(exc):
                reset_client()
                continue
            raise HTTPException(502, f"The agent pipeline failed: {exc}") from exc
    CACHE[key] = result
    return {**result, "cached": False}


@app.post("/api/explain/stream")
async def explain_stream(req: ExplainRequest) -> StreamingResponse:
    """Same as /api/explain, but streams one JSON object per line as each agent starts and finishes."""
    match, moment, player, key = resolve(req)

    async def lines():
        if key in CACHE:
            yield json.dumps({"event": "result", "result": {**CACHE[key], "cached": True}}) + "\n"
            return
        for attempt in (1, 2):
            try:
                async for ev in run_pipeline(match, moment, MOMENTS[req.match_id], req.audience, req.language, player):
                    if ev["event"] == "result":
                        CACHE[key] = ev["result"]
                        ev = {"event": "result", "result": {**ev["result"], "cached": False}}
                    yield json.dumps(ev) + "\n"
                return
            except Exception as exc:
                if attempt == 1 and "Azure CLI" in str(exc):  # the `az` subprocess failed once on a cold start
                    reset_client()
                    continue
                yield json.dumps({"event": "error", "message": f"The agent pipeline failed: {exc}"}) + "\n"
                return

    return StreamingResponse(lines(), media_type="application/x-ndjson")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
