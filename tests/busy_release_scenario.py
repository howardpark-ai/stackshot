"""Scenario test for the second proof of the refusal of a hold on an item its mover is moving: a release of a pull request tied to the item that is running (stackshot/audit/busy_hold.py `live_release`,
stackshot/service/gates.py `gate_busy_hold` and `BUSY_RELEASE_REFUSAL`, the server's `_busy_live`) — a scratch store, fixture items, fake units and release logs, no server socket, no network, no model call, no GitHub.

release.sh runs each release as the user unit stackshot-release-<n>.service, which stays active through the checks, the merge queue, the merge, the deploy and main's run. A hold from the item's mover is refused while
the unit of a pull request TIED TO THIS ITEM is active and its log (<state>/releases/pr-<n>.log) was written within 15 minutes; an older log is a stuck release, and a mover is never trapped. Unknown is never a refusal.

  1  refuses     the unit of a pull request the item is tied to by an anchor, by an open step's URL, by `PR #n` in a step, by a step's stored proof, or by its own words (merge_tie) refuses a hold and a date
                 alone; the text names the release, the unit, the log's age and its stage, and tells the mover to keep the item in hand or wait on the event by name; the stage is read from the log's own lines
  2  ties        what does NOT tie: another item's pull request, an anchored pull request with no unit, a unit of another repository's pull request with the same number, a pull request the item does not name
  3  passes      no unit, a unit read that raises, a log older than 15 minutes (the bound itself included), no log, a log that cannot be read, no own repository, anchors or an item that cannot be read; the same
                 early exits as the subagent proof: guard off, the owner, a sender that is not the mover, a closing write, done=, clear_*, a named blocker, a hand-off, an item that is not open, no `live`
  4  both arms   a subagent live OR a release live refuses (the subagent is named first), neither passes; a failing subagent read still lets the release arm speak
  5  tool        through the real update tool and `server._busy_live` (the unit list, the anchors and the logs read as the server reads them): the refused hold stores nothing, the same write passes once the unit
                 has ended or its log has gone quiet, work= passes; the reply note of a doing item is dropped while a tied release runs and stays when it does not
  6  shape       the log is never read while no unit runs, the check costs one unit read and the item, gates.py names no audit/ module, the text of the refusal

    tests/run-suite busy_release        -> exit 0 / 1"""
import contextlib, json, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="busyrel-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK)

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml      # never the host's session store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1                 # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                           # an isolated HOME
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state", "transcripts/-home-x"): (T / d).mkdir(parents=True)
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-owner", "home-stew", "marsh-builder", "quill-agent", "home-other"), 1)}
(T / "store/anchors.json").write_text("{}"); (T / "store/next-id").write_text("900")
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/quill": {"title": "Quill", "name": "Quill", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                               "board": [], "board_open": 0, "agents": {"quill-agent": "the front", "marsh-builder": "the back"}, "back_agents": {"marsh-builder": "the back"}}}}))
(T / "brain/projects/quill.md").write_text("---\ntitle: Quill\ndisplay-name: home-stew\nagents:\n  quill-agent: the front\n  background:\n    marsh-builder: the back\n---\n\n# Quill\n")
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()})); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1500]}" if got is not None else ""))

from fastmcp.exceptions import ToolError
from stackshot.audit import busy_hold, subagent_tie
from stackshot.core import config as _cfg
from stackshot.web import server
from stackshot.web import publish as _web_publish
from stackshot.service import gates, telling, update as update_svc
from stackshot.tools import next_report as _nr
from stackshot.web.tools import update as _wt_update
from stackshot.web.ui import releasing as _rel
from stackshot.model import steps as _steps

@contextlib.contextmanager
def patched(owner, **kv):
    """Names of a module replaced for a case, put back after."""
    old = {k: getattr(owner, k) for k in kv}
    for k, v in kv.items(): setattr(owner, k, v)
    try: yield
    finally:
        for k, v in old.items(): setattr(owner, k, v)
@contextlib.contextmanager
def cfg_model(**kv):
    """[model] keys set for a case (the config is read live), put back after."""
    m = _cfg.CFG.setdefault("model", {}); old = {k: m.get(k, "<absent>") for k in kv}
    m.update(kv)
    try: yield
    finally:
        for k, v in old.items():
            if v == "<absent>": m.pop(k, None)
            else: m[k] = v
def outcome(thunk):
    try: return ("ok", thunk())
    except ToolError as e: return ("refused", str(e))
    except Exception as e: return ("raised", f"{e.__class__.__name__}: {e}")

NOW = time.time()
OWNER = "Oliver"; BACK = "marsh-builder"; OTHER = "home-other"; PROJECT = "projects/quill"
import datetime as dt
FUT = (dt.datetime.fromtimestamp(NOW, dt.timezone(dt.timedelta(hours=4))) + dt.timedelta(days=3)).strftime("%Y-%m-%d")
def put(i, status="open", **meta):
    it = {"id": str(i), "gid": f"a{i}", "subject": f"[home] item {i}", "description": "- A thing", "status": status, "updated": NOW - 3600, "state_updated": NOW - 3600, "confirmed": NOW - 3600,
          "metadata": {"project": PROJECT, "next": f"{BACK}: do it", **meta}}
    (T / f"store/a/{i}.json").write_text(json.dumps(it), encoding="utf-8")
    return it
def read(i): return json.loads((T / f"store/a/{i}.json").read_text(encoding="utf-8"))
put(1, mover=BACK)                      # the item the cases hold
put(2, mover=BACK)                      # another open item of the same mover
put(3, mover=OTHER)                     # an item another session moves
put(4, status="completed", mover=BACK, outcome="done")
put(5, mover=BACK)
put(6, mover=BACK)

BOARD = "board" + chr(35)                                          # the board's id form, written out here so no literal id sits in the file: "@3" in a string below is item 3's shown id
def X(t): return re.sub(r"@(\d+)", lambda m: BOARD + m.group(1), t)
def sub(desc, brief="", **kw):
    desc, brief = X(desc), X(brief)
    return {"id": "x1", "description": desc, "brief": brief, "text": f"{desc}\n{brief}", "at": NOW, **kw}
def live_for(subs=None, raises=None, anch=None, items=None):
    """The gate's `live` callable as the server builds it (audit/busy_hold.py), over the scratch store and a fake `subagents`."""
    def live(gid, mover):
        return busy_hold.live_work(gid, mover, subagents=(lambda who: (_ for _ in ()).throw(raises)) if raises is not None else (lambda who: subs if who == BACK else []),
                                   items=items or (lambda: _nr.load_all(None)), anchored=lambda: anch or {}, same=server._handoff.ho_same, shown=_nr.shown)
    return live
def gate(live, sender=BACK, gid="a1", **kw):
    kw.setdefault("hold", True)
    return outcome(lambda: gates.gate_busy_hold(gid, sender, live=live, **kw))
def refused(got): return got[0] == "refused" and got[1].startswith("Refused: this item is being moved now: ")

# ---------------------------------------------------------------- fixtures: units, logs, the proof as the server builds it
OWN = "acme/stack"; OTHERREPO = "other/repo"
_rel._OWN[:] = [OWN]                                              # this checkout's repository, as releasing.own_repo reads it (read once per process)
UNITS_OUT = {"v": ""}
_rel._run = lambda argv: UNITS_OUT["v"]                           # never the host's systemd: `systemctl --user list-units` answers what a case says
def units_text(*ns): return "".join(f"stackshot-release-{n}.service loaded active running [systemd-run] /srv/stack/release.sh --run {n}\n" for n in ns)
RELDIR = T / "state/releases"; RELDIR.mkdir(parents=True)
STAMP = "2026-11-14T15:03:37Z "
QUEUED = STAMP + "in the merge queue (QUEUED position 1): 3 min since the enqueue, up to 40 min; reading it every 30s\n"
def tail(*lines): return "".join(STAMP + l + "\n" for l in lines)
def logfile(n, text=QUEUED, age=120.0):
    p = RELDIR / f"pr-{n}.log"; p.write_text(text, encoding="utf-8"); os.utime(p, (time.time() - age, time.time() - age)); return p
def rel_live(units=(77,), anch=None, own=OWN, logs=None, pages=None, raises=None, now=None, calls=None, step_prs=None, item=None):
    """The gate's `live` callable as the server builds the release arm (audit/busy_hold.py `live_release`), over the scratch store, fake units and fake logs (a dict {n: (mtime, tail)}; absent = no log)."""
    logs = {n: (NOW - 120.0, QUEUED) for n in units} if logs is None else logs
    def count(k):
        if calls is not None: calls.append(k)
    def U():
        count("units")
        if raises is not None: raise raises
        return set(units)
    def L(n):
        count(f"log{n}")
        v = logs.get(n)
        if isinstance(v, Exception): raise v
        return v
    def live(gid, mover):
        return busy_hold.live_release(gid, units=U, anchored=lambda: anch or {}, item=item or (lambda g: count("item") or server._svcstore._load(g)), own_repo=lambda: own, canon=_cfg.canon_repo,
                                      step_prs=step_prs or _rel.step_prs, pages=lambda: count("pages") or (pages or {}), log=L, now=lambda: NOW if now is None else now)
    return live
def both_for(subs=None, **kw):
    """The server's `_busy_live` as a callable over fakes: the subagent proof first, the release proof second."""
    a, b = live_for(subs or [], anch=kw.get("anch")), rel_live(**kw)
    return lambda g, w: a(g, w) or b(g, w)
ok = lambda got: got == ("ok", None)
A77 = {"a1": {f"{OWN}#77"}}
RELWORDS = lambda got: got[0] == "refused" and got[1].startswith("Refused: this item is being moved now: your release of PR #")
def reset(): put(1, mover=BACK)
def setdesc(i, text):
    """The item's own description (put() puts keyword arguments in the metadata)."""
    it = read(i); it["description"] = text; (T / f"store/a/{i}.json").write_text(json.dumps(it), encoding="utf-8")

# ---------------------------------------------------------------- 1. refuses
want = ("Refused: this item is being moved now: your release of PR #77 is running on it (unit stackshot-release-77.service, its log written 2 min ago, in the merge queue (QUEUED position 1)), so it is not paused. "
        "Keep it in hand and write where its step stands (work=<one line>, state in progress), or wait on it by name (wait_event pr_released or pr_merged). Park it with a hold only once nothing of yours is running on it.")
got = gate(rel_live(anch=A77))
check("1 a running release of a pull request anchored to the item refuses the mover's hold, in exactly the words of the refusal", got == ("refused", want), got)
check("1 …the same text is the constant, formatted", gates.BUSY_RELEASE_REFUSAL.format(live="your release of PR #77 is running on it (unit stackshot-release-77.service, its log written 2 min ago, in the merge queue (QUEUED position 1))") == want)
check("1 …the subagent's refusal keeps its own text (no wait_event clause), so the two are told apart", gates.BUSY_HOLD_REFUSAL.format(live="x") != want and "pr_released" not in gates.BUSY_HOLD_REFUSAL)
check("1 …the refusal names no item of the board", not re.search(r"\b(?:" + BOARD + r"\d+|a\d+)\b", got[1]), got)
check("1 …and a date alone (a wake or an until the write turns into a hold) is refused as a hold is", RELWORDS(gate(rel_live(anch=A77), hold=False, wake=FUT)) and RELWORDS(gate(rel_live(anch=A77), wake=FUT)), gate(rel_live(anch=A77), hold=False, wake=FUT))
check("1 …and wait_kind time, the plain park, is refused", RELWORDS(gate(rel_live(anch=A77), wait_kind="time")))
put(5, mover=BACK, hold=True)
check("1 …an item already on hold is refused again when the write sets the hold", RELWORDS(gate(rel_live(anch={"a5": {f"{OWN}#77"}}), gid="a5")), gate(rel_live(anch={"a5": {f"{OWN}#77"}}), gid="a5"))
put(5, mover=BACK)
check("1 the anchor of another spelling of this repository (an old name through [github.moved]) ties as the repository's own", RELWORDS(gate(rel_live(anch={"a1": {"ACME/Stack#77"}}))), gate(rel_live(anch={"a1": {"ACME/Stack#77"}})))
# tied by an open step
put(1, mover=BACK, next=f"{BACK}: release https://github.com/{OWN}/pull/78 once the checks are green")
check("1 (fixture) the open step's URL is read by releasing.step_prs as this repository's pull request 78", _rel.step_prs(read(1)["metadata"]) == {78}, _rel.step_prs(read(1)["metadata"]))
got = gate(rel_live(units=(78,)))
check("1 a running release of the pull request an open step links by URL refuses (no anchor needed)", RELWORDS(got) and "PR #78 is running on it (unit stackshot-release-78.service" in got[1], got)
put(1, mover=BACK, next=f"{BACK}: release PR #79 and watch main")
check("1 (fixture) `PR #79` in an open step reads as this repository's pull request 79", _rel.step_prs(read(1)["metadata"]) == {79}, _rel.step_prs(read(1)["metadata"]))
check("1 a running release of the pull request an open step names as `PR #79` refuses", RELWORDS(gate(rel_live(units=(79,)))), gate(rel_live(units=(79,))))
put(1, mover=BACK, next=f"{BACK}: land the fix", step_proof={_steps.key(f"{BACK}: land the fix"): f"pr_released {OWN}#80"})
check("1 (fixture) an open step's stored proof pr_released of this repository reads as pull request 80", _rel.step_prs(read(1)["metadata"]) == {80}, _rel.step_prs(read(1)["metadata"]))
check("1 a running release of the pull request an open step's proof names refuses", RELWORDS(gate(rel_live(units=(80,)))), gate(rel_live(units=(80,))))
put(1, mover=BACK, step_proof={_steps.key(f"{BACK}: do it"): f"pr_merged {OWN}#81"})
check("1 …a pr_merged proof ties as a pr_released one does", RELWORDS(gate(rel_live(units=(81,)))), gate(rel_live(units=(81,))))
# tied by the item's own words (merge_tie)
put(1, mover=BACK); setdesc(1, f"- Fixes the export, https://github.com/{OWN}/pull/82")
check("1 a running release of the pull request the item's description links by URL refuses", RELWORDS(gate(rel_live(units=(82,)))), gate(rel_live(units=(82,))))
put(1, mover=BACK); setdesc(1, "- Fixes the export in PR 83")
check("1 a number written `PR 83` ties only an item that speaks of this repository (its project page holds an anchor in it): a project of another repository does not", ok(gate(rel_live(units=(83,), pages={}))), gate(rel_live(units=(83,), pages={})))
check("1 …and one of this repository's project does", RELWORDS(gate(rel_live(units=(83,), pages={OWN: {PROJECT}}))), gate(rel_live(units=(83,), pages={OWN: {PROJECT}})))
check("1 …and an item with a pull request of the repository anchored to it speaks of it too", RELWORDS(gate(rel_live(units=(83,), anch={"a1": {f"{OWN}#5"}}))), gate(rel_live(units=(83,), anch={"a1": {f"{OWN}#5"}})))
put(1, mover=BACK, next=f"{BACK}: do it\n{BACK}: wait for #84 to be released")
check("1 …`#84` in the next lines ties likewise (merge_tie's own reading of a number)", RELWORDS(gate(rel_live(units=(84,), pages={OWN: {PROJECT}}))), gate(rel_live(units=(84,), pages={OWN: {PROJECT}})))
reset()

# the stage: the log's own words
def stage_in(text, **kw):
    got = gate(rel_live(anch=A77, logs={77: (NOW - 120.0, text)}, **kw))
    m = re.search(r"its log written 2 min ago(, .*?)?\), so it is not paused", got[1])
    return m.group(1)[2:] if m and m.group(1) else "" if m else got
for what, line, stage in (
        ("queued", "in the merge queue (QUEUED position 1): 3 min since the enqueue, up to 40 min; reading it every 30s", "in the merge queue (QUEUED position 1)"),
        ("awaiting checks", "in the merge queue (AWAITING_CHECKS position 2): 9 min since the enqueue, up to 40 min; reading it every 30s", "in the merge queue (AWAITING_CHECKS position 2)"),
        ("a state with no position", "in the merge queue (MERGEABLE): 1 min since the enqueue", "in the merge queue (MERGEABLE)"),
        ("enqueued", "enqueued: the merge queue accepted the head 1a2b3c4", "enqueued in the merge queue"),
        ("checks", "checks on 1a2b3c4d: 1 of 1 run(s) of 1a2b3c4d not completed (poller file 30s old); waiting on the ci-runs file, no GitHub call", "checks on 1a2b3c4d"),
        ("the PR's tests", "waiting for the PR's tests on 1a2b3c4 (pending); 3 min of up to 40", "waiting on the PR's checks"),
        ("merged", "merged by the merge queue as b187281, 16 min after the enqueue", "merged by the merge queue"),
        ("deploying", "deploying b187281 at once: the merge queue ran the suites its selection picked", "deploying"),
        ("main's run", "main's run 43607500681 on 52ef35e: 1 of 1 run(s) of 52ef35e not completed (poller file 30s old)", "main's run 43607500681"),
        ("main's run, running", "main's run 4360750 is running, on 52ef35e (4 min so far); waiting for it to finish", "main's run 4360750"),
        ("a line that names none", "release queue: nothing to start (1 of at most 4 running; 1 listed)", ""),
        ("an empty log", "", "")):
    got = stage_in(tail(line) if line else "")
    check(f"1 the stage is read from the log's last line: {what}", got == stage, (got, line))
check("1 a line with no time (a command's own output) names no stage even when it reads like one", stage_in("deploying b187281 now\n") == "", stage_in("deploying b187281 now\n"))
check("1 …but it is skipped, not the end of the search: a timed stage line before it is read", stage_in(tail("deploying b187281 at once") + "  web/server.py  (server-side)\n.service: unchanged\n") == "deploying")
check("1 the newest of the last four timed lines that names a stage is the stage", stage_in(tail("deploying b1", "release queue: nothing to start", "release queue: nothing to start", "release queue: nothing to start")) == "deploying")
check("1 …a stage five timed lines back is not quoted (it may be long past)", stage_in(tail("deploying b1", "release queue: nothing to start", "release queue: nothing to start", "release queue: nothing to start", "release queue: nothing to start")) == "")
check("1 …the newer stage wins over an older one", stage_in(tail("merged by the merge queue as b187281", "deploying b187281 at once")) == "deploying")
check("1 a log that is only a torn line, or not text, names no stage and still refuses", RELWORDS(gate(rel_live(anch=A77, logs={77: (NOW - 120.0, "��\x00\x01")}))))
check("1 the stage function on its own: a line is read after its words are collapsed to one line", busy_hold.stage_of("in   the merge queue\t(QUEUED position 3)") == "in the merge queue (QUEUED position 3)" and busy_hold.stage_of(None) == "" and busy_hold.stage_of("") == "")
check("1 the age is told in minutes, and under a minute as such", "log written under a minute ago" in gate(rel_live(anch=A77, logs={77: (NOW - 20.0, QUEUED)}))[1] and "log written 1 min ago" in gate(rel_live(anch=A77, logs={77: (NOW - 90.0, QUEUED)}))[1] and "log written 14 min ago" in gate(rel_live(anch=A77, logs={77: (NOW - 14 * 60.0 - 30.0, QUEUED)}))[1])
two = gate(rel_live(units=(77, 91), anch={"a1": {f"{OWN}#77", f"{OWN}#91"}}, logs={77: (NOW - 600.0, QUEUED), 91: (NOW - 60.0, tail("deploying b1"))}))
check("1 with two releases tied and running, the one written to most recently is named", RELWORDS(two) and "PR #91 is running on it" in two[1] and "deploying" in two[1], two)
check("1 …a tied release with a stuck log beside a fresh one: the fresh one is named", "PR #77 is running" in gate(rel_live(units=(77, 91), anch={"a1": {f"{OWN}#77", f"{OWN}#91"}}, logs={77: (NOW - 60.0, QUEUED), 91: (NOW - 5000.0, QUEUED)}))[1])

# ---------------------------------------------------------------- 2. what does not tie
reset()
check("2 an anchored pull request with no unit running never refuses (anchors are never pruned)", ok(gate(rel_live(units=(), anch=A77))), gate(rel_live(units=(), anch=A77)))
check("2 …nor does a unit of a pull request the item names nothing of", ok(gate(rel_live(units=(99,), anch=A77))), gate(rel_live(units=(99,), anch=A77)))
check("2 a unit of a pull request that is anchored to ANOTHER item (a2) never refuses this item", ok(gate(rel_live(anch={"a2": {f"{OWN}#77"}}))), gate(rel_live(anch={"a2": {f"{OWN}#77"}})))
check("2 …an item with no anchor, no step and no word naming any pull request is untied (a false negative, never a false refusal)", ok(gate(rel_live())), gate(rel_live()))
check("2 a unit whose number is another repository's pull request anchored to the item (a number collision) never refuses", ok(gate(rel_live(anch={"a1": {f"{OTHERREPO}#77"}}))), gate(rel_live(anch={"a1": {f"{OTHERREPO}#77"}})))
put(1, mover=BACK, next=f"{BACK}: release https://github.com/{OTHERREPO}/pull/77 first")
check("2 …a step's URL of another repository's pull request with the same number", ok(gate(rel_live())) and _rel.step_prs(read(1)["metadata"]) == set(), (gate(rel_live()), _rel.step_prs(read(1)["metadata"])))
put(1, mover=BACK, next=f"{BACK}: wait for {OTHERREPO} PR #77")
check("2 …`other/repo PR #77` in a step", ok(gate(rel_live())) and _rel.step_prs(read(1)["metadata"]) == set(), (gate(rel_live()), _rel.step_prs(read(1)["metadata"])))
put(1, mover=BACK); setdesc(1, f"- See https://github.com/{OTHERREPO}/pull/77")
check("2 …a description that links another repository's pull request 77", ok(gate(rel_live(pages={OWN: {PROJECT}}))), gate(rel_live(pages={OWN: {PROJECT}})))
reset()
check("2 a pull request number in no word of the item ties nothing", ok(gate(rel_live(pages={OWN: {PROJECT}}))))
put(1, mover=BACK); setdesc(1, "- Done in PR 770")
check("2 …whole: `PR 770` in the item's words does not tie unit 77", ok(gate(rel_live(pages={OWN: {PROJECT}}))), gate(rel_live(pages={OWN: {PROJECT}})))
put(1, mover=BACK); setdesc(1, "- Done in PR 77")
check("2 …and `PR 77` does tie it (the same fixture, the whole number)", RELWORDS(gate(rel_live(pages={OWN: {PROJECT}}))), gate(rel_live(pages={OWN: {PROJECT}})))
reset()
check("2 an item whose project page holds no anchor in the repository is not tied by a bare number in its words", ok(gate(rel_live(pages={OWN: {"projects/elsewhere"}}))) )
put(3, mover=OTHER)
check("2 an item another session moves (a3) is not refused even with its pull request live", ok(gate(rel_live(anch={"a3": {f"{OWN}#77"}}), gid="a3")), gate(rel_live(anch={"a3": {f"{OWN}#77"}}), gid="a3"))

# ---------------------------------------------------------------- 3. passes (unknown is never a refusal)
reset()
check("3 no unit running passes", ok(gate(rel_live(units=(), anch=A77))))
check("3 a unit read that raises (systemctl gone, no user bus) passes", ok(gate(rel_live(anch=A77, raises=OSError("no bus")))), gate(rel_live(anch=A77, raises=OSError("no bus"))))
check("3 a log written 14 min 59 s ago is a release that is running", RELWORDS(gate(rel_live(anch=A77, logs={77: (NOW - 899.0, QUEUED)}))))
check("3 …a log written exactly 15 minutes ago is stuck: the mover is never trapped", ok(gate(rel_live(anch=A77, logs={77: (NOW - 900.0, QUEUED)}))), gate(rel_live(anch=A77, logs={77: (NOW - 900.0, QUEUED)})))
check("3 …and one written an hour ago", ok(gate(rel_live(anch=A77, logs={77: (NOW - 3600.0, QUEUED)}))))
check("3 …a log dated ahead of the clock (a skew, however far) is fresh, not a stuck one: it is `under 15 minutes` old", RELWORDS(gate(rel_live(anch=A77, logs={77: (NOW + 30.0, QUEUED)}))) and RELWORDS(gate(rel_live(anch=A77, logs={77: (NOW + 3600.0, QUEUED)}))), gate(rel_live(anch=A77, logs={77: (NOW + 3600.0, QUEUED)})))
check("3 a unit with no log passes (unknown)", ok(gate(rel_live(anch=A77, logs={}))) and ok(gate(rel_live(anch=A77, logs={77: None}))))
check("3 a log that cannot be read passes", ok(gate(rel_live(anch=A77, logs={77: OSError("denied")}))), gate(rel_live(anch=A77, logs={77: OSError("denied")})))
check("3 a repository this checkout cannot name passes", ok(gate(rel_live(anch=A77, own=""))), gate(rel_live(anch=A77, own="")))
check("3 anchors that cannot be read pass", ok(outcome(lambda: gates.gate_busy_hold("a1", BACK, hold=True, live=lambda g, w: busy_hold.live_release(g, units=lambda: {77}, anchored=lambda: 1 / 0, item=server._svcstore._load, own_repo=lambda: OWN,
      canon=_cfg.canon_repo, step_prs=_rel.step_prs, pages=lambda: {}, log=lambda n: (NOW - 60.0, QUEUED), now=lambda: NOW)))))
check("3 an item that cannot be read passes", ok(gate(rel_live(anch=A77, item=lambda g: 1 / 0))), gate(rel_live(anch=A77, item=lambda g: 1 / 0)))
check("3 an unreadable step reader passes", ok(gate(rel_live(anch=A77, step_prs=lambda m: 1 / 0))))
check("3 a pull request the unit list gives that is no number is no unit", ok(gate(rel_live(units=("x",), anch=A77))))
check("3 a `live` that raises passes the write, and no `live` at all passes", ok(gate(lambda g, w: 1 / 0)) and ok(gate(None)))
# the proof itself answers "" for anything it cannot tell (the gate would also catch a raise, so the callable is asked directly)
direct = lambda **kw: rel_live(**kw)("a1", BACK)
check("3 the proof answers \"\" itself, never raising, when the unit list raises, the anchors raise, the item raises, the log raises or the repository cannot be named",
      direct(anch=A77, raises=OSError("x")) == "" and direct(anch=A77, logs={77: OSError("denied")}) == "" and direct(anch=A77, item=lambda g: 1 / 0) == "" and direct(anch=A77, own="") == ""
      and busy_hold.live_release("a1", units=lambda: {77}, anchored=lambda: 1 / 0, item=server._svcstore._load, own_repo=lambda: OWN, canon=_cfg.canon_repo, step_prs=_rel.step_prs, pages=lambda: {}, log=lambda n: (NOW, QUEUED), now=lambda: NOW) == "")
check("3 …and its words, when it can tell, are the refusal's start", direct(anch=A77).startswith("your release of PR #77 is running on it (unit stackshot-release-77.service"), direct(anch=A77))
check("3 an anchored pull request that is not running is not counted although its log is fresh (only a unit proves it)", ok(gate(rel_live(units=(99,), anch=A77, logs={77: (NOW - 60.0, QUEUED), 99: (NOW - 60.0, QUEUED)}))), gate(rel_live(units=(99,), anch=A77, logs={77: (NOW - 60.0, QUEUED), 99: (NOW - 60.0, QUEUED)})))
check("3 a step's pull request that is not running is not counted although its log is fresh", ok(gate(rel_live(units=(99,), step_prs=lambda m: {78}, logs={78: (NOW - 60.0, QUEUED), 99: (NOW - 60.0, QUEUED)}))))
check("3 two tied releases, one with no log and one fresh: the fresh one refuses (a missing log is skipped, not fatal)", "PR #91 is running" in gate(rel_live(units=(77, 91), anch={"a1": {f"{OWN}#77", f"{OWN}#91"}}, logs={91: (NOW - 60.0, QUEUED)}))[1], gate(rel_live(units=(77, 91), anch={"a1": {f"{OWN}#77", f"{OWN}#91"}}, logs={91: (NOW - 60.0, QUEUED)})))
check("3 …and with the log of one unreadable the other still speaks", "PR #91 is running" in gate(rel_live(units=(77, 91), anch={"a1": {f"{OWN}#77", f"{OWN}#91"}}, logs={77: OSError("x"), 91: (NOW - 60.0, QUEUED)}))[1])
# the early exits are the subagent proof's own
L77 = rel_live(anch=A77)
check("3 (the live proof refuses before the exits below)", RELWORDS(gate(L77)))
check("3 a sender that is not the item's mover is not refused (a3's mover is another session)", ok(gate(rel_live(anch={"a3": {f"{OWN}#77"}}), sender=BACK, gid="a3")))
check("3 …nor the owner, nor a write that names no sender", ok(gate(L77, sender=OWNER)) and ok(gate(L77, sender="")))
with cfg_model(busy_hold_guard=False):
    off = gate(L77)
check("3 `[model] busy_hold_guard = false` switches the release arm off too, read live (and back on after)", ok(off) and RELWORDS(gate(L77)), (off, gate(L77)))
check("3 a write that closes the item (status completed) is not refused", ok(gate(L77, status="completed")))
check("3 a write that ticks a step (done=) is not refused", ok(gate(L77, done=[1])) and ok(gate(L77, done="1")))
check("3 a write that drops the park (clear_hold, clear_wake, clear_wait) is not refused", all(ok(gate(L77, **{k: True})) for k in ("clear_hold", "clear_wake", "clear_wait")))
check("3 a write that is no hold and no date is not refused", ok(gate(L77, hold=False)) and ok(gate(L77, hold=False, wake="none")))
check("3 a wait that names its blocker is not refused (wait_kind, after, needs, ask_by)", ok(gate(L77, wait_kind="relay")) and ok(gate(L77, wait_kind="event")) and ok(gate(L77, after=["a2"])) and ok(gate(L77, needs=["external"])) and ok(gate(L77, ask_by=FUT)))
check("3 a hand-off to another session (mover=, a next line that hands it on) is not the mover's hold", ok(gate(L77, mover=OTHER)) and ok(gate(L77, next_text=f"{OTHER}: take it from here")))
check("3 a next line of the mover's own steps does not lift the refusal", RELWORDS(gate(L77, next_text=f"{BACK}: write the tests")))
put(4, status="completed", mover=BACK, outcome="done"); put(7, mover=OWNER)
check("3 a completed item, an item that does not exist, and an item the owner moves are not refused", ok(gate(rel_live(anch={"a4": {f"{OWN}#77"}}), gid="a4")) and ok(gate(L77, gid="a99999")) and ok(gate(rel_live(anch={"a7": {f"{OWN}#77"}}), gid="a7")))
put(1, mover=BACK, hold=True, wait_kind="event", wait_event=f"pr_released {OWN}#77")
check("3 an item whose stored wait names its blocker (an event wait) is not parked again by this check", ok(gate(L77)), gate(L77))
reset()

# ---------------------------------------------------------------- 4. both arms
SUB1 = [sub("Build @1: the export fix")]
got = gate(both_for(SUB1, anch=A77))
check("4 a subagent live and a release live: the subagent is named (its proof comes first), with its own refusal", refused(got) and 'your subagent "' in got[1] and "your release" not in got[1] and "pr_released" not in got[1], got)
check("4 a release live and no subagent: the release is named, with its own refusal", RELWORDS(gate(both_for([], anch=A77))))
check("4 a subagent live and no release: the subagent is named", 'your subagent "' in gate(both_for(SUB1, anch=A77, units=()))[1])
check("4 neither passes", ok(gate(both_for([], anch=A77, units=()))))
check("4 a subagent tied to another item of the mover and a release tied to this one: the release refuses", RELWORDS(gate(both_for([sub("Build @2: the other fix")], anch=A77))), gate(both_for([sub("Build @2: the other fix")], anch=A77)))
def broken_subs(gid, mover):
    return busy_hold.live_work(gid, mover, subagents=lambda who: (_ for _ in ()).throw(subagent_tie.Unreadable("no transcript")), items=lambda: _nr.load_all(None), anchored=lambda: {}, same=server._handoff.ho_same, shown=_nr.shown)
check("4 a mover whose subagents cannot be read (unknown) still lets a live release speak", RELWORDS(gate(lambda g, w: broken_subs(g, w) or rel_live(anch=A77)(g, w))))
check("4 …and when neither can be told it passes", ok(gate(lambda g, w: broken_subs(g, w) or rel_live(anch=A77, raises=OSError("x"))(g, w))))

# ---------------------------------------------------------------- 5. tool: the real update tool, the real `server._busy_live`
SUBS = []
def fake_server_subs(who, idx=None, now=None):
    if who != BACK: return []
    return SUBS
def update(i, **kw):
    kw.setdefault("sender", BACK)
    with patched(_web_publish, _publish=lambda *a, **k: None), patched(telling, tell_woken=lambda *a, **k: None):
        return outcome(lambda: _wt_update.stackshot_update(f"a{i}", **kw))
HOLD = dict(next=f"{BACK}: do it", wake=FUT, hold=True, wait_basis=f"the soak window ends {FUT}")
check("5 the real unit list is parsed from systemctl's own line shape: release_units reads the numbers of active release units", (UNITS_OUT.update(v=units_text(77, 225)), _rel.release_units())[1] == {77, 225} and (UNITS_OUT.update(v=""), _rel.release_units())[1] == set())
with patched(server, _mover_subagents=fake_server_subs), patched(server._rlive, released_anchors=lambda: dict(A77)):
    SUBS[:] = []
    UNITS_OUT["v"] = units_text(77); logfile(77, QUEUED, age=120.0)
    before = json.dumps(read(1), sort_keys=True)
    got = update(1, **HOLD)
    check("5 a hold while the release of the item's anchored pull request runs is refused through the real tool, naming the release, its unit, its log and its stage", RELWORDS(got) and "PR #77 is running on it (unit stackshot-release-77.service, its log written 2 min ago, in the merge queue (QUEUED position 1))" in got[1], got)
    check("5 …and the refused write stores nothing", json.dumps(read(1), sort_keys=True) == before and not read(1)["metadata"].get("until") and not read(1)["metadata"].get("hold"))
    got = update(1, until=FUT, next=f"{BACK}: do it", wait_basis=f"the soak window ends {FUT}")
    check("5 …an until alone (a date the write turns into a hold) is refused as a hold is", RELWORDS(got), got)
    got = update(1, sender=BACK, work={"text": "PR 77 in the merge queue", "state": "in progress"})
    check("5 …a status line with work= (keeping it in hand) goes through", got[0] == "ok", got)
    reset()
    UNITS_OUT["v"] = ""
    got = update(1, **HOLD)
    check("5 the same hold passes and is stored once the unit has ended (a failed or finished release has none)", got[0] == "ok" and bool(read(1)["metadata"].get("until")), (got, read(1)["metadata"]))
    reset(); UNITS_OUT["v"] = units_text(77); logfile(77, QUEUED, age=16 * 60.0)
    got = update(1, **HOLD)
    check("5 …and while the unit runs but its log has been quiet for 16 minutes (a stuck release) the hold is stored", got[0] == "ok" and bool(read(1)["metadata"].get("until")), (got, read(1)["metadata"]))
    reset(); logfile(77, QUEUED, age=60.0)
    (RELDIR / "pr-77.log").unlink()
    got = update(1, **HOLD)
    check("5 …and a unit with no log at all passes", got[0] == "ok", got)
    reset(); logfile(77, QUEUED, age=60.0); UNITS_OUT["v"] = units_text(78)
    got = update(1, **HOLD)
    check("5 …and a unit of a pull request the item is not tied to passes (the unit of PR 78 is another item's)", got[0] == "ok", got)
    reset(); UNITS_OUT["v"] = units_text(77)
    got = update(1, **{**HOLD, "sender": OWNER})
    check("5 the owner's own hold is not refused", not RELWORDS(got), got)
    reset()
    with cfg_model(busy_hold_guard=False):
        got = update(1, **HOLD)
    check("5 with the switch off the hold is stored through the tool", got[0] == "ok" and bool(read(1)["metadata"].get("until")), (got, read(1)["metadata"]))
    reset()
    got = update(1, **{**HOLD, "done": [1]})
    check("5 a hold written together with done= is not refused", not RELWORDS(got), got)
    reset()
    SUBS[:] = [sub("Build @1: the export fix")]
    got = update(1, **HOLD)
    check("5 both live through the tool: the subagent is named, with its own text", refused(got) and X('your subagent "Build @1: the export fix"') in got[1] and "your release" not in got[1], got)
    reset(); SUBS[:] = []
    # the units cannot be listed at all: a box with no systemd, the failover box
    def no_systemd(argv): raise FileNotFoundError("systemctl")
    with patched(_rel, _run=no_systemd):
        got = update(1, **HOLD)
    check("5 a box where the unit list cannot be had (no systemctl) passes the hold", got[0] == "ok", got)
    reset()
with patched(server, _mover_subagents=lambda who, idx=None, now=None: (_ for _ in ()).throw(subagent_tie.Unreadable("no transcript of the session on this box"))), patched(server._rlive, released_anchors=lambda: dict(A77)):
    UNITS_OUT["v"] = units_text(77); logfile(77, QUEUED, age=60.0)
    got = update(1, **HOLD)
    check("5 a mover whose subagents cannot be read (unknown) does not hide a live release through the tool", RELWORDS(got), got)
    reset()
with patched(server._rlive, released_anchors=lambda: 1 / 0), patched(server, _mover_subagents=fake_server_subs):
    got = update(1, **HOLD)
    check("5 anchors the server cannot read are unknown: the write passes", got[0] == "ok", got)
    reset()
UNITS_OUT["v"] = ""
# the failover box: a stale copy of a log and no unit
logfile(77, QUEUED, age=30.0)
check("5 a stale log with no unit (the failover box's stale copies) is never read as a release", server._busy_live("a1", BACK) == "")
# the real proof, nothing but the unit list replaced
UNITS_OUT["v"] = units_text(77)
with patched(server, _mover_subagents=fake_server_subs), patched(server._rlive, released_anchors=lambda: dict(A77)):
    check("5 server._busy_live answers the words of the release for an item whose anchored pull request is released now", server._busy_live("a1", BACK).startswith("your release of PR #77 is running on it (unit stackshot-release-77.service"), server._busy_live("a1", BACK))
    check("5 …and \"\" for another item of the mover", server._busy_live("a2", BACK) == "")
UNITS_OUT["v"] = ""

# the reply note
NOTE = "this item is doing, but its next reads as a wait"
WAITING_NEXT = f"{BACK}: the first nightly run ends overnight; record its counts and cost in the morning"
def doing(i): put(i, mover=BACK, needs=[BACK], state="doing")
def note_of(i, **kw):
    doing(i)
    with patched(server, _mover_subagents=fake_server_subs):
        return update(i, next=WAITING_NEXT, **kw)
A90 = {"a8": {f"{OWN}#90"}}
logfile(90, tail("deploying b1"), age=60.0)
doing(8); base = update(8, next=WAITING_NEXT)
check("5 with no release running the doing item's wait wording draws the note, as before", base[0] == "ok" and base[1].count(NOTE) == 1, base)
UNITS_OUT["v"] = units_text(90)
with patched(server._rlive, released_anchors=lambda: dict(A90)):
    got = note_of(8)
    check("5 …no note while a release of a pull request tied to the item runs (its wait wording is about the mover's own release); the write itself goes through", got[0] == "ok" and NOTE not in got[1] and "overnight" in read(8)["metadata"]["next"], got)
    logfile(90, tail("deploying b1"), age=20 * 60.0)
    got = note_of(8)
    check("5 …the note stays when that release's log has been quiet for 20 minutes", got[0] == "ok" and got[1].count(NOTE) == 1, got)
    logfile(90, tail("deploying b1"), age=60.0)
    with cfg_model(busy_hold_guard=False):
        got = note_of(8)
    check("5 …and with the switch off", got[0] == "ok" and got[1].count(NOTE) == 1, got)
with patched(server._rlive, released_anchors=lambda: {"a2": {f"{OWN}#90"}}):
    got = note_of(8)
    check("5 …and the note stays when the running release is tied to another item", got[0] == "ok" and got[1].count(NOTE) == 1, got)
with patched(server._rlive, released_anchors=lambda: dict(A90)), patched(_rel, _run=lambda argv: (_ for _ in ()).throw(OSError("no bus"))):
    got = note_of(8)
    check("5 …and when the unit list cannot be read", got[0] == "ok" and got[1].count(NOTE) == 1, got)
UNITS_OUT["v"] = ""

# ---------------------------------------------------------------- 6. shape and cost
calls = []
check("6 with no unit running nothing else is read: no item, no pages, no log", ok(gate(rel_live(units=(), anch=A77, calls=calls))) and calls == ["units"], calls)
calls.clear()
check("6 an item tied by an anchor to the one unit that runs: one unit read, the item once, that pull request's log once, and no page read", RELWORDS(gate(rel_live(units=(77,), anch=A77, calls=calls))) and sorted(calls) == ["item", "log77", "units"], calls)
calls.clear()
check("6 …with another unit beside it the item's words and the project pages are read once, and only the tied pull request's log", RELWORDS(gate(rel_live(units=(77, 91), anch=A77, calls=calls, logs={77: (NOW - 60.0, QUEUED), 91: (NOW - 60.0, QUEUED)}))) and sorted(calls) == ["item", "log77", "pages", "units"], calls)
calls.clear()
check("6 a unit tied to nothing reads no log", ok(gate(rel_live(units=(99,), calls=calls))) and not [c for c in calls if c.startswith("log")], calls)
calls.clear()
check("6 an own-repository that cannot be named reads no item and no log", ok(gate(rel_live(anch=A77, own="", calls=calls))) and calls == ["units"], calls)
gsrc = pathlib.Path(STACK, "stackshot/service/gates.py").read_text(encoding="utf-8")
check("6 gates.py names no audit/ module (the proof is handed in as a callable)", "stackshot.audit" not in gsrc and "from stackshot import audit" not in gsrc)
check("6 the gate chooses the release refusal by the words' own prefix, and that prefix is what live_release writes", gates.BUSY_RELEASE_PREFIX == busy_hold.RELEASE_WORDS == "your release of PR #" and gate(rel_live(anch=A77))[1].count(gates.BUSY_RELEASE_PREFIX + "77 is running on it") == 1)
check("6 the units are the release script's own (stackshot-release-<n>.service), listed by the board's own reader", "stackshot-release-" in pathlib.Path(STACK, "stackshot/web/ui/releasing.py").read_text(encoding="utf-8") and busy_hold.RELEASE_FRESH_S == 15 * 60.0)
check("6 the refusal names wait_event kinds that exist: pr_released and pr_merged are in the tools' shared text", all(k in " ".join(pathlib.Path(STACK, "stackshot/web/tools/text/shared.md").read_text(encoding="utf-8").split()) for k in ("pr_released", "pr_merged")))
check("6 the log's end is read through a bounded tail, a unit's number through int", busy_hold.LOG_TAIL_BYTES <= 64 * 1024 and busy_hold.STAGE_LINES == 4)
big = RELDIR / "pr-95.log"; big.write_text("x" * 200000 + "\n" + tail("deploying b1"), encoding="utf-8")
got = busy_hold.release_log(95)
check("6 release_log reads only the end of a long log (never the whole file), with its time", got is not None and len(got[1]) <= busy_hold.LOG_TAIL_BYTES and "deploying" in got[1] and abs(got[0] - time.time()) < 60, (got and (len(got[1]), got[0])))
check("6 …and None for a log that is not there", busy_hold.release_log(96) is None)

print(f"busy_release scenario: {len(ran) - len(fails)}/{len(ran)} checks")
_scratch.cleanup()
if fails:
    print("FAILED:", *fails, sep="\n  "); sys.exit(1)
print(f"ok: busy_release scenario, {len(ran)} checks")
