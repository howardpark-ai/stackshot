"""canvas.py (web/ui): the shell a canvas is read in (docs/canvas.md): one bar (the way back to the board, the canvas's number and title, its item, its versions) and the page in a sandboxed frame.

The shell is the board's own page and runs no script (its policy, web/canvas_guard.py, allows none): the versions are a <details> list of links, so switching version loads a new shell and the frame never
has to ask for anything itself. Nothing of the canvas is written into the shell but its title, escaped; the page is only ever the frame's address, so the bar is never part of what is stored and a
later reader of the bare page (…/raw) gets none of it. The frame's `sandbox` is `allow-scripts` and nothing else: no same origin, no forms, no popups, no moving the window.
"""
from __future__ import annotations

import html
from typing import Any

from stackshot.core import config as _cfg
from stackshot.github import ghsync as _gh
from stackshot.service import canvas as _canvas
from stackshot.web import i18n as _i18n
from stackshot.web.ui import under

_CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{display:flex;flex-direction:column;height:100dvh;font:15px/1.35 system-ui,sans-serif;background:Canvas;color:CanvasText}
header{display:flex;flex-wrap:wrap;align-items:center;gap:0 6px;padding:0 8px;border-bottom:1px solid GrayText}
header a,summary{display:inline-flex;align-items:center;justify-content:center;min-height:44px;min-width:44px;padding:0 8px;color:LinkText}
.cv-name{flex:1 1 8em;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
details{position:relative}
summary{cursor:pointer;list-style:none;color:CanvasText}
summary::-webkit-details-marker{display:none}
ul{position:absolute;right:0;top:100%;z-index:1;margin:0;padding:4px 0;list-style:none;max-height:70vh;overflow:auto;background:Canvas;border:1px solid GrayText;border-radius:8px;white-space:nowrap}
li a{display:flex;justify-content:flex-start;padding:0 16px}
li a[aria-current]{font-weight:600}
iframe{flex:1 1 auto;width:100%;min-height:0;border:0;background:#fff}
"""
_CLOCK = ('<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
          '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg>')


def _esc(x: Any) -> str:
    return html.escape(str(x), quote=True)


def address(number: int, version: str | None = None) -> str:
    """The path of a canvas, or of one of its versions."""
    return under(f"{_canvas.PATH}/{number}" + (f"/versions/{version}" if version else ""))


def shell(rec: dict[str, Any], version: str | None) -> str:
    """The shell of canvas `rec`, on its current page or on `version`, in the request's language."""
    t, lang = _i18n.t, _i18n.current()
    number = rec["number"]
    name = t("canvas.name", n=number)
    title = name + (f" · {rec['title']}" if rec["title"] else "")
    bar = [f'<a href="{_esc(under("/"))}">&#8249; {_esc(t("canvas.board"))}</a><span class="cv-name">{_esc(title)}</span>']
    if rec["item"]:
        bar.append(f'<a href="{_esc(under("/items/" + _gh.href_id(rec["item"])))}">{_esc(_gh.shown(rec["item"]))}</a>')
    if version:
        bar.append(f'<a href="{_esc(address(number))}">{_esc(t("canvas.current"))}</a>')
    rows = []
    for v in sorted(rec["versions"], key=lambda x: x["id"], reverse=True):
        when = _i18n.fmt_date(_canvas.version_time(v["id"]).astimezone(_cfg.tz()))
        here = ' aria-current="page"' if v["id"] == version else ""
        rows.append(f'<li><a href="{_esc(address(number, v["id"]))}"{here}>{_esc(t("canvas.until", when=when))}</a></li>')
    if rows:
        label = _esc(t("canvas.versions"))
        bar.append(f'<details><summary aria-label="{label}" title="{label}">{_CLOCK}</summary><ul>{"".join(rows)}</ul></details>')
    return (f'<!doctype html><html lang="{_esc(lang)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
            f'<title>{_esc(title)}</title><link rel="icon" href="{_esc(under("/favicon.svg"))}" type="image/svg+xml"><style>{_CSS}</style></head><body><header>{"".join(bar)}</header>'
            f'<iframe sandbox="allow-scripts" src="{_esc(address(number, version) + "/raw")}" title="{_esc(name)}"></iframe></body></html>')
