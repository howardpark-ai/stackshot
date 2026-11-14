"""anchors.py: the `anchors` tool: what the board watches for an item or a project, and the machine and mailbox listings it carries."""
from __future__ import annotations

import json
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field

from stackshot.anchors import anchors as _anc, machine_anchor as _ma
from stackshot.core import config as _cfg
from stackshot.model.ids import _norm_id
from stackshot.service import telling as _telling
from stackshot.web.auth import oauth as _oauth
from stackshot.service import gates as _gates
from stackshot.web.publish import _publish
from stackshot.web.tools.text import _ANCHOR_SHAPES, _GMAIL_TERMS, _lead, load_text

_T = load_text("anchors")

_evw_boxes = None      # set by register: the server's own, looked up at each call
_machine_state = None      # set by register: the server's own, looked up at each call


_ANCHORS_DESC = (
    _T.description("anchors")
)


def stackshot_anchors(project: Annotated[str, Field(description=_T.param("project"))],
                      add: Annotated[list[str] | None, Field(description=_T.param("add"))] = None,
                      items: Annotated[list[str] | None, Field(description=_T.param("items"))] = None,
                      remove: Annotated[list[str] | None, Field(description=_T.param("remove"))] = None) -> str:
    return _anchors(project, add, items, remove, _oauth._who())


def _gmail_boxes() -> dict[str, str]:
    """{name: address} of the mailboxes the anchors service reads (its status file's google.mailboxes), the names a Gmail query anchor can scope itself to; {} when the anchors service has not said (not running, or no Google account)."""
    try:
        d = json.load(open(_cfg.state("anchor-hub", "status.json"), encoding="utf-8")).get("google") or {}
        return {str(k): str(v) for k, v in (d.get("mailboxes") or {}).items()}
    except Exception:  # noqa: BLE001
        return {}


def _gmail_key(u: str, boxes: dict[str, str]) -> str:
    """The identity of a scoped Gmail query URL: its mailbox names as the labels spell them, its #mention fragment kept; "" for any other URL."""
    base, frag = _anc.split_fragment(u)
    q = _anc.gmail_query(base.strip())
    if q is None or q[0] is None:
        return ""
    return _anc.gmail_canonical(base.strip(), boxes) + (("#" + frag) if frag else "")


def _gmail_scope_args(urls: list[str] | None, boxes: dict[str, str], refuse: bool, stored: list[str] | None = None) -> list[str]:
    """The URLs of an anchors call with every scoped Gmail query (`gmail:q@<mailbox>[,<mailbox>]:<query>`) written with its mailbox names as the anchors service spells them, so one anchor is one entry however it was typed.
    With `refuse` (an add), a scope that names no mailbox or one the anchors service does not read is refused with the valid names, and so is a scope with a space in it (the names are separated by commas alone);
    the name check is skipped while the service has named no mailbox (it reports a scope it cannot read once it runs). `stored` is the project's stored URLs: an anchor stored in another spelling of the same scope (typed
    before the service had named its mailboxes) is the one added to, so a second spelling never makes a second entry (add, `refuse`), and a removal also takes every stored spelling of the scope it names (remove)."""
    out: list[str] = []
    same = lambda u: [e for e in stored or [] if _gmail_key(u, boxes) and _gmail_key(e, boxes) == _gmail_key(u, boxes)]
    for u in urls or []:
        base, frag = _anc.split_fragment(u)
        q = _anc.gmail_query(base.strip())
        if q is None and base.strip().startswith("gmail:q@"):
            if refuse:
                raise ToolError(f"Refused: {u!r} is not a Gmail query scope: the mailbox names sit between gmail:q@ and the next colon, separated by commas with no spaces (gmail:q@a,b:<query>)")
            out.append(u)
            continue
        why = _anc.gmail_query_problem(u) if refuse and q is not None else ""
        if why:
            raise ToolError(f"Refused: the Gmail query in {u!r} is not one the matcher can evaluate: {why}. {_GMAIL_TERMS}")
        if q is None or q[0] is None:
            out.append(u)
            continue
        if refuse and not q[0]:
            raise ToolError(f"Refused: {u!r} names no mailbox after gmail:q@; the form is gmail:q@<mailbox>:<query> (several: gmail:q@a,b:<query>), or gmail:q:<query> for every mailbox"
                            + (f" (the mailboxes are {', '.join(boxes)})" if boxes else ""))
        _good, bad = _anc.gmail_resolve(q[0], boxes) if boxes else ([], [])
        if refuse and bad:
            raise ToolError(f"Refused: {', '.join(repr(b) for b in bad)} is no mailbox the anchors service reads; the mailboxes are {', '.join(boxes)}. The form is gmail:q@<mailbox>:<query>, or gmail:q:<query> for every mailbox")
        canon = _anc.gmail_canonical(base.strip(), boxes) + (("#" + frag) if frag else "") if boxes else u
        if refuse:
            out.append(next(iter(same(canon)), canon))
        else:
            out.extend(dict.fromkeys([u, canon, *same(canon)]))
    return out


def _machine_args(add: list[str] | None, remove: list[str] | None) -> tuple[list[str], list[str]]:
    """The machines of an anchors call's add and remove (`machine:<name>`, the prefix in any case): (the fleet names to add, the names to remove). A name is a machine the fleet knows, by fleet name or hostname in any
    case, stored under its fleet name; one it does not know is refused with the known ones. A removal of a name the fleet no longer knows is taken as written, so an anchor on a machine the table dropped can still go."""
    boxes = _evw_boxes()
    known = sorted({f for f, _r in boxes.values()}, key=str.lower)
    adds, rms = [], []
    for u in add or []:
        if _ma.is_machine(u):
            name = _ma.name_of(u)
            hit = boxes.get(name.lower())
            if not name or hit is None:
                raise ToolError(f"Refused: {u.strip()!r} names no machine of the fleet" + (f"; the machines are {', '.join(known)}" if known else "; the server knows no machine yet") + ". The form is machine:<name>, by fleet name or hostname")
            if hit[0] not in adds:
                adds.append(hit[0])
    for u in remove or []:
        if _ma.is_machine(u):
            name = _ma.name_of(u)
            rms.append((boxes.get(name.lower()) or (name,))[0])
    return adds, rms


def _machine_listing(entries: list[dict[str, Any]]) -> str:
    """The machine anchors of a page for the anchors tool's list: each with whether the machine is online now."""
    if not entries:
        return ""
    boxes = _evw_boxes()
    online = {e["machine"].lower(): _machine_state(e["machine"], boxes)[2] for e in entries if _machine_state(e["machine"], boxes)[0]}
    return "\nmachine anchors (the item's mover is told each time the machine checks in again):\n" + _ma.fmt(entries, online)


def _anchors(project: str, add: list[str] | None = None, items: list[str] | None = None, remove: list[str] | None = None, who: str = "") -> str:
    value = project.strip().strip("/")
    hits = _gates.registry_hits("projects", value)
    store = _anc.load()
    if not hits:
        # A key whose page is gone (renamed by hand: the old slug is a redirect stub, which the registry skips) can still hold
        # anchors. They stay listable and removable, or a rename done without rename_page.py strands them for good.
        stale = [k for k in dict.fromkeys(pat.format(value=value) for pat in _cfg.CFG["registries"]["projects"].get("match", ["{value}"])) if k in store]
        if len(stale) != 1 or add:
            raise ToolError(f"Refused: project {project!r} names no page (projects/<slug> or infra/<slug>)"
                            + (f"; {stale[0]} still holds anchors, which can be listed and removed, not added to" if len(stale) == 1 else ""))
        key = stale[0]
        if remove:
            _anc.remove(store, key, _gmail_scope_args(remove, _gmail_boxes(), False, [e.get("url", "") for e in store.get(key, [])]))
            _anc.save(store)
            _publish()
        return (f"{key} names no page any more (renamed or removed): its anchors notify nobody and can only be listed and removed.\n"
                + _anc.fmt(store.get(key, [])))
    if len(hits) > 1:
        raise ToolError(f"Refused: project {project!r} is ambiguous — it names {' and '.join(hits)}; write the full key")
    key = hits[0]
    scope: list[str] | None = None
    if items:
        known = {t["gid"]: t for t in _anc.items()}
        scope = []
        for i in items:
            g = _norm_id(i)
            t = known.get(g)
            if not t:
                raise ToolError(f"Refused: no item {g}")
            if _anc.project_of(t) != key:
                raise ToolError(f"Refused: {g} belongs to {_anc.project_of(t)}, not {key}")
            if t.get("status") == "completed":
                raise ToolError(f"Refused: {g} is completed — scope an anchor to open items, or leave it project-wide")
            scope.append(g)
    mach_add, mach_rm = _machine_args(add, remove)       # `machine:<name>` entries are a machine of the fleet (machine_anchor.py), not a URL
    add, remove = [u for u in add or [] if not _ma.is_machine(u)], [u for u in remove or [] if not _ma.is_machine(u)]
    for u in add or []:
        base, _ = _anc.split_fragment(u)
        if not _anc.anchor_id(base):
            raise ToolError(f"Refused: {u!r} is not an anchor shape ({_ANCHOR_SHAPES})")
    boxes = _gmail_boxes()
    held = [e.get("url", "") for e in store.get(key, [])]
    add, remove = _gmail_scope_args(add, boxes, True, held), _gmail_scope_args(remove, boxes, False, held)
    if add:
        _anc.add(store, key, add, scope, by=who)
    if remove:
        _anc.remove(store, key, remove)
    if add or remove:
        _anc.save(store)
        _publish()
    with _ma.LOCK:
        mstore = _ma.load()
        if mach_add or mach_rm:
            for fleet in mach_add:
                _ma.seed(fleet, _machine_state(fleet)[1])        # a check-in that is past tells nothing: the notice is for the next one
            if mach_add:
                _ma.add(mstore, key, mach_add, scope, who)
            if mach_rm:
                _ma.remove(mstore, key, mach_rm)
            _ma.save(mstore)
    keeper = _anc.name_line(key)
    stew = _anc.notice_name(key) or keeper           # a sub-page's notices go to the root's name, not its keeper
    kept = f"; kept by {keeper}" if keeper and keeper != stew else ""
    try:
        hub = json.load(open(_cfg.state("anchor-hub", "status.json"), encoding="utf-8")).get("anchors") or {}
    except Exception:
        hub = {}
    kp = _telling.page_keeper(key)                               # its keeper, not the retired name-line session
    who_gets = f"router: rules this project; keeper: {kp or 'none: no page, hub or scope general agent lists a -main agent'}{kept}"
    out = f"{key} anchors ({who_gets}):\n" + (_anc.fmt(store.get(key, []), hub, boxes) if store.get(key) or not mstore.get(key) else "") + _machine_listing(mstore.get(key, []))
    for u in add or []:
        q = _anc.gmail_query(_anc.split_fragment(u)[0].strip())
        if q is not None:
            names = ", ".join(_anc.gmail_mailboxes(_anc.split_fragment(u)[0].strip(), boxes)[0]) or "none the anchors service has named yet"
            out += f"\nGmail query {q[1]!r} reads the mailboxes: {names}" + ("" if q[0] is not None else " (every mailbox the anchors service reads; gmail:q@<mailbox>:<query> reads only the one named)") + "."
            out += f"\nIt matches a mail when: {_anc.gmail_query_reading(u)}."
    if add:
        out += ("\nThe anchors service reads each new anchor within two minutes: one it cannot read (not shared with it, a mailbox it has no access to, a wrong link) "
                "is reported once to the project's keeper and marked UNREADABLE in this list. A line with no name after the scope, other than a Gmail query (named by its mailboxes at once), has not been read yet.")
    if mach_add:
        out += (f"\nmachine anchor{'s' if len(mach_add) > 1 else ''} added: {', '.join(mach_add)}. Nothing is told for a check-in that is past; the mover of each item in scope is told at the machine's next check-in "
                "(offline to online), once per check-in, naming the machine. The item is not turned and not saved: park it with a wait only when nothing else is open.")
    return out


def register(mcp, *, evw_boxes, machine_state) -> None:
    """Adds the tool of this module to `mcp`, and takes the server's callables the bodies use."""
    global _evw_boxes, _machine_state
    _evw_boxes = evw_boxes
    _machine_state = machine_state
    mcp.tool(name="anchors", description=_lead(_ANCHORS_DESC))(stackshot_anchors)
