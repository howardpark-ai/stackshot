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
from stackshot.web import server; from stackshot.model import last_activity as LA, last_activity_pass as LP, progress as PROG; from stackshot.tools import last_activity_backfill as BF; from stackshot.tools import until_migrate as UM; from stackshot.tools import stamp_phase as SP
from stackshot.anchors import event_log as ELOG, merge_log as MLOG
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda gid, owner, note, tag="wake": None
server._front_sender = lambda who: False
CFGM = server._cfg.CFG.setdefault("model", {})
CFGM.update(guards=True, watchers=True, pause=False, one_mover=True, handoff=True, switchover=False, migration=False)
sent = []
server._tell = lambda *a, **k: sent.append(("tell", a))

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
check("1 the skew is the one an event's own time is allowed", LA.SKEW_S == ELOG.AHEAD_S, (LA.SKEW_S, ELOG.AHEAD_S))

# ---- 2. the dry run
CFGM["migration"] = True
call = lambda machine="box-a", **body: server._client_post(machine, "migrate", {"sender": SENDER, **body})
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
held = []; orig_sw = server._stamp_write
def spying_write(*a, **k):
    held.append(server._ITEM_LOCK._is_owned()); return orig_sw(*a, **k)
server._stamp_write = spying_write
PID = "20260101-000000-abcdef"
st_, d_ = call(op="lastact", items=[f"g{i}" for i in OPEN], pass_id=PID)
server._stamp_write = orig_sw
res = {int(r["item"].split("#")[1]): r for r in d_["results"]} if st_ == 200 else {}
check("3 the pass fills the eight, leaves the one with a record, and refuses the two whose History does not read and the one dated ahead", [res[i]["action"] for i in (11, 12, 13, 14, 16, 19, 20, 22)] == ["set"] * 8
      and res[15]["action"] == "same" and [res[i]["action"] for i in (17, 18)] == ["refused"] * 2, {i: res[i]["action"] for i in res})
check("3 only metadata.last_activity changed in each filled file: every other byte of the item (top-level fields and every other metadata key) is the same",
      all(without(raw(i), "metadata") == without(orig[i], "metadata") and without(mt(i), "last_activity") == without(orig[i]["metadata"], "last_activity") for i in (11, 12, 13, 14, 16, 19, 20, 22)), None)
check("3 …the files of the items left as they are are byte for byte the same", all(bytes_of(i) == orig_bytes[i] for i in (15, 17, 18)), None)
check("3 …no clock moved (updated, confirmed, activity, state_updated, written_at), no commit was made, nobody was told, nothing was held", all(all(raw(i).get(k) == orig[i].get(k) for k in ("updated", "confirmed", "activity", "state_updated", "written_at", "written_by")) for i in OPEN)
      and head() == H0 and sent == [] and not server._watch.holding(), sent)
check("3 the records are the History's: step done at the real write, mover changed, created, PR merged", rec_of(11) == {"at": now0 - 3 * HR, "kind": "step_done", "what": "step 1 done"} and rec_of(12) == {"at": now0 - 90 * MIN, "kind": "state_change", "what": "mover changed"}
      and rec_of(13) == {"at": now0 - 26 * HR, "kind": "state_change", "what": "created"} and rec_of(14) == {"at": now0 - 50 * MIN, "kind": "pr_merged", "what": "PR 7 merged"}, [rec_of(i) for i in (11, 12, 13, 14)])
check("3 the item with a record keeps it, whatever its History says", rec_of(15) == KEEP, rec_of(15))
check("3 every record reads (last_activity.read) and none is dated after the clock", all(LA.read(raw(i), time.time()) is not None and rec_of(i)["at"] <= time.time() for i in (11, 12, 13, 14, 16, 19, 20, 22)), None)

# ---- 4. the refused class
check("4 an item with a torn version in its History is refused with the reason, the class, and is left as it is", res[18]["action"] == "refused" and res[18]["class"] == LP.CLASS_HISTORY and "does not read as JSON" in res[18]["why"] and "last_activity" not in mt(18), res[18])
check("4 an item with a version dated two days ahead is refused for it, and nothing is guessed", res[17]["action"] == "refused" and res[17]["class"] == LP.CLASS_HISTORY and "ahead of the clock" in res[17]["why"] and "last_activity" not in mt(17), res[17])
plain = pathlib.Path(_scratch.mkdtemp(prefix="lactfill-nogit-"))
nogit = LP.one(server, "g13", dry=True, git_store=plain)
write_file(23, version(now0 - 3 * HR, now0 - 3 * HR))
nogit2 = LP.one(server, "g23", dry=True, git_store=plain)
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
def runner(): done.append(LP.one(server, "g24", dry=True))
server._ITEM_LOCK.acquire()
th = threading.Thread(target=runner); th.start(); th.join(0.5)
waited = not done
server._ITEM_LOCK.release(); th.join(10)
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
orig_tied = server._merge_tied
server._merge_tied = lambda rows, now: [(r, f"{r['repo']}#{r['n']}", {"g19": "anchored"}) for r in rows if r["n"] == 9]      # the live tie is merge_tie's, covered by its own suite; here the lines are tied to one item
rows_ = LP.pr_rows(server, now0)
check("8 the two logs are read whole, each line on its own (a merge-log line is a merge)", sorted((r["kind"], r["n"]) for r in rows_) == [("ci_failed", 99), ("comment", 9), ("merged", 9), ("review", 9)], rows_)
tied = LP.ties(server, now0)
check("8 a tied event is a signal at the time the hub saw it, of its kind; a line stamped days ahead of the clock is dropped", [(s["kind"], s["what"], s["at"]) for s in tied.get("g19", [])] == [("pr_merged", "PR 9 merged", now0 - 3 * HR), ("comment", "comment on #9", newer)], tied)
r19 = LP.one(server, "g19", dry=True, tied=tied, now=now0)
check("8 …the newest of the History and the events is the record (a comment 20 minutes ago over a creation 8 hours ago)", r19["action"] == "would_set" and (r19["kind"], r19["at"]) == ("comment", newer), r19)
server._merge_tied = orig_tied
r19b = LP.one(server, "g19", dry=True, tied={}, now=now0)
check("8 …without the tie the record is the History's alone (created 8 hours ago)", (r19b["kind"], r19b["what"], r19b["at"]) == ("state_change", "created", now0 - 8 * HR), r19b)

# ---- 9. the script
class DirectApp:
    """The live server's route, called in this process (what LiveApplier does over HTTP)."""
    def __init__(self): self.log = []
    def call(self, body):
        self.log.append(body["op"] + ("-dry" if body.get("dry") else ""))
        return server._client_post("box-a", "migrate", {**body, "sender": SENDER})
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
check("9 the files the script wrote differ from the History's only in last_activity", all(without(mt(i), "last_activity") == without(json.loads(snapS0[f"{i}.json"])["metadata"], "last_activity") for i in (11, 12, 13, 14, 16, 19, 20, 22)), None)
rc2, out2, _e = cli(BF.apply)
check("9 a second apply writes nothing", rc2 == 3 and out2["filled"] == 0 and set(out2["left_over"]) == {BOARD + "17", BOARD + "18"}, (rc2, out2))
# a later save changes the record of one item (the event pass wrote a newer one): the undo keeps it
newer_rec = {"at": now0 - 1 * MIN, "kind": "ci_result", "what": "CI passing again on PR 5"}
d14 = raw(14); d14["metadata"]["last_activity"] = newer_rec; write_file(14, without(d14, "id"))
rc3, out3, _e = cli(BF.undo, undo=str(undo_file))
back = all(rec_of(i) is None for i in (11, 12, 13, 19, 20, 22)) and rec_of(16) == FUTURE
check("9 --undo puts the records back value for value on the items still as the pass left them (the key goes when it had none, the old value returns when it had one) and keeps the one a later write changed",
      rc3 == 0 and back and out3["results"] == {"set": 7, "kept": 1} and out3["kept_because_a_later_save_changed_them"] == [BOARD + "14"] and rec_of(14) == newer_rec, (rc3, out3, [rec_of(i) for i in (11, 16, 14)]))
check("9 …every other byte is back too: the files of the undone items are what they were before the pass", all(bytes_of(i) == snapS0[f"{i}.json"] or json.loads(bytes_of(i)) == json.loads(snapS0[f"{i}.json"]) for i in (11, 12, 13, 16, 19, 20, 22)), None)
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
check("10 …a fill needs no begin and holds nothing", st_ == 200 and d_["results"][0]["action"] == "set" and not server._watch.holding(), (st_, d_))
CFGM["migration"] = False

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
