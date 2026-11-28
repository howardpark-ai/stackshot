#!/usr/bin/env python3
"""tools/frontdoor_preflight.py: what has to hold before the first step of a live switch to the front door. Read-only: it changes nothing of the board,
its config or its units, so it has no --apply. One thing it may write: it reads the config notes through `uv run` in the checkout, which first brings that
checkout's Python environment up to date when it is behind (FRONTDOOR_SWITCH_PYTHON names another command).

    python3 tools/frontdoor_preflight.py (--backup-dir DIR | --backup-log FILE) [--baseline FILE] [--confirm NAME ...]

One line per check. PASS or FAIL for what the script reads itself; MANUAL for what only a person can see, until --confirm NAME says it holds:
    go            the owner's go for the switch is given
    token-choice  the owner's answer on accept_portal_token is written down
    ssh           a second ssh session to the board's machine is open
    signed-in     the owner is signed in on a second device
    no-long-call  no long tool call is running (the front door's replay window is 300 s)

Where today's backup of the board shows (one of the two at least; with both, either one passes the line), "today" being in [instance] timezone:
--backup-dir (or FRONTDOOR_BACKUP_DIR) is a folder of the board's daily backups: the newest file there is not empty and dated today.
--backup-log (or FRONTDOOR_BACKUP_LOG) is the log of a backup job that keeps its copy elsewhere, one line a run, tab-separated: the time (ISO 8601 with
its UTC offset), the job, ok|skipped|failed, the bytes sent, a note. The last line of the job "stackshot" is ok, of more than 0 bytes and dated today.
Only the log is read: the copy itself is not fetched or checked. Neither the cut-over nor the way back reads a daily backup, so none has to be on this machine.
--baseline is a saved list of the config notes to compare with; without it the notes are printed (the snapshot script saves them as the baseline).

Exit 0: every line passes. 1: a check failed. 2: the script cannot run. 3: every check passes and MANUAL lines are left.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import frontdoor_switch as fs

# the merge that brought what the switch uses: the front door's unit templates, the real-call check, `release.sh hold` and `stackshot frontdoor-token`
NEEDED_COMMIT = "e7b4353d3be4a0e5219c8f01cce16f563f6083f9"
BACKUP_JOB = "stackshot"              # the name of the board's lines in a backup log
MANUAL = {
    "go": "the owner's go for the switch is given",
    "token-choice": "the owner's answer on accept_portal_token is written down",
    "ssh": "a second ssh session to the board's machine is open",
    "signed-in": "the owner is signed in on a second device",
    "no-long-call": "no long tool call is running",
}


def listening_ports() -> set[int]:
    rc, out = fs.run(["ss", "-Hltn"])
    if rc != 0:
        raise fs.Usage(f"ss cannot list the listening ports (exit {rc})")
    ports: set[int] = set()
    for line in out.splitlines():
        cols = line.split()
        if len(cols) >= 4 and cols[3].rsplit(":", 1)[-1].isdigit():
            ports.add(int(cols[3].rsplit(":", 1)[-1]))
    return ports


def newest_backup(folder: Path, cfg: dict | None) -> tuple[bool, str]:
    if not folder.is_dir():
        return False, f"no folder {folder}"
    files = [p for p in folder.iterdir() if p.is_file() and p.stat().st_size > 0]
    if not files:
        return False, f"no backup file in {folder}"
    newest = max(files, key=lambda p: p.stat().st_mtime)
    day = datetime.fromtimestamp(newest.stat().st_mtime, fs.zone(cfg)).date()
    return day == datetime.now(fs.zone(cfg)).date(), f"the newest, {newest.name}, is dated {day.isoformat()}"


def logged_backup(log: Path, cfg: dict | None) -> tuple[bool, str]:
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, f"cannot read the backup log {log}: {e.strerror}"
    runs = [cols for cols in (x.split("\t") for x in text.splitlines()) if len(cols) > 1 and cols[1] == BACKUP_JOB]
    if not runs:
        return False, f"no run of {BACKUP_JOB} in {log}"
    try:
        stamp, _, result, sent = runs[-1][:4]
        when, size = datetime.fromisoformat(stamp), int(sent)
    except ValueError:
        when = None
    if when is None or when.tzinfo is None:
        return False, f"the last run of {BACKUP_JOB} in {log} cannot be read"
    day = when.astimezone(fs.zone(cfg)).date()
    ok = result == "ok" and size > 0 and day == datetime.now(fs.zone(cfg)).date()
    return ok, f"the last run of {BACKUP_JOB} in {log.name} is dated {day.isoformat()}: {result}, {size} bytes"


def checks(co: Path, cfg_path: Path, backups: Path | None, backup_log: Path | None, baseline: Path | None) -> list[tuple[str, bool]]:
    rows: list[tuple[str, bool]] = []
    cfg = fs.read_toml(cfg_path)
    rows += [(f"config before the switch: {name}", ok) for name, ok in fs.single_user_checks(cfg)]

    _, head = fs.run(["git", "-C", str(co), "log", "--oneline", "-1"])
    rc, _ = fs.run(["git", "-C", str(co), "merge-base", "--is-ancestor", NEEDED_COMMIT, "HEAD"])
    rows.append((f"the checkout holds the merge {NEEDED_COMMIT[:8]} (HEAD: {fs.last_line(head) or 'unreadable'})", rc == 0))

    hstate, _, hline = fs.hold_state(co)
    rows.append((f"no release hold ({hline})", hstate == "none"))
    qstate, qline = fs.queue_state(co)
    rows.append((f"release queue is empty ({qline})", qstate == "empty"))
    running, rline = fs.release_running()
    rows.append((f"no release in flight ({rline})", running is False))

    busy = sorted(listening_ports() & set(fs.PRE_FLIGHT_PORTS))
    rows.append((f"ports {', '.join(map(str, fs.PRE_FLIGHT_PORTS))} are free" + (f" (busy: {', '.join(map(str, busy))})" if busy else ""), not busy))

    missing = [u for u in fs.RESTORE_UNITS if not (fs.unit_dir() / u).is_file()]
    rows.append((f"the units the cut-over and its way back restart are installed ({', '.join(fs.RESTORE_UNITS)})"
                 + (f" (not installed: {', '.join(missing)}; {fs.SYNC_UNIT} is installed only with [portal] account_id set)" if missing else ""), not missing))

    left = fs.overrides_present()
    rows.append(("no override of an earlier way back is in place" + (f" ({', '.join(str(p) for p in left)}: run the undo script after the config revert)" if left else ""), not left))

    ok, notes = fs.config_notes(co)
    rows.append((f"the config notes can be read ({len(notes) if ok else notes[0]})", ok))
    if ok and baseline is None:
        for line in notes:
            fs.say("NOTE", f"config note: {line}")
    if baseline is not None:
        saved = [x.rstrip() for x in baseline.read_text(encoding="utf-8").splitlines() if x.strip()]
        rows.append((f"the config notes are the baseline's ({len(saved)} lines saved)", ok and notes == saved))

    found = [look(path, cfg) for look, path in ((newest_backup, backups), (logged_backup, backup_log)) if path is not None]
    rows.append((f"a backup of today is there ({'; '.join(line for _, line in found)})", any(ok for ok, _ in found)))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/frontdoor_preflight.py", description="What has to hold before a live switch to the front door. It changes nothing of the board, its "
                                 "config or its units; reading the config notes runs `uv run` in the checkout, which may first sync that checkout's Python environment.")
    ap.add_argument("--backup-dir", metavar="DIR", default="", help="a folder of the board's daily backups (default: FRONTDOOR_BACKUP_DIR)")
    ap.add_argument("--backup-log", metavar="FILE", default="", help="the log of a backup job that keeps its copy elsewhere (default: FRONTDOOR_BACKUP_LOG)")
    ap.add_argument("--baseline", metavar="FILE", help="a saved list of the config notes to compare with")
    ap.add_argument("--confirm", action="append", default=[], choices=list(MANUAL), metavar="NAME", help="confirm a manual line: " + ", ".join(MANUAL))
    a = ap.parse_args(argv)
    try:
        cfg_path = fs.config_path()
        folder = a.backup_dir or os.environ.get("FRONTDOOR_BACKUP_DIR", "").strip()
        log = a.backup_log or os.environ.get("FRONTDOOR_BACKUP_LOG", "").strip()
        if not folder and not log:
            raise fs.Usage("--backup-dir DIR or --backup-log FILE is required (or FRONTDOOR_BACKUP_DIR, FRONTDOOR_BACKUP_LOG): where today's backup of the board shows")
        baseline = Path(os.path.expanduser(a.baseline)) if a.baseline else None
        if baseline is not None and not baseline.is_file():
            raise fs.Usage(f"--baseline names no file: {baseline}")
        folder, log = (Path(os.path.expanduser(x)) if x else None for x in (folder, log))
        rows = checks(fs.checkout(), cfg_path, folder, log, baseline)
    except fs.Usage as e:
        return fs.cannot(e)

    for name, ok in rows:
        fs.say("PASS" if ok else "FAIL", name)
    pending = [n for n in MANUAL if n not in a.confirm]
    for name, text in MANUAL.items():
        fs.say("MANUAL" if name in pending else "PASS", f"{name}: {text}" + ("" if name in pending else " (confirmed)"))
    bad = fs.failed(rows)
    fs.emit(f"{len(rows) - len(bad)} of {len(rows)} automated checks pass, {len(pending)} manual lines left; nothing was changed, so nothing is to be undone")
    if bad:
        return fs.FAILED
    if pending:
        fs.emit("look at the MANUAL lines, then run again with " + " ".join(f"--confirm {n}" for n in pending))
        return fs.PENDING
    return fs.OK


if __name__ == "__main__":
    sys.exit(main())
