"""Recorded demo mode: explanations generated earlier by the real agents,
replayed without Azure.

Each recording is tied to a fingerprint of the demo match (its events and
detected moments). If the generator
or the analytics change, the fingerprint changes and the old recordings are
ignored instead of attaching
explanations to the wrong facts.
"""

from datetime import date
import hashlib
import json
import os
from pathlib import Path

from .schema import Match

DEMO_FILE = (
    Path(__file__).resolve().parent.parent / "demo" / "explanations.json"
)
DEMO_MATCH_ID = "synthetic-7"

# Failures that mean "live agents cannot run here" (as opposed to a transient or
# a code error).
AUTH_MARKERS = (
    "Azure CLI",
    "az login",
    "CredentialUnavailable",
    "ClientAuthentication",
    "AuthenticationFailed",
    "Unauthorized",
    "FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_MODEL",
    "project_endpoint",
)

Key = tuple  # (match_id, moment_id, player_id, audience, language)


def is_auth_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(marker in text for marker in AUTH_MARKERS)


def fingerprint(match: Match, moments: list[dict]) -> str:
    """Identifies the match and moments that the recordings belong to.

    The hash covers every event and the facts of every moment, so recordings
    made
    for a different match, or before the generator changed, are detected and
    ignored.

    Args:
      match: The demo match.
      moments: Its detected moments.

    Returns:
      A short hexadecimal digest.
    """
    payload = {
        "events": [
            [e.id, e.type, e.side, e.minute, e.second, e.player_id, e.x, e.y]
            for e in match.events
        ],
        "moments": [
            [
                m["id"],
                m["type"],
                m["minute"],
                json.dumps(m["facts"], sort_keys=True),
            ]
            for m in moments
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()[:16]


def is_clean(result: dict, audience: str) -> bool:
    """A recording worth keeping: verified, every figure traced, and a graphic
    when one was requested."""
    v = result.get("verification") or {}
    traced = not (v.get("numeric_check") or {}).get("unverified")
    return (
        not v.get("issues")
        and traced
        and (audience != "broadcaster" or bool(result.get("graphic")))
    )


def entry_key(
    match_id: str, moment_id, player_id, audience: str, language: str
) -> Key:
    return (match_id, moment_id, player_id, audience, language)


def load(path: Path = DEMO_FILE) -> tuple[str | None, dict[Key, dict]]:
    """Return (fingerprint, recordings) from the demo file, or (None, {}) when
    it does not exist."""
    if not path.exists():
        return None, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for e in data.get("entries", []):
        out[
            entry_key(
                e["match_id"],
                e["moment_id"],
                e["player_id"],
                e["audience"],
                e["language"],
            )
        ] = e["result"]
    return data.get("fingerprint"), out


def save(entries: dict[Key, dict], fp: str, path: Path = DEMO_FILE) -> None:
    """Writes the recorded explanations to disk.

    Args:
      entries: The recorded results, keyed by (match, moment, player, audience,
        language).
      fp: The fingerprint of the match the entries belong to.
      path: The destination file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "fingerprint": fp,
        "generated": date.today().isoformat(),
        "model": os.environ.get("FOUNDRY_MODEL", "unknown"),
        "entries": [
            {
                "match_id": k[0],
                "moment_id": k[1],
                "player_id": k[2],
                "audience": k[3],
                "language": k[4],
                "result": r,
            }
            for k, r in sorted(
                entries.items(), key=lambda kv: tuple(str(x) for x in kv[0])
            )
        ],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    tmp.replace(
        path
    )  # atomic: an interrupted run never leaves a half-written file


def install(
    match: Match, moments: list[dict], path: Path = DEMO_FILE
) -> tuple[dict[Key, dict], dict]:
    """Recordings usable for this match, plus a small status report. Stale
    recordings are not returned."""
    fp, entries = load(path)
    current = fingerprint(match, moments)
    if fp is None:
        return {}, {"found": False, "usable": False, "count": 0}
    if fp != current:
        return {}, {
            "found": True,
            "usable": False,
            "count": len(entries),
            "reason": "match changed since recording",
        }
    return entries, {"found": True, "usable": True, "count": len(entries)}


def pick_fallback(recorded: dict[Key, dict], key: Key) -> Key | None:
    """Nearest recording for an unrecorded request: same target in English, same
    audience first."""
    match_id, moment_id, player_id, audience, _language = key
    for aud in (audience, "casual_fan"):
        candidate = entry_key(match_id, moment_id, player_id, aud, "en")
        if candidate in recorded:
            return candidate
    return None
