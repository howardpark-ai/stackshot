"""sibling_words.py — a front agent's message to a sibling front agent of its project that quotes the owner's words.

A message to a front agent that carries a need of the owner (the mark, or the words of the router's own signals) starts a turn only when he is
talking with that agent now or asked it to tell him about the subject (service/front_turn.py); otherwise the gate refuses it, naming the item's
builder, and the router passes it to that builder or archives it. When the sender is a live front agent of the same project as the addressee and
the message quotes the owner's words, checked as the wake cap checks them, the message is held for the addressee's next turn instead: a held
line starts no turn. Without such words nothing changes.

The words are a line of the message in the form of an Acked-by trailer:

    Acked-by: "his sentences, cut verbatim" (the time he said it, session <the session that heard him>)

The quote is looked up the way a plain `said` is (service/gates.gate_said): his own message found in the transcript of that session (the sender's
own when the line names none), and read through `gates.sibling_quote`, which is the wake cap's own reader (waiting.owner_words): a checked Acked-by
no older than [waiting] cap_days. The time in the line is for the reader; the age is that of the message in the transcript. No second checker.
Pure of the message tool and the router: both call `held_words` at one place each."""
from __future__ import annotations

import re

from stackshot.anchors import anchors as _anc
from stackshot.fleet import sessions_registry as _sr
from stackshot.service import gates as _gates

_LINE = re.compile(r"^[ \t>*-]*Acked-by:[ \t]*[\"“]([^\"”\n]{3,}?)[\"”](?P<rest>[^\n]*)$", re.M | re.I)
_SESSION = re.compile(r"\bsession[ \t:=]+([A-Za-z0-9][\w.\-]{1,80})", re.I)


def quoted(text: str) -> tuple[str, str]:
    """The quote of the first Acked-by line of `text` and the session it names ("" when it names none): ("", "") when no line has the form."""
    m = _LINE.search(str(text or ""))
    if not m:
        return "", ""
    s = _SESSION.search(m.group("rest") or "")
    return m.group(1).strip(), (s.group(1) if s else "")


def held_words(sender: str, to: str, text: str) -> str:
    """The owner's words (one sentence of them) that let `sender`'s message `text` to `to` be held for the addressee's next turn, or "": `sender` and `to` must be two distinct live front agents of one project
    (gates._front_sibling), and the message must carry an Acked-by line whose quote is found in the transcript and passes the wake cap's reader. "" for any other sender or addressee, a message with no such line,
    words that fail the check, and any failure of the lookups: the message takes the path it took before."""
    try:
        quote, sess = quoted(text)
        if not quote or not str(sender or "").strip():
            return ""
        roles = _anc.session_roles()
        name = _sr._role_name(roles, to, "")
        if not name or roles[name].get("role") != "front":
            return ""
        if not _gates._front_sibling(sender, name, str(roles[name].get("project") or "")):
            return ""
        return _gates.sibling_quote(_gates.lazy_said(quote, sess or str(sender).strip())())
    except Exception:  # noqa: BLE001  — an extra rule: a failure leaves the path as it was
        return ""
