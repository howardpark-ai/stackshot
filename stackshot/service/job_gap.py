"""job_gap.py: `client.py post job-gap open|clear`, a gap in a scheduled job as one board item per (timer, code).

sala's job-gap watcher (`sala job check`) finds a timer or service of the host that is not in git or has no X-Model-Lane; `post job-gap open` files one item per (timer, code), moved by the builder of the project
that owns the repo holding the job's script, and `clear` closes it once the gap is fixed. Modelled on the terminal prompt (service/terminal_prompt.py, whose helpers it files its rows with): the same create path, a mark
in the item's metadata, the look for an open item and the write under one lock (`_JOBGAP_LOCK`), a script's row that owes the page nothing. `_JOBGAP_REPOS` is the default of [job_gap.repos].

A service module: it reads the config, the project record and the store and writes through `create_item` and the update tool's code. The route that calls it (`_client_post`) is the surface's.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import re
import threading
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core.store import _item_files
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model.field_gates import _close_reason_max, _fit, _next_line_max, _subject_max
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _registry
from stackshot.service import agents as _agents
from stackshot.service import create as _create_svc
from stackshot.service import item_read as _item_read
from stackshot.service import owner_words as _owner_words
from stackshot.service import store as _svcstore
from stackshot.service import terminal_prompt as _terminal
from stackshot.service import update as _update_svc
from stackshot.service import writes as _writes


# ----------------------------------------------------------------------------- a gap in a scheduled job (client.py post job-gap)
# sala's job-gap watcher (`sala job check`) finds a timer or service of the host that is not in git or has no X-Model-Lane. `post job-gap open` files one board item per
# (timer, code), moved by the builder of the project that owns the repo holding the job's script and kept by that project's -main agent; `clear` closes it once the watcher
# finds the gap fixed. Modelled on the terminal prompt (above): the same create path, a mark in the item's metadata, the look for an open item and the write under one lock, a
# script's row that owes the page nothing. Unlike a terminal prompt the item is not the owner's: its builder is told (once, at the create, through the needs notice) and no front
# agent is woken.
_JOBGAP_LOCK = threading.Lock()
_JOBGAP_REPOS: dict[str, str] = {}   # the default of [job_gap.repos] (no repo until the instance names its own): repo -> the project page that owns it
_JOBGAP_DETAIL_MAX = 600          # --detail: at most this many characters (the description keeps a few lines of it)
_JOBGAP_TIMER = re.compile(r"(?=.{1,120}\Z)[A-Za-z0-9](?:[A-Za-z0-9:_.\-]|(?<=[A-Za-z0-9])@(?=[A-Za-z0-9]))*")     # an @ only between letters or digits (a template unit, job@1.service): never one that starts a mention (a.@name)
_JOBGAP_CODE = re.compile(r"[a-z][a-z0-9-]{0,39}")
_JOBGAP_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9._-]{1,100}")
_JOBGAP_WORDS = {      # code -> (the gap in the subject, the gap in the first description bullet)
    "no-description": ("has no Description=", "has no Description= line"),
    "no-lane": ("has no X-Model-Lane", "has no X-Model-Lane= line"),
    "bad-lane": ("has a bad X-Model-Lane", "has an X-Model-Lane= that is not a lane sala knows"),
    "not-git": ("is not in git", "is not in git"),
    "git-differs": ("differs from its file in git", "differs from its file in git"),
}
_JOBGAP_FIX = {        # code -> the one fix line, {unit} and {repo} filled in
    "no-description": "add a Description= line to {unit}'s unit file in {repo}, linked from there",
    "no-lane": "put {unit}'s unit file in {repo} with an X-Model-Lane= line, linked from there",
    "bad-lane": "correct the X-Model-Lane= line of {unit}'s unit file in {repo}, linked from there",
    "not-git": "put {unit}'s unit file in {repo} with an X-Model-Lane= line, linked from there",
    "git-differs": "make {unit}'s installed file and its file in {repo} one (the file in git, linked from there)",
}
_JOBGAP_FIX_OTHER = "see the watcher's report for the fix to {unit} (its unit file is in {repo})"     # a code the table does not know: no guess at the fix


def _jobgap_repos() -> dict[str, str]:
    """[job_gap.repos]: "owner/repo" -> the project page key that owns it (lower-cased, through [github.moved]); absent = no repo is known (_JOBGAP_REPOS is empty). A table of another type reads as empty
    (no repo is known, never a wider rule than the file says); an entry that is not text is skipped. Read where it is used, so a reload applies."""
    sec = _cfg.get("job_gap")
    tab = _JOBGAP_REPOS if not isinstance(sec, dict) or "repos" not in sec else sec["repos"]
    if not isinstance(tab, dict):
        return {}
    return {_cfg.canon_repo(k): str(v).strip() for k, v in tab.items() if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()}


def _jobgap_mark(timer: str, code: str) -> str:
    return f"{timer}: {code}"


def _jobgap_open_items(mark: str) -> list[str]:
    """The ids of the open items marked as this (timer, code)'s gap (the mark is read as text first, so a store of thousands is cheap to scan)."""
    out = []
    for gid, p in _item_files():
        try:
            if '"job_gap"' not in p.read_text(encoding="utf-8"):
                continue
            it = _svcstore._load(gid)
        except (OSError, ValueError, ToolError):
            continue
        if it.get("status") == "open" and str((it.get("metadata") or {}).get("job_gap") or "") == mark:
            out.append(gid)
    return out


def _jobgap_post(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post job-gap open <timer> <code> --repo <owner/name> [--detail T] [--sender L]` and `… clear <timer> <code> [--sender L]`: sala's job-gap watcher says a timer or service of
    the host has a gap (code: no-description | no-lane | bad-lane | not-git | git-differs; any `[a-z][a-z0-9-]*` is taken) or that the gap is fixed. body: action (open | clear), timer, code,
    sender (default "client.py"), and for open the repo and an optional detail (at most 600 characters).
    open: one open item per (timer, code), filed through create_item (service/create.py: the create tool's own code: subject prefix, description and next gates, project page, GitHub mirror; a refusal is the tool's
    text, 400). The repo is mapped to its project page by [job_gap.repos] (else none): the config repo -> projects/config, salamander -> projects/example-two, stackshot -> projects/example;
    a repo it does not list is a 400 naming the ones it does. The mover is the project's builder (_builder_agent: the background agent whose mandate builds), the creator the project's front
    agent (its -main first); a project with no builder is moved by that -main agent, and the item says so (`fallback` in the answer). The subject is "<prefix> <timer>: <the gap>" (the project scope's prefix, else [subject] fallback_prefix, else the first prefix) cut to [subject]
    max_length, p2, the description says what the gap is and how to fix it, next "<mover>: <the fix>", marked metadata.job_gap = "<timer>: <code>". The builder is told once, at the create
    (the needs notice: the item names it in needs), no front agent is woken; the row owes the page nothing (a script's notification). A repeat open of an open (timer, code) changes nothing and
    answers the existing item. clear: closes the open item (outcome done, reason within [close] reason_max, bullets); with none open it does nothing and answers 200 (`cleared` empty).
    -> (status, {item, timer, code, project, mover, owner, repeat, fallback} | {timer, code, cleared: [ids], note})."""
    action = str(body.get("action") or "").strip()
    timer, code, repo, sender = (str(body.get(k) or "").strip() for k in ("timer", "code", "repo", "sender"))
    detail = body.get("detail") if isinstance(body.get("detail"), str) else ""
    sender = sender or "client.py"
    if action not in ("open", "clear"):
        return 400, {"error": "action = open | clear"}
    if not _JOBGAP_TIMER.fullmatch(timer):
        return 400, {"error": "timer = the unit's name (foo.timer, foo.service): letters, digits and @ : _ . - only, at most 120 characters"}
    if not _JOBGAP_CODE.fullmatch(code):
        return 400, {"error": "code = the gap's code (no-description | no-lane | bad-lane | not-git | git-differs): lower-case letters, digits and -, at most 40 characters"}
    if len(sender) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in sender):
        return 400, {"error": "sender = the script's own label: one line of at most 80 characters (unit-gaps)"}
    try:
        _owner_words._sender_not_owner(sender)
    except ToolError as e:
        return 400, {"error": str(e)}
    sender = _owner_words._no_ping(sender)        # the label goes into the description and the creator's name, which the GitHub mirror shows: an @name in it would ping that user
    mark, by = _jobgap_mark(timer, code), f"{sender} via a script on {machine}"
    rec: dict[str, Any] = {}
    if action == "open":
        if not _JOBGAP_REPO.fullmatch(repo):
            return 400, {"error": "repo = the repository that holds the job's script, as owner/name (--repo)"}
        repos = _jobgap_repos()
        page = repos.get(_cfg.canon_repo(repo))
        if not page:
            return 400, {"error": f"repo {repo!r} is not one this server knows: {', '.join(sorted(repos)) or 'none is listed'} ([job_gap.repos] maps a repo to the project page that owns it)"}
        detail = detail.strip()
        if len(detail) > _JOBGAP_DETAIL_MAX or any((ord(c) < 32 and c not in "\n\t") or ord(c) == 127 for c in detail):
            return 400, {"error": f"detail must be text of at most {_JOBGAP_DETAIL_MAX} characters ({len(detail)} now); shorten it, the watcher's own report has the rest"}
        try:
            recs = _prj.refs(page, _registry("projects"))
        except ValueError as e:
            return 503, {"error": f"the project record cannot be read right now, nothing was filed: {e}"}
        if len(recs) != 1:
            return 409, {"error": f"repo {repo} maps to {page}, which is {'no project page' if not recs else 'ambiguous'} in the registry; fix [job_gap.repos]"}
        rec = recs[0]
    try:
        with _JOBGAP_LOCK:           # the look for an open item and the write that follows are one step, so two calls for one gap file one item
            _writes.QUESTION.on = True      # the watcher's own detail is not judged for alarming words: a script's item must not be lost on a wording refusal (see _question)
            _writes.TERMINAL_ROW.on = True  # a script's notification: it owes no page, and a close tells no front agent (the builder is told at the create, by the needs notice)
            try:
                found = _jobgap_open_items(mark)
                if action == "clear":
                    return 200, _jobgap_clear(found, timer, code, sender, machine, by)
                return _jobgap_open(found, rec, repo, timer, code, detail, sender, machine, by, mark)
            finally:
                _writes.QUESTION.on = _writes.TERMINAL_ROW.on = False
    except ToolError as e:
        return 400, {"error": str(e)}


def _jobgap_clear(found: list[str], timer: str, code: str, sender: str, machine: str, by: str) -> dict[str, Any]:
    """Close every open item of the gap (one, unless an earlier failure left more) -> {timer, code, cleared: [ids as shown], note}; none open closes nothing."""
    done = []
    for gid in found:
        desc = _terminal._terminal_bullets(f"{timer}: the gap ({code}) is fixed", f"Closed by {sender} (a script on {machine}): the job-gap watcher no longer finds it")
        _update_svc._update(gid, outcome_text=desc, status="completed", outcome="done", reason=_fit(f"{code} is fixed on {timer}: sala's job-gap watcher no longer finds it", _close_reason_max()), sender=by)
        done.append(_gh.shown(gid))
    return {"timer": timer, "code": code, "cleared": done, "note": "" if done else f"no open item for {timer}: {code}; nothing was closed"}


def _jobgap_open(found: list[str], rec: dict[str, Any], repo: str, timer: str, code: str, detail: str, sender: str, machine: str, by: str, mark: str) -> tuple[int, dict[str, Any]]:
    if found:
        meta = _svcstore._load(found[0]).get("metadata") or {}
        return 200, {"item": _gh.shown(found[0]), "timer": timer, "code": code, "project": str(meta.get("project") or ""), "mover": _sr._session_label(str(meta.get("mover") or "")),
                     "owner": _sr._session_label(str(meta.get("owner") or "")), "repeat": True, "fallback": bool(meta.get("job_gap_fallback"))}
    key = rec["key"]
    front = sorted(_item_read._hub_sessions(key)[3], key=lambda n: (not n.endswith("-main"), n))
    if not front:
        return 409, {"error": f"{key} lists no front agent (a user-facing agent under `agents:` on its page, or its hub's), so there is nobody to keep the item; a front agent lists itself first (client.py post project-agent)"}
    owner = front[0]
    builder = _agents._builder_agent(key)
    mover = builder or owner
    gap, what = _JOBGAP_WORDS.get(code, (f"has the gap {code}", f"has the gap {code}"))
    fix = _JOBGAP_FIX.get(code, _JOBGAP_FIX_OTHER).format(unit=timer, repo=repo)
    lines = [f"{timer} {what} (found by sala's job-gap watcher on {machine})", f"Fix: {fix}", f"{repo} is {key}'s repo; the unit lives there with X-Model-Lane= so every job has a lane"]
    if detail:
        lines.insert(1, _owner_words._no_ping(" ".join(detail.split())))      # the watcher's text may carry an @name (a path, a mail address): broken so the mirror pings no one
    if not builder:
        lines.append(f"{key} lists no builder, so this is with {owner}, its front agent")
    lines.append(f"Opened by {sender} (a script on {machine}); it closes when the watcher finds the gap fixed")
    desc = _terminal._terminal_bullets(*lines)
    pfx_, tail_ = _terminal._terminal_subject_prefix(str(rec.get("scope") or "")), f": {gap}"
    timer_ = _svcstore._shown_ids(timer)
    room_ = (_subject_max() - len(pfx_) - len(tail_)) if _subject_max() else 0      # a long unit name is cut so the server's own subject is never refused (as the terminal prompt's)
    subject = f"{pfx_}{_fit(timer_, room_) if 8 <= room_ < len(timer_) else timer_}{tail_}"
    if _subject_max():
        subject = _fit(subject, _subject_max())
    nxt = _fit(f"{mover}: {fix}", _next_line_max())
    extra: dict[str, Any] = {"job_gap": mark}
    if not builder:
        extra["job_gap_fallback"] = True
    gid, _reply = _create_svc.create_item(subject=subject, description=desc, project=key, owner=owner, next=nxt, needs=[builder] if builder else "", priority="p2", mover=mover, by=by, extra=extra)
    meta = _svcstore._load(gid).get("metadata") or {}
    return 200, {"item": _gh.shown(gid), "timer": timer, "code": code, "project": str(meta.get("project") or key), "mover": _sr._session_label(mover), "owner": _sr._session_label(owner),
                 "repeat": False, "fallback": not builder}
