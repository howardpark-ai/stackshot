"""Scenario test for the last-activity backfill: `metadata.last_activity` filled for the open items that have no record, from their History (stackshot/model/last_activity_pass.py, the ops lastact and unlastact of the
migration route in the server, tools/last_activity_backfill.py) — fixture data in a throwaway git store, no live store written, no network, no server socket.

An item nobody has touched since the record shipped carries none, so its On agent row can say nothing about it. The pass works the newest visible activity out of the History the store's git holds (every version of the
item's file replayed through the function a save goes through) and the hub's logs of pull request events, and writes `metadata.last_activity` and nothing else. It is the until pass's shape: one item at a time under the
item lock, an undo file and a backup written before the first write, a refused class for a History that cannot be read.

  1  replay          the pure half: a step marked by a real write, a state change by a real write, a bookkeeping save that changes nothing visible, a merge recorded, the creation; the version's time is the record's time
  2  dry run         the route's dry run changes no file and no commit, answers the record each item would get, the kind and the words, and `same` for an item that has one
  3  write           only metadata.last_activity changes in each file (every other byte of the item is the same), no clock moves, no commit is made, nobody is told; the times and kinds are the History's
  4  refused class   an item whose History does not read (a torn version, a store outside git) and one with a version dated ahead of the clock are refused with the reason and left as they are; nothing is guessed
  5  future time     a record never goes in dated after the clock; a time inside the skew reads as now; a stored record far ahead of the clock is no record and is replaced, and the undo puts it back
  6  lock            the write is made with the item lock held, and an item locked by another writer makes the pass wait
  7  idempotent      a second pass answers `same` for every item it filled and rewrites no file
  8  events          the hub's logged events tied to an item can be the newest signal; a line stamped ahead of the clock is dropped
  9  script          tools/last_activity_backfill.py: --apply plans first, backs up every touched file byte for byte and writes the undo file before the first write, ends 3 for the refused items; a second apply writes nothing;
                     --undo puts the records back (the key goes when it had none) and keeps one a later save changed; twice is a no-op; the dry run over a copy writes nothing live
  15 logs            the hub's logs, or the anchors that tie them, cannot be read: the dry run warns and the real pass refuses
  16 anchors         `mprog_svc._merge_tied` reports an anchors-read error as a problem of the answer (the live passes still tie the rest); the ties come back as a problem, the route refuses, apply writes nothing
  17 plan read twice the plan read twice is the same plan; --apply reads it twice, right before the write
  18 dry run exit 1 a dry run whose second pass on the copy would still change something exits 1 (a refusal in the History is exit 0)
  19 renames         the store's log is made with --no-renames: a moved file shows under both names, and the new one holds only its own History
  20 delete, re-add  an item file git saw deleted and added back is refused (the deleting commit holds no version of it)
  21 undo closed     --undo leaves an item closed since the pass alone and names it
  10 gate            refused while [model] migration is off, for a sender or machine outside the lists, for a body naming another key, for an undo entry naming a key the pass does not write

    tests/run-suite last_activity_backfill        -> exit 0 / 1"""
import argparse, contextlib, io, json, logging, os, pathlib, re, subprocess, sys, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="lactfill-"); T = pathlib.Path(tmp)


def mk_toml(root):
    """A config whose every path is inside `root`, with no GitHub mirror and no commit."""
    t = _instance.apply(_instance.base_toml(), owner=True)
    t = t.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in t
    for key, val in (("repo", root), ("store", f"{root}/store"), ("markdown", f"{root}/board.md"), ("brain", f"{root}/brain"),
                     ("state", f"{root}/state"), ("secrets", f"{root}/secrets"), ("project_touch", f"{root}/touch"), ("rules", f"{root}/RULES.md"), ("timezone", "Asia/Seoul")):
        t, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', t); assert n == 1, key
    t, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', t); assert n == 1
    t, n = re.subn(r'(?m)^git = true', 'git = false', t, count=1); assert n == 1
    t, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{root}/no-such-root", "{root}/transcripts"]', t); assert n == 1
    t, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", t); assert n == 1
    return t


(T / "stackshot.toml").write_text(mk_toml(tmp), encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchors", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
MIN, HR, DAY = 60.0, 3600.0, 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
BACK = "team-back"
SENDER = "falcon-engineer"
BOARD = "board" + "#"      # a board id is built at run time, never written as a literal
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server, wiring; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.model import last_activity as LA, last_activity_pass as LP, progress as PROG; from stackshot.tools import last_activity_backfill as BF; from stackshot.tools import until_migrate as UM; from stackshot.tools import stamp_phase as SP
from stackshot.web.routes import client_api as _rt_client
from stackshot.service import merge_progress as mprog_svc
from stackshot.service import stamp as stamp_svc
from stackshot.service import retire_passes as retire_svc
HOST = stamp_svc.PassHost(server, stamp_svc, retire_svc, mprog_svc, wiring.PASS_NAMES)   # the `S` of last_activity_pass: the server module, then the stamp and retire modules that own the names it reads
from stackshot.anchors import anchors as _anc
from stackshot.model import merge_tie as _mtie
from stackshot.core import config as _cfg
from stackshot.waits import watchers as _watch
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import telling
from stackshot.anchors import event_log as ELOG, merge_log as MLOG
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
telling.front_sender = lambda who: False
CFGM = _cfg.CFG.setdefault("model", {})
CFGM.update(guards=True, watchers=True, pause=False, one_mover=True, handoff=True, switchover=False, migration=False)
sent = []

# ---- the store is a git repository whose commits carry the fixture's own times (a neutral identity through the environment, never through the repository's config)
GENV = {**os.environ, "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid", "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
def git(*args, ct=None, cwd=None):
    env = dict(GENV)
    if ct is not None: env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{int(ct)} +0000"
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "init.defaultBranch=main", "-C", str(cwd or T / "store"), *args], capture_output=True, text=True, env=env)
assert git("init", "-q").returncode == 0
BASE = {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing", "needs": [BACK]}
def version(t, act, status="open", **meta):
    """An item as one save left it: `t` is its own time (updated and confirmed), `act` its activity clock."""
    return {"subject": "[home] a fixture item", "description": "- A thing\n- It lives here\n- Done when done", "status": status, "updated": t, "state_updated": t, "confirmed": t, "activity": act, "metadata": {**BASE, **meta}}
def write_file(i, d): (T / f"store/g/{i}.json").write_text(json.dumps({"id": str(i), **d}, ensure_ascii=False, indent=1), encoding="utf-8")
def commit(i, d, ct):
    write_file(i, d)
    assert git("add", "-A").returncode == 0
    r = git("commit", "-q", "-m", f"item {i}", ct=ct); assert r.returncode == 0, r.stderr
def raw(i): return json.loads((T / f"store/g/{i}.json").read_text())
def mt(i): return raw(i)["metadata"]
def bytes_of(i): return (T / f"store/g/{i}.json").read_bytes()
def snapshot(): return {p.name: p.read_bytes() for p in sorted((T / "store/g").glob("*.json"))}
def head(): return git("rev-parse", "HEAD").stdout.strip()
def rec_of(i): return mt(i).get("last_activity")
def without(d, *keys): return {k: v for k, v in d.items() if k not in keys}
def canon(b):
    """A file's bytes with the lines of its `last_activity` block taken out (and the comma a trailing key leaves on the line before a closing brace): what is left is every other byte of the item. Two files
    equal under it differ in that one block and nowhere else, byte for byte."""
    lines = b.decode("utf-8").split("\n"); out = []; i = 0
    while i < len(lines):
        l = lines[i]
        if l.lstrip().startswith('"last_activity":'):
            ind = len(l) - len(l.lstrip())
            if l.rstrip().endswith("{"):
                i += 1
                while not (lines[i].lstrip().startswith("}") and len(lines[i]) - len(lines[i].lstrip()) == ind): i += 1
            i += 1; continue
        out.append(l); i += 1
    for k in range(len(out) - 1):
        if out[k + 1].lstrip().startswith(("}", "]")): out[k] = out[k].rstrip(",")
    return "\n".join(out).encode("utf-8")

# 11: a step marked by a real write at -3 h, then a bookkeeping save that changes nothing visible at -2 h
STEPS0 = [{"text": "build it", "status": "open"}]; STEPS1 = [{"text": "build it", "status": "done"}]
commit(11, version(now0 - 5 * HR, now0 - 5 * HR, steps=STEPS0), now0 - 5 * HR)
commit(11, version(now0 - 3 * HR, now0 - 3 * HR, steps=STEPS1), now0 - 3 * HR)
commit(11, version(now0 - 2 * HR, now0 - 3 * HR, steps=STEPS1), now0 - 2 * HR)
# 12: a mover change by a real write at -90 min; a later bookkeeping save changes the mover again (not activity)
commit(12, version(now0 - 6 * HR, now0 - 6 * HR), now0 - 6 * HR)
commit(12, version(now0 - 90 * MIN, now0 - 90 * MIN, mover=BACK), now0 - 90 * MIN)
commit(12, version(now0 - 40 * MIN, now0 - 90 * MIN, mover="home-other"), now0 - 40 * MIN)
# 13: only ever created, a day ago
commit(13, version(now0 - 26 * HR, now0 - 26 * HR), now0 - 26 * HR)
# 14: a pull request recorded as merged by a real write at -50 min
commit(14, version(now0 - 4 * HR, now0 - 4 * HR), now0 - 4 * HR)
commit(14, version(now0 - 50 * MIN, now0 - 50 * MIN, merged_seen=["owner/repo#7"]), now0 - 50 * MIN)
# 15: already has a record that reads (stays exactly as it is)
KEEP = {"at": now0 - 10 * MIN, "kind": "comment", "what": "comment on #124"}
commit(15, version(now0 - 8 * HR, now0 - 8 * HR, last_activity=KEEP), now0 - 8 * HR)
# 16: a stored record dated a day ahead of the clock (no record), History from 2 h ago
FUTURE = {"at": now0 + DAY, "kind": "comment", "what": "comment on #1"}
commit(16, version(now0 - 2 * HR, now0 - 2 * HR, last_activity=FUTURE), now0 - 2 * HR)
# 17: a version dated two days ahead of the clock (a clock that jumped): the History is not trusted
commit(17, version(now0 - 3 * HR, now0 - 3 * HR), now0 - 3 * HR)
commit(17, version(now0 + 2 * DAY, now0 + 2 * DAY, mover=BACK), now0 - 2 * HR)
# 18: a torn version in the middle of the History (not JSON)
commit(18, version(now0 - 3 * HR, now0 - 3 * HR), now0 - 3 * HR)
(T / "store/g/18.json").write_text("{not json", encoding="utf-8"); assert git("add", "-A").returncode == 0; assert git("commit", "-q", "-m", "torn", ct=now0 - 2 * HR).returncode == 0
commit(18, version(now0 - 1 * HR, now0 - 1 * HR, mover=BACK), now0 - 1 * HR)
# 19: tied to a pull request event (the logs, section 8): its own History is old
commit(19, version(now0 - 8 * HR, now0 - 8 * HR), now0 - 8 * HR)
# 20: a version ten minutes ahead of the clock (inside the skew): read as now
commit(20, version(now0 - 3 * HR, now0 - 3 * HR), now0 - 3 * HR)
commit(20, version(now0 + 10 * MIN, now0 + 10 * MIN, mover=BACK), now0 - 2 * HR)
# 21: a closed item
commit(21, version(now0 - 3 * HR, now0 - 3 * HR, status="completed"), now0 - 3 * HR)
# 22: written on disk and not yet committed (the server commits on a debounce): the file on disk is the last version
commit(22, version(now0 - 5 * HR, now0 - 5 * HR), now0 - 5 * HR)
write_file(22, version(now0 - 25 * MIN, now0 - 25 * MIN, mover=BACK))
OPEN = [11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 22]
H0 = head()

# ---- 1. the pure half
vs = [(now0 - 5 * HR, version(now0 - 5 * HR, now0 - 5 * HR, steps=STEPS0)), (now0 - 3 * HR, version(now0 - 3 * HR, now0 - 3 * HR, steps=STEPS1)), (now0 - 2 * HR, version(now0 - 2 * HR, now0 - 3 * HR, steps=STEPS1))]
sigs, bad = LP.replay(vs, now0)
check("1 replay: the creation and the step marked by a real write are signals; the bookkeeping save that changed nothing is none", not bad and [(s["kind"], s["what"], s["at"]) for s in sigs] == [("state_change", "created", now0 - 5 * HR), ("step_done", "step 1 done", now0 - 3 * HR)], (sigs, bad))
check("1 …the record is the newest of them", LP.newest(sigs, now0) == {"at": now0 - 3 * HR, "kind": "step_done", "what": "step 1 done"}, LP.newest(sigs, now0))
sigs2, _ = LP.replay([(now0 - 6 * HR, version(now0 - 6 * HR, now0 - 6 * HR)), (now0 - 90 * MIN, version(now0 - 90 * MIN, now0 - 90 * MIN, mover=BACK)), (now0 - 40 * MIN, version(now0 - 40 * MIN, now0 - 90 * MIN, mover="home-other"))], now0)
check("1 a mover change by a real write is a state change; the same change by the server's bookkeeping (the activity clock did not move) is none", [(s["what"], s["at"]) for s in sigs2] == [("created", now0 - 6 * HR), ("mover changed", now0 - 90 * MIN)], sigs2)
check("1 a version dated ahead of the clock by more than the skew makes the History untrusted; inside the skew it is read as now",
      LP.replay([(0, version(now0 + 2 * DAY, now0))], now0)[1] != "" and LP.replay([(0, version(now0 + 10 * MIN, now0))], now0)[0][0]["at"] == now0, None)
check("1 a version with no time of its own takes its commit's time; one with neither is a problem", LP.replay([(now0 - HR, {"status": "open", "metadata": {}})], now0)[0][0]["at"] == now0 - HR and LP.replay([(0, {"status": "open", "metadata": {}})], now0)[1] != "", None)
nan, inf = float("nan"), float("inf")
check("1 a time that is a bool, a numeric string, NaN or infinity is no time (vtime and the clock read), as the record's own reader has it; numbers stand",
      LP.vtime({"updated": True}) == 0.0 and LP.vtime({"updated": "123"}) == 0.0 and LP.vtime({"updated": nan, "confirmed": inf}) == 0.0 and LP.vtime({"updated": None, "confirmed": [5]}) == 0.0
      and LP._num(True) == 0.0 and LP._num("7") == 0.0 and LP._num(nan) == 0.0 and LP._num(-inf) == 0.0 and LP.vtime({"updated": 5, "confirmed": 7.5}) == 7.5 and LP._num(3) == 3.0, None)
sg_, bd_ = LP.replay([(now0 - HR, {"status": "open", "updated": True, "confirmed": "999", "activity": "x", "metadata": {}})], now0)
sg2_, bd2_ = LP.replay([(now0 - HR, {"status": "open", "updated": nan, "metadata": {}})], now0)
check("1 …so a version whose own times are such takes its commit's time, and a version with only such times and no commit time is a problem", not bd_ and sg_[0]["at"] == now0 - HR and not bd2_ and sg2_[0]["at"] == now0 - HR
      and LP.replay([(0, {"status": "open", "updated": True, "confirmed": "5", "metadata": {}})], now0)[1] != "", (sg_, bd_, sg2_, bd2_))
check("1 …and a string as the activity clock is no clock (it does not make a version real)", [s["what"] for s in LP.replay([(now0 - 2 * HR, version(now0 - 2 * HR, now0 - 2 * HR, steps=STEPS0)), (now0 - HR, version(now0 - HR, "999999999999", steps=STEPS1))], now0)[0]] == ["created"], None)
check("1 the skew is the one an event's own time is allowed", LA.SKEW_S == ELOG.AHEAD_S, (LA.SKEW_S, ELOG.AHEAD_S))

# ---- 2. the dry run
CFGM["migration"] = True
call = lambda machine="box-a", **body: _rt_client._client_post(machine, "migrate", {"sender": SENDER, **body})
snap0 = snapshot()
st_, d_ = call(op="lastact", items=[f"g{i}" for i in OPEN], dry=True)
dry = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("2 a dry run changes no file and no commit, and answers would_set for the items to fill, same for the one with a record", st_ == 200 and snapshot() == snap0 and head() == H0
      and [dry[i]["action"] for i in (11, 12, 13, 14, 16, 19, 20, 22)] == ["would_set"] * 8 and dry[15]["action"] == "same", (st_, {i: dry[i]["action"] for i in dry}))
check("2 …its before and after name the one key; the kind and words are the History's", dry[11]["before"] == {"last_activity": None} and dry[11]["after"]["last_activity"] == {"at": now0 - 3 * HR, "kind": "step_done", "what": "step 1 done"}
      and (dry[12]["kind"], dry[12]["what"]) == ("state_change", "mover changed") and (dry[13]["kind"], dry[13]["what"], dry[13]["at"]) == ("state_change", "created", now0 - 26 * HR), dry[11])
check("2 …a bookkeeping save does not move the time (12 stays at the real write 90 minutes ago), the file on disk not yet committed is the last version (22)", dry[12]["at"] == now0 - 90 * MIN and (dry[22]["what"], dry[22]["at"]) == ("mover changed", now0 - 25 * MIN), (dry[12], dry[22]))
check("2 …a merge recorded is a pr_merged signal naming the pull request", (dry[14]["kind"], dry[14]["what"], dry[14]["at"]) == ("pr_merged", "PR 7 merged", now0 - 50 * MIN), dry[14])

# ---- 3. the write
orig = {i: raw(i) for i in OPEN}; orig_bytes = {i: bytes_of(i) for i in OPEN}
held = []; orig_sw = stamp_svc._stamp_write
def spying_write(*a, **k):
    held.append(writes.ITEM_LOCK._is_owned()); return orig_sw(*a, **k)
stamp_svc._stamp_write = spying_write
PID = "20260101-000000-abcdef"
st_, d_ = call(op="lastact", items=[f"g{i}" for i in OPEN], pass_id=PID)
stamp_svc._stamp_write = orig_sw
res = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("3 the pass fills the eight, leaves the one with a record, and refuses the two whose History does not read and the one dated ahead", [res[i]["action"] for i in (11, 12, 13, 14, 16, 19, 20, 22)] == ["set"] * 8
      and res[15]["action"] == "same" and [res[i]["action"] for i in (17, 18)] == ["refused"] * 2, {i: res[i]["action"] for i in res})
check("3 only metadata.last_activity changed in each filled file: every other byte of the item is the same (the file bytes compared, with the record's own lines taken out of both; the record is in the new file)",
      all(canon(bytes_of(i)) == canon(orig_bytes[i]) and b'"last_activity"' in bytes_of(i) and bytes_of(i) != orig_bytes[i] for i in (11, 12, 13, 14, 16, 19, 20, 22)), [i for i in (11, 12, 13, 14, 16, 19, 20, 22) if canon(bytes_of(i)) != canon(orig_bytes[i])])
check("3 …the canon check sees a change elsewhere in the file (a byte of the description) and a changed record is no change to it", canon(bytes_of(11).replace(b"A thing", b"A thinG")) != canon(orig_bytes[11]) and canon(bytes_of(11).replace(b"step 1 done", b"step 2 done")) == canon(orig_bytes[11]), None)
check("3 …the files of the items left as they are are byte for byte the same", all(bytes_of(i) == orig_bytes[i] for i in (15, 17, 18)), None)
check("3 …no clock moved (updated, confirmed, activity, state_updated, written_at), no commit was made, nobody was told, nothing was held", all(all(raw(i).get(k) == orig[i].get(k) for k in ("updated", "confirmed", "activity", "state_updated", "written_at", "written_by")) for i in OPEN)
      and head() == H0 and sent == [] and not _watch.holding(), sent)
check("3 the records are the History's: step done at the real write, mover changed, created, PR merged", rec_of(11) == {"at": now0 - 3 * HR, "kind": "step_done", "what": "step 1 done"} and rec_of(12) == {"at": now0 - 90 * MIN, "kind": "state_change", "what": "mover changed"}
      and rec_of(13) == {"at": now0 - 26 * HR, "kind": "state_change", "what": "created"} and rec_of(14) == {"at": now0 - 50 * MIN, "kind": "pr_merged", "what": "PR 7 merged"}, [rec_of(i) for i in (11, 12, 13, 14)])
check("3 the item with a record keeps it, whatever its History says", rec_of(15) == KEEP, rec_of(15))
check("3 every record reads (last_activity.read) and none is dated after the clock", all(LA.read(raw(i), time.time()) is not None and rec_of(i)["at"] <= time.time() for i in (11, 12, 13, 14, 16, 19, 20, 22)), None)

# ---- 4. the refused class
check("4 an item with a torn version in its History is refused with the reason, the class, and is left as it is", res[18]["action"] == "refused" and res[18]["class"] == LP.CLASS_HISTORY and "does not read as JSON" in res[18]["why"] and "last_activity" not in mt(18), res[18])
check("4 an item with a version dated two days ahead is refused for it, and nothing is guessed", res[17]["action"] == "refused" and res[17]["class"] == LP.CLASS_HISTORY and "ahead of the clock" in res[17]["why"] and "last_activity" not in mt(17), res[17])
plain = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-nogit-"))
nogit = LP.one(HOST, "g13", dry=True, git_store=plain)
write_file(23, version(now0 - 3 * HR, now0 - 3 * HR))
nogit2 = LP.one(HOST, "g23", dry=True, git_store=plain)
check("4 a store outside git is the same class: the History cannot be read (an item that has a record is not read at all)", nogit["action"] == "same" and nogit2["action"] == "refused" and nogit2["class"] == LP.CLASS_HISTORY and "git did not answer" in nogit2["why"], (nogit, nogit2))
(T / "store/g/23.json").unlink()
st_, d_ = call(op="lastact", items=["g21", "g404", "nonsense"])
check("4 a closed item is refused and left as it is; an unknown item and a malformed id are refused one by one", [r["action"] for r in d_["results"]] == ["refused"] * 3 and "closed" in d_["results"][0]["why"] and "last_activity" not in mt(21), d_)

# ---- 5. a future time is never written
check("5 the record of the item whose version stands ten minutes ahead (inside the skew) reads as now, not after it", rec_of(20)["at"] <= time.time() and rec_of(20)["at"] >= now0 - 1, rec_of(20))
check("5 a stored record a day ahead of the clock was no record: it is replaced by the History's time, and the entry keeps the old value", rec_of(16) == {"at": now0 - 2 * HR, "kind": "state_change", "what": "created"} and res[16]["before"] == {"last_activity": FUTURE}, (rec_of(16), res[16]["before"]))
check("5 …the reader agrees: a record more than the skew ahead is none, one inside it is just now, in read, at and age_s",
      LA.read({"metadata": {"last_activity": FUTURE}}, now0) is None and LA.at({"metadata": {"last_activity": FUTURE}}, now0) == 0.0 and LA.age_s({"metadata": {"last_activity": FUTURE}}, now0) is None
      and LA.age_s({"metadata": {"last_activity": {**FUTURE, "at": now0 + 10 * MIN}}}, now0) == 0.0 and LA.read({"metadata": {"last_activity": FUTURE}}) is not None, None)
check("5 the pass states it too: a time it found ahead of the clock is never written (the guard in `one`)", all(LA.read(raw(i), time.time())["at"] <= time.time() + 1 for i in (11, 12, 13, 14, 16, 19, 20, 22)), None)

# ---- 6. the lock
check("6 every write was made with the item lock held", held and all(held) and len(held) == 8, held)
write_file(24, version(now0 - 4 * HR, now0 - 4 * HR)); subprocess.run(["git", "-C", str(T / "store"), "add", "-A"], env=GENV); git("commit", "-q", "-m", "24", ct=now0 - 4 * HR)
done = []
def runner(): done.append(LP.one(HOST, "g24", dry=True))
writes.ITEM_LOCK.acquire()
th = threading.Thread(target=runner); th.start(); th.join(0.5)
waited = not done
writes.ITEM_LOCK.release(); th.join(10)
check("6 an item locked by another writer makes the pass wait, then it reads the item as the writer left it", waited and done and done[0]["action"] == "would_set", (waited, done))
(T / "store/g/24.json").unlink()      # the script section below plans over every open item of the store

# ---- 7. idempotent
snap1 = snapshot()
st_, d_ = call(op="lastact", items=[f"g{i}" for i in OPEN])
acts = {int(r["item"].split("#")[1]): r["action"] for r in d_["results"]}
check("7 a second pass writes nothing: same for every item it filled and for the one that had a record, refused for the two it refused, no file changes", st_ == 200 and snapshot() == snap1
      and all(acts[i] == "same" for i in (11, 12, 13, 14, 15, 16, 19, 20, 22)) and acts[17] == acts[18] == "refused", acts)

# ---- 8. the hub's logged events
newer = now0 - 20 * MIN
for p_, rows in ((MLOG.path(), [{"ts": now0 - 3 * HR, "repo": "owner/repo", "n": 9, "refs": []}]),
                 (ELOG.path(), [{"ts": newer, "repo": "owner/repo", "n": 9, "kind": "comment", "refs": []}, {"ts": now0 + 5 * DAY, "repo": "owner/repo", "n": 9, "kind": "review", "refs": []},
                                {"ts": now0 - 5 * MIN, "repo": "owner/repo", "n": 99, "kind": "ci_failed", "refs": []}])):
    p_.parent.mkdir(parents=True, exist_ok=True); p_.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
reset_files = lambda: [write_file(i, {k: v for k, v in json.loads(orig_bytes[i]).items() if k != "id"}) for i in (11, 12, 13, 14, 16, 19, 20, 22)]
reset_files()      # the eight as the History left them (no record), for the events to be the newest signal
orig_tied = mprog_svc._merge_tied
mprog_svc._merge_tied = lambda rows, now: [(r, f"{r['repo']}#{r['n']}", {"g19": "anchored"}) for r in rows if r["n"] == 9]      # the live tie is merge_tie's, covered by its own suite; here the lines are tied to one item
rows_, probs_ = LP.pr_rows(HOST, now0)
check("8 the two logs are read whole, each line on its own (a merge-log line is a merge)", not probs_ and sorted((r["kind"], r["n"]) for r in rows_) == [("ci_failed", 99), ("comment", 9), ("merged", 9), ("review", 9)], (rows_, probs_))
tied, tie_why = LP.ties(HOST, now0)
check("8 …the ties read without a problem", tie_why == "", tie_why)
check("8 a tied event is a signal at the time the hub saw it, of its kind; a line stamped days ahead of the clock is dropped", [(s["kind"], s["what"], s["at"]) for s in tied.get("g19", [])] == [("pr_merged", "PR 9 merged", now0 - 3 * HR), ("comment", "comment on #9", newer)], tied)
r19 = LP.one(HOST, "g19", dry=True, tied=tied, now=now0)
check("8 …the newest of the History and the events is the record (a comment 20 minutes ago over a creation 8 hours ago)", r19["action"] == "would_set" and (r19["kind"], r19["at"]) == ("comment", newer), r19)
mprog_svc._merge_tied = orig_tied
r19b = LP.one(HOST, "g19", dry=True, tied={}, now=now0)
check("8 …without the tie the record is the History's alone (created 8 hours ago)", (r19b["kind"], r19b["what"], r19b["at"]) == ("state_change", "created", now0 - 8 * HR), r19b)

# ---- 9. the script
class DirectApp:
    """The live server's route, called in this process (what LiveApplier does over HTTP)."""
    def __init__(self): self.log = []
    def call(self, body):
        self.log.append(body["op"] + ("-dry" if body.get("dry") else ""))
        return _rt_client._client_post("box-a", "migrate", {**body, "sender": SENDER})
def reset():
    """Every fixture item as the History left it (no record on the ones the pass filled), the file on disk as its last commit."""
    for i in (11, 12, 13, 14, 16, 19, 20, 22):
        d = json.loads(orig_bytes[i]); write_file(i, {k: v for k, v in d.items() if k != "id"})
reset()
snapS0 = snapshot()
RUN = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-run-"))
args = argparse.Namespace(sender=SENDER, run_dir=str(RUN), undo="", plan="", allow_changed_plan=False)
def cli(fn, app=None, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(argparse.Namespace(**{**vars(args), **kw}), app or DirectApp())
    try: return rc, json.loads(out.getvalue()), err.getvalue()
    except ValueError: return rc, out.getvalue(), err.getvalue()
app = DirectApp()
orig_write = SP.write_atomic; seen_undo = []
def spy(path, obj):
    if str(path).endswith("undo.json") and not seen_undo and not any(r.get("result") for r in obj["items"]):
        seen_undo.append((len([f for f in snapshot() if snapshot()[f] != snapS0[f]]), len(obj["items"])))      # files already written when the undo file first lands
    return orig_write(path, obj)
SP.write_atomic = spy
rc1, out1, err1 = cli(BF.apply, app=app)
SP.write_atomic = orig_write
undo_file = pathlib.Path(out1["undo"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("9 apply asks for the plan first (a dry call), writes the undo file, names the refused class before it writes, and ends with the left-over exit code (3, not a failure)",
      rc1 == BF.EXIT_LEFT_OVER == 3 and app.log[0] == "lastact-dry" and "lastact" in app.log and undo_file.is_file() and "refused class" in err1 and BOARD + "17" in err1 and BOARD + "18" in err1
      and set(out1["refused_in_the_plan"]) == {BOARD + "17", BOARD + "18"} and out1["results"] == {"set": 8}, (rc1, out1, err1[-600:]))
check("9 …the undo file is written whole before the first file changes", seen_undo and seen_undo[0][0] == 0 and seen_undo[0][1] == 8, seen_undo)
bk = pathlib.Path(out1["backup"]) if isinstance(out1, dict) else pathlib.Path("/nonexistent")
check("9 …the backup holds every touched file byte for byte as it was, and only those", sorted(p.name for p in bk.glob("*.json")) == sorted(f"g{i}.json" for i in (11, 12, 13, 14, 16, 19, 20, 22))
      and all((bk / f"g{i}.json").read_bytes() == snapS0[f"{i}.json"] for i in (11, 12, 13, 14, 16, 19, 20, 22)), sorted(p.name for p in bk.glob("*")))
uj = json.loads(undo_file.read_text()) if undo_file.is_file() else {"items": []}
check("9 …the undo file names each item with its record before and after and the real result", {"pass_id", "by", "when", "store", "backup", "items"} <= set(uj) and all({"item", "before", "after", "sha256_before", "result"} <= set(e) and e["result"] == "set" for e in uj["items"]), uj["items"][:1])
check("9 the files the script wrote differ from the History's only in last_activity, byte for byte", all(canon(bytes_of(i)) == canon(snapS0[f"{i}.json"]) for i in (11, 12, 13, 14, 16, 19, 20, 22)), None)
rc2, out2, _e = cli(BF.apply)
check("9 a second apply writes nothing", rc2 == 3 and out2["filled"] == 0 and set(out2["left_over"]) == {BOARD + "17", BOARD + "18"}, (rc2, out2))
# a later save changes the record of one item (the event pass wrote a newer one): the undo keeps it
newer_rec = {"at": now0 - 1 * MIN, "kind": "ci_result", "what": "CI passing again on PR 5"}
d14 = raw(14); d14["metadata"]["last_activity"] = newer_rec; write_file(14, without(d14, "id"))
rc3, out3, _e = cli(BF.undo, undo=str(undo_file))
back = all(rec_of(i) is None for i in (11, 12, 13, 19, 20, 22)) and rec_of(16) == FUTURE
check("9 --undo puts the records back value for value on the items still as the pass left them (the key goes when it had none, the old value returns when it had one) and keeps the one a later write changed",
      rc3 == 0 and back and out3["results"] == {"set": 7, "kept": 1} and out3["kept_because_a_later_save_changed_them"] == [BOARD + "14"] and rec_of(14) == newer_rec, (rc3, out3, [rec_of(i) for i in (11, 16, 14)]))
check("9 …every other byte is back too: the files of the undone items are what they were before the pass, byte for byte", all(bytes_of(i) == snapS0[f"{i}.json"] for i in (11, 12, 13, 16, 19, 20, 22)), [i for i in (11, 12, 13, 16, 19, 20, 22) if bytes_of(i) != snapS0[f"{i}.json"]])
rc4, out4, e4 = cli(BF.undo, undo=str(undo_file))
check("9 …undo twice is a no-op (the file is marked undone and says so)", rc4 == 0 and "already put back" in e4 and rec_of(14) == newer_rec, (rc4, out4, e4))
check("9 --apply and --undo need --sender", subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/last_activity_backfill.py"), "--apply"], capture_output=True, text=True).returncode != 0
      and subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/last_activity_backfill.py"), "--undo", "x.json"], capture_output=True, text=True).returncode != 0, None)
rc5, o5, e5 = cli(BF.undo, undo=str(RUN / "no-such" / "undo.json"))
check("9 an undo file that is none is a clean error and creates nothing", rc5 == 1 and "cannot use" in e5 and not (RUN / "no-such").exists(), (rc5, e5))
CFGM["migration"] = False
reset(); snapD = snapshot(); HD = head()
p = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/last_activity_backfill.py"), "--store", str(T / "store")], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml"})
check("9 the dry run over a copy writes nothing live (no file, no commit), prints the record each item would get and the totals, names the refused class, and exits 0", p.returncode == 0 and snapshot() == snapD and head() == HD
      and "step_done: step 1 done" in p.stdout and "items the pass would write: 8 of" in p.stdout and "a second pass: " in p.stdout and "refused class" in p.stdout and "does not read as JSON" in p.stdout and "ahead of the clock" in p.stdout
      and "with a record already (left as they are): 1" in p.stdout, (p.returncode, p.stdout[-1400:], p.stderr[-600:]))

# ---- 10. the gate
CFGM["migration"] = False
st_, d_ = call(op="lastact", items=["g11"])
check("10 the route is refused while [model] migration is off", st_ == 403 and bytes_of(11) == snapD["11.json"], (st_, d_))
CFGM["migration"] = True
st_, d_ = call(op="lastact", items=["g11"], sender="somebody-else")
check("10 …and for a sender outside [model] migration_senders", st_ == 403 and bytes_of(11) == snapD["11.json"], (st_, d_))
st_, d_ = call(machine="home-evil", op="lastact", items=["g11"])
check("10 …and for a token from a machine outside migration_machines", st_ == 403 and bytes_of(11) == snapD["11.json"], (st_, d_))
st_, d_ = call(op="lastact", items=["g11"], writes=[{"item": "g11", "set": {"mover": BACK}}])
check("10 …a body naming a key of its own is refused whole", st_ == 400 and "takes op, sender, items" in d_["error"] and bytes_of(11) == snapD["11.json"], (st_, d_))
st_, d_ = call(op="unlastact", items=[{"item": "g11", "before": {"mover": None}, "after": {"mover": BACK}}])
check("10 …an undo entry naming a key the pass does not write is refused", d_["results"][0]["action"] == "refused" and "not a key" in d_["results"][0]["why"], d_)
st_, d_ = call(op="unlastact", items=["g11"], dry=True)
check("10 …dry goes with lastact only; an empty list is refused", st_ == 400 and call(op="lastact", items=[])[0] == 400, (st_, d_))
st_, d_ = call(op="lastact", items=["g11"])
check("10 …a fill needs no begin and holds nothing", st_ == 200 and d_["results"][0]["action"] == "set" and not _watch.holding(), (st_, d_))
CFGM["migration"] = False

# ---- 11. a partial apply, then --undo: a batch whose answer was lost after the server wrote it
CFGM["migration"] = True
reset(); snapP = snapshot()
class LossyApp(DirectApp):
    """The route, but the answer of the second real batch is lost after the server has written it (a connection that dropped)."""
    def __init__(self): super().__init__(); self.real = 0
    def call(self, body):
        st, d = super().call(body)
        if body["op"] == "lastact" and not body.get("dry"):
            self.real += 1
            if self.real == 2: return 0, "connection lost"
        return st, d
orig_chunks = SP.chunks; SP.chunks = lambda xs, n=3: orig_chunks(xs, 3)      # eight items to fill, three to a batch: the second batch is the lost one
RUN2 = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-run2-"))
try: rcL, outL, errL = cli(BF.apply, app=LossyApp(), run_dir=str(RUN2))
finally: SP.chunks = orig_chunks
undoL = pathlib.Path(outL["undo"]) if isinstance(outL, dict) else pathlib.Path("/nonexistent")
ujL = json.loads(undoL.read_text()) if undoL.is_file() else {"items": []}
filled = (11, 12, 13, 14, 16, 19, 20, 22)
check("11 a batch with a lost answer: the apply ends 1, names the unanswered batch, and the undo file keeps no result for its three entries (the other five are final)",
      rcL == 1 and "no answer that says what it wrote" in errL and sorted(str(e["result"]) for e in ujL["items"]) == ["None"] * 3 + ["set"] * 5 and outL["results"] == {"set": 5, "batch unanswered": 3}, (rcL, errL[-400:], [e["result"] for e in ujL["items"]]))
check("11 …the server did write all eight (the lost answer came after the write)", all(bytes_of(i) != snapP[f"{i}.json"] for i in filled) and all(rec_of(i) is not None for i in filled), None)
rcU, outU, errU = cli(BF.undo, undo=str(undoL))
check("11 --undo takes the three entries with no result from the server's pass record and puts all eight items back", rcU == 0 and "taken from the server's pass record" in errU and outU["results"] == {"set": 8}
      and "put them back from their planned values" not in errU, (rcU, outU, errU[-500:]))
check("11 …every item is byte for byte as it was before the apply, and the file is marked undone", all(bytes_of(i) == snapP[f"{i}.json"] for i in filled) and json.loads(undoL.read_text()).get("undone"), [i for i in filled if bytes_of(i) != snapP[f"{i}.json"]])

# ---- 12. the `moved` path: a writer that takes no lock lands between the read and the replace
reset(); snapM = snapshot(); writer = {}; HM = head()
orig_sw2 = stamp_svc._stamp_write
def racing_write(p_, raw_, h0_, edits_):
    if p_.name == "11.json" and not writer:
        d_w = json.loads(p_.read_bytes()); d_w["description"] = "- Edited by a writer that takes no lock"
        p_.write_text(json.dumps(d_w, ensure_ascii=False, indent=1), encoding="utf-8"); writer["bytes"] = p_.read_bytes()
    return orig_sw2(p_, raw_, h0_, edits_)
stamp_svc._stamp_write = racing_write
try: r_m = LP.one(HOST, "g11")
finally: stamp_svc._stamp_write = orig_sw2
check("12 a write that lands between the read and the replace: the item is `moved`, the writer's file stands byte for byte, nothing of the pass is in it, no temp file is left", r_m["action"] == "moved" and bytes_of(11) == writer["bytes"]
      and "last_activity" not in mt(11) and not list((T / "store/g").glob(".*tmp")) and head() == HM, (r_m["action"], r_m["why"], bytes_of(11) == writer["bytes"], head() == HM))
r_m2 = LP.one(HOST, "g11")
check("12 …the next run fills it from its History and keeps the writer's text", r_m2["action"] == "set" and rec_of(11) is not None and raw(11)["description"] == "- Edited by a writer that takes no lock", r_m2)
reset(); writer.clear()
RUN3 = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-run3-"))
stamp_svc._stamp_write = racing_write
try: rcM, outM, errM = cli(BF.apply, run_dir=str(RUN3))
finally: stamp_svc._stamp_write = orig_sw2
check("12 through the script: seven filled, the one moved is named to run again and its entry is `moved`, the exit is 3 (not a failure), and the writer's file stands", rcM == 3 and outM["results"] == {"set": 7, "moved": 1} and outM["moved_run_again_for_these"] == [BOARD + "11"]
      and bytes_of(11) == writer["bytes"] and [e["result"] for e in json.loads(pathlib.Path(outM["undo"]).read_text())["items"]].count("moved") == 1, (rcM, outM))
rcM2, outM2, _e = cli(BF.apply, run_dir=str(RUN3))
check("12 …and the next apply fills it (one set), keeping the writer's text", outM2["results"] == {"set": 1}, outM2)
check("12 …the record is there and the writer's description is kept", rec_of(11) is not None and raw(11)["description"] == "- Edited by a writer that takes no lock", None)

# ---- 13. a store that is a subdirectory of the repository (as the live board-data is)
T2 = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-sub-"))
def commit2(rel, d, ct):
    f = T2 / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    assert git("add", "-A", cwd=T2).returncode == 0
    r = git("commit", "-q", "-m", rel, ct=ct, cwd=T2); assert r.returncode == 0, r.stderr
assert git("init", "-q", cwd=T2).returncode == 0
commit2("README", {"x": 1}, now0 - 9 * HR)      # a file at the repository's root
V11 = [(now0 - 5 * HR, version(now0 - 5 * HR, now0 - 5 * HR, steps=STEPS0)), (now0 - 3 * HR, version(now0 - 3 * HR, now0 - 3 * HR, steps=STEPS1)), (now0 - 2 * HR, version(now0 - 2 * HR, now0 - 3 * HR, steps=STEPS1))]
for ct_, v_ in V11: commit2("board-data/g/11.json", {"id": "11", **v_}, ct_)
commit2("other/g/11.json", {"id": "11", **version(now0 - MIN, now0 - MIN, mover="home-other")}, now0 - MIN)                  # the same file name in a sibling folder, newer
commit2("board-data-old/g/11.json", {"id": "11", **version(now0 - MIN, now0 - MIN, mover="home-other")}, now0 - MIN)        # a folder whose name starts with the store's own
SUB = T2 / "board-data"
log_, why_ = LP.store_log(SUB)
check("13 the store's log from a subdirectory of the repository holds only the files of that folder, named relative to it (no prefix, no file of a sibling folder or of the repository's root), each with its path in the repository",
      why_ == "" and list(log_) == ["g/11.json"] and len(log_["g/11.json"]) == 3 and {x[2] for x in log_["g/11.json"]} == {"board-data/g/11.json"}, (why_, {k: [x[2] for x in v] for k, v in log_.items()}))
vs_, why2_ = LP.git_versions(SUB, "g/11.json")
check("13 …its versions are the three of the item, at their commit times, oldest first", why2_ == "" and [t for t, _v in vs_] == [float(int(t)) for t, _v in V11], (why2_, [t for t, _v in vs_]))
reset()
in_sub = LP.one(HOST, "g11", dry=True, git_store=SUB, now=now0)
in_flat = LP.one(HOST, "g11", dry=True, git_store=T / "store", now=now0)
check("13 …and the pass over the subdirectory store gives the record the flat store gives (step 1 done at the real write), not the newer file of the sibling folders", in_sub["action"] == "would_set" and (in_sub["kind"], in_sub["what"], in_sub["at"]) == ("step_done", "step 1 done", now0 - 3 * HR)
      and (in_sub["kind"], in_sub["what"], in_sub["at"]) == (in_flat["kind"], in_flat["what"], in_flat["at"]), (in_sub, in_flat))
deeper = LP.store_log(T2 / "board-data" / "g")
check("13 a folder one level deeper reads the same way (its prefix is longer), and a folder that does not exist is a problem, not an empty History", deeper[1] == "" and list(deeper[0]) == ["11.json"] and LP.store_log(T2 / "no-such-folder")[1] != "", (deeper[1], list(deeper[0])))

# ---- 14. the plan compares the times
rowA = {"item": BOARD + "1", "action": "would_set", "class": "", "at": 100.0, "kind": "comment"}
check("14 the plan's signature carries each item's time and kind: a different time or kind is a different plan; a refused row has none", BF.signature([rowA]) != BF.signature([{**rowA, "at": 101.0}]) and BF.signature([rowA]) != BF.signature([{**rowA, "kind": "pr_merged"}])
      and BF.signature([rowA]) == BF.signature([{**rowA, "action": "set"}]) and BF.signature([{**rowA, "action": "refused", "class": "unreadable_history", "at": 1.0}]) == BF.signature([{**rowA, "action": "refused", "class": "unreadable_history", "at": 2.0}]), None)
check("14 …except a time that is `now` (clamped), which moves with the clock by itself", BF.signature([{**rowA, "clamped": True, "at": 5.0}]) == BF.signature([{**rowA, "clamped": True, "at": 9.0}]) and BF.signature([{**rowA, "clamped": True}]) != BF.signature([rowA]), None)
check("14 the pass marks a record that is `now` as clamped (the version ten minutes ahead) and no other", dry[20]["clamped"] is True and all(dry[i]["clamped"] is False for i in (11, 12, 13, 14, 16, 19, 22)), {i: dry[i].get("clamped") for i in dry})
reset(); snapQ = snapshot()
mprog_svc._merge_tied = lambda rows, now: [(r, f"{r['repo']}#{r['n']}", {"g19": "anchored"}) for r in rows if r["n"] == 9]
st_, d_ = call(op="lastact", items=[f"g{i}" for i in OPEN], dry=True)
planf = T / "lactfill-plan.json"; planf.write_text(json.dumps(d_["results"], default=str), encoding="utf-8")
RUN4 = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-run4-"))
rcP, outP, errP = cli(BF.apply, run_dir=str(RUN4), plan=str(planf))
check("14 an apply whose plan is the dry run's goes ahead (the version a little ahead of the clock is `now` in both and does not make the plan differ)", rcP == 3 and outP["results"] == {"set": 8} and rec_of(19)["at"] == newer, (rcP, errP[-300:]))
reset(); snapQ = snapshot()
elog_before = ELOG.path().read_text(encoding="utf-8")
with open(ELOG.path(), "a", encoding="utf-8") as f_: f_.write(json.dumps({"ts": now0 - 2 * MIN, "repo": "owner/repo", "n": 9, "kind": "comment", "refs": []}) + "\n")      # an event lands after the dry run: item 19's time is now another
rcQ, outQ, errQ = cli(BF.apply, run_dir=str(RUN4), plan=str(planf))
check("14 an event that arrived after the dry run changes an item's time: the apply says the times differ and writes nothing (no file, no new pass folder)", rcQ == 1 and "times they would get" in errQ and snapshot() == snapQ
      and len([x for x in RUN4.iterdir() if UM.PASS_DIR_RX.fullmatch(x.name)]) == 1, (rcQ, errQ[-400:]))
rcQ2, outQ2, errQ2 = cli(BF.apply, run_dir=str(RUN4), plan=str(planf), allow_changed_plan=True)
check("14 …and --allow-changed-plan applies it, with the newer time", rcQ2 == 3 and rec_of(19)["at"] == now0 - 2 * MIN, (rcQ2, errQ2[-300:], rec_of(19)))
ELOG.path().write_text(elog_before, encoding="utf-8"); mprog_svc._merge_tied = orig_tied; reset()

# ---- 15. the hub's logs cannot be read: the dry run warns and the real pass refuses
snapT = snapshot()
orig_read = MLOG.read
def broken_read(*a, **k): raise RuntimeError("the log cannot be read")
MLOG.read = broken_read
RUN5 = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-run5-"))
try:
    tied_x, why_x = LP.ties(HOST, now0)
    st_dry, d_dry = call(op="lastact", items=["g11"], dry=True)
    st_real, d_real = call(op="lastact", items=["g11"], pass_id="20260101-000000-abcdea")
    rcT, outT, errT = cli(BF.apply, run_dir=str(RUN5))
finally: MLOG.read = orig_read
check("15 a log that cannot be read is not swallowed: the ties come back empty with the reason", tied_x == {} and "merge log was not read" in why_x and "RuntimeError" in why_x, (tied_x, why_x))
check("15 the route's dry run still answers, with `ties_problem` set; the real pass is refused whole (400) and writes nothing", st_dry == 200 and "merge log" in d_dry["ties_problem"] and d_dry["results"][0]["action"] == "would_set"
      and st_real == 400 and "could not be read" in d_real["error"] and snapshot() == snapT, (st_dry, d_dry.get("ties_problem"), st_real, d_real))
check("15 --apply refuses before it backs anything up or writes: exit 1, the reason named, no pass folder, no file changed", rcT == 1 and "plan is refused" in errT and "merge log" in errT and snapshot() == snapT
      and not [x for x in RUN5.iterdir() if UM.PASS_DIR_RX.fullmatch(x.name)], (rcT, errT[-400:]))
check("15 …and with the logs readable again the same call is served", call(op="lastact", items=["g11"], dry=True)[1].get("ties_problem") is None, None)
wrap = T / "lactfill-dry-wrapper.py"
wrap.write_text(f"""import importlib.abc, importlib.util, sys
sys.path.insert(0, {STACK!r})
class Patch(importlib.abc.MetaPathFinder):      # the dry run loads the pass module after it has switched to its copy; this makes its ties read fail when it does
    def find_spec(self, name, path, target=None):
        if name != "stackshot.model.last_activity_pass": return None
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(name); load = spec.loader.exec_module
        def exec_module(mod):
            load(mod); mod.ties = lambda S, now: ({{}}, 'forced for the test')
        spec.loader.exec_module = exec_module
        return spec
sys.meta_path.insert(0, Patch())
from stackshot.tools import last_activity_backfill as BF
sys.exit(BF.main(['--store', {str(T / 'store')!r}]))
""", encoding="utf-8")
CFGM["migration"] = False
pw = subprocess.run([sys.executable, str(wrap)], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml"})
check("15 the dry run prints the warning in its summary (and at the top) and says --apply refuses; it still reads the History and writes nothing", pw.returncode == 0 and pw.stdout.count("WARNING") == 2 and "forced for the test" in pw.stdout and "--apply refuses until" in pw.stdout
      and "items the pass would write: 8 of" in pw.stdout and snapshot() == snapT, (pw.returncode, pw.stdout[-900:], pw.stderr[-500:]))

# ---- 16. the anchors cannot be read: reported as a ties problem, so the real pass refuses
CFGM["migration"] = True
reset(); snapA = snapshot()
def broken(*a, **k): raise RuntimeError("the anchors cannot be read")
sample = [{"ts": now0 - HR, "repo": "owner/repo", "n": 9, "kind": "comment", "refs": []}]
# the anchors file read as a whole fails (the first read of `_merge_tied`: it raises, and `ties` reports it); or the anchors are read but the pages of the repository cannot be made from them (the read `_merge_tied` used to log and
# go on from, with no ties by anchor: now the answer carries the problem)
for label, owner_, attr, raises in (("the anchors file", _anc, "load", True), ("the pages made from the anchors", _mtie, "repo_pages", False)):
    keep = getattr(owner_, attr)
    RUNA = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-runa-"))
    setattr(owner_, attr, broken)
    try:
        try: res_tied, raised = mprog_svc._merge_tied(sample, now0), False
        except RuntimeError: res_tied, raised = None, True
        tied_a, why_a = LP.ties(HOST, now0)
        st_dry, d_dry = call(op="lastact", items=["g11"], dry=True)
        st_real, d_real = call(op="lastact", items=["g11"], pass_id="20260101-000000-abcdeb")
        rcA, outA, errA = cli(BF.apply, run_dir=str(RUNA))
    finally: setattr(owner_, attr, keep)
    check(f"16 {label} cannot be read: `_merge_tied` " + ("raises (as it always did)" if raises else "still answers (the live passes tie the rest) and says why in its answer's `problem`"),
          raised if raises else (not raised and isinstance(res_tied, list) and len(res_tied) == 1 and "anchors could not be read" in getattr(res_tied, "problem", "")), (raised, res_tied, getattr(res_tied, "problem", None)))
    check(f"16 …the ties come back empty with the reason (a ties problem), {label}", tied_a == {} and why_a != "" and ("anchors could not be read" in why_a or "could not be tied" in why_a) and "RuntimeError" in why_a, (tied_a, why_a))
    check(f"16 …the route's dry run still answers with `ties_problem` set; the real pass is refused whole (400) and writes nothing, {label}", st_dry == 200 and d_dry["ties_problem"] and d_dry["results"][0]["action"] == "would_set"
          and st_real == 400 and "could not be read" in d_real["error"] and snapshot() == snapA, (st_dry, d_dry.get("ties_problem"), st_real, d_real))
    check(f"16 …--apply refuses before it backs anything up or writes: exit 1, no pass folder, no file changed, {label}", rcA == 1 and "plan is refused" in errA and snapshot() == snapA
          and not [x for x in RUNA.iterdir() if UM.PASS_DIR_RX.fullmatch(x.name)], (rcA, errA[-400:]))
check("16 with the anchors readable `_merge_tied` has no problem, and the same call is served", getattr(mprog_svc._merge_tied(sample, now0), "problem", None) == "" and call(op="lastact", items=["g11"], dry=True)[1].get("ties_problem") is None, None)

# ---- 17. the plan read twice is the same plan
reset(); snapR = snapshot()
plan_a = call(op="lastact", items=[f"g{i}" for i in OPEN], dry=True)[1]["results"]
plan_b = call(op="lastact", items=[f"g{i}" for i in OPEN], dry=True)[1]["results"]
check("17 the plan read twice is the same plan: the same signature (items, times, kinds, refused ones), the same action and words for every item, and no file written", len(plan_a) == len(OPEN) and BF.signature(plan_a) == BF.signature(plan_b)
      and [(r["item"], r["action"], r.get("kind"), r.get("what")) for r in plan_a] == [(r["item"], r["action"], r.get("kind"), r.get("what")) for r in plan_b] and snapshot() == snapR, (BF.signature(plan_a), BF.signature(plan_b)))
RUN7 = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-run7-"))
app7 = DirectApp()
rc7, out7, err7 = cli(BF.apply, app=app7, run_dir=str(RUN7))
check("17 --apply reads the plan twice before its first write (two dry calls, then the writes), and the two readings agree so it writes", rc7 == 3 and app7.log[:2] == ["lastact-dry", "lastact-dry"] and "lastact" in app7.log[2:] and "differ" not in err7 and "changed while" not in err7
      and out7["results"] == {"set": 8}, (rc7, app7.log, err7[-300:]))

# ---- 18. a dry run that cannot end clean exits 1
reset(); snapX = snapshot()
wrap2 = T / "lactfill-dry-wrapper2.py"
wrap2.write_text(f"""import importlib.abc, importlib.util, sys
sys.path.insert(0, {STACK!r})
class Patch(importlib.abc.MetaPathFinder):      # the dry run loads the pass module after it has switched to its copy; this makes the third pass over each item (its second pass on the copy) still write
    def find_spec(self, name, path, target=None):
        if name != "stackshot.model.last_activity_pass": return None
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(name); load = spec.loader.exec_module
        def exec_module(mod):
            load(mod); real = mod.one; calls = {{}}
            def one(S, gid, **kw):
                r = real(S, gid, **kw); calls[gid] = calls.get(gid, 0) + 1
                return {{**r, "action": "set"}} if calls[gid] == 3 else r
            mod.one = one
        spec.loader.exec_module = exec_module
        return spec
sys.meta_path.insert(0, Patch())
from stackshot.tools import last_activity_backfill as BF
sys.exit(BF.main(['--store', {str(T / 'store')!r}]))
""", encoding="utf-8")
CFGM["migration"] = False
px = subprocess.run([sys.executable, str(wrap2)], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml"})
check("18 a dry run whose second pass on the copy would still change something exits 1 (it still prints its summary and writes nothing live)", px.returncode == 1 and "a second pass: " in px.stdout and "set " in px.stdout.split("a second pass: ")[-1].split("\n")[0]
      and snapshot() == snapX, (px.returncode, px.stdout[-500:], px.stderr[-500:]))
pn = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/tools/last_activity_backfill.py"), "--store", str(T / "store")], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/stackshot.toml"})
check("18 …while the same dry run with refused items in the store (two of them) and a pass that settles exits 0: a refusal is not a failure of the dry run", pn.returncode == 0 and "refused: 2" in pn.stdout, (pn.returncode, pn.stdout[-400:]))

# ---- 19. the store's log is made with --no-renames: a moved file is not hidden
T3 = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-mv-"))
assert git("init", "-q", cwd=T3).returncode == 0
def commit3(rel, d, ct):
    f = T3 / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    assert git("add", "-A", cwd=T3).returncode == 0
    r = git("commit", "-q", "-m", rel, ct=ct, cwd=T3); assert r.returncode == 0, r.stderr
commit3("g/30.json", {"id": "30", **version(now0 - 5 * HR, now0 - 5 * HR, steps=STEPS0)}, now0 - 5 * HR)
commit3("g/30.json", {"id": "30", **version(now0 - 4 * HR, now0 - 4 * HR, steps=STEPS1)}, now0 - 4 * HR)
assert git("mv", "g/30.json", "g/31.json", cwd=T3).returncode == 0      # the same bytes under another name: what git's rename detection pairs
assert git("commit", "-q", "-m", "move", ct=now0 - 3 * HR, cwd=T3).returncode == 0
plain_log = git("log", "--name-only", "--format=", cwd=T3).stdout.split()
nr_log = git("log", "--no-renames", "--name-only", "--format=", cwd=T3).stdout.split()
log3, why3 = LP.store_log(T3)
check("19 the fixture is one git's own rename detection pairs (plain `git log --name-only` names the old path once, the move commit only under the new name; --no-renames names both)", plain_log.count("g/30.json") == 2 and nr_log.count("g/30.json") == 3 and nr_log.count("g/31.json") == 1, (plain_log, nr_log))
check("19 the store's log shows the moved file under both names: the move is a commit of the old path (its deletion) and of the new one (its creation)", why3 == "" and len(log3.get("g/30.json", [])) == 3 and len(log3.get("g/31.json", [])) == 1
      and log3["g/30.json"][-1][0] == log3["g/31.json"][0][0], (why3, {k: len(v) for k, v in log3.items()}))
vs31, why31 = LP.git_versions(T3, "g/31.json")
check("19 …and the moved file has the History it has under its present name: one version at the move, nothing of the old name's two (git log --follow would bring them in)", why31 == "" and [t for t, _v in vs31] == [float(int(now0 - 3 * HR))], (why31, [t for t, _v in vs31]))

# ---- 20. an item file deleted and added back is refused
commit(25, version(now0 - 6 * HR, now0 - 6 * HR), now0 - 6 * HR)
assert git("rm", "-q", "g/25.json").returncode == 0 and git("commit", "-q", "-m", "delete 25", ct=now0 - 5 * HR).returncode == 0
commit(25, version(now0 - 4 * HR, now0 - 4 * HR, mover=BACK), now0 - 4 * HR)
vs25, why25 = LP.git_versions(T / "store", "g/25.json")
r25 = LP.one(HOST, "g25", dry=True, now=now0)
check("20 an item file git saw deleted and then added back has no readable History: the version at the deleting commit is missing", vs25 == [] and "missing from the store's git" in why25, (vs25, why25))
check("20 …so the pass refuses the item with the History class and the reason, and the file is left as it is", r25["action"] == "refused" and r25["class"] == LP.CLASS_HISTORY and "missing from the store's git" in r25["why"] and "last_activity" not in mt(25), r25)
CFGM["migration"] = True
snap25 = bytes_of(25); st25, d25 = call(op="lastact", items=["g25"])
check("20 …and the real pass writes nothing for it", st25 == 200 and d25["results"][0]["action"] == "refused" and bytes_of(25) == snap25, d25)
(T / "store/g/25.json").unlink()      # the sections below plan over every open item of the store

# ---- 21. --undo leaves an item closed since the pass alone
reset(); snapC = snapshot()
RUN8 = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-run8-"))
rc8, out8, err8 = cli(BF.apply, run_dir=str(RUN8))
undo8 = pathlib.Path(out8["undo"]) if isinstance(out8, dict) else pathlib.Path("/nonexistent")
d12c = raw(12); d12c["status"] = "completed"; write_file(12, without(d12c, "id"))      # a session closed it after the pass
closed_bytes = bytes_of(12)
rc9, out9, err9 = cli(BF.undo, undo=str(undo8))
check("21 --undo puts back the seven open items and leaves the closed one alone: its file is byte for byte as it was when it was closed, the record stays, and the answer names it", rc9 == 0 and out9["results"] == {"set": 7, "kept": 1}
      and out9["kept_because_closed_since_the_pass"] == [BOARD + "12"] and out9["kept_because_a_later_save_changed_them"] == [] and bytes_of(12) == closed_bytes and rec_of(12) is not None
      and all(rec_of(i) is None for i in (11, 13, 19, 20, 22)) and rec_of(16) == FUTURE, (rc9, out9, err9[-300:]))
st_c, d_c = call(op="unlastact", items=[{"item": "g12", "before": {"last_activity": None}, "after": {"last_activity": rec_of(12)}}])
check("21 …the route says why: kept, `it was closed since the pass`, and the file is untouched", d_c["results"][0]["action"] == "kept" and "closed since the pass" in d_c["results"][0]["why"] and bytes_of(12) == closed_bytes, d_c)
CFGM["migration"] = False

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
