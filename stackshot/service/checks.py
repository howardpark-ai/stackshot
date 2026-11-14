"""checks.py: the done check, an item's `metadata.check`, and the pass that reads it.

A check is one of a fixed list the server reads itself on its minute pass (a pull request merged, an item closed, a session on a lane, a systemd user unit active): when it passes the server closes the
item, when it can no longer pass (a pull request closed unmerged) it records the wait as failed and tells the keeper at once. This module holds the forms and their parse (`parse_check`, `check_label`, `check_changed`), the readers
of each kind (`pr_merged`, `unit_active`, `lane_on`), the pass's own state in <state>/checks.json (`checks_load`) and the pass itself (`check_tick`, with `check_close`, `check_fail` and `check_wait`). The readers of
a pull request's merged state are shared with the step proofs (service/proofs.py) and the event waits (service/event_waits.py): one record per pull request, one GitHub read.

What it still reaches in server.py comes through `Hooks` in service/checks_hooks.py, looked up when it runs, so a suite that replaces one on server.py is the one called. A suite that replaces a function or a
clock of this module sets it here (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core import ghbudget as _gb
from stackshot.core import lanes as _lanes
from stackshot.core.instance import NAME, OWNER
from stackshot.core.store import _item_files
from stackshot.github import ghsync as _gh
from stackshot.github import pr_state as _prs
from stackshot.model import activity as _activity
from stackshot.model import model as _model
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.model.ids import _norm_id
from stackshot.service import telling as _telling
from stackshot.service import wakes as _wakes
from stackshot.service import writes as _writes
from stackshot.service.checks_hooks import hooks as _hooks
from stackshot.service.store import _load, _path
from stackshot.waits import watchers as _watch


# ----------------------------------------------------------------------------- the done check
# An item whose mover handed its work to another session (its next named that session, or its needs did) stayed open after the
# work was done: nothing triggered the mover's check-and-close step, and a session turn spent on asking is what he wants least
#. So a hand-off carries one of two things. A wake: the mover is told at the date, as any wake
# tells. Or a done check, metadata.check, one of a fixed list the server reads itself on its minute pass (never free shell):
#   pr_merged <owner>/<repo>#<n>   the pull request is merged: one GET of the PR through ghsync's client, at most one per PR
#                                  every [check] github_minutes, shared by the items that name it, backing off while GitHub is down
#   item_closed <id>               that board item is completed (the store)
#   lane <session> <lane>          the fleet tool's lane record puts that pane on that lane: its row in [client] lanes_file, else
#                                  the default lane (lane-default beside it; lanes.DEFAULT_CODE when that file is absent), as the fleet tool
#                                  reads them; the lane a running claude is on is in its environment, which the server never reads.
#                                  Off while lanes_file is unset (refused at the write). `sala_lane`, its former name,
#                                  is still read on a stored item and taken on a write, stored as `lane`. A lane's old code and its current one
#                                  are one lane in every comparison (lane_name, lanes.code), as is
#                                  any other lane's old code and its current one (sala's lane-names file lists the aliases); shown as the current code
#   unit_active <unit>             the systemd user unit is loaded and active on the server box (one `systemctl --user show`)
# When a check passes the server closes the item itself: outcome done, the reason naming the check, as the server's own act (no
# page owed, like a wake or a release). The rule: a close nobody was told of is a wait that ended
# unseen, so the keeper of the item's page is told in one line (a close with his own words on the item is a row on his For you list,
# not a message to the mover); the sessions in its needs and the observers are not, so no session turn is spent checking. With the mirror on
# the server's note goes to the History, and the items that waited on it (after) are released and told as any close releases them.
# A check that passes while the item waits on the owner's decision (needs holds decision, so an ask is open) closes nothing: closing would
# drop the ask he has not answered (a past defect). The item stays open, one note says the check is met and waits for the
# decision (check_wait, once per check: the pass's record items[gid]["met"] keeps it), and the first pass after the decision is cleared closes
# the item as for any passed check. Every other needs (external, a session) closes as before.
# The same rule makes the other end fail at once: a pr_merged whose pull request was closed without being merged can never pass,
# so the wait is recorded as failed (metadata.wait_failed) and the keeper told at once (check_fail). A check the server cannot read (GitHub down, a unit name not found, no lane
# data) never closes: it is logged once per error and tried again each pass. The gate: an update that creates the hand-off is
# refused unless the item carries a check or a wake (a front agent's hand-off is not asked for either, and its own wake or check on an item another
# session moves is refused: gates.gate_sender_watch). A hand-off is a line of next in its form `<session>: <action>`: a session
# other than the mover and the writer, one a page or the fleet knows, at the start of a line (after a list marker, "- " or
# "1. ", at most), followed by a colon. A name anywhere else in next is not one: inside a page slug (projects/my-project), a
# `#s=<name>` link or a sentence that mentions the session ("other-engineer merged it; verify") hands nothing over
# (a review of the first cut: the plain-word match fired on all three). A write that leaves an
# existing hand-off as it was is not asked again, and an item already in that state before this rule is never retro-refused. A
# session named in needs alone is not a gated hand-off: it is asked about the item at each of its turn ends and told to close it
# or hand it back (tell_needed). A check alone is a filing edit: no page owed, the state clock unmoved. The pass's own state
# (the last error per item, the GitHub answers and backoff) lives in <state>/checks.json, out of the store, so a pass that
# reads touches no item file.
CHECK_FORMS = ("pr_merged <owner>/<repo>#<n> (or the PR's URL)", "item_closed <item id>", "lane <session> <lane>",
                "unit_active <unit>.service (a systemd user unit on the server box; .timer, .socket, .path, .target, .mount too)")
CHECK_HOW = "one of: " + " | ".join(CHECK_FORMS) + "; check=\"none\" clears it"
PR_RX = re.compile(r"^(?:https?://github\.com/)?([\w.-]+)/([\w.-]+?)(?:/pull/|#)(\d+)/?$")   # an owner or repo of dots alone (., ..) is refused after the match
PANE_RX = re.compile(r"^[A-Za-z0-9][\w.-]{0,63}$")
LANE_RX = re.compile(r"^(?=.{1,20}$)[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")   # one lowercase word, hyphens inside allowed (aws-platform)
# A lane may be renamed on the fleet tool's side, so either word may be in lanes.tsv, lane-default, limit.json, lane-signin.state or a stored check.
# Every comparison and every shown name goes through lane_name: the two words are one lane, in both directions. Stored data is never rewritten.
# The words are lanes.py's: the fleet tool's lane-names file (a lane's aliases) over a fixed floor of old codes; stackshot never spells a lane's plan name, its display name comes from the file (lanes.display_name).


def lane_name(lane: Any) -> str:
    """A lane name as stackshot compares and shows it: the current code of the lane a word names (an old code or alias reads as the current one), else the name as it is."""
    return _lanes.code(lane)


def lane_codes_hint() -> str:
    """`; the tool's lanes: a, b (Name)` with the lane codes (and display names) the fleet tool's lane-names file lists, for a refusal. With no file (or none listed)
    `; lanes such as a, b`: the floor's codes and the plain ones (lanes.FALLBACK_CODES), so the refusal always names valid lanes."""
    cs = _lanes.codes()
    if cs:
        return "; the tool's lanes: " + ", ".join(_lanes.shown(c) for c in cs)
    return "; lanes such as " + ", ".join(_lanes.FALLBACK_CODES)


def check_changed(new: Any, old: Any) -> bool:
    """A write changed an item's check: the two stored strings differ once each lane word is read by its code (a re-sent old word over a stored one is no change)."""
    return check_lane_shown(new or "") != check_lane_shown(old or "")


def check_lane_shown(check: str) -> str:
    """A stored lane check with its lane name in the current word (an old code in `lane box-a <old>` reads as the current one); any
    other text as it is."""
    parts = str(check or "").split(" ")
    if len(parts) == 3 and parts[0] in ("lane", "sala_lane"):
        parts[2] = lane_name(parts[2])
    return " ".join(parts)
# A unit name starts with a letter or a digit: one starting with "-" would read as an option to systemctl (-Hhost.service reaches
# another host), and the argv puts "--" before it besides (the review of the first cut).
UNIT_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.\\@-]{0,199}\.(?:service|timer|socket|path|target|mount|slice|scope)$")
CHECK_EVERY = 60.0            # seconds between passes; the runner calls it every 60 s
CHECK_GH_BACKOFF_MAX = 3600.0  # while GitHub is down: the wait doubles from [check] github_minutes up to this
CHECK_LAST = [0.0]
CHECK_LOGGED: dict[str, str] = {}   # gid → the error last logged for it: one stderr line per new error, not one per pass
CHECK_GH: dict[str, Any] = {}       # "<api> <owner/repo>" → the ghsync client that reads that repo's pull requests


def parse_check(text: str, gid: str = "") -> str:
    """A done check as a session writes it → its stored form (the kind, then its argument, normalised); refused, with the valid
    forms, when it is none of them. `gid` = the item it is written on (item_closed may not name the item itself)."""
    s = " ".join(str(text or "").split())
    kind, _, arg = s.partition(" ")
    kind = kind.lower()
    bad = lambda why: ToolError(f"Refused: check {text!r}: {why}. check is {CHECK_HOW}")
    if kind == "pr_merged":
        m = PR_RX.match(arg)
        if not m or not m.group(1).strip(".") or not m.group(2).strip("."):   # ./x, ../.., a/..: not a repo, a path
            raise bad("pr_merged names the pull request as <owner>/<repo>#<n> or by its URL")
        return f"pr_merged {m.group(1)}/{m.group(2)}#{m.group(3)}"
    if kind == "item_closed":
        try:
            g = _norm_id(arg)
        except ToolError:
            raise bad("item_closed names a board item by its id (or <letter><n> for an older item)")
        if not _path(g).exists():
            raise bad(f"item_closed names {_gh.shown(g)}, which does not exist")
        if gid and g == gid:
            raise bad("item_closed cannot name the item itself")
        return f"item_closed {g}"
    if kind in ("lane", "sala_lane"):        # sala_lane: the kind's former name, stored as lane
        parts = arg.split()
        if len(parts) != 2 or not PANE_RX.match(parts[0]) or not LANE_RX.match(parts[1]):
            raise bad(f"lane takes a session name and a lane (a short lowercase word: a lane code, or an old word of one{lane_codes_hint()})")
        if lanes_file() is None:
            raise bad("lane needs a lane record, and none is configured ([client] lanes_file is empty), so it could never pass")
        return f"lane {parts[0]} {lane_name(parts[1])}"
    if kind == "unit_active":
        if not arg or " " in arg or not UNIT_RX.match(arg):
            raise bad("unit_active takes one systemd user unit name with its type suffix (stackshot.service, backup.timer)")
        return f"unit_active {arg}"
    raise bad("not a check the server knows")


def check_label(check: str) -> str:
    """A stored check as a session reads it: an item_closed's id as shown (never the store id)."""
    kind, _, arg = str(check or "").partition(" ")
    return f"item_closed {_gh.shown(arg)}" if kind == "item_closed" and arg else check_lane_shown(check)


def unit_run(argv: list[str]) -> str:
    """Run `argv` (systemctl's), its stdout: no shell. Replaced by a test with a stub that records the argv."""
    r = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    return r.stdout


def unit_show(unit: str) -> str:
    """`systemctl --user show -p LoadState -p ActiveState -- <unit>`, its stdout: the unit name an argument the gate has matched
    against UNIT_RX (a letter or digit first), behind `--` so that systemctl never reads it as an option."""
    return unit_run(["systemctl", "--user", "show", "-p", "LoadState", "-p", "ActiveState", "--", unit])


def unit_active(unit: str) -> tuple[bool, str]:
    """→ (the unit is loaded and active, the error): a unit systemd does not know (LoadState not-found) or an answer with no
    state is an error, never a fail, so a mistyped or removed unit never closes an item."""
    try:
        out = str(unit_show(unit) or "")
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"systemctl did not answer: {e}"
    kv = dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)
    load, active = kv.get("LoadState", "").strip(), kv.get("ActiveState", "").strip()
    if not load or not active:
        return False, f"systemctl gave no state for {unit}"
    if load != "loaded":
        return False, f"unit {unit} is {load}"
    return active == "active", ""


def lanes_file() -> Path | None:
    """[client] lanes_file, read at use (a reload is live): the fleet tool's lane record, one row per session, `<session>\\t<lane>`;
    None when unset or empty (no lane data: the lane check is off)."""
    v = str(_cfg.get("client", "lanes_file") or "").strip()
    return Path(os.path.expanduser(v)) if v else None


def lane_record(pane: str) -> tuple[str, str]:
    """→ (the lane the fleet tool's record puts `pane` on, the error). The record, as the tool reads it (the stackshot–sala
    contracts): the session's row in lanes_file, else the first line of lane-default beside it, else lanes.DEFAULT_CODE. No lanes_file at all
    is an error (the path may be wrong, and a pass that cannot read never closes); no lane-default is the tool's own fallback."""
    p = lanes_file()
    if p is None:
        return "", "no lane data: [client] lanes_file is empty"
    try:
        rows = p.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        return "", f"lane data not readable: {p} ({e.strerror or e})"
    rec = ""
    for ln in rows:
        parts = ln.rstrip("\r").split("\t")
        if len(parts) >= 2 and parts[0] == pane:
            rec = parts[1].strip(); break
    if not rec:
        try:
            rec = (p.with_name("lane-default").read_text(encoding="utf-8").splitlines() or [""])[0].strip()
        except OSError:
            rec = ""
        rec = rec or _lanes.DEFAULT_CODE
    return lane_name(rec), ""


def lane_on(pane: str, lane: str) -> tuple[bool, str]:
    """→ (the lane record puts `pane` on `lane`, the error): lane_record against the lane asked."""
    rec, err = lane_record(pane)
    return (False, err) if err else (rec == lane_name(lane), "")


def check_gh_every() -> float:
    """[check] github_minutes, in seconds: how often one pull request is read at most (5 min when unset; 0 = every pass)."""
    v = _cfg.get("check", "github_minutes")
    try:
        return max(0.0, 60.0 * (5.0 if v is None or v == "" else float(v)))
    except (TypeError, ValueError):
        return 300.0


def check_gh(repo: str) -> Any:
    """ghsync's client for the PR's repo (the mirror's own when it is that repo, else one of its own on the same token and
    API base), kept for the process. Reads are not paced by the client; the pass's cadence is the pace."""
    if _cfg.canon_name(repo) == _cfg.canon_name(_gh.repo()):
        return _gh.client()       # not kept here: ghsync keeps it, keyed by the current [github] issues_repo and issues_repo_id
    key = f"{_gh.api_url()} {repo}"
    c = CHECK_GH.get(key)
    if c is None:
        c = CHECK_GH[key] = _gh.GitHub(repo, _gh.api_url(), shared=True)
    return c


def check_ref(ref: str) -> str:
    """A pr_merged check's argument "owner/repo#n" with its repo through [github.moved] (config.canon_name: a name the table does not know is
    left exactly as written), the key its answer is kept under in checks.json. Read at each call."""
    repo, sep, n = str(ref or "").partition("#")
    return _cfg.canon_name(repo) + sep + n


def pr_merged(ref: str, now: float, gh_st: dict[str, Any]) -> tuple[bool, str]:
    """→ (the PR `ref` (owner/repo#n) is merged, the error). One GET per PR every [check] github_minutes, its answer kept in the one shared record
    store of pr_state.py (read by the done check, the step proof and the event wait alike) and in `gh_st` (the caller's own dict: checks.json, the
    step proof's file, the event waits' memory) for the items that name the same PR and for the passes in between; GitHub down or rate-limited
    backs off (doubling, at most an hour, or what GitHub asked for), a refusal (a PR that is not there, a token that cannot read the repo) is an
    error tried again at the normal cadence. The reader itself is pr_state.merged."""
    ref = check_ref(ref)       # [github.moved]: the PR by its current name, so the old and the new name of one PR share one read and one kept answer
    return _prs.merged(ref, now, gh_st, check_gh, check_gh_every(), CHECK_GH_BACKOFF_MAX)


def check_dead(check: str, gh_st: dict[str, Any]) -> str:
    """Why a check can no longer pass, "" while it can: a pr_merged whose pull request was closed without being merged. Read
    from the answer pr_merged kept for the PR (the same read, no second GET)."""
    kind, _, arg = str(check or "").partition(" ")
    arg = check_ref(arg) if kind == "pr_merged" else arg
    rec = gh_st.get(arg) if kind == "pr_merged" and isinstance(gh_st.get(arg), dict) else {}
    return str(rec.get("dead") or "")


def check_eval(check: str, now: float, gh_st: dict[str, Any]) -> tuple[bool, str]:
    """One stored check → (passed, error). An error is a condition the server could not read this pass; (False, "") is a check
    that has not passed yet."""
    kind, _, arg = str(check or "").partition(" ")
    if kind == "item_closed":
        try:
            return _load(arg).get("status") == "completed", ""
        except ToolError:
            return False, f"no item {arg}"
    if kind == "unit_active":
        return unit_active(arg)
    if kind in ("lane", "sala_lane"):        # sala_lane: an item stored before the rename
        parts = arg.split()
        return lane_on(parts[0], parts[1]) if len(parts) == 2 else (False, f"{kind} needs a session and a lane")
    if kind == "pr_merged":
        with _gb.tag("done_check"):
            return pr_merged(arg, now, gh_st)
    return False, f"not a check the server knows: {kind}"


def checks_path() -> Path:
    return _cfg.state("checks.json")


def checks_load() -> dict[str, Any]:
    try:
        d = json.load(open(checks_path(), encoding="utf-8"))
    except Exception:
        d = {}
    return {"items": d.get("items") if isinstance(d.get("items"), dict) else {}, "github": d.get("github") if isinstance(d.get("github"), dict) else {}}


def check_words(gid: str, item: dict[str, Any] | None = None) -> str:
    """The item's check line's tail for get and the replies: what the pass found last."""
    rec = checks_load()["items"].get(gid) or {}
    err = str(rec.get("err") or "")
    cur = " ".join(str(((item or {}).get("metadata") or {}).get("check") or "").split())      # the note is true only of the check now on the item, while his decision is still open
    met = f"; met, and waiting for {OWNER}'s decision before it closes the item" if item and rec.get("met") and rec.get("met") == cur and _hooks().rmod_needs_kind(item) == "call" else ""
    return " (the server closes the item when it passes" + met + (f"; not readable at the last pass: {err}" if err else "") + ")"


def check_close(gid: str, it: dict[str, Any], check: str, now: float) -> None:
    """Close `gid` on its check, the server's own act: outcome done, the reason naming the check, the live fields cleared as a
    session's close clears them, the description as it stands (the reason says how it ended). No page owed; the History
    and the after releases are the record. The owner's one rule: a close that nobody was told of is a wait that ended unseen, so the
    item's mover is told (tell_check_closed); a close with his words on the item is a row on his For you list (_foryou_on_save)."""
    _telling.CLOSE_WAS.item = json.loads(json.dumps(it))      # the close is told to the mover, which the close drops
    meta = dict(it.get("metadata") or {})
    _steps.close_meta(meta, "done", NAME, now)       # a close marks the open steps, the server's own close included
    for k in ("next", "next_by", "owner_step", "ask", "needs", "options", "after", "hold", "hold_set", "wake", "recycle", "recycle_at", "idle", "check", "watch_reason", "waiting", "wait_failed", "wait_basis", *_states.DROP_ON_CLOSE, *_states.CLOSE_EXTRA, *_model.DROP_ON_CLOSE, *_watch.DROP_ON_CLOSE):
        meta.pop(k, None)
    label = check_label(check)
    meta["outcome"], meta["reason"] = "done", _hooks().fit(f"done check passed: {label}", _hooks().close_reason_max())     # kept to the reason limit a session's close is held to
    it["status"] = "completed"; it["metadata"] = meta
    it["updated"] = it["state_updated"] = it["confirmed"] = now
    _writes.save(gid, it, activity=_activity.EVENT)      # no writer, no note: the History line is the change itself ("completed · done — done check passed: …"); the event the check waited for is activity
    print(f"check: {gid} closed, {label} — {it.get('subject')}", file=sys.stderr, flush=True)
    try:
        _telling.tell_check_closed(gid, it, label)
    except Exception as e:  # noqa: BLE001
        print(f"check: {gid} closed but its keeper was not told: {e}", file=sys.stderr, flush=True)
    _telling.CLOSE_WAS.item = None
    try:
        _wakes.release_after(gid, "done", "", "")
    except Exception as e:  # noqa: BLE001
        print(f"check: {gid} closed but its after releases failed: {e}", file=sys.stderr, flush=True)


def check_fail(gid: str, it: dict[str, Any], check: str, why: str, now: float) -> None:
    """A done check that can no longer pass (a pr_merged whose pull request was closed unmerged, the owner's one rule) fails at once
    instead of reading "not yet" for ever: the check goes, the failure is recorded on the item (metadata.wait_failed),
    the item stays open and both clocks move, as a wait ending does. The server's own act:
    no page owed, the History says it. The item's mover is told at once (tell_wait_failed)."""
    meta = dict(it.get("metadata") or {})
    meta.pop("check", None); meta.pop("idle", None); meta.pop("waiting", None); meta.pop("watch_reason", None)
    label = check_label(check)
    meta["wait_failed"] = {"what": f"check {label}", "why": why, "at": now}
    it["metadata"] = meta
    it["updated"] = it["state_updated"] = now
    _writes.save(gid, it, note=f"check failed: {label}: {why}; the item stays open")
    print(f"check: {gid} failed, {label}: {why} — {it.get('subject')}", file=sys.stderr, flush=True)
    _telling.tell_wait_failed(gid, it, f"check {label}", why)


def check_wait(gid: str, it: dict[str, Any], check: str) -> None:
    """A done check that is met while the item waits on the owner's decision (needs holds decision) does not close it: closing would drop
    the ask he has not answered. The item stays open, as it was (no clock moves, nothing cleared), and one line says the check is met and
    waits for the decision: the server's own note and the History. The pass calls this once per check (its record,
    items[gid]["met"], keeps the check text); the first pass after the decision is cleared closes the item as any passed check does."""
    label = check_label(check)
    _writes.save(gid, it, note=f"done check met: {label}; the item needs {OWNER}'s decision, so it stays open and the server closes it once the decision is cleared", activity=_activity.EVENT)
    print(f"check: {gid} met, {label}: waits for the decision before it closes — {it.get('subject')}", file=sys.stderr, flush=True)


def check_unchanged(gid: str, it: dict[str, Any]) -> dict[str, Any] | None:
    """The item read again after its check passed → the fresh record when it is still open and as it was at the load (the store
    keeps no revision counter: `updated` moves on every write, and the whole record is compared, which catches a re-key or a
    write that left the clock alone too), else None. The check's call (a GET of up to 20 s) runs between the load and the
    close; a session's write in that window (a new next, a cleared check, a close of its own) would be overwritten by the
    loaded copy, so such a pass skips the item and the next pass reads it afresh (the review of the first cut)."""
    try:
        again = _load(gid)
    except Exception:
        return None
    if again.get("status") != "open" or again.get("updated") != it.get("updated") or again != it:
        return None
    return again


def check_tick(now: float | None = None) -> list[str]:
    """One pass over the open items' done checks (at most once a minute; the runner calls it every 60 s). → the gids closed."""
    now = time.time() if now is None else now
    if now - CHECK_LAST[0] < CHECK_EVERY:
        return []
    CHECK_LAST[0] = now
    st = checks_load()
    items: dict[str, Any] = {}
    closed: list[str] = []
    failed = 0
    seen_refs: set[str] = set()
    for gid, _p in _item_files():
        try:
            it = _load(gid)
        except Exception:
            continue
        meta = it.get("metadata") or {}
        check = " ".join(str(meta.get("check") or "").split())
        if it.get("status") != "open" or not check:
            continue
        keep = {"met": check} if (st["items"].get(gid) or {}).get("met") == check else {}     # the waiting note was written for this check: a pass that cannot tell (an error, a race) keeps the record, only a clean "not met" resets it
        try:
            ok, err = check_eval(check, now, st["github"])
        except Exception as e:  # noqa: BLE001  — a check that raises is an error like any other: logged, tried again
            ok, err = False, f"{type(e).__name__}: {e}"
        if not err and ok and _hooks().rmod_needs_kind(it) == "call":     # met while his decision is open: the item waits (one line, once), and the check closes it on a later pass
            fresh = check_unchanged(gid, it)
            if fresh is not None and _hooks().rmod_needs_kind(fresh) == "call":
                if not keep:
                    check_wait(gid, fresh, check)
                items[gid] = {"err": "", "at": now, "met": check}
                CHECK_LOGGED.pop(gid, None)
            else:
                print(f"check: {gid} changed while its check ran, left for the next pass", file=sys.stderr, flush=True)
                if keep:
                    items[gid] = {"err": "", "at": now, **keep}
            if check.startswith("pr_merged "):
                seen_refs.add(check_ref(check[len("pr_merged "):]))
            continue
        if not err and ok:
            fresh = check_unchanged(gid, it)
            if fresh is not None:
                check_close(gid, fresh, check, now)
                closed.append(gid)
                CHECK_LOGGED.pop(gid, None)
                continue
            # written or closed while the check ran: this pass leaves it (its GitHub answer kept, no error recorded), the next reads it afresh
            print(f"check: {gid} changed while its check ran, left for the next pass", file=sys.stderr, flush=True)
            if check.startswith("pr_merged "):
                seen_refs.add(check_ref(check[len("pr_merged "):]))
            continue
        dead = "" if (err or ok) else check_dead(check, st["github"])     # The owner's one rule: a check that can never pass fails now, never "not yet" for ever
        if dead:
            fresh = check_unchanged(gid, it)
            if fresh is not None:
                check_fail(gid, fresh, check, dead, now)
                failed += 1
                CHECK_LOGGED.pop(gid, None)
                continue
            print(f"check: {gid} changed while its check ran, left for the next pass", file=sys.stderr, flush=True)
            seen_refs.add(check_ref(check[len("pr_merged "):]))
            continue
        if check.startswith("pr_merged "):   # the PR's answer is kept while an item still open names it
            seen_refs.add(check_ref(check[len("pr_merged "):]))
        if err and CHECK_LOGGED.get(gid) != err:
            CHECK_LOGGED[gid] = err
            print(f"check: {gid} {check}: not readable, tried again next pass: {err}", file=sys.stderr, flush=True)
        elif not err:
            CHECK_LOGGED.pop(gid, None)
        items[gid] = {"err": err, "at": now, **(keep if err else {})}
    st["items"] = items
    st["github"] = {k: v for k, v in st["github"].items() if k in seen_refs}
    try:
        p = checks_path(); p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(st, indent=1) + "\n", encoding="utf-8"); os.replace(tmp, p)
    except Exception as e:
        print(f"check: state not saved: {e}", file=sys.stderr, flush=True)
    if closed or failed:
        _hooks().publish()
    return closed
