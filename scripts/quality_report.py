"""First-try quality of the agents, measured with deterministic checks. Writes docs/quality_report.md.

    python -m scripts.quality_report             # the full set (needs `az login`, takes several minutes)
    python -m scripts.quality_report --limit 6   # a short trial

Unlike the recordings in demo/ (the best of up to four attempts), every case here runs ONCE and the first result
counts. Only infrastructure failures (rate limit, `az` cold start) are retried, never quality failures.

What it measures: the verifier flagged nothing, every figure in the text traces to the data, the broadcast graphic
exists, no chaotic-spell text names a single team, and no goal headline/graphic calls a goal the winner, the
equaliser or the opener when the computed goal role says otherwise. What it does NOT measure: whether the writing is
good, useful or well phrased. A pass is "no detectable error", not "good".
"""
import argparse
import asyncio
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

from app import demo
from app import players as pl
from app.agents import explain
from app.main import MATCHES, MOMENTS

OUT = Path(__file__).resolve().parent.parent / "docs" / "quality_report.md"
CONCURRENCY = 2
INFRA_RETRIES = 3
INFRA_MARKERS = ("rate limit", "Azure CLI", "timed out", "Connection", "temporarily")

ROLE_CLAIMS = [  # (what the text claims, regex, a substring the computed role must contain)
    ("match-winning", re.compile(r"match[- ]winning|winning goal|\bwinner\b|game[- ]winning", re.I), "match-winning"),
    ("equaliser", re.compile(r"equali[sz]er|equali[sz]ed|levell?ed", re.I), "equaliser"),
    ("opening goal", re.compile(r"opening goal|\bopener\b|first goal|scored first", re.I), "opening goal"),
]


def build_targets(match, moments) -> list[dict]:
    t = []
    for mo in moments:
        for aud in ("casual_fan", "coach", "broadcaster"):
            t.append({"moment": mo, "player": None, "audience": aud, "language": "en"})
        t.append({"moment": mo, "player": None, "audience": "broadcaster", "language": "pt"})
    for aud in ("casual_fan", "coach", "broadcaster"):
        t.append({"moment": None, "player": None, "audience": aud, "language": "en"})
    ranked = pl.overview(match)
    for side in ("home", "away"):
        for p in [s for s in ranked if s["side"] == side][:3]:
            t.append({"moment": None, "player": p, "audience": "casual_fan", "language": "en"})
    return t


def label(t: dict) -> str:
    kind = t["moment"]["title"] if t["moment"] else (f"player {t['player']['name']}" if t["player"] else "match recap")
    return f"{kind} / {t['audience']} / {t['language']}"


def kind_of(t: dict) -> str:
    return t["moment"]["type"] if t["moment"] else ("player" if t["player"] else "recap")


def role_mismatches(result: dict, moment: dict | None, language: str) -> list[str]:
    """Goal headlines and graphic text that claim a role the computed goal role contradicts (English only)."""
    if moment is None or moment["type"] != "goal" or language != "en":
        return []
    role = moment["facts"].get("goal_role", "")
    g = result.get("graphic") or {}
    short = " ".join([result.get("headline", ""), g.get("title", ""), g.get("line", "")])
    return [f"text says '{name}' but the goal was: {role}" for name, rx, need in ROLE_CLAIMS
            if rx.search(short) and need not in role]


async def run_one(t: dict, match, moments) -> dict:
    player = pl.player_facts(match, t["player"]["id"]) if t["player"] else None
    retries, t0, result, error = 0, time.perf_counter(), None, None
    for attempt in range(1, INFRA_RETRIES + 2):
        try:
            result = await explain(match, t["moment"], moments, t["audience"], t["language"], player)
            error = None
            break
        except Exception as exc:  # classify: infrastructure (retry) or a real failure (record)
            error = str(exc)[:200]
            if any(m.lower() in str(exc).lower() for m in INFRA_MARKERS) and attempt <= INFRA_RETRIES:
                retries += 1
                await asyncio.sleep(20 * attempt)
                t0 = time.perf_counter()
                continue
            break
    seconds = round(time.perf_counter() - t0, 1)
    rec = {"label": label(t), "kind": kind_of(t), "audience": t["audience"], "language": t["language"],
           "seconds": seconds, "retries": retries, "reasons": [], "claims": 0, "agent_seconds": {}, "text": ""}
    if result is None:
        rec["reasons"].append(f"pipeline error: {error}")
        return rec
    g = result.get("graphic") or {}  # kept so a failing case can be read, not just counted
    rec["text"] = " | ".join(x for x in (result.get("headline", ""), g.get("title", ""), g.get("line", "")) if x)
    v = result["verification"]
    rec["claims"] = v.get("claims_checked", 0)
    rec["agent_seconds"] = {x["agent"]: x["seconds"] for x in result["trace"] if "seconds" in x}
    for issue in v.get("issues") or []:
        rec["reasons"].append(("wording" if "concerns both teams" in issue else "verifier") + f": {issue}")
    if (v.get("numeric_check") or {}).get("unverified"):
        rec["reasons"].append(f"untraced figures: {v['numeric_check']['unverified']}")
    if t["audience"] == "broadcaster" and not result.get("graphic"):
        rec["reasons"].append("missing graphic")
    rec["reasons"] += [f"goal role: {m}" for m in role_mismatches(result, t["moment"], t["language"])]
    return rec


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}% ({n}/{d})" if d else "n/a"


def category(reason: str) -> str:
    for key in ("pipeline error", "verifier", "wording", "untraced figures", "missing graphic", "goal role"):
        if reason.startswith(key):
            return key
    return "other"


def write_report(records: list[dict], model: str) -> str:
    n = len(records)
    ok = [r for r in records if not r["reasons"]]
    lines = [
        "# Quality report: first-try results", "",
        f"Generated {date.today().isoformat()} with `{model}`. Command: `python -m scripts.quality_report`.", "",
        "Every case ran **once**; the first result counts (no retries on quality, unlike the recordings in `demo/`, "
        "which keep the best of up to four attempts). Only infrastructure failures such as rate limits were retried.", "",
        "**What a pass means:** the verifier flagged nothing, every figure in the text traces to the data, the broadcast "
        "graphic exists, a chaotic-spell text does not name just one team, and a goal headline or graphic does not call "
        "the goal the winner, the equaliser or the opener when the computed goal role says otherwise. "
        "**It does not mean the writing is good or useful.** Titles can still be generic and grammar can still slip.", "",
        "## Result", "", f"- Cases: **{n}** (match: the synthetic demo match, seed 7)",
        f"- Clean on the first try: **{pct(len(ok), n)}**", ""]
    by_cat = defaultdict(int)
    for r in records:
        for c in {category(x) for x in r["reasons"]}:
            by_cat[c] += 1
    lines += ["### Why cases failed (a case can fail for more than one reason)", "", "| Reason | Cases |", "|---|---|"]
    lines += [f"| {c} | {k} |" for c, k in sorted(by_cat.items(), key=lambda kv: -kv[1])] or ["| none | 0 |"]
    for title, key in (("By audience", "audience"), ("By language", "language"), ("By kind of target", "kind")):
        groups = defaultdict(list)
        for r in records:
            groups[r[key]].append(r)
        lines += ["", f"### {title}", "", "| Group | Clean first try |", "|---|---|"]
        lines += [f"| {g} | {pct(sum(1 for r in rs if not r['reasons']), len(rs))} |" for g, rs in sorted(groups.items())]
    times = [r["seconds"] for r in records if not any(x.startswith("pipeline error") for x in r["reasons"])]
    per_agent = defaultdict(list)
    for r in records:
        for a, s in r["agent_seconds"].items():
            per_agent[a].append(s)
    if times:
        lines += ["", "## Speed (live agents)", "", f"- Per explanation: median {statistics.median(times):.1f} s, "
                  f"slowest {max(times):.1f} s ({len(times)} runs, {CONCURRENCY} in parallel)",
                  "- Mean per agent: " + ", ".join(f"{a} {statistics.mean(s):.1f} s" for a, s in per_agent.items()),
                  "- Recorded results and the selection card are instant; only a new live explanation pays this cost."]
    lines += ["", "## Failing cases", ""]
    failing = [r for r in records if r["reasons"]]
    if failing:
        for r in failing:
            lines.append(f"- **{r['label']}**")
            if r.get("text"):
                lines.append(f"  - text: _{r['text'][:300]}_")
            lines += [f"  - {x}" for x in r["reasons"]]
    else:
        lines.append("None.")
    retried = sum(r["retries"] for r in records)
    lines += ["", f"Infrastructure retries (rate limit and similar, not counted as quality): {retried}.", "",
              "## Limits of this measurement", "",
              "- One synthetic match, one run per case: a different run can give a different result (the model varies).",
              "- The checks find errors that can be detected by rules. They cannot judge clarity, usefulness or tone.",
              "- English and Portuguese only; other languages were not measured.",
              "- Goal-role checks apply to English text only."]
    return "\n".join(lines) + "\n"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="only cases whose label contains this text (e.g. 'Chaotic')")
    ap.add_argument("--out", default=str(OUT), help="where to write the report")
    args = ap.parse_args()
    match, moments = MATCHES[demo.DEMO_MATCH_ID], MOMENTS[demo.DEMO_MATCH_ID]
    targets = build_targets(match, moments)
    if args.only:
        targets = [t for t in targets if args.only.lower() in label(t).lower()]
    if args.limit:
        targets = targets[:args.limit]
    print(f"{len(targets)} cases, {CONCURRENCY} in parallel.", flush=True)
    gate, done, records = asyncio.Semaphore(CONCURRENCY), 0, []

    async def worker(t):
        nonlocal done
        async with gate:
            rec = await run_one(t, match, moments)
        done += 1
        records.append(rec)
        print(f"[{done}/{len(targets)}] {'ok ' if not rec['reasons'] else 'FAIL'} {rec['seconds']:>5}s  {rec['label']}"
              + ("" if not rec["reasons"] else "  -> " + "; ".join(r[:70] for r in rec["reasons"])), flush=True)

    await asyncio.gather(*(worker(t) for t in targets))
    records.sort(key=lambda r: r["label"])
    report = write_report(records, os.environ.get("FOUNDRY_MODEL", "unknown"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    ok = sum(1 for r in records if not r["reasons"])
    print(f"\nClean on the first try: {pct(ok, len(records))}. Report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
