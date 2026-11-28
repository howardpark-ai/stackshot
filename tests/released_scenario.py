"""Scenario test for a live pull request settling the items built for it — fixture data, no live store, no network.

Covers: release.sh's call once main's full run passed on a released merge and it recorded it as last-good (the client write `released`, client.py
released). Which steps count: only a release step, one that says it releases the PR ("release PR #N", "release #N", "release <its URL>"), and only on
an item anchored to the PR or naming its URL; "release PR #N" on an unanchored item without the URL, even in the release's own project, is left as
it was; steps that only mention the PR (investigate, review, verify, "the salamander PR #N", another repository's PR) are never ticked and never close
the item. An item whose only open step is that release is completed, outcome done, by the server, with no session turn; an item with a step after it
gets the release step ticked done and its mover one real notice, delivered through the front-agent gate by the real push path (a fake push.py);
a release step plus a verify step ticks one and keeps the item open; a step that carries its follow-up on the same line stays open and its mover is
told. Held items, items whose needs name a decision or a session other than the mover, and completed ones are left alone, with why. Live means
passed: the API refuses, writing nothing, a PR that is not merged, a missing or unknown merge sha, a merge not yet in last-good (main's run still
going) and a merge rolled back out of HEAD; the one-off sweep (client write `sweep-released`) reads the merges in last-good and HEAD, so a merge after
last-good or one rolled back closes nothing. A rerun of released or of the sweep never sends a mover a second notice for the same PR (the item is
stamped). The same over HTTP with the machine's token; the client verbs' usage and lines. A [released.repos] repository's PR is live by its checkout's HEAD, and a checkout on another machine is read there over ssh (a stand-in ssh):
a copy on the server's own machine never counts for it, a deploy and a rollback there show at once, and a machine that gives no answer settles nothing.

    tests/run-suite released        → exit 0 / 1"""
import json, os, re, sys, pathlib, subprocess, time, logging, io, contextlib, shlex, socket
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance, _fake_ssh
tmp = _scratch.mkdtemp(prefix="releasedtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/releases", "brain/projects"): (T / d).mkdir(parents=True)
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-builder", "home-other", "home-third"), 1)}
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({U[n]: {"name": n, "machine": "a", "seen": now} for n in U}))
AGENTS = {"projects/alpha": {"home-builder": "the front"}, "projects/beta": {}}     # home-builder is alpha's front agent: its notices pass the front gate
(T / "store/projects.json").write_text(json.dumps({"pages": {p: {"title": p[9:].title(), "name": p[9:].title(), "org": "home", "tags": [], "type": "project",
                                                                 "session": "home-builder", "status": "active", "board": [], "board_open": 0,
                                                                 "agents": AGENTS[p], "back_agents": {}}
                                                             for p in AGENTS}}))
for p in AGENTS:
    k = p[9:]
    (T / f"brain/projects/{k}.md").write_text(f"---\ntitle: {k.title()}\n" + ("agents:\n" + "".join(f"  {a}: {r}\n" for a, r in AGENTS[p].items()) if AGENTS[p] else "")
                                               + f"---\n\n# {k.title()}\n")
REPO = "example-owner/stackshot"
def url(n): return f"https://github.com/{REPO}/pull/{n}"
PR = url(41)


def item(i, nxt, project="projects/alpha", status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing. It lives here. Done when done.",
                                                       "status": status, "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                       "metadata": {"owner": U["home-builder"], "mover": U["home-builder"], "project": project, "next": nxt, **meta}}))


MENTIONS = "\n".join(("home-builder: investigate PR #41", "home-builder: review PR #41", "home-builder: verify PR #41 is live",
                      "home-builder: check the salamander PR #41", "home-builder: release https://github.com/other-owner/other/pull/41"))
ALL = range(1, 28)


def fixtures():
    for f in (T / "store/a").glob("*.json"): f.unlink()
    item(1, "home-builder: release PR #41")                                                       # its only open step is the release: closes
    item(2, "home-builder: release PR #41\nhome-builder: then check the pages")                  # a step after it: ticked, the mover told
    item(3, "home-builder: release PR #41", hold=True, wake="2099-01-02")                        # on hold
    item(4, "home-builder: release PR #41", needs=["decision"], ask="Ship it?")                   # waits on the owner's decision
    item(5, "home-builder: release PR #42")                                                       # another PR
    item(6, "home-builder: release PR #41, then run an audit")                                   # its follow-up on the same line
    item(7, "home-builder: release PR #41", status="completed", outcome="done", reason="earlier")  # closed already
    item(8, "home-builder: release PR #41")                                                       # the release's own project, not anchored, no URL: could be another repo's #41
    item(9, f"home-other: release {PR}", project="projects/beta")                                # the URL after "release": counts anywhere
    item(10, "home-builder: release PR #43")                                                      # for the sweep: #43 is in last-good
    item(11, "home-builder: release PR #45")                                                      # #45 is merged after last-good: main's run still going
    item(12, MENTIONS)                                                                            # mentions only: never ticked, never closed
    item(13, "home-builder: release PR #41\nhome-builder: verify PR #41 is live")                # a release step and a verify step: one ticked, the item stays open
    item(14, "home-builder: release PR #41", needs=["home-third"])                               # its needs name a session other than its mover
    item(15, "home-builder: release #41")                                                         # "release #N"
    item(16, "home-builder: release PR #41 and verify the pages")                                # a follow-up after "and": not a pure release
    item(17, "home-builder: release PR #41, restart x")                                          # …after a comma
    item(18, "home-builder: release PR #41 — check prod")                                    # …after a dash
    item(19, "home-builder: release PR #41 (needs an ok)")                                       # …in a parenthetical that names something to do
    item(20, "home-builder: release PR #41 (in its turn)")                                       # a parenthetical naming nothing to do: still a pure release
    item(21, "home-builder: release PR #41 (after #40)")                                         # …also
    item(22, "home-builder: do not release PR #41 yet")                                          # negated: never a release step
    item(23, "home-builder: pre-release #41")
    item(24, "home-builder: don't release #41")
    item(25, "home-builder: release PR #41\nhome-builder: release PR #45")                       # the only other open step is a pure release of another PR: ticked, nobody told
    item(26, "home-builder: release PR #41\nhome-builder: release PR #45, then restart x")       # the other step is a release with a follow-up: ticked, the mover told
    item(27, "home-builder: release PR #41.")                                                    # a closing full stop is no follow-up
    (T / "store/next-id").write_text("40")
    (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [
        {"url": PR, "items": ["a1", "a2", "a3", "a4", "a5", "a6", "a7", "a12", "a13", "a14", "a15", *[f"a{k}" for k in range(16, 28)]], "added": 1, "by": "t"},
        {"url": url(43), "items": ["a10"], "added": 1, "by": "t"}, {"url": url(45), "items": ["a11"], "added": 1, "by": "t"}]}))


# ---- the checkout: merges #41 and #43 are in last-good; #45 is merged after it (main's full run on it still going)
genv = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": tmp}
def g(*a): return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=T / "repo", env=genv, capture_output=True, text=True, check=True).stdout.strip()
(T / "repo").mkdir(); g("init", "-q", "-b", "main"); (T / "repo/f").write_text("0"); g("add", "f"); g("commit", "-qm", "base")
M = {}
for n in (41, 43, 45):
    g("checkout", "-qb", f"topic{n}"); (T / "repo/f").write_text(str(n)); g("commit", "-qam", f"change {n}")
    g("checkout", "-q", "main"); g("merge", "-q", "--no-ff", "-m", f"Merge pull request #{n} from example-owner/topic{n}", f"topic{n}"); M[n] = g("rev-parse", "HEAD")
g("checkout", "-qb", "topic44"); (T / "repo/f").write_text("44"); g("commit", "-qam", "change 44"); NOT_MERGED = g("rev-parse", "HEAD"); g("checkout", "-q", "main")
LAST_GOOD = T / "state/releases/last-good"
def good(sha): LAST_GOOD.write_text(sha + "\n")
good(M[43])

fixtures()
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def raw(i): return (T / f"store/a/{i}.json").read_text()
def snap(): return {i: raw(i) for i in ALL}
def same(s): return [i for i in s if raw(i) != s[i]]

from stackshot.web import server
from stackshot.core import config as _cfg
from stackshot.model import steps as _steps
from stackshot.core import instance as _core_instance
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.service import proofs as proofs_svc, released as released_svc, released_live as rlive_svc, writes
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import text as _wt_text
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
released_svc._OWN_REPO[:] = [REPO]                       # this checkout's origin, as the fixture's repository
rlive_svc.HERE = T / "repo"
check("the last-good path is release.sh's ($LOGDIR/last-good, LOGDIR = config.py state releases)", _cfg.state("releases", "last-good") == LAST_GOOD)
# the delivery path is the real one: tell_woken → the front gate → push.py (a fake that logs what it was asked to send)
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []; GATED = []
_real_tell, _real_gate = telling.tell_woken, telling.front_gate
def _gate(gid, owner, note, tag, kind):
    r = _real_gate(gid, owner, note, tag, kind); GATED.append((gid, tag, r)); return r
telling.front_gate = _gate
def _tell(gid, owner, note, tag="wake", result=None):
    th = _real_tell(gid, owner, note, tag, result)
    if th: THREADS.append(th)
    return th
telling.tell_woken = _tell
def drain():
    while THREADS: THREADS.pop(0).join(30)
def pushes(): drain(); return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
def pushes_for(gid): return [p for p in pushes() if p[1].startswith(f"[stackshot] {gid}: ")]
check("home-builder is a front agent, so the notices below go through the front gate", telling.front_sender(U["home-builder"]))

# ---- 1. release.sh's call: main's full run passed on the merge of PR #41 and it is in last-good
before = snap()
r = released_svc.released(PR, sha=M[41])
rows = {x["item"]: x for x in r["items"]}
it1 = rd(1)
check("only open step is the release: completed, outcome done, the reason naming the PR, its merge and last-good",
      it1["status"] == "completed" and it1["metadata"].get("outcome") == "done" and it1["metadata"]["reason"].startswith(f"PR #41 is live (merged at {M[41][:7]} on ")
      and f"in the last-good commit {M[43][:7]}" in it1["metadata"]["reason"] and "main's tests passed" in it1["metadata"]["reason"] and rows.get("a1", {}).get("action") == "closed", (it1, rows.get("a1")))
check("…its release step is marked done by the server's own label, next is gone",
      [(s["status"], s["by"]) for s in it1["metadata"].get("steps", [])] == [("done", _core_instance.NAME)] and "next" not in it1["metadata"], it1["metadata"])
check("…no session turn: nobody is told of the close", not pushes_for("a1"), pushes())
check("\"release #41\" counts too: closed", rd(15)["status"] == "completed" and rows.get("a15", {}).get("action") == "closed", rows.get("a15"))
it2 = rd(2)
check("a step after it: the release step is ticked done by the server, the step after it stays open in next",
      it2["status"] == "open" and it2["metadata"].get("next") == "home-builder: then check the pages"
      and [(s["text"], s["status"], s.get("by")) for s in it2["metadata"].get("steps", [])] == [("home-builder: release PR #41", "done", _core_instance.NAME), ("home-builder: then check the pages", "open", None)]
      and rows.get("a2", {}).get("action") == "ticked", (it2["metadata"], rows.get("a2")))
n2 = pushes_for("a2")
check("…and its mover gets one real notice, pushed by push.py through the front gate (exempt: it asks the mover to act)",
      len(n2) == 1 and n2[0][0] == U["home-builder"] and "PR #41 is live; its step is ticked; the item's other open steps remain" in n2[0][1] and "do the step after it" not in n2[0][1]
      and ("a2", "release", False) in GATED, (pushes(), GATED))
check("…and the item is stamped with the PR it was told about", it2["metadata"].get("released_told") == [f"{REPO}#41"], it2["metadata"])
it13 = rd(13)
check("a release step and a verify step: the release is ticked, the verify step stays open, the item stays open, its mover is told once",
      it13["status"] == "open" and it13["metadata"].get("next") == "home-builder: verify PR #41 is live" and rows.get("a13", {}).get("action") == "ticked"
      and len(pushes_for("a13")) == 1, (it13["metadata"], rows.get("a13"), pushes()))
it6 = rd(6)
check("the follow-up on the same line: the step stays open (it is not only the release) and the mover is told once",
      it6["status"] == "open" and it6["metadata"].get("next") == "home-builder: release PR #41, then run an audit" and rows.get("a6", {}).get("action") == "told"
      and len(pushes_for("a6")) == 1 and it6["metadata"].get("released_told") == [f"{REPO}#41"], (it6["metadata"], rows.get("a6"), pushes()))
for i, why in ((16, "\"and verify the pages\""), (17, "\", restart x\""), (18, "a dash and \"check prod\""), (19, "\"(needs an ok)\""), (21, "\"(after #40)\", a condition")):
    itx = rd(i)
    check(f"a follow-up after the release phrase ({why}): the step stays open and un-ticked, the item stays open, the mover is told once",
          itx["status"] == "open" and [s["status"] for s in itx["metadata"].get("steps", [])] in ([], ["open"]) and itx["metadata"].get("next") == json.loads(before[i])["metadata"]["next"]
          and rows.get(f"a{i}", {}).get("action") == "told" and len(pushes_for(f"a{i}")) == 1 and "its step is not ticked (it names a follow-up)" in pushes_for(f"a{i}")[0][1]
          and itx["metadata"].get("released_told") == [f"{REPO}#41"], (itx["metadata"], rows.get(f"a{i}"), pushes_for(f"a{i}")))
for i, why in ((20, "(in its turn)"), (27, "a closing full stop")):
    check(f"a release step with only {why} after it is a pure release: the item closes, nobody told",
          rd(i)["status"] == "completed" and rows.get(f"a{i}", {}).get("action") == "closed" and not pushes_for(f"a{i}"), (rd(i)["status"], rows.get(f"a{i}")))
for i, why in ((22, "do not release PR #41 yet"), (23, "pre-release #41"), (24, "don't release #41")):
    check(f"\"{why}\" is never a release step: untouched byte for byte, not listed, nobody told", raw(i) == before[i] and f"a{i}" not in rows and not pushes_for(f"a{i}"), (rd(i), rows.get(f"a{i}")))
it25 = rd(25)
check("every other open step is a pure release of another PR: this release step is ticked, the other stays open, nobody is told, nothing is stamped",
      it25["status"] == "open" and rows.get("a25", {}).get("action") == "ticked" and rows["a25"].get("quiet") is True and rows["a25"]["told"] == ""
      and [(s["text"], s["status"]) for s in it25["metadata"]["steps"]] == [("home-builder: release PR #41", "done"), ("home-builder: release PR #45", "open")]
      and not pushes_for("a25") and "released_told" not in it25["metadata"], (it25["metadata"], rows.get("a25"), pushes_for("a25")))
it26 = rd(26)
check("the other open step is a release of another PR with a follow-up: ticked, and the mover is told the item's other open steps remain",
      it26["status"] == "open" and rows.get("a26", {}).get("action") == "ticked" and rows["a26"].get("quiet") is False and len(pushes_for("a26")) == 1
      and "PR #41 is live; its step is ticked; the item's other open steps remain" in pushes_for("a26")[0][1], (it26["metadata"], rows.get("a26"), pushes_for("a26")))
check("mention-only steps (investigate, review, verify, the salamander PR, another repo's PR): never ticked, item untouched byte for byte, not listed",
      raw(12) == before[12] and "a12" not in rows, (rd(12), rows.get("a12")))
check("\"release PR #41\" on an unanchored item without the URL, in the release's own project: untouched (it could be another repository's #41)",
      raw(8) == before[8] and "a8" not in rows, rows.get("a8"))
check("held, decision, other-session needs, another PR, completed: untouched, byte for byte", not same({i: before[i] for i in (3, 4, 5, 7, 14)}), same(before))
check("…held, decision and other-session needs are reported as left alone, each with why; the others are not listed",
      rows.get("a3", {}).get("action") == "left" and rows["a3"]["why"] == "parked"
      and rows.get("a4", {}).get("action") == "left" and "decision" in rows["a4"]["why"]
      and rows.get("a14", {}).get("action") == "left" and "its needs name home-third, not its mover" == rows["a14"]["why"]
      and not {"a5", "a7"} & set(rows), rows)
check("the PR's URL after \"release\" counts in any project: closed", rd(9)["status"] == "completed" and rows.get("a9", {}).get("action") == "closed", rows.get("a9"))
check("#43's and #45's items are not touched by #41's release", raw(10) == before[10] and raw(11) == before[11])
check("no notice for the left-alone or untouched items", not any(pushes_for(gx) for gx in ("a3", "a4", "a5", "a7", "a8", "a12", "a14", "a22", "a23", "a24")), pushes())

# ---- 2. idempotent: a rerun of released, then the sweep, sends nobody a second notice for PR #41
p0 = len(pushes())
r = released_svc.released(PR, sha=M[41])
check("released again: nothing closed or ticked, the told item is left with why, no second notice",
      not [x for x in r["items"] if x["action"] in ("closed", "ticked", "told")] and len(pushes()) == p0
      and {x["item"]: x["why"] for x in r["items"]}.get("a6") == "its mover was told already that PR #41 is live", (r, pushes()[p0:]))
d = released_svc.sweep_released()
check("the sweep after it: closes #43's item, sends no second notice for #41", rd(10)["status"] == "completed"
      and not [p for p in pushes()[p0:] if "PR #41" in p[1]], (d, pushes()[p0:]))
d = released_svc.sweep_released()
check("the sweep again: nothing more, nobody told", not [x for x in d["items"] if x["action"] in ("closed", "ticked", "told")] and not pushes()[p0:], (d, pushes()[p0:]))

# ---- 3. live means passed: the API refuses before writing anything
fixtures(); p0 = len(pushes()); s0 = snap()
for name, pr, sha, want in (("a PR that is not merged", url(44), NOT_MERGED, "PR #44 is not merged"),
                            ("a PR that is not merged, given another PR's merge", url(44), M[43], "PR #44 is not merged"),
                            ("the merge sha missing", PR, "", "has no merge commit given"),
                            ("a merge sha this checkout does not know", PR, "deadbeef00", "not a commit this checkout knows"),
                            ("a merge not yet in last-good (main's run going)", url(45), M[45], f"is not in the last-good commit {M[43][:7]} yet"),
                            ("a URL of another repository", "https://github.com/someone-else/other/pull/41", M[41], "pull request URL of this repository"),
                            ("no URL", "", M[41], "pull request URL of this repository")):
    try: released_svc.released(pr, sha=sha); check(f"refused: {name}", False)
    except ToolError as e: check(f"refused: {name}", want in str(e) and str(e).startswith("Refused:"), str(e))
check("…and none of them wrote or told anything", not same(s0) and len(pushes()) == p0, (same(s0), pushes()[p0:]))
LAST_GOOD.unlink()
try: released_svc.released(PR, sha=M[41]); check("refused: no last-good recorded", False)
except ToolError as e: check("refused: no last-good recorded", "no last-good commit is recorded" in str(e), str(e))
try: released_svc.sweep_released(); check("the sweep refused: no last-good recorded", False)
except ToolError as e: check("the sweep refused: no last-good recorded", "no last-good commit is recorded" in str(e), str(e))
good(M[43])
check("…nothing written", not same(s0))

# ---- 4. the sweep before last-good holds the merge: #45's item stays open; dry run first
d = released_svc.sweep_released(dry=True)
acts = {(x["item"], x["pr"]): x["action"] for x in d["items"]}
check("dry run: lists what it would close, tick, tell and leave, for the merges in last-good only",
      acts == {("a1", 41): "closed", ("a2", 41): "ticked", ("a3", 41): "left", ("a4", 41): "left", ("a6", 41): "told", ("a9", 41): "closed",
               ("a10", 43): "closed", ("a13", 41): "ticked", ("a14", 41): "left", ("a15", 41): "closed",
               ("a16", 41): "told", ("a17", 41): "told", ("a18", 41): "told", ("a19", 41): "told", ("a20", 41): "closed", ("a21", 41): "told",
               ("a25", 41): "ticked", ("a26", 41): "ticked", ("a27", 41): "closed"} and d["good"] == M[43] and d["head"] == M[45], (acts, d.get("good"), d.get("head")))
check("dry run: writes nothing and tells nobody", not same(s0) and len(pushes()) == p0, (same(s0), pushes()[p0:]))
d = released_svc.sweep_released()
check("the real sweep: the merge after last-good (#45, main's run going) closes nothing", raw(11) == s0[11] and not [x for x in d["items"] if x.get("pr") == 45], d)
check("…the merges in last-good settle as release.sh's call would", rd(1)["status"] == "completed" and rd(10)["status"] == "completed" and rd(13)["status"] == "open"
      and raw(12) == s0[12] and raw(8) == s0[8], d)
check("…the closes tell nobody; the ticks and the same-line follow-up tell their movers, once each", sorted(p[1].split(":")[0].split()[-1] for p in pushes()[p0:]) == ["a13", "a16", "a17", "a18", "a19", "a2", "a21", "a26", "a6"], pushes()[p0:])

# ---- 5. a rollback closes nothing: last-good names #45's merge, but the checkout went back before it
fixtures(); p0 = len(pushes()); s0 = snap()
good(M[45]); g("reset", "-q", "--hard", M[43])
try: released_svc.released(url(45), sha=M[45]); check("refused: a merge rolled back out of HEAD", False)
except ToolError as e: check("refused: a merge rolled back out of HEAD", f"is not in the live checkout {M[43][:7]} (rolled back)" in str(e), str(e))
d = released_svc.sweep_released()
check("the sweep after a rollback: #45's item stays as it was", raw(11) == s0[11] and not [x for x in d["items"] if x.get("pr") == 45], d)
g("reset", "-q", "--hard", M[45]); good(M[43])

# ---- 6. over HTTP, with the machine's token, and the client verbs
fixtures(); s0 = snap()
from stackshot.fleet import client
tok = open(client.mint("testbox")).read().strip()
from starlette.testclient import TestClient
with TestClient(server.mcp.http_app()) as c:
    h = {"Authorization": "Bearer " + tok}
    res = c.post("/client/released", json={"pr": url(44), "sha": NOT_MERGED}, headers=h)
    check("POST /client/released for an unmerged PR: a 400 that says so, and nothing written", res.status_code == 400 and "PR #44 is not merged" in res.json().get("error", "") and not same(s0), res.text)
    res = c.post("/client/released", json={"pr": url(45), "sha": M[45]}, headers=h)
    check("POST /client/released for a merge not in last-good: a 400, nothing written", res.status_code == 400 and "last-good" in res.json().get("error", "") and not same(s0), res.text)
    res = c.post("/client/released", json={"pr": PR}, headers=h)
    check("POST /client/released with no sha: a 400, nothing written", res.status_code == 400 and "no merge commit given" in res.json().get("error", "") and not same(s0), res.text)
    res = c.post("/client/released", json={"pr": PR, "sha": M[41][:7]}, headers=h)
    check("POST /client/released settles the PR's items", res.status_code == 200 and rd(1)["status"] == "completed" and rd(2)["metadata"].get("next") == "home-builder: then check the pages", res.text)
    res = c.post("/client/released", json={"pr": PR, "sha": M[41]})
    check("no token, no write", res.status_code == 401, res.text)
    s1 = snap()
    res = c.post("/client/sweep-released", json={"dry_run": True}, headers=h)
    check("POST /client/sweep-released with dry_run lists and writes nothing", res.status_code == 200 and ["a10"] == [x["item"] for x in res.json()["items"] if x["action"] == "closed"]
          and not same(s1), res.text)
drain()

# ---- 7. a [released.repos] repository: a PR is live when its merge is an ancestor of that checkout's HEAD (real git in a scratch repo; the table is set in-process)
SIB = "example-owner/sibling"; SC = T / "sib"
def surl(n): return f"https://github.com/{SIB}/pull/{n}"
def sg(*a): return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=SC, env=genv, capture_output=True, text=True, check=True).stdout.strip()
SC.mkdir(); sg("init", "-q", "-b", "main"); (SC / "f").write_text("0"); sg("add", "f"); sg("commit", "-qm", "base")
SIBM = {}
for n, br in ((7, "main"), (8, "pending")):      # #7 is merged into main, which the checkout is on; #8 is merged on a branch the checkout has not been moved to (not deployed yet)
    sg("checkout", "-q", br) if br == "main" else sg("checkout", "-qb", br)
    sg("checkout", "-qb", f"topic{n}"); (SC / "f").write_text(str(n)); sg("commit", "-qam", f"change {n}")
    sg("checkout", "-q", br); sg("merge", "-q", "--no-ff", "-m", f"Merge pull request #{n} from example-owner/topic{n}", f"topic{n}"); SIBM[n] = sg("rev-parse", "HEAD")
sg("checkout", "-q", "main")
FOREIGN = (30, 31, 32, 33, 34, 40, 41, 42)
def ffix():
    fixtures()
    item(30, f"home-builder: release PR {surl(7)}")                       # the URL, with "PR" before it: closes
    item(31, "home-builder: release PR #7")                                # a bare #7 on an item anchored to the sibling's PR 7: closes
    item(32, "home-builder: release #7")                                   # a bare #7, not anchored: this repository's #7, left alone
    item(33, f"home-builder: release PR {surl(8)}")                       # merged on a branch the checkout is not on: not live
    item(34, f"home-builder: release {surl(7)}\nhome-builder: then check the pages")     # a step after it: ticked, the mover told
    item(40, f"home-builder: release PR {surl(7)}"); item(41, "home-builder: release PR #7"); item(42, "home-builder: release #7")      # the clock's catch-up reads these
    a = json.loads((T / "store/anchors.json").read_text())
    a["projects/alpha"] += [{"url": surl(7), "items": ["a31", "a41"], "added": 1, "by": "t"}]
    (T / "store/anchors.json").write_text(json.dumps(a))
def fsnap(): return {i: raw(i) for i in FOREIGN}
def fsame(s0): return [i for i in s0 if raw(i) != s0[i]]
ffix(); f0 = fsnap(); p0 = len(pushes())
try: released_svc.released(surl(7), sha=SIBM[7]); check("refused: a sibling PR with no [released.repos] at all", False)
except ToolError as e: check("refused: a sibling PR with no [released.repos] at all, saying that none is configured", "pull request URL of this repository" in str(e) and "none is configured" in str(e) and str(e).startswith("Refused:"), str(e))
check("…nothing written", not fsame(f0))
_cfg.CFG["released"] = {"repos": {SIB: {"checkout": str(SC)}}}
try:
    for name, pr, sha, want in (("a repository the table does not list, naming the one it does", "https://github.com/someone-else/other/pull/7", SIBM[7], SIB),
                                ("a configured repository's PR whose merge is not in the checkout's HEAD (not deployed yet)", surl(8), SIBM[8], "is not live: its merge"),
                                ("…given with a short sha", surl(8), SIBM[8][:7], "not deployed, or rolled back"),
                                ("a sha the checkout does not know", surl(7), "deadbeef00", "is not a commit the checkout of example-owner/sibling knows"),
                                ("a sha that is no sha (a path or an option)", surl(7), "../../etc/passwd", "is not a commit the checkout of example-owner/sibling knows"),
                                ("a sha that holds no merge of the PR", surl(9), SIBM[7], "is not merged"),
                                ("no sha and the PR is not in the checkout's log", surl(9), "", "is not merged")):
        try: released_svc.released(pr, sha=sha); check(f"foreign refused: {name}", False)
        except ToolError as e: check(f"foreign refused: {name}", want in str(e) and str(e).startswith("Refused:"), str(e))
    check("…none of them wrote or told anything", not fsame(f0) and len(pushes()) == p0, (fsame(f0), pushes()[p0:]))
    r = released_svc.released(surl(7), sha=SIBM[7][:7])
    rows = {x["item"]: x for x in r["items"]}
    check("foreign released: the PR given by URL, by a bare #7 on an item anchored to it, and with a step after it settle as this repository's do",
          rd(30)["status"] == "completed" and rd(31)["status"] == "completed" and rows.get("a30", {}).get("action") == "closed" and rows.get("a31", {}).get("action") == "closed"
          and rows.get("a34", {}).get("action") == "ticked" and rd(34)["metadata"].get("next") == "home-builder: then check the pages" and len(pushes_for("a34")) == 1, (rows, rd(34)["metadata"]))
    check("…the reason names the sibling's PR and its live checkout, and says nothing of main's tests", rd(30)["metadata"]["reason"].startswith(f"PR {SIB}#7 is live (merged at {SIBM[7][:7]} on ")
          and "in the checkout at " in rd(30)["metadata"]["reason"] and "main's tests" not in rd(30)["metadata"]["reason"], rd(30)["metadata"])
    check("…the notice to the mover names the PR with its repository", "PR example-owner/sibling#7 is live; its step is ticked" in pushes_for("a34")[0][1] and "main's tests" not in pushes_for("a34")[0][1], pushes_for("a34"))
    check("…a bare #7 on an item not anchored to the sibling's PR is this repository's #7: untouched; the PR that is not deployed stays open", raw(32) == f0[32] and raw(33) == f0[33] and "a32" not in rows and "a33" not in rows, rows)
    p1 = len(pushes()); r = released_svc.released(surl(7), sha=SIBM[7])
    check("foreign released again: nobody is told twice", not [x for x in r["items"] if x["action"] in ("closed", "ticked", "told")] and len(pushes()) == p1, (r, pushes()[p1:]))
    ffix(); f0 = fsnap()
    r = released_svc.released(surl(7), sha="")
    check("foreign released with no sha: the merge is found in the checkout's log and the items settle", rd(30)["status"] == "completed" and rd(31)["status"] == "completed" and r["sha"] == SIBM[7], (r, rd(30)["status"]))
    ffix(); f0 = fsnap(); p1 = len(pushes())
    d = proofs_svc.sweep_proofs()
    acts = {x["item"]: x["action"] for x in d["items"] if x.get("kind") == "pr_released"}
    check("the clock's catch-up (a release the call missed): the sibling's PR given by URL, or by a bare #7 on an item anchored to it, is settled; a bare #7 on an unanchored item and a PR not deployed are not",
          acts.get("a30") == "closed" and acts.get("a40") == "closed" and acts.get("a41") == "closed" and acts.get("a34") == "ticked" and "a42" not in acts and "a33" not in acts and "a32" not in acts
          and raw(33) == f0[33] and raw(42) == f0[42] and raw(32) == f0[32], (acts, d["items"]))
    # a step's proof: pr_released for a listed repository is accepted, for another is refused naming the listed ones
    cl = _steps.view({"next": "home-builder: restart the unit"}, keeper="")
    meta = {}; note = proofs_svc.step_proof_set(meta, cl, [{"step": 1, "proof": f"pr_released {SIB}#8"}])
    check("step_proof: pr_released for a listed repository's PR is stored", meta.get("step_proof") == {"home-builder: restart the unit": f"pr_released {SIB}#8"} and "step 1 proof: pr_released" in note, (meta, note))
    try: proofs_svc.step_proof_set({}, cl, [{"step": 1, "proof": "pr_released other-owner/else#3"}]); check("step_proof: pr_released for an unlisted repository is refused", False)
    except ToolError as e: check("step_proof: pr_released for an unlisted repository is refused, naming the listed one and pr_merged", "pr_released is for this repository's pull requests" in str(e) and SIB in str(e) and "use pr_merged" in str(e), str(e))
    # a path is never taken from the client: a body field named checkout changes nothing
    ffix(); f0 = fsnap()
    with TestClient(server.mcp.http_app()) as c:
        res = c.post("/client/released", json={"pr": surl(8), "sha": SIBM[8], "checkout": str(SC), "path": str(SC)}, headers=h)
        check("POST /client/released: a checkout or path field in the body is not read (the merge not in HEAD stays refused), nothing written", res.status_code == 400 and "is not live" in res.json().get("error", "") and not fsame(f0), res.text)
        res = c.post("/client/released", json={"pr": "https://github.com/someone-else/other/pull/7", "sha": SIBM[7], "checkout": str(SC)}, headers=h)
        check("…an unlisted repository is refused whatever path is sent", res.status_code == 400 and SIB in res.json().get("error", "") and not fsame(f0), res.text)
        res = c.post("/client/released", json={"pr": surl(7), "sha": SIBM[7]}, headers=h)
        check("POST /client/released settles a listed repository's PR", res.status_code == 200 and rd(30)["status"] == "completed", res.text)
    drain()
    _cfg.CFG["github"] = {"moved": {"old-owner/sibling": SIB}}      # a moved repository's name is compared as the other checks do
    try:
        check("the table is read through [github.moved]: the old name reaches the same checkout", rlive_svc.released_foreign("Old-Owner/Sibling") == SC, _cfg.released_repos())
    finally:
        _cfg.CFG.pop("github", None)
finally:
    _cfg.CFG.pop("released", None)
ffix(); f0 = fsnap()
try: released_svc.released(surl(7), sha=SIBM[7]); check("with the table gone again the feature is off: refused", False)
except ToolError as e: check("with the table gone again the feature is off: refused, nothing written", "none is configured" in str(e) and not fsame(f0), str(e))
drain()

# ---- 8. a [released.repos] checkout on another machine: the checkout that runs the repository is read over ssh (a stand-in ssh on PATH runs the command in a folder that plays that machine's home folder)
HOST = "sib-host.invalid"
ssh = _fake_ssh.FakeSsh(T / "other-machine")
LIVE = ssh.home / "sib live"      # a space in the name: the command sent over ssh is quoted
subprocess.run(["git", "clone", "-q", str(SC), str(LIVE)], env=genv, check=True, capture_output=True)      # it runs main: #7 is deployed; #8's commits are there, not deployed
def lg(*a): return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=LIVE, env=genv, capture_output=True, text=True, check=True).stdout.strip()
sg("merge", "-q", "--ff-only", "pending")      # a copy on the server's own machine that follows main already holds #8
def remote(co="~/sib live", host=HOST): _cfg.CFG["released"] = {"repos": {SIB: {"checkout": co, "ssh": host}}}
def report(n):
    try: released_svc.released(surl(n), sha=SIBM[n]); return ""
    except ToolError as e: return str(e)
def sent_git(c): return shlex.split(c[-1])      # ["timeout", "<seconds>", "git", "-C", <checkout>, <verb>, ...]; a report's session: [..., "sh", "-c", <its git commands>]
def verbs(): return [g[2] for g in ssh.gits()]      # a git run over there: ["-C", <checkout>, <verb>, ...]
def head_reads(): return [g for g in ssh.gits() if g[2:] == ["rev-parse", "--verify", "--quiet", "HEAD^{commit}"]]
def dry(n, sha=""):      # a dry-run report → the merge it accepts, or its refusal
    try: return released_svc.released(surl(n), sha=sha, dry=True)["sha"]
    except ToolError as e: return str(e)
SSH_ARGS = ["-n", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2", "-o", "ControlMaster=no", "-o", "ControlPath=none", "--"]
UNREADABLE = f"Refused: the checkout of {SIB} cannot be read; nothing written"
try:
    with ssh:
        remote(); ffix(); f0 = fsnap(); p0 = len(pushes()); ssh.clear()
        e = report(8)
        check("remote: a merge the running checkout does not hold is not live, though a copy on the server's own machine holds it", e.startswith("Refused:") and "is not live: its merge" in e and "not deployed, or rolled back" in e
              and not fsame(f0) and len(pushes()) == p0, e)
        calls, seen, there = ssh.calls(), ssh.gits(), lg("rev-parse", "HEAD")
        def in_live(*a): return ["-C", "sib live", *a]
        check("remote: a report is one ssh session, with no password prompt, no input, a connect timeout, a dead-link limit, no shared connection, the host after --, and an end there after its seconds",
              len(calls) == 1 and calls[0][:-1] == [*SSH_ARGS, HOST] and sent_git(calls[0])[:4] == ["timeout", "10", "sh", "-c"], calls)
        check("remote: ...and it reads that checkout only: HEAD, the reported commit, that commit's merges, and whether that HEAD holds it",
              seen == [in_live("rev-parse", "--verify", "--quiet", "HEAD^{commit}"), in_live("rev-parse", "--verify", "--quiet", f"{SIBM[8]}^{{commit}}"),
                      in_live("log", "--first-parent", "--merges", "-n50", "--format=%H%x09%ct%x09%s", SIBM[8]), in_live("merge-base", "--is-ancestor", SIBM[8], there)], seen)
        lg("merge", "-q", "--ff-only", "origin/pending")      # the deploy on the machine that runs it
        real_argv, locked = rlive_svc.ssh_argv, []
        rlive_svc.ssh_argv = lambda *a: (locked.append(writes.ITEM_LOCK._is_owned()), real_argv(*a))[1]
        ssh.clear()
        try: r = released_svc.released(surl(8), sha=SIBM[8])
        finally: rlive_svc.ssh_argv = real_argv
        check("remote: the same report is accepted as soon as the running checkout holds the merge, and the item built for it settles",
              rd(33)["status"] == "completed" and f"in the checkout at {lg('rev-parse', 'HEAD')[:7]}" in rd(33)["metadata"]["reason"], (r, rd(33)["metadata"]))
        check("remote: ...in one session, made while the item lock is not held", len(ssh.calls()) == 1 and locked == [False], (ssh.calls(), locked))
        drain()
        for sha, n, what in ((SIBM[8], 7, "a later commit that holds the merge"), (SIBM[8][:7], 8, "a short sha"), ("HEAD", 8, "the word HEAD")):
            ssh.clear(); got = dry(n, sha)
            check(f"remote: a report that gives {what} is one session too", got == SIBM[n] and len(ssh.calls()) == 1, (got, ssh.calls()))
        ssh.clear(); got = dry(8, "HEAD")
        check("remote: ...the word HEAD is read there once, and its merges are those of the commit that read gave", got == SIBM[8] and verbs() == ["rev-parse", "log"] and ssh.gits()[1][-1] == lg("rev-parse", "HEAD"), ssh.gits())
        ssh.clear(); got = dry(7); seen = ssh.gits()
        check("remote: ...as is one with no sha, which reads the merges of the HEAD that session read", got == SIBM[7] and len(ssh.calls()) == 1 and verbs() == ["rev-parse", "log"]
              and seen[1][-1] == lg("rev-parse", "HEAD") and "-n3000" in seen[1], (got, seen))
        ssh.clear(); rlive_svc.foreign_ahead(rlive_svc.released_foreign(SIB), SIBM[7], 50)
        check("remote: nothing is read ahead outside a request, where nothing would keep it", ssh.calls() == [], ssh.calls())
        lg("reset", "-q", "--hard", SIBM[7]); ffix(); f0 = fsnap()      # a rollback there
        e = report(8)
        check("remote: after a rollback there the report is refused again (HEAD is read at each call)", "not deployed, or rolled back" in e and not fsame(f0), e)
        ssh.clear(); got = dry(7, SIBM[8]); seen = ssh.gits()
        check("remote: a given commit that HEAD does not hold says nothing of the older merge in it: HEAD is asked about that merge, in a second session",
              got == SIBM[7] and len(ssh.calls()) == 2 and seen[-1] == in_live("merge-base", "--is-ancestor", SIBM[7], lg("rev-parse", "HEAD")), (got, seen))
        for word in (f"{SIBM[7]};touch pwned", "$(touch pwned)", f"{SIBM[7]}\ntouch pwned", "--output=pwned", "HEAD~1"):
            ssh.clear(); got = dry(7, word)
            check(f"remote: a sha that is no commit's name ({word[:20]!r}) is refused and never sent there", "is not a commit the checkout of" in got and not (ssh.home / "pwned").exists()
                  and not [c for c in ssh.calls() if "pwned" in c[-1] or "HEAD~1" in c[-1]], (got, ssh.calls()))
        ssh.clear()
        d = proofs_svc.sweep_proofs()
        acts = {x["item"]: x["action"] for x in d["items"] if x.get("kind") == "pr_released"}
        check("remote sweep: the items are settled by what the running checkout holds, and its HEAD is read once a pass however many pull requests wait",
              acts.get("a30") == "closed" and acts.get("a40") == "closed" and "a33" not in acts and raw(33) == f0[33] and len(head_reads()) == 1, (acts, head_reads()))
        drain()

        for mode, what in (("down", "a machine that gives no answer"), ("banner", "a machine whose shell prints a line before every answer")):
            ssh.mode(mode); ssh.clear(); ffix(); f0 = fsnap(); e = report(7)
            check(f"remote: {what} reads as 'cannot be read' after one read, nothing written", e == UNREADABLE and not fsame(f0) and len(ssh.calls()) == 1, (e, ssh.calls()))
        ssh.mode("down"); ffix(); f0 = fsnap(); d = proofs_svc.sweep_proofs()
        check("remote sweep: nothing is settled while the machine gives no answer", not [x for x in d["items"] if x.get("kind") == "pr_released" and x["item"] in ("a30", "a31", "a40", "a41")] and not fsame(f0), d["items"])
        ssh.mode("gitfail merge-base"); e = report(7)
        check("remote: an ancestor question that gets no answer is 'cannot be read', never 'not deployed'", f"is not live: the checkout of {SIB} cannot be read" in e and "not deployed" not in e and not fsame(f0), e)
        for mode, what in (("fail merge-base", "a session that gives no connection"), ("short merge-base", "a session that answers only some of the questions, though it ends well")):
            ssh.mode(mode); e = report(7)
            check(f"remote: {what} is 'cannot be read', and nothing is written", e == UNREADABLE and not fsame(f0), e)
        rlive_svc.PROOF_GIT.clear(); ssh.mode("fail log --first-parent")
        h1, m1 = rlive_svc.foreign_prs(SIB); ssh.mode(""); h2, m2 = rlive_svc.foreign_prs(SIB)
        check("remote: a log that failed after HEAD was read reads as nothing and is not kept: the next read sees the merges of the same commit", (h1, m1) == ("", {}) and h2 == lg("rev-parse", "HEAD") and 7 in m2, (h1, m1, h2, m2))
        ssh.clear(); h3, m3 = rlive_svc.foreign_prs(SIB)
        check("remote: ...a log that worked is kept by commit, and HEAD is read again", verbs() == ["rev-parse"] and (h3, m3) == (h2, m2), verbs())

        remote(co=str(LIVE)); ssh.clear(); h, _m = rlive_svc.foreign_prs(SIB)
        check("remote: an absolute path is sent as written", h == h2 and sent_git(ssh.calls()[0])[2:5] == ["git", "-C", str(LIVE)], ssh.calls())
        check("remote: '~/' alone is the home folder there", shlex.split(rlive_svc.git_argv(("x",), _cfg.RemoteCheckout(HOST, "~/"))[-1]) == ["timeout", "10", "git", "-C", ".", "x"])
        odd = ssh.home / "o'dd $(touch pwned) ;x \"y\" `touch pwned`"
        subprocess.run(["git", "clone", "-q", str(LIVE), str(odd)], env=genv, check=True, capture_output=True)
        for co in (str(odd), f"~/{odd.name}"):
            remote(co=co); ssh.clear(); got = dry(7, SIBM[7])
            check("remote: a path full of shell characters reaches git as one word, in a report's session", got == SIBM[7] and len(ssh.calls()) == 1 and {g[1] for g in ssh.gits()} == {co.replace("~/", "")}
                  and not (ssh.home / "pwned").exists(), (got, ssh.gits()))

        _cfg.CFG["hosts"] = {"lookup": f"printf '%s\\n' {HOST} {{role}}"}; remote(host="host:sib-box"); ssh.clear(); h, _m = rlive_svc.foreign_prs(SIB)
        check("remote: a role word is looked up when git runs, and the table keeps the word", h == h2 and bool(ssh.calls()) and {c[-2] for c in ssh.calls()} == {HOST}
              and _cfg.released_repos()[SIB] == _cfg.RemoteCheckout("host:sib-box", "~/sib live"), (h, ssh.calls()))
        _cfg.CFG["hosts"] = {"lookup": "false {role}"}; remote(host="host:gone-box"); ssh.clear()
        with contextlib.redirect_stderr(io.StringIO()): e = report(7)
        check("remote: a role word with no answer reads as 'cannot be read', and ssh is not run", e == UNREADABLE and ssh.calls() == [], (e, ssh.calls()))
        _cfg.CFG.pop("hosts")

        remote(co=str(LIVE), host=socket.gethostname()); ssh.clear(); h, _m = rlive_svc.foreign_prs(SIB)
        check("remote: a host that names the server's own machine is read directly, with no ssh", h == h2 and ssh.calls() == [], (h, ssh.calls()))
        home_was = os.environ.get("HOME"); os.environ["HOME"] = str(ssh.home)
        try:
            remote(host="localhost"); ssh.clear(); h, _m = rlive_svc.foreign_prs(SIB)
            check("remote: ...and '~/' is then this process's home folder", h == h2 and ssh.calls() == [], (h, ssh.calls()))
            got = dry(7, SIBM[7])
            check("remote: ...and a report of it is read there too", got == SIBM[7] and ssh.calls() == [], (got, ssh.calls()))
        finally:
            os.environ.pop("HOME") if home_was is None else os.environ.__setitem__("HOME", home_was)
        remote(host="someone@localhost"); ssh.clear(); h, _m = rlive_svc.foreign_prs(SIB)
        check("remote: a host written with a user is asked over ssh as that user, even when it names this machine", h == h2 and bool(ssh.calls()) and ssh.calls()[0][-2] == "someone@localhost", ssh.calls())

    bad = {"example-owner/empty": {"checkout": str(SC), "ssh": ""}, "example-owner/option": {"checkout": str(SC), "ssh": "-oProxyCommand=x"}, "example-owner/words": {"checkout": str(SC), "ssh": "two words"},
           "example-owner/number": {"checkout": str(SC), "ssh": 5}, "example-owner/role": {"checkout": str(SC), "ssh": "host:two words"}, "example-owner/relative": {"checkout": "sib live", "ssh": HOST},
           "example-owner/user-home": {"checkout": "~someone/sib", "ssh": HOST}, "example-owner/no-path": {"ssh": HOST},
           "example-owner/misspelled": {"checkout": str(SC), "shh": HOST}, "example-owner/extra": {"checkout": "~/sib", "ssh": HOST, "branch": "main"}}
    _cfg.CFG["released"] = {"repos": bad}
    check("config: an entry with a bad ssh host, a path that cannot be sent or a key that is not read (a misspelled ssh) is ignored and said, so its path is never read on this machine instead",
          _cfg.released_repos() == {} and len(_cfg.released_notes()) == len(bad) and all('ssh = "<host>"' in n and "no other key is read" in n for n in _cfg.released_notes()), (_cfg.released_repos(), _cfg.released_notes()))
    _cfg.CFG["released"] = {"repos": {SIB: {"checkout": " ~/sib live ", "ssh": f" {HOST} "}}}
    check("config: a good one is a checkout on that machine, the spaces round its values dropped, with no note", _cfg.released_repos() == {SIB: _cfg.RemoteCheckout(HOST, "~/sib live")} and _cfg.released_notes() == [], _cfg.released_repos())
    check("...and client.py's help says such a checkout is read over ssh", "over ssh when it is on another machine" in " ".join(client.__doc__.split()))
finally:
    _cfg.CFG.pop("released", None); _cfg.CFG.pop("hosts", None)

# ---- 9. a read that gets no answer: nothing is known and nothing is kept; the reads have a time limit; a machine that gives no answer is asked once; a read is the request's, write's or pass's own
SIB2 = "example-owner/second"
def two(host2=HOST): _cfg.CFG["released"] = {"repos": {SIB: {"checkout": "~/sib live", "ssh": HOST}, SIB2: {"checkout": "~/sib two", "ssh": host2}}}
def both():
    with rlive_svc.reading(): return [rlive_svc.foreign_prs(SIB), rlive_svc.foreign_prs(SIB2), rlive_svc.foreign_prs(SIB)]
def timed(f):
    began = time.monotonic(); got = f(); return got, time.monotonic() - began
NOTHING = ("", {})
real_limits = (rlive_svc.READ_SECONDS, rlive_svc.REMOTE_SECONDS)
try:
    with ssh:
        lg("reset", "-q", "--hard", SIBM[8]); remote(); ffix(); f0 = fsnap()      # the running checkout holds #7 and #8
        for mode, what in (("cut log --first-parent", "a log that stops part way"), ("gitfail log --first-parent", "a log git ends with a failure")):
            ssh.mode(mode); e = report(8)
            check(f"no answer: {what} is 'cannot be read', never 'not merged', and nothing is written", e == UNREADABLE and not fsame(f0), e)
        rlive_svc.PROOF_GIT.clear(); ssh.mode("cut log --first-parent"); got = rlive_svc.foreign_prs(SIB); ssh.mode(""); again = rlive_svc.foreign_prs(SIB)
        check("no answer: ...and the merges it did print are not kept: the next read of the same commit has them all", got == NOTHING and again[0] == SIBM[8] and {7, 8} <= set(again[1]), (got, again))
        ssh.mode("gitfail " + SIBM[7]); e = report(7)
        check("no answer: the question about the reported sha left unanswered is 'cannot be read', never 'not a commit'", e == UNREADABLE and not fsame(f0), e)
        ssh.mode("")
        try: released_svc.released(surl(7), sha="0" * 40); e = ""
        except ToolError as x: e = str(x)
        check("no answer: ...while a sha the checkout answers it does not know is still said to be unknown", "is not a commit the checkout of" in e and not fsame(f0), e)
        for asked, which in ((SIBM[7], "a commit it knows"), ("0" * 40, "a sha it does not know")):
            for noisy, ahead in (("banner", "of the session"), ("noise", "of the answer")):
                ssh.mode(f"{noisy} {asked}"); got = dry(7, asked)
                check(f"no answer: a line printed ahead {ahead} about {which} is 'cannot be read', never 'not a commit'", got == UNREADABLE and not fsame(f0), got)
        for mode, what in (("gitfail merge-base", "ends with git's failure"), ("hang merge-base", "never comes")):
            rlive_svc.READ_SECONDS = 3; ssh.mode(mode); e = report(8); why = rlive_svc.foreign_live(SIB, SIBM[8])
            check(f"no answer: an ancestor question whose answer {what} never counts as live", "cannot be read" in e and "cannot be read" in why and not fsame(f0), (e, why))
        real_git = rlive_svc.git
        def no_merge_base(*a, **k):
            if a[0] == "merge-base": raise OSError("no process")
            return real_git(*a, **k)
        rlive_svc.git = no_merge_base; ssh.mode("")
        try: why = rlive_svc.foreign_live(SIB, SIBM[8])
        finally: rlive_svc.git = real_git
        check("no answer: ...nor does an ancestor question that cannot be asked at all", "cannot be read" in why, why)

        rlive_svc.READ_SECONDS = 1.5; ssh.mode("hang"); ssh.clear(); e, took = timed(lambda: report(7))
        check("time limit: a machine that sends nothing is given up within the read's limit and not asked again", e == UNREADABLE and took < 8 and len(ssh.calls()) == 1 and not fsame(f0), (e, took, ssh.calls()))
        two(); ssh.clear(); got, took = timed(both)
        check("time limit: ...nor asked about a second repository in the same pass", got == [NOTHING] * 3 and took < 8 and len(ssh.calls()) == 1, (got, took, ssh.calls()))
        ssh.clear(); got = [rlive_svc.foreign_prs(SIB), rlive_svc.foreign_prs(SIB2)]
        check("time limit: ...and the next pass asks it again", got == [NOTHING] * 2 and len(ssh.calls()) == 2, (got, ssh.calls()))
        rlive_svc.READ_SECONDS = real_limits[0]
        ssh.mode("down"); ssh.clear(); got = both()
        check("silent machine: one that gives no connection is asked once in a pass", got == [NOTHING] * 3 and len(ssh.calls()) == 1, ssh.calls())
        two("other-host.invalid"); ssh.clear(); got = both()
        check("silent machine: ...which says nothing of another machine", [c[-2] for c in ssh.calls()] == [HOST, "other-host.invalid"], ssh.calls())
        two(); ssh.mode("gitfail rev-parse"); ssh.clear(); got = both()
        check("silent machine: a git failure there silences nothing, so another checkout on it is still asked; a read that failed is not made again in the same pass",
              got == [NOTHING] * 3 and [sent_git(c)[4] for c in ssh.calls()] == ["sib live", "sib two"], ssh.calls())
        rlive_svc.REMOTE_SECONDS = 1; ssh.mode("stuck"); two(); ssh.clear(); got, took = timed(both)
        check("time limit: a git that does not end over there is ended there after its seconds, and that machine is not asked again", got == [NOTHING] * 3 and took < _fake_ssh.STUCK_SECONDS - 2
              and len(ssh.calls()) == 1 and sent_git(ssh.calls()[0])[:2] == ["timeout", "1"], (got, took, ssh.calls()))
        remote(); e, took = timed(lambda: report(7))
        check("time limit: ...and a report of it is 'cannot be read' as soon", e == UNREADABLE and took < _fake_ssh.STUCK_SECONDS - 2 and not fsame(f0), (e, took))
        rlive_svc.REMOTE_SECONDS = real_limits[1]; rlive_svc.READ_SECONDS = 4; ssh.mode("slow 1.5"); ssh.clear(); got = dry(7, SIBM[7])
        check("slow machine: a report is accepted when every session there is slow, since it makes one", got == SIBM[7] and len(ssh.calls()) == 1, (got, ssh.calls()))
        lg("reset", "-q", "--hard", SIBM[7]); rlive_svc.READ_SECONDS = 1.7; ssh.mode("slow 1"); ssh.clear(); e, took = timed(lambda: dry(7, SIBM[8]))
        check("time limit: the sessions of one report share the limit, so answers that are each in time but slow end it", "cannot be read" in e and took < 6 and len(ssh.calls()) == 2 and not fsame(f0), (e, took, ssh.calls()))
        lg("reset", "-q", "--hard", SIBM[8]); ssh.mode("")
        check("time limit: ...and the next read has its own", rlive_svc.foreign_prs(SIB)[0] == SIBM[8])
        rlive_svc.READ_SECONDS = real_limits[0]
        check("time limit: one report's reads end well inside the minute its client waits, and a command is ended there before the read's limit",
              rlive_svc.SSH_CONNECT < rlive_svc.REMOTE_SECONDS < rlive_svc.READ_SECONDS <= 30, (rlive_svc.SSH_CONNECT, rlive_svc.REMOTE_SECONDS, rlive_svc.READ_SECONDS))

        ssh.clear(); bare = rlive_svc.foreign_prs_locked(SIB)
        with rlive_svc.reading(): unread = rlive_svc.foreign_prs_locked(SIB)
        check("under the item lock: with no read made by this write, a checkout on another machine is not read", bare == unread == NOTHING and ssh.calls() == [], (bare, unread, ssh.calls()))
        with rlive_svc.reading():
            before = rlive_svc.foreign_prs(SIB); n_calls = len(ssh.calls()); locked = rlive_svc.foreign_prs_locked(SIB)
            with rlive_svc.reading(): inner = rlive_svc.foreign_prs(SIB)
            after_inner = rlive_svc.foreign_prs_locked(SIB)
        check("under the item lock: with one, that read is what is used, in a block inside it and after it too, with no further call", before[0] == SIBM[8] and locked == inner == after_inner == before
              and len(ssh.calls()) == n_calls, (before[0], n_calls, ssh.calls()))
        lg("reset", "-q", "--hard", SIBM[7]); ssh.clear(); after = rlive_svc.foreign_prs(SIB)
        check("under the item lock: nothing of a read outlives its block, so a rollback shows in the next", after[0] == SIBM[7] and 8 not in after[1] and ssh.calls() != []
              and rlive_svc.foreign_prs_locked(SIB) == NOTHING, (after, ssh.calls()))
        _cfg.CFG["released"] = {"repos": {SIB: {"checkout": str(LIVE)}}}
        check("under the item lock: a checkout on this machine with no earlier read is read there and then", rlive_svc.foreign_prs_locked(SIB)[0] == SIBM[7])

        me = socket.gethostname(); short = me.split(".")[0]; like = f"{short}.example.invalid"
        check("own machine: its name whole or short, in any case, localhost and a loopback address", all(rlive_svc.own_machine(h) for h in (me, me.upper(), short, "localhost", "localhost.localdomain", "127.0.0.1", "127.0.1.1", "::1")), me)
        check("own machine: a name that only begins like it, another name or address, and a name with a user are not", not any(rlive_svc.own_machine(h) for h in (like, me + "x", f"someone@{me}", "192.0.2.7", "2001:db8::7", "127.example.invalid", HOST)), me)
        remote(co=str(LIVE), host=like); ssh.clear(); h, _m = rlive_svc.foreign_prs(SIB)
        check("own machine: so a host under another domain that begins like this one is asked over ssh", h == SIBM[7] and bool(ssh.calls()) and {c[-2] for c in ssh.calls()} == {like}, (h, ssh.calls()))
        remote(co=str(LIVE), host="127.0.0.1"); ssh.clear(); h, _m = rlive_svc.foreign_prs(SIB)
        check("own machine: and a loopback address is read directly", h == SIBM[7] and ssh.calls() == [], (h, ssh.calls()))

        gone, where = T / "role-gone", T / "where.sh"
        where.write_text(f"#!/bin/sh\n[ -e '{gone}' ] && exit 1\necho {HOST}\n", encoding="utf-8")
        _cfg.CFG["hosts"] = {"lookup": f"sh '{where}' {{role}}", "cache_seconds": 0}; remote(host="host:moving-box"); ssh.clear()
        h_ok, _m = rlive_svc.foreign_prs(SIB)
        check("role: the lookup answers and the checkout is read on that host", h_ok == SIBM[7] and {c[-2] for c in ssh.calls()} == {HOST}, (h_ok, ssh.calls()))
        gone.touch(); ssh.clear(); ffix(); f0 = fsnap()
        with contextlib.redirect_stderr(io.StringIO()): first, second = report(7), report(7)      # the failing lookup, then its rest
        check("role: while its lookup fails nothing is read, at the first failure and while it rests, though the other settings keep the last good host",
              first == second == UNREADABLE and ssh.calls() == [] and not fsame(f0) and _cfg.host("host:moving-box") == HOST, (first, second, ssh.calls()))
        gone.unlink(); _cfg._host_reset(); h_back, _m = rlive_svc.foreign_prs(SIB)
        check("role: ...and it is read again once the lookup answers", h_back == SIBM[7], h_back)
        _cfg.CFG.pop("hosts")
finally:
    rlive_svc.READ_SECONDS, rlive_svc.REMOTE_SECONDS = real_limits
    _cfg.CFG.pop("released", None); _cfg.CFG.pop("hosts", None)

class Dropping(dict):
    def __setitem__(self, k, v): pass      # what a clear from another thread, right after the keep, looks like
kept_was = rlive_svc.PROOF_GIT
rlive_svc.PROOF_GIT = Dropping()
try: got = rlive_svc.proof_git(("k",), lambda: {1: "x"})
except KeyError as x: got = x
finally: rlive_svc.PROOF_GIT = kept_was
check("kept answers: the answer in hand is returned, whatever another thread did to the table meanwhile", got == {1: "x"}, got)
real_git = rlive_svc.git
def half_log(*a, **k): return subprocess.CompletedProcess(a, 128, "abc\t1\tMerge pull request #5 from x/y\n", "fatal: bad object")
def no_git(*a, **k): raise OSError("no git")
for fake, what in ((half_log, "ends with a failure after printing a line"), (no_git, "cannot be run")):
    rlive_svc.git = fake; key = ("prs", "ab12cd34", what)
    try: got = rlive_svc.proof_git(key, lambda: rlive_svc.merged_prs("ab12cd34"))
    finally: rlive_svc.git = real_git
    check(f"kept answers: a log of this checkout that {what} reads as no merges and is not kept", got == {} and key not in rlive_svc.PROOF_GIT, (got, rlive_svc.PROOF_GIT.get(key)))

sent = []
client.post = lambda what, body, timeout=30.0: (sent.append((what, body)), (200, {"pr": PR, "head": "abcdef1234", "good": "600d000aaa", "items": [
    {"item": "a1", "action": "closed", "reason": "PR #41 is live (x) and main's tests passed", "subject": "[home] item 1", "pr": 41},
    {"item": "a2", "action": "ticked", "told": "home-builder", "subject": "[home] item 2", "pr": 41},
    {"item": "a25", "action": "ticked", "told": "", "quiet": True, "mover": "home-builder", "subject": "[home] item 25", "pr": 41},
    {"item": "a16", "action": "told", "told": "home-builder", "subject": "[home] item 16", "pr": 41},
    {"item": "a3", "action": "left", "why": "parked", "subject": "[home] item 3", "pr": 41},
    {"item": "a14", "action": "left", "why": "its needs name home-third, not its mover", "subject": "[home] item 14", "pr": 41}]}))[1]
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "released", "--pr", PR, "--sha", "0606060"])
check("client.py released posts the PR and the merge", rc == 0 and sent[-1] == ("released", {"pr": PR, "sha": "0606060", "dry_run": False}), sent)
check("…and prints one line per item, a skipped one with why (release.sh logs these lines)", buf.getvalue().splitlines() == [
    "stackshot: PR #41: closed a1 (outcome done: PR #41 is live (x) and main's tests passed) — [home] item 1",
    "stackshot: PR #41: ticked the release step of a2 and told its mover home-builder that the item's other open steps remain — [home] item 2",
    "stackshot: PR #41: ticked the release step of a25 (every other open step releases another PR: nobody told) — [home] item 25",
    "stackshot: PR #41: told the mover home-builder of a16 that the PR is live and its release step is not ticked (it names a follow-up or a condition, so the step stays open) — [home] item 16",
    "stackshot: PR #41: left a3 alone: parked — [home] item 3",
    "stackshot: PR #41: left a14 alone: its needs name home-third, not its mover — [home] item 14"], buf.getvalue())
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "sweep-released", "--dry-run"])
check("client.py sweep-released --dry-run posts dry_run and says it would", rc == 0 and sent[-1] == ("sweep-released", {"dry_run": True})
      and "last-good 600d000, live checkout abcdef1" in buf.getvalue() and "dry run: nothing written, nobody told" in buf.getvalue()
      and "would close a1" in buf.getvalue() and "would tick the release step of a2" in buf.getvalue(), buf.getvalue())
n_sent = len(sent)
for argv in (["released"], ["released", "--sha", "x"], ["released", "--pr", PR], ["released", "--pr", PR, "--sha", "x", "--project", "projects/alpha"], ["sweep-released", "--project", "x"]):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()): rc = client.main(["client.py", *argv])
    check(f"usage, exit 1, nothing sent: {' '.join(argv)}", rc == 1 and len(sent) == n_sent)
client.post = lambda what, body, timeout=30.0: (400, {"error": "Refused: PR #44 is not merged"})
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "released", "--pr", url(44), "--sha", "abc1234"])
check("a refusal exits 1 and says why", rc == 1 and "items not settled [400] Refused: PR #44 is not merged" in buf.getvalue(), buf.getvalue())
check("client.py's help names both verbs and which steps count", "client.py released --pr <PR url> --sha <merge commit>" in client.__doc__ and "client.py sweep-released" in client.__doc__
      and '"release PR #N", "release #N", or "release" before the PR\'s URL' in client.__doc__)
check("…and says a repository other than this one is read only when [released.repos] lists it, in the help and in the usage a wrong call prints",
      "[released.repos]" in client.__doc__ and "ancestor of that repository's checkout HEAD" in client.__doc__ and "[released.repos]" in client.RELEASED_USAGE)
rel = pathlib.Path(STACK, "release.sh").read_text(encoding="utf-8")
check("release.sh's help says what it does once main's full run passed, and which steps count",
      "`client.py released --pr <url> --sha <merge>`" in rel and "PR #N is live; its step is ticked; the item's other open steps remain" in rel and "do the step after it and close the item" not in rel and "pre-release" in rel and '"release PR #N", "release #N", or "release" before its URL' in rel
      and "--project projects/example" not in rel)
check("the update/create check text says exactly which steps count", "`release PR #<n>`, `release #<n>`, or `release` before the PR's URL" in _wt_text._CHECK_FORM
      and "only mentions the PR" in _wt_text._CHECK_FORM)

print(f"{len(ran) - len(fails)}/{len(ran)} passed" + (f" — FAILED: {', '.join(fails)}" if fails else ""))
sys.exit(1 if fails else 0)
