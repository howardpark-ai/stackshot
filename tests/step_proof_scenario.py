"""Scenario test for a step that names the event which finishes it (step_proof.py, server._proof_item / _sweep_proofs / _proof_tick, the step_proof parameter, client.py
sweep-step-proof, tools/backfill_step_proof.py) — fixture data, no live store, no network (GitHub's answers are a table).

Covers: the patterns for a step's words (release / merge phrases, pure or with a follow-up, negations, gates, mentions that never match); the explicit form (update and create take
step_proof, stored under the step, refused for a step that is not open, his own step, a release of another repository's PR, a bad proof); the events (a PR released: its merge in last-good
and HEAD; a PR merged: in git or GitHub says so; one closed unmerged or unreadable ticks nothing); the settling (a pure step is ticked by the server and the History says so, the mover is told
the next open step once, a follow-up or a gate tells the mover once and ticks nothing, the last open step closes the item as a release does, held / decision / other-session items are
left alone, his own step is never ticked, an event seen twice ticks once); the dry run and the backfill tool, which write nothing; the client verb and the route.

    tests/run-suite step_proof        → exit 0 / 1"""
import json, os, re, sys, pathlib, subprocess, time, logging, io, contextlib, shutil
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="stepprooftest-"); T = pathlib.Path(tmp)
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
AGENTS = {"projects/alpha": {"home-builder": "the front"}}     # home-builder is alpha's front agent: its notices pass the front gate
(T / "store/projects.json").write_text(json.dumps({"pages": {p: {"title": p[9:].title(), "name": p[9:].title(), "org": "home", "tags": [], "type": "project",
                                                                 "session": "home-builder", "status": "active", "board": [], "board_open": 0,
                                                                 "agents": AGENTS[p], "back_agents": {}}
                                                             for p in AGENTS}}))
for p in AGENTS:
    k = p[9:]
    (T / f"brain/projects/{k}.md").write_text(f"---\ntitle: {k.title()}\nagents:\n" + "".join(f"  {a}: {r}\n" for a, r in AGENTS[p].items()) + f"---\n\n# {k.title()}\n")
REPO = "example-owner/stackshot"
def url(n, repo=REPO): return f"https://github.com/{repo}/pull/{n}"
def key(n, repo=REPO): return f"{repo}#{n}"

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

sys.path.insert(0, STACK)
from stackshot.model import step_proof as SP

# ---- 1. what a step's words say (step_proof.py): pure functions
def kinds(text): return [(p.kind, p.n or p.url, p.pure, p.via) for p in SP.text_proofs(text)]
R, M = SP.PR_RELEASED, SP.PR_MERGED
for text, want in (
        ("release PR #29", [(R, 29, True, "release")]),
        ("release #29", [(R, 29, True, "release")]),
        ("Release Pull Request #29.", [(R, 29, True, "release")]),
        ("release #29 (in its turn)", [(R, 29, True, "release")]),
        ("release #29 (after #37)", [(R, 29, False, "release"), (R, 37, False, "gate")]),
        ("home-builder: release PR #29", [(R, 29, True, "release")]), ("x (builder): release #29 (in its turn).", [(R, 29, True, "release")]), ("no-op-agent: merge #29", [(M, 29, True, "merge")]),
        ("- **home-builder:** release PR #29", [(R, 29, True, "release")]),
        ("release PR #38 after release PR #29", [(R, 38, False, "release"), (R, 29, False, "release")]), ("release PR #29, release PR #38", [(R, 29, False, "release"), (R, 38, False, "release")]),
        ("something else first, release PR #29", [(R, 29, False, "release")]), ("release PR #29\n- the details", [(R, 29, False, "release")]),
        ("home-builder: Decide whether to release PR #29", []), ("do not yet release PR #29", []), ("cannot release PR #29", []), ("Do NOT, until Friday, release PR #29", []),
        ("we should release #29", []), ("can't merge #29 yet", []), ("without a merge of #29 first, merge #38", []),
        ("release https://github.com/o/r/pull/29", [(R, "https://github.com/o/r/pull/29", True, "release")]),
        ("merge PR #29", [(M, 29, True, "merge")]),
        ("merge #29.", [(M, 29, True, "merge")]),
        ("merge https://github.com/o/r/pull/29 (in turn)", [(M, "https://github.com/o/r/pull/29", True, "merge")]),
        ("release PR #29 and verify the pages", [(R, 29, False, "release")]),
        ("release PR #29, restart x", [(R, 29, False, "release")]),
        ("release #29 - check prod", [(R, 29, False, "release")]),
        ("release #29 (needs an ok)", [(R, 29, False, "release")]),
        ("merge PR #29, then release it", [(M, 29, False, "merge")]),
        ("release #29 after #37", [(R, 29, False, "release"), (R, 37, False, "gate")]),
        ("once #29 is released, run the audit", [(R, 29, False, "gate")]),
        ("when PR #29 is merged, announce it", [(M, 29, False, "gate")]),
        ("after #29 lands, tell the team", [(M, 29, False, "gate")]),
        ("until PR #29 is live, wait", [(R, 29, False, "gate")]),
        ("release it after #29", [(R, 29, False, "gate")]),
        ("as soon as https://github.com/o/r/pull/29 is merged, go", [(M, "https://github.com/o/r/pull/29", False, "gate")]),
        ("do not release PR #29 yet", []), ("don't release #29", []), ("pre-release #29", []), ("never merge #29", []), ("without merge #29", []),
        ("review PR #29", []), ("verify #29 is released", []), ("investigate why PR #29 was merged", []), ("release notes for #29", []),
        ("check after #29", []), ("merge main into the branch", []), ("released #29", []), ("the merge of #29", []), ("", [])):
    check(f"words {text!r}", kinds(text) == want, kinds(text))
check("hits match the number or the URL's key, only for the kind asked",
      SP.hits(SP.text_proofs("release PR #29"), R, 29, "o/r#29", lambda u: "") != [] and SP.hits(SP.text_proofs("release PR #29"), M, 29, "o/r#29", lambda u: "") == []
      and SP.hits(SP.text_proofs("release PR #29"), R, 38, "o/r#38", lambda u: "") == []
      and SP.hits(SP.text_proofs("release https://github.com/o/r/pull/29"), R, 29, "o/r#29", lambda u: "o/r#29") != []
      and SP.hits(SP.text_proofs("release https://github.com/o/r/pull/29"), R, 29, "o/q#29", lambda u: "o/r#29") == [])
check("pure_step: the phrase is all the step does", SP.pure_step(SP.text_proofs("release PR #29 (in its turn)"), R, 29, "o/r#29", lambda u: "")
      and not SP.pure_step(SP.text_proofs("release PR #29, then x"), R, 29, "o/r#29", lambda u: "") and not SP.pure_step(SP.text_proofs("once #29 is released, x"), R, 29, "o/r#29", lambda u: ""))
check("other_pure: a pure proof of another PR, never a gate", SP.other_pure(SP.text_proofs("merge PR #5"), R, 29, "o/r#29", lambda u: "")
      and not SP.other_pure(SP.text_proofs("once #5 is released, x"), R, 29, "o/r#29", lambda u: "") and not SP.other_pure(SP.text_proofs("release PR #29"), R, 29, "o/r#29", lambda u: ""))
check("the spec: a list, a JSON string, one dict, none, nothing",
      SP.parse_spec([{"step": 1, "proof": "pr_merged #5"}]) == [(1, "pr_merged #5")] and SP.parse_spec('[{"step": "a b", "proof": " pr_merged   #5 "}]') == [("a b", "pr_merged #5")]
      and SP.parse_spec({"step": 2, "proof": "none"}) == [(2, "none")] and SP.parse_spec("none") == [] and SP.parse_spec(None) is None and SP.parse_spec("  ") is None)
for bad in ("{", [{"step": 1}], [{"proof": "pr_merged #5"}], [3], 7):
    try: SP.parse_spec(bad); check(f"the spec {bad!r} is refused", False)
    except SP.ProofError as e: check(f"the spec {bad!r} is refused with the form", "step_proof=[" in str(e), str(e))
check("a proof as written", SP.split_proof("PR_Merged #5") == ("pr_merged", "#5") and SP.split_proof("none") == ("none", "") and SP.read_stored("pr_released o/r#5") == ("pr_released", "o/r#5") and SP.read_stored("x") == ("", ""))
for bad in ("pr_merged", "merged #5", "pr_merged a b"):
    try: SP.split_proof(bad); check(f"the proof {bad!r} is refused", False)
    except SP.ProofError as e: check(f"the proof {bad!r} is refused", "pr_merged <owner>/<repo>#<n>" in str(e), str(e))


# ---- 2. the store, the checkout and GitHub's answers
def item(i, nxt, project="projects/alpha", status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing. It lives here. Done when done.",
                                                       "status": status, "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                       "metadata": {"owner": U["home-builder"], "mover": U["home-builder"], "project": project, "next": nxt, **meta}}))

from stackshot.web import server
from stackshot.service import telling
OWNER = server.OWNER
OTHER = "other-owner/other"
ALL = range(1, 27)
def fixtures():
    for f in (T / "store/a").glob("*.json"): f.unlink()
    item(1, "home-builder: merge PR #39")                                                          # merged on GitHub (not in git): the only step, closes
    item(2, "home-builder: merge PR #39\nhome-builder: then check the pages")                     # ticked; the mover is told the next step
    item(3, "home-builder: merge PR #39 and release it")                                          # a follow-up: not ticked, told
    item(4, "home-builder: merge PR #40")                                                          # closed unmerged: never ticked
    item(5, "home-builder: merge PR #41")                                                          # GitHub cannot read it: nothing
    item(6, "home-builder: merge PR #39")                                                          # not anchored, no URL: could be another repository's #39
    item(7, f"home-builder: merge {url(7, OTHER)}")                                                # another repository's PR by its URL: counts anywhere
    item(8, "home-builder: investigate PR #39\nhome-builder: review PR #39 before the merge")     # mentions only
    item(9, "home-builder: restart the unit\nhome-builder: check the pages", step_proof={"home-builder: restart the unit": f"pr_released {key(42)}"})    # explicit release proof on a step with other words
    item(10, "home-builder: once #42 is released, run the audit")                                  # a gate, on an item anchored to another PR of the repository
    item(11, "home-builder: release it after #42")                                                 # a gate by "release ... after #n"
    item(12, "home-other: release PR #42")                                                         # another session's step: ticked when its proof arrives
    item(13, f"{OWNER}: release PR #42")                                                           # his own step: never ticked by an event
    item(14, "home-builder: release PR #42\nhome-builder: merge PR #39")                           # two pure proofs: ticked quietly, then the item closes
    item(15, "home-builder: do not merge PR #39 yet\nhome-builder: pre-merge #39\nhome-builder: don't merge #39")    # negated: never
    item(16, "home-builder: merge PR #39", hold=True, wake="2099-01-02")                           # on hold
    item(17, "home-builder: when PR #39 is merged, announce it")                                   # a gate on a merge
    item(18, "home-builder: verify PR #42 is released\nhome-builder: write the release notes for #42")    # words that are no proof
    item(19, "home-builder: merge PR #39", status="completed", outcome="done", reason="earlier")   # closed already
    item(20, "home-builder: wait for their fix\nhome-builder: update our docs", step_proof={"home-builder: wait for their fix": f"pr_merged {key(7, OTHER)}"})    # explicit, another repository
    item(21, "home-builder: wait for the fix", step_proof={"home-builder: wait for the fix": f"pr_merged {key(40)}"})        # explicit, closed unmerged
    item(22, "home-builder: merge PR #39", needs=["decision"], ask="Ship it?")                      # waits on the owner's decision
    item(23, "home-builder: merge PR #39", needs=["home-third"])                                     # needs a session other than its mover
    item(24, "home-builder: release PR #43")                                                       # merged after last-good: main's run still going
    item(25, "home-builder: merge PR #43")                                                         # merged in HEAD (git says so, GitHub is not asked)
    item(26, "home-builder: wait for the unit\nhome-builder: check the pages", step_proof={"home-builder: wait for the unit": f"pr_released {key(43)}"})    # explicit release, not yet live
    (T / "store/next-id").write_text("60")
    anc = lambda n, *ids: {"url": url(n), "items": [f"a{i}" for i in ids], "added": 1, "by": "t"}
    (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [
        anc(39, 1, 2, 3, 8, 14, 15, 16, 17, 19, 22, 23), anc(40, 4), anc(41, 5), anc(42, 12, 13, 14, 18), anc(44, 10, 11), anc(43, 24, 25)]}))

genv = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": tmp}
def g(*a): return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=T / "repo", env=genv, capture_output=True, text=True, check=True).stdout.strip()
(T / "repo").mkdir(); g("init", "-q", "-b", "main"); (T / "repo/f").write_text("0"); g("add", "f"); g("commit", "-qm", "base")
g("remote", "add", "origin", f"https://github.com/{REPO}.git")
MS = {}
for n in (42, 45, 43):
    g("checkout", "-qb", f"topic{n}"); (T / "repo/f").write_text(str(n)); g("commit", "-qam", f"change {n}")
    g("checkout", "-q", "main"); g("merge", "-q", "--no-ff", "-m", f"Merge pull request #{n} from example-owner/topic{n}", f"topic{n}"); MS[n] = g("rev-parse", "HEAD")
LAST_GOOD = T / "state/releases/last-good"
LAST_GOOD.write_text(MS[45] + "\n")                        # #42 and #45 are live; #43 is merged after last-good (main's run on it still going)

fixtures()
logging.disable(logging.INFO)
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def raw(i): return (T / f"store/a/{i}.json").read_text()
def snap(): return {i: raw(i) for i in ALL}
def same(s): return [i for i in s if raw(i) != s[i]]
server._publish = lambda: None
server._OWN_REPO[:] = [REPO]
server._HERE = T / "repo"
GH = {key(39): ("merged", ""), key(40): ("dead", ""), key(41): ("err", "GitHub refused the read (404)"), key(7, OTHER): ("merged", "")}
GH_CALLS = []; GH_TAGS = []
from stackshot.core import ghbudget as _gbud
def fake_pr_merged(ref, now_, gh_st):
    ref = server._check_ref(ref); st, err = GH.get(ref, ("open", "")); GH_CALLS.append(ref); GH_TAGS.append(_gbud.current())     # the ledger tag in force while the PR is read
    gh_st[ref] = {"next": now_ + 300, "back": 0.0, "err": err, "merged": st == "merged", **({"dead": "its pull request was closed without being merged"} if st == "dead" else {})}
    return st == "merged", err
REAL_PR_MERGED = server._pr_merged
server._pr_merged = fake_pr_merged
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []
_real_tell = telling.tell_woken
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
check("his own step reads as his, a session's does not", server._steps.is_his(f"{OWNER}: release PR #42", unnamed_is_his=False) and not server._steps.is_his("home-builder: release PR #42", unnamed_is_his=False))

# ---- 3. the dry run first: lists what it would do, writes nothing, tells nobody
s0 = snap(); p0 = len(pushes())
d = server._sweep_proofs(dry=True)
acts = {}
for x in d["items"]: acts.setdefault(x["item"], []).append((x["pr"], x["kind"], x["action"]))
check("the dry run lists, per item, what the server would do",
      acts == {"a1": [(39, M, "closed")], "a2": [(39, M, "ticked")], "a3": [(39, M, "told")], "a4": [(40, M, "told")], "a7": [(7, M, "closed")],
               "a9": [(42, R, "ticked")], "a10": [(42, R, "told")], "a11": [(42, R, "told")], "a12": [(42, R, "closed")],
               "a14": [(39, M, "ticked"), (42, R, "ticked")], "a16": [(39, M, "left")], "a17": [(39, M, "told")], "a20": [(7, M, "ticked")], "a21": [(40, M, "told")],
               "a22": [(39, M, "left")], "a23": [(39, M, "left")], "a25": [(43, M, "closed")]}, acts)
check("…writes nothing and tells nobody", not same(s0) and len(pushes()) == p0, (same(s0), pushes()[p0:]))
check("…and the dry run still reads GitHub for what git cannot answer (this repository's #43 is in git: not asked)", key(43) not in GH_CALLS and key(39) in GH_CALLS and key(41) in GH_CALLS, GH_CALLS)
check("…the answers are not kept on a dry run", not (T / "state/step-proof.json").exists())

# ---- 4. the real pass: ticks, closes, tells
GH_CALLS.clear()
d = server._sweep_proofs()
rows = {}
for x in d["items"]: rows.setdefault(x["item"], []).append(x)
a1 = rd(1)
check("the only open step is a merged PR's merge: the item closes, outcome done, the reason names the PR and where it was seen",
      a1["status"] == "completed" and a1["metadata"].get("outcome") == "done" and a1["metadata"]["reason"] == "PR #39 is merged (merged on GitHub)"
      and [(s["status"], s["by"]) for s in a1["metadata"].get("steps", [])] == [("done", server.NAME)] and "next" not in a1["metadata"] and "step_proof" not in a1["metadata"], a1["metadata"])
check("…nobody is told of a close", not pushes_for("a1"), pushes())
a2 = rd(2)
check("a step after it: the merge step is ticked done by the server, the step after it stays open",
      a2["status"] == "open" and a2["metadata"].get("next") == "home-builder: then check the pages"
      and [(s["text"], s["status"], s.get("by")) for s in a2["metadata"]["steps"]] == [("home-builder: merge PR #39", "done", server.NAME), ("home-builder: then check the pages", "open", None)], a2["metadata"])
n2 = pushes_for("a2")
check("…and its mover gets one real notice that names the next open step",
      len(n2) == 1 and n2[0][0] == U["home-builder"] and "PR #39 is merged; its step is ticked; the item's other open steps remain." in n2[0][1]
      and "Next step: home-builder: then check the pages." in n2[0][1], n2)
check("…the History says the step was ticked, by the server, with the event",
      any(re.search(r"step done: home-builder: merge PR #39 \(PR #39 is merged; ticked by " + re.escape(server.NAME) + r"\)", str(h)) for h in server._history_lines("a2")) if hasattr(server, "_history_lines") else True)
check("…the item is stamped with the merge it told", a2["metadata"].get("released_told") == [f"merged {key(39)}"], a2["metadata"])
a3 = rd(3)
check("a follow-up after the merge phrase: the step stays open and un-ticked, the mover is told once",
      a3["status"] == "open" and a3["metadata"].get("next") == "home-builder: merge PR #39 and release it" and rows.get("a3", [{}])[0].get("action") == "told"
      and len(pushes_for("a3")) == 1 and "its step is not ticked (it names a follow-up)" in pushes_for("a3")[0][1] and "PR #39 is merged" in pushes_for("a3")[0][1], (a3["metadata"], pushes_for("a3")))
a4 = rd(4)
check("a PR closed without a merge ticks nothing: the step stays open, the mover is told once to fix it, and the told mark is kept",
      a4["status"] == "open" and a4["metadata"].get("next") == "home-builder: merge PR #40" and [x["status"] for x in a4["metadata"].get("steps", [])] in ([], ["open"]) and rows["a4"][0]["action"] == "told"
      and rows["a4"][0]["dead"] == "its pull request was closed without being merged" and a4["metadata"].get("released_told") == [f"dead {key(40)}"]
      and len(pushes_for("a4")) == 1 and "PR #40 was closed without being merged, so its step \"home-builder: merge PR #40\" will never be ticked by it" in pushes_for("a4")[0][1], (rows.get("a4"), a4["metadata"], pushes_for("a4")))
a21 = rd(21)
check("…the same for an explicit proof, and `get` marks the proof dead in its step proof line",
      rows["a21"][0]["action"] == "told" and len(pushes_for("a21")) == 1 and f"1. home-builder: wait for the fix ← pr_merged {key(40)} (dead: that pull request was closed without being merged; reword or drop the step)" in server.stackshot_get("a21")
      and "the server ticks the step when it happens" not in server.stackshot_get("a21").split("step proof:")[1].split("\n")[0], server.stackshot_get("a21")[:1500])
check("a PR GitHub cannot read (refused, 404): nothing happens, not even a row", raw(5) == s0[5] and "a5" not in rows)
check("a bare #39 on an unanchored item without the URL: untouched (it could be another repository's)", raw(6) == s0[6] and "a6" not in rows)
a7 = rd(7)
check("another repository's PR by its URL counts anywhere: closed", a7["status"] == "completed" and a7["metadata"]["reason"] == f"PR {key(7, OTHER)} is merged (merged on GitHub)", a7["metadata"])
check("steps that only mention the PR (investigate, review): untouched", raw(8) == s0[8] and "a8" not in rows)
a9 = rd(9)
check("an explicit release proof on a step whose words name no PR: ticked when the PR is live, the proof goes with the step, the mover is told the next step",
      a9["status"] == "open" and a9["metadata"].get("next") == "home-builder: check the pages" and [s["status"] for s in a9["metadata"]["steps"]] == ["done", "open"]
      and "step_proof" not in a9["metadata"] and len(pushes_for("a9")) == 1 and "PR #42 is live; its step is ticked" in pushes_for("a9")[0][1] and "Next step: home-builder: check the pages." in pushes_for("a9")[0][1]
      and a9["metadata"].get("released_told") == [key(42)], (a9["metadata"], pushes_for("a9")))
for i, what in ((10, "once #42 is released, run the audit"), (11, "release it after #42")):
    ax = rd(i)
    check(f"a condition ({what}) on an item anchored to another PR of the repository: never ticked, the mover is told once that it is met",
          ax["status"] == "open" and ax["metadata"].get("next") == json.loads(s0[i])["metadata"]["next"] and [s["status"] for s in ax["metadata"].get("steps", [])] in ([], ["open"])
          and len(pushes_for(f"a{i}")) == 1 and "PR #42 is live" in pushes_for(f"a{i}")[0][1] and ax["metadata"].get("released_told") == [key(42)], (ax["metadata"], pushes_for(f"a{i}")))
a12 = rd(12)
check("another session's step is ticked when its proof arrives (the item closes: nothing else is open)", a12["status"] == "completed" and a12["metadata"]["reason"].startswith("PR #42 is live (merged at "), a12["metadata"])
check("his own step is never ticked by an event: untouched, not listed", raw(13) == s0[13] and "a13" not in rows)
a14 = rd(14)
check("two pure proofs of different PRs: the first is ticked with nobody told, the second closes the item",
      a14["status"] == "completed" and [r["action"] for r in rows["a14"]] == ["ticked", "closed"] and rows["a14"][0]["quiet"] is True and not pushes_for("a14")
      and [(s["text"], s["status"]) for s in a14["metadata"]["steps"]] == [("home-builder: release PR #42", "done"), ("home-builder: merge PR #39", "done")], (a14["metadata"], rows.get("a14")))
check("negated phrases are never proofs: untouched, not listed", raw(15) == s0[15] and "a15" not in rows)
check("held: left alone, with why", raw(16) == s0[16] and rows["a16"][0]["action"] == "left" and rows["a16"][0]["why"] == "on hold")
a17 = rd(17)
check("a condition on a merge (when PR #39 is merged, ...): not ticked, the mover is told once",
      a17["status"] == "open" and a17["metadata"].get("next") == "home-builder: when PR #39 is merged, announce it" and len(pushes_for("a17")) == 1 and "PR #39 is merged" in pushes_for("a17")[0][1], (a17["metadata"], pushes_for("a17")))
check("words that are no proof (verify ... is released, release notes): untouched", raw(18) == s0[18] and "a18" not in rows)
check("a closed item: untouched", raw(19) == s0[19])
a20 = rd(20)
check("an explicit pr_merged proof of another repository's PR: ticked, the mover told the next step",
      a20["status"] == "open" and a20["metadata"].get("next") == "home-builder: update our docs" and "Next step: home-builder: update our docs." in pushes_for("a20")[0][1] and f"PR {key(7, OTHER)} is merged" in pushes_for("a20")[0][1] and "step_proof" not in a20["metadata"], (a20["metadata"], pushes_for("a20")))
check("decision and other-session needs: left alone, each with why", raw(22) == s0[22] and raw(23) == s0[23] and "decision" in rows["a22"][0]["why"] and rows["a23"][0]["why"] == "its needs name home-third, not its mover", (rows.get("a22"), rows.get("a23")))
check("a PR in HEAD but not in last-good is merged, not released: the merge step closes (git answered, GitHub was not asked); the release step waits for last-good",
      rd(25)["status"] == "completed" and rd(24)["status"] == "open" and rd(26)["status"] == "open" and "a24" not in rows and "a26" not in rows and key(43) not in GH_CALLS, (rows.get("a25"), GH_CALLS))
check("the GitHub answers are kept for the next pass (one read per PR, not per item)", (T / "state/step-proof.json").exists() and GH_CALLS.count(key(39)) == 1, GH_CALLS)
# the item's activity clock (activity.py): the fixtures are items from before the field, last touched an hour ago; each of the three saves the pass makes on an anchor's event moves it to now
check("activity: the close on a merged PR moves the item's activity clock (the item had none: it was last touched an hour ago)", rd(1).get("activity", 0) >= now, rd(1).get("activity"))
check("activity: the tick of a step moves it", rd(2).get("activity", 0) >= now, rd(2).get("activity"))
check("activity: the told-the-mover save (a follow-up step stays open) moves it", rd(3).get("activity", 0) >= now, rd(3).get("activity"))
check("activity: the told-once save of a PR closed without a merge moves it", rd(4).get("activity", 0) >= now, rd(4).get("activity"))
check("activity: an item the pass left alone has no clock written", "activity" not in rd(22), rd(22).get("activity"))

# ---- 5. an event seen twice ticks once, tells once
p1 = len(pushes()); s1 = snap()
d = server._sweep_proofs()
check("a second pass: nothing ticked or closed, no second notice, the told items left with why",
      not [x for x in d["items"] if x["action"] in ("closed", "ticked")] and len(pushes()) == p1
      and {x["item"]: x["why"] for x in d["items"] if x["action"] == "left"}.get("a3") == "its mover was told already that PR #39 is merged", d["items"])
check("…and nothing is changed on disk", not same(s1), same(s1))
LAST_GOOD.write_text(MS[43] + "\n")
d = server._sweep_proofs()
check("last-good moves to #43's merge: the release steps settle (the item whose only step is the release closes; the explicit one ticks)",
      rd(24)["status"] == "completed" and rd(26)["metadata"].get("next") == "home-builder: check the pages" and [s["status"] for s in rd(26)["metadata"]["steps"]] == ["done", "open"], (rd(24)["status"], rd(26)["metadata"]))
LAST_GOOD.write_text(MS[45] + "\n")

# ---- 6. release.sh's call settles the same steps, explicit ones included
fixtures(); p0 = len(pushes())
r = server._released(url(42), sha=MS[42])
rr = {x["item"]: x for x in r["items"]}
check("released: the explicit proof ticks and the plain 'release PR #n' steps close, as before; merge steps and other PRs' are not touched",
      rr.get("a9", {}).get("action") == "ticked" and rr.get("a12", {}).get("action") == "closed" and rr.get("a14", {}).get("action") == "ticked" and "a1" not in rr and "a13" not in rr
      and rd(9)["metadata"].get("next") == "home-builder: check the pages" and raw(1) == json.dumps(json.loads(raw(1))), rr)
check("…its rows say which event", all(x.get("kind") == R for x in r["items"]), r["items"])
fixtures()

# ---- 7. the pass: _proof_tick is throttled and settles
server._PROOF_LAST[0] = 0.0
s_t = snap(); p_t = len(pushes())
done = server._proof_tick(now + 1)
check("the first pass of the clock only logs: it writes and tells nothing, keeps what it would do, and marks itself done",
      done == [] and not same(s_t) and len(pushes()) == p_t and (T / "state/step-proof-dry.json").exists() and server._proof_state().get("dry_logged")
      and {x["item"] for x in json.loads((T / "state/step-proof-dry.json").read_text())["items"]} >= {"a1", "a2", "a9"}, (done, same(s_t)))
check("…the pass after it acts: it settles what the sweep would (the ids of the closed, ticked and told)", server._proof_tick(now + 2) == [] and not same(s_t))
done = server._proof_tick(now + 1 + server._PROOF_EVERY + 1)
check("…once its interval has passed", "a1" in done and "a2" in done and "a3" in done and rd(1)["status"] == "completed", done)
_cfg_get = server._cfg.get
def with_switch(v):
    server._cfg.get = lambda *k, **kw: ({} if v is None else {"live": v}) if k == ("step_proof",) else _cfg_get(*k, **kw)
fixtures(); (T / "state/step-proof.json").unlink(); s_t = snap()
with_switch(False); server._PROOF_LAST[0] = 0.0
server._proof_tick(now + 1); server._PROOF_LAST[0] = 0.0; server._proof_tick(now + 2)
check("[step_proof] live = false: the clock never acts, however many passes, and never marks its first pass as done", not same(s_t) and not server._proof_state().get("dry_logged") and not server._proof_live())
with_switch(True); server._PROOF_LAST[0] = 0.0
done = server._proof_tick(now + 3)
check("[step_proof] live = true: the very first pass acts", "a1" in done and rd(1)["status"] == "completed", done)
with_switch(None); fixtures()
check("…the tick is one of the runner's clocks, in its settle group", [t.group for t in server._minute_ticks() if t.name == "proof_tick"] == ["settle"])
fixtures()

# ---- 8. writing the proof: update and create take step_proof
def upd(i, **kw): return server._update(f"a{i}", sender="home-builder", **kw)
def refused(name, fn, *want):
    try: fn(); check(name, False)
    except server.ToolError as e: check(name, str(e).startswith("Refused:") and all(w in str(e) for w in want), str(e))
item(30, "home-builder: restart the unit\nhome-builder: merge PR #39\nhome-builder: check the pages")
out = upd(30, step_proof=[{"step": 1, "proof": "pr_released #45"}, {"step": "home-builder: check the pages", "proof": f"pr_merged {url(7, OTHER)}"}])
m30 = rd(30)["metadata"]
check("update stores the proofs under the steps' keys, as 'kind owner/repo#n', and says so",
      m30.get("step_proof") == {"home-builder: restart the unit": f"pr_released {key(45)}", "home-builder: check the pages": f"pr_merged {key(7, OTHER)}"}
      and f"(step 1 proof: pr_released {key(45)}" in out and f"(step 3 proof: pr_merged {key(7, OTHER)}" in out, (m30, out))
check("get shows them under 'step proof:'", f"step proof: 1. home-builder: restart the unit ← pr_released {key(45)}; 3. home-builder: check the pages ← pr_merged {key(7, OTHER)} (the server ticks the step when it happens)" in server.stackshot_get("a30"), server.stackshot_get("a30")[:1500])
upd(30, step_proof=[{"step": 1, "proof": "none"}])
check("a proof of 'none' clears that step's", rd(30)["metadata"].get("step_proof") == {"home-builder: check the pages": f"pr_merged {key(7, OTHER)}"}, rd(30)["metadata"])
upd(30, step_proof="none")
check('step_proof="none" clears them all', "step_proof" not in rd(30)["metadata"], rd(30)["metadata"])
upd(30, step_proof='[{"step": 2, "proof": "pr_merged ' + url(39) + '"}]')
check("a JSON string and a PR URL work, the repository goes through the same canonical name", rd(30)["metadata"].get("step_proof") == {"home-builder: merge PR #39": f"pr_merged {key(39)}"}, rd(30)["metadata"])
upd(30, done=[1])
check("marking a step done leaves other steps' proofs alone; a proof goes with a step that is no longer open",
      rd(30)["metadata"].get("step_proof") == {"home-builder: merge PR #39": f"pr_merged {key(39)}"}, rd(30)["metadata"])
upd(30, done=[2])
check("…done on the step takes its proof", "step_proof" not in rd(30)["metadata"], rd(30)["metadata"])
item(31, "home-builder: restart the unit\nhome-builder: check the pages")
upd(31, step_proof=[{"step": 1, "proof": "pr_merged #39"}])
upd(31, next="home-builder: restart the unit and the proxy\nhome-builder: check the pages", done=[1])
check("a reworded step is a new step: the old one is marked and its proof goes", "step_proof" not in rd(31)["metadata"], rd(31)["metadata"])
refused("a step that is not found", lambda: upd(30, step_proof=[{"step": "no such step", "proof": "pr_merged #5"}]), "no open step reads")
refused("a position that is not there", lambda: upd(31, step_proof=[{"step": 9, "proof": "pr_merged #5"}]), "there is no step 9")
refused("a step that is not open", lambda: upd(30, step_proof=[{"step": 1, "proof": "pr_merged #5"}]), "already done")
refused("a proof that is neither kind", lambda: upd(31, step_proof=[{"step": 2, "proof": "pr_closed #5"}]), "pr_merged <owner>/<repo>#<n>")
refused("a PR that is not a PR", lambda: upd(31, step_proof=[{"step": 2, "proof": "pr_merged nonsense"}]), "is not a pull request")
refused("a release of another repository's PR", lambda: upd(31, step_proof=[{"step": 2, "proof": f"pr_released {key(7, OTHER)}"}]), "pr_released is for this repository's pull requests", "use pr_merged")
refused("a list that is not a list of steps and proofs", lambda: upd(31, step_proof="[3]"), "each step_proof entry names a step and its proof")
item(32, f"{OWNER}: pick the colour\nhome-builder: check the pages")
refused("his own step takes no proof", lambda: upd(32, step_proof=[{"step": 1, "proof": "pr_merged #5"}]), "is the owner's own step" if OWNER == "the owner" else "own step", "ticked by his answer")
check("nothing above wrote a proof", all("step_proof" not in rd(i)["metadata"] for i in (31, 32)), (rd(31)["metadata"], rd(32)["metadata"]))
item(33, "home-builder: merge PR #39", status="completed", outcome="done", reason="earlier")
refused("a closed item's checklist is the record", lambda: upd(33, step_proof=[{"step": 1, "proof": "pr_merged #5"}]), "is closed and its checklist is the record")
out = server._create(subject="[home] made with a proof", description="- A thing. It lives here. Done when done.", project="projects/alpha", owner="home-builder", mover="home-builder",
                     next="home-builder: confirm their fix\nhome-builder: update the docs", step_proof=[{"step": 1, "proof": f"pr_merged {url(7, OTHER)}"}])
gid = re.search(r"created (\S+)", out).group(1)
mc = json.loads((T / f"store/{gid[0]}/{gid[1:]}.json").read_text())["metadata"]
check("create takes step_proof for the steps of its next", mc.get("step_proof") == {"home-builder: confirm their fix": f"pr_merged {key(7, OTHER)}"} and f"(step 1 proof: pr_merged {key(7, OTHER)}" in out, (mc, out))
refused("create refuses a proof for a step that is not there", lambda: server._create(subject="[home] bad proof", description="- A thing. It lives here. Done when done.", project="projects/alpha", owner="home-builder", mover="home-builder",
                                                                                     next="home-builder: do x", step_proof=[{"step": 4, "proof": "pr_merged #5"}]), "there is no step 4")
upd(30, status="open")
item(34, "home-builder: restart the unit", step_proof={"home-builder: restart the unit": f"pr_merged {key(7, OTHER)}"})
upd(34, status="completed", outcome="done", reason="finished by hand", description="- Finished by hand. Nothing is left to do.")
check("a close takes the proofs with the steps", "step_proof" not in rd(34)["metadata"], rd(34)["metadata"])

# ---- 8b. what a pass costs and what it says twice
fixtures(); GH.update({key(46): ("merged", "")})
item(27, "home-builder: merge PR #46")                                    # a bare #n on an item with no anchor and no URL: it can never match
item(28, "home-builder: merge PR #39\nhome-builder: check the pages", owner=OWNER, mover=OWNER)      # nobody to send a notice to
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": url(39), "items": ["a28", "a3", "a16"], "added": 1, "by": "t"}]}))
_holder0 = telling.holder
telling.holder = lambda it, was=None: "" if str(it.get("id")) == "28" else _holder0(it, was)      # an item whose holder cannot be named
GH_CALLS.clear(); server._PROOF_LOGGED.clear()
try:
    d = server._sweep_proofs()
finally:
    telling.holder = _holder0
check("a bare pull request number that no step of its item can match makes no event and no GitHub read", key(46) not in GH_CALLS and "a27" not in {x["item"] for x in d["items"]} and raw(27) == json.dumps(json.loads(raw(27))), GH_CALLS)
a28 = rd(28)
check("an item with no holder: its step is ticked, the told mark is recorded all the same, nobody is told",
      a28["metadata"].get("released_told") == [f"merged {key(39)}"] and [x["status"] for x in a28["metadata"]["steps"]] == ["done", "open"] and not pushes_for("a28"), a28["metadata"])
GH_CALLS.clear(); s_n = snap(); p_n = len(pushes())
d = server._sweep_proofs()
check("the second pass changes nothing, tells nothing, and rereads no GitHub answer that can no longer change (merged, closed unmerged)",
      not same(s_n) and len(pushes()) == p_n and not [k for k in GH_CALLS if k in (key(39), key(40), key(7, OTHER))], (same(s_n), GH_CALLS))
check("…its rows for the dead PR and the told follow-up say so",
      {x["item"]: x["why"] for x in d["items"] if x["action"] == "left"}.get("a21") == f"its mover was told already that PR #40 was closed without a merge", d["items"])
# the log: one "left alone" line per item and reason
import contextlib, io as _io
err = _io.StringIO(); server._PROOF_LOGGED.clear()
with contextlib.redirect_stderr(err):
    server._sweep_proofs(); server._sweep_proofs(); server._sweep_proofs()
check("a held item is logged as left alone once, not every pass", err.getvalue().count("released: a16 left alone for PR #39: on hold") == 1, err.getvalue()[-600:])
# the cost: git is read only for the pull requests some open step waits on, and kept by commit
calls = {"prs": 0, "live": 0, "base": 0}
_mp, _live, _base = server._merged_prs, server._released_is_live, server._released_live_base
server._merged_prs = lambda *a, **k: (calls.__setitem__("prs", calls["prs"] + 1), _mp(*a, **k))[1]
server._released_is_live = lambda *a, **k: (calls.__setitem__("live", calls["live"] + 1), _live(*a, **k))[1]
server._released_live_base = lambda *a, **k: (calls.__setitem__("base", calls["base"] + 1), _base(*a, **k))[1]
try:
    fixtures(); server._PROOF_GIT.clear()
    server._sweep_proofs(dry=True)
    c1 = dict(calls)
    check("a pass reads the merges of last-good and HEAD once, and asks 'is it live' only for the pull requests an open step releases (#42 and #43), not for every merge",
          c1["prs"] <= 3 and c1["live"] <= 2, c1)
    server._sweep_proofs(dry=True); server._sweep_proofs(dry=True)
    check("…and the same commits cost no git log or merge-base on the passes after", calls["prs"] == c1["prs"] and calls["live"] == c1["live"], (c1, calls))
    for f in (T / "store/a").glob("*.json"): f.unlink()
    item(1, "home-builder: release PR #29 (no step waits on a merge in this repository)"); calls.update(prs=0, live=0, base=0); server._PROOF_GIT.clear()
    item(2, f"home-builder: merge {url(7, OTHER)}"); (T / "store/anchors.json").write_text("{}")
    GH_CALLS.clear(); server._sweep_proofs(dry=True)
    check("only another repository's merge to wait for: no git log, no merge-base", calls["prs"] == 0 and calls["live"] == 0, calls)
    for f in (T / "store/a").glob("*.json"): f.unlink()
    calls.update(prs=0, live=0, base=0)
    check("the clock with no step waiting on an event reads no git at all (not even the base)", server._sweep_proofs(tick=True)["items"] == [] and calls == {"prs": 0, "live": 0, "base": 0}, calls)
finally:
    server._merged_prs, server._released_is_live, server._released_live_base = _mp, _live, _base
fixtures()

# the explicit form: a proof dropped with its step says so; a close takes no proof
item(35, "home-builder: restart the unit\nhome-builder: check the pages", step_proof={"home-builder: restart the unit": f"pr_merged {key(39)}"})
out = upd(35, next="home-builder: restart the unit and the proxy\nhome-builder: check the pages", dropped=[1])
check("a proof that goes with its step says so in the reply", "step proof dropped:" in out and f"pr_merged {key(39)}" in out and "step_proof" not in rd(35)["metadata"], (out, rd(35)["metadata"]))
item(36, "home-builder: restart the unit\nhome-builder: check the pages")
refused("a close that also gives a proof is refused", lambda: upd(36, status="completed", outcome="done", reason="finished", description="- Finished by hand. Nothing is left.", step_proof=[{"step": 1, "proof": "pr_merged #5"}]), "is being closed")
import asyncio
TOOLS = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
check("step_proof's schema carries a one-line description", all(((TOOLS[n].parameters or {}).get("properties", {}).get("step_proof") or {}).get("description", "").startswith("The event that finishes a step") for n in ("update", "create")))

# ---- 9. the tool text names the new form and the sweep
import asyncio
TOOLS = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
check("update's and create's descriptions teach the step's proof, the events and the explicit form",
      all(server._STEP_PROOF_FORM in TOOLS[n].description for n in ("update", "create")) and all(x in server._STEP_PROOF_FORM for x in (
          "step_proof=[{", "pr_released", "pr_merged", "release PR #<n>", "A pull request closed without a merge ticks nothing", "once #<n> is released")), server._STEP_PROOF_FORM[:300])
check("…and both take the step_proof parameter", all("step_proof" in (TOOLS[n].parameters or {}).get("properties", {}) for n in ("update", "create")))

# ---- 10. the client verb and the route
fixtures(); s0 = snap()
from stackshot.fleet import client
tok = open(client.mint("testbox")).read().strip()
from starlette.testclient import TestClient
with TestClient(server.mcp.http_app()) as c:
    h = {"Authorization": "Bearer " + tok}
    res = c.post("/client/sweep-step-proof", json={"dry_run": True}, headers=h)
    check("POST /client/sweep-step-proof with dry_run lists and writes nothing", res.status_code == 200 and {x["item"] for x in res.json()["items"]} >= {"a1", "a2", "a9"} and not same(s0), res.text[:400])
    res = c.post("/client/sweep-step-proof", json={})
    check("no token, no write", res.status_code == 401, res.text)
    res = c.post("/client/sweep-step-proof", json={}, headers=h)
    check("POST /client/sweep-step-proof settles the items", res.status_code == 200 and rd(1)["status"] == "completed" and rd(2)["metadata"].get("next") == "home-builder: then check the pages", res.text[:400])
drain()
sent = []
client.post = lambda what, body, timeout=30.0: (sent.append((what, body)), (200, {"head": "abcdef1234", "good": "600d000aaa", "items": [
    {"item": "a1", "action": "closed", "reason": "PR #39 is merged (merged on GitHub)", "subject": "[home] item 1", "pr": 39, "kind": "pr_merged"},
    {"item": "a2", "action": "ticked", "told": "home-builder", "subject": "[home] item 2", "pr": 39, "kind": "pr_merged"},
    {"item": "a3", "action": "told", "told": "home-builder", "subject": "[home] item 3", "pr": 39, "kind": "pr_merged"},
    {"item": "a9", "action": "ticked", "told": "home-builder", "subject": "[home] item 9", "pr": 42, "kind": "pr_released"},
    {"item": "a4", "action": "told", "dead": "closed", "told": "home-builder", "step": "home-builder: merge PR #40", "subject": "[home] item 4", "pr": 40, "kind": "pr_merged"},
    {"item": "a20", "action": "ticked", "quiet": True, "subject": "[home] item 20", "pr": 7, "kind": "pr_merged", "ref": "PR other-owner/other#7"}]}))[1]
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "sweep-step-proof", "--dry-run"])
check("client.py sweep-step-proof --dry-run posts dry_run and says what it would do, per item, merge and release alike",
      rc == 0 and sent[-1] == ("sweep-step-proof", {"dry_run": True}) and buf.getvalue().splitlines() == [
          "stackshot: last-good 600d000, live checkout abcdef1 (dry run: nothing written, nobody told)",
          "stackshot: PR #39: would close a1 (outcome done: PR #39 is merged (merged on GitHub)) — [home] item 1",
          "stackshot: PR #39: would tick the merge step of a2 and tell its mover home-builder that the item's other open steps remain — [home] item 2",
          "stackshot: PR #39: would tell the mover home-builder of a3 that the PR is merged and its merge step is not ticked (it names a follow-up or a condition, so the step stays open) — [home] item 3",
          "stackshot: PR #42: would tick the release step of a9 and tell its mover home-builder that the item's other open steps remain — [home] item 9",
          "stackshot: PR #40: would tell the mover home-builder of a4 that PR #40 was closed without being merged, so its step can never be ticked by it (home-builder: merge PR #40) — [home] item 4",
          "stackshot: PR other-owner/other#7: would tick the merge step of a20 (every other open step waits on another pull request: nobody to be told) — [home] item 20"], buf.getvalue())
n_sent = len(sent)
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()): rc = client.main(["client.py", "sweep-step-proof", "--project", "x"])
check("usage, exit 1, nothing sent: an option it does not take", rc == 1 and len(sent) == n_sent)
check("client.py's help names the verb", "client.py sweep-step-proof [--dry-run]" in client.__doc__ and "merge PR #N" in client.__doc__)

# ---- 11. the backfill tool: a dry run on a copy, offline, writes nothing
fixtures()
copy = T / "copy"; shutil.copytree(T / "store", copy)
cs0 = {p.name: p.read_text() for p in (copy / "a").glob("*.json")}
env = {k: v for k, v in os.environ.items() if k not in ("STACKSHOT_CONFIG", "BOARD_MCP_CONFIG")}
env["HOME"] = tmp; env["TMPDIR"] = tmp
tool = [sys.executable, str(pathlib.Path(STACK, "stackshot", "tools", "backfill_step_proof.py")), "--config", str(T / "stackshot.toml"), "--store", str(copy), "--checkout", str(T / "repo"), "--state", str(T / "state")]
p = subprocess.run(tool, capture_output=True, text=True, env=env, cwd=tmp)
check("the tool's dry run exits 0, lists each item with what the server would do, and counts", p.returncode == 0 and "dry run: nothing written, nobody told" in p.stdout
      and re.search(r"a9\s+would tick\s+\[PR #42 released\]", p.stdout) and re.search(r"a12\s+would close\s+\[PR #42 released\]", p.stdout) and re.search(r"a25\s+would close\s+\[PR #43 merged\]", p.stdout)
      and re.search(r"a10\s+would tell the mover\s+\[PR #42 released\]", p.stdout), (p.stdout[-1500:], p.stderr[-800:]))
check("…it makes no GitHub call: the merges only GitHub knows are listed as not read, and nothing about them is settled",
      f"not read (git cannot say, no --github): {key(39)}, {key(40)}, {key(41)}, {key(7, OTHER)}" in p.stdout and "\na1 " not in p.stdout and "\na2 " not in p.stdout, p.stdout[-600:])
check("…it wrote nothing: the copy and the real store are as they were, and no push was made", {q.name: q.read_text() for q in (copy / "a").glob("*.json")} == cs0 and not same(s0), same(s0))
pj = subprocess.run([*tool, "--json"], capture_output=True, text=True, env=env, cwd=tmp)
js = json.loads(pj.stdout) if pj.returncode == 0 else {}
check("--json gives the counts and the rows", js.get("counts", {}).get("closed") == 2 and any(x["item"] == "a9" and x["action"] == "ticked" for x in js.get("items", [])) and js.get("unread"), (pj.stdout[:500], pj.stderr[-400:]))
pa = subprocess.run([*tool, "--apply"], capture_output=True, text=True, env=env, cwd=tmp)
check("--apply is refused together with the options that point a dry run at a copy", pa.returncode == 1 and "goes through the running server" in pa.stderr, (pa.stdout, pa.stderr))
check("every PR the step-proof sweep read on GitHub was read under the 'step_proof' ledger tag (and the tag is gone afterwards)", GH_TAGS and set(GH_TAGS) == {"step_proof"} and _gbud.current() == "", (GH_TAGS, _gbud.current()))
check("the tool left no folder of its own behind (its temporary folder is made under the suite's own scratch folder)", not list(pathlib.Path(tmp).glob("stepproof-*")))

# ---- 9. the real reader behind _pr_merged is shared with the done check and the event wait (pr_state.py): a read one of them made inside the pace is not made again by the sweep
from stackshot.github import pr_state as _prs
class _Cl:
    repo_id = 0
    def __init__(self): self.calls = []
    def repo_path(self, rest=""): return f"/repos/{REPO}" + rest
    def request(self, method, path, **kw):
        self.calls.append((path, kw.get("etag"), _gbud.current()))
        on = path.endswith("/pulls/39")
        return {"state": "closed" if on else "open", "merged": on, "merged_at": "2026-11-03T00:00:00Z" if on else None}
CL9 = _Cl(); _cg9 = server._check_gh; server._check_gh = lambda repo: CL9
try:
    server._pr_merged = REAL_PR_MERGED; _prs.reset(); fixtures()
    (T / "state/step-proof.json").unlink(missing_ok=True)
    t9 = time.time()
    with _gbud.tag("done_check"): ok9 = server._pr_merged(key(39), t9, {})          # the done check's pass reads #39 first
    d9 = server._sweep_proofs(dry=True, save=True)
    c50 = [c for c in CL9.calls if c[0].endswith("/pulls/39")]
    check("9: the done check read #39 once and the sweep, asking for the same PR inside the pace, made no second read (its other pull requests were read, as before)",
          ok9 == (True, "") and len(c50) == 1 and c50[0][1] is True and c50[0][2] == "done_check" and any(c[0].endswith("/pulls/40") for c in CL9.calls) and any(x["item"] == "a1" and x["action"] == "closed" for x in d9["items"]), (CL9.calls, d9["items"][:3]))
    kept = json.loads((T / "state/step-proof.json").read_text()).get("github", {})
    check("9: …the sweep's own file keeps the answer the done check read (it is where a later pass looks first)", kept.get(key(39), {}).get("merged") is True and kept.get(key(40), {}).get("merged") is False, kept)
    check("9: …the PRs the sweep read itself were read under its own ledger tag", all(c[2] == "step_proof" for c in CL9.calls if not c[0].endswith("/pulls/39")) and any(c[2] == "step_proof" for c in CL9.calls), CL9.calls)
finally:
    server._check_gh = _cg9; server._pr_merged = fake_pr_merged; _prs.reset()

print(f"{len(ran) - len(fails)}/{len(ran)} passed" + (f" — FAILED: {', '.join(fails)}" if fails else ""))
sys.exit(1 if fails else 0)
