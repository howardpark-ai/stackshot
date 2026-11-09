"""field_gates.py: the write-time checks of an item's fields and the registry readers they look pages up with: the subject (its scope prefix and length, `_gate_subject`, `_project_subject_prefix`),
the description (short `- ` bullets, `_gate_description`, and its opening goal, `_gate_goal`), `next` (a named actor and a length per line, `_gate_next`; the marks of a dropped step), a session's bare URLs
(`_gate_bare_urls`), the metadata (`_gate_metadata`, with its page lookup in the registry: `_registry_hit`, `_registry_hits`, `_registry_text`), the small limits they read (`_subject_max`, `_close_reason_max`,
`_description_limits`, `_next_line_max`, `_bullets_on`, `_fit`) and the thread-local that marks a session's own write (`_SESSION_NEXT`).

server.py is being split into one module per area (CONTRIBUTING.md, Layout). The module needs nothing of server.py (a module here cannot import it, and it runs as `__main__`): it reads the config, the store's
path, the registry (`shared.py`) and the pure text modules. server.py imports each name its writes, its tools and the suites read back from here, so `server._gate_description`, `server._fit`,
`server._SESSION_NEXT` and the others stay the names they use. `_SESSION_NEXT` is set (`.on`) by the create and update tools' own calls in server.py and read here; it is never rebound, so the name on `server` and the one
here are one object. No suite sets a name on `server` that code here reads."""
from __future__ import annotations

import datetime as dt
import json
import re
import shlex
import sys
import threading
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.model import bullet_text as _bt
from stackshot.model import model_guards as _mg
from stackshot.model import next_rules as _nr
from stackshot.model import nextlines as _nl
from stackshot.projects import brains as _brains
from stackshot.projects import pages as _pages
from stackshot.projects import projects as _prj
from stackshot.web import render as _rmod
from stackshot.web import store as _store
from stackshot.web.common import OWNER, _clip_line
from stackshot.web.shared import _registry, _roles_sync_safe

_SESSION_NEXT = threading.local()  # `.on` around the create and update tools' own calls: only a session's write is judged by the write checks of Next (N1, N3, N6; next_rules.py); a script's, the router's and the server's own writes (_update and _create called inside the server) are not


# ----------------------------------------------------------------------------- registries
def _registry_text() -> str:
    """The page registry file's text for the client API (`/client/registry`), with the project record's entries laid over the pages when there are any: a hook on another machine reads
    the same registry as the server does. The file's own text when no entry changes a page."""
    text = (_store.STORE / "projects.json").read_text(encoding="utf-8")
    try:
        doc = json.loads(text)
        pages = doc.get("pages") if isinstance(doc, dict) else None
        laid = _prj.with_record(pages) if isinstance(pages, dict) else pages
        return text if laid is pages else _prj.registry_json({**doc, "pages": laid})
    except Exception:  # noqa: BLE001
        return text         # a file that does not parse is served as it always was; only an unreadable one is "no registry yet"


def _registry_hits(name: str, value: str) -> list[str]:
    """Every registry key the value can name, in match order (a bare slug may name projects/<slug> and infra/<slug>)."""
    reg = _registry(name)
    if name == "projects" and _prj.is_id(value):                 # a project's permanent id names its page (phase A: stored data still carries the key)
        k = _prj.id_to_key(value, reg)
        return [k] if k and k in reg else []
    return [k for k in dict.fromkeys(pat.format(value=value) for pat in _cfg.CFG["registries"][name].get("match", ["{value}"])) if k in reg]


def _registry_hit(name: str, value: str) -> tuple[str | None, dict[str, Any]]:
    hits = _registry_hits(name, value)
    return (hits[0], _registry(name)[hits[0]]) if hits else (None, {})


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


def _project_subject_prefix(project: str) -> str:
    """The scope prefix a subject for `project` takes: "[<scope>] " of the project's scope when the instance has that prefix, else [subject] fallback_prefix when it is one of the prefixes;
    "" when the project does not name one record, the record has no scope, or neither applies (the subject is then refused for its missing prefix, as before)."""
    try:
        recs = _prj.refs(project, _registry("projects"))
    except Exception:  # noqa: BLE001 — a project record that cannot be read: the gate refuses the subject as it always did
        return ""
    if len(recs) != 1:
        return ""
    prefixes = list(_cfg.CFG["subject"]["prefixes"])
    fallback = str(_cfg.get("subject", "fallback_prefix") or "")
    scope = str(recs[0].get("scope") or "")
    return next((p for p in (f"[{scope}] " if scope else "", fallback) if p and p in prefixes), "")


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


def _gate_bare_urls(fields: dict[str, str], stored: dict[str, Any] | None = None) -> None:
    """A session's write through the create and update tools (_SESSION_NEXT) may not put a bare http(s) URL in description, next or ask: the page does not always draw one as a
    link, so a reader sees plain text. A URL inside `[words](url)`, a code span or a fenced block is fine. Judges the text written in this call, `fields` by name, and of that only a URL
    the stored text of the field (`stored`, an update's) does not already hold, so an update that sets a field again with an old bare URL in it is not refused for that. Scripts and the
    server's own writes are not judged. How a page draws a bare URL is not changed here."""
    if not getattr(_SESSION_NEXT, "on", False):
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


def _gate_next(next_: str, has_ask: bool = False) -> None:
    """a `next` line over [metadata.next] line_max (200; 0 = off) characters is refused, where it used to be noted. Checks only the text written
    in this call. A link counts by its text and a naked URL not at all, as in a description. Not judged: a `<owner>: `command`` line (the
    whole command in one backtick span; any other line of his is prose and counts), and next's first non-blank line when it is an ask line and
    the call passes no `ask` (a client without the ask parameter writes the ask there; the server lifts it). Hashes, test counts and past
    tense stay notes (_report_note). (a session's write through the create and update tools only, _SESSION_NEXT): a line that opens with no `<actor>:` is refused, naming the line and the fix; a sub-line under a named step is fine."""
    if getattr(_SESSION_NEXT, "on", False) and (bad := _nr.unnamed(next_, skip_first=None if has_ask else (lambda ln: _rmod.parse_ask(ln) is not None))):
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


def _gate_metadata(meta: dict[str, Any], *, creating: bool) -> None:
    rules = _cfg.CFG["metadata"]
    for key, rule in rules.items():
        val = meta.get(key)
        if rule.get("required") and creating and val in (None, ""):
            raise ToolError(f"Refused: metadata.{key} is required")
        if val in (None, "", []):
            continue
        if key == "needs":                   # a list of the enum's kinds and session names, gated by _gate_needs
            if not isinstance(val, list):
                raise ToolError("Refused: metadata.needs is a list")
            continue
        if "enum" in rule and val not in rule["enum"]:
            raise ToolError(f"Refused: metadata.{key} must be one of {rule['enum']} — got {val!r}")
        if rule.get("format") == "YYYY-MM-DD":
            try:
                dt.date.fromisoformat(str(val))
            except ValueError:
                raise ToolError(f"Refused: metadata.{key} must be YYYY-MM-DD ({_cfg.tz_abbr()}) — got {val!r}")
        if rule.get("type") == "list" and not isinstance(val, list):
            raise ToolError(f"Refused: metadata.{key} must be a list")
        if rule.get("type") == "string" and not isinstance(val, str):
            raise ToolError(f"Refused: metadata.{key} must be a string")
        if "registry" in rule:
            hit, _ = _registry_hit(rule["registry"], str(val))
            if not hit and rule["registry"] == "projects":
                # The registry is rebuilt on publish, i.e. after a successful write — so a page created minutes ago is
                # missing exactly when the first item for it arrives (a first item for a new page can arrive before
                # the pages checkout has it). Rebuild once, then re-check.
                try:
                    _pages.cmd_registry(quiet=True)
                except Exception:
                    pass
                _roles_sync_safe()                  # a new hub's agents are front at once, not at the next publish
                hit, _ = _registry_hit(rule["registry"], str(val))
            if not hit and rule["registry"] == "projects":
                # Fail open for a second brain ([[brains]]): a key it holds whose copy is missing or stale cannot be looked up, so it is
                # taken as written (the full key) and a warning naming the brain is logged; the board never blocks on that brain.
                want = _pages.norm(str(val))
                if _brains.skip(want, "create's page check accepts its keys unchecked") and not _prj.is_id(str(val)):
                    print(f"create: metadata.{key} = {want} is in second brain {_brains.for_key(want).name!r}, whose copy cannot be read: accepted unchecked",
                          file=sys.stderr, flush=True)
                    meta[key] = want
                    continue
            if not hit and rule["registry"] == "projects":
                # The record says the project has no page: there is no page to name, so the refusal below (which is for a page that does not exist) does not apply. The item stores
                # the project's permanent id. A project whose record points at a page that does not resolve is not this case: it is still refused.
                nopage = _prj.pageless(str(val))
                if nopage:
                    meta[key] = nopage["id"]
                    continue
            if not hit:
                reg = _registry(rule["registry"])
                known = sorted(k.split("/", 1)[1] for k in reg if k.startswith(_cfg.page_dirs()[0] + "/"))
                infra = sorted(k for k in reg if any(k.startswith(d + "/") for d in _cfg.page_dirs()[1:]))
                raise ToolError(
                    f"Refused: metadata.{key} = {val!r} names no page. Every board item belongs to a project page "
                    f"(gbrain projects/<slug>, or infra/<slug> for a machine/service item, written as the bare slug or the full key); "
                    f"create the page first, then the item. Existing project slugs: {', '.join(known)}. Infra pages: {', '.join(infra)}"
                    + (f". Where it looked: {where}." if (where := _brains.looked_in(_pages.norm(str(val)))) else "")
                )
            if rule["registry"] == "projects":
                hits = _registry_hits(rule["registry"], str(val))
                if len(hits) > 1:
                    raise ToolError(f"Refused: metadata.{key} = {val!r} is ambiguous — it names {' and '.join(hits)}; write the full key")
                meta[key] = hit          # the item stores the page's full key (projects/<slug> or infra/<slug>) — the board and the hooks never guess
