"""terminal_prompt.py: `client.py post terminal-prompt open|clear`, a pane waiting in its terminal as a row in the owner's Your move list.

When a session's permission prompt cannot be answered by a hook, sala calls `post terminal-prompt open`: one open item per session, filed through `create_item` (the create tool's own code), marked
`metadata.terminal_prompt`; `clear` closes it when the pane stops waiting. `_TERMINAL_LOCK` makes the look for an open item and the write that follows one step. The small helpers (`_terminal_bullets`,
`_terminal_subject_prefix`) are the ones service/job_gap.py and service/item_open.py file their rows with. The module sets `owner_steps.ALIKE` at its import: the question line it writes is the owner's step itself.

A service module: it reads the registry, the project record and the store and writes through `create_item` and the update tool's code. The route that calls it (`_client_post`) is the surface's.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import re
import sys
import threading
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.core.store import _item_files
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import bullet_text as _bt
from stackshot.model import owner_steps as _hs
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.model.field_gates import _description_limits, _fit, _next_line_max, _subject_max
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _registry
from stackshot.service import create as _create_svc
from stackshot.service import item_read as _item_read
from stackshot.service import owner_words as _owner_words
from stackshot.service import store as _svcstore
from stackshot.service import update as _update_svc
from stackshot.service import writes as _writes


# ----------------------------------------------------------------------------- a pane waiting in its terminal (client.py post terminal-prompt)
# When a session's permission prompt cannot be answered by a hook (a question to the owner, a guarded file, plan mode), the pane waits in its terminal and
# sala calls `client.py post terminal-prompt open`: one open item per session, in the owner's Your move list, linking the pane; `clear` closes it when the
# pane stops waiting. The item is marked metadata.terminal_prompt = the session's name as the registry has it now, and a session is matched on what both names
# resolve to (a permanent id, a transcript id or an old name finds the same item).
_TERMINAL_LOCK = threading.Lock()
_TERMINAL_Q_MAX = 200                                         # the question: one line of at most this many characters
_TERMINAL_REASON = "the pane stopped waiting"


def _terminal_fallback() -> str:
    """[terminal] fallback_project ("" = none): the project a terminal-prompt item is filed under when the session's own project lists no front agent. Read where used, so a reload applies."""
    return str(_cfg.get("terminal", "fallback_project") or "").strip()


def _terminal_same(a: str, b: str) -> bool:
    """Do two references name one session? As permanent ids when the registry resolves both, else as strings or as the names the fleet gives them."""
    t = _sr.same(a, b)
    return (a == b or _sr._session_label(a) == _sr._session_label(b)) if t is None else t


def _terminal_bullets(*lines: str) -> str:
    """Lines as the `- ` bullets of a description (clipped to [description] line_max)."""
    max_lines, line_max = _description_limits()
    return _bt.bullets("\n".join(lines), max_lines, line_max)


def _terminal_open_items(session: str) -> list[str]:
    """The ids of the open items marked as `session`'s terminal prompt. A file is read as text first (the mark is a key in its JSON), so a store of thousands is cheap to scan."""
    out = []
    for gid, p in _item_files():
        try:
            if '"terminal_prompt"' not in p.read_text(encoding="utf-8"):
                continue
            it = _svcstore._load(gid)
        except (OSError, ValueError, ToolError):
            continue
        mark = str((it.get("metadata") or {}).get("terminal_prompt") or "")
        if it.get("status") == "open" and mark and _terminal_same(mark, session):
            out.append(gid)
    return out


def _terminal_projects(session: str) -> list[dict[str, Any]]:
    """The projects a terminal-prompt item may be filed under, best first: the session's own (the registry row's project_key, else its project), then [terminal] fallback_project (none by default);
    each a project record that lists a front agent (the item's `then` is its -main agent first, as _question files)."""
    row = _sr.row(session) or {}
    out: list[dict[str, Any]] = []
    for ref in (row.get("project_key"), row.get("project"), _terminal_fallback()):
        ref = str(ref or "").strip()
        if not ref:
            continue
        try:
            recs = _prj.refs(ref, _registry("projects"))
        except ValueError as e:
            raise ToolError(f"the project record cannot be read right now, nothing was filed: {e}")
        if len(recs) == 1 and recs[0]["key"] not in [r["key"] for r in out] and _item_read._hub_sessions(recs[0]["key"])[3]:
            out.append(recs[0])
    return out


def _terminal_subject_prefix(scope: str) -> str:
    """The subject prefix of an item no session wrote: the project's scope when the instance has that prefix, else [subject] fallback_prefix when that is one of the prefixes (empty: none), else the first prefix."""
    prefixes = list(_cfg.CFG["subject"]["prefixes"])
    fallback = str(_cfg.get("subject", "fallback_prefix") or "")
    return next((p for p in (f"[{scope}] ", fallback) if p and p in prefixes), prefixes[0])


def _terminal_next(name: str, question: str) -> str:
    """The item's one next line, "<owner>: open <the pane's address> and answer: `<question>`". The address is [client] session_view with the name url-quoted (with none set, the line says "the pane of <name>"). The
    question is the pane's own free text, so it stands as a code span (a backtick in it becomes an apostrophe): the next guards read prose, and a question that says "wait for
    the nightly window" is no wait of the item's. A line over [metadata.next] line_max (the address does not count) has its question cut at a word with an ellipsis, where the next gate
    would refuse it."""
    from urllib.parse import quote
    view = str(_cfg.get("client", "session_view") or "")
    link = view.replace("{name}", quote(name, safe="")) if view else f"the pane of {name}"
    head, q = f"{OWNER}: open {link} and answer: ", question.replace("`", "'")
    limit = _next_line_max()
    if limit and _bt.visible_len(f"{head}`{q}`") > limit:
        q = _bt.clip_bullet(head + q, max(limit - 2, 1))[len(head):]
        if not q.strip(" …"):         # no word of the question fits (one long token): a hard cut with an ellipsis, never an empty question
            room = max(limit - _bt.visible_len(head + "`") - 2, 1)       # the opener, the opening backtick, the closing one and the ellipsis
            q = question.replace("`", "'")[:room].rstrip() + "…"
    return f"{head}`{q}`"


def _terminal_prompt(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post terminal-prompt open|clear --session S --sender L [--question Q]`: a pane waiting in its terminal becomes an open item in the owner's Your move list, and
    stops being one when the pane stops waiting. body: action (open | clear), session, sender, and for open the question (one line, at most 200 characters).
    open: one open item per session. It is filed through create_item (service/create.py), the create tool's own code, so the subject prefix, the description and next gates, the project page, the
    owner as mover and the GitHub mirror all apply and a refusal is the tool's text (400): the subject "<session> is waiting for your answer in its terminal", under the session's
    project from the registry (else projects/example-two), p1, mover the owner, then the project's front agent (its -main agent first, as _question), next "<owner>:
    open <the pane's address> and answer: <question>", marked metadata.terminal_prompt = the session's name; then its state is set to your-step with the step "Answer <session>'s
    question in its terminal" (a create sets no step). A second open for a session that has an open item changes that item's next line and creates nothing; the same question
    again writes nothing. clear: closes the session's open item (outcome done, reason "the pane stopped waiting"); with none open it does nothing and answers 200. The session is
    matched through the registry, so an id, an old name and the current name reach one item. The writes are a script's (like _question's): the guard on alarming words does not judge
    a pane's own question (QUESTION) and the script owes no page. -> (status, {item, session, project, repeat} | {session, cleared: [ids]})."""
    action = str(body.get("action") or "").strip()
    session, sender = (str(body.get(k) or "").strip() for k in ("session", "sender"))
    question = body.get("question") if isinstance(body.get("question"), str) else ""
    if action not in ("open", "clear"):
        return 400, {"error": "action = open | clear"}
    if not session or len(session) > 120:
        return 400, {"error": "session = the pane's name or id, at most 120 characters"}
    if re.search(r"[\[\]()<>@`\s\x00-\x1f\x7f]", session):         # the name goes into the subject, the description, the step and the link: a markup character, a mention or a space would render or notify
        return 400, {"error": "session = a pane's name or id without spaces or any of [ ] ( ) < > @ ` (a name like that would render as markup or mention someone on the item); use the name or id sala has for the pane"}
    if not sender or len(sender) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in sender):
        return 400, {"error": "sender = the script's own label: required, one line of at most 80 characters (permission-hook)"}
    try:
        _owner_words._sender_not_owner(sender)
    except ToolError as e:
        return 400, {"error": str(e)}
    question = question.strip()
    if action == "open":
        if not question:
            return 400, {"error": "question is required (--question): the one line the pane is asking"}
        if len(question.splitlines()) > 1:
            return 400, {"error": f"question must be one line (it is shown on {OWNER}'s row); shorten it, the pane has the rest"}
        if len(question) > _TERMINAL_Q_MAX or any(ord(c) < 32 or ord(c) == 127 for c in question):
            return 400, {"error": f"question must be one line of at most {_TERMINAL_Q_MAX} characters ({len(question)} now); shorten it, the pane has the rest"}
    name = _sr._session_label(session)
    by = f"{sender} via a script on {machine}"
    try:
        with _TERMINAL_LOCK:         # the look for an open item and the write that follows are one step, so two calls for one session file one item
            _writes.QUESTION.on = True      # a pane's own words are not judged for alarming ones (see _question)
            _writes.TERMINAL_ROW.on = True  # the row owes no page and tells no session (create_item, _update, the tell_* notices)
            try:
                found = _terminal_open_items(name)
                if action == "clear":
                    return 200, _terminal_clear(found, name, sender, machine, by)
                return _terminal_open(found, session, name, question, sender, machine, by)
            finally:
                _writes.QUESTION.on = _writes.TERMINAL_ROW.on = False
    except ToolError as e:
        return 400, {"error": str(e)}


def _terminal_clear(found: list[str], name: str, sender: str, machine: str, by: str) -> dict[str, Any]:
    """Close every open terminal-prompt item of the session (one, unless an earlier failure left more) -> {session, cleared: [ids as shown]}; none open closes nothing."""
    done = []
    for gid in found:
        desc = _terminal_bullets(f"{name} stopped waiting in its terminal", f"Closed by {sender} (a script on {machine}): {_TERMINAL_REASON}")
        _update_svc._update(gid, outcome_text=desc, status="completed", outcome="done", reason=_TERMINAL_REASON, sender=by)
        done.append(_gh.shown(gid))
    return {"session": name, "cleared": done}


def _terminal_state(gid: str, name: str, by: str) -> None:
    """The item's state: your-step with the one-line step (a create sets none)."""
    _update_svc._update(gid, step=f"Answer {name}'s question in its terminal", sender=by)


def _terminal_question_line(text: str) -> bool:
    """Is the step the terminal prompt's own question line (the shape _terminal_next writes)? Only that line is dropped when the question changes, by its position in the checklist: another writer's lines stay, and two equal lines never clash."""
    return text.startswith(f"{OWNER}: open ") and " and answer: `" in text.splitlines()[0]


_hs.ALIKE = _terminal_question_line      # the question line the terminal prompt writes is his step itself: the server adopts it (records it as its step) rather than adding a second beside it


def _terminal_open(found: list[str], session: str, name: str, question: str, sender: str, machine: str, by: str) -> tuple[int, dict[str, Any]]:
    nxt = _terminal_next(name, question)
    if found:
        gid = found[0]
        meta = _svcstore._load(gid).get("metadata") or {}
        if str(meta.get("next") or "").strip() != nxt.strip():
            _update_svc._update(gid, next=nxt, sender=f"a script on {machine}", dropped=[i + 1 for i, x in enumerate(_steps.view(meta)) if x["status"] == _steps.OPEN and _terminal_question_line(x["text"])])       # a script's line is the creator's (the item's first writer), which this write replaces (next_writer in _update); the old question is a dropped step
        if meta.get("state") != "your-step" or not _states.clean(meta.get("step")):
            _terminal_state(gid, name, by)                                # an item a crash left between its create and its state write is made whole here
        return 200, {"item": _gh.shown(gid), "session": name, "project": str(meta.get("project") or ""), "repeat": True}
    cands = _terminal_projects(session)
    if not cands:
        fb = _terminal_fallback()
        return 409, {"error": "no project to file under: the session's project" + (f" and {fb}" if fb else "") + " list no front agent (a user-facing agent under `agents:` on the page)"}
    rec = cands[0]
    key = rec["key"]
    owner = sorted(_item_read._hub_sessions(key)[3], key=lambda n: (not n.endswith("-main"), n))[0]
    desc = _terminal_bullets(f"{name} is waiting in its terminal for {OWNER}'s answer", f"Opened by {sender} (a script on {machine}); it closes when the pane stops waiting")
    pfx_, tail_ = _terminal_subject_prefix(str(rec.get('scope') or '')), " is waiting for your answer in its terminal"
    name_ = _svcstore._shown_ids(name)
    room_ = (_subject_max() - len(pfx_) - len(tail_)) if _subject_max() else 0      # a long pane name is cut so the server's own subject is never refused
    subject = f"{pfx_}{_fit(name_, room_) if 0 < room_ < len(name_) else name_}{tail_}"
    gid, _reply = _create_svc.create_item(subject=subject, description=desc, project=key, owner=owner, next=nxt, priority="p1", mover=OWNER, then=owner, by=by, extra={"terminal_prompt": name})      # The owner answers, then the project's -main agent takes it
    try:                     # a create sets no step: the state is a second write, and an item the state fails for (a refusal or any error) is closed again, never left half made
        _terminal_state(gid, name, by)
    except Exception:  # noqa: BLE001  — re-raised below; a crash between the two writes is repaired by the next open (the repeat path)
        try:
            _update_svc._update(gid, outcome_text=_terminal_bullets(f"{name}: the row could not be made", f"Closed by {sender} (a script on {machine})"), status="completed",
                    outcome="dropped", reason="the item could not be made whole", sender=by)
        except Exception as e2:  # noqa: BLE001
            print(f"terminal prompt: {_gh.shown(gid)} left open half made, not closed: {e2}", file=sys.stderr, flush=True)
        raise
    meta = _svcstore._load(gid).get("metadata") or {}
    return 200, {"item": _gh.shown(gid), "session": name, "project": str(meta.get("project") or key), "repeat": False}
