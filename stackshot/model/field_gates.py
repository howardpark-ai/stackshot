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

from stackshot.core import call_log as _calls
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.model import bullet_text as _bt
from stackshot.model import faults as _faults
from stackshot.model import model_guards as _mg
from stackshot.model import next_rules as _nr
from stackshot.model import nextlines as _nl
from stackshot.model import step_split as _ss
from stackshot.model import steps as _steps
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


def subject_faults(subject: str, current: str | None = None) -> list[str]:
    """Every fault of a subject's form, each as the refusal it is alone: no scope prefix, over [subject] max_length. `current` is the stored subject of an update: a write that sets the very text
    it already has (a long one stored before the limit) is not a change and passes the length check."""
    s = _cfg.CFG["subject"]
    out: list[str] = []
    if not any(subject.startswith(pfx) for pfx in s["prefixes"]):
        out.append(f"Refused: subject must start with one of {s['prefixes']} — got {subject[:40]!r}")
    lim = _subject_max()
    if lim and len(subject) > lim and subject != current:
        out.append(f"Refused: the subject is {len(subject)} characters and the limit is {lim}, the scope prefix counted. Shorten it to the finished outcome; "
                   "the detail goes in the description bullets (and the project page's timeline).")
    return out


def _gate_subject(subject: str, current: str | None = None) -> None:
    """Refuse a subject that does not start with a scope prefix, or is over [subject] max_length (every fault of it, together; `subject_faults` has them as a list)."""
    if got := subject_faults(subject, current):
        raise _faults.refusals(got)


def fix_long_subject(subject: str, current: str | None = None) -> str:
    """A subject over [subject] max_length, put right instead of refused: cut at the last word that fits with " …" after it, the whole counted in the limit (bullet_text.cut_words: no word is cut in two, the kept
    words and the scope prefix are as written), and the reply says so (call_log.fixed). The subject as given when it fits, when it is the stored text sent back (a long one stored before the limit), when it
    has no scope prefix (the prefix check refuses it as before) or when no word after the prefix fits: the gate then refuses it as before."""
    lim = _subject_max()
    if not lim or len(subject) <= lim or subject == current:
        return subject
    pfx = next((p for p in _cfg.CFG["subject"]["prefixes"] if subject.startswith(p)), None)
    new = _bt.cut_words(subject, lim) if pfx is not None else None
    if not new or not new.startswith(pfx) or len(new) - 2 <= len(pfx.rstrip()):          # the cut fell inside the prefix, or left nothing after it
        return subject
    _calls.fixed("subject-cut", f"the subject was {len(subject)} characters and the limit is {lim}, the scope prefix counted: it was cut at the last word that fits and ends with an ellipsis; to change it, send a shorter subject",
                 fields=["subject"], stored=new, sent=subject)
    return new


def fix_bare_urls(description: str, stored: str | None = None, session: bool = False) -> str:
    """A session's description with a bare http(s) URL in it, put right instead of refused (_gate_bare_urls): each URL the stored description does not already hold is written as a link to itself,
    `[url](url)` (bullet_text.link_bare_urls: the address ends at its last URL character, one inside an angle autolink, a link, a reference definition, an attribute or code is left alone, nothing else changes), and the
    reply says so and shows the addresses (call_log.fixed). The text as given for a script's or the server's own write (not judged), when it holds no new bare URL, when it breaks the description's form for a reason other
    than a long bullet (the line cap, or a line that is no bullet: the gates refuse it, and it is not scanned), or when a URL would still be bare after the change (the gate then refuses it as before). next and ask keep
    their refusal: a link in a step or a question is the writer's to word."""
    if not session or not description:
        return description
    bad = _description_fault(description)
    if bad and bad[0] != "long":
        return description
    old = set(_bt.bare_urls(str(stored or "")))
    if not [u for u in _bt.bare_urls(description) if u not in old]:
        return description
    res = _bt.link_bare_urls(description, old)
    if res is None or res[0] == description:
        return description
    new, linked = res
    if stored is not None and new.strip() == str(stored).strip():          # the same text again, already stored as links: nothing is changed, so nothing is counted or told
        return new
    n = len(linked)
    shown = ", ".join(_clip_line(u, 60) for u in linked[:3]) + (f" and {n - 3} more" if n > 3 else "")
    _calls.fixed("description-url", f"{n} bare address{'' if n == 1 else 'es'} in the description {'was' if n == 1 else 'were'} written as a link to itself, the address as the link's text and target ({shown}): the page links a bare address by its own rule for where it ends, so the link stores the address exactly; "
                 "to give a link words, write `[words](address)`", fields=["description"], stored=new, sent=description)
    return new


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


def fix_long_bullets(desc: str, stored: str | None = None, field: str = "description") -> tuple[str, str]:
    """A description (or a close's outcome text, `field="outcome_text"`) whose bullets read over the limit, put right instead of refused: each long bullet is split at the gaps after its sentences into shorter bullets, a clause
    still over the limit on its own at its last comma, colon, spaced dash or opening parenthesis that leaves each piece within it, and a bullet no such cut splits at its last space that fits, the rest on an indented `- ` line under
    it (bullet_text.split_long_wrap: no word is dropped or cut, nothing is cut inside a link, a naked URL or a code span), and the reply says so (call_log.fixed: kind description-bullet or outcome-bullet for the first
    two cuts, bullet-wrap or outcome-wrap for the last). -> (the text, the History line the caller writes onto the item: the server changed it, "" when it did not). The text as given when it is within the form, when the fault is anything
    but a long bullet, or when the split cannot be made (a piece that is one unbroken token, a bullet with lines indented under it, more lines than the cap): the gate then refuses it as before. A text with no bullet form
    required ([description] require_bullets = false) is left alone. When the split text breaks the form some other way (a later line that is no bullet), the split text comes back with no note and no fix counted, so
    the gate refuses the fault that is left, not a long bullet the server would have put right. `stored` is the text the item holds already (an update passes it): when the split gives exactly that text, the same long
    text has been sent before and is stored as split, so the server changed nothing this time: no fix is counted, no reply line, no History line."""
    if not desc or not _bullets_on():
        return desc, ""
    max_lines, line_max = _description_limits()
    bad = _bt.judge(desc, max_lines, line_max)
    if not bad or bad[0] != "long":
        return desc, ""
    res = _bt.split_long_wrap(desc, max_lines, line_max)
    if not res:
        return desc, ""
    new, n, soft, wrapped = res
    if _bt.judge(new, max_lines, line_max):          # a split that still breaks the form (a later line not a bullet) is no fix: the gate refuses the fault that is left, and nothing is counted or told
        return new, ""
    if stored is not None and new.strip() == str(stored).strip():          # the same long text again, already stored as split: nothing is changed, so nothing is counted, told or noted
        return new, ""
    by_sentence = n - wrapped
    hist: list[str] = []
    if by_sentence:
        where, h_ = ("at the end of a sentence or at a comma, colon, dash or parenthesis", "at the end of a sentence or a comma, colon, dash or parenthesis") if soft else ("at the end of a sentence",) * 2
        kept = "no word changed; a spaced dash at a cut is dropped" if soft else "no word changed"
        _calls.fixed("description-bullet" if field == "description" else "outcome-bullet",
                     f"{by_sentence} {field} bullet{'' if by_sentence == 1 else 's'} over {line_max} characters {'was' if by_sentence == 1 else 'were'} split {where} into shorter bullets, {kept}", fields=[field], stored=new, sent=desc)
        hist.append(f"{field}: {by_sentence} long bullet{'' if by_sentence == 1 else 's'} split by the server {h_}")
    if wrapped:
        _calls.fixed("bullet-wrap" if field == "description" else "outcome-wrap", f"{wrapped} {field} bullet{'' if wrapped == 1 else 's'} over {line_max} characters {'was' if wrapped == 1 else 'were'} cut at a space, the rest on an indented `- ` line under it, no word changed",
                     fields=[field], stored=new, sent=desc)
        hist.append(f"{field}: {wrapped} long bullet{'' if wrapped == 1 else 's'} continued on an indented line by the server, cut at a space")
    return new, "; ".join(hist)


def _step_line_room() -> int:
    """The longest action a split puts on a line of next: [metadata.next] line_max (200), or 300 (the step's own line limit) when that refusal is off."""
    return _next_line_max() or 300


def fix_long_step(step: str) -> tuple[str, list[str]]:
    """A step of his that is a long chain of actions, put into the shape the board draws instead of refused or left unreadable: the step becomes a short summary and each action a line of next that opens with his name
    (step_split.split_step: split at sentence ends, semicolons and inline numbered items, every word kept; a text of more than SPLIT_MAX characters or more than MAX_ACTIONS actions is left as written).
    → (the step to store, the lines to add to next); the step as given and no lines when it is short, already structured, or holds one action. Writes nothing and says nothing: the caller says what it did
    (`say_long_step`) once it knows how many lines it added."""
    got = _ss.split_step(step, _step_line_room())
    if got is None:
        return step, []
    return got


def long_step_skipped(step: str) -> str:
    """Why a one-line step over the step limit was not split into lines ("" when it was, or it is no case for it): the words that go beside its refusal, so the writer knows the server tried."""
    return _ss.skipped(step, _step_line_room())


def say_long_step(step: str, lines: list[str], added: int, settled: int = 0) -> None:
    """The reply's line for a long step that was split into `lines` (call_log.fixed, kind step-split): what was done, or, when `added` is 0 (the summary and every one of its lines are on the item already: the same step
    sent again), that nothing was added. `settled`: how many of the lines were ticked done or dropped before and stay so (they are no open lines on the item, and the reply does not say they are)."""
    open_n = max(0, len(lines) - added - settled)
    acts, lns = (f"{len(lines)} action", f"{len(lines)} line") if len(lines) == 1 else (f"{len(lines)} actions", f"{len(lines)} lines")      # a lead-in with its list is one line
    was = [f"{open_n} of the lines {'was' if open_n == 1 else 'were'} on the item already" if open_n else "", f"{settled} {'was' if settled == 1 else 'were'} done or dropped before and stay so" if settled else ""]
    was_txt = " and ".join(x for x in was if x)
    if added:
        nested = sum(len(x.splitlines()) - 1 for x in lines)      # the items of a list that stand as sub-lines under their lead-in line
        _calls.fixed("step-split", f"the step ran {len(_steps.clean(step))} characters with {acts}, so it was split into a summary and {lns} of next that open with {OWNER}'s name, "
                     "which the board draws as his list; every word is in a line" + (f"; the {nested} items of a list stand as indented sub-lines under their lead-in line, ticked with it" if nested else "")
                     + ("" if added == len(lines) else f" ({was_txt}, so {added} were added)"), fields=["step", "next"])
    elif settled:
        _calls.fixed("step-split", f"the step ran {len(_steps.clean(step))} characters with {acts}: it is stored as a summary, and of its {lns} {was_txt}, so nothing was added", fields=["step"])
    else:
        _calls.fixed("step-split", f"the step ran {len(_steps.clean(step))} characters with {acts}: it is stored as a summary, and its {lns} of next {'is' if len(lines) == 1 else 'are'} on the item already, so nothing was added",
                     fields=["step"])


def fix_long_owner_lines(next_: str, known: set[str]) -> str:
    """The lines of next that open with the owner's name and run long with several actions, one line per action (step_split.split_line), the other lines as they are, and the reply says so (call_log.fixed).
    A line that is an open step already (`known`: its steps.key) or one whole command in backticks is left as it stands, and so is a line that has sub-lines under it (the writer's own shape). A lead-in that ends with
    a colon, followed by `1) … 2) …`, is one line with its items as indented sub-lines (step_split). The text as given when no line is split."""
    if not next_ or not str(next_).strip():
        return next_
    room, out, n_in, n_out = _step_line_room(), [], 0, 0
    for entry in _nl.split(next_):
        first = entry.split("\n", 1)[0]
        parts = None if _steps.key(entry) in known or _owner_command(first) else _ss.split_line(entry, room)
        if parts:
            out.extend(parts)
            n_in, n_out = n_in + 1, n_out + len(parts)
        else:
            out.append(entry)
    if not n_in:
        return next_
    _calls.fixed("step-split", f"{n_in} line{'' if n_in == 1 else 's'} of next that open{'s' if n_in == 1 else ''} with {OWNER}'s name held several actions, so {'it was' if n_in == 1 else 'they were'} split into {n_out} lines, "
                 "one per action; every word is in a line", fields=["next"])
    return "\n".join(out)


def _description_fault(desc: str) -> tuple[str, str, int] | None:
    """The first fault of a description's form (bullet_text.judge; with [description] require_bullets = false the line cap alone), None when it keeps it."""
    max_lines, line_max = _description_limits()
    return _bt.judge(desc, max_lines, line_max) if _bullets_on() else (("lines", "", n) if (n := len([ln for ln in desc.splitlines() if ln.strip()])) > max_lines else None)


def description_faults(desc: str, field: str = "description") -> list[str]:
    """Every fault of a description's form, each as the refusal `_gate_description` raises for it alone: the form of its lines (the first bullet or line that breaks it) and, for a description, a forbidden word.
    A description is short `- ` bullets, one fact each, refused at write time and not only noted. Checks the text
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
    out: list[str] = []
    bad = _description_fault(desc)
    if bad:
        kind, ln, n = bad
        if kind == "lines":
            out.append(f"Refused: {field} has {n} lines, the limit is {max_lines}; {fix}")
        elif kind == "marker":
            out.append(f"Refused: {field} line is not a `- ` bullet: \"{_clip_line(ln, 60)}\"; {fix}")
        else:
            out.append(f"Refused: {field} bullet is {n} characters, the limit is {line_max} (a link's URL does not count): \"{_clip_line(ln, 60)}\"; the server splits a long bullet at a sentence end or a space by itself, "
                       f"and could not split this one (no ordinary space to cut at within a line: a word or link longer than a line, or text spaced only with non-breaking or wide spaces; a bullet with lines indented under it, or more than {max_lines} lines once split); {fix}")
    if field != "description":
        return out
    low = desc.lower()
    for tok in d.get("forbid_tokens", []):
        if tok.lower() in low:
            out.append(f"Refused: description contains {tok!r} — a description is the live state, never a changelog; fold the resolution into the state")
            break
    return out


def _gate_description(desc: str, field: str = "description") -> None:
    """Refuse a description that breaks the form (every fault of it, together; `description_faults` has them as a list)."""
    if got := description_faults(desc, field):
        raise _faults.refusals(got)


_GOAL_RETRY = (" Retry the call with the description's first bullet changed; a session whose tool list was cached before this rule reads the live text through the MCP Portal "
               "(portal_codemode_execute with codemode.stackshot_create or codemode.stackshot_update), and a relaunch does not refresh it.")


def fix_goal_label(desc: str, stored: str = "") -> str:
    """A session's description whose first `- ` bullet opens with a goal word in another form (`goal: x`, `Goal - x`, `GOALS: x`, a bold label, the Korean word for it), put right instead of refused: the bullet is written
    `- Goal: x` (bullet_text.relabel_goal: the words after the label and every other line are as written) and the reply says so (call_log.fixed). The text as given when it opens with `Goal:` already, when its first bullet
    opens with anything else (the gate then refuses it and shows the description with that bullet as the goal) or holds a label and nothing after it. The callers run it where `_gate_goal` would judge the text.
    [description] require_bullets = false switches it off with the other form checks. `stored` is the description the item holds (an update): a text that is the stored one once relabelled is no fix."""
    if not desc or not _bullets_on():
        return desc
    res = _bt.relabel_goal(desc)
    if res is None:
        return desc
    new, label = res
    if stored.strip() and new.strip() == stored.strip():
        return new          # the stored text with only its label written otherwise: the write changes nothing, so no fix is counted or told
    _calls.fixed("description-goal", f"the description's first bullet opened with \u201c{label}\u201d and is stored as `- Goal: ...`, the words after it as you wrote them; to change the goal, send the description with the first bullet you want",
                 fields=["description"], stored=new, sent=desc)
    return new


def _sendable(desc: str) -> bool:
    """Would `desc` pass the form gate as sent: within the line cap and the bullet length, or after the bullet fix (`fix_long_bullets`) has split what it can. Nothing is counted or noted."""
    max_lines, line_max = _description_limits()
    if not _bt.judge(desc, max_lines, line_max):
        return True
    res = _bt.split_long_wrap(desc, max_lines, line_max)
    return bool(res) and not _bt.judge(res[0], max_lines, line_max)


def goal_fault(desc: str) -> str:
    """The refusal text `_gate_goal` raises for `desc`, "" when the description opens with its goal (or the form checks are off). A session's new description, or one it rewrites, opens with the goal: the first `- ` bullet starts `Goal:` (case-sensitive, right after the dash) and says the finished outcome;
    a symptom, cause or trigger goes in a later bullet that opens `Problem:`. Why: an item once carried a title and bullets that described the trouble and never said what result was wanted.
    Judged on the text written in the call only (the callers run it for a session's create and for an update that replaces the description with other text), after the form gate.
    The first bullet is the first `- ` line (bullet_text.first_bullet); a description with no bullet is refused the same way. [description] require_bullets = false switches it off with the other form checks."""
    if not _bullets_on() or _bt.goal_of(desc) is not None:
        return ""
    first = _bt.first_bullet(desc)
    saw = f"the first bullet starts “{_clip_line(' '.join(first.split()[:6]), 60)}”" if first is not None else "it has no `- ` bullet"
    ex = _bt.goal_example(desc)
    if ex is not None and not _sendable(ex):      # a corrected description the form gate would refuse again is no example to copy
        ex = None
    shown = (f" Send the description again with that bullet as the goal:\n{ex}\n" + "If that bullet names a symptom, a cause or a trigger, write the finished outcome as the goal and move the bullet to a later bullet that opens `Problem:`.") if ex else ""
    return (f"Refused: the description must open with its goal, and {saw}.{shown} The subject and the first bullet name the same finished outcome: `- Goal: <the result you want, in a sentence>`; "
                    "a symptom, a cause or a trigger goes in a later bullet that opens `Problem:`. "
                    "Example: the symptom title “Fix X fails when Y” becomes the outcome title “Make X work when Y”, with `- Goal: X works when Y` as the first bullet "
                    "and `- Problem: X fails when Y` as the second. `Goal:` is case-sensitive and sits right after the dash." + _GOAL_RETRY)


def _gate_goal(desc: str) -> None:
    """Refuse a description that does not open with its goal (`goal_fault` has the rule and the text)."""
    if why := goal_fault(desc):
        raise ToolError(why)


def bare_url_faults(fields: dict[str, str], stored: dict[str, Any] | None = None, session: bool = False) -> list[str]:
    """One refusal text per field that holds a bare URL (the first in it), none when the write is no session's. A session's write through the create and update tools (`session`: the per-write flag the caller reads) may not put a bare http(s) URL in description, next or ask: the page does not always draw one as a
    link, so a reader sees plain text. A URL inside `[words](url)`, a code span or a fenced block is fine. Judges the text written in this call, `fields` by name, and of that only a URL
    the stored text of the field (`stored`, an update's) does not already hold, so an update that sets a field again with an old bare URL in it is not refused for that. Scripts and the
    server's own writes are not judged. How a page draws a bare URL is not changed here."""
    out: list[str] = []
    if not session:
        return out
    for field, text in fields.items():
        if not text:
            continue
        old = set(_bt.bare_urls(str((stored or {}).get(field) or "")))
        for url in _bt.bare_urls(text):
            if url not in old:
                out.append(f"Refused: {field} has a bare URL ({_clip_line(url, 80)}) and the page may not draw it as a link. Write it as `[words](url)`, the words saying what the link opens "
                           "(a URL in a code span or a fenced block is fine)")
                break
    return out


def _gate_bare_urls(fields: dict[str, str], stored: dict[str, Any] | None = None, session: bool = False) -> None:
    """Refuse a bare URL in a session's description, next or ask (every field that has one, together; `bare_url_faults` has them as a list)."""
    if got := bare_url_faults(fields, stored, session):
        raise _faults.refusals(got)


def _owner_command(line: str) -> bool:
    """`<owner>: `a command in backticks``: the line the owner runs, whole in one backtick span (the form docs/configuration.md shows); prose after the name is not one."""
    return re.fullmatch(rf"{re.escape(OWNER)}:\s*`[^`\n]+`[.,;]?", line.strip(), re.I) is not None


NEXT_LONG_SHOWN = 3         # a next with more long lines than this names the first few and counts the rest
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


def next_faults(next_: str, has_ask: bool = False, session: bool = False) -> list[str]:
    """Every fault of the text of next, each as the refusal `_gate_next` raises for it alone: the lines that name no one (one fault for all of them) and each line over the limit. a `next` line over [metadata.next] line_max (200; 0 = off) characters is refused, where it used to be noted. Checks only the text written
    in this call. A link counts by its text and a naked URL not at all, as in a description. Not judged: a `<owner>: `command`` line (the
    whole command in one backtick span; any other line of his is prose and counts), and next's first non-blank line when it is an ask line and
    the call passes no `ask` (a client without the ask parameter writes the ask there; the server lifts it). Hashes, test counts and past
    tense stay notes (_report_note). (a session's write through the create and update tools only, `session`): a line that opens with no `<actor>:` is refused, naming the line and the fix; a sub-line under a named step is fine."""
    out: list[str] = []
    if session and (bad := _nr.unnamed(next_, skip_first=None if has_ask else (lambda ln: _rmod.parse_ask(ln) is not None))):
        out.append(f"Refused: a line of next names no one: \"{_clip_line(bad[0], 60)}\"" + (f" (and {len(bad) - 1} more)" if len(bad) > 1 else "") + (f" ({h})" if (h := _nr.hint(bad[0])) else "") + f". One step is one action with one named actor: {_nr.FIX}. "
                   "A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next")
    limit = _next_line_max()
    if not limit:
        return out                   # off: [metadata.next] line_max = 0, or [description] require_bullets = false (then _report_note notes a long line again)
    first = True
    long_: list[str] = []
    long_more = 0
    for raw in str(next_ or "").splitlines():
        ln = re.sub(r"^\s*(?:[-*\u2022]\s+)?", "", raw)
        if not ln.strip():
            continue
        lifted, first = first and not has_ask and _rmod.parse_ask(ln.strip()) is not None, False
        if lifted or _owner_command(ln):
            continue
        fault = ""
        if (n := _next_len(ln)) > limit:
            fault = (f"Refused: a line of next is {n} characters after its `<actor>: ` prefix, the limit is {limit} (a link's URL does not count): \"{_clip_line(ln, 60)}\"; "
                     "next is one short line per next action, each naming who takes it; results and detail go on the project page (Current state or a timeline line)")
        elif (whole := _visible_len(ln)) > limit + NEXT_PREFIX_ROOM:         # the prefix is a name of up to three words of any length: the line as a whole is capped too
            fault = (f"Refused: a line of next is {whole} characters in all, the limit for the whole line is {limit + NEXT_PREFIX_ROOM} (the {limit} counts after its `<actor>: ` prefix, which has {NEXT_PREFIX_ROOM} characters of room; "
                     f"a link's URL does not count): \"{_clip_line(ln, 60)}\"; next is one short line per next action, each naming who takes it, with a short name; results and detail go on the project page (Current state or a timeline line)")
        if fault and len(long_) < NEXT_LONG_SHOWN:
            long_.append(fault)
        elif fault:
            long_more += 1
    if long_more:
        long_[-1] += f" (and {long_more} more line{'s' if long_more > 1 else ''} over the limit)"
    return [*out, *long_]


def _gate_next(next_: str, has_ask: bool = False, session: bool = False) -> None:
    """Refuse a text of next that breaks its form (every fault of it, together; `next_faults` has them as a list)."""
    if got := next_faults(next_, has_ask, session):
        raise _faults.refusals(got)


def _require_marks() -> bool:
    """[metadata.next] require_marks (default true): a write of next that leaves out an open step of the writer's without marking it done, dropped or reworded keeps the step open (the update carries its line over and the reply says so; a line rewritten with words added is refused). false is the way back: the step reads as dropped, with nobody and no time."""
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
