"""audit_run.py — the daily board audit as a script.

Until now the audit was a standing Claude Code session (the audit agent) that read every open item once a day. Half of what it checked reads only item fields, so code does that, with no
tokens; the checks that need judgment get one `claude -p` call per suspect item, picked by cheap heuristics, under a fixed rubric (audit_rubric.txt) and a cap on calls. `audit.py cue`
(the timer's `audit.py cue scheduled`, the board's "Audit now") runs this when `[audit] mode` is "script" (the default) and cues the agent as before when it is "agent": switching back is the rollback.

    audit.py run [--dry-run]      one run now (what the timer and the button start); refused (exit 1) while a run is in progress, when [audit] enabled is false or when the mode is "agent";
                                  --dry-run lists the suspects and the field findings, makes no model call, sends nothing, writes no record, and is never refused

The checks (category names as the audit agent's brief has them; one finding = {"id", "project", "owner" (= mover), "mover", "category", "detail", "fix", "source"}):

  in code, no tokens      ask-missing (a decision item with no ask) · next rules (tools/next_report.py, N1 to N7) · idle-pass (counted in by_category, not a finding)
  not made here           the ten-minute passes make these (audit_checks.py, silence.py, the server's runner): stuck-elsewhere (the first open step opens with someone other than the item's mover) and the board checks'
                          arbitrary-hold and mislabeled-state, the filing pass (`filing_pass`); stale (an item's own wake has passed with no write since), the dates pass (`dates_pass`); an item on an agent with no
                          activity for 45 minutes (stale, for an item with no date of its own; the board checks' idle-on-agent), the silence pass (`silence.silence_pass`). They
                          send their findings to the same recipient through the same `deliver_findings`, with the same text and send stamps (`merged_sent` joins the records), so a finding reaches its
                          mover once whichever pass finds it; they stand still while a run is in progress. Not counted in this run's `by_category`, the unmoved digest, the threshold or the 20% tightening share.
  one model call each     next-done · wrong-needs · ask-missing (an ask that no longer fits) · unneeded-escalation · older-than-page · obsolete-wait (a waiting item, held or after another item or parked or outside, whose wait a later change may have overtaken) · why-not-now (a stored doing item whose wake is more than an hour out and whose every open step is dated for that day or later: is there a concrete reason the step cannot run before then?) · goal-unclear (an open item whose subject and `Goal:` bullet are new or reworded since the last judgment: does each name an outcome wanted rather than a symptom, cause, task or trigger, and do the two name the same one? Items with no Goal bullet are the one-time pass's, tools/goal_pass.py; at most `GOAL_MAX` a run; the stamps judged are the record's `goal_judged`). A suspect is an item a heuristic picks for one or more of
                          these (`suspects`); the call returns {"finding": "yes"|"no", "check", "reason", "fix"}. At most `[audit] max_calls` calls, one at a time; an item judged "no" or "yes" is not
                          judged again until it is written; a call that fails is not counted as a "no" (the item is tried again next run), and three failures in a row end the calls.
  the orphan hand-over    the first stage of a run, before the board is read (`orphan_stage`; the server does the work, `POST /client/orphan-handover`, because the item lock and the fleet's heartbeat are its): an open item whose
                          mover (an alive item) or post-wake mover (a waiting one) is a session that is gone, the last agent of a retired project included, goes to the closest live agent (successor.py: a live background agent of an item with a mover, else the project's own front agents,
                          its parent's -main, its hub's, the scope's general -main), through the hand-off pass's write, with a History line giving the reason and a message to the new mover. Never an item an owner moves;
                          an item with no live successor stays and is listed in the summary (`orphans.left`). Idempotent. `[audit] orphan_handover`: "report" (default: lists, moves nothing), "apply", "off". `--dry-run` lists
                          what would move and writes nothing. `audit.py orphans [--apply]` makes the same call by hand.
  the proof-waits stage   after the judgment calls and before the pages stage, in code (`proof_stage`, `audit_checks.proof_wait_findings`; no model call, no write): an open item held for a real event (an event wait for a recycle, a fleet op
                          or a job run, or a hold or park whose own words say it is kept open to see the fix happen for real) closes if the fix's tests passed and it is live (the item carries a release notice, `released_told`);
                          otherwise its mover is told to stage the event now (a downgrade, a probe, a dry run) and close on the result. A wait that cannot be staged (an outside party, news only the owner relays, an anchor event, another
                          item's close, a real-world date, a release still to come, a mover that is no session) keeps its basis named on the record (`proof_waits.left`) and is left alone. The finding (category `proof-wait`) goes to the
                          item's mover through the usual delivery (the same send stamps; when no mover can be reached it falls back like the other findings; an item that is the owner's move is left alone), and at most `PROOF_MAX` (10) fresh ones a run (`proof_waits.capped` counts the rest, which
                          wait for the next run). The audit closes nothing.
  the pages stage         after the judgment calls and under the same `[audit] max_minutes` limit, the server makes its page-debt call (`pages_stage`; POST /client/page-debt, because the debt ledger and the page writes are the
                          server's): one model call per page with page updates that moved to the page's keeper, the smallest Current-state edit, applied (live) or logged (shadow). It runs only while `[router] page_debt` is on,
                          once per run (twice a day with the timer's two times; a page is marked per run), and a page whose call fails does not stop the others or the run. The record's `pages` and the summary line carry
                          what it did: pages called, the results, the pages without an edit, the pages left at the time limit.
  the pattern review     the last stage of a model run, after the pages stage (`pattern_stage`; `[audit] pattern_review`, "shadow" by default, "off" = nothing): it reads the findings every audit made since the review before it
                          (the findings log, `<paths.state>/audit/findings-log.jsonl`: each audit pass appends a finding the first time its record shows it, and the run appends its own fresh ones), groups the repeats by kind, agent and
                          project, and for the patterns (at least `PATTERN_MIN` appearances on `PATTERN_MIN_ITEMS` items; none drafted in the last 7 days; at most `PATTERN_MAX` per run) makes ONE model call, on the audit's lane and
                          model, inside `[audit] max_minutes` and `max_calls` (the call keeps one of the calls), that drafts one guardrail per pattern: a hook, a mod, a tool's text, a rulebook line, or a new audit or an edit to one.
                          In shadow the drafts are only logged: the record's `pattern_review` holds them (with where each would go: the builder as a board item, the rulebook's own path, or the owner as a decision), the summary line names
                          them, and nothing is sent, opened or edited. A stage that fails is recorded as failed and the run goes on.

Output, as the agent reported: one message per recipient per run, `<id> · <category> · <evidence> · <what would fix it>` per line. A finding goes straight to its mover only when the mover is a background agent
(`recipient`); a front agent's, a retired, an outside or no mover's finding goes to the project's page key (`projects/<slug>`, unmarked), never to a front agent; the owner's own item (he is the mover) goes to the
project's -main agent with `[for <owner>]` first (a second marked path: a finding that went to a builder and stayed unanswered through its reminders and the builder-level send goes once to -main, marked for its owner; see split_sent). A finding already sent (same item, same check) whose item has not been written since is not sent again: it stays on the record with its `sent` time and counts in
`repeats`. The unmoved digest below names an item once per unmoved stretch (`stuck[].chased`); a finding on the previous run's record whose item has had no write since goes, as a job, to the project's builder and onto the record's `stuck`
list (`first_flagged` kept); a summary to `[audit] summary_to` (default `projects/example`); and ONE message to `[audit] builder` when a check has at least `[audit] threshold` findings or the run trips a tightening
condition (more than 20% of the open items flagged, the same session or the same category on top three days running). The record is `<paths.state>/audit/run-<date>-<HHMMSS>.json` (the start time, so a
second run the same day keeps the first one's record), as audit.py reads it, with `idle_pass`, `judged`, `calls` and `messages` beside the agent's keys. A run that dies finishes its record with `error`
and puts a line in cues.jsonl, so it never holds the next cue back. A run begins no new model call once `[audit] max_minutes` (default 100) have passed since it started (`calls.timed_out`). A finding
whose message to its mover fails goes to the project's -main agent, noted in `messages` (`kind: fallback`); when the refusal says the recipient is a front agent (the mover was a session id the role map
did not know as one), it goes unmarked to the project's page key, where the router hands it on (`kind: project`).

Page agent lines (tools/page_agent_report.py, `audit.py page-agents` reads them without sending): after the item messages the run sends each page's -main agent (else the parent page's, the hub's, the scope's general one: the router's
fallback, the first that sala knows; when none of them is live the audit's own -main agent, never the router's fallback name, which may be the gone one) ONE message listing that agent's pages' lines of the `agents:` map, `agent:` and `display-name:` that name a session sala no longer knows (`<page> · <line> · <name> · <what fixes it>`; a front
agent's starts with `[for <owner>]`; kind `page-agents` in `messages`). It repeats each day until the line is fixed. When sala's session list cannot be read or is empty nothing is flagged and the summary says "not checked". The lines
are on the record as `page_agents` and are no finding of the item checks: they count in neither `by_category` nor the tightening. The same message carries a third kind of line: a `type: project` page that is no sub-page, with open items
(or items touched in the last 30 days) and no front agent on its `agents:` map (`no agents map` / `no front agent`, the name is the item count); it goes the same way and repeats the same way. A fourth kind, `session off the map`, names the live sessions that created, move or are the contact of
an open item of a project whose `agents:` map has no line for them (`anchors.off_map`); one line for each project page, to the same recipient.

The project registry (tools/registry_report.py, `audit.py registry` reads it without sending): every run checks the project record and the pages it points at, and the findings are on the run record as `registry` (they are no finding of the item
checks: they count in neither `by_category` nor the tightening). Each is `page · problem · name · what fixes it`: a page with no project (`adopt`), a project whose page is gone, page lines that differ from the record (`mirror`), an agent on no
live session, items whose project id or key no project has, two live projects on one page. Messages go out only with `[registry_audit] send = true` (the default is false): then, after the page agent lines, each project's -main agent (else the
page's, the hub's, the scope's general one) gets ONE message listing its problems, no fyi, kind `registry` in `messages`, at most once a calendar day: a second run on the same date sends an agent nothing that a delivered message of that date
already told it (the record's `registry.told_earlier_today` names them), and the next day it comes again until the problem is fixed. Nothing is sent when sala's session list could not be read. Not made when the record has no projects (the summary
then says nothing about it); a source it cannot read (sala, the page store, the items) skips only the checks that need it and says so in the note.

Not carried over from the agent (the agent's mode still has them): wrong-owner (the `owner check:` line it read no longer exists), page-lag and page-shape, and the timeline entry on
the project page (a script cannot call gbrain; the summary message goes to the project instead).

Stdlib plus the repo's modules. Every outside effect (the clock, the store, the model call, the messages, the page read) is a parameter of `run`, so the scenario test runs it on fixtures."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tools"))
import audit as _audit  # noqa: E402
import dated_wait as _dw  # noqa: E402
import config as _cfg  # noqa: E402
import model as _model  # noqa: E402
import states as _states  # noqa: E402
import steps as _steps  # noqa: E402
import waiting as _wt  # noqa: E402
import audit_checks as _ac  # noqa: E402
# the code checks live in audit_checks.py (the filing pass in the server calls them too); the names stay importable from here
from audit_checks import (CHECKS_CODE, FIX, _clip, _f, _hours, _item_view, _label, _no_session, _norm, _num, _stamp,  # noqa: E402,F401
                          PROOF_MAX, PATTERN_BRIEF, PATTERN_DEDUPE_DAYS, PATTERN_LOG_DAYS, PATTERN_MAX, PATTERN_WINDOW_H, check_ask_missing, check_stale, check_stuck_elsewhere, drafted_recently, field_findings,
                          goal_sig, goal_view, group_patterns, idle_pass, log_row, parse_drafts, pattern_prompt, pick_patterns, proof_wait_findings)

RUBRIC = HERE / "audit_rubric.txt"
SENDER = "stackshot audit"
UNMOVED_MIN_HOURS = 6.0       # the previous run counts as "before this one" when it started this long ago; with scheduled runs some hours apart the run before is always the previous one
ONCE = ("event-missing",)    # a finding of these categories is sent once and never repeated or escalated (the builder's message about an event no type reports)
REMIND_TRIES = 3             # a ten-minute pass sends an unanswered finding this many times (first send and reminders), then once to the builder as unmoved, then (a finding that went to a builder) once to the project's -main agent (split_sent)
TIGHTEN_SHARE = 0.20          # a run that flags more than this share of the open items trips a tightening review
FAIL_STOP = 3                 # model calls in a row that fail (no answer) end the calls of the run
MSG_MAX = 4000
# what the message tool says when a message goes to a front agent without the mark (server._gate_front)
FRONT_REFUSAL = "is a front agent of"
CHECKS_MODEL = ("next-done", "wrong-needs", "ask-missing", "unneeded-escalation", "older-than-page", "obsolete-wait", "why-not-now", "goal-unclear")
_BOARD_RX = re.compile(r"\bboard#(\d+)\b")


# ---------- small helpers ----------
def _date_of(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, _cfg.tz()).date().isoformat()


def _stamp_of(ts: float) -> str:
    """The start time as a record file name has it: 2099-03-31-050000 (the [instance] timezone)."""
    return dt.datetime.fromtimestamp(ts, _cfg.tz()).strftime("%Y-%m-%d-%H%M%S")


def run_label(t0: float, hist: list[dict[str, Any]]) -> str:
    """What a message and the summary call this run: its date, and for a run that is not the first of its date also its start time (`2099-03-04 20:00`), so two runs of one day (the timer's
    two times, or a button press and a timer run) send messages that read apart. The first run of a date is the plain date, so a once-a-day schedule shows only the date unless another run (a button press, say) happened earlier that day."""
    date = _date_of(t0)
    earlier = any(h.get("date") == date and (_audit._epoch(h.get("started")) or t0) < t0 for h in hist)
    return f"{date} {dt.datetime.fromtimestamp(t0, _cfg.tz()).strftime('%H:%M')}" if earlier else date


def by_day(hist: list[dict[str, Any]], skip_date: str) -> list[dict[str, Any]]:
    """`hist` (newest first) cut to one record a day, the newest of each, with `skip_date` left out: the tightening conditions count days (3 days running, 3 of the last 7), and two runs a
    day would otherwise count one day twice."""
    out: list[dict[str, Any]] = []
    seen = {skip_date}
    for h in hist:
        d = h.get("date")
        if d in seen:
            continue
        seen.add(d)
        out.append(h)
    return out


# ---------- the environment (everything that reads the world) ----------
class Env:
    """What `run` reads and does outside itself; each member is replaceable. `roles` → {name: {"role", "retired"}}; `fallback(project)` → the
    project's -main agent; `builder(project)` → its builder; `page_of(project)` → (Current state text, its timestamp); `runner(message)` → router.run_call's result; `deliver(to, text, fyi)` and
    `push(to, text)` → (delivered, what was said); `orphans(apply)` → the server's orphan hand-over answer; `clock()` → the time now (epoch seconds); `step_mark` and `step_move` → the two item writes of the front-step rule (the server's; none = the rule does nothing)."""

    def __init__(self, **kw: Any) -> None:
        self.roles = kw.get("roles")
        self.fallback = kw.get("fallback")
        self.builder = kw.get("builder")
        self.page_of = kw.get("page_of")
        self.runner = kw.get("runner")
        self.deliver = kw.get("deliver") or _deliver
        self.push = kw.get("push") or _audit._push
        self.clock = kw.get("clock") or time.time
        self.sessions = kw.get("sessions")          # () -> (live names, aliases) as sala lists them, or None when unreadable; None here reads sala
        self.registry = kw.get("registry")          # () -> the project pages' registry; None here reads the store's
        self.pages = kw.get("pages")                # (run stamp, deadline epoch) -> the server's answer to its page-debt pass ({"enabled", "mode", "counts"}); None here asks the server (client.page_debt)
        self.registry_check = kw.get("registry_check")   # (items, now) -> the project registry check's answer ({"checked", "note", "projects", "pages", "findings"}); None here runs tools/registry_report.py on the store
        self.orphans = kw.get("orphans")            # (apply) -> the server's answer to its orphan hand-over ({"checked", "applied", "found", "moved", "left", ...}); None here asks the server (client.orphan_handover)
        self.step_mark = kw.get("step_mark")        # (gid, step hash or None, now, mover) -> whether the item's stuck_since clock was written (None hash: dropped); the server's, None = the front-step rule does nothing (front_step.py)
        self.step_move = kw.get("step_move")        # (gid, step hash, opener, mover, hours, now) -> {"moved": bool, "why": str, "line": str}: the server rewords the step to the mover and writes the History line (front_step.py)
        self.wait_end = kw.get("wait_end")          # (gid, plan, now) -> {"fixed": bool, "what": str, "why": str}: the server sets the wait a next line names, with a History line (wait_end.py, server_fixes.py); None = the pass only asks the mover
        self.wait_facts = kw.get("wait_facts")      # () -> wait_end.Facts: the machines, the pull requests and the links the wait-end rule reads; None = the rule reads only the items themselves
        self.wake_park = kw.get("wake_park")        # (gid, now) -> {"parked": bool, "wake": str, "line": str}: the server parks a wake that is the whole of the mover's wait, with a History line (server_fixes.py); None = the pass only reports it

    def role_map(self) -> dict[str, dict[str, Any]]:
        if self.roles is None:
            try:
                import anchors as _anc  # noqa: PLC0415
                self.roles = _anc.file_roles(_anc.registry())
            except Exception:  # noqa: BLE001
                self.roles = {}
        return self.roles if isinstance(self.roles, dict) else {}

    def main_of(self, project: str) -> str:
        try:
            if self.fallback:
                return self.fallback(project) or _cfg.audit_main()
            import anchors as _anc  # noqa: PLC0415
            return _anc.fallback_main(project) or _cfg.audit_main()
        except Exception:  # noqa: BLE001
            return _cfg.audit_main()

    def builder_of(self, project: str) -> str:
        try:
            if self.builder:
                return self.builder(project) or _cfg.audit_builder()
            import router_live as _rl  # noqa: PLC0415
            return _rl.builder(project) or _cfg.audit_builder()
        except Exception:  # noqa: BLE001
            return _cfg.audit_builder()

    def page_agents(self, items: Any = None, now: float | None = None) -> dict[str, Any]:
        """The page agent lines check (tools/page_agent_report.py) on this environment's registry and sala sessions, and the run's board items (None reads the store's). A check that fails is a check not made, never the end of the run."""
        try:
            import page_agent_report as _par  # noqa: PLC0415
            return _par.read(self.registry() if self.registry else None, self.sessions, items, now)
        except Exception as e:  # noqa: BLE001
            return {"checked": False, "note": _clip(f"the check failed: {type(e).__name__}: {e}", 120), "sessions": 0, "pages": 0, "findings": []}

    def registry_problems(self, items: Any = None, now: float | None = None) -> dict[str, Any]:
        """The project registry check (tools/registry_report.py) on this environment's record, pages, sala sessions and the run's board items (None reads the store's). `registry_check` replaces it (a fixture hands in
        the answer). A check that fails is a check not made, never the end of the run."""
        try:
            if self.registry_check:
                return self.registry_check(items, now)
            import registry_report as _rr  # noqa: PLC0415
            return _rr.read(ov=self.registry() if self.registry else None, sessions=self.sessions, items=items)
        except Exception as e:  # noqa: BLE001
            return {"checked": False, "note": _clip(f"the check failed: {type(e).__name__}: {e}", 120), "projects": 0, "pages": 0, "findings": []}

    def page(self, project: str) -> tuple[str, float | None]:
        try:
            if self.page_of:
                return self.page_of(project)
            import pages as _pages  # noqa: PLC0415
            return str(_pages.current_state(project, 4000) or ""), _pages.page_ts(project)
        except Exception:  # noqa: BLE001
            return "", None


def _deliver(to: str, text: str, fyi: bool = False) -> tuple[bool, str]:
    """One message through the server with this machine's token, as a script's message (client.py)."""
    import client as _client  # noqa: PLC0415 — only a real send needs it
    status, said = _client.message(to, text, SENDER, fyi=fyi)
    return status == 200, f"[{status}] {said}"



# ---------- the judgment checks: suspects ----------
def is_waiting(item: dict[str, Any], after_open: Callable[[dict[str, Any]], Any]) -> bool:
    """A waiting item as the model reads it (held, behind an open item, parked, blocked, outside or verifying); an item that waits on the owner's decision is his move, not a wait, and neither is a relay wait (an
    outside item that waits on news only the owner relays)."""
    held = _wt.is_held(item)
    try:
        m = _model.derive(item, None, after_open)
    except Exception:  # noqa: BLE001  (a malformed item is no wait here; the field checks read it their own way)
        return held
    if m.wait is not None and m.wait.kind == "relay":
        return False
    return held or m.state == _model.WAITING


def wait_since(item: dict[str, Any], meta: dict[str, Any]) -> float:
    """When the wait began, as an epoch: the stamp of its hold or of its wait basis, else the item's last state change, else its last save."""
    for k in ("hold_set", "wait_basis"):
        v = meta.get(k)
        at = _f(v.get("at")) if isinstance(v, dict) else 0.0
        if at > 0:
            return at
    return _f(item.get("state_updated")) or _f(item.get("updated"))


def cited_ids(item: dict[str, Any], meta: dict[str, Any], description: bool = False) -> list[str]:
    """The board numbers a waiting item names in the wait's own words, in order of first mention, not its own: the wait's basis, its expected reason, next, the open steps and the items it waits after; with
    `description`, the description's too (a mention there is background unless the cited item was dropped or superseded)."""
    import board_report as _br  # noqa: PLC0415
    texts = [*_br._texts(item), *(f"board#{_num(g)}" for g in _wt.after_of(meta))] + ([str(item.get("description") or "")] if description else [])
    own = str(_num(str(item.get("id") or "")))
    out: list[str] = []
    for t in texts:
        for n in _BOARD_RX.findall(t):
            if n != own and n not in out:
                out.append(n)
    return out


def _closed_line(n: str, it: dict[str, Any]) -> str:
    m = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
    how = str(m.get("outcome") or "done")
    why = f" ({_clip(m.get('reason'), 160)})" if m.get("reason") else ""
    when = _f(it.get("state_updated")) or _f(it.get("updated"))
    return f"board#{n} is closed as {how}{why}" + (f", {_stamp(when)}" if when else "") + f": {_clip(it.get('subject'), 120)}"


def obsolete_wait_evidence(gid: str, items: dict[str, dict[str, Any]], by_num: dict[str, list[str]], env: Env,
                           pages: dict[str, tuple[str, float | None]], last: float = 0.0) -> tuple[str, list[str], str, bool]:
    """(evidence line, context lines for the call, signature, whether a cited item is closed) for a waiting item a later change may have overtaken, or ("", [], "", False). The two signals, read from fields and
    the project page with no model: an item the wait cites is closed (a closed item named in the wait's own words counts whatever its outcome; one named only in the description counts when it was dropped or
    superseded), or the project page, written after both the wait began and the item was last written, has a line that names an item the wait cites (never the item itself: a session writes its page line
    right after it parks an item). The signature is a hash of each counted closed item's number, outcome and reason and of the matched page lines, so a verdict stands until one of them changes."""
    it = items[gid]
    meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
    since = wait_since(it, meta)
    own = cited_ids(it, meta)
    closed: list[str] = []
    keys: list[str] = []
    refs: list[str] = []
    for n in cited_ids(it, meta, description=True):
        gs = by_num.get(n) or []
        if len(gs) != 1 or gs[0] == gid:
            continue
        cm = items[gs[0]].get("metadata") if isinstance(items[gs[0]].get("metadata"), dict) else {}
        if n in own:
            refs.append(f"board#{n}")
        if items[gs[0]].get("status") != "open" and (n in own or str(cm.get("outcome") or "") in ("dropped", "superseded")):
            closed.append(_closed_line(n, items[gs[0]]))
            keys.append(f"{n}:{cm.get('outcome') or 'done'}:{' '.join(str(cm.get('reason') or '').split())}")
    lines: list[str] = []
    proj = str(meta.get("project") or "")
    if proj and refs:
        if proj not in pages:
            pages[proj] = env.page(proj)
        text, pts = pages[proj]
        if text and pts and since and float(pts) > max(since, last):
            rx = re.compile("|".join(re.escape(r) + r"(?!\d)" for r in refs))
            lines = [_clip(ln, 220) for ln in text.splitlines() if rx.search(ln)][:3]
    if not closed and not lines:
        return "", [], "", False
    parts = []
    if closed:
        parts.append("an item the wait cites is closed: " + " | ".join(closed[:3]))
    if lines:
        parts.append(f"the project page ({_stamp(float(pages[proj][1]))}) is newer than the wait ({_stamp(since)}) and mentions an item it cites: " + " | ".join(lines))
    wb = meta.get("wait_basis")
    basis = " ".join(str(wb.get("text") or "").split()) if isinstance(wb, dict) else ""
    head = "; ".join(x for x in ((f"The wait began {_stamp(since)} ({_hours(max(0.0, env.clock() - since))} ago)" if since else ""), (f"basis: {_clip(basis, 200)}" if basis else ""),
                                 (f"wake {meta['wake']}" if meta.get("wake") else "")) if x)
    ctx = ([head] if head else []) + [f"- {c}" for c in closed[:5]] + [f"- page: {ln}" for ln in lines]
    sig = hashlib.sha1(("|".join(sorted(keys)) + "||" + "|".join(lines)).encode("utf-8")).hexdigest()[:12]
    return "; ".join(parts), ctx, sig, bool(closed)


PAGE_ONLY_MAX = 5          # obsolete-wait suspects per run that rest on a page line alone (no cited item is closed)
SELF_WAIT_MAX = 5          # why-not-now suspects per run (a doing item that waits for a later day on its own say-so), beside the cap of calls
GOAL_MAX = 10              # goal-unclear suspects per run (an item new or reworded since the last judgment), beside the cap of calls


def goal_evidence(item: dict[str, Any], goal_seen: dict[str, str], sid: str) -> tuple[str, str]:
    """(evidence line, stamp) for an open item whose subject and `Goal:` bullet have not been judged yet (its (subject, goal) stamp is not the one kept for it in `goal_seen`), or ("", ""): an item with no Goal bullet (filed before the
    form, or by a script) is the one-time pass's business (tools/goal_pass.py), not this check's, and a pair already judged stays judged until the item's subject or Goal sentence changes, whatever else is written to the item."""
    view = goal_view(item)
    if view is None:
        return "", ""
    subject, goal = view
    sig = goal_sig(subject, goal)
    if goal_seen.get(sid) == sig:
        return "", ""
    return f"the subject and the Goal bullet are new or reworded since the last judgment: subject: {_clip(subject, 120)} | Goal: {_clip(goal, 200)}", sig


def dated_wait_evidence(item: dict[str, Any], now: float, after_open: Any = None) -> tuple[str, list[str], str]:
    """(evidence line, context lines for the call, signature) for a doing item (stored, or read as doing from its fields) that is only waiting for a later day (dated_wait.py: its wake is more than an hour out and every open
    step is dated for that day or later), or ("", [], ""): not one whose still-future wake states its reason (dated_wait.basis_wait; `after_open` as model.derive takes it), which the board lists as waiting by that reason and the audit leaves alone. The signature is the dated lines plus the wake: the verdict stands until the lines or the time change."""
    dw = _dw.of(item, now)
    if dw is None or _dw.basis_wait(item, now, after_open) is not None:
        return "", [], ""
    lines = [_clip(ln, 160) for ln, _, _ in dw.steps][:4]
    what = dw.source.replace("_", " ")
    line = f"read as doing, but its {what} {dw.at} is {_hours(dw.until - now)} away and every open step is dated for later, so the board shows it as waiting: " + " | ".join(lines)
    ctx = [f"The item is read as doing (work in hand) with its {what} at {dw.at}, {_hours(dw.until - now)} from now; every open step is dated for that day or later:"] + [f"- {ln}" for ln in lines]
    return line, ctx, _dw.signature(dw)


def suspects(items: dict[str, dict[str, Any]], now: float, env: Env, judged: dict[str, Any] | None = None, live: set[str] | None = None,
             goal_seen: dict[str, str] | None = None) -> tuple[list[dict[str, Any]], int]:
    """(suspects, how many were skipped as unchanged since a verdict): the open items a cheap heuristic picks for one or more judgment checks, each {id, gid, project, checks, evidence: {check: line}, write,
    priority, sig, context}, strongest first, then by item number. A held item is checked for next-done and, like every waiting item, for obsolete-wait (obsolete_wait_evidence: a cited item is closed, or the
    project page, newer than the wait, names one it cites); the evidence's signature `sig` is kept with the verdict, so the item is judged again only when that evidence changes. A suspect for obsolete-wait
    alone ranks after every other check (priority 3), and at most PAGE_ONLY_MAX suspects a run rest on a page line alone. `live`, when given, is filled with the shown ids whose obsolete-wait evidence stands now,
    judged before or not (`carried` drops a "yes" whose item is not in it). A stored doing item the board shows as waiting because only a later day holds it (dated_wait.py) is a suspect for
    why-not-now (dated_wait_evidence), ranked with obsolete-wait alone (priority 3); at most SELF_WAIT_MAX such suspects a run, and its signature is the dated lines plus the wake. An open item whose description opens with a
    Goal bullet is a suspect for goal-unclear (goal_evidence) when its (subject, Goal sentence) pair is not the one `goal_seen` ({shown id: stamp}, kept on the record) holds for it, held or not and whatever else is written to
    the item; it ranks with the other priority-3 checks, at most GOAL_MAX a run, and the pair's stamp `gsig` goes with the suspect."""
    import board_report as _br  # noqa: PLC0415
    import next_report as _nr  # noqa: PLC0415
    judged = judged or {}
    by_num: dict[str, list[str]] = {}
    for g in items:
        by_num.setdefault(str(_num(g)), []).append(g)
    pages: dict[str, tuple[str, float | None]] = {}
    out: list[dict[str, Any]] = []
    skipped = 0
    page_only = 0
    self_wait = 0
    goal_n = 0
    goal_seen = goal_seen or {}

    def after_open(x: dict[str, Any]) -> list[str]:
        return [g for g in _wt.after_of(x.get("metadata") or {}) if (items.get(g) or {}).get("status") == "open"]
    for gid in sorted(items, key=_num):
        it = items[gid]
        if it.get("status") != "open":
            continue
        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        sid = _nr.shown(gid)
        last = _br._last_write(it)
        held = _wt.is_held(it)
        ev: dict[str, str] = {}
        for s in _steps.view(meta, keeper=str(meta.get("owner") or "")):
            if s["status"] != _steps.OPEN:
                continue
            for n in _BOARD_RX.findall(_steps.first_line(s["text"])):
                gs = by_num.get(n) or []
                if len(gs) == 1 and gs[0] != gid and items[gs[0]].get("status") == "completed":
                    ev.setdefault("next-done", f"open step cites board#{n}, which is closed: {_clip(_steps.first_line(s['text']), 120)}")
        kinds = [k.lower() for k in _states.kinds_of(meta)]
        ask = " ".join(str(meta.get("ask") or "").split())
        if not held:
            if "decision" in kinds and ask:
                ev["unneeded-escalation"] = f"waits on {_cfg.owner()} with the ask: {_clip(ask, 140)}"
                ev["ask-missing"] = "the ask may no longer fit the item"
                his = [s for s in _steps.view(meta, keeper=str(meta.get("owner") or "")) if s["status"] == _steps.OPEN and _steps.is_his(s["text"], unnamed_is_his=False)]
                if not his:
                    ev["wrong-needs"] = f"needs a decision, but no open step is {_cfg.owner()}'s"
            elif ask and "decision" not in kinds:
                ev["wrong-needs"] = f"carries an ask but needs lacks decision: {_clip(ask, 120)}"
                ev["ask-missing"] = "an ask with no needs: decision"
            proj = str(meta.get("project") or "")
            if proj and last:
                if proj not in pages:
                    pages[proj] = env.page(proj)
                text, pts = pages[proj]
                if text and pts and float(pts) > last and sid in text:
                    lines = [_clip(ln, 220) for ln in text.splitlines() if sid in ln][:3]
                    ev["older-than-page"] = f"the project page ({_stamp(float(pts))}) is newer than the item's last write ({_stamp(last)}) and mentions {sid}: " + " | ".join(lines)
        sig, ctx, has_closed = "", [], False
        if is_waiting(it, after_open):
            line, ctx, sig, has_closed = obsolete_wait_evidence(gid, items, by_num, env, pages, last)
            if line:
                ev["obsolete-wait"] = line
                if live is not None:
                    live.add(sid)
        else:
            wline, wctx, wsig = dated_wait_evidence(it, now, after_open)       # a doing item that waits for a later day: why not now?
            if wline:
                ev["why-not-now"], ctx, sig = wline, wctx, wsig
                if live is not None:
                    live.add(sid)
        gline, gsig = goal_evidence(it, goal_seen, sid)
        if gline:
            ev["goal-unclear"] = gline
        if not ev:
            continue
        checks = [c for c in CHECKS_MODEL if c in ev]
        prev = judged.get(sid)
        if (isinstance(prev, dict) and _f(prev.get("write")) >= last and sorted(prev.get("checks") or []) == sorted(checks) and prev.get("verdict") in ("no", "yes")
                and str(prev.get("sig") or "") == sig and str(prev.get("gsig") or "") == (gsig if "goal-unclear" in ev else "")):
            skipped += 1
            continue
        if "goal-unclear" in ev:
            if goal_n >= GOAL_MAX:
                del ev["goal-unclear"]
                gsig = ""
                if not ev:
                    continue
                checks = [c for c in CHECKS_MODEL if c in ev]
            else:
                goal_n += 1
        if "obsolete-wait" in ev and not has_closed:
            if page_only >= PAGE_ONLY_MAX:
                del ev["obsolete-wait"]
                sig, ctx = "", []
                if not ev:
                    continue
                checks = [c for c in CHECKS_MODEL if c in ev]
            else:
                page_only += 1
        if "why-not-now" in ev:
            if self_wait >= SELF_WAIT_MAX:
                del ev["why-not-now"]
                sig, ctx = "", []
                if not ev:
                    continue
                checks = [c for c in CHECKS_MODEL if c in ev]
            else:
                self_wait += 1
        prio = 0 if "next-done" in ev else (1 if "unneeded-escalation" in ev or "wrong-needs" in ev else (3 if set(ev) <= {"obsolete-wait", "why-not-now", "goal-unclear"} else 2))
        out.append({"id": sid, "gid": gid, "project": str(meta.get("project") or ""), "checks": checks, "evidence": ev, "write": last, "priority": prio, "sig": sig, "context": ctx,
                    **({"gsig": gsig} if "goal-unclear" in ev else {})})
    out.sort(key=lambda x: (x["priority"], _num(x["gid"])))
    return out, skipped


def prompt(item: dict[str, Any], sus: dict[str, Any], mover: str, now: float) -> str:
    """The message of one call: the item's facts and the candidate checks with their evidence. The rubric is the system prompt."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    last = sus["write"]
    lines = [f"Item {sus['id']}: {_clip(item.get('subject'), 160)}",
             f"Project: {meta.get('project') or '-'}",
             f"State: {meta.get('state') or '-'} · needs: {', '.join(_wt.needs_of(meta)) or '-'} · mover: {mover or '-'}",
             f"Ask: {_clip(meta.get('ask'), 300) or '(none)'}",
             f"Last write: {_stamp(last) if last else 'unknown'}" + (f" ({_hours(now - last)} ago)" if last else ""),
             f"Description: {_clip(item.get('description'), 700) or '(none)'}", "Steps:"]
    view = _steps.view(meta, keeper=str(meta.get("owner") or ""))
    for s in view[-14:]:
        lines.append(f"- [{s['status']}] {_clip(_steps.first_line(s['text']), 220)}")
    if not view:
        lines.append("- (none)")
    lines.append("")
    lines.append("Candidate checks (answer under one of these):")
    for c in sus["checks"]:
        lines.append(f"- {c}: {sus['evidence'][c]}")
    if sus.get("context"):
        lines += ["", f"The wait (for {' and '.join(c for c in ('obsolete-wait', 'why-not-now') if c in sus['checks'])}):", *sus["context"]]
    return "\n".join(lines)


def judge(items: dict[str, dict[str, Any]], picked: list[dict[str, Any]], now: float, env: Env, rubric: str, t0: float | None = None) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """One call per suspect, in order, one at a time. No new call is begun once `[audit] max_minutes` have passed since the run started (`t0`, default `now`; the clock is `env.clock`): the suspects left wait
    for the next run. → (findings, judged entries for the record, the call counts: made, failed, timed_out, notes)."""
    import board_report as _br  # noqa: PLC0415
    import cold_call as _cc  # noqa: PLC0415
    model = _cfg.audit_model()
    lane = _cfg.audit_lane()
    runner = env.runner
    if runner is None:
        def runner(message: str) -> dict[str, Any]:      # noqa: F811 — the router's call, on the [router] command (and on [audit] lane when it names one), with this call's model when [audit] model names one
            import router as _router  # noqa: PLC0415
            return _router.run_call(message, rubric, model_name=model or None, lane=lane or None)
    found: list[dict[str, Any]] = []
    entries: dict[str, Any] = {}
    n_calls = n_fail = streak = 0
    notes: list[str] = []
    limit = _cfg.audit_max_minutes() * 60
    start = now if t0 is None else t0
    timed_out = False
    for i, sus in enumerate(picked):
        if env.clock() - start >= limit:
            timed_out = True
            notes.append(f"{_cfg.audit_max_minutes()} minutes passed since the run started: {len(picked) - i} suspect(s) wait for the next run")
            break
        it = items[sus["gid"]]
        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}

        def after_open(x: dict[str, Any]) -> list[str]:
            return [g for g in _wt.after_of(x.get("metadata") or {}) if (items.get(g) or {}).get("status") == "open"]
        mover = _br.mover_of(it, after_open)
        n_calls += 1
        status, ans, note, _raw = _cc.run_with(prompt(it, sus, mover, now), rubric, lambda t: _cc.parse_object(t, "finding", ("yes", "no")), runner)
        if status != "ok" or ans is None:
            n_fail += 1
            streak += 1
            notes.append(f"{sus['id']}: {note}")
            if streak >= FAIL_STOP:
                notes.append(f"{FAIL_STOP} calls in a row failed: the rest of the suspects wait for the next run")
                break
            continue
        streak = 0
        check = str(ans.get("check") or "").strip().lower()
        yes = ans["finding"] == "yes" and check in sus["checks"]
        entry = {"verdict": "yes" if yes else "no", "write": sus["write"], "checks": sus["checks"], "at": now, **({"sig": sus["sig"]} if sus.get("sig") else {}),
                 **({"gsig": sus["gsig"]} if sus.get("gsig") else {})}
        if sus["checks"] == ["goal-unclear"]:
            entry["reason"] = _clip(ans.get("reason"), 240)       # a "no" keeps its reason too: the one-time pass (tools/goal_pass.py) prints it
        if yes:
            reason, fix = _clip(ans.get("reason"), 240), _clip(ans.get("fix"), 200) or FIX.get(check, "")
            if check == "goal-unclear":
                fix = FIX[check]                     # the fix is the one the check teaches, not the model's rewording of it
            entry.update(check=check, reason=reason, fix=fix)
            found.append({"id": sus["id"], "project": sus["project"], "owner": mover, "mover": mover, "category": check, "detail": reason, "fix": fix, "source": "model"})
        entries[sus["id"]] = entry
    return found, entries, {"made": n_calls, "failed": n_fail, "timed_out": timed_out, "notes": notes[:10]}


def carried(prev_judged: dict[str, Any], items: dict[str, dict[str, Any]], picked_ids: set[str], by_shown: dict[str, str], live: set[str] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The previous record's `judged` entries that still hold: the item is open and was not judged again this run. → (entries to keep, the findings of its unchanged "yes" verdicts). With `live` (see `suspects`),
    an obsolete-wait or why-not-now verdict whose item no longer has that evidence (a cited item reopened, a page line gone) is dropped, so its finding is not sent again."""
    import board_report as _br  # noqa: PLC0415
    keep: dict[str, Any] = {}
    again: list[dict[str, Any]] = []
    for sid, e in (prev_judged or {}).items():
        gid = by_shown.get(sid)
        if not gid or items[gid].get("status") != "open" or sid in picked_ids or not isinstance(e, dict):
            continue
        it = items[gid]
        if _br._last_write(it) > _f(e.get("write")):
            continue                                    # written since: the old verdict says nothing; it is judged again when a heuristic picks it
        if live is not None and e.get("check") in ("obsolete-wait", "why-not-now") and sid not in live:
            continue                                    # the wait's evidence is gone: the old "yes" is stale
        keep[sid] = e
        if e.get("verdict") == "yes" and e.get("check"):
            meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}

            def after_open(x: dict[str, Any]) -> list[str]:
                return [g for g in _wt.after_of(x.get("metadata") or {}) if (items.get(g) or {}).get("status") == "open"]
            mover = _br.mover_of(it, after_open)
            again.append({"id": sid, "project": str(meta.get("project") or ""), "owner": mover, "mover": mover, "category": e["check"], "detail": str(e.get("reason") or ""), "fix": str(e.get("fix") or ""), "source": "model"})
    return keep, again


# ---------- reporting ----------
FRONT_ROLES = ("front", "keeper")     # anchors.session_roles: a user-facing agent, and a page's name-line session (the one the owner talks to)


def _norm_name(v: Any) -> str:
    return re.sub(r"\s*\(.*\)$", "", str(v or "")).strip().lower()


def page_key(project: str) -> str:
    """The page key a project's name stands for: `projects/<slug>`, which the router handles."""
    p = str(project or "").strip()
    return p if "/" in p else f"projects/{p}"


def recipient(who: str, project: str, env: Env, mover: str = "") -> tuple[str, bool]:
    """(where a finding for `who` goes, whether the message is marked `[for <owner>]`). A finding reaches a session directly only when that session is a background agent (or a name the role map does not
    know, which the message tool accepts or refuses and `_run` handles). It never goes straight to a front agent, a retired session, an outside party or nobody: those go to the project's page key
    (`projects/<slug>`, unmarked), where the router passes them on. The one marked path kept is the owner's own: a finding on an item that is his move (`who` is the owner and so is the item's `mover`) goes
    to the project's -main agent with `[for <owner>]` first, as before. A finding addressed to the owner on an item another session moves (stuck-elsewhere: the first open step is his, the mover is not)
    is no decision for him and follows the mover's rule. A finding with no project has no page key: the -main agent, marked, as before."""
    w = str(who or "").strip()
    if _model.is_owner(w):
        m = str(mover or "").strip()
        if _no_session(m) and not _model.is_owner(m):          # no mover, "-" and an outside party read alike
            m = ""
        if not m or _model.is_owner(m):
            return env.main_of(project), True
        w = m
    r = env.role_map().get(w) or {}
    if not _no_session(w) and not r.get("retired") and r.get("role") not in FRONT_ROLES:
        return w, False
    if not str(project or "").strip():
        return env.main_of(project), True
    return page_key(project), False


def finding_key(f: dict[str, Any]) -> tuple[str, str, str]:
    """What makes two findings the same finding: the item, the check and, for the two reports whose category holds several checks (`next rules`: the rule, `board checks`: the kind), which one."""
    cat = str(f.get("category") or "")
    sub = str(f.get("detail") or "").split(":", 1)[0].strip() if cat in ("next rules", "board checks") else ""
    return str(f.get("id") or ""), cat, sub


def written_since_run(last: float, started: float | None, sending_from: float | None, end: float | None) -> bool:
    """Was the item written after a run read it, as a real write? A run reads the board at `started`, judges, then sends from `sending_from` to `end`. A write after `end` counts; so does one after `started` and
    at or before `sending_from` (the run read the item before it, and nothing the run did made it). A write between `sending_from` and `end` is the run's own deliveries (a message that names an item may write it)
    and is ignored. A run with no `sending_from` (a record from before it was kept) has no such window: a write counts only after `end`, as it did."""
    if end is not None and last > end:
        return True
    return sending_from is not None and started is not None and started < last <= sending_from


def sent_before(rec: dict[str, Any] | None) -> dict[tuple[str, str, str], tuple[float, float | None, float | None]]:
    """{finding key: (when it was sent, the run's `sending_from`, the run's start)} from a finished run record: the stamps each finding carries (a finding whose message reached no one has none). A record from
    before the stamp existed (no `repeats` key) counts its findings as sent when the run started; one from before `sending_from` was kept has no window."""
    out: dict[tuple[str, str, str], tuple[float, float | None, float | None]] = {}
    if not rec:
        return out
    started = _audit._epoch(rec.get("started")) or 0.0
    legacy = "repeats" not in rec
    num = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    for f in rec.get("findings") or []:
        if not isinstance(f, dict):
            continue
        ts = num(f.get("sent"))
        ts = ts if ts is not None else (started if legacy else 0.0)
        if ts > 0:
            out[finding_key(f)] = (ts, num(f.get("sending_from")), num(f.get("run_started")))
    return out


_TRY = ("", "", "second try", "third try", "fourth try", "fifth try")


def line_of(f: dict[str, Any]) -> str:
    """One finding as a message line. A later try carries its ordinal in words ("second try, no answer"): the router drops a message that repeats an earlier one but for numbers and dates, and a reminder must not be dropped as one."""
    n = f.get("tries")
    t = (_TRY[n] if isinstance(n, int) and n < len(_TRY) else "a later try") if isinstance(n, int) and n > 1 else ""
    return f"{f['id']} · {f['category']} · " + (f"{t}, no answer · " if t else "") + f"{_clip(f['detail'], 260)} · {_clip(f.get('fix'), 160)}"


def compose(lines: list[str], head: str, front: bool) -> str:
    out = ([(f"[for {_cfg.owner()}]")] if front else []) + [head] + lines
    text = "\n".join(out)
    if len(text) <= MSG_MAX:
        return text
    keep = list(lines)
    while keep and len("\n".join([*([(f"[for {_cfg.owner()}]")] if front else []), head, *keep, f"… and {len(lines) - len(keep)} more"])) > MSG_MAX:
        keep.pop()
    return "\n".join([*([(f"[for {_cfg.owner()}]")] if front else []), head, *keep, f"… and {len(lines) - len(keep)} more"])


def counts(findings: list[dict[str, Any]], passes: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    by_cat: dict[str, int] = {}
    by_ses: dict[str, int] = {}
    for f in findings:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
        w = f.get("to") or f.get("mover") or "-"
        by_ses[w] = by_ses.get(w, 0) + 1
    if passes:
        by_cat["idle-pass"] = len(passes)
    return by_cat, by_ses


def _top(d: dict[str, int], skip: tuple[str, ...] = ()) -> str:
    d = {k: v for k, v in d.items() if k not in skip and v > 0}
    return max(sorted(d), key=lambda k: d[k]) if d else ""


def tightening(open_n: int, findings: list[dict[str, Any]], by_cat: dict[str, int], by_ses: dict[str, int], history: list[dict[str, Any]]) -> list[str]:
    """The tightening conditions this run trips (the agent's brief): more than 20% of the open items flagged; the session with most findings also on top in 2 of the 6 runs before (3 of the last 7);
    the category with most findings also on top in each of the 2 runs before (3 days running)."""
    out: list[str] = []
    flagged = {f["id"] for f in findings}
    if open_n and len(flagged) / open_n > TIGHTEN_SHARE:
        out.append(f"{len(flagged)} of {open_n} open items flagged ({len(flagged) / open_n:.0%}, more than {TIGHTEN_SHARE:.0%})")
    ts = _top({k: v for k, v in by_ses.items() if k != "-"})
    if ts and sum(1 for h in history[:6] if _top({k: v for k, v in (h.get("by_session") or {}).items() if k != "-"}) == ts) >= 2:
        out.append(f"{ts} has the most findings on 3 of the last 7 days")
    tc = _top(by_cat, ("idle-pass",))
    if tc and len(history) >= 2 and all(_top(h.get("by_category") or {}, ("idle-pass",)) == tc for h in history[:2]):
        out.append(f"{tc} is the top category 3 days running")
    return out


def threshold_message(findings: list[dict[str, Any]], trips: list[str], run_date: str) -> str:
    thr = _cfg.audit_threshold()
    by: dict[str, list[str]] = {}
    for f in findings:
        by.setdefault(f["category"], []).append(f["id"])
    lines = [f"[stackshot] Board audit {run_date} tripped a threshold: a tightening review or a mechanism fix is wanted."]
    for c in sorted(by, key=lambda k: -len(by[k])):
        if len(by[c]) >= thr:
            lines.append(f"- {c}: {len(by[c])} findings (threshold {thr}): {', '.join(sorted(dict.fromkeys(by[c]), key=lambda i: _num(i)))}")
    lines += [f"- {t}" for t in trips]
    return "\n".join(lines)[:MSG_MAX]


def par_line(f: dict[str, Any]) -> str:
    return f"{f['page']} · {f['line']} · {f['name']} · {_clip(f.get('fix'), 320)}"


def par_target(f: dict[str, Any], env: Env) -> tuple[str, bool]:
    """(the agent a page agent line goes to, whether its message is marked `[for <owner>]`). `tools/page_agent_report.py` names only an agent that sala knows; when it names none (the page's own -main agent and the
    fallbacks are all gone) the line goes straight to the audit's -main agent, marked like any front recipient: not through `env.main_of`, which walks the same candidates without asking sala and can answer the gone name,
    and a message to a gone name queues silently."""
    to = str(f.get("to") or "").strip()
    if to and not (env.role_map().get(to) or {}).get("retired"):
        return to, (env.role_map().get(to) or {}).get("role") == "front"
    return _cfg.audit_main(), True


def page_agent_groups(res: dict[str, Any], env: Env) -> dict[str, dict[str, Any]]:
    """The page agent lines by the agent they go to: {to: {"front", "lines", "pages"}}. A page whose own -main agent and fallbacks are none that sala knows goes to the audit's -main agent (`par_target`)."""
    groups: dict[str, dict[str, Any]] = {}
    for f in res.get("findings") or []:
        to, front = par_target(f, env)
        g = groups.setdefault(to, {"front": front, "lines": [], "pages": set(), "gaps": 0})
        g["lines"].append(par_line(f))
        g["gaps"] += f.get("line") in ("no agents map", "no front agent", "other project's session", "session off the map")      # a project with items and no agent, or a session its map has no line for (tools/page_agent_report.py `agentless`, `offmap`), not a name sala has lost
        g["pages"].add(f["page"])
    return groups


# ---------- the run ----------
def _record_path(t0: float) -> Path:
    """The record of the run that started at `t0`: run-<date>-<HHMMSS>.json, so a second run the same day does not overwrite the first."""
    return _audit.state_dir() / f"run-{_stamp_of(t0)}.json"


def write_record(rec: dict[str, Any], t0: float) -> None:
    """Atomic: a reader never sees half a record."""
    p = _record_path(t0)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def start_record(now: float) -> dict[str, Any]:
    """The record of a run in progress (`finished` null): what the board's status reads, and what holds a second cue back (409)."""
    rec = {"started": now, "finished": None, "items_read": 0, "findings": [], "by_session": {}, "by_category": {}, "mode": "script"}
    write_record(rec, now)
    return rec


def deliver_findings(env: Env, fresh: list[dict[str, Any]], label: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    """Send `fresh` findings, one message per recipient (a finding goes to its mover, or the project's -main agent / page key as `recipient` says; a mover that cannot be reached falls back to the
    project's -main agent). `label` opens each message head ("Board audit 2099-03-03"). → (what was sent, the findings that reached someone, `sending_from`: the time just before the first send).
    `sending_from` is the time a write the caller did not make is told apart from the deliveries' own: a message that names an item may write it."""
    sent: list[dict[str, Any]] = []
    sending_from = env.clock()
    reached_fs: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    esc: dict[str, list[tuple[dict[str, Any], str]]] = {}
    up: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for f in [f for f in fresh if f.get("escalate") == 2]:       # still unanswered after the builder was told: the project's -main agent hears of a finding that went to a builder, once (marked for the owner, as every message to it)
        proj = str(f.get("project") or "")
        to0, front0 = recipient(f.get("to") or f.get("mover") or "", proj, env, f.get("mover") or "")
        main = env.main_of(proj)
        if front0 or not to0 or to0 == page_key(proj) or not main or _norm_name(to0) == _norm_name(main):
            f["lvl"] = 2
            reached_fs.append(f)       # its first recipient was not a builder (a front agent's or a retired mover's finding went to the builder at level 1, by design, and ends there), or -main is the builder: nobody is left to tell, the finding goes quiet
            continue
        up.setdefault(main, []).append((f, f"{f['id']} · nobody answered after {f.get('tries', 1) - 1} messages · {f['category']} · {_clip(f['detail'], 200)} · {f.get('mover') or 'its mover'} writes it, or says what holds it"))
    for to, ls in sorted(up.items()):
        ok, said = _send(env, to, compose([ln for _f, ln in ls], f"[stackshot] {label}: {len(ls)} finding(s) nobody answered, its builder after the reminders included; please look at them or pass them on.", True))
        sent.append({"to": to, "lines": len(ls), "delivered": ok, "said": _clip(said, 120), "kind": "unanswered"})
        if ok:
            for f, _ln in ls: f["lvl"] = 2
            reached_fs += [f for f, _ln in ls]
    for f in [f for f in fresh if f.get("escalate") == 1]:       # a finding that stayed unanswered through its reminders goes to the project's builder, as the daily run's unmoved flag does, and to no one else
        proj = str(f.get("project") or "")
        b = env.builder_of(proj)
        if proj and _norm_name(b) in {_norm_name(f.get("mover")), _norm_name(recipient(f.get("to") or f.get("mover") or "", proj, env, f.get("mover") or "")[0])}:
            b = page_key(proj)       # the builder is the one that did not answer: the page key, where the router rules it, never the mover itself
        elif not proj and not b:
            continue
        esc.setdefault(b, []).append((f, f"{f['id']} · unmoved after {f.get('tries', 1) - 1} messages · {f['category']} · {_clip(f['detail'], 200)} · {f.get('mover') or 'its mover'} writes it, or says what holds it"))
    fresh = [f for f in fresh if not f.get("escalate")]
    for to, ls in sorted(esc.items()):
        ok, said = _send(env, to, compose([ln for _f, ln in ls], f"[stackshot] {label}: {len(ls)} finding(s) its mover did not answer after repeated messages; chase the mover (job).", False))
        sent.append({"to": to, "lines": len(ls), "delivered": ok, "said": _clip(said, 120), "kind": "unmoved"})
        if ok:
            for f, _ln in ls: f["lvl"] = 1       # kept on the record: only a builder send made with the level kept is followed by the message to -main (split_sent)
            reached_fs += [f for f, _ln in ls]
    for f in fresh:
        to, front = recipient(f.get("to") or f.get("mover") or "", f["project"], env, f.get("mover") or "")
        g = groups.setdefault(to, {"front": front, "lines": [], "by": [], "fs": []})
        g["lines"].append(line_of(f))
        g["by"].append((f["project"], line_of(f)))
        g["fs"].append(f)
    for to, g in sorted(groups.items()):
        text = compose(g["lines"], f"[stackshot] {label}: {len(g['lines'])} item(s) for you (id · check · evidence · what fixes it).", g["front"])
        ok, said = _send(env, to, text)
        sent.append({"to": to, "lines": len(g["lines"]), "delivered": ok, "said": _clip(said, 120)})
        reached = ok
        if not ok:
            # the mover could not be reached: its findings go to the project's -main agent, one message per -main, noted next to the failed one.
            # A refusal because the recipient is a front agent (a session id the role map did not know as one) is no unreachable mover: the lines go to the project's
            # page key, where the router hands them to the builder or rules them, with no [for <owner>] mark
            refused = FRONT_REFUSAL in said
            fb: dict[str, list[str]] = {}
            direct: dict[str, list[str]] = {}
            for proj, ln in g["by"]:
                if refused and proj:
                    direct.setdefault(page_key(proj), []).append(ln)
                    continue
                m = env.main_of(proj)
                if m and m != to:
                    fb.setdefault(m, []).append(ln)
            for pk, ls in sorted(direct.items()):
                ok2, said2 = _send(env, pk, compose(ls, f"[stackshot] {label}: {len(ls)} item(s) for {to}, a front agent of this project that takes no unmarked message; please pass them to whoever moves them (id · check · evidence · what fixes it).", False))
                sent.append({"to": pk, "lines": len(ls), "delivered": ok2, "said": _clip(said2, 120), "kind": "project", "for": to})
                reached = reached or ok2
            for m, ls in sorted(fb.items()):
                ok2, said2 = _send(env, m, compose(ls, f"[stackshot] {label}: {len(ls)} item(s) for {to}, whose session could not be reached ({_clip(said, 80)}); please pass them on (id · check · evidence · what fixes it).", True))
                sent.append({"to": m, "lines": len(ls), "delivered": ok2, "said": _clip(said2, 120), "kind": "fallback", "for": to})
                reached = reached or ok2
        if reached:
            reached_fs += g["fs"]
    return sent, reached_fs, sending_from


PAGE_RESULT_FAILED = ("error", "fallback", "would_fall_back")      # no edit came of the call: it raised, or its answer could not be applied (live: the debt went to an agent; shadow: it would have); proposed / applied are edits, "skipped" (a second brain's page that could not be read) is neither
PAGES_GRACE_S = 300.0         # after the stage's deadline, the page call already begun may finish (it is limited by [router] timeout_seconds, and the page write)


def _pages_ask(run: str, deadline: float) -> dict[str, Any]:
    """The default `Env.pages`: the server makes the pass (it holds the debt ledger and the page writes) and answers when its calls are done."""
    import client as _client  # noqa: PLC0415 — only a real run needs it
    status, d = _client.page_debt(run, deadline, timeout=max(60.0, deadline - time.time() + PAGES_GRACE_S))
    if status != 200:
        raise RuntimeError(f"[{status}] {_clip(d.get('error') or d, 160)}")
    return d


def pages_stage(env: Env, t0: float) -> dict[str, Any]:
    """The pages stage, beside the judgment checks and under the same time limit: the page-debt call (one model call per page with page updates that moved to its keeper;
    the server makes it, `Env.pages`) is made once per run, for the pages that the last runs left. No page is begun once `[audit] max_minutes` have passed since the run started
    (`timed_out`; the pages left wait for the next run). A page whose call fails does not stop the others, and a stage that fails altogether (the server not reached, an error answer)
    does not stop the run: it is counted in `failed` and said in `note`. → {"enabled": None while unknown, "mode", "called", "left", "results", "failed", "timed_out", "note"}."""
    out: dict[str, Any] = {"enabled": None, "mode": "", "called": 0, "left": 0, "results": {}, "failed": 0, "timed_out": False, "note": ""}
    deadline = t0 + _cfg.audit_max_minutes() * 60
    if env.clock() >= deadline:
        out.update(timed_out=True, note=f"{_cfg.audit_max_minutes()} minutes passed since the run started: the page calls wait for the next run")
        return out
    try:
        ans = (env.pages or _pages_ask)(_stamp_of(t0), deadline)
    except Exception as e:  # noqa: BLE001
        out.update(failed=1, note=_clip(f"the pages stage failed: {type(e).__name__}: {e}", 200))
        print(f"audit run: {out['note']}", file=sys.stderr, flush=True)
        return out
    counts = ans.get("counts") if isinstance(ans, dict) and isinstance(ans.get("counts"), dict) else {}
    results = {k: int(v) for k, v in counts.items() if k not in ("pages", "left") and isinstance(v, int) and not isinstance(v, bool)}
    out.update(enabled=bool(ans.get("enabled")) if isinstance(ans, dict) else False, mode=str(ans.get("mode") or "") if isinstance(ans, dict) else "",
               called=int(counts.get("pages") or 0), left=int(counts.get("left") or 0), results=results,
               failed=sum(results.get(k, 0) for k in PAGE_RESULT_FAILED))
    if out["left"]:
        out.update(timed_out=True, note=f"{_cfg.audit_max_minutes()} minutes passed since the run started: {out['left']} page(s) wait for the next run")
    return out


LEFT_SHOWN = 20          # the proof-waits stage's left-alone items kept on the record (the count is whole)


def proof_stage(items: dict[str, dict[str, Any]], anchors: dict[str, Any], now: float, env: Env) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The proof-waits stage, after the model checks and before the pages stage: the code rule `audit_checks.proof_wait_findings` over the open items (an item held for a real event closes when the fix is tested and
    live, else its mover stages the event now; a wait that cannot be staged keeps its basis named and is left alone). No model call and no write: the findings are sent like any other (to the mover, once per unchanged
    item, by `deliver_findings`), and nothing is closed. A stage that fails is a stage not made (said in `note`), never the end of the run; one item that cannot be read is skipped and counted in `skipped`. → (findings,
    {"read", "found", "left": [{id, basis}], "left_n", "skipped", "capped", "failed", "note"}); `capped` is filled by the run when more fresh findings than PROOF_MAX came up."""
    info: dict[str, Any] = {"read": 0, "found": 0, "left": [], "left_n": 0, "skipped": 0, "capped": 0, "failed": 0, "note": ""}
    try:
        found, left, read, skipped = proof_wait_findings(items, anchors, now, env)
    except Exception as e:  # noqa: BLE001
        info.update(failed=1, note=_clip(f"the proof-waits stage failed: {type(e).__name__}: {e}", 200))
        print(f"audit run: {info['note']}", file=sys.stderr, flush=True)
        return [], info
    info.update(read=read, found=len(found), left=[{"id": x["id"], "basis": x["basis"]} for x in left[:LEFT_SHOWN]], left_n=len(left), skipped=skipped)
    return found, info


def proof_text(pw: dict[str, Any]) -> str:
    """The proof-waits stage as the summary line has it ('' when it found and left nothing and did not fail)."""
    if pw.get("failed"):
        return f" · proof waits: {pw['note']}"
    if not pw.get("found") and not pw.get("left_n") and not pw.get("skipped"):
        return ""
    return f" · proof waits: {pw['found']} found" + (f" ({pw['capped']} over the cap of {PROOF_MAX}, left for the next run)" if pw.get("capped") else "") + (f", {pw['left_n']} left alone with their basis" if pw.get("left_n") else "") + (f", {pw['skipped']} unreadable item(s) skipped" if pw.get("skipped") else "")


def pages_text(pg: dict[str, Any]) -> str:
    """The pages stage as the summary line has it ('' when the page call is switched off)."""
    if pg.get("enabled") is False:
        return ""
    if pg.get("enabled") is None:
        return f" · pages: {pg['note']}" if pg.get("note") else ""
    detail = ", ".join(f"{n} {k}" for k, n in sorted(pg["results"].items()))
    return f" · pages ({pg['mode']}): {pg['called']} called" + (f" ({detail})" if detail else "") + (f", {pg['failed']} without an edit" if pg["failed"] else "") + (f", {pg['left']} left for the next run" if pg["left"] else "")


# ---------- the orphan hand-over (the first stage of a run) ----------
ORPHAN_SHOWN = 20          # moved and left-over items kept on the record and in the summary message (the counts are whole)


def _orphans_ask(apply: bool) -> dict[str, Any]:
    """The default `Env.orphans`: the server makes the check and the hand-over (it holds the item lock and the fleet's heartbeat) and answers with what it found."""
    import client as _client  # noqa: PLC0415 — only a real run needs it
    status, d = _client.orphan_handover(apply)
    if status != 200:
        raise RuntimeError(f"[{status}] {_clip(d.get('error') or d, 160)}")
    return d


def orphan_stage(env: Env, apply: bool) -> dict[str, Any]:
    """The orphan hand-over, the first stage of a run (successor.py; the server does the work through `Env.orphans`): an open item whose mover is a session that is gone, a project's last retired agent included, is handed to
    the closest live agent, with a History line giving the reason. It runs before the run reads the board, so the checks that follow see the movers it left. `apply` False (a dry run) only reads: the server writes
    nothing and tells nobody. An item an owner moves is never listed; one with no live successor stays and is reported (`left`). A stage that fails is a stage not made (said in `note`, `failed`), never the end of the run;
    `[audit] orphan_handover` "report" lists without moving and "off" makes no check. → {"mode", "checked", "applied", "read", "found", "moved": [...], "left": [...], "moved_n", "left_n", "skipped", "over_cap", "note", "failed"}."""
    mode = _cfg.audit_orphan_handover()
    out: dict[str, Any] = {"mode": mode, "checked": False, "applied": False, "read": 0, "found": 0, "moved": [], "left": [], "moved_n": 0, "left_n": 0, "skipped": 0, "over_cap": 0, "note": "", "failed": False, "ceiling": False}
    if mode == "off":
        return out
    try:
        ans = (env.orphans or _orphans_ask)(apply and mode == "apply")
    except Exception as e:  # noqa: BLE001
        out.update(failed=True, note=_clip(f"the orphan hand-over failed: {type(e).__name__}: {e}", 200))
        print(f"audit run: {out['note']}", file=sys.stderr, flush=True)
        return out
    ans = ans if isinstance(ans, dict) else {}
    moved = [m for m in ans.get("moved") or [] if isinstance(m, dict)]
    left = [m for m in ans.get("left") or [] if isinstance(m, dict)]
    out.update(checked=bool(ans.get("checked")), applied=bool(ans.get("applied")), read=int(ans.get("read") or 0), found=int(ans.get("found") or 0), moved=moved[:ORPHAN_SHOWN], left=left[:ORPHAN_SHOWN],
               moved_n=len(moved), left_n=len(left), skipped=int(ans.get("skipped") or 0), over_cap=int(ans.get("over_cap") or 0), note=_clip(ans.get("note"), 300), ceiling=bool(ans.get("ceiling")))
    return out


def orphan_text(o: dict[str, Any]) -> str:
    """The orphan stage as the summary line has it ('' when it is off or found nothing)."""
    if o.get("failed") or o.get("ceiling") or (o.get("note") and not o.get("checked")):
        return f" · orphan hand-over: {o['note']}"
    if not o.get("found"):
        return ""
    verb = "handed over" if o.get("applied") else "would be handed over"
    return (f" · orphan hand-over ({o['mode']}): {o['moved_n']} {verb}" + (f", {o['skipped']} changed under it and left" if o.get("skipped") else "")
            + (f", {o['over_cap']} over the cap, left for the next run" if o.get("over_cap") else "") + (f", {o['left_n']} with no live successor" if o.get("left_n") else ""))


def orphan_lines(o: dict[str, Any]) -> list[str]:
    """The lines the summary message carries under its first line: each item handed over (from → to, and why) and each item left with no live successor, so the person reading it can name one."""
    out = [f"  orphan {'handed over' if o.get('applied') else 'would move'} · {m.get('id')} · {m.get('from') or 'no session'} → {m.get('to')} · {_clip(m.get('why'), 160)}" for m in o.get("moved") or []]
    out += [f"  orphan left · {m.get('id')} · {m.get('from') or 'no session'} · no live agent to take it ({m.get('project')})" for m in o.get("left") or []]
    return out


# ---------- the pattern review (the last stage of a model run) ----------
LOG_FILE = "findings-log.jsonl"


def _log_path() -> Path:
    return _audit.state_dir() / LOG_FILE


def log_findings(rows: list[dict[str, Any]]) -> None:
    """Append appearances of findings to the findings log (`<paths.state>/audit/findings-log.jsonl`, one JSON row a line): what the pattern review reads. Each audit pass appends a finding the first time its record shows it
    (`write_pass_record`), the run appends its fresh ones. Nothing is kept with `[audit] pattern_review` off. A log that cannot be written is never the end of a pass or a run."""
    if not rows or _cfg.audit_pattern_review() == "off":
        return
    data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")
    try:
        fd = os.open(_log_path(), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)      # one write on an append descriptor: a batch of any size goes in whole, never between another writer's lines
        try:
            done = 0
            while done < len(data):                 # a short write (rare on a regular file) goes on from where it stopped
                done += os.write(fd, data[done:])
        finally:
            os.close(fd)
    except OSError as e:
        print(f"audit: findings log not written: {e}", file=sys.stderr, flush=True)


def read_log(since: float = 0.0) -> list[dict[str, Any]]:
    """The findings log's rows appended after `since` (an epoch), oldest first; a line that does not parse is skipped."""
    try:
        text = _log_path().read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for ln in text.splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and _f(r.get("at")) > since:
            out.append(r)
    return out


def prune_log(now: float) -> None:
    """Drop the rows older than PATTERN_LOG_DAYS, through a temporary file renamed over the log. Called by the run, while the passes stand still."""
    p = _log_path()
    if not p.exists():
        return
    rows = read_log(now - PATTERN_LOG_DAYS * 86400)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, p)


def review_since(hist: list[dict[str, Any]], now: float) -> float:
    """Where the pattern review's window opens: when the last review that finished reading did so (`pattern_review.at`), found by walking the finished records `hist` (newest first) back to the newest one that has it.
    A review that was off, failed, was cut short or left patterns to the cap has none, and the next review reads what it did not, however many such reviews come in a row. Never more than twice
    PATTERN_WINDOW_H hours back (so with records but no finished review among them, that far); with no record at all, PATTERN_WINDOW_H hours back."""
    floor = now - 2 * PATTERN_WINDOW_H * 3600
    if not hist:
        return now - PATTERN_WINDOW_H * 3600
    for rec in hist:
        pr = rec.get("pattern_review") if isinstance(rec, dict) and isinstance(rec.get("pattern_review"), dict) else {}
        at = _f(pr.get("at"))
        if at > 0:
            return max(at, floor)
    return floor


def _brief_runner(env: Env, brief: str) -> Callable[[str], dict[str, Any]]:
    """The model call of a stage whose system prompt is `brief`: `env.runner` when given (the scenarios), else the router's call on the audit's lane and model, as the judgment calls make it."""
    if env.runner is not None:
        return env.runner
    model, lane = _cfg.audit_model(), _cfg.audit_lane()

    def runner(message: str) -> dict[str, Any]:
        import router as _router  # noqa: PLC0415
        return _router.run_call(message, brief, model_name=model or None, lane=lane or None)
    return runner


def pattern_stage(env: Env, t0: float, hist: list[dict[str, Any]], fresh: list[dict[str, Any]], made: int, dry: bool = False) -> dict[str, Any]:
    """The pattern review, the last stage of a model run: the findings since the review before it (the findings log, and `fresh`, this run's own), grouped by kind, agent and project into patterns, and ONE model call
    (`audit_checks.PATTERN_BRIEF`, the audit's lane and model) that drafts one guardrail for each pattern asked about: a hook, a mod, a tool's text, a rulebook line, or a new audit or an edit to one. A pattern needs
    PATTERN_MIN appearances on PATTERN_MIN_ITEMS items; one drafted in the last PATTERN_DEDUPE_DAYS days is not drafted again (the drafts are on the run records); no more than PATTERN_MAX patterns are asked about.
    The call begins only inside `[audit] max_minutes` and `max_calls` (`made` calls are spent already). Shadow ("shadow", the default): the drafts only go onto the record, nothing is sent, opened or edited, and nothing
    outside the findings log is written; "off": nothing is read, called or logged. A stage that fails is a stage not made (`failed`, said in `note`), never the end of the run; its findings stay unread for the next review
    (`at` stays None; so it does when the cap held patterns back). `dry`: groups and picks, makes no call, writes nothing. → {"mode", "at" (when the review finished reading; None when it did not), "since", "read", "groups", "patterns", "deduped", "capped",
    "called", "failed", "timed_out", "note", "drafts": [{key, kind, agent, project, count, items, guardrail, route, draft, why, at}]}."""
    mode = _cfg.audit_pattern_review()
    info: dict[str, Any] = {"mode": mode, "at": None, "since": None, "read": 0, "groups": 0, "patterns": 0, "deduped": 0, "capped": 0, "called": 0, "failed": 0, "timed_out": False, "note": "", "drafts": []}
    if mode == "off":
        return info
    rt = max(env.clock(), t0)
    try:
        since = review_since(hist, rt)
        rows = read_log(since) + [log_row(f, rt, "run") for f in fresh]
        picked, n = pick_patterns(group_patterns(rows), drafted_recently(hist, rt))
        info.update(since=since, read=len(rows), **n)
        deadline = t0 + _cfg.audit_max_minutes() * 60
        if not picked:
            info["at"] = rt
        elif dry:
            info["note"] = f"would make 1 call about {len(picked)} pattern(s)"
        elif made >= _cfg.audit_max_calls():
            info["note"] = f"[audit] max_calls ({_cfg.audit_max_calls()}) leaves no model call for the review"
        elif env.clock() >= deadline:
            info.update(timed_out=True, note=f"{_cfg.audit_max_minutes()} minutes passed since the run started: no pattern review call")
        else:
            import cold_call as _cc  # noqa: PLC0415
            by_key = {g["key"]: g for g in picked}

            def parse(text: str) -> dict[str, Any] | None:
                d = parse_drafts(text, set(by_key))
                return None if d is None else {"drafts": d}
            info["called"] = 1
            status, ans, note, _raw = _cc.run_with(pattern_prompt(picked, _stamp(since)), PATTERN_BRIEF, parse, _brief_runner(env, PATTERN_BRIEF))
            if status != "ok" or ans is None:
                info.update(failed=1, note=_clip(f"the pattern review call failed: {note}", 200))
            else:
                info["at"] = rt if not info["capped"] else None      # patterns held back by the cap were not read: the next review starts where this one did, and drafts none twice (the dedupe)
                info["drafts"] = [{**{k: by_key[d["key"]][k] for k in ("kind", "agent", "project", "count", "items")}, **d, "at": rt} for d in ans["drafts"][:PATTERN_MAX]]
    except Exception as e:  # noqa: BLE001
        info.update(failed=1, at=None, note=_clip(f"the pattern review failed: {type(e).__name__}: {e}", 200))
        print(f"audit run: {info['note']}", file=sys.stderr, flush=True)
    if not dry:
        # the log's own upkeep, whatever became of the review (each step apart, so one failing does not stop the other): the run's own findings join the log at the time of the review, after they were read, so the
        # next review does not read them again (a review that did not finish has no `at`, and the next window starts before them); rows past PATTERN_LOG_DAYS go
        try:
            log_findings([log_row(f, rt, "run") for f in fresh])
        except Exception as e:  # noqa: BLE001
            print(f"audit run: findings log not kept: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        try:
            prune_log(rt)
        except Exception as e:  # noqa: BLE001
            print(f"audit run: findings log not pruned: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    return info


def pattern_text(pr: dict[str, Any]) -> str:
    """The pattern review as the summary line has it ('' when it is off or has nothing to say)."""
    if pr.get("mode") == "off":
        return ""
    head = f" · pattern review ({pr['mode']}): "
    if pr.get("failed") or (pr.get("note") and not pr.get("patterns")):
        return head + str(pr.get("note") or "failed")
    if not pr.get("patterns"):
        return ""
    return (head + f"{pr['patterns']} pattern(s) in {pr['read']} finding(s), {len(pr['drafts'])} drafted" + (f" ({', '.join(sorted({d['guardrail'] for d in pr['drafts']}))})" if pr["drafts"] else "")
            + (f", {pr['deduped']} already drafted in the last {PATTERN_DEDUPE_DAYS} days" if pr["deduped"] else "") + (f", {pr['capped']} over the cap of {PATTERN_MAX}, left for the next run" if pr["capped"] else "")
            + (f", {pr['note']}" if pr.get("note") else ""))


def pattern_lines(pr: dict[str, Any]) -> list[str]:
    """The lines the summary message carries under its first line for the drafts: the pattern, the kind of guardrail and where it would go (the text of a draft stays on the record)."""
    return [f"  pattern draft · {d['guardrail']} · for {d['route']} · {d['key']}" for d in pr.get("drafts") or []]


def previous(now: float) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """(the last finished record that started at least 6 hours ago, the finished records before this run, newest first). A run that died (`error`) has nothing to compare with: it is left out of both."""
    recs = [r for r in _audit.runs() if r.get("finished") is not None and not r.get("error") and _audit._epoch(r.get("started")) is not None]
    old = [r for r in recs if now - _audit._epoch(r.get("started")) >= UNMOVED_MIN_HOURS * 3600]
    return (old[0] if old else None), recs


def front_step_count(hist: list[dict[str, Any]], items: dict[str, dict[str, Any]], env: Env, now: float) -> tuple[dict[str, Any] | None, str]:
    """(the monthly front-step count, its line for the summary): the first run of a calendar month (in the instance's timezone) takes front_step.month_count over the board and reports it; a month a record
    already holds one for is not counted again, so a regression of the write check shows once a month and costs nothing the rest of it. (None, "") when this month is done or the count cannot be made."""
    import front_step as _fs  # noqa: PLC0415
    try:
        month = dt.datetime.fromtimestamp(now, _cfg.tz()).strftime("%Y-%m")
        if any(isinstance(h.get("front_step_count"), dict) and h["front_step_count"].get("month") == month for h in hist):
            return None, ""
        c = {"month": month, **_fs.month_count(items, env.role_map(), now)}
        c["ids"] = [_shown(g) for g in c["ids"]]
    except Exception as e:  # noqa: BLE001  — the count is an extra: a run does not fail for it
        print(f"audit run: front-step count not made: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None, ""
    return c, (f"  front-held steps, last {c['days']} days: {c['by_other']} of {c['closed']} closed by someone else · {c['open']} open step(s) the write check would refuse now"
               + (f" ({', '.join(c['ids'][:5])}{' …' if len(c['ids']) > 5 else ''})" if c["ids"] else ""))


def _send(env: Env, to: str, text: str, fyi: bool = False) -> tuple[bool, str]:
    """env.deliver, but an exception is a failed delivery, not the end of the run."""
    try:
        ok, said = env.deliver(to, text, fyi)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    return bool(ok), str(said or "")


def _crashed(t0: float, e: BaseException, env: Env) -> None:
    """A run that died: its record is finished with `error` (so the lock on the next cue is gone) and cues.jsonl says why."""
    err = _clip(f"{type(e).__name__}: {e}", 300)
    now = max(env.clock(), t0)
    try:
        write_record({"started": t0, "finished": now, "items_read": 0, "findings": [], "by_session": {}, "by_category": {}, "mode": "script", "error": err}, t0)
    except Exception as w:  # noqa: BLE001
        print(f"audit run: crash record not written: {w}", file=sys.stderr, flush=True)
    _audit._log("script run", 500, f"the audit run failed: {err}", now)


def run(*, dry: bool = False, now: float | None = None, started: float | None = None, items: dict[str, dict[str, Any]] | None = None, anchors: dict[str, Any] | None = None,
        store: Path | None = None, env: Env | None = None, rubric: str | None = None, out: Callable[[str], None] | None = None) -> dict[str, Any]:
    """One audit run. `started`: the epoch the caller already wrote the running record for (the button path); otherwise the run writes it. → the record (or, with `dry`, {"dry": True, …}).
    A run that raises after its record is started finishes that record with `error` (and a line in cues.jsonl) and raises again: a crash is never silent and never holds the next cue back."""
    now = time.time() if now is None else now
    env = env or Env()
    t0 = started if started is not None else now
    if not dry and started is None:
        start_record(t0)
    old_term = None
    if not dry:
        def _term(signum: int, _frame: Any) -> None:       # a systemctl stop, a reboot or the unit's TimeoutStartSec (SIGTERM) ends the run through the crash path, so its record is finished with the reason
            raise SystemExit(128 + signum)
        try:
            old_term = signal.signal(signal.SIGTERM, _term)
        except ValueError:                                  # not the main thread: the caller's handler stays
            old_term = None
    try:
        return _run(dry=dry, now=now, t0=t0, items=items, anchors=anchors, store=store, env=env, rubric=rubric, out=out)
    except BaseException as e:
        if not dry:
            _crashed(t0, e, env)
        raise
    finally:
        if old_term is not None:
            signal.signal(signal.SIGTERM, old_term)


def _run(*, dry: bool, now: float, t0: float, items: dict[str, dict[str, Any]] | None, anchors: dict[str, Any] | None, store: Path | None, env: Env, rubric: str | None, out: Callable[[str], None] | None) -> dict[str, Any]:
    import board_report as _br  # noqa: PLC0415
    import next_report as _nr  # noqa: PLC0415
    say = out or (lambda s: print(s, flush=True))
    orph = orphan_stage(env, apply=not dry)         # first: the open items whose mover is gone go to the closest live agent, so the checks below read the movers it left (a dry run only reads)
    items = items if items is not None else _nr.load_all(store)
    anchors = anchors if anchors is not None else _br.load_anchors(store)
    rubric = rubric if rubric is not None else RUBRIC.read_text(encoding="utf-8").replace("{owner}", _cfg.owner())   # the rubric names the owner as {owner}: his name comes from [instance] owner
    date = _date_of(t0)
    prev, hist = previous(t0)
    label = run_label(t0, hist)
    latest = hist[0] if hist else None             # the verdicts carry on from the newest finished run, whatever its age: they hold until the item is written
    prev_judged = (latest or {}).get("judged") if isinstance((latest or {}).get("judged"), dict) else {}
    by_shown = {_nr.shown(g): g for g in items}
    goal_prev = next((h["goal_judged"] for h in hist if isinstance(h.get("goal_judged"), dict)), {})    # {shown id: stamp of the (subject, Goal) pair judged}, from the newest record that has it

    findings, passes, n_open = field_findings(items, anchors, now, env)
    live: set[str] = set()
    sus, skipped = suspects(items, now, env, prev_judged, live, goal_prev)
    cap = _cfg.audit_max_calls()
    reserve = 1 if cap >= 2 and _cfg.audit_pattern_review() != "off" else 0     # the pattern review's one call keeps one of the calls of the cap
    picked = sus[:cap - reserve]
    pa = env.page_agents(items, now)                        # read only; its messages go after the item findings'
    rg = env.registry_problems(items, now)                  # read only; its messages go after the page agent lines'
    if dry:
        say(f"audit dry run: {n_open} open items · {len(findings)} field findings ({len(passes)} idle-pass) · {len(sus)} suspects ({skipped} unchanged since a verdict) · would make {len(picked)} call(s), cap {cap}")
        for f in findings:
            say(f"  [code] {line_of(f)}  (mover {f['mover'] or '-'})")
        for s in sus:
            say(f"  [suspect{' · over the cap' if s not in picked else ''}] {s['id']} · {', '.join(s['checks'])} · " + " | ".join(f"{c}: {_clip(s['evidence'][c], 100)}" for c in s["checks"]))
        say("  [page-agents] " + (f"{len(pa['findings'])} line(s) on {len({f['page'] for f in pa['findings']})} page(s)" if pa["checked"] else f"not checked ({pa['note']})"))
        for f in pa["findings"]:
            say(f"  [page-agents] {par_line(f)}  (to {par_target(f, env)[0]})")
        if not rg.get("silent"):
            say("  [registry · " + ("sending on" if _cfg.registry_audit_send() else "sending off: [registry_audit] send = false") + "] " + (f"{len(rg['findings'])} problem(s) on {len({f['page'] for f in rg['findings']})} page(s)" + (f" · {rg['note']}" if rg["note"] else "") if rg["checked"] else f"not checked ({rg['note']})"))
        for f in rg["findings"]:
            say(f"  [registry] {par_line(f)}  (to {par_target(f, env)[0]})")
        pw_found, pw = proof_stage(items, anchors, now, env)
        say(f"  [proof-waits] {pw['read']} held for a real event read · {pw['found']} finding(s) · {pw['left_n']} left alone with their basis" + (f" · {pw['note']}" if pw["note"] else ""))
        for f in pw_found:
            say(f"  [proof-wait] {line_of(f)}  (mover {f['mover'] or '-'})")
        for x in pw["left"]:
            say(f"  [proof-wait · left alone] {x['id']} · {x['basis']}")
        if orph["mode"] != "off":
            say(f"  [orphans · {orph['mode']}] " + (f"{orph['read']} open items read · {orph['found']} with a mover that is gone · {orph['moved_n']} would move to the closest live agent · {orph['left_n']} with no live successor" if orph["checked"] else f"not checked ({orph['note']})")
                + (f" · {orph['over_cap']} over the cap, left for the next run" if orph["over_cap"] else "") + (f" · NOTHING MOVES: {orph['note']}" if orph["ceiling"] else ""))
            for ln in orphan_lines(orph):
                say(ln.replace("  orphan ", "  [orphan] ", 1))
        pr = pattern_stage(env, t0, hist, [], 0, dry=True)
        if pr["mode"] != "off":
            say(f"  [pattern-review · {pr['mode']}] {pr['read']} finding(s) in the log since {_stamp(pr['since'])} · {pr['patterns']} pattern(s), {pr['deduped']} already drafted, {pr['capped']} over the cap" + (f" · {pr['note']}" if pr["note"] else ""))
        return {"dry": True, "items_read": n_open, "findings": findings, "idle_pass": passes, "suspects": [{k: s[k] for k in ("id", "checks")} for s in sus], "would_call": len(picked), "cap": cap, "page_agents": pa, "registry": rg, "proof_waits": {**pw, "findings": pw_found},
                "orphans": orph, "pattern_review": pr}

    model_found, entries, calls = judge(items, picked, now, env, rubric, t0)
    pw_found, pw = proof_stage(items, anchors, now, env)      # the proof-waits stage: code only, after the model checks and before the pages stage
    pg = pages_stage(env, t0)                       # the page-debt call, once per run, under the same time limit as the judgment calls
    keep, again = carried(prev_judged, items, {s["id"] for s in picked}, by_shown, live)
    judged = {**keep, **entries}
    goal_judged = {sid: g for sid, g in goal_prev.items() if by_shown.get(sid) and items[by_shown[sid]].get("status") == "open"}     # a closed item's stamp goes
    goal_judged.update({sid: e["gsig"] for sid, e in entries.items() if e.get("gsig")})
    model_ids = {(f["id"], f["category"]) for f in model_found}
    findings += model_found + [f for f in again if (f["id"], f["category"]) not in model_ids] + pw_found

    # a finding already sent, with its item not written since, is not sent again (it keeps its `sent` stamps on the record, so it stays quiet until the item is written, as `written_since_run` reads a write, or the finding ends)
    before = merged_sent(latest, read_filing(), read_dates())      # what the 10-minute filing pass and dates pass sent counts as sent, too
    repeats: list[dict[str, Any]] = []
    fresh: list[dict[str, Any]] = []
    over_cap: list[dict[str, Any]] = []
    n_proof = 0
    for f in findings:
        st = before.get(finding_key(f))
        gid = by_shown.get(f["id"])
        if st and gid and items[gid].get("status") == "open" and not written_since_run(_br._last_write(items[gid]), st[2], st[1], st[0]):
            f["sent"], f["sending_from"], f["run_started"] = st[0], st[1], st[2]
            repeats.append(f)
        elif f["category"] == "proof-wait" and n_proof >= PROOF_MAX:
            over_cap.append(f)                      # more fresh proof-wait findings than the cap: this one waits for the next run (neither sent nor on the record)
        else:
            n_proof += f["category"] == "proof-wait"
            fresh.append(f)
    if over_cap:
        drop = {id(f) for f in over_cap}
        findings = [f for f in findings if id(f) not in drop]
        pw["capped"] = len(over_cap)

    # the pattern review, the last stage: the findings since the review before it, grouped, one guardrail drafted for each pattern; in shadow it only goes onto the record. Before the messages, so it holds nothing back between the
    # sends and the record's end time, and so its text is in the summary line
    pr = pattern_stage(env, t0, hist, fresh, calls["made"])

    # the unmoved flag: a finding of the previous run whose item has had no write since goes to the project's builder, and onto `stuck`
    stuck: list[dict[str, Any]] = []
    prev_start = _audit._epoch((prev or {}).get("started")) if prev else None
    prev_end = (_audit._epoch((prev or {}).get("finished")) or prev_start) if prev else None      # a write after the previous run's last send is a write; one the server makes while that run delivers is not
    prev_from = _audit._epoch((prev or {}).get("sending_from")) if prev else None                 # …and a write the run's own judging time let by, before it began to send, is one too
    prev_stuck = {str(s.get("id")): s for s in ((prev or {}).get("stuck") or []) if isinstance(s, dict)}
    chased_before = {sid for sid, st in prev_stuck.items() if st.get("chased")}
    for h in hist:                                  # a run too recent to be `prev` (under 6 hours before this one, across a midnight too) may have chased the item already
        hs = _audit._epoch(h.get("started"))
        if hs is not None and 0 <= t0 - hs < UNMOVED_MIN_HOURS * 3600:
            chased_before |= {str(st.get("id")) for st in (h.get("stuck") or []) if isinstance(st, dict) and st.get("chased")}
    seen: set[str] = set()
    for pf in [*((prev or {}).get("findings") or []), *((prev or {}).get("idle_pass") or [])]:
        if not isinstance(pf, dict) or prev_start is None:
            continue
        sid = str(pf.get("id") or "")
        gid = by_shown.get(sid)
        if not gid or sid in seen or items[gid].get("status") != "open" or written_since_run(_br._last_write(items[gid]), prev_start, prev_from, prev_end):
            continue
        seen.add(sid)
        stuck.append({"id": sid, "project": str(pf.get("project") or ""), "mover": str(pf.get("mover") or pf.get("owner") or ""), "category": str(pf.get("category") or ""),
                      "first_flagged": (prev_stuck.get(sid) or {}).get("first_flagged") or (prev or {}).get("date") or _date_of(prev_start), "detail": _clip(pf.get("detail"), 160),
                      "chased": sid in chased_before})

    # the messages: one per recipient per run
    sent, reached_fs, sending_from = deliver_findings(env, fresh, f"Board audit {label}")
    sending_from = max(sending_from, t0)
    # the unmoved digest lists an item once: the run that first finds it unmoved chases it to the builder, and only a delivered digest counts as a chase; the record's `stuck` and the summary keep naming it until it is written
    jobs: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for s in stuck:
        if s["chased"]:
            continue
        jobs.setdefault(env.builder_of(s["project"]), []).append((s, f"{s['id']} · unmoved since {s['first_flagged']} · {s['category']} · {s['detail']} · {s['mover'] or 'its mover'} writes it, or says what holds it"))
    for to, ls in sorted(jobs.items()):
        ok, said = _send(env, to, compose([ln for _s, ln in ls], f"[stackshot] Board audit {label}: {len(ls)} flagged item(s) still unmoved since an earlier run; chase the mover (job).", False))
        sent.append({"to": to, "lines": len(ls), "delivered": ok, "said": _clip(said, 120), "kind": "unmoved"})
        if ok:
            for st, _ln in ls:
                st["chased"] = True

    # the page agent lines: one message per agent, listing its pages' leftovers (a front agent's starts with [for <owner>]); it asks the agent to fix the line or retire the name, so it is no fyi
    for to, g in sorted(page_agent_groups(pa, env).items()):
        head = (f"[stackshot] Page agent lines {label}: {len(g['lines'])} line(s) on {len(g['pages'])} page(s) name a session sala no longer knows (page · line · name · what fixes it); fix the line or retire the name."
                if not g["gaps"] else
                f"[stackshot] Page agent lines {label}: {len(g['lines'])} line(s) on {len(g['pages'])} page(s) need a fix (page · line · name · what fixes it): a session sala no longer knows, a project with items and no agents map, or a session working on a project whose agents map has no line for it; each line says the fix.")
        text = compose(g["lines"], head, g["front"])
        ok, said = _send(env, to, text)
        sent.append({"to": to, "lines": len(g["lines"]), "delivered": ok, "said": _clip(said, 120), "kind": "page-agents"})

    # the project registry: with [registry_audit] send = true, one message per agent a day, listing the record's problems with the fix of each (page · problem · name · what fixes it); no fyi, and it comes again the next
    # day until the problem is fixed. A second run on a date sends an agent nothing that a delivered message of that date already told it; nothing is sent when sala's list could not be read (nobody is known to be live)
    registry_told: list[str] = []
    if _cfg.registry_audit_send() and not rg.get("unrouted"):
        told_today = {m.get("to") for h in hist if h.get("date") == date for m in (h.get("messages") or []) if m.get("kind") == "registry" and m.get("delivered")}
        for to, g in sorted(page_agent_groups(rg, env).items()):
            if to in told_today:
                registry_told.append(to)
                continue
            head = (f"[stackshot] Project registry {label}: {len(g['lines'])} problem(s) on {len(g['pages'])} page(s) in the project record or the pages it points at (page · problem · name · what fixes it); each line says the fix.")
            text = compose(g["lines"], head, g["front"])
            ok, said = _send(env, to, text)
            sent.append({"to": to, "lines": len(g["lines"]), "delivered": ok, "said": _clip(said, 120), "kind": "registry"})

    by_cat, by_ses = counts(findings, passes)
    trips = tightening(n_open, findings, by_cat, by_ses, by_day(hist, date))
    thr = _cfg.audit_threshold()
    tripped = [c for c, n in by_cat.items() if c != "idle-pass" and n >= thr]
    if tripped or trips:
        builder = _cfg.audit_builder()
        text = threshold_message(findings, trips, label)
        try:
            ok, said = env.push(builder, text)
        except Exception as e:  # noqa: BLE001
            ok, said = False, f"{type(e).__name__}: {e}"
        if not ok:
            ok, said = _send(env, builder, text)
        sent.append({"to": builder, "lines": len(tripped) + len(trips), "delivered": bool(ok), "said": _clip(said, 120), "kind": "threshold", "checks": sorted(tripped)})
    summary = (f"[stackshot] Board audit {label} (script): {n_open} open items · {len({f['id'] for f in findings})} flagged ({len(findings)} findings) · "
               + (" · ".join(f"{c} {n}" for c, n in sorted(by_cat.items(), key=lambda kv: -kv[1])) or "no findings") + f" · {calls['made'] + pr['called']} model call(s) of {cap}" +(f" · stopped at the {_cfg.audit_max_minutes()}-minute limit" if calls.get("timed_out") else "") + orphan_text(orph) + proof_text(pw) + pages_text(pg) + pattern_text(pr) + (f" · unmoved: {', '.join(s['id'] for s in stuck)}" if stuck else "") + (f" · {len(repeats)} unchanged since sent, not sent again" if repeats else "")
               + (f" · page agent lines {len(pa['findings'])}" if pa["checked"] else f" · page agent lines not checked ({pa['note']})")
               + ("" if rg.get("silent") else f" · registry problems {len(rg['findings'])}" if rg["checked"] else f" · registry not checked ({rg['note']})"))
    fsc, fsc_line = front_step_count(hist, items, env, t0)       # once a calendar month: front agents' steps closed by someone else, and the open ones the write check would refuse now
    summary_to = _cfg.audit_summary_to()
    ok, said = _send(env, summary_to, "\n".join([summary, *orphan_lines(orph), *pattern_lines(pr), *([fsc_line] if fsc_line else [])]), True)
    sent.append({"to": summary_to, "lines": 1, "delivered": ok, "said": _clip(said, 120), "kind": "summary"})

    # the run's end, taken after its last send: a finding is quiet from here on, and the next run reads a write after this time as a write. Every message that cites an item has gone by now, so a save the server makes
    # while delivering one (a message that names an item may write it) is no write of the item's
    end = max(env.clock(), t0)
    for f in reached_fs:
        f["sent"], f["sending_from"], f["run_started"] = end, sending_from, t0

    rec = {"started": t0, "finished": end, "items_read": n_open,
           "findings": [{k: f[k] for k in ("id", "project", "owner", "category", "mover", "detail", "source", "sent", "sending_from", "run_started", "tries", "lvl") if k in f} for f in findings],
           "sending_from": sending_from,
           "repeats": len(repeats),
           "by_session": by_ses, "by_category": by_cat, "stuck": stuck, "idle_pass": passes, "judged": judged, "goal_judged": goal_judged,
           "calls": {"made": calls["made"], "failed": calls["failed"], "cap": cap, "max_minutes": _cfg.audit_max_minutes(), "timed_out": bool(calls.get("timed_out")), "suspects": len(sus), "unchanged": skipped, "notes": calls["notes"]},
           "pages": pg, "proof_waits": pw, **({"orphans": orph} if orph["mode"] != "off" else {}), **({"pattern_review": pr} if pr["mode"] != "off" else {}), **({"front_step_count": fsc} if fsc else {}),
           "messages": sent, "mode": "script",
           "page_agents": {"checked": pa["checked"], "note": pa["note"], "sessions": pa["sessions"], "pages": pa["pages"], "findings": [{k: f.get(k, "") for k in ("page", "line", "name", "to")} for f in pa["findings"]]},
           "registry": {"checked": rg["checked"], "note": rg["note"], "projects": rg["projects"], "pages": rg["pages"], "send": _cfg.registry_audit_send(), "told_earlier_today": registry_told, "findings": [{k: f.get(k, "") for k in ("page", "line", "name", "project", "to")} for f in rg["findings"]]}}
    write_record(rec, t0)
    return rec


# ---------- the front-step rule (part of the filing pass) ----------
def _moved_text(f: dict[str, Any], opener: str, kind: str, hrs: float, line: str, now: float) -> str:
    """The one message to the mover of a step the rule moved to it."""
    return (f"[stackshot] Filing check {_stamp(now)}: {f['id']}: the first open step is now yours ({_clip(line, 110)}). It opened with {opener}, {kind}, and stayed open {hrs:g} hours with the stuck-elsewhere finding "
            f"unanswered, so stackshot reworded it to open with you; the item's History has the original opener. Do it, hand it on or mark it done.")


def _shown(gid: str) -> str:
    import next_report as _nr  # noqa: PLC0415
    return _nr.shown(gid)


def front_step_pass(findings: list[dict[str, Any]], items: dict[str, dict[str, Any]], by_shown: dict[str, str], now: float, env: Env) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The front-step rule (front_step.py): a stuck-elsewhere finding whose step opens with a front agent or a retired session, on an item a session other than the opener moves, starts a clock on the item
    the first pass that sees it (`metadata.stuck_since`, through `env.step_mark`), and past `[audit] front_step_move_hours` (default 3, 0 = off) the step is reworded to open with the item's mover
    (`env.step_move`: the server's reword, with a History line naming the original opener) and the mover gets one message, `fyi`, when it is a session a message can reach (a front or retired mover
    is not told: the History line is the record). Nothing is sent to the front agent. A clock is dropped by a pass that no longer sees the finding for its step. A step moves once. The finding of a step
    still waiting says what will happen and when. → (the findings without the ones whose step moved, the report {hours, started, moved, cleared, errors, messages}). With the threshold 0 (off) it only drops the
    clocks it finds; without the environment's writers, or with an empty role map, it does nothing."""
    import front_step as _fs  # noqa: PLC0415
    hrs = _fs.hours()
    rep: dict[str, Any] = {"hours": hrs, "started": [], "moved": [], "cleared": [], "errors": [], "messages": []}
    if env.step_mark is None or env.step_move is None:
        return findings, rep
    roles = env.role_map()
    if hrs > 0 and not roles:
        return findings, rep          # the role map is briefly empty now and then: no one is a front agent for this pass, which must not drop the clocks
    cands = _fs.candidates(findings, items, by_shown, roles, FRONT_ROLES) if hrs > 0 else {}      # off: no step is watched, and the sweep below drops the clocks a longer setting left, so turning it on again starts clean
    cands = {g: c for g, c in cands.items() if not _fs.moved_before(items[g].get("metadata") or {}, c["hash"])}      # a step moves once
    moved: set[str] = set()
    for gid, c in cands.items():
        f, h, mover = c["finding"], c["hash"], c["mover"]
        at = _fs.clock(items[gid].get("metadata") or {}, h, mover)
        promise: float | None = None        # when the finding says the step moves: only for a clock that is kept (a failed write, a refused move promise nothing)
        try:
            if at is None:
                if env.step_mark(gid, h, now, mover):
                    rep["started"].append(f["id"])
                    promise = now + hrs * 3600
            elif now - at >= hrs * 3600:
                res = env.step_move(gid, h, c["opener"], mover, hrs, now) or {}
                if res.get("moved"):
                    moved.add(gid)
                    shown_h = round((now - at) / 3600, 1)
                    rep["moved"].append({"id": f["id"], "from": c["opener"], "to": mover, "hours": shown_h})
                    to, front = recipient(mover, f.get("project") or "", env, mover)
                    if to == mover and not front:
                        kind = "a retired session" if (roles.get(c["opener"]) or {}).get("retired") else "a front agent"
                        ok, said = _send(env, mover, _moved_text(f, c["opener"], kind, shown_h, str(res.get("line") or ""), now), fyi=True)
                        rep["messages"].append({"to": mover, "delivered": ok, "said": _clip(said, 120)})
                    continue
                rep["errors"].append(f"{f['id']}: not moved ({_clip(res.get('why'), 100)})")
            else:
                promise = at + hrs * 3600
        except Exception as e:  # noqa: BLE001  — one item's failure never stops the pass
            rep["errors"].append(f"{f['id']}: {type(e).__name__}: {_clip(e, 100)}")
        if promise is not None:
            f["fix"] = _fs.fix_text(_label(mover), promise)
    for gid, it in items.items():          # a clock whose finding is gone (the step is done, dropped or reworded, or the mover or the opener changed): dropped
        if gid in cands or not isinstance(it.get("metadata"), dict) or _fs.CLOCK not in it["metadata"]:
            continue
        try:
            if env.step_mark(gid, None, now):
                rep["cleared"].append(_shown(gid))
        except Exception as e:  # noqa: BLE001
            rep["errors"].append(f"{gid}: {type(e).__name__}: {_clip(e, 100)}")
    return [f for f in findings if not (f.get("category") == "stuck-elsewhere" and by_shown.get(str(f.get("id") or "")) in moved)], rep


def wake_park_pass(findings: list[dict[str, Any]], items: dict[str, dict[str, Any]], by_shown: dict[str, str], now: float, env: Env) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The server's own fix of a wake that is the whole of a wait (server_fixes.WAKE_PARK): each why-not-now finding the filing rules raise in code (audit_checks.date_only_wait) is parked through
    `env.wake_park`, the same park the write makes (hold with the wake and a wait_basis made from the step's words, a History line), and no longer sent as a finding. The mover gets one message,
    `fyi`, naming what was parked and how to undo it (clear_hold), when it is a session a message can reach (a retired mover is not told: the History line is the record). An item whose mover is a front agent is not parked at all: it would get no notice, so the finding stands. A wake the
    mover sent back (clear_hold on the park) is not parked again and is no finding either: the server leaves that field alone, with or without the writer. A finding for a wake the server could not
    park stands. Nothing is closed and no ask is written. → (the findings without the ones parked or sent back, the report {parked, declined, errors, messages}). Without the environment's writer
    nothing else is done."""
    import server_fixes as _sf  # noqa: PLC0415
    rep: dict[str, Any] = {"parked": [], "declined": [], "errors": [], "messages": []}
    done: set[str] = set()
    owed: dict[str, list[str]] = {}
    proj: dict[str, str] = {}
    for f in findings:
        if f.get("category") != "why-not-now" or f.get("source") != "code":
            continue
        gid = by_shown.get(str(f.get("id") or ""))
        if not gid:
            continue
        meta = (items.get(gid) or {}).get("metadata") or {}
        if _sf.declined(meta, _sf.WAKE_PARK, str(meta.get("wake") or "")):
            done.add(str(f["id"]))
            rep["declined"].append(f["id"])
            continue
        if env.wake_park is None:
            continue
        if str((env.role_map().get(str(f.get("mover") or "")) or {}).get("role") or "") in FRONT_ROLES:      # a front agent gets no notice of a park: the finding stands, as it did before the fix
            continue
        try:
            res = env.wake_park(gid, now) or {}
        except Exception as e:  # noqa: BLE001  — one item's failure never stops the pass
            rep["errors"].append(f"{f['id']}: {type(e).__name__}: {_clip(e, 100)}")
            continue
        if not res.get("parked"):
            continue
        done.add(str(f["id"]))
        rep["parked"].append(f["id"])
        owed.setdefault(str(f.get("mover") or ""), []).append(f"{f['id']} (wake {res.get('wake')})")
        proj.setdefault(str(f.get("mover") or ""), str(f.get("project") or ""))
    for mover, shown in owed.items():
        to, front = recipient(mover, proj.get(mover, ""), env, mover)
        if to != mover or front:
            continue
        ok, said = _send(env, mover, (f"The server parked {len(shown)} item{'s' if len(shown) > 1 else ''} of yours whose only open step waits for its wake, as the ten-minute check used to ask you to: " + "; ".join(shown)
                                       + ". Each is on hold until its wake, with a wait_basis made from the step's own words, and History has a line. If a step can run now, write it as the action and pass clear_hold=true: "
                                         "the server then leaves that wake alone."), fyi=True)
        rep["messages"].append({"to": mover, "delivered": ok, "said": _clip(said, 120)})
    return [f for f in findings if str(f.get("id")) not in done or f.get("category") != "why-not-now"], rep


def wait_end_pass(findings: list[dict[str, Any]], items: dict[str, dict[str, Any]], by_shown: dict[str, str], now: float, env: Env) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The server's own fix of a wait a next line states in words (server_fixes.WAIT_END, wait_end.py): each `wait-end` finding the filing rules raise in code that carries a fix (`gap.plan`) is made through `env.wait_end`
    (after, an event wait, an anchor wait, a step proof or a backstop day, through the gates a write passes, with a History line) and no longer sent as a finding, at most wait_end.FIX_CAP a pass. The mover gets one message, `fyi`,
    naming what was set and how to send it back, when it is a session a message can reach. An item whose mover is a front agent is not fixed (it would get no notice) and its finding stands, and so does a finding the server could not
    fix (the write gates refused it, or the line changed under it). Nothing is closed and no ask is written. With `[audit] wait_end = "ask"` (or no `env.wait_end`) nothing is written: the findings go to the movers as questions.
    -> (the findings without the ones fixed, {fixed, asked, routed, errors, messages})."""
    import wait_end as _we  # noqa: PLC0415
    rep: dict[str, Any] = {"fixed": [], "asked": 0, "routed": 0, "errors": [], "messages": []}
    done: set[str] = set()
    owed: dict[str, list[str]] = {}
    proj: dict[str, str] = {}
    live = env.wait_end is not None and _cfg.audit_wait_end() == "fix"
    for f in findings:
        gap = f.get("gap")
        if f.get("category") != "wait-end" or f.get("source") != "code" or gap is None or not live:
            continue
        gid = by_shown.get(str(f.get("id") or ""))
        if not gid or len(rep["fixed"]) >= _we.FIX_CAP:
            continue
        if str((env.role_map().get(str(f.get("mover") or "")) or {}).get("role") or "") in FRONT_ROLES:      # a front agent gets no notice of a fix: the finding stands
            continue
        try:
            res = env.wait_end(gid, {**gap.plan, "token": gap.token, "line": gap.line, "pos": gap.pos, "kind": gap.kind}, now) or {}
        except Exception as e:  # noqa: BLE001  - one item's failure never stops the pass
            rep["errors"].append(f"{f['id']}: {type(e).__name__}: {_clip(e, 100)}")
            continue
        if not res.get("fixed"):
            continue
        done.add(str(f["id"]))
        rep["fixed"].append(f["id"])
        owed.setdefault(str(f.get("mover") or ""), []).append(f"{f['id']} ({res.get('what') or gap.plan.get('op')})")
        proj.setdefault(str(f.get("mover") or ""), str(f.get("project") or ""))
    for mover, shown in owed.items():
        to, front = recipient(mover, proj.get(mover, ""), env, mover)
        if to != mover or front:
            continue
        ok, said = _send(env, mover, _we.mover_message(shown), fyi=True)
        rep["messages"].append({"to": mover, "delivered": ok, "said": _clip(said, 120)})
    left = [f for f in findings if not (str(f.get("id")) in done and f.get("category") == "wait-end")]
    rep["asked"] = sum(1 for f in left if f.get("category") == "wait-end")
    rep["routed"] = sum(1 for f in left if f.get("category") == "event-missing")
    return left, rep


# ---------- the filing pass (every ten minutes, in the server) ----------
FILING_FILE = "filing.json"


def _filing_path() -> Path:
    return _audit.state_dir() / FILING_FILE


def read_filing() -> dict[str, Any]:
    """The filing pass's record (`<paths.state>/audit/filing.json`): shaped like a run record for what the daily run reads of it (`started`, `repeats`, `findings` with their `sent` stamps), plus `flags`. {} when none."""
    try:
        d = json.loads(_filing_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def merged_sent(*recs: dict[str, Any] | None) -> dict[tuple[str, str, str], tuple[float, float | None, float | None]]:
    """`sent_before` over several records (the newest daily run, the filing pass's own): where two say a finding was sent, the later send stands. A finding the filing pass sent is therefore not sent again by the
    daily run while its item stays unwritten, and the other way round."""
    out: dict[tuple[str, str, str], tuple[float, float | None, float | None]] = {}
    for rec in recs:
        for k, v in sent_before(rec).items():
            if k not in out or v[0] > out[k][0]:
                out[k] = v
    return out


def tries_before(*recs: dict[str, Any] | None) -> dict[tuple[str, str, str], int]:
    """{finding key: how many times it was sent while it stood} from the passes' records: the `tries` a finding carries, from the record whose send is the latest. A finding whose record does not carry one counts once
    (a send before this was kept), and one the pass dropped from its record (it ended) is gone, so a finding that comes back starts over."""
    best: dict[tuple[str, str, str], tuple[float, int]] = {}
    for rec in recs:
        for f in (rec or {}).get("findings") or []:
            if not isinstance(f, dict) or not isinstance(f.get("sent"), (int, float)) or isinstance(f.get("sent"), bool) or f["sent"] <= 0:
                continue
            n = f.get("tries")
            n = n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 1
            k = finding_key(f)
            if k not in best or f["sent"] >= best[k][0]:
                best[k] = (float(f["sent"]), n)
    return {k: v[1] for k, v in best.items()}


def levels_before(*recs: dict[str, Any] | None) -> dict[tuple[str, str, str], int]:
    """{finding key: the escalation level its latest send reached} from the passes' records (`lvl`: 1 = told the project's builder as unmoved, 2 = the project's -main agent). A record from before levels were kept
    carries none, so a finding that was escalated then is not escalated again by a release that adds a level: only a builder send this code made is followed by a message to -main."""
    best: dict[tuple[str, str, str], tuple[float, int]] = {}
    for rec in recs:
        for f in (rec or {}).get("findings") or []:
            if not isinstance(f, dict) or not isinstance(f.get("sent"), (int, float)) or isinstance(f.get("sent"), bool) or f["sent"] <= 0:
                continue
            v = f.get("lvl")
            v = v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0
            k = finding_key(f)
            if k not in best or f["sent"] >= best[k][0]:
                best[k] = (float(f["sent"]), v)
    return {k: v[1] for k, v in best.items()}


def split_sent(findings: list[dict[str, Any]], items: dict[str, dict[str, Any]], before: dict[tuple[str, str, str], tuple[float, float | None, float | None]],
               by_shown: dict[str, str], tries: dict[tuple[str, str, str], int] | None = None, now: float | None = None,
               last: Callable[[dict[str, Any], dict[str, Any]], float] | None = None,
               levels: dict[tuple[str, str, str], int] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(repeats, fresh): a finding sent before (`before`, from `merged_sent`) whose item has not been written since goes back onto its old stamps (`sent`, `sending_from`, `run_started`) and is not sent again;
    every other finding is fresh. The rule the daily run applies to its own findings, shared by the ten-minute passes. `last(item, finding)` is the item's last write (default board_report._last_write).
    With `tries` and `now` (the ten-minute passes give them) a finding does not go quiet for good: each finding carries `tries`, how many sends it has had while it stood (a send after a write counts too), and an unanswered
    one is fresh again `[audit] remind_hours` after its last send, worded as a later try, until it has had REMIND_TRIES; at the next due time after that it is `escalate`d 1 (deliver_findings sends it to the
    project's builder as unmoved, once), at the one after that `escalate`d 2 (to the project's -main agent, once, and only a finding that went to a builder), and then it is quiet until the item is written.
    `levels` (from `levels_before`) is what keeps a release from sending a burst: the second level applies only to a finding whose builder-level send was made with the level kept (`lvl` 1 on its record); one
    that was escalated before, or whose record carries none, stays quiet."""
    import board_report as _br  # noqa: PLC0415
    last = last or (lambda it, _f: _br._last_write(it))
    hrs = _cfg.audit_remind_hours() if tries is not None and now is not None else 0.0
    repeats: list[dict[str, Any]] = []
    fresh: list[dict[str, Any]] = []
    for f in findings:
        k = finding_key(f)
        st = before.get(k)
        gid = by_shown.get(f["id"])
        n = (tries or {}).get(k, 1) if st else 0
        if st and gid and items[gid].get("status") == "open" and not written_since_run(last(items[gid], f), st[2], st[1], st[0]):
            lv = (levels or {}).get(k, 0)
            if lv:
                f["lvl"] = lv       # the level a repeat has reached stays on its record
            if hrs > 0 and now is not None and f.get("category") not in ONCE and n <= REMIND_TRIES + (1 if lv else 0) and now - st[0] >= hrs * 3600:
                f["tries"] = n + 1
                f["prev"] = {"sent": st[0], "sending_from": st[1], "run_started": st[2], "tries": n}       # what carry_unreached puts back if this send is not reached
                if n >= REMIND_TRIES:
                    f["escalate"] = n - REMIND_TRIES + 1       # 1: the builder (the page key when it is the builder that did not answer); 2: the project's -main agent
                fresh.append(f)
                continue
            f["sent"], f["sending_from"], f["run_started"] = st[0], st[1], st[2]
            if tries is not None:
                f["tries"] = n
            repeats.append(f)
        else:
            if tries is not None:
                f["tries"] = n + 1
            fresh.append(f)
    return repeats, fresh


def carry_unreached(findings: list[dict[str, Any]]) -> None:
    """A reminder or the escalation that was not reached (the send failed, the recipient could not be found) leaves the finding on its old stamps and old `tries`: the next pass finds it due again and retries that same send, with its
    wording, instead of starting over at the first try (and, for the escalation, instead of walking the whole chain again). A finding that was reached carries its new stamps and is left alone."""
    for f in findings:
        prev = f.pop("prev", None)
        if prev and "sent" not in f:
            f["sent"], f["sending_from"], f["run_started"], f["tries"] = prev["sent"], prev["sending_from"], prev["run_started"], prev["tries"]
            f.pop("escalate", None)


def write_pass_record(p: Path, rec: dict[str, Any]) -> None:
    """A ten-minute pass's record, written whole through a temporary file and renamed over the old one, so a reader never sees half of it. A finding the record shows that the record before it did not (a new one, or one that
    ended and came back) is appended to the findings log first, for the pattern review (`log_findings`); a log that cannot be kept never stops the record."""
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        if _cfg.audit_pattern_review() != "off" and isinstance(rec.get("findings"), list):
            try:
                old = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                old = {}
            seen = {finding_key(f) for f in (old.get("findings") or [] if isinstance(old, dict) else []) if isinstance(f, dict)}
            at = rec.get("finished") if isinstance(rec.get("finished"), (int, float)) and not isinstance(rec.get("finished"), bool) else time.time()
            log_findings([log_row(f, float(at), p.stem) for f in rec["findings"] if isinstance(f, dict) and finding_key(f) not in seen])
    except Exception as e:  # noqa: BLE001
        print(f"audit: findings log not kept for {p.name}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def filing_pass(*, now: float | None = None, items: dict[str, dict[str, Any]] | None = None, anchors: dict[str, Any] | None = None, store: Path | None = None,
                env: Env | None = None, dry: bool = False) -> dict[str, Any]:
    """The filing rules (audit_checks.filing_findings) over the open items, and what a finding owes. A finding goes to its mover as the daily run sends one (`deliver_findings`), once: it is not sent
    again while its item has not been written since (the daily run's own rule, and the daily run's records count too), and it is sent again once its item has been written since. A finding that ends and comes back with its item unwritten is sent again: the pass's record keeps only the findings of its last pass, and the daily run no longer makes these checks, so no daily record holds its send stamp. The record is
    `<paths.state>/audit/filing.json`, rewritten each pass. Nothing is sent or written while a daily run is in progress (the pass stands still then, and what falls due is sent by the first pass after the run) or with `dry`.
    → {"skipped": why} or {"open", "findings", "fresh", "repeats", "flags", "sent"}."""
    import board_report as _br  # noqa: PLC0415
    import next_report as _nr  # noqa: PLC0415
    now = time.time() if now is None else now
    env = env or Env()
    if not dry and _audit.running(now) is not None:
        return {"skipped": "a daily run is in progress"}
    items = items if items is not None else _nr.load_all(store)
    anchors = anchors if anchors is not None else _br.load_anchors(store)
    findings, flags = _ac.filing_findings(items, anchors, now, env)
    n_open = sum(1 for it in items.values() if it.get("status") == "open")
    by_shown = {_nr.shown(g): g for g in items}
    front = None
    parked: dict[str, Any] = {}
    waited: dict[str, Any] = {}
    if not dry:
        findings, front = front_step_pass(findings, items, by_shown, now, env)
        findings, parked = wake_park_pass(findings, items, by_shown, now, env)
        findings, waited = wait_end_pass(findings, items, by_shown, now, env)
    recs = _audit.runs(limit=5)
    latest = next((r for r in recs if r.get("finished") is not None and not r.get("error")), None)
    prior = read_filing()
    before = merged_sent(latest, prior)
    repeats, fresh = split_sent(findings, items, before, by_shown, tries_before(latest, prior), now, levels=levels_before(latest, prior))
    res = {"open": n_open, "findings": len(findings), "fresh": len(fresh), "repeats": len(repeats), "flags": len(flags), "sent": []}
    if dry:
        return {**res, "dry": True, "detail": findings, "flag_detail": flags}
    sent, reached_fs, sending_from = deliver_findings(env, fresh, f"Filing check {_stamp(now)}") if fresh else ([], [], env.clock())
    end = max(env.clock(), now)
    sending_from = max(sending_from, now)
    for f in reached_fs:
        f["sent"], f["sending_from"], f["run_started"] = end, sending_from, now
    carry_unreached(findings)
    rec = {"started": now, "finished": end, "items_read": n_open, "repeats": len(repeats), "flags": flags, "messages": sent,
           **({"front_steps": front} if front and (front["moved"] or front["started"] or front["cleared"] or front["errors"]) else {}),
           **({"wake_park": parked} if parked.get("parked") or parked.get("errors") else {}),
           **({"wait_end": waited} if waited.get("fixed") or waited.get("errors") or waited.get("asked") or waited.get("routed") else {}),
           "findings": [{k: f[k] for k in ("id", "project", "owner", "category", "mover", "detail", "source", "sent", "sending_from", "run_started", "tries", "lvl") if k in f} for f in findings]}
    write_pass_record(_filing_path(), rec)
    return {**res, "sent": sent, **({"front_steps": front} if front else {}), **({"wake_park": parked} if parked else {}), **({"wait_end": waited} if waited else {})}


# ---------- the dates pass (every ten minutes, in the server) ----------
DATES_FILE = "dates.json"


def _dates_path() -> Path:
    return _audit.state_dir() / DATES_FILE


def read_dates() -> dict[str, Any]:
    """The dates pass's record (`<paths.state>/audit/dates.json`), shaped like the filing pass's: `started`, `repeats`, `findings` with their `sent` stamps. {} when none."""
    try:
        d = json.loads(_dates_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def dates_pass(*, now: float | None = None, items: dict[str, dict[str, Any]] | None = None, anchors: dict[str, Any] | None = None, store: Path | None = None,
               env: Env | None = None, dry: bool = False, entered: Any = None) -> dict[str, Any]:
    """The dates rule (audit_checks.dates_findings: an item's own expected time has passed with no write since) over the open items, and what a finding owes. Delivered as the filing pass delivers:
    to the recipient the daily run's `stale` finding goes to (`deliver_findings`), once, not again while its item has not been written since (the newest daily record counts too, so a send an earlier run made still holds), and again once the item has been written since. The record is `<paths.state>/audit/dates.json`, rewritten each pass. Nothing is sent or written while a
    daily run is in progress (the pass stands still then, and what falls due is sent by the first pass after the run) or with `dry`. `entered(gid, mover, now, detail)`, when given (the server gives it
    with `[ladder] silence` on), is called for each fresh finding that reached someone, as the silence pass calls it: the message is the ask of the one ladder.
    → {"skipped": why} or {"open", "findings", "fresh", "repeats", "idle_pass", "sent"}."""
    import board_report as _br  # noqa: PLC0415
    import next_report as _nr  # noqa: PLC0415
    now = time.time() if now is None else now
    env = env or Env()
    if not dry and _audit.running(now) is not None:
        return {"skipped": "a daily run is in progress"}
    items = items if items is not None else _nr.load_all(store)
    anchors = anchors if anchors is not None else _br.load_anchors(store)
    findings, passes = _ac.dates_findings(items, anchors, now, env)
    n_open = sum(1 for it in items.values() if it.get("status") == "open")
    by_shown = {_nr.shown(g): g for g in items}
    recs = _audit.runs(limit=5)
    latest = next((r for r in recs if r.get("finished") is not None and not r.get("error")), None)
    prior = read_dates()
    before = merged_sent(latest, prior)
    repeats, fresh = split_sent(findings, items, before, by_shown, tries_before(latest, prior), now, levels=levels_before(latest, prior))
    res = {"open": n_open, "findings": len(findings), "fresh": len(fresh), "repeats": len(repeats), "idle_pass": len(passes), "sent": []}
    if dry:
        return {**res, "dry": True, "detail": findings, "idle_pass_detail": passes}
    sent, reached_fs, sending_from = deliver_findings(env, fresh, f"Dates check {_stamp(now)}") if fresh else ([], [], env.clock())
    end = max(env.clock(), now)
    sending_from = max(sending_from, now)
    for f in reached_fs:
        f["sent"], f["sending_from"], f["run_started"] = end, sending_from, now
        if entered is not None and by_shown.get(f["id"]):
            try:
                entered(by_shown[f["id"]], f.get("mover") or "", now, f.get("detail") or "")
            except Exception as e:  # noqa: BLE001  — the message went; the item is simply not on the ladder
                print(f"dates: {f['id']} not put on the ladder: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    carry_unreached(findings)
    rec = {"started": now, "finished": end, "items_read": n_open, "repeats": len(repeats), "idle_pass": passes, "messages": sent,
           "findings": [{k: f[k] for k in ("id", "project", "owner", "category", "mover", "detail", "source", "sent", "sending_from", "run_started", "tries", "lvl") if k in f} for f in findings]}
    write_pass_record(_dates_path(), rec)
    return {**res, "sent": sent}


# ---------- the command line ----------
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="audit.py run", description="One board audit run in script mode.")
    ap.add_argument("--dry-run", action="store_true", help="list the field findings and the suspects; make no model call, send nothing, write no record")
    ap.add_argument("--started", type=float, help="the epoch of the running record the caller (the button) already wrote; the run continues it")
    ap.add_argument("--store", help="read the items from this folder (a copy of the store) instead of [paths] store")
    a = ap.parse_args(argv)
    store = Path(a.store).expanduser() if a.store else None
    started = a.started
    if started is not None:
        cur = _audit.running()
        if cur is None or _audit._epoch(cur.get("started")) != started:
            print("audit run: no running record with that start; nothing done", file=sys.stderr)
            return 1
    elif not a.dry_run:
        # a run by hand passes the same guards as a cue, under the same lock: it writes the running record itself
        started = time.time()
        code, text = _audit.claim(started)
        if code == 0:
            print('audit run: [audit] mode is "agent", the script does not run (switch the mode back to "script" to use it); nothing done', file=sys.stderr)
            return 1
        if code != 202:
            print(f"audit run: {text}; nothing done", file=sys.stderr)
            return 1
    rec = run(dry=a.dry_run, started=started, now=time.time(), store=store)
    if not a.dry_run:
        summary = f"audit run: {rec['items_read']} open items · {len(rec['findings'])} findings · {rec['calls']['made']} model call(s) · record {_record_path(rec['started']).name}"
        print(summary)
        if a.started is not None:                           # the detached run of the button: its end goes to the cue log, as an inline run's does through the cue
            _audit._log("script run", 200, summary, time.time())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
