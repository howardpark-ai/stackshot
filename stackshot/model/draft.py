"""draft.py — the draft of an item: the verbatim text the owner pastes elsewhere (an item whose step is to post a text carries the text on its page to copy;
such a message once lived only in a session's chat).

An item can carry `metadata.draft`: the text exactly as it is to be posted, sent or pasted, many lines, any language, stored and shown as written (no bullet form, no line
cap; one size cap, MAX). The item page draws it inside the step of the Your step block that uses it, under a "Message to paste" label ("Email text to paste" for an email) with Copy beside it and the text in the page's body font, and the home row
does the same, collapsed behind that label with the same Copy; get shows it as a `draft:` block; the GitHub mirror carries it in the issue body under "### Draft". A close drops it, and so does his Done or Send note on the step.

The write guard (`problem`): an item that a write leaves in state your-step with the owner as the mover, whose step names text to post, send or paste (a word of STEMS, or one of [keywords.draft]), is
refused unless it carries a draft or its step or description links the document that holds the text. Pure functions of an item and a text: no server import, so the server, the
renderer and the guard share one copy."""
from __future__ import annotations

import re
from typing import Any

from stackshot.core import config as _cfg
from stackshot.model import model as _model

MAX = 20000                                  # a draft is at most this many characters (a sane total, not a line cap)
NONE = ("none", "clear", "-")                # a whole value of these clears the field, as for ask and due (draft="" is the default and means "not passed")

# What a step says when the thing the owner does is post, send or paste a text. A heuristic, not a complete list: a step that says it in other words passes. English is found as a whole word with its endings;
# a hyphen on either side (post-mortem, e-mail-based) is no hit. Left out on purpose: "error message", "commit message", "log message" and "warning message" (a message the machine wrote); "send me",
# "send back", "reply here", "message me" (the answer to the session that asked); "share your screen"; "going forward", "look forward", "moving forward" (an adverb); "submit the form" and
# "submit a PR". A language without word boundaries adds its words under [keywords.draft]: `stems` are found anywhere in the step, `stem_patterns` are regular expressions found anywhere,
# `standalone_stems` only as a whole word, with at most one of the `particles` after them, and a phrase of `ignore_phrases` (a screen share) is cut out of the step before the search.
_EN = re.compile(r"(?<![\w-])(?:post(?:s|ed|ing)?|send(?:s|ing)?(?!\s+(?:me|us|back)\b)|sent(?!\s+(?:me|us)\b)|paste[sd]?|pasting|repl(?:y|ies|ied|ying)(?!\s+(?:here|back|to me|to us)\b)|draft(?:s|ed|ing)?"
                 r"|(?<!error )(?<!commit )(?<!log )(?<!warning )message[sd]?(?!\s+(?:me|us)\b)|e-?mail(?:s|ed|ing)?(?!\s+(?:me|us)\b)"
                 r"|share[sd]?(?!\s+(?:(?:your|the|my|our)\s+)?screen\b)|sharing(?!\s+(?:(?:your|the|my|our)\s+)?screen\b)"
                 r"|(?<!going )(?<!look )(?<!looking )(?<!moving )(?<!straight )forward(?:s|ed|ing)?|submit(?:s|ted|ting)?(?!\s+(?:(?:the|a|an)\s+)?(?:form|pr|pull request)\b))(?![\w-])", re.I)
STEMS = "post, send, paste, reply, draft, message, email, share, forward, submit"      # what the refusal and the docs name (the English words; [keywords.draft] adds others)
_CODE = re.compile(r"`[^`\n]*`|\]\([^)\s]*\)|https?://\S+")            # a command in backticks, a link's address and a bare URL are not prose
_LINK = re.compile(r"https?://[^\s<>\"`)\]]+", re.I)
# A link that cannot hold the text: a GitHub issue, pull request or commit (a discussion about work, not the document), and the board's own item pages (the configured public base URL).
_NOT_DOC = re.compile(r"https?://(?:www\.)?github\.com/[^/\s]+/[^/\s]+/(?:issues|pull|pulls|commit|commits)(?:/|$|[?#])", re.I)


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def normalize(text: Any) -> str:
    """The draft as stored: its line breaks as \\n and its blank lines before and after dropped, nothing else touched (the indentation and spaces inside stay as written)."""
    t = str(text if text is not None else "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"(?:\n[ \t]*)+\Z", "", re.sub(r"\A(?:[ \t]*\n)+", "", t))


def is_clear(text: Any) -> bool:
    """Is the whole value one of none, clear or - (a clear, like the ask's)?"""
    return str(text or "").strip().lower() in NONE


def of(item: dict[str, Any]) -> str:
    """The draft an open item carries, "" when it has none or is closed."""
    if item.get("status") == "completed":
        return ""
    v = (item.get("metadata") or {}).get("draft")
    return v if isinstance(v, str) and v.strip() else ""


def fenced(text: str) -> str:
    """The text as a markdown code block, its fence one backtick longer than the longest run of backticks inside it (so the text cannot close the block early)."""
    run = max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, run + 1)
    return f"{fence}\n{text}\n{fence}"


def _extra():
    """The words of [keywords.draft] as one regex (compiled once per set of words, so a reload is seen); a pattern nothing matches when none are set."""
    def build(stems, pats, standalone, particles, _ign):
        parts = [x for x in (stems, pats) if x]
        if standalone:
            part = r"(?<!\w)(?:" + standalone + ")"
            if particles:
                part += "(?:" + particles + ")?"
            parts.append(part + r"(?!\w)")
        return "|".join(parts) or _cfg._NEVER
    return _cfg.kw_rx("draft.extra", build, (("draft", "stems"), ("draft", "stem_patterns"), ("draft", "standalone_stems"), ("draft", "particles"), ("draft", "ignore_phrases")), re.I)


def names_text(step: Any) -> str:
    """The word of the step that says it is about a text to post, send or paste ("" when none): code spans and links are cut out first."""
    t = _CODE.sub(" ", str(step or ""))
    ign = _cfg.kw_alt("draft", "ignore_phrases")
    if ign:
        t = _cfg.kw_rx("draft.ignore", lambda a: a, (("draft", "ignore_phrases"),), re.I).sub(" ", t)
    m = _extra().search(t) or _EN.search(t)
    return m.group(0) if m else ""


def has_link(*texts: Any) -> bool:
    """Does any of these texts hold an http(s) link to a document that can hold the text? A GitHub issue, pull request or commit link and a link to the board's own pages ([instance] board_url) do
    not count; a doc, a Drive file, a Notion page, a Slack thread and any other address do."""
    own = str(_cfg.get("instance", "board_url") or "").rstrip("/").lower()
    for t in texts:
        for m in _LINK.finditer(str(t or "")):
            u = m.group(0).rstrip(".,;:")
            if _NOT_DOC.match(u) or (own and (u.lower() == own or u.lower().startswith(own + "/"))):
                continue
            return True
    return False


def owner_steps(item: dict[str, Any]) -> bool:
    """Does the item stand in your-step with the owner as the mover (a stored mover other than the owner is an agent's move, not his)?"""
    if item.get("status") == "completed":
        return False
    m = item.get("metadata") or {}
    if m.get("state") != "your-step":
        return False
    mover = _model.norm_who(m.get("mover"))
    return not mover or _model.is_owner(mover)


def problem(item: dict[str, Any]) -> str:
    """Why the item, as a write leaves it, is refused ("" = fine): it is the owner's step, the step names text to post, send or paste, and the item has no draft and its step and
    description link no document. One line that names the field and the link alternative."""
    if not owner_steps(item):
        return ""
    step = (item.get("metadata") or {}).get("step")
    hit = names_text(step)
    if not hit or of(item) or has_link(step, item.get("description")):
        return ""
    return (f"the step asks {_model.owner_display()} to post, send or paste a text (\"{hit}\"), so put the text in draft=<the text exactly as it is to be pasted> (his item page shows it in a block with a Copy button), "
            "or link the document that holds it in the step or description (an https:// link to a doc; a GitHub issue or PR link does not count)")
