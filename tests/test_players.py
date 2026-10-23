from app import players as pl
from app.generator import HOME, AWAY, generate_match
from app.schema import Event, Match, Player

MATCH = generate_match(7)


def tiny_match(events: list[Event]) -> Match:
    people = [Player(id=1, name="Ana", number=8, position="CM", side="home"),
              Player(id=2, name="Bea", number=9, position="ST", side="home")]
    return Match(id="t", home=HOME, away=AWAY, players=people, events=events)


def ev(i, t, etype, pid, **kw):
    base = dict(id=i, minute=t, side="home", player_id=pid, type=etype, x=50.0, y=34.0, sequence_id=1)
    return Event(**{**base, **kw})


def test_progressive_pass_needs_ten_metres_towards_goal():
    near = ev(1, 1, "pass", 1, x=40.0, end_x=48.0, outcome="complete")
    far = ev(2, 1, "pass", 1, x=40.0, end_x=55.0, outcome="complete")
    away_back = ev(3, 1, "pass", 1, side="away", x=60.0, end_x=45.0, outcome="complete")
    assert pl.gain(near) < pl.PROGRESSIVE_GAIN_M <= pl.gain(far)
    assert pl.gain(away_back) == 15.0  # the away side attacks towards x=0


def test_pass_quality_is_bounded_and_rewards_chances():
    long_pass = ev(1, 1, "pass", 1, x=40.0, end_x=90.0, outcome="complete")
    assert 0 <= pl.pass_quality(long_pass, False) <= 1
    assert pl.pass_quality(long_pass, True) > pl.pass_quality(long_pass, False)
    sideways = ev(2, 1, "pass", 1, x=40.0, end_x=40.0, outcome="complete")
    assert pl.pass_quality(sideways, False) == 0.0


def test_chance_created_and_impact_formula():
    events = [
        ev(1, 10, "pass", 1, x=60.0, end_x=90.0, outcome="complete"),       # progressive, creates the chance
        ev(2, 10, "goal", 2, x=90.0, xg=0.5, outcome="goal"),
    ]
    stats = pl.build_stats(tiny_match(events))
    assert stats[1]["chances_created"] == 1 and stats[1]["progressive_passes"] == 1
    assert stats[2]["goals"] == 1 and stats[2]["xg"] == 0.5
    assert stats[1]["impact"] == round(0.8 * 1 + 0.12 * 1, 2)
    assert stats[2]["impact"] == round(3 * 1 + 1.5 * 0.5, 2)


def test_cards_reduce_impact():
    events = [ev(1, 10, "tackle", 1), ev(2, 20, "red_card", 1)]
    assert pl.build_stats(tiny_match(events))[1]["impact"] == round(0.15 - 2, 2)


def test_every_shot_has_a_creator_in_the_synthetic_match():
    ov = pl.overview(MATCH)
    for side in ("home", "away"):
        created = sum(s["chances_created"] for s in ov if s["side"] == side)
        shots = sum(s["shots"] for s in ov if s["side"] == side)
        assert created == shots


def test_overview_is_ranked_by_impact_with_consecutive_team_ranks():
    ov = pl.overview(MATCH)
    assert [s["impact"] for s in ov] == sorted((s["impact"] for s in ov), reverse=True)
    for side in ("home", "away"):
        assert [s["rank_in_team"] for s in ov if s["side"] == side] == list(range(1, 1 + sum(1 for s in ov if s["side"] == side)))


def test_goal_roles_follow_the_score_line_not_the_final_score():
    from app import analytics as an
    roles = [(g.player_name, an.goal_role(MATCH, g)) for g in MATCH.events if g.type == "goal"]
    assert roles[0][1] == "opening goal"                       # away scores first, but loses: not match-winning
    assert roles[1][1] == "equaliser"                          # 0-1 -> 1-1: the home side's final margin is irrelevant
    assert roles[2][1].startswith("go-ahead goal") and "match-winning" in roles[2][1]


def test_player_facts_carry_goal_roles():
    scorer = next(g for g in MATCH.events if g.type == "goal" and g.side == "home")
    facts = pl.player_facts(MATCH, scorer.player_id)
    assert facts["goals"][0]["role"] == "equaliser" and facts["goals"][0]["score_after"] == "1-1"


def test_player_facts_unknown_player_is_none():
    assert pl.player_facts(MATCH, 99999) is None
    assert pl.player_facts(MATCH, pl.overview(MATCH)[0]["id"])["player"]["rank_overall"] == 1
