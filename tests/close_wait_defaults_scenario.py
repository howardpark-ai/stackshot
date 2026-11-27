"""Scenario test for two defaults a call may leave out (fixture data, no live store, no network, no server socket): a close with no outcome on an item whose every step is done or dropped
is closed as done with the server's words, marked as the server's; a wait with nothing that can wake it (on an item, anchor, relay or event with no end, or a time wait, park or hold with no
date) gets the default backstop day, 14 days from today, marked as the server's and shown so in the agent reads. Two rules switch them off, and the call is then judged as it was before the
defaults existed: (A) the default close applies only to a call that passes nothing outside its allow list (checked from the tools' signatures, every other parameter one by one); (B) no
default applies while the item holds a question or call for the owner he has not answered (decision, an ask, options, a your-call), parked or not, nor to a close right after such a call.
A blank or "none" date is no date of the caller's; an expected-by is never read, an unreadable one included; the wake pass drops the mark with the day. An open step, no steps at all, a
date in the past and a day the caller gives past the cap or with no reason stay refused, whichever old name carries it; an anchor's notice still releases what it released before; two
writers racing on the same item end in one consistent state.

    tests/run-suite close_wait_defaults  -> exit 0 / 1"""
import asyncio, contextlib, datetime, importlib.util, io, json, os, re, sys, pathlib, tempfile, time, logging, hashlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="cwdtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the item model's data layer, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", subject=None, desc=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su,
                                                              "metadata": {"owner": owner or U["home-front"], "project": "projects/alpha", "next": "do the thing", **meta}}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.waits import waiting as W; from stackshot.web import render; from stackshot.github import ghsync; from stackshot.model import states; from stackshot.model import model
from stackshot.web.tools import get as _get_tool
from stackshot.service import client_reads as client_reads_svc
from stackshot.service import update as _update_svc
from stackshot.service import store as _service_store
from stackshot.anchors import anchors as _anc
from stackshot.core import instance as _core_instance
from stackshot.core import config as _cfg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import checks as checks_svc
from stackshot.web.tools import brief as _wt_brief
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import notes as _wt_notes
from stackshot.web.tools import text as _wt_text
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda gid, owner, note, tag="wake": None
def _pr_open(ref, now, gh_st):
    """No network: a pull request an event wait names reads as open, not merged (the wait's end day is what this suite is about, not the PR; event_wait reads PRs)."""
    gh_st[checks_svc.check_ref(ref)] = {"merged": False, "err": "", "next": now + 300}
    return False, ""
checks_svc.pr_merged = _pr_open
FB = telling.fallback_mover("projects/alpha")      # the project's builder, else its -main agent (here its first front agent): what an item nothing else names is moved by, never its creator
assert FB == "home-front", FB
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
BACK, OTHER, GONE = "team-back", "home-other", "home-gone"      # as the update path stores a name the registry does not know
UB, UO = U["team-back"], U["home-other"]

from stackshot.model.model import Model, Wait   # noqa: E402
OWN = model.owner_display()            # the owner as the instance names him ("the owner" in the example config)
NOW = now0
FUT, PAST = day(5), day(-3)
ASK = "Decide: ship the thing now · Recommend: yes · Stakes: a week of delay · By: no date"
mt = lambda i, letter="a": rd(i, letter)["metadata"]
raw = lambda i, letter="a": (T / f"store/{letter}/{i}.json").read_text()
def upd(i, **kw): return _update_svc._update(f"a{i}", sender="home-front", **kw)

# ================================================================ helpers
from stackshot.core import call_log as _CL
import threading
from stackshot.web.ui import render as ui_render
NEWB = "- the export is live\n- the nightly run takes a minute"
def with_fixes(f):
    tok = _CL.begin()
    try:
        out = f()
    except BaseException:
        _CL.end(tok)
        raise
    return out, _CL.end(tok)
def S(text, status): return {"text": f"home-front: {text}", "status": status, "by": "", "at": 0}
def done_item(i, *statuses, **kw):
    item(i, next="\n".join(f"home-front: step {n}" for n, s in enumerate(statuses, 1) if s == "open"), steps=[S(f"step {n}", s) for n, s in enumerate(statuses, 1)], **kw)
def updt(i, **kw): return _wt_update.stackshot_update(f"a{i}", sender="home-front", **kw)
def comp(i, **kw): return _wt_complete.stackshot_complete(f"a{i}", sender="home-front", **kw)

# ================================================================ 1. a close with no outcome, every step done or dropped
done_item(60, "done", "dropped", "done")
out, fx = with_fixes(lambda: comp(60))
r60 = rd(60)
check("close: a close with no outcome, reason or outcome_text on an item whose every step is done or dropped closes it as done", r60["status"] == "completed" and r60["metadata"].get("outcome") == "done", r60)
check("close: ...with the server's reason (a step was dropped: done or dropped)", r60["metadata"].get("reason") == "closed with every step done or dropped (set by the server)", r60["metadata"])
check("close: ...and the server's outcome bullet", r60["metadata"].get("outcome_text") == "- every step is done or dropped (set by the server)", r60["metadata"])
check("close: ...the reply says so in plain words, naming what the server wrote and how to give the real end state", [k for k, _ in fx] == ["outcome-defaulted"] and "left out outcome, reason, outcome_text" in fx[0][1]
      and "closed with every step done or dropped (set by the server)" in fx[0][1] and "every step is done or dropped (set by the server)" in fx[0][1] and "reopen" in fx[0][1] and "(set by the server)" in _CL.reply_note(fx), fx)
check("close: ...the reply carries the line through the reply note (the text the client is shown)", _CL.reply_note(fx).startswith("\n(fixed for you: ") and "closed with every step done or dropped (set by the server)" in _CL.reply_note(fx), _CL.reply_note(fx))
check("close: ...and the line invites no resend", "outcome-defaulted" in _CL.NO_RESEND and "send it again" not in _CL.reply_note(fx), _CL.reply_note(fx))

done_item(61, "done", "done")
out, fx = with_fixes(lambda: comp(61, reason="shipped in the release"))
check("close: the reason the caller gave is kept; the outcome and the bullet are the server's", rd(61)["metadata"].get("reason") == "shipped in the release" and rd(61)["metadata"].get("outcome") == "done"
      and rd(61)["metadata"].get("outcome_text") == "- every step is done (set by the server)" and "left out outcome, outcome_text" in fx[0][1] and "shipped in the release" not in fx[0][1], (rd(61)["metadata"], fx))
done_item(62, "done")
out, fx = with_fixes(lambda: comp(62, outcome_text=NEWB))
check("close: the outcome bullets the caller gave are kept; the outcome and the reason are the server's", rd(62)["metadata"].get("outcome_text") == NEWB and rd(62)["metadata"].get("reason") == "closed with every step done (set by the server)"
      and rd(62)["metadata"].get("outcome") == "done", rd(62)["metadata"])
done_item(63, "done")
out, fx = with_fixes(lambda: comp(63, outcome="done", reason="it works", outcome_text=NEWB))
check("close: a full outcome is unchanged: stored as given, no fix told", rd(63)["metadata"].get("reason") == "it works" and rd(63)["metadata"].get("outcome_text") == NEWB and fx == [], (rd(63)["metadata"], fx))
LONG = "- " + "the export was rewritten so that every nightly run reads the new table once and writes one file. " * 3
done_item(64, "done")
out, fx = with_fixes(lambda: comp(64, outcome_text=LONG.strip()))
check("close: a bullet over the length limit keeps its split-and-say behaviour beside the default", {k for k, _ in fx} == {"outcome-bullet", "outcome-defaulted"} and rd(64)["status"] == "completed"
      and all(len(l) <= 120 for l in rd(64)["metadata"]["outcome_text"].splitlines()), (fx, rd(64)["metadata"].get("outcome_text")))

# an open step, no steps at all, another outcome: nothing is written, the refusal says what is missing
done_item(65, "done", "open", "open")
was = raw(65)
refused("close: open steps leave the item open and the refusal names them by number", lambda: comp(65), "steps 2, 3 are still open", "Nothing is written and the item stays open")
check("close: ...nothing is written", raw(65) == was and rd(65)["status"] == "open", None)
done_item(66, "done", "open")
refused("close: one open step is named in the singular", lambda: comp(66), "step 2 is still open")
item(67, next="")
refused("close: an item with no steps and no outcome is refused with that said", lambda: comp(67), "no steps and no outcome", "Nothing is written")
check("close: ...and it stays open", rd(67)["status"] == "open", None)
done_item(68, "done")
refused("close: outcome=dropped with no reason is not defaulted (the default is the done close)", lambda: comp(68, outcome="dropped"), "needs reason, outcome_text")
refused("close: an outcome_text with an open step and no outcome is still refused", lambda: comp(65, outcome_text=NEWB), "steps 2, 3 are still open")

# update with status=completed: marks in the same call count
item(69, next="home-front: first\nhome-front: second", steps=[S("first", "open"), S("second", "open")])
refused("close: the same refusal through update", lambda: upd(69, status="completed"), "steps 1, 2 are still open")
out, fx = with_fixes(lambda: upd(69, status="completed", done=[1], dropped=[2]))
check("close: steps marked in the closing call count: the item closes with the defaults", rd(69)["status"] == "completed" and rd(69)["metadata"].get("reason") == "closed with every step done or dropped (set by the server)"
      and [k for k, _ in fx] == ["outcome-defaulted"], (rd(69), fx))

# ================================================================ 2. a wait with no end day
item(70, needs=[BACK], subject="[home] a blocker")
item(71, needs=[BACK], subject="[home] waits after it")
out, fx = with_fixes(lambda: updt(71, after=["a70"]))
m71 = mt(71)
EXP14 = day(14)
check("wait: a wait after another item with no end stores the default backstop day (14 days from today)", m71.get("ask_by") == EXP14 or m71.get("until") == EXP14, m71)
check("wait: ...marked as set by the server", m71.get("until_server") == EXP14, m71)
check("wait: ...and the reply says what the server stored and that the mover replaces it", [k for k, _ in fx] == ["wait-end-defaulted"] and EXP14 in fx[0][1] and "set by the server" in fx[0][1] and "replaces it with the real day" in fx[0][1], fx)
g71 = _wt_get.stackshot_get("a71")
check("wait: get shows the date and the server mark on the model line", "end date " + EXP14 + " set by the server; its mover replaces it with the real day" in g71, g71)
page71 = ui_render.Board(f"{tmp}/store").item_html("a71")
check("wait: the item page shows the mark beside the end date", "end date set by the server; its mover replaces it with the real day" in page71, (re.search(r'<section class="iwait">.*?</section>', page71, re.S) or [""])[0][:600])

item(72, needs=[BACK], subject="[home] blocker with an expected day", state="doing", expected_by=day(3))
item(73, needs=[BACK], subject="[home] waits after it")
upd(73, after=["a72"])
check("wait: an awaited item's expected-by is never read: the default is 14 days from today", (mt(73).get("ask_by") or mt(73).get("until")) == EXP14 and mt(73).get("until_server") == EXP14, mt(73))

updt(73, until=day(5))
check("wait: a day the caller sends is the caller's own: the mark goes", "until_server" not in mt(73) and (mt(73).get("ask_by") or mt(73).get("until")) == day(5), mt(73))

item(74, needs=[BACK], subject="[home] relay no end", wait_kind="relay", wait_event="the vendor's reply", post_wake_mover="team-back")
out, fx = with_fixes(lambda: upd(74, wait_event="the vendor replies"))
check("wait: a stored relay wait with no end gets the default day when another field is edited", (mt(74).get("ask_by") or mt(74).get("until")) == EXP14 and mt(74).get("until_server") == EXP14 and [k for k, _ in fx] == ["wait-end-defaulted"], (mt(74), fx))

# an end the caller gives is kept, and replaces the server's
out, fx = with_fixes(lambda: updt(74, until=day(6)))
check("wait: the caller's own end day replaces the server's and drops the mark", (mt(74).get("ask_by") or mt(74).get("until")) == day(6) and "until_server" not in mt(74) and fx == [], (mt(74), fx))
item(75, needs=[BACK], subject="[home] given end", after=["a70"], wake=day(6))
upd(75, next="home-front: look again")
check("wait: a wait that has an end gets no default and no mark", "until_server" not in mt(75) and (mt(75).get("wake") == day(6)), mt(75))
upd(71, clear_wait=True, clear_after=True)
check("wait: ending the wait drops the server mark", "until_server" not in mt(71), mt(71))

# a time wait with no date: the same server-set backstop day, told; the guard text itself (the strict migration pass) still names the input
from stackshot.model import model_guards as _mgd
from stackshot.service import gates as _gates_svc
def time_item(): return {"status": "open", "subject": "[home] time", "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "home-front: wait", "wait_kind": "time", "needs": [BACK], "mover": BACK}}
probs, _ = _mgd.check(time_item(), _mgd.Ctx(label=lambda x: x, shown=lambda x: x), creating=True)
txt = " ".join(p.text for p in probs)
check("wait: the guard still names a time wait's missing date (what the strict pass refuses), and no longer says it has no safe default", any(p.key == "wait_input" for p in probs) and "needs its date" in txt and "no safe default" not in txt, txt)
ti = time_item()
with_fixes(lambda: _gates_svc.gate_model(ti, None, "a99", creating=True))
check("wait: the write gate accepts a time wait with no date and stores the default day, marked", ti["metadata"].get("until") == EXP14 and ti["metadata"].get("until_server") == EXP14, ti["metadata"])
ti3 = time_item()
try:
    _gates_svc.gate_model(ti3, None, "a99", creating=True, strict=True); strict_t = False
except Exception as e:
    strict_t = "needs its date" in str(e)
check("wait: the strict (migration) gate still refuses it and stores nothing", strict_t and not any(k in ti3["metadata"] for k in ("until", "ask_by", "until_server")), ti3["metadata"])
ti4 = time_item(); ti4["metadata"]["recycle"] = True
check("wait: a recycle wait is no time wait with no date: nothing is stored", _gates_svc._default_wait_end(ti4, "a99", True) == "" and "until" not in ti4["metadata"], ti4["metadata"])
refused("wait: an end date in the past stays refused", lambda: updt(74, until=PAST), "already past")

# ---- review fixes: the storage form, the kind, create, the other kinds, and the paths that must not default
item(80, needs=[BACK], subject="[home] blocker for storage")
item(81, needs=[BACK], subject="[home] storage form")
upd(81, after=["a80"])
m81 = mt(81)
check("storage: the update path stores the default as until (folded), no ask_by or wake beside it", m81.get("until") == EXP14 and "ask_by" not in m81 and "wake" not in m81, m81)
check("storage: ...the kind is stamped item and the server mark is the same day", m81.get("wait_kind") == "item" and m81.get("until_server") == EXP14, m81)
check("storage: ...the stored wait reads back as that end", _WT.stored_until(m81) == EXP14, m81)
g81 = _wt_get.stackshot_get("a81")
check("storage: get shows the day and the mark", EXP14 in g81 and "set by the server" in g81, g81)
page81 = ui_render.Board(f"{tmp}/store").item_html("a81")
check("storage: the item page shows the Until row and the mark", "<dt>Until</dt>" in page81 and "end date set by the server" in page81, (re.search(r'<section class="iwait">.*?</section>', page81, re.S) or [""])[0][:600])
upd(81, clear_wait=True, clear_after=True)
m81 = mt(81)
check("storage: clearing the wait removes the end, the kind and the mark", not any(k in m81 for k in ("until", "until_server", "ask_by", "wake")) and "wait_kind" not in m81, m81)
upd(81, after=["a80"])
check("storage: a later wait gets its own default", mt(81).get("until") == EXP14 and mt(81).get("until_server") == EXP14, mt(81))
updt(81, until=day(6))
check("storage: the caller's end replaces it as until, with no mark", mt(81).get("until") == day(6) and "until_server" not in mt(81) and mt(81).get("wait_kind") == "item", mt(81))
item(82, needs=[BACK], subject="[home] close the waiting item", state="doing")
upd(82, after=["a80"])
try:
    out82 = updt(82, status="completed", outcome="done", reason="finished by hand", outcome_text="- it is done")
except Exception as e:
    out82 = "ERR " + str(e)
check("storage: closing a waiting item with the server's end clears the end and the mark, no model conflict", rd(82)["status"] == "completed" and "until_server" not in mt(82) and "ERR" not in out82, (mt(82), out82))

# create with after stamps the item kind and stores until
r = _wt_create.stackshot_create(subject="[home] created waiting", description=DESC, project="projects/alpha", sender="home-front", needs=[BACK], after=["a80"], next=f"{BACK}: wait for it")
cid = re.search(r"created [a-z]?(\d+)", r or "")
cm = json.loads(next(T.glob(f"store/*/{cid.group(1)}.json")).read_text())["metadata"] if cid else {}
check("create: a create with after and no end stores the default as until, kind item stamped, marked", cm.get("until") == EXP14 and cm.get("wait_kind") == "item" and cm.get("until_server") == EXP14, (cm, r))

# the other kinds: a stored wait with no end gets the day, each kind
item(83, needs=[BACK], subject="[home] anchor no end", wait_kind="anchor", wait_anchor="https://example.org/pull/7", wait_event="merged", post_wake_mover=BACK)
out, fx = with_fixes(lambda: upd(83, wait_event="merged for real"))
check("wait: a stored anchor wait with no end gets the default day, marked and told", (mt(83).get("until") or mt(83).get("ask_by")) == EXP14 and mt(83).get("until_server") == EXP14 and [k for k, _ in fx] == ["wait-end-defaulted"], (mt(83), fx))
item(84, needs=[BACK], subject="[home] event no end", wait_kind="event", wait_event="pr_merged acme/repo#5", post_wake_mover=BACK)
out, fx = with_fixes(lambda: upd(84, wait_event="pr_merged acme/repo#6"))
check("wait: a stored event wait with no end gets the default day, marked and told", (mt(84).get("until") or mt(84).get("ask_by")) == EXP14 and mt(84).get("until_server") == EXP14 and [k for k, _ in fx] == ["wait-end-defaulted"], (mt(84), fx))

# the strict gate (the migration pass) never defaults: it refuses
def anchor_item(): return {"status": "open", "subject": "[home] anchor", "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "home-front: wait", "wait_kind": "anchor", "wait_anchor": "https://example.org/pull/8", "wait_event": "merged", "needs": [BACK], "mover": BACK, "post_wake_mover": BACK}}
sa = anchor_item()
try:
    _gates_svc.gate_model(sa, None, "a99", creating=True, strict=True); strict_refused = False
except Exception:
    strict_refused = True
check("wait: the strict (migration) gate never defaults an end: it refuses and stores nothing", strict_refused and not any(k in sa["metadata"] for k in ("until", "ask_by", "until_server")), sa["metadata"])
sa2 = anchor_item()
try:
    _gates_svc.gate_model(sa2, None, "a99", creating=True)
except Exception:
    pass
check("wait: the same item through the plain gate gets the default", sa2["metadata"].get("until") == EXP14 and sa2["metadata"].get("until_server") == EXP14, sa2["metadata"])

# close paths the default must read right
done_item(90, "done", "open"); was = raw(90)
refused("close: work is not on the allow list: a close that sends a step status, done or not, gets no default and is refused as before", lambda: _update_svc._update("a90", sender="home-front", status="completed", work={"text": "finished", "state": "done"}),
        "closing a90 needs outcome, reason, outcome_text")
check("close: ...nothing is written", raw(90) == was, rd(90)["metadata"])
done_item(91, "done", "open")
refused("close: without that tick the open step refuses, naming it by number", lambda: _update_svc._update("a91", sender="home-front", status="completed"), "step 2 is still open")
check("close: ...and nothing was written", rd(91)["status"] == "open" and "reason" not in rd(91)["metadata"], rd(91)["metadata"])
done_item(92, "done", "done")
tok92 = _CL.begin(); err92 = ""
try:
    _update_svc._update("a92", sender="home-front", status="completed", superseded_by="a70", reason="replaced by a70", outcome_text="- a70 carries it on")
except Exception as e:
    err92 = str(e)
fx92 = [k for k, _ in _CL.end(tok92)]
check("close: a close naming a replacing item closes as superseded, never as the done default", not err92 and rd(92)["status"] == "completed" and rd(92)["metadata"].get("outcome") == "superseded" and "outcome-defaulted" not in fx92 and "outcome-superseded" in fx92, (fx92, err92, rd(92)["metadata"]))
item(93, subject="[home] no steps", next="")
refused("close: no steps and no outcome is refused with those words", lambda: _update_svc._update("a93", sender="home-front", status="completed"), "no steps and no outcome")

# ---- a wait with nothing that can wake it is accepted whatever its kind: time, park, hold, verifying, expected-by; create and update, each with the mark, the page row, the client read and the close cleanup
def wait_row(i):
    return {x["shown"]: x for x in json.loads(client_reads_svc._client_items(UB)[2])["items"]}.get(f"a{i}")
def server_end_checks(label, i, fx, out=""):
    m = mt(i); note = _CL.reply_note(fx)
    check(f"{label}: the day is stored as until (14 days from today), no old working field (wake, ask_by, hold) beside it", m.get("until") == EXP14 and not any(k in m for k in ("ask_by", "wake", "hold", "hold_set")), m)
    check(f"{label}: ...marked as the server's, and told once as wait-end-defaulted", m.get("until_server") == EXP14 and [k for k, _ in fx] == ["wait-end-defaulted"], (m, fx))
    check(f"{label}: ...the reply carries the fix line with the day and the mover's replacing it", note.startswith("\n(fixed for you: ") and EXP14 in note and "replaces it with the real day" in note and note.endswith(".)") and "send it again" not in note, note)
    check(f"{label}: ...get shows the mark on the model line", f"end date {EXP14} set by the server" in _wt_get.stackshot_get(f"a{i}"), _wt_get.stackshot_get(f"a{i}")[:600])
    pg = ui_render.Board(f"{tmp}/store").item_html(f"a{i}")
    check(f"{label}: ...the item page shows the End row and the mark", "end date set by the server" in pg and ("<dt>Until</dt>" in pg or "<dt>End</dt>" in pg), (re.search(r'<section class="iwait">.*?</section>', pg, re.S) or [""])[0][:500])
    row = wait_row(i)
    check(f"{label}: ...the client read lists it as waiting on its mover", bool(row) and (row.get("mover") or {}).get("who") == BACK and row.get("list") == "waiting", row)
def closes_clean(label, i):
    try:
        updt(i, status="completed", outcome="done", reason="finished by hand", outcome_text="- it is done"); err = ""
    except Exception as e:
        err = str(e)
    m = mt(i)
    check(f"{label}: closing it clears the end, the kind and the mark", rd(i)["status"] == "completed" and not err and not any(k in m for k in ("until", "until_server", "ask_by", "wake", "wait_kind")), (err, m))

item(200, needs=[BACK], subject="[home] stored time wait, no date", wait_kind="time", mover=BACK)
out, fx = with_fixes(lambda: updt(200, mover=BACK))
server_end_checks("time wait: a stored time wait with no date, any write", 200, fx, out)
closes_clean("time wait", 200)

item(201, needs=[BACK], subject="[home] hold, no date", state="doing")
out, fx = with_fixes(lambda: updt(201, hold=True))
server_end_checks("hold: a bare hold with no date", 201, fx, out)
closes_clean("hold", 201)

item(202, needs=[BACK], subject="[home] verifying, no end", state="verifying")
out, fx = with_fixes(lambda: updt(202, mover=BACK))
server_end_checks("verifying: a verifying state with no end", 202, fx, out)
closes_clean("verifying", 202)

item(203, needs=[BACK], subject="[home] parked with an expected-by only", state="parked", expected_by=day(3))
out, fx = with_fixes(lambda: updt(203, mover=BACK))
server_end_checks("expected-by: a park with only an expected-by day", 203, fx, out)
closes_clean("expected-by", 203)

# the same forms on a create
def made(**kw):
    tok = _CL.begin()
    r = _wt_create.stackshot_create(subject=kw.pop("subject"), description=DESC, project="projects/alpha", sender="home-front", **({"needs": [BACK], "next": f"{BACK}: pick it up"} | kw))
    f = _CL.end(tok)
    n = re.search(r"created [a-z]?(\d+)", r or "").group(1)
    p = next(T.glob(f"store/*/{n}.json"))
    return n, p.parent.name, r, f
for label, kw in (("outside party", dict(needs=["external"], next="external: the vendor sends the file", wait_event="the vendor sends the file")),):
    n, letter, r, f = made(subject=f"[home] created {label}", **kw)
    m = rd(int(n), letter)["metadata"]
    check(f"create ({label}): no date stores the default as until with the mark and tells it", m.get("until") == EXP14 and m.get("until_server") == EXP14 and "ask_by" not in m and "wake" not in m and [k for k, _ in f] == ["wait-end-defaulted"] and _CL.reply_note(f).startswith("\n(fixed for you: "), (m, f, r[:300]))
    check(f"create ({label}): ...get, the page row and the client read show it", f"end date {EXP14} set by the server" in _wt_get.stackshot_get(f"{letter}{n}") and "end date set by the server" in ui_render.Board(f"{tmp}/store").item_html(f"{letter}{n}") and bool(wait_row(int(n)) if letter == "a" else True), r[:200])
    try:
        _wt_update.stackshot_update(f"{letter}{n}", sender="home-front", status="completed", outcome="done", reason="finished by hand", outcome_text="- it is done"); err = ""
    except Exception as e:
        err = str(e)
    m = rd(int(n), letter)["metadata"]
    check(f"create ({label}): closing it clears the end and the mark", not err and not any(k in m for k in ("until", "until_server", "wait_kind")), (err, m))
n, letter, r, f = made(subject="[home] created with an explicit time kind", wait_kind="time")
m = rd(int(n), letter)["metadata"]
check("create: an explicit wait_kind=time with no date keeps the existing next-day fallback (not the 14-day backstop), marked as the server's day", m.get("until") and m.get("until") != EXP14 and m.get("until_server") == m.get("until"), m)

# the dates the caller gives keep the cap rules: a time wait given 20 days out is still held to them
item(204, needs=[BACK], subject="[home] caller's own far day", state="doing")
try:
    updt(204, until=day(20), wait_kind="time", hold=True); far = ""
except Exception as e:
    far = str(e)
check("cap: a day the caller gives past the cap keeps its refusal (the default does not lift it)", "days" in far or "cap" in far or "wait_basis" in far, far[:300])

# L1: the mark goes when the awaited item closes
item(210, needs=[BACK], subject="[home] awaited item")
item(211, needs=[BACK], subject="[home] waiter with a server day")
upd(211, after=["a210"])
check("release: the waiter holds the server's day before the awaited item closes", mt(211).get("until_server") == EXP14, mt(211))
comp(210, outcome="done", reason="finished by hand", outcome_text="- it is done")
m111 = mt(211)
check("release: when the awaited item closes the waiter's end, kind and server mark go with the wait", not any(k in m111 for k in ("until", "until_server", "wait_kind", "after")), m111)
from stackshot.model import model as _model_mod
from stackshot.waits import watchers as _watchers_mod
check("release: the mark is in the wait group every clear of a wait drops (close, release, clear_wait)", _model_mod.SERVER_END_KEY in _model_mod.WAIT_GROUP and _model_mod.SERVER_END_KEY in _watchers_mod.LIVE_DROP and _model_mod.SERVER_END_KEY in _model_mod.DROP_ON_CLOSE, None)

# an anchor wait that lacks its anchor but has an end is refused for the anchor: the end is not touched and nothing is marked as the server's
sk = {"status": "open", "subject": "[home] anchor", "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "home-front: wait", "wait_kind": "anchor", "wait_event": "merged", "until": day(3), "needs": [BACK], "mover": BACK, "post_wake_mover": BACK}}
try:
    _gates_svc.gate_model(sk, None, "a99", creating=True); sk_err = ""
except Exception as e:
    sk_err = str(e)
check("wait: a wait with an end but a missing input is refused for that input and its end is left as it is", "anchor" in sk_err and sk["metadata"].get("until") == day(3) and "until_server" not in sk["metadata"], (sk_err[:200], sk["metadata"]))

# L5: the event form with a wait_kind and no day gets the next-day fallback, not the 14-day backstop
item(213, needs=[BACK], subject="[home] event form, no day")
out, fx = with_fixes(lambda: updt(213, wait_kind="event", wait_event="pr_merged acme/repo#9", mover=BACK))
check("event form: wait_kind=event with no day takes the fallback day (not the 14-day backstop), marked as the server's day, and is not told as the backstop", (_WT.stored_until(mt(213)) or "") not in ("", EXP14) and mt(213).get("until_server") == _WT.stored_until(mt(213)) and "wait-end-defaulted" not in [k for k, _ in fx], (mt(213), fx))

# L8: the caller's own end given as wake pops the mark; the fix kinds invite no resend; nine open steps say "and more"
item(212, needs=[BACK], subject="[home] given as wake")
upd(212, after=["a70"])
check("wait: (setup) a server day stands on the item", mt(212).get("until_server") == EXP14, mt(212))
upd(212, wake=day(4))
check("wait: the caller's own end given as wake replaces the server's day and pops the mark", "until_server" not in mt(212) and (_WT.stored_until(mt(212)) or mt(212).get("wake")) == day(4), mt(212))
check("wait: both defaults' fix kinds invite no resend (NO_RESEND)", {"wait-end-defaulted", "outcome-defaulted"} <= set(_CL.NO_RESEND), sorted(_CL.NO_RESEND))
done_item(95, *["open"] * 9)
refused("close: nine open steps are named by the first eight and 'and more'", lambda: comp(95), "steps 1, 2, 3, 4, 5, 6, 7, 8 and more are still open", "Nothing is written and the item stays open")
done_item(96, "dropped", "dropped")
out, fx = with_fixes(lambda: comp(96))
check("close: when every step was dropped the server's reason and bullet say done or dropped", rd(96)["metadata"].get("outcome_text") == "- every step is done or dropped (set by the server)" and rd(96)["metadata"].get("reason") == "closed with every step done or dropped (set by the server)", rd(96)["metadata"])
done_item(97, "done", "done")
out, fx = with_fixes(lambda: comp(97, outcome="done"))
check("close: an explicit outcome=done with no reason or bullet is filled in, and the reply says what was left out", rd(97)["metadata"].get("reason") == "closed with every step done (set by the server)" and "left out reason, outcome_text" in fx[0][1] and _CL.reply_note(fx).startswith("\n(fixed for you: ") and "left out reason, outcome_text" in _CL.reply_note(fx), (fx, out[:300]))
refused("close: through update the refusal reads as sentences and names the marks update takes: Nothing... Mark them...", lambda: upd(95, status="completed"), ". Mark them in the same call (done=[...] or dropped=[...])")
try:
    comp(95); e95 = ""
except Exception as e:
    e95 = str(e)
check("close: complete's refusal names only what complete takes (outcome, reason, outcome_text), never the step marks it has no parameter for", "Pass outcome, reason, outcome_text yourself" in e95 and not any(w in e95 for w in ("done=[", "dropped=[", "Mark them", "add the steps")), e95)
try:
    comp(93); e93 = ""
except Exception as e:
    e93 = str(e)
check("close: ...and so for no steps at all: complete's refusal does not tell it to add and mark steps", "no steps and no outcome" in e93 and "Pass them yourself" in e93 and "add the steps" not in e93, e93)

# ---- a close that sends anything beside its allow list (rule A), or on an item with a question open for the owner (rule B), is judged as before the default: refused with the plain
# words of a close with no outcome (none of the default's), and nothing is written
PLAIN = "needs outcome, reason, outcome_text; "
def unchanged(label, i, was_):
    check(f"{label}: ...nothing is written: the item stays open with its steps as they were", raw(i) == was_ and rd(i)["status"] == "open", rd(i)["metadata"])
def plain_refusal(label, i, f):
    was_ = raw(i)
    try:
        f(); e_ = ""
    except Exception as e:
        e_ = str(e)
    check(f"{label}: refused as before the default, in the plain words of a close with no outcome", f"closing a{i} {PLAIN}" in e_ and "Nothing is written and the item stays open" not in e_ and "set by the server" not in e_, e_[:400])
    unchanged(label, i, was_)
done_item(150, "done", "done")
plain_refusal("close+next (rule A)", 150, lambda: upd(150, status="completed", next="home-front: a new step"))
done_item(151, "done", "done")
plain_refusal("close+need+ask (rule A)", 151, lambda: upd(151, status="completed", needs=["decision"], ask=ASK))
done_item(152, "done", "done")
plain_refusal("close+work status (rule A)", 152, lambda: upd(152, status="completed", work={"text": "building it", "state": "in progress"}))
done_item(153, "done", "open")
plain_refusal("close+mark+next (rule A): marking the last step done does not let new work through", 153, lambda: upd(153, status="completed", done=[2], next="home-front: another"))
done_item(156, "done", "open")
plain_refusal("close+next+open step (rule A)", 156, lambda: upd(156, status="completed", next="home-front: brand new"))
done_item(154, "done", "done", needs=["decision"], ask=ASK)
plain_refusal(f"close+open ask (rule B): an item that still waits on {OWN}'s answer", 154, lambda: comp(154))
done_item(158, "done", "done", needs=["decision"], ask=ASK)
plain_refusal("close+clear_ask (rule A): taking the ask back in the closing call is an argument outside the list", 158, lambda: upd(158, status="completed", clear_ask=True))
done_item(155, "done", "done", check="item_closed a70"); was = raw(155)
refused("close+check: a done check that has not passed is not closed over by default", lambda: comp(155), "the item's done check (item_closed a70) has not passed")
unchanged("close+check", 155, was)
done_item(157, "done", "done")
plain_refusal("close+check given (rule A)", 157, lambda: upd(157, status="completed", check="item_closed a70"))

# ---- the server's close words are marked as the server's in metadata and in get; a reopen drops the mark
check("mark: a close the server filled lists the fields it wrote (outcome_server)", mt(60).get("outcome_server") == ["outcome", "reason", "outcome_text"] and mt(61).get("outcome_server") == ["outcome", "outcome_text"], (mt(60).get("outcome_server"), mt(61).get("outcome_server")))
check("mark: a close with every field given carries no mark", "outcome_server" not in mt(63), mt(63))
g60 = _wt_get.stackshot_get("a60")
check("mark: get marks the server's outcome, and words that already say so are not marked twice", "outcome: done (set by the server)" in g60 and "(set by the server) (set by the server)" not in g60, g60[:600])
done_item(170, "done", "done")
comp(170, reason="shipped in the release", outcome_text=NEWB)
g170 = _wt_get.stackshot_get("a170")
check("mark: get marks only the field the server wrote: the outcome, not the caller's reason or bullets", mt(170).get("outcome_server") == ["outcome"] and "outcome: done (set by the server)" in g170
      and "reason: shipped in the release\n" in g170 and "outcome text:\n" in g170, g170[:600])
try:
    updt(170, status="open", next="home-front: one more step"); e170 = ""
except Exception as e:
    e170 = str(e)
check("mark: a reopen drops the mark with the close fields", not e170 and rd(170)["status"] == "open" and "outcome_server" not in mt(170), (e170[:300], mt(170)))

# ---- the old names of a park's date are judged as the date they stand for: ask_by beside hold=true, clear_wake or a time wait keeps the future, the cap and the reason rules
for n_, d_, want in ((140, PAST, "must be in the future"), (141, day(300), "a wait runs at most"), (142, day(3), "with no reason")):
    item(n_, needs=[BACK], subject="[home] hold with ask_by", state="doing"); was = raw(n_)
    refused(f"hold+ask_by: hold=true with ask_by={d_} is refused as the same day given as until is ({want})", lambda: updt(n_, hold=True, ask_by=d_), want)
    check(f"hold+ask_by ({d_}): ...nothing is stored", raw(n_) == was, mt(n_))
    item(n_, needs=[BACK], subject="[home] hold with until", state="doing")
    refused(f"hold+until ({d_}): (the same day as until is refused for the same reason)", lambda: updt(n_, hold=True, until=d_), want)
item(143, needs=[BACK], subject="[home] time wait with ask_by", state="doing"); was = raw(143)
refused("time+ask_by: wait_kind=time with a past ask_by is refused as a past day", lambda: updt(143, wait_kind="time", ask_by=PAST), "must be in the future")
check("time+ask_by: ...nothing is stored", raw(143) == was, mt(143))
item(144, needs=[BACK], subject="[home] a hold stored the old way", hold=True, wake=day(4)); was = raw(144)
refused("clear_wake+ask_by: a past ask_by sent with clear_wake on a stored hold is refused as a past day", lambda: updt(144, clear_wake=True, ask_by=PAST), "must be in the future")
check("clear_wake+ask_by: ...the hold and its day stand", raw(144) == was, mt(144))
item(146, needs=[BACK], subject="[home] hold with ask_by and a reason", state="doing")
updt(146, hold=True, ask_by=day(3), wait_basis=f"the soak collects its logs ends {day(3)}")
check("hold+ask_by: a day inside the cap with its reason is accepted and stored as until, no ask_by beside it", mt(146).get("until") == day(3) and "ask_by" not in mt(146) and "until_server" not in mt(146), mt(146))

# ---- clear_wake on a hold stored the old way ends the park; clear_after on a defaulted item wait ends it with its server day
item(145, needs=[BACK], subject="[home] a hold stored the old way", hold=True, wake=day(4))
updt(145, clear_wake=True)
check("clear_wake: on a hold stored as hold and wake, it ends the park: no hold, no date, no server day put in its place", not any(k in mt(145) for k in ("hold", "hold_set", "wake", "until", "until_server", "wait_kind")), mt(145))
item(166, needs=[BACK], subject="[home] defaulted item wait")
upd(166, after=["a70"])
g166 = _wt_get.stackshot_get("a166")
check("mark: get's until line marks the server's day", f"until: {EXP14} (set by the server)" in g166, g166[:600])
out166 = updt(166, clear_after=True)
check("clear_after: ending the item wait drops the server's day, its mark and its kind with it", not any(k in mt(166) for k in ("until", "until_server", "wait_kind", "after", "hold", "wake", "ask_by")), mt(166))
check("clear_after: ...and the reply says so", f"the backstop day {EXP14} the server had set for that wait went with it" in out166 and "no longer waits" in out166, out166[-600:])

# ---- a bare hold ends a stored state as a hold with a date does, is never stamped a time wait, and sent again is accepted
item(165, needs=[BACK], subject="[home] hold, no date, sent twice", state="doing")
out165 = updt(165, hold=True)
check("hold: a bare hold on a doing item ends the stored state, as a hold with a date does, and says so", "state" not in mt(165) and "stored state doing dropped" in out165, (mt(165), out165[-500:]))
check("hold: ...it is a park on the server's day, not stamped a time wait", "wait_kind" not in mt(165) and mt(165).get("until") == EXP14 and mt(165).get("until_server") == EXP14, mt(165))
out, fx = with_fixes(lambda: updt(165, hold=True))
check("hold: hold=true sent again with no date is accepted: the server's day and its mark stand, nothing told twice", mt(165).get("until") == EXP14 and mt(165).get("until_server") == EXP14 and "hold" not in mt(165) and "wait-end-defaulted" not in [k for k, _ in fx], (mt(165), fx))

# ---- an anchor scoped to the item: its notice still releases what the server parked
from stackshot.service import wakes as _wakes_svc
A9 = "https://github.com/o/r/pull/909"
_anc.save({"projects/alpha": [{"url": A9, "items": ["a160", "a161", "a162"], "added": now0 - 20 * DAY, "by": "x"}]})
_wake_notify_was = _wakes_svc.wake_notify
_wakes_svc.wake_notify = lambda *a, **k: []
try:
    item(160, needs=["external"], subject="[home] outside, scoped anchor")
    out, fx = with_fixes(lambda: updt(160, wait_event="the vendor ships"))
    check("anchor: a wait read from a scoped anchor alone (no wait_anchor) gets the server's day but is not stamped an anchor wait", "wait_kind" not in mt(160) and mt(160).get("until") == EXP14 and mt(160).get("until_server") == EXP14 and [k for k, _ in fx] == ["wait-end-defaulted"], (mt(160), fx))
    item(161, needs=[BACK], subject="[home] bare hold, scoped anchor", state="doing")
    out161, fx161 = with_fixes(lambda: updt(161, hold=True))
    check("anchor: a bare hold on an item an anchor is scoped to keeps its hold flag beside the server's day", mt(161).get("hold") is True and mt(161).get("until") == EXP14 and mt(161).get("until_server") == EXP14 and "wait_kind" not in mt(161), mt(161))
    check("anchor: ...and the reply says the notice still releases it first", "the notice of the anchor scoped to the item still releases it first" in out161 + _CL.reply_note(fx161), (out161[-500:], fx161))
    m162 = {"owner": U["home-front"], "project": "projects/alpha", "next": "home-front: wait", "needs": ["external"], "wake": FUT}
    told162 = _gates_svc._default_wait_end({"status": "open", "subject": "[home] x", "metadata": m162}, "a162", False, True)
    check("anchor: a date the write already gave is kept, and an anchor read from a scoped anchor alone is not stamped there either", told162 == "" and m162.get("wake") == FUT and "wait_kind" not in m162 and "until_server" not in m162, m162)
    n9 = {"kind": "anchor", "anchor": A9, "to": "home-stew", "ruling": "passed", "ruled_at": time.time() + 30, "ts": time.time() + 30, "id": "cwd160"}
    rel = _wakes_svc.anchor_release("projects/alpha", n9)
    check("anchor: the anchor's notice releases both", {"a160", "a161"} <= set(rel), rel)
    check("anchor: ...the server's day and its mark go with the release", not any(k in mt(160) for k in ("until", "until_server")) and not any(k in mt(161) for k in ("hold", "until", "until_server")), (mt(160), mt(161)))
finally:
    _wakes_svc.wake_notify = _wake_notify_was
    _anc.save({})

# ---- an awaited item's expected-by is never read, far out or unreadable: the day is 14 days from today, marked, and the guards still judge the write
item(175, needs=[BACK], subject="[home] blocker expected far out", state="doing", expected_by=day(40))
item(176, needs=[BACK], subject="[home] waits after the far one")
out, fx = with_fixes(lambda: upd(176, after=["a175"]))
check("expected-by: a far expected-by moves nothing: the day is 14 days from today and the line says so", mt(176).get("until") == EXP14 and mt(176).get("until_server") == EXP14 and [k for k, _ in fx] == ["wait-end-defaulted"] and "14 days from today" in fx[0][1], (mt(176), fx))
for n_, bad in ((177, "9999-12-31"), (178, "2027-02-31")):
    item(n_, needs=[BACK], subject=f"[home] blocker expected {bad}", state="doing", expected_by=bad)
    item(n_ + 10, needs=[BACK], subject="[home] waits after it")
    err_ = io.StringIO()
    with contextlib.redirect_stderr(err_):
        out, fx = with_fixes(lambda: upd(n_ + 10, after=[f"a{n_}"]))
    check(f"expected-by: an unreadable one ({bad}) stops nothing: the waiter gets the 14-day day, marked and told", mt(n_ + 10).get("until") == EXP14 and mt(n_ + 10).get("until_server") == EXP14 and [k for k, _ in fx] == ["wait-end-defaulted"], (mt(n_ + 10), fx))
    check(f"expected-by ({bad}): ...the guards judged the write (no 'not judged' line)", "not judged" not in err_.getvalue() and "not defaulted" not in err_.getvalue(), err_.getvalue())
def _fill_fails(item_, meta_, *a):
    meta_["until"] = meta_["until_server"] = EXP14; meta_["wait_kind"] = "item"
    raise ValueError("a day that is no date")
_fill_was = _gates_svc._wait_end_fill
_gates_svc._wait_end_fill = _fill_fails
try:
    m_ = {"owner": U["home-front"], "project": "projects/alpha", "next": "home-front: wait", "needs": [BACK], "after": ["a70"]}; err_ = io.StringIO()
    with contextlib.redirect_stderr(err_):
        told_ = _gates_svc._default_wait_end({"status": "open", "metadata": m_}, "a99", False, True)
    check("default end: a failure inside it leaves the item as the write made it, says so on stderr and tells nothing", told_ == "" and not any(k in m_ for k in ("until", "until_server", "wait_kind")) and "a99 not defaulted" in err_.getvalue(), (told_, m_, err_.getvalue()))
    item(179, needs=[BACK], subject="[home] waits, the default fails"); was = raw(179)
    with contextlib.redirect_stderr(io.StringIO()):
        refused("default end: ...and the guards then judge the write as before the default: a wait with no end is refused", lambda: upd(179, after=["a70"]), "has no end")
    check("default end: ...nothing is stored", raw(179) == was, mt(179))
finally:
    _gates_svc._wait_end_fill = _fill_was
from stackshot.model import migration as _mig_mod
class _MigEnv:
    today = datetime.date.fromisoformat(day(0))
    def __init__(self, items): self.items = items
    def after_open(self, it): return list(it["metadata"].get("after") or [])
for bad in ("9999-12-31", "2027-02-31"):
    env_ = _MigEnv({"a1": {"metadata": {"expected_by": bad}}, "a2": {"metadata": {"expected_by": day(3)}}})
    got_ = _mig_mod.default_end(env_, {"metadata": {"after": ["a1", "a2"]}}, "item")
    check(f"expected-by: the start repair's default_end skips an unreadable expected-by ({bad}) and reads the others", got_[0] == day(5) and day(3) in got_[1], got_)
    env_ = _MigEnv({"a1": {"metadata": {"expected_by": bad}}})
    check(f"expected-by: ...and with only that one, it takes 14 days from the pass ({bad})", _mig_mod.default_end(env_, {"metadata": {"after": ["a1"]}}, "item")[0] == (_MigEnv.today + datetime.timedelta(days=14)).isoformat(), None)

# ---- the mark counts only while the stored end is the server's day
SM, STALE = {"until": EXP14, "until_server": EXP14}, {"until": day(6), "until_server": EXP14}
check("mark: server_end reads the mark only while the stored end is that day", model.server_end(SM) == EXP14 and model.server_end(STALE) == "" and model.server_end({"until_server": EXP14}) == "", None)
item(181, needs=[BACK], subject="[home] a stale mark", after=["a70"], wait_kind="item", until=day(6), until_server=EXP14)
g181 = _wt_get.stackshot_get("a181")
check("mark: get shows no server mark beside a day that is not the server's", "set by the server" not in g181 and day(6) in g181, g181[:600])
item(180, needs=[BACK], subject="[home] a stale mark, written", after=["a70"], wait_kind="item", until=day(6), until_server=EXP14)
upd(180, next="home-front: look again")
check("mark: a write drops a mark that no longer matches the stored end, and the end stays", "until_server" not in mt(180) and mt(180).get("until") == day(6), mt(180))
from stackshot.tools import board_report as _board_report
from stackshot.audit import audit_run as _audit_run
check("mark: board.md's parked mark and the brief's parked line mark the server's day (render.server_mark), not another", render.server_mark({"metadata": SM}) == " (set by the server)" and render.server_mark({"metadata": STALE}) == "", None)
check("mark: the board report's wake words mark the server's day, not another", _board_report._wake_words(SM) == f"until {EXP14} (set by the server)" and _board_report._wake_words(STALE) == f"until {day(6)}", (_board_report._wake_words(SM), _board_report._wake_words(STALE)))
check("mark: the audit's stored-wait text marks the server's day, not another", f"ends on {EXP14} (set by the server)" in _audit_run.stored_wait_text({"metadata": SM}) and "set by the server" not in _audit_run.stored_wait_text({"metadata": STALE}),
      (_audit_run.stored_wait_text({"metadata": SM}), _audit_run.stored_wait_text({"metadata": STALE})))

class _AuditEnv:
    clock = staticmethod(time.time)
    page = staticmethod(lambda p: ("", None))
def audit_head(mk):
    """The context lines the audit's obsolete-wait check gives for an item that waits after a closed one, its stored end as `mk`."""
    its = {"a500": {"id": "500", "status": "open", "subject": "[home] waits", "updated": now0, "state_updated": now0, "metadata": {"project": "projects/alpha", "after": ["a501"], "wait_kind": "item", **mk}},
           "a501": {"id": "501", "status": "completed", "subject": "[home] done", "updated": now0, "metadata": {"outcome": "done", "reason": "finished"}}}
    return _audit_run.obsolete_wait_evidence("a500", its, {"500": ["a500"], "501": ["a501"]}, _AuditEnv(), {}, 0.0)[1]
check("mark: the audit's obsolete-wait head marks the server's day", (audit_head(SM) or [""])[0].endswith(f"until {EXP14} (set by the server)"), audit_head(SM))
check("mark: ...and not a day that is not the server's", bool(audit_head(STALE)) and "set by the server" not in audit_head(STALE)[0] and f"until {day(6)}" in audit_head(STALE)[0], audit_head(STALE))

# ================================================================ rule A: the default close's allow list, checked from the tools' signatures
import inspect
UPD_P = set(inspect.signature(_wt_update.stackshot_update).parameters)
UNL_P = set(inspect.signature(_update_svc.update_unlocked).parameters)
CMP_P = set(inspect.signature(_wt_complete.stackshot_complete).parameters)
ALLOW_ = _update_svc.CLOSE_DEFAULT_ARGS
check("rule A: the allow list is the close's own fields, his recorded words and the step marks, nothing else", ALLOW_ == {"item_id", "sender", "status", "outcome", "reason", "outcome_text", "description", "superseded_by", "said", "done", "dropped"}, sorted(ALLOW_))
check("rule A: every argument of the write is a parameter of the update tool or one the tool layer computes (SERVER_ARGS): an argument added later is outside the list until it is named there",
      UNL_P - _update_svc.SERVER_ARGS <= UPD_P and _update_svc.SERVER_ARGS <= UNL_P, sorted(UNL_P - _update_svc.SERVER_ARGS - UPD_P))
check("rule A: ...and every update tool parameter reaches the write, but the retired rank pair (refused at the tool) and until (passed on as wake or ask_by)", UPD_P - UNL_P == {"rank", "clear_rank", "until"}, sorted(UPD_P - UNL_P))
check("rule A: complete passes only arguments on the list, and the list names only arguments the write has", CMP_P <= ALLOW_ and ALLOW_ <= UNL_P, (sorted(CMP_P - ALLOW_), sorted(ALLOW_ - UNL_P)))
check("rule A: an argument the write gains later is outside the list", _update_svc.close_extra_args({"status": "completed", "outcome": "", "a_new_argument": "x"}) == ["a_new_argument"], None)
check("rule A: blank, False, 0 and None are not passed; an empty list is (it clears)", _update_svc.close_extra_args({"next": "  ", "hold": False, "rank": 0, "after": None, "needs": [], "wake": "none"}) == ["needs", "wake"], None)
OPTS = [{"label": "Ship", "line": "Ship it now.", "recommended": True}, {"label": "Wait", "line": "Wait a week.", "recommended": False}]
SAMPLE = {"after": ["a70"], "agent": BACK, "next": "home-front: a new step", "needs": [BACK], "ask": ASK, "options": OPTS, "work": {"text": "finished", "state": "done"},
          "check": "item_closed a70", "mover": BACK, "then": BACK, "post_wake_mover": BACK, "until": day(5), "wake": day(5), "ask_by": day(5), "due": day(5), "expected_by": day(5),
          "observers": [BACK], "tell_him": "home-front", "reword": {"1": "step one renamed"}, "waits": [{"after": "a70"}], "wait_mode": "any", "subject": "[home] renamed",
          "project": "projects/alpha", "priority": "high", "anchors": ["https://example.org/pull/7"], "wait_kind": "time", "wait_anchor": "https://example.org/pull/7", "wait_event": "merged",
          "wait_basis": f"the soak ends {day(5)}", "goal": "A new goal", "step": "pick it", "supplies": "the file", "draft": "a draft", "contact": "someone", "watch_reason": "x",
          "wait_reason": "the nightly run finishes at 03:00", "owner_name": "x", "expected_reason": "x", "owner": "home-front"}
def sample_of(p, prm):
    return SAMPLE.get(p, True if prm.default is False else 1 if (prm.default == 0 and prm.default is not False) else "x")
done_item(399, "done", "done")
out, fx = with_fixes(lambda: updt(399, status="completed"))
check("rule A: (control) the same close with nothing beside the list is closed by the default", rd(399)["status"] == "completed" and [k for k, _ in fx] == ["outcome-defaulted"], fx)
n_ = 400; leaked = []
for p, prm in sorted(inspect.signature(_wt_update.stackshot_update).parameters.items()):
    if p in ALLOW_:
        continue
    v = sample_of(p, prm); n_ += 1; done_item(n_, "done", "done"); was_ = raw(n_)
    try:
        updt(n_, status="completed", **{p: v}); e_ = ""
    except Exception as e:
        e_ = str(e)
    if raw(n_) != was_ or not e_ or "set by the server" in e_ or "Nothing is written and the item stays open" in e_:
        leaked.append((p, e_[:160]))
    if p in UNL_P and _update_svc.close_extra_args({p: v}) != [p]:
        leaked.append((p, "not read as outside the list"))
check(f"rule A: each of the {n_ - 400} update parameters outside the list, sent with a close with no outcome on an item whose every step is done, gets no default: refused as before, nothing written", not leaked and n_ - 400 >= 50, leaked)
for n_, (p, v) in enumerate((("after", ["a70"]), ("agent", BACK), ("mover", BACK), ("needs", [BACK]), ("clear_needs", True), ("observers", [BACK]), ("due", day(5)), ("wait_kind", "time"), ("subject", "[home] renamed")), 470):
    done_item(n_, "done", "done")
    plain_refusal(f"rule A: {p}= beside a close with no outcome" + (" (M1)" if p == "after" else " (M2: the old name of needs)" if p == "agent" else ""), n_, lambda: updt(n_, status="completed", **{p: v}))

# ================================================================ rule B: a question or call open for the owner switches every default off
from stackshot.model import needs as _needs_mod
oq = _needs_mod.owner_question_open
check("rule B: the predicate reads decision in needs, a stored ask, options he has not answered and a your-call, whoever the mover is",
      oq({"needs": ["decision"]}) and oq({"needs": ["decision", BACK]}) and oq({"ask": ASK, "needs": [BACK]}) and oq({"options": OPTS}) and oq({"state": "your-call", "needs": [BACK]})
      and oq({"options": OPTS, "answers": []}) and oq({"options": OPTS, "answers": ["not a record"]}), None)
check("rule B: ...and nothing else: options his answer settled, a blank ask, a session's need, nothing at all", not oq({"options": OPTS, "answers": [{"text": "ship it"}]}) and not oq({"ask": "  "}) and not oq({"needs": [BACK]}) and not oq({}) and not oq({"state": "doing"}), None)
done_item(300, "done", "done", needs=[BACK], mover=OWN, until=day(10), wait_kind="time", wait_basis=f"the vendor quote is due {day(10)}", ask=ASK, options=OPTS)
plain_refusal(f"rule B (H1): the parked call of {OWN} (needs a session, he is mover, a time wait with its basis, ask and options unanswered, steps done): a bare complete", 300, lambda: comp(300))
plain_refusal("rule B (H1): ...and a close through update", 300, lambda: updt(300, status="completed"))
done_item(301, "done", "done", needs=["decision"], ask=ASK, options=OPTS)
updt(301, needs=[BACK])
check("rule B (H1): (setup) a hand-off by needs alone keeps the ask and the options", mt(301).get("needs") == [BACK] and mt(301).get("ask") and mt(301).get("options"), mt(301))
plain_refusal("rule B (H1): a complete right after a hand-off by needs alone", 301, lambda: comp(301))
done_item(302, "done", "done", needs=[BACK], state="your-call")
plain_refusal("rule B (H1): a your-call item with needs a session", 302, lambda: comp(302))
done_item(308, "done", "done", needs=[BACK], options=OPTS)
plain_refusal("rule B: an item with options he has not answered and no ask", 308, lambda: comp(308))
done_item(303, "done", "done", needs=["decision"], ask=ASK, options=OPTS); was = raw(303)
refused("rule B (H2): a bare hold beside needs a session, on a decision item with its ask and options, is refused as before: no server day", lambda: updt(303, needs=[BACK], hold=True), "a park names what it waits for")
check("rule B (H2): ...nothing is stored: no day, no mark, the question stays his", raw(303) == was, mt(303))
plain_refusal("rule B (H2): ...and a complete right after it", 303, lambda: comp(303))
refused("rule B (H2): the same park with until 14 days out stays refused by the cap", lambda: updt(303, needs=[BACK], hold=True, until=day(14)), "a wait runs at most")
refused("rule B: ...and so with until=\"none\"", lambda: updt(303, needs=[BACK], hold=True, until="none"), "a park names what it waits for")
for n_, kw in ((305, dict(state="doing", ask=ASK)), (307, dict(state="doing", options=OPTS))):
    item(n_, needs=[BACK], **kw); was = raw(n_)
    refused(f"rule B: a bare hold on an item with {'an ask' if 'ask' in kw else 'options he has not answered'} is refused as before", lambda: updt(n_, hold=True), "a park names what it waits for")
    check(f"rule B ({n_}): ...nothing is stored", raw(n_) == was, mt(n_))
item(310, needs=[BACK], ask=ASK); was = raw(310)
refused("rule B: a wait after another item with no end, on an item with an ask, is refused for its end as before", lambda: updt(310, after=["a70"]), "has no end")
check("rule B (310): ...nothing is stored", raw(310) == was, mt(310))
item(312, needs=[BACK], ask=ASK, wait_kind="relay", wait_event="the vendor's reply", post_wake_mover=BACK); was = raw(312)
refused("rule B: a stored relay wait with no end, on an item with an ask, is refused for its end when another field is edited", lambda: updt(312, wait_event="the vendor replies"), "has no end")
check("rule B (312): ...nothing is stored", raw(312) == was, mt(312))
item(313, needs=["decision"], ask=ASK, options=OPTS)
refused("rule B: ask_by beside a hold on a decision item is not read as the park's date: refused as before", lambda: updt(313, hold=True, ask_by=day(3)), "needs holds decision together with a park")
for n_, kw, want in ((314, dict(stored=dict(ask=ASK), call={}), "wait_basis explains the wake"), (317, dict(stored={}, call=dict(ask=ASK)), "wait_basis explains the wake")):
    item(n_, needs=[BACK], state="doing", **kw["stored"]); was = raw(n_)
    refused(f"rule B: ask_by beside a hold with {'a stored ask' if kw['stored'] else 'an ask the call itself sends'} stays the ask's day, not the park's: refused as before", lambda: updt(n_, hold=True, ask_by=day(3), wait_basis=f"the soak collects its logs ends {day(3)}", **kw["call"]), want)
    check(f"rule B ({n_}): ...nothing is stored", raw(n_) == was, mt(n_))
item(316, needs=[BACK], ask=ASK, hold=True, wake=day(4)); was = raw(316)
refused("rule B: clear_wake on a hold stored the old way, on an item with an ask, does not end the park: judged as before", lambda: updt(316, clear_wake=True), "a park names what it waits for")
check("rule B (316): ...nothing is stored", raw(316) == was, mt(316))
for n_, kw, want in ((330, dict(after=["a70"]), "has no end"), (331, dict(hold=True), "a park names what it waits for")):
    item(n_, needs=["decision"], ask=ASK, **({"state": "doing"} if "hold" in kw else {})); was = raw(n_)
    refused(f"rule B: a hand-off that takes the ask back ({', '.join(kw)}) is judged by the item as it stood: no server day, refused as before", lambda: updt(n_, needs=[BACK], clear_ask=True, **kw), want)
    check(f"rule B ({n_}): ...nothing is stored", raw(n_) == was, mt(n_))
for n_, kw, want in ((334, dict(hold=True), "a park names what it waits for"), (335, dict(after=["a70"]), "has no end")):
    item(n_, needs=["decision"], **({"state": "doing"} if "hold" in kw else {})); was = raw(n_)
    refused(f"rule B: a hand-off by needs from a decision with no ask ({', '.join(kw)}) is judged by the item as it stood: no server day, refused as before", lambda: updt(n_, needs=[BACK], **kw), want)
    check(f"rule B ({n_}): ...nothing is stored", raw(n_) == was, mt(n_))
item(332, needs=[BACK], ask=ASK, state="doing"); was = raw(332)
refused("rule B: ...and so is a bare hold that takes the ask back", lambda: updt(332, clear_ask=True, hold=True), "a park names what it waits for")
check("rule B (332): ...nothing is stored", raw(332) == was, mt(332))
item(321, needs=[BACK], state="doing", ask=ASK, hold=True, until=day(9), until_server=day(9)); was = raw(321)
refused("rule B: hold=true sent again on a server-dated park that holds an ask is judged as a date given, as before", lambda: updt(321, hold=True), "with no reason")
check("rule B (321): ...nothing is stored", raw(321) == was, mt(321))
for label, m_ in (("decision and an ask", {"needs": ["decision"], "ask": ASK}), ("an ask", {"needs": [BACK], "ask": ASK}), ("a your-call", {"needs": [BACK], "state": "your-call"})):
    ti = {"status": "open", "subject": "[home] q", "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "home-front: wait", "after": ["a70"], **m_}}
    try:
        _gates_svc.gate_model(ti, None, "", creating=True)
    except Exception:
        pass
    check(f"rule B: a create with {label} and a wait with no end gets no server day", not any(k in ti["metadata"] for k in ("until", "ask_by", "until_server")), ti["metadata"])
m_now = {"owner": U["home-front"], "project": "projects/alpha", "next": "home-front: wait", "needs": [BACK], "after": ["a70"]}
check("rule B: the default end reads the item as it stood too: a question the write takes away still switches it off", _gates_svc._default_wait_end({"status": "open", "metadata": m_now}, "a99", False, True, {"needs": ["decision"], "ask": ASK}) == "" and "until_server" not in m_now
      and _gates_svc._default_wait_end({"status": "open", "metadata": dict(m_now)}, "a99", False, True, {"needs": [BACK]}) != "", m_now)

# ================================================================ M3: a blank or "none" date is no date of the caller's
item(320, needs=[BACK], subject="[home] hold, ask_by none", state="doing")
out, fx = with_fixes(lambda: updt(320, hold=True, ask_by="none"))
server_end_checks("M3: hold=true with ask_by=\"none\"", 320, fx, out)
out, fx = with_fixes(lambda: updt(320, hold=True, ask_by="none"))
check("M3: ...sent again it is accepted: the server's day and its mark stand, nothing told twice", mt(320).get("until") == EXP14 and mt(320).get("until_server") == EXP14 and "wait-end-defaulted" not in [k for k, _ in fx], (mt(320), fx))
for n_, kw in ((325, dict(ask_by=" ")), (326, dict(until="none")), (327, dict(wake="none")), (328, dict(until=" "))):
    item(n_, needs=[BACK], subject=f"[home] hold, {kw}", state="doing")
    out, fx = with_fixes(lambda: updt(n_, hold=True, **kw))
    check(f"M3: hold=true with {kw} is a bare hold: the server's day, marked and told", mt(n_).get("until") == EXP14 and mt(n_).get("until_server") == EXP14 and [k for k, _ in fx] == ["wait-end-defaulted"], (mt(n_), fx))
item(322, needs=[BACK], subject="[home] after-wait, ask_by none")
upd(322, after=["a70"])
updt(322, ask_by="none")
check("M3: ask_by=\"none\" on a server-dated wait after another item leaves the server's day and its mark", mt(322).get("until") == EXP14 and mt(322).get("until_server") == EXP14, mt(322))
item(329, needs=[BACK], subject="[home] after-wait, clear_after with ask_by none")
upd(329, after=["a70"])
out329 = updt(329, clear_after=True, ask_by="none")
check("M3: clear_after with ask_by=\"none\" ends the server-dated wait as clear_after alone does: the day and its mark go, and the reply says so",
      not any(k in mt(329) for k in ("until", "until_server", "wait_kind", "after")) and f"the backstop day {EXP14} the server had set for that wait went with it" in out329, (mt(329), out329[-400:]))
item(323, needs=[BACK], subject="[home] relay, no ask_by"); item(324, needs=[BACK], subject="[home] relay, ask_by none")
out_a, fx_a = with_fixes(lambda: updt(323, wait_kind="relay", wait_event="the vendor's reply", mover=BACK))
out_b, fx_b = with_fixes(lambda: updt(324, wait_kind="relay", wait_event="the vendor's reply", mover=BACK, ask_by="none"))
check("M3: a relay wait with ask_by=\"none\" is stored as the same call with none: the fallback day, marked as the server's, told the same", bool(_WT.stored_until(mt(323))) and _WT.stored_until(mt(324)) == _WT.stored_until(mt(323))
      and mt(324).get("until_server") == _WT.stored_until(mt(324)) == mt(323).get("until_server") and [k for k, _ in fx_b] == [k for k, _ in fx_a], (mt(323), mt(324), fx_a, fx_b))

# ================================================================ 3. two writers
def race(fa, fb):
    bar = threading.Barrier(2); res = [None, None]
    def run(n, f):
        bar.wait()
        try: res[n] = ("ok", f())
        except Exception as e: res[n] = ("err", str(e))
    ts = [threading.Thread(target=run, args=(n, f)) for n, f in enumerate((fa, fb))]
    [t.start() for t in ts]; [t.join(60) for t in ts]
    return res
seen = set()
for n in range(100, 112):      # a close with no outcome racing a step added to the same item
    done_item(n, "done", "done")
    r = race(lambda: comp(n), lambda: upd(n, next="home-front: one more step"))
    d = rd(n); sts = [s["status"] for s in d["metadata"].get("steps", [])]
    ok_closed = d["status"] == "completed" and "open" not in sts and d["metadata"].get("reason") == "closed with every step done (set by the server)"
    ok_open = d["status"] == "open" and "open" in sts
    seen.add("closed" if ok_closed else "open" if ok_open else "BAD")
    if not (ok_closed or ok_open): print("race close:", r, d["status"], sts)
check("race: a close with no outcome racing a step edit never closes over an open step (closed whole, or refused and open)", seen <= {"closed", "open"} and seen, seen)
seen = set()
for n in range(120, 132):      # a default end racing the same item's own end day
    item(n, needs=[BACK], subject=f"[home] racing wait {n}")
    r = race(lambda: upd(n, after=["a70"]), lambda: updt(n, after=["a70"], until=day(6)))
    m = mt(n); end = m.get("ask_by") or m.get("until") or m.get("wake")
    seen.add("given" if end == day(6) and "until_server" not in m else "default" if end == EXP14 and m.get("until_server") == EXP14 else "BAD")
    if "BAD" in seen: print("race wait:", r, m)
check("race: a wait racing an update that gives its end ends on one consistent day: the given one with no mark, or the default with its mark", seen <= {"given", "default"} and seen, seen)

# ================================================================ 4. the end of a server-dated wait takes the mark with the day (last: the pass below wakes every dated item in the store)
from stackshot.service import watching as _watching_svc
item(340, needs=[BACK], subject="[home] bare hold, to wake", state="doing")
updt(340, hold=True)
item(341, needs=[BACK], subject="[home] dated hold, to wake", state="doing")
updt(341, hold=True, until=day(3), wait_basis=f"the soak collects its logs ends {day(3)}")
item(344, needs=[BACK], subject="[home] the blocker it parks on")
item(343, needs=[BACK], subject="[home] park on a closing, server-dated", after=["a344"], until=EXP14, until_server=EXP14)
item(345, needs=[BACK], subject="[home] server-dated, no watcher can end it", wait_kind="anchor", until=EXP14, until_server=EXP14)
check("end: (setup) a345 is the old wake pass's, not a watcher's", not _watchers_mod.watches(rd(345)), mt(345))
check("end: (setup) the bare hold is on the server's day, the dated one on its own", mt(340).get("until_server") == EXP14 and mt(341).get("until") == day(3) and "until_server" not in mt(341), (mt(340), mt(341)))
_notify_was, _wtell_was = _wakes_svc.wake_notify, _watching_svc.watch_tell
_wakes_svc.wake_notify = lambda *a, **k: []
_watching_svc.watch_tell = lambda *a, **k: None
try:
    comp(344, outcome="done", reason="finished", outcome_text="- it is done")
    check("end: the release of a park on a closing item drops the server's day and its mark", not any(k in mt(343) for k in ("until", "until_server")), mt(343))
    _wakes_svc.wake_pass(_wakes_svc._pages.zone_now() + datetime.timedelta(days=16))
finally:
    _wakes_svc.wake_notify, _watching_svc.watch_tell = _notify_was, _wtell_was
KEYS_ = ("mover", "wait_kind", "hold", "hold_set", "until", "wake", "needs", "state", "after")
check("end: the wake of a bare hold takes the server's mark with its day", "until_server" not in mt(340) and "until" not in mt(340), mt(340))
check("end: ...and so does the old wake pass, for a dated wait no watcher can end", "until_server" not in mt(345) and "until" not in mt(345), mt(345))
check("end: ...and leaves the item as the wake of a hold with its own day leaves it (status, mover, kind, needs)", rd(340)["status"] == rd(341)["status"] and {k: mt(340).get(k) for k in KEYS_} == {k: mt(341).get(k) for k in KEYS_}, (rd(340)["status"], mt(340), rd(341)["status"], mt(341)))

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": close and wait defaults,{len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
