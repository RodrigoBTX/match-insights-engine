import json
from pathlib import Path

from app import analytics as an
from app.adapters import from_statsbomb
from app.generator import generate_match

FIXTURE = Path(__file__).parent / "fixtures" / "statsbomb_sample.json"


def load():
    return from_statsbomb(json.loads(FIXTURE.read_text(encoding="utf-8")), "test")


def test_teams_and_event_mapping():
    m = load()
    assert (m.home.name, m.away.name) == ("Alpha FC", "Beta United")
    assert [e.type for e in m.events] == ["pass", "pass", "pass", "goal", "shot", "red_card"]
    assert m.events[1].outcome == "incomplete"


def test_coordinates_follow_attacking_direction():
    m = load()
    home_pass, away_pass = m.events[0], m.events[2]
    assert home_pass.x == 52.5 and home_pass.end_x == 78.8          # 60/120*105, 90/120*105
    assert away_pass.x == 105 - 17.5                                 # away is mirrored to absolute coords
    goal = m.events[3]
    assert goal.xg == 0.31 and goal.outcome == "goal"


def test_analytics_run_on_adapted_data():
    m = load()
    assert an.match_summary(m)["score"] == {"home": 1, "away": 0}
    moments = an.detect_moments(m)
    assert [x["type"] for x in moments if x["type"] in ("goal", "red_card")] == ["goal", "red_card"]


def test_synthetic_story_is_stable():
    m = generate_match(7)
    s = an.match_summary(m)
    assert s["score"] == {"home": 2, "away": 1}
    assert [x["type"] for x in an.detect_moments(m)].count("goal") == 3
