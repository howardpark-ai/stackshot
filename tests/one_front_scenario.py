"""Scenario test for moving to one front agent — fixture data, no live store, no network.

Covers: `project agent-background` (a listed front agent turned background: the keeper mark and the status stay, a dry run writes nothing, the refusals); a project left with a background agent alone
and `[front] agent` set (a question to it, a new item, an inbound notice, the configured front as contact); `client.py repoint FROM TO` (a dry run first, what moves on open items, what is left or
listed, the one notice, a second run; a reworded step's proof; a script route's own step; the notice with an issue-numbered item and a failed push; a save that fails part way; a front agent of
another project as the new session).

    tests/run-suite one_front        → exit 0 / 1"""
import contextlib, hashlib, io, json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="onefront-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's fleet store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "state/cache", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
CHIEF, SOLO, SOLOB, MAIN, SIDE, BUILD = "team-chief", "home-golf-main", "home-golf-builder", "home-delta-main", "home-delta-desk", "home-delta-builder"
CLUB = "home-club-main"
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({f"00000000-0000-4000-8000-00000000000{i}": {"name": n, "machine": "a", "url": "", "seen": "x"} for i, n in enumerate((CHIEF, SOLO, SOLOB, MAIN, SIDE, BUILD, CLUB), 1)}))
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
def page(key, agents="", hub=""):
    (T / f"brain/{key}.md").parent.mkdir(parents=True, exist_ok=True)
    (T / f"brain/{key}.md").write_text(f"---\ntype: project\ntitle: {key[9:].title()}\n" + (f"agents:\n{agents}\n" if agents else "") + (f"hub: {hub}\n" if hub else "") + "status: active\n---\n\n# x\n", encoding="utf-8")
page("projects/chief", f"  {CHIEF}: talks to the owner about everything")
page("projects/golf", f"  {SOLO}: talks to the owner about golf\n  background:\n    {SOLOB}: builds golf")
page("projects/delta", f"  {MAIN}: talks to the owner\n  {SIDE}: answers at the side desk\n  background:\n    {BUILD}: builds delta")
page("projects/golf/club", f"  {CLUB}: talks to the owner about the club")          # a sub-page of golf (no front agent) that lists its own
page("projects/golf/range", hub="projects/delta")                                   # a sub-page whose hub lists fronts
page("projects/golf/shop")                                                          # a sub-page with neither
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.web import server, wiring  # noqa: F401  (installs the hooks)
from stackshot.web import publish as _web_publish, page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route, create as _wt_create
from stackshot.web.routes import client_api
from stackshot.projects import pages, project_registry as pr, project_verbs as pv, keeper as kp
from stackshot.router import page_debt, router
from stackshot.anchors import anchors
from stackshot.service import item_read, contacts, question, item_open, job_alert, telling, proofs, writes, update
from stackshot.model import steps as st
from stackshot.github import ghsync as _gh
from stackshot.fleet import client, sessions_registry as sr
from stackshot.core import config as cfg
from stackshot.core.instance import OWNER
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
told = []                                              # every notice the server would send: recorded, never sent
send = telling.tell_woken                              # the real sender, for the check of a push that fails
telling.tell_woken = lambda *a, **k: told.append((a, k))
pages.cmd_registry(quiet=True)
IO = page_debt.PlainIO()
pid = lambda key: anchors.registry()[key]["id"]
GOLF = pid("projects/golf")
REC = T / "store/project-record.json"
sha = lambda: hashlib.sha256(REC.read_bytes()).hexdigest() if REC.exists() else ""
text = lambda: (T / "brain/projects/golf.md").read_text(encoding="utf-8")
def refused(fn):
    try:
        fn(); return None
    except Exception as e:  # noqa: BLE001
        return e

# ---- a listed front agent turned background
pv.keeper("projects/golf", SOLO, apply=True, io=IO, by="cli", run_dir=T / "undo")
was, page_was = sha(), text()
r = pv.agent_background("projects/golf", SOLO, io=IO, by="cli", dry=True)
check("agent-background, dry run: says the change and writes neither the record nor the page", r["dry"] and r["lines"][0] == f"{SOLO} on projects/golf: front -> background" and sha() == was and text() == page_was, r)
r = pv.agent_background("projects/golf", SOLO.upper(), io=IO, by="cli")
pages.cmd_registry(quiet=True)
ag = pr.entries()[GOLF]["agents"]
check("agent-background: the agent is background in the record, its mandate and keeper mark kept", r["result"] == "background" and ag[SOLO]["front"] is False and ag[SOLO]["mandate_line"] == "talks to the owner about golf" and kp.record_mark(ag)[0] == SOLO, ag)
check("agent-background: the project keeps its status (not archived), and its page and roles list the agent as background", (pr.entries()[GOLF].get("status") or "active") == "active" and "status: active" in text()
      and SOLO in anchors.registry()["projects/golf"]["back_agents"] and anchors.session_roles()[SOLO]["role"] == "back", (text(), anchors.session_roles().get(SOLO)))
check("agent-background: the answer names the roles that change and warns that no front agent is left", any(x.startswith(f"roles.json {SOLO}: front") for x in r["lines"]) and "no front agent is left" in r.get("warning", "") and "its hub's, else the configured one ([front] agent)" in r["warning"], r)
was = sha(); r = pv.agent_background("projects/golf", SOLO, io=IO, by="cli")
check("agent-background again: already background, nothing written", r["result"] == "already background" and not r["changed"] and sha() == was, r)
# its mandate rewritten afterwards, with a condition written in another script: both existing commands, and the text read back from the record, the page and the registry
WORDS = "".join(map(chr, (0xD55C, 0xAD6D, 0xC5B4))) + " " + chr(0x65E5) + chr(0x672C) + " " + chr(0xE9) + "t" + chr(0xE9)
rest = lambda a: {k: v for k, v in a.items() if k != "mandate_line"}
before = rest(pr.entries()[GOLF]["agents"][SOLO])
for how in ("project.py agent-mandate", "client.py post project-agent-mandate"):
    line = f"works behind {CHIEF}, who relays to the owner ({how.split()[0]}); answers in {WORDS} when asked in it: never otherwise"
    if how.startswith("project.py"):
        run = subprocess.run([sys.executable, f"{STACK}/stackshot/tools/project.py", "agent-mandate", "projects/golf", SOLO, "--mandate", line], capture_output=True, text=True, encoding="utf-8", env=os.environ, cwd=tmp)
        done = (run.returncode == 0, run.stdout, run.stderr)
    else:
        s, d = client_api._client_post("a", "project-agent-mandate", {"project": "projects/golf", "name": SOLO, "mandate": line, "sender": "00000000-0000-4000-8000-000000000002"})
        done = (s == 200, s, d)
    pages.cmd_registry(quiet=True)
    now = pr.entries()[GOLF]["agents"][SOLO]
    check(f"{how}: a non-ASCII line reads back the same from the record, the page and the registry, every other field kept", done[0] and now["mandate_line"] == line and rest(now) == before and WORDS in text()
          and anchors.registry()["projects/golf"]["agents"][SOLO] == line and SOLO in anchors.registry()["projects/golf"]["back_agents"], (done, now, text()))
e = refused(lambda: pv.agent_background("projects/golf", "home-golf-nobody", io=IO, by="cli"))
check("agent-background: a name that is not listed is refused", getattr(e, "status", 0) == 404, e)
pv.agent_add("projects/delta", "delta-app", True, "answers the app", surface="slack", io=IO, by="cli")
e = refused(lambda: pv.agent_background("projects/delta", "delta-app", io=IO, by="cli"))
check("agent-background: an agent of another surface is refused", getattr(e, "status", 0) == 400, e)
run = subprocess.run([sys.executable, f"{STACK}/stackshot/tools/project.py", "--dry-run", "agent-background", "projects/delta", SIDE], capture_output=True, text=True, env=os.environ, cwd=tmp)
check("agent-background from the command line", run.returncode == 0 and f"{SIDE} on projects/delta: front -> background" in run.stdout, (run.returncode, run.stdout, run.stderr))

# ---- a project with a background agent alone
pages.cmd_registry(quiet=True)
def rd(g): return json.loads(next((T / "store").glob(f"?/{re.findall(r'[0-9]+', str(g))[-1]}.json")).read_text())   # a new item takes the instance's letter
def who(g, key="contact"): return sr._session_label(str(rd(g)["metadata"].get(key) or ""))
def ask(n):
    return question._question("a", {"project": "projects/golf", "ask": "Decide: which tee time · Recommend: the early one · Stakes: a lost slot · By: Friday", "subject": "[home] Pick the tee time",
                                    "text": "Two slots are open.", "request_id": f"q{n}", "options": [{"label": "Early", "line": "book the early slot", "recommended": True}, {"label": "Late", "line": "book the late slot"}]})
def opened(n):
    return item_open._itemopen_post("a", {"marker": f"chore:{n}", "project": "projects/golf", "subject": "[home] Mow the green", "step": f"{SOLOB}: mow it", "mover": SOLOB,
                                          "description": "- Goal: a mown green\n- It lives here\n- Done when mown"})
def mk(**kw):
    return _wt_create.stackshot_create(**{"subject": "[home] a golf item", "description": "- Goal: A thing\n- It lives here\n- Done when done", "project": "projects/golf",
                                          "sender": SOLOB, "mover": SOLOB, "next": f"{SOLOB}: build it", **kw})
def failed(): return job_alert._jobalert_failed_post("a", {"unit": "golf-mow.service", "host": "testbox", "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "project": "projects/golf"})
q0, o0, j0 = ask(0), opened("zero"), failed()
check("with no configured front such a project refuses a question, item-open and a job alert, and names no stand-in", q0[0] == 409 and o0[0] == 409 and j0[0] == 409 and anchors.sole_front() == "" and anchors.fallback_main("projects/golf") == "", (q0, o0))
cfg.CFG.setdefault("front", {})["agent"] = "home-golf-nobody"
check("a configured name no page lists as front counts for nothing", anchors.sole_front() == "" and ask(1)[0] == 409)
cfg.CFG["front"]["agent"] = CHIEF
s, d = ask(2)
check("a question to the project is filed, taken after the answer by the configured front, who is its contact", s == 200 and who(d["item"], "then") == CHIEF and who(d["item"]) == CHIEF, (s, d, rd(d["item"])["metadata"] if s == 200 else ""))
s, d = opened("one")
check("item-open files an item on the project, kept by the configured front and moved by the background agent", s == 200 and who(d["item"], "owner") == CHIEF and who(d["item"], "mover") == SOLOB and who(d["item"]) == CHIEF, (s, d))
s, d = failed()
check("a job alert on the project is filed there, kept by the configured front", s == 200 and d["project"] == "projects/golf" and who(d["item"], "owner") == CHIEF, (s, d))
r = mk(); g = r.split()[1] if r.startswith("created") else ""
check("a new item by the background agent has the configured front as contact", g and who(g) == CHIEF, r)
r = mk(subject="[home] a named contact", contact=CHIEF)
check("the configured front can be named as the contact", r.startswith("created") and who(r.split()[1]) == CHIEF, r)
e = refused(lambda: mk(subject="[home] a wrong contact", contact=MAIN))
check("another project's front agent still cannot be named", e is not None and "not a front agent" in str(e), e)
cx = router.Context()
note = {"id": "n1", "kind": "message", "from": "a-script", "target": "projects/golf", "text": "a report", "ts": time.time()}
line = router.fallback_line(note, "k1", "projects/golf", cx, "unknown")
check("an inbound notice nothing places is passed to the configured front", cx.main_agent("projects/golf") == CHIEF and line["ruling"] == "passed" and line["target"] == CHIEF, line)
person = {"id": "n2", "kind": "anchor", "anchor": "slack:C1", "author_kind": "person", "from": "someone", "text": "can you look?", "ts": time.time()}
line = router.person_hold_line(person, "k2", "projects/golf", cx, "unplaced")
check("a person's inbound message is held for the project's background agent", line["ruling"] == "passed" and line["target"] == SOLOB, line)
cfg.CFG.setdefault("router", {})["general_home"] = cfg.CFG["router"]["general_ops"] = MAIN
check("with a general agent too, the contact is the configured front and notices keep the general one", anchors.contact_main("projects/golf") == CHIEF and contacts._contact_of({"project": "projects/golf", "contact": SOLO}) == CHIEF
      and anchors.contact_main("projects/delta") == MAIN, (anchors.contact_main("projects/golf"), anchors.fallback_main("projects/golf")))

# ---- a sub-page: its own front agent, else its hub's, else the configured one
pages.cmd_registry(quiet=True)
check("a sub-page's registry entries are read", all(k in anchors.registry() for k in ("projects/golf/club", "projects/golf/range", "projects/golf/shop")), sorted(anchors.registry()))
def sub(name, **kw): return mk(subject=f"[home] on {name}", project=f"projects/golf/{name}", **kw)
r = sub("club"); g = r.split()[1] if r.startswith("created") else ""
check("a sub-page that lists its own front agent: that agent is the default contact, not the configured one", g and who(g) == CLUB and anchors.contact_main("projects/golf/club") == CLUB and anchors.has_front("projects/golf/club"), (r, anchors.contact_main("projects/golf/club")))
r = sub("range"); g = r.split()[1] if r.startswith("created") else ""
check("a sub-page whose hub lists fronts: the hub's -main agent is the default contact", g and who(g) == MAIN and anchors.contact_main("projects/golf/range") == MAIN and anchors.has_front("projects/golf/range"), (r, anchors.contact_main("projects/golf/range")))
r = sub("shop"); g = r.split()[1] if r.startswith("created") else ""
check("a sub-page with neither: the configured front is the default contact", g and who(g) == CHIEF and anchors.contact_main("projects/golf/shop") == CHIEF and not anchors.has_front("projects/golf/shop"), (r, anchors.contact_main("projects/golf/shop")))
r = sub("club", contact=CLUB)
check("a sub-page's own front agent can be named as its contact", r.startswith("created") and who(r.split()[1]) == CLUB, r)
r = sub("range", contact=MAIN)
check("a sub-page's hub front agent can be named as its contact", r.startswith("created") and who(r.split()[1]) == MAIN, r)
e = refused(lambda: sub("club", contact=CHIEF))
check("the configured front is not offered to a sub-page that lists its own", e is not None and "not a front agent" in str(e), e)
check("a sub-page's items are kept by its own front agent, else its hub's, else the configured one", (item_read._front_keepers("projects/golf/club"), item_read._front_keepers("projects/golf/range"), item_read._front_keepers("projects/golf/shop"))
      == ([CLUB], sorted([MAIN, SIDE], key=lambda n: (not n.endswith("-main"), n)), [CHIEF]), (item_read._front_keepers("projects/golf/club"), item_read._front_keepers("projects/golf/range"), item_read._front_keepers("projects/golf/shop")))

# ---- repoint
now0 = time.time()
def put(i, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": status,
        "updated": now0 - 60, "state_updated": now0 - 60, "confirmed": now0 - 60, "metadata": {"owner": SIDE, "project": "projects/delta", **meta}}))
for p in (T / "store/a").glob("*.json"): p.unlink()
line1, line2 = f"{SIDE}: draft the note", f"{BUILD}: send it"
full = dict(mover=SIDE, needs=["external", SIDE], observers=[SIDE, BUILD], contact=SIDE, tell_him=[SIDE], next=f"{line1}\n{line2}",
            steps=[{"text": line1, "status": "open", "tag": {"text": "D1", "state": "assigned", "ts": 1}}, {"text": line2, "status": "open"}])
put(1, **full); put(2, "completed", mover=SIDE); put(3, mover=MAIN, owner=MAIN)
put(5, mover=OWNER, then=SIDE, needs=[OWNER], owner=MAIN)          # waits on the owner, taken after him by the old session
told.clear()                                           # the notices of the creates above are not repoint's
cfg.CFG.setdefault("audit", {})["builder"] = SIDE
snap = {i: (T / f"store/a/{i}.json").read_bytes() for i in (1, 2, 3, 5)}
s, out = client_api._client_post("a", "repoint", {"from": SIDE, "to": BUILD})
rows = {r["item"][-1]: r for r in out.get("items") or []}; row = rows.get("1") or {}
check("repoint, dry run: lists the open item and its fields, writes and tells nothing", s == 200 and out["dry_run"] and set(rows) == {"1", "5"} and set(row["changed"]) == {"mover", "needs", "observers", "next", "contact"} and rows["5"]["changed"] == ["then"]
      and row["left"] and all((T / f"store/a/{i}.json").read_bytes() == b for i, b in snap.items()) and told == [], (s, out))
check("repoint: lists the settings that name the old session, by key and not changed", "setting audit.builder" in out["settings"] and cfg.CFG["audit"]["builder"] == SIDE and out["created"] == 1, out)
s, out = client_api._client_post("a", "repoint", {"from": SIDE, "to": BUILD, "apply": True})
m = rd(1)["metadata"]
check("repoint to a background agent: mover, then, needs and observers move, each session once", s == 200 and out["written"] == 2 and who(1, "mover") == BUILD and who(5, "then") == BUILD
      and [sr._session_label(x) for x in m["needs"]] == ["external", BUILD] and [sr._session_label(x) for x in m["observers"]] == [BUILD], (out, m))
check("repoint: the next line and its step name the new session, the step keeping its tag", m["next"] == f"{BUILD}: draft the note\n{line2}" and m["steps"][0]["text"] == f"{BUILD}: draft the note" and m["steps"][0]["tag"]["text"] == "D1", m)
check("repoint: the contact falls to the project's -main agent, tell_him stays and is reported, the creator stays", who(1) == MAIN and m["tell_him"] == [SIDE] and m["owner"] == SIDE and any("tell_him" in x for r in out["items"] for x in r["left"]), m)
check("repoint: one notice names every item the new holder got, the closed item untouched", len(told) == 1 and told[0][0][:2] == ("a1,a5", sr._store_ref(BUILD)) and (T / "store/a/2.json").read_bytes() == snap[2], told)
s, out = client_api._client_post("a", "repoint", {"from": SIDE, "to": BUILD, "apply": True})
check("repoint again: nothing more to write", s == 200 and out["written"] == 0 and len(told) == 1, out)
told.clear(); put(4, mover=SIDE, contact=SIDE, tell_him=[SIDE], next=f"{SIDE}: carry on")
client.post = lambda what, body, timeout=0: client_api._client_post("a", what, body)
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "repoint", SIDE, MAIN, "--apply"])
check("repoint to a front agent from the command line: contact and tell_him follow, no notice", rc == 0 and who(4) == MAIN and rd(4)["metadata"]["tell_him"] == [MAIN] and told == [] and "applied" in buf.getvalue(), (rc, buf.getvalue(), rd(4)["metadata"]))
for what, a, b in (("a name no page lists", SIDE, "home-delta-nobody"), ("one session twice", SIDE, SIDE), ("the owner", SIDE, "owner"), ("no name", "", BUILD)):
    s, out = client_api._client_post("a", "repoint", {"from": a, "to": b, "apply": True})
    check(f"repoint refuses {what}", s == 400 and out.get("error"), (s, out))


def clear():
    told.clear()
    for q in (T / "store").glob("?/*.json"): q.unlink()
def move(a, b): return client_api._client_post("a", "repoint", {"from": a, "to": b, "apply": True})
def opens(g): return [x["text"] for x in st.view(rd(g)["metadata"], keeper=rd(g)["metadata"]["owner"]) if x["status"] == st.OPEN]

# a step with an explicit proof keeps it under its new words, through a later write too
clear()
old, new, pr5 = f"{SIDE}: merge the change", f"{BUILD}: merge the change", "pr_merged example/repo#5"
put(6, mover=SIDE, next=old, steps=[{"text": old, "status": "open"}], step_proof={st.key(old): pr5})
move(SIDE, BUILD)
m = rd(6)["metadata"]
check("repoint: a reworded step keeps its proof, and the event still ticks it", m.get("step_proof") == {st.key(new): pr5}
      and proofs.proof_hits(st.view(m), [0], m, "pr_merged", 5, "example/repo#5", set(), False) == {0: True}, m)
report = f"{BUILD}: report it"
out = update._update("a6", next=f"{new}\n{report}", sender=BUILD)
m = rd(6)["metadata"]
check("repoint: a later write of the list keeps the moved proof and adds no second step", m.get("step_proof") == {st.key(new): pr5} and opens(6) == [new, report] and "proof dropped" not in out, (out, m))

# a script route's own step on an item whose other lines move
clear()
sync = {"action": "open", "marker": "chore:box", "project": "projects/delta", "subject": "Restart the box", "description": ["The box is stuck"], "mover": OWNER, "then": SIDE, "step": "restart the box"}
s, d = client_api._client_post("a", "item-sync", sync)
g = d.get("item", "")
mine, extra = f"{OWNER}: restart the box", f"{SIDE}: check the box after"
if g:
    it = rd(g); gm = it["metadata"]
    gm["steps"] = st.stored([*st.view(gm, keeper=gm["owner"]), {"text": extra, "status": "open"}]); gm["next"] += "\n" + extra
    next((T / "store").glob(f"?/{re.findall(r'[0-9]+', g)[-1]}.json")).write_text(json.dumps(it))
s2, d2 = move(SIDE, BUILD)
m = rd(g)["metadata"] if g else {}
moved = f"{BUILD}: check the box after"
check("repoint: a script route's own step stays recorded as its own beside the moved line", s == 200 and s2 == 200 and d2["written"] == 1 and m.get("item_sync_step") == "restart the box" and m.get("item_sync_sent") == "restart the box"
      and opens(g) == [mine, moved] and who(g, "then") == BUILD, (d, d2, m))
s, d = client_api._client_post("a", "item-sync", {**sync, "then": BUILD})
check("repoint: the route's repeat open adds no second step", s == 200 and d["action"] == "refreshed" and opens(g) == [mine, moved], (d, rd(g)["metadata"]))
s, d = client_api._client_post("a", "item-sync", {**sync, "then": BUILD, "step": "restart the box twice"})
check("repoint: the route's next step replaces its own and leaves the moved line once", s == 200 and sorted(opens(g)) == sorted([moved, f"{OWNER}: restart the box twice"]), (d, rd(g)["metadata"]))

# an issue-numbered item (its shown id is not its stored one) and a push that fails: the real sender records it
clear()
(T / "store/g").mkdir(exist_ok=True)
(T / "store/g/7.json").write_text(json.dumps({"id": "7", "subject": "[home] item 7", "description": "- A thing\n- It lives here\n- Done when done", "status": "open", "updated": now0, "metadata": {"owner": MAIN, "project": "projects/delta", "mover": SIDE}}))
(T / "push_fails.py").write_text("print('failed: no live pane')\n")
threads = []
real_push, telling.PUSH = telling.PUSH, [sys.executable, str(T / "push_fails.py")]
telling.tell_woken = lambda *a, **k: threads.append((a, send(*a, **k)))
s, d = move(SIDE, BUILD)
for _a, th in threads:
    if th: th.join(60)
telling.PUSH, telling.tell_woken = real_push, lambda *a, **k: told.append((a, k))
u = rd(7)["metadata"].get("undelivered") or []
shown = _gh.shown("g7")
check("repoint: a notice that cannot be delivered is recorded on an item whose shown id is not its stored one", s == 200 and shown != "g7" and d["told"] == [shown] and len(threads) == 1 and shown in threads[0][0][2]
      and [(x.get("tag"), x.get("to")) for x in u] == [("repoint", BUILD)], (d, threads, u))

# a save that fails part way: what had moved is still told
clear()
put(8, mover=SIDE, owner=MAIN); put(9, mover=SIDE, owner=MAIN)
real_save, saved = writes.save, []
def one_save(gid, *a, **k):
    if saved: raise OSError("no space left")
    saved.append(gid); return real_save(gid, *a, **k)
writes.save = one_save
e = refused(lambda: move(SIDE, BUILD))
writes.save = real_save
check("repoint: a save that fails still sends the notice for the items already moved", isinstance(e, OSError) and len(saved) == 1 and len(told) == 1 and told[0][0][:2] == (saved[0], sr._store_ref(BUILD)), (e, saved, told))

# FROM typed in another letter case moves what the right case moves
clear()
put(13, mover=SIDE, needs=["external", SIDE], observers=[SIDE], contact=SIDE, next=f"{SIDE}: draft the note", steps=[{"text": f"{SIDE}: draft the note", "status": "open"}], then=SIDE)
s, d = move(SIDE.upper(), BUILD); m = rd(13)["metadata"]
check("repoint: FROM typed in capitals moves every field the lower-case name moves", s == 200 and set(d["items"][0]["changed"]) == {"mover", "then", "needs", "observers", "next", "contact"} and who(13) == MAIN
      and who(13, "mover") == BUILD and m["next"] == f"{BUILD}: draft the note" and not d["items"][0]["left"], (s, d, m))

# two lines that read alike once reworded keep a proof
clear()
a1, a2 = f"{SIDE}: merge the change", f"{BUILD}: merge the change"
put(14, mover=SIDE, next=f"{a1}\n{a2}", steps=[{"text": a1, "status": "open"}, {"text": a2, "status": "open"}], step_proof={st.key(a1): "pr_merged example/repo#5", st.key(a2): "pr_merged example/repo#6"})
move(SIDE, BUILD); m = rd(14)["metadata"]
check("repoint: a step already worded as the new one keeps its own proof, none is dropped", m.get("step_proof") == {st.key(a2): "pr_merged example/repo#6"}, m)
clear()
put(15, mover=SIDE, next=f"{a1}\n{a2}", steps=[{"text": a1, "status": "open"}, {"text": a2, "status": "open"}], step_proof={st.key(a1): "pr_merged example/repo#5"})
move(SIDE, BUILD); m = rd(15)["metadata"]
check("repoint: the old step's proof goes to the step already worded as the new one when that has none", m.get("step_proof") == {st.key(a2): "pr_merged example/repo#5"}, m)

# a save that fails part way: the command line does not say nothing moved
real_post = client.post
client.post = lambda what, body, timeout=0: (500, {"error": "OSError: no space left"})
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "repoint", SIDE, BUILD, "--apply"])
client.post = lambda what, body, timeout=0: (400, {"error": "from and to = two session names"})
buf2 = io.StringIO()
with contextlib.redirect_stdout(buf2): rc2 = client.main(["client.py", "repoint", SIDE, BUILD, "--apply"])
client.post = real_post
check("repoint on the command line: a failure part way says what stays moved, a refusal says nothing moved", rc == 1 and "stay moved" in buf.getvalue() and "items not moved" not in buf.getvalue() and rc2 == 1 and "items not moved" in buf2.getvalue(), (buf.getvalue(), buf2.getvalue()))

# the new session is a front agent of another project: contact only where an update would take it
clear()
put(10, contact=SIDE, owner=MAIN); put(11, contact=SIDE, owner=CHIEF); put(12, contact=SOLO, owner=SOLOB, project="projects/golf")
move(SIDE, CHIEF); move(SOLO, CHIEF)
check("repoint to another project's front agent: the contact falls to the -main agent, unless that session created the item or is the configured front of a project with none",
      (who(10), who(11), who(12)) == (MAIN, CHIEF, CHIEF), (who(10), who(11), who(12)))

# no front is made from a lone name-line session while a front is configured
for key, lines in (("projects/lone", "display-name: home-lone-main\n"), ("projects/lead", "display-name: home-lead-main\nagents:\n  background:\n    home-lead-builder: builds the lead's work\n")):
    (T / f"brain/{key}.md").write_text(f"---\ntype: project\ntitle: {key[9:].title()}\n{lines}status: active\n---\n\n# x\n", encoding="utf-8")
pages.cmd_registry(quiet=True)
configured = cfg.CFG["front"]["agent"]
cfg.CFG["front"]["agent"] = ""
free = {n: anchors.file_roles().get(n, {}).get("role") for n in ("home-lone-main", "home-lead-main", "home-lead-builder", "home-golf-main")}
check("a lone name-line session is front when no front is configured, as before", free == {"home-lone-main": "front", "home-lead-main": "front", "home-lead-builder": "back", "home-golf-main": "back"}, free)
cfg.CFG["front"]["agent"] = configured
FR = anchors.file_roles()
check("a lone name-line session is no front while a front is configured: it keeps its name-line role, on its project",
      FR["home-lone-main"] == {"role": "keeper", "project": "projects/lone"} and FR["home-lead-main"] == {"role": "keeper", "project": "projects/lead"}, (FR.get("home-lone-main"), FR.get("home-lead-main")))
check("…a background agent stays back, the configured front stays front, and no session of those projects is listed as front",
      FR["home-lead-builder"]["role"] == "back" and FR[CHIEF]["role"] == "front" and FR[SOLO]["role"] == "back" and not [n for n, r in FR.items() if r["role"] == "front" and r["project"] in ("projects/lone", "projects/lead")], FR)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
