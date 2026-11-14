"""stall_hooks.py: what the stall pass and the one ladder still reach in web/server.py.

The stall state and its steps, the one ladder and the pass itself live in service/stall.py, service/ladder.py and service/stall_tick.py. A few things they use are still the surface's or the audit's, because
other code shares them: the open-item and wait reader, the project's -main agent, the queue map, the page publish, the session ids and names, the time zone and the words for a time, and the activity clock and the
step status the audit reads (audit/ and tools/ sit outside the layers, so no service module imports them). They are reached through `Hooks`, which server.py fills once with `install` (these modules cannot import
server.py: the surface sits above them). A hook is looked up on server.py when it runs, so a suite that replaces one there reaches the passes; a suite that replaces a function of the passes sets it on the module that
owns it. A hook leaves this table when the area that holds it moves under service/.

Imports point down only: this module imports nothing of the package."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Hooks:
    """What the stall pass and the one ladder still reach outside service/, by the names they have there without the leading underscore. server.py builds one and gives it to `install`. A hook that reads a value is a function with no argument."""
    after_open: Callable[..., Any]  # item_read._after_open
    main_agent: Callable[..., Any]  # agents._main_agent
    next_report_all: Callable[..., Any]  # tools/next_report.load_all
    publish: Callable[..., Any]  # web.publish._publish
    queue_map: Callable[..., Any]  # server._queue_map
    role_name: Callable[..., Any]  # sessions_registry._role_name
    session_id: Callable[..., Any]  # server._session_id
    silence_clock: Callable[..., Any]  # audit/silence.clock
    silence_minutes: Callable[..., Any]  # audit/silence.minutes
    silence_subagent_running: Callable[..., Any]  # audit/silence.subagent_running
    when_words: Callable[..., Any]  # web/render.when_words
    zone: Callable[[], Any]  # server.ZONE


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Server.py gives the stall pass and the one ladder what they still reach outside service/ (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the stall pass has no hooks installed (server.py installs them at its import)")
    return _hooks_
