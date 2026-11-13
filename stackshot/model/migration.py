"""migration.py — the planner of the item model's migration (the design: docs/design, sections 2, 5, 6 and 9, and
its build plan, Step 4).

The migration moves every item onto the model: an open item gets stored what model.derive only infers (its mover, `then`, the wait's kind, input and post-wake mover), the guards'
residue is filled where the item states what is missing, and a closed item without an outcome gets one. This module is the PLAN, pure of the server: it reads items, the session
registry, the fleet and the anchors (through model_guards.Ctx) and returns writes and residue lists; it changes nothing. tools/migrate_model.py runs it (and the cold call it needs),
and the server applies the writes (server.py `_migrate_apply`, behind POST /client/migrate): the script plans, the server is the only writer.

A write is `{item, set, drop, expect, kind, note}`: the metadata fields to set and to drop, the item's `updated` it was planned on (an item that moved since is planned again, never
overwritten), the transition it stands for and a one-line note for the History (no issue comment since an earlier change). The migration records no hand-off, sends no notice and wakes nobody (the server holds the
board-wide pause while it applies, and the due waits fire in one batch when it lifts).

What each open item gets, by the table of section 2 (the mover and the post-wake mover are what model.derive reads today, so an item reads the same before and after):
  your-call, your-step    alive, <owner>: mover the owner, `then` the asker
  doing                   alive, the agent: mover the first session in needs, else the owner
  outside                 waiting on an anchor (the one scoped to the item) or on the owner's relay: wait_kind, the anchor or the party as the event, ask_by the day to chase
  blocked                 waiting on an item: wait_kind item (after stays)
  parked, verifying       waiting on a time: wait_kind time (wake, or a verifying item's end)
and the residue of the guards:
  wait input, wait with no end   the input and the end from the item's own fields (party, chase, wake, the anchor scoped to it), else from a confident read of its text; else listed
  snooze                         the hold stays when a quote of his that parks is found in the item's answers (copied, never typed); otherwise the hold goes and the item is alive with its last mover
  next line with no name         the line gets the item's mover as its name
  mover gone                     the project's background agent takes the item
  a wait hidden in next          a confident read of the text sets the wait; the rest are listed
A state-defining write the guards would still refuse is not made (the item stays as it is, on the old machinery, and is listed); the text edit that passes alone is."""
from __future__ import annotations

import copy
import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from stackshot.anchors import anchors as _anc
from stackshot.anchors import anchor_scope as _ascope
from stackshot.model import cold_call as _cold
from stackshot.core import config as _cfg
from stackshot.router import routing as _routing
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.router import router as _router
from stackshot.fleet import sessions_registry as _sr
from stackshot.model import states as _states
from stackshot.waits import waiting as _wt

# the metadata fields a planned write may set or drop (the server's route refuses any other), split by status: an open item takes the model's fields and never an outcome, a closed one only its
# outcome. `needs` follows a mover swap (the one session that moves the item now).
OUTCOME_FIELDS = frozenset({"outcome", "reason", "superseded_by"})
OPEN_SET_FIELDS = frozenset({"mover", "then", "wait_kind", "wait_anchor", "wait_event", "ask_by", "post_wake_mover", "next", "cap_ok", "wait_basis", "wake", "hold", "hold_set", "after",
                             "needs"})
SET_FIELDS = OPEN_SET_FIELDS | OUTCOME_FIELDS
DROP_FIELDS = frozenset({"hold", "hold_set", "state", "mover", "then", *_states.CARRY_FIELDS})
MODEL_KEYS = ("mover", "then", "wait_kind", "wait_anchor", "wait_event", "ask_by", "post_wake_mover")
DEFINING = (*MODEL_KEYS, "wake", "hold", "hold_set", "after", "cap_ok", "wait_basis", "needs")     # what defines an item's state: stripped from a write the guards would refuse
RESIDUE_GUARDS = ("wait_input", "no_end", "snooze", "mover", "post_wake")                   # the guards whose refusal means the state cannot be written whole
AUTHOR = "migration"
# The event paths that still notify while the pass holds the board, each a person's or a session's own act (the pass writes through none of them); an item one moves is `moved` when the pass reaches it.
MID_PASS_PATHS = (
    "a keeper's ruling on an anchor notice (`_route` → `anchor_release` in service/wakes.py): a held item that waited on that anchor is released and its session told; the waits' watchers stand still (the hold)",
    "a session closing an item (`release_after` in service/wakes.py): an item with an old `after` wait that closes the last blocker wakes and its session is told; a watched item's wait stands still (the hold)",
    "any session's own update, answer or comment on an item: the usual History line, notices and hand-off record, as ever",
)


def clean(v: Any) -> str:
    return " ".join(str(v or "").split())


def shown(gid: str) -> str:
    return f"board#{gid[1:]}" if re.fullmatch(r"[gl]\d+", gid) else gid


def day_of(v: Any) -> str:
    """The date part (YYYY-MM-DD) of a wake or end, '' when it is none."""
    m = re.match(r"\d{4}-\d{2}-\d{2}", clean(v))
    return m.group(0) if m else ""


def _num(gid: str) -> tuple[str, int]:
    return gid[:1], int("".join(c for c in gid if c.isdigit()) or 0)


def _tz() -> dt.tzinfo:
    from stackshot.core import config as _cfg
    return _cfg.tz()


@dataclass
class Write:
    gid: str
    kind: str                               # the transition it stands for: "doing → alive, an agent", "closed: done", …
    set: dict[str, Any] = field(default_factory=dict)
    drop: list[str] = field(default_factory=list)
    expect: float = 0.0                     # the item's `updated` when planned
    note: str = ""
    sig: list[int] = field(default_factory=list)     # activity_sig of the item when planned: set by the script; the server checks it again with the write

    def empty(self) -> bool:
        return not self.set and not self.drop

    def as_body(self) -> dict[str, Any]:
        return {"item": shown(self.gid), "kind": self.kind, "set": self.set, "drop": self.drop, "expect": self.expect, "expect_sig": list(self.sig), "note": self.note}


def activity_sig(item: dict[str, Any], comments: int) -> list[int]:
    """What an answer or a comment changes without moving the item's `updated`: [its stored answers, 0: the mirror keeps no copy of the issue's comments since an earlier change, and the owner's own comment on GitHub is an answer on the item]. A write is planned on it and refused as `moved` when it differs."""
    return [len([a for a in (item.get("metadata") or {}).get("answers") or [] if isinstance(a, dict)]), int(comments)]


@dataclass
class Residue:
    gid: str
    kind: str                               # a guard key (model_guards.GUARDS), or: mover_gone, hidden_wait, closed_unread, snooze_alive, next_unnamed, refused, error
    why: str
    hand: bool = True                       # left for a person to set by hand (False: the plan dealt with it and says how)
    fields: tuple[str, ...] = ()            # the exact fields a person must set (wait_event, wait_anchor, after, ask_by, wake)
    default: str = ""                       # a default the migration stored (ask_by) that its owner is to replace; or, for an item left whole, the one it would have stored

    def as_dict(self) -> dict[str, Any]:
        return {"item": shown(self.gid), "kind": self.kind, "why": self.why, "hand": self.hand, "fields": list(self.fields), "default": self.default}


@dataclass
class Plan:
    writes: list[Write] = field(default_factory=list)
    residue: list[Residue] = field(default_factory=list)
    kinds: dict[str, str] = field(default_factory=dict)                   # open item → its transition label
    outcome: dict[str, str] = field(default_factory=dict)                 # open item → written | skipped (already so) | left (a state write the guards would refuse)
    proposals: list[dict[str, Any]] = field(default_factory=list)         # the hidden-wait reads: item, why, status, answer, applied
    wants_read: dict[str, dict[str, Any]] = field(default_factory=dict)   # gid → {why, lines}: the items the cold call must read before the final plan
    relay_post: dict[str, tuple[str, str]] = field(default_factory=dict)  # a relay wait's post-wake mover chosen here: gid → (who, where the record has it: stored mover | hand-off | needs | then | owner | background agent)
    reassigned: list[str] = field(default_factory=list)                   # the items whose mover or post-wake mover was replaced by another session (the pass keeps the last mover as recorded: only a gone one that is no front agent)

    def note(self, gid: str, kind: str, why: str, hand: bool = True, fields: tuple[str, ...] = (), default: str = "") -> None:
        if not any(r.gid == gid and r.kind == kind for r in self.residue):
            self.residue.append(Residue(gid, kind, why, hand, fields, default))

    def transitions(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for g, k in self.kinds.items():
            out.setdefault(k, []).append(g)
        return out


# ---------------------------------------------------------------------------------------------------------------- what the plan reads
class Env:
    """What a plan reads that is not in the items: the clock, the guards' Ctx (sessions, fleet, project pages), the anchors, and the one-time reads. `reads` is {gid: read} from the cold
    call ({status, answer (validated) | None, why}); empty on the first pass, where the plan says which items it wants read."""

    def __init__(self, items: dict[str, dict[str, Any]], ctx: "_mg.Ctx", anchors: dict[str, list[dict[str, Any]]] | None = None, today: dt.date | None = None,
                 reads: dict[str, dict[str, Any]] | None = None, one_mover: bool = True, label: Callable[[str], str] | None = None,
                 notices: Callable[[str, float], list[dict[str, Any]]] | None = None) -> None:
        self.items = items
        self.ctx = ctx
        self.now = ctx.now
        self.today = today or dt.datetime.fromtimestamp(ctx.now, _tz()).date()
        self.anchors = anchors if anchors is not None else _anc.load()
        self.reads = reads or {}
        self.one_mover = one_mover
        self._label = label
        self._notices = notices

    def notices(self, project: str, since: float) -> list[dict[str, Any]]:
        """What anchor-hub logged for the project since `since` (the routing log, oldest first); [] when it cannot be read."""
        try:
            return list((self._notices or _routing.read)(project, since))
        except Exception:  # noqa: BLE001
            return []

    def after_open(self, it: dict[str, Any]) -> list[str]:
        return [g for g in _wt.after_of(it.get("metadata") or {}) if (self.items.get(g) or {}).get("status") == "open"]

    def scoped(self, project: str, gid: str) -> list[str]:
        return [str(e.get("url") or "") for e in _ascope.anchor_scope(self.anchors, gid, project) if e.get("url")]

    def anchored(self, gid: str, project: str) -> Callable[[dict[str, Any]], bool]:
        return lambda _it: bool(self.scoped(project, gid))

    def derive(self, gid: str, it: dict[str, Any]) -> "_model.Model":
        project = clean((it.get("metadata") or {}).get("project"))
        return _model.derive(it, self.now, self.after_open, self.anchored(gid, project))

    def label(self, who: str) -> str:
        """A session reference as people write it in a next line: the owner, the registry's name, else the fleet's, else the reference as it stands."""
        w = clean(who)
        if not w or _model.is_owner(w):
            return _model.owner_display()
        if self._label:
            return self._label(w)
        try:
            n = _sr.display_name(w)
        except Exception:  # noqa: BLE001
            n = None
        if n:
            return n
        by_id = self.ctx.rows().get(w)
        if isinstance(by_id, dict) and by_id.get("name"):
            return str(by_id["name"])
        rows = [r for r in self.ctx.rows().values() if isinstance(r, dict) and r.get("name") == w]
        return str(rows[0].get("name")) if rows else w

    def background(self, project: str) -> list[str]:
        """The project's background agents, the builder first (the same ranking as server._handoff_ranked, which the hand-off machinery falls to): those of the page whose hub is the
        project's; class 0 a mandate that says build, 1 one that says maintain, merge or engineer, 2 the rest."""
        try:
            reg = self.ctx.reg()
            roles = self.ctx.roles()
            hub = _anc.hub_of(project, reg)
            out = []
            for i, (n, r) in enumerate(roles.items()):
                if r.get("role") != "back" or _anc.hub_of(r.get("project", ""), reg) != hub:
                    continue
                mand = str(((reg.get(r.get("project", "")) or {}).get("agents") or {}).get(n) or "")
                out.append((0 if re.search(r"\bbuild", mand, re.I) else 1 if _router._BUILDER.search(mand) else 2, i, n))
            return [n for _a, _b, n in sorted(out)]
        except Exception:  # noqa: BLE001
            return []

    def is_front(self, who: str, project: str) -> bool:
        """Is `who` a user-facing (front) agent of the project's hub: a page's `agents:` entry outside `background:`, or its name line? The pass never takes an item from one."""
        try:
            roles = self.ctx.roles()
            names = {who}
            try:
                names |= {_sr.display_name(who) or "", *_sr.names_of(who)}
            except Exception:  # noqa: BLE001
                pass
            key = next((n for n in names if n and n in roles and roles[n].get("role") != "back"), "")
            if not key or not project:
                return False
            reg = self.ctx.reg()
            return _anc.hub_of(roles[key].get("project", ""), reg) == _anc.hub_of(project, reg)
        except Exception:  # noqa: BLE001
            return False

    def relay_post(self, it: dict[str, Any], project: str) -> tuple[str, str]:
        """The post-wake mover of a relay wait: the last agent that moved the item, else its owner, and never the owner (he relays the news, an agent moves on it, and the session that takes it is
        recorded as the mover). From the record, in this order: the mover it stores, the session its hand-off record names, the session in its needs, its `then`, its owner; the first that can
        be a mover now. → (who, where the record has it), or ("", "") when none can."""
        from stackshot.waits import handoff as _ho
        m = it.get("metadata") or {}
        rec = _ho.record_of(it) or {}
        cands = [(clean(m.get("mover")), "stored mover"), (clean(rec.get("to")), "hand-off"), (next(iter(_states.sessions_of(m)), ""), "needs"), (clean(m.get("then")), "then"), (clean(m.get("owner")), "owner")]
        for who, src in cands:
            if who and not _model.is_owner(who) and not self.ctx.mover_problem(who, project):
                return who, src
        return "", ""

    def take_over(self, project: str) -> str:
        """The background agent that takes an item whose mover is gone: the first of the project's that can be a mover now."""
        for n in self.background(project):
            if not self.ctx.mover_problem(n, project):
                return n
        return ""

    def resolve(self, text: str) -> str:
        """An item id as the call wrote it (board#N, #N, g7) → the store's id when that item exists, else ''."""
        m = re.search(r"(?:board)?#?\s*([a-z]?)(\d+)", clean(text).lower())
        if not m:
            return ""
        cands = [f"{m.group(1)}{m.group(2)}"] if m.group(1) else [f"g{m.group(2)}", f"l{m.group(2)}"]
        return next((c for c in cands if c in self.items), "")

    def choices(self, gid: str, it: dict[str, Any], mod: "_model.Model | None" = None) -> dict[str, str]:
        """The names a post-wake mover may be offered as → the reference stored: the owner, the item's own mover or post-wake mover, its owner, the sessions in its needs and the project's
        background agents; only those the guards would accept now."""
        m = it.get("metadata") or {}
        project = clean(m.get("project"))
        refs = [_model.owner_display()]
        if mod is not None:
            refs += [mod.mover, mod.wait.post_wake_mover if mod.wait else ""]
        refs += [clean(m.get("owner")), *_states.sessions_of(m), *self.background(project)]
        out: dict[str, str] = {}
        for r in refs:
            r = clean(r)
            if r and not self.ctx.mover_problem(r, project):
                out.setdefault(self.label(r), r)
        return out


# ---------------------------------------------------------------------------------------------------------------- next lines
def next_lines(text: Any) -> list[tuple[int, str, str]]:
    """[(line index in text.splitlines(), the raw line, the name before its colon or "")] for the top-level lines of next, as model_guards.next_openers reads them (a fenced block, a
    server note in parentheses, an indented continuation and a blank line are no lines of the item's own next)."""
    raw_all = str(text or "")
    masked = _mg._FENCE_RX.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), raw_all).splitlines()
    out: list[tuple[int, str, str]] = []
    for i, raw in enumerate(raw_all.splitlines()):
        mk = masked[i] if i < len(masked) else raw
        if not mk.strip() or mk[:1] in (" ", "\t"):
            continue
        c = _mg._MARK_RX.sub("", mk.strip().replace("**", ""))
        if not c or c.startswith("("):
            continue
        m = _mg._NAME_RX.match(c)
        out.append((i, raw, m.group("name") if m else ""))
    return out


def _owner_lead() -> "re.Match[str] | None":
    """The pattern of a nameless line that opens with the owner's name or an alias and no colon ("<owner> reviews the draft"); None when no name is known."""
    names = _cfg.owner_names()
    if not names:
        return None
    return re.compile(r"^(?P<who>" + "|".join(re.escape(n) for n in names) + r")(?:\s+to)?\s+(?P<rest>\S.*)$")


def name_next(text: Any, mover_label: str, roster: set[str]) -> tuple[str, list[str], str]:
    """(the next text with every nameless top-level line given a name, the lines changed, why it could not: "") for a next whose lines do not all say who takes them. A line that opens
    with the owner's name and no colon ("the owner reviews the draft") becomes `<owner>: reviews the draft`; any other nameless line is prefixed `<mover>: `. A name the guard would not know (no
    roster entry) is no name: nothing is written, the reason says so. Lines already named, notes and continuation lines stay as they are."""
    lines = str(text or "").splitlines()
    names = roster | _mg.owner_names_cf()
    known = lambda n: bool(n) and (n.casefold() in names or n.casefold().startswith("cse_"))
    changed: list[str] = []
    for i, raw, name in next_lines(text):
        if name and (known(name) or not roster):
            continue
        marker = _mg._MARK_RX.match(raw).group(0)
        body = raw[len(marker):]
        plain = body.replace("**", "")
        lead = _owner_lead()
        m = lead.match(plain) if lead else None
        if m and not _mg._NAME_RX.match(plain):
            new = f"{marker}{_model.owner_display()}: {m.group('rest')}"
        else:
            if not known(mover_label) and roster:
                return str(text or ""), [], f"its mover {mover_label!r} is no name the guard knows, so a line cannot be given one"
            new = f"{marker}{mover_label}: {body}"
        lines[i] = new
        changed.append(new)
    if not changed:
        return str(text or ""), [], ""
    return "\n".join(lines) + ("\n" if str(text or "").endswith("\n") else ""), changed, ""


# ---------------------------------------------------------------------------------------------------------------- his words behind a hold
def park_quote(item: dict[str, Any], now: float) -> dict[str, Any] | None:
    """The newest entry of the item's answers that the store attributes to the owner (the board's answer form or his own GitHub comment, with text) that reads as a park and stands behind the
    current wake (waiting.entry_pairs, without a git history: given since the move that set the wake, or at most a day before it) → the entry, else None. The text is copied from
    the entry, never typed (tools/cap_words.py does the same for its handful of items)."""
    m = item.get("metadata") or {}
    best = None
    for a in m.get("answers") or []:
        if not isinstance(a, dict) or a.get("kind") not in ("decision", "comment") or a.get("via") not in ("board", "github"):
            continue
        text = _wt.answer_words(a)
        if not text or (a.get("via") == "github" and (a.get("comment_id") is None or not clean(a.get("url")))):
            continue
        if not _wt.answer_parks(a):
            continue
        ok, _how = _wt.entry_pairs(item, a.get("ts"), now, None)
        if not ok:        # no git history here: the hold's own stamp is the move that set the wake; his words at most a day before it (or just after: the stamp is the session's, a moment later)
            hs = m.get("hold_set") if isinstance(m.get("hold_set"), dict) else {}
            try:
                lead = float(hs.get("at")) - float(a.get("ts"))
            except (TypeError, ValueError):
                lead = None
            ok = lead is not None and -60.0 <= lead <= _wt.PAIR_LEAD_SECONDS
        if ok and (best is None or float(a.get("ts") or 0) > float(best.get("ts") or 0)):
            best = a
    return best


def cap_ok_from(item: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """metadata.cap_ok for the item's wake from his stored entry: the wake, who recorded it, his quote and where it came from."""
    m = item.get("metadata") or {}
    co = dict(m["cap_ok"]) if isinstance(m.get("cap_ok"), dict) else {}
    when = dt.datetime.fromtimestamp(float(entry.get("ts") or 0), _tz()).strftime("%a %b %d %H:%M")
    co.update(wake=m.get("wake"), by=f"{AUTHOR} (copied from his stored answer)", quote=_wt.answer_words(entry),
              source=f"{_model.owner_display()}'s {'comment' if entry.get('kind') == 'comment' else 'answer'} on {'the board' if entry.get('via') == 'board' else 'GitHub'}, {when} {_cfg.tz_abbr()}")
    return co


# ---------------------------------------------------------------------------------------------------------------- the guards on the item as a write would leave it
def after_state(it: dict[str, Any], set_: dict[str, Any], drop: list[str]) -> dict[str, Any]:
    """The item as the write would leave it (a copy)."""
    new = copy.deepcopy(it)
    meta = new.setdefault("metadata", {})
    for k in drop:
        meta.pop(k, None)
    meta.update(copy.deepcopy(set_))
    return new


def problems(env: Env, gid: str, after: dict[str, Any]) -> list[_mg.Problem]:
    """What the guards, judging every field of the item as it would stand, find wrong with it."""
    project = clean((after.get("metadata") or {}).get("project"))
    try:
        probs, _flags = _mg.check(after, env.ctx, touched=None, gid=gid, after_open=lambda i: env.after_open(i), anchored=env.anchored(gid, project), one_mover=env.one_mover, windows_text="")
    except Exception as e:  # noqa: BLE001
        return [_mg.Problem("error", f"the guards could not read it: {type(e).__name__}: {e}")]
    return probs


def missing_fields(env: Env, gid: str, after: dict[str, Any], key: str) -> tuple[str, ...]:
    """The exact fields a person must set for the guard `key` (wait_input | no_end) to pass on the item as it stands: wait_anchor, wait_event, after, wake, ask_by."""
    if key == "no_end":
        return ("ask_by",)
    try:
        w = env.derive(gid, after).wait
    except Exception:  # noqa: BLE001
        return ()
    if w is None:
        return ()
    out: list[str] = []
    if w.kind == "anchor":
        if not (w.anchor or env.scoped(clean((after.get("metadata") or {}).get("project")), gid)):
            out.append("wait_anchor")
        if not w.event:
            out.append("wait_event")
    elif w.kind == "item":
        if not w.after:
            out.append("after")
    elif w.kind == "relay":
        if not w.event:
            out.append("wait_event")
    elif w.kind == "time":
        if not w.until:
            out.append("wake")
    return tuple(out)


DEFAULT_END_DAYS = 14        # a default backstop for a wait with no end: this many days from the pass
EXPECTED_PLUS_DAYS = 2       # …or, for a wait on other items, the latest expected-by of the open ones plus this many days


def default_end(env: Env, it: dict[str, Any], kind: str) -> tuple[str, str]:
    """(the default ask_by day, how it was chosen) for a wait that has no end. An item wait: the latest expected-by among the open items it waits after, plus two days, when that day is still
    ahead; else, and for a relay or anchor wait, 14 days from the day of the pass. It is a backstop the owner replaces, never a promise."""
    plain = env.today + dt.timedelta(days=DEFAULT_END_DAYS)
    if kind == "item":
        days = []
        for g in env.after_open(it):
            d = day_of(((env.items.get(g) or {}).get("metadata") or {}).get("expected_by"))
            if d:
                days.append(dt.date.fromisoformat(d))
        if days:
            cand = max(days) + dt.timedelta(days=EXPECTED_PLUS_DAYS)
            if cand > env.today:
                return cand.isoformat(), f"the latest expected-by of the items it waits after ({max(days).isoformat()}) plus {EXPECTED_PLUS_DAYS} days"
    return plain.isoformat(), f"{DEFAULT_END_DAYS} days from the pass"


def gone(env: Env, who: str, project: str) -> str:
    """Why `who` cannot be a mover (or a post-wake mover) now, "" when it can: the guards' own test."""
    return env.ctx.mover_problem(who, project) if who else "is no one"


# ---------------------------------------------------------------------------------------------------------------- one open item
def _take(env: Env, plan: Plan, gid: str, who: str, project: str, what: str) -> tuple[str, bool]:
    """(the mover to store, whether it had to be replaced): `who` when it can move the item; else the project's background agent (listed, nothing for a person to do); else `who` and the
    item is listed for hand setting."""
    why = gone(env, who, project)
    if not why:
        return who, False
    if env.is_front(who, project):
        plan.note(gid, "mover_gone", f"its {what} {env.label(who)} is a front agent and {why}: the pass keeps the last mover as the item records it and reassigns none; set by hand")
        return who, False
    alt = env.take_over(project)
    if alt:
        plan.note(gid, "mover_gone", f"its {what} {env.label(who)} {why}: the project's background agent {env.label(alt)} takes it", hand=False)
        plan.reassigned.append(gid)
        return alt, True
    plan.note(gid, "mover_gone", f"its {what} {env.label(who) or 'is no one'} {why}, and the project has no background agent that can take it")
    return who, False


def _fill_wait(env: Env, plan: Plan, gid: str, it: dict[str, Any], mod: "_model.Model") -> tuple[dict[str, Any], list[str]]:
    """The wait fields a waiting item should store, from what the item itself holds: its kind, the post-wake mover (the project's background agent when it is gone), an anchor scoped to it
    (the one, or the one its text names), the party as the event, the chase day or the wake day as the end. → (the fields, notes on what could not be chosen)."""
    m = it.get("metadata") or {}
    w = mod.wait
    assert w is not None
    project = clean(m.get("project"))
    out: dict[str, Any] = {"wait_kind": w.kind}
    extra: list[str] = []
    want = w.post_wake_mover
    if w.kind == "relay" and not w.post_explicit:        # the model's default for a relay is the owner; he relays the news and never moves on it: the last agent mover moves on it
        who, src = env.relay_post(it, project)
        if not who:                                      # no agent on its record can move it now: the project's background agent, else nobody is stored and it is listed
            who, src = env.take_over(project), "background agent"
            if who:
                plan.note(gid, "relay_post", f"no agent on its record (mover, hand-off, needs, then) can move it now: the project's background agent {env.label(who)} is its post-wake mover", hand=False)
        if who:
            plan.relay_post[gid] = (who, src)
            out["post_wake_mover"] = who
            want = ""
        else:
            plan.relay_post[gid] = ("", "none")
            plan.note(gid, "post_wake", "a relay wait with no agent on its record that can move it, and no background agent in the project: set its post_wake_mover by hand", fields=("post_wake_mover",))
            want = ""
    if want:
        post, _swapped = _take(env, plan, gid, want, project, "post-wake mover")
        out["post_wake_mover"] = post
    end_day = day_of(m.get("ask_by")) or day_of(m.get("chase"))
    event = clean(m.get("wait_event")) or clean(m.get("party"))
    if w.kind == "anchor":
        url = clean(m.get("wait_anchor"))
        if not url:
            scoped = env.scoped(project, gid)
            if len(scoped) == 1:
                url = scoped[0]
            elif scoped:
                text = " ".join(str(x) for x in (it.get("subject"), it.get("description"), m.get("next")))
                named = [u for u in scoped if u in text or (len(u.rstrip("/").rsplit("/", 1)[-1]) > 3 and u.rstrip("/").rsplit("/", 1)[-1] in text)]
                if len(named) == 1:
                    url = named[0]
                else:
                    extra.append(f"{len(scoped)} anchors are scoped to it ({', '.join(scoped)}) and none could be picked from its text")
        if url:
            out["wait_anchor"] = url
        if event:
            out["wait_event"] = event
        if end_day and not w.backstop and not m.get("ask_by"):
            out["ask_by"] = end_day
    elif w.kind == "relay":
        if event:
            out["wait_event"] = event
        end = end_day or day_of(m.get("wake"))
        if end and not m.get("ask_by"):
            out["ask_by"] = end
    elif w.kind == "item":
        if end_day and not w.backstop and not m.get("ask_by"):
            out["ask_by"] = end_day
    return out, extra


def _hidden_record(plan: Plan, gid: str, read: dict[str, Any]) -> dict[str, Any]:
    rec = {"item": shown(gid), "why": read.get("why", ""), "status": read.get("status", ""), "answer": read.get("answer"), "applied": False, "asked": read.get("asked", "")}
    plan.proposals.append(rec)
    return rec


def _commit(env: Env, plan: Plan, gid: str, it: dict[str, Any], kind: str, set_: dict[str, Any], drop: list[str], notes: list[str], mover_label: str) -> None:
    """Name the nameless lines of next, judge the item as the write would leave it, and record the write: a state the guards would still refuse is not written (it is listed), the text
    edit alone is."""
    m = it.get("metadata") or {}
    nxt, changed, why = name_next(m.get("next"), mover_label, env.ctx.roster())
    if changed:
        set_["next"] = nxt
        notes.append(f"{len(changed)} next line{'s' if len(changed) > 1 else ''} named")
    elif why:
        plan.note(gid, "next_unnamed", why)
    probs = problems(env, gid, after_state(it, set_, drop))
    blocking = [p for p in probs if p.key in RESIDUE_GUARDS]
    for p in blocking:
        plan.note(gid, p.key, p.text, fields=missing_fields(env, gid, after_state(it, set_, drop), p.key))
    if blocking:
        for k in list(set_):
            if k in DEFINING:
                set_.pop(k)
        drop = []
    w = Write(gid, kind, dict(set_), list(drop), float(it.get("updated") or 0), "; ".join(notes))
    plan.kinds[gid] = kind
    if blocking:
        plan.outcome[gid] = "left"
    elif w.empty():
        plan.outcome[gid] = "skipped"
    else:
        plan.outcome[gid] = "written"
    if not w.empty():
        plan.writes.append(w)


def _plan_alive(env: Env, plan: Plan, gid: str, it: dict[str, Any], mod: "_model.Model") -> None:
    m = it.get("metadata") or {}
    project = clean(m.get("project"))
    today_state = mod.today or "?"
    set_: dict[str, Any] = {}
    drop: list[str] = []
    notes: list[str] = []
    hits, _broad = _mg.wait_lines(m.get("next"))
    if hits:
        read = env.reads.get(gid)
        if read is None:
            plan.wants_read[gid] = {"why": "an alive item whose next reads as a wait", "lines": [h[0] for h in hits]}
        else:
            rec = _hidden_record(plan, gid, read)
            ans = read.get("answer")
            if ans and ans.get("wait") == "yes" and ans.get("confident"):
                ch = env.choices(gid, it, mod)
                post = ch.get(ans["post_wake_mover"], ans["post_wake_mover"])
                kind = ans["kind"]
                if kind == "relay" and _model.is_owner(post):       # never <owner>: he relays the news, the last agent mover moves on it
                    who, src = env.relay_post(it, project)
                    post = who or post
                    if who:
                        plan.relay_post[gid] = (who, src)
                elif kind == "relay":
                    plan.relay_post[gid] = (post, "the call's read")
                set_.update(wait_kind=kind, post_wake_mover=post)
                if kind == "time":
                    set_.update(wake=ans["wake"], hold=True, hold_set={"at": env.now, "by": AUTHOR}, wait_basis={"text": ans["basis"], "wake": ans["wake"], "by": AUTHOR, "at": env.now})
                elif kind == "anchor":
                    set_.update(wait_anchor=ans["anchor"], wait_event=ans["event"], ask_by=ans["end"])
                elif kind == "item":
                    set_.update(after=ans["after"], ask_by=ans["end"])
                else:
                    set_.update(wait_event=ans["event"], ask_by=ans["end"])
                drop += [k for k in ("mover", "then", "state", *_states.CARRY_FIELDS) if k in m]
                rec["applied"] = True
                notes.append("a wait read from its next")
                _commit(env, plan, gid, it, f"{today_state} → waiting on {_model.KIND_WORDS[kind].format(owner=_model.owner_display())} (read from its next)", set_, drop, notes, env.label(post))
                if plan.outcome.get(gid) == "left":
                    rec["applied"] = False
                    rec["why"] = "the guards would refuse it as read: listed"
                return
            if ans and ans.get("wait") == "yes":
                plan.note(gid, "hidden_wait", f"its next reads as a wait; the call read a {ans['kind']} wait with confidence {ans.get('confidence')} ({ans.get('reason')}): listed, not set")
                rec["why"] = f"confidence {ans.get('confidence')}: listed, not set"
            elif not ans:
                plan.note(gid, "hidden_wait", f"its next reads as a wait and the call could not read it: {read.get('why') or 'no answer'}")
    mover, swapped = _take(env, plan, gid, mod.mover, project, "mover")
    if mover and clean(m.get("mover")) != mover:
        set_["mover"] = mover
    if swapped:
        notes.append(f"mover gone, {env.label(mover)} takes it")
        if _wt.needs_of(m) != [mover]:
            set_["needs"] = [mover]                # as watchers.turn_alive does: the one session in needs is the one that moves it, so every reader of needs sees the same mover
    if _model.is_owner(mover):
        if mod.then and clean(m.get("then")) != clean(mod.then):
            set_["then"] = mod.then
        who = f"{_model.owner_display()} moves it"
    else:
        who = "an agent moves it"
    _commit(env, plan, gid, it, f"{today_state} → alive, {who}" + (" (mover gone)" if swapped else ""), set_, drop, notes, env.label(mover))


def _wait_label(env: Env, it: dict[str, Any], today: str, post: str) -> str:
    """The name a nameless line of a waiting item's next gets: the post-wake mover, unless that is the owner (a relay's ask-by day turns the item to him, but the line is the session's own
    step in the meantime: the one who asks him, `then` of section 3's defaults)."""
    if post and not _model.is_owner(post):
        return env.label(post)
    return env.label(_model._defaults(it.get("metadata") or {}, today)[1])


def _anchor_seen(env: Env, plan: Plan, gid: str, it: dict[str, Any], set_: dict[str, Any]) -> None:
    """A migrated anchor wait counts the notices anchor-hub logged on its anchor since the item's last move (the server stamps its `set_at` from `state_updated`, not from the pass): they are its
    arrivals, which the wait counts. List each such item, so the person who takes the item after the wake is told before the message arrives."""
    m = it.get("metadata") or {}
    if plan.outcome.get(gid) == "left" or clean(set_.get("wait_kind") or m.get("wait_kind")).lower() != "anchor":
        return
    url = clean(set_.get("wait_anchor") or m.get("wait_anchor"))
    project = clean(m.get("project"))
    if not url or not project:
        return
    since = float(it.get("state_updated") or it.get("updated") or 0)
    rows = [n for n in env.notices(project, since) if n.get("kind") == "anchor" and _same_anchor(str(n.get("anchor") or ""), url)]
    if rows:
        plan.note(gid, "anchor_seen", anchor_seen_why(url, len(rows)), hand=False, default=str(len(rows)))


def anchor_seen_why(url: str, n: int) -> str:
    """The line for an anchor wait that already has notices: the anchor and a count, nothing anyone wrote (the server builds the same line from the stored anchor, never from a row it is handed)."""
    return f"anchor-hub logged {n} notice{'s' if n != 1 else ''} on {url} since its last move: the wait counts {'them' if n != 1 else 'it'}; it ends when the anchor-hub check passes"


def _same_anchor(a: str, b: str) -> bool:
    def key(u: str) -> str:
        try:
            return _anc.anchor_id(_anc.split_fragment(u)[0]) or u
        except Exception:  # noqa: BLE001
            return u
    a, b = clean(a), clean(b)
    return bool(a) and bool(b) and (a == b or key(a) == key(b))


def _plan_waiting(env: Env, plan: Plan, gid: str, it: dict[str, Any], mod: "_model.Model") -> None:
    m = it.get("metadata") or {}
    project = clean(m.get("project"))
    w = mod.wait
    assert w is not None
    today_state = mod.today or "?"
    notes: list[str] = []
    drop: list[str] = []
    set_: dict[str, Any] = {}
    # ---- a time wait that carries neither his words nor a real date: his stored quote, else it is no wait
    if w.kind == "time" and clean(m.get("wake")):
        quote = str(_wt.words_of(m).get("quote") or "")
        if not (w.basis or (quote and _mg.has_wait_words(quote))):
            entry = park_quote(it, env.now)
            if entry:
                set_["cap_ok"] = cap_ok_from(it, entry)
                notes.append("his stored words recorded for the wake")
            else:
                drop = [k for k in ("hold", "hold_set", "state", *_states.CARRY_FIELDS) if k in m]
                mod2 = env.derive(gid, after_state(it, {}, drop))
                if mod2.state != _model.ALIVE:
                    plan.note(gid, "snooze", f"a time wait (wake {m.get('wake')}) with none of his words in its answers and no real date; without the hold it still waits ({mod2.wait.kind if mod2.wait else '?'}): set by hand")
                else:
                    mover, swapped = _take(env, plan, gid, mod2.mover, project, "mover")
                    set_["mover"] = mover
                    plan.note(gid, "snooze_alive", f"a time wait (wake {m.get('wake')}) with none of his words in its answers and no real date: the hold goes, the wake stays as a backstop, "
                                                  f"the item is alive with {env.label(mover)}", hand=False)
                    notes.append("a snooze: the hold goes, the wake stays as a backstop")
                    who = f"{_model.owner_display()} moves it" if _model.is_owner(mover) else "an agent moves it"
                    _commit(env, plan, gid, it, f"{today_state} → alive, {who} (snooze: none of his words found)", set_, drop, notes, env.label(mover))
                    return
    fill, extra = _fill_wait(env, plan, gid, it, mod)
    set_.update(fill)
    probe = problems(env, gid, after_state(it, set_, drop))
    lacking = [p for p in probe if p.key in ("wait_input", "no_end")]
    read = env.reads.get(gid)
    if lacking and w.kind in ("anchor", "item", "relay") and read is None:
        plan.wants_read[gid] = {"why": "a wait whose input or end its own fields do not state: " + " ".join(p.text for p in lacking), "lines": []}
    elif lacking and read is not None:
        rec = _hidden_record(plan, gid, read)
        ans = read.get("answer")
        if not ans or ans.get("wait") != "yes":
            rec["why"] = rec["why"] or "the call read no wait in the text"
        elif ans["kind"] != w.kind:
            rec["why"] = f"the call read a {ans['kind']} wait, the item's fields a {w.kind} wait: listed"
        elif not ans.get("confident"):
            rec["why"] = f"confidence {ans.get('confidence')}: listed, not set"
        else:
            new = dict(set_)
            if w.kind == "anchor":
                new.setdefault("wait_anchor", ans["anchor"])
                new.setdefault("wait_event", ans["event"])
            elif w.kind == "relay":
                new.setdefault("wait_event", ans["event"])
            has_end = bool(m.get("ask_by") or new.get("ask_by")) or (w.kind != "relay" and bool(w.backstop))
            if not has_end:
                new["ask_by"] = ans["end"]
            still = [p for p in problems(env, gid, after_state(it, new, drop)) if p.key in ("wait_input", "no_end")]
            if len(still) < len(lacking):
                set_ = new
                rec["applied"] = True
                notes.append("input and end read from its text")
            else:
                rec["why"] = "the read did not complete the wait: listed"
    dflt, dwhy = "", ""
    if w.kind in ("anchor", "item", "relay") and any(p.key == "no_end" for p in problems(env, gid, after_state(it, set_, drop))):
        dflt, dwhy = default_end(env, it, w.kind)
        set_["ask_by"] = dflt
        notes.append(f"a default ask_by {dflt} ({dwhy}) for its mover to replace")
    for x in extra:
        plan.note(gid, "wait_input", x, fields=("wait_anchor",))
    for k in list(set_):
        if k in MODEL_KEYS and clean(m.get(k)) == clean(set_[k]):
            set_.pop(k)
    _commit(env, plan, gid, it, f"{today_state} → waiting on {_model.KIND_WORDS[w.kind].format(owner=_model.owner_display())}", set_, drop, notes, _wait_label(env, it, today_state, set_.get("post_wake_mover") or w.post_wake_mover))
    _anchor_seen(env, plan, gid, it, set_)
    if dflt:
        if plan.outcome.get(gid) == "left":     # the state was not written, so no default is stored: the owner is told what it would have been
            plan.note(gid, "no_end", f"the wait has no end (a default of {dflt}, {dwhy}, would have been stored; the item is left whole until its input is set)", fields=("ask_by",), default=dflt)
        else:
            plan.note(gid, "default_end", f"the wait had no end: ask_by {dflt} is a default ({dwhy}); its mover replaces it with the real day", hand=False, fields=("ask_by",), default=dflt)


def plan_open(gid: str, it: dict[str, Any], env: Env, plan: Plan) -> None:
    """Plan one open item: alive (mover, then) or waiting (kind, input, end, post-wake mover), the snooze, the nameless next lines, and the confident reads of its text."""
    mod = env.derive(gid, it)
    if mod.state == _model.ALIVE:
        _plan_alive(env, plan, gid, it, mod)
    elif mod.state == _model.WAITING and mod.wait is not None:
        _plan_waiting(env, plan, gid, it, mod)


def plan_items(items: dict[str, dict[str, Any]], env: Env) -> Plan:
    """The plan for every open item. One that cannot be planned is listed as an error and the rest go on."""
    plan = Plan()
    for gid in sorted(items, key=_num):
        it = items[gid]
        if it.get("status") != "open":
            continue
        try:
            plan_open(gid, it, env, plan)
        except Exception as e:  # noqa: BLE001
            plan.note(gid, "error", f"not planned: {type(e).__name__}: {e}")
    return plan


# ---------------------------------------------------------------------------------------------------------------- the closed items
def closed_without_outcome(items: dict[str, dict[str, Any]]) -> list[str]:
    return [g for g in sorted(items, key=_num) if items[g].get("status") == "completed" and not clean((items[g].get("metadata") or {}).get("outcome"))]


# The words of a record that say how an item ended: drop words (what the back-fill reads as dropped or superseded) and completion words. The "Done when ..." line every description carries is the
# item's goal, not an outcome, and is left out.
OUTCOME_WORDS = re.compile(r"\b(dropped|declined|abandoned|outdated|not planned|no longer needed|won'?t do|superseded|duplicate|folded into|merged into|replaced by|"
                           r"completed|shipped|resolved|delivered|deployed|released|merged|landed|went live|is live|now live)\b|"
                           r"\b(?:is|was|are|were|now|all|marked|got)\s+(done)\b|(?:^|[\n\"'(])\s*(done)\s*[:\u2014\u2013-]", re.I)
_DONE_LINE = re.compile(r"\bdone when\b[^.\n]*[.\n]?", re.I)


def record_text(it: dict[str, Any]) -> str:
    """What the closed item's own record says about its end: the reason it stored, its last next line, his answers on it, and its description without the done-line."""
    m = it.get("metadata") or {}
    answers = [clean(a.get("text") or a.get("choice")) for a in (m.get("answers") or []) if isinstance(a, dict)]
    return _DONE_LINE.sub(" ", " \n".join([clean(m.get("reason")), clean(m.get("next")), *answers, str(it.get("description") or "")]))


def outcome_words(it: dict[str, Any]) -> list[str]:
    """The distinct outcome words the closed item's record holds, lower-cased, in the order they stand."""
    return list(dict.fromkeys(next(g for g in m if g).lower() for m in OUTCOME_WORDS.findall(record_text(it))))


def plan_closed(gid: str, it: dict[str, Any], read: dict[str, Any] | None, plan: Plan) -> None:
    """A closed item's outcome from the cold call's read: `read` = {status, answer (validated, in the store's words) | None, why}. Written only on a HIGH confidence read of done, dropped or
    superseded. A read of lower confidence, or one that finds nothing, is `unrecorded` only when the record has no outcome words (OUTCOME_WORDS); with them it is listed for a person, never
    guessed. An item the call could not read is listed too."""
    if not read or not read.get("answer"):
        plan.note(gid, "closed_unread", (read or {}).get("why") or "not read")
        return
    a = read["answer"]
    conf = clean(a.get("confidence")).lower()
    if a["outcome"] != "unrecorded" and conf == "high":
        s: dict[str, Any] = {"outcome": a["outcome"], "reason": a["reason"]}
        if a.get("superseded_by"):
            s["superseded_by"] = a["superseded_by"]
        plan.writes.append(Write(gid, f"closed: {a['outcome']}", s, [], float(it.get("updated") or 0), f"outcome back-filled: {a['read'].replace('_', ' ')} ({a['reason']})"))
        return
    words = outcome_words(it)
    if words:
        plan.note(gid, "closed_unsure", f"the call read {a['read'].replace('_', ' ')} with {conf or 'no'} confidence ({a.get('call_said') or a.get('reason') or 'no reason'}) and the record has outcome words "
                                        f"({', '.join(words[:6])}): left for a person to set its outcome")
        return
    plan.writes.append(Write(gid, "closed: unrecorded", {"outcome": "unrecorded", "reason": _cold.UNRECORDED_REASON}, [], float(it.get("updated") or 0),
                             "outcome back-filled: unrecorded (the record says nothing about how it ended)"))


# ---------------------------------------------------------------------------------------------------------------- the wake at the end of the pass
FIELD_HINTS = {
    "wait_event": "wait_event=<who or what is waited for>",
    "wait_anchor": "wait_anchor=<the link it waits on>",
    "after": 'after=["board#N", ...] (the items it waits after)',
    "ask_by": "ask_by=YYYY-MM-DD (the day it comes back to someone when nothing has arrived)",
    "wake": "wake=YYYY-MM-DD",
}


def wake_row(shown_id: str, subject: str, r: Residue) -> str:
    """One line of the residue wake for one item: what to set, with the exact field, and that a stored ask_by is a default to replace."""
    sets = ", ".join(FIELD_HINTS.get(f, f"{f}=<value>") for f in r.fields)
    if r.kind == "default_end":
        return (f"- {shown_id} {subject}: its wait had no end, so the migration stored ask_by={r.default} as a DEFAULT backstop (not a date anyone chose). "
                f"Replace it with the real day: update({shown_id}, ask_by=YYYY-MM-DD).")
    if r.kind == "anchor_seen":
        return (f"- {shown_id} {subject}: {r.why}. Nothing to set: read {'them' if r.default != '1' else 'it'} first; the person who takes the item when the wait ends is told what arrived.")
    tail = f" (a backstop of {r.default} is suggested)" if r.default and "ask_by" in r.fields else ""
    why = f" ({' '.join(r.why.split())[:200]})" if r.fields == ("wait_anchor",) and r.why else ""      # which links, when several are scoped to it
    return f"- {shown_id} {subject}: set {sets}{why}{tail}. Until then it waits on the old machinery, not on a watcher."


def wake_text(owner: str, rows: list[str], items: int = 0) -> str:
    """The message one owner gets when the migration pass ends: its items with what each needs, one line each (`items` = how many items the lines are about; the lines when not given)."""
    n = items or len(rows)
    return (f"[stackshot] The item model migration pass finished. {n} of {owner}'s items {'is' if n == 1 else 'are'} listed with what each needs "
            f"(a field to set by hand with update(item_id, <field>=...), a default to replace, or a notice already on its anchor):\n" + "\n".join(rows))
