"""work.py — a step's status line: where the session that holds a step of an item is with it.

An item has one list, its checklist (`next`, steps.py). A step is a stage of the work ("stage 11: PR 83 up"), not a status. What changes while the stage
is under way (a pull request is up, a review is running, a release is going out) is the step's status line, `tag` on the step: {text, state, ts}, a few
words and a state. The update tool's `work` parameter writes it: it changes the status line of the sender's first open step in place, so a long job keeps one
line on the page, and marking the step done (done=[n], or work with state done) ticks the step. The sender with no open step gets one made from the text.

Pure helpers with no config and no store, shared by the server (the update tool, the get and brief replies), the renderer (a row's "engineer: migrating", the
item page's Next and History) and the audits (a status line in progress is a build subagent at work on the item).

READ-COMPAT. Before the migration (tools/migrate_work_to_steps.py) an item may still carry the old `metadata.work` list, {id, text, agent, state, ts} lines. Every reader goes
through `lines_of`, which gives those lines as they are beside the status lines of the open steps, so a release is safe in either order; the writer never adds to the old list."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from stackshot.model import nextlines as _nl
from stackshot.model import steps as _steps

STATES = ("defined", "assigned", "in progress", "done")
TEXT_MAX = 40            # a status line is a few words
KEYS = ("text", "state", "agent", "remove")      # `id` named a line of the old list: a non-empty one is refused with the way in (a client with a cached schema must not tick a whole step by it); an empty one is ignored
_STATE_ALIAS = {"wip": "in progress", "doing": "in progress", "started": "in progress", "completed": "done", "finished": "done", "todo": "defined", "open": "defined"}
FORM = "{text: a few words (at most 40 characters), state: in progress | done}"


def _ts(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def key_of(text: str, taken: list[str] | tuple[str, ...] | set[str] = ()) -> str:
    """A line's key from its words: "migrating the ids" → migrating-the-ids (at most 24 characters, unique among `taken`)."""
    base = "-".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))[:24].rstrip("-") or "line"
    key, n = base, 1
    while key in taken:
        n += 1; key = f"{base}-{n}"
    return key


# ---------------------------------------------------------------------------------------------------------------- reading
def legacy_lines(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """metadata.work, the old list, as a clean list of {id, text, agent, state, ts}; a misshaped entry is skipped, a missing key or state filled."""
    v = (meta or {}).get("work")
    out: list[dict[str, Any]] = []
    if not isinstance(v, list):
        return out
    for x in v:
        if not isinstance(x, dict):
            continue
        text = re.sub(r"\s+", " ", str(x.get("text") or "")).strip()
        if not text:
            continue
        st = str(x.get("state") or "defined").strip().lower()
        out.append({"id": str(x.get("id") or "").strip() or key_of(text, [o["id"] for o in out]), "text": text,
                    "agent": str(x.get("agent") or "").strip(), "state": st if st in STATES else "defined", "ts": _ts(x.get("ts"))})
    return out


def step_lines(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The status lines of an item's open steps, as {id, text, agent, state, ts, step}: the step's status line, the session the step names as `agent`, `step` the step's first line.
    Read through steps.view (the creator as keeper), so a step whose line left next without a mark reads as dropped there and shows on no row and holds no running-subagent check: a status line is of a step to do."""
    out: list[dict[str, Any]] = []
    for s in _steps.view(meta):
        t = _steps.tag_of(s)
        if s["status"] != _steps.OPEN or t is None:
            continue
        out.append({"id": _steps.key(s["text"]), "text": t["text"], "agent": _steps.opener(s["text"]), "state": t["state"], "ts": t["ts"], "step": _steps.first_line(s["text"])})
    return out


def lines_of(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """What is in motion on an item: the status lines of its open steps, and any line of the old `work` list the migration has not moved yet."""
    return [*step_lines(meta), *legacy_lines(meta)]


def open_lines(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The lines not done, in progress first, then assigned, then defined (each group in its stored order)."""
    rank = {"in progress": 0, "assigned": 1, "defined": 2}
    return sorted([l for l in lines_of(meta) if l["state"] != "done"], key=lambda l: rank.get(l["state"], 3))


def in_progress(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [l for l in lines_of(meta) if l["state"] == "in progress"]


def short_agent(name: str, prefix: str = "") -> str:
    """An agent's short name on a row: the project name's prefix dropped (my-engineer → engineer); any other name as it is."""
    name, prefix = str(name or ""), str(prefix or "")
    return name[len(prefix) + 1:] if prefix and name.startswith(prefix + "-") and len(name) > len(prefix) + 1 else name


def row_parts(meta: dict[str, Any] | None, prefix: str = "", limit: int = 2) -> tuple[list[tuple[str, str]], int]:
    """What a board row shows of an item's work: the status lines in progress, at most `limit`, each (the agent's short name, the
    text), and how many open lines are not shown ("+N")."""
    ip = in_progress(meta)
    shown = [(short_agent(l["agent"], prefix), l["text"]) for l in ip[:limit]]
    return shown, len(open_lines(meta)) - len(shown)


def row_words(meta: dict[str, Any] | None, prefix: str = "", limit: int = 2) -> str:
    """The row's words: "engineer: migrating · board: answer box +1"; "" with nothing in progress."""
    shown, more = row_parts(meta, prefix, limit)
    if not shown:
        return ""
    return " · ".join(f"{a}: {t}" if a else t for a, t in shown) + (f" +{more}" if more > 0 else "")


def words(meta: dict[str, Any] | None) -> str:
    """One line for a tool reply or board.md: the open status lines, in progress first, each with its state and the session it belongs to: "PR 83 up — in progress (my-engineer) · tests — defined"."""
    ls = open_lines(meta)
    done = [l["text"] for l in legacy_lines(meta) if l["state"] == "done"]
    out = " · ".join(f"{l['text']} — {l['state']}" + (f" ({l['agent']})" if l["agent"] else "") for l in ls)
    if done:
        out += (" · " if out else "") + "done: " + ", ".join(done)
    return out


# ---------------------------------------------------------------------------------------------------------------- writing
def norm_state(s: Any) -> str:
    """A state as given → one of STATES; ValueError for anything else."""
    t = re.sub(r"[\s_-]+", " ", str(s or "").strip().lower())
    t = _STATE_ALIAS.get(t, t)
    if t not in STATES:
        raise ValueError(f"work: state {str(s)!r} is not one of {', '.join(STATES)}")
    return t


def parse(spec: Any) -> dict[str, Any]:
    """The update tool's `work` argument as given → {text, state, agent, remove}, each normalized ("" / False when not given). Accepts an object, a JSON string of one (a client whose
    cached schema sends the parameter as text), or a plain string, which is the text of the status line. ValueError with the hint on anything else."""
    if isinstance(spec, str):
        s = spec.strip()
        if s[:1] == "{":
            try:
                spec = json.loads(s)
            except ValueError:
                raise ValueError(f"work: not valid JSON; pass an object {FORM}, or the text of the status line alone")
        else:
            spec = {"text": s}
    if isinstance(spec, list):
        raise ValueError("work: one status line per call, since each change is one line in the item's History; call update once per line")
    if not isinstance(spec, dict):
        raise ValueError(f"work: an object {FORM}; it sets the status line of your open step; remove: true clears it")
    if str(spec.get("id") or "").strip():
        raise ValueError(f"work: `id` named a line of the old Work list, which is gone; a status belongs to your open step. Use done=[n] to tick a step, or send a status on your step: {FORM}")
    bad = [str(k) for k in spec if k not in KEYS and k != "id"]      # an empty `id` (checked above) is let through and ignored
    if bad:
        raise ValueError(f"work: unknown key{'s' if len(bad) > 1 else ''} {', '.join(bad)}; the keys are {', '.join(KEYS)}")
    text = re.sub(r"\s+", " ", str(spec.get("text") or "")).strip()
    if len(text) > TEXT_MAX:
        raise ValueError(f"work: a status line is a few words, at most {TEXT_MAX} characters ({len(text)} given: \"{text[:TEXT_MAX]}…\"); the details of a stage stay on the project page")
    out = {"text": text, "state": norm_state(spec["state"]) if spec.get("state") not in (None, "") else "",
           "agent": str(spec.get("agent") or "").strip(), "remove": bool(spec.get("remove"))}
    if not out["text"] and not out["state"] and not out["remove"]:
        raise ValueError(f"work: text is the status line's few words (or state alone, to move the line you have); {FORM}")
    return out


def _same(a: Any, b: Any) -> bool:
    return bool(a) and str(a).casefold() == str(b).casefold()


def step_of(steps: list[dict[str, Any]], agent: str, same: Callable[[Any, Any], bool] | None = None) -> int:
    """The position (0-based, in the checklist) of the first open step that opens with `agent`'s name, -1 when it has none. `same(a, b)` says whether two names are one session."""
    same = same or _same
    for i, s in enumerate(steps):
        if s["status"] == _steps.OPEN:
            nm = _steps.opener(s["text"])
            if nm and same(nm, agent):
                return i
    return -1


def apply(step: dict[str, Any], spec: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """The step with its status line set from `spec` (from parse()): text and state given replace the line; a state alone moves the line it has (a step with none takes the step's own
    first words); remove drops it. A new line is in progress unless the spec says otherwise. The line's time moves when its text or state changes. Returns a new dict."""
    now = time.time() if now is None else now
    out = dict(step)
    if spec.get("remove"):
        out.pop(_steps.TAG, None)
        return out
    cur = _steps.tag_of(step)
    text = spec.get("text") or (cur["text"] if cur else _steps.strip_opener(_steps.first_line(step["text"]))[:TEXT_MAX])
    state = spec.get("state") or (cur["state"] if cur else "in progress")
    if cur and cur["text"] == text and cur["state"] == state:
        return out
    out[_steps.TAG] = {"text": text, "state": state, "ts": now}
    return out


# ---------------------------------------------------------------------------------------------------------------- History
def tag_events(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The status-line changes between two versions of an item's metadata, one per step whose line changed: {key, step (its first line), agent, text, state, ts, removed}. Steps are matched by
    their words (steps.key); a step that left next unmarked has no event."""
    pv = {_steps.key(s["text"]): _steps.tag_of(s) for s in _steps._valid((before or {}).get("steps"))}
    out = []
    for s in _steps._valid((after or {}).get("steps")):
        k, t = _steps.key(s["text"]), _steps.tag_of(s)
        old = pv.get(k)
        if t is None and old is None:
            continue
        if t is not None and old is not None and (t["text"], t["state"]) == (old["text"], old["state"]):
            continue
        out.append({"key": k, "step": _steps.first_line(s["text"]), "agent": _steps.opener(s["text"]), "text": (t or old)["text"], "state": (t or {}).get("state", ""),
                    "ts": (t or {}).get("ts", 0.0), "removed": t is None})
    return out


def say(ev: dict[str, Any], agent: str = "") -> str:
    """One status-line change as a line of text: "status: PR 83 up · in progress (my-engineer)"."""
    ag = f" ({agent})" if agent else ""
    return f"status: {ev['text']} cleared" if ev.get("removed") else f"status: {ev['text']} · {ev['state']}{ag}"


def legacy_changes(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    """What changed between two versions of an item's old `work` list, one readable line each, as the History shows it: "work: migrating → in progress (my-engineer)". The list leaving whole
    (the migration moved it onto the steps) says nothing, and a done line that aged off says nothing."""
    if (after or {}).get("work") is None and (before or {}).get("work") is not None:
        return []
    a, b = {l["id"]: l for l in legacy_lines(before)}, {l["id"]: l for l in legacy_lines(after)}
    out = []
    for k, l in b.items():
        p = a.get(k)
        ag = f" ({l['agent']})" if l["agent"] else ""
        if p is None:
            out.append(f"work: {l['text']} · {l['state']}{ag}")
            continue
        if p["text"] != l["text"]:
            out.append(f"work: {p['text']} → \"{l['text']}\"")
        if p["state"] != l["state"]:
            out.append(f"work: {l['text']} → {l['state']}{ag}")
        elif p["agent"] != l["agent"]:
            out.append(f"work: {l['text']} → {l['agent'] or 'no agent'} ({l['state']})")
    out += [f"work: {p['text']} removed" for k, p in a.items() if k not in b and p["state"] != "done"]
    return out


def changes(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    """What changed between two versions of an item's status lines, one readable line each, as a reply and the text History say it: the steps' status lines
    ("status: PR 83 up · in progress (my-engineer)") and, for an item that still carries the old list, its lines (legacy_changes)."""
    return [say(e, e["agent"]) for e in tag_events(before, after)] + legacy_changes(before, after)


def closed_steps(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[tuple[str, str]]:
    """The steps a write marked done or dropped, between two versions of an item's metadata: open in `before`, marked in `after` → (steps.key, the stored status, "done" or "dropped").
    The mark is read from the stored step, so a close that marks the open steps itself (dropped, superseded) says dropped."""
    pv = {_steps.key(s["text"]): s["status"] for s in _steps._valid((before or {}).get("steps"))}
    return [(_steps.key(s["text"]), s["status"]) for s in _steps._valid((after or {}).get("steps")) if s["status"] != _steps.OPEN and pv.get(_steps.key(s["text"])) == _steps.OPEN]


# ---------------------------------------------------------------------------------------------------------------- migration
def fold_legacy(meta: dict[str, Any], now: float | None = None, same: Callable[[Any, Any], bool] | None = None, keeper: str = "") -> tuple[dict[str, Any], list[str]]:
    """The old `work` list moved onto the checklist → (the new metadata, notes on what was made); `meta` is not changed. The lines go oldest first. A done line becomes a done step of its
    own (`<agent>: <text>`, by its agent, at its time, its status line done): the fold of finished steps. Of the other lines (defined / assigned / in progress) only the newest of each agent
    stays live (the newest by its time, the last in the list when the times tie): it becomes the status line of its agent's first open step that has none yet, or, when the agent has no such
    step, a new open step added to next for it (`<agent>: <text>`). Every older such line of the agent is an earlier status of the same job, superseded by the newest, and becomes a done step
    of its own like a done line (note `superseded line ... -> a done step`). A line with no agent belongs to the item's mover, else the first session its needs name, else
    the creator. The `work` field is dropped. Pure and idempotent: with no `work` field the metadata comes back as it was."""
    m = json.loads(json.dumps(meta))
    notes: list[str] = []
    if "work" not in m:
        return m, notes
    lines = sorted(legacy_lines(m), key=lambda l: l["ts"])
    keeper = keeper or str(m.get("owner") or "")
    fallback = str(m.get("mover") or "") or next((str(x) for x in (m.get("needs") or []) if isinstance(x, str) and x.lower() not in ("decision", "external")), "") or keeper
    eq = same or _same
    steps = _steps.view(m, keeper=keeper)
    pos = next((j for j, s in enumerate(steps) if s["status"] == _steps.OPEN), len(steps))      # finished steps go before the open ones, oldest first: the checklist reads in the order things happened
    live: dict[str, int] = {}      # per agent, the index (in `lines`) of its newest line that is not done: the only one that stays live
    for n, l in enumerate(lines):      # `lines` is sorted by time (stable), so the last of an agent is the newest, and the last in the list when the times tie
        if l["state"] != "done":
            live[(l["agent"] or fallback).casefold()] = n
    for n, l in enumerate(lines):
        agent = l["agent"] or fallback
        text = l["text"][:TEXT_MAX]
        label = f"{agent}: " if agent else ""
        if l["state"] == "done" or live.get(agent.casefold()) != n:
            steps.insert(pos, {**_steps._step(f"{label}{l['text']}", _steps.DONE, agent, l["ts"]), _steps.TAG: {"text": text, "state": "done", "ts": l["ts"]}})
            pos += 1
            notes.append(f"{'done' if l['state'] == 'done' else 'superseded'} line \"{text}\" -> a done step")
            continue
        i = next((j for j, s in enumerate(steps) if s["status"] == _steps.OPEN and _steps.tag_of(s) is None and _steps.opener(s["text"]) and eq(_steps.opener(s["text"]), agent)), -1)
        if i >= 0:
            steps[i] = {**steps[i], _steps.TAG: {"text": text, "state": l["state"], "ts": l["ts"]}}
            notes.append(f"line \"{text}\" -> the status of step {i + 1}")
            continue
        m["steps"] = _steps.stored(steps)
        _nl.append(m, f"{label}{l['text']}", agent or keeper, keeper)
        steps = _steps.view(m, keeper=keeper)
        j = next(j for j in range(len(steps) - 1, -1, -1) if steps[j]["status"] == _steps.OPEN)
        steps[j] = {**steps[j], _steps.TAG: {"text": text, "state": l["state"], "ts": l["ts"]}}
        notes.append(f"line \"{text}\" -> a new open step (no open step of {agent or 'its agent'} without a status)")
    m["steps"] = _steps.stored(steps)
    m.pop("work", None)
    return m, notes
