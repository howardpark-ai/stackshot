#!/usr/bin/env python3
"""tools/frontdoor_snapshot.py: before a live switch to the front door, the snapshot (the way back) and the front door's secrets and members file.

    python3 tools/frontdoor_snapshot.py --expect MEMBERS,ALIASES,ADDRESSES [--data PATH ...] [--apply]

Dry run by default: it prints the plan and writes nothing. With --apply it checks the member list, then does the snapshot, then the secrets, and reads
both back. One run of the scripts that write goes at a time (a lock).

The member list is checked before anything is written: the members.json that will be used (the one that is there, else the one to be made) has to hold
--expect's number of members, aliases and addresses, and the front door has to read every entry of it. When it does not, nothing is written.

The snapshot is a new folder (700, files 600) under FRONTDOOR_SNAPSHOT_ROOT, named by the time in [instance] timezone; an existing folder is never written into:
  board.tar.gz       tar of the data folders: [paths] repo and [paths] state, or each --data PATH. A data folder that is a link is followed to the real
                     folder. A link inside them that leads outside them is refused (the archive would hold the link alone): give each folder it leads to
                     with --data too. tar's exit 0 or 1 (a file changed while read) passes
  <the config file>  a copy of STACKSHOT_CONFIG, which has to be the single-user config: the cut-over's way back runs the board on it
  stackshot-head     the checkout's commit
  config-notes.txt   the config notes as they are now: the cut-over refuses a note that is not in this list
  snapshot-complete  written last, only when every check of the snapshot passed: the cut-over refuses a snapshot without it
The archive is read back with its listing thrown away (a listing would show the names of sign-in files), and every file that was in the data folders both
before and after tar ran has to be in it.

The secrets go into FRONTDOOR_SECRETS_DIR (700, files 600). identity.key and verify.key (48 random bytes, base64) and members.json (the board's members as
the board itself reads them: [[members]], else [instance] owner and owner_aliases and [auth] allowed_emails; board `main`) are made when missing and KEPT
when there: to make them again, remove them first. board-token is the board's machine token of <paths.secrets>/oauth.env, copied again on each run. Only
counts and lengths are printed. The printed undo removes only the files this run made. `stackshot frontdoor-token --check` needs the [frontdoor] table: it
is run here when the config has one, and the cut-over runs it before the restart.

Exit 0: the plan (dry run), or every read-back, passes. 1: one failed, or another run holds the lock. 2: the script cannot run.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shlex
import sys
import tarfile
import tempfile
from collections import Counter
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
    """The real folders the archive holds, every link on the way to one followed. A relative path is taken from the home directory."""
    raw = given or [v for v in (fs.setting(cfg, "paths", "repo"), fs.setting(cfg, "paths", "state")) if isinstance(v, str) and v.strip()]
    if not raw:
        raise fs.Usage("no data folder to archive: the config has no [paths] repo or state, so give --data PATH")
    out: list[Path] = []
    for d in raw:
        p = Path(os.path.expanduser(d))
        p = p if p.is_absolute() else Path.home() / p
        real = Path(os.path.realpath(p))
        if real != Path(os.path.normpath(p)):
            fs.say("NOTE", "snapshot: a data folder is reached through a link, and the archive holds the real one", f"{p} is {real}")
        if real not in out and not any(real.is_relative_to(q) for q in out):
            out = [q for q in out if not q.is_relative_to(real)] + [real]
    return out


def tar_base(p: Path) -> Path:
    """The folder tar is run from for the data folder `p`: the home directory, or the folder's own parent when it is outside it."""
    home = Path(os.path.realpath(Path.home()))
    return home if p.is_relative_to(home) and p != home else p.parent


def tar_args(paths: list[Path]) -> list[str]:
    out: list[str] = []
    for p in paths:
        out += ["-C", str(tar_base(p)), str(p.relative_to(tar_base(p)))]
    return out


def walk(paths: list[Path]) -> tuple[Counter, int]:
    """(the names the archive gives the regular files of the data folders, the links in them that lead to something outside all of them)."""
    files: Counter = Counter()
    outside = 0

    def look(p: Path, base: Path) -> None:
        nonlocal outside
        if p.is_symlink():
            real = Path(os.path.realpath(p))
            if real.exists() and not any(real.is_relative_to(q) for q in paths):
                outside += 1
        elif p.is_file():
            files[p.relative_to(base).as_posix()] += 1

    for top in paths:
        base = tar_base(top)
        if not top.is_dir():
            look(top, base)
            continue
        for folder, folders, names in os.walk(top):                   # links are listed, never walked into
            for name in (*folders, *names):
                look(Path(folder, name), base)
    return files, outside


def archived(archive: Path) -> Counter | None:
    """The names of the files the archive holds content for, or None when it cannot be read to its end. Nothing of it is printed."""
    try:
        with tarfile.open(archive, "r:gz") as tf:
            return Counter(os.path.normpath(m.name) for m in tf if m.isreg() or m.islnk())
    except (OSError, EOFError, tarfile.TarError, ValueError):
        return None


def snapshot(co: Path, cfg_path: Path, cfg: dict, data: list[Path], apply: bool, made: list[Path]) -> list[tuple[str, bool]]:
    """The snapshot's checks; the folder it makes is added to `made`."""
    root = snapshot_root()
    dest = root / datetime.now(fs.zone(cfg)).strftime("%Y%m%d-%H%M%S")
    rows = [(f"snapshot: {name}", ok) for name, ok in fs.single_user_checks(cfg)]
    rows += [(f"snapshot: {p} exists", p.exists()) for p in data]
    rows += [(f"snapshot: the folder {root} is not inside {p}", not Path(os.path.realpath(root)).is_relative_to(p)) for p in data]
    _, outside = walk(data)
    find = shlex.join(["find", *map(str, data), "-type", "l"])
    rows.append((f"snapshot: no link in the data folders leads outside them ({outside} do; give each folder they lead to with --data too; list the links with: {find})"
                 if outside else "snapshot: no link in the data folders leads outside them", not outside))
    if not apply:
        fs.say("PLAN", "snapshot", f"{dest}: {fs.SNAPSHOT_ARCHIVE} of {', '.join(map(str, data))}; {cfg_path.name}; {fs.SNAPSHOT_HEAD}; {fs.SNAPSHOT_NOTES}; {fs.SNAPSHOT_COMPLETE}")
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
    before, _ = walk(data)
    rc, out = fs.run(["tar", "-czf", str(archive), *tar_args(data)], timeout=1800)
    after, _ = walk(data)
    rows.append((f"snapshot: tar of the data folders (exit {rc}; 0 or 1 passes)", rc in (0, 1)))
    fs.new_private(dest / cfg_path.name, cfg_path.read_bytes())
    fs.new_private(dest / fs.SNAPSHOT_HEAD, (fs.last_line(head) + "\n").encode())
    fs.new_private(dest / fs.SNAPSHOT_NOTES, "".join(n + "\n" for n in notes).encode("utf-8"))
    rc, _ = fs.run(["tar", "-tzf", str(archive)], timeout=1800)
    rows.append((f"snapshot: the archive reads back (exit {rc})", rc == 0))
    need = before & after                                     # what was there all the time tar ran
    held = archived(archive)
    missing = sum((need - held).values()) if held is not None else sum(need.values())
    rows.append((f"snapshot: the archive holds the content of the data folders ({sum(need.values())} files, {missing} not in it"
                 + (", the archive cannot be read through" if held is None else "") + (": run again" if missing else "") + ")", held is not None and not missing))
    rows.append(("snapshot: the folder is 700 and its archive 600", fs.mode_of(dest) == 0o700 and fs.mode_of(archive) == 0o600))
    if not fs.failed(rows):
        fs.new_private(dest / fs.SNAPSHOT_COMPLETE, f"{archive.stat().st_size}\n".encode())
    return rows


def board_members(cfg: dict) -> tuple[dict, int]:
    """(the members file for the config's members as the board itself reads them, how many sessions the config lists as acting for one of them)."""
    sys.dont_write_bytecode = True                            # a dry run writes nothing, the checkout included
    sys.path.insert(0, str(fs.TOOLS.parent))
    try:
        from stackshot.core import members as stack_members
        people = [p for p in stack_members.build(cfg) if p.declared]
    except SystemExit:                                         # the board would not start on it; its own words name members, so they are not passed on
        raise fs.Usage("the board's own code refuses this config, so there is no member list to write: run `python3 -m stackshot.core.config check` in the checkout to see why") from None
    if not people or any(not p.name for p in people):
        raise fs.Usage("the config names no member, or one with no name ([[members]] name, or [instance] owner), so there is no member list to write")
    record = {p.name: {"boards": [BOARD], "aliases": list(p.aliases), "emails": [str(e).lower() for e in p.emails]} for p in people}
    return record, sum(len(p.agents) for p in people)           # one entry a member: the board's code refuses two of one name at import


def read_as_the_door(path: Path) -> tuple[tuple[int, int, int], list[str]] | None:
    """((members, aliases, addresses) as the front door reads the file, what it would drop or cannot use, with every name left out), or None when it cannot read it."""
    from stackshot.core import frontdoor_files
    notes: list[str] = []
    try:
        records = frontdoor_files.read_member_records(str(path), notes)
    except frontdoor_files.FileError:
        return None
    hidden = [re.sub(r"'[^']*'|\"[^\"]*\"", "(a name)", n) for n in notes]
    return (len(records), sum(len(m.aliases) for m in records.values()), sum(len(m.emails) for m in records.values())), hidden


def written(record: dict) -> bytes:
    return (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")


def member_checks(cfg: dict, expect: tuple[int, int, int] | None) -> tuple[dict, list[tuple[str, bool]]]:
    """(the members file to be made, the checks of the members file that will be used). Writes nothing that stays."""
    record, agents = board_members(cfg)
    kept = fs.secrets_dir() / "members.json"
    if agents:
        fs.say("NOTE", f"members: the config lists {agents} sessions as acting for a member; the front door's list holds none, so behind the front door they do not")
    if kept.exists():
        got = read_as_the_door(kept)
        which = f"the members file that is there and stays ({kept})"
    else:
        with tempfile.TemporaryDirectory(prefix="frontdoor-members-") as tmp:        # removed on every way out
            trial = Path(tmp, "members.json")
            fs.new_private(trial, written(record))
            got = read_as_the_door(trial)
        which = "the members file to be made"
    if got is None:
        return record, [(f"members: {which} can be read by the front door", False)]
    counts, dropped = got
    rows = [(f"members: the front door reads every entry of {which}" + (f" (not so: {' | '.join(dropped)})" if dropped else ""), not dropped)]
    if expect is None:
        fs.say("PLAN", "members", f"{which} holds {counts[0]} member, {counts[1]} aliases, {counts[2]} addresses (--expect checks these numbers)")
    else:
        rows.append((f"members: {which} holds {counts[0]} member, {counts[1]} aliases, {counts[2]} addresses (expected {expect[0]}, {expect[1]}, {expect[2]})", counts == expect))
    if kept.exists() and got is not None:
        try:
            same = json.loads(kept.read_text(encoding="utf-8")) == record
        except (OSError, ValueError):
            same = False
        if not same:
            fs.say("NOTE", "members: the file that is there differs from what the config gives now; it stays (to make it again, remove it first)")
    return record, rows


def secrets_step(co: Path, cfg: dict, record: dict, apply: bool, created: list[Path]) -> list[tuple[str, bool]]:
    """The secrets' checks; each file this run makes is added to `created`."""
    folder = fs.secrets_dir()
    if not apply:
        for name in FILES:
            there = (folder / name).is_file()
            fs.say("PLAN", f"secrets: {folder / name}", ("copied again" if there else "copied") if name == "board-token" else ("kept" if there else "made"))
        return []
    # the board's own code reads the token and writes its copy, so both read and write it exactly as the board and `stackshot frontdoor-token` do
    from stackshot.core import config as stack_config
    from stackshot.frontdoor import boardtoken

    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    for name, data in ((KEYS[0], None), (KEYS[1], None), ("members.json", written(record))):
        if os.path.lexists(folder / name):
            fs.say("KEPT", f"secrets: {name}")
            continue
        fs.new_private(folder / name, data if data is not None else base64.b64encode(secrets.token_bytes(KEY_BYTES)))
        created.append(folder / name)
    token, why = "", ""
    copy = folder / "board-token"
    there = os.path.lexists(copy)
    try:
        token = boardtoken.board_token(str(stack_config.secrets("oauth.env")))
        if not boardtoken.holds(str(copy), token)[0]:
            boardtoken.write(str(copy), token)
            if there:
                fs.say("NOTE", "secrets: board-token was there with another content and holds the board's token now")
            else:
                created.append(copy)
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
    rows.append((f"secrets: board-token holds the board's machine token{why}", bool(token) and boardtoken.holds(str(copy), token)[0]))
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


def undo_lines(made: list[Path], created: list[Path]) -> None:
    """How to remove what this run made, and nothing else."""
    for folder in made:
        fs.emit(f"snapshot: {folder}")
        fs.emit(f"undo of the snapshot (only when it is no longer wanted; this cannot be undone): {shlex.join(['rm', '-r', str(folder)])}")
    if created:
        fs.emit(f"undo of the secrets this run made (a file it kept is not removed): {shlex.join(['rm', '-f', *map(str, created)])}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/frontdoor_snapshot.py", description="Before a live switch: the snapshot, and the front door's secrets and members file.")
    ap.add_argument("--data", action="append", default=[], metavar="PATH", help="a data folder to archive (repeatable; default: [paths] repo and state)")
    ap.add_argument("--expect", default="", metavar="M,A,E", help="the members, aliases and addresses the members file must hold (needed with --apply)")
    ap.add_argument("--apply", action="store_true", help="write the snapshot and the secrets (default: a dry run that writes nothing)")
    a = ap.parse_args(argv)
    os.umask(0o077)
    made: list[Path] = []
    created: list[Path] = []
    rows: list[tuple[str, bool]] = []
    try:
        co = fs.checkout()
        cfg_path = fs.config_path()
        cfg = fs.read_toml(cfg_path)
        if cfg is None:
            raise fs.Usage(f"{cfg_path} cannot be read as a config")
        expect = expected(a.expect) if a.expect else None
        if a.apply and expect is None:
            raise fs.Usage("--expect MEMBERS,ALIASES,ADDRESSES is needed with --apply")
        data = data_paths(cfg, a.data)
        if a.apply:
            fs.take_lock()
        record: dict = {}
        if not fs.failed(fs.single_user_checks(cfg)):          # any other config is refused by the snapshot step, and its members may be the front door's already
            record, rows = member_checks(cfg, expect)          # before anything is written
        bad = report(rows)
        for name, step in (("snapshot", lambda: snapshot(co, cfg_path, cfg, data, a.apply, made)),
                           ("secrets", lambda: secrets_step(co, cfg, record, a.apply, created))):
            if bad and (a.apply or name == "secrets"):
                fs.say("NOTE", f"the {name} step was not started: an earlier check did not pass")
                continue
            more = step()
            bad += report(more)
            rows += more
    except fs.Usage as e:
        return fs.cannot(e)
    except fs.Locked as e:
        fs.say("REFUSE", str(e))
        return fs.FAILED
    finally:
        undo_lines(made, created)                              # also when a step ended in an error: what it made is said
    if not a.apply:
        fs.emit("dry run: nothing written (add --apply)")
        return fs.FAILED if bad else fs.OK
    fs.emit(f"{len(rows) - len(bad)} of {len(rows)} checks pass")
    if made and not bad:
        fs.emit(f"the cut-over needs this folder: {fs.command('frontdoor_cutover.py', '--snapshot', str(made[0]), '--apply')}")
    return fs.FAILED if bad else fs.OK


if __name__ == "__main__":
    sys.exit(main())
