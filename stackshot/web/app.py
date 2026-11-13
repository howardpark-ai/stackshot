"""app.py: the MCP application. `build` makes the FastMCP instance, adds the middleware in the order the server has always run them, installs the standby copy's route wrapper, and registers the board's own sign-in, the tools (web/tools/) and the routes (web/routes/), in that order.

server.py calls `build` once, at import, and keeps the result as `mcp`. What the tools and the routes need from the rest of server.py (the passes, the stores, the helpers that stay there) arrives as keyword arguments, late-bound: a callable looked up when it is called, so a suite that replaces the server's own still reaches it. This module imports nothing of server.py (web/ is one layer; CONTRIBUTING.md, Layout)."""
from __future__ import annotations

import sys
from pathlib import Path

from fastmcp import FastMCP
from mcp_types import Icon as _Icon
from starlette.responses import FileResponse, HTMLResponse, PlainTextResponse

from stackshot.core import config as _cfg, instance as _inst, readonly as _ro, store as _store
from stackshot.core.instance import NAME, OWNER
from stackshot.github import ghsync as _gh
from stackshot.web import i18n as _i18n, uiprefs as _uiprefs
from stackshot.web.auth import oauth as _oauth, signin as _signin
from stackshot.web.auth.signin import _ui_renewed
from stackshot.web.board_home import _board_home_drop
from stackshot.web.tools.text import ZONE, _DESC_LINE_MAX, _DESC_MAX_LINES, _NEXT_WORDS
from stackshot.web.tools import notes as _tool_notes
from stackshot.web.tools import brief as _tool_brief
from stackshot.web.tools import get as _tool_get
from stackshot.web.tools import create as _tool_create
from stackshot.web.tools import update as _tool_update
from stackshot.web.tools import complete as _tool_complete
from stackshot.web.tools import sessions as _tool_sessions
from stackshot.web.tools import message as _tool_message
from stackshot.web.tools import route as _tool_route
from stackshot.web.tools import anchors as _tool_anchors
from stackshot.web.tools import rules as _tool_rules
from stackshot.web.middleware import _Fingerprint, _LinkIds, _ReadOnly, _RefusalLog, _RetiredInputs
from stackshot.web.routes import client_api as _routes_client_api
from stackshot.web.routes import answers as _routes_answers
from stackshot.web.routes import ui_api as _routes_ui_api
from stackshot.web.routes import board_pages as _routes_board_pages

_ICON = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+PHJlY3Qgd2lkdGg9IjY0IiBoZWlnaHQ9IjY0IiByeD0iMTQiIGZpbGw9IiMxZjFmMjEiLz48cGF0aCBkPSJNMTUgMzRsMTIgMTIgMjItMjYiIGZpbGw9Im5vbmUiIHN0cm9rZT0iI2YwYTA2YSIgc3Ryb2tlLXdpZHRoPSI4IiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz48L3N2Zz4K"  # the board's favicon (<state>/site/favicon.svg), same mark everywhere


# the web routes of a warm standby copy. Every route registered with mcp.custom_route below goes through this wrapper (installed here,
# before the first one is declared): on the standby a request that is not a read (POST, PUT, PATCH, DELETE ...) is answered 503 with
# readonly.REFUSAL, and so is any method on /audit/now (it starts a run); a read goes on to its handler and an HTML answer gets the banner. The
# live instance runs the handler as it always did. FastMCP's own /mcp and OAuth routes are not custom routes: the tool middleware above refuses
# the writes there.
def _request_lang(request) -> str:
    """The language a request's page is drawn in: the signed-in person's stored choice (uiprefs.lang_of) when that language has a catalog loaded (i18n.available), else English. Worked out once per
    request (kept on request.state); a visitor not signed in, a person who never picked one and a board with no locale folder read English without a second look at the catalog."""
    try:
        got = getattr(request.state, "ui_lang", None)
        if got is not None:
            return got
        email = _signin._ui_email(request) if request.method in ("GET", "HEAD") else ""
        lang = _uiprefs.lang_of(email) if email else _i18n.DEFAULT
        lang = _i18n.norm(lang) if lang != _i18n.DEFAULT else lang
        request.state.ui_lang = lang
        return lang
    except Exception as e:  # noqa: BLE001  — a language that cannot be worked out is English, never a refused page
        print(f"page language not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _i18n.DEFAULT


def _panel_ordered(request, resp):
    """A page's HTML answer with the side panel as the signed-in person left it: its sections in their saved order (ui/render.py apply_panel_order) and the panel closed when they closed
    it (apply_panel_open), and in their language (apply_lang: <html lang>, the page scripts' words, the fixed buttons); any other answer, a visitor not signed in and a person who never moved a
    section, closed the panel or picked a language get it as it is. The page is drawn in the default order with the panel open (the home is one kept draw per language), so both are put in on
    the way out and are in the first paint. A page that cannot be read or changed is served as it was, never refused for it."""
    try:
        if (request.method != "GET" or not isinstance(resp, HTMLResponse)
                or resp.status_code != 200 or not str(resp.media_type or "").startswith("text/html")):
            return resp
        email = _signin._ui_email(request)
        from stackshot.web.ui import render as r2
        if not email:       # not signed in: nothing of a person's to put in, and the language switch (it saves per person) comes out
            page = bytes(resp.body).decode("utf-8")
            if 'id="panel-lang"' not in page:
                return resp
            page = r2.strip_lang_toggle(page)
        else:
            order, is_open = _uiprefs.panel_prefs(email)
            lang = _request_lang(request)
            if _uiprefs.is_default(order) and is_open and lang == _i18n.DEFAULT:
                return resp
            page = r2.apply_lang(r2.apply_panel_open(r2.apply_panel_order(bytes(resp.body).decode("utf-8"), order), is_open, lang), lang)
        resp.body = page.encode("utf-8")
        resp.headers["content-length"] = str(len(resp.body))
    except Exception as e:  # noqa: BLE001
        print(f"panel order not applied: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return resp


_UI_WRITES = ("/items/", "/for-you/", "/landed/", "/runners/", "/prefs/")      # the write routes of the root pages: a post to one drops the kept home
_UI_WRITES_KEEP_HOME = ("/prefs/panel-open", "/prefs/lang")      # …except these: the home's draw does not depend on whether the panel is open (apply_panel_open puts it in per person on the way out) nor on whose language it is (each language has its own kept draw), so a toggle leaves the kept draws
_RO_REFUSED_PATHS = ("/audit/now",)
_RO_LIVE_ONLY = ("/runners", "/runners.json")       # these read GitHub and other machines over ssh on each request: the live board does that, a standby asks nobody


def _ro_with_banner(resp):
    """A standby copy's HTML answer with the banner under its <body ...> tag; any other answer as it is. The validators go: the page differs per request."""
    mt = str(getattr(resp, "media_type", "") or "")
    if not mt.startswith("text/html") or getattr(resp, "status_code", 200) >= 300:
        return resp
    try:
        raw = Path(resp.path).read_bytes() if isinstance(resp, FileResponse) else bytes(resp.body)
        page = _ro.with_banner(raw.decode("utf-8", "replace"), _store.STORE, ZONE)
    except Exception:  # noqa: BLE001  — a page that cannot carry the banner is served without it, never refused for it
        return resp
    drop = {"content-length", "content-type", "etag", "last-modified", "content-encoding"}
    return HTMLResponse(page, status_code=resp.status_code, headers={k: v for k, v in resp.headers.items() if k.lower() not in drop})


_custom_route_plain = None      # set by build: the route decorator FastMCP made, which the wrapper below calls


def _custom_route_ro(path, methods, **kw):
    if _ro.is_read_only():       # on the standby every write method reaches the wrapper and is answered 503 with the sentence, not 405 (route table made once, at start)
        methods = list(dict.fromkeys([*methods, "POST", "PUT", "PATCH", "DELETE"]))
    deco = _custom_route_plain(path, methods=methods, **kw)

    def wrap(fn):
        import functools

        @functools.wraps(fn)
        async def guarded(request):
            path = request.url.path
            if not _ro.is_read_only():
                tok = _i18n.set_current(_request_lang(request))      # the page handler draws in the person's language (i18n.current)
                try:
                    resp = await fn(request)
                finally:
                    _i18n.reset_current(tok)
                resp = _ui_renewed(request, _panel_ordered(request, resp))
                if request.method == "POST" and path.startswith(_UI_WRITES) and not path.startswith(_UI_WRITES_KEEP_HOME):      # a write from a page of the board: the home is drawn again on its next read
                    _board_home_drop()
                return resp
            if request.method not in ("GET", "HEAD", "OPTIONS") or path in _RO_REFUSED_PATHS:
                return PlainTextResponse(_ro.REFUSAL, status_code=503, headers={"Cache-Control": "no-store"})
            if path in _RO_LIVE_ONLY:
                return PlainTextResponse("this page reads GitHub and the other machines; on a read-only standby copy (STACKSHOT_READ_ONLY) it is on the live board.", status_code=503, headers={"Cache-Control": "no-store"})
            tok = _i18n.set_current(_request_lang(request))
            try:
                resp = await fn(request)
            finally:
                _i18n.reset_current(tok)
            return _ui_renewed(request, _ro_with_banner(_panel_ordered(request, resp)))
        deco(guarded)
        return fn
    return wrap


def build(
    *,
    fmt,
    handoff_brief,
    is_parked,
    model_report_line,
    notice_asked,
    notice_report,
    evwait_preread,
    sender_not_owner,
    ask_after_write,
    update,
    wait_alias_gate,
    fleet_names,
    inbox_flag_minutes,
    message,
    anchor_release,
    watch_label,
    evw_boxes,
    machine_state,
    rules_text,
    main_agent,
    client_get,
    client_post,
    recycle_wanted_tokens,
    answer,
    contact_label,
    runner_status,
    phase_sweep_status,
) -> FastMCP:
    """The server's MCP application, built once: the FastMCP instance with its middleware, the standby wrapper on `mcp.custom_route`, then the sign-in, the tools and the routes registered in this order (the route table's order is the order of these calls; the board pages' catch-all is last)."""
    global _custom_route_plain
    mcp = FastMCP(
        "stackshot",
        icons=[_Icon(src=_ICON, mime_type="image/svg+xml")],
        instructions=(
            f"{NAME} — {OWNER}'s task board (web UI: {_inst.BOARD_URL}). Items are HUMAN-LEVEL: a deliverable a session owns, a decision or "
            f"input {OWNER} must give, a blocker on someone outside, a handoff — never a working step. Subject starts with "
            f"{_cfg.CFG['subject']['prefixes']}. Description = the item's background: what the item is + where it lives + what done means, as short `- ` bullets (one fact each, at most "
            f"{_DESC_MAX_LINES} lines of {_DESC_LINE_MAX} characters; parallel bullets under one parent, indented two spaces; the server refuses prose), live state only, never steps or commands for {OWNER} (those go in step). metadata.project = the item's gbrain page, projects/<slug> or infra/<slug> for a machine/service item (required; a bare slug is accepted and stored as the full key). sender = your "
            f"own session (cse_… id or name) on a create, an update, a confirm and a complete: the server records it as the item's creator ('created by' in History). mover = who moves it now (with none, the project's builder, else its -main agent) (the item model, docs/design). metadata.needs = decision | external. due = YYYY-MM-DD {_cfg.get('instance', 'timezone')}, only from a real deadline. next = {_NEXT_WORDS} "
            f"An update replaces only your own lines of next, and a line of yours it leaves out is marked done or dropped in that update (clear_next=true wipes all). Ids read board#<n> for a new item (its GitHub issue number), {_gh.local_prefix()}#<n> for one created while "
            f"GitHub was down or the hour's writes were spent (temporary, until it takes its issue number), and <letter><n> for older items; write an id in "
            f"that shown form, never a store id such as {_gh.letter()}7. A board change that reflects a state change is matched by a project-page "
            f"update in the same turn, the page first (a page write up to five minutes before the change counts). If your session did not load {OWNER}'s standing rulebook at start (a cloud or Cowork session), call the rules tool first and follow it: it overrides any default behaviour. A Claude Code session on the owner's machines has it already through CLAUDE.md and does not call it."
        ),
        auth=_oauth._auth(),
    )
    mcp.add_middleware(_Fingerprint(mcp))
    mcp.add_middleware(_LinkIds())
    # The refusal log, the standby copy's read-only refusal and the retired-input refusal come after _LinkIds, in this order.
    mcp.add_middleware(_RefusalLog())
    mcp.add_middleware(_ReadOnly())
    mcp.add_middleware(_RetiredInputs())
    _custom_route_plain = mcp.custom_route
    mcp.custom_route = _custom_route_ro
    _tool_notes.bind(main_agent=main_agent)
    _tool_brief.register(mcp, fmt=fmt, handoff_brief=handoff_brief, is_parked=is_parked, model_report_line=model_report_line)
    _tool_get.register(mcp, fmt=fmt, notice_asked=notice_asked, notice_report=notice_report)
    _tool_create.register(mcp, evwait_preread=evwait_preread, sender_not_owner=sender_not_owner)
    _tool_update.register(mcp, ask_after_write=ask_after_write, sender_not_owner=sender_not_owner, update=update, wait_alias_gate=wait_alias_gate)
    _tool_complete.register(mcp, sender_not_owner=sender_not_owner)
    _tool_sessions.register(mcp, fleet_names=fleet_names)
    _tool_message.register(mcp, inbox_flag_minutes=inbox_flag_minutes, message=message)
    _tool_route.register(mcp, anchor_release=anchor_release, watch_label=watch_label)
    _tool_anchors.register(mcp, evw_boxes=evw_boxes, machine_state=machine_state)
    _tool_rules.register(mcp, rules_text=rules_text)
    _signin.register(mcp)
    _routes_client_api.register(mcp, client_get=client_get, client_post=client_post, recycle_wanted_tokens=recycle_wanted_tokens)
    _routes_answers.register(mcp, answer=answer)
    _routes_ui_api.register(mcp, contact_label=contact_label, runner_status=runner_status, phase_sweep_status=phase_sweep_status)
    _routes_board_pages.register(mcp, contact_label=contact_label)
    return mcp
