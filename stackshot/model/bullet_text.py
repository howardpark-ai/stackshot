"""bullet_text.py — the pure half of the board's bullet form: how long a line reads, whether a description keeps the form, and how a script's or a model's
text is made into short `- ` bullets.

Used by server.py's description and next gates, by the cold call's close (cold_call.validate), by the question route (service/question.py `_question_text`) and by the re-bullet pass
(rebullet.verdict), so every one of them counts, judges and clips alike. Stdlib only; no state.

  visible_len   a line's length as it reads: a Markdown link counts as its words (its destination, in any common form, is cut out) and a naked URL not at all
  bare_urls     the http(s) URLs a text writes outside a Markdown link, a code span and a fenced block (the ones the page may not draw as a link)
  judge         the one judgement of a description's form: at most max_lines lines, every line a `- ` bullet of at most line_max visible characters, with two exemptions
                (a `>` quote line is not held to the marker, a fenced block is held to nothing but the line count)
  first_bullet  the text of a description's first `- ` bullet (a fenced block and a `>` quote line are not bullets), None when it has none
  goal_of       the sentence a description's first bullet gives after its `Goal:` label (the label is case-sensitive and sits right after the dash), None when the first bullet does not open that way
  stated_goal   the goal a stored description gives however it wrote it: `goal_of`, the same once the label in another form is put right (relabel_goal), else the first bullet
  goal_words    the words of a goal sentence, for asking whether a rewrite changed them: case left out, spacing and punctuation only between words, a link as its words
  split_long    a description's long bullets cut at a sentence end (first tier), else at a comma, colon, spaced dash or opening parenthesis (second tier: `split_long_ex` also says how many needed it)
  clip_bullet   one bullet shortened to `line_max` visible characters at a word boundary that lies outside any link and any naked URL, then an ellipsis
  bullets       a text as `- ` bullets, split on lines only, each clipped, at most `max_lines` of them (the last says how many more there were)
  _clip_line    free text as one line of a notice: whitespace collapsed, cut at a word before a limit with an ellipsis
  cut_words     one line cut at the last whole word that fits with " …" after it (None when no whole word fits): the cut of a subject or a status line over its limit
  link_bare_urls  a text with each bare http(s) URL written as a link to itself, `[url](url)` (the address ends at its last URL character; none inside an angle autolink, a link, a reference definition, an attribute or code, nor one `skip` holds)

Every pattern here is linear in the line's length (no nested quantifier over the same characters, the open-ended parts are bounded, and whitespace that two neighbours could
match is matched possessively), so a 40,000-character line of brackets, angle marks or spaces costs milliseconds, not seconds."""
from __future__ import annotations

import bisect
import re
import unicodedata
from typing import Any

# A Markdown link: `[words](destination)`, the destination as `(url)`, `(url "title")`, `(url 'title')`, `(url (title))`, `(<a destination with spaces>)`, or a url that holds
# one level of balanced parentheses. The words take no bracket (so a run of `[` is one step each); the angle destination and the title are bounded.
RX_MD_LINK = re.compile(r"\[([^\[\]]*+)\]\(\s*+(?>(?:<[^>\n]{0,500}>|(?:[^()\s]|\([^()\s]*+\))*+))(?:\s++(?:\"[^\"]{0,200}+\"|'[^']{0,200}+'|\([^)]{0,200}+\)))?+\s*+\)")
RX_NAKED_URL = re.compile(r"(?<!\]\()https?://[^\s)\]>]+")
RX_BULLET = re.compile(r"^\s*-[ \t]+\S")                       # a bullet: a dash, spaces or a tab, then something
_RX_MARKER = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])[ \t]+")      # a list marker taken off a script's or a model's line: a bullet, a star, a dot, `1.` or `12)`
_RX_FENCE = re.compile(r"^[ \t]*(?:```|~~~)")
_RX_FENCE_END = re.compile(r"^[ \t]*(?:```|~~~)[ \t]*$")
_RX_QUOTE = re.compile(r"^[ \t]*>")


def _visible(line: str) -> str:
    """A line as it reads: a link as its words, a naked URL as nothing, the ends trimmed."""
    return RX_NAKED_URL.sub("", RX_MD_LINK.sub(r"\1", line)).strip()


def visible_len(line: str) -> int:
    """A line's length as it reads: a link counts as its words, a naked URL as nothing, the ends trimmed."""
    return len(_visible(line))


_RX_CODE_SPAN = re.compile(r"`[^`\n]*+`")
_RX_ANY_URL = re.compile(r"https?://[^\s<>)\]]++", re.I)
_URL_TAIL = ".,;:!?'\"*_"           # what a sentence puts after a URL, not part of it


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
            out.append(m.group(0).rstrip(_URL_TAIL))
    return out


def _closed_fences(lines: list[str]) -> set[int]:
    """The indexes of the lines inside a closed fenced block, fence lines included (a fence still open at the end is no fence), as bare_urls reads them."""
    out, open_at = set(), -1
    for k, ln in enumerate(lines):
        if open_at < 0:
            if _RX_FENCE.match(ln):
                open_at = k
        elif _RX_FENCE_END.match(ln):
            out.update(range(open_at, k + 1))
            open_at = -1
    return out


_RX_SCHEME = re.compile(r"https?://", re.I)
_RX_ANGLE = re.compile(r"<https?://[^\s<>]*+>", re.I)                 # an autolink
_RX_REFDEF = re.compile(r"^[ ]{0,3}\[[^\]\n]*+\]:[ \t]*+<?(https?://\S*+)", re.I)      # a reference definition's address
_RX_ATTR = re.compile(r"=[ \t]*+[\"']?+")                              # what an attribute puts before its address
_URL_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~:/?#@!$&'*+,;=%")      # the ASCII a URL is made of (a bracket, a quote, a space and anything else ends it); parentheses by balance


_RX_TICKS = re.compile(r"`+")
_JOINERS = "/?#=&%~+:@.-_"           # what an address does not end on when more of it follows (a character that is no URL character after one of these is part of a path, not a particle)
_REST_TAIL = ".,;:!?'\")]*_"          # what a sentence, a quote, a closing bracket or a closing emphasis puts after an address


def _code_spans(ln: str) -> list[tuple[int, int]]:
    """The code spans of one line as Markdown reads them: a run of N backticks to the next run of exactly N (a longer or shorter run is no closer). A run with no closer opens nothing. Linear: the runs of each length are
    walked once."""
    runs = [m.span() for m in _RX_TICKS.finditer(ln)]
    by_len: dict[int, list[int]] = {}
    for k, (a, b) in enumerate(runs):
        by_len.setdefault(b - a, []).append(k)
    at: dict[int, int] = {}
    out, k = [], 0
    while k < len(runs):
        n = runs[k][1] - runs[k][0]
        lst, j = by_len[n], at.get(n, 0)
        while j < len(lst) and lst[j] <= k:
            j += 1
        at[n] = j
        if j < len(lst):
            out.append((runs[k][0], runs[lst[j]][1]))
            k = lst[j] + 1
        else:
            k += 1
    return out


_RX_EMPH = re.compile(r"\*+|_+")


def _emph_depths(ln: str) -> dict[tuple[str, int], tuple[list[int], list[int]]]:
    """For each emphasis run of one line (a run of * or _ and its length): its start positions in order and, after each, how many runs of that kind are open there. A run opens when no letter or digit stands before it and a
    non-space follows (so `snake_case_` and `* item` open nothing); one closes the latest open run of its kind when a non-space stands before it and no letter or digit follows. One pass over the line."""
    out: dict[tuple[str, int], tuple[list[int], list[int]]] = {}
    for m in _RX_EMPH.finditer(ln):
        a, b = m.span()
        before, after = ln[a - 1] if a else "", ln[b] if b < len(ln) else ""
        pos, depth = out.setdefault((m.group()[0], b - a), ([], []))
        d = depth[-1] if depth else 0
        if not before.isalnum() and after and not after.isspace():
            d += 1
        elif before and not before.isspace() and not after.isalnum() and d:
            d -= 1
        pos.append(a)
        depth.append(d)
    return out


def _url_span(s: str, at: int, emph: dict[str, Any] | None = None) -> tuple[int, int]:
    """(where the address that opens with the scheme at `s[at:]` ends, where the scan goes on): the end is `at` when the address is not to be linked. It runs as far as URL characters go, a parenthesis only as one
    that closes one inside it (an unclosed one ends the address before it), without the . , ; : ! ? or ' a sentence puts after it, and without a closing run of * or _ that an emphasis opened earlier in the line (a run of the same
    character and length opened before the address and not yet closed; a trailing run nothing opened, as in `__init__` or `src/**`, is the address's own). `emph` is the line's cache of those runs, built once on first use. When the address stops short and the rest of its whitespace-delimited token still reads as
    address (a path character, a letter or a digit, or any non-ASCII character after one of / ? # = & % . - _ ~ + : @), the token is no address this can cut in the right place: it is not linked, and the caller's
    refusal stands. A short rest that is no address (a particle after the address, a closing bracket or quote) stays out of the link."""
    start = _RX_SCHEME.match(s, at).end()
    i, opens = start, []
    while i < len(s):
        c = s[i]
        if c == "(":
            opens.append(i)
        elif c == ")":
            if not opens:
                break
            opens.pop()
        elif c not in _URL_CHARS:
            break
        i += 1
    stop = opens[0] if opens else i
    token = stop
    while token < len(s) and not s[token].isspace():
        token += 1
    end = stop
    if emph is None:
        emph = {}
    while True:                                                           # what a sentence and what an emphasis put after the address, in either order (`**address**.`)
        was = end
        while end > start and s[end - 1] in ".,;:!?'":
            end -= 1
        run = 0
        while end > start and end - run > start and s[end - run - 1] in "*_" and s[end - run - 1] == s[end - 1]:
            run += 1
        if run:
            if "runs" not in emph:
                emph["runs"] = _emph_depths(s)
            pos, depth = emph["runs"].get((s[end - 1], run), ([], []))
            k = bisect.bisect_left(pos, at) - 1                           # the last run of this kind before the address: how many are open there
            if k >= 0 and depth[k]:
                end -= run
        if end == was:
            break
    if end <= start:
        return at, token
    rest = s[stop:token].rstrip(_REST_TAIL)
    if rest and (any(c.isascii() and (c.isalnum() or c in "/?#=&%.-~+") for c in rest) or (not rest.isascii() and s[stop - 1] in _JOINERS)):
        return at, token
    return end, token


def link_bare_urls(text: str, skip: Any = ()) -> tuple[str, list[str]] | None:
    """(`text` with every bare http(s) URL that bare_urls finds written as a link to itself, `[url](url)`, the addresses linked in order): the address as the link's words and its target, ending at its last URL character
    (never on a Korean particle after it, a closing parenthesis only when it closes one inside it, a closing emphasis mark that was opened earlier left out, a trailing _ or * run nothing opened kept), nothing else changed (the ends of the line, the line breaks and the punctuation after
    a URL stay). An address already inside an angle autolink, a Markdown link, a reference definition, an attribute or a code span of any backtick count (or a fence) is left as it is, and so is one that stops short with more address-like text after it in its token (see _url_span), and so is one in `skip` (the ones the item already holds,
    as bare_urls reads them). None when a URL is still bare after the change (the caller then leaves the text as written for its own refusal). Linear in the text: each address is scanned once, the guarded stretches are
    searched by position."""
    lines = str(text or "").splitlines(keepends=True)
    fenced = _closed_fences([ln.rstrip("\r\n") for ln in lines])
    room = max(map(len, skip), default=0) + 2          # a run of more characters than any held address is none of them
    out, linked = [], []
    for k, ln in enumerate(lines):
        if k in fenced or "http" not in ln.lower():
            out.append(ln)
            continue
        spans = sorted([m.span() for rx in (_RX_CODE_SPAN, RX_MD_LINK, _RX_ANGLE) for m in rx.finditer(ln)] + [m.span(1) for m in _RX_REFDEF.finditer(ln)] + _code_spans(ln))
        guard: list[tuple[int, int]] = []
        for a, b in spans:
            if guard and a <= guard[-1][1]:
                guard[-1] = (guard[-1][0], max(b, guard[-1][1]))
            else:
                guard.append((a, b))
        starts = [a for a, _ in guard]
        attr_at = {m.end() for m in _RX_ATTR.finditer(ln)}
        parts, at, pos = [], 0, 0
        emph: dict[str, Any] = {}
        for m in _RX_SCHEME.finditer(ln):
            if m.start() < pos:
                continue                                                   # inside the address just written
            g = bisect.bisect_right(starts, m.start()) - 1
            if (g >= 0 and m.start() < guard[g][1]) or m.start() in attr_at:
                continue
            end, nxt = _url_span(ln, m.start(), emph)
            if end == m.start():
                pos = nxt                                                  # not linked: the rest of its token is no other address (the scan stays linear)
                continue
            url = ln[m.start():end]
            if skip:
                raw = _RX_ANY_URL.match(ln, m.start(), min(len(ln), m.start() + room))
                if url in skip or (raw is not None and raw.end() < m.start() + room and raw.group(0).rstrip(_URL_TAIL) in skip):
                    pos = end
                    continue
            parts.append(ln[at:m.start()] + f"[{url}]({url})")
            linked.append(url)
            at = pos = end
        out.append("".join(parts) + ln[at:])
    new = "".join(out)
    return None if set(bare_urls(new)) - set(skip) else (new, linked)


def _fenced(lines: list[str]) -> set[int]:
    """The indexes of the lines inside a closed fenced block, fence lines included (a fence still open at the end is no fence: its lines stay judged)."""
    fenced: set[int] = set()
    open_at = -1                               # one pass: the line a fence opened at, -1 when none is open
    for k, ln in enumerate(lines):
        if open_at < 0:
            if _RX_FENCE.match(ln):
                open_at = k
        elif _RX_FENCE_END.match(ln):
            fenced.update(range(open_at, k + 1))
            open_at = -1
    return fenced


def judge(text: str, max_lines: int, line_max: int) -> tuple[str, str, int] | None:
    """The form of a description, judged once for everyone (the write gate, the re-bullet pass): None when it keeps the form, else ("lines", "", n) when it has n non-blank
    lines (more than max_lines), ("marker", line, 0) for the first line that is not a `- ` bullet, or ("long", line, n) for the first line that reads n characters (over line_max).
    Every non-blank line counts toward max_lines, a fence line and a `>` quote line too. A `>` quote line (his words) is exempt from the marker but not from the length; a fenced
    block, fence lines included, from both. An indented line that is not a bullet is prose, like any other. An unclosed fence is no fence. line_max 0 judges no length."""
    lines = str(text or "").splitlines()
    live = [(k, ln) for k, ln in enumerate(lines) if ln.strip()]
    if len(live) > max_lines:                  # the count first: nothing else is worth scanning for a text that is refused anyway
        return ("lines", "", len(live))
    fenced = _fenced(lines)
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


_RX_CLAUSE_END = re.compile(r"(?<=[.;]) +(?=\S)")      # the gap after a sentence or a clause that ends with a full stop or a semicolon
_RX_LEAD = re.compile(r"^\s*-[ \t]+")
# What a full stop or semicolon may close without ending a sentence: an entity (&amp;), an abbreviation (e.g., i.e., Mr., Dr., vs., etc., St., Jr., Inc., No.), a dotted initialism (U.S., a.m.), a number ("3.").
# It is searched in the last 24 characters before the gap only (`search(text, pos, endpos)` still reads the character before `pos`), so a long bullet costs a constant per gap.
_RX_NO_CUT = re.compile(r"(?:&#?\w+;|(?i:(?<![\w.])(?:e\.g|i\.e|mr|mrs|ms|dr|vs|cf|fig|approx|etc|st|jr|sr|inc|ltd|corp))\.|(?<![\w.])(?:No|Nos)\.|(?<![\w.])(?:[A-Za-z]\.){2,}|(?<![\w.])\d+\.)$")
_NO_CUT_WINDOW = 24


def _indent(ln: str) -> int:
    return len(ln) - len(ln.lstrip())


def _merged(spans: list[tuple[int, int]]) -> tuple[list[int], list[int]]:
    """The starts and the ends of `spans` with the ones that overlap taken as one (spans that only touch stay apart: a cut between them is outside both)."""
    starts: list[int] = []
    ends: list[int] = []
    for a, b in sorted(spans):
        if ends and a < ends[-1]:
            ends[-1] = max(ends[-1], b)
        else:
            starts.append(a)
            ends.append(b)
    return starts, ends


def _clauses(body: str) -> list[tuple[str, str]]:
    """`body` cut at the gaps after a full stop or a semicolon, as (the clause, the spaces that followed it; "" for the last). A gap is no cut inside a link, a naked URL or a code span, inside an open
    parenthesis or an unclosed `**` emphasis, nor after an entity, an abbreviation or a number (`_RX_NO_CUT`). One pass: the balance is counted on the stretch since the last gap, never again on the whole prefix."""
    starts, ends = _merged(_spans(body) + [m.span() for m in _RX_CODE_SPAN.finditer(body)])

    def inside(x: int) -> bool:
        k = bisect.bisect_left(starts, x) - 1
        return k >= 0 and x < ends[k]

    out: list[tuple[str, str]] = []
    at = seen = opens = closes = strong = 0
    for m in _RX_CLAUSE_END.finditer(body):
        s = m.start()
        seg = body[seen:s]                 # a `**` never straddles a gap: its stars are not a full stop or a semicolon
        opens, closes, strong, seen = opens + seg.count("("), closes + seg.count(")"), strong + seg.count("**"), s
        if inside(s) or inside(m.end()) or opens > closes or strong % 2 or _RX_NO_CUT.search(body, max(0, s - _NO_CUT_WINDOW), s):
            continue
        out.append((body[at:s], m.group(0)))
        at = m.end()
    out.append((body[at:], ""))
    return out


# The second tier of a split: a clause that is over the limit on its own is cut at a comma or a colon (the mark stays at the end of the first piece, as a semicolon does), at a spaced dash (the dash is
# the separator the new bullet replaces and is dropped) or before an opening parenthesis (it opens the next piece). Each gap is a space run with a character that is no space after it.
_RX_SOFT_CUT = re.compile(r"(?<=[,:]) +(?=\S)|(?<=\S) +[-\u2013\u2014] +(?=\S)|(?<=\S) +(?=\()")
_SOFT_MIN = 10                  # a piece cut by the second tier reads at least this many characters: a stub of a few words is no bullet


_RX_NONSPACE = re.compile(r"\S")
_SOFT_SLACK = (0, 0)           # a test seam, (a piece's fit and floor, the rest's fit): how far the table below may read too generously, so a test can show the full `visible_len` confirmations are what decide


def _soft_units(c: str, mark: str, line_max: int, cap: int) -> list[tuple[str, str]] | None:
    """One clause `c` that reads over `line_max` (after `mark`) as (the piece, the gap that followed it) units, cut from the left at the last comma, colon, spaced dash or opening parenthesis that leaves the
    piece within the limit; the rest is cut again the same way until it fits. A cut is never made inside a link, a naked URL or a code span, an open parenthesis or an unclosed `**` emphasis, and never leaves a
    piece that reads under `_SOFT_MIN`. The last unit's gap is "" (the caller gives it the clause's own). None when no such cut gives a fit, or when it would take more than `cap` cuts (more pieces than the
    description may have lines).
    Linear in the clause: what a stretch reads comes from one table, bisected, and only the pieces a cut makes are then measured in full (`visible_len`), which decides. The table counts what `visible_len` counts: a
    link as its words, then no naked URL (also one that sits in a link's words, or starts before a link: those stretches are merged), the ends of a piece trimmed (so the spaces beside an edge URL do not count),
    the spaces inside a piece do."""
    links = list(RX_MD_LINK.finditer(c))
    zero = [(m.start(), m.start(1)) for m in links] + [(m.end(1), m.end()) for m in links]          # a link's brackets and destination read as nothing
    runs_t: list[int] = []
    runs_o: list[int] = []                    # where each stretch of the link-less text `t` starts in `t` and in `c`
    tlen = pos = 0
    for m in links:
        for lo, hi in ((pos, m.start()), (m.start(1), m.end(1))):
            if hi > lo:
                runs_t.append(tlen)
                runs_o.append(lo)
                tlen += hi - lo
        pos = m.end()
    if len(c) > pos:
        runs_t.append(tlen)
        runs_o.append(pos)
    for u in RX_NAKED_URL.finditer(RX_MD_LINK.sub(r"\1", c)):          # the addresses `_visible` takes out, found as it finds them, then put back at their place in `c`
        p, q = u.span()
        i, k = bisect.bisect_right(runs_t, p) - 1, bisect.bisect_right(runs_t, q - 1) - 1
        zero.append((runs_o[i] + p - runs_t[i], runs_o[k] + q - runs_t[k]))
    zst: list[int] = []
    zen: list[int] = []
    for x, y in sorted(zero):
        if zen and x <= zen[-1]:
            zen[-1] = max(zen[-1], y)
        else:
            zst.append(x)
            zen.append(y)
    zsum = [0]
    for x, y in zip(zst, zen):
        zsum.append(zsum[-1] + y - x)

    def reads(x: int) -> int:         # what c[:x] reads before the ends are trimmed, for an x that is no place inside a link or a URL
        return x - zsum[bisect.bisect_right(zen, x)]

    def zskip(x: int) -> int:         # x, or the end of the stretch of nothing that holds it
        k = bisect.bisect_right(zst, x) - 1
        return zen[k] if k >= 0 and x < zen[k] else x

    def zback(x: int) -> int:         # x, or the start of the stretch of nothing that holds the character before it
        k = bisect.bisect_right(zst, x - 1) - 1
        return zst[k] if k >= 0 and x - 1 < zen[k] else x

    def first_visible(x: int, hi: int) -> int | None:          # the first character in c[x:hi] that is no space and does not read as nothing
        while x < hi:
            if (y := zskip(x)) != x:
                x = y
            elif (m := _RX_NONSPACE.search(c, x, hi)) is None:
                return None
            elif (y := zskip(m.start())) == m.start():
                return m.start()
            else:
                x = y
        return None

    def last_visible_end(lo: int, x: int) -> int | None:       # the end of the last such character in c[lo:x]
        while x > lo:
            w = c[max(lo, x - 512):x]
            if n := len(w) - len(w.rstrip()):
                x -= n
            elif (y := zback(x)) != x:
                x = max(y, lo)
            else:
                return x
        return None

    starts, ends = _merged(_spans(c) + [m.span() for m in _RX_CODE_SPAN.finditer(c)])

    def inside(x: int) -> bool:
        k = bisect.bisect_left(starts, x) - 1
        return k >= 0 and x < ends[k]

    cuts: list[tuple[int, int]] = []
    seen = opens = closes = strong = 0
    for m in _RX_SOFT_CUT.finditer(c):
        s = m.start()
        seg = c[seen:s]
        opens, closes, strong, seen = opens + seg.count("("), closes + seg.count(")"), strong + seg.count("**"), s
        if inside(s) or inside(m.end()) or opens > closes or strong % 2:
            continue
        cuts.append((s, m.end()))
    a0, send = first_visible(0, len(c)), last_visible_end(0, len(c))
    if a0 is None or send is None:
        return None
    sp: list[int] = []                         # for each cut: where the first piece's last readable character ends, and where the rest's first begins
    last, lo = 0, 0
    for s, _ in cuts:
        last = x if (x := last_visible_end(lo, s)) is not None else last
        sp.append(last)
        lo = s
    ep = [0] * len(cuts)
    nxt = len(c)
    for j in range(len(cuts) - 1, -1, -1):
        hi = cuts[j + 1][1] if j + 1 < len(cuts) else len(c)
        nxt = x if (x := first_visible(cuts[j][1], hi)) is not None else nxt
        ep[j] = nxt
    vs, ve, vep = [reads(x) for x in sp], [reads(e) for _, e in cuts], [reads(x) for x in ep]
    vend = reads(send)
    room = line_max - len(mark.lstrip())
    slack, slack_end = _SOFT_SLACK
    out: list[tuple[str, str]] = []
    at = vat = 0
    vap = reads(a0)
    while vend - vat > room + slack_end:
        if len(out) > cap:
            return None
        j = bisect.bisect_right(vs, vat + room + slack) - 1           # the last cut whose first piece fits; the ones before it read less
        while j >= 0 and cuts[j][0] > at and vs[j] - vap >= _SOFT_MIN - slack:
            s, e = cuts[j]
            if vend - vep[j] >= _SOFT_MIN - slack and visible_len(mark + c[at:s]) <= line_max and visible_len(c[at:s]) >= _SOFT_MIN and visible_len(c[e:]) >= _SOFT_MIN:
                out.append((c[at:s], c[s:e]))
                at, vat, vap = e, ve[j], vep[j]
                break
            j -= 1
        else:
            return None
    if visible_len(mark + c[at:]) > line_max:
        return None
    out.append((c[at:], ""))
    return out


_RX_SPACES = re.compile(r"[ \t]+")
_CONT_INDENT = 2          # a continuation line sits two spaces deeper than its bullet: the form the parallel-bullets text names (a child bullet under one parent)


def _wrap_words(ln: str, line_max: int, cap: int) -> list[str] | None:
    """The last-resort cut of one bullet line that reads over `line_max`: cut at the last space whose first part reads within `line_max` (counted as `visible_len` counts a line: `- ` included, the ends trimmed, so the indent is free), the
    rest put on a new line `<indent + 2 spaces>- <rest>`, a child bullet under the first (the form the gate takes: a line with no `- ` marker is refused as prose); the rest is cut again the same way while it reads
    over. A cut is made only at a space, never inside a word, a link, a naked URL or a code span, so no word is changed. -> the lines, or None when a piece cannot be cut to fit (one unbroken token longer than a line),
    or when the lines would pass `cap`. A line that fits comes back as it is."""
    out: list[str] = []
    cur = ln
    while visible_len(cur) > line_max:
        if len(out) + 1 >= cap:
            return None
        starts, ends = _merged(_spans(cur) + [m.span() for m in _RX_CODE_SPAN.finditer(cur)])
        lead = _RX_LEAD.match(cur)
        body_at = lead.end() if lead else 0
        cut = None
        for m in reversed(list(_RX_SPACES.finditer(cur))):
            k = bisect.bisect_left(starts, m.start()) - 1
            if m.start() <= body_at or m.end() >= len(cur) or (k >= 0 and m.start() < ends[k]):
                continue                # no cut in the lead, after the last word, or inside a link, URL or code span
            if visible_len(cur[:m.start()]) <= line_max and visible_len(cur[body_at:m.start()]) >= _SOFT_MIN:          # the first part is more than a label or a stub (as a clause cut's pieces are)
                cut = m
                break
        if cut is None:
            return None
        out.append(cur[:cut.start()])
        cur = " " * (_indent(cur) + (0 if len(out) > 1 else _CONT_INDENT)) + "- " + cur[cut.end():]
    return out + [cur]


def _split_long(text: str, max_lines: int, line_max: int, wrap: bool) -> tuple[str, int, int, int] | None:
    """A description whose only fault is bullets that read over `line_max`, put right without losing a word: each such bullet is cut at the gaps after a full stop or a semicolon (never inside a link, a naked
    URL or a code span) into the fewest bullets that each read within `line_max`, the same indent and dash on each. A clause that is over the limit on its own gets a second tier (`_soft_units`): it is cut at
    the last comma, colon, spaced dash or opening parenthesis that leaves each piece within the limit. → (the new text, how many bullets were split, how many of those needed the second tier), or None when it
    cannot be done that way: a clause with no such cut, a result over `max_lines` lines, a long bullet that has an indented line under it (its children would end up under the last piece), or no long bullet to split. A cut is not
    made inside an open parenthesis or an open `**` emphasis, nor after an entity, an abbreviation (e.g., i.e., Mr., etc., St., No., U.S.) or a bare number. A `>` quote line, a fenced block and a line that is no
    bullet are left as they are (the gate still judges them). The text changes at the cut and nowhere else: each semicolon stays, the spaces between the clauses that stay together stay as written, and every
    line end (LF, CRLF or any other the text has) is kept; a cut puts that line's own end between its pieces. The bullets that need a split are summed up first: when what they read, spaces left out, cannot fit
    `max_lines` lines of `line_max`, the answer is None before any bullet is scanned (the splitter runs under the item lock, so a pasted wall of text is refused at once).
    `wrap` adds the last resort for a bullet the sentence and clause cuts cannot split (a clause with no cut that fits): the bullet is cut at its last space that fits and the rest goes on an indented child bullet
    (`_wrap_words`: no word is cut, nothing inside a link, a URL or a code span). A bullet that has children under it, a result over `max_lines` lines and a piece that cannot be cut to fit are still None.
    -> (text, bullets split, of those cut at a comma or dash, of those wrapped at a space)."""
    if not line_max:
        return None
    raw = str(text or "").splitlines(keepends=True)
    lines = [r.splitlines()[0] for r in raw]
    ends = [r[len(c):] for r, c in zip(raw, lines)]
    default_end = next((e for e in ends if e), "\n")
    fenced = _fenced(lines)
    long_at: list[int] = []
    dense = 0
    for k, ln in enumerate(lines):
        if not ln.strip() or k in fenced or _RX_QUOTE.match(ln) or not _RX_LEAD.match(ln):
            continue
        vis = _visible(ln)
        if len(vis) > line_max:
            long_at.append(k)
            dense += len("".join(vis.split()))        # what a cut keeps whole: every character that is no space, so the pieces cannot read less than this in all
    if not long_at or dense > max_lines * line_max:
        return None
    out: list[str] = []
    n = soft = wrapped = 0
    todo = set(long_at)
    for k, ln in enumerate(lines):
        if k not in todo:
            out.append(ln + ends[k])
            continue
        lead = _RX_LEAD.match(ln)
        body, mark = ln[lead.end():], lead.group(0)
        below = next((x for x in lines[k + 1:] if x.strip()), "")
        if below and _indent(below) > _indent(ln):          # a bullet with children under it: the children belong to the whole, so no cut
            return None
        pieces: list[str] | None = []
        gap = ""
        soft_here = False
        for c, after in _clauses(body):
            units: list[tuple[str, str]] | None = [(c, after)]
            if visible_len(mark + c) > line_max:
                if (units := _soft_units(c, mark, line_max, max_lines)) is None:
                    pieces = None
                    break
                units[-1] = (units[-1][0], after)
                soft_here = True
            for u, g in units:
                if pieces and visible_len(mark + pieces[-1] + gap + u) <= line_max:
                    pieces[-1] += gap + u
                else:
                    pieces.append(u)
                gap = g
        sep = ends[k] or default_end
        if pieces is not None and len(pieces) >= 2:
            out.extend(mark + p + (sep if i < len(pieces) - 1 else ends[k]) for i, p in enumerate(pieces))
            n += 1
            soft += soft_here
            continue
        wrapped_ = _wrap_words(ln, line_max, max_lines) if wrap else None
        if wrapped_ is None:
            return None
        out.extend(w + (sep if i < len(wrapped_) - 1 else ends[k]) for i, w in enumerate(wrapped_))
        n += 1
        wrapped += 1
    if not n or len([ln for ln in out if ln.strip()]) > max_lines:
        return None
    return "".join(out), n, soft, wrapped


def split_long_ex(text: str, max_lines: int, line_max: int) -> tuple[str, int, int] | None:
    """`_split_long` with the sentence and clause cuts only: (the new text, how many bullets were split, how many of those needed the second tier), or None (see `_split_long`)."""
    res = _split_long(text, max_lines, line_max, False)
    return None if res is None else res[:3]


def split_long_wrap(text: str, max_lines: int, line_max: int) -> tuple[str, int, int, int] | None:
    """`_split_long` with the last resort on (a bullet no sentence or clause cut can split is cut at its last space that fits, the rest on an indented child bullet): (the new text, how many bullets were split,
    how many of those needed the second tier, how many of those were cut at a space), or None. The write gates use this one."""
    return _split_long(text, max_lines, line_max, True)




def split_long(text: str, max_lines: int, line_max: int) -> tuple[str, int] | None:
    """`split_long_ex` without the count of bullets that needed the second tier: (the new text, how many bullets were split), or None."""
    res = split_long_ex(text, max_lines, line_max)
    return None if res is None else res[:2]


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


# What `str.splitlines` ends a line at: a line's end is read the same way here as `first_bullet` reads the lines, so a bullet with an unusual end keeps it.
_LINE_END_CHARS = "\r\n\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"


def _end_of(ln: str) -> str:
    return ln[len(ln.rstrip(_LINE_END_CHARS)):]


def _body_of(ln: str) -> str:
    return ln[:len(ln) - len(_end_of(ln))]


def _first_bullet_at(text: str) -> tuple[list[str], int] | None:
    """(the lines of `text` with their line ends, the index of its first `- ` bullet as `first_bullet` reads it), None when it has none."""
    lines = str(text or "").splitlines(keepends=True)
    fenced = False
    for i, ln in enumerate(lines):
        if _RX_FENCE.match(_body_of(ln)):
            fenced = not fenced
            continue
        if not fenced and _RX_FIRST_BULLET.match(_body_of(ln)):
            return lines, i
    return None


# A goal label in another form: any case, Goal or Goals, the Korean word for it (written as escapes: no Hangul in the repository), a colon (also the wide one) or one spaced dash after it, optional bold marks.
_RX_GOAL_FORM = re.compile(r"^(?P<indent>[ \t]*)-[ \t]+(?P<open>\*{0,2})(?P<label>goals?|\ubaa9\ud45c)(?P<c1>\*{0,2})(?:[ \t]*[:\uff1a]|[ \t]+[-\u2013\u2014](?![-\u2013\u2014]))(?P<c2>\*{0,2})[ \t]*(?P<rest>\S.*)$", re.I)


_RX_GOAL_BARE = re.compile(r"^\*{0,2}(?:goals?|\ubaa9\ud45c)\*{0,2}(?:[ \t]*[:\uff1a]|[ \t]+[-\u2013\u2014])?\*{0,2}[ \t]*$", re.I)


def relabel_goal(text: str) -> tuple[str, str] | None:
    """A description whose first `- ` bullet opens with a goal word in another form (`goal: x`, `Goal - x`, `GOALS: x`, the Korean label, a bold one) → (the text with that bullet written `- Goal: x`, the label as
    written), the bullet's indent, its line end and the words after the label untouched and the other lines byte for byte. A bold mark that opens before the label and closes after the sentence (`**Goal: x**`) goes with
    the label. None when the first bullet already opens `Goal:`, opens with anything else, holds a label and nothing after it (a goal is a sentence), or would be left with a bold mark that does not close."""
    if goal_of(text) is not None:
        return None
    at = _first_bullet_at(text)
    if at is None:
        return None
    lines, i = at
    m = _RX_GOAL_FORM.match(_body_of(lines[i]))
    if m is None:
        return None
    rest, mark = m.group("rest").strip(), m.group("open")
    if mark and not (m.group("c1") or m.group("c2")):
        n = rest.count(mark)
        if n == 1 and rest.endswith(mark):
            rest = rest[:-len(mark)].rstrip()      # the mark that opened before the label closes after the sentence: the label's own mark goes, and so does its close
        elif n:
            return None                            # a mark inside the sentence that the label's would have paired with: dropping one leaves them paired wrongly
    if not rest or rest.count("**") % 2:
        return None
    lines[i] = f"{m.group('indent')}- {GOAL_LABEL} {rest}" + _end_of(lines[i])
    return "".join(lines), m.group("label")


def goal_example(text: str) -> str | None:
    """The description as written with its first `- ` bullet turned into the goal: `- Goal: <that bullet>`, the other lines as they are; None when the text has no bullet. What a refusal for a description that does not
    open with its goal shows, so the writer can send it again as it is (or reword the goal in it)."""
    at = _first_bullet_at(text)
    if at is None:
        return None
    lines, i = at
    first = _RX_FIRST_BULLET.match(_body_of(lines[i])).group(1).strip()
    if _RX_GOAL_BARE.match(first):          # a label and nothing after it: there is no sentence to carry over
        return None
    lines[i] = f"- {GOAL_LABEL} {first}" + _end_of(lines[i])
    return "".join(lines).strip("\r\n")


def goal_of(text: str) -> str | None:
    """The goal a description states: what follows `Goal:` in its first bullet when that bullet opens with it (case-sensitive, the label right after the dash) and says something after it; else None."""
    b = first_bullet(text)
    if b is None or not b.startswith(GOAL_LABEL):
        return None
    rest = b[len(GOAL_LABEL):].strip()
    return rest or None


def stated_goal(text: str) -> str | None:
    """The goal a stored description gives, however it wrote it: `goal_of`; for a first bullet with the label in another form (relabel_goal), what follows the label; else the first bullet itself, so that a rewrite
    that only puts the label before it changes no words. None when there is no bullet."""
    if (got := goal_of(text)) is not None:
        return got
    if relabeled := relabel_goal(text):
        return goal_of(relabeled[0])
    return first_bullet(text)


def goal_words(sentence: str) -> list[str]:
    """The words of a goal sentence, to compare two writings of it: letters and digits, in any case, and each symbol (`<`, `=`, `+`, a currency sign) or percent sign as a word of its own; a link counts as its words.
    Spacing, punctuation, quotes, dashes, emphasis marks and backticks only separate words, so a re-formatted sentence gives the same list; a word split or joined ("Re-run", "Rerun") gives another, and so does
    a changed symbol (the `~` of strikethrough is one)."""
    t = RX_MD_LINK.sub(r"\1", str(sentence or "")).replace("`", " ")
    t = unicodedata.normalize("NFC", t).casefold()
    return "".join(c if c.isalnum() or unicodedata.category(c)[0] == "M" else f" {c} " if c == "%" or unicodedata.category(c)[0] == "S" else " " for c in t).split()


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


def _clip_line(text: str, limit: int = 600) -> str:
    """Free text as one line of a notice: whitespace collapsed, cut at a word before `limit` with an ellipsis."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0] if " " in t[:limit] else t[:limit]
    return cut.rstrip(" ,;:") + " …"


def cut_words(text: str, limit: int, mark: str = " …") -> str | None:
    """One line `text` over `limit` characters cut at the last whole word that fits, with `mark` after it (counted in the limit, as clip_bullet and the server's own cuts do): no word is cut in two and the
    kept words are as written. Never inside a code span, a link's words or a parenthesis: the cut falls before one that would be left open (an odd number of backticks, a `[` or a `(` with no closing mark in what is kept).
    `text` itself when it reads within the limit; None when no whole word fits (a first word over the room, or no gap outside such a stretch), which the caller refuses as before."""
    t = str(text or "").strip()
    if len(t) <= limit:
        return t
    room = limit - len(mark)
    if room < 1:
        return None
    head = t[:room + 1]
    for e in sorted((m.start() for m in re.finditer(r"\s", head) if m.start() <= room), reverse=True):          # the gaps a word can end at: a word of exactly `room` characters ends at the gap just after it
        kept = t[:e].rstrip(" ,;:")
        if kept and kept.count("`") % 2 == 0 and kept.count("[") <= kept.count("]") and kept.count("(") <= kept.count(")"):
            return kept + mark
    return None
