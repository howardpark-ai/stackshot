"""notes.py: the helpers more than one tool calls: the note a sender off its project's agents map gets, the owner and until parameter helpers, the sender check of the writes; and the notes a reply carries: the form notes
(a command or a report in next, a naked URL, a hold that waits on the owner), the `model:` and `mover:` lines of an item, the report of what the item model's guards would refuse, and the report of the holds nothing holds."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import threading
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.core.store import _item_files
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import holders as _holders
from stackshot.model import item_project as _ip
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model import next_rules as _nr
from stackshot.model.bullet_text import _clip_line
from stackshot.model.field_gates import _next_len, _next_line_max
from stackshot.model.ids import _norm_id
from stackshot.model.needs import _needs_kinds
from stackshot.projects import projects as _prj
from stackshot.service import item_read as _item_read
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import wait_fixes as _wait_fixes
from stackshot.service.store import _legacy_hold, _legacy_needs, _load
from stackshot.waits import server_fixes as _sf
from stackshot.waits import waiting as _wt
from stackshot.waits import watchers as _watch
from stackshot.web import render as _rmod
from stackshot.web.page_debts import _session_id
from stackshot.web.tools import text as _wttext
from stackshot.web.tools.text import _MODEL_PAGE, _T

_main_agent = None      # set by register: the server's own, looked up at each call


def _off_map_note_item(sender: str, item_id: str, project: str = "") -> str:
    """_off_map_note for a write to an item: the project the write names, else the item's own."""
    try:
        proj = project or str((_load(_norm_id(item_id, bare=True)).get("metadata") or {}).get("project") or "")
    except Exception:  # noqa: BLE001  — an item that does not read had no write to note
        return ""
    return _off_map_note(sender, proj)


def _off_map_note_to(sender: str, to: str) -> str:
    """_off_map_note for a message: only a target that is a project page (`projects/<slug>` or its id) names a project; anything that raises here leaves the delivered message's reply as it was."""
    try:
        key = _prj.to_key(str(to or "").strip()).rstrip("/")
        return _off_map_note(sender, key) if re.match(_cfg.page_dirs_re() + "/", key) else ""
    except Exception as e:  # noqa: BLE001  — the note is an extra
        print(f"off-map note for {sender!r} to {to!r} not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""


def _off_map_note(sender: str, project: str) -> str:
    """The line a write's reply ends with when `sender` is a session the project's agents map has no line for (anchors.off_map, the rule the audit's finding uses): it says so and names the project's
    -main agent, so the sender can ask for a line. A note, never a refusal; "" for a session the map lists, a visitor listed on another project's map, the owner, a script or when the registry cannot be read."""
    try:
        project = _anc.project_of({"metadata": {"project": str(project or "")}})       # a bare slug is the page in the first [pages] dir
        who = _anc.off_map(sender, project)
        if not who:
            return ""
        main = _main_agent(project)
    except Exception as e:  # noqa: BLE001  — the note is an extra: a failure in it leaves the reply as it was
        print(f"off-map note for {sender!r} on {project!r} not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""
    return (f"\n(note: {str(project).strip('/')} has no agents-map line for {who}. "
            + (f"Its -main agent is {main}: ask it to list you or to take this work.)" if main else "The project names no -main agent.)"))


_OWNER_PARAM_UNTIL = "2099-03-03"


def _owner_param_until() -> dt.date:
    """[model] owner_param_until (YYYY-MM-DD, default the code's): the last day create and update still accept the old `owner` parameter. A value that is not a date reads as the default."""
    v = str(_cfg.get("model", "owner_param_until", default=_OWNER_PARAM_UNTIL) or _OWNER_PARAM_UNTIL).strip()
    try:
        return dt.date.fromisoformat(v)
    except ValueError:
        return dt.date.fromisoformat(_OWNER_PARAM_UNTIL)


def _owner_param(tool: str, owner: str) -> str:
    """The old `owner` parameter of create or update → "" when it was not passed, else the note the reply ends with while it is still accepted; a ToolError (naming `mover`)
    from the day after [model] owner_param_until."""
    if not str(owner or "").strip():
        return ""
    until = _owner_param_until()
    if dt.datetime.now(_cfg.tz()).date() > until:
        raise ToolError(f"Refused: owner is not a parameter of {tool} any more (it was accepted until {until:%Y-%m-%d}). "
                        + ("Pass sender=<your own session>: the server records it as the item's creator. " if tool == "create" else "")
                        + f"Say who moves the item with mover=<a session, {OWNER} or the project's background agent> (and then=<who takes it after {OWNER}'s answer or step>). To name the front agent the item page leads with, use contact=<a front agent of the project>. The item model: {_MODEL_PAGE}.")
    return (f"\n(note: owner is going away: it is accepted until {until:%Y-%m-%d} and refused after. "
            + ("Pass sender=<your own session> instead: the server records it as the item's creator. " if tool == "create" else "To hand the item to a session, set mover=<session>. ")
            + f"Say who moves the item with mover=, and who takes it after {OWNER}'s answer or step with then=. To name the front agent the item page leads with, use contact=<a front agent of the project>. The item model: {_MODEL_PAGE}.)")


_SENDER_MIRROR = _T.piece("SENDER_MIRROR")      # the sender rule's wording, read by the complete tool's text and a test


def _sender_required(sender: str) -> None:
    """The refusal of a tool write without a sender while the GitHub mirror is on."""
    if _gh.enabled() and not str(sender or "").strip():
        raise ToolError("Refused: pass sender=<your session name or id>, because with the GitHub mirror on every change must name "
                        "who made it (the board records the author of each change).")


def bind(*, main_agent) -> None:
    """Takes the server's callables the helpers use; app.build calls it before any tool is registered."""
    global _main_agent
    _main_agent = main_agent


# ----------------------------------------------------------------------------- the notes a reply carries
_NAKED_URL = re.compile(r"(?<!\]\()https?://[^\s)\]>]+")


# Words that say an item waits on the owner running something (a command must sit on the item, not only in a session's chat). Narrow on purpose: the note is a nudge.
_CMD_EN = r"\b(?:paste|command|commands)\b|\brun (?:this|these|the|it|a)\b"


def _cmd_rx():
    """The command cues: the English ones plus [keywords.server] command_cues (compiled once per set of words, so a reload is seen)."""
    return _cfg.kw_rx("server.cmd", lambda a: _CMD_EN + _cfg.kw_pipe(a), (("server", "command_cues"),), re.I)


def _command_note(meta: dict[str, Any]) -> str:
    """A needs=decision item whose ask or next says the owner runs a command or a paste, while next carries neither a link nor a
    code span → the note naming the rule; "" otherwise."""
    if "decision" not in _needs_kinds(meta):
        return ""
    nxt = str(meta.get("next") or "")
    if not _cmd_rx().search(str(meta.get("ask") or "") + "\n" + nxt) or "`" in nxt or "](" in nxt or re.search(r"https?://", nxt):
        return ""
    return (f"this item waits on {OWNER} running a command or a paste, but next carries neither the command (a `code span`) nor a link to it: "
            "the item carries it, in next when it is short, otherwise on the project page with next linking to it; a chat reply alone scrolls past")


# A board item's next read like a log (results, commit hashes and test counts in it). next is only the next
# concrete action; the note names what in next reads like a report and never refuses. Per line; a line that starts `<owner>:` (a command
# he runs) is exempt from every signal. A markdown link's URL and a naked URL are cut out first, so a hash in a link target (and a PR or
# issue link alone) is quiet, while a bare hash or one in link text counts. The matchers live in next_rules.py (report_signals), which the daily audit's tools/next_report.py reads too.
_RX_LINK_URL = _nr.RX_LINK_URL


def _report_note(next_: str) -> str:
    """The note when next reads like a report: a commit hash, a test count, a past-tense report ("merged", "done at", "live since",
    "deployed", "released" at a line's start or after "PR #N"; a status word mid-line such as "PR #12 is live" or "was merged", unless a condition word comes first), a stamp of when work began ("since 09:30", "at work since"),
    or, with the refusal off, a line over 200 characters; "" otherwise. One note per write, naming the line (the first two it found). A step is an action, never a status;
    the write goes through. (A line over [metadata.next] line_max is refused, _gate_next.)"""
    seen: dict[str, str] = {}
    lines: list[str] = []
    for raw in str(next_ or "").splitlines():
        ln = re.sub(r"^\s*(?:[-*\u2022]\s+)?", "", raw)
        if not ln.strip() or ln.lower().startswith(f"{OWNER.lower()}:"):
            continue
        ln = _NAKED_URL.sub("", _RX_LINK_URL.sub(r"\1", ln))
        hit = False
        for kind, found in _nr.report_signals(ln).items():
            hit = True
            if kind not in seen:
                seen[kind] = found
        if not _next_line_max() and _next_len(ln) > 200 and "a line over 200 characters" not in seen:     # the refusal is off ([metadata.next] line_max = 0, or require_bullets = false): the old note
            seen["a line over 200 characters"] = ""
            hit = True
        if hit and len(lines) < 2:
            lines.append(_clip_line(ln.strip(), 70))
    if not seen:
        return ""
    what = ", ".join(f"{k} ({v})" if v else k for k, v in seen.items())
    where = " in " + " and ".join(f'"{x}"' for x in lines) if lines else ""
    return (f"next reads like a report ({what}){where}: a step is an action, never a status; next holds the next action, one per line, each naming who takes it; "
            "put results, hashes and test counts on the project page (Current state or a timeline line)")


def _form_notes(description: str = "", next_: str = "", parked: bool = False, meta: dict[str, Any] | None = None, gid: str = "", cmd: bool = False, ext: bool = False) -> str:
    """The board's form rules a reply can check, which left the rulebook. Each speaks only
    when broken, as a note and never a refusal: a URL not on words, an owner's hold without a wake, a hold on an item that waits
    on someone outside (unless its thread is anchored to it), an item put on someone outside with no anchor scoped to it.
    `parked` = this call put the item on hold; `ext` = this call put external into its needs."""
    out = []
    naked = [m.group(0).rstrip(".,;:") for f in (description, next_) for m in _NAKED_URL.finditer(f or "")]
    if naked:
        out.append(f"a naked URL ({naked[0][:80]}{', …' if len(naked) > 1 else ''}): put each link on the words it belongs to, [text](url)")
    if parked and meta is not None:
        if "external" in _needs_kinds(meta) and (why := _wait_fixes._anchored_wait(gid, meta)):
            out.append(why)
            ext = False                        # the hold note already says to anchor it: once
    if ext and meta is not None and not _item_read._scoped_anchor_exists(gid, meta):
        # an item waiting on an outside reply with no anchor
        out.append("this item now waits on someone outside, and no thread is anchored to it: anchor the thread it waits on in this same turn "
                   f"(anchors(project, add=[url], items=[{gid or 'its id'}])), so its reply wakes you and the item links it")
    if parked and meta is not None and _waits_on_owner(str(meta.get("next") or "")):
        out.append(f"this hold's next says it waits on {OWNER}: an item waiting on {OWNER} is never parked. Give it needs=decision with its ask, "
                   f"or after=[<the item that carries the ask>], which releases it when that item closes (a wake on an item {OWNER} has already answered is fine)")
    if cmd and meta is not None and (why := _command_note(meta)):
        out.append(why)
    if why := _report_note(next_):
        out.append(why)
    return "".join(f"\n(note: {x}.)" for x in out)


# An item parked on a timed hold while his choice was open calls for 'needs your call', not 'on hold':
# an item waiting on him is never held; it carries needs=decision with its ask, or after=<the item carrying the ask>.
# A hold whose next says it waits on him draws a note, never a refusal (a wake on an item he has already answered is legitimate).
# Narrow on purpose: a waiting word, then the owner or "his"/"<owner>'s" with a decision noun, or "until/for <owner> to decide" and
# the like. A next that only mentions him ("per the owner's call, deploy") stays quiet.
_O = re.escape(OWNER)


_DECIDE_NOUN = r"(?:call|decision|answer|reply|go-ahead|go|ok|okay|approval|pick|choice|word|review|sign-off|input|confirmation)"


_DECIDE_VERB = r"(?:decide|decides|answer|answers|reply|replies|approve|approves|pick|picks|choose|chooses|confirm|confirms|sign off|signs off|weigh in|weighs in)"


_WAITS_ON_OWNER_RX = re.compile(
    rf"\b(?:wait(?:s|ing|ed)?|await(?:s|ing)?|blocked|pending|parked|held|hold(?:s|ing)?|until|till)\s+(?:(?:on|for|upon)\s+)?"
    rf"(?:{_O}(?!['’])\b|(?:{_O}['’]s|his)\s+{_DECIDE_NOUN}\b)"
    rf"|\bneeds?\s+(?:{_O}['’]s|his)\s+{_DECIDE_NOUN}\b"
    rf"|\b(?:until|till|once|when|for)\s+{_O}\s+(?:to\s+)?{_DECIDE_VERB}\b", re.I)


def _waits_on_owner(text: str) -> bool:
    """True when text says the item waits on the owner (waiting on the owner, his call, until the owner decides); a passing mention is not, nor is a quoted span or a pick he already made
    (server_fixes.settled_out: 'his answer was "wait until Oliver decides"', 'Oliver picked A')."""
    return bool(_WAITS_ON_OWNER_RX.search(_sf.settled_out(text, _sf.owner_names())))


def _holds_unexplained() -> list[dict[str, Any]]:
    """Every open item on hold that nothing holds now (_hold_held_by). A stored reason is never trusted. A hold stored before the
    record has no setter: `by` is "" and `at` is 0. Read only: the item's mover releases each (update clear_hold=true, which the server takes from any session that writes the item) or gives it a condition.
    → [{gid, owner, wake, by, at, subject}], oldest hold first."""
    rows = []
    for gid, p in _item_files():
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:
            continue
        if not isinstance(it, dict):
            continue
        _legacy_hold(it); _legacy_needs(it); _ip.read_through(it)
        if not _holders._is_held(it):
            continue
        meta = it.get("metadata") or {}
        if _wait_fixes._hold_held_by(gid, meta):
            continue
        owner = _telling.holder(it)
        rows.append({"gid": gid, "owner": _sr._session_label(_session_id(owner)) if owner else "", "wake": str(_wt.wake_value(meta) or ""),
                     "by": _rmod.hold_by(it), "at": _rmod.hold_at(it), "subject": str(it.get("subject") or "")})
    return sorted(rows, key=lambda r: (r["at"], r["gid"]))


def _holds_report() -> str:
    """The unexplained holds as the client prints them: one line each, for the item's mover to release one by one."""
    rows = _holds_unexplained()
    if not rows:
        return "no open item is on hold without something holding it\n"
    out = [f"{len(rows)} open item(s) on hold that nothing holds now (no open after, pane recycle, needs external or item-scoped anchor); "
           "its mover releases each with update clear_hold=true (the server takes it from any session that writes the item), or gives it its condition; the mover shown is who holds it:"]
    for r in rows:
        when = _rmod.when_words(dt.datetime.fromtimestamp(r["at"], _wttext.ZONE)) if r["at"] else "before the record"
        out.append(f"{_gh.shown(r['gid'])} · mover {r['owner'] or 'none'} · wake {r['wake'] or 'none'} · set by {r['by'] or 'unknown'} ({when}) · {r['subject']}")
    return "\n".join(out) + "\n"


_GUARD_REPORT: dict[str, Any] = {"at": 0.0, "rep": None}


_GUARD_REPORT_LOCK = threading.Lock()


def _model_report(max_age: float = 60.0) -> "_mg.Report":
    """What the item model's write guards would refuse on the items already in the store (model_guards.report): read only, nothing is refused or changed. One read of the store
    and of the sessions, kept `max_age` seconds, since the brief asks for it on every call."""
    with _GUARD_REPORT_LOCK:
        now = time.time()
        if _GUARD_REPORT["rep"] is not None and now - float(_GUARD_REPORT["at"]) < max_age:
            return _GUARD_REPORT["rep"]
        items: dict[str, dict[str, Any]] = {}
        for gid, _p in _item_files():
            try:
                items[gid] = _svcstore._load(gid)
            except Exception:  # noqa: BLE001  — one unreadable item never stops the report
                continue
        rep = _mg.report(items, _mg.Ctx(now=now, label=_sr._session_label, shown=_gh.shown), one_mover=bool(_cfg.get("model", "one_mover", default=True)))
        _GUARD_REPORT.update(at=now, rep=rep)
        return rep


def _model_report_line() -> str:
    """The brief's one line of counts ("" when nothing would be refused, or the report cannot be read: a brief never fails over it)."""
    try:
        line = _mg.brief_line(_model_report())
    except Exception as e:  # noqa: BLE001
        print(f"model guards: report not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""
    return line + ("" if _item_read._model_guards_on() else " (the guards are off: [model] guards = false)") if line else ""


def _mover_lines(item: dict[str, Any]) -> list[str]:
    """What get and a write's reply lead with: `mover:` (who moves an alive item now, as the model reads it: the stored mover, else the default) and `then:` (who takes it after
    the answer or step; it stands only beside the owner). A waiting item shows who picks it up when the wait ends as its mover, and `then:` only when he is that one; a closed one has none at all. [] when the reading fails: a get never fails over it."""
    try:
        mod = _item_read._model_of(item)
        who = lambda w: _sr._session_label(w) if w and not _model.is_owner(w) else (w or "no one")
        if mod.state == _model.ALIVE:
            return [f"mover: {who(mod.mover)}" + ("" if mod.mover_explicit else " (derived)")] + ([f"then: {who(mod.then)}" + ("" if mod.then_explicit else " (derived)")] if mod.then else [])
        if mod.state == _model.WAITING and mod.wait:
            return [f"mover: {who(mod.wait.mover)} (picks it up when the wait ends)"] + ([f"then: {who(mod.then)}"] if mod.then else [])
    except Exception as e:  # noqa: BLE001
        print(f"model: {item.get('gid') or item.get('id')} mover not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return []


def _shown_waiting_note(item: dict[str, Any], mod: "_model.Model") -> str:
    """The tail of the `model:` line for a stored doing item the board lists as waiting (model.view: a wake with every open step dated for that day or later, a wake on a held doing item, or a still-future wake that carries a wait_basis):
    ` · the board lists it as waiting until <time> (<why>)`, "" for every other item. The stored state stays doing, and `model: alive` is what the guards and the router read."""
    vw = _model.view(item, mod, after_open=lambda i_: _item_read._after_open(i_.get("metadata") or {}))
    if vw is mod or vw.state != _model.WAITING or mod.state != _model.ALIVE or not vw.wait:
        return ""
    return f" · the board lists it as waiting until {vw.wait.until}" + (f" ({vw.wait.basis})" if vw.wait.basis else "")


def _arrival_when(ts: float) -> str:
    """The time a line of a wait on a list arrived, for the `model:` line: YYYY-MM-DD HH:MM and the zone's name (as the refusals that give a time name it), in the board's zone; "" for a time no date can show,
    so the line keeps its arrival words and drops the time (a get never loses its model line over one)."""
    try:
        t = dt.datetime.fromtimestamp(float(ts), _cfg.tz())      # the zone read at the call, as tz_abbr reads it (ZONE is fixed at import): the clock and its name never come from two zones
        return f"{t:%Y-%m-%d %H:%M} {_cfg.tz_abbr(t)}"
    except (ValueError, OverflowError, OSError):
        return ""


def _model_lines(item: dict[str, Any], short: bool = False) -> list[str]:
    """The `model:` line of get (and its conflicts, one line each); the brief's (short) is one line for an open item, with no `derived:` tail, no conflicts and none for a closed item.
    [] when the reading fails: a get never fails over it."""
    try:
        mod = _item_read._model_of(item)
        shown_as = _shown_waiting_note(item, mod)
        if short:
            return [_model.words(mod, _sr._session_label, _gh.shown, derived=False, when=_arrival_when) + shown_as] if mod.state != _model.DEAD else []
        extra = [x for x in (_watch.chases_line(item.get("metadata") or {}, _sr._session_label), _watch.woke_line(item.get("metadata") or {}, _sr._session_label)) if x and item.get("status") == "open"]
        return [_model.words(mod, _sr._session_label, _gh.shown, when=_arrival_when) + shown_as] + extra + [f"model conflict: {c}" for c in mod.conflicts]
    except Exception as e:  # noqa: BLE001
        print(f"model: {item.get('gid') or item.get('id')} not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return []
