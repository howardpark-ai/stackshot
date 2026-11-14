"""foryou_hooks.py: what the For you rows still reach in web/.

The rows a change of an item makes and the due-date look live in service/foryou_events.py. Three things they use are still the surface's, because other code on the surface shares them: the debounced
publish of the board, the page's parser of an ask line and the words for a date. They are reached through `Hooks`, which server.py fills once with `install` (these modules cannot import server.py: the
surface sits above them). A hook is looked up on server.py when it runs, so a suite that replaces one there reaches the rows. A hook leaves this table when the area that holds it moves under service/.

Imports point down only: this module imports nothing of the package."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Hooks:
    """What the For you rows still reach outside service/, by the names they have there without the leading underscore. server.py builds one and gives it to `install`."""
    parse_ask: Callable[..., Any]  # web/render.parse_ask
    publish: Callable[..., Any]  # web.publish._publish
    when_words: Callable[..., Any]  # web/render.when_words


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Server.py gives the For you rows what they still reach outside service/ (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the For you rows have no hooks installed (server.py installs them at its import)")
    return _hooks_
