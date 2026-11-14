"""item_open.py: `client.py post item-open`, an item a script opens for a background agent of a project.

A timer's script that finds work for a project's background agent asks for one board item of that work. The route is narrow on purpose: the mover must be a background agent the project's page lists, the subject takes
the project scope's prefix from the server, the description is bullets within the create tool's limits, and the item is marked with the caller's marker (`metadata.item_open`): while an item with that marker is open on
the same project a repeat call answers it and files nothing. `_ITEMOPEN_LOCK` makes the look for an open item and the write one step. The helpers it files its rows with are service/terminal_prompt.py's.

A service module: it reads the project record, the anchors' registry and the store and writes through `create_item`. The route that calls it (`_client_post`) is the surface's.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import re
import threading
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.store import _item_files
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import bullet_text as _bt
from stackshot.model.field_gates import _description_limits
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _registry
from stackshot.service import create as _create_svc
from stackshot.service import item_read as _item_read
from stackshot.service import owner_words as _owner_words
from stackshot.service import store as _svcstore
from stackshot.service import terminal_prompt as _terminal
from stackshot.service import writes as _writes


# ----------------------------------------------------------------------------- an item a script opens for a background agent (client.py post item-open)
# A timer's script that finds work for a project's background agent (a weekly report past a threshold) asks for one board item of that work. The route is narrow on purpose: the item's mover
# must be a background agent the project page lists, the subject takes the project scope's prefix from the server, the description is bullets within the create tool's limits, the step names
# the mover, and the item is marked with the caller's marker: while an item with that marker is open on the same project a repeat call answers it and files nothing, after it is closed a call files a new one; a project holds at most _ITEMOPEN_OPEN_MAX open items of this route.
_ITEMOPEN_LOCK = threading.Lock()
_ITEMOPEN_KEYS = ("marker", "project", "subject", "description", "step", "mover", "sender")
_ITEMOPEN_MARKER = re.compile(r"[a-z][a-z0-9_.-]{0,39}:[A-Za-z0-9][A-Za-z0-9._/-]{0,79}")      # "<kind>:<what>", for example test_trim:stackshot: no spaces, no markup
_ITEMOPEN_SENDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,59}")                               # the script's label: a word, never markup or a mention
_ITEMOPEN_ATTRIBUTION = "Opened by {sender} (a script on a client machine)"
_ITEMOPEN_OPEN_MAX = 10                                                                          # open items this route may hold per project: a marker that changes every run cannot pile up items


def _itemopen_open_items(project: str) -> list[tuple[str, str]]:
    """(id, marker) of every open item this route filed under `project` (the page key), read from the store (the mark is looked for as text first, so a store of thousands is cheap to scan).
    A marker belongs to its project: the same marker on another project is another item."""
    out = []
    for gid, p in _item_files():
        try:
            if '"item_open"' not in p.read_text(encoding="utf-8"):
                continue
            it = _svcstore._load(gid)
        except (OSError, ValueError, ToolError):
            continue
        meta = it.get("metadata") or {}
        if it.get("status") == "open" and str(meta.get("item_open") or "") and str(meta.get("project") or "") == project:
            out.append((gid, str(meta["item_open"])))
    return out


def _itemopen_lines(raw: Any) -> tuple[list[str], str]:
    """The description a script wrote -> (its lines without their markers, "") or ([], why it is refused). A list of lines or one text of lines; a line is refused, never clipped, when it reads
    longer than [description] line_max as a bullet, and a text with more lines than [description] max_lines less the attribution line is refused (as the create tool refuses prose and a long list)."""
    if raw is None:
        raw = ""
    if isinstance(raw, list):
        if not all(isinstance(x, str) for x in raw):
            return [], "description is a list of text lines"
        raw = "\n".join(raw)
    if not isinstance(raw, str):
        return [], "description is bullets: a list of lines, or one text of lines"
    if any((ord(c) < 32 and c not in "\n\t") or ord(c) == 127 for c in raw):
        return [], "description holds a control character"
    lines = [_owner_words._no_ping(" ".join(t.split())) for t in _bt.clean_lines(raw)]
    max_lines, line_max = _description_limits()
    if not lines:
        return [], "description has no line of words: send the item's background as short lines, one fact each"
    if len(lines) > max_lines - 1:
        return [], f"description has {len(lines)} lines and an item's description takes at most {max_lines - 1} here (one more line says who opened it); shorten it"
    for i, t in enumerate(lines, 1):
        if _bt.visible_len("- " + t) > line_max:
            return [], f"description line {i} reads {_bt.visible_len('- ' + t)} characters and a line takes at most {line_max}; shorten it"
    return lines, ""


def _itemopen_post(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post item-open <marker> --project P --subject S --mover M --step "<M>: ..." --line "..." [--line ...] [--sender L]`: a script asks for ONE board item for a background agent of project P.
    body: marker (`<kind>:<what>`, the item's mark), project (an id, a page key or a bare slug), subject (the action and its object, no prefix: the server puts the project scope's prefix before it, and a
    prefix the caller wrote is replaced), description (the bullets: a list of lines or one text of lines), step (one line that starts `<mover>: `), mover (a background agent listed under `background:` on the
    project's page, nobody else: a front agent, the owner, an unlisted name are refused), sender (the script's own label, one word; default client.py). Any other key is refused.
    The item is filed through create_item (service/create.py), the create tool's own code, so the subject, description and next gates, the project page and the GitHub mirror all apply and a refusal is the tool's text (400);
    the caller picks no field the tool does not take for a script (no needs, owner, priority, ask or date). The project's front agent (its -main first) is the item's creator and the mover is named in needs, so it is
    told once at the create. The description ends with "- Opened by <sender> (a script on a client machine)": no host name reaches the item or its GitHub issue. Marked metadata.item_open = <marker>; while an item with
    the marker is open on this project (read from the store; the marker is per project) a repeat call answers it and files nothing, and once it is closed a call files a new one. A project holds at most 10 open items filed by this route: past it a new marker is a 400 until one closes (a repeat never counts). The row owes no page, as every script route's. 404 no such project, 409 no front agent
    to file under, 503 the project record cannot be read. -> (status, {item, marker, project, mover, owner, repeat})."""
    extra_keys = sorted(k for k in body if k not in _ITEMOPEN_KEYS)
    if extra_keys:
        return 400, {"error": f"not taken: {', '.join(str(k) for k in extra_keys)}; item-open takes {', '.join(_ITEMOPEN_KEYS)} and nothing else"}
    for k in ("marker", "project", "subject", "step", "mover", "sender"):
        if k in body and not isinstance(body[k], str):
            return 400, {"error": f"{k} is text"}
    marker, project, subject, step, mover, sender = (" ".join(str(body.get(k) or "").split()) for k in ("marker", "project", "subject", "step", "mover", "sender"))
    if not marker:
        return 400, {"error": "marker is required: the item's mark, <kind>:<what> (for example test_trim:stackshot), the same every time the same piece of work is asked for"}
    if not _ITEMOPEN_MARKER.fullmatch(marker):
        return 400, {"error": "marker = <kind>:<what>: a lower-case kind (at most 40 characters of letters, digits, _ . -), a colon, then at most 80 characters of letters, digits and _ . - / (no spaces)"}
    for k, v in (("project", project), ("subject", subject), ("step", step), ("mover", mover)):
        if not v:
            return 400, {"error": f"{k} is required"}
    if any(ord(c) < 32 or ord(c) == 127 for c in str(body.get("subject")) + str(body.get("step"))):
        return 400, {"error": "subject and step are one line each, with no control character"}
    sender = sender or "client.py"
    if not _ITEMOPEN_SENDER.fullmatch(sender):
        return 400, {"error": "sender = the script's own label: one word of letters, digits and _ . - (at most 60 characters), no spaces or markup"}
    try:
        _owner_words._sender_not_owner(sender)
    except ToolError as e:
        return 400, {"error": str(e)}
    lines, why = _itemopen_lines(body.get("description"))
    if why:
        return 400, {"error": why}
    try:
        recs = _prj.refs(project, _registry("projects"))
    except ValueError as e:
        return 503, {"error": f"the project record cannot be read right now, nothing was filed: {e}"}
    if not recs:
        return 404, {"error": f"no project {project!r}: an id (prj_<8 hex>), a page key or a bare slug of a page in the registry"}
    if len(recs) > 1:
        return 400, {"error": f"{project!r} is ambiguous: it names {' and '.join(r['key'] for r in recs)}; write the full key or the id"}
    rec = recs[0]
    key = rec["key"]
    back = sorted(str(x) for x in ((_anc.registry().get(key) or {}).get("back_agents") or {}))
    if mover not in back:
        return 400, {"error": f"mover {mover!r} is not a background agent listed on {key}'s page (its agents map): " + (", ".join(back) or "the page lists none")}
    if not step.startswith(mover + ": ") or not step[len(mover) + 2:].strip():
        return 400, {"error": f"step is one line that starts with the mover's name: '{mover}: <what it does>'"}
    front = sorted(_item_read._hub_sessions(key)[3], key=lambda n: (not n.endswith("-main"), n))
    if not front:
        return 409, {"error": f"{key} lists no front agent (a user-facing agent under `agents:` on its page, or its hub's), so there is nobody to keep the item; a front agent lists itself first (client.py post project-agent)"}
    owner = front[0]
    by = f"{sender} (a script on a client machine)"
    prefixes = list(_cfg.CFG["subject"]["prefixes"])
    subject = _svcstore._shown_ids(subject)
    bare = [p.strip() for p in prefixes if p.strip()]
    def _prefix_at_start(text: str) -> str:
        """the instance prefix the text starts with, when it is a prefix of its own: a space, the end of the text or another prefix follows it (so `[work]-style fix` keeps its bracket word)"""
        for b in bare:
            if text.startswith(b):
                rest = text[len(b):]
                if not rest or rest[0].isspace() or any(rest.startswith(o) for o in bare):
                    return b
        return ""
    while (hit := _prefix_at_start(subject)):      # every prefix the caller wrote comes off: the scope's prefix is the server's to choose, and goes on once
        subject = subject[len(hit):].lstrip()
    if not subject:
        return 400, {"error": "subject is only an instance prefix: write the action and its object after it (the server puts the project's prefix on)"}
    subject = _terminal._terminal_subject_prefix(str(rec.get("scope") or "")) + subject
    desc = _terminal._terminal_bullets(*lines, _ITEMOPEN_ATTRIBUTION.format(sender=sender))
    try:
        with _ITEMOPEN_LOCK:         # the look for an open item and the write that follows are one step, so two calls for one marker file one item
            open_here = _itemopen_open_items(key)
            found = [g for g, m_ in open_here if m_ == marker]
            if found:
                meta = _svcstore._load(found[0]).get("metadata") or {}
                return 200, {"item": _gh.shown(found[0]), "marker": marker, "project": str(meta.get("project") or key), "mover": _sr._session_label(str(meta.get("mover") or "")),
                             "owner": _sr._session_label(str(meta.get("owner") or "")), "repeat": True}
            if len(open_here) >= _ITEMOPEN_OPEN_MAX:
                return 400, {"error": f"{key} already has {len(open_here)} open items filed by this route and the cap is {_ITEMOPEN_OPEN_MAX}: an open item must close before another is filed "
                                      "(a repeat of an open marker is always answered; a marker that changes on every run is the usual cause)"}
            _writes.TERMINAL_ROW.on = True  # a script's notification: it owes no page (the mover is told at the create, by the needs notice)
            try:
                gid, _reply = _create_svc.create_item(subject=subject, description=desc, project=key, owner=owner, next=step, needs=[mover], mover=mover, by=by, extra={"item_open": marker})
            finally:
                _writes.TERMINAL_ROW.on = False
    except ToolError as e:
        return 400, {"error": str(e)}
    meta = _svcstore._load(gid).get("metadata") or {}
    return 200, {"item": _gh.shown(gid), "marker": marker, "project": str(meta.get("project") or key), "mover": _sr._session_label(mover), "owner": _sr._session_label(owner), "repeat": False}
