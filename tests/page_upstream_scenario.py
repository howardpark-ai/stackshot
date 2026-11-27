"""Scenario test for the page edits a pages checkout has not pulled yet (page_upstream.py): a bare repository stands in for the pages' remote, a writer's clone edits
and pushes, and the server's checkout is a second clone that nothing here pulls. Fixture data only: no live store, no network, only local repositories.

Covers: a client box's reminder is dropped at the first prompt after a pushed edit; the client API's page-ts answers with the fetched edit when the caller says since
when it needs one, off the event loop, and fetches nothing without that or when the copy already satisfies it; the server's own debt settles on a fetched edit
without a board write ever waiting, a strict one only on a Current-state edit; the checkout's working tree, branch, remote-tracking ref and FETCH_HEAD stay as they
were; the fetch brings no tags, starts no housekeeping and asks for no password; one fetch at a time (calls at once included), throttled; a remote that hangs costs a
caller at most the wait and is ended at the limit; a failed fetch, a copy with no upstream and a read-only standby answer as the copy does; fetches that fail come
further apart, and a lock file left on the ref is removed once it is old; a page new, removed or put back on the remote under a strict debt; a read that fails
settles nothing; the fetched edit is read once a page, however many owe it.

    tests/run-suite page_upstream        -> exit 0 / 1"""
import contextlib, io, json, os, re, subprocess, sys, threading, time, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="pageupstreamtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                 ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet",
                  GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")       # the fixtures' git reads no config of the machine's
for d in ("store/a", "fleet/a", "state/site", "secrets", "touch", "writer/projects"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

def page(state="- the call is open.", timeline=""):
    return f"---\ntitle: Alpha\ntype: project\n---\n# Alpha\n\n## Current state\n\n{state}\n\n## Timeline\n\n- **2026-10-01** | ops - opened\n{timeline}"
def git(where, *a, at=None):
    env = dict(os.environ, **({"GIT_AUTHOR_DATE": f"{at} +0000", "GIT_COMMITTER_DATE": f"{at} +0000"} if at else {}))
    r = subprocess.run(["git", "-C", str(where), "-c", "user.name=t", "-c", "user.email=t@t.invalid", *a], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, (a, r.stderr)
    return r.stdout.strip()

KEY, A = "projects/alpha", "11111111-1111-4111-8111-111111111111"
REMOTE, WRITER, BRAIN = T / "remote.git", T / "writer", T / "brain"
t0 = int(time.time())
git(T, "init", "-q", "--bare", "-b", "main", str(REMOTE))
git(WRITER, "init", "-q", "-b", "main"); (WRITER / "projects/alpha.md").write_text(page()); (WRITER / "projects/beta.md").write_text(page())
git(WRITER, "add", "-A"); git(WRITER, "commit", "-qm", "first", at=t0 - 3000)
git(WRITER, "remote", "add", "origin", str(REMOTE)); git(WRITER, "push", "-q", "origin", "main")
git(T, "clone", "-q", str(REMOTE), str(BRAIN))
for f in BRAIN.glob("projects/*.md"): os.utime(f, (t0 - 3000, t0 - 3000))        # pulled long ago: the file's write time says nothing newer than its commit

def push(text, at, name="alpha"):
    (WRITER / f"projects/{name}.md").write_text(text); git(WRITER, "commit", "-qam", "edit", at=at); git(WRITER, "push", "-q", "origin", "main")

def untouched():
    """What of the server's checkout a pull or a writer there would care about."""
    return (git(BRAIN, "rev-parse", "HEAD"), git(BRAIN, "rev-parse", "refs/remotes/origin/main"), git(BRAIN, "status", "--porcelain"),
            (BRAIN / "projects/alpha.md").read_text(), (BRAIN / "projects/alpha.md").stat().st_mtime, (BRAIN / ".git/FETCH_HEAD").exists())

sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.core import readonly as _ro
from stackshot.projects import pages as pg, page_upstream as up
from stackshot.web import server
from stackshot.web import page_debts as pdebts
from stackshot.web.routes import client_api as routes
from stackshot.service import client_reads as reads
from stackshot.fleet import client

def done():
    """Wait for the fetch under way, if any."""
    run = up._RUNS.get(pg.BRAIN)
    if run: assert run[1].wait(30), "a fetch never ended"
def fresh(): done(); up._RUNS.clear()
def page_ts(since=None, key=KEY):
    st, _, body = reads._client_get("page-ts", {"key": key, **({"since": str(since)} if since is not None else {})})
    assert st == 200, (st, body)
    return json.loads(body)["ts"]
def took(fn):
    a = time.monotonic(); r = fn(); return r, time.monotonic() - a
def owe(settle="ct", ts=None): pdebts._owed_save({KEY: {A: {"ts": ts or t0, "item": "a1", "settle": settle}}})
def owed(): return KEY in pdebts._owed_load()

SINCE = t0 - 300        # a board write at t0, less the page rule's slack
before = untouched()
check("fixture: the copy's page is older than the board write", pg.page_ts(KEY) == t0 - 3000, pg.page_ts(KEY))

# ---- 1. no edit anywhere: the answers are the copy's, the debt stays
owe(); pdebts._owed_settle(); done()
check("no edit on the remote: the debt stays after the fetch", owed() and KEY in pdebts._owed_settle())
fresh(); check("no edit on the remote: page-ts answers the copy's time", page_ts(SINCE) == t0 - 3000, page_ts(SINCE))

# ---- 2. an edit pushed, the copy not pulled
edited = page(state="- the vendor is chosen.")
push(edited, at=t0 + 5)
fresh(); check("page-ts with no since answers the copy's time and begins no fetch", page_ts() == t0 - 3000 and not up._RUNS, up._RUNS)
check("page-ts whose since the copy already satisfies begins no fetch", page_ts(t0 - 4000) == t0 - 3000 and not up._RUNS, up._RUNS)
for bad in ("", "abc", "-5", "1.5", "nan", "9" * 40, "²"):
    st, _, body = reads._client_get("page-ts", {"key": KEY, "since": bad})
    check(f"a since of {bad[:8]!r} is not read: the copy's time, no fetch", st == 200 and json.loads(body)["ts"] == t0 - 3000 and not up._RUNS, (st, body))
got, secs = took(lambda: page_ts(SINCE))
check("page-ts with since answers the fetched edit's time at the first read", got == t0 + 5, (got, secs))
check("…well inside the client's 6 s", secs < up.WAIT + 1, secs); print(f"page-ts, a fetch from a local remote: {secs:.2f} s")
check("the fetch moved one ref of its own and nothing else of the checkout", untouched() == before and git(BRAIN, "rev-parse", up.REF) == git(WRITER, "rev-parse", "HEAD"), (before, untouched()))
check("…so the copy's own page still reads as before", pg.page_ts(KEY) == t0 - 3000)

# ---- 3. the client box's reminder
(T / "touch" / f"{A}.json").write_text(json.dumps({"touches": {KEY: {"ts": t0, "task": "a1", "settle": "ct"}}}))
real_reads_local, real_api = pg.reads_local, pg._api
SENT = []
def over_api(what, key="", timeout=6.0, **extra):
    SENT.append((what, key, extra)); pg.reads_local = real_reads_local          # the server's half reads its own copy
    try: st, _, body = reads._client_get(what, {"key": key, **extra})
    finally: pg.reads_local = away
    return body if st == 200 else None
away = lambda base=None: False
fresh(); pg.reads_local, pg._api = away, over_api
try: stale, secs = took(lambda: pg.stale_touches(A))
finally: pg.reads_local, pg._api = real_reads_local, real_api
check("client box: the first prompt after the pushed edit drops the reminder", stale == [] and KEY not in pg.load_state(A).get("touches", {}), (stale, SENT))
check("…and it said since when it needs the edit", SENT and all(w == "page-ts" and k == KEY and e == {"since": str(SINCE)} for w, k, e in SENT), SENT)

# ---- 4. the server's own debt (a board write's reply, the nag, the move to the keeper)
delayed, runs = T / "delayed-upload-pack", T / "delayed.log"        # the remote's end of a fetch: notes the run and what it was told about prompts, then answers after 2 s
delayed.write_text(f'#!/bin/sh\necho "prompt=$GIT_TERMINAL_PROMPT" >> {runs}\nsleep 2\nexec git upload-pack "$@"\n'); delayed.chmod(0o755)
def delayed_runs(): return runs.read_text().split() if runs.exists() else []
git(WRITER, "tag", "fixture-tag"); git(WRITER, "push", "-q", "origin", "fixture-tag")
git(BRAIN, "config", "remote.origin.uploadpack", str(delayed))
words = []; _Popen = subprocess.Popen
class Spy(_Popen):
    def __init__(self, args, *a, **k):
        if "fetch" in args: words.append(list(args))
        super().__init__(args, *a, **k)
kept_prompt = os.environ.get("GIT_TERMINAL_PROMPT"); os.environ["GIT_TERMINAL_PROMPT"] = "1"
fresh(); git(BRAIN, "update-ref", "-d", up.REF); owe(); subprocess.Popen = Spy
try:
    d, secs = took(pdebts._owed_settle)
    check("server: with nothing fetched yet the call does not wait for the fetch it begins", up._RUNS and not up._RUNS[pg.BRAIN][1].is_set() and secs < 1.0 and owed(), secs)
    done()
finally:
    subprocess.Popen = _Popen
    if kept_prompt is None: os.environ.pop("GIT_TERMINAL_PROMPT")
    else: os.environ["GIT_TERMINAL_PROMPT"] = kept_prompt
check("the fetch is told never to ask for a password, whatever the server's own environment says", delayed_runs() == ["prompt=0"], delayed_runs())
check("…brings no tag with it", git(BRAIN, "tag", "-l") == "", git(BRAIN, "tag", "-l"))
check("…and starts no housekeeping of the repository, fetches no submodule and writes no FETCH_HEAD", len(words) == 1 and "gc.auto=0" in words[0] and "maintenance.auto=false" in words[0]
      and all(words[0][words[0].index(v) - 1] == "-c" for v in ("gc.auto=0", "maintenance.auto=false")) and words[0].index("maintenance.auto=false") < words[0].index("fetch")
      and {"--no-tags", "--no-recurse-submodules", "--no-write-fetch-head", "--refmap="} <= set(words[0]), words)
git(BRAIN, "config", "--unset", "remote.origin.uploadpack")
check("server: once fetched, the Current-state edit settles the strict debt", KEY not in pdebts._owed_settle() and not owed(), pdebts._owed_load())
check("…the checkout is still as it was", untouched() == before)
owe(ts=t0 + 3600); fresh(); pdebts._owed_settle(); done()
check("server: a fetched edit older than a later board write settles nothing", KEY in pdebts._owed_settle())

push(edited + "- **2026-10-22** | ops - a timeline line\n", at=t0 + 7200)
owe(ts=t0 + 7000); fresh(); pdebts._owed_settle(); done()
check("server: a fetched timeline line alone leaves a strict debt", KEY in pdebts._owed_settle(), pdebts._owed_load())
owe("any", ts=t0 + 7000)
check("server: …and settles a debt that any page write settles", KEY not in pdebts._owed_settle(), pdebts._owed_load())
push(page(state="- beta moved."), at=t0 + 7300, name="beta"); owe("any", ts=t0 + 7600); fresh(); pdebts._owed_settle(); done()      # since = t0 + 7300: the other page's edit is that late, this page's last one is not
check("server: an edit of another page settles nothing", KEY in pdebts._owed_settle(), pdebts._owed_load())

# ---- 5. one fetch at a time, throttled
fresh(); up.refresh(pg.BRAIN, 10); first = up._RUNS[pg.BRAIN]
push(page(state="- signed."), at=t0 + 9000)
up.refresh(pg.BRAIN, 10)
check("a second call within EVERY seconds begins no fetch", up._RUNS[pg.BRAIN] is first and up.edit_ts(KEY, t0 + 8000) == 0, up._RUNS)
every, up.EVERY = up.EVERY, 0.0
got = up.edit_ts(KEY, t0 + 8000, wait=10)
check("…and after it the next call fetches again", up._RUNS[pg.BRAIN] is not first and got == t0 + 9000, got)
up.EVERY = every
git(BRAIN, "config", "remote.origin.uploadpack", str(delayed)); runs.unlink()
fresh(); every, up.EVERY = up.EVERY, 0.0          # no pause between fetches: only the one under way holds the others back
gate = threading.Barrier(12)
def at_once(): gate.wait(10); up.refresh(pg.BRAIN)
many = [threading.Thread(target=at_once) for _ in range(12)]
for x in many: x.start()
for x in many: x.join(20)
done(); up.EVERY = every
check("twelve calls at once begin one fetch", len(delayed_runs()) == 1, delayed_runs())
git(BRAIN, "config", "--unset", "remote.origin.uploadpack")
git(BRAIN, "pull", "-q", "--ff-only")
check("once the copy has pulled, nothing is left that only the fetched ref holds", up.edit_ts(KEY, 0) == 0 and pg.page_ts(KEY) >= t0 + 9000)
for f in BRAIN.glob("projects/*.md"): os.utime(f, (t0 - 3000, t0 - 3000))

# ---- 6. a remote that hangs
slow, slowlog = T / "slow-upload-pack", T / "slow.pids"
slow.write_text(f"#!/bin/sh\necho $$ >> {slowlog}\nexec sleep 20\n"); slow.chmod(0o755)
git(BRAIN, "config", "remote.origin.uploadpack", str(slow))
push(page(state="- signed and filed."), at=t0 + 9500)
wait, limit, grace = up.WAIT, up.LIMIT, up.END_GRACE
up.LIMIT, up.END_GRACE = 6.0, 1.0
late = t0 + 9400
fresh(); err = io.StringIO()
with contextlib.redirect_stderr(err):
    owe("any", ts=late + 300); _, write = took(pdebts._owed_settle)          # the call that begins the fetch: the whole wait is still ahead
    under_way = not up._RUNS[pg.BRAIN][1].is_set()
    got, one = took(lambda: page_ts(late))
    got2, two = took(lambda: page_ts(late))
    check("hanging remote: a board write's settle begins the fetch and never waits for it", under_way and write < 1.0 and owed(), (write, under_way))
    check("hanging remote: the first read waits the bounded time and answers the copy's time", got < late and wait - write - 0.3 <= one < wait + 1.5, (got, one, write))
    check("…a read after the wait has passed answers at once", got2 == got and two < 1.0, two)
    done()
print(f"hanging remote: first page-ts {one:.2f} s, the next {two:.2f} s, the server's settle {write:.2f} s")
pids = slowlog.read_text().split()
check("one fetch only was begun while it hung", len(pids) == 1, pids)
def running(pid):
    try: return pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1][0] != "Z"
    except OSError: return False
end = time.monotonic() + 5
while time.monotonic() < end and running(pids[0]): time.sleep(0.05)
check("…ended at the limit with what it had started", not running(pids[0]), pids)
check("…and said once on stderr, naming the copy", err.getvalue().count("page upstream:") == 1 and pg.BRAIN in err.getvalue() and "still running after 6 s" in err.getvalue(), err.getvalue())
check("…leaving no lock on the ref", not list((BRAIN / ".git").rglob("*.lock")), list((BRAIN / ".git").rglob("*.lock")))
up.LIMIT, up.END_GRACE = limit, grace
git(BRAIN, "config", "--unset", "remote.origin.uploadpack")

# ---- 7. what cannot be fetched answers as the copy does
url = git(BRAIN, "config", "remote.origin.url")
up._FAILS.clear(); git(BRAIN, "config", "remote.origin.url", str(T / "gone.git"))
err = io.StringIO(); every, up.EVERY = up.EVERY, 0.0
with contextlib.redirect_stderr(err):
    fresh(); a_ = page_ts(late); done(); b_ = page_ts(late); done()
check("a remote that is not there: the copy's time, each time", a_ == b_ and a_ < late, (a_, b_))
check("…said once while it lasts", err.getvalue().count("page upstream:") == 1 and "git fetch ended with status" in err.getvalue(), err.getvalue())
git(BRAIN, "config", "remote.origin.url", url)
fresh(); check("…and read again once the remote is back", page_ts(late) == t0 + 9500)
done(); check("a fetch that works clears the count of failed ones", pg.BRAIN not in up._FAILS, up._FAILS)
git(BRAIN, "config", "remote.origin.url", str(T / "gone.git")); err = io.StringIO()
with contextlib.redirect_stderr(err): fresh(); up.refresh(pg.BRAIN, 10); done()
check("…so the next failure is said again", err.getvalue().count("page upstream:") == 1, err.getvalue())

# fetches that fail come further apart: EVERY, then double with each failure in a row, up to BACKOFF
def aged(seconds):
    done(); up._RUNS[pg.BRAIN] = (time.monotonic() - seconds, up._RUNS[pg.BRAIN][1])
def begins():
    was = up._RUNS[pg.BRAIN]; up.refresh(pg.BRAIN, 10); done(); return up._RUNS[pg.BRAIN] is not was
up.EVERY = 100.0
with contextlib.redirect_stderr(io.StringIO()):
    up._FAILS.clear(); fresh(); up.refresh(pg.BRAIN, 10)          # one failure
    aged(150); a_ = begins(); aged(201); b_ = begins()             # the next after 200
    aged(250); c_ = begins(); aged(301); d_ = begins()             # then 300, the most
    for _ in range(4): aged(301); begins()
    aged(301); e_ = begins()
check("after one failed fetch the next comes after twice the pause, not before", (a_, b_) == (False, True), (a_, b_))
check("…and the pause grows no further than BACKOFF, however many have failed", (c_, d_, e_) == (False, True, True), (c_, d_, e_))
git(BRAIN, "config", "remote.origin.url", url)
aged(301); a_ = begins(); aged(101); b_ = begins()
check("…and a fetch that works puts the pause back", (a_, b_) == (True, True), (a_, b_))
up.EVERY = every

# a lock file a fetch ended outright left on the ref
lock = pathlib.Path(git(BRAIN, "rev-parse", "--path-format=absolute", "--git-path", f"{up.REF}.lock")); lock.parent.mkdir(parents=True, exist_ok=True)
push(page(state="- one more thing."), at=t0 + 9600)
lock.write_text(""); err = io.StringIO(); up._FAILS.clear()
with contextlib.redirect_stderr(err): fresh(); got = page_ts(t0 + 9550); done()
check("a lock file on the ref that could still be a fetch's is left alone: the fetch fails, the copy answers", got < t0 + 9550 and lock.exists() and up._FAILS.get(pg.BRAIN) == 1, (got, err.getvalue()))
os.utime(lock, (time.time() - up.STALE - 60,) * 2); err = io.StringIO()
with contextlib.redirect_stderr(err): fresh(); got = page_ts(t0 + 9550); done()
check("one left behind longer than STALE is removed, said, and the fetch works again", got == t0 + 9600 and not lock.exists() and pg.BRAIN not in up._FAILS
      and "removed a lock file left behind" in err.getvalue(), (got, lock.exists(), err.getvalue()))

git(BRAIN, "update-ref", "-d", up.REF); git(BRAIN, "branch", "--unset-upstream")
err = io.StringIO()
with contextlib.redirect_stderr(err): fresh(); got = page_ts(late); done()
check("a branch with no upstream: nothing is fetched, nothing is said", got < late and err.getvalue() == "" and not (BRAIN / ".git" / up.REF).exists(), (got, err.getvalue()))
git(BRAIN, "branch", "--set-upstream-to=origin/main")

fresh(); _ro._reload_for_test(True)
try: got = page_ts(late); owe("any", ts=late + 300); pdebts._upstream_settles(KEY, A, pdebts._owed_load()[KEY][A], pdebts._upstream_ts(KEY))
finally: _ro._reload_for_test(False)
check("a read-only standby begins no fetch", got < late and not up._RUNS, (got, up._RUNS))
check("a copy that is not there begins no fetch", up.refresh(str(T / "no-such-copy"), 1) is None and not up._RUNS)

# ---- 8. the route: off the event loop
from starlette.testclient import TestClient
H = {"Authorization": "Bearer " + open(client.mint("box-far")).read().strip()}
threads = []; _real = routes._client_get
def spy(what, params):
    threads.append(threading.current_thread()); return _real(what, params)
routes._client_get = spy
try:
    with TestClient(server.mcp.http_app()) as c:
        fresh()
        r = c.get("/client/page-ts", params={"key": KEY, "since": str(late)}, headers=H)
        no = c.get("/client/page-ts", params={"key": KEY, "since": str(late)})
        c.portal.call(lambda: threads.append(threading.current_thread()))        # the event loop's own thread
finally: routes._client_get = _real
check("http: the machine's token gets the fetched edit's time", r.status_code == 200 and r.json() == {"key": KEY, "ts": t0 + 9600}, (r.status_code, r.text))
check("http: no token is refused as before", no.status_code == 401, no.status_code)
check("http: the read runs off the event loop", len(threads) == 2 and threads[0] is not threads[1], threads)
done()

# ---- 9. a strict debt on a page that is new, removed or put back on the remote
def remote_commit(at, what):
    git(WRITER, "add", "-A"); git(WRITER, "commit", "-qm", what, at=at); git(WRITER, "push", "-q", "origin", "main")
def owe_on(key, ts, settle="ct"): pdebts._owed_save({key: {A: {"ts": ts, "item": "a1", "settle": settle}}})
def settled(key):
    """A settle with the remote's state fetched."""
    fresh(); up.refresh(pg.BRAIN, 10); done(); return key not in pdebts._owed_settle()
BETA, NEW = "projects/beta", "projects/gamma"
(WRITER / "projects/beta.md").unlink(); remote_commit(t0 + 10000, "remove beta")
(WRITER / "projects/beta.md").write_text(page(state="- beta is back.")); (WRITER / "projects/gamma.md").write_text(page(state="- gamma starts.")); remote_commit(t0 + 11000, "beta back, gamma new")
owe_on(NEW, t0 + 11000); check("strict: a page that is new on the remote settles the debt", settled(NEW), pdebts._owed_load())
owe_on(BETA, t0 + 11000); check("strict: a page removed before the board write and put back after it settles the debt", settled(BETA), pdebts._owed_load())
(WRITER / "projects/beta.md").write_text(page(state="- beta changed again.")); remote_commit(t0 + 12000, "beta changes")
(WRITER / "projects/beta.md").unlink(); remote_commit(t0 + 12010, "beta removed")
owe_on(BETA, t0 + 12000); check("strict: a page the remote no longer holds settles nothing", not settled(BETA), pdebts._owed_load())

# ---- 10. a read that fails or is slow cannot tell, and the debt stays
push(page(state="- the order went out."), at=t0 + 13000)
fresh(); up.refresh(pg.BRAIN, 10); done()
_run = subprocess.run
READS = (("the look for the version at the board write", lambda a: any(str(x).startswith("--before=") for x in a)),
         ("the look for the page in that version", lambda a: "ls-tree" in a),
         ("the read of that version", lambda a: "show" in a and not str(a[-1]).startswith(up.REF)),
         ("the read of the fetched version", lambda a: "show" in a and str(a[-1]).startswith(up.REF)))
for what, hit in READS:
    for how in ("is slow", "fails"):
        met = []
        def broken(args, *a, **k):
            if isinstance(args, list) and hit(args):
                met.append(args)
                if how == "is slow": raise subprocess.TimeoutExpired(args, up.READ_LIMIT)
                return subprocess.CompletedProcess(args, 128, "", "fatal: no")
            return _run(args, *a, **k)
        owe(ts=t0 + 13000); subprocess.run = broken; up._READ_FAILED.clear()      # a failed read is not repeated for the back-off: each case starts without one
        try: left = pdebts._owed_settle()
        finally: subprocess.run = _run
        check(f"strict: when {what} {how}, the debt stays", KEY in left and owed() and met, (met, left))
owe(ts=t0 + 13000); up._READ_FAILED.clear(); check("strict: …and with every read answered the same edit settles it", KEY not in pdebts._owed_settle())

# ---- 11. the fetched edit is read once a page, whoever owes it, and each debt judged by its own time
B, C = "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
E = lambda ts, settle="any": {"ts": ts, "item": "a1", "settle": settle}
pdebts._owed_save({KEY: {A: E(t0 + 13000, "ct"), B: E(t0 + 13100), C: E(t0 + 13600)}, BETA: {A: E(t0 + 20000), B: E(t0 + 20000)}})
asked = []; _edit_ts = up.edit_ts
up.edit_ts = lambda key, *a, **k: (asked.append(key), _edit_ts(key, *a, **k))[1]
try: left = pdebts._owed_settle()
finally: up.edit_ts = _edit_ts
check("one read of the fetched edit a page in a settle, with several writers owing it", sorted(asked) == [KEY, BETA], asked)
check("…and each debt judged by its own time", list(left.get(KEY, {})) == [C] and sorted(left.get(BETA, {})) == [A, B], left)
done()

# ---- 12. a fetch thread that cannot be started leaves nothing registered, so a later call fetches
fresh(); up._FAILS.clear(); _start = threading.Thread.start; refused = []
def no_thread(self):
    if self.name == "page-upstream": raise RuntimeError("can't start new thread")
    return _start(self)
threading.Thread.start = no_thread
try:
    with contextlib.redirect_stderr(io.StringIO()) as said:
        try: up.refresh(pg.BRAIN, 1)
        except Exception as e: refused.append(e)
finally: threading.Thread.start = _start
check("a thread that cannot be started: the call answers as the copy does (no error) and registers no run", not refused and pg.BRAIN not in up._RUNS, (refused, up._RUNS))
up.refresh(pg.BRAIN, 10)
check("…and the next call begins a fetch that ends (no run waits forever for an event nothing sets)", pg.BRAIN in up._RUNS and up._RUNS[pg.BRAIN][1].wait(30), up._RUNS)
up._FAILS.clear(); done()

# ---- 13. a fetched read that keeps failing is tried once, not once a debtor at every settle, and the debts stay
fresh(); up.refresh(pg.BRAIN, 10); done()
pdebts._owed_save({KEY: {A: E(t0 + 13000, "ct"), B: E(t0 + 13001, "ct"), C: E(t0 + 13002, "ct")}})
reads_of_copy = []; _read0 = up._read
def counting(base, *args):
    if not any(str(x).startswith("HEAD..") for x in args): reads_of_copy.append(args)      # the look for the edit's time is a read of its own, once a page
    return None if "show" in args and str(args[-1]).startswith(up.REF) else _read0(base, *args)
up._read = counting; up._READ_FAILED.clear()
try:
    first = pdebts._owed_settle(); n_first = len(reads_of_copy); reads_of_copy.clear()
    second = pdebts._owed_settle(); n_second = len(reads_of_copy)
finally: up._read = _read0
check("a fetched read that fails is tried once for three debtors of one page", n_first == 1, reads_of_copy or n_first)
check("…and not again at the next settle within the back-off", n_second == 0, n_second)
check("…and every debt stays owed", sorted(first.get(KEY, {})) == sorted([A, B, C]) and sorted(second.get(KEY, {})) == sorted([A, B, C]), (first, second))
backoff, up.READ_BACKOFF = up.READ_BACKOFF, 0.0
try: after = pdebts._owed_settle()
finally: up.READ_BACKOFF = backoff
check("…and once the back-off is over the reads are tried again and settle them", KEY not in after, after)
up._READ_FAILED.clear(); done()

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
