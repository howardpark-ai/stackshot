"""activity.py — the item's `activity` clock: when something real last happened on the work.

The pure half: no server import, no clock read, no file. server._save asks `counts` once per save and stamps the item (`item["activity"]`, epoch seconds, top level
beside `updated` and `confirmed`); a pass that wants "how long has this item been quiet" reads `at`.

Why a clock of its own. `updated` moves for every save, the server's own nudges included, and `confirmed` moves for a bare confirm, so neither can say whether anyone
did anything: a silence check that read them would be reset by its own nudge, and a "still on it" confirm would keep an item fresh without moving it. `activity` moves only
for a write that is about the work:

  counts   a session's write to the item (create, update, a step done or added, a state change, a new next step or description), the owner's answer or comment, a
           message written onto the item, an event on one of its anchors (a pull request, a commit, a CI run: the step-proof saves)
  does not an audit's own write (its agent's, the instance's own name, the migration's, the router's ruling name), a bare confirm (moves `confirmed` and nothing else),
           and the server's own bookkeeping (a wake, an idle mark, a stall or hand-off nudge, a migration, a repair): a save with no writer and no kind

An item saved before the field existed has none: `at` reads its last state change or update, and the first save that does not count seeds the field from what the item
read as before that save, so a nudge on an old item does not become its first activity. No pass rewrites the store for this."""
from __future__ import annotations

from typing import Any, Iterable

FIELD = "activity"

# The kinds a save is filed under (server._save's `activity` argument, else derived from who wrote it).
WRITE = "write"              # a session's (or the owner's) write through a tool: create, update, close
ANSWER = "answer"            # the owner's answer on the board or his comment on GitHub
MESSAGE = "message"          # a message written onto the item as a History line
EVENT = "event"              # an event on an anchor of the item: a pull request merged or released, a step its proof ticked
CONFIRM = "confirm"          # the confirm tool: `confirmed` only
AUDIT = "audit"              # an audit's own write
MIGRATION = "migration"      # a migration or repair pass's write
BOOKKEEPING = "bookkeeping"  # the server's own save with no writer: a wake, an idle mark, a nudge, a settle

COUNTS = frozenset({WRITE, ANSWER, MESSAGE, EVENT})
KINDS = COUNTS | {CONFIRM, AUDIT, MIGRATION, BOOKKEEPING}


def _norm(name: object) -> str:
    return " ".join(str(name or "").split()).casefold()


def audit_writer(writer: str | Iterable[str], audit_names: Iterable[str]) -> bool:
    """Is any of the writer's names (its session name, its id, an author label) one of the audit's own? `audit_names` is the caller's list: the audit agent, the audit's
    push label, the instance's name, the router's ruling name, the migration's label."""
    names = {_norm(n) for n in audit_names if _norm(n)}
    ws = [writer] if isinstance(writer, str) else list(writer)
    return any(_norm(w) in names for w in ws if _norm(w))


def kind_of(writer: str = "", author: tuple[str, str] | None = None, explicit: str = "") -> str:
    """The kind a save is filed under. An explicit kind (a caller that knows: confirm, an anchor event, a message) wins; else the owner's board answer is an answer, any other
    author (the migration's) a migration, a writer a write, and no writer at all the server's own bookkeeping."""
    if explicit:
        if explicit not in KINDS:
            raise ValueError(f"unknown activity kind {explicit!r}")
        return explicit
    if author:
        return ANSWER if author[1] == "board" else MIGRATION
    return WRITE if str(writer or "").strip() else BOOKKEEPING


def counts(kind: str, writer: str | Iterable[str] = "", audit_names: Iterable[str] = ()) -> bool:
    """Does a save of this kind by this writer move the item's activity clock? The one place that decides. An audit's writer never counts, whatever the kind says (an audit
    agent that updates an item is still the audit); a kind outside COUNTS never counts."""
    if kind not in COUNTS:
        return False
    return not audit_writer(writer, audit_names)


def at(item: dict[str, Any] | None) -> float:
    """The time of the item's last real activity: its `activity` stamp, else (an item from before the field) its last state change or update, else 0."""
    it = item or {}
    try:
        v = float(it.get(FIELD) or 0)
    except (TypeError, ValueError):
        v = 0.0
    if v > 0:
        return v
    out = 0.0
    for k in ("state_updated", "updated"):
        try:
            out = max(out, float(it.get(k) or 0))
        except (TypeError, ValueError):
            pass
    return out


def stamp(item: dict[str, Any], before: dict[str, Any] | None, now: float, kind: str, writer: str | Iterable[str] = "", audit_names: Iterable[str] = (),
          when: float | None = None) -> bool:
    """Apply one save to the item: a counting save sets the clock to `now`; any other leaves it, and an item with no clock yet gets one seeded from what it read as
    before this save (`before` = the stored item, else the item itself), so the save that did not count is not its first activity. `when`: the time the activity happened,
    for an event the server reads later (the owner's comment on GitHub, read after a restart): the clock takes it, but never a time after `now` and never one before the clock
    already read, so a backlog read late is not activity now and a clock never goes back. → True when the item's field changed."""
    old = item.get(FIELD)
    if counts(kind, writer, audit_names):
        if when is None:
            item[FIELD] = now
        else:
            try:
                w = float(when)
            except (TypeError, ValueError):
                w = now
            item[FIELD] = max(min(w, now), at(before) if before is not None else 0.0)
    elif not old:
        seed = at(before if before is not None else item)
        if seed > 0:
            item[FIELD] = seed
    return item.get(FIELD) != old
