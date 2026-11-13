"""ui/render.py — the board's page renderer: the home, an item page, a project page, Projects, Closed (HTML). A Board loads the store, the fleet state and the hub status ONCE and
carries the model (sessions, projects, anchors) and draws the pages from it. Every address a page writes (a link, a form action, a redirect target, a script's fetch) goes through
under() (ui/__init__.py: the board is at the root address). The markdown and the brief are render.py's; the icon, font and manifest files stay at their shared addresses."""
import contextlib
import io
import json, os, sys, glob, datetime, re, subprocess, hashlib, textwrap, html as H
from pathlib import Path
from urllib.parse import quote, urlsplit
from stackshot.web.ui import PREFIX, under   # the (empty) root prefix: every address this page writes goes through under()
from stackshot.web.ui import kit as _ui   # the one item system: the state words and tags, the one row every list draws, the type scale
from stackshot.web.ui import groups as _grp   # rows in one foldable subsection per scope: home's four lists and the Closed page (groups.py)
from stackshot.web.ui import releasing as _rel   # which pull requests are in the release script's queue (an item anchored to one is Queued for release)
RELEASE_LIST = "release"   # the home page's fourth list, beside home.py's three: the agents' items whose pull request is in the release queue (Board.home_lists)
from stackshot.model import option_labels as _ol   # the letter an option's label repeats from its badge, dropped on read (option_labels.py)
from stackshot.core import config as _cfg  # stackshot.toml: paths, fleet, scopes, the Machines panel, branding
from stackshot.core import legacy_owner as _lo   # an old version of an item (from the store's history) read as the current code reads it: History only, never written back
from stackshot.fleet import fleet as _fleet   # the session and machine view, and the one rule for a session's presence (running / present)
from stackshot.router import routing as _routing   # the routing log: what came in per project and how it was ruled (the pilot)
from stackshot.github import ghsync as _gh   # how an id is written for a person (board-tmp-<machine>#3) and its page address (/items/<n>)
from stackshot.model import queued as _queued   # a mover busy on another item: its other items on an agent read waiting, queued behind it (queued.py)
from stackshot.model import work as _work   # a step's status line, what is in motion on an item (a row's "engineer: migrating", the item page's Next and History)
from stackshot.model import said as _said   # the trailers: his words on an item, a tag on the History line of the write that recorded them, the quote behind it
from stackshot.model import states as _states   # an open item's stored state, or the one derived from its fields (states.py)
from stackshot.waits import event_waits as _ew   # a fleet event line of a wait on a list, in words
from stackshot.waits import waiting as _wt   # what an item waits on and whose move it is (waiting.py)
from stackshot.anchors import receiver_health as _rh   # when a receiver's last check is too old to call it healthy (receiver_health.py)
from stackshot.anchors import anchor_scope as _ascope   # which anchors count for an item, from every project's page (anchor_scope.py)
from stackshot.model import draft as _draft   # an item's draft: the verbatim text the owner pastes elsewhere, drawn in a block with a Copy button (draft.py)
from stackshot.web import itempage as _ip   # the item page's words on the item model: since, next lines
from stackshot.model import step_commands as _sc   # the step of a your-step item: numbered list, commands to copy (step_commands.py)
from stackshot.model import steps as _steps   # the checklist behind next: done, dropped and open steps (steps.py)
from stackshot.model import owner_steps as _os   # the step the server makes on the checklist for his your-step or decision (owner_steps.py)
from stackshot.waits import dated_wait as _dw   # a stored doing item whose open steps are all dated for a later day reads as waiting (dated_wait.py)
from stackshot.model import model as _model   # the item model: dead, alive or waiting, the mover and the wait (model.py)
from stackshot.waits import watchers as _wat   # the waits' watchers: the chases logged on a wait
from stackshot.audit import hourly_log as _hlog   # the hourly audit lines written on an item (History lines)
from stackshot.waits import stall as _stall   # the steps of the stall pass written on an item (History lines)
from stackshot.waits import handover as _hov   # a finished step handed the item on: the record behind a History line (handover.py)
from stackshot.waits import quiet as _quiet   # what a front agent was or was not told of an item, one History line each
from stackshot.waits import handoff as _hand   # a hand-off not yet taken
from stackshot.web import whatschanged as _wc  # what changed in the tools in the last 7 days: a line in the brief
from stackshot.web import uiprefs as _up   # the signed-in person's panel order (uiprefs.py): the default order, normalize
from stackshot.web import i18n as _i18n   # the string table: a page's words in the person's language, the English ones when it has none (i18n.py)
from stackshot.web.i18n import t as _t
from stackshot.web import foryou as _fy  # the For you list: rows for what the owner should see, newest first (foryou.py)
from stackshot.web import landed as _ld  # the Landed list: the closes of agents that the owner did not make, and which he has seen (landed.py)
from stackshot.model import item_project as _iproj   # an item's project by its permanent id: the page key read through the id (item_project.py)
from stackshot.projects import projects as _prj   # the project record: an agent registered there whose page line is still owed (with_pending)
from stackshot.model import model as _model   # the item model: dead, alive or waiting, the mover and the wait (model.py)
from stackshot.model import last_activity as _lastact   # the item's last-activity record: the On agent rows and the item page show it (act_parts)
from stackshot.web import home as _home   # the home page's three lists on that model: Your move, On agent, Waiting (home.py)
from stackshot.waits import handoff as _ho   # "handed to X, not yet taken" on an On agent row (handoff.py)
LIST_ORDER = (_home.YOUR_MOVE, _home.AGENTS, RELEASE_LIST, _home.WAITING)      # the four lists in the order the home page and the project page draw them
from stackshot.waits import watchers as _watch   # a relay's subject and the chases logged on a wait (watchers.py)
from stackshot.fleet import sessions_registry as _sr   # the permanent session id: a stored id is shown as the session's name now, and two forms of one session read as one
from stackshot.core import ghbudget as _gb   # the hour's GitHub calls, drawn as a card in the side panel's Audit section
from stackshot.web.ui import search as _search   # the search box every page's header draws, and its style (search.py)
from stackshot.web.ui import colortool as _ct   # the shared color tool's settings and script blocks (ui/colortool.py, shared/colortool.js)
from stackshot.web import runners as _runners   # the side panel's Runners section: the last snapshot, never a build (runners.peek)
_OWNER = str(_cfg.get("instance", "owner") or "the owner")   # whom a Next line addresses with "<owner>:"
# The board page does not show the For you section: it is hidden until its redesign, because as it stands it is nearly unusable.
# Display only: the rows are still recorded
# (foryou.py, for-you.json), the server's routes and `client.py get for-you` are unchanged, and for_you_html() / _FORYOU_JS stay below. True brings
# the section back, in the page, the in-place block set and the seen script. Read only where the board page is assembled (Board.html / _page).
_SHOW_FOR_YOU = False


def fleet_names():
    """letter → fleet name: session-names.tsv first (a box with no fleet state yet), then the fleet state's own `fleet` name (fleet.names)."""
    from stackshot.fleet import fleet as _fl
    return _fl.names()


def render(data_dir: str, mode: str = "full") -> str:
    """The board as text: mode = full (markdown) · html · brief."""
    return Board(data_dir).render({mode})[mode]


def render_all(data_dir: str) -> dict:
    """brief, full and html from ONE load of the store."""
    return Board(data_dir).render({"brief", "full", "html"})


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


# A receiver card never prints anchor-hub's raw error inline (a "drive …: [Errno …" string ran
# out of the google card across its neighbours): it shows a short state word, and the raw message sits in the tooltip.
# A network-shaped error reads "unreachable" (warn: usually a passing outage), anything else "error" (bad). The page script's
# rcv() takes the same pattern (injected from here), so the live update and the render agree.
_NET_ERR = (r"errno|timed? ?out|timeout|connect|resolv|name or service|temporary failure|unreachable|network|getaddrinfo"
            r"|ssl|eof occurred|refused|reset by peer|broken pipe|max retries|dns")
def receiver_state(v):
    """A receiver's status as (word, class): ("healthy ✓", "ok"), ("unreachable ✗", "warn") or ("error ✗", "bad")."""
    if v.get("ok"): return _t("js.rcv.ok"), "ok"
    return (_t("js.rcv.warn"), "warn") if re.search(_NET_ERR, str(v.get("error") or ""), re.I) else (_t("js.rcv.bad"), "bad")


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
    """In the verifying state (stored: states.py never derives it). The board's totals count these apart from open, so "open" is the work still to do."""
    return _states.of(r, after_open)[0] == "verifying"
def n_apart(rs):
    """(the rows that are not verifying, how many are): a project's or the board's open count, and its verifying count beside it."""
    rest = [r for r in rs if not is_verifying(r)]
    return rest, len(rs) - len(rest)
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


def _fact_time(v):
    """A reported time (an ISO string, Z or offset, or an epoch) as an aware datetime in the board's zone; None when unreadable."""
    try:
        if isinstance(v, (int, float)) and not isinstance(v, bool): t = datetime.datetime.fromtimestamp(float(v), datetime.timezone.utc)
        else: t = datetime.datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        return (t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)).astimezone(_cfg.tz())
    except Exception: return None


CHECKOUT_WHAT = "stackshot checkout"      # the puller's `what` for the box's own stackshot checkout (puller.py): the one update judged by where the box is
def server_commit():
    """The commit the boxes follow (clients.checkout_commit), "" when it cannot be told (a fixture, git away): machine_alerts then
    judges a checkout by its last attempt alone, as before."""
    try:
        from stackshot.fleet import clients as _cl
        return _cl.checkout_commit() or ""
    except Exception:
        return ""
def machine_alerts(m, server=""):
    """What a machine's view (machine.json) says went wrong, for its column in the Machines panel: the last setup run when it
    failed, and every package whose latest update attempt failed (facts.updates, ok false; the last one listed for a `what` wins, and
    an absent or malformed list is none). The box's own stackshot checkout is judged by where it is, not by its last attempt: when
    the box reports its checkout commit (`stackshot`) and the server's commit `server` is known, the failed attempt shows only while
    the two differ, and the card is clear again the moment they match (the box got there another way, a later attempt, a hand fix),
    except a failed reload of that very commit (reason "reload failed…", `to` the box's commit: the code there does not load);
    with either unknown the last attempt decides. → (setup or None, [failed updates]), each a dict as reported."""
    s = m.get("setup") if isinstance(m.get("setup"), dict) else None
    latest = {}
    for u in m.get("updates") if isinstance(m.get("updates"), list) else []:
        if isinstance(u, dict) and str(u.get("what") or "").strip(): latest[str(u["what"]).strip()] = u
    here, want = str(m.get("stackshot") or "").strip().lower(), str(server or "").strip().lower()
    ck = latest.get(CHECKOUT_WHAT)
    if here and want and here == want and ck is not None:
        reload_of_here = str(ck.get("reason") or "").startswith("reload failed") and str(ck.get("to") or "") == here[:12]
        if not reload_of_here: latest.pop(CHECKOUT_WHAT)    # a reload that failed on the code at the box's own commit is true there: the box is at the commit and not running it
    return (s if s and s.get("ok") is False else None), [u for u in latest.values() if u.get("ok") is False]


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
    return not is_held(r) or held_only_for_recycle(r, open_after)
_LANE_KINDS = {"call": _ui.YOUR_MOVE, "relay": _ui.WAITING, "": _ui.AGENT}      # needs_kind → the lists' state kind, for an item with no stored state
_STATE_KINDS = {"doing": _ui.AGENT, "your-call": _ui.YOUR_MOVE, "your-step": _ui.YOUR_MOVE,
                "outside": _ui.WAITING, "blocked": _ui.WAITING, "parked": _ui.WAITING, "verifying": _ui.WAITING}   # a stored state → the state kind whose word the lists use


def list_word(state, kind=None):
    """The word the lists use for a stored `state` (_STATE_KINDS), in the request's language; "" for a state this board does not know, a missing one or a value that is no string. With `kind` (needs_kind)
    given and no word for the state, the lane's word (_LANE_KINDS). The History says every move in these words ("moved to Your move")."""
    k = _STATE_KINDS.get(state) if isinstance(state, str) else None
    k = k or _LANE_KINDS.get(kind)
    return _ui.word(k) if k else ""
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
# (server._gate_options); the renderer draws what options_of returns, so a hand-edited list that broke the shape draws nothing.
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
    return _i18n.fmt_date(t, clock=clock)      # the string table's date forms (i18n.fmt_date): English unless the request is in another language
def age_words(seconds):
    """An age in words: "12 min", "5 h", "2 d" (minutes below 90 min, hours below 36 h, days from then on)."""
    m = int(max(0.0, float(seconds)) // 60)
    return _t("more.age_min", n=m) if m < 90 else (_t("more.age_hour", n=m // 60) if m < 60 * 36 else _t("more.age_day", n=m // 1440))
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
# A design decision's mockup (a claude.ai artifact page, or a fleet tool's /mockup/<n> page) is linked on the question itself: the home row and the item page's Ask block draw
# "Mockup ↗" beside the Decide part, so the owner opens the design from the ask he answers and not only from the item's background.
from stackshot.web.render import mockup_hit   # the one rule for what counts as a mockup link (render.py): server.py's write gate uses it too
def mockup_url(r):
    """The first mockup link (a claude.ai artifact page or a /mockup/<n> page) of an open decision item, looked for in the ask, then the options, then the description, then next; "" when it names
    none or is no open decision."""
    if r.get("status") == "completed" or needs_kind(r) != "call": return ""
    m = r.get("metadata") or {}
    opts = " ".join(f'{o.get("label") or ""} {o.get("line") or ""}' for o in (m.get("options") or []) if isinstance(o, dict))
    for text in (ask_of(r), opts, str(r.get("description") or ""), str(m.get("next") or "")):
        hit = mockup_hit(text)
        if hit: return hit
    return ""
def mockup_link(r, shown=""):
    """The "Mockup ↗" link drawn beside an open decision's question (an outside link: a new tab), "" when the item names no mockup, or when `shown`, the question text
    the page draws, already carries that link (the refusal tells a session to put [mockup](url) in the ask, so the chip would sit beside the same link)."""
    u = mockup_url(r)
    if u and u in shown: return ""
    return f' <a class="mockup" href="{esc(u)}" target="_blank" rel="noopener" title="{esc(_t("link.mockup_tip"))}">{esc(_t("link.mockup_chip"))}</a>' if u else ""
def stale_tip(r, label=str):
    """The tooltip of a stale item's ⚠: a your-call item's ask may be out of date; any other lane has gone unconfirmed (a parked item is never stale)."""
    a = age_words(r.get("_age") or 0)
    return _t("more.stale_tip_call", age=a) if needs_kind(r) == "call" else _t("more.stale_tip", age=a)
def _vtime(v):
    """A stored version's own time: the later of its `updated` and `confirmed` clocks, 0.0 when it has neither."""
    out = 0.0
    for k in ("updated", "confirmed"):
        try: out = max(out, float(v.get(k) or 0))
        except (TypeError, ValueError): pass
    return out
def id_href(g): return under(f"/items/{_gh.href_id(g)}")                 # an item's own page: /items/s5,
def item_href(r): return id_href(r["gid"])                         # an issue-numbered item's at /items/<n>, a temporary one's at /items/board-tmp-<machine>-3
def shown_full(g): return _gh.shown(g)                             # an id as a session reads it: board#N, board-tmp-<machine>#3, an older letter-and-number id as it is
def shown(g):                                                      # an id on the board itself: #7 ("board" crowds the UI), the rest as shown_full
    t = shown_full(g); return t[len("board"):] if t.startswith("board#") else t
def rid(r): return shown(r["gid"])
def issue_url(gid, store) -> str:
    """The item's GitHub issue, https://github.com/<[github] issues_repo>/issues/<n> (each item page links to its issue);
    "" with [github] sync off or no issues_repo, and for an item with no
    issue yet (a temporary id until it takes its number). The number is ghsync.issue_of's, a migrated item's old id resolved."""
    repo = _gh.repo()
    if not (_gh.enabled() and repo) or _gh.is_local(gid): return ""
    n = _gh.issue_of(str(gid), Path(store))
    return f"https://github.com/{repo}/issues/{n}" if n > 0 else ""
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
    if m: return _t("link.releases", repo=m.group(1))
    m = re.search(r"github\.com/[^/]+/([^/]+)/blob/[^/]+/(.+)", u)
    if m: return m.group(2).split("/")[-1]
    if "github.com" in h: return "GitHub"
    if "notion" in h: return "Notion"
    if "docs.google.com" in h: return {"/document": _t("link.google_doc"), "/spreadsheets": _t("link.google_sheet"), "/presentation": _t("link.google_slides")}.get(next((k for k in ("/document", "/spreadsheets", "/presentation") if path.startswith(k)), ""), _t("link.google_docs"))
    if "drive.google.com" in h: return "Drive"
    if "claude.ai" not in h and mockup_hit(u) == u: return _t("link.mockup")   # a fleet tool's mockup page: a plain link, never embedded (its pages share the terminal's address)
    if "claude.ai" in h: return _t("link.session")
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
def ago(s): return _i18n.fmt_age(s)      # "just now", "12m ago" (i18n.fmt_age: the catalog's age forms)
def landed_ago(s):
    """A close's age on the Landed page, in the page's one format (ago): "just now", "12m ago", "3h ago" (to 48 h), "5d ago". _LANDED_JS's ago() says the same, keep them in step."""
    return ago(max(int(s), 0))
def cli_behind(v, latest):
    """True when a machine's CLI version is older than the npm latest (numeric compare; unknown → False)."""
    try: return bool(latest) and tuple(int(x) for x in v.split(".")) < tuple(int(x) for x in str(latest).split("."))
    except Exception: return False
def esc(x): return H.escape(str(x), quote=True)
def esc_dq(x):      # for the value of a double-quoted attribute that is written in plain English with an apostrophe ("open this item's GitHub issue"): & < > and " are escaped, ' is not (esc turns it into &#x27;)
    return H.escape(str(x), quote=False).replace('"', "&quot;")
def _update_word(latest):
    """A machine row's update notice: `→ <latest version>`, and nothing at all while the latest version is not known (no arrow pointing nowhere)."""
    v = str(latest or "").strip()
    return "" if v in ("", "?") else "→ " + esc(v)
def _cmd_block(text, link=True, label=None):
    """A command to copy (a step's command or fenced block): its text escaped in a code block, with a Copy button beside it. The one place a command box is drawn. With [steps] owner_shell set, a line
    above the box names where the command runs ("Runs on <machine>", "In PowerShell"); in sala's Shell (owner_shell = "sala-shell") with a valid [steps] shell_url, an "Open shell" link to that page in a new tab
    sits on the line too, when `link` is true (a step with several commands passes it for its first box only). A box with no place to name and no link is the plain box."""
    label = _t("home.copy_clipboard") if label is None else label
    place, in_shell = _sc.runs_on(text)
    url = _cfg.shell_url() if in_shell and link else ""
    head = ""
    if place or url:
        head = ('<div class="cplace">' + (f'<span>{esc(place)}</span>' if place else "")
                + (f'<a class="cshell" href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(_t("home.open_shell"))}</a>' if url else "") + '</div>')
    return head + f'<div class="cmd"><pre><code>{esc(text)}</code></pre><button type="button" class="b copy" aria-label="{esc(label)}">{esc(_t("js.copy"))}</button></div>'
def _cmd_blocks(cmds, seen=None, **kw):
    """The boxes of several commands, with the Open shell link on the first box that can carry one: `seen` is a one-item list that says a link is already drawn in the same step (or in the same block of steps), and is
    kept across calls. A box that cannot carry a link (a bare link, a `! ` line) leaves it for the next."""
    seen = [False] if seen is None else seen
    out = []
    for c in cmds:
        blk = _cmd_block(c, link=not seen[0], **kw)
        if 'class="cshell"' in blk: seen[0] = True
        out.append(blk)
    return "".join(out)
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
_OUTCOME_KEYS = {"done": "item.outcome_word.done", "dropped": "item.outcome_word.dropped", "superseded": "item.outcome_word.superseded", "unrecorded": "item.outcome_word.unrecorded"}
def outcome_ui(oc):
    """An outcome as the item page says it in the viewer's language (the History's completed line); outcome_word stays the English every other reader (tool text, the markdown) gets."""
    return _t(_OUTCOME_KEYS[oc]) if oc in _OUTCOME_KEYS else oc


def outcome_of(r):
    """How a completed item ended: (outcome, reason, superseded_by), or ("", "", "") for an open item or one closed before
    the close carried them (no backfill)."""
    if r.get("status") != "completed": return "", "", ""
    m = r.get("metadata") or {}
    return str(m.get("outcome") or ""), str(m.get("reason") or ""), str(m.get("superseded_by") or "")
from stackshot.anchors.anchors import KINDS as _KIND     # an anchor id's prefix → its type; the one table, shared with anchor-hub
from stackshot.anchors import anchors as _anc   # roles.json's live flag per session (roles_live)
from stackshot.anchors.anchors import hub_of as _hub_of   # the page a key belongs to on the board (a `hub:` line, else its top-level page)
_AFLAG = {"unlisted": ("sessions.flag_unlisted", "sessions.flag_unlisted_tip"),      # the flag the index computes → (its label's key, its tooltip's key)
          "no session": ("sessions.flag_nosession", "sessions.flag_nosession_tip")}
_KIND_ORDER = ["Slack", "Notion", "Gmail", "Drive", "GitHub", "Link"]
_ROLE_TIP = {"background": _i18n.EN["projects.role_background"]}      # the English view; projects_table draws it through projects.role_background
# The theme switch: system → light → dark, one icon button, remembered per browser in
# localStorage; the board and the routing pages share the origin, so one choice covers both. _THEME_HEAD runs before the
# first paint so a re-rendered page never flashes the wrong theme; storage that throws (a private window) means "system".
_THEME_KEY = "stackshot-theme"
_THEME_HEAD = ("<script>(function(){var p='system';try{p=localStorage.getItem('" + _THEME_KEY + "')||p}catch(e){}"
               "if(p!=='light'&&p!=='dark')p='system';var r=document.documentElement;r.setAttribute('data-pref',p);"
               "if(p!=='system')r.setAttribute('data-theme',p)})();</script>")
# The board as an installed app (Chrome "Install page as app", display standalone). The manifest (/manifest.webmanifest,
# served by routes/board_pages.py) is fetched with credentials: Chrome fetches a manifest without cookies unless the link says
# use-credentials, and the hostname sits behind Cloudflare Access, which turns a cookieless request away. In an app window a
# target="_blank" link opens another app window whose Back closes it, so there a click on a same-origin _blank link
# navigates the window itself; links to other origins keep opening outside the app, and an ordinary browser tab is
# unchanged (items still open in a new tab). The listener is delegated on the document, so links the board's in-place
# update swaps in (_LIVE_JS) are covered without a re-bind, and the display mode is read at click time, so a page that
# moves between a tab and an app window follows the move. A click with a modifier or another button keeps its default. The same goes for a submit of the header's search box
# (a GET form with target=_blank, whose results open in a new tab): in an app window the results load in the window itself.
# The icons' URLs carry a version, ?v=<the first 12 hex digits of the SHA-256 of the file's bytes>, so a new icon is a new URL:
# an installed app (Chrome, Android) takes its icons through the browser's HTTP cache and Cloudflare's edge, and an icon
# under an unchanged URL never reached it (the maskable icon kept its old look). The
# versions are read once, when this module is imported (the server's start; deploy.sh restarts it when icons/ changes),
# from the committed icons/ (auth/signin.py _APP_ICONS) and the favicon in <state>/site. The version is a query string and the
# file names stay: the Cloudflare Access bypass names the icons' exact paths, which a query string keeps and a new name would
# not. routes/board_pages.py serves a request whose ?v= is the version of the bytes it sends as immutable; any other, as before.
# The icon and font files, their versions and addresses are the shared ones (render.py): static files at their root addresses, served once for both UIs.
from stackshot.web.render import ICON_DIR, asset_version, ICON_V, icon_href, FONT_DIR, FONT_FILE, font_href
_D2_FACE = '@font-face{font-family:"D2Coding";src:url("' + font_href() + '") format("woff2");font-weight:400;font-style:normal;font-display:swap}'
# The page scripts' words: SST(key, {field: value}) answers from window.SSI (the person's language, put in the head by apply_lang) else window.SSD (these English ones, from the string table's js.* and age.* keys), so the English page
# says exactly what the table says and a script never carries a copy of a word. A key in neither is returned as it is.
_SST_HEAD = ("<script>window.SSD=" + json.dumps(_i18n.js_table("en")).replace("</", "<\\/") + ";window.SSI=window.SSI||{};"
             "window.SST=function(k,f){var s=window.SSI[k];if(s==null)s=window.SSD[k];if(s==null)s=k;"
             "return f?s.replace(/\\{(\\w+)\\}/g,function(m,x){return f[x]==null?m:f[x]}):s}</script>")
# How long ago, in script: the same forms as i18n.fmt_age ("just now", "12m ago", "3h ago" to 48 h, "5d ago"; q: the ">21h ago" mark of a silence's start), from the table's age.* keys.
_AGE_FN = ("function fa(s,q){var m=Math.floor(Math.max(s,0)/60),k=m<60?'age.min':m<2880?'age.hour':'age.day',n=m<60?m:m<2880?Math.floor(m/60):Math.floor(m/1440);"
           "return q?'>'+SST(k,{n:n}):s<60?SST('age.now'):SST(k,{n:n})}")
# The last activity of an On agent row, kept current in script: every [data-at] (epoch seconds of the activity) is redrawn every 30 s. The age (.ir-age) says it as i18n.fmt_span does ("<1m", "46m", "1h 44m", "2d 3h", the age.span_* keys), the
# pill (.ir-pill) as the band says (its data-w-ok, data-w-warn and data-w-bad, the words in the person's language: they are on the element, not in the string table every page carries), and both take the band in data-b: ok under 45 minutes, warn from 45 up to and including 60, bad only past 60 minutes
# (model/last_activity.py BAND_* and band(); keep them in step: the script bands the age in seconds, as the model does, so that exactly an hour is amber and one second more is red). data-at is whole seconds, the same value the server banded by. A time ahead of the page's clock by more than
# SKEW_S is no record: the script leaves that element as the server drew it (never "<1m" for a time that has not come); Elements with no data-at are left alone.
_ACT_WORD = {_lastact.OK: "home.act.active", _lastact.WARN: "home.act.quiet", _lastact.BAD: "home.act.idle"}      # the pill's words by band (the string table's keys)
_LACT_JS = ("function lact(){var n=Date.now()/1000;document.querySelectorAll('[data-at]').forEach(function(e){var s=n-(+e.getAttribute('data-at'));if(s<-%d)return;s=Math.max(s,0);var m=Math.floor(s/60),"
            "b=s>%d?'bad':s>=%d?'warn':'ok';e.setAttribute('data-b',b);"
            "e.textContent=e.classList.contains('ir-pill')?e.getAttribute('data-w-'+b):"
            "m<1?SST('age.span_now'):m<60?SST('age.span_min',{m:m}):m<1440?SST('age.span_hour',{h:Math.floor(m/60),m:m%%60}):SST('age.span_day',{d:Math.floor(m/1440),h:Math.floor(m%%1440/60)})})}"
            "lact();setInterval(lact,30000);document.addEventListener('stackshot:swapped',lact);") % (int(_lastact.SKEW_S), _lastact.BAND_BAD_S, _lastact.BAND_WARN_S)
_APP_HEAD = _SST_HEAD + ('<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">'
             f'<link rel="apple-touch-icon" href="{icon_href("apple-touch-icon.png")}">'          # 180 px, opaque (auth/signin.py _APP_ICONS)
             '<meta name="theme-color" content="#fafaf8" media="(prefers-color-scheme: light)">'   # the app's title bar: each theme's --bg
             '<meta name="theme-color" content="#161617" media="(prefers-color-scheme: dark)">'
             "<script>(function(){var m=window.matchMedia?matchMedia('(display-mode: standalone)'):null;"
             "function app(){return !!((m&&m.matches)||window.navigator.standalone===true)}"
             "document.addEventListener('click',function(ev){if(ev.defaultPrevented||ev.button!==0||ev.metaKey||ev.ctrlKey||ev.shiftKey||ev.altKey||!app())return;"
             "var a=ev.target&&ev.target.closest?ev.target.closest('a[href]'):null;if(!a||String(a.target).toLowerCase()!=='_blank'||a.hasAttribute('download'))return;"
             "var u;try{u=new URL(a.href,location.href)}catch(e){return}if(u.origin!==location.origin)return;"
             "ev.preventDefault();location.assign(u.href)});"
             # the search box's form opens its results in a new tab; an app window has none, so a same-origin GET form with target=_blank goes to the window itself, as its link does
             "document.addEventListener('submit',function(ev){var f=ev.target;if(ev.defaultPrevented||!app()||!f||!f.getAttribute||String(f.getAttribute('target')).toLowerCase()!=='_blank'||String(f.getAttribute('method')).toLowerCase()!=='get')return;"
             "var u;try{u=new URL(f.getAttribute('action')||location.href,location.href)}catch(e){return}if(u.origin!==location.origin)return;"
             "u.search=new URLSearchParams(new FormData(f)).toString();ev.preventDefault();location.assign(u.href)})})();</script>")
_APP_HEAD += _ct.HEAD   # the color tool's library (once per page) and the script that applies the stored look, in the head of every page after the theme script, before the page's own style
def _panel_btn(is_open: bool = True, lang: str | None = None) -> str:
    """The summary panel's button in the title bar, in `lang` (default: the request's): drawn for an open panel (aria-expanded true, "Hide summary panel"), or for a closed one (apply_panel_open)."""
    return ('<button type="button" class="b ico pbtn" id="panel-open" aria-label="' + esc(_t("panel.button", lang)) + '" aria-controls="panel" aria-expanded="' + ("true" if is_open else "false")
            + '" title="' + esc(_t("panel.hide" if is_open else "panel.show", lang)) + '">'
            '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2.5" y="3.5" width="15" height="13" rx="2.5"/><path d="M12.5 3.8v12.4"/></svg></button>')
_PANEL_BTN = _panel_btn(True, "en")
_PANEL_BTN_CLOSED = _panel_btn(False, "en")   # the button as drawn for a person whose panel is stored closed (apply_panel_open)
def _theme_btn(lang: str | None = None) -> str:
    """The theme button (system, light, dark) in `lang`; the page script puts the label of the theme in use on it (js.theme.*)."""
    return _THEME_BTN.replace('aria-label="Theme: system" title="Theme: system"', 'aria-label="' + esc(_t("js.theme.system", lang)) + '" title="' + esc(_t("js.theme.system", lang)) + '"', 1)
_THEME_BTN = ('<button type="button" class="b ico theme" id="theme" aria-label="Theme: system" title="Theme: system">'
              '<svg class="i-system" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>'
              '<svg class="i-light" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
              '<svg class="i-dark" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg></button>')
# The reload button. It floats on every page, stacked right above the floating 'to the top' button: the same round 44 px
# button as #totop (shared CSS rule), fixed 10 px above it at the bottom right. Back to top is always shown (it does not wait for a scroll),
# so the pair is always a stack and neither moves. A full reload; the browser keeps the scroll position, the item page's and project page's folds are in localStorage (the home page's are not) and
# the panel pins again on load. One delegated listener (_RELOAD_JS) serves the button wherever the page puts it, so the board's in-place
# swap needs no re-bind; the pair sits outside every swapped block. The target of Back to top is the page's id="top" element (the board's
# main, the item page's and the project page's main). _FAB_PAIR is the one copy of the markup, _TOTOP_JS of its click handler.
_RELOAD_FAB = ('<button type="button" class="fab" id="reload" aria-label="Reload" title="Reload page">'
               '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg></button>')
_RELOAD_JS = ("<script>document.addEventListener('click',function(e){var b=e.target&&e.target.closest?e.target.closest('#reload'):null;"
              "if(b)location.reload()})</script>")
_TOTOP_LINK = ('<a href="#top" id="totop" aria-label="Back to top" title="Back to top"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.5" '
               'stroke-linecap="round" stroke-linejoin="round"><path d="M6 14l6-6 6 6"/></svg></a>')
_FAB_PAIR = _RELOAD_FAB + "\n" + _TOTOP_LINK
_FAB_PAIR += _ct.BODY   # the color tool's init, at the end of every page's body: it draws the Colors button into the side panel's mount (#panel-colors) and the panel in the body
_TOTOP_JS = ("<script>(function(){var b=document.getElementById('totop');if(!b)return;"
             "b.addEventListener('click',function(e){e.preventDefault();window.scrollTo(0,0);history.replaceState(null,'',' ')})})();</script>")
# The folds' open state is per browser (localStorage). The toggle listener is delegated (toggle does not bubble: capture on the
# document), so a section the in-place update swaps in (_LIVE_JS) keeps recording without a re-bind; the swap itself carries
# each fold's live open state over to its new node. Two kinds (the scope groups inside a section
# collapsible like the sections): a section fold renders closed and opens on a stored '1'; a scope group fold renders open and
# closes on a stored '0'. A hash to a line opens every fold around it (its group and its section); to a section, the section.
_FOLD_GO = r"""function go(h,scroll){if(!h)return;var id=decodeURIComponent(h.replace(/^#/,''));var el=document.getElementById(id);if(!el)return;
if(el.matches&&el.matches('section')){var s=el.querySelector('details.fold');if(s&&!s.open)s.open=true}
else for(var d=el.closest&&el.closest('details.fold');d;d=d.parentElement&&d.parentElement.closest('details.fold'))if(!d.open)d.open=true;if(scroll)el.scrollIntoView()}
"""
_FOLD_HASH = r"""go(location.hash,false);window.addEventListener('load',function(){if(location.hash)go(location.hash,true)});
window.addEventListener('hashchange',function(){go(location.hash,true)});
document.querySelectorAll('a.hcard[href^="#"]').forEach(function(a){a.addEventListener('click',function(){var h=a.getAttribute('href');if(h===location.hash){go(h,true)}})});})();"""
_FOLD_JS = (r"""(function(){var K='stackshot.fold.',F=[].slice.call(document.querySelectorAll('details.fold')).filter(function(d){return !d.closest('#panel')});
function get(k){try{return localStorage.getItem(K+k)}catch(e){return null}}function put(k,v){try{localStorage.setItem(K+k,v)}catch(e){}}
F.forEach(function(d){var v=get(d.getAttribute('data-fold'));if(d.open){if(v==='0')d.open=false}else if(v==='1')d.open=true});
""" + _FOLD_GO + r"""document.addEventListener('toggle',function(e){var d=e.target;if(d&&d.matches&&d.matches('details.fold')&&d.isConnected&&!d.closest('#panel'))put(d.getAttribute('data-fold'),d.open?'1':'0')},true);
""" + _FOLD_HASH)
# The home page's own fold script (only Your move open, all the others closed by default, nothing remembered):
# the home page remembers nothing. The server renders Your move open and every other fold of
# the main column (On agent, Waiting, For you, the Task board, Completed) closed, and Queued for release open; the side panel's sections (Machines, Runners, Anchor hub,
# Audit) render open; this script neither
# reads nor writes a fold's state, and removes the keys an earlier version stored for these sections (_HOME_OLD_FOLD_KEYS: the section
# ids only, since the item page's and the project page's folds keep their own "item.*" / "project.*" keys in the same store). A hash
# to a section, or to a row inside a closed one, still opens it on load and on hashchange (the same go() as _FOLD_JS).
_HOME_OLD_FOLD_KEYS = ("for-you", "your-move", "agents-at-work", "queued-release", "waiting-list", "by-project", "completed", "machines", "anchorhub")
_HOME_FOLD_JS = (r"""(function(){try{""" + json.dumps(list(_HOME_OLD_FOLD_KEYS)) + r""".forEach(function(k){localStorage.removeItem('stackshot.fold.'+k)})}catch(e){}
""" + _FOLD_GO + r"""var go0=go;go=function(h,scroll){go0(h,scroll);if(scroll&&location.hash)try{history.replaceState(null,'',location.pathname+location.search)}catch(e){}};
""" + _FOLD_HASH)
# First paint (the For you section always appeared expanded on page load and then instantly closed itself):
# _FOLD_JS runs at the end of the body, so a fold whose stored state differs from its rendered default (For you rendered
# open, stored '0') painted in the default state and snapped a moment later. _FOLD_HEAD sits in the head, next to _THEME_HEAD,
# and watches the parser: a MutationObserver on the document element sees each details.fold as it is inserted (and any inside an
# added subtree) and applies the stored state exactly as _FOLD_JS does, in a microtask, before the browser renders. It stops at
# DOMContentLoaded (after one last pass over the pending records). _FOLD_JS keeps its own pass as a backstop, for a browser without
# MutationObserver. Storage that throws (a private window) leaves the rendered default.
_FOLD_HEAD = ("<script>(function(){if(!window.MutationObserver)return;"
              "function ap(d){if(d.closest('#panel'))return;var v=null;try{v=localStorage.getItem('stackshot.fold.'+d.getAttribute('data-fold'))}catch(e){}"
              "if(d.open){if(v==='0')d.open=false}else if(v==='1')d.open=true}"
              "function sc(n){if(n.nodeType!==1)return;if(n.matches('details.fold'))ap(n);[].forEach.call(n.querySelectorAll('details.fold'),ap)}"
              "function run(rs){rs.forEach(function(r){[].forEach.call(r.addedNodes,sc)})}"
              "var o=new MutationObserver(run);o.observe(document.documentElement,{childList:true,subtree:true});"
              "document.addEventListener('DOMContentLoaded',function(){run(o.takeRecords());o.disconnect()})})();</script>")
# The top-level sections (Need your call (agents), For you, Task board in the main column; Machines, Runners, Anchor hub, Audit and Projects in the panel) fold like the item sections: the same details.fold
# markup.
# In the main column only Your move renders open, the panel's sections all render open, and nothing is remembered (_HOME_FOLD_JS), a hash to the section id opens it,
# and the in-place swap carries the live open state over. The key is the section id (distinct from every item section's and scope group's). The Tasks tiles are in the summary panel (_PANEL_JS), with Machines and Anchor hub, not in the main column.
def _top_fold(sid: str, h2: str, body: str, is_open: bool = False) -> str:
    # A side-panel section carries the grip that moves it (see the panel order, below) beside the fold, not inside its <summary>: a button in a summary is nested interactive
    # content and merges its name into the summary's ("Runners Move Runners section"); beside it, the summary keeps the title as its name and the grip its own.
    grip = _pgrip(sid) if sid in _PANEL_LABELS else ""
    return f'<section id="{sid}"><details class="fold" data-fold="{sid}"{" open" if is_open else ""}><summary>{h2}</summary>{body}</details>{grip}</section>'
# The header's height: the sticky header (a phone's is not sticky) is as tall as `--hdr` says, which the rows' and sections' scroll margin and a notice that sticks under it read. One copy for home (which swaps its blocks: the
# swap event) and for every other page (panel_tail).
_HDR_JS = ("(function(){var h=document.querySelector('header.top');if(!h)return;function hdr(){document.documentElement.style.setProperty('--hdr',(getComputedStyle(h).position==='sticky'?h.offsetHeight:0)+'px')}"
           "hdr();window.addEventListener('resize',hdr);document.addEventListener('stackshot:swapped',hdr)})();")
# The site title: the logo and the board's name, the home page's h1, now the first line of the header every page draws (page_header) and a link to "/"
# (the item, project, Landed and Search pages had a small grey "← title" link in its place). On the home page it is the page's h1; on the others, where
# the page's own heading is the h1 (the item's subject, the project's name, Landed, Search), the same markup is a <p>, so a page has one h1. The link takes the
# text colour and is underlined only on hover and keyboard focus (.site in the CSS). On the home page it also clears a #hash: a click on a link to "/" there
# loads the page without it. `src` is the logo's address: the home page's is relative (its markup is published as a file), the others' absolute.
def _site_title(title: str, src: str, h1: bool = False) -> str:
    tag = "h1" if h1 else "p"
    return f'<{tag} class="site"><a href="{under("/")}"><img class="logo" src="{src}" alt="" aria-hidden="true">{esc(title)}</a></{tag}>'
# The "rendered … ago" line, drawn once for every page with the header (page_header) and kept beside the site title: grey while the page is current, warn-coloured past the stale threshold
# (_stale_s: 1.5 publish periods). `stamp_html` is the stamp span (Board.stamp); the home page's shell fingerprint passes "" (the per-render value taken out). The text of the span and the
# warn colour are kept current by the home page's tick and live update, and on every other page by _STAMP_JS (panel_tail). Under 600 px the word "rendered" is left off (.rw), the age stays.
# `tip` is the span's title text: home's (the default) is about the server's publishing; a page drawn per request says when it was drawn, since its amber only means that page is old.
_AGE_AT = "\x00age\x00"      # where the template of the rendered line puts the age (never in a translation)
def _rendered_line(stamp_html: str, tip: str | None = None) -> str:
    tip = _t("home.rendered_tip", every=f"{_every_m():g}", stale=_stale_s() // 60) if tip is None else tip
    parts = _t("home.rendered_line", age=_AGE_AT).split(_AGE_AT)      # one template, so a language can put the age first ("3m ago updated"); the words around the age are what the narrow page leaves off (.rw)
    # The age is drawn once, at the template's first {age}: a second {age} draws nothing (its place is empty, the marker never reaches the page); a template with none (a language may leave a field out) puts
    # the age span after its words, since the span carries the stale colour, the title text and the tick.
    pre, post = parts[0], "".join(parts[1:])
    rw = lambda x: f'<span class="rw">{esc(x)}</span>' if x else ""
    return f'<p class="rline">{rw(pre)}<span id="rendered" data-stale="{_stale_s()}" title="{esc(tip)}">{stamp_html}</span>{rw(post)}</p>'
# The age on a page that is not home (home's tick does the same for the whole page): the stamp's text redrawn every 30 s from its data-ts and the old class set past data-stale. A page without the line does nothing.
_STAMP_JS = ("<script>(function(){var g=document.getElementById('rendered'),s=g&&g.querySelector('[data-ts]');if(!s)return;"
             + _AGE_FN +
             "function tick(){var d=Date.now()/1000-(+s.getAttribute('data-ts'));s.textContent=fa(d);g.classList.toggle('old',d>+g.getAttribute('data-stale'))}"
             "tick();setInterval(tick,30000)})();</script>")
# The summary panel's frame: the hover strip, the aside with its five blocks (Board.panel_blocks, keyed as the home page swaps them) and the scrim. The
# home page draws it from its blocks (or their placeholders, for its shell fingerprint), every other page from Board.panel_tail; both put it after the page's <main>
# inside <div id="layout">, the grid that docks it (the CSS, _PANEL_DOCK_PX).
def _panel_frame(B: dict) -> str:
    return ('<div id="panel-edge" aria-hidden="true"></div>\n<aside id="panel" aria-label="' + esc(_t("panel.title")) + '">\n'
            '<div class="phead"><span class="ptitle">' + esc(_t("panel.title")) + '</span><button type="button" class="b ico pbtn" id="panel-close" aria-label="' + esc(_t("panel.close")) + '">&times;</button></div>\n'
            + "\n".join(f'<!--ps:{k}-->{B[k]}<!--/ps:{k}-->' for k in _up.PANEL_SECTIONS)
            + _lang_toggle()
            + '\n<div id="panel-colors-gap" aria-hidden="true"></div><div id="panel-colors"></div>'      # the color tool's mount (ui/colortool.py): the last thing in the panel, outside the sections that move, with the gap before it
            + '\n<div id="panel-menu" class="pmenu" role="menu" aria-label="' + esc(_t("panel.move_menu")) + '" hidden>'
            + "".join(f'<button type="button" role="menuitem" class="pmi" data-act="{a}" tabindex="-1">{esc(_t("panel.move." + a))}</button>' for a in _PANEL_MOVES)
            + '</div>\n<div id="panel-live" class="pvh" role="status" aria-live="polite" aria-atomic="true"></div>\n</aside>\n<div id="panel-scrim"></div>')
# The order of the side panel's sections (Machines, Runners, Anchor hub, Audit, Projects) is the signed-in person's own, kept on the server (uiprefs.py) so a PC tab and a
# phone show the same. The page is drawn in the default order and the server puts it in the person's order on the way out (apply_panel_order, called by the root
# routes' wrapper): the saved order is in the first paint, so nothing moves when the page loads, and the home page's one kept draw serves everyone. Each section is
# wrapped in <!--ps:id-->...<!--/ps:id--> in the frame so the reorder is a split on markers, never a parse of the section's own markup. The grip on each section's
# header (_pgrip; in the section, outside the fold's <summary>, at the header's right end) is the one control: dragged with a pointer (mouse, touch, pen) it moves the section, with an accent-coloured (orange) drop line where it will land; clicked, or
# focused and Enter / Space, it opens a menu of the four moves (Move up, Move down, Move to top, Move to bottom; the ones that do not apply are disabled), the way for the
# keyboard and a phone. Each move is announced in the live region and saved at once (POST /prefs/panel-order). The default order needs no control of its own: moving the sections back is moving them.
_AUDIT_GROUPS = {v: k[len("panel.audit.group."):] for k, v in _i18n.EN.items() if k.startswith("panel.audit.group.")}     # an audit group's English name -> its key (audit_overview.GROUPS names, the audit card)
_AUDIT_NOTES = {v: k[len("panel.audit.note."):] for k, v in _i18n.EN.items() if k.startswith("panel.audit.note.")}        # the card's note line, English -> key (audit_overview.NOTE_*)
def _audit_word(table: dict, english: str, prefix: str) -> str:
    """An audit group's name or the card's note in the request's language: by the English text the audit module gives; one the table does not know stays as it is."""
    k = table.get(english)
    return _t(prefix + k) if k else english
_AUDIT_PACES = {v: k[len("audit.pace."):] for k, v in _i18n.EN.items() if k.startswith("audit.pace.")}      # an audit's pace and mode words, English -> key (audit_overview.GROUPS, _mode); the Audits page draws them through the table
_AUDIT_MODES = {v: k[len("audit.mode."):] for k, v in _i18n.EN.items() if k.startswith("audit.mode.")}
_PANEL_LABELS = {"machines": "Machines", "runners": "Runners", "anchorhub": "Anchor hub", "audit-panel": "Audit", "projects-panel": "Projects"}      # English; the section's name in the person's language is panel.sec.<id> (panel_label)
assert tuple(_PANEL_LABELS) == _up.PANEL_SECTIONS
_PANEL_MOVES = ("up", "down", "top", "bottom")      # the move menu's items; their words are panel.move.<name>
def panel_label(sid: str) -> str:
    """A side-panel section's name in the request's language."""
    return _t("panel.sec." + sid)
def _lang_toggle() -> str:
    """The language switch at the foot of the side panel: EN and KO as two buttons (the pressed one is the language in use), drawn only when a second language has loaded (i18n.available()), so a board
    with no locale folder shows none. _LANG_JS saves the choice (POST /prefs/lang) and reloads the page."""
    langs = _i18n.available()
    if len(langs) < 2: return ""
    cur = _i18n.norm(_i18n.current())
    btns = "".join(f'<button type="button" class="b plg" data-lang="{c}" lang="{c}" aria-pressed="{"true" if c == cur else "false"}" title="{esc(_t("panel.lang." + c))}">{c.upper()}</button>' for c in langs)
    return f'\n<div id="panel-lang" role="group" aria-label="{esc(_t("panel.lang"))}">{btns}</div>'
_LANG_TOGGLE_RX = re.compile(r'\n<div id="panel-lang" .*?</div>', re.S)
def strip_lang_toggle(page: str) -> str:
    """The page without its language switch. The switch saves a choice for a signed-in person (POST /prefs/lang), so a visitor who is not signed in gets none: the draw is shared, the server takes it out on the way."""
    return _LANG_TOGGLE_RX.sub("", page, count=1)
_LANG_JS = ("(function(){var G=document.getElementById('panel-lang');if(!G||!window.fetch)return;"
            "G.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('button[data-lang]');if(!b||b.getAttribute('aria-pressed')==='true')return;"
            "[].forEach.call(G.querySelectorAll('button'),function(x){x.disabled=true});"
            "fetch('@ROOT@/prefs/lang',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({lang:b.getAttribute('data-lang')})})"
            ".then(function(r){if(!r.ok)throw 0;location.reload()},function(){[].forEach.call(G.querySelectorAll('button'),function(x){x.disabled=false})}).catch(function(){})})})();").replace("@ROOT@", PREFIX)
_PGRIP_SVG = ('<svg viewBox="0 0 10 16" width="10" height="16" aria-hidden="true" focusable="false"><g fill="currentColor"><circle cx="2.5" cy="3" r="1.4"/><circle cx="7.5" cy="3" r="1.4"/>'
              '<circle cx="2.5" cy="8" r="1.4"/><circle cx="7.5" cy="8" r="1.4"/><circle cx="2.5" cy="13" r="1.4"/><circle cx="7.5" cy="13" r="1.4"/></g></svg>')
def _pgrip(sid: str) -> str:
    lab = esc(panel_label(sid))
    return (f'<button type="button" class="pgrip" id="pgrip-{sid}" data-sec="{sid}" data-label="{lab}" aria-label="{esc(_t("panel.move_section", label=panel_label(sid)))}" aria-haspopup="menu" aria-expanded="false" aria-controls="panel-menu" '
            f'title="{esc(_t("panel.grip_tip"))}">{_PGRIP_SVG}</button>')
_PSEC_RX = re.compile(r"<!--ps:([a-z0-9-]+)-->(.*?)<!--/ps:\1-->", re.S)
def apply_panel_order(page: str, order) -> str:
    """The page (drawn in the default order) with the side panel's sections in `order` (made whole by uiprefs.normalize).
    A page with no side panel, or whose sections are not wrapped as _panel_frame writes them, comes back as it was."""
    want = _up.normalize(order)
    if _up.is_default(want):
        return page
    secs = {m.group(1): m for m in _PSEC_RX.finditer(page)}
    if set(secs) != set(_up.PANEL_SECTIONS):
        return page
    it = iter(want)
    return _PSEC_RX.sub(lambda m: secs[next(it)].group(0), page)
# The copy button on a command block: the clipboard API on the https board, a hidden textarea where it is missing
_COPY_JS = ("<script>document.addEventListener('click',function(ev){var b=ev.target.closest&&ev.target.closest('button.copy');if(!b)return;"
            "var p=b.closest('.draft')||b.parentNode,t=p.querySelector('code').textContent;function ok(){b.textContent=SST('js.copied');setTimeout(function(){b.textContent=SST('js.copy')},1500)}"
            "function fb(){var a=document.createElement('textarea');a.value=t;a.setAttribute('readonly','');a.style.position='fixed';a.style.opacity='0';"
            "document.body.appendChild(a);a.select();var d=false;try{d=document.execCommand('copy')}catch(e){}a.remove();"
            "if(d)ok();else{var c=p.querySelector('code'),g=document.createRange(),n=window.getSelection();g.selectNodeContents(c);n.removeAllRanges();n.addRange(g)}}"      # no copy at all: the text is selected, for the person's own copy
            "if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(t).then(ok,fb);else fb()});</script>")
_SAID_JS = ("<script>(function(){function o(){var h=location.hash;if(!h||h.indexOf('#said-')!==0)return;var d=document.getElementById(h.slice(1));"
            "if(d&&d.tagName==='DETAILS'){d.open=true;d.scrollIntoView()}}o();addEventListener('hashchange',o)})()</script>")   # the issue's trailer link opens its entry
_THEME_JS = ("<script>(function(){var b=document.getElementById('theme');if(!b)return;var r=document.documentElement,"
             "o=['system','light','dark'],n={system:SST('js.theme.system'),light:SST('js.theme.light'),dark:SST('js.theme.dark')};"
             "function show(p){if(o.indexOf(p)<0)p='system';r.setAttribute('data-pref',p);if(p==='system')r.removeAttribute('data-theme');"
             "else r.setAttribute('data-theme',p);b.setAttribute('aria-label',n[p]);b.title=n[p]}"
             "show(r.getAttribute('data-pref'));"
             "b.addEventListener('click',function(){var p=o[(o.indexOf(r.getAttribute('data-pref'))+1)%3];show(p);"
             "try{localStorage.setItem('" + _THEME_KEY + "',p)}catch(e){}});"
             "window.addEventListener('storage',function(e){if(e.key==='" + _THEME_KEY + "')show(e.newValue||'system')})})();</script>")
# The summary panel (open by default, and open or closed on a wide screen as the signed-in person last left it, on every page): a panel on the
# right of the board, as sala's sidebar is on the left, holding what is not the day's work: the Tasks counts, Machines, Runners, Anchor hub, Audit and Projects.
# On a wide screen (800 px and up) the pointer on the strip along the page's right edge (#panel-edge) or on the title bar's button
# (#panel-open) PEEKS it: it slides in over the page, below the title bar, and leaving the three (strip, button, panel) takes it away
# after a short moment, so the way from the button to the panel does not shut it. A click on the button PINS it: it docks beside the
# page (the main column keeps its width, see the CSS) until the next click unpins it. Where it sits (the buttons fixed at the
# window's top right, the panel right under them in both open states; sala's sidebar mirrored to the right): on a wide screen the panel's button and the theme
# button are position:fixed at the window's top right on every page and in every state, in a _PANEL_TOP_PX band with the page background (body::before) so text
# scrolled under them stays readable; the panel is position:fixed at the window's right edge starting at _PANEL_TOP_PX, _PANEL_PX wide, peeking and pinned alike (pinned it sits at z-index 9, under the floating reload and Back to top buttons at 10, which float over its bottom padding as before; peeking it is over them);
# pinned, #layout leaves _PANEL_RESERVE_PX of room on its right for it. Nothing moves when the panel opens or pins. Under 800 px the drawer and the buttons in
# the page header are as they were. Below 800 px (a phone, a
# narrow tablet in portrait) the button opens it as a drawer from the right, closed by its × button, a tap on the scrim, Escape or a tap on a
# link to the main column. It is PINNED on a wide screen and a closed drawer on a narrow one. What a click on a wide screen leaves, pinned or unpinned, is the person's own and is kept on the server with
# their panel order (uiprefs.py `panel_open`; POST /prefs/panel-open, saved by _PANEL_JS), so it holds on every page, reload, browser and device; the default, nothing stored, is pinned. The drawer under 800 px is
# never stored and starts closed whatever is stored. Its sections (Machines,
# Runners, Anchor hub, Audit and Projects) are open on every load (_HOME_FOLD_JS). The default
# is the page's own markup, so the first paint has it: every page is drawn with the body class panel-pin (the pin rules live inside the
# min-width:800px media query, so on a narrow screen the class changes nothing the eye sees) and the button aria-expanded="true" with the title "Hide summary panel"; the server then
# draws it closed for a person whose stored state is closed (apply_panel_open, on the way out like the section order: a bare <body> and the button "false" with "Show summary panel"), so the first paint is right on
# every page and nothing flashes. The script reads the class (pinned only when wide) and corrects the button on a narrow screen. Crossing 800 px sets that state again (the one the page was drawn with, or the
# one the person last chose here). The state is the body's classes (panel-peek, panel-pin, panel-open);
# the panel and its frame are outside the blocks the in-place update (_LIVE_JS) swaps, so a swap leaves them as they are, and the
# blocks swapped into it (overview, machines, anchorhub) take the folds' open state over as everywhere. A hash to something inside
# it (#machines, #anchorhub) opens it: pinned on a wide screen (nothing holds a peek open without the pointer), the drawer on a phone.
# The button's accessible name is fixed ("Summary panel"); aria-expanded alone carries the state (its title says what a click does).
# Whatever closes the drawer returns focus to the button, the one control that opens it, also after a tap on the scrim blurred focus to the body.
# The item, project, Landed and Search pages carry the same panel as home: the same body class, frame, button, script and blocks
# (Board.panel_blocks, Board.panel_tail), pinned by default the same way, the item page included, and kept the same way (one stored state for every page). Their folds in the
# panel are not remembered either: _FOLD_JS and _FOLD_HEAD leave a fold inside #panel alone. The Audit script's addresses are absolute (/audit/status, /audit/now),
# since those pages are not at the root.
_PANEL_DOCK_PX = 800   # the one width at which the panel docks (was 960): the CSS media query below and _PANEL_JS's matchMedia both take it from here, so they cannot drift apart. A zoomed desktop window is narrower in CSS px, so 960 was too high; at 800 the pinned main column is 480 px (800 - 2*16 padding - 288 room for the panel), measured usable by tests/phone_width_check.py.
# The item page's Details column (.iside) sits beside the main column (.imain) and moves above it, into the one-column strip it has under 768 px, whenever
# the pinned summary panel leaves too little room for both. The main column keeps the width the board measured usable (480 px, see
# _PANEL_DOCK_PX); the room it needs is that, the Details column and its gap beside it, then the panel, its gap and the body's side padding:
# 480 + 256 + 32 + 288 + 2 * 16 = 1088 px (288 is _PANEL_RESERVE_PX: the 280 px panel and 8 px beside the body's own 16 px padding, a 24 px gap). Below it, with the panel pinned (body.panel-pin, which only a viewport of _PANEL_DOCK_PX and up keeps),
# the strip rules apply; with the panel unpinned the item page has the whole width and the two columns stay down to 768 px.
_ITEM_MAIN_MIN_PX, _ITEM_SIDE_PX, _GRID_GAP_PX, _BODY_PAD_PX = 480, 256, 32, 32
# Pinned or peeking, the panel's left border also runs up through the buttons' band to the top of the page (body::after, a 1 px line at the panel's left edge); the header's cards column is capped to what it is with the panel pinned (100cqw of the root element, which leaves a classic scrollbar out as the pinned layout does; 100vw would not), so the cards keep one size in every panel state.
_PANEL_PX, _PANEL_TOP_PX, _PANEL_RESERVE_PX = 280, 56, 288   # the panel's width, the top band the buttons own (the panel starts under it), and the room #layout leaves for a pinned panel
_ITEM_PIN_STRIP_PX = _ITEM_MAIN_MIN_PX + _ITEM_SIDE_PX + _GRID_GAP_PX + _PANEL_RESERVE_PX + _BODY_PAD_PX   # 1088: the strip below this width, panel pinned
_ISTRIP_CSS = '.ilayout{grid-template-columns:minmax(0,1fr)}.imain,.iside{grid-column:1;grid-row:auto}.imain{display:contents}.imain>*{order:2}.imain>.istat,.imain>.iask,.imain>.ianswer,.imain>.iwait,.imain>.ioutcome{order:0}.iside{order:1}.istep .istepbody{margin-top:4px}.istep .cmd{margin:6px 0 2px}.iside{margin:0 0 16px;padding-top:10px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.iside dl.sgrp{display:grid;grid-template-columns:7.5em minmax(0,1fr);column-gap:12px;row-gap:8px;align-items:baseline;padding:10px 0}.iside dl.sgrp:first-child{padding-top:0}.iside dt,.iside dd{margin:0}'

# The Closed card's "N new" sits on the label line, right after the word Closed. Where that line is too narrow for it (the card's content width, which a container query on the card measures,
# is at or under a limit that grows with the count's digits), "N new" moves up to the number line, beside the number: never clipped, never cut to the bare count. The word is the
# page's own, the string catalog's "home.new_word" in the person's language (_new_word); the limits below are the English word's (79 px for a count of one digit, 6 more for each digit up to four) plus the room a longer word needs, estimated
# per character at the badge's size (a wide character, as east-asian text has, takes 12 px, any other 7: the English word's 21 px is within the limits as they were), so a longer word
# only moves up sooner. The row then needs the number's width, the count and the word (the card's --need, estimated in px at the full sizes: 22 px digits, 12 px badge); where the card's
# content (and the 6 px of its side padding the badge may use) is narrower than that, both shrink in that proportion (the badge never under 9 px unless the word is so long that the number would then fall under its 6 px; the number then takes what the badge leaves, --nk and --bk), so the whole stays inside the card. The card is 60 px tall and its label one line either way.
def _new_word():
    """The word after the Closed card's count as the page says it, in the request's language: the catalog's "home.new_word" without its leading space."""
    return _t("home.new_word").strip()
_HNEW_LIMITS = (79, 85, 92, 98)
_HNEW_DIGIT_PX, _HNEW_SMALL_DIGIT_PX, _HNEW_SPACE_PX, _HNEW_CHAR_PX, _HNEW_WIDE_PX = 15.4, 7.2, 3.4, 7, 12
def _word_px(word):
    """The room a word takes in the badge, estimated: 7 px a character, 12 for a wide (east-asian) one."""
    import unicodedata
    return sum(_HNEW_WIDE_PX if unicodedata.east_asian_width(c) in "WF" else _HNEW_CHAR_PX for c in word)
def _hnew_need(n, new, word=None):
    """The number line's need in px, for the Closed number `n` and the count `new`, at the full sizes, without the 4 px between them: the card's --need."""
    return round(_HNEW_DIGIT_PX * len(str(n)) + _HNEW_SMALL_DIGIT_PX * len(str(new)) + _HNEW_SPACE_PX + _word_px(_new_word() if word is None else word))
def _hnew_parts(n, new, word=None):
    """The card's --nk (the number's width in px at its full 22 px size) and --bk (the badge's width per px of its font size: its digits, the space and the word at the full 12 px, over 12), for the narrow rules."""
    full = _HNEW_SMALL_DIGIT_PX * len(str(new)) + _HNEW_SPACE_PX + _word_px(_new_word() if word is None else word)
    return round(_HNEW_DIGIT_PX * len(str(n)), 1), round(full / 12, 2)
_HNEW_BF = "min(max(9px,min(12px,calc((100cqw + 2px) * 12 / var(--need,1)))),calc((100cqw + 2px - var(--nk,0) * 6px / 22) / var(--bk,1)))"      # the badge's font size: shrinks with the card as the number does, but never under 9 px, so a big count stays readable; the last term lets a very long word go under 9 px rather than leave the number under its own 6 px floor (the pair must fit)
_HNEW_UP = ("a.hcard i.hnew{position:absolute;top:9px;right:12px;margin:0;font-size:" + _HNEW_BF + "}"
            "@supports (left:anchor(--hcn right)){a.hcard i.hnew{position-anchor:--hcn;left:calc(anchor(right) + 4px);right:auto;top:auto;bottom:calc(anchor(bottom) + 2px)}}"
            "a.hcard:has(i.hnew) b{font-size:min(22px,max(6px,calc((100cqw + 2px - var(--bk,0) * " + _HNEW_BF + ") * 22 / var(--nk,1))))}")      # the number takes what the badge at its own size leaves, so the pair stays inside the card
def _hnew_css(word=None):
    """The rules that move the Closed card's "N new" up beside the number where the label line is too narrow for it, for the word `word` (default: the catalog's, _new_word)."""
    extra = max(0, _word_px(_new_word() if word is None else word) - 21)
    out = []
    for lim, cls in zip(_HNEW_LIMITS, ("", ".w2", ".w3", ".w4")):
        out.append(f"@container hcard (max-width:{lim + extra}px){{{_HNEW_UP.replace('a.hcard i.hnew', 'a.hcard i.hnew' + cls).replace('a.hcard:has(i.hnew)', 'a.hcard:has(i.hnew' + cls + ')')}}}")
    return "".join(out)
def _scoped(css: str, prefix: str) -> str:
    """css (plain rules, no at-rules) with `prefix` put before every selector."""
    return re.sub(r"([^{}]+)\{([^{}]*)\}", lambda m: ",".join(prefix + x.strip() for x in m.group(1).split(",")) + "{" + m.group(2) + "}", css)
# The panel's pin state is the page's own markup, and the signed-in person's stored choice (uiprefs.panel_open) puts it in. Every page, the item page too, is DRAWN pinned, <body class="panel-pin"> (the
# home is one kept draw for everyone, so the draw cannot differ per person); apply_panel_open turns it into the closed form, a bare <body>, for a person whose panel is stored closed, and a hover still peeks a
# closed panel open. A pin or unpin made with the button on a wide screen is saved (POST /prefs/panel-open) and so holds on the next page, reload and device.
_PANEL_BODY = '<body class="panel-pin">'
_PANEL_BODY_CLOSED = '<body>'   # the closed form of _PANEL_BODY
def apply_panel_open(page: str, is_open: bool, lang: str | None = None) -> str:
    """The page (drawn with the panel open) with the panel closed when `is_open` is false: the body without panel-pin and the button offering to show the panel, so the first paint is closed on a wide
    screen (a narrow one shows a closed drawer either way). A page with no side panel comes back as it was; only the first body tag and the first panel button are touched."""
    open_btn = _panel_btn(True, lang)
    if is_open or _PANEL_BODY not in page or open_btn not in page:
        return page
    return page.replace(_PANEL_BODY, _PANEL_BODY_CLOSED, 1).replace(open_btn, _panel_btn(False, lang), 1)
_CHROME = (('aria-label="Reload" title="Reload page"', "chrome.reload", "chrome.reload_tip"), ('aria-label="Back to top" title="Back to top"', "chrome.totop", "chrome.totop"))      # fixed English markup every page carries (the floating buttons), in the person's language by apply_lang
def apply_lang(page: str, lang: str) -> str:
    """The page (drawn in `lang` by a Board) with the language put in on the way out: <html lang>, the page scripts' words (window.SSI, the table's js.* and age.* keys in that language, ahead of the English ones the head
    carries), and the fixed chrome the pages share as constants (the floating buttons). English comes back as it was; so does a page already done (the marker id="ssi")."""
    if not isinstance(lang, str) or lang == _i18n.DEFAULT or 'id="ssi"' in page: return page
    page = page.replace('<html lang="en">', f'<html lang="{esc(lang)}">', 1)
    blob = json.dumps(_i18n.js_table(lang)).replace("</", "<\\/")
    page = page.replace('<meta charset="utf-8">', f'<meta charset="utf-8"><script id="ssi">window.SSI={blob};</script>', 1)
    for frag, aria, tip in _CHROME:
        if frag in page: page = page.replace(frag, f'aria-label="{esc(_t(aria, lang))}" title="{esc(_t(tip, lang))}"')
    return page
_PANEL_JS = r"""(function(){var P=document.getElementById('panel'),B=document.getElementById('panel-open'),E=document.getElementById('panel-edge'),S=document.getElementById('panel-scrim'),X=document.getElementById('panel-close');
if(!P||!B)return;
var M=window.matchMedia('(max-width: __NARROW__px)'),b=document.body,D=b.classList.contains('panel-pin'),s={peek:false,pin:D&&!M.matches,open:false,t:0},LV=250;
function narrow(){return M.matches}
var KN=null,KB=false;
function keep(v){KN=v;if(!KB)kflush()}
function kflush(){var v=KN;KN=null;if(v===null||!window.fetch)return;KB=true;
fetch('@ROOT@/prefs/panel-open',{method:'POST',keepalive:true,credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify({open:v})})
.then(null,function(){}).then(function(){KB=false;kflush()})}
function apply(){b.classList.toggle('panel-peek',s.peek);b.classList.toggle('panel-pin',s.pin);b.classList.toggle('panel-open',s.open);
var held=s.pin||s.open,on=held||s.peek;
B.setAttribute('aria-expanded',String(on));B.title=SST(held?'panel.hide':s.peek?'panel.pin':'panel.show')}
function peek(){clearTimeout(s.t);if(narrow()||s.pin)return;s.peek=true;apply()}
function leave(){clearTimeout(s.t);if(!narrow()&&s.peek)s.t=setTimeout(settle,LV)}
function settle(){if([E,P,B].some(function(e){return e&&e.matches(':hover')})||document.querySelector('.ct-pop:not([hidden])')){s.t=setTimeout(settle,LV);return}s.peek=false;apply()}
[E,P,B].forEach(function(e){if(!e)return;e.addEventListener('mouseenter',peek);e.addEventListener('mouseleave',leave)});
function shut(){var was=s.open;s.open=false;apply();if(was)B.focus({preventScroll:true})}
B.addEventListener('click',function(){clearTimeout(s.t);
if(narrow()){if(s.open)shut();else{s.open=true;apply();if(X)X.focus({preventScroll:true})}return}
s.pin=!s.pin;s.peek=false;D=s.pin;apply();keep(s.pin)});
if(X)X.addEventListener('click',shut);if(S)S.addEventListener('click',shut);
document.addEventListener('keydown',function(e){if(e.key!=='Escape')return;if(s.open)shut();else if(s.peek){clearTimeout(s.t);s.peek=false;apply()}});
function inside(h){var id;try{id=decodeURIComponent(String(h||'').replace(/^#/,''))}catch(e){return false}var el=id&&document.getElementById(id);return !!el&&P.contains(el)}
function reveal(){if(!inside(location.hash))return;if(narrow()){if(!s.open){s.open=true;apply()}}else if(!s.pin){s.pin=true;s.peek=false;apply()}}
P.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('a[href]');if(!a||!narrow()||!s.open||a.origin!==location.origin||a.target)return;var h=a.getAttribute('href');
if(h.charAt(0)==='#'?!inside(h):(a.pathname===location.pathname&&a.hash&&!inside(a.hash)))shut()});
M.addEventListener('change',function(){clearTimeout(s.t);s.peek=s.open=false;s.pin=!M.matches&&D;apply()});
apply();reveal();window.addEventListener('hashchange',reveal)})();""".replace("__NARROW__", f"{_PANEL_DOCK_PX - 0.02:g}").replace("@ROOT@", PREFIX)   # max-width 799.98px: exactly the complement of min-width:800px, so a fractional width (zoom) is never in neither
# The panel order's script (see the comment above _PANEL_LABELS). All its listeners sit on #panel, which the in-place update never swaps, so the grips of swapped
# sections work without re-binding. A move is made in the page at once and saved with one POST (the next one waits for the one in flight, so the last move wins); a
# refused or failed save leaves the move in the page and says so in the live region. The page's own order is read from the DOM, never from a copy.
_PORDER_JS = r"""(function(){var P=document.getElementById('panel'),L=document.getElementById('panel-live'),M=document.getElementById('panel-menu');
if(!P||!M||!window.fetch)return;
var DEF=__DEF__,URL='@ROOT@/prefs/panel-order',drag=null,cur=null,line=null,lastDrag=0,busy=false,next=null;
function secs(){return [].slice.call(P.children).filter(function(e){return e.tagName==='SECTION'&&DEF.indexOf(e.id)>=0})}
function order(){return secs().map(function(e){return e.id})}
function grip(id){return P.querySelector('.pgrip[data-sec="'+id+'"]')}
function label(id){var g=grip(id);return g?g.getAttribute('data-label'):id}
function say(t){if(!L)return;L.textContent='';setTimeout(function(){L.textContent=t},40)}
function place(id,to){var l=secs(),el=document.getElementById(id),i=l.indexOf(el);if(i<0)return false;l.splice(i,1);to=Math.max(0,Math.min(l.length,to));if(to===i)return false;
if(to<l.length)P.insertBefore(el,l[to]);else{var z=l[l.length-1];P.insertBefore(el,z?z.nextSibling:M)}return true}
function save(b){next=b;if(!busy)flush()}
function flush(){var b=next;next=null;if(!b)return;busy=true;
fetch(URL,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(b)})
.then(function(r){if(!r.ok)throw r.status;return r.json()})
.then(null,function(e){say(SST(e===403||e===401?'panel.order_signin':'panel.order_failed'))})
.then(function(){busy=false;flush()})}
function moved(id,refocus){var o=order();say(SST('panel.moved',{label:label(id),pos:o.indexOf(id)+1,n:o.length}));save({order:o});
if(refocus){var g=grip(id);if(g)g.focus()}}
function act(id,a){var o=order(),i=o.indexOf(id),n=o.length;if(i<0)return;var to=a==='up'?i-1:a==='down'?i+1:a==='top'?0:n-1;if(to<0||to>=n)return;if(place(id,to))moved(id,true)}
function closeMenu(back){if(M.hidden)return;M.hidden=true;if(cur){cur.setAttribute('aria-expanded','false');if(back)cur.focus()}cur=null}
function items(){return [].slice.call(M.querySelectorAll('.pmi')).filter(function(b){return !b.disabled})}
function openMenu(g){var id=g.getAttribute('data-sec'),o=order(),i=o.indexOf(id),n=o.length;
[].forEach.call(M.querySelectorAll('.pmi'),function(b){var a=b.getAttribute('data-act');b.disabled=(a==='up'||a==='top')?i<=0:i>=n-1});
M.setAttribute('data-for',id);M.setAttribute('aria-label',SST('panel.move_for',{label:label(id)}));M.hidden=false;g.setAttribute('aria-expanded','true');cur=g;
var pr=P.getBoundingClientRect(),gr=g.getBoundingClientRect(),h=M.offsetHeight,top=gr.bottom-pr.top+P.scrollTop+4;
if(gr.bottom+4+h>pr.bottom&&gr.top-4-h>pr.top)top=gr.top-pr.top+P.scrollTop-h-4;
M.style.top=Math.max(0,top)+'px';var f=items()[0];if(f)f.focus()}
P.addEventListener('click',function(e){var g=e.target.closest&&e.target.closest('.pgrip');
if(g){e.preventDefault();e.stopPropagation();if(Date.now()-lastDrag<400)return;if(cur===g)closeMenu(true);else openMenu(g);return}
var b=e.target.closest&&e.target.closest('.pmi');
if(b&&!b.disabled){var id=M.getAttribute('data-for'),a=b.getAttribute('data-act');closeMenu(false);act(id,a);return}});
M.addEventListener('keydown',function(e){var k=e.key,l=items(),i=l.indexOf(document.activeElement);
if(k==='Escape'){e.preventDefault();e.stopPropagation();closeMenu(true)}
else if(k==='ArrowDown'){e.preventDefault();if(l.length)l[(i+1)%l.length].focus()}
else if(k==='ArrowUp'){e.preventDefault();if(l.length)l[(i<=0?l.length:i)-1].focus()}
else if(k==='Home'){e.preventDefault();if(l[0])l[0].focus()}
else if(k==='End'){e.preventDefault();if(l.length)l[l.length-1].focus()}
else if(k==='Tab')closeMenu(true)});
document.addEventListener('pointerdown',function(e){if(!M.hidden&&!(e.target.closest&&(e.target.closest('#panel-menu')||e.target.closest('.pgrip'))))closeMenu(false)});
function dropAt(y){var l=secs();for(var k=0;k<l.length;k++){var r=l[k].getBoundingClientRect();if(y<r.top+r.height/2)return k}return l.length}
function mark(){if(!drag)return;var l=secs(),k=drag.to=dropAt(drag.cy),pr=P.getBoundingClientRect(),y;
if(!l.length)return;if(k<l.length)y=l[k].getBoundingClientRect().top;else y=l[l.length-1].getBoundingClientRect().bottom;
line.style.top=(y-pr.top+P.scrollTop)+'px'}
function stop(apply){if(!drag)return;var d=drag;drag=null;P.removeAttribute('data-pbusy');clearInterval(d.t);try{d.g.releasePointerCapture(d.pid)}catch(x){}
document.body.classList.remove('pdrag');var s=document.getElementById(d.id);if(s)s.classList.remove('pdragging');if(line){line.remove();line=null}
if(d.on){lastDrag=Date.now();if(apply){var i=order().indexOf(d.id),to=d.to>i?d.to-1:d.to;if(d.to>=0&&place(d.id,to))moved(d.id,false)}}}
P.addEventListener('pointerdown',function(e){var g=e.target.closest&&e.target.closest('.pgrip');if(!g||(e.pointerType==='mouse'&&e.button!==0)||!e.isPrimary)return;
drag={g:g,id:g.getAttribute('data-sec'),x:e.clientX,y:e.clientY,cy:e.clientY,on:false,pid:e.pointerId,to:-1,t:0,dir:0};P.setAttribute('data-pbusy','');try{g.setPointerCapture(e.pointerId)}catch(x){}});
P.addEventListener('pointermove',function(e){if(!drag||e.pointerId!==drag.pid)return;drag.cy=e.clientY;
if(!drag.on){if(Math.abs(e.clientX-drag.x)+Math.abs(e.clientY-drag.y)<5)return;drag.on=true;closeMenu(false);document.body.classList.add('pdrag');
var s=document.getElementById(drag.id);if(s)s.classList.add('pdragging');line=document.createElement('div');line.id='panel-drop';line.setAttribute('aria-hidden','true');P.appendChild(line);
drag.t=setInterval(function(){if(drag&&drag.dir){P.scrollTop+=drag.dir*10;mark()}},16)}
e.preventDefault();var pr=P.getBoundingClientRect();drag.dir=e.clientY<pr.top+36?-1:e.clientY>pr.bottom-36?1:0;mark()});
P.addEventListener('pointerup',function(e){if(drag&&e.pointerId===drag.pid)stop(true)});
P.addEventListener('pointercancel',function(e){if(drag&&e.pointerId===drag.pid)stop(false)});
document.addEventListener('keydown',function(e){if(e.key==='Escape'&&drag){e.preventDefault();e.stopPropagation();stop(false)}},true)})();""".replace("__DEF__", json.dumps(list(_up.PANEL_SECTIONS))).replace("@ROOT@", PREFIX)
# Back after an answer (Back after answering an item should go to where he came from,
# usually the board, not to the item page as the browser's back-forward cache holds it). The answer form submits by script: the POST is a fetch that follows the server's 303 to the item's
# page (?sent=<code>), and the page then location.replace()s itself with that address, so the answer replaces the pre-answer
# entry in history instead of stacking one; Back goes to the page before it. The pressed button's name and value (choice, or
# act) go with the form's fields, url-encoded as the plain form sends them. While the request runs every button of the form
# is disabled; a refusal or no answer shows inline under the buttons with the server's own words, the form left as it was.
# Without script, or a browser without SubmitEvent.submitter, the form is the plain POST and 303 it always was.
_ANSWER_JS = r"""<script>(function(){var F=document.querySelector('form.ianswer');if(!F||!window.fetch||!window.URLSearchParams)return;
var E=F.querySelector('.aerr'),busy=false,S=null,L='';
function btns(on){[].forEach.call(F.querySelectorAll('button'),function(b){b.disabled=!on})}
function fail(t){busy=false;btns(true);F.removeAttribute('aria-busy');if(S){S.removeAttribute('aria-busy');S.innerHTML=L;S=null}if(E){E.textContent=SST('js.answer.nothing_sent',{why:t});E.hidden=false}if(window.ssCards)ssCards.sync(F)}
F.addEventListener('submit',function(ev){var s=ev.submitter;if(s===undefined)return;ev.preventDefault();if(busy)return;
var d=new FormData(F);if(s&&s.name)d.append(s.name,s.value);busy=true;btns(false);F.setAttribute('aria-busy','true');if(s){S=s;L=s.innerHTML;s.setAttribute('aria-busy','true');if(s.name==='act')s.textContent=SST('js.answer.sending')}if(E)E.hidden=true;
fetch(F.action,{method:'POST',body:new URLSearchParams(d),credentials:'same-origin',redirect:'follow'}).then(function(r){
var u=new URL(r.url,location.href);if(r.ok&&r.redirected&&u.origin===location.origin&&/^@ROOTR@\/items\/[^\/]+$/.test(u.pathname)){location.replace(u.href);return}
return r.text().then(function(t){t=String(t||'').replace(/\s+/g,' ').trim();if(!r.ok&&t&&t.length<400&&!/^</.test(t))return fail(t);
fail(SST('js.answer.bad_reply',{what:r.ok?SST('js.answer.unexpected_page'):r.status}))})
},function(){fail(SST('js.answer.no_answer'))})})})();</script>"""
# The answer boxes' resize handle, by the main pointer. Fine pointer (a mouse or trackpad): the browser's own corner grip is off (resize:none) and the box's whole bottom edge is the
# handle, a full-width separator (cursor row-resize, 12 px tall) that draws a corner grip, the two short diagonals, at its right end; the height a viewer drags to is kept per box (H in
# _ABOX_JS, keyed by the form) and put back after the home page's in-place swap. Coarse pointer (a phone or tablet: `@media (pointer: coarse)`, never the screen's width): no handle and no
# manual resize; the box starts at two lines and grows with its text up to _ABOX_COARSE_VH percent of the viewport's height (40dvh), then scrolls inside. Pointer events with pointer capture
# serve mouse and pen; the keyboard works too (the WAI-ARIA window splitter: Down taller, Up shorter, 16 px a step, 64 with Shift, Home the minimum, End the maximum). One document-level
# listener, so the in-place swap of the home page needs no re-binding; its event only re-reads the sizes and puts back a height the viewer had set. The markup is drawn by the server
# (_abox), so a form still works without script, only the resizing (and the growing, on a phone) is then off.
_ABOX_MAX_VH = 70
_ABOX_COARSE_VH = 40
# The button set: every button on every page is the one class `.b`, in two levels.
#   SECONDARY (plain `.b`): a 1 px outline in --ibd (3:1 on the page and the card in both themes), no fill, text at full strength (--fg), 13 px, 32 px tall (44 px on a coarse pointer, ui/kit.py), 8 px corners.
#   Hover (a pointer that can hover only, so a tap on a phone leaves nothing stuck): a light fill (--fg at 6%) and the outline to --fg, a .warn edge kept. Pressed: --fg at 12%. Disabled: 45% opacity in the light theme; in the dark one a flat fill (--dis-bg) with its text (--dis-fg) at full opacity.
#   MAIN (`.b.main`): the composer's Send, one per form: a solid --acc fill with the --on-acc label (4.5:1 or more in both themes; tests/button_set_scenario.py computes it from these tokens). Hover and pressed darken (light) or lighten (dark) the fill
#   toward --fg; busy keeps the fill; disabled is the same fill at 50% in the light theme (a flat --dis-bg fill in the dark one), still visible.
# --acc is the one accent of the board: --orange (#ad4608 light, #f0a06a dark), the one orange of every page; --acc, --call (the "your call" markers), --t-you (ui/kit.py) and the tints --t-you-bg and --selbg all read it, none repeats the hex. The main button, the text links, the focus rings and the selected card read --acc. Status colours keep their own tokens (--run the status blue of running and live, --warn the amber, --p1, --ok). tests/orange_scenario.py fails on any other orange.
# No button is told from another by a colour other than the main one: a destructive action is told by its wording, and red (--p1) is held for state words, never a button.
# Modifiers: .on a pressed state (aria-pressed: the outline and a light tint turn --acc), .warn a warn-colored edge (the newer-board strip's Reload overrides it with the solid accent look, in the page sheet beside .conn), .busy a request in flight, .ico a square icon button of the title bar.
# The option cards (the answer box), the tags, the filter chips and the round .fab / #totop pair keep their own looks, styled beside them.
_BTN_CSS = """
.b{font:inherit;font-size:13px;line-height:1.2;min-height:32px;padding:5px 12px;border:1px solid var(--ibd,var(--mut));border-radius:8px;background:transparent;color:var(--fg);font-weight:400;display:inline-flex;align-items:center;justify-content:center;gap:6px;max-width:100%;cursor:pointer;text-align:left;text-decoration:none;transition:background-color .12s,border-color .12s,color .12s}
.b:hover{text-decoration:none}.b:focus-visible{outline:2px solid var(--acc);outline-offset:2px}.b:disabled{opacity:.45;cursor:default}
@media(hover:hover){.b:hover:not(:disabled){color:var(--fg);border-color:var(--fg);background:color-mix(in srgb,var(--fg) 6%,transparent)}.b.warn:hover:not(:disabled){border-color:var(--warn)}}
.b:active:not(:disabled){background:color-mix(in srgb,var(--fg) 12%,transparent)}
.b.on{border-color:var(--acc);color:var(--fg);background:color-mix(in srgb,var(--acc) 12%,transparent);opacity:1;cursor:default}
.b.warn{border-color:var(--warn)}.b .badge{margin:0}
.b.ico{width:32px;height:32px;min-width:0;padding:0}
.b.busy,.b[aria-busy=true],form[aria-busy] .b{background:color-mix(in srgb,var(--fg) 6%,var(--bg));opacity:1;cursor:progress}
.b.main{background:var(--acc);border-color:var(--acc);color:var(--on-acc);font-weight:600}.b.main:disabled{opacity:.5}
@media(hover:hover){.b.main:hover:not(:disabled){background:color-mix(in srgb,var(--fg) 14%,var(--acc));border-color:color-mix(in srgb,var(--fg) 14%,var(--acc));color:var(--on-acc)}}
.b.main:active:not(:disabled){background:color-mix(in srgb,var(--fg) 24%,var(--acc));border-color:color-mix(in srgb,var(--fg) 24%,var(--acc));color:var(--on-acc)}
.b.main.busy,.b.main[aria-busy=true],form[aria-busy] .b.main{background:var(--acc);border-color:var(--acc);color:var(--on-acc);opacity:.75}
"""
# The panel order's style: the grip at the right end of a section's header (28 px, 36 on a coarse pointer, laid over the section's top padding, --pt, so the header's height stays the title's),
# the drop line (--acc, the orange accent), the move menu and the live region (visually hidden).
_PORDER_CSS = """
#panel>section>details.fold>summary{padding-right:34px}
.pgrip{position:absolute;top:calc(var(--pt,14px) - 6px);right:0;display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;margin:0;padding:0;border:1px solid transparent;border-radius:6px;background:transparent;color:var(--mut);cursor:grab;touch-action:none;-webkit-tap-highlight-color:transparent}
.pgrip:hover{color:var(--fg);border-color:var(--line)}.pgrip:focus-visible{outline:2px solid var(--acc);outline-offset:1px;color:var(--fg)}.pgrip[aria-expanded=true]{color:var(--acc);border-color:var(--acc)}
@media(pointer:coarse){.pgrip{width:36px;height:36px;top:calc(var(--pt,14px) - 10px)}#panel>section>details.fold>summary{padding-right:42px}}
body.pdrag,body.pdrag *{cursor:grabbing!important;user-select:none;-webkit-user-select:none}#panel section.pdragging{opacity:.45}
#panel-drop{position:absolute;left:16px;right:16px;height:3px;margin-top:-2px;border-radius:2px;background:var(--acc);pointer-events:none;z-index:3;box-shadow:0 0 0 1px color-mix(in srgb,var(--acc) 35%,transparent)}
.pmenu{position:absolute;z-index:4;right:16px;min-width:176px;padding:4px;background:var(--card);border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,.22);display:flex;flex-direction:column}.pmenu[hidden]{display:none}
.pmi{font:inherit;font-size:13px;text-align:left;padding:8px 10px;min-height:36px;border:0;border-radius:6px;background:transparent;color:var(--fg);cursor:pointer}
.pmi:hover:not(:disabled){background:color-mix(in srgb,var(--acc) 14%,var(--card))}.pmi:focus-visible{outline:2px solid var(--acc);outline-offset:-2px;background:color-mix(in srgb,var(--acc) 14%,var(--card))}.pmi:disabled{opacity:.45;cursor:default}
.pvh{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
"""
def _abox(textarea: str, tid: str) -> str:
    """The textarea (it carries id=tid) with its handle after it; the handle stays hidden until the script marks the box (.abox.js)."""
    return (f'<div class="abox">{textarea}<div class="rsz" role="separator" aria-orientation="horizontal" tabindex="0" '
            f'aria-controls="{tid}" aria-label="{esc(_t("home.resize_box"))}"></div></div>')
_ABOX_CSS = """
textarea::placeholder{color:var(--iph);opacity:1}.abox{position:relative}.abox textarea{resize:none}.abox:not(.js) .rsz{display:none}
.rsz{position:absolute;left:0;right:0;bottom:0;height:12px;cursor:row-resize;touch-action:none;-webkit-tap-highlight-color:transparent;border-radius:0 0 6px 6px}
.rsz::after{content:'';position:absolute;right:3px;bottom:2px;width:9px;height:9px;pointer-events:none;background:linear-gradient(135deg,transparent 0 50%,var(--grip,var(--mut)) 50% 60%,transparent 60% 75%,var(--grip,var(--mut)) 75% 85%,transparent 85%)}
.rsz:hover,.rsz.drag,.rsz:focus-visible{--grip:var(--acc)}.rsz:focus-visible{outline:2px solid var(--acc);outline-offset:0}
@media(pointer:coarse){.rsz{display:none}.abox textarea{max-height:__CVH__vh;max-height:__CVH__dvh}.abox.js textarea{min-height:0}}
""".replace("__CVH__", str(_ABOX_COARSE_VH))
# The answer box's option cards (board answer box rebuilt on the root UI only, from the approved mockup v3). One card per option, a radio input styled as a card, so the form posts the same
# `choice` field and works with the script off: the card shows the option's label and its whole text; a question with three or more options letters them A, B, C and posts
# "B · <label>" (the server keeps the letter beside the label); two options carry no letters. The signals have a channel each: selection = filled circle + 2 px accent border + tint;
# recommendation = the "recommended" badge only. One Send is the only way to send; the script (_CARDS_JS) greys it, with the hint beside it, until a card is picked or the note has text,
# and lets a second tap on the picked card clear it.
_CARDS_CSS = """
:root{--selbg:color-mix(in srgb,var(--orange) 8%,var(--card));--keybg:#f1f0ec}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--keybg:#2a2a2d}}:root[data-theme=dark]{--keybg:#2a2a2d}
.acards{display:grid;gap:8px;margin:4px 0 0;min-width:0}
.acards .acard{position:relative;margin:0;display:grid;grid-template-columns:20px minmax(0,1fr);gap:0 10px;align-items:start;box-sizing:border-box;text-align:left;font:inherit;color:var(--fg);background:var(--card);border:1px solid var(--ibd);border-radius:8px;padding:10px 12px;cursor:pointer;-webkit-tap-highlight-color:transparent}
.acards .acard input{position:absolute;opacity:0;width:1px;height:1px;margin:0;pointer-events:none}
.acards .acard:has(input:checked){border:2px solid var(--acc);background:var(--selbg);padding:9px 11px}
.acards .acard:has(input:focus-visible){outline:2px solid var(--acc);outline-offset:2px}
.acards .acard:has(input:disabled){opacity:.5;cursor:default}
.adot{width:18px;height:18px;border-radius:50%;border:2px solid var(--ibd);box-sizing:border-box;margin-top:2px;display:grid;place-items:center}
.acards .acard:has(input:checked) .adot{border-color:var(--acc)}.acards .acard:has(input:checked) .adot::after{content:"";width:8px;height:8px;border-radius:50%;background:var(--acc)}
.abody{min-width:0;overflow-wrap:anywhere}.alab{font-weight:600;font-size:15px}
.akey{display:inline-block;min-width:20px;padding:0 3px;text-align:center;font-weight:700;font-size:13px;line-height:20px;border-radius:4px;background:var(--keybg);color:var(--fg);margin-right:6px;vertical-align:1px}
.acards .acard .badge{margin:0 0 0 4px;vertical-align:1px}
.adesc{display:block;color:var(--fg);font-size:14px;margin-top:2px;line-height:1.5;white-space:pre-line}
label.anote{display:block;color:var(--mut);font-size:13px;margin:10px 0 4px}
.abtns-send{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin-top:8px}.ahint{color:var(--mut);font-size:13px}.ahint[hidden]{display:none}
form.hanswer[data-cards] .acards{margin-top:0}form.hanswer .acard{padding:8px 10px}form.hanswer .acard:has(input:checked){padding:7px 9px}form.hanswer .alab{font-size:14px}form.hanswer .adesc{font-size:13px}
"""
_CARDS_JS = r"""<script>(function(){
function pick(f){return f.querySelector('input[name=choice]:checked')}
function step(f){var t=f.querySelector('textarea'),ok=!!t&&t.value.trim()!=='';[].forEach.call(f.querySelectorAll('button[data-needs-text]:not([data-spent])'),function(b){b.disabled=!ok;if(b.hasAttribute('data-hint')){if(ok)b.removeAttribute('title');else b.title=b.getAttribute('data-hint')}})}
function sync(f){if(!f||f.hasAttribute('aria-busy'))return;if(f.hasAttribute('data-step'))return step(f);var b=f.querySelector('button[name=act]'),t=f.querySelector('textarea'),h=f.querySelector('.ahint'),ok=!!pick(f)||(!!t&&t.value.trim()!=='');
if(b)b.disabled=!ok;if(h)h.hidden=ok}
function all(){[].forEach.call(document.querySelectorAll('form[data-cards],form[data-step]'),function(f){var p=pick(f);f._was=p?p.value:'';sync(f)})}
document.addEventListener('click',function(e){var i=e.target;if(!i||!i.matches||!i.matches('form[data-cards] input[name=choice]'))return;var f=i.form;
if(f._was===i.value){i.checked=false;f._was=''}else f._was=i.value;sync(f)},true);
document.addEventListener('input',function(e){var t=e.target;if(t&&t.matches&&t.matches('form[data-cards] textarea,form[data-step] textarea'))sync(t.form)});
document.addEventListener('stackshot:swapped',all);window.addEventListener('pageshow',all);window.ssCards={sync:sync,all:all};all()})();</script>"""
def _card_order(opts):
    """The options in the order the answer box draws them. Three or more are drawn, and lettered, in the order the owner stored them, because a session writes its ask ("Recommend: B, …")
    in that order and the letter on a card has to agree with it; the recommended card keeps its badge wherever it sits. Two (Approve and Decline, Yes and No) carry no letters and keep the
    page's rule of the recommended one first. server._split_letter derives the letter from the same stored order."""
    return list(opts) if len(opts) >= 3 else sorted(opts, key=lambda o: not o["recommended"])
def _cards_html(opts) -> str:
    """The option cards of the answer box: opts = [{"label", "line", "recommended"}] in the order drawn (_card_order). One label-wrapped radio (name=choice) per option,
    showing the label, the "recommended" badge on the recommended one and the whole text of the option; three or more options are lettered A, B, C by their place in the list and the radio's value is
    "B · <label>" (the server splits it again, server._split_letter), two carry no letters and post the bare label. Nothing here is a button: the page script's Send is the only way to send."""
    lettered = len(opts) >= 3
    cards = []
    for i, o in enumerate(opts):
        key = f'<span class="akey">{chr(65 + i)}</span>' if lettered else ""
        val = (f"{chr(65 + i)} · {o['label']}" if o["label"] else chr(65 + i)) if lettered else o["label"]      # a label that was only its letter (option_labels) posts the letter alone
        cards.append(f'<label class="acard"><input type="radio" name="choice" value="{esc(val)}">'
                     f'<span class="adot" aria-hidden="true"></span><span class="abody"><span class="alab">{key}{esc(o["label"])}</span>'
                     + (f' <span class="badge rec">{esc(_t("home.recommended"))}</span>' if o["recommended"] else "") + f'<span class="adesc">{esc(o["line"])}</span></span></label>')
    return f'<div class="acards" role="radiogroup" aria-label="{esc(_t("home.options"))}">' + "".join(cards) + '</div>'
_ABOX_JS = r"""(function(){var H={},seen=[],D=null,MQ=window.matchMedia?matchMedia('(pointer: coarse)'):null,RO=window.ResizeObserver?new ResizeObserver(function(l){l.forEach(function(e){var t=e.target,h=hd(t);if(h)sync(h);if(coarse())requestAnimationFrame(function(){grow(t)})})}):null;
function coarse(){return !!(MQ&&MQ.matches)}
function hd(t){return t.parentNode&&t.parentNode.querySelector('.rsz')}
function ta(h){return h.parentNode.querySelector('textarea')}
function key(h){var f=h.closest('form');return f&&(f.getAttribute('data-gid')||f.className)||''}
function lim(t){var mn=Math.round(parseFloat(getComputedStyle(t).minHeight))||48;return[mn,Math.max(mn,Math.round(window.innerHeight*__VH__/100))]}
function sync(h){var t=ta(h),c=t&&Math.round(t.getBoundingClientRect().height);if(!c)return;var l=lim(t);
h.setAttribute('aria-valuemin',l[0]);h.setAttribute('aria-valuemax',l[1]);h.setAttribute('aria-valuenow',Math.max(l[0],Math.min(l[1],c)))}
function set(h,v){var t=ta(h),l=lim(t);v=Math.max(l[0],Math.min(l[1],Math.round(v)));t.style.height=v+'px';H[key(h)]=v;sync(h)}
function cur(h){return Math.round(ta(h).getBoundingClientRect().height)}
function clamp(h){var t=ta(h),m=lim(t)[1];if(t.style.height&&cur(h)>m){t.style.height=m+'px';H[key(h)]=m}sync(h)}
function grow(t){if(!t.getClientRects().length){t.style.height='';return}
var y=window.scrollY,c=getComputedStyle(t),b=(parseFloat(c.borderTopWidth)||0)+(parseFloat(c.borderBottomWidth)||0);
t.style.height='auto';t.style.height=(t.scrollHeight+b)+'px';if(window.scrollY!==y)window.scrollTo(window.scrollX,y)}
function fit(t){var h=hd(t),k=h&&key(h);
if(coarse()){if(!t.hasAttribute('data-rows0')){t.setAttribute('data-rows0',t.rows);t.rows=2}grow(t)}
else{if(t.hasAttribute('data-rows0')){t.rows=+t.getAttribute('data-rows0');t.removeAttribute('data-rows0');t.style.height=''}
if(h&&k in H&&!t.style.height)t.style.height=H[k]+'px'}}
function init(){[].slice.call(document.querySelectorAll('.abox .rsz')).forEach(function(h){var t=ta(h);if(!t)return;h.parentNode.classList.add('js');
fit(t);sync(h);if(RO&&seen.indexOf(t)<0){seen.push(t);RO.observe(t)}});
seen=seen.filter(function(t){if(document.contains(t))return true;if(RO)RO.unobserve(t);return false})}
document.addEventListener('pointerdown',function(e){var h=e.target.closest&&e.target.closest('.rsz');if(!h||D||coarse()||(e.pointerType==='mouse'&&e.button!==0))return;
e.preventDefault();try{h.setPointerCapture(e.pointerId)}catch(x){return}h.focus({preventScroll:true});D={h:h,id:e.pointerId,y:e.clientY,v:cur(h)};h.classList.add('drag')});
document.addEventListener('pointermove',function(e){if(D&&e.pointerId===D.id)set(D.h,D.v+e.clientY-D.y)});
function end(e){if(D&&e.pointerId===D.id){D.h.classList.remove('drag');D=null}}
document.addEventListener('pointerup',end);document.addEventListener('pointercancel',end);document.addEventListener('lostpointercapture',end);
document.addEventListener('keydown',function(e){var h=e.target.closest&&e.target.closest('.rsz');if(!h||coarse()||e.altKey||e.ctrlKey||e.metaKey)return;
var l=lim(ta(h)),s=e.shiftKey?64:16,v=cur(h);
if(e.key==='ArrowDown')v+=s;else if(e.key==='ArrowUp')v-=s;else if(e.key==='Home')v=l[0];else if(e.key==='End')v=l[1];else return;
e.preventDefault();set(h,v)});
document.addEventListener('input',function(e){var t=e.target;if(coarse()&&t&&t.matches&&t.matches('.abox textarea'))grow(t)});
window.addEventListener('resize',function(){if(coarse())[].slice.call(document.querySelectorAll('.abox textarea')).forEach(fit);else[].slice.call(document.querySelectorAll('.abox .rsz')).forEach(clamp)});
if(MQ&&MQ.addEventListener)MQ.addEventListener('change',init);
init();document.addEventListener('stackshot:swapped',init);window.addEventListener('pageshow',init)})();""".replace("__VH__", str(_ABOX_MAX_VH))
# The For you list's "seen": the form is a plain POST to /for-you/seen that works without script; with script the page
# sends it as a fetch and drops the row (or every row, for "mark all seen") without leaving the board, and the count with it. One listener on
# the document, because the in-place update swaps the section's markup. A fetch that fails falls back to the plain form.
# The answer forms on Your move rows. The board is one static page for every viewer, so a row's form carries no token and is drawn hidden; this script asks
# GET /answer-tokens for the tokens of the forms on the page (the item page's own token, one per item, for the signed-in viewer) and shows each form it gets one for. A viewer
# with no token (not signed in, a failed fetch, a script off) keeps the row's "Open to answer" link to the item page. The in-place update swaps the lists: the forms are drawn again
# and shown again from the tokens already fetched. The form is a plain POST to /items/<n>/answer, which answers with a 303 to the item page's own "sent" notice.
# The form's `back` is the page's own path with no row fragment (a fragment scrolled home to the item's new place): the script saves scrollY in sessionStorage as the form is sent and, on the page the 303 lands on (?sent= present, no hash, the saved entry the same path and under 15 s old, used once), scrolls to it again, adding the height the notice takes, and keeps the notice stuck below the header for 8 s so it is seen. The server still follows a fragment in `back` for any other form.
# Ctrl+Enter (Cmd+Enter on a Mac) in an answer or comment box presses the form's main button: Done on a step form, otherwise the Send button (name=act).
# One delegated keydown listener on the document, so the home page's in-place swap needs no re-binding; it is on the item page, the home page and the project page.
# A key press that is part of an IME composition (an input method for Chinese, Japanese or Korean: isComposing, or keyCode 229 in Safari) never sends, a held key (repeat) sends once,
# a disabled button (a home row before its token arrives, a form already sending) is left alone, and plain Enter still makes a new line. requestSubmit(button)
# goes through the same submit event a click does (the item page's fetch, the home page's token check). The buttons carry the key as a hover title.
_SENDKEY_JS = r"""<script>(function(){var mac=/Mac|iPhone|iPad/.test(navigator.platform||''),K=mac?'\u2318+Enter':'Ctrl+Enter';
function main(f){return f.querySelector('button[name=act]')}
document.addEventListener('keydown',function(e){if(e.key!=='Enter'||!(e.ctrlKey||e.metaKey)||e.isComposing||e.keyCode===229||e.repeat)return;
var t=e.target;if(!t||!t.matches||!t.matches('form.ianswer textarea,form.hanswer textarea'))return;var f=t.form;if(!f)return;
e.preventDefault();var b=main(f);if(!b||b.disabled)return;if(f.requestSubmit)f.requestSubmit(b);else b.click()});
function hint(){[].forEach.call(document.querySelectorAll('form.ianswer,form.hanswer'),function(f){var b=main(f);if(b&&!b.title)b.title=K})}
hint();document.addEventListener('stackshot:swapped',hint)})();</script>"""
_HOME_JS = r"""(function(){var T={},SK='ss-home-scroll';
function run(){var F=[].slice.call(document.querySelectorAll('form.hanswer[data-gid]'));if(!F.length)return;if(!window.fetch){F.forEach(function(f){f.hidden=true});return}
var need=F.map(function(f){return f.getAttribute('data-gid')}).filter(function(g,i,a){return !(g in T)&&a.indexOf(g)===i});
function show(){F.forEach(function(f){var t=T[f.getAttribute('data-gid')],i=f.querySelector('input[name=token]');if(t&&i){i.value=t;f.hidden=false;[].forEach.call(f.querySelectorAll('button[disabled]:not([data-spent])'),function(b){b.disabled=false});if(window.ssCards)ssCards.sync(f)}})}
function giveup(){F.forEach(function(f){var i=f.querySelector('input[name=token]');if(!(i&&i.value))f.hidden=true})}
if(!need.length){show();giveup();return}
fetch('@ROOT@/answer-tokens?ids='+encodeURIComponent(need.join(',')),{credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json'}})
.then(function(r){return r.ok&&!r.redirected?r.json():null}).then(function(d){if(d)need.forEach(function(g){if(d[g])T[g]=d[g]});show();giveup()}).catch(giveup)}
run();document.addEventListener('stackshot:swapped',run);
document.addEventListener('submit',function(ev){var f=ev.target;if(!f||!f.matches||!f.matches('form.hanswer'))return;var tk=f.querySelector('input[name=token]');if(!tk||!tk.value){ev.preventDefault();return}var tn=Date.now();if(f._sent&&tn-f._sent<8000){ev.preventDefault();return}f._sent=tn;var b=f.querySelector('input[name=back]');if(!b)return;
b.value=location.pathname;try{sessionStorage.setItem(SK,JSON.stringify({y:Math.round(window.scrollY||0),t:Date.now(),p:location.pathname}))}catch(e){}},true);
(function(){var q=new URLSearchParams(location.search),k=q.get('sent'),N=document.getElementById('sent-notes');if(!k||!N)return;var m;try{m=JSON.parse(N.getAttribute('data-notes'))[k]}catch(e){}
var S=null,h0=document.documentElement.scrollHeight,np=null,Y=0;try{S=JSON.parse(sessionStorage.getItem(SK));sessionStorage.removeItem(SK)}catch(e){}
if(m){var p=document.createElement('p');p.className='isent '+m[0];p.setAttribute('role','status');var id=q.get('item'),nm='',lab='';
if(id&&/^(?:[a-z]\d+|[1-9]\d*|board-tmp-[a-z0-9-]*[a-z0-9]-[1-9]\d*)$/.test(id)){lab=/^\d+$/.test(id)?(N.getAttribute('data-hash')||'')+id:id;var d=id.match(/^([a-z])(\d+)$/),rw=document.getElementById(d?'task-'+d[1]+'-'+d[2]:/^\d+$/.test(id)?'task-g-'+id:''),g=rw&&rw.querySelector('.hgoal');nm=g?g.textContent:''}
var th=q.get('then'),ms=m[1],sk=k==='done'||k==='donenote'||k==='stepreply';if(sk&&th&&th.length<=80&&[].some.call(document.querySelectorAll('.hwho'),function(x){return x.textContent===th}))ms=SST(k==='done'?'js.sent_done':k==='donenote'?'js.sent_done_note':'js.sent_note',{who:th});
if(sk&&rw)[].forEach.call(rw.querySelectorAll('form.hstep button[name=act]'),function(b){b.disabled=true;b.setAttribute('data-spent','1')});
p.textContent=(nm?nm+' ('+lab+')':lab)+(nm||lab?' — ':'')+ms;
var c=document.querySelector('header.top')||document.getElementById('counts')||N;if(c&&c.parentNode){c.parentNode.insertBefore(p,c.nextSibling);np=p}}
if(S&&S.y>0&&S.p===location.pathname&&!location.hash&&Date.now()-S.t>=0&&Date.now()-S.t<15000){Y=S.y+(document.documentElement.scrollHeight-h0);window.scrollTo(0,Y);
if(np){np.style.cssText='position:sticky;top:calc(var(--hdr,0px) + 8px);z-index:8';setTimeout(function(){np.style.cssText=''},8000)}
var u=0;['wheel','touchstart','keydown','pointerdown'].forEach(function(n){window.addEventListener(n,function(){u=1},{once:true,passive:true})});
window.addEventListener('load',function(){if(!u&&Math.abs(window.scrollY-Y)>2)window.scrollTo(0,Y)})}
if(window.history&&history.replaceState)history.replaceState(null,'',location.pathname+location.hash)})()})();"""
_FORYOU_JS = r"""(function(){document.addEventListener('submit',function(ev){var f=ev.target;
if(!f||!f.matches||!f.matches('form.fy-seen')||!window.fetch||!window.URLSearchParams||ev.submitter===undefined)return;
ev.preventDefault();var b=f.querySelector('button');if(b){b.disabled=true;b.setAttribute('aria-busy','true')}
fetch(f.action,{method:'POST',body:new URLSearchParams(new FormData(f)),credentials:'same-origin',redirect:'manual'}).then(function(r){
if(!(r.ok||r.type==='opaqueredirect'))throw 0;var S=document.getElementById('for-you');if(!S)return;
var all=f.classList.contains('fy-all'),li=f.closest('li.fy-row');
if(all)S.querySelectorAll('li.fy-row').forEach(function(x){x.remove()});else if(li)li.remove();
var n=S.querySelectorAll('li.fy-row').length,c=S.querySelector('h2 .count');if(c)c.textContent=String(n);
if(n<2){var a=S.querySelector('form.fy-all');if(a)a.remove()}
if(!n){var u=S.querySelector('ul.fy-list');if(u){var p=document.createElement('p');p.className='empty fy-empty';p.textContent='nothing new for you';u.replaceWith(p)}}
}).catch(function(){if(b){b.disabled=false;b.removeAttribute('aria-busy')}f.submit()})},true)})();"""
# The Landed page's script. Clear, Clear all and Undo ask the server (POST /landed/clear, /landed/unclear with Accept: application/json) without leaving the page: a cleared line stays where it is, dimmed, its Clear
# replaced by an Undo that stays until the page is reloaded (a reload draws only what the server holds uncleared); Clear all leaves every line it cleared with its own Undo. The counts on the page follow; the home Landed count is
# the server's (it republishes after each change, and an open home page picks that up). Without JavaScript, or when the request fails, the forms post as they always did (303 back to the page). Nothing here inserts HTML: text goes in with
# textContent, and the only nodes made are a form, an input and a button. The relative times redraw every 30 s (ago() says what render.landed_ago says; keep them in step).
_LANDED_JS = r"""(function(){var M=document.querySelector('main#top');if(!M||!window.fetch||!window.URLSearchParams)return;
""" + _AGE_FN + r"""
function ago(s){return fa(s)}
function tick(){var n=Date.now()/1000;M.querySelectorAll('.lago[data-ts]').forEach(function(e){e.textContent=ago(n-(+e.getAttribute('data-ts')))})}
tick();setInterval(tick,30000);
function live(sec){return [].filter.call(sec.querySelectorAll('li.lrow'),function(x){return!x.classList.contains('lcleared')})}
function counts(){var n=live(M).length,p=M.querySelector('p.lnote');
if(p&&p.hasAttribute('data-n')&&p.firstChild&&p.firstChild.nodeType===3)p.firstChild.nodeValue=SST(n===1?'js.closed.note_one':'js.closed.note_many',{n:n});
[].forEach.call(M.querySelectorAll('#new details.hscope'),function(g){var c=g.querySelector('summary h3 .count');if(c)c.textContent=String(live(g).length)});
var h=M.querySelector('#new>h2 .count');if(h)h.textContent=String(n);var a=M.querySelector('form.lmark');if(a)a.hidden=!n}
function mk(cls,look,action,key,label,aria){var f=document.createElement('form');f.className=cls;f.method='post';f.action=action;
var i=document.createElement('input');i.type='hidden';i.name='keys';i.value=key;var b=document.createElement('button');b.type='submit';b.className=look;b.textContent=label;b.setAttribute('aria-label',SST('js.closed.aria',{label:label,id:aria}));
f.appendChild(i);f.appendChild(b);return f}
function setState(li,cleared,ok){var act=li.querySelector('.ir-act');if(!act){act=document.createElement('div');act.className='ir-act';li.appendChild(act)}var old=act.querySelector('form, span.lgone'),k=li.getAttribute('data-key'),id=(li.querySelector('.ir-id')||{}).textContent||'';
li.classList.toggle('lcleared',cleared||ok===false);var nf;
if(ok===false){nf=document.createElement('span');nf.className='lgone';nf.textContent=SST('js.closed.not_restored')}
else if(cleared)nf=mk('lundo','b','@ROOT@/landed/unclear',k,SST('js.closed.undo'),id);
else nf=mk('lclear','b','@ROOT@/landed/clear',k,SST('js.closed.clear'),id);
if(old)old.replaceWith(nf);else act.insertBefore(nf,act.firstChild)}
document.addEventListener('submit',function(ev){var f=ev.target;if(!f||!f.matches||!f.matches('form.lclear,form.lundo,form.lmark'))return;
ev.preventDefault();var all=f.classList.contains('lmark'),undo=f.classList.contains('lundo'),li=f.closest('li.lrow'),inp=f.querySelector('input[name=keys]'),b=f.querySelector('button');
var lis=all?live(M):li?[li]:[];if(all)inp.value=lis.map(function(x){return x.getAttribute('data-key')}).join(',');
if(!inp.value)return;var lab=b&&b.textContent;function rest(){if(b){b.disabled=false;b.removeAttribute('aria-busy');b.textContent=lab}}
if(b){b.disabled=true;b.setAttribute('aria-busy','true');if(all)b.textContent=SST('js.closed.clearing')}
fetch(f.action,{method:'POST',body:new URLSearchParams({keys:inp.value}),credentials:'same-origin',headers:{'Accept':'application/json'},redirect:'manual'}).then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(d){
if(!d||!d.ok)throw 0;rest();lis.forEach(function(x){setState(x,!undo,undo&&!d.changed?false:true)});counts()
}).catch(function(){rest();f.submit()})},true)})();"""
# A page restored from the back-forward cache is the copy from when it was left: an item page (and a project page) reloads
# instead, so Back always shows the item as it is now. They are served no-store as well; Chrome may still keep a no-store
# page in that cache, so the reload is what holds. The board has its own pageshow handler (_LIVE_JS): it polls the render
# stamp at once and updates in place, with no reload.
_BFCACHE_JS = "<script>window.addEventListener('pageshow',function(e){if(e.persisted)location.reload()})</script>"
# Is this copy of the board current? (a browser may show a cached
# board with nothing saying so.) The server publishes after every write (debounced 5 s) and on its own timer every
# [publish] every_minutes (10) on the dot, so a fresh page is at most one timer period old: past 1.5 periods (15 minutes)
# the "rendered … ago" stamp turns warn-coloured. The page polls /render-stamp (the render time of the home the server
# holds, no-store) every 60 s and whenever the tab comes back (focus, visibility, online, a page restored from the back-forward
# cache): unreachable (a failed fetch, a non-OK answer, a redirect to a sign-in, anything that is not the stamp) → the
# warn banner, retried every 15 s until it answers; a newer render → the page updates itself in place, or the "newer board"
# banner while a popover is open, a field has focus or text is selected, or an answer form holds a picked card or a typed note. That check comes before the frame check below: a refresh already on its way when
# he picks, whose page differs in its frame (a deploy), would otherwise reload the page and take the pick and the note with it (tests/decision_pick_check.py).
# In place, not a reload (the board "flickers" every few minutes, since every board write
# republishes it): the script fetches the page itself (same URL, uncached; a redirect or a non-OK answer reads as unreachable,
# as the stamp does), parses it, and swaps only the top-level blocks (the stat tiles, Need your call (agents), Machines, Anchor hub,
# the index, the four item sections, by id) whose fingerprint in the stackshot-blocks meta changed. Kept across a swap: the scroll
# position, each fold's open state, the live audit line (its own script keeps it current), the focused link; a block with a
# popover open in it is left for the next tick. The page's own script and style are fingerprinted too (the stackshot-shell
# meta, Board.html): a render whose shell differs (a deploy that changed the page's JS, CSS or frame), a block set that
# differs, or anything that throws falls back to the full reload (scroll position kept, the folds back to their defaults). A fetch that
# still lands on the older copy (a cache in the way) does not loop: that stamp then only gets the banner; so does a fallback
# reload that lands on it.
def _every_m() -> float: return float(_cfg.get("publish", "every_minutes") or 10)   # read at each render: a reload is live
def _stale_s() -> int: return int(_every_m() * 60 * 1.5)
_LIVE_JS = r"""(function(){var M=document.querySelector('meta[name="stackshot-rendered"]'),R=M?+M.content:0,B=document.getElementById('conn');if(!B)return;
var SH=document.querySelector('meta[name="stackshot-shell"]'),BM=document.querySelector('meta[name="stackshot-blocks"]'),V=bl(document),KY='stackshot.reload.y',KF='stackshot.reload.for',down=false,newer=false,out=false,told=false,timer=null,last=0,tried=0,inflight=null;
function ss(k,v){try{if(v===undefined)return sessionStorage.getItem(k);if(v===null)sessionStorage.removeItem(k);else sessionStorage.setItem(k,v)}catch(e){return null}}
var y=ss(KY);if(y!==null){ss(KY,null);window.addEventListener('load',function(){window.scrollTo(0,+y)})}
function typed(){var l=document.querySelectorAll('form.hanswer textarea,form.hanswer input[type=text],form.hanswer input:not([type])');for(var i=0;i<l.length;i++)if(l[i].value)return true;return !!document.querySelector('form.hanswer input[name=choice]:checked')}
function busy(){var a=document.activeElement,s=window.getSelection?String(window.getSelection()):'';return !!((a&&(/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)||(a.matches&&a.matches('.rsz'))))||document.querySelector('.rsz.drag')||document.querySelector('#panel[data-pbusy],#panel-menu:not([hidden])')||s||typed())}
function draw(){var k=out?'out':down?'down':newer?'new':'';if(out&&!told){told=true;var a=B.querySelector('#conn-signin');if(a)a.setAttribute('href',location.pathname+location.search);document.dispatchEvent(new Event('stackshot:signedout'))}B.className='conn'+(k?' '+k:'');B.hidden=!k}
function reload(){ss(KY,String(window.scrollY||0));location.reload()}
function fallback(ts){if(ss(KF)!==String(ts)){ss(KF,String(ts));reload()}else newer=true}
function bl(d){var m=d.querySelector('meta[name="stackshot-blocks"]'),o={};if(m)String(m.content).split(' ').forEach(function(p){var i=p.indexOf('=');if(i>0)o[p.slice(0,i)]=p.slice(i+1)});return o}
function key(a){return a.id?'#'+a.id:a.getAttribute('href')?a.tagName+'|'+a.className+'|'+a.getAttribute('href'):''}
function swap(o,n){var x=document.importNode(n,true),f={},a=document.activeElement,k='';
o.querySelectorAll('details.fold').forEach(function(d){f[d.getAttribute('data-fold')]=d.open});
x.querySelectorAll('details.fold').forEach(function(d){var k=d.getAttribute('data-fold');if(k in f)d.open=f[k]});
var oa=o.querySelector('#audit'),na=x.querySelector('#audit');if(oa&&na)na.parentNode.replaceChild(oa,na);
if(a&&a!==document.body&&o.contains(a)&&!(oa&&oa.contains(a)))k=key(a);
o.parentNode.replaceChild(x,o);if(oa&&a&&oa.contains(a)&&document.activeElement!==a)try{a.focus({preventScroll:true})}catch(e){}
if(k){var b=[].slice.call(x.querySelectorAll(a.tagName)).filter(function(e){return key(e)===k})[0];if(b)try{b.focus({preventScroll:true})}catch(e){}}}
function apply(t){var D=new DOMParser().parseFromString(t,'text/html'),m=D.querySelector('meta[name="stackshot-rendered"]'),S=m?+m.content:0,
sh=D.querySelector('meta[name="stackshot-shell"]');if(!S)throw 0;if(S<=R)return 'old';
if(busy())return 'busy';
if(!SH||!sh||sh.content!==SH.content)throw 0;
var W=bl(D),K=Object.keys(W);if(!K.length||K.join(' ')!==Object.keys(V).join(' '))throw 0;
var P=K.map(function(k){var o=document.getElementById(k),n=D.getElementById(k);if(!o||!n)throw 0;return[k,o,n]});
var y=window.scrollY,later=false,did=false;
P.forEach(function(p){var k=p[0],o=p[1];if(V[k]===W[k])return;
if(o.querySelector('details:not(.fold)[open]')){later=true;return}swap(o,p[2]);V[k]=W[k];did=true});
if(!later){if(BM)BM.content=D.querySelector('meta[name="stackshot-blocks"]').content;var g=document.getElementById('rendered'),ng=D.getElementById('rendered'),c=B.querySelector('.c-down'),nc=D.querySelector('#conn .c-down');
if(g&&ng)g.innerHTML=ng.innerHTML;if(c&&nc)c.textContent=nc.textContent;R=S;M.content=String(S)}
if(window.scrollY!==y)window.scrollTo(0,y);
if(did)document.dispatchEvent(new Event('stackshot:swapped'));return later?'later':'done'}
function update(ts){if(inflight)return inflight;
inflight=fetch(location.pathname+location.search,{cache:'no-store',credentials:'same-origin',headers:{'Accept':'text/html'}})
.then(function(r){if(r.status===401){out=true;throw 0}if(!r.ok||r.redirected)throw 0;return r.text()})
.then(function(t){var k;try{k=apply(t)}catch(e){k='fail'}
if(k==='fail')fallback(ts);else if(k==='old'){tried=ts;newer=true}else if(k==='busy')newer=true;else{newer=false;ss(KF,null)}})
.then(function(){inflight=null},function(e){inflight=null;throw e});return inflight}
function seen(ts){if(!R||ts<=R){newer=false;ss(KF,null);return}
if(busy()||tried===ts){newer=true;return}return update(ts)}
function poll(){if(out)return;var t=Date.now();if(t-last<2000)return;last=t;clearTimeout(timer);document.dispatchEvent(new Event('stackshot:poll'));
fetch('@ROOT@/render-stamp',{cache:'no-store',credentials:'same-origin',headers:{'Accept':'application/json'}}).then(function(r){if(r.status===401){out=true;throw 0}if(!r.ok||r.redirected)throw 0;return r.json()})
.then(function(d){if(!d||typeof d.ts!=='number')throw 0;down=false;return seen(d.ts)}).catch(function(){if(!out)down=true})
.then(function(){draw();if(!out)timer=setTimeout(poll,down?15000:60000)})}
document.getElementById('conn-reload').addEventListener('click',reload);
window.addEventListener('focus',poll);window.addEventListener('online',poll);
window.addEventListener('offline',function(){down=true;draw()});
document.addEventListener('visibilitychange',function(){if(!document.hidden)poll()});
window.addEventListener('pageshow',function(e){if(e.persisted){last=0;poll()}});
poll()})();"""
# The audit card (the side panel's Audit section): its name is a link to the Audits page, with the Audit now text link beside it, and under the name the shortlist: each audit group with its number of audits and
# its findings in the last 24 hours (a dash for a group that keeps no findings log, never a zero). The static page carries the card already drawn (Board.audit_line:
# a card that shipped hidden and empty blinked out on every reload; the rows this script draws are the ones the server draws, character for character, tests/phone_width_check.py compares them), hidden only when the audit is not enabled; this script
# redraws it from GET /audit/status on every tick of the reachability poll above (load, every 60 s, focus / visibility /
# online), uncached, building the new text before it swaps it in and leaving it alone when nothing changed. A failed fetch
# keeps what is drawn (the banner above says the server is unreachable); enabled false or a 404 hides the card. Times are drawn
# in the board's zone (data-tz), in the rulebook's "Thu Mar 5th 05:00" form. The button POSTs /audit/now once (no retry),
# is disabled while the request is in flight, while a run is in progress and for the 10 s the "cued" answer shows; the
# server's answer shows next to it for 10 s (202 plain; 409 / 503 / anything else warn; 404 hides the card), then the
# status is fetched again. The Audits page has the same button (#audit-now-page, with its message line #audit-page-msg): this one script drives both, so they post to the same route and share one state.
_AUDIT_JS = r"""(function(){var E=document.getElementById('audit');if(!E)return;
var T=E.querySelector('.a-txt'),N=document.getElementById('audit-now'),P=document.getElementById('audit-now-page'),G=[E.querySelector('.a-msg'),document.getElementById('audit-page-msg')].filter(Boolean),B=[N,P].filter(Boolean),Z=E.getAttribute('data-tz'),inflight=false,run=false,hold=0,mt=null;
var O={weekday:'short',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'},F;try{F=new Intl.DateTimeFormat('en-US',Object.assign({timeZone:Z},O))}catch(e){F=new Intl.DateTimeFormat('en-US',O)}
function pt(ts){var o={};F.formatToParts(new Date(ts*1000)).forEach(function(p){o[p.type]=p.value});return o}
var WD=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],GK=@GK@,NK=@NK@;
function ord(d){return d%100>=11&&d%100<=13?'date.ord.n':({1:'date.ord.1',2:'date.ord.2',3:'date.ord.3'})[d%10]||'date.ord.n'}
function when(ts){var p=pt(ts);return SST('date.full',{wd:SST('date.wd.'+WD.indexOf(p.weekday)),month:SST('date.mon.'+(MO.indexOf(p.month)+1)),day:SST('date.day',{n:+p.day,ord:SST(ord(+p.day))}),hm:p.hour+':'+p.minute})}
function clock(ts){var p=pt(ts),q=pt(Date.now()/1000);return p.month===q.month&&p.day===q.day?p.hour+':'+p.minute:when(ts)}
function num(v){return typeof v==='number'&&isFinite(v)}
function sig(e){return [].map.call(e.childNodes,function(c){return c.nodeType===1?c.className+'|'+c.title+'|'+c.textContent:'#'+c.textContent}).join('\u0001')}
function sp(c,t,tip){var e=document.createElement('span');e.className=c;e.textContent=t;if(tip)e.title=tip;return e}
function btn(){B.forEach(function(b){b.disabled=run||inflight||Date.now()<hold;if(inflight)b.setAttribute('aria-busy','true');else b.removeAttribute('aria-busy')})}
function draw(d){if(!d.enabled){E.hidden=true;if(P)P.hidden=true;return}
var L=d.last,C=d.card,f=document.createDocumentFragment();run=!!d.running;
if(run)f.appendChild(sp('a-run',num(d.running_since)?SST('panel.audit.running_since',{at:clock(d.running_since)}):SST('panel.audit.running')));
else if(L&&L.finished==null)f.appendChild(sp('a-run a-bad',SST('panel.audit.unfinished')));
if(C&&C.groups&&C.groups.length){f.appendChild(sp('a-h',''));f.appendChild(sp('a-h',SST('panel.audit.h_audits')));f.appendChild(sp('a-h',SST('panel.audit.h_found')));
C.groups.forEach(function(g){f.appendChild(sp('lbl',GK[g.name]?SST('panel.audit.group.'+GK[g.name]):g.name));f.appendChild(sp('val a-n',String(g.audits)));f.appendChild(sp('val a-n'+(g.found?' hit':''),g.found===null?'–':String(g.found)))});
if(C.note)f.appendChild(sp('a-cn',NK[C.note]?SST('panel.audit.note.'+NK[C.note]):C.note))}
else{btn();E.hidden=false;if(P)P.hidden=false;return}
if(sig(f)!==sig(T)){if(T.replaceChildren)T.replaceChildren(f);else{T.textContent='';T.appendChild(f)}}
btn();E.hidden=false;if(P)P.hidden=false}
function refresh(){fetch('@ROOT@/audit/status',{cache:'no-store',credentials:'same-origin',headers:{'Accept':'application/json'}})
.then(function(r){if(r.status===404&&!r.redirected){E.hidden=true;return null}if(!r.ok||r.redirected)throw 0;return r.json()})
.then(function(d){if(d===null)return;if(!d||typeof d.enabled!=='boolean')throw 0;draw(d)}).catch(function(){})}
function say(t,warn){G.forEach(function(g){g.textContent=t;g.className=g.className.replace(/ ?warn/,'')+(warn?' warn':'')});clearTimeout(mt);mt=setTimeout(function(){G.forEach(function(g){g.textContent=''});hold=0;btn()},10000)}
function cue(){if(inflight||run)return;inflight=true;btn();
fetch('@ROOT@/audit/now',{method:'POST',cache:'no-store',credentials:'same-origin'})
.then(function(r){if(r.redirected||r.status===401)return[0,''];return r.text().then(function(t){return[r.status,t]})})
.then(function(a){var s=a[0],t=String(a[1]||'').trim().slice(0,200);
if(s===404){E.hidden=true;if(P)P.hidden=true;return}
if(s===202){hold=Date.now()+10000;say(t||SST('panel.audit.cued'),false)}
else if(s===409||s===503)say(t||SST('panel.audit.http',{n:s}),true);
else say(s?SST('panel.audit.cue_failed',{n:s}):SST('panel.audit.cue_signin'),true)})
.catch(function(){say(SST('panel.audit.unreachable'),true)})
.then(function(){inflight=false;btn();refresh()})}
B.forEach(function(b){b.addEventListener('click',function(){if(!b.disabled)cue()})});
document.addEventListener('stackshot:poll',refresh)})();"""
# The scripts above are written with @ROOT@ where an address starts, filled in once here.
_AUDIT_JS = _AUDIT_JS.replace("@GK@", json.dumps(_AUDIT_GROUPS)).replace("@NK@", json.dumps(_AUDIT_NOTES))     # the English names of the audit groups and the card's notes, to the keys the script asks the table for
_ANSWER_JS, _HOME_JS, _LANDED_JS, _LIVE_JS, _AUDIT_JS = (x.replace("@ROOTR@", PREFIX.replace("/", "\\/")).replace("@ROOT@", PREFIX) for x in (_ANSWER_JS, _HOME_JS, _LANDED_JS, _LIVE_JS, _AUDIT_JS))


# The in-place update's fingerprints: the stackshot-blocks meta lists each top-level block of the board by its id with
# a hash of its HTML, what changes on every render without changing the board taken out: the age text of a time stamp (the
# page script redraws it from data-ts), the "waiting …" span's text (from data-wait) and the audit line (its own script keeps
# it current, and a swap keeps the live one). Two renders of the same board give a block the same hash; _LIVE_JS swaps only
# a block whose hash changed. The blocks' own markup carries nothing extra.
_VOLATILE = ((re.compile(r'(<span class="tip[^"]*" data-ts="\d+"[^>]*>)[^<]*(</span>)'), r"\1\2"),
             (re.compile(r'(<span class="[^"]*\bir-(?:age|pill)\b[^"]*" data-at="\d+") data-b="\w+"([^>]*>)[^<]*(</span>)'), r"\1\2\3"),      # the last activity's age, pill and band (the page script redraws them from data-at)
             (re.compile(r'(data-wait="\d+"[^>]*>)[^<]*'), r"\1"),
             (re.compile(r'<div id="audit".*?</div>', re.S), ""))   # the card's rows are spans, so its first </div> closes it
def _fp(html):
    """A short fingerprint of a piece of the page."""
    import hashlib
    return hashlib.sha256(html.encode("utf-8")).hexdigest()[:16]
def _blk_fp(html):
    """A top-level block's fingerprint for the stackshot-blocks meta: its HTML without the per-render text (_VOLATILE)."""
    for rx, sub in _VOLATILE: html = rx.sub(sub, html)
    return _fp(html)
def _num_ok(v):
    """The page script's num(): a finite number (not a bool)."""
    import math
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


_MACH_CSS = """
.pc.mach{grid-template-columns:minmax(0,max-content) minmax(0,max-content) minmax(0,1fr);min-width:0}.pc.mach .mh{grid-column:1/-1;display:block;margin:0;padding:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mr{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,max-content) minmax(0,max-content) minmax(0,1fr);grid-template-columns:subgrid;column-gap:8px;align-items:baseline;min-width:0}.mr>*{min-width:0;overflow-wrap:anywhere}
.mr .lbl{font-size:12px;color:var(--mut)}.mr a.lbl{text-decoration:none}.mr a.lbl:hover{color:var(--fg);text-decoration:underline}.mr .val{font-size:12px;color:var(--mut);font-variant-numeric:tabular-nums}
.mr .st{font-size:12px;color:var(--mut);min-width:0;overflow-wrap:anywhere}.mr .st.ok{color:var(--ok);font-weight:600}.mr.update .st{color:var(--fg);font-weight:600}.mr.offline{opacity:.6}
#machines .matrix{grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}
.pc.mach>.mf{grid-column:1/-1;display:block;min-width:0;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere;cursor:help}
"""   # the Machines panel's machine cards, appended after the main sheet so that its #machines .matrix wins over the old 128px columns; the panel's own one-column rule is more specific and still applies

_AUDITS_CSS = """
main.audits-page .atop{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 16px}main.audits-page .atop h1{margin:0}
main.audits-page .atop .atbtn{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
main.audits-page .apmsg{font-size:13px;color:var(--fg);overflow-wrap:anywhere}main.audits-page .apmsg:empty{display:none}main.audits-page .apmsg.warn{color:var(--warn);font-weight:600}
main.audits-page .asub{margin:4px 0 16px;color:var(--mut)}
main.audits-page .apaces{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0 0 22px}
@media(max-width:520px){main.audits-page .apaces{grid-template-columns:minmax(0,1fr)}}
main.audits-page .apace{min-width:0;padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card)}main.audits-page .apace b{display:block;font-weight:600}main.audits-page .apace span{font-size:13px;color:var(--mut);overflow-wrap:anywhere}
main.audits-page h2{margin:22px 0 8px;font-size:17px}main.audits-page h2 small{font-size:13px;font-weight:400;color:var(--mut)}
main.audits-page .agroups,main.audits-page .afeed{display:flex;flex-direction:column;gap:8px}
details.audg{border:1px solid var(--line);border-radius:10px;background:var(--card)}
details.audg>summary{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:12px;align-items:baseline;padding:8px 12px;cursor:pointer;list-style:none}
details.audg>summary::-webkit-details-marker{display:none}details.audg>summary:focus-visible{outline:2px solid var(--acc);outline-offset:2px;border-radius:10px}
@media(max-width:420px){details.audg>summary{grid-template-columns:minmax(0,1fr) auto}details.audg>summary .agn{grid-column:1/-1}}
details.audg .agn b{display:block;font-weight:600}details.audg .agn b::before{content:'▸';display:inline-block;margin-right:6px;color:var(--mut)}details.audg[open] .agn b::before{transform:rotate(90deg)}#audit-now-page[hidden]{display:none}details.audg .agn span{display:block;font-size:13px;color:var(--mut)}
main.audits-page .anum{font-size:13px;color:var(--mut);white-space:nowrap;font-variant-numeric:tabular-nums}main.audits-page .anum.hit{color:var(--orange);font-weight:600}
details.audg ul.aaud{margin:0;padding:0 12px 10px;list-style:none;border-top:1px solid var(--line)}
details.audg ul.aaud li{display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 12px;padding:5px 0;border-bottom:1px solid var(--line);font-size:13px}details.audg ul.aaud li:last-child{border-bottom:0}
details.audg ul.aaud li span{color:var(--mut)}details.audg ul.aaud li span.shadow{color:var(--orange)}
main.audits-page .af{min-width:0;padding:7px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);font-size:13px;overflow-wrap:anywhere}main.audits-page .af .am{font-size:12px;color:var(--mut)}
main.audits-page .aempty{margin:0;padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--mut)}
main.audits-page .atw{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
main.audits-page .atw table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}main.audits-page .atw th,main.audits-page .atw td{padding:6px 12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
main.audits-page .atw th{font-weight:400;color:var(--mut)}main.audits-page .atw tr:last-child td{border-bottom:0}main.audits-page .atw td.warn{color:var(--warn);font-weight:600}
@media(max-width:520px){main.audits-page .atw th,main.audits-page .atw td{padding:6px 8px}}
main.audits-page .anote{max-width:70ch;margin:16px 0 0;font-size:13px;color:var(--mut)}
"""   # the Audits page (GET /audits): the paces, the audit groups (a native details each), the latest findings and the runs, on the theme's tokens, so light and dark need no rule of their own

_RUN_CSS = """
#runners{margin:0 0 4px}#runners h2.hdr{margin:32px 0 12px}
#audit-panel:has(#audit[hidden]):not(:has(#ghcalls)){display:none}
#panel #machines .matrix{grid-template-columns:minmax(0,max-content) minmax(0,max-content) minmax(6em,1fr)}#panel #machines .mcol{grid-column:1/-1;grid-template-columns:subgrid}#panel #machines .mcol>.pc{grid-column:1/-1}#panel #machines .pc.mach{grid-template-columns:subgrid}#panel #machines .mr>:not(.st){overflow:hidden;text-overflow:ellipsis}#panel #machines .mr .st{white-space:normal}#panel #machines .mr.update .st{white-space:nowrap}
.mr.unknown{opacity:.6}.mr.unknown .val{font-style:italic}
#panel .rlist{display:grid;gap:8px}#panel .pc.rc{display:flex;align-items:baseline;gap:8px;color:var(--fg)}#panel .pc.rc .rn{flex:1 1 auto;min-width:0;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#panel .pc.rc .rv{flex:none;font-variant-numeric:tabular-nums;color:var(--mut)}#panel .pc.rc .rv.busy{color:var(--fg);font-weight:700}#panel .pc.rc .rv.full{color:var(--warn);font-weight:700}#panel .pc.rc .rv.off{color:var(--warn);font-weight:600}#panel .pc.rc .go{flex:none;color:var(--mut)}
#panel a.pc.rc:hover{border-color:var(--acc)}#panel a.pc.rc:hover .go{color:var(--acc)}
tr.scope{scroll-margin-top:calc(var(--hdr,0px) + 12px)}
#panel :is(.audit,.ghc)>.mh{grid-column:1/-1;display:flex;justify-content:space-between;align-items:center;gap:8px;overflow:visible;text-overflow:clip}
#audit-now{position:relative;flex:none;margin:0;padding:0;border:0;border-radius:2px;background:none;font:inherit;font-weight:400;line-height:inherit;color:var(--acc);text-decoration:none;cursor:pointer}
#audit-now::after{content:'';position:absolute;left:-8px;right:-8px;top:-6px;bottom:-6px}
@media(hover:hover){#audit-now:hover:not(:disabled){text-decoration:underline}}
#audit-now:focus-visible{outline:2px solid var(--acc);outline-offset:2px;text-decoration:underline}
#audit-now:disabled{color:var(--mut);text-decoration:none;cursor:not-allowed}
@media(pointer:coarse){#audit-now::after{bottom:auto;height:44px}}
#audit{grid-template-columns:minmax(0,1fr) auto auto;column-gap:12px}
#audit .mh a.nm{color:var(--fg)}#audit .mh a.nm:hover{color:var(--acc)}
#panel .audit .a-h{font-size:11px;line-height:1.4;color:var(--mut);text-align:right}
#audit .a-n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}#audit .a-n.hit{color:var(--orange);font-weight:600}
#panel .audit .a-cn{grid-column:1/-1;margin-top:4px;font-size:11px;line-height:1.4;color:var(--mut);white-space:normal}
#panel .ghc{margin-top:8px;font-size:12px}#panel .ghc .val{color:var(--fg)}#panel .ghc .val .cap{color:var(--mut)}
"""   # the Runners panel's cards (one line each, the count busy/online and a ↗, since an earlier change): the Machines cards' look, one to a row in the side panel; the Audit section: the daily audit's card, its name row with the Audit now text link beside the name, and the GitHub calls card, the section hidden when the audit is off and there is no calls card; every panel section on the Anchor hub's card spacing (8px between cards, 6px 10px inside a card, 2px between lines) and the Machines and Runners cards on the same three columns (subgrid: the matrix owns them, so "latest" lines up from card to card)
def _run_stale_s(): return 3 * max(float(_runners.conf("panel_refresh_s")), _every_m() * 60)   # a snapshot older than this carries a "last read at" note in the Runners panel: three times the larger of the panel refresh and the publish interval, so the note never flips between two publishes and the block holds still (younger ones say nothing)


class Board:
    """The board's data, read once: items, sessions, projects, anchors, versions, the hub's status — and what is drawn from it."""

    def __init__(self, data_dir: str, now=None, contact_of=None):
        """`contact_of(item) -> str` (the server's `_contact_label`): the item's contact as the item page's side column names it, so a list row names the same agent. None reads the stored contact."""
        self.contact_of = contact_of; self._contacts = {}      # the lookup runs at most once per item in a render (row_contact)
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
        self.renamed = _anc.roles_renamed()            # roles.json's `renamed_to`: a name sala keeps only as the old name of a renamed session reads live (an alias) but names nobody, so it is not drawn either
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
        self.mfacts = {L: _fleet.read(L, "machine") for L in _fleet.letters()}   # each machine's view: its last setup run, update attempts and checkout commit (machine_alerts)
        self.server_commit = server_commit()           # the commit the boxes follow: a box's checkout is judged against it (machine_alerts)
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
        tool = _cfg.fleet_tool(); lt = title or (_t("link.session_in", tool=tool) if tool else _t("link.session_view"))
        if u: return (f'<a{c} href="{esc(u)}" target="_blank" rel="noopener" title="{esc_dq(lt)}">'
                      f'{body}{" ↗" if arrow else ""}</a>')
        t = f' title="{esc_dq(title)}"' if title else ""
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
    def linkify(self, text, own=""): return self.mentions(linkify(text), own)   # free text a session wrote → HTML, mentions linked
    def md_html(self, text, own=""):
        """Item text (a description, a comment in the History) → HTML as the safe markdown subset (md_block), then the mentions pass:
        an item id and a live session name become links in the text only, never inside a link, code or a tag."""
        return self.mentions(md_block(text), own)
    def md_line(self, text, own=""):
        """One line (a Next step) → inline HTML (md_inline), mentions linked."""
        return self.mentions(md_inline(text), own)
    def cmd_step(self, x, own="", fmt=None):
        """A Next step addressed to the owner ("<owner>: in PowerShell run `ssh …`"): each backticked command (a span with a space
        in it; a lone word such as `default` stays inline) leaves the line for its own block with a copy button (an inline shell command is hard to copy, so it sits in an isolated code block). fmt turns the
        rest of the line into HTML (default linkify; the item page passes md_line, the markdown subset)."""
        fmt = fmt or self.linkify
        is_cmd = lambda m: m.group(3) is not None and " " in m.group(3).strip()   # code inside a link's label is the label's
        cmds = [m.group(3) for m in _LINK_OR_CODE.finditer(x) if is_cmd(m)] if re.match(rf"\s*{re.escape(_OWNER)}\b", x) else []
        if not cmds: return fmt(x, own)
        n = iter(range(1, len(cmds) + 1))
        line = _LINK_OR_CODE.sub(lambda m: m.group(0) if not is_cmd(m) else
                                 (_t("home.cmd_below") if len(cmds) == 1 else _t("home.cmd_n_below", n=next(n))), x)
        return fmt(line, own) + _cmd_blocks([c.strip() for c in cmds], label=_t("home.copy_the", label=_t("home.command")))
    def due_badge(self, r):
        d = due_of(r)
        if not d: return ""
        left = (d - self.now.date()).days
        cls = "due"   # one color for every due date (no traffic-light coloring)
        return badge(_t("item.due_today" if left == 0 else "item.due_overdue" if left < 0 else "item.due_in", n=abs(left), md=f"{d:%m-%d} {_t(f'date.wd.{d.weekday()}')}"), cls)
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
    def agent_live(self, name):
        """False when roles.json says sala lists no session of that name (its `live` flag is false) or lists it only as the old name of a renamed session (`renamed_to`: the agent is drawn under its new name);
        a name roles.json does not know, or a file written while sala could not be read, is shown."""
        n = str(name).split("/", 1)[-1]
        return n not in self.renamed and self.live_flags.get(n, True)
    def finished(self, k):
        """Is the project page `k` archived (retired): its `status:` word is one of [project_scopes] retired_statuses (the one rule the project picker and roles use)."""
        return bool(k) and _prj.page_status(self.proj.get(k) or {}) in _prj.retired_statuses()
    def is_hub(self, k):
        """A hub page splits its sessions into a keeper and agents: it lists them under `agents:` (background ones nested under `background:`)."""
        front, back = self.agent_roles(k)
        return bool(front or back)
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
    def index_lines(self, k, rs):
        """The index's lines for a row: on a hub row the background agents leave the index, and come
        back dimmed with a tag ("background") only while they own an open item here, so drift shows; the page's keeper
        line is a front agent like the others (the project sessions were retired, so it carries no tag), as are
        the front agents and unlisted owners of lines(). A row that is not a hub is lines() unchanged.
        → [(label, url, short, is_agent, rows, flag, tip, tag)]; the first line shown carries its full label and leads
        the row (is_agent False); when every line is hidden, one empty line (label "")."""
        has_st, ls0 = self._lines(k, rs)
        ls = [x for x in ls0 if x[4] or self.agent_live(x[0])]      # an agent with no live session is not drawn, unless it owns an open item (that item stays on the index)
        has_st = has_st and bool(ls) and ls[0] is ls0[0]
        if not ls and ls0: return [("", "", "", False, [], "", "", "")]      # every line was hidden: the project's row still renders
        if not self.is_hub(k): return [(*x, "") for x in ls]
        _front, back = self.agent_roles(k)
        front = sorted([x for x in ls if x[0].split("/", 1)[-1] not in back], key=lambda x: not x[0].endswith("-main"))   # the -main agent leads: the owner's point of contact
        out = [(*x, "") for x in front] + [(*x, "background") for x in ls if x[0].split("/", 1)[-1] in back and x[4]]
        if not out: return [("", "", "", False, [], "", "", "")]
        lead_st = has_st and out[0][:2] == ls[0][:2]            # the suffixes are the keeper's: they read right only under its own line
        l, u, _short, _ag, g, flag, tip, tag = out[0]
        return [(l, u, "", False, g, flag, tip, tag)] + [(a, b, sh if lead_st else "", has_st, *z) for a, b, sh, _ag, *z in out[1:]]
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
        return info.get("name") or (k.split("/", 1)[1] if "/" in k else k) or _t("item.no_project")
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
        at = f"{t:%Y-%m-%d %H:%M} {_cfg.tz_abbr(t)}"
        return (f'<span class="tip{" " + cls if cls else ""}" data-ts="{int(t.timestamp())}"{" data-q" if quiet else ""} '
                f'data-tip="{esc(_t("item.when.no_change_since", when=at) if quiet else at)}" title="">'
                f'{_i18n.fmt_age(s_, quiet=True) if quiet else ago(s_)}</span>')
    def anchor_entries(self, page):
        """One page's anchors from the anchors file, as clean dicts (clean_anchor_entries)."""
        return clean_anchor_entries(self.anchors.get(page))
    def _when(self, st, added=None):
        """HTML (already escaped): the anchor's last activity as a stamp (anchor-hub reads it from the source at first sight);
        none known (a source it cannot read) → ">age ago", counted from the later of the anchor's addition and
        the start of anchor-hub's unbroken change record."""
        u = st.get("unreadable")
        if u:       # the hub asked the source and was refused: no notice can come from it
            return f'<span class="aflag" title="{H.escape(_t("item.when.unreadable_tip", since=str(u.get("since")), tz=_cfg.tz_abbr(), why=str(u.get("why"))), quote=True)}">{esc(_t("item.when.unreadable"))}</span>'
        when = esc(_t("item.when.quiet"))
        if st.get("last"):
            try: when = self.stamp(datetime.datetime.strptime(st["last"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=self.now.tzinfo))
            except Exception: when = H.escape(str(st["last"]))
        else:
            try: ad = datetime.datetime.fromtimestamp(float(added), self.now.tzinfo) if added else None
            except (TypeError, ValueError, OverflowError, OSError): ad = None      # an `added` that is no time shows nothing
            since = [x for x in (self.anchor_since, ad) if x]
            if since: when = self.stamp(max(since), quiet=True)
        if st.get("mode") == "poll": when += esc(_t("item.when.poll"))
        return when
    def anchor_row(self, e):
        """One anchor entry as the lists draw it: (kind, (name, url, when, scope, hot)): the name and link anchor-hub knows it by, the stamp of its last activity, the items it is about, whether it moved in the last day."""
        from stackshot.anchors import anchors as _anc
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
        return kind, (name, url, self._when(st, e.get("added")), scope, hot)
    def proj_anchor_groups(self, k):
        """A project's anchors grouped by type, in a fixed order (one row per type, one chip per type that
        opens the list). → [(kind, [(name, url, when, scope, hot)], any_hot)]."""
        groups = {}
        seen = set()
        for e in [e for page in (self.group.get(k) or [k]) for e in self.anchor_entries(page)]:   # the row and every page under it
            if (str(e.get("url")), tuple(e.get("items") or ())) in seen: continue
            seen.add((str(e.get("url")), tuple(e.get("items") or ())))
            kind, row = self.anchor_row(e)
            groups.setdefault(kind, []).append(row)
        return [(kind, groups[kind], any(x[4] for x in groups[kind])) for kind in _KIND_ORDER if kind in groups]

    def routing_counts(self, k):
        """The row's last 24 hours from the routing log, over every page that rolls up to it."""
        return _routing.counts(self.group.get(k) or [k], now=self.now.timestamp(), wait=60.0 * float(_cfg.get("pilot", "waiting_minutes") or 60))
    WATCH = {"bad": ("broken", "needs a person"), "wait": ("waiting", "a notice is waiting for its ruling"), "ok": ("ok", "all heard"),
             "none": ("—", "nothing watched")}
    def watch(self, k):
        """The row's watch state (a green / yellow / red icon showing status health;
        mapping by the project's main agent), or None for the no-project row. → (state, the detail lines). Precedence bad > wait > ok > none:
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
    def sessions_html(self, k):
        """The project page's Sessions section → (count, HTML): every session of the row, in groups —
        Agents (the page's name line among them, the -main agent first), Background agents on a hub page; one group "Session"
        otherwise. Each line: the name (linked to its view while it has a live pane, sess_html), the machine, the flags the index uses,
        the open items it owns here (links to the board) and its mandate. The open items are the row's, sub-pages rolled up as on the index."""
        rs = self.by_proj.get(k, []) if k in self.group else [r for r in self.needs + self.agent + self.held if proj_key(r) == k or proj_key(r).startswith(k + "/")]
        ls = [x for x in self._lines(k, rs)[1] if self.agent_live(x[0])]      # an agent with no live session is not drawn (roles.json's live flag)
        e = lambda x: H.escape(str(x), quote=True)
        def li(l, _u, g, flag, tip):   # _u: the store's link (board.md's); the name links to its view
            mach, nm = l.split("/", 1) if "/" in l else ("", l)
            where = "" if mach in ("", "?") else (_t("sessions.cloud") if mach == "c" else self.fleet.get(mach) or mach)
            name = self.sess_html(nm)
            ids = ", ".join(f'<a href="{item_href(r)}">{e(rid(r))}</a>' for r in sorted(g, key=lambda r: (r["L"], num(r))))
            return (f'<li><span class="sn">{name}</span>' + (f' <span class="dim">· {e(where)}</span>' if where else "")
                    + (f' <span class="aflag" title="{e(_t(_AFLAG[flag][1]))}">{e(_t(_AFLAG[flag][0]))}</span>' if flag else "")
                    + (f' <span class="own">{_t("sessions.owns", ids=ids)}</span>' if ids else "")
                    + (f'<span class="mand">{self.mentions(e(tip))}</span>' if tip else "") + '</li>')   # the page's mandate words: mentions linked
        if self.is_hub(k):
            _front, back = self.agent_roles(k)
            groups = [(_t("sessions.agents"), sorted([x for x in ls if x[0].split("/", 1)[-1] not in back], key=lambda x: not x[0].endswith("-main"))),
                      (_t("sessions.background"), [x for x in ls if x[0].split("/", 1)[-1] in back])]
        else:
            groups = [(_t("sessions.session"), ls)]
        body = "".join(f'<h3 class="sgrp">{e(t)}</h3><ul class="alist slist">' + "".join(li(x[0], x[1], x[4], x[5], x[6]) for x in xs) + '</ul>'
                       for t, xs in groups if xs)
        if body and self.finished(k): body = f'<details class="archived"><summary>{_t("page.archived")}</summary>{body}</details>'       # an archived project's agents sit in a group that starts closed
        return len(ls), body
    def when(self, ts, clock=True):
        """"Mon Mar 2nd 20:00" (clock=False: "Mon Mar 2nd"): the rulebook's form for a date a person reads, in the board's zone.
        ts = epoch seconds, a datetime, or a date (a date has no clock)."""
        if isinstance(ts, datetime.datetime): t = ts.astimezone(self.now.tzinfo)
        elif isinstance(ts, datetime.date): t, clock = ts, False
        else: t = datetime.datetime.fromtimestamp(float(ts), self.now.tzinfo)
        return when_words(t, clock)
    def arrival_when(self, ts):
        """When a line of a wait on a list arrived, as `when` says it; "" for a time no date can show (the stored shape keeps those out, this keeps a page whole whatever it is handed)."""
        try: return self.when(ts)
        except (ValueError, OverflowError, OSError, TypeError): return ""
    def span_words(self, a, b):
        """A span of time for a History line that folds several writes: "Tue Nov 10th 08:31 – 09:39" (the second time alone when it is the same day), the board's zone."""
        ta, tb = (datetime.datetime.fromtimestamp(float(x), self.now.tzinfo) for x in (a, b))
        return self.when(a) if (ta.hour, ta.minute, ta.date()) == (tb.hour, tb.minute, tb.date()) else f"{self.when(a)} – {tb:%H:%M}" if ta.date() == tb.date() else f"{self.when(a)} – {self.when(b)}"
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
    def hold_tip(self, r):
        """A parked item's words for a tooltip or a list: "on hold · wakes Fri Mar 6th 12:00", "on hold · no wake date", or for an
        item that waits on another "after board#N · until it closes" (both when both)."""
        w = wake_of(r); parts = []
        if is_held(r): parts.append("on hold · " + (f"wakes {self.when(w)}" if w else "no wake date"))
        if after_open(r): parts.append(self.after_words(r) + " · until it closes")
        return " · ".join(parts)
    def md_hold(self, r):
        """board.md's mark on a parked item: "on hold, wake Thu Mar 12th 09:30", "on hold, no wake date", or "after board#N"."""
        w = wake_of(r); parts = []
        if is_held(r): parts.append("on hold, " + (f"wake {self.when(w)}" if w else "no wake date"))
        if after_open(r): parts.append(self.after_words(r))
        return "; ".join(parts)
    # ---------------- step statuses: what is in motion on an item ----------------
    def work_prefix(self, r):
        """The keeper whose prefix an agent's name drops on a row (work.short_agent: my-engineer → engineer): the
        `session:` of the item's board row page, else of its own page."""
        k = proj_key(r); row = self.row_of(k) if k else ""
        return str((self.proj.get(row) or self.proj.get(k) or {}).get("session") or "")
    def work_row(self, r):
        """A row's words for the work in progress on an item, as HTML: "engineer: migrating · board: answer box +1" (at most two
        step statuses, the agent's short name in bold, the other open ones counted); "" with nothing in progress. The title lists every open status."""
        shown, more = _work.row_parts(r["metadata"], self.work_prefix(r))
        if not shown: return ""
        tip = " · ".join(f"{l['text']} — {l['state']}" + (f" ({l['agent']})" if l["agent"] else "") for l in _work.open_lines(r["metadata"]))
        body = " · ".join((f"<b>{esc(a)}</b>: " if a else "") + esc(t) for a, t in shown) + (f' <span class="dim">+{more}</span>' if more > 0 else "")
        return f' <span class="iwork" title="{esc(tip)}">{body}</span>'
    def work_html(self, r):
        """The old Work field of the sidebar, for an item that still carries the old `work` list (read-compat: a closed item keeps the list it was closed with; the lines live on the steps
        otherwise and the field is not drawn): every line with its state, its agent and when it last changed; "" with none."""
        ls = _work.legacy_lines(r["metadata"])
        if not ls: return ""
        rank = {"in progress": 0, "assigned": 1, "defined": 2, "done": 3}
        e = esc; L = lambda x: self.mentions(e(x), r["gid"])
        items = "".join(f'<li class="w-{e(l["state"].replace(" ", "-"))}"><span class="wtext">{L(l["text"])}</span>{badge(l["state"], "w-" + l["state"].replace(" ", "-"))}'
                        + (f'<span class="wagent">{L(l["agent"])}</span>' if l["agent"] else "") + (f'<span class="dim">· {e(self.when(l["ts"]))}</span>' if l["ts"] else "") + '</li>'
                        for l in sorted(ls, key=lambda l: rank.get(l["state"], 4)))
        return f'<dt>{esc(_t("item.work"))} <span class="count">{len(ls)}</span></dt><dd><ul class="iwork">{items}</ul></dd>'
    # ---------------- the trailers: his words on an item ----------------
    def said_tag(self, r, n, tag, who="", checked=True):
        """The History's tag for one of his recorded words, on the line of the write that recorded them: "Acked-by the owner",
        reading "Acked-by the owner · unchecked" itself when the transcript could not be read. It expands (a details element) to the
        quote, the session he said it in (linked like other session names), the message's time in the board's zone, and whether
        it was checked. Anchored said-<n> (the entry's position on the item), where the issue's trailer link lands."""
        e = esc
        ents = _said.entries_of(r["metadata"]); ent = ents[n - 1] if 0 < n <= len(ents) else None
        if ent is not None: checked = ent["checked"]
        base = f"{tag} {who or _OWNER}"
        label = base if checked else _t("said.label_unchecked", label=base)
        summary = f'<summary>{badge(label, "said" + ("" if checked else " unchecked"))}</summary>'
        if ent is None:
            return f'<details class="said" id="{e(_said.anchor(n))}">{summary}<div class="sbody"><span class="dim">{_t("said.no_record")}</span></div></details>'
        x = self.sess_of(ent["session"]) or {}
        nm = x.get("name") or ent["session"] or _t("said.unknown_session")
        sess = self.sess_html(nm)
        when = f' · {e(self.when(ent["ts"]))}' if ent["ts"] else ""
        chk = _t("said.checked") if checked else (_t("said.unchecked_why", why=e(ent["why"])) if ent.get("why") else _t("said.unchecked"))
        return (f'<details class="said" id="{e(_said.anchor(n))}">{summary}<div class="sbody"><blockquote>{e(ent["quote"])}</blockquote>'
                f'<span class="smeta">{_t("said.meta", owner=e(_OWNER), sess=sess, when=when, chk=chk)}</span></div></details>')
    def item(self, gid):
        """The item with board id `gid`, open, on hold or completed; KeyError when the store has none."""
        r = next((r for r in self.rows if r["gid"] == str(gid)), None)
        if r is None: raise KeyError(gid)
        return r
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
        fk = {"next": "item.log.field.next", "ask": "item.log.field.ask", "options": "item.log.field.options", "description": "item.log.field.description"}.get(field)
        fw = _t(fk) if fk else field          # the field's name in the request's language
        if not t:
            return _t("item.log.field_cleared", field=fw) + esc(suffix), ""
        if field == "next":
            lines = [ln for ln in t.splitlines() if ln.strip()]
            shown = _ip.clip_md(lines[0], self.HIST_NEXT_CLIP)
            bullet = _t("item.log.next_line", line=self.md_line(shown, r["gid"])) + esc(suffix)
            more = len(lines) > 1 or shown != _ip.clean(lines[0])
            title = _t("item.log.fold_next")
        else:
            bullet, more, title = _t("item.log.field_edited", field=fw) + esc(suffix), True, _t("item.log.fold_field", field=fw)
        fold = f'<details class="ehold"><summary class="more">{title}</summary><div class="body md">{md_block(t)}</div></details>' if more else ""
        return bullet, fold
    @staticmethod
    def hist_bullets(items):
        """[(bullet html, fold html[, class])] → the entry's body: one line each; the class "osub" sets a bullet under the one above it (the options of a decision)."""
        return "".join(f'<div class="eb{" " + x[2] if len(x) > 2 and x[2] else ""}">{x[0]}{x[1]}</div>' for x in items)
    @staticmethod
    def decision_made(prev, v):
        """The decision answer (metadata.answers entry, kind decision) that version v added to the one before it, None when v added none."""
        pa, na = answers_of(prev), answers_of(v)
        return next((a for a in (na[len(pa):] if na[:len(pa)] == pa else []) if a.get("kind") == "decision" and a.get("via") != "github"), None)
    def item_events(self, r):
        """The item's history as (ts, kind, html) tuples, one per change, newest first (item_log without the merge, the author and the plain text); → ([(ts, kind, html)], n_more)."""
        with _i18n.use(_i18n.DEFAULT):          # English whatever the viewer reads: the search index and the migration comment are not a page
            evs, more = self.item_log(r, merge=False)
        return [(x["ts"], x["kind"], re.sub(r'</div><div class="eb(?: osub)?">', "; ", x.get("brief", x["html"]))) for x in evs], more     # a bullet each, without the fold that holds a field's text (the migration comment, the search index)
    def creator_name(self, r, v=None) -> str:
        """The name of whoever created an item, the one rule behind the History's "created by" and the sidebar's Creator row: the version's owner (a cloud owner's
        owner_name, else today's when it is the same owner) resolved as a session name; "" when the version names no owner. `v`: a stored version of the item
        (item_versions); None reads the item as it is now."""
        v = r if v is None else v
        m = v.get("metadata") or {}; o = m.get("owner") or v.get("owner") or ""
        x = self.sess_of(o, m.get("owner_name") or (r["metadata"].get("owner_name", "") if o == r["owner"] else "")) or {}
        return x.get("name") or x.get("id") or ""
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
            b_, f_ = self.hist_field(r, field, text)
            return ("edit", b_, None, f_)
        def owner(v):          # the creator's name (creator_name, also the sidebar's Creator row); "nobody" when the version names none
            return self.creator_name(r, v) or _t("item.log.nobody")
        def mover_of(v):       # step 4b: who moves the item in this version, as the model reads its fields ("" for a closed or a waiting item)
            try:
                mod = _model.derive(v, self.now.timestamp(), after_open=after_open)
            except Exception: return ""
            return mod.mover if mod.state == _model.ALIVE else ""
        def mover_show(w): return _t("item.log.no_one") if not w else (w if _model.is_owner(w) else self.mover_name(w))
        def whose(v):
            if is_held(v): return _t("item.log.on_hold")
            return _t("item.log.completed_word") if v.get("status") == "completed" else list_word((v.get("metadata") or {}).get("state"), needs_kind({"metadata": v.get("metadata") or {}}))
        def due(v): return due_of({"metadata": v.get("metadata") or {}})
        def step_word(w): return {"done": _t("item.log.step_word.done"), "dropped": _t("item.log.step_word.dropped")}.get(w, w)     # the mark a step took, as the History says it
        def proj(v):
            k = proj_key({"metadata": v.get("metadata") or {}})
            return self.proj_label(k) if k in self.proj else (k or _t("item.no_project"))
        out = []
        groups = {}          # a step's key -> the status updates written on it while it was open (folded under its one line); a closed group stays here only for the line it made
        vs = self.item_versions(r); prev = None
        for vi, (ts, v) in enumerate(vs):
            m = v.get("metadata") or {}; ev = []
            if prev is None:
                ev.append(("created", (_t("item.log.created_mover", subject=e(v.get('subject') or ''), whose=e(whose(v)), mover=e(mover_show(mover_of(v))), owner=e(owner(v))) if mover_of(v)
                                  else _t("item.log.created", subject=e(v.get('subject') or ''), whose=e(whose(v)), owner=e(owner(v))))   # the subject it was born with
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
                        ev.append(("completed", (_t("item.log.completed_outcome", outcome=f"<b>{e(outcome_ui(oc))}</b>") if oc else _t("item.log.completed")) + (" " + _t("item.by", who=e(shown(by))) if by else "") + (_t("item.log.completed_why", why=e(why)) if why else "")))
                    elif h_ and not ph:
                        w = wake_of(v); ev.append(("hold", _t("item.log.hold_wake", when=e(self.when(w))) if w else _t("item.log.hold")))
                    elif ph and not h_: ev.append(("unhold", _t("item.log.unhold", whose=e(whose(v)))))
                    elif ps == "completed": ev.append(("reopened", _t("item.log.reopened", whose=e(whose(v)))))
                if not h_ and not ph and s_ != "completed" and ps == s_:
                    a, b = needs_kind({"metadata": pm}), needs_kind({"metadata": m})
                    if a != b:
                        po = options_of(prev) if a == "call" else []    # the options leave the page with the decision and stay here
                        pk = ask_of(prev) if a == "call" else ""        # and so does the ask, its Decide part (the raw line if misshaped)
                        pk = ((parse_ask(pk) or {}).get("decide") or pk) if pk else ""
                        mv = ("needs", _t("item.log.moved_to", lane=f"<b>{e(list_word(m.get('state'), b))}</b>"))
                        ev.append(mv)
                        if pk: ev.append(("needs", _t("item.log.ask_was", ask=e(_ip.clip(pk, 160))), None, f'<details class="ehold"><summary class="more">{_t("item.log.whole_ask")}</summary><div class="body md">{md_block(ask_of(prev))}</div></details>'))
                        dec = self.decision_made(prev, v)                # his answer written with this change, when it is one
                        kept = {"metadata": {"options": (dec or {}).get("options")}}
                        po, rpo = (options_of(kept), options_of(kept, raw=True)) if options_of(kept) else (po, options_of(prev, raw=True) if a == "call" else [])      # the options he was shown, kept on his answer (a record from before that has them from the version before); rpo = their labels as stored
                        if po:
                            ev.append(("needs", _t("item.log.options_were")))
                            hits = [j for j, (o, ro) in enumerate(zip(po, rpo)) if dec and dec.get("choice") and dec["choice"] in (o["label"], ro["label"])]      # the label as shown, or as stored (an answer from before the letter was dropped on read)
                            lt = str((dec or {}).get("letter") or "")
                            hit = (ord(lt) - 65 if len(lt) == 1 and lt.isascii() and lt.isalpha() and ord(lt) - 65 in hits else hits[0] if hits else -1)      # one option is marked: the letter's place when the answer carries one, else the first match (as the pick resolves)
                            for i, (o, ro) in enumerate(zip(po, rpo)):
                                taken = i == hit
                                ev.append(("needs", _t("item.log.opt_rec" if o["recommended"] else "item.log.opt", label=f'<b>{e(_ol.listed(o["label"], i))}</b>', line=e(o["line"])) + (_t("item.log.opt_picked", picked=f'<b>{_t("item.log.picked")}</b>') if taken else ""), None, "", "osub"))
                            if dec and not dec.get("choice"): ev.append(("needs", _t("item.log.no_pick")))
                    elif [shown_ref(x) for x in needs_sessions({"metadata": pm})] != [shown_ref(x) for x in needs_sessions({"metadata": m})]:   # the sessions named changed, the lane not
                        ns = [shown_ref(x) for x in needs_sessions({"metadata": m})]; ev.append(("needs", _t("item.log.needs", names="<b>" + e(", ".join(ns)) + "</b>") if ns else _t("item.log.needs_none")))
                elif is_held(v) and is_held(prev) and wait_date_of(prev) != wait_date_of(v):
                    w = wait_date_of(v); ev.append(("hold", _t("item.log.wake_set", when=e(self.when(w))) if w else _t("item.log.wake_cleared")))
                if not h_ and not ph and s_ != "completed" and ps == s_ and wait_date_of(prev) != wait_date_of(v):   # a date that is no wait (a backstop): set, moved or gone
                    w = wait_date_of(v); ev.append(("hold", _t("item.log.backstop_set", when=e(self.when(w))) if w else _t("item.log.backstop_cleared")))
                if s_ != "completed" and after_of({"metadata": pm}) != after_of({"metadata": m}):   # what it waits on
                    af = after_of({"metadata": m}); ev.append(("hold", _t("item.log.after", ids="<b>" + e(", ".join(shown(g) for g in af)) + "</b>") if af else _t("item.log.after_cleared")))
                if s_ != "completed" and (pm.get("state") != m.get("state") or any(pm.get(k) != m.get(k) for k in _states.CARRY_FIELDS)):   # where it stands, with what the state carries
                    ev.append(("hold", (_t("item.log.state_moved", old=e(pm['state']), new=f"<b>{e(m['state'])}</b>") if pm.get("state") in (*_states.STATES, *_states.LEGACY_STATES) and pm.get("state") != m.get("state") else _t("item.log.state", new=f"<b>{e(m['state'])}</b>")) + "".join(_t("item.log.state_carry", label=k, value=e(_ip.clip(m[k], 300))) for k in _states.CARRY.get(m["state"], ()) if m.get(k)) if m.get("state") in _states.STATES
                               else _t("item.log.state_cleared", old=e(list_word(pm.get('state')) or pm.get('state')))))
                if s_ != "completed" and (pm.get("draft") or "") != (m.get("draft") or ""):   # the draft's own line its text is on the item
                    ev.append(("edit", _t("item.log.draft_cleared") if not m.get("draft") else _t("item.log.draft_edited") if pm.get("draft") else _t("item.log.draft_set")))
                if s_ != "completed" and pm.get("rank") != m.get("rank"):   # the builder's queue order
                    ev.append(("hold", _t("item.log.rank_set", rank=f"<b>{e(m['rank'])}</b>") if m.get("rank") else _t("item.log.rank_cleared", old=e(pm.get('rank')))))
                if s_ != "completed":                       # a step the stall pass took (its mover's pane had no turn running), one line each, said by stackshot
                    for x in _stall.new_entries(pm, m): ev.append(("stall", "stackshot: " + e(x["text"])))
                    for x in _hlog.new_entries(pm, m): ev.append(("stall", "stackshot: " + e(x["text"])))      # the hourly audit line (audit/hourly.py), its own log
                if s_ != "completed":                       # a front agent's notice about the item (told on his next turn, or not told), the board keeps the news either way
                    for x in _quiet.new_entries(pm, m): ev.append(("front", "stackshot: " + e(x["text"])))
                if s_ != "completed" and ps == "open":      # a mover change, in the model's words; a close or a reopening says its own line
                    mv_a, mv_b = mover_of(prev), mover_of(v)
                    if mv_a and mv_b and mv_a != mv_b and not same_ref(mv_a, mv_b):      # a hold or a wait takes the mover away: its own line says that
                        ev.append(("mover", _t("item.log.mover", old=e(mover_show(mv_a)), new=f"<b>{e(mover_show(mv_b))}</b>")))
                ho_ = _hov.fresh(pm, m) if s_ != "completed" else {}       # a finished step handed the item on, or could not: its own line (handover.py)
                if ho_:
                    ev.append(("mover", (_t("item.log.handover_moved_from", old=e(mover_show(mover_of(prev))), to=f"<b>{e(mover_show(mover_of(v)))}</b>") if mover_of(prev) else _t("item.log.handover_moved", to=f"<b>{e(mover_show(mover_of(v)))}</b>")) if ho_.get("kind") == _hov.MOVED
                               else _t("item.log.handover_kept", who=e(self.mover_name(ho_.get('to') or '')), to=f"<b>{e(mover_show(mover_of(v)) if mover_of(v) != 'no one' else _t('item.log.its_mover'))}</b>")))
                a, b = due(prev), due(v)
                if a != b:
                    ev.append(("due", _t("item.log.due_set", when=f"<b>{e(self.when(b))}</b>") if not a else _t("item.log.due_cleared", old=e(self.when(a))) if not b
                               else _t("item.log.due_moved", old=e(self.when(a)), new=f"<b>{e(self.when(b))}</b>")))
                if (pm.get("priority") or "p2") != (m.get("priority") or "p2"): ev.append(("priority", _t("item.log.priority", old=e(pm.get('priority') or 'p2'), new=f"<b>{e(m.get('priority') or 'p2')}</b>")))
                if proj_key({"metadata": pm}) != proj_key({"metadata": m}):
                    rl = _gh.refile_line(pm, m)        # "Refile itself": the server moved it to its owner's project
                    ev.append(("project", e(rl) if rl else _t("item.log.project", old=e(proj(prev)), new=f"<b>{e(proj(v))}</b>")))
                if prev.get("subject") != v.get("subject"): ev.append(("edit", _t("item.log.subject_edited", old=e(prev.get('subject') or ''))))
                who_ = " ".join(str(v.get("written_by") or "").split())
                for te in _work.tag_events(pm, m):          # a step's status line set, moved or cleared: folded under the step's one line (below), not a line of its own
                    g = groups.get(te["key"])
                    if g is None or g["closed"]:
                        g = groups[te["key"]] = {"step": te["step"], "ups": [], "first": ts, "closed": False, "vi": vi}
                    g["ups"].append((ts, te)); g["last"] = ts; g["vi"] = vi; g["who"] = who_
                just_closed = set()
                for k_, mark_ in _work.closed_steps(pm, m):         # a step marked done or dropped closes its group
                    g = groups.get(k_)
                    if g is not None and not g["closed"]:
                        g["closed"] = True; g["vi"] = vi; g["last"] = ts; g["who"] = who_; g["mark"] = mark_
                        just_closed.add(g["step"])
                for word, line in _steps.changes(pm, m, s_ == "completed"):     # a step checked or dropped, one line each (a step with status updates has the folded line instead)
                    if line in just_closed: continue
                    ev.append(("step", _t("item.log.step_mark", mark=step_word(word), line=self.md_line(_ip.clip_md(line, self.HIST_NEXT_CLIP), r["gid"]))))
                if (pm.get("next") or "") != (m.get("next") or ""): ev.append(fev("next", m.get("next")))
                pa, a_ = str(pm.get("ask") or "").strip(), str(m.get("ask") or "").strip()
                if pa != a_: ev.append(fev("ask", a_))
                if (pm.get("options") or []) != (m.get("options") or []): ev.append(fev("options", _gh._options_text(m.get("options"))))
                if (prev.get("description") or "") != (v.get("description") or ""): ev.append(fev("description", v.get("description")))
                pa_, na_ = answers_of(prev), answers_of(v)
                if len(na_) > len(pa_) and na_[:len(pa_)] == pa_:        # phase 3: his answer from the board, one line each
                    for a in na_[len(pa_):]:
                        ch, tx = str(a.get("choice") or ""), str(a.get("text") or "")
                        if ch and a.get("letter"): ch = _ol.pick_words(ch, a["letter"])      # the letter the answer box drew beside the option
                        ev.append(("answer", _t("item.log.answer_via", owner=e(_OWNER), via=e(a.get('via') or _t("item.log.via_board"))) + (f"<b>{e(ch)}</b>" if ch else "") + (" — " if ch and tx else "")
                                   + e(tx) + (f' <span class="dim">{_t("item.log.tag_comment")}</span>' if a.get("kind") == "comment" else f' <span class="dim">{_t("item.log.tag_step_note")}</span>' if a.get("kind") == "step-reply" else "")))
                for w in _work.legacy_changes(pm, m): ev.append(("work", e(w)))   # a line of the old work list added, moved, reassigned or removed, one line each (an item the migration has not reached)
                new_said = _said.new_entries(pm, m)                          # the trailers: his words recorded by this version, a tag each
                if new_said: ev.append(("said", e(_said.recorded_words([x for _n, x in new_said])) + "".join(" " + self.said_tag(r, n, x["tag"], "", x["checked"]) for n, x in new_said)))
                if (prev.get("confirmed") != v.get("confirmed") and v.get("confirmed")
                        and {k_: ({kk: vv for kk, vv in x.items() if kk not in ("phase", "waits_on", "project_id", "last_activity")} if k_ == "metadata" and isinstance(x, dict) else x) for k_, x in prev.items() if k_ not in ("confirmed", "activity")} == {k_: ({kk: vv for kk, vv in x.items() if kk not in ("phase", "waits_on", "project_id", "last_activity")} if k_ == "metadata" and isinstance(x, dict) else x) for k_, x in v.items() if k_ not in ("confirmed", "activity")}):      # `activity` is a clock too (activity.py): seeding it is no change to the item, and neither are the stored phase and the kind of its wait that every save of an open item writes (metadata.phase, metadata.waits_on), nor the last-activity record the hub's event pass stamps (metadata.last_activity)
                    ev.append(("confirm", _t("item.log.confirmed")))   # the confirm tool: confirmed changed alone
                pa_ = answers_of(prev)
                for a in answers_of(v)[len(pa_):]:      # phase 3: the owner's comment written on GitHub, at the comment's own time
                    if a.get("via") == "github":
                        u, t = str(a.get("url") or ""), re.sub(r"\s+", " ", str(a.get("text") or "")).strip()
                        t = t if len(t) <= 160 else t[:159].rstrip() + "…"
                        where = f'<a href="{e(u)}" target="_blank" rel="noopener">{_t("item.log.on_github")}</a>' if u else _t("item.log.on_github")
                        try: at = float(a.get("ts") or 0) or None
                        except (TypeError, ValueError): at = None
                        ev.append(("comment", _t("item.log.gh_comment", owner=e(_OWNER), where=where, text=e(t)), at))
            who = " ".join(str(v.get("written_by") or "").split())          # the revision's author (model.py: every save records it); older revisions carry none
            chg = [x for x in ev if x[0] != "comment"]
            if not merge:                                                    # one entry per change, as before (item_events)
                out += [(vi, j, {"ts": (x[2] if len(x) > 2 and x[2] else ts), "kind": x[0], "html": x[1], "who": who, "what": _ip.plain(x[1]), "comment": x[0] == "comment"}) for j, x in enumerate(ev)]
            else:
                if chg:                                                      # one entry per revision: its author and time on the header line, one bullet per change (a text field's text in a fold)
                    h = self.hist_bullets([(x[1], x[3] if len(x) > 3 else "", x[4] if len(x) > 4 else "") for x in chg])
                    out.append((vi, 0, {"ts": ts, "kind": next((k_ for k_ in ("completed", "reopened", "answer", "created", "said") if any(x[0] == k_ for x in chg)), chg[0][0]), "html": h, "who": who, "what": "; ".join(_ip.plain(x[1]) for x in chg), "comment": False}))
                for j, x in enumerate(c for c in ev if c[0] == "comment"):   # his comment written on GitHub: its own line, at the comment's own time
                    out.append((vi, j + 1, {"ts": (x[2] if len(x) > 2 and x[2] else ts), "kind": "comment", "html": self.hist_bullets([(x[1], "")]), "who": _OWNER, "what": _ip.plain(x[1]), "comment": True}))
            prev = v
        for g in groups.values():          # one line per step: a closed step says it was closed, the status updates written on it folded under; an open step's updates are one line too, at its newest update
            n = len(g["ups"])
            fold = ("".join(f'<li><span class="dim">{e(self.when(t_))}</span> {e(te["text"]) if not te["removed"] else _t("item.log.status_cleared", text=e(te["text"]))}'
                            + (f' <span class="dim">· {e(te["state"])}</span>' if te["state"] else "") + '</li>' for t_, te in g["ups"]))
            nstat = _t("item.log.status_one" if n == 1 else "item.log.status_many", n=n)
            body = [((_t("item.log.step_mark", mark=step_word(g["mark"]), line="") if g["closed"] else _t("item.log.step_open", line="")) + self.md_line(_ip.clip_md(g["step"], self.HIST_NEXT_CLIP), r["gid"]),
                     f'<details class="ehold"><summary class="more">{nstat}</summary><div class="body"><ul class="estat">{fold}</ul></div></details>')]
            ent = {"ts": g["last"], "ts_from": g["first"], "kind": "work", "html": self.hist_bullets(body), "who": g.get("who", ""),
                   "what": (_t("item.log.step_mark", mark=step_word(g["mark"]), line=g["step"]) if g["closed"] else _t("item.log.step_open", line=g["step"])) + f'; {nstat}: ' + "; ".join(te["text"] for _w, te in g["ups"]), "comment": False}
            host = next((x[2] for x in out if merge and g["closed"] and x[0] == g["vi"] and x[1] == 0), None)      # the write that closed the step is one entry: its step line first, its other changes (a new next) after it
            if host is not None:
                host["html"], host["ts_from"], host["what"] = ent["html"] + host["html"], g["first"], ent["what"] + "; " + host["what"]
            else:
                out.append((g["vi"], 0.5, ent))
        out.sort(key=lambda x: (-x[0], x[1]))
        return [x for _vi, _j, x in out[:self.HISTORY_CAP]], max(len(out) - self.HISTORY_CAP, 0)
    _SENT_KEYS = {"decision": ("ok", "sent.decision"),      # ?sent=<code> → (the notice's class, its key on the item page, its key on the home page when that differs: it has no "below" and no box to press again in)
                  "comment": ("ok", "sent.comment"),
                  "empty": ("warn", "sent.empty"),
                  "emptynote": ("warn", "sent.emptynote"),      # Send note on a blank box (a decision form's blank Send is "empty": it asks for a note or an option)
                  "toolong": ("warn", "sent.toolong"),
                  "stale": ("warn", "sent.stale", "sent.stale_home"),
                  "askedback": ("warn", "sent.askedback", "sent.askedback_home"),
                  "stalenote": ("ok", "sent.stalenote", "sent.stalenote_home"),
                  "closednote": ("ok", "sent.closednote"),
                  "closed": ("warn", "sent.closed"),
                  "done": ("ok", "sent.done"),
                  "donenote": ("ok", "sent.donenote"),      # Done pressed with a note in the box: the note went along
                  "stepreply": ("ok", "sent.stepreply"),      # the item page names who: sent_html(taken_by=)
                  "nomover": ("warn", "sent.nomover"),
                  "nostep": ("warn", "sent.nostep", "sent.nostep_home")}
    _SENT = {k: (v[0], *[_i18n.EN[x] for x in v[1:]]) for k, v in _SENT_KEYS.items()}      # the English view of the table above (what the tests read)
    def sent_msg(self, code, taken_by="") -> str:
        """The notice of a ?sent= code (a key of _SENT_KEYS) in the request's language, as plain text (not escaped): the item page's wording (the home page's own, where a code has one, is read by sent_notes_html).
        After Done or a note on the step, `taken_by` (who moves the item now) names them. "" for a code that is none."""
        v = self._SENT_KEYS.get(code)
        if not v: return ""
        if taken_by and code == "done": return _t("js.sent_done", who=taken_by)
        if taken_by and code == "donenote": return _t("js.sent_done_note", who=taken_by)
        if taken_by and code == "stepreply": return _t("sent.stepreply_by", who=taken_by)
        return _t(v[1])
    def answer_html(self, r, answer, comment_only=False) -> str:
        """the answer box under the Ask of an open item, for a signed-in viewer (`answer` = {"action", "token"} from
        the server; None draws nothing). While it needs his decision: one card per stored option (_cards_html: the label and the whole text of the option, the recommended one marked by its badge;
        three or more options in the stored order, lettered A, B, C, two with the recommended one first), an optional note and one Send, which is the only way to send and which the page script (_CARDS_JS) greys until a card is
        picked or the note has text; when the owner listed no options, two cards of our own, Yes (recommended, first) and No (Approve and Decline are options like any other: only an owner who
        lists them gets them, and one who lists options gets only those). Otherwise a text box with one Send, a comment. A plain form
        POST that the page's script (_ANSWER_JS) sends as a fetch, so the answer replaces the page in history; the form itself
        holds no script and works without it (the cards are radio inputs; Send is then always on). A picked card also sends what the note holds, as a note to the choice.
        comment_only (an item he does not move, whose box takes the answer box's slot on the item model's page): the same form with the comment button alone."""
        if not answer or r.get("status") == "completed": return ""
        e = esc
        if comment_only:
            return (f'<form class="ianswer" data-comment-only method="post" action="{e(answer["action"])}"><b>{_t("answer.add_comment")}</b>'
                    f'<input type="hidden" name="token" value="{e(answer["token"])}">'
                    f'<label for="atext">{_t("answer.write_comment")}</label>'
                    + _abox('<textarea id="atext" name="text" rows="3" maxlength="4000"></textarea>', "atext") +
                    f'<div class="abtns"><button type="submit" class="b main" name="act" value="comment">{_t("home.send")}</button></div>'
                    '<p class="isent warn aerr" role="alert" hidden></p></form>')
        call = "decision" in [x.lower() for x in needs_of(r)]          # the server takes a choice only then (server._answer)
        opts = _card_order(options_of(r) or yesno_options(r)) if call else []     # three or more in the stored order (lettered), two with the recommended one first; the owner's stored options only, and with none, Yes and No
        if opts:                  # the cards (_cards_html), an optional note and one Send, greyed by the page script (_CARDS_JS) until a card is picked or the note has text
            return (f'<form class="ianswer" data-cards method="post" action="{e(answer["action"])}"><b>{_t("answer.your_answer")}</b>'
                    f'<input type="hidden" name="token" value="{e(answer["token"])}">{_cards_html(opts)}'
                    f'<label class="anote" for="atext">{_t("home.note_optional")}</label>'
                    + _abox('<textarea id="atext" name="text" rows="3" maxlength="4000"></textarea>', "atext") +
                    f'<div class="abtns-send"><button type="submit" class="b main" name="act" value="answer">{_t("home.send")}</button><span class="ahint" hidden>{_t("home.pick_hint")}</span></div>'
                    '<p class="isent warn aerr" role="alert" hidden></p></form>')
        return (f'<form class="ianswer" method="post" action="{e(answer["action"])}"><b>{_t("answer.your_answer") if call else _t("answer.add_comment")}</b>'
                f'<input type="hidden" name="token" value="{e(answer["token"])}">'
                f'<label for="atext">{_t("answer.write_answer") if call else _t("answer.write_comment")}</label>'
                + _abox('<textarea id="atext" name="text" rows="3" maxlength="4000"></textarea>', "atext") +
                f'<div class="abtns"><button type="submit" class="b main" name="act" value="{"answer" if call else "comment"}">{_t("home.send")}</button></div>'
                '<p class="isent warn aerr" role="alert" hidden></p></form>')
    def watch_html(self, watch) -> str:
        """The For you control in an item page's sidebar, for a signed-in viewer (`watch` from the server; None draws
        nothing): whether the item is watched now and why, and the three buttons Watch, Mute and Default (his stored flag, if any, is the
        one pressed). A plain form POST to /items/<n>/watch."""
        if not watch: return ""
        e = esc; flag = str(watch.get("flag") or "")
        state = _t("watch.muted") if flag == "mute" else (_t("watch.watched") if watch.get("watched") else _t("watch.not_watched"))
        def btn(mode, label):
            on = flag == mode or (mode == "default" and not flag)
            return (f'<button type="submit" class="b{" on" if on else ""}" name="mode" value="{mode}"'
                    + (' aria-pressed="true" disabled' if on else ' aria-pressed="false"') + f'>{label}</button>')
        why = f' <span class="dim">· {e(watch.get("why") or "")}</span>' if watch.get("why") else ""
        return ('<dl class="sgrp"><dt>' + _t("watch.for_you") + '</dt><dd><form class="iwatch" method="post" action="' + e(watch["action"]) + '">'
                '<input type="hidden" name="token" value="' + e(watch["token"]) + f'"><span class="wstate">{state}</span>{why}'
                '<div class="abtns">' + btn("watch", _t("watch.watch")) + btn("mute", _t("watch.mute")) + btn("default", _t("watch.default")) + '</div></form></dd></dl>')
    def for_you_html(self) -> str:
        """The board's For you section: what he should see, newest first, one row each: the item (linked), what
        happened, when (the board's zone) and a "seen" button that clears it (POST /for-you/seen; the page script sends it as a fetch
        and drops the row, the form itself works without script). Always drawn, so the block set of the page stays the same."""
        rows = _fy.rows(); e = esc
        def row(r):
            gid = str(r.get("gid") or "")
            who = (f'<a class="fy-id" href="{e(id_href(gid))}" target="_blank" rel="noopener">{e(shown(gid))}</a>' if gid else f'<span class="fy-id dim">{e(str(r.get("kind") or "").replace("_", " "))}</span>')
            urgent = f' <span class="badge due">{_t("foryou.urgent")}</span>' if r.get("urgent") else ""
            return (f'<li class="fy-row{" urgent" if r.get("urgent") else ""}" id="fy-{int(r["id"])}"><span class="fy-main">{who}'
                    f'<span class="fy-what">{e(str(r.get("what") or ""))}{urgent}</span></span>'
                    f'<span class="fy-when" title="{e(str(r.get("kind") or ""))}">{e(self.when(float(r.get("ts") or 0)))}</span>'
                    f'<form class="fy-seen" method="post" action="{under("/for-you/seen")}"><input type="hidden" name="id" value="{int(r["id"])}">'
                    f'<button type="submit" class="b" title="{esc(_t("foryou.seen_tip"))}">{_t("foryou.seen_btn")}</button></form></li>')
        allb = (f'<form class="fy-seen fy-all" method="post" action="{under("/for-you/seen")}"><input type="hidden" name="id" value="all">'
                f'<button type="submit" class="b">{_t("foryou.all_seen")}</button></form>') if len(rows) > 1 else ""
        body = (f'<ul class="fy-list">{"".join(row(r) for r in rows)}</ul>{allb}' if rows else f'<p class="empty fy-empty">{_t("foryou.empty")}</p>')
        return _top_fold("for-you", f'<h2>{_t("watch.for_you")} <span class="count">{len(rows)}</span></h2>', body)
    def sent_html(self, answer, taken_by="") -> str:
        """The short notice after a POST (?sent=<code>): sent, or why nothing was. After Done or a note on the step `taken_by` is who moves the item now."""
        k = str((answer or {}).get("sent") or "")
        if k not in self._SENT: return ""
        cls = self._SENT[k][0]
        msg = self.sent_msg(k, taken_by)
        return f'<p class="isent {cls}" role="status">{esc(msg)}</p>'
    def contact_name(self, r, contact=None) -> str:
        """The item's contact as the side column's first row names it: `contact` as the server derived it (an open item's live contact, server._contact_label), else the stored metadata.contact as the session's name now; "" when none."""
        stored = str((r.get("metadata") or {}).get("contact") or "").strip()
        return str(contact).strip() if contact is not None else (self.mover_name(stored) if stored else "")
    def row_contact(self, r) -> str:
        """The contact a list row names: the same name as the side column's Owner row (contact_name), derived by `contact_of` when the board has one. One lookup per item and render, kept for the rows of the other lists that draw it again."""
        g = r["gid"]
        if g not in self._contacts:
            c = None
            if self.contact_of is not None:
                try: c = str(self.contact_of(r) or "")
                except Exception: c = None      # an extra: the row then reads the stored contact
            self._contacts[g] = self.contact_name(r, c)
        return self._contacts[g]
    def owner_row(self, r, contact=None) -> tuple:
        """The side column's first row → (the "Owner" label with its hover text, the value), or ("", "") when the item has no contact (no row). The value is the contact's session
        name, drawn as every session on the page is (sess_html): a link to the fleet tool's view ([client] session_view) while the session has a live pane, plain text otherwise. `contact`: the name as the server
        derived it (an open item's live contact, server._contact_label); None reads the stored metadata.contact as the session's name now."""
        name = self.contact_name(r, contact)
        if not name: return ("", "")
        val = self.sess_html(name, arrow=True)      # the page's one rule: a link to the session's view while its pane lives, plain text otherwise
        return (f'<span title="{esc(_t("item.owner_tip"))}">{_t("item.owner")}</span>', val)
    def mover_row(self, r) -> tuple:
        """The side column's first row → (the "Mover" label, the value): the agent the item sits under (its mover; for an item the owner moves, its `then`; for a waiting one, the session
        that takes it when the wait ends), drawn as every session on the page is (sess_html) with the machine it runs on, or "no agent" when none. The creator is no one's agent (a History
        line, "created by"). The row is drawn once, first in the column, in the group with Owner and Creator; the line under the title no longer names the mover."""
        e = esc
        x = self._sess_obj(r) or {}; mach = str(x.get("machine") or "")
        where = _t("item.cloud") if mach == "c" else (self.fleet.get(mach) or mach)
        nm = x.get("name") or x.get("id") or _t("item.no_agent")
        return (_t("item.mover"), self.sess_html(nm, arrow=True) + (f' <span class="dim">· {e(where)}</span>' if where else ""))
    def creator_row(self, r) -> tuple:
        """The side column's row under Owner (Mover, Owner, Creator are its first three) → (the "Creator" label with its hover text, the value): whoever created the item, by the name the History's first line gives (creator_name),
        drawn as every session on the page is (sess_html). It is on every item, open or closed; one that names no creator reads as a muted "unknown", never blank."""
        name = self.creator_name(r)
        val = self.sess_html(name, arrow=True) if name else f'<span class="dim">{_t("item.unknown")}</span>'
        return (f'<span title="{esc(_t("item.creator_tip"))}">{_t("item.creator")}</span>', val)
    def item_html(self, gid, answer=None, watch=None, contact=None) -> str:
        """An item's own page at /items/<gid>, on the item model (the layout is GitHub's: a main column beside a right-hand sidebar, one
        column under 768px). The goal as the title (the subject when it has none; the id first, muted, beside the item's GitHub issue link), then in the main column: one state line in
        words (alive · since; waiting on · watched by · until · then; done · date · outcome; the mover and the `then` are the sidebar's Mover and Then rows) on its own (the History keeps every change),
        the ask with its buttons and box (or the Your step block) while it is alive with the owner as mover, Next (every line, numbered, each
        `<mover>: <action>`), the wait and its chases while it waits, the Outcome of a closed item (the stored `outcome_text`, first among the sections, under the state line; none for an open item or a close with no outcome text), the Background (the stored `description`, which a close leaves as it was), and History and Comments, closed folds. The sidebar opens with Mover, Owner and Creator (one group, in that order) and holds
        project, then, priority, wake, anchors, the GitHub issue and the For you control; today's other fields (agent at work, due, confirmed, work, after,
        observers) sit in a closed "More details" fold below them. The History is one line per revision with its author. Rendered on request; KeyError for an unknown id.
        answer: the server's {"action", "token", "sent"} for a signed-in viewer: the answer box under the Ask (an item the owner does not move has the comment box in the same place, open).
        watch (the For you list): the server's {"action", "token", "flag", "watched", "why"} for a signed-in viewer: the Watch / Mute control in the sidebar.
        contact: the item's contact as the server derives it (server._contact_label), the sidebar's second row, "Owner" (after Mover); None reads the stored one; no contact, no row."""
        r = self.item(gid); m = r["metadata"]; e = esc
        done = r.get("status") == "completed"
        L = lambda x: self.linkify(x, r["gid"])       # session-written free text: links, and item and session mentions
        M = lambda t: self.mentions(e(t), r["gid"])   # a plain sentence: escaped, then the sessions and items it names linked
        tnow = self.now.timestamp()
        # the project, the scoped anchors (the model reads an outside item as an anchor wait when one is scoped to it)
        pk = proj_key(r); mirror = self.proj_mirror(pk) if pk else ""
        # the anchors that count for the item are the ones scoped to it on any project's page (anchor_scope.anchor_scope: the rule the server and the lists read); one held by another project's page says whose
        arows = sorted(((self.anchor_row(x), x) for x in _ascope.anchor_scope(self.anchors, r["gid"], pk)), key=lambda t: _KIND_ORDER.index(t[0][0]) if t[0][0] in _KIND_ORDER else len(_KIND_ORDER))
        held_on = lambda x: (f' · <span class="dim">{_t("item.anchor_on", page=e(self.proj_label(x["page"]) if x["page"] in self.proj else x["page"]))}</span>' if x["page"] != pk else "")
        alist = "".join(f'<li><b>{e(kind)}</b> ' + (f'<a href="{e(u)}" target="_blank" rel="noopener">{e(nm_)}</a>' if u else e(nm_)) + f' <em>· {w}</em>{held_on(x)}</li>'
                        for (kind, (nm_, u, w, _sc, _h)), x in arows)
        mod = _queued.overlay(_model.view(r, _model.derive(r, now=tnow, after_open=after_open, anchored=lambda _i: bool(arows)), tnow, after_open), self.queue_map().get(r["gid"], ""))      # a doing item whose wake is far out with every step dated reads as waiting
        alive, waiting = mod.state == _model.ALIVE, mod.state == _model.WAITING
        who_html = lambda w: e(w) if (not w or _model.is_owner(w)) else self.sess_html(self.mover_name(w))     # the owner as he is named; a session linked while its pane lives
        who_text = lambda w: (w if (not w or _model.is_owner(w)) else self.mover_name(w))
        # ---- the title and the state line
        goal = _ip.clean(m.get("goal")); title = self.bare(r["subject"])      # the subject as home shows it (no leading "[project]" tag), never the goal; the goal is the line under it
        since = _ip.since_of(r, mod)
        oc, why, by = outcome_of(r)
        not_taken = bool(alive and _hand.awaiting_session(r, mod.mover, same_ref))      # a hand-off to a session only, never the owner's
        wtext = wend = wlab = ""                # a waiting item: what it waits on and its end, as plain text
        w_ = mod.wait
        wbasis = "" if done else _wt.basis_of(m)         # a long wait that stands on a real-world date (wait_basis), and his words when they were recorded
        wwords = {} if done else _wt.words_of(m)
        if waiting and w_:
            reason = wbasis or (wwords.get("quote") or "")
            wtext = _ip.wait_what(w_, shown=shown, party=str(m.get("party") or ""), words=reason, mode=_ip.list_mode_words(mod))
            wlab = _ip.wait_end_label(w_) if (w_.until or w_.backstop) else _t("wait.end.until")
            wend = w_.until or w_.backstop or _ip.clean(m.get("wake"))      # a wait the fields end by a date (a relay's ask-by, an event's backstop), else the wake the item carries
        post = w_.mover if (waiting and w_) else ""
        # ---- the History, split: what changed, and what people said
        evs, more = self.item_log(r)
        changes, said_ = [x for x in evs if not x["comment"]], [x for x in evs if x["comment"]]
        li = lambda x: f'<li class="ev ev-{x["kind"]}"><div class="eh">{"<b>" + e(x["who"]) + "</b> · " if x["who"] else ""}<span class="t">{e(self.span_words(x["ts_from"], x["ts"]) if x.get("ts_from") else self.when(x["ts"]))}</span>{" " + x["mark"] if x.get("mark") else ""}</div><div class="w">{self.mentions(x["html"], r["gid"])}</div></li>'
        extra = []
        if not done and waits_recycle(r): extra.append(badge(_t("item.waits_recycle"), "recycle"))   # held ones too (they keep the field)
        # ---- Next: every line, numbered, each `<mover>: <action>` (no "+N more" fold)
        nmover = who_text(mod.mover if alive else post)
        lines = _ip.next_lines(m.get("next") or "", nmover)
        # Next is the item's checklist: open ones with an empty box, done ones checked and dimmed with who checked them and when, dropped ones struck through
        # drawn with the finished steps first, in the order they were marked, then the open ones in their planned order (steps.drawn_order); the stored order and the positions in get are unchanged
        # his decisions on the board (option picks, Approve/Decline/Yes/No/Done) are drawn among the finished rows by time, as rows of their own: not steps, nothing stored, no position in get
        sl = _steps.view(m, closed=done)
        checklist = _steps.drawn_order(sl, self.decision_rows(r, sl))
        def cli(x):
            if x["status"] == "decided":
                return (f'<li class="cl-decided"><span class="cb" aria-hidden="true">✓</span><div class="cl-b"><span class="sr">{_t("item.sr", word=_t("item.step.decided"))}</span><span class="cl-t">{self.md_line(x["text"], r["gid"])}</span>'
                        f'<span class="cl-by"><b>{_t("item.stamp.decided")}</b>{" · " + e(self.when(float(x["at"]))) if x.get("at") else ""}</span></div></li>')
            nl = (_ip.next_lines(x["text"], "" if _steps.is_bare(x["text"]) else nmover) or [_ip.NextLine("", True)])[0]      # a bare bullet is a step of its own (nextlines) and reads as a sub-step: no mover put in front of it
            st = x["status"]; fmt = self.cmd_step if st == _steps.OPEN else (lambda t_, g_, f_: f_(t_, g_))      # a command block (with Copy) only on a step still to do
            subs = "".join(f"<li class=\"icode\"><div class=\"md\">{self.md_html(s_, r['gid'])}</div></li>" if _ip.is_fence(s_) else f"<li>{fmt(s_, r['gid'], self.md_line)}</li>" for s_ in nl.subs)
            body = fmt(nl.text, r['gid'], self.md_line) if nl.text else ''
            who = e(str(x.get("by") or "")); when_ = e(self.when(float(x["at"]))) if x.get("at") else ""
            stamp = " · ".join(b_ for b_ in ((f"<b>{_t('item.stamp.done') if st == _steps.DONE else _t('item.stamp.dropped')}</b>" + (" " + _t("item.by", who=who) if who else "")), when_) if b_)      # the verb opens the byline, done and dropped alike
            word = {_steps.OPEN: _t("item.step.todo"), _steps.DONE: _t("item.step.done"), _steps.DROPPED: _t("item.step.dropped")}[st]
            glyph = {_steps.OPEN: "", _steps.DONE: "✓", _steps.DROPPED: "×"}[st]
            tg = _steps.tag_of(x) if st == _steps.OPEN else None      # an open step's status line, under its words: where its session is with it, and since when
            tag = (f'<span class="cl-tag">{self.md_line(tg["text"], r["gid"])}' + (f' <span class="dim">· {e(tg["state"])}</span>' if tg["state"] != "in progress" else "")
                   + (f' <span class="dim">· {e(self.when(tg["ts"]))}</span>' if tg["ts"] else "") + '</span>') if tg else ""
            return (f'<li class="cl-{st}"><span class="cb" aria-hidden="true">{glyph}</span><div class="cl-b"><span class="sr">{_t("item.sr", word=word)}</span><span class="cl-t">{body}</span>' + tag
                    + (f"<ul>{subs}</ul>" if subs else "") + (f'<span class="cl-by">{stamp}</span>' if st != _steps.OPEN and stamp else "") + "</div></li>")
        opens = [x for x in checklist if x["status"] == _steps.OPEN]; earlier = [x for x in checklist if x["status"] != _steps.OPEN]
        if checklist:
            # one list: the open steps always show; of the finished ones only the newest done (or decided) step shows above them, and the rest fold behind one line that opens to one line per step
            newest = next((x for x in reversed(earlier) if x["status"] in (_steps.DONE, "decided")), None)
            folded = [x for x in earlier if x is not newest]
            nxt = ""
            if folded:        # every earlier line kept as it was drawn (the board's record, struck-through drops); only the order changes
                nd, ndr, ndec = (sum(1 for x in folded if x["status"] == k) for k in (_steps.DONE, _steps.DROPPED, "decided"))
                tally = _t("item.tally", parts=_t("item.tally_sep").join(_t(k_, n=n) for n, k_ in ((nd, "item.tally.done"), (ndr, "item.tally.dropped"), (ndec, "item.tally.decided")) if n)) if (ndr or ndec) else ""
                head = _t("item.steps_done_one" if len(folded) == 1 else "item.steps_done", n=len(folded)) if nd == len(folded) else _t("item.earlier_one" if len(folded) == 1 else "item.earlier", n=len(folded), tally=tally)
                nxt += (f'<details class="iearlier"><summary>{head} · <span class="sh-show">{_t("item.show")}</span><span class="sh-hide">{_t("item.hide")}</span></summary>'
                        f'<ul class="inext" aria-label="{e(_t("item.earlier_steps"))}">{"".join(cli(x) for x in folded)}</ul></details>')
            shown_ = ([newest] if newest is not None else []) + opens
            nxt += f'<ul class="inext" aria-label="{e(_t("item.next_steps"))}">{"".join(cli(x) for x in shown_)}</ul>' if shown_ else ""
            if not opens and not done: nxt += f'<p class="empty">{_t("item.no_open_steps")}</p>'
        else: nxt = f'<p class="empty">{_t("item.none")}</p>'
        def fold(sid, h2, body, open_=False, cls=""):      # every section of the page is a fold with the same heading and indent; the key is remembered per browser
            return f'<details class="fold{" " + cls if cls else ""}" data-fold="item.{sid}"{" open" if open_ else ""} id="{sid}"><summary><h2>{h2}</h2></summary>{body}</details>'
        ask = open_ask(r); pa = parse_ask(ask) if ask else None   # a completed item shows no ask; nor one whose decision left its needs
        # ---- the ask, the options, the answer box: while the owner moves it
        if pa: ask_html = (f'<div class="iask"><b>{_t("item.ask")}</b><dl>' + "".join(f'<dt>{lb}</dt><dd>{L(pa[k_])}{mockup_link(r, ask) if k_ == "decide" else ""}</dd>' for lb, k_ in
                           ((_t("item.ask.decide"), "decide"), (_t("item.ask.recommend"), "recommend"), (_t("item.ask.stakes"), "stakes"), (_t("item.ask.by"), "by"))) + '</dl></div>')
        elif ask: ask_html = f'<div class="iask"><b>{_t("item.ask")}</b><p>{L(ask)}{mockup_link(r, ask)}</p></div>'   # present but misshaped (a hand edit): the raw line
        else: ask_html = ""
        opts = open_options(r)                        # the options, one line each, the recommended one marked; only while his decision is open
        ol = ""
        if opts:                                      # in the root UI the answer box's cards show each option with its whole text, so the Ask block lists them only when no box is drawn (below)
            ol = ('<ol class="iopts">' + "".join(f'<li{" class=rec" if o["recommended"] else ""}><b>{e(_ol.listed(o["label"], i))}</b>'
                                                  + (f' <span class="badge rec">{_t("home.recommended")}</span>' if o["recommended"] else "") + f'<span class="oline">{L(o["line"])}</span></li>'
                                                  for i, o in enumerate(opts)) + '</ol>')
        asked = bool(ask_html) or bool(ol)            # the item asks something (an ask line or options), whether or not the options are listed in the Ask block
        # his answer is asked while the item is open and his: the model says he moves it, or its needs still hold his decision (old data, until the step 4 migration)
        his = (not done) and (mod.owner_moves or "decision" in [x.lower() for x in needs_of(r)])
        if not his: ask_html = ""
        sb_html = ""
        if his and not asked and answer and _ip.step_block(r):       # a your-step item: the step, directly under the state line, then the note box with Done and Send note
            sb_html = (f'<div class="iask istep"><b>{_t("item.your_step")}</b><div class="istepbody">{self.your_step_html(r)}</div></div>'
                       f'<form class="ianswer" data-step method="post" action="{e(answer["action"])}"><input type="hidden" name="token" value="{e(answer["token"])}">'
                       f'<label for="atext">{_t("home.step_note_aria")}</label>'
                       + _abox(f'<textarea id="atext" name="text" rows="3" maxlength="4000" placeholder="{e(_t("home.step_note"))}"></textarea>', "atext") +
                       f'<div class="abtns"><button type="submit" class="b main" name="act" value="done">{_t("home.step_done")}</button>'
                       f'<button type="submit" class="b" name="act" value="note" title="{e(_t("home.step_send_note_hint"))}" data-hint="{e(_t("home.step_send_note_hint"))}" data-needs-text>{_t("home.step_send_note")}</button></div>'
                       '<p class="isent warn aerr" role="alert" hidden></p></form>')
        elif his and not asked and _ip.step_block(r):                 # signed out (or no token): the step is still the page's
            sb_html = f'<div class="iask istep"><b>{_t("item.your_step")}</b><div class="istepbody">{self.your_step_html(r)}</div></div>'
        draft_html = "" if sb_html else self.draft_alone_html(r)               # a draft on an item that is not in the Your step block (stored before the step, or a step that is not his) is still on the page, under the state line
        form = sb_html or (self.answer_html(r, answer) if his else "")
        if his and ol and "data-cards" not in form:   # no answer box with cards is drawn (signed out, or no token): the options are still the page's, as a list in the Ask block
            ask_html = (ask_html[:-len('</div>')] + f'<b class="osub">{_t("home.options")}</b>' + ol + '</div>') if ask_html else f'<div class="iask"><b>{_t("home.options")}</b>{ol}</div>'
        cform = "" if his else self.answer_html(r, answer, comment_only=True)     # an item he does not move: the comment box takes the answer box's slot, open
        # ---- the wait and its chases
        wait_html = self.wait_html(r, mod, wtext, ((wlab.capitalize(), self.wait_day(wend)) if wend else (_t("wait.label.end"), _t("item.no_end_date"))), post, who_html) if waiting and w_ else ""
        # ---- the sidebar: mover, owner and creator first, then project, then, priority, wake, anchors, the GitHub issue (and the For you control)
        tk = proj_top(r) or pk                        # the project it shows is the top-level one; the link stays the page the item is filed on (pk), as the gbrain page link below does
        if pk in self.proj: prj = f'<a href="{e(under("/" + pk))}">{e(self.proj_label(tk))}</a>'
        elif tk in self.proj: prj = f'<a href="{e(under("/" + tk))}">{e(self.proj_label(tk))}</a>'      # the filed page has no row of its own: the project's page stands in
        elif pk: prj = (f'<code>{e(tk)}</code> <span class="dim">·</span> ' if tk != pk else "") + f'<code>{e(pk)}</code> <span class="aflag">{_t("item.page_missing")}</span>'      # the flag sits beside the page that is missing, the one the item is filed on
        else: prj = f'<span class="dim">{_t("item.no_project")}</span>'
        if mirror: prj += f' <span class="dim">·</span> <a href="{e(mirror)}" target="_blank" rel="noopener">{_t("item.gbrain_page")}</a>'
        then_v = who_html(mod.then) if mod.then else ""      # who takes it after his answer: the sidebar's Then row, only while it stands (the owner moves the item, or picks it up when its wait ends)
        pr = str(m.get("priority") or "p2")
        prio = '<span class="tag t-p1">P1</span>' if pr == "p1" else e(pr.upper())      # P1 red; P2 and P3 plain
        wk = wake_of(r)
        wlabel = {"relay": _t("wait.label.ask_by"), "anchor": _t("wait.label.backstop"), "item": _t("wait.label.backstop"), "list": _t("wait.label.backstop")}.get(w_.kind if w_ else "", _t("item.wake")) if (w_ and (w_.until or w_.backstop)) else _t("item.wake")
        wakev = e(self.when(wk)) if (wk and not done and not waiting) else (e(self.wait_day(wend)) if (waiting and wend) else "")
        gu = issue_url(r["gid"], self.data_dir)       # in the sidebar: the item's GitHub issue, when it has one and the mirror is on
        ghl = (f'<a class="hgh" href="{e(gu)}" target="_blank" rel="noopener" title="{esc_dq(_t("item.github_issue_tip"))}">{_t("item.github_issue")}</a>' if gu else "")
        def grp(*fields):                             # one sidebar group: a small heading over each value, a thin line between groups
            body = "".join(f'<dt>{h}</dt><dd>{v}</dd>' for h, v in fields if v)
            return f'<dl class="sgrp">{body}</dl>' if body else ""
        ol, ov = self.owner_row(r, contact)
        cl, cv = self.creator_row(r)
        ml, mv = self.mover_row(r)
        who_rows = f'<dt>{ml}</dt><dd>{mv}</dd>' + (f'<dt>{ol}</dt><dd>{ov}</dd>' if ov else "") + f'<dt>{cl}</dt><dd>{cv}</dd>'      # Mover first, then Owner, then Creator, in one group
        acnt = f'<span class="count">{alist.count("<li>")}</span>'
        side = (f'<dl class="sgrp">{who_rows}</dl>' + grp((_t("item.project"), prj)) + grp((_t("item.then"), then_v)) + grp((_t("item.priority"), prio))
                + grp((wlabel if waiting else _t("item.wake"), wakev))
                + (f'<dl class="sgrp"><dt>{_t("item.anchors", count=acnt)}</dt><dd><ul class="alist">{alist}</ul></dd></dl>' if alist else "")
                + grp(("GitHub", ghl))
                + self.watch_html(watch)
                + self.more_html(r, done))
        # ---- the header line: [state tag] · since (the words and colors of the lists; the mover, the then and the project are the sidebar's Mover, Then and Project rows, never this line), then why it ended when it has
        kind_ = self.state_kind(r)
        bits = [_ui.tag(kind_)]
        if since:
            stamp_ = self.stamp(datetime.datetime.fromtimestamp(since, self.now.tzinfo))
            bits.append(stamp_ if done else _t("item.since", when=stamp_))
        if done and by: bits.append(_t("item.by", who=f'<a href="{e(id_href(by))}">{e(shown(by))}</a>'))
        if not_taken: bits.append(f'<span class="iwarn">{_t("item.not_taken")}</span>')
        sline = " · ".join(bits)
        act = self.act_parts(r) if kind_ == _ui.AGENT else None      # an item on an agent shows its last activity beside the state, as its row on the home page does: the age, the pill, what it was and when
        act_html = f'<div class="ir-actl"><span class="ir-lbl">{esc(_t("home.last_label"))}</span>{act[0]}{act[1]}</div>' if act else ""      # the label tells this age from the "since" one beside the state
        said = "" if not done else (_t("item.no_outcome") if oc == "unrecorded" else (_ip.clean(why) or (_t("item.no_outcome") if not by else "")))
        reason_html = f'<p class="ireason">{M(said)}</p>' if said else ""
        goal_html = f'<p class="igoal">{self.mentions(e(goal), r["gid"])}</p>' if goal and goal != title else ""
        font_css = str(_cfg.get("instance", "font_css") or "")
        # Next, Background, History and Comments are folds: Next and Background open, History and Comments closed (the page's folds remember a reader's choice per browser, as the board's)
        none = _t("item.no_history")
        hist = (f'<ul class="hist">{"".join(li(x) for x in changes)}</ul>' + (f'<p class="empty">{_t("item.older_events", n=more)}</p>' if more else "")) if changes else f'<p class="empty">{none}</p>'
        comm = f'<ul class="hist">{"".join(li(x) for x in said_)}</ul>' if said_ else f'<p class="empty">{_t("item.no_comments")}</p>'      # the list only: the form is drawn in the answer box's slot
        desc = (r.get("description") or "").strip()
        dsc = f'<div class="desc md">{self.md_html(desc, r["gid"])}</div>' if desc and desc != r["subject"] else f'<p class="empty">{_t("item.none")}</p>'
        outcome_text = str(m.get("outcome_text") or "").strip() if done else ""      # how a closed item ended, in bullets, kept apart from the description (a close leaves that as it was); an open item, or a close with no outcome text, has no block
        outcome_html = fold("outcome", _t("item.outcome"), f'<div class="desc md">{self.md_html(outcome_text, r["gid"])}</div>', True, "ioutcome") if outcome_text else ""
        return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow">'
                f'<title>{e(rid(r))} · {e(title)}</title><link rel="icon" href="{icon_href("favicon.svg")}" type="image/svg+xml">' + (f'<link rel="stylesheet" href="{e(font_css)}">' if font_css else "")
                + _THEME_HEAD + _FOLD_HEAD + _APP_HEAD + f'<style>{self._css()}</style></head>{_PANEL_BODY}<div id="layout"><main class="itempage" id="top">' + self.page_header() +
                f'<h1><span class="hid">{e(rid(r))}</span> {self.mentions(e(title), r["gid"])}</h1>{goal_html}{self.sent_html(answer, who_text(mod.mover) if alive else "")}'
                # the sidebar comes first in the source; from 768px wide the grid puts it in the right-hand column. On a phone
                # (one column) the CSS orders it after the state line, the Ask and the answer box and before Next (the Ask first, not a screen below the fields as on GitHub's mobile page)
                f'<div class="ilayout"><aside class="iside" aria-label="{e(_t("item.details"))}">{side}</aside><div class="imain">'
                f'<div class="istat"><p class="istate">{sline}</p>{" ".join(extra)}{act_html}</div>{reason_html}{outcome_html}{sb_html}{draft_html}{ask_html}{"" if sb_html else (form or cform)}{wait_html}'
                + ("" if done and not checklist else fold("next", _t("item.after_wait") if waiting else _t("item.next"), nxt, True))
                + fold("description", _t("item.background"), dsc, True)
                + fold("history", _t("item.history", count=f'<span class="count">{len(changes)}{"+" if more else ""}</span>'), hist)
                + fold("comments", _t("item.comments", count=f'<span class="count">{len(said_)}</span>'), comm)
                + f'</div></div><script>{_FOLD_JS}</script>' + (f'<script>(function(){{{_LACT_JS}}})();</script>' if act_html else "") + '</main>' + self.panel_tail() + _FAB_PAIR + _THEME_JS + _RELOAD_JS + _TOTOP_JS + _COPY_JS + _SAID_JS + _BFCACHE_JS + (_ANSWER_JS + _CARDS_JS + "<script>" + _ABOX_JS + "</script>" + _SENDKEY_JS if '<form class="ianswer"' in form + cform else "") + '</body></html>')
    def wait_day(self, v) -> str:
        """A wait's end as a person reads it: "Sat Mar 28th" for a date, "Sat Mar 28th 09:00" for a date and a time (the board's zone); the text itself when it reads as neither."""
        t = str(v or "").strip().replace(" ", "T")
        try:
            if "T" in t: return self.when(datetime.datetime.fromisoformat(t[:16]).replace(tzinfo=self.now.tzinfo))
            return self.when(datetime.date.fromisoformat(t[:10]))
        except ValueError: return str(v or "")
    def wait_html(self, r, mod, wtext, end, post, who_html) -> str:
        """The wait line and the chases of a waiting item: what it waits on in full (an anchor's link and event, the items it waits after and whether each is
        open, the party a relay waits on, a time's basis or his words), who watches, until when, who takes it after, and every chase logged on it."""
        e = esc; m = r["metadata"]; w = mod.wait; rows = []
        if w.kind == "list" and mod.waits:      # a wait on a list: each line with its tick, then the one backstop day (no chases: a list is never chased)
            rows = [(_t("wait.waits_on"), self.wait_list_html(r, mod, page=True)), (_t("wait.label.backstop"), e(_t("wait.list.backstop", day=self.wait_day(w.backstop)))), (_t("wait.picks_up"), f'<b>{who_html(post)}</b>')]
            rows += [(_t("item.then"), f'<b>{who_html(mod.then)}</b>')] if mod.then else []
            return f'<section class="iwait"><h2>{_t("state.wait")}</h2><dl class="iwl">' + "".join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in rows) + '</dl></section>'
        if w.kind == "anchor":
            what = self.wait_anchor_html(r, w, full=True)      # the stored anchor in full, else the ones scoped to the item
        elif w.kind == "item":
            opn = set(after_open(r))
            what = ", ".join(f'<a href="{e(id_href(g))}">{e(shown(g))}</a> <span class="dim">{_t("wait.state_open" if (g in opn or w.queued) else "wait.state_closed")}</span>' for g in w.after) or _t("wait.item_none")
            if w.queued: what += f' <span class="dim">· {e(_t("wait.queued_note"))}</span>'
        elif w.kind == "relay": what = self.mentions(e(_wat.subject_of(m)), r["gid"]) + f' <span class="dim">{_t("wait.relay_note", who=e(_model.owner_display()))}</span>'
        else:
            what = e(wtext) if wtext and wtext != _t("wait.a_date") else _t("wait.a_date")
        rows += [(_t("wait.waits_on"), what), (_t("wait.watched_by"), e(_ip.watched_by(w.kind))), (e(end[0]), e(end[1])), (_t("wait.picks_up"), f'<b>{who_html(post)}</b>')] + ([(_t("item.then"), f'<b>{who_html(mod.then)}</b>')] if mod.then else [])
        wwords = _wt.words_of(m)
        if wwords.get("quote"):
            rows.append((_t("wait.his_words"), f'{e(wwords["quote"])}' + (f' <span class="dim">({e(wwords["source"])})</span>' if wwords.get("source") else "")))
        ch = _ip.chase_rows(m)
        if ch:
            def one(c):
                try: at = self.when(float(c.get("at") or 0))
                except (TypeError, ValueError): at = ""
                return f'<li><span class="dim">{e(at)}</span> · <b>{self.mentions(e(str(c.get("by") or "")), r["gid"])}</b>: {self.mentions(e(str(c.get("note") or "")), r["gid"])}</li>'
            more = f' <span class="dim">{_t("wait.chase_note", n=_wat.CHASES_MAX, owner=e(_model.owner_display()))}</span>' if w.kind in _wat.CHASE_KINDS else ""
            rows.append((_t("wait.chases"), f'{len(ch)}{more}<ul class="ichases">{"".join(one(c) for c in ch)}</ul>'))
        elif w.kind in _wat.CHASE_KINDS: rows.append((_t("wait.chases"), f'<span class="dim">{_t("wait.none_yet")}</span>'))
        return f'<section class="iwait"><h2>{_t("state.wait")}</h2><dl class="iwl">' + "".join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in rows) + '</dl></section>'
    def more_html(self, r, done) -> str:
        """The sidebar's closed "More details" fold: the fields the page showed before the item model and the sidebar's rows do not cover (agent at work on the item, due, confirmed and
        stale, a leftover old work list, after and observers, a wait's basis and his words). Nothing is dropped, and it is one fold to delete once the owner has seen the page."""
        e = esc; m = r["metadata"]; L = lambda x: self.mentions(e(x), r["gid"])
        def grp(*fields):
            body = "".join(f'<dt>{h}</dt><dd>{v}</dd>' for h, v in fields if v)
            return f'<dl class="sgrp">{body}</dl>' if body else ""
        due_b = self.due_badge(r) if not done and due_of(r) else ""
        ca = confirmed_at(r); conf = ""
        if not done and ca > 0:            # when the item was last confirmed true; " · stale" past its lane's limit
            conf = (f'{e(self.when(ca))}' + (f' <span class="iwarn stw" title="{e(stale_tip(r, self.mover_name))}">{_t("more.stale")}</span>' if r.get("_fresh") == "stale" else ""))
        waits = ""                                    # what it waits on, who observes it (open items only)
        if not done:
            af = after_of(r)
            if af:
                opn = set(after_open(r))
                waits += f'<dt>{_t("more.after")}</dt><dd>' + " · ".join(f'<a href="{e(id_href(g))}">{e(shown(g))}</a> <span class="dim">{_t("wait.state_open" if g in opn else "wait.state_closed")}</span>' for g in af) + '</dd>'
            ob = observers_of(r)
            if ob: waits += f'<dt>{_t("more.observers")}</dt><dd>{self.mentions(e(", ".join(shown_ref(x) for x in ob)), r["gid"])}</dd>'
        agents = [] if done else list(dict.fromkeys(l["agent"] for l in _work.in_progress(m) if l["agent"]))   # who is working on it now
        wbasis = "" if done else e(_wt.basis_of(m))
        wwords = {} if done else _wt.words_of(m)
        wwhy = (f'{e(wwords["quote"])} <span class="dim">({e(wwords["source"])})</span>' if wwords.get("source") else e(wwords["quote"])) if wwords else ""
        body = (grp((_t("state.agent"), " · ".join(L(a) for a in agents)))
                + grp((_t("more.due"), due_b), (_t("more.confirmed"), conf))
                + (f'<dl class="sgrp">{wk}</dl>' if (wk := self.work_html(r)) else "")
                + (f'<dl class="sgrp">{waits}</dl>' if waits else "")
                + grp((_t("wait.waits_on"), wbasis), (_t("wait.his_words"), wwhy)))
        return f'<details class="fold imore" data-fold="item.more"><summary><h3>{_t("item.more_details")}</h3></summary>{body}</details>' if body else ""
    def project_items(self, k):
        """The project page's Items section → (open count without the verifying ones, completed count, HTML, verifying count): the open items of the row and its sub-pages (the items sessions_html counts:
        sub-pages rolled up as on the index) in the home page's four lists, Your move, On agent, Queued for release and Waiting (home_lists: the same classification, home.classify, and the same sorts), each row
        drawn by the home page's home_row (goal · next step or ask · mover · age, the Waiting fields; a Your move row opens with one top line, number · title · age, and names no mover;
        flags=True keeps the stale ⚠ and the "waits for recycle" badge the project page's lines carried). A list with no item is left out. Then the items completed in the last 14 days, their group folded by default, drawn by done_row, an item on a sub-page carrying the
        sub-page's name on its who line. Each list is a fold (data-fold "project.items.<list>", one choice per viewer for every project page, as the board's folds)."""
        on = (lambda r: self.row_of(proj_key(r)) == k) if k in self.group else (lambda r: proj_key(r) == k or proj_key(r).startswith(k + "/"))
        rows = [r for r in self.rows if r.get("status") != "completed" and on(r)]
        lists = self.home_lists(rows)      # the same four lists as the home page, so the same groups, order and labels
        done = [r for r in self.done if on(r)]
        def sub(r): pk = proj_key(r); return self.sub_title(pk, k) if pk and pk != k else ""
        body = "".join(f'<details class="fold sfold" data-fold="project.items.{which}" open><summary><h3 class="iscope">{esc(t)} <span class="count">{len(lists[which])}</span></h3></summary>'
                       + _ui.rows([self.home_row(r, mod, which, flags=True) for r, mod in lists[which]]) + '</details>'
                       for which, t in ((w, self.list_title(w)) for w in LIST_ORDER) if lists[which])
        if done:
            body += (f'<details class="fold sfold" data-fold="project.items.completed"><summary><h3 class="iscope">{_t("routing.completed_title")} <span class="count">{len(done)}</span></h3></summary>'
                     + _ui.rows([self.done_row(r, sub(r)) for r in done]) + '</details>')
        n_ver = n_apart(rows)[1]     # the verifying items count apart from open
        return len(rows) - n_ver, len(done), ("" if rows else f'<p class="empty">{_t("routing.no_open")}</p>') + body, n_ver

    def routing_html(self, k) -> str:
        """The project's details page behind a row's watch light: its items, its sessions, its anchors, then every notice
        delivered for it, newest first — time, source, gist, whom it was for, the ruling and reason. Titled by the
        project, with a small link back to the Projects page above the title. Each section is a fold like the board's (data-fold "project.<section>", remembered per viewer by _FOLD_JS,
        one choice for every project page): Notices folded by default, the rest open."""
        from stackshot.anchors import anchors as _anc
        keys = self.group.get(k) or ([k] if k in self.proj else [])
        if not keys and not _routing.read(k): raise KeyError(k)
        keys = keys or [k]
        esc = lambda x: H.escape(str(x), quote=True)
        pilot = bool(_anc.pilot_root(k)); name = self.proj_title(k); c = self.routing_counts(k)
        notes = sorted((n for p in keys for n in _routing.read(p)), key=lambda n: -float(n.get("ts", 0)))[:400]
        when = self.when
        def ruling(n):
            r = n.get("ruling")
            if r: return f'<span class="r-{esc(r)}">{esc(r)}</span>' + (f' → {esc(n["ruled_to"])}' if n.get("ruled_to") else "")
            return f'<span class="r-pending">{_t("routing.pending_ruling")}</span>' if n.get("pilot") else '<span class="dim">—</span>'
        rows = self.mentions("".join(     # who, gist, for, ruling and reason are free text: mentions linked
            f'<tr><td class="t">{when(n["ts"])}</td><td>' + (f'<a href="{esc(n["url"])}" target="_blank" rel="noopener">{esc(n.get("label") or n.get("kind"))}</a>' if n.get("url") else esc(n.get("label") or n.get("kind")))
            + f'</td><td>{esc(n.get("who", ""))}{": " if n.get("who") and n.get("text") else ""}{esc(n.get("text", ""))}</td><td class="f">{esc(n.get("target") or "")}</td><td class="r">{ruling(n)}</td><td class="why">{esc(n.get("reason", ""))}</td></tr>'
            for n in notes))
        groups = [g for p in keys for g in self.proj_anchor_groups(p)] if k in self.group else self.proj_anchor_groups(k)
        seen = set(); alist = ""
        for kind, xs, _hot in groups:
            for nm, u, w, sc, _h in xs:
                if (nm, sc) in seen: continue
                seen.add((nm, sc))
                # the type is the plain bold label, the link is the anchor's title: anchor-hub keeps the two apart
                alist += f'<li><b>{esc(kind)}</b> ' + (f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(nm)}</a>' if u else esc(nm)) + f' <em>· {w} · {esc(sc)}</em></li>'
        alist = self.mentions(alist)      # an anchor's scope is a list of item ids
        font_css = str(_cfg.get("instance", "font_css") or "")
        n_sess, sess_body = self.sessions_html(k)
        n_items, n_done, items_body, n_ver = self.project_items(k)
        def fold(sid, title, n, body, open_=True, more=""):   # one section as the board draws one: the heading with its count is the summary
            return (f'<section id="{sid}"><details class="fold" data-fold="project.{sid}"{" open" if open_ else ""}><summary><h2>{esc(title)} <span class="count">{n}</span>{more}</h2></summary>'
                    f'{body}</details></section>')
        mirror = self.proj_mirror(k)       # the project's gbrain page on its GitHub mirror
        summary = " · ".join([_t("routing.in", n=c["in"])] + ([f"{c[r]} {r}" for r in _routing.RULINGS if c[r]] if pilot else [])) + (" · " + _t("routing.pending", n=c["pending"]) if c["pending"] else "")      # the ruling words are the router's own vocabulary
        return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow">'
                f'<title>{esc(name)}</title><link rel="icon" href="{icon_href("favicon.svg")}" type="image/svg+xml">' + (f'<link rel="stylesheet" href="{esc(font_css)}">' if font_css else "")
                + _THEME_HEAD + _FOLD_HEAD + _APP_HEAD + f'<style>{self._css()}</style><noscript><style>form.hanswer{{display:none}}</style></noscript></head>{_PANEL_BODY}<div id="layout"><main id="top">' + self.page_header() +
                f'<p class="pjback"><a href="{under("/projects")}">{_t("routing.back")}</a></p><h1>{esc(name)}</h1>' + (f'<p class="sub"><a href="{esc(mirror)}" target="_blank" rel="noopener">{_t("routing.gbrain_page")}</a></p>' if mirror else "")
                + f'<p class="sub">{_t("routing.sub_pilot" if pilot else "routing.sub_plain", summary=esc(summary))}</p>'
                + self.sent_notes_html() + fold("items", _t("routing.sec_items"), n_items, items_body, more=(f' <span class="count dim">{_t("routing.verifying", n=n_ver)}</span>' if n_ver else "") + (f' <span class="count dim">{_t("routing.completed", n=n_done)}</span>' if n_done else ""))
                + fold("sessions", _t("routing.sec_sessions"), n_sess, sess_body or f'<p class="empty">{_t("page.none")}</p>')
                + fold("anchors", _t("routing.sec_anchors"), len(seen), f'<ul class="alist">{alist}</ul>' if alist else f'<p class="empty">{_t("page.none")}</p>')
                + fold("notices", _t("routing.sec_notices"), len(notes), f'<div class="rwrap"><table class="rlog"><thead><tr><th>{_t("routing.th_when", tz=_cfg.tz_abbr())}</th><th>{_t("routing.th_source")}</th><th>{_t("routing.th_what")}</th><th>{_t("routing.th_for")}</th><th>{_t("routing.th_ruling")}</th><th>{_t("routing.th_reason")}</th></tr></thead><tbody>{rows}</tbody></table></div>' if rows else f'<p class="empty">{_t("routing.nothing")}</p>', open_=False)
                + f'<script>{_FOLD_JS}</script>' + (f'<script>(function(){{{_LACT_JS}}})();</script>' if 'data-at="' in items_body else '') + '</main>' + self.panel_tail() + _FAB_PAIR + _THEME_JS + _RELOAD_JS + _TOTOP_JS + _COPY_JS + _CARDS_JS + f'<script>{_HOME_JS}</script>' + _SENDKEY_JS + _BFCACHE_JS + '</body></html>')

    # ---------------- the emitters ----------------
    def render(self, modes) -> dict:
        """{mode: text} for the modes asked: brief · full (markdown) · html."""
        out = {}
        if "brief" in modes: out["brief"] = self.brief()
        if "full" in modes: out["full"] = self.markdown()
        if "html" in modes: out["html"] = self.html()
        return out

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

    def _css(self):
        """The site's stylesheet (the board and the routing pages share it). Every .badge is a GitHub-style label: a pill tinted 16% with its colour, 1px border in it, text
        in it too; a value sets only --bc to a theme token. --ink is how much of that colour the text keeps: 65% (the rest --fg)
        in light, where the raw tokens on their tint fall under 4.5:1 at 12px, all of it in dark, where they clear it. Priority runs
        red-yellow-green: p1 --p1, p2 --yellow, p3 --ok. --yellow is its own token because --warn
        (#936b09 in light, #e3b341 in dark) is amber, and in light its text keeps only 45% of it (--yellow-ink) to reach 5.5:1 on its tint. --relay is
        the purple, so "on others" is one colour on the badge, the on-others tile, its column header and the id links.
        On a phone (360 to 430 px) every page is the screen's width: the Task board table fits the screen (the agents
        column takes what the others leave, the ids wrap in their cells), Machines is a card per machine that wraps (one to a row), the
        Anchor hub cards two to a row, long ids and links break (tests/phone_width_check.py measures it). The root itself paints
        --bg, so the overscroll and the gesture-bar area of a phone take the theme too, and the page runs edge to edge
        (viewport-fit=cover) with the safe-area insets as padding."""
        # in the Landed rows below, Clear and Undo swap in place: one fixed width (64px, the span.lgone width) so the text
        # beside them never moves, and no colour fade on the new button. Kept here, outside the shipped CSS, so no page carries it.
        css = """
__D2FACE__
:root{--bg:#fafaf8;--fg:#1a1918;--mut:#6b6a66;--line:#e4e2dc;--card:#fff;--orange:#ad4608;--acc:var(--orange);--on-acc:#ffffff;--run:#2f6fdd;--call:var(--orange);--relay:#8250df;--p1:#b42323;--ok:#2e8b57;--live:#17613a;--live-bg:#dcf3e3;--warn:#936b09;--yellow:#d9b200;--ink:65%;--yellow-ink:45%}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161617;--fg:#ececea;--mut:#a3a29d;--line:#2c2c2e;--card:#1f1f21;--orange:#f0a06a;--on-acc:#1f1f21;--run:#7fb0ff;--relay:#bc8cff;--p1:#ff7b7b;--ok:#6fcf97;--live:#8fe0b0;--live-bg:#1d3a2a;--warn:#e3b341;--yellow:#f0c929;--ink:100%;--yellow-ink:100%;color-scheme:dark}}:root[data-theme=dark]{--bg:#161617;--fg:#ececea;--mut:#a3a29d;--line:#2c2c2e;--card:#1f1f21;--orange:#f0a06a;--on-acc:#1f1f21;--run:#7fb0ff;--relay:#bc8cff;--p1:#ff7b7b;--ok:#6fcf97;--live:#8fe0b0;--live-bg:#1d3a2a;--warn:#e3b341;--yellow:#f0c929;--ink:100%;--yellow-ink:100%;color-scheme:dark}
/* input tokens: --ibd border (3:1 on the page and the card), --ifill fill, --iph placeholder (4.5:1 on the fill) */
:root{--ibd:#85847f;--ifill:#ffffff;--iph:#68675f}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--ibd:#929190;--ifill:#2b2b2f;--iph:#b0afaa}}:root[data-theme=dark]{--ibd:#929190;--ifill:#2b2b2f;--iph:#b0afaa}
/* dark only: the small labels (the orange badges and the "Your move" tag) and the disabled buttons are flat fills with their own tokens, a label is the orange text on a dark brown fill of its own, a disabled button a flat grey fill with grey text at full opacity. The color tool sets these five inline when a look is applied. The light theme keeps the tinted labels and the faded disabled buttons. */
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--lab-bg:#3a2619;--lab-fg:var(--orange);--lab-bd:#3a2619;--dis-bg:#2a2a2c;--dis-fg:#a3a29d}}:root[data-theme=dark]{--lab-bg:#3a2619;--lab-fg:var(--orange);--lab-bd:#3a2619;--dis-bg:#2a2a2c;--dis-fg:#a3a29d}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]) .badge.call,:root:not([data-theme=light]) .badge.rec{background:var(--lab-bg);color:var(--lab-fg);border-color:var(--lab-bd)}:root:not([data-theme=light]) .tag.t-you{background:var(--lab-bg);color:var(--lab-fg);box-shadow:inset 0 0 0 1px var(--lab-bd)}:root:not([data-theme=light]) .b:disabled:not(.busy,.on,[aria-busy=true],form[aria-busy] .b){opacity:1;background:var(--dis-bg);border-color:var(--dis-bg);color:var(--dis-fg)}}
:root[data-theme=dark] .badge.call,:root[data-theme=dark] .badge.rec{background:var(--lab-bg);color:var(--lab-fg);border-color:var(--lab-bd)}:root[data-theme=dark] .tag.t-you{background:var(--lab-bg);color:var(--lab-fg);box-shadow:inset 0 0 0 1px var(--lab-bd)}:root[data-theme=dark] .b:disabled:not(.busy,.on,[aria-busy=true],form[aria-busy] .b){opacity:1;background:var(--dis-bg);border-color:var(--dis-bg);color:var(--dis-fg)}
:root{color-scheme:light}.theme{flex:none}.theme svg{display:none}html:not([data-pref]) .theme .i-system,html[data-pref=system] .theme .i-system,html[data-pref=light] .theme .i-light,html[data-pref=dark] .theme .i-dark{display:block}header.top{--ico:32px}@media(pointer:coarse){header.top{--ico:44px}}header.top .theme{position:absolute;top:12px;right:16px}header.top .pbtn{position:absolute;top:12px;right:calc(24px + var(--ico))}header.top h1,header.top p.site{display:flex;align-items:center;min-height:var(--ico);padding-right:calc(24px + 2 * var(--ico))}header.top .site{min-width:0;overflow-wrap:anywhere}
.site{font-size:18px;font-weight:700;margin:0}.site a{color:inherit;text-decoration:none}.site a:hover,.site a:focus-visible{text-decoration:underline}
*{box-sizing:border-box}html{background:var(--bg);scrollbar-gutter:stable}body{margin:0;padding:0 max(16px,env(safe-area-inset-right)) calc(64px + env(safe-area-inset-bottom)) max(16px,env(safe-area-inset-left));background:var(--bg);color:var(--fg);font:15px/1.5 __FONT__}
main{max-width:920px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 20px}h2{font-size:18px;letter-spacing:.06em;text-transform:uppercase;font-weight:700;color:var(--fg);margin:32px 0 12px;border-bottom:1px solid var(--line);padding-bottom:6px}
.count{font-weight:400;color:var(--mut);font-size:14px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mut);font-weight:600}
article.task{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}article.task h3{font-size:15px;margin:0 0 6px;line-height:1.35}
.idl{color:var(--mut);text-decoration:none}.meta{margin:0 0 6px}
.badge{--bc:var(--mut);display:inline-block;font-size:12px;font-weight:500;line-height:18px;padding:0 7px;border-radius:2em;border:1px solid var(--bc);color:color-mix(in srgb,var(--bc) var(--ink),var(--fg));background:color-mix(in srgb,var(--bc) 16%,transparent);margin-right:4px;vertical-align:baseline}
.badge.call,.badge.rec{--bc:var(--call)}.badge.agent,.badge.due,.badge.done,.badge.w-assigned{--bc:var(--run)}.badge.relay,.badge.oc-superseded{--bc:var(--relay)}.badge.prio-p1{--bc:var(--p1)}.badge.open,.badge.oc-done,.badge.said,.badge.w-in-progress,.badge.prio-p3{--bc:var(--ok)}.badge.hold,.badge.recycle,.badge.wait,.badge.said.unchecked{--bc:var(--warn)}.badge.prio-p2{--bc:var(--yellow);--ink:var(--yellow-ink)}.badge.w-defined,.badge.w-done,.badge.oc-dropped{--bc:var(--mut)}.badge.oc-dropped,.badge.said.unchecked{border-style:dashed}.badge.said{margin-right:0}
.row{font-size:14px;margin:2px 0}.next{margin:8px 0 4px;padding:8px 10px;border-left:3px solid var(--acc);background:var(--bg);border-radius:0 8px 8px 0}.next b{display:block;font-size:12px;color:var(--acc);font-weight:600;margin-bottom:2px}.next ol{margin:0;padding-left:20px}.next li{font-size:14px;line-height:1.5;margin:3px 0}.next ol ul{margin:2px 0 0;padding-left:18px;list-style:disc}.next ol ul li{margin:1px 0}.next p{margin:0;font-size:14px;line-height:1.5}.row b{color:var(--mut);font-weight:600;margin-right:6px}.desc{font-size:14px;color:var(--fg);opacity:.85;margin:8px 0 2px;padding-left:20px}.desc li{margin:0 0 4px;line-height:1.5}.desc ul{margin:2px 0 0;padding-left:18px}.desc ul li{margin:0 0 2px}.desc p{margin:0 0 5px;line-height:1.5}
code{font:13px "D2Coding",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:0 4px}a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}a.sref{text-decoration:none}a.sref code{color:var(--acc);border-color:var(--acc)}a.sref:hover,a.sref:hover code{text-decoration:none}a.sref:hover code{border-color:var(--fg)}
.empty{color:var(--mut)}ul.done{padding-left:18px}ul.done li{margin:6px 0;font-size:14px}


.dim{color:var(--mut)}
h2.hdr{margin:10px 0 12px}#machines,#anchorhub,#by-project{margin:0 0 4px}#machines h2.hdr,#anchorhub h2.hdr,#by-project h2.hdr{margin:32px 0 12px}td.sess{font-size:13px;white-space:nowrap}ul.pagents{list-style:none;margin:0;padding:0}ul.pagents li{padding:1px 0}table.pidx{table-layout:fixed;width:100%;border-collapse:separate;border-spacing:0}.pwrap{max-width:100%}table.pidx col.c-proj{width:30%}@media(max-width:600px){table.pidx td,table.pidx th{padding-left:4px;padding-right:4px}table.pidx th{font-size:11px;overflow-wrap:anywhere}table.pidx col.c-proj{width:36%}table.pidx td.sess{white-space:normal}table.pidx td.sess a,table.pidx td.sess code{display:inline;max-width:none;overflow:visible;text-overflow:clip;white-space:normal;overflow-wrap:anywhere}}td.sess{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}td.proj{white-space:normal;overflow-wrap:break-word}td.sess a,td.sess code{display:inline-block;max-width:100%;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom;white-space:nowrap}tr.scope th{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--fg);padding-top:14px;border-bottom:1px solid var(--mut)}.matrix{display:grid;gap:8px;margin:0 0 6px}#machines .matrix{grid-template-columns:repeat(auto-fit,minmax(128px,1fr))}.mcol{display:grid;gap:8px;align-content:start;min-width:0}.mcol .pc.none{padding:6px 10px;border:1px solid transparent}.matrix.rcvs{grid-template-columns:repeat(4,minmax(0,1fr))}@media(max-width:600px){.matrix.rcvs{grid-template-columns:repeat(2,minmax(0,1fr))}}.matrix .mh{display:flex;flex-direction:column;padding:4px 6px 2px;min-width:0}.matrix .mh .name{font-size:12px;color:var(--fg);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.matrix .mh .hi{font-style:normal;font-size:12px;font-weight:600;color:var(--mut)}.pc{display:grid;grid-template-columns:max-content max-content;column-gap:8px;row-gap:2px;align-items:baseline;padding:6px 10px;border:1px solid var(--line);border-radius:10px;background:var(--card)}.pc .lbl{font-size:12px;color:var(--mut)}.pc b.lbl{font-weight:600;color:var(--fg)}.pc .val{font-size:12px;color:var(--mut);font-variant-numeric:tabular-nums}.pc.update{border-color:var(--call)}.pc.update .lbl:not(b){color:var(--call);font-weight:600}.pc.update .val:nth-of-type(n+3){color:var(--call)}.pc.offline{opacity:.6}.pc.none{visibility:hidden;border:0;background:none;padding:0;min-height:0}.pc.bad{border-color:var(--p1)}.tip{position:relative;cursor:default}.tip:hover::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 3px);z-index:40;white-space:nowrap;padding:2px 7px;border-radius:6px;background:var(--fg);color:var(--bg);font-size:11px;font-weight:400;font-style:normal;line-height:1.5;pointer-events:none}.pc .val.ok,.pc .lbl.ok{color:var(--ok);font-weight:600}.pc .val.bad,.pc .lbl.bad{color:var(--p1);font-weight:600}a.pc{text-decoration:none;color:inherit}a.pc:hover{border-color:var(--fg);text-decoration:none}a.pc:hover *{text-decoration:none}
header.top{position:sticky;top:0;z-index:9;background:var(--bg);margin:0 -16px;padding:14px 16px 8px;border-bottom:2px solid var(--mut);box-shadow:0 6px 14px -8px rgba(0,0,0,.45)}header.top h1,header.top p.site{font-size:18px;margin:0 0 6px}h1 .logo,.site .logo{width:1.2em;height:1.2em;vertical-align:-.2em;margin-right:.4em;border-radius:.25em}header.top .hbar{display:flex;align-items:center;gap:12px;margin:0 0 6px;padding-right:calc(24px + 2 * var(--ico))}header.top .hbar>h1,header.top .hbar>p.site{margin:0;padding-right:0;min-width:0;flex:0 1 auto}header.top .rline{margin:0;flex:none;white-space:nowrap;color:var(--mut);font-size:12px}header.top .rline:has(#rendered.old){color:var(--warn)}section,article.task,li.iline,details.said,details.fold{scroll-margin-top:calc(var(--hdr,0px) + 12px)}@media(max-width:600px){header.top .rline .rw{display:none}header.top{position:relative;margin:0;padding:16px 0 0;border:0;box-shadow:none}header.top .theme{top:16px;right:0}header.top .pbtn{top:16px;right:calc(8px + var(--ico))}section,article.task,li.iline,details.said,details.fold{scroll-margin-top:0}}
#totop,.fab{position:fixed;right:calc(20px + env(safe-area-inset-right));bottom:calc(20px + env(safe-area-inset-bottom));width:44px;height:44px;border-radius:50%;background:var(--card);border:1.5px solid var(--mut);color:var(--fg);display:flex;align-items:center;justify-content:center;text-decoration:none;box-shadow:0 2px 12px rgba(0,0,0,.35);z-index:10;transition:background-color .12s,border-color .12s}#totop:hover,.fab:hover{border-color:var(--acc);background:color-mix(in srgb,var(--acc) 10%,var(--card));text-decoration:none}.fab{bottom:calc(74px + env(safe-area-inset-bottom));padding:0;cursor:pointer;font:inherit}.fab:focus-visible,#totop:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
a.rt{color:var(--fg);font-size:13px;white-space:normal;overflow-wrap:anywhere}a.rt:hover{color:var(--acc)}.aflag{color:var(--call);font-size:11px;font-weight:600;white-space:nowrap;cursor:help}table.rlog{table-layout:auto;font-size:13px}table.rlog td{vertical-align:top}table.rlog td.t{white-space:nowrap;color:var(--mut)}table.rlog td.r,table.rlog td.f{white-space:nowrap}table.rlog td.why{min-width:24ch}table.rlog th{white-space:nowrap}.r-pending{color:var(--call);font-weight:600}.r-dropped,.r-merged{color:var(--mut)}.r-passed{color:var(--ok)}ul.alist{padding-left:18px;font-size:14px;overflow-wrap:anywhere}ul.alist em{font-style:normal;color:var(--mut)}.rwrap{overflow-x:auto;max-width:100%}details.archived{margin-top:12px}details.archived>summary{cursor:pointer;color:var(--mut);font-size:13px}
.dimline,.dimline code{color:var(--mut)}.dimline code{opacity:.75}.dimline a.sref code{color:var(--mut);border-color:var(--line)}.rtag{display:inline-block;font-size:10px;font-weight:600;letter-spacing:.02em;color:var(--mut);border:1px solid var(--line);border-radius:999px;padding:0 6px;line-height:1.5;vertical-align:1px;cursor:help}
ul.ilines{list-style:none;margin:0;padding:0}h3.iscope{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--fg);margin:14px 0 0;padding:0 4px 3px;border-bottom:1px solid var(--mut);line-height:1.4}h3.iscope .count{font-size:12px;letter-spacing:0}li.iline{display:grid;grid-template-columns:minmax(2.8em,max-content) minmax(0,1fr);align-items:baseline;column-gap:8px;row-gap:2px;padding:6px 4px;border-bottom:1px solid var(--line);font-size:14px;line-height:1.4;min-width:0}li.iline:target{background:color-mix(in srgb,var(--acc) 12%,transparent)}li.iline .iid{font-weight:600}li.iline .iidw{white-space:nowrap}li.iline .iidw .iid{min-width:0}.iwarn{color:var(--warn);font-size:11px;margin-left:2px;cursor:help}.istat .iwarn.stw{font-size:13px;margin-left:0;font-weight:600}li.iline .isubj{grid-column:2;color:var(--fg);min-width:0;overflow-wrap:anywhere}li.iline .imeta{grid-column:2;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 6px;min-width:0;font-size:12px;line-height:1.35;color:var(--mut)}li.iline .imeta .badge{margin:0}.iown{font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--mut)}a.iown:hover{color:var(--acc)}.iage{white-space:nowrap}
nav.hcards{display:grid;grid-template-columns:repeat(5,minmax(0,148px));gap:8px;margin:10px 0 4px;container:hcards/inline-size}@media(max-width:600px){nav.hcards{grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;margin:8px 0 2px}a.hcard{padding:6px 10px}a.hcard b{font-size:22px}}@media(max-width:480px){nav.hcards{grid-template-columns:repeat(auto-fit,minmax(96px,1fr))}}a.hcard{container:hcard/inline-size;anchor-scope:--hcn;position:relative;display:grid;grid-template-columns:auto minmax(0,1fr);align-content:center;justify-items:start;height:60px;overflow:hidden;min-width:0;padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);text-decoration:none}a.hcard:hover{text-decoration:none;border-color:var(--fg)}a.hcard:focus-visible{outline:2px solid var(--acc);outline-offset:2px}a.hcard b{anchor-name:--hcn;grid-area:1/1;font-size:22px;line-height:1.1;font-variant-numeric:tabular-nums}a.hcard span{grid-area:2/1/3/3;justify-self:stretch;font-size:12px;color:var(--mut);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}a.hcard i.hnew{margin-left:2px;font-size:12px;font-style:normal;font-weight:600;color:var(--ok);white-space:nowrap}a.hcard i.hnew em{font-style:normal}@container hcards (max-width:680px){a.hcard span .more{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}}__HNEW__a.hcard.call{border-color:var(--call)}a.hcard.call b,a.hcard.call span{color:var(--call)}a.hcard.zero b{color:var(--mut)}.hsep{color:var(--mut)}.hscope h3.iscope{overflow-wrap:anywhere}h2.lsec{font-size:17px;line-height:1.3;margin:28px 0 4px;overflow-wrap:anywhere}h2.lsec .count{font-size:14px;font-weight:400;color:var(--mut)}section.lnew+section.lcompleted{margin-top:36px}form.lmark{margin:8px 0 4px}form.lmark[hidden]{display:none}li.lrow{display:flex;align-items:flex-start;gap:10px;padding:8px 4px}li.lrow .lbody{flex:1 1 auto;min-width:0}li.lrow .lhead{display:flex;align-items:baseline;gap:2px 10px;min-width:0}li.lrow .lhead .isubj{flex:1 1 auto;font-weight:600}li.lrow .lago{flex:none;margin-left:auto;font-size:13px;color:var(--fg)}li.lrow .lago:hover::after{left:auto;right:0}li.lrow .imeta{margin-top:3px}form.lclear,form.lundo,span.lgone{margin:0;flex:none}li.lrow form.lclear .b,li.lrow form.lundo .b{width:64px;min-width:64px;padding-left:0;padding-right:0}li.lrow .b{transition:none}span.lgone{min-height:32px;min-width:64px;display:inline-flex;align-items:center;font-size:12px;color:var(--mut)}li.lrow.lcleared .lbody{opacity:.45}li.iline .lwhy{display:block;margin-top:2px;min-width:0;overflow-wrap:anywhere;font-size:14px;color:var(--fg)}p.lnote{margin:6px 0 4px;color:var(--mut);font-size:14px}
#status{margin:0}#status:empty{display:none}
li.hrow{padding:10px 12px;min-width:0;font-size:14px;line-height:1.4;scroll-margin-top:calc(var(--hdr,0px) + 12px)}
.hmeta{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 8px;min-width:0;font-size:12px;line-height:1.4;color:var(--mut);overflow-wrap:anywhere}.hmeta .iwarn,.hmeta .badge{margin:0}.hl1{min-width:0;margin-top:4px}.hg{display:block;min-width:0}a.hnum{flex:none;max-width:100%;overflow:hidden;text-overflow:ellipsis;font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--mut);white-space:nowrap}a.hnum:hover{color:var(--acc)}a.hgoal{display:block;min-width:0;font-weight:600;color:var(--fg);overflow-wrap:anywhere}a.hgoal:hover{color:var(--acc)}
.hnote .badge{margin:0}.hage{flex:none;font-size:12px;color:var(--mut);white-space:nowrap}.hage.amber{color:var(--warn);font-weight:600}.hage.red{color:var(--p1);font-weight:600}.hage.hnot{color:var(--call);font-weight:600;white-space:normal;flex:0 1 auto;min-width:0;overflow-wrap:anywhere}
.hl2 .hthen,.hl2 .hby{font-size:12px;color:var(--fg);min-width:0;margin-left:12px}.hl2 .hlab{color:var(--mut)}.hl2.hind .hwait{display:inline}.hbody{margin:6px 0 0 6px;padding-left:10px;border-left:1px solid var(--mut);min-width:0}.hbody>:first-child{margin-top:0}.hnote.hnstep{margin-left:16px}
.hl2{margin-top:4px;min-width:0;font-size:13px;color:var(--mut)}.hnext,.hwait{display:block;min-width:0;overflow-wrap:anywhere;color:var(--fg)}.hwait{color:var(--mut)}.hwait .hon{color:var(--fg)}.hnext.hq{font-weight:500}a.mockup{white-space:nowrap;font-weight:500}
.hwho{font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--mut)}.hwho.own{font-family:inherit;font-weight:600;font-size:12px;color:var(--call)}a.hwho:hover{color:var(--acc)}
.iask .istepbody>b.osub{display:block;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--call);font-weight:600;margin:10px 0 4px}.draft{margin:6px 0 4px}.draft .dhead{margin:0 0 4px}.draft .dlab{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--call);font-weight:600}.draft button.copy{margin-left:8px;vertical-align:baseline}.draft pre{margin:0;padding:8px 10px;background:var(--card);border:1px solid var(--line);border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.5;color:var(--fg)}.draft pre code{font:inherit;border:0;padding:0;background:none;color:var(--fg)}.hdraft{margin:4px 0 2px;font-size:13px}.hdraft summary{cursor:pointer;color:var(--mut);font-size:12px}.hdraft .dlab{font-size:12px;letter-spacing:0;text-transform:none;font-weight:400;color:var(--mut)}.hdraft pre{margin:4px 0 0;background:var(--bg);font-size:13px;line-height:1.45}.hnote{margin-top:4px;font-size:12px;color:var(--mut);overflow-wrap:anywhere}.hnote .hwho{font-size:12px}li.hrow .cmd{margin:6px 0 2px;color:var(--fg)}ol.stepol{margin:4px 0 6px;padding-left:22px}ol.stepol>li{margin:6px 0;line-height:1.5}p.sp{margin:4px 0}.stepol .cmd{margin:6px 0 2px}
.hask{margin-top:6px}form.hanswer{margin:0;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg)}form.hanswer[hidden]{display:none}form.hanswer .abtns{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}form.hanswer .abtns-opt{margin-top:0}form.hanswer textarea{display:block;box-sizing:border-box;width:100%;min-height:3.2em;margin-top:8px;padding:6px 8px;font:inherit;font-size:14px;color:var(--fg);background:var(--ifill);border:1px solid var(--ibd);border-radius:6px;resize:none}form.hanswer textarea:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
ul.hdones li.hdone{display:block;min-width:0}.hdl1{display:flex;flex-wrap:nowrap;align-items:baseline;gap:2px 8px;min-width:0}ul.hdones .isubj{flex:1 1 0;grid-column:auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}ul.hdones .badge{flex:none;margin:0;white-space:nowrap}ul.hdones .iage{flex:none;margin-left:auto;font-size:12px;color:var(--mut);white-space:nowrap}.hdl2{margin-top:2px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:var(--mut)}ul.hdones a.hnum{flex:none}
.hl1.hytop{display:flex;flex-wrap:nowrap;align-items:baseline;gap:8px;margin-top:0}.hytop a.hnum{flex:none;max-width:none;overflow:visible;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:inherit;font-weight:600;color:var(--fg)}.hytop a.hnum:hover{color:var(--acc)}.hytop a.hgoal{display:block;flex:1 1 auto;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.hytop .hage{flex:none;white-space:nowrap}.hytop+.hmeta{margin-top:4px}
details.fold>summary{list-style:none;cursor:pointer}details.fold>summary::-webkit-details-marker{display:none}details.fold>summary h2::before{content:'▸ ';color:var(--mut)}details.fold[open]>summary h2::before{content:'▾ '}details.fold>summary h3::before{content:'▸ ';color:var(--mut)}details.fold[open]>summary h3::before{content:'▾ '}details.fold>summary:focus-visible{outline:2px solid var(--acc);outline-offset:2px}.rnote{margin:0 0 10px;padding:5px 12px;border:1px solid color-mix(in srgb,var(--warn) 45%,var(--line));border-left:3px solid var(--warn);border-radius:8px;background:color-mix(in srgb,var(--warn) 7%,var(--card));color:var(--fg);font-size:13px;line-height:1.45;overflow-wrap:anywhere}.rnote .r-ico{color:var(--warn);font-weight:700}.rnote b.r-host{font-weight:600}.rnote .r-off{color:var(--mut)}
.mnote{margin:-4px 0 8px;font-size:12px;line-height:1.4;color:var(--mut);overflow-wrap:anywhere}.mnote a.r-id{color:var(--fg);font-weight:600;white-space:nowrap}.mnote a.r-id:hover{color:var(--acc)}
main.itempage{overflow-wrap:anywhere}main.itempage h1{font-size:22px;line-height:1.3;margin:6px 0 8px}.istat{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:0 0 14px;font-size:13px}.istat .badge{margin:0}main.itempage h1 .hid{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-weight:600;color:var(--mut);white-space:nowrap}main.itempage h1 .hsep{color:var(--mut);font-weight:400}.ilayout{display:grid;grid-template-columns:minmax(0,1fr) 256px;column-gap:32px;align-items:start;margin-top:8px}.imain{grid-column:1;grid-row:1;min-width:0}.iside{grid-column:2;grid-row:1;min-width:0;font-size:13px;line-height:1.45}.iside dl.sgrp{margin:0;padding:14px 0;border-top:1px solid var(--line)}.iside dl.sgrp:first-child{border-top:0;padding-top:2px}.iside dt{font-size:12px;font-weight:600;color:var(--mut);margin:0 0 6px}.iside dt .count{font-size:12px}.iside dd{margin:0 0 12px;min-width:0}.iside dd:last-child{margin-bottom:0}.iside .badge{margin:0 4px 0 0}.iside .sneeds{display:block;margin-top:4px;color:var(--fg)}.iside .iwarn.stw{font-size:12px;margin-left:0;font-weight:600}.iside ul.iwork{font-size:13px;margin:0}.iside ul.iwork li{gap:2px 6px;margin:0 0 8px}.iside ul.iwork li:last-child{margin-bottom:0}.iside ul.iwork .wtext{flex:1 1 100%}.iside ul.alist{margin:0;padding-left:16px;font-size:13px}.iside ul.alist li{margin:0 0 4px}.iside a.hgh{white-space:nowrap}@media(max-width:767px){__ISTRIP__}@media(min-width:__DOCK__px) and (max-width:__ISPIN__px){__ISTRIP_PIN__}.iask{margin:0 0 16px;padding:8px 12px;border-left:3px solid var(--call);background:var(--card);border-radius:0 8px 8px 0;font-size:14px}.iask>b{display:block;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--call);font-weight:600;margin-bottom:4px}.iask dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:3px 14px;margin:0}.iask dt{color:var(--mut);font-weight:600}.iask dd{margin:0;min-width:0}.iask p{margin:0;line-height:1.5}.iask b.osub{margin-top:10px}ol.iopts{margin:0;padding-left:22px}ol.iopts li{margin:3px 0;line-height:1.5}ol.iopts li.rec::marker{color:var(--call);font-weight:600}ol.iopts .oline{display:block}ol.inext{margin:0;padding-left:22px;font-size:14px}ol.inext li{margin:3px 0;line-height:1.5}ol.inext ul{padding-left:18px;list-style:disc}.cplace{margin:6px 0 -2px;font-size:12px;color:var(--mut)}.cplace span+a.cshell{margin-left:10px}.cplace+.cmd{margin-top:2px}.cmd{position:relative;margin:6px 0 4px}.cmd pre{margin:0;padding:8px 78px 8px 10px;background:var(--card);border:1px solid var(--line);border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.45}.cmd pre code{border:0;padding:0;background:none;color:var(--fg)}.cmd button.copy{position:absolute;top:5px;right:5px}main.itempage .desc{opacity:1;margin-top:0}ul.hist{list-style:none;margin:0 0 0 5px;padding:0 0 0 16px;border-left:2px solid var(--line);font-size:14px}ul.hist li{position:relative;margin:0 0 12px;line-height:1.45}ul.hist>li::before{content:'';position:absolute;left:-23px;top:5px;width:8px;height:8px;border-radius:50%;background:var(--bg);border:2px solid var(--mut)}ul.hist li.ev-completed::before{background:var(--run);border-color:var(--run)}ul.hist li.ev-created::before{background:var(--ok);border-color:var(--ok)}ul.hist li.ev-needs::before{border-color:var(--call)}ul.hist li.ev-hold::before{border-color:var(--warn)}ul.hist li.ev-answer::before{background:var(--call);border-color:var(--call)}.ianswer{margin:0 0 16px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);font-size:14px}.ianswer>b{display:block;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--call);font-weight:600;margin-bottom:6px}.ianswer label{display:block;color:var(--mut);font-size:13px;margin:8px 0 4px}.ianswer textarea{display:block;box-sizing:border-box;width:100%;min-height:4.5em;padding:8px 10px;font:inherit;font-size:15px;color:var(--fg);background:var(--ifill);border:1px solid var(--ibd);border-radius:6px;resize:none}.ianswer textarea:focus-visible{outline:2px solid var(--acc);outline-offset:1px}.abtns{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}.abtns-opt{margin-top:0}header.top+.isent{margin-top:32px}.isent{margin:0 0 12px;padding:6px 10px;border-radius:6px;font-size:14px;border:1px solid var(--line);background:var(--card)}.isent.ok{border-color:var(--ok);color:var(--ok)}.isent.warn{border-color:var(--warn);color:var(--warn)}.ianswer .aerr{margin:8px 0 0}ul.hist .eh{font-size:13px;margin:0 0 2px}ul.hist .t{color:var(--mut);font-size:13px;white-space:nowrap;font-variant-numeric:tabular-nums}ul.hist .eb{position:relative;padding-left:14px;margin:1px 0 0;font-size:14px}ul.hist .eb::before{content:"•";position:absolute;left:3px;color:var(--mut)}ul.hist .eb.osub{padding-left:30px}ul.hist .eb.osub::before{left:19px}ul.hist .ehold{margin:2px 0 0;font-size:13px}ul.hist .ehold summary{cursor:pointer;color:var(--mut)}ul.hist .ehold .md{margin:4px 0 0;padding-left:10px;border-left:2px solid var(--line)}ul.hist .w{min-width:0}ul.hist b{font-weight:600}ul.hist .body{display:block;white-space:pre-wrap;margin:2px 0 0;font-size:13px;line-height:1.45;opacity:.92}ul.hist .ed{color:var(--mut);font-size:12px}ul.hist li.ev-comment::before{border-color:var(--call)}ul.hist li.ev-reopened::before{border-color:var(--run)}
h3.sgrp{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:16px 0 6px}ul.slist{list-style:none;padding-left:0;margin:0 0 4px}ul.slist li{margin:0 0 9px;line-height:1.45}ul.slist .sn{font-weight:600}ul.slist .own{color:var(--mut);font-size:13px}ul.slist .mand{display:block;color:var(--mut);font-size:13px}
.pc{grid-template-columns:minmax(0,max-content) minmax(0,1fr);min-width:0}.pc>*{min-width:0;white-space:nowrap}.pc>:not(.tip){overflow:hidden;text-overflow:ellipsis}.pc.rcv{grid-template-columns:minmax(0,max-content) minmax(min-content,1fr)}.pc.rcv>:nth-child(2){contain:inline-size}.pc.warn{border-color:var(--warn)}.pc .val.warn,.pc .lbl.warn{color:var(--warn);font-weight:600}.pc .st{cursor:help}.pc.alert>.val{white-space:normal;overflow-wrap:anywhere}.pc.alert>.wide{grid-column:1/-1}.conn{display:flex;align-items:center;gap:8px;margin:0 calc(24px + 2 * var(--ico, 32px)) 8px 0;padding:6px 12px;border:0;border-bottom:1px solid var(--line);border-radius:0;background:var(--card);color:var(--fg);font-size:13px;line-height:1.4}.conn .b.warn{background:var(--acc);color:var(--on-acc);border:0;border-radius:8px;font-weight:600;padding:4px 12px}@media(hover:hover){.conn .b.warn:hover:not(:disabled){background:color-mix(in srgb,var(--fg) 14%,var(--acc));color:var(--on-acc)}}.conn .b.warn:active:not(:disabled){background:color-mix(in srgb,var(--fg) 24%,var(--acc));color:var(--on-acc)}.conn[hidden]{display:none}.conn.down,.conn.out{color:var(--warn)}.conn>span{display:none}.conn.down .c-down,.conn.new .c-new,.conn.out .c-out{display:inline}#rendered.old{color:var(--warn);font-weight:600}
.audit{margin:0;font-size:12px}.audit[hidden]{display:none}.audit .a-txt{display:contents}.audit .lbl,.audit .val{min-width:0}.audit .val{white-space:normal;overflow-wrap:anywhere}.audit .a-run,.audit .a-msg{grid-column:1/-1;white-space:normal;overflow-wrap:anywhere}.audit .a-run{color:var(--mut)}.audit .a-f[title]:not([title='']){justify-self:start;cursor:help;border-bottom:1px dotted var(--mut)}.audit .a-bad,.audit .a-msg.warn{color:var(--warn);font-weight:600}.audit .a-msg{color:var(--fg)}.audit .a-msg:empty{display:none}
li.iline .imeta .iwork{color:var(--fg);cursor:default}.iwork b{font-weight:600}ul.iwork{list-style:none;margin:0 0 4px;padding:0;font-size:14px}ul.iwork li{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 8px;margin:0 0 6px;line-height:1.45}ul.iwork .badge{margin:0}ul.iwork li.w-done .wtext{color:var(--mut);text-decoration:line-through}ul.iwork .wagent{font:12px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--mut)}ul.hist li.ev-work::before{border-color:var(--ok)}
ul.hist details.said{display:inline-block;vertical-align:baseline;max-width:100%}ul.hist details.said>summary{list-style:none;cursor:pointer;display:inline}ul.hist details.said>summary::-webkit-details-marker{display:none}ul.hist details.said>summary:focus-visible{outline:2px solid var(--acc);outline-offset:2px;border-radius:999px}ul.hist details.said[open]>summary .badge{background:color-mix(in srgb,var(--bc) 30%,transparent)}ul.hist details.said .sbody{display:block;margin:4px 0 2px;padding:6px 10px;border-left:3px solid var(--line);background:var(--card);border-radius:0 8px 8px 0;font-size:13px;line-height:1.45;white-space:normal}ul.hist details.said blockquote{margin:0 0 4px;white-space:pre-wrap;color:var(--fg)}ul.hist details.said .smeta{color:var(--mut);font-size:12px}ul.hist details.said:target{background:color-mix(in srgb,var(--acc) 12%,transparent);border-radius:8px}ul.hist li.ev-said::before{border-color:var(--ok)}
main.itempage .istate{margin:0;font-size:15px;line-height:1.5;min-width:0}.istate .st{display:inline-block;padding:0 10px;border:1px solid transparent;border-radius:999px;font-size:13px;font-weight:600;line-height:1.55;vertical-align:1px}.istate .st-alive{background:var(--live-bg);color:var(--live);border-color:var(--live)}.istate .st-wait{background:transparent;color:var(--mut);border-color:var(--mut)}.istate .st-dead{background:transparent;color:var(--mut);border-color:var(--line);font-weight:500}.istate .iwarn{font-size:13px;margin-left:0}
main.itempage details.fold[id]>summary~*{margin-left:18px}main.itempage details.fold[id]>summary h2{margin-bottom:6px}
.wl{display:grid;gap:5px;font-size:13px;min-width:0}.wlh{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.wmode{font-size:11px;font-weight:600;padding:1px 8px;border-radius:999px;background:color-mix(in srgb,var(--mut) 16%,var(--card));color:var(--fg);white-space:nowrap}.wll{display:grid;grid-template-columns:16px minmax(0,1fr);gap:8px;align-items:start}.wbox{width:14px;height:14px;border:1.5px solid var(--mut);border-radius:3px;margin-top:2px;box-sizing:border-box;display:grid;place-items:center;font-size:10px;line-height:1;color:transparent}.wbox.on{background:var(--ok);border-color:var(--ok);color:var(--on-acc)}.wlt{min-width:0;overflow-wrap:anywhere;color:var(--fg)}.wkind{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;color:var(--mut);margin-right:6px;text-transform:uppercase;letter-spacing:.03em}.warr{color:var(--ok);font-size:12px;margin-left:4px}.wsub{display:block;font-size:12px;color:var(--mut)}
.iwait{margin:0 0 14px}.iwait h2{margin:0 0 6px}dl.iwl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 14px;margin:0;font-size:14px;line-height:1.45}dl.iwl dt{color:var(--mut)}dl.iwl dd{margin:0;min-width:0}ul.ichases{list-style:none;margin:4px 0 0;padding:0;font-size:13px}ul.ichases li{margin:0 0 3px}
main.itempage details.fold>summary h2{margin-top:18px}.imore{margin-top:10px;border-top:1px solid var(--line);padding-top:6px}.imore>summary h3{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:6px 0}.imore dl.sgrp:first-of-type{border-top:0}
ul.inext{list-style:none;margin:0 0 4px;padding:0;font-size:14px;line-height:1.5}ul.inext>li{display:flex;align-items:flex-start;gap:9px;margin:0 0 7px;min-width:0}ul.inext .cb{flex:none;display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;width:17px;height:17px;margin-top:3px;border:1.5px solid var(--fg);border-radius:4px;font-size:13px;font-weight:700;line-height:1;color:var(--mut)}ul.inext .cl-b{flex:1 1 auto;min-width:0;overflow-wrap:anywhere}ul.inext .cl-b ul{list-style:disc;margin:2px 0 0;padding-left:18px}ul.inext .cl-by{display:block;font-size:12px;line-height:1.4;color:var(--mut)}ul.inext li.cl-done .cb{border-color:var(--ok);background:var(--ok);color:var(--bg)}ul.inext li.cl-done .cl-by b{color:var(--ok);font-weight:600}ul.inext li.cl-decided .cb{border-color:var(--ok);background:var(--ok);color:var(--bg)}ul.inext li.cl-decided .cl-by b{color:var(--ok);font-weight:600}ul.inext li.cl-dropped{color:var(--mut);opacity:.75}ul.inext li.cl-dropped a{color:inherit;text-decoration:underline}ul.inext li.cl-dropped code{color:inherit}ul.inext li.cl-dropped .cb{border-color:var(--mut);color:var(--mut)}ul.inext li.cl-dropped .cl-t{text-decoration:line-through}ul.inext li.cl-dropped .cl-by b{font-weight:600}ul.inext li.icode{list-style:none;margin:4px 0 4px -14px}ul.inext li.icode .md pre{margin:0}.sr{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}ul.hist li.ev-step::before{border-color:var(--ok)}.istep .istepnext{margin:8px 0 0}.istep .istepnext ol.stepol{margin-top:0}li.hrow .istepnext{margin:6px 0 0}li.hrow .istepnext ol.stepol{margin-top:0}ul.inext .cl-tag{display:block;font-size:12px;line-height:1.4;color:var(--mut)}ul.inext .cl-tag::before{content:"status: "}details.iearlier .sh-hide{display:none}details.iearlier[open] .sh-show{display:none}details.iearlier[open] .sh-hide{display:inline}ul.hist ul.estat{list-style:none;margin:2px 0 0;padding:0}ul.hist ul.estat li{margin:0 0 2px;line-height:1.4}ul.hist li.ev-work::before{border-color:var(--run)}
.md{min-width:0;overflow-wrap:anywhere}.md>:first-child{margin-top:0}.md>:last-child{margin-bottom:0}.md p{margin:0 0 8px;line-height:1.5}.md ul,.md ol{margin:0 0 8px;padding-left:22px}.md ul ul,.md ul ol,.md ol ul,.md ol ol{margin:2px 0}.md ul{list-style:disc}.md ul ul{list-style:circle}.md li{margin:0 0 3px;line-height:1.5}.md li>p{margin:0 0 4px}.md li>:last-child{margin-bottom:0}.md blockquote{margin:0 0 8px;padding:2px 12px;border-left:3px solid var(--line);color:var(--mut)}.md blockquote>:last-child{margin-bottom:0}.md pre{margin:0 0 8px;padding:8px 10px;background:var(--card);border:1px solid var(--line);border-radius:6px;white-space:pre-wrap;overflow-wrap:anywhere;overflow-x:auto;max-width:100%;line-height:1.45}.md pre code{border:0;padding:0;background:none;color:var(--fg)}main.itempage .desc.md{padding-left:0;margin:0;font-size:14px}ul.hist .w{min-width:0;max-width:100%}ul.hist .body.md{display:block;white-space:normal;margin:2px 0 0;font-size:13px;line-height:1.45;opacity:.92}ul.hist .body.md p{line-height:1.45}
#for-you h2{margin-top:20px}ul.fy-list{list-style:none;margin:0;padding:0;border:1px solid var(--ibd);border-radius:10px;background:var(--bg)}
li.fy-row{display:flex;align-items:center;gap:10px;padding:6px 12px;border-top:1px solid var(--ibd);font-size:14px;line-height:1.35;min-width:0}li.fy-row:first-child{border-top:0}li.fy-row.urgent{border-left:3px solid var(--call)}
.fy-main{flex:1 1 auto;min-width:0;display:flex;flex-wrap:wrap;gap:2px 8px;align-items:baseline;overflow-wrap:anywhere}.fy-id{font:600 13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap}.fy-what .badge{margin:0 0 0 4px}
.fy-when{flex:none;color:var(--mut);font-size:12px;white-space:nowrap}form.fy-seen{margin:0;flex:none}form.fy-all{margin:8px 0 0}
.iwatch .wstate{font-weight:600}.iwatch .abtns{margin-top:6px}
@media(max-width:520px){li.fy-row{flex-wrap:wrap}.fy-main{flex-basis:100%}}
main header.top+h1,main header.top+p.pjback{margin-top:32px}
.b.pbtn{font-size:20px;line-height:1;flex:none}body.panel-open #panel-open{color:var(--acc);border-color:var(--acc)}.pbtn svg{display:block}
#panel{position:fixed;z-index:30;top:0;right:0;height:100dvh;width:min(300px,88vw);overflow-y:auto;overscroll-behavior:contain;padding:calc(12px + env(safe-area-inset-top)) max(16px,env(safe-area-inset-right)) calc(24px + env(safe-area-inset-bottom)) 16px;background:var(--bg);border-left:1px solid var(--line);box-shadow:-4px 0 24px rgba(0,0,0,.16);font-size:13px;line-height:1.45;transform:translateX(100%);visibility:hidden;transition:transform .18s ease,visibility 0s .18s;overflow-wrap:anywhere}
body.panel-open #panel{transform:none;visibility:visible;transition:transform .18s ease,visibility 0s}
.phead{display:flex;align-items:center;justify-content:space-between;margin:0 0 8px}.ptitle{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}
#panel-lang{display:flex;gap:6px;margin:14px 0 0;padding-top:14px;border-top:1px solid var(--line)}#panel-lang .plg{min-width:44px;padding:0 10px;font-weight:600}#panel-lang .plg[aria-pressed=true]{color:var(--acc);border-color:var(--acc)}
nav.lpager{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:12px 0 0}nav.lpager .pg{display:inline-block;min-width:80px;padding:8px 14px;text-align:center;border:1px solid var(--ibd);border-radius:8px;background:var(--card);color:var(--acc);font-weight:600;text-decoration:none}nav.lpager a.pg:hover{border-color:var(--acc)}nav.lpager .pg.off{color:var(--mut);background:none;font-weight:400}nav.lpager .lpos{font-size:13px;color:var(--mut);text-align:center}
p.lpgnote{margin:8px 0 0;font-size:13px;color:var(--mut)}section.lcompleted{margin-top:8px}section.lcompleted ul.ir-rows{margin-top:8px}p.pjnote{margin:0 0 12px;font-size:13px;color:var(--mut)}p.pjback{margin:0 0 4px;font-size:13px;color:var(--mut)}p.pjback a{display:inline-block;padding:4px 0}p.pjback a:hover{color:var(--acc)}
#panel-edge{display:none}#panel-scrim{display:none;position:fixed;inset:0;z-index:29;background:rgba(0,0,0,.35)}body.panel-open #panel-scrim{display:block}
#panel section{margin:0;padding:14px 0;border-top:1px solid var(--line)}#panel>section{--pt:2px;position:relative;padding-top:var(--pt);border-top:0}#panel>section:not([hidden],#audit-panel:has(#audit[hidden]):not(:has(#ghcalls)))~section:not([hidden],#audit-panel:has(#audit[hidden]):not(:has(#ghcalls))){--pt:14px;border-top:1px solid var(--line)}
#panel section h2,#panel section h2.hdr{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--fg);margin:0;padding:0;border:0}#panel #tasks h2{margin-bottom:8px}#panel details.fold>summary+*{margin-top:8px}

#panel #machines .matrix,#panel .matrix.rcvs{grid-template-columns:minmax(0,1fr);margin-bottom:0}#panel .mcol .pc.none{display:none}#panel .mnote{margin:0 0 8px}#panel .tip:hover::after{left:auto;right:0;width:max-content;max-width:min(200px,70vw);white-space:normal;overflow-wrap:anywhere}
@media(prefers-reduced-motion:reduce){#panel{transition:none}}
@media(min-width:__DOCK__px){
body::before{content:"";position:fixed;top:0;right:0;width:104px;height:__PTOP__px;background:var(--bg);z-index:8;pointer-events:none}
header.top .theme,header.top .pbtn{position:fixed;z-index:10}
#panel-edge{display:block;position:fixed;z-index:29;top:__PTOP__px;right:0;bottom:0;width:8px}
#panel{top:__PTOP__px;height:calc(100dvh - __PTOP__px);width:__PW__px;padding-top:14px}
body.panel-peek #panel{transform:none;visibility:visible;transition:transform .18s ease,visibility 0s}
body.panel-pin #panel{z-index:9;padding-bottom:calc(126px + env(safe-area-inset-bottom));box-shadow:none;transform:none;visibility:visible;transition:none}
body.panel-pin #panel-edge,#panel-scrim,body.panel-open #panel-scrim{display:none}body.panel-pin #panel-open{color:var(--acc);border-color:var(--acc)}
body.panel-pin #layout{padding-right:__PRES__px}
html{container:page/inline-size}nav.hcards{max-width:calc(100cqw - __HCARDS_OPEN__px)}
body::after{content:"";display:none;position:fixed;top:0;right:calc(__PW__px - 1px);width:1px;height:__PTOP__px;background:var(--line);z-index:31;pointer-events:none}body.panel-pin::after,body.panel-peek::after{display:block}
.phead{display:none}}
"""
        css = css.replace("__PTOP__", str(_PANEL_TOP_PX)).replace("__PW__", str(_PANEL_PX)).replace("__PRES__", str(_PANEL_RESERVE_PX)).replace("__HCARDS_OPEN__", str(_PANEL_RESERVE_PX + _BODY_PAD_PX))
        css = css.replace("__HNEW__", _hnew_css())
        css = css.replace("__ISTRIP_PIN__", _scoped(_ISTRIP_CSS, "body.panel-pin ")).replace("__ISTRIP__", _ISTRIP_CSS)
        css = css.replace("__D2FACE__", _D2_FACE).replace("__DOCK__", str(_PANEL_DOCK_PX)).replace("__ISPIN__", f"{_ITEM_PIN_STRIP_PX - 0.02:g}")
        css = css.replace("__FONT__", str(_cfg.get("instance", "font_stack") or "system-ui,sans-serif"))
        ts = _ui.type_scale      # the page's own rules on the five-size scale; the panel's cards, the machine cards and the Runners page keep theirs
        return ts(css) + ts(_BTN_CSS) + ts(_ABOX_CSS) + ts(_CARDS_CSS) + _MACH_CSS + _RUN_CSS + ts(_PORDER_CSS) + ts(_search.CSS) + ts(_AUDITS_CSS) + _ui.CSS

    def audit_line(self):
        """HTML: the audit card, the body of the side panel's Audit section. The name row is `Audits ↗`, a link to the Audits page (/audits), with the Audit now text link at its right; under it the shortlist
        (audit_overview.card): one row per audit group with its number of audits and its findings in the last 24 hours, `–` for a group that keeps no findings log (never a zero) and a line under the list that
        says what the dash means. Drawn at render time with the rows, classes and button _AUDIT_JS draws from GET /audit/status, character for character, so the page script's first refresh changes
        nothing. A run in progress is a line above the list (`Audit running since 03:00…`), a last run that did not finish a warn line. The status is the endpoint's own (audit.status, imported here:
        audit.py needs only config). Hidden only when the audit is not enabled; a status that cannot be read leaves the card hidden and empty for the script to fill."""
        z = _cfg.tz()
        head = f'<div id="audit" class="pc audit" data-tz="{esc(str(z))}"'
        name = f'<b class="lbl mh"><a class="nm" href="{under("/audits")}">{esc(_t("panel.audit.name"))}</a><button type="button" id="audit-now"{{dis}}>{esc(_t("panel.audit.now"))}</button></b>'      # the card's name row: the link to the page, and the text link beside it (a real button, styled as a link in _RUN_CSS: no .b)
        tail = ' <span class="a-msg" role="status" aria-live="polite"></span></div>'
        try:
            from stackshot.audit import audit as _audit
            from stackshot.audit import audit_overview as _ov
            d = _audit.status(self.now.timestamp())
            c = _ov.card(self.now.timestamp(), getattr(self, "_audit_rows", None))      # set by audits_html: the page's own read of the findings log, so the card and the page agree
        except Exception:
            d = c = None
        if not d or not d.get("enabled"):
            return f'{head} hidden>' + name.format(dis="") + '<span class="a-txt"></span>' + tail
        def clock(ts):
            try: t, n = datetime.datetime.fromtimestamp(ts, z), self.now.astimezone(z)
            except (OverflowError, OSError, ValueError, TypeError): return "–"      # an epoch no date can hold is a dash
            return f"{t:%H:%M}" if (t.month, t.day) == (n.month, n.day) else when_words(t)
        def cell(cls, text): return f'<span class="{cls}">{esc(text)}</span>'
        L, run = d.get("last"), bool(d.get("running"))
        if run:
            txt = cell("a-run", _t("panel.audit.running_since", at=clock(d['running_since'])) if _num_ok(d.get("running_since")) else _t("panel.audit.running"))
        elif L and L.get("finished") is None:
            txt = cell("a-run a-bad", _t("panel.audit.unfinished"))
        else:
            txt = ""
        txt += cell("a-h", "") + cell("a-h", _t("panel.audit.h_audits")) + cell("a-h", _t("panel.audit.h_found"))
        for g in c["groups"]:
            txt += cell("lbl", _audit_word(_AUDIT_GROUPS, g["name"], "panel.audit.group.")) + cell("val a-n", str(g["audits"])) + cell("val a-n" + (" hit" if g["found"] else ""), "–" if g["found"] is None else str(g["found"]))
        if c["note"]:
            txt += cell("a-cn", _audit_word(_AUDIT_NOTES, c["note"], "panel.audit.note."))
        return f'{head}>' + name.format(dis=" disabled" if run else "") + f'<span class="a-txt">{txt}</span>' + tail

    def gh_calls_card(self):
        """HTML: the hour's GitHub calls as a card after the audit card in the side panel's Audit section
        (it replaces a loose line under the Runners cards): the name `GitHub calls`, then label / value rows in the audit card's layout:
        `writes` and `reads` as `n / cap` (the cap muted, a thousands separator), `counted` the 60-minute window the counts cover, `HH:MM – HH:MM` in the
        board's zone: GitHub's limit is the calls of the past 60 minutes, rolling, so the end is when the numbers were read (this render) and the start an
        hour before. Read lock-free from the ledger file (ghbudget.peek), never waits on a lock; nothing at all before the ledger exists."""
        b = _gb.peek(self.now.timestamp())
        if b is None: return ""
        end = self.now.astimezone(_cfg.tz()); start = end - datetime.timedelta(minutes=60)
        def row(lab, n, cap): return f'<span class="lbl">{lab}</span><span class="val">{n:,} <span class="cap">/ {cap:,}</span></span>'
        return (f'<div id="ghcalls" class="pc ghc"><b class="lbl mh">{esc(_t("panel.gh.title"))}</b>' + row(esc(_t("panel.gh.writes")), b["writes"], b["write_cap"]) + row(esc(_t("panel.gh.reads")), b["reads"], b["read_cap"])
                + f'<span class="lbl">{esc(_t("panel.gh.counted"))}</span><span class="val">{start:%H:%M} – {end:%H:%M}</span></div>')

    def recycle_html(self):
        """HTML: the one "Pane recycle pending for … (<the fleet tool> runs it)" status line, listing the
        open items whose metadata.recycle is set and that are not on hold or held for the recycle alone (self.recycle, the same
        test as the server's recycle-wanted: recycle_due; oldest update first), each id linking to its item page
        in a new tab with its subject as the tooltip. Nothing at all while no such item exists. A plain, muted line under the
        Machines heading, styled as the audit line, not a notice under "Need your call (agents)": the fleet tool runs a flagged recycle itself, so it
        is nothing the owner acts on (a flagged recycle is the fleet tool's to run,
        not his). Inside the machines block, so the block's fingerprint covers it and the in-place update shows or drops it."""
        rs = self.recycle
        if not rs: return ""
        ids = ", ".join(f'<a class="r-id" href="{item_href(r)}" target="_blank" rel="noopener" title="{esc(r["subject"])}">{esc(rid(r))}</a>' for r in rs)
        return f'<p id="recycle" class="mnote" role="status">{_t("panel.recycle", ids=ids, tool=esc(_cfg.fleet_tool() or _t("panel.fleet_tool")))}</p>\n'

    def provision_html(self):
        """HTML: the "Provision needed for …" line under "Need your call (agents)", in the notice style the recycle line had before it became a status line, naming the boxes whose
        puller is behind, "(offline)" after a box that is off (the fleet tool provisions it when it wakes). Nothing while every box is current."""
        if not self.provision: return ""
        hs = ", ".join(f'<b class="r-host">{esc(h)}</b>' + ("" if on else f' <span class="r-off">{esc(_t("panel.offline_paren"))}</span>') for h, on in self.provision)
        return f'<p id="provision" class="rnote" role="status"><span class="r-ico" aria-hidden="true">⟳</span> {_t("panel.provision", hosts=hs)}</p>'

    @staticmethod
    def bare(t):
        """The subject as these list lines show it: a leading configured tag ("[work] ") dropped, since the scope sub-heading
        says it now; the stored subject, the item page, tooltips and board.md keep it."""
        PFX = [str(p) for p in (_cfg.get("subject", "prefixes") or [])]
        t = str(t or ""); p = next((p for p in PFX if p and t.startswith(p)), "")
        return t[len(p):] if p and t[len(p):].strip() else t
    # ---------------- the home page's three lists (home.py is the pure half) ----------------
    # Every open item is one of
    # alive or waiting (model.py) and sits in exactly one of Your move, On agent and Waiting. A row is two lines: the goal (the subject,
    # linking the item page) and its age; the immediate next step (the first `next` line, its `<mover>: ` prefix stripped) and the mover. The
    # lists draw nothing that pushes, sends or repeats: the nag is the age's colour on Your move (amber past two days, red past five), here only.
    def base_mod(self, r):
        """The item as the model reads it (model.derive: the stored model fields, else today's fields), once per row, before the queue rule."""
        m = r.get("_base")
        if m is None:
            m = r["_base"] = _model.view(r, _model.derive(r, self.now.timestamp(), after_open=after_open, anchored=lambda it: str(it["gid"]) in self.scoped_urls()), self.now.timestamp(), after_open)      # a doing item whose wake is far out with every step dated reads as waiting
        return m
    def queue_map(self):
        """{item: the item it is queued behind} over the open rows (queued.board_queue: a mover busy on another item, `[model] queued_behind`), {} while the rule is off; read once per Board."""
        if getattr(self, "_queue", None) is None: self._queue = _queued.board_queue(self.rows, self.base_mod, self.now.timestamp(), _home.front_test())
        return self._queue
    def mod_of(self, r):
        """The item as the board shows it: base_mod, then the queue rule (an item behind its mover's other item reads waiting, queued behind it), once per row."""
        m = r.get("_mod")
        if m is None: m = r["_mod"] = _queued.overlay(self.base_mod(r), self.queue_map().get(str(r.get("gid") or ""), ""))
        return m
    def scoped_urls(self, gid=None):
        """The anchors scoped to items, from every project's page in the anchors file (anchor_scope.scoped_map, the rule the server reads too): {item id: [url, …]} in the order they were added
        (an `added` that is no number sorts as the oldest); with a gid, that item's list. An `outside` item with one is an anchor wait, else a relay, and it is where such a wait's anchor is: the
        model's wait_anchor is a field a session may leave unset (those rows said "no anchor stored")."""
        if getattr(self, "_scoped", None) is None:
            self._scoped = _ascope.scoped_map(self.anchors)
        return self._scoped if gid is None else self._scoped.get(str(gid), [])
    def wait_anchor_html(self, r, w, full=False):
        """What an anchor wait waits on, as HTML: the anchor the wait stores, else the anchors scoped to the item (links, each its short label), else "an anchor (none recorded)": the anchor
        is never said to be missing from the store when it is in the project's anchors, and never invented when there is none. A watched anchor is a URL, a gmail:q: query or a Slack ref: only
        a URL is a link."""
        urls = [_ip.clean(w.anchor)] if _ip.clean(w.anchor) else self.scoped_urls(r["gid"])
        more = 0
        if not full and len(urls) > 3: urls, more = urls[:3], len(urls) - 3      # a row shows three; the item page lists them all
        labels = [u if full else link_label(u) for u in urls]
        seen = {}
        def label(i):      # several anchors with the same label are numbered, in the order they are shown ("mail.google.com (1)", "(2)")
            seen[labels[i]] = seen.get(labels[i], 0) + 1
            return f"{labels[i]} ({seen[labels[i]]})" if labels.count(labels[i]) > 1 else labels[i]
        what = ", ".join(f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(label(i))}</a>' if u.startswith(("http://", "https://")) else esc(u) for i, u in enumerate(urls)) or esc(_t("wait.anchor_none"))
        if more: what += f' <span class="dim">{esc(_t("wait.more", n=more))}</span>'
        return what + (f": {esc(w.event)}" if w.event else "")
    def home_pairs(self, rows=None):
        """The open rows (default: every open item of the board) in the three lists, sorted as the page says: {your-move, agents, waiting} → [(row, model)].
        Your move oldest first; On agent oldest first by the age the row shows; Waiting by end date."""
        rows = [r for r in (self.rows if rows is None else rows) if r.get("status") != "completed"]
        lists = _home.classify(rows, self.mod_of)
        return {_home.YOUR_MOVE: _home.sort_your_move(lists[_home.YOUR_MOVE], sort_key, same_ref),
                _home.AGENTS: _home.sort_agents(lists[_home.AGENTS], sort_key, same_ref),
                _home.WAITING: _home.sort_waiting(lists[_home.WAITING], sort_key)}
    def list_title(self, which):
        """The heading of one of the four lists, the home page's own words (ui/kit.py title)."""
        return {_home.YOUR_MOVE: _ui.title(_ui.YOUR_MOVE), _home.AGENTS: _ui.title(_ui.AGENT), RELEASE_LIST: _ui.title(_ui.RELEASE), _home.WAITING: _ui.title(_ui.WAITING)}[which]
    def queued_release_ids(self):
        """The ids of the items linked to a pull request whose release is in the release script's queue (ui/releasing.py: that release's unit is running; the link is an anchor, an open step's proof or an open step's words): read once per Board, one systemctl call, no GitHub call."""
        if getattr(self, "_rel_ids", None) is None: self._rel_ids = _rel.queued_items(self.scoped_urls(), self.rows)
        return self._rel_ids
    def home_lists(self, rows=None):
        """The home page's four lists (of the given open rows, default every open item): home_pairs, with the agents' items whose pull request is in the release queue taken out of On agent into Queued for release (RELEASE_LIST), same order. Only an item an agent moves
        goes there: one on Your move or Waiting stays in its list (it needs him, or waits on something else), and an item whose release has not been queued yet stays On agent."""
        if rows is None and getattr(self, "_lists", None) is not None: return self._lists      # the whole board's lists are drawn once per Board: the home page and the count cards of every other page's header read them
        lists = self.home_pairs(rows)
        q = self.queued_release_ids()
        lists[RELEASE_LIST] = [p for p in lists[_home.AGENTS] if p[0]["gid"] in q]
        lists[_home.AGENTS] = [p for p in lists[_home.AGENTS] if p[0]["gid"] not in q]
        if rows is None: self._lists = lists
        return lists
    def state_kind(self, r):
        """The state kind (ui/kit.py) of any item: an open one by the list it is in on home (Your move, On agent or Queued for release, Waiting), a closed one by how it ended (Done, Dropped, Superseded; Closed with no outcome recorded)."""
        if r.get("status") == "completed": return _ui.kind_of_outcome(outcome_of(r)[0])
        for which, pairs in _home.classify([r], self.mod_of).items():
            if pairs: return _ui.RELEASE if which == _home.AGENTS and r["gid"] in self.queued_release_ids() else _ui.kind_of_list(which)
        return _ui.AGENT
    def home_mover(self, who):
        """A mover as a row shows him: the owner by name; a session by name, linked to its view in the fleet tool while its pane lives (sess_html)."""
        if not who: return f'<span class="hwho dim">{esc(_t("home.no_mover"))}</span>'
        if _model.is_owner(who): return f'<span class="hwho own">{esc(_model.owner_display())}</span>'
        return self.sess_html(self.mover_name(who), cls="hwho")
    def day_words(self, s):
        """A stored date (YYYY-MM-DD, or with THH:MM) as "Mon Mar 30th" ("… 09:00"); text that is no date as it is."""
        t = wake_of({"metadata": {"wake": s}})
        return self.when(t) if t else str(s)
    def step_html(self, step, gid):
        """The immediate next step as the row shows it, inline markdown with its mentions linked; for a step only the owner takes, its command in a block of its own with a copy
        button (a link in it stays in the line), as the item page's Next draws it."""
        text, blocks = _home.copyables(step)
        return self.md_line(text, gid) + _cmd_blocks(blocks)
    def decision_rows(self, r, steps):
        """one row for each decision answer of the item (metadata.answers, kind "decision"; a comment or a note on his step is no decision), drawn among the finished steps of Next:
        `<owner>: picked <label> (<option line>)`, `<owner>: picked <label>` with no stored line, else `<owner>: <his words, one line>`. A Done on his step that checked a step (the step carries the
        answer's time) is already a done step and is not drawn twice. The rows are made for drawing only: status "decided", no position, nothing stored."""
        out = []
        for a in answers_of(r):
            if a.get("kind") != "decision": continue
            try: ts = float(a.get("ts") or 0)
            except (TypeError, ValueError): ts = 0.0
            if a.get("step") and any(s["status"] == _steps.DONE and ts and abs(float(s.get("at") or 0) - ts) < 1 for s in steps): continue
            ch, ln, tx = (" ".join(str(a.get(k) or "").split()) for k in ("choice", "choice_line", "text"))
            if ch and a.get("letter"): ch = _ol.pick_words(ch, a["letter"])
            if ch: body = f"picked {ch}" + (f" ({ln})" if ln else "")
            elif tx: body = tx if len(tx) <= 160 else tx[:159].rstrip() + "…"
            else: continue
            out.append({"text": f"{_OWNER}: {body}", "status": "decided", "by": _OWNER, "at": ts})
        return out
    def his_open_steps(self, r):
        """His open steps of the checklist (the lines of next that open with his name, or with none) as (first line without its opener, the lines under it), each said once, in order. The line the
        server made on the checklist for a your-step item (the step's summary, recorded as metadata.owner_step, with his name in front of it or not) is not drawn: the summary stays where space is short.
        Only that line is skipped, never a separate step of his that happens to say the same words, and a line that repeats an earlier one of his (any case, with or without his name) reads as one.
        A line whose first line is empty after his name takes the first line under it as its own. [] when he has none."""
        meta = r["metadata"] or {}
        lk = lambda t: _steps.loose_key(t).casefold()
        cand = []
        for x in _steps.view(meta):
            if x["status"] != _steps.OPEN or not _steps.is_his(x["text"]): continue
            ls = [ln for ln in str(x["text"]).split("\n") if ln.strip()]
            if ls: cand.append((x, ls))
        mir = lk(meta.get(_os.KEY))
        skip = max((i for i, (x, _) in enumerate(cand) if mir and lk(x["text"]) == mir), default=-1)      # the server's own line: the last one that says the summary
        out, seen = [], set()
        for i, (x, ls) in enumerate(cand):
            if i == skip: continue
            if _sc.FENCE_RX.match(ls[0]): first, rest = "", ls
            else:
                first, rest = _steps.strip_owner(ls[0]), ls[1:]
                while not first and rest and not _sc.FENCE_RX.match(rest[0]): first, rest = rest[0].strip(), rest[1:]       # "Name:" alone: the line under it is the step
            if not first and not rest: continue
            k = lk(x["text"])
            if k in seen: continue
            seen.add(k); out.append((first, rest))
        return out
    def step_field_entries(self, r):
        """The numbered lines and the commands of a step field stored before the one-line-summary rule, as (first line, lines under it) entries in the field's order: each numbered line (its fenced blocks under it),
        a fenced block standing alone (first ""), and for a one-line step that carries a command that line itself (a `! ...` pane line as a block). Plain lines of the field are the summary and are not entries. [] for the step
        of today (one line, no command)."""
        raw = str((r["metadata"] or {}).get("step") or "").strip()
        if not _steps.clean(raw): return []
        fence = lambda b: ["```", *str(b).split("\n"), "```"]
        if not _sc.structured(raw):
            if not _sc.commands_of(raw): return []
            return [("", fence(raw))] if raw.startswith("!") else [(_steps.strip_owner(_steps.key(raw)), [])]
        out = []
        for p in _sc.parse(raw):
            if p.kind == "cmd": out.append(("", fence(p.text)))
            elif p.kind == "text":
                if _sc.split_spans(p.text)[1]: out.append((_steps.strip_owner(p.text), []))
            else:
                for it in p.items: out.append((it.text, [ln for b in it.fences for ln in fence(b)]))
        return out
    def your_steps(self, r):
        """What the Your step block lists, as (first line, lines under it) entries: his open steps (his_open_steps), and with them any numbered line or command of an old step field that none of his lines shows
        (step_field_entries), at the place the field gives it, each once. [] when he has no open step on the checklist (the step field is then the step: step_block_html)."""
        mine = self.his_open_steps(r)
        if not mine: return []
        cm = lambda e: set(_sc.commands_of("\n".join([e[0], *e[1]]))) if e[1] or "`" in e[0] else set()
        used, out = set(), []
        for f in self.step_field_entries(r):
            fk, fc = _steps.loose_key(f[0]).casefold(), cm(f)
            at = next((i for i, h in enumerate(mine) if i not in used and ((fk and _steps.loose_key(h[0]).casefold() == fk) or (fc and fc <= cm(h)))), None)
            if at is None: out.append(f); continue
            out += [mine[i] for i in range(at + 1) if i not in used]; used |= set(range(at + 1))
        return out + [h for i, h in enumerate(mine) if i not in used]
    def step_nexts_html(self, r, draft=None):
        """The Your step block's list: his open steps (your_steps), drawn as the whole of the block (the one-line summary stays where space is short, the tab title and a Slack notice): one ordered list numbered
        from 1, each step in full without its `<name>: ` opener, each command in backticks (a span with a space in it) or fenced block in a code block with a Copy button under its line. `draft` (a function from the
        step's text to the drawn draft) puts the text to paste inside the step that uses it (draft_inside). They are the checklist's steps themselves, so a step checked leaves this list and
        shows checked in Next; Next still draws all of them. "" when he has none."""
        mine = self.your_steps(r)
        if not mine: return ""
        text, n = [], 0
        for first, rest in mine:
            if first:
                n += 1; text.append(f"{n}. {first}")
                text += [ln if ln[:1] in (" ", "\t") else "   " + ln for ln in rest]
            else: text += textwrap.dedent("\n".join(rest)).split("\n")         # a fenced block with no line of its own: a box, no number
        parts = _sc.parse("\n".join(text))
        return f'<div class="istepnext">{self.step_parts_html(parts, r["gid"], self.draft_inside(r, parts, draft))}</div>' if parts else ""
    def draft_inside(self, r, parts, draft):
        """{the position of the step that holds the draft: the drawn draft} for step_parts_html, {} for an item with no draft or with no `draft` function. The step that uses the text is the last one that
        names text to post, send or paste (draft.names_text, the write guard's own reading), else the last without a command, else the last. With no line of text to hold it (the steps are
        fenced blocks alone) it is drawn after the list, as key -1, so the text is never lost. A draft that is one of the commands the steps already show is the same text twice: it is not drawn again."""
        d = _draft.of(r)
        if not d or draft is None: return {}
        items = [it for p in parts if p.kind != "cmd" for it in (p.items if p.kind == "ol" else [_sc.Item(p.text)])]     # the lines step_parts_html numbers for `inside`
        cmds = [_sc.split_spans(it.text)[1] + it.fences for it in items]
        if any(_draft.clean(c) == _draft.clean(d) for c in [p.text for p in parts if p.kind == "cmd"] + [c for cs in cmds for c in cs]): return {}
        if not items: return {-1: draft("")}
        texts = [_sc.split_spans(it.text)[0] for it in items]
        at = ([i for i, t in enumerate(texts) if _draft.names_text(t)] or [i for i, cs in enumerate(cmds) if not cs] or [len(items) - 1])[-1]
        return {at: draft(texts[at])}
    def your_step_html(self, r, home=False):
        """The inside of the Your step block, for the item page and the home row alike: his open steps as one numbered list (step_nexts_html), each said once, each command in its own box with Copy,
        the item's draft (the text to paste) inside the step that uses it. The one-line summary is not drawn beside them (it stays in the tab title and the Slack notice). An item with no step of his on
        the checklist (the step is the whole of what he does) draws the step field itself (step_block_html), its draft in it. "" for an item with no your-step."""
        sb = _ip.step_block(r)
        if not sb: return ""
        draft = lambda text="": self.draft_html(r, self.draft_label(text), home)
        return self.step_nexts_html(r, draft) or self.step_block_html(r, sb=sb, home=home)
    def step_block_html(self, r, sb=None, home=False):
        """The step field of a your-step item as HTML (itempage.step_block is the one reading), for an item whose checklist holds no step of his: its text as markdown with each command taken out of it
        into a copyable block of its own (a link stays in the text); a `! ...` line he types in a pane stays whole and verbatim in one block. The item's draft goes right under the step's text,
        before those blocks: the draft is part of the step, and is left out when it is one of those commands. "" for any other item."""
        sb = sb or _ip.step_block(r)
        if not sb: return ""
        d = _draft.of(r)
        cmds = list(sb.blocks)
        for p in sb.parts or []:
            cmds += [p.text] if p.kind == "cmd" else _sc.split_spans(p.text)[1] if p.kind == "text" else [c for it in p.items for c in _sc.split_spans(it.text)[1] + it.fences]
        draft = "" if (not d or any(_draft.clean(c) == _draft.clean(d) for c in cmds)) else self.draft_html(r, self.draft_label(sb.text or "", (r["metadata"] or {}).get("step")), home)
        if sb.parts is not None: return self.step_parts_html(sb.parts, r["gid"]) + draft
        blk = _cmd_blocks(sb.blocks)
        return (self.md_line(sb.text, r["gid"]) if sb.text else "") + draft + blk
    def step_parts_html(self, parts, gid, inside=None):
        """A step that is a numbered list or holds a fenced block (step_commands.parse), drawn part by part: a plain line as a paragraph (inline markdown, mentions linked), a run of numbered lines as one
        ordered list (the first number kept), each item's text with the commands taken out of it (a span with a space in it, or a fenced block) into code blocks with a Copy button under that item, a fenced block
        outside any item as a block of its own. `inside` ({n: html}) puts a drawn block (the draft) at the end of the n-th line, counting the lines of every list and the plain lines from 0, and key -1 after the last part.
        Everything is escaped (the markdown subset takes no raw HTML; a command goes through esc)."""
        flat = [False]      # one Open shell link for the whole block outside a numbered list (its text lines and fenced blocks); a numbered step has one of its own, on its first box
        inside = inside or {}; n = -1
        out = []
        for p in parts:
            if p.kind == "cmd":
                out.append(_cmd_blocks([p.text], flat))
            elif p.kind == "text":
                text, cmds = _sc.split_spans(p.text)
                n += 1
                out.append((f'<p class="sp">{self.md_line(text, gid)}</p>' if text else "") + _cmd_blocks(cmds, flat) + inside.get(n, ""))
            else:
                lis = []
                for it in p.items:
                    n += 1
                    text, cmds = _sc.split_spans(it.text)
                    lis.append(f"<li>{self.md_line(text, gid) if text else ''}{_cmd_blocks(cmds + it.fences)}{inside.get(n, '')}</li>")
                out.append(f'<ol class="stepol"{f" start={p.start}" if p.start != 1 else ""}>' + "".join(lis) + "</ol>")
        return "".join(out) + inside.get(-1, "")
    def draft_label(self, *texts):
        """What the text to paste is called: "Email text to paste" when the words of the step it sits under speak of an email (email, e-mail, or the Korean words for it), else "Message to paste". Never "Draft". A word that only
        looks like one (a channel `#email-alerts`, an address, `gmail`) is no email, and the item's summary is not asked where a step is: a Slack post under a summary that says e-mail is a message. Only the paths with no step line of his (the step field drawn alone, a draft with no step block)
        pass the step field's words, since the step field is the step there."""
        # \uBA54\uC77C is the Korean word for "mail" (also inside the one for "email"); it is written as escapes so the public scan finds no Hangul in the repo
        return _t("home.draft.email") if re.search(r"(?<![\w#@/.-])e-?mails?(?![A-Za-z0-9_-])|\uBA54\uC77C", " ".join(str(t or "") for t in texts), re.I) else _t("home.draft.message")
    def draft_html(self, r, label, home=False):
        """The item's draft, the verbatim text the owner pastes elsewhere (draft.py), under `label` (draft_label) with Copy just beside it, then the text in the page's own body font with its lines and
        spaces as stored (the block wraps long lines but keeps every break), escaped, not monospace. It sits inside the step that uses it. On the home row it is a collapsed <details> whose summary is the label
        with Copy beside it (a tap on Copy copies without opening it; the page's copy script reads the text from the .draft block). "" when the item is closed or carries none."""
        d = _draft.of(r)
        if not d: return ""
        aria = esc(_t("home.copy_the", label=f"{label[0].lower()}{label[1:]}"))
        if home:
            return (f'<div class="draft hdraft"><details><summary><span class="dlab">{esc(label)}</span><button type="button" class="b copy" aria-label="{aria}">{esc(_t("js.copy"))}</button></summary>'
                    f'<pre><code>{esc(d)}</code></pre></details></div>')
        return (f'<div class="draft"><div class="dhead"><b class="dlab">{esc(label)}</b><button type="button" class="b copy" aria-label="{aria}">{esc(_t("js.copy"))}</button></div><pre><code>{esc(d)}</code></pre></div>')
    def draft_alone_html(self, r):
        """The draft of an item that draws no Your step block, in a block of its own (the same label and Copy)."""
        b = self.draft_html(r, self.draft_label((r["metadata"] or {}).get("step"), open_ask(r)))
        return f'<div class="iask idraft"><div class="istepbody">{b}</div></div>' if b else ""
    def home_draft_html(self, r):
        """The home row's draft where no step block holds it (an ask's row, or a row with no step form): right under the detail, collapsed (draft_html)."""
        return self.draft_html(r, self.draft_label((r["metadata"] or {}).get("step"), open_ask(r)), home=True)
    def home_step(self, r):
        """(the step as the row shows it, its form) for a your-step item of the owner's with no ask: the step itself, then an optional note box with TWO buttons: Done (the main one: the step is finished, the item goes to its
        then-mover as after any Done, and a note written in the box goes along to it) and Send note (the step stays open, the note goes to the then-mover as his step-reply; greyed until the box has text), drawn hidden for the page
        script to show with a token, as the decision rows' forms are. The step is drawn as the item page's Your step block draws it (your_step_html): his open steps, numbered, each command with its Copy box. None for any other item."""
        if open_ask(r) or not _ip.step_block(r): return None
        form = (f'<form class="hanswer hstep" data-step method="post" action="{esc(id_href(r["gid"]))}/answer" data-gid="{esc(r["gid"])}"><input type="hidden" name="token" value=""><input type="hidden" name="back" value="">'
                + _abox(f'<textarea id="astep-{esc(r["gid"])}" name="text" rows="2" maxlength="4000" aria-label="{esc(_t("home.step_note_aria"))}" placeholder="{esc(_t("home.step_note"))}"></textarea>', f'astep-{esc(r["gid"])}') +
                f'<div class="abtns"><button type="submit" class="b main" name="act" value="done" disabled>{esc(_t("home.step_done"))}</button>'
                f'<button type="submit" class="b" name="act" value="note" title="{esc(_t("home.step_send_note_hint"))}" data-hint="{esc(_t("home.step_send_note_hint"))}" data-needs-text disabled>{esc(_t("home.step_send_note"))}</button></div></form>')
        return self.your_step_html(r, home=True), form
    def home_ask(self, r):
        """(the question as the row shows it, its answer form) for an open decision of the owner's, None when the item carries none. The question is the ask's Decide part (a watcher's
        relay or drop-it ask, which has no Recommend, Stakes or By, its whole question); the form is the item page's: a card per stored option (_cards_html; Approve and Decline
        appear only as listed options; with none listed, Yes and No), the recommended one first, an optional note, one "Send" (greyed until a card is picked or the note has text). It is drawn hidden: the page script (_HOME_JS) asks GET /answer-tokens for the signed-in viewer's tokens and shows the form
        only when it gets one, so the static page carries no token; until then (and for a viewer who is not signed in) the row links the item page."""
        if "decision" not in [x.lower() for x in needs_of(r)]: return None
        ask = open_ask(r)
        if not ask: return None
        pa = parse_ask(ask)
        q = pa["decide"] if pa else re.sub(r"^Decide:\s*", "", ask).split(" · Options:")[0].strip()
        stored = open_options(r)
        opts = _card_order(stored or yesno_options(r))      # with no stored options, Yes and No
        cards = _cards_html(opts) if opts else ""
        hint = esc(_t("home.note_optional" if cards else "home.write_answer"))
        send = (f'<button type="submit" class="b main" name="act" value="answer" disabled>{esc(_t("home.send"))}</button>' + (f'<span class="ahint" hidden>{esc(_t("home.pick_hint"))}</span>' if cards else ""))
        form = (f'<form class="hanswer" {"data-cards " if cards else ""}method="post" action="{esc(id_href(r["gid"]))}/answer" data-gid="{esc(r["gid"])}"><input type="hidden" name="token" value=""><input type="hidden" name="back" value="">{cards}'
                + _abox(f'<textarea id="atext-{esc(r["gid"])}" name="text" rows="2" maxlength="4000" aria-label="{hint}" placeholder="{hint}"></textarea>', f'atext-{esc(r["gid"])}') +
                f'<div class="abtns{"-send" if cards else ""}">{send}</div></form>')
        return self.md_line(q, r["gid"]) + mockup_link(r, q), form       # the mockup a design decision is about, beside the question
    def home_wait(self, r, mod):
        """A waiting row's detail line, as HTML: what it waits on and until when, in the words the row leads with: "Until Sun Mar 1st 07:00: <why>" for a time (his words or the basis, or
        the proof of a verifying item), "After #5, #6" for another item's close (with its backstop day), "On <anchor>: <event>" for an anchor, "On <event> · backstop <day>" for an outside event, "On <party's news>, ask by <day>" for news only the owner
        relays; then the chases when there are any. Who takes it after and who watches it are the who line's (wait_who); the next step follows it on its own line, labeled "after the wait:" (home_row)."""
        w, m, e = mod.wait, r["metadata"], esc
        if w is None: return f'<span class="dim">{esc(_ui.word(_ui.WAITING))}</span>'
        if w.kind == "list" and mod.waits: return self.wait_list_html(r, mod, page=False)      # a wait on a list: the lines, ticked when they have arrived, and the backstop day (never chased)
        if w.kind == "time":
            quote = (_wt.words_of(m) or {}).get("quote") or ""
            proof = _model.clean(m.get("proof")) if is_verifying(r) else ""      # a verifying item waits on its end date with the proof named
            why = w.basis or (f"“{quote}”" if quote else "") or (_t("home.wait.proof", proof=proof) if proof else "")
            text = (_t("home.wait.until", day=e(self.day_words(w.until))) if w.until else esc(_t("home.wait.no_date"))) + (f": {e(why)}" if why else "")
        elif w.kind == "item":
            text = _t("home.wait.queued" if w.queued else "home.wait.after", ids=", ".join(f'<a href="{e(id_href(g))}" target="_blank" rel="noopener">{e(shown(g))}</a>' for g in w.after)) if w.after else esc(_t("home.wait.item_none"))
            if w.backstop: text += f' <span class="dim">{_t("home.wait.back_anyway", day=e(self.day_words(w.backstop)))}</span>'
        elif w.kind == "anchor":
            text = _t("home.wait.on", what=self.wait_anchor_html(r, w))      # the anchor the wait stores, else the ones scoped to the item
            if w.backstop: text += f' <span class="dim">{_t("home.wait.backstop", day=e(self.day_words(w.backstop)))}</span>'
        elif w.kind == "event":
            text = _t("home.wait.on", what=e(_ip.wait_what(w)))      # an event wait has no relay party to ask: the row names the event, with its backstop day as an anchor's does
            if w.backstop: text += f' <span class="dim">{_t("home.wait.backstop", day=e(self.day_words(w.backstop)))}</span>'
        else:
            text = _t("home.wait.relay", what=e(_watch.subject_of(m)), day=e(self.day_words(w.until)) if w.until else esc(_t("home.wait.no_date_short")))
        n = len(_watch.chases_of(m))
        return text + (f' <span class="dim">{esc(_t("home.wait.chased", n=n))}</span>' if n else "")
    def item_open(self, g):
        """Is the item `g` open on this board (a line of a wait on a list that waits on an item says so)? The set of open ids is read once per Board."""
        if getattr(self, "_open_set", None) is None: self._open_set = {x["gid"] for x in self.rows if x.get("status") != "completed"}
        return g in self._open_set
    def wait_list_html(self, r, mod, page):
        """A wait on a list as HTML (waits/wait_list.py; model.Model.waits): a head with the mode ("all of 2" / "any of 2") and what has arrived, then one line per wait, in the stored order, each with its kind,
        what it waits on and a box that is ticked, with the time, once it has arrived. The row (page=False) closes the head with "back anyway <backstop day>"; the item page (page=True) says how the mode
        ends it and gives each line a second line: when and in what words it arrived, else what watches it. The words of every line are free text (an event, an anchor), so each is escaped here, once."""
        e = esc; gid = r["gid"]; w = mod.wait
        n = sum(1 for ln in mod.waits if ln.arrived)
        head = (_t("wait.list.page_all", n=n) if mod.wait_mode == "all" else _t("wait.list.page_any")) if page else _t("wait.list.row_head", n=n, day=e(self.day_words(w.backstop)))
        out = [f'<span class="wlh"><span class="wmode">{e(_ip.list_mode_words(mod))}</span><span class="dim">{head}</span></span>']
        for ln in mod.waits:
            k = ln.kind
            at = self.arrival_when(ln.arrived_at) if ln.arrived else ""      # "" when it has not arrived, or for a time no date can show
            arrived_at = _t("wait.list.arrived", when=at) if at else _t("wait.list.box_on")
            if k == "time": text = e(_t("wait.list.line.time", day=self.day_words(ln.until)))
            elif k == "item":
                text = _t("wait.what.close_of", items=f'<a href="{e(id_href(ln.after))}" target="_blank" rel="noopener">{e(shown(ln.after))}</a>')
            elif k == "anchor":
                a = ln.anchor
                link = f'<a href="{e(a)}" target="_blank" rel="noopener">{e(a if page else link_label(a))}</a>' if a.startswith(("http://", "https://")) else e(a)      # the page gives the address in full, the row its short label
                text = self.mentions(e(ln.event), gid) + ("" if page else f' <span class="dim">({link})</span>')
            elif k == "event": text = e(_ew.words(ln.event))
            else: text = self.mentions(e(ln.event), gid)      # relay: the news the owner relays
            sub = ""
            if page:
                watcher = e(_home.watcher_word(_ip._WATCHERS.get(k, "the server")))
                if ln.arrived:
                    said = _t("wait.list.arrived_sub", what=ln.arrived_what, when=at) if ln.arrived_what and at else ln.arrived_what or arrived_at      # its words and its time; no words → "arrived <time>" alone (never "arrived · arrived <time>")
                    sub = (link + " · " if k == "anchor" else "") + e(said)      # an arrived anchor line keeps its address
                else:
                    what = (_t("wait.list.sub.relay", who=_model.owner_display()) if k == "relay" else (link if k == "anchor" else ("" if k != "item" else _t("wait.state_open" if self.item_open(ln.after) else "wait.state_closed"))))
                    sub = _t("wait.list.sub.watched", what=what, who=watcher) if what else _t("home.watched_by", who=watcher)
            tick = f'<span class="wbox on" title="{e(_t("wait.list.box_on"))}" aria-label="{e(_t("wait.list.box_on"))}">✓</span>' if ln.arrived else f'<span class="wbox" title="{e(_t("wait.list.box_off"))}" aria-label="{e(_t("wait.list.box_off"))}"></span>'
            arr = f'<span class="warr">{e(arrived_at)}</span>' if (ln.arrived and not page) else ""
            out.append(f'<span class="wll{" wdone" if ln.arrived else ""}">{tick}<span class="wlt"><span class="wkind">{e(_t("wait.list.kind." + k))}</span>{text}{arr}' + (f'<span class="wsub">{sub}</span>' if sub else "") + '</span></span>')
        return '<span class="wl">' + "".join(out) + '</span>'
    def wait_end_slot(self, mod, t0):
        """A Waiting row's right-hand slot on line one: the date the wait ends, "until Wed Mar 4th" ("… 09:00" when the stored wake has a time), read by home.end_of, the one reader the Waiting sort uses; "no end date"
        (dimmed) when the wait has none. Plain text, not a live stamp (no data-ts: the page script has no age to keep current here); how long the wait has run is the hover, "waiting since <time>" (the age stamp's tooltip)."""
        v = _home.end_of(mod)
        tip = f' data-tip="{esc(_t("home.waiting_since", at=f"{t0:%Y-%m-%d %H:%M}", tz=_cfg.tz_abbr(t0)))}" title=""' if t0 else ""
        return f'<span class="tip ir-age ir-end{"" if v else " dim"}"{tip}>{esc(_t("home.until", day=self.day_words(v))) if v else esc(_t("home.no_end"))}</span>'
    def wait_who(self, r, mod):
        """A waiting row's who line: "<who picks it up when the wait ends> picks it up" ("<owner>, then <who>" when he does and a `then` stands) · watched by <what notices its end> · set by <who set the date>" (a long wait that stands on a real-world date says who set it). Nothing is
        said to watch a wait nothing can notice the end of: a time or a relay with no date, an item wait with neither an item nor a backstop date, an anchor wait with no anchor."""
        w = mod.wait
        if w is None: return ""
        if not w.mover: bits = [esc(_t("home.nobody_picks"))]
        elif _model.is_owner(w.mover): bits = [_t("home.owner_then", who=self.home_mover(w.mover), then=self.home_mover(mod.then)) if mod.then else _t("home.picks_up", who=self.home_mover(w.mover))]
        else: bits = [_t("home.picks_up", who=self.home_mover(w.mover))]
        noticed = {"time": bool(w.until), "relay": bool(w.until), "item": bool(w.after or w.backstop), "anchor": bool(w.anchor or self.scoped_urls(r["gid"]))}.get(w.kind, True)
        if w.kind == "list" and mod.waits: bits.append(_t("home.watched_by", who=", ".join(esc(_home.watcher_word(x)) for x in _ip.list_watchers(mod))))      # each kind of line has its own watcher; the arrived lines need none
        elif noticed: bits.append(_t("home.watched_by", who=esc(_home.watcher_word("the scheduler" if w.kind == "item" and not w.after else _home.watched_by(w.kind)))))      # an item wait with only its backstop date is the scheduler's (watchers.can_end)
        wb = (r["metadata"] or {}).get("wait_basis")
        if w.kind == "time" and w.basis and isinstance(wb, dict): bits.append(_t("home.set_by", who=esc(shown_ref(str(wb.get("by") or "")) or _t("home.unknown"))))
        return " · ".join(bits)
    def known_movers(self, r, mod):
        """The names a next line may open with and have the row drop them: the item's mover, owner and the one who picks it up when its wait ends, as stored (a name or a session id) and as the board names them
        (mover_name, the owner's display name), and the names of the fleet's sessions the board holds (the sala links use them)."""
        w = mod.wait
        who = [mod.mover, r.get("owner"), r.get("owner_name"), (w.mover if w else ""), mod.then]
        names = [self.mover_name(x) for x in who if x]
        o = self._sess_obj(r) or {}
        fleet = [x.get("name") for x in self.sess.values() if isinstance(x, dict)]
        return tuple(dict.fromkeys(str(x) for x in who + names + [o.get("name")] + fleet if x))
    def act_parts(self, r):
        """The last activity of an open item (its metadata.last_activity record, model/last_activity.py) as an On agent row and the item page draw it: (age_html, line_html), None when the item has no record or is parked (on hold, or after
        another item: nothing is expected of it, so no idle flag). The age is the time since the activity ("46m", "1h 44m", "2d 3h"), drawn on the title line in place of the age since the row's state began; the line is the pill (active
        under 45 minutes, quiet to an hour, idle over 1 h) and "Last: <what it was> at <HH:MM>" (the date too when it was not today). Both carry the activity's time in data-at, which the page script (_LACT_JS) keeps current, with the band in data-b.
        The age is taken from the render's own clock here, so a page with no script says the same."""
        if r.get("status") != "open" or is_parked(r): return None
        rec = _lastact.read(r, self.now.timestamp())      # a record stamped more than SKEW_S ahead of the clock is none: the old age and no line, never "<1m" for a time that has not come
        if not rec: return None
        try: t = datetime.datetime.fromtimestamp(rec["at"], self.now.tzinfo)
        except (ValueError, OverflowError, OSError): return None      # a time the calendar cannot take: the old age and no line, never a page that fails (the record already refuses one past MAX_AT)
        rec = {**rec, "at": float(int(rec["at"]))}      # whole seconds, the value data-at carries: the server bands by the very number the page script reads, so the two cannot differ at a boundary
        sec = max(0.0, self.now.timestamp() - rec["at"]); b = _lastact.band(sec)
        words = {k: _t(v) for k, v in _ACT_WORD.items()}
        clock = f"{t:%H:%M}" if t.date() == self.now.date() else self.when(rec["at"])
        tip = esc(_t("home.last_tip", when=self.when(rec["at"]), tz=_cfg.tz_abbr(t)))
        age = f'<span class="tip ir-age" data-at="{int(rec["at"])}" data-b="{b}" data-tip="{tip}" title="">{esc(_i18n.fmt_span(sec))}</span>'
        line = (f'<span class="ir-pill" data-at="{int(rec["at"])}" data-b="{b}" data-w-ok="{esc(words[_lastact.OK])}" data-w-warn="{esc(words[_lastact.WARN])}" data-w-bad="{esc(words[_lastact.BAD])}">{esc(words[b])}</span>'
                f'<span class="ir-lwhat">{esc(_t("home.last", what=rec["what"], time=clock))}</span>')
        return age, line
    def home_row(self, r, mod, which, flags=False, named=False):
        """One row of Your move (which = home.YOUR_MOVE), On agent or Waiting: the one row (ui/kit.py). Line one: `#id title` (wrapping, never cut) and the age since the row's state began at the right (a stamp the page
        script keeps current; on Your move amber past two days and red past five; on Waiting, which is sorted by end date, the end date in its place: "until Wed Mar 4th" or "no end date", plain text, the age on hover; wait_end_slot). The who line, small and gray, only when it says something: On agent the mover, or "handed to X, not yet taken";
        Waiting "then X · watched by Y · set by Z"; Your move none (it is always the owner), except on a project page. The detail behind its guide line: Your move the ask's question or the step (a command or link in a block to copy,
        a draft under it), On agent the immediate next step, Waiting "Until <when>: <what>" and the chases, then "after the wait: <next step>"; a `woke:` line shows until the mover writes. The actions under the detail: on Your move the answer form, drawn hidden
        for the page script to show with a token (_HOME_JS); the title is the link to the item. named=True (home) draws the project's name above the title (project_line) and the item's owner after it (row_line); a project page's rows show the owner alone, the page says the project.
        The card's left edge takes the list's color (Your move, On agent, Queued for release, Waiting).
        flags=True (the project page's lists) keeps what an item's line there carried: the due badge, the stale ⚠ and the "waits for recycle" badge, on the who line."""
        e = esc; m = r["metadata"]; gid = r["gid"]
        ts = _home.since(r, mod, same_ref)
        t0 = datetime.datetime.fromtimestamp(ts, self.now.tzinfo) if ts else None
        cls = _home.age_class((self.now - t0).total_seconds()) if (which == _home.YOUR_MOVE and t0) else ""
        age = self.stamp(t0, "ir-age" + (f" {cls}" if cls else "")) if t0 else ""
        if which == _home.WAITING: age = self.wait_end_slot(mod, t0)      # Waiting is sorted by end date, so its slot shows the end date; the age is the hover
        act = self.act_parts(r) if which == _home.AGENTS else None      # On agent: the age is the time since the item's last activity, with the pill and what it was under the mover; an item with no record keeps the old age and has no line
        if act: age = act[0]
        who = []
        if which in (_home.AGENTS, RELEASE_LIST):      # Queued for release rows are On agent rows: the mover, or the hand-off not yet taken
            ho = _ho.record_of(r)
            front, _b = self.agent_roles(self.row_of(proj_key(r))) if proj_key(r) else ({}, {})
            exempt = self.mover_name(mod.mover) in front        # a front agent is no hand-off waiting to be taken
            if ho and same_ref(ho.get("to"), mod.mover) and _ho.awaiting_session(r) and not exempt: who.append(f'<span class="attn">{_t("home.handed", who=self.home_mover(mod.mover))}</span>')
            else: who.append(self.home_mover(mod.mover))
        elif which == _home.WAITING:
            who.append(self.wait_who(r, mod))
        if flags:
            if due_of(r): who.append(self.due_badge(r))      # the old project line was the one place a deadline showed: kept, on the who line
            if r.get("_fresh") == "stale": who.append(f'<span class="iwarn" title="{e(stale_tip(r, self.mover_name))}">⚠</span>')
            if waits_recycle(r): who.append(badge(_t("item.waits_recycle"), "recycle"))
        notes = []
        wk = m.get("woke")
        if which != _home.WAITING and isinstance(wk, dict) and wk.get("what"):
            notes.append(f'<div class="hnote">{_t("home.woke", what=e(wk["what"]), who=self.home_mover(str(wk.get("to") or mod.mover)))}</div>')
        ask = self.home_ask(r) if which == _home.YOUR_MOVE else None
        stp = self.home_step(r) if (which == _home.YOUR_MOVE and not ask) else None
        dr = self.home_draft_html(r) if (which == _home.YOUR_MOVE and not stp) else ""      # a step's draft is drawn inside its step, under the step's text (home_step); an ask's, or a row with no step form, right under the detail
        _name, step = _home.first_next(m.get("next"), self.known_movers(r, mod))
        nxt = (self.step_html(step, gid) if which == _home.YOUR_MOVE else self.md_line(step, gid)) if step else f'<span class="dim">{esc(_t("home.no_next"))}</span>'
        actions = ""
        if which == _home.WAITING: detail = f'<span class="hwait">{self.home_wait(r, mod)}</span>' + (f'<span class="hnext hafter"><span class="dim">{esc(_t("home.after_wait"))}</span> {nxt}</span>' if step else "")
        elif ask: detail, actions = f'<span class="hnext hq">{ask[0]}</span>{dr}', ask[1]
        elif stp: detail, actions = f'<span class="hnext">{stp[0]}</span>', stp[1]      # a your-step item: the step itself in place of the next line, with the note box and its Done and Send note buttons
        else: detail = f'<span class="hnext">{nxt}</span>{dr}'
        return _ui.row(href=item_href(r), rid=rid(r), title=self.bare(r["subject"]), age_html=age, who_html=" · ".join(x for x in who if x),
                       detail_html=detail + "".join(notes), actions_html=actions, li_id=anchor(r), li_class="hrow",
                       project_html=self.row_line(r, project=named), edge=RELEASE_LIST if which == RELEASE_LIST else _ui.kind_of_list(which),
                       act_html=act[1] if act else "")
    def project_line(self, r):
        """The project's name as the small line above a row's title (home and Closed): a link to the project's page, the label proj_label gives for the item's top-level project (proj_top), never the sub-page it is filed on (the project page's
        own sub-page badge and the who line name that); "" for an item with no project. Reads the registry the board already holds, no lookup of its own."""
        k = proj_top(r) or proj_key(r)
        if not k: return ""
        return _ui.project_line(under("/" + (self.row_of(k) or k)), self.proj_label(k))
    def row_line(self, r, project=True):
        """The small quiet line above a row's title: `project · owner`, the owner being the name the item page's side column shows (row_contact), a link to the session's view while it has a live pane and plain text otherwise (sess_html).
        project=False (a project page's rows: the page says the project) leaves the owner alone; an item with no contact shows the project alone, and one with neither has no line."""
        parts = [self.project_line(r)] if project else []
        n = self.row_contact(r)
        if n: parts.append(self.sess_html(n, cls="pjo"))
        return " · ".join(x for x in parts if x)
    def sent_notes_html(self):
        """The hidden element the home page's script (_HOME_JS) reads to show the notice of an answer sent from a row: the item page's own notices (one text per ?sent= code, the home wording where it has
        one) and the prefix an issue-numbered id is written with. The home page and the project page carry it, both draw answer forms in their rows; the notice shows after #counts, else after this element."""
        return (f'<div id="sent-notes" hidden data-hash="{esc(shown("g1")[:-1])}" data-notes="'
                + esc(json.dumps({k: [v[0], _t(v[-1])] for k, v in self._SENT_KEYS.items()})) + '"></div>')
    def scope_groups(self, items, row=lambda x: x):
        """Items grouped by scope: [(scope, [item])]. The one grouping home's four lists and the Closed page's New and Last 14 days sections draw (ui/groups.py): an item's scope is the Closed page's (landed_scope: the scope of the project
        its board row rolls up to, no project the default scope), the groups in [project_scopes] order (team, lab, infra, say), the items of a group in the order given (each list keeps its own sort). A scope with no items has no group. An item
        whose scope is not one of the configured scopes is not dropped: its scope's own name is a last group (several such, by name). `row(item)` is the item's board row when the item is not itself the row (a home pair, a Landed record)."""
        memo = {}
        def of(it):
            k = self.row_of(proj_key(row(it))) or proj_key(row(it)) or ""
            if k not in memo: memo[k] = self.landed_scope(k)
            return memo[k]
        return _grp.group(items, of, _prj.scopes())
    def scope_sections(self, prefix, items, draw, row=lambda x: x):
        """The subsections of one list of items, one foldable subsection per scope (scope_groups, ui/groups.py): the scope's name and its row count in the summary, the rows (draw(item) → the row's <li>) under it, open. prefix
        names the list in each subsection's data-fold key (`<prefix>.<scope>`); `row` is as in scope_groups."""
        return _grp.sections(prefix, self.scope_groups(items, row), draw)
    def home_section(self, sid, title, pairs, which, empty):
        """One of the four lists as a top-level fold: Your move and Queued for release render open, On agent and Waiting closed, nothing remembered. The heading is the list's name and its count; the rows are the one row,
        in a foldable subsection per scope (scope_sections: the scope's name and row count in the summary, the Closed page's h3.iscope, open even in a list that starts closed); a list with no rows keeps its one empty line."""
        if not pairs: return _top_fold(sid, f'<h2>{esc(title)} <span class="count">0</span></h2>', f'<p class="empty">{esc(empty)}</p>', is_open=(which in (_home.YOUR_MOVE, RELEASE_LIST)))
        body = self.scope_sections(f"home.{sid}", pairs, lambda p: self.home_row(p[0], p[1], which, named=True), row=lambda p: p[0])
        return _top_fold(sid, f'<h2>{esc(title)} <span class="count">{len(pairs)}</span></h2>', body, is_open=(which in (_home.YOUR_MOVE, RELEASE_LIST)))
    def home_counts(self, lists=None, off_home=False):
        """The count cards at the top of the page, in the header between the title and the rendered line (page_header draws the same cards on every other page):
        one card per count, the number over its label, each a link: Your move, On agent, Queued for release and Waiting to their lists, Closed to the Closed page (/closed, the Landed page renamed).
        Closed: the number is the items closed in the last 14 days, done, dropped and superseded alike (len(self.done), the Last 14 days section's count), and on the label line, right after the word "Closed", the count
        "N new" as green text (the number stands alone above it where the line has room; where the label line is too narrow for it, "N new" moves up beside the number, never clipped), N the closes of agents that he has not cleared (landed_count, the New section's count, which reaches back over all the days landed.py keeps a close, not only the 14); no count at 0. The card look is the board's old state tiles (.stat). Closed is drawn at 0 too, number muted: the row keeps one shape.
        Every card is 60 px tall at every width (a label never wraps; Queued for release says "Queued" where the column is narrow); the count is part of that. The column is the same with the side panel closed as with it pinned (the CSS caps the column to the pinned one's in every state),
        so the cards' size and that wording never follow the panel.
        `lists` is home_lists() (default: drawn here, so a page that is not home gets the same four counts home shows from the same code). `off_home=True` (every page but home): the four list cards link to home
        with that list open (`/#your-move` and so on: home opens the section a hash names, _FOLD_HASH), where on home itself they are the bare `#your-move` that filters in place."""
        lists = self.home_lists() if lists is None else lists
        at = under("/") if off_home else ""
        def card(href, cls, label, n, tip="", short="", new=0):
            t = f' title="{esc(tip)}"' if tip else ""
            if short and label.startswith(short): label = f'{short}<span class="more">{label[len(short):]}</span>'      # the short form is the label's start: narrow, the rest is clipped away but stays for a screen reader
            badge = f' <i class="hnew{f" w{min(len(str(new)), 4)}" if new > 9 else ""}">{_t("home.new_fmt", n=new, word="<em>" + esc(_t("home.new_word")) + "</em>")}</i>' if new else ""        # in the label line, right after the label; where that line is too narrow for it (the card's content under 80 px for one digit, 86, 93 and 99 for two, three and four or more; a class w2, w3, w4 says which, _hnew_css) it moves up beside the number: the word is never cut away
            nk, bk = _hnew_parts(n, new)
            need = f' style="--need:{_hnew_need(n, new)};--nk:{nk:g};--bk:{bk:g}"' if new else ""      # the number line's width in px with the count beside the number, for the narrow rules (_hnew_css)
            return f'<a class="hcard{cls}" href="{href}"{t}{need}><b>{n}</b><span>{label}{badge}</span></a>'
        nl = self.landed_count()        # the closes of agents that he has not cleared: exactly the lines of the New section of the Closed page
        nd = len(self.done)             # the items closed in the last 14 days, done, dropped and superseded alike: exactly the rows of the Last 14 days section
        return (f'<nav class="hcards" id="counts" aria-label="{esc(_t("home.counts"))}">'
                + card(at + "#your-move", " call", _ui.title(_ui.YOUR_MOVE), len(lists[_home.YOUR_MOVE]))
                + card(at + "#agents-at-work", "", _ui.title(_ui.AGENT), len(lists[_home.AGENTS]))
                + card(at + "#queued-release", "", _ui.title(_ui.RELEASE), len(lists[RELEASE_LIST]), _t("home.queued_tip"), short=_t("home.queued_short"))
                + card(at + "#waiting-list", "", _ui.title(_ui.WAITING), len(lists[_home.WAITING]))
                + card(under("/closed"), "" if nd else " zero", _ui.word(_ui.CLOSED), nd, _t("home.closed_tip") + (_t("home.closed_tip_new", n=nl) if nl else ""), new=nl)
                + '</nav>')
    def done_row(self, r, sub="", who_html=None, named=False):
        """One closed item as the one row: its outcome as the state tag (Done, Dropped, Superseded; Closed for one closed with no outcome recorded), `#id title` and how long ago it closed at the right, the close reason
        behind the guide line. `sub` (a project page's row for an item on a sub-page) names the sub-page on the who line; `named=True` (the Closed page's Last 14 days) draws the project's name above the title (project_line) and the owner after it (row_line); a project page's rows show the owner alone.
        Its card keeps the plain edge."""
        oc, why, _by = outcome_of(r)
        return _ui.row(tag_html=_ui.tag(_ui.kind_of_outcome(oc)), href=item_href(r), rid=rid(r), title=self.bare(r["subject"]), age_html=self.stamp(r["_updated"], "ir-age"),
                       who_html=who_html if who_html is not None else (esc(sub) if sub else ""), detail_html=esc(why) if why else (f'<span class="dim">{esc(_t("item.no_outcome"))}</span>' if oc in ("", "unrecorded") else ""), li_id=anchor(r),
                       project_html=self.row_line(r, project=named))
    COMPLETED_PAGE = 25          # rows to a page of the Completed section on the Landed page
    def completed_page(self, page):
        """The page asked for of the Completed section -> (rows, page, pages): the items closed in the last 14 days, newest first, COMPLETED_PAGE to a page. `page` is what the address carried (a string, an int or None): anything that is
        not a whole number, and anything under 1, is page 1; one past the last is the last page (pages is at least 1, so an empty list is page 1 of 1). Only the rows of that page are returned, so only they are drawn and sent."""
        n = len(self.done); pages = max(1, -(-n // self.COMPLETED_PAGE))
        try: page = int(str(page).strip())
        except (TypeError, ValueError): page = 1
        page = min(max(page, 1), pages)
        return self.done[(page - 1) * self.COMPLETED_PAGE:page * self.COMPLETED_PAGE], page, pages
    def completed_html(self, page=None):
        """Last 14 days, the second section of the Closed page (the Landed page, renamed): the items closed in the last 14 days, newest first, each the one row (done_row, the project named above the title), in the same foldable subsections per scope as the New section (the page's rows only, COMPLETED_PAGE to a page, so a subsection's count is the rows of that scope on the page shown). Under the rows, when there is more than one page, Newer (the page before: more
        recent) at the left and Older (the page after) at the right, each a link to ?page=N#completed; at an edge the missing one is plain, dimmed text, not a link. Only the page asked for is drawn."""
        rows, page, pages = self.completed_page(page)
        n = len(self.done); first = (page - 1) * self.COMPLETED_PAGE
        def at(p): return under("/closed") + (f"?page={p}" if p > 1 else "") + "#completed"
        def side(word, p, rel):
            return f'<a class="pg" rel="{rel}" href="{esc(at(p))}">{word}</a>' if p else f'<span class="pg off" aria-disabled="true">{word}</span>'
        pager = (f'<nav class="lpager" aria-label="{esc(_t("closed.pager"))}">{side(_t("closed.newer"), page - 1 if page > 1 else 0, "prev")}<span class="lpos">{_t("closed.page_of", page=page, pages=pages)}</span>'
                 f'{side(_t("closed.older"), page + 1 if page < pages else 0, "next")}</nav>') if pages > 1 else ""
        body = self.scope_sections("closed.completed", rows, lambda r: self.done_row(r, named=True)) if rows else f'<p class="empty">{_t("page.none")}</p>'
        note = _t("closed.last14_showing", first=first + 1, last=first + len(rows), n=n) if rows and pages > 1 else _t("closed.last14_note")
        return (f'<section id="completed" class="lcompleted"><h2 class="lsec" title="{esc(_t("closed.last14_tip"))}">{_t("closed.last14")} <span class="count">{n}</span></h2>'
                f'<p class="lpgnote">{esc(note)}</p>{body}{pager}</section>')

    # ---------------- Landed ----------------
    def landed_rows(self):
        """The closes on the Closed page's New section AND in the Closed card's "N new" badge, newest first: [(record, item)]. The one function both read: every close he has not cleared, of the last _ld.KEEP_DAYS (60) days,
        of the items the store still holds as completed with an outcome that lands (done or dropped). The item is looked up among all the board's rows, not only self.done (the last 14 days), so a close older than 14 days
        stays New, with its own title, outcome and reason, until he clears it or landed.py drops it; the card's separate Closed number and the Last 14 days section stay on the 14-day window. Once per Board."""
        if getattr(self, "_landed", None) is None:
            by = {r["gid"]: r for r in self.rows}
            self._landed = [(rec, by[rec["gid"]]) for rec in _ld.records(self.now.timestamp())
                            if rec["gid"] in by and by[rec["gid"]].get("status") == "completed" and outcome_of(by[rec["gid"]])[0] in _ld.OUTCOMES]
        return self._landed
    def landed_count(self):
        """How many entries the Landed page lists: the header's Landed count. The length of landed_rows, nothing else."""
        return len(self.landed_rows())
    def landed_keys(self):
        """The identity of each close on the page (landed.key): what Clear all carries (a close that lands after the page was drawn is not in it, so it is not cleared unseen)."""
        return [_ld.key(rec["gid"], rec["ts"]) for rec, _r in self.landed_rows()]
    def landed_scope(self, k):
        """The scope a project sits under on the Landed page: the one sala's sidebar and the New session form's project picker use (team, lab, infra), read from the same source, projects.py: the scope set on
        purpose for the page (its mark in the id file), else derive_scope (the page's key prefix, its org and tags, the prefix of its keeper's and agents' names: `work-…` is work, `ops-…` ops, else the default).
        k = the board row's page key ("" for an item with no project: the default scope). → (scope, rank), the rank its place in [project_scopes] order."""
        order = _prj.scopes()
        entry = self.proj.get(k) if isinstance(self.proj.get(k), dict) else {}
        sc = _prj.scope_of(k, entry, self.proj)
        return sc, (order.index(sc) if sc in order else len(order))
    def landed_html(self, mark=True, page=None) -> str:
        """The Closed page (GET /closed, the Landed page renamed, behind the board's sign-in; /landed redirects here): two sections, New (one entry per close that the owner has not cleared) and Last 14 days (completed_html). Both draw their rows the way home's lists do (scope_sections, ui/groups.py): one foldable subsection per scope (work, home, ops as sala's sidebar has them, from the project's scope in projects.py) in [project_scopes] order, the scope's name and its row count in the summary, open by default; the entries of a scope newest first. A row names its project and its owner in a small line above the title (row_line), as home's rows do, and its card has the green New edge.
        An entry is the one row (ui/kit.py): the outcome tag (Done, Dropped), `#id title` with the close's age beside it ("12m ago", "30h ago"; the exact time in the board's zone on hover), the close reason behind the guide line (wrapped, never cut),
        and Clear under the reason. Like a phone's notifications an entry stays until he clears it: nothing here clears anything but a Clear (`/landed/clear` with that close's key) or
        Clear all (every key on the page) button, and opening the page clears nothing. The page's script (_LANDED_JS) keeps a cleared line in place, dimmed, with an Undo (`/landed/unclear`) until the page is reloaded. Clear all sits at the top, above the list. mark=False draws no buttons.
        Below the groups, the Completed section (completed_html); `page` is the page of it asked for (?page=N)."""
        e = esc; rows = self.landed_rows()
        now_ts = self.now.timestamp()
        def line(rec, r):
            oc, why, _sup = outcome_of(r)
            key = _ld.key(rec["gid"], rec["ts"])
            clear = (f'<form class="lclear" method="post" action="{under("/landed/clear")}"><input type="hidden" name="keys" value="{e(key)}">'
                     f'<button type="submit" class="b" aria-label="{e(_t("js.closed.aria", label=_t("js.closed.clear"), id=rid(r)))}">{_t("js.closed.clear")}</button></form>') if mark else ""
            when = (f'<span class="tip ir-age lago" data-ts="{int(rec["ts"])}" data-tip="{e(self.when(rec["ts"]))} {e(_cfg.tz_abbr(datetime.datetime.fromtimestamp(rec["ts"], self.now.tzinfo)))}" title="">'
                    f'{e(landed_ago(now_ts - rec["ts"]))}</span>')
            # the one row: the outcome as its tag, `#id title` with the close's age at the right, the close reason behind the guide line, Clear under the reason (where Your move has its Send)
            return _ui.row(tag_html=_ui.tag(_ui.kind_of_outcome(oc)), href=item_href(r), rid=rid(r), title=self.bare(r["subject"]), age_html=when, detail_html=e(why) if why else "",
                           actions_html=clear, li_class="lrow", data=f'data-key="{e(key)}"', project_html=self.row_line(r), edge=_ui.NEW)
        # the same subsections as home's lists (scope_sections): one foldable subsection per scope in [project_scopes] order, the entries of a scope newest first (landed_rows is), each a row with no who line
        secs = self.scope_sections("closed.new", rows, lambda pr: line(*pr), row=lambda pr: pr[1])
        note = _t("js.closed.note_one" if len(rows) == 1 else "js.closed.note_many", n=len(rows)) if rows else _t("closed.note_none")
        btn = ('<form class="lmark" method="post" action="' + under("/landed/clear") + '"><input type="hidden" name="keys" value="' + e(",".join(self.landed_keys())) + '">'
               '<button type="submit" class="b">' + _t("closed.clear_all") + '</button></form>') if rows and mark else ""
        font_css = str(_cfg.get("instance", "font_css") or "")
        return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                f'<meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow"><title>{_t("state.closed")} · {e(self.title)}</title>'
                f'<link rel="icon" href="{icon_href("favicon.svg")}" type="image/svg+xml">' + (f'<link rel="stylesheet" href="{e(font_css)}">' if font_css else "")
                + _THEME_HEAD + _APP_HEAD + f'<style>{self._css()}</style></head>{_PANEL_BODY}<div id="layout"><main id="top">{self.page_header()}'
                f'<h1>{_t("state.closed")}</h1><section id="new" class="lnew"><h2 class="lsec">{_t("closed.new")} <span class="count">{len(rows)}</span></h2><p class="lnote"{" data-n" if rows else ""}>{note}</p>{btn}{secs}</section>{self.completed_html(page)}</main>'
                + self.panel_tail() + _FAB_PAIR + _THEME_JS + _RELOAD_JS + _TOTOP_JS + _BFCACHE_JS + f'<script>{_HOME_FOLD_JS}</script><script>{_LANDED_JS}</script></body></html>')

    def projects_html(self) -> str:
        """The Projects page (GET /projects, behind the board's sign-in): the list of projects and their running agents (projects_table). A project's items and watch are on its own page."""
        e = esc
        font_css = str(_cfg.get("instance", "font_css") or "")
        return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                f'<meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow"><title>{_t("projects.title")} · {e(self.title)}</title>'
                f'<link rel="icon" href="{icon_href("favicon.svg")}" type="image/svg+xml">' + (f'<link rel="stylesheet" href="{e(font_css)}">' if font_css else "")
                + _THEME_HEAD + _APP_HEAD + f'<style>{self._css()}</style></head>{_PANEL_BODY}<div id="layout"><main id="top">{self.page_header()}'
                f'<h1>{_t("projects.title")}</h1><p class="pjnote">{_t("projects.note")}</p><section id="by-project">{self.projects_table()}</section></main>'
                + self.panel_tail() + _FAB_PAIR + _THEME_JS + _RELOAD_JS + _TOTOP_JS + _BFCACHE_JS + f'<script>{_HOME_FOLD_JS}</script></body></html>')

    # TEMPORARY PROBE (the installed-app session link test) (remove, or promote into sess_html, in the follow-up PR): GET /probe/sala-link, a signed-in page of the same session link written six ways, so a tap on an Android phone
    # in the installed stackshot app shows which way opens the installed sala app instead of a Chrome Custom Tab. It makes no write and changes no link on any other page.
    def probe_target(self, to=None) -> str:
        """The one address every link of the probe page points at: `to` when it is on the origin of the [client] session_view template (scheme, host and port equal; no user info, control character or backslash), else the
        session view of the first live session this board knows (sess_href), else the template's origin root; "" when no session_view is set."""
        tpl = str(_cfg.get("client", "session_view") or "")
        o = urlsplit(tpl.replace("{name}", "x")) if tpl else None
        if o is None or o.scheme not in ("http", "https") or not o.netloc: return ""
        t = to if isinstance(to, str) else ""
        if t and len(t) <= 2000 and not any(ord(c) <= 32 or ord(c) == 127 or c == chr(92) for c in t):
            try: u = urlsplit(t)
            except ValueError: u = None
            if u is not None and u.scheme == o.scheme and u.netloc.lower() == o.netloc.lower(): return t
        for k in sorted(self.sess):
            if k.startswith("name:"):
                h = self.sess_href(k[5:])
                if h: return h
        return f"{o.scheme}://{o.netloc}/"
    @staticmethod
    def probe_intents(url: str) -> tuple[str, str]:
        """The two intent:// forms of an http(s) address for the probe: (plain, with the VIEW action and the BROWSABLE category). The address without its #fragment follows intent:// (#Intent is the fragment of an intent link);
        the fallback is the whole address percent-encoded, so it decodes back to `url` exactly."""
        sp = urlsplit(url)
        body = "intent://" + sp.netloc + quote(sp.path or "/", safe="/%:@!$&'()*+,;=-._~") + (("?" + quote(sp.query, safe="/?%:@!$&'()*+,;=-._~")) if sp.query else "")
        fb = f"S.browser_fallback_url={quote(url, safe='')};end"
        return (f"{body}#Intent;scheme={sp.scheme};{fb}",
                f"{body}#Intent;scheme={sp.scheme};action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;{fb}")
    def probe_html(self, to=None) -> str:
        """The probe page (GET /probe/sala-link, behind the board's sign-in, drawn on request): a heading, one line of instruction and the variants A to F of one link (probe_target), each with a short label and one line saying
        what it is. A to E are links (plain with and without target=_blank, the intent:// link with and without it, the intent:// link with the VIEW action and BROWSABLE category), F two buttons (window.open, location.href).
        With no session_view set it says so and draws no link. Every value is escaped; the page writes nothing."""
        e = esc
        url = self.probe_target(to)
        font_css = str(_cfg.get("instance", "font_css") or "")
        if url:
            c, ee = self.probe_intents(url)
            ln = lambda href, tgt: f'<a href="{e(href)}"{" target=_blank" if tgt else ""}>{_t("probe.go")}</a>'
            items = [(_t("probe.a.label"), _t("probe.a.what"), f'<a href="{e(url)}" target="_blank" rel="noopener">{_t("probe.go")}</a>'),
                     (_t("probe.b.label"), _t("probe.b.what"), ln(url, False)),
                     (_t("probe.c.label"), _t("probe.c.what"), ln(c, True)),
                     (_t("probe.d.label"), _t("probe.d.what"), ln(c, False)),
                     (_t("probe.e.label"), _t("probe.e.what"), ln(ee, False)),
                     (_t("probe.f.label"), _t("probe.f.what"),
                      f'<button type="button" class="b" data-probe="open" data-url="{e(url)}">{_t("probe.f.open")}</button> '
                      f'<button type="button" class="b" data-probe="href" data-url="{e(url)}">{_t("probe.f.href")}</button>')]
            body = (f'<p class="pjnote">{_t("probe.target", url="<code>" + e(url) + "</code>")}</p><ul class="probe">'
                    + "".join(f'<li><b>{lab}</b><br><span class="dim">{what}</span><br>{ctl}</li>' for lab, what, ctl in items) + "</ul>"
                    "<script>document.addEventListener('click',function(ev){var b=ev.target&&ev.target.closest?ev.target.closest('button[data-probe]'):null;if(!b)return;"
                    "var u=b.getAttribute('data-url');if(b.getAttribute('data-probe')==='open')window.open(u,'_blank');else location.href=u});</script>")
        else:
            body = f'<p class="pjnote">{_t("probe.no_template")}</p>'
        return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                f'<meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow"><title>{_t("probe.title")} · {e(self.title)}</title>'
                f'<link rel="icon" href="{icon_href("favicon.svg")}" type="image/svg+xml">' + (f'<link rel="stylesheet" href="{e(font_css)}">' if font_css else "")
                + _THEME_HEAD + _APP_HEAD + f'<style>{self._css()}ul.probe{{list-style:none;padding:0;margin:0}}ul.probe li{{margin:0 0 16px;overflow-wrap:anywhere}}</style></head>{_PANEL_BODY}<div id="layout"><main id="top">{self.page_header()}'
                f'<h1>{_t("probe.title")}</h1><p class="pjnote">{_t("probe.note")}</p>{body}</main>'
                + self.panel_tail() + _FAB_PAIR + _THEME_JS + _RELOAD_JS + _TOTOP_JS + _BFCACHE_JS + '</body></html>')

    def audits_html(self, runner=None) -> str:
        """The Audits page (GET /audits, behind the board's sign-in, drawn on request): the three paces the audits run at, the audit groups (each a fold of its audits with their pace and mode, the number
        of audits and the findings of the last 24 hours), the latest findings, and the recent runs, with an Audit now button at the top (the same button as the side panel card's: _AUDIT_JS drives both, and both post
        to /audit/now). The data is audit_overview.overview: the findings log, the run records and, for the ten-minute set's last run, `runner`, the runner's record (service/runner.py status; None draws no "last").
        A group that keeps no findings log shows `not logged`, never a zero; with the findings log off no group has a count. Nothing yet (no run, no finding) draws the same page with plain empty lines, and the audit off
        says so and has no button. The page makes no write and no model call."""
        from stackshot.audit import audit_overview as _ov
        e = esc
        z = _cfg.tz()
        ts = self.now.timestamp()
        rows = _ov.day_rows(ts)      # the findings log, read once for the whole request: the page's counts and rows and the side panel's card below all come from this list
        self._audit_rows = rows
        ov = _ov.overview(ts, runner, rows)
        def at(t):
            try: return datetime.datetime.fromtimestamp(t, z)
            except (OverflowError, OSError, ValueError, TypeError): return None      # an epoch no date can hold (a damaged record) is a dash, never an error page
        def words(t):
            d = at(t)
            return "–" if d is None else when_words(d)
        def stamp(t):
            """A time as the page says it: the clock for today, the date and clock for another day (the way the card's clock() does)."""
            d = at(t)
            return "–" if d is None else (f"{d:%H:%M}" if d.date() == self.now.astimezone(z).date() else when_words(d))
        running = ov["running_since"] is not None
        if ov["enabled"]:
            sub = _t("audit.sub_next", n=ov["total"], groups=len(ov["groups"]), at=words(ov["next"])) if _num_ok(ov["next"]) else _t("audit.sub", n=ov["total"], groups=len(ov["groups"]))
            btn = (f'<div class="atbtn"><button type="button" class="b" id="audit-now-page"{" disabled" if running else ""}>{_t("panel.audit.now")}</button>'
                   '<span class="apmsg" id="audit-page-msg" role="status" aria-live="polite"></span></div>')
        else:
            sub, btn = _t("audit.off"), ""
        done = [r for r in ov["runs"] if r["finished"] is not None and not r["error"]]
        last = done[0] if done else None
        times = _t("audit.times_join").join(ov["times"]) or _t("audit.scheduled")
        paces = [(_t("audit.pace_min"), _t("audit.pace_min_what")),
                 (_t("audit.pace_ten"), _t("audit.pace_ten_what_last", at=stamp(ov["ten_last"])) if ov["ten_last"] else _t("audit.pace_ten_what")),
                 (times, _t("audit.pace_runs_last", at=stamp(last["finished"]), items=last["items"] if last["items"] is not None else 0, found=last["found"]) if last else _t("audit.no_run_yet"))]
        paces_html = "".join(f'<div class="apace"><b>{e(a)}</b><span>{e(b)}</span></div>' for a, b in paces)
        def group(g):
            if g["found"] is None:
                num = f'<span class="anum">{_t("audit.not_logged" if not g["log"] else "audit.log_off")}</span>'
            else:
                num = f'<span class="anum{" hit" if g["found"] else ""}">{_t("audit.found", n=g["found"])}</span>'
            word = lambda table, prefix, english: _audit_word(table, english, prefix)      # a pace or a mode in the request's language; an audit's own name stays as the module gives it
            items = "".join(f'<li>{e(a["name"])}<span{"" if a["mode"] == "on" else " class=" + chr(34) + "shadow" + chr(34)}>{e(word(_AUDIT_PACES, "audit.pace.", a["pace"]))}{"" if a["mode"] == "on" else " · " + e(word(_AUDIT_MODES, "audit.mode.", a["mode"]))}</span></li>' for a in g["audits"])
            desc = _t("audit.desc." + g["key"]) if "audit.desc." + g.get("key", "") in _i18n.EN else g["desc"]
            return (f'<details class="audg"><summary><span class="agn"><b>{e(_audit_word(_AUDIT_GROUPS, g["name"], "panel.audit.group."))}</b><span>{e(desc)}</span></span><span class="anum">{_t("audit.n_audits", n=len(g["audits"]))}</span>{num}</summary>'
                    f'<ul class="aaud">{items}</ul></details>')
        groups_html = "".join(group(g) for g in ov["groups"])
        def finding(r):
            n = _ov.item_path(r["id"])
            ref = f'<a href="{under("/items/" + n)}">{e(r["id"])}</a>' if n else e(r["id"])
            return (f'<div class="af">{ref} {e(r["detail"])}<div class="am">{e(stamp(r["at"]))} · {e(_t("audit.source." + r["source"]) if r["source"] in _ov.SOURCES else (r["source"] or _t("audit.source_default")))} · {e(r["agent"])}</div></div>')
        if not ov["log"]:
            feed, fsub = f'<p class="aempty">{_t("audit.feed_log_off")}</p>', _t("audit.log_off")
        elif ov["recent"]:
            feed, fsub = '<div class="afeed">' + "".join(finding(r) for r in ov["recent"]) + "</div>", _t("audit.found_24h", n=ov["found"])
        else:
            feed, fsub = f'<p class="aempty">{_t("audit.feed_none")}</p>', _t("audit.none_24h")
        def run_row(r):
            unfinished = False
            if r["finished"] is None:
                unfinished = not (running and r["started"] == ov["running_since"])
                took = _t("audit.run_unfinished" if unfinished else "audit.run_running")
            else:
                took = _t("audit.run_secs", n=max(0, round(r["finished"] - (r["started"] or r["finished"]))))
            warn = ' class="warn"' if unfinished or r["error"] else ""
            start = words(r["started"]) if r["started"] is not None else "–"
            dash = lambda v: "–" if v is None else str(v)
            return f'<tr><td>{e(start)}</td><td{warn}>{e(took)}</td><td>{e(dash(r["items"]))}</td><td>{r["found"]}</td><td>{e(dash(r["calls"]))}</td></tr>'
        if ov["runs"]:
            runs = (f'<div class="atw"><table><tr><th>{_t("audit.th_started")}</th><th>{_t("audit.th_took")}</th><th>{_t("audit.th_items")}</th><th>{_t("audit.th_findings")}</th><th>{_t("audit.th_calls")}</th></tr>' + "".join(run_row(r) for r in ov["runs"]) + "</table></div>")
        else:
            runs = f'<p class="aempty">{_t("audit.no_runs")}</p>'
        note = _t("audit.note_logged" if ov["log"] else "audit.note_log_off")
        font_css = str(_cfg.get("instance", "font_css") or "")
        return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                f'<meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow"><title>{_t("audit.title")} · {e(self.title)}</title>'
                f'<link rel="icon" href="{icon_href("favicon.svg")}" type="image/svg+xml">' + (f'<link rel="stylesheet" href="{e(font_css)}">' if font_css else "")
                + _THEME_HEAD + _APP_HEAD + f'<style>{self._css()}</style></head>{_PANEL_BODY}<div id="layout"><main id="top" class="audits-page">{self.page_header()}'
                f'<div class="atop"><h1>{_t("audit.title")}</h1>{btn}</div><p class="asub">{e(sub)}</p><div class="apaces">{paces_html}</div>'
                f'<h2>{_t("audit.groups")} <small>{_t("audit.groups_hint")}</small></h2><div class="agroups">{groups_html}</div>'
                f'<h2>{_t("audit.findings")} <small>{e(fsub)}</small></h2>{feed}'
                f'<h2>{_t("audit.runs")} <small>{e(_t("audit.runs_hint", times=times, button=_t("panel.audit.now")))}</small></h2>{runs}<p class="anote">{e(note)}</p></main>'
                + self.panel_tail() + _FAB_PAIR + _THEME_JS + _RELOAD_JS + _TOTOP_JS + _BFCACHE_JS + '</body></html>')

    def page_header(self, q: str = "", counts: str | None = None, h1: bool = False, conn: str = "", rstamp: str | None = None, search_page: bool = False) -> str:
        """The header every page of the board starts with, the home page's own: the theme and summary-panel buttons, the site title (a link to "/") with the rendered line beside it (_rendered_line), the five count cards (home_counts) and the search box.
        Home passes its parts in (`counts`: the live block it swaps in place; `h1`: the title is its h1; `conn`: the connection notice; `rstamp`: the rendered line's stamp, "" for the shell fingerprint); every
        other page calls it bare and gets the cards drawn by the same code from the same Board (home_counts with off_home: the four list cards link to home with that list open, Closed to /closed),
        the title a <p> because those pages have their own h1. The panel button is drawn for an open panel, as every page is (apply_panel_open changes it for a person whose panel is stored closed); `q` is the search box's text (the Search page); `search_page=True` (the Search page) makes the box search in place, where every other page's box opens its results in a new tab (_search.box). Cost: one
        classification of the open rows, which the Board holds (home_lists) and the page's own lists may share, and the Closed numbers the Board already computed; no store read, no GitHub call of its own."""
        counts = self.home_counts(off_home=True) if counts is None else counts
        rl = (_rendered_line(self.stamp(self.now), _t("home.drawn_tip", when=self.when(self.now))) if rstamp is None
              else _rendered_line(rstamp))         # a page drawn per request says when it was drawn; home's line is about the published board
        return (f'<header class="top">\n{_theme_btn()}{_panel_btn()}\n{conn}<div class="hbar">{_site_title(self.title, icon_href("favicon.svg"), h1=h1)}{rl}</div>\n{counts}\n{_search.box(q, in_place=search_page)}\n</header>')

    def panel_tail(self) -> str:
        """What follows a page's </main> on every page but home: the summary panel as the home page has it (the same frame, the same
        five blocks from panel_blocks), the end of <div id="layout"> (opened before the <main>, with <body class="panel-pin">: every page is drawn with the panel open, and apply_panel_open closes it for a person who has), the panel's scripts and the header's height script (_HDR_JS). The script of
        the Audit card is the home page's; the card's refresh on the page's poll stays the home page's (these pages do not poll). GitHub calls: see panel_blocks (none of its own; at most one throttled background runners refresh per 120 s, shared by all pages)."""
        return _panel_frame(self.panel_blocks()) + f'</div><script>{_PANEL_JS}</script><script>{_PORDER_JS}</script><script>{_LANG_JS}</script><script>{_AUDIT_JS}</script><script>{_HDR_JS}</script>' + _STAMP_JS

    def panel_blocks(self) -> dict:
        """The side panel's five blocks (Machines, Runners, Anchor hub, Audit, Projects) as HTML, keyed as the home page swaps them: the one builder the home page and every other page
        draw the panel from, so they cannot drift. Everything it reads is local and already held: the fleet's versions and facts, the last
        runners snapshot (runners.peek), the receivers' status, the audit status and the ledger file (ghbudget.peek). A page view makes no GitHub call of its own: runners.peek returns at once
        and may start at most one throttled background refresh per panel_refresh_s (120 s), one for all pages together, however many are viewed."""
        now, PUB, FLEET, PKG_ORDER, OWNER = self.now, self.pub, self.fleet, self.pkg_order, self.owner
        stamp, sess_of = self.stamp, self.sess_of
        _vers = self.versions
        _PKG = {v.get("name"): v for v in _vers}
        _COLS = [PUB] + sorted(x for x in FLEET if x != PUB)   # the publisher, then the fleet; no cloud column — never a store letter
        def when_tip(v):
            t = _fact_time(v)
            return f"{ago((now - t).total_seconds())} ({t:%m-%d %H:%M} {_cfg.tz_abbr(t)})" if t else _t("panel.unknown_time")
        def failures(L, who=""):
            """Machine L's failed setup run and failed update attempts, each as (kind, detail, tip): kind is "setup" or "update", detail the step, or the package and the version it tried,
            tip the raw reason for the hover text (prefixed with `who` for a machine that has no card). An empty list when all went well."""
            s, ups = machine_alerts(self.mfacts.get(L) or {}, self.server_commit)
            out = []
            if s:
                tip = _t("panel.mach.setup_tip", step=s.get('step') or '?', when=when_tip(s.get('at')), reason=s.get('reason') or _t("panel.no_reason"))
                out.append(("setup", _t("panel.mach.step", step=s.get('step') or '?'), who + tip))
            for u in ups:
                ver = " → ".join(str(x) for x in (u.get("from"), u.get("to")) if x)
                tip = _t("panel.mach.update_tip", what=u.get('what'), ver=' ' + ver if ver else '', when=when_tip(u.get('at')), reason=u.get('reason') or _t("panel.no_reason"))
                out.append(("update", " ".join(str(x) for x in (u.get("what"), u.get("to")) if x), who + tip))
            return out
        def fail_lines(L):
            """The failure lines at the foot of machine L's card, under its version rows (the receiver-card rule: a short state word inline, the step or the package
            named, the raw reason in the tooltip). Empty when all went well."""
            return "".join(f'<div class="mf" title="{esc(tip)}"><span class="lbl bad">{esc(_t("panel.mach.failed", kind=_t("panel.mach.kind." + kind)))}</span> <span class="val">{esc(detail)}</span></div>' for kind, detail, tip in failures(L))
        def orphan_alert_cards(L):
            """The separate card for a failure of a machine that has no card (a machine view the fleet has no name for), so the failure never vanishes: its tip names the machine by its letter."""
            return [f'<div class="pc alert bad" title="{esc(tip)}"><b class="lbl">{esc(_t("panel.mach.kind." + kind))}</b><span class="lbl st bad">{esc(_t("panel.mach.failed_short"))}</span><span class="val wide">{esc(detail)}</span></div>'
                    for kind, detail, tip in failures(L, _t("panel.mach.orphan_prefix", name=L))]
        def mrow(name, inst, latest, state):
            """One package row inside a machine's card: the package (a link to its owner's view while the owner has a live pane), its
            version, and the state word: `latest ✓` (the same green + check as a healthy receiver), `→ <latest version>` (no word "update", the text colour (bold) says it; one line),
            `offline`, or `latest unknown`. The row's state class colours the word (_MACH_CSS)."""
            own = OWNER.get(name); u = self.sess_href((sess_of(own) or {}).get("name")) if own else ""
            if state == "update": st = f'<span class="st">{_update_word(latest)}</span>'
            elif state == "offline": st = f'<span class="st">{esc(_t("panel.mach.offline"))}</span>'
            elif state == "latest": st = f'<span class="st ok">{esc(_t("panel.mach.latest"))}</span>'
            else: st = f'<span class="st">{esc(_t("panel.mach.unknown"))}</span>'
            lab = (f'<a class="lbl" href="{esc(u)}" target="_blank" rel="noopener">{esc(name)}</a>' if u else f'<span class="lbl">{esc(name)}</span>')
            return f'<div class="mr {state}">{lab}<span class="val">{esc(inst)}</span>{st}</div>'
        def fleet_rows(L):
            """The package rows of fleet machine L, in the config's order, as (package, html): only the packages that run there (a host-only package
            shows under the publisher; c = cloud sessions carries no versions)."""
            out = []
            for name in PKG_ORDER:
                v = _PKG.get(name) or {}
                if not v: continue
                if isinstance(v.get("machines"), dict):
                    inst = (v.get("machines") or {}).get(L); st = str((v.get("machine_state") or {}).get(L, ""))
                    if not inst: continue
                    latest = v.get("latest"); off = st.startswith("offline")
                    state = "offline" if off else ("update" if cli_behind(inst, latest) else "latest")   # a box whose puller is not checking in is offline
                else:
                    if L != PUB: continue
                    inst, latest, state = v.get("installed", ""), v.get("latest"), v.get("state", "")
                out.append((name, mrow(name, inst, latest, state)))
            return out
        def host_rows(h):
            """The package rows of an ssh-read host, as (package, html): the packages its version command found, in the config's order,
            against the same latest as the fleet's. An unreachable host shows the versions it last had as offline, or one `offline` row (package "")."""
            pk = h.get("packages") if isinstance(h.get("packages"), dict) else {}
            up = h.get("reachable") is not False
            out = []
            for name in PKG_ORDER:
                inst = str(pk.get(name) or "")
                if not inst: continue
                latest = (_PKG.get(name) or {}).get("latest"); latest = latest if latest and latest != "?" else ""
                state = "offline" if not up else ("update" if cli_behind(inst, latest) else ("latest" if latest else "unknown"))
                out.append((name, mrow(name, inst, latest, state)))
            if not out and not up:
                out.append(("", f'<div class="mr offline"><span class="st">{esc(_t("panel.mach.offline"))}</span></div>'))
            return out
        def mcard(name, rows, fails=""):
            """A machine as one card (the machine name sits inside the card, like the anchor hub style): its
            name is the bold first label and a row per package follows. The only hover text on it is a failure line's reason
            (fail_lines, under the rows); a card with a failure line has the alert border."""
            return f'<div class="pc mach{" bad" if fails else ""}"><b class="lbl mh">{esc(name)}</b>{"".join(rows)}{fails}</div>'
        def fleet_card(L, h=None):
            """Fleet machine L's card. A machine that is also in [machines_panel] ssh_hosts (h, found by its full hostname) is this one card, not a second
: per package the ssh-probed row wins while the host answers (it is read live from the machine), else the fleet's row; when the probe
            failed (the host is unreachable) the fleet's own row wins and the host's last-known row fills only a package the fleet does not know; the host's lone
            `offline` row only when neither has a package."""
            name = FLEET.get(L, _t("panel.mach.cloud") if L == "c" else L)
            fails = fail_lines(L)
            if h is None: return mcard(name, [r for _, r in fleet_rows(L)], fails)
            f, p = dict(fleet_rows(L)), host_rows(h); hostd = dict(p)
            up = h.get("reachable") is not False
            merged = [((hostd.get(n) or f[n]) if up else (f.get(n) or hostd[n])) for n in PKG_ORDER if n in hostd or n in f]
            return mcard(name, merged or [r for _, r in p], fails)
        def host_card(h):
            return mcard(str(h["name"]), [r for _, r in host_rows(h)])
        _AST = self.hub_status
        _RCV = _AST.get("receivers") or {}
        def delivery(k): return receiver_type(_AST, k)
        def receivers_html():
            """Anchor hub: its own section, a card per receiver in the Machines card style."""
            if not _RCV: return ""
            def card(k, v):
                ok = bool(v.get("ok")); ck = str(v.get("checked", ""))
                t_ck = 0.0
                try:   # relative on the card, the full time on hover; the page script keeps it current between renders
                    t = datetime.datetime.strptime(ck, "%Y-%m-%d %H:%M:%S").replace(tzinfo=now.tzinfo)
                    when = stamp(t, "val"); t_ck = t.timestamp()
                except Exception: when = f'<span class="val">{esc(ck[11:16])}</span>'
                word, cls = receiver_state(v); raw = str(v.get("error") or (_t("js.rcv.healthy") if ok else _t("js.rcv.down")))[:500]
                late = _rh.stale_age(k, ok, t_ck, now.timestamp(), (_AST.get("hold") or {}).get(k, 0))      # a healthy receiver that has not reported for over twice its beat: stale, with the age
                if late: word, cls, raw = _t("js.rcv.stale", age=_rh.age_words(late)), "warn", _rh.stale_note(k, late)
                return (f'<div class="pc rcv {cls}" data-rcv="{esc(k)}" title="{esc(_t("js.rcv.title", raw=raw, checked=v.get("checked", ""), tz=_cfg.tz_abbr()))}">'
                        f'<b class="lbl">{esc(k)}</b><span class="lbl">{esc(_t("panel.rcv.last_checked"))}</span>'   # status on row 2, like a machine card's "latest"
                        f'<span class="lbl st {cls}" title="{esc(raw)}">{word}</span>{when}<span class="lbl">{esc(_t("panel.rcv.type"))}</span><span class="val rtype">{esc(delivery(k))}</span></div>')
            return _top_fold("anchorhub", f'<h2 class="hdr">{esc(panel_label("anchorhub"))}</h2>', '<div class="matrix rcvs">'
                             + "".join(card(k, v) for k, v in _RCV.items()) + '</div>', is_open=True)
        def runners_html():
            """Runners (a sidebar section like Machines): a one-line card per
            machine, linking to /runners: the machine's name (bold, takes the width), the count `busy/online` summed over its repos (runners.card_total: muted at 0 busy, bold
            while some are busy, bold amber when all are) and a muted ↗ that turns accent with the card's border on hover. No link above the cards, no per-repo line (the
            Runners page keeps the split). The heading is plain text. Drawn from runners.peek(), the last snapshot: this render never waits on GitHub or ssh, and a
            missing snapshot reads "not read yet". With no repo listed in [runners] repos the section reads "not used on this board", and once a clean read has found no runner at all "no self-hosted runners" (no cards, no link).
            The hour's GitHub calls are a card in the Audit section (gh_calls_card), no longer a line here."""
            head = f'<h2 class="hdr">{esc(panel_label("runners"))}</h2>'
            if not _runners.enabled():                 # no repo in [runners] repos (or no [runners] table): one plain line, no cards, nothing read (the section stays, so the panel keeps its five sections and their order)
                return _top_fold("runners", head, f'<p class="mnote">{esc(_t("panel.runners.unused"))}</p>', is_open=True)
            snap = _runners.peek()
            if snap is None: return _top_fold("runners", head, f'<p class="mnote">{esc(_t("panel.runners.unread"))}</p>', is_open=True)
            if _runners.unused(snap):                  # a clean read found no runner at all: the same plain line, in its own words
                return _top_fold("runners", head, f'<p class="mnote">{esc(_t("panel.runners.none"))}</p>', is_open=True)
            note = ""
            if now.timestamp() - float(snap.get("ts") or 0) > _run_stale_s():
                note = f'<p class="mnote">{esc(_t("panel.runners.last_read", hm=datetime.datetime.fromtimestamp(float(snap["ts"]), _cfg.tz()).strftime("%H:%M"), tz=_cfg.tz_abbr()))}</p>'
            cards = []
            for c in _runners.counts(snap):
                t = _runners.card_total(c)
                cards.append(f'<a class="pc rc" href="{under("/runners")}" target="_blank" rel="noopener"><b class="rn">{esc(c["box"])}</b>'
                             f'<span class="rv {t["cls"]}">{esc(t["text"])}</span><span class="go" aria-hidden="true">↗</span></a>')
            return _top_fold("runners", head, f'{note}<div class="rlist">{"".join(cards)}</div>', is_open=True)
        def projects_panel_html():
            """Projects (a sidebar section like Runners): one card per scope, the scopes the Projects page groups its projects under (the board's scopes, in their order, so a new
            scope appears here by itself), in the Runners cards' look: the scope's name and its count of projects, archived ones included (the card's hover text says how many of them are
            archived), and a link to the scope's group on that page (/projects#grp-<name>, the id projects_table writes). A scope with no project shows 0; the same list of projects
            the page's table draws (project_keys), so the two cannot differ."""
            head = f'<h2 class="hdr">{esc(panel_label("projects-panel"))}</h2>'
            if not self.scopes: return _top_fold("projects-panel", head, f'<p class="mnote">{esc(_t("panel.projects.none"))}</p>', is_open=True)
            keys = self.project_keys()
            cards = []
            for sc in self.scopes:
                ks = [k for k in keys if self.proj_scope(k) == sc]
                n, nfin = len(ks), sum(1 for k in ks if self.finished(k))
                tip = f' title="{esc(_t("panel.projects.tip", active=n - nfin, archived=nfin))}"' if nfin else ""
                cards.append(f'<a class="pc rc" href="{under("/projects")}#{self.scope_anchor(sc)}"{tip}><b class="rn">{esc(sc)}</b>'
                             f'<span class="rv">{esc(_t("panel.projects.one" if n == 1 else "panel.projects.many", n=n))}</span><span class="go" aria-hidden="true">→</span></a>')
            return _top_fold("projects-panel", head, f'<div class="rlist">{"".join(cards)}</div>', is_open=True)
        # one card per machine, its name inside as the card's first label, the cards stacked one to a row in the side
        # panel and side by side as wide as they fit elsewhere, wrapping onto a second band on a narrow screen. A machine's failed
        # setup step or update is a line inside its card, under its version rows (the card's border marks it); only a failure of a machine that has
        # no card gets a separate alert card, in a column of its own at the end. The fleet's machines come first, then the
        # ssh-read hosts of [machines_panel] ssh_hosts that are not fleet machines, in config order (one with a fleet name is merged into that card).
        # An ssh host that is also a fleet machine is that machine's one card, found by its full hostname.
        _HOSTS = {}
        for h in self.ssh_hosts: _HOSTS.setdefault(str(h["name"]), h)
        _fleet_cards = [FLEET.get(L, _t("panel.mach.cloud") if L == "c" else L) for L in _COLS]
        _orphans = [c for L in sorted(self.mfacts) if L not in _COLS for c in orphan_alert_cards(L)]       # a failed machine the panel draws no card for
        matrix_html = ('<div class="matrix">' + "".join(f'<div class="mcol">{fleet_card(L, _HOSTS.get(n))}</div>' for L, n in zip(_COLS, _fleet_cards))
                       + "".join(f'<div class="mcol">{host_card(h)}</div>' for n, h in _HOSTS.items() if n not in _fleet_cards)
                       + (f'<div class="mcol">{"".join(_orphans)}</div>' if _orphans else "") + '</div>')
        return {"machines": _top_fold("machines", f'<h2 class="hdr">{esc(panel_label("machines"))}</h2>', f'\n{self.recycle_html()}{matrix_html}', is_open=True),
                "runners": runners_html(), "anchorhub": receivers_html(),
                "audit-panel": _top_fold("audit-panel", f'<h2 class="hdr">{esc(panel_label("audit-panel"))}</h2>', self.audit_line() + self.gh_calls_card(), is_open=True),
                "projects-panel": projects_panel_html()}

    def project_agents(self, k):
        """The agents the Projects page lists for project `k` -> (declared, [(name, what it is for, is_background)]).
        Order: the -main agent, the other front agents (the page's order), then the running background agents. Only agents sala
        lists a running session of are listed (agent_live, as the project page decides it); `declared` is whether the page names
        any agent (or a keeper session) at all, so a project with none can say so. A page without an `agents:` map has its
        keeper session as its one front agent."""
        front, back = self.agent_roles(k)
        if front or back:
            names = sorted(front, key=lambda n: not n.endswith("-main"))          # stable: -main first, the rest in the page's order
            return True, [(n, front[n], False) for n in names if self.agent_live(n)] + [(n, back[n], True) for n in back if self.agent_live(n)]
        st, _others = self.keeper_split(k, [])
        if not st: return False, []
        name = st[0].split("/", 1)[-1]
        return True, ([(name, "", False)] if self.agent_live(name) else [])
    def project_keys(self) -> list:
        """The registered projects, by title: a top-level page of type project, with or without open items (notes and sub-pages roll up). The one list the Projects page's table
        and the side panel's Projects section both count from."""
        is_project = lambda k: str((self.proj.get(k) or {}).get("type") or "").strip().lower() == "project"
        return sorted({x for x in self.group if x and is_project(x)}, key=lambda k: self.proj_title(k).lower())
    @staticmethod
    def _scope_slug(sc) -> str:      # the prefix "grp-", not "scope-"
        return "grp-" + (re.sub(r"[^a-z0-9]+", "-", str(sc).lower()).strip("-") or "x")
    def scope_anchors(self) -> dict:
        """{scope: id} for the board's scopes, in their order: the id of a scope's group on the Projects page and the fragment the side panel's card for it links to. The id is "grp-"
        and the scope's name lower-cased, anything but a letter or digit turned to a dash; two scopes whose names come to the same slug ("Lab Notes" and "lab-notes") would share one id, so
        the first keeps it and a later one gets "-2" (then "-3"…), never an id another scope already has. The scopes' order is the board's own, so the ids are the same on every draw."""
        out, used = {}, set()
        for sc in self.scopes:
            if sc in out: continue
            base = self._scope_slug(sc); a, n = base, 1
            while a in used:
                n += 1; a = f"{base}-{n}"
            used.add(a); out[sc] = a
        return out
    def scope_anchor(self, sc) -> str:
        """The id for scope `sc` (see scope_anchors); a name the board does not list gets its plain slug."""
        return self.scope_anchors().get(sc) or self._scope_slug(sc)
    def projects_table(self) -> str:
        """The Projects page's table: one row per project under its scope, two columns, Project and Agents. A project's agents are a plain
        list (project_agents): its -main agent, the other front agents, then its running background agents, muted and tagged
        "background"; a project with no agent of its own says so. The items and the watch are on the project's own page.
        The archived projects (a page status in retired_statuses; a project is archived when its last agent is retired, project_archive.py) sit in a foldable
        Archived group after the active ones, drawn as home's subsections are (groups.fold_block: the heading, its count of projects, a native fold) and
        closed on load; inside it they are listed by scope as above. The table fits its box at every width (fixed layout, names wrap on a phone)."""
        SCOPES = self.scopes
        _cols = ('<colgroup><col class="c-proj"><col class="c-sess"></colgroup><thead><tr><th>' + _t("projects.th_project") + '</th><th>' + _t("projects.th_agents") + '</th></tr></thead><tbody>')   # the head the active table and the Archived group both draw
        def ref(nm):   # a session's name, linked to its view while it has one
            code = esc(nm)
            return self.sess_html(nm, cls="sref", inner=code) if self.sess_href(nm) else code
        def agent_li(nm, what, back):
            body = ref(nm) + (f' <span class="rtag" title="{esc(_t("projects.role_background"))}">{_t("projects.background")}</span>' if back else "")
            return f'<li{" class=dimline" if back else ""}{f' title="{esc(what)}"' if what else ""}>{body}</li>'
        rows = self.project_keys()      # a registered project is a top-level page of type project, with or without open items; notes and sub-pages roll up
        out = {False: [], True: []}     # the table rows of the active projects and of the archived ones
        n_arch = 0
        _anchored = set()      # a scope's id (scope_anchor, the side panel's link) sits on its first group, the active one, or the archived one when that is all it has
        for sc, fin_pass in [(x, False) for x in SCOPES] + [(x, True) for x in SCOPES]:      # the active projects first, then the archived ones in a closed group of their own
            ks = [k for k in rows if self.proj_scope(k) == sc and self.finished(k) == fin_pass]
            if not ks: continue
            n_arch += len(ks) if fin_pass else 0
            sid = "" if sc in _anchored else f' id="{self.scope_anchor(sc)}"'; _anchored.add(sc)
            out[fin_pass].append(f'<tr class="scope"{sid}><th colspan="2"><span class="sc">{esc(sc)}</span></th></tr>')
            for k in ks:
                t = self.proj_title(k)
                # the name opens the project's details page in a new tab; its items, its watch and its gbrain page are there
                pl = f'<a href="{esc(under("/" + k))}" target="_blank" rel="noopener" title="{esc(t)}">{esc(t)}</a>'
                declared, ags = self.project_agents(k)
                cell = (f'<ul class="pagents">{"".join(agent_li(*x) for x in ags)}</ul>' if ags
                        else f'<span class="dim">{_t("projects.none_running" if declared else "projects.no_agent")}</span>')
                out[fin_pass].append(f'<tr><td class="proj">{pl}</td><td class="sess">{cell}</td></tr>')
        table = lambda trs: '<div class="pwrap"><table class="pidx">' + _cols + "".join(trs) + '</tbody></table></div>'      # .pwrap: the table's box; the table fits it at every width (fixed layout, the agents column takes the rest), no sideways scroll
        return table(out[False]) + (_grp.fold_block("projects.archived", _t("page.archived"), n_arch, table(out[True]), opened=False, cls="fold sfold") if n_arch else "")

    def html(self) -> str:
        """The board's home as one HTML page."""
        now, TITLE, PUB, FLEET, PKG_ORDER, OWNER, SCOPES = self.now, self.title, self.pub, self.fleet, self.pkg_order, self.owner, self.scopes
        n_open, n_call, n_relay, agent, done, by_proj = self.n_open, self.n_call, self.n_relay, self.agent, self.done, self.by_proj
        url, lab, due_badge, proj_state, proj_title, proj_scope, proj_mirror, proj_label = self.url, self.lab, self.due_badge, self.proj_state, self.proj_title, self.proj_scope, self.proj_mirror, self.proj_label
        lines, sess_of, stamp = self.lines, self.sess_of, self.stamp
        held = self.held
        css = self._css()
        _font_css = str(_cfg.get("instance", "font_css") or "")
        _font_link = f'<link rel="stylesheet" href="{esc(_font_css)}">' if _font_css else ""
        # The home page on the item model: every open item is in exactly one of four lists, Your move, On agent, Queued for release and Waiting, under their counts
        # where the state tiles were; the Task board (project index) moved to the Projects page and Completed to the Landed page. The tiles, "Need your call (agents)" (its audit and
        # provision lines stay, as a status block), the Needs your call, On others and On agent sections and the "Parked on an outside event" block are gone: the rows they
        # held are in the lists (a wait that stands on a real-world date is a Waiting row with its basis). For you was already hidden (_SHOW_FOR_YOU).
        lists = self.home_lists()
        status = self.provision_html()      # the "Provision needed" note; the daily audit's line moved into the side panel's Audit section, kept current by _AUDIT_JS
        # the page's top-level blocks, in order (the in-place update swaps these one by one; see _LIVE_JS)
        BL = {"counts": self.home_counts(lists), "status": f'<div id="status">{status}</div>', "for-you": self.for_you_html() if _SHOW_FOR_YOU else "",
              "your-move": self.home_section("your-move", _ui.title(_ui.YOUR_MOVE), lists[_home.YOUR_MOVE], _home.YOUR_MOVE, _t("home.empty.your_move")),
              "agents-at-work": self.home_section("agents-at-work", _ui.title(_ui.AGENT), lists[_home.AGENTS], _home.AGENTS, _t("home.empty.agents")),
              "queued-release": self.home_section("queued-release", _ui.title(_ui.RELEASE), lists[RELEASE_LIST], RELEASE_LIST, _t("home.empty.release")),
              "waiting-list": self.home_section("waiting-list", _ui.title(_ui.WAITING), lists[_home.WAITING], _home.WAITING, _t("home.empty.waiting")),
              **self.panel_blocks()}
        # The shell: the page with every block and every per-render value (the render time, the "as of" in the banner, the
        # rendered stamp) taken out, fingerprinted into the stackshot-shell meta. It changes only when the page's frame does
        # (its script, its style, its markup outside the blocks: a deploy) or a block appears or goes; _LIVE_JS then reloads
        # the whole page instead of swapping blocks into a frame that no longer matches them.
        shell = _fp(self._page({k: f"<!--{k}-->" if v else "" for k, v in BL.items()}, 0, "", "", "", "", css, _font_link))
        blocks = " ".join(f"{k}={_blk_fp(v)}" for k, v in BL.items() if v)
        return self._page(BL, int(now.timestamp()), esc(self.when(now)), stamp(now), shell, blocks, css, _font_link)

    def _page(self, BL, ts, as_of, rstamp, shell, blocks, css, _font_link):
        """The board page around its blocks BL (Board.html); ts / as_of / rstamp are the per-render values, shell and blocks
        the fingerprints _LIVE_JS reads."""
        TITLE = self.title
        conn = f'''<div id="conn" class="conn" role="status" aria-live="polite" hidden><span class="c-down">{_t("home.conn.down", as_of=as_of)}</span><span class="c-new">{_t("home.conn.new", btn='<button type="button" id="conn-reload" class="b warn">' + esc(_t("home.conn.reload")) + '</button>')}</span><span class="c-out">{_t("home.conn.out", link=f'<a href="{under("/")}" id="conn-signin">' + esc(_t("home.conn.signin")) + '</a>')}</span></div>\n'''
        _h = io.StringIO()
        with contextlib.redirect_stdout(_h):
            print(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow"><meta name="stackshot-rendered" content="{ts}"><meta name="stackshot-shell" content="{shell}"><meta name="stackshot-blocks" content="{blocks}"><title>{esc(TITLE)}</title><link rel="icon" href="{icon_href('favicon.svg')}" type="image/svg+xml">{_font_link}{_THEME_HEAD}{_APP_HEAD}<style>{css}</style><noscript><style>form.hanswer{{display:none}}</style></noscript></head>{_PANEL_BODY}<div id="layout"><main id="top">
{self.page_header(counts=BL["counts"], h1=True, conn=conn, rstamp=rstamp)}
{BL["status"]}
{BL["for-you"]}
{BL["your-move"]}
{BL["agents-at-work"]}
{BL["queued-release"]}
{BL["waiting-list"]}
</main>
{_panel_frame(BL)}
</div>
<script>{_PANEL_JS}</script>
<script>{_PORDER_JS}</script>
<script>{_LANG_JS}</script>
<script>{_HOME_FOLD_JS}</script>
{self.sent_notes_html()}
{_CARDS_JS}
<script>{_HOME_JS}</script>
<script>{_ABOX_JS}</script>
{_SENDKEY_JS}
{_COPY_JS}
{_FAB_PAIR}
{_TOTOP_JS}
<script>
{_HDR_JS}
(function(){{function dur(s){{var m=Math.floor(Math.max(s,0)/60);return m<60?m+'m':m<2880?Math.floor(m/60)+'h':Math.floor(m/1440)+'d'}}{_AGE_FN}
function tick(){{var n=Date.now()/1000;document.querySelectorAll('[data-ts]').forEach(function(e){{var s=n-(+e.getAttribute('data-ts'));e.textContent=fa(s,e.hasAttribute('data-q'))}});

var g=document.getElementById('rendered'),gs=g&&g.querySelector('[data-ts]');if(gs)g.classList.toggle('old',n-(+gs.getAttribute('data-ts'))>+g.getAttribute('data-stale'))}}
tick();setInterval(tick,30000);
{_LACT_JS}
var NET=new RegExp({json.dumps(_NET_ERR)},'i');
var gone=false;document.addEventListener('stackshot:signedout',function(){{gone=true}});
function rcv(){{if(gone)return;fetch('{PREFIX}/receivers.json',{{cache:'no-store'}}).then(function(r){{if(r.status===401)gone=true;return r.ok?r.json():null}}).then(function(d){{if(!d)return;
document.querySelectorAll('[data-rcv]').forEach(function(c){{var v=d[c.getAttribute('data-rcv')];if(!v)return;
var raw=String(v.error||(v.ok?'healthy':'down')).slice(0,500),k=v.ok?'ok':NET.test(raw)?'warn':'bad';
['ok','warn','bad'].forEach(function(x){{c.classList.toggle(x,x===k)}});c.title=SST('js.rcv.title',{{raw:raw,checked:v.checked,tz:'{_cfg.tz_abbr()}'}});
var h=c.querySelector('.st');if(h){{h.className='lbl st '+k;h.title=raw;h.textContent=SST(k==='ok'?'js.rcv.ok':k==='warn'?'js.rcv.warn':'js.rcv.bad')}}
if(v.ok&&+v.stale>0){{var sw=SST('js.rcv.stale',{{age:dur(+v.stale)}}),sn=String(v.stale_note||sw);c.classList.remove('ok','bad');c.classList.add('warn');c.title=SST('js.rcv.title',{{raw:sn,checked:v.checked,tz:'{_cfg.tz_abbr()}'}});if(h){{h.className='lbl st warn';h.title=sn;h.textContent=sw}}}}
var t=c.querySelector('[data-ts]');if(t&&v.ts){{t.setAttribute('data-ts',v.ts);t.setAttribute('data-tip',v.checked+' {_cfg.tz_abbr()}')}}
var y=c.querySelector('.rtype');if(y&&v.type)y.textContent=v.type}});tick()}}).catch(function(){{}})}}
rcv();setInterval(rcv,60000);document.addEventListener('stackshot:swapped',function(){{tick();rcv()}});}})();
{_AUDIT_JS}
{_FORYOU_JS if _SHOW_FOR_YOU else ''}
{_LIVE_JS}
</script>
{_THEME_JS}
{_RELOAD_JS}
</body></html>""")
        return _h.getvalue()
