"""brief.py: the `brief` tool: the board at a glance for a session."""
from __future__ import annotations

import json
import re

from stackshot.core import config as _cfg, instance as _inst
from stackshot.core.instance import OWNER
from stackshot.core.store import _item_files
from stackshot.github import ghsync as _gh
from stackshot.model import item_project as _ip, model as _model
from stackshot.service import telling as _telling
from stackshot.service.store import _legacy_hold, _load
from stackshot.waits import watchers as _watch
from stackshot.web import whatschanged as _wc
from stackshot.web.auth import oauth as _oauth
from stackshot.web.page_debts import _nag
from stackshot.web.tools.text import _lead, load_text

_T = load_text("brief", {"BOARD_URL": str(_inst.BOARD_URL)})

_fmt = None      # set by register: the server's own, looked up at each call
_handoff_brief = None      # set by register: the server's own, looked up at each call
_is_parked = None      # set by register: the server's own, looked up at each call
_model_report_line = None      # set by register: the server's own, looked up at each call


def _world_waits_text() -> str:
    """The brief's "Waiting on the world" (design section 4): the open items whose stored wait is news only the owner relays, one line each (what, ask-by date, chases), the earliest
    ask-by first. "" when none, or the watchers are off: a brief never fails over it."""
    if not _watch.enabled():
        return ""
    rows: list[tuple[str, str]] = []
    stuck: list[str] = []
    for gid, _p in _item_files():
        try:
            it = _load(gid)
            m = it.get("metadata") or {}
            if it.get("status") != "open" or not _watch.stored_kind(m):
                continue
            if _watch.stored_kind(m) == "relay":
                rows.append((_model.clean(_watch.relay_day(m)) or "9999", _watch.world_line(_gh.shown(gid), str(it.get("subject") or ""), m)))
            if not _watch.can_end(m):
                stuck.append(_gh.shown(gid))
        except Exception:  # noqa: BLE001
            continue
    out = []
    if rows:
        out.append(f"Waiting on the world ({len(rows)}; news only {OWNER} relays, each comes to him as a question on its ask-by day):\n" + "\n".join(r for _d, r in sorted(rows)))
    if stuck:
        out.append(f"Waits no watcher can end ({len(stuck)}: {', '.join(stuck)}): the wait has no date or anchor to watch, so it keeps today's wake pass; give it one (wake, ask_by, after or wait_anchor).")
    return "\n\n".join(out)


_BRIEF_DESC = (
    _T.description("brief")
)


def stackshot_brief() -> str:
    _oauth._who()
    md = _cfg.path("paths", "markdown")
    head = ""
    if md.exists():
        text = md.read_text(encoding="utf-8")
        j = text.find("\n## Your move")          # the head: counts, Machines, Anchor hub, the Task board index; the items follow in full
        head = text[:j].rstrip() if j > 0 else text[:8000]
        # board.md links an item to its card on the same page ([board#N](#task-g-7)), an anchor that spells the store id and
        # leads nowhere outside the board; the brief a session reads links the item's page instead, as a notice does (notice_link)
        head = re.sub(r"\]\(#task-([a-z])-([1-9]\d*)\)", lambda m_: f"]({_telling.notice_link(m_.group(1) + m_.group(2))})", head)
    changed = "\n".join(_wc.lines())                  # step 4b: what changed in the tools in the last 7 days (whatschanged.py, generated from the tools' text snapshot), at the top
    if changed:
        head = changed + ("\n\n" + head if head else "")
    guards = _model_report_line()                    # what the model's write guards would refuse on the items already there, in one line
    if guards:
        head = (head + "\n\n" if head else "") + guards
    world = _world_waits_text()                      # the relay waits, "waiting on the world"
    if world:
        head = (head + "\n\n" if head else "") + world
    handed = _handoff_brief()                        # step 2: the hand-offs not yet taken
    if handed:
        head = (head + "\n\n" if head else "") + handed
    mine, held = [], []
    for gid, p in _item_files():
        with open(p, encoding="utf-8") as f:
            it = json.load(f)
        _legacy_hold(it); _ip.read_through(it)
        if it.get("status") == "open":
            it["gid"] = gid; (held if _is_parked(it) else mine).append(_fmt(it, brief=True))
    hold = ("\n\nOn hold (" + str(len(held)) + "), on the agent side but out of the queue until they wake or are released:\n\n" + "\n\n".join(held)) if held else ""
    return (head + "\n\n---\n" + "All open items in full (" + str(len(mine)) + " active" + (f", {len(held)} on hold below" if held else "") + "):\n\n" + ("\n\n".join(mine) if mine else "(none)") + hold
            + "\n\nFull board: " + _inst.BOARD_URL + " · any item by id: the get tool") + _nag()


def register(mcp, *, fmt, handoff_brief, is_parked, model_report_line) -> None:
    """Adds the tool of this module to `mcp`, and takes the server's callables the bodies use."""
    global _fmt, _handoff_brief, _is_parked, _model_report_line
    _fmt = fmt
    _handoff_brief = handoff_brief
    _is_parked = is_parked
    _model_report_line = model_report_line
    mcp.tool(name="brief", description=_lead(_BRIEF_DESC))(stackshot_brief)
