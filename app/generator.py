"""Synthetic match generator.

Produces a full 90+ minute match in the canonical schema. Baseline play is
randomised (seeded); a handful of scripted sequences give the match a story:
a counter-attack goal against the run of play, a red card that shifts momentum,
an equaliser from a corner and a winner after sustained pressure.
Random shots never score, so the score line is exactly what the script says.
"""
import math
import random

from .schema import PITCH_H, PITCH_W, Event, Match, Player, Team

HOME = Team(side="home", name="Northbridge FC", short="NOR", color="#4f8cff")
AWAY = Team(side="away", name="Eastport United", short="EAS", color="#ff8a3d")

POSITIONS = ["GK", "LB", "CB", "CB", "RB", "CM", "CM", "CAM", "LW", "RW", "ST"]
HOME_NAMES = ["Tomas Hale", "Ben Okafor", "Luca Brandt", "Mateo Silva", "Jonas Weir", "Idris Moreau",
              "Kai Lindqvist", "Rafael Duarte", "Elias Novak", "Samir Haddad", "Oskar Penn"]
AWAY_NAMES = ["Viktor Rask", "Dario Conte", "Hugo Marchetti", "Niall Foster", "Teo Barros", "Anders Voll",
              "Yusuf Demir", "Felix Brandao", "Marek Sobol", "Diogo Lacerda", "Callum Reid"]

GOAL_W = 7.32


def build_players() -> list[Player]:
    players: list[Player] = []
    for side, names in (("home", HOME_NAMES), ("away", AWAY_NAMES)):
        base = 1 if side == "home" else 101
        for i, (name, pos) in enumerate(zip(names, POSITIONS)):
            players.append(Player(id=base + i, name=name, number=i + 1 if i else 1, position=pos, side=side))
    return players


def expected_goals(local_x: float, local_y: float) -> float:
    """Simple distance/angle xG model. Coordinates are local (attacking towards x=105)."""
    dx, dy = PITCH_W - local_x, abs(local_y - PITCH_H / 2)
    dist = math.hypot(dx, dy)
    a1 = math.atan2(dy + GOAL_W / 2, dx) if dx > 0 else math.pi / 2
    a2 = math.atan2(dy - GOAL_W / 2, dx) if dx > 0 else math.pi / 2
    angle = abs(a1 - a2)
    return round(max(0.01, min(0.65, 0.95 * math.exp(-dist / 11.0) * min(1.0, angle / 0.55))), 2)


def to_abs(side: str, lx: float, ly: float) -> tuple[float, float]:
    return (lx, ly) if side == "home" else (PITCH_W - lx, PITCH_H - ly)


def phase(minute: float) -> tuple[float, float, tuple[int, int]]:
    """(home possession probability, shot-ending probability, passes per sequence) by minute."""
    if minute < 12:
        return 0.64, 0.30, (5, 8)   # calm, patient home control
    if minute < 27:
        return 0.64, 0.30, (3, 8)
    if minute < 36:
        return 0.54, 0.30, (3, 7)
    if minute < 45:
        return 0.50, 0.28, (2, 4)   # scrappy spell: short sequences, constant turnovers
    if minute < 56:
        return 0.50, 0.28, (3, 7)
    if minute < 63:
        return 0.68, 0.34, (4, 8)   # away down to ten men
    return 0.72, 0.46, (4, 8)       # sustained home pressure


def scrappy(minute: float) -> bool:
    return 36 <= minute < 45


class Gen:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.players = build_players()
        self.events: list[dict] = []
        self.seq = 0

    def pick(self, side: str, positions: tuple[str, ...] | None = None) -> Player:
        pool = [p for p in self.players if p.side == side and p.position != "GK"]
        if positions:
            pool = [p for p in pool if p.position in positions]
        return self.r.choice(pool)

    def gk(self, side: str) -> Player:
        return next(p for p in self.players if p.side == side and p.position == "GK")

    def add(self, t: float, side: str, etype: str, player: Player | None, lx: float, ly: float,
            lex: float | None = None, ley: float | None = None, **kw) -> None:
        ax, ay = to_abs(side, lx, ly)
        end = to_abs(side, lex, ley) if lex is not None else (None, None)
        self.events.append(dict(
            t=t, side=side, type=etype, player_id=player.id if player else None,
            player_name=player.name if player else None, x=round(ax, 1), y=round(ay, 1),
            end_x=round(end[0], 1) if end[0] is not None else None,
            end_y=round(end[1], 1) if end[1] is not None else None,
            sequence_id=self.seq, **kw))

    def pass_speed(self, dist: float, fast: bool = False) -> float:
        base = 55 + dist * 0.9 if fast else 30 + dist * 1.1
        return round(max(18.0, base + self.r.gauss(0, 4)), 1)

    def build_up(self, t: float, side: str, path: list[tuple[float, float]], fast: bool = False,
                 step: tuple[float, float] = (1.6, 3.4)) -> tuple[float, Player]:
        """Emit completed passes along a local-coordinate path. Returns end time and last receiver."""
        holder = self.pick(side)
        for (x0, y0), (x1, y1) in zip(path, path[1:]):
            dist = math.hypot(x1 - x0, y1 - y0)
            self.add(t, side, "pass", holder, x0, y0, x1, y1, outcome="complete",
                     speed_kmh=self.pass_speed(dist, fast))
            t += self.r.uniform(*((1.8, 2.6) if fast else step))
            holder = self.pick(side)
        return t, holder

    def shot(self, t: float, side: str, shooter: Player, lx: float, ly: float, outcome: str,
             xg: float | None = None, speed: float | None = None) -> None:
        xg = xg if xg is not None else expected_goals(lx, ly)
        speed = speed or round(self.r.uniform(78, 112), 1)
        etype = "goal" if outcome == "goal" else "shot"
        self.add(t, side, etype, shooter, lx, ly, PITCH_W, PITCH_H / 2 + self.r.uniform(-3, 3),
                 outcome=outcome, xg=xg, speed_kmh=speed)
        if outcome == "saved":
            other = "away" if side == "home" else "home"
            self.add(t + 0.8, other, "save", self.gk(other), *self._mirror_local(side, lx, ly))

    def _mirror_local(self, shooter_side: str, lx: float, ly: float) -> tuple[float, float]:
        # keeper stands on the opposite local goal line; stored via the keeper's own local coords
        return 4.0, PITCH_H / 2 + self.r.uniform(-3, 3)

    # ------------------------------------------------------------------ random play
    def random_sequence(self, t: float, minute: float) -> float:
        home_p, shot_p, lengths = phase(minute)
        side = "home" if self.r.random() < home_p else "away"
        other = "away" if side == "home" else "home"
        self.seq += 1
        n = self.r.randint(*lengths)
        sx = self.r.uniform(18, 55)
        shooting = self.r.random() < shot_p * 0.4
        tx = self.r.uniform(80, 94) if shooting else self.r.uniform(55, 80)
        if side == "away" and minute >= 56 and not shooting:
            # ten men, pinned back: they lose the ball early and the home side wins it high up the pitch
            sx, tx = self.r.uniform(12, 30), self.r.uniform(26, 50)
        xs = sorted([sx + (tx - sx) * i / n + self.r.gauss(0, 3) for i in range(n + 1)])
        path = [(max(2, min(103, x)), max(4, min(64, PITCH_H / 2 + self.r.gauss(0, 14)))) for x in xs]
        t, holder = self.build_up(t, side, path)
        lx, ly = path[-1]
        if shooting:
            xg = expected_goals(lx, ly)
            outcome = self.r.choices(["saved", "off_target", "blocked"], [0.38, 0.4, 0.22])[0]
            self.shot(t, side, holder, lx, ly, outcome, xg=xg)
            t += 2.0
            if outcome == "blocked" and self.r.random() < 0.35:
                self.add(t, side, "corner", holder, PITCH_W, 0.0 if self.r.random() < 0.5 else PITCH_H)
                t += 6.0
        else:
            roll = self.r.random()
            d = self.pick(other)
            if roll < 0.55:
                self.add(t, other, "tackle", d, PITCH_W - lx, PITCH_H - ly, outcome="won")
            elif roll < 0.90:
                self.add(t, other, "interception", d, PITCH_W - lx, PITCH_H - ly, outcome="won")
            else:
                self.add(t, side, "foul", holder, lx, ly)
        return t + (self.r.uniform(1, 3.5) if scrappy(minute) else self.r.uniform(3, 8))

    # ------------------------------------------------------------------ scripted story
    def script(self) -> list[tuple[float, callable]]:
        return [
            (27 * 60 + 10, self.counter_goal_away),
            (33 * 60 + 40, lambda t: self.card(t, "home", "yellow_card", 26, 30)),
            (44 * 60 + 30, self.home_big_chance),
            (56 * 60 + 0, self.away_red_card),
            (63 * 60 + 20, self.home_corner_equaliser),
            (71 * 60 + 5, lambda t: self.card(t, "away", "yellow_card", 70, 40)),
            (78 * 60 + 0, self.home_pressure_winner),
            (88 * 60 + 15, self.away_late_chance),
        ]

    def card(self, t: float, side: str, kind: str, lx: float, ly: float) -> float:
        self.seq += 1
        p = self.pick(side, ("CB", "CM", "LB", "RB"))
        self.add(t, side, "foul", p, lx, ly)
        self.add(t + 2, side, kind, p, lx, ly)
        return t + 20

    def counter_goal_away(self, t: float) -> float:
        # Away win the ball deep in their own half, break at pace and score against the run of play.
        self.seq += 1
        d = self.pick("away", ("CB", "CM"))
        self.add(t, "away", "interception", d, 28, 36, outcome="won")  # local coords for away
        path = [(30, 36), (52, 22), (74, 40), (88, 34)]
        t2, holder = self.build_up(t + 1.2, "away", path, fast=True)
        striker = self.pick("away", ("ST", "LW", "RW"))
        self.shot(t2, "away", striker, 90, 35, "goal", xg=0.42, speed=96.0)
        return t2 + 30

    def home_big_chance(self, t: float) -> float:
        self.seq += 1
        t, _ = self.build_up(t, "home", [(55, 30), (70, 42), (84, 36)])
        self.shot(t, "home", self.pick("home", ("ST", "CAM")), 90, 34, "saved", xg=0.38)
        return t + 20

    def away_red_card(self, t: float) -> float:
        # Home attacker is clean through; the last defender brings him down.
        self.seq += 1
        t, _ = self.build_up(t, "home", [(46, 34), (66, 28), (84, 32)])
        defender = self.pick("away", ("CB",))
        self.add(t, "away", "foul", defender, 21, 36)  # away-local (21, 36) == absolute (84, 32)
        self.add(t + 3, "away", "red_card", defender, 21, 36)
        return t + 35

    def home_corner_equaliser(self, t: float) -> float:
        self.seq += 1
        self.add(t, "home", "corner", self.pick("home", ("CAM", "LW")), PITCH_W, 0.0)
        header = self.pick("home", ("CB", "ST"))
        self.shot(t + 4, "home", header, 98, 31, "goal", xg=0.14, speed=71.0)
        return t + 30

    def home_pressure_winner(self, t: float) -> float:
        # High press wins the ball, then 14 passes of sustained pressure before the winner.
        self.seq += 1
        d = self.pick("home", ("CM",))
        self.add(t, "home", "tackle", d, 74, 30, outcome="won")
        path = [(74, 30)]
        for i in range(14):
            px, py = path[-1]
            path.append((min(96, px + self.r.uniform(-1, 2.5)), max(8, min(60, py + self.r.gauss(0, 9)))))
        t, holder = self.build_up(t + 1, "home", path, step=(2.0, 3.8))
        self.shot(t, "home", self.pick("home", ("ST", "RW", "LW")), 91, 33, "goal", xg=0.31, speed=101.0)
        return t + 30

    def away_late_chance(self, t: float) -> float:
        self.seq += 1
        t, _ = self.build_up(t, "away", [(45, 30), (66, 38), (82, 34)], fast=True)
        self.shot(t, "away", self.pick("away", ("ST",)), 86, 33, "saved", xg=0.33)
        return t + 20

    # ------------------------------------------------------------------ main loop
    def run(self) -> list[Event]:
        end_t = 93 * 60
        t = 0.0
        self.seq = 0
        self.add(0, "home", "kickoff", None, 52.5, 34.0)
        scripted = sorted(self.script(), key=lambda s: s[0])
        i = 0
        while t < end_t:
            if i < len(scripted) and t >= scripted[i][0] - 25:
                t = max(t, scripted[i][0])
                t = scripted[i][1](t) + 4
                i += 1
                continue
            t = self.random_sequence(t, t / 60)
        # run remaining scripted events if the loop overshot
        while i < len(scripted):
            scripted[i][1](max(t, scripted[i][0]))
            i += 1
        self.events.sort(key=lambda e: e["t"])
        out: list[Event] = []
        for idx, e in enumerate(self.events, 1):
            total = int(e.pop("t"))
            out.append(Event(id=idx, minute=total // 60, second=total % 60, **e))
        return out


def generate_match(seed: int = 7) -> Match:
    g = Gen(seed)
    events = g.run()
    return Match(id=f"synthetic-{seed}", home=HOME, away=AWAY, players=g.players, events=events)
