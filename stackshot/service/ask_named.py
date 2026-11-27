"""ask_named.py — the open asks that a message named to a session during its turn (the client read `asks-named`).

An ask can stay on the owner's move while the session that wrote it is redrawing what it asks about. The end-of-turn board question
(projects/pages.py) therefore lists, on its own, each item with a standing ask that a message which reached the session since its turn began
names, when the session wrote the ask or the item's notices go to it (its mover, or its `then` while the owner moves it). An ask written or
rewritten since the turn began is not listed.

A message reached the session when the message log has a row to it that was delivered, queued or put in its inbox, or when
held.reached_since has its words (a held line its hook printed, a router pass delivered to it). A message that was refused, archived or is
still held reached nobody. A service module: it only reads."""
from __future__ import annotations

import json
import math
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.github import ghsync as _gh
from stackshot.model import ask_leaves as _askl
from stackshot.service import agent_names as _agent_names
from stackshot.service import asks as _asks
from stackshot.service import handoff as _handoff
from stackshot.service import messaging as _messaging
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.waits import held as _held

GRACE = 30.0        # s before the turn's start from which a message still counts: the one that opens the turn is recorded within moments of it, by another clock
ITEMS_MAX = 20      # items in one answer


def _client_asks_named(key: str, since: str) -> tuple[int, str, str]:
    """`asks-named?key=<session>&since=<epoch seconds the turn began>` → {"items": [{gid, shown, subject, ask}]}."""
    k = str(key or "").strip()
    if not k or len(k) > 200 or any(c in k for c in "\r\n\t"):
        return 400, "text/plain", "key = the asking session: its transcript uuid, cse_ id or pane name"
    try:
        start = float(since)
    except (TypeError, ValueError):
        start = 0.0
    if not (math.isfinite(start) and start > 0):
        return 400, "text/plain", "since = when the session's turn began, in epoch seconds"
    return 200, "application/json", json.dumps({"items": _named(k, start)}, ensure_ascii=False)


def _named(key: str, start: float) -> list[dict[str, Any]]:
    seen: dict[str, bool] = {}

    def me(who: str) -> bool:
        if who not in seen:
            seen[who] = _handoff.ho_same(who, key)
        return seen[who]
    floor = start - GRACE
    texts = [str(d.get("text") or "") for d in _messaging._log_rows(floor) if _messaging._reached(d) and me(str(d.get("to") or ""))]
    texts += _held.reached_since(floor, key, _anc.canonical(key))
    out: list[dict[str, Any]] = []
    for gid in dict.fromkeys(g for t in texts for g in _agent_names._item_refs(t)):
        item = {**_svcstore._load(gid), "gid": gid}
        ask = _asks._ask_stands(item)
        if not ask:
            continue
        rec = _askl.rec_of(item.get("metadata") or {})      # {} for an ask stored before the record: nothing says who wrote it or when
        if float(rec.get("at") or 0) >= start:
            continue
        if not (me(str(rec.get("by") or "")) or me(_telling.holder(item))):
            continue
        out.append({"gid": gid, "shown": _gh.shown(gid), "subject": str(item.get("subject") or ""), "ask": ask})
        if len(out) >= ITEMS_MAX:
            break
    return out
