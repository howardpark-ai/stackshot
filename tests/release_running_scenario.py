"""release_running_scenario.py: a release that runs on one box, told to the box the server runs on ([release] deploy_ssh): stackshot/core/release_running.py, the two readers of a running release
(web/ui/releasing.py, audit/busy_hold.py) and release.sh's running_start and running_end. Scratch folders, a stub ssh, release.sh run by the release suites' harness beside its stubs: no network, no real ssh,
no systemd call, no GitHub.

  1  entry     what is sent: the log's end and its age, a log that cannot be read, the command run on the other box and its time limit
  2  store     what the server box keeps: one file a release, only a newer stamp replaces an entry that counts, an ended one and an expired one are not listed, what is not an entry is refused
  3  send      one send over ssh: bounded, never held by what ssh leaves behind, the real command run end to end against the real module, `end` and `put` from the command line
  4  beat      the sender beside a release: now and every interval, stopped with the send in flight, gone with its parent, a failure said once
  5  readers   the board's running list, the release log the busy hold reads and its words, the Queued for release label
  6  release   release.sh: with deploy_ssh it tells the other box from its start to its end (a failed release too), holds no lock and writes nothing into its log while it does; a send that fails or hangs fails
               and delays nothing; one box (deploy_ssh unset, or not a host name) starts no process and calls no ssh

    tests/run-suite release_running        -> exit 0 / 1"""
from _release_harness import *
import _scratch, _instance

TMP = pathlib.Path(_scratch.mkdtemp(prefix="relrun-")); STATE = TMP / "state"; RUNDIR = STATE / "releases/running"
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml, n = re.subn(r'(?m)^state = "[^"]*"', f'state = "{STATE}"', toml); assert n == 1
(TMP / "stackshot.toml").write_text(toml, encoding="utf-8")
(TMP / "home").mkdir(); (TMP / "home/stackshot").symlink_to(STACK)      # what `cd ~/stackshot` finds on the "server box"
os.environ["STACKSHOT_CONFIG"] = str(TMP / "stackshot.toml")
sys.path.insert(0, STACK)
from stackshot.audit import busy_hold
from stackshot.core import release_running as rr
from stackshot.web.ui import releasing

TOOL = os.path.join(STACK, "stackshot/core/release_running.py")
FAKE = TMP / "fake"; (FAKE / "bin").mkdir(parents=True)
# the ssh of this suite: one line per call in calls, its pid in pids; $FAKE_DIR/mode = ok (the entry on stdin is kept) | fail | hang | linger (answers, and leaves a process that holds the output for 4 s) | run (the command, as the other box would)
(FAKE / "bin/ssh").write_text('#!/bin/sh\nd="$FAKE_DIR"\nprintf "%s\\n" "$*" >> "$d/calls"\necho $$ >> "$d/pids"\nfor a; do cmd=$a; done\ncase "$(cat "$d/mode" 2>/dev/null)" in\n'
                              '  fail) echo "kex_exchange_identification: read: reset" >&2; echo "ssh: connect to host box-b port 22: Connection refused" >&2; exit 255 ;;\n'
                              '  hang) exec /usr/bin/sleep 30 ;;\n'
                              '  linger) cat >/dev/null; /usr/bin/sleep 4 & echo $! >> "$d/lingering"; exit 0 ;;\n'
                              '  run) HOME="$d/../home" exec sh -c "$cmd" ;;\n'
                              '  *) cat >> "$d/entries"; echo >> "$d/entries" ;;\nesac\n')
(FAKE / "bin/ssh").chmod(0o755)
FENV = {**os.environ, "FAKE_DIR": str(FAKE), "PATH": f"{FAKE}/bin:{os.environ.get('PATH', '')}"}

def fake(mode="ok"):
    for f in ("calls", "pids", "entries", "lingering"): (FAKE / f).unlink(missing_ok=True)
    (FAKE / "mode").write_text(mode)
def lines(p): return pathlib.Path(p).read_text().splitlines() if pathlib.Path(p).exists() else []
def entries(): return [json.loads(l) for l in lines(FAKE / "entries") if l]
def alive(pid):
    try: return pathlib.Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError, ValueError): return False
def until(cond, secs=20.0):
    end = time.time() + secs
    while time.time() < end:
        if cond(): return True
        time.sleep(0.03)
    return bool(cond())
def logfile(name, text, age=0.0):
    p = TMP / name; p.write_text(text, encoding="utf-8"); os.utime(p, (time.time() - age, time.time() - age)); return str(p)
def wipe():
    if RUNDIR.exists(): shutil.rmtree(RUNDIR)
def ent(stamp=1, ended=False, age=5.0, tail="t\n"): return json.dumps({"stamp": stamp, "ended": ended, "age": age, "tail": tail})
def written_ago(n, secs): os.utime(RUNDIR / f"pr-{n}", (time.time() - secs, time.time() - secs))

# ---- 1. entry
e = json.loads(rr.entry(logfile("a.log", "x" * 20000 + "\nthe last line\n", age=100.0)))
check("1 an entry carries the end of the log, at most 8192 bytes of it, its age and a stamp, and is not ended",
      e["tail"].endswith("the last line\n") and len(e["tail"].encode()) == rr.TAIL_BYTES == 8192 and 99 <= e["age"] <= 130 and type(e["stamp"]) is int and e["stamp"] > 10 ** 18 and e["ended"] is False, (len(e["tail"]), e["age"], e["stamp"], e["ended"]))
a1 = json.loads(rr.entry(logfile("b.log", "short\n"), ended=True)); a2 = json.loads(rr.entry(str(TMP / "b.log"), ended=True))
check("1 …a short log whole; ended is said when asked; the next entry's stamp is newer", a1["tail"] == "short\n" and a1["ended"] is True and a2["stamp"] > a1["stamp"] and 0 <= a1["age"] < 30, (a1, a2))
m = json.loads(rr.entry(str(TMP / "no-such.log")))
check("1 …a log that cannot be read: still an entry, with no age and no tail", m["age"] is None and m["tail"] == "" and m["ended"] is False and type(m["stamp"]) is int, m)
check("1 an entry of a log full of bytes JSON escapes still fits in what `put` reads", len(rr.entry(logfile("c.log", "\x01" * 9000))) < rr.ENTRY_MAX, None)
CMD = "cd ~/stackshot && exec timeout -k 2 8 python3 stackshot/core/release_running.py put 12"
check("1 the command on the other box runs in the checkout there, under a time limit of what is left of the send's after the connect (20 s: 8 s), at least 1 s",
      rr.command(12, 20.0) == CMD and rr.command(12, 40.0).split(" -k 2 ")[1].startswith("28 ") and rr.command(12, 1.0).split(" -k 2 ")[1].startswith("1 ") and rr.CONNECT_S == 10, (rr.command(12, 20.0), rr.command(12, 1.0)))
check("1 an entry counts for 300 s, more than three of release.sh's sends each given its whole limit", rr.EXPIRE_S == 300 and rr.EXPIRE_S >= 3 * (60 + 20), rr.EXPIRE_S)

# ---- 2. store
wipe()
check("2 no folder (one box): nothing is listed, and reading makes nothing", rr.running() == {} and not (STATE / "releases").exists(), (rr.running(), STATE.exists()))
check("2 the folder is <state>/releases/running", rr.folder() == RUNDIR, rr.folder())
r = rr.put(12, ent(stamp=100, age=60.0, tail="twelve\n")); written_ago(12, 30); got = rr.running()
check("2 an entry is stored and listed under its number: the log was written `age` before the entry was, by this box's clock",
      r == "" and set(got) == {12} and abs(got[12][0] - ((RUNDIR / "pr-12").stat().st_mtime - 60.0)) < 0.01 and abs(time.time() - got[12][0] - 90) < 15 and got[12][1] == "twelve\n", (r, got))
for stamp, what in ((99, "an older"), (100, "an equal")):
    check(f"2 {what} stamp does not replace an entry that counts, and the put is not an error", rr.put(12, ent(stamp=stamp, tail="late\n")) == "" and rr.running()[12][1] == "twelve\n", rr.running())
rr.put(12, ent(stamp=101, tail="newer\n"))
check("2 a newer stamp replaces it", rr.running()[12][1] == "newer\n", rr.running())
rr.put(13, ent(stamp=5, tail="thirteen\n"))
check("2 one file a release: another release's entry leaves this one alone, both listed", set(rr.running()) == {12, 13} and rr.running()[12][1] == "newer\n" and sorted(p.name for p in RUNDIR.glob("pr-*")) == ["pr-12", "pr-13"], rr.running())
rr.put(12, ent(stamp=200, ended=True))
check("2 an ended entry is not listed", set(rr.running()) == {13}, rr.running())
rr.put(12, ent(stamp=150, tail="late beat\n"))
check("2 …and a beat sent before the end that arrives after it changes nothing: the release stays ended", set(rr.running()) == {13} and json.loads((RUNDIR / "pr-12").read_text())["ended"] is True, rr.running())
written_ago(13, rr.EXPIRE_S - 20)
check("2 an entry written just under 300 s ago still counts", set(rr.running()) == {13}, rr.running())
written_ago(13, rr.EXPIRE_S + 1)
check("2 …one written 300 s ago or more is not listed: a release that died without a word holds nothing", rr.running() == {}, rr.running())
rr.put(13, ent(stamp=1, tail="again\n"))
check("2 an expired entry is replaced whatever the stamps say", rr.running().get(13, (0, ""))[1] == "again\n", rr.running())
written_ago(12, rr.EXPIRE_S + 5); rr.put(14, ent(stamp=1))
check("2 a put removes the entries that have expired and keeps the ones that count", sorted(p.name for p in RUNDIR.glob("pr-*")) == ["pr-13", "pr-14"], sorted(p.name for p in RUNDIR.iterdir()))
BAD = {"not JSON": "{", "nothing": "", "a list": "[1]", "no stamp": json.dumps({"ended": False, "age": 1, "tail": ""}), "a stamp that is true": ent(stamp=True), "a stamp that is text": ent(stamp="5"),
       "ended that is not a boolean": ent(ended=0), "a tail that is not text": ent(tail=None), "a negative age": ent(age=-1), "an age that is not a number": ent(age=float("nan")), "an age that is text": ent(age="3")}
wipe()
refused = {k: rr.put(15, v) for k, v in BAD.items()}
check("2 what is not an entry (a send cut off, another shape) is refused and nothing is stored", all(v == "what came in is not a release entry" for v in refused.values()) and not RUNDIR.exists(), refused)
rr.put(16, ent(age=None, tail=""))
(RUNDIR / "pr-17").write_text("{half"); (RUNDIR / "pr-18.bak").write_text(ent()); (RUNDIR / ".pr-19.part").write_text(ent()); (RUNDIR / "pr-20").mkdir()
check("2 an entry with no log is listed without one; a file that does not read, another name, a half-written one and a folder are skipped", rr.running() == {16: None}, rr.running())

# ---- 3. send
old_path, old_fake = os.environ["PATH"], os.environ.get("FAKE_DIR")
os.environ.update(PATH=FENV["PATH"], FAKE_DIR=str(FAKE))
log = logfile("send.log", "2026-01-01T00:00:00Z deploying abc\n")
fake("ok"); why = rr.send("box-b", 12, log, ended=False, limit=20.0)
check("3 a send is one ssh call, BatchMode and a 10 s connect, the host and the command, with the entry on standard input",
      why == "" and lines(FAKE / "calls") == [f"-o BatchMode=yes -o ConnectTimeout=10 box-b {CMD}"] and len(entries()) == 1 and entries()[0]["tail"].endswith("deploying abc\n") and entries()[0]["ended"] is False, (why, lines(FAKE / "calls"), entries()))
fake("fail"); why = rr.send("box-b", 12, log, ended=False, limit=20.0)
check("3 a send that fails says its exit status and ssh's last line", why == "exit status 255: ssh: connect to host box-b port 22: Connection refused", why)
fake("hang"); t0 = time.monotonic(); why = rr.send("box-b", 12, log, ended=False, limit=1.0); took = time.monotonic() - t0
check("3 a send that is never answered is cut at its limit and its ssh is stopped", why == "no answer within 1 s" and took < 12 and not any(alive(p) for p in lines(FAKE / "pids")), (why, took, lines(FAKE / "pids")))
fake("linger"); t0 = time.monotonic(); why = rr.send("box-b", 12, log, ended=False, limit=3.0); took = time.monotonic() - t0
check("3 a send ssh answered is a success at once, though what ssh left behind still holds the output", why == "" and took < 2.8, (why, took))
until(lambda: not any(alive(p) for p in lines(FAKE / "lingering")))
os.environ["PATH"] = str(TMP / "no-such-bin"); why = rr.send("box-b", 12, log, ended=False, limit=5.0); os.environ["PATH"] = FENV["PATH"]
check("3 no ssh to start: said, not raised", why.startswith("ssh did not start"), why)
wipe(); fake("run"); why = rr.send("box-b", 12, log, ended=False, limit=40.0)
check("3 end to end: the command, run as the other box runs it, stores the entry in that box's state folder", why == "" and rr.running().get(12, (0, ""))[1].endswith("deploying abc\n"), (why, rr.running()))
held = open(RUNDIR / ".lock", "a"); fcntl.flock(held, fcntl.LOCK_EX)
t0 = time.monotonic(); why = rr.send("box-b", 12, log, ended=True, limit=13.0); took = time.monotonic() - t0
held.close()
check("3 …and a command that cannot finish there (the store is held) is cut on that box, before the sender's own limit", why.startswith("exit status 124") and took < 11 and 12 in rr.running(), (why, took))

def tool(*a, stdin="", env=None): return subprocess.run([sys.executable, TOOL, *a], input=stdin, env=env or FENV, capture_output=True, text=True, timeout=60)
fake("ok"); c = tool("end", "12", log, "box-b", "--limit", "20")
check("3 `end` sends the ended entry once: exit 0, silent", c.returncode == 0 and c.stdout == "" and len(lines(FAKE / "calls")) == 1 and [x["ended"] for x in entries()] == [True], (c.returncode, c.stdout, c.stderr, entries()))
fake("fail"); c = tool("end", "12", log, "box-b", "--limit", "20")
check("3 `end` that is not stored: exit 1 and one line that says why", c.returncode == 1 and c.stdout.strip() == "exit status 255: ssh: connect to host box-b port 22: Connection refused", (c.returncode, c.stdout, c.stderr))
wipe(); c = tool("put", "21", stdin=ent(tail="by hand\n")); d = tool("put", "22", stdin="junk")
check("3 `put` stores what is on standard input (exit 0); junk is exit 1 with the reason", c.returncode == 0 and d.returncode == 1 and "not a release entry" in d.stdout and set(rr.running()) == {21}, (c.returncode, c.stderr, d.returncode, d.stdout, rr.running()))
os.environ["PATH"] = old_path
if old_fake is None: os.environ.pop("FAKE_DIR", None)

# ---- 4. beat
beats = []      # every sender this suite started, ended whatever the checks say
def start_beat(parent, every="0.1", limit="20"):
    p = subprocess.Popen([sys.executable, TOOL, "beat", "12", log, "box-b", "--parent", str(parent), "--every", every, "--limit", limit], env=FENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    beats.append(p); return p
def stop(p, secs=20):
    p.terminate()
    try: out, _ = p.communicate(timeout=secs)
    except subprocess.TimeoutExpired: p.kill(); out, _ = p.communicate(); return None, out
    return p.returncode, out
try:
    fake("ok"); p = start_beat(os.getpid()); many = until(lambda: len(entries()) >= 3); rc, out = stop(p)
    es = entries()
    check("4 the sender sends at once and again every interval, each entry newer and not ended, while its parent is the process named, and says nothing while it succeeds",
          many and all(not x["ended"] for x in es) and [x["stamp"] for x in es] == sorted({x["stamp"] for x in es}) and rc == 0 and out == "", (many, rc, out, len(es)))
    fake("hang"); p = start_beat(os.getpid()); sending = until(lambda: lines(FAKE / "pids")); t0 = time.monotonic(); rc, out = stop(p, 10); took = time.monotonic() - t0
    gone = until(lambda: not any(alive(x) for x in lines(FAKE / "pids")), 5)
    check("4 stopped in the middle of a send, the sender ends at once and takes that ssh with it", sending and rc == 0 and took < 8 and gone, (sending, rc, took, gone))
    fake("ok"); p = start_beat(1)
    try: rc = p.wait(timeout=15)
    except subprocess.TimeoutExpired: rc = None; stop(p)
    check("4 a process that is not its parent: nothing is sent, the sender ends", rc == 0 and lines(FAKE / "calls") == [], (rc, lines(FAKE / "calls")))
    # a parent that goes away: a middle process starts the sender as its child, waits for two sends and exits; the sender is this suite's grandchild, known by its pid
    fake("ok"); pidfile = TMP / "orphan.pid"
    # it carries an alarm of its own (30 s, kept across runpy): a sender that did not end with its parent ends by itself, so nothing here has to signal a process that is not a child of this suite
    sender = ("import runpy, signal, sys; signal.alarm(30); "
              f"sys.argv = [{TOOL!r}, 'beat', '12', {log!r}, 'box-b', '--parent', sys.argv[1], '--every', '0.1', '--limit', '20']; runpy.run_path({TOOL!r}, run_name='__main__')")
    middle = ("import os, subprocess, sys, time\n"
              f"p = subprocess.Popen([sys.executable, '-c', {sender!r}, str(os.getpid())], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
              f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
              f"end = time.time() + 20\n"
              f"while time.time() < end and (not os.path.exists({str(FAKE / 'calls')!r}) or len(open({str(FAKE / 'calls')!r}).readlines()) < 2): time.sleep(0.02)\n")
    subprocess.run([sys.executable, "-c", middle], env=FENV, timeout=40, check=True)
    orphan = int(pidfile.read_text())
    ended = until(lambda: not alive(orphan), 10); n1 = len(lines(FAKE / "calls")); time.sleep(0.5); n2 = len(lines(FAKE / "calls"))
    check("4 a sender whose parent is gone sends nothing more and ends", ended and n1 >= 2 and n2 == n1, (ended, n1, n2))
    if not ended: until(lambda: not alive(orphan), 40)      # its own alarm ends it: no sender outlives this suite
    fake("fail"); p = start_beat(os.getpid()); a = until(lambda: len(lines(FAKE / "calls")) >= 4); (FAKE / "mode").write_text("ok"); b = until(lambda: len(entries()) >= 3); rc, out = stop(p)
    said = out.splitlines()
    check("4 a failure is said once, however many sends fail in a row, and so is the recovery",
          a and b and len(said) == 2 and "PR #12: box-b was not told that the release runs: exit status 255: ssh: connect" in said[0] and "PR #12: box-b is told again that the release runs" in said[1], said)
finally:
    for p in beats:
        if p.poll() is None: p.kill(); p.communicate()

# ---- 5. readers
OWN = "example-owner/stackshot"; releasing._OWN[:] = [OWN]
UNITS = {"v": "", "raise": False}
def unit_list(argv):      # never the host's systemd
    if UNITS["raise"]: raise OSError("no systemctl")
    return "".join(f"stackshot-release-{n}.service loaded active running release\n" for n in UNITS["v"].split())
releasing._run = unit_list
wipe(); UNITS["v"] = "7"
check("5 one box: the running releases are this box's units, as before", releasing.release_units() == {7} and not RUNDIR.exists(), releasing.release_units())
rr.put(12, ent(tail="x\n"))
check("5 a release another box told this one runs is listed beside this box's units", releasing.release_units() == {7, 12}, releasing.release_units())
UNITS["raise"] = True
check("5 …and listed on a box whose systemctl cannot be asked", releasing.release_units() == {12}, releasing.release_units())
UNITS.update(v="", **{"raise": False})
QUEUED = "2026-01-01T00:00:00Z release of PR #12 starts\n2026-01-01T00:01:00Z waiting: in the merge queue (QUEUED position 1)\n"
LOCAL = STATE / "releases/pr-12.log"
def local(text, age): LOCAL.parent.mkdir(parents=True, exist_ok=True); LOCAL.write_text(text); os.utime(LOCAL, (time.time() - age, time.time() - age))
wipe()
check("5 no log here and nothing told: no log", busy_hold.release_log(12) is None, busy_hold.release_log(12))
local("an old copy\n", 3 * 86400)
check("5 nothing told: this box's own file, as before", busy_hold.release_log(12)[1] == "an old copy\n", busy_hold.release_log(12))
rr.put(12, ent(stamp=1, age=120.0, tail=QUEUED)); g = busy_hold.release_log(12)
check("5 what the release box told comes before a file of that name here, with the age it told", g[1] == QUEUED and 119 <= time.time() - g[0] < 150, g)
local("a copy made a moment ago\n", 0)
check("5 …a file here that is newer by its time included (a copy)", busy_hold.release_log(12)[1] == QUEUED, busy_hold.release_log(12))
rr.put(12, ent(stamp=2, age=None, tail=""))
check("5 an entry with no log: this box's file", busy_hold.release_log(12)[1] == "a copy made a moment ago\n", busy_hold.release_log(12))
LOCAL.unlink()
ITEM = {"metadata": {}, "status": "open"}
def live(): return busy_hold.live_release("a1", units=releasing.release_units, anchored=lambda: {"a1": [f"{OWN}#12"]}, item=lambda g: ITEM, own_repo=releasing.own_repo, canon=lambda r: r.lower(),
                                         step_prs=releasing.step_prs, log=busy_hold.release_log, now=time.time)
rr.put(12, ent(stamp=3, age=120.0, tail=QUEUED)); words = live()
check("5 the busy hold's words for a release that runs on another box are the ones of a release here", words == "a release of PR #12 tied to this item is running (unit stackshot-release-12.service, its log written 2 min ago, in the merge queue (QUEUED position 1))", words)
rr.put(12, ent(stamp=4, age=16 * 60.0, tail=QUEUED))
check("5 …a release whose log there has not moved for 15 minutes is stuck and holds nobody", live() == "" and releasing.release_units() == {12}, live())
rr.put(12, ent(stamp=5, age=60.0, tail=QUEUED)); written_ago(12, rr.EXPIRE_S + 1)
check("5 …an expired entry holds nobody", live() == "", live())
rr.put(12, ent(stamp=6, age=60.0, tail=QUEUED))
SCOPED = {"a1": [f"https://github.com/{OWN}/pull/12"], "a2": [f"https://github.com/{OWN}/pull/13"]}
check("5 the Queued for release label: the item of a pull request whose release runs on another box", releasing.queued_items(SCOPED, []) == {"a1"}, releasing.queued_items(SCOPED, []))
rr.put(12, ent(stamp=7, ended=True))
check("5 …gone once that release said it ended", releasing.queued_items(SCOPED, []) == set() and live() == "", (releasing.queued_items(SCOPED, []), live()))

# ---- 6. release.sh
HOST = "deploy-host"
QUIET = {"SALA_CODEX_REVIEW": "off"}
def calls(s): return [l for l in ssh_all(s) if "release_running.py" in l]
def held_by(s): return lines(s["dir"] / "running_calls")                          # "<pid of the ssh> none[ openN...]" a send
def told(s, n=23):
    p = s["dir"] / f"remote/releases/running/pr-{n}"
    return json.loads(p.read_text()) if p.exists() else None
def publog(s): return lines(s["dir"] / "releases/running-publish.log")
SENT = f"-o BatchMode=yes -o ConnectTimeout=10 {HOST} cd ~/stackshot && exec timeout -k 2 8 python3 stackshot/core/release_running.py put 23"
def senders(d):      # the sender processes of the scenario in folder d (read only, never signalled)
    out = []
    for p in pathlib.Path("/proc").glob("[0-9]*"):
        try: a = (p / "cmdline").read_bytes().split(b"\0")
        except OSError: continue
        if b"beat" in a and any(x.endswith(b"release_running.py") for x in a) and any(str(d).encode() in x for x in a) and alive(p.name): out.append(int(p.name))
    return out

seen = {}
def look(d):      # while the release waits for the deploy lock: what the server box holds, and what the sender holds open
    f = d / "remote/releases/running/pr-23"
    seen["waiting"] = until(lambda: f.exists() and "another release holds the deploy lock; waiting" in json.loads(f.read_text())["tail"])
    seen["entry"] = json.loads(f.read_text()) if f.exists() else None
    pids = senders(d); seen["senders"] = pids
    for pid in pids[:1]:
        links = {}
        for fd in pathlib.Path(f"/proc/{pid}/fd").iterdir():
            try: links[int(fd.name)] = os.readlink(fd)
            except OSError: pass
        parent = int(pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
        seen["links"] = links; seen["tee"] = os.readlink(f"/proc/{parent}/fd/1")
s = fast("run-told", merge="ok", deploy_ssh=HOST, hold="until-waiting", lockhook=look, extra={**QUIET, "RELEASE_RUNNING_BEAT": "0.2"})
en = seen.get("entry") or {}
check("6 while a release runs, the server box holds its entry, sent again and again with the log's newest lines and their age",
      seen.get("waiting") and en.get("ended") is False and 0 <= (en.get("age") if en.get("age") is not None else -1) < 60 and len(calls(s)) >= 3, (seen.get("waiting"), en, len(calls(s))))
check("6 each send is the one ssh call: BatchMode, a 10 s connect, the host, the command under its 8 s limit there", len(calls(s)) >= 1 and set(calls(s)) == {SENT}, sorted(set(calls(s))))
links = seen.get("links", {})
check("6 the sender is one process, which holds neither the release's log pipe nor any file of the release state but its own log, and reads nothing",
      len(seen.get("senders", [])) == 1 and links.get(0) == "/dev/null" and links.get(1, "").endswith("/releases/running-publish.log") and links.get(2) == links.get(1) and seen.get("tee", "").startswith("pipe:")
      and seen["tee"] not in links.values() and all(v.endswith("/releases/running-publish.log") for v in links.values() if "/releases/" in v), (seen.get("senders"), links, seen.get("tee")))
check("6 …nor does its ssh hold any of the release's descriptors", held_by(s) and all(l.split(" ", 1)[1] == "none" for l in held_by(s)), held_by(s))
check("6 as the release exits, the server box is told it ended: the entry is ended, the last send, and no sender is left",
      s["rc"] == 0 and (told(s) or {}).get("ended") is True and senders(s["dir"]) == [] and not any(alive(p) for p in seen.get("senders", [])), (s["rc"], told(s), senders(s["dir"])))
check("6 the release itself is as ever: green, deployed, one report, nothing about it in its log and nothing in the sender's",
      s["deployed"] and len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS) and "was not told" not in s["log"] and publog(s) == [], (s["msgs"], s["log"][-300:], publog(s)))

def one_send(d): seen["first"] = until(lambda: len(lines(d / "running_calls")) >= 1); time.sleep(1.5); seen["after"] = len(lines(d / "running_calls"))
s = fast("run-default", merge="ok", deploy_ssh=HOST, hold="until-waiting", lockhook=one_send, extra=QUIET)
text = pathlib.Path(STACK, "release.sh").read_text()
check("6 by default a release sends every 60 s, each send given 20 s: one send at the start, none for the next moments, one more at the end",
      seen.get("first") and seen.get("after") == 1 and len(calls(s)) == 2 and 'RUN_BEAT="${RELEASE_RUNNING_BEAT:-60}"' in text and 'RUN_LIMIT="${RELEASE_RUNNING_LIMIT:-20}"' in text, (seen.get("after"), calls(s)))

s = fast("run-failed", checks="fail", deploy_ssh=HOST, extra=QUIET)
check("6 a release that fails before its merge says it ended too", s["rc"] == 1 and (told(s) or {}).get("ended") is True and senders(s["dir"]) == [] and len(red(s)) == 1, (s["rc"], told(s), s["msgs"]))

def three(d): seen["three"] = until(lambda: len(lines(d / "running_calls")) >= 3)
s = fast("run-fails", merge="ok", deploy_ssh=HOST, running_fails="1", hold="until-waiting", lockhook=three, extra={**QUIET, "RELEASE_RUNNING_BEAT": "0.2"})
check("6 every send fails: the release is green, deployed and reports once, as ever",
      s["rc"] == 0 and s["deployed"] and len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS) and seen.get("three") and told(s) is None, (s["rc"], s["msgs"], s["log"][-400:]))
check("6 …the sends beside it are said once, in the sender's own log, never in the release's",
      len(publog(s)) == 1 and "PR #23: deploy-host was not told that the release runs: exit status 255" in publog(s)[0] and "was not told that the release runs" not in s["log"], (publog(s), s["log"][-400:]))
last = [l for l in s["log"].splitlines() if "was not told that this release ended" in l]
check("6 …and the last word that fails is one line of the release log, with why and what follows, never in the words a waiter reads as a result",
      len(last) == 1 and "deploy-host was not told that this release ended (exit status 255: ssh: connect to host failed: Connection timed out): it may count it as running for up to 5 more minutes" in last[0] and " FAILED " not in s["log"], (last, s["log"][-400:]))

def hung(d): seen["hung"] = until(lambda: len(lines(d / "running_calls")) >= 1)
s = fast("run-hangs", merge="ok", deploy_ssh=HOST, running_hang="1", hold="until-waiting", lockhook=hung, extra={**QUIET, "RELEASE_RUNNING_LIMIT": "2"})
pids = [l.split()[0] for l in held_by(s)]
check("6 a server box that never answers: the release is green and ends after the last word's limit, and no send of it is left behind",
      s["rc"] == 0 and s["deployed"] and "was not told that this release ended (no answer within 2 s)" in s["log"] and len(pids) == 2 and not any(alive(p) for p in pids) and senders(s["dir"]) == [] and s["secs"] < 25, (s["rc"], s["secs"], pids, s["log"][-400:]))

s = fast("run-onebox", merge="ok", extra=QUIET)
check("6 one box (deploy_ssh unset): no sender, no ssh, no file of it, no line about it",
      s["rc"] == 0 and ssh_all(s) == [] and not (s["dir"] / "releases/running-publish.log").exists() and not (s["dir"] / "releases/running").exists() and not (s["dir"] / "remote").exists() and "was not told" not in s["log"], (s["rc"], ssh_all(s), s["log"][-300:]))
s = fast("run-badhost", merge="ok", deploy_ssh="-oProxyCommand=evil", extra=QUIET)
check("6 a deploy_ssh that is not a host name starts no sender and reaches no ssh", s["rc"] == 1 and ssh_all(s) == [] and not (s["dir"] / "releases/running-publish.log").exists() and "was not told" not in s["log"], (s["rc"], ssh_all(s), s["log"][-300:]))

finish()
