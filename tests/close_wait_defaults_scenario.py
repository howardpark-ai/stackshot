"""Scenario test for two defaults a call may leave out (fixture data, no live store, no network, no server socket): a close with no outcome on an item whose every step is done or dropped
is closed as done with the server's words, marked as the server's, unless the call sends new work, a need, an ask or a check with it, or the item still waits on an ask to the owner or a done
check; a wait with nothing that can wake it (on an item, anchor, relay or event with no end, or a time wait, park or hold with no date) gets the default backstop day, marked as the server's
and shown so in the agent reads; an open step, no steps at all, a date in the past and a day the caller gives past the cap or with no reason stay refused, whichever old name carries it;
an anchor's notice still releases what it released before; two writers racing on the same item end in one consistent state.

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
check("wait: for an item wait the default is the latest expected-by of the open items it waits after plus two days", (mt(73).get("ask_by") or mt(73).get("until")) == day(5) and mt(73).get("until_server") == day(5), mt(73))

updt(73, until=day(5))
check("wait: sending the very day the server stored makes it the caller's own: the mark goes", "until_server" not in mt(73) and (mt(73).get("ask_by") or mt(73).get("until")) == day(5), mt(73))

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
done_item(90, "done", "open")
out, fx = with_fixes(lambda: _update_svc._update("a90", sender="home-front", status="completed", work={"text": "finished", "state": "done"}))
check("close: the step a status done ticks in the same call counts as marked", rd(90)["status"] == "completed" and rd(90)["metadata"].get("outcome") == "done" and [k for k, _ in fx] == ["outcome-defaulted"], (rd(90)["status"], fx, out))
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

# ---- a close that would throw away what the same call sends, or an ask or a check still open, is not defaulted: the refusal names what is in the way, and nothing is written
def unchanged(label, i, was_):
    check(f"{label}: ...nothing is written: the item stays open with its steps as they were", raw(i) == was_ and rd(i)["status"] == "open", rd(i)["metadata"])
done_item(150, "done", "done"); was = raw(150)
refused("close+work: new work in next beside a close with no outcome is refused, naming it", lambda: upd(150, status="completed", next="home-front: a new step"),
        "Nothing is written and the item stays open", "this call adds work in next (\"home-front: a new step\"), which would be left open", "or send the new work in an update of its own")
unchanged("close+work", 150, was)
done_item(151, "done", "done"); was = raw(151)
refused("close+need: a new need and an ask beside the close are refused, each named", lambda: upd(151, status="completed", needs=["decision"], ask=ASK), "this call sets needs", "this call sets an ask")
unchanged("close+need", 151, was)
done_item(152, "done", "done"); was = raw(152)
refused("close+status: a work status that is not done is refused, naming it", lambda: upd(152, status="completed", work={"text": "building it", "state": "in progress"}), "a step status that is not done (work: in progress)")
unchanged("close+status", 152, was)
done_item(153, "done", "open"); was = raw(153)
refused("close+mark+work: marking the last step done does not let new work through", lambda: upd(153, status="completed", done=[2], next="home-front: another"), "this call adds work in next")
unchanged("close+mark+work", 153, was)
done_item(156, "done", "open"); was = raw(156)
refused("close+work+open step: the refusal names the new work and the open step together", lambda: upd(156, status="completed", next="home-front: brand new"), "this call adds work in next", "step 2 is still open")
unchanged("close+work+open step", 156, was)
done_item(154, "done", "done", needs=["decision"], ask=ASK); was = raw(154)
try:
    comp(154); e154 = ""
except Exception as e:
    e154 = str(e)
check(f"close+open ask: an item that still waits on {OWN}'s answer is not closed by default; complete's refusal names the ask and only what complete takes", f"the item still waits on {OWN}'s answer to its ask" in e154 and "Pass outcome, reason, outcome_text yourself" in e154 and "send the new work" not in e154, e154)
unchanged("close+open ask", 154, was)
done_item(155, "done", "done", check="item_closed a70"); was = raw(155)
refused("close+check: a done check that has not passed is not closed over by default", lambda: comp(155), "the item's done check (item_closed a70) has not passed")
unchanged("close+check", 155, was)
done_item(157, "done", "done"); was = raw(157)
refused("close+check given: a done check sent with the close is not closed over either", lambda: upd(157, status="completed", check="item_closed a70"), "this call sets a done check")
unchanged("close+check given", 157, was)

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

# ---- a day the server takes from an awaited item's expected-by far out says how far and why
item(175, needs=[BACK], subject="[home] blocker expected far out", state="doing", expected_by=day(40))
item(176, needs=[BACK], subject="[home] waits after the far one")
out, fx = with_fixes(lambda: upd(176, after=["a175"]))
check("far: the day is the awaited item's expected-by plus two days, and the reply says how far out and why", mt(176).get("until") == day(42) and any("that is 42 days out, later than the usual 14, because the item it waits after is expected then" in t for _, t in fx), (mt(176), fx))

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

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": close and wait defaults,{len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
