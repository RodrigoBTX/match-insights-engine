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


def test_report_counts_failures_and_never_claims_more_than_it_measured():
    ok = {"label": "a", "kind": "goal", "audience": "coach", "language": "en", "seconds": 10.0, "retries": 0,
          "reasons": [], "claims": 5, "agent_seconds": {"Analyst": 8.0}}
    bad = {**ok, "label": "b", "reasons": ["untraced figures: ['99']", "wording: one-sided"]}
    text = q.write_report([ok, bad], "model-x")
    assert "Clean on the first try: **50% (1/2)**" in text
    assert "does not mean the writing is good" in text and "ran **once**" in text
    assert "| untraced figures | 1 |" in text and "| wording | 1 |" in text
