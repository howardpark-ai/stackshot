"""minute.py: `stackshot minute`, the minute set's runner as a process of its own.

With `[runner] process = "unit"` the server starts no runner thread and this process runs the runner instead: the same `Runner` over the same tick table (service/runner.py), the wake file, the hold file and the
status file the two sides share (core/runner_files.py). With `"inline"` set, the server runs the runner as a thread and this process refuses to start; with the setting absent the default is "unit", so this is the process that runs it.

What it does, in order:
  1. installs its signal handlers first (SIGTERM and SIGINT stop it, SIGHUP asks for a config reload): a reload signal that comes while the server's modules are still being imported is kept, never fatal
  2. refuses, with one stderr line and an exit code of its own, when no config is named and this is not the production checkout (as the server does, before it reads or writes anything), when the instance is a read-only standby,
     and when `[runner] process` is "inline" (the server runs the runner)
  3. takes the runner's lock (`<paths.state>/minute/runner.lock`, a flock held for the life of the process): exactly one process runs the runner, so a second `stackshot minute`, or a server that has the runner inline,
     makes this one refuse
  4. imports the server's wiring AS A MODULE (`stackshot.web.server`, never run as `__main__`), so the hook tables of the service areas are installed in the order the server installs them (`install_early`, `build`,
     `install_late`; tests/phase_sweep_scenario.py pins it). That starts no thread and runs none of the server's start-time passes (the migrations, the refile and wake passes stay in the server)
  5. waits until the server answers `GET /healthz` with `ok`, as the receiver's unit does before it starts: the server answers only after its start-time passes, so the store is migrated before the first tick. It waits for as long
     as it takes and says so on stderr every 30 seconds; a stop signal ends the wait
  6. builds the runner (`service/runner.make`, the same one the server builds) and starts its thread, saying first that this process serves the instance (`publish.serving`: its ticks publish as the server's do), and
     reloads the config on SIGHUP as the server's reload does for what the runner reads (the config, the stall pause)
  7. on SIGTERM or SIGINT asks the runner to stop and waits up to `--stop-wait` seconds for the round that is running (a tick is never cut off before that); a tick that is still running after it is abandoned, which is safe
     (every tick is meant to be run again), the lock is released and the process exits 0

It starts no other thread of the server: not the router, the search index, the GitHub mirror, the publish loop or the runner's watchdog (the server's watchdog reads the status file this process writes).

Exit codes: 0 stopped by a signal · 1 failed (an uncaught error: a restart is right; also an option out of range, `--ready-poll` not above zero or `--stop-wait` below zero: one line, nothing started) · 2 no config named outside the production checkout, or a bad option · 3 the setting is "inline" · 4 a read-only standby ·
5 the runner's lock is held by another process · 6 the runner's lock could not be had (the lock file could not be opened). 2, 3 and 4 do not change by themselves, so a restart does not help; 5 and 6 can.

    stackshot minute [--ready-poll SECONDS] [--stop-wait SECONDS]"""
from __future__ import annotations

import argparse
import math
import os
import signal
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

from stackshot import paths as _paths
from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro
from stackshot.core import runner_files as _files

EXIT_STOPPED, EXIT_FAILED, EXIT_USAGE, EXIT_INLINE, EXIT_STANDBY, EXIT_LOCK_HELD, EXIT_LOCK_ERROR = 0, 1, 2, 3, 4, 5, 6
READY_POLL = 2.0              # seconds between two looks at /healthz while the server is not up
READY_TIMEOUT = 3.0           # one look: the server's socket may accept and not answer until its start-time passes have ended
READY_SAY = 30.0              # seconds between two "waiting" lines
STOP_WAIT = 30.0              # seconds a stop signal waits for the round that is running before it abandons the tick
LOOP_POLL = 0.5               # the main loop looks at the stop and reload flags this often
PRODUCTION_CHECKOUT = "~/stackshot"     # as web/server.py: a run from any other checkout needs STACKSHOT_CONFIG


def _say(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _refuse_unconfigured() -> None:
    """Exit 2 when no config is named in the environment and this file is not in the production checkout: the runner writes the live store, so a bare run of a development checkout must never reach it (web/server.py does the same
    before it reads or writes anything)."""
    if os.environ.get("STACKSHOT_CONFIG") or os.environ.get("BOARD_MCP_CONFIG"):
        return
    here = _paths.ROOT
    prod = Path(os.path.expanduser(PRODUCTION_CHECKOUT)).resolve()
    if here != prod:
        _say(f"stackshot minute: not started: STACKSHOT_CONFIG is unset and {here} is not the production checkout ({prod}), so this run would use {_cfg.PATH}. "
             f"Set STACKSHOT_CONFIG to a test config; nothing was touched.")
        sys.exit(EXIT_USAGE)


def healthz_url() -> str:
    """The server's /healthz on its own [server] host and port (a wildcard host is reached through the loopback address)."""
    s = _cfg.CFG["server"]
    host, port = str(s["host"]).strip(), int(s["port"])
    if host in ("", "0.0.0.0"):
        host = "127.0.0.1"
    elif host in ("::", "[::]"):
        host = "::1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/healthz"


def server_ready(url: str, timeout: float = READY_TIMEOUT) -> bool:
    """One look at /healthz: True when the server answers 200 and its body starts with `ok`. Never raises (a refused connection, a timeout, an odd answer are all "not yet"); no proxy is used."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as r:
            return r.status == 200 and r.read(64).decode("utf-8", "replace").split()[:1] == ["ok"]
    except Exception:  # noqa: BLE001
        return False


def wait_ready(stop: threading.Event, url: str, poll: float = READY_POLL, say: Callable[[str], None] = _say, every: float = READY_SAY) -> bool:
    """Wait until the server answers at `url`. → True when it did, False when `stop` was set first (no look is made after it is). One "waiting" line at the first look and one every `every` seconds after."""
    last = None
    while not stop.is_set():
        if server_ready(url):
            return True
        now = time.monotonic()
        if last is None or now - last >= every:
            last = now
            say(f"stackshot minute: waiting for the server at {url}: it answers after its start-time passes, and the runner starts then")
        stop.wait(poll)
    return False


def reload_config() -> None:
    """SIGHUP: re-read stackshot.toml as the server's reload does (a valid file is live at once, a broken one is logged and the running config kept, a restart-only key waits for the restart), and begin the stall pause's
    clock afresh. The server's own reload also runs the phase sweep and the publish: they stay the server's."""
    changed = _cfg.reload()
    if changed is None:
        _say("config reload: failed, nothing changed")
        return
    _say(f"config reload: {', '.join(changed) if changed else 'no live setting changed'}" + (f"; waiting for a restart: {', '.join(_cfg.PENDING)}" if _cfg.PENDING else ""))
    try:
        from stackshot.service import stall as _stallsvc
        _stallsvc.stall_pause_reload()
        _stallsvc.stall_pause_check()
    except Exception as e:  # noqa: BLE001
        _say(f"config reload: stall pause not checked: {e.__class__.__name__}: {e}")


def run(stop: threading.Event, hup: threading.Event, ready_poll: float = READY_POLL, stop_wait: float = STOP_WAIT) -> int:
    """Everything after the lock is taken: import the server's wiring, wait for the server, run the runner until `stop`, stop it. → the exit code."""
    from stackshot.web import server as _server      # noqa: F401  — the wiring: the hook tables are installed at its import, in the server's order; nothing starts (no thread, no start-time pass)
    from stackshot.web import publish as _publish
    from stackshot.core import runner as _minute
    from stackshot.service import runner as _runner
    from stackshot.service import stall as _stallsvc
    if not wait_ready(stop, healthz_url(), ready_poll):
        _say("stackshot minute: stopped before the server was up; no runner was started")
        return EXIT_STOPPED
    _stallsvc.stall_pause_reload()
    try:
        _stallsvc.stall_pause_check()                   # a pause of the stall pass read at the start begins its clock now, as the server's start does
    except Exception as e:  # noqa: BLE001
        _say(f"stackshot minute: stall pause not checked: {e.__class__.__name__}: {e}")
    _say(f"stackshot minute: runner (pid {os.getpid()}; one thread, one lock, paced rounds every {_minute.PACE:g} s)")
    if not _runner.RUNNER:
        _runner.RUNNER[:] = [_runner.make()]
    rn = _runner.RUNNER[0]
    _publish.serving()                  # the runner is part of the server: its ticks' publishes ask nothing about the host (web/publish.py)
    rn.start()
    while not stop.wait(LOOP_POLL):
        if hup.is_set():
            hup.clear()
            reload_config()
    _say("stackshot minute: stopping: the round that is running finishes first")
    if rn.stop(stop_wait):
        _say("stackshot minute: stopped")
    else:
        _say(f"stackshot minute: a tick was still running after {stop_wait:g} s and is abandoned (every tick is run again by the next runner)")
    return EXIT_STOPPED


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stackshot minute", description="Run the minute set's runner as a process of its own (the default, and what [runner] process = \"unit\" says; the server then starts none). "
                                 "Exactly one process runs the runner: a second one, or a server that has it inline, makes this one refuse.")
    ap.add_argument("--ready-poll", type=float, default=READY_POLL, metavar="SECONDS", help=f"seconds between looks at the server's /healthz while it is not up (default {READY_POLL:g})")
    ap.add_argument("--stop-wait", type=float, default=STOP_WAIT, metavar="SECONDS", help=f"seconds a stop signal waits for the round that is running before it abandons the tick (default {STOP_WAIT:g})")
    args = ap.parse_args(argv)
    if not (math.isfinite(args.ready_poll) and args.ready_poll > 0):       # refused, not clamped: a unit that passes a zero would otherwise look at /healthz in a tight loop and say nothing
        _say(f"stackshot minute: not started: --ready-poll must be a number of seconds above zero (got {args.ready_poll:g})")
        return EXIT_FAILED
    if not (math.isfinite(args.stop_wait) and args.stop_wait >= 0):
        _say(f"stackshot minute: not started: --stop-wait must be a number of seconds, zero or more (got {args.stop_wait:g})")
        return EXIT_FAILED
    stop, hup = threading.Event(), threading.Event()
    old = {s: signal.signal(s, h) for s, h in ((signal.SIGTERM, lambda *_: stop.set()), (signal.SIGINT, lambda *_: stop.set()), (signal.SIGHUP, lambda *_: hup.set()))}     # the previous handlers, put back when main returns (a test calls it in-process)
    try:
        _refuse_unconfigured()
        if _ro.is_read_only():
            _say("stackshot minute: not started: this is a read-only standby (STACKSHOT_READ_ONLY); it runs no runner and writes nothing")
            return EXIT_STANDBY
        if _cfg.runner_process() != "unit":
            _say('stackshot minute: not started: [runner] process is "inline", so the server runs the minute set\'s runner itself; set it to "unit" (or remove the line: "unit" is the default) and restart the server to run it here')
            return EXIT_INLINE
        got = _files.lock_take()
        if got.state == "held":
            _say(f"stackshot minute: not started: the runner lock is held by {'pid ' + str(got.pid) if got.pid else 'another process'} ({_files.LOCK} in {_files.DIR}/ of the state folder); exactly one process runs the runner")
            return EXIT_LOCK_HELD
        if got.state != "taken":
            _say(f"stackshot minute: not started: the runner lock could not be had ({got.why})")
            return EXIT_LOCK_ERROR
        try:
            return run(stop, hup, args.ready_poll, args.stop_wait)
        finally:
            _files.lock_release()
    finally:
        for s, h in old.items():
            signal.signal(s, signal.SIG_DFL if h is None else h)


if __name__ == "__main__":
    sys.exit(main())
