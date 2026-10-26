"""Deterministic player and pass-quality analytics.

Definitions (kept simple so they can be explained on screen):
- progressive pass: a completed pass that moves the ball at least 10 m closer to
  the opponent's goal
- pass quality (0-1): 0.60 x territorial gain (saturates at 30 m) + 0.25 if it
  ends in the attacking third
  + 0.15 if it is the pass that leads to a shot
- chance created: the last completed pass (or corner) before a shot or goal by
  the same team in a sequence
- impact: 3 x goals + 1.5 x xG + 0.8 x chances created + 0.8 x saves + 0.12 x
  progressive passes
  + 0.15 x (tackles + interceptions) - 0.5 x yellow cards - 2 x red cards
"""

from collections import defaultdict

from . import analytics as an
from .schema import Event
from .schema import Match

PROGRESSIVE_GAIN_M = 10.0


def gain(e: Event) -> float:
    """Metres gained towards the opponent's goal by a pass."""
    if e.end_x is None:
        return 0.0
    return (e.end_x - e.x) if e.side == "home" else (e.x - e.end_x)


def _attacking_third(side: str, x: float) -> bool:
    return x >= 70 if side == "home" else x <= 35


def chance_creators(match: Match) -> set[int]:
    """Ids of the passes/corners that directly precede a shot by the same team
    in the same sequence."""
    last: dict[tuple, Event] = {}
    out: set[int] = set()
    for e in sorted(match.events, key=lambda ev: ev.t):
        key = (e.sequence_id, e.side)
        if e.type == "pass" and e.outcome == "complete" or e.type == "corner":
            last[key] = e
        elif e.type in ("shot", "goal") and key in last:
            out.add(last.pop(key).id)
    return out


def pass_quality(e: Event, leads_to_shot: bool) -> float:
    q = 0.6 * min(max(gain(e), 0.0) / 30.0, 1.0)
    if e.end_x is not None and _attacking_third(e.side, e.end_x):
        q += 0.25
    if leads_to_shot:
        q += 0.15
    return round(q, 2)


def build_stats(match: Match) -> dict[int, dict]:
    creators = chance_creators(match)
    stats: dict[int, dict] = {}
    for p in match.players:
        stats[p.id] = {
            "id": p.id,
            "name": p.name,
            "number": p.number,
            "position": p.position,
            "side": p.side,
            "team": match.team(p.side).name,
            "passes": 0,
            "completed": 0,
            "progressive_passes": 0,
            "chances_created": 0,
            "shots": 0,
            "shots_on_target": 0,
            "goals": 0,
            "xg": 0.0,
            "top_shot_speed_kmh": None,
            "saves": 0,
            "tackles": 0,
            "interceptions": 0,
            "fouls": 0,
            "yellow": 0,
            "red": 0,
            "_quality": [],
            "_pass_speed": [],
        }
    for e in match.events:
        s = stats.get(e.player_id) if e.player_id is not None else None
        if s is None:
            continue
        if e.type == "pass":
            s["passes"] += 1
            if e.outcome == "complete":
                s["completed"] += 1
                if gain(e) >= PROGRESSIVE_GAIN_M:
                    s["progressive_passes"] += 1
                s["_quality"].append(pass_quality(e, e.id in creators))
                if e.speed_kmh:
                    s["_pass_speed"].append(e.speed_kmh)
        elif e.type == "corner" and e.id in creators:
            s["chances_created"] += 1
        elif e.type in ("shot", "goal"):
            s["shots"] += 1
            s["xg"] += e.xg or 0.0
            if e.type == "goal" or e.outcome == "saved":
                s["shots_on_target"] += 1
            if e.type == "goal":
                s["goals"] += 1
            if e.speed_kmh and (
                s["top_shot_speed_kmh"] is None
                or e.speed_kmh > s["top_shot_speed_kmh"]
            ):
                s["top_shot_speed_kmh"] = e.speed_kmh
        elif e.type == "save":
            s["saves"] += 1
        elif e.type == "tackle":
            s["tackles"] += 1
        elif e.type == "interception":
            s["interceptions"] += 1
        elif e.type == "foul":
            s["fouls"] += 1
        elif e.type == "yellow_card":
            s["yellow"] += 1
        elif e.type == "red_card":
            s["red"] += 1
    for pid in creators:
        e = next(
            (ev for ev in match.events if ev.id == pid and ev.type == "pass"),
            None,
        )
        if e is not None and e.player_id in stats:
            stats[e.player_id]["chances_created"] += 1

    for s in stats.values():
        q, sp = s.pop("_quality"), s.pop("_pass_speed")
        s["pass_completion_pct"] = (
            round(100 * s["completed"] / s["passes"]) if s["passes"] else None
        )
        s["avg_pass_quality"] = round(sum(q) / len(q), 2) if q else None
        s["avg_pass_speed_kmh"] = round(sum(sp) / len(sp), 1) if sp else None
        s["xg"] = round(s["xg"], 2)
        s["ball_wins"] = (
            s["tackles"] + s["interceptions"]
        )  # precomputed so agents never do arithmetic
        s["impact"] = round(
            3 * s["goals"]
            + 1.5 * s["xg"]
            + 0.8 * s["chances_created"]
            + 0.8 * s["saves"]
            + 0.12 * s["progressive_passes"]
            + 0.15 * (s["tackles"] + s["interceptions"])
            - 0.5 * s["yellow"]
            - 2 * s["red"],
            2,
        )
    return stats


def overview(match: Match) -> list[dict]:
    """All players with a minimum of activity, ranked by impact, with overall
    and in-team rank."""
    stats = [
        s
        for s in build_stats(match).values()
        if s["passes"] or s["shots"] or s["saves"]
    ]
    stats.sort(key=lambda s: s["impact"], reverse=True)
    seen: dict[str, int] = defaultdict(int)
    for i, s in enumerate(stats, 1):
        seen[s["side"]] += 1
        s["rank_overall"], s["rank_in_team"] = i, seen[s["side"]]
    return stats


def player_facts(match: Match, player_id: int) -> dict | None:
    """Facts handed to the agents about one player, with team context."""
    ranked = overview(match)
    me = next((s for s in ranked if s["id"] == player_id), None)
    if me is None:
        return None
    team = [s for s in ranked if s["side"] == me["side"]]
    events = [e for e in match.events if e.player_id == player_id]
    goals = []
    for e in events:
        if e.type == "goal":
            h, a = an.score_at(match, e.t, inclusive=True)
            goals.append(
                {
                    "minute": f"{e.minute}'{e.second:02d}",
                    "score_after": f"{h}-{a}",
                    "role": an.goal_role(match, e),
                    "xg": e.xg,
                }
            )
    cards = [
        f"{e.type.replace('_card', '')} {e.minute}'"
        for e in events
        if e.type in ("yellow_card", "red_card")
    ]
    totals = {
        k: sum(s[k] for s in team)
        for k in ("progressive_passes", "chances_created", "goals", "shots")
    }
    totals["xg"] = round(sum(s["xg"] for s in team), 2)
    totals["ball_wins"] = sum(s["ball_wins"] for s in team)
    share = {
        k: round(100 * me[k] / totals[k]) if totals[k] else 0
        for k in (
            "progressive_passes",
            "chances_created",
            "goals",
            "shots",
            "xg",
            "ball_wins",
        )
    }
    final_score = {
        side: sum(
            1 for e in match.events if e.type == "goal" and e.side == side
        )
        for side in ("home", "away")
    }
    return {
        "teams": {"home": match.home.name, "away": match.away.name},
        "player": me,
        "goals": goals,
        "cards": cards,
        "team_totals": totals,
        "share_of_team_pct": share,
        "match_score": (
            f"{match.home.name} {final_score['home']}-{final_score['away']} {match.away.name}"
        ),
        "players_ranked_overall": len(ranked),
        "impact_formula": (
            "3*goals + 1.5*xG + 0.8*chances_created + 0.8*saves + "
            "0.12*progressive_passes "
            "+ 0.15*(tackles+interceptions) - 0.5*yellow - 2*red"
        ),
    }
