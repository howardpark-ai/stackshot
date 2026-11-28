"""title_label.py: the leading tag an older title still carries ("[work] Fix the export"), hidden wherever a title is shown.

An item's group (its scope) comes from its project, never from its title: no write asks for a tag and none adds one. A title stored with a tag (an open item not yet cleaned up, a
closed record kept as it was) stays as stored; the one function here, `bare`, is what every screen and every text rendering shows in its place. The tags it knows are the instance's
[subject] prefixes (when the setting is there) and `[<scope>] ` for each name in [project_scopes] order, so an instance that dropped the setting still hides the tags it used.
Nothing here writes or changes a stored title."""
from __future__ import annotations

import re

from stackshot.core import config as _cfg


_SEP = re.compile(r"^[-\u2013\u2014:]\s+")      # a dash (hyphen, en or em) or colon standing alone after a tag


def prefixes() -> list[str]:
    """The tags a stored title may still open with, each as written with its trailing space: [subject] prefixes, then `[<scope>] ` for every scope of [project_scopes] order not already there."""
    out = [str(p) for p in (_cfg.get("subject", "prefixes") or []) if str(p).strip()]
    for sc in (_cfg.get("project_scopes", "order") or []):
        p = f"[{sc}] "
        if str(sc).strip() and p not in out:
            out.append(p)
    return out


def bare(title, or_blank: bool = False) -> str:
    """The title as screens show it: every leading tag of `prefixes()` taken off, matched with no care for case, for whitespace before it (an older title stored with "  [work] Fix" leads with a
    space before the tag) or how much whitespace follows it, none at all included ("[Work]Fix" for a configured "[work] "); stacked tags come off one at a time ("[work][home] Fix"), and a dash or colon that stands alone after them goes with them ("[work] - Fix" is "Fix"). A title
    that is only a tag (and, once stripped, only whitespace) is shown as stored, so a row is never empty — unless `or_blank`, which a write-time check reads instead: a title that is nothing
    a tag is then "" as much as one that was blank to start with, so the two are refused alike. The stored title is not touched."""
    orig = t = str(title or "")
    def _pat(p):
        bare_p = p.rstrip()
        # the no-space lookahead ("[Work]Fix", "[work][home] Fix") is only safe for a bracketed tag, which always ends in "]": a bracketless
        # configured prefix ("WIP ", no brackets) would otherwise match inside an ordinary word that happens to start with the same letters
        # ("Wipe the report" is not "WIP" + "e the report"), so a bracketless prefix still needs real whitespace (or the end of the string) after it.
        look = r"|(?=[A-Za-z0-9\[])" if bare_p.endswith("]") else ""
        return re.compile(r"^" + re.escape(bare_p) + r"(?:\s+" + look + r"|$)", re.IGNORECASE)
    pats = [_pat(p) for p in prefixes()]
    stripped = False
    while True:
        s = t.lstrip()
        m = next((m for m in (pat.match(s) for pat in pats) if m), None)
        if not m:
            break
        rest = s[m.end():]
        if not rest.strip():
            return "" if or_blank else orig   # a title that is nothing but one tag or several stacked ones is shown as stored (the whole original), never a partly-stripped remainder
        t, stripped = rest, True
    if stripped:
        # "[work] - Fix": the dash after a tag is the tag's own punctuation, taken off with it; only a dash or colon that stands alone before whitespace, so "[work] -5 degrees" keeps its minus
        rest = _SEP.sub("", t.lstrip(), count=1)
        if rest != t.lstrip():
            if not rest.strip():
                return "" if or_blank else orig
            t = rest
    return t
