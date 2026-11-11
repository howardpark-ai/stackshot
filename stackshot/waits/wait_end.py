"""wait_end.py: an open item whose next line waits in words for something nothing tells the item has happened, and what the server does about it.

A line of `next` that says "wait for item 812 to close", "once PR #7 is released", "when hp-box is back online" or "wait for the reply in <link>" is a wait, but the item stores none of it: no `after`, no event or anchor wait, no step proof. Nothing
then tells the item the wait ended, so it sits as work until somebody notices. The write guards refuse new lines of this shape; this module finds the legacy ones and the ones another session wrote, for the ten-minute filing pass
(audit_checks.wait_end_gaps reads the items with it, audit_run.wait_end_pass acts, server._wait_end_fix writes).

The gaps (each a `Gap`, `kind` in KINDS), read from the mover's own open steps and the steps that name nobody (another session's step and the owner's are never read):

  item      the line defers on an open item (`board#N`) the item's `after` does not name: fix `after`
  pr        the line waits for a pull request's merge or release: fix an event wait (`pr_merged` / `pr_released`) when the line is the item's only open step, a step proof when it is a pure wait step among other work
  box       the line waits for a machine of the fleet to come online: fix a `box_online` event wait
  url       the line waits for something in a link the anchors tool takes: fix an anchor wait (the link is added as an anchor scoped to the item)
  stored    the item stores a wait no watcher can end (watchers.can_end): fix only what is derivable (a backstop day, the one anchor the item has), else ask
  delivery  a step that delivers a pull request (`ship PR #7`) and carries no proof: fix its `step_proof` when delivery is the whole step
  event     the wait is for an event no event type reports (a scheduled job, an upstream release, a CI or deploy finishing, a service coming back): a message to the builder, never a fix

A gap the server cannot fix with certainty is a question to the mover (the `wait-end` finding), never a guess: an "or", several items, a bare `#n` the item is not anchored to, a machine or pull request that is not what the line seems to
say, an item with other work open. An item waits only wholly, so an item-level fix needs the line to be the item's only open step. An item that is held, already waits, or is moved by the owner is never touched; a fix the mover sends back
(clear_after, clear_wait, step_proof=none) is recorded by token (server_fixes.WAIT_END) and the line is left alone.

Pure functions of strings, dicts and the `Facts` a caller hands in: no server import, no clock read except `now` passed in."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Any, Callable, NamedTuple

from stackshot.waits import event_waits as _ew
from stackshot.model import model_guards as _mg
from stackshot.waits import server_fixes as _sf
from stackshot.model import step_proof as _sp
from stackshot.model import steps as _steps
from stackshot.waits import watchers as _watch
from stackshot.waits import waiting as _wt

ITEM, PR, BOX, URL, STORED, DELIVERY, EVENT = "item", "pr", "box", "url", "stored", "delivery", "event"
KINDS = (ITEM, PR, BOX, URL, STORED, DELIVERY, EVENT)
EVENT_MISSING = "event-missing"      # the category of the message to the builder
FIX_CAP = 10                         # fixes one pass makes at most (the rest wait for the next pass)


class Facts(NamedTuple):
    """What the detector reads of the world, handed in by the caller (the server hands in the real ones; a scenario its own). `machines`: lower-case host or fleet name → fleet name; `online`: the fleet names (lower case) whose
    puller checked in lately; `own_repo` and `released`: this repository and the lower-case names of [released.repos]; `item_prs(gid)`: the "owner/repo#n" pull requests the item is anchored to; `item_anchors(gid)`: the URLs
    of the anchors scoped to the item; `anchor_url(url)`: whether the anchors tool takes the link."""
    machines: dict = {}
    online: frozenset = frozenset()
    own_repo: str = ""
    released: frozenset = frozenset()
    item_prs: Callable[[str], Any] = lambda gid: ()
    item_anchors: Callable[[str], Any] = lambda gid: ()
    anchor_url: Callable[[str], bool] = lambda url: False


class Gap(NamedTuple):
    """One line (or one stored wait) with nothing to end it. `plan` = {} for a question only, else what the server sets: {"op": after | event | anchor | proof | backstop | anchor_pick, ...}. `evidence` is the finding's words;
    `token` binds a fix (and a mover's no) to the line."""
    kind: str
    pos: int
    line: str
    entity: str
    evidence: str
    plan: dict
    token: str
    cls: str = ""


def _clip(text: Any, n: int = 80) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def line_hash(text: Any) -> str:
    """8 hex of the whole step (every non-blank line, marker and bold marks off): an edit to a continuation line is a new fact as much as an edit to the first. A token made from the first line alone
    (an earlier shape) simply no longer matches and goes stale: the line is read as new once."""
    body = "\n".join(_steps.key(ln) for ln in str(text or "").splitlines() if ln.strip())
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:8]


def token(kind: str, entity: str, text: Any) -> str:
    """`<kind>:<entity>|<8 hex of the step's text>`: a changed step or a changed entity is a new fact."""
    return f"{kind}:{entity}|{line_hash(text)}"


def kind_of_token(tok: str) -> str:
    return str(tok).split(":", 1)[0]


# ---------------------------------------------------------------------------------------------------------------- which lines are read
def own_steps(meta: dict[str, Any], mover: str, same: Callable[[str, str], bool]) -> list[tuple[int, str]]:
    """[(1-based position in the checklist, the step as written)] of the open steps the mover owns or that name nobody. Another session's step and the owner's are the openers' to word, never read here."""
    out: list[tuple[int, str]] = []
    for i, s in enumerate(_steps.view(meta)):
        if s["status"] != _steps.OPEN:
            continue
        who = _steps.opener(s["text"])
        if who and not same(who, mover):
            continue
        if _steps.is_his(s["text"], unnamed_is_his=False):
            continue
        out.append((i + 1, s["text"]))
    return out


def body_of(text: Any) -> str:
    """The step on one line without its opener: the words the patterns read."""
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    head = _steps.strip_opener(lines[0])
    return " ".join([head, *lines[1:]])


_WAITW = re.compile(r"\b(?:wait(?:s|ing|ed)?|await(?:s|ing|ed)?|until|till|once|when|after|pending|blocked)\b", re.I)
_WAIT_ON = re.compile(r"\b(?:wait(?:s|ing|ed)?\s+(?:for|on)|await(?:s|ing|ed)?|until|till|once|after|when|pending|blocked on)\b", re.I)


def _wait_before(plain: str, start: int, reach: int = 90) -> bool:
    """Does a waiting word stand in the clause before `start` (not negated)?"""
    seg = plain[max(0, start - reach):start]
    seg = re.split(r"[.;!?\n]", seg)[-1]
    for m in _WAIT_ON.finditer(seg):
        if not _mg._negated(seg, m.start()):
            return True
    return False


def _item_refs(text: Any) -> list[tuple[str, list[str]]]:
    """[(line, [board#N ...])] of the lines that wait on an open item in words: the deferrals model_guards reads (once, after, when, until ... board#N) and a waiting word right before the id ("wait for board#N",
    "waiting on board#N", "pending board#N"), not negated. One entry per line, the ids in the order written."""
    out: dict[str, list[str]] = {}
    for line, refs in _mg.deferral_refs(text):
        out.setdefault(line, []).extend(r for r in refs if r not in out.get(line, []))
    for raw in str(text or "").splitlines():
        line = " ".join(raw.split())
        if not line or line.startswith("("):
            continue
        plain = _mg._plain(line)
        for m in _mg._BOARD_REF_RX.finditer(plain):
            ref = f"board#{m.group(1)}"
            if _wait_before(plain, m.start()) and ref not in out.get(line, []):
                out.setdefault(line, []).append(ref)
    return list(out.items())


# ---------------------------------------------------------------------------------------------------------------- pull requests
_REPO_REF = re.compile(r"(?<![\w/.-])([\w.-]+/[\w.-]+)#(\d+)\b")
_PR_URL = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", re.I)
_BARE_PR = re.compile(r"(?:\b(?:PR|pull request)s?\s*#?(\d+)\b)|(?<![\w/#])#(\d+)\b", re.I)
_EV_RELEASED = re.compile(r"\b(?:released?|live|ship(?:s|ped)?|deploy(?:s|ed)?|go(?:es)?\s+live)\b", re.I)
_EV_MERGED = re.compile(r"\b(?:merged?|merges|lands?|landed)\b", re.I)
_PURE_WAIT = re.compile(
    r"wait(?:s|ing)?\s+(?:for|on|until)\s+(?:the\s+)?(?:(?:PR|pull request)\s*)?(?:#\d+|[\w.-]+/[\w.-]+#\d+|https?://github\.com/\S+?/pull/\d+)"
    r"(?:\s+(?:to\s+|is\s+|gets\s+|has\s+)?(?:be\s+|been\s+)?(?:merge|merged|release|released|land|landed|lands|live|ship|shipped|deployed|go live))?\s*\.?", re.I)


def pr_refs(text: str) -> list[tuple[str, int, str]]:
    """The pull requests a line names → [(repo as written ("" for a bare #n), n, position-in-line start)], URL and `owner/repo#n` forms first, then a bare PR #n."""
    out: list[tuple[str, int, int]] = []
    cut = text
    for m in _PR_URL.finditer(text):
        out.append((m.group(1), int(m.group(2)), m.start()))
        cut = cut[:m.start()] + " " * (m.end() - m.start()) + cut[m.end():]
    for m in _REPO_REF.finditer(cut):
        out.append((m.group(1), int(m.group(2)), m.start()))
        cut = cut[:m.start()] + " " * (m.end() - m.start()) + cut[m.end():]
    for m in _BARE_PR.finditer(cut):
        out.append(("", int(m.group(1) or m.group(2)), m.start()))
    return out


def _pr_event(body: str) -> str:
    """The event the line waits for: pr_released / pr_merged, "" when it names none (or both: which one is the mover's to say)."""
    rel, mer = _EV_RELEASED.search(body), _EV_MERGED.search(body)
    if rel and mer:
        return ""
    return _sp.PR_RELEASED if rel else _sp.PR_MERGED if mer else ""


def _resolve_pr(repo: str, n: int, anchored: Any, facts: Facts) -> tuple[str, str]:
    """(the pull request as "owner/repo#n" with the repository lower-cased, why not). A bare #n counts only when the item is anchored to that pull request (the precedent: the step-proof words), else it is the mover's to name."""
    if repo:
        return f"{repo.lower()}#{n}", ""
    hits = sorted(k for k in anchored if k.rpartition("#")[2] == str(n))
    if len(hits) == 1:
        return hits[0].lower(), ""
    return "", f"a bare #{n} is not anchored to the item, so it may be any repository's: name it as owner/repo#{n}"


def _pr_kind_for(kind: str, key: str, facts: Facts) -> str:
    """A foreign repository's pull request is never released by this server's release path unless [released.repos] lists it: wait for its merge (the rule step_proof.proof_gaps uses)."""
    repo = key.rpartition("#")[0].lower()
    if kind == _sp.PR_RELEASED and facts.own_repo and repo != facts.own_repo.lower() and repo not in facts.released:
        return _sp.PR_MERGED
    return kind


# ---------------------------------------------------------------------------------------------------------------- the event classes no event type reports
_CLASSES = (
    ("a scheduled job's run", re.compile(r"\b(?:nightly|cron|scheduled)\b[^.;]{0,30}\b(?:run|job|batch)\b|\bnext\s+(?:nightly|scheduled)\s+(?:run|job)\b|\b(?:the\s+)?[\w.-]+\s+job\s+(?:runs|finishes|completes|has\s+run)\b", re.I)),
    ("an upstream release", re.compile(r"\b(?:upstream|vendor|library)\b[^.;]{0,40}\b(?:release[sd]?|ships?|publishes?|new\s+version)\b|\bnew\s+(?:version|release)\s+of\s+\S+", re.I)),
    ("a CI run or deploy finishing", re.compile(r"\b(?:CI|build|deploy(?:ment)?|pipeline)\s+(?:run\s+)?(?:is\s+|to\s+)?(?:finish\w*|complet\w*|green|done|passes?|succeed\w*)\b", re.I)),
    ("a service coming back healthy", re.compile(r"\b(?:service|server|endpoint|site|api)\s+(?:is\s+|to\s+)?(?:healthy|back\s+up|up\s+again|recovers?|recovered)\b", re.I)),
)


def event_class(body: str) -> str:
    """The class of event a line waits for that no event type reports ("" when none): a scheduled job's run, an upstream release, a CI run or deploy finishing, a service coming back."""
    for name, rx in _CLASSES:
        m = rx.search(body)
        if m and not _mg._negated(body, m.start()):
            return name
    return ""


# ---------------------------------------------------------------------------------------------------------------- boxes
_BOX_UP = re.compile(r"\b(?:online|back\s+up|comes?\s+back|is\s+up|reachable|powered\s+on|boots?|returns?)\b", re.I)
_BOX_NAME = re.compile(r"\b(?:wait(?:s|ing)?\s+(?:for|on)|until|till|once|when|after)\s+([A-Za-z][\w.-]{1,40})\s+(?:is\s+|to\s+|comes?\s+|gets?\s+)*(?:back\s+)?(?:online|up|reachable)\b", re.I)


def _boxes_in(body: str, facts: Facts) -> list[str]:
    seen: list[str] = []
    for name, fleet in facts.machines.items():
        if len(name) >= 3 and re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w.-])", body, re.I) and fleet not in seen:
            seen.append(fleet)
    return seen


# ---------------------------------------------------------------------------------------------------------------- the gaps of one item
def _g(kind: str, pos: int, text: Any, entity: str, evidence: str, plan: dict, cls: str = "") -> Gap:
    return Gap(kind, pos, _clip(_steps.strip_opener(_steps.first_line(text)), 90), entity, evidence, plan, token(kind, entity or "-", text), cls)


def line_gaps(pos: int, text: str, sole: bool, ctx: "Ctx") -> Gap | None:
    """The gap of one step, or None. The first kind that fits wins: an item in prose, a pull request, a machine, a link, a delivery, an event no type reports."""
    facts = ctx.facts
    body = body_of(text)
    plain = _mg._plain(body)
    if not body:
        return None
    # --- an item in prose
    for line, refs in _item_refs(text):
        open_ids = []
        for r in refs:
            g = ctx.open_item(r)
            if g and g != ctx.gid and g not in ctx.after:
                open_ids.append((r, g))
        if not open_ids:
            continue
        shown = ", ".join(r for r, _g_ in open_ids)
        ev = f"next line {pos} ({_clip(body, 70)!r}) waits for {shown} and the item stores no `after`, so nothing tells it when {shown} closes"
        alternative = bool(re.search(r"\bor\b", _mg._plain(line), re.I))
        if len(open_ids) > 1 or alternative:
            return _g(ITEM, pos, text, shown, ev + (": the line has an alternative" if alternative else ": it names several items"), {})
        if not sole:
            return _g(ITEM, pos, text, shown, ev + "; other work is open on the item, so it cannot wait as a whole: split the wait into its own item or step", {})
        return _g(ITEM, pos, text, shown, ev, {"op": "after", "ids": [open_ids[0][1]], "shown": [open_ids[0][0]]})
    # --- a pull request
    refs = pr_refs(body)
    if refs:
        has_proof = _sp.has_proof(text, ctx.proofs, _steps.key)
        gated = bool(list(_sp.gates(body)))
        waiting = [r for r in refs if gated or _wait_before(plain, r[2])]
        ev_kind = _pr_event(body)
        if waiting and not has_proof and (ev_kind or _EV_RELEASED.search(body) or _EV_MERGED.search(body)) and not _sp.delivers(body)[0]:
            repo, n, _p = waiting[0]
            key, why = _resolve_pr(repo, n, ctx.anchored(), facts)
            ref_s = f"{repo}#{n}" if repo else f"PR #{n}"
            ev = f"next line {pos} ({_clip(body, 70)!r}) waits for {ref_s} and the item stores no event wait or step proof, so nothing tells it when that happens"
            if len({(r[0].lower(), r[1]) for r in waiting}) > 1:
                return _g(PR, pos, text, ref_s, ev + ": it names several pull requests", {})
            if not ev_kind:
                return _g(PR, pos, text, ref_s, ev + ": it does not say whether the merge or the release ends the wait", {})
            if why:
                return _g(PR, pos, text, ref_s, ev + f": {why}", {})
            kind = _pr_kind_for(ev_kind, key, facts)
            phrase = f"{kind} {key}"
            if sole:
                return _g(PR, pos, text, key, ev, {"op": "event", "phrase": phrase, "kind": kind, "key": key})
            if _PURE_WAIT.fullmatch(body.strip()):
                return _g(PR, pos, text, key, ev, {"op": "proof", "proof": phrase, "pos": pos})
            return _g(PR, pos, text, key, ev + "; other work is open on the item: give the step its proof, step_proof=[{\"step\": " + str(pos) + ", \"proof\": \"" + phrase + "\"}]", {})
    # --- a machine
    if _BOX_UP.search(body) and _WAITW.search(body):
        boxes = _boxes_in(body, facts)
        known = sorted({f for f in facts.machines.values()}, key=str.lower)
        ev0 = f"next line {pos} ({_clip(body, 70)!r}) waits for a machine to come online and the item stores no event wait, so nothing tells it when that happens"
        if len(boxes) == 1:
            fleet = boxes[0]
            if fleet.lower() in facts.online:
                return _g(BOX, pos, text, fleet, f"next line {pos} ({_clip(body, 70)!r}) waits for {fleet} to come online and {fleet} is online now: the wait has already ended", {})
            if sole:
                return _g(BOX, pos, text, fleet, ev0, {"op": "event", "phrase": f"{_ew.BOX_ONLINE} {fleet}", "kind": _ew.BOX_ONLINE, "key": fleet})
            return _g(BOX, pos, text, fleet, ev0 + "; other work is open on the item, so it cannot wait as a whole", {})
        if len(boxes) > 1:
            return _g(BOX, pos, text, "+".join(boxes), ev0 + ": it names several machines", {})
        m = _BOX_NAME.search(body)
        if m and m.group(1).lower() not in facts.machines and re.search(r"[-\d]", m.group(1)):
            return _g(BOX, pos, text, m.group(1), ev0 + f": {m.group(1)} is not a machine the server knows" + (f" (the machines are {', '.join(known)})" if known else ""), {})
    # --- a link
    for m in re.finditer(r"https?://[^\s<>)\]]+", body):
        url = m.group(0).rstrip(".,;:!?")
        if _PR_URL.match(url) or not _wait_before(plain, m.start()):
            continue
        base = _anc_split(url)
        if not facts.anchor_url(base):
            continue
        ev = f"next line {pos} ({_clip(body, 70)!r}) waits for something in {_clip(base, 60)} and the item stores no anchor wait, so nothing tells it when that happens"
        if sole:
            return _g(URL, pos, text, base, ev, {"op": "anchor", "url": base, "event": _clip(body, 120)})
        return _g(URL, pos, text, base, ev + "; other work is open on the item, so it cannot wait as a whole", {})
    # --- a delivery step with no proof
    kind, ref = _sp.delivers(body)
    if kind and not _sp.has_proof(text, ctx.proofs, _steps.key) and not ctx.other_after(pos):
        gd = _delivery_gap(pos, text, body, kind, ref, ctx)
        if gd is not None:
            return gd
    # --- an event no event type reports
    cls = event_class(body)
    if cls and _mg.wait_lines(text)[0]:
        return Gap(EVENT, pos, _clip(body, 90), "", f"next line {pos} ({_clip(body, 70)!r}) waits on {cls} and no event type tells the server when that happens", {}, token(EVENT, cls, text), cls)
    return None


def _anc_split(url: str) -> str:
    m = re.search(r"#mention=.*$", url)
    return url[:m.start()] if m else url


_DELIVERY_WHOLE = re.compile(r"(?:ship|deploy|land)\s+(?:(?:PR|pull request)\s*)?(?:#\d+|https?://github\.com/\S+?/pull/\d+)\s*\.?", re.I)


def _delivery_gap(pos: int, text: str, body: str, kind: str, ref: str, ctx: "Ctx") -> Gap | None:
    facts = ctx.facts
    m = re.match(r"https?://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", ref)
    if m:
        key = f"{m.group(1).lower()}#{int(m.group(2))}"
        why = ""
    else:
        key, why = _resolve_pr("", int(ref.lstrip("#")), ctx.anchored(), facts)
        if why and facts.own_repo:
            key, why = f"{facts.own_repo.lower()}#{int(ref.lstrip('#'))}", ""      # a bare #n of a step is this repository's, as the explicit step_proof form reads it
    ev = f"step {pos} ({_clip(body, 70)!r}) delivers {ref} and carries no proof, so nothing ticks it when that happens"
    if why or not key:
        return _g(DELIVERY, pos, text, ref, ev + f": {why or 'name the pull request as owner/repo#n'}", {})
    kind = _pr_kind_for(kind, key, facts)
    proof = f"{kind} {key}"
    whole = bool(_DELIVERY_WHOLE.fullmatch(body.strip())) or bool(re.fullmatch(r"(?:release|merge)\s+(?:(?:PR|pull request)\s*)?(?:#\d+|\S+)\s*\.?", body.strip(), re.I))
    if whole:
        return _g(DELIVERY, pos, text, key, ev, {"op": "proof", "proof": proof, "pos": pos})
    return _g(DELIVERY, pos, text, key, ev + f": the step carries more than the delivery; split `{_sp.VERB.get(kind, 'merge')} {ref}` into a step of its own or give it step_proof=[{{\"step\": {pos}, \"proof\": \"{proof}\"}}]", {})


class Ctx(NamedTuple):
    """What one item's lines are read against."""
    gid: str
    facts: Facts
    open_item: Callable[[str], str]
    after: frozenset
    proofs: dict
    anchored: Callable[[], frozenset]      # the "owner/repo#n" pull requests the item is anchored to, read on first use (most lines never ask)
    other_after: Callable[[int], bool]


def stored_gap(meta: dict[str, Any], facts: Facts, gid: str, now: float) -> Gap | None:
    """The gap of a stored wait that no watcher can end (watchers.can_end False), with the derivable fix: a backstop day for an event or item wait, the one scoped anchor for an anchor wait; else a question."""
    kind = _watch.stored_kind(meta)
    if not kind or _watch.can_end(meta):
        return None
    phrase = str(meta.get("wait_event") or "").strip()
    if kind == "event":
        if _ew.problem(phrase):
            return Gap(STORED, 0, _clip(phrase, 90), kind, f"the item waits on an event ({_clip(phrase, 70)!r}) the server cannot read: {_clip(_ew.problem(phrase), 120)}", {}, token(STORED, "event", phrase))
        return Gap(STORED, 0, _clip(phrase, 90), kind, f"the item waits on {_ew.words(phrase)} and has no backstop day, so it comes back only if the event does", {"op": "backstop"}, token(STORED, "event-backstop", phrase))
    if kind == "item":
        return Gap(STORED, 0, "after", kind, "the item waits on other items but names none in `after` and has no backstop day, so nothing ends the wait", {}, token(STORED, "item", "after"))
    if kind == "anchor":
        urls = list(facts.item_anchors(gid) or ())
        if len(urls) == 1:
            return Gap(STORED, 0, "anchor", kind, f"the item waits on an anchor and names none in wait_anchor; it has one anchor scoped to it ({_clip(urls[0], 60)})", {"op": "anchor_pick", "url": urls[0]}, token(STORED, "anchor", urls[0]))
        return Gap(STORED, 0, "anchor", kind, "the item waits on an anchor and names none in wait_anchor" + ("" if not urls else f" (it has {len(urls)} anchors scoped to it: say which)"), {}, token(STORED, "anchor", "none"))
    if kind == "relay":
        return Gap(STORED, 0, "relay", kind, "the item waits on news only the owner relays and has no ask_by day, so nobody is asked", {}, token(STORED, "relay", "ask_by"))
    return Gap(STORED, 0, "time", kind, "the item waits on a time and has no wake, so nothing ends the wait", {}, token(STORED, "time", "wake"))


def event_gap_stored(meta: dict[str, Any]) -> Gap | None:
    """A stored event wait that no event type reports (event_waits.live False, today a job_run): it turns only on its backstop day."""
    if _watch.stored_kind(meta) != "event":
        return None
    phrase = str(meta.get("wait_event") or "").strip()
    if _ew.problem(phrase):
        return None
    try:
        spec = _ew.parse(phrase)
    except _ew.EventWaitError:
        return None
    if _ew.live(spec):
        return None
    cls = {_ew.JOB_RUN: "a scheduled job's run"}.get(spec.kind, spec.kind)
    day = _wt.stored_until(meta) or meta.get("ask_by") or meta.get("wake") or ""
    return Gap(EVENT, 0, _clip(phrase, 90), spec.kind, f"the item waits on {cls} ({_clip(phrase, 60)!r}) and no event type tells the server when it ends; it can only come back on its backstop {day}".rstrip(), {}, token(EVENT, spec.kind, phrase), cls)


def handled_hashes(meta: dict[str, Any]) -> frozenset:
    """The step hashes (line_hash) of the WAIT_END tokens the server fixed or the mover sent back, the stored-wait and event kinds left out: the one key by which a step counts as handled, in the gaps
    (item_gaps) and in the lines the generic wait finding leaves alone (audit_checks.handled_lines). The entity half of a token depends on what the facts say at the time (a bare #n resolves only while
    the item is anchored to the pull request, a machine only while the fleet view is readable), so the step's own text is what is matched."""
    toks = [*_sf.mark_tokens(meta, _sf.WAIT_END), *_sf.declined_tokens(meta, _sf.WAIT_END)]
    return frozenset(t.rpartition("|")[2] for t in toks if kind_of_token(t) not in (STORED, EVENT))


def item_gaps(gid: str, meta: dict[str, Any], mover: str, state: str, facts: Facts, open_item: Callable[[str], str], same: Callable[[str, str], bool], now: float,
              pending: Callable[[str], bool] = lambda tok: False) -> list[Gap]:
    """The gaps of one open item, in line order (a stored wait's first). `state`: "alive" (its lines are read) or "waiting" (its stored wait is read). `pending(token)` is true for a token the mover sent back or the server fixed: that gap is left out."""
    gaps: list[Gap] = []
    if state == "waiting":
        for g in (stored_gap(meta, facts, gid, now), event_gap_stored(meta)):
            if g is not None and not pending(g.token):
                gaps.append(g)
        return gaps
    if state != "alive" or _watch.stored_kind(meta) or meta.get("hold") or _mg_after(meta):
        return gaps
    mine = own_steps(meta, mover, same)
    all_open = [s for s in _steps.view(meta) if s["status"] == _steps.OPEN]
    sole = len(all_open) == 1 and len(mine) == 1
    after = frozenset(str(x) for x in (meta.get("after") if isinstance(meta.get("after"), list) else []))
    proofs = meta.get("step_proof") if isinstance(meta.get("step_proof"), dict) else {}
    memo: list[frozenset] = []

    def anchored() -> frozenset:
        if not memo:
            memo.append(frozenset(str(k).lower() for k in (facts.item_prs(gid) or ())))
        return memo[0]
    view = _steps.view(meta)

    def other_after(pos: int) -> bool:
        return any(i + 1 > pos and s["status"] == _steps.OPEN and _steps.opener(s["text"]) and not same(_steps.opener(s["text"]), mover) and not _steps.is_his(s["text"], unnamed_is_his=False)
                   for i, s in enumerate(view))
    ctx = Ctx(gid, facts, open_item, after, proofs, anchored, other_after)
    done = handled_hashes(meta)
    for pos, text in mine:
        if done and line_hash(text) in done:
            continue            # a step the server fixed or the mover sent back: read again with other facts it would be another entity, not another step
        try:
            g = line_gaps(pos, text, sole, ctx)
        except Exception:  # noqa: BLE001  (a line the patterns cannot read is no gap)
            g = None
        if g is not None and not pending(g.token):
            gaps.append(g)
    return gaps


def _mg_after(meta: dict[str, Any]) -> bool:
    a = meta.get("after")
    return bool(a) if isinstance(a, list) else bool(str(a or "").strip())


# ---------------------------------------------------------------------------------------------------------------- the words of a fix
def backstop_day(now: float, days: float, zone: Any) -> str:
    """The day (YYYY-MM-DD in the instance zone) an item comes back anyway when nothing else ended its wait: `days` after now."""
    return dt.datetime.fromtimestamp(now + days * 86400.0, zone).strftime("%Y-%m-%d")


def history(plan: dict[str, Any], gap_line: str, pos: int, back: str, mover: str) -> str:
    """The History line of a fix (stall.note keeps 240 characters): what the line was, what was set, where the item goes, and the way back."""
    quote = f"next line {pos} ({_clip(gap_line, 40)!r})" if pos else "the stored wait"
    op = plan.get("op")
    if op == "after":
        return f"wait set: {quote} waited for an open item; after={plan.get('shown')}, back to {mover} when it closes or on {back}. clear_after=true sends it back and the server leaves that line alone"
    if op == "event":
        return f"wait set: {quote} waited for an event; wait_event={plan.get('phrase')}, back to {mover} when it happens or on {back}. clear_wait=true sends it back and the server leaves that line alone"
    if op == "anchor":
        return f"wait set: {quote} waited on a link; anchor wait on {_clip(plan.get('url'), 50)}, back to {mover} when it changes or on {back}. clear_wait=true sends it back and the server leaves that line alone"
    if op == "proof":
        return f"step {plan.get('pos')} now ticks when {plan.get('proof')} happens ({quote}). step_proof=none sends it back and the server leaves that step alone"
    if op == "backstop":
        return f"backstop set: the wait had no day to come back on; ask_by={back}. clear_wait=true sends it back and the server leaves that wait alone"
    return f"wait completed: the anchor wait named none; wait_anchor={_clip(plan.get('url'), 50)} (the item's one scoped anchor). clear_wait=true sends it back and the server leaves that wait alone"


def mover_message(rows: list[str]) -> str:
    """The one `fyi` message to a mover after the pass set waits on its items."""
    n = len(rows)
    return (f"The server set a wait on {n} item{'s' if n > 1 else ''} of yours whose next waited in words with nothing to tell the item when it ends: " + "; ".join(rows)
            + ". History has a line each. If a wait is wrong, clear_after=true, clear_wait=true or step_proof=none sends it back and the server leaves that line alone.")


def event_fix(gap: Gap, mover: str) -> str:
    """The fix text of the message to the builder for a wait on an event nothing reports."""
    return f"add an event type for {gap.cls} to event_waits.py, or tell {mover or 'its mover'} to wait on a time or a relay"
