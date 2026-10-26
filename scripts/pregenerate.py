"""Record real agent explanations for the synthetic demo match, so the app can
run without Azure.

Run from the project root, signed in with `az login`:

    python -m scripts.pregenerate              # record everything missing
    python -m scripts.pregenerate --limit 3    # a short trial run
    python -m scripts.pregenerate --force      # re-record everything

Resumable: entries that are already recorded and clean are skipped. Only clean
results are worth keeping, so each
target is retried up to three times; if none is clean the last attempt is stored
and listed in the summary.
"""

import argparse
import asyncio
import sys

from app import demo
from app import players as pl
from app.agents import explain
from app.main import MATCHES
from app.main import MOMENTS

AUDIENCES_EN = ("casual_fan", "coach", "broadcaster")
AUDIENCES_PT = ("casual_fan", "broadcaster")
TOP_PLAYERS_PER_TEAM = 6
ATTEMPTS = 4
CONCURRENCY = (
    2  # 3 in parallel hit the deployment's rate limit on a student subscription
)


def build_targets(match, moments) -> list[tuple]:
    """(moment_id, player_id, audience, language) for everything the demo should
    answer offline."""
    targets = []
    for mo in moments:
        targets += [(mo["id"], None, a, "en") for a in AUDIENCES_EN]
        targets += [(mo["id"], None, a, "pt") for a in AUDIENCES_PT]
    targets += [(None, None, a, "en") for a in AUDIENCES_EN]
    targets += [(None, None, a, "pt") for a in AUDIENCES_PT]
    ranked = pl.overview(match)
    for side in ("home", "away"):
        for p in [s for s in ranked if s["side"] == side][
            :TOP_PLAYERS_PER_TEAM
        ]:
            targets += [
                (None, p["id"], a, "en") for a in ("casual_fan", "broadcaster")
            ]
    return targets


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=0, help="only the first N targets"
    )
    parser.add_argument(
        "--force", action="store_true", help="re-record even clean entries"
    )
    parser.add_argument(
        "--moment",
        default="",
        help="only this moment id (e.g. m3); with --force re-records it",
    )
    args = parser.parse_args()

    match_id = demo.DEMO_MATCH_ID
    match, moments = MATCHES[match_id], MOMENTS[match_id]
    fp = demo.fingerprint(match, moments)
    old_fp, entries = demo.load()
    if old_fp != fp:
        if entries:
            print(
                f"Existing recordings belong to a different match ({old_fp} != "
                f"{fp}); starting over."
            )
        entries = {}

    todo = []
    for mid, pid, aud, lang in build_targets(match, moments):
        if args.moment and mid != args.moment:
            continue
        key = demo.entry_key(match_id, mid, pid, aud, lang)
        if (
            args.force
            or key not in entries
            or not demo.is_clean(entries[key], aud)
        ):
            todo.append((key, mid, pid, aud, lang))
    if args.limit:
        todo = todo[: args.limit]
    print(
        f"{len(todo)} to record, {len(entries)} already recorded. Fingerprint "
        f"{fp}.",
        flush=True,
    )

    by_id = {m["id"]: m for m in moments}
    gate, lock, done = asyncio.Semaphore(CONCURRENCY), asyncio.Lock(), 0

    async def record(key, mid, pid, aud, lang) -> None:
        nonlocal done
        async with gate:
            moment = by_id.get(mid)
            player = pl.player_facts(match, pid) if pid is not None else None
            result = None
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    result = await explain(
                        match, moment, moments, aud, lang, player
                    )
                except Exception as exc:
                    print(
                        f"  ! {key[1:]} attempt {attempt} failed: "
                        f"{str(exc)[:140]}",
                        flush=True,
                    )
                    limited = "rate limit" in str(exc).lower()
                    await asyncio.sleep(
                        25 * attempt if limited else 3
                    )  # back off properly when throttled
                    continue
                if demo.is_clean(result, aud):
                    break
        async with lock:
            done += 1
            if result is None:
                print(f"[{done}/{len(todo)}] FAILED {key[1:]}", flush=True)
                return
            entries[key] = result
            demo.save(entries, fp)
            print(
                f"[{done}/{len(todo)}] "
                f"{'clean' if demo.is_clean(result, aud) else 'NOT CLEAN'} "
                f"{key[1:]}",
                flush=True,
            )

    await asyncio.gather(*(record(*t) for t in todo))

    dirty = [k[1:] for k, r in entries.items() if not demo.is_clean(r, k[3])]
    print(f"\nRecorded {len(entries)} entries; {len(dirty)} not clean.")
    for k in dirty:
        print("  not clean:", k)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
