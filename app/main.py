"""FastAPI service: match data, analytics and the multi-agent explanation endpoints."""
import asyncio
import json
import logging
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
from . import chips as chips_mod
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
log = logging.getLogger("uvicorn.error")
MAX_UPLOAD_BYTES = 25 * 2**20  # a full Opta F24 match is a few MB
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
        # key figures per moment so the UI can show them on the first click, without waiting for the agents;
        # added on copies: the stored moments (and so the recordings' fingerprint) are untouched
        "moments": [{**m, "chips": chips_mod.build_chips(match, m, None, "en")} for m in MOMENTS[match.id]],
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
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"The event feed is larger than {MAX_UPLOAD_BYTES // 2**20} MB")
    match_id = f"upload-{len(MATCHES)}"
    try:
        if data.lstrip(b"\xef\xbb\xbf \r\n\t").startswith(b"<"):
            match = from_opta_f24(data, match_id=match_id)
        else:
            match = from_statsbomb(json.loads(data), match_id=match_id)
    except (ValueError, KeyError, TypeError, AttributeError, ParseError) as exc:
        if not data.strip():
            why = "the file is empty"
        elif isinstance(exc, ParseError):
            why = "it is not valid XML"
        elif isinstance(exc, json.JSONDecodeError):
            why = "it is not valid JSON"
        else:
            why = str(exc) or "unexpected content"
        raise HTTPException(422, f"This file could not be read as an Opta F24 or StatsBomb event feed: {why}.") from exc
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


def finalize(result: dict, match: Match, moment: dict | None, player: dict | None, language: str, **flags) -> dict:
    """Put the computed key figures on a result before it is served.

    The agents write the text; the figures on screen (panel cards and the graphic's three cards) come from the
    data, with team names and both sides of every comparison. Applying them here, rather than when the agents
    run, also corrects results that were recorded or cached earlier.
    """
    out = {**result, **flags}
    shown = (out.get("fallback") or {}).get("shown", {}).get("language", language)
    chips = chips_mod.build_chips(match, moment, player, shown)
    if chips:
        out["stat_chips"] = chips
        if out.get("graphic"):
            out["graphic"] = {**out["graphic"], "chips": chips}
    return out


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


def failure_reason(exc: BaseException) -> str:
    """A short, plain reason for a failed run. The raw error (class names, request ids) goes to the server log only."""
    text = f"{type(exc).__name__}: {exc}"
    if any(k in text for k in ("DeploymentNotFound", "NotFoundError")):
        return "the AI model deployment was not found"
    if any(k in text for k in ("RateLimit", "429", "Too Many Requests")):
        return "the AI service is busy right now"
    if any(k in text for k in ("Connection error", "APIConnectionError", "Timeout", "timed out", "ConnectError")):
        return "the AI service could not be reached"
    return "the agents could not complete the request"


def failure_message(reason: str) -> str:
    return f"{reason[0].upper()}{reason[1:]}. Please try again in a moment."


def unavailable_message(key: tuple, reason: str) -> str:
    scope = ("Recordings cover the original synthetic match only." if key[0] != demo.DEMO_MATCH_ID
             else "Recordings cover every moment, the match recap and the six highest-impact players of each team.")
    return f"Live agents are unavailable ({reason}) and this selection was not recorded. {scope}"


@app.post("/api/explain")
async def explain(req: ExplainRequest) -> dict:
    match, moment, player, key = resolve(req)
    if key in CACHE:
        return finalize(CACHE[key], match, moment, player, req.language, cached=True)
    if DEMO_ONLY:
        reason = "demo-only mode"
        result = recorded_fallback(key, reason)
        if result is None:
            raise HTTPException(503, unavailable_message(key, reason))
        return finalize(result, match, moment, player, req.language)
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
                return finalize(fallback, match, moment, player, req.language)
            log.error("agent pipeline failed", exc_info=exc)
            reason = failure_reason(exc)
            fallback = recorded_fallback(key, reason)
            if fallback is None:
                raise HTTPException(502, failure_message(reason)) from exc
            return finalize(fallback, match, moment, player, req.language)
    STATE["live"] = True
    if cacheable(req, result):
        CACHE[key] = result
    return finalize(result, match, moment, player, req.language, cached=False)


@app.post("/api/explain/stream")
async def explain_stream(req: ExplainRequest) -> StreamingResponse:
    """Same as /api/explain, but streams one JSON object per line as each agent starts and finishes."""
    match, moment, player, key = resolve(req)

    def fallback_events(reason: str) -> str:
        result = recorded_fallback(key, reason)
        if result is None:
            return json.dumps({"event": "error", "message": unavailable_message(key, reason)}) + "\n"
        return json.dumps({"event": "result",
                           "result": finalize(result, match, moment, player, req.language)}) + "\n"

    async def lines():
        if key in CACHE:
            res = finalize(CACHE[key], match, moment, player, req.language, cached=True)
            yield json.dumps({"event": "result", "result": res}) + "\n"
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
                        ev = {"event": "result",
                              "result": finalize(ev["result"], match, moment, player, req.language, cached=False)}
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
                log.error("agent pipeline failed", exc_info=exc)
                reason = failure_reason(exc)
                if recorded_fallback(key, reason) is not None:
                    yield fallback_events(reason)
                else:
                    yield json.dumps({"event": "error", "message": failure_message(reason)}) + "\n"
                return

    return StreamingResponse(lines(), media_type="application/x-ndjson")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
