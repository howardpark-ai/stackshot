"""subagent_tie.py: which running subagent of a mover is at work on WHICH item: the hourly audit's proof that "a subagent is running on it" (audit/hourly.py).

A step status in progress (silence.subagent_running) is something the mover wrote: a claim, and one mover can carry it on several items while one subagent runs. The pane being busy is
the same sort of claim about the mover, not about an item. The audit therefore asks the subagent itself: the subagents a mover has running come from the fleet's session manager (audit/agent_state.py: its last
snapshot, `POST /client/agent-state`), each with its description and the first part of the brief its mover gave it. This module only ties them.

`tied(subagents, shown, keys)` says whether one of them is on an item: its description or its brief names the item (its shown id, `board` and `#` and its number, whole: item 12 is not item 123) or a pull request
anchored to the item (`keys`, "owner/repo#n", by its URL or by `PR n` / `#n`, as merge_tie names a pull request for an item that speaks of its repository). A subagent that names neither is on no item the
audit can tell. What that means for an item (audit/hourly.py): a subagent tied to another item leaves this one idle (part F, audit/hand_idle.py, hands it on); a running subagent tied to NONE of the mover's
items (a brief that names no item and no pull request yet, "Build part D") leaves the mover's items UNKNOWN, not idle, since any of them may be what it builds. So does anything that cannot be read: a mover whose state
the snapshot cannot give (`Unreadable`), a subagent entry the sender could not read (listed with no words).

Stdlib plus the repo's modules; reads no file."""
from __future__ import annotations

import re
from typing import Any, Iterable

from stackshot.model import merge_tie as _mt


class Unreadable(Exception):
    """The mover's subagents cannot be told from what the server holds (no fresh agent-state snapshot, an agent it does not name, a state it was not able to read). The audit reads it as UNKNOWN, never as nothing running."""


def _names_pr(text: str, key: str, bare: bool = True) -> bool:
    """Does `text` name the pull request `key` ("owner/repo#n"), and in the key's own repository? By its URL, or written out as `owner/repo#n`, always; by its number alone (`PR n`, `#n`) only when `bare` and the text names no pull
    request of the same number in another repository by URL (then the number is that one's): a bare number is the repository's of the item it is anchored to, never any repository's."""
    k = key.lower()
    repo, _, n = k.rpartition("#")
    if not (repo and n):
        return False
    if _mt.names(text, k):      # its URL (the number alone is not asked here)
        return True
    if re.search(r"(?<![\w./-])" + re.escape(k) + r"(?!\w)", text, re.I):      # `owner/repo#n` written out
        return True
    if not bare:
        return False
    if any(m.group(2) == n and m.group(1).lower() != repo for m in _mt.PR_URL.finditer(text)):
        return False      # the text gives this number's pull request by URL, in another repository
    return _mt.names(text, k, [repo])


def names_item(text: str, shown: str, keys: Iterable[str] = (), no_bare: Iterable[str] = ()) -> bool:
    """Does `text` name the item (its shown id, whole and in any case) or a pull request anchored to it (`keys`, "owner/repo#n")? A pull request is named by its URL or as `owner/repo#n`, and by `PR n` / `#n` (the
    item speaks of that repository: a pull request of it is anchored to the item) only in the item's own repository: a number whose URL in the text is in another repository is that repository's, and a key in `no_bare`
    (lower-case) is named by its URL or its full form alone."""
    t = str(text or "")
    if shown and re.search(r"(?<![\w#])" + re.escape(shown) + r"(?![\w])", t, re.I):
        return True
    off = {str(x).lower() for x in no_bare}
    return any(_names_pr(t, k, k.lower() not in off) for k in keys if k)


def _clashing(candidates: dict[str, tuple[str, Iterable[str]]]) -> set[str]:
    """The pull request keys (lower-case) of the candidates that share a number with a key of another repository: `PR 5` alone cannot say which of two repositories' pull request 5 a subagent means."""
    by_n: dict[str, set[str]] = {}
    for _shown, keys in candidates.values():
        for k in keys or ():
            if k:
                repo, _, n = str(k).lower().rpartition("#")
                by_n.setdefault(n, set()).add(repo)
    return {f"{repo}#{n}" for n, repos in by_n.items() if len(repos) > 1 for repo in repos}


def tied_to(sub: dict[str, Any], candidates: dict[str, tuple[str, Iterable[str]]]) -> set[str]:
    """The candidates ({id: (its shown id, its anchored pull requests)}) a running subagent is tied to: those its DESCRIPTION names; only when the description names none, those its brief names. A brief that merely mentions
    an item ("a follow-up of item X") must not tie the subagent to it when the description already says what it works on. A subagent given with a `text` alone (no `description` key) reads that text as its description.
    A pull request number written alone ties only when it is no other candidate's number in another repository (`_clashing`): two items anchored to `a/x#5` and `b/y#5` are told apart by the URL or `owner/repo#n` form."""
    desc = str(sub.get("description") if "description" in sub else sub.get("text") or "")
    clash = _clashing(candidates)
    for words in (desc, str(sub.get("brief") or "")):
        hit = {g for g, (shown, keys) in candidates.items() if names_item(words, shown, [k for k in keys if k], clash)}
        if hit:
            return hit
    return set()


def tied(subagents: Iterable[dict[str, Any]], shown: str, keys: Iterable[str] = ()) -> bool:
    """Is one of the running `subagents` (from `running`) at work on the item (by `tied_to` with the item as the only candidate): its description, else its brief, names the item or a pull request anchored to it."""
    return any(tied_to(s, {"": (shown, keys)}) for s in subagents or ())
