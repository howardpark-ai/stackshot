"""anchor_offers.py: the one-line offer of a ready `anchors` call that a board reply carries at the moments where an anchor would catch news the item waits on.

Three moments, each answered by a reply line and never by a refusal (an offer never blocks a write):

  * a relay wait on someone outside (the item waits on news the owner relays) that has no anchor scoped to the item: the create or update that set the wait says so and carries the call;
  * a source link in an item's description (a Slack thread, a Gmail thread, a Drive file or a Notion page) that no anchor watches for the item: the create, or the update that put the link there;
  * a new project's page (`post project`): its repository's releases and its Slack channel.

The call is ready: the project key and the item id are filled in. What the server cannot know (the person's thread, the repository's owner) is filled from the item's own text when it holds a link or an
address that fits, and is a placeholder in angle brackets otherwise. At most one offer line makes one reply. None is made when the anchor already exists (the same anchor held project-wide on the item's
page, or scoped to the item on any page), when the item is closed, or when `[anchors] offers = false`. A failure to work an offer out is a stderr line and no line, never a failed write.

Imports point down only: the anchors, the item reads, the config and the model."""
from __future__ import annotations

import re
import sys
from typing import Any

from stackshot.anchors import anchor_scope as _ascope
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.waits import watchers as _watch

KINDS = ("slack", "gmail", "drive", "notion")      # the anchor kinds a source link offers: the links a person follows to a thread or a file, not a pull request (a hook anchors those)
MAX_LINKS = 3                                      # the most links one offer carries
_URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
_EMAIL = re.compile(r"(?<![\w.%+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_WORDS = {"slack": "Slack", "gmail": "Gmail", "drive": "Drive", "notion": "Notion"}


def enabled() -> bool:
    """`[anchors] offers` (true by default): false turns every offer off. Read at each call, so a reload applies. A value that is not true or false reads as true (`config.notes` says so)."""
    v = _cfg.get("anchors", "offers", default=True)
    return v if isinstance(v, bool) else True


def _id(url: str) -> str:
    return _anc.anchor_id(_anc.split_fragment(url.strip())[0]) or ""


def links(*texts: Any) -> list[tuple[str, str]]:
    """The source links of the texts, in order, as (anchor id, url): a Slack, Gmail, Drive or Notion link, once per anchor id, trailing punctuation cut. A link that is no anchor shape, and a pull request or issue, is left out."""
    out: dict[str, str] = {}
    for t in texts:
        for m in _URL.finditer(str(t or "")):
            u = m.group(0).rstrip(".,;:!?'\"")
            aid = _id(u)
            if aid.split(":", 1)[0] in KINDS and aid not in out:
                out[aid] = u
    return list(out.items())


def _held(store: Any, gid: str, project: str) -> set[str]:
    """The anchor ids that already watch for item `gid`: those scoped to it on any page and the project-wide ones of its own page."""
    return {i for i in (_id(e["url"]) for e in _ascope.anchor_scope(store, gid, project, wide=True)) if i}


def _call(project: str, add: list[str], gid: str = "") -> str:
    """The anchors call as a session writes it: the project, what to add and, for an item, its id."""
    adds = ", ".join('"' + a + '"' for a in add)
    return f'anchors(project="{project}", add=[{adds}]' + (f', items=["{_gh.shown(gid)}"]' if gid else "") + ")"


def _relay_line(project: str, gid: str, meta: dict[str, Any], texts: list[str], held: set[str]) -> str:
    """The offer for a relay wait with no anchor scoped to the item: the link of the thread when the item's text holds one that nothing watches, else a Gmail query on an address in it, else the call with the one thing
    the server cannot know, the thread, as a placeholder. "" when every link the item's text holds is watched already."""
    party = _model.clean(meta.get("wait_event"))[:60] or "the party"
    cand = links(*texts)
    found = [u for aid, u in cand if aid not in held][:MAX_LINKS]
    if cand and not found:
        return ""                  # the thread the item's text links is watched already
    if not found:
        for m in _EMAIL.finditer(" ".join(texts)):
            q = f"gmail:q:from:{m.group(0)}"
            if q not in held and not _anc.gmail_query_problem(q):
                found = [q]
                break
    add = found or ["<their Slack thread or Drive file link, or gmail:q:from:<their address>>"]
    return (f"\n(anchor offer: {_gh.shown(gid)} waits on {party} and no anchor watches their thread for it, so a reply there reaches no one before the wait ends. "
            f"To watch it: {_call(project, add, gid)})")


def _links_line(project: str, gid: str, new: list[tuple[str, str]]) -> str:
    """The offer for source links in an item's description that no anchor watches for it: one call that adds them all, scoped to the item."""
    kinds = ", ".join(dict.fromkeys(_WORDS[a.split(":", 1)[0]] for a, _u in new))
    return (f"\n(anchor offer: the {kinds} link{'s' if len(new) > 1 else ''} in {_gh.shown(gid)}'s description {'have' if len(new) > 1 else 'has'} no anchor for it, so news there reaches no session. "
            f"To watch {'them' if len(new) > 1 else 'it'}: {_call(project, [u for _a, u in new], gid)})")


def item_line(gid: str, item: dict[str, Any], was: dict[str, Any] | None = None) -> str:
    """The offer line of a create (`was` None: the item is new) or of an update (`was` the item as it stood before the write), "" when there is none. A relay wait is offered when this write set it (new, or a
    different party than before); source links are offered when they are new in this write's description; each only for an open item and only when no anchor already watches for it."""
    if not enabled() or item.get("status") != "open" or not gid:
        return ""
    try:
        meta = item.get("metadata") or {}
        project = str(meta.get("project") or "")
        if not project:
            return ""
        was_meta = (was or {}).get("metadata") or {}
        store = _anc.load()
        held = _held(store, gid, project)
        desc = str(item.get("description") or "")
        if _watch.stored_kind(meta) == "relay" and not (was is not None and _watch.stored_kind(was_meta) == "relay" and _model.clean(was_meta.get("wait_event")) == _model.clean(meta.get("wait_event"))):
            if not _ascope.anchor_scope(store, gid, project):
                return _relay_line(project, gid, meta, [str(meta.get("wait_event") or ""), desc, str(meta.get("next") or "")], held)
        before = {a for a, _u in links((was or {}).get("description"))}
        new = [(a, u) for a, u in links(desc) if a not in held and a not in before][:MAX_LINKS]
        return _links_line(project, gid, new) if new else ""
    except Exception as e:  # noqa: BLE001  — the write is saved: an offer that fails is a stderr line
        print(f"anchor offer: {gid} not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""


def project_line(key: str) -> str:
    """The sentence a new project's page adds to the answer of `post project`: its repository's releases and its Slack channel, as one ready call with the project's own key."""
    if not enabled() or not key:
        return ""
    return (f" Anchor offer: nothing watches {key}'s outside threads yet. To watch its repository's releases and its Slack channel: "
            + _call(key, ["https://github.com/<owner>/<repo>/releases", "<the project's Slack channel link>"]))
