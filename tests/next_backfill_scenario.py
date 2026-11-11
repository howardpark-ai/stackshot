"""Scenario test for the one-off fill-in of his past decisions (next_backfill.py, server.py `_migrate_backfill`) — fixture data, no live store,
no network, no server socket.

Covers: the plan for an open item (a saved `decision` answer becomes `Oliver: <the Decide part of its ask> → <the option>`, done by him at the answer's time; an answer with no ask reads `answer the ask
on the item`; a Done on a step shows that step; his words are quoted; a comment and a note on a step add nothing); an answer already on the checklist (a done step of his at its time, or a done step of
his that says the same question ticked by a session) is not added again; a closed item is left as it is; the steps are appended after the checklist as it reads, in the order he answered, and nothing
else in the metadata changes (the open steps, next and the writers stay); a second run adds nothing; the server's `backfill` write recomputes from the item's own answers (a step text sent in the body is never stored), is idempotent (`already`), is refused for a closed item and without
`expect` / `expect_sig`, and reports an item written or answered since it was planned as `moved`; the author is `migration` and no clock moves.

    tests/run-suite next_backfill        → exit 0 / 1"""
import hashlib, json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="nbftest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"

toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^owner = "the owner"', 'owner = "Oliver"'), (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^git = true', 'git = false'),
                 (r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root"]')):
    toml, n = re.subn(pat, rep, toml, count=1); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
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
DESC = "- A thing, finished when it works"
ASK = "Decide: whether to ship it now · Recommend: ship · Stakes: a day either way · By: no date"
T1, T2, T3, T4 = now - 5000.5, now - 4000.25, now - 3000.75, now - 2000.0
def item(i, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": DESC, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "next": "home-agent: build it", **meta}}))
ANS = lambda ts, kind="decision", **kw: {"ts": ts, "kind": kind, "via": "board", **kw}
item(1, answers=[ANS(T1, choice="Ship", ask=ASK), ANS(T2, text="park it until Monday"), ANS(T3, "comment", text="a thought"), ANS(T4, "step-reply", text="did most of it", step="check the box")])
item(2, answers=[ANS(T1, choice="Ship", ask=ASK)],
     steps=[{"text": "Oliver: whether to ship it now → Ship", "status": "done", "by": "Oliver", "at": T1 + 1}, {"text": "home-agent: build it", "status": "open"}])      # …its step is there already
item(3, status="completed", answers=[ANS(T1, choice="Ship", ask=ASK)], outcome="done")
item(4, answers=[ANS(T1, choice="Done", step="post the draft on the site")])
item(5, answers=[ANS(T1, choice="Ship", ask=ASK)],
     steps=[{"text": "Oliver: whether to ship it now", "status": "done", "by": "home-agent", "at": T1 + 900}, {"text": "home-agent: build it", "status": "open"}])        # …a session ticked his step
item(6)                                                                                                      # no answers
item(7, answers=[ANS(T1, choice="Ship", ask=ASK), ANS(T2, choice="Ship", ask=ASK)])                          # asked the same thing twice
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def digest(): return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((T / "store").glob("*/*.json"))}

from stackshot.web import server; from stackshot.model import steps as S; from stackshot.model import nextlines as NL; from stackshot.model import next_backfill as NB; from stackshot.model import owner_steps as HS; from stackshot.model import migration as M
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None

# ---- 1. the plan, one item
p1 = NB.plan(mt(1), "open", OWNER)
check("a saved decision with its ask becomes `Oliver: <Decide part> → <the option>`; one with no ask reads `answer the ask on the item → \"his words\"`; in the order he answered",
      [r["line"] for r in p1] == ["Oliver: whether to ship it now → Ship", 'Oliver: answer the ask on the item → "park it until Monday"'], p1)
check("…a comment and a note on a step add nothing (the note leaves its step to the session that judges it)", len(p1) == 2, p1)
p4 = NB.plan(mt(4), "open", OWNER)
check("a Done on a step shows that step", [r["line"] for r in p4] == ["Oliver: post the draft on the site → Done"], p4)
check("an item with no answers adds nothing", NB.plan(mt(6), "open", OWNER) == [], None)
check("a closed item is left as it is", NB.plan(mt(3), "completed", OWNER) == [], NB.plan(mt(3), "completed", OWNER))
add2, have2 = NB.audit(mt(2), "open", OWNER)
check("an answer whose done step of his is there already (at its time) is not added again", add2 == [] and [h["why"] for h in have2] == ["step there"], (add2, have2))
add5, have5 = NB.audit(mt(5), "open", OWNER)
check("a done step of his that says the same, ticked by a session, is left as it is and not added beside", add5 == [] and [h["why"] for h in have5] == ["ticked by home-agent"], (add5, have5))
check("the same question answered twice adds both answers", len(NB.plan(mt(7), "open", OWNER)) == 2, NB.plan(mt(7), "open", OWNER))

# ---- 2. apply on the metadata
m = json.loads(json.dumps(mt(1)))
before_next, before_open = m["next"], [x for x in S.view(m, keeper=OWNER) if x["status"] == "open"]
n = NB.apply(m, p1, OWNER)
cl = S.view(m, keeper=OWNER)
done = [x for x in cl if x["status"] == "done"]
check("apply appends the done steps after the checklist as it reads, done by Oliver at each answer's time", n == 2 and [(x["text"], x["by"], x["at"]) for x in done] == [(r["line"], "Oliver", r["ts"]) for r in p1] and cl[0]["text"] == "home-agent: build it", cl)
check("…next and the open steps are untouched, and a second plan finds nothing to add (idempotent)", m["next"] == before_next and [x["text"] for x in cl if x["status"] == "open"] == [x["text"] for x in before_open] and NB.plan(m, "open", OWNER) == [], (m["next"], NB.plan(m, "open", OWNER)))

# ---- 3b. the edge of `near`: a done step of his within NEAR seconds of the answer is that answer's step
def edge(dt):
    m = {"owner": OWNER, "answers": [ANS(1790000000.25, choice="Ship", ask=ASK)], "next": "home-agent: build it",
         "steps": [{"text": "Oliver: something else entirely → X", "status": "done", "by": "Oliver", "at": 1790000000.25 + dt}, {"text": "home-agent: build it", "status": "open"}]}
    return NB.audit(m, "open", OWNER)
a_, h_ = edge(NB.NEAR); check("near edge: a step of his exactly NEAR seconds after the answer counts as its step", a_ == [] and [x["why"] for x in h_] == ["step there"], (a_, h_))
a_, h_ = edge(-NB.NEAR); check("near edge: …and exactly NEAR seconds before it", a_ == [] and len(h_) == 1, (a_, h_))
a_, h_ = edge(NB.NEAR + 0.1); check("near edge: a step 0.1 s past NEAR is another step, so the answer's step is added", len(a_) == 1 and h_ == [], (a_, h_))
a_, h_ = edge(-NB.NEAR - 0.1); check("near edge: …on either side", len(a_) == 1 and h_ == [], (a_, h_))
item(8, answers=[ANS(T1, choice="Ship", ask=ASK)])

# ---- 4. the server's write
CFGM = server._cfg.CFG.setdefault("model", {})
CFGM.update(guards=True, watchers=True, pause=False, migration=True, migration_senders=["falcon-engineer"], migration_machines=["testbox"])
def call(op, **kw):
    try: return server._migrate_write({"op": op, "sender": "falcon-engineer", **kw}, "testbox")
    except Exception as e: return {"error": str(e)}
def body(i, **kw):
    it = rd(i)
    return {"item": f"a{i}", "backfill": "owner_steps", "expect": it["updated"], "expect_sig": M.activity_sig(it, 0), **kw}
check("begin holds the pass", "pass_id" in call("begin"), None)
st0 = {i: rd(i) for i in (1, 2, 3, 4)}
r = call("apply", writes=[body(1), body(2), body(3), body(4)])
res = {x["item"]: x for x in r.get("results", [])}
check("the server writes items 1 and 4, finds item 2 already done and refuses the closed item 3", [res.get(f"a{i}", {}).get("action") for i in (1, 2, 3, 4)] == ["set", "already", "refused", "set"], r)
check("…the steps are the ones the plan gives, done by Oliver at the answers' times (recomputed on the server)",
      [(x["text"], x["by"], x["at"]) for x in S.view(mt(1), keeper=OWNER) if x["status"] == "done"] == [(r_["line"], "Oliver", r_["ts"]) for r_ in p1], S.view(mt(1), keeper=OWNER))
check("…the author is `migration` and no clock moves (updated, the state clock and the confirm stay), next stays", rd(1).get("written_by") == "migration" and rd(1)["updated"] == st0[1]["updated"]
      and rd(1)["state_updated"] == st0[1]["state_updated"] and rd(1)["confirmed"] == st0[1]["confirmed"] and mt(1)["next"] == st0[1]["metadata"]["next"], rd(1))
check("…item 2 and the closed item 3 are byte for byte what they were", rd(2) == st0[2] and rd(3) == st0[3], None)
r2 = call("apply", writes=[body(1), body(4)])
check("a second run changes nothing (already)", [x["action"] for x in r2.get("results", [])] == ["already", "already"], r2)
# a step text sent in the body is never stored: the server works from the item's own answers
r3 = call("apply", writes=[{**body(7), "set": {"steps": [{"text": "Oliver: typed text", "status": "done"}]}, "line": "Oliver: typed text → Yes"}])
check("a text sent with the write is never stored (the item's own answers are what the server uses)", r3["results"][0]["action"] == "set" and not any("typed" in x["text"] for x in S.view(mt(7), keeper=OWNER)), (r3, S.view(mt(7), keeper=OWNER)))
check("…item 7's two identical questions each get their step", len([x for x in S.view(mt(7), keeper=OWNER) if x["status"] == "done"]) == 2, S.view(mt(7), keeper=OWNER))
nb = {"item": "a5", "backfill": "owner_steps"}
check("a write with no expect or no expect_sig is refused", "expect is required" in call("apply", writes=[nb])["results"][0]["why"] and "expect_sig is required" in call("apply", writes=[{**nb, "expect": rd(5)["updated"]}])["results"][0]["why"], None)
check("a backfill kind other than owner_steps is refused", "only fill-in" in call("apply", writes=[{**body(5), "backfill": "something"}])["results"][0]["why"], None)
stale = body(6); item(6, answers=[ANS(T1, choice="Ship", ask=ASK)], next="home-agent: build it")
check("an item that was written since it was planned is `moved`, never overwritten", call("apply", writes=[stale])["results"][0]["action"] == "moved" and not any(x["status"] == "done" for x in S.view(mt(6), keeper=OWNER)), None)
b6 = body(6)
(T / "store/a/6.json").write_text(json.dumps({**rd(6), "metadata": {**mt(6), "answers": [*mt(6)["answers"], ANS(T2, choice="Ship", ask=ASK)]}}))
check("…an answer that arrived since it was planned (it moves nothing else) is `moved` too", call("apply", writes=[b6])["results"][0]["action"] == "moved", None)
call("end", residue=[])
CFGM.pop("migration"); CFGM.pop("migration_senders"); CFGM.pop("migration_machines")
# ---- 5. the gate off: a backfill write is refused as a whole and nothing is written
d8 = digest()
it8 = rd(8)
st_, d_ = server._client_post("testbox", "migrate", {"op": "apply", "sender": "falcon-engineer", "writes": [{"item": "a8", "backfill": "owner_steps", "expect": it8["updated"], "expect_sig": M.activity_sig(it8, 0)}]})
check("gate off: a backfill write answers 403 and writes nothing", st_ == 403 and "error" in d_ and "results" not in d_ and digest() == d8 and not any(x["status"] == "done" for x in S.view(mt(8), keeper=OWNER)), (st_, d_))
st_, d_ = server._client_post("testbox", "migrate", {"op": "apply", "sender": "somebody-else", "writes": [{"item": "a8", "backfill": "owner_steps"}]})
check("…and so does one from a sender that is not named", st_ == 403 and digest() == d8, (st_, d_))

print(("ok" if not fails else "FAILED") + f": next_backfill scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
