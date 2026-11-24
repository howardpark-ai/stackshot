"""catches.py: `client.py post catch`, the record of a hook's catches, and the held word to the project's builder.

A plugin hook of a front agent's pane notices a turn that signed off with a no-ask phrase after a turn a trigger started (a notice, a message, a script's line), and posts that catch here. The server keeps one
line per catch in `<paths.state>/catches/<YYYY-MM>.jsonl` (a month by the catch's day in the instance timezone), modelled on the call log (core/call_log.py): an append under one lock, one file a month, a line
that does not parse skipped on read. tools/catch_report.py reads the lines for its daily count.

The body is `{hook, id, t, pane, kind, sender, outcome, first}`, all text: `hook` the hook's name, `id` the catch's own id (a replay of the same id is safe: it is answered ok with `duplicate: true` and
written once), `t` the time of the catch (ISO with its offset or Z, from Jan 1st 2020 to two days ahead of now: any other time is a 400), `pane` the front agent's session, `kind` how the turn that began it was started (`notice`, `message`, `script`, any other word), `sender` the
raw sender of that turn, `outcome` what the hook did, `first` the first words of the reply (folded to one line, clipped to 200 characters, never refused for its length). Every other field is one line of printable text: a control character, a line or paragraph separator (U+2028, U+2029, U+0085), a tab or any other character
`str.isprintable()` refuses is a 400 that names the field (the file is read split on newline only, so none of them can cut a line in two). A line adds `source`, `project` and `day`:

  source    worked out here, never sent by the hook: one of SOURCES, from the raw sender, the kind and the roles registry (anchors.session_roles): `router notice` (kind notice, router or router-notice, in any case,
            with a space or an underscore for the dash), `script` (kind script, or a sender that says it is a script), `stackshot message` (a sender that is the instance's own name, [instance] name, alone or
            followed by a space and more: `stackshot`, `stackshot audit`; never `stackshot-builder`, which is a session's name), `background-agent hand-back` (a sender the registry lists as a background
            agent), `front peer` (a sender it lists as a front agent), else `other`
  project   the project page of the pane's agent in the registry, else of the sender, else ""
  day       the day of `t` in the instance timezone, YYYY-MM-DD

The first catch of an hour for one pane and sender (the UTC hour of `t`, so an hour that a clock change repeats is two hours) sends one held fyi to the project's builder (service/agents.py: the background agent whose
mandate builds): one line of fixed words and the fields with their square brackets and any `needs:` taken out, so no mark of the owner's can stand in it, saying what was caught and the time in the instance
timezone. It is handed to the builder only by the hold itself (service/telling.py `hold_notice`: the builder's hook fetches held lines): it is never pushed as a turn, so when it cannot be held (the hook does not
fetch, the hold is off, the write failed) nothing is sent and `told` is empty. At most FYI_PER_BUILDER (10) fyis go to one builder in an hour of the clock, whatever the panes and senders (counted in memory: a
restart counts again). A project with no builder, a send that could not be held or one over the cap loses nothing: the line is written first.

A service module: it reads the config, the roles and the clock, writes its own log and sends through the message path. The route that calls it (`_client_post`) is the surface's. The id is looked up in the month file of `t`'s day only: a replay must send the same `t` (the hook keeps it with the id).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.fleet import sessions_registry as _sr
from stackshot.service import agents as _agents
from stackshot.service import owner_words as _owner_words
from stackshot.service import telling as _telling
from stackshot.waits import held as _held

SOURCES = ("router notice", "stackshot message", "background-agent hand-back", "front peer", "script", "other")
FIELDS = ("hook", "id", "t", "pane", "kind", "sender", "outcome", "first")
REQUIRED = ("hook", "id", "t", "pane", "kind")           # the others may be empty text
LIMITS = {"hook": 80, "id": 200, "t": 40, "pane": 120, "kind": 40, "sender": 300, "outcome": 120}      # characters; `first` is clipped to FIRST_MAX instead of refused
FIRST_MAX = 200
FYI_SENDER = "stackshot catch log"
_LOCK = threading.Lock()
_NOTICE_KINDS = frozenset({"notice", "router", "router-notice"})
_SCRIPT_SENDER = re.compile(r"\ba script\b|^script\b|^machine:", re.I)       # "<label> via a script on <machine>", "script: x", the route's own "machine:<name>"
T_MIN = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)      # a catch's `t` is from here ...
T_AHEAD = dt.timedelta(days=2)                                # ... to this far ahead of now: a stray time makes no stray month file
FYI_PER_BUILDER = 10                                          # held fyis one builder is sent in an hour of the clock, whatever the panes and senders
_BUDGET: dict[tuple[str, str], int] = {}                      # (builder, UTC hour of the clock) -> fyis sent; in memory


def _ord(n: int) -> str:
    return f"{n}th" if 10 <= n % 100 <= 20 else f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def shown_day(d: dt.date) -> str:
    """A date as a person reads it: Mon Nov 2nd."""
    return f"{d:%a %b} {_ord(d.day)}"


def shown_time(when: dt.datetime) -> str:
    """A time as a person reads it, in the instance timezone: Mon Nov 2nd 14:05 (+04)."""
    z = when.astimezone(_cfg.tz())
    return f"{shown_day(z.date())} {z:%H:%M} ({_cfg.tz_abbr(z)})"


def _file(day: str) -> Path:
    return _cfg.state("catches") / (day[:7] + ".jsonl")


def _now() -> float:
    return time.time()


def _is_server_label(sender: str) -> bool:
    """Is the sender the instance's own name ([instance] name), alone or followed by a space and more (`stackshot`, `stackshot audit`)? A name that only begins with it (`stackshot-builder`, `stackshotx`) is not."""
    s, n = sender.casefold(), _inst.NAME.casefold()
    return s == n or s.startswith(n + " ")


def _fold(text: Any) -> str:
    return " ".join(str(text or "").split())


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _parse_t(text: str) -> dt.datetime | None:
    """`t` as an aware time: ISO 8601 with an offset or Z. None for any other text (a time with no offset is not guessed at)."""
    try:
        when = dt.datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    return when if when.tzinfo is not None and when.utcoffset() is not None else None


def _role_of(who: str) -> tuple[str, str]:
    """A session's role and project in the roles registry -> ("front" | "back" | "", the project key); ("", "") when no page lists it or the roles cannot be read."""
    who = who.strip()
    if not who:
        return "", ""
    try:
        roles = _anc.session_roles()
        name = _sr._role_name(roles, who) or next((n for n in roles if n.casefold() == who.casefold()), "")
        r = roles.get(name) or {}
        return (str(r.get("role") or "") if r.get("role") in ("front", "back") else ""), str(r.get("project") or "")
    except Exception as e:  # noqa: BLE001 — a catch is recorded without its class rather than lost
        print(f"catches: roles not read ({e.__class__.__name__}: {e}); the source is worked out without them", file=sys.stderr, flush=True)
        return "", ""


def source_of(sender: str, kind: str) -> tuple[str, str]:
    """The class of the turn that began a catch, from the raw sender, the kind and the roles registry -> (one of SOURCES, the project of a sender the registry lists, else "").
    In order: a notice kind is a router notice; a script kind or a sender that says it is a script is a script; a sender that is the server's own name is a stackshot message;
    a background agent of the registry is a background-agent hand-back, a front agent a front peer; anything else is other."""
    sender, k = _fold(sender), re.sub(r"[\s_]+", "-", _fold(kind).casefold())
    role, project = _role_of(sender)
    if k in _NOTICE_KINDS:
        return "router notice", project
    if k == "script" or _SCRIPT_SENDER.search(sender):
        return "script", project
    if _is_server_label(sender):
        return "stackshot message", project
    if role == "back":
        return "background-agent hand-back", project
    if role == "front":
        return "front peer", project
    return "other", project


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    try:
        lines = path.read_bytes().decode("utf-8", "replace").split("\n")      # newline only: a line separator inside a field (U+2028, U+0085) never cuts a line
    except OSError:
        return
    for ln in lines:
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            yield row


def read_day(day: str) -> list[dict[str, Any]]:
    """The lines of one day (YYYY-MM-DD, instance timezone), in the order they were written."""
    return [r for r in _rows(_file(day)) if r.get("day") == day]


def _hour(when: dt.datetime) -> str:
    """The hour of an instant: its UTC hour, so the hour a clock change repeats is two hours, never one."""
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H")


def _bad(field: str, why: str) -> tuple[int, dict[str, Any]]:
    return 400, {"error": f"{field} = {why}"}


def _clean(body: dict[str, Any]) -> tuple[dict[str, str], tuple[int, dict[str, Any]] | None]:
    """The body's fields as text -> (fields, None), or ({}, the 400 that names the first fault)."""
    got: dict[str, str] = {}
    for f in FIELDS:
        v = body.get(f, "")
        if not isinstance(v, str):
            return {}, _bad(f, "text (a JSON string)")
        if f != "first" and not v.isprintable():
            return {}, _bad(f, "one line of printable text: no control character, tab, line or paragraph separator")
        got[f] = v.strip() if f != "first" else _fold("".join(c if c.isprintable() else " " for c in v))
        if f in REQUIRED and not got[f]:
            return {}, _bad(f, {"hook": "the hook's name", "id": "the catch's own id (a replay of it is safe)", "t": "the time of the catch, ISO 8601 with its offset or Z",
                                "pane": "the front agent's session that signed off", "kind": "how the turn that began it was started (notice, message, script, ...)"}[f] + "; it is required")
        if f in LIMITS and len(got[f]) > LIMITS[f]:
            return {}, _bad(f, f"at most {LIMITS[f]} characters ({len(got[f])} now)")
    got["first"] = _clip(got["first"], FIRST_MAX)
    return got, None


FYI_FIRST = 40          # characters of the reply's first words in the held line: the line is a short note with its own prefix (`[stackshot message] from <sender>: `), not the reply; the pane has the reply


def _plain(text: Any) -> str:
    """A field as it stands in the fyi line: no square bracket and no `needs:`, so no mark of the owner's (`[for <owner>]`, `needs: decision`: waits/held.py) can be written by a hook into it."""
    return _fold(re.sub(r"(?i)needs\s*:", "needs", re.sub(r"[\[\]]", "", str(text or ""))))


def _fyi_line(row: dict[str, Any], when: dt.datetime) -> str:
    who = _plain(row["sender"]) or "no sender"
    line = (f"{_plain(row['hook'])} caught {_plain(row['pane'])} at {shown_time(when)}: signed off with no ask after a {row['source']} turn ({who})"
            + (f": \"{_clip(_plain(row['first']), FYI_FIRST)}\"" if row["first"] else ""))
    return _owner_words._no_ping(_fold(line))


def _tell_builder(row: dict[str, Any], when: dt.datetime) -> str:
    """The held fyi to the builder of the catch's project -> the builder's name, "" when none was held (no project, no builder, a builder whose hook does not fetch held lines, a hold that is off or failed, a builder
    over its hour's cap: said on stderr when it failed, never raised). It goes through the hold alone, never as a turn: `telling.hold_notice` answers False for anything it cannot hold and sends nothing."""
    try:
        to = _agents._builder_agent(row["project"]) if row["project"] else ""
        if not to:
            return ""
        text = f"[stackshot message] from {FYI_SENDER}: {_fyi_line(row, when)}"        # the envelope a held message carries (messaging._message): what the builder reads
        if _held._owner_mark().search(text):         # the line is fixed words and cleaned fields: this is a guard, never a way the owner's mark reaches a builder's next turn
            return ""
        key = (to, time.strftime("%Y-%m-%d %H", time.gmtime(_now())))
        with _LOCK:
            if _BUDGET.get(key, 0) >= FYI_PER_BUILDER:
                return ""
            for old in [k for k in _BUDGET if k[1] != key[1]]:
                del _BUDGET[old]
            _BUDGET[key] = _BUDGET.get(key, 0) + 1
        held = False
        try:
            held = _telling.hold_notice(to, text, "fyi", project=row["project"], sender=FYI_SENDER)
        finally:
            if not held:                      # a hold that was refused or failed takes nothing from the hour's cap
                with _LOCK:
                    _BUDGET[key] = max(0, _BUDGET.get(key, 1) - 1)
        if not held:
            return ""
        return to
    except Exception as e:  # noqa: BLE001 — the catch is written; a word to the builder that failed is not worth a lost catch
        print(f"catches: the fyi to the builder of {row.get('project')} was not sent ({e.__class__.__name__}: {str(e)[:200]})", file=sys.stderr, flush=True)
        return ""


def _catch_post(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post catch` / POST /client/catch: one catch of a hook, `{hook, id, t, pane, kind, sender, outcome, first}` (see the module's text) -> (200, {ok, duplicate, id, source, project, day, told}) or (400, {error}).
    The line is written once per id (the month of its day is searched: a replay is answered ok with duplicate true and written, and told, no more). `told` is the builder the held fyi went to, "" when
    none was held: the first catch of an hour for one pane and sender holds one, a project with no builder, a builder that does not fetch held lines or one over its hour's cap none."""
    f, bad = _clean(body)
    if bad:
        return bad
    when = _parse_t(f["t"])
    if when is None:
        return _bad("t", "the time of the catch, ISO 8601 with its offset or Z (2026-11-23T14:05:00+09:00); a time with no offset is not taken")
    try:
        day = when.astimezone(_cfg.tz()).date().isoformat()
    except (OverflowError, ValueError):            # a time at the calendar's edge, which the instance timezone cannot write
        return _bad("t", "a time this server can write in its own timezone (ISO 8601 with its offset or Z, from Jan 1st 2020 to two days ahead of now)")
    if not T_MIN <= when <= dt.datetime.fromtimestamp(_now(), dt.timezone.utc) + T_AHEAD:
        return _bad("t", "a time from Jan 1st 2020 to two days ahead of now")
    source, sender_project = source_of(f["sender"], f["kind"])
    project = _role_of(f["pane"])[1] or sender_project
    row = {**f, "source": source, "project": project, "day": day}
    path, hour = _file(day), _hour(when)
    with _LOCK:
        first_of_hour = True
        for old in _rows(path):
            if old.get("id") == f["id"]:
                return 200, {"ok": True, "duplicate": True, "id": f["id"], "source": str(old.get("source") or ""), "project": str(old.get("project") or ""), "day": str(old.get("day") or day), "told": ""}
            if old.get("pane") == f["pane"] and old.get("sender") == f["sender"] and first_of_hour:
                t0 = _parse_t(str(old.get("t") or ""))
                if t0 is not None and _hour(t0) == hour:
                    first_of_hour = False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError as e:
            return 503, {"error": f"the catch could not be written ({e.__class__.__name__}); send it again, a replay of its id is safe"}
    told = _tell_builder(row, when) if first_of_hour else ""
    return 200, {"ok": True, "duplicate": False, "id": f["id"], "source": source, "project": project, "day": day, "told": told}
