import copy

from app import analytics as an
from app import chips as ch
from app import main
from app import players as pl
from app.generator import generate_match

MATCH = generate_match(7)
MOMENTS = an.detect_moments(MATCH)
H, A = MATCH.home.short, MATCH.away.short


def moment(kind, nth=0):
    return [m for m in MOMENTS if m["type"] == kind][nth]


def test_recap_cards_name_both_teams_and_show_both_sides():
    cards = ch.build_chips(MATCH, None, None, "en")
    assert [c["label"] for c in cards] == ["Possession", "Shots", "xG"]
    s = an.match_summary(MATCH)
    assert (
        cards[0]["value"]
        == f"{s['possession_pct']['home']}% – {s['possession_pct']['away']}%"
    )
    assert cards[1]["value"] == f"{s['shots']['home']} – {s['shots']['away']}"
    assert all(
        c["detail"] == f"{H} – {A}" for c in cards
    )  # the old graphic said "63% Possession": whose?


def test_every_card_has_a_language_neutral_key():
    for lang in ch.LABELS:
        keys = [c["key"] for c in ch.build_chips(MATCH, None, None, lang)]
        assert keys == ["possession", "shots", "xg"], lang
    for m in MOMENTS:
        assert all(c["key"] for c in ch.build_chips(MATCH, m, None, "pt")), m[
            "title"
        ]


def test_every_moment_type_gives_three_complete_cards():
    for m in MOMENTS:
        cards = ch.build_chips(MATCH, m, None, "en")
        assert len(cards) == 3, m["title"]
        assert all(c["label"] and c["value"] and c["detail"] for c in cards), m[
            "title"
        ]


def test_goal_cards_use_the_scoring_side_probability_and_the_goal_xg():
    g = moment("goal", 1)  # the home equaliser
    f = g["facts"]
    cards = ch.build_chips(MATCH, g, None, "en")
    assert (
        cards[0]["value"] == f"{f['xg']:.2f}"
        and cards[0]["detail"] == f["player"]
    )
    assert cards[1]["value"] == f"{f['shot_speed_kmh']:.0f} km/h"
    b, a = (
        f["win_probability_before"]["home"],
        f["win_probability_after"]["home"],
    )
    assert (
        cards[2]["value"] == f"{round(b * 100)}% → {round(a * 100)}%"
        and cards[2]["detail"] == H
    )


def test_red_card_cards_show_both_teams_win_probability():
    r = moment("red_card")
    cards = ch.build_chips(MATCH, r, None, "en")
    assert (
        [c["detail"] for c in cards[:2]] == [H, A]
        and "→" in cards[0]["value"]
        and "→" in cards[1]["value"]
    )
    assert (
        cards[2]["label"] == "Red cards"
        and cards[2]["detail"] == A
        and cards[2]["value"] == "1"
    )


def test_shift_and_chaos_cards_show_before_to_after():
    shift = ch.build_chips(MATCH, moment("tactical_shift", 1), None, "en")
    assert [c["label"] for c in shift] == [
        "Territory",
        "Press height",
        "Possession",
    ]
    assert all("→" in c["value"] for c in shift) and shift[1]["value"].endswith(
        " m"
    )
    chaos = ch.build_chips(MATCH, moment("chaotic_spell"), None, "en")
    assert all("→" in c["value"] and c["detail"] == f"{H} + {A}" for c in chaos)


def test_outfield_cards_match_the_player_statistics():
    top = next(
        s
        for s in pl.overview(MATCH)
        if s["position"] != "GK" and s["goals"] == 0 and s["ball_wins"] >= 3
    )
    cards = ch.build_chips(MATCH, None, pl.player_facts(MATCH, top["id"]), "en")
    short = MATCH.team(top["side"]).short
    assert [c["label"] for c in cards] == [
        "Chances created",
        "Progressive passes",
        "Ball wins",
    ]
    assert cards[0]["value"] == str(top["chances_created"]) and cards[0][
        "detail"
    ].startswith(short)
    assert cards[1]["value"] == str(top["progressive_passes"])
    assert cards[2]["value"] == str(top["ball_wins"])


def test_a_scorer_gets_a_goals_card_with_his_xg():
    scorer = next(s for s in pl.overview(MATCH) if s["goals"] > 0)
    cards = ch.build_chips(
        MATCH, None, pl.player_facts(MATCH, scorer["id"]), "en"
    )
    assert cards[2]["label"] == "Goals" and cards[2]["value"] == str(
        scorer["goals"]
    )
    assert cards[2]["detail"] == f"xG {scorer['xg']:.2f}"


def test_a_goalkeeper_is_described_by_saves_not_by_zero_goals_and_passes():
    keeper = next(
        s
        for s in pl.overview(MATCH)
        if s["position"] == "GK" and s["saves"] > 0
    )
    cards = ch.build_chips(
        MATCH, None, pl.player_facts(MATCH, keeper["id"]), "en"
    )
    assert [c["label"] for c in cards] == ["Saves", "Impact"]
    assert cards[0]["value"] == str(keeper["saves"])
    assert cards[1]["value"] == f"{keeper['impact']:.1f}" and cards[1][
        "detail"
    ].startswith("#")
    assert "0" not in [c["value"] for c in cards]  # no filler zeros


def test_only_labels_are_translated_never_the_numbers():
    en, pt = ch.build_chips(MATCH, None, None, "en"), ch.build_chips(
        MATCH, None, None, "pt"
    )
    assert [c["label"] for c in pt] == ["Posse", "Remates", "xG"]
    assert [c["value"] for c in en] == [c["value"] for c in pt]
    for lang, table in ch.LABELS.items():
        assert (
            table.keys() == ch.LABELS["en"].keys()
        ), lang  # no language is missing a label


def test_missing_shot_speed_falls_back_to_possession_instead_of_a_blank():
    g = copy.deepcopy(moment("goal", 1))
    g["facts"]["shot_speed_kmh"] = None
    cards = ch.build_chips(MATCH, g, None, "en")
    assert cards[1]["label"] == "Possession (prev. 10')" and cards[1][
        "value"
    ].endswith("%")


def test_unusual_facts_give_no_cards_rather_than_a_wrong_figure():
    broken = copy.deepcopy(moment("goal"))
    del (
        broken["facts"]["win_probability_after"]["home"],
        broken["facts"]["win_probability_after"]["away"],
    )
    assert ch.build_chips(MATCH, broken, None, "en") == []


def test_payload_carries_each_moments_cards_without_mutating_moments():
    match = main.MATCHES[main.demo.DEMO_MATCH_ID]
    before = [dict(m) for m in main.MOMENTS[match.id]]
    data = main.payload(match)
    assert len(data["moments"]) == len(main.MOMENTS[match.id])
    for sent, stored in zip(data["moments"], main.MOMENTS[match.id]):
        assert (
            len(sent["chips"]) == 3 and "chips" not in stored
        )  # the stored moment is not mutated
        assert sent["chips"] == ch.build_chips(match, stored, None, "en")
    assert main.MOMENTS[match.id] == before


def test_finalize_replaces_model_chosen_cards_and_keeps_the_text():
    model_result = {
        "headline": "h",
        "explanation": "e",
        "stat_chips": [{"label": "Possession", "value": "63%"}],
        "graphic": {
            "title": "t",
            "line": "l",
            "chips": [{"label": "Shots", "value": "24"}],
        },
    }
    out = main.finalize(model_result, MATCH, None, None, "pt", cached=True)
    assert (
        out["graphic"]["title"] == "t"
        and out["headline"] == "h"
        and out["cached"] is True
    )
    assert (
        out["graphic"]["chips"] == out["stat_chips"]
        and out["stat_chips"][0]["label"] == "Posse"
    )
    assert out["stat_chips"][0]["detail"] == f"{H} – {A}"
    assert model_result["graphic"]["chips"] == [
        {"label": "Shots", "value": "24"}
    ]  # the input is not mutated


def test_finalize_uses_the_language_that_is_actually_shown_on_fallback():
    r = {
        "headline": "h",
        "graphic": None,
        "fallback": {"shown": {"audience": "coach", "language": "en"}},
    }
    assert (
        main.finalize(r, MATCH, None, None, "pt")["stat_chips"][0]["label"]
        == "Possession"
    )
