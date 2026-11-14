"""text.py: the words the tools carry and the limits they state: the opener every tool's description starts with, the description pieces and parameter texts that create and update share, and the constants server.py and the tools both read."""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from stackshot.core import config as _cfg
from stackshot.core.instance import NAME, OWNER
from stackshot.model import draft as _draft, step_commands as _sc
from stackshot.waits import event_waits as _ew, waiting as _wt
from stackshot.web import render as _rmod
from stackshot.model.decision_gates import _OPT_FORM
from stackshot.model.field_gates import NEXT_PREFIX_ROOM, _close_reason_max, _subject_max
from stackshot.web.tools import textfile as _tf

_FOR_OWNER = f"[for {OWNER}]"   # the mark a message to a front agent carries on its first line ("[for <owner>]" on the owner's instance)
# Tool text that names the owner's names and the shell the owner runs steps in: built here once from [instance] owner_aliases and [steps] owner_shell / bash_host / shell_name.
_ALIASES = _cfg.owner_aliases()
_ALIAS_PAREN = (" (or " + ", ".join(f"`{a}:`" for a in _ALIASES) + ")") if _ALIASES else ""
_OPENERS_TXT = ", ".join(f"`{o}:`" for o in _cfg.owner_openers())


_HOST = _sc.bash_host() or "the Linux host"
_FIX = _sc.bash_fix()
if _sc.shell_rule():
    _P_RUN = f', a command for {_HOST} is written `{_FIX}` (bare bash is refused) and the line says where it runs ("In PowerShell: …"; "a terminal on {_HOST}" is no place)'
    _P_BANG = f"write it `In PowerShell: {_FIX}`"
    _P_CHK = " (where it runs, the ssh form)"
    _P_EX = '"In PowerShell:"'
    _P_EX2 = '"In PowerShell: ssh -t ' + _HOST + " '…'" + '"'
    _P_PLACE_STEP = f'with the place it runs ("In PowerShell: …", on a Windows machine, the default; a command for {_HOST} is `{_FIX}` inside it; never a `! ` line, the pane form, which is refused in a step and in a next line that starts `{OWNER}:`, whatever else the line says). '
    _P_OLD = f": a command names where it runs, bash for {_HOST} has the ssh form"
    _P_BARE = f", a command for {_HOST} written bare, or a command with no word that says where it runs"
elif _sc.sala_shell():
    # The owner types his commands in sala's Shell (a terminal in the sala web UI): bash on the host, `ssh <host> '<command>'` for another machine, Shift+Insert to paste.
    _PLACE = _sc.shell_place()
    _OTHER = _sc.other_host_form()
    _P_RUN = (f", as typed in {_PLACE}, bash on {_HOST}: a command for {_HOST} is written as it stands, one for another machine as `{_OTHER}` (`ssh -t` when it asks for input); "
              "a PowerShell or Windows-only command outside ssh is refused, and no line saying where it runs is asked for")
    _P_BANG = f"write it in backticks as typed in {_PLACE}"
    _P_CHK = f" (bash as typed in {_PLACE}, the ssh form for another machine)"
    _P_EX = '"In sala\'s Shell:"'
    _P_EX2 = '"In sala\'s Shell: ls -la"'
    _P_PLACE_STEP = (f"as typed in {_PLACE}, a terminal in the sala web UI that runs bash on {_HOST} (a command for {_HOST} is written as it stands, one for another machine as `{_OTHER}`; "
                     f"he pastes there with Shift+Insert, not Ctrl+V); never a `! ` line, the pane form, which is refused in a step and in a next line that starts `{OWNER}:`, whatever else the line says. ")
    _P_OLD = ""
    _P_BARE = ""
else:
    _P_RUN = ""
    _P_BANG = "put the command in backticks"
    _P_CHK = ""
    _P_EX = '"In a terminal:"'
    _P_EX2 = '"In a terminal: ls -la"'
    _P_PLACE_STEP = f"never a `! ` line, the pane form, which is refused in a step and in a next line that starts `{OWNER}:`, whatever else the line says. "
    _P_OLD = ""
    _P_BARE = ""


ZONE = _cfg.tz()

_DESC_MAX_LINES = int(_cfg.CFG["description"].get("max_lines", 8))        # the limits the tool texts state; the gates read the config live
_DESC_LINE_MAX = int(_cfg.CFG["description"].get("line_max", 120))
_SUBJECT_MAX = _subject_max()                  # the subject and close-reason limits the tool texts state; the gates read the config live
_CLOSE_REASON_MAX = _close_reason_max()
_NEXT_LINE_MAX = int(_cfg.CFG.get("metadata", {}).get("next", {}).get("line_max", 200))

# The words are in text/shared.md (the pieces and parameter texts more than one tool uses) and in one text/<tool>.md per tool; a {{NAME}} in them is filled
# from the values here or from the values the tool's own module passes to load_text. A name no text uses, or a {{NAME}} nothing defines, fails at import.
VALUES = {
    "OWNER": OWNER,
    "NAME": NAME,
    "FOR_OWNER": _FOR_OWNER,
    "SUBJECT_MAX": str(_SUBJECT_MAX),
    "DESC_MAX_LINES": str(_DESC_MAX_LINES),
    "DESC_LINE_MAX": str(_DESC_LINE_MAX),
    "NEXT_LINE_MAX": str(_NEXT_LINE_MAX),
    "NEXT_LINE_FULL": str(_NEXT_LINE_MAX + NEXT_PREFIX_ROOM),
    "ALIAS_PAREN": _ALIAS_PAREN,
    "P_EX": _P_EX,
    "P_CHK": _P_CHK,
    "P_RUN": _P_RUN,
    "P_BANG": _P_BANG,
    "OPENERS_TXT": _OPENERS_TXT,
    "TIMEZONE": str(_cfg.get("instance", "timezone")),
    "OPT_FORM": str(_OPT_FORM),
    "EVENT_FORMS": str(_ew.FORMS),
    "WAIT_GUARD_REASON_MIN": str(_cfg.WAIT_GUARD_REASON_MIN),
    "CAP_DAYS": f"{_wt.cap_days():g}",
    "CLOSE_REASON_MAX": str(_CLOSE_REASON_MAX),
    "OPTIONS_MIN": str(_rmod.OPTIONS_MIN),
    "OPTIONS_MAX": str(_rmod.OPTIONS_MAX),
    "OPTION_LINE_MAX": str(_rmod.OPTION_LINE_MAX),
    "DRAFT_MAX": str(_draft.MAX),
    "DRAFT_STEMS": str(_draft.STEMS),
}
_T = _tf.load("shared", VALUES, common=True)


def load_text(name: str, values: dict[str, str] | None = None, *, late: tuple[str, ...] = ()) -> _tf.Texts:
    """The text file of one tool module (text/<name>.md), read through the shared file; `values` are what the module's own texts fill in, `late` the names it passes when it asks for a text."""
    return _tf.load(name, values, late=late, parent=_T)


# The pieces below are the shared texts under the names the tests and server.py read; the words are in text/shared.md.
# A piece used by one tool's description only is not bound here (the description's own file places it).
_NEEDS_FORM = _T.piece("NEEDS_FORM")      # the sessions whose move it is now (needs), who hears only a close (observers), and the items that must close first (after)

_ASK_NONE = ("none", "clear", "-")      # the words that clear an ask; the ask's own form is in the renderer (render.ASK_RE / parse_ask)

_ANCHOR_SHAPES = _T.piece("ANCHOR_SHAPES")

_NEXT_WORDS = _T.piece("NEXT_WORDS")      # the words every tool text carries for next, one copy (the create and update descriptions, the connector's instructions)


def _lead(desc: str) -> str:
    """Every tool's description opens with the one directive a session behind the portal (cloud, Cowork), which never receives the server's `instructions=`, would otherwise miss: call rules first."""
    return _T.piece("LEAD") + desc


# `owner` is no longer an agent's parameter of create or update: who moves an item is `mover`; the item model is on this page.
_MODEL_PAGE = "docs/design"

_NEXT_REFUSALS = _T.piece("NEXT_REFUSALS")
_ITEM_FORM = _T.piece("ITEM_FORM")
_SAID_PARAM = _T.piece("SAID_PARAM")      # the said parameter's own description: the rule in full (a tool's description is cut for a CLI session, a parameter's is not)
_CHECK_FORM = _T.piece("CHECK_FORM")      # the done check: what closes the item once the hand-off's work is done
_MODEL_FORM = _T.piece("MODEL_FORM")
_SELF_WAIT_FORM = _T.piece("SELF_WAIT_FORM")
_STEP_PROOF_FORM = _T.piece("STEP_PROOF_FORM")
_ASK_RULE = _T.piece("ASK_RULE")      # what the server does with an ask on its own: the close text and the update text carry the same words
_CLOSE_REFUSAL = _T.piece("CLOSE_REFUSAL")      # the full close rule a refused close appends; the tool text carries the shorter CLOSE_FORM
_CLOSE_FORM = _T.piece("CLOSE_FORM")
_GMAIL_TERMS = _T.piece("GMAIL_TERMS")

_AFTER_PARAM = Annotated[list[str] | str | None, Field(description=_T.param("AFTER"))]
_OUTCOME_PARAM = Annotated[str, Field(description=_T.param("OUTCOME"))]
_REASON_PARAM = Annotated[str, Field(description=_T.param("REASON"))]
_DESCRIPTION_PARAM = Annotated[str, Field(description=_T.param("DESCRIPTION"))]
_OPTIONS_PARAM = Annotated[list[dict[str, Any]] | str | None, Field(description=_T.param("OPTIONS"))]
_CHECK_PARAM = Annotated[str, Field(description=_T.param("CHECK"))]
_STEP_PROOF_PARAM = Annotated[list[dict[str, Any]] | str | None, Field(description=_T.param("STEP_PROOF"))]
_WAIT_KIND_PARAM = Annotated[str, Field(description=_T.param("WAIT_KIND"))]
_WAITS_PARAM = Annotated[list[dict[str, Any]] | str | None, Field(description=_T.param("WAITS"))]
_WAIT_MODE_PARAM = Annotated[str, Field(description=_T.param("WAIT_MODE"))]
_WAIT_EVENT_PARAM = Annotated[str, Field(description=_T.param("WAIT_EVENT"))]
_MOVER_PARAM = Annotated[str, Field(description=_T.param("MOVER"))]
_THEN_PARAM = Annotated[str, Field(description=_T.param("THEN"))]
_POST_WAKE_PARAM = Annotated[str, Field(description=_T.param("POST_WAKE"))]
_CONTACT_PARAM = Annotated[str, Field(description=_T.param("CONTACT"))]
_OUTCOME_TEXT_PARAM = Annotated[str, Field(description=_T.param("OUTCOME_TEXT"))]

MSG_MAX = 4000
