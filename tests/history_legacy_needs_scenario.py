"""Scenario test for History over a store whose old commits keep the old needs value (legacy_owner.py, ui/render.py Board.item_versions) — made-up data in a temp git repo, no live store, no network.

A legacy owner label stays supported: an item that waited on the owner may have stored the owner's first name in lower case as its `needs` value. The live files hold `decision`, but the store's git keeps every old commit, and History diffs those commits (item_versions → item_log). Read as they are, an item whose first commit says needs [<legacy name>] and
whose second says ["decision"] showed a move that never happened: "created as … · On agent" and "whose move: On agent → Your move". The old version is read as `decision`
(a copy; nothing is written), the legacy name being derived from [instance] owner (the first word, lower case).

Covers: the made-up owner "Pat Example" (legacy name `pat`); an item with the list form and one with the string form of the old value: History equals what a store written in the neutral name from
the start shows (one created line saying "Your move", no whose-move line), in the board's renderer; a control with the owner unnamed shows the false move (so the check bites, and the name
comes from the config); the helper itself (the first word, the placeholder names no one, list and string forms, a duplicate beside `decision`, other entries kept, the same object when
nothing changes, the version given is not changed); the other readers of historical versions read no needs: server._writers_since (written_by) and waiting.prior_state_ts (wake, state_updated)
give the same answers on the old commits.

    tests/run-suite history_legacy_needs        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="histlegacy-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", f"{tmp}/store"), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/store/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Pat Example"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")      # the commits go into the temp store only
for d in ("store/a", "control/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
HERE = "00000000-0000-4000-8000-000000000001"
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({HERE: {"name": "home-here", "machine": "a", "seen": now0}}))
PROJ = {"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-here", "status": "active", "board": [], "board_open": 0}}}
for root in ("store", "control"):
    (T / root / "projects.json").write_text(json.dumps(PROJ)); (T / root / "next-id").write_text("500"); (T / root / "anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-here\n---\n\n# Alpha\n")
ASK = "Decide: whether to ship · Recommend: ship · Stakes: none either way · By: no date"
OPTS = [{"label": "Ship", "line": "Ship it now", "recommended": True}, {"label": "Wait", "line": "Wait a week", "recommended": False}]
T0, T1 = now0 - 7200.0, now0 - 3600.0


def version(i, needs, at, writer, wake=None):
    meta = {"owner": HERE, "project": "projects/alpha", "needs": needs, "ask": ASK, "options": OPTS, "next": "home-here: wait for the answer"}
    if wake: meta["wake"] = wake
    return {"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here.\n\n" + "".join(f"- item {i}, line {n}: " + "xyzzy plugh"[n % 5:] * (3 + (i * 7 + n) % 5) + "\n" for n in range(30)), "status": "open", "updated": at, "state_updated": at, "confirmed": at,
            "written_by": writer, "metadata": meta}


def git(root, *a, when=None):
    env = {**os.environ, **({"GIT_AUTHOR_DATE": f"{int(when)} +0000", "GIT_COMMITTER_DATE": f"{int(when)} +0000"} if when else {})}
    r = subprocess.run(["git", "-C", str(T / root), *a], capture_output=True, text=True, env=env)
    assert r.returncode == 0, (a, r.stderr)


def commit(root, i, v, when):
    (T / root / "a" / f"{i}.json").write_text(json.dumps(v)); git(root, "add", f"a/{i}.json"); git(root, "commit", "-q", "-m", f"item {i}", when=when)


for root in ("store", "control"):
    git(root, "init", "-q"); git(root, "config", "commit.gpgsign", "false")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.core import legacy_owner as lo; from stackshot.core import config as _cfg
LEG = lo.name_from_owner("Pat Example")
# the old store: item 1 has the list form in its first commit, item 2 the one-word string form; both say ["decision"] in the second. The control was written in the neutral name from the start.
commit("store", 1, version(1, [LEG], T0, "home-x"), T0); commit("store", 1, version(1, ["decision"], T1, "home-y"), T1)
commit("store", 2, version(2, LEG, T0, "home-x"), T0); commit("store", 2, version(2, ["decision"], T1, "home-y"), T1)
for i in (1, 2):
    commit("control", i, version(i, ["decision"], T0, "home-x"), T0); commit("control", i, version(i, ["decision"], T1, "home-y"), T1)
# item 3: a first commit with a wake and the old value, then the answer; for the readers that look at a wake
W0, W1 = "2026-11-10", "2026-11-12"
commit("store", 3, version(3, [LEG], T0, "home-x", wake=W0), T0); commit("store", 3, version(3, ["decision"], T1, "home-y", wake=W1), T1)

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1500]}" if got is not None else ""))


def lines(root, i):
    bd = ui_render.Board(str(T / root)); row = bd.item(f"a{i}")
    evs, _more = bd.item_log(row)
    return [(x["kind"], x["what"]) for x in evs]


try:
    from stackshot.web.ui import render as ui_render
    # ---- the helper
    check("the legacy name is the first word of [instance] owner in lower case", LEG == "pat" and lo.name_from_owner("Pat Example") == "pat" and lo.name_from_owner("  PAT-Lee ") == "pat", LEG)
    check("…an owner that names no one gives none (the placeholder, empty, not a word)", all(lo.name_from_owner(x) == "" for x in ("the owner", "", None, "  ", "___", "owner")), None)
    v0 = {"metadata": {"needs": [LEG, "home-other"], "k": 1}}
    out = lo.history_version(v0, LEG)
    check("history_version: the old value reads as decision, other entries and fields stay, the version given is not changed", out["metadata"]["needs"] == ["decision", "home-other"] and out["metadata"]["k"] == 1 and v0["metadata"]["needs"] == [LEG, "home-other"], (out, v0))
    check("…the string form, any case and padding", lo.history_version({"metadata": {"needs": f" {LEG.upper()} "}}, LEG)["metadata"]["needs"] == "decision", None)
    check("…a duplicate beside decision is dropped", lo.history_version({"metadata": {"needs": ["decision", LEG]}}, LEG)["metadata"]["needs"] == ["decision"] and lo.history_version({"metadata": {"needs": [LEG, "decision"]}}, LEG)["metadata"]["needs"] == ["decision"], None)
    same = {"metadata": {"needs": ["decision", "external"]}}
    check("…nothing to change gives the same object back, and no name gives it back as it is", lo.history_version(same, LEG) is same and lo.history_version(v0, "") is v0 and lo.history_version({"x": 1}, LEG) == {"x": 1}, None)
    check("…a session whose name merely contains the legacy name is not the owner", lo.history_version({"metadata": {"needs": [LEG + "-session"]}}, LEG)["metadata"]["needs"] == [LEG + "-session"], None)

    # ---- History: the old store equals the control
    mine, false_move = "Your move", "On agent"      # the lane in the page's own words
    for i in (1, 2):
        got, want = lines("store", i), lines("control", i)
        check(f"item {i}, History over the old commits is what a store written in the neutral name shows", got == want and len(got) >= 1, (got, want))
        created = [w for k, w in got if k == "created"]
        check(f"item {i}: one created line, in 'Your move', and no whose-move line", len(created) == 1 and mine in created[0] and false_move not in created[0] and not any(("whose move" in w or "moved to" in w) for _k, w in got), got)

    # ---- the check bites: with the owner unnamed no legacy name is derived, and the old commit reads as it is stored
    running = _cfg.CFG["instance"]["owner"]
    try:
        _cfg.CFG["instance"]["owner"] = "the owner"
        bad = lines("store", 1)
    finally:
        _cfg.CFG["instance"]["owner"] = running
    check("control: without a legacy name (owner unnamed) the same commits show the false move, 'On agent' then 'Your move'", any("On agent" in w for k, w in bad if k == "created") and any("moved to" in w and "Your move" in w for _k, w in bad), bad)
    check("…and the name is read at each call (a config reload is seen)", lines("store", 1) == lines("control", 1), None)

    # ---- the other readers of historical versions read no needs
    from stackshot.web import server; from stackshot.waits import waiting as _wt
    ws = server._writers_since("a1", T0 - 10)
    check("server._writers_since (written_by) gives both writers of the old commits", ("home-x", "") in ws and ("home-y", "") in ws, ws)
    prior = _wt.prior_state_ts("a3", W1)
    check("waiting.prior_state_ts (wake, state_updated) gives the state clock before the wake of the old commits", prior is not None and abs(float(prior) - T0) < 1.0, prior)
except Exception:
    import traceback; traceback.print_exc(); fails.append("scenario raised")
finally:
    print(("ok" if not fails else "FAILED") + f": history over legacy needs scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
