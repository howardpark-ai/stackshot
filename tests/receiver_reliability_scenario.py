"""Scenario test for the reliability of the receivers service (stackshot/anchors/anchorhub): fakes only, no network, no process is started or stopped.

What it covers, each as a scenario on the real code:
  1. Status writes. write_status and persist are called from many threads at once (every receiver's thread reports through them): the file
     always parses for a reader running meanwhile, no writer fails, the last text written is the file's, no temp file is left, and a failed
     replace leaves the old file whole and no temp file behind. (A shared `status.json.tmp` let one thread's rename take the file another thread
     was about to rename: FileNotFoundError, which ended the GitHub poll thread.)
  2. Loop guard. guarded_loop on its own (an exception is logged with the receiver's name, its type, the line and a traceback; the loop waits
     its retry time and goes on; only the stop signal ends it), then the real loop of each receiver (GitHub, Slack, Notion, Google and
     Google's renewals) driven on fakes, with one call that raises once: the pass is logged, the loop goes on, and the next pass does its work.
  3. Google's health. A failed health re-read is tried again after a short wait before Google is marked down: one dropped connection (a broken
     pipe, an SSL EOF) leaves it healthy; the consecutive failures of every try mark it down; an error waiting cannot fix is not retried.
  4. The beats the board judges staleness by agree with the constants the receivers run on, and the rule itself: a healthy receiver whose last
     check is older than twice its beat is stale (exactly twice is not), a receiver that is down, unknown or stamped in the future is not.
     (The board's card and the receivers endpoint are checked in pilot_scenario and board_pages_scenario.)

    tests/run-suite receiver_reliability      → exit 0 / 1"""
import sys, os, re, json, time, types, queue, pathlib, threading, logging, subprocess, ssl
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="rcvrel-")
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's store of sessions
toml, n1 = re.subn(r'(?m)^state = "[^"]*"', f'state = "{tmp}/state"', toml); toml, n2 = re.subn(r'(?m)^secrets = "[^"]*"', f'secrets = "{tmp}/secrets"', toml)
toml, n3 = re.subn(r'(?m)^timezone = "[^"]*"', 'timezone = "Asia/Dubai"', toml)
assert (n1, n2, n3) == (1, 1, 1), (n1, n2, n3)
pathlib.Path(tmp, "stackshot.toml").write_text(toml, encoding="utf-8"); os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
os.environ.pop("ANCHOR_HUB_ALLOW_SELF", None)
EMAIL = "ada@example.test"
sys.path.insert(0, STACK)

_wd = threading.Timer(150, lambda: (print("FAIL: the scenario did not end in 150 s (a loop that never stops)", flush=True), os._exit(3))); _wd.daemon = True; _wd.start()   # a hung loop ends the run, never the machine's time
fails = checks = 0
def check(name, ok, got=None):
    global fails, checks
    checks += 1
    print(("ok:   " if ok else "FAIL: ") + name + ("" if ok else f"\n      got: {str(got)[:700]}"), flush=True)
    if not ok: fails += 1

from stackshot.anchors.anchorhub import core, github as ghr, gworkspace as gw, notion as nr, slack as sl
from stackshot.anchors import receiver_health as rh
import urllib.request, urllib.error

# the service's own folders, as the modules name them (never a spelled-out path)
os.makedirs(core.ADIR, exist_ok=True); os.makedirs(gw.GDIR, exist_ok=True)
pathlib.Path(core.ENVF).write_text("SLACK_USER_TOKEN=xoxp-fixture\nSLACK_APP_TOKEN=xapp-fixture\nNOTION_TOKEN=fixture-token\n")
pathlib.Path(gw.GDIR, f"{EMAIL}.json").write_text("{}")

records: list[str] = []
class Capture(logging.Handler):
    def emit(self, record): records.append(logging.Formatter().format(record))
core.log.addHandler(Capture()); core.log.setLevel(logging.INFO); core.log.propagate = False   # the scenario reads the log itself; it prints no traceback of its own fakes
def logged(pattern): return [r for r in records if re.search(pattern, r)]

ADIR = pathlib.Path(core.ADIR)
def leftovers(): return sorted(p.name for p in ADIR.iterdir() if ".tmp" in p.name)

# ---- 1. status writes from many threads at once
hub = core.Hub(); hub.write_status()
THREADS, ROUNDS = 12, 60
errors: list[str] = []; torn: list[str] = []; reads = [0]; done = threading.Event()
def writer(i):
    try:
        for j in range(ROUNDS):
            with hub.lock: hub.status[f"w{i}"] = j; hub.status.setdefault("receivers", {})[f"r{i}"] = {"ok": True, "checked": core.now_iso()}
            hub.write_status()
    except BaseException as e: errors.append(f"{type(e).__name__}: {e}")
def reader():
    while not done.is_set():
        try: json.load(open(core.STATUS)); reads[0] += 1
        except Exception as e: torn.append(f"{type(e).__name__}: {e}")
ws = [threading.Thread(target=writer, args=(i,)) for i in range(THREADS)]; rd = threading.Thread(target=reader)
rd.start()
for t in ws: t.start()
for t in ws: t.join()
done.set(); rd.join()
final = json.load(open(core.STATUS))
check(f"{THREADS} threads write the status {ROUNDS} times each: no writer fails", not errors, errors[:3])
check("…a reader running meanwhile always finds a whole file", reads[0] > 0 and not torn, (reads[0], torn[:3]))
check("…the last text written is the file's (every thread's last value is in it)", all(final.get(f"w{i}") == ROUNDS - 1 for i in range(THREADS)), {k: v for k, v in final.items() if k.startswith("w")})
check("…and no temp file is left in the state folder", leftovers() == [], leftovers())

before = pathlib.Path(core.STATUS).read_text(); real_replace = core.os.replace
def _boom(a, b): raise OSError("disk full")
core.os.replace = _boom
try:
    try: hub.write_status(); err = ""
    except OSError as e: err = str(e)
finally: core.os.replace = real_replace
check("a status write whose replace fails raises, leaves the old file whole and no temp file behind", err == "disk full" and pathlib.Path(core.STATUS).read_text() == before and leftovers() == [], (err, leftovers()))
check("the status file keeps a readable mode (not the private mode of a fresh temp file)", (os.stat(core.STATUS).st_mode & 0o044) == 0o044, oct(os.stat(core.STATUS).st_mode))

hub.savers["x"] = lambda: {"n": 1}; perr: list[str] = []
def saver():
    try:
        for _ in range(25): hub.persist()
    except BaseException as e: perr.append(f"{type(e).__name__}: {e}")
ps = [threading.Thread(target=saver) for _ in range(8)]
for t in ps: t.start()
for t in ps: t.join()
check("persist from 8 threads at once: no failure, the file parses, no temp file is left", not perr and json.load(open(core.CURSORS))["x"] == {"n": 1} and leftovers() == [], (perr[:3], leftovers()))

# ---- 2. the loop guard
class StopAfter:
    """Stands in for hub.stopping.wait: records each pause without waiting and sets the stop signal after `n` of them."""
    def __init__(self, hub, n, on_wait=None): self.hub, self.n, self.waits, self.on_wait = hub, n, [], on_wait
    def __call__(self, seconds=None):
        self.waits.append(seconds)
        if self.on_wait: self.on_wait(len(self.waits))
        if len(self.waits) >= self.n: self.hub.stopping.set()
        return self.hub.stopping.is_set()
def raise_once(hub, what="health"):
    """hub.<what> raises on its first call, then does its work. Returns the list of its calls."""
    orig = getattr(hub, what); calls: list[tuple] = []
    def f(*a, **k):
        calls.append(a)
        if len(calls) == 1: raise OSError("status file is gone")
        return orig(*a, **k)
    setattr(hub, what, f); return calls
class FastQ(queue.Queue):
    """The trigger queue without the one-second wait of an empty get."""
    def get(self, block=True, timeout=None): return super().get(block=False)

h0 = core.Hub(); passes = []; n_log = len(records)
def flaky():
    passes.append(1)
    if len(passes) == 1: raise ValueError("one bad pass")
h0.stopping.wait = StopAfter(h0, 3)
core.guarded_loop(h0, "unitloop", flaky, every=lambda: 7, retry=3)
check("guarded_loop: a pass that raises does not end the loop; it waits the retry time, then the pass after it runs and waits its own interval",
      len(passes) == 3 and h0.stopping.wait.waits == [3, 7, 7], (len(passes), h0.stopping.wait.waits))
lg = "\n".join(records[n_log:])
check("…the failure is logged with the receiver's name, the exception, the line it came from and a traceback",
      "receiver unitloop" in lg and "ValueError: one bad pass" in lg and "at receiver_reliability_scenario.py:" in lg and "Traceback (most recent call last)" in lg, lg[:400])
h1 = core.Hub(); h1.stopping.set(); ran = []
core.guarded_loop(h1, "stopped", lambda: ran.append(1), every=lambda: 1)
check("…the stop signal ends the loop, before another pass", ran == [], ran)
h2 = core.Hub(); ran = []; h2.stopping.wait = StopAfter(h2, 2)
core.guarded_loop(h2, "slow", lambda: ran.append(1), every=lambda: 60, pause_first=True)
check("…pause_first waits before the first pass", ran == [1] and h2.stopping.wait.waits == [60, 60], (ran, h2.stopping.wait.waits))

# GitHub: the real loop on a fake `gh`
hg = core.Hub(); hg.status["receivers"] = {}
ghr.subprocess = types.SimpleNamespace(run=lambda args, **k: types.SimpleNamespace(returncode=0, stdout=json.dumps({"login": "oliver"}), stderr=""), TimeoutExpired=subprocess.TimeoutExpired)
caught: list = []; ghr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
gh_sleeps: list[float] = []
def _gh_sleep(s):
    gh_sleeps.append(s)
    if len(gh_sleeps) >= 3: hg.stopping.set()
ghr.time = types.SimpleNamespace(time=time.time, sleep=_gh_sleep)
ghr.run(hg); calls = raise_once(hg); n_log = len(records)
check("github: a start announces that its first pass may take a while (the board counts no age until the pass ends or the time is up)",
      600 - 5 <= hg.status["hold"]["github"] - time.time() <= 600 + 5 and ghr.FIRST_PASS == 600, hg.status.get("hold"))
caught[0]()
check("…the first pass's own check clears the announcement", "github" not in hg.status["hold"], hg.status["hold"])
check("github: a pass whose status report raises is logged and the loop goes on; the next pass reports GitHub healthy", len(calls) >= 2 and hg.status["receivers"]["github"]["ok"] is True, (len(calls), hg.status["receivers"]))
check("…the loop waited a poll interval after the failed pass and then ran on the dot, and it ended on the stop signal", gh_sleeps[0] == ghr.GHPOLL and 0 < gh_sleeps[1] <= ghr.GHPOLL and len(gh_sleeps) == 3, gh_sleeps)
check("…the failure names the receiver", any("receiver github" in r and "status file is gone" in r for r in records[n_log:]), records[n_log:][:2])

# Slack: the real watch thread on the fake socket and Web API
class Web:
    def __init__(self, token=None): pass
    def auth_test(self): return {"user_id": "UME", "url": "https://fixture.slack.test/"}
    def conversations_info(self, channel): return {"channel": {"name": channel.lower()}}
    def conversations_members(self, channel): return {"members": []}
    def users_info(self, user): return {"user": {"real_name": user, "name": user}}
    def conversations_history(self, channel, limit=100, oldest=None): return {"messages": []}
class Socket:
    def __init__(self, app_token=None, web_client=None): self.socket_mode_request_listeners = []
    def connect(self): pass
    def close(self): pass
    def is_connected(self): return True
sys.modules.update({"slack_sdk": types.SimpleNamespace(WebClient=Web), "slack_sdk.socket_mode": types.SimpleNamespace(SocketModeClient=Socket),
                    "slack_sdk.socket_mode.request": types.SimpleNamespace(SocketModeRequest=object),
                    "slack_sdk.socket_mode.response": types.SimpleNamespace(SocketModeResponse=lambda envelope_id: envelope_id)})
hs = core.Hub(); hs.status["receivers"] = {}; caught.clear()
sl.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
sl.run(hs); calls = raise_once(hs); hs.stopping.wait = StopAfter(hs, 3); n_log = len(records)
caught[0]()
check("slack: a pass whose health report raises is logged and the watch goes on; the next pass reports Slack healthy", len(calls) >= 2 and hs.status["receivers"]["slack"]["ok"] is True, (len(calls), hs.status["receivers"]))
check("…it waited a minute before the first pass and between the others, and ended on the stop signal", hs.stopping.wait.waits == [sl.WATCH] * 3, hs.stopping.wait.waits)
check("…the failure names the receiver", any("receiver slack" in r and "status file is gone" in r for r in records[n_log:]), records[n_log:][:2])

# Notion: the real loop; the API is a fake that is always unreachable (a failed check is logged, not fatal), so the work seen is the calls it makes;
# the first pass ends by writing the status, which raises once
PAGE = "a" * 32
api_calls: list[str] = []; armed = [False]
hn = core.Hub(); hn.status["receivers"] = {}; hn.triggers = FastQ(); hn.bindings = {f"notion:{PAGE}": {"sess"}}
def _urlopen(req, timeout=None):
    api_calls.append(req.full_url)
    if armed[0]: hn.stopping.set()          # the pass after the failed one made its call: end the loop after it
    raise urllib.error.URLError("offline")
real_urlopen = urllib.request.urlopen; urllib.request.urlopen = _urlopen
nr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
try:
    caught.clear(); nr.run(hn); calls = raise_once(hn, "write_status"); n_log = len(records)
    def _arm(n): armed[0] = True; hn.triggers.put(("notion", PAGE))      # during the pause after the failed pass a webhook event arrives
    hn.stopping.wait = StopAfter(hn, 99, on_wait=_arm); n_calls = len(api_calls)
    caught[0]()
finally: urllib.request.urlopen = real_urlopen
check("notion: with a page bound the health re-read reports even when the page is polled (the poll does not take its place)", hn.status["receivers"].get("notion", {}).get("ok") is False, hn.status["receivers"])
check("notion: a pass whose status write raises is logged and the loop goes on; the next pass reads the page that was pushed", len(calls) >= 2 and len(api_calls) > n_calls and hn.stopping.is_set(), (len(calls), n_calls, len(api_calls)))
check("…the failure names the receiver", any("receiver notion" in r and "status file is gone" in r for r in records[n_log:]), records[n_log:][:2])

# Google: the real loop and the renewals thread on a fake Google API
class Api:
    """Any chain of attribute calls ending in .execute() reaches script(key, kwargs), key like "gmail.users.history.list"."""
    def __init__(self, root, path=(), kw=None): self.root, self.path, self.kw = root, path, kw or {}
    def __getattr__(self, name):
        if name == "execute": return lambda: self.root.handle(".".join(self.path), self.kw)
        return lambda *a, **k: Api(self.root, self.path + (name,), k)
class FakeGoogle:
    def __init__(self): self.calls: list[str] = []; self.script: dict = {}
    def service(self, name): return Api(self, (name,))
    def handle(self, key, kw):
        self.calls.append(key)
        if key in self.script: return self.script[key](len([c for c in self.calls if c == key]))
        return {"drive.changes.getStartPageToken": {"startPageToken": "p1"}, "gmail.users.getProfile": {"historyId": "h1"},
                "drive.changes.list": {"changes": [], "newStartPageToken": "p2"}, "gmail.users.history.list": {"history": [], "historyId": "h2"}}.get(key, {})
def _module(name, **attrs):
    m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m
class _HttpRequest:
    def execute(self, *a, **k): return {}
G = FakeGoogle()
for _n in ("google", "google.oauth2", "google.auth", "google.auth.transport", "googleapiclient"): _module(_n)      # the Google libraries are not in the suites' environment: fakes stand in for them
_module("google.oauth2.credentials", Credentials=types.SimpleNamespace(from_authorized_user_file=lambda f: types.SimpleNamespace(valid=True)))
_module("google.auth.transport.requests", Request=object)
_module("googleapiclient.discovery", build=lambda name, version, credentials=None, cache_discovery=False: G.service(name))
_module("googleapiclient.http", HttpRequest=_HttpRequest)
gw._gmail_poll = lambda: 10 ** 10                    # no fallback poll in these runs: the only poll is the health re-read
gw.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)), RLock=threading.RLock)
G.script["drive.changes.watch"] = lambda n: (_ for _ in ()).throw(RuntimeError("no push in this test"))
def start_google(script=None, bindings=None):
    """A new hub with the Gmail anchor bound (or `bindings`) and the Google receiver started on the fake API. Returns (hub, loop target, renewals target)."""
    G.calls.clear(); G.script = {k: v for k, v in G.script.items() if k == "drive.changes.watch"}; G.script.update(script or {})
    h = core.Hub(); h.status["receivers"] = {}; h.triggers = FastQ(); h.bindings = {"gmail:thread1": {"sess"}} if bindings is None else bindings
    caught.clear(); gw.run(h)
    return h, next(t for t in caught if t.__name__ == "loop"), next(t for t in caught if t.__name__ == "renewals")
def stop_after_health(h):
    orig = h.health
    def f(*a, **k):
        try: return orig(*a, **k)
        finally: h.stopping.set()
    h.health = f
check("the retry waits of Google's health re-read are short (a couple of tries, seconds apart)", 1 <= len(gw.HEALTH_RETRY) <= 3 and max(gw.HEALTH_RETRY) <= 10, gw.HEALTH_RETRY)
gw.HEALTH_RETRY = (0.0, 0.0)           # the scenarios below do not wait

# the loop guard on Google's loop: the health report raises once; a trigger arrives meanwhile and its poll runs
h, loop, renew = start_google()
calls = raise_once(h); n_log = len(records)
def _gtrigger(n): h.triggers.put(("gmail", EMAIL))
h.stopping.wait = StopAfter(h, 99, on_wait=_gtrigger)
orig_handle = G.handle
def _handle(key, kw):
    r = orig_handle(key, kw)
    if key == "gmail.users.history.list" and len([c for c in G.calls if c == key]) >= 2: h.stopping.set()      # the poll of the pushed event
    return r
G.handle = _handle
try: loop()
finally: G.handle = orig_handle
check("google: a pass whose health report raises is logged and the loop goes on; the next pass polls the mailbox that was pushed",
      len(calls) == 1 and G.calls.count("gmail.users.history.list") >= 2, (len(calls), G.calls))
check("…the failure names the receiver", any("receiver google" in r and "status file is gone" in r for r in records[n_log:]), records[n_log:][:2])

# the renewals thread: its status write raises once
h, loop, renew = start_google()
calls = raise_once(h, "write_status"); n_log = len(records); h.stopping.wait = StopAfter(h, 3)
renew()
check("google renewals: a pass whose status write raises is logged and the thread goes on to its next pass", len(calls) == 3 and h.stopping.wait.waits == [300, 300, 300] and any("receiver google renewals" in r for r in records[n_log:]), (len(calls), h.stopping.wait.waits))

# ---- 3. Google's health re-read is tried again before Google is marked down
def google_health(script):
    h, loop, renew = start_google(script); stop_after_health(h)
    loop()
    return h.status["receivers"]["google"], G.calls.count("gmail.users.history.list")
state, n = google_health({"gmail.users.history.list": lambda n: (_ for _ in ()).throw(BrokenPipeError(32, "Broken pipe")) if n == 1 else {"history": [], "historyId": "h2"}})
check("health: one dropped call (a broken pipe) then success: Google is not marked down", state["ok"] is True and state["error"] is None and n == 2, (state, n))
state, n = google_health({"gmail.users.history.list": lambda n: (_ for _ in ()).throw(ssl.SSLError("UNEXPECTED_EOF_WHILE_READING")) if n <= 2 else {"history": [], "historyId": "h2"}})
check("health: two dropped calls (an SSL EOF) then success: still not marked down (the last try is the third)", state["ok"] is True and n == 3, (state, n))
state, n = google_health({"gmail.users.history.list": lambda n: (_ for _ in ()).throw(BrokenPipeError(32, "Broken pipe"))})
check("health: every try fails (1 + the retries): Google is marked down, with the error", state["ok"] is False and "Broken pipe" in state["error"] and n == 1 + len(gw.HEALTH_RETRY), (state, n))
state, n = google_health({"gmail.users.history.list": lambda n: (_ for _ in ()).throw(ValueError("bad cursor"))})
check("health: an error waiting cannot fix is not retried: one call, Google is marked down", state["ok"] is False and n == 1, (state, n))
state, n = google_health({})
check("health: no failure: healthy after one call", state["ok"] is True and n == 1, (state, n))
sleeps: list[float] = []
gw.HEALTH_RETRY = (2.0, 6.0)
h, loop, renew = start_google({"gmail.users.history.list": lambda n: (_ for _ in ()).throw(BrokenPipeError(32, "Broken pipe")) if n == 1 else {"history": [], "historyId": "h2"}})
stop_after_health(h)
h.stopping.wait = lambda s=None: (sleeps.append(s), False)[1]
loop()
check("health: the wait before the retry is the first of the backoff", sleeps == [2.0] and h.status["receivers"]["google"]["ok"] is True, (sleeps, h.status["receivers"]["google"]))
gw.HEALTH_RETRY = (0.0, 0.0)

# a failing status write after binding a source: the source is still counted as bound, so the cursors are reset and the channels registered once
class CountQ(FastQ):
    """The trigger queue that counts the passes of a loop that waits on it, and ends the loop (hub.stopping) after `n`."""
    def __init__(self, hub, n): super().__init__(); self.hub, self.n, self.passes = hub, n, 0
    def get(self, block=True, timeout=None):
        self.passes += 1
        if self.passes > self.n: self.hub.stopping.set()
        return super().get(block=False)
h, loop, renew = start_google(); h.triggers = CountQ(h, 4); h.stopping.wait = StopAfter(h, 6); h.write_status = lambda: (_ for _ in ()).throw(OSError("disk full"))
n_log = len(records); loop()
check("google: a status write that keeps failing after a source is bound does not repeat the binding every pass (cursor read once at the bind, one start read)",
      G.calls.count("gmail.users.getProfile") == 2 and h.triggers.passes > 4, (G.calls.count("gmail.users.getProfile"), h.triggers.passes))
check("…and the failed write is logged", any("google status write after binding gmail" in r and "disk full" in r for r in records[n_log:]), records[n_log:][:2])

# ---- an idle receiver (nothing bound) keeps stamping its beat: never stale in three hours, on a clock that runs ahead 10 minutes per pass
import datetime as _dt
clock = [1_800_000_000.0]
core_now_iso = core.now_iso; core.now_iso = lambda: _dt.datetime.fromtimestamp(clock[0], core.ZONE).strftime("%Y-%m-%d %H:%M:%S")
def checked_ts(h, name): return _dt.datetime.strptime(h.status["receivers"][name]["checked"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=core.ZONE).timestamp()
class ClockQ(FastQ):
    """Each pass of the loop is 10 minutes later; before it runs, the card's rule is asked about the receiver (the oldest it ever looks)."""
    def __init__(self, hub, name, passes): super().__init__(); self.hub, self.name, self.n, self.i, self.worst = hub, name, passes, 0, 0
    def get(self, block=True, timeout=None):
        self.i += 1; clock[0] += 600
        r = self.hub.status["receivers"][self.name]
        self.worst = max(self.worst, rh.stale_age(self.name, r["ok"], checked_ts(self.hub, self.name), clock[0], (self.hub.status.get("hold") or {}).get(self.name, 0)))
        if self.i >= self.n: self.hub.stopping.set()
        return super().get(block=False)
gw.time = types.SimpleNamespace(time=lambda: clock[0], sleep=lambda s: None)
h, loop, renew = start_google(bindings={}); core._receiver_state(h, "google", True, None); stamp0 = checked_ts(h, "google")
h.triggers = ClockQ(h, "google", 18); loop()
check("google, nothing bound: after three hours the receiver is not stale (it stamped its beat on the way), the stamp moved", h.triggers.worst == 0 and checked_ts(h, "google") > stamp0 + 3 * 1800, (h.triggers.worst, checked_ts(h, "google") - stamp0))
nr.time = types.SimpleNamespace(time=lambda: clock[0], sleep=lambda s: None); urllib.request.urlopen = _urlopen
try:
    hn2 = core.Hub(); hn2.status["receivers"] = {}; hn2.bindings = {}; caught.clear(); nr.run(hn2); core._receiver_state(hn2, "notion", True, None); stamp0 = checked_ts(hn2, "notion")
    hn2.triggers = ClockQ(hn2, "notion", 18); armed[0] = False; caught[0]()
finally: urllib.request.urlopen = real_urlopen
check("notion, nothing bound: after three hours the receiver is not stale, the stamp moved", hn2.triggers.worst == 0 and checked_ts(hn2, "notion") > stamp0 + 3 * 1800, (hn2.triggers.worst, checked_ts(hn2, "notion") - stamp0))
# …and the same run without the stamp is what the card used to show: the rule at the 3 hours
check("…(the rule on the start-time stamp alone at three hours: stale, which is what an idle receiver showed before)", rh.stale_age("google", True, stamp0, stamp0 + 3 * 3600) == 3 * 3600)
core.now_iso = core_now_iso

# GitHub waiting after it refused calls: announced before the wait, so the card is not stale during it
hb = core.Hub(); hb.status["receivers"] = {}; hb.bindings = {"github:o/r#5": {"sess"}}; caught.clear(); gh_waits: list[tuple] = []
def _gh_limited(args, **k):
    if args[-1] == "/user": return types.SimpleNamespace(returncode=0, stdout=json.dumps({"login": "oliver"}), stderr="")
    return types.SimpleNamespace(returncode=1, stdout="", stderr="gh: API rate limit exceeded (HTTP 403)")
ghr.subprocess = types.SimpleNamespace(run=_gh_limited, TimeoutExpired=subprocess.TimeoutExpired)
def _backoff_sleep(sec):
    gh_waits.append((sec, hb.status.get("hold", {}).get("github"), time.time()))
    if len(gh_waits) >= 2: hb.stopping.set()
ghr.time = types.SimpleNamespace(time=time.time, sleep=_backoff_sleep)
ghr.run(hb); caught[0]()
sec, held_until, at = gh_waits[0]
check("github: a wait after GitHub refuses calls waits the announced time and says so first (the hold runs to the end of the wait)", sec == ghr.BACKOFF == 600 and held_until is not None and abs(held_until - (at + 600)) < 5, gh_waits)
check("…so the card is not stale at the end of the wait, and counts from there: stale only after two more beats", rh.stale_age("github", True, at - 120, at + 599, held_until) == 0
      and rh.stale_age("github", True, at - 120, held_until + 120, held_until) == 0 and rh.stale_age("github", True, at - 120, held_until + 121, held_until) == 121, "")
check("…and the pass's own check ends the announcement", "github" not in hb.status.get("hold", {}), hb.status.get("hold"))

# ---- 4. the beats the board judges staleness by
check("receiver_health.EVERY agrees with the beats the receivers run on (GitHub's poll, Slack's watch, Google's and Notion's re-read)",
      rh.EVERY == {"github": ghr.GHPOLL, "slack": sl.WATCH, "google": core.HEALTH, "notion": core.HEALTH}, (rh.EVERY, ghr.GHPOLL, sl.WATCH, core.HEALTH))
NOW = 1_800_000_000.0
for name, every in rh.EVERY.items():
    check(f"stale rule, {name} (beat {every} s): exactly twice the beat is not stale", rh.stale_age(name, True, NOW - 2 * every, NOW) == 0)
    check("…one second past twice the beat is stale, with its age", rh.stale_age(name, True, NOW - 2 * every - 1, NOW) == 2 * every + 1)
    check("…one second under twice the beat is not stale", rh.stale_age(name, True, NOW - 2 * every + 1, NOW) == 0)
check("stale rule: a receiver that is down already shows its error, so it is not called stale", rh.stale_age("github", False, NOW - 10_000, NOW) == 0)
check("stale rule: a receiver the table does not know, or with no readable check time, or checked in the future, is not stale",
      rh.stale_age("hook-a", True, NOW - 10_000, NOW) == 0 and rh.stale_age("github", True, 0, NOW) == 0 and rh.stale_age("github", True, NOW + 500, NOW) == 0)
check("stale rule: an announced wait is counted out: the age runs from the later of the last check and the end of the wait",
      rh.stale_age("github", True, NOW - 5000, NOW, hold_until=NOW + 300) == 0 and rh.stale_age("github", True, NOW - 5000, NOW, hold_until=NOW - 120) == 0
      and rh.stale_age("github", True, NOW - 5000, NOW, hold_until=NOW - 121) == 121 and rh.stale_age("github", True, NOW - 5000, NOW, hold_until=None) == 5000)
check("stale rule: a huge, infinite or garbled hold is clamped: it never hides a receiver whose last check is hours old",
      rh.stale_age("github", True, NOW - 10_800, NOW, hold_until=1e15) == 3600 and rh.stale_age("github", True, NOW - 10_800, NOW, hold_until=float("inf")) == 3600
      and rh.stale_age("github", True, NOW - 10_800, NOW, hold_until=float("nan")) == 10_800 and rh.stale_age("github", True, NOW - 10_800, NOW, hold_until="x") == 10_800
      and rh.stale_age("github", True, NOW - 100, NOW, hold_until=float("inf")) == 0, (rh.stale_age("github", True, NOW - 10_800, NOW, hold_until=1e15), rh.stale_age("github", True, NOW - 10_800, NOW, hold_until=float("nan"))))
check("stale note: the one text of the tooltip", rh.stale_note("slack", 121) == "no check for 2m (it reports every 1m); the last one said healthy", rh.stale_note("slack", 121))
check("age words: minutes under an hour, hours under two days, then days (as the page script writes them)",
      [rh.age_words(s) for s in (0, 59, 60, 3599, 3600, 2879 * 60, 2880 * 60, 5 * 86400)] == ["0m", "0m", "1m", "59m", "1h", "47h", "2d", "5d"], [rh.age_words(s) for s in (0, 59, 60, 3599, 3600, 2879 * 60, 2880 * 60, 5 * 86400)])

print(f"{checks - fails}/{checks} checks passed")
sys.exit(1 if fails else 0)
