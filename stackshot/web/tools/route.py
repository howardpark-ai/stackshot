"""route.py: the `route` tool: a ruling on a notice delivered for a project."""
from __future__ import annotations

import time

from fastmcp.exceptions import ToolError

from stackshot.core.instance import OWNER
from stackshot.fleet.sessions_registry import _session_label
from stackshot.router import routing as _routing
from stackshot.service.store import _load
from stackshot.web.auth import oauth as _oauth
from stackshot.web.page_debts import _session_id
from stackshot.web.publish import _publish
from stackshot.web.tools.text import _lead

_anchor_release = None      # set by register: the server's own, looked up at each call
_watch_label = None      # set by register: the server's own, looked up at each call


def _route_released(rel: list[str]) -> str:
    """The `route` reply's line about the items a ruling released: a held item is released from hold; an item whose stored wait the notice ended turned to its post-wake mover."""
    held, turned = [], []
    for g in rel:
        try:
            w = (_load(g).get("metadata") or {}).get("woke")
        except Exception:  # noqa: BLE001
            w = None
        if isinstance(w, dict) and time.time() - float(w.get("at") or 0) < 120:
            turned.append(f"{g} turned to {_watch_label(str(w.get('to') or ''))}")
        else:
            held.append(g)
    out = f"\n({', '.join(held)} waited on this anchor and {'is' if len(held) == 1 else 'are'} released from hold)" if held else ""
    return out + (f"\n({'; '.join(turned)}: its wait on this anchor ended)" if turned else "")


def _route(notice: str, ruling: str, to: str = "", reason: str = "", sender: str = "") -> str:
    ruling = ruling.strip().lower()
    if ruling == "passed" and not to.strip():
        raise ToolError("Refused: a notice that was passed names the agent it went to — to=<agent's session name>")
    try:
        project, n = _routing.rule(notice, ruling, to, reason, by=_session_label(_session_id(sender)) if sender.strip() else "")
    except KeyError:
        raise ToolError(f"Refused: no notice {notice!r} in the routing log — the id is the last word of the notice you received (\"notice a1b2c3\")")
    except ValueError as e:
        raise ToolError(f"Refused: {e}")
    rel = _anchor_release(project, n, by=sender) if ruling in ("passed", "merged") else []   # a held item that waited on this anchor comes back
    _publish()
    return (f"ruled {n['id']} ({project}): {ruling}" + (f" to {to.strip()}" if to.strip() else "") + (f" — {n.get('reason')}" if n.get("reason") else "") + f".\n{n.get('label', '')}: {n.get('text', '')}"
            + _route_released(rel))


def stackshot_route(notice: str, ruling: str, to: str = "", reason: str = "", sender: str = "") -> str:
    _oauth._who()
    return _route(notice, ruling, to, reason, sender)


def register(mcp, *, anchor_release, watch_label) -> None:
    """Adds the tool of this module to `mcp`, and takes the server's callables the bodies use."""
    global _anchor_release, _watch_label
    _anchor_release = anchor_release
    _watch_label = watch_label
    mcp.tool(name="route", description=_lead(f"A ruling on a notice delivered for a project. The router rules every notice of every project by itself (rules in code, then one thin call), so call this to overrule a ruling that was wrong. `notice` = the id at the end of the notice (\"notice a1b2c3\"); `ruling` = passed (handed to an agent: name it in `to`) | merged (folded into a digest) | held (kept for later) | dropped (not worth anyone's attention); `reason` = one line {OWNER} can skim; `sender` = your own session. Right call: route(notice=\"a1b2c3\", ruling=\"passed\", to=\"my-x\", reason=\"belongs to the export work\", sender=\"my-x\"). Call it once per notice, after acting on it; call it again to overrule an earlier ruling. The project's routing page (behind its number in the board's anchors column) lists every notice with its ruling and reason, and the board flags notices left without a ruling for over an hour."))(stackshot_route)
