"""Multi-agent pipeline on Microsoft Agent Framework + Microsoft Foundry.

A SequentialBuilder workflow shares one conversation between four agents:

  Analyst   - calls deterministic analytics tools and returns grounded findings
  Narrator  - explains why the moment matters, using only those facts
  Verifier  - checks every claim of the Narrator against the facts (hallucination guard)
  Localiser - removes anything the Verifier flagged, then adapts audience and language

Numbers come from app.analytics (facts and tools); the agents interpret them.
"""
import json
import re
import time
from collections.abc import AsyncIterator

from agent_framework import Agent, tool
from agent_framework_foundry import FoundryChatClient
from agent_framework_orchestrations import SequentialBuilder
from azure.identity import AzureCliCredential
from dotenv import load_dotenv

from . import analytics as an
from .grounding import allowed_numbers, numeric_check
from .schema import Match

load_dotenv()

AUDIENCES = {
    "casual_fan": "a casual fan: plain words, no jargon, one or two vivid sentences of context",
    "coach": "a coach: tactical detail, pressing/transition/shape language, concrete numbers, what to change",
    "broadcaster": "a TV commentator: a punchy on-air line plus one stat graphic caption, broadcast-ready",
}
LANGUAGES = {"en": "English", "pt": "European Portuguese", "es": "Spanish", "fr": "French",
             "de": "German", "it": "Italian"}

_client: FoundryChatClient | None = None


def client() -> FoundryChatClient:
    global _client
    if _client is None:
        _client = FoundryChatClient(credential=AzureCliCredential())
    return _client


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def make_tools(match: Match, trace: list[dict], evidence: list[str]):
    seqs = an.sequences(match)

    def log(name: str, args: dict) -> None:
        trace.append({"agent": "Analyst", "tool": name, "args": args})

    def reply(payload: dict) -> str:
        out = json.dumps(payload)
        evidence.append(out)  # tool results count as traceable data for the numeric guard
        return out

    @tool(name="window_stats", description="Possession, shots, xG, final-third passes, field tilt, press height "
          "(metres from own goal where the ball is won), sequences per minute and passes per sequence between "
          "two match minutes. Keys are 'home' and 'away'. Use it to compare phases of the game.")
    def window_stats(start_minute: float, end_minute: float) -> str:
        log("window_stats", {"start_minute": start_minute, "end_minute": end_minute})
        return reply(an.window_stats(match, start_minute, end_minute))

    @tool(name="sequence_details", description="Details of one possession sequence by id: kind "
          "(counter-attack, sustained-pressure, set-piece...), passes, duration, metres gained, pass speed.")
    def sequence_details(sequence_id: int) -> str:
        log("sequence_details", {"sequence_id": sequence_id})
        s = seqs.get(sequence_id)
        return reply({k: v for k, v in s.items() if k != "event_ids"} if s else {"error": "unknown sequence"})

    @tool(name="score_and_win_probability", description="Score and Poisson win probability at a given match minute.")
    def score_and_win_probability(minute: float) -> str:
        log("score_and_win_probability", {"minute": minute})
        t = minute * 60
        h, a = an.score_at(match, t)
        reds = an.reds_before(match, t)
        return reply({"score": f"{h}-{a}", "win_probability": an.win_probability(
            h - a, 93 - minute, reds["home"], reds["away"])})

    return [window_stats, sequence_details, score_and_win_probability]


NAMING = (
    "Always name teams and players (facts.teams maps the home/away keys to team names); never write 'home' "
    "or 'away' as if it were a name. "
)

ANALYST_PROMPT = (
    "You are the Analyst agent of a football match-intelligence system. The conversation starts with verified "
    "facts about one match moment. Use your tools to check context (e.g. compare the 10 minutes before with the "
    "10 minutes after, inspect the sequence). Then reply with ONLY a JSON object: "
    '{"findings": ["3 to 5 short, factual findings"], "stat_chips": [{"label": "...", "value": "..."}]} '
    "with at most 5 stat_chips. Copy numbers exactly from the facts or tool results; never invent numbers. "
    + NAMING +
    "last_10_min_before_moment covers the 10 minutes before the moment and excludes the moment itself. "
    "Say what the data explains: why this moment mattered (score, win probability), whether it went with or "
    "against the run of play, and what changed tactically. For event 'tactical_shift' explain the swing using "
    "field tilt (share of final-third passes), press height (metres from own goal where the ball is won) and "
    "likely_trigger; for 'chaotic_spell' explain the loss of control by BOTH teams: more sequences per minute, "
    "fewer passes per sequence and more turnovers than ten_minutes_before_spell and the rest of the match. A "
    "chaotic spell is not one team imposing itself: never say a team raised its pressure or possession unless "
    "ten_minutes_before_spell and during_spell show that rise. Report only what the numbers show; do not claim a "
    "cause that is not in likely_trigger. Ignore the delivery request; it is for the Localiser."
)
NARRATOR_PROMPT = (
    "You are the Narrator agent. Using ONLY the facts and the Analyst's findings in the conversation, write a "
    "clear, neutral explanation of WHY the moment matters. Reply with ONLY a JSON object: "
    '{"headline": "max 12 words", "explanation": "2-4 sentences", "tactical_takeaway": "1 sentence"}. '
    "Do not add numbers or causes that are not in the conversation. Ignore the delivery request."
)
RECAP_NARRATOR_PROMPT = (
    "You are the Narrator agent. Using ONLY the match facts in the conversation, write a recap that tells the "
    "story of the game (control, the shocks, the turning point, the finish). Reply with ONLY a JSON object: "
    '{"headline": "max 12 words", "explanation": "a recap of 5-7 sentences", '
    '"tactical_takeaway": "the single insight that decided the game"}. '
    "Do not add numbers or causes that are not in the facts. Ignore the delivery request."
)
VERIFIER_PROMPT = (
    "You are the Verifier agent, the hallucination guard. Check the Narrator's JSON claim by claim against the "
    "facts (first message) and the Analyst findings. A claim is an issue if a number, name, minute or causal "
    "statement is not supported by them. A claim that something rose, fell, increased, decreased, improved or "
    "dropped is supported only if BOTH the earlier and the later value are in the facts and move in that "
    "direction; a lone value does not show a change. Reply with ONLY a JSON object: "
    '{"verdict": "verified" or "issues", "claims_checked": <integer>, "issues": ["short description of each '
    'unsupported claim, empty if none"]}. Be strict but do not flag harmless paraphrase.'
)
LOCALISER_PROMPT = (
    "You are the Personalisation agent. Take the Narrator's JSON. If the Verifier listed issues, drop or correct "
    "exactly those claims. Then rewrite it for the audience and language requested in the delivery request, "
    "keeping every remaining number and fact unchanged. Reply with ONLY a JSON object: "
    '{"headline": "...", "explanation": "...", "tactical_takeaway": "...", "stat_chips": [{"label": "...", '
    '"value": "..."}]}. If the Analyst produced stat_chips, translate their labels and keep their values; '
    "otherwise return an empty stat_chips list."
)


def _delivery(audience: str, language: str) -> str:
    return f"Delivery request (for the Localiser): audience = {AUDIENCES[audience]}; language = {LANGUAGES[language]}."


async def run_pipeline(match: Match, moment: dict | None, moments: list[dict], audience: str,
                       language: str) -> AsyncIterator[dict]:
    """Yield progress events, then a final {"event": "result", ...}."""
    trace: list[dict] = []
    evidence: list[str] = []
    c = client()
    if moment is not None:
        agents = [Agent(c, ANALYST_PROMPT, name="Analyst", tools=make_tools(match, trace, evidence)),
                  Agent(c, NARRATOR_PROMPT, name="Narrator")]
        task = "Moment facts:\n" + json.dumps(moment["facts"])
    else:
        agents = [Agent(c, RECAP_NARRATOR_PROMPT, name="Narrator")]
        keys = ("minute", "player", "xg", "score_before", "score_after", "win_probability_before",
                "win_probability_after", "against_run_of_play", "sequence", "change", "likely_trigger",
                "during_spell", "rest_of_match_average")
        task = "Match facts:\n" + json.dumps({
            "home": match.home.name, "away": match.away.name, "summary": an.match_summary(match),
            "moments": [{"title": m["title"], "facts": {k: m["facts"][k] for k in keys if k in m["facts"]}}
                        for m in moments]})
    agents += [Agent(c, VERIFIER_PROMPT, name="Verifier"), Agent(c, LOCALISER_PROMPT, name="Localiser")]
    names = [a.name for a in agents]
    yield {"event": "plan", "agents": names}

    workflow = SequentialBuilder(participants=agents, intermediate_output_from="all").build()
    started: dict[str, float] = {}
    texts: dict[str, str] = {}
    async for ev in workflow.run(task + "\n\n" + _delivery(audience, language), stream=True):
        if ev.executor_id not in names:
            continue
        if ev.type == "executor_invoked":
            started[ev.executor_id] = time.perf_counter()
            yield {"event": "start", "agent": ev.executor_id}
        elif ev.type == "executor_completed":
            seconds = round(time.perf_counter() - started[ev.executor_id], 1)
            texts[ev.executor_id] = ev.data[0].agent_response.text  # data[1:] are streaming chunks
            trace.append({"agent": ev.executor_id, "seconds": seconds})
            yield {"event": "done", "agent": ev.executor_id, "seconds": seconds}

    final = parse_json(texts["Localiser"])
    analysis = parse_json(texts["Analyst"]) if "Analyst" in texts else {}
    try:
        verification = parse_json(texts["Verifier"])
    except (ValueError, KeyError):
        verification = {"verdict": "unknown", "claims_checked": 0, "issues": []}
    final.setdefault("stat_chips", [])
    findings = analysis.get("findings", [])
    allowed = allowed_numbers(task, *evidence, *findings)
    narrated = " ".join([final.get("headline", ""), final.get("explanation", ""), final.get("tactical_takeaway", ""),
                         *(str(c.get("value", "")) for c in final["stat_chips"])])
    verification["numeric_check"] = numeric_check(narrated, allowed)
    yield {"event": "result", "result": {
        **final, "findings": findings, "verification": verification, "trace": trace}}


async def explain(match: Match, moment: dict | None, moments: list[dict], audience: str, language: str) -> dict:
    result: dict = {}
    async for ev in run_pipeline(match, moment, moments, audience, language):
        if ev["event"] == "result":
            result = ev["result"]
    return result
