"""client_api.py: the client API, /client/...: what a machine's puller and a session's hooks call (write, for-you seen, item watch and the read calls of /client/{what}).

`_client_post` is the POST dispatcher of /client/{what}: one branch per `what`, each handing the body to the service that does the work (service/recycle.py, released.py, question.py, terminal_prompt.py, job_gap.py, item_open.py and the others) and answering (status, JSON).
It is the surface's: it names the services and the status codes, and writes nothing itself. A suite that replaces a function of one of those services sets it on that module and calls `_client_post` here.

`register(mcp, *, client_get, recycle_wanted_tokens)` adds the routes to the server's `mcp` in the order they were declared in server.py. The two callables are the server's own
(`_client_get` serves the read calls, `_recycle_wanted_tokens` the tokens a poll hands out) and are looked up when a call is made, never when the routes are added."""
from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from stackshot.core import config as _cfg
from stackshot.fleet import clients as _clients, inbox as _inbox
from stackshot.fleet.clients import POLL_MAX as _POLL_MAX
from stackshot.github import ghsync as _gh
from stackshot.model.ids import _norm_id
from stackshot.projects import brains as _brains
from stackshot.router import page_debt as _page_debt
from stackshot.service import agent_names as _agent_names
from stackshot.service import contacts as _contacts
from stackshot.service import event_waits as _evwaits
from stackshot.service import foryou as _fy
from stackshot.service import handoff as _handoff
from stackshot.service import item_open as _item_open
from stackshot.service import job_gap as _job_gap
from stackshot.service import messaging as _messaging
from stackshot.service import migrations as _migrations
from stackshot.service import owner_words as _owner_words
from stackshot.service import page_debt as _pdsvc
from stackshot.service import proofs as _proofs
from stackshot.service import question as _question_svc
from stackshot.service import recycle as _recycle_svc
from stackshot.service import released as _relsvc
from stackshot.service import terminal_prompt as _terminal_prompt_svc
from stackshot.service import update as _update_svc
from stackshot.service.projects import _form_call, _new_project, _project_agent, _project_agent_mandate, _project_agent_rename, _project_agent_retire, _project_list
from stackshot.service.store import _load
from stackshot.waits import event_waits as _ew
from stackshot.waits import held as _held
from stackshot.web.publish import _publish


_client_get, _recycle_wanted_tokens = None, None      # the server's own, set by register()


_CLIENTS = _cfg.secrets("clients.json")     # {machine: {"sha256": <hex of its token>, "created": <iso>}}, written by client.py mint


def _client_machine(authorization: str) -> str:
    """The machine a client token belongs to, "" when it belongs to none. The server keeps the token's SHA-256, never the token."""
    import hashlib
    import hmac
    tok = authorization[7:].strip() if authorization[:7].lower() == "bearer " else ""
    if len(tok) < 32:
        return ""
    h = hashlib.sha256(tok.encode()).hexdigest()
    try:
        d = json.loads(Path(_CLIENTS).read_text(encoding="utf-8"))
    except Exception:
        return ""
    hit = ""
    for name, v in d.items():       # no early exit: the same work whichever entry matches
        if isinstance(v, dict) and hmac.compare_digest(str(v.get("sha256") or ""), h):
            hit = str(name)
    return hit


def _client_config() -> dict[str, Any]:
    """The instance's settings a client box's hooks need, and nothing secret: `stackshot client install --url` writes
    them into that box's config, so its nag speaks in the instance's timezone and page flavor. Values as the hooks read them."""
    def plain(v: Any) -> Any:           # what TOML may hold that JSON cannot (a bare date) goes as its text
        return v if isinstance(v, (str, int, float, bool)) else [plain(x) for x in v] if isinstance(v, list) else str(v)
    out: dict[str, Any] = {
        "instance": {k: str(_cfg.get("instance", k) or "") for k in ("name", "title", "owner", "timezone", "board_url")},
        "pages": {"flavor": _cfg.page_flavor(), "dirs": _cfg.page_dirs()},
        "paths": {"brain": str(_cfg.get("paths", "brain") or "")},
        "subject": {"prefixes": [str(p) for p in (_cfg.get("subject", "prefixes") or [])]},
        "page_gate": {str(k): plain(v) for k, v in (_cfg.get("page_gate") or {}).items()},
        "board_check": {"mode": _cfg.board_check_mode()},
        "gbrain": {"mirror_url": str(_cfg.get("gbrain", "mirror_url") or "")},
        "server": {"path": str(_cfg.get("server", "path") or "/mcp")},
    }
    if _brains.configured():    # each second brain's page rules and mirror, so a client box links its pages to the right mirror (no gbrain home: a client writes nothing)
        out["brains"] = _brains.client_entries()
    return out


def _client_post(machine: str, what: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """One write of the client API → (status, JSON). `machine` is the token's, never the body's."""
    if what == "recycled":      # the fleet tool's end-of-recycle hook: the waits-for-recycle field comes off what the recycle covered
        sk = body.get("skipped") or []
        sk = sk.split() if isinstance(sk, str) else sk
        if not isinstance(sk, list):
            return 400, {"error": "skipped is a list of session names (or one space-separated string)"}
        try:
            started = float(body.get("started") or 0)
        except (TypeError, ValueError):
            return 400, {"error": "started is an epoch in seconds"}
        kind = str(body.get("kind") or "recycle")
        if kind not in ("recycle", "reboot"):
            return 400, {"error": "kind = recycle | reboot"}
        try:
            flag_at = float(body.get("flag_at") or 0)
        except (TypeError, ValueError):
            return 400, {"error": "flag_at is an epoch in seconds"}
        return 200, _recycle_svc._recycled(machine, kind, started, str(body.get("result") or "ok"), [str(x) for x in sk], flag_at)
    if what == "recycle-due":   # a script marks a recycle as due on an item (client.py recycle-due)
        try:
            return 200, _recycle_svc._recycle_due(machine, str(body.get("item") or ""), str(body.get("pr") or ""))
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "released":      # release.sh: main's tests passed on a released merge, so the items built for that PR are settled (client.py released)
        try:
            return 200, _relsvc.released(str(body.get("pr") or ""), str(body.get("sha") or ""), bool(body.get("dry_run")))
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "event":         # a machine reports a fleet event an event wait may wait on: a recycle, a fleet op's end, a job's run (client.py event)
        try:
            ev = _ew.event_from_report({**body, "machine": body.get("machine") or machine})
        except _ew.EventWaitError as e:
            return 400, {"error": str(e)}
        woken = _evwaits.evwait_report(ev)
        return 200, {"event": _ew.arrival(ev), "woken": [_gh.shown(g) for g in woken]}
    if what == "sweep-released":   # the same rule for the PRs the running server already holds (client.py sweep-released [--dry-run])
        try:
            return 200, _relsvc.sweep_released(bool(body.get("dry_run")))
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "sweep-step-proof":   # every open step whose proof (a PR merged or released) already happened is settled (client.py sweep-step-proof [--dry-run])
        try:
            return 200, _proofs.sweep_proofs(bool(body.get("dry_run")))
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "page-debt":      # the audit run's pages stage (audit_run.py): the page-debt pass for that run, made here because the debt ledger and the page writes are this process's
        run = body.get("run")
        if not isinstance(run, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{6}", run):     # the shape audit_run._stamp_of writes
            return 400, {"error": "run = the audit run's start stamp, YYYY-MM-DD-HHMMSS"}
        try:
            deadline = float(body["deadline"]) if body.get("deadline") not in (None, "") else None
            if deadline is not None and not math.isfinite(deadline):
                raise ValueError(deadline)
        except (TypeError, ValueError):
            return 400, {"error": "deadline = an epoch in seconds (the end of the run's time budget), or left out"}
        enabled = _page_debt.enabled()
        return 200, {"enabled": enabled, "mode": _page_debt.mode() if enabled else "", "counts": _pdsvc.page_debt_pass(run=run, deadline=deadline)}
    if what == "orphan-handover":   # the audit run's hand-over of open items whose mover is gone (audit_run.py); a dry run unless the body says apply
        try:
            return 200, _handoff.orphan_handover(apply=body.get("apply") is True)
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "backfill-contact":   # every open item without a live contact gets one (client.py backfill-contact [--dry-run]); a dry run unless the body says apply
        try:
            return 200, _contacts._contact_backfill(dry=body.get("apply") is not True)
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "message":       # a script sends a message the way a session's `message` tool does
        to, text, sender = (str(body.get(k) or "") for k in ("to", "text", "sender"))
        if str(body.get("release") or "") == "green" and text.strip() and sender.strip():   # release.sh's green result: log-only (the turn rule's second build)
            try:
                res = _relsvc._release_green(to, text, sender.strip(), machine, str(body.get("pr") or ""))
            except Exception as e:  # noqa: BLE001  — what the log-only path cannot do is delivered as before, never lost
                print(f"release: log-only failed, delivering instead: {e}", file=sys.stderr, flush=True)
                res = None
            if res is not None:
                return 200, {"result": res}
        # No For you row for a failed release: release.sh's raw text told him nothing he could act on and stayed after the fix.
        # The builder gets the message below; he hears of a failure through the item it serves.
        try:
            return 200, {"result": _messaging._message(to, text, sender, f"machine:{machine}", machine, **({"fyi": True} if body.get("fyi") is True else {}))}
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "handover":      # a box's PostToolUse hook saw a SendMessage to a background agent that names an item (pages.py touch)
        to, text, sender = (str(body.get(k) or "").strip() for k in ("to", "text", "sender"))
        if not (to and text and sender):
            return 400, {"error": "to, text and sender are required: the recipient, the message and the sending session"}
        try:
            return 200, {"result": _agent_names._name_on_handover(to, text, sender, via=f"SendMessage on {machine}").strip()}
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "project-agent":     # phase A: a front agent or the keeper lists a new agent of the project (client.py post project-agent)
        try:
            return _project_agent(machine, body)
        except ValueError as e:         # the id file is damaged (projects.py raises, mints nothing and writes nothing): not recorded, say so
            return 503, {"error": f"the project record cannot be read or written right now, nothing was recorded: {e}"}
    if what == "project-agent-mandate":     # the keeper or a front agent changes the mandate line of a listed agent (client.py post project-agent-mandate)
        try:
            return _project_agent_mandate(machine, body)
        except ValueError as e:         # the id file is damaged (projects.py raises): nothing was changed
            return 503, {"error": f"the project record cannot be read right now, nothing was changed: {e}"}
    if what == "project-agent-rename":      # the form renames an agent's entry on the project's page, in place (client.py post project-agent-rename)
        try:
            return _project_agent_rename(machine, body)
        except ValueError as e:         # the id file is damaged (projects.py raises): nothing was written
            return 503, {"error": f"the project record cannot be read right now, nothing was changed: {e}"}
    if what == "project-agent-retire":      # sala retired a session; the form removes its line from the page's agents map with a timeline line, or drops its pending agent (client.py post project-agent-retire)
        try:
            return _project_agent_retire(machine, body)
        except ValueError as e:         # the id file is damaged (projects.py raises): nothing was changed
            return 503, {"error": f"the project record cannot be read right now, nothing was changed: {e}"}
    if what == "project":       # the fleet tool's New session form makes a project and its gbrain page (client.py post project)
        return _new_project(machine, body)
    if what == "project-list":  # ... and lists a hidden one again (client.py post project-list)
        return _project_list(machine, body)
    if what == "question":      # a script files a question for the owner as a needs=decision item (client.py post question)
        return _question_svc._question(machine, body)
    if what == "terminal-prompt":   # sala: a pane waiting in its terminal is a row in the owner's Your move list (client.py post terminal-prompt open | clear)
        return _terminal_prompt_svc._terminal_prompt(machine, body)
    if what == "job-gap":       # sala: a gap in a scheduled job is one item per (timer, code), moved by the owning repo's builder (client.py post job-gap open | clear)
        return _job_gap._jobgap_post(machine, body)
    if what == "item-open":     # a script opens one board item for a background agent of a project, once per marker while it is open (client.py post item-open)
        return _item_open._itemopen_post(machine, body)
    if what == "cap-words":     # tools/cap_words.py --apply: his park words already in the store, or a long wait's real-world date, recorded through the normal write path
        try:
            if "basis" in body:
                by = _owner_words._script_sender(body, machine)
                gid = _norm_id(str(body.get("item") or ""))
                out = _update_svc._update(gid, wait_basis=str(body.get("basis") or ""), sender=by)
                return 200, {"item": _gh.shown(gid), "action": "set", "result": out.splitlines()[0] if out else ""}
            return 200, _owner_words._record_cap_words(body, machine)
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "rebullet":      # tools/rebullet_descriptions.py: an open item's description rewritten as short bullets, checked for loss, through the normal write path
        try:
            return 200, _owner_words._rebullet_write(body, machine)
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "state":         # retired: the route answers 400 with the refusal naming what update takes instead (client.py post state sends nothing any more)
        try:
            return 200, _owner_words._state_write(body, machine)
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "migrate":       # tools/migrate_model.py: the migration onto the item model, planned by the script, applied here through the normal save path (begin | apply | end)
        gate = _migrations.migration_gate(machine, body)       # off by default ([model] migration), and only the named sessions on the named machines
        if gate is not None:
            return gate
        try:
            return 200, _migrations.migrate_write(body, machine)
        except ToolError as e:
            return 400, {"error": str(e)}
    if what == "register":      # a session says it exists (its SessionStart hook)
        try:
            s = _clients.register(machine, body)
        except ValueError as e:
            return 400, {"error": str(e)}
        return 200, {"ok": True, "name": s.get("name") or "", "machine": s.get("machine")}
    if what == "setup-result":  # a PC's own provisioning run ended (client.py setup-result): kept per machine, drawn on its Machines column
        ok = body.get("ok")
        if not isinstance(ok, bool):
            return 400, {"error": "ok = true (the run succeeded) or false (it failed at step, for reason)"}
        try:
            rec = _clients.setup_result(machine, ok, str(body.get("step") or ""), str(body.get("reason") or ""))
        except ValueError as e:
            return 400, {"error": str(e)}
        return 200, {"machine": machine, "setup": rec}
    if what == "seen":          # a sign of life from a registered session (its Stop hook)
        return 200, {"ok": _clients.seen(machine, str(body.get("uuid") or ""))}
    if what == "ack":           # a puller confirms what it delivered and what it could not
        d, f = body.get("delivered") or [], body.get("failed") or []
        if not (isinstance(d, list) and isinstance(f, list)):
            return 400, {"error": "delivered and failed are lists of line ids"}
        acked = _inbox.peek([str(x) for x in d])           # step 2: the lines are gone once acked; a hand-off notice among them is the delivery of its hand-off
        removed = _inbox.ack([str(x) for x in d], [str(x) for x in f])
        if acked:
            _handoff.handoff_acked(acked)
        return 200, {"removed": removed}
    if what == "held":          # a session's UserPromptSubmit hook fetches the notices held for it while it was busy (held.py); handed over once
        uuid = str(body.get("uuid") or "").lower()
        if not _clients.UUID.match(uuid):
            return 400, {"error": "uuid = the session's transcript id"}
        rec = _clients.sessions_on(machine).get(uuid)       # as drain: only a session the server holds for THIS machine, and its name is the server's record, never the request's
        if rec is None:
            return 200, {"text": "", "ids": []}
        name = str(rec.get("name") or "")
        if "ack" in body:       # the hook printed these lines: they go (until then they are leased, and offered again when the lease runs out)
            ids = body.get("ack")
            if not (isinstance(ids, list) and all(isinstance(x, str) for x in ids)):
                return 400, {"error": "ack = the list of line ids the hook printed"}
            return 200, {"removed": _held.ack(uuid, name, ids=ids)}
        _held.mark_client(uuid, name)       # this session's hook fetches held lines: from now on a notice that asks nothing of it is held (the rollout gate)
        text, ids = _held.lease(uuid, name)
        return 200, {"text": text, "ids": ids}
    if what == "drain":         # no puller on the machine: a session's own hook fetches what waits for it, at its next prompt
        uuid = str(body.get("uuid") or "").lower()
        if not _clients.UUID.match(uuid):
            return 400, {"error": "uuid = the session's transcript id"}
        rec = _clients.sessions_on(machine).get(uuid)
        if rec is None:
            try:
                rec = _clients.register(machine, {"uuid": uuid, "name": str(body.get("name") or "")})
            except ValueError as e:
                return 400, {"error": str(e)}
        else:
            _clients.seen(machine, uuid)
        return 200, {"deliveries": _inbox.take({uuid: str(rec.get("name") or "")})}
    return 404, {"error": "no such write: message | handover | held | project-agent | project-agent-mandate | project-agent-rename | project-agent-retire | project | project-list | question | terminal-prompt | job-gap | item-open | cap-words | state | rebullet | register | seen | poll | ack | drain | recycled | recycle-due | released | sweep-released | sweep-step-proof | page-debt | backfill-contact | event | setup-result"}


async def client_write(request: Request):
    """The client API's writes: what a machine's hooks and its puller send, each proved by the machine's token.
    `poll` is the puller's long poll: it reports the sessions live on the machine (the machine's sign of life), and is held
    open until a line waits for one of them or `wait` seconds pass."""
    import asyncio
    from starlette.concurrency import run_in_threadpool
    machine = _client_machine(request.headers.get("authorization", ""))
    if not machine:
        return PlainTextResponse("unauthorized: a machine token is required (Authorization: Bearer …)", status_code=401)
    what = str(request.path_params.get("what", ""))
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
    except Exception:
        return JSONResponse({"error": "the body is a JSON object"}, status_code=400)
    nocache = {"Cache-Control": "no-store"}
    if what == "poll":
        sessions = [x for x in (body.get("sessions") or []) if isinstance(x, dict)]
        try:
            wait = min(_POLL_MAX, max(0.0, float(body.get("wait") or 0)))
        except Exception:
            wait = 0.0
        await run_in_threadpool(_clients.checkin, machine, sessions, body.get("facts") if isinstance(body.get("facts"), dict) else {}, bool(body.get("partial")))
        current = await run_in_threadpool(_clients.current, machine)        # what is current, so a box behind it updates itself when idle (puller 9)
        live = {str(x.get("uuid") or x.get("sessionId") or "").lower(): str(x.get("name") or "") for x in sessions}
        mine = await run_in_threadpool(_clients.sessions_on, machine)        # only what the server holds for THIS machine is served
        # the name a line is matched by is the one the server kept for the session (checkin has just applied the report), never the CLI's placeholder
        # a relaunched pane reports ("pane-x": its lines then matched nobody); the newest registration settles namesakes
        live = {u: str(mine[u].get("name") or n) for u, n in live.items() if u in mine}
        rank = {u: _clients._ts(mine[u].get("registered")) for u in live}
        deadline = time.time() + wait
        try:
            while True:
                deliveries = await run_in_threadpool(lambda: _inbox.take(live, rank=rank)) if live else []
                if deliveries or time.time() >= deadline:
                    break
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:      # the server is stopping while it holds this poll: answer empty, no traceback, no 500;
            deliveries = []                 # a line taken in that moment is leased, and returns to the inbox when its lease runs out
        return JSONResponse({"deliveries": deliveries, "machine": machine, "current": current}, headers=nocache)
    status, out = await run_in_threadpool(_client_post, machine, what, body)      # delivery can take seconds: off the event loop
    return JSONResponse(out, status_code=status, headers=nocache)


# The For you list's two writes for the fleet tool's web server, which holds the machine token and has no board cookie or page token. Sub-paths of
# /client, so their own routes (the generic one takes a single segment). Only the New session form's caller may (_form_call: `sender` in
# [project_agent] form_senders AND the token's machine in form_machines; defaults: no sender label, no machine): a session that holds the machine
# token must not be able to mute his items or clear his list. Any other caller: 403 with the reason.
_FORYOU_NOT_FORM = ("refused: only the web form may change the For you list: `sender` must be a label in [project_agent] form_senders "
                    "and the token must be a machine in form_machines")


def _foryou_form_gate(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]] | str:
    """The checks both routes share -> the sender label to log, or (status, JSON) to answer: 400 for a sender that is no label, 403 unless _form_call."""
    sender = body.get("sender")
    if not isinstance(sender, str) or not sender.strip() or len(sender.strip()) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in sender.strip()):
        return 400, {"error": "sender = the caller's own label: one line of at most 80 characters"}
    sender = sender.strip()
    if not _form_call(machine, sender):
        return 403, {"error": _FORYOU_NOT_FORM}
    return sender


def _client_foryou_seen(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`POST /client/for-you/seen` body {id: <row id int> | "all", sender} -> 200 {ok, seen: [ids marked], rows: the unseen rows as GET /client/for-you
    serves them}; 400 a bad body, 403 not the web form, 404 a row that is not on the list."""
    gate = _foryou_form_gate(machine, body)
    if not isinstance(gate, str):
        return gate
    rid = body.get("id")
    if not ((isinstance(rid, int) and not isinstance(rid, bool) and rid >= 1) or rid == "all"):
        return 400, {"error": 'id = a row\'s number (a whole number from 1), or "all"'}
    gone = _fy.mark_seen(rid)
    if gone is None:
        return 404, {"error": f"no row {rid} on the For you list (never made, or already seen)"}
    if gone:
        print(f"for-you: seen {'all rows' if rid == 'all' else 'row'} {gone} by {gate} (machine {machine})", file=sys.stderr, flush=True)
        _publish()
    return 200, {"ok": True, "seen": gone, "rows": _fy.payload(_gh.shown)["rows"]}


def _client_item_watch(machine: str, key: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`POST /client/items/{key}/watch` body {state: watch | mute | default, sender} -> 200 {ok, item: board#N, state, flags: the whole map as
    GET /client/for-you serves it}; 400 a bad state, 403 not the web form, 404 an unknown item."""
    gate = _foryou_form_gate(machine, body)
    if not isinstance(gate, str):
        return gate
    state = body.get("state")
    if state not in ("watch", "mute", "default"):
        return 400, {"error": "state = watch | mute | default"}
    try:
        gid = _norm_id("board#" + key if key.isdigit() else key)
        _load(gid)
    except ToolError:
        return 404, {"error": f"no item {key!r}: an id as shown, board#<n>, or its store id"}
    _fy.set_flag(gid, state)
    print(f"for-you: {_gh.shown(gid)} set to {state} by {gate} (machine {machine})", file=sys.stderr, flush=True)
    _publish()
    return 200, {"ok": True, "item": _gh.shown(gid), "state": state, "flags": _fy.payload(_gh.shown)["flags"]}


async def _client_foryou_call(request: Request, fn: Any, *args: Any):
    from starlette.concurrency import run_in_threadpool
    machine = _client_machine(request.headers.get("authorization", ""))
    if not machine:
        return PlainTextResponse("unauthorized: a machine token is required (Authorization: Bearer …)", status_code=401)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
    except Exception:
        return JSONResponse({"error": "the body is a JSON object"}, status_code=400)
    status, out = await run_in_threadpool(fn, machine, *args, body)
    return JSONResponse(out, status_code=status, headers={"Cache-Control": "no-store"})


async def client_foryou_seen(request: Request):
    return await _client_foryou_call(request, _client_foryou_seen)


async def client_item_watch(request: Request):
    return await _client_foryou_call(request, _client_item_watch, str(request.path_params.get("key", "")))


async def client_api(request: Request):
    machine = _client_machine(request.headers.get("authorization", ""))
    if not machine:
        return PlainTextResponse("unauthorized: a machine token is required (Authorization: Bearer …)", status_code=401)
    what = str(request.path_params.get("what", ""))
    if what == "whoami":
        return JSONResponse({"machine": machine}, headers={"Cache-Control": "no-store"})
    if what == "config":
        return JSONResponse(_client_config(), headers={"Cache-Control": "no-store"})
    if what == "recycle-wanted":   # the fleet tool's watchdog: "<count> <id>[@<epoch>][~<repo>:pr<N>]…" of what a recycle of this machine would serve now
        from starlette.concurrency import run_in_threadpool
        ids = await run_in_threadpool(_recycle_wanted_tokens, machine)
        return PlainTextResponse(" ".join([str(len(ids)), *ids]), headers={"Cache-Control": "no-store"})
    if what == "puller-lag":       # the fleet tool's watchdog: "<hostname> <reported> <current>" per box whose puller is behind
        from starlette.concurrency import run_in_threadpool
        rows = await run_in_threadpool(_clients.puller_lag)
        return PlainTextResponse("".join(f"{h} {r} {c}\n" for h, r, c in rows), headers={"Cache-Control": "no-store"})
    status, ctype, body = _client_get(what, dict(request.query_params))
    return PlainTextResponse(body, status_code=status, media_type=ctype, headers={"Cache-Control": "no-store"})


def register(mcp, *, client_get, recycle_wanted_tokens) -> None:
    """Add the routes to the server's `mcp`, in the order they were declared in server.py. Called once."""
    global _client_get, _recycle_wanted_tokens
    _client_get, _recycle_wanted_tokens = client_get, recycle_wanted_tokens
    mcp.custom_route("/client/{what}", methods=["POST"])(client_write)
    mcp.custom_route("/client/for-you/seen", methods=["POST"])(client_foryou_seen)
    mcp.custom_route("/client/items/{key}/watch", methods=["POST"])(client_item_watch)
    mcp.custom_route("/client/{what}", methods=["GET"])(client_api)
