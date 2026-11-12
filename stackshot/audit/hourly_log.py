"""hourly_log.py: the hourly audit lines an item carries, kept apart from the ladder's own (`metadata.stall.log`).

The pure half of audit/hourly.py: no server import, no clock read, no file. The lines are an item's History (one line each, "stackshot: Audit hh:mm: …"), written in a log of their own,
`metadata.hourly_audit.log`, so they neither crowd out the stall ladder's last eight entries nor read as steps of the stall pass (`get` prints them with an `audit:` prefix, not `stall:`).
Each entry is {"at", "text", "kind"}, kind `audit` (something was verified) or `audit_idle` (nothing was). Importable from the renderers: it pulls in nothing."""
from __future__ import annotations

from typing import Any

KEY = "hourly_audit"
KEEP = 8                    # the lines an item keeps (the History keeps every one it has shown: it reads the item's revisions)
CLIP = 240                  # one line's text
KIND_OK, KIND_IDLE = "audit", "audit_idle"


def log_of(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The lines written on an item (metadata.hourly_audit.log), oldest first."""
    s = (meta or {}).get(KEY)
    return [x for x in ((s or {}).get("log") or []) if isinstance(x, dict)] if isinstance(s, dict) else []


def note(meta: dict[str, Any], now: float, text: str, kind: str, keep: int = KEEP) -> None:
    """Write a line onto the item's metadata."""
    log = log_of(meta)
    log.append({"at": now, "text": " ".join(str(text).split())[:CLIP], "kind": kind})
    meta[KEY] = {"log": log[-keep:]}


def new_entries(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The lines `after` has that `before` did not (History: one line each)."""
    seen = {(x.get("at"), x.get("text")) for x in log_of(before)}
    return [x for x in log_of(after) if (x.get("at"), x.get("text")) not in seen]
