"""work.py — an item's work lines (the item page shows what is in motion and what is waiting, and for what):
metadata.work, a short list of subtask status lines, each
{id, text, agent, state, ts}. A line is a few words; the details of a subtask stay on the project page. Pure helpers with
no config and no store, shared by the server (the update tool's `work` parameter, the get and brief replies), the renderer
(a row's "engineer: migrating", the item page's list, the History) and the GitHub mirror (the comment of a change)."""
from __future__ import annotations

import json
import re
import time
from typing import Any

STATES = ("defined", "assigned", "in progress", "done")
TEXT_MAX = 40            # a line is a few words
OPEN_MAX = 8             # open (not done) lines per item
DONE_KEEP_S = 24 * 3600  # a done line stays on the list this long; the History keeps it after that
KEYS = ("id", "text", "state", "agent", "remove")
_STATE_ALIAS = {"wip": "in progress", "doing": "in progress", "started": "in progress", "completed": "done", "finished": "done", "todo": "defined", "open": "defined"}
FORM = "{text: a few words, state: defined | assigned | in progress | done, agent: the session doing it}"


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


def lines_of(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """metadata.work as a clean list of {id, text, agent, state, ts}; a misshaped entry is skipped, a missing key or state filled."""
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


def open_lines(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The lines not done, in progress first, then assigned, then defined (each group in its stored order)."""
    rank = {"in progress": 0, "assigned": 1, "defined": 2}
    return sorted([l for l in lines_of(meta) if l["state"] != "done"], key=lambda l: rank.get(l["state"], 3))


def in_progress(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [l for l in lines_of(meta) if l["state"] == "in progress"]


def norm_state(s: Any) -> str:
    """A state as given → one of STATES; ValueError for anything else."""
    t = re.sub(r"[\s_-]+", " ", str(s or "").strip().lower())
    t = _STATE_ALIAS.get(t, t)
    if t not in STATES:
        raise ValueError(f"work: state {str(s)!r} is not one of {', '.join(STATES)}")
    return t


def parse(spec: Any) -> dict[str, Any]:
    """The update tool's `work` argument as given → {id, text, state, agent, remove}, each normalized ("" / False when not
    given). Accepts an object, a JSON string of one (a client whose cached schema sends the parameter as text), or a plain
    string, which is the text of a line to add. ValueError with the hint on anything else."""
    if isinstance(spec, str):
        s = spec.strip()
        if s[:1] == "{":
            try:
                spec = json.loads(s)
            except ValueError:
                raise ValueError(f"work: not valid JSON; pass an object {FORM}, or the text of a new line alone")
        else:
            spec = {"text": s}
    if isinstance(spec, list):
        raise ValueError("work: one line per call, since each change is one line in the item's History; call update once per line")
    if not isinstance(spec, dict):
        raise ValueError(f"work: an object {FORM}; id names a line already there (or give its text again); remove: true drops a line")
    bad = [str(k) for k in spec if k not in KEYS]
    if bad:
        raise ValueError(f"work: unknown key{'s' if len(bad) > 1 else ''} {', '.join(bad)}; the keys are {', '.join(KEYS)}")
    text = re.sub(r"\s+", " ", str(spec.get("text") or "")).strip()
    if len(text) > TEXT_MAX:
        raise ValueError(f"work: a line is a few words, at most {TEXT_MAX} characters ({len(text)} given: \"{text[:TEXT_MAX]}…\"); the details of a subtask stay on the project page")
    out = {"id": str(spec.get("id") or "").strip(), "text": text, "state": norm_state(spec["state"]) if spec.get("state") not in (None, "") else "",
           "agent": str(spec.get("agent") or "").strip(), "remove": bool(spec.get("remove"))}
    if not out["id"] and not out["text"]:
        raise ValueError(f"work: text is the line's few words, nothing to add or find without it (or id names a line already there); {FORM}")
    return out


def live_lines(meta: dict[str, Any] | None, now: float | None = None) -> list[dict[str, Any]]:
    """The lines apply() works on: lines_of without the done lines older than DONE_KEEP_S (they dropped off the list)."""
    now = time.time() if now is None else now
    return [l for l in lines_of(meta) if l["state"] != "done" or now - l["ts"] < DONE_KEEP_S]


def apply(meta: dict[str, Any], spec: dict[str, Any], writer: str = "", now: float | None = None) -> list[dict[str, Any]]:
    """Add, change or remove one line (`spec` from parse()) → the new list for metadata.work. A line is found by its id, else
    by its text (case apart); a new one takes the text. A new line is defined, assigned when it comes with an agent; a line
    moved to in progress without an agent takes the writer; an agent set on a defined line makes it assigned. Done lines
    older than DONE_KEEP_S drop off the list (the History keeps them). ValueError on a refusal, with the hint."""
    now = time.time() if now is None else now
    lines = live_lines(meta, now)
    key, text = spec.get("id") or "", spec.get("text") or ""
    hit = next((l for l in lines if l["id"] == key), None) if key else next((l for l in lines if l["text"].casefold() == text.casefold()), None)
    listed = ", ".join(f"{l['id']} ({l['text']}, {l['state']})" for l in lines) or "none"
    if key and hit is None:
        raise ValueError(f"work: no line {key!r} on this item (its lines: {listed}); give the text of a new line instead")
    if spec.get("remove"):
        if hit is None:
            raise ValueError(f"work: nothing to remove, no line reads \"{text}\" (its lines: {listed})")
        return [l for l in lines if l is not hit]
    if hit is None:
        if len([l for l in lines if l["state"] != "done"]) >= OPEN_MAX:
            raise ValueError(f"work: {OPEN_MAX} open lines already (its lines: {listed}); mark one done or remove one first: a line is a subtask's status, its details stay on the project page")
        state = spec.get("state") or ("assigned" if spec.get("agent") else "defined")
        agent = spec.get("agent") or (writer if state == "in progress" else "")
        return [*lines, {"id": key_of(text, [l["id"] for l in lines]), "text": text, "agent": agent, "state": state, "ts": now}]
    was = dict(hit)
    if key and text and text != hit["text"]:
        hit["text"] = text
    if spec.get("agent") and spec["agent"] != hit["agent"]:
        hit["agent"] = spec["agent"]
        if not spec.get("state") and hit["state"] == "defined":
            hit["state"] = "assigned"
    if spec.get("state"):
        hit["state"] = spec["state"]
        if hit["state"] == "in progress" and not hit["agent"]:
            hit["agent"] = writer
    if {k: v for k, v in hit.items() if k != "ts"} != {k: v for k, v in was.items() if k != "ts"}:
        hit["ts"] = now
    return lines


def changes(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    """What changed between two versions of an item's work list, one readable line each, as the History
    shows it: "work: migrating → in progress (my-engineer)". A done line that aged off the list says nothing."""
    a, b = {l["id"]: l for l in lines_of(before)}, {l["id"]: l for l in lines_of(after)}
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


def short_agent(name: str, prefix: str = "") -> str:
    """An agent's short name on a row: the project name's prefix dropped (my-engineer → engineer); any other name as it is."""
    name, prefix = str(name or ""), str(prefix or "")
    return name[len(prefix) + 1:] if prefix and name.startswith(prefix + "-") and len(name) > len(prefix) + 1 else name


def row_parts(meta: dict[str, Any] | None, prefix: str = "", limit: int = 2) -> tuple[list[tuple[str, str]], int]:
    """What a board row shows of an item's work: the lines in progress, at most `limit`, each (the agent's short name, the
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
    """One line for a tool reply or board.md: the open lines in progress first, each with its state and agent, then the done
    ones still on the list: "migrating the ids — in progress (my-engineer) · tests — defined · done: answer box"."""
    ls = open_lines(meta)
    done = [l["text"] for l in lines_of(meta) if l["state"] == "done"]
    out = " · ".join(f"{l['text']} — {l['state']}" + (f" ({l['agent']})" if l["agent"] else "") for l in ls)
    if done:
        out += (" · " if out else "") + "done: " + ", ".join(done)
    return out
