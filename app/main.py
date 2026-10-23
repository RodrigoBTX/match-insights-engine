"""FastAPI service: match data, analytics and the multi-agent explanation endpoints."""
import asyncio
import json
import os
import random
from contextlib import asynccontextmanager
from pathlib import Path
from xml.etree.ElementTree import ParseError  # raised by defusedxml for malformed XML

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics as an
from . import demo
from . import players as pl
from .adapters import from_opta_f24, from_statsbomb
from .agents import AUDIENCES, LANGUAGES, reset_client, run_pipeline, warm_up
from .agents import explain as run_explain
from .generator import generate_match
from .schema import Match

STATIC = Path(__file__).resolve().parent.parent / "static"

# DEMO_ONLY=1 never contacts Azure: only recorded explanations are shown. Without it the app tries live agents
# and falls back to the recordings by itself when Azure sign-in is not available.
DEMO_ONLY = os.environ.get("DEMO_ONLY") == "1"
STATE: dict = {"live": None}  # None = not known yet, True/False once a check or a request has told us


async def check_live() -> None:
    STATE["live"] = await asyncio.to_thread(warm_up)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if DEMO_ONLY:
        STATE["live"] = False
    else:
        asyncio.create_task(check_live())  # in the background: do not delay startup
    yield


app = FastAPI(title="Match Insights Engine", lifespan=lifespan)

MATCHES: dict[str, Match] = {}
MOMENTS: dict[str, list[dict]] = {}
CACHE: dict[tuple, dict] = {}
RECORDED: dict[tuple, dict] = {}  # explanations recorded earlier for the demo match
DEMO_INFO: dict = {}


def register(match: Match) -> Match:
    MATCHES[match.id] = match
    MOMENTS[match.id] = an.detect_moments(match)
    return match


def load_demo() -> None:
    """Make the recordings available (they are ignored if the demo match no longer matches them)."""
    entries, info = demo.install(MATCHES[demo.DEMO_MATCH_ID], MOMENTS[demo.DEMO_MATCH_ID])
    RECORDED.clear()
    RECORDED.update({k: {**r, "recorded": True} for k, r in entries.items()})
    DEMO_INFO.clear()
    DEMO_INFO.update(info)
    for k, r in RECORDED.items():
        CACHE.setdefault(k, r)


register(generate_match(7))
load_demo()


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


@app.get("/api/status")
def status() -> dict:
    """Whether live agents can run here, and what is recorded for the demo match."""
    return {"live": STATE["live"], "demo_only": DEMO_ONLY, "recorded": len(RECORDED),
            "demo_match": demo.DEMO_MATCH_ID, "recordings": DEMO_INFO}


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


def cacheable(req: ExplainRequest, result: dict) -> bool:
    """A broadcaster result without its graphic is incomplete: do not cache it, so a retry can succeed."""
    return req.audience != "broadcaster" or bool(result.get("graphic"))


def recorded_fallback(key: tuple, reason: str) -> dict | None:
    """The nearest recording when live agents cannot run, labelled so the UI never passes it off as live."""
    fb = demo.pick_fallback(RECORDED, key)
    if fb is None:
        return None
    result = {**RECORDED[fb], "cached": True, "recorded": True}
    if fb != key:
        result["fallback"] = {"reason": reason, "requested": {"audience": key[3], "language": key[4]},
                              "shown": {"audience": fb[3], "language": fb[4]}}
    return result


def unavailable_message(key: tuple, reason: str) -> str:
    scope = ("Recordings cover the original synthetic match only." if key[0] != demo.DEMO_MATCH_ID
             else "Recordings cover every moment, the match recap and the six highest-impact players of each team.")
    return f"Live agents are unavailable ({reason}) and this selection was not recorded. {scope}"


@app.post("/api/explain")
async def explain(req: ExplainRequest) -> dict:
    match, moment, player, key = resolve(req)
    if key in CACHE:
        return {**CACHE[key], "cached": True}
    if DEMO_ONLY:
        reason = "demo-only mode"
        result = recorded_fallback(key, reason)
        if result is None:
            raise HTTPException(503, unavailable_message(key, reason))
        return result
    for attempt in (1, 2):
        try:
            result = await run_explain(match, moment, MOMENTS[req.match_id], req.audience, req.language, player)
            break
        except Exception as exc:  # model/auth/network failures surface as a readable error
            if attempt == 1 and "Azure CLI" in str(exc):
                reset_client()
                continue
            if demo.is_auth_error(exc):
                STATE["live"] = False
                reason = "Azure sign-in not available"
                fallback = recorded_fallback(key, reason)
                if fallback is None:
                    raise HTTPException(503, unavailable_message(key, reason)) from exc
                return fallback
            raise HTTPException(502, f"The agent pipeline failed: {exc}") from exc
    STATE["live"] = True
    if cacheable(req, result):
        CACHE[key] = result
    return {**result, "cached": False}


@app.post("/api/explain/stream")
async def explain_stream(req: ExplainRequest) -> StreamingResponse:
    """Same as /api/explain, but streams one JSON object per line as each agent starts and finishes."""
    match, moment, player, key = resolve(req)

    def fallback_events(reason: str) -> str:
        result = recorded_fallback(key, reason)
        if result is None:
            return json.dumps({"event": "error", "message": unavailable_message(key, reason)}) + "\n"
        return json.dumps({"event": "result", "result": result}) + "\n"

    async def lines():
        if key in CACHE:
            yield json.dumps({"event": "result", "result": {**CACHE[key], "cached": True}}) + "\n"
            return
        if DEMO_ONLY:
            yield fallback_events("demo-only mode")
            return
        for attempt in (1, 2):
            try:
                async for ev in run_pipeline(match, moment, MOMENTS[req.match_id], req.audience, req.language, player):
                    if ev["event"] == "result":
                        STATE["live"] = True
                        if cacheable(req, ev["result"]):
                            CACHE[key] = ev["result"]
                        ev = {"event": "result", "result": {**ev["result"], "cached": False}}
                    yield json.dumps(ev) + "\n"
                return
            except Exception as exc:
                if attempt == 1 and "Azure CLI" in str(exc):  # the `az` subprocess failed once on a cold start
                    reset_client()
                    continue
                if demo.is_auth_error(exc):
                    STATE["live"] = False
                    yield fallback_events("Azure sign-in not available")
                    return
                yield json.dumps({"event": "error", "message": f"The agent pipeline failed: {exc}"}) + "\n"
                return

    return StreamingResponse(lines(), media_type="application/x-ndjson")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
