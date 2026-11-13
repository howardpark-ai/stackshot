"""Scenario test for creating an item (stackshot/service/create.py, `create_item` with its `Hooks`, and the request map) — a scratch store, fake hooks, no server, no port, no network.

The create runs the write gates (service/gates.py: this suite replaces each there with a recorder) and the checks and notices that are still server.py's through `Hooks`, takes the item's id, saves it through the write path and tells the sessions it names, in an order that is part of what
a create means. This suite installs hooks that record each call and return what a gate that lets the write through returns, wraps the save in a recorder (which calls the real one) and holds:

  1  order          the whole sequence of a session's create, from the subject gate to the reply's last note; a create from a script (`by`) leaves out the checks of a session's own write
  2  flags          the three thread-local flags are read through the hooks: a session's write (goal, an open step, a front agent's step), a script's question (the open-question checks are skipped), the
                    terminal prompt's row (no owner-step check, no page debt, no pilot relay)
  3  the file       the item the save gets: id, clocks, who wrote it, `filed_by` for a script, the fixes recorded; the subject takes the project's prefix; the writer is `by` or the creator
  4  refusals       a gate that refuses stops the create before an id is taken or a file is written, and the request is remembered only after the save
  5  request map    a retry with the same request id returns the item the first call made and runs no gate; an entry whose item is gone files anew; the map is written whole and leaves no temporary file
  6  github ids     with the issue-number ids on, the id is the issue's; a GitHub that does not answer is a refusal without the queue and a temporary id with it (budget or outage), told in the reply
  7  hooks          a create without hooks installed is refused, and a hook table with a hook missing cannot be built
  8  the table      the table the server builds holds every hook, and looks each up when it is called: a patch of the owner (the nag's page_debts, a gate on the server) after the install reaches the create

    tests/run-suite create        -> exit 0 / 1"""
import dataclasses, json, os, pathlib, re, sys, threading
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
tmp = _scratch.mkdtemp(prefix="wr3-create-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home").mkdir(); (T / "store/g").mkdir(parents=True); (T / "store/s").mkdir(parents=True); (T / "fleet").mkdir(); (T / "state").mkdir()
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1200]}" if got is not None else ""))

from fastmcp.exceptions import ToolError
from stackshot.core import store as cstore
from stackshot.github import ghsync as gh
from stackshot.service import create, gates, writes
cstore.STORE = T / "store"
check("0 the module's request map sits in the instance's state folder", str(create.REQUESTS) == f"{tmp}/state/requests.json", create.REQUESTS)

LOG = []                                                     # every hook and the save, in the order they were called: (name, args)
FLAGS = {"session_next": False, "question": False, "terminal_row": False}
RET = {}                                                     # a hook's return value by name, where the default below is not what a case needs
RAISE = {}                                                   # a hook that refuses (ToolError) by name
BORED = {"gate_options": [], "gate_needs": [], "gate_observers": [], "gate_after": [], "gate_said": [], "parse_check": "", "gate_model_args": ({}, {}), "contact_default": "",
         "gate_draft_args": ("", False), "step_proof_set": "", "fallback_wait_date": ("", "", ""), "evwait_gate": "", "owner_then_default": "", "lift_ask": "", "ask_owed": "",
         "options_note": "", "actor_note": "", "gate_model": "", "after_open": False, "model_guards_on": True, "pilot_charge": ("", ""), "writer_owes": False, "pilot_relay": "",
         "tell_needed": "", "handoff_notify": "", "machine_note": "", "fmt": "<item>", "said_note": "", "form_notes": "", "similar_note": "", "nag": "", "session_id": None,
         "gate_ask": None, "gate_contact": "", "wait_alias_gate": None, "project_subject_prefix": "", "writer_charge": ""}
def hook(name):
    def run(*a, **k):
        LOG.append((name, a, k))
        if name in RAISE: raise ToolError(RAISE[name])
        if name in RET: return RET[name]
        if name == "session_id": return a[0]
        if name == "gate_ask": return a[0]
        if name == "next_put": a[0]["next"] = a[1]; return []
        if name == "pilot_charge": return ("", "")
        if name in ("wait_alias_gate",): return __import__("datetime").date(2000, 1, 1)
        return BORED.get(name)
    return run
def flag(name):
    def run():
        LOG.append((name, (), {}))
        return FLAGS[name]
    return run
# the write gates are service/gates.py's, not hooks: the create calls them on that module, so this suite replaces each there (the recorder above) and puts the real ones back before it imports the server
REAL_GATES = {n: getattr(gates, n) for n in dir(gates) if n.startswith("gate_") and callable(getattr(gates, n))}
for _n in REAL_GATES: setattr(gates, _n, hook(_n))
def make_hooks(**over):
    kw = {}
    for f in dataclasses.fields(create.Hooks):
        if f.name in FLAGS: kw[f.name] = flag(f.name)
        elif f.name == "ask_none": kw[f.name] = ("none", "clear", "-")
        elif f.name == "subject_tagged": kw[f.name] = re.compile(r"^\[[a-z]+\] ")
        else: kw[f.name] = hook(f.name)
    kw.update(over)
    return create.Hooks(**kw)

STEPS = ("settle_mover", "owner_steps", "ask_stamp", "handoff_on_save", "handoff_his_over", "handoff_follow", "phase_stamp", "foryou_on_save", "landed_on_save", "search_touch", "handback_drop", "answer_ack")
writes.install(writes.Steps(**{n: (lambda *a, **k: None) for n in STEPS}))
real_save = writes.save
def save(gid, item, **kw):
    LOG.append(("save", (gid,), dict(kw, subject=item.get("subject"), had_id=item.get("id"))))
    return real_save(gid, item, **kw)
writes.save = save

OWNER = "wr3-session"
DESC = "- Goal: Done when the thing is done\n- A second bullet"
def mk(**kw):
    base = dict(subject="[home] a thing to do", description=DESC, project="projects/alpha", owner=OWNER, next=f"{OWNER}: begin")
    base.update(kw)
    LOG.clear()
    return create.create_item(**base)
def names(skip=()):
    return [n for n, _a, _k in LOG if n not in skip]
def called(name): return [(a, k) for n, a, k in LOG if n == name]
def rd(gid): return json.loads((T / "store" / gid[0] / f"{gid[1:]}.json").read_text(encoding="utf-8"))
def files(): return sorted(f"{p.parent.name}{p.name}" for p in (T / "store").glob("*/*.json"))

create.install(make_hooks())

# ---------------------------------------------------------------- 1. order
FLAGS.update(session_next=True)
gid, reply = mk()
FLAG_READS = ("session_next", "question", "terminal_row")
got = names(skip=FLAG_READS)
check("1 the whole order of a session's create, from the subject gate to the last note of the reply", got == [
    "gate_subject", "gate_recycle_item", "gate_description", "gate_goal", "gate_next", "gate_bare_urls", "gate_options", "session_id", "gate_said", "wait_alias_gate", "gate_model_args",
    "contact_default", "next_put", "gate_step_gap", "evwait_gate", "owner_then_default", "gate_draft_args", "gate_metadata", "lift_ask", "ask_owed", "gate_one_decision", "gate_alternatives",
    "gate_open_question", "gate_recommend_stance", "gate_mockup", "gate_own_action", "options_note", "actor_note", "gate_model", "anchor_wait_gate", "gate_owner_step", "model_guards_on",
    "gate_front_step", "refuse_if_owing", "record_fixes", "save", "pilot_charge", "owed_mark", "tell_needed", "handoff_notify", "publish", "machine_note", "fmt", "said_note", "form_notes",
    "similar_note", "nag"], got)
check("1 …and the reply opens with the created line, then the item as get shows it", reply.startswith(f"created {gh.shown(gid)} — it is being published to the board (") and "<item>" in reply, reply[:200])
check("1 a create that files the item takes the page debt: the creator is charged for it (the pilot gives no keeper)", called("owed_mark")[0][0] == ("projects/alpha", OWNER, gid), called("owed_mark"))
gid_s, _ = mk(by="a script (a script on box-a)", subject="[home] a script's item")
got_s = names(skip=FLAG_READS)
check("1 a script's create (by=…) skips the goal, the front-agent step and the page-debt checks of a session's write", not {"gate_goal", "gate_front_step", "refuse_if_owing"} & set(got_s), got_s)
check("1 …and still runs the gates every create runs, and the save", {"gate_subject", "gate_description", "gate_next", "gate_model", "gate_owner_step", "save"} <= set(got_s), got_s)
check("1 …and the script's nag is the empty one (no creator to nag)", called("nag")[0][0] == ("",), called("nag"))
check("1 a script's filing charges no one when the pilot names no keeper (no mark, no relay)", not called("owed_mark") and not called("pilot_relay"), got_s)
FLAGS.update(session_next=False)
gid_n, _ = mk()
check("1 a write that is not a session's own (no flag) is not judged by the goal, the open step or the front-agent checks", not {"gate_goal", "gate_front_step"} & set(names()), names())

# ---------------------------------------------------------------- 2. flags
FLAGS.update(session_next=True)
mk()
check("2 a session's write reads the flag once per check, through the hook (goal, open step, front-agent step)", names().count("session_next") >= 3 and "gate_goal" in names(), names())
try: mk(next=""); RAISE_NO_STEP = None
except ToolError as e: RAISE_NO_STEP = str(e)
check("2 a session's create with no step in next is refused with the open-step text (N6)", RAISE_NO_STEP is not None and RAISE_NO_STEP.startswith("Refused: the new item has no open step in next"), RAISE_NO_STEP)
FLAGS.update(session_next=False)
mk(next="")
check("2 …and the same create is not refused when the write is no session's", True)
FLAGS.update(question=True)
mk()
check("2 a script's question skips the open-question and the stance checks", "gate_open_question" not in names() and "gate_recommend_stance" not in names() and "gate_mockup" in names(), names())
FLAGS.update(question=False)
FLAGS.update(terminal_row=True)
RET["pilot_charge"] = ("stew-session", "name")
RET["writer_owes"] = True
RET["pilot_relay"] = "\n(relayed)"
gid_t, rep_t = mk(by="a script (a script on box-a)")
n_t = names(skip=FLAG_READS)
check("2 the terminal prompt's row skips the owner-step check", "gate_owner_step" not in n_t, n_t)
check("2 …owes no page: no one is charged, no mark, no pilot relay, no writer charge", not {"owed_mark", "pilot_relay", "writer_charge"} & set(n_t), n_t)
check("2 …and the reply carries no relay line", "(relayed)" not in rep_t, rep_t)
FLAGS.update(terminal_row=False)
RET["writer_owes"] = False
gid_p, rep_p = mk()
n_p = names(skip=FLAG_READS)
check("2 without the row flag, a keeper who must account for the page gets the relay", "pilot_relay" in n_p and "(relayed)" in rep_p, (n_p, rep_p))
check("2 …and the page debt is marked on the keeper, not on the creator", called("owed_mark")[0][0] == ("projects/alpha", "stew-session", gid_p), called("owed_mark"))
RET["writer_owes"] = True; RET["pilot_charge"] = ("stew-session", "name"); RET["writer_charge"] = "\n(charged)"
gid_w, rep_w = mk()
check("2 a keeper named by name, with the writer owing and no script: the writer is charged, not the keeper", "writer_charge" in names() and "owed_mark" not in names() and "(charged)" in rep_w, (names(), rep_w))
RET.pop("pilot_charge"); RET.pop("writer_owes"); RET.pop("pilot_relay"); RET.pop("writer_charge")

# ---------------------------------------------------------------- 3. the file
FLAGS.update(session_next=True)
import time
t0 = time.time()
gid, rep = mk(subject="[home] the item", priority="p2", due="2030-01-02", owner_name="Wr3 Title")
it = rd(gid)
sv = called("save")[0]
check("3 the item's id is the next one in the store, without its letter", gid == gid[0] + it["id"] and it["id"].isdigit(), (gid, it["id"]))
check("3 the save gets the new id and the creator as the writer", sv[0] == (gid,) and sv[1]["writer"] == OWNER and sv[1]["had_id"] == it["id"], sv)
check("3 the clocks are set together: updated, state_updated and confirmed", t0 - 1 <= it["updated"] and it["updated"] == it["state_updated"] == it["confirmed"], it)
check("3 the metadata holds the creator, the project and the fields given", it["metadata"].get("owner") == OWNER and it["metadata"]["project"] == "projects/alpha" and it["metadata"].get("priority") == "p2" and it["metadata"].get("due") == "2030-01-02" and it["metadata"].get("owner_name") == "Wr3 Title", it["metadata"])
check("3 the item is open and has no filed_by", it["status"] == "open" and "filed_by" not in it, it)
gid_b, _ = mk(by="a script (a script on box-a)", subject="[home] filed by a script", extra={"terminal_prompt": "wr3"})
it_b = rd(gid_b); sv_b = called("save")[0]
check("3 a script's item is saved under the script's name, records it as filed_by, and carries the route's own marks", sv_b[1]["writer"] == "a script (a script on box-a)" and it_b["filed_by"] == "a script (a script on box-a)" and it_b["metadata"].get("terminal_prompt") == "wr3" and it_b["metadata"]["owner"] == OWNER, (sv_b, it_b))
RET["project_subject_prefix"] = "[work] "
gid_p, _ = mk(subject="no prefix at all")
check("3 a subject with no scope prefix takes the project's, through the hook", rd(gid_p)["subject"] == "[work] no prefix at all" and called("project_subject_prefix"), rd(gid_p)["subject"])
gid_q, _ = mk(subject="[home] already scoped")
check("3 …and one with a prefix of the instance's list does not ask the project", not called("project_subject_prefix") and rd(gid_q)["subject"] == "[home] already scoped", names())
gid_r, _ = mk(subject="no prefix at all", by="a script (a script on box-a)")
check("3 …nor does a script's subject get one", not called("project_subject_prefix") and rd(gid_r)["subject"] == "no prefix at all", names())
RET.pop("project_subject_prefix")
gid_f, _ = mk(fixes=[("front-mover", "tok", "line")])
check("3 what a tool wrapper fixed is passed to the record before the save", names().index("record_fixes") < names().index("save") and called("record_fixes")[0][0][1] == [("front-mover", "tok", "line")], called("record_fixes"))
RET["contact_default"] = "wr3-main"
gid_c, _ = mk()
check("3 the contact defaults to the hook's answer when none is named", rd(gid_c)["metadata"].get("contact") == "wr3-main", rd(gid_c)["metadata"])
RET.pop("contact_default")
RET["gate_contact"] = "wr3-named"
gid_c2, _ = mk(contact="wr3-named")
check("3 …and a named contact is checked by the gate and stored", rd(gid_c2)["metadata"].get("contact") == "wr3-named" and called("gate_contact") and not called("contact_default"), (called("gate_contact"), rd(gid_c2)["metadata"]))
RET.pop("gate_contact")
RET["gate_needs"] = ["decision"]
gid_d, _ = mk(needs=["decision"], ask="Which one?")
check("3 needs are gated and stored", rd(gid_d)["metadata"].get("needs") == ["decision"] and called("gate_needs")[0][0][0] == ["decision"], rd(gid_d)["metadata"])
RET.pop("gate_needs")
try: mk(anchors=["https://example.invalid/x"]); anc = None
except ToolError as e: anc = str(e)
check("3 anchors belong to the project: a create with them is refused before the item is made", anc is not None and anc.startswith("Refused: anchors belong to the project") and "save" not in names(), (anc, names()))
import datetime as dt
from stackshot.projects import pages as _pages
def parse_wake(v):
    if not re.fullmatch(r"\d{4}-\d\d-\d\d(T\d\d:\d\d)?", v): raise ToolError("Refused: no date")
    return v
def wake_at(v):
    d = dt.datetime.fromisoformat(v if "T" in v else v + "T09:00")
    return d.replace(tzinfo=_pages.zone_now().tzinfo)
RET["parse_wake"] = None
create.install(make_hooks(parse_wake=lambda v: (LOG.append(("parse_wake", (v,), {})), parse_wake(v))[1], wake_at=lambda v: (LOG.append(("wake_at", (v,), {})), wake_at(v))[1]))
past = "2000-01-01"
try: mk(until=past); up = None
except ToolError as e: up = str(e)
check("3 an until in the past is refused with the zone's name", up is not None and up.startswith("Refused: until must be in the future ("), up)
try: mk(until="next friday"); up2 = None
except ToolError as e: up2 = str(e)
check("3 …and one that is no date is refused with its form", up2 is not None and up2.startswith("Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM (") and "'next friday'" in up2, up2)
far = (dt.date.today() + dt.timedelta(days=3)).isoformat()
gid_u, _ = mk(until=far, wait_kind="")
check("3 an until in the future is passed to the model's arguments as given and judged against the cap", called("gate_cap") and called("gate_model_args")[0][0][0]["until"] == far, (called("gate_cap"), called("gate_model_args")))
create.install(make_hooks())
# the writer is `by or owner`, and the writer charge is made without `loose` (the page debt of a create is the strict one)
RET["pilot_charge"] = ("stew-session", "name"); RET["writer_owes"] = True; RET["writer_charge"] = "\n(charged)"
RET["gate_model_args"] = ({"mover": "wr3-back"}, {})
gid_lw, _ = mk()
wc = called("writer_charge")
check("3 a session's create charges its page debt with loose=False, to the creator, naming the item and the keeper", len(wc) == 1 and wc[0][1].get("loose") is False and wc[0][0] == ("projects/alpha", gid_lw, OWNER, "stew-session", "created"), wc)
gh_o = called("gate_handoff")
check("3 …and a hand-off at creation is gated for the creator as the writer when no script filed it", len(gh_o) == 1 and gh_o[0][0][3] == OWNER, gh_o)
RET["writer_owes"] = False; RET["pilot_charge"] = ("stew-session", "name")
gid_sw, _ = mk(by="a script (a script on box-a)")
gh_s = called("gate_handoff")
check("3 a script's create gates the hand-off for the script, not for the creator (by or owner)", len(gh_s) == 1 and gh_s[0][0][3] == "a script (a script on box-a)", gh_s)
check("3 …and its save and its pilot charge name the script too, and no writer charge is made for a script", called("save")[0][1]["writer"] == "a script (a script on box-a)" and called("pilot_charge")[0][0][1] == "a script (a script on box-a)" and not called("writer_charge"), (called("save"), called("pilot_charge")))
RET.pop("pilot_charge"); RET.pop("writer_owes"); RET.pop("writer_charge"); RET.pop("gate_model_args")

# ---------------------------------------------------------------- 4. refusals
before_files = files()
for hook_name in ("gate_subject", "gate_description", "gate_next", "gate_model", "gate_front_step", "refuse_if_owing", "gate_handoff"):
    RAISE[hook_name] = f"Refused: {hook_name}"
    LOG.clear()
    try:
        if hook_name == "gate_handoff":
            RET["gate_model_args"] = ({"mover": "wr3-back"}, {})      # a hand-off at creation: the model's arguments name a mover
            mk(request_id=f"rid-{hook_name}")
        else:
            mk(request_id=f"rid-{hook_name}")
        out = None
    except ToolError as e: out = str(e)
    RAISE.pop(hook_name); RET.pop("gate_model_args", None)
    check(f"4 a refusal by {hook_name} reaches the caller as it is", out == f"Refused: {hook_name}", out)
    check(f"4 …writes no file, takes no id and remembers no request", files() == before_files and "save" not in names() and f"rid-{hook_name}" not in create._requests(), (files(), before_files, names()))
check("4 the checks that come after a gate do not run once it refuses (the save, the telling, the publish)", not {"save", "tell_needed", "publish"} & set(names()), names())
RAISE["gate_subject"] = "Refused: first"
try: mk(); stop = None
except ToolError: stop = names()
RAISE.pop("gate_subject")
check("4 the first gate is the subject's: nothing is called before it", stop == ["gate_subject"] or stop[:1] == ["session_next"] and stop[1:] == ["gate_subject"], stop)

# ---------------------------------------------------------------- 5. request map
real_remember = create._remember_request
def remember(rid, gid):
    LOG.append(("remember_request", (rid, gid), {}))
    return real_remember(rid, gid)
create._remember_request = remember
LOG.clear()
gid1, rep1 = mk(request_id="rid-one")
check("5 the first call files the item and remembers the request right after the save, before the page debt is charged", names().index("save") + 1 == names().index("remember_request") < names().index("pilot_charge") and create._requests().get("rid-one") == gid1, (names(), create._requests()))
create._remember_request = real_remember
n_before = len(files())
gid2, rep2 = mk(request_id="rid-one", subject="[home] a different subject")
check("5 a retry with the same request id returns the same item, files nothing and runs no gate", gid2 == gid1 and len(files()) == n_before and not {n for n in names()} - {"fmt", "nag"} , (gid2, names()))
check("5 …and its reply says so, then shows the item", rep2.startswith(f"already created as {gh.shown(gid1)} (same request_id).\n<item>"), rep2)
(T / "store" / gid1[0] / f"{gid1[1:]}.json").unlink()
gid3, _ = mk(request_id="rid-one")
check("5 an entry whose item is gone is no previous entry: the item is filed anew and the map is rewritten", gid3 != gid1 and create._requests().get("rid-one") == gid3, (gid3, create._requests()))
errs = []
def race(i):
    try: create._remember_request(f"map-race-{i}", f"s{9000 + i}")
    except Exception as e: errs.append(e)
ths = [threading.Thread(target=race, args=(i,)) for i in range(12)]
[t.start() for t in ths]; [t.join() for t in ths]
mp = create._requests()
check("5 twelve writers at once leave every entry in the map", not errs and all(mp.get(f"map-race-{i}") == f"s{9000 + i}" for i in range(12)), (errs, mp))
check("5 …and no temporary file beside it", not [f for f in os.listdir(create.REQUESTS.parent) if f.startswith(".requests.json.")], os.listdir(create.REQUESTS.parent))
create.REQUESTS.write_text("not json", encoding="utf-8")
check("5 a map that does not read is an empty one", create._requests() == {}, create._requests())

# ---------------------------------------------------------------- 6. github ids
real = {n: getattr(gh, n) for n in ("issue_ids", "allocate", "allocate_local", "enabled", "letter")}
GH = {"ids": True, "enabled": True, "alloc": None, "n": 700}
gh.issue_ids = lambda: GH["ids"]; gh.enabled = lambda: GH["enabled"]
def allocate(item, names=None, store=None, gh=None, max_wait=None):
    LOG.append(("allocate", (item.get("subject"), dict(names or {})), {"max_wait": max_wait}))
    if GH["alloc"]: raise GH["alloc"]
    GH["n"] += 1
    return GH["n"]
gh.allocate = allocate; gh.allocate_local = lambda store=None: "a-tmp-1"
try:
    gid_g, rep_g = mk()
    check("6 with the issue-number ids on, the item takes the issue's number, asked for before the file with a short wait", gid_g == f"{gh.letter()}701" and called("allocate")[0][1]["max_wait"] == gh.CREATE_WAIT and names().index("allocate") < names().index("save"), (gid_g, names()))
    check("6 …and the file is that item's", rd(gid_g)["id"] == "701", rd(gid_g))
    GH["alloc"] = gh.GitHubDown(503, "503")
    GH["enabled"] = False
    try: mk(); down = None
    except ToolError as e: down = str(e)
    check("6 GitHub not answering, with no queue to carry the create later, is a refusal that says to try again", down is not None and down.startswith("Refused: GitHub did not answer (HTTP 503: 503)") and "try again in a minute" in down, down)
    n_f = len(files())
    GH["enabled"] = True
    gid_l, rep_l = mk()
    check("6 …with the queue it takes a temporary id and the reply says so", gid_l == "a-tmp-1" and "is a temporary id: the item takes its issue number when GitHub is back" in rep_l and "GitHub did not answer (HTTP 503: 503)" in rep_l, rep_l)
    GH["alloc"] = gh.GitHubBudget(60, 120.0, "writes")
    gid_m, rep_m = mk()
    check("6 …and a spent hour's budget has its own words", "GitHub is taking no new write right now" in rep_m and "when GitHub has room" in rep_m, rep_m)
    GH["alloc"] = gh.GitHubError(422, "422")
    try: mk(); refused = None
    except ToolError as e: refused = str(e)
    check("6 GitHub refusing the issue is a refusal naming why", refused is not None and refused.startswith("Refused: GitHub refused the issue for this item (HTTP 422: 422)"), refused)
finally:
    for n, f in real.items(): setattr(gh, n, f)

# ---------------------------------------------------------------- 7. hooks
create.install(None)
try: mk(); bare = None
except RuntimeError as e: bare = str(e)
check("7 a create with no hooks installed is refused, naming the install", bare is not None and "no hooks installed" in bare, bare)
try: create.Hooks(**{f.name: None for f in dataclasses.fields(create.Hooks)[:-1]}); short = None
except TypeError as e: short = str(e)
check("7 a hook table with a hook missing cannot be built", short is not None, short)
check("7 the table holds the three flags and the two constants, and no name that service must not import", {"session_next", "question", "terminal_row", "ask_none", "subject_tagged"} <= {f.name for f in dataclasses.fields(create.Hooks)}, None)

# ---------------------------------------------------------------- 8. the table the server builds
# The server's own table, not this suite's: a hook is looked up when it is called, so a suite that replaces the owner's function after the install still reaches the create.
for _n, _f in REAL_GATES.items(): setattr(gates, _n, _f)      # the real write gates back, as the server imports them
from stackshot.web import server, page_debts
tbl = create._hooks()
check("8 no write gate is a hook of the create: the create calls each on service/gates.py, where a suite patches it", not ({f.name for f in dataclasses.fields(create.Hooks)} & set(REAL_GATES)) and len(REAL_GATES) >= 25, sorted(REAL_GATES))
check("8 the server's table has every hook the create names", {f.name for f in dataclasses.fields(create.Hooks)} == {f.name for f in dataclasses.fields(tbl)}, None)
real_nag = page_debts._nag
page_debts._nag = lambda owner="": f"<nag for {owner!r}>"
try: via_table = tbl.nag("wr3-owner")
finally: page_debts._nag = real_nag
check("8 the nag is page_debts' own function looked up at each call (a patch of its owner after the install reaches the create)", via_table == "<nag for 'wr3-owner'>", via_table)
real_gate = server._gate_subject
server._gate_subject = lambda *a, **k: "<patched gate>"
try: via_gate = tbl.gate_subject("x")
finally: server._gate_subject = real_gate
check("8 …and a gate that stays on the server is looked up late too (a suite's patch of the server's name reaches the create)", via_gate == "<patched gate>", via_gate)

writes.save = real_save
print(f"create scenario: {len(ran) - len(fails)}/{len(ran)} checks")
if fails: print(f"FAILED {len(fails)}"); sys.exit(1)
print(f"ok: create scenario, {len(ran)} checks")
