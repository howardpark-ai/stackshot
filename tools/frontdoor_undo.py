#!/usr/bin/env python3
"""tools/frontdoor_undo.py: the way back from a live switch to the single-user board on its old port.

    python3 tools/frontdoor_undo.py [--apply] [--saved] [--snapshot DIR] [--end-hold]
    python3 tools/frontdoor_undo.py [--apply] --drop-saved

Dry run by default: it prints what it would do and writes nothing. It asks no question. It commits and pushes nothing. With --apply it ignores the signals
that would end it (an interrupt, a hangup, a termination, quit, the user signals) from before its first change to its end, so a dropped terminal leaves no
half of a way back; each program it runs has a time limit. One run of the scripts that write goes at a time (a lock). Which way it goes is read from the
config on disk (STACKSHOT_CONFIG):

THE CONFIG IS REVERTED (the commits of the switch are reverted, pushed and pulled)
  The checkout's code has to load the config (`python -m stackshot.core.config check`). When it does not, nothing is changed: fix the config, or run this
  with --saved (and --snapshot DIR when there is no saved copy that such a run would take).
  1  the splitter is disabled; it runs on until step 4
  2  an override of an earlier run is removed
  3  `./install.sh units`. When step 2 or 3 fails, nothing is restarted and the override is put back
  4  the splitter is stopped. When it still runs afterwards, nothing is restarted and the override is put back
  5  the board is restarted; it answers on its old port
  6  the minute runner and the portal sync are restarted
  7  the board answers on the public address
  When the board does not come up on this config (step 5) and there is a saved copy to run on (below), it is put on the saved copy.

THE CONFIG STILL SHOWS THE SWITCH (the cut-over runs this by itself after a failed check), or --saved is given
  The board comes back on a SAVED copy of the single-user config: the one the cut-over put aside from the snapshot, or the one in --snapshot DIR. A saved
  copy that no unit reads and that is more than a day old may be left from an earlier switch: it is refused, and --snapshot DIR is asked for. A person's
  run also refuses a saved copy that the checkout's code cannot load.
  1  the saved copy is put where the units are to read it
  2  the splitter is disabled and stopped
  3  a drop-in for the same three units points STACKSHOT_CONFIG at the saved copy (it holds across a reboot, and `install.sh units` leaves it)
  4  the board is restarted; it answers on its old port
  5  the minute runner and the portal sync are restarted
  6  the board answers on the public address
  A person still has to revert the commits of the switch (or fix the config on disk), push and pull, run this script again (it removes the override) and
  end the release hold. These steps are printed on every end of this way, a failed one included.

The cut-over's own run does not refuse: when the config on disk cannot be loaded, its units cannot be set up for it, or the board does not come up on it,
it takes the saved copy.

NO DATA IS RESTORED OR REMOVED, either way: the board's records stay as they are, with everything written since the snapshot. The snapshot's archive
is not used.

--drop-saved removes the saved copy of a switch that is kept. It is refused while an override makes a unit read the copy.

When the cut-over runs this, every program is held to what is left of the cut-over's window, and the portal sync's restart is asked for and not waited for.

Exit 3: reverted config, the automated checks pass, MANUAL checks are left. 4: the board is back on the saved config (--saved, a config that still shows
the switch, or one it did not come up on); the revert or the fix is left.
5: a step or a check failed, a person is needed now. 1: refused (no config the board can come back on, or another run holds the lock), nothing changed.
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


def overrides_held() -> dict[Path, bytes | None]:
    """The overrides in place and what each holds (None when it cannot be read): what `put_back` writes again."""
    held: dict[Path, bytes | None] = {}
    for p in fs.overrides_present():
        try:
            held[p] = p.read_bytes()
        except OSError:
            held[p] = None
    return held


def put_back(held: dict[Path, bytes | None], rep: Report, lim: fs.Limits) -> None:
    for p, data in held.items():
        if data is None:
            rep.row("override put back", False, f"{p} could not be read before it was removed")
            continue
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            fs.write_private(p, data)
            rep.row("override put back", True, str(p))
        except OSError as e:
            rep.row("override put back", False, str(e))
    reload_systemd(rep, lim)


def reload_systemd(rep: Report, lim: fs.Limits) -> None:
    ok, line = fs.systemctl("daemon-reload", timeout=lim.act())
    rep.row("systemd read the unit files again", ok, "" if ok else line)


def restart(unit: str, rep: Report, lim: fs.Limits, queued: bool = False) -> None:
    """Restart one unit. queued: ask systemd for it and go on (a one-shot unit is only back when its program has ended)."""
    fs.systemctl("reset-failed", unit, timeout=lim.read())         # a unit that hit its start limit would refuse the restart; nothing to reset is no failure
    ok, line = fs.systemctl("restart", *(("--no-block",) if queued else ()), unit, timeout=lim.restart())
    rep.row(f"restart of {unit} asked for, not waited for" if queued and ok else f"restarted {unit}", ok, "" if ok else line)


def restart_board(rep: Report, lim: fs.Limits) -> bool:
    """The board first, and its answer, so that nothing else stands between the board and being back. → whether it answers and runs."""
    restart(fs.BOARD_UNIT, rep, lim)
    ok, code = fs.wait_code(f"http://127.0.0.1:{fs.OLD_BOARD_PORT}/healthz", "200", lim.answers().left())
    rep.row(f"the board answers on {fs.OLD_BOARD_PORT} (healthz)", ok, f"HTTP {code}")
    if lim.window is not None:
        fs.emit(f"{lim.window.seconds - lim.window.left():.0f} s after the first restart (the window is {lim.window.seconds:.0f} s)"
                + (": LATER THAN THE WINDOW" if lim.window.left() < 0 else ""))
    running, state = fs.unit_active(fs.BOARD_UNIT, lim.read())
    rep.row(f"{fs.BOARD_UNIT} is running", running, state)
    return ok and running


def restart_rest(public: str, rep: Report, lim: fs.Limits) -> None:
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


def left_on_saved(co: Path, cfg_path: Path, refused: bool = False, reverted: bool = False) -> None:
    """Everything a person still has to do while the board is on the saved copy, or should be. Printed on every end of that way, whatever worked.
    reverted: the config on disk is a single-user config (it could not be used, or --saved was given); else it shows the switch."""
    repo = fs.config_repo(cfg_path)
    there = f" ({repo})" if repo else ""
    steps = []
    if refused:
        steps.append("disable the splitter: " + shlex.join(["systemctl", "--user", "disable", "--now", fs.SPLITTER_UNIT]))
    if reverted:
        steps.append(f"if the board could not use the config on disk, fix it in the config's repository{there} and push")
    else:
        steps.append(f"in the config's repository{there}, revert the commits of the switch, newest first (the cut-over, the test splitter, the settings), and push")
    steps.append("pull it on this machine: " + (shlex.join(["git", "-C", str(repo), "pull", "--ff-only"]) if repo else "git pull --ff-only in that repository"))
    again = len(steps) + 1
    steps.append(f"remove the override and run on the config on disk: {fs.command('frontdoor_undo.py', '--apply')}")
    steps.append(f"end the release hold, only after step {again} has passed: {end_hold_command(co)}")
    for number, step in enumerate(steps, 1):
        fs.say("OPERATOR", str(number), step)
    if fs.rollback_copy().is_file():
        fs.say("NOTE", f"the saved copy of the config stays until step {again} has passed", str(fs.rollback_copy()))
    which = "the config on disk" if reverted else "the pulled config, which shows the switch"
    if fs.overrides_present():
        fs.say("NOTE", f"until step {again} the units with an override do not see a change to the config; other units and command-line calls still read {which}")
    else:
        fs.say("NOTE", f"no override is in place: the units read {which}")
    why = "reads the config on disk, which the board is not to run on yet" if reverted else "looks for the board on the pulled config's port and fails"
    fs.say("NOTE", f"keep releases held until step {again} (a hold ends by itself after two hours at most): a release deployed before it {why}")


def left_on_reverted(co: Path, held: bool, failed: bool = False, snapshot: Path | None = None) -> None:
    """What is left on a reverted config, printed on every end of that way. held: the release hold was not ended by this run.
    failed: with how to put the board on the saved copy of the old config (the snapshot's, when one was named)."""
    if held and failed:
        fs.say("OPERATOR", "1", f"end the release hold, only once a run of the undo has passed: {end_hold_command(co)}")
    elif held:
        fs.say("OPTION", "end the release hold", end_hold_command(co))
    if held:
        fs.say("NOTE", "a release hold also ends by itself, after two hours at most")
    saved = fs.rollback_copy()
    if failed and saved.is_file():
        fs.say("NOTE", "the saved copy of the config stays until a run on the reverted config passes", str(saved))
    if failed:
        if snapshot:
            fs.say("OPTION", "put the board on the snapshot's config instead", fs.command("frontdoor_undo.py", "--apply", "--saved", "--snapshot", str(snapshot)))
        elif not (usable(saved) or stale(saved)):
            fs.say("OPTION", "put the board on the saved copy of the old config instead", fs.command("frontdoor_undo.py", "--apply", "--saved"))
        else:
            fs.say("OPTION", "put the board on a snapshot's config instead, with its folder for DIR",
                   fs.command("frontdoor_undo.py", "--apply", "--saved", "--snapshot") + " DIR")
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


def fallback_copy(cfg_path: Path, snapshot: Path | None, held: dict) -> Path | None:
    """The saved copy a run on the reverted config can put the board on when it does not come up, or None. The copy an override of this moment reads comes
    first: the board ran on it."""
    saved = fs.rollback_copy()
    if held and not usable(saved):
        return saved
    source = fs.snapshot_config(snapshot, cfg_path) if snapshot else saved
    return None if usable(source) or (not snapshot and stale(source)) else source


def back_on_reverted(co: Path, cfg_path: Path, snapshot: Path | None, public: str, end_hold: bool, again: list[str], lim: fs.Limits) -> int:
    rep = Report()
    held = overrides_held()                  # read before the first change
    spare = fallback_copy(cfg_path, snapshot, held)

    def to_the_saved_copy(why: str) -> int:
        fs.emit(f"{why}: putting the board on the saved copy of the old config ({spare})")
        lim.part = 1.0
        return back_on_saved(co, cfg_path, spare, public, end_hold, again, lim, reverted=True)

    def not_complete() -> int:
        rc = incomplete(rep, again)
        left_on_reverted(co, held=True, failed=True, snapshot=snapshot)
        return rc

    # disabled first, so that no boot starts it; stopped only when the board is about to be restarted, so that a step that fails before that leaves it serving
    fs.systemctl("disable", fs.SPLITTER_UNIT, timeout=lim.act())            # what it came to is checked by splitter_step
    if held:
        remove_overrides(rep)
        reload_systemd(rep, lim)
    if not rep.bad:
        ok, line = fs.install_units(co, lim.install())
        rep.row("units rendered and installed (`./install.sh units`)", ok, "" if ok else line)
    if rep.bad:
        if lim.window is not None and spare:             # the cut-over's run: the board has to come back, and no person is there
            return to_the_saved_copy("the units could not be set up for the config on disk")
        if held:
            put_back(held, rep, lim)
        fs.say("NOTE", "nothing was restarted. The splitter is disabled; this run did not stop it, so one that ran still runs")
        return not_complete()
    splitter_step(rep, lim)
    if rep.bad and fs.unit_active(fs.SPLITTER_UNIT, lim.read())[0]:          # it may hold the board's port: a restart would take the board off the one it has
        if held:
            put_back(held, rep, lim)
        fs.say("NOTE", "nothing was restarted: the splitter still runs")
        return not_complete()
    if spare:
        lim.part = 0.5                       # the rest of a window is for the way to the saved copy
    back = restart_board(rep, lim)
    if not back and spare:
        return to_the_saved_copy("the board does not come up on the config on disk")
    lim.part = 1.0
    restart_rest(public, rep, lim)
    if rep.bad:
        return not_complete()
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
            return not_complete()
    fs.emit(f"the board is back on {fs.OLD_BOARD_PORT} on the reverted config; the automated checks pass, MANUAL checks are pending")
    fs.emit(NO_DATA)
    manual_lines()
    left_on_reverted(co, held=not end_hold)
    return fs.PENDING


def back_on_saved(co: Path, cfg_path: Path, saved: Path, public: str, end_hold: bool, again: list[str], lim: fs.Limits, reverted: bool = False) -> int:
    rep = Report()
    try:                                     # first: when the copy cannot be put there, nothing else is changed
        if saved != fs.rollback_copy():
            saved = store_saved(saved)
        rep.row("the saved single-user config is in place", True, str(saved))
    except OSError as e:
        rep.row("the saved single-user config is in place", False, str(e))
        rc = incomplete(rep, again)
        left_on_saved(co, cfg_path, reverted=reverted)
        return rc
    splitter_step(rep, lim)
    write_overrides(saved, rep)
    reload_systemd(rep, lim)
    restart_board(rep, lim)
    restart_rest(public, rep, lim)
    if rep.bad:
        rc = incomplete(rep, again)
        left_on_saved(co, cfg_path, reverted=reverted)
        return rc
    fs.emit(f"THE BOARD IS BACK on {fs.OLD_BOARD_PORT}, on the SAVED copy of the config; the automated checks pass, MANUAL checks are pending")
    fs.emit(NO_DATA)
    differ_note(saved, cfg_path, reverted)
    manual_lines()
    left_on_saved(co, cfg_path, reverted=reverted)
    if end_hold:
        fs.say("NOTE", "--end-hold was not done: end the hold once a run on the config on disk has passed (that run takes --end-hold)")
    return fs.ROLLED_BACK


def differ_note(saved: Path, cfg_path: Path, reverted: bool = False) -> None:
    now = fs.read_toml(cfg_path)
    if now is None:
        fs.say("NOTE", "the config on disk cannot be read, so it was not compared with the saved one")
        return
    names = fs.other_differences(fs.read_toml(saved), now)
    if names:
        until = "until the override is removed" if reverted else "until the revert"
        fs.say("NOTE", f"outside the switch's own settings the saved config differs from the one on disk, and the board runs without these changes {until}",
               ", ".join(names))


def see_why(co: Path, path: Path) -> str:
    """The shell line that shows why a config cannot be loaded. This script does not pass those words on: they may name members."""
    return shlex.join(["cd", str(co)]) + " && " + shlex.join(fs.config_check_args(path))


def loads(co: Path, path: Path, what: str, lim: fs.Limits) -> bool:
    rc, _ = fs.config_check(co, path, lim.load())
    fs.say("PASS" if rc == 0 else "FAIL", f"the checkout's code loads {what}", "" if rc == 0 else f"exit {rc}; see why: {see_why(co, path)}")
    return rc == 0


def way_back(co: Path, cfg_path: Path, snapshot: Path | None, apply: bool, end_hold: bool, window: fs.Window | None = None, on_saved: bool = False) -> int:
    """Bring the board back; the lines are printed as they happen. Returns the exit code. window: the cut-over's, which every program is then held to.
    on_saved: on the saved copy, whatever the config on disk says."""
    public = fs.need_public_url() if apply else fs.public_url()
    if cfg_path.resolve() == fs.rollback_copy().resolve():
        raise fs.Usage(f"STACKSHOT_CONFIG is the saved copy {cfg_path}: point it at the instance's own config")
    cfg = fs.read_toml(cfg_path)
    not_reverted = fs.failed(fs.single_user_checks(cfg))
    use_saved = on_saved or bool(not_reverted)
    source = fs.snapshot_config(snapshot, cfg_path) if snapshot else fs.rollback_copy()
    lim = fs.Limits(window)
    again = ["--apply", *(["--saved"] if on_saved else []), *(["--snapshot", str(snapshot)] if snapshot else []), *(["--end-hold"] if end_hold else [])]

    if not_reverted:
        fs.say("NOTE", "the config on disk still shows the switch", "; ".join(not_reverted))
    elif on_saved:
        fs.say("NOTE", "the config on disk is a single-user config; as asked with --saved, the way back runs on the saved copy")
    else:
        fs.say("NOTE", "the config on disk is a single-user config: the way back runs on it")
        left = [t for t in fs.SWITCH_TABLES if fs.setting(cfg, t) is not None]
        if left:
            fs.say("NOTE", "tables of the switch are still in the config (the undo of the whole switch reverts the settings and the test splitter too)", ", ".join(left))
        if snapshot:
            fs.say("NOTE", "--snapshot is used only if the board does not come up on the config on disk (to run on it at once, add --saved)")

    # before anything is changed: the board must not be taken off the config it runs on for one that the code cannot load
    if not use_saved and not loads(co, cfg_path, "the config on disk", lim):
        if window is None:
            fs.say("REFUSE", "the board is not restarted on a config that the code cannot load")
            retry = "nothing was changed. Fix the config in its repository, push, pull and run this again; or run the board on "
            saved = fs.rollback_copy()
            if snapshot or not (usable(saved) or stale(saved)):
                fs.emit(retry + "the saved copy of the old config:")
                fs.say("UNDO", fs.command("frontdoor_undo.py", "--apply", "--saved", *(["--snapshot", str(snapshot)] if snapshot else [])))
            else:                                    # no copy a run would take: an UNDO line is pasted as it is, so this one is an OPTION
                fs.emit(retry + "a snapshot's config:")
                fs.say("OPTION", "put the board on a snapshot's config, with its folder for DIR",
                       fs.command("frontdoor_undo.py", "--apply", "--saved", "--snapshot") + " DIR")
            return fs.FAILED
        fs.say("NOTE", "the way back runs on the saved copy instead")
        use_saved = True
    reverted = not not_reverted

    if use_saved:
        why_not = usable(source) or ([] if snapshot else stale(source))
        if not why_not and window is None and not loads(co, source, "the saved config", lim):       # the cut-over checked its own before the restart
            why_not = [f"the checkout's code cannot load {source}"]
        if why_not:
            fs.say("REFUSE", "no config the board can come back on", "; ".join(why_not))
            fs.emit("nothing was changed. Do this, or run this again with --snapshot DIR:")
            left_on_saved(co, cfg_path, refused=True, reverted=reverted)
            return fs.FAILED

    if not apply:
        if use_saved:
            steps = [f"put the saved config where the units are to read it (from {source})", "disable and stop the splitter",
                     f"write an override for {', '.join(fs.RESTORE_UNITS)} that reads it", "systemctl --user daemon-reload"]
        else:
            steps = ["disable the splitter (it runs on until the board is about to be restarted)"]
            if fs.overrides_present():
                steps += ["remove the override of an earlier run", "systemctl --user daemon-reload"]
            steps += ["./install.sh units", "stop the splitter"]
        steps += [f"restart {fs.BOARD_UNIT} and check {fs.OLD_BOARD_PORT} within {fs.undo_window_seconds():.0f} s",
                  f"restart {fs.MINUTE_UNIT} and {fs.SYNC_UNIT}, and check the public address within {fs.undo_window_seconds():.0f} s"]
        if end_hold and not use_saved:
            steps.append("release.sh hold --end")
        for i, s in enumerate(steps, 1):
            fs.say("PLAN", f"step {i}", s)
        if use_saved:
            fs.emit("what would be left for a person afterwards:")
            left_on_saved(co, cfg_path, reverted=reverted)
        else:
            spare = fallback_copy(cfg_path, snapshot, overrides_held())
            fs.emit("a step that fails before the restart would end the run with nothing restarted"
                    + (f"; a board that does not come up would be put on the saved copy ({spare})" if spare else "; there is no saved copy to fall back on"))
        fs.emit(NO_DATA.replace("no data was", "no data would be"))
        fs.emit("dry run: nothing changed (add --apply)")
        return fs.OK

    try:
        if use_saved:
            return back_on_saved(co, cfg_path, source, public, end_hold, again, lim, reverted=reverted)
        return back_on_reverted(co, cfg_path, snapshot, public, end_hold, again, lim)
    except BaseException:
        fs.say("UNDO", fs.command("frontdoor_undo.py", *again))          # a bug here still leaves the person with all that is to be done
        if use_saved:
            left_on_saved(co, cfg_path, reverted=reverted)
        else:
            left_on_reverted(co, held=True, failed=True, snapshot=snapshot)
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
    ap.add_argument("--saved", action="store_true", help="run the board on the saved copy of the old config, whatever the config on disk says")
    ap.add_argument("--snapshot", metavar="DIR", help="the snapshot folder whose config is the saved copy (without it: the one the cut-over put aside)")
    ap.add_argument("--end-hold", action="store_true", help="also end the release hold (only on a reverted config)")
    ap.add_argument("--drop-saved", action="store_true", help="the switch is kept: remove the saved copy of the old config, and nothing else")
    a = ap.parse_args(argv)
    if a.drop_saved and (a.snapshot or a.end_hold or a.saved):
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
        return way_back(co, cfg_path, snapshot, a.apply, a.end_hold, on_saved=a.saved)
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
