"""ui/search.py — the page half of search.py: the search box and the results page, with every address written through under() (the root).

The index (sync, rebuild, standby_index, the kinds) is search.py's. The rule and the page are this module's own.

The rule is the fleet tool's search: the query is lower-cased and split on white space ("quoted text" stays one unit), and every unit must appear, as a plain case-insensitive
substring, in the same entry. There is no word boundary: "redesign" finds "redesigned", and a quoted phrase must appear contiguously (search.query matches
the start of a word instead). search.words reads the query and search.find returns every row that holds all of it.

The page is the fleet tool's search page in the board's own rows: one list, newest first, of every kind (Item, History, Project, Session) under one set of filters, each with the number it adds.
  * When: 1 h, 6 h, 24 h, 3 days, 7 days, All, or Dates (From and To, in the board's zone). A search started from the box has the last 7 days (items live for weeks, so the fleet tool's 6 hours would hide most of them).
  * Kind: Items, History, Projects, Sessions. State: Open, Closed; it filters the items and their History, and leaves projects and sessions (which have no state) alone.
  * The number beside a box is what ticking it adds to the answer, the other filters as they stand: so a box says what it hides before it is ticked.
  * 25 rows show first and "Show 25 more" adds 25 (a link: the page needs no script to do it), up to CAP (200); beyond that the summary says the list was cut.
Everything is in the address (q, when, from, to, kind, state, n), so a reload, Back and a shared link open the same search; the form is a plain GET and the chips are its submit buttons. A small script
submits the form when a box or a date changes."""
from __future__ import annotations

import datetime
import html as H
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro
from stackshot.web import i18n as _i18n
from stackshot.web import search as _s
from stackshot.web.search import (KINDS, LIMIT, MAX_Q, MIN_CHARS, REQUEST_ITEMS, TITLES, _corrupt, building, query, rebuild, standby_index, sync, terms)   # noqa: F401  — query and terms stay importable from here
from stackshot.web.ui import under
from stackshot.web.ui import kit as _ui

PAGE = 25                  # rows shown first, and added by each "Show more"
CAP = 200                  # rows a search shows at most (the rest is said, not drawn)
WHEN = (("1h", "1 h", 3600), ("6h", "6 h", 6 * 3600), ("24h", "24 h", 24 * 3600), ("3d", "3 days", 3 * 86400), ("7d", "7 days", 7 * 86400))
DEFAULT_WHEN = "7d"        # a search started from the box
STATES = (("open", "Open"), ("closed", "Closed"))
ROW_KIND = {"item": "Item", "history": "History", "project": "Project", "session": "Session"}


# ----------------------------------------------------------------------------- the box and the results page
def esc(x: Any) -> str:
    return H.escape(str(x), quote=True)


CSS = """
.sbox{display:flex;align-items:stretch;gap:6px;margin:8px 0 4px;max-width:560px}.sbox input{flex:1;min-width:0;min-height:32px;box-sizing:border-box;padding:0 10px;border:1px solid var(--ibd,var(--mut));border-radius:8px;background:var(--ifill,var(--card));color:var(--fg);font:inherit;font-size:14px}
.sbox input::placeholder{color:var(--iph,var(--mut));opacity:1}.sbox input:focus-visible,.sbox button:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.sbox button{flex:none}
header.top .sbox{margin:6px 0 0}@media(max-width:600px){.sbox input{font-size:16px}header.top .sbox{max-width:none}}
.sres-note{color:var(--mut);margin:8px 0}
form.se-controls{display:grid;grid-template-columns:minmax(0,1fr);gap:10px;padding-bottom:12px;border-bottom:1px solid var(--line)}
.se-q{position:relative}.se-q svg{position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--mut);pointer-events:none}
.se-q input{display:block;width:100%;height:34px;padding:0 10px 0 32px;border:1px solid var(--ibd);border-radius:8px;background:var(--ifill);color:var(--fg);font:inherit;font-size:15px}
.se-q input::placeholder{color:var(--iph,var(--mut));opacity:1}.se-q input:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.se-row{display:flex;align-items:center;flex-wrap:wrap;gap:6px 14px;font-size:13px}
.se-row>b{flex:none;min-width:62px;color:var(--mut);font-weight:600}
.se-row label{display:inline-flex;align-items:center;gap:5px;cursor:pointer}
.se-row label small{color:var(--mut);font-size:12px;font-variant-numeric:tabular-nums}
.se-row input[type=checkbox]{margin:0;width:16px;height:16px;accent-color:var(--acc)}
.se-row input[type=datetime-local]{height:32px;padding:0 8px;border:1px solid var(--ibd);border-radius:8px;background:var(--ifill);color:var(--fg);font:inherit;font-size:13px}
.se-row input[type=datetime-local]:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.se-zone{color:var(--mut);font-size:12px}
.se-chip{font:inherit;font-size:13px;padding:3px 11px;border:1px solid var(--ibd);border-radius:999px;background:transparent;color:var(--mut);cursor:pointer;margin-right:-8px}
.se-chip:hover{background:color-mix(in srgb,var(--fg) 8%,transparent)}.se-chip:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.se-chip[aria-pressed=true]{background:var(--fg);border-color:var(--fg);color:var(--bg)}
.se-summary{padding:9px 2px;font-size:13px;color:var(--mut);border-bottom:1px solid var(--ibd)}.se-summary b{color:var(--fg);font-weight:600}
ul.ir-rows.se-hits{margin-top:12px}
span.ktag{display:inline-block;flex:none;font-size:12px;line-height:20px;font-weight:500;padding:0 6px;border-radius:4px;white-space:nowrap;vertical-align:1px;margin-right:2px;background:color-mix(in srgb,var(--fg) 9%,transparent);color:var(--fg)}
li.irow.srow .ir-det{color:var(--mut);font-size:13px;line-height:18px}
li.irow.srow .ir-det mark,.ir-link mark{background:rgba(217,178,0,.35);color:inherit;border-radius:2px;padding:0 1px}
a.se-more{display:block;width:100%;margin:8px 0 0;padding:10px;border:1px solid var(--ibd);border-radius:8px;background:transparent;color:var(--acc);font:inherit;font-size:15px;font-weight:600;text-align:center;text-decoration:none;cursor:pointer}
a.se-more:hover{background:color-mix(in srgb,var(--fg) 6%,transparent);text-decoration:none}a.se-more:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.ir-link{overflow-wrap:anywhere}
@media(max-width:600px){.se-row>b{min-width:100%}.se-chip{padding:7px 12px;margin-right:0}.se-q input{height:44px;font-size:16px}}
"""

_ICON = ('<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
         '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>')

# The hint in a search box: the full line on a wide window, a short one on a phone (a placeholder cannot change by a media query, and the full line is wider than the
# box on a phone, where the text is 16 px and the box 270 to 320 px, so the end of it was cut). The line changes at 480 px and under; without a script the full line stays.
HINT = "Search items, history, projects, sessions"
HINT_SHORT = "Search the board"
_HINT_JS = ("<script>(function(){var m=window.matchMedia&&matchMedia('(max-width:480px)');if(!m)return;function f(){var a=document.querySelectorAll('input[data-hint-short]');"
            "for(var i=0;i<a.length;i++)a[i].placeholder=m.matches?a[i].getAttribute('data-hint-short'):a[i].getAttribute('data-hint')}f();"
            "if(m.addEventListener)m.addEventListener('change',f)})()</script>")

# a change to a box or a date submits the form (the chips and the Enter key are the form's own); without a script the Apply button does it
_JS = ("<script>(function(){var f=document.getElementById('se-form');if(!f)return;f.addEventListener('change',function(e){"
       "if(e.target&&e.target.type==='search')return;if(f.requestSubmit)f.requestSubmit();else f.submit()})})()</script>")


def box(q: str = "", in_place: bool = False) -> str:
    """The search box, a plain GET form to /search: what every page's header draws (its style is in CSS, which Board._css carries).
    The form opens its results in a new tab (target="_blank", rel="noopener"), so the page the search started from stays as it was; no script is involved, so Enter and the button both do it.
    `in_place=True` is the Search page's own header box: there the results replace the page, so tabs do not pile up (the filters under it are a plain in-place form too).
    An installed app window has no tabs: head's script (render.py _APP_HEAD) sends a same-origin target="_blank" form's results to the window itself, as it does a link's."""
    tab = "" if in_place else ' target="_blank" rel="noopener"'
    hint, short = esc(_i18n.t("home.search.hint")), esc(_i18n.t("home.search.hint_short"))      # the words are the string table's (English: HINT, HINT_SHORT)
    return (f'<form class="sbox" action="{under("/search")}" method="get" role="search"{tab}><input type="search" name="q" value="{esc(str(q or "")[:MAX_Q])}" '
            f'placeholder="{hint}" data-hint="{hint}" data-hint-short="{short}" aria-label="{esc(_i18n.t("home.search.aria"))}" maxlength="{MAX_Q}" autocomplete="off" enterkeyhint="search">'
            f'<button type="submit" class="b ico" aria-label="{esc(_i18n.t("home.search.button"))}" title="{esc(_i18n.t("home.search.button"))}">{_ICON}</button></form>{_HINT_JS}')


def _hl(text: str, ws: list[str]) -> str:
    """A title as HTML with the typed words marked where they appear (the rule the query makes); escaped piece by piece."""
    text = str(text or "")
    if not ws:
        return esc(text)
    out, at = [], 0
    for m in _s.word_rx(ws).finditer(text):
        out.append(esc(text[at:m.start()]) + "<mark>" + esc(m.group(0)) + "</mark>")
        at = m.end()
    return "".join(out) + esc(text[at:])


def _mark(snip: str) -> str:
    """A snippet as HTML: escaped whole, then the match markers become <mark>. Nothing else of the text is markup."""
    return esc(snip).replace("\x02", "<mark>").replace("\x03", "</mark>")


# ----------------------------------------------------------------------------- what the address says
def _all(params: Any, name: str) -> list[str]:
    if params is None:
        return []
    if hasattr(params, "getlist"):
        return [str(v) for v in params.getlist(name)]
    v = params.get(name) if hasattr(params, "get") else None
    return [] if v is None else [str(x) for x in v] if isinstance(v, (list, tuple)) else [str(v)]


@dataclass
class Filters:
    """The search an address describes. What it leaves out is a search started from the box: the last 7 days, every kind, open and closed, the first 25."""
    when: str = DEFAULT_WHEN
    frm: str = ""                                            # Dates: From and To as the date pickers write them (`YYYY-MM-DDTHH:MM`), in the board's zone
    to: str = ""
    kinds: tuple[str, ...] = KINDS
    states: tuple[str, ...] = tuple(k for k, _ in STATES)
    n: int = PAGE                                            # rows shown


def parse(params: Any) -> Filters:
    """The filters of a request's parameters. `f=1` marks a submitted form: there an unticked box is absent from the address, so absent means off; without it every box is on.
    A chip is a submit button named `w` and wins over the hidden `when` the form carries."""
    f = Filters()
    when = (_all(params, "w") or _all(params, "when") or [""])[0]
    if when in {k for k, _, _ in WHEN} | {"all", "dates"}:
        f.when = when
    f.frm = (_all(params, "from") or [""])[0].strip()[:32]
    f.to = (_all(params, "to") or [""])[0].strip()[:32]
    if _all(params, "f"):
        f.kinds = tuple(k for k in KINDS if k in _all(params, "kind"))
        f.states = tuple(k for k, _ in STATES if k in _all(params, "state"))
    try:
        f.n = max(PAGE, min(CAP, int((_all(params, "n") or [PAGE])[0])))
    except ValueError:
        pass
    return f


_TS_LO = 86400.0                      # the earliest and latest moment a window can bound: a date outside is held to the edge, so that it can be shown in any zone
_TS_HI = 253402214400.0 - 2 * 86400   # (a margin short of the largest date there is)


def _pick(v: str, tz: datetime.tzinfo) -> float | None:
    """A moment a date picker wrote, read in the board's zone and held to what can be displayed; None for text that is no date."""
    try:
        d = datetime.datetime.fromisoformat(v)
    except ValueError:
        return None
    try:
        t = (d.replace(tzinfo=tz) if d.tzinfo is None else d).timestamp()
    except (OverflowError, OSError, ValueError):
        t = _TS_LO if d.year < 5000 else _TS_HI
    return min(max(t, _TS_LO), _TS_HI)


def _window(f: Filters, now: datetime.datetime) -> tuple[float | None, float | None, str, str]:
    """(since, until, the window in words, a problem in words) of a search: None is no bound."""
    if f.when == "all":
        return None, None, "all time", ""
    if f.when == "dates":
        if not f.frm:
            return None, None, "", "Pick a From date and time (the To is optional)."
        since, until = _pick(f.frm, now.tzinfo), _pick(f.to, now.tzinfo) if f.to else None
        if since is None or (f.to and until is None):
            return None, None, "", "That date is not one a search can use."
        d = lambda t: datetime.datetime.fromtimestamp(t, now.tzinfo).strftime("%Y-%m-%d %H:%M")
        return since, until, f"from {d(since)}" + (f" to {d(until)}" if until else ""), ""
    for k, label, secs in WHEN:
        if k == f.when:
            return now.timestamp() - secs, None, "last " + label, ""
    return None, None, "", ""


def _href(q: str, f: Filters, **over: Any) -> str:
    """The address of the search `f` describes (with `over` changed), as the form would write it."""
    g = Filters(**{**f.__dict__, **over})
    pairs: list[tuple[str, str]] = [("q", q), ("f", "1"), ("when", g.when)]
    if g.when == "dates":
        pairs += [("from", g.frm), ("to", g.to)]
    pairs += [("kind", k) for k in g.kinds] + [("state", k) for k in g.states]
    if g.n > PAGE:
        pairs.append(("n", str(g.n)))
    return under("/search") + "?" + urlencode(pairs)


# ----------------------------------------------------------------------------- the results page
def _hit_ts(board: Any, kind: str, x: dict[str, Any], r: dict[str, Any] | None) -> float:
    """The time a hit is ordered and windowed by: an item's last change, a History entry's own time, a project page's file time, a session's last sight."""
    if kind == "history":
        return float(x["ts"] or 0.0)
    if kind == "item":
        return r["_updated"].timestamp() if r else 0.0
    if kind == "project":
        return _s.page_mtime(x["key"])
    seen = (board.sess.get("name:" + x["key"]) or {}).get("seen")
    try:
        return datetime.datetime.fromisoformat(str(seen).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def results_html(board: Any, q: str, opts: Any = None) -> str:
    """The results page for `q` (drawn as the fleet tool's search page): the board's chrome, the query box and the When, Kind and State filters,
    the summary line, one newest-first list of rows and "Show 25 more". `opts` is the request's query parameters (see Filters). Escapes everything it draws."""
    from stackshot.web.ui import render as R
    q = " ".join(str(q or "").split())[:MAX_Q]
    f = parse(opts)
    ws = _s.words(q)
    wide = _s.unit_count(q) > _s.MAX_TERMS
    short = not wide and not _s.long_enough(ws)
    since, until, window_words, problem = _window(f, board.now)
    rebuilding = False
    found: list[dict[str, Any]] = []
    if _ro.is_read_only():
        try:
            standby_index(board)
        except Exception as e:  # noqa: BLE001  — a failing build still answers from what is indexed
            print(f"search: standby index failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        try:
            sync(board, max_items=REQUEST_ITEMS, history=False)     # a write is in the index before it answers; its History is the thread's (never a git read here)
        except Exception as e:  # noqa: BLE001  — a failing sync still answers from what is indexed
            if _corrupt(e):
                raise
            print(f"search: sync failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        if not short and not wide and not problem:
            found = _s.find(ws)
    except sqlite3.DatabaseError as e:
        if not _corrupt(e):
            raise
        rebuild(f"{e.__class__.__name__}: {e}")                     # the file is dropped and the thread builds it again
        rebuilding = True
    rows = {r["gid"]: r for r in board.rows}
    hits: list[dict[str, Any]] = []
    for x in found:
        kind, r = x["kind"], rows.get(x["key"])
        if kind in ("item", "history") and r is None:
            continue                                                # an item gone since it was indexed
        if kind == "project" and x["key"] not in board.proj:
            continue
        hits.append({**x, "r": r, "t": _hit_ts(board, kind, x, r), "closed": (r.get("status") == "completed") if kind in ("item", "history") else None})
    in_window = [h for h in hits if (since is None or h["t"] >= since) and (until is None or h["t"] <= until)]
    kind_ok = lambda h: h["kind"] in f.kinds
    state_ok = lambda h: h["closed"] is None or ("closed" if h["closed"] else "open") in f.states      # projects and sessions have no state: the State boxes leave them alone
    n_kind = {k: sum(1 for h in in_window if h["kind"] == k and state_ok(h)) for k in KINDS}
    n_state = {"open": sum(1 for h in in_window if h["closed"] is False and kind_ok(h)), "closed": sum(1 for h in in_window if h["closed"] is True and kind_ok(h))}
    chosen = sorted((h for h in in_window if kind_ok(h) and state_ok(h)), key=lambda h: (-h["t"], KINDS.index(h["kind"]), h["key"], h["sub"]))
    total = len(chosen)
    pool = chosen[:CAP]
    page_rows = pool[:f.n]
    snips = _s.snippets(ws, [h["rowid"] for h in page_rows if h["kind"] != "session"])
    state_of: dict[str, str] = {}
    lis = []
    for i, h in enumerate(page_rows):
        if h["r"] is not None and h["r"]["gid"] not in state_of:
            state_of[h["r"]["gid"]] = board.state_kind(h["r"])
        lis.append(_row(board, R, h, snips.get(h["rowid"], ""), ws, state_of, "se-new" if f.n > PAGE and i == f.n - PAGE else ""))
    left = len(pool) - len(page_rows)

    if rebuilding:
        note = "The search index is being rebuilt. Try again in a minute."
    elif wide:
        note = f"A search is at most {_s.MAX_TERMS} words; put a phrase in quotes to keep it as one."
    elif short:
        note = f'Type at least {MIN_CHARS} characters.' if not q else f'Type at least {MIN_CHARS} characters (letters or digits).'
    elif problem:
        note = problem
    else:
        n_s = "match" if total == 1 else "matches"
        note = (f'<b>{total} {n_s}</b> for “{esc(q)}” · newest first · {esc(window_words)} · times in {esc(_cfg.tz_abbr(board.now))}'
                + (f' · <b>cut at {CAP}</b>' if total > CAP else ""))
        if not total:
            note += " · No matches." + _empty_hint(hits, in_window, f, since is not None or until is not None, n_kind, n_state)
        if not _ro.is_read_only() and building():                   # a standby never reads History: "still being built" would never end
            note += " The index is still being built: older history may be missing for a few minutes."
        elif _ro.is_read_only():
            note += " This is a read-only standby copy: items, projects and sessions are searched, not item History."
    more = (f'<a class="se-more" id="se-more" href="{esc(_href(q, f, n=f.n + PAGE) + "#se-new")}">Show {min(PAGE, left)} more</a>' if left > 0 else "")
    results = f'<ul class="ir-rows se-hits">{"".join(lis)}</ul>' if lis else ""
    font_css = str(_cfg.get("instance", "font_css") or "")
    title = f"Search · {board.title}" if short else f"{q} · Search · {board.title}"
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow"><title>{esc(title)}</title>'
            f'<link rel="icon" href="{R.icon_href("favicon.svg")}" type="image/svg+xml">' + (f'<link rel="stylesheet" href="{esc(font_css)}">' if font_css else "")
            + R._THEME_HEAD + R._APP_HEAD + f'<style>{board._css()}</style></head>{R._PANEL_BODY}<div id="layout"><main id="top">{board.page_header(q=q, search_page=True)}'
            f'<h1>Search</h1>{_controls(q, f, board.now, n_kind, n_state)}<div class="se-summary" role="status">{note}</div>{results}{more}</main>'
            + board.panel_tail() + R._FAB_PAIR + R._THEME_JS + R._RELOAD_JS + R._TOTOP_JS + R._BFCACHE_JS + '</body></html>')


def _empty_hint(hits: list[dict[str, Any]], in_window: list[dict[str, Any]], f: Filters, bounded: bool, n_kind: dict[str, int], n_state: dict[str, int]) -> str:
    """What a search that found nothing can say: the matches the window leaves out, and the unticked boxes that hold some."""
    out = ""
    older = len(hits) - len(in_window)
    if bounded and older:
        out += f" {older} {'match is' if older == 1 else 'matches are'} outside this window: choose All."
    off = [f"{TITLES[k]} ({n_kind[k]})" for k in KINDS if k not in f.kinds and n_kind[k]] + [f"{lab} ({n_state[k]})" for k, lab in STATES if k not in f.states and n_state[k]]
    if off:
        out += " Unticked boxes hold more: " + ", ".join(off) + "."
    return out


def _controls(q: str, f: Filters, now: datetime.datetime, n_kind: dict[str, int], n_state: dict[str, int]) -> str:
    """The query box and the filters: one GET form. The first submit button is invisible so that Enter in the box searches again with the filters as they are; a chip is a submit button named `w`."""
    chips = "".join(f'<button type="submit" class="se-chip" name="w" value="{k}" aria-pressed="{"true" if f.when == k else "false"}">{lab}</button>' for k, lab, _ in WHEN)
    chips += "".join(f'<button type="submit" class="se-chip" name="w" value="{k}" aria-pressed="{"true" if f.when == k else "false"}">{lab}</button>' for k, lab in (("all", "All"), ("dates", "Dates")))
    dates = (f'<div class="se-row" role="group" aria-label="Dates"><b>Dates</b><label>From <input type="datetime-local" name="from" value="{esc(f.frm)}"></label>'
             f'<label>To <input type="datetime-local" name="to" value="{esc(f.to)}"></label><span class="se-zone">in {esc(_cfg.tz_abbr(now))}</span></div>') if f.when == "dates" else ""
    kinds = "".join(f'<label><input type="checkbox" name="kind" value="{k}"{" checked" if k in f.kinds else ""}> {TITLES[k]} <small>({n_kind[k]})</small></label>' for k in KINDS)
    states = "".join(f'<label><input type="checkbox" name="state" value="{k}"{" checked" if k in f.states else ""}> {lab} <small>({n_state[k]})</small></label>' for k, lab in STATES)
    return (f'<form class="se-controls" id="se-form" action="{under("/search")}" method="get" role="search" aria-label="Search filters">'
            f'<button type="submit" class="sr" tabindex="-1" aria-hidden="true">Search</button><input type="hidden" name="f" value="1"><input type="hidden" name="when" value="{esc(f.when)}">'
            f'<div class="se-q">{_ICON}<input id="se-query" type="search" name="q" value="{esc(q)}" maxlength="{MAX_Q}" placeholder="{HINT}" data-hint="{HINT}" data-hint-short="{HINT_SHORT}" aria-label="Search the board" '
            f'autocomplete="off" enterkeyhint="search" spellcheck="false"></div>'
            f'<div class="se-row" role="group" aria-label="When"><b>When</b>{chips}</div>{dates}'
            f'<div class="se-row" role="group" aria-label="Kind"><b>Kind</b>{kinds}</div>'
            f'<div class="se-row" role="group" aria-label="State"><b>State</b>{states}</div>'
            f'<noscript><button type="submit" class="b">Apply</button></noscript></form>{_JS}{_HINT_JS}')


def _row(board: Any, R: Any, h: dict[str, Any], snip: str, ws: list[str], state_of: dict[str, str], li_id: str) -> str:
    """One hit as a row: its kind label, the item's state tag where it has one, `#id title` (the typed words marked), how long ago it changed at the right, a who line, and the excerpt behind the guide line."""
    kind, r, x = h["kind"], h["r"], h
    kt = f'<span class="ktag">{ROW_KIND[kind]}</span>'
    age = board.stamp(datetime.datetime.fromtimestamp(h["t"], board.now.tzinfo), "ir-age") if h["t"] else ""
    detail = _mark(snip) if "\x02" in snip else ""                  # a match in the title is marked in the title; the excerpt only when it holds one
    if kind in ("item", "history"):
        pk = R.proj_top(r)       # the project it shows is the top-level one (an item on a sub-page reads as its project)
        proj = esc(board.proj_label(pk)) if pk else ""
        if kind == "history":
            bits = [f'History · {esc(h["sub"] or "change")}', esc(board.when(h["t"])) if h["t"] else "", proj]
        else:
            by = r.get("written_by")
            bits = [f'updated by {esc(by)}' if by else "", esc(board.when(h["t"])) if h["t"] else "", proj]
        subj = board.bare(r.get("subject") or "")
        return _ui.row(tag_html=kt + " " + _ui.tag(state_of[r["gid"]]), href=R.item_href(r), rid=R.rid(r), title=subj, title_html=_hl(subj, ws), age_html=age,
                       who_html=" · ".join(b for b in bits if b), detail_html=detail, li_class="srow", li_id=li_id, new_tab=False)
    idat = f' id="{li_id}"' if li_id else ""
    if kind == "project":
        k = h["key"]
        link = f'<a class="ir-link" href="{esc(under("/" + k))}"><span class="hgoal">{_hl(board.proj_title(k), ws)}</span> <span class="ir-id dim">{esc(k)}</span></a>'
        mirror = board.proj_mirror(k)
        bits = [f'page changed {esc(board.when(h["t"]))}' if h["t"] else "", f'<a href="{esc(mirror)}" target="_blank" rel="noopener">gbrain page ↗</a>' if mirror else ""]
        who = f'<div class="ir-who">{" · ".join(b for b in bits if b)}</div>' if any(bits) else ""
        return f'<li class="irow srow"{idat}><div class="ir-top"><span class="ir-title">{kt} {link}</span>{age}</div>{who}' + (f'<div class="ir-det">{detail}</div>' if detail else "") + '</li>'
    name = h["key"]                                                 # a session: the fleet tool's view while it has a live pane (the way the board links it), else the name as text
    href = board.sess_href(name)
    title = f'<a class="ir-link" href="{esc(href)}" target="_blank" rel="noopener"><span class="hgoal">{_hl(name, ws)}</span></a>' if href else f'<span class="hgoal">{_hl(name, ws)}</span>'
    s = board.sess.get("name:" + name) or {}
    bits = [esc(h["sub"]) if h["sub"] else "", esc(str(s.get("status") or "")), "opens in sala" if href else "no live pane"]
    return f'<li class="irow srow"{idat}><div class="ir-top"><span class="ir-title">{kt} {title}</span>{age}</div><div class="ir-who">{" · ".join(b for b in bits if b)}</div></li>'
