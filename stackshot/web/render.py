"""render.py — the stackshot board's text renderer (markdown · brief) and the helpers the server, the tools and the search index read. render(data_dir, mode) returns the text;
render_all() returns both from one load. Shape: pure text helpers at module level, and a Board that loads the store, the fleet state and the hub status ONCE and carries the model
(sessions, projects, anchors) and the two emitters. The board's web pages are drawn by ui/render.py."""
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]
import contextlib
import functools
import io
import json, os, sys, glob, datetime, re, subprocess, hashlib, html as H
from pathlib import Path
from urllib.parse import quote
from stackshot import paths as _paths
from stackshot.core import config as _cfg  # stackshot.toml: paths, fleet, scopes, the Machines panel, branding
from stackshot.core import legacy_owner as _lo   # an old version of an item (from the store's history) read as the current code reads it: History only, never written back
from stackshot.fleet import fleet as _fleet   # the session and machine view, and the one rule for a session's presence (running / present)
from stackshot.router import routing as _routing   # the routing log: what came in per project and how it was ruled (the pilot)
from stackshot.model import option_labels as _ol   # the letter an option's label repeats from its badge, dropped on read (option_labels.py)
from stackshot.github import ghsync as _gh   # how an id is written for a person (board-tmp-<machine>#3) and its page address (/items/<n>)
from stackshot.model import work as _work   # an item's work lines, what is in motion on it (a row's "engineer: migrating", the item page's list, the History)
from stackshot.model import said as _said   # the trailers: his words on an item, a tag on the History line of the write that recorded them, the quote behind it
from stackshot.model import states as _states   # an open item's stored state, or the one derived from its fields (states.py)
from stackshot.waits import waiting as _wt   # what an item waits on and whose move it is (waiting.py)
from stackshot.anchors import anchor_scope as _ascope   # which anchors count for an item, from every project's page (anchor_scope.py)
from stackshot.web import itempage as _ip  # the item page's words on the item model: since, next lines
from stackshot.model import steps as _steps   # the checklist behind next: done, dropped and open steps (steps.py)
from stackshot.waits import dated_wait as _dw   # a stored doing item whose open steps are all dated for a later day reads as waiting (dated_wait.py)
from stackshot.model import model as _model   # the item model: dead, alive or waiting, the mover and the wait (model.py)
from stackshot.model import queued as _queued   # a mover busy on another item: its other items on an agent read waiting, queued behind it (queued.py)
from stackshot.web import home as _home   # the home page's three lists on that model: Your move, On agent, Waiting (home.py); board.md and the brief count from them
from stackshot.audit import hourly_log as _hlog   # the hourly audit lines written on an item (History lines)
from stackshot.waits import stall as _stall   # the steps of the stall pass written on an item (History lines)
from stackshot.waits import handover as _hov   # a finished step handed the item on: the record behind a History line (handover.py)
from stackshot.waits import quiet as _quiet   # what a front agent was or was not told of an item, one History line each
from stackshot.web import whatschanged as _wc  # what changed in the tools in the last 7 days: a line in the brief
from stackshot.model import item_project as _iproj   # an item's project by its permanent id: the page key read through the id (item_project.py)
from stackshot.projects import projects as _prj   # the project record: an agent registered there whose page line is still owed (with_pending)
from stackshot.model import model as _model   # the item model: dead, alive or waiting, the mover and the wait (model.py)
from stackshot.fleet import sessions_registry as _sr   # the permanent session id: a stored id is shown as the session's name now, and two forms of one session read as one
_OWNER = str(_cfg.get("instance", "owner") or "the owner")   # whom a Next line addresses with "<owner>:"


def fleet_names():
    """letter → fleet name: session-names.tsv first (a box with no fleet state yet), then the fleet state's own `fleet` name (fleet.names)."""
    from stackshot.fleet import fleet as _fl
    return _fl.names()


def render(data_dir: str, mode: str = "full") -> str:
    """The board as text: mode = full (markdown) · brief."""
    return Board(data_dir).render({mode})[mode]


def render_all(data_dir: str) -> dict:
    """brief and full from ONE load of the store."""
    return Board(data_dir).render({"brief", "full"})


def receiver_type(st, k):
    """How an anchor-hub receiver hears about changes: push (the vendor calls in) or poll (anchor-hub asks). Shared by the
    board and the server's live receivers.json."""
    pu = st.get("push") or {}
    if k == "slack": return "push" if (st.get("slack") or {}).get("connected") else "down"
    if k == "google":
        ms = [str(v.get("mode", "")) for src in ("drive", "gmail") for v in (pu.get(src) or {}).values() if isinstance(v, dict)]
        return "push" if ms and all(m == "push" for m in ms) else ("push + poll" if any(m == "push" for m in ms) else "poll")
    m = str((pu.get(k) or {}).get("mode") or "")
    return m.split(" (")[0] if m else "poll"


# ---------------- text helpers (pure: no board state) ----------------
def load_dir(d):
    out = {}
    for p in sorted(glob.glob(os.path.join(d, "*.json"))):
        if os.path.basename(p).startswith("."): continue
        try: t = json.load(open(p, encoding="utf-8"))
        except Exception: continue
        if not isinstance(t, dict) or "id" not in t: continue      # not a task file
        t["_path"] = p; out[str(t.get("id"))] = t
    return out

def split_outside(text, pattern):
    """Split on `pattern` matches that sit outside ( ) [ ] { } 「 」 — sessions write run-on prose; see next_steps/sentences."""
    text = str(text); out, cur, depth, i = [], "", 0, 0
    opens, closes = "([「{", ")]」}"; tick = False
    while i < len(text):
        c = text[i]
        if c == "`" and (tick or _CODE.match(text, i)): tick = not tick   # a `backticked` span (a command) is never split; a stray backtick opens none
        elif tick: pass
        elif c in opens: depth += 1
        elif c in closes and depth: depth -= 1
        if depth == 0 and not tick:
            m = re.match(pattern, text[i:])
            if m: out.append(cur); cur = ""; i += m.end(); continue
        cur += c; i += 1
    out.append(cur)
    return [x.strip(" ;") for x in out if x.strip(" ;")]
def next_steps(text):
    """→ [(level, text)]: each line is a step (further split on "; " / " → " / " -> " outside brackets);
a line starting with "- " / "• " is a sub-step of the previous step."""
    out = []
    for line in str(text).split("\n"):
        if not line.strip(): continue
        if re.match(r"^\s*[-•]\s+", line): out.append((1, re.sub(r"^\s*[-•]\s+", "", line).strip()))
        else: out += [(0, x) for x in split_outside(line, r";\s+|\s+(?:→|->)\s+")]
    return out
def sentences(text):
    """→ [(level, text)]: newlines split paragraphs; a paragraph starting with "- " / "• " is a sub-bullet
(level 1, kept whole) under the previous bullet; other paragraphs split into one sentence per bullet."""
    parts = []
    for para in split_outside(text, r"\n+"):
        if re.match(r"^\s*[-•]\s+", para): parts.append((1, re.sub(r"^\s*[-•]\s+", "", para).strip()))
        else: parts += [(0, x) for x in _sent(para)]
    return parts
def nested_html(items, link=None):
    link = link or linkify          # an item page passes the Board's linker, which adds item and session mentions (Board.linkify)
    out, open_sub = [], False
    for lvl, x in items:
        if lvl == 0:
            if open_sub: out.append("</ul></li>"); open_sub = False
            elif out: out.append("</li>")
            out.append(f"<li>{link(x)}")
        else:
            if not out: out.append("<li>")
            if not open_sub: out.append("<ul>"); open_sub = True
            out.append(f"<li>{link(x)}</li>")
    if out: out.append("</ul></li>" if open_sub else "</li>")
    return "".join(out)
def _sent(para):
    out, cur, depth = [], "", 0
    i = 0
    while i < len(para):
        c = para[i]; cur += c
        if c in "([「{": depth += 1
        elif c in ")]」}" and depth: depth -= 1
        if depth == 0 and c in ".!?。":
            m = re.match(r"\s+(?=[A-Z0-9\"'(\[]|[^\x00-\x7f\W])", para[i+1:])
            if m: out.append(cur); cur = ""; i += 1 + m.end(); continue
        i += 1
    out.append(cur)
    return [x.strip() for x in out if x.strip()]
def num(r):
    try: return int(r["id"])
    except Exception: return 0
def due_of(r):
    try: return datetime.date.fromisoformat(str(r["metadata"].get("due","")).strip()[:10])
    except Exception: return None
def sort_key(r):  # due date first (dated before undated), then machine, then id — not priority
    d = due_of(r); return (0 if d else 1, d or datetime.date.max, r["L"], num(r))
def needs_of(r):
    """An item's needs as the list it is since an earlier change (decision, external and session names); a stored word (the form before) reads
    as a one-entry list. The one place here that knows the field's two shapes."""
    v = (r.get("metadata") or {}).get("needs")
    if isinstance(v, list): return [str(x).strip() for x in v if str(x).strip()]
    v = str(v or "").strip()
    return [v] if v else []
NEEDS_KINDS = ("decision", "external")
def needs_sessions(r): return [x for x in needs_of(r) if x.lower() not in NEEDS_KINDS]
def needs_kind(r):
    """The lane: "call" when needs holds decision, else "relay" when it holds external (or, in the old one-word form, any other
    word), else "" (on agent: the owner's move, or a session's named in needs). the first of decision, external, a session."""
    ns = [x.lower() for x in needs_of(r)]
    if not ns: return ""
    if "decision" in ns: return "call"
    if "external" in ns or isinstance((r.get("metadata") or {}).get("needs"), str): return "relay"
    return ""
def shown_ref(x):
    """A stored session reference (a permanent id, an old name, a transcript id) as the page names it: the registry's current name, else as stored."""
    x = str(x or ""); return (_sr.display_name(x) or x) if x else x
def same_ref(a, b):
    """Do two stored session references name one session? Compared as permanent ids when both resolve, else as stored."""
    a, b = str(a or ""), str(b or ""); t = _sr.same(a, b)
    return t if t is not None else a == b
def after_of(r):
    """The items an item waits on (metadata.after): ids, in the stored order."""
    v = (r.get("metadata") or {}).get("after")
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
def state_words(r):
    """"state: doing" for an open item that stores a state; "" for a closed one and for one that stores none (states.py)."""
    return _states.words(r, after_open)
def observers_of(r):
    v = (r.get("metadata") or {}).get("observers")
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
def answers_of(r):
    """The owner's answers on an item (metadata.answers): [{ts, kind: decision | comment | step-reply (his note on a step), choice?, text?, via, …}],
    in the stored order; a comment the owner wrote on the item's GitHub issue has via "github" with its url and comment_id."""
    v = (r.get("metadata") or {}).get("answers")
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
def after_open(r):
    """The items in `after` still open, as the Board sets them on each row (`_after`); [] for a version without it."""
    return list(r.get("_after") or [])
def is_parked(r):
    """Out of the queue: on hold, or waiting on an open item (after). Drawn under on agent, after the active ones."""
    return is_held(r) or bool(after_open(r))
def is_verifying(r):
    """In the verifying state (stored: states.py never derives it). The item model reads it as a wait on its end date."""
    return _states.of(r, after_open)[0] == "verifying"
def waits_on_end(r):
    """A verifying item whose wait is its end date (no wake of its own): held until then, like a parked item."""
    m = r.get("metadata") or {}
    return is_verifying(r) and not _wt.wake_value(m) and bool(m.get("end"))
def anchor(r): return f"task-{r['L']}-{r['id']}"
def is_held(r):
    """On hold: parked, out of the queue; drawn as a kind of on agent, never your call or on others. A
    property of an open item (its lane stays 'on agent' and a secondary property renders it as 'on hold'):
    status open with a truthy metadata.hold; optional metadata.wake
    YYYY-MM-DD or YYYY-MM-DDTHH:MM in the instance timezone, at which the server itself releases the item (drops hold and wake) and it returns to
    the lane its needs give it, so the board only shows it; needs and due stay on the item meanwhile. A row with the retired
    status "on_hold" (a stale file, an old version in the store's git) reads as held. The one place here that knows the field.
    An item whose needs hold decision is never shown on hold, whatever
    its stored flag says; it is in the owner's queue (the server's _is_held, the same rule; its update drops such a flag). A
    wake an item still carries with no hold and no until (a hand-off's backstop, or one stored before until) is no wait and leaves it in its lane."""
    st = str(r.get("status") or "")
    m = r.get("metadata") or {}
    date_wait = bool(_wt.stored_until(m)) and _wt.kind_of(m) == "time"        # a wait on a date alone (an until with no kind, or the kind time): parked like the hold with a wake it replaces
    return (st == "on_hold" or (st == "open" and (bool(m.get("hold")) or date_wait))) and needs_kind(r) != "call"
def _when_of(v):
    v = str(v or "").strip().replace(" ", "T")
    try:
        if "T" in v: return datetime.datetime.fromisoformat(v[:16]).replace(tzinfo=_cfg.tz())
        return datetime.date.fromisoformat(v[:10])
    except Exception: return None
def wake_of(r):
    """An item's wake (on hold: when it is released; not on hold: a hand-off's backstop): a date ("YYYY-MM-DD", start of that day), a datetime in the instance timezone ("YYYY-MM-DDTHH:MM", the owner
    "until friday evening"), or None. Board.when() draws either: "Fri Mar 6th" or "Fri Mar 6th 12:00"."""
    md = r.get("metadata") or {}
    return _when_of(str(md.get("until") or "").strip() or str(md.get("wake", "")).strip())      # a stored `until` first, else the wake
def wait_date_of(r):
    """The date an item's wait ends on as History compares it between two versions: its wake as above, else the date the old fields give for its kind (a relay's ask_by), so that rewriting a stored wait as
    `until` (the data migration) reads as no change of date."""
    md = r.get("metadata") or {}
    if not _wt.stored_until(md) and str(md.get("ask_by") or "").strip():
        return _when_of(_wt.until_of(md)) or wake_of(r)        # old fields with both dates: the one date they give for the kind, as the rewrite stores it
    return wake_of(r) or _when_of(_wt.until_of(md))
def wake_key(r):
    """A wake as a datetime in the instance timezone for sorting (a date is its midnight; no wake sorts last)."""
    w = wake_of(r)
    if w is None: return datetime.datetime.max.replace(tzinfo=_cfg.tz())
    return w if isinstance(w, datetime.datetime) else datetime.datetime.combine(w, datetime.time(), _cfg.tz())
HOLD_WHY = {"after": "an open after item", "recycle": "a pane recycle", "external": "an outside party (needs external)", "anchor": "an anchor scoped to it"}
clean_anchor_entries = _ascope.clean_entries      # one page's anchors from the anchors file's list as clean dicts (anchor_scope.py): the one reader of a page's list, Board.anchor_entries
def hold_whys(r, item_anchors, after_words=""):
    """What holds a held item, as the words HOLD_WHY and `after_words` give ([] = nothing holds it now): an open after item, a pane recycle, needs external, an anchor scoped to it
    (`item_anchors`: the anchors that count for the item, from every project's page: anchor_scope.anchor_scope, or Board.scoped_urls(gid)). The one definition: Board.new_hold_words
    (the briefings' "nothing holds it now") and tools/board_report.py (the audit's arbitrary-hold check) read it."""
    why = []
    if after_open(r): why.append(after_words or "after " + ", ".join(after_open(r)))
    if waits_recycle(r): why.append(HOLD_WHY["recycle"])
    if "external" in [x.lower() for x in needs_of(r)]: why.append(HOLD_WHY["external"])
    if item_anchors: why.append(HOLD_WHY["anchor"])
    return why
HOLD_AT_MAX = 4102444800                          # 2100-01-01: a hold's time beyond it is a malformed value, not a moment
def hold_set_of(r):
    """Who set a hold and when (metadata.hold_set {at: epoch, by: a session's name}, written by the server when a hold is set); {} for a hold stored before the record."""
    v = (r.get("metadata") or {}).get("hold_set")
    return v if isinstance(v, dict) else {}
def hold_at(r):
    """When a hold was set, epoch seconds; 0.0 when there is no record or its value is malformed (never an error)."""
    try:
        v = float(hold_set_of(r).get("at") or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return v if 0 < v < HOLD_AT_MAX else 0.0       # a milliseconds epoch, 1e300, nan or inf is no record: fromtimestamp would raise on it
def hold_by(r):
    """Who set a hold, as one clean line for board.md, the brief and get: whitespace and newlines collapsed, at most 80 characters;
    "" when there is no record."""
    v = hold_set_of(r).get("by")
    return " ".join(str(v).split())[:80] if isinstance(v, str) else ""
def new_holds(rows, now, hours=24):
    """The items on hold whose hold was set in the last `hours` hours (`now` a datetime), newest first, for the briefings: the
    board.md head, the session-start brief and the `brief` tool's head. A hold with no record (set before it) never counts as new."""
    cut = now.timestamp() - hours * 3600
    out = [r for r in rows if r.get("status") == "open" and is_held(r) and hold_at(r) >= cut > 0]
    return sorted(out, key=lambda r: -hold_at(r))
def provision_lag(now) -> list[tuple[str, bool]]:
    """The boxes whose stackshot puller reports a VERSION behind this checkout's, as (hostname, online), sorted (the owner,
    shown at once, the way the recycle line is; the fleet tool's watchdog provisions them within a tick, so the line
    clears on its own unless a box is off). [] when the server's client state cannot be read (a fixture, another box)."""
    try:
        from stackshot.fleet import clients as _cl
        st = _cl.load(); ts = now.timestamp()
        on = {str(m.get("fleet") or k): _cl.online(m, ts) for k, m in st["machines"].items()}
        return [(h, on.get(h, False)) for h, _, _ in _cl.puller_lag(st)]
    except Exception:
        return []


def waits_recycle(r):
    """The item waits for the panes to be recycled: a truthy metadata.recycle, which the
    server's update tool sets. Set = true, 1, or the strings "true" / "yes" / "1" (any case); anything else (false, 0, "",
    "no", absent) is not. The one place here that knows the field."""
    v = (r.get("metadata") or {}).get("recycle")
    if isinstance(v, bool): return v
    if isinstance(v, (int, float)): return v == 1
    return isinstance(v, str) and v.strip().lower() in ("true", "yes", "1")
def held_only_for_recycle(r, open_after):
    """On hold, and the pane recycle is all the hold waits for: an open item with metadata.hold, no wake and no open
    after (`open_after`: the ids in its `after` still open, as the caller knows them; the server reads the files, the Board its
    rows). An anchor-scoped hold always carries a backstop wake (the rule in the server's update), so the wake test covers
    it. The one definition: the server's _recycled releases such a hold with the recycle, and recycle_due() counts the item."""
    m = r.get("metadata") or {}
    return r.get("status") == "open" and bool(m.get("hold")) and not _wt.wake_value(m) and not open_after
def recycle_due(r, open_after):
    """The item is one a pane recycle would serve now, as far as the item itself says: open, flagged
    (waits_recycle), and either not on hold or on hold for the recycle alone (held_only_for_recycle). Both the server's
    recycle-wanted (the fleet tool's watchdog, which adds its per-machine filters) and the board's "Pane recycle pending" line use it,
    so the two never disagree about which items wait."""
    if r.get("status") != "open" or not waits_recycle(r): return False
    if _wt.stored_until(r.get("metadata") or {}) and _wt.kind_of(r.get("metadata") or {}) in ("time", "item"): return False      # parked on a date or on an open item (the one until, no hold beside it): held for something else too
    return not is_held(r) or held_only_for_recycle(r, open_after)
WHOSE ={"call": "your call", "relay": "on others", "": "on agent"}   # whose move, in words: needs_kind → the board's names
# The ask line: what a needs=decision item asks of him, in one line of four
# labelled parts in this order, separated by " · " (space, U+00B7, space). The shape lives here, importable; the server validates
# through parse_ask. The By part is free text by design: the rulebook's date form ("Thu Mar 12th") or "no date".
ASK_MAX = 240
ASK_RE = re.compile(r"Decide: (?P<decide>\S.*?) · Recommend: (?P<recommend>\S.*?) · Stakes: (?P<stakes>\S.*?) · By: (?P<by>\S.*)")
ASK_FORM = "Decide: … · Recommend: … · Stakes: … · By: …"
def parse_ask(text):
    """An ask line → {"decide", "recommend", "stakes", "by"}; None when it is misshaped (a part missing or out of order, a
    separator other than " · "), longer than ASK_MAX characters, or holds a line break. Surrounding spaces are not counted."""
    t = str(text or "")
    if any(c in t for c in "\r\n\v\f\x85\u2028\u2029"): return None   # one line: a break anywhere, even a trailing one, is refused
    t = t.strip()
    if not t or len(t) > ASK_MAX: return None
    m = ASK_RE.fullmatch(t)
    return {k: v.strip() for k, v in m.groupdict().items()} if m else None
# The options (the board shows them in a well-readable form for every item with choices):
# metadata.options on an item that asks him to
# pick, a list of OPTIONS_MIN to OPTIONS_MAX entries {label, line, recommended}, exactly one recommended. The server validates
# (service/wait_gates.py `_gate_options`); the renderer draws what options_of returns, so a hand-edited list that broke the shape draws nothing.
OPTIONS_MIN, OPTIONS_MAX, OPTION_LABEL_MAX, OPTION_LINE_MAX = 2, 6, 40, 160
def options_of(r, raw=False):
    """An item's options → [{"label", "line", "recommended"}], [] when it has none or they are misshaped. The labels are as the card shows them: with three or more options whose labels all open
    with their own place's letter, that letter is dropped (option_labels.strip_letters; the badge draws it). `raw=True` gives the labels as stored. Nothing is written."""
    v = (r.get("metadata") or {}).get("options")
    if not isinstance(v, list) or not OPTIONS_MIN <= len(v) <= OPTIONS_MAX: return []
    out = []
    for o in v:
        if not isinstance(o, dict) or not str(o.get("label") or "").strip() or not str(o.get("line") or "").strip(): return []
        out.append({"label": str(o["label"]).strip(), "line": str(o["line"]).strip(), "recommended": o.get("recommended") is True})
    if sum(o["recommended"] for o in out) != 1: return []
    if not raw:
        for o, label in zip(out, _ol.strip_letters([o["label"] for o in out])): o["label"] = label
    return out
def answers_of(r):
    """The owner's answers from the board as stored (metadata.answers), oldest first; [] when none or misshaped."""
    v = (r.get("metadata") or {}).get("answers")
    return [a for a in v if isinstance(a, dict)] if isinstance(v, list) else []
def open_options(r):
    """The options while they are an open choice: an open item that still needs his decision (an
    item whose decision had left its needs still drew its options and read as waiting on him). [] otherwise; the item page
    keeps them in its History, on the line where the decision left the needs."""
    return options_of(r) if r.get("status") != "completed" and needs_kind(r) == "call" else []
YESNO_OPTIONS = ({"label": "Yes", "line": "Answer yes.", "recommended": True}, {"label": "No", "line": "Answer no.", "recommended": False})
def yesno_options(r):
    """(the owner): an open decision whose owner stored no options gets two choices of its own, Yes (recommended, first) and No, as
    choices with the box beside them. [] for any other item: one with stored options shows only those (never Yes/No, Approve or
    Decline added to them; nor to a hand-edited list that broke the shape), and so does one that asks no decision or is closed. The server takes the same two labels on the same test
    (server._answer), so an answer to an ask that has since gained options, or left the decision, reads as stale."""
    if r.get("status") == "completed" or "decision" not in [x.lower() for x in needs_of(r)] or (r.get("metadata") or {}).get("options"): return []
    return [dict(o) for o in YESNO_OPTIONS]
def option_lines(r):
    """The options as plain lines, "label (recommended): line", for a tool reply or a tooltip."""
    return [f'{_ol.listed(o["label"], i)}{" (recommended)" if o["recommended"] else ""}: {o["line"]}' for i, o in enumerate(options_of(r))]
def when_words(t, clock=True):
    """"Thu Mar 5th 18:30" (clock=False: "Thu Mar 5th"): the rulebook's form for a date a person reads. t = an aware datetime
    (drawn in its own zone) or a date (no clock). Board.when and the server's replies use it."""
    if not isinstance(t, datetime.datetime): clock = False
    d = t.day
    return f"{t:%a %b} {d}{'th' if 11 <= d % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')}" + (f" {t:%H:%M}" if clock else "")
def age_words(seconds):
    """An age in words: "12 min", "5 h", "2 d" (minutes below 90 min, hours below 36 h, days from then on)."""
    m = int(max(0.0, float(seconds)) // 60)
    return f"{m} min" if m < 90 else (f"{m // 60} h" if m < 60 * 36 else f"{m // 1440} d")
def confirmed_at(r, path=None):
    """When an item was last confirmed true (epoch seconds): its top-level `confirmed` (set on create, on every state
    change and by the confirm tool); an item without one reads as confirmed at its state_updated, else updated, else the
    file's mtime (`path`, or the row's _path), else 0. The one place that knows the fallbacks: the server and the renderer both use it."""
    for k in ("confirmed", "state_updated", "updated"):
        try:
            v = float(r.get(k) or 0)
            if v > 0: return v
        except (TypeError, ValueError): pass
    try: return os.path.getmtime(path or r["_path"])
    except Exception: return 0.0
_FRESH_KEY = {"call": "call_days", "": "agent_days", "relay": "external_days"}
def freshness(r, now):
    """("fresh" | "stale" | "held", age in seconds) of an item; computed only, never sent. age = now − confirmed_at(r)
    (the wake pass moves state_updated but never `confirmed`, so a woken item reads stale until its owner refreshes it). An
    item on hold, or after an open item, and a verifying item that waits on its end date, is "held", never stale: it is held
    until its own wake, its blocker's close or its end date (waiting.py); a completed one is never stale. Otherwise stale once
    the age reaches its lane's limit ([freshness] call_days for your call, agent_days for on agent, external_days for on others;
    config.freshness_days). now = an aware datetime or epoch seconds."""
    t = now.timestamp() if isinstance(now, datetime.datetime) else float(now)
    age = max(0.0, t - confirmed_at(r))
    if is_parked(r) or waits_on_end(r):     # held until its own wake, its blocker's close or its end date: no stale mark
        return "held", age
    if r.get("status") == "completed": return "fresh", age
    days = _cfg.freshness_days()[_FRESH_KEY[needs_kind({"metadata": r.get("metadata") or {}})]]
    return ("stale" if age >= days * 86400 else "fresh"), age
def ask_of(r):
    """An item's ask line as stored (metadata.ask, stripped), "" when it has none."""
    return str((r.get("metadata") or {}).get("ask") or "").strip()
def open_ask(r):
    """The ask line while it is an open question, as open_options for the options: an open item that still needs his
    decision (an item whose decision had left its needs still showed its ask on its page and in
    get, and read as waiting on him). "" otherwise; the stored line stays (a decision put back brings it back), and the item
    page's History names it on the line where the decision left the needs."""
    return ask_of(r) if r.get("status") != "completed" and needs_kind(r) == "call" else ""
# A design decision's mockup (a claude.ai artifact page, or a /mockup/<n> page of the fleet tool's web UI) is linked on the question itself: the home row and the item page's Ask block draw
# "Mockup ↗" beside the Decide part, so the owner opens the design from the ask he answers and not only from the item's background.
_HOST_RX = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*"   # dot-separated labels of letters, digits and inner hyphens: never ".", ".." or "-" alone
def mockup_hosts():
    """The hosts whose https://<host>/mockup/<n> page counts as a mockup, from the instance config only ([client] mockup_hosts, a list or one name; read at use, so a reload is live). A missing
    or misshaped key, an empty list and a list with no usable host give no host: then only a claude.ai artifact page is a mockup."""
    v = _cfg.get("client", "mockup_hosts")
    if isinstance(v, str): v = [v]
    if not isinstance(v, (list, tuple)): return ()
    return tuple(h.strip().lower() for h in v if isinstance(h, str) and re.fullmatch(_HOST_RX, h.strip()))
@functools.lru_cache(maxsize=8)
def _mockup_rx(hosts):
    tail = r"[^\s<>()\[\]\"'`]+"
    alts = ["https://claude\\.ai/(?:code/)?artifact/" + tail]
    # the host ends at the slash (a lookalike such as <host>.evil.example never matches), the id is digits only and ends at a non-word character or a sentence dot; the scheme starts the token,
    # so a link that follows any other character (a word character or / . = ? & % - # @ : , ...) is quoted inside something else and is no mockup; only white space, a bracket, a quote or markdown emphasis may precede it
    if hosts: alts.append(r"(?<![^\s<>()\[\]\"'`*])https://(?P<sala>(?i:" + "|".join(re.escape(h) for h in hosts) + r")/mockup/[0-9]+(?![\w-]|\.\w)(?:[/\\?#]" + tail + ")?)")
    return re.compile("|".join(alts))
def _dot_segment(link):
    """True when the path of a link holds a . or .. segment, spelled plainly or percent-encoded, with a backslash read as a slash as a browser does: it would walk out of /mockup/<n> to another page of the host."""
    from urllib.parse import unquote
    path = re.split(r"[?#]", link, maxsplit=1)[0].split("//", 1)[-1]
    return any(seg in (".", "..") for seg in unquote(path).replace("\\", "/").split("/"))
def mockup_hit(text):
    """The first mockup link in `text` (a claude.ai artifact page or a configured host's /mockup/<n> page), its trailing sentence punctuation dropped; "" when it has none."""
    for m in _mockup_rx(mockup_hosts()).finditer(str(text or "")):
        if m.groupdict().get("sala") is not None and _dot_segment(m.group(0)): continue   # the whole match: a trailing /.. is a dot segment, not sentence punctuation
        return m.group(0).rstrip(".,;:!?")
    return ""
def _vtime(v):
    """A stored version's own time: the later of its `updated` and `confirmed` clocks, 0.0 when it has neither."""
    out = 0.0
    for k in ("updated", "confirmed"):
        try: out = max(out, float(v.get(k) or 0))
        except (TypeError, ValueError): pass
    return out
def id_href(g): return f"/items/{_gh.href_id(g)}"                 # an item's own page: /items/s5,
def item_href(r): return id_href(r["gid"])                         # an issue-numbered item's at /items/<n>, a temporary one's at /items/board-tmp-<machine>-3
def shown_full(g): return _gh.shown(g)                             # an id as a session reads it: board#N, board-tmp-<machine>#3, an older letter-and-number id as it is
def shown(g):                                                      # an id on the board itself: #7 ("board" crowds the UI), the rest as shown_full
    t = shown_full(g); return t[len("board"):] if t.startswith("board#") else t
def rid_full(r): return shown_full(r["gid"])                       # board.md and the brief, which sessions read and quote: board#N
def _page_key(v):
    v = str(v or "").strip().strip("/")
    if not v: return ""
    if v.endswith(".md"): v = v[:-3]
    return v if "/" in v else _cfg.page_dirs()[0] + "/" + v   # items store the full page key; a bare value is legacy and means <first [pages] dir>/<slug>
def proj_key(r):
    """The PAGE the item is filed on (its plain detail link): the key every reader that needs the page reads (the board row, the keeper, the anchors, the project page's items and sub-page badge)."""
    return _page_key(_iproj.key_of(r["metadata"]))
def proj_top(r):
    """The item's PROJECT: the page key of the top-level project that owns the page it is filed on (item_project.project_of). What a reader that shows the item's project writes; proj_key is the page."""
    return _page_key(_iproj.project_of(r["metadata"]))
def link_label(u):
    """Short label for a bare URL (never show a raw URL on the board)."""
    from urllib.parse import urlparse
    try: p = urlparse(u)
    except ValueError: return u      # "http://[x" (an invalid IPv6 host): anyone can write one in a comment; the raw text, never a 500 for the page
    h = p.netloc.lower().replace("www.", ""); path = p.path
    m = re.search(r"github\.com/([^/]+/[^/]+)/(issues|pull)/(\d+)", u)
    if m: return f"{m.group(1).split('/')[1]}#{m.group(3)}" if m.group(2) == "issues" else f"{m.group(1).split('/')[1]} PR #{m.group(3)}"
    m = re.search(r"github\.com/[^/]+/([^/]+)/releases(?:/latest)?/?$", u)
    if m: return f"{m.group(1)} releases"
    m = re.search(r"github\.com/[^/]+/([^/]+)/blob/[^/]+/(.+)", u)
    if m: return m.group(2).split("/")[-1]
    if "github.com" in h: return "GitHub"
    if "notion" in h: return "Notion"
    if "docs.google.com" in h: return {"/document": "Google Doc", "/spreadsheets": "Google Sheet", "/presentation": "Google Slides"}.get(next((k for k in ("/document", "/spreadsheets", "/presentation") if path.startswith(k)), ""), "Google Docs")
    if "drive.google.com" in h: return "Drive"
    if "claude.ai" not in h and mockup_hit(u) == u: return "mockup"   # a fleet tool's mockup page: a plain link, never embedded (its pages share the terminal's address)
    if "claude.ai" in h: return "session"
    if "slack.com" in h: return "Slack"
    return h
def m_link(text):
    text = str(text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s<>\)]+)\)", r"[\1](\2)", text)
    def _l(m):
        u = m.group(1); tail = ""
        while u and u[-1] in ".,;:!?": tail = u[-1] + tail; u = u[:-1]
        return f"[{link_label(u)}]({u}){tail}"
    return re.sub(r"(?<!\()(https?://[^\s<>\)]+)", _l, text)
def anchor_key(u):
    try:
        from stackshot.anchors import anchors as _anc
        return _anc.anchor_id(str(u))
    except Exception:
        return None
def dur(s):
    """A span of time, 9m / 1h / 2d — the page's one format; the page script's dur() says the same, keep them in step."""
    m_ = max(int(s), 0) // 60
    return f"{m_}m" if m_ < 60 else f"{m_ // 60}h" if m_ < 48 * 60 else f"{m_ // 1440}d"
def ago(s): return "just now" if s < 60 else dur(s) + " ago"
def cli_behind(v, latest):
    """True when a machine's CLI version is older than the npm latest (numeric compare; unknown → False)."""
    try: return bool(latest) and tuple(int(x) for x in v.split(".")) < tuple(int(x) for x in str(latest).split("."))
    except Exception: return False
def esc(x): return H.escape(str(x), quote=True)
_CODE = re.compile(r"`([^`\n]+)`")
_LINK_OR_CODE = re.compile(r"\[([^\]]{1,300})\]\((https?://[^\s<>\)]{1,2000})\)|`([^`\n]+)`")   # left to right: a [label](url) whose label holds code stays one link
def _code(text): return "".join(f"<code>{esc(x)}</code>" if i % 2 else esc(x) for i, x in enumerate(_CODE.split(str(text))))
# ---- a bare address: a host with or without a path, written without https://, is a link too ----
# It counts only when the host's last label is one of BARE_TLDS: an explicit, small list of real top-level domains, so a file name
# (render.py, config.toml, a.b.c), a version (1.2.3), an IP address or a sha never reads as an address. Left out on purpose: every
# ending that is also a common file type (py, md, rs, pl, ts, zip, mov, cc). "sh", "so", "info" and "app" are in, because bun.sh/install,
# notion.so/page, example.info and example.app are real addresses, but only with a path after the host (BARE_TLD_NEEDS_PATH): a lone
# install.sh, libfoo.so, logger.info or Claude.app is a file or code. Code stays text in two more ways: a host whose first label is a
# common code receiver (CODE_RECEIVERS: self.io, os.me, logger.dev) is not an address, and a host followed by "(" is a call
# (logger.info("x")). A name in a file's ending that is also a TLD and has no path (logo.ai) is still taken for an address.
# The address is not preceded by an ASCII letter, digit, "_", "@", "/", "." or "-" (an e-mail address, the host of an https://
# address, a longer name) and not followed by "@", "(", an ASCII letter, digit, "_" or "-", or ".<word>" (a name with more labels,
# such as config.toml.example). Only ASCII counts in those look-arounds and in the address itself, so a non-ASCII particle or word
# glued to it (an address with a particle written right after or before it) does not hide an address or become part of it: the path stops at the first
# non-ASCII character. A path or query runs to white space, a quote, a bracket, a backtick or a non-ASCII character; a trailing
# . , ; : ! ? * is prose. Never inside an https:// address, a [label](target) of up to 300 label and 2000 target characters or a `code span`.
# The href is "https://" + the address as written.
BARE_TLDS = frozenset("com org net io ai dev app co kr gov edu me so sh info biz xyz cloud tech page site online uk de jp fr eu ca au".split())
BARE_TLD_NEEDS_PATH = frozenset({"so", "sh", "info", "app"})
CODE_RECEIVERS = frozenset("self cls this os sys logger logging".split())
_ADDR_RX = re.compile(
    r"(?P<skip>https?://[^\s<>\"\)]+|\[[^\]\n]{0,300}\]\([^)\s]{0,2000}\)|`[^`\n]+`)"
    r"|(?ai:(?<![A-Za-z0-9_@/.\-])(?P<host>(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?P<tld>" + "|".join(sorted(BARE_TLDS, key=len, reverse=True)) + r"))"
    r"(?![A-Za-z0-9_@(\-]|\.[A-Za-z0-9_])(?P<rest>(?::\d{1,5})?(?:[/?#][^\s<>\"'`()\[\]\x80-\U0010ffff]*)?))")
def _addresses(text):
    """[(start, end, bare)] of the web addresses in a plain-text run, in order: an https:// address (bare False, its trailing . , ; : ! ?
    left out, as the board always did) and a bare address (bare True; see above). A markdown link and a code span are skipped."""
    out = []
    for m in _ADDR_RX.finditer(text):
        s = m.group("skip")
        if s is not None:
            if s.startswith(("http://", "https://")):
                u = s
                while u and u[-1] in ".,;:!?": u = u[:-1]
                out.append((m.start(), m.start() + len(u), False))
            continue
        u = m.group(0)
        while u and u[-1] in ".,;:!?*": u = u[:-1]
        if m.group("tld").lower() in BARE_TLD_NEEDS_PATH and not u[len(m.group("host")):].startswith("/"): continue
        if m.group("host").split(".")[0].lower() in CODE_RECEIVERS: continue
        out.append((m.start(), m.start() + len(u), True))
    return out
def _board_host():
    """The board's own host, from [instance] board_url ("" when unset)."""
    from urllib.parse import urlsplit
    try: return (urlsplit(str(_cfg.get("instance", "board_url") or "")).hostname or "").lower()
    except ValueError: return ""
def _url_own(u):
    """True when an absolute http(s) address is on the board's own host ([instance] board_url)."""
    from urllib.parse import urlsplit
    own = _board_host()
    if "\\" in str(u): return False                       # a browser reads "\" as "/": https://other.example\@board.example/x goes to the first host, urlsplit says the second
    try: return bool(own) and (urlsplit(str(u).strip()).hostname or "").lower() == own
    except ValueError: return False
def _a_html(href, inner, own, rel="noopener"):
    """One link, `href` and `inner` already escaped: on the board's own host the same tab and no arrow, on any other host a new tab with `rel` and the arrow."""
    return f'<a href="{href}">{inner}</a>' if own else f'<a href="{href}" target="_blank" rel="{rel}">{inner} ↗</a>'
def _bare_link(addr):
    """A bare address → its link: href https://<address>, the short label of link_label, a new tab with rel="noopener noreferrer" (the board's own host: the same tab, see _a_html)."""
    u = "https://" + addr
    return _a_html(esc(u), esc(link_label(u)), _url_own(u), "noopener noreferrer")
def linkify(text):
    """[label](url) → labelled link; a bare url → link with a domain-derived label. Never a raw URL. A `backticked` span →
    <code>, its text verbatim and never linked."""
    text, out, i = str(text), [], 0
    for m in _LINK_OR_CODE.finditer(text):
        out.append(_linkify_run(text[i:m.start()])); i = m.end()
        out.append(f"<code>{esc(m.group(3))}</code>" if m.group(3) is not None
                   else _a_html(esc(m.group(2)), _code(m.group(1)), _url_own(m.group(2))))
    return "".join(out) + _linkify_run(text[i:])
def _linkify_run(text):
    """A run of plain text → HTML: each bare address (see _addresses) a link, the rest through _linkify_plain (markdown links and https:// addresses)."""
    out, i = [], 0
    for a, b, bare in _addresses(text):
        if not bare: continue
        out.append(_linkify_plain(text[i:a])); out.append(_bare_link(text[a:b])); i = b
    return "".join(out) + _linkify_plain(text[i:])
def _linkify_plain(text):
    text = esc(text)
    text = re.sub(r"\[([^\]]{1,300})\]\((https?://[^\s<>\)]{1,2000})\)", lambda m: _a_html(m.group(2), m.group(1), _url_own(H.unescape(m.group(2)))), text)
    def _a(m):
        u = m.group(1); tail = ""
        while u and u[-1] in ".,;:!?": tail = u[-1] + tail; u = u[:-1]     # trailing punctuation is prose, not URL
        return _a_html(u, esc(link_label(u)), _url_own(H.unescape(u))) + tail
    return re.sub(r'(?<!href=")(?<!">)(https?://[^\s<>"\)]+)', _a, text)
# ---- the item page's text as markdown (GitHub's mirrored issues already show it as markdown) ----
# A safe subset through markdown-it-py: paragraphs, nested lists, **bold** / *italic*, `code` and fenced code, > quotes, and
# [text](url) links; a single newline is a line break (as on GitHub's comments), so old text written a line at a time reads as before.
# An image ![alt](url) is shown as its plain link (alt text, then the arrow), never an <img>. Left off, so the text stays plain: raw HTML (html=False: <script> is shown as text), tables, headings (a "# Title" line is
# an ordinary paragraph line), horizontal rules, indented code, reference links, entities, autolinks. A link opens only for http or
# https (validateLink below, on top of markdown-it's own refusal of javascript: and data:); anything else stays as typed. A bare
# url becomes a labelled link as everywhere on the board (link_label), by a core rule on the text nodes outside links and code.
# Board.mentions then links item ids and live session names on the finished HTML, which skips links, code, pre and tags.
def _md_drop_bad_links(state):
    """A link or an image whose address is not http(s) (an empty one, `[x]()`, `![a]()`: markdown-it keeps the token with href "") leaves only
    its label as plain text: no <a href="">. validateLink already empties a javascript: or data: address, which lands here the same way."""
    ok = lambda u: bool(re.match(r"https?://", str(u or "").strip(), re.I))
    for blk in state.tokens:
        if blk.type != "inline" or not blk.children: continue
        out, skip = [], False
        for t in blk.children:
            if t.type == "link_open" and not ok(t.attrGet("href")): skip = True; continue
            if t.type == "link_close" and skip: skip = False; continue
            if t.type == "image" and not ok(t.attrGet("src")):
                if t.content: out.append(_md_text(state, t.content))
                continue
            out.append(t)
        blk.children = out
def _md_bare_urls(state):
    from markdown_it.token import Token
    md = state.md
    for blk in state.tokens:
        if blk.type != "inline" or not blk.children: continue
        out, depth = [], 0
        for t in blk.children:
            if t.type == "link_open": depth += 1
            elif t.type == "link_close": depth = max(depth - 1, 0)
            if t.type != "text" or depth or ("://" not in t.content and "." not in t.content): out.append(t); continue
            s, i = t.content, 0
            for a, b, bare in _addresses(s):                                      # https:// and bare addresses, trailing punctuation left out
                u = ("https://" + s[a:b]) if bare else s[a:b]
                if not u or not md.validateLink(u): continue
                if a > i: out.append(_md_text(state, s[i:a]))
                lo = Token("link_open", "a", 1); lo.attrs = {"href": md.normalizeLink(u)}; lc = Token("link_close", "a", -1)
                if bare: lo.meta = {"bare": True}
                out += [lo, _md_text(state, link_label(u)), lc]
                i = b
            if i < len(s): out.append(_md_text(state, s[i:]))
        blk.children = out
def _md_text(state, s):
    from markdown_it.token import Token
    t = Token("text", "", 0); t.content = s; return t
def _md_own_links(state):
    """Marks each link, and its closing token, that points at the board's own host (meta "own"): it opens in the same tab, with no arrow."""
    for blk in state.tokens:
        if blk.type != "inline" or not blk.children: continue
        own = False
        for t in blk.children:
            if t.type == "link_open": own = _url_own(t.attrGet("href") or "")
            if own and t.type in ("link_open", "link_close"): t.meta = {**(t.meta or {}), "own": True}
            if t.type == "link_close": own = False
def _md_link_open(self, tokens, idx, options, env):
    t = tokens[idx]; m = t.meta or {}; href = esc(t.attrGet("href") or "")
    if m.get("own"): return f'<a href="{href}">'                                    # the board's own host: the same tab
    return f'<a href="{href}" target="_blank" rel="noopener{" noreferrer" if m.get("bare") else ""}">'
def _md_link_close(self, tokens, idx, options, env): return "</a>" if (tokens[idx].meta or {}).get("own") else " ↗</a>"
def _md_image(self, tokens, idx, options, env):   # no <img>: an image is its plain link, alt text (else the short label) as the words, no leading "!"
    t = tokens[idx]; src = t.attrGet("src") or ""
    return _a_html(esc(src), esc(t.content or link_label(src)), _url_own(src))
def _md_make():
    from markdown_it import MarkdownIt      # here and not at the top: publish.py (the brief, flush and bump, on the system python) imports this module and never renders item text
    md = MarkdownIt("zero", {"html": False, "linkify": False, "breaks": True, "typographer": False})
    md.enable(["paragraph", "text", "newline", "escape", "backticks", "emphasis", "link", "image", "blockquote", "list", "fence"])
    ok = md.validateLink
    md.validateLink = lambda url: bool(re.match(r"https?://", str(url).strip(), re.I)) and ok(url)
    md.add_render_rule("link_open", _md_link_open); md.add_render_rule("link_close", _md_link_close); md.add_render_rule("image", _md_image)
    md.core.ruler.push("drop_bad_links", _md_drop_bad_links)
    md.core.ruler.push("bare_urls", _md_bare_urls)
    md.core.ruler.push("own_links", _md_own_links)
    return md
_MD = None
def _md():
    """The parser, built on first use. None when markdown-it-py cannot be imported (md_block and md_inline then fall back to the plain escaped text)."""
    global _MD
    if _MD is None:
        try: _MD = _md_make()
        except ImportError as e:
            _MD = False; print(f"render: markdown-it-py is not importable ({e}); item text is shown as plain text", file=sys.stderr, flush=True)
    return _MD or None
_MD_LIST = re.compile(r"[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+\S"); _MD_FENCE = re.compile(r"[ \t]{0,3}(`{3,}|~{3,})")
def _md_prep(text):
    """What the item text was written for, made explicit before markdown reads it, outside fenced blocks only: a "•" bullet line is a "-"
    one, and a plain line right after a list line starts a new paragraph (a blank line goes before it), where CommonMark would fold it into
    the last list item. Old items are a label, "- " lines, then a plain line ("Done when ..."). A line of a quote ("> "), a list marker or two
    or more spaces of indent (a continuation of the item) is left where it is."""
    out, fence, in_list = [], "", False
    for ln in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = _MD_FENCE.match(ln)
        if fence:
            out.append(ln)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not ln.strip().strip(fence[0]): fence = ""
            continue
        ln = re.sub(r"^([ \t]*)•[ \t]+", r"\1- ", ln)
        if m: fence = m.group(1)
        if not ln.strip(): in_list = False
        elif _MD_LIST.match(ln): in_list = True
        elif in_list and not ln.startswith(("  ", "\t", ">")):
            out.append(""); in_list = False
        out.append(ln)
    return "\n".join(out)
def md_block(text):
    """Item text (a description, a comment) → HTML, block level: the safe markdown subset above, after _md_prep."""
    md = _md()
    if md is None: return "<ul>" + nested_html(sentences(text)) + "</ul>"     # no parser: the text as it was shown before, escaped, one bullet per sentence
    return md.render(_md_prep(text))
def md_inline(text):
    """One line (a Next step) → HTML, inline level: bold, italic, code and links only, no block."""
    md = _md()
    return linkify(text) if md is None else md.renderInline(str(text or ""))
# what a mention never reaches in escaped HTML (Board.mentions): an existing link, code, a tag (its attributes, an href), a
# `backticked` span (within one text run: a stray backtick never pairs across cells) and an entity (&#x27; would read as the
# id x27); left to right, so the first match wins
_MSKIP = r"<a\b[^>]*>.*?</a>|<(?P<raw>code|pre|script|style)\b[^>]*>.*?</(?P=raw)>|<[^>]*>|`[^`<>\n]+`|&#?\w+;"
_BOARD_MENTION = r"board-tmp-[a-z0-9-]*[a-z0-9]#[1-9]\d*|board#[1-9]\d*"   # an issue-numbered or temporary id as a person writes it
def badge(txt, cls=""): return f'<span class="badge {cls}">{esc(txt)}</span>'
NO_OUTCOME = "closed (no outcome recorded)"      # what an item the migration back-filled as `unrecorded` is called wherever the outcome is shown


def outcome_word(oc):
    """An outcome as a person reads it: `unrecorded` (closed before the item model with no outcome in its record, written by the migration only) is "closed (no outcome recorded)"."""
    return NO_OUTCOME if oc == "unrecorded" else oc


def outcome_of(r):
    """How a completed item ended: (outcome, reason, superseded_by), or ("", "", "") for an open item or one closed before
    the close carried them (no backfill)."""
    if r.get("status") != "completed": return "", "", ""
    m = r.get("metadata") or {}
    return str(m.get("outcome") or ""), str(m.get("reason") or ""), str(m.get("superseded_by") or "")
from stackshot.anchors.anchors import KINDS as _KIND     # an anchor id's prefix → its type; the one table, shared with anchor-hub
from stackshot.anchors import anchors as _anc   # roles.json's live flag per session (roles_live)
from stackshot.anchors.anchors import hub_of as _hub_of   # the page a key belongs to on the board (a `hub:` line, else its top-level page)
_KIND_ORDER = ["Slack", "Notion", "Gmail", "Drive", "GitHub", "Link"]
# The board as an installed app (Chrome "Install page as app", display standalone). The manifest (/manifest.webmanifest,
# served by server.py) is fetched with credentials: Chrome fetches a manifest without cookies unless the link says
# use-credentials, and the hostname sits behind Cloudflare Access, which turns a cookieless request away. In an app window a
# target="_blank" link opens another app window whose Back closes it, so there a click on a same-origin _blank link
# navigates the window itself; links to other origins keep opening outside the app, and an ordinary browser tab is
# unchanged (items still open in a new tab). The listener is delegated on the document, so links the board's in-place
# update swaps in (_LIVE_JS) are covered without a re-bind, and the display mode is read at click time, so a page that
# moves between a tab and an app window follows the move. A click with a modifier or another button keeps its default.
# The icons' URLs carry a version, ?v=<the first 12 hex digits of the SHA-256 of the file's bytes>, so a new icon is a new URL:
# an installed app (Chrome, Android) takes its icons through the browser's HTTP cache and Cloudflare's edge, and an icon
# under an unchanged URL never reached it (the maskable icon stayed the old white one). The
# versions are read once, when this module is imported (the server's start; deploy.sh restarts it when icons/ changes),
# from the committed icons/ (auth/signin.py _APP_ICONS) and the favicon in <state>/site. The version is a query string and the
# file names stay: the Cloudflare Access bypass names the icons' exact paths, which a query string keeps and a new name would
# not. server.py serves a request whose ?v= is the version of the bytes it sends as immutable; any other, as before.
ICON_DIR = _paths.ROOT / "icons"
def asset_version(p) -> str:
    """A file's version for its URL: the first 12 hex digits of the SHA-256 of its bytes; "" when it cannot be read."""
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:12]
    except OSError:
        return ""
ICON_V = {p.name: asset_version(p) for p in sorted(ICON_DIR.glob("*")) if p.suffix in (".png", ".ico")}
ICON_V["favicon.svg"] = asset_version(_cfg.state("site", "favicon.svg"))
def icon_href(name: str) -> str:
    """An icon's URL with its version: /<name>?v=<version>, or /<name> for a file that is not there."""
    v = ICON_V.get(name)
    return f"/{name}?v={v}" if v else f"/{name}"
# D2Coding (Naver, SIL OFL 1.1), the font of command blocks and inline code on the board and the item pages,
# served by stackshot itself from the committed fonts/ (auth/signin.py _FONT_PATH): one regular-weight WOFF2 of Naver's
# Ver 1.4.0 release, converted without subsetting (fonts/README.md). Its URL carries the version of its bytes, like the icons',
# so the file is kept a year; the @font-face has font-display:swap, so the text shows in the fallback stack until it is in.
FONT_DIR = _paths.ROOT / "fonts"
FONT_FILE = "D2Coding-Regular.woff2"
def font_href() -> str:
    """The D2Coding file's URL with its version: /fonts/D2Coding-Regular.woff2?v=<version>, unversioned when the file is not there."""
    v = asset_version(FONT_DIR / FONT_FILE)
    return f"/fonts/{FONT_FILE}?v={v}" if v else f"/fonts/{FONT_FILE}"


class Board:
    """The board's data, read once: items, sessions, projects, anchors, versions, the hub's status — and what is drawn from it."""

    def __init__(self, data_dir: str, now=None):
        ZONE = _cfg.tz(); now = now or datetime.datetime.now(ZONE)
        PUB = str(_cfg.get("fleet", "publisher_letter") or "a")                  # the box that runs the server: first column, always live
        FLEET = fleet_names()                                                    # letter → fleet name
        TITLE = str(_cfg.get("instance", "title") or _cfg.get("instance", "name") or "stackshot")
        _PKGS = list(_cfg.get("machines_panel", "packages") or [])
        PKG_ORDER = [x["name"] for x in _PKGS]                                   # rows of the Machines panel, top to bottom
        OWNER = {x["name"]: x["owner"] for x in _PKGS if x.get("owner")}         # the session with jurisdiction over a package; its card links to it
        ANCH_STATUS_FILE = str(_cfg.state("anchor-hub", "status.json")); VERSIONS_FILE = str(_cfg.state("site", "versions.json"))

        rows, urls = [], {}
        SESS = {}                      # session objects by id (transcript UUID / cse_…) and by "name:<label>"
        # sessions (heartbeat, the fleet tool): the LIVE store outside git (fleet.py), {id: {name, url, seen, machine}}
        # keyed by the pane's transcript UUID; a LEGACY {name: url} shape is still accepted. urls[L] keeps name → url, SESS
        # collects session objects by id and by name. Items stay in board-data/<letter>/ in git.
        for L in _fleet.letters():
            urls[L] = {}
            for k, v in _fleet.read(L, "sessions").items():
                if isinstance(v, dict):
                    v = {"id": k, "kind": "pane", "machine": v.get("machine") or L, **v}
                    SESS[k] = v
                    if v.get("name"): urls[L][v["name"]] = v.get("url") or ""
                else:
                    urls[L][k] = v; SESS.setdefault("name:" + k, {"id": "", "kind": "pane", "machine": L, "name": k, "url": v})
        # by name: the running session first, then the one gone most recently. A gone row keeps a session's identity (name,
        # link, machine) so its items still name their owner; it never takes a name from a live one.
        for v in sorted([x for x in SESS.values() if x.get("id") and x.get("name")], key=lambda x: (0 if _fleet.running(x) else 1, _fleet.gone_for(x))):
            SESS.setdefault("name:" + v["name"], v)
        letters = sorted(x for x in os.listdir(data_dir) if len(x) == 1 and os.path.isdir(os.path.join(data_dir, x))) if os.path.isdir(data_dir) else []
        for L in letters:
            d = os.path.join(data_dir, L)
            urls.setdefault(L, {})
            merged = load_dir(d)
            for t in merged.values():
                if t.get("status") == "deleted": continue
                t["metadata"] = t.get("metadata") or {}
                if t.get("status") == "on_hold": t["status"] = "open"; t["metadata"]["hold"] = True   # the retired status, until the server's start-time migration rewrites the file
                t["L"] = L; t["gid"] = f"{L}{t['id']}"
                t["owner"] = t["metadata"].get("owner") or t.get("owner") or ""   # metadata.owner is what the server writes; a top-level key is CLI-era legacy (it masked an owner change)
                t["_updated"] = datetime.datetime.fromtimestamp(float(t.get("updated") or os.path.getmtime(t["_path"])), ZONE)   # item clock first, file mtime for legacy items
                rows.append(t)
        open_ids = {r["gid"] for r in rows if r.get("status") != "completed"}
        for t in rows:
            t["_after"] = [g for g in after_of(t) if g in open_ids and g != t["gid"]] if t.get("status") != "completed" else []   # the open items it waits on
        for t in rows:
            t["_fresh"], t["_age"] = freshness(t, now)   # "fresh" | "stale" | "held", seconds since last confirmed; for the queue's ⚠ (drawn by the board side)

        _PROJ = {}
        try: _PROJ = json.load(open(os.path.join(data_dir, "projects.json"), encoding="utf-8")).get("pages", {})
        except Exception: _PROJ = {}
        _PROJ = _prj.with_pending(_prj.with_record(_PROJ))               # A form-made agent showed under Unregistered: one whose page line is still owed is the project's agent here too (the page wins; a retired project gains none)
        live    = [r for r in rows if r.get("status") != "completed" and not is_parked(r)]   # active open items; parked ones (on hold, or after an open item) are kept apart (below)
        held    = sorted([r for r in rows if is_parked(r)], key=lambda r: (wake_key(r), sort_key(r)))
        needs   = sorted([r for r in live if needs_kind(r)], key=sort_key)
        n_call  = [r for r in needs if needs_kind(r) == "call"]
        n_relay = [r for r in needs if needs_kind(r) == "relay"]
        agent   = sorted([r for r in live if not needs_kind(r)], key=sort_key)   # the next move is a session's (status is open|completed, no in-progress)
        done    = sorted([r for r in rows if r.get("status") == "completed" and (now - r["_updated"]).days <= 14], key=lambda r: r["_updated"], reverse=True)
        n_open  = len(needs) + len(agent)              # active open items only; the totals drawn (brief(), the stat tiles, board.md) add the held ones
        open_rows = needs + agent + held               # on hold is a kind of on agent: parked work on the agent side keeps its project row
        by_proj = {}                                   # project page → open items (the index is by project, sessions are a column)
        # the board row an item sits on is decided by the page tree, not by the page it names: the nearest
        # page in its chain that declares `board_row: true`, else the top-level page; the item keeps naming the specific page,
        # which stays the accountable one (page debt, keeper, anchors). A row's anchors are the union of its pages'.
        self.proj = _PROJ
        self.live_flags = _anc.roles_live()            # roles.json's per-session `live` flag (sala's session list; absent when sala could not be read): a name that is not live is not drawn in a session list
        for r in open_rows: by_proj.setdefault(self.row_of(proj_key(r)), []).append(r)
        self.group = {}
        for k in _PROJ: self.group.setdefault(self.row_of(k), []).append(k)
        SCOPES = list(_cfg.get("scopes", "order") or ["personal"])   # the board's project groups, derived from the page's org, tags and key (never a new field)
        _SC_DEFAULT = str(_cfg.get("scopes", "default") or SCOPES[0]); _SC_ORG = _cfg.get("scopes", "by_org") or {}; _SC_TAG = _cfg.get("scopes", "by_tag") or {}; _SC_PRE = _cfg.get("scopes", "by_prefix") or {}
        _ANCH_STATUS, _ANCH_SINCE, _st = {}, None, {}
        try:
            _st = json.load(open(ANCH_STATUS_FILE))
            _ANCH_STATUS = _st.get("anchors", {})
            _ANCH_SINCE = datetime.datetime.strptime(_st.get("history_since") or _st["started"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=now.tzinfo)
        except Exception: pass
        try: _ANCHORS = json.load(open(os.path.join(data_dir, "anchors.json"), encoding="utf-8"))
        except Exception: _ANCHORS = {}
        try: _vdoc = json.load(open(VERSIONS_FILE, encoding="utf-8"))       # written by versions.py; absent = no versions shown
        except Exception: _vdoc = {}
        versions = _vdoc.get("packages", []) if isinstance(_vdoc, dict) else []
        ssh_hosts = [h for h in (_vdoc.get("ssh_hosts") or []) if isinstance(h, dict) and h.get("name")] if isinstance(_vdoc, dict) else []   # machines with no fleet letter, read over ssh
        self.data_dir = data_dir
        self.now, self.title, self.pub, self.fleet, self.pkg_order, self.owner, self.scopes = now, TITLE, PUB, FLEET, PKG_ORDER, OWNER, SCOPES
        self.rows, self.sess, self.proj, self.anchors, self.versions = rows, SESS, _PROJ, _ANCHORS, versions
        self.ssh_hosts = ssh_hosts
        self.hub_status, self.anchor_status, self.anchor_since = _st, _ANCH_STATUS, _ANCH_SINCE        # anchor-hub's status.json, its per-anchor part, the start of its change record
        self.needs, self.n_call, self.n_relay, self.agent, self.done, self.n_open, self.by_proj = needs, n_call, n_relay, agent, done, n_open, by_proj
        self.held = held                               # on-hold items, by wake: drawn as on agent (muted, a pause mark) but never in the queue,
                                                       # and never under your call / on others even when they keep a needs field
        self.recycle = sorted([r for r in rows if recycle_due(r, after_open(r))], key=lambda r: (r["_updated"], sort_key(r)))   # the open items
                                                       # a pane recycle would serve (not held, or held for the recycle alone: recycle_due, the test the
                                                       # server's recycle-wanted uses), oldest update first (as the queue orders); the status line lists them
        open_w = [r for r in rows if r.get("status") != "completed"]
        self.undelivered = [r for r in open_w if isinstance(r["metadata"].get("undelivered"), list) and r["metadata"]["undelivered"]]   # a notice that could not be delivered, on the item
        self.basis_waits = sorted([r for r in open_w if _wt.basis_of(r["metadata"])], key=lambda r: (wake_key(r), sort_key(r)))   # waits that stand on a real-world date (wait_basis): listed once a week in the head
        self.provision = provision_lag(now)            # [(hostname, online)] of the boxes whose stackshot puller is behind
        self.mfacts = {L: _fleet.read(L, "machine") for L in _fleet.letters()}   # each machine's view: its last setup run and update attempts (machine_alerts)
        self._sc = (_SC_DEFAULT, _SC_ORG, _SC_TAG, _SC_PRE)

    # ---------------- the model ----------------
    def basis_due(self):
        """Is today the weekday the head lists the waits that stand on a real-world date ([waiting] basis_weekday, Monday when unset; -1 every day)?"""
        wd = _wt.basis_weekday()
        return wd == -1 or self.now.weekday() == wd

    def mover_name(self, who):
        """A session mover as the Owner field names it (sess_of: a transcript id or a cse_ id → the session's name); an id that does not resolve stays as it is."""
        try: return str((self.sess_of(who) or {}).get("name") or who)
        except Exception: return str(who)
    def sess_of(self, owner, owner_name=""):
        """Resolve an item's owner (session id, or a legacy name) to {id, kind, name, url, machine}."""
        o = str(owner or "")
        if not o: return None
        if o.startswith("cse_"):     # cloud session: its claude.ai title and link from the CLI's own lookup (cloud.py);
            from stackshot.core import cloud as _cloud   # a chat's workspace opens as the chat and keeps the name the session gave
            ci = _cloud.info(o)
            return {"id": o, "kind": "cloud", "name": ci["title"] or owner_name or o, "url": ci["url"], "machine": "c"}
        sid = _sr.resolve(o)
        if sid:                      # the fleet tool's registry knows the session (step B): its name now, on the object of its present transcript
            nm = _sr.display_name(sid) or o
            best = None
            for t in _sr.transcripts(sid):
                x = self.sess.get(t)
                if x is not None and (best is None or (_fleet.running(x), str(x.get("seen", ""))) >= (_fleet.running(best), str(best.get("seen", "")))): best = x
            base = best or self.sess.get("name:" + nm) or {"id": sid, "kind": "pane", "name": nm, "url": "", "machine": ""}
            return {**base, "name": nm}
        if o in self.sess: return self.sess[o]
        if "name:" + o in self.sess: return self.sess["name:" + o]
        return {"id": o if len(o) >= 32 else "", "kind": "pane", "name": owner_name or o, "url": "", "machine": ""}
    # A session name on the web pages links to that session's view in the fleet tool's web UI (link
    # the board and the fleet tool both ways, so on a phone one tap takes the owner from an item to its session; Remote
    # Control is not relied on, so the name no longer opens the url the fleet tool's store gives, which board.md and the brief keep). The link is
    # by name, [client] session_view with {name} url-quoted, read at use (a reload is live), and only while the session holding that name
    # has a live pane by fleet's one rule (present: running, or relaunching within the grace; the name's row is the running
    # one first, else the latest gone, __init__). A name with no live pane, a cloud session's included, stays plain text.
    # Every place that shows a session name draws it here, inline mentions too; the view is another site, so it opens in a new
    # tab, which the installed app's click handler (_APP_HEAD) leaves outside the app window.
    def sess_href(self, name) -> str:
        """The fleet tool's view of the session named `name` ([client] session_view) when it has a live pane, else ""."""
        tpl, n = str(_cfg.get("client", "session_view") or ""), str(name or "")
        x = self.sess.get("name:" + n) if n else None
        if not tpl or not x or x.get("kind") != "pane" or not _fleet.present(x): return ""
        return tpl.replace("{name}", quote(n, safe=""))
    def sess_html(self, name, label=None, cls="", title=None, arrow=False, inner=None) -> str:
        """A session name as HTML: a link to its view (sess_href) when it has a live pane, else the text. label = the words shown
        (default the name; "a/name" or a "-main" suffix on the index), escaped here; inner = HTML already escaped, in its place.
        cls goes on the link or on a <span> around the text; title on the link (default "open this session in <[fleet] tool_name>",
        "open this session's view" when that is unset), and on the span only when given."""
        body = inner if inner is not None else esc(name if label is None else label)
        u = self.sess_href(name); c = f' class="{esc(cls)}"' if cls else ""
        tool = _cfg.fleet_tool(); lt = title or (f"open this session in {tool}" if tool else "open this session's view")
        if u: return (f'<a{c} href="{esc(u)}" target="_blank" rel="noopener" title="{esc(lt)}">'
                      f'{body}{" ↗" if arrow else ""}</a>')
        t = f' title="{esc(title)}"' if title else ""
        return f'<span{c}{t}>{body}</span>' if cls or title else body
    def _mention_rx(self):
        """The one regex Board.mentions runs, built on first use and kept for the Board's life (a Board is one load): _MSKIP,
        else a word-bounded mention, a hyphen counting as part of the word (alpha is not found inside alpha-main).
        A mention is a known session name with a link (longest first) or an id-shaped token, board#N and
        board-tmp-<machine>#3 among them (matched first); whether that token is an item is a lookup in the id map, so nothing
        is linked for looking like an id. Machine names stay plain: not sessions."""
        if getattr(self, "_mrx", None) is None:
            mach = set(self.fleet.values())
            self._mids = {r["gid"]: r for r in self.rows}                                      # open, on hold and completed
            self._mnames = {k[5:] for k in self.sess if k.startswith("name:") and k[5:] not in mach
                            and self.sess_href(k[5:])}   # the names with a live pane (sess_href): each links to its view
            alt = "".join(re.escape(n) + "|" for n in sorted(self._mnames, key=len, reverse=True))
            self._mrx = re.compile(_MSKIP + r"|(?<![\w-])(?P<m>" + _BOARD_MENTION + "|" + alt + r"[a-z]\d+)(?![\w-]|\.\d)", re.S)
        return self._mrx
    def mentions(self, h, own=""):
        """Escaped HTML → the same, with every inline mention of a board item or a session linked:
        an item id to its page,
        a session name to its view (sess_html), both in a new tab as the board's own id and session links open. Never inside
        a link, code, a tag or an entity; `own` (an item page's own id) stays plain. A session with no live pane stays text."""
        def _m(m):
            t = m.group("m")
            if not t: return m.group(0)
            if t in self._mnames: return self.sess_html(t, inner=t)
            g = _gh.norm(t) if t.startswith("board") else t   # → g7, board-tmp-<machine>#3 → l3 (another machine's: no item)
            r = self._mids.get(g)
            if r is None or g == own: return t
            return f'<a href="{item_href(r)}" target="_blank" rel="noopener" title="{esc(r["subject"])}">{esc(shown(g))}</a>'
        return self._mention_rx().sub(_m, h)
    def md_line(self, text, own=""):
        """One line (a Next step) → inline HTML (md_inline), mentions linked."""
        return self.mentions(md_inline(text), own)
    NO_AGENT = "no agent"      # D7: the group of an open item that sits under no agent (it is the owner's and its `then` names none)
    def _sess_obj(self, r): return self.sess_of(*self.mover_ref(r))
    def mover_ref(self, r):
        """The agent an item sits under on the board, as a (session ref, display name) pair: the session that moves it now (alive: its mover; waiting: the one who picks it up when the wait ends);
        an item the owner moves sits under its `then` agent. ("", "") for none: the creator is no one's agent (it stays a History fact, "created by")."""
        try:
            mod = r.get("_mod") or _model.derive(r, self.now.timestamp())
            if mod.state == _model.ALIVE:
                who = mod.then if _model.is_owner(mod.mover) else mod.mover
            else:      # waiting: the one who picks it up when the wait ends; when the owner does, his `then`
                who = (mod.then if _model.is_owner(mod.wait.mover) else mod.wait.mover) if mod.wait else ""
        except Exception: return ("", "")
        if not who or _model.is_owner(who): return ("", "")
        return (who, "")
    def mover_word(self): return "mover"
    def lab(self, r):
        """The agent label an item is drawn under ("machine/name"); the no-agent group's name for an open item that sits under none; "" for a closed item with no session
        (a closed item has no mover, so there is nothing to name: the store letter "g" it used to return drew as a stray letter on the Completed rows)."""
        x = self.sess_of(*self.mover_ref(r))
        if not x: return self.NO_AGENT if r.get("status") != "completed" else ""
        return f"{x.get('machine') or r['L']}/{x.get('name') or x.get('id')}"
    def url(self, r):
        x = self._sess_obj(r); return (x or {}).get("url") or None
    def keeper_split(self, k, rs):
        """The project's keeper — its page's `session:` — as (label, url), and the owners of its open items who are not the
        keeper as {label: (url, [rows], short)} (the column shows the keeper, not every owner). A cloud or
        Cowork keeper is named by its items' owner_name."""
        sid = str((self.proj.get(k) or {}).get("session") or "")
        x = self.sess_of(sid) if sid else None
        st = (f"{x.get('machine') or '?'}/{x.get('name') or x.get('id')}", x.get("url") or "") if x else None
        sname, smach = str((x or {}).get("name") or ""), str((x or {}).get("machine") or "")
        others = {}                                    # label → (url, [rows], short): short = "-<suffix>" for an agent named <keeper>-<suffix>
        for r in rs:                                   # on the keeper's machine (the naming convention makes the suffix enough);
            o = self._sess_obj(r) or {}                # any other owner keeps its full label
            if x and ((o.get("id") and o.get("id") == x.get("id")) or (o.get("name") and o.get("name") == x.get("name"))): continue
            oname = str(o.get("name") or "")
            short = oname[len(sname):] if sname and oname.startswith(sname + "-") and len(oname) > len(sname) + 1 and str(o.get("machine") or r["L"]) == smach else ""
            others.setdefault(self.lab(r), (self.url(r), [], short))[1].append(r)
        return st, others
    def declared_agents(self, k):
        """The agents a hub page lists in its `agents:` line → {name: what it is for} (the keeper writes it, the
        board checks it against the open items and the live sessions)."""
        a = (self.proj.get(k) or {}).get("agents")
        return {str(n): str(m) for n, m in a.items()} if isinstance(a, dict) else {}
    def agent_roles(self, k):
        """The page's agents split by role → (front, back), each {name: one-line mandate}: front agents are the ones the owner
        talks to; background agents run out of his sight. The registry's `agents` holds every agent and `back_agents` the
        background ones (pages.py's reading of the page's nested `agents: background:` map); front = the
        rest. (The transitional "background:" mandate prefix went once every page had moved.)"""
        back = {str(n): str(m).strip() for n, m in ((self.proj.get(k) or {}).get("back_agents") or {}).items()}
        front = {n: m.strip() for n, m in self.declared_agents(k).items() if n not in back}
        return front, back
    def lines(self, k, rs):
        return self._lines(k, rs)[1]
    def _lines(self, k, rs):
        """A project's lines on the index, each a session with the open items it owns (an agent is its own
        row with its items on it, instead of a hover): the keeper first, then the other owners by label.
        → [(label, url, short, is_agent, rows, flag, tip)]; short as in keeper_split(); with no keeper the owners are plain lines.
        When the hub page lists its agents (`agents:`), every listed agent has a line, with or without an open item, and the
        line says what does not match: flag "unlisted" = it owns an item here but the page does not list it; "no session" =
        the page lists it but no such session is known to the fleet. tip = the agent's one line of mandate from the page.
        Every session is listed, background agents too (board.md and brief read this); the index thins it in index_lines().
        On a hub row the page's keeper gets a line only while it owns an open item here or is a listed agent
        (retired name-line sessions were back on the index); with no pane it is flagged "no session"
        (a cloud keeper counts as live). Otherwise its line goes and the others keep their full labels.
        _lines → (has a name line first, the lines)."""
        st, others = self.keeper_split(k, rs)
        theirs = {id(r) for _u, g, _s in others.values() for r in g}
        front, back = self.agent_roles(k)
        decl = {**front, **back}; sname = st[0].split("/", 1)[-1] if st else ""; smach = st[0].split("/", 1)[0] if st else ""
        srows = [r for r in rs if id(r) not in theirs] if st else []      # the keeper's own items (keeper_split() left them out of others)
        sflag = ""
        if st and decl:                                                    # a hub row (agents listed): the keeper is no line of its own for nothing
            if not srows and sname not in decl:
                st, sname = None, ""                                       # dropped: no label is shortened against a line that is not shown (smach still names the machine of an unknown listed agent)
                others = {l: (u, g, "") for l, (u, g, _s) in others.items()}
            else:
                sx = self.sess.get("name:" + sname)
                sflag = "" if smach == "c" or (sx and _fleet.present(sx)) else "no session"
        out = [(st[0], st[1], "", False, srows, sflag, decl.get(sname, ""))] if st else []   # a keeper the page lists keeps its mandate
        rest, seen = [], set()
        for l, (u, g, short) in others.items():
            name = l.split("/", 1)[-1]; seen.add(name)
            rest.append((l, u, short, bool(st), g, "unlisted" if decl and name not in decl and l != self.NO_AGENT else "", decl.get(name, "")))
        for name, what in decl.items():                 # a listed agent with no open item still has its line
            if name in seen or name == sname: continue
            x = self.sess.get("name:" + name)
            l = f"{(x or {}).get('machine') or smach or '?'}/{name}"
            short = name[len(sname):] if sname and name.startswith(sname + "-") and (not x or str(x.get("machine") or "") == smach) else ""
            rest.append((l, (x or {}).get("url") or "", short, bool(st), [], "" if x and _fleet.present(x) else "no session", what))   # gone past the grace: not running
        return bool(st), out + sorted(rest, key=lambda t: t[0])
    def proj_state(self, r):
        """→ (key, registry info or None). The "page older than item" badge is gone: the server's page-debt
        ledger is the one freshness signal, and the badge cost a git log per project per render."""
        k = proj_key(r)
        return k, (self.proj.get(k) if k else None)
    def row_of(self, k):
        """The board row a page key rolls up to: itself or the nearest ancestor with `board_row: true`, else its hub page: the
        page a `hub:` line in its chain names (ops/hub sits on the hub project's row, with its keeper and
        agents), else the top-level page."""
        if not k: return ""
        parts = k.split("/")
        for n in range(len(parts), 2, -1):
            cand = "/".join(parts[:n])
            if (self.proj.get(cand) or {}).get("board_row"): return cand
        return _hub_of(k, self.proj)
    def proj_label(self, k):
        """An item's project as the card says it: the scope and the row's name, then the sub-page's when the item sits below the row, with plain
        slashes ("ops/hub/sharing/sub-page", "home/general")."""
        row = self.row_of(k)
        if row == k: return self.proj_title(k)
        return f"{self.proj_title(row)}/{self.sub_title(k, row)}"
    def sub_title(self, k, row):
        """A sub-page's name below its row: an unnamed sub-page is named by its path below the row ("alpha-ops/notes",
        not "alpha-ops/alpha-ops/notes"); a page on another project's row through `hub:`
        keeps its own name. The card's project label and the project page's sub-page badge. No scope: the row's name in front of it has one."""
        return (self.proj.get(k) or {}).get("name") or (k[len(row) + 1:] if k.startswith(row + "/") else self.proj_name(k))
    def proj_name(self, k):
        """The project's name without its scope: the page's `name:`, else the slug — never the long title."""
        info = self.proj.get(k) or {}
        return info.get("name") or (k.split("/", 1)[1] if "/" in k else k) or "no project"
    def proj_title(self, k):
        """The name the board shows for a project: its scope, a slash and its name ("ops/general", "home/general", "work/General"; projects.scoped_name). Made here,
        at display time, from the page key and the page's own lines: the `display-name:` line, the session names and the keys are never changed. An instance with
        a single scope shows the plain name."""
        return _prj.scoped_name(self.label_scope(k), self.proj_name(k))
    def label_scope(self, k):
        """The scope word in front of a project's name (projects.label_scope), read once per key for the draw; "" for no key, a key that is no page, or a single-scope instance."""
        if not k or k not in self.proj: return ""
        c = self.__dict__.setdefault("_lscope", {})
        if k not in c:
            if "_lscope_id" not in self.__dict__:
                try: ids = _prj.ids_by_key()
                except ValueError: ids = {}                    # a damaged id file: the registry's own copy of the id answers
                self.__dict__["_lscope_id"] = (ids, _prj.marks())
            ids, mk = self.__dict__["_lscope_id"]
            c[k] = _prj.label_scope(k, self.proj.get(k) or {}, self.proj, ids, mk)
        return c[k]
    def proj_mirror(self, k):
        return (self.proj.get(k) or {}).get("mirror") or ""
    def proj_scope(self, k):
        _SC_DEFAULT, _SC_ORG, _SC_TAG, _SC_PRE = self._sc
        info = self.proj.get(k) or {}
        if not k: return _SC_DEFAULT
        org = str(info.get("org") or "").lower()
        if org in _SC_ORG: return _SC_ORG[org]
        tags = info.get("tags") or []
        if isinstance(tags, str): tags = [tags]
        for t in tags:
            if str(t).lower() in _SC_TAG: return _SC_TAG[str(t).lower()]
        for pre, sc in _SC_PRE.items():
            if k.startswith(pre): return sc
        return _SC_DEFAULT
    def stamp(self, t, cls="", quiet=False):
        """HTML: a time shown as its age (">21h ago" when it only marks the start of a silence), the full time in an instant CSS
        tooltip (a native title waits ~1 s); the page script keeps the age current. title="" stops a card's own title popping up."""
        s_ = (self.now - t).total_seconds()
        return (f'<span class="tip{" " + cls if cls else ""}" data-ts="{int(t.timestamp())}"{" data-q" if quiet else ""} '
                f'data-tip="{"no change since " if quiet else ""}{t:%Y-%m-%d %H:%M} {_cfg.tz_abbr(t)}" title="">'
                f'{">" + dur(s_) + " ago" if quiet else ago(s_)}</span>')
    def anchor_entries(self, page):
        """One page's anchors from the anchors file, as clean dicts (clean_anchor_entries)."""
        return clean_anchor_entries(self.anchors.get(page))
    def _when(self, st, added=None):
        """HTML (already escaped): the anchor's last activity as a stamp (anchor-hub reads it from the source at first sight);
        none known (a source it cannot read) → ">age ago", counted from the later of the anchor's addition and
        the start of anchor-hub's unbroken change record."""
        u = st.get("unreadable")
        if u:       # the hub asked the source and was refused: no notice can come from it
            return f'<span class="aflag" title="{H.escape("anchor-hub cannot read it since " + str(u.get("since")) + " " + _cfg.tz_abbr() + ": " + str(u.get("why")), quote=True)}">unreadable</span>'
        when = "quiet"
        if st.get("last"):
            try: when = self.stamp(datetime.datetime.strptime(st["last"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=self.now.tzinfo))
            except Exception: when = H.escape(str(st["last"]))
        else:
            try: ad = datetime.datetime.fromtimestamp(float(added), self.now.tzinfo) if added else None
            except (TypeError, ValueError, OverflowError, OSError): ad = None      # an `added` that is no time shows nothing
            since = [x for x in (self.anchor_since, ad) if x]
            if since: when = self.stamp(max(since), quiet=True)
        if st.get("mode") == "poll": when += " · poll"
        return when
    def proj_anchor_groups(self, k):
        """A project's anchors grouped by type, in a fixed order (one row per type, one chip per type that
        opens the list). → [(kind, [(name, url, when, scope, hot)], any_hot)]."""
        from stackshot.anchors import anchors as _anc
        groups = {}
        seen = set()
        for e in [e for page in (self.group.get(k) or [k]) for e in self.anchor_entries(page)]:   # the row and every page under it
            if (str(e.get("url")), tuple(e.get("items") or ())) in seen: continue
            seen.add((str(e.get("url")), tuple(e.get("items") or ())))
            u = str(e.get("url") or ""); base, _frag = _anc.split_fragment(u)
            key = anchor_key(base); st = self.anchor_status.get(key, {}) if key else {}
            kind = _KIND.get((key or "").split(":", 1)[0], "Link")
            name = st.get("title") or st.get("label") or (key or base); url = st.get("url") or (base if base.startswith("http") else "")
            scope = "project-wide" if not e.get("items") else ", ".join(e["items"])
            hot = False
            try:
                hot = bool(st.get("last")) and (self.now - datetime.datetime.strptime(st["last"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=self.now.tzinfo)).total_seconds() < 86400
            except Exception:
                hot = False
            groups.setdefault(kind, []).append((name, url, self._when(st, e.get("added")), scope, hot))
        return [(kind, groups[kind], any(x[4] for x in groups[kind])) for kind in _KIND_ORDER if kind in groups]

    def routing_counts(self, k):
        """The row's last 24 hours from the routing log, over every page that rolls up to it."""
        return _routing.counts(self.group.get(k) or [k], now=self.now.timestamp(), wait=60.0 * float(_cfg.get("pilot", "waiting_minutes") or 60))
    WATCH = {"bad": ("broken", "needs a person"), "wait": ("waiting", "a notice is waiting for its ruling"), "ok": ("ok", "all heard"),
             "none": ("—", "nothing watched")}
    def watch(self, k):
        """The row's watch state (a green / yellow / red icon showing status health;
        mapping by my-main), or None for the no-project row. → (state, the detail lines). Precedence bad > wait > ok > none:
        bad = an anchor anchor-hub cannot read;
        wait = a notice unruled past [pilot] waiting_minutes; ok = something watched and all of it heard and ruled;
        none = no anchors and nothing in the log. The counts go in the overlay, one per line, not in the cell. anchor-hub itself being down is the
        Machines panel's, not this column's: it blinds every row at once."""
        from stackshot.anchors import anchors as _anc
        if not k: return None
        c = self.routing_counts(k); keys = self.group.get(k) or [k]
        n_anch = sum(len(self.anchor_entries(p)) for p in keys)
        bad = sum(1 for p in keys for e in self.anchor_entries(p)
                  if (self.anchor_status.get(anchor_key(_anc.split_fragment(str(e.get("url") or ""))[0]) or "") or {}).get("unreadable"))
        mins = lambda key, d: int(float(_cfg.get("pilot", key) or d))
        span = lambda m: "an hour" if m == 60 else f"{m // 60} hours" if m % 60 == 0 else f"{m} minutes"
        pl = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
        state = ("bad" if bad else "wait" if c["waiting"] else "ok" if (n_anch or c["in"] or c["pending"]) else "none")
        parts = [pl(n_anch, "anchor") + " watched" + (f", {bad} unreadable by anchor-hub" if bad else ""),
                 pl(c["in"], "notice") + " in the last 24 hours"]
        if c["waiting"] > 0: parts.append(f"{c['waiting']} unruled past {span(mins('waiting_minutes', 60))}")
        return state, parts
    def when(self, ts, clock=True):
        """"Mon Mar 2nd 20:00" (clock=False: "Mon Mar 2nd"): the rulebook's form for a date a person reads, in the board's zone.
        ts = epoch seconds, a datetime, or a date (a date has no clock)."""
        if isinstance(ts, datetime.datetime): t = ts.astimezone(self.now.tzinfo)
        elif isinstance(ts, datetime.date): t, clock = ts, False
        else: t = datetime.datetime.fromtimestamp(float(ts), self.now.tzinfo)
        return when_words(t, clock)
    def new_hold_words(self, r):
        """A new hold's words for the briefings: "set by my-x Sat Mar 21st 09:00 · wake Mon Mar 23rd · held by after board#N",
        or "… · nothing holds it now" when no open after, recycle, needs external or item-scoped anchor holds it."""
        h, w = hold_set_of(r), wake_of(r)
        why = hold_whys(r, self.scoped_urls(r["gid"]), self.after_words(r))
        return " · ".join([f"set by {hold_by(r) or 'unknown'} {self.when(hold_at(r))}", f"wake {self.when(w)}" if w else "no wake date", "held by " + ", ".join(why) if why else "nothing holds it now"])
    def after_words(self, r):
        """"after board#N" (several: "after board#N, board#M"): the open items an item waits on, "" when none."""
        a = after_open(r)
        return ("after " + ", ".join(shown(g) for g in a)) if a else ""
    def md_hold(self, r):
        """board.md's mark on a parked item: "on hold, wake Thu Mar 12th 09:30", "on hold, no wake date", or "after board#N"."""
        w = wake_of(r); parts = []
        if is_held(r): parts.append("on hold, " + (f"wake {self.when(w)}" if w else "no wake date"))
        if after_open(r): parts.append(self.after_words(r))
        return "; ".join(parts)
    # ---------------- the trailers: his words on an item ----------------
    def said_tag(self, r, n, tag, who="", checked=True):
        """The History's tag for one of his recorded words, on the line of the write that recorded them: "Acked-by the owner",
        reading "Acked-by the owner · unchecked" itself when the transcript could not be read. It expands (a details element) to the
        quote, the session he said it in (linked like other session names), the message's time in the board's zone, and whether
        it was checked. Anchored said-<n> (the entry's position on the item), where the issue's trailer link lands."""
        e = esc
        ents = _said.entries_of(r["metadata"]); ent = ents[n - 1] if 0 < n <= len(ents) else None
        if ent is not None: checked = ent["checked"]
        label = f"{tag} {who or _OWNER}" + ("" if checked else " · unchecked")
        summary = f'<summary>{badge(label, "said" + ("" if checked else " unchecked"))}</summary>'
        if ent is None:
            return f'<details class="said" id="{e(_said.anchor(n))}">{summary}<div class="sbody"><span class="dim">the item holds no record of this entry</span></div></details>'
        x = self.sess_of(ent["session"]) or {}
        nm = x.get("name") or ent["session"] or "an unknown session"
        sess = self.sess_html(nm)
        when = f' · {e(self.when(ent["ts"]))}' if ent["ts"] else ""
        chk = "checked against the transcript" if checked else "unchecked" + (f": {e(ent['why'])}" if ent.get("why") else "")
        if ent["kind"] == _said.ACTED:        # a pasted result that proves a step was done, not his words
            return (f'<details class="said" id="{e(_said.anchor(n))}">{summary}<div class="sbody"><blockquote>{e(ent["quote"])}</blockquote>'
                    f'<span class="smeta">pasted in {sess}{when} · {chk} · proof of a step, not his words</span></div></details>')
        return (f'<details class="said" id="{e(_said.anchor(n))}">{summary}<div class="sbody"><blockquote>{e(ent["quote"])}</blockquote>'
                f'<span class="smeta">{e(_OWNER)} in {sess}{when} · {chk}</span></div></details>')
    HISTORY_CAP = 50
    def item_versions(self, r):
        """The item's json at every commit of the store's git that touched its file, oldest first, then the file on disk when
        it differs from the last commit (the server commits on a debounce, so the newest write may not be in git yet).
        → [(epoch seconds, dict)]: a version's time is the later of its own `updated` and `confirmed` clocks (the confirm tool
        moves `confirmed` alone), else its commit time. One `git log` and one
        `git cat-file --batch`; a store outside git, or git failing, → [] (the page then shows no history). A version that holds the old needs value (legacy_owner.py) reads it as
        `decision`, so History compares old and new versions in the same words; nothing is written."""
        d = self.data_dir; rel = os.path.relpath(r["_path"], d)
        legacy = _lo.name_from_owner(_cfg.owner())     # an old commit keeps the old needs value for good: it reads as `decision`, as the live store now holds it
        def git(*args, inp=None):
            return subprocess.run(["git", "-C", d, *args], input=inp, capture_output=True, timeout=10)
        try:
            lg = git("log", "--follow", "--name-only", "--format=%x01%H%x09%ct", "--", rel)
            if lg.returncode: return []
            commits = []
            for chunk in lg.stdout.decode("utf-8", "replace").split("\x01")[1:]:
                head, _, rest = chunk.partition("\n"); sha, _, ct = head.partition("\t")
                path = next((x.strip() for x in rest.splitlines() if x.strip()), "")      # the file's path at that commit (a rename is followed)
                if sha and path: commits.append((sha, int(ct or 0), path))
            commits.reverse(); out = []
            if commits:
                buf = git("cat-file", "--batch", inp="".join(f"{sha}:{path}\n" for sha, _c, path in commits).encode()).stdout; i = 0
                for _sha, ct, _path in commits:
                    nl = buf.find(b"\n", i)
                    if nl < 0: break
                    hdr = buf[i:nl].split(); i = nl + 1
                    if len(hdr) < 3 or hdr[1] != b"blob": continue          # "<name> missing"
                    n = int(hdr[2]); body = buf[i:i + n]; i += n + 1
                    try: v = json.loads(body)
                    except Exception: continue
                    if isinstance(v, dict): v = _lo.history_version(v, legacy); out.append((_vtime(v) or float(ct), v))
        except Exception:
            return []
        try: cur = json.load(open(r["_path"], encoding="utf-8"))
        except Exception: cur = None
        if isinstance(cur, dict): cur = _lo.history_version(cur, legacy)
        if isinstance(cur, dict) and (not out or out[-1][1] != cur):
            out.append((_vtime(cur) or os.path.getmtime(r["_path"]), cur))
        return out
    HIST_NEXT_CLIP = 160
    def hist_field(self, r, field, text, suffix=""):
        """One text field's change as a History bullet and its fold (item model section 8, the field named, never the whole field re-dumped) → (bullet html, fold html).
        next: the new text's first line, clipped to HIST_NEXT_CLIP characters (markdown as the Next list reads it), with a closed fold for the rest when there is any; ask, options,
        description: "<field> edited" and a closed fold with the new text; a field emptied: "<field> cleared". `suffix`: a bundle's " (2×, 09:00–09:01)"."""
        t = str(text or "").strip()
        if not t:
            return f"{field} cleared" + esc(suffix), ""
        if field == "next":
            lines = [ln for ln in t.splitlines() if ln.strip()]
            shown = _ip.clip_md(lines[0], self.HIST_NEXT_CLIP)
            bullet = "next: " + self.md_line(shown, r["gid"]) + esc(suffix)
            more = len(lines) > 1 or shown != _ip.clean(lines[0])
            title = "the whole next"
        else:
            bullet, more, title = f"{field} edited" + esc(suffix), True, f"the new {field}"
        fold = f'<details class="ehold"><summary class="more">{title}</summary><div class="body md">{md_block(t)}</div></details>' if more else ""
        return bullet, fold
    @staticmethod
    def hist_bullets(items):
        """[(bullet html, fold html)] → the entry's body: one line each."""
        return "".join(f'<div class="eb">{b}{f}</div>' for b, f in items)
    def item_events(self, r):
        """The item's history as (ts, kind, html) tuples, one per change, newest first (item_log without the merge, the author and the plain text); → ([(ts, kind, html)], n_more)."""
        evs, more = self.item_log(r, merge=False)
        return [(x["ts"], x["kind"], x.get("brief", x["html"]).replace('</div><div class="eb">', "; ")) for x in evs], more     # a bullet each, without the fold that holds a field's text (the migration comment, the search index)
    def item_log(self, r, merge=True):
        """The item's history as events, newest first, at most HISTORY_CAP → ([(ts, kind, html)], n_more). Always derived from the store's git by diffing
        consecutive versions (item_versions), also with the GitHub mirror on: since an earlier change the issue carries no history comments, so the issue is no
        source of it (until then, with the mirror on, the issue's comments were): created; whose move (needs); owner; due; on hold / back from hold; completed /
        reopened; priority; project; subject, next, ask and description edits; a confirm with nothing else changed. One entry per revision (the item page): its author
        (`written_by`, which every save records since step 1; an older revision names none), then everything the revision changed; a comment he wrote on GitHub is an entry of its own.
        merge=False gives one entry per change instead (item_events).
        → ([{ts, kind, html, who, what (the entry as plain text), comment (True: it belongs under Comments)}], n_more)."""
        e = esc
        def fev(field, text):          # a text field's change: its bullet and, in the 4th place, the fold with its text
            b_, f_ = self.hist_field(r, field, text); return ("edit", b_, None, f_)
        def owner(v):          # a cloud owner's name: the version's owner_name, else today's when it is the same owner
            m = v.get("metadata") or {}; o = m.get("owner") or v.get("owner") or ""
            x = self.sess_of(o, m.get("owner_name") or (r["metadata"].get("owner_name", "") if o == r["owner"] else "")) or {}
            return x.get("name") or x.get("id") or "nobody"        # the creator: the History says "created by" and nothing more of it
        def mover_of(v):       # step 4b: who moves the item in this version, as the model reads its fields ("" for a closed or a waiting item)
            try:
                mod = _model.derive(v, self.now.timestamp(), after_open=after_open)
            except Exception: return ""
            return mod.mover if mod.state == _model.ALIVE else ""
        def mover_show(w): return "no one" if not w else (w if _model.is_owner(w) else self.mover_name(w))
        def whose(v):
            if is_held(v): return "on hold"
            return "completed" if v.get("status") == "completed" else WHOSE[needs_kind({"metadata": v.get("metadata") or {}})]
        def due(v): return due_of({"metadata": v.get("metadata") or {}})
        def proj(v):
            k = proj_key({"metadata": v.get("metadata") or {}})
            return self.proj_label(k) if k in self.proj else (k or "no project")
        out = []
        vs = self.item_versions(r); prev = None
        for vi, (ts, v) in enumerate(vs):
            m = v.get("metadata") or {}; ev = []
            if prev is None:
                ev.append(("created", f"created as “{e(v.get('subject') or '')}” · {e(whose(v))} · " + (f"mover {e(mover_show(mover_of(v)))} · " if mover_of(v) else "") + f"created by {e(owner(v))}"   # the subject it was born with
                           + "".join(" " + self.said_tag(r, n, x["tag"], "", x["checked"]) for n, x in _said.new_entries(None, m))))   # his words the first version already held
                rl = _gh.refile_line(None, m)          # "Refile itself": filed under another project, moved to the owner's
                if rl: ev.append(("project", e(rl)))
            else:
                pm = prev.get("metadata") or {}
                ps, s_ = str(prev.get("status") or "open"), str(v.get("status") or "open")
                ph, h_ = is_held(prev), is_held(v)          # a hold is a property of an open item (legacy versions: status on_hold), not a status
                if ps != s_ or ph != h_:
                    if s_ == "completed":
                        oc, why, by = outcome_of(v)   # an item closed before then says only "completed"
                        ev.append(("completed", "completed" + (f" · <b>{e(outcome_word(oc))}</b>" if oc else "") + (f" by {e(shown(by))}" if by else "") + (f" — {e(why)}" if why else "")))
                    elif h_ and not ph:
                        w = wake_of(v); ev.append(("hold", "put on hold" + (f" · wake {e(self.when(w))}" if w else "")))
                    elif ph and not h_: ev.append(("unhold", f"back from hold · {e(whose(v))}"))
                    elif ps == "completed": ev.append(("reopened", f"reopened · {e(whose(v))}"))
                if not h_ and not ph and s_ != "completed" and ps == s_:
                    a, b = needs_kind({"metadata": pm}), needs_kind({"metadata": m})
                    if a != b:
                        po = options_of(prev) if a == "call" else []    # the options leave the page with the decision and stay here
                        pk = ask_of(prev) if a == "call" else ""        # and so does the ask, its Decide part (the raw line if misshaped)
                        pk = ((parse_ask(pk) or {}).get("decide") or pk) if pk else ""
                        ev.append(("needs", f"whose move: {e(WHOSE[a])} → <b>{e(WHOSE[b])}</b>"))
                        if pk: ev.append(("needs", f"the ask was: {e(_ip.clip(pk, 160))}", None, f'<details class="ehold"><summary class="more">the whole ask</summary><div class="body md">{md_block(ask_of(prev))}</div></details>'))
                        if po: ev.append(("needs", "the options were: " + "; ".join(f'{e(_ol.listed(o["label"], i))}{" (recommended)" if o["recommended"] else ""}' for i, o in enumerate(po))))
                    elif [shown_ref(x) for x in needs_sessions({"metadata": pm})] != [shown_ref(x) for x in needs_sessions({"metadata": m})]:   # the sessions named changed, the lane not
                        ns = [shown_ref(x) for x in needs_sessions({"metadata": m})]; ev.append(("needs", "needs: <b>" + e(", ".join(ns)) + "</b>" if ns else "needs: no session named any more"))
                elif is_held(v) and is_held(prev) and wait_date_of(prev) != wait_date_of(v):
                    w = wait_date_of(v); ev.append(("hold", f"wake {'set to ' + e(self.when(w)) if w else 'cleared'}"))
                if not h_ and not ph and s_ != "completed" and ps == s_ and wait_date_of(prev) != wait_date_of(v):   # a date that is no wait (a backstop): set, moved or gone
                    w = wait_date_of(v); ev.append(("hold", f"backstop {'set to ' + e(self.when(w)) if w else 'cleared'}"))
                if s_ != "completed" and after_of({"metadata": pm}) != after_of({"metadata": m}):   # what it waits on
                    af = after_of({"metadata": m}); ev.append(("hold", "after: <b>" + e(", ".join(shown(g) for g in af)) + "</b>" if af else "after cleared: nothing left to wait on"))
                if s_ != "completed" and (pm.get("state") != m.get("state") or any(pm.get(k) != m.get(k) for k in _states.CARRY_FIELDS)):   # where it stands, with what the state carries
                    ev.append(("hold", (f"state {e(pm['state'])} → <b>{e(m['state'])}</b>" if pm.get("state") in (*_states.STATES, *_states.LEGACY_STATES) and pm.get("state") != m.get("state") else f"state <b>{e(m['state'])}</b>") + "".join(f" · {k}: {e(_ip.clip(m[k], 300))}" for k in _states.CARRY.get(m["state"], ()) if m.get(k)) if m.get("state") in _states.STATES
                               else f"state cleared (was {e(pm.get('state'))})"))
                if s_ != "completed" and (pm.get("draft") or "") != (m.get("draft") or ""):   # the draft's own line its text is on the item
                    ev.append(("edit", "draft cleared" if not m.get("draft") else "draft edited" if pm.get("draft") else "draft set"))
                if s_ != "completed" and pm.get("rank") != m.get("rank"):   # the builder's queue order
                    ev.append(("hold", f"rank set to <b>{e(m['rank'])}</b>" if m.get("rank") else f"rank cleared (was {e(pm.get('rank'))})"))
                if s_ != "completed":                       # a step the stall pass took (its mover's pane had no turn running), one line each, said by stackshot
                    for x in _stall.new_entries(pm, m): ev.append(("stall", "stackshot: " + e(x["text"])))
                    for x in _hlog.new_entries(pm, m): ev.append(("stall", "stackshot: " + e(x["text"])))      # the hourly audit line (audit/hourly.py), its own log
                if s_ != "completed":                       # a front agent's notice about the item (told on his next turn, or not told), the board keeps the news either way
                    for x in _quiet.new_entries(pm, m): ev.append(("front", "stackshot: " + e(x["text"])))
                if s_ != "completed" and ps == "open":      # a mover change, in the model's words; a close or a reopening says its own line
                    mv_a, mv_b = mover_of(prev), mover_of(v)
                    if mv_a and mv_b and mv_a != mv_b and not same_ref(mv_a, mv_b):      # a hold or a wait takes the mover away: its own line says that
                        ev.append(("mover", f"mover: {e(mover_show(mv_a))} → <b>{e(mover_show(mv_b))}</b>"))
                ho_ = _hov.fresh(pm, m) if s_ != "completed" else {}       # a finished step handed the item on, or could not: its own line (handover.py)
                if ho_:
                    ev.append(("mover", f"step hand-over: item moved{(' from ' + e(mover_show(mover_of(prev)))) if mover_of(prev) else ''} to <b>{e(mover_show(mover_of(v)))}</b>" if ho_.get("kind") == _hov.MOVED
                               else f"step hand-over: the next step is {e(self.mover_name(ho_.get('to') or ''))}'s but that session isn't running; it stays with <b>{e(mover_show(mover_of(v)) if mover_of(v) != 'no one' else 'its mover')}</b>"))
                a, b = due(prev), due(v)
                if a != b:
                    ev.append(("due", f"due set to <b>{e(self.when(b))}</b>" if not a else f"due cleared (was {e(self.when(a))})" if not b
                               else f"due moved: {e(self.when(a))} → <b>{e(self.when(b))}</b>"))
                if (pm.get("priority") or "p2") != (m.get("priority") or "p2"): ev.append(("priority", f"priority: {e(pm.get('priority') or 'p2')} → <b>{e(m.get('priority') or 'p2')}</b>"))
                if proj_key({"metadata": pm}) != proj_key({"metadata": m}):
                    rl = _gh.refile_line(pm, m)        # "Refile itself": the server moved it to its owner's project
                    ev.append(("project", e(rl) if rl else f"project: {e(proj(prev))} → <b>{e(proj(v))}</b>"))
                if prev.get("subject") != v.get("subject"): ev.append(("edit", f"subject edited (was “{e(prev.get('subject') or '')}”)"))
                for word, line in _steps.changes(pm, m, s_ == "completed"):     # a step checked or dropped, one line each
                    ev.append(("step", f"step {word}: " + self.md_line(_ip.clip_md(line, self.HIST_NEXT_CLIP), r["gid"])))
                if (pm.get("next") or "") != (m.get("next") or ""): ev.append(fev("next", m.get("next")))
                pa, a_ = str(pm.get("ask") or "").strip(), str(m.get("ask") or "").strip()
                if pa != a_: ev.append(fev("ask", a_))
                if (pm.get("options") or []) != (m.get("options") or []): ev.append(fev("options", _gh._options_text(m.get("options"))))
                if (prev.get("description") or "") != (v.get("description") or ""): ev.append(fev("description", v.get("description")))
                pa_, na_ = answers_of(prev), answers_of(v)
                if len(na_) > len(pa_) and na_[:len(pa_)] == pa_:        # phase 3: his answer from the board, one line each
                    for a in na_[len(pa_):]:
                        ch, tx = str(a.get("choice") or ""), str(a.get("text") or "")
                        ev.append(("answer", f"{e(_OWNER)} ({e(a.get('via') or 'board')}): " + (f"<b>{e(ch)}</b>" if ch else "") + (" — " if ch and tx else "")
                                   + e(tx) + (' <span class="dim">· comment</span>' if a.get("kind") == "comment" else ' <span class="dim">· note on his step</span>' if a.get("kind") == "step-reply" else "")))
                for w in _work.legacy_changes(pm, m): ev.append(("work", e(w)))   # a line of the old work list added, moved or removed (a step status is folded under its step in the page, not a line each here)
                new_said = _said.new_entries(pm, m)                          # the trailers: his words recorded by this version, a tag each
                if new_said: ev.append(("said", e(_said.recorded_words([x for _n, x in new_said])) + "".join(" " + self.said_tag(r, n, x["tag"], "", x["checked"]) for n, x in new_said)))
                if (prev.get("confirmed") != v.get("confirmed") and v.get("confirmed")
                        and {k_: ({kk: vv for kk, vv in x.items() if kk not in ("phase", "waits_on", "project_id", "last_activity")} if k_ == "metadata" and isinstance(x, dict) else x) for k_, x in prev.items() if k_ not in ("confirmed", "activity")} == {k_: ({kk: vv for kk, vv in x.items() if kk not in ("phase", "waits_on", "project_id", "last_activity")} if k_ == "metadata" and isinstance(x, dict) else x) for k_, x in v.items() if k_ not in ("confirmed", "activity")}):      # `activity` is a clock too (activity.py): seeding it is no change to the item, and neither are the stored phase and the kind of its wait that every save of an open item writes (metadata.phase, metadata.waits_on), nor the last-activity record the hub's event pass stamps (metadata.last_activity)
                    ev.append(("confirm", "confirmed"))   # the confirm tool: confirmed changed alone
                pa_ = answers_of(prev)
                for a in answers_of(v)[len(pa_):]:      # phase 3: the owner's comment written on GitHub, at the comment's own time
                    if a.get("via") == "github":
                        u, t = str(a.get("url") or ""), re.sub(r"\s+", " ", str(a.get("text") or "")).strip()
                        t = t if len(t) <= 160 else t[:159].rstrip() + "…"
                        where = f'<a href="{e(u)}" target="_blank" rel="noopener">on GitHub</a>' if u else "on GitHub"
                        try: at = float(a.get("ts") or 0) or None
                        except (TypeError, ValueError): at = None
                        ev.append(("comment", f"{e(_OWNER)} commented {where}: “{e(t)}”", at))
            who = " ".join(str(v.get("written_by") or "").split())          # the revision's author (model.py: every save records it); older revisions carry none
            chg = [x for x in ev if x[0] != "comment"]
            if not merge:                                                    # one entry per change, as before (item_events)
                out += [(vi, j, {"ts": (x[2] if len(x) > 2 and x[2] else ts), "kind": x[0], "html": x[1], "who": who, "what": _ip.plain(x[1]), "comment": x[0] == "comment"}) for j, x in enumerate(ev)]
            else:
                if chg:                                                      # one entry per revision: its author and time on the header line, one bullet per change (a text field's text in a fold)
                    h = self.hist_bullets([(x[1], x[3] if len(x) > 3 else "") for x in chg])
                    out.append((vi, 0, {"ts": ts, "kind": next((k_ for k_ in ("completed", "reopened", "answer", "created", "said") if any(x[0] == k_ for x in chg)), chg[0][0]), "html": h, "who": who, "what": "; ".join(_ip.plain(x[1]) for x in chg), "comment": False}))
                for j, x in enumerate(c for c in ev if c[0] == "comment"):   # his comment written on GitHub: its own line, at the comment's own time
                    out.append((vi, j + 1, {"ts": (x[2] if len(x) > 2 and x[2] else ts), "kind": "comment", "html": self.hist_bullets([(x[1], "")]), "who": _OWNER, "what": _ip.plain(x[1]), "comment": True}))
            prev = v
        out.sort(key=lambda x: (-x[0], x[1]))
        return [x for _vi, _j, x in out[:self.HISTORY_CAP]], max(len(out) - self.HISTORY_CAP, 0)
    _SENT = {"decision": ("ok", "Sent: your answer is on the item, it has left your queue, and the agent on it has been told."),
             "comment": ("ok", "Sent: your comment is on the item and the agent on it has been told."),
             "empty": ("warn", "Nothing sent: write something in the box, or pick an option."),
             "emptynote": ("warn", "Nothing sent: write a note to send it."),
             "toolong": ("warn", "Nothing sent: the text is too long."),
             "stale": ("warn", "Nothing sent: the item no longer asks this (its options or its needs changed). Read it again below.",
                       "Nothing sent: the ask changed before your answer arrived; open the item to read it again."),
             "askedback": ("warn", "Sent: your note is on the item. I could not read a date from it, so the question is back below with days to pick from. Pick one, or write a date in the box.",
                           "Sent: your note is on the item. I could not read a date from it; open the item to pick a day."),
             "stalenote": ("ok", "Sent as a comment: the item no longer asks this, so your note is on it as a comment. Read the item again below.",
                           "Sent as a comment: the ask changed before your answer arrived, so your note is on the item as a comment; open the item to read it again."),
             "closednote": ("ok", "Sent as a comment: the item is closed, and your note is on it."),
             "closed": ("warn", "Nothing sent: the item is closed."),
             "done": ("ok", "Done: the item goes on to its next mover."),
             "donenote": ("ok", "Done: the item goes on to its next mover, and your note went along."),
             "stepreply": ("ok", "Sent: your note is on the item and its next mover has it. It decides whether the step is done, and hands the item back to you if it was a question."),      # the item page names who: sent_html(taken_by=)
             "nomover": ("warn", "Nobody is set to take this item next, so nothing was recorded. Write a comment instead."),
             "nostep": ("warn", "Nothing sent: the item has no step for you any more. Read it again below.",
                        "Nothing sent: the item has no step for you any more; open the item to read it again.")}


    # ---------------- the emitters ----------------
    def render(self, modes) -> dict:
        """{mode: text} for the modes asked: brief · full (markdown)."""
        out = {}
        if "brief" in modes: out["brief"] = self.brief()
        if "full" in modes: out["full"] = self.markdown()
        return out

    def base_mod(self, r):
        """The item as the model reads it before the queue rule (model.derive, then model.view: a doing item whose wake is far out with every step dated reads as waiting), once per row."""
        m = r.get("_base")
        if m is None:
            m = r["_base"] = _model.view(r, _model.derive(r, self.now.timestamp(), after_open=after_open, anchored=lambda it: str(it["gid"]) in self.scoped_urls()), self.now.timestamp(), after_open)
        return m

    def queue_map(self):
        """{item: the item it is queued behind} over the board's open rows (queued.board_queue: a mover busy on another item, `[model] queued_behind`), {} while the rule is off; read once per Board."""
        if getattr(self, "_queue", None) is None:
            self._queue = _queued.board_queue(self.rows, self.base_mod, self.now.timestamp(), _home.front_test())
        return self._queue

    def mod_of(self, r):
        """The item as the board shows it (base_mod, then the queue rule: an item behind its mover's other item reads waiting, queued behind it), once per row: the reading the home page's lists, the item page and board.md share."""
        m = r.get("_mod")
        if m is None:
            m = r["_mod"] = _queued.overlay(self.base_mod(r), self.queue_map().get(str(r.get("gid") or ""), ""))
        return m

    def scoped_urls(self, gid=None):
        """The anchors scoped to items, from every project's page in the anchors file (anchor_scope.scoped_map, the same rule the server reads): {item id: [url, ...]} in the order they were added;
        with a gid, that item's list. An `outside` item with one is an anchor wait, else a relay (the model's `anchored`)."""
        if getattr(self, "_scoped", None) is None:
            self._scoped = _ascope.scoped_map(self.anchors)
        return self._scoped if gid is None else self._scoped.get(str(gid), [])

    def home_pairs(self, rows=None):
        """The open rows in the home page's three lists, sorted as the home page sorts them: {your-move, agents, waiting} -> [(row, model)] (home.classify, home.sort_*). The one classification: the home page, board.md and the brief count and list from it."""
        rows = [r for r in (self.rows if rows is None else rows) if r.get("status") != "completed"]
        lists = _home.classify(rows, self.mod_of)
        return {_home.YOUR_MOVE: _home.sort_your_move(lists[_home.YOUR_MOVE], sort_key, same_ref),
                _home.AGENTS: _home.sort_agents(lists[_home.AGENTS], sort_key, same_ref),
                _home.WAITING: _home.sort_waiting(lists[_home.WAITING], sort_key)}

    def phase_counts(self):
        """The counts board.md's head and the brief draw: {open, your_move, agents, alive, waiting}, from home_pairs. Every open item is alive or waiting; an alive item is the owner's move or an agent's (agents includes the home page's Queued for release),
        so open = your_move + agents + waiting, alive = your_move + agents."""
        p = self.home_pairs()
        ym, ag, wt = (len(p[k]) for k in (_home.YOUR_MOVE, _home.AGENTS, _home.WAITING))
        return {"open": ym + ag + wt, "your_move": ym, "agents": ag, "alive": ym + ag, "waiting": wt}

    def brief(self) -> str:
        """The few lines a session sees at start."""
        if not self.rows: return "Board: empty.\n"
        T = self.phase_counts(); pairs = self.home_pairs()
        n_basis = sum(1 for r in self.agent if _dw.basis_wait(r, self.now.timestamp(), after_open) is not None)    # the items the board lists as waiting for a wake that states its reason
        stale = sum(1 for r in self.needs + self.agent + self.held if r.get("_fresh") == "stale")   # every open item; a parked one is held and never stale
        lines = [f"Board: {T['open']} open ({T['your_move']} your move, {T['agents']} on agents, {T['waiting']} waiting), {len(self.done)} completed in 14d"
                 + (f" · {stale} stale" if stale else "")
                 + (f" · {len(self.undelivered)} with an undelivered notice" if self.undelivered else "") + "."]
        lines += _wc.lines()                      # step 4b: what changed in the tools in the last 7 days (whatschanged.py)
        lines += [f"  your move: {rid_full(r)} {r['subject']} [{self.lab(r)}]" for r, _m in pairs[_home.YOUR_MOVE][:5]]
        lines += [f"  waiting: {rid_full(r)} {r['subject']} [{self.lab(r)}]{' · ' + _home.wait_phrase(m_, 'on', shown_full) if _home.wait_phrase(m_, 'on', shown_full) else ''}" for r, m_ in pairs[_home.WAITING][:5]]
        nh = new_holds(self.held, self.now)       # the holds set in the last 24 hours, with their reason
        lines += [f"  new hold (24 h): {rid_full(r)} {r['subject']} [{self.lab(r)}] · {self.new_hold_words(r)}" for r in nh[:8]]
        if len(nh) > 8: lines.append(f"  … and {len(nh) - 8} more new holds")
        if T["open"]:
            lines.append(f"  alive {T['alive']} (your move {T['your_move']}, agents {T['agents']}) · waiting {T['waiting']}")
            # held doing items that wait for their wake (dated_wait.held_wait) and doing items whose wake stands on a wait_basis (dated_wait.basis_wait) are left out on purpose: the line's advice (park it, or write the step that can run now) does not apply to an item already on hold
            ndated = sum(1 for r in self.needs + self.agent + self.held if _dw.of(r, self.now.timestamp()) is not None and _dw.basis_wait(r, self.now.timestamp(), after_open) is None)      # the other way a stored doing item reads as waiting: every open step is dated for a later day (dated_wait.py)
            if n_basis: lines.append(f"  {n_basis} of the doing items have a wake that states its reason (wait_basis): the board lists them as waiting until the wake, whatever the stored state says")
            if ndated: lines.append(f"  {ndated} of the doing items have a wake more than {_wt.dated_wait_min_hours():g} h out and every open step dated for a later day: the board lists them as waiting; park each (update hold=true, until=...) or write the step that can run now")
        if self.basis_waits and self.basis_due():     # the weekly list: long waits that stand on a real-world date, for a person to look at
            lines += [f"  waits on a real-world date: {rid_full(r)} {r['subject']} [wake {self.when(wake_of(r))} · {_wt.basis_of(r['metadata'])}]" for r in self.basis_waits[:8]]
            if len(self.basis_waits) > 8: lines.append(f"  and {len(self.basis_waits) - 8} more waits on a real-world date (the board's head lists them)")
        return "\n".join(lines) + "\n"

    def markdown(self) -> str:
        """The board as markdown (board.md in git)."""
        now, TITLE, PUB, FLEET, PKG_ORDER, SCOPES = self.now, self.title, self.pub, self.fleet, self.pkg_order, self.scopes
        n_open, n_call, n_relay, agent, done, by_proj = self.n_open, self.n_call, self.n_relay, self.agent, self.done, self.by_proj
        url, lab, proj_state, proj_title, proj_scope, proj_mirror = self.url, self.lab, self.proj_state, self.proj_title, self.proj_scope, self.proj_mirror
        lines, proj_anchor_groups = self.lines, self.proj_anchor_groups
        def m_sref(r):
            u = url(r); l = lab(r)
            if not l: return ""     # a closed item with no session names no one
            return f"`{l}` · [open](<{u}>)" if u else f"`{l}`"
        def m_ids(xs, per=4, held=()):
            links = ([f"[{rid_full(r)}](#{anchor(r)})" for r in sorted(xs, key=lambda r: (r["L"], num(r)))]
                     + [f"[{rid_full(r)}](#{anchor(r)}) ({'on hold' if is_held(r) else self.after_words(r)})" for r in sorted(held, key=lambda r: (wake_key(r), r["L"], num(r)))])   # parked: after the active ones
            return "<br>".join(", ".join(links[i:i+per]) for i in range(0, len(links), per)) or "—"
        def m_item(r):
            m = r["metadata"]; out = [f"<a id=\"{anchor(r)}\"></a>**{rid_full(r)} · {r['subject']}**" + (f" ({self.md_hold(r)})" if is_parked(r) else "")]
            k = "" if is_parked(r) else needs_kind(r)   # parked: its needs field waits with it
            meta = ([f"**Due in {(due_of(r) - now.date()).days} d ({due_of(r):%m-%d %a})**"] if due_of(r) else []) + [m.get("priority") or "p2"]
            if _home.wait_phrase(self.mod_of(r), "waiting on", shown_full): meta.append(_home.wait_phrase(self.mod_of(r), "waiting on", shown_full))      # the kind of its wait, in the model's words
            if r.get("_fresh") == "stale": meta.append("stale")                       # before the ask, whose own " · " would swallow it
            if k == "call" and open_ask(r): meta.append("ask: " + open_ask(r))
            out.append("- " + " · ".join(meta))
            if k == "call" and options_of(r):        # the options under the ask, the recommended one marked
                out.append("- options:\n" + "\n".join(f'  - **{_ol.listed(o["label"], i)}**{" (recommended)" if o["recommended"] else ""}: {m_link(o["line"])}' for i, o in enumerate(options_of(r))))
            out.append("- mover: " + m_sref(r))      # step 4b: board.md names the mover
            if needs_sessions(r): out.append("- needs: " + ", ".join(f"`{shown_ref(s)}`" for s in needs_sessions(r)))   # the sessions whose move it is
            if after_of(r): out.append("- after: " + ", ".join(f"[{shown_full(g)}](#task-{g[0]}-{g[1:]})" + ("" if g in after_open(r) else " (closed)") for g in after_of(r)))
            if observers_of(r): out.append("- observers: " + ", ".join(f"`{shown_ref(s)}`" for s in observers_of(r)))
            if r.get("status") != "completed" and _work.lines_of(m): out.append("- step status: " + _work.words(m))   # what is in motion on it
            pk, pinfo = proj_state(r)
            tk = proj_top(r) or pk                         # the project it shows is the top-level one; the link stays the page the item is filed on (its own page's mirror, else the project's)
            pinfo = pinfo or (self.proj.get(tk) if tk else None)
            if pinfo: out.append(f"- project: [{tk}]({pinfo['mirror']})" if pinfo.get("mirror") else f"- project: `{tk}`")   # no mirror configured: no link
            elif tk: out.append(f"- project: `{tk}`" + (f" · `{pk}`" if pk and pk != tk else "") + " (page missing)")      # the flag follows the page that is missing, the one the item is filed on
            else: out.append("- project: _none_")
            if m.get("next"):
                parts = next_steps(m["next"])
                if len(parts) == 1: out.append("- next: " + m_link(parts[0][1]))
                else:
                    lines, n = [], 0
                    for lvl, x in parts:
                        if lvl == 0: n += 1; lines.append(f"  {n}. {m_link(x)}")
                        else: lines.append(f"     - {m_link(x)}")
                    out.append("- next:\n" + "\n".join(lines))
            desc = (r.get("description") or "").strip()
            if desc and desc != r["subject"]:
                out.extend(("  - " if lvl else "- ") + m_link(x) for lvl, x in sentences(desc))
            return "\n".join(out)
        def m_section(title, items, empty, lead=""):
            print(); print(f"## {title}"); print()
            if lead: print(lead); print()
            print("\n\n".join(m_item(r) for r in items) if items else empty)
        lists = self.home_pairs(); lk = {r["gid"]: w for w, ps in lists.items() for r, _m in ps}      # the home page's three lists: the sections, and the project table's cells
        _rc = self.recycle      # the pane-recycle status line, under the Machines table, only while an item waits for one (recycle_due).
        # Informational since the fleet tool runs a flagged recycle itself (a flagged recycle needs no one
        # to act on it), so it is no longer at the top of the waiting part
        rc_line = (f"Pane recycle pending for {', '.join(f'[{rid_full(r)}](#{anchor(r)})' for r in _rc)} ({_cfg.fleet_tool() or 'the fleet tool'} runs it)") if _rc else ""
        pv_line = (f"Provision needed for {', '.join(h + ('' if on else ' (offline)') for h, on in self.provision)}") if self.provision else ""   
        _b = io.StringIO()
        with contextlib.redirect_stdout(_b):
            print(f"# {TITLE}"); print()
            _v = self.versions
            _cc = next((x for x in _v if isinstance(x.get("machines"), dict)), {})   # the per-machine package (the CLI): its version lives on each machine
            _cols = [PUB] + sorted(x for x in FLEET if x != PUB)
            def _mver(L):
                v = (_cc.get("machines") or {}).get(L)
                if not v: return L
                ms = str((_cc.get("machine_state") or {}).get(L, "")); off = ms.startswith("offline")
                return f"{L} {v}" + (" ↑" if cli_behind(v, _cc.get("latest")) else "") + (" (offline)" if off else "")
            _T = self.phase_counts()
            print(f"_{_T['open']} open · {_T['your_move']} your move · {_T['agents']} on agents · {_T['waiting']} waiting · machines: {' · '.join(_mver(L) for L in _cols + ['c'])} · rendered by stackshot_"); print()
            _pk = {x.get("name"): x for x in _v}
            def _cell(name, L):
                v = _pk.get(name) or {}
                if isinstance(v.get("machines"), dict):
                    inst = (v.get("machines") or {}).get(L)
                    if not inst: return "—"
                    off = str((v.get("machine_state") or {}).get(L, "")).startswith("offline")
                    return inst + (" (offline)" if off else f" → **{v.get('latest')}**" if cli_behind(inst, v.get("latest")) else "")
                if L != PUB or not v: return "—"
                return v.get("installed", "") + (f" → **{v.get('latest')} update available**" if v.get("state") == "update" else " (latest)" if v.get("state") == "latest" else "")
            if self.undelivered:    # notices nobody got
                print("## Undelivered notices"); print()
                print(f"- Undelivered notices: {', '.join(f'[{rid_full(r)}](#{anchor(r)})' for r in self.undelivered)}")
                print()
            if self.basis_waits and self.basis_due():     # once a week: the waits the 7-day cap lets stand on a real-world date, for a person to read the dates
                print("## Waits on a real-world date (weekly)"); print()
                print("These waits run past the cap on a date outside the board, which the session that parked each one gave. Check that the date still holds.")
                print()
                for r in self.basis_waits:
                    wb = r["metadata"].get("wait_basis") or {}
                    print(f"- [{rid_full(r)}](#{anchor(r)}) · {r['subject']} — wake {self.when(wake_of(r))} · {_wt.basis_of(r['metadata'])} · set by {wb.get('by') or 'unknown'}")
                print()
            print("## Machines"); print(); print("| package | " + " | ".join(_cols) + " |"); print("|---|" + "---|" * len(_cols))
            for name in PKG_ORDER: print(f"| {name} | " + " | ".join(_cell(name, L) for L in _cols) + " |")
            print()
            if rc_line: print(rc_line); print()
            _rcv = self.hub_status.get("receivers") or {}
            if _rcv:
                print("## Anchor hub"); print(); print("| receiver | state |"); print("|---|---|")   # no check stamp here: it moves every minute and made every timer publish a commit
                for k, v in _rcv.items(): print(f"| {k} | {'healthy' if v.get('ok') else 'DOWN: ' + str(v.get('error') or '')} |")
                print()
            _newh = new_holds(self.held, now)    # the morning briefing's data: the holds set in the last 24 hours and why; left out when none
            if _newh:
                print("## New holds (last 24 hours)"); print()
                for r in _newh: print(f"- [{rid_full(r)}](#{anchor(r)}) · {self.mover_word()} `{self.lab(r)}` · {self.new_hold_words(r)}")
                print()
            print("Shared by every Claude session on every machine. Items are human-level: deliverables, decisions, blockers, handoffs. Ask any session to add, complete or reprioritise; every write publishes at once.")
            print(); print("## Task board"); print()
            for sc in SCOPES:
                ks = [k for k in sorted(by_proj, key=lambda k: (k == "", proj_title(k).lower())) if proj_scope(k) == sc]
                if not ks: continue
                print(f"### {sc}"); print()
                print("| project | agents | watch | open | your move | on agents | waiting |"); print("|---|---|---|---|---|---|---|")
                for k in ks:
                    rs = by_proj[k]; u = proj_mirror(k); t = proj_title(k)
                    pl = f"[{t}]({u})" if u else (t if k else "_no project_")
                    ref = lambda l, u: f"`{l}` · [open](<{u}>)" if u else f"`{l}`"
                    _w = self.watch(k); ach = self.WATCH[_w[0]][0] if _w else ""      # the watch column as a word: ok · waiting · broken · —
                    for i, (l, lu, short, is_agent, lrs, flag, _tip) in enumerate(lines(k, rs)):      # the keeper's line carries the project, its anchors and the total
                        sess = ("" if short or not is_agent else "+ ") + ref(short or l, lu) + (f" ({flag})" if flag else "")
                        head = f"| {pl} | {sess} | {ach or '—'} | {len(rs)} |" if i == 0 else f"|  | {sess} |  |  |"
                        cell = lambda w: m_ids([r for r in lrs if lk.get(r["gid"]) == w and not is_parked(r)], held=[r for r in lrs if lk.get(r["gid"]) == w and is_parked(r)])
                        print(f"{head} {cell(_home.YOUR_MOVE)} | {cell(_home.AGENTS)} | {cell(_home.WAITING)} |")
                print()
            m_section("Your move", [r for r, _m in lists[_home.YOUR_MOVE]], "_nothing waits on you_", lead=pv_line)
            m_section("Waiting", [r for r, _m in lists[_home.WAITING]], "_nothing is waiting_")
            m_section("On agents", [r for r, _m in lists[_home.AGENTS]], "_no agent has an open item_")
            print(); print("## Completed (last 14 days)"); print()
            if done:
                for r in done:
                    oc, why, by = outcome_of(r)   # how it ended
                    print(f"- <a id=\"{anchor(r)}\"></a>**{rid_full(r)}** {r['subject']}" + (f" · **{outcome_word(oc)}**" + (f" by {shown_full(by)}" if by else "") + (f": {why}" if why else "") if oc else "")
                          + (f" · {m_sref(r)}" if lab(r) else "") + f" · {r['_updated']:%m-%d %H:%M} {_cfg.tz_abbr(r['_updated'])}")
            else: print("_none_")
        return _b.getvalue()


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.stdout.write(render(a[0], a[1] if len(a) > 1 else "full"))
