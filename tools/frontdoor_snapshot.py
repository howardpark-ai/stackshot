#!/usr/bin/env python3
"""tools/frontdoor_snapshot.py: before a live switch to the front door, the snapshot (the way back) and the front door's secrets and members file.

    python3 tools/frontdoor_snapshot.py --expect MEMBERS,ALIASES,ADDRESSES [--data PATH ...] [--apply]

Dry run by default: it prints the plan and writes nothing. With --apply it does the snapshot, then the secrets, and reads both back.

The snapshot is a new folder (700, files 600) under FRONTDOOR_SNAPSHOT_ROOT, named by the time in [instance] timezone; an existing folder is never written into:
  board.tar.gz       tar of the data folders: [paths] repo and [paths] state, or each --data PATH. tar's exit 0 or 1 (a file changed while read) passes
  <the config file>  a copy of STACKSHOT_CONFIG, which has to be the single-user config: the cut-over's way back runs the board on it
  stackshot-head     the checkout's commit
  config-notes.txt   the config notes as they are now: the cut-over refuses a note that is not in this list
The archive is read back with its listing thrown away (a listing would show the names of sign-in files).

The secrets go into FRONTDOOR_SECRETS_DIR (700, files 600). identity.key and verify.key (48 random bytes, base64) and members.json (from [instance] owner and
owner_aliases and [auth] allowed_emails, board `main`) are made when missing and KEPT when there: to make them again, remove them first. board-token is the
board's machine token of <paths.secrets>/oauth.env, copied again on each run. Only counts and lengths are printed. --expect holds the member list to the
number of members, aliases and addresses the operator expects. `stackshot frontdoor-token --check` needs the [frontdoor] table: it is run here when the
config has one, and the cut-over runs it before the restart.

Exit 0: the plan (dry run), or every read-back, passes. 1: one failed. 2: the script cannot run.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shlex
import sys
from datetime import datetime
from pathlib import Path

import frontdoor_switch as fs

KEY_BYTES = 48
MIN_KEY = 32
DEFAULT_ROOT = "~/.local/share/stackshot-runs/frontdoor-switch"
KEYS = ("identity.key", "verify.key")
FILES = (*KEYS, "board-token", "members.json")
BOARD = "main"


def snapshot_root() -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.environ.get("FRONTDOOR_SNAPSHOT_ROOT", "").strip() or DEFAULT_ROOT)))


def data_paths(cfg: dict, given: list[str]) -> list[Path]:
    """The folders the archive holds. A relative path is taken from the home directory."""
    raw = given or [v for v in (fs.setting(cfg, "paths", "repo"), fs.setting(cfg, "paths", "state")) if isinstance(v, str) and v.strip()]
    if not raw:
        raise fs.Usage("no data folder to archive: the config has no [paths] repo or state, so give --data PATH")
    out: list[Path] = []
    for d in raw:
        p = Path(os.path.expanduser(d))
        p = Path(os.path.normpath(p if p.is_absolute() else Path.home() / p))
        if p not in out and not any(p.is_relative_to(q) for q in out):
            out = [q for q in out if not q.is_relative_to(p)] + [p]
    return out


def tar_args(paths: list[Path]) -> list[str]:
    """What tar is given: each folder relative to the home directory, or to its own parent when it is outside it."""
    home = Path.home()
    out: list[str] = []
    for p in paths:
        base = home if p.is_relative_to(home) and p != home else p.parent
        out += ["-C", str(base), str(p.relative_to(base))]
    return out


def snapshot(co: Path, cfg_path: Path, cfg: dict, data: list[Path], apply: bool, made: list[Path]) -> list[tuple[str, bool]]:
    """The snapshot's checks; the folder it makes is added to `made`."""
    root = snapshot_root()
    dest = root / datetime.now(fs.zone(cfg)).strftime("%Y%m%d-%H%M%S")
    rows = [(f"snapshot: {name}", ok) for name, ok in fs.single_user_checks(cfg)]
    rows += [(f"snapshot: {p} exists", p.exists()) for p in data]
    rows += [(f"snapshot: the folder {root} is not inside {p}", not root.is_relative_to(p)) for p in data]
    if not apply:
        fs.say("PLAN", "snapshot", f"{dest}: {fs.SNAPSHOT_ARCHIVE} of {', '.join(map(str, data))}; {cfg_path.name}; {fs.SNAPSHOT_HEAD}; {fs.SNAPSHOT_NOTES}")
        return rows
    if fs.failed(rows):
        return rows
    rc, head = fs.run(["git", "-C", str(co), "rev-parse", "HEAD"])
    ok_notes, notes = fs.config_notes(co)
    if rc != 0 or not fs.last_line(head):
        return rows + [("snapshot: the checkout's commit can be read", False)]
    if not ok_notes:
        return rows + [(f"snapshot: the config notes can be read ({notes[0]})", False)]
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        dest.mkdir(mode=0o700)
    except FileExistsError:
        return rows + [(f"snapshot: {dest} is new (it is there already; run again)", False)]
    os.chmod(dest, 0o700)
    made.append(dest)
    fs.say("DONE", "snapshot folder", str(dest))
    archive = dest / fs.SNAPSHOT_ARCHIVE
    fs.new_private(archive, b"")                              # tar writes into this file, so it is 600 from its first byte
    rc, out = fs.run(["tar", "-czf", str(archive), *tar_args(data)], timeout=1800)
    rows.append((f"snapshot: tar of the data folders (exit {rc}; 0 or 1 passes)", rc in (0, 1)))
    fs.new_private(dest / cfg_path.name, cfg_path.read_bytes())
    fs.new_private(dest / fs.SNAPSHOT_HEAD, (fs.last_line(head) + "\n").encode())
    fs.new_private(dest / fs.SNAPSHOT_NOTES, "".join(n + "\n" for n in notes).encode("utf-8"))
    rc, _ = fs.run(["tar", "-tzf", str(archive)], timeout=1800)
    rows.append((f"snapshot: the archive reads back (exit {rc})", rc == 0))
    rows.append(("snapshot: the folder is 700 and its archive 600", fs.mode_of(dest) == 0o700 and fs.mode_of(archive) == 0o600))
    return rows


def member_record(cfg: dict) -> dict:
    owner = str(fs.setting(cfg, "instance", "owner") or "").strip()
    if not owner:
        raise fs.Usage("the config has no [instance] owner, so there is no member to write")
    aliases = [str(a) for a in fs.setting(cfg, "instance", "owner_aliases") or []]
    emails = [str(e).lower() for e in fs.setting(cfg, "auth", "allowed_emails") or []]
    return {owner: {"boards": [BOARD], "aliases": aliases, "emails": emails}}


def counts(path: Path) -> tuple[int, int, int]:
    """(members, aliases, addresses) of the members file, -1 each when it cannot be read as one."""
    try:
        mem = json.loads(path.read_text(encoding="utf-8"))
        return len(mem), sum(len(v["aliases"]) for v in mem.values()), sum(len(v["emails"]) for v in mem.values())
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return -1, -1, -1


def secrets_step(co: Path, cfg: dict, expect: tuple[int, int, int] | None, apply: bool) -> list[tuple[str, bool]]:
    folder = fs.secrets_dir()
    record = member_record(cfg)
    if not apply:
        for name in FILES:
            there = (folder / name).is_file()
            fs.say("PLAN", f"secrets: {folder / name}", ("copied again" if there else "copied") if name == "board-token" else ("kept" if there else "made"))
        return []
    # the board's own code reads the token and writes its copy, so both read and write it exactly as the board and `stackshot frontdoor-token` do
    sys.path.insert(0, str(fs.TOOLS.parent))
    from stackshot.core import config as stack_config
    from stackshot.frontdoor import boardtoken

    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    for name in KEYS:
        if (folder / name).exists():
            fs.say("KEPT", f"secrets: {name}")
        else:
            fs.new_private(folder / name, base64.b64encode(secrets.token_bytes(KEY_BYTES)))
    if (folder / "members.json").exists():
        fs.say("KEPT", "secrets: members.json")
    else:
        fs.new_private(folder / "members.json", (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
    token, why = "", ""
    try:
        token = boardtoken.board_token(str(stack_config.secrets("oauth.env")))
        if not boardtoken.holds(str(folder / "board-token"), token)[0]:
            boardtoken.write(str(folder / "board-token"), token)
    except (boardtoken.Refused, KeyError) as e:
        why = f" ({e})"

    rows = [("secrets: the folder is 700", fs.mode_of(folder) == 0o700)]
    for name in FILES:
        p = folder / name
        rows.append((f"secrets: {name} is there and 600", p.is_file() and fs.mode_of(p) == 0o600))
    values = {}
    for name in KEYS:
        try:
            values[name] = (folder / name).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            values[name] = ""
        rows.append((f"secrets: {name} has {len(values[name])} characters ({MIN_KEY} or more)", len(values[name]) >= MIN_KEY))
    rows.append((f"secrets: {KEYS[0]} and {KEYS[1]} differ", values[KEYS[0]] != values[KEYS[1]]))
    rows.append((f"secrets: board-token holds the board's machine token{why}", bool(token) and boardtoken.holds(str(folder / "board-token"), token)[0]))
    got = counts(folder / "members.json")
    rows.append((f"secrets: members.json has {got[0]} member, {got[1]} aliases, {got[2]} addresses (expected {expect[0]}, {expect[1]}, {expect[2]})", got == expect))
    if fs.setting(cfg, "frontdoor") is None:
        fs.say("NOTE", "secrets: `stackshot frontdoor-token --check` needs the [frontdoor] table: run it after the config save that adds it (the cut-over runs it too)")
    else:
        rc, out = fs.run([*fs.py_cmd(), "-m", "stackshot.frontdoor.boardtoken", "--check"], cwd=co, timeout=300)
        rows.append((f"secrets: `stackshot frontdoor-token --check` ({fs.last_line(out) or f'exit {rc}'})", rc == 0))
    return rows


def expected(text: str) -> tuple[int, int, int]:
    parts = text.split(",")
    if len(parts) != 3 or not all(p.strip().isdigit() for p in parts):
        raise fs.Usage(f"--expect takes three whole numbers, MEMBERS,ALIASES,ADDRESSES, not {text!r}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def report(rows: list[tuple[str, bool]]) -> list[str]:
    for name, ok in rows:
        fs.say("PASS" if ok else "FAIL", name)
    return fs.failed(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/frontdoor_snapshot.py", description="Before a live switch: the snapshot, and the front door's secrets and members file.")
    ap.add_argument("--data", action="append", default=[], metavar="PATH", help="a data folder to archive (repeatable; default: [paths] repo and state)")
    ap.add_argument("--expect", default="", metavar="M,A,E", help="the members, aliases and addresses the members file must hold (needed with --apply)")
    ap.add_argument("--apply", action="store_true", help="write the snapshot and the secrets (default: a dry run that writes nothing)")
    a = ap.parse_args(argv)
    os.umask(0o077)
    co = fs.checkout()
    try:
        cfg_path = fs.config_path()
        cfg = fs.read_toml(cfg_path)
        if cfg is None:
            raise fs.Usage(f"{cfg_path} cannot be read as a config")
        expect = expected(a.expect) if a.expect else None
        if a.apply and expect is None:
            raise fs.Usage("--expect MEMBERS,ALIASES,ADDRESSES is needed with --apply")
        data = data_paths(cfg, a.data)
        member_record(cfg)                       # a config with nobody to write is refused before anything is written
        made: list[Path] = []
        rows = snapshot(co, cfg_path, cfg, data, a.apply, made)
        bad = report(rows)
        if not bad:
            more = secrets_step(co, cfg, expect, a.apply)
            bad = report(more)
            rows += more
        else:
            fs.say("NOTE", "the secrets step was not started: the snapshot did not pass")
    except fs.Usage as e:
        return fs.cannot(e)
    if not a.apply:
        fs.emit("dry run: nothing written (add --apply)")
        return fs.FAILED if bad else fs.OK
    fs.emit(f"{len(rows) - len(bad)} of {len(rows)} checks pass")
    for folder in made:
        fs.emit(f"snapshot: {folder}")
        fs.emit(f"undo of the snapshot (only when it is no longer wanted; this cannot be undone): {shlex.join(['rm', '-r', str(folder)])}")
    if made and not bad:
        fs.emit(f"the cut-over needs this folder: {fs.command('frontdoor_cutover.py', '--snapshot', str(made[0]), '--apply')}")
    fs.emit(f"undo of the secrets: {shlex.join(['rm', '-f', *(str(fs.secrets_dir() / n) for n in FILES)])}")
    return fs.FAILED if bad else fs.OK


if __name__ == "__main__":
    sys.exit(main())
