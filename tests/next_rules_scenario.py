"""Scenario test for the write checks of Next (rules N1, N3, N6 and N7 of that design) — fixture data, the tools called in-process, no live store, no network.

Covers, through stackshot_create and stackshot_update (a session's write):
  N1  a line of next that names no one is refused, naming the line and the fix; a line opening `<session>:`, `Oliver:` or an outside party's name passes; a sub-line (`- `) under a step passes, one with
      no step above it is refused; a line stored before the rule that names no one is still read (his), and a session's valid write beside it goes through
  N3  the old open step plus added words (a tail, a parenthetical) is refused and nothing is written; marking the step done and writing the next as a new step passes; a genuine rewording passes
  N6  a create with no open step is refused, one that asks Oliver (his server-made step) passes; a write that takes the last open step off an item that stays open is refused (done on it, `next=none`,
      clear_next); a close is exempt; an item that had no open step before is not refused for an unrelated write
  N7  a commit id, a test count, a past-tense status, a since-time stamp, "at work since" and a mid-line status word are noted in the reply and the write goes through; "release PR #16", "merge PR #12
      after green CI", a condition and a `Oliver:` line are quiet
Internal writers (server._update, _wt_create._create, create_item, the answer, the hold and the wake pass) are not judged: only the two tools mark a session's write.

    tests/run-suite next_rules        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="nextrulestest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"


def write_toml():
    toml = _instance.apply(_instance.base_toml())
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
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-agent", "status": "active", "board": [], "board_open": 0}}}))
DESC = "- Goal: A thing, finished when it works"
ASK = "Decide: whether to ship it now · Recommend: ship · Stakes: a day either way · By: no date"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True}]
def item(i, status="open", **meta):
    base = {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "next": "home-agent: build it"}
    base.update(meta)
    for k in [k for k, v in base.items() if v is None]: base.pop(k)
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": DESC, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600, "metadata": base}))
for i in range(1, 60):
    item(i)                                                       # items in the agent's hands, one open step each
for i in (6, 7, 8, 55, 56, 57): item(i, next="home-agent: write the docs")        # the step the N3 checks work on
item(40, next="build the old thing")                              # stored before N1: a line that names no one
item(41, next=None, needs=[])                                     # an item that stored no open step at all
(T / "store/next-id").write_text("60"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]

from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import steps as S; from stackshot.model import nextlines as NL; from stackshot.model import next_rules as NR
from stackshot.service import wakes as wakes_svc
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
from stackshot.service import writes
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
for p_ in (T / "store/a").glob("*.json"):       # as a session's write leaves them: each line remembers who wrote it (next_by), so a session's next replaces its own lines
    j_ = json.loads(p_.read_text()); m_ = j_["metadata"]
    if m_.get("next", "").startswith("home-agent:"):
        m_["next_by"] = [[AGENT, NL.key_of(m_["next"])]]; p_.write_text(json.dumps(j_))
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
def refused(name, f, *want, i=None):
    was = rd(i) if i is not None else None
    try:
        out = f(); check(name, False, out)
    except server.ToolError as e:
        check(name, all(w in str(e) for w in want) and (was is None or rd(i) == was), str(e))
def upd(i, **kw): return _wt_update.stackshot_update(f"a{i}", sender="home-agent", **kw)
def mk(**kw):
    kw = {"subject": "[home] a new thing", "description": DESC, "project": "projects/alpha", "next": "home-agent: build it", "sender": "home-agent", "mover": "home-agent", **kw}
    return _wt_create.stackshot_create(**kw)
def files(): return sorted(p.name for p in (T / "store/a").glob("*.json"))
def st(i): return [(x["status"], x["text"]) for x in S.view(mt(i), keeper=OWNER)]
OPEN = lambda t: ("open", t)

# ---- N1: a line that names no one
# N1 is the one rule on who may be named: the model guard `next_unnamed` (model_guards.py) lets any `<name>:` through, and a session's unnamed line is refused by N1 before the guard sees it (checked further down with guards ON).
# The checks in this block run with the guards off so that they stay about N1 alone, and the internal-writer checks do too (the guard still judges a script's unnamed line).
import contextlib
@contextlib.contextmanager
def noguards():
    g = server._cfg.CFG.setdefault("model", {}); was = g.get("guards", True); g["guards"] = False
    try: yield
    finally: g["guards"] = was
with noguards():
    before = files()
    refused("create: an unnamed next line is refused, naming the line and the fix", lambda: mk(next="build it"), "names no one", '"build it"', "open the line with who takes it: `<session>:`, `Oliver:` or the outside party's name")
    check("…and nothing is created", files() == before, files())
    refused("create: the second line unnamed is refused too (one step, one action, one named actor)", lambda: mk(next="home-agent: build it\ntest it"), "names no one", '"test it"')
    refused("create: with three unnamed lines the others are counted", lambda: mk(next="build it\ntest it\nship it"), "names no one", "and 2 more")
    for who in ("home-agent", "Oliver", "Kim", "Anthropic support"):
        try:
            r = mk(next=f"home-agent: build it\n{who}: do the next thing" if who != "home-agent" else "home-agent: do the next thing"); ok = r.startswith("created")
        except server.ToolError as e:
            ok, r = False, str(e)
        check(f"create: a line opening `{who}:` passes", ok, r)
    r = mk(next="home-agent: build it\n- check the log\n- then say so")
    check("create: a sub-line (`- `) under a named step belongs to it and passes", r.startswith("created"), r)
    refused("create: a `- ` line with no step above it is refused", lambda: mk(next="- check the log"), "names no one", "check the log")
    refused("create: a numbered line with no step above it is refused", lambda: mk(next="1. check the log\nhome-agent: build it"), "names no one", "check the log")

    refused("update: an unnamed next line is refused and the item is unchanged", lambda: upd(1, next="wait for the build"), "names no one", '"wait for the build"', "open the line with who takes it", i=1)
    refused("update: the same through an unnamed line after a named one", lambda: upd(1, next="home-agent: build it\nwait for the build"), "names no one", i=1)
    r = upd(2, next="home-agent: build it\n- check the log")
    check("update: a named step with a sub-line passes and the item holds both lines", "home-agent: build it" in mt(2)["next"] and "- check the log" in mt(2)["next"], (r, mt(2)))
    r = upd(3, next="home-agent: build it\nOliver: pick the path")
    check("update: `Oliver:` passes (his line is named)", "Oliver: pick the path" in mt(3)["next"], (r, mt(3)))
    r = upd(4, next="Kim: send the contract\nhome-agent: build it")
    check("update: an outside party's name opens a step", "Kim: send the contract" in mt(4)["next"], (r, mt(4)))

# N1 is the one rule while [model] guards is ON (the production default): the model guard next_unnamed lets any `<name>:` through, an outside party's among them, and an unnamed line is refused once, by N1
check("guards are on for these checks (the production default)", server._model_guards_on(), None)
r = mk(next="home-agent: build it\nKim: send the contract")
check("guards ON, create: an outside party's name opens a step and the item is created", r.startswith("created"), r)
r = mk(next="Anthropic support: answer the ticket\nhome-agent: build it")
check("guards ON, create: a name of two words passes too", r.startswith("created"), r)
r = upd(49, next="home-agent: build it\nKim: send the contract")
check("guards ON, update: an outside party's name passes", "Kim: send the contract" in mt(49)["next"], (r, mt(49)))
r = mk(next="home-agent: build it\n- check the log\n- then say so")
check("guards ON, create: a `- ` sub-line at column 0 under a named step passes (the guard no longer refuses it)", r.startswith("created"), r)
for nm, f in (("create", lambda: mk(next="build it")), ("update", lambda: upd(50, next="build it"))):
    try:
        f(); check(f"guards ON, {nm}: an unnamed line is refused", False, "not refused")
    except server.ToolError as e:
        m = str(e)
        check(f"guards ON, {nm}: an unnamed line is refused once, by N1's message, with no second refusal from the model guard", m.startswith("Refused: a line of next names no one") and m.count("Refused") == 1 and "does not say who takes it" not in m and "open the line with who takes it" in m, m)
refused("guards ON, update: a stray `- ` line with no step above it is refused by N1", lambda: upd(50, next="- check the log"), "names no one", i=50)
# the board item part 3 (the part 2 reviewer's notes b and c): a label is no actor; a role in parentheses after the name is fine; a missing space after the colon is refused with its own hint
refused("N1 (b): a `Status:` line is refused, and the refusal says a label is no actor", lambda: upd(51, next="home-agent: build it\nStatus: the build is green"), "names no one", "`Status:` is a label", "name the actor first", i=51)
refused("N1 (b): `Note:`, `Result:` and `Done:` are labels too", lambda: upd(51, next="Note: read the log"), "`Note:` is a label", i=51)
refused("N1 (b): `Status:` with no space after it gets the label hint", lambda: upd(51, next="Status:green"), "`Status:` is a label", i=51)
check("N1 (b): unnamed() lists a label line and does not take it for a step that a bullet may belong to", NR.unnamed("Status: ok\n- sub") == ["Status: ok", "- sub"] and NR.unnamed("home-agent: a\nStatus: ok") == ["Status: ok"], NR.unnamed("Status: ok\n- sub"))
check("N1 (b): a real name that only starts like a label passes (`Updates team`, `Done by`)", NR.unnamed("Updates team: send it\nNotes bot: file it") == [], NR.unnamed("Updates team: send it"))
r = upd(52, next="home-agent (builder): build the docs", dropped=[1])
check("N1 (c): a role in parentheses after the name is the name's, and the line is stored as written", st(52)[-1] == OPEN("home-agent (builder): build the docs") and S.opener("home-agent (builder): build the docs") == "home-agent", (r, st(52)))
r = upd(53, next="home-agent: build it\nKim (the vendor): send the contract")
check("N1 (c): an outside party with a role passes", "Kim (the vendor): send the contract" in mt(53)["next"], (r, mt(53)))
refused("N1 (c): no space after the colon (`home-agent:do`) is refused with the fix named", lambda: upd(54, next="home-agent:do the build"), "names no one", "put a space after the colon", "`home-agent: do", i=54)
check("N1 (c): a link is no opener and gets no spacing hint, a sentence with a colon neither", NR.hint("see https://example.org/x") == "" and NR.hint("build it") == "", NR.hint("see https://example.org/x"))
check("N1 (c): hint() of a plain line without a name is empty and of a label names it", NR.hint("Status: ok").startswith("`Status:` is a label") and NR.hint("home-agent:do it").startswith("put a space"), NR.hint("home-agent:do it"))
# the guard itself, for the writes N1 does not judge (a script's, the server's own): any name passes, an unnamed line is refused
from stackshot.model import model_guards as _MG
_it = lambda nx: {"id": "a1", "status": "open", "subject": "[home] x", "description": "- x", "metadata": {"project": "projects/alpha", "next": nx, "mover": "home-agent", "needs": ["home-agent"]}}
_ctx = _MG.Ctx(label=server._session_label, shown=server._gh.shown)
_keys = lambda nx: [p.key for p in _MG.check(_it(nx), _ctx, touched={"next"})[0]]
check("model guard next_unnamed: an outside name, a two-word name and a sub-line under a named step pass", "next_unnamed" not in _keys("Kim: send it\nhome-agent: do it\n- sub") and "next_unnamed" not in _keys("Anthropic support: answer it"), _keys("Kim: send it"))
check("model guard next_unnamed (part 3): a `Status:` label is no name for it either, and its message carries the hint",
      "next_unnamed" in _keys("Status: the build is green") and "is a label" in " ".join(p.text for p in _MG.check(_it("Status: green"), _ctx, touched={"next"})[0] if p.key == "next_unnamed"), _keys("Status: green"))
check("model guard next_unnamed: a line with no name is still refused (a script's write is no N1 write)", "next_unnamed" in _keys("send it") and "next_unnamed" in _keys("- check the log"), _keys("send it"))

# the pure matcher, the words that take lines off, and the ask line a client writes first
check("unnamed: the words none and clear and an empty text are no line", NR.unnamed("none") == [] and NR.unnamed("clear") == [] and NR.unnamed("-") == [] and NR.unnamed("") == [], NR.unnamed("none"))
check("unnamed: named lines and their sub-lines are quiet; an unnamed line and a stray bullet are listed",
      NR.unnamed("home-agent: a\n- sub\nOliver: b\nKim: c") == [] and NR.unnamed("a thing\n- sub") == ["a thing", "- sub"] and NR.unnamed("home-agent: a\nand then b") == ["and then b"], NR.unnamed("a thing\n- sub"))
check("unnamed: the ask line a client without the ask parameter writes first is no unnamed line", NR.unnamed(f"{ASK}\nhome-agent: build it", skip_first=lambda ln: server._rmod.parse_ask(ln) is not None) == [], NR.unnamed(f"{ASK}\nhome-agent: build it"))
with noguards():
    r = upd(5, next=f"{ASK}\nhome-agent: build it")
check("update: an ask written as the first next line by a client without the ask parameter is not refused as unnamed", "home-agent: build it" in mt(5)["next"], (r, mt(5)))

# a line stored before the rule is read as it was: his; a session's valid write beside it goes through
check("legacy: a stored line that names no one is still read, as an open step", st(40) == [OPEN("build the old thing")], st(40))
r = upd(40, next="home-agent: look at the old thing")
check("legacy: a session's valid write beside the stored unnamed line goes through; the old line stays on the list, untouched",
      OPEN("build the old thing") in st(40) and OPEN("home-agent: look at the old thing") in st(40), (r, st(40)))
refused("legacy: a session cannot write the unnamed line itself (it is refused as a new line)", lambda: upd(40, next="home-agent: look at the old thing\nbuild the old thing again"), "names no one", i=40)

# ---- N3: nothing leaves the list
refused("N3: the old step plus a progress clause is refused, nothing written", lambda: upd(6, next="home-agent: write the docs, builder at work since 23:28"), "with words added", "never rewritten to add progress", "done=[1]", i=6)
refused("N3: the old step plus a parenthetical is refused", lambda: upd(6, next="home-agent: write the docs (green on 3 of 4 jobs)"), "with words added", "dropped=[1]", "project page", i=6)
refused("N3: the old step plus a tail of words is refused", lambda: upd(6, next="home-agent: write the docs and then merge it"), "with words added", i=6)
refused("N3: a closing full stop on the old text is no escape", lambda: upd(6, next="home-agent: write the docs. Then it is done"), "with words added", i=6)
r = upd(6, next="home-agent: tell Oliver it is done", done=[1])
check("N3: marking the step done and writing the next as a new step passes: the old stays on the list as done, the new is open", st(6) == [("done", "home-agent: write the docs"), OPEN("home-agent: tell Oliver it is done")], (r, st(6)))
r = upd(7, next="home-agent: run the migration by hand", dropped=[1])
check("N3: a genuine rewording that is not the old text plus words passes (the old drops, the new is added)", [s for s, _ in st(7)][-2:] == ["dropped", "open"] and OPEN("home-agent: run the migration by hand") in st(7), (r, st(7)))
# the board item part 3 (reviewer note d): the step marked dropped stays on the list, so the extended line that replaces it loses nothing
r = upd(55, next="home-agent: write the docs, builder at work since 23:28", dropped=[1])
check("N3 (d): the old step marked dropped and the extended line written passes: the old stays as dropped, the extended one is open", st(55) == [("dropped", "home-agent: write the docs"), OPEN("home-agent: write the docs, builder at work since 23:28")], (r, st(55)))
r = upd(56, next="home-agent: write the docs and then merge it", done=[1])
check("N3 (d): the old step marked done and the extended line written passes", st(56) == [("done", "home-agent: write the docs"), OPEN("home-agent: write the docs and then merge it")], (r, st(56)))
refused("N3 (d): the extended line with the old step left unmarked is still refused, and the refusal says the old step carries no mark", lambda: upd(57, next="home-agent: write the docs (green on 3 of 4 jobs)"), "with words added", "left without a mark", "dropped=[1]", i=57)
r = upd(8, next="home-agent: write the docs")
check("N3: sending the same open step again changes nothing", st(8) == [OPEN("home-agent: write the docs")], st(8))
check("grows(): old plus words at a boundary, or old plus a parenthetical", NR.grows("home-a: write the docs", "home-a: write the docs (green)") and NR.grows("home-a: write the docs", "home-a: write the docs, now at work since 23:28")
      and NR.grows("home-a: write the docs.", "home-a: write the docs and merge") and NR.grows("home-a: wait (1 job)", "home-a: wait (2 jobs)"), None)
check("grows(): a different action, the same text, a word merely continued and a shorter text are no growth",
      not NR.grows("home-a: write the docs", "home-a: run the migration") and not NR.grows("home-a: write the docs", "home-a: write the docs") and not NR.grows("home-a: write the docs", "home-a: write the docss")
      and not NR.grows("home-a: write the docs and merge", "home-a: write the docs") and not NR.grows("", "x"), None)

# ---- N6: an open item has an open step
refused("N6 create: a session's create with no next at all is refused", lambda: mk(next=""), "has no open step in next", "who takes it")
with noguards():
    refused("N6 create: the word none is no step either", lambda: mk(next="none"), "has no open step in next")
r = mk(next="", needs="decision", ask=ASK, options=OPTS, mover="Oliver")
check("N6 create: an item that asks Oliver (his server-made step) is not refused for a missing next", r.startswith("created"), r)
refused("N6 update: done on the last open step of an item that stays open is refused, nothing written", lambda: upd(10, done=[1]), "no open step in next", "complete", i=10)
refused("N6 update: `next=none` that takes the last open step off (marked dropped) is refused", lambda: upd(11, next="none", dropped=[1]), "no open step in next", i=11)
refused("N6 update: clear_next that leaves no open step is refused", lambda: upd(12, clear_next=True), "no open step in next", i=12)
r = upd(13, next="home-agent: build it\nhome-agent: second step")
r = upd(13, done=[1])
check("N6 update: done on one of two open steps passes (one stays open)", st(13) == [("done", "home-agent: build it"), OPEN("home-agent: second step")], (r, st(13)))
r = upd(14, done=[1], next="home-agent: the step after")
check("N6 update: done on the last step with a new step in the same write passes", st(14) == [("done", "home-agent: build it"), OPEN("home-agent: the step after")], (r, st(14)))
r = _wt_complete.stackshot_complete("a15", outcome="done", reason="finished", description="- Goal: A thing, finished", sender="home-agent")
check("N6: closing the item (complete) is exempt: the last open step goes with it", rd(15)["status"] == "completed", (r, rd(15)["status"]))
# the board item part 3 (reviewer note a): a parked item needs the step its wake leads to
import datetime as _dt3
_w3 = (_dt3.date.today() + _dt3.timedelta(days=3)).isoformat()
refused("N6 hold (a): a hold that drops the last step is refused with the parked-item text: a parked item needs a step, the one its wake leads to", lambda: upd(58, hold=True, wake=_w3, wait_basis=f"the vendor ships the part {_w3}", dropped=[1]),
        "no open step in next", "a parked item needs a step too", "the one its wake leads to", "look again", i=58)
r = upd(58, hold=True, wake=_w3, wait_basis=f"the vendor ships the part {_w3}", next=f"home-agent: look again at the vendor part on {_w3}", dropped=[1])
check("N6 hold (a): a hold that carries a wake step in the same call passes: the old step is dropped, the wake step is open, the item is held", hd_(mt(58)) and st(58) == [("dropped", "home-agent: build it"), OPEN(f"home-agent: look again at the vendor part on {_w3}")], (r, st(58)))
refused("N6 (a): an item that is not held gets the ordinary text, with no mention of parking", lambda: upd(59, next="none", dropped=[1]), "no open step in next", "an open item always has an open step", i=59)
r = upd(41, priority="p2")
check("N6: an item that had no open step before is not refused for an unrelated write (the hold restriction: only a write that takes the last open step off is refused)", mt(41).get("priority") == "p2", (r, mt(41)))
r = upd(41, next="home-agent: take it up")
check("…and a write that gives it a step passes", st(41) == [OPEN("home-agent: take it up")], (r, st(41)))
r = upd(17, needs="decision", ask=ASK, options=OPTS)

r = upd(17, done=[1])
check("N6: his server-made open step counts: marking the session's last own step done on an item that asks him passes", ("done", "home-agent: build it") in st(17) and any(s == "open" and t.startswith("Oliver:") for s, t in st(17)), (r, st(17)))

# ---- N7: a step is an action, never a status (a note, never a refusal)
ids = iter(range(18, 39))
def n7(name, text, quiet=False, *want):
    i = next(ids)
    try:
        r = upd(i, next=f"home-agent: {text}", dropped=[1])
    except server.ToolError as e:
        check(name, False, str(e)); return
    note = "next reads like a report" in r
    ok = (not note) if quiet else (note and all(w in r for w in want))
    check(name, ok and f"home-agent: {text}" in mt(i)["next"], r)
n7("N7: a commit id is noted, naming the line, and the write goes through", "merge 015cc0de01 after the checks", False, "a commit hash", '"home-agent: merge 015cc0de01 after the checks"')
n7("N7: a test count is noted", "rerun the suite, 12 tests passed so far", False, "a test count")
n7("N7: a past-tense status at a line's start is noted", "merged to main", False, "a past-tense report")
n7("N7: `PR #12 merged` is noted", "PR #12 merged, release it", False, "a past-tense report")
n7("N7: a since-time stamp is noted", "watch the deploy, at work since 23:28", False, "a since-time stamp", "since 23:28")
n7("N7: `since 23:28` alone is noted", "review the run since 23:28", False, "a since-time stamp")
n7("N7: `at work since` is noted", "builder at work since the PR went up", False, "a since-time stamp")
n7("N7: a status word in the middle of a line is noted (`is live`)", "tell Oliver PR #12 is live", False, "a past-tense report")
n7("N7: `release PR #16` is an action and stays quiet (the PR number false positive)", "release PR #16", True)
n7("N7: `merge PR #12 after green CI` is an action and stays quiet", "merge PR #12 after green CI", True)
n7("N7: a condition before a status word is quiet (`once PR #12 is live`)", "tell Oliver once PR #12 is live", True)
n7("N7: `check that it is deployed` is quiet", "check that it is deployed", True)
n7("N7: a plain action line is quiet", "write the release notes", True)
n7("N7: a PR link alone is quiet", "review [PR 16](https://github.com/o/r/pull/16)", True)
n7("N7: a commit id in a link target is quiet", "read [the diff](https://github.com/o/r/commit/015cc0de015c)", True)
n7("N7: a hash that is the object of a wait is quiet (`when GitHub removes commit <hash>`)",
   "when GitHub removes commit 0201c0d (or support replies), trim the comment and close", True)
n7("N7: a hash after `once` is quiet", "once 0202c0d reaches main, tag the release", True)
n7("N7: a hash that reports a merge is noted (`merge at <hash>`), a later `after` in another clause changes nothing",
   "PR #7 re-checked, merge at 0202c0d; release after #5", False, "a commit hash", "0202c0d")
from stackshot.model import next_rules as _nr7
for ln, quiet in (("lane-example: when GitHub removes commit 0201c0d (or support replies), trim the comment and close", True),
                  ("lane-example: wait until 0203c0d is gone from the fork, then close", True),
                  ("lane-example: after 0204c0d is deployed, close", True),
                  ("lane-example: merged at 0202c0d, close the item", False),
                  ("lane-example: the fix landed in 0204c0d, tell the reviewer", False),
                  ("lane-example: pushed 0205c0d, wait for CI", False),
                  ("lane-example: wait for the fix in 0204c0d to deploy", False),
                  ("lane-example: head 0205c0d, review it", False),
                  ("lane-example: reviewed (merge, head 0205c0d), release it", False),
                  ("lane-example: after the rebase the fix is 0202c0d", False),
                  ("lane-example: once CI is green the fix is 0202c0d", False),
                  ("lane-example: tests pass after 0202c0d", False),
                  ("lane-example: this PR reverts 0204c0d", False),
                  ("lane-example: once 0204c0d reaches main, tag the release", True),
                  ("lane-example: until the 0204c0d is gone, hold", True)):
    hit = "a commit hash" in _nr7.report_signals(ln)
    check(f"N7: {'a hash that is waited on is quiet' if quiet else 'a hash that reports finished work is noted'}: {ln!r}", hit != quiet, _nr7.report_signals(ln))
i = next(ids)
r = upd(i, next="home-agent: build it\nOliver: merged to main, run `uptime` to confirm")
check("N7: a `Oliver:` line is exempt from the signals", "next reads like a report" not in r and "Oliver: merged" in mt(i)["next"], r)
r = mk(next="home-agent: merged to main, 015cc0de01")
check("N7: a create notes it too and still creates", r.startswith("created") and "next reads like a report" in r, r)
check("N7: the note says a step is an action and sends results to the project page", "project page" in server._report_note("home-agent: merged to main") and "never a status" in server._report_note("home-agent: merged to main"), None)

# ---- internal writers are not judged: only the two tools mark a session's write
check("the flag is off outside the tools", not getattr(writes.SESSION_NEXT, "on", False), None)
# the older model guard (next_unnamed) judges every write while [model] guards is on, the server's own among them: these checks run with it off so that the rule under test is N1/N3/N6
_ng = noguards(); _ng.__enter__()
try:
    r = server._update("a44", next="build it, no name on the line", sender="home-agent", dropped=[1])
    check("internal: server._update with an unnamed line is not refused (a script's, the router's and the server's own writes read the line as they always did)", "build it, no name" in mt(44)["next"], (r, mt(44)))
except server.ToolError as e:
    check("internal: server._update with an unnamed line is not refused", False, str(e))
try:
    server._update("a45", next="home-agent: write the docs", sender="home-agent", dropped=[1])
    r = server._update("a45", next="home-agent: write the docs, now at work since 23:28", sender="home-agent", dropped=[2])
    check("internal: server._update is not held to N3 (an old step plus words is accepted as before)", "at work since 23:28" in mt(45)["next"], (r, mt(45)))
except server.ToolError as e:
    check("internal: server._update is not held to N3", False, str(e))
try:
    r = server._update("a46", next="none", sender="home-agent", dropped=[1])
    check("internal: server._update that leaves no open step is not refused (N6 is a session's write only)", rd(46)["status"] == "open", (r, mt(46)))
except server.ToolError as e:
    check("internal: server._update that leaves no open step is not refused", False, str(e))
try:
    r = _wt_create._create(subject="[home] made by the server", description=DESC, project="projects/alpha", owner="home-agent", next="")
    check("internal: _wt_create._create with no next is not refused (the router, the cold call and the recycle write create items this way)", str(r).startswith("created"), r)
except server.ToolError as e:
    check("internal: _wt_create._create with no next is not refused", False, str(e))
try:
    r = _wt_create._create(subject="[home] made by the server again", description=DESC, project="projects/alpha", owner="home-agent", next="an unnamed line")
    check("internal: _wt_create._create with an unnamed line is not refused", str(r).startswith("created"), r)
except server.ToolError as e:
    check("internal: _wt_create._create with an unnamed line is not refused", False, str(e))
refused("a refused tool call leaves the flag off again", lambda: mk(next="build it"), "names no one")
check("…the flag is off after a tool call, refused or not", not getattr(writes.SESSION_NEXT, "on", False), None)
_ng.__exit__(None, None, None)
upd(47, needs="decision", ask=ASK, options=OPTS)
r = server._answer("a47", "Ship", "", "")
check("internal: his answer ticks his step without a refusal, with the session's own step still open", r == "decision" and ("done", "Oliver: whether to ship it now → Ship") in st(47) and OPEN("home-agent: build it") in st(47), (r, st(47)))
import datetime as _dt
_w = (_dt.date.today() + _dt.timedelta(days=3)).isoformat()
r = upd(48, hold=True, wake=_w, wait_basis=f"the vendor ships the part {_w}")
check("a hold through the tool keeps the step it had (an item on hold has the step its wake leads to)", hd_(mt(48)) and st(48) == [OPEN("home-agent: build it")], (r, st(48)))
wakes_svc.wake_pass(_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=10))
check("the wake pass over the held item raises no refusal and leaves its step", not hd_(mt(48)) and st(48) == [OPEN("home-agent: build it")], (mt(48), st(48)))
check("the router never calls the two tools (they write through the server's own functions)",
      not re.search(r"\bstackshot_(update|create)\(", pathlib.Path(STACK, "stackshot/router/router.py").read_text() + pathlib.Path(STACK, "stackshot/router/router_live.py").read_text()), None)

print(("ok" if not fails else "FAILED") + f": next_rules scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
