"""save_hooks.py: what the save steps and the owner's words still reach in the surface.

The save steps (service/mover_steps.py: the mover settle, the owner's step on the checklist, the stored state, the notes a read carries), the recorders of the owner's words (service/owner_words.py), the naming of the working
background agent (service/agent_names.py) and the message relay (service/messaging.py) run from service/. A few things they use are still the surface's or the audit's: the debounced publish of the board, the session id of
a name, the audit's broad wait words, the board's words for a time and its time zone, and the message length cap. They are reached through `Hooks`, which
server.py fills once with `install` (these modules cannot import server.py: the surface sits above them). A hook is looked up on its owner when it runs, so a suite that replaces one there reaches the steps; a suite that replaces a
function of the steps sets it on the module that owns it. A hook leaves this table when the area that holds it moves under service/.

Imports point down only: this module imports nothing of the package."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Hooks:
    """What the save steps and the owner's words still reach outside service/, by the names they have there without the leading underscore. server.py builds one and gives it to `install`. A hook that reads a value is a function with no argument."""
    msg_max: Callable[[], Any]  # web.tools.text.MSG_MAX
    publish: Callable[..., Any]  # web.publish._publish
    session_id: Callable[..., Any]  # server._session_id
    wait_words: Callable[..., Any]  # audit.audit_checks.wait_words
    when_words: Callable[..., Any]  # web.render.when_words
    zone: Callable[[], Any]  # web.tools.text.ZONE


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Server.py gives the save steps and the owner's words what they still reach outside service/ (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the save steps and the owner's words have no hooks installed (server.py installs them at its import)")
    return _hooks_
