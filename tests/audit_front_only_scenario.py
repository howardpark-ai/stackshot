"""Scenario test for where the audit sends a project's unmoved findings and its unmoved digest (audit_run.Env.chase_of, audit_run.deliver_findings, the unmoved digest of audit_run.run): a front-only
project (anchors.front_only: its `agents:` map lists no `background:` agent) has no builder to chase, so both go to its -main agent, marked for the owner as every message to a front agent is; a project with
a builder is unchanged. Fixture data (English stand-in names) in a temporary store, messages replaced by recorders, no network, no model call.

  1  the choice on its own (Env.chase_of): a front-only project with a -main agent -> (that agent, front); a project with a builder -> (the builder, not front); a front-only project whose -main agent cannot
     be named -> ([audit] builder, not front) with one line on stderr per project; a finding with no project, a front-only test that raises and a -main read that raises keep the builder; an environment
     that names the builder itself says the project has one (no test made); with the registry in hand the test and the -main agent are read from it (the default path, no front_only= given)
  2  the finding that stayed unanswered (the filing pass, three sends, then the escalation): a front-only project's goes to its -main agent, marked `[for <owner>]`, and the level after it (the message to -main
     for a finding that went to a builder) is not sent, as -main has been told; a project with a builder's goes to the builder unmarked and then on to -main, as before; a front-only project with no -main
     agent goes to [audit] builder as before
  3  the unmoved digest (the daily run): the same split, one message per recipient, marked for the owner when it goes to a front agent; a digest that is not delivered leaves the item unchased
  4  the two lows of the review of that change: (a) a session that is a front-only project's -main agent and another project's builder gets one message of each kind (the mark is keyed by recipient AND
     whether it is a front agent, not by the recipient alone), for the unanswered finding and for the digest; (b) the digest never tells a -main agent to chase itself: when the mover of a front-only
     project's unmoved item is its -main agent, the page key takes it, unmarked, as at the finding's first level (chase_to); (c) the ordinary findings of one run are grouped by (recipient, front) too, so
     one session that gets an owner-decision finding as a project's -main agent and a finding for an item it moves in another project gets two messages, only the first marked; (d) so are the page agent
     lines (page_agent_groups): a line that names a background session and a line that falls to the audit's -main agent are two groups when that agent is the same session

    tests/run-suite audit_front_only        -> exit 0 / 1"""
import contextlib, copy, datetime as dt, io, json, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="auditfo-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))

toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
for key, val in (("agent", "falcon-audit"), ("builder", "falcon-engineer"), ("main", "falcon-main")):
    toml, n = re.subn(rf"(?m)^{key} = \"my-[a-z]+\"", f"{key} = \"{val}\"", toml); assert n == 1, key
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                              # an isolated HOME: the pane registry is a folder of ours
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state"): (T / d).mkdir(parents=True)
(T / "store/anchors.json").write_text("{}"); (T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("1")
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))

from stackshot.core import config as _cfg; from stackshot.audit import audit_run as AR; from stackshot.audit import audit_checks as AC
H = 3600; now = time.time()
ZONE_OFFSET = 4 * H                       # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
ZONE = dt.timezone(dt.timedelta(seconds=ZONE_OFFSET))
if min((now + ZONE_OFFSET) % 86400, 86400 - (now + ZONE_OFFSET) % 86400) < 600: now -= 900
OWNER = "00000000-0000-4000-8000-000000000001"
_cfg.CFG["audit"]["pattern_review"] = "off"
_cfg.CFG["audit"]["mode"] = "script"
B = "board" + "#"                             # an item id as the board writes it
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

STORE = T / "store/a"
def path(k): return STORE / f"{k[1:]}.json"
def put(k, d): path(k).write_text(json.dumps(d), encoding="utf-8")
def wipe_store():
    for p in STORE.glob("*.json"): p.unlink()
def clear_state():
    for p in (T / "state/audit").glob("*.json"): p.unlink()
def item(i, project, status="open", wrote=None, **meta):
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": status, "updated": now - H if wrote is None else wrote,
         "state_updated": now - H, "confirmed": now - H, "metadata": {"owner": OWNER, "project": project, **meta}}
    if wrote is not None: d["written_at"] = wrote; d["written_by"] = "home-agent"
    return f"a{i}", d
def doing(i, project, nxt, needs=("home-agent",), **kw): return item(i, project, wrote=now - H, state="doing", needs=list(needs), next=nxt, **kw)

SOLO, BUILT, ORPHAN = "projects/solo", "projects/built", "projects/orphan"      # a front-only project with a -main agent; one with a builder; a front-only one with no -main agent
MAINS = {SOLO: "solo-main", BUILT: "built-main"}
BUILDERS = {BUILT: "built-builder"}
FRONT_ONLY = {SOLO: True, BUILT: False, ORPHAN: True}
ROLES = {"home-agent": {"role": "background"}, "ops-other": {"role": "background"}, "solo-main": {"role": "front"}, "built-main": {"role": "front"}, "built-builder": {"role": "background"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(**kw):
    kw.setdefault("pages", lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})
    kw.setdefault("sessions", lambda: None)
    kw.setdefault("orphans", lambda apply: {"checked": True, "applied": apply, "read": 0, "found": 0, "moved": [], "left": []})
    kw.setdefault("clock", lambda: 0.0)         # the pass time is the test's own `now`: never the real clock
    return AR.Env(roles=kw.pop("roles", ROLES), fallback=lambda p: MAINS.get(p, ""), builder=lambda p: BUILDERS.get(p, ""), page_of=lambda p: ("", None),
                  front_only=kw.pop("front_only", lambda p: FRONT_ONLY.get(p, False)), deliver=kw.pop("deliver", deliver), **kw)
def said(to): return [t for t_, t, _f in sent if t_ == to]

# ---------------------------------------------------------------- 1. the choice on its own
err = io.StringIO()
with contextlib.redirect_stderr(err):
    e = env()
    got = {p: e.chase_of(p) for p in (SOLO, BUILT, ORPHAN, "")}
    e.chase_of(ORPHAN); e.chase_of(ORPHAN)       # asked again: said once
check("1 a front-only project with a -main agent -> that agent, a front agent", got[SOLO] == ("solo-main", True), got)
check("1 a project with a builder -> the builder, not a front agent", got[BUILT] == ("built-builder", False), got)
check("1 a front-only project whose -main agent cannot be named -> [audit] builder, not a front agent", got[ORPHAN] == ("falcon-engineer", False), got)
check("1 …and says so once on stderr, naming the project", err.getvalue().count("projects/orphan is front-only but names no -main agent") == 1 and "projects/solo" not in err.getvalue(), err.getvalue())
check("1 a finding with no project keeps the builder path (no front-only test)", got[""] == ("falcon-engineer", False), got)
with contextlib.redirect_stderr(io.StringIO()) as err2:
    boom = env(front_only=lambda p: 1 / 0).chase_of(SOLO)
    no_main = AR.Env(roles=ROLES, fallback=lambda p: 1 / 0, builder=lambda p: "x-builder", front_only=lambda p: True).chase_of(SOLO)
check("1 a front-only test that raises keeps the builder, and says so", boom == ("falcon-engineer", False) and "front-only test of projects/solo failed" in err2.getvalue(), (boom, err2.getvalue()))
check("1 a -main read that raises is a -main agent that cannot be named: the builder", no_main == ("x-builder", False), no_main)
check("1 an environment that names the builder itself (no front_only= given) says the project has one: no test is made",
      AR.Env(roles=ROLES, fallback=lambda p: "solo-main", builder=lambda p: "named-builder").chase_of(SOLO) == ("named-builder", False))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
REG = {SOLO: page(agents={"solo-main": "front"}),
       BUILT: page(agents={"built-main": "front", "built-builder": "builds it"}, back_agents={"built-builder": "builds it"})}
reg_env = AR.Env(roles=ROLES, registry=lambda: REG, sessions=lambda: None, page_of=lambda p: ("", None), deliver=deliver)
check("1 with the registry in hand and no front_only= given, the map decides: a map of front agents -> its -main agent", reg_env.chase_of(SOLO) == ("solo-main", True), reg_env.chase_of(SOLO))
check("1 …and a map with a background agent is not front-only: the builder pick (here none is found, so [audit] builder), not the -main agent",
      reg_env.chase_of(BUILT) == (reg_env.builder_of(BUILT), False) and reg_env.chase_of(BUILT)[0] != "built-main", reg_env.chase_of(BUILT))

# ---------------------------------------------------------------- 2. a finding nobody answered (the filing pass: three sends, then the escalation)
M = 60; REM = 6 * H
_cfg.CFG["audit"]["remind_hours"] = 6
def fixtures():
    wipe_store(); clear_state(); sent.clear()
    for i, p in ((9101, SOLO), (9102, BUILT), (9103, ORPHAN)):
        k, d = doing(i, p, "ops-other: do the first part\nhome-agent: then the second"); put(k, d)       # a background agent's step: the finding goes to that agent, and nobody answers
fixtures()
tk = now
for n in range(3):
    sent.clear(); AR.filing_pass(now=tk, env=env()); tk += REM + 60
check("2 the sends before the escalation went to the agent whose step it is, in every project alike (the last one lists the three items)", all(f"{B}{i}" in "".join(said("ops-other")) for i in (9101, 9102, 9103)), sent)
sent.clear(); AR.filing_pass(now=tk, env=env())
unmoved = lambda to: [t for t in said(to) if "unmoved after 3 messages" in t]
solo_u, built_u, orphan_u = unmoved("solo-main"), unmoved("built-builder"), unmoved("falcon-engineer")
check("2 a front-only project's finding goes to its -main agent as unmoved, marked for the owner", len(solo_u) == 1 and solo_u[0].startswith("[for Oliver]\n") and B + "9101" in solo_u[0] and "chase the mover (job)" in solo_u[0], solo_u)
check("2 …and not to the builder of any project, nor to the global audit builder", B + "9101" not in "".join(said("built-builder") + said("falcon-engineer")), sent)
check("2 a project with a builder: its builder, unmarked, as before", len(built_u) == 1 and not built_u[0].startswith("[for") and B + "9102" in built_u[0] and B + "9101" not in built_u[0] and B + "9103" not in built_u[0], built_u)
check("2 a front-only project with no -main agent: the global audit builder, unmarked, as before", len(orphan_u) == 1 and not orphan_u[0].startswith("[for") and B + "9103" in orphan_u[0], orphan_u)
check("2 …and nobody else is told at this level", {to for to, _t, _f in sent} == {"solo-main", "built-builder", "falcon-engineer"}, [to for to, _t, _f in sent])
sent.clear(); AR.filing_pass(now=tk + 10 * M, env=env())
check("2 …nothing more before the next remind_hours", sent == [], sent)
tk += REM + 60; sent.clear(); AR.filing_pass(now=tk, env=env())
up = {to: t for to, t, _f in sent}
check("2 the next level (-main told of a finding that went to a builder): the project with a builder's -main agent is told once, marked for the owner",
      "built-main" in up and up["built-main"].startswith("[for Oliver]\n") and B + "9102" in up["built-main"] and "nobody answered after" in up["built-main"], up)
check("2 …a front-only project's -main agent is not told a second time (it had the finding already)", "solo-main" not in up, [(to, t[:80]) for to, t in up.items()])
check("2 …and a front-only project with no -main agent keeps the old second level: [audit] main, marked, the builder named as having had it", "falcon-main" in up and B + "9103" in up["falcon-main"], up)
sent.clear()
for k in range(1, 4): AR.filing_pass(now=tk + k * (REM + 60), env=env())
check("2 …then everything is quiet until the items are written", sent == [], sent)

# ---------------------------------------------------------------- 3. the unmoved digest (the daily run)
wipe_store(); clear_state(); sent.clear()
prev_day = dt.datetime.fromtimestamp(now - 2 * 86400, ZONE).date().isoformat()
(T / "state/audit").mkdir(parents=True, exist_ok=True)
(T / "state/audit" / f"run-{prev_day}.json").write_text(json.dumps({"started": now - 2 * 86400, "finished": now - 2 * 86400 + 60, "items_read": 10, "by_session": {}, "by_category": {},
      "findings": [{"id": f"{B}{i}", "project": p, "owner": "home-agent", "mover": "home-agent", "category": "stale", "detail": f"flagged on {p}"} for i, p in ((1, SOLO), (2, BUILT), (3, ORPHAN))]}))
for i, p in ((1, SOLO), (2, BUILT), (3, ORPHAN)):
    k, d = item(i, p, wrote=now - 3 * 86400, state="doing", needs=["home-agent"], next="home-agent: build it", expected_by=dt.datetime.fromtimestamp(now + 30 * H, ZONE).strftime("%Y-%m-%d %H:%M"), expected_reason="the build runs overnight")
    d["updated"] = now - 3 * 86400; put(k, d)
_cfg.CFG["router"] = {"shadow": True, "command": [sys.executable, "-c", "import sys; sys.exit(3)"], "timeout_seconds": 20, "login_shell": False}     # no model call is made here; a call would fail
with contextlib.redirect_stderr(io.StringIO()):
    sent.clear(); rec = AR.run(now=now, items={f"a{i}": json.loads(path(f"a{i}").read_text()) for i in (1, 2, 3)}, anchors={}, env=env(), rubric="rubric")
digest = lambda to: [t for t in said(to) if "still unmoved since an earlier run" in t]
check("3 the digest names each item once, on the record's `stuck`, chased", sorted((s["id"], s["chased"]) for s in rec["stuck"]) == [(B + "1", True), (B + "2", True), (B + "3", True)], rec["stuck"])
check("3 a front-only project's item goes to its -main agent, marked for the owner, and to no builder", len(digest("solo-main")) == 1 and digest("solo-main")[0].startswith("[for Oliver]\n") and B + "1 · unmoved since " in digest("solo-main")[0]
      and B + "1" not in "".join(digest("built-builder") + digest("falcon-engineer")), [(to, t[:90]) for to, t, _f in sent])
check("3 a project with a builder: its builder, unmarked, with its own item only", len(digest("built-builder")) == 1 and not digest("built-builder")[0].startswith("[for") and B + "2" in digest("built-builder")[0] and B + "1" not in digest("built-builder")[0] and B + "3" not in digest("built-builder")[0], digest("built-builder"))
check("3 a front-only project with no -main agent: the global audit builder, unmarked, with its own item only", len(digest("falcon-engineer")) == 1 and not digest("falcon-engineer")[0].startswith("[for") and B + "3" in digest("falcon-engineer")[0] and B + "2" not in digest("falcon-engineer")[0], digest("falcon-engineer"))
check("3 the record's messages say who was sent which digest", sorted((m["to"], m["lines"], m["delivered"]) for m in rec["messages"] if m.get("kind") == "unmoved") == [("built-builder", 1, True), ("falcon-engineer", 1, True), ("solo-main", 1, True)], [m for m in rec["messages"] if m.get("kind") == "unmoved"])

def refuse_main(to, text, fyi=False):
    sent.append((to, text, fyi)); return (False, "[400] no") if to == "solo-main" else (True, "[200] ok")
clear_state(); (T / "state/audit" / f"run-{prev_day}.json").write_text(json.dumps({"started": now - 2 * 86400, "finished": now - 2 * 86400 + 60, "items_read": 10, "by_session": {}, "by_category": {},
      "findings": [{"id": B + "1", "project": SOLO, "owner": "home-agent", "mover": "home-agent", "category": "stale", "detail": "flagged"}]}))
with contextlib.redirect_stderr(io.StringIO()):
    sent.clear(); rx = AR.run(now=now, items={"a1": json.loads(path("a1").read_text())}, anchors={}, env=env(deliver=refuse_main), rubric="rubric")
check("3 a digest to -main that is not delivered leaves the item unchased, and the record says so", [(s["id"], s["chased"]) for s in rx["stuck"]] == [(B + "1", False)]
      and any(m.get("kind") == "unmoved" and m["to"] == "solo-main" and m["delivered"] is False for m in rx["messages"]), (rx["stuck"], rx["messages"]))

# ---------------------------------------------------------------- 4. the two lows: the mark is keyed by (recipient, front); the digest never tells a -main agent to chase itself
SHARED = "projects/shared"       # a project with a builder that is the -main agent of SOLO as well: one session, a front agent for one project and a builder for another
MAINS[SHARED] = "shared-main"; BUILDERS[SHARED] = "solo-main"; FRONT_ONLY[SHARED] = False
ROLES["shared-main"] = {"role": "front"}
wipe_store(); clear_state(); sent.clear()
for i, p in ((9201, SOLO), (9202, SHARED)):
    k, d = doing(i, p, "ops-other: do the first part\nhome-agent: then the second"); put(k, d)
tk = now
for n in range(3):
    sent.clear(); AR.filing_pass(now=tk, env=env()); tk += REM + 60
sent.clear(); AR.filing_pass(now=tk, env=env())
to_sm = [t for t in said("solo-main") if "unmoved after 3 messages" in t]
marked = [t for t in to_sm if t.startswith("[for Oliver]\n")]; plain = [t for t in to_sm if not t.startswith("[for Oliver]")]
check("4a one session, two kinds of recipient: the unanswered findings make two messages to it, one for each project", len(to_sm) == 2, [t[:70] for t in to_sm])
check("4a …the one for the project it is -main of is marked for the owner and holds only that project's item", len(marked) == 1 and B + "9201" in marked[0] and B + "9202" not in marked[0], marked)
check("4a …the one for the project it builds is not marked and holds only that project's item (it was marked before: the mark followed the recipient's name)", len(plain) == 1 and B + "9202" in plain[0] and B + "9201" not in plain[0], plain)

wipe_store(); clear_state(); sent.clear()
(T / "state/audit" / f"run-{prev_day}.json").write_text(json.dumps({"started": now - 2 * 86400, "finished": now - 2 * 86400 + 60, "items_read": 10, "by_session": {}, "by_category": {},
      "findings": [{"id": f"{B}{i}", "project": p, "owner": "home-agent", "mover": mv, "category": "stale", "detail": f"flagged on {p}"}
                   for i, p, mv in ((11, SOLO, "home-agent"), (12, SHARED, "home-agent"), (13, SOLO, "solo-main"))]}))
for i, p, mv in ((11, SOLO, "home-agent"), (12, SHARED, "home-agent"), (13, SOLO, "solo-main")):
    k, d = item(i, p, wrote=now - 3 * 86400, state="doing", needs=[mv], next=f"{mv}: build it", expected_by=dt.datetime.fromtimestamp(now + 30 * H, ZONE).strftime("%Y-%m-%d %H:%M"), expected_reason="the build runs overnight")
    d["updated"] = now - 3 * 86400; put(k, d)
with contextlib.redirect_stderr(io.StringIO()):
    sent.clear(); rec4 = AR.run(now=now, items={f"a{i}": json.loads(path(f"a{i}").read_text()) for i in (11, 12, 13)}, anchors={}, env=env(), rubric="rubric")
dg = [(to, t) for to, t, _f in sent if "still unmoved since an earlier run" in t]
dg_sm = [t for to, t in dg if to == "solo-main"]
check("4a the digest too: two messages to the session that is -main of one project and the builder of another, the first marked and holding its own item, the other not and holding its own",
      len(dg_sm) == 2 and sum(t.startswith("[for Oliver]\n") for t in dg_sm) == 1
      and any(t.startswith("[for Oliver]\n") and B + "11 · " in t and B + "12 · " not in t for t in dg_sm) and any(not t.startswith("[for") and B + "12 · " in t and B + "11 · " not in t for t in dg_sm), [(to, t[:90]) for to, t in dg])
check("4b the digest never tells a -main agent to chase itself: the item its -main agent moves goes to the project's page key, unmarked, and not to the -main agent",
      any(to == SOLO and not t.startswith("[for") and B + "13 · " in t for to, t in dg) and not any(B + "13 · " in t for t in dg_sm), [(to, t[:90]) for to, t in dg])
check("4b …the other item of that project still goes to its -main agent", any(to == "solo-main" and B + "11 · " in t for to, t in dg), [(to, t[:90]) for to, t in dg])
check("4b …and the record says who was sent which digest, the item chased once", sorted(s["chased"] for s in rec4["stuck"]) == [True, True, True]
      and sorted((m["to"], m["lines"]) for m in rec4["messages"] if m.get("kind") == "unmoved") == [(SOLO, 1), ("solo-main", 1), ("solo-main", 1)], [m for m in rec4["messages"] if m.get("kind") == "unmoved"])

# 4c: ordinary findings (deliver_findings' groups) are keyed by (recipient, front): "dual" is the -main agent of DUALP (an owner-decision finding goes to it, marked) and moves an item of BUILT (its finding goes to it, unmarked)
DUALP = "projects/dualp"
MAINS[DUALP] = "dual"; FRONT_ONLY[DUALP] = True; ROLES["dual"] = {"role": "background"}
sent.clear()
fnd = [{"id": f"{B}9301", "project": DUALP, "to": "Oliver", "mover": "", "category": "stale", "detail": "an item that waits on his answer", "fix": "answer it"},
       {"id": f"{B}9302", "project": BUILT, "to": "dual", "mover": "dual", "category": "stale", "detail": "an item it moves", "fix": "write it"}]
with contextlib.redirect_stderr(io.StringIO()):
    AR.deliver_findings(env(), fnd, "Board audit test")
to_dual = [t for to, t, _f in sent if to == "dual"]
check("4c one session, two kinds of ordinary finding: two messages to it, one marked for the owner and one not", len(to_dual) == 2 and sum(t.startswith("[for Oliver]\n") for t in to_dual) == 1, [t[:80] for t in to_dual])
check("4c …the marked one holds only the finding it got as -main agent, the unmarked one only the finding for the item it moves (one message of both, marked by the first finding's kind, before)",
      any(t.startswith("[for Oliver]\n") and B + "9301" in t and B + "9302" not in t for t in to_dual) and any(not t.startswith("[for") and B + "9302" in t and B + "9301" not in t for t in to_dual), [t[:120] for t in to_dual])

# 4d: page agent lines (page_agent_groups) are keyed by (recipient, front): "falcon-main" is the audit's -main agent and also a background session a page line names
pa_res = {"findings": [{"to": "falcon-main", "page": "projects/pa-one", "line": "a session sala no longer knows", "name": "gone-one", "fix": "retire it"},
                       {"to": "", "page": "projects/pa-two", "line": "no agents map", "name": "-", "fix": "add the map"}]}
pa_env = AR.Env(roles={"falcon-main": {"role": "background"}}, sessions=lambda: None, page_of=lambda p: ("", None), deliver=deliver)
pa = AR.page_agent_groups(pa_res, pa_env)
check("4d one session reached both ways (named as a background session, and as the audit's -main agent): two groups, one marked and one not", sorted(pa) == [("falcon-main", False), ("falcon-main", True)] and
      [g["front"] for _k, g in sorted(pa.items())] == [False, True], {k: v["front"] for k, v in pa.items()})
check("4d …each holds only its own page's line (the unmarked one was marked or not by the first line alone, before)", all(len(g["lines"]) == 1 for g in pa.values()) and "pa-one" in pa[("falcon-main", False)]["lines"][0] and "pa-two" in pa[("falcon-main", True)]["lines"][0], pa)

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: audit front-only scenario, {len(ran)} checks")
