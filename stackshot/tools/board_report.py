"""tools/board_report.py — the board checks the audit makes: arbitrary on-hold descriptions and mis-labeled status. (Silence, an item on an agent not moving, is the ten-minute silence pass's: silence.py.)

Reads the open items in the store and lists, per item, what the audit is to challenge, each finding naming the item and its mover (so the audit sends it to that mover). Read only: it changes no item, refuses nothing and
needs no server. Stdlib plus the repo's modules, Python 3.11+. Beside tools/next_report.py, which it is modeled on and shares its reader with.

  arbitrary-hold    an item on hold whose hold has no concrete reason: nothing structural holds it (render.hold_whys, the function behind the briefing's "nothing holds it now": an open after item, a pane recycle,
                    needs external, an anchor scoped to it), it has no check, party, words of the owner's (cap_ok, or his name in the wait basis) or wait basis with a real YYYY-MM-DD date (the end of a window the work needs), and the text of its next, steps, wait basis and expected reason names no event it
                    waits for (an item, a PR, a link, "once/when/after/until/waiting on <something>"): only a date, or vague words (later, parked, nothing holds it now)
  mislabeled-state  the stored state does not match what the item's fields say: it differs from the state the fields derive (states.derive; your-step and verifying are stored only, never derived, so they are
                    not compared), or the stored state lacks what it must carry (states.problems: your-call with no ask, outside with no external in needs, blocked with no after), or the item is on hold while its text names the owner's decision (should be your-call) or an outside party (should be outside); that reading of the words is skipped for a hold already labeled outside (external in needs, stored state outside) or on his recorded words (cap_ok)

  tools/board_report.py                 the findings, one line each (id, project, mover, kind, why), then the counts
  tools/board_report.py --line          the one line the audit carries ("Board checks: 3 item(s) · arbitrary-hold 1 · mislabeled-state 2")
  tools/board_report.py --json          {"open", "closed", "items", "kinds": {kind: count of items}, "findings": [{id, project, mover, category, kind, detail}]}
  tools/board_report.py --store DIR     read the items from DIR (a copy of the store) instead of [paths] store

The audit calls it through `audit.py board-check`. Exit 0."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parents[2]
from stackshot.anchors import anchor_scope as _ascope  # noqa: E402  — which anchors count for an item, from every project's page
from stackshot.core import config as _cfg  # noqa: E402
from stackshot.model import model as _model  # noqa: E402
from stackshot.tools import next_report as _nr  # noqa: E402  — the store reader and the id words, shared
from stackshot.web import render as _render  # noqa: E402  — hold_whys: what holds an item on hold (the brief's "nothing holds it now")
from stackshot.waits import server_fixes as _sf  # noqa: E402  — settled_out: words that quote or record a pick already made are no wait on its giver
from stackshot.fleet import sessions_registry as _sr  # noqa: E402
from stackshot.model import states as _states  # noqa: E402
from stackshot.model import steps as _steps  # noqa: E402
from stackshot.waits import waiting as _wt  # noqa: E402

CATEGORY = "board checks"
KINDS = ("arbitrary-hold", "mislabeled-state")
SCRIPT_WRITERS = ("migration", "stackshot")      # a stamp of server code or a one-off script is no session's write (a stamp reading "… via a script on …" is one too)

# What a hold's words may name as the event it waits for. Dates are cut out first (a date alone is no event) and so are the vague words below.
_REF_RX = re.compile(r"(?:\bboard#\d+|\b[a-z]\d{1,4}\b(?=[\s,.;:)]|$)|\bPR\s*#?\d+|(?<!\w)#\d+|https?://\S+|\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b)", re.I)      # an item, a PR, a link, a commit
_EVENT_RX = re.compile(r"\b(?:once|when|after|until|till|waiting\s+(?:for|on)|waits?\s+(?:for|on)|blocked\s+(?:on|by)|depends?\s+on|pending|needs?\s+\S+\s+to|before)\s+(?P<what>[^.;\n]*)", re.I)
_HAPPENS_RX = re.compile(r"(?P<what>[^.;\n]*?)\b(?:ends?|expires?|resets?|arrives?|lands?|finishes|completes?|returns?|is\s+live|goes\s+live|comes\s+back|has\s+(?:run|passed))\b", re.I)      # "<something> ends/resets/expires …": a dated event is still an event
_VAGUE_WORDS = frozenset(("later", "then", "now", "soon", "it", "this", "that", "parked", "park", "hold", "held", "nothing", "holds", "nothing holds it now", "a", "an", "the", "wake", "woken", "tbd", "some", "time", "point", "further", "notice", "again", "to", "is", "be", "and", "or", "of", "for", "on", "in", "at", "by", "so", "up", "date", "day", "days", "week", "weeks", "hours", "weekend", "ready", "done", "needed", "possible"))
_DATE_SRC = r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2})?\b|\b(?:Mon(?:day)?|Tue(?:s(?:day)?)?|Wed(?:nesday)?|Thu(?:r(?:s(?:day)?)?)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)\b|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?\b|\b\d{1,2}(?::\d{2})?\s*(?:am|pm|UTC{ZONE})(?![A-Za-z0-9])|\b\d{1,2}:\d{2}\b|\btomorrow\b|\btoday\b|\bnext\s+(?:week|month|day)\b"      # {ZONE}: the instance timezone's own abbreviations, after a clock time

_DATE_RXS: dict[str, "re.Pattern[str]"] = {}


def _date_rx() -> "re.Pattern[str]":
    """The date words of a line, with a clock time that may name the instance timezone ("9am", "21:00 UTC", "05 +04"); built from the config at each use (cached per set of labels)."""
    zone = "".join("|" + re.escape(x) for x in _cfg.tz_labels())
    if zone not in _DATE_RXS:
        _DATE_RXS[zone] = re.compile(_DATE_SRC.replace("{ZONE}", zone), re.I)
    return _DATE_RXS[zone]


def _owner_alt() -> str:
    """The owner's name and aliases as one regex group, matched case-sensitively and whole (no ASCII word character or hyphen beside them, so `box-a` is not `AE`, while a particle glued after
    a name still matches); `the owner` when no name is set."""
    names = "|".join(re.escape(n) for n in _cfg.owner_names()) or "the owner"
    return r"(?<![A-Za-z0-9_-])(?:" + names + r")(?![A-Za-z0-9_-])"


def _owner_rx() -> "re.Pattern[str]":
    return re.compile(_owner_alt())


def _decision_rx() -> "re.Pattern[str]":
    """A line that says the owner (any of his names) decides, approves or answers, or that a decision waits on him (no bare yes, no, say or call: they read in many other senses). The names match
    case-sensitively, the verbs in any case."""
    o = _owner_alt()
    return re.compile(r"(?:" + o + r"[^.;\n]{0,50}(?i:\b(?:decid\w*|decision|approv\w*|pick\w*|choose|chooses|answer\w*|go-?ahead|sign\w*|says|confirm\w*)\b)"
                      r"|(?i:\b(?:decision|approval|go-?ahead|answer|sign-?off)\b[^.;\n]{0,25}\b(?:from|of|by)\s+)" + o +
                      r"|(?i:\bwaiting\s+(?:on|for)\s+)" + o + r")")
_OUTSIDE_RX = re.compile(r"(?:\bouter\b|\boutside\s+(?:party|the\s+perimeter)\b|\bthird[- ]party\b|\bvendor\b|\bcustomers?\b|\bsupport\s+ticket\b|\btheir\s+(?:reply|answer|response)\b|\b(?:wait(?:ing|s)?\s+(?:for|on)\s+)(?:a\s+|the\s+|an\s+)?(?:reply|response|answer)\s+from\b)", re.I)


def _last_write(item: dict[str, Any]) -> float:
    """When a session or the owner last wrote the item, as an epoch (0.0 = unknown). `written_at` is the stamp only such a write sets (`writes.record_writer` in service/writes.py: a wake, an idle mark or a server save leaves it alone); a stamp of the
    migration or a script is no session's write, so for those, and for an item with no stamp, the item's own clock `updated` stands in (a server save can move it, which can only hide an idle item, never invent one)."""
    who = str(item.get("written_by") or "").lower()
    ts = _nr._float(item.get("written_at"))
    if ts > 0 and who and not any(who == w or who.startswith(w + " ") or " via a script" in who for w in SCRIPT_WRITERS):
        return ts
    return _nr._float(item.get("updated")) or ts


def fallback_mover(project: str) -> str:
    """The session that moves an item nothing else names a mover for: the project's builder, else its -main agent, read from the project registry as server._fallback_mover does, without that
    function's last step, the page keeper (server.py is not importable here). "" when the project names neither."""
    try:
        from stackshot.anchors import anchors as _anc  # noqa: PLC0415
        from stackshot.router import router_live as _rl  # noqa: PLC0415
        return _rl.builder(project) or _anc.fallback_main(project) or ""
    except Exception:  # noqa: BLE001
        return ""


def install_fallback() -> None:
    """The CLI runs without the server, which installs waiting.FALLBACK_MOVER; install the same lookup here unless one is there (a test's, or the server's)."""
    if _wt.FALLBACK_MOVER is None:
        _wt.FALLBACK_MOVER = fallback_mover


def _label(who: str) -> str:
    return (_sr.display_name(who) or who) if who else ""


def mover_of(item: dict[str, Any], after_open: Callable[[dict[str, Any]], Any] | None = None) -> str:
    """Who moves the item now, as a name: the model's mover while it is alive, the post-wake mover while it waits (a held item's session), the stored mover or the project's fallback otherwise."""
    try:
        mod = _model.derive(item, None, after_open)
        who = mod.mover if mod.state == _model.ALIVE else (mod.wait.mover if mod.wait else "")
    except Exception:  # noqa: BLE001
        who = ""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    who = who or _model.clean(meta.get("mover")) or _wt.mover_of(meta)["who"]
    return who if _model.is_owner(who) else _label(who)


def _texts(item: dict[str, Any]) -> list[str]:
    """The words a hold may give its reason in: the wait basis, the expected reason, next and the open steps (first lines, the item's own words only)."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    out = [_wt.basis_of(meta), str(meta.get("expected_reason") or ""), str(meta.get("watch_reason") or "")]
    out += [_steps.first_line(s["text"]) for s in _steps.view(meta, keeper=str(meta.get("owner") or "")) if s["status"] == _steps.OPEN]
    out.append(_steps.first_line(meta.get("next")))
    return [" ".join(t.split()) for t in out if t and t.strip()]


def names_event(text: str) -> bool:
    """Does a hold's text name an event it waits for: an item, a PR, a link or a commit, or a wait word (once, when, after, until, waiting on, depends on …) followed by words that are more than a date or a vague word."""
    t = " ".join(str(text or "").split())
    if _REF_RX.search(t):
        return True
    for m in _EVENT_RX.finditer(_date_rx().sub(" ", t)):
        what = [w for w in re.findall(r"[A-Za-z][\w'-]*", m.group("what")) if w.lower() not in _VAGUE_WORDS]
        if what:
            return True
    for m in _HAPPENS_RX.finditer(_date_rx().sub(" ", t)):
        if [w for w in re.findall(r"[A-Za-z][\w'-]*", m.group("what")) if w.lower() not in _VAGUE_WORDS]:
            return True
    return False


def dated_basis(meta: dict[str, Any]) -> bool:
    """Does the item's wait basis (the one written for its current wake) carry a real calendar date as YYYY-MM-DD? 2026-02-30 is not one."""
    for x in _wt._ISO_RX.findall(_wt.basis_of(meta)):
        try:
            dt.date.fromisoformat(x)
        except ValueError:
            continue
        return True
    return False


def _structural(item: dict[str, Any], row: dict[str, Any], item_anchors: list[dict[str, Any]]) -> list[str]:
    """What holds the held item besides its words: render.hold_whys (open after item, pane recycle, needs external, an anchor scoped to it), plus a check, a named party, a
    stored wait kind (item, anchor or relay: something outside arrives), the owner's name in the wait basis or his recorded words for the wake (cap_ok), and a wait basis that carries a real
    YYYY-MM-DD date (the end of a window the work itself needs, "the sample window ends 2099-01-04"; the server stores one only for a hold or a wake it accepted on that date)."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    why = list(_render.hold_whys(row, item_anchors))
    if _model.clean(meta.get("check")):
        why.append("a check")
    if _model.clean(meta.get("party")):
        why.append("an outside party named")
    if _model.clean(meta.get("wait_kind")).lower() in ("item", "anchor", "relay"):
        why.append("a wait kind")
    if _owner_rx().search(_wt.basis_of(meta)):
        why.append("his word in the wait basis")
    if dated_basis(meta):
        why.append("a dated wait basis")
    if _wt.words_of(meta):
        why.append("his words for the wake")
    return why


def _wake_words(meta: dict[str, Any]) -> str:
    from stackshot.waits import waiting as _wt  # noqa: PLC0415
    return f"{'until' if _wt.stored_until(meta) else 'wake'} {_wt.wake_value(meta)}" if _wt.wake_value(meta) else "no wake date"


def check_item(item: dict[str, Any], gid: str, items: dict[str, dict[str, Any]], anchors: dict[str, Any], now: float) -> list[tuple[str, str]]:
    """[(kind, what is wrong)] for one OPEN item in KINDS order; [] for a closed item or one that passes both."""
    if item.get("status") != "open":
        return []
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}

    def after_open(it: dict[str, Any]) -> list[str]:
        return [g for g in _wt.after_of(it.get("metadata") or {}) if (items.get(g) or {}).get("status") == "open"]
    held = _wt.is_held(item)
    out: list[tuple[str, str]] = []
    stored = _states.stored(item)
    derived = _states.derive(item, after_open)
    mismatch = bool(stored and stored not in ("your-step", "verifying") and derived != stored)
    # --- arbitrary-hold
    if held:
        proj = _render.proj_key({"metadata": meta})
        row = {**item, "gid": gid, "L": gid[:1], "metadata": meta, "_after": after_open(item)}
        item_anchors = _ascope.anchor_scope(anchors or {}, gid, proj)      # scoped to the item on any project's page
        why = _structural(item, row, item_anchors)
        texts = _texts(item)
        if not why and not any(names_event(t) for t in texts):
            said = _nr._clip(next((t for t in texts if t), ""), 70)
            out.append(("arbitrary-hold", f"on hold with {_wake_words(meta)}; nothing holds it (no open after, check, outside party or anchor) and its words name no event" + (f": {said}" if said else " (it has none)")))
    # --- mislabeled-state
    probs: list[str] = []
    if mismatch:
        probs.append(f"stored state {stored}, but its fields read as {derived}" + (" (it is on hold)" if held and stored == "doing" else ""))
    if stored in ("your-call", "outside", "blocked"):
        for p in _states.problems(meta, stored, dt.datetime.fromtimestamp(now, _cfg.tz()).date(), check_dates=False):
            if p.startswith(("ask=", "needs including", "after=")):
                probs.append(f"stored state {stored} lacks {p}")
    labeled = "external" in [x.lower() for x in _wt.needs_of(meta)] or stored == "outside" or bool(_wt.words_of(meta))      # a hold already labeled outside, or on his recorded words, is not second-guessed from its text
    if held and not probs and not labeled:
        text = " ".join(_texts(item))
        if _decision_rx().search(_sf.settled_out(text, _sf.owner_names())):      # a quoted span or a pick he already made is no wait on him (server_fixes.settled_out)
            probs.append(f"on hold while its words wait on {_cfg.owner()}'s decision: that is your-call, not a hold")
        elif _OUTSIDE_RX.search(text):
            probs.append("on hold while its words wait on an outside party: that is outside (needs external, party, chase), not a hold")
    for p in probs:
        out.append(("mislabeled-state", p))
    order = {k: i for i, k in enumerate(KINDS)}
    return sorted(out, key=lambda x: order.get(x[0], 9))


def load_anchors(store: Path | None = None) -> dict[str, Any]:
    try:
        d = json.loads(((store or _cfg.path("paths", "store")) / "anchors.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def scan(items: dict[str, dict[str, Any]], anchors: dict[str, Any] | None = None, now: float | None = None) -> dict[str, Any]:
    """{"open", "closed", "items" (with a finding), "kinds": {kind: count of items}, "findings": [{id, project, mover, category, kind, detail}]}. Reads only."""
    now = time.time() if now is None else now
    anchors = anchors or {}

    def after_open(it: dict[str, Any]) -> list[str]:
        return [g for g in _wt.after_of(it.get("metadata") or {}) if (items.get(g) or {}).get("status") == "open"]
    findings: list[dict[str, str]] = []
    kinds = {k: 0 for k in KINDS}
    n_open = n_closed = n_items = 0
    for gid in sorted(items, key=_nr.num):
        it = items[gid]
        if it.get("status") != "open":
            n_closed += 1
            continue
        n_open += 1
        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        hits = check_item(it, gid, items, anchors, now)
        if hits:
            n_items += 1
        seen: set[str] = set()
        for kind, detail in hits:
            if kind not in seen:
                kinds[kind] += 1
                seen.add(kind)
            findings.append({"id": _nr.shown(gid), "project": str(meta.get("project") or ""), "mover": mover_of(it, after_open), "category": CATEGORY, "kind": kind, "detail": detail})
    return {"open": n_open, "closed": n_closed, "items": n_items, "kinds": kinds, "findings": findings}


def line(rep: dict[str, Any]) -> str:
    if not rep["items"]:
        return "Board checks: no open item is held for no reason or in the wrong state"
    per = " · ".join(f"{k} {n}" for k, n in rep["kinds"].items())
    return f"Board checks: {rep['items']} item(s) · {per}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="The open items that are held for no concrete reason or carry the wrong state (read only).")
    ap.add_argument("--line", action="store_true", help="the one line of counts the audit carries")
    ap.add_argument("--json", action="store_true", help="the report as JSON")
    ap.add_argument("--store", help="read the items from this folder (a copy of the store) instead of [paths] store")
    a = ap.parse_args(argv)
    store = Path(a.store).expanduser() if a.store else None
    if store is not None and not store.is_dir():
        print(f"--store {store}: not a folder", file=sys.stderr)
        return 2
    install_fallback()
    rep = scan(_nr.load_all(store), load_anchors(store))
    if a.json:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
    elif a.line:
        print(line(rep))
    else:
        for f in rep["findings"]:
            print(f"{f['id']} | {f['project'] or '-'} | mover {f['mover'] or '-'} | {f['kind']} | {f['detail']}")
        print()
        print(f"{line(rep)} (of {rep['open']} open; {rep['closed']} closed left as they are; read only)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
