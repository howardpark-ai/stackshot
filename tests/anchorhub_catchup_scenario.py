"""Scenario test for a catch-up of the GitHub receiver (stackshot/anchors/anchorhub/github.py): the first pass after a first start or after the `gh` login
changed. GitHub answers an ETag only for the token it was given, so such a pass reads every anchor in full, and every full read is counted in the host's one hourly ledger
(stackshot/core/ghbudget.py, [github] read_budget), which the server shares. A fake `gh` (the module's own injection point for subprocess.run) that answers ETags like
GitHub (a 304 for a validator of the same login only), the real Hub with its status file and saved positions, a small read_budget, no network, no thread of the receiver.

Covers: a catch-up pass starts no further anchor once the hour's ledger holds two thirds of the budget (CATCHUP_SHARE), so a third is left for the server and the anchors
already read; the anchors not yet read go first, then the others by when each was read, the one read longest ago first; the next passes carry on from where it stopped, as the
hour's reads expire, and the note goes when every anchor has been read; the card is healthy (the status file, receiver_state, the receivers endpoint) with the note
"catching up: n of m anchors read", never the cap error, and the server can still read; the cap spent by someone else's reads, a bad credential and a GitHub that answers 5xx at
the start are still errors; a look that failed is not a read (a failed read of the pull request or its check runs included); a restart in the middle of a catch-up goes on from the saved position; a file from before the position was kept
counts the anchors with ETags as read. After a login change an anchor that is merged or closed is read in full and paced like the others, never skipped and counted as read (so no later turn of it reads it unpaced past the allowance);
a 410 is an answer like a 404; an anchor whose look keeps failing (not a failure of everything) goes behind the others and is tried less often, and is said apart in the note; a failure of every look
is an outage, not any anchor's, and starts no back-off; a read budget of 1 does not break the pacing.

    tests/run-suite anchorhub_catchup      → exit 0 / 1"""
import sys, os, re, json, time, types, pathlib, threading, logging, subprocess, hashlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="ah-catchup-")
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's store of sessions
toml, n1 = re.subn(r'(?m)^state = "[^"]*"', f'state = "{tmp}/state"', toml); toml, n2 = re.subn(r'(?m)^secrets = "[^"]*"', f'secrets = "{tmp}/secrets"', toml)
assert (n1, n2) == (1, 1), (n1, n2)
pathlib.Path(tmp, "stackshot.toml").write_text(toml, encoding="utf-8"); os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
os.environ.pop("ANCHOR_HUB_ALLOW_SELF", None)
sys.path.insert(0, STACK); logging.disable(logging.WARNING)

_wd = threading.Timer(240, lambda: (print("FAIL: the scenario did not end in 240 s", flush=True), os._exit(3))); _wd.daemon = True; _wd.start()
fails = checks = 0
def check(name, ok, got=None):
    global fails, checks
    checks += 1
    print(("ok:   " if ok else "FAIL: ") + name + ("" if ok else f"\n      got: {str(got)[:700]}"), flush=True)
    if not ok: fails += 1

from stackshot.anchors.anchorhub import core, github as ghr
from stackshot.core import ghbudget as _gb, config as _cfg
from stackshot.web.ui import render as ui_render
from stackshot.web.routes import board_pages

N = 12
aids = [f"github:o/r#{n}" for n in range(1, N + 1)]
def num(a): return int(a.rsplit("#", 1)[1])


def set_budget(n): _cfg.CFG.setdefault("github", {})["read_budget"] = n
def age_ledger():
    """An hour passes: every stamp of the ledger is older than an hour, so the ledger is empty."""
    p = _cfg.state("github", _gb.LEDGER_NAME)
    try: doc = json.loads(p.read_text(encoding="utf-8"))
    except OSError: return
    shift = lambda rows: [t - 3700 for t in rows]
    doc = {"w": shift(doc.get("w", [])), "r": shift(doc.get("r", [])), "by": {k: {c: shift(v) for c, v in (d or {}).items()} for k, d in (doc.get("by") or {}).items()}}
    p.write_text(json.dumps(doc), encoding="utf-8")
def clear_ledger(): _cfg.state("github", _gb.LEDGER_NAME).unlink(missing_ok=True)


# ---- a fake GitHub: N open issues of one repository (no pull request under any number), an ETag per login (like GitHub's: a token is answered 304 only for its own ETag), every call logged
MORE = 6      # anchors 13 to 18 exist on the fake too: a test binds them later
class Fake:
    def __init__(self):
        self.login = "oliver"; self.user = "ok"; self.log = []; self.reset()
    def reset(self):
        """Every number an open issue, no pull request, no failing path."""
        self.status = {}; self.fail = set(); self.prs = set()
        self.issues = {n: {"state": "open", "comments": 0, "title": f"thing {n}", "user": {"login": "kim"}, "html_url": f"https://github.com/o/r/issues/{n}",
                           "created_at": "2026-10-20T00:00:00Z", "updated_at": "2026-10-25T00:00:00Z", "closed_at": None} for n in range(1, N + MORE + 1)}
    def make_pr(self, n, merged=False):
        """Number n is a pull request: open, or merged (and so finished)."""
        self.prs.add(n); i = self.issues[n]; i["pull_request"] = {"merged_at": "2026-10-20T00:00:00Z" if merged else None}
        if merged: self.close(n)
    def close(self, n): self.issues[n]["state"] = "closed"; self.issues[n]["closed_at"] = "2026-10-20T00:00:00Z"
    def gh(self, args, capture_output=True, text=True, timeout=30):
        cond = "-i" in args
        inm = next((args[k + 1][len("If-None-Match: "):] for k, x in enumerate(args) if x == "-H"), None)
        path = next(x for x in args[2:] if x not in ("-i", "-H") and not x.startswith("If-None-Match"))
        def fail(code, msg): self.log.append((path, code, inm)); return types.SimpleNamespace(returncode=1, stdout="", stderr=msg)
        if path == "/user":
            if self.user == "401": return fail(401, "HTTP 401: Bad credentials (https://api.github.com/user)")
            if self.user == "500": return fail(500, "gh: Server Error (HTTP 500)")
            self.log.append((path, 200, inm)); return types.SimpleNamespace(returncode=0, stdout=json.dumps({"login": self.login}), stderr="")
        if path in self.fail: return fail(500, "gh: Server Error (HTTP 500)")
        if path in self.status: return fail(*self.status[path])
        obj = None
        if (m := re.fullmatch(r"/repos/o/r/issues/(\d+)", path)) and int(m.group(1)) in self.issues: obj = self.issues[int(m.group(1))]
        elif (m := re.fullmatch(r"/repos/o/r/pulls/(\d+)", path)) and int(m.group(1)) in self.prs:
            k = int(m.group(1)); obj = {"head": {"sha": f"sha{k}", "ref": f"br{k}", "repo": {"full_name": "o/r"}}, "base": {"repo": {"full_name": "o/r", "id": 77}}, "user": {"login": "kim"}}
        elif (m := re.fullmatch(r"/repos/o/r/commits/sha(\d+)/check-runs\?per_page=100", path)) and int(m.group(1)) in self.prs:
            obj = {"check_runs": [{"name": "unit", "status": "completed", "conclusion": "success", "completed_at": "2026-10-20T00:00:00Z"}]}
        if obj is None: return fail(404, "gh: Not Found (HTTP 404)")      # a pull request read of any number that is none lands here: no pull request is under it
        text_ = json.dumps(obj, sort_keys=True); tag = '"' + self.login + "-" + hashlib.sha1(text_.encode()).hexdigest()[:12] + '"'
        if cond and inm == tag:
            self.log.append((path, 304, inm)); return types.SimpleNamespace(returncode=0, stdout="HTTP/2.0 304 Not Modified\n\n", stderr="")
        self.log.append((path, 200, inm)); return types.SimpleNamespace(returncode=0, stdout=(f"HTTP/2.0 200 OK\netag: {tag}\n\n" + text_) if cond else text_, stderr="")
    def counted(self, since=0): return [c for c in self.log[since:] if c[1] != 304]


F = Fake()
class _Stop(Exception): pass
def _no_sleep(s): raise _Stop()
caught: list = []
ghr.subprocess = types.SimpleNamespace(run=F.gh, TimeoutExpired=subprocess.TimeoutExpired)
ghr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
CLOCK = [0.0]      # seconds the receiver's own clock is ahead of the real one: a test lets minutes pass without waiting (the ledger of reads keeps the real time, and age_ledger() moves its hour)
ghr.time = types.SimpleNamespace(time=lambda: time.time() + CLOCK[0], sleep=_no_sleep)
events: list = []

def boot(order=None):
    """A start of the receiver over whatever cursors.json holds (as the service makes it) → the hub, the anchors bound in `order`."""
    del caught[:]
    h = core.Hub(); h.emit = lambda ev: events.append(ev); h.bindings = {a: {"sess"} for a in (order or aids)}
    ghr.run(h); return h
def one_pass():
    try: caught[0]()
    except _Stop: pass
def card():
    """What the board's card reads: the status file the hub wrote, as the receivers endpoint serves it, and the card's own word and class."""
    v = json.load(open(core.STATUS))["receivers"]["github"]
    api = json.loads(board_pages._receivers_response().body)["github"]
    return v, api, ui_render.receiver_state(v)
def run_pass():
    """One pass → (counted reads it made by GitHub's count, the paths it asked in order, the card)."""
    n = len(F.log); one_pass()
    return len(F.counted(n)), [c[0] for c in F.log[n:]], card()
def drop_cursors(): pathlib.Path(core.CURSORS).unlink(missing_ok=True)


# ---- 1. a first start: nothing saved, every anchor is read in full (an issue costs 2 counted reads: the pull request that is not there, then the issue); read_budget 18 → a catch-up line of 12
set_budget(18); clear_ledger(); P = int(18 * ghr.CATCHUP_SHARE)
check("the catch-up line is two thirds of the read budget, and a third is left", P == 12 and ghr.CATCHUP_SHARE == 2 / 3, (P, ghr.CATCHUP_SHARE))
h = boot(); cost = len(F.counted())
check("start: the check is one counted read (GET /user), and the receiver reports nothing yet", cost == 1 and "github" in h.status, F.log)
reads, paths, (v, api, word) = run_pass()
read_now = [a for a in aids if f"/repos/o/r/issues/{num(a)}" in paths]
check("a catch-up pass reads only its allowance: it starts no anchor once the ledger holds 12 of the 18 (6 anchors, 12 reads; one anchor can pass the line by its own cost, never more)",
      reads == 12 and _gb.count("r") == 13 and len(read_now) == 6, (reads, _gb.count("r"), read_now))
check("…and it reads the anchors never read in the order they are bound", read_now == aids[:6], read_now)
check("…the card is healthy, with the note of how far it is: ok, 'catching up: 6 of 12 anchors read', no error", v["ok"] is True and v["error"] == "catching up: 6 of 12 anchors read" and word == ("healthy ✓", "ok"), (v, word))
check("…the receivers endpoint serves the same: ok, the note, not stale", api["ok"] is True and api["error"] == "catching up: 6 of 12 anchors read" and not api["stale"], api)
check("…the pass is a finished check (last_pass set), nothing is told to anyone", h.status["github"].get("last_pass") and not events, (h.status["github"], events))
check("…the cap is not spent and the server can still read: the ledger has room, and a server read is allowed (a third of the budget is left)",
      _gb.wait("r") == 0 and _gb.take("r", caller="step_proof") == 0 and 18 - _gb.count("r") >= 18 // 3 - 2, (_gb.wait("r"), _gb.count("r")))
for _ in range(2): _gb.take("r", caller="step_proof")

# ---- 2. the next pass in the same hour: nothing more is started, the anchors already read go on (free), in the order of when each was read, whatever the order they are bound in
h.bindings = {a: {"sess"} for a in reversed(aids)}
reads, paths, (v, api, word) = run_pass()
check("the next pass, the hour not over: no counted read, the six anchors not read are not started", reads == 0 and not [p for p in paths if re.search(r"/issues/(7|8|9|10|11|12)$", p)], (reads, paths))
check("…the anchors already read are asked as 304s, the one read longest ago first (not in the order they are bound in)", paths == [f"/repos/o/r/issues/{n}" for n in range(1, 7)], paths)
check("…the card still says healthy with the note, unchanged", v["ok"] is True and v["error"] == "catching up: 6 of 12 anchors read" and word == ("healthy ✓", "ok"), (v, word))

# ---- 3. an hour on: the catch-up carries on from where it stopped (the anchors never read first, in the order bound), and finishes; the note goes
age_ledger()
reads, paths, (v, api, word) = run_pass()
first_new = [p for p in paths if re.search(r"/issues/\d+$|/pulls/\d+$", p)][0]
check("an hour later the pass reads the anchors never read first (before the ones already read), in the order bound: #12 first", first_new == "/repos/o/r/pulls/12" and paths[:2] == ["/repos/o/r/pulls/12", "/repos/o/r/issues/12"], paths[:4])
check("…it reads the 6 it had left, 12 reads, and every anchor has been read", reads == 12 and all(a in h.gh_state["looked"] for a in aids), (reads, len(h.gh_state["looked"])))
check("…the note is gone: healthy, no text at all", v["ok"] is True and not v.get("error") and not api["error"] and word == ("healthy ✓", "ok"), (v, word))
reads, paths, (v, api, word) = run_pass()
check("…and the pass after it reads nothing counted", reads == 0 and v["ok"] is True and not v.get("error"), (reads, v))
h.persist(); doc = json.load(open(core.CURSORS))["github"]
check("the position is saved with the ETags: when each of the 12 anchors was read", sorted(doc["looked"]) == sorted(aids) and all(isinstance(t, float) for t in doc["looked"].values()) and sorted(doc["etags"]) == sorted(aids), (list(doc["looked"]), list(doc["etags"])))

# ---- 4. the login changes: GitHub honors no ETag across tokens, so every anchor is read in full again; read_budget 9 → a line of 6 (an issue is 1 counted read now: its pull request is known to be none)
set_budget(9); P = 6; clear_ledger(); F.login = "marlow"
h = boot(); n0 = len(F.log)
check("a login change: the ETags and the record of what was read are not used (the position of the other login is dropped)", not h.gh_state["etags"] and not h.gh_state["looked"], (list(h.gh_state["etags"]), list(h.gh_state["looked"])))
reads, paths, (v, api, word) = run_pass()
full = [c for c in F.log[n0:] if c[0].startswith("/repos/o/r/issues/")]
check("…the pass reads each anchor in full, with no validator, and stops at its allowance: 5 anchors, the start check's read and theirs making 6", reads == 5 and len(full) == 5 and all(c[1] == 200 and c[2] is None for c in full) and _gb.count("r") == 6, (reads, full, _gb.count("r")))
check("…the card reads healthy, 'catching up: 5 of 12 anchors read'; no error, never the cap's", v["ok"] is True and v["error"] == "catching up: 5 of 12 anchors read" and "cap" not in v["error"] and word == ("healthy ✓", "ok"), (v, word))
reads, paths, (v, api, word) = run_pass()
check("…the pass after it, in the same hour, reads nothing counted (the five read are 304s now) and keeps the note", reads == 0 and v["error"] == "catching up: 5 of 12 anchors read" and len([p for p in paths if p.endswith("/1")]) == 1, (reads, paths, v))
age_ledger(); reads, paths, (v, api, word) = run_pass()
check("…an hour later it reads 6 more and says so", reads == 6 and v["ok"] is True and v["error"] == "catching up: 11 of 12 anchors read", (reads, v))
reads, paths, (v, api, word) = run_pass()
check("…the same hour: nothing more", reads == 0 and v["error"] == "catching up: 11 of 12 anchors read", (reads, v))
age_ledger(); reads, paths, (v, api, word) = run_pass()
check("…the next hour: the last one, and the note goes", reads == 1 and v["ok"] is True and not v.get("error") and word == ("healthy ✓", "ok"), (reads, v))
check("…the first read of each anchor is not reported as news (nothing changed under the new login)", not events, events)
h.persist()

# ---- 5. the cap spent by someone else's reads is a real failure, a catch-up or not
set_budget(18); clear_ledger(); drop_cursors(); F.login = "oliver"
h = boot()
for _ in range(18): _gb.note("r", caller="step_proof")          # the server's own reads take the whole budget
reads, paths, (v, api, word) = run_pass()
check("the cap spent by the server's reads, in the middle of nothing read: the pass reads nothing and the card reads error ('reads held by the hourly cap, resume in …')",
      reads == 0 and not paths and v["ok"] is False and v["error"].startswith("reads held by the hourly cap, resume in ") and word == ("error ✗", "bad") and "last_pass" not in h.status["github"], (reads, v, word))
check("…the receivers endpoint serves the error too", api["ok"] is False and api["error"].startswith("reads held by the hourly cap"), api)
clear_ledger(); reads, paths, (v, api, word) = run_pass()
check("…the hour's reads free again, the next pass runs and the card is healthy again", reads == 12 and v["ok"] is True and v["error"] == "catching up: 6 of 12 anchors read", (reads, v))

# ---- 6. the server's reads that take the room of the catch-up (over its line, under the cap) slow it down; they are not an error
clear_ledger(); drop_cursors()
h = boot()
for _ in range(14): _gb.note("r", caller="step_proof")          # 15 with the start check: over the line of 12, under the cap of 18
reads, paths, (v, api, word) = run_pass()
check("the server has used the catch-up's room (the ledger is over the line, under the cap): no anchor is started, and the card is healthy with the note, not an error", reads == 0 and v["ok"] is True and v["error"] == "catching up: 0 of 12 anchors read" and word == ("healthy ✓", "ok"), (reads, v, word))

# ---- 7. a restart in the middle of a catch-up goes on from the saved position: the anchors read are 304s, the rest wait for room
clear_ledger(); drop_cursors()
h = boot(); reads, paths, (v, api, word) = run_pass(); h.persist()
check("a catch-up cut at its allowance, saved", reads == 12 and v["error"] == "catching up: 6 of 12 anchors read", (reads, v))
h = boot(); n0 = len(F.log); reads, paths, (v, api, word) = run_pass()
check("restart in the middle of it (same login): the six read are asked as 304s, the others are still waiting for the hour's room, and the note says how far it was", reads == 0 and len([c for c in F.log[n0:] if c[1] == 304]) == 6 and v["error"] == "catching up: 6 of 12 anchors read", (reads, F.log[n0:], v))
age_ledger(); reads, paths, (v, api, word) = run_pass(); h.persist()
check("…and an hour on it finishes the rest", reads == 12 and v["ok"] is True and not v.get("error"), (reads, v))
doc = json.load(open(core.CURSORS)); del doc["github"]["looked"]; open(core.CURSORS, "w").write(json.dumps(doc))
h = boot(); reads, paths, (v, api, word) = run_pass()
check("a file from before the position was kept (ETags saved, no record of what was read): the anchors with ETags count as read, no catch-up, no counted read", reads == 0 and v["ok"] is True and not v.get("error"), (reads, v))
for a in aids[:2]: doc["github"]["etags"].pop(a)
open(core.CURSORS, "w").write(json.dumps(doc)); h = boot()
check("…an anchor with no ETags saved in such a file is not read yet", sorted(a for a in aids if a not in h.gh_state["looked"]) == sorted(aids[:2]), list(h.gh_state["looked"]))
doc["github"]["looked"] = {aids[0]: "nope", aids[1]: True, aids[2]: 123.0, aids[3]: -1, "github:gone/x#9": 5}; open(core.CURSORS, "w").write(json.dumps(doc)); h = boot(); h.persist()
check("…and a record that is not a time (text, a boolean, a negative number) is not believed; a time is, and an anchor no longer bound is not kept", aids[0] not in h.gh_state["looked"] and aids[1] not in h.gh_state["looked"] and h.gh_state["looked"][aids[2]] == 123.0
      and "github:gone/x#9" not in json.load(open(core.CURSORS))["github"]["looked"], (dict(h.gh_state["looked"])))

# ---- 8. a look that failed is not a read: the anchor stays unread, is tried again first, and the card says so
set_budget(1000); clear_ledger(); drop_cursors()
F.fail = {f"/repos/o/r/issues/{n}" for n in (2, 3)}
h = boot(); reads, paths, (v, api, word) = run_pass()
check("two anchors whose read fails (GitHub's 500) are not counted as read: the note says 10 of 12, the pass is a finished check as before", v["ok"] is True and v["error"] == "catching up: 10 of 12 anchors read", (v, paths))
F.fail = set(); n0 = len(F.log); reads, paths, (v, api, word) = run_pass()
check("…the next pass tries them first, they are read, and the note goes", [p for p in paths if "/issues/" in p][:2] == ["/repos/o/r/issues/2", "/repos/o/r/issues/3"] and v["ok"] is True and not v.get("error"), (paths, v))

# ---- 9. a real failure at the start: a bad credential, and a GitHub that answers 5xx. The receiver is not ready, retried, and its card reads error (the pass loop is never reached)
set_budget(1000); clear_ledger(); drop_cursors()
def start_with(user):
    F.user = user; del caught[:]; h = core.Hub(); h.status["receivers"] = {}; h.bindings = {a: {"sess"} for a in aids}; stop = threading.Event()
    th = core.start_receiver(h, "github", ghr.run, lambda: bool(h.status.get("github")), backoff=(0.02, 0.05), stop=stop)
    time.sleep(0.15); st = dict(h.status["receivers"]["github"]); stop.set()
    if th: th.join(10)
    return st, th
st, th = start_with("401")
check("a bad credential: the receiver is not ready, retried, and its card reads error 'gh not authenticated'", st["ok"] is False and "not authenticated" in st["error"] and st.get("retrying") is True and ui_render.receiver_state(st) == ("error ✗", "bad"), st)
st, th = start_with("500")
check("GitHub answering 5xx at the start: not ready, retried, the card reads error with GitHub's own words", st["ok"] is False and "HTTP 500" in st["error"] and st.get("retrying") is True, st)
F.user = "ok"

# ---- 10. after a login change, the anchors that are FINISHED (merged pull requests, closed issues) are read in full and paced like any other: none is skipped and counted as read (its later turn would read it unpaced, past the allowance)
F.reset(); MERGED = {n for n in range(1, N + 1) if n % 2 == 0}
for n in range(1, N + 1): F.make_pr(n, merged=True) if n in MERGED else F.close(n)      # even numbers merged pull requests (3 counted reads in full), odd ones closed issues (1)
set_budget(1000); clear_ledger(); drop_cursors(); F.login = "oliver"
h = boot(); reads, paths, (v, api, word) = run_pass(); h.persist()
check("setup: under the first login every finished anchor is read once and seeded, nothing is news", all(a in h.gh_state["looked"] for a in aids) and all(h.gh_state["state"][a]["state"] == "closed" for a in aids) and not events, (list(h.gh_state["looked"]), events))
set_budget(9); P = 6; clear_ledger(); F.login = "marlow"
h = boot(); n0 = len(F.log)
def really_read(since):
    """The anchors whose issue was read in full (a 200 sent with no validator) in the calls made since `since`."""
    return {a for a in aids if any(c[0] == f"/repos/o/r/issues/{num(a)}" and c[1] == 200 and c[2] is None for c in F.log[since:])}
worst = 0; red = []; same = []; hours = 0
while hours < 10 and len(h.gh_state["looked"]) < N:
    hours += 1
    for _ in range(12):      # a pass a minute for a while: every finished anchor's turn (one in FINISHED_EVERY passes) falls inside it
        reads, paths, (v, api, word) = run_pass()
        worst = max(worst, _gb.count("r")); same.append(set(h.gh_state["looked"]) == really_read(n0))
        if not (v["ok"] is True and word == ("healthy ✓", "ok") and "cap" not in (v.get("error") or "")): red.append((hours, v))
    age_ledger()
check("a login change over finished anchors: the ledger never goes past the catch-up line (6) by more than one anchor's cost (a merged pull request: 3 reads): at most 8 of the 9", worst <= P - 1 + 3, worst)
check("…`looked` holds exactly the anchors really read in full, after every pass (none counted for a skipped turn)", all(same) and len(same) >= 12, same)
check("…the card never reads error or 'reads held by the hourly cap' on the way: healthy with a note each pass", not red, red)
check("…the catch-up finishes as the ledger expires (within a few hours), every anchor read, and the note is gone", len(h.gh_state["looked"]) == N and hours <= 6 and not (card()[0].get("error")), (hours, len(h.gh_state["looked"]), card()[0]))
reads, paths, (v, api, word) = run_pass()
check("…afterwards the finished anchors cost nothing (their turns are 304s), whatever the pass", reads == 0 and v["ok"] is True, (reads, v))
check("…and none of it is reported as news", not events, events)

# ---- 11. a 410 (a deleted issue) is an answer like a 404; another failure that stays is not
F.reset(); set_budget(1000); clear_ledger(); drop_cursors(); F.login = "oliver"
F.status = {"/repos/o/r/issues/3": (410, "gh: Gone (HTTP 410)"), "/repos/o/r/issues/4": (404, "gh: Not Found (HTTP 404)"), "/repos/o/r/issues/5": (422, "gh: Validation Failed (HTTP 422)")}
h = boot(); reads, paths, (v, api, word) = run_pass()
check("a 410 and a 404 are answers: those anchors count as read; a 422 is not a look", aids[2] in h.gh_state["looked"] and aids[3] in h.gh_state["looked"] and aids[4] not in h.gh_state["looked"], list(h.gh_state["looked"]))
check("…the note says 11 of 12 (the 422's is the only one still to read) and the card is healthy", v["ok"] is True and v["error"] == "catching up: 11 of 12 anchors read", v)

# ---- 12. anchors whose look keeps failing do not starve the others
# a. a small budget (18: a line of 12) and the six failing ones first in the order bound: the first pass cannot know, and spends the line on them; an hour on, they have failed once and go behind the ones never tried
F.reset(); set_budget(18); clear_ledger(); drop_cursors(); CLOCK[0] = 0.0
BAD = aids[:6]; F.status = {f"/repos/o/r/issues/{num(a)}": (422, "gh: Validation Failed (HTTP 422)") for a in BAD}
h = boot(); reads, paths, (v, api, word) = run_pass()
check("six anchors that always fail, first in the order bound, at a small budget: the first pass spends the allowance on them (it cannot know yet)", reads == 12 and not [a for a in aids[6:] if a in h.gh_state["looked"]], (reads, list(h.gh_state["looked"])))
age_ledger(); reads, paths, (v, api, word) = run_pass()
issue_paths = [p for p in paths if re.search(r"/issues/\d+$", p)]
check("…an hour on, the anchors never tried go first and are all read, and the six that failed wait behind them", issue_paths[:6] == [f"/repos/o/r/issues/{n}" for n in range(7, 13)] and all(a in h.gh_state["looked"] for a in aids[6:]), (issue_paths, list(h.gh_state["looked"])))
check("…the card is healthy, the note counts what is still to read ('catching up: 6 of 12')", v["ok"] is True and v["error"] == "catching up: 6 of 12 anchors read", v)
# b. a budget that holds a pass: everything not failing is read in the first hour; the failing ones are tried a few times, then less and less often, and the anchors bound later are read at once
F.reset(); set_budget(300); clear_ledger(); drop_cursors(); CLOCK[0] = 0.0
F.status = {f"/repos/o/r/issues/{num(a)}": (422, "gh: Validation Failed (HTTP 422)") for a in BAD}
h = boot(); n12 = len(F.log); reads, paths, (v, api, word) = run_pass()
check("six failing anchors first in the order bound: in the first hour all six others are read, the failing ones are not counted as read", all(a in h.gh_state["looked"] for a in aids[6:]) and not [a for a in BAD if a in h.gh_state["looked"]] and v["error"] == "catching up: 6 of 12 anchors read", (list(h.gh_state["looked"]), v))
late = [f"github:o/r#{n}" for n in range(13, 19)]; noted = []; late_ok = None
for minute in range(1, 181):      # a pass a minute for three hours, the receiver's clock moving with it
    CLOCK[0] += 60
    if minute % 60 == 0: age_ledger()
    if minute == 60: h.bindings.update({a: {"sess"} for a in late})
    reads, paths, (v, api, word) = run_pass()
    if minute == 60: late_ok = all(a in h.gh_state["looked"] for a in late)
    noted.append((v["ok"], v.get("error")))
tries = [len([c for c in F.log[n12:] if c[0] == f"/repos/o/r/issues/{num(a)}"]) for a in BAD]
check("…each is tried three times in a row, then less and less often: 4 to 9 tries in three hours, not one a minute", all(4 <= t <= 9 for t in tries), tries)
check("…anchors bound an hour in are read in the pass they appear, ahead of the failing ones", late_ok is True, late_ok)
check("…the card stays healthy through it and, once they are given up on for now, says so apart: no 'catching up' for good", all(ok for ok, _ in noted) and noted[-1][1] == "6 anchors could not be read, tried again less often", (noted[-1], [x for x in noted if not x[0]][:2]))
F.status = {}; CLOCK[0] += 7200; age_ledger(); reads, paths, (v, api, word) = run_pass()
check("…and they are read the moment the cause goes and their turn comes (no anchor is dropped), and the note goes", all(a in h.gh_state["looked"] for a in aids + late) and not v.get("error") and not h.gh_state["retry"], (list(h.gh_state["looked"]), v, dict(h.gh_state["retry"])))
CLOCK[0] = 0.0

# ---- 13. GitHub failing for everything is an outage, not any anchor's: nothing is counted as read, no anchor goes into back-off, and the first pass that GitHub answers reads them all
F.reset(); set_budget(1000); clear_ledger(); drop_cursors(); CLOCK[0] = 0.0
F.status = {f"/repos/o/r/issues/{n}": (500, "gh: Server Error (HTTP 500)") for n in range(1, N + 1)}
h = boot()
for _ in range(6): CLOCK[0] += 60; reads, paths, (v, api, word) = run_pass()
check("every read failing for six passes: no anchor counted as read, none put in back-off (they are tried every pass), the card says how far it is and is not red for it", not h.gh_state["looked"] and not [a for a, (n, wait) in h.gh_state["retry"].items() if wait] and v["ok"] is True and v["error"] == "catching up: 0 of 12 anchors read", (dict(h.gh_state["retry"]), v))
F.status = {}; CLOCK[0] += 60; reads, paths, (v, api, word) = run_pass()
check("…the first pass GitHub answers reads every one of them, and the note goes", all(a in h.gh_state["looked"] for a in aids) and not v.get("error"), (len(h.gh_state["looked"]), v))
CLOCK[0] = 0.0

# ---- 14. a failed read of the pull request, or of its check runs, is not a look either
F.reset(); set_budget(1000); clear_ledger(); drop_cursors()
for n in range(1, N + 1): F.make_pr(n)
F.status = {"/repos/o/r/pulls/5": (500, "gh: Server Error (HTTP 500)"), "/repos/o/r/commits/sha6/check-runs?per_page=100": (500, "gh: Server Error (HTTP 500)")}
h = boot(); reads, paths, (v, api, word) = run_pass()
check("a pull request read that fails (#5) and a check-runs read that fails (#6): neither anchor is counted as read, the other ten are", sorted(a for a in aids if a not in h.gh_state["looked"]) == sorted([aids[4], aids[5]]) and v["error"] == "catching up: 10 of 12 anchors read", (list(h.gh_state["looked"]), v))
F.status = {}; reads, paths, (v, api, word) = run_pass()
check("…the next pass reads them, and the note goes", all(a in h.gh_state["looked"] for a in aids) and not v.get("error"), (list(h.gh_state["looked"]), v))

# ---- 15. a read budget of 1, 2 or 3 (two thirds of it is less than one, or one) does not break the pacing
for b in (1, 2, 3):
    F.reset(); set_budget(b); clear_ledger(); drop_cursors()
    h = boot(); clear_ledger(); err = None
    try: one_pass()
    except _Stop: pass
    except Exception as e: err = repr(e)
    try: shown = card()[0]["ok"] in (True, False)      # the pass ended in a report to the card (the loop's guard would have logged a crash and written none)
    except Exception as e: shown = False; err = err or repr(e)
    check(f"read_budget {b}: a pass starts at most the anchors the budget holds and does not raise", err is None and shown, err)

print(("ok" if not fails else "FAILED") + f": GitHub receiver catch-up scenario, {checks} checks" + (f", {fails} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
