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


TEAMS = [("Northbridge FC", "Northbridge"), ("Eastport United", "Eastport")]


def test_a_chaotic_spell_text_naming_only_one_team_is_flagged():
    from app.grounding import framing_issues
    one_sided = "Entre os minutos 35 e 45, o Northbridge FC assumiu maior controlo e pressionou intensamente."
    assert framing_issues("chaotic_spell", one_sided, TEAMS) == [
        "A chaotic spell concerns both teams, but the text names only one of them."]


def test_naming_both_teams_or_neither_is_fine_and_other_events_are_not_checked():
    from app.grounding import framing_issues
    assert framing_issues("chaotic_spell", "Northbridge FC and Eastport United lost control.", TEAMS) == []
    assert framing_issues("chaotic_spell", "Possession and turnovers spike for both teams.", TEAMS) == []
    assert framing_issues("goal", "Northbridge FC score.", TEAMS) == []  # a goal belongs to one team
    assert framing_issues(None, "Northbridge FC dominate the match.", TEAMS) == []  # nor does a recap


def test_each_field_is_checked_on_its_own_so_a_long_explanation_cannot_hide_a_one_sided_title():
    from app.agents import wording_issues
    final = {"headline": "Chaos erupts as Northbridge FC storms back in the possession battle",
             "explanation": "Northbridge FC and Eastport United both lost control of the ball for ten minutes.",
             "graphic": {"title": "Chaotic spell shakes the match",
                         "line": "From minute 35 to 45, Northbridge FC increased possession drastically."}}
    issues = wording_issues(final, "chaotic_spell", TEAMS)
    assert [i.split(":")[0] for i in issues] == ["headline", "graphic line"]
    fixed = {**final, "headline": "Both teams lose control in a chaotic ten minutes",
             "graphic": {"title": "Chaos on the pitch", "line": "Possession changes hands twice as often."}}
    assert wording_issues(fixed, "chaotic_spell", TEAMS) == []
    assert wording_issues(final, "goal", TEAMS) == []


def test_small_integers_are_ignored():
    assert numeric_check("The first of two goals came in the last 10 minutes.", [])["checked"] == 0
