"""stackshot — the owner's stackshot instance: the MCP connector (<board_url>/mcp) and the board publisher (publish.py +
render.py, in-process); the board is its web UI (<board_url>).

Every session, CLI pane or cloud, writes board items only through this server; the gates of the earlier board live here as
hard refusals. Every rule, path, identity and label of THIS instance lives in stackshot.toml (config.py) — this file carries the
mechanism (store · gates · page debts · publish · messaging · anchors · rules · static site · auth).

This file is the entry only: the check of the config and the port taken before anything is read, the three steps of web/wiring.py
(`install_early`, `build`, `install_late`: the hook tables of the service areas and the MCP application), the access log's filter,
the reload signal, the start-time passes and the background threads, and the serve loop. Everything else lives in the packages
(service/, model/, waits/, web/, ...) and nothing here is looked up on this module by name: a suite replaces a name on its owner.

Layout: ONE store, [paths] store (board-data/ in a repository of its own), <letter>/<n>.json per item
(the letters mark where an item came from; s = everything created since). This server is the only
allocator (next-id file) and the only writer; publish.py renders and commits.

Run:  STACKSHOT_CONFIG=<file> uv run --locked --extra server stackshot server   (outside the production checkout a run without it is refused)
      STACKSHOT_AUTH=off …                                 (local test only)
"""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any

_EARLY_HUP: list[int] = []
if __name__ == "__main__":      # a reload signal before the loop's handler is up (the imports below take seconds) is kept, never fatal
    signal.signal(signal.SIGHUP, lambda *_: _EARLY_HUP.append(1))



from stackshot import paths as _paths
from stackshot.core import config as _cfg  # noqa: E402  — stackshot.toml: every path, identity, rule and label of this instance
from stackshot.core import readonly as _ro  # noqa: E402  — the read-only mode of a warm standby copy: STACKSHOT_READ_ONLY=1, read once at start (readonly.py)

# ----------------------------------------------------------------------------- the start takes its port before the store
# A server started from a checkout with no STACKSHOT_CONFIG must not read the instance's config or run its start-time passes
# (the hold and needs migrations, the refile and wake passes, roles.json) against the live store before its port is checked. So a run of this file,
# before the rest of the module writes anything (the store dirs below):
# (1) a checkout other than the production one refuses to start without $STACKSHOT_CONFIG, and (2) the listening socket is
# bound first and handed to uvicorn later (_serve), so a port another server holds ends the run here, the store untouched.
# PRODUCTION_CHECKOUT is the one place the code names the instance's checkout: the units set STACKSHOT_CONFIG themselves
# (install.sh), so a production start passes (1) wherever its checkout lives; only a bare run outside ~/stackshot is refused.
PRODUCTION_CHECKOUT = "~/stackshot"
_LISTEN: Any = None                     # the socket bound at start (__main__ only); None when the module is imported


def _refuse_unconfigured() -> None:
    """Exit 2 when no config is named in the environment and this file is not in the production checkout."""
    if os.environ.get("STACKSHOT_CONFIG") or os.environ.get("BOARD_MCP_CONFIG"):
        return
    here = _paths.ROOT
    prod = Path(os.path.expanduser(PRODUCTION_CHECKOUT)).resolve()
    if here != prod:
        print(f"stackshot: not started: STACKSHOT_CONFIG is unset and {here} is not the production checkout ({prod}), so this run "
              f"would use {_cfg.PATH}. Set STACKSHOT_CONFIG to a test config (as tests/*_scenario.py do); nothing was touched.",
              file=sys.stderr, flush=True)
        sys.exit(2)


def _take_port() -> Any:
    """Bind and listen on [server] host:port the way uvicorn would (SO_REUSEADDR, IPv6 for a host with a colon) → the socket.
    A port already listened on exits 1 with one line, before any state is read or written."""
    import socket
    s = _cfg.CFG["server"]
    host, port = str(s["host"]), int(s["port"])
    sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        sock.listen(2048)                   # uvicorn's backlog; listening now is what holds the port against a second start
    except OSError as e:
        sock.close()
        print(f"stackshot: not started: port {host}:{port} is taken ({e.strerror or e}), most likely by another stackshot server; "
              f"config {_cfg.PATH}; nothing was touched.", file=sys.stderr, flush=True)
        sys.exit(1)
    return sock


if __name__ == "__main__":
    _refuse_unconfigured()
    _LISTEN = _take_port()

from stackshot.github import ghsync as _gh  # noqa: E402  — the GitHub mirror: its worker and its comment reader are started in `_start_background`
from stackshot.web import whatschanged as _wc  # noqa: E402  — the record of the tools' text a start makes (`_start_background`)
from stackshot.waits import watchers as _watch  # noqa: E402  — `holding()`, read by the reload (`_on_hup`)
from stackshot.service import runner as _runner  # noqa: E402  — the minute tick table and the background threads (service/runner.py): `_start_background` starts it
from stackshot.service import wakes as _wakes  # noqa: E402  — the wake pass the start runs (service/wakes.py)
from stackshot.service import handoff as _handoff  # noqa: E402  — the hand-off repair pass the start runs (service/handoff.py)
from stackshot.service import stall as _stallsvc  # noqa: E402  — the stall pass' pause, read at the start and at a reload (service/stall.py)
from stackshot.service import stamp as _stamp_svc  # noqa: E402  — the stored phase sweep the start and a reload run (service/stamp.py)
from stackshot.service import migrations as _migrations  # noqa: E402  — the start-up migrations (service/migrations.py)
from stackshot.service import wait_fixes as _wait_fixes  # noqa: E402  — the one warning for a missing [model] wait_alias_until (service/wait_fixes.py)
from stackshot.web import runners as _runners  # noqa: E402  — the Runners page: its snapshot and its rebuild are set up by `_start_background` (runners.py)
from stackshot.web import search as _search  # noqa: E402  — the board's search index: its loop is started by `_start_background` (search.py)
from stackshot.core import store as _store  # noqa: E402  — the store's path, for the standby backstop and the store directory below (core/store.py)
from stackshot.service import create as _create_svc  # noqa: E402  — the request map's folder, made below (service/create.py)
from stackshot.web import publish as _pubmod  # noqa: E402  — the debounced publish: the start and a reload call `_pubmod._publish()`
from stackshot.web.publish import _publish_if_idle  # noqa: E402  — the idle test the board's runner rebuild asks (`_runners.ON_CHANGE` in `_start_background`)
from stackshot.router import router_live as _router_live  # noqa: E402  — the router: its loop is started by `_start_background`
from stackshot.projects import projects as _prj  # noqa: E402  — the project record: the registry stamp the start runs (`stamp_registry`)
from stackshot.projects.project_registry import _roles_sync_safe  # noqa: E402  — roles.json, with projects.json beside it, made at the start (projects/project_registry.py)
if _ro.is_read_only():
    # a warm standby copy changes nothing: no directory is made, and any file write under the instance's own directories is refused
    _ro.install_backstop([_store.STORE, _cfg.state(), *(_cfg.path("paths", k) for k in ("repo", "markdown", "brain", "project_touch") if _cfg.get("paths", k))])
else:
    (_store.STORE / _store.LETTER).mkdir(parents=True, exist_ok=True)
    _create_svc.REQUESTS.parent.mkdir(parents=True, exist_ok=True)


from stackshot.web import wiring as _wiring  # noqa: E402  — the hook tables and the MCP application (web/wiring.py): its three steps run in the order they have always run, `install_early` here, `build` below, `install_late` after it
_wiring.install_early(sys.modules[__name__])   # the hook tables of the write path and the switches; this module, run as `__main__` in production, is handed over as the first owner of the passes' names


# ----------------------------------------------------------------------------- MCP surface
# The FastMCP instance, its middleware, the tools and the routes are web/app.py's `build`, called from web/wiring.py, which hands it the callables they take (late-bound, so a suite that replaces one on its owner still reaches it).
mcp = _wiring.build()   # the FastMCP instance, its middleware, the tools and the routes (web/app.py, built in web/wiring.py)


_wiring.install_late()   # the hand-off clock's name and the hook tables of the service areas (web/wiring.py), after the build, as they were installed before


# ----------------------------------------------------------------------------- the access log keeps no sign-in secrets
# uvicorn's access log records the request path with its query string. Three parameters carry a one-time sign-in value that
# does not belong in the journal: `code` (the OAuth authorization code on /auth/callback and /ui/callback), `state` (the
# OAuth state on /authorize and the callbacks) and `txn_id` (the consent transaction on the consent page). Each is single-use
# and short-lived, but the value of such a parameter is logged as `[redacted]` on every route; the path and the other
# parameters stay readable.
_REDACTED_PARAMS = frozenset({"code", "state", "txn_id"})


class _RedactCodes(logging.Filter):
    """uvicorn logs `'%s - "%s %s HTTP/%s" %d'` with args (client, method, path?query, http_version, status)."""
    def filter(self, record: logging.LogRecord) -> bool:
        a = record.args
        if isinstance(a, tuple) and len(a) == 5 and isinstance(a[2], str) and "?" in a[2]:
            path, _, query = a[2].partition("?")
            parts = query.split("&")
            if any(part.partition("=")[0] in _REDACTED_PARAMS for part in parts):
                query = "&".join(part.partition("=")[0] + "=[redacted]" if part.partition("=")[0] in _REDACTED_PARAMS else part
                                 for part in parts)
                record.args = (a[0], a[1], f"{path}?{query}", a[3], a[4])
        return True                                  # never drop a line, only rewrite it


# Installed at import, before uvicorn is configured: its dictConfig replaces the logger's handlers but keeps its filters.
logging.getLogger("uvicorn.access").addFilter(_RedactCodes())


def _on_hup() -> None:
    """SIGHUP (`systemctl --user reload stackshot.service`, which stackshot-reload.path runs when the config file changes): re-read
    stackshot.toml. A valid file is live at once and the board is published once; a broken one is logged and the running config
    kept; a RESTART_ONLY key is logged and waits for the restart (config.reload says which)."""
    changed = _cfg.reload()
    if changed is None:
        print("config reload: failed, nothing changed", file=sys.stderr, flush=True)
        return
    print(f"config reload: {', '.join(changed) if changed else 'no live setting changed'}"
          + (f"; waiting for a restart: {', '.join(_cfg.PENDING)}" if _cfg.PENDING else ""), file=sys.stderr, flush=True)
    if _ro.is_read_only():                  # the config is re-read; a standby copy has no stall pause to check and publishes nothing
        return
    try:
        _stallsvc.stall_pause_reload()
        _stallsvc.stall_pause_check()                                  # a pause of the stall pass read by this reload begins its clock now (the start line); the warning with its end is config.reload's own, once (config.notes carries stall_notes)
    except Exception as e:  # noqa: BLE001
        print(f"config reload: stall pause not checked: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        if not _watch.holding():            # a setting that feeds the reading ([waiting] dated_wait_min_hours, [instance] timezone) may have moved what the board shows: the stored phase follows now, not at the next minute
            _stamp_svc._phase_sweep()       # the publish below is this reload's own
    except Exception as e:  # noqa: BLE001
        print(f"config reload: phase sweep failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    _pubmod._publish()


async def _serve() -> None:
    """mcp.run's own loop, with the reload signal on it."""
    import asyncio
    asyncio.get_running_loop().add_signal_handler(signal.SIGHUP, _on_hup)
    if _EARLY_HUP:
        _on_hup()
    s = _cfg.CFG["server"]
    await mcp.run_async(transport="http", host=s["host"], port=int(s["port"]), path=s["path"], show_banner=False,
                        **({"sockets": [_LISTEN]} if _LISTEN is not None else {}))   # the socket bound before the passes


def _start_background() -> list[str]:
    """The start-time passes and the background threads, in the order they have always run; → the names of the threads started.
    on a warm standby copy (STACKSHOT_READ_ONLY=1) nothing here runs and nothing starts: no record of the tools' text, no project-id
    stamp, no roles.json, no migration or wake pass (each writes items), no runner, no publish loop, no router, no page-debt call, no runners
    rebuild, no search index, no GitHub mirror (each acts outward or writes). The web UI and the MCP read tools are all a standby serves."""
    if _ro.is_read_only():
        print("stackshot: read-only standby copy (STACKSHOT_READ_ONLY): no start-time passes, no background threads; writes go to the live board", file=sys.stderr, flush=True)
        return []
    try:
        print(_wc.record(_paths.ROOT / "tests" / "tool_text.snapshot.json"), file=sys.stderr, flush=True)     # a start is a release; a change in the tools' text since the last one becomes the brief's what-changed line
    except Exception as e:
        print(f"what changed: not recorded: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    try:
        _prj.stamp_registry()               # phase A: the one-time backfill, every page of the registry carries its project id from the first second (minted once, never changed)
    except Exception as e:
        print(f"project ids: {e}", file=sys.stderr, flush=True)
    _roles_sync_safe()                      # roles.json is current from the first second, before any publish (and projects.json beside it)
    _stallsvc.stall_pause_reload()
    _stallsvc.stall_pause_check()                    # a pause of the stall pass read at the start begins its clock now (or keeps the one in <state>/stall_pause.json) and logs its end time
    for _n in _cfg.notes():                 # a setting missing from the one-file config that changes behaviour silently (the page rules off): a pause of the stall pass, with its end
        print(f"config: {_n}", file=sys.stderr, flush=True)
    _wait_fixes._wait_alias_check()                     # one warning when [model] wait_alias_until is missing: the code's default end of the alias window stands
    try:
        if _migrations.migrate_holds():                # status on_hold → open + metadata.hold, before the first publish and the runner
            _pubmod._publish()
    except Exception as e:
        print(f"hold migration failed: {e}", file=sys.stderr, flush=True)
    try:
        if _migrations.migrate_needs():                # needs a list, the linked agent (metadata.agent) in it; idempotent, so every start runs it
            _pubmod._publish()
    except Exception as e:
        print(f"needs migration failed: {e}", file=sys.stderr, flush=True)
    try:
        if _migrations._session_ids_pass():             # step B: a requested move to permanent session ids (or its rollback), under the item lock, before the first publish
            _pubmod._publish()
    except Exception as e:
        print(f"session ids pass failed: {e}", file=sys.stderr, flush=True)
    try:
        if _migrations.migrate_owner_mover():         # an item that waits on him has him as mover, his answered hand-offs are ended; idempotent, so every start runs it
            _pubmod._publish()
    except Exception as e:
        print(f"mover migration failed: {e}", file=sys.stderr, flush=True)
    try:
        if _migrations._retire_rank_pass():             # ranks are retired: an open item's rank and a rank-only queued state are cleared, clocks unchanged; idempotent, so every start runs it
            _pubmod._publish()
    except Exception as e:
        print(f"rank retirement pass failed: {e}", file=sys.stderr, flush=True)
    try:
        if [r for r in _migrations._mover_backfill_pass() if r["mover"]]:     # D1: a live item with no mover gets the project's builder, else its -main agent, never its creator; idempotent
            _pubmod._publish()
    except Exception as e:
        print(f"mover backfill pass failed: {e}", file=sys.stderr, flush=True)
    try:
        if _handoff.handoff_repair_pass():          # an open hand-off record that names someone but the item's mover is ended into its history; idempotent, and before the wake pass and any thread
            _pubmod._publish()
    except Exception as e:
        print(f"hand-off record repair failed: {e}", file=sys.stderr, flush=True)
    try:
        if _migrations._close_marks_pass():             # the closed items still showing an open step get them marked (done / dropped by outcome); idempotent, so every start runs it
            _pubmod._publish()
    except Exception as e:
        print(f"close marks pass failed: {e}", file=sys.stderr, flush=True)
    try:
        if _wakes.wake_pass():                    # items whose wake passed while the server was down are open before the first publish
            _pubmod._publish()
    except Exception as e:
        print(f"wake pass failed: {e}", file=sys.stderr, flush=True)
    try:
        _stamp_svc._phase_tick()            # a stored phase the down time left behind (a wait that ended, a deploy that changed the reading) is true before the first publish; the runner's first sweep is a minute away
    except Exception as e:
        print(f"phase sweep failed: {e}", file=sys.stderr, flush=True)
    started = _runner.start()               # the minute set's runner, the timer publish and the runner's watchdog (service/runner.py)
    threading.Thread(target=_router_live.loop, daemon=True).start()   # the router's ticks (a call takes minutes), in a thread of their own
    _runners.PERSIST = True             # the last runners snapshot is kept in a file under the state dir, and taken back here: the Runners pages draw it at once after a restart
    _runners.restore()
    _runners.AUTOSTART = True           # the side panel's Runners section may start its one background rebuild (runners.peek; [runners] panel = false stops it); never at import, so a test that renders the board makes no GitHub call
    _runners.ON_CHANGE = _publish_if_idle   # …and when that rebuild ends with other counts, the debounced publish (5 s) refreshes the home that is kept (False while a publish is running: runners.py asks again every 10 s for 2 min); one per panel_refresh_s
    threading.Thread(target=_search.loop, daemon=True).start()      # step 3: the search index's first build and its passes after a save, in a thread of its own
    threading.Thread(target=_gh.worker_loop, daemon=True).start()   # the GitHub mirror's worker; it idles while [github] sync is off (the default), so a reload can turn the mirror on
    threading.Thread(target=_gh.comments_loop, daemon=True).start() # phase 3: the reader of the owner's comments on the issues, beside the worker; idles the same way
    return [*started, "router", "search", "ghsync-worker", "ghsync-comments"]


if __name__ == "__main__":
    _start_background()
    import anyio
    anyio.run(_serve)                   # = mcp.run(transport="http", …), plus the SIGHUP handler on its loop
