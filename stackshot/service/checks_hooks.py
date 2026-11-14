"""checks_hooks.py: what the done check, the release settle and the step proofs still reach in web/server.py.

The done check and its pass live in service/checks.py, the readers of what is live in service/released_live.py, the release settle in service/released.py and the step proofs, with the hand-over they trigger, in
service/proofs.py. A few things they use are still the surface's, because other code on the surface shares them: this checkout's repository and the pull-request key (the readers of an anchor and a write's gates also
use them), the hold readers of the item model, the page publish, the session ids and rosters, the renderer's answer for whose move an item waits on, and the mark of a wait the
server set back. They are reached through `Hooks`, which server.py fills once with `install` (these modules cannot import server.py: the surface sits above them). A hook is looked up on server.py when it runs, so a
suite that replaces one there reaches the passes; a suite that replaces a function of the passes sets it on the module that owns it. A hook leaves this table when the area that holds it moves under service/.

Imports point down only: this module imports nothing of the package."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Hooks:
    """What the done check, the release settle and the step proofs still reach outside service/, by the names they have there without the leading underscore. server.py builds one and gives it to `install`. A hook that reads a value is a function with no argument."""
    date_parked: Callable[..., Any]  # item_read._date_parked
    hold_flag: Callable[..., Any]  # holders._hold_flag
    is_held: Callable[..., Any]  # holders._is_held
    own_repo: Callable[..., Any]  # server._own_repo
    pr_key: Callable[..., Any]  # server._pr_key
    pr_url: Callable[[], Any]  # server._PR_URL
    publish: Callable[..., Any]  # web.publish._publish
    rmod_needs_kind: Callable[..., Any]  # server._rmod.needs_kind
    role_name: Callable[..., Any]  # sessions_registry._role_name
    same_sess: Callable[..., Any]  # sessions_registry._same_sess
    session_down: Callable[..., Any]  # pane_recovery._session_down
    session_id: Callable[..., Any]  # server._session_id
    session_roster: Callable[..., Any]  # agents._session_roster
    wait_end_sent_back: Callable[..., Any]  # server._wait_end_sent_back


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Server.py gives the done check, the release settle and the step proofs what they still reach outside service/ (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the done check, the release settle and the step proofs have no hooks installed (server.py installs them at its import)")
    return _hooks_
