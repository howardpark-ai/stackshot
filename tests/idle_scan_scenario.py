"""Scenario test for what the server does between requests: the minute passes read the store, and the board's publish and the search index read the store's git (made-up data in a temp store and temp git repos,
no live store, no network).

  1  the scans of the store: a pass that looks for the open items (the anchor pass, the sent-mail views, the merge pass's ties, the phase sweep, the stall tick, the check pass) parses the files of the open items only
     once it has seen the closed ones: a closed item whose file has not changed is skipped on its `stat`. Pinned by counting the item files `json.load` parses over a store of many closed items and a few open ones, and
     by what a write does to the answer (a replaced file, a file written in place at once after a read, a later write of the same size).
  2  the History of an item (item_history.commits, behind Board.item_versions of both renderers): `git log --follow` over the whole store is read once per item and HEAD; a new commit asks only for the commits
     since (identical to the whole walk, checked against it at every step, a rename and a rewritten history included); the same HEAD asks git nothing.
  3  the page times of a brain (pages.git_times): the walk of every commit is made once per HEAD; a new commit is read on the next call.

    tests/run-suite idle_scan       -> exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="idlescan-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml, n = re.subn(r'(?m)^session_links = "[^"]*"', 'session_links = ""', toml); assert n == 1
for key, val in (("repo", f"{tmp}/store"), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/store/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")      # the commits go into the temp repos only
for d in ("store/a", "fleet/a", "state", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("500"); (T / "store/anchors.json").write_text("{}")
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"})); (T / "fleet/a/sessions.json").write_text("{}")
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:300]}" if got is not None else ""))
now0 = time.time()
LONG_AGO = now0 - 3600.0


def item_file(i, status, mtime=LONG_AGO, **meta):
    p = T / f"store/a/{i}.json"
    p.write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "a thing\n" * 20, "status": status, "updated": now0 - 100, "state_updated": now0 - 100, "confirmed": now0 - 100,
                             "metadata": {"project": "projects/alpha", **meta}}))
    if mtime: os.utime(p, ns=(int(mtime * 1e9), int(mtime * 1e9)))
    return p


class Parsed:
    """Counts the reads of the item files while it is on: the files `json.load` parses and the ones `Path.read_text` reads (the two ways an item's file is read)."""
    def __init__(self): self.n = 0; self.real = json.load; self.real_text = pathlib.Path.read_text
    def __enter__(self):
        me = self
        def load(f, *a, **kw):
            if re.search(r"/store/a/\d+\.json$", str(getattr(f, "name", ""))): me.n += 1
            return me.real(f, *a, **kw)
        def read_text(path, *a, **kw):
            if re.search(r"/store/a/\d+\.json$", str(path)): me.n += 1
            return me.real_text(path, *a, **kw)
        json.load = load; pathlib.Path.read_text = read_text; return self
    def __exit__(self, *e): json.load = self.real; pathlib.Path.read_text = self.real_text


try:
    from stackshot.web import server, wiring           # noqa: F401  — wires the hooks the passes call
    from stackshot.core import store as cstore
    from stackshot.service import store as svcstore, wakes, stamp, merge_progress, sent_match, checks, stall_tick, stall as stall_svc, event_waits, watching, proofs

    # ---- 1  the scans of the store
    N_CLOSED, OPEN = 60, (1, 2, 3, 4)
    for i in OPEN: item_file(i, "open")
    for i in range(10, 10 + N_CLOSED): item_file(i, "completed")
    item_file(9, "on_hold")                                                    # an old stored form of a hold: read as an open item
    scans = {
        "anchor_pass": lambda: wakes.anchor_pass(),
        "sent_match._views": lambda: sent_match._views(),
        "merge_progress._merge_tied": lambda: merge_progress._merge_tied([], now0),
        "stamp._phase_sweep": lambda: stamp._phase_sweep(),
        "checks.check_tick": lambda: (checks.CHECK_LAST.__setitem__(0, 0.0), checks.check_tick())[1],
        "event_waits.evwait_report": lambda: event_waits.evwait_report(event_waits._evwait_pr_event("pr_merged", "acme/widgets", 1), now0),
        "event_waits.evwait_box_poll": lambda: event_waits.evwait_box_poll(now0, {}),
        "event_waits._evwait_poll_prs": lambda: event_waits._evwait_poll_prs(now0, {}),
        "wakes.wake_rows": lambda: wakes.wake_rows(),
        "watching.watch_pass": lambda: watching.watch_pass(now0),
        "watching.watch_refresh_asks": lambda: watching.watch_refresh_asks(now0),
        "watching.watch_anchor_notice": lambda: watching.watch_anchor_notice("projects/alpha", "https://example.com/a", {"id": "n1", "text": "hi"}, now0, "a notice"),
        "proofs.sweep_proofs": lambda: proofs.sweep_proofs(dry=True, tick=True),
        "stall_tick": lambda: (stall_svc.STALL_LAST.__setitem__(0, 0.0), stall_tick.stall_tick())[1],
    }
    n_open = len(OPEN) + 1
    for name, run in scans.items():
        for k in list(svcstore._CLOSED): svcstore._CLOSED.pop(k)
        with Parsed() as first:
            try: run()
            except Exception as e: print(f"  ({name} raised {e.__class__.__name__}: {e})")
        with Parsed() as again:
            try: run()
            except Exception as e: print(f"  ({name} raised {e.__class__.__name__}: {e})")
        check(f"{name}: the first scan reads every file ({first.n} of {N_CLOSED + n_open})", first.n >= N_CLOSED, first.n)
        check(f"{name}: the next scan parses the files of the open items only ({again.n} of {N_CLOSED + n_open})", again.n <= 2 * n_open, again.n)

    # ---- the answer of the cheap path is the answer of `_load`
    for i in list(OPEN) + [9, 10, 11]:
        g = f"a{i}"; got = svcstore._load_open(g); want = svcstore._load(g)
        check(f"_load_open({g}): the item as `_load` reads it when it is open (a held one too), None when it is not", got == (want if want.get("status") == "open" else None), (got, want.get("status")))
    try: svcstore._load_open("a9999"); raised = False
    except Exception as e: raised = "no item" in str(e)
    check("_load_open of an item that does not exist raises 'no item', as `_load` does", raised)

    # ---- what a write does to the answer
    svcstore._CLOSED.clear()
    p = item_file(20, "completed")
    check("a closed item: None, and remembered", svcstore._load_open("a20") is None and str(p) in svcstore._CLOSED, list(svcstore._CLOSED)[:2])
    old = p.stat()
    item_file(20, "open", mtime=None)                                          # written in place: same inode, a later time
    check("a write in place (later time) shows the item again", (svcstore._load_open("a20") or {}).get("status") == "open", p.stat().st_mtime_ns)
    svcstore._CLOSED.clear()
    item_file(21, "completed"); check("a closed item again: remembered", svcstore._load_open("a21") is None and len(svcstore._CLOSED) == 1)
    tmpf = T / "store/a/.21.json.tmp"; tmpf.write_text(json.dumps({**json.loads((T / "store/a/21.json").read_text()), "status": "open"}))
    st21 = (T / "store/a/21.json").stat(); os.utime(tmpf, ns=(st21.st_atime_ns, st21.st_mtime_ns))
    pad = st21.st_size - tmpf.stat().st_size
    if pad > 0: tmpf.write_text(tmpf.read_text() + " " * pad); os.utime(tmpf, ns=(st21.st_atime_ns, st21.st_mtime_ns))
    same_size_and_time = tmpf.stat().st_size == st21.st_size and tmpf.stat().st_mtime_ns == st21.st_mtime_ns
    os.replace(tmpf, T / "store/a/21.json")                                     # the server's own way: a file renamed over it, the same size and time but another inode
    check("a replaced file of the same size and time shows the item again (the inode is part of what is remembered)", same_size_and_time and (svcstore._load_open("a21") or {}).get("status") == "open", same_size_and_time)
    svcstore._CLOSED.clear()
    pr = item_file(22, "completed", mtime=time.time())                                # written just now
    check("a file written within the last moments is never remembered", svcstore._load_open("a22") is None and not svcstore._CLOSED, list(svcstore._CLOSED))
    st = pr.stat(); body = json.loads(pr.read_text()); body["status"] = "open"; txt = json.dumps(body)
    txt = txt + " " * (st.st_size - len(txt)) if st.st_size >= len(txt) else txt
    pr.write_text(txt); os.utime(pr, ns=(st.st_atime_ns, st.st_mtime_ns))     # the same size, the same time, the same inode: a second write in one clock tick
    check("a second write of the same size in the same clock tick shows the item", pr.stat().st_size == st.st_size and (svcstore._load_open("a22") or {}).get("status") == "open", (pr.stat().st_size, st.st_size))

    # ---- 2  the History of an item
    from stackshot.web import item_history as ih
    G = T / "hist"; G.mkdir()
    def git(*a, when=None, cwd=G):
        env = {**os.environ, **({"GIT_AUTHOR_DATE": f"{int(when)} +0000", "GIT_COMMITTER_DATE": f"{int(when)} +0000"} if when else {})}
        r = subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, env=env)
        assert r.returncode == 0, (a, r.stderr); return r.stdout
    def write(rel, n, repo=G):
        f = repo / rel; f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"id": "1", "subject": "item", "n": n, "description": "text\n" * 40})); git("add", rel, cwd=repo)
    def truth(rel, repo=G):
        r = subprocess.run(["git", "-C", str(repo), "log", "--follow", "--name-only", "--format=%x01%H%x09%ct", "--", rel], capture_output=True)
        return ih._parse(r.stdout)
    git("init", "-q", "-b", "main")
    for k in range(3): write("a/1.json", k); git("commit", "-q", "-m", f"c{k}", when=1_700_000_000 + 100 * k)
    logs = []; real_git = ih._git
    def spy(d, *args, **kw): logs.append(args); return real_git(d, *args, **kw)
    ih._git = spy
    try:
        ih._CACHE.clear(); ih.CALLS["log"] = 0
        a = ih.commits(str(G), "a/1.json")
        check("History: the whole walk, as `git log --follow` gives it", a == truth("a/1.json") and len(a) == 3 and ih.CALLS["log"] == 1, (a, ih.CALLS))
        logs.clear(); b = ih.commits(str(G), "a/1.json")
        check("History: the same HEAD asks git for no log", b == a and not [x for x in logs if x[0] == "log"] and ih.CALLS["log"] == 1, (logs, ih.CALLS))
        write("a/1.json", 3); git("commit", "-q", "-m", "c3", when=1_700_000_400); logs.clear()
        c = ih.commits(str(G), "a/1.json")
        ranged = [x for x in logs if x[0] == "log"]
        check("History: a new commit of the item asks only for the commits since, and the answer is the whole walk's", c == truth("a/1.json") and len(c) == 4 and ih.CALLS["log"] == 1 and len(ranged) == 1 and ".." in " ".join(ranged[0]), (len(c), ih.CALLS, ranged))
        write("b/2.json", 0); git("commit", "-q", "-m", "other", when=1_700_000_500); logs.clear()
        d_ = ih.commits(str(G), "a/1.json")
        check("History: a commit of another file changes nothing, and the walk is not made again", d_ == c == truth("a/1.json") and ih.CALLS["log"] == 1, (len(d_), ih.CALLS))
        git("mv", "a/1.json", "g1.json"); git("commit", "-q", "-m", "rename", when=1_700_000_600)
        e = ih.commits(str(G), "g1.json")
        check("History: after a rename the new path is walked whole and follows the old one", e == truth("g1.json") and len(e) == 5 and e[-1][2] == "a/1.json" and ih.CALLS["log"] == 2, (e, ih.CALLS))
        write("g1.json", 4); git("commit", "-q", "-m", "c4", when=1_700_000_700)
        f_ = ih.commits(str(G), "g1.json")
        check("History: a commit after the rename is asked for alone, the old names kept", f_ == truth("g1.json") and len(f_) == 6 and ih.CALLS["log"] == 2, (f_, ih.CALLS))
        git("reset", "-q", "--hard", "HEAD~1"); write("g1.json", 5); git("commit", "-q", "-m", "c5", when=1_700_000_800)
        g_ = ih.commits(str(G), "g1.json")
        check("History: a history that was rewritten (the HEAD kept is no ancestor) is walked whole again", g_ == truth("g1.json") and len(g_) == 6 and g_[0][0] not in {x[0] for x in f_} and ih.CALLS["log"] == 3, (g_, ih.CALLS))
        # a merge since the answer kept: the order of the walk is another one, so it is walked whole
        write("g1.json", 6); git("commit", "-q", "-m", "c6", when=1_700_000_900); ih.commits(str(G), "g1.json"); walks = ih.CALLS["log"]
        git("checkout", "-q", "-b", "side"); write("g1.json", 7); git("commit", "-q", "-m", "side", when=1_700_001_000)
        git("checkout", "-q", "main"); write("b/2.json", 8); git("commit", "-q", "-m", "main", when=1_700_001_100); git("merge", "-q", "--no-ff", "-m", "merge", "side", when=1_700_001_200)
        h_ = ih.commits(str(G), "g1.json")
        check("History: a merge since the answer kept makes the walk whole again, and the answer is its", h_ == truth("g1.json") and ih.CALLS["log"] == walks + 1, (len(h_), ih.CALLS, walks))
        # a deletion and a creation of the file since: for the whole walk too
        ih.commits(str(G), "g1.json"); walks = ih.CALLS["log"]
        git("rm", "-q", "g1.json"); git("commit", "-q", "-m", "gone", when=1_700_001_300); write("g1.json", 9); git("commit", "-q", "-m", "back", when=1_700_001_400)
        i_ = ih.commits(str(G), "g1.json")
        check("History: a file deleted and created again since is walked whole, and the answer is the walk's", i_ == truth("g1.json") and ih.CALLS["log"] == walks + 1, (len(i_), ih.CALLS, walks))
        check("History: git failing (no repository) is None, and nothing is kept", ih.commits(str(T / "brain"), "a/1.json") is None and (str(T / "brain"), "a/1.json") not in ih._CACHE)
    finally:
        ih._git = real_git
    # the two renderers read it through the module
    from stackshot.web import render as old_render
    from stackshot.web.ui import render as ui_render
    H = T / "histstore"; (H / "a").mkdir(parents=True)
    for fn in ("projects.json", "next-id", "anchors.json"): (H / fn).write_text((T / "store" / fn).read_text())
    git("init", "-q", "-b", "main", cwd=H)
    def put(n, when):
        (H / "a/7.json").write_text(json.dumps({"id": "7", "subject": "[home] seven", "description": "d", "status": "open", "updated": when, "state_updated": when, "confirmed": when, "written_by": "w",
                                                "metadata": {"project": "projects/alpha", "n": n}}))
        git("add", "a/7.json", cwd=H); git("commit", "-q", "-m", f"v{n}", when=when, cwd=H)
    put(0, now0 - 900); put(1, now0 - 600)
    for label, mod in (("web/render.py", old_render), ("web/ui/render.py", ui_render)):
        bd = mod.Board(str(H)); row = next(r for r in bd.rows if r["gid"] == "a7"); ih._CACHE.clear(); ih.CALLS["log"] = 0
        v1 = bd.item_versions(row); v2 = bd.item_versions(row)
        check(f"{label} Board.item_versions: two reads, one walk of the history, the same versions", v1 == v2 and len(v1) >= 2 and ih.CALLS["log"] == 1, (len(v1), len(v2), ih.CALLS))
        put(len(v1) + 5, now0 - 100 * len(v1)); bd2 = mod.Board(str(H)); v3 = bd2.item_versions(next(r for r in bd2.rows if r["gid"] == "a7"))
        check(f"{label} Board.item_versions: a commit since is in the next read, with no new walk", len(v3) == len(v1) + 1 and ih.CALLS["log"] == 1, (len(v1), len(v3), ih.CALLS))
        git("reset", "-q", "--hard", "HEAD~1", cwd=H)

    # ---- 3  the page times of a brain
    from stackshot.projects import pages
    B = T / "brainrepo"; (B / "projects").mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=B)
    (B / "projects/x.md").write_text("# x\n"); git("add", "projects/x.md", cwd=B); git("commit", "-q", "-m", "x", when=1_700_000_000, cwd=B)
    pages._GT_CACHE.clear(); pages.GT_WALKS[0] = 0
    t1 = pages.git_times(("projects",), str(B)); t1b = pages.git_times(("projects",), str(B))
    check("git_times: the whole walk once for the same HEAD, the same answer", t1 == t1b == {"projects/x.md": 1_700_000_000} and pages.GT_WALKS[0] == 1, (t1, pages.GT_WALKS))
    t1b["projects/x.md"] = 5; t1c = pages.git_times(("projects",), str(B))
    check("git_times: a caller changing the answer does not change the one kept", t1c == {"projects/x.md": 1_700_000_000}, t1c)
    (B / "projects/y.md").write_text("# y\n"); (B / "projects/x.md").write_text("# x2\n"); git("add", "-A", cwd=B); git("commit", "-q", "-m", "y", when=1_700_000_900, cwd=B)
    t2 = pages.git_times(("projects",), str(B))
    check("git_times: a new commit is read on the next call (x is newer, y is there)", t2 == {"projects/x.md": 1_700_000_900, "projects/y.md": 1_700_000_900} and pages.GT_WALKS[0] == 2, (t2, pages.GT_WALKS))
    check("git_times: a second brain is kept apart", pages.git_times(("projects",), str(B)) == t2 and pages.GT_WALKS[0] == 2 and len(pages._GT_CACHE) == 1)
    check("git_times: a directory that is no repository is {} and is not kept", pages.git_times(("projects",), str(T / "state")) == {} and len(pages._GT_CACHE) == 1)
except Exception:
    import traceback; traceback.print_exc(); fails.append("scenario raised")
finally:
    print(f"{len(ran) - len(fails)}/{len(ran)} checks passed"); sys.stdout.flush(); os._exit(1 if fails else 0)
