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
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1                 # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
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
from stackshot.service import audit_ticks as audit_ticks_svc, telling
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
FUT = (dt.datetime.fromtimestamp(NOW, dt.timezone(dt.timedelta(hours=4))) + dt.timedelta(days=3)).strftime("%Y-%m-%d")
def put(i, status="open", **meta):
    it = {"id": str(i), "gid": f"a{i}", "subject": f"[home] item {i}", "description": "- A thing", "status": status, "updated": NOW - 3600, "state_updated": NOW - 3600, "confirmed": NOW - 3600,
          "metadata": {"project": PROJECT, "next": f"{BACK}: do it", **meta}}
    (T / f"store/a/{i}.json").write_text(json.dumps(it), encoding="utf-8")
def read(i): return json.loads((T / f"store/a/{i}.json").read_text(encoding="utf-8"))
def update(i, **kw):
    kw.setdefault("sender", BACK)
    with patched(_web_publish, _publish=lambda *a, **k: None), patched(telling, tell_woken=lambda *a, **k: None), patched(audit_ticks_svc, _mover_subagents=lambda *a, **k: []):
        return outcome(lambda: _wt_update.stackshot_update(f"a{i}", **kw))
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
OWN_YES = ("the dry-run count can be read 2099-01-01", "the watch count is read on 2099-01-01", "a dry run is read", "the sent-mail watch shows it", "the watch result is in", "a count the server keeps")
OWN_NO = ("the vendor visits on a date", "error-log soak ends", "a 7-day watch of the logs", "recount", "the count of rows", "until the count shows", "the auditor publishes the vote count on 2099-01-01",
          "the translator returns the word count and the final count of strings on 2099-01-01", "the vendor's dry run at their site on 2099-01-01", "the dry-run count at the partner's, their site", "a customer dry run")
check("0 the matcher reads a dry run, the dry-run or watch count, the sent-mail watch and a count the server keeps", all(_wtell.own_read(t) for t in OWN_YES), [t for t in OWN_YES if not _wtell.own_read(t)])
check("0 …and not an outside party's count or dry run, a soak window, a bare watch or count", not any(_wtell.own_read(t) for t in OWN_NO), [t for t in OWN_NO if _wtell.own_read(t)])
check("0 …a reason is read on its own: an outside word in another reason does not silence it, one in the same reason does", _wtell.own_read("the vendor visits on a date", "the dry-run count can be read") and not _wtell.own_read("the dry-run count can be read, the vendor visits"), None)
FRONT_YES = ("waiting on quill-agent's answer on 2099-01-01", "continue once quill-agent replies", "waiting for quill-agent", "quill-agent's answer is due 2099-01-01",
             "asks quill-agent whether to ship", "wait until quill-agent decides", "Waiting on Quill-Agent's decision")
FRONT_NO = ("once built, tell quill-agent what the vendor says", "build the parser", "waiting on old-quill-agent's answer", "wait for quill-agent-two's answer", "waiting on the vendor's answer", "quill-agent wrote the page",
            "quill-agent reviews the page on 2099-01-01", "waiting on quill-agent to be told", "waiting on quill-agent to be told the answer", "waiting on quill-agent to finish the build", "tell quill-agent the answer is due", "x-quill-agent's answer is due on a date")
check("0 a front agent is named when it is waited on, asked or waited for to answer or decide", all(_wtell.front_named([t], [FRONT]) == FRONT for t in FRONT_YES), [t for t in FRONT_YES if _wtell.front_named([t], [FRONT]) != FRONT])
check("0 …and not when it is only told, named with no wait, a longer name, an outside party's answer or its real work", not any(_wtell.front_named([t], [FRONT]) for t in FRONT_NO), [t for t in FRONT_NO if _wtell.front_named([t], [FRONT])])
check("0 …and a name that is no front agent (a back agent) is never returned", not _wtell.front_named(["waiting on marsh-builder's answer"], [FRONT]) and not _wtell.front_named(["waiting on quill-agent's answer"], []), None)

# ---------------------------------------------------------------- 1. own read
got = update(1, hold=True, until=FUT, wait_basis=f"the dry-run count can be read {FUT}")
check("1 a park whose wait_basis says the dry-run count can be read gets the note, and is stored", has_own(got) and waits(1), (got, read(1)["metadata"]))
check("1 …the note is one line that says to read or stage it now and to park only for an outside party, a vendor or a date", got[1].count(OWN) == 1 and "read or stage that now" in got[1] and "a vendor or a date" in got[1], got)
reset()
got = update(1, hold=True, until=FUT, wait_basis=f"the watch count is read on {FUT}")
check("1 a wait_basis that says the watch count is read gets the note", has_own(got) and waits(1), got)
reset()
got = update(1, sender=OTHER, hold=True, until=FUT, wait_basis=f"the dry-run count can be read {FUT}")
check("1 a session no page lists as back gets the note too (the own-read tell is for every writer)", has_own(got), got)
reset()
PROBES = ((f"the vendor visits on {FUT}", f"{BACK}: compare the count of rows"), (f"the auditor publishes the vote count on {FUT}", None),
          (f"the translator returns the word count and the final count of strings on {FUT}", None), (f"the vendor's dry run at their site on {FUT}", None),
          (f"the vendor ships the part on {FUT}", f"{BACK}: dry run passed on Tuesday; wait for the vendor"), (f"the vendor signs off on {FUT}", f"{BACK}: after the vendor signs off, re-run the dry run"),
          (f"the dry-run count can be read {FUT}, once the vendor is done", None))
for basis, nxt in PROBES:
    got = update(1, hold=True, until=FUT, wait_basis=basis, **({"next": nxt} if nxt else {}))
    check(f"1 an outside party's wait gets no note: {basis[:56]} / {nxt}", got[0] == "ok" and OWN not in got[1] and waits(1), got)
    reset()
got = update(1, hold=True, until=FUT, wait_basis=f"the error-log soak ends {FUT}")
check("1 a soak window the work itself needs gets no note", got[0] == "ok" and OWN not in got[1], got)
reset()
got = update(1, hold=True, until=FUT, wait_basis=f"the soak window ends {FUT}", next=f"{BACK}: read the dry run output once the date comes")
check("1 a next that says to read the dry run, with a soak reason, gets no note (the next is no reason)", got[0] == "ok" and OWN not in got[1] and waits(1), got)
reset()
got = update(1, hold=True, until=FUT, wait_basis=f"the soak window ends {FUT}", work={"text": "waiting for the dry-run count", "state": "in progress"})
check("1 a status line that says the dry-run count gets no note (the status line is no reason)", got[0] == "ok" and OWN not in got[1], got)
reset()
got = update(1, next=f"{BACK}: read the dry run output")
check("1 the same next with no wait set gets no note", got[0] == "ok" and OWN not in got[1] and not waits(1), got)
reset()
got = update(1, wait_kind="relay", wait_event="the dry-run count can be read", ask_by=FUT)
check("1 a wait_event that says the dry-run count can be read gets the note", has_own(got), got)
reset()
put(1, mover=BACK, until=FUT, hold=True, wait_basis={"text": f"the dry-run count can be read {FUT}", "wake": FUT, "by": BACK, "at": 1})
got = update(1, next=f"{BACK}: still on it")
check("1 a write that sets no wait (the stored basis is not this write's) gets no note", got[0] == "ok" and OWN not in got[1], got)
reset()

# ---------------------------------------------------------------- 2. front answer
got = update(1, hold=True, until=FUT, wait_basis=f"waiting on {FRONT}'s answer, due {FUT}")
check("2 a wait_basis that names a front agent's answer gets the note naming the agent, and is stored", has_front(got) and FRONT in got[1] and waits(1), (got, read(1)["metadata"]))
check("2 …the note says to decide it or put it to Oliver as a decision with options, and that the answer is no wait", got[1].count(FRONT_NOTE) == 1 and "as a decision with options and your recommendation" in got[1] and "is no wait" in got[1], got)
reset()
got = update(1, hold=True, until=FUT, next=f"{BACK}: waiting on {FRONT}'s answer on {FUT}", wait_basis=f"the soak window ends {FUT}")
check("2 a next that waits on a front agent's answer gets the note", has_front(got), got)
reset()
got = update(1, hold=True, until=FUT, next=f"{BACK}: continue once {FRONT} replies", wait_basis=f"the soak window ends {FUT}")
check("2 a next that waits until a front agent replies gets the note", has_front(got), got)
reset()
put(1, mover=BACK, until=FUT)
got = update(1, after=["a3"], next=f"{BACK}: continue once {FRONT} replies")
check("2 a write whose only wait is an after link still gets the note when its next waits on the front agent", has_front(got) and read(1)["metadata"].get("after"), (got, read(1)["metadata"]))
reset()
got = update(1, after=["a2"], until=FUT)
check("2 an after on an item a front agent holds is a dependency on its work: no note, stored", got[0] == "ok" and FRONT_NOTE not in got[1] and read(1)["metadata"].get("after"), got)
reset()
put(2, mover=FRONT, next=f"{FRONT}: build the parser")
got = update(1, after=["a2"], until=FUT, next=f"{BACK}: continue after the parser is built")
check("2 …also when the front agent's own next is work", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
got = update(1, hold=True, until=FUT, next=f"{BACK}: once built, tell {FRONT} what the vendor says", wait_basis=f"the vendor ships the part on {FUT}")
check("2 a front agent only told what an outside party says gets no note", got[0] == "ok" and FRONT_NOTE not in got[1] and waits(1), got)
reset()
got = update(1, hold=True, until=FUT, wait_basis=f"waiting on x-{FRONT}'s answer on {FUT}")
check("2 a longer name that ends in a front agent's name gets no note", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
got = update(1, hold=True, until=FUT, wait_basis=f"{FRONT} reviews the page on {FUT}")
check("2 a front agent named with no waiting or answer word gets no note", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
got = update(1, hold=True, until=FUT, wait_basis=f"the vendor's answer is due {FUT}")
check("2 a wait on an outside answer gets no note", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
got = update(1, hold=True, until=FUT, wait_basis=f"waiting on {BACK2}'s answer on {FUT}")
check("2 a wait on another back agent's answer gets no note", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
put(2, mover=FRONT, next=f"{FRONT}: answer the question")
got = update(2, sender=FRONT, hold=True, until=FUT, wait_basis=f"waiting on {FRONT}'s answer, due {FUT}")
check("2 a front agent's own write gets no note", FRONT_NOTE not in got[1], got)
reset()
put(1, mover=OTHER, next=f"{OTHER}: do it")
got = update(1, sender=OTHER, hold=True, until=FUT, wait_basis=f"waiting on {FRONT}'s answer, due {FUT}")
check("2 a session no page lists as back gets no note", FRONT_NOTE not in got[1], got)
reset()
put(5, mover=BACK, next=f"{BACK}: waiting on {FRONT}'s answer")
got = update(5, next=f"{BACK}: carry on")
check("2 a write that sets no wait gets no note", got[0] == "ok" and FRONT_NOTE not in got[1], got)
reset()
real = _anc.session_roles()
check("2 (the fixture) the roles list the front agent as front and the back agent as back", real.get(FRONT, {}).get("role") == "front" and real.get(BACK, {}).get("role") == "back", {k: real.get(k) for k in (FRONT, BACK)})
with patched(_anc, session_roles=lambda: {**real, FRONT: {**real[FRONT], "retired": True}}):
    got = update(1, hold=True, until=FUT, wait_basis=f"waiting on {FRONT}'s answer, due {FUT}")
check("2 a retired front agent is not one to wait on: no note, stored", got[0] == "ok" and FRONT_NOTE not in got[1] and waits(1), got)
reset()
def _boom(): raise RuntimeError("roles unreadable")
with patched(_anc, session_roles=_boom):
    got = update(1, hold=True, until=FUT, wait_basis=f"waiting on {FRONT}'s answer, due {FUT}")
    got2 = update(1, hold=True, until=FUT, wait_basis=f"the dry-run count can be read {FUT}")
check("2 a failed roles read keeps the write stored, with no front note", got[0] == "ok" and FRONT_NOTE not in got[1] and waits(1), got)
check("2 …and the own-read note, which needs no roles, still comes", has_own(got2), got2)
reset()

# ---------------------------------------------------------------- 3. an after wait shows only the item
BACKSTOP = "2099-03-09"
now = NOW
def mod_of(**meta):
    it = {"status": "open", "gid": "a9", "subject": "x", "metadata": {"project": PROJECT, "mover": BACK, "needs": [BACK], **meta}}
    return _model.derive(it, now, after_open=lambda i: ["a8"])
line = _model.words(mod_of(wait_kind="item", after=["a8"], until=BACKSTOP, post_wake_mover=BACK), derived=False, shown=lambda g: "item-" + g[1:])
check("3 words: an after wait with a backstop prints only the item it waits on", line == f"model: waiting on the close of item-8 · mover {BACK}", line)
check("3 words: a wait on a date alone still prints its date", BACKSTOP in _model.words(mod_of(hold=True, until=BACKSTOP, wait_kind="time", post_wake_mover=BACK), derived=False), _model.words(mod_of(hold=True, until=BACKSTOP, wait_kind="time", post_wake_mover=BACK), derived=False))
check("3 words: an anchor wait keeps its backstop", BACKSTOP in _model.words(mod_of(wait_kind="anchor", wait_anchor="https://example.org/pull/1", wait_event="PR merged", until=BACKSTOP, post_wake_mover=BACK), derived=False),
      _model.words(mod_of(wait_kind="anchor", wait_anchor="https://example.org/pull/1", wait_event="PR merged", until=BACKSTOP, post_wake_mover=BACK), derived=False))
empty = _model.words(mod_of(wait_kind="item", after=[], until=BACKSTOP, post_wake_mover=BACK), derived=False)
check("3 words: an item wait with no item stored keeps the old date line, never a bare close of no item", BACKSTOP in empty, empty)
got = update(1, after=["a3"], until=FUT)
shown = _wt_get.stackshot_get("a1")
mline = next((ln for ln in shown.splitlines() if ln.startswith("model:")), "")
check("3 through the tool: a stored after with a backstop is told by get as the close of the item alone", mline.startswith("model: waiting on the close of ") and FUT not in mline and "until" not in mline, (got, mline))
check("3 …and the backstop is still stored and in force", FUT in json.dumps(read(1)["metadata"]) and bool(read(1)["metadata"].get("after")), read(1)["metadata"])

print(f"wait_tells scenario: {len(ran) - len(fails)}/{len(ran)} checks")
_scratch.cleanup()
if fails:
    print("FAILED:", *fails, sep="\n  "); sys.exit(1)
print(f"ok: wait_tells scenario, {len(ran)} checks")
