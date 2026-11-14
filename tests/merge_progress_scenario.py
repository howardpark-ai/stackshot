"""Scenario test for the merge pass: a pull request merged for an item is recorded on it (`metadata.merged_seen`, a History line, a save of the server's own with activity kind `event`), whether or not the merge
settles a step. The hub writes one line per merge to its merge log (anchors/merge_log.py, read by `mprog_svc._merge_progress_tick`), and a merge is tied to open items by merge_tie (an anchor scoped to the item, the
pull request's body naming the item, the item's own words naming it). Fixture items, panes that are files in a temp folder, a fake clock (every pass is given its `now`, and the saves are stamped from a fake `time`),
no live store, no network, no model call.

  1  pure: progress.merges and progress.moved (a merge newly recorded is a "merged" signal; the model/progress.py list of what counts as the item having moved is what the last-activity record reads)
  2  merge_log (refs, pull_of, line_for, read, append, normal, shown) and merge_tie (names, repo_pages, tied)
  3  the pass: the items a merge is tied to are saved, the others are left alone; the offset, a malformed line, an item that cannot be read or saved, the backlog older than six hours, the minute anchor pass

    tests/run-suite merge_progress       -> exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="laddersil-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/audit", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-docs", "home-peer", "home-peer2", "home-peer3", "home-send", "home-beta-front", "home-stew", "home-beta-stew", "home-fleet")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
ALPHA = {"home-front": "the front", "home-docs": "keeps the pages", "team-back": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": proj("home-stew", ALPHA, {k: ALPHA[k] for k in ("home-docs", "team-back")}),
    "projects/beta": proj("home-beta-stew", {"home-beta-front": "the front"}, {})}}))
for key, name, agents in (("alpha", "home-stew", ALPHA), ("beta", "home-beta-stew", {"home-beta-front": "the front"})):
    back = [k for k in agents if k in ("home-docs", "team-back")]
    front = [k for k in agents if k not in back]
    (T / f"brain/projects/{key}.md").write_text(f"---\ntitle: {key}\ndisplay-name: {name}\nagents:\n" + "".join(f"  {k}: {agents[k]}\n" for k in front)
                                                 + ("  background:\n" + "".join(f"    {k}: {agents[k]}\n" for k in back) if back else "") + f"---\n\n# {key}\n\n## Current state\n\nSTATE-OF-{key.upper()}: the sample task is in progress.\n\n<!-- timeline -->\n\n## Timeline\n", encoding="utf-8")
(T / "store/next-id").write_text("1"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
MIN = 60.0; H = 3600.0
B = now0 - 6 * H                  # the stall pass first ran then (before every clock below)
ZONE = __import__("datetime").timezone(__import__("datetime").timedelta(hours=4))   # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
local = lambda ts: __import__("datetime").datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%dT%H:%M")
def put(i, project="projects/alpha", mover="home-peer", status="open", act=None, **meta):
    """An open doing item on `mover`, last written and last active `act` minutes before now0 (its other clocks recent: a bare confirm, a save of the server's)."""
    base = {"owner": U["home-front"], "project": project, "next": f"{mover}: do the thing", "state": "doing", "needs": [mover]}
    if mover: base["mover"] = mover
    base.update(meta)
    at = now0 - (60 if act is None else act) * MIN
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": at, "state_updated": at, "confirmed": at,
                                                       "activity": at, "written_at": at, "written_by": "home-front", "metadata": base}))
def close(*ids):
    for i in ids:
        d = rd(i); d["status"] = "completed"; (T / f"store/a/{i}.json").write_text(json.dumps(d))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def ho(i): return mt(i).get("handoff") or {}
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:300]}" if got is not None else ""))
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.waits import stall as S; from stackshot.audit import audit_run as AR; from stackshot.service import audit_ticks as audit_ticks_svc; from stackshot.service import event_activity as event_activity_svc
from stackshot.service import wait_fixes as _wait_fixes_svc
from stackshot.web.tools import get as _get_tool
from stackshot.web.tools import notes as _notes_tool
from stackshot.service import client_reads as client_reads_svc, recycle as recycle_svc, merge_progress as mprog_svc
from stackshot.service import asks as asks_svc, wait_gates as wait_gates_svc, answer_handover as handover_svc
from stackshot.service import store as _service_store
from stackshot.core import config as _cfg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import fleet_events as fleetev
from stackshot.service import migrations as migsvc
from stackshot.service import page_debt as pdebt_svc
from stackshot.service import handoff as handoff_svc
from stackshot.service import handoff_cold as hcold_svc
from stackshot.service import checks as checks_svc, proofs as proofs_svc, released as released_svc
from stackshot.service import pane_recovery as _pane_recovery
from stackshot.service import mover_steps as _mover_steps
from stackshot.service import owner_words as _owner_words
from stackshot.service import stall as stall_svc, stall_tick as stalltick_svc
from stackshot.service import wakes as wakes_svc
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []
_real_tell = telling.tell_woken
def _tell(gid, owner, note, tag="wake"):
    th = _real_tell(gid, owner, note, tag)
    if th: THREADS.append(th)
    return th
telling.tell_woken = _tell
def drain():
    while THREADS: THREADS.pop(0).join(30)
    while hcold_svc.HO_COLD_THREADS: hcold_svc.HO_COLD_THREADS.pop(0).join(30)
    while THREADS: THREADS.pop(0).join(30)
def pushes(): return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
def pushes_to(who, gid=None): return [p for p in pushes() if p[0] == U[who] and (gid is None or gid in p[1])]
def recovery_pushes(gid): return [p for p in pushes_to("home-fleet", gid) if "fleet recovery:" in p[1]]
def look_notices(who, i): return [p for p in pushes_to(who, f"a{i}") if "nothing written for" in p[1]]
def stall_notices(who, i): return [p for p in pushes_to(who, f"a{i}") if "have had no turn running" in p[1]]
def set_cfg(**kw): _cfg.CFG["model"] = dict(kw)
set_cfg(); _cfg.CFG["stall"] = {}
_cfg.CFG.setdefault("fleet", {})["operator_session"] = "home-fleet"
COLD_MSGS = []
def cold(answer, status="ok"):
    def run(msg):
        COLD_MSGS.append(msg)
        return {"status": status, "text": json.dumps(answer) if isinstance(answer, dict) else str(answer), "duration_s": 0.1, "usage": {}, "note": "stub"}
    hcold_svc.COLD_RUNNER = run
cold("no json at all here")
def cli_row(who, status, at):
    (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": status, "statusUpdatedAt": int(at * 1000), "updatedAt": int(at * 1000)}))
def no_row(who): (T / f"cli/{os.getpid()}-{who}.json").unlink(missing_ok=True)
handoff_svc.CLI_SESSIONS = T / "cli"
stall_svc.stall_since(B)
def log_of(i): return S.log_of(mt(i))
ROLES = {"home-peer": {"role": "background"}, "home-peer2": {"role": "background"}, "home-peer3": {"role": "background"}, "team-back": {"role": "background"}, "home-front": {"role": "front"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env():
    return AR.Env(roles=ROLES, fallback=lambda p: "home-front", builder=lambda p: "team-back", page_of=lambda p: ("", None), deliver=deliver, push=lambda to, text: (True, "delivered"), sessions=lambda: None,
                  pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})
def clear_records():
    for p in (T / "state/audit").glob("*.json"): p.unlink()
    sent.clear()
def load(*ids): return {f"a{i}": _service_store._load(f"a{i}") for i in ids}
def entry(i): return stall_svc.stall_load().get(f"a{i}")

from stackshot.model import progress as PG
class _Clock:
    """The server's `time` module for the saves below: the item's `updated` is stamped from the server's own clock, which a scenario with a fake `now` must be able to set."""
    t = None
    def __getattr__(self, n): return getattr(time, n)
    def time(self): return time.time() if self.t is None else self.t
CLK = _Clock(); server.time = event_activity_svc.time = client_reads_svc.time = recycle_svc.time = mprog_svc.time = _wait_fixes_svc.time = _notes_tool.time = _get_tool.time = fleetev.time = migsvc.time = pdebt_svc.time = handoff_svc.time = hcold_svc.time = checks_svc.time = proofs_svc.time = released_svc.time = asks_svc.time = audit_ticks_svc.time = wait_gates_svc.time = handover_svc.time = _pane_recovery.time = _mover_steps.time = _owner_words.time = stall_svc.time = stalltick_svc.time = CLK; writes.time = CLK
def save_at(ts, i, mutate, writer="home-peer", **kw):
    """A real `writes.save` of item `i` at the fake time `ts`, `mutate` changing the loaded item first: the stamp is the one a live write takes."""
    d_ = _service_store._load(f"a{i}"); mutate(d_); CLK.t = ts
    try: writes.save(f"a{i}", d_, writer=writer, **kw)
    finally: CLK.t = None

def step(text, status, at=0): return {"text": text, "status": status, "by": "x", "at": at}
base = {"status": "open", "metadata": {"mover": "m", "state": "doing", "needs": ["m"], "phase": "alive", "steps": [step("a", "open"), step("b", "done", 5)]}}
def with_meta(**kw): return {**base, "metadata": {**base["metadata"], **kw}}
def waits_after(i, dep):
    d_ = rd(i); d_["metadata"].pop("state", None); d_["metadata"].pop("needs", None); d_["metadata"]["after"] = [dep]; (T / f"store/a/{i}.json").write_text(json.dumps(d_))
import datetime as _dt
def iso(ts): return _dt.datetime.fromtimestamp(ts, ZONE).strftime("%Y-%m-%dT%H:%M")

# ================================================================ a pull request merged for the item is recorded on it, whether or not it settles a step: the hub's merge log (anchors/merge_log.py), tied to items by merge_tie
from stackshot.anchors import merge_log as ML; from stackshot.model import merge_tie as MT
from stackshot.anchors.anchorhub import core as HUB
W_ = "https://github.com/acme/widgets"
def shown(i): return f"board#{i}"
def merge_pass(now):
    """One merge pass at `now`, the saves stamped at it; the board id board#<n> is the fixture item a<n> for the pass (the fixtures are a<n>: [github] issues_letter), and the other sections' ids are left as they were."""
    gh_ = _cfg.CFG.setdefault("github", {}); had = gh_.get("issues_letter"); gh_["issues_letter"] = "a"; CLK.t = now
    try: return mprog_svc._merge_progress_tick(now)
    finally:
        CLK.t = None
        if had is None: gh_.pop("issues_letter", None)
        else: gh_["issues_letter"] = had
check("merge_log.refs: the board ids a body names, once each, in order; a bare #n, owner/repo#n and board-ish words are not", ML.refs("Closes " + shown(9301) + " and " + shown(9302) + ", " + shown(9301) + " again; see #5, acme/widgets#6, a board #9303") == [shown(9301), shown(9302)] and ML.refs(None) == []
      and len(ML.refs(" ".join(f"board#{n}" for n in range(1, 30)))) == ML.MAX_REFS, ML.refs("Closes " + shown(9301) + " and " + shown(9302) + ", " + shown(9301) + " again; see #5, acme/widgets#6, a board #9303"))
check("merge_log.pull_of: the anchor's own id, else the link of the event (a pull request page or a comment on it); a release or a bare repository has none",
      ML.pull_of("github:Acme/Widgets#21") == ("acme/widgets", 21) and ML.pull_of("github:acme/widgets@notifications", f"{W_}/pull/22#issuecomment-5") == ("acme/widgets", 22)
      and ML.pull_of("github:acme/widgets@releases", "https://github.com/acme/widgets/releases/tag/v1") == ("", 0) and ML.pull_of("slack:C1") == ("", 0), None)
check("merge_log.line_for: only a merge (the type among a burst's, joined with +) of a pull request makes a line", ML.line_for("github:acme/widgets#21", "", "pr_merged", [shown(9203)], 5.0) == {"ts": 5.0, "repo": "acme/widgets", "n": 21, "refs": [shown(9203)]}
      and ML.line_for("github:acme/widgets#21", "", "comment+pr_merged", [], 5.0)["n"] == 21 and ML.line_for("github:acme/widgets#21", "", "pr_closed", [], 5.0) is None and ML.line_for("github:acme/widgets#21", "", "", [], 5.0) is None
      and ML.line_for("github:acme/widgets@releases", "", "pr_merged", [], 5.0) is None, None)
check("merge_tie.names: a URL names the pull request in any repository; #n, PR n and PR #n only for a repository the item speaks of without a URL; a prefix of a longer number or another repository's #n does not",
      MT.names(f"see {W_}/pull/21/files", "acme/widgets#21") and not MT.names(f"see {W_}/pull/210", "acme/widgets#21") and MT.names("PR #21 and more", "acme/widgets#21", ["acme/widgets"]) and MT.names("done in PR 21", "acme/widgets#21", ["acme/widgets"])
      and MT.names("#21 landed", "acme/widgets#21", ["acme/widgets"]) and not MT.names("#21 landed", "acme/widgets#21", ["other/repo"]) and not MT.names(shown(9221) + " and acme/widgets#21", "acme/widgets#21", ["acme/widgets"])
      and not MT.names("#210", "acme/widgets#21", ["acme/widgets"]), None)
check("progress.merges: a key of merged_seen counts as a merge recorded (one with the same pull request in released_told is one); progress.moved sees it newly added",
      PG.merges(with_meta(merged_seen=["a/b#1"], released_told=["merged a/b#1", "a/b#2"])) == frozenset({"merged a/b#1"}) and PG.moved(base, with_meta(merged_seen=["a/b#1"])) == ["merged"]
      and not PG.moved(with_meta(merged_seen=["a/b#1"]), with_meta(merged_seen=["a/b#1"])) and not PG.moved(base, with_meta(merged_seen=["a/b#1"]), False), None)

# the pure half: what counts as the item having moved (model/progress.py, read by the last-activity record)
check("moved: a step newly marked done or dropped is progress; one already marked, or a step only reworded or added, is not",
      PG.moved(base, with_meta(steps=[step("a", "done", 9), step("b", "done", 5)])) == ["step"] and PG.moved(base, with_meta(steps=[step("a", "dropped", 9), step("b", "done", 5)])) == ["step"]
      and not PG.moved(base, with_meta(steps=[step("a2", "open"), step("b", "done", 5), step("c", "open")])) and not PG.moved(base, with_meta(steps=[step("a", "open"), step("b", "done", 7)])), None)
check("moved: a state change is progress: the status (closed), the phase, the kind of a wait, the mover, the state and the needs",
      PG.moved(base, {**base, "status": "completed"}) == ["state"] and PG.moved(base, with_meta(phase="waiting", waits_on="time")) == ["state"] and PG.moved(base, with_meta(mover="n")) == ["state"]
      and PG.moved(base, with_meta(state="verifying")) == ["state"] and PG.moved(base, with_meta(needs=["m", "decision"])) == ["state"] and not PG.moved(base, with_meta(needs=["m"])), None)
check("moved: a save that is no one's write (a migration, the server's bookkeeping: real=False) moves the item only by its status and phase, never by a step mark, a merge note, a mover, a state or needs",
      not PG.moved(base, with_meta(steps=[step("a", "done", 9), step("b", "done", 5)]), False) and not PG.moved(base, with_meta(mover="n"), False) and not PG.moved(base, with_meta(released_told=["merged o/r#5"]), False)
      and PG.moved(base, {**base, "status": "completed"}, False) == ["state"] and PG.moved(base, with_meta(phase="waiting", waits_on="time"), False) == ["state"], None)
check("moved: a status line (work), a note, a description or a reworded next step is not progress", not PG.moved(base, with_meta(work=[{"id": "build", "state": "in progress", "agent": "m", "ts": 1}], next="m: other words"))
      and not PG.moved(base, {**base, "description": "other"}), None)
check("moved: a pull request newly recorded as merged is progress; a release (a bare ref) and one already recorded are not",
      PG.moved(base, with_meta(released_told=["merged o/r#5"])) == ["merged"] and not PG.moved(base, with_meta(released_told=["o/r#5"])) and not PG.moved(with_meta(released_told=["merged o/r#5"]), with_meta(released_told=["merged o/r#5"])), None)
check("moved: an item with no phase stored yet is not changed by the save that stores it; a new item is progress", not PG.moved({**base, "metadata": {k: v for k, v in base["metadata"].items() if k != "phase"}}, base) and PG.moved(None, base) == ["created"], None)

# the log, the anchors and the items: a merge tied to an item is recorded on it at the pass's time.
def line(n, refs=(), at=20 * MIN): return {"ts": now0 + at, "repo": "acme/widgets", "n": n, "refs": list(refs)}
anchors_ = {"projects/alpha": [{"url": f"{W_}/pull/21", "items": ["a200"]}, {"url": f"{W_}/pull/22"}, {"url": f"{W_}/pull/30", "items": ["a205"]}, {"url": f"{W_}/pull/32", "items": ["a207"]}, {"url": f"{W_}/pull/28", "items": ["a212", "a213"]}]}
(T / "store/anchors.json").write_text(json.dumps(anchors_))
def fixture(i, **meta): put(i, act=30, mover="home-peer", **meta)
for i in (200, 201, 202, 203, 204, 205, 207, 211): fixture(i)
fixture(206, project="projects/beta")      # an item of another project: its bare "#25" may be another repository's
d_ = rd(204); d_["description"] = f"- Waits on {W_}/pull/23\n- Done when it lands"; (T / "store/a/204.json").write_text(json.dumps(d_))
d_ = rd(205); d_["metadata"]["steps"] = [step("home-peer: land PR #24 and check it", "open")]; (T / "store/a/205.json").write_text(json.dumps(d_))
d_ = rd(206); d_["metadata"]["steps"] = [step("home-peer: land PR #25 and check it", "open")]; (T / "store/a/206.json").write_text(json.dumps(d_))      # the number alone, in a project that holds no anchor in that repository and with none of its own: not tied
d_ = rd(211); d_["metadata"]["steps"] = [step("home-peer: land PR #26 and check it", "open")]; (T / "store/a/211.json").write_text(json.dumps(d_))      # the number alone, in the project that holds anchors in that repository: tied
fixture(212, hold=True, wake=iso(now0 + 5 * H), phase="waiting", waits_on="time")      # held and waiting for a dated wake, with an anchor on the merged pull request: not on the stall ladder
fixture(213); waits_after(213, "a203")             # ordered after an open item, the same anchor: not on the stall ladder
fixture(208, project="projects/alpha"); close(208)                                   # a closed item named by the body: left alone
for ln in (line(21), line(22), line(23), line(24), line(25), line(26), line(28), line(99), line(31, [shown(201), shown(208), shown(9299)]), line(40, [shown(201)])):
    ML.append(ln)
saved = merge_pass(now0 + 21 * MIN)
check("the pass saves exactly the items a merge is tied to: anchored (a200), the body naming it (a201, also by a merge no anchor holds), its own words (a204 by URL, a205 by number with a pull request of its repository anchored, a211 by number in the project that holds the repository's anchors)",
      sorted(saved) == ["a200", "a201", "a204", "a205", "a211"], saved)
check("…each was saved at the pass's time, recorded the key in merged_seen, and said why in the History", all(rd(i)["updated"] == now0 + 21 * MIN and rd(i)["activity"] == now0 + 21 * MIN for i in (200, 201, 204, 205, 211))
      and mt(200).get("merged_seen") == ["acme/widgets#21"] and sorted(mt(201).get("merged_seen")) == ["acme/widgets#31", "acme/widgets#40"] and mt(204).get("merged_seen") == ["acme/widgets#23"] and mt(205).get("merged_seen") == ["acme/widgets#24"]
      and any("an anchor of the item names it" in x["text"] for x in log_of(200)) and any("description names the item" in x["text"] for x in log_of(201)) and any("own words name it" in x["text"] for x in log_of(204)),
      ([rd(i).get("updated") for i in (200, 201, 204, 205)], [mt(i).get("merged_seen") for i in (200, 201, 204, 205)], log_of(201)))
check("a project-wide anchor's merge (a202's project holds #22 for nobody), an unrelated merge (#99), a bare number in an item of another project (a206: its PR number may be another repository's), a closed item named by the body (a208) and an anchored item the board shows held (a212) or ordered after an open item (a213) move nothing: the clock stays and nothing is written",
      all(rd(i)["updated"] == now0 - 30 * MIN and rd(i)["activity"] == now0 - 30 * MIN and "merged_seen" not in mt(i) for i in (202, 203, 206, 207, 208, 212, 213)) and rd(208).get("status") == "completed" and rd(202)["updated"] == now0 - 30 * MIN, [rd(i).get("updated") for i in (202, 203, 206, 207, 208)])
check("the pass keeps where it stopped: a second pass reads no line again and saves nothing", merge_pass(now0 + 22 * MIN) == [] and ML.read(mprog_svc._merge_progress_offset())[0] == [], mprog_svc._merge_progress_offset())
check("…and a line a pass sees again (the offset lost) is not saved twice: the item holds the key already", (mprog_svc._merge_progress_save(0), merge_pass(now0 + 23 * MIN))[1] == [] and mt(200).get("merged_seen") == ["acme/widgets#21"] and rd(200)["updated"] == now0 + 21 * MIN, mt(200))
close(200, 201, 202, 203, 204, 205, 206, 207, 211, 212, 213)

# the first pass on a state directory with no offset reads only lines the pass could use (six hours back); the offset file is then written
(T / "state/merge-progress.json").unlink(missing_ok=True)
fixture(209, project="projects/alpha"); fixture(210, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/50", "items": ["a209"]}, {"url": f"{W_}/pull/51", "items": ["a210"]}]}))
ML.append({"ts": now0 - 7 * H, "repo": "acme/widgets", "n": 50, "refs": []}); ML.append({"ts": now0 - 1 * H, "repo": "acme/widgets", "n": 51, "refs": []})
saved = merge_pass(now0)
check("the first pass: a merge older than six hours is skipped (a209), a recent one counts (a210); the offset is kept", saved == ["a210"] and "merged_seen" not in mt(209) and mprog_svc._merge_progress_offset() == ML.read(0)[1], (saved, mprog_svc._merge_progress_offset()))
close(209, 210)

# a shorter or replaced merges.jsonl (the offset is past its end): read from the start with the first run's time filter, never a full replay
fixture(214, project="projects/alpha"); fixture(215, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/52", "items": ["a214"]}, {"url": f"{W_}/pull/53", "items": ["a215"]}]}))
off_before = mprog_svc._merge_progress_offset()
ML.path().write_text(json.dumps({"ts": now0 - 7 * H, "repo": "acme/widgets", "n": 52, "refs": []}) + "\n" + json.dumps({"ts": now0 - 1 * H, "repo": "acme/widgets", "n": 53, "refs": []}) + "\n", encoding="utf-8")
saved = merge_pass(now0)
check("the file replaced by a shorter one (offset past its end): read from the start, only the lines the clock could use (a merge 7 hours old is skipped, one an hour old counts), the offset is the new end",
      off_before > ML.size() and saved == ["a215"] and "merged_seen" not in mt(214) and mprog_svc._merge_progress_offset() == ML.size(), (off_before, ML.size(), saved, mprog_svc._merge_progress_offset()))
close(214, 215)

# one item that cannot be read or saved does not abort the pass: the others are saved, the failure is logged, the offset is stored
for i in (216, 217, 218): fixture(i, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/54", "items": ["a216", "a217", "a218"]}]}))
ML.append(line(54, at=-60))
_real_save, _real_load = writes.save, _service_store._load
def _bad_save(gid, *a, **kw):
    if gid == "a216": raise OSError("disk full")
    return _real_save(gid, *a, **kw)
def _bad_load(gid, *a, **kw):
    if gid == "a218" and _bad_load.on: raise OSError("unreadable")
    return _real_load(gid, *a, **kw)
_bad_load.on = False
writes.save, _service_store._load = _bad_save, _bad_load
import io as _io, contextlib as _cl
errs = _io.StringIO()
try:
    _bad_load.on = True
    with _cl.redirect_stderr(errs): saved = merge_pass(now0)
finally:
    writes.save, _service_store._load = _real_save, _real_load
check("an item whose save fails (a216) or whose read fails (a218) is logged and skipped; the other (a217) is saved, and the offset is stored so the pass does not repeat",
      saved == ["a217"] and "merged_seen" not in mt(216) and "merged_seen" not in mt(218) and mt(217).get("merged_seen") == ["acme/widgets#54"] and "a216 not saved" in errs.getvalue() and mprog_svc._merge_progress_offset() == ML.size(),
      (saved, errs.getvalue()[-300:], mprog_svc._merge_progress_offset(), ML.size()))
close(216, 217, 218)

# a malformed line between two good ones is logged and skipped, and the offset moves past it (it never stops the pass)
for i in (219, 220): fixture(i, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/70", "items": ["a219"]}, {"url": f"{W_}/pull/71", "items": ["a220"]}]}))
ML.append(line(70, at=-120))
with open(ML.path(), "a", encoding="utf-8") as f_:
    f_.write(json.dumps({"ts": "yesterday", "repo": "acme/widgets", "n": 5, "refs": []}) + "\n")      # a ts that is no number
    f_.write(json.dumps({"ts": now0, "repo": "acme/widgets", "n": "x", "refs": []}) + "\n")            # a pull request number that is none
    f_.write(json.dumps({"ts": now0, "repo": "not a repo", "n": 5, "refs": []}) + "\n")                # a repository that is none
    f_.write('{"ts": 1, "repo": "acme/wid\n')                                                           # a torn line that is no JSON at all
ML.append(line(71, at=-60))
errs = _io.StringIO()
with _cl.redirect_stderr(errs): saved = merge_pass(now0)
check("a bad line (a ts or a pull request number that is none, a repository that is none, a torn line) between two good ones is logged and skipped: both good ones are saved and the offset moves to the end",
      sorted(saved) == ["a219", "a220"] and errs.getvalue().count("line skipped") == 3 and mprog_svc._merge_progress_offset() == ML.size(), (saved, errs.getvalue()[-400:], mprog_svc._merge_progress_offset(), ML.size()))
check("…and the pass after it reads nothing again (the offset is past the bad lines)", merge_pass(now0 + 60) == [] and mprog_svc._merge_progress_offset() == ML.size(), None)
close(219, 220)

# the backlog of a downtime: on every pass (not only the first), a merge older than six hours is no news now, and is not recorded
for i in (221, 222): fixture(i, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/72", "items": ["a221"]}, {"url": f"{W_}/pull/73", "items": ["a222"]}]}))
ML.append(line(72, at=-30 * H)); ML.append(line(73, at=-60))
saved = merge_pass(now0)
check("a backlog line from 30 hours ago (the server was down) is not stamped on a pass that is not the first, a recent one is; the offset moves past both",
      saved == ["a222"] and "merged_seen" not in mt(221) and rd(221)["updated"] == now0 - 30 * MIN and mprog_svc._merge_progress_offset() == ML.size(), (saved, mprog_svc._merge_progress_offset(), ML.size()))
close(221, 222)

# the floor is the pass's own six hours and nothing else: a merge a little under it counts, one a little over it does not, whatever `[ladder] main_hours` (a retired key nothing reads) says
FLOOR_H = 6 * H
def floor_pass(label, n_young, n_old, items, ladder=None):
    """One merge pass at `now0` over two lines: a merge 5 hours 50 minutes old and one 6 hours 10 minutes old, each for its own anchored item; `ladder` is the config's `[ladder]` table for the pass (None: none) → the ids saved."""
    for i in items: fixture(i, project="projects/alpha")
    (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/{n_young}", "items": [f"a{items[0]}"]}, {"url": f"{W_}/pull/{n_old}", "items": [f"a{items[1]}"]}]}))
    ML.append(line(n_young, at=-(FLOOR_H - 10 * MIN))); ML.append(line(n_old, at=-(FLOOR_H + 10 * MIN)))
    had = _cfg.CFG.get("ladder")
    if ladder is None: _cfg.CFG.pop("ladder", None)
    else: _cfg.CFG["ladder"] = ladder
    try: return merge_pass(now0)
    finally:
        if had is None: _cfg.CFG.pop("ladder", None)
        else: _cfg.CFG["ladder"] = had
        close(*items)
saved = floor_pass("default", 80, 81, (223, 224))
check("the floor is six hours: a merge 5 hours 50 minutes old is recorded, one 6 hours 10 minutes old is not (a floor of 5 hours drops the first, one of 6.9 or 8 hours records the second)",
      saved == ["a223"] and "merged_seen" in mt(223) and "merged_seen" not in mt(224), (saved, mt(223).get("merged_seen"), mt(224).get("merged_seen")))
saved = floor_pass("main_hours 1", 82, 83, (225, 226), {"enabled": True, "main_hours": 1})
check("…with `[ladder] main_hours = 1` in the config the 5 hours 50 minute merge is still recorded (the floor is not main_hours plus two hours, which would be three)",
      saved == ["a225"] and "merged_seen" in mt(225) and "merged_seen" not in mt(226), (saved, mt(225).get("merged_seen"), mt(226).get("merged_seen")))
saved = floor_pass("main_hours 10", 84, 85, (227, 228), {"enabled": True, "main_hours": 10})
check("…and with `main_hours = 10` the 6 hours 10 minute merge is still not recorded (it would be, with a floor of twelve)",
      saved == ["a227"] and "merged_seen" in mt(227) and "merged_seen" not in mt(228), (saved, mt(227).get("merged_seen"), mt(228).get("merged_seen")))

# which ids a body names: board#N, a temporary id, a legacy letter-and-number id and an item link, as a message's ids are read (code, quotes, glued ids and the queue's groups are not)
TMP_ = "board" + "-tmp-box" + chr(35)      # a temporary id and an item link, built from pieces so no id-shaped or link-shaped text sits in the source
HOST_ = "https" + ":" + "//host" + "/items/"
body_ = "Closes " + shown(9301) + ", " + TMP_ + "4 and g12. In code `" + shown(9302) + "`, fenced:\n```\n" + shown(9303) + "\n```\nquoted \"" + shown(9304) + "\", x_" + shown(9305) + ", group g7, [" + shown(9306) + "]" + "(" + HOST_ + "9306) and " + HOST_ + "9307"
check("merge_log.refs reads a body as a message's ids are read (model/ids.py): board#N, a temporary id, a legacy gNN id and an item link count; fenced code, inline code, quoted text, an id with something glued on and a merge queue's group number do not",
      ML.refs(body_) == [shown(9301), TMP_ + "4", "g12", shown(9306), shown(9307)], ML.refs(body_))
fixture(230, project="projects/alpha"); fixture(231, project="projects/alpha")
(T / "store/anchors.json").write_text("{}")
ML.append(line(74, ["board" + "-tmp-nobox" + chr(35) + "9", "zz", "a230"], at=-60))
saved = merge_pass(now0)
check("the server resolves a stored ref as it resolves any id (a legacy letter-and-number id, a000-style, names a230); a ref that names no item (another machine's temporary id, a word) is skipped and does not stop the pass",
      saved == ["a230"] and mt(230).get("merged_seen") == ["acme/widgets#74"] and "merged_seen" not in mt(231), saved)

# a failure in the anchor pass does not stop the merge pass (the minute tick runs both)
fixture(232, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/75", "items": ["a232"]}]}))
ML.append({"ts": time.time(), "repo": "acme/widgets", "n": 75, "refs": []})
_real_anchor_pass = wakes_svc.anchor_pass
def _broken_anchor_pass(): raise RuntimeError("anchor pass broke")
wakes_svc.anchor_pass = _broken_anchor_pass
errs = _io.StringIO()
try:
    with _cl.redirect_stderr(errs): wakes_svc.minute_anchor_pass()
finally:
    wakes_svc.anchor_pass = _real_anchor_pass
check("_minute_anchor_pass: an anchor pass that raises is logged and the merge pass still runs (the item the merge is tied to is saved)",
      "anchor pass: RuntimeError: anchor pass broke" in errs.getvalue() and mt(232).get("merged_seen") == ["acme/widgets#75"], (errs.getvalue()[-300:], mt(232)))
close(230, 231, 232)

# the item's own words include each step's status tag and the lines of its next: a session writes "PR 261 released; PR 262 in review" on the tag, or names the pull request on its next line, before any step text says it
def tagged(text): return step("home-peer: do the thing", "open") | {"tag": {"text": text, "state": "in progress", "ts": now0 - 3 * H}}
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/9999"}]}))      # the project holds an anchor in the repository (for no item): a bare number in its items speaks of that repository
fixture(250, project="projects/alpha", steps=[tagged("PR 260 released; PR 261 in review")])
fixture(251, project="projects/alpha", next="home-peer: land PR #262 and check it")
fixture(252, project="projects/beta", steps=[tagged("PR 263 in review")])      # the number alone in a tag, in a project that holds no anchor in the repository: another repository's number, not tied
fixture(253, project="projects/alpha", steps=[tagged("PR 264 in review")])
fixture(254, project="projects/alpha", steps=[step("home-peer: do the thing", "open"), step("home-peer: an earlier step", "done") | {"tag": {"text": "PR 266 released", "state": "done", "ts": now0 - 3 * H}}])      # a finished step keeps its tag: a stale "PR 266 released" ties nothing
fixture(255, project="projects/alpha", steps=[tagged("PR 266 released")])      # the same tag on an open step ties
for n_ in (261, 262, 263, 265, 266): ML.append(line(n_, at=-60))
saved = merge_pass(now0 + 21 * MIN)
check("the item's own words include a step's status tag (a250 names PR 261 only there, a255 PR 266) and a line of its next (a251 names PR 262 there): both tie, with the History line of the words", sorted(saved) == ["a250", "a251", "a255"]
      and mt(250).get("merged_seen") == ["acme/widgets#261"] and mt(251).get("merged_seen") == ["acme/widgets#262"] and mt(255).get("merged_seen") == ["acme/widgets#266"] and all(rd(i)["updated"] == now0 + 21 * MIN for i in (250, 251, 255))
      and any("own words name it" in x["text"] for x in log_of(250)) and any("own words name it" in x["text"] for x in log_of(251)), (saved, [mt(i).get("merged_seen") for i in (250, 251)], log_of(250)))
check("…a bare number in a tag of an item that does not speak of that repository (a252, project beta, PR 263) ties nothing, nor does a merge no word of an item names (#265), nor a number the tag did not name (a253 names 264, which did not merge), nor a tag on a done step (a254: the tag of a finished step is stale; the same words on an open step, a255, tie)",
      all("merged_seen" not in mt(i) and rd(i)["updated"] == now0 - 30 * MIN for i in (252, 253, 254)), [mt(i).get("merged_seen") for i in (252, 253, 254)])
close(250, 251, 252, 253, 254, 255)

# merge_tie: a bare number ties only an item of a project that holds an anchor in the repository, or with a pull request of it anchored; a URL ties anywhere
pg_ = MT.repo_pages({"projects/alpha": [{"url": f"{W_}/pull/1"}, {"url": "https://example.org/x"}], "projects/beta": [{"url": "https://github.com/other/repo/pull/2"}, "junk"]}, lambda u: "acme/widgets" if "acme/widgets" in u else "other/repo" if "other/repo" in u else "")
check("merge_tie.repo_pages: the pages that hold an anchor in each repository (any scope), others and malformed entries left out", pg_ == {"acme/widgets": {"projects/alpha"}, "other/repo": {"projects/beta"}}, pg_)
tx_ = {"i1": "see #7", "i2": "see #7", "i3": "see #7", "i4": f"see {W_}/pull/7"}
tied_ = MT.tied("acme/widgets#7", [], {"i3": {"acme/widgets#99"}}, tx_, {"i1": "projects/alpha", "i2": "projects/beta", "i3": "projects/beta", "i4": "projects/beta"}, pg_)
check("merge_tie.tied: the item of the repository's project (i1) and the one with a pull request of it anchored (i3) tie by a bare number, the item of another project (i2) does not, a URL ties it anywhere (i4)",
      tied_ == {"i1": "words", "i3": "words", "i4": "words"}, tied_)

# the hub: Hub.emit writes the line for a merge, before any lane, and for nothing else
hub_ = HUB.Hub(); hub_.deliver = lambda anchor, session, text: None; hub_.write_status = lambda: None; hub_.persist = lambda: "saved"
hub_.bindings = {"github:acme/widgets#60": {"home-peer"}, "github:acme/widgets@notifications": {"home-peer"}}
off_ = ML.read(0)[1]
def hub_event(anchor, etype, url, refs=None, text="merged it"):
    summary = {"title": "widgets#60", "who": "someone", "text": text, "url": url, "ts": "2026-11-12T00:00:00Z", "etype": etype}
    if refs is not None: summary["meta"] = {"refs": refs}
    hub_.event(anchor, summary, kind="github-state")
hub_event("github:acme/widgets#60", "pr_closed", f"{W_}/pull/60")
hub_event("github:acme/widgets#60", "ci_passed", f"{W_}/pull/60")
check("the hub: a closed pull request and a CI result write no line", ML.read(off_)[0] == [], ML.read(off_)[0])
hub_event("github:acme/widgets#60", "pr_merged", f"{W_}/pull/60", [shown(201)])
hub_event("github:acme/widgets@notifications", "comment+pr_merged", f"{W_}/pull/61#issuecomment-9", [], "merged on #61")
rows_, _o = ML.read(off_)
check("the hub: a merge writes one line (the anchored pull request, with the board ids its body names; a thread of a repository's notifications, by its link), whatever lane its notice takes",
      [(r["repo"], r["n"], r["refs"]) for r in rows_] == [("acme/widgets", 60, [shown(201)]), ("acme/widgets", 61, [])], rows_)
with open(ML.path(), "ab") as f_: f_.write(b'{"ts": 1, "repo": "acme/widgets", "n": 62, "refs": []}')      # a line the hub is still writing: no newline yet
part_rows, part_off = ML.read(_o)
with open(ML.path(), "ab") as f_: f_.write(b"\n")
whole_rows, whole_off = ML.read(_o)
check("merge_log.read: a line the hub is still writing (no newline yet) is not read, and is read whole next time; the offset moves past whole lines only",
      part_rows == [] and part_off == _o and [r["n"] for r in whole_rows] == [62] and whole_off == ML.path().stat().st_size, (part_rows, part_off, whole_rows, whole_off))
check("merge_log.read: an offset past the end (a replaced, shorter file) reads from the start; no file reads as nothing", ML.read(10 ** 9)[0][0]["n"] == 52 and (ML.path().rename(ML.path().with_suffix(".gone")), ML.read(5))[1] == ([], 5), None)

# a line that cannot be parsed costs only itself: deep nesting (RecursionError), an oversized number and a bad byte (ValueError) are skipped, the lines around them are read
ML.path().unlink(missing_ok=True)
deep_line = b"[" * 200000
big_num = b'{"repo": "acme/widgets", "n": ' + b"9" * 6000 + b"}"
ML.append({"ts": 1, "repo": "acme/widgets", "n": 71, "refs": []})
with open(ML.path(), "ab") as f_: f_.write(deep_line + b"\n" + big_num + b"\n" + b'\xff\xfe{"repo": "acme/widgets", "n": 99}\n')
ML.append({"ts": 2, "repo": "acme/widgets", "n": 72, "refs": []})
bad_rows, bad_off = ML.read(0)
check("merge_log.read: a line nested too deep to parse, an oversized number and a bad byte are each skipped, and the lines around them are still read",
      [r["n"] for r in bad_rows] == [71, 72] and bad_off == ML.path().stat().st_size, (bad_rows, bad_off))

# append starts on a line of its own when the file does not end with a newline, so two rows never glue together
ML.path().unlink(missing_ok=True)
ML.path().write_bytes(b'{"ts": 1, "repo": "acme/widgets", "n": 81, "refs": []}')      # no newline at the end (a torn write, a hand edit)
ML.append({"ts": 2, "repo": "acme/widgets", "n": 82, "refs": []})
glued_rows, _ = ML.read(0)
check("merge_log.append: a file that does not end with a newline gets one before the new row, so both rows read apart", [r["n"] for r in glued_rows] == [81, 82], glued_rows)
ML.append({"ts": 3, "repo": "acme/widgets", "n": 83, "refs": []})
raw_ = ML.path().read_bytes()
check("merge_log.append: a file that already ends with a newline gets no blank line; a first row in a new file starts with none",
      b"\n\n" not in raw_ and raw_.count(b"\n") == 3 and raw_.endswith(b"\n") and (ML.path().unlink(), ML.append({"ts": 4, "repo": "acme/widgets", "n": 84, "refs": []}), ML.path().read_bytes().startswith(b"{"))[2], raw_)

# ---- a line nested deeper than str() can follow: json still parses it, and `normal` used to turn its refs into text (RecursionError), then the handler turned the whole line into text (RecursionError again), so the pass
# died before it saved its offset and every pass after it read the same line. Nothing below assumes a depth: the depth is found at run time, the first one where str() on this interpreter fails (str() follows the C
# recursion limit of the interpreter, which is not always sys.getrecursionlimit()), starting from three times the Python limit.
def nest(d):
    x = []
    for _ in range(d): x = [x]
    return x
def str_fails(x):
    try: str(x)
    except RecursionError: return True
    return False
depth = sys.getrecursionlimit() * 3
while not str_fails(nest(depth)):
    depth = int(depth * 1.1) + 1
    assert depth < 3_000_000, depth
deep = nest(depth)
def attempt(fn):
    try: return fn()
    except Exception as e_: return f"raised {e_.__class__.__name__}"

# (1) normal: a ref is a string, anything else is no ref and is never turned into text
got = attempt(lambda: ML.normal({"ts": 1, "repo": "acme/widgets", "n": 5, "refs": [deep, "g12", [["g99"]], {"g98": deep}, "g13"]})["refs"])
check("merge_log.normal: a ref that is a list or an object, however deep, is skipped as no ref (never turned into text); the line keeps its string refs", got == ["g12", "g13"], got)
got = attempt(lambda: ML.normal({"ts": 1, "repo": "acme/widgets", "n": 5, "refs": [12, True, 1.5, None, "g12"]})["refs"])
check("merge_log.normal: a number, a boolean and none are no refs (12 and True would match a ref's shape as text)", got == ["g12"], got)

# (2) the handler: the exception's class, the first of its message and a bounded look at the line, never str(row)
import reprlib as _rl
from stackshot.anchors import event_log as EL
class _Hostile:
    def __repr__(self): raise RuntimeError("no repr")
class _NoClass:      # reprlib's own fallback reads x.__class__, so this one makes reprlib itself raise; only a class name read with type() survives it
    __class__ = property(lambda self: (_ for _ in ()).throw(RuntimeError("no class")))
    def __repr__(self): raise RuntimeError("no repr")
dict_deep = {}
for _ in range(depth): dict_deep = {"k": dict_deep}
wide = {k_: "v" * 200 for k_ in ("aaaa", "bbbb", "cccc", "dddd")}      # reprlib renders it at more than 80 characters, so the cap decides what is kept
t0_ = time.perf_counter()
got = attempt(lambda: (ML.shown(deep), ML.shown({"repo": deep}), ML.shown("x" * 5000), ML.shown({"a": "y" * 5000}), ML.shown(_Hostile()), ML.shown(wide), ML.shown(dict_deep), ML.shown({"a": "y" * 10**7}), ML.shown(_NoClass())))
took = time.perf_counter() - t0_
check("merge_log.shown: at most 80 characters for a deep structure, a long string and a long value; an object whose repr raises shows as its class (reprlib's own fallback)",
      isinstance(got, tuple) and all(len(x_) <= 80 for x_ in got) and got[4].startswith("<_Hostile"), got)
check("merge_log.shown: the cap is what cuts a row reprlib renders at more than 80 characters (the first 80 of it, no more, no less), and a second cap is honored",
      isinstance(got, tuple) and len(_rl.repr(wide)) > 80 and got[5] == _rl.repr(wide)[:80] and got[5].startswith("{'aaaa': 'vvv") and ML.shown(wide, 30) == _rl.repr(wide)[:30] and ML.shown(wide, 160) == _rl.repr(wide)[:160], got[5:6])
check("merge_log.shown: a dict nested past reprlib's depth shows its structure (the nesting, then '...'), not just its class; a 10-million-character value is cut at once",
      isinstance(got, tuple) and got[6].startswith("{'k': {'k': {'k':") and "..." in got[6] and got[6] != "<dict>" and got[7] == _rl.repr({"a": "y" * 10**7})[:80] and took < 1.0, (got[6:8], took))
check("merge_log.shown: when reprlib itself raises (an object whose repr and __class__ both raise: reprlib's own fallback reads __class__) the class name stands in, read with type(): it never raises",
      isinstance(got, tuple) and got[8] == "<_NoClass>" and got[0].startswith("[[[[") and "..." in got[0] and got[0] != "<list>", got[:1] + got[8:])
check("event_log.shown is merge_log.shown with a cap of 160: the same content, longer, and the same fallback",
      EL.shown(wide) == _rl.repr(wide)[:160] and len(EL.shown(wide)) > 80 and EL.shown(_NoClass()) == "<_NoClass>" and EL.shown(dict_deep) == ML.shown(dict_deep, 160) and EL.shown(deep) == ML.shown(deep, 160), None)

# (2b) normal: the wrong shapes it raises on, each by its class, and the bounds on repo and n
def raised(row):
    try: ML.normal(row)
    except Exception as e_: return e_.__class__.__name__
    return "none"
ok_row = {"ts": 1, "repo": "acme/widgets", "n": 5, "refs": []}
shapes = {"repo list": {**ok_row, "repo": deep}, "repo dict": {**ok_row, "repo": dict_deep}, "repo number": {**ok_row, "repo": 12}, "n 1e999": {**ok_row, "n": 1e999}, "ts 400 digits": {**ok_row, "ts": 10**400},
          "n text": {**ok_row, "n": "abc"}, "n list": {**ok_row, "n": [1]}, "repo long": {**ok_row, "repo": "a" * 70 + "/" + "b" * 71}, "n big": {**ok_row, "n": 10**12}, "n 0": {**ok_row, "n": 0}, "repo bad": {**ok_row, "repo": "nope"}}
got = {k_: raised(r_) for k_, r_ in shapes.items()}
check("merge_log.normal: each wrong shape raises by the class the docstring names (a repo that is not text is a TypeError before it is turned into text, however deep; n=1e999 and a time of 400 digits are OverflowError)",
      got == {"repo list": "TypeError", "repo dict": "TypeError", "repo number": "TypeError", "n 1e999": "OverflowError", "ts 400 digits": "OverflowError", "n text": "ValueError", "n list": "TypeError", "repo long": "ValueError", "n big": "ValueError", "n 0": "ValueError", "repo bad": "ValueError"}, got)
check("merge_log.normal: owner/repo at GitHub's longest (39 + 1 + 100) and a number at the bound are kept; one character more is not",
      raised({**ok_row, "repo": "a" * 39 + "/" + "b" * 100, "n": ML.MAX_NUMBER}) == "none" and raised({**ok_row, "repo": "a" * 40 + "/" + "b" * 100}) == "ValueError" and raised({**ok_row, "n": ML.MAX_NUMBER + 1}) == "ValueError", None)
try: ML.normal({**ok_row, "repo": "z" * 5000})
except ValueError as e_: msg_ = str(e_)
else: msg_ = ""
LONG_OK, LONG_BAD = "a" * 39 + "/" + "b" * 100, "a" * 40 + "/" + "b" * 100      # GitHub's longest owner/repo (140 characters), and one character more
caps_ok = [ML.line_for(f"github:{LONG_OK}#{ML.MAX_NUMBER}", "", "pr_merged", [], 5.0), ML.line_for("", f"https://github.com/{LONG_OK}/pull/{ML.MAX_NUMBER}", "pr_merged", [], 5.0), EL.lines_for(f"github:{LONG_OK}#{ML.MAX_NUMBER}", "", "pr_merged", "", [], 5.0)]
caps_bad = [ML.line_for(f"github:{LONG_BAD}#5", "", "pr_merged", [], 5.0), ML.line_for("", f"https://github.com/{LONG_BAD}/pull/5", "pr_merged", [], 5.0), ML.line_for(f"github:acme/widgets#{ML.MAX_NUMBER + 1}", "", "pr_merged", [], 5.0),
            ML.line_for(f"github:acme/widgets#{'9' * 400}", "", "pr_merged", [], 5.0), ML.line_for("", f"https://github.com/acme/widgets/pull/{ML.MAX_NUMBER + 1}", "pr_merged", [], 5.0), ML.line_for("", f"https://github.com/acme/widgets/pull/{'7' * 30}", "pr_merged", [], 5.0),
            EL.lines_for(f"github:{LONG_BAD}#5", "", "pr_merged", "", [], 5.0), EL.lines_for(f"github:acme/widgets#{ML.MAX_NUMBER + 1}", "", "pr_merged", "", [], 5.0)]
check("merge_log writers: a repository at the cap (140 characters) and a number at the cap (a billion) are written, and `normal` accepts each line", caps_ok[0] and caps_ok[1] and caps_ok[0]["n"] == ML.MAX_NUMBER and len(caps_ok[0]["repo"]) == ML.MAX_REPO and len(caps_ok[2]) == 1
      and ML.normal(caps_ok[0])["n"] == ML.MAX_NUMBER and ML.normal(caps_ok[1])["repo"] == LONG_OK, caps_ok)
check("merge_log writers: an over-cap repository or number (an anchor or a link, a run of digits however long) is no line at all, never one the reader would refuse; the same for event_log.lines_for",
      caps_bad[:6] == [None] * 6 and caps_bad[6:] == [[], []] and ML.pull_of(f"github:{LONG_BAD}#5") == ("", 0) and ML.pull_of("", f"https://github.com/acme/widgets/pull/{ML.MAX_NUMBER + 1}") == ("", 0), caps_bad)
check("merge_log: the regexes bound their digit runs and name parts, so no pattern can match a run longer than the caps (a 30-digit number is not read as its first ten)", "{1,10}" in ML._ANCHOR.pattern and "{1,10}" in ML._GITHUB_PATH.pattern and "{1,140}" in ML._ANCHOR.pattern
      and ML.pull_of("", f"https://github.com/acme/widgets/pull/{'1' * 30}") == ("", 0), (ML._ANCHOR.pattern, ML._GITHUB_PATH.pattern))
_eleven = "https://github.com/a/b/pull/10000000001"      # eleven digits whose first ten are at the cap: only the lookahead keeps it from reading as number 1000000000
_no_look = re.compile(ML._GITHUB_PATH.pattern.replace(r"(?!\d)", ""), re.I).search(_eleven)
check("merge_log: the link pattern's lookahead is what refuses an eleven-digit number whose first ten digits are within the cap (without it the link reads as a/b#1000000000)",
      r"(?!\d)" in ML._GITHUB_PATH.pattern and _no_look is not None and (_no_look.group(1), int(_no_look.group(2))) == ("a/b", 1000000000)
      and ML._GITHUB_PATH.search(_eleven) is None and ML.pull_of("", _eleven) == ("", 0), (_no_look and _no_look.groups(), ML.pull_of("", _eleven)))
check("merge_log.normal: the message of a refused line holds no more than the start of a long repo (it rides into a log line)", msg_.startswith("not a merge line: repo='zzz") and "z" * 41 not in msg_ and len(msg_) < 120, msg_)
errs = _io.StringIO()
with _cl.redirect_stderr(errs): kept = attempt(lambda: mprog_svc._merge_rows([{"ts": now0, "repo": deep, "n": 5, "refs": []}, {"ts": now0, "repo": "acme/widgets", "n": 6, "refs": []}], now0))
logged = [l_ for l_ in errs.getvalue().splitlines() if "line skipped" in l_]
check("_merge_rows: a line whose repo nests too deep for str() is logged as its exception class and a bounded look (one short line), and the line after it is kept",
      isinstance(kept, list) and [r_["n"] for r_ in kept] == [6] and len(logged) == 1 and "TypeError" in logged[0] and len(logged[0]) < 300, (kept, logged and logged[0][:300]))
errs = _io.StringIO()
with _cl.redirect_stderr(errs): kept = attempt(lambda: mprog_svc._merge_rows([{"ts": now0, "repo": "not-a-repo", "n": 7, "refs": []}, {"ts": now0, "repo": "acme/widgets", "n": "x" * 50, "refs": []}, {"ts": now0, "repo": "acme/widgets", "n": 8, "refs": []}], now0))
logged = [l_ for l_ in errs.getvalue().splitlines() if "line skipped" in l_]
check("_merge_rows: the log line carries the start of the exception's message beside its class (the repo that was refused; the text int() choked on), cut at 80, and the line after is kept",
      isinstance(kept, list) and [r_["n"] for r_ in kept] == [8] and len(logged) == 2 and "ValueError: not a merge line: repo='not-a-repo'" in logged[0] and "ValueError: invalid literal for int()" in logged[1]
      and all(len(l_) < 330 for l_ in logged), logged)

# (4) the whole pass: first with the lines handed in from memory (no parse, so no interpreter's parse depth matters), then through the file (the lines are parsed, or dropped by read, whichever this interpreter does)
for i in (240, 241, 242, 243): fixture(i, project="projects/alpha")
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/{90 + k}", "items": [f"a{240 + k}"]} for k in range(4)]}))
ML.path().unlink(missing_ok=True); mprog_svc._merge_progress_save(0)
SENT = 4321
_real_read = ML.read
ML.read = lambda offset=0, file=None: ([{"ts": now0, "repo": "acme/widgets", "n": 95, "refs": [deep, 12, "g12"]}, {"ts": now0, "repo": deep, "n": 96, "refs": []}, line(93, at=-30)], SENT)
errs = _io.StringIO()
try:
    with _cl.redirect_stderr(errs): saved = attempt(lambda: merge_pass(now0))
finally:
    ML.read = _real_read
check("the pass, lines nested too deep for str() handed in: it does not stop, the line after them moves its item's clock, and the offset is saved",
      saved == ["a243"] and mprog_svc._merge_progress_offset() == SENT and mt(243).get("merged_seen") == ["acme/widgets#93"] and rd(243)["updated"] == now0 and errs.getvalue().count("line skipped") == 1,
      (saved, mprog_svc._merge_progress_offset(), errs.getvalue()[-300:]))
mprog_svc._merge_progress_save(0)

# Where the lines of the next two checks go wrong is the interpreter's: json parses to a depth of its own and str() fails at another. On Python 3.14 json parses what str() cannot follow (json fails at 57,947
# levels, str at 47,413), so a deep line reaches `normal` and the handler through the file; on 3.12 and 3.13 both fail near 9,998, so `read` drops the line as unparseable and the handler never sees it. The checks
# through the file prove less there, and say so in their label; the checks above with the lines handed in from memory hold on every version.
try: json.loads("[" * depth + "]" * depth); through_file = "json parses these lines here: they reach normal and the handler"
except RecursionError: through_file = "json refuses these lines on this Python, so read drops them and this proves less than on 3.14"
ML.path().unlink(missing_ok=True)
ML.append(line(90, at=-120))
with open(ML.path(), "ab") as f_:
    f_.write(f'{{"ts": {int(now0)}, "repo": "acme/widgets", "n": 95, "refs": '.encode() + b"[" * depth + b"]" * depth + b"}\n")                  # nested refs
    f_.write(f'{{"ts": {int(now0)}, "repo": '.encode() + b"[" * depth + b"]" * depth + ', "n": 96, "refs": []}\n'.encode())                     # a nested repo
ML.append(line(91, at=-60)); ML.append(line(92, at=-30))
errs = _io.StringIO()
with _cl.redirect_stderr(errs): saved = attempt(lambda: merge_pass(now0))
check(f"the pass, the lines nested too deep for str() in the file: the offset is saved at its end, and the lines before and after them move their items' clocks [{through_file}]",
      isinstance(saved, list) and sorted(saved) == ["a240", "a241", "a242"] and mprog_svc._merge_progress_offset() == ML.size() and all(rd(i)["updated"] == now0 for i in (240, 241, 242)), (saved, mprog_svc._merge_progress_offset(), ML.size(), errs.getvalue()[-300:]))
errs = _io.StringIO()
with _cl.redirect_stderr(errs): again = attempt(lambda: merge_pass(now0 + 60))
check(f"…and the pass after it does not read the deep lines again: nothing is saved, nothing is logged, the offset stays at the end [{through_file}]",
      again == [] and "line skipped" not in errs.getvalue() and mprog_svc._merge_progress_offset() == ML.size(), (again, errs.getvalue()[-300:]))

# (3) the documented behaviour of read: a line that is not JSON, or too deep to parse, is dropped with no log line (the doc says so)
ML.path().unlink(missing_ok=True)
with open(ML.path(), "ab") as f_: f_.write(b"[" * 200000 + b"\n" + b'{"ts": 1, "repo": "acme/wid\n')
ML.append({"ts": 2, "repo": "acme/widgets", "n": 97, "refs": []})
with open(ML.path(), "ab") as f_: f_.write(b'{}\n[1]\n{"repo": "acme/widgets", "n": 0}\n{"repo": "", "n": 5}\n{"repo": "acme/widgets"}\n')      # parsed, but not an object with a repository and a number
ML.append({"ts": 3, "repo": "acme/widgets", "n": 98, "refs": []})
quiet = _io.StringIO()
with _cl.redirect_stderr(quiet): quiet_rows, _ = ML.read(0)
doc_ = pathlib.Path(STACK, "docs/stall-and-ladder.md").read_text(encoding="utf-8")
check("docs: the merge pass's section says that merge_log.read drops a line that is not JSON or is too deep to parse without a log line, and the code does exactly that (it prints nothing)",
      "`merge_log.read` without a log line" in doc_ and "(logged, the offset moves past it)" not in doc_ and [r_["n"] for r_ in quiet_rows] == [97, 98] and quiet.getvalue() == "", (quiet_rows, quiet.getvalue()[:200]))
check("docs: …and a line that parses but is no object with a repository and a number ({}, [1], a number of 0, an empty repository) is dropped by read the same way (not logged, as the section said), while a line with both and a wrong shape is logged by the pass",
      "so is a line that parses but is not an object with a repository and a number" in doc_ and "is logged by the pass as its exception class, the first 80 characters of its message" in doc_ and "a line that parses but is of the wrong shape is logged by the pass" not in doc_
      and all(r_.get("repo") and r_.get("n") for r_ in quiet_rows), doc_[doc_.find("so is a line that parses") - 100:doc_.find("so is a line that parses") + 200])
close(240, 241, 242, 243)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
