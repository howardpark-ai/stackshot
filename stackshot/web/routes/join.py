"""join.py (web/routes): the setup page an invite's link names, `GET /join` (`invites.PAGE_PATH`): how an AI agent, or the person, adds the board's MCP connection.

Anyone may read it, signed in or not, so it holds nothing but the connector's address from the config and the same words for everyone: no secret, no member, no
item, no board name. The one thing that depends on the request is the language (a signed-in reader's own; a query string changes nothing), so it says nothing
about whether an address is registered. It reads no store and writes nothing. Requests are limited per source (`caller_pass._source`) and over all of them. The route
is there only on a board that can invite ([invites], core/invites.py). Every text is escaped as it is put in; the page carries no script and loads nothing."""
from __future__ import annotations

import html

from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response

from stackshot.core import invites as _invites
from stackshot.service.caller_pass import RateLimit, _source
from stackshot.web import i18n as _i18n

# The address is the connection's as uvicorn gives it (`request.client`): the peer, or the client the loopback proxy in front of the server names in X-Forwarded-For.
# `_source` counts it as the client API's limits do (an IPv6 address by its /64).
PER_SOURCE = RateLimit(60, 60)       # pages one source reads a minute
CEILING = RateLimit(600, 60)         # ...and all of them together

_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_STYLE = ("body{margin:0 auto;max-width:42rem;padding:1.25rem;font:16px/1.55 system-ui,-apple-system,sans-serif}"
          "h1{font-size:1.35rem}h2{font-size:1.05rem;margin-top:1.5rem}"
          "pre{white-space:pre-wrap;overflow-wrap:anywhere;border:1px solid #8886;border-radius:6px;padding:.6rem .75rem}"
          "p,li{overflow-wrap:anywhere}@media(prefers-color-scheme:dark){body{background:#16171a;color:#e6e6e6}}")


def _p(key: str, **fields: str) -> str:
    return f"<p>{html.escape(_i18n.t(key, **fields))}</p>"


def _code(text: str) -> str:
    return f"<pre><code>{html.escape(text)}</code></pre>"


def _app(name: str, *parts: str) -> str:
    return f"<h2>{html.escape(name)}</h2>" + "".join(parts)


def page(url: str) -> str:
    """The page for the connector address `url`, in the request's language."""
    title = html.escape(_i18n.t("join.title"))
    steps = "".join(f"<li>{html.escape(_i18n.t(k))}</li>" for k in ("join.step.add", "join.step.sign_in", "join.step.start"))
    body = "".join((
        f"<h1>{title}</h1>",
        _p("join.who"),
        _p("join.address"),
        _code(url),
        f"<ol>{steps}</ol>",
        _app("claude.ai", _p("join.claude_ai"), _p("join.claude_ai.plans")),
        _app("Claude Code", _p("join.claude_code.add"), _code(f"claude mcp add --transport http board {url}"), _p("join.claude_code.sign_in"),
             _code("claude mcp login board")),
        _app("ChatGPT", _p("join.chatgpt"), _p("join.chatgpt.plans")),
        _app("Cursor", _p("join.cursor"), _code('{\n  "mcpServers": {\n    "board": { "url": "' + url + '" }\n  }\n}')),
        f"<h2>{html.escape(_i18n.t('join.refused.title'))}</h2>",
        _p("join.refused"),
    ))
    return (f'<!doctype html><html lang="{html.escape(_i18n.current())}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>{title}</title><style>{_STYLE}</style></head><body>{body}</body></html>')


async def join(request: Request) -> Response:
    source = _source(request.client.host if request.client else "")
    wait = PER_SOURCE.allow(source) or CEILING.allow()
    if wait:
        return PlainTextResponse(_i18n.t("join.busy"), status_code=429, headers={**_HEADERS, "Retry-After": str(int(wait) + 1)})
    s = _invites.settings()
    if not s.on:
        return PlainTextResponse("not found", status_code=404, headers=_HEADERS)
    return HTMLResponse(page(s.mcp_url), headers=_HEADERS)


def register(mcp) -> None:
    """Add the page on a board that can invite people; otherwise the board has no such route."""
    if _invites.settings().on:
        mcp.custom_route(_invites.PAGE_PATH, methods=["GET"])(join)
