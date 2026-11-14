"""answer_handover.py: where an item goes after the owner's answer, a Done or the end of a wait.

The helpers the answer path and the wait passes share: `_hand_to_mover` is the one place an answer or a Done gives an item to its then-mover (mover = the session, `then` cleared, the session named first in needs);
`_then_live` is the test every hand-over to a stored `then` makes (a background agent of the item's project, or a session live or in the cloud); `_hand_stored_then` hands an item whose wait just ended to its stored
`then`; `_decision_hand_over` takes the item out of his hands once his decision is in (the stored `then`, a time wait for a parked item, the default mover); `_check_his_step` ticks the lines of his own that his Done
finishes; `_keep_note` keeps an answer note that has no decision to go with it as his comment and tells the mover; `_answer_line` and `_client_answer` are the line `client.py get answer` prints.

A service module: it reads the store and writes an item only through `writes.save`, under the locks the caller holds. The delivery of the answer, the form's note words and the renderer's reader of the answers are the
surface's (the answer form, web/answers.py and web/server.py `_answer_deliver`), reached through service/save_hooks.py. A suite that replaces one of these sets it on this module (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core.instance import OWNER
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model import nextlines as _nl
from stackshot.model import steps as _steps
from stackshot.model.ids import _norm_id
from stackshot.model.needs import _NEEDS_KINDS, _canon_needs, _needs_kinds, _needs_of, _needs_sessions, _needs_store
from stackshot.service import item_read as _item_read
from stackshot.service import store as _svcstore
from stackshot.service import writes as _writes
from stackshot.service.save_hooks import hooks as _hooks
from stackshot.waits import until_write as _uw
from stackshot.waits import waiting as _wt
from stackshot.waits import watchers as _watch


def _answer_line(item: dict[str, Any]) -> str:
    """The owner's answer on an item as the one line `client.py get answer` prints: `<kind>` TAB `<chosen option's label>` TAB `<text>` TAB
    `<when>`; "" when he has not answered. It is his newest decision (kind decision: he answered the item, with an option or in words),
    even when he commented after it; only when he has decided nothing, his newest comment (kind comment). So a later comment never
    hides a decision, and a caller resumes on a decision only. The label is empty when he picked none, the text's line breaks are " / " and
    its tabs spaces, and `when` is when he gave it, an ISO time in the instance's timezone (empty when the answer carries none).
    metadata.answers is oldest first (as in the get tool); the line does not know which question it answers, so a caller files a new item
    for each question."""
    ans = _hooks().answers_of(item)
    if not ans:
        return ""
    a = next((x for x in reversed(ans) if x.get("kind") != "comment"), ans[-1])
    one = lambda v: " / ".join(" ".join(ln.split()) for ln in str(v or "").splitlines() if ln.strip())
    try:
        when = dt.datetime.fromtimestamp(float(a["ts"]), _hooks().zone()).isoformat(timespec="seconds")
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        when = ""
    return f"{'comment' if a.get('kind') == 'comment' else 'decision'}\t{one(a.get('choice'))}\t{one(a.get('text'))}\t{when}"


def _client_answer(key: str) -> tuple[int, str, str]:
    """`client.py get answer board#N` -> (status, content type, body): the answer line (_answer_line) or an empty body, 404 for an id that
    names no item."""
    if not key.strip():
        return 400, "text/plain", "key = an item id as shown: board#<n>"
    try:
        it = _svcstore._load(_norm_id(key))
    except ToolError as e:
        return 404, "text/plain", str(e)
    line = _answer_line(it)
    return 200, "text/plain; charset=utf-8", line + "\n" if line else ""


def _hand_to_mover(meta: dict[str, Any], who: str) -> None:
    """The one place an answer or a Done gives an item to its then-mover (a session, never he): mover = who, `then` cleared, and who is named in needs, first among the sessions, so the pending
    answer, the notice (notice_to) finds it and not the page's keeper. The decision path and the Done path both call this, so they cannot drift."""
    sid = _hooks().session_id(who)
    meta["mover"] = who
    meta.pop("then", None)
    _needs_store(meta, _canon_needs([sid, *[x for x in _needs_of(meta) if x.lower() in _NEEDS_KINDS or _hooks().session_id(x) != sid]]))


def _then_live(then: str, meta: dict[str, Any]) -> bool:
    """Is `then` a session that can take an item now: a background agent of the item's project, or a session that is live or in the cloud? The one test every hand-over to a stored `then`
    makes (a decision answer, the end of a wait), so a retired, unknown or free-text name never becomes a mover."""
    ctx = _mg.Ctx()
    return bool(ctx.background_of(then, str(meta.get("project") or "")) or ctx.session_state(then) in ("live", "cloud"))


def _hand_stored_then(gid: str, item: dict[str, Any], meta: dict[str, Any]) -> bool:
    """A wait just ended on `meta` (the old wake pass, the release of an `after` link). A `then` stored on the item was waiting for the owner's move, so it takes the item only when that is what
    the item was: the stored mover is he or absent, no session is named in needs, and with a stored mover he dropped the item reads alive and not his (no decision in needs, no your-call or
    your-step, no other wait). An item whose stored mover or needs already name an agent is left alone (an agent-set `then` must not take an item from the agent working it), and so is a `then`
    that is not a live session (_then_live: free text, a retired or unknown name). A `then` left over when this declines is dropped where it follows nobody (the model reads a `then` only while the owner is the mover, so it
    would only sit unread): when it already is the stored mover or is named in needs, or is not a live session; in any other case (the item still reads as waiting or his) it stays.
    Then: the stored mover he goes, mover = `then` named first in needs (_hand_to_mover), and the notice the release sends (notice_to reads needs) reaches it. → True when handed."""
    then = _model.norm_who(meta.get("then"))
    if not then or _model.is_owner(then):
        return False
    if not _then_live(then, meta):
        meta.pop("then", None)
        return False
    mover_s = _model.norm_who(meta.get("mover"))
    if (mover_s and not _model.is_owner(mover_s)) or _needs_sessions(meta):
        sid = _hooks().session_id(then)
        if (mover_s and _hooks().session_id(mover_s) == sid) or any(_hooks().session_id(x) == sid for x in _needs_sessions(meta)):
            meta.pop("then", None)      # the `then` already is the mover or is named in needs: it follows nobody
        return False
    probe = {k: v for k, v in meta.items() if k != "mover"}
    mod = _item_read._model_of({**item, "gid": gid, "metadata": probe})
    if mod.state != _model.ALIVE or _model.is_owner(mod.mover):
        return False
    meta.pop("mover", None)
    _hand_to_mover(meta, then)
    return True


def _decision_hand_over(meta: dict[str, Any], mover_in: str, then_in: str, parked: bool = False, waiting: bool = False, now: float = 0.0) -> str:
    """His decision is in (decision already out of needs, your-call ended): the item leaves his hands, as a Done does on a step. With a stored `then` (a session, not he) the
    item goes to it at once (_hand_to_mover: mover = then, `then` cleared, named first in needs).
    A `then` that is no live session (_then_live: free text, retired, unknown) is dropped first, and the item takes the no-`then` path below.
    With no `then`, a stored mover that is he is dropped, so the item reads as it does when nothing is stored: the first session in needs, else the project's builder or -main agent (the model's default `then`).
    An item that still reads as waiting after the answer (`waiting`; a park, a pick carrying a wake, is one) has no mover: a stored mover that is he goes, and a stored `then` is kept for
    whoever ends the wait only where the code that ends that wait hands it over. By what the wait is:
      an open `after` link: `then` stays; _wakes.release_after hands the item to it when the last prerequisite closes (_hand_stored_then), with its usual notice;
      a hold with a wake (and no `external`, no open `after`, no wait already stored): a time wait, wait_kind=time and mover=`then` (watch.set_at stamped, as an update does), `then` cleared,
        so the watcher's wake hands the item to it; `update clear_hold=true` drops that wait with the hold. With `[model] watchers = false` no time wait is stored: the park stays as it was, `then`
        with it, and the old wake pass hands the item to it when the hold ends (_hand_stored_then);
      `external` in needs, a hold with no wake, any other shape: `then` is dropped (nothing reads it when such a wait ends, and a stale one would sit on the item unread); the wait's own
        mover (the first session in needs, else the project's builder or -main agent) takes it when it ends. A wait already stored as a watcher's keeps its own post-wake mover.
    Without this a stored mover=the owner stayed on an item whose state had become doing: "model conflict: mover=the owner on an item whose state is doing", and needs read as the keeper. → who the item was handed to now ("" when to nobody): it is told it is the mover."""
    then = "" if _model.is_owner(then_in) else then_in
    if then and not _then_live(then, meta):      # a `then` that is no live session (free text, retired, unknown) takes nothing, here or at the end of a wait: it is dropped and the item falls back to needs or the project's default mover
        meta.pop("then", None)
        then = ""
    if parked or waiting:
        if _model.is_owner(mover_in):
            meta.pop("mover", None)
        if _model.is_owner(then_in):
            meta.pop("then", None)
        elif then and not _uw.kind_of(meta):               # no wait stored as a kind (an until alone is a wait on the date, with no kind)
            if "external" in _needs_kinds(meta):
                meta.pop("then", None)
            elif _item_read._after_open(meta):
                pass
            elif (meta.get("hold") and meta.get("wake")) or _wt.stored_until(meta):
                if _watch.enabled():      # a stored time wait is the watcher's (watchers.watches): its wake hands the item to the post-wake mover; the old wake pass would only put it back in its lane
                    if _wt.stored_until(meta):
                        _model.store_picker(meta, then)       # a wait on the date alone stores no kind (until is the whole of it)
                    else:
                        meta["wait_kind"] = "time"
                        _model.store_picker(meta, then)
                    meta["watch"] = {**(meta["watch"] if isinstance(meta.get("watch"), dict) else {}), "set_at": now or time.time()}
                    meta.pop("then", None)
                # [model] watchers = false: no watcher would wake it, so no time wait is stored. The old park stays with `then` on it, and the old wake pass hands the item over when the hold ends (_hand_stored_then)
            else:
                meta.pop("then", None)
        return ""
    if then:
        _hand_to_mover(meta, then)
        return then
    if _model.is_owner(mover_in):
        meta.pop("mover", None)
    if _model.is_owner(then_in):      # a `then` that names him follows nobody: it would read as a conflict once the mover is not he
        meta.pop("then", None)
    return ""


def _check_his_step(meta: dict[str, Any], step: str, now: float) -> str:
    """his Done (his word that his step is done; an empty Send from a page loaded earlier is the same) checks the open steps of the item's checklist that are his, the lines the Your step block shows
    (steps.is_his: named for him, or naming no one), whoever wrote them, the server's own line for the summary included (the block does not draw that line or a repeat, but his Done is his word that all of it is done). Sets metadata.steps and takes the lines out of next with their writers (nextlines.prune), the
    other lines staying. → the first checked step's first line, "" when none was his (nothing written). A note on the step (step-reply) never comes here: it ticks only the server's step (owner_steps.tick), and the session that takes the item
    marks the lines it wrote when it judges the step finished. `step` (the item's one-line summary) is not looked for in the lines: his Done finishes all of his open lines."""
    cl = _steps.view(meta)
    mine = [i for i, x in enumerate(cl) if x["status"] == _steps.OPEN and _steps.is_his(x["text"])]      # the open lines render.his_open_steps starts from, before it leaves out the server's summary line and repeats
    if not mine:
        return ""
    for i in mine:
        cl[i] = {"text": cl[i]["text"], "status": _steps.DONE, "by": OWNER, "at": now}
    _nl.prune(meta, [cl[i]["text"] for i in mine], str(meta.get("owner") or ""))
    meta["steps"] = _steps.stored(cl)
    return _steps.first_line(cl[mine[0]]["text"])


def _keep_note(gid: str, item: dict[str, Any], note: str, code: str, pick: str = "", why: str = "") -> str:
    """An answer note that has no decision to go with it (the item is closed, or the question it answered has changed) is kept as his comment on the item and told to the mover, as any comment of his
    is: the board never drops what he wrote. `pick` is the option he sent with it and `why` the words that name it in front of the note ("the item is closed", "the item no longer asks this"). A second
    send of the same thing is a no-op: the same text, or the same pick with the same note that a decision just recorded, among the item's latest answers within ten minutes (a double click).
    → `code`, the notice the page shows (it says the note was kept). The caller holds the item and answer locks."""
    now = time.time()
    meta = dict(item.get("metadata") or {})
    text = f"({why}: {pick}) {note}" if why and pick else note
    def _ts(a: dict[str, Any]) -> float:
        try:
            return float(a.get("ts") or 0)
        except (TypeError, ValueError):      # a hand-edited record
            return 0.0
    for a in (meta.get("answers") if isinstance(meta.get("answers"), list) else [])[-3:]:
        if isinstance(a, dict) and now - _ts(a) < 600 and (a.get("text") == text or (pick and a.get("choice") == pick and a.get("text") == note)):
            return code
    rec: dict[str, Any] = {"ts": now, "kind": "comment", "text": text, "via": "board"}
    prior = meta.get("answers") if isinstance(meta.get("answers"), list) else []
    meta["answers"] = [*prior, rec]
    item["metadata"], item["updated"] = meta, now
    _writes.save(gid, item, note=_hooks().answer_note(rec), author=(OWNER, "board"))
    item["gid"] = gid
    told = [t for t in _hooks().answer_deliver(gid, item, rec) if t]
    print(f"answer: {gid} {code}: his note kept as a comment, told {', '.join(told) or 'nobody'}", file=sys.stderr, flush=True)
    _hooks().publish()
    return code
