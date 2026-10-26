import asyncio

from app import agents
from app.agents import result_problems
from app.agents import revision_request


def res(headline="h", issues=(), untraced=(), graphic=True, trace=None):
    return {
        "headline": headline,
        "graphic": {"title": "t", "line": "l"} if graphic else None,
        "verification": {
            "verdict": "verified",
            "claims_checked": 3,
            "issues": list(issues),
            "numeric_check": {"checked": 5, "unverified": list(untraced)},
        },
        "trace": (
            trace
            if trace is not None
            else [{"agent": "Narrator", "seconds": 1.0}]
        ),
    }


def stub(monkeypatch, outcomes):
    """Replace one workflow pass: each call yields progress events and then the
    next outcome (or raises it)."""
    calls = []

    async def fake(
        match, moment, moments, audience, language, player=None, feedback=None
    ):
        calls.append(feedback)
        yield {"event": "plan", "agents": ["Narrator"]}
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        yield {"event": "result", "result": outcome}

    monkeypatch.setattr(agents, "_run_once", fake)
    return calls


def run(audience="coach", revise=True):
    async def collect():
        return [
            ev
            async for ev in agents.run_pipeline(
                None, None, [], audience, "en", None, revise
            )
        ]

    return asyncio.run(collect())


def kinds(events):
    return [e["event"] for e in events]


def test_a_clean_first_draft_is_returned_untouched_with_one_pass(monkeypatch):
    calls = stub(monkeypatch, [res("fine")])
    events = run()
    assert len(calls) == 1 and "revise" not in kinds(events)
    assert (
        events[-1]["result"]["headline"] == "fine"
        and "revision" not in events[-1]["result"]
    )


def test_a_flagged_draft_is_revised_once_with_the_reasons_and_the_fix_is_kept(
    monkeypatch,
):
    calls = stub(
        monkeypatch,
        [res("bad", issues=["headline: names only one team"]), res("good")],
    )
    events = run()
    assert (
        len(calls) == 2
        and calls[0] is None
        and calls[1]
        and "names only one team" in calls[1][0]
    )
    assert kinds(events).count("plan") == 2 and "revise" in kinds(
        events
    )  # the UI sees the second pass
    final = events[-1]["result"]
    assert final["headline"] == "good"
    assert (
        final["revision"]["fixed"] is True
        and final["revision"]["kept"] == "revised"
    )
    assert any(
        t.get("note") for t in final["trace"]
    )  # the trace says a revision happened


def test_only_one_revision_even_if_the_second_draft_is_still_flagged(
    monkeypatch,
):
    calls = stub(
        monkeypatch,
        [
            res("a", issues=["x"]),
            res("b", issues=["y"]),
            res("never", issues=["z"]),
        ],
    )
    events = run()
    assert len(calls) == 2  # never a third pass
    assert events[-1]["result"]["revision"]["fixed"] is False


def test_a_revision_that_makes_things_worse_is_discarded(monkeypatch):
    stub(
        monkeypatch,
        [
            res("first", issues=["x"]),
            res("second", issues=["x", "y"], untraced=["99"]),
        ],
    )
    final = run()[-1]["result"]
    assert (
        final["headline"] == "first"
        and final["revision"]["kept"] == "first"
        and final["revision"]["fixed"] is False
    )


def test_a_failing_revision_never_costs_the_first_draft(monkeypatch):
    stub(
        monkeypatch,
        [res("first", issues=["x"]), RuntimeError("rate limit exceeded")],
    )
    final = run()[-1]["result"]
    assert final["headline"] == "first" and final["revision"]["kept"] == "first"
    assert "rate limit" in final["revision"]["error"]


def test_revision_can_be_switched_off(monkeypatch):
    calls = stub(monkeypatch, [res("a", issues=["x"]), res("b")])
    events = run(revise=False)
    assert (
        len(calls) == 1
        and events[-1]["result"]["headline"] == "a"
        and "revise" not in kinds(events)
    )


def test_malformed_json_from_the_model_gets_one_more_attempt_not_an_error(
    monkeypatch,
):
    calls = stub(
        monkeypatch,
        [
            ValueError("Expecting ':' delimiter: line 1 column 2138"),
            res("recovered"),
        ],
    )
    events = run()
    assert len(calls) == 2 and "retry" in kinds(events)
    assert events[-1]["result"]["headline"] == "recovered"


def test_malformed_json_twice_is_still_an_error(monkeypatch):
    import pytest

    calls = stub(
        monkeypatch, [ValueError("bad json"), ValueError("bad json again")]
    )
    with pytest.raises(ValueError):
        run()
    assert len(calls) == 2  # one retry, not a loop


def test_only_a_chaotic_spell_gets_a_two_team_headline_example():
    from app import analytics as an
    from app.agents import moment_guidance
    from app.generator import generate_match

    match = generate_match(7)
    moments = an.detect_moments(match)
    spell = next(m for m in moments if m["type"] == "chaotic_spell")
    text = moment_guidance(match, spell)
    assert (
        match.home.name in text
        and match.away.name in text
        and "between minutes 35 and 45" in text
    )
    assert all(
        moment_guidance(match, m) == ""
        for m in moments
        if m["type"] != "chaotic_spell"
    )
    assert moment_guidance(match, None) == ""


def test_guidance_changes_neither_facts_nor_fingerprint():
    from app import analytics as an
    from app import demo
    from app.generator import generate_match

    match = generate_match(7)
    before = demo.fingerprint(match, an.detect_moments(match))
    from app.agents import moment_guidance

    moment_guidance(match, an.detect_moments(match)[0])
    assert demo.fingerprint(match, an.detect_moments(match)) == before


def test_lines_that_only_say_there_is_no_issue_are_not_issues():
    from app.agents import real_issues

    issues = [
        "Claim 'both teams turned the ball over more' is supported by "
        "turnovers "
        "2.3 to 4.5. No issue here.",
        "The graphic line is vague but aligns with data; no strict issue here.",
        "Claim about possession matches the facts. No issue.",
        "The claim that Eastport nearly doubled their shots is not supported: "
        "shots went from 1 to 3.",
    ]
    assert real_issues(issues) == [issues[3]]
    assert real_issues(None) == [] and real_issues([]) == []
    assert (
        real_issues(
            ["No issue was found with the xG, but the minute is wrong."]
        )
        != []
    )  # a real flag that mentions it


def test_what_counts_as_a_problem():
    assert result_problems(res(), "coach") == []
    assert result_problems(res(issues=["wrong"]), "coach") == [
        "The checks flagged: wrong"
    ]
    assert "90" in result_problems(res(untraced=["90"]), "coach")[0]
    assert (
        result_problems(res(graphic=False), "coach") == []
    )  # a graphic is only required for broadcasters
    assert "graphic" in result_problems(res(graphic=False), "broadcaster")[0]


def test_revision_request_lists_every_problem_and_the_format():
    text = revision_request(["The checks flagged: a", "The checks flagged: b"])
    assert (
        "- The checks flagged: a" in text and "- The checks flagged: b" in text
    )
    assert "same JSON format" in text and "only figures from the facts" in text
