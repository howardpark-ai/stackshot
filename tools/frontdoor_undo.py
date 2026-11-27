#!/usr/bin/env python3
"""tools/frontdoor_undo.py: the way back from a live switch to the single-user board on its old port.

    python3 tools/frontdoor_undo.py [--apply] [--snapshot DIR] [--end-hold]
    python3 tools/frontdoor_undo.py [--apply] --drop-saved

Dry run by default: it prints what it would do and writes nothing. It asks no question. It commits and pushes nothing. With --apply it ignores the signals
that would end it (an interrupt, a hangup, a termination, quit, the user signals) from before its first change to its end, so a dropped terminal leaves no
half of a way back; each program it runs has a time limit. One run of the scripts that write goes at a time (a lock). Which way it goes is read from the
config on disk (STACKSHOT_CONFIG):

THE CONFIG IS REVERTED (the commits of the switch are reverted, pushed and pulled)
  1  the splitter is disabled and stopped (left enabled it would take the board's old port at the next boot)
  2  an override of an earlier run is removed
  3  `./install.sh units`
  4  the board is restarted; it answers on its old port
  5  the minute runner and the portal sync are restarted
  6  the board answers on the public address

THE CONFIG STILL SHOWS THE SWITCH (the cut-over runs this by itself after a failed check)
  The board comes back on a SAVED copy of the single-user config: the one the cut-over put aside from the snapshot, or the one in --snapshot DIR. A saved
  copy that no unit reads and that is more than a day old may be left from an earlier switch: it is refused, and --snapshot DIR is asked for.
  1  the splitter is disabled and stopped
  2  a drop-in for the same three units points STACKSHOT_CONFIG at the saved copy (it holds across a reboot, and `install.sh units` leaves it)
  3  the board is restarted; it answers on its old port
  4  the minute runner and the portal sync are restarted
  5  the board answers on the public address
  A person still has to revert the commits of the switch, push and pull, run this script again (it removes the override) and end the release hold. These
  steps are printed on every end of this way, a failed one included.

NO DATA IS RESTORED OR REMOVED, either way: the board's records stay as they are, with everything written since the snapshot. The snapshot's archive
is not used.

--drop-saved removes the saved copy of a switch that is kept. It is refused while an override makes a unit read the copy.

When the cut-over runs this, every program is held to what is left of the cut-over's window, and the portal sync's restart is asked for and not waited for.

Exit 3: reverted config, the automated checks pass, MANUAL checks are left. 4: the board is back on the saved config, the revert is left.
5: a step or a check failed, a person is needed now. 1: refused (neither a reverted nor a saved config, or another run holds the lock), nothing changed.
2: the script cannot run. A dry run exits 0, or 1 when it would refuse. FRONTDOOR_PUBLIC_URL is required with --apply (not with --drop-saved).
"""
from __future__ import annotations

import argparse
import shlex
import sys
import time
from pathlib import Path

import frontdoor_switch as fs

MANUAL = (
    ("portal", "a real call from the portal reaches the board (for example a brief)"),
    ("browser", "a browser sign-in on the public address lands on the board"),
)
NO_DATA = ("no data was restored or removed: the board's records are as they are, with everything written since the snapshot; the snapshot's archive is not used "
           "(putting it back by hand would drop what was written since)")


class Report:
    """The steps of one way back: every step runs, and what failed is remembered for the exit code."""

    def __init__(self):
        self.bad: list[str] = []

    def row(self, name: str, ok: bool, detail: str = "") -> bool:
        fs.say("PASS" if ok else "FAIL", name, detail)
        if not ok:
            self.bad.append(name)
        return ok


def usable(path: Path) -> list[str]:
    """Why the file at `path` cannot be the config the board comes back on ([] when it can)."""
    if not path.is_file():
        return [f"there is no file {path}"]
    return [f"{path} is not a single-user config: {name} does not hold" for name in fs.failed(fs.single_user_checks(fs.read_toml(path)))]


def stale(saved: Path) -> list[str]:
    """Why the saved copy, taken without being named, may be an earlier switch's ([] when it is this one's)."""
    if fs.overrides_present() or not saved.is_file():
        return []
    age = time.time() - saved.stat().st_mtime
    if age <= fs.SAVED_COPY_SECONDS:
        return []
    return [f"{saved} is {age / 3600:.0f} hours old and no unit reads it, so it may be left from an earlier switch: give --snapshot DIR"]


def store_saved(source: Path) -> Path:
    """Put the saved config where the board is to read it (600, in a folder of its own)."""
    dest = fs.rollback_copy()
    dest.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    dest.parent.chmod(0o700)
    fs.write_private(dest, source.read_bytes())
    return dest


def override_text(config: Path) -> str:
    value = str(config).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")        # systemd's quoting, and %% for its specifiers
    return ("# Written by tools/frontdoor_undo.py: this unit reads the saved single-user config until the front door switch is reverted.\n"
            "# The same script removes this file once the config is reverted and pulled.\n"
            f'[Service]\nEnvironment="STACKSHOT_CONFIG={value}"\n')


def write_overrides(config: Path, rep: Report) -> None:
    for unit in fs.RESTORE_UNITS:
        p = fs.override_path(unit)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            fs.write_private(p, override_text(config).encode("utf-8"))
            rep.row(f"override written for {unit}", True, str(p))
        except OSError as e:
            rep.row(f"override written for {unit}", False, str(e))


def remove_overrides(rep: Report) -> None:
    for p in fs.overrides_present():
        try:
            p.unlink()
            rep.row("override removed", True, str(p))
        except OSError as e:
            rep.row("override removed", False, str(e))
            continue
        try:
            p.parent.rmdir()                 # only when nothing else is in it (the board's own drop-in folder keeps its other files)
        except OSError:
            pass


def reload_systemd(rep: Report, lim: fs.Limits) -> None:
    ok, line = fs.systemctl("daemon-reload", timeout=lim.act())
    rep.row("systemd read the unit files again", ok, "" if ok else line)


def restart(unit: str, rep: Report, lim: fs.Limits, queued: bool = False) -> None:
    """Restart one unit. queued: ask systemd for it and go on (a one-shot unit is only back when its program has ended)."""
    fs.systemctl("reset-failed", unit, timeout=lim.read())         # a unit that hit its start limit would refuse the restart; nothing to reset is no failure
    ok, line = fs.systemctl("restart", *(("--no-block",) if queued else ()), unit, timeout=lim.restart())
    rep.row(f"restart of {unit} asked for, not waited for" if queued and ok else f"restarted {unit}", ok, "" if ok else line)


def restart_and_check(public: str, rep: Report, lim: fs.Limits) -> None:
    """The board first, and its answer, so that nothing else stands between the board and being back."""
    restart(fs.BOARD_UNIT, rep, lim)
    ok, code = fs.wait_code(f"http://127.0.0.1:{fs.OLD_BOARD_PORT}/healthz", "200", lim.answers().left())
    rep.row(f"the board answers on {fs.OLD_BOARD_PORT} (healthz)", ok, f"HTTP {code}")
    if lim.window is not None:
        fs.emit(f"{lim.window.seconds - lim.window.left():.0f} s after the first restart (the window is {lim.window.seconds:.0f} s)"
                + (": LATER THAN THE WINDOW" if lim.window.left() < 0 else ""))
    running, state = fs.unit_active(fs.BOARD_UNIT, lim.read())
    rep.row(f"{fs.BOARD_UNIT} is running", running, state)
    restart(fs.MINUTE_UNIT, rep, lim)
    restart(fs.SYNC_UNIT, rep, lim, queued=lim.window is not None)
    ok, code = fs.wait_code(f"{public}/healthz", "200", lim.answers().left())
    rep.row("the public address answers (healthz)", ok, f"HTTP {code}")


def splitter_step(rep: Report, lim: fs.Limits) -> None:
    ok, line = fs.splitter_off(lim.act(), lim.read())
    rep.row("the splitter is disabled and stopped", ok, line)


def manual_lines() -> None:
    for name, text in MANUAL:
        fs.say("MANUAL", f"{name}: {text}")


def end_hold_command(co: Path) -> str:
    return shlex.join([str(co / "release.sh"), "hold", "--end"])


def left_on_saved(co: Path, cfg_path: Path, refused: bool = False) -> None:
    """Everything a person still has to do while the pulled config shows the switch. Printed on every end of that way, whatever worked."""
    repo = fs.config_repo(cfg_path)
    steps = []
    if refused:
        steps.append("disable the splitter: " + shlex.join(["systemctl", "--user", "disable", "--now", fs.SPLITTER_UNIT]))
    steps.append(f"in the config's repository{f' ({repo})' if repo else ''}, revert the commits of the switch, newest first (the cut-over, the test splitter, the settings), and push")
    steps.append("pull it on this machine: " + (shlex.join(["git", "-C", str(repo), "pull", "--ff-only"]) if repo else "git pull --ff-only in that repository"))
    again = len(steps) + 1
    steps.append(f"remove the override and run on the reverted config: {fs.command('frontdoor_undo.py', '--apply')}")
    steps.append(f"end the release hold, only after step {again} has passed: {end_hold_command(co)}")
    for number, step in enumerate(steps, 1):
        fs.say("OPERATOR", str(number), step)
    if fs.rollback_copy().is_file():
        fs.say("NOTE", f"the saved copy of the config stays until step {again} has passed", str(fs.rollback_copy()))
    if fs.overrides_present():
        fs.say("NOTE", f"until step {again} the units with an override do not see a change to the config; other units and command-line calls still read the pulled config, which shows the switch")
    else:
        fs.say("NOTE", "no override is in place: the units read the pulled config, which shows the switch")
    fs.say("NOTE", f"keep releases held until step {again} (a hold ends by itself after two hours at most): a release deployed before it looks for the board on the pulled config's port and fails")


def left_on_reverted(co: Path, held: bool, failed: bool = False) -> None:
    """What is left on a reverted config, printed on every end of that way. held: the release hold was not ended by this run."""
    if held and failed:
        fs.say("OPERATOR", "1", f"end the release hold, only once a run of the undo has passed: {end_hold_command(co)}")
    elif held:
        fs.say("OPTION", "end the release hold", end_hold_command(co))
    if held:
        fs.say("NOTE", "a release hold also ends by itself, after two hours at most")
    if failed and fs.rollback_copy().is_file():
        fs.say("NOTE", "the saved copy of the config stays until a run on the reverted config passes", str(fs.rollback_copy()))
    fs.say("OPTION", "stop the front door and the sign-in", "systemctl --user disable --now " + " ".join(fs.FRONT_UNITS))
    fs.say("OPTION", "undo the step that changed the tailnet proxy, by its own undo")


def incomplete(rep: Report, again: list[str]) -> int:
    fs.emit(f"THE WAY BACK IS NOT COMPLETE, a person is needed now. Failed: {'; '.join(rep.bad)}")
    fs.say("NOTE", "look with", f"systemctl --user status {' '.join((fs.BOARD_UNIT, fs.SPLITTER_UNIT))}")
    fs.say("NOTE", "and with", f"journalctl --user -u {fs.BOARD_UNIT} --since -10min")
    fs.emit("then run again:")
    fs.say("UNDO", fs.command("frontdoor_undo.py", *again))
    fs.emit(NO_DATA)
    return fs.INCOMPLETE


def back_on_reverted(co: Path, public: str, end_hold: bool, again: list[str], lim: fs.Limits) -> int:
    rep = Report()
    splitter_step(rep, lim)
    if fs.overrides_present():
        remove_overrides(rep)
        reload_systemd(rep, lim)
    ok, line = fs.install_units(co, lim.install())
    rep.row("units rendered and installed (`./install.sh units`)", ok, "" if ok else line)
    restart_and_check(public, rep, lim)
    if rep.bad:
        rc = incomplete(rep, again)
        left_on_reverted(co, held=True, failed=True)
        return rc
    saved = fs.rollback_copy()
    if saved.is_file() and not fs.overrides_present():
        saved.unlink()                       # nothing reads it now, and a later way back must not find an old one
        fs.say("DONE", "the saved copy of the config is removed", str(saved))
    if end_hold:
        state, _, line = fs.hold_state(co)
        if state == "none":
            rep.row("no release hold to end", True, line)
        else:
            rc, out = fs.run([str(co / "release.sh"), "hold", "--end"], cwd=co)
            rep.row("release hold ended", rc == 0, fs.last_line(out) or f"exit {rc}")
        if rep.bad:
            rc = incomplete(rep, again)
            left_on_reverted(co, held=True, failed=True)
            return rc
    fs.emit(f"the board is back on {fs.OLD_BOARD_PORT} on the reverted config; the automated checks pass, MANUAL checks are pending")
    fs.emit(NO_DATA)
    manual_lines()
    left_on_reverted(co, held=not end_hold)
    return fs.PENDING


def back_on_saved(co: Path, cfg_path: Path, saved: Path, public: str, end_hold: bool, again: list[str], lim: fs.Limits) -> int:
    rep = Report()
    splitter_step(rep, lim)
    try:
        if saved != fs.rollback_copy():
            saved = store_saved(saved)
        rep.row("the saved single-user config is in place", True, str(saved))
    except OSError as e:
        rep.row("the saved single-user config is in place", False, str(e))
        rc = incomplete(rep, again)
        left_on_saved(co, cfg_path)
        return rc
    write_overrides(saved, rep)
    reload_systemd(rep, lim)
    restart_and_check(public, rep, lim)
    if rep.bad:
        rc = incomplete(rep, again)
        left_on_saved(co, cfg_path)
        return rc
    fs.emit(f"THE BOARD IS BACK on {fs.OLD_BOARD_PORT}, on the SAVED copy of the config; the automated checks pass, MANUAL checks are pending")
    fs.emit(NO_DATA)
    differ_note(saved, cfg_path)
    manual_lines()
    left_on_saved(co, cfg_path)
    if end_hold:
        fs.say("NOTE", "--end-hold was not done: end the hold after the revert (the run on the reverted config takes --end-hold)")
    return fs.ROLLED_BACK


def differ_note(saved: Path, cfg_path: Path) -> None:
    now = fs.read_toml(cfg_path)
    if now is None:
        fs.say("NOTE", "the pulled config cannot be read, so it was not compared with the saved one")
        return
    names = fs.other_differences(fs.read_toml(saved), now)
    if names:
        fs.say("NOTE", "outside the switch's own settings the saved config differs from the pulled one, and the board runs without these changes until the revert",
               ", ".join(names))


def way_back(co: Path, cfg_path: Path, snapshot: Path | None, apply: bool, end_hold: bool, window: fs.Window | None = None) -> int:
    """Bring the board back; the lines are printed as they happen. Returns the exit code. window: the cut-over's, which every program is then held to."""
    public = fs.need_public_url() if apply else fs.public_url()
    if cfg_path.resolve() == fs.rollback_copy().resolve():
        raise fs.Usage(f"STACKSHOT_CONFIG is the saved copy {cfg_path}: point it at the instance's own config")
    cfg = fs.read_toml(cfg_path)
    not_reverted = fs.failed(fs.single_user_checks(cfg))
    source = (snapshot / cfg_path.name) if snapshot else fs.rollback_copy()
    why_not = (usable(source) or ([] if snapshot else stale(source))) if not_reverted else []

    if not not_reverted:
        fs.say("NOTE", "the config on disk is a single-user config: the way back runs on it")
        left = [t for t in fs.SWITCH_TABLES if fs.setting(cfg, t) is not None]
        if left:
            fs.say("NOTE", "tables of the switch are still in the config (the undo of the whole switch reverts the settings and the test splitter too)", ", ".join(left))
    else:
        fs.say("NOTE", "the config on disk still shows the switch", "; ".join(not_reverted))

    if why_not:
        fs.say("REFUSE", "no config the board can come back on", "; ".join(why_not))
        fs.emit("nothing was changed. Do this, or run this again with --snapshot DIR:")
        left_on_saved(co, cfg_path, refused=True)
        return fs.FAILED

    if not apply:
        steps = ["disable and stop the splitter"]
        if not_reverted:
            steps += [f"write an override for {', '.join(fs.RESTORE_UNITS)} that reads the saved config ({source})", "systemctl --user daemon-reload"]
        else:
            if fs.overrides_present():
                steps += ["remove the override of an earlier run", "systemctl --user daemon-reload"]
            steps += ["./install.sh units"]
        steps += [f"restart {fs.BOARD_UNIT} and check {fs.OLD_BOARD_PORT} within {fs.undo_window_seconds():.0f} s",
                  f"restart {fs.MINUTE_UNIT} and {fs.SYNC_UNIT}, and check the public address within {fs.undo_window_seconds():.0f} s"]
        if end_hold and not not_reverted:
            steps.append("release.sh hold --end")
        for i, s in enumerate(steps, 1):
            fs.say("PLAN", f"step {i}", s)
        if not_reverted:
            fs.emit("what would be left for a person afterwards:")
            left_on_saved(co, cfg_path)
        fs.emit(NO_DATA.replace("no data was", "no data would be"))
        fs.emit("dry run: nothing changed (add --apply)")
        return fs.OK

    again = ["--apply", *(["--snapshot", str(snapshot)] if snapshot else []), *(["--end-hold"] if end_hold else [])]
    lim = fs.Limits(window)
    try:
        if not_reverted:
            return back_on_saved(co, cfg_path, source, public, end_hold, again, lim)
        return back_on_reverted(co, public, end_hold, again, lim)
    except BaseException:
        fs.say("UNDO", fs.command("frontdoor_undo.py", *again))          # a bug here still leaves the person with all that is to be done
        if not_reverted:
            left_on_saved(co, cfg_path)
        else:
            left_on_reverted(co, held=True, failed=True)
        raise


def drop_saved(apply: bool) -> int:
    """Remove the saved copy of a switch that is kept: a later way back must not take it for its own."""
    saved = fs.rollback_copy()
    if fs.overrides_present():
        fs.say("REFUSE", "units read the saved copy through an override, so it stays: revert the config, pull, and run the undo")
        fs.say("UNDO", fs.command("frontdoor_undo.py", "--apply"))
        return fs.FAILED
    if not saved.is_file():
        fs.say("PASS", "there is no saved copy of the config to remove", str(saved))
        return fs.OK
    if not apply:
        fs.say("PLAN", "remove the saved copy of the config", str(saved))
        fs.emit("dry run: nothing changed (add --apply)")
        return fs.OK
    saved.unlink()
    fs.say("DONE", "the saved copy of the config is removed", str(saved))
    fs.say("NOTE", "a later way back while the config shows the switch needs --snapshot DIR")
    return fs.OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/frontdoor_undo.py", description="The way back from a live switch to the single-user board on its old port.")
    ap.add_argument("--apply", action="store_true", help="run the steps (default: a dry run that changes nothing)")
    ap.add_argument("--snapshot", metavar="DIR", help="the snapshot folder whose config the board comes back on while the pulled config shows the switch")
    ap.add_argument("--end-hold", action="store_true", help="also end the release hold (only on a reverted config)")
    ap.add_argument("--drop-saved", action="store_true", help="the switch is kept: remove the saved copy of the old config, and nothing else")
    a = ap.parse_args(argv)
    if a.drop_saved and (a.snapshot or a.end_hold):
        ap.error("--drop-saved goes alone (with --apply or without)")
    try:
        if a.drop_saved:
            if a.apply:
                fs.take_lock()
            return drop_saved(a.apply)
        fs.check_settings()
        snapshot = Path(a.snapshot).expanduser().resolve() if a.snapshot else None
        co, cfg_path = fs.checkout(), fs.config_path()
        if a.apply:
            fs.take_lock()
            fs.shield()                      # from here to the end: a way back that is cut short leaves the board worse than before it
        return way_back(co, cfg_path, snapshot, a.apply, a.end_hold)
    except fs.Usage as e:
        return fs.cannot(e)
    except fs.Locked as e:
        fs.say("REFUSE", str(e))
        return fs.FAILED
    except Exception as e:
        if not a.apply:
            raise
        fs.emit(f"THE WAY BACK IS NOT COMPLETE, a person is needed now: {type(e).__name__}: {e}")
        return fs.INCOMPLETE


if __name__ == "__main__":
    sys.exit(main())
