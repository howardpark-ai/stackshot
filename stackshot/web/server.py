"""stackshot — the owner's stackshot instance: the MCP connector (<board_url>/mcp) and the board publisher (publish.py +
render.py, in-process); the board is its web UI (<board_url>).

Every session, CLI pane or cloud, writes board items only through this server; the gates of the earlier board live here as
hard refusals. Every rule, path, identity and label of THIS instance lives in stackshot.toml (config.py) — this file carries the
mechanism (store · gates · page debts · publish · messaging · anchors · rules · static site · auth).

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

import importlib
import logging
import os
import signal
import sys
import threading
import time as _time_mod
from pathlib import Path
from typing import Any, Callable

time = _time_mod        # the clock this module's own code reads (`time.time()`): a suite that pins it sets it here, and sets the `time` of each other module the clock must reach on that module

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

from stackshot.github import ghsync as _gh  # noqa: E402  — the GitHub mirror and the id switch, both off unless [github] says so
from stackshot.web import whatschanged as _wc  # noqa: E402  — the brief's what-changed lines for 7 days after a release that changes a tool
from stackshot.waits import waiting as _wt  # noqa: E402  — what an item waits on and whose move it is (waiting.py)
from stackshot.model import model as _model  # noqa: E402  — the item model of the redesign: dead | alive | waiting, the mover and the wait, derived from the fields (model.py)
from stackshot.model import queued as _queued  # noqa: E402  — a mover busy on another item: the rule that reads its other on-agent items as waiting, queued behind it (queued.py; `[model] queued_behind`)
from stackshot.web import home as _home  # noqa: E402  — the home page's three lists (your-move, agents, waiting) on that model (home.py: the items API carries the list)
from stackshot.waits import watchers as _watch  # noqa: E402  — the waits' watchers of the item model: what ends a wait, the relay's ask, the chases (watchers.py)
from stackshot.waits import handoff as _ho  # noqa: E402  — the hand-off machinery of the item model: the record, the clock, section 5 (handoff.py)
from stackshot.service import runner as _runner  # noqa: E402  — the minute tick table, the wake event and the background threads (service/runner.py)
from stackshot.service import wakes as _wakes  # noqa: E402  — the wake pass, the anchor pass, the item and anchor release and the minute tick bodies of the wake passes (service/wakes.py)
from stackshot.service import watching as _watching  # noqa: E402  — the waits' watchers: a wait that ends turns its item; anchor ids and the routine-line test (service/watching.py)
from stackshot.service import event_waits as _evwaits  # noqa: E402  — the waits on a fleet event: the reports, the polls and the machine anchors (service/event_waits.py)
from stackshot.service import wake_hooks as _wake_hooks  # noqa: E402  — what those three still reach on this module (service/wake_hooks.py)
from stackshot.service import handoff as _handoff  # noqa: E402  — the hand-off record, its delivery, the minute pass, the gone-mover hand-over and the display (service/handoff.py)
from stackshot.service import handoff_hooks as _handoff_hooks  # noqa: E402  — what those two still reach on this module (service/handoff_hooks.py)
from stackshot.service import stall as _stallsvc  # noqa: E402  — the stall pass's state, its pause and its steps (service/stall.py)
from stackshot.service import ladder as _laddersvc  # noqa: E402  — the one ladder of the stall pass and the hand-off audit (service/ladder.py)
from stackshot.service import stall_hooks as _stall_hooks  # noqa: E402  — what those two and the pass itself (service/stall_tick.py) still reach on this module (service/stall_hooks.py)
from stackshot.service import checks as _checks  # noqa: E402  — the done check: its forms, its readers and its minute pass (service/checks.py)
from stackshot.service import released_live as _rlive  # noqa: E402  — what is live in a checkout, read from git, and the pull requests anchored to an item (service/released_live.py)
from stackshot.service import proofs as _proofs  # noqa: E402  — a step's proof, the settle of one item for one event and the hand-over after it (service/proofs.py)
from stackshot.service import released as _relsvc  # noqa: E402  — a live pull request settles the items built for it (service/released.py)
from stackshot.service import checks_hooks as _checks_hooks  # noqa: E402  — what those four still reach on this module (service/checks_hooks.py)
from stackshot.service import fleet_events as _fleetev  # noqa: E402  — the fleet's own minute clocks (the clients' tick, the inbox flag) and the fleet helpers (service/fleet_events.py)
from stackshot.service import github_events as _github_events  # noqa: E402  — what the GitHub mirror's reader reports to the board: an item that took its issue number, the owner's comment (service/github_events.py)
from stackshot.service import retire_passes as _retire_passes  # noqa: E402  — the retire pass: the stored state words and carry fields out of the open items (service/retire_passes.py)
from stackshot.service import stamp as _stamp_svc  # noqa: E402  — the stored phase and waits_on, the sweep that keeps it true and the project-id pass (service/stamp.py)
from stackshot.service import migrations as _migrations  # noqa: E402  — the start-up migrations and the passes of the migration route (service/migrations.py)
from stackshot.service import page_debt as _pdsvc  # noqa: E402  — the page-debt call: its pass, its calls per page and the fallback to the page's keeper (service/page_debt.py)
from stackshot.service import passes_hooks as _passes_hooks  # noqa: E402  — what the page-debt call, the migrations, the fleet events, the client reads and the recycle bookkeeping still reach on this module (service/passes_hooks.py)
from stackshot.service import client_reads as _client_reads  # noqa: E402  — the reads of the client API and the item facts they carry: an item's mover, its then, its wait and its list (service/client_reads.py)
from stackshot.service import recycle as _recycle_svc  # noqa: E402  — the recycle bookkeeping: what waits for one, what one cleared and the script's request for one (service/recycle.py)
from stackshot.service import merge_progress as _merge_progress  # noqa: E402  — a merged pull request is progress for the item it is tied to: the pass and the tie (service/merge_progress.py)
from stackshot.web import runners as _runners  # noqa: E402  — the Runners page: each CI runner by machine and repo, idle, running or offline with the CI switch's reason (runners.py)
from stackshot.web import search as _search  # noqa: E402  — the board's search: an FTS5 index over items, history, project pages and session names, rebuilt on write (search.py)
# Settings read once here are the ones config.RESTART_ONLY keeps for the run (written into the tool descriptions at start);
# every other setting is read where it is used, so a reload (SIGHUP) is live at once.
from stackshot.core.instance import NAME  # noqa: E402  — NAME: the one read of [instance] (core/instance.py)
from stackshot.web.tools import get as _tool_get  # noqa: E402  — the item as `get` and the brief show it, the notice's ruling (web/tools/get.py)
from stackshot.web.tools import notes as _tool_notes  # noqa: E402  — the notes a reply carries: form notes, the model lines, the guard report, the holds report (web/tools/notes.py)
from stackshot.web.tools import text as _wttext  # noqa: E402  — the words and limits the tools state, and the board's time zone (`ZONE`, read on this module when a line says a time, so a suite that pins it sets it there; web/tools/text.py)
from stackshot.web.tools.text import _ANCHOR_SHAPES, _ASK_NONE, _CLOSE_REFUSAL, _GMAIL_TERMS, _MODEL_PAGE  # noqa: E402  — the words and limits the tools state (web/tools/text.py), which this module's passes read too
from stackshot.web.tools import rules as _rules_tool  # noqa: E402  — the rulebook's text and the rules tool (web/tools/rules.py)
from stackshot.web.middleware import _unlink_ids  # noqa: E402, F401  — the save hooks look it up here at call time (`_late("_unlink_ids")`)
from stackshot.core import store as _store  # noqa: E402  — the store's path (`_store.STORE`, read from [paths] store at this import), its item files, the next id and the file write (core/store.py); `STORE` is read and set on that module, never here
from stackshot.service import writes as _writes  # noqa: E402  — the one write path of an item: its lock (`ITEM_LOCK`), its save (`save`) and the write context (service/writes.py)
from stackshot.service import telling as _telling  # noqa: E402  — who is told of a write: the senders, the gate in front of a front agent, the holds and the notices (service/telling.py)
from stackshot.service import store as _svcstore  # noqa: E402  — the readers of one item: `_load` and `_shown_ids` are called on this module, so a suite that replaces one sets it there (service/store.py)
from stackshot.service.store import _legacy_hold, _legacy_needs, _path  # noqa: E402,F401  — the readers of one item (service/store.py); the passes written against the server module read `S._legacy_hold`, `S._legacy_needs` and `S._path` off it (stamp.PassHost)
from stackshot.service import create as _create_svc  # noqa: E402  — creating an item: every gate and write of the create tool in their order, and the request map (service/create.py)
from stackshot.service import gates as _gates  # noqa: E402  — the write gates of the create, update and complete tools and the checks before the item lock (service/gates.py)
from stackshot.service import update as _update_svc  # noqa: E402  — updating, completing and confirming an item: every gate and write of the update tool in their order (service/update.py)
from stackshot.model import holders as _holders  # noqa: E402  — who holds an item and who may be named to move it: the stored hold flag, the role a page gives a session, the front-agent pair rule (model/holders.py)
from stackshot.service import item_read as _item_read  # noqa: E402  — reading items: the open `after` items, the item as the model reads it, the scoped anchors, what is parked, the model's switches (service/item_read.py)
from stackshot.service import agents as _agents  # noqa: E402  — a project's -main agent and builder, the names a hand-off could name, the reader of many items' movers (service/agents.py)
from stackshot.service import contacts as _contacts  # noqa: E402  — an item's contact: the readers, the write, what follows a retired or renamed agent, the backfill (service/contacts.py)
from stackshot.service import pane_recovery as _pane_recovery  # noqa: E402  — pane liveness, a session or a machine down, the recovery request of a quiet mover and the park fallback (service/pane_recovery.py)
from stackshot.service import mover_steps as _mover_steps  # noqa: E402  — the steps of a save that keep whose move an item is: the stored state, the mover settle, the owner's step on the checklist, the notes a read carries (service/mover_steps.py)
from stackshot.service import owner_words as _owner_words  # noqa: E402  — the owner's words behind a write and who wrote it: the sender check, the said note, the cap-words and re-bullet writers (service/owner_words.py)
from stackshot.service.owner_words import _BASIS_WORDS, _RELAUNCH, OUTCOMES  # noqa: E402  — the three values of the write path that the hook tables capture by value (service/owner_words.py)
from stackshot.service import save_hooks as _save_hooks  # noqa: E402  — what the save steps, the naming, the message relay and the owner's words still reach in the surface (service/save_hooks.py)
from stackshot.service import agent_names as _agent_names  # noqa: E402  — naming the working background agent in an item's needs, the items a text names, and the router's push told to the hand-off (service/agent_names.py)
from stackshot.service import messaging as _messaging  # noqa: E402  — the message tool's relay: `_message`, its refusals, the report written onto an item, and the log `MSG_LOG` (service/messaging.py)
from stackshot.service import asks as _asks  # noqa: E402  — the ask line: its shape gate, its form in next, the nag, and the leaves of a wrong or moot ask (service/asks.py)
from stackshot.service import wait_fixes as _wait_fixes  # noqa: E402  — the wait and hold fixes with I/O and the old wait parameters' window (service/wait_fixes.py)
from stackshot.service import wait_gates as _wait_gates  # noqa: E402  — the write guards of event, anchor and front-step waits, the decision options' gate, and what an update owes the watchers (service/wait_gates.py)
from stackshot.service import audit_ticks as _audit_ticks  # noqa: E402  — the ten-minute audit ticks (the filing, dates, archive and audit-line passes), the balancer and the queue map they read (service/audit_ticks.py)
from stackshot.service import answer_handover as _handover  # noqa: E402  — where an item goes after the owner's answer, a Done or the end of a wait: the hand-over helpers and the answer line (service/answer_handover.py)
from stackshot.service import answer as _answer_svc  # noqa: E402  — the owner's answer from the board: its record, its delivery, the settle of a pending one and the escalation (service/answer.py)
from stackshot.web import answers as _answers_mod  # noqa: E402  — the answer form's lock, limits, pending file and words (web/answers.py): the save hooks hand the module to service/answer.py, which reads them on it each time, so a suite that puts a spy in place of `_ANSWER_LOCK` sets it there
if _ro.is_read_only():
    # a warm standby copy changes nothing: no directory is made, and any file write under the instance's own directories is refused
    _ro.install_backstop([_store.STORE, _cfg.state(), *(_cfg.path("paths", k) for k in ("repo", "markdown", "brain", "project_touch") if _cfg.get("paths", k))])
else:
    (_store.STORE / _store.LETTER).mkdir(parents=True, exist_ok=True)
    _create_svc.REQUESTS.parent.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------- needs, observers and after
# An item relates to sessions four ways, on the whole board. Its mover (the first design called it the owner), one
# session he talks to. metadata.needs, whose move it is now, a LIST: "decision" (his), "external" (someone outside, named in
# next) and session names (a keeper or a background agent of any project, or the mover itself), several at once; empty is the
# mover's move. It replaces the linked agent (metadata.agent): the item's notices (a wake, a recycle done,
# an `after` released) go to the sessions in needs, or to the page's keeper when it names none, and a mover named there is
# never messaged (only its own turn-end check asks it). metadata.observers: sessions that hear only a close or a reopen.
# metadata.after: items of any project that must close first; while one is open the item is parked without a hold,
# and the last close wakes it. The stored list is canonical: decision, external, then the sessions as given.
# _NEEDS_KINDS, _needs_list, _needs_of, _needs_kinds, _canon_needs, _needs_store, _needs_sessions, _waits_decision, _after_of and _observers_of are model/needs.py's (imported near the top of this module).
# _after_open, which reads each `after` item from the store, is service/item_read.py's.


# _legacy_needs and _legacy_hold, the two forms _load reads an old file through, are store.py's.


from stackshot.web import wiring as _wiring  # noqa: E402  — the hook tables, the switches of the router and the queue, the GitHub mirror's two hooks and the build of the MCP application (web/wiring.py): this module calls its three steps in the order they have always run, `install_early` here, `build` at the MCP surface below, `install_late` after it
_wiring.install_early(sys.modules[__name__])   # the write path's steps, the GitHub mirror's hooks, the default mover, the page gate's local-only switch, the router's and the queue's switches; the server module is what the tables' late lookups (`_late`) reach


# NAME is core/instance.py's (imported near the top of this module).


# The page rule's debts (page_debts.py), the names this module's own code uses. A suite or a script that reads or sets one of the others reaches it on page_debts.py. Private names nobody here reads stay in that module:
# _KEEPER_WHY, _age, _brain_dir, _debt_strict.
from stackshot.web import page_debts as _pdebts  # noqa: E402,F401  — the suites that put a page's time in place of the real one set `_page_ts` on this module (`server._pdebts._page_ts`)
from stackshot.web.page_debts import (  # noqa: E402,F401
    _OWED_LOCK,
    _debt_mover,
    _grace_min,
    _owed_brain_skip,
    _owed_load,
    _owed_mark,
    _owed_readable,
    _owed_save,
    _owed_settle,
    _session_id,
    _shown_needs,
    _shown_ref,
)


from stackshot.anchors import anchors as _anc  # noqa: E402
from stackshot.anchors import merge_log as _mlog  # noqa: E402,F401  — the hub's record of the pull requests it saw merge (merge_log.py): the merge pass (service/merge_progress.py) reads it itself; the last-activity pass reads it here (`S._mlog`)
from stackshot.anchors import event_log as _elog  # noqa: E402  — the hub's record of the other activity on pull requests (CI results, comments, reviews, merges): read by the last-activity pass (event_log.py)
from stackshot.web import render as _rmod  # noqa: E402
from stackshot.model import ask_read as _ar  # noqa: E402  — how an ask and its options are read (open question, alternatives, Yes/No pair, Recommend), shared with the audit (ask_read.py)
from stackshot.router import router_live as _router_live  # noqa: E402  — the router: holds every project's notices for itself, rules them and delivers the passes
from stackshot.projects import pages as _pages  # noqa: E402  — the pane gate's module: page freshness, the item settle test, the registry (one copy since an earlier change)
from stackshot.projects import projects as _prj  # noqa: E402  — the project record: a permanent id per page, the lookup by id or key, projects.json
from stackshot.fleet import sessions_registry as _sr  # noqa: E402  — the permanent session id: any reference to a session (id, name, alias, transcript id) → one id, or None
from stackshot.projects.project_registry import _registry, _roles_sync_safe  # noqa: E402  — a registry file of the store, and roles.json with projects.json beside it (projects/project_registry.py)
from stackshot.web import publish as _pubmod  # noqa: E402  — the debounced publish: the writes here call `_pubmod._publish()` and the hook tables look its functions up on that module, so a suite that replaces one sets it on `stackshot.web.publish` (the timer is `_PUB_TIMER` there)
from stackshot.web.publish import _publish_if_idle  # noqa: E402  — the idle test the board's runner rebuild asks (`_runners.ON_CHANGE` in __main__)
from stackshot.service import foryou_hooks as _foryou_hooks  # noqa: E402  — what those rows still reach on this module (service/foryou_hooks.py)
from stackshot.service.projects import _page_io  # noqa: E402  — the page store the hook tables look up (service/projects.py)
from stackshot.service import event_activity as _event_activity  # noqa: E402  — the last-activity pass on a tied pull request's events (the wake table's `event_activity_tick`)
from stackshot.audit import audit_checks as _ac  # noqa: E402  — the audit's code checks: the filing pass, and the broad wait words of an alive item's next


# The For you list's rows (whether he watches an item, the row a save makes, the Landed record, the due-date pass) are service/foryou_events.py's; the dates pass (service/audit_ticks.py) runs the due-date look on that module.


# ----------------------------------------------------------------------------- whose move it is
# Every open item has a MOVER (the one party whose move it is now: waiting.mover_for). No date is derived for it: an item has no "expected by" time
# and is not marked late for one. A parked item (on hold, or after an open item) is held until its wake or its blocker closes; a wait that went wrong
# is caught by the passes that read the item's own fields (the wake pass and the watchers, the dates pass, the failed-check notice, the wait-end audit).
# A wait that can no longer end (a check whose pull request closed unmerged) is recorded as failed when it happens (metadata.wait_failed) and the mover
# is told at once; an `after` item that closes releases the item, whatever way it closed, and the wake notice says so.


# ---- an item's contact (contact.py): the front agent the person the board is for talks to about the item; stored in metadata.contact, a filing field


# ----------------------------------------------------------------------------- MCP surface
# The FastMCP instance, its middleware, the tools and the routes are web/app.py's `build`, called from web/wiring.py, which hands it the callables they take (late-bound, so a suite that replaces one on its owner still reaches it).
mcp = _wiring.build()   # the FastMCP instance, its middleware, the tools and the routes (web/app.py, built in web/wiring.py): what they take from this module is passed late-bound, looked up at each call


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
