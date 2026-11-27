#!/usr/bin/env python3
"""tools/frontdoor_cutover.py: the cut-over of a live switch to the front door, as one run.

    python3 tools/frontdoor_cutover.py --snapshot DIR [--apply]

DIR is the folder tools/frontdoor_snapshot.py made. Dry run by default: only reads, nothing written. It asks no question and commits and pushes nothing.
The one config save of the cut-over is made and pushed first; run this within five minutes of it (the journal check below looks back five minutes).

BEFORE THE RESTART, stopping at the first failed check and restarting nothing:
  nothing answers on 8021 yet (a run after a switch that was made changes nothing)
  the release hold is on with 15 minutes or more left, the release queue is empty, no release runs
  the snapshot holds a single-user config that this code can load, its notes and its archive; no override of an earlier way back is in place
  the saved config is put aside for the way back
  the config is pulled; it holds the cut-over's settings; it has no config note the snapshot's list does not have
  the front door holds the board's machine token; `./install.sh units`
  the board's journal says a key waits for the next restart; the board still answers on its old port
  the test splitter is disabled and stopped

FROM THE BOARD'S RESTART, where the window of 300 s starts; the first check that fails, or a window that runs out, or any error or signal in this
part, brings the board back by itself (tools/frontdoor_undo.py, on the saved config; no person needed, no data touched):
  the board and the minute runner are restarted
  health on 8021, 8030 and 8031; a call to the board without the front door is refused (403)
  the splitter is enabled and started; the portal sync is restarted; `stackshot.frontdoor.check --installed` passes
  health on 8020 and the public address; a call without a sign-in is refused (401) on both

Checks only a person can make are printed as MANUAL lines with the time they are due and the command that undoes the switch.

Exit 0: the dry run's checks pass. 3: every automated check passes, MANUAL checks are pending. 1: stopped before the restart. 2: the script cannot run.
4: a check failed after the restart and the board is back on its old port. 5: it failed and the way back did not complete: a person is needed now.
A run that is killed with SIGKILL, or whose machine goes down, brings nothing back: run the undo script then. Give the run 15 minutes before any outside timeout.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

import frontdoor_switch as fs
import frontdoor_undo as undo

JOURNAL_SINCE = "-5min"
CHECK_INSTALLED_WAIT = 90
MANUAL = (
    ("portal", "a real call through the portal reaches the board"),
    ("connector", "a call from the chat client's connector reaches the board"),
    ("browser", "a browser sign-in on the public address lands on the board"),
    ("tailnet", "the board's tailnet name answers"),
    ("polls", "the puller and the minute runner have polled since the restart (journalctl --user -u stackshot-puller.service -u stackshot-minute.service --since -5min)"),
)
SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


class Failed(Exception):
    """A check that did not pass: the run goes no further."""


class Interrupted(BaseException):
    """A signal asked the run to end."""


def _signals(handler) -> None:
    for s in SIGNALS:
        signal.signal(s, handler)


def _interrupt(number, _frame) -> None:
    _signals(signal.SIG_IGN)                 # one is enough: what follows is the way back, which must not be cut short
    raise Interrupted(signal.Signals(number).name)


def row(name: str, ok: bool, detail: str = "") -> None:
    fs.say("PASS" if ok else "FAIL", name, detail)
    if not ok:
        raise Failed(name)


def saved_checks(co: Path, cfg_path: Path, snapshot: Path) -> None:
    """The way back has to be there before anything is restarted."""
    saved = fs.snapshot_config(snapshot, cfg_path)
    why = undo.usable(saved)
    row("the snapshot holds a single-user config to come back on", not why, "; ".join(why) or str(saved))
    rc, out = fs.run(["env", f"STACKSHOT_CONFIG={saved}", *fs.py_cmd(), "-m", "stackshot.core.config", "check"], cwd=co, timeout=300)
    row("this code can load the saved config", rc == 0, "" if rc == 0 else fs.last_line(out) or f"exit {rc}")
    row("the snapshot holds its list of config notes", (snapshot / fs.SNAPSHOT_NOTES).is_file(), str(snapshot / fs.SNAPSHOT_NOTES))
    archive = snapshot / fs.SNAPSHOT_ARCHIVE
    row("the snapshot holds its archive", archive.is_file() and archive.stat().st_size > 0, str(archive))
    left = fs.overrides_present()
    row("no override of an earlier way back is in place", not left, ", ".join(map(str, left)))


def new_port_answer() -> str:
    return fs.http_code(f"http://127.0.0.1:{fs.NEW_BOARD_PORT}/healthz")


def journal_says_waiting(co: Path) -> tuple[bool, str]:
    end = time.monotonic() + fs.check_seconds()
    while True:
        rc, out = fs.run(["journalctl", "--user", "-u", fs.BOARD_UNIT, "--since", JOURNAL_SINCE, "--no-pager"], cwd=co)
        hits = sum("next restart" in line.lower() for line in out.splitlines()) if rc == 0 else 0
        if hits or time.monotonic() >= end:
            return bool(hits), f"{hits} lines in the last five minutes" if rc == 0 else f"journalctl exit {rc}"
        time.sleep(fs.poll_seconds())


def before_restart(co: Path, cfg_path: Path, snapshot: Path, apply: bool) -> None:
    """Everything up to the restart; raises Failed at the first check that is not green. A dry run reads only."""
    code = new_port_answer()                 # first: a second run on a moved board would stop the splitter that serves it
    row(f"the board has not moved yet (nothing answers on {fs.NEW_BOARD_PORT})", code == "000", f"HTTP {code}")
    state, minutes, line = fs.hold_state(co)
    row(f"release hold on with {fs.MIN_HOLD_MINUTES} minutes or more left", state == "active" and minutes >= fs.MIN_HOLD_MINUTES, line)
    state, line = fs.queue_state(co)
    row("release queue is empty", state == "empty", line)
    running, line = fs.release_running()
    row("no release is running", running is False, line)
    saved_checks(co, cfg_path, snapshot)
    saved = fs.snapshot_config(snapshot, cfg_path)
    if apply:
        copy = undo.store_saved(saved)
        row("the saved config is put aside for the way back", copy.read_bytes() == saved.read_bytes(), str(copy))
        ok, line = fs.pull_config(cfg_path)
        row("the config is pulled (fast forward only)", ok, line)
    else:
        fs.say("PLAN", f"put the saved config aside at {fs.rollback_copy()}")
        fs.say("PLAN", "pull the config (the checks below read it as it is on disk now)")

    cfg = fs.read_toml(cfg_path)
    rows = fs.switched_checks(cfg)
    for name, ok in rows:
        fs.say("PASS" if ok else "FAIL", f"the config holds the cut-over's settings: {name}")
    if fs.failed(rows):
        raise Failed("the config does not hold the cut-over's settings")
    others = fs.other_differences(fs.read_toml(saved), cfg)
    if others:
        fs.say("NOTE", "settings outside the switch differ from the saved config; a way back runs without these changes", ", ".join(others))
    baseline = {x.rstrip() for x in (snapshot / fs.SNAPSHOT_NOTES).read_text(encoding="utf-8").splitlines() if x.strip()}
    ok, notes = fs.config_notes(co)
    new = [n for n in notes if n not in baseline] if ok else []
    row("no config note outside the baseline", ok and not new, " | ".join(new) if ok else notes[0])
    rc, out = fs.run([*fs.py_cmd(), "-m", "stackshot.frontdoor.boardtoken", "--check"], cwd=co, timeout=300)
    row("the front door holds the board's machine token", rc == 0, fs.last_line(out) or f"exit {rc}")

    if not apply:
        for step in ("./install.sh units", "the board's journal says a key waits for the next restart", f"the board answers on {fs.OLD_BOARD_PORT}",
                     "disable and stop the splitter"):
            fs.say("PLAN", step)
        return
    ok, line = fs.install_units(co)
    row("units rendered and installed (`./install.sh units`)", ok, "" if ok else line)
    missing = [u for u in (*fs.RESTORE_UNITS, *fs.FRONT_UNITS, fs.SPLITTER_UNIT) if not (fs.unit_dir() / u).is_file()]
    row("every unit the cut-over and its way back use is installed", not missing, ", ".join(missing))
    ok, line = journal_says_waiting(co)
    row("the board's journal says a key waits for the next restart", ok, line)
    ok, code = fs.wait_code(f"http://127.0.0.1:{fs.OLD_BOARD_PORT}/healthz", "200", fs.check_seconds())
    row(f"the board still answers on {fs.OLD_BOARD_PORT} (healthz)", ok, f"HTTP {code}")
    ok, line = fs.splitter_off()
    row("the splitter is disabled and stopped", ok, line)


def from_restart(co: Path, state: dict) -> fs.Window:
    """From the board's restart on. The window starts here; every program and every check is held to what is left of it. → the window."""
    win = fs.Window(fs.window_seconds())
    state["restarted"] = True                # set before the restart is asked for: a failed or cut-off restart is after it

    def left() -> float:
        seconds = win.left()
        if seconds <= 0:
            raise Failed(f"the window of {win.seconds:.0f} s from the restart is over")
        return seconds

    def unit(name: str, *args: str) -> None:
        ok, line = fs.systemctl(*args, timeout=left())
        row(name, ok, "" if ok else line)

    def answers(name: str, url: str, want: str, method: str = "GET") -> None:
        # a health answer is asked again whatever it was; a refusal only while nothing answers: any other answer to a call that must be refused is final
        again = (lambda code: True) if want == "200" else fs.not_answering
        ok, code = fs.wait_code(url, want, min(fs.check_seconds(), left()), method=method, again=again)
        row(name, ok, f"HTTP {code}")

    local = "http://127.0.0.1:"
    unit("the board and the minute runner are restarted", "restart", fs.BOARD_UNIT, fs.MINUTE_UNIT)
    answers(f"the board answers on {fs.NEW_BOARD_PORT} (healthz)", f"{local}{fs.NEW_BOARD_PORT}/healthz", "200")
    answers(f"the front door answers on {fs.DOOR_PORT} (healthz)", f"{local}{fs.DOOR_PORT}/healthz", "200")
    answers(f"the sign-in answers on {fs.SIGNIN_PORT} (healthz)", f"{local}{fs.SIGNIN_PORT}/healthz", "200")
    answers(f"the board refuses a call without the front door (POST {fs.NEW_BOARD_PORT}/mcp is 403)", f"{local}{fs.NEW_BOARD_PORT}/mcp", "403", "POST")
    unit("the splitter is enabled and started", "enable", "--now", fs.SPLITTER_UNIT)
    unit("the portal sync is restarted", "restart", fs.SYNC_UNIT)
    seconds = left()
    rc, out = fs.run([*fs.py_cmd(), "-m", "stackshot.frontdoor.check", "--installed", "--wait", str(int(min(CHECK_INSTALLED_WAIT, seconds)))], cwd=co, timeout=seconds)
    if rc != 0:
        fs.emit(out.rstrip())
    row("`stackshot.frontdoor.check --installed` passes", rc == 0, fs.last_line(out) or f"exit {rc}")
    public = fs.public_url()
    answers(f"the board answers on {fs.OLD_BOARD_PORT} (healthz)", f"{local}{fs.OLD_BOARD_PORT}/healthz", "200")
    answers(f"a call without a sign-in is refused on {fs.OLD_BOARD_PORT} (POST /mcp is 401)", f"{local}{fs.OLD_BOARD_PORT}/mcp", "401", "POST")
    answers("the public address answers (healthz)", f"{public}/healthz", "200")
    answers("a call without a sign-in is refused on the public address (POST /mcp is 401)", f"{public}/mcp", "401", "POST")
    left()                                   # green, but too late, is not green
    return win


def stopped_before_restart(co: Path, cfg_path: Path, snapshot: Path) -> int:
    fs.emit("STOPPED before the restart: this run restarted nothing, and no automatic way back was needed")
    if new_port_answer() != "000":
        fs.emit(f"something answers on {fs.NEW_BOARD_PORT} already: a switch that has been made needs no second cut-over. Look before undoing anything")
    elif fs.failed(fs.single_user_checks(fs.read_toml(cfg_path))):
        fs.emit("the config on disk shows the switch: a restart of the board for any reason would now move it. Do not fix forward; undo:")
        fs.say("OPERATOR", "1", "revert the config commit of the cut-over, push, and pull it on this machine")
        fs.say("OPERATOR", "2", f"in {co}: ./install.sh units")
        fs.say("OPERATOR", "3", "undo the earlier steps in reverse order, or the whole switch with the command below")
    else:
        fs.emit("the config on disk is still a single-user config")
    fs.say("UNDO", fs.command("frontdoor_undo.py", "--apply", "--snapshot", str(snapshot)) + "   (restarts the board; on the saved config while the pulled one shows the switch)")
    return fs.FAILED


def passed(cfg_path: Path, win: fs.Window) -> int:
    due = fs.clock(fs.read_toml(cfg_path), win.end_epoch)
    fs.emit(f"every automated check passes, with {max(0.0, win.left()):.0f} s of the window left; MANUAL checks are pending")
    for name, text in MANUAL:
        fs.say("MANUAL", f"{name}: {text}")
    fs.emit(f"make them by {due}. If one fails, or they are not all green by then, undo the switch at once:")
    fs.say("UNDO", fs.command("frontdoor_undo.py", "--apply"))
    fs.emit("when all are green: end the release hold (./release.sh hold --end), and keep the snapshot for a few days")
    return fs.PENDING


def cut_over(co: Path, cfg_path: Path, snapshot: Path) -> int:
    state = {"restarted": False}
    _signals(_interrupt)
    try:
        try:
            before_restart(co, cfg_path, snapshot, apply=True)
            win = from_restart(co, state)
        finally:
            _signals(signal.SIG_IGN)         # inside the outer try: a signal that lands on this line is still answered by the way back
    except BaseException as e:               # a failed check, a signal, a bug here: after the restart the board comes back whatever it was
        why = str(e) if isinstance(e, Failed) else f"{type(e).__name__}: {e}"
        fs.emit(f"stopped: {why}")
        if not state["restarted"]:
            return stopped_before_restart(co, cfg_path, snapshot)
        fs.emit("stopped after the restart: bringing the board back now")
        try:
            rc = undo.way_back(co, cfg_path, None, apply=True, end_hold=False)
        except BaseException as again:       # reported, never swallowed: the exit code says a person is needed
            fs.emit(f"THE WAY BACK IS NOT COMPLETE, a person is needed now: {type(again).__name__}: {again}")
            fs.say("UNDO", fs.command("frontdoor_undo.py", "--apply"))
            return fs.INCOMPLETE
        return fs.ROLLED_BACK if rc in (fs.ROLLED_BACK, fs.PENDING) else fs.INCOMPLETE
    return passed(cfg_path, win)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/frontdoor_cutover.py", description="The cut-over of a live switch to the front door, as one run.")
    ap.add_argument("--snapshot", required=True, metavar="DIR", help="the folder tools/frontdoor_snapshot.py made: its config is what the way back runs on")
    ap.add_argument("--apply", action="store_true", help="run the cut-over (default: a dry run that changes nothing)")
    a = ap.parse_args(argv)
    co = fs.checkout()
    try:
        cfg_path = fs.config_path()
        snapshot = Path(a.snapshot).expanduser().resolve()
        if not snapshot.is_dir():
            raise fs.Usage(f"--snapshot names no folder: {snapshot}")
        if cfg_path.resolve() == fs.rollback_copy().resolve():
            raise fs.Usage(f"STACKSHOT_CONFIG is the saved copy {cfg_path}: point it at the instance's own config")
        if a.apply:
            fs.need_public_url()
    except fs.Usage as e:
        return fs.cannot(e)

    if a.apply:
        return cut_over(co, cfg_path, snapshot)
    fs.emit(f"dry run: reads only; the window from the restart would be {fs.window_seconds():.0f} s")
    try:
        before_restart(co, cfg_path, snapshot, apply=False)
    except Failed as e:
        fs.emit(f"dry run: the run would stop at: {e}")
        return fs.FAILED
    fs.say("PLAN", "restart the board and the minute runner; then the checks, and the way back at the first one that fails")
    for name, text in MANUAL:
        fs.say("PLAN", f"manual afterwards: {name}: {text}")
    fs.emit("dry run: nothing changed (add --apply)")
    return fs.OK


if __name__ == "__main__":
    sys.exit(main())
