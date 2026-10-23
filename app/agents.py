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
from . import players as pl
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
        # `az` is a slow subprocess on Windows; the default 10 s limit failed once on a cold first call
        _client = FoundryChatClient(credential=AzureCliCredential(process_timeout=40))
    return _client


def reset_client() -> None:
    global _client
    _client = None


def warm_up() -> bool:
    """Start `az` once at server start so the first request does not pay the cold start.

    Returns whether a token could be obtained, which is how the app knows if live agents can run here.
    """
    try:
        AzureCliCredential(process_timeout=40).get_token("https://cognitiveservices.azure.com/.default")
        return True
    except Exception:  # best effort: a failure here must not stop the server
        return False


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


def make_player_tools(match: Match, trace: list[dict], evidence: list[str]):
    stats = {s["id"]: s for s in pl.overview(match)}

    def reply(tool_name: str, args: dict, payload: dict) -> str:
        trace.append({"agent": "Analyst", "tool": tool_name, "args": args})
        out = json.dumps(payload)
        evidence.append(out)
        return out

    @tool(name="player_stats", description="Full statistics and impact score of one player by id: passes, "
          "progressive passes, average pass quality (0-1), chances created, shots, xG, goals, top shot speed, "
          "tackles, interceptions, saves, cards, and overall/in-team rank.")
    def player_stats(player_id: int) -> str:
        return reply("player_stats", {"player_id": player_id}, stats.get(player_id, {"error": "unknown player"}))

    @tool(name="top_players", description="The n highest-impact players of a side ('home' or 'away'), "
          "with their key numbers, to compare a player with teammates or opponents.")
    def top_players(side: str, n: int = 3) -> str:
        top = [s for s in stats.values() if s["side"] == side][:max(1, min(n, 5))]
        keep = ("id", "name", "position", "goals", "xg", "chances_created", "progressive_passes", "impact", "rank_in_team")
        return reply("top_players", {"side": side, "n": n}, {"players": [{k: s[k] for k in keep} for s in top]})

    return [player_stats, top_players]


GRAPHIC_RULE = (
    " The audience is a broadcaster, so ALSO include a key \"graphic\" for an on-screen lower third: "
    '{"title": "max 6 words", "line": "one on-air sentence of max 20 words", "chips": [{"label": "max 3 words", '
    '"value": "a short figure"}]} with exactly 3 chips. Use only figures that appear in the conversation. The '
    'title must state the news itself (who did what), never a generic label such as "Key Match Stats", "Moment '
    'That Mattered" or "Match Summary".'
)

LOCALISER_GRAPHIC = (
    ' Your JSON MUST also contain the key "graphic": {"title": "...", "line": "...", "chips": [{"label": "...", '
    '"value": "..."}]}, copied from the "graphic" object in the Narrator JSON and translated, with exactly the same '
    "figures and the same number of chips. Never omit it."
)

GOAL_RULE = (
    "Say what a goal meant only from its goal_role (or goals[].role): never call a goal the winner, the "
    "equaliser or the opener because of the final score or the number of goals a player scored. "
)

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
    "against the run of play, and what changed tactically. " + GOAL_RULE +
    "For event 'tactical_shift' explain the swing using "
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
PLAYER_ANALYST_PROMPT = (
    "You are the Player Spotlight analyst. The conversation starts with verified facts about one player. Use "
    "your tools to compare the player with teammates (top_players for their side) and with the opposition "
    "(top_players for the other side). Then reply with ONLY a JSON object: "
    '{"findings": ["3 to 5 short, factual findings"], "stat_chips": [{"label": "...", "value": "..."}]} '
    "with at most 5 stat_chips. Copy numbers exactly from the facts or tool results; never invent numbers. "
    + NAMING +
    "Do not do arithmetic: use ready-made fields such as ball_wins and share_of_team_pct instead of adding or "
    "dividing numbers yourself. " + GOAL_RULE +
    "Cover what the player did (creating chances, progressing the ball, finishing, winning the ball), how "
    "they rank in their team and in the match, and how much of the team's output they account for. Impact is "
    "a formula-based score (impact_formula in the facts), not a rating from a human; say so if you cite it. "
    "Ignore the delivery request; it is for the Localiser."
)
PLAYER_NARRATOR_PROMPT = (
    "You are the Narrator agent writing a player spotlight. Using ONLY the facts and the Analyst's findings in "
    "the conversation, explain HOW this player influenced the match and what kind of player the numbers show. "
    "Reply with ONLY a JSON object: "
    '{"headline": "max 12 words", "explanation": "2-4 sentences", "tactical_takeaway": "1 sentence on how '
    'the team used or could use this player"}. Do not add numbers or claims that are not in the conversation. '
    "A rank or a comparison (more than, fewer than) needs both values in the conversation. " + GOAL_RULE +
    "Ignore the delivery request."
)
VERIFIER_PROMPT = (
    "You are the Verifier agent, the hallucination guard. Check the Narrator's JSON claim by claim against the "
    "facts (first message) and the Analyst findings. A claim is an issue if a number, name, minute or causal "
    "statement is not supported by them. A claim that something rose, fell, increased, decreased, improved or "
    "dropped is supported only if BOTH the earlier and the later value are in the facts and move in that "
    "direction; a lone value does not show a change. Describing a goal as the opener, the equaliser, "
    "go-ahead or match-winning is supported only if it matches goal_role or goals[].role in the facts; if the "
    "text gives a goal a role that differs from it, that is an issue. If the Narrator JSON has a \"graphic\" "
    "object, check its title, line and chip values exactly like the rest. Reply with ONLY a JSON object: "
    '{"verdict": "verified" or "issues", "claims_checked": <integer>, "issues": ["short description of each '
    'unsupported claim, empty if none"]}. Be strict but do not flag harmless paraphrase.'
)
LOCALISER_PROMPT = (
    "You are the Personalisation agent. Take the Narrator's JSON. If the Verifier listed issues, drop or correct "
    "exactly those claims. Then rewrite it for the audience and language requested in the delivery request, "
    "keeping every remaining number and fact unchanged. Reply with ONLY a JSON object: "
    '{"headline": "...", "explanation": "...", "tactical_takeaway": "...", "stat_chips": [{"label": "...", '
    '"value": "..."}]}. If the Analyst produced stat_chips, translate their labels and keep their values; '
    "otherwise return an empty stat_chips list. If the Narrator JSON has a \"graphic\" object, include it too, "
    "translated, with the same keys and unchanged figures (title, line, chips[].label, chips[].value)."
)


def normalize_graphic(raw) -> dict | None:
    """Validate the lower-third graphic an agent returned; anything malformed is dropped, not guessed."""
    if not isinstance(raw, dict):
        return None
    title, line, chips = raw.get("title"), raw.get("line"), raw.get("chips")
    if not (isinstance(title, str) and title.strip() and isinstance(line, str) and line.strip()):
        return None
    clean = [{"label": str(c.get("label", "")).strip(), "value": str(c.get("value", "")).strip()}
             for c in (chips if isinstance(chips, list) else []) if isinstance(c, dict)]
    return {"title": title.strip(), "line": line.strip(), "chips": [c for c in clean if c["label"] and c["value"]][:3]}


def narrated_text(final: dict) -> str:
    """Every piece of text shown to the user, so the numeric guard sees all of it (graphic included)."""
    graphic = final.get("graphic") or {}
    return " ".join([
        final.get("headline", ""), final.get("explanation", ""), final.get("tactical_takeaway", ""),
        *(str(c.get("value", "")) for c in final.get("stat_chips", [])),
        graphic.get("title", ""), graphic.get("line", ""),
        *(f"{c.get('label', '')} {c.get('value', '')}" for c in graphic.get("chips", [])),
    ])


def _delivery(audience: str, language: str) -> str:
    return f"Delivery request (for the Localiser): audience = {AUDIENCES[audience]}; language = {LANGUAGES[language]}."


async def run_pipeline(match: Match, moment: dict | None, moments: list[dict], audience: str,
                       language: str, player: dict | None = None) -> AsyncIterator[dict]:
    """Yield progress events, then a final {"event": "result", ...}."""
    trace: list[dict] = []
    evidence: list[str] = []
    c = client()
    extra = GRAPHIC_RULE if audience == "broadcaster" else ""  # the Narrator writes the graphic so the Verifier checks it
    if player is not None:
        agents = [Agent(c, PLAYER_ANALYST_PROMPT, name="Analyst", tools=make_player_tools(match, trace, evidence)),
                  Agent(c, PLAYER_NARRATOR_PROMPT + extra, name="Narrator")]
        task = "Player facts:\n" + json.dumps(player)
    elif moment is not None:
        agents = [Agent(c, ANALYST_PROMPT, name="Analyst", tools=make_tools(match, trace, evidence)),
                  Agent(c, NARRATOR_PROMPT + extra, name="Narrator")]
        task = "Moment facts:\n" + json.dumps(moment["facts"])
    else:
        agents = [Agent(c, RECAP_NARRATOR_PROMPT + extra, name="Narrator")]
        keys = ("minute", "player", "xg", "score_before", "score_after", "win_probability_before",
                "win_probability_after", "against_run_of_play", "sequence", "change", "likely_trigger",
                "during_spell", "rest_of_match_average")
        task = "Match facts:\n" + json.dumps({
            "home": match.home.name, "away": match.away.name, "summary": an.match_summary(match),
            "moments": [{"title": m["title"], "facts": {k: m["facts"][k] for k in keys if k in m["facts"]}}
                        for m in moments]})
    localiser_prompt = LOCALISER_PROMPT + (LOCALISER_GRAPHIC if audience == "broadcaster" else "")
    agents += [Agent(c, VERIFIER_PROMPT, name="Verifier"), Agent(c, localiser_prompt, name="Localiser")]
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
    graphic = None
    if audience == "broadcaster":
        graphic = normalize_graphic(final.get("graphic"))
        if graphic is None and language == "en":
            # the Localiser left it out: the Narrator's English graphic is already the final text in English.
            # For other languages there is no safe fallback (it would be untranslated), so it stays None.
            try:
                graphic = normalize_graphic(parse_json(texts["Narrator"]).get("graphic"))
            except (ValueError, KeyError):
                graphic = None
    final["graphic"] = graphic
    findings = analysis.get("findings", [])
    allowed = allowed_numbers(task, *evidence, *findings)
    verification["numeric_check"] = numeric_check(narrated_text(final), allowed)
    yield {"event": "result", "result": {
        **final, "findings": findings, "verification": verification, "trace": trace}}


async def explain(match: Match, moment: dict | None, moments: list[dict], audience: str, language: str,
                  player: dict | None = None) -> dict:
    result: dict = {}
    async for ev in run_pipeline(match, moment, moments, audience, language, player):
        if ev["event"] == "result":
            result = ev["result"]
    return result
