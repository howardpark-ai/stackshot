"""bullet_text.py — the pure half of the board's bullet form: how long a line reads, whether a description keeps the form, and how a script's or a model's
text is made into short `- ` bullets.

Used by server.py's description and next gates, by the cold call's close (cold_call.validate), by the question route (server._question_text) and by the re-bullet pass
(rebullet.verdict), so every one of them counts, judges and clips alike. Stdlib only; no state.

  visible_len   a line's length as it reads: a Markdown link counts as its words (its destination, in any common form, is cut out) and a naked URL not at all
  bare_urls     the http(s) URLs a text writes outside a Markdown link, a code span and a fenced block (the ones the page may not draw as a link)
  judge         the one judgement of a description's form: at most max_lines lines, every line a `- ` bullet of at most line_max visible characters, with two exemptions
                (a `>` quote line is not held to the marker, a fenced block is held to nothing but the line count)
  first_bullet  the text of a description's first `- ` bullet (a fenced block and a `>` quote line are not bullets), None when it has none
  goal_of       the sentence a description's first bullet gives after its `Goal:` label (the label is case-sensitive and sits right after the dash), None when the first bullet does not open that way
  clip_bullet   one bullet shortened to `line_max` visible characters at a word boundary that lies outside any link and any naked URL, then an ellipsis
  bullets       a text as `- ` bullets, split on lines only, each clipped, at most `max_lines` of them (the last says how many more there were)

Every pattern here is linear in the line's length (no nested quantifier over the same characters, the open-ended parts are bounded, and whitespace that two neighbours could
match is matched possessively), so a 40,000-character line of brackets, angle marks or spaces costs milliseconds, not seconds."""
from __future__ import annotations

import bisect
import re

# A Markdown link: `[words](destination)`, the destination as `(url)`, `(url "title")`, `(url 'title')`, `(url (title))`, `(<a destination with spaces>)`, or a url that holds
# one level of balanced parentheses. The words take no bracket (so a run of `[` is one step each); the angle destination and the title are bounded.
RX_MD_LINK = re.compile(r"\[([^\[\]]*+)\]\(\s*+(?>(?:<[^>\n]{0,500}>|(?:[^()\s]|\([^()\s]*+\))*+))(?:\s++(?:\"[^\"]{0,200}+\"|'[^']{0,200}+'|\([^)]{0,200}+\)))?+\s*+\)")
RX_NAKED_URL = re.compile(r"(?<!\]\()https?://[^\s)\]>]+")
RX_BULLET = re.compile(r"^\s*-[ \t]+\S")                       # a bullet: a dash, spaces or a tab, then something
_RX_MARKER = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])[ \t]+")      # a list marker taken off a script's or a model's line: a bullet, a star, a dot, `1.` or `12)`
_RX_FENCE = re.compile(r"^[ \t]*(?:```|~~~)")
_RX_FENCE_END = re.compile(r"^[ \t]*(?:```|~~~)[ \t]*$")
_RX_QUOTE = re.compile(r"^[ \t]*>")


def visible_len(line: str) -> int:
    """A line's length as it reads: a link counts as its words, a naked URL as nothing, the ends trimmed."""
    return len(RX_NAKED_URL.sub("", RX_MD_LINK.sub(r"\1", line)).strip())


_RX_CODE_SPAN = re.compile(r"`[^`\n]*+`")
_RX_ANY_URL = re.compile(r"https?://[^\s<>)\]]++", re.I)


def bare_urls(text: str) -> list[str]:
    """The http(s) URLs `text` writes outside a Markdown link `[words](url)` (an image's too), a `code span` and a closed fenced block, in order, a closing . , ; : ! ? or quote left off.
    A URL in a code span or a fence is literal text on purpose; a `<url>` is not a link in this markdown and is found like a naked one."""
    keep, open_at = str(text or "").splitlines(), -1
    for k, ln in enumerate(list(keep)):
        if open_at < 0:
            if _RX_FENCE.match(ln):
                open_at = k
        elif _RX_FENCE_END.match(ln):
            keep[open_at:k + 1] = [""] * (k + 1 - open_at)       # a fence still open at the end is no fence: its lines stay judged
            open_at = -1
    out = []
    for ln in keep:
        for m in _RX_ANY_URL.finditer(RX_MD_LINK.sub(" ", _RX_CODE_SPAN.sub(" ", ln))):
            out.append(m.group(0).rstrip(".,;:!?'\"*_"))
    return out


def judge(text: str, max_lines: int, line_max: int) -> tuple[str, str, int] | None:
    """The form of a description, judged once for everyone (the write gate, the re-bullet pass): None when it keeps the form, else ("lines", "", n) when it has n non-blank
    lines (more than max_lines), ("marker", line, 0) for the first line that is not a `- ` bullet, or ("long", line, n) for the first line that reads n characters (over line_max).
    Every non-blank line counts toward max_lines, a fence line and a `>` quote line too. A `>` quote line (his words) is exempt from the marker but not from the length; a fenced
    block, fence lines included, from both. An indented line that is not a bullet is prose, like any other. An unclosed fence is no fence. line_max 0 judges no length."""
    lines = str(text or "").splitlines()
    live = [(k, ln) for k, ln in enumerate(lines) if ln.strip()]
    if len(live) > max_lines:                  # the count first: nothing else is worth scanning for a text that is refused anyway
        return ("lines", "", len(live))
    fenced: set[int] = set()
    open_at = -1                               # one pass: the line a fence opened at, -1 when none is open
    for k, ln in enumerate(lines):
        if open_at < 0:
            if _RX_FENCE.match(ln):
                open_at = k
        elif _RX_FENCE_END.match(ln):
            fenced.update(range(open_at, k + 1))
            open_at = -1                       # a fence still open at the end is no fence: its lines stay judged
    for k, ln in live:
        if k in fenced:
            continue
        if not _RX_QUOTE.match(ln) and not RX_BULLET.match(ln):
            return ("marker", ln, 0)
        if line_max and (n := visible_len(ln)) > line_max:
            return ("long", ln, n)
    return None


def _spans(line: str) -> list[tuple[int, int]]:
    """The stretches a cut must not fall inside: every link, and every naked URL outside a link (found by a search among the links' starts)."""
    links = [m.span() for m in RX_MD_LINK.finditer(line)]
    starts = [a for a, _ in links]
    out = list(links)
    for m in RX_NAKED_URL.finditer(line):
        k = bisect.bisect_right(starts, m.start()) - 1
        if not (k >= 0 and links[k][0] <= m.start() < links[k][1]):
            out.append(m.span())
    return sorted(out)


def clip_bullet(line: str, line_max: int) -> str:
    """`line` itself when it reads within `line_max` characters; else its start, cut at the end of a word that lies outside any link and any naked URL (a link stays whole or
    goes whole), with " …" after it, the finished string reading within `line_max`. A line whose first word is longer than the room is cut inside that word (never inside a link
    or a URL). A line that opens with a link too long for the room keeps the link, its words clipped; with no room for even that it becomes "- …"."""
    line = line.rstrip()
    if visible_len(line) <= line_max:
        return line
    spans = _spans(line)
    starts = [a for a, _ in spans]

    def inside(i: int) -> bool:           # strictly inside a link or a URL
        k = bisect.bisect_left(starts, i) - 1
        return k >= 0 and spans[k][0] < i < spans[k][1]

    def fits(cut: int) -> bool:           # the finished string is what is judged: a URL cut out at the end, or a space before the ellipsis, can change the count
        return visible_len(line[:cut].rstrip() + " …") <= line_max

    floor = 2 if line.startswith("- ") else 0           # a bullet is more than its marker
    # the cut points, widest first: the end of a word, then any character boundary outside a span
    words = [i for i in range(1, len(line)) if not line[i - 1].isspace() and line[i].isspace() and not inside(i)]
    chars = [i for i in range(1, len(line)) if not inside(i)]
    for cuts in (words, chars):
        lo, hi, best = 0, len(cuts), -1
        while lo < hi:                                    # the start reads longer as the cut moves right: find about where it stops fitting …
            mid = (lo + hi) // 2
            if fits(cuts[mid]):
                best, lo = mid, mid + 1
            else:
                hi = mid
        while best >= 0 and not fits(cuts[best]):         # … and step left until the finished string really fits (a cut next to a URL can be a few off)
            best -= 1
        if best >= 0:
            head = line[: cuts[best]].rstrip()
            if len(head) > floor and head.strip(" -") != "":
                return head + " …"
    m = RX_MD_LINK.search(line)
    if m:                                                 # a lone long link: keep it, its words clipped
        room = line_max - visible_len(line[: m.start()] + "x") - 1       # the characters left for the words, less the ellipsis
        dest = m.group(0)[len(m.group(1)) + 2:]                          # "(url)" with its brackets
        words = m.group(1)
        while room >= 1 and words.strip():
            cand = f"{line[: m.start()]}[{words[:room].rstrip()}…]{dest}"
            if visible_len(cand) <= line_max:      # the finished string is what is judged: a naked URL touching the link can read over
                return cand
            room -= 1
    return ("- " if floor else "") + "…"


_RX_FIRST_BULLET = re.compile(r"^\s*-[ \t]+(\S.*)$")
GOAL_LABEL = "Goal:"


def first_bullet(text: str) -> str | None:
    """The first `- ` bullet of a description, without its dash, the ends trimmed; None when there is none. A line that is not a bullet (a `>` quote, prose) before it is passed over, and so is a fenced block."""
    fenced = False
    for ln in str(text or "").splitlines():
        if _RX_FENCE.match(ln):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _RX_FIRST_BULLET.match(ln)
        if m:
            return m.group(1).strip()
    return None


def goal_of(text: str) -> str | None:
    """The goal a description states: what follows `Goal:` in its first bullet when that bullet opens with it (case-sensitive, the label right after the dash) and says something after it; else None."""
    b = first_bullet(text)
    if b is None or not b.startswith(GOAL_LABEL):
        return None
    rest = b[len(GOAL_LABEL):].strip()
    return rest or None


def clean_lines(text: str) -> list[str]:
    """The lines of `text` with a leading `-`, `*`, `•` or `1.` / `12)` marker taken off, the ends trimmed, and every line dropped that has no letter or digit in it. Newlines are
    the only split: a sentence end is not one (numbered lists, "e.g.", "Dr." and link words would break)."""
    out = []
    for raw in str(text or "").splitlines():
        t = _RX_MARKER.sub("", raw, count=1).strip()
        if t and any(c.isalnum() for c in t):
            out.append(t)
    return out


def bullets(text: str, max_lines: int = 8, line_max: int = 120) -> str:
    """`text` as `- ` bullets, one per line, each clipped to `line_max` (clip_bullet). When more than `max_lines` remain, the last of the `max_lines` says "- …and N more", N being
    the lines it stands for (the ones past the first max_lines - 1), so nothing is dropped silently and the result still has at most `max_lines` lines."""
    max_lines = max(int(max_lines), 1)
    lines = ["- " + t for t in clean_lines(text)]
    if len(lines) > max_lines:
        more = len(lines) - (max_lines - 1)
        lines = lines[: max_lines - 1] + [f"- …and {more} more"]
    return "\n".join(clip_bullet(ln, line_max) for ln in lines)
