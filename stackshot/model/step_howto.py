"""step_howto.py — how to do the owner's step (where to click, what to attach) stands under the step, never only in the description.

THE SHAPE. metadata.step stays the one-line summary every reader of the step reads: the server's checklist line `<owner>: <step>` (owner_steps.py), the tab title, the notices, the wait checks. How to do
it is kept beside it, in metadata.step_howto = {"step": <the step it stands under, on one line>, "text": <`- ` lines, with the lines indented under them>}. The home row and the item page's Your step block
draw it under the step (web/ui/render.py), get shows it under `step:`, and it never enters next: no line of the checklist, no adoption of a session's `<owner>:` line and no wait check reads it.
It follows its step (follow, run on every save): when the step ends (step="none", a state change, a close, his Done) or a write other than a session's update changes the step, the lines go back to
the end of the description, so no line is lost.

WHAT A SESSION'S WRITE LEAVES (plan, service/update.py, for a write that leaves the item in his your-step; never a refusal):
  1. step= sent as a lead line with `- ` lines under it (split_step): those lines are the how-to, and the lead is the step. A numbered or fenced step is its own how-to and keeps none beside it.
     A how-to bullet of the description that the step says (every line of it, the list marker and the spacing aside) leaves the description; any other stays where it is.
  2. else a description the write changes that holds how-to bullets: those bullets are the how-to, and they leave the description.
  3. else, while the item keeps no how-to, the how-to bullets of the description move under the step.
  4. else the how-to stays as it is: a reworded, resent or split one-line step keeps it.
  What a write replaces is quoted once in the reply (call_log kind step-howto), and the dropped-lines note never names a line that went under the step.

A HOW-TO BULLET (detected) is a top-level `- ` bullet of the description with the lines indented under it, outside a fenced block and with none under it, whose first line
  - is a click path: two or more arrows (U+2192 or U+203A) outside quotes and code spans, the item after each arrow not starting lowercase, or
  - opens with the imperative attach or upload, with a link in the bullet,
  and is none of: the Goal bullet, a line that opens with a one-word label (`Problem:`, a name), a date or a warning word, a line with a negation, a word of a past event or a verb that says what
  something is or does (shows, removes, needs). Words inside quotes, code spans and link addresses do not count. In doubt it is none.
It moves (movable) only with no command in it, within the step's limits (states.STEP_LINES lines and STEP_MAX characters with the step, STEP_LINE_MAX a line), and never as the last text of the description.
The filing pass reports exactly what rule 3 would move (pending, audit_checks.check_step_howto). A long how-to bullet is wrapped, never split into siblings (keeps_whole, field_gates.fix_long_bullets),
so it moves whole. Pure functions of texts and an item's metadata."""
from __future__ import annotations

import re
from typing import Any

from stackshot.model import states as _states
from stackshot.model import step_commands as _sc

KEY = "step_howto"
ARROW_RX = re.compile("[→›]")      # a click path's arrows: the arrow and the breadcrumb one
_GOAL_RX = re.compile(r"^-[ \t]+\**[ \t]*goal[ \t]*\**[ \t]*:", re.I)
_TOP_RX = re.compile(r"^[-*•][ \t]+(\S.*)$")                    # a top-level list line of a step sent with its how-to
_SUB_RX = re.compile(r"^([ \t]+)[-*•][ \t]+(\S.*)$")             # …and a list line indented under one
_MARK_RX = re.compile(r"^[ \t]*(?:[-*+•]|\d{1,3}[.)])[ \t]+")    # the marker a line opens with, for the key
_QUOTED_RX = re.compile("`[^`\n]*`|\"[^\"\n]*\"|“[^”\n]*”|‘[^’\n]*’|(?<![\\w])'[^'\n]*'(?![\\w])")
_LABEL_RX = re.compile(r"^\**[^\s:*]+\**[ \t]*:(?:\s|$)")             # `Problem:`, `Oliver:`, `**Note**:` (`In the console:` is a place, not a label)
_DATE_RX = re.compile(r"^(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}(?!\d)|\d{1,2}:\d{2}(?!\d)|(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)(?![\w-])"
                      r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?[ \t]+\d|(?:yesterday|today|earlier|last|on[ \t]+\d)(?![\w-]))", re.I)
_PAST_RX = re.compile(r"(?<![\w-])(?:was|were|had|did|got|went|tried|failed|broke|saw|showed|happened|clicked|worked|crashed|stopped|said|told|reported|noticed|seemed|been|ago|yesterday|previously"
                      r"|earlier|already)(?![\w-])", re.I)
_NOT_RX = re.compile(r"(?<![\w-])(?:not|cannot|never|avoid|nothing|no[ \t]+longer)(?![\w-])|n['’]t(?![\w-])", re.I)
_SAYS_RX = re.compile(r"(?<![\w-])(?:is|are|has|have|shows|displays|returns|gives|says|reads|lists|fails|errors|hangs|loads|crashes|breaks|throws|stays|keeps|lacks|misses|contains|needs|deletes"
                      r"|removes|wipes|erases|resets|loses|destroys|overwrites|revokes|drops|appears|leads|goes|sends|takes|works|means|happens|causes)(?![\w-])", re.I)      # what something is or does: a fact, not an action
_WARN_RX = re.compile(r"^(?:\u26a0|(?:warning|caution|careful|beware|danger|important|note|nb|fyi|tip|heads[ -]up)(?![\w-]))", re.I)
_DO_RX = re.compile(r"^(?:attach|upload)(?![\w-])(?![ \t]+(?:is|was|are|were|has|had|does|did|will|would|can|could|should|must|may|might|fails|failed|works|worked|stays|limit|limits|size|button)(?![\w-]))", re.I)
_LINK_RX = re.compile(r"\]\([^)\s]+\)|https?://\S+")
_TARGET_RX = re.compile(r"\]\([^)\s]*\)")
_URL_RX = re.compile(r"https?://\S+")


# ---------------------------------------------------------------------------------------------------------------- the detector
def _plain(text: str) -> str:
    """The text with a link's address left out and each quoted or code span written as Q: no word of an address or inside quotes counts, and a quoted label still heads a click path."""
    return _QUOTED_RX.sub("Q", _URL_RX.sub("U", _TARGET_RX.sub("]", text)))


def _top_is_howto(top: str, block: str = "") -> bool:
    """Is `top`, the first line of a top-level `- ` bullet (`block`: the bullet with its lines, for the link of the attach rule), how to do a step? In doubt False."""
    if not top.startswith("- ") or _GOAL_RX.match(top):
        return False
    plain = _plain(top[2:].strip())
    bare = plain.lstrip("*_ \t")
    if _LABEL_RX.match(plain) or _DATE_RX.match(bare) or _WARN_RX.match(bare) or _PAST_RX.search(plain) or _NOT_RX.search(plain) or _SAYS_RX.search(plain):
        return False
    segs = ARROW_RX.split(plain)
    if len(segs) >= 3 and all((h := s.strip().lstrip("*_[(")) and not h[0].islower() for s in segs[1:]):
        return True
    return bool(_DO_RX.match(bare) and _LINK_RX.search(block or top))


def keeps_whole(line: str) -> bool:
    """A description line that is the first line of a how-to bullet: a long one is wrapped onto an indented line, never split into sibling bullets, so the bullet moves whole (bullet_text._split_long)."""
    return _top_is_howto(str(line).rstrip())


def _blocks(lines: list[str]) -> list[tuple[int, int]]:
    """(first line, the line after the last) of each top-level `- ` bullet of a description with the lines indented under it, outside fenced blocks; a bullet with a fenced block under it is left out."""
    out: list[list[Any]] = []
    cur: "list[Any] | None" = None
    fence = ""
    for i, ln in enumerate(lines):
        s, under = ln.strip(), ln[:1] in (" ", "\t")
        if fence:
            if s and set(s) == {fence[0]} and len(s) >= len(fence):
                fence = ""
            continue
        if m := _sc.FENCE_RX.match(ln):
            fence = m.group(1)
            if cur is not None and under:
                cur[2] = False
            cur = None
        elif ln.startswith("- "):
            cur = [i, i + 1, True]
            out.append(cur)
        elif s and under and cur is not None:
            cur[1] = i + 1
        elif s:
            cur = None
    return [(a, b) for a, b, whole in out if whole]


def _detected(block: list[str]) -> bool:
    return bool(block) and _top_is_howto(block[0], "\n".join(block))


def howto_bullets(description: Any) -> list[str]:
    """The how-to bullets a description holds, each with its lines, as written (the detector alone: what may move is `pending`)."""
    lines = _sc.lines_of(description)
    return ["\n".join(b) for b in (_rows(lines, a, z) for a, z in _blocks(lines)) if _detected(b)]


def _rows(lines: list[str], a: int, z: int) -> list[str]:
    return [ln.rstrip() for ln in lines[a:z] if ln.strip()]


def _key(line: str) -> str:
    """A line as the comparisons read it: its list marker and its spacing aside."""
    return " ".join(_MARK_RX.sub("", line, count=1).split())


def _has_command(text: str) -> bool:
    return bool(_sc.step_carries_command(text) or _sc.commands_of(text) or _sc.pane_commands(text))


def _fits(step: str, lines: list[str]) -> bool:
    """May `lines` stand under `step`: STEP_LINES lines and STEP_MAX characters with the step, STEP_LINE_MAX on a line."""
    rows = [*[ln for ln in _sc.lines_of(step) if ln.strip()], *lines]
    return len(rows) <= _states.STEP_LINES and len("\n".join(rows)) <= _states.STEP_MAX and all(len(ln) <= _states.STEP_LINE_MAX for ln in lines)


def _left(lines: list[str], gone: set[int]) -> bool:
    return any(ln.strip() for i, ln in enumerate(lines) if i not in gone)


def _take(lines: list[str], found: list[tuple[int, int, list[str]]], step: str, have: list[str] | None = None) -> list[tuple[int, int, list[str]]]:
    """The detected bullets that move under `step` (beside the lines `have`), in order: no command in one, within the step's limits, and never the last text of the description."""
    got: list[tuple[int, int, list[str]]] = []
    rows, gone = list(have or []), set()
    for a, z, blk in found:
        out = gone | set(range(a, z))
        if _has_command("\n".join(blk)) or not _fits(step, [*rows, *blk]) or not _left(lines, out):
            continue
        got.append((a, z, blk))
        rows, gone = rows + blk, out
    return got


# ---------------------------------------------------------------------------------------------------------------- the stored how-to
def text_of(meta: dict[str, Any]) -> str:
    """The how-to the item keeps ("" for none), whichever step it was stored with."""
    h = (meta or {}).get(KEY)
    return str(h.get("text") or "").strip("\n") if isinstance(h, dict) else ""


def drawn(meta: dict[str, Any]) -> str:
    """The how-to drawn under the step: the one kept for the step the item holds ("" when the step is another or there is none)."""
    h = (meta or {}).get(KEY)
    step = _states.clean((meta or {}).get("step"))
    return text_of(meta) if isinstance(h, dict) and step and _states.clean(h.get("step")) == step else ""


def store(meta: dict[str, Any], text: str) -> None:
    """Keep `text` as the how-to of the step `meta` holds (none: the field goes)."""
    if str(text or "").strip() and _states.clean(meta.get("step")):
        meta[KEY] = {"step": _states.clean(meta.get("step")), "text": str(text).strip("\n")}
    else:
        meta.pop(KEY, None)


def follow(item: dict[str, Any]) -> int:
    """The how-to follows its step (writes.save, every save): kept while the item is open in your-step with the step it was stored with; else its lines go back to the end of the description and the
    field goes. → how many lines went back (0 when none)."""
    meta = item.get("metadata")
    if not isinstance(meta, dict) or KEY not in meta:
        return 0
    text = text_of(meta)
    if text and item.get("status") == "open" and meta.get("state") == "your-step" and drawn(meta):
        return 0
    meta.pop(KEY, None)
    if not text:
        return 0
    desc = str(item.get("description") or "").rstrip("\n")
    item["description"] = f"{desc}\n{text}" if desc.strip() else text
    return len([ln for ln in text.split("\n") if ln.strip()])


def lines_note(text: str) -> str:
    """`step:`'s lines under it, as get shows them and step= takes them back ("" for none)."""
    return f"\n{text}" if str(text or "").strip() else ""


# ---------------------------------------------------------------------------------------------------------------- a write
def split_step(step: Any) -> tuple[Any, "str | None"]:
    """A step a session sends → (the step to store, its own how-to lines). A lead line with `- ` lines under it (and lines indented under those) is the lead and the lines, each marker written `- `
    and a wrapped line joined to the line it continues; a numbered or fenced step is its own how-to (""). Any other step, and lines that hold a command, point elsewhere or break the step's limits,
    come back as sent with None: the step is judged as ever (a command in it is refused, as before)."""
    t = str(step or "").replace("\r\n", "\n").replace("\r", "\n")
    if _sc.structured(t):
        return step, ""
    rows = [ln.rstrip() for ln in t.split("\n") if ln.strip()]
    if len(rows) < 2 or _TOP_RX.match(rows[0]) or rows[0][:1] in (" ", "\t") or not _TOP_RX.match(rows[1]):
        return step, None
    out: list[str] = []
    for ln in rows[1:]:
        if m := _TOP_RX.match(ln):
            out.append("- " + " ".join(m.group(1).split()))
        elif m := _SUB_RX.match(ln):
            out.append(m.group(1).expandtabs(4) + "- " + " ".join(m.group(2).split()))
        elif ln[:1] in (" ", "\t"):
            out[-1] += " " + " ".join(ln.split())
        else:
            return step, None
    lead = " ".join(rows[0].split())
    text = "\n".join(out)
    if _has_command(text) or _sc.points_elsewhere(text) or not _fits(lead, out):
        return step, None
    return lead, text


def _tops(text: str) -> list[list[str]]:
    lines = _sc.lines_of(text)
    return [_rows(lines, a, z) for a, z in _blocks(lines)]


def _quote(blocks: list[list[str]], n: int = 3) -> str:
    """The first line of each of the first `n` bullets, quoted and clipped, then how many more."""
    def one(b: list[str]) -> str:
        t = " ".join(b[0][2:].split())
        return f"\"{t if len(t) <= 70 else t[:69].rstrip() + '…'}\""
    return ", ".join(one(b) for b in blocks[:n]) + (f" and {len(blocks) - n} more" if len(blocks) > n else "")


def _n(k: int, word: str) -> str:
    return f"{k} {word}{'' if k == 1 else 's'}"


def plan(step: Any, description: Any, sent: bool, howto: Any, own: "str | None", take: bool = True, step_was: Any = "") -> tuple[str, str, str]:
    """What a session's write that leaves the item in his your-step keeps under the step (rules 1 to 4 above) → (the how-to, the description, the reply's sentence: "" when there is nothing to say).
    `step` is the step as the write stores it, `description` the description as it leaves it and `sent` whether the write changes it (the stored text sent back is no change), `howto` the how-to kept
    before, `own` the step's own lines (split_step: "" for a numbered or fenced step, None when it brings none), `take` False leaves the description as it is (the item is not his to move), `step_was` the
    step before (rule 4 says when a changed step keeps the lines)."""
    desc, old, step_t = str(description or ""), str(howto or "").strip("\n"), _states.step_text(step)
    lines = _sc.lines_of(desc)
    found = [(a, z, b) for a, z in _blocks(lines) if _detected(b := _rows(lines, a, z))] if take else []
    notes: list[str] = []
    if own is not None:
        new = own.strip("\n")
        said = {_key(ln) for ln in [*_sc.lines_of(step_t), *_sc.lines_of(new)] if ln.strip()}
        gone: list[tuple[int, int, list[str]]] = []
        cut: set[int] = set()
        for a, z, blk in found:
            if all(_key(ln) in said for ln in blk) and _left(lines, cut | set(range(a, z))):
                gone.append((a, z, blk))
                cut |= set(range(a, z))
        stay = [b for a, z, b in found if (a, z, b) not in gone]
        if gone:
            notes.append(f"{_n(len(gone), 'how-to bullet')} of the description that the step says {'was' if len(gone) == 1 else 'were'} taken out of it")
        if stay:
            notes.append(f"{_n(len(stay), 'how-to bullet')} of the description ({_quote(stay)}) {'stays' if len(stay) == 1 else 'stay'} there, since the step brings its own lines")
    elif sent and (gone := _take(lines, found, step_t)):
        new = "\n".join(ln for _a, _z, b in gone for ln in b)
        same = [tuple(map(_key, b)) for b in _tops(new)] == [tuple(map(_key, b)) for b in _tops(old)]
        notes.append(f"the description's {_n(len(gone), 'how-to bullet')} ({_quote([b for _a, _z, b in gone])}) "
                     + ("stand under the step already, so they were taken out of the description again" if same else "are the how-to under the step now, taken out of the description"))
        said = set()
    elif not old and (gone := _take(lines, found, step_t)):
        new = "\n".join(ln for _a, _z, b in gone for ln in b)
        notes.append(f"{_n(len(gone), 'how-to bullet')} ({_quote([b for _a, _z, b in gone])}) moved from the description to under the step, where the home row and Your step show "
                     f"{'it' if len(gone) == 1 else 'them'}; {'it goes' if len(gone) == 1 else 'they go'} back to the description when the step ends")
        said = set()
    else:
        new, gone, said = old, [], set()
        if old and _states.clean(step_was) and _states.clean(step) != _states.clean(step_was):
            n = len(_tops(old))
            notes.append(f"the {_n(n, 'how-to bullet')} under the step ({_quote(_tops(old))}) {'stays' if n == 1 else 'stay'} with the new step; to change them, send step= with its own `- ` lines")
    kept = {tuple(map(_key, b)) for b in _tops(new)}
    replaced = [b for b in _tops(old) if tuple(map(_key, b)) not in kept and not all(_key(ln) in said for ln in b)]
    if replaced:
        notes.append(f"the how-to under the step was replaced; the {_n(len(replaced), 'bullet')} it had, gone now: {_quote(replaced)}")
    cut = {i for a, z, _b in gone for i in range(a, z)}
    out_desc = "\n".join(ln for i, ln in enumerate(lines) if i not in cut).strip("\n") if cut else desc
    return new, out_desc, "; ".join(notes)


def pending(item: dict[str, Any]) -> list[str]:
    """The how-to bullets rule 3 moves on the next session's write of an item that is his your-step: while it keeps no how-to, the detected bullets of the description that may move, each with its lines.
    [] for any other item. The filing pass reports exactly these (audit_checks.check_step_howto), so it never reports a bullet the move would not take."""
    meta = item.get("metadata") or {}
    if item.get("status") != "open" or meta.get("state") != "your-step" or not _states.clean(meta.get("step")) or text_of(meta):
        return []
    lines = _sc.lines_of(item.get("description"))
    found = [(a, z, b) for a, z in _blocks(lines) if _detected(b := _rows(lines, a, z))]
    return ["\n".join(b) for _a, _z, b in _take(lines, found, _states.step_text(meta.get("step")))]
