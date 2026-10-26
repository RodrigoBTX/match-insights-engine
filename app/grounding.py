"""Deterministic numeric guard: every number in the agents' final text must be
traceable to the data.

It complements the LLM Verifier, which is good at names and causes but can miss
a wrong figure.
Small integers (<= 10) are ignored because they appear in ordinary prose ("two
goals", "10 minutes").
Numbers that are legitimately derived (a difference, a sum) are reported too:
the guard flags what it
cannot trace and leaves the judgement to the reader.
"""

import re

NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _parse(token: str) -> float:
    return float(token.replace(",", "."))


def numbers_in(text: str) -> list[float]:
    return [_parse(m.group()) for m in NUM.finditer(text)]


def allowed_numbers(*sources: str) -> list[float]:
    allowed: list[float] = []
    for src in sources:
        for n in numbers_in(src):
            allowed.append(n)
            if 0 < n <= 1:
                allowed.append(
                    round(n * 100, 1)
                )  # fractions are narrated as percentages
    return allowed


def framing_issues(
    event: str | None, text: str, teams: list[tuple[str, ...]]
) -> list[str]:
    """Wording checks the numbers cannot see.

    A chaotic spell is a loss of control by both teams. Text that names exactly
    one of them (as "Northbridge ramps
    up possession") frames it as that team imposing itself, which the data does
    not say; the numeric guard and the
    Verifier both let such text through. Naming both teams, or neither, is fine.
    """
    if event != "chaotic_spell":
        return []
    named = [
        any(alias and alias in text for alias in aliases) for aliases in teams
    ]
    if sum(named) == 1:
        return [
            "A chaotic spell concerns both teams, but the text names only one "
            "of them."
        ]
    return []


def numeric_check(text: str, allowed: list[float]) -> dict:
    checked, unverified = 0, []
    for token in NUM.findall(text):
        n = _parse(token)
        if n == int(n) and n <= 10:
            continue
        checked += 1
        tol = (
            1.0 if n == int(n) else 0.051
        )  # integers may be rounded or truncated, decimals may not
        if not any(abs(n - a) <= tol for a in allowed):
            unverified.append(token)
    return {"checked": checked, "unverified": sorted(set(unverified))}
