"""Scenario test for reading a pane stopped on an error (items once reached the owner with a
bare Approve after "running hours" were counted against panes stopped on "Credit balance is too low") — fixture data,
no live store, no network.

Covers: the tail reader: a session whose transcript on the box ends in an API error (Claude Code's assistant entry with isApiErrorMessage; a
usage limit, a workspace limit, the credit balance) reads as stopped, with the error as the reason; a prompt after the error means the pane is trying
again, a tool result or injected context is part of a turn, the CLI's other records are passed over; a pane with no transcript on the box
(another machine) says nothing; a pane on another machine is read through its puller (puller 7 reports `stopped` per session, which the
server's client state stores, clears and shows in the view); the fleet's builder ([fleet] operator_session; its project's keeper when that
session is retired).

    tests/run-suite idle_stopped      → exit 0 / 1"""
import json, os, re, sys, pathlib, tempfile, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="idlestoppedtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r'(?m)^operator_session = .*$', 'operator_session = "home-master"', toml); assert n == 1                          # the fleet operator: a background agent of alpha
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-owner", "home-stew", "home-stuck", "home-far", "home-master", "home-crew"), 1)}
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
def fleet(gone=()):
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", **({"gone": "2026-01-01T00:00:00Z"} if n in gone else {})} for n, u in U.items()}))
fleet()
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-master": "runs the fleet"}, "back_agents": {"home-master": "runs the fleet"}}}}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\n---\n\n# Alpha\n")
TR = T / "transcripts" / "-home-x"
def entry(kind, text, err=False):
    if kind == "user":
        return json.dumps({"type": "user", "uuid": "u1", "timestamp": "2026-10-14T00:00:00.000Z", "message": {"role": "user", "content": text}})
    e = {"type": "assistant", "uuid": "a1", "timestamp": "2026-10-14T00:00:01.000Z", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    if err: e["isApiErrorMessage"] = True
    return json.dumps(e)
JUNK = [json.dumps({"type": "system", "subtype": "stop_hook_summary", "level": "info"}), json.dumps({"type": "attachment", "attachment": {"type": "x"}}),
        json.dumps({"type": "user", "isMeta": True, "message": {"role": "user", "content": "<local-command-caveat>"}}),
        json.dumps({"type": "user", "toolUseResult": {"ok": 1}, "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}),
        json.dumps({"type": "mode", "mode": "default"}), json.dumps({"type": "pr-link", "prNumber": 1}), "not json at all"]
def transcript(name, *lines):
    (TR / f"{U[name]}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
def stopped(name, why="Credit balance is too low"):      # the last turn ended in the error; the CLI's later records are not a turn
    transcript(name, entry("user", "hi"), entry("assistant", "working on it"), entry("user", "go on"), entry("assistant", why, err=True), *JUNK)
def healthy(name):                                       # an earlier error, then a turn that ended well
    transcript(name, entry("user", "hi"), entry("assistant", "Credit balance is too low", err=True), entry("user", "again"), entry("assistant", "done, moving on"), *JUNK)
stopped("home-stuck")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())

from stackshot.web import server
from stackshot.web import publish as _web_publish
from stackshot.service import fleet_events as fleetev
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
# ---- 0. the tail reader on its own
check("the transcript check: the last turn ended in an error, whatever the CLI wrote after it", server._pane_stuck(U["home-stuck"]) == "Credit balance is too low", server._pane_stuck(U["home-stuck"]))
check("…a pane name resolves to its transcript; nothing known for a session with no transcript on this box, or a cloud id",
      server._pane_stuck("home-stuck") == "Credit balance is too low" and server._pane_stuck(U["home-far"]) == "" and server._pane_stuck("cse_0123456789abcdef") == "")
transcript("home-far", entry("user", "hi"), entry("assistant", "You've hit your weekly limit · resets Jan 8, 5am (UTC)", err=True), entry("user", "try again"))
check("…a prompt after the error: the pane is trying again, not stopped", server._pane_stuck(U["home-far"]) == "", server._pane_stuck(U["home-far"]))
transcript("home-far", entry("user", "hi"), entry("assistant", "API Error: 400 You have reached your specified workspace API usage limits. You will regain access on 2030-01-01 at 00:00 UTC.", err=True))
check("…the error text is the reason, clipped to one line", server._pane_stuck(U["home-far"]).startswith("API Error: 400 You have reached your specified workspace API usage limits"), server._pane_stuck(U["home-far"]))
transcript("home-far", *JUNK)
check("…a tail with no turn in it: nothing known", server._pane_stuck(U["home-far"]) == "")
(TR / f"{U['home-far']}.jsonl").unlink()
got = []
for op in ("home-stew", "home-crew", ""):
    server._cfg.CFG.setdefault("fleet", {})["operator_session"] = op; got.append(fleetev.fleet_builder())
check("the notice of a stopped pane goes to the fleet's builder, [fleet] operator_session; with none set, nobody; there is no [idle] stuck_to",
      got == ["home-stew", "home-crew", ""] and not hasattr(server, "_stuck_to") and "stuck_to" not in (server._cfg.CFG.get("idle") or {}), got)
server._cfg.CFG["fleet"]["operator_session"] = "home-stew"

# ---- 0b. a pane on another machine: no transcript here, so its puller (version 7) reads it there and reports `stopped` on the session's record
check("a pane with no transcript on this box and a running record that carries `stopped` (its puller's report) reads as stopped, with that reason; a gone record, or none, does not",
      server._pane_stuck(U["home-far"], None, {U["home-far"]: {"name": "home-far", "stopped": "Credit balance is too low"}}) == "Credit balance is too low"
      and server._pane_stuck(U["home-far"], None, {U["home-far"]: {"name": "home-far", "stopped": "x", "gone": "2026-01-01T00:00:00Z"}}) == ""
      and server._pane_stuck(U["home-far"], None, {U["home-far"]: {"name": "home-far"}}) == "" and server._pane_stuck(U["home-far"], None, {}) == "")
from stackshot.fleet import puller
puller._transcript_roots = lambda: [str(T / "transcripts")]
rep = puller.report([{"sessionId": U["home-stuck"], "name": "home-stuck"}, {"sessionId": U["home-owner"], "name": "home-owner"}])
check("the puller reads the transcript on its own machine (said.transcript_error, the reader the server uses) and reports `stopped` per session; \"\" for one with no transcript",
      [r["stopped"] for r in rep] == ["Credit balance is too low", ""] and int(puller.VERSION) >= 7, rep)
from stackshot.fleet import clients as _cl
cst = {"sessions": {}, "machines": {}}
_cl._upsert(cst, "a", {"uuid": U["home-far"], "name": "home-far", "stopped": "Credit balance is too low"}, "puller", now0)
kept = cst["sessions"][U["home-far"]].get("stopped")
_cl._upsert(cst, "a", {"uuid": U["home-far"], "name": "home-far"}, "hook", now0 + 1)                   # a hook's record has no key: left as it was
kept_hook = cst["sessions"][U["home-far"]].get("stopped")
_cl._upsert(cst, "a", {"uuid": U["home-far"], "name": "home-far", "stopped": ""}, "puller", now0 + 2)  # the puller says it runs well again: cleared
check("the server's client state stores `stopped`, leaves it alone for a hook's record and clears it when the puller reports it empty, and the view carries it",
      kept == "Credit balance is too low" and kept_hook == "Credit balance is too low" and "stopped" not in cst["sessions"][U["home-far"]]
      and "stopped" in _cl._view({"machines": {"home-x": {"letter": "a", "puller": "2026-10-21T00:00:00Z", "seen": "2026-10-21T00:00:00Z"}},
                                  "sessions": {U["home-far"]: {"name": "home-far", "machine": "a", "stopped": "Credit balance is too low"}}}, now0)["a"][1][U["home-far"]], (kept, kept_hook, cst))

print(("ok" if not fails else "FAILED") + f": stopped pane scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
