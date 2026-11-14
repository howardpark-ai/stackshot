"""field_gates.py: the write-time checks of an item's fields: the subject (its scope prefix and length, `_gate_subject`), the description (short `- ` bullets, `_gate_description`, and its opening
goal, `_gate_goal`), `next` (a named actor and a length per line, `_gate_next`; the marks of a dropped step), a session's bare URLs (`_gate_bare_urls`), the small limits they read (`_subject_max`,
`_close_reason_max`, `_description_limits`, `_next_line_max`, `_bullets_on`, `_fit`) and the two sentences a refusal borrows from the fleet settings (`_when_idle`, `_fleet_tool`).

Each is a rule of the item's own text and the instance's settings: it raises ToolError with the refusal, or returns what it normalized, and reads nothing from the store and changes nothing. The two
checks that apply to a session's own write only (`_gate_next`'s actor check, `_gate_bare_urls`) take that as the `session` argument: the caller reads the per-write flag (`service/writes.py`) and passes it. The
metadata check, which looks a project's page up in the registry and may rebuild it, and the registry readers it uses are `service/gates.py`'s."""
from __future__ import annotations

import json
import re
import shlex
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.model import bullet_text as _bt
from stackshot.model import model_guards as _mg
from stackshot.model import next_rules as _nr
from stackshot.model import nextlines as _nl
from stackshot.model.bullet_text import _clip_line
from stackshot.web import render as _rmod


# ----------------------------------------------------------------------------- gates (all deterministic)
SUBJECT_MAX_DEFAULT = 80          # a title is one short line (was 200 in code, 160 in the example config); the length of the whole subject, scope prefix included
CLOSE_REASON_MAX_DEFAULT = 120    # a close's reason is one short line ([close] reason_max)


def _subject_max() -> int:
    """[subject] max_length (default 80): the longest subject a create or an update that sets one takes, the scope prefix counted (len of the stored text, as before)."""
    return int(_cfg.CFG["subject"].get("max_length", SUBJECT_MAX_DEFAULT) or 0)


def _close_reason_max() -> int:
    """[close] reason_max (default 120): the longest reason a close (complete, or update with status=completed) takes; 0 = no limit."""
    return int((_cfg.CFG.get("close") or {}).get("reason_max", CLOSE_REASON_MAX_DEFAULT) or 0)


def _fit(text: str, limit: int) -> str:
    """Free text as one line of at most `limit` characters (0 = no limit): whitespace collapsed, cut at a word with an ellipsis that is counted. For what the server writes itself,
    where a gate must never refuse it (a close's reason, a subject it builds)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not limit or len(t) <= limit:
        return t
    room = max(limit - 2, 1)
    cut = t[:room].rsplit(" ", 1)[0] if " " in t[:room] else t[:room]
    return cut.rstrip(" ,;:") + " …"


# a subject that already opens with a bracketed tag or a "word:" (`[Work] x`, `[work]x`, ` [work] x`, `work: x`) is somebody's attempt at a prefix, not a missing one: it is refused as ever, the list named
_SUBJECT_TAGGED = re.compile(r"[\s​-‏⁠﻿]*(?:\[[^\]]*\]|\w+:)")


def _gate_subject(subject: str, current: str | None = None) -> None:
    """Refuse a subject that does not start with a scope prefix, or is over [subject] max_length. `current` is the stored subject of an update: a write that sets the very text
    it already has (a long one stored before the limit) is not a change and passes the length check."""
    s = _cfg.CFG["subject"]
    if not any(subject.startswith(pfx) for pfx in s["prefixes"]):
        raise ToolError(f"Refused: subject must start with one of {s['prefixes']} — got {subject[:40]!r}")
    lim = _subject_max()
    if lim and len(subject) > lim and subject != current:
        raise ToolError(f"Refused: the subject is {len(subject)} characters and the limit is {lim}, the scope prefix counted. Shorten it to the action and its object; "
                        "the detail goes in the description bullets (and the project page's timeline).")


def _when_idle() -> str:
    """What a session does about a recycle no item covers, read at use: run [fleet] recycle_when_idle with its reason (the fleet
    tool runs the recycle once the box is idle), or, with no such command configured, nothing: the change waits for the next one."""
    cmd = shlex.join(_cfg.recycle_when_idle())
    return f'run {cmd} "<reason>"' if cmd else "leave it for the next recycle (no idle-recycle command is configured)"


def _fleet_tool() -> str:
    """The fleet tool as the prose names it: [fleet] tool_name, else "the fleet tool"."""
    return _cfg.fleet_tool() or "the fleet tool"


# (a recycle is not an item, a flag does that): a subject whose task is only
# to relaunch or recycle panes or sessions. Its words: relaunch/recycle first, or relaunch/recycle/restart followed by panes,
# sessions or the fleet.
_RECYCLE_ONLY = re.compile(r"^\s*(?:re-?launch|recycle)\b|\b(?:re-?launch|recycle|restart)\s+(?:(?:the|every|all|each)\s+)?"
                           r"(?:claude\s+)?(?:panes?|sessions?|fleet|clis?)\b", re.I)


def _gate_recycle_item(subject: str) -> None:
    rest = subject
    for pfx in _cfg.CFG["subject"]["prefixes"]:
        if rest.startswith(pfx):
            rest = rest[len(pfx):]; break
    if _RECYCLE_ONLY.search(rest):
        raise ToolError("Refused: a recycle is not an item. Flag the item whose change needs it: update(<item>, recycle=true), with the "
                        f"after-recycle check as its next; when no item covers the change, {_when_idle()}")


_visible_len = _bt.visible_len       # what the length count cuts out of a line is bullet_text's (links in all their forms, naked URLs); _RX_LINK_URL, the report note's own, is unchanged


def _bullets_on() -> bool:
    """[description] require_bullets (default true): false switches all of the description strictness off (the bullet and length checks, the next-line refusal, the question route's
    bulleting and clipping, the cold call's re-bulleting) and leaves the line cap, forbid_tokens and [model] description_guard."""
    return bool(_cfg.CFG["description"].get("require_bullets", True))


def _description_limits() -> tuple[int, int]:
    d = _cfg.CFG["description"]
    return int(d.get("max_lines", 8)), int(d.get("line_max", 120))


def _next_line_max() -> int:
    """The longest line of next the write takes: [metadata.next] line_max (200); 0 when the refusal is off (line_max = 0, or require_bullets = false)."""
    return int(_cfg.CFG.get("metadata", {}).get("next", {}).get("line_max", 200)) if _bullets_on() else 0


def _gate_description(desc: str, field: str = "description") -> None:
    """A description is short `- ` bullets, one fact each, refused at write time and not only noted. Checks the text
    written in this call and nothing stored (the callers pass it only when the write carries a description, a close included). The judgement is
    bullet_text.judge, which the re-bullet pass uses too: at most [description] max_lines non-blank lines, each a `- ` bullet (a dash and spaces or a tab; an
    indented bullet is a bullet, an indented line that is not one is prose) of at most line_max characters as it reads (a link by its text, its destination in any
    form and a naked URL not at all). A `>` quote line is exempt from the marker but not the length, a fenced block (fence lines included) from both; all count toward
    max_lines. The question route and the cold call's close write bullets themselves and go through this gate like any create. [description] require_bullets = false
    leaves the line cap and the forbidden tokens only. `field` names the text in a refusal. The outcome text of a close (`outcome_text`) is held to the same form and length but may say
    what was resolved or done, so it skips the forbidden tokens, which keep a description from reading as a changelog."""
    d = _cfg.CFG["description"]
    max_lines, line_max = _description_limits()
    fix = f"write short `- ` bullets, one fact each (at most {max_lines} lines of {line_max} characters; parallel bullets such as batches, steps or parts go under one parent bullet, indented two spaces); details go on the project page"
    bad = _bt.judge(desc, max_lines, line_max) if _bullets_on() else (("lines", "", n) if (n := len([ln for ln in desc.splitlines() if ln.strip()])) > max_lines else None)
    if bad:
        kind, ln, n = bad
        if kind == "lines":
            raise ToolError(f"Refused: {field} has {n} lines, the limit is {max_lines}; {fix}")
        if kind == "marker":
            raise ToolError(f"Refused: {field} line is not a `- ` bullet: \"{_clip_line(ln, 60)}\"; {fix}")
        raise ToolError(f"Refused: {field} bullet is {n} characters, the limit is {line_max} (a link's URL does not count): \"{_clip_line(ln, 60)}\"; {fix}")
    if field != "description":
        return
    low = desc.lower()
    for tok in d.get("forbid_tokens", []):
        if tok.lower() in low:
            raise ToolError(f"Refused: description contains {tok!r} — a description is the live state, never a changelog; fold the resolution into the state")


_GOAL_RETRY = (" Retry the call with the description's first bullet changed; a session whose tool list was cached before this rule reads the live text through the MCP Portal "
               "(portal_codemode_execute with codemode.stackshot_create or codemode.stackshot_update), and a relaunch does not refresh it.")


def _gate_goal(desc: str) -> None:
    """A session's new description, or one it rewrites, opens with the goal: the first `- ` bullet starts `Goal:` (case-sensitive, right after the dash) and says the outcome wanted;
    a symptom, cause or trigger goes in a later bullet that opens `Problem:`. Why: an item once carried a title and bullets that described the trouble and never said what result was wanted.
    Judged on the text written in the call only (the callers run it for a session's create and for an update that replaces the description with other text), after the form gate.
    The first bullet is the first `- ` line (bullet_text.first_bullet); a description with no bullet is refused the same way. [description] require_bullets = false switches it off with the other form checks."""
    if not _bullets_on() or _bt.goal_of(desc) is not None:
        return
    first = _bt.first_bullet(desc)
    saw = f"the first bullet starts “{_clip_line(' '.join(first.split()[:6]), 60)}”" if first is not None else "it has no `- ` bullet"
    raise ToolError(f"Refused: the description must open with its goal, and {saw}. The subject and the first bullet state the outcome wanted: `- Goal: <the result you want, in a sentence>`; "
                    "a symptom, a cause or a trigger goes in a later bullet that opens `Problem:`. "
                    "Example: the symptom title “Fix X fails when Y” becomes the outcome title “Make X work when Y”, with `- Goal: X works when Y` as the first bullet "
                    "and `- Problem: X fails when Y` as the second. `Goal:` is case-sensitive and sits right after the dash." + _GOAL_RETRY)


def _gate_bare_urls(fields: dict[str, str], stored: dict[str, Any] | None = None, session: bool = False) -> None:
    """A session's write through the create and update tools (`session`: the per-write flag the caller reads) may not put a bare http(s) URL in description, next or ask: the page does not always draw one as a
    link, so a reader sees plain text. A URL inside `[words](url)`, a code span or a fenced block is fine. Judges the text written in this call, `fields` by name, and of that only a URL
    the stored text of the field (`stored`, an update's) does not already hold, so an update that sets a field again with an old bare URL in it is not refused for that. Scripts and the
    server's own writes are not judged. How a page draws a bare URL is not changed here."""
    if not session:
        return
    for field, text in fields.items():
        if not text:
            continue
        old = set(_bt.bare_urls(str((stored or {}).get(field) or "")))
        for url in _bt.bare_urls(text):
            if url not in old:
                raise ToolError(f"Refused: {field} has a bare URL ({_clip_line(url, 80)}) and the page may not draw it as a link. Write it as `[words](url)`, the words saying what the link opens "
                                "(a URL in a code span or a fenced block is fine)")


def _owner_command(line: str) -> bool:
    """`<owner>: `a command in backticks``: the line the owner runs, whole in one backtick span (the form docs/configuration.md shows); prose after the name is not one."""
    return re.fullmatch(rf"{re.escape(OWNER)}:\s*`[^`\n]+`[.,;]?", line.strip(), re.I) is not None


NEXT_PREFIX_ROOM = 80       # a line of next may be this many characters longer than [metadata.next] line_max in all: room for its `<actor>: ` prefix (the whole-line cap is line_max + 80, 280 by default)


def _next_len(line: str) -> int:
    """The length a line of next counts for the limit ([metadata.next] line_max): the characters after its `<actor>: ` prefix (the text up to and including the first colon-space that names the
    actor, as the actor check reads it: `my-x (builder): `, a list marker or bold marks in front of it), so that a long session name costs the action no room; a link counts by its text and a naked
    URL not at all (_visible_len). A line with no recognizable prefix counts whole."""
    s = line.strip()
    c = _mg._MARK_RX.sub("", s.replace("**", ""))
    m = _mg._NAME_RX.match(c)
    if not m or _mg.not_actor(m.group("name")):         # `Status:` and the like name no one
        return _visible_len(line)
    target = len(s.replace("**", "")) - len(c) + m.end()        # the characters of s, bold marks aside, that the prefix (marker and spaces in front of it included) takes
    i, seen = 0, 0
    while i < len(s) and seen < target:
        if s.startswith("**", i):
            i += 2
            continue
        i += 1
        seen += 1
    return _visible_len(s[i:])


def _gate_next(next_: str, has_ask: bool = False, session: bool = False) -> None:
    """a `next` line over [metadata.next] line_max (200; 0 = off) characters is refused, where it used to be noted. Checks only the text written
    in this call. A link counts by its text and a naked URL not at all, as in a description. Not judged: a `<owner>: `command`` line (the
    whole command in one backtick span; any other line of his is prose and counts), and next's first non-blank line when it is an ask line and
    the call passes no `ask` (a client without the ask parameter writes the ask there; the server lifts it). Hashes, test counts and past
    tense stay notes (_report_note). (a session's write through the create and update tools only, `session`): a line that opens with no `<actor>:` is refused, naming the line and the fix; a sub-line under a named step is fine."""
    if session and (bad := _nr.unnamed(next_, skip_first=None if has_ask else (lambda ln: _rmod.parse_ask(ln) is not None))):
        raise ToolError(f"Refused: a line of next names no one: \"{_clip_line(bad[0], 60)}\"" + (f" (and {len(bad) - 1} more)" if len(bad) > 1 else "") + (f" ({h})" if (h := _nr.hint(bad[0])) else "") + f". One step is one action with one named actor: {_nr.FIX}. "
                        "A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next")
    limit = _next_line_max()
    if not limit:
        return                       # off: [metadata.next] line_max = 0, or [description] require_bullets = false (then _report_note notes a long line again)
    first = True
    for raw in str(next_ or "").splitlines():
        ln = re.sub(r"^\s*(?:[-*\u2022]\s+)?", "", raw)
        if not ln.strip():
            continue
        lifted, first = first and not has_ask and _rmod.parse_ask(ln.strip()) is not None, False
        if lifted or _owner_command(ln):
            continue
        if (n := _next_len(ln)) > limit:
            raise ToolError(f"Refused: a line of next is {n} characters after its `<actor>: ` prefix, the limit is {limit} (a link's URL does not count): \"{_clip_line(ln, 60)}\"; "
                            "next is one short line per next action, each naming who takes it; results and detail go on the project page (Current state or a timeline line)")
        if (whole := _visible_len(ln)) > limit + NEXT_PREFIX_ROOM:         # the prefix is a name of up to three words of any length: the line as a whole is capped too
            raise ToolError(f"Refused: a line of next is {whole} characters in all, the limit for the whole line is {limit + NEXT_PREFIX_ROOM} (the {limit} counts after its `<actor>: ` prefix, which has {NEXT_PREFIX_ROOM} characters of room; "
                            f"a link's URL does not count): \"{_clip_line(ln, 60)}\"; next is one short line per next action, each naming who takes it, with a short name; results and detail go on the project page (Current state or a timeline line)")


def _require_marks() -> bool:
    """[metadata.next] require_marks (default true): a write of next that drops an open step without marking it done or dropped is refused. false is the way back: the step reads as dropped, with nobody and no time."""
    return bool(_cfg.CFG.get("metadata", {}).get("next", {}).get("require_marks", True))


def _marks_given(v: Any) -> bool:
    """Does a `done` or `dropped` argument name a step? A list with an entry, a position (any number, so that 0 is refused as no step), or text."""
    if isinstance(v, bool) or v is None:
        return False
    if isinstance(v, int):
        return True
    return bool(v if isinstance(v, (list, tuple)) else str(v).strip())


def _nl_text_without(meta: dict[str, Any], texts: list[str], keeper: str) -> str:
    """The item's next as it reads once the lines `texts` are taken out of it (nextlines.prune on a copy): what the checklist is lined up with."""
    probe = json.loads(json.dumps(meta))
    _nl.prune(probe, texts, keeper)
    return str(probe.get("next") or "")
