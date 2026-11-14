"""agents.py: which session is a project's -main agent and which its builder, who an item's mover could hand work to, and the reader of many items' movers: the project's -main agent (`_main_agent`), its builder and the
builder a page maps to (`_builder_agent`, `_builder_by_page`, `_builder_for`), the names a hand-off could name (`_session_roster`, `_handoffs_in`) and the cache one reader keeps of the items it has read (`_WaitCtx`).

A service module: it reads the project registry, the config and the store, and writes nothing. Whether a session is up is pane_recovery.py's; an item's contact (the front agent the owner talks to about it) is contacts.py's."""
from __future__ import annotations

import re
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.model import holders as _holders
from stackshot.model.ids import _plain_text
from stackshot.router import router_live as _router_live
from stackshot.service import store as _svcstore
from stackshot.waits import waiting as _wt


class _WaitCtx:
    """What one reader needs to work out the mover of many items: a cache of the items read (an `after` blocker is read once)."""
    def __init__(self, now: float) -> None:
        self.now = now
        self._items: dict[str, dict[str, Any] | None] = {}

    def load(self, gid: str) -> dict[str, Any] | None:
        if gid not in self._items:
            try:
                self._items[gid] = _svcstore._load(gid)
            except Exception:  # noqa: BLE001
                self._items[gid] = None
        return self._items[gid]

    def mover(self, gid: str, item: dict[str, Any]) -> dict[str, str]:
        """The item's mover (waiting.mover_for)."""
        return _wt.mover_for({**item, "gid": gid}, self.load)


def _session_roster() -> set[str]:
    """Every session name a hand-off could name: the sessions a page names (anchors.session_roles: keepers, user-facing and
    background agents) and the names the fleet knows (anchors.names)."""
    names: set[str] = set()
    try:
        names |= set(_anc.session_roles())
    except Exception:
        pass
    try:
        names |= {str(n) for n in _anc.names().values() if n}
    except Exception:
        pass
    return names


_HANDOFF_LINE = re.compile(r"^[ \t]*(?:[-*+•]|\d+[.)])?[ \t]*([A-Za-z0-9][\w.-]*)[ \t]*:", re.M)   # "<session>: <action>", a list marker before it at most


def _handoffs_in(text: str, roster: set[str]) -> list[str]:
    """The sessions `text` hands work to: a roster name at the start of a line of `text` (after a list marker, "- " or "1. ",
    and whitespace at most) followed by a colon, the `<session>: <action>` form a next line takes. A name anywhere else (inside a
    page slug, a `#s=<name>` link, a sentence that mentions the session, code or quotes) is not a hand-off. → the names, sorted."""
    plain = _plain_text(text)
    if not plain.strip():
        return []
    return sorted({m.group(1) for m in _HANDOFF_LINE.finditer(plain)} & roster)


def _main_agent(project: str) -> str:
    """The project's -main agent: the page's front `agents:` entry whose name ends in -main, else its first front agent; for a page with none, its
    hub's, else the general -main agent of its scope (anchors.fallback_main); "" when none. Front-only: a background agent is never the
    escalation target (the -main agent is the one the owner talks to)."""
    try:
        return _anc.fallback_main(project)
    except Exception:
        return ""


def _builder_agent(project: str) -> str:
    """The project's builder while the router is live for it (router_live.builder: a background agent whose mandate builds, maintains,
    merges or engineers), else "" — page work and build work go to it, never to a retired name-line session."""
    return _router_live.builder(project)


def _builder_by_page() -> dict[str, str]:
    """[handoff.builder_by_page]: project page key -> the background agent that builds that area. A table of another type reads as empty (every item keeps the project's first
    builder, today's behaviour); an entry that is not text is skipped. Keys lose their surrounding slashes. Read where it is used, so a reload applies."""
    sec = _cfg.get("handoff")
    tab = sec.get("builder_by_page") if isinstance(sec, dict) else None
    if not isinstance(tab, dict):
        return {}
    return {k.strip().strip("/"): v.strip() for k, v in tab.items() if isinstance(k, str) and isinstance(v, str) and k.strip().strip("/") and v.strip()}


def _builder_for(project: str) -> str:
    """The builder a new item of `project` (the page it is filed on) goes to by default: the agent [handoff.builder_by_page] maps the page to, by prefix (the key itself or a page under it,
    the longest key first), when that agent is a background agent of the item's project; else the project's first builder (_builder_agent). Never an error: an unmapped page, an empty map and a
    mapped agent the project does not list all give the first builder. An explicit mover on a create never comes through here."""
    key = str(project or "").strip().strip("/")
    tab = _builder_by_page() if key else {}
    for page in sorted((p for p in tab if key == p or key.startswith(p + "/")), key=len, reverse=True):
        if _holders._is_background(tab[page], project):
            return tab[page]
    return _builder_agent(project)
