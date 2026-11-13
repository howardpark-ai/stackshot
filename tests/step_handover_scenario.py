"""Scenario test for the hand-over of a finished step (handover.py, server._handover / service/update.py _handover_by_hand / service/gates.py gate_step_gap, step_proof.proof_gaps, audit_checks.check_step_handover) — fixture data,
no live store, no network (GitHub's answers are a table, the pane notices go to a fake push).

Covers: the pure rules (the first open step decides; the owner, a front agent, an unknown name and the mover's own step move nothing; a session that is down falls back once; a step handed over is not
handled twice); a two-session item end to end (session A's step is ticked by its proof, session B named on the next step is reached with no message from anyone, the mover is B, the stuck-elsewhere
and the hand-over audit stay quiet); the down-session fallback (the mover keeps the item and is told once, the audit names the unreached session); parallel steps (the first open step decides, the
later ones in their turn); a step marked done by hand; a write that names the mover or needs; an event seen twice; the write check (the refusal is one line that says what to pass; a proof, a pure
phrase, a step that names no pull request and a script's write pass); the audit (a missing proof, a next session never reached, the page key for a front mover, a repeat only after an item write).

    tests/run-suite step_handover        → exit 0 / 1"""
import json, os, re, sys, pathlib, subprocess, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="stephandovertest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                              # an isolated HOME: the pane registry is a folder of ours
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/releases", "brain/projects"): (T / d).mkdir(parents=True)
NAMES = ("home-builder", "home-one", "home-two", "home-three")      # home-builder = alpha's front agent; the others are its background agents; home-gone has no heartbeat at all
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({U[n]: {"name": n, "machine": "a", "seen": now} for n in U}))
BACK = {"home-one": "builds", "home-two": "reviews", "home-three": "checks", "home-gone": "a session that is not running"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-builder", "status": "active",
                                                                               "board": [], "board_open": 0, "agents": {"home-builder": "the front"}, "back_agents": BACK}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\nagents:\n  home-builder: the front\nbackground:\n" + "".join(f"  {a}: {r}\n" for a, r in BACK.items()) + "---\n\n# Alpha\n")
REPO = "example-owner/stackshot"
def key(n, repo=REPO): return f"{repo}#{n}"

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

sys.path.insert(0, STACK)
from stackshot.waits import handover as HO
from stackshot.model import step_proof as SP

# ---- 1. the pure rules (handover.py)
def meta_of(*texts, **kw): return {"owner": "o", "project": "projects/alpha", "next": "\n".join(texts), **kw}
KIND = {"s-two": HO.SESSION, "s-three": HO.SESSION, "front": HO.FRONT, "the-owner": HO.OWNER}
kind_of = lambda n: KIND.get(n, HO.OTHER)
same = lambda a, b: a == b
def dec(meta, mover="s-one", down=lambda n: ""): return HO.decide(meta, "o", mover, kind_of, down, same)
d = dec(meta_of("s-two: check it", "s-three: ship it"))
check("rules: the first open step names another session: move to it, and only it", d["action"] == "move" and d["to"] == "s-two" and d["step"] == "s-two: check it" and d["hash"] == HO.step_hash("s-two: check it"), d)
check("rules: the mover's own first step, no open step, a step that names no one: nothing", [dec(m)["action"] for m in (meta_of("s-one: build it", "s-two: check"), {"owner": "o", "next": ""}, meta_of("just a line"))] == ["none"] * 3
      and dec(meta_of("s-two: check it"), mover="s-two")["action"] == "none")
check("rules: the owner's step, a front agent's and a name that is no session: nothing moves", [dec(meta_of(f"{n}: do it"))["action"] for n in ("the-owner", "front", "nobody")] == ["none"] * 3
      and "owner" in dec(meta_of("the-owner: do it"))["why"] and "front agent" in dec(meta_of("front: do it"))["why"] and "no session" in dec(meta_of("nobody: do it"))["why"])
m = meta_of("s-two: check it")
d = dec(m, down=lambda n: "no pane of it is in the heartbeat")
check("rules: a session that is down: a fallback with the reason", d["action"] == "fallback" and d["why"] == "no pane of it is in the heartbeat", d)
HO.mark(m, d["hash"], HO.FALLBACK, "s-two", now, d["why"])
check("rules: …told once: the same step falls back no second time", dec(m, down=lambda n: "gone")["action"] == "none" and "told already" in dec(m, down=lambda n: "gone")["why"])
check("rules: …and moves when the session can be reached", dec(m)["action"] == "move")
HO.mark(m, d["hash"], HO.MOVED, "s-two", now)
check("rules: a step handed over is not handed over twice", dec(m, mover="s-one")["action"] == "none" and "already" in dec(m, mover="s-one")["why"] and HO.handled(m, d["hash"], HO.MOVED) and not HO.handled(m, "x", HO.MOVED))
check("rules: a sub-step that names no one is not the next step", HO.next_open(meta_of("s-one: build it", "  - a detail", "s-two: check it"), "o")[1] in ("s-one",), HO.next_open(meta_of("s-one: build it", "  - a detail", "s-two: check it"), "o"))

# ---- 2. the store, the checkout and GitHub's answers
def item(i, nxt, mover="home-one", status="open", **meta):      # the mover is stored by name, as a session that writes the field stores it
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing. It lives here. Done when done.",
                                                       "status": status, "updated": now - 7200, "state_updated": now - 7200, "confirmed": now - 7200,
                                                       "metadata": {"owner": U["home-builder"], "mover": mover, "project": "projects/alpha", "next": nxt, **meta}}))
from stackshot.web import server; from stackshot.model import needs as _model_needs
from stackshot.service import telling
from stackshot.service import writes
OWNER = server.OWNER
IDS = (1, 2, 3, 4, 5, 6, 7, 8, 9)
def fixtures():
    for f in (T / "store/a").glob("*.json"): f.unlink()
    item(1, "home-one: merge PR #11\nhome-two: verify the pages")                                       # the two-session item: one's step ticks, two is next
    item(2, "home-one: merge PR #11\nhome-gone: verify the pages")                                      # the next session has no pane at all
    item(3, "home-one: merge PR #11\nhome-two: check the part\nhome-three: check the other part")        # parallel: two then three
    item(4, f"home-one: merge PR #11\n{OWNER}: pick the colour")                                        # the owner's step next: never moved to him
    item(5, "home-one: merge PR #11\nhome-builder: report it")                                          # a front agent's step next
    item(6, "home-one: merge PR #11\nnobody-here: do the rest")                                         # no such session
    item(7, "home-one: merge PR #11\nhome-one: close it out")                                           # the mover's own next step
    item(8, "home-one: merge PR #11\nhome-two: verify the pages", needs=["home-one", "home-three"])    # needs name another session beside the mover: left alone
    item(9, "home-one: write the thing\nhome-two: review it")                                            # ticked by hand
    (T / "store/next-id").write_text("60")
    (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"https://github.com/{REPO}/pull/11", "items": [f"a{i}" for i in (1, 2, 3, 4, 5, 6, 7, 8)], "added": 1, "by": "t"}]}))

genv = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": tmp}
def g(*a): return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=T / "repo", env=genv, capture_output=True, text=True, check=True).stdout.strip()
(T / "repo").mkdir(); g("init", "-q", "-b", "main"); (T / "repo/f").write_text("0"); g("add", "f"); g("commit", "-qm", "base")
g("remote", "add", "origin", f"https://github.com/{REPO}.git")
(T / "state/releases/last-good").write_text(g("rev-parse", "HEAD") + "\n")
fixtures()
logging.disable(logging.INFO)
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def raw(i): return (T / f"store/a/{i}.json").read_text()
server._publish = lambda: None
server._OWN_REPO[:] = [REPO]
server._HERE = T / "repo"
GH = {key(11): ("merged", "")}
def fake_pr_merged(ref, now_, gh_st):
    ref = server._check_ref(ref); st, err = GH.get(ref, ("open", ""))
    gh_st[ref] = {"next": now_ + 300, "back": 0.0, "err": err, "merged": st == "merged"}
    return st == "merged", err
server._pr_merged = fake_pr_merged
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []
_real_tell = telling.tell_woken
def _tell(gid, owner, note, tag="wake", result=None):
    th = _real_tell(gid, owner, note, tag, result)
    if th: THREADS.append(th)
    return th
telling.tell_woken = _tell
def drain():
    while THREADS: THREADS.pop(0).join(30)
def pushes(): drain(); return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
def pushes_for(gid, to=None): return [p for p in pushes() if p[1].startswith(f"[stackshot] {gid}") and (to is None or p[0] == U.get(to, to))]
def mover_of(i): return server._session_label(telling.holder({**rd(i), "gid": f"a{i}"}))
check("the fixture: home-builder is a front agent, home-one and home-two are background sessions with a pane, home-gone has none",
      telling.front_sender(U["home-builder"]) and server._handover_kind("home-two") == HO.SESSION and server._handover_kind("home-builder") == HO.FRONT and server._handover_kind(OWNER) == HO.OWNER
      and server._handover_kind("nobody-here") == HO.OTHER and not server._handover_down("home-two") and server._handover_down("home-gone"), (server._handover_kind("home-two"), server._handover_down("home-gone")))
s_before = {i: raw(i) for i in IDS}

# ---- 3. a two-session item end to end: one's step is ticked by its proof, two is reached with no message from anyone
d = server._sweep_proofs()
rows = {x["item"]: x for x in d["items"]}
a1 = rd(1); m1 = a1["metadata"]
check("two sessions: one's step is ticked by the server (the proof is its PR) and the step after it stays open", [(s["text"], s["status"]) for s in m1["steps"]] == [("home-one: merge PR #11", "done"), ("home-two: verify the pages", "open")]
      and m1["next"] == "home-two: verify the pages" and a1["status"] == "open", m1)
check("…the item's mover is the session the next step names, and its needs say so", mover_of(1) == "home-two" and m1.get("mover") == "home-two" and _model_needs._needs_of(m1)[:1] == ["home-two"], (m1.get("mover"), m1.get("needs")))
check("…the record says which step was handed to whom", m1.get("handover", {}).get("kind") == HO.MOVED and m1["handover"]["to"] == "home-two" and m1["handover"]["step"] == HO.step_hash("home-two: verify the pages"), m1.get("handover"))
n2 = pushes_for("a1", "home-two")
check("…home-two is told, by the server, with the step's text, that the item is its own now (nobody else sent anything)", len(n2) == 1 and "is yours" in n2[0][1] and "home-two: verify the pages" in n2[0][1]
      and "home-one: merge PR #11 is done" in n2[0][1] and "sender='home-one'" in n2[0][1], n2)
check("…the row of the pass says so", rows["a1"].get("handover", {}).get("action") == "moved" and rows["a1"]["handover"]["to"] == "home-two", rows.get("a1"))
from stackshot.audit import audit_checks as AC
known = {"home-builder", "home-one", "home-two", "home-three", "home-gone"}
ROLES = {"home-builder": {"role": "front"}, "home-one": {"role": "back"}, "home-two": {"role": "back"}, "home-three": {"role": "back"}, "home-gone": {"role": "back"}}
class _Env:
    def role_map(self): return ROLES
def audit_of(i, at=None):
    it = {**rd(i), "gid": f"a{i}"}
    f, _fl = AC.filing_findings({f"a{i}": it}, {}, at or time.time(), _Env())
    return sorted((x["category"], x.get("to", "")) for x in f)
check("…the idle path does not fire: nothing for stuck-elsewhere (the opener is the mover) and nothing for the hand-over audit", audit_of(1, now + 7200) == [], audit_of(1, now + 7200))
# the same state as before this change: the step ticked, the mover still the first session: the first open step opens with another session, and the audit would have said so
old = rd(1); old["metadata"] = {**old["metadata"], "mover": "home-one", "needs": ["home-one"]}; old["metadata"].pop("handover", None)
f_old, _x = AC.filing_findings({"a1": {**old, "gid": "a1"}}, {}, now + 7200, _Env())
check("…whereas before the hand-over that state is what the stuck-elsewhere and the hand-over audit found (the control)",
      sorted(x["category"] for x in f_old) == ["step-handover", "stuck-elsewhere"], [(x["category"], x["detail"]) for x in f_old])

# ---- 4. a session that is down: the item stays, its mover is told once, the audit names the session
a2 = rd(2); m2 = a2["metadata"]
check("down: the step is ticked and the item stays with its mover; the record says it fell back, and why", [s["status"] for s in m2["steps"]] == ["done", "open"] and mover_of(2) == "home-one"
      and m2.get("handover", {}).get("kind") == HO.FALLBACK and m2["handover"]["to"] == "home-gone" and "heartbeat" in m2["handover"]["why"], m2.get("handover"))
check("…the mover is told once what is next, that the session cannot take it, and what to do", len([p for p in pushes_for("a2", "home-one") if "cannot take the item now" in p[1]]) == 1
      and "home-gone: verify the pages" in [p for p in pushes_for("a2", "home-one") if "cannot take" in p[1]][0][1] and not pushes_for("a2", "home-gone"), pushes_for("a2"))
check("…the row says fallback", rows["a2"].get("handover", {}).get("action") == "fallback", rows.get("a2"))
fa = audit_of(2, now + 7200)
check("…and the audit names it half an hour on (the step-handover finding beside the stuck-elsewhere to the session)", ("step-handover", "") in fa, fa)
f2, _x = AC.filing_findings({"a2": {**rd(2), "gid": "a2"}}, {}, now + 7200, _Env())
sh = [x for x in f2 if x["category"] == "step-handover"][0]
check("…its evidence names the step, the session and why it could not take it, and the fix says what to do", "home-gone" in sh["detail"] and "could not take it" in sh["detail"] and sh["owner"] == "home-one" and "mover=" in sh["fix"], sh)
check("…the audit waits the grace first: a step done a minute ago is not yet a finding", "step-handover" not in [c for c, _t in audit_of(2, time.time())], audit_of(2, time.time()))

# ---- 5. parallel steps: the first open step decides, the later one in its turn
a3 = rd(3); m3 = a3["metadata"]
check("parallel: the item moves to the session of the first open step only; the later one is not told", mover_of(3) == "home-two" and len(pushes_for("a3", "home-two")) == 1 and not pushes_for("a3", "home-three"), (mover_of(3), pushes_for("a3")))
check("…both steps stay open, and the record is the first one's", [s["status"] for s in m3["steps"]] == ["done", "open", "open"] and m3["handover"]["to"] == "home-two", m3["steps"])
out = server._update("a3", sender="home-two", done=[2])
a3 = rd(3)
check("…when home-two marks its step done by hand, the item goes on to home-three and says so in the reply", mover_of(3) == "home-three" and "the next step is home-three's" in out and "home-three" in a3["metadata"].get("handover", {}).get("to", ""), (mover_of(3), out))
n3 = pushes_for("a3", "home-three")
check("…home-three is told with its step's text, by the server", len(n3) == 1 and "home-three: check the other part" in n3[0][1] and "home-two: check the part is done" in n3[0][1], n3)

# ---- 6. the owner, a front agent, no such session, the mover's own step: nothing moves
for i, who, why in ((4, "home-one", "owner"), (5, "home-one", "front agent"), (6, "home-one", "no session"), (7, "home-one", "mover's own")):
    mi = rd(i)["metadata"]
    check(f"nothing moves: item {i} ({why}): the step is ticked, the mover is {who}, no record, nobody pushed", [s["status"] for s in mi["steps"]][0] == "done" and mover_of(i) == who and "handover" not in mi
          and not pushes_for(f"a{i}", "home-two") and not pushes_for(f"a{i}", "home-builder") and not pushes_for(f"a{i}", OWNER), (mi, pushes_for(f"a{i}")))
check("item 8: needs name another session beside the mover: left alone, as a tick is", mover_of(8) == "home-one" and "handover" not in rd(8)["metadata"] and rd(8)["metadata"].get("needs") == ["home-one", "home-three"], rd(8)["metadata"])

# ---- 7. an event seen twice, a hand-over asked twice
snap = {i: raw(i) for i in IDS}; p0 = len(pushes())
server._sweep_proofs()
check("idempotent: a second pass changes no item and tells nobody", all(raw(i) == snap[i] for i in IDS) and len(pushes()) == p0, [i for i in IDS if raw(i) != snap[i]])
r = server._handover("a1", time.time(), ["home-one: merge PR #11"])
check("…a hand-over asked again for the session that holds the item does nothing", r and r["action"] == "none" and mover_of(1) == "home-two" and raw(1) == snap[1], r)
back = rd(1); back["metadata"]["mover"] = "home-one"; back["metadata"]["needs"] = ["home-one"]; (T / "store/a/1.json").write_text(json.dumps(back)); p0 = len(pushes())
r = server._handover("a1", time.time(), ["home-one: merge PR #11"])
check("…and one asked for a step on record as handed over does nothing, whoever holds the item now", r and r["action"] == "none" and "already" in r["why"] and mover_of(1) == "home-one" and len(pushes()) == p0, r)
p0 = len(pushes()); r = server._handover("a2", time.time(), ["x"])
check("…nor a second fallback (the mover was told already)", r["action"] == "none" and "told already" in r["why"] and len(pushes()) == p0, r)
(T / "fleet/a/sessions.json").write_text(json.dumps({**{U[n]: {"name": n, "machine": "a", "seen": time.time()} for n in U}, "00000000-0000-4000-8000-0000000000ff": {"name": "home-gone", "machine": "a", "seen": time.time()}}))
server._sessions_index.cache_clear() if hasattr(server._sessions_index, "cache_clear") else None
r = server._handover("a2", time.time(), ["home-one: merge PR #11"])
check("…and a session that came back is handed the item the next time the hand-over is asked (a fallback is not a final answer)", r["action"] == "moved" and mover_of(2) == "home-gone" and rd(2)["metadata"]["handover"]["kind"] == HO.MOVED, r)
(T / "fleet/a/sessions.json").write_text(json.dumps({U[n]: {"name": n, "machine": "a", "seen": time.time()} for n in U}))

# ---- 8. a step marked done by hand
fixtures(); p0 = len(pushes())
out = server._update("a9", sender="home-one", done=[1])
check("by hand: the step marked done hands the item to the session of the next step, the reply says so, and it is told", mover_of(9) == "home-two" and "the next step is home-two's" in out and len(pushes_for("a9", "home-two")) == 1
      and rd(9)["metadata"]["handover"]["kind"] == HO.MOVED, (mover_of(9), out))
fixtures()
server._update("a9", sender="home-one", done=[1], mover="home-three")
check("by hand: a write that names the mover makes its own hand-off, and this one does not move the item again", mover_of(9) == "home-three" and "handover" not in rd(9)["metadata"], rd(9)["metadata"])
fixtures()
server._update("a9", sender="home-one", done=[1], needs=["home-one"])
check("by hand: a write that sets needs is left alone", mover_of(9) == "home-one" and "handover" not in rd(9)["metadata"], rd(9)["metadata"])
fixtures()
server._update("a9", sender="home-one", next="home-one: write the thing\nhome-two: review it\nhome-one: wrap up")
check("by hand: a write that marks no step done hands nothing over", mover_of(9) == "home-one" and "handover" not in rd(9)["metadata"], rd(9)["metadata"])
fixtures(); n9 = len(pushes_for("a9", "home-two"))
server._update("a9", sender="home-one", done=[1, 2])
check("by hand: marking every open step done leaves no step to hand over: no record, no notice, the mover is the same", "handover" not in rd(9)["metadata"] and len(pushes_for("a9", "home-two")) == n9 and mover_of(9) == "home-one", (rd(9)["metadata"], pushes_for("a9")))

# ---- 9. the write check: a step that delivers a pull request and has another session's step after it needs its proof
def refused(name, fn, *want):
    try:
        with writes.session_write(): fn()
        check(name, False, "no refusal")
    except server.ToolError as e: check(name, str(e).startswith("Refused:") and "\n" not in str(e) and all(w in str(e) for w in want), str(e))
def accepts(name, fn):
    try:
        with writes.session_write(): fn()
        check(name, True)
    except server.ToolError as e: check(name, False, str(e))
def mk(nxt, **kw): return lambda: server._create(subject="[home] made", description="- Goal: a thing works. It lives here.", project="projects/alpha", owner="home-builder", mover="home-one", next=nxt, **kw)
refused("write check: a create whose step delivers a PR and is followed by another session's step is refused with the one-line fix",
        mk("home-one: merge PR #12 and restart the unit\nhome-two: verify the pages"), "step 1", "delivers #12", "another session's step follows", 'step_proof=[{"step": 1, "proof": "pr_merged #12"}]')
accepts("…the same create with the proof passes", mk("home-one: merge PR #12 and restart the unit\nhome-two: verify the pages", step_proof=[{"step": 1, "proof": "pr_merged #12"}]))
accepts("…a step that is only the merge phrase is its own proof", mk("home-one: merge PR #13\nhome-two: verify the pages"))
accepts("…a step that names no pull request is not judged (a proof needs one, which a create may not have yet)", mk("home-one: open the pull request and merge it\nhome-two: verify the pages"))
accepts("…a delivery step followed by the same session's step is not judged", mk("home-one: merge PR #14 and restart the unit\nhome-one: verify the pages"))
accepts("…nor one followed by the owner's step", mk(f"home-one: merge PR #15 and restart the unit\n{OWNER}: pick the colour"))
refused("…a release step with a follow-up, a URL and a second gap: the first is named and the count of the rest", mk("home-one: release #16 and restart\nhome-two: ship PR #17 and tell\nhome-three: verify"),
        "step 1", "delivers #16", 'step_proof=[{"step": 1, "proof": "pr_released #16"}]', "(and 1 more step)")
_scr = lambda: server._create(subject="[home] made by a script", description="- Goal: a thing works. It lives here.", project="projects/alpha", owner="home-builder",
                                                                                 mover="home-one", next="home-one: merge PR #18 and restart the unit\nhome-two: verify the pages")
try: _scr(); check("…a script's write (no session's) is not judged", True)
except server.ToolError as e: check("…a script's write (no session's) is not judged", False, str(e))
fixtures()
item(20, "home-one: write the fix")
refused("write check: an update that adds such a step is refused the same way", lambda: server._update("a20", sender="home-one", check="pr_merged example-owner/stackshot#11", next="home-one: write the fix\nhome-one: merge PR #19 and restart\nhome-two: verify the pages"), "step 2", "delivers #19")
accepts("…and passes with the proof", lambda: server._update("a20", sender="home-one", check="pr_merged example-owner/stackshot#11", next="home-one: write the fix\nhome-one: merge PR #19 and restart\nhome-two: verify the pages", step_proof=[{"step": 2, "proof": "pr_merged #19"}]))
item(21, "home-one: merge PR #22 and restart\nhome-two: verify the pages")        # a step written before the check: an update that leaves it alone is not refused for it
accepts("…a step that was there before the write is not judged again by a write that leaves it alone", lambda: server._update("a21", sender="home-one", description="- Goal: a thing works. It lives here, really."))

# the delivery must be the step's own leading action: a reviewer, a verifier, a waiter and a checker are no delivery
for words in ("review the release PR #7 for the notes", "verify the release PR #7 is live", "check merge #7 conflicts"):
    accepts(f"write check: `{words}` before another session's step is no delivery step and is not refused", mk(f"home-one: {words}\nhome-two: verify the pages"))
refused("…`then merge PR #23 and restart` is one", mk("home-one: then merge PR #23 and restart the unit\nhome-two: verify the pages"), "step 1", "delivers #23")
from stackshot.model import step_proof as _SP
check("delivers: the leading verb only", [_SP.delivers(t) for t in ("a: review the release PR #7", "a: merge PR #7 and restart", "a: wait for merge #7", "a: check merge #7 conflicts", "a: Merge #7.", "a: ship PR #7 and tell", "a: land #7",
                                                                       "a: please release #7 and verify", "a: wait for the release PR #7 to merge")]
      == [("", ""), ("pr_merged", "#7"), ("", ""), ("", ""), ("pr_merged", "#7"), ("pr_released", "#7"), ("pr_merged", "#7"), ("pr_released", "#7"), ("", "")], None)
refused("the refusal says to split the step as well as to pass the proof, in one line", mk("home-one: merge PR #12 and restart the unit\nhome-two: verify the pages"), "split it so `merge PR #12` is a step of its own", "or, if the PR landing finishes the step, add step_proof=")
_st = lambda *t: [{"text": x, "status": "open"} for x in t]
_gap = lambda own, *t: _SP.proof_gaps(_st(*t), {}, server._steps.opener, lambda a, b: a == b, server._steps.key, own=own)
check("…a release of a URL naming another repository is given a merge proof (only this repository's PRs are released); this repository's keeps the release proof",
      _gap("o/q", "home-one: release https://github.com/o/r/pull/9 and restart", "home-two: x") == [(1, "https://github.com/o/r/pull/9", "pr_merged https://github.com/o/r/pull/9")]
      and _gap("o/r", "home-one: release https://github.com/o/r/pull/9 and restart", "home-two: x") == [(1, "https://github.com/o/r/pull/9", "pr_released https://github.com/o/r/pull/9")], _gap("o/q", "home-one: release https://github.com/o/r/pull/9 and restart", "home-two: x"))
check("…and a repository listed as released keeps the release proof, with the plain URL and with `release PR <URL>`; one not listed still gets the merge proof",
      _SP.proof_gaps(_st("home-one: release PR https://github.com/o/r/pull/9 and restart", "home-two: x"), {}, server._steps.opener, lambda a, b: a == b, server._steps.key, own="o/q", released={"o/r"})
      == [(1, "https://github.com/o/r/pull/9", "pr_released https://github.com/o/r/pull/9")]
      and _SP.proof_gaps(_st("home-one: release PR https://github.com/o/r/pull/9 and restart", "home-two: x"), {}, server._steps.opener, lambda a, b: a == b, server._steps.key, own="o/q", released={"o/s"})
      == [(1, "https://github.com/o/r/pull/9", "pr_merged https://github.com/o/r/pull/9")], None)
check("…`release PR <URL>` is a release phrase of its own (pure when it is all the step does), as `release <URL>` is",
      _SP.text_proofs("home-one: release PR https://github.com/o/r/pull/9") == _SP.text_proofs("home-one: release https://github.com/o/r/pull/9")
      and [(p.kind, p.url, p.pure) for p in _SP.text_proofs("release pull request https://github.com/o/r/pull/9 and restart")] == [("pr_released", "https://github.com/o/r/pull/9", False)], None)
refused("…a bare #n tells the writer what to pass for another repository's PR", mk("home-one: release #9 and restart\nhome-two: verify the pages"), "pr_released #9", "another repository's PR: pr_merged <owner>/<repo>#<n>")

# ---- 10. the audit: a missing proof; the page key for a front mover; a repeat only after an item write
fixtures()
item(30, "home-one: merge PR #24 and restart the unit\nhome-two: verify the pages")
f30, _x = AC.filing_findings({"a30": {**rd(30), "gid": "a30"}}, {}, time.time(), _Env())
sh = [x for x in f30 if x["category"] == "step-handover"]
check("audit: a delivery step with no proof before another session's step is found, with the step, the PR and what it means", len(sh) == 1 and "step 1" in sh[0]["detail"] and "#24" in sh[0]["detail"] and "has no proof" in sh[0]["detail"]
      and sh[0]["fix"] == AC.FIX["step-handover"] and sh[0]["mover"] == "home-one", sh)
item(31, "home-one: merge PR #25\nhome-two: verify the pages")
item(32, "home-one: merge PR #26 and restart\nhome-two: verify the pages", step_proof={"home-one: merge PR #26 and restart": f"pr_merged {key(26)}"})
item(33, f"home-one: merge PR #27 and restart\n{OWNER}: pick")
item(34, "home-one: merge PR #28 and restart\nhome-nobody: verify")
fs, _x = AC.filing_findings({f"a{i}": {**rd(i), "gid": f"a{i}"} for i in (31, 32, 33, 34)}, {}, time.time(), _Env())
check("audit: …not found for a pure step, one with a stored proof, one followed by the owner's step or by a name no role map knows", [x for x in fs if x["category"] == "step-handover"] == [], [(x["id"], x["detail"]) for x in fs])
# a done step whose next session was never reached: ticked by the server long ago, mover unchanged, no record
item(35, "home-one: the first part\nhome-two: the second part", steps=[{"text": "home-one: the first part", "status": "done", "by": server.NAME, "at": now - 7200}, {"text": "home-two: the second part", "status": "open", "by": "", "at": 0}])
sh = [x for x in AC.filing_findings({"a35": {**rd(35), "gid": "a35"}}, {}, now, _Env())[0] if x["category"] == "step-handover"]
check("audit: a next session never reached after a done step is found half an hour on, with no hand-over on record", len(sh) == 1 and "home-two" in sh[0]["detail"] and "no hand-over to home-two is on record" in sh[0]["detail"] and sh[0]["mover"] == "home-one", sh)
mm = rd(35); mm["metadata"]["handover"] = {"step": HO.step_hash("home-two: the second part"), "kind": HO.MOVED, "to": "home-two", "at": now}
check("audit: …not found once the record says it was handed over", not [x for x in AC.filing_findings({"a35": {**mm, "gid": "a35"}}, {}, now, _Env())[0] if x["category"] == "step-handover"])
mf = rd(35); mf["metadata"]["steps"][0]["by"] = "someone else"
check("audit: …nor when the last step was marked by another session (it is that session's to hand on)", not [x for x in AC.filing_findings({"a35": {**mf, "gid": "a35"}}, {}, now, _Env())[0] if x["category"] == "step-handover"])
mn = rd(35); mn["metadata"]["steps"][0]["at"] = now - 60
check("audit: …nor a minute after the step was done", not [x for x in AC.filing_findings({"a35": {**mn, "gid": "a35"}}, {}, now, _Env())[0] if x["category"] == "step-handover"])
mv = rd(35); mv["metadata"]["next"] = "home-builder: the second part"; mv["metadata"]["steps"][1]["text"] = "home-builder: the second part"
check("audit: …nor when the next step is a front agent's (the front-step rule moves it on)", not [x for x in AC.filing_findings({"a35": {**mv, "gid": "a35"}}, {}, now, _Env())[0] if x["category"] == "step-handover"])

base35 = rd(35)
for what, extra in (("on hold", {"hold": True, "wake": "2099-01-02"}), ("waiting on a decision", {"needs": ["decision"], "ask": "Ship it?"}), ("with needs that name another session", {"needs": ["home-one", "home-three"]})):
    mx = json.loads(json.dumps(base35)); mx["metadata"].update(extra)
    got = [x for x in AC.filing_findings({"a35": {**mx, "gid": "a35"}}, {}, now, _Env())[0] if x["category"] == "step-handover"]
    check(f"audit: an item {what} is left alone, as the server leaves it (no 'not reached' finding)", got == [], got)
    check(f"…and the server says why in the same words (one shared rule)", HO.skip_reason(mx["metadata"], "home-one", lambda a, b: a == b, str, "the owner") != "", None)
mx = json.loads(json.dumps(base35)); mx["metadata"]["needs"] = ["home-one"]
check("audit: needs naming only the mover is no skip: the finding stays", len([x for x in AC.filing_findings({"a35": {**mx, "gid": "a35"}}, {}, now, _Env())[0] if x["category"] == "step-handover"]) == 1)

# delivery: to the mover; a front mover through the page key; repeated only after an item write
from stackshot.audit import audit_run as AR
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(**kw):
    kw.setdefault("pages", lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})
    return AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None), deliver=deliver, sessions=lambda: None, **kw)
for p in (T / "state/audit").glob("*.json"): p.unlink()
fixtures()
item(40, "home-one: the first part\nhome-two: the second part", steps=[{"text": "home-one: the first part", "status": "done", "by": server.NAME, "at": now - 7200}, {"text": "home-two: the second part", "status": "open", "by": "", "at": 0}])
item(41, "home-one: the first part\nhome-two: the second part", mover="home-builder", steps=[{"text": "home-one: the first part", "status": "done", "by": "home-builder", "at": now - 7200}, {"text": "home-two: the second part", "status": "open", "by": "", "at": 0}])
items = {f"a{i}": {**rd(i), "gid": f"a{i}"} for i in (40, 41)}
r1 = AR.filing_pass(now=now, items=items, anchors={}, env=env())
to40 = [t for to, t, _f in sent if "board#40" in t and "step-handover" in t]
to41 = [(to, t) for to, t, _f in sent if "board#41" in t and "step-handover" in t]
check("audit delivery: the finding goes to the mover through the existing path, headed as a filing check", len(to40) == 1 and any(to == "home-one" for to, t, _f in sent if "board#40" in t), sent)
check("…a front mover's finding goes to the project's page key, not to the front agent", len(to41) == 1 and to41[0][0] == "projects/alpha" and not any(to == "home-builder" for to, _t, _f in sent), sent)
sent.clear()
r2 = AR.filing_pass(now=now + 600, items=items, anchors={}, env=env())
check("…a second pass ten minutes on sends nothing", not sent and r2["fresh"] == 0, (sent, r2))
fresher = dict(items); fresher["a40"] = {**items["a40"], "written_at": time.time() + 60, "written_by": "home-one"}
r3 = AR.filing_pass(now=now + 1200, items=fresher, anchors={}, env=env())
check("…and after a write to the item it is sent again (its two findings), and the other item's is not", r3["fresh"] == 2 and sent and all("board#40" in t and "board#41" not in t for _to, t, _f in sent), (r3, sent))

print(f"{len(ran) - len(fails)}/{len(ran)} passed" + (f" — FAILED: {', '.join(fails)}" if fails else ""))
sys.exit(1 if fails else 0)
