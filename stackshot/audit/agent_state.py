"""agent_state.py: is a registered agent busy or idle, as the fleet's session manager last told the server (service/agent_state.py, `POST /client/agent-state`).

The hourly audit (audit/hourly.py), the idle hand-over and the busy-hold guard (audit/busy_hold.py) need the mover's state and the subagents it has running. The server reads neither a pane registry nor a
transcript of its own: the machine that runs the panes pushes one snapshot of the whole fleet about every five minutes, and this module reads the last one.

  state_of(name, now, snap, aliases)   -> AgentState(state, why, pane, since, subagents): `busy` or `idle` only when a FRESH snapshot names the agent, says it was read and says so itself; else `unknown` and why
  pane_of(st)                          the pane word the hourly line reads: "busy" for a pane in a turn, the pane's own word otherwise, "" when the state is unknown
  subagents_of(st)                     the subagent entries of a busy agent as the audit ties them: {"id", "description", "brief", "text", "at", "quiet"?, "unreadable"?}
  snapshot()                           the stored snapshot, None when there is none that reads

FAIL CLOSED. A snapshot that is absent, torn, of another schema, older than `MAX_AGE_S` (15 minutes: three missed pushes) or dated ahead of the clock by more than `SKEW_S`, an agent the snapshot does not name, an entry whose
`read` is false and a `state` that is not busy or idle are all UNKNOWN, never idle: the audit then writes its unknown line, flags nothing and hands nothing on. The sender decides the state (busy: the pane is in a turn or a
subagent runs, quiet or unreadable ones included when it counts them; idle: neither), so this module trusts `state` and uses the subagents only for the words a line says and for tying a subagent to an item
(audit/subagent_tie.py). An idle agent has no subagents here: whatever the entry lists is not running as the sender counts it.

Pure but for reading the one file: no ssh, no pane registry, no transcript (the caller may pass the sessions index's other name of the agent as an alias). Stdlib plus the repo's modules."""
from __future__ import annotations

import math
from typing import Any, Iterable, NamedTuple

from stackshot.service import agent_state as _svc

MAX_AGE_S = 15 * 60.0        # a snapshot written longer ago than this says nothing: every agent reads unknown
SKEW_S = 300.0               # a snapshot dated this far ahead of the clock is a skew of clocks, still read; dated further ahead it is no snapshot
BUSY, IDLE, UNKNOWN = "busy", "idle", "unknown"
TURN = "turn"                # the snapshot's word for a pane in a turn
NUMBER_MAX = 1e12            # a time is epoch seconds: a number past this, or not finite, is no time (a hand-edited file may hold -Infinity or a huge integer; reading one never raises)
_UNSET: Any = object()


class AgentState(NamedTuple):
    state: str                       # busy | idle | unknown
    why: str                         # one line: the sender's own, or why the reader could not tell
    pane: str                        # the snapshot's pane word (turn, idle, shell, sleeping), "" when unknown
    since: float                     # the epoch second the sender says the state began, 0.0 when unknown
    subagents: tuple[dict[str, Any], ...]      # a busy agent's listed subagents


def snapshot() -> dict[str, Any] | None:
    """The stored snapshot as the route wrote it, None when there is none that reads."""
    return _svc.load()


def _finite(v: Any) -> float | None:
    """`v` as a float when it is a number that is no bool, finite and no larger than `NUMBER_MAX` in size; else None (a huge integer cannot be converted: OverflowError, read as no number)."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) and abs(f) <= NUMBER_MAX else None


def _unknown(why: str) -> AgentState:
    return AgentState(UNKNOWN, why, "", 0.0, ())


def _find(agents: dict[str, Any], names: Iterable[str]) -> Any:
    """The entry of the first of `names` the snapshot holds, by its name as written and then in any case; None when it holds none."""
    for n in names:
        n = str(n or "").strip()
        if not n:
            continue
        if n in agents:
            return agents[n]
        low = n.casefold()
        for k, v in agents.items():
            if isinstance(k, str) and k.casefold() == low:
                return v
    return None


def state_of(name: str, now: float, snap: Any = _UNSET, aliases: Iterable[str] = ()) -> AgentState:
    """The state of the registered agent `name` at `now` (epoch seconds) by the last snapshot (`snap`, read from the file when not given). `aliases` are other names of the same agent, tried when `name` is not in
    the snapshot. Unknown, with the reason, for everything the module doc lists; busy or idle only for a fresh snapshot whose entry for the agent was read and says so."""
    if snap is _UNSET:
        snap = snapshot()
    if not isinstance(snap, dict) or not isinstance(snap.get("agents"), dict):
        return _unknown("the fleet's session manager has sent no agent state the server can read")
    written = _finite(snap.get("written"))
    if written is None:
        return _unknown("the agent-state snapshot has no time")
    age = now - written
    if age > MAX_AGE_S:
        return _unknown(f"the agent-state snapshot is {int(age // 60)} minutes old (over {int(MAX_AGE_S // 60)})")
    if age < -SKEW_S:
        return _unknown("the agent-state snapshot is dated ahead of the clock")
    a = _find(snap["agents"], (name, *aliases))
    if a is None:
        return _unknown("the agent is not in the agent-state snapshot")
    if not isinstance(a, dict) or a.get("read") is not True:
        return _unknown("the agent's state was not read" + (f": {a['why']}" if isinstance(a, dict) and a.get("why") else ""))
    st = a.get("state")
    if st not in (BUSY, IDLE):
        return _unknown("the agent's state is unknown" + (f": {a['why']}" if a.get("why") else ""))
    subs = a.get("subagents")
    since = a.get("since", 0)
    if _finite(since) is None:
        return _unknown("the agent's entry holds a since that is no time")
    return AgentState(st, str(a.get("why") or ""), str(a.get("pane") or ""), _finite(since) or 0.0,
                      tuple(s for s in subs if isinstance(s, dict)) if st == BUSY and isinstance(subs, list) else ())


def pane_of(st: AgentState) -> str:
    """The pane word of the hourly line: "busy" for a pane in a turn, the pane's own word (idle, shell, sleeping) otherwise, "" for an unknown state (nothing is verified by it)."""
    if st.state == UNKNOWN:
        return ""
    return "busy" if st.pane == TURN else st.pane


def subagents_of(st: AgentState) -> list[dict[str, Any]]:
    """The subagents of a busy agent as the audit ties them (`text` is the description and the brief together); [] for an idle one. Raises ValueError for an unknown state: nothing can be said of it."""
    if st.state == UNKNOWN:
        raise ValueError(st.why)
    out = []
    for s in st.subagents:
        d, b = str(s.get("description") or ""), str(s.get("brief") or "")
        e: dict[str, Any] = {"id": str(s.get("id") or ""), "description": d, "brief": b, "text": f"{d}\n{b}", "at": _finite(s.get("at")) or 0.0}
        if s.get("quiet") is True:
            e["quiet"] = True
        if s.get("unreadable") is True:
            e["unreadable"] = True
        out.append(e)
    return out
