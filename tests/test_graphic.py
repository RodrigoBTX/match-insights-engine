from app.agents import GRAPHIC_RULE, narrated_text, normalize_graphic
from app.grounding import allowed_numbers, numeric_check

GOOD = {"title": "Penn levels it", "line": "Oskar Penn heads home on 63 minutes to make it 1-1.",
        "chips": [{"label": "xG", "value": "0.14"}, {"label": "Minute", "value": "63'"}, {"label": "Score", "value": "1-1"}]}


def test_valid_graphic_is_kept_and_capped_at_three_chips():
    g = normalize_graphic({**GOOD, "chips": GOOD["chips"] + [{"label": "Extra", "value": "9"}]})
    assert g["title"] == "Penn levels it" and len(g["chips"]) == 3


def test_malformed_graphic_is_dropped_not_repaired():
    assert normalize_graphic(None) is None
    assert normalize_graphic("text") is None
    assert normalize_graphic({"title": "", "line": "x"}) is None
    assert normalize_graphic({"title": "T", "line": "L", "chips": "nope"})["chips"] == []
    assert normalize_graphic({"title": "T", "line": "L", "chips": [{"label": "", "value": "1"}]})["chips"] == []


def test_numeric_guard_sees_the_graphic_text():
    final = {"headline": "h", "explanation": "e", "tactical_takeaway": "t", "stat_chips": [], "graphic": GOOD}
    assert "0.14" in narrated_text(final)
    allowed = allowed_numbers("xG 0.14 minute 63'24 score 1-1")
    assert numeric_check(narrated_text(final), allowed)["unverified"] == []
    bad = {**final, "graphic": {**GOOD, "chips": [{"label": "xG", "value": "0.91"}] * 3}}
    assert "0.91" in numeric_check(narrated_text(bad), allowed)["unverified"]


def test_rule_asks_for_exactly_three_chips_and_only_known_figures():
    assert "exactly 3 chips" in GRAPHIC_RULE and "only figures that appear in the conversation" in GRAPHIC_RULE
