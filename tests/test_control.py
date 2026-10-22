from app import analytics as an
from app.generator import generate_match

MATCH = generate_match(7)


def test_control_windows_cover_match_and_use_all_states():
    wins = an.control_windows(MATCH)
    assert wins[0]["start"] == 0 and wins[-1]["end"] == 93
    states = {w["state"] for w in wins}
    assert {"home_control", "chaotic"} <= states


def test_scrappy_spell_is_detected_as_chaotic():
    spells = an.chaotic_spells(MATCH)
    assert len(spells) == 1
    f = spells[0]["facts"]
    assert f["spell_minutes"] == "35-45"
    assert f["during_spell"]["sequences_per_min"] > 1.5 * f["rest_of_match_average"]["sequences_per_min"]
    assert f["during_spell"]["avg_passes_per_sequence"] < f["rest_of_match_average"]["avg_passes_per_sequence"]


def test_red_card_press_shift_is_found_and_trigger_precedes_it():
    shifts = {s["minute"]: s for s in an.tactical_shifts(MATCH)}
    press = [s for s in shifts.values() if "press higher" in s["title"]]
    assert press, "expected a press-higher shift after the red card"
    assert press[0]["facts"]["likely_trigger"]["event"] == "red_card"
    for s in shifts.values():  # a cause must never come after its effect
        trig = s["facts"]["likely_trigger"]
        if trig:
            m, sec = trig["minute"].split("'")
            assert int(m) + int(sec) / 60 <= s["minute"]


def test_moment_ids_follow_chronological_order():
    moments = an.detect_moments(MATCH)
    times = [(m["minute"], m["second"]) for m in moments]
    assert times == sorted(times)
    assert [m["id"] for m in moments] == [f"m{i}" for i in range(1, len(moments) + 1)]
