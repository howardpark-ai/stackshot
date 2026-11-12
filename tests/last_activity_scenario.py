"""Scenario test for the item's last-activity record, `metadata.last_activity = {"at", "kind", "what"}` (model/last_activity.py, anchors/event_log.py, `server._stamp_last_activity`,
`server._event_activity_tick`): the one place that says when something visible last happened to an item and what it was. It records; the On agent rows and the item page show it (tests/on_agent_row_scenario.py), and nothing else reads it, so every other clock must be
exactly as it was. Fixture items, a fake clock (the passes are given their `now`, the saves are stamped from a fake `time`), no live store, no network, no model call.

  1  pure: the words for each signal (a step done or dropped, a state change, a merge, created), and what is no activity (a status line, a reply, a note, a confirm, a new or reworded step, a description edit,
     the server's own bookkeeping); newest wins; a torn candidate is skipped; a time in the future reads as now; the record never goes back
  2  a real `_save`: a session's step mark and state change stamp it at the save's time; a status line, a reply and the ladder's own History line (a bookkeeping save) do not; the merge pass's save says "PR n merged"
  3  the event log: kinds, a burst is one line per kind, a bot's comment is left out, a line is never written for what names no pull request; `Hub.emit` writes it for a CI result, a comment, a review and a merge
     and for nothing else; the merge log is untouched by a line of another kind
  4  the pass: each kind of event of a tied pull request stamps the right words at the event's time; the same tie rules as a merge (anchored, the body, the item's own words; a project-wide anchor, a waiting item,
     a held one and a closed one are left alone); the other clocks (activity, progress, updated, History, merged_seen) are as they were
  5  the pass's care: newest wins; a torn, malformed or oversized line is skipped and bounded in the log; a restart resumes from the offset; a replaced file is read from its start; an old event is not read; one
     item that cannot be saved stops no other; nothing raises out of the pass; a standby and a held board run nothing
  6  a body names an item for anyone: only a merge ties through it (a comment, a review and a CI result tie by an anchor scoped to the item or the item's own words); a line the hub is still writing waits, a file
     with no newline at its end gets one before the next line; a torn stored record is repaired by the next signal; the words of a signal are one clean line
  7  the hub's events are as they were: a comment's direct notice (the pull request's body naming an item) is byte for byte the notice it had, a merge's too; a comment by an account typed Bot is marked
  8  one save for many lines of an item (the newest wins); a stored time ahead of the clock is ignored; an item closed, held or begun to wait between the tie and the save is not stamped; a bot by its type
  9  who counts: only a comment or review whose author_association is OWNER, MEMBER or COLLABORATOR, and a CI result from a branch of the repository itself, is activity (each association value; a
     stranger's comment on an anchored pull request and on an issue the item's words name; a fork's, a deleted fork's and a nameless CI result); a merge is not filtered
  10 the line's time is the event's own when it can be read and is within the window (a backlog is not now); absent or unreadable falls back to the hub's; outside the window writes no line
  11 History: a confirm and a last-activity stamp saved in one window still show the `confirm` line (both renderers)

    tests/run-suite last_activity       -> exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging, io, math
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="lastact-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-peer", "home-peer2", "home-stew")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = float(int(time.time()))      # whole seconds: the event log keeps a time to the millisecond, so the sums below compare exactly
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
ALPHA = {"home-front": "the front", "team-back": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                  "agents": ALPHA, "back_agents": {"team-back": ALPHA["team-back"]}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: builds, merges and releases the code\n---\n\n# alpha\n\n## Current state\n\nx\n\n<!-- timeline -->\n\n## Timeline\n", encoding="utf-8")
(T / "store/next-id").write_text("1"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
MIN = 60.0; H = 3600.0
W_ = "https://github.com/acme/widgets"
def BID(n): return "board" + "#" + str(n)      # an item id as a body names it, built from pieces

def put(i, mover="home-peer", status="open", act=30, **meta):
    """An open doing item on `mover`, last written and last active `act` minutes before now0."""
    base = {"owner": U["home-front"], "project": "projects/alpha", "next": f"{mover}: do the thing", "state": "doing", "needs": [mover], "mover": mover}
    base.update(meta)
    at = now0 - act * MIN
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": at, "state_updated": at, "confirmed": at,
                                                       "activity": at, "progress": at, "written_at": at, "written_by": "home-front", "metadata": base}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def wr(i, d): (T / f"store/a/{i}.json").write_text(json.dumps(d))
def la(i):
    r = mt(i).get("last_activity")
    return {k: v for k, v in r.items() if k != "kind"} if isinstance(r, dict) else r      # the time and the words; the kind is lk
def lk(i): return (mt(i).get("last_activity") or {}).get("kind")
def step(text, status, at=0): return {"text": text, "status": status, "by": "x", "at": at}
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:300]}" if got is not None else ""))
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.web import server
from stackshot.model import last_activity as LA, progress as PG, activity as ACT
from stackshot.anchors import event_log as EL, merge_log as ML
from stackshot.anchors.anchorhub import core as HUB
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._PUSH = [sys.executable, "-c", "pass"]
class _Clock:
    """The server's `time` module for the saves below: the clocks are stamped from the server's own clock, which a scenario with a fake `now` must be able to set."""
    t = None
    def __getattr__(self, n): return getattr(time, n)
    def time(self): return time.time() if self.t is None else self.t
CLK = _Clock(); server.time = CLK
def save_at(ts, i, mutate, writer="home-peer", **kw):
    """A real `server._save` of item `i` at the fake time `ts`, `mutate` changing the loaded item first."""
    d_ = server._load(f"a{i}"); mutate(d_); CLK.t = ts
    try: server._save(f"a{i}", d_, writer=writer, **kw)
    finally: CLK.t = None
class _Err:
    """stderr of the server's prints, kept for a check."""
    def __enter__(self): self.old, self.buf = sys.stderr, io.StringIO(); sys.stderr = self.buf; return self
    def __exit__(self, *a): sys.stderr = self.old
    @property
    def text(self): return self.buf.getvalue()

# ================================================================ 1. pure: last_activity.py
def W(b, a, real=True): return "; ".join(x["what"] for x in LA.save_signals(b, a, 100.0, real))
def K(b, a, real=True): return [x["kind"] for x in LA.save_signals(b, a, 100.0, real)]
def doc(**kw): return {"status": "open", "metadata": {"mover": "m", "state": "doing", "needs": ["m"], "phase": "alive", "steps": [step("a", "open"), step("b", "done", 5), step("c", "open")], **kw}}
base = doc()
def after(**kw): return doc(**kw)
check("1 save_words: a step marked done is named by its place on the checklist; one marked dropped likewise",
      W(base, after(steps=[step("a", "done", 9), step("b", "done", 5), step("c", "open")])) == "step 1 done" and W(base, after(steps=[step("a", "open"), step("b", "done", 5), step("c", "dropped", 9)])) == "step 3 dropped", None)
check("1 save_words: several steps marked in one save are one phrase, the first three named",
      W(base, after(steps=[step("a", "done", 9), step("b", "done", 5), step("c", "dropped", 9)])) == "step 1 done, step 3 dropped", W(base, after(steps=[step("a", "done", 9), step("b", "done", 5), step("c", "dropped", 9)])))
check("1 save_words: a state change says which: the phase (and the kind of a wait), the state, the mover, the needs",
      W(base, after(phase="waiting", waits_on="time")) == "state: waiting (time)" and W(base, after(state="verifying")) == "state: verifying"
      and W(base, after(mover="n")) == "mover changed" and W(base, after(needs=["m", "n"])) == "needs changed"
      and W(base, {**base, "status": "completed"}) == "state: completed", [W(base, after(phase="waiting", waits_on="time")), W(base, after(mover="n"))])
check("1 save_words: a merge recorded names the pull request (merged_seen, or the merged entry of released_told); a created item says created",
      W(base, after(merged_seen=["acme/widgets#7"])) == "PR 7 merged" and W(base, after(released_told=["merged acme/widgets#8"])) == "PR 8 merged" and W(None, base) == "created", None)
check("1 save_words: no activity in a status line, a reply, a note, a confirm, a new or reworded step, a description edit",
      all(W(base, a) == "" for a in (after(work=[{"id": "x", "text": "building", "state": "in progress"}]), after(next="m: do it (no change)"), after(note="still on it"), {**base, "confirmed": 5},
                                                  after(steps=[step("a", "open"), step("b", "done", 5), step("c", "open"), step("d", "open")]), after(steps=[step("a2", "open"), step("b", "done", 5), step("c", "open")]),
                                                  {**base, "description": "- another"}, after(steps=[step("a", "open"), step("b", "done", 7), step("c", "open")]))), None)
check("1 save_words: a save that is no one's write (real=False) records no step mark, mover or merge, only a status or phase change, as progress counts it",
      W(base, after(steps=[step("a", "done", 9), step("b", "done", 5), step("c", "open")]), False) == "" and W(base, after(mover="n"), False) == "" and W(base, after(merged_seen=["a/b#1"]), False) == ""
      and W(base, after(phase="waiting", waits_on="time"), False) == "state: waiting (time)", None)
cands = [{"at": 100, "kind": "step_done", "what": "step 1 done"}, {"at": 300, "kind": "ci_result", "what": "CI failed on PR 5"}, {"at": 200, "kind": "review", "what": "review on PR 5"}]
check("1 record: the newest candidate wins whatever the order they come in; none gives None", LA.record({"metadata": {}}, cands) == {"at": 300.0, "kind": "ci_result", "what": "CI failed on PR 5"} and LA.record({"metadata": {}}, reversed(cands)) == {"at": 300.0, "kind": "ci_result", "what": "CI failed on PR 5"}
      and LA.record({"metadata": {}}, []) is None and LA.record(None, None) is None, None)
held_ = {"metadata": {"last_activity": {"at": 250, "kind": "state_change", "what": "state: waiting"}}}
check("1 record: a candidate replaces the stored record only when strictly later: an older one and one at the same time leave it, a later one replaces it",
      LA.record(held_, [{"at": 200, "kind": "comment", "what": "x"}])["what"] == "state: waiting" and LA.record(held_, [{"at": 250, "kind": "comment", "what": "x"}])["what"] == "state: waiting" and LA.record(held_, [{"at": 251, "kind": "comment", "what": "x"}]) == {"at": 251.0, "kind": "comment", "what": "x"}, None)
check("1 record: of candidates at the same time the last given wins", LA.record({"metadata": {}}, [{"at": 5, "kind": "comment", "what": "first"}, {"at": 5, "kind": "review", "what": "second"}])["what"] == "second", None)
torn = [None, "x", 5, {}, {"at": None, "kind": "comment", "what": "x"}, {"at": "soon", "kind": "comment", "what": "x"}, {"at": float("nan"), "kind": "comment", "what": "x"}, {"at": float("inf"), "kind": "comment", "what": "x"}, {"at": -3, "kind": "comment", "what": "x"}, {"at": 0, "kind": "comment", "what": "x"}, {"at": 9, "kind": "comment", "what": ""}, {"at": 9, "kind": "comment", "what": "   "}, {"at": 9, "kind": "comment"}, {"at": 9, "what": "no kind"}, {"at": 9, "kind": "push", "what": "an unknown kind"}]
check("1 record: a torn candidate (not a dict, no time, a time that is no number or not finite or not positive, no words) is skipped, and does not stop the good one after it",
      LA.record({"metadata": {}}, torn) is None and LA.record({"metadata": {}}, [*torn, {"at": 7, "kind": "review", "what": "review on PR 1"}]) == {"at": 7.0, "kind": "review", "what": "review on PR 1"} and LA.read({"metadata": {"last_activity": "garbage"}}) is None and LA.at({"metadata": {"last_activity": {"at": "x", "kind": "comment", "what": "y"}}}) == 0 and LA.read({"metadata": {"last_activity": {"at": 5, "what": "no kind"}}}) is None, None)
check("1 record: a time after now reads as now; the words are one line of at most 80 characters", LA.record({"metadata": {}}, [{"at": 999, "kind": "comment", "what": "x"}], now=500)["at"] == 500.0 and LA.clean({"at": 1, "kind": "audit", "what": "a\n  b\n" + "w" * 200})["what"].startswith("a b w") and len(LA.clean({"at": 1, "kind": "audit", "what": "w" * 200})["what"]) == 80, None)
item_ = {"status": "open", "metadata": {}}
S_ = lambda at, what="x", kind="comment": {"at": at, "kind": kind, "what": what}
check("1 apply: stores the record with its kind; the same again, an older one and a torn one change nothing (no write); a later one replaces it",
      LA.apply(item_, [S_(10)]) and item_["metadata"]["last_activity"] == {"at": 10.0, "kind": "comment", "what": "x"} and not LA.apply(item_, [S_(10)]) and not LA.apply(item_, [S_(5, "y")]) and not LA.apply(item_, [None, {"at": "z"}])
      and LA.apply(item_, [S_(11, "y", "review")]) and item_["metadata"]["last_activity"] == {"at": 11.0, "kind": "review", "what": "y"} and not LA.apply({"metadata": "not a dict"}, [S_(1, "z")]), item_)
check("1 kinds: the five of the progress signals and the pull request's events are known from day one, with update and audit; STAMPED is what is stamped today",
      LA.KINDS == frozenset({"step_done", "step_dropped", "state_change", "pr_merged", "ci_result", "review", "comment", "update", "audit"}) and set(LA.STAMPED) == LA.KINDS - {"update", "audit"}, sorted(LA.KINDS))
check("1 save_signals: each save signal has its kind: step_done, step_dropped, state_change, pr_merged, and created is a state_change",
      K(base, after(steps=[step("a", "done", 9), step("b", "done", 5), step("c", "open")])) == ["step_done"] and K(base, after(steps=[step("a", "open"), step("b", "done", 5), step("c", "dropped", 9)])) == ["step_dropped"]
      and K(base, after(phase="waiting", waits_on="time")) == ["state_change"] and K(base, after(merged_seen=["a/b#1"])) == ["pr_merged"] and K(None, base) == ["state_change"]
      and K(base, after(mover="n", merged_seen=["a/b#1"])) == ["state_change", "pr_merged"] and K(base, after(work=[{"id": "x"}])) == [], K(base, after(mover="n", merged_seen=["a/b#1"])))
check("1 pr_candidate: the events of a tied pull request are the signals ci_result (failed or passing), review, comment and pr_merged",
      [(LA.pr_candidate(k, 9, 5, 50) or {}).get("kind") for k in ("ci_failed", "ci_passed", "review", "comment", "merged")] == ["ci_result", "ci_result", "review", "comment", "pr_merged"], None)
# update and audit: defined and tested, stamped by nothing yet
check("1 update_signal: a status write whose text differs from the previous one is an update, the words the text itself; the same text again (case and spacing aside), a blank one and a torn time are not",
      LA.update_signal("building the fix", "tests pass, opening the pull request", 40) == {"at": 40.0, "kind": "update", "what": "tests pass, opening the pull request"}
      and LA.update_signal("building the fix", "  Building   the FIX ", 40) is None
      and LA.update_signal("x", "", 40) is None and LA.update_signal("x", None, 40) is None and LA.update_signal("x", "y", "soon") is None and LA.update_signal(None, "first line", 40)["what"] == "first line", LA.update_signal("a", "b", 40))
check("1 audit_signal: a line the audit wrote saying what it verified is an audit signal, the words that text; one that verified nothing is none",
      LA.audit_signal("pane in a turn; commit on PR 4 an hour ago", 40) == {"at": 40.0, "kind": "audit", "what": "pane in a turn; commit on PR 4 an hour ago"} and LA.audit_signal("", 40) is None and LA.audit_signal("   ", 40) is None and LA.audit_signal("x", None) is None, None)
it_ = {"status": "open", "metadata": {}}
LA.apply(it_, [LA.update_signal("", "wired the thing", 10)]); first_ = dict(it_["metadata"]["last_activity"])
LA.apply(it_, [LA.audit_signal("subagent running", 20)])
check("1 update and audit signals take part in newest-wins like the rest: an audit line later than an update replaces it, an older update after it does not", first_["kind"] == "update" and it_["metadata"]["last_activity"] == {"at": 20.0, "kind": "audit", "what": "subagent running"}
      and not LA.apply(it_, [LA.update_signal("", "older", 15)]), it_)
check("1 pr_what: the words for each kind of event (a comment is on #n: the hub does not say whether the anchor is a pull request); a kind that is no activity has none", [LA.pr_what(k, 123) for k in ("ci_failed", "ci_passed", "comment", "review", "merged")] == ["CI failed on PR 123", "CI passing on PR 123", "comment on #123", "review on PR 123", "PR 123 merged"]
      and LA.pr_what("pr_closed", 5) == "" and LA.pr_what("comment", 0) == "" and LA.pr_candidate("pr_closed", 5, 100, 200) is None and LA.pr_candidate("comment", 5, 100, 200) == {"at": 100.0, "kind": "comment", "what": "comment on #5"}, None)
closed_ = {"status": "completed", "metadata": {"steps": [step("a", "done", 9)]}}
check("1 stamp: only an open item has a record", not LA.stamp(closed_, {"status": "open", "metadata": {"steps": [step("a", "open")]}}, 50.0) and "last_activity" not in closed_["metadata"], closed_)

# ================================================================ 2. a real _save
ASTEP = lambda text, status, at=0: step(text, status, at)
put(300); put(301); put(302); put(303)
save_at(now0 + 5 * MIN, 300, lambda d_: d_["metadata"].update(steps=[ASTEP("home-peer: do the thing", "done", now0 + 5 * MIN), ASTEP("home-peer: more", "open")], next="home-peer: more"))
check("2 a session marks a step done: the record is stamped at the save, in words, with its kind", la(300) == {"at": now0 + 5 * MIN, "what": "step 1 done"} and lk(300) == "step_done", la(300))
save_at(now0 + 9 * MIN, 300, lambda d_: d_["metadata"].update(work=[{"id": "build", "text": "building the fix", "state": "in progress", "agent": "home-peer", "ts": now0 + 9 * MIN}]))
save_at(now0 + 10 * MIN, 300, lambda d_: d_["metadata"].update(next="home-peer: more (no change)"))
save_at(now0 + 11 * MIN, 300, lambda d_: d_.update(confirmed=now0 + 11 * MIN), activity=ACT.CONFIRM)
save_at(now0 + 12 * MIN, 300, lambda d_: None, note="still on it", activity=ACT.MESSAGE)
check("2 a status line, a \"no change\" reply, a confirm and a note do not move it", la(300) == {"at": now0 + 5 * MIN, "what": "step 1 done"}, la(300))
d_ = server._load("a300"); server._stall.note(d_["metadata"], now0 + 13 * MIN, "it has not moved for 4 hours: handed up"); CLK.t = now0 + 13 * MIN
try: server._save("a300", d_, activity=ACT.BOOKKEEPING)
finally: CLK.t = None
check("2 the ladder's own History line (a save of the server's, no writer) does not move it, and the History line is on the item", la(300) == {"at": now0 + 5 * MIN, "what": "step 1 done"} and any("handed up" in x.get("text", "") for x in server._stall.log_of(mt(300))), mt(300).get("stall") or mt(300).keys())
save_at(now0 + 20 * MIN, 300, lambda d_: d_["metadata"].update(mover="home-peer2", needs=["home-peer2"]))
check("2 a session's state change (a new mover) moves it, newest wins", la(300) == {"at": now0 + 20 * MIN, "what": "mover changed"} and lk(300) == "state_change", la(300))
save_at(now0 + 30 * MIN, 300, lambda d_: d_["metadata"].update(released_told=["merged acme/widgets#12"]), writer="", activity=ACT.EVENT)
check("2 a merge recorded by the server's event save says which pull request merged", la(300) == {"at": now0 + 30 * MIN, "what": "PR 12 merged"} and lk(300) == "pr_merged", la(300))
save_at(now0 + 31 * MIN, 301, lambda d_: d_["metadata"].update(wake="2999-01-01T00:00", state="waiting", needs=["decision"]), writer="")
check("2 an item no one has acted on keeps no record (the field is absent until there is something to say)", la(302) is None and la(303) is None, None)
d_ = rd(303); d_["status"] = "completed"; wr(303, d_)
save_at(now0 + 32 * MIN, 303, lambda d_: d_["metadata"].update(steps=[ASTEP("x", "done", now0)]))
check("2 a closed item gets no record", la(303) is None, la(303))
save_at(now0 + 33 * MIN, 302, lambda d_: d_["metadata"].update(steps=[ASTEP("y", "open")]), writer="home-peer", activity=ACT.WRITE)
check("2 the other clocks are as they were: a save that records nothing leaves progress and activity to their own rules (a step added moves neither the record nor progress)", la(302) is None and rd(302)["progress"] == now0 - 30 * MIN, (la(302), rd(302)["progress"]))

# ================================================================ 3. the event log and the hub
ALLK = "comment+review+ci_failed+ci_passed"      # the kinds a source can vouch for: the tests below that are not about the filter vouch for all of them
def lines(anchor, url, etype, who="alice", refs=(), now=10.0, vouched=ALLK, **kw): return EL.lines_for(anchor, url, etype, who, list(refs), now, vouched=vouched, **kw)
A_ = "github:acme/widgets#40"
check("3 kinds_of: a CI result, a comment, a review (a review comment is one), a merge; several joined with + are each once; others (closed, opened, a push, unclassified) are none",
      EL.kinds_of("ci_failed") == ["ci_failed"] and EL.kinds_of("review_comment") == ["review"] and EL.kinds_of("comment+review+review_comment+pr_merged") == ["comment", "review", "merged"]
      and EL.kinds_of("pr_closed") == [] and EL.kinds_of("pr_synchronize") == [] and EL.kinds_of("pr_opened+ci_activity") == [] and EL.kinds_of("") == [] and EL.kinds_of(None) == [], None)
check("3 lines_for: one line per kind, with the pull request, the time and the body's board ids; a burst writes each kind",
      lines(A_, "", "pr_merged", "alice", [BID(9)]) == [{"ts": 10.0, "repo": "acme/widgets", "n": 40, "kind": "merged", "refs": [BID(9)]}]
      and [r["kind"] for r in lines(A_, "", "comment+pr_merged")] == ["comment", "merged"], lines(A_, "", "comment+pr_merged"))
check("3 lines_for: only a merge keeps the board ids the body names; a comment, a review and a CI result in the same burst, or alone, carry none (a body names an item for anyone who opens a pull request)",
      [(r["kind"], r["refs"]) for r in lines(A_, "", "comment+review+ci_failed+pr_merged", "alice", [BID(9)])] == [("comment", []), ("review", []), ("ci_failed", []), ("merged", [BID(9)])], lines(A_, "", "comment+review+ci_failed+pr_merged", "alice", [BID(9)]))
check("3 lines_for: the pull request comes from the anchor, else the link (a notification thread); a repository's thread with no pull request, a release and a bare repository write none",
      lines("github:acme/widgets@notifications", f"{W_}/pull/41#issuecomment-1", "comment")[0]["n"] == 41 and lines("github:acme/widgets@notifications", f"{W_}/actions", "ci_failed") == [] and lines("github:acme/widgets@releases", "", "pr_merged") == [] and lines("slack:C1", "", "comment") == [], None)
check("3 lines_for: a comment or review by a bot is left out (every login a bot's), one with a person among them is kept; CI and a merge are kept whoever did them",
      lines(A_, "", "comment", "ci-helper[bot]") == [] and lines(A_, "", "review", "a[bot], b[bot]") == [] and len(lines(A_, "", "comment", "a[bot], carol")) == 1 and len(lines(A_, "", "ci_failed", "ci-helper[bot]")) == 1
      and len(lines(A_, "", "pr_merged", "merge-bot[bot]")) == 1 and len(lines(A_, "", "comment", "someone")) == 1, None)
def raises(fn):
    try: fn()
    except (ValueError, TypeError, KeyError): return True
    return False
check("3 normal: a good line is read as merge_log reads one, with its kind", EL.normal({"ts": 1, "repo": "A/b", "n": 3, "kind": "merged", "refs": [BID(1), "bad ref"]}) == {"ts": 1.0, "repo": "a/b", "n": 3, "kind": "merged", "refs": [BID(1)]}
      and EL.normal({"ts": 1, "repo": "A/b", "n": 3, "kind": "review", "refs": [BID(1)]})["refs"] == [], None)
check("3 normal: a line of the wrong shape is refused (no kind, a kind that is none, a bad repository, a number that is no number, no number, a time that is not a number)",
      all(raises(lambda r=r: EL.normal(r)) for r in ({"ts": 1, "repo": "a/b", "n": 3}, {"ts": 1, "repo": "a/b", "n": 3, "kind": "pr_closed"}, {"ts": 1, "repo": "nope", "n": 3, "kind": "comment"},
                                                    {"ts": 1, "repo": "a/b", "n": "x", "kind": "comment"}, {"ts": 1, "repo": "a/b", "n": 0, "kind": "comment"}, {"ts": float("nan"), "repo": "a/b", "n": 1, "kind": "comment"})), None)
def ISO_NOW(back=0.0): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - back))      # an event's own time as the source writes it, built at run time (the window is relative to the clock)
hub_ = HUB.Hub(); hub_.deliver = lambda anchor, session, text: None; hub_.write_status = lambda: None; hub_.persist = lambda: "saved"
hub_.bindings = {"github:acme/widgets#60": {"home-peer"}}
EL.path().unlink(missing_ok=True); ML.path().unlink(missing_ok=True)
def hub_event(etype, who="alice", refs=None, url=f"{W_}/pull/60"):
    summary = {"title": "widgets#60", "who": who, "text": "did it", "url": url, "ts": ISO_NOW(), "etype": etype, "vouched": ALLK}
    if refs is not None: summary["meta"] = {"refs": refs}
    hub_.event("github:acme/widgets#60", summary, kind="github-state")
for et in ("pr_closed", "pr_synchronize", "pr_opened", "ci_activity", ""): hub_event(et)
hub_event("comment", "ci-helper[bot]")
check("3 the hub: a closed or opened pull request, a push, an unclassified event and a bot's comment write no line", EL.read(0)[0] == [], EL.read(0)[0])
for et in ("ci_failed", "ci_passed", "comment", "review", "review_comment"): hub_event(et, "CI" if et.startswith("ci_") else "alice")
hub_event("pr_merged", "alice", [BID(7)])
rows_, off_ = EL.read(0)
check("3 the hub: a CI result, a comment, a review (twice: a review and a review comment) and a merge each write a line, the merge with the board ids its body names",
      [r["kind"] for r in rows_] == ["ci_failed", "ci_passed", "comment", "review", "review", "merged"] and rows_[-1]["refs"] == [BID(7)] and all(r["n"] == 60 and r["repo"] == "acme/widgets" for r in rows_), rows_)
mrows, _ = ML.read(0)
check("3 the merge log is as before: it holds the merge alone, and no line of the event log is read as a merge", [r["n"] for r in mrows] == [60] and "kind" not in mrows[0] and EL.path() != ML.path(), mrows)
ML.append({"ts": 1, "repo": "acme/widgets", "n": 1, "refs": []}); check("3 merge_log.append and read keep their one-argument form", ML.read(0)[0][-1]["n"] == 1, None)

# ================================================================ 4. the pass: each kind of event of a tied pull request
anchors_ = {"projects/alpha": [{"url": f"{W_}/pull/{n}", "items": [f"a{400 + n - 31}"]} for n in (31, 32, 33, 34, 35)] + [{"url": f"{W_}/pull/36"}]}      # the project-wide anchor on 36 names no item
(T / "store/anchors.json").write_text(json.dumps(anchors_))
for i in range(400, 405): put(i)
put(410); put(411, wake="2999-01-01T00:00", phase="waiting", waits_on="time", hold=True); put(412); put(413, project="projects/alpha"); d_ = rd(413); d_["status"] = "completed"; wr(413, d_)
d_ = rd(410); d_["description"] = f"- Waits on {W_}/pull/50\n- Done when it lands"; wr(410, d_)
shown = lambda i: f"board#{i}"
def ev_pass(now, **kw):
    gh_ = server._cfg.CFG.setdefault("github", {}); had = gh_.get("issues_letter"); gh_["issues_letter"] = "a"; CLK.t = now
    try: return server._event_activity_tick(now)
    finally:
        CLK.t = None
        if had is None: gh_.pop("issues_letter", None)
        else: gh_["issues_letter"] = had
EL.path().unlink(missing_ok=True); (EL.offset_path()).unlink(missing_ok=True)
def emit(n, etype, who="alice", at=10 * MIN, refs=(), url=None):
    EL.note(f"github:acme/widgets#{n}", url or "", etype, who, list(refs), now0 + at, vouched=ALLK)
emit(31, "ci_failed", "CI", 10 * MIN); emit(32, "ci_passed", "CI", 11 * MIN); emit(33, "comment", "alice", 12 * MIN); emit(34, "review_comment", "bob", 13 * MIN); emit(35, "pr_merged", "alice", 14 * MIN)
emit(36, "comment", "alice", 15 * MIN)                                   # a project-wide anchor: names no item
emit(37, "pr_merged", "alice", 15 * MIN, [shown(401)])                    # the merged pull request's body names the item (a401), no anchor does
emit(50, "review", "bob", 16 * MIN)                                      # the item's own words name it (a410: its description holds the URL)
emit(38, "pr_merged", "alice", 17 * MIN, [shown(411), shown(413), shown(9999)])   # named: a held item, a closed one, an item that does not exist
before_all = {i: rd(i) for i in (400, 401, 402, 403, 404, 410, 411, 412, 413)}
saved = ev_pass(now0 + 20 * MIN)
check("4 the pass saves exactly the items an event is tied to: anchored (a400..a404), the body naming the item (a401), the item's own words (a410); not a project-wide anchor, a held item, a closed one",
      sorted(saved) == ["a400", "a401", "a402", "a403", "a404", "a410"], saved)
check("4 each kind has its own words, kind and time, the event's own: a400 (anchored to 31) CI failed at 10, a401 (anchored to 32, named by the merge of 37) PR 37 merged at 15 is the later, a402 comment on 33, a403 review on 34, a404 merged 35",
      la(400) == {"at": now0 + 10 * MIN, "what": "CI failed on PR 31"} and la(401) == {"at": now0 + 15 * MIN, "what": "PR 37 merged"} and la(402) == {"at": now0 + 12 * MIN, "what": "comment on #33"}
      and la(403) == {"at": now0 + 13 * MIN, "what": "review on PR 34"} and la(404) == {"at": now0 + 14 * MIN, "what": "PR 35 merged"} and la(410) == {"at": now0 + 16 * MIN, "what": "review on PR 50"}
      and [lk(i) for i in (400, 401, 402, 403, 404, 410)] == ["ci_result", "pr_merged", "comment", "review", "pr_merged", "review"], [la(i) for i in (400, 401, 402, 403, 404, 410)])
check("4 the ones not tied are untouched, file for file", all(rd(i) == before_all[i] for i in (411, 412, 413)), None)
check("4 the other clocks are as they were: activity, progress, updated, written_by, the History and merged_seen of every item saved",
      all(all(rd(i).get(k) == before_all[i].get(k) for k in ("activity", "progress", "updated", "written_by", "written_at", "confirmed", "state_updated")) and mt(i).get("merged_seen") == before_all[i]["metadata"].get("merged_seen")
          and mt(i).get("stall") == before_all[i]["metadata"].get("stall") for i in (400, 401, 402, 403, 404, 410)) and not any("last_activity" in str(before_all[i]) for i in before_all), None)
d1 = {k: v for k, v in rd(404)["metadata"].items() if k not in ("last_activity", "phase")}; check("4 …and nothing else of the metadata changed (the phase every save of the server stores aside)", d1 == before_all[404]["metadata"], d1)
check("4 the offset is stored at the end of the log it read", EL.load_offset() == EL.path().stat().st_size, EL.load_offset())
check("4 a second pass with nothing new reads nothing, saves nothing", ev_pass(now0 + 21 * MIN) == [] and rd(400) == rd(400), None)

# ================================================================ 5. the pass's care
# newest wins: a later event, then an older event that arrives afterwards (the log is in the hub's order, not the event's)
emit(31, "review", "bob", 30 * MIN); emit(31, "comment", "alice", 25 * MIN)
ev_pass(now0 + 31 * MIN)
check("5 newest wins: a later event replaces the record, an older one that arrives after it does not", la(400) == {"at": now0 + 30 * MIN, "what": "review on PR 31"}, la(400))
emit(31, "comment", "alice", 30 * MIN)
check("5 …an event at the same time as the record leaves it", ev_pass(now0 + 32 * MIN) == [] and la(400)["what"] == "review on PR 31", la(400))
# a time in the future reads as now
emit(32, "comment", "alice", 50 * MIN)
ev_pass(now0 + 40 * MIN)
check("5 an event stamped a little later than the pass (a skew of the clocks) reads as the time of the pass", la(401) == {"at": now0 + 40 * MIN, "what": "comment on #32"}, la(401))
emit(32, "review", "bob", 600 * MIN)
ev_pass(now0 + 41 * MIN)
check("5 …one stamped hours ahead is a torn line and is not read", la(401) == {"at": now0 + 40 * MIN, "what": "comment on #32"}, la(401))
# torn, malformed and oversized lines are skipped, the good ones around them are read, and the log line is bounded
off_before = EL.load_offset()
with open(EL.path(), "ab") as f_:
    f_.write(b'{"ts": 5, "repo": "acme/widgets", "n": 33, "kind":\n')                       # torn mid-object, with a newline after it
    f_.write(b'[' * 200000 + b"\n")
    f_.write(b'{"ts": 5, "repo": "acme/widgets", "n": ' + b"9" * 6000 + b', "kind": "comment"}\n')
    f_.write(b'\xff\xfe{"repo": "acme/widgets", "n": 33, "kind": "comment"}\n')
    f_.write(json.dumps({"ts": now0 + 41 * MIN, "repo": "acme/widgets", "n": 33, "kind": "x" * 100000, "refs": []}).encode() + b"\n")      # a kind that is none: refused, and huge
    f_.write(json.dumps({"ts": now0 + 41 * MIN, "repo": "acme/widgets", "n": 33, "kind": "review", "refs": ["y" * 90000]}).encode() + b"\n")      # an oversized ref: dropped, the line read
    f_.write(b'{"ts": "' + b"7" * 400 + b'", "repo": "acme/widgets", "n": 33, "kind": "comment"}\n')      # a time that overflows into infinity
    f_.write(b'{"ts": 1, "repo": "acme/widgets", "n": 33, "kind": "comment"')                # the last line is still being written: no newline
with _Err() as e_:
    saved = ev_pass(now0 + 42 * MIN)
check("5 a torn, deep, oversized, bad-byte and unknown-kind line is each skipped; the good line among them is read; the one still being written waits", saved == ["a402"] and la(402) == {"at": now0 + 41 * MIN, "what": "review on PR 33"}, (saved, la(402)))
check("5 …each skip is logged in a bounded line (never the whole row)", "line skipped" in e_.text and max(len(l) for l in e_.text.splitlines()) < 500, [len(l) for l in e_.text.splitlines()])
with open(EL.path(), "ab") as f_: f_.write(b"\n")
ev_pass(now0 + 43 * MIN)
check("5 …and the line that was being written is read whole next time (its event is older than the record, so it changes nothing)", EL.load_offset() == EL.path().stat().st_size and la(402)["what"] == "review on PR 33", (EL.load_offset(), EL.path().stat().st_size))
# restart: a fresh read of the offset file resumes there; nothing is read twice
d_ = rd(403); d_["metadata"].pop("last_activity"); wr(403, d_)
ev_pass(now0 + 44 * MIN)
check("5 a restart resumes from the offset: lines already read are not applied again (an item whose record was cleared stays clear)", la(403) is None, la(403))
emit(34, "ci_failed", "CI", 45 * MIN)
ev_pass(now0 + 46 * MIN)
check("5 …and a line written after it is read", la(403) == {"at": now0 + 45 * MIN, "what": "CI failed on PR 34"}, la(403))
# a replaced (shorter) file reads from its start
big = EL.load_offset(); EL.path().unlink()
emit(35, "comment", "alice", 50 * MIN)
check("5 the new file is shorter than the offset", EL.path().stat().st_size < big, None)
ev_pass(now0 + 51 * MIN)
check("5 an offset past the end of the file (it was replaced) reads from the start", la(404) == {"at": now0 + 50 * MIN, "what": "comment on #35"}, la(404))
# an old event is not read; a day of downtime does not fill the record with old news
emit(32, "review", "bob", -30 * H)
emit(33, "comment", "alice", 55 * MIN)
d_ = rd(401); d_["metadata"].pop("last_activity"); wr(401, d_)
ev_pass(now0 + 56 * MIN)
check("5 an event older than a day is not read (the record of an item without one is not set from it)", la(401) is None, la(401))
# one item that cannot be saved stops no other; the offset is stored
put(420); put(421)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/60", "items": ["a420", "a421"]}]}))
emit(60, "comment", "alice", 60 * MIN)
real_save = server._save
def flaky(gid, item, *a, **kw):
    if gid == "a420": raise RuntimeError("disk " + "z" * 90000)
    return real_save(gid, item, *a, **kw)
server._save = flaky
try:
    with _Err() as e_: saved = ev_pass(now0 + 61 * MIN)
finally: server._save = real_save
check("5 one item that cannot be saved is logged (bounded) and skipped, the other is saved, the offset is stored", saved == ["a421"] and la(421) == {"at": now0 + 60 * MIN, "what": "comment on #60"} and la(420) is None
      and "a420 not saved" in e_.text and max(len(l) for l in e_.text.splitlines()) < 500 and EL.load_offset() == EL.path().stat().st_size, (saved, e_.text[:300]))
# nothing raises out of the pass
emit(60, "review", "bob", 62 * MIN)
real_read = EL.read
EL.read = lambda off=0: (_ for _ in ()).throw(OSError("log gone"))
try:
    with _Err() as e_: out = server._event_activity_tick(now0 + 63 * MIN)
finally: EL.read = real_read
check("5 a failure of the read is logged and the pass returns, raising nothing", out == [] and "pass failed" in e_.text, e_.text[:200])
real_tied = server._merge_tied
server._merge_tied = lambda rows, now: (_ for _ in ()).throw(RuntimeError("items unreadable"))
off_ = EL.load_offset()
try:
    with _Err() as e_: out = ev_pass(now0 + 64 * MIN)
finally: server._merge_tied = real_tied
check("5 items that cannot be read at all: nothing is saved and the offset stays, so the lines are read again", out == [] and EL.load_offset() == off_ and "items not read" in e_.text, (out, EL.load_offset(), off_))
saved = ev_pass(now0 + 65 * MIN)
check("5 …and the next pass applies them", sorted(saved) == ["a420", "a421"] and la(420) == {"at": now0 + 62 * MIN, "what": "review on PR 60"}, (saved, la(420)))
# a read-only standby copy and a held board run nothing, and keep the offset
emit(60, "comment", "alice", 70 * MIN)
off_ = EL.load_offset()
real_ro, real_hold = server._ro.is_read_only, server._watch.holding
server._ro.is_read_only = lambda: True
try: out_ro = ev_pass(now0 + 71 * MIN)
finally: server._ro.is_read_only = real_ro
server._watch.holding = lambda *a: True
try: out_hold = ev_pass(now0 + 71 * MIN)
finally: server._watch.holding = real_hold
check("5 a read-only standby copy and a held board run nothing and keep the offset", out_ro == [] and out_hold == [] and EL.load_offset() == off_ and la(420)["at"] == now0 + 62 * MIN, (out_ro, out_hold))
saved = ev_pass(now0 + 72 * MIN)
check("5 …the pass runs when they let go", sorted(saved) == ["a420", "a421"] and la(420)["at"] == now0 + 70 * MIN, saved)
# the merge pass and the event pass together: a merge ties the same, the merge pass still records it, the words agree
ML.path().unlink(missing_ok=True); (T / "state/merge-progress.json").unlink(missing_ok=True)
put(430, mover="home-peer"); d_ = rd(430); d_["progress"] = now0 - 3 * H; wr(430, d_)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/70", "items": ["a430"]}]}))
ML.append({"ts": now0 + 80 * MIN, "repo": "acme/widgets", "n": 70, "refs": []}); emit(70, "pr_merged", "alice", 80 * MIN)
CLK.t = now0 + 81 * MIN
gh_ = server._cfg.CFG.setdefault("github", {}); gh_["issues_letter"] = "a"
try: moved = server._merge_progress_tick(now0 + 81 * MIN)
finally: CLK.t = None
check("5 the merge pass is as before: it records the merge in merged_seen and moves progress, and the record says which pull request merged", moved == ["a430"] and mt(430).get("merged_seen") == ["acme/widgets#70"] and rd(430)["progress"] == now0 + 81 * MIN
      and la(430) == {"at": now0 + 81 * MIN, "what": "PR 70 merged"}, (moved, la(430), rd(430).get("progress")))
d_ = rd(430); progress_, activity_ = d_["progress"], d_["activity"]
saved = ev_pass(now0 + 82 * MIN)
check("5 …and the event pass finds its merge event older than the record: nothing is written", saved == [] and rd(430)["progress"] == progress_ and rd(430)["activity"] == activity_ and la(430)["at"] == now0 + 81 * MIN, (saved, la(430)))


# ================================================================ 6. a body names an item for anyone: only a merge ties through it
for i in (440, 441): put(i)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/80", "items": ["a441"]}]}))
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
hub_.bindings["github:acme/widgets#81"] = {"home-peer"}; hub_.bindings["github:acme/widgets#80"] = {"home-peer"}
def hub_on(n, etype, who="mallory", refs=None):
    summary = {"title": f"widgets#{n}", "who": who, "text": "did it", "url": f"{W_}/pull/{n}", "ts": ISO_NOW(), "etype": etype, "vouched": ALLK}
    if refs is not None: summary["meta"] = {"refs": refs}
    hub_.event(f"github:acme/widgets#{n}", summary, kind="github-state")
CLK.t = None
hub_on(81, "comment", refs=[BID(440)]); hub_on(81, "review", refs=[BID(440)]); hub_on(81, "ci_failed", "CI", refs=[BID(440)])
ML.append({"ts": time.time(), "repo": "acme/widgets", "n": 81, "kind": "comment", "refs": [BID(440)]}, EL.path())      # a line written by hand, or by a hub of the other build, with ids on a comment
check("6 a comment, a review and a CI result on a pull request whose body names an item, with no anchor scoped to the item, write lines with no ids", all(r["refs"] == [] for r in EL.read(0)[0][:3]) and len(EL.read(0)[0]) == 4 and all(EL.normal(r)["refs"] == [] for r in EL.read(0)[0]), EL.read(0)[0])
def ev_pass_now(): return ev_pass(time.time() + 5)
saved = ev_pass_now()
check("6 …and the pass stamps nothing for them: a body naming an item is not a tie for a comment, a review or a CI result (anyone can open such a pull request)", saved == [] and la(440) is None and la(441) is None, (saved, la(440)))
hub_on(80, "comment", refs=[BID(441)]); EL.note("github:acme/widgets#80", "", "review", "bob", [], time.time() + 3, vouched=ALLK)
saved = ev_pass_now()
check("6 …with an anchor scoped to the item the same events stamp it", saved == ["a441"] and la(441)["what"] == "review on PR 80" and lk(441) == "review" and la(440) is None, (saved, la(441)))
hub_on(81, "pr_merged", "alice", refs=[BID(440)])
saved = ev_pass_now()
check("6 …and a merge keeps the body tie (the rule of the merge log): the item the merged pull request's body names is stamped", saved == ["a440"] and la(440)["what"] == "PR 81 merged" and lk(440) == "pr_merged", (saved, la(440)))

# ================================================================ 6b. a line the hub is still writing waits; a file that ends without a newline gets one before the next line
for i in (450, 451, 452): put(i)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/{n}", "items": [f"a{i}"]} for n, i in ((90, 450), (91, 451), (92, 452))]}))
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
t0_ = time.time()
row_ = json.dumps({"ts": t0_, "repo": "acme/widgets", "n": 90, "kind": "review", "refs": []}).encode()
half = len(row_) // 2
EL.path().write_bytes(row_[:half])      # the first half of a valid line, no newline: the hub is mid-write
saved = ev_pass(t0_ + 60)
check("6b half a line is not read: nothing is stamped and the offset stays before it", saved == [] and la(450) is None and EL.load_offset() == 0, (saved, EL.load_offset()))
with open(EL.path(), "ab") as f_: f_.write(row_[half:] + b"\n")
saved = ev_pass(t0_ + 61)
check("6b …the rest and the newline arrive: the line is read whole and applied (the offset moves past it)", saved == ["a450"] and la(450) == {"at": t0_, "what": "review on PR 90"} and EL.load_offset() == EL.path().stat().st_size, (saved, la(450)))
row2 = json.dumps({"ts": t0_ + 5, "repo": "acme/widgets", "n": 91, "kind": "comment", "refs": []}).encode()
size_before = EL.path().stat().st_size
with open(EL.path(), "ab") as f_: f_.write(row2)      # a whole line whose newline is not there yet
saved = ev_pass(t0_ + 62)
check("6b a line that is whole but has no newline yet is not read either", saved == [] and la(451) is None and EL.load_offset() == size_before, (saved, EL.load_offset(), size_before))
EL.note("github:acme/widgets#92", "", "ci_failed", "CI", [], t0_ + 10, vouched=ALLK)      # the next line is appended to a file that does not end with a newline
check("6b …the next line starts on a line of its own (the file got its newline first), so both rows read apart", EL.path().read_bytes().count(b"\n") == 3 and b"}{" not in EL.path().read_bytes(), EL.path().read_bytes()[-200:])
saved = ev_pass(t0_ + 63)
check("6b …and both are applied at the next pass", sorted(saved) == ["a451", "a452"] and la(451) == {"at": t0_ + 5, "what": "comment on #91"} and la(452)["what"] == "CI failed on PR 92", (saved, la(451), la(452)))

# ================================================================ 6c. a stored record that is torn is repaired by the next signal; the words are one clean line
check("6c clean: a kind that is a list, a dict or a number, and a time too large for a float, are torn signals, not an error",
      all(LA.clean({"at": 5, "kind": k, "what": "x"}) is None for k in (["step_done"], {"a": 1}, 7, None, ("comment",))) and LA.clean({"at": 10 ** 400, "kind": "comment", "what": "x"}) is None and LA.read({"metadata": {"last_activity": {"at": 5, "kind": ["x"], "what": "y"}}}) is None, None)
torn_item = {"status": "open", "metadata": {"last_activity": {"at": 5, "kind": ["step_done"], "what": "x"}}}
check("6c apply: a torn stored record is replaced by the next signal, whatever its time", LA.apply(torn_item, [{"at": 3, "kind": "comment", "what": "older but whole"}]) and torn_item["metadata"]["last_activity"] == {"at": 3.0, "kind": "comment", "what": "older but whole"}, torn_item)
put(460, last_activity={"at": 5, "kind": ["step_done"], "what": "x"}); put(461, last_activity={"at": 5, "kind": {"a": 1}, "what": "x"})
with _Err() as e_:
    save_at(now0 + 5 * MIN, 460, lambda d_: d_["metadata"].update(steps=[step("home-peer: do the thing", "done", now0 + 5 * MIN), step("home-peer: more", "open")], next="home-peer: more"))
check("6c a save with a torn stored record logs nothing and repairs it", la(460) == {"at": now0 + 5 * MIN, "what": "step 1 done"} and "not recorded" not in e_.text and "clock not stamped" not in e_.text, (la(460), e_.text[:200]))
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/95", "items": ["a461"]}]}))
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
EL.note("github:acme/widgets#95", "", "comment", "alice", [], now0 + 6 * MIN, vouched=ALLK)
with _Err() as e_: saved = ev_pass(now0 + 7 * MIN)
check("6c …and so does the event pass: the record is whole after it, and the item is saved once", saved == ["a461"] and la(461) == {"at": now0 + 6 * MIN, "what": "comment on #95"} and "not saved" not in e_.text, (saved, la(461), e_.text[:200]))
import unicodedata
dirty = "first\nsecond\t\x1b[31m red\x00 end​‮ done " + "w" * 200
sigs = [LA.update_signal("", dirty, 9), LA.audit_signal(dirty, 9), LA.signal("audit", 9, dirty)]
check("6c update and audit words: one line of at most 80 characters with no control or format character, however they are written", all(x and len(x["what"]) <= 80 and all(unicodedata.category(c)[0] != "C" for c in x["what"]) and x["what"].startswith("first second [31m red end done") for x in sigs), [x and x["what"] for x in sigs])
check("6c …a text of nothing but control characters is no signal", LA.audit_signal("\x00\x1b\n\t", 9) is None and LA.update_signal("a", "\x07\x08", 9) is None, None)

# ================================================================ 7. the hub's events are as they were: a comment's direct notice is byte for byte the notice it had (no ids from the pull request's body in its meta)
import types, subprocess
ghr = __import__("stackshot.anchors.anchorhub.github", fromlist=["x"])
RP = "/repos/acme/widgets"; AN = "github:acme/widgets#26"; NA = "github:acme/widgets@notifications"; NPATH = f"{RP}/notifications?all=true&per_page=50"
BODY = "Closes " + BID(440) + " and more"
def pr_issue(**kw): return {"state": "open", "comments": 0, "updated_at": "2026-10-28T00:00:00Z", "title": "a thing", "html_url": f"{W_}/pull/26", "body": BODY, "pull_request": {"merged_at": None}, **kw}
def thread(updated): return {"id": "t1", "updated_at": updated, "reason": "comment", "subject": {"type": "PullRequest", "url": f"https://api.github.com{RP}/pulls/5", "title": "a pull request"}, "repository": {"id": 7}}
GHD = {"/user": {"login": "hubaccount"}, f"{RP}/pulls/26": {"head": {"sha": "a" * 40, "ref": "x/y"}, "user": {"login": "someone"}, "base": {"repo": {"id": 7}}},
       f"{RP}/commits/{'a' * 40}/check-runs?per_page=100": {"check_runs": [{"name": "suites", "status": "completed", "conclusion": "success"}]},
       f"{RP}/issues/26": pr_issue(), NPATH: [thread("2026-10-28T00:00:00Z")], f"{RP}/issues/5": pr_issue(html_url=f"{W_}/pull/5", comments=1, updated_at="2026-10-28T02:00:00Z")}
def _fake_gh(args, capture_output=True, text=True, timeout=30):
    a = [x for x in args[2:] if x != "-i" and x != "-H" and not x.startswith("If-None-Match")]; path = a[0]; cond = "-i" in args
    body = json.dumps(GHD.get(path, [])); return types.SimpleNamespace(returncode=0, stdout=("HTTP/2.0 200 OK\netag: \"x\"\n\n" + body) if cond else body, stderr="")
class _Stop(Exception): pass
def _no_sleep(s): raise _Stop()
caught = []; _sub, _thr, _tim = ghr.subprocess, ghr.threading, ghr.time
ghr.subprocess = types.SimpleNamespace(run=_fake_gh, TimeoutExpired=subprocess.TimeoutExpired)
ghr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
ghr.time = types.SimpleNamespace(time=time.time, sleep=_no_sleep)
hub2 = HUB.Hub(); hub2.write_status = lambda: None; evs = []; hub2.emit = evs.append
hub2.bindings = {AN: {"home-peer"}, NA: {"home-peer"}}
def one_pass():
    try: caught[0]()
    except _Stop: pass
try:
    ghr.run(hub2); one_pass()      # the first pass seeds what it sees
    del evs[:]
    GHD[f"{RP}/issues/26"] = pr_issue(comments=1, updated_at="2026-10-28T01:00:00Z")
    GHD[f"{RP}/issues/26/comments?since=2026-10-28T00:00:00Z&per_page=20"] = [{"user": {"login": "kim", "type": "User"}, "body": "please look at this", "html_url": f"{W_}/pull/26#issuecomment-1", "created_at": "2026-10-28T00:30:00Z"}]
    GHD[NPATH] = [thread("2026-10-28T03:00:00Z")]
    since = "2026-10-28T00:00:00Z"
    GHD[f"{RP}/issues/5/comments?since={since}&per_page=50"] = [{"user": {"login": "kim", "type": "User"}, "body": "x", "html_url": f"{W_}/pull/5#issuecomment-2", "created_at": "2026-10-28T02:30:00Z"}]
    GHD[f"{RP}/pulls/5/reviews?per_page=100"] = [{"user": {"login": "lee", "type": "User"}, "state": "APPROVED", "html_url": f"{W_}/pull/5#pullrequestreview-3", "submitted_at": "2026-10-28T02:40:00Z"}]
    GHD[f"{RP}/pulls/5/comments?since={since}&per_page=50"] = [{"user": {"login": "lee", "type": "User"}, "body": "y", "html_url": f"{W_}/pull/5#discussion_r4", "created_at": "2026-10-28T02:45:00Z"}]
    one_pass()
    got = {(e.anchor, e.etype): e for e in evs}
    c_ = got.get((AN, "comment")); t_ = got.get((NA, "comment+review+review_comment"))
    check("7 the hub reads the comment on the anchored pull request whose body names an item, and a thread of the repository's notifications likewise", c_ is not None and t_ is not None, [(e.anchor, e.etype) for e in evs])
    check("7 …neither carries ids from the body in its meta", (c_ and not c_.meta) and (t_ and not t_.meta), (c_ and c_.meta, t_ and t_.meta))
    check("7 …so the direct notice of the comment is the one-line notice it was, byte for byte: the text is there",
          c_ is not None and HUB.direct_notice(c_) == HUB.notice(c_) == f'[anchor] {c_.label}: comment by kim: "please look at this" → {W_}/pull/26#issuecomment-1' and "please look at this" in HUB.direct_notice(c_), c_ and HUB.direct_notice(c_))
    check("7 a comment by an ordinary account is not marked as a bot's", c_ is not None and c_.bot is False, c_ and c_.bot)
    GHD[f"{RP}/issues/26"] = pr_issue(comments=2, updated_at="2026-10-28T02:00:00Z")
    GHD[f"{RP}/issues/26/comments?since=2026-10-28T01:00:00Z&per_page=20"] = [{"user": {"login": "helper", "type": "Bot"}, "body": "a helper wrote this", "html_url": f"{W_}/pull/26#issuecomment-9", "created_at": "2026-10-28T01:30:00Z"}]
    del evs[:]; one_pass()
    b_ = next((e for e in evs if e.anchor == AN and e.etype == "comment"), None)
    check("7 a comment whose author the payload types as Bot is marked as one (no extra read; the login has no [bot] suffix)", b_ is not None and b_.bot is True and "helper" in b_.who, [(e.anchor, e.etype, e.bot, e.who) for e in evs])
    check("7 …the marked comment is still the one-line notice it was (the mark is not in the meta)", b_ is not None and HUB.direct_notice(b_) == HUB.notice(b_) and not b_.meta, b_ and (b_.meta, HUB.direct_notice(b_)))
    GHD[f"{RP}/issues/26"] = pr_issue(comments=1, updated_at="2026-10-28T04:00:00Z", state="closed", closed_at="2026-10-28T04:00:00Z", closed_by={"login": "alice"}, pull_request={"merged_at": "2026-10-28T04:00:00Z"})
    del evs[:]; one_pass()
    m_ = next((e for e in evs if e.etype == "pr_merged" and e.anchor == AN), None)
    check("7 a merge keeps its ids for the merge log (meta refs) and its direct notice is still the one-line notice (the ids are not a source's, so they do not turn it into the full form)",
          m_ is not None and m_.meta == {"refs": [BID(440)]} and HUB.direct_notice(m_) == HUB.notice(m_), m_ and (m_.meta, HUB.direct_notice(m_)))
finally:
    ghr.subprocess, ghr.threading, ghr.time = _sub, _thr, _tim
sl_ = HUB.Event(anchor="slack:C1", kind="slack", title="#team", who="kim", text="hi", url="https://example.invalid/m", meta={"ts": "1.5", "thread_ts": "1.2", "refs": [BID(1)]}, full="the whole text")
check("7 a Slack event keeps its full form (its ids in the header, the whole text below), the ids of a body aside", HUB.direct_notice(sl_) == "[anchor] Slack #team: new message from kim (ts 1.5 · thread_ts 1.2) → https://example.invalid/m\nthe whole text", HUB.direct_notice(sl_))

# ================================================================ 8. one save for many lines of an item; a stored time ahead of the clock; the item read again under the lock; a bot by its type
for i in (470, 471, 472, 473, 474): put(i)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/{n}", "items": [f"a{i}"]} for n, i in ((100, 470), (101, 471), (102, 472), (103, 473), (104, 474))]}))
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
t8 = now0 + 100 * MIN
emit(100, "comment", "alice", 101 * MIN); emit(100, "review", "bob", 104 * MIN); emit(100, "ci_failed", "CI", 102 * MIN); emit(100, "comment", "carol", 103 * MIN)      # the log is in the hub's order, not the events'
emit(100, "review", "dan", 95 * MIN)
saves_ = []
real_save = server._save
def counting(gid, item, *a, **kw):
    saves_.append(gid); return real_save(gid, item, *a, **kw)
server._save = counting
try: saved = ev_pass(t8 + 10 * MIN)
finally: server._save = real_save
check("8 five lines for one item are one save, and the newest of them is the record", saves_ == ["a470"] and saved == ["a470"] and la(470) == {"at": t8 + 4 * MIN, "what": "review on PR 100"} and lk(470) == "review", (saves_, saved, la(470)))
# a stored time later than the clock must not block every later signal
put(471, last_activity={"at": t8 + 500 * H, "kind": "comment", "what": "comment on #1"})
emit(101, "review", "bob", 111 * MIN)
saved = ev_pass(t8 + 12 * MIN)
check("8 a stored record dated far ahead of the clock is replaced by the next real signal (it would otherwise hide every later one)", saved == ["a471"] and la(471) == {"at": t8 + 11 * MIN, "what": "review on PR 101"}, (saved, la(471)))
ahead = {"status": "open", "metadata": {"last_activity": {"at": 900.0, "kind": "comment", "what": "x"}}}
check("8 last_activity: with a clock given, a stored time after it is ignored; without one, as it was (newest wins)",
      LA.apply(dict(ahead, metadata=dict(ahead["metadata"])), [S_(50)], now=100) and not LA.apply(dict(ahead, metadata=dict(ahead["metadata"])), [S_(50)])
      and LA.record(ahead, [S_(50)], 100)["at"] == 50.0 and LA.record(ahead, [S_(50)])["at"] == 900.0, None)
# the item is read again under the lock: closed, held or begun to wait between the tie and the save
real_tied = server._merge_tied
def tie_then(mutate):
    def f(rows, now):
        out = real_tied(rows, now); mutate(); return out
    return f
def close_it():
    d_ = rd(472); d_["status"] = "completed"; wr(472, d_)
def hold_it():
    d_ = rd(473); d_["metadata"]["hold"] = True; wr(473, d_)
def wait_it():
    d_ = rd(474); d_["metadata"].update(wake="2999-01-01T00:00", phase="waiting", waits_on="time"); wr(474, d_)
for n_, i_, fn_, what_ in ((102, 472, close_it, "closed"), (103, 473, hold_it, "put on hold"), (104, 474, wait_it, "begun to wait")):
    emit(n_, "comment", "alice", 121 * MIN)
    server._merge_tied = tie_then(fn_)
    try: saved = ev_pass(t8 + 22 * MIN)
    finally: server._merge_tied = real_tied
    after_ = rd(i_)
    check(f"8 an item {what_} between the tie and the save is not stamped", saved == [] and "last_activity" not in after_["metadata"], (saved, after_["metadata"].get("last_activity")))
# a bot by its type: the payload says Bot, the login has no suffix
check("8 lines_for: a comment or review whose payload types the author as a bot is left out whatever the login; CI and a merge are kept",
      EL.lines_for(A_, "", "comment", "helper", [], 10.0, True, vouched=ALLK) == [] and EL.lines_for(A_, "", "review", "helper", [], 10.0, True, vouched=ALLK) == [] and len(EL.lines_for(A_, "", "comment", "helper", [], 10.0, False, vouched=ALLK)) == 1
      and len(EL.lines_for(A_, "", "ci_failed", "helper", [], 10.0, True, vouched=ALLK)) == 1 and len(EL.lines_for(A_, "", "pr_merged", "helper", [], 10.0, True)) == 1, None)
EL.path().unlink(missing_ok=True)
hub_.event("github:acme/widgets#60", {"title": "widgets#60", "who": "helper", "text": "did it", "url": f"{W_}/pull/60", "ts": ISO_NOW(), "etype": "comment", "bot": True, "vouched": ALLK}, kind="github-state")
check("8 the hub: an event the source marks as a bot's writes no line, the same without the mark writes one", EL.read(0)[0] == [], EL.read(0)[0])
hub_.event("github:acme/widgets#60", {"title": "widgets#60", "who": "helper", "text": "did it", "url": f"{W_}/pull/60", "ts": ISO_NOW(), "etype": "comment", "vouched": ALLK}, kind="github-state")
check("8 …and without the mark it writes one", len(EL.read(0)[0]) == 1, EL.read(0)[0])

# ================================================================ 9. who counts: only the repository's own side is activity; a CI result counts from a branch of the repository itself
class GH:
    """The GitHub receiver on a fake `gh`: `ghd` maps an API path to its answer (a "404" string is a refusal); the receiver's events are kept in `evs` instead of being routed."""
    def __init__(self, ghd, anchors):
        self.ghd, self.caught, self.evs = ghd, [], []
        self.hub = HUB.Hub(); self.hub.write_status = lambda: None; self.hub.emit = self.evs.append; self.hub.bindings = {a: {"home-peer"} for a in anchors}
    def __enter__(self):
        self.old = (ghr.subprocess, ghr.threading, ghr.time)
        def fake(args, capture_output=True, text=True, timeout=30):
            a = [x for x in args[2:] if x != "-i" and x != "-H" and not x.startswith("If-None-Match")]; path = a[0]; cond = "-i" in args
            ans = self.ghd.get(path, [])
            if ans == "404": return types.SimpleNamespace(returncode=1, stdout="", stderr="gh: Not Found (HTTP 404)")
            body = json.dumps(ans); return types.SimpleNamespace(returncode=0, stdout=("HTTP/2.0 200 OK\netag: \"x\"\n\n" + body) if cond else body, stderr="")
        ghr.subprocess = types.SimpleNamespace(run=fake, TimeoutExpired=subprocess.TimeoutExpired)
        ghr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: self.caught.append(target)))
        ghr.time = types.SimpleNamespace(time=time.time, sleep=_no_sleep)
        ghr.run(self.hub); return self
    def one(self):
        del self.evs[:]
        try: self.caught[0]()
        except _Stop: pass
        return list(self.evs)
    def __exit__(self, *a): ghr.subprocess, ghr.threading, ghr.time = self.old
tb_ = time.time() - 2 * H
def iso9(dt): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tb_ + dt))      # a source's time, a little before now, built at run time
def pr9(n, head="acme/widgets", base="acme/widgets", sha=None, **kw):
    sha = sha or f"{n:02d}" * 20
    pull = {"head": {"sha": sha, "ref": "x/y", "repo": ({"full_name": head} if head else None)}, "user": {"login": "someone"}, "base": {"repo": {"id": 7, **({"full_name": base} if base else {})}}}
    return {f"/repos/acme/widgets/pulls/{n}": pull, f"/repos/acme/widgets/issues/{n}": {"state": "open", "comments": 0, "updated_at": iso9(0), "title": "a thing", "html_url": f"{W_}/pull/{n}", "body": "", "pull_request": {"merged_at": None}, **kw},
            f"/repos/acme/widgets/commits/{sha}/check-runs?per_page=100": {"check_runs": [{"name": "suites", "status": "completed", "conclusion": "success"}]}}
ASSOC = (("OWNER", True), ("MEMBER", True), ("COLLABORATOR", True), ("CONTRIBUTOR", False), ("NONE", False), ("FIRST_TIMER", False), ("FIRST_TIME_CONTRIBUTOR", False), ("MANNEQUIN", False), ("SOMETHING_NEW", False), ("member", False), (None, False))

# the rule itself, in the one place the lines are made
check("9 trusted_association: OWNER, MEMBER and COLLABORATOR only; every other value, a missing one and a value of another type are a stranger's",
      [EL.trusted_association(a) for a, _ in ASSOC] == [ok for _, ok in ASSOC] and not EL.trusted_association(5) and not EL.trusted_association(["OWNER"]) and not EL.trusted_association({"OWNER"}), None)
check("9 lines_for: a comment, a review and a CI result are lines only when the source vouched for that kind; nothing vouched writes none of them, a merge is not filtered",
      lines(A_, "", "comment+review+ci_failed+pr_merged", vouched="") and [r["kind"] for r in lines(A_, "", "comment+review+ci_failed+pr_merged", vouched="")] == ["merged"]
      and [r["kind"] for r in lines(A_, "", "comment+review+ci_passed", vouched="comment")] == ["comment"] and [r["kind"] for r in lines(A_, "", "comment+review", vouched="review+ci_failed")] == ["review"]
      and [r["kind"] for r in lines(A_, "", "ci_failed", vouched=["ci_failed"])] == ["ci_failed"] and lines(A_, "", "ci_failed", vouched=None) == [] and lines(A_, "", "comment", vouched=5) == [], None)
check("9 lines_for: a bot's comment stays out even when vouched", lines(A_, "", "comment", "helper", vouched="comment", ) != [] and lines(A_, "", "comment", "helper[bot]", vouched="comment") == [], None)

# the receiver: what it vouches for, by the payload alone (no read of its own)
AN9 = "github:acme/widgets#26"
g9 = {"/user": {"login": "hubaccount"}, **pr9(26)}
with GH(g9, [AN9]) as G:
    G.hub.status.setdefault("anchors", {})
    G.one()      # seeds
    got9 = []
    for i, (assoc, ok) in enumerate(ASSOC):
        prev, new = iso9(i * 60), iso9((i + 1) * 60)
        g9[f"{RP}/issues/26"] = pr9(26)[f"{RP}/issues/26"] | {"comments": i + 1, "updated_at": new}
        g9[f"{RP}/issues/26/comments?since={prev}&per_page=20"] = [{"user": {"login": f"u{i}", "type": "User"}, "body": "hello", "html_url": f"{W_}/pull/26#issuecomment-{i}", "created_at": iso9(i * 60 + 30), **({"author_association": assoc} if assoc is not None else {})}]
        e9 = [e for e in G.one() if e.etype == "comment"]
        got9.append(e9[0] if e9 else None)
check("9 the receiver vouches for a comment on an anchored pull request exactly for OWNER, MEMBER and COLLABORATOR (each value, a missing one and a lower-case one tried)",
      all(e is not None for e in got9) and [e.vouched for e in got9] == ["comment" if ok else "" for _, ok in ASSOC], [e and e.vouched for e in got9])
check("9 …and the notice text is untouched by it (the same one-line notice, no ids in the meta)", all(HUB.direct_notice(e) == HUB.notice(e) and not e.meta for e in got9), None)

# A: a stranger comments on a pull request whose anchor is scoped to an item; B: the item's own words name an issue of a repository the project anchors
put(480); put(481); d_ = rd(481); d_["description"] = "- Waiting for the reply on #81\n- Done when it replies"; wr(481, d_)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/26", "items": ["a480"]}, {"url": f"{W_}/pull/27"}]}))
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
hub_.bindings[AN9] = {"home-peer"}; hub_.bindings["github:acme/widgets#81"] = {"home-peer"}
strangers = [e for e, (a, ok) in zip(got9, ASSOC) if not ok]; members = [e for e, (a, ok) in zip(got9, ASSOC) if ok]
for e in strangers: hub_.emit(e)
b9 = HUB.Event(anchor="github:acme/widgets#81", kind="github", title="widgets#81", who="mallory", text="please look", url=f"{W_}/issues/81#issuecomment-9", ts=iso9(100), etype="comment", vouched="")
hub_.emit(b9)
check("9 A+B: a stranger's comment on the anchored pull request and on the issue the item's words name write no line", EL.read(0)[0] == [], EL.read(0)[0])
saved = ev_pass_now()
check("9 …so the pass stamps neither item (a480 anchored to the pull request, a481 naming #81)", saved == [] and la(480) is None and la(481) is None, (saved, la(480), la(481)))
hub_.emit(members[0])
rows9, _ = EL.read(0)
saved = ev_pass_now()
check("9 A: a member's comment on the same pull request still stamps the anchored item, at the comment's own time", saved == ["a480"] and la(480)["what"] == "comment on #26" and lk(480) == "comment" and la(481) is None
      and abs(la(480)["at"] - (tb_ + 30)) < 2 and len(rows9) == 1, (saved, la(480), rows9))
hub_.emit(HUB.Event(anchor="github:acme/widgets#81", kind="github", title="widgets#81", who="maintainer", text="done", url=f"{W_}/issues/81#issuecomment-10", ts=iso9(200), etype="comment", vouched="comment"))
saved = ev_pass_now()
check("9 B: a collaborator's comment on the issue the item's words name stamps that item", saved == ["a481"] and la(481)["what"] == "comment on #81" and lk(481) == "comment", (saved, la(481)))

# a review and a review comment from a thread of the repository's notifications: vouched by the association of the reviewers
NA9 = "github:acme/widgets@notifications"; NP9 = f"{RP}/notifications?all=true&per_page=50"
def thread9(updated, k=0, n=5): return {"id": "t9", "updated_at": updated, "reason": "comment", "subject": {"type": "PullRequest", "url": f"https://api.github.com{RP}/pulls/{n}", "title": f"a pull request {k}"}, "repository": {"id": 7}}      # a title of its own each round: one thread update is one notice
n9 = {"/user": {"login": "hubaccount"}, NP9: [thread9(iso9(0))], f"{RP}/issues/5": {"state": "open", "comments": 1, "updated_at": iso9(0), "title": "t", "html_url": f"{W_}/pull/5", "body": "", "pull_request": {"merged_at": None}}}
with GH(n9, [NA9]) as G:
    G.one()
    since9 = iso9(0)
    def thread_case(cassoc, rassoc, rcassoc, k):
        global since9
        n9[NP9] = [thread9(iso9(k * 100 + 50), k)]
        n9[f"{RP}/issues/5/comments?since={since9}&per_page=50"] = [{"user": {"login": "kim", "type": "User"}, "body": "x", "html_url": f"{W_}/pull/5#issuecomment-1", "created_at": iso9(k * 100 + 10), "author_association": cassoc}]
        n9[f"{RP}/pulls/5/reviews?per_page=100"] = [{"user": {"login": "lee", "type": "User"}, "state": "APPROVED", "html_url": f"{W_}/pull/5#pullrequestreview-3", "submitted_at": iso9(k * 100 + 20), "author_association": rassoc}]
        n9[f"{RP}/pulls/5/comments?since={since9}&per_page=50"] = [{"user": {"login": "lee", "type": "User"}, "body": "y", "html_url": f"{W_}/pull/5#discussion_r4", "created_at": iso9(k * 100 + 30), "author_association": rcassoc}]
        out = G.one(); since9 = iso9(k * 100 + 50)
        return [e for e in out if e.anchor == NA9]
    th1 = thread_case("NONE", "MEMBER", "NONE", 1)
    th2 = thread_case("COLLABORATOR", "FIRST_TIMER", "CONTRIBUTOR", 2)
    th3 = thread_case("NONE", "NONE", "OWNER", 3)
    th4 = thread_case("CONTRIBUTOR", "NONE", "NONE", 4)
check("9 a thread of the notifications vouches per kind: a member's review (review), a collaborator's comment (comment), an owner's review comment (review), strangers alone nothing",
      [e.vouched for e in th1 + th2 + th3 + th4] == ["review", "comment", "review", ""] and all(e.etype == "comment+review+review_comment" for e in th1 + th2 + th3 + th4), [(e.etype, e.vouched) for e in th1 + th2 + th3 + th4])
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
hub_.bindings[NA9] = {"home-peer"}
for e in th1 + th2 + th3 + th4: hub_.emit(e)
kinds9 = [r["kind"] for r in EL.read(0)[0]]
check("9 …and the event log keeps exactly those kinds (4 events of three kinds each: 3 vouched kinds in all)", kinds9 == ["review", "comment", "review"], kinds9)

# CI: from a branch of the repository itself; a fork's, a deleted fork's and a payload that does not say are not
anchors9 = {n: f"github:acme/widgets#{n}" for n in (30, 31, 32, 33)}
g30 = {"/user": {"login": "hubaccount"}, **pr9(30), **pr9(31, head="mallory/widgets"), **pr9(32, head=None), **pr9(33, head=None, base=None)}
g30[f"{RP}/pulls/33"] = {"head": {"sha": "33" * 20, "ref": "x/y"}, "user": {"login": "someone"}, "base": {"repo": {"id": 7}}}      # a pull request read that names no repositories at all
with GH(g30, list(anchors9.values())) as G:
    G.hub.status.setdefault("anchors", {})
    G.one()      # seeds the passing state
    for n in anchors9:
        g30[f"{RP}/commits/{str(n) * 20}/check-runs?per_page=100"] = {"check_runs": [{"name": "suites", "status": "completed", "conclusion": "failure"}]}
    ci9 = {e.anchor: e for e in G.one() if e.etype == "ci_failed"}
check("9 the receiver vouches for a CI result only when the head repository is the base repository: the repository's own branch yes; a fork, a deleted fork and a payload that names none no",
      sorted(ci9) == sorted(anchors9.values()) and [ci9[anchors9[n]].vouched for n in anchors9] == ["ci_failed", "", "", ""], {a: e.vouched for a, e in ci9.items()})
put(482); put(483)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/30", "items": ["a482"]}, {"url": f"{W_}/pull/31", "items": ["a483"]}]}))
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
for a_, e in ci9.items(): hub_.bindings[a_] = {"home-peer"}; hub_.emit(e)
saved = ev_pass_now()
check("9 CI: a failure on the repository's own branch stamps the item anchored to it; the same on a fork's pull request stamps nothing", saved == ["a482"] and la(482)["what"] == "CI failed on PR 30" and lk(482) == "ci_result" and la(483) is None, (saved, la(482), la(483)))

# ================================================================ 10. the line's time is the event's own when sane (a backlog after downtime is not now)
now10 = 1_800_000_000.0
iso_at = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
check("10 event_time: own time kept", EL.event_time(iso_at(now10 - 10 * H), now10) == now10 - 10 * H and EL.event_time(now10 - 5 * H, now10) == now10 - 5 * H and EL.event_time(iso_at(now10 - 3 * H).replace("Z", "+00:00"), now10) == now10 - 3 * H, EL.event_time(iso_at(now10 - 10 * H), now10))
check("10 event_time: absent, empty, unreadable, boolean, infinite and negative times fall back to the hub's own",
      all(EL.event_time(t, now10) == now10 for t in (None, "", "not a time", "2026-13-45T99:99:99Z", True, float("inf"), float("nan"), -5, 0, "x" * 500, [], {})), [EL.event_time(t, now10) for t in (None, "", "bad", True, float("inf"))])
check("10 event_time: older than a day, or more than an hour ahead, is dropped (None): the rule the pass has always applied to a line; just inside both is kept",
      EL.event_time(iso_at(now10 - 25 * H), now10) is None and EL.event_time(iso_at(now10 + 2 * H), now10) is None and EL.event_time(iso_at(now10 - 23 * H), now10) == now10 - 23 * H and EL.event_time(iso_at(now10 + 0.5 * H), now10) == now10 + 0.5 * H, None)
check("10 a naive time is read in the instance's timezone, as the hub writes its own",
      abs(EL.event_time(__import__("datetime").datetime.fromtimestamp(now10 - 2 * H, server._cfg.tz()).strftime("%Y-%m-%d %H:%M:%S"), now10) - (now10 - 2 * H)) < 1, None)
check("10 lines_for: the line carries the event's own time; an event outside the window writes none, one with no time the hub's",
      lines(A_, "", "comment", now=now10, ts=iso_at(now10 - 10 * H))[0]["ts"] == now10 - 10 * H and lines(A_, "", "comment", now=now10, ts=iso_at(now10 - 30 * H)) == [] and lines(A_, "", "comment", now=now10, ts=iso_at(now10 + 3 * H)) == []
      and lines(A_, "", "comment", now=now10)[0]["ts"] == now10 and lines(A_, "", "pr_merged", now=now10, ts=iso_at(now10 - 2 * H))[0]["ts"] == now10 - 2 * H, None)
# end to end: a backlog the hub reads after downtime
put(490); put(491); put(492)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/{n}", "items": [f"a{i}"]} for n, i in ((110, 490), (111, 491), (112, 492))]}))
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
for n in (110, 111, 112): hub_.bindings[f"github:acme/widgets#{n}"] = {"home-peer"}
def hub_ts(n, ts, vouched="comment"):
    e = HUB.Event(anchor=f"github:acme/widgets#{n}", kind="github", title=f"widgets#{n}", who="maintainer", text="x", url=f"{W_}/pull/{n}", etype="comment", vouched=vouched)
    if ts is not _NOTS: e.ts = ts
    hub_.emit(e)
_NOTS = object()
t_h = time.time()
hub_ts(110, iso_at(t_h - 10 * H)); hub_ts(111, _NOTS); hub_ts(112, iso_at(t_h + 3 * H))
rows10, _ = EL.read(0)
check("10 the hub: a comment from ten hours ago keeps its own time, one without a time gets the hub's, one dated three hours ahead writes no line (a torn clock, as the pass reads it)",
      [r["n"] for r in rows10] == [110, 111] and abs(rows10[0]["ts"] - (t_h - 10 * H)) < 2 and abs(rows10[1]["ts"] - t_h) < 5, rows10)
saved = ev_pass(t_h + 60)
check("10 the pass: the old comment stamps its own time, not the pass's; the absent time stamps now", sorted(saved) == ["a490", "a491"] and abs(la(490)["at"] - (t_h - 10 * H)) < 2 and abs(la(491)["at"] - t_h) < 5 and la(492) is None, (saved, la(490), la(491)))
hub_ts(110, iso_at(t_h - 30 * H))
check("10 …and a comment from thirty hours ago writes no line", len(EL.read(0)[0]) == 2, EL.read(0)[0])

# ================================================================ 11. a confirm and a last-activity stamp in one publish window keep the confirmed line in the History
from stackshot.web import render as root_render
from stackshot.web.ui import render as ui_render
STORE_DIR = str(T / "store")
gitc = lambda *a: subprocess.run(["git", "-C", STORE_DIR, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
def events11(bd, gid): return [k for _t, k, _h in bd.item_events(next(r for r in bd.rows if r["gid"] == gid))[0]]
def distinct11(i):      # the log follows a file across a rename by similarity, and the fixture items are near copies: give each a body of its own
    d = rd(i); d["description"] = "\n".join(f"- line {n} of item {i}: " + "x%d" % ((n * 7919 + i * 104729) % 100003) * 3 for n in range(12)); d["subject"] = f"[home] history item {i} " + "y%d" % (i * 31337); wr(i, d)
put(500, needs=["home-peer"]); distinct11(500); put(501, needs=["home-peer"]); distinct11(501)
d_ = rd(500); d_["metadata"].pop("phase", None); d_["metadata"].pop("waits_on", None); wr(500, d_)
gitc("init", "-q"); gitc("add", "a/500.json", "a/501.json"); gitc("commit", "-q", "-m", "fixture")
d_ = rd(500); d_["confirmed"] = now0 - 5 * 86400; d_["metadata"]["last_activity"] = {"at": now0 - 6 * 86400, "kind": "comment", "what": "comment on #26"}; wr(500, d_)      # one window: the confirm and the event pass's stamp
d_ = rd(501); d_["confirmed"] = now0 - 5 * 86400; wr(501, d_)                                                                                                         # the confirm alone
for label, mod_ in (("ui/render.py", ui_render), ("render.py", root_render)):
    bd = mod_.Board(STORE_DIR)
    k500, k501 = events11(bd, "a500"), events11(bd, "a501")
    check(f"11 {label}: a confirm and a last-activity stamp saved in one window still show the `confirm` line, as a confirm alone does", "confirm" in k500 and "confirm" in k501, (k500, k501))
gitc("add", "a/500.json", "a/501.json"); gitc("commit", "-q", "-m", "confirmed")
d_ = rd(500); d_["metadata"]["last_activity"] = {"at": now0 - 4 * 86400, "kind": "review", "what": "review on PR 26"}; wr(500, d_)      # a stamp alone, later
for label, mod_ in (("ui/render.py", ui_render), ("render.py", root_render)):
    bd = mod_.Board(STORE_DIR)
    k500 = events11(bd, "a500")
    check(f"11 {label}: …and a stamp alone adds no line (the record shows nothing)", k500.count("confirm") == 1 and len(k500) == len(events11(bd, "a501")) , k500)

# ================================================================ 12. the time of a notifications thread is its vouched items', and a CI result's is its check runs' own
# a: owner-side comment early, a stranger's later in the same batch: the stamp is the owner side's, not the thread's updated_at (which the stranger's comment moved)
NP12 = NP9
def cm12(login, assoc, at, i): return {"user": {"login": login, "type": "User"}, "body": "x", "html_url": f"{W_}/pull/5#issuecomment-{i}", "created_at": iso9(at), "author_association": assoc}
def batch12(comments, reviews=(), rcomments=(), tag=0):
    n12 = {"/user": {"login": "hubaccount"}, NP12: [thread9(iso9(0))], f"{RP}/issues/5": {"state": "open", "comments": 1, "updated_at": iso9(0), "title": "t", "html_url": f"{W_}/pull/5", "body": "", "pull_request": {"merged_at": None}}}
    with GH(n12, [NA9]) as G:
        G.one()      # seeds the thread at iso9(0)
        n12[NP12] = [thread9(iso9(1000), 12 + tag)]
        n12[f"{RP}/issues/5/comments?since={iso9(0)}&per_page=50"] = list(comments)
        n12[f"{RP}/pulls/5/reviews?per_page=100"] = list(reviews)
        n12[f"{RP}/pulls/5/comments?since={iso9(0)}&per_page=50"] = list(rcomments)
        return [e for e in G.one() if e.anchor == NA9]
ev_a = batch12([cm12("kim", "MEMBER", 500, 1), cm12("mallory", "NONE", 700, 2)], tag=1)
check("12 a thread with an owner-side comment (early) and a stranger's (later): the event carries the owner side's own time, not the thread's", len(ev_a) == 1 and ev_a[0].vouched == "comment" and ev_a[0].ts == iso9(500), [(e.ts, e.vouched) for e in ev_a])
ev_b = batch12([cm12("mallory", "NONE", 300, 1), cm12("kim", "COLLABORATOR", 400, 2), cm12("lee", "OWNER", 600, 3), cm12("mallory", "FIRST_TIMER", 800, 4)], tag=2)
check("12 …the newest of the vouched items wins (owner and collaborator comments, strangers on both sides ignored)", len(ev_b) == 1 and ev_b[0].ts == iso9(600), [(e.ts, e.vouched) for e in ev_b])
ev_c = batch12([cm12("mallory", "NONE", 300, 1)], reviews=[{"user": {"login": "lee", "type": "User"}, "state": "APPROVED", "html_url": f"{W_}/pull/5#pullrequestreview-3", "submitted_at": iso9(550), "author_association": "MEMBER"}], tag=3)
check("12 …a member's review counts with its submitted_at, a stranger's comment beside it does not move the time", len(ev_c) == 1 and ev_c[0].vouched == "review" and ev_c[0].ts == iso9(550), [(e.ts, e.vouched) for e in ev_c])
ev_d = batch12([cm12("mallory", "NONE", 300, 1)], tag=4)
check("12 …a batch no vouched item is in falls back to the thread's time (and writes no comment line)", len(ev_d) == 1 and ev_d[0].vouched == "" and ev_d[0].ts == iso9(1000), [(e.ts, e.vouched) for e in ev_d])
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
hub_.bindings[NA9] = {"home-peer"}
hub_.emit(ev_a[0])
rows12, _ = EL.read(0)
check("12 end to end: the log line of that batch is stamped at the owner side's comment", len(rows12) == 1 and rows12[0]["kind"] == "comment" and abs(rows12[0]["ts"] - (tb_ + 500)) < 2, rows12)

# b: a CI result seen after downtime is stamped at its check runs' completed_at, when that is inside the log's window
def ci12(n, runs):
    sha = f"{n:02d}" * 20
    g = {"/user": {"login": "hubaccount"}, **pr9(n)}
    with GH(g, [f"github:acme/widgets#{n}"]) as G:
        G.hub.status.setdefault("anchors", {})
        G.one()      # seeds the passing state
        g[f"{RP}/commits/{sha}/check-runs?per_page=100"] = {"check_runs": runs}
        return [e for e in G.one() if e.etype == "ci_failed"]
def run12(done, conclusion="failure", name="suites"): return {"name": name, "status": "completed", "conclusion": conclusion, **({"completed_at": done} if done else {})}
t12 = time.time()
ci_old = ci12(34, [run12(iso_at(t12 - 3 * H), "success", "lint"), run12(iso_at(t12 - 2 * H))])
check("12 a CI result seen after downtime carries the newest check run's completed_at (two hours ago), not the hub's now", len(ci_old) == 1 and ci_old[0].ts == iso_at(t12 - 2 * H), [e.ts for e in ci_old])
for label, n, done in (("a time a day and more old", 35, iso_at(t12 - 30 * H)), ("a time more than an hour ahead", 36, iso_at(t12 + 3 * H)), ("no completed_at", 37, "")):
    got = ci12(n, [run12(done)])
    check(f"12 …{label} falls back to the hub's own time, as before", len(got) == 1 and abs(EL._epoch(got[0].ts) - time.time()) < 10, [e.ts for e in got])
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
hub_.bindings["github:acme/widgets#34"] = {"home-peer"}
hub_.emit(ci_old[0])
rows12b, _ = EL.read(0)
check("12 end to end: the CI line is stamped at the check run's completion, so a backlog is not now", len(rows12b) == 1 and rows12b[0]["kind"] == "ci_failed" and abs(rows12b[0]["ts"] - (t12 - 2 * H)) < 2, rows12b)

# ================================================================ 13. the item's own words include a step's status tag: a merge whose pull request is named only there ties, and the tick records pr_merged
def tagged(text): return step("home-peer: do the thing", "open") | {"tag": {"text": text, "state": "in progress", "ts": now0}}
put(460, steps=[tagged("PR 260 released; PR 261 in review")])
put(461, next="home-peer: land PR #262 and check it")
put(462, project="projects/beta", steps=[tagged("PR 263 in review")])      # the number alone in a tag, in a project that holds no anchor in the repository: not tied
put(463, steps=[step("home-peer: do the thing", "open"), step("home-peer: an earlier step", "done") | {"tag": {"text": "PR 264 released", "state": "done", "ts": now0}}])      # a finished step keeps its tag: stale, ties nothing
put(464, steps=[tagged("PR 264 released")])      # the same tag on an open step ties
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/9999"}]}))      # an anchor in the repository for no item: a bare number in an item of the project speaks of that repository
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
emit(261, "pr_merged", "alice", 100 * MIN); emit(262, "pr_merged", "alice", 101 * MIN); emit(263, "pr_merged", "alice", 102 * MIN); emit(264, "pr_merged", "alice", 103 * MIN)
saved = ev_pass(now0 + 110 * MIN)
check("13 a merge whose pull request is named only in a step's tag (a460, PR 261) or on a line of the item's next (a461, PR 262) is tied: the tick records pr_merged at the merge, with the pull request in the words",
      sorted(saved) == ["a460", "a461", "a464"] and lk(460) == "pr_merged" and la(460) == {"at": now0 + 100 * MIN, "what": "PR 261 merged"} and lk(461) == "pr_merged" and la(461) == {"at": now0 + 101 * MIN, "what": "PR 262 merged"}, (saved, la(460), la(461)))
check("13 …and a bare number in a tag of an item whose project holds no anchor in that repository (a462, PR 263) is not tied: nothing is recorded", la(462) is None, la(462))
check("13 …nor is a tag on a done step (a463, PR 264): only the tag of an open step counts, as the same tag on an open step (a464) ties", la(463) is None and lk(464) == "pr_merged" and la(464)["what"] == "PR 264 merged", (la(463), la(464)))
# ================================================================ 14. an anchor added after the merge: the first read of a pull request merged within a day writes the merge line, and the item the anchor is scoped to is credited
put(600); put(601); put(603); put(604)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/90", "items": ["a600"]}, {"url": f"{W_}/pull/91"}, {"url": f"{W_}/pull/92", "items": ["a600"]}, {"url": f"{W_}/pull/93", "items": ["a603"]},
                                                                      {"url": f"{W_}/pull/94"}]}))
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True); ML.path().unlink(missing_ok=True)
t13 = time.time()
def late_pr(n, ago, **kw):
    at = ISO_NOW(ago)
    GHD[f"{RP}/pulls/{n}"] = GHD[f"{RP}/pulls/26"]
    GHD[f"{RP}/issues/{n}"] = pr_issue(**{"state": "closed", "html_url": f"{W_}/pull/{n}", "closed_at": at, "updated_at": at, "closed_by": {"login": "alice"}, "pull_request": {"merged_at": at}, "body": "", **kw})
late_pr(90, 2 * H); late_pr(91, 2 * H); late_pr(92, 30 * H); late_pr(93, 20 * H); late_pr(94, 2 * H, body="Closes " + BID(604))      # 94: no anchor scoped to an item, the body names one
told13 = []
hub13 = HUB.Hub(); hub13.write_status = lambda: None; hub13.emit = told13.append
hub13.bindings = {f"github:acme/widgets#{n}": {"home-peer"} for n in (90, 91, 92, 93, 94)}
_sub, _thr, _tim = ghr.subprocess, ghr.threading, ghr.time
ghr.subprocess = types.SimpleNamespace(run=_fake_gh, TimeoutExpired=subprocess.TimeoutExpired)
ghr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
ghr.time = types.SimpleNamespace(time=time.time, sleep=_no_sleep)
del caught[:]
try:
    ghr.run(hub13); one_pass(); one_pass()
finally:
    ghr.subprocess, ghr.threading, ghr.time = _sub, _thr, _tim
rows13, _ = EL.read(0); mrows13, _ = ML.read(0)
check("14 a pull request that merged 2 hours ago, first read through an anchor added later, writes one merge line in each log; one that merged 30 hours ago writes none, and a second pass adds nothing",
      sorted(r["n"] for r in mrows13) == [90, 91, 93, 94] and sorted((r["n"], r["kind"]) for r in rows13) == [(90, "merged"), (91, "merged"), (93, "merged"), (94, "merged")] and told13 == [], (mrows13, rows13, told13))
check("14 …both logs carry the time it merged, not the hub's now (the merge pass skips a merge older than its floor)",
      all(abs(r["ts"] - (t13 - ago)) < 5 for lg in (mrows13, rows13) for r in lg for n, ago in ((90, 2 * H), (91, 2 * H), (93, 20 * H), (94, 2 * H)) if r["n"] == n), (mrows13, rows13))
check("14 …the body's ids are not read on this path (a body can be edited long after the merge): the lines carry none", all(r["refs"] == [] for r in mrows13 + rows13), (mrows13, rows13))
saved = ev_pass(time.time() + 5)
check("14 …the pass credits the item the anchor is scoped to (pr_merged at the time it merged), even a merge of 20 hours ago; the project-wide anchor's pull request ties no item, and a body naming an item ties none",
      sorted(saved) == ["a600", "a603"] and lk(600) == "pr_merged" and la(600)["what"] == "PR 90 merged" and abs(la(600)["at"] - (t13 - 2 * H)) < 5 and abs(la(603)["at"] - (t13 - 20 * H)) < 5
      and la(601) is None and la(604) is None, (saved, la(600), la(603), la(601), la(604)))
(T / "state/merge-progress.json").unlink(missing_ok=True); gh_["issues_letter"] = "a"; CLK.t = time.time() + 5
try: done13 = server._merge_progress_tick(time.time() + 5)
finally: CLK.t = None
check("14 …and the merge pass records the 2-hour merge on its item (progress clock) but not the 20-hour one, which is past its floor (credited as activity, no progress)",
      done13 == ["a600"] and "acme/widgets#90" in (mt(600).get("merged_seen") or []) and not mt(603).get("merged_seen"), (done13, mt(600).get("merged_seen"), mt(603).get("merged_seen")))

# ================================================================ 14. a green head after a green head is activity on the item the pull request is anchored to (it was dropped: only a pass after a failure was reported)
put(484)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/40", "items": ["a484"]}]}))
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
g13 = {"/user": {"login": "hubaccount"}, **pr9(40)}
with GH(g13, ["github:acme/widgets#40"]) as G:
    G.hub.status.setdefault("anchors", {})
    G.one()      # seeds the first green head: silent
    g13.update(pr9(40, sha="41" * 20))      # a new head, green as the one before
    ci13 = [e for e in G.one() if e.etype.startswith("ci_")]
    ci13b = [e for e in G.one() if e.etype.startswith("ci_")]
check("14 a new green head after a green one is one ci_passed event, vouched for; the pass after it adds none",
      [(e.etype, e.who, e.vouched, e.text) for e in ci13] == [("ci_passed", "CI", "ci_passed", "passing on 4141414 (1 checks)")] and ci13b == [], ([(e.etype, e.text) for e in ci13], ci13b))
hub_.bindings["github:acme/widgets#40"] = {"home-peer"}
for e in ci13: hub_.emit(e)
rows13, _ = EL.read(0)
saved = ev_pass_now()
check("14 …it writes a ci_passed line for the pull request and stamps the item anchored to it: ci_result, 'CI passing on PR 40'",
      [(r["kind"], r["n"]) for r in rows13] == [("ci_passed", 40)] and saved == ["a484"] and la(484)["what"] == "CI passing on PR 40" and lk(484) == "ci_result", (rows13, saved, la(484)))

# a fork's pull request: the same green after green is not the repository's own side, so it is not vouched for and writes no line
put(485)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"{W_}/pull/42", "items": ["a485"]}]}))
EL.path().unlink(missing_ok=True); EL.offset_path().unlink(missing_ok=True)
g13f = {"/user": {"login": "hubaccount"}, **pr9(42, head="mallory/widgets")}
with GH(g13f, ["github:acme/widgets#42"]) as G:
    G.hub.status.setdefault("anchors", {})
    G.one()
    g13f.update(pr9(42, head="mallory/widgets", sha="43" * 20))
    ci13f = [e for e in G.one() if e.etype.startswith("ci_")]
check("14 a fork's pull request: a green head after a green one is the same record_only ci_passed event, not vouched for", [(e.etype, e.vouched, e.record_only) for e in ci13f] == [("ci_passed", "", True)], [(e.etype, e.vouched, e.record_only) for e in ci13f])
hub_.bindings["github:acme/widgets#42"] = {"home-peer"}
for e in ci13f: hub_.emit(e)
rows13f, _ = EL.read(0)
saved = ev_pass_now()
check("14 …it writes no line to the event log and stamps nothing (a fork's CI is not the repository's own side)", rows13f == [] and saved == [] and la(485) is None, (rows13f, saved, la(485)))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
