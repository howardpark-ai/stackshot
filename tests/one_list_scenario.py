"""Scenario test for the one list (a step's status line replaces the separate Work list) — fixture data, a fake clock, no live store, no network, no server socket.

The shape of a long build overnight: next set at the start ("pick stage 7"), then a status write about every 30 minutes through ten stages, each stage closed once (some by
done=[n], some by a status done). What the item shows is one list, not two:

  1  the stored checklist has one step per stage, each with its latest status; a night of writes adds no step and no line; the old `work` field is never written
  2  a status write changes the status of the sender's open step in place; one sent again unchanged keeps its old time; state done ticks the step; with no open step it makes one
  3  the page: the Work field is gone from the sidebar; Next shows the open step and the newest done step, and the other done steps fold behind one line that opens to one line each
  4  History: one line per closed step with its status updates folded under it, not one line per write; other writes (the create, a hand-off) keep their own lines
  5  the stall and silence checks take a step-status write as news: it ends the stall episode (`server._stall_ver`), moves the activity clock, keeps a build subagent "running" for 90 minutes
     (`silence.subagent_running`, from the step's status time), and a status sent again unchanged does not extend that; the state clock and the confirm stay for a plain status write
  6  the item never has more than a handful of visible lines in Next and in History, however many writes came

    tests/run-suite one_list        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging, subprocess, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="onelisttest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "brain/projects"): (T / d).mkdir(parents=True)
MAIN, ENG = "quill-main", "quill-engineer"
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate((MAIN, ENG), 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/example.md").write_text("---\ntype: project\ntitle: Stackshot\ndisplay-name: quill\nagents:\n  quill-main: builds it\n---\n\n# x\n", encoding="utf-8")
STORE = T / "store"
git = lambda *a: subprocess.run(["git", "-C", str(STORE), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", "fixture")
def snap(msg="w"): git("add", "-A"); git("commit", "-q", "--allow-empty", "-m", msg)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server; from stackshot.model import steps as S; from stackshot.model import work as W; from stackshot.audit import silence as SL; from stackshot.model import ids as _model_ids
from stackshot.web.ui import render as ui_render
server._cfg.CFG.setdefault("model", {})["guards"] = False      # fixture sessions the guards would judge; the write guards have their own suite
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
STK = "projects/example"; DESC = "- Goal: A thing\n- It lives here\n- Done when done"
def rd(gid): return json.loads(server._path(gid).read_text())
same = lambda a, b: bool(a) and bool(b) and a == b

real_time = time.time; t0 = real_time(); clk = [t0]; time.time = lambda: clk[0]
MIN = 60.0
try:
    r = server.stackshot_create(subject="[home] a long build", description=DESC, project=STK, sender=ENG, owner=ENG, mover=ENG, next=f"{ENG}: pick stage 7")
    g = _model_ids._norm_id(r.split()[1]); snap("create")
    m0 = rd(g)["metadata"]
    check("the item starts with one open step and no work field", [x["status"] for x in S.view(m0)] == ["open"] and "work" not in m0, m0)

    writes = 0; vers = []; per_stage = {}
    stages = list(range(7, 17))
    for k, stage in enumerate(stages):
        n_this = 0
        for j, txt in enumerate((f"stage {stage}: PR up", f"stage {stage}: review", f"stage {stage}: scan 99", f"stage {stage}: releasing")):
            clk[0] += 30 * MIN
            before = rd(g)
            server._update(g, work={"text": txt}, sender=ENG); snap(f"s{stage}.{j}")
            after = rd(g); writes += 1; n_this += 1
            vers.append((server._stall_ver(before), server._stall_ver(after), before, after))
        # close the stage: some by done=[n] with the next stage in next, some by a status done with the next stage given in the same call
        clk[0] += 30 * MIN
        pos = len(S.view(rd(g)["metadata"]))          # the open step is the last position of the stored checklist
        nxt = f"{ENG}: pick stage {stage + 1}"
        if k % 2 == 0:
            server._update(g, done=[pos], next=nxt, sender=ENG)
        else:
            server._update(g, work={"state": "done"}, next=nxt, sender=ENG)
        snap(f"close{stage}"); per_stage[stage] = n_this + 1
    m = rd(g)["metadata"]; st = S.view(m)

    # ------------------------------------------------------------ 1 the stored checklist
    check("one step per stage: 10 done and 1 open (the last stage's successor), not one entry per write", [x["status"] for x in st] == ["done"] * 10 + ["open"], [x["status"] for x in st])
    check("each done step carries its latest status (done), and the old work field was never written", all((S.tag_of(x) or {}).get("state") == "done" for x in st[:10]) and "work" not in m, m.get("work"))
    check("the open step has no status yet (nothing written since the last close) and `next` is one line", S.tag_of(st[10]) is None and m["next"].count("\n") == 0, (st[10], m["next"]))
    clk[0] += 30 * MIN
    server._update(g, work={"text": "stage 17: PR up"}, sender=ENG); snap("s17")
    m = rd(g)["metadata"]; st = S.view(m)
    check("a status write sets the status of the sender's open step in place: still 11 steps", len(st) == 11 and (S.tag_of(st[10]) or {}).get("text") == "stage 17: PR up", st[10])

    # ------------------------------------------------------------ 2 in place, unchanged, done, made
    ts1 = S.tag_of(st[10])["ts"]; clk[0] += 5 * MIN
    out = server._update(g, work={"text": "stage 17: PR up"}, sender=ENG)
    st = S.view(rd(g)["metadata"])
    check("a status sent again unchanged keeps its old time and says so", S.tag_of(st[10])["ts"] == ts1 and "unchanged, already so" in out, (S.tag_of(st[10]), out))
    clk[0] += 5 * MIN
    server._update(g, work={"text": "stage 17: review", "state": "in progress"}, sender=ENG)
    st = S.view(rd(g)["metadata"])
    check("a changed status moves the time", S.tag_of(st[10])["text"] == "stage 17: review" and S.tag_of(st[10])["ts"] > ts1, S.tag_of(st[10]))

    # ------------------------------------------------------------ 3 the page
    snap("s17b")
    B = ui_render.Board(str(STORE)); pg = B.item_html(g)
    side = pg[pg.find('<aside class="iside"'):pg.find("</aside>")]
    check("the page's sidebar has no Work field", "<dt>Work" not in side and 'class="iwork"' not in side, side[:400])
    nxt_html = pg[pg.find("<h2>Next</h2></summary>"):pg.find('<details class="fold" data-fold="item.description"')]
    fold_at = nxt_html.find('<details class="iearlier">'); fold_end = nxt_html.find("</details>", fold_at)
    outside = nxt_html[:fold_at] + nxt_html[fold_end + len("</details>"):] if fold_at >= 0 else nxt_html
    vis = re.findall(r'<li class="cl-(\w+)">', outside)
    check("Next shows the newest done step and the open step with its status, nothing else", vis == ["done", "open"] and '<span class="cl-tag">stage 17: review' in outside, (vis, outside[:600]))
    check("the 9 older done steps are folded behind one line", fold_at >= 0 and "<summary>9 steps done · " in nxt_html and len(re.findall(r'<li class="cl-done">', nxt_html[fold_at:fold_end])) == 9, nxt_html[fold_at:fold_at + 300])

    # ------------------------------------------------------------ 4 History
    evs, more = B.item_events(B.item(g))
    work_evs = [h for _t, k_, h in evs if k_ == "work"]
    closed = [h for h in work_evs if "step done: " in h]
    check("History has one line per closed step (10), each with its status updates folded under it", len(closed) == 10 and all("status update" in h for h in closed), work_evs[:2])
    counts = sorted(int(re.search(r"(\d+) status updates?", h).group(1)) for h in closed)
    check("…the folded count is the writes of that stage plus the close", counts == sorted(per_stage.values()), (counts, per_stage))
    check("…and the open step's updates are one line too", len(work_evs) == 11 and sum("step: " in h and "step done" not in h for h in work_evs) >= 1, [h[:80] for h in work_evs])
    plain = [k_ for _t, k_, h in evs if k_ != "work"]
    check("other writes keep their own lines: the create stays, and no line says a status alone", "created" in plain, plain)

    # ------------------------------------------------------------ 5 news for the stall and silence checks
    ended = [v for v in vers if v[0] != v[1]]
    check("every status write ended the stall episode (the version `_stall_ver` reads moved)", len(ended) == writes, (len(ended), writes))
    check("a plain status write keeps the state clock and the confirm (a filing edit)", all(v[2]["state_updated"] == v[3]["state_updated"] and v[2].get("confirmed") == v[3].get("confirmed") for v in vers), vers[0][2].get("state_updated"))
    check("…and it moves the activity clock, the item's own measure of news", all(float(v[3].get("activity") or 0) > float(v[2].get("activity") or 0) for v in vers), [(v[2].get("activity"), v[3].get("activity")) for v in vers[:2]])
    it = rd(g); tag_ts = S.tag_of(S.view(it["metadata"])[10])["ts"]
    check("a status in progress counts as a running build subagent on the mover's step for 90 minutes", SL.subagent_running(it, tag_ts + 80 * MIN, ENG, same), it["metadata"].get("steps"))
    check("…not after that, and not for another session's mover", not SL.subagent_running(it, tag_ts + 95 * MIN, ENG, same) and not SL.subagent_running(it, tag_ts + 10 * MIN, MAIN, same))
    clk[0] += 60 * MIN
    server._update(g, work={"text": "stage 17: review", "state": "in progress"}, sender=ENG)       # unchanged: its old time stays, so a status left in progress does not hide the item forever
    it2 = rd(g); st2 = S.view(it2["metadata"])
    check("a status sent again unchanged does not extend the 90 minutes", S.tag_of(st2[10])["ts"] == tag_ts and not SL.subagent_running(it2, tag_ts + 95 * MIN, ENG, same), S.tag_of(st2[10]))
    server._update(g, work={"text": "stage 17: scan 99"}, sender=ENG)
    it3 = rd(g)
    check("…while a changed one starts them again", SL.subagent_running(it3, time.time() + 80 * MIN, ENG, same), S.tag_of(S.view(it3["metadata"])[10]))
    server._update(g, work={"state": "done"}, sender=ENG)
    check("the step marked done by a status done is no running subagent", not SL.subagent_running(rd(g), time.time() + MIN, ENG, same))

    # ------------------------------------------------------------ 6 a handful of lines
    snap("end")
    B = ui_render.Board(str(STORE)); pg = B.item_html(g)
    nxt_html = pg[pg.find("<h2>Next</h2></summary>"):pg.find('<details class="fold" data-fold="item.description"')]
    fold_at = nxt_html.find('<details class="iearlier">'); fold_end = nxt_html.find("</details>", fold_at)
    outside = nxt_html[:fold_at] + nxt_html[fold_end + len("</details>"):]
    check("however many writes came, Next shows at most a handful of lines (the rest are folded)", len(re.findall(r'<li class="cl-', outside)) <= 3, len(re.findall(r'<li class="cl-', outside)))
    log, more_ = B.item_log(B.item(g))
    check("…and the page's History is one entry per closed step and one for the step in motion plus the create (12 or fewer entries for 50 writes), each closed step's entry carrying its time range",
          len(log) <= 12 and writes + 10 >= 50 and sum(1 for x in log if x.get("ts_from") and x["ts_from"] < x["ts"]) >= 10, (len(log), writes, [x.get("ts_from") for x in log][:3]))
    check("…and a closing write's new next line stays in the same entry as its step line", any("step done" in x["html"] and "next" in x["html"] for x in log), [x["html"][:200] for x in log[:2]])

    # ------------------------------------------------------------ 7 a close that marks the open step itself (dropped), a legacy `id`
    r2 = server.stackshot_create(subject="[home] a build that is called off", description=DESC, project=STK, sender=ENG, owner=ENG, mover=ENG, next=f"{ENG}: build it")
    g2 = _model_ids._norm_id(r2.split()[1]); snap("create2")
    clk[0] += 30 * MIN; server._update(g2, work={"text": "PR up"}, sender=ENG); snap("w2a")
    clk[0] += 30 * MIN; server._update(g2, work={"text": "review"}, sender=ENG); snap("w2b")
    clk[0] += 30 * MIN; server.stackshot_complete(g2, outcome="dropped", reason="called off", outcome_text="- called off", sender=ENG); snap("drop2")
    st_d = S.view(rd(g2)["metadata"], closed=True)
    check("the close marked the open step dropped, and it kept its status", [x["status"] for x in st_d] == ["dropped"] and (S.tag_of(st_d[0]) or {}).get("text") == "review", st_d)
    B = ui_render.Board(str(STORE)); log2, _m = B.item_log(B.item(g2))
    steplines = [x for x in log2 if "status update" in x["html"]]
    check("History says the step was dropped, not done, with its status updates folded under it", len(steplines) == 1 and "step dropped: " in steplines[0]["html"] and "step done" not in steplines[0]["html"]
          and "2 status updates" in steplines[0]["html"], [x["html"][:300] for x in log2])
    r3 = server.stackshot_create(subject="[home] an old client writes", description=DESC, project=STK, sender=ENG, owner=ENG, mover=ENG, next=f"{ENG}: build it")
    g3 = _model_ids._norm_id(r3.split()[1]); before3 = rd(g3)
    refused = []
    for spec in ({"id": "x", "state": "done"}, {"id": "migrating-ids", "text": "migrating ids", "state": "done"}, '{"id": "x", "state": "done"}'):
        try:
            server._update(g3, work=spec, sender=ENG); refused.append("accepted")
        except Exception as ex:
            refused.append(str(ex))
    check("a work spec that carries a legacy `id` is refused with the way in, and ticks nothing", all("old Work list" in x and "done=[n]" in x for x in refused) and rd(g3) == before3, refused)
    check("…while the same spec without the `id` is a status write on the sender's step", (server._update(g3, work={"text": "migrating ids"}, sender=ENG), (S.tag_of(S.view(rd(g3)["metadata"])[0]) or {}).get("text"))[1] == "migrating ids")
    for empty_id in ("", None, "  "):
        W.parse({"id": empty_id, "text": "migrating ids"})
    out_e = server._update(g3, work={"id": "", "text": "migrating ids, again"}, sender=ENG)
    check("an empty or null `id` (a cached-schema client may always send one) is ignored: the write is a status write", (S.tag_of(S.view(rd(g3)["metadata"])[0]) or {}).get("text") == "migrating ids, again", out_e)
    check("…and so are a zero and an empty list in `id`", W.parse({"id": 0, "text": "x"})["text"] == "x" and W.parse({"id": [], "text": "x"})["text"] == "x")
    server._update(g3, work='{"id":"","text":"from a json string"}', sender=ENG)
    check("…and an empty id through the JSON-string form writes a status", (S.tag_of(S.view(rd(g3)["metadata"])[0]) or {}).get("text") == "from a json string", S.view(rd(g3)["metadata"])[0])
    # a drifted step (its line left next without a mark) shows on no row and holds no running subagent
    it4 = rd(g3); m4 = it4["metadata"]; m4["next"] = f"{ENG}: something else"
    check("a step whose line left next without a mark has no status line on the row", W.step_lines(m4) == [] and W.row_words(m4) == "", W.step_lines(m4))
finally:
    time.time = real_time

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + (f"; FAILED: {len(fails)}" if fails else ""))
sys.exit(1 if fails else 0)
