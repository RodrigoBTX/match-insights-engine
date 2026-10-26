"""Does the Verifier still catch wrong claims? Plants five errors in a goal
explanation and counts what it flags.

    python -m scripts.verifier_probe        # needs `az login`; a few seconds
    per round

A control round with a CORRECT text checks that it does not cry wolf. Run it
again after any change to the
Verifier prompt: making it quieter (fewer false alarms) must not make it blind.
"""

import asyncio
import json
import sys

from agent_framework import Agent

from app import demo
from app.agents import client
from app.agents import parse_json
from app.agents import VERIFIER_PROMPT
from app.main import MOMENTS

ROUNDS = 3


def build_texts(facts: dict) -> tuple[dict, dict, dict[str, tuple[str, ...]]]:
    """(correct narration, narration with five planted errors, how to recognise
    each error in the issues)."""
    team, player = facts["team"], facts["player"]
    wp_b, wp_a = (
        facts["win_probability_before"][facts["side"]],
        facts["win_probability_after"][facts["side"]],
    )
    correct = {
        "headline": f"{player} scores for {team}",
        "explanation": (
            f"At {facts['minute']}, {player} scored for {team} with an xG of {facts['xg']:.2f}. "
            f"{team}'s win probability moved from {wp_b * 100:.1f}% to {wp_a * 100:.1f}%."
        ),
        "tactical_takeaway": "The goal changed the shape of the game.",
    }
    planted = {
        "headline": f"Marek Sobol scores for {team}",
        "explanation": (
            f"At 31'05, Marek Sobol scored for {team} with an xG of 0.85 after 11 passes. "
            f"{team}'s win probability rose from {wp_b * 100:.1f}% to 91.0%. "
            "The opposition had a player sent off just before."
        ),
        "tactical_takeaway": "The goal changed the shape of the game.",
    }
    markers = {
        "wrong scorer": ("Marek", "Sobol", player),
        "wrong minute": ("31'05", "31:05", "minute"),
        "wrong xG": ("0.85",),
        "wrong pass count": ("11 passes", "11 pass", "passes"),
        "wrong probability": ("91",),
        "invented red card": ("sent off", "red card", "dismiss"),
    }
    return correct, planted, markers


async def ask(text: dict, facts: dict) -> dict:
    verifier = Agent(client(), VERIFIER_PROMPT, name="Verifier")
    reply = await verifier.run(
        "Facts:\n"
        + json.dumps(facts)
        + "\n\nNarrator JSON:\n"
        + json.dumps(text)
    )
    return parse_json(reply.text)


async def main() -> int:
    goal = next(m for m in MOMENTS[demo.DEMO_MATCH_ID] if m["type"] == "goal")
    correct, planted, markers = build_texts(goal["facts"])
    caught_total, false_total = 0, 0
    for i in range(1, ROUNDS + 1):
        control = await ask(correct, goal["facts"])
        wrong = await ask(planted, goal["facts"])
        issues = " ".join(wrong.get("issues") or []).lower()
        found = {
            name: any(k.lower() in issues for k in keys)
            for name, keys in markers.items()
        }
        caught = sum(found.values())
        caught_total += caught
        false_total += len(control.get("issues") or [])
        print(
            f"round {i}: planted errors caught {caught}/{len(markers)} "
            f"({', '.join(n for n, ok in found.items() if not ok) or 'none missed'} missed) | "
            f"correct text: verdict={control.get('verdict')}, issues listed={len(control.get('issues') or [])}",
            flush=True,
        )
    print(
        f"\nTotal: {caught_total}/{ROUNDS * len(markers)} planted errors caught; "
        f"{false_total} issues listed on the correct text over {ROUNDS} rounds."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
