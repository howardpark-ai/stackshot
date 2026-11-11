"""similar.py: the create reply's similar-items note: `_similar_note` (the reply line naming up to `_SIMILAR_MAX` existing items that look like the new one, "" on any failure), with the score it ranks by
(`_similar_score`), the subject's words it compares (`_subject_words`) and the constants they read (`_SIMILAR_DAYS`, `_SIMILAR_MIN`, `_SIMILAR_MAX`, `_SIMILAR_STOP`).

server.py is being split into one module per area (CONTRIBUTING.md, Layout). The module needs nothing of server.py (a module here cannot import it, and it runs as `__main__`): it reads the config, the anchors
registry, the item-project reader, the GitHub id switch and the store's file list (`store.py`). server.py imports `_similar_note` back at the old position, where the create tool calls it, and `_subject_words` and
`_similar_score`, which `tests/similar_scenario.py` reads as `server.<name>`. The four constants no caller on server reads stay in this module."""
from __future__ import annotations

import json
import re
import time

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.github import ghsync as _gh
from stackshot.model import item_project as _ip
from stackshot.core.store import _item_files


# A create's reply lists the existing items closest to the new one (a create once duplicated an open item): a note, never a block.
# One pass over the store, no network, no model. A candidate is an open item or one completed within _SIMILAR_DAYS days; its score is
# the Dice overlap of the subjects' words (lowercased, the [scope] prefix, short and filler words dropped, a plural folded)
# plus a bonus for the same project page (+0.10) or the same hub (+0.05). Shown at _SIMILAR_MIN and above, and only when at least
# two words are shared (or both subjects are the same one word), so a lone common word never matches: 0.55 is four shared words
# of seven, or two of four with the project bonus, while an unrelated subject in the same project stays near 0.2-0.3.
_SIMILAR_DAYS = 14
_SIMILAR_MIN = 0.55
_SIMILAR_MAX = 3
_SIMILAR_STOP = frozenset("the and for with from into that this when then than not are was were has have its our your new add fix make use via per all any can will should "
                          "one two who how what why where which item board get set pick hold date result check".split())


def _subject_words(subject: str) -> frozenset[str]:
    s = str(subject or "").lower().strip()
    for p in _cfg.CFG["subject"]["prefixes"]:
        if s.startswith(p.lower().strip()):
            s = s[len(p.strip()):]
            break
    out = set()
    for w in re.findall(r"\w+", s):
        if w.isascii() and len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]                     # a plural folds into its singular
        if w in _SIMILAR_STOP or (w.isascii() and len(w) <= 2):
            continue
        out.add(w)
    return frozenset(out)


def _similar_score(a: frozenset[str], b: frozenset[str], same_project: bool, same_hub: bool) -> float:
    shared = len(a & b)
    if not shared or (shared < 2 and a != b):
        return 0.0
    return 2 * shared / (len(a) + len(b)) + (0.10 if same_project else 0.05 if same_hub else 0.0)


def _similar_note(gid: str, subject: str, project: str) -> str:
    """The reply line for a create naming up to _SIMILAR_MAX existing items that look like the new one; "" when none passes."""
    try:
        words = _subject_words(subject)
        if not words:
            return ""
        try:
            reg = _anc.registry()
            hub_of = lambda p: _anc.hub_of(p, reg)
        except Exception:
            hub_of = lambda p: p
        mine_hub, now, rows = hub_of(project), time.time(), []
        for g, p in _item_files():
            if g == gid:
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    it = json.load(f)
            except Exception:
                continue
            if not isinstance(it, dict):
                continue
            status = str(it.get("status") or "")
            if status != "open":
                try:
                    closed = float(it.get("state_updated") or it.get("updated") or 0)
                except (TypeError, ValueError):
                    closed = 0.0
                if status != "completed" or not closed or now - closed > _SIMILAR_DAYS * 86400:
                    continue
            other = _ip.key_of(it.get("metadata") or {})
            score = _similar_score(words, _subject_words(str(it.get("subject") or "")), bool(project) and other == project, bool(other) and hub_of(other) == mine_hub)
            if score >= _SIMILAR_MIN - 1e-9:      # a float sum may land a hair under the bound it equals
                rows.append((score, int(g[1:]) if g[1:].isdigit() else 0, g, str(it.get("subject") or ""), status))
        rows.sort(key=lambda r: (-r[0], -r[1]))
        if not rows:
            return ""
        shown = ", ".join(f'{_gh.shown(g)} "{" ".join(sub.split())[:90]}" [{"open" if st == "open" else "completed"}]' for _s, _n, g, sub, st in rows[:_SIMILAR_MAX])
        return f"\n(similar items, check before working this one: {shown}; if one already carries this, update it and close the new one as superseded)"
    except Exception:
        return ""                          # a note only: the create stands
