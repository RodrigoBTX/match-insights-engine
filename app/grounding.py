"""Deterministic numeric guard: every number in the agents' final text must be traceable to the data.

It complements the LLM Verifier, which is good at names and causes but can miss a wrong figure.
Small integers (<= 10) are ignored because they appear in ordinary prose ("two goals", "10 minutes").
Numbers that are legitimately derived (a difference, a sum) are reported too: the guard flags what it
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
                allowed.append(round(n * 100, 1))  # fractions are narrated as percentages
    return allowed


def numeric_check(text: str, allowed: list[float]) -> dict:
    checked, unverified = 0, []
    for token in NUM.findall(text):
        n = _parse(token)
        if n == int(n) and n <= 10:
            continue
        checked += 1
        tol = 0.5 if n == int(n) else 0.051  # integers may be rounded, decimals may not
        if not any(abs(n - a) <= tol for a in allowed):
            unverified.append(token)
    return {"checked": checked, "unverified": sorted(set(unverified))}
