"""job_alert.py: `client.py job-failed` and `client.py job-ok`, a scheduled job's failed run as ONE board item per (unit, host) that the job's next successful run closes.

A machine's job that ends in failure runs a failure hook that calls `client.py job-failed <unit> <host> <ISO-Z time of the failing run> <project>`; the same job's later successful run calls
`client.py job-ok <unit> <host> <ISO-Z time>`. The first opens one item for the project's builder (the background agent whose mandate builds, `agents._builder_agent`, as job_gap.py finds it), the second
closes it. The item is marked `metadata.job_alert` = `<unit> on <host>`, and the state a later call needs (the failed runs' times, their count, whether the item sits with a fallback) is in its metadata, never in
memory, so a restart of the server loses nothing. While an item with the mark is open a repeat failure adds the run's time to it (and to its count) and files nothing; a failure after the close opens a new item, unless its time is no later than the success that closed the last one (the close keeps
that success's time in `metadata.closed_by_ok_at`: a retry or a call that came late is that item's); a
`job-ok` with no open item, or older than the latest failed run it was sent for, does nothing. The caller re-sends a `job-ok` that was lost, so both calls are safe to repeat: a time already recorded counts once.

The project text is a page key, a `scope/project` label or `-`: the instance's own map `[job_alert.projects]` is read first, then the key or slug, then the page whose `display-name:` is the label with `/` made `-`. A project of `-` (the unit has none) or one this server has no page for goes to the general project's builder (the page `[job_alert] fallback_project` names: the code names none, an instance sets its own) and the item says so; with none set the call is a 409. A project with no builder is
moved by its -main agent, as job_gap.py does, and says so. Modelled on job_gap.py (the same create path, the lookup of an open item and the write under one lock, a script's row that owes no page and tells no
front agent); the helpers it files its rows with are service/terminal_prompt.py's.

A service module: it reads the config, the project record and the store and writes through `create_item`, the store's own save and the update tool's code. The route that calls it (`_client_post`) is the surface's.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import re
import threading
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core import datewords as _datewords
from stackshot.core.store import _item_files
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model.field_gates import _close_reason_max, _fit, _next_line_max, _subject_max
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _registry
from stackshot.service import agents as _agents
from stackshot.service import create as _create_svc
from stackshot.service import item_read as _item_read
from stackshot.service import job_gap as _job_gap
from stackshot.service import store as _svcstore
from stackshot.service import terminal_prompt as _terminal
from stackshot.service import update as _update_svc
from stackshot.service import writes as _writes


# ----------------------------------------------------------------------------- a failed run of a scheduled job (client.py job-failed, job-ok)
_JOBALERT_LOCK = threading.Lock()
_JOBALERT_LABEL = "job alert"                                                          # the script's own label: the item's creator reads "job alert (a script on <machine>)"
_JOBALERT_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
_JOBALERT_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")      # an ISO time in UTC, the form every script on a machine can write
_JOBALERT_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,59}(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,59}){0,2}")      # `scope/project`, an id or a bare slug; a single `-` is no project
_JOBALERT_KEEP = 20                                                                    # failed runs' times kept on the item (the newest); the count goes on past it
_JOBALERT_SHOWN = 3                                                                    # failed runs listed in the description (the newest)
_JOBALERT_AHEAD = dt.timedelta(minutes=5)                                              # how far past the server's clock a run's time may be (the machines' clocks differ a little); a later one is refused


def _jobalert_when(iso: str) -> str:
    """An ISO-Z time as people read it in the instance's timezone: `Mon Nov 23rd 11:16 KST`, with the year when it is not the current one."""
    d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(_cfg.tz())
    return f"{_datewords.when_words(d, _jobalert_now().astimezone(_cfg.tz()))} {_cfg.tz_abbr(d)}"


def _jobalert_instant(iso: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _jobalert_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _jobalert_canon(d: dt.datetime) -> str:
    """One spelling for one instant (`...:00Z` and `...:00.000Z` are the same run): UTC, the fraction only when it is not zero."""
    return d.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _jobalert_mark(unit: str, host: str) -> str:
    return f"{unit} on {host}"


def _jobalert_items(mark: str, is_open: bool) -> list[str]:
    """The ids of the items marked as this (unit, host)'s failed run, the open ones or the others (the mark is read as text first, so a store of thousands is cheap to scan). The key is the item's own: it survives a restart."""
    out = []
    for gid, p in _item_files():
        try:
            if '"job_alert"' not in p.read_text(encoding="utf-8"):
                continue
            it = _svcstore._load(gid)
        except (OSError, ValueError, ToolError):
            continue
        if (it.get("status") == "open") == is_open and str((it.get("metadata") or {}).get("job_alert") or "") == mark:
            out.append(gid)
    return out


def _jobalert_open_items(mark: str) -> list[str]:
    return _jobalert_items(mark, True)


def _jobalert_last_ok(mark: str) -> tuple[str, dt.datetime | None]:
    """The closed item of this (unit, host) whose success is the latest -> (its id, that success's instant), or ("", None) when no closed item holds one (an item closed before the success was kept, or closed by hand, holds none)."""
    best: tuple[str, dt.datetime | None] = ("", None)
    for gid in _jobalert_items(mark, False):
        at = _jobalert_instant(str((_svcstore._load(gid).get("metadata") or {}).get("closed_by_ok_at") or ""))
        if at is not None and (best[1] is None or at > best[1]):
            best = (gid, at)
    return best


def _jobalert_check(body: dict[str, Any], keys: tuple[str, ...]) -> tuple[dict[str, str], tuple[int, dict[str, Any]] | None]:
    """The body's text fields checked -> ({unit, host, time[, project]}, None) or ({}, the 400)."""
    stray = sorted(str(k) for k in body if k not in keys)
    if stray:
        return {}, (400, {"error": f"not taken: {', '.join(stray)}; this call takes {', '.join(keys)} and nothing else"})
    got = {}
    for k in keys:
        v = body.get(k)
        if not isinstance(v, str) or not v.strip():
            return {}, (400, {"error": f"{k} is required: text"})
        got[k] = v.strip()
    if not _job_gap._JOBGAP_TIMER.fullmatch(got["unit"]):
        return {}, (400, {"error": "unit = the systemd unit's name (nightly.service): letters, digits and @ : _ . - only, at most 120 characters"})
    if not _JOBALERT_HOST.fullmatch(got["host"]):
        return {}, (400, {"error": "host = the machine's name: letters, digits and . _ - only, at most 63 characters"})
    at = _jobalert_instant(got["time"]) if _JOBALERT_TIME.fullmatch(got["time"]) else None
    if at is None:
        return {}, (400, {"error": "time = the run's time as an ISO time in UTC, 2026-11-23T02:15:00Z"})
    if at > _jobalert_now() + _JOBALERT_AHEAD:
        ahead = int((at - _jobalert_now()).total_seconds() // 60)
        return {}, (400, {"error": f"time = the run's time, which cannot be later than now (the server allows 5 minutes for clocks that differ): the machine's clock is ahead of the server's by {ahead} minutes; check the machine's clock"})
    try:
        _jobalert_when(got["time"])
    except (OverflowError, ValueError):
        return {}, (400, {"error": "time = a run's time the board can show, 2026-11-23T02:15:00Z"})
    got["time"] = _jobalert_canon(at)
    if "project" in got and got["project"] != "-" and not _JOBALERT_PROJECT.fullmatch(got["project"]):
        return {}, (400, {"error": "project = a project page key, a `scope/project` label, or - when the job has no project"})
    return got, None


def _jobalert_page(key: str, reg: dict[str, Any]) -> dict[str, Any] | None:
    """The record of the page whose full key is `key` (None when the registry has no such page)."""
    return next((r for r in _prj.refs(key, reg) if r["key"] == key), None) if key in reg else None


def _jobalert_resolve(project: str, reg: dict[str, Any]) -> tuple[dict[str, Any] | None, tuple[int, dict[str, Any]] | None]:
    """The project page a unit's project text names -> (its record, None), (None, None) when it names none, or (None, the 409) when it names several. In order: the instance's own map of labels to page
    keys (`[job_alert.projects]`, read at each call; a key that names no page falls through), then the text as an id, a full page key or a bare slug (`projects.refs`), then, for a `scope/project` label, the one
    top-level page whose `display-name:` line is the label with its `/` made `-` (`projects.name_line`, the line every name check reads; compared without regard to case, and only a page of `type: project` that is
    active (`projects.page_active`: not done, retired, archived or moved) counts, so a finished page of the same name is no second match). A text that matches two pages of either kind is refused: the caller names one by its full key,
    or the instance pins the label in its map. A record that was found by the map or by the name carries `via`, the words the item's note says it by."""
    mapped = _cfg.get("job_alert", "projects")
    target = str(mapped.get(project) or "").strip().strip("/") if isinstance(mapped, dict) else ""
    if target and (rec := _jobalert_page(target, reg)):
        return {**rec, "via": f"{project} is mapped to {rec['key']} by [job_alert.projects]"}, None
    recs = _prj.refs(project, reg)
    if len(recs) > 1:
        return None, (409, {"error": f"{project} names several project pages ({', '.join(r['key'] for r in recs)}), so the item would go to a guess; send the full key of the one that owns the job, or pin it with the `[job_alert.projects]` map"})
    if recs:
        return recs[0], None
    if "/" not in project:
        return None, None
    fold = project.replace("/", "-").casefold()
    keys = [k for k, e in sorted(reg.items()) if isinstance(e, dict) and str(e.get("type") or "").strip().lower() == "project" and _prj.page_active(e) and _prj.name_line(e).casefold() == fold
            and not _prj.is_sub_page(k, reg, e)]
    recs = [r for r in (_jobalert_page(k, reg) for k in keys) if r]
    if len(recs) > 1:
        return None, (409, {"error": f"{project} is the project name of several pages ({', '.join(r['key'] for r in recs)}), so the item would go to a guess; send the full key of the one that owns the job, or pin it with the `[job_alert.projects]` map"})
    return ({**recs[0], "via": f"{project} is the project name of {recs[0]['key']}"}, None) if recs else (None, None)


def _jobalert_project(project: str) -> tuple[dict[str, Any] | None, str, tuple[int, dict[str, Any]] | None]:
    """The project the item is filed under -> (its record, why it is the general project's instead or "", None), or (None, "", the refusal). A project text names its page by the instance's label map, a page key or a
    `scope/project` label (`_jobalert_resolve`). A `-` or a project this server has no page for is the general project's: the page [job_alert] fallback_project names (none by default: an instance sets it); with that missing,
    or naming no page, nothing can be filed and the caller is told (409). A text that names several pages is refused (409) too: the caller names the one it means by its full key."""
    why = ""
    try:
        reg = _registry("projects")
        rec, bad = _jobalert_resolve(project, reg) if project != "-" else (None, None)
        if bad:
            return None, "", bad
        if rec:
            return rec, "", None
        why = f"{project} is no project page here" if project != "-" else "the job names no project"
        general = str(_cfg.get("job_alert", "fallback_project") or "").strip()
        recs = _prj.refs(general, reg) if general else []
    except ValueError as e:
        return None, "", (503, {"error": f"the project record cannot be read right now, nothing was filed: {e}"})
    if len(recs) != 1:
        return None, "", (409, {"error": f"{why}, and " + (f"the general project {general} is {'no project page' if not recs else 'ambiguous'} in the registry" if general else "no general project is set") + ", so there is nobody to file under; set [job_alert] fallback_project to a project page"})
    return recs[0], f"{why}, so this is under {recs[0]['key']}'s builder", None


def _jobalert_text(unit: str, host: str, meta: dict[str, Any], machine: str) -> str:
    """The description, from what the item's metadata holds: the failed runs' times, their count, the note on where it was filed. Made again from the metadata at every failure, so it is never out of step with it."""
    runs = [str(t) for t in meta.get("job_alert_runs") or []]
    lines = [f"{unit} on {host} ended a scheduled run in failure", f"Failed runs since this item opened: {int(meta.get('job_alert_count') or len(runs))}"]
    lines += [f"Failed run at {_jobalert_when(t)}" for t in runs[-_JOBALERT_SHOWN:]]
    if meta.get("job_alert_note"):
        lines.append(str(meta["job_alert_note"]))
    lines.append(f"To do: read the journal of {unit} on {host}, fix the cause; the next successful run closes this item")
    lines.append(f"Opened by {_JOBALERT_LABEL} (a script on {machine})")
    return _terminal._terminal_bullets(*lines)


def _jobalert_failed_post(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py job-failed <unit> <host> <ISO-Z time> <project>`: a scheduled job ended a run in failure on a machine.
    body: unit, host, time (ISO UTC, the failing run's), project (a page key, a `scope/project` label, or `-` for none): all text, nothing else is taken.
    One open item per (unit, host), filed through create_item (the create tool's own code: the subject, description and next gates, the project page, the GitHub mirror; a refusal is the tool's text, 400), marked
    metadata.job_alert = "<unit> on <host>". The mover is the project's builder (agents._builder_agent), named in needs and told once, at the create; the creator is the project's front agent (its -main
    first); a project with no builder is moved by that -main agent and says so. A `-` or a project this server has no page for goes to the general project ([job_alert] fallback_project: the page that holds it; none by default) and
    says so; with none set or no such page, 409. The item says which job, which machine, the time of the failed run, how many failed runs since it opened and what to do. While an item with the mark is open the call adds the
    run's time and counts it (a time already on the item counts once, so a call sent twice is one failure) and files nothing; with none open, a time no later than the latest success that closed an item of the mark is that item's (`seen`), so a
    retry or a call that came late opens nothing. The time is kept as one spelling (UTC, the fraction only when not zero) and may not be later than now plus 5 minutes (400). The row owes no page. The creator reads `job alert (a script on <machine>)`.
    -> (200, {item, unit, host, project, mover, owner, action: opened | added | seen, failures, fallback}); 400 a check, 409 no front agent, no project to file under or a key or label of several pages, 503 the project record cannot be read."""
    got, bad = _jobalert_check(body, ("unit", "host", "time", "project"))
    if bad:
        return bad
    unit, host, when, project = got["unit"], got["host"], got["time"], got["project"]
    mark, by = _jobalert_mark(unit, host), f"{_JOBALERT_LABEL} (a script on {machine})"
    try:
        with _JOBALERT_LOCK:         # the look for an open item and the write that follows are one step, so two calls for one job file one item
            _writes.QUESTION.on = True      # the job's own words are not judged for alarming ones: a script's item must not be lost on a wording refusal
            _writes.TERMINAL_ROW.on = True  # a script's notification: it owes no page, and the builder is told at the create, by the needs notice
            try:
                found = _jobalert_open_items(mark)
                if found:
                    return _jobalert_add(found[0], unit, host, when, machine)
                last_gid, last_ok = _jobalert_last_ok(mark)
                if last_ok is not None and _jobalert_instant(when) <= last_ok:      # a failure no later than the success that closed the last item (a retry, a call that came late): that item had it
                    return 200, _jobalert_answer(last_gid, unit, host, "seen")
                return _jobalert_open(project, unit, host, when, machine, by, mark)
            finally:
                _writes.QUESTION.on = _writes.TERMINAL_ROW.on = False
    except ToolError as e:
        return 400, {"error": str(e)}


def _jobalert_answer(gid: str, unit: str, host: str, action: str) -> dict[str, Any]:
    meta = _svcstore._load(gid).get("metadata") or {}
    return {"item": _gh.shown(gid), "unit": unit, "host": host, "project": str(meta.get("project") or ""), "mover": _sr._session_label(str(meta.get("mover") or "")),
            "owner": _sr._session_label(str(meta.get("owner") or "")), "action": action, "failures": int(meta.get("job_alert_count") or 0), "fallback": bool(meta.get("job_alert_fallback"))}


def _jobalert_add(gid: str, unit: str, host: str, when: str, machine: str) -> tuple[int, dict[str, Any]]:
    """A failure of a job whose item is open: the run's time joins the item (the count, the description) unless it is on the item already (a call sent twice)."""
    with _writes.ITEM_LOCK:
        item = _svcstore._load(gid)
        meta = item.setdefault("metadata", {})
        runs = [str(t) for t in meta.get("job_alert_runs") or []]
        at = _jobalert_instant(when)
        seen = any(_jobalert_instant(t) == at for t in runs) or (len(runs) >= _JOBALERT_KEEP and at < _jobalert_instant(runs[0]))      # a time older than every one kept is a time the item has had
        if seen:
            return 200, _jobalert_answer(gid, unit, host, "seen")
        meta["job_alert_runs"] = sorted([*runs, when], key=lambda t: _jobalert_instant(t))[-_JOBALERT_KEEP:]
        meta["job_alert_count"] = int(meta.get("job_alert_count") or len(runs)) + 1
        _writes.save(gid, item, note="job alert: another failed run")      # the metadata first: the description below is made from it, so a refusal of the description leaves a count that is right
    desc = _jobalert_text(unit, host, meta, machine)
    _update_svc._update(gid, description=desc, sender=f"{_JOBALERT_LABEL} (a script on {machine})")
    return 200, _jobalert_answer(gid, unit, host, "added")


def _jobalert_open(project: str, unit: str, host: str, when: str, machine: str, by: str, mark: str) -> tuple[int, dict[str, Any]]:
    rec, why, bad = _jobalert_project(project)
    if bad:
        return bad
    assert rec is not None
    key = rec["key"]
    front = sorted(_item_read._hub_sessions(key)[3], key=lambda n: (not n.endswith("-main"), n))
    if not front:
        return 409, {"error": f"{key} lists no front agent (a user-facing agent under `agents:` on its page, or its hub's), so there is nobody to keep the item; a front agent lists itself first (client.py post project-agent)"}
    owner = front[0]
    builder = _agents._builder_agent(key)
    mover = builder or owner
    notes = [why] if why else ([str(rec["via"])] if rec.get("via") else [])
    if not builder:
        notes.append(f"{key} lists no builder, so this is with {owner}, its front agent")
    meta: dict[str, Any] = {"job_alert_runs": [when], "job_alert_count": 1, "job_alert_note": "; ".join(notes)}
    desc = _jobalert_text(unit, host, meta, machine)
    pfx_, tail_ = _terminal._terminal_subject_prefix(str(rec.get("scope") or "")), f" failed on {host}"
    unit_ = _svcstore._shown_ids(unit)
    room_ = (_subject_max() - len(pfx_) - len(tail_)) if _subject_max() else 0      # a long unit name is cut so the server's own subject is never refused
    subject = f"{pfx_}{_fit(unit_, room_) if 8 <= room_ < len(unit_) else unit_}{tail_}"
    if _subject_max():
        subject = _fit(subject, _subject_max())
    nxt = _fit(f"{mover}: read the journal of {unit} on {host}, fix the cause; the next successful run closes this item", _next_line_max())
    extra: dict[str, Any] = {"job_alert": mark, "job_alert_unit": unit, "job_alert_host": host, **meta, "job_alert_fallback": bool(why or not builder)}
    gid, _reply = _create_svc.create_item(subject=subject, description=desc, project=key, owner=owner, next=nxt, needs=[builder] if builder else "", priority="p2", mover=mover, by=by, extra=extra)
    return 200, _jobalert_answer(gid, unit, host, "opened")


def _jobalert_ok_post(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py job-ok <unit> <host> <ISO-Z time>`: a scheduled job's run succeeded. body: unit, host, time (ISO UTC): all text, nothing else is taken.
    Closes the open item of (unit, host) through the update tool's own close (outcome done, the run's time as the reason within [close] reason_max, the end state in outcome_text). With no open item it does nothing and
    answers 200 (`closed` empty); so does a time older than the latest failed run the item holds (a success sent late, after a newer failure opened it, is no news about that failure). A call sent twice closes once.
    -> (200, {unit, host, closed: [ids as shown], note}); 400 a check."""
    got, bad = _jobalert_check(body, ("unit", "host", "time"))
    if bad:
        return bad
    unit, host, when = got["unit"], got["host"], got["time"]
    mark, by = _jobalert_mark(unit, host), f"{_JOBALERT_LABEL} (a script on {machine})"
    done: list[str] = []
    held = ""
    try:
        with _JOBALERT_LOCK:
            _writes.QUESTION.on = _writes.TERMINAL_ROW.on = True
            try:
                for gid in _jobalert_open_items(mark):
                    runs = [str(t) for t in (_svcstore._load(gid).get("metadata") or {}).get("job_alert_runs") or []]
                    if runs and _jobalert_instant(when) < max(_jobalert_instant(t) for t in runs):      # sent for a success that is older than a failed run this item holds
                        held = f"the success at {when} is older than the item's latest failed run; the item stays open"
                        continue
                    outcome = _terminal._terminal_bullets(f"{unit} on {host} ran successfully at {_jobalert_when(when)}", f"Closed by {_JOBALERT_LABEL} (a script on {machine}): the job's next run succeeded")
                    _update_svc._update(gid, outcome_text=outcome, status="completed", outcome="done", reason=_fit(f"the next run of {unit} on {host} succeeded at {_jobalert_when(when)}", _close_reason_max()), sender=by)
                    with _writes.ITEM_LOCK:      # the success is kept on the closed item: a failure no later than it is that item's, and opens nothing
                        item = _svcstore._load(gid)
                        item.setdefault("metadata", {})["closed_by_ok_at"] = when
                        _writes.save(gid, item, note="job alert: the run that closed it")
                    done.append(_gh.shown(gid))
            finally:
                _writes.QUESTION.on = _writes.TERMINAL_ROW.on = False
    except ToolError as e:
        return 400, {"error": str(e)}
    return 200, {"unit": unit, "host": host, "closed": done, "note": "" if done else (held or f"no open item for {_jobalert_mark(unit, host)}; nothing was closed")}
