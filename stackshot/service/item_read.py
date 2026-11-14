"""item_read.py: reading items and the facts about one item that other code asks for: the items an `after` names that are still open (`_after_open`), the item as the model reads it (`_model_of`), the anchors scoped to it
(`_scoped_anchors`, `_scoped_anchor_exists`), what the board draws as parked (`_is_parked`) and the wait on one date alone (`_date_parked`), one item by id or none (`_load_or_none`, `_open_item_named`), the sessions of an
item's project (`_hub_sessions`) and the two switches of the item model (`_model_guards_on`, `_switchover_on`, `_old_wait_off`).

A service module: it reads the store (the items an `after` names, one item by id), the registry and the config, and writes nothing. The pure rules of a hold (the stored flag, what is on hold) are model/holders.py's.
Two rules are the board renderer's (web/render.py: what is parked, and the lane the needs give), and a service module cannot import the surface: `Hooks` carries them, and web/wiring.py fills it once with `install` (web/server.py calls it at its import). A hook
leaves this table when the renderer's rule moves under model/."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import json

from stackshot.anchors import anchor_scope as _ascope
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.model import model as _model
from stackshot.model.ids import _GID, _norm_id
from stackshot.model.needs import _after_of
from stackshot.service import store as _svcstore
from stackshot.service.store import _path
from stackshot.waits import until_write as _uw
from stackshot.waits import waiting as _wt


@dataclass(frozen=True)
class Hooks:
    """What the item readers still reach outside service/: the renderer's two rules, by the names they have in web/render.py (`is_held`, `needs_kind`). web/wiring.py builds one and gives it to `install`; a hook is looked up
    on web/render.py when it runs, so a suite that replaces one there reaches the readers."""
    is_held: Callable[..., Any]  # web.render.is_held: what the board draws as parked
    needs_kind: Callable[..., Any]  # web.render.needs_kind: the lane the needs give ("call", "relay" or "")


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Server.py gives the readers the renderer's two rules (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def _hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the item readers have no hooks installed (web/wiring.py installs them, called from web/server.py at its import)")
    return _hooks_


def _after_open(meta: dict[str, Any]) -> list[str]:
    """The items in an item's `after` that are still open (a missing file counts as closed: it blocks nothing)."""
    out = []
    for g in _after_of(meta):
        try:
            p = _path(g)
            if p.exists() and json.load(open(p, encoding="utf-8")).get("status") == "open":
                out.append(g)
        except Exception:
            continue
    return out


def _is_parked(item: dict[str, Any]) -> bool:
    """What the board draws as parked: the renderers' own rule (render.is_held), so a session reads what the board shows: an open item on hold (the flag), or waiting on one date alone (an `until`
    with no kind or the kind time), never one whose needs hold decision. `_is_held` (model/holders.py) is the hold flag alone, for the logic that releases and sets holds."""
    return _hooks().is_held(item)


def _date_parked(item: dict[str, Any], unfolded: bool = False) -> bool:
    """A wait stored as one date (`until`, no kind or the kind time) is what the old hold with a wake was: the write's notes and
    relays read it as put on hold / released from hold. `unfolded`: the write began by unfolding a stored until into the old
    working fields (so the until is not in the item yet): True for that read of the item as it was."""
    m = item.get("metadata") or {}
    return bool((unfolded or _wt.stored_until(m)) and _uw.kind_of(m) in ("", "time") and item.get("status") == "open" and _hooks().needs_kind(item) != "call")      # one rule with the board's (_is_parked): an item whose needs hold his decision is never parked


def _hub_sessions(project: str) -> tuple[str, str, list[str], list[str], str]:
    """→ (hub key, the name-line session (always "": it is retired), background agents, user-facing agents, the page's own `agent:` keeper) for an item's project: the
    background agents of the page, of its pilot root and of its hub, together."""
    reg = _anc.registry()
    hub = _anc.hub_of(project, reg)
    keys = [k for k in dict.fromkeys([str(project).strip("/"), _anc.pilot_root(project), hub]) if k]
    back, front = [], []
    for k in keys:
        e = reg.get(k) or {}
        b = [str(x) for x in (e.get("back_agents") or {})]
        back += [x for x in b if x not in back]
        front += [str(x) for x in (e.get("agents") or {}) if str(x) not in b and str(x) not in front]
    e = reg.get(str(project).strip("/")) or {}
    keeper = str(e.get("session") or "") if e.get("role") == "agent" else ""
    stew = ""      # the retired name-line session is not offered as a session to name
    return hub, stew, back, [x for x in front if x not in back], keeper


def _open_item_named(ref: str) -> str:
    """`board#N` as a session wrote it in a next line → the store id of that item when it exists and is open, else "" (a closed or unknown item is nothing to wait for). Read only."""
    try:
        g = _norm_id(ref)
        return g if _svcstore._load(g).get("status") == "open" else ""
    except Exception:  # noqa: BLE001
        return ""


def _model_guards_on() -> bool:
    """[model] guards (default true): the write guards of the item model. false turns them off without a deploy of code; the report on existing items still reads."""
    return bool(_cfg.get("model", "guards", default=True))


def _switchover_on() -> bool:
    """[model] switchover (default false): the item model is the board's only rule. On: the guards judge every write, existing items included (the report-only exemption of
    a write that touches only model fields goes), the hand-off rules and the watchers cover every item, and the old machinery stands down: the wake pass and the `after` release for an item
    and a watcher watches. Off: the model runs beside the old machinery, as before the migration. Needs [model] guards and one that has run the migration
    (tools/migrate_model.py): an item the migration left with residue has no watcher yet, and keeps the old machinery's wake until it is set by hand (`switchover_fallback`, default true)."""
    return bool(_cfg.get("model", "switchover", default=False)) and _model_guards_on()


def _old_wait_off() -> bool:
    """The old wake pass and `after` release stand down for the items no watcher watches: [model] switchover on and [model] switchover_fallback (default true) false. With the fallback
    (default) they keep serving only an item the migration left with residue (a wait with no input or end: no watcher owns it yet), until it is set by hand; a watched wait was never theirs."""
    return _switchover_on() and not bool(_cfg.get("model", "switchover_fallback", default=True))


def _load_or_none(gid: str) -> dict[str, Any] | None:
    try:
        return _svcstore._load(gid)
    except Exception:  # noqa: BLE001
        return None


def _scoped_anchors(project: str, gid: str, anchors: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The anchors scoped to this item, from every project's page and not only the item's own (anchor_scope.anchor_scope; the project-wide ones do not count): each once, with the
    page that holds it in `page`. `project`: the item's project, whose page is read first. `anchors`: the anchors already loaded (a pass that asks about many items loads them once)."""
    try:
        return _ascope.anchor_scope(_anc.load() if anchors is None else anchors, gid, project)
    except Exception:
        return []


def _scoped_anchor_exists(gid: str, meta: dict[str, Any]) -> bool:
    """True when an anchor is scoped to this item, held by any project's page (a project-wide one does not count); a failed lookup says true, so no note."""
    try:
        return bool(_scoped_anchors(str(meta.get("project") or ""), gid))
    except Exception:
        return True


def _model_of(item: dict[str, Any]) -> "_model.Model":
    """The item read by the model (model.py): the state, the effective mover and the effective wait, from the stored fields and today's state."""
    gid, m = str(item.get("gid") or item.get("id") or ""), item.get("metadata") or {}
    return _model.derive(item, after_open=lambda i_: _after_open(i_.get("metadata") or {}),
                         anchored=lambda i_: bool(_GID.match(gid) and _scoped_anchors(str(m.get("project") or ""), gid)))
