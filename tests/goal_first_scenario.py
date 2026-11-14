"""Scenario test for the goal-first form of an item's text (the create and update tools' `Goal:` gate) — fixture data, no live store, no network.

Covers: a session's create is refused unless the description's first `- ` bullet opens `Goal:` (case-sensitive, the label right after the dash, with a sentence after it):
no bullet at all, another label, a lowercase `goal:`, `Goals:`, a bold label, a bare `Goal:` and a goal that sits second are all refused, each with a refusal that names the
first words it saw, says the subject and the first bullet state the outcome wanted, sends a symptom, cause or trigger to a later `Problem:` bullet, gives the before and after
example and the retry hint, and files nothing; the same description with `- Goal: …` first passes (a leading quote line or a later `Problem:` bullet is fine; the first `- ` bullet
is the one read); an update that replaces the description is judged the same, an update that leaves the description out, sends the stored text back, closes the item or sets a
new subject alone is not; the items a script files (the question route, the server's own `_create`, a script's sender on update, the re-bullet route) are filed whatever their first
bullet says; `[description] require_bullets = false` switches it off with the other form checks; the form gate still speaks first for prose; the pure readers
(bullet_text.first_bullet, goal_of); and the tools' text states the rule in create, update and the connector's tool list.

    tests/run-suite goal_first        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="goalfirst-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra"): (T / d).mkdir(parents=True)
NAMES = ("falcon-main", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/example.md", "type: project\ntitle: Stackshot\ndisplay-name: falcon\nagents:\n  falcon-main: builds it\nstatus: active")
page("projects/other.md", "type: project\ntitle: Other\ndisplay-name: home-other\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import bullet_text as BT; from stackshot.model import ids as _model_ids; from stackshot.service import create as create_svc
from stackshot.web import publish as _web_publish
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import text as _wt_text
from stackshot.web.tools import update as _wt_update
from stackshot.service import writes
server._cfg.CFG.setdefault("model", {})["guards"] = False      # fixture owners the fleet does not know; the write guards have their own suite
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None

MAIN = "falcon-main"
STK = "projects/example"
GOOD = "- Goal: The nightly run finishes by 06:00\n- Problem: it fails when the disk is full\n- Lives in the nightly unit"
def n_items(): return len(list((T / "store").rglob("[0-9]*.json")))
def create(desc=GOOD, **kw):
    if not kw.get("next") and "ask" not in kw:
        kw["next"] = f"{MAIN}: carry on"
    r = _wt_create.stackshot_create(subject=kw.pop("subject", "[home] Make the nightly run finish by 06:00"), description=desc, project=STK, owner=MAIN, **kw)
    return r, _model_ids._norm_id(r.split()[1])
def update(gid, **kw): return _wt_update.stackshot_update(gid, sender=MAIN, **kw)
def stored(gid): return json.loads((T / "store" / gid[0] / f"{gid[1:]}.json").read_text(encoding="utf-8"))
def legacy(i, desc="- A thing\n- It lives here\n- Done when done"):
    """an item stored before the gate: its first bullet carries no label"""
    now = time.time()
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] old item {i}", "description": desc, "status": "open", "updated": now, "state_updated": now, "confirmed": now,
                                                    "metadata": {"owner": MAIN, "project": STK, "next": f"{MAIN}: carry on"}}))
    return f"a{i}"
def refusal(f):
    try:
        f(); return ""
    except server.ToolError as e:
        return str(e)

# ---- 1. the pure readers
check("first_bullet: the first `- ` line, without its dash", BT.first_bullet("- one\n- two") == "one" and BT.first_bullet("  - indented\n- two") == "indented", None)
check("first_bullet: a quote line or a fenced block before it is passed over", BT.first_bullet("> quoted\n- Goal: x") == "Goal: x" and BT.first_bullet("```\n- inside\n```\n- after") == "after", None)
check("first_bullet: no bullet is None (prose, a star, an empty text)", BT.first_bullet("prose") is None and BT.first_bullet("* star") is None and BT.first_bullet("") is None and BT.first_bullet("-nospace") is None, None)
check("goal_of: the sentence after `Goal:` in the first bullet", BT.goal_of("- Goal: Make X work\n- Problem: y") == "Make X work", BT.goal_of("- Goal: Make X work"))
check("goal_of: case-sensitive, label right after the dash, text required, first bullet only",
      all(BT.goal_of(t) is None for t in ("- goal: x", "- Goals: x", "- GOAL: x", "- **Goal:** x", "- Goal:", "- Goal:   ", "- A thing\n- Goal: x", "- The Goal: x", "")), None)

# ---- 2. create: refused
n0 = n_items()
SEEN = "the first bullet starts"
for name, desc, saw in (("another label first", "- Problem: it fails when the disk is full\n- Goal: it does not", "Problem: it fails when"),
                        ("an unlabeled first bullet", "- A thing\n- It lives here\n- Done when done", "A thing"),
                        ("a lowercase `goal:`", "- goal: the run finishes", "goal: the run finishes"),
                        ("`Goals:`", "- Goals: the run finishes", "Goals: the run finishes"),
                        ("a bold label", "- **Goal:** the run finishes", "**Goal:** the run finishes"),
                        ("a bare `Goal:` with no sentence", "- Goal:\n- Problem: x", "Goal:"),
                        ("the goal second", "- Problem: it fails\n- Goal: it works", "Problem: it fails")):
    e = refusal(lambda: create(desc))
    check(f"create refused: {name}", e.startswith("Refused: the description must open with its goal") and f"{SEEN} “{saw}" in e, e)
e = refusal(lambda: create("> only a quote line"))
check("create refused: a description with no `- ` bullet at all, with the same text", e.startswith("Refused: the description must open with its goal, and it has no `- ` bullet"), e)
e = refusal(lambda: create(""))
check("create refused: an empty description is no goal either", e.startswith("Refused: the description must open with its goal, and it has no `- ` bullet"), e)
e = refusal(lambda: create("- A thing"))
check("the refusal names the outcome form, the Problem bullet, the example and the retry hint",
      "`- Goal: <the result you want, in a sentence>`" in e and "opens `Problem:`" in e and "“Fix X fails when Y”" in e and "“Make X work when Y”" in e
      and "`- Goal: X works when Y`" in e and "`- Problem: X fails when Y`" in e and "case-sensitive" in e and "Retry the call" in e and "MCP Portal" in e and "The subject and the first bullet" in e, e)
check("…and long first words are cut to six words", f"{SEEN} “one two three four five six”" in refusal(lambda: create("- one two three four five six seven eight")), None)
check("every refusal above filed nothing", n_items() == n0, n_items() - n0)
e = refusal(lambda: create("A thing. It lives here."))
check("prose is still the form gate's refusal, which speaks first", e.startswith("Refused: description line is not a `- ` bullet"), e)

# ---- 3. create: passes
r, g = create()
check("create passes: the first bullet opens `Goal:`", r.startswith("created") and stored(g)["description"] == GOOD, r)
r, g = create("- Goal: The disk never fills")
check("create passes: a Goal bullet alone", r.startswith("created"), r)
r, g = create("> the nightly run keeps failing\n- Goal: The nightly run stays green\n- Problem: it fails twice a week")
check("create passes: a quote line before it, the first `- ` bullet is the one read", r.startswith("created"), r)
r, g = create("-  Goal: two spaces after the dash")
check("create passes: any spaces after the dash", r.startswith("created"), r)

# ---- 4. update
legacy(41)
r = update("a41", priority="p2")
check("update passes: a call without a description is not judged, whatever the stored first bullet", "updated" in r.lower() or "a41" in r, r)
r = update("a41", description="- A thing\n- It lives here\n- Done when done")
check("update passes: the stored text sent back is no rewrite", stored("a41")["description"].startswith("- A thing"), r)
e = refusal(lambda: update("a41", description="- A thing, reworded\n- It lives here"))
check("update refused: a replacement description with no Goal bullet, naming what it saw", e.startswith("Refused: the description must open with its goal") and f"{SEEN} “A thing, reworded”" in e, e)
check("…and it wrote nothing", stored("a41")["description"].startswith("- A thing\n"), stored("a41")["description"])
e = refusal(lambda: update("a41", description="- goal: lowercase\n- It lives here"))
check("update refused: a lowercase label", "must open with its goal" in e, e)
r = update("a41", description="- Goal: The thing works\n- Problem: it did not\n- It lives here")
check("update passes: a replacement that opens with `Goal:`", stored("a41")["description"].startswith("- Goal: The thing works"), r)
r = update("a41", description="- Goal: The thing works\n- Problem: it did not")
check("update passes: …and a later rewrite that keeps a Goal bullet", stored("a41")["description"].count("\n") == 1, r)
legacy(42)
r = update("a42", subject="[home] Make the old thing work")
check("update passes: a new subject alone", stored("a42")["subject"] == "[home] Make the old thing work", r)
r = _wt_complete.stackshot_complete("a42", outcome="done", reason="finished", outcome_text="- It is done\n- In use", sender=MAIN)
check("complete passes: a close judges its outcome text, not the description", stored("a42")["status"] == "completed" and stored("a42")["description"].startswith("- A thing"), r)
legacy(43)
r = _wt_complete.stackshot_complete("a43", outcome="done", reason="finished", description="- It is done", sender=MAIN)
check("complete passes: a description passed with a close is the outcome text, and the description stays", stored("a43")["status"] == "completed" and stored("a43")["description"].startswith("- A thing"), r)
legacy(44)
r = update("a44", status="completed", outcome="done", reason="finished", outcome_text="- Done")
check("update passes: a close through update", stored("a44")["status"] == "completed", r)
r = update("a44", status="open", next=f"{MAIN}: look again")
check("update passes: a reopen without a description", stored("a44")["status"] == "open", r)

# ---- 5. what is not the create and update tools' own call is never refused
legacy(45)
out = server._update("a45", description="- A rewrite with no label\n- Second", sender="home-other")
check("a server-side _update with an unlabeled description is written", stored("a45")["description"].startswith("- A rewrite"), out)
out = _wt_create._create(subject="[home] built by the server", description="- No label here\n- Second", project=STK, owner=MAIN, next=f"{MAIN}: carry on")
check("the server's own _create is filed whatever its first bullet", out.startswith("created"), out)
me = "box-1"
st, ans = server._client_post(me, "question", {"project": "example", "ask": "Decide: whether to cut the retry to three · Recommend: cut it · Stakes: the run waits an hour either way · By: Fri Oct 23rd",
                                               "text": "The nightly run failed twice on the same step.\nCut the retry to three, or keep five and wait?", "sender": "q-script",
                                               "options": [{"label": "Cut", "line": "Cut the retry to three and go on.", "recommended": True}, {"label": "Keep", "line": "Keep five retries and wait.", "recommended": False}],
                                               "subject": "[home] Cut the nightly retry?", "request_id": "goal-q-1"})
check("the question route files its item whatever its first bullet says", st == 200 and ans.get("item") and not stored(_model_ids._norm_id(ans["item"]))["description"].startswith("- Goal:"), (st, ans))
with writes.session_write():
    out = create_svc.create_item(subject="[home] filed by a script label", description="- No label here\n- Second", project=STK, owner=MAIN, next=f"{MAIN}: carry on", by="a script (a script on box-1)")[1]
check("an item a script label files is filed whatever its first bullet, even inside a session write", out.startswith("created"), out)
legacy(46)
r = _wt_update.stackshot_update("a46", description="- A script's rewrite\n- Second", sender="a script on box-1")
check("an update from a script's sender is not judged", stored("a46")["description"].startswith("- A script's rewrite"), r)
before = n_items()
try:
    writes.REFORMAT.on = True
    legacy(47)
    with writes.session_write():
        out = server._update("a47", description="- Re-bulleted, same words\n- Second", sender="rebullet")
finally:
    writes.REFORMAT.on = False
check("the re-bullet route's filing edit is not judged, inside a session write too", stored("a47")["description"].startswith("- Re-bulleted"), out)

# ---- 6. the switch
server._cfg.CFG["description"]["require_bullets"] = False
r = create("Plain prose, as before.")[0]
check("require_bullets = false: the goal check is off with the other form checks (the way back)", r.startswith("created"), r)
server._cfg.CFG["description"]["require_bullets"] = True
check("…and back on by default", "must open with its goal" in refusal(lambda: create("- A thing")), None)

# ---- 7. the text sessions learn the rule from
TOOLS = {t.name: t.description for t in __import__("asyncio").run(server.mcp.list_tools())}
for t in ("create", "update"):
    check(f"the {t} tool's text says the subject is the outcome and the first bullet opens `Goal:`, a symptom goes under `Problem:`",
          "the outcome wanted" in TOOLS[t] and "opens `Goal:`" in TOOLS[t] and "opens `Problem:`" in TOOLS[t] and "never the symptom" in TOOLS[t] and "case-sensitive" in TOOLS[t], TOOLS[t][:300])
check("the shared form says an update that leaves the description out is never judged", "an update that leaves description out is never judged" in _wt_text._ITEM_FORM, None)

print(("ok" if not fails else "FAILED") + f": goal_first scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
