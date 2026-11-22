"""retired_recipient.py: what becomes of a message or notice sent to a session name that is no live session.

A line addressed to a name nobody runs used to wait in the per-session queue (<hub state dir>/queue-msg/<name>.jsonl) for a session that never came back: a
retired agent, an old name of a renamed session, a name that was never one. The queue grew, and nobody was told. Now such a line is not left there:

  1. it is readdressed to the project the name belongs to (`project_of_name`: the page that lists the name, else the page whose project name the session name starts with),
     recorded for that project the way a message to a project is, and ruled by the router, which picks the receiver (router_live: find the agent, reuse it);
  2. when no page can be told that has an agent to take it (the name belongs to no project, or the project has no agent), it goes back to its sender, saying the receiver is retired;
     when the sender is a script (a label that is no session: the server's own name, a client.py caller), the return is only logged;
  3. either way the sender is told, in one line, that the receiver is retired and who got it (`Result.line`, which push.py prints as its outcome and the message tool words in its own reply).

Which names count (`gone_why`): a name no pane runs under and that is a retired session (a page lists it as a retired name-line session, or the fleet tool's registry says it is retired), an
old name of a renamed session, a session whose every pane has been gone longer than `[client] dead_after_minutes` on a machine that is online (the message tool's rule: liveness.pane_dead),
or a name no heartbeat has seen at all and whose line has waited longer than that. A name with a pane running, or one that is only away or not yet seen, is no such name, and an
unreadable or partial view of the fleet says nothing: every doubt is "as before" (the line is queued). Never raises into the caller: `handle` answers None for "as before".

The queue the lines of such names piled up in is cleaned once by `sweep` (a dry run first): `python3 stackshot/fleet/retired_recipient.py sweep [--apply] [--queue DIR]`. A queued notice about an
item that has since closed, been parked again or changed mover, and one that is over age, is dropped (stale_notice.screen); every other line of a gone name is readdressed or returned as above.
Nothing is deleted without a record: every dropped, readdressed or returned line is one line of <hub state dir>/queue-msg-retired.jsonl (id, name, reason), and the queue file is moved
to <hub state dir>/archive/. Run again after a stop, it skips the lines the log already has.

Imports the domain only (fleet, router, anchors, projects), each lazily: push.py loads this module only when it is about to queue a line for a name it could not deliver to."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Callable

if not __package__:   # started as a script: the checkout must be importable
    _here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [os.path.dirname(os.path.dirname(_here))] + [p for p in sys.path if os.path.abspath(p or ".") != _here]

from stackshot.core import config as _cfg  # noqa: E402

LOG_NAME = "queue-msg-retired.jsonl"
ARCHIVE_DIR = "archive"
_ROUTER_SENDER = "stackshot (router)"         # router_live.BY: the router's own delivery is never readdressed (it would rule its own pass again)
_SCRIPT = re.compile(r"\ba script on\b")
_LABEL_TAIL = re.compile(r"\s*\(.*$", re.S)   # a name followed by a parenthesis (a short id) → the session's name


def hub_dir() -> Path:
    """The hub's state directory, the one push.py keeps its queues in."""
    from stackshot.fleet import push as _push
    return Path(_push.A)


# ----------------------------------------------------------------------------- which names are no session
def _view() -> tuple[Any, dict[str, Any]] | None:
    """(the heartbeat index, the page roles), None when the view of the fleet is partial or empty: then nothing is said about any name."""
    from stackshot.anchors import anchors as _anc
    from stackshot.fleet import sessions_registry as _sr
    idx = _sr._sessions_index()
    if getattr(idx, "unreadable", None) or not len(idx):
        return None
    return idx, _anc.session_roles()


def gone_why(name: str, age: float = 0.0, now: float | None = None, view: tuple[Any, dict[str, Any]] | None = None) -> str:
    """Why `name` is no live session, in words ("" when it may be one, or when that cannot be told). `age` = how long the line has waited (a name no heartbeat has seen is gone only for a line older
    than liveness.dead_after: a pane started a minute ago is not yet in any heartbeat)."""
    n = str(name or "").strip()
    try:
        if not n or n.startswith("cse_"):
            return ""
        from stackshot.fleet import liveness as _lv
        from stackshot.fleet import sessions_registry as _sr
        v = view or _view()
        if v is None or getattr(v[0], "unreadable", None) or not len(v[0]):
            return ""
        idx, roles = v
        rows = [r for r in idx.values() if isinstance(r, dict) and r.get("name") == n]
        byid = idx.get(n)
        if isinstance(byid, dict) and not any(byid is r for r in rows):
            rows.append(byid)
        if any(_lv.running(r) for r in rows):
            return ""
        held = _sr._role_name(roles, n)
        if held and roles[held].get("retired"):
            return "a retired name-line session, its pane gone"
        reg = _sr.row(n)
        if reg and reg.get("state") != "live":
            return "a retired session, its pane gone"
        if rows:
            whys = [_lv.pane_dead(r, now) for r in rows]
            return whys[0] if all(whys) else ""
        cur = _sr.display_name(n) if reg else None
        if reg and cur and cur != n:
            return f"an old name of {cur}"
        if reg:
            return ""
        return "no pane of that name is in any heartbeat" if age > _lv.dead_after() else ""
    except Exception:  # noqa: BLE001  — a view that does not read says nothing: the line is queued as before
        return ""


# ----------------------------------------------------------------------------- the project of a name
def project_of_name(name: str, roles: dict[str, Any], reaches: Callable[[str, dict[str, Any]], Any] | None = None) -> str:
    """The page key a session name belongs to and whose page would get the message to someone else: the page that lists the name (roles), else
    the page whose project name the session's name starts with (`<project>-<role>`, projects._name_prefixes), the longer name first. Several
    pages can share one display name (projects/hub, projects/example, projects/example-portal and a sub-page all answer to `my-project`),
    so among the pages of one prefix the choice is, in order: a page whose `agents:` map lists the exact name; a page with a
    non-empty agents map, a top-level page (no sub-page) whose key slug is the prefix's last part (`my-project` → `stackshot`) first,
    else the one with the most agents; then the rest, the shallower page first. A page counts only when it has a
    keeper to pass the message to (`reaches`: the stand-in, router_live.stand_in by default: its builder, else its -main agent, else its hub's, else the scope's general one): the
    router rules every page's message. "" when no page can be told. The message relay (service/messaging.py `_project_of_name`) and the queue's sweep both ask this one."""
    from stackshot.anchors import anchors as _anc
    from stackshot.fleet import sessions_registry as _sr
    from stackshot.projects import projects as _prj
    from stackshot.router import router_live as _rl
    reg = _anc.registry()
    take = reaches or _rl.stand_in
    def ok(k: str) -> bool:
        return bool(take(k, reg))
    k = str((roles.get(_sr._role_name(roles, name)) or {}).get("project") or "")
    if k in reg and ok(k):
        return k
    fold = name.casefold(); best: list[tuple[int, int, int, int, int, str]] = []
    dirs = tuple(d + "/" for d in _cfg.page_dirs())
    for k, e in reg.items():
        if not isinstance(e, dict) or not k.startswith(dirs):
            continue
        try:
            pre = _prj._name_prefixes(k, e, reg)
        except Exception:  # noqa: BLE001
            continue
        hit = [x for x in pre if fold.startswith(x.casefold() + "-") and len(name) > len(x) + 1]
        if hit:
            x = max(hit, key=len)
            ags = {str(a).casefold() for a in (e.get("agents") if isinstance(e.get("agents"), dict) else {})}
            depth = k.count("/"); slug = k.rsplit("/", 1)[-1].casefold()
            home = depth == 1 and (x.casefold() == slug or x.casefold().endswith("-" + slug))
            # the exact listing first; then pages with agents (the slug's top-level page, else the most agents); then the rest
            best.append((-len(x), 0 if fold in ags else 1 if ags else 2, 0 if home else 1, -len(ags), depth, k))
    return next((t[-1] for t in sorted(best) if ok(t[-1])), "")


def takes_other(project: str, name: str) -> bool:
    """Can the project's router pass a message meant for `name` to someone else: its stand-in is another session, or the page (or its hub) lists another agent. A page whose only agent is the retired name has
    no receiver: a message sent to it would be ruled back onto the name."""
    try:
        from stackshot.anchors import anchors as _anc
        from stackshot.router import router_live as _rl
        reg = _anc.registry()
        keeper = _rl.stand_in(project, reg)
        if keeper and keeper != name:
            return True
        front, back = _rl._agents_of(project, reg)
        return any(a != name for a in (*front, *back))
    except Exception:  # noqa: BLE001
        return False


# ----------------------------------------------------------------------------- one line
class Result:
    """What became of one line: `action` is "rerouted" (recorded for `project`, notice `nid`), "returned" (told to its sender) or "logged" (a script sender: only the log has it);
    `line` is the one sentence that tells the sender the receiver is retired and who got it."""
    def __init__(self, action: str, why: str, project: str = "", nid: str = "", line: str = "") -> None:
        self.action, self.why, self.project, self.nid, self.line = action, why, project, nid, line


def line_id(name: str, t: Any, text: str) -> str:
    return hashlib.sha1(f"{name}|{t}|{text}".encode("utf-8", "replace")).hexdigest()[:12]


def _sender_session(sender: str, view: tuple[Any, dict[str, Any]] | None) -> str:
    """The name of the running session a sender label stands for ("" for a script, the server's own name, a label no heartbeat row runs under)."""
    s = str(sender or "").strip()
    if not s or _SCRIPT.search(s):
        return ""
    nm = _LABEL_TAIL.sub("", s).strip()
    if view is None or not nm:
        return ""
    try:
        from stackshot.fleet import liveness as _lv
        idx = view[0]
        rows = [r for r in idx.values() if isinstance(r, dict) and r.get("name") == nm]
        byid = idx.get(nm)
        if isinstance(byid, dict):
            rows.append(byid)
        return nm if any(_lv.running(r) for r in rows) else ""
    except Exception:  # noqa: BLE001
        return ""


def _first(text: str, n: int = 160) -> str:
    return " ".join(str(text).split())[:n]


def _told(name: str, why: str, text: str) -> str:
    return (f"[stackshot] Your message to {name} was not delivered: {name} is retired ({why}), and no project page that has an agent takes its messages, so nobody got it. "
            f"It began: {_first(text)}")


def _envelope(name: str, project: str, why: str, sender: str, text: str) -> str:
    return (f"[stackshot message] from {sender or 'an unnamed script'}, sent to {name}, which is retired ({why}); it came to {project} instead.\n{text}")


def handle(name: str, text: str, sender: str = "", *, age: float = 0.0, apply: bool = True, deliver: Callable[[str, str, str], Any] | None = None,
           view: tuple[Any, dict[str, Any]] | None = None, via: str = "push", t: Any = None, log_to: Path | None = None) -> Result | None:
    """The treatment of one line for `name`. None = as before (the name may be a live session, the view says nothing, the sender is the router, or anything failed): the caller queues it.
    `apply` False decides and writes nothing (the sweep's dry run). `deliver(name, text, sender)`: how a line reaches a live session (push.deliver); without it a return to a session sender is only logged."""
    try:
        if str(sender or "").startswith(_ROUTER_SENDER):
            return None
        v = view or _view()
        why = gone_why(name, age, view=v)
        if not why:
            return None
        roles = v[1] if v else {}
        proj = project_of_name(name, roles)
        if proj and not takes_other(proj, name):
            proj = ""                    # the project's only agent is the retired name: nobody to give it to
        who = str(sender or "").strip()
        lid = line_id(name, t if t is not None else time.time(), text)
        if proj:
            nid = ""
            from stackshot.anchors import anchors as _anc
            if not _anc.pilot_root(proj):         # the router rules every page: a key it does not know is no project to send to
                return None
            if apply:
                from stackshot.router import routing as _routing
                from stackshot.router import router_live as _rl
                nid = _routing.record(proj, kind="message", to="", label=f"message to {proj} (for retired {name})", who=who or "an unnamed script", text=text,
                                      target="project-wide", pilot=True, live=True)
                if not nid:
                    return None
                _rl.stash(nid, _envelope(name, proj, why, who, text))
            res = Result("rerouted", why, proj, nid or "(dry run)",
                         f"queued (retired: {name}, {why}; sent to {proj}, where the router rules notice {nid or '…'} and passes it to the agent it fits) → {name}")
        else:
            back = _sender_session(who, v)
            if back and back != name and apply and deliver is not None:
                try:
                    with redirect_stdout(io.StringIO()):
                        deliver(back, _told(name, why, text), "stackshot")
                    res = Result("returned", why, line=f"queued (retired: {name}, {why}; no project takes its messages, so it was returned to {back}) → {name}")
                except Exception:  # noqa: BLE001
                    res = Result("logged", why, line=f"queued (retired: {name}, {why}; no project takes its messages, and it could not be returned to {back}: logged) → {name}")
            elif back and back != name and not apply:
                res = Result("returned", why, line=f"queued (retired: {name}, {why}; no project takes its messages, so it was returned to {back}) → {name}")
            else:
                res = Result("logged", why, line=f"queued (retired: {name}, {why}; no project takes its messages and its sender is a script: logged) → {name}")
        if apply:
            log(via, lid, name, res, who, text, dest=log_to)
        return res
    except Exception as e:  # noqa: BLE001  — the line is queued as before
        print(f"retired_recipient: {name!r} left to the queue: {e!r}", file=sys.stderr, flush=True)
        return None


def log(via: str, lid: str, name: str, res: "Result | str", sender: str = "", text: str = "", why: str = "", dest: Path | None = None) -> None:
    """One journal line: id, name, reason, what was done. Never raises."""
    try:
        action = res if isinstance(res, str) else res.action
        entry = {"t": time.time(), "via": via, "id": lid, "name": name, "action": action, "reason": why or (res.why if not isinstance(res, str) else ""),
                 "project": "" if isinstance(res, str) else res.project, "notice": "" if isinstance(res, str) else res.nid, "from": sender, "text": _first(text, 200)}
        p = dest or (hub_dir() / LOG_NAME)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


# ----------------------------------------------------------------------------- the one-shot sweep of the queue
def _read(path: Path) -> list[dict[str, Any]]:
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if isinstance(d, dict):
                rows.append(d)
    return rows


def _done_ids(log_path: Path) -> set[str]:
    try:
        return {str(json.loads(ln).get("id")) for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()}
    except (OSError, ValueError):
        return set()


def sweep(queue_dir: str | Path, apply: bool = False, now: float | None = None, deliver: Callable[[str, str, str], Any] | None = None,
          view: tuple[Any, dict[str, Any]] | None = None, load: Callable[[str], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    """Apply the treatment above to every line of every queue file of `queue_dir` (<hub dir>/queue-msg) → {"names": {name: {action: count}}, "actions": {action: count}, "files": [...]}.
    Without `apply` nothing is written. The log and the archive are beside the queue directory. A name with a live session keeps its file whole ("kept"); a line of a gone name is "dropped"
    (stale_notice.screen: its item closed, was parked again, has another mover, or the notice is over age), "rerouted", "returned" or "logged"; a line of a name that is not yet gone stays ("kept")."""
    from stackshot.fleet import stale_notice as _stale
    q = Path(queue_dir)
    hub = q.parent
    log_path = hub / LOG_NAME
    now = time.time() if now is None else now
    v = view if view is not None else _view()
    done = _done_ids(log_path)
    out: dict[str, Any] = {"names": {}, "actions": {}, "projects": {}, "files": [], "unreadable_view": v is None}
    for f in sorted(q.glob("*.jsonl")):
        name = f.stem
        try:
            rows = _read(f)
        except OSError:
            continue
        counts: dict[str, int] = out["names"].setdefault(name, {})
        def bump(a: str, n: int = 1) -> None:
            counts[a] = counts.get(a, 0) + n; out["actions"][a] = out["actions"].get(a, 0) + n
        todo = [r for r in rows if line_id(name, r.get("t"), str(r.get("text") or "")) not in done]
        if len(todo) < len(rows):
            bump("already-done", len(rows) - len(todo))
        age_of = lambda r: now - float(r.get("t") or now)      # noqa: E731
        gone = [r for r in todo if gone_why(name, age_of(r), now, v)]
        keep = [r for r in todo if r not in gone]
        if keep:
            bump("kept", len(keep))
        if not gone and len(todo) == len(rows):
            continue          # nothing of it to do (a file some of whose lines a cut-off run did is finished below: archived, the rest kept)
        live_rows, dropped = _stale.screen(gone, recipient=[name], now=now, load=load) if gone else ([], [])
        for r, why in dropped:
            bump("dropped")
            if apply:
                log("sweep", line_id(name, r.get("t"), str(r.get("text") or "")), name, "dropped", str(r.get("from") or ""), str(r.get("text") or ""), why, dest=log_path)
        for r in live_rows:
            res = handle(name, str(r.get("text") or ""), str(r.get("from") or ""), age=age_of(r), apply=apply, deliver=deliver, view=v, via="sweep", t=r.get("t"), log_to=log_path)
            if res is None:
                bump("kept"); keep.append(r)
            else:
                bump(res.action)
                if res.project:
                    out["projects"].setdefault(name, set()).add(res.project)
        if apply:
            arch = hub / ARCHIVE_DIR
            arch.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
            dest = arch / f"queue-msg-{name}-{stamp}.jsonl"
            os.replace(f, dest)
            out["files"].append(str(dest))
            if keep:
                with open(f, "w", encoding="utf-8") as g:
                    for r in keep:
                        g.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


def report(res: dict[str, Any], apply: bool) -> str:
    lines = [("applied" if apply else "dry run (nothing written)") + (": the view of the fleet could not be read, so no name was called gone" if res.get("unreadable_view") else "")]
    for name, c in sorted(res["names"].items()):
        to = sorted(res.get("projects", {}).get(name, ()))
        lines.append(f"  {name}: " + ", ".join(f"{a} {n}" for a, n in sorted(c.items())) + (f" → {', '.join(to)}" if to else ""))
    lines.append("total: " + (", ".join(f"{a} {n}" for a, n in sorted(res["actions"].items())) or "nothing queued"))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help") or argv[0] != "sweep":
        print(__doc__); return 2
    apply = "--apply" in argv
    q = hub_dir() / "queue-msg"
    if "--queue" in argv:
        i = argv.index("--queue")
        if i + 1 >= len(argv):
            print("usage: retired_recipient.py sweep [--apply] [--queue DIR]", file=sys.stderr); return 2
        q = Path(argv[i + 1])
    deliver = None
    if apply:
        os.environ["ANCHOR_PUSH_SOURCE"] = "msg"          # a return to a session goes through the message queue's own delivery
        from stackshot.fleet import push as _push
        deliver = _push.deliver
    print(report(sweep(q, apply=apply, deliver=deliver), apply))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
