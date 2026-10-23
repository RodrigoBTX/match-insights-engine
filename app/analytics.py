"""Deterministic match analytics. All numbers shown to users come from here, never from the LLM:
agents interpret these facts, they do not invent them."""

import math
from collections import defaultdict

from .schema import PITCH_W, Event, Match

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


def goal_role(match: Match, goal: Event) -> str:
    """What a goal meant in the match, computed from the score line so no one has to infer it.

    The match-winning goal is the winner's (loser's final total + 1)th goal.
    """
    before_h, before_a = score_at(match, goal.t)
    own_b, opp_b = (before_h, before_a) if goal.side == "home" else (before_a, before_h)
    own_a = own_b + 1
    final_h, final_a = score_at(match, 10**9)
    final_own, final_opp = (
        (final_h, final_a) if goal.side == "home" else (final_a, final_h)
    )
    if own_b + opp_b == 0:
        role = "opening goal"
    elif own_b == opp_b:
        role = "go-ahead goal"
    elif own_b < opp_b and own_a == opp_b:
        role = "equaliser"
    elif own_b < opp_b:
        role = "goal that reduces the deficit"
    else:
        role = "goal that extends the lead"
    if final_own > final_opp and own_a == final_opp + 1:
        role += " (match-winning)"
    return role


def reds_before(match: Match, t: float) -> dict[str, int]:
    out = {"home": 0, "away": 0}
    for e in match.events:
        if e.type == "red_card" and e.t <= t:
            out[e.side] += 1
    return out


def win_probability(
    diff: int, minutes_left: float, home_reds: int = 0, away_reds: int = 0
) -> dict[str, float]:
    """Poisson model of the remaining goals. diff = home goals - away goals."""
    left = max(minutes_left, 0.0) / 90.0
    lam_h = 1.35 * left * (1 + 0.25 * away_reds) * (1 - 0.25 * home_reds)
    lam_a = 1.35 * left * (1 + 0.25 * home_reds) * (1 - 0.25 * away_reds)

    def pmf(lam: float, k: int) -> float:
        return math.exp(-lam) * lam**k / math.factorial(k)

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
    return {
        "home": round(ph / s, 3),
        "draw": round(pd / s, 3),
        "away": round(pa / s, 3),
    }


def possession_windows(match: Match, size: int = 5) -> list[dict]:
    counts: dict[int, dict[str, int]] = defaultdict(lambda: {"home": 0, "away": 0})
    for e in match.events:
        if e.type == "pass":
            counts[e.minute // size][e.side] += 1
    out = []
    for w in range(0, 93 // size + 1):
        c = counts[w]
        tot = c["home"] + c["away"]
        out.append(
            {
                "start": w * size,
                "end": (w + 1) * size,
                # a window without a single pass has no possession figure: None, not an invented 50/50
                "home": round(100 * c["home"] / tot) if tot else None,
                "away": round(100 * c["away"] / tot) if tot else None,
            }
        )
    return out


def xg_timeline(match: Match) -> list[dict]:
    cum = {"home": 0.0, "away": 0.0}
    by_min: dict[int, dict[str, float]] = defaultdict(
        lambda: {"home": 0.0, "away": 0.0}
    )
    for e in match.events:
        if e.xg is not None and e.type in ("shot", "goal"):
            by_min[e.minute][e.side] += e.xg
    out = []
    for m in range(0, 93):
        for s in cum:
            cum[s] += by_min[m][s]
        out.append(
            {"minute": m, "home": round(cum["home"], 2), "away": round(cum["away"], 2)}
        )
    return out


def momentum(match: Match) -> list[dict]:
    """Per-minute pressure index in [-1, 1]; positive favours home. Smoothed over a 3 minute window."""
    raw = {"home": defaultdict(float), "away": defaultdict(float)}
    for e in match.events:
        w = 0.0
        if e.type == "pass":
            w = 0.12 + (
                0.25
                if _attacking_third(e, e.end_x if e.end_x is not None else e.x)
                else 0.0
            )
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
        elif (
            finishing
            and dur <= 16
            and progress >= 40
            and evs[0].type in ("interception", "tackle")
        ):
            kind = "counter-attack"
        elif len(passes) >= 10:
            kind = "sustained-pressure"
        elif evs[0].type in ("tackle",) and evs[0].side == side:
            kind = "press-recovery"
        out[sid] = {
            "sequence_id": sid,
            "side": side,
            "kind": kind,
            "start_minute": start.minute,
            "start_second": start.second,
            "duration_s": dur,
            "passes": len(passes),
            "metres_gained": progress,
            "avg_pass_speed_kmh": (
                round(sum(speeds) / len(speeds), 1) if speeds else None
            ),
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
    passes = {
        s: sum(1 for e in ev if e.type == "pass" and e.side == s)
        for s in ("home", "away")
    }
    tot = sum(passes.values()) or 1
    res["possession_pct"] = {s: round(100 * passes[s] / tot) for s in passes}
    res["shots"] = {
        s: sum(1 for e in ev if e.type in ("shot", "goal") and e.side == s)
        for s in passes
    }
    res["xg"] = {
        s: round(
            sum(e.xg or 0 for e in ev if e.type in ("shot", "goal") and e.side == s), 2
        )
        for s in passes
    }
    res["final_third_passes"] = {
        s: sum(
            1
            for e in ev
            if e.type == "pass" and e.side == s and _attacking_third(e, e.end_x or e.x)
        )
        for s in passes
    }
    turnovers = sum(1 for e in ev if e.type in ("tackle", "interception"))
    span = max(end - start, 1)
    res["turnovers_per_min"] = round(turnovers / span, 2)
    top = max(res["possession_pct"], key=res["possession_pct"].get)
    res["game_state"] = (
        f"{top}_control" if res["possession_pct"][top] >= 60 else "contested"
    )

    ft = res["final_third_passes"]
    ft_total = (ft["home"] + ft["away"]) or 1
    res["field_tilt_pct"] = {
        s: round(100 * ft[s] / ft_total) for s in ft
    }  # share of final-third passes
    # press height: mean distance from own goal where a side wins the ball (higher = more aggressive press)
    res["press_height_m"] = {}
    for s in ("home", "away"):
        xs = [
            e.x if s == "home" else PITCH_W - e.x
            for e in ev
            if e.type in ("tackle", "interception") and e.side == s
        ]
        res["press_height_m"][s] = round(sum(xs) / len(xs), 1) if len(xs) >= 3 else None
    seq_ids = {
        e.sequence_id for e in ev if e.sequence_id is not None and e.type == "pass"
    }
    res["sequences_per_min"] = round(len(seq_ids) / span, 2)
    n_pass = sum(passes.values())
    res["passes_total"] = n_pass
    res["avg_passes_per_sequence"] = round(n_pass / len(seq_ids), 1) if seq_ids else 0.0
    res["tackles_interceptions"] = {
        s: sum(1 for e in ev if e.type in ("tackle", "interception") and e.side == s)
        for s in passes
    }
    return res


def _score_str(h: int, a: int) -> str:
    return f"{h}-{a}"


MIN_WINDOW_PASSES = 10        # per 5-minute window
MIN_SHIFT_WINDOW_PASSES = 30  # per 10-minute window on each side of a candidate shift


def control_windows(match: Match, size: int = 5) -> list[dict]:
    """Classify each window as home/away control, balanced or chaotic.

    Control blends possession with field tilt (share of final-third passes). A window is chaotic when
    possession changes hands much more often than the match average (short sequences, constant turnovers).
    """
    raw = [window_stats(match, s, min(s + size, 93)) for s in range(0, 93, size)]
    # A window with too few passes says nothing about control or chaos (gaps in a feed, sparse data): it is
    # shown as balanced and never counted as chaotic nor used for the match average.
    dense = [w for w in raw if w["passes_total"] >= MIN_WINDOW_PASSES]
    mean_spm = (sum(w["sequences_per_min"] for w in dense) / len(dense)) if dense else 1.0
    mean_spm = mean_spm or 1.0
    out = []
    for w in raw:
        score = {
            s: round(0.5 * w["possession_pct"][s] + 0.5 * w["field_tilt_pct"][s])
            for s in ("home", "away")
        }
        chaos = round(w["sequences_per_min"] / mean_spm, 2)
        top = max(score, key=score.get)
        if w["passes_total"] < MIN_WINDOW_PASSES:
            state = "balanced"
        else:
            state = (
                "chaotic"
                if chaos >= 1.25
                else f"{top}_control" if score[top] >= 62 else "balanced"
            )
        out.append(
            {
                "start": w["from_minute"],
                "end": w["to_minute"],
                "state": state,
                "chaos_ratio": chaos,
                "control_score": score,
                "possession_pct": w["possession_pct"],
                "field_tilt_pct": w["field_tilt_pct"],
                "sequences_per_min": w["sequences_per_min"],
                "avg_passes_per_sequence": w["avg_passes_per_sequence"],
            }
        )
    return out


def chaotic_spells(match: Match) -> list[dict]:
    """Merge consecutive chaotic windows into spells and compare them with the rest of the match."""
    wins = control_windows(match)
    spells, run = [], []
    for w in wins + [{"state": None}]:
        if w["state"] == "chaotic":
            run.append(w)
        elif run:
            spells.append((run[0]["start"], run[-1]["end"]))
            run = []
    names = {"home": match.home.name, "away": match.away.name}
    out = []
    for start, end in spells:
        inside = window_stats(match, start, end)
        h, a = score_at(match, start * 60)
        rest_spm = [
            w["sequences_per_min"] for w in wins if not start <= w["start"] < end
        ]
        rest_pps = [
            w["avg_passes_per_sequence"] for w in wins if not start <= w["start"] < end
        ]
        lo, hi = start * 60, end * 60
        ids = [
            e.id
            for e in match.events
            if lo <= e.t < hi
            and e.type
            in ("tackle", "interception", "foul", "yellow_card", "shot", "goal")
        ][:40]
        side = "home" if inside["possession_pct"]["home"] >= 50 else "away"
        out.append(
            {
                "minute": start,
                "side": side,
                "title": f"Chaotic spell – {start}' to {end}'",
                "event_ids": ids,
                "facts": {
                    "minute": f"{start}'00",
                    "teams": {"home": match.home.name, "away": match.away.name},
                    "team": "both teams",
                    "side": side,
                    "player": None,
                    "event": "chaotic_spell",
                    "xg": None,
                    "shot_speed_kmh": None,
                    "score_before": _score_str(h, a),
                    "score_after": _score_str(h, a),
                    "win_probability_before": None,
                    "win_probability_after": None,
                    "spell_minutes": f"{start}-{end}",
                    "ten_minutes_before_spell": {
                        k: window_stats(match, max(0, start - 10), start)[k]
                        for k in _SHIFT_KEYS
                    },
                    "during_spell": {k: inside[k] for k in _SHIFT_KEYS},
                    "rest_of_match_average": {
                        "sequences_per_min": round(sum(rest_spm) / len(rest_spm), 2),
                        "avg_passes_per_sequence": round(
                            sum(rest_pps) / len(rest_pps), 1
                        ),
                    },
                    "sequence": None,
                    "against_run_of_play": False,
                    "likely_trigger": None,
                    "red_cards_so_far": reds_before(match, start * 60),
                },
            }
        )
    return out


_SHIFT_KEYS = (
    "possession_pct",
    "field_tilt_pct",
    "press_height_m",
    "shots",
    "xg",
    "sequences_per_min",
    "avg_passes_per_sequence",
    "turnovers_per_min",
)


def _shift_score(before: dict, after: dict) -> float:
    """Home-perspective swing: field tilt points plus 1.5x the change in (home - away) press height."""
    delta = after["field_tilt_pct"]["home"] - before["field_tilt_pct"]["home"]
    ph = [w["press_height_m"] for w in (before, after)]
    if all(p["home"] is not None and p["away"] is not None for p in ph):
        delta += 1.5 * (
            (ph[1]["home"] - ph[1]["away"]) - (ph[0]["home"] - ph[0]["away"])
        )
    return delta


def tactical_shifts(
    match: Match, window: int = 10, threshold: int = 25, max_shifts: int = 3
) -> list[dict]:
    """Find the minutes where territory and pressing swing most between the 10 minutes before and after."""
    cands = []
    for t in range(window, 93 - window + 1):
        before, after = window_stats(match, t - window, t), window_stats(
            match, t, t + window
        )
        if min(before["passes_total"], after["passes_total"]) < MIN_SHIFT_WINDOW_PASSES:
            continue  # too little play on one side of the cut for a swing to mean anything
        delta = _shift_score(before, after)
        cands.append((abs(delta), t, delta, before, after))
    cands.sort(key=lambda c: c[0], reverse=True)
    chosen = []
    for score, t, delta, before, after in cands:
        if score < threshold or len(chosen) == max_shifts:
            break
        if all(abs(t - c["t"]) >= window for c in chosen):
            chosen.append({"t": t, "delta": delta, "before": before, "after": after})
    chosen.sort(key=lambda c: c["t"])

    names = {"home": match.home.name, "away": match.away.name}
    out = []
    for c in chosen:
        t, side = c["t"], "home" if c["delta"] > 0 else "away"
        before, after = c["before"], c["after"]
        # A cause must precede its effect: the latest goal or red card in the 6 minutes up to the shift.
        # Shifts are located at whole minutes, so an event in the first minute of the "after" window
        # (which starts at that minute) still counts: tolerance of one minute, never more.
        causes = [
            e
            for e in match.events
            if e.type in ("goal", "red_card") and -1 <= t - e.t / 60 <= 6
        ]
        trig = None
        if causes:
            e = max(causes, key=lambda x: x.t)
            trig = {
                "event": e.type,
                "team": names[e.side],
                "minute": f"{e.minute}'{e.second:02d}",
            }
        pb, pa = before["press_height_m"][side], after["press_height_m"][side]
        press_delta = round(pa - pb, 1) if pb is not None and pa is not None else None
        if press_delta is not None and press_delta >= 8:
            phrase = "press higher up the pitch"
        elif after["field_tilt_pct"][side] >= 60:
            phrase = "take territorial control"
        else:
            phrase = "claw back territory"
        h, a = score_at(match, t * 60)
        reds = reds_before(match, t * 60)
        lo, hi = t * 60, (t + window) * 60
        press_ids = [
            e.id
            for e in match.events
            if e.side == side
            and e.type in ("tackle", "interception")
            and lo <= e.t < hi
        ][:40]
        out.append(
            {
                "minute": t,
                "side": side,
                "title": f"Tactical shift – {names[side]} {phrase}",
                "event_ids": press_ids,
                "facts": {
                    "minute": f"{t}'00",
                    "teams": {"home": match.home.name, "away": match.away.name},
                    "team": names[side],
                    "side": side,
                    "player": None,
                    "event": "tactical_shift",
                    "xg": None,
                    "shot_speed_kmh": None,
                    "score_before": _score_str(h, a),
                    "score_after": _score_str(h, a),
                    "win_probability_before": None,
                    "win_probability_after": None,
                    "window_before_10_min": {k: before[k] for k in _SHIFT_KEYS},
                    "window_after_10_min": {k: after[k] for k in _SHIFT_KEYS},
                    "change": {
                        "field_tilt_points": abs(
                            after["field_tilt_pct"]["home"]
                            - before["field_tilt_pct"]["home"]
                        ),
                        "press_height_change_m": press_delta,
                        "sequences_per_min": round(
                            after["sequences_per_min"] - before["sequences_per_min"], 2
                        ),
                    },
                    "likely_trigger": trig,
                    "sequence": None,
                    "against_run_of_play": False,
                    "red_cards_so_far": reds,
                },
            }
        )
    return out


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
        wp_b = win_probability(
            before[0] - before[1], left, reds_b["home"], reds_b["away"]
        )
        wp_a = win_probability(
            after[0] - after[1], left, reds_a["home"], reds_a["away"]
        )
        w_start = max(0, t / 60 - 10)
        recent = window_stats(match, w_start, t / 60)  # strictly before the moment
        seq = seqs.get(e.sequence_id) if e.sequence_id is not None else None
        facts = {
            "minute": f"{e.minute}'{e.second:02d}",
            "teams": {"home": match.home.name, "away": match.away.name},
            "team": names[e.side],
            "side": e.side,
            "player": e.player_name,
            "event": kind,
            "xg": e.xg,
            "shot_speed_kmh": e.speed_kmh,
            "score_before": _score_str(*before),
            "score_after": _score_str(*after),
            "win_probability_before": wp_b,
            "win_probability_after": wp_a,
            "last_10_min_before_moment": recent,
            "sequence": (
                {k: v for k, v in seq.items() if k != "event_ids"} if seq else None
            ),
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
        if kind == "goal":
            facts["goal_role"] = goal_role(match, e)
        moments.append(
            {
                "minute": e.minute,
                "second": e.second,
                "type": kind,
                "side": e.side,
                "title": title,
                "event_id": e.id,
                "sequence_id": e.sequence_id,
                "event_ids": seq["event_ids"] if seq else [e.id],
                "facts": facts,
            }
        )
    for kind, found in (
        ("tactical_shift", tactical_shifts(match)),
        ("chaotic_spell", chaotic_spells(match)),
    ):
        for s in found:
            moments.append(
                {
                    "minute": s["minute"],
                    "second": 0,
                    "type": kind,
                    "side": s["side"],
                    "title": s["title"],
                    "event_id": None,
                    "sequence_id": None,
                    "event_ids": s["event_ids"],
                    "facts": s["facts"],
                }
            )
    moments.sort(key=lambda m: (m["minute"], m["second"]))
    for i, m in enumerate(moments, 1):
        m["id"] = f"m{i}"
    return moments


def match_summary(match: Match) -> dict:
    h, a = score_at(match, 10**9)
    shots = {
        s: sum(1 for e in match.events if e.type in ("shot", "goal") and e.side == s)
        for s in ("home", "away")
    }
    on_target = {
        s: sum(
            1
            for e in match.events
            if e.type in ("goal",) or (e.type == "shot" and e.outcome == "saved")
            if e.side == s
        )
        for s in ("home", "away")
    }
    xg = {
        s: round(
            sum(
                e.xg or 0
                for e in match.events
                if e.type in ("shot", "goal") and e.side == s
            ),
            2,
        )
        for s in ("home", "away")
    }
    passes = {
        s: sum(1 for e in match.events if e.type == "pass" and e.side == s)
        for s in ("home", "away")
    }
    tot = sum(passes.values()) or 1
    return {
        "score": {"home": h, "away": a},
        "shots": shots,
        "on_target": on_target,
        "xg": xg,
        "possession_pct": {s: round(100 * passes[s] / tot) for s in passes},
        "passes": passes,
        "cards": {
            s: {
                "yellow": sum(
                    1 for e in match.events if e.type == "yellow_card" and e.side == s
                ),
                "red": sum(
                    1 for e in match.events if e.type == "red_card" and e.side == s
                ),
            }
            for s in ("home", "away")
        },
    }
