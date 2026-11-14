"""save_hooks.py: what the save steps, the asks, the wait gates and the hand-over helpers still reach in the surface.

The save steps (service/mover_steps.py: the mover settle, the owner's step on the checklist, the stored state, the notes a read carries), the recorders of the owner's words (service/owner_words.py), the naming of the working
background agent (service/agent_names.py), the message relay (service/messaging.py), the ask line (service/asks.py), the write guards of the waits and of a decision's options (service/wait_gates.py), the wait and hold fixes (service/wait_fixes.py), the hand-over
after an answer (service/answer_handover.py), the answer itself (service/answer.py) and the audit ticks (service/audit_ticks.py) run from service/. A few things they use are still the surface's or the audit's: the debounced publish of the board, the session id of a name, the audit's broad wait words and
its modules, the reader of every item that tools/ holds, the board's words for a time and its time zone, the message length cap, the page's parser of an ask line and its option limits, the words the tools state, the answer form's note words and its module (lock, limits, pending file), and the
shown form of an id turned back to the stored one. They are reached through `Hooks`, which
server.py fills once with `install` (these modules cannot import server.py: the surface sits above them). A hook is looked up on its owner when it runs, so a suite that replaces one there reaches the steps; a suite that replaces a
function of the steps sets it on the module that owns it. A hook leaves this table when the area that holds it moves under service/.

Imports point down only: this module imports nothing of the package."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Hooks:
    """What these service modules still reach outside service/, by the names they have there without the leading underscore. server.py builds one and gives it to `install`. A hook that reads a value is a function with no argument."""
    anchor_shapes: Callable[[], Any]  # web.tools.text._ANCHOR_SHAPES
    answer_deliver: Callable[..., Any]  # service.answer._answer_deliver
    answer_note: Callable[..., Any]  # web.answers._answer_note
    answers_mod: Callable[[], Any]  # web.answers (the answer form's lock, limits, pending file and words; service/answer.py reads them on the module each time)
    answers_of: Callable[..., Any]  # web.render.answers_of
    ask_form: Callable[[], Any]  # web.render.ASK_FORM
    ask_max: Callable[[], Any]  # web.render.ASK_MAX
    ask_none: Callable[[], Any]  # web.tools.text._ASK_NONE
    audit_mod: Callable[[str], Any]  # the audit module of that name (audit/ sits outside the layers: it is imported when the hook runs)
    gmail_terms: Callable[[], Any]  # web.tools.text._GMAIL_TERMS
    msg_max: Callable[[], Any]  # web.tools.text.MSG_MAX
    next_report_all: Callable[..., Any]  # tools.next_report.load_all (tools/ sits outside the layers: it is imported when the hook runs)
    option_label_max: Callable[[], Any]  # web.render.OPTION_LABEL_MAX
    option_line_max: Callable[[], Any]  # web.render.OPTION_LINE_MAX
    options_max: Callable[[], Any]  # web.render.OPTIONS_MAX
    options_min: Callable[[], Any]  # web.render.OPTIONS_MIN
    options_of: Callable[..., Any]  # web.render.options_of
    parse_ask: Callable[..., Any]  # web.render.parse_ask
    publish: Callable[..., Any]  # web.publish._publish
    session_id: Callable[..., Any]  # server._session_id
    unlink_ids: Callable[..., Any]  # web.middleware._unlink_ids
    wait_words: Callable[..., Any]  # audit.audit_checks.wait_words
    when_words: Callable[..., Any]  # web.render.when_words
    yesno_options: Callable[..., Any]  # web.render.yesno_options
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
