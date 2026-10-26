"""Adapters that convert external event feeds into the canonical schema.

Everything downstream (analytics, agents, UI) reads only app.schema, so plugging
in real data is
a matter of writing one function like this. The StatsBomb-style adapter below
follows the public
open-data event layout (120x80 pitch, per-team attacking direction, `possession`
ids); it is
written against that documented layout and covered by a small fixture test, not
by a full real match.
"""

from defusedxml import ElementTree as ET  # hardened parser: uploads are untrusted

from .generator import expected_goals
from .schema import Event
from .schema import Match
from .schema import PITCH_H
from .schema import PITCH_W
from .schema import Player
from .schema import Team

PALETTE = {"home": "#4f8cff", "away": "#ff8a3d"}


def _scale(loc: list[float] | None) -> tuple[float, float] | tuple[None, None]:
    if not loc or len(loc) < 2:
        return None, None
    return loc[0] * PITCH_W / 120.0, loc[1] * PITCH_H / 80.0


def _absolute(
    side: str, x: float | None, y: float | None
) -> tuple[float | None, float | None]:
    """StatsBomb stores every team attacking towards x=120; we keep the home
    team as-is and mirror away."""
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
    home = Team(
        side="home",
        name=team_names[0],
        short=team_names[0][:3].upper(),
        color=PALETTE["home"],
    )
    away = Team(
        side="away",
        name=team_names[1],
        short=team_names[1][:3].upper(),
        color=PALETTE["away"],
    )

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
            players[pl["id"]] = Player(
                id=pl["id"],
                name=pl.get("name", "?"),
                number=0,
                position=(ev.get("position") or {}).get("name", "?"),
                side=side,
            )

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
                kind, outcome = (
                    "pass",
                    "incomplete" if p.get("outcome") else "complete",
                )
        elif etype == "Shot":
            s = ev.get("shot", {})
            res = (s.get("outcome") or {}).get("name", "")
            kind = "goal" if res == "Goal" else "shot"
            outcome = {
                "Goal": "goal",
                "Saved": "saved",
                "Blocked": "blocked",
            }.get(res, "off_target")
            xg = s.get("statsbomb_xg")
            ex, ey = _scale(
                s.get("end_location", [None, None])[:2]
                if s.get("end_location")
                else None
            )
        elif etype == "Interception":
            kind, outcome = "interception", "won"
        elif (
            etype == "Duel"
            and ((ev.get("duel") or {}).get("type") or {}).get("name")
            == "Tackle"
        ):
            kind, outcome = "tackle", "won"
        elif etype == "Foul Committed":
            card = ((ev.get("foul_committed") or {}).get("card") or {}).get(
                "name", ""
            )
            kind = (
                "red_card"
                if "Red" in card or "Second" in card
                else "yellow_card"
                if "Yellow" in card
                else "foul"
            )
        elif etype == "Goal Keeper" and "Save" in (
            (ev.get("goalkeeper") or {}).get("type") or {}
        ).get("name", ""):
            kind = "save"

        if not kind:
            continue
        ax, ay = _absolute(side, x, y)
        aex, aey = _absolute(side, ex, ey)
        events.append(
            Event(
                id=len(events) + 1,
                minute=int(ev.get("minute", 0)),
                second=int(ev.get("second", 0)),
                side=side,
                player_id=pl.get("id"),
                player_name=pl.get("name"),
                type=kind,
                x=round(ax, 1),
                y=round(ay, 1),
                end_x=round(aex, 1) if aex is not None else None,
                end_y=round(aey, 1) if aey is not None else None,
                outcome=outcome,
                xg=xg,
                sequence_id=ev.get("possession"),
            )
        )

    events.sort(key=lambda e: e.t)
    for i, e in enumerate(events, 1):
        e.id = i
    return Match(
        id=match_id,
        competition="Imported event feed",
        source="statsbomb-format",
        home=home,
        away=away,
        players=list(players.values()),
        events=events,
    )


# ---------------------------------------------------------------------------------------------
# Opta F24 (XML) adapter
#
# Verified against the open-source `socceraction` parser: Game/Event/Q
# structure, end coordinates
# in qualifiers 140/141 (pass) and 146/147 (blocked shot), corner = pass with
# qualifier 6.
# Taken from a secondary source (penaltyblog): event type ids and card
# qualifiers 31-33.
# NOT verified: which of 31/32/33 is which card (assumed 31 yellow, 32 second
# yellow, 33 red) and that
# the Game element carries team names. Written without access to a real feed;
# tested on a hand-made
# fixture. F24 has no player names and, as far as I could confirm, no xG, so ids
# stand in for names and
# xG comes from this project's distance/angle model.
# ---------------------------------------------------------------------------------------------
(
    OPTA_PASS,
    OPTA_OFFSIDE_PASS,
    OPTA_FOUL,
    OPTA_TACKLE,
    OPTA_INTERCEPTION,
    OPTA_SAVE,
    OPTA_CARD,
) = (1, 2, 4, 7, 8, 10, 17)
OPTA_SHOTS = {
    13: "off_target",
    14: "off_target",
    15: "saved",
    16: "goal",
}  # miss, post, attempt saved, goal
OPTA_CARD_QUALIFIERS = {31: "yellow_card", 32: "red_card", 33: "red_card"}
OPTA_OWN_GOAL = 28
OPTA_PLAYED_PERIODS = (
    1,
    2,
    3,
    4,
)  # halves and extra time; period 5 is the shoot-out, 14 is pre-match


def _opta_xy(
    attr: dict, xk: str, yk: str
) -> tuple[float, float] | tuple[None, None]:
    """Opta pitch coordinates are 0-100 on both axes; convert to metres."""
    try:
        return (
            float(attr[xk]) * PITCH_W / 100.0,
            float(attr[yk]) * PITCH_H / 100.0,
        )
    except (KeyError, TypeError, ValueError):
        return None, None


def _assign_sequences(events: list[Event]) -> None:
    """F24 has no possession id, so derive sequences: a pass/shot by another
    team, a gap over 12 s, or a
    ball won (tackle/interception) starts a new one. A save belongs to the shot
    it answers.
    """
    seq, side, last_t = 0, None, -1e9
    for e in events:
        if e.type == "save":
            e.sequence_id = seq
            continue
        starts = (
            seq == 0
            or e.type in ("tackle", "interception")
            or (
                e.type in ("pass", "shot", "goal", "corner")
                and (e.side != side or e.t - last_t > 12)
            )
        )
        if starts:
            seq += 1
            side = e.side
        e.sequence_id = seq
        last_t = e.t


def from_opta_f24(xml: bytes | str, match_id: str = "opta-match") -> Match:
    root = ET.fromstring(xml)
    game = next(root.iter("Game"), None)
    if game is None:
        raise ValueError("No <Game> element found: is this an Opta F24 feed?")
    try:
        home_id, away_id = int(game.attrib["home_team_id"]), int(
            game.attrib["away_team_id"]
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(
            "The <Game> element needs home_team_id and away_team_id"
        ) from exc
    side_of = {home_id: "home", away_id: "away"}
    home_name = game.attrib.get("home_team_name") or f"Team {home_id}"
    away_name = game.attrib.get("away_team_name") or f"Team {away_id}"
    home = Team(
        side="home",
        name=home_name,
        short=home_name[:3].upper(),
        color=PALETTE["home"],
    )
    away = Team(
        side="away",
        name=away_name,
        short=away_name[:3].upper(),
        color=PALETTE["away"],
    )

    players: dict[int, Player] = {}
    events: list[Event] = []
    for ev in game.iter("Event"):
        a = ev.attrib
        try:
            tid, team_id, period = (
                int(a["type_id"]),
                int(a["team_id"]),
                int(a["period_id"]),
            )
        except (KeyError, ValueError):
            continue
        if team_id not in side_of or period not in OPTA_PLAYED_PERIODS:
            continue
        side = side_of[team_id]
        q = {
            int(x.attrib["qualifier_id"]): x.attrib.get("value")
            for x in ev.iter("Q")
            if "qualifier_id" in x.attrib
        }
        x, y = _opta_xy(a, "x", "y")
        if x is None:
            continue
        pid = int(a["player_id"]) if a.get("player_id") else None
        if pid is not None and pid not in players:
            players[pid] = Player(
                id=pid, name=f"Player {pid}", number=0, position="?", side=side
            )

        kind, outcome, xg, ex, ey = None, None, None, None, None
        if tid in (OPTA_PASS, OPTA_OFFSIDE_PASS):
            ex, ey = _opta_xy({"x": q.get(140), "y": q.get(141)}, "x", "y")
            if 6 in q:
                kind = "corner"
            else:
                kind = "pass"
                outcome = (
                    "complete"
                    if tid == OPTA_PASS and a.get("outcome", "1") == "1"
                    else "incomplete"
                )
        elif tid in OPTA_SHOTS:
            if OPTA_OWN_GOAL in q:
                continue
            kind = "goal" if tid == 16 else "shot"
            outcome = OPTA_SHOTS[tid]
            xg = expected_goals(
                x, y
            )  # model xG from distance and angle; the feed's own xG is not used
        elif tid == OPTA_TACKLE:
            kind, outcome = "tackle", "won"
        elif tid == OPTA_INTERCEPTION:
            kind, outcome = "interception", "won"
        elif (
            tid == OPTA_FOUL and a.get("outcome") == "0"
        ):  # Opta logs the foul for both players: keep the offender
            kind = "foul"
        elif tid == OPTA_SAVE:
            kind = "save"
        elif tid == OPTA_CARD:
            kind = next(
                (
                    OPTA_CARD_QUALIFIERS[k]
                    for k in OPTA_CARD_QUALIFIERS
                    if k in q
                ),
                None,
            )
        if kind is None:
            continue

        ax, ay = _absolute(side, x, y)
        aex, aey = _absolute(side, ex, ey)
        events.append(
            Event(
                id=0,
                minute=int(a.get("min", 0)),
                second=int(a.get("sec", 0)),
                side=side,
                player_id=pid,
                player_name=players[pid].name if pid in players else None,
                type=kind,
                x=round(ax, 1),
                y=round(ay, 1),
                end_x=round(aex, 1) if aex is not None else None,
                end_y=round(aey, 1) if aey is not None else None,
                outcome=outcome,
                xg=xg,
            )
        )

    if not events:
        raise ValueError("The feed contains no usable events")
    events.sort(key=lambda e: e.t)
    for i, e in enumerate(events, 1):
        e.id = i
    _assign_sequences(events)
    return Match(
        id=match_id,
        competition="Imported event feed",
        source="opta-f24-format",
        home=home,
        away=away,
        players=list(players.values()),
        events=events,
    )
