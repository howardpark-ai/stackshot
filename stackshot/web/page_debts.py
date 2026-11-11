"""page_debts.py: the page rule's debts: a board write that changes state owes a project-page update by the session that made it (the ledger `ledger.json` under the state dir, `_owed_load`, `_owed_save`, `_owed_mark`,
`_owed_settle`), the grace and the slack that settle it (`_grace_min`, `_page_slack`, `_page_ts`), the nag a reply ends with (`_nag`) and the refusal of a write while a debt is past its grace (`_refuse_if_owing`), with the
helpers they read: how a page is written (`_page_how`), a session's stored reference and its shown name (`_session_id`, `_store_ref`, `_same_sess`, `_shown_ref`, `_shown_needs`, `_role_name`) and the ledger's one lock (`_OWED_LOCK`).

server.py is being split into one module per area (CONTRIBUTING.md, Layout). The module needs nothing of server.py (a module here cannot import it, and it runs as `__main__`): it reads the config, the page and project
modules, the registry readers (`field_gates.py`), the session helpers (`shared.py`) and the pure pieces (`common.py`). server.py imports each name its writes, its tools and the suites read back from here, so
`server._owed_mark`, `server._refuse_if_owing`, `server._nag` and the others stay the names they use. `_refuse_if_owing` has no caller here: the writes in server.py call it, and a suite that stubs it
(`server._refuse_if_owing = ...`) stubs it where they look it up. `_page_ts` is called here by `_owed_settle` and by the client API's page-ts answer in server.py: the suites that put a page's time in place of the real one for
the debts set it on this module (`server._pdebts._page_ts`), and the one that stubs the client API's answer sets it on `server`. `_HERE` is the checkout's root, read only in the two messages that name the `pages.py clear` command;
server.py keeps its own `_HERE` (its git calls read it, and the suites set it), which is the same value."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot import paths as _paths
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.fleet import sessions_registry as _sr
from stackshot.model.needs import _NEEDS_KINDS
from stackshot.projects import brains as _brains
from stackshot.projects import pages as _pages
from stackshot.projects import project_registry as _pr
from stackshot.projects import projects as _prj
from stackshot.router import page_debt as _page_debt
from stackshot.web import render as _rmod
from stackshot.web.field_gates import _registry_hits
from stackshot.web.shared import _session_label, _sessions_index

_HERE = _paths.ROOT


def _page_how(flavor: str | None = None) -> str:
    """How a page is written, as the nag and the refusal say it ([pages] flavor): gbrain's tools, or the plain file."""
    if (flavor or _cfg.page_flavor()) == "gbrain":
        return "dated line → add_timeline_entry; other edits → get_page with section or grep (the smallest read that shows the text to change; a whole read only for a rewrite or a change spanning the page), then edit_page with expected_revision (the read's revision) and edits [{old_text, new_text}]; put_page only for a whole rewrite; never edit or git inside the brain mirror"
    return "edit " + str(_cfg.get("paths", "brain") or "").rstrip("/") + "/<key>.md (its Current state, and a dated line under its Timeline), commit and push"


# ----------------------------------------------------------------------------- page rule (debts)
# A board write that changes state owes a project-page update, by the session that made it (the
# earlier per-project list named no debtor, never cleared itself — it parsed an epoch as an ISO string — and was marked
# by every write, typo fixes included). Debts live in page_rule.state_file as {page key: {owner: {"ts", "item"}}}.
_STATE_FIELDS = ("description", "next", "needs", "status", "due")   # a change here is a state change; owner/project/priority/subject are filing


def _page_slack() -> int:
    """A page put up to this long BEFORE the board write counts as the same turn."""
    return int(_cfg.get("page_rule", "slack_seconds") or 300)


def _brain_dir() -> Path:
    return _cfg.path("paths", "brain")


def _page_ts(key: str) -> float:
    """When the page last changed: the mirror's last commit or the file's mtime, whichever is newer (the managed coordinator
    writes and commits ~1 s after a put); the same rule the pane gate applies (pages.page_ts; one copy since an earlier change)."""
    try:
        return float(_pages.page_ts(key) or 0)
    except Exception:
        return 0.0


def _owed_path() -> Path:
    p = _cfg.state("ledger.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


_OWED_LOCK = threading.RLock()     # the page-debt ledger is read, changed and rewritten whole: one thread at a time (a read-change-write holds it from its read to its write)


def _owed_load() -> dict[str, dict[str, dict[str, Any]]]:
    try:
        with _OWED_LOCK, open(_owed_path(), encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for k, v in (raw or {}).items():
        hits = _registry_hits("projects", k)
        key = hits[0] if hits else (k if "/" in k else f"{_cfg.page_dirs()[0]}/{k}")
        if isinstance(v, dict):
            for o, e in v.items():
                if isinstance(e, dict) and e.get("ts"):
                    out.setdefault(key, {})[o] = e
    return out


def _owed_save(d: dict[str, dict[str, dict[str, Any]]]) -> None:
    with _OWED_LOCK:
        path = _owed_path()
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))     # a temporary file of its own, as the request map's
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _session_id(value: str) -> str:
    """A pane name → its transcript UUID when exactly one live pane carries that name (from the heartbeats), so the
    store holds the id and the board follows a /rename on its own; ids and unknown names pass through.
    The same rule the anchor bindings use (anchors.canonical)."""
    return _anc.canonical(value)


def _shown_ref(value: str) -> str:
    """A stored session reference as people read it: the registry's current name when it resolves, else what is stored, as it is."""
    v = str(value or "")
    return _sr.display_name(v) or v if v else v


def _shown_needs(needs: list[str]) -> list[str]:
    """A needs list for people: decision and external as they are, each session by its current name."""
    return [x if x.lower() in _NEEDS_KINDS else _shown_ref(x) for x in needs]


def _role_name(roles: dict[str, Any], who: str, *extra: str) -> str:
    """The name a project page lists `who` under, as `roles` (anchors.session_roles) has it: who as given, its name now, the old names the fleet tool
    kept for it (a page may still list the name before a rename), then any `extra`. "" when no page lists it."""
    who = str(who or "").strip()
    if not who:
        return ""
    sid = _sr.resolve(who)

    def mine(n: str) -> bool:        # a name the registry gives this session counts only when it resolves back to it: a retired row never takes a live row's entry by alias
        return not sid or n == who or n in extra or _sr.resolve(n) == sid
    return next((n for n in (who, _session_label(who), *_sr.names_of(who), *extra) if n and n in roles and mine(n)), "")


def _store_ref(value: str) -> str:
    """The form a session reference is stored in on an item: its permanent id when the registry resolves it, else the value unchanged."""
    v = str(value or "").strip()
    return _sr.resolve(v) or v if v else v


def _same_sess(a: str, b: str) -> bool:
    """Do two stored references name one session? As permanent ids when the registry resolves both, else as the strings stand."""
    t = _sr.same(a, b)
    return (a == b) if t is None else t


def _owed_mark(project: str, owner: str, item: str, settle: str = "", moves: str = "", what: str = "") -> None:
    """Charge a page debt to `owner`. The page-writer debts carry settle ("ct": a Current-state edit settles it; "any": any page
    write, for a next-only change or a hold) and moves (the keeper it moves to after the grace, with `what` for its notice)."""
    if _prj.is_id(project):         # a project the item names by id: the page debt is on its page, and a project with no page in this instance's page store owes none
        project = _pr.page_key_of(project)
    if not project or _brains.shared_refusal(project):      # a page of a brain marked shared owes nothing: stackshot writes none of its board there, and no session is asked to
        return
    o = _session_id(owner) or "?"
    with _OWED_LOCK:
        d = _owed_load()
        prev = d.get(project, {}).get(o) or {}
        if settle == "any" and prev.get("settle") == "ct":
            settle = "ct"            # a later next-only change never loosens what an earlier state change still owes
        e: dict[str, Any] = {"ts": time.time(), "item": item}
        if settle: e["settle"] = settle
        if moves: e.update(moves=moves, what=what)
        d.setdefault(project, {})[o] = e
        _owed_save(d)


def _writer_owes() -> bool:
    """(stackshot.toml [pilot] writer_owes_page): in a pilot project the session that
    changes an item owes the page update itself, and the keeper gets it only when it is still missing after the grace.
    Off: the keeper is charged and told at once, as before."""
    return bool(_cfg.get("pilot", "writer_owes_page"))


def _debt_strict(owner: str, e: dict[str, Any]) -> bool:
    """Does this debt settle only on a Current-state edit? A writer debt says so itself; any other follows _strict."""
    settle = e.get("settle")
    return settle == "ct" if settle in ("ct", "any") else _strict(owner)


def _strict(owner: str) -> bool:
    """(stackshot.toml [page_gate] keeper_currency; every page keeper): this debtor's debts settle only
    on a Current-state edit."""
    try:
        return _pages.in_currency(owner, str((_sessions_index().get(owner) or {}).get("name") or ""))
    except Exception:
        return False


def _owed_settle() -> dict[str, dict[str, dict[str, Any]]]:
    """Drop every debt whose page changed after the board write (minus the slack); return what is still owed. For a page
    keeper the page's compiled truth must have changed too — a timeline line alone does not settle it."""
    with _OWED_LOCK:
        d = _owed_load(); changed = False
        for key in list(d):
            if _brains.shared_refusal(key):     # a debt an earlier run charged on a page of a brain now marked shared: it owes nothing, so it is dropped
                del d[key]; changed = True
                continue
            if _owed_brain_skip(key):       # a second brain whose copy cannot be read: its debts are kept as they are, not settled or charged this run
                continue
            pt: float | None = None         # the page's time (a git log), read once per key
            for o in list(d[key]):
                if d[key][o].get("retired_only"):       # an entry an earlier release wrote for a retired agent's line (stackshot removes that line itself now): it owes nothing
                    del d[key][o]; changed = True
                    continue
                if "retired" in d[key][o]:              # …and the same release's line on an entry that also owes a debt: the debt stays, the line goes
                    del d[key][o]["retired"]; changed = True
                ts = float(d[key][o].get("ts", 0))
                if pt is None: pt = _page_ts(key)
                if pt >= ts - _page_slack():
                    if _debt_strict(o, d[key][o]):
                        try:
                            if not _pages.ct_changed_since(key, int(ts)): continue
                        except Exception: pass
                    del d[key][o]
                    changed = True
            if not d[key]:
                del d[key]; changed = True
        if changed:
            _owed_save(d)
        return d


def _owed_brain_skip(key: str) -> bool:
    """True when the page sits in a second brain ([[brains]]) whose copy is missing or stale: pages owed and the audit's page call skip it for this
    run and say so once, naming the brain (brains.warn_once); the board never blocks on it."""
    try:
        return bool(_brains.skip(key, "pages owed and the audit's page call skip its pages this run"))
    except Exception:  # noqa: BLE001
        return False


def _owed_readable(d: dict[str, dict[str, dict[str, Any]]]) -> dict[str, dict[str, dict[str, Any]]]:
    """The debts whose page can be read now: the ledger as _owed_settle returns it, without a skipped second brain's pages (a copy: the
    caller never saves it)."""
    return {k: v for k, v in d.items() if not _owed_brain_skip(k)}


def _age(ts: float) -> str:
    return _rmod.age_words(time.time() - float(ts))


def _grace_min() -> int:
    return int(_cfg.CFG["page_rule"].get("grace_minutes", 30))


_KEEPER_WHY = "a timeline line says something happened, not what is true now"   # the rule left core for this notice


def _debt_mover(project: str = "", keeper: str = "") -> str:
    """Who takes a page debt that is still unsettled after the grace, in the words of a reply or the nag: the audit's page call while it
    is live (it writes the page from the item, else hands it to the agent that keeps it), else the router (it passes the page update to
    the agent that keeps the page). `project` and `keeper` are kept for the callers."""
    if _page_debt.live():
        return "the audit's page call, which writes the page from the item or hands it to the agent that keeps the page"
    return "the router, which passes the page update to the agent that keeps the page"


def _nag(owner: str = "") -> str:
    """Appended to replies: the caller's own debts in full (when the call names its owner), everyone else's in one line."""
    d = _owed_readable(_owed_settle())
    if not d:
        return ""
    owner = _session_id(owner)
    mine = [(k, e) for k, os_ in d.items() for o, e in os_.items() if owner and _same_sess(o, owner) and not e.get("moves")]
    moving = [(k, e) for k, os_ in d.items() for o, e in os_.items() if owner and _same_sess(o, owner) and e.get("moves")]
    others = [(k, o, e) for k, os_ in d.items() for o, e in os_.items() if not (owner and _same_sess(o, owner))]
    out = []
    if moving:                    # a writer's pilot debt is never refused; past the grace it moves to the keeper
        out.append("[nag] PROJECT PAGE owed by you: " + ", ".join(f"{k} ({e.get('item') or 'item'}, {_age(e['ts'])} ago; "
                   + ("its Current state" if _debt_strict(owner, e) else "any page write, a timeline line included") + ")" for k, e in moving)
                   + f" ({_page_how()}). Still missing after {_grace_min()} min, it moves to {_debt_mover(moving[0][0])}.")
    if mine:
        out.append("[nag] PROJECT PAGE owed by you: " + ", ".join(f"{k} ({e.get('item') or 'item'}, {_age(e['ts'])} ago)" for k, e in mine)
                   + f" — a board change that reflects a state change is followed by a page update in the same turn ({_page_how()}). "
                   + (f"As a page keeper your debt settles only when the page's Current state changes: {_KEEPER_WHY}. " if any(_debt_strict(owner, e) for _k, e in mine) else "")
                   + f"After {_grace_min()} min the server refuses your next board write until the page is newer than the change. "
                   + f"Board-only edit that changed no state: `python3 {_HERE}/stackshot/projects/pages.py clear <key>` on the server box.")
    if others:
        out.append("pages owed: " + ", ".join(f"{k} ({_session_label(o)}, {_age(e['ts'])}{', a keeper: settles on a Current-state edit' if _debt_strict(o, e) else ''})" for k, o, e in others))
    return ("\n\n" + "\n".join(out)) if out else ""


def _refuse_if_owing(owner: str) -> None:
    """page_rule.mode = refuse: a session that has owed a page longer than the grace gets its next board write refused."""
    if _cfg.CFG["page_rule"].get("mode") != "refuse" or not owner:
        return
    grace = _grace_min() * 60
    d = _owed_readable(_owed_settle()); owner = _session_id(owner)
    late = [(k, e) for k, os_ in d.items() for o, e in os_.items() if _same_sess(o, owner) and time.time() - float(e.get("ts", 0)) > grace
            and not e.get("moves")]    # a writer's pilot debt moves to the keeper instead (_pilot_fallback_tick)
    if late:
        raise ToolError("Refused: you owe a project-page update — " + ", ".join(f"{k} (since {e.get('item') or 'a board change'}, {_age(e['ts'])} ago)" for k, e in late)
                        + f" — update the page first ({_page_how()}), then retry this write. "
                        + (f"As a page keeper your debt settles only when the page's Current state changes: {_KEEPER_WHY}. " if _strict(owner) else "")
                        + f"If that earlier board edit changed no state: `python3 {_HERE}/stackshot/projects/pages.py clear <key>` on the server box.")
