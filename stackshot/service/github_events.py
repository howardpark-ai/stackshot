"""github_events.py: what the GitHub mirror's reader reports to the board: an item that took its issue number (`_rekeyed`) and the owner's own comment on an item's issue (`_github_comment`).

The two are the hooks ghsync calls (`_gh.on_rekey`, `_gh.on_comment`), which web/server.py sets at its import. The publish and the session id of a name are the surface's, reached through `Hooks` in
service/passes_hooks.py, looked up when they run. A suite that replaces a function or the clock of the hooks sets it here (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import instance as _inst
from stackshot.core.instance import OWNER
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import activity as _activity
from stackshot.service import handoff as _handoff
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service.passes_hooks import hooks as _hooks
from stackshot.waits import handoff as _ho


def _rekeyed(old: str, new: str, item: dict[str, Any]) -> None:
    """ghsync's re-key hook: an item that had a temporary id has taken its issue number; its mover
    hears the new id in one plain line (the creator is no one's to tell). The old id still resolves to it (an alias), so a front
    agent mover, which no item notice wakes, is not told: its old id still names the item."""
    meta = item.get("metadata") or {}
    owner = _telling.holder(item)
    if owner and _telling.front_keeper(owner, str(meta.get("project") or ""))[0]:
        print(f"owner: {old} is now {new}; its mover {_sr._session_label(owner)} is a front agent, not told (the old id still resolves)", file=sys.stderr, flush=True)
        return
    _telling.tell_woken(new, _hooks().session_id(owner) if owner else "", f"[stackshot] {_gh.shown(old)} is now {_gh.shown(new)} (the item took its issue number; "
                f"{_gh.shown(old)} still names it): {item.get('subject') or ''} → {_inst.BOARD_URL}/items/{_gh.href_id(new)}", tag="owner")


def _github_comment(gid: str, c: dict[str, Any]) -> bool:
    """ghsync's hook for the owner's own comment on an item's issue. The comment
    is recorded on the item under metadata.answers, the list the board's answer buttons write too (the board's
    answer box): {ts, kind: "comment", text, via: "github", url, comment_id}, `via` being the flag that it was written
    on GitHub. The save is the server's own (no author): the mirror carries no answers, so the owner's comment is never posted back to the issue. Then the mover and the sessions named in
    its needs are told one line each (tell_comment). Reading only: needs, status and the page stay as they are. → False when
    no item has the id (the reader skips the comment); True when it is on the item (a second call for the same comment, after
    a restart between the save and the reader's mark, tells nobody again)."""
    with _writes.ITEM_LOCK:        # it reads, changes the hand-off record and saves, so it takes turns with an update and an answer
        try:
            item = _svcstore._load(gid)
        except ToolError:
            return False
        meta = item.get("metadata")
        if not isinstance(meta, dict):
            meta = item["metadata"] = {}
        answers = [a for a in meta["answers"] if isinstance(a, dict)] if isinstance(meta.get("answers"), list) else []
        if any(a.get("comment_id") == c.get("id") for a in answers):
            return True
        answers.append({"ts": float(c.get("ts") or time.time()), "kind": "comment", "text": str(c.get("text") or ""), "via": "github",
                        "url": str(c.get("url") or ""), "comment_id": c.get("id")})
        meta["answers"] = answers
        try:
            r_ = _ho.pending_his(item)
            if _handoff.handoff_on() and r_ and float(c.get("ts") or time.time()) >= float(r_.get("at") or 0):      # his comment, made after the hand-off, ends his hand-off record
                _ho.answered(item, time.time(), f"{OWNER} commented on GitHub", at=float(c.get("ts") or time.time()))
        except Exception as e:  # noqa: BLE001
            print(f"handoff: {gid} his hand-off not ended: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        _writes.save(gid, item, activity=_activity.ANSWER, activity_at=float(c.get("ts") or 0) or None)      # the owner's comment is an answer: real activity though the save is the server's, stamped at the comment's own time (a backlog read after a restart is not activity now)
    _hooks().publish()
    _telling.tell_comment(gid, item, str(c.get("text") or ""))
    return True
