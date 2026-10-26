from app import demo
from app.main import MATCHES, MOMENTS
from scripts import quality_report as q

MATCH, MOMENTS_7 = MATCHES[demo.DEMO_MATCH_ID], MOMENTS[demo.DEMO_MATCH_ID]


def test_the_set_covers_every_moment_in_three_audiences_plus_portuguese_graphics_recaps_and_players():
    targets = q.build_targets(MATCH, MOMENTS_7)
    moments = len(MOMENTS_7)
    assert len(targets) == moments * 4 + 3 + 6
    assert sum(1 for t in targets if t["language"] == "pt") == moments  # broadcaster graphics in Portuguese
    assert sum(1 for t in targets if t["player"]) == 6


def test_the_goal_role_check_catches_the_known_failure_and_accepts_correct_wording():
    equaliser = next(m for m in MOMENTS_7 if m["type"] == "goal" and "equaliser" in m["facts"]["goal_role"])
    wrong = {"headline": "Penn scores the match-winning goal", "graphic": {"title": "Winner", "line": "x"}}
    right = {"headline": "Penn's equaliser levels it", "graphic": {"title": "Equaliser", "line": "x"}}
    assert q.role_mismatches(wrong, equaliser, "en") != []
    assert q.role_mismatches(right, equaliser, "en") == []
    assert q.role_mismatches(wrong, equaliser, "pt") == []  # English only, stated in the report
    assert q.role_mismatches(wrong, None, "en") == []


def record(label="a", reasons=(), revised=False, kept=None, first=()):
    return {"label": label, "kind": "goal", "audience": "coach", "language": "en", "seconds": 10.0, "retries": 0,
            "reasons": list(reasons), "claims": 5, "agent_seconds": {"Analyst": 8.0}, "text": "",
            "revised": revised, "revision_kept": kept, "revision_error": None, "first_problems": list(first),
            "raw_clean": not revised and not reasons}


def test_report_separates_the_first_draft_from_the_revised_result_and_never_claims_more_than_it_measured():
    cases = [record("clean"),
             record("fixed", revised=True, kept="revised", first=["headline: names only one team"]),
             record("still bad", reasons=["untraced figures: ['99']"], revised=True, kept="first", first=["x"]),
             record("bad no revision", reasons=["goal role: wrong"])]
    text = q.write_report(cases, "model-x")
    assert "first draft** (nothing flagged, no revision needed): **25% (1/4)**" in text
    assert "after the automatic revision**, which is what the user sees: **50% (2/4)**" in text
    assert "Revisions triggered: 2; the revised draft was kept in 1, the first draft in 1" in text
    assert "does not mean the writing is good" in text and "ran **once**" in text
    assert "## Revised cases" in text and "**fixed** (fixed; kept the revised draft)" in text
    assert "names only one team" in text  # what was flagged is shown, not just counted
    assert "| untraced figures | 1 |" in text and "| goal role | 1 |" in text


def test_a_different_seed_is_labelled_as_a_held_out_measurement():
    own = q.write_report([record()], "m", seed=7)
    other = q.write_report([record()], "m", seed=11)
    assert "Held-out" not in own and "used while tuning" in own
    assert "Held-out measurement" in other and "seed 11" in other and "partly independent" in other