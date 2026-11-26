"""ask_ref.py — the reference of an item's open question, as the board's answer forms carry it (a pure module, no config and no store).

An answer form is drawn from the item as it stands then, and may be sent after a session has rewritten the question: an option keeps its label while the question under it is another. So the form
carries the reference of the question it shows, and the answer path (service/answer.py) compares it with the reference of the question that stands when the answer arrives.

The reference is read from what is stored, never from a drawn page, so the reader's language is no part of it. What counts:

  * whether `needs` holds a decision;
  * the ask line, and each stored option's label, line and recommended mark, in the stored order (three or more options are lettered by it), with whitespace collapsed;
  * the stored draft, character for character (the page shows it under the ask with its line breaks and spaces as written, and an option may send it);
  * the mockup link the page draws beside the question, wherever the item names it (the caller reads it: which link counts is the page's rule, ui/render.py `question_ref`).

Nothing else counts: not who wrote the ask or when (metadata.ask_rec), not any other field or time, not the order the metadata's keys are written in. Left out although a page shows them: the title,
the goal, the state line and the sidebar, the wait and woke lines, the Next list, the Background text apart from its mockup link, the History and comments, the draft's label, and what stands
behind any link. Left out as no card shows them: an option's stored `wake` and `date` (a date button names its date in its label).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

HEX = 32      # the length of a reference, in hex digits


def _words(x: Any) -> str:
    return " ".join(str(x or "").split())


def ref_of(meta: dict[str, Any], mockup: str) -> str:
    """The reference of the question `meta` (an item's metadata) holds now; `mockup` is the link its page draws beside the question, "" for none."""
    needs = meta.get("needs")
    needs = needs if isinstance(needs, list) else [needs]        # a list, or the one stored word of the older form
    options = meta.get("options") if isinstance(meta.get("options"), list) else []
    draft = meta.get("draft")
    asked = [any(_words(n).lower() == "decision" for n in needs), _words(meta.get("ask")),
             [[_words(o.get("label")), _words(o.get("line")), o.get("recommended") is True] if isinstance(o, dict) else _words(o) for o in options],
             draft if isinstance(draft, str) else "",      # as stored, never collapsed: a line break or a space is part of the text he sends
             mockup]
    return hashlib.sha256(json.dumps(asked, separators=(",", ":")).encode("ascii")).hexdigest()[:HEX]
