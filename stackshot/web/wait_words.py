"""wait_words.py: a question the server itself put on a waiting item (waits/watchers.py: a relay's ask-by day and "stop waiting?"), drawn in the reader's language.

The item stores it in English: a session reads it, and a button's label is the identity of a pick. Only what a page draws is translated, from the string table (the wait_ask.* keys, whose English is the
stored wording). The event the question is about is the item's own text and is drawn as written, on a line of its own after the question. Anything that is not such a question comes back as it was, so a
caller needs no test of its own. Pure but for the language of the request (web/i18n.current)."""
from __future__ import annotations

from typing import Any

from stackshot.model import model as _model
from stackshot.model import owner_steps as _owner_steps
from stackshot.model import steps as _steps
from stackshot.waits import watchers as _watch
from stackshot.web.i18n import t as _t

_QUESTION = {"relay": "wait_ask.q.relay", "drop": "wait_ask.q.drop"}
_LINES = (_watch.LINE_ARRIVED, _watch.LINE_WEEK, _watch.LINE_DROP)      # the stored line of each button
_LABEL = {"arrived": "wait_ask.opt.arrived", "week": "wait_ask.opt.week", "drop": "wait_ask.opt.drop"}


def question(ask: Any) -> tuple[str, str] | None:
    """(the question, the line that says what is waited for, "" when the item names nothing) of a server's wait question, from its ask line or its Decide part; None for any other text."""
    q = _watch.read_question(ask)
    if not q:
        return None
    return _t(_QUESTION[q["kind"]], n=q["n"]), _t("wait_ask.event", event=q["event"]) if q["event"] else ""


def one_line(ask: Any) -> str:
    """The question and what is waited for as one line of text (a History line, the owner's step); any other text as it was."""
    got = question(ask)
    return " ".join(x for x in got if x) if got else str(ask or "")


def label(ask: Any, text: str) -> str:
    """A button's label of the server's wait question `ask` (or the pick an answer stored) in the reader's language; any other label, and any label of any other question, as it was."""
    kind = _watch.option_kind(text) if _watch.read_question(ask) else ""
    return _t(_LABEL[kind]) if kind else text


def line(ask: Any, text: str) -> str:
    """A button's one-line explanation: none for the server's wait question, whose label says what a pick does (and a line left in English would be the one English word on a page in another language); any other as it was."""
    return "" if _watch.read_question(ask) and text in _LINES else text


def options(ask: Any, opts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The options of `ask` as a page shows them: each with "shown" and "shown_line", the label and line to draw; "label" stays the stored one, which a form posts."""
    return [{**o, "shown": label(ask, o["label"]), "shown_line": line(ask, o["line"])} for o in opts]


def worded(ask: Any, opts: Any) -> Any:
    """The stored options of `ask` with each label and line as the reader reads them, for a text that only says what they were (a History fold); anything that is no list of options as it was."""
    if not isinstance(opts, list):
        return opts
    return [{**o, "label": label(ask, str(o.get("label") or "")), "line": line(ask, str(o.get("line") or ""))} if isinstance(o, dict) else o for o in opts]


def steps(text: Any) -> str:
    """Every line of a text of checklist steps (an item's next), each as `step` reads it."""
    return "\n".join(step(x) for x in str(text or "").split("\n"))


def step(text: str) -> str:
    """The line of a checklist step: the step the server made for its wait question (`<owner>: <question> ...`, `→ <the pick>` once answered) in the reader's language, any other line as it was."""
    first, sep, rest = str(text).partition("\n")
    who = _steps.opener(first)
    if not who or not _model.is_owner(who):
        return text
    body = _steps.without_owner(first)
    body, arrow, pick = body.rpartition(_owner_steps.ARROW) if _owner_steps.ARROW in body else (body, "", "")
    if not _watch.read_question(body):
        return text
    return f"{first.split(':', 1)[0]}: {one_line(body)}" + (arrow + label(body, pick) if arrow else "") + sep + rest
