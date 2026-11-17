"""builderless.py: how a front-only project (no background agent on its page) routes an item that its front agents carry.

A project whose page lists only front agents (user-facing ones) has no background agent to receive build work: it is front-only (anchors.front_only, the one test; the server supplies it). Two routing decisions then fall to the front agents, and this module
holds their pure parts (the server supplies what needs the project registry):

  answer_target(meta, usable, keeper)   who takes the item once the owner's step is answered and the item names no `then`: the session the item's next open step names (the step's
                                        owner line), else the item's stored contact, else "" (the caller falls back to the project's -main agent, as before)
  handover_allowed(sender, target, front_only, item_project)  may a session name a front agent in `mover=` (a hand-over), `then=` or `post_wake_mover=`: the project the item is filed under is front-only and the target is a
                                        live front agent of it (listed on that page or a page above it); the sender is any live session some project page lists, front or background,
                                        of any project

A project with no agents map (a one-session page) counts as having no builder too, but it lists no front agent, so neither rule finds a session to name there and the old fallback stands.

Pure functions of strings and metadata: no server import."""
from __future__ import annotations

from typing import Any, Callable

from stackshot.model import model as _model
from stackshot.model import steps as _steps


def front_of(row: dict[str, Any] | None, item_project: str) -> bool:
    """Is the session role row {"role", "project", "retired"} a live front agent of the project an item is filed under: listed on that page, or on a page above it (a sub-page counts)?"""
    if not row or row.get("role") != "front" or row.get("retired"):
        return False
    page = str(row.get("project") or "").strip().strip("/")
    proj = str(item_project or "").strip().strip("/")
    return bool(page) and (proj == page or proj.startswith(page + "/"))


def next_named_step(meta: dict[str, Any], keeper: str = "") -> str:
    """The name that opens the item's first open step which names a session other than the owner (a bare sub-step and a step that names no one are passed over); "" when there is none."""
    for s in _steps.view(meta, keeper=keeper or str((meta or {}).get("owner") or "")):
        if s["status"] != _steps.OPEN or _steps.is_bare(s["text"]):
            continue
        nm = _steps.opener(s["text"])
        if nm and not _model.is_owner(nm):
            return nm
    return ""


def answer_target(meta: dict[str, Any], usable: Callable[[str], bool], keeper: str = "") -> str:
    """Who takes an item of a front-only project (anchors.front_only) when the owner's step is answered and the item stores no `then`: the session its next open step names, when `usable(name)` says it is a
    live front agent of the item's project (the server reads the roles; the same target test as handover_allowed, so a step line does no more than `mover=`); else the item's stored contact when that is usable; else "". The caller keeps the project's -main agent as the last resort."""
    nm = next_named_step(meta, keeper)
    if nm and usable(nm):
        return nm
    contact = _model.clean((meta or {}).get("contact"))
    if contact and not _model.is_owner(contact) and contact.lower() not in ("none", "-") and usable(contact):
        return contact
    return ""


def handover_allowed(sender: dict[str, Any] | None, target: dict[str, Any] | None, front_only: bool, item_project: str) -> bool:
    """May `sender` name `target` in `mover=` (a hand-over), `then=` or `post_wake_mover=` of an item filed under `item_project` although the target is a front agent (a front agent gets no hand-off notice from another session, so the write is
    refused or the builder is substituted; here the target is told instead)? Only when the project is front-only (`front_only`, from anchors.front_only: it has no builder to substitute), the target is a
    live front agent of the project the item is filed under (front_of: a hand-over cannot point at an unrelated project's front agent) and the sender is any live session some project page lists: a front
    agent, a background agent or a one-session project's own session, of this project or of another. Each is a row of the session roles; None for a session no page lists, and a retired row is no session."""
    if not front_only or not front_of(target, item_project):
        return False
    return bool(sender) and not sender.get("retired")
