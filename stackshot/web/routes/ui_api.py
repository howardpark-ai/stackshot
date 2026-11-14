"""ui_api.py: the board page's own API: the prefs (panel-open, language, panel-order), the colour combos, search, the sala-link probe, landed and closed, the projects, the runners, routing and the audit pages.

`register(mcp, *, contact_label, runner_status, phase_sweep_status)` adds the routes to the server's `mcp` in the order they were declared in server.py. The three callables are the server's own, which its
tools and passes read too, and are looked up when a call is made."""
from __future__ import annotations

import json
import sys
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from stackshot.audit import audit as _audit, audit_overview as _audit_overview
from stackshot.core import readonly as _ro, store as _store
from stackshot.service import landed as _ld
from stackshot.web import i18n as _i18n, uiprefs as _uiprefs, runners as _runners, colorcombos as _colorcombos
from stackshot.web.answers import _answer_same_origin
from stackshot.web.auth import signin as _signin
from stackshot.web.auth.signin import _ui_guard, _ui_key, _ui_open
from stackshot.web.project_form import _FORM_MACHINES, _cfg_names, _form_call
from stackshot.web.publish import _publish
from stackshot.web.routes.board_pages import _details_key, _ui_mods
from stackshot.web.routes.client_api import _client_machine


_contact_label, _runner_status, _phase_sweep_status = None, None, None      # the server's own, set by register()


_PREFS_BODY_MAX = 4096


async def _prefs_body(request: Request, what: str):
    """The gates every save under /prefs/ shares, for a body of JSON: (the signed-in person's address, the decoded JSON, None), or (None, None, the refusal to answer with). Signed in to
    the board (403 otherwise: with no address there is no person to keep it for, so a viewer let in without sign-in cannot save), from the board's own origin (403), a JSON content type
    (415), a body of at most 4 KB (413, judged from Content-Length before the body is read, or as a body with none arrives), valid JSON (400). `what` names the setting in the refusals."""
    email = _signin._ui_email(request)
    if not email:
        return None, None, PlainTextResponse(f"sign in to the board to keep the panel {what}", status_code=403)
    if not _answer_same_origin(request):
        return None, None, PlainTextResponse("refused: this did not come from the board's own page", status_code=403)
    if "json" not in str(request.headers.get("content-type") or "").lower():
        return None, None, PlainTextResponse(f"send the {what} as JSON", status_code=415)
    declared = request.headers.get("content-length")      # the size is judged before a byte is read; a body with none (chunked) is cut off as it arrives
    if declared is not None:
        if not declared.isdigit():
            return None, None, PlainTextResponse("the request length is not a number", status_code=400)
        if int(declared) > _PREFS_BODY_MAX:
            return None, None, PlainTextResponse("refused: the request is too long", status_code=413)
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > _PREFS_BODY_MAX:
            return None, None, PlainTextResponse("refused: the request is too long", status_code=413)
    try:
        d = json.loads(body.decode("utf-8"))
    except ValueError:
        return None, None, PlainTextResponse("the body is not JSON", status_code=400)
    return email, d, None


async def panel_open_save(request: Request):
    """Save whether the signed-in person's side panel is open on a wide screen: the page's script sends it when they pin or unpin the panel with its button, never from the narrow drawer.
    Body (JSON): {"open": true} or {"open": false}, a real boolean (anything else, a body that is not an object, or no `open` is 400). Kept per person on the server beside the panel order
    (uiprefs.py), so every page, reload, browser and device draws the panel the same way; open is the default and is stored as no key. The gates are the order save's (_prefs_body):
    signed in to the board (403 otherwise), from the board's own origin (403), a JSON body of at most 4 KB (413, 415, 400). A settings file that cannot be read or written is 503
    ("could not be saved"), and nothing is changed. Answers {"open": bool}."""
    email, d, refused = await _prefs_body(request, "state")
    if refused is not None:
        return refused
    if not isinstance(d, dict) or not isinstance(d.get("open"), bool):
        return PlainTextResponse('send {"open": true} or {"open": false}', status_code=400)
    try:
        is_open = _uiprefs.set_panel_open(email, d["open"])
    except OSError as e:
        print(f"panel state not saved: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return PlainTextResponse("the panel state could not be saved on the server; try again", status_code=503, headers={"Cache-Control": "no-store"})
    return JSONResponse({"open": is_open}, headers={"Cache-Control": "no-store"})


async def lang_save(request: Request):
    """Save the language the signed-in person reads the board's pages in: the page's KO/EN switch at the foot of the side panel sends it. Body (JSON): {"lang": "en"} or {"lang": "ko"}, one of the codes
    in i18n.LANGS (anything else, a body that is not an object, or no `lang` is 400). Kept per person on the server beside the panel settings (uiprefs.py), so every page, reload, browser and device reads
    the same language; English is the default and is stored as no key. A code with no catalog loaded is kept all the same and draws in English until its catalog (the folder [ui] locale_dir names) loads.
    The gates are the order save's (_prefs_body): signed in to the board (403 otherwise), from the board's own origin (403), a JSON body of at most 4 KB (413, 415, 400). A settings file that cannot be
    read or written is 503 ("could not be saved"), and nothing is changed. Answers {"lang": code}."""
    email, d, refused = await _prefs_body(request, "language")
    if refused is not None:
        return refused
    if not isinstance(d, dict) or not isinstance(d.get("lang"), str) or d["lang"] not in _i18n.LANGS:
        return PlainTextResponse("send " + " or ".join('{"lang": "%s"}' % c for c in _i18n.LANGS), status_code=400)
    try:
        lang = _uiprefs.set_lang(email, d["lang"])
    except OSError as e:
        print(f"language not saved: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return PlainTextResponse("the language could not be saved on the server; try again", status_code=503, headers={"Cache-Control": "no-store"})
    return JSONResponse({"lang": lang}, headers={"Cache-Control": "no-store"})


async def panel_order_save(request: Request):
    """Save the signed-in person's order of the board's side panel's sections (Machines, Runners, Anchor hub, Audit, Projects), or put it back to the default. Body (JSON):
    {"order": ["runners", "machines", ...]} or {"reset": true}. The order is kept per person on the server (uiprefs.py), so every device shows it. The gates are the
    other writes': signed in to the board (403 otherwise: with no address there is no person to keep it for, so a viewer let in without sign-in cannot save), from the
    board's own origin (403), a JSON body of at most 4 KB (413 judged from Content-Length before the body is read, 415, 400). `order` is the sections the page shows, in the
    order they now have: names the page does not have are ignored, and the names sent take the places they hold in the person's stored order, so a section left out (one
    the page did not draw) keeps its place; a body that is not an object, an `order` that is not a list of short strings, or neither key, is 400. A settings file that
    cannot be read or written is 503 ("could not be saved"), and nothing is changed. Answers {"order": [...whole order...], "default": bool}."""
    email, d, refused = await _prefs_body(request, "order")
    if refused is not None:
        return refused
    if not isinstance(d, dict):
        return PlainTextResponse('send {"order": [...]} or {"reset": true}', status_code=400)
    names = None
    if d.get("reset") is not True:
        if "order" not in d:
            return PlainTextResponse('send {"order": [...]} or {"reset": true}', status_code=400)
        names = d["order"]
        if (not isinstance(names, list) or len(names) > _uiprefs.MAX_NAMES
                or any(not isinstance(n, str) or len(n) > _uiprefs.MAX_NAME_LEN for n in names)):
            return PlainTextResponse("order = a list of section names", status_code=400)
    try:
        # a name the panel does not have is ignored; the names sent take the places they have in the person's stored order, a section left out keeps its place
        order = _uiprefs.reset_panel_order(email) if names is None else _uiprefs.set_panel_order(email, names)
    except OSError as e:
        print(f"panel order not saved: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return PlainTextResponse("the order could not be saved on the server; try again", status_code=503, headers={"Cache-Control": "no-store"})
    return JSONResponse({"order": order, "default": _uiprefs.is_default(order)}, headers={"Cache-Control": "no-store"})


# The saved color combinations of the shared color tool (colorcombos.py): one list for the instance, read and written by the board's own page and by the fleet tool's web
# server. Not under /prefs/ on purpose: a post there drops the kept home page (_UI_WRITES) and a color list changes no board page. Every answer is JSON and no-store; an error is
# {"error": "<a plain sentence>", "field": "<the failing color key, "name", "values", "id" or "sender", else null>"}, except the machine routes' 401, which is the plain text
# every /client route gives. The server runs no contrast check.

_COLORS_NOT_FORM = (f"refused: only the web form may change the saved colors: `sender` must be \"{_colorcombos.WEB_LABEL}\", a label in [project_agent] form_senders, "
                    "and the token must be a machine in form_machines")
_COLORS_NOT_MACHINE = "refused: the token must be a machine in [project_agent] form_machines"
_COLORS_FAILED = "the saved colors could not be read or saved on the server; try again"


def _colors_err(status: int, message: str, field: str | None = None) -> JSONResponse:
    return JSONResponse({"error": message, "field": field}, status_code=status, headers={"Cache-Control": "no-store"})


def _colors_run(op: str, body: dict[str, Any], via: str) -> JSONResponse:
    """The store call behind all four writes and both reads -> the answer {"combos": [...], "max": 50}, or the error: 400 a bad name, values or id (field = the failing
    key), 409 a new name when the list is full, 503 when the file cannot be read or written (nothing changed)."""
    try:
        if op == "list":
            out = _colorcombos.payload()
        elif op == "save":
            out = _colorcombos.payload(_colorcombos.save(body.get("name"), body.get("values"), via))
        else:
            out = _colorcombos.payload(_colorcombos.delete(body.get("id")))
    except _colorcombos.Invalid as e:
        return _colors_err(400, str(e), e.field)
    except _colorcombos.Full as e:
        return _colors_err(409, str(e))
    except OSError as e:
        print(f"saved colors not read or saved: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return _colors_err(503, _COLORS_FAILED)
    return JSONResponse(out, headers={"Cache-Control": "no-store"})


async def _colors_body(request: Request) -> dict[str, Any] | JSONResponse:
    """A write's JSON object, or the error answer: 415 not JSON by content type, 400 a length that is no number, 413 over 4 KB (judged from Content-Length before the body is
    read, and as the body arrives when it has none), 400 not JSON or not an object."""
    if "json" not in str(request.headers.get("content-type") or "").lower():
        return _colors_err(415, "send the body as JSON")
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isdigit():
            return _colors_err(400, "the request length is not a number")
        if int(declared) > _colorcombos.BODY_MAX:
            return _colors_err(413, "refused: the request is too long")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > _colorcombos.BODY_MAX:
            return _colors_err(413, "refused: the request is too long")
    try:
        d = json.loads(body.decode("utf-8"))
    except ValueError:
        return _colors_err(400, "the body is not JSON")
    if not isinstance(d, dict):
        return _colors_err(400, "the body is a JSON object")
    return d


async def _colors_browser(request: Request, op: str):
    """The board's own page: signed in (403 otherwise, a read too: nothing here is public), and a write from the board's own origin (403)."""
    from starlette.concurrency import run_in_threadpool
    if not _signin._ui_email(request):
        return _colors_err(403, "sign in to the board to use the saved colors")
    body: dict[str, Any] = {}
    if op != "list":
        if not _answer_same_origin(request):
            return _colors_err(403, "refused: this did not come from the board's own page")
        got = await _colors_body(request)
        if isinstance(got, JSONResponse):
            return got
        body = got
    return await run_in_threadpool(_colors_run, op, body, "board")


async def _colors_machine(request: Request, op: str):
    """The fleet tool's web server, by the machine token (Authorization: Bearer, as every /client route): 401 without a valid one (the plain text of the other /client routes),
    403 when its machine is not in [project_agent] form_machines. A write also needs `sender` to be "sala-web" and a label in form_senders (_form_call, as the For you writes)."""
    from starlette.concurrency import run_in_threadpool
    machine = _client_machine(request.headers.get("authorization", ""))
    if not machine:
        return PlainTextResponse("unauthorized: a machine token is required (Authorization: Bearer …)", status_code=401)
    if machine not in _cfg_names("form_machines", _FORM_MACHINES):
        return _colors_err(403, _COLORS_NOT_MACHINE)
    body: dict[str, Any] = {}
    if op != "list":
        got = await _colors_body(request)
        if isinstance(got, JSONResponse):
            return got
        body = got
        sender = body.get("sender")
        if not isinstance(sender, str) or not sender.strip() or len(sender.strip()) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in sender.strip()):
            return _colors_err(400, "sender = the caller's own label: one line of at most 80 characters", "sender")
        if sender.strip() != _colorcombos.WEB_LABEL or not _form_call(machine, sender.strip()):
            return _colors_err(403, _COLORS_NOT_FORM, "sender")
    return await run_in_threadpool(_colors_run, op, body, _colorcombos.WEB_LABEL)


async def colors_combos_list(request: Request):
    """The saved color combinations of the shared color tool, for a person signed in to the board -> 200 {"combos": [{id, name, values, saved, via}, ...], "max": 50}, oldest first.
    403 without sign-in, 503 when the file cannot be read."""
    return await _colors_browser(request, "list")


async def colors_combos_save(request: Request):
    """Save a color combination: body (JSON, at most 4 KB) {"name": 1-40 characters, "values": {the 14 keys bg card fg mut line ibd link solid onsolid labbg labfg labbd disbg disfg,
    each "#rrggbb"}}. A name the list already has (case ignored) replaces that combination and keeps its id. Gates as /prefs/panel-order: signed in (403), the board's own
    origin (403), JSON (415), size (413), an object (400). -> 200 the list as GET; 400 a bad name or value (`field` names the key), 409 "the list is full, delete one" (50),
    503 the file cannot be read or written."""
    return await _colors_browser(request, "save")


async def colors_combos_delete(request: Request):
    """Delete a saved combination: body {"id": "<id>"}; an id the list does not have is no error (it is already gone). Same gates as the save. -> 200 the list as GET."""
    return await _colors_browser(request, "delete")


async def client_colors_combos_list(request: Request):
    """The saved color combinations for the fleet tool's web server (machine token): 200 as GET /colors/combos; 401 without a valid token; 403 a machine not in form_machines."""
    return await _colors_machine(request, "list")


async def client_colors_combos_save(request: Request):
    """As POST /colors/combos, by the machine token, with "sender": "sala-web" in the body. 401 without a valid token, 403 for a machine not in form_machines or a sender that is
    not "sala-web" in form_senders; then the body's gates (415, 413, 400); the combination is saved with via "sala-web"."""
    return await _colors_machine(request, "save")


async def client_colors_combos_delete(request: Request):
    """As POST /colors/combos/delete, by the machine token, with "sender": "sala-web" in the body; the gates are the machine save's."""
    return await _colors_machine(request, "delete")


async def site_search(request: Request):
    """The board's search: /search?q=… (one newest-first list under When, Kind and State filters, from ui/search.py), rendered on request. Behind the board's sign-in, as the
    board and the item pages are (_ui_guard). Matched before the catch-all below, so no static file can take the name."""
    g = _ui_guard(request)
    if g is not None:
        return g
    from starlette.concurrency import run_in_threadpool

    rmod, smod, _ = _ui_mods()

    def page() -> str:         # the filters (When, Kind, State, how many rows) come from the address too
        return smod.results_html(rmod.Board(str(_store.STORE)), str(request.query_params.get("q") or ""), request.query_params)
    return HTMLResponse(await run_in_threadpool(page), headers={"Cache-Control": "no-store"})


async def probe_sala_link(request: Request):
    """TEMPORARY PROBE (the installed-app session link test) (removed, or promoted into the session link, in the follow-up PR): one session link written six ways, so a tap on an Android phone in the installed app shows which way opens the installed
    sala app (ui/render.py Board.probe_html). `?to=<url>` is used only when it is on the origin of [client] session_view; anything else is ignored. Behind the board's sign-in, as the other pages are (_ui_guard); it writes nothing."""
    g = _ui_guard(request)
    if g is not None:
        return g
    from starlette.concurrency import run_in_threadpool

    rmod = _ui_mods()[0]
    to = str(request.query_params.get("to") or "")
    return HTMLResponse(await run_in_threadpool(lambda: rmod.Board(str(_store.STORE)).probe_html(to)), headers={"Cache-Control": "no-store"})


async def landed_moved(request: Request):
    """The Landed page is now the Closed page, at /closed: an old address (a bookmark, a link from a message) goes there with its query (?page=N) kept. A permanent redirect, never cached ("no-store"), so a later move needs no
    cache purge. Not behind the sign-in: it says nothing but where the page is, and the page itself asks."""
    q = request.url.query
    return RedirectResponse("/closed" + (f"?{q}" if q else ""), status_code=301, headers={"Cache-Control": "no-store"})


async def landed_page(request: Request):
    """The Closed page at /closed (the Landed page, renamed; /landed redirects to it): the closes agents made that he did not and has not cleared (New), grouped by project (Board.landed_html), and the Last 14 days section, a page of 25 at a time (?page=N). Behind the board's
    sign-in, rendered on request. Like a phone's notifications the entries stay until he clears them: opening the page clears nothing (a Clear button per line and Clear all at the top post to /landed/clear)."""
    g = _ui_guard(request)
    if g is not None:
        return g
    from starlette.concurrency import run_in_threadpool

    rmod = _ui_mods()[0]

    kw = {"page": request.query_params.get("page")}        # the Closed page pages its Completed section (?page=N)

    def page() -> str:
        return rmod.Board(str(_store.STORE), contact_of=_contact_label).landed_html(**kw)
    return HTMLResponse(await run_in_threadpool(page), headers={"Cache-Control": "no-store"})


async def projects_page(request: Request):
    """The Projects page: each project with its live agents and its items (ui/render.py Board.projects_html), the project index that left the home. Behind the board's sign-in, drawn on request."""
    g = _ui_guard(request)
    if g is not None:
        return g
    from starlette.concurrency import run_in_threadpool

    from stackshot.web.ui import render as r2

    return HTMLResponse(await run_in_threadpool(lambda: r2.Board(str(_store.STORE)).projects_html()), headers={"Cache-Control": "no-store"})


async def _landed_change(request: Request, change):
    """The Landed page's buttons: Clear, Clear all and Undo post here through `change` (landed.clear or landed.unclear), which takes the comma-separated landed.key values of the `keys` field. The gates are the For you
    seen route's: signed in to the board (or the board open), from its own origin; the body is capped at 64 KB. A change that changed something republishes the board (debounced; the home Landed count follows with it).
    A form post (no JavaScript) gets a 303 back to the page; the page's own script asks with `Accept: application/json` and gets {"ok": true, "changed": n}, and keeps the line where it is. No keys changes nothing (it is not a clear-everything call)."""
    email = _signin._ui_email(request)
    if not email and not (_ui_open() or _signin._auth_mode() == "off"):
        return PlainTextResponse("sign in to the board", status_code=403)
    if not _answer_same_origin(request):
        return PlainTextResponse("refused: this did not come from the board's own page", status_code=403)
    body = await request.body()
    if len(body) > 65536:
        return PlainTextResponse("refused: the form is too long", status_code=413)
    from urllib.parse import parse_qs
    raw = (parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).get("keys") or [""])[0]
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    n = change(keys) if keys else 0
    if n:
        _publish()
    if "application/json" in str(request.headers.get("accept") or "").lower():
        return JSONResponse({"ok": True, "changed": n}, headers={"Cache-Control": "no-store"})
    return RedirectResponse("/closed", status_code=303, headers={"Cache-Control": "no-store"})


async def _landed_clear(request: Request):
    """The Landed page's Clear and Clear all buttons: the closes named by `keys` (comma-separated landed.key values: one for a line's Clear, every key the page listed for Clear all) are cleared and leave
    the home count (the page's script keeps their lines in place, dimmed, with an Undo until the page is reloaded)."""
    return await _landed_change(request, _ld.clear)


async def landed_clear(request: Request):
    return await _landed_clear(request)


async def landed_unclear(request: Request):
    """The Landed page's Undo: puts back the closes named by `keys` that are cleared and still inside the 60-day window (landed.unclear); an unknown key, an uncleared one or an old one does nothing. Same gates as Clear."""
    return await _landed_change(request, _ld.unclear)


async def landed_seen(request: Request):
    """The old Mark all seen route, kept so a Landed page still open from before an earlier change works: it clears the keys it carries, like /landed/clear."""
    return await _landed_clear(request)


def _runners_switch_token(email: str, box: str) -> str:
    """The Disable / Enable form's token on the CI runners page: an HMAC over the signed-in address and the machine, as _watch_token, under its own label."""
    import hashlib, hmac
    return hmac.new(_ui_key(), f"runners-switch\x00{email}\x00{box}".encode(), hashlib.sha256).hexdigest()


def _runners_token_maker(request: Request):
    """The page's token maker for the viewer (None draws no button: no switch script configured, or this copy is read-only)."""
    if _ro.is_read_only() or not _runners.switch_enabled():
        return None
    email = _signin._ui_email(request)
    if not email:
        return None                        # the route needs a real signed-in address, so an open board draws no button that would only be refused
    return lambda box: _runners_switch_token(email, box)


async def site_runners(request: Request):
    """The CI runners page: the count cards and each machine's CI runners, idle, running, disabled or offline, with a Disable / Enable button per machine (runners.py).
    Behind the board's sign-in like the other pages; matched before the catch-all below."""
    g = _ui_guard(request)
    if g is not None:
        return g
    from starlette.concurrency import run_in_threadpool
    token = _runners_token_maker(request)

    rmod, _, nmod = _ui_mods()

    def page() -> str:
        return nmod.page_html(rmod.Board(str(_store.STORE)), _runners.serve(), token)     # the last snapshot at once; a rebuild (GitHub and ssh) runs in its own thread
    return HTMLResponse(await run_in_threadpool(page), headers={"Cache-Control": "no-store"})


async def site_runners_json(request: Request):
    """The CI runners page's data (runners.data): the counts, the runners with their state, job and reason, and the table as HTML, which the page swaps in every 30 s.
    The snapshot behind it is the last one, at once; a viewer finding it older than [runners] cache_s starts the one background rebuild, so many viewers make one set of GitHub calls."""
    g = _ui_guard(request)
    if g is not None:
        return g
    from starlette.concurrency import run_in_threadpool
    token = _runners_token_maker(request)
    nmod = _ui_mods()[2]
    return JSONResponse(await run_in_threadpool(lambda: nmod.data(_runners.serve(), token=token)), headers={"Cache-Control": "no-store"})


async def site_runners_switch(request: Request):
    """The CI runners page's Disable / Enable button: turns one machine's CI switch off or on by running the configured switch script (runners.switch_box: argv `bash <switch_script> off|on <box>`, a timeout, one at a time per machine).
    Disable lets a running job finish and then takes no new job. The gates are the other state-changing actions': a read-only copy answers 503 first (the route wrapper), then a real signed-in address (an open board is refused too, as /answer and /watch do), from its own origin,
    the form's token (an HMAC over the viewer and the machine); the body is capped at 4096 bytes; the action and the machine are checked (the machine against runners.switch_boxes: the fleet's names, plus a [runners] boxes entry named in [runners.ssh_hosts]) before anything runs. The page's script asks with
    `Accept: application/json` and gets {"ok": bool, "text": "..."} to show; a form post gets the same text as plain text."""
    email = _signin._ui_email(request)
    if not email:
        return PlainTextResponse("sign in to the board to disable or enable a CI machine", status_code=403)
    if not _answer_same_origin(request):
        return PlainTextResponse("refused: this did not come from the board's own page", status_code=403)
    body = await request.body()
    if len(body) > 4096:
        return PlainTextResponse("refused: the form is too long", status_code=413)
    from urllib.parse import parse_qs
    form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    f = lambda k: (form.get(k) or [""])[0]
    box, act = f("box"), f("act")
    import hmac
    if not hmac.compare_digest(f("token").encode(), _runners_switch_token(email, box).encode()):     # bytes: a non-ASCII token is a 403, not a TypeError
        return PlainTextResponse("refused: the form's token does not match; reload the page and send again", status_code=403)
    if act not in _runners.SWITCH_ACTIONS:
        return PlainTextResponse("refused: the action is Disable or Enable", status_code=400)
    if box not in _runners.switch_boxes():
        return PlainTextResponse("refused: that is not one of the fleet's machines", status_code=400)
    from starlette.concurrency import run_in_threadpool
    ok, text = await run_in_threadpool(_runners.switch_box, box, act)
    if "application/json" in str(request.headers.get("accept") or "").lower():
        return JSONResponse({"ok": ok, "text": text}, status_code=200 if ok else 502, headers={"Cache-Control": "no-store"})
    return PlainTextResponse(text, status_code=200 if ok else 502, headers={"Cache-Control": "no-store"})


async def site_routing(request: Request):
    """The old address of a details page (/routing/<key>.html): a permanent redirect to /<key>, query
    dropped. It serves nothing itself, so it answers before the sign-in; a path that is not a page key is a plain 404."""
    key = _details_key(str(request.path_params.get("key", "")))
    if not key:
        return PlainTextResponse("not found", status_code=404)
    return RedirectResponse("/" + key, status_code=301)


# The daily board audit: the board's "Audit now" button and its "last audit ran" line. Both sit
# behind the board's own wall, as the board and the item pages do (_ui_guard: the edge's access proxy with [auth] ui_open, the
# server's sign-in without it), and are matched before the catch-all below. The cue itself is audit.cue, shared with the timer.
_AUDIT_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def audit_now(request: Request):
    """POST: start the audit now (audit.cue("button")): in [audit] mode "script" a detached `audit.py run`, in mode "agent" a cue to the audit agent; the answer is its
    code with its text: 202 started or cued · 409 a run is in progress · 404 the audit is not enabled · 503 the run could not start (agent mode: the agent is not live). Any other method is 405."""
    g = _ui_guard(request)
    if g is not None:
        return g
    if request.method != "POST":
        return PlainTextResponse("method not allowed: POST /audit/now", status_code=405, headers={"Allow": "POST"})
    from starlette.concurrency import run_in_threadpool
    code, text = await run_in_threadpool(_audit.cue, "button")       # push.py may take seconds: off the event loop
    return PlainTextResponse(text, status_code=code, headers={"Cache-Control": "no-store"})


async def audits_page(request: Request):
    """The Audits page: the paces the audits run at, the audit groups with their audits, the latest findings and the recent runs (ui/render.py Board.audits_html, from audit_overview). Behind the board's sign-in,
    drawn on request; its Audit now button posts to /audit/now, like the side panel card's."""
    g = _ui_guard(request)
    if g is not None:
        return g
    from starlette.concurrency import run_in_threadpool

    from stackshot.web.ui import render as r2

    return HTMLResponse(await run_in_threadpool(lambda: r2.Board(str(_store.STORE)).audits_html(runner=_runner_status())), headers={"Cache-Control": "no-store"})


async def audit_status(request: Request):
    """The audit at a glance (audit.status): enabled, the agent, a run in progress and since when, the last run, the next."""
    g = _ui_guard(request)
    if g is not None:
        return g
    out = _audit.status()
    out["card"] = _audit_overview.card(time.time())      # the side panel card's shortlist: per audit group its audits and its findings in 24 hours (null where the group keeps no findings log)
    out["runner"] = _runner_status()        # the minute set: which mode, and per tick its last run and last error (runner.py)
    out["phase_sweep"] = _phase_sweep_status()      # the stored phase kept true at the clock edges: runs, items swept, stamped, moved, differences seen, last run (_phase_sweep)
    return JSONResponse(out, headers={"Cache-Control": "no-store"})


def register(mcp, *, contact_label, runner_status, phase_sweep_status) -> None:
    """Add the routes to the server's `mcp`, in the order they were declared in server.py. Called once."""
    global _contact_label, _runner_status, _phase_sweep_status
    _contact_label, _runner_status, _phase_sweep_status = contact_label, runner_status, phase_sweep_status
    mcp.custom_route("/prefs/panel-open", methods=["POST"])(panel_open_save)
    mcp.custom_route("/prefs/lang", methods=["POST"])(lang_save)
    mcp.custom_route("/prefs/panel-order", methods=["POST"])(panel_order_save)
    mcp.custom_route("/colors/combos", methods=["GET"])(colors_combos_list)
    mcp.custom_route("/colors/combos", methods=["POST"])(colors_combos_save)
    mcp.custom_route("/colors/combos/delete", methods=["POST"])(colors_combos_delete)
    mcp.custom_route("/client/colors/combos", methods=["GET"])(client_colors_combos_list)
    mcp.custom_route("/client/colors/combos", methods=["POST"])(client_colors_combos_save)
    mcp.custom_route("/client/colors/combos/delete", methods=["POST"])(client_colors_combos_delete)
    mcp.custom_route("/search", methods=["GET"])(site_search)
    mcp.custom_route("/probe/sala-link", methods=["GET"])(probe_sala_link)
    mcp.custom_route("/landed", methods=["GET"])(landed_moved)
    mcp.custom_route("/closed", methods=["GET"])(landed_page)
    mcp.custom_route("/projects", methods=["GET"])(projects_page)
    mcp.custom_route("/landed/clear", methods=["POST"])(landed_clear)
    mcp.custom_route("/landed/unclear", methods=["POST"])(landed_unclear)
    mcp.custom_route("/landed/seen", methods=["POST"])(landed_seen)
    mcp.custom_route("/runners", methods=["GET"])(site_runners)
    mcp.custom_route("/runners.json", methods=["GET"])(site_runners_json)
    mcp.custom_route("/runners/switch", methods=["POST"])(site_runners_switch)
    mcp.custom_route("/routing/{key:path}", methods=["GET"])(site_routing)
    mcp.custom_route("/audit/now", methods=_AUDIT_METHODS)(audit_now)
    mcp.custom_route("/audits", methods=["GET"])(audits_page)
    mcp.custom_route("/audit/status", methods=["GET"])(audit_status)
