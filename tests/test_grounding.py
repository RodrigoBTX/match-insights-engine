import json

from app import analytics as an
from app.generator import generate_match
from app.grounding import allowed_numbers, numeric_check


def moment_facts():
    m = generate_match(7)
    goal = next(x for x in an.detect_moments(m) if x["type"] == "goal")
    return json.dumps(goal["facts"])


def test_correct_text_passes():
    allowed = allowed_numbers(moment_facts())
    text = ("At 27'17 Eastport scored (xG 0.42, shot 96 km/h). Win probability rose from 34,4% to 65.6%. "
            "The move covered 62 metres.")
    assert numeric_check(text, allowed)["unverified"] == []


def test_planted_numbers_are_flagged():
    allowed = allowed_numbers(moment_facts())
    text = "Eastport scored after 31 passes with xG 0.85 and win probability 91.0%."
    res = numeric_check(text, allowed)
    assert {"0.85", "91.0"} <= set(res["unverified"])


def test_small_integers_are_ignored():
    assert numeric_check("The first of two goals came in the last 10 minutes.", [])["checked"] == 0
