"""hourly_log.py: the hourly audit lines an item carries, kept apart from the ladder's own (`metadata.stall.log`).

The pure half of audit/hourly.py: no server import, no clock read, no file. The lines are an item's History (one line each, "stackshot: Audit hh:mm: …"), written in a log of their own,
`metadata.hourly_audit.log`, so they neither crowd out the stall ladder's last eight entries nor read as steps of the stall pass (`get` prints them with an `audit:` prefix, not `stall:`).
Each entry is {"at", "text", "kind"} (and `"pane_only": true` on a line whose only verification was a busy pane), kind `audit` (something was verified), `audit_idle` (nothing was) or `audit_unknown` (the audit could not tell: a running subagent of the mover is tied to no item, or the mover's subagents could not be read;
the item is not idle and nothing is stamped). Importable from the renderers: it pulls in nothing."""
from __future__ import annotations

from typing import Any

KEY = "hourly_audit"
KEEP = 8                    # the lines an item keeps (the History keeps every one it has shown: it reads the item's revisions)
MAX_AT = 1e11                # a time past the year 5000 is no time (datetime cannot print 1e30 or inf)
CLIP = 240                  # one line's text
KIND_OK, KIND_IDLE, KIND_UNKNOWN = "audit", "audit_idle", "audit_unknown"


def _well_formed(x: Any) -> bool:
    """An entry the renderers can print: a dict with a finite time a date can be made of (not a bool) and a text that is a string. A torn one (a bad write, a hand edit) is left out, never raised on."""
    at = x.get("at") if isinstance(x, dict) else None
    return isinstance(x.get("text") if isinstance(x, dict) else None, str) and isinstance(at, (int, float)) and not isinstance(at, bool) and abs(at) < MAX_AT      # NaN fails the comparison too


def log_of(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The lines written on an item (metadata.hourly_audit.log), oldest first; a torn entry (no text, a time that is not a number or no date) is left out."""
    s = (meta or {}).get(KEY)
    return [x for x in ((s or {}).get("log") or []) if _well_formed(x)] if isinstance(s, dict) else []


def note(meta: dict[str, Any], now: float, text: str, kind: str, keep: int = KEEP, pane_only: bool = False) -> None:
    """Write a line onto the item's metadata. `pane_only` marks a line that verified nothing but a busy pane (audit/busy_tell.py reads it): the entry then carries `"pane_only": true`; any other entry has no such key."""
    log = log_of(meta)
    entry: dict[str, Any] = {"at": now, "text": " ".join(str(text).split())[:CLIP], "kind": kind}
    if pane_only:
        entry["pane_only"] = True
    log.append(entry)
    meta[KEY] = {"log": log[-keep:]}


def new_entries(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The lines `after` has that `before` did not (History: one line each)."""
    seen = {(x.get("at"), x.get("text")) for x in log_of(before)}
    return [x for x in log_of(after) if (x.get("at"), x.get("text")) not in seen]
