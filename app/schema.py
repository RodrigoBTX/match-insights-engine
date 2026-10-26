"""Canonical event schema. Agents, analytics and UI only ever read these models,
so synthetic and real data are interchangeable via an adapter.

Pitch coordinates: 105 x 68 metres. The home team attacks towards x=105,
the away team towards x=0. Coordinates are absolute (never mirrored).
"""

from typing import Literal

from pydantic import BaseModel
from pydantic import Field

PITCH_W = 105.0
PITCH_H = 68.0

Side = Literal["home", "away"]
EventType = Literal[
    "pass",
    "shot",
    "goal",
    "save",
    "tackle",
    "interception",
    "foul",
    "yellow_card",
    "red_card",
    "corner",
    "kickoff",
]


class Player(BaseModel):
    id: int
    name: str
    number: int
    position: str
    side: Side


class Team(BaseModel):
    side: Side
    name: str
    short: str
    color: str


class Event(BaseModel):
    id: int
    minute: int
    second: int = 0
    side: Side
    player_id: int | None = None
    player_name: str | None = None
    type: EventType
    x: float
    y: float
    end_x: float | None = None
    end_y: float | None = None
    outcome: str | None = (
        None  # complete/incomplete, on_target/off_target/blocked/saved/goal
    )
    xg: float | None = None
    speed_kmh: float | None = None  # ball speed for passes and shots
    sequence_id: int | None = None
    note: str | None = None

    @property
    def t(self) -> float:
        """Match time in seconds."""
        return self.minute * 60 + self.second


class Match(BaseModel):
    id: str
    competition: str = "Synthetic League"
    source: str = "synthetic"
    home: Team
    away: Team
    players: list[Player] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)

    def team(self, side: Side) -> Team:
        return self.home if side == "home" else self.away
