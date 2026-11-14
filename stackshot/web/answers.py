"""answers.py: the helpers of the board's answer form: the form's limits and lock (`_ANSWER_TEXT_MAX`, `_ANSWER_BODY_MAX`, `_ANSWER_ESCALATE_S`, `_ANSWER_LOCK`), its token and its
same-origin check (`_answer_token`, `_origin_of`, `_answer_same_origin`), the lettered options of a pick (`_split_letter`, `_option_forms`), an answer's words and its stored note (`_choice_words`, `_answer_words`, `_answer_note`) and the file the
pending answers are kept in (`_answers_path`, `_answers_load`, `_answers_save`).

The module needs nothing of server.py (a module here cannot import it, and it runs as `__main__`): it reads the config, the renderer, the option labels, the item
states, the instance settings (`core/instance.py`) and the sign-in key (`auth/signin.py`). server.py reads nothing from here: the answer path (service/answer.py, through the save hooks and web/wiring.py), the routes (`routes/answers.py`, `routes/board_pages.py`, `routes/ui_api.py`) and the tools (`tools/get.py`) import this module, and the suites and scripts read and set every name on it.
`_ANSWER_LOCK` is taken only by the answer path of service/answer.py (`_answer_ack`, `_answer` and `_answer_tick`), nothing here takes it: it reads it on this module each time (`answers._ANSWER_LOCK`, through the `answers_mod` hook),
so the suite that puts a spy in its place sets it here."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from starlette.requests import Request

from stackshot.core import config as _cfg
from stackshot.model import option_labels as _option_labels
from stackshot.model import states as _states
from stackshot.web import render as _rmod
from stackshot.core import instance as _inst
from stackshot.web.auth.signin import _ui_key


# ----------------------------------------------------------------------------- the owner answers an item from its page
# The owner enters his input (usually his decision on the ASK) on the item directly from the UI: a few buttons, a button each for every proposed choice or option, or a comment; the design
# (the design doc, "Proposal" and "Revised proposal"). The item page of an open
# item carries a form (render.Board.item_html): a button per stored option while it needs his
# decision (none when the owner listed none: Yes / No and the box, the fallback for a yes/no ask or an older item; Approve and Decline are options like any other), and a comment box sent as his answer or as a comment. POST /items/<n>/answer takes it, signed-in only (the board's
# cookie, _ui_email) with a token bound to his address and the item and a same-origin Origin or Referer. An answer is stored in
# metadata.answers ({ts, kind: decision | comment, choice?, choice_line?, letter? (the answer box's A, B, C beside the label), text?, via: "board"}); a decision takes `decision` out of needs (the
# sessions named stay) and clears the ask, so the item leaves his queue at once, and moves the state clock; a decision that is a pick
# among the item's options also clears the options (his answer keeps the option's label and line); a comment changes
# neither. Either is pushed to the owner and to every session named in needs, and shows in the History as his
# (the author `the owner · board` is one only the server writes, _sender_not_owner; nothing is posted to the issue since an earlier change). A decision
# nobody it was sent to has acted on (a write to the item) within _ANSWER_ESCALATE_S goes to the project's keeper once.
_ANSWER_TEXT_MAX = 4000                 # characters of the comment box; a longer one is refused, not cut
_ANSWER_BODY_MAX = 64 * 1024            # bytes of the form body read at all
_ANSWER_ESCALATE_S = 1800.0             # 30 min: a decision answer the owner has not written to the item after → the project's keeper
_ANSWER_LOCK = threading.RLock()     # re-entrant: _answer saves (its own save names no writer, but a hook may)


def _answer_token(email: str, gid: str) -> str:
    """The answer form's token: an HMAC, with the board's cookie key (<secrets>/ui-session.key), over the signed-in address and
    the item's store id. A form rendered for one item or one person does not answer another."""
    import hashlib, hmac
    return hmac.new(_ui_key(), f"answer\x00{email}\x00{gid}".encode(), hashlib.sha256).hexdigest()


def _origin_of(url: str) -> str:
    from urllib.parse import urlsplit
    try:
        p = urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    return f"{p.scheme}://{p.netloc}".lower() if p.scheme and p.netloc else ""


def _answer_same_origin(request: Request) -> bool:
    """The POST came from the board's own pages: its Origin (else, when a browser sent none, its Referer) is the board's
    address ([auth] base_url or [instance] board_url). Neither header, or "null", is refused."""
    allowed = {o for o in (_origin_of(_cfg.get("auth", "base_url")), _origin_of(_inst.BOARD_URL)) if o}
    got = str(request.headers.get("origin") or "").strip()
    if got:
        return got != "null" and _origin_of(got) in allowed
    return _origin_of(request.headers.get("referer") or "") in allowed


_LETTERED_CHOICE = re.compile(r"([A-Z]) · (.+)", re.S)


def _split_letter(item: dict[str, Any], choice: str) -> tuple[str, str]:
    """(label, letter) for the `choice` a form posted. The answer box of the board letters a question's options A, B, C when it has three or more, by their place in the order the owner
    stored them (the order a session writes its ask in: "Recommend: B, …"), and posts "B · <label>"; every other form posts the bare label. The lettered form is tried first: a
    "<letter> · <label>" whose letter is the label's stored place among three or more options gives (label, letter), so an option whose label is itself "B · X" cannot capture
    the card for "X" at place B. Otherwise a choice that is one of the stored labels (or Yes/No) comes back as it is with no letter, and anything else unchanged, for the caller's stale check.
    An option whose stored label repeats its own letter ("A Report", all of a card's labels in order: option_labels.strip_letters) is drawn without it, so the label a pick may name at a place is the
    shown one or the stored one (a page loaded before the change still posts "A · A Report"); a label that was only its letter is posted as that letter alone, and the pick is stored under the label as stored."""
    forms = _option_forms(item)
    m = _LETTERED_CHOICE.fullmatch(choice)
    if m and len(forms) >= 3 and ord(m[1]) - 65 < len(forms) and m[2] in forms[ord(m[1]) - 65][1:]:
        return forms[ord(m[1]) - 65][0], m[1]
    if len(forms) >= 3 and len(choice) == 1 and choice.isascii() and choice.isalpha() and ord(choice.upper()) - 65 < len(forms) and not forms[ord(choice.upper()) - 65][1]:
        return forms[ord(choice.upper()) - 65][0], choice.upper()      # the card of a label that was only its letter posts the letter (ASCII only: "ß".upper() is two characters)
    for name, shown, raw in (forms if choice else []):
        if choice in (shown, raw):
            return name, ""
    return choice, ""


def _option_forms(item: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Per stored option, in the stored order: (the name a pick is stored under, the label as the card shows it, the label as stored). [] when the item has no readable options."""
    shown, raw = _rmod.options_of(item), _rmod.options_of(item, raw=True)
    return list(zip(_option_labels.pick_names([o["label"] for o in raw], [o["label"] for o in shown]), [o["label"] for o in shown], [o["label"] for o in raw]))


def _choice_words(rec: dict[str, Any]) -> str:
    """The option an answer picked as a person reads it: "B · <label>" when the box lettered it, the letter alone when the option was only its letter, else the label."""
    return _option_labels.pick_words(str(rec.get("choice") or ""), str(rec.get("letter") or ""))


def _answer_words(rec: dict[str, Any], limit: int = 600) -> str:
    """An answer in one line for a notice: "<choice> — <text>", the text's line breaks as " / ", cut at `limit`."""
    text = " / ".join(ln.strip() for ln in str(rec.get("text") or "").splitlines() if ln.strip())
    if len(text) > limit:
        text = text[:limit].rstrip() + " … (the whole text is on the item's page)"
    choice = _choice_words(rec)
    return f"{choice} — {text}" if choice and text else choice or text


def _answer_note(rec: dict[str, Any]) -> str:
    """The line a board answer is stored under on the item (`metadata.answers` and the History); since an earlier change it is no longer posted to the issue."""
    text = str(rec.get("text") or "").strip()
    if rec.get("kind") == "comment":
        return "comment:\n\n" + text
    step = _states.clean(rec.get("step"))
    if rec.get("kind") == "step-reply":
        return "note on his step:" + (f"\n\nthe step: {step}" if step else "") + "\n\n" + text
    return "answer: " + (f"**{_choice_words(rec)}**" if rec.get("choice") else "") + (f"\n\nthe step he did: {step}" if step else "") + ("\n\n" + text if text else "")


def _answers_path() -> Path:
    return _cfg.state("answers.json")


def _answers_load() -> dict[str, dict[str, Any]]:
    try:
        d = json.loads(_answers_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _answers_save(d: dict[str, dict[str, Any]]) -> None:
    p = _answers_path(); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp"); tmp.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8"); os.replace(tmp, p)
