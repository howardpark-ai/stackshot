"""Scenario test for the GitHub receiver on a GitHub App's token (stackshot/anchors/anchorhub/github.py): a fake `gh` (the module's own injection point for
subprocess.run), no network, no thread of the receiver is started.

An App's installation token reads repositories and pull requests, but GitHub answers it 403 "Resource not accessible by integration" for `gh api /user` and for
the user's notifications; `gh api /rate_limit` works for any accepted token. What it covers:
  1. The start check. A 403 of that kind on /user is followed by a probe of /rate_limit, and a token that passes starts the receiver. A 401 or a refused
     /rate_limit does not start it (a person's login is not an App's).
  2. `me`, the login whose own activity is not news: the setting `[anchor_hub] github_login` for an App token; with no setting, none (the filter is off) and one log
     line says so; with a person's token, /user's login as before and the setting is not used.
  3. The `@notifications` anchors: with an App token they are not read (no call, not even to name them), skipped with one log line for the whole run, and the receiver's
     status stays healthy with a note that they need a user sign-in, never a failure; with a person's token they are read as before.
  4. The start check is tried again: through start_receiver, a failed check (the network, a login not made yet, a refused credential: a Transient whatever the cause) is
     retried with a backoff until it passes, and the retry stops at the start.

    tests/run-suite github_app_token      → exit 0 / 1"""
import sys, os, re, json, time, types, pathlib, threading, logging, subprocess
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="ghapp-")
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's store of sessions
toml, n1 = re.subn(r'(?m)^state = "[^"]*"', f'state = "{tmp}/state"', toml); toml, n2 = re.subn(r'(?m)^secrets = "[^"]*"', f'secrets = "{tmp}/secrets"', toml)
toml, n3 = re.subn(r'(?m)^github_login = ""', 'github_login = "app-bot[bot]"', toml)
assert (n1, n2, n3) == (1, 1, 1), (n1, n2, n3)
pathlib.Path(tmp, "stackshot.toml").write_text(toml, encoding="utf-8"); os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
os.environ.pop("ANCHOR_HUB_ALLOW_SELF", None)
sys.path.insert(0, STACK)

_wd = threading.Timer(120, lambda: (print("FAIL: the scenario did not end in 120 s", flush=True), os._exit(3))); _wd.daemon = True; _wd.start()
fails = checks = 0
def check(name, ok, got=None):
    global fails, checks
    checks += 1
    print(("ok:   " if ok else "FAIL: ") + name + ("" if ok else f"\n      got: {str(got)[:700]}"), flush=True)
    if not ok: fails += 1

from stackshot.anchors.anchorhub import core, github as ghr

records: list[str] = []
class Capture(logging.Handler):
    def emit(self, record): records.append(record.getMessage())
core.log.addHandler(Capture()); core.log.setLevel(logging.INFO); core.log.propagate = False
def logged(pattern): return [r for r in records if re.search(pattern, r)]

# ---- a fake gh: the paths in GHD answer 200, the paths in DENY answer the App token's 403, the rest 404
RP = "/repos/example-owner/stackshot"
PR = "github:example-owner/stackshot#26"; BOT_ISSUE = "github:example-owner/stackshot#27"; PERSON_ISSUE = "github:example-owner/stackshot#28"
def notif(i): return f"github:example-owner/repo{i}@notifications"
def issue(n, login, created, updated):
    return {"state": "open", "comments": 0, "created_at": created, "updated_at": updated, "closed_at": None, "title": f"issue {n}", "user": {"login": login},
            "html_url": f"https://github.com/example-owner/stackshot/pull/{n}", "pull_request": {"merged_at": None}}
GHD = {"/rate_limit": {"resources": {}},
       f"{RP}/pulls/26": {"head": {"sha": "a" * 40, "ref": "x/y"}, "user": {"login": "someone"}, "base": {"repo": {"id": 7}}},
       f"{RP}/commits/{'a' * 40}/check-runs?per_page=100": {"check_runs": [{"name": "suites", "status": "completed", "conclusion": "success"}]},
       f"{RP}/issues/26": issue(26, "someone", "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z"),
       f"{RP}/issues/27": issue(27, "app-bot[bot]", "2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z"),
       f"{RP}/issues/28": issue(28, "someone", "2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z")}
for i in range(7): GHD[f"/repos/example-owner/repo{i}/notifications?all=true&per_page=50"] = []
USER = {"login": "example-owner"}
mode = {"user": "app"}      # "app": /user is refused as an App token's; "person": /user answers; "401": /user answers a bad credential; "down": every call fails as the network does
calls: list[str] = []; rate_denied = [False]
def _fake_gh(args, capture_output=True, text=True, timeout=30):
    a = [x for x in args[2:] if x != "-i" and x != "-H" and not x.startswith("If-None-Match")]; path = a[0]; cond = "-i" in args; calls.append(path)
    def fail(msg): return types.SimpleNamespace(returncode=1, stdout="", stderr=msg)
    if mode["user"] == "down": return fail("error connecting to api.github.com\ncheck your internet connection or https://githubstatus.com")
    if path == "/user":
        if mode["user"] == "person": body = json.dumps(USER)
        elif mode["user"] == "401": return fail("HTTP 401: Bad credentials (https://api.github.com/user)")
        else: return fail("gh: Resource not accessible by integration (HTTP 403)")
        return types.SimpleNamespace(returncode=0, stdout=body, stderr="")
    if path == "/rate_limit" and rate_denied[0]: return fail("HTTP 401: Bad credentials (https://api.github.com/rate_limit)")
    if "/notifications" in path and mode["user"] != "person": return fail("gh: Resource not accessible by integration (HTTP 403)")
    if path not in GHD: return fail("gh: Not Found (HTTP 404)")
    body = json.dumps(GHD[path]); return types.SimpleNamespace(returncode=0, stdout=("HTTP/2.0 200 OK\netag: \"x\"\n\n" + body) if cond else body, stderr="")
class _Stop(Exception): pass
def _no_sleep(s): raise _Stop()
caught: list = []
ghr.subprocess = types.SimpleNamespace(run=_fake_gh, TimeoutExpired=subprocess.TimeoutExpired)
ghr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
ghr.time = types.SimpleNamespace(time=time.time, sleep=_no_sleep)
real_cfg = ghr._cfg
class NoLogin:      # the config as the module sees it, with `[anchor_hub] github_login` empty (a running config keeps the value it started with)
    def __getattr__(self, k): return getattr(real_cfg, k)
    def get(self, *a, **kw): return "" if a[:2] == ("anchor_hub", "github_login") else real_cfg.get(*a, **kw)

def fresh(bindings, user="app"):
    """A hub with the given anchors bound, the receiver started on the fake gh (as `user`) → the hub."""
    mode["user"] = user; del calls[:], caught[:]; del records[:]; rate_denied[0] = False
    h = core.Hub(); h.write_status = lambda: None; h.emit = lambda ev: None; h.bindings = {a: {"sess"} for a in bindings}; h.status["receivers"] = {}
    ghr.run(h); return h
def one_pass():
    try: caught[0]()
    except _Stop: pass

if True:
    # ---- 1. the start check
    h1 = fresh([PR])
    check("start: /user is refused to an App token (403), /rate_limit is probed and passes: the receiver starts", calls == ["/user", "/rate_limit"] and bool(h1.status.get("github")), (calls, h1.status.get("github")))
    mode["user"] = "app"; rate_denied[0] = True; del calls[:]; hx = core.Hub(); hx.write_status = lambda: None
    try: ghr.run(hx); err = None
    except Exception as e: err = e
    check("start: a refused /rate_limit after the 403 does not start it: a Transient (retried), the receiver not registered", isinstance(err, core.Transient) and calls == ["/user", "/rate_limit"] and not hx.status.get("github"), (err, calls))
    mode["user"] = "401"; rate_denied[0] = False; del calls[:]
    try: ghr.run(hx); err = None
    except Exception as e: err = e
    check("start: a 401 on /user is no App token's 403: no /rate_limit probe, a Transient naming the refusal", isinstance(err, core.Transient) and calls == ["/user"] and "not authenticated" in str(err), (err, calls))
    mode["user"] = "person"; h1b = fresh([PR], "person")
    person_app_lines = logged(r"App token")      # the log of the person's start, taken before another start clears it
    check("start: a person's token passes /user as before: one call, no probe, `me` is the login /user answers", calls == ["/user"] and h1b.status["github"]["user"] == "example-owner", (calls, h1b.status.get("github")))

    # ---- 2. `me`
    h2 = fresh([PR], "app")
    check("me: for an App token it is the setting [anchor_hub] github_login", h2.status["github"]["user"] == "app-bot[bot]", h2.status["github"])
    seen = lambda hub, a: hub.resolvers["github"](a)["seen"]
    at = lambda z: core.now_iso_at(core._ts(z))      # a GitHub time as the board's `seen` writes it
    check("me: the bot's own issue is not news (its newest activity is the issue's update), another login's issue is (its creation)",
          seen(h2, BOT_ISSUE) == at("2026-11-03T00:00:00Z") and seen(h2, PERSON_ISSUE) == at("2026-11-02T00:00:00Z"), (seen(h2, BOT_ISSUE), seen(h2, PERSON_ISSUE)))
    check("me: the start says it in one log line naming the login", len(logged(r"ready with an App token.*as app-bot\[bot\]")) == 1, records)
    ghr._cfg = NoLogin()
    try: h2b = fresh([PR], "app")
    finally: ghr._cfg = real_cfg
    check("me: with no setting there is no login, the receiver still starts, and one log line says the filter is off", h2b.status["github"]["user"] == "" and len(logged(r"no \[anchor_hub\] github_login")) == 1, (h2b.status.get("github"), records))
    check("me: …and nothing is filtered: the bot's own issue counts as news like anyone's", seen(h2b, BOT_ISSUE) == at("2026-11-02T00:00:00Z"), seen(h2b, BOT_ISSUE))
    check("me: a person's token ignores the setting (the login is /user's)", h1b.status["github"]["user"] == "example-owner" and not person_app_lines, (h1b.status["github"], person_app_lines))

    # ---- 3. the notification anchors
    NA = [notif(i) for i in range(7)]
    h3 = fresh([PR, *NA], "app"); del calls[:]
    infos = [h3.resolvers["github"](a) for a in NA]; info = infos[-1]
    check("notifications: an App token's resolver names a notification anchor without a call (no 403 asked for)", not [c for c in calls if "/notifications" in c] and info["title"] == "repo6 notifications" and "unreadable" not in info, (calls, info))
    one_pass(); one_pass()
    check("notifications: two passes read the pull request and no notification list", not [c for c in calls if "/notifications" in c] and f"{RP}/pulls/26" in calls, calls)
    check("notifications: skipped with ONE log line for the whole run, naming the count and the user sign-in", len(logged(r"notification anchors? not read")) == 1 and "7 notification anchors" in logged(r"not read")[0] and "user sign-in" in logged(r"not read")[0], records)
    rc = h3.status["receivers"]["github"]
    check("notifications: the receiver's status stays healthy (ok, not a failure) and carries the note that they need a user sign-in",
          rc["ok"] is True and "7 notification anchors" in (rc["error"] or "") and "user sign-in" in rc["error"], rc)
    h3.bindings = {PR: {"sess"}}; one_pass(); rc = h3.status["receivers"]["github"]
    check("notifications: with none bound the note is gone (a healthy report with no note)", rc["ok"] is True and rc["error"] is None, rc)
    h3p = fresh([PR, notif(0)], "person"); one_pass()
    check("notifications: a person's token reads them as before, and no note", any("/notifications" in c for c in calls) and h3p.status["receivers"]["github"]["error"] is None and not logged(r"not read"), (calls, h3p.status["receivers"]))
    hh = core.Hub(); hh.write_status = lambda: None; hh.health("x", True, "a note"); hh.health("y", True); hh.health("z", False, "boom"); hh.health("w", False)
    r = hh.status["receivers"]
    check("health: a healthy report keeps its note in `error`, no note stays None, a failure keeps its error or says 'check failed'", (r["x"]["error"], r["y"]["error"], r["z"]["error"], r["w"]["error"]) == ("a note", None, "boom", "check failed") and r["x"]["ok"] is True, r)

    # ---- 4. the retry of a failed start check, through start_receiver (as the service starts it)
    def started(first_fails, kind):
        """start_receiver on the fake gh whose first `first_fails` calls of /user fail as `kind`; backoff of a few ms, the loop's waits recorded."""
        n = {"u": 0}; waits = []; inner = _fake_gh
        def gh(args, **kw):
            path = [x for x in args[2:] if x != "-i" and x != "-H" and not x.startswith("If-None-Match")][0]
            if path == "/user":
                n["u"] += 1
                if n["u"] > first_fails: rate_denied[0] = False      # whatever kept /rate_limit from passing is over by the last try
                if n["u"] <= first_fails:
                    mode["user"] = kind
                    try: return inner(args, **kw)
                    finally: mode["user"] = "app"
            return inner(args, **kw)
        ghr.subprocess = types.SimpleNamespace(run=gh, TimeoutExpired=subprocess.TimeoutExpired)
        class Stop:
            def wait(self, s): waits.append(s); return False
        mode["user"] = "app"; del calls[:], caught[:]
        h = core.Hub(); h.write_status = lambda: None; h.emit = lambda ev: None; h.bindings = {}; h.status["receivers"] = {}
        t = core.start_receiver(h, "github", ghr.run, lambda: bool(h.status.get("github")), backoff=(0.01, 0.04), stop=Stop())
        if t: t.join(10)
        ghr.subprocess = types.SimpleNamespace(run=_fake_gh, TimeoutExpired=subprocess.TimeoutExpired)
        return h, t, waits, n["u"]
    for kind, label in (("down", "the network is down"), ("401", "the credential is refused"), ("app", "an App token's 403 with /rate_limit refused")):
        del records[:]
        if kind == "app": rate_denied[0] = True
        h4, t4, waits, users = started(3, kind)
        rate_denied[0] = False
        check(f"retry ({label}): the start is tried again after each failure with a growing, capped wait, and starts at the fourth try",
              h4.status["receivers"]["github"]["ok"] is True and users == 4 and len(waits) == 3 and all(0 < w <= 0.04 for w in waits) and waits[2] >= waits[0], (h4.status["receivers"], users, waits))
        check(f"retry ({label}): each failure is one warning line of the receiver, and the recovery one line", len(logged(r"receiver github: start failed")) == 3 and len(logged(r"receiver github: ready after 4 tries")) == 1, records)
    h5, t5, waits, users = started(0, "app")
    check("retry: a start that passes at once makes no retry thread, no wait", t5 is None and waits == [] and users == 1 and h5.status["receivers"]["github"]["ok"] is True, (t5, waits, users))
    h6, t6, waits, users = started(3, "401"); n_calls = len(calls); time.sleep(0.05)
    check("retry: it stops once started: no further call to gh after the receiver is up", len(calls) == n_calls and not (t6 and t6.is_alive()), (len(calls), n_calls))

print(f"{checks - fails}/{checks} checks passed")
sys.exit(1 if fails else 0)
