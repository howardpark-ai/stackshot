"""event_waits.py — a wait on a fleet event (wait_kind=event), and how its event is read and matched.

The item model's waits name what they wait on (model.py: time | anchor | item | relay | event). An item whose mover is waiting on something that happens in the fleet (a release running, a
fleet op finishing, a recycle, a scheduled job's next run) used to be stored as work, and so read as idle after ten minutes with no turn running, got nagged by the stall pass and,
at its last step, raised to the owner. An event wait is the honest store: the wait names the event, the server watches for it, and the idle and stall clocks do not run while it is open.

The event is a short phrase kept in the item's `wait_event` (the field an anchor or relay wait already uses for its own event), canonical form below. The kinds, each an event the server
is told of once, by code:

    pr_released <owner/repo#n>        the pull request is merged AND live: release.sh saw main's full run pass on its merge (client.py released), checked against the checkout (a [released.repos] repository's: its HEAD).
                                      Only this repository's and those of [released.repos] are released
    pr_merged <owner/repo#n>          the pull request is merged (GitHub says so; the server reads it at the done check's own pace)
    recycle [<machine>]               a recycle (or a reboot) of the fleet's panes finished: sala's end-of-recycle hook (client.py recycled). With a machine, only that machine's. A recycle
                                      wait never asks for a recycle (it is not metadata.recycle, which /client/recycle-wanted counts): it waits for the next one
    fleet_op <verb|any|many> [<machine>]   a fleet op ended: sala's result (client.py event --kind fleet_op). `verb` is the op (lane, provision, update …), `any` every op, `many` every op over
                                      more than one session (the event carries its session count)
    job_run <name>                    a scheduled job ran: its own report (client.py event --kind job_run --name <name>)

A bare #n or n names a pull request of this repository. The wait needs a backstop date beside the event (ask_by or a wake) that is after now (a day falls due at 00:00 in the instance timezone): the day the item comes back anyway if the event never came.
Live today (`live`): the PR kinds, recycle, and every fleet_op form (any verb, `any`, `many`): the fleet tool reports the end of every op with `client.py event --kind fleet_op`. Nothing posts `client.py event --kind job_run` yet, so a job_run wait turns only on its backstop.

Pure functions of strings and dicts: no server import, no clock read, so the server, the guards, the renderer and the tests share one copy of what an event is."""
from __future__ import annotations

import re
from typing import Any, NamedTuple

PR_RELEASED, PR_MERGED, RECYCLE, FLEET_OP, JOB_RUN = "pr_released", "pr_merged", "recycle", "fleet_op", "job_run"
KINDS = (PR_RELEASED, PR_MERGED, RECYCLE, FLEET_OP, JOB_RUN)
PR_KINDS = (PR_RELEASED, PR_MERGED)
REPORTED = (RECYCLE, FLEET_OP, JOB_RUN)             # the kinds a machine may report with client.py event (the PR kinds the server verifies for itself)
FORMS = "pr_released <owner/repo#n> | pr_merged <owner/repo#n> | recycle [<machine>] | fleet_op <verb | any | many> [<machine>] | job_run <name>"
ANY, MANY = "any", "many"

_NAME = re.compile(r"[A-Za-z0-9][\w.@:-]{0,79}")
_VERB = re.compile(r"[a-z][a-z0-9_-]{0,39}")
_PR = re.compile(r"(?:(?:PR|pull request)\s*)?(?:(?P<repo>[\w.-]+/[\w.-]+)#|#)?(?P<n>\d+)", re.I)
_URL = re.compile(r"https?://github\.com/(?P<repo>[\w.-]+/[\w.-]+)/pull/(?P<n>\d+)", re.I)


class EventWaitError(ValueError):
    """An event phrase the server refuses; the message says what to pass instead."""


class Spec(NamedTuple):
    """What a wait waits for. `key`: the pull request ("owner/repo#n", or "#n" while the repository is not yet resolved), the fleet op's verb, or the job's name; `machine`: "" for any."""
    kind: str
    key: str = ""
    machine: str = ""


def parse(text: Any) -> Spec:
    """A phrase ("pr_released #7", "recycle box-1", "fleet_op many", "job_run nightly") → the Spec; EventWaitError with the forms otherwise."""
    s = " ".join(str(text or "").split())
    if not s:
        raise EventWaitError(f"an event wait names its event in wait_event: {FORMS}")
    kind, _, arg = s.partition(" ")
    kind, arg = kind.lower(), arg.strip()
    kind = FLEET_OP if kind == "sala_op" else kind          # the first name of the kind, still accepted
    if kind not in KINDS:
        raise EventWaitError(f"wait_event {s[:80]!r} is not an event the server watches. Pass one of: {FORMS}")
    if kind in PR_KINDS:
        m = _URL.fullmatch(arg) or _PR.fullmatch(arg)
        if not m:
            raise EventWaitError(f"{kind} names a pull request: {kind} <owner/repo#n> (a bare #n is this repository's, a PR URL works too); got {arg[:60]!r}")
        repo = (m.group("repo") or "").lower()
        return Spec(kind, f"{repo}#{int(m.group('n'))}")
    parts = arg.split()
    if kind == RECYCLE:
        if len(parts) > 1 or (parts and not _NAME.fullmatch(parts[0])):
            raise EventWaitError(f"recycle takes at most a machine: recycle [<machine>]; got {arg[:60]!r}")
        return Spec(kind, "", parts[0] if parts else "")
    if kind == FLEET_OP:
        if not 1 <= len(parts) <= 2 or not _VERB.fullmatch(parts[0].lower()) or (len(parts) == 2 and not _NAME.fullmatch(parts[1])):
            raise EventWaitError(f"fleet_op takes the op and at most a machine: fleet_op <verb | any | many> [<machine>] (any = every op, many = every op over more than one session); got {arg[:60]!r}")
        return Spec(kind, parts[0].lower(), parts[1] if len(parts) == 2 else "")
    if len(parts) != 1 or not _NAME.fullmatch(parts[0]):         # job_run
        raise EventWaitError(f"job_run takes the job's name: job_run <name>; got {arg[:60]!r}")
    return Spec(kind, parts[0])


def problem(text: Any) -> str:
    """Why a phrase is no event, "" when it is one (the write guard's test)."""
    try:
        parse(text)
        return ""
    except EventWaitError as e:
        return str(e)


def resolved(spec: Spec, own_repo: str, canon: Any = None) -> Spec:
    """A pull-request spec with its repository filled in (a bare #n is `own_repo`'s) and run through `canon` (the server's [github.moved] table); the others come back as they are."""
    if spec.kind not in PR_KINDS:
        return spec
    repo, _, n = spec.key.partition("#")
    repo = repo or own_repo
    if not repo:
        raise EventWaitError(f"{spec.kind} #{n}: this server has no GitHub repository of its own to read a bare #{n} against; name the pull request as <owner/repo>#{n}")
    return Spec(spec.kind, f"{canon(repo) if canon else repo.lower()}#{n}")


def text(spec: Spec) -> str:
    """The canonical phrase, as it is stored."""
    return " ".join(x for x in (spec.kind, spec.key, spec.machine) if x)


def live(spec: Spec) -> bool:
    """Does something tell the server of this event today? The PR kinds (the server reads them), a recycle (the fleet tool's end-of-recycle hook) and every fleet op (the fleet tool reports the end of each
    with `client.py event --kind fleet_op`: any verb, `any`, `many`). `job_run` needs a `client.py event` that nothing posts yet: such a wait turns only on its backstop."""
    return spec.kind in PR_KINDS or spec.kind in (RECYCLE, FLEET_OP)


def pr_number(spec: Spec) -> int:
    return int(spec.key.rpartition("#")[2]) if spec.kind in PR_KINDS else 0


def words(phrase: Any) -> str:
    """The event as a person reads it, for the item page, get and the brief ("PR #7 live", "the next recycle of box-1"); a phrase that is no event comes back as written."""
    try:
        sp = parse(phrase)
    except EventWaitError:
        return " ".join(str(phrase or "").split())
    if sp.kind in PR_KINDS:
        return f"PR {sp.key if sp.key.startswith('#') else '#' + sp.key.rpartition('#')[2]} " + ("live" if sp.kind == PR_RELEASED else "merged") + ("" if sp.key.startswith("#") else f" ({sp.key.rpartition('#')[0]})")
    if sp.kind == RECYCLE:
        return "the next recycle" + (f" of {sp.machine}" if sp.machine else "")
    if sp.kind == FLEET_OP:
        what = {ANY: "the next fleet op", MANY: "the next fleet op over more than one session"}.get(sp.key, f"the next fleet {sp.key}")
        return what + (f" on {sp.machine}" if sp.machine else "")
    return f"the next run of job {sp.key}"


# ------------------------------------------------------------------------------------------------------ the events
def event(kind: str, key: str = "", machine: str = "", verb: str = "", name: str = "", sessions: int | None = None, result: str = "", what: str = "") -> dict[str, Any]:
    """An event the server was told of, in the form `matches` reads. `what` is its words for the mover ("PR #7 is live …")."""
    return {"kind": kind, "key": key, "machine": machine, "verb": verb.lower(), "name": name, "sessions": sessions, "result": result, "what": what}


def matches(spec: Spec, ev: dict[str, Any]) -> bool:
    """Does the event end a wait for `spec`? A pull request's key must be the same; a recycle matches any machine unless the spec names one; a fleet op by its verb (`any` every op, `many` every op
    reported over more than one session) and its machine when the spec names one; a job by its name."""
    if ev.get("kind") != spec.kind:
        return False
    if spec.kind in PR_KINDS:
        return ev.get("key") == spec.key
    if spec.machine and ev.get("machine") != spec.machine:
        return False
    if spec.kind == RECYCLE:
        return True
    if spec.kind == FLEET_OP:
        if spec.key == ANY:
            return True
        if spec.key == MANY:
            n = ev.get("sessions")
            return isinstance(n, int) and n > 1
        return ev.get("verb") == spec.key
    return ev.get("name") == spec.key


def arrival(ev: dict[str, Any]) -> str:
    """What the mover is told arrived: the event's own words when it carries them, else a plain line built from it."""
    if ev.get("what"):
        return " ".join(str(ev["what"]).split())
    k = ev.get("kind")
    if k in PR_KINDS:
        n = str(ev.get("key") or "").rpartition("#")[2]
        return f"PR #{n} is " + ("live" if k == PR_RELEASED else "merged")
    if k == RECYCLE:
        return "a recycle finished" + (f" on {ev['machine']}" if ev.get("machine") else "") + (f" ({ev['result']})" if ev.get("result") else "")
    if k == FLEET_OP:
        n = ev.get("sessions")
        return f"fleet op {ev.get('verb') or ''} finished" + (f" on {ev['machine']}" if ev.get("machine") else "") + (f", {n} sessions" if isinstance(n, int) else "") + (f" ({ev['result']})" if ev.get("result") else "")
    return f"job {ev.get('name') or ''} ran" + (f" ({ev['result']})" if ev.get("result") else "")


def event_from_report(body: dict[str, Any]) -> dict[str, Any]:
    """A machine's report (client.py event) → the event, or EventWaitError. kind recycle | fleet_op | job_run; fleet_op needs a verb, job_run a name; sessions a whole number when given."""
    kind = str(body.get("kind") or "").strip().lower()
    kind = FLEET_OP if kind == "sala_op" else kind          # the first name of the kind, still accepted
    if kind not in REPORTED:
        raise EventWaitError(f"kind is one of {' | '.join(REPORTED)} (a pull request's merge and release the server sees for itself); got {kind[:40]!r}")
    machine = str(body.get("machine") or "").strip()
    verb, name = str(body.get("verb") or "").strip().lower(), str(body.get("name") or "").strip()
    if machine and not _NAME.fullmatch(machine):
        raise EventWaitError(f"machine {machine[:40]!r} is not a machine name")
    if kind == FLEET_OP and not _VERB.fullmatch(verb):
        raise EventWaitError("a fleet_op report names the op: verb (lane, provision, update …)")
    if kind == JOB_RUN and not _NAME.fullmatch(name):
        raise EventWaitError("a job_run report names the job: name")
    raw = body.get("sessions")
    sessions: int | None = None
    if raw not in (None, ""):
        try:
            sessions = int(raw)
        except (TypeError, ValueError):
            raise EventWaitError("sessions is a whole number")
        if sessions < 0:
            raise EventWaitError("sessions is a whole number")
    return event(kind, "", machine, verb if kind == FLEET_OP else "", name if kind == JOB_RUN else "", sessions, " ".join(str(body.get("result") or "").split())[:80], " ".join(str(body.get("text") or "").split())[:240])
