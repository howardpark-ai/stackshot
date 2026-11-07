"""What a cloud session is called and where it opens.

A `cse_…` owner is either a cloud Code / Cowork session, whose claude.ai title is its name, or the cloud workspace claude.ai
attaches to a regular chat that runs tools ("Claude.ai E1 upgraded conversation", tag `bard-conversation:<chat uuid>`):
that one opens as the chat, and its name stays the one the session gave (owner_name) — the chat's own title is not read.
The lookup is the Claude Code CLI's own (its `ccr:list`): GET https://api.anthropic.com/v1/code/sessions/<id> with the
claude.ai login token the CLI keeps in paths.claude_credentials (the server box; read on each call because the CLI refreshes
it; never logged). Results are cached for TTL seconds in <state>/cloud-sessions.json; a failed lookup keeps the last answer,
or none, and the board falls back to owner_name and the Code-session link.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

import config as _cfg  # noqa: E402

CACHE: Path = _cfg.state("cloud-sessions.json")
CREDS: Path = _cfg.path("paths", "claude_credentials")
TTL = 600          # s
_mem: dict[str, dict[str, Any]] | None = None


def _load() -> dict[str, dict[str, Any]]:
    global _mem
    if _mem is None:
        try: _mem = json.load(open(CACHE, encoding="utf-8"))
        except Exception: _mem = {}
    return _mem


def _fetch(cse: str) -> dict[str, Any] | None:
    try:
        tok = json.load(open(CREDS, encoding="utf-8"))["claudeAiOauth"]["accessToken"]
        req = urllib.request.Request(f"https://api.anthropic.com/v1/code/sessions/{cse}",
                                     headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json", "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=10) as r:
            rs = json.load(r).get("response_shape") or {}
    except Exception:
        return None
    chat = next((t.split(":", 1)[1] for t in rs.get("tags") or [] if t.startswith("bard-conversation:")), "")
    return {"title": "" if chat else (rs.get("title") or ""), "chat": chat, "status": rs.get("status") or "", "at": time.time()}


def info(cse: str) -> dict[str, Any]:
    """{title, url, chat, status} for a cse_… id; title is '' for a chat (its own title is not read)."""
    c = _load()
    e = c.get(cse)
    if not e or time.time() - float(e.get("at", 0)) > TTL:
        f = _fetch(cse)
        if f:
            c[cse] = e = f
            try:
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                tmp = CACHE.with_suffix(".tmp"); json.dump(c, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1); os.replace(tmp, CACHE)
            except Exception:
                pass
    e = e or {}
    url = f"https://claude.ai/chat/{e['chat']}" if e.get("chat") else "https://claude.ai/code/session_" + cse[4:]
    return {"title": e.get("title", ""), "url": url, "chat": bool(e.get("chat")), "status": e.get("status", "")}
