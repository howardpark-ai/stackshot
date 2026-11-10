"""Scenario test for the worked examples in the board tools' text — fixture data, the tools called in-process, the self-wait model call stubbed, no live store, no network.

A worked example that the server refuses teaches the wrong call. Each example below is copied from the live tool text (the test first checks that the fragment is in the first
2,048 characters of its tool's description, the part a CLI session keeps), then called as written through the real tool function with only the names swapped for the fixture's
(session, project, item ids, a day inside the wait cap for a placeholder day).

    create   own work · an item that needs the owner's call (ask and options) · a wait on another item · work for the builder
    update   a step done and the next one added · reword · dropped · a work line · a park · a reminder wake on your own item · a wait on another item · a description
    complete done · dropped · superseded
    message  a front agent · a plain result to the project · a question and a hand-off to a background agent (the hand-off example must sit in the first 2,048 characters)
    anchors  list · add · add scoped to an item · remove        confirm        route        check=  (create and update)

    uv run tests/tool_text_examples_scenario.py        → exit 0 / 1"""
import datetime as dt, json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="examplestest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"


def write_toml():
    toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                     (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                     (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^sync = false', 'sync = true'), (r'(?m)^issues_repo = ""', 'issues_repo = "o/r"'),
                     (r'(?m)^api_url = "[^"]*"', 'api_url = "http://127.0.0.1:9"'), (r'(?m)^token_file = ""', f'token_file = "{tmp}/github.token"')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")


write_toml()
(T / "github.token").write_text("test-token\n")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
BUILDER = "00000000-0000-4000-8000-000000000003"
FRONT = "00000000-0000-4000-8000-000000000004"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now},
                                                                               BUILDER: {"name": "home-builder", "machine": "a", "seen": now},
                                                                               FRONT: {"name": "home-alpha-main", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-agent", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-alpha-main": "the front", "home-builder": "builds the code"}, "back_agents": {"home-builder": "builds the code"}}}}))
DESC = "- Goal: A thing, finished when it works"


def item(i, status="open", **meta):
    base = {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "next": "home-agent: build it"}
    base.update(meta)
    for k in [k for k, v in base.items() if v is None]: base.pop(k)
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": DESC, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600, "metadata": base}))


for i in range(1, 60):
    item(i)                                                       # items in the agent's hands, one open step each
TWO = "home-agent: build it\nhome-agent: ship it"
(T / "store/next-id").write_text("200"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-alpha\nagents:\n  home-alpha-main: the front\n  background:\n    home-builder: builds the code\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []


def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))


def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]


from stackshot.web import server; from stackshot.waits import self_wait as SW; from stackshot.router import router as R
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
def _no_claude(*a, **k): raise AssertionError("the real model was called")
R.run_call = _no_claude
SW._run = lambda message: {"status": "ok", "text": json.dumps({"can_do_now": False, "reason": "the nightly run is still going"})}   # the self-wait check: the step cannot be done now

SNAP = json.loads(pathlib.Path(SCR, "tool_text.snapshot.json").read_text(encoding="utf-8"))["tools"]
CLI_CUT = 2048                       # a CLI session keeps this many characters of a tool description
TODAY = dt.datetime.now(dt.timezone(dt.timedelta(hours=4))).date()      # the instance zone is Asia/Dubai: UTC+4
D = lambda n: (TODAY + dt.timedelta(days=n)).isoformat()


def groups_of(frags):
    """A call written whole in the text is one list of fragments; a call the text spells in pieces ("the same call with no mover, and needs=…") is a list of groups, each a list of fragments."""
    return [list(g) for g in frags] if any(isinstance(f, (list, tuple)) for f in frags) else [list(frags)]


def flat(frags):
    return [f for g in groups_of(frags) for f in g]


def fragment_ok(tool, frags):
    """The example is in the first CLI_CUT characters of the tool's description as written: each group of fragments, joined as the text joins them, whole and in that order."""
    text, at = SNAP[tool]["description"][:CLI_CUT], 0
    for g in groups_of(frags):
        i = text.find(", ".join(g), at)
        if i < 0: return False
        at = i + len(", ".join(g))
    return True


def kwargs_of(*frags, swap=None):
    """The keyword arguments the fragments spell, as a dict: JSON words read as Python, the text's names swapped for the fixture's."""
    text = ", ".join(frags)
    for old, new in (swap or []) + [("my-x", "home-agent"), ("projects/widgets", "projects/alpha"), ("[work] ", "[home] "),
                                     ("<tomorrow or later, within 7 days, YYYY-MM-DD>", D(1)), ("<last day of the window, YYYY-MM-DD>", D(3)), ("<that day>", D(3))]:
        text = text.replace(old, new)
    text = re.sub(r"\btrue\b", "True", text); text = re.sub(r"\bfalse\b", "False", text)
    kw = eval(f"dict({text})", {"__builtins__": {"dict": dict}})
    if isinstance(kw.get("reword"), dict): kw["reword"] = {str(k): v for k, v in kw["reword"].items()}      # JSON keys are strings
    return kw


def runs(name, tool, frags, fn, *, swap=None, **extra):
    """Check the fragments sit in the description's first CLI_CUT characters, then call the real tool with them."""
    check(f"{name}: the example is in the first {CLI_CUT} characters of {tool}", fragment_ok(tool, frags), ", ".join(flat(frags)))
    try:
        kw = kwargs_of(*flat(frags), swap=swap); kw.update(extra)
        out = fn(**kw)
        check(f"{name}: the server takes the example", True)
        return out
    except server.ToolError as e:
        check(f"{name}: the server takes the example", False, str(e))
    except Exception as e:
        check(f"{name}: the server takes the example", False, f"{type(e).__name__}: {e}")


def upd(i, *frags, **kw): return runs(f"update a{i}", "update", frags, lambda **k: server.stackshot_update(f"a{i}", **k), sender="home-agent", **kw)


# ---------------------------------------------------------------------------------------------------------------------------------------------------- create
DEC = ('ask="Decide: whether to approve the sample schema · Recommend: Approve · Stakes: waiting a week delays the demo · By: Mon Jun 8th 2099", '
       'options=[{"label": "Approve", "line": "Approve the schema", "recommended": true}, {"label": "Decline", "line": "Wait a week", "recommended": false}]')
SUBJ = 'subject="[work] Make the export finish in under a minute"'
DESC_X = r'description="- Goal: the export finishes in under a minute\n- Problem: the nightly run takes 9 minutes"'
P = 'project="projects/widgets"'

out = runs("create: own work", "create", [P, SUBJ, 'sender="my-x"', 'mover="my-x"', DESC_X, 'next="my-x: profile the nightly run"'],
           lambda **k: server.stackshot_create(**k))
check("create: own work: written, moved by the sender", bool(out) and "mover: home-agent" in out and "profile the nightly run" in out, out)

out = runs("create: an item that needs the owner's call", "create",
           [[P, SUBJ, 'sender="my-x"'], [DESC_X, 'next="my-x: profile the nightly run"'], ['needs="decision"', 'then="my-x"'], [DEC]],
           lambda **k: server.stackshot_create(**k))

out = runs("create: a step that waits on another item", "create",
           [[P, SUBJ, 'sender="my-x"', 'mover="my-x"', DESC_X], ['next="my-x: ship the export once board#N closes"', 'after=["board#N"]', 'ask_by="2099-03-02"']],
           lambda **k: server.stackshot_create(**k), swap=[("board#N", "a12")])

out = runs("create: work for the builder (mover left out)", "create",
           [[P, SUBJ, 'sender="my-x"'], [DESC_X, 'next="my-x: profile the nightly run"']],
           lambda **k: server.stackshot_create(**k))

# ---------------------------------------------------------------------------------------------------------------------------------------------------- update
item(40, next=TWO, owner=AGENT)       # the steps are the agent's own: only the writer of a step rewords it
upd(1, 'done=[1]', 'next="my-x: open the PR"')
check("update: done and the next one added", "open the PR" in str(mt(1).get("next")), mt(1))
upd(40, 'reword={"2": "my-x: ship the export"}')
check("update: reword", "ship the export" in str(mt(40).get("next")), mt(40))
item(41, next=TWO, owner=AGENT)
upd(41, 'dropped=[2]')
upd(2, 'work={"text": "PR 83 up", "state": "in progress"}')
check("update: a step status", "PR 83 up" in json.dumps(mt(2)), mt(2))
upd(3, 'hold=true', 'wake="<last day of the window, YYYY-MM-DD>"', 'wait_basis="soak ends <that day>"')
check("update: a park", mt(3).get("hold") and mt(3).get("wake", "").startswith(D(3)), mt(3))
upd(4, 'wake="<tomorrow or later, within 7 days, YYYY-MM-DD>T04:00"', 'wait_reason="the nightly run finishes at 03:00"')
check("update: a reminder wake on your own item", mt(4).get("wake", "").startswith(D(1)), mt(4))
upd(5, 'after=["board#N"]', 'ask_by="2099-03-02"', swap=[("board#N", "a12")])
upd(6, DESC_X)
check("update: a description", "takes 9 minutes" in rd(6)["description"], rd(6)["description"])

# why the reminder example names a day inside the cap: a far wake with a reason and no wait_basis is refused
item(9)
try:
    server.stackshot_update("a9", sender="home-agent", wake="2099-03-02T09:00", wait_reason="the nightly run finishes at 03:00"); check("update: a wake far past the cap without a wait_basis is refused", False)
except server.ToolError as e:
    check("update: a wake far past the cap without a wait_basis is refused", "wait_basis" in str(e) or "days" in str(e), str(e))
check("update: …and the text says a wake past the cap needs a wait_basis", "needs a wait_basis" in SNAP["update"]["description"][:CLI_CUT] + SNAP["update"]["parameters"]["wake"]["description"])

# ---------------------------------------------------------------------------------------------------------------------------------------------------- complete
CLOSE = 'sender="my-x"'
runs("complete: done", "complete", ['outcome="done"', 'reason="Export shipped in PR 12"', r'outcome_text="- PR 12 merged\n- live on the box"'],
     lambda **k: server.stackshot_complete("a7", **k), sender="home-agent")
check("complete: done: the item is completed", rd(7)["status"] == "completed", rd(7).get("status"))
item(50)
runs("complete: dropped", "complete", ['outcome="dropped"', 'reason="No longer needed"', 'outcome_text="- The export moved to another team"'],
     lambda **k: server.stackshot_complete("a50", **k), sender="home-agent")
runs("complete: superseded", "complete", ['outcome="superseded"', 'superseded_by="board#M"', 'reason="Merged into board#M"', 'outcome_text="- Scope moved to board#M"'],
     lambda **k: server.stackshot_complete("a51", **k), sender="home-agent", swap=[("board#M", "a52")])

# ---------------------------------------------------------------------------------------------------------------------------------------------------- message
# The examples are called through the real function with the text's names swapped for the fixture's. The delivery itself (the hub, a pane) is not under test: a message to a
# session that is not live is queued, which is a successful reply.
msg = SNAP["message"]["description"][:CLI_CUT]
MSGS = [("ask a front agent", 'to="widgets-main", sender="my-x", text="[for the owner]\\nDecide whether the export ships on Friday; I would ship it."'),
        ("a plain result to the project", 'to="projects/widgets", sender="my-x", text="PR 12 is live", fyi=true'),
        ("a question to a background agent (the id in backticks)", 'to="widgets-builder", sender="my-x", text="Does `board#N` need the export in the nightly run?"'),
        ("a hand-off of a done step (the id as a plain word)", 'to="widgets-builder", sender="my-x", text="board#N: the design is done, build the export"')]
for what, frag in MSGS:
    check(f"message: {what}: the example is in the first {CLI_CUT} characters", f"message({frag})" in msg, frag)
    out = runs(f"message: {what}", "message", [frag], lambda **k: server.stackshot_message(**k), swap=[("widgets-main", "home-alpha-main"), ("[for the owner]", server._FOR_OWNER), ("widgets-builder", "home-builder"), ("board#N", "a12")])
    check(f"message: {what}: the reply says what became of it", bool(out) and out.split()[0].lower().rstrip(":—") in ("delivered", "queued", "held", "inbox", "not"), out)
check("message: the hand-off sentence and the context-only sentence are both in the first characters",
      "which names the item id, written as a plain word, not in backticks or quotes" in msg and "An item id cited only for context, not handed over, goes in backticks" in msg, msg[-400:])
check("message: the front-agent example opens with the mark the server asks for", 'text="[for the owner]\\n' in msg, msg[:CLI_CUT])

# ---------------------------------------------------------------------------------------------------------------------------------------------------- anchors, confirm, route
P_ = 'project="projects/widgets"'; PR_ = 'add=["https://github.com/acme/widgets/pull/12"]'
anc = lambda **k: server.stackshot_anchors(**k)
item(12)
runs("anchors: list", "anchors", [P_], anc)
runs("anchors: add one for the project", "anchors", [P_, PR_], anc)
runs("anchors: scope it to an open item", "anchors", [P_, PR_, 'items=["board#N"]'], anc, swap=[("board#N", "a12")])
runs("anchors: remove", "anchors", [P_, 'remove=["https://github.com/acme/widgets/pull/12"]'], anc)
check("anchors: the four examples are written as anchors(...) calls", all(f"anchors({x})" in SNAP["anchors"]["description"][:CLI_CUT] for x in (
      P_, f"{P_}, {PR_}", f'{P_}, {PR_}, items=["board#N"]', f'{P_}, remove=["https://github.com/acme/widgets/pull/12"]')), SNAP["anchors"]["description"][:900])

item(8)
runs("confirm", "confirm", ['item_id="board#N", sender="my-x"'], lambda **k: server.stackshot_confirm(**k), swap=[("board#N", "a8")])
check("confirm: the example is written as confirm(...)", 'confirm(item_id="board#N", sender="my-x")' in SNAP["confirm"]["description"][:CLI_CUT])

nid = server._routing.record("projects/alpha", kind="board", to=AGENT, label="board note", who="hub", text="a note for the export work", target="project-wide")
out = runs("route", "route", ['notice="a1b2c3", ruling="passed", to="my-x", reason="belongs to the export work", sender="my-x"'], lambda **k: server.stackshot_route(**k),
           swap=[("a1b2c3", nid), ('to="my-x"', 'to="home-builder"')])
check("route: the example is written as route(...)", 'route(notice="a1b2c3", ruling="passed", to="my-x", reason="belongs to the export work", sender="my-x")' in SNAP["route"]["description"][:CLI_CUT])
check("route: the reply names the ruling", bool(out) and "ruled" in out and "passed" in out, out)

# ---- the check= example: it sits in the parameter text of create and update (and in the update description after the first characters), so it is called here with the whole text searched
item(10)
CHK = 'next="other-x: build the export", check="pr_merged acme/widgets#12"'
check("update: the check example is in the parameter text and the description", 'check="pr_merged acme/widgets#12"' in SNAP["update"]["parameters"]["check"]["description"] and 'check="pr_merged acme/widgets#12"' in SNAP["update"]["description"],
      SNAP["update"]["parameters"]["check"]["description"][:300])
try:
    out = server.stackshot_update("a10", sender="home-agent", **kwargs_of(CHK, swap=[("other-x", "home-builder")])); check("update a10: the server takes the check example", True)
    check("update a10: the check is stored", "pr_merged" in json.dumps(mt(10)), mt(10))
except server.ToolError as e:
    check("update a10: the server takes the check example", False, str(e))

try:
    out = server.stackshot_create(sender="home-agent", mover="home-agent", **kwargs_of(P, SUBJ, DESC_X, CHK, swap=[("other-x", "home-builder")])); check("create: the server takes the check example", bool(out) and "created" in out, out)
except server.ToolError as e:
    check("create: the server takes the check example", False, str(e))
check("create: the check example is in the parameter text", 'check="pr_merged acme/widgets#12"' in SNAP["create"]["parameters"]["check"]["description"])

print(("ok" if not fails else "FAILED") + f": tool text examples scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
