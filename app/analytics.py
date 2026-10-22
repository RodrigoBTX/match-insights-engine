"""Deterministic match analytics. All numbers shown to users come from here, never from the LLM:
agents interpret these facts, they do not invent them."""
import math
from collections import defaultdict

from .schema import Event, Match

OTHER = {"home": "away", "away": "home"}


def _attacking_third(e: Event, x: float) -> bool:
    return x >= 70 if e.side == "home" else x <= 35


def score_at(match: Match, t: float, inclusive: bool = False) -> tuple[int, int]:
    h = a = 0
    for e in match.events:
        if e.type != "goal":
            continue
        if e.t < t or (inclusive and e.t == t):
            h += e.side == "home"
            a += e.side == "away"
    return h, a


def reds_before(match: Match, t: float) -> dict[str, int]:
    out = {"home": 0, "away": 0}
    for e in match.events:
        if e.type == "red_card" and e.t <= t:
            out[e.side] += 1
    return out


def win_probability(diff: int, minutes_left: float, home_reds: int = 0, away_reds: int = 0) -> dict[str, float]:
    """Poisson model of the remaining goals. diff = home goals - away goals."""
    left = max(minutes_left, 0.0) / 90.0
    lam_h = 1.35 * left * (1 + 0.25 * away_reds) * (1 - 0.25 * home_reds)
    lam_a = 1.35 * left * (1 + 0.25 * home_reds) * (1 - 0.25 * away_reds)

    def pmf(lam: float, k: int) -> float:
        return math.exp(-lam) * lam ** k / math.factorial(k)

    ph = pa = pd = 0.0
    for i in range(9):
        for j in range(9):
            p = pmf(lam_h, i) * pmf(lam_a, j)
            total = diff + i - j
            if total > 0:
                ph += p
            elif total < 0:
                pa += p
            else:
                pd += p
    s = ph + pa + pd
    return {"home": round(ph / s, 3), "draw": round(pd / s, 3), "away": round(pa / s, 3)}


def possession_windows(match: Match, size: int = 5) -> list[dict]:
    counts: dict[int, dict[str, int]] = defaultdict(lambda: {"home": 0, "away": 0})
    for e in match.events:
        if e.type == "pass":
            counts[e.minute // size][e.side] += 1
    out = []
    for w in range(0, 93 // size + 1):
        c = counts[w]
        tot = c["home"] + c["away"]
        out.append({"start": w * size, "end": (w + 1) * size,
                    "home": round(100 * c["home"] / tot) if tot else 50,
                    "away": round(100 * c["away"] / tot) if tot else 50})
    return out


def xg_timeline(match: Match) -> list[dict]:
    cum = {"home": 0.0, "away": 0.0}
    by_min: dict[int, dict[str, float]] = defaultdict(lambda: {"home": 0.0, "away": 0.0})
    for e in match.events:
        if e.xg is not None and e.type in ("shot", "goal"):
            by_min[e.minute][e.side] += e.xg
    out = []
    for m in range(0, 93):
        for s in cum:
            cum[s] += by_min[m][s]
        out.append({"minute": m, "home": round(cum["home"], 2), "away": round(cum["away"], 2)})
    return out


def momentum(match: Match) -> list[dict]:
    """Per-minute pressure index in [-1, 1]; positive favours home. Smoothed over a 3 minute window."""
    raw = {"home": defaultdict(float), "away": defaultdict(float)}
    for e in match.events:
        w = 0.0
        if e.type == "pass":
            w = 0.12 + (0.25 if _attacking_third(e, e.end_x if e.end_x is not None else e.x) else 0.0)
        elif e.type in ("shot", "goal"):
            w = 1.0 + 4.0 * (e.xg or 0)
        elif e.type == "corner":
            w = 0.8
        elif e.type == "save":
            continue
        raw[e.side][e.minute] += w
    series = []
    for m in range(0, 93):
        h = sum(raw["home"][k] for k in range(m - 1, m + 2))
        a = sum(raw["away"][k] for k in range(m - 1, m + 2))
        tot = h + a
        series.append({"minute": m, "value": round((h - a) / tot, 2) if tot else 0.0})
    return series


def sequences(match: Match) -> dict[int, dict]:
    groups: dict[int, list[Event]] = defaultdict(list)
    for e in match.events:
        if e.sequence_id is not None and e.type != "kickoff":
            groups[e.sequence_id].append(e)
    out: dict[int, dict] = {}
    for sid, evs in groups.items():
        evs.sort(key=lambda e: e.t)
        passes = [e for e in evs if e.type == "pass"]
        side = passes[0].side if passes else evs[0].side
        own = [e for e in evs if e.side == side]
        start, end = own[0], own[-1]
        dur = round(end.t - start.t, 1)
        sx = start.x
        ex = end.end_x if end.type == "pass" and end.end_x is not None else end.x
        progress = round(abs(ex - sx), 1)
        finishing = next((e for e in own if e.type in ("goal", "shot")), None)
        speeds = [e.speed_kmh for e in passes if e.speed_kmh]
        kind = "build-up"
        if evs[0].type == "corner":
            kind = "set-piece"
        elif finishing and dur <= 16 and progress >= 40 and evs[0].type in ("interception", "tackle"):
            kind = "counter-attack"
        elif len(passes) >= 10:
            kind = "sustained-pressure"
        elif evs[0].type in ("tackle",) and evs[0].side == side:
            kind = "press-recovery"
        out[sid] = {
            "sequence_id": sid, "side": side, "kind": kind,
            "start_minute": start.minute, "start_second": start.second,
            "duration_s": dur, "passes": len(passes), "metres_gained": progress,
            "avg_pass_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else None,
            "started_with": evs[0].type,
            "ended_with": finishing.type if finishing else end.type,
            "max_xg": max([e.xg for e in own if e.xg] or [0]),
            "event_ids": [e.id for e in evs],
        }
    return out


def window_stats(match: Match, start: float, end: float) -> dict:
    """Aggregate stats between two match minutes (inclusive start, exclusive end)."""
    lo, hi = start * 60, end * 60
    ev = [e for e in match.events if lo <= e.t < hi]
    res: dict = {"from_minute": start, "to_minute": end}
    passes = {s: sum(1 for e in ev if e.type == "pass" and e.side == s) for s in ("home", "away")}
    tot = sum(passes.values()) or 1
    res["possession_pct"] = {s: round(100 * passes[s] / tot) for s in passes}
    res["shots"] = {s: sum(1 for e in ev if e.type in ("shot", "goal") and e.side == s) for s in passes}
    res["xg"] = {s: round(sum(e.xg or 0 for e in ev if e.type in ("shot", "goal") and e.side == s), 2) for s in passes}
    res["final_third_passes"] = {
        s: sum(1 for e in ev if e.type == "pass" and e.side == s and _attacking_third(e, e.end_x or e.x))
        for s in passes}
    turnovers = sum(1 for e in ev if e.type in ("tackle", "interception"))
    span = max(end - start, 1)
    res["turnovers_per_min"] = round(turnovers / span, 2)
    top = max(res["possession_pct"], key=res["possession_pct"].get)
    res["game_state"] = f"{top}_control" if res["possession_pct"][top] >= 60 else "contested"
    res["tackles_interceptions"] = {s: sum(1 for e in ev if e.type in ("tackle", "interception") and e.side == s)
                                    for s in passes}
    return res


def _score_str(h: int, a: int) -> str:
    return f"{h}-{a}"


def detect_moments(match: Match) -> list[dict]:
    seqs = sequences(match)
    names = {"home": match.home.name, "away": match.away.name}
    moments: list[dict] = []
    for e in match.events:
        kind = None
        if e.type == "goal":
            kind = "goal"
        elif e.type == "red_card":
            kind = "red_card"
        elif e.type == "shot" and (e.xg or 0) >= 0.3 and e.outcome == "saved":
            kind = "big_chance"
        if not kind:
            continue
        t = e.t
        before = score_at(match, t)
        after = score_at(match, t, inclusive=True)
        reds_b = reds_before(match, t - 1)
        reds_a = reds_before(match, t)
        left = 93 - t / 60
        wp_b = win_probability(before[0] - before[1], left, reds_b["home"], reds_b["away"])
        wp_a = win_probability(after[0] - after[1], left, reds_a["home"], reds_a["away"])
        w_start = max(0, t / 60 - 10)
        recent = window_stats(match, w_start, t / 60)  # strictly before the moment
        seq = seqs.get(e.sequence_id) if e.sequence_id is not None else None
        facts = {
            "minute": f"{e.minute}'{e.second:02d}",
            "teams": {"home": match.home.name, "away": match.away.name},
            "team": names[e.side], "side": e.side, "player": e.player_name,
            "event": kind, "xg": e.xg, "shot_speed_kmh": e.speed_kmh,
            "score_before": _score_str(*before), "score_after": _score_str(*after),
            "win_probability_before": wp_b, "win_probability_after": wp_a,
            "last_10_min_before_moment": recent,
            "sequence": {k: v for k, v in seq.items() if k != "event_ids"} if seq else None,
            "red_cards_so_far": reds_a,
        }
        against_run = kind == "goal" and recent["possession_pct"][e.side] < 45
        title = {
            "goal": f"Goal – {names[e.side]}",
            "red_card": f"Red card – {names[e.side]}",
            "big_chance": f"Big chance saved – {names[e.side]}",
        }[kind]
        if kind == "goal" and seq and seq["kind"] != "build-up":
            title += f" ({seq['kind']})"
        facts["against_run_of_play"] = against_run
        moments.append({
            "id": f"m{len(moments) + 1}", "minute": e.minute, "second": e.second,
            "type": kind, "side": e.side, "title": title,
            "event_id": e.id, "sequence_id": e.sequence_id,
            "event_ids": seq["event_ids"] if seq else [e.id],
            "facts": facts,
        })
    return moments


def match_summary(match: Match) -> dict:
    h, a = score_at(match, 10 ** 9)
    shots = {s: sum(1 for e in match.events if e.type in ("shot", "goal") and e.side == s) for s in ("home", "away")}
    on_target = {s: sum(1 for e in match.events if e.type in ("goal",) or (e.type == "shot" and e.outcome == "saved")
                        if e.side == s) for s in ("home", "away")}
    xg = {s: round(sum(e.xg or 0 for e in match.events if e.type in ("shot", "goal") and e.side == s), 2)
          for s in ("home", "away")}
    passes = {s: sum(1 for e in match.events if e.type == "pass" and e.side == s) for s in ("home", "away")}
    tot = sum(passes.values()) or 1
    return {
        "score": {"home": h, "away": a}, "shots": shots, "on_target": on_target, "xg": xg,
        "possession_pct": {s: round(100 * passes[s] / tot) for s in passes},
        "passes": passes,
        "cards": {s: {"yellow": sum(1 for e in match.events if e.type == "yellow_card" and e.side == s),
                      "red": sum(1 for e in match.events if e.type == "red_card" and e.side == s)}
                  for s in ("home", "away")},
    }
