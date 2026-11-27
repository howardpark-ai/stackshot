"""page_debts.py: the page rule's debts: a board write that changes state owes a project-page update by the session that made it (the ledger `ledger.json` under the state dir, `_owed_load`, `_owed_save`, `_owed_mark`,
`_owed_settle`), the grace and the slack that settle it (`_grace_min`, `_page_slack`, `_page_ts`), the nag a reply ends with (`_nag`) and the line a write's reply carries when the write went through while a debt was past its grace (`_owing_note`), with the
helpers they read: how a page is written (`_page_how`), a session's stored reference and its shown name (`_session_id`, `_shown_ref`, `_shown_needs`; `_store_ref`, `_same_sess` and `_role_name` are `fleet/sessions_registry.py`'s) and the ledger's one lock (`_OWED_LOCK`).

server.py is being split into one module per area (CONTRIBUTING.md, Layout). The module needs nothing of server.py (a module here cannot import it, and it runs as `__main__`): it reads the config, the page and project
modules, the registry readers (`service/gates.py`), the session helpers (`fleet/sessions_registry.py`) and the instance settings and text clipping (`core/instance.py`, `model/bullet_text.py`). server.py imports the names its own code reads from here (`_owed_mark` and the others it calls), and the suites and
scripts read and set every other name on this module. `_owing_note` has no caller here and is not a name of server.py: the create and update tables look it up on this module when a write runs
(`_late_in`), and a suite that stubs it (`page_debts._owing_note = ...`) stubs it here, which reaches every caller. No board write is refused or held for a page debt: the debt stays in the ledger and the write's reply says so. `_page_ts` is called here by `_owed_settle` and by the client API's page-ts answer in server.py, which reads it on this module too: the suites that put a page's time in place of the real one
set it here, and that reaches both callers. `_HERE` is the checkout's root, read only in the message that names the `pages.py clear` command."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from stackshot import paths as _paths
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import xlock as _xlock
from stackshot.fleet import sessions_registry as _sr
from stackshot.model.needs import _NEEDS_KINDS
from stackshot.projects import brains as _brains
from stackshot.projects import page_upstream as _upstream
from stackshot.projects import pages as _pages
from stackshot.projects import project_registry as _pr
from stackshot.projects import projects as _prj
from stackshot.router import page_debt as _page_debt
from stackshot.web import render as _rmod
from stackshot.service import gates as _gates
from stackshot.fleet.sessions_registry import _same_sess, _session_label, _sessions_index

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


def _upstream_ts(key: str) -> int:
    """For a page whose local copy leaves a debt open: the time of the newest edit that the copy's remote holds and the copy has not pulled yet (page_upstream),
    0 = none, or it cannot tell. Begins a fetch and never waits for it, so a write is not slowed: what it reads is what an earlier fetch brought."""
    try:
        return _upstream.edit_ts(key, 0)
    except Exception:  # noqa: BLE001
        return 0


def _upstream_settles(key: str, owner: str, e: dict[str, Any], edit: int) -> bool:
    """Does that edit (`edit`, _upstream_ts) settle this debt? False whenever it cannot tell."""
    try:
        since = int(float(e.get("ts", 0))) - _page_slack()
        if not edit or edit < since:
            return False
        return not _debt_strict(owner, e) or _upstream.ct_changed(key, since)
    except Exception:  # noqa: BLE001
        return False


def _owed_path() -> Path:
    p = _cfg.state("ledger.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


_OWED_LOCK = _xlock.XLock("ledger")     # the page-debt ledger is read, changed and rewritten whole: one thread at a time (a read-change-write holds it from its read to its write)


def _salvage_ledger(text: str) -> dict[str, Any]:
    """What a ledger that does not parse still holds: the pages, writers and entries that were written out whole before the text went wrong (a write cut short, a bad
    byte). {page key: {writer: entry}}; an entry is taken only whole, a page or a writer's list as far as it was read."""
    dec, n = json.JSONDecoder(), len(text)

    def ws(i: int) -> int:
        while i < n and text[i] in " \t\r\n":
            i += 1
        return i

    def members(i: int, depth: int) -> tuple[dict[str, Any], int | None]:
        """The members read of the object at text[i], and the index after it (None when it ended unread). Objects `depth` levels down are read into, the rest whole or not at all."""
        out: dict[str, Any] = {}
        i = ws(i)
        if i >= n or text[i] != "{":
            return out, None
        i += 1
        first = True
        while True:
            i = ws(i)
            if i >= n:
                return out, None
            if text[i] == "}":
                return out, i + 1
            if not first:
                if text[i] != ",":
                    return out, None
                i = ws(i + 1)
            first = False
            try:
                k, i = dec.raw_decode(text, i)
                if not isinstance(k, str):
                    return out, None
                i = ws(i)
                if i >= n or text[i] != ":":
                    return out, None
                i = ws(i + 1)
                if depth and i < n and text[i] == "{":
                    out[k], i = members(i, depth - 1)
                    if i is None:
                        return out, None
                else:
                    out[k], i = dec.raw_decode(text, i)
            except ValueError:
                return out, None

    return members(0, 1)[0]


def _owed_unreadable(path: Path, text: str | None, why: BaseException) -> dict[str, Any]:
    """A ledger that cannot be read is never written over: it is moved aside (`ledger.json.unreadable-<time>`, what a person can look at or mend), a line on stderr says so (once: the
    file is gone from its place after), and the debts that could be read from it are written back as the ledger. Returns them (the raw ledger form). Called with the lock held."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    aside = path.with_name(f"{path.name}.unreadable-{stamp}")
    for i in range(2, 100):
        if not aside.exists():
            break
        aside = path.with_name(f"{path.name}.unreadable-{stamp}-{i}")
    kept = _salvage_ledger(text) if text else {}
    n = sum(1 for v in kept.values() if isinstance(v, dict) for e in v.values() if isinstance(e, dict) and e.get("ts"))
    try:
        os.replace(path, aside)
        said = f"it is kept as {aside}"
    except OSError as e:
        said = f"it could not be moved aside ({type(e).__name__}) and stays where it is"
    print(f"page debts: the ledger {path} could not be read ({type(why).__name__}); {said}; {n} debt(s) are kept from what could be read", file=sys.stderr)
    if kept and not path.exists():
        _owed_save(kept)
    return kept


def _owed_load() -> dict[str, dict[str, dict[str, Any]]]:
    try:
        with _OWED_LOCK:
            path = _owed_path()
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                return {}
            except OSError as e:
                raw: Any = _owed_unreadable(path, None, e)
            else:
                try:
                    raw = json.loads(data.decode("utf-8"))
                    if raw is not None and not isinstance(raw, dict):
                        raise ValueError("the ledger is not an object")
                except ValueError as e:      # a cut or damaged file (UnicodeDecodeError and JSONDecodeError are ValueErrors)
                    raw = _owed_unreadable(path, data.decode("utf-8", "replace"), e)
    except Exception:
        return {}
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for k, v in (raw or {}).items():
        hits = _gates.registry_hits("projects", k)
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
    keeper the page's compiled truth must have changed too — a timeline line alone does not settle it.
    The ledger is read under its lock, the pages' git is read with none held (a page's time and its compiled truth are subprocesses that can take seconds, and every writer of the ledger waits on the lock),
    and the verdicts are applied under the lock again to the ledger as it stands then: an entry a writer replaced since (a different `ts`) is left for the next pass."""
    with _OWED_LOCK:
        snap = json.loads(json.dumps(_owed_load()))      # the ledger as read; the verdicts below are worked out on this copy
    gone_keys: set[str] = set()                           # a brain now marked shared: its debts owe nothing
    drops: list[tuple[str, str, Any]] = []                # (key, debtor, the entry's ts when it was read): settled
    strips: list[tuple[str, str, bool]] = []              # (key, debtor, drop the whole entry): a retired agent's line, or a retired-only entry
    for key in list(snap):
        if _brains.shared_refusal(key):     # a debt an earlier run charged on a page of a brain now marked shared: it owes nothing, so it is dropped
            gone_keys.add(key)
            continue
        if _owed_brain_skip(key):       # a second brain whose copy cannot be read: its debts are kept as they are, not settled or charged this run
            continue
        pt: float | None = None         # the page's time (a git log), read once per key
        ahead: int | None = None        # the time of an edit the copy has not pulled (another git log), read once per key, and only for a debt the copy leaves open
        for o in list(snap[key]):
            e = snap[key][o]
            if e.get("retired_only"):       # an entry an earlier release wrote for a retired agent's line (stackshot removes that line itself now): it owes nothing
                strips.append((key, o, True))
                continue
            if "retired" in e:              # …and the same release's line on an entry that also owes a debt: the debt stays, the line goes
                strips.append((key, o, False))
            ts = float(e.get("ts", 0))
            if pt is None: pt = _page_ts(key)
            local = pt >= ts - _page_slack()
            if local and _debt_strict(o, e):
                try:
                    local = bool(_pages.ct_changed_since(key, int(ts)))
                except Exception:       # a read that fails cannot tell: the debt stays (an answer that cannot be had settles nothing)
                    local = False
            if not local:
                if ahead is None: ahead = _upstream_ts(key)
                local = _upstream_settles(key, o, e, ahead)
            if local:
                drops.append((key, o, e.get("ts")))
    with _OWED_LOCK:
        d = _owed_load(); changed = False
        for key in gone_keys:
            if key in d:
                del d[key]; changed = True
        for key, o, whole in strips:
            e = d.get(key, {}).get(o)
            if e is None:
                continue
            if whole and e.get("retired_only"):
                del d[key][o]; changed = True
            elif not whole and "retired" in e:
                del e["retired"]; changed = True
        for key, o, ts in drops:
            if key in d and o in d[key] and d[key][o].get("ts") == ts:
                del d[key][o]; changed = True
        for key in [k for k in d if not d[k]]:
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
    """Appended to replies: the caller's own debts in full (when the call names its owner), everyone else's as one line of page keys."""
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
                   + "Your board writes go through while it is owed. "
                   + f"Board-only edit that changed no state: `python3 {_HERE}/stackshot/projects/pages.py clear <key>` (on another box, the same from the checkout there). "
                     "Such a box needs `[release] deploy_ssh` in its config, naming the server host, so that the clear runs there, or `[server] box = false`, so that it prints the command to run there; "
                     "with neither it counts as the server host and the server's entry stays.")
    if others:
        out.append("pages owed by others: " + ", ".join(dict.fromkeys(k for k, _o, _e in others)))      # the page keys only, once each, in ledger order: no session, age or keeper text
    return ("\n\n" + "\n".join(out)) if out else ""


def _owing_note(owner: str) -> str:
    """The one line a write's reply carries when the write went through while its writer had a page owed longer than the grace, else "". A board write is
    never refused or held for a page debt: the debt stays in the ledger (and in the brief and the pages owed) and settles as before, when the page's Current
    state is edited and the server has seen the edit, in its copy of the pages or in what it fetched of that copy's remote. Read before the write records its own debt."""
    if not owner:
        return ""
    try:
        grace = _grace_min() * 60
        d = _owed_readable(_owed_settle()); owner = _session_id(owner)
        late = [(k, e) for k, os_ in d.items() for o, e in os_.items() if _same_sess(o, owner) and time.time() - float(e.get("ts", 0)) > grace
                and not e.get("moves")]    # a writer's pilot debt moves to the keeper instead (_pilot_fallback_tick)
    except Exception:  # noqa: BLE001  — fail-open: a ledger that cannot be read is no reason to fail the write; the note is left out
        return ""
    if not late:
        return ""
    return ("\nThis write went through. Still owed by you: " + ", ".join(f"{k} (since {e.get('item') or 'a board change'}, {_age(e['ts'])} ago)" for k, e in late)
            + "; it stays owed until the page's Current state is edited"
            + (" and the server has seen that edit." if _cfg.page_flavor() == "gbrain" else "."))
