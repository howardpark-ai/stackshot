"""renamed_agents.py — a session sala renamed keeps its old name as an alias, and nothing in stackshot may treat that old name as an agent.

sala lists a renamed session under its new name with the old one in `aliases`. Two things in stackshot read an alias as a live session: the roles file's `live` flag
(anchors.sala_live counts names and aliases, because a roles key is often an alias of a live session), and the project record's pending agents (an agent registered through the
New session form, its page line still owed). A pending agent registered under the old name therefore stayed in its project's record, owing a page line for a name that
names nobody, and the Projects page drew it as a running agent. Three small pieces close that:

  renames_of(rows)   {old name: new name} from the rows of `sala sessions --json`: an alias that is no session's current name and belongs to one session only (names compare case-folded).
  sweep(renames)     settles the pending entry of every old name in the project record, in whichever project holds it (the session may have moved to another project in the same step):
                     dropped when the new name is registered somewhere (a page lists it, or a project's pending map holds it), renamed to the new name in place when it is registered
                     nowhere (so the page line it owes is not lost), skipped for 10 minutes after its `at` (a new session may be registered before sala lists it; the next sweep takes it).
                     Every entry it touches is logged to the server log, with the fields it held. Run on every roles build (server._roles_sync), where sala is read once anyway.
  the roles file     carries `renamed_to` on such a name (anchors.session_roles), and the Projects page leaves a name with `renamed_to` out (ui/render.py agent_live).

The old name stops drawing. The new name draws only when a page lists it or a project's pending map holds it: an old name that is dropped has the new name registered already, and one
that is renamed becomes the pending entry of the new name. A name sala also lists as a current session is never an old name here: a name reused by a new session is that session's.
Stdlib only; projects.py is its one import."""
from __future__ import annotations

import sys
import time
from typing import Any, Callable

from stackshot.projects import projects as _prj


MIN_AGE = 10 * 60       # s: a pending entry registered more recently than this is left for the next sweep


def renames_of(rows: list[dict[str, Any]] | None) -> dict[str, str]:
    """{old name: the name its session has now} from the rows of `sala sessions --json` (anchors.sala_rows). Names compare case-folded. An alias counts when no row carries it as its
    name (a name taken again by a new session is that session's) and only one session lists it (two sessions claiming one old name, however they spell it, leave it unresolved).
    {} for no rows: when sala could not be read nothing is known, so nothing is renamed."""
    if not rows:
        return {}
    rows = [x for x in rows if isinstance(x, dict) and x.get("name")]
    current = {str(x["name"]).casefold() for x in rows}
    seen: dict[str, tuple[str, set[int], str]] = {}         # case-folded alias -> (the alias as written first, the rows that list it, the name of the first)
    for i, x in enumerate(rows):
        for a in x.get("aliases") or []:
            if a and isinstance(a, str) and a.casefold() not in current:
                alias, who, name = seen.get(a.casefold(), (a, set(), str(x["name"])))
                who.add(i); seen[a.casefold()] = (alias, who, name)
    return {alias: name for alias, who, name in sorted(seen.values(), key=lambda v: v[0]) if len(who) == 1}


def sweep(renames: dict[str, str], reg: dict[str, Any] | None = None, now: float | None = None, log: Callable[[str], Any] | None = None) -> list[tuple[str, str, dict[str, Any], str, str]]:
    """Settle the project record's pending entry of every old name in `renames` (see the module text), in whichever project holds it. `reg` = the page registry (the names pages list
    count as registered; None reads it). Each entry dropped or renamed is logged with `log` (default: a line on standard error, the server's log). → projects.settle_renamed_pending's list. A damaged id
    file raises ValueError and nothing is changed (the caller fails open). Cheap when there is nothing to do: one read of the id file under the record's lock."""
    if not renames:
        return []
    reg = _prj.registry() if reg is None else reg
    listed = {str(n) for e in reg.values() if isinstance(e, dict) for n in (e.get("agents") if isinstance(e.get("agents"), dict) else {})}
    done = _prj.settle_renamed_pending(renames, listed, time.time() if now is None else now, MIN_AGE)
    emit = log or (lambda m: print(m, file=sys.stderr, flush=True))
    for pid, name, e, how, new in done:
        if how == "kept":       # registered under ten minutes ago: left for the next sweep, nothing changed, nothing to log
            continue
        emit(f"renamed agent {name!r} -> {new!r} in {pid}: pending entry {how}"
             f" [role={e.get('role')!r} front={e.get('front')!r} mandate_line={e.get('mandate_line')!r} by={e.get('by')!r} at={e.get('at')!r}]")
    return done
