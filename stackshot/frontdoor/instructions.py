"""instructions.py: the front door's own instructions text.

A proxy server forwards a backend's instructions only when its own are unset, and the front door has several backends, so it writes the text itself:

    <the preface of the config>

    You are on: <the caller's backends>. <one line on the board argument, when the caller is on a board>

    --- instructions of board a (verbatim) ---
    <the text board a gave when the front door connected to it>

    --- instructions of boards b, c (the same text, verbatim) ---
    ...

Each backend's text is read live from its own initialize reply, kept five minutes (a backend that does not answer is skipped and tried again at the next
request), and put in unchanged. A caller sees the backends it is a member of and no other; with no caller (the server's own start) the text is the preface.
"""
from __future__ import annotations

import asyncio
import time

from stackshot.frontdoor.backend import log
from stackshot.frontdoor.provider import Door

CACHE_SECONDS = 300.0


class Instructions:
    def __init__(self, door: Door):
        self.door = door
        self._cache: dict[str, tuple[float, str]] = {}

    async def _of(self, name: str, user: str) -> str | None:
        have = self._cache.get(name)
        if have and time.monotonic() - have[0] < CACHE_SECONDS:
            return have[1]
        try:
            async with self.door.backends.client(name, user) as c:
                text = (c.initialize_result.instructions or "") if c.initialize_result else ""
        except Exception as e:      # noqa: BLE001  (the backend is down or refuses: its text is left out this time)
            log.warning("instructions: %s '%s' did not answer (%s: %s)", self.door.backends.by_name[name].kind, name, type(e).__name__, str(e)[:160])
            return None
        self._cache[name] = (time.monotonic(), text)
        return text

    async def compose(self, user: str | None) -> str:
        """The instructions text for the caller `user` (None: no caller)."""
        d = self.door
        mine = d.backends_of(user) if user else []
        parts = [d.settings.preface]
        if mine:
            boards = d.boards_of(user)
            line = "You are on: " + ", ".join(f"{d.backends.by_name[n].kind} {n}" for n in mine) + "."
            if boards:
                line += " Every board tool takes an optional `board` argument naming the board the call is for; leave it out when you are on only one board."
            parts.append(line)
        texts = await asyncio.gather(*(self._of(n, user or "") for n in mine))
        groups: list[tuple[str, list[str]]] = []
        for n, t in zip(mine, texts):
            if not t:
                continue
            for g in groups:
                if g[0] == t:
                    g[1].append(n)
                    break
            else:
                groups.append((t, [n]))
        for text, names in groups:
            kinds = {d.backends.by_name[n].kind for n in names}
            word = (kinds.pop() if len(kinds) == 1 else "backend") + ("s" if len(names) > 1 else "")
            parts.append(f"--- instructions of {word} {', '.join(names)} ({'the same text, ' if len(names) > 1 else ''}verbatim) ---\n{text}")
        return "\n\n".join(parts)
