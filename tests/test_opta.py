from pathlib import Path

import pytest

from app import analytics as an
from app import players as pl
from app.adapters import from_opta_f24

FIXTURE = Path(__file__).parent / "fixtures" / "opta_f24_sample.xml"


def load():
    return from_opta_f24(FIXTURE.read_bytes(), "opta-test")


def test_teams_and_event_mapping():
    m = load()
    assert (m.home.name, m.away.name) == ("Alpha FC", "Beta United")
    types = [e.type for e in m.events]
    # own goal, shoot-out goal and the fouled player's foul record are all dropped
    assert types == [
        "pass",
        "pass",
        "tackle",
        "pass",
        "foul",
        "corner",
        "goal",
        "shot",
        "save",
        "red_card",
    ]
    assert (
        m.events[1].outcome == "incomplete"
        and m.events[0].outcome == "complete"
    )
    assert [e.type for e in m.events if e.type == "foul"] and next(
        e for e in m.events if e.type == "foul"
    ).side == "away"


def test_coordinates_scale_and_away_is_mirrored():
    m = load()
    first, away_pass = m.events[0], m.events[3]
    assert (first.x, first.end_x) == (
        63.0,
        94.5,
    )  # 60 and 90 on a 0-100 axis -> metres
    assert (
        away_pass.x == 105 - 21.0
    )  # away events are mirrored to absolute coordinates
    assert away_pass.end_x == 105 - 47.2


def test_corner_goal_and_model_xg():
    m = load()
    corner, goal = next(e for e in m.events if e.type == "corner"), next(
        e for e in m.events if e.type == "goal"
    )
    assert corner.side == "home" and goal.xg and 0 < goal.xg <= 0.65
    assert goal.outcome == "goal"


def test_sequences_are_derived_and_creators_found():
    m = load()
    assert all(e.sequence_id for e in m.events)
    corner = next(e for e in m.events if e.type == "corner")
    goal = next(e for e in m.events if e.type == "goal")
    assert corner.sequence_id == goal.sequence_id
    assert corner.id in pl.chance_creators(m)


def test_analytics_run_on_opta_data():
    m = load()
    assert an.match_summary(m)["score"] == {"home": 1, "away": 0}
    assert [
        x["type"]
        for x in an.detect_moments(m)
        if x["type"] in ("goal", "red_card")
    ] == ["goal", "red_card"]
    assert pl.overview(m)


def test_sparse_feed_does_not_invent_chaos_or_shifts():
    types = {x["type"] for x in an.detect_moments(load())}
    assert "chaotic_spell" not in types and "tactical_shift" not in types
    assert all(w["state"] == "balanced" for w in an.control_windows(load()))


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        from_opta_f24("<Games></Games>")
    with pytest.raises(ValueError):
        from_opta_f24(
            '<Games><Game home_team_id="1" away_team_id="2"></Game></Games>'
        )  # no usable events


def test_xml_with_entities_is_rejected_not_expanded():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        '<Games><Game home_team_id="1" away_team_id="2">&b;</Game></Games>'
    )
    from defusedxml.common import DefusedXmlException

    with pytest.raises(DefusedXmlException):
        from_opta_f24(bomb)
