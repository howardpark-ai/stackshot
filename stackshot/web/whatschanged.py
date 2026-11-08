"""whatschanged.py — the brief's what-changed lines (the design: docs/design).

For 7 days after a deploy that changes a tool's text, the brief carries one line for it, so a session that learned the tools before reads what moved:

    stackshot changed on Tue Mar 3rd: <what>; see docs/design

Nobody writes the <what>. tests/tool_text.snapshot.json holds the text of every tool (its parameters, its description, the labels of the lines it returns), and CI
fails a pull request that changes a tool without it. When the server starts (`record`, called from server.py's start), the snapshot of the checkout it runs is compared
with the copy kept from the last start that changed it, `<paths.state>/tool_text.released.json`: a difference becomes one entry, today's date and the generated summary
(`summarize`), appended to `<paths.state>/tool_text.history.json`, and the copy is replaced. A deploy restarts the server whenever a tool changed, so the start is the
mark of a release; a restart with nothing changed records nothing. The first start with no copy only takes the copy, and seeds the history with the two entries that
were written by hand before the snapshot existed (SEED, two example entries).

An entry shows while its date + 7 days is today or later, and goes by itself after, so nothing is removed or released to take a line away. Newest first. A missing or
unreadable file, or an entry that is not {"date": "YYYY-MM-DD", "text": "…"}, shows nothing: a brief never fails over it. Stdlib and config.py only (render.py, which the
system python runs for the session-start brief, imports this)."""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg

HISTORY = "tool_text.history.json"
RELEASED = "tool_text.released.json"
PATH: Path | None = None            # tests point this at a history file; None = <paths.state>/tool_text.history.json
SHOW_DAYS = 7
PAGE = "docs/design"
MAX_CLAUSES = 8                     # tools named in one line; the rest is "and N more"

# Two example entries, written by hand before the snapshot existed. Only a state with no history yet takes them.
SEED = [
    {"date": "2099-03-03", "text": "notices and replies say mover and keeper of record"},
    {"date": "2099-03-03", "text": "the tools say mover: create takes sender and mover, get leads with mover: and then:, and History writes mover: A → B"},
]


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def day_words(d: dt.date) -> str:
    """A date as people read it: Tue Mar 3rd."""
    return f"{d:%a %b} {_ordinal(d.day)}"


def history_path() -> Path:
    return PATH or _cfg.state(HISTORY)


def entries(path: Path | None = None) -> list[tuple[dt.date, str]]:
    """The history's entries as (date, text), newest first; [] when the file is missing or not a list, and an entry that is not {date, text} is skipped."""
    try:
        data: Any = json.loads((path or history_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[tuple[dt.date, str]] = []
    for e in data if isinstance(data, list) else []:
        try:
            out.append((dt.date.fromisoformat(str(e["date"])), " ".join(str(e["text"]).split()).rstrip(". ")))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted((x for x in out if x[1]), key=lambda x: x[0], reverse=True)


def lines(today: dt.date | None = None, path: Path | None = None) -> list[str]:
    """The lines the brief carries now: one per entry whose date + SHOW_DAYS is today or later (and which is not dated in the future)."""
    today = today or dt.datetime.now(_cfg.tz()).date()
    return [f"stackshot changed on {day_words(d)}: {t}; see {PAGE}" for d, t in entries(path) if d <= today <= d + dt.timedelta(days=SHOW_DAYS)]


# ---------------------------------------------------------------- the summary of a snapshot's change
def _join(names: list[str]) -> str:
    return "/".join(names)


def _param_clauses(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """What changed in a tool's parameters: added, removed, renamed (a removed and an added one of the same type, requiredness and description), changed."""
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    renamed: list[tuple[str, str]] = []
    for r in list(removed):
        for a in list(added):
            if old[r] == new[a]:
                renamed.append((r, a)); removed.remove(r); added.remove(a)
                break
    out = []
    if added:
        out.append(f"parameters added {_join(added)}" if len(added) > 1 else f"parameter added {added[0]}")
    if removed:
        out.append(f"parameters removed {_join(removed)}" if len(removed) > 1 else f"parameter removed {removed[0]}")
    out.extend(f"parameter {r} renamed {a}" for r, a in renamed)
    changed = [f"{p} ({'/'.join(k for k in ('type', 'required', 'default', 'description') if old[p].get(k) != new[p].get(k))})" for p in sorted(set(old) & set(new)) if old[p] != new[p]]
    if changed:
        out.append("parameters changed " + ", ".join(changed))
    return out


def summarize(old: dict[str, Any], new: dict[str, Any]) -> str:
    """One plain line for what differs between two snapshots, "" when nothing does: the tools added or removed, and per tool its parameters (added, removed, renamed,
    changed), whether its description changed, and the labels of its returned lines (added, removed). Tools are sorted by name; the line names at most MAX_CLAUSES of them."""
    ot, nt = old.get("tools") or {}, new.get("tools") or {}
    clauses = []
    if set(nt) - set(ot):
        clauses.append("new tools " + _join(sorted(set(nt) - set(ot))))
    if set(ot) - set(nt):
        clauses.append("tools removed " + _join(sorted(set(ot) - set(nt))))
    for name in sorted(set(ot) & set(nt)):
        o, n = ot[name], nt[name]
        parts = _param_clauses(o.get("parameters") or {}, n.get("parameters") or {})
        if o.get("description") != n.get("description"):
            parts.append("description changed")
        la, lr = sorted(set(n.get("labels") or []) - set(o.get("labels") or [])), sorted(set(o.get("labels") or []) - set(n.get("labels") or []))
        if la:
            parts.append(f"lines added {_join(la)}")
        if lr:
            parts.append(f"lines removed {_join(lr)}")
        if parts:
            clauses.append(f"{name}: " + ", ".join(parts))
    if old.get("instructions") != new.get("instructions"):
        clauses.append("the connector's instructions changed")
    if old.get("resources") != new.get("resources"):
        clauses.append("resources changed")
    if len(clauses) > MAX_CLAUSES:
        clauses = clauses[:MAX_CLAUSES] + [f"and {len(clauses) - MAX_CLAUSES} more"]
    return "; ".join(clauses)


# ---------------------------------------------------------------- the mark of a release
def _write(path: Path, data: Any) -> None:
    """Whole file or none: a reader never sees half a history. The file is 0600, as the state dir's other private writers make theirs (ledger.json, requests.json:
    a temp file from mkstemp, which is 0600 by itself; set again here so that it holds whatever the umask), and the temp file is removed when the write or the
    rename fails, so a failing disk leaves no `.tmp` litter per start."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record(snapshot: Path, today: dt.date | None = None, state_dir: Path | None = None) -> str:
    """The server's start is a release: compare the checkout's snapshot with the copy kept at the last one. Returns what it did, in one line (for the log):
    nothing to compare (no snapshot), the first copy taken, unchanged, or the entry written. A bad file is rebuilt from this snapshot; a write that fails raises (server.py logs it and the start goes on)."""
    state_dir = state_dir or _cfg.state()
    today = today or dt.datetime.now(_cfg.tz()).date()
    try:
        new = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return f"what changed: no snapshot to compare ({e.__class__.__name__})"
    if not isinstance(new, dict):
        return "what changed: no snapshot to compare (not an object)"
    kept, hist = state_dir / RELEASED, state_dir / HISTORY
    try:
        old = json.loads(kept.read_text(encoding="utf-8"))
    except (OSError, ValueError):       # none yet, or one that cannot be read: it is taken again from this snapshot
        old = None
    if not isinstance(old, dict):      # a list or any other shape is not a copy: treated as absent, rebuilt from this snapshot (else every start would fail on it)
        old = None
    if old is None:
        seeded = not hist.exists()
        if seeded:
            _write(hist, SEED)
        _write(kept, new)
        return "what changed: first start with a snapshot: its copy is kept" + (", the history is seeded" if seeded else "")
    if old == new:
        return "what changed: the tools' text is as at the last start"
    text = summarize(old, new)
    try:
        hdata = json.loads(hist.read_text(encoding="utf-8"))
        hdata = hdata if isinstance(hdata, list) else []
    except (OSError, ValueError):
        hdata = []
    entry = {"date": today.isoformat(), "text": text}
    if text and entry not in hdata:     # idempotent: if the copy below fails, the next start (same day) finds this entry and does not add it again
        hdata.append(entry)
        _write(hist, hdata)
    _write(kept, new)
    return f"what changed: {text or 'the snapshot differs but names no tool change'}"
