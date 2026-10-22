"""Adapters that convert external event feeds into the canonical schema.

Everything downstream (analytics, agents, UI) reads only app.schema, so plugging in real data is
a matter of writing one function like this. The StatsBomb-style adapter below follows the public
open-data event layout (120x80 pitch, per-team attacking direction, `possession` ids); it is
written against that documented layout and covered by a small fixture test, not by a full real match.
"""
from .schema import PITCH_H, PITCH_W, Event, Match, Player, Team

PALETTE = {"home": "#4f8cff", "away": "#ff8a3d"}


def _scale(loc: list[float] | None) -> tuple[float, float] | tuple[None, None]:
    if not loc or len(loc) < 2:
        return None, None
    return loc[0] * PITCH_W / 120.0, loc[1] * PITCH_H / 80.0


def _absolute(side: str, x: float | None, y: float | None) -> tuple[float | None, float | None]:
    """StatsBomb stores every team attacking towards x=120; we keep the home team as-is and mirror away."""
    if x is None:
        return None, None
    return (x, y) if side == "home" else (PITCH_W - x, PITCH_H - y)


def from_statsbomb(raw: list[dict], match_id: str = "real-match") -> Match:
    if not isinstance(raw, list) or not all(isinstance(ev, dict) for ev in raw):
        raise ValueError("Expected a JSON array of event objects")
    team_names: list[str] = []
    for ev in raw:
        name = (ev.get("team") or {}).get("name")
        if name and name not in team_names:
            team_names.append(name)
        if len(team_names) == 2:
            break
    if len(team_names) < 2:
        raise ValueError("Expected events from two teams")
    side_of = {team_names[0]: "home", team_names[1]: "away"}
    home = Team(side="home", name=team_names[0], short=team_names[0][:3].upper(), color=PALETTE["home"])
    away = Team(side="away", name=team_names[1], short=team_names[1][:3].upper(), color=PALETTE["away"])

    players: dict[int, Player] = {}
    events: list[Event] = []
    for ev in raw:
        tname = (ev.get("team") or {}).get("name")
        etype = (ev.get("type") or {}).get("name")
        if tname not in side_of or not etype:
            continue
        side = side_of[tname]
        pl = ev.get("player") or {}
        if pl.get("id") and pl["id"] not in players:
            players[pl["id"]] = Player(id=pl["id"], name=pl.get("name", "?"), number=0,
                                       position=(ev.get("position") or {}).get("name", "?"), side=side)

        x, y = _scale(ev.get("location"))
        if x is None:
            continue
        kind, outcome, xg, ex, ey = None, None, None, None, None

        if etype == "Pass":
            p = ev.get("pass", {})
            ex, ey = _scale(p.get("end_location"))
            if (p.get("type") or {}).get("name") == "Corner":
                kind = "corner"
            else:
                kind, outcome = "pass", "incomplete" if p.get("outcome") else "complete"
        elif etype == "Shot":
            s = ev.get("shot", {})
            res = (s.get("outcome") or {}).get("name", "")
            kind = "goal" if res == "Goal" else "shot"
            outcome = {"Goal": "goal", "Saved": "saved", "Blocked": "blocked"}.get(res, "off_target")
            xg = s.get("statsbomb_xg")
            ex, ey = _scale(s.get("end_location", [None, None])[:2] if s.get("end_location") else None)
        elif etype == "Interception":
            kind, outcome = "interception", "won"
        elif etype == "Duel" and ((ev.get("duel") or {}).get("type") or {}).get("name") == "Tackle":
            kind, outcome = "tackle", "won"
        elif etype == "Foul Committed":
            card = ((ev.get("foul_committed") or {}).get("card") or {}).get("name", "")
            kind = "red_card" if "Red" in card or "Second" in card else "yellow_card" if "Yellow" in card else "foul"
        elif etype == "Goal Keeper" and "Save" in ((ev.get("goalkeeper") or {}).get("type") or {}).get("name", ""):
            kind = "save"

        if not kind:
            continue
        ax, ay = _absolute(side, x, y)
        aex, aey = _absolute(side, ex, ey)
        events.append(Event(
            id=len(events) + 1, minute=int(ev.get("minute", 0)), second=int(ev.get("second", 0)), side=side,
            player_id=pl.get("id"), player_name=pl.get("name"), type=kind,
            x=round(ax, 1), y=round(ay, 1),
            end_x=round(aex, 1) if aex is not None else None, end_y=round(aey, 1) if aey is not None else None,
            outcome=outcome, xg=xg, sequence_id=ev.get("possession"),
        ))

    events.sort(key=lambda e: e.t)
    for i, e in enumerate(events, 1):
        e.id = i
    return Match(id=match_id, competition="Imported event feed", source="statsbomb-format",
                 home=home, away=away, players=list(players.values()), events=events)
