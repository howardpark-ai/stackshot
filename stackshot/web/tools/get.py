"""get.py: the `get` tool: one item, or the items of a project, with what the server shows about them, and the item as get and the brief show it (`_fmt`), the lines under next that name other items
(`_next_names_lines`) and a notice's ruling (`_notice_asked`, `_notice_report`: get with a notice id)."""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field

from stackshot.anchors import anchor_scope as _ascope
from stackshot.anchors import anchors as _anc
from stackshot.core.instance import OWNER
from stackshot.github import ghsync as _gh
from stackshot.model import draft as _draft
from stackshot.model import item_project as _ip
from stackshot.model import model as _model
from stackshot.model import said as _said
from stackshot.model import states as _states
from stackshot.model import step_proof as _sp
from stackshot.model import steps as _steps
from stackshot.model import work as _work
from stackshot.model.bullet_text import _clip_line
from stackshot.model.ids import _GID, _norm_id
from stackshot.model.needs import _after_of, _needs_of, _observers_of
from stackshot.fleet import sessions_registry as _sr
from stackshot.router import router as _router
from stackshot.router import router_live as _router_live
from stackshot.router import routing as _routing
from stackshot.service import checks as _checks
from stackshot.service import contacts as _contacts
from stackshot.service import handoff as _handoff
from stackshot.service import item_read as _item_read
from stackshot.service import mover_steps as _mover_steps
from stackshot.service import proofs as _proofs
from stackshot.service import store as _svcstore
from stackshot.service.store import _load, _path
from stackshot.waits import stall as _stall
from stackshot.waits import waiting as _wt
from stackshot.web import render as _rmod
from stackshot.web.answers import _answer_words
from stackshot.web.auth import oauth as _oauth
from stackshot.web.page_debts import _nag, _shown_needs, _shown_ref
from stackshot.web.tools import notes as _notes
from stackshot.web.tools import text as _wttext
from stackshot.web.tools.text import _lead, load_text

_T = load_text("get")


_NEXT_NAMES_MAX = 8      # how many items next names get a line in get (the first ones, in the order next names them)


_BOARD_REF_RX = re.compile(r"(?<![\w#/&-])board#([1-9]\d*)(?!\d)", re.I)


def _next_names_lines(item: dict[str, Any]) -> list[str]:
    """(a closed item must not be reported as waiting): the lines get shows under next, one per
    board#N that next names, in the order it names them, with that item's live state: `board#N: closed Tue Feb 3rd 2099 14:10 (done)`, `board#N: open, mover my-engineer`, `board#N: open,
    waiting after board#N`, `board#N: not found`. The item itself is left out. A reading that fails gives no line, never a failed get."""
    m = item.get("metadata") or {}
    me = _gh.resolve(str(item.get("gid") or item.get("id") or ""))
    seen: list[str] = []
    for n in _BOARD_REF_RX.findall(str(m.get("next") or "")):
        try:
            g = _norm_id(f"board#{n}")
        except ToolError:
            continue
        if g != me and g not in seen:
            seen.append(g)
    lines = []
    for g in seen[:_NEXT_NAMES_MAX]:
        try:
            it = _svcstore._load(g); it["gid"] = g
        except ToolError:
            lines.append(f"- {_gh.shown(g)}: not found")
            continue
        except Exception:  # noqa: BLE001
            continue
        cm = it.get("metadata") or {}
        if it.get("status") == "completed":
            at = float(it.get("state_updated") or it.get("updated") or 0)
            sup = str(cm.get("superseded_by") or "")
            lines.append(f"- {_gh.shown(g)}: closed" + (f" {_rmod.when_words(dt.datetime.fromtimestamp(at, _wttext.ZONE))}" if at else "")
                         + f" ({_rmod.outcome_word(cm.get('outcome') or 'done')}{' by ' + _gh.shown(sup) if sup else ''})")
            continue
        try:
            mod = _model.view(it, _item_read._model_of(it), after_open=lambda i_: _item_read._after_open(i_.get("metadata") or {}))      # the same view as the home page, so a long-doing item reads as waiting here too
            who = lambda w: _sr._session_label(w) if w and not _model.is_owner(w) else (w or "no one")
            if mod.state == _model.WAITING:
                left = _item_read._after_open(cm)
                lines.append(f"- {_gh.shown(g)}: open, waiting" + (f" after {', '.join(_gh.shown(x) for x in left)}" if left else ""))
            else:
                lines.append(f"- {_gh.shown(g)}: open, mover {who(mod.mover)}")
        except Exception:  # noqa: BLE001
            lines.append(f"- {_gh.shown(g)}: open")
    if len(seen) > _NEXT_NAMES_MAX:
        lines.append(f"- … and {len(seen) - _NEXT_NAMES_MAX} more")
    return ["named in next:", *lines] if lines else []


def _fmt(item: dict[str, Any], brief: bool = False) -> str:
    m = item.get("metadata") or {}
    out = [f"{_gh.shown(item.get('gid') or item['id'])} [{item.get('status')}{' · on hold' if _item_read._is_parked(item) else ''}] {item.get('subject')}"]
    if not brief:                            # step 4b: get leads with the mover (and then); the brief's item lines carry the `model:` line, which names it
        out.extend(_notes._mover_lines(item))
    if item.get("description"):
        out.append(item["description"])
    if m.get("goal"):                        # the end-state in one sentence
        out.append(f"goal: {m['goal']}")
    if item.get("status") == "completed" and m.get("outcome"):   # how it ended
        out.append(f"outcome: {_rmod.outcome_word(m['outcome'])}" + (f" by {m['superseded_by']}" if m.get("superseded_by") else ""))
        if m.get("reason"):
            out.append(f"reason: {m['reason']}")
        if m.get("outcome_text") and not brief:    # how it ended, in bullets: the description above stays what the item was about (the brief leaves it out, like the description's length)
            out.append(f"outcome text:\n{m['outcome_text']}")
    if item.get("status") == "open":         # where it stands: the stored state with the fields it carries; an item that stores none shows no state line (the model line below says alive or waiting)
        out.extend(w for w in [_states.words(item, lambda i_: _item_read._after_open(i_.get("metadata") or {}))] if w)
        out.extend(f"{k}: {v}" for k, v in _states.carry_of(item).items())
        if _draft.of(item):                          # the verbatim text the owner pastes elsewhere, as stored (many lines); the brief, which loads into every session, only says it is there
            d_ = _draft.of(item)
            out.append(f"draft: {len(d_.splitlines())} lines, {len(d_)} characters (get shows it)" if brief else "draft:\n" + d_)
        out.extend(_mover_steps._state_check_notes(item))            # next names the owner under an agent's state; next may be stale (the owner-step and stale-next checks)
    out.extend(_notes._model_lines(item, brief))                   # dead, alive or waiting, with the mover and the wait
    if not brief:
        out.extend(_handoff.handoff_lines(item))                    # step 2: handed to X, not yet taken | taken | returned
    for k in ("project", "needs", "ask", "priority", "due", "wake", "until"):       # the creator is no line here (the History says "created by"); the mover leads the model line
        if k == "needs":                     # the list
            needs = _needs_of(m)
            if needs:
                out.append("needs: " + ", ".join(_shown_needs(needs)))
            continue
        if k == "ask":                       # the ask only while it waits on his decision, as the options below
            if _rmod.open_ask(item):
                out.append(f"ask: {_rmod.open_ask(item)}")
        elif k == "project":
            if m.get(k):
                out.append(f"project: {_ip.line_of(m)}")      # the top-level project, with the page the item is filed on after it when that is a sub-page (item_project.line_of)
        elif m.get(k):
            out.append(f"{k}: {m[k]}")
        if k == "ask" and _rmod.open_options(item):   # under the ask, one line each; only while it waits on his decision
            out.append("options:\n" + "\n".join("- " + ln for ln in _rmod.option_lines(item)))
    if not brief and _contacts._contact_label(item):   # the front agent the person talks to about the item (the brief, which loads into every session, leaves it out)
        out.append(f"contact: {_contacts._contact_label(item)}")
    if _item_read._is_parked(item) and _rmod.hold_set_of(item):   # who set the hold, and when
        hs = _rmod.hold_set_of(item)
        out.append(f"hold: set by {_rmod.hold_by(item) or 'unknown'}"
                   + (f" {_rmod.when_words(dt.datetime.fromtimestamp(_rmod.hold_at(item), _wttext.ZONE))}" if _rmod.hold_at(item) else ""))
    if item.get("status") == "open" and _wt.basis_of(m):   # a wake past the cap that stands on a real-world date, and who said so
        wb = m["wait_basis"]
        out.append(f"wait basis: {_wt.basis_of(m)} (lifts the {_wt.cap_days():g}-day cap for the wake {_wt.wake_value(m)} only; set by {wb.get('by') or 'unknown'}"
                   + (f" {_rmod.when_words(dt.datetime.fromtimestamp(float(wb['at']), _wttext.ZONE))}" if isinstance(wb.get("at"), (int, float)) else "") + ")")
    if item.get("status") == "open" and _wt.words_of(m):   # his words behind the wake, quoted, and where they came from
        ww = _wt.words_of(m)
        out.append(f"{OWNER}'s words behind the wake {_wt.wake_value(m)}: “{_clip_line(ww['quote'], 300)}”" + (f" ({ww['source']})" if ww["source"] else ""))
    if _after_of(m):                         # what must close first, each with its state
        states = []
        for g in _after_of(m):
            try:
                states.append(f"{g} ({_svcstore._load(g).get('status')})")
            except ToolError:
                states.append(f"{g} (missing)")
        out.append("after: " + ", ".join(states) + ("" if _item_read._after_open(m) else " — all closed" if item.get("status") == "open" else ""))
    if _observers_of(m):
        out.append("observers: " + ", ".join(_shown_ref(x) for x in _observers_of(m)))
    if item.get("status") != "completed" and _work.lines_of(m):   # what is in motion on it, one line (the item page shows each on its step)
        out.append("step status: " + _work.words(m))
    for e in _said.entries_of(m):            # the trailers: his words on the item, each with where it was checked; an acted entry is a pasted result that proves a step, not his words
        sess_ = _sr._session_label(e["session"]) or "unknown session"
        when_ = f" · {_rmod.when_words(dt.datetime.fromtimestamp(e['ts'], _wttext.ZONE))}" if e["ts"] else ""
        if e["kind"] == _said.ACTED:
            out.append(f"{e['tag']}: pasted in {sess_}{when_} · " + ("checked against the transcript" if e["checked"] else "unchecked") + f" (proof of a step, not his words) · “{_clip_line(e['quote'], 200)}”")
            continue
        out.append(f"{e['tag']}: {OWNER} · {sess_}{when_}" + (" · checked" if e["checked"] else " · unchecked")
                   + f" · “{_clip_line(e['quote'], 200)}”")
    ans = _rmod.answers_of(item)
    if ans:                                  # phase 3: his answers from the board, the last three, oldest first
        out.append(f"{OWNER}'s answers on the board" + (f" (last 3 of {len(ans)})" if len(ans) > 3 else "") + ":\n" + "\n".join(
            f"- {_rmod.when_words(dt.datetime.fromtimestamp(float(a.get('ts') or 0), _wttext.ZONE))} {'comment' if a.get('kind') == 'comment' else 'note on his step' if a.get('kind') == 'step-reply' else 'answer'}: "
            + _answer_words(a, 1200) + (f" [chosen option: {a['choice']}: {a['choice_line']}]" if a.get("choice") and a.get("choice_line") else "") for a in ans[-3:]))
    idle = m.get("idle") if isinstance(m.get("idle"), dict) else {}
    if idle.get("poked"):                    # what the idle pass did; the audit skips an item it poked after its last confirm. The idle pass only ever asked the fleet's builder (no code writes `recovery` now; the line reads the record it left), so this line keeps that wording: the hand-off and stall ladders, which can ask a front-only project's -main agent, write their own lines ("handoff:", "stall:")
        w = lambda k: _rmod.when_words(dt.datetime.fromtimestamp(float(idle[k]), _wttext.ZONE))
        out.append(f"idle: poked {idle.get('to') or '?'} {w('poked')}" + (f", the fleet's builder was asked to recover it {w('recovery')}" if idle.get("recovery") else ""))
    from stackshot.audit import hourly_log as _hlog
    for x in _hlog.log_of(m)[-1:]:           # the newest hourly audit line (audit/hourly.py), with its own prefix: it is no step of the stall pass
        out.append(f"audit: {_rmod.when_words(dt.datetime.fromtimestamp(float(x.get('at') or 0), _wttext.ZONE))} {x.get('text') or ''}")
    for x in _stall.log_of(m)[-3:]:          # what the stall pass did (its mover's pane had no turn running), the last three, oldest first
        out.append(f"stall: {_rmod.when_words(dt.datetime.fromtimestamp(float(x.get('at') or 0), _wttext.ZONE))} {x.get('text') or ''}")
    if _rmod.waits_recycle(item):            # waits for a pane recycle, since when
        at = m.get("recycle_at")
        out.append("recycle: waits for a pane recycle" + (f" (since {_rmod.when_words(dt.datetime.fromtimestamp(float(at), _wttext.ZONE))})" if isinstance(at, (int, float)) else ""))
    gid = str(item.get("gid") or "")
    if item.get("status") == "open" and m.get("check"):   # the done check: what closes it, and what the last pass found
        out.append("check: " + _checks.check_label(str(m["check"])) + _checks.check_words(gid, item))
    if item.get("status") == "open" and isinstance(m.get("step_proof"), dict) and m["step_proof"]:   # a step that names the event which ticks it (step_proof)
        told_ = {str(x) for x in (m.get(_proofs.RELEASED_TOLD) or [])}
        sp_, dead_ = [], False
        for i, s_ in enumerate(_steps.view(m, keeper=str(m.get("owner") or "")), 1):
            if s_["status"] == _steps.OPEN and _steps.key(s_["text"]) in m["step_proof"]:
                pv = m["step_proof"][_steps.key(s_["text"])]
                isdead = f"dead {_sp.read_stored(pv)[1]}" in told_
                dead_ = dead_ or isdead
                sp_.append(f"{i}. {_steps.first_line(s_['text'])[:70]} ← {pv}" + (" (dead: that pull request was closed without being merged; reword or drop the step)" if isdead else ""))
        if sp_:
            out.append("step proof: " + "; ".join(sp_) + ("" if dead_ and all("(dead:" in x for x in sp_) else " (the server ticks the step when it happens)"))
    if item.get("status") == "open" and _GID.match(gid):   # a wait that can no longer end
        fail = _wt.failed_of(m)
        if fail:
            out.append(f"wait failed: {fail.get('what') or 'a wait'}: {fail.get('why') or 'it can no longer end'} ({_rmod.when_words(dt.datetime.fromtimestamp(float(fail['at']), _wttext.ZONE))})")
    if item.get("status") == "open" and isinstance(m.get("undelivered"), list) and m["undelivered"]:   # a notice that was not delivered (a log line nobody read)
        out.append("undelivered notices:\n" + "\n".join(
            f"- {_rmod.when_words(dt.datetime.fromtimestamp(float(u.get('at') or 0), _wttext.ZONE))} ({u.get('tag') or 'notice'}) to {u.get('to') or '?'}: {u.get('why') or 'not delivered'}"
            for u in m["undelivered"] if isinstance(u, dict)))
    seen = _rmod.confirmed_at(item, _path(gid) if _GID.match(gid) else None)
    if seen:                                 # when the item was last confirmed true, and whether that is stale for its lane
        fresh, age = _rmod.freshness(item, time.time())
        out.append(f"confirmed: {_rmod.when_words(dt.datetime.fromtimestamp(seen, _wttext.ZONE))} ({'stale ' + _rmod.age_words(age) if fresh == 'stale' else fresh})")
    if m.get("next"):
        out.append("next:\n" + str(m["next"]))
        if item.get("status") == "open" and not brief:
            out.extend(_next_names_lines(item))      # the live state of each item next names, so nobody relays a stale status
    try:                                     # with a step done or dropped, the whole checklist with its positions (done=[…] and dropped=[…] take them)
        cl = _steps.view(m, closed=item.get("status") == "completed")
        if any(x["status"] != _steps.OPEN for x in cl):
            def _cl_line(i: int, x: dict[str, Any]) -> str:
                who = f" · {x['by']}" if x.get("by") else ""
                when = f" · {_rmod.when_words(dt.datetime.fromtimestamp(float(x['at']), _wttext.ZONE))}" if x.get("at") else ""
                return f"{i}. [{x['status']}{who}{when}] {_clip_line(_steps.first_line(x['text']), 110)}"
            out.append("checklist:\n" + "\n".join(_cl_line(i, x) for i, x in enumerate(cl, 1)))
    except Exception:  # noqa: BLE001  — a reading that fails never fails the get
        pass
    try:                                     # the anchors that count for this item: those scoped to it on any project's page (a page other than the item's own project is named) + its project's project-wide ones
        project = str(m.get("project") or "")
        pa = _ascope.anchor_scope(_anc.load(), str(item.get("gid") or item.get("id")), project, wide=True)
        if pa:
            out.append("anchors (any project): " + " · ".join(f"{e['url']} [{'items: ' + ', '.join(e['items']) if e.get('scoped') else 'project-wide'}"
                                                 + (f"; held by {', '.join(x for x in e['pages'] if x != project)}" if any(x != project for x in e["pages"]) else "") + "]" for e in pa))
    except Exception:
        pass
    return "\n".join(out)


# ----------------------------------------------------------------------------- a notice's ruling (get with a notice id)
_RULING_SAYS = {"merged": "merged into a digest (nobody is told at once)", "held": "held (kept for the daily digest or the page pass; nobody is told at once)",
                "dropped": "dropped (nobody needed it)"}


_REPEAT_OF = re.compile(r"\brepeat of (?:notice )?([0-9a-f]{6})\b")


def _notice_asked(item_id: str) -> str:
    """The notice id get was asked for, "" when item_id names an item. A notice id is six hex characters (routing.record's token_hex(3)), with
    "notice " before it or not; bare, it is an item id first when the store holds an item of that name (a12345 reads as both)."""
    m = re.fullmatch(r"(notice[\s:#]*)?([0-9a-f]{6})", str(item_id).strip().lower())
    if not m:
        return ""
    if not m.group(1):
        try:
            if _path(_norm_id(m.group(2))).exists():
                return ""
        except ToolError:
            pass
    return m.group(2)


def _notice_report(nid: str) -> str:
    """What the router did with a notice, from its own records: the routing log (the notice and its latest ruling: routing.lookup, which parses only the
    lines that carry the id) and live.jsonl (router_live.trace: the rule or call that ruled it, the item it went onto, an error while it waits). The
    live log is read first, only because it names the project's file; the ruling shown is the routing log's, so a `route` overrule shows as it stands."""
    tr = _router_live.trace(nid)
    hint = str(((tr.get("ruled") or tr.get("last")) or {}).get("key") or "")
    hit = _routing.lookup(nid, hint)
    if hit is None:
        raise ToolError(f"no notice {nid} in the routing log — a notice id is the six hex characters a message to a project returns (\"notice a1b2c3\"); an item id reads board#<n>"
                        + (f" (and the store holds no item {nid})" if _GID.match(nid) else ""))
    key, n = hit
    when = lambda t: _rmod.when_words(dt.datetime.fromtimestamp(float(t), _wttext.ZONE))
    text = " ".join(str(n.get("text") or "").split())
    text = text if len(text) <= 120 else text[:119].rstrip() + "…"
    out = [f"notice {nid}: {n.get('label') or n.get('kind') or 'a notice'}", f"project: {key}", f"sender: {n.get('who') or 'unknown'}",
           f"sent: {when(n.get('ts') or 0)}", f"text: {text}"]
    ruling = str(n.get("ruling") or "")
    if ruling:
        by, target = str(n.get("ruled_by") or ""), str(n.get("ruled_to") or "")
        out.append("ruling: " + (f"passed to {target or 'nobody named'}" if ruling == "passed" else _RULING_SAYS.get(ruling, ruling)))
        if n.get("reason"):
            out.append(f"reason: {n['reason']}")
        rep = _REPEAT_OF.search(str(n.get("reason") or ""))
        if rep:
            out.append(f"repeat of: notice {rep.group(1)}")
        live = tr.get("ruled") if by == _router_live.BY and (tr.get("ruled") or {}).get("ruling") == ruling else None
        if live:
            how = {"code": "code", "call": "the router's call", "fallback": "fallback"}.get(str(live.get("source") or ""), str(live.get("source") or "the router"))
            out.append("rule: " + (f"{live['rule']} ({how})" if live.get("rule") else how))
            out.append(f"item: {_gh.shown(str(live['item'])) if live.get('item') else 'none'}")
        elif by == _routing.AUTO_RULER:
            out.append("rule: ruled at once when it was logged, nothing delivered (code)")
        elif by and by != _router_live.BY:
            out.append("rule: overruled by hand with the route tool")
        if by:
            out.append(f"ruled by: {by}")
        if n.get("ruled_at"):
            out.append(f"ruled: {when(n['ruled_at'])}")
        return "\n".join(out)
    now, tick = time.time(), _router_live.tick_s()
    if tr.get("stuck"):
        out += ["ruling: none, stuck", f"reason: {str(tr['stuck'].get('reason') or 'the router could not write its ruling')[:200]}"]
    elif n.get("live") and n.get("pilot"):
        due = float(n.get("ts") or 0) + tick
        late = now > due + _router.timeout_s()
        out += ["ruling: none yet, still held for the router",
                f"expected: by {when(due)} (the router takes up held notices every {int(tick)} s; a judgment call can add up to {int(_router.timeout_s())} s)"
                + (" — it is late: a failed judgment is tried again at the router's next tick" if late else "")]
        last = tr.get("last") or {}
        if last.get("status") == "error" and last.get("error"):
            out.append(f"last try: {str(last['error'])[:200]}")
    elif n.get("pilot"):
        out.append("ruling: none yet, waiting for a ruling (the route tool rules it)")
    else:
        out.append("ruling: none, recorded as a count only (no ruling is owed)")
    return "\n".join(out)


# What an agent does when the stall pass takes a wrong step; the same path is in stall.py's docstring and docs/stall-and-ladder.md.
_STALL_FORM = _T.piece("STALL_FORM")


def stackshot_get(item_id: Annotated[str, Field(description=_T.param("item_id"))]) -> str:
    """Read one item by id as shown (board#N, or the older letter-and-number form for an older item). It shows `needs:` (whose move it is: decision, external and the sessions named), `after:` (the items that must close first, each with its state), and `observers:`. It leads with `mover:` (who moves the item now) and `then:` (who takes it after the answer or the wait); History says who created it. `model:` says alive or waiting, the mover and what it waits on (a time, the close of other items, an anchor, an answer relayed to a person, or a fleet event, shown as `a fleet event (<the event>; backstop <day>)`); on a doing item the board lists as waiting it ends with `· the board lists it as waiting until <time> (<why>)` (stored as doing, but its wake is more than an hour away and every open step is dated for that day or later, or its wake carries a wait_basis and is still ahead; a wake kept as a hand-off's backstop, with no wait_basis, is no wait; a date alone is a wait until it), so it is listed as waiting until then. After `next:` a `named in next:` block gives each board#N the next names with its live state (closed with the time and outcome, open with its mover, waiting, or not found), so a status is never relayed from the words of next. The item model is on docs/design. item_id can also be a notice id (the six hex characters a message to a project returns): it then shows who sent the notice and when, its project, a one-line excerpt, the router's ruling with its reason, rule and item, when it was ruled, or that it is still held and when the router rules it."""
    _oauth._who()
    nid = _notice_asked(item_id)
    if nid:
        return _notice_report(nid)
    gid = _norm_id(item_id, bare=True); it = _load(gid); it["gid"] = gid
    return _fmt(it) + _nag()


def register(mcp) -> None:
    """Adds the tool of this module to `mcp`."""
    mcp.tool(name="get", description=_lead(_T.description("get")))(stackshot_get)
