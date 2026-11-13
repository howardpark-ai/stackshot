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
stamped). The same over HTTP with the machine's token; the client verbs' usage and lines.

    tests/run-suite released        → exit 0 / 1"""
import json, os, re, sys, pathlib, subprocess, time, logging, io, contextlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
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
from stackshot.service import telling
server._publish = lambda: None
server._OWN_REPO[:] = [REPO]                       # this checkout's origin, as the fixture's repository
server._HERE = T / "repo"
check("the last-good path is release.sh's ($LOGDIR/last-good, LOGDIR = config.py state releases)", server._cfg.state("releases", "last-good") == LAST_GOOD)
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
r = server._released(PR, sha=M[41])
rows = {x["item"]: x for x in r["items"]}
it1 = rd(1)
check("only open step is the release: completed, outcome done, the reason naming the PR, its merge and last-good",
      it1["status"] == "completed" and it1["metadata"].get("outcome") == "done" and it1["metadata"]["reason"].startswith(f"PR #41 is live (merged at {M[41][:7]} on ")
      and f"in the last-good commit {M[43][:7]}" in it1["metadata"]["reason"] and "main's tests passed" in it1["metadata"]["reason"] and rows.get("a1", {}).get("action") == "closed", (it1, rows.get("a1")))
check("…its release step is marked done by the server's own label, next is gone",
      [(s["status"], s["by"]) for s in it1["metadata"].get("steps", [])] == [("done", server.NAME)] and "next" not in it1["metadata"], it1["metadata"])
check("…no session turn: nobody is told of the close", not pushes_for("a1"), pushes())
check("\"release #41\" counts too: closed", rd(15)["status"] == "completed" and rows.get("a15", {}).get("action") == "closed", rows.get("a15"))
it2 = rd(2)
check("a step after it: the release step is ticked done by the server, the step after it stays open in next",
      it2["status"] == "open" and it2["metadata"].get("next") == "home-builder: then check the pages"
      and [(s["text"], s["status"], s.get("by")) for s in it2["metadata"].get("steps", [])] == [("home-builder: release PR #41", "done", server.NAME), ("home-builder: then check the pages", "open", None)]
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
      rows.get("a3", {}).get("action") == "left" and rows["a3"]["why"] == "on hold"
      and rows.get("a4", {}).get("action") == "left" and "decision" in rows["a4"]["why"]
      and rows.get("a14", {}).get("action") == "left" and "its needs name home-third, not its mover" == rows["a14"]["why"]
      and not {"a5", "a7"} & set(rows), rows)
check("the PR's URL after \"release\" counts in any project: closed", rd(9)["status"] == "completed" and rows.get("a9", {}).get("action") == "closed", rows.get("a9"))
check("#43's and #45's items are not touched by #41's release", raw(10) == before[10] and raw(11) == before[11])
check("no notice for the left-alone or untouched items", not any(pushes_for(gx) for gx in ("a3", "a4", "a5", "a7", "a8", "a12", "a14", "a22", "a23", "a24")), pushes())

# ---- 2. idempotent: a rerun of released, then the sweep, sends nobody a second notice for PR #41
p0 = len(pushes())
r = server._released(PR, sha=M[41])
check("released again: nothing closed or ticked, the told item is left with why, no second notice",
      not [x for x in r["items"] if x["action"] in ("closed", "ticked", "told")] and len(pushes()) == p0
      and {x["item"]: x["why"] for x in r["items"]}.get("a6") == "its mover was told already that PR #41 is live", (r, pushes()[p0:]))
d = server._sweep_released()
check("the sweep after it: closes #43's item, sends no second notice for #41", rd(10)["status"] == "completed"
      and not [p for p in pushes()[p0:] if "PR #41" in p[1]], (d, pushes()[p0:]))
d = server._sweep_released()
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
    try: server._released(pr, sha=sha); check(f"refused: {name}", False)
    except server.ToolError as e: check(f"refused: {name}", want in str(e) and str(e).startswith("Refused:"), str(e))
check("…and none of them wrote or told anything", not same(s0) and len(pushes()) == p0, (same(s0), pushes()[p0:]))
LAST_GOOD.unlink()
try: server._released(PR, sha=M[41]); check("refused: no last-good recorded", False)
except server.ToolError as e: check("refused: no last-good recorded", "no last-good commit is recorded" in str(e), str(e))
try: server._sweep_released(); check("the sweep refused: no last-good recorded", False)
except server.ToolError as e: check("the sweep refused: no last-good recorded", "no last-good commit is recorded" in str(e), str(e))
good(M[43])
check("…nothing written", not same(s0))

# ---- 4. the sweep before last-good holds the merge: #45's item stays open; dry run first
d = server._sweep_released(dry=True)
acts = {(x["item"], x["pr"]): x["action"] for x in d["items"]}
check("dry run: lists what it would close, tick, tell and leave, for the merges in last-good only",
      acts == {("a1", 41): "closed", ("a2", 41): "ticked", ("a3", 41): "left", ("a4", 41): "left", ("a6", 41): "told", ("a9", 41): "closed",
               ("a10", 43): "closed", ("a13", 41): "ticked", ("a14", 41): "left", ("a15", 41): "closed",
               ("a16", 41): "told", ("a17", 41): "told", ("a18", 41): "told", ("a19", 41): "told", ("a20", 41): "closed", ("a21", 41): "told",
               ("a25", 41): "ticked", ("a26", 41): "ticked", ("a27", 41): "closed"} and d["good"] == M[43] and d["head"] == M[45], (acts, d.get("good"), d.get("head")))
check("dry run: writes nothing and tells nobody", not same(s0) and len(pushes()) == p0, (same(s0), pushes()[p0:]))
d = server._sweep_released()
check("the real sweep: the merge after last-good (#45, main's run going) closes nothing", raw(11) == s0[11] and not [x for x in d["items"] if x.get("pr") == 45], d)
check("…the merges in last-good settle as release.sh's call would", rd(1)["status"] == "completed" and rd(10)["status"] == "completed" and rd(13)["status"] == "open"
      and raw(12) == s0[12] and raw(8) == s0[8], d)
check("…the closes tell nobody; the ticks and the same-line follow-up tell their movers, once each", sorted(p[1].split(":")[0].split()[-1] for p in pushes()[p0:]) == ["a13", "a16", "a17", "a18", "a19", "a2", "a21", "a26", "a6"], pushes()[p0:])

# ---- 5. a rollback closes nothing: last-good names #45's merge, but the checkout went back before it
fixtures(); p0 = len(pushes()); s0 = snap()
good(M[45]); g("reset", "-q", "--hard", M[43])
try: server._released(url(45), sha=M[45]); check("refused: a merge rolled back out of HEAD", False)
except server.ToolError as e: check("refused: a merge rolled back out of HEAD", f"is not in the live checkout {M[43][:7]} (rolled back)" in str(e), str(e))
d = server._sweep_released()
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
try: server._released(surl(7), sha=SIBM[7]); check("refused: a sibling PR with no [released.repos] at all", False)
except server.ToolError as e: check("refused: a sibling PR with no [released.repos] at all, saying that none is configured", "pull request URL of this repository" in str(e) and "none is configured" in str(e) and str(e).startswith("Refused:"), str(e))
check("…nothing written", not fsame(f0))
server._cfg.CFG["released"] = {"repos": {SIB: {"checkout": str(SC)}}}
try:
    for name, pr, sha, want in (("a repository the table does not list, naming the one it does", "https://github.com/someone-else/other/pull/7", SIBM[7], SIB),
                                ("a configured repository's PR whose merge is not in the checkout's HEAD (not deployed yet)", surl(8), SIBM[8], "is not live: its merge"),
                                ("…given with a short sha", surl(8), SIBM[8][:7], "not deployed, or rolled back"),
                                ("a sha the checkout does not know", surl(7), "deadbeef00", "is not a commit the checkout of example-owner/sibling knows"),
                                ("a sha that is no sha (a path or an option)", surl(7), "../../etc/passwd", "is not a commit the checkout of example-owner/sibling knows"),
                                ("a sha that holds no merge of the PR", surl(9), SIBM[7], "is not merged"),
                                ("no sha and the PR is not in the checkout's log", surl(9), "", "is not merged")):
        try: server._released(pr, sha=sha); check(f"foreign refused: {name}", False)
        except server.ToolError as e: check(f"foreign refused: {name}", want in str(e) and str(e).startswith("Refused:"), str(e))
    check("…none of them wrote or told anything", not fsame(f0) and len(pushes()) == p0, (fsame(f0), pushes()[p0:]))
    r = server._released(surl(7), sha=SIBM[7][:7])
    rows = {x["item"]: x for x in r["items"]}
    check("foreign released: the PR given by URL, by a bare #7 on an item anchored to it, and with a step after it settle as this repository's do",
          rd(30)["status"] == "completed" and rd(31)["status"] == "completed" and rows.get("a30", {}).get("action") == "closed" and rows.get("a31", {}).get("action") == "closed"
          and rows.get("a34", {}).get("action") == "ticked" and rd(34)["metadata"].get("next") == "home-builder: then check the pages" and len(pushes_for("a34")) == 1, (rows, rd(34)["metadata"]))
    check("…the reason names the sibling's PR and its live checkout, and says nothing of main's tests", rd(30)["metadata"]["reason"].startswith(f"PR {SIB}#7 is live (merged at {SIBM[7][:7]} on ")
          and "in the checkout at " in rd(30)["metadata"]["reason"] and "main's tests" not in rd(30)["metadata"]["reason"], rd(30)["metadata"])
    check("…the notice to the mover names the PR with its repository", "PR example-owner/sibling#7 is live; its step is ticked" in pushes_for("a34")[0][1] and "main's tests" not in pushes_for("a34")[0][1], pushes_for("a34"))
    check("…a bare #7 on an item not anchored to the sibling's PR is this repository's #7: untouched; the PR that is not deployed stays open", raw(32) == f0[32] and raw(33) == f0[33] and "a32" not in rows and "a33" not in rows, rows)
    p1 = len(pushes()); r = server._released(surl(7), sha=SIBM[7])
    check("foreign released again: nobody is told twice", not [x for x in r["items"] if x["action"] in ("closed", "ticked", "told")] and len(pushes()) == p1, (r, pushes()[p1:]))
    ffix(); f0 = fsnap()
    r = server._released(surl(7), sha="")
    check("foreign released with no sha: the merge is found in the checkout's log and the items settle", rd(30)["status"] == "completed" and rd(31)["status"] == "completed" and r["sha"] == SIBM[7], (r, rd(30)["status"]))
    ffix(); f0 = fsnap(); p1 = len(pushes())
    d = server._sweep_proofs()
    acts = {x["item"]: x["action"] for x in d["items"] if x.get("kind") == "pr_released"}
    check("the clock's catch-up (a release the call missed): the sibling's PR given by URL, or by a bare #7 on an item anchored to it, is settled; a bare #7 on an unanchored item and a PR not deployed are not",
          acts.get("a30") == "closed" and acts.get("a40") == "closed" and acts.get("a41") == "closed" and acts.get("a34") == "ticked" and "a42" not in acts and "a33" not in acts and "a32" not in acts
          and raw(33) == f0[33] and raw(42) == f0[42] and raw(32) == f0[32], (acts, d["items"]))
    # a step's proof: pr_released for a listed repository is accepted, for another is refused naming the listed ones
    cl = server._steps.view({"next": "home-builder: restart the unit"}, keeper="")
    meta = {}; note = server._step_proof_set(meta, cl, [{"step": 1, "proof": f"pr_released {SIB}#8"}])
    check("step_proof: pr_released for a listed repository's PR is stored", meta.get("step_proof") == {"home-builder: restart the unit": f"pr_released {SIB}#8"} and "step 1 proof: pr_released" in note, (meta, note))
    try: server._step_proof_set({}, cl, [{"step": 1, "proof": "pr_released other-owner/else#3"}]); check("step_proof: pr_released for an unlisted repository is refused", False)
    except server.ToolError as e: check("step_proof: pr_released for an unlisted repository is refused, naming the listed one and pr_merged", "pr_released is for this repository's pull requests" in str(e) and SIB in str(e) and "use pr_merged" in str(e), str(e))
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
    server._cfg.CFG["github"] = {"moved": {"old-owner/sibling": SIB}}      # a moved repository's name is compared as the other checks do
    try:
        check("the table is read through [github.moved]: the old name reaches the same checkout", server._released_foreign("Old-Owner/Sibling") == SC, server._cfg.released_repos())
    finally:
        server._cfg.CFG.pop("github", None)
finally:
    server._cfg.CFG.pop("released", None)
ffix(); f0 = fsnap()
try: server._released(surl(7), sha=SIBM[7]); check("with the table gone again the feature is off: refused", False)
except server.ToolError as e: check("with the table gone again the feature is off: refused, nothing written", "none is configured" in str(e) and not fsame(f0), str(e))
drain()

sent = []
client.post = lambda what, body, timeout=30.0: (sent.append((what, body)), (200, {"pr": PR, "head": "abcdef1234", "good": "600d000aaa", "items": [
    {"item": "a1", "action": "closed", "reason": "PR #41 is live (x) and main's tests passed", "subject": "[home] item 1", "pr": 41},
    {"item": "a2", "action": "ticked", "told": "home-builder", "subject": "[home] item 2", "pr": 41},
    {"item": "a25", "action": "ticked", "told": "", "quiet": True, "mover": "home-builder", "subject": "[home] item 25", "pr": 41},
    {"item": "a16", "action": "told", "told": "home-builder", "subject": "[home] item 16", "pr": 41},
    {"item": "a3", "action": "left", "why": "on hold", "subject": "[home] item 3", "pr": 41},
    {"item": "a14", "action": "left", "why": "its needs name home-third, not its mover", "subject": "[home] item 14", "pr": 41}]}))[1]
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "released", "--pr", PR, "--sha", "0606060"])
check("client.py released posts the PR and the merge", rc == 0 and sent[-1] == ("released", {"pr": PR, "sha": "0606060", "dry_run": False}), sent)
check("…and prints one line per item, a skipped one with why (release.sh logs these lines)", buf.getvalue().splitlines() == [
    "stackshot: PR #41: closed a1 (outcome done: PR #41 is live (x) and main's tests passed) — [home] item 1",
    "stackshot: PR #41: ticked the release step of a2 and told its mover home-builder that the item's other open steps remain — [home] item 2",
    "stackshot: PR #41: ticked the release step of a25 (every other open step releases another PR: nobody told) — [home] item 25",
    "stackshot: PR #41: told the mover home-builder of a16 that the PR is live and its release step is not ticked (it names a follow-up or a condition, so the step stays open) — [home] item 16",
    "stackshot: PR #41: left a3 alone: on hold — [home] item 3",
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
check("the update/create check text says exactly which steps count", "`release PR #<n>`, `release #<n>`, or `release` before the PR's URL" in server._CHECK_FORM
      and "only mentions the PR" in server._CHECK_FORM)

print(f"{len(ran) - len(fails)}/{len(ran)} passed" + (f" — FAILED: {', '.join(fails)}" if fails else ""))
sys.exit(1 if fails else 0)
