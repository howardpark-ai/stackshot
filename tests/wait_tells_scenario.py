"""Scenario test for the tells a wait gets and for how an item wait reads (stackshot/model/wait_tells.py, `_wait_tells` in stackshot/service/update.py, `model.words`) — a scratch store, fixture items, the tools
called in-process, no server socket, no network, no model call.

A wait is for what cannot be had now: an outside party, a vendor, a date, or a park the user asked for. Three changes keep it so:

  1  own read      a write that sets a wait on stackshot's own count, dry run or watch (the wait_basis, the wait_event or the wait reason says so: the dry-run count, the watch count, the sent-mail watch) gets one note on its
                   reply, saying to read or stage it now; the write is stored all the same; a reason that names an outside party (a vendor, an auditor, their site), the next or the status line alone, a soak window and a
                   bare "watch" or "count" get none; a write that sets no wait gets none
  2  front answer  a back session's write whose wait_basis or next waits on a front agent's answer ("waiting on <front>'s answer", "once <front> replies") gets one note saying the call is the writer's, or goes to the
                   user as options; a front agent only told something, an `after` on an item a front agent holds (a dependency on its work), a front agent's own write, a session no page lists as back, a retired front
                   agent and a wait that names no front agent get none; a failed roles read keeps the write stored
  3  after wait     the model line of an item that waits after another item names only that item: the backstop it also carries stays stored, and is not printed; a wait on a date alone still prints its date

    tests/run-suite wait_tells        -> exit 0 / 1"""
import contextlib, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="waittells-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK)

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml      # never the host's session store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml = _instance.set_person(toml)
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1                 # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^wait_alias_until = "[^"]*"', 'wait_alias_until = "2020-01-01"', toml); assert n == 1      # the window of the old wait parameters (wake, ask_by, hold) is shut for the whole suite: no write here may lean on one, so no date can end this suite
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                           # an isolated HOME
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state", "transcripts/-home-x"): (T / d).mkdir(parents=True)
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-owner", "home-stew", "marsh-builder", "quill-agent", "home-other", "marsh-second"), 1)}
(T / "store/anchors.json").write_text("{}"); (T / "store/next-id").write_text("900")
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/quill": {"title": "Quill", "name": "Quill", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                               "board": [], "board_open": 0, "agents": {"quill-agent": "the front", "marsh-builder": "the back", "marsh-second": "the second back"},
                                                                               "back_agents": {"marsh-builder": "the back", "marsh-second": "the second back"}}}}))
(T / "brain/projects/quill.md").write_text("---\ntitle: Quill\ndisplay-name: home-stew\nagents:\n  quill-agent: the front\n  background:\n    marsh-builder: the back\n    marsh-second: the second back\n---\n\n# Quill\n")
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()})); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1500]}" if got is not None else ""))

from fastmcp.exceptions import ToolError
from stackshot.model import model as _model
from stackshot.model import wait_tells as _wtell
from stackshot.anchors import anchors as _anc
from stackshot.web import server
from stackshot.service import audit_ticks as audit_ticks_svc, telling, update as _upd_svc
from stackshot.web import publish as _web_publish
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import update as _wt_update
from stackshot.web.ui import releasing as _rel
_rel._run = lambda argv: ""      # no release unit runs here, never the host's


@contextlib.contextmanager
def patched(owner, **kv):
    """Names of a module replaced for a case, put back after."""
    old = {k: getattr(owner, k) for k in kv}
    for k, v in kv.items(): setattr(owner, k, v)
    try: yield
    finally:
        for k, v in old.items(): setattr(owner, k, v)
def outcome(thunk):
    try: return ("ok", thunk())
    except ToolError as e: return ("refused", str(e))
    except Exception as e: return ("raised", f"{e.__class__.__name__}: {e}")

import datetime as dt
NOW = time.time()
BACK = "marsh-builder"; BACK2 = "marsh-second"; FRONT = "quill-agent"; OTHER = "home-other"; PROJECT = "projects/quill"
FUT = (dt.datetime.fromtimestamp(NOW, dt.timezone(dt.timedelta(hours=4))) + dt.timedelta(days=10)).strftime("%Y-%m-%d")      # past the 7-day cap of a wait: a wait_basis stands for it, and no hold (an old parameter) is needed
NEAR = (dt.datetime.fromtimestamp(NOW, dt.timezone(dt.timedelta(hours=4))) + dt.timedelta(days=3)).strftime("%Y-%m-%d")      # inside the 7-day cap of a wait: a date alone, no reason needed
def put(i, status="open", **meta):
    it = {"id": str(i), "gid": f"a{i}", "subject": f"[home] item {i}", "description": "- A thing", "status": status, "updated": NOW - 3600, "state_updated": NOW - 3600, "confirmed": NOW - 3600,
          "metadata": {"project": PROJECT, "next": f"{BACK}: do it", **meta}}
    (T / f"store/a/{i}.json").write_text(json.dumps(it), encoding="utf-8")
def read(i): return json.loads((T / f"store/a/{i}.json").read_text(encoding="utf-8"))
def update(i, **kw):
    kw.setdefault("sender", BACK)
    with patched(_web_publish, _publish=lambda *a, **k: None), patched(telling, tell_woken=lambda *a, **k: None), patched(audit_ticks_svc, _mover_subagents=lambda *a, **k: []):
        return outcome(lambda: _wt_update.stackshot_update(f"a{i}", **kw))
def update_raw(i, **kw):
    """The service entry itself (update_item), with the arguments the tool would not pass (a None where it passes a string)."""
    with patched(_web_publish, _publish=lambda *a, **k: None), patched(telling, tell_woken=lambda *a, **k: None), patched(audit_ticks_svc, _mover_subagents=lambda *a, **k: []):
        return outcome(lambda: _upd_svc.update_item(f"a{i}", **kw))
def reset():
    put(1, mover=BACK)
    put(2, mover=FRONT, next=f"{FRONT}: answer the question")        # an item a front agent holds
    put(3, mover=BACK2)                                                # an item another back agent holds
    put(4, status="completed", mover=FRONT, outcome="done")
reset()
OWN, FRONT_NOTE = _wtell.OWN_READ_NOTE, "a front agent. A call that is not Oliver's is yours to decide"
def has_own(got): return got[0] == "ok" and OWN in got[1]
def has_front(got): return got[0] == "ok" and FRONT_NOTE in got[1]
def waits(i): return bool(read(i)["metadata"].get("until") or read(i)["metadata"].get("hold"))

# ---------------------------------------------------------------- the words
OWN_YES = ("the dry-run count can be read 2099-01-01", "the watch count is read on 2099-01-01", "the sent-mail watch shows it", "the watch result is in", "a count the server keeps", "stackshot's own count is read on 2099-01-01")
OWN_NO = ("the vendor visits on a date", "error-log soak ends", "a 7-day watch of the logs", "recount", "the count of rows", "until the count shows", "the auditor publishes the vote count on 2099-01-01",
          "the translator returns the word count and the final count of strings on 2099-01-01", "the vendor's dry run at their site on 2099-01-01", "the dry-run count at the partner's, their site", "a customer dry run",
          "the bank's dry run", "Oliver's own count of receipts", "the web server's count of requests at the CDN", "The dry run passed; wait for the soak window to end", "a dry run is read",
          "the dry-run count was read; wait for the soak window to end", "the watch count is read before the deadline", "the dry-run count is read after the release date")
check("0 the matcher reads the dry-run or watch count, the sent-mail watch, the watch result, stackshot's own count and a count the server keeps", all(_wtell.own_read(t) for t in OWN_YES), [t for t in OWN_YES if not _wtell.own_read(t)])
check("0 …and not an outside party's count or dry run, a bare dry run, own or server's count, another blocker (a soak, a window, a deadline), a bare watch or count", not any(_wtell.own_read(t) for t in OWN_NO), [t for t in OWN_NO if _wtell.own_read(t)])
OUTSIDE_PROBES = {"vendor": "the vendor's dry-run count", "auditor": "the dry-run count the auditor reads", "partner": "the dry-run count at the partner's", "customer": "the customer's dry-run count",
                  "supplier": "the supplier's watch count", "translator": "the dry-run count the translator returns", "contractor": "the contractor's watch count", "their": "the dry-run count at their site",
                  "outside": "an outside dry-run count", "external": "the external dry-run count"}
for _w, _t in OUTSIDE_PROBES.items():
    check(f"0 the outside word '{_w}' alone silences a reason that reads as an own count: {_t}", not _wtell.own_read(_t) and _wtell.own_read(_t.replace(_w, "x")), (_t, _wtell.own_read(_t), _wtell.own_read(_t.replace(_w, "x"))))
check("0 …a reason is read on its own: an outside word in another reason does not silence it, one in the same reason does", _wtell.own_read("the vendor visits on a date", "the dry-run count can be read") and not _wtell.own_read("the dry-run count can be read, the vendor visits"), None)
FRONT_YES = ("waiting on quill-agent's answer on 2099-01-01", "continue once quill-agent replies", "waiting for quill-agent", "quill-agent's answer is due 2099-01-01",
             "asks quill-agent whether to ship", "wait until quill-agent decides", "Waiting on Quill-Agent's decision", "expecting quill-agent's answer", "waiting for the answer from quill-agent",
             "need quill-agent's answer by 2099-01-01", "waiting on quill-agent to decide", "waiting on quill-agent for the go-ahead", "pending quill-agent's reply")
FRONT_NO = ("once built, tell quill-agent what the vendor says", "build the parser", "waiting on old-quill-agent's answer", "wait for quill-agent-two's answer", "waiting on the vendor's answer", "quill-agent wrote the page",
            "quill-agent reviews the page on 2099-01-01", "waiting on quill-agent to be told", "waiting on quill-agent to be told the answer", "waiting on quill-agent to finish the build", "tell quill-agent the answer is due", "x-quill-agent's answer is due on a date",
            "waiting on quill-agent to merge the PR that adds the decision page", "waiting on quill-agent to ship the reply-handling feature", "waiting on quill-agent for the word count script",
            "waiting on quill-agent to finish the build and confirm the artifacts", "Ask quill-agent for the build artifacts", "Quill-agent's answer is already in; wait for the soak to end",
            "after quill-agent confirmed the schema last week, continue", "asked quill-agent for the go-ahead yesterday; got it", "no need for quill-agent's answer", "waited on quill-agent's answer yesterday")
check("0 a front agent is named when it is waited on, asked or waited for to answer or decide", all(_wtell.front_named([t], [FRONT]) == FRONT for t in FRONT_YES), [t for t in FRONT_YES if _wtell.front_named([t], [FRONT]) != FRONT])
check("0 …and not when it is only told, named with no wait, a longer name, an outside party's answer, its real work, an answer in another clause or a past tense", not any(_wtell.front_named([t], [FRONT]) for t in FRONT_NO), [t for t in FRONT_NO if _wtell.front_named([t], [FRONT])])
check("0 …and a name that is no front agent (a back agent) is never returned", not _wtell.front_named(["waiting on marsh-builder's answer"], [FRONT]) and not _wtell.front_named(["waiting on quill-agent's answer"], []), None)

LONG = "a" * 5000
LONG_LINES = [f"waiting on {LONG}", f"waiting for {LONG}'s answer", f"{LONG}'s answer is waiting", f"ask {LONG} for", f"until {LONG} decides", f"{LONG}'s {LONG}'s answer waiting", f"waiting {LONG}-{LONG} the answer from {LONG}"] * 6
_t0 = time.time(); _got = _wtell.front_named(LONG_LINES, [FRONT]); _took = time.time() - _t0
check("0 a line of one 5,000-character token (forty-two of them) is read in linear time: it names nobody and returns fast", _got == "" and _took < 2.0, (_got, round(_took, 2)))
check("0 …and so does a line of that token in a name that is a front agent's longer name", _wtell.front_named([f"waiting on {FRONT}-{LONG}'s answer"], [FRONT]) == "", None)

_calls = []
def _counting_roles():
    _calls.append(1); return _anc_real_roles()
_anc_real_roles = _anc.session_roles
with patched(_anc, session_roles=_counting_roles):
    quiet = _upd_svc._wait_tells(BACK, ["the vendor ships the part"], [f"{BACK}: build the parser"], True)
    n_quiet = len(_calls)
    loud = _upd_svc._wait_tells(BACK, [f"waiting on {FRONT}'s answer"], [""], True)
    n_loud = len(_calls)
    own_only = _upd_svc._wait_tells(BACK, ["the dry-run count can be read"], [""], True)
    n_own = len(_calls)
check("7 the roles are not read when no text could name a front agent and none reads as an own count", quiet == "" and n_quiet == 0, (quiet, n_quiet))
check("7 …they are read when a text waits on someone, and when a reason reads as an own count (the writer's role gates that note)", FRONT_NOTE in loud and n_loud == 1 and OWN in own_only and n_own == 2, (n_loud, n_own))

# ---------------------------------------------------------------- 1. own read
got = update(1, until=FUT, wait_kind="time", wait_basis=f"the dry-run count can be read {FUT}")
check("1 a park whose wait_basis says the dry-run count can be read gets the note, and is stored", has_own(got) and waits(1), (got, read(1)["metadata"]))
check("1 …the note is one line that says to read or stage it now and to park only for an outside party, a vendor or a date", got[1].count(OWN) == 1 and "read or stage that now" in got[1] and "a vendor or a date" in got[1], got)
reset()
got = update(1, until=FUT, wait_kind="time", wait_basis=f"the watch count is read on {FUT}")
check("1 a wait_basis that says the watch count is read gets the note", has_own(got) and waits(1), got)
reset()
got = update(1, sender=OTHER, until=FUT, wait_kind="time", wait_basis=f"the dry-run count can be read {FUT}")
check("1 a session no page lists as back gets no own-read note (it is for back and builder sessions), and the write is stored", got[0] == "ok" and OWN not in got[1] and waits(1), got)
reset()
put(2, mover=FRONT, next=f"{FRONT}: answer the question")
got = update(2, sender=FRONT, until=FUT, wait_kind="time", wait_basis=f"the dry-run count can be read {FUT}")
check("1 a front agent's own write gets no own-read note either, and the write is stored", got[0] == "ok" and OWN not in got[1] and waits(2), got)
reset()
got = update(3, sender=BACK2, until=FUT, wait_kind="time", wait_basis=f"the dry-run count can be read {FUT}")
check("1 another back session gets the own-read note (the role is back, whichever item it moves)", has_own(got), got)
reset()
_old_wake, _old_hold = update(1, wake=FUT), update(1, until=FUT, hold=True, wait_basis="x")
check("1 the old wait parameters are refused in this suite (the alias window is shut), so no write here leans on one", _old_wake[0] == "refused" and "not a parameter any more" in _old_wake[1] and _old_hold[0] == "refused" and "not a parameter any more" in _old_hold[1], (_old_wake, _old_hold))
reset()
PROBES = ((f"the vendor visits on {FUT}", f"{BACK}: compare the count of rows"), (f"the auditor publishes the vote count on {FUT}", None),
          (f"the translator returns the word count and the final count of strings on {FUT}", None), (f"the vendor's dry run at their site on {FUT}", None),
          (f"the vendor ships the part on {FUT}", f"{BACK}: dry run passed on Tuesday; wait for the vendor"), (f"the vendor signs off on {FUT}", f"{BACK}: after the vendor signs off, re-run the dry run"),
          (f"the dry-run count can be read {FUT}, once the vendor is done", None))
for basis, nxt in PROBES:
    got = update(1, until=FUT, wait_kind="time", wait_basis=basis, **({"next": nxt} if nxt else {}))
    check(f"1 an outside party's wait gets no note: {basis[:56]} / {nxt}", got[0] == "ok" and OWN not in got[1] and waits(1), got)
    reset()
got = update(1, until=FUT, wait_kind="time", wait_basis=f"the error-log soak ends {FUT}")
check("1 a soak window the work itself needs gets no note", got[0] == "ok" and OWN not in got[1], got)
reset()
got = update(1, until=FUT, wait_kind="time", wait_basis=f"the soak window ends {FUT}", next=f"{BACK}: read the dry run output once the date comes")
check("1 a next that says to read the dry run, with a soak reason, gets no note (the next is no reason)", got[0] == "ok" and OWN not in got[1] and waits(1), got)
reset()
got = update(1, until=FUT, wait_kind="time", wait_basis=f"the soak window ends {FUT}", work={"text": "waiting for the dry-run count", "state": "in progress"})
check("1 a status line that says the dry-run count gets no note (the status line is no reason)", got[0] == "ok" and OWN not in got[1], got)
reset()
got = update(1, next=f"{BACK}: read the dry run output")
check("1 the same next with no wait set gets no note", got[0] == "ok" and OWN not in got[1] and not waits(1), got)
reset()
got = update(1, wait_kind="relay", wait_event="the dry-run count can be read", until=NEAR)
check("1 a wait_event that says the dry-run count can be read gets the note", has_own(got), got)
reset()
put(1, mover=BACK, until=FUT, hold=True, wait_basis={"text": f"the dry-run count can be read {FUT}", "wake": FUT, "by": BACK, "at": 1})
got = update(1, next=f"{BACK}: still on it")
check("1 a write that sets no wait (the stored basis is not this write's) gets no note", got[0] == "ok" and OWN not in got[1], got)
reset()

# ---------------------------------------------------------------- 2. front answer
got = update(1, until=FUT, wait_kind="time", wait_basis=f"waiting on {FRONT}'s answer, due {FUT}")
check("2 a wait_basis that names a front agent's answer gets the note naming the agent, and is stored", has_front(got) and FRONT in got[1] and waits(1), (got, read(1)["metadata"]))
check("2 …the note says to decide it or put it to Oliver as a decision with options, and that the answer is no wait", got[1].count(FRONT_NOTE) == 1 and "as a decision with options and your recommendation" in got[1] and "is no wait" in got[1], got)
reset()
got = update(1, until=FUT, wait_kind="time", next=f"{BACK}: waiting on {FRONT}'s answer on {FUT}", wait_basis=f"the soak window ends {FUT}")
check("2 a next that waits on a front agent's answer gets the note", has_front(got), got)
reset()
got = update(1, until=FUT, wait_kind="time", next=f"{BACK}: continue once {FRONT} replies", wait_basis=f"the soak window ends {FUT}")
check("2 a next that waits until a front agent replies gets the note", has_front(got), got)
reset()
put(1, mover=BACK, until=FUT)
got = update(1, after=["a3"], next=f"{BACK}: continue once {FRONT} replies")
check("2 a write whose only wait is an after link still gets the note when its next waits on the front agent", has_front(got) and read(1)["metadata"].get("after"), (got, read(1)["metadata"]))
reset()
got = update(1, after=["a2"], until=NEAR)
check("2 an after on an item a front agent holds is a dependency on its work: no note, stored", got[0] == "ok" and FRONT_NOTE not in got[1] and read(1)["metadata"].get("after"), got)
reset()
put(2, mover=FRONT, next=f"{FRONT}: build the parser")
got = update(1, after=["a2"], until=NEAR, next=f"{BACK}: continue after the parser is built")
check("2 …also when the front agent's own next is work", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
got = update(1, until=FUT, wait_kind="time", next=f"{BACK}: once built, tell {FRONT} what the vendor says", wait_basis=f"the vendor ships the part on {FUT}")
check("2 a front agent only told what an outside party says gets no note", got[0] == "ok" and FRONT_NOTE not in got[1] and waits(1), got)
reset()
got = update(1, until=FUT, wait_kind="time", wait_basis=f"waiting on x-{FRONT}'s answer on {FUT}")
check("2 a longer name that ends in a front agent's name gets no note", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
got = update(1, until=FUT, wait_kind="time", wait_basis=f"{FRONT} reviews the page on {FUT}")
check("2 a front agent named with no waiting or answer word gets no note", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
got = update(1, until=FUT, wait_kind="time", wait_basis=f"the vendor's answer is due {FUT}")
check("2 a wait on an outside answer gets no note", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
got = update(1, until=FUT, wait_kind="time", wait_basis=f"waiting on {BACK2}'s answer on {FUT}")
check("2 a wait on another back agent's answer gets no note", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
put(2, mover=FRONT, next=f"{FRONT}: answer the question")
got = update(2, sender=FRONT, until=FUT, wait_kind="time", wait_basis=f"waiting on {FRONT}'s answer, due {FUT}")
check("2 a front agent's own write gets no note", FRONT_NOTE not in got[1], got)
reset()
put(1, mover=OTHER, next=f"{OTHER}: do it")
got = update(1, sender=OTHER, until=FUT, wait_kind="time", wait_basis=f"waiting on {FRONT}'s answer, due {FUT}")
check("2 a session no page lists as back gets no note", FRONT_NOTE not in got[1], got)
reset()
put(5, mover=BACK, next=f"{BACK}: waiting on {FRONT}'s answer")
got = update(5, next=f"{BACK}: carry on")
check("2 a write that sets no wait gets no note", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
got = update(1, mover=BACK2, until=NEAR, next=f"{BACK2}: ask {FRONT} whether to ship the page")
check("2 a hand-over that carries a date (its backstop, no wait) gets no front note, and the date is kept as the backstop, no wait", got[0] == "ok" and FRONT_NOTE not in got[1] and not read(1)["metadata"].get("until") and NEAR in json.dumps(read(1)["metadata"]), (got, read(1)["metadata"]))
reset()
got = update(1, next=f"{BACK}: ask {FRONT} whether to ship the page")
check("2 a write whose next asks a front agent and that sets no wait gets no note", got[0] == "ok" and FRONT_NOTE not in got[1] and not waits(1), (got, read(1)["metadata"]))
reset()
got = update(1, hold=True, recycle=True, next=f"{BACK}: ask {FRONT} whether to ship the page")
check("2 a hold alone (a park on a pane recycle: no date, no kind, no reason of its own) counts as setting a wait: the front agent asked in the next is told", has_front(got) and waits(1), (got, read(1)["metadata"]))
reset()
got = update(1, until=FUT, wait_kind="time", wait_basis=f"the dry-run count can be read {FUT}", next=f"{BACK}: ask {FRONT} whether to ship the page")
check("2 a write that reads as both gets both notes: the front note does not replace the own-read note", has_own(got) and has_front(got) and got[1].count("(note:") == 2, got)
reset()
got = update(4, wait_kind="time", wait_basis=f"waiting on {FRONT}'s answer, due {FUT}")
check("2 a closed item is not told", FRONT_NOTE not in got[1] and read(4)["status"] != "open", (got, read(4)["status"]))
reset()
put(1, mover=BACK, until=NEAR, wait_kind="time", wait_basis={"text": f"waiting on {FRONT}'s answer", "wake": NEAR, "by": BACK, "at": 1})
got = update(1, status="completed", outcome="done", reason="done", outcome_text="- done")
check("2 …and the write that closes an item that waited on a front agent's answer is not told either", got[0] == "ok" and FRONT_NOTE not in got[1] and OWN not in got[1] and read(1)["status"] == "completed", (got, read(1)["status"]))
reset()
got = update_raw(1, sender=BACK, next=f"{BACK}: carry on", wait_basis=None)
check("7 a wait_basis that is no string (None) on a write with no wait is read as empty: the write is stored, never raised", got[0] == "ok" and "carry on" in json.dumps(read(1)["metadata"]), got)
reset()
real = _anc.session_roles()
check("2 (the fixture) the roles list the front agent as front and the back agent as back", real.get(FRONT, {}).get("role") == "front" and real.get(BACK, {}).get("role") == "back", {k: real.get(k) for k in (FRONT, BACK)})
with patched(_anc, session_roles=lambda: {**real, FRONT: {**real[FRONT], "retired": True}}):
    got = update(1, until=FUT, wait_kind="time", wait_basis=f"waiting on {FRONT}'s answer, due {FUT}")
check("2 a retired front agent is not one to wait on: no note, stored", got[0] == "ok" and FRONT_NOTE not in got[1] and waits(1), got)
reset()
def _boom(): raise RuntimeError("roles unreadable")
with patched(_anc, session_roles=_boom):
    got = update(1, until=FUT, wait_kind="time", wait_basis=f"waiting on {FRONT}'s answer, due {FUT}")
    got2 = update(1, until=FUT, wait_kind="time", wait_basis=f"the dry-run count can be read {FUT}")
check("2 a failed roles read keeps the write stored, with no front note", got[0] == "ok" and FRONT_NOTE not in got[1] and waits(1), got)
check("2 …and the own-read note, which needs no roles, still comes", has_own(got2), got2)
reset()

# ---------------------------------------------------------------- 3. an after wait shows only the item
BACKSTOP = "2099-03-09"
now = NOW
def mod_of(**meta):
    it = {"status": "open", "gid": "a9", "subject": "x", "metadata": {"project": PROJECT, "mover": BACK, "needs": [BACK], **meta}}
    return _model.derive(it, now, after_open=lambda i: ["a8"])
line = _model.words(mod_of(wait_kind="item", after=["a8"], until=BACKSTOP, mover=BACK), derived=False, shown=lambda g: "item-" + g[1:])
check("3 words: an after wait with a backstop prints only the item it waits on", line == f"model: waiting on the close of item-8 · mover {BACK}", line)
check("3 words: a wait on a date alone still prints its date", BACKSTOP in _model.words(mod_of(hold=True, until=BACKSTOP, wait_kind="time", mover=BACK), derived=False), _model.words(mod_of(hold=True, until=BACKSTOP, wait_kind="time", mover=BACK), derived=False))
check("3 words: an anchor wait keeps its backstop", BACKSTOP in _model.words(mod_of(wait_kind="anchor", wait_anchor="https://example.org/pull/1", wait_event="PR merged", until=BACKSTOP, mover=BACK), derived=False),
      _model.words(mod_of(wait_kind="anchor", wait_anchor="https://example.org/pull/1", wait_event="PR merged", until=BACKSTOP, mover=BACK), derived=False))
empty = _model.words(mod_of(wait_kind="item", after=[], until=BACKSTOP, mover=BACK), derived=False)
check("3 words: an item wait with no item stored keeps the old date line, never a bare close of no item", BACKSTOP in empty, empty)
got = update(1, after=["a3"], until=NEAR)
shown = _wt_get.stackshot_get("a1")
mline = next((ln for ln in shown.splitlines() if ln.startswith("model:")), "")
check("3 through the tool: a stored after with a backstop is told by get as the close of the item alone", mline.startswith("model: waiting on the close of ") and NEAR not in mline and "until" not in mline, (got, mline))
check("3 …and the backstop is still stored and in force", NEAR in json.dumps(read(1)["metadata"]) and bool(read(1)["metadata"].get("after")), read(1)["metadata"])

print(f"wait_tells scenario: {len(ran) - len(fails)}/{len(ran)} checks")
_scratch.cleanup()
if fails:
    print("FAILED:", *fails, sep="\n  "); sys.exit(1)
print(f"ok: wait_tells scenario, {len(ran)} checks")
