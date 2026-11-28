"""draft.py — the draft of an item: the verbatim text the owner pastes elsewhere (an item whose step is to post a text carries the text on its page to copy;
such a message once lived only in a session's chat).

An item can carry `metadata.draft`: the text exactly as it is to be posted, sent or pasted, many lines, any language, stored and shown as written (no bullet form, no line
cap; one size cap, MAX). The item page draws it inside the step of the Your step block that uses it, under a "Message to paste" label ("Email text to paste" for an email) with Copy beside it and the text in the page's body font, and the home row
does the same, collapsed behind that label with the same Copy; get shows it as a `draft:` block. A close drops it, and so does his Done or Send note when that leaves no step of his open.

THE STEP IT SERVES. A draft is offered for copying only while a step of his that it could serve is open. The server stores no link from a draft to one step (one text per item; the write guard ties it
to `step`, the page places it by the words of the steps), so among several open ones it never guesses. It is RETIRED by the write that leaves nothing of his open (his_open: the open `<member>:` lines
of the checklist, the step of a your-step item, the question of a decision): all dropped or ticked with nothing of his in their place, or all ticked even when the write adds another. A step reworded
or replaced in that write keeps the draft, and so do any step of his still open, a draft the write itself sets, and a draft stored before any step of his. Retiring destroys nothing: the text stays in
metadata.draft. Every step of his that closes while the draft is offered is recorded under it, since any of them may be the one it serves; once it is retired, one of those open again shows it again, as
a new draft does. Another step does not.

AN ANSWERED TEXT. Once he has answered a decision the draft was offered under (to_send), the session may still have to send it: get keeps printing it when it is retired, and neither a Done nor a note of
his drops it, whatever is added, said or closed afterwards, until a new draft, a clear or the close. No page shows a retired one. A write that asks or rewords a decision whose option offers such a text
while the draft stays retired is refused unless it passes draft= (offer_problem).

THE RECORD: metadata.draft_closed (CLOSED) is the keys of the steps of his closed under the draft (True: set by the write being made), metadata.draft_retired (RETIRED) is True while it is retired,
metadata.draft_answered (ANSWERED) is True once he has answered a decision on it.
A draft with no CLOSED was stored before the record and is read from the item as it stands: retired when nothing waits on him and his checklist holds a closed step. A text written after all his steps
had closed, for a step not yet made, reads the same there and cannot be told apart, so it is not offered either (kept; draft= shows it). Every other draft with no record is shown.

The write guards judge the draft as the save will leave it (writes.settled), so one write is judged as the same change in two. `problem`: an item that a write leaves in state your-step with the owner as the mover, whose step names text to post, send or paste (a word of STEMS, or one of [keywords.draft]), is
refused unless it carries a draft or its step or description links the document that holds the text. Pure functions of an item and a text: no server import, so the server, the
renderer and the guard share one copy."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from stackshot.core import config as _cfg
from stackshot.model import model as _model
from stackshot.model import owner_steps as _os
from stackshot.model import steps as _steps

MAX = 20000                                  # a draft is at most this many characters (a sane total, not a line cap)
NONE = ("none", "clear", "-")                # a whole value of these clears the field, as for ask and due (draft="" is the default and means "not passed")
CLOSED, RETIRED, ANSWERED = "draft_closed", "draft_retired", "draft_answered"      # metadata: the record of how the draft stands to his steps (THE STEP IT SERVES) and to his answer (AN ANSWERED TEXT)
RECORD = (CLOSED, RETIRED, ANSWERED)         # all of it: it goes with the text

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


def kept(item: dict[str, Any]) -> str:
    """The draft text an open item holds, offered or retired; "" when it has none or is closed."""
    if item.get("status") == "completed":
        return ""
    v = (item.get("metadata") or {}).get("draft")
    return v if isinstance(v, str) and v.strip() else ""


def of(item: dict[str, Any]) -> str:
    """The draft a page or the write guard takes: the one the item holds, "" once it is retired (THE STEP IT SERVES)."""
    return "" if retired(item) else kept(item)


def _asks_decision(meta: dict[str, Any]) -> bool:
    needs = meta.get("needs")
    return any(clean(n).lower() == "decision" for n in (needs if isinstance(needs, list) else [needs]))


def _checklist(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """The steps on the checklist that open with a member's name, open and closed."""
    return [s for s in _steps.view(meta, keeper=str(meta.get("owner") or "")) if _os.is_named(s["text"])]


def his_open(item: dict[str, Any]) -> set[str]:
    """The keys (steps.owner_key) of what stands open for him on an item: the open `<member>:` lines of its checklist, the step of a your-step item, the question of a decision."""
    if item.get("status") == "completed":
        return set()
    m = item.get("metadata") or {}
    keys = {_steps.owner_key(s["text"]) for s in _checklist(m) if s["status"] == _steps.OPEN}
    if owner_steps(item) and clean(m.get("step")):
        keys.add(_steps.owner_key(_os.line_of(m.get("step"), m)))
    if _asks_decision(m) and clean(m.get("ask")):
        keys.add(_steps.owner_key(_os.line_of(_os.decide_of(m.get("ask")), m)))
    return keys


def _waits(item: dict[str, Any]) -> bool:
    """Does anything stand open for him: a key of his_open, or a your-step or a decision with no words of its own."""
    return bool(his_open(item)) or owner_steps(item) or (item.get("status") != "completed" and _asks_decision(item.get("metadata") or {}))


def _keys(v: Any) -> set[str]:
    """The step keys of a CLOSED record (none for True, the mark of the write that sets a draft)."""
    return {k for k in v if isinstance(k, str)} if isinstance(v, list) else set()


def retired(item: dict[str, Any]) -> bool:
    """Is the draft the item holds retired: the steps of his it served are closed, so nothing offers it for copying (THE STEP IT SERVES)."""
    if not kept(item):
        return False
    m = item.get("metadata") or {}
    if CLOSED not in m:                      # stored before the record: read from the item as it stands
        return not _waits(item) and any(s["status"] != _steps.OPEN for s in _checklist(m))
    return m.get(RETIRED) is True and not his_open(item) & _keys(m[CLOSED])


def _ticked(done_key: str, key: str) -> bool:
    """Is the done step the one `key` names: the same words, or those with his answer after the arrow (owner_steps.with_answer)."""
    return done_key == key or done_key.startswith(key + _os.ARROW.rstrip())


def _picks(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """His answers to decisions on the item (a Done or a note on a step carries `step` and is none)."""
    answers = meta.get("answers")
    return [r for r in answers if isinstance(r, dict) and r.get("kind") == "decision" and "step" not in r] if isinstance(answers, list) else []


def _offer(meta: dict[str, Any]) -> str:
    """The word by which an option's label offers to post, send or paste a text ("" when none does)."""
    return next((w for o in meta.get("options") or [] if isinstance(o, dict) and (w := names_text(o.get("label")))), "")


def to_send(item: dict[str, Any]) -> bool:
    """May a session still have the draft to send: he answered a decision on it, and no new draft, clear or close came since (AN ANSWERED TEXT). Offered or retired is not asked here. One stored
    before the record is read from the item: it does not stand in his your-step, and a decision answer of his ticked a step on its checklist."""
    if not kept(item):
        return False
    m = item.get("metadata") or {}
    if m.get(ANSWERED) is True:
        return True
    if CLOSED in m or owner_steps(item):
        return False
    at = {r.get("ts") for r in _picks(m)}
    return any(s["status"] == _steps.DONE and s.get("at") in at for s in _checklist(m))


def pin(meta: dict[str, Any], before: dict[str, Any]) -> None:
    """Give a draft stored before the record the one it read as when this write began, on `meta` (the item's metadata as the write leaves it), so a step the write adds does not bring a retired
    draft back."""
    if CLOSED in meta or not kept(before):
        return
    old = before.get("metadata") or {}
    keys: set[str] = set()
    if CLOSED not in old and retired(before):
        keys = {_steps.owner_key(s["text"]) for s in _checklist(old) if s["status"] != _steps.OPEN}
        keys |= {k.rsplit(_os.ARROW.rstrip(), 1)[0] for k in keys}      # an answered step opens again under its words alone
        meta[RETIRED] = True
    elif old.get(RETIRED) is True:
        meta[RETIRED] = True
    meta[CLOSED] = old[CLOSED] if CLOSED in old else sorted(keys)
    if to_send(before):
        meta[ANSWERED] = True


def _all_ticked(keys: set[str], before: dict[str, Any], item: dict[str, Any]) -> bool:
    """Did this write tick every one of the steps `keys` (as against dropping or rewording any)."""
    now, was = (Counter(_steps.owner_key(s["text"]) for s in _checklist(i.get("metadata") or {}) if s["status"] == _steps.DONE) for i in (item, before))
    return all(any(_ticked(d, k) for d in now - was) for k in keys)


def settle(item: dict[str, Any], before: dict[str, Any] | None) -> None:
    """Keep the draft's record as a save leaves the item (writes.save: every write, once the checklist is final). Never touches the text."""
    m = item.get("metadata")
    if not isinstance(m, dict):
        return
    if not kept(item):
        for k in RECORD:
            m.pop(k, None)
        return
    if before is None or m.get(CLOSED) is True or (before.get("metadata") or {}).get("draft") != m.get("draft"):
        m[CLOSED] = []; m.pop(RETIRED, None); m.pop(ANSWERED, None)      # a draft this write set: nothing has closed under it, and he has answered nothing on it
        return
    pin(m, before)
    old = before.get("metadata") or {}
    if of(before) and len(_picks(m)) > len(_picks(old)) and (_offer(old) or not owner_steps(before)):
        m[ANSWERED] = True                           # his answer to a decision it was offered under (beside a your-step the text is that step's, unless an option of the question offered it)
    if m.get(RETIRED) is True:
        if not retired(item):
            m.pop(RETIRED)                   # a step recorded under it is open again: this write retires nothing (whatever else closed in it was not what the draft served)
        return
    was, now = his_open(before), his_open(item)
    m[CLOSED] = sorted(_keys(m.get(CLOSED)) | (was - now))
    if was and not was & now and (not _waits(item) or _all_ticked(was, before, item)):
        m[RETIRED] = True


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


def problem(item: dict[str, Any], saved: dict[str, Any] | None = None) -> str:
    """Why the item, as a write leaves it, is refused ("" = fine): it is the owner's step, the step names text to post, send or paste, and the item has no draft and its step and
    description link no document. One line that names the field and the link alternative. `saved` is the item as the save will leave it, its own retiring of the draft included (None: `item` as it is)."""
    saved = item if saved is None else saved
    if not owner_steps(item):
        return ""
    step = (item.get("metadata") or {}).get("step")
    hit = names_text(step)
    if not hit or of(saved) or has_link(step, item.get("description")):
        return ""
    old = " (the draft the item holds is retired, its step closed: pass draft= with the text for this one)" if retired(saved) else ""
    return (f"the step asks {_model.owner_display()} to post, send or paste a text (\"{hit}\"), so put the text in draft=<the text exactly as it is to be pasted> (his item page shows it in a block with a Copy button), "
            "or link the document that holds it in the step or description (an https:// link to a doc; a GitHub issue or PR link does not count)" + old)


def question(item: dict[str, Any]) -> tuple[Any, Any, bool]:
    """The decision an item asks, as a write can change it: the ask, the options, and whether its needs hold a decision."""
    m = item.get("metadata") or {}
    return m.get("ask"), m.get("options"), _asks_decision(m)


def offer_problem(item: dict[str, Any], saved: dict[str, Any]) -> str:
    """Why a write that asks or rewords a decision is refused ("" = fine): an option's label offers to post, send or paste a text while the draft the item holds is retired as the save will leave it
    (`saved`), so his page would make the offer with no text, and the ask and description link no document."""
    m = item.get("metadata") or {}
    if item.get("status") == "completed" or not _asks_decision(m) or not retired(saved):
        return ""
    hit = _offer(m)
    if not hit or has_link(m.get("ask"), item.get("description")):
        return ""
    return (f"the options offer {_model.owner_display()} a text to post, send or paste (\"{hit}\") and the draft the item holds is retired, its step closed, so his page would show none: pass draft=<the text> with this question "
            "(get prints one kept for sending), link the document that holds it in the ask or description, or pass clear_draft=true when the question is about no text")
