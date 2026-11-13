"""Scenario test for: no automatic return or fallback goes to a front agent, and an item notice reaches a front agent only while Oliver is there
and the agent touched the item in its current conversation. Fixture data, no live store, no network, no server socket, no tmux.

  1  the hand-off ladder never returns an item to a front agent: the builder first, else the fleet's builder is asked to recover the session, with the mover unchanged; a project without a builder keeps the item and says so
  2  stackshot's own picks: auto_mover / no_front, the cold call is offered background agents only
  3  what Oliver or a session set explicitly (a mover that is a front agent) is left as written
  4  presence: no stamp, a stale stamp, a stamp from the future, a stamp inside [presence] minutes, the config key and its default
  5  touched: the item's writer since the pane's startedAt (the file on disk, and the store's git revisions)
  6  what the agent hears: absent or not touched -> nothing (logged held); present and touched -> an fyi line on its next turn (no push); a close or a stuck notice -> the normal push
  7  not gated: a relayed board answer, a wake/watch/idle/wait/comment notice, a background agent
  9  the senders are wired to the gate (close / stuck kinds), written_at, every tag has a kind, a hand-back never goes to a front mover
  10 the review round: the owner-change fallback is gated (progress), a reply never says "told" for a notice the gate held, the builder's hand-back line rides its next turn (held path, a close inside the
     hold drops it, an old record with no writer tells nobody), no start time is no touch, a [presence] minutes that is no number above 0 is said at config load
  8  the board always reaches him: every case that reaches a front pane leaves its board record in the same pass, and a held case leaves it too
     (a progress notice: a History line; a close: the item's close revision; a stuck notice: the wait_failed mark, past due)

    tests/run-suite front_quiet        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging, subprocess
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="frontquiet-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")      # the git case below commits into the temp store only
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-docs", "home-peer", "home-send", "home-beta-front", "home-stew", "home-beta-stew")
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
def proj(session, agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": session, "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
# alpha: front home-front; background home-docs (listed first) and team-back (builds); beta: a front agent and no background agent (nobody to build)
ALPHA = {"home-front": "the front", "home-docs": "keeps the pages", "team-back": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": proj("home-stew", ALPHA, {k: ALPHA[k] for k in ("home-docs", "team-back")}),
    "projects/beta": proj("home-beta-stew", {"home-beta-front": "the front"}, {})}}))
for key, name, agents in (("alpha", "home-stew", ALPHA), ("beta", "home-beta-stew", {"home-beta-front": "the front"})):
    back = [k for k in agents if k in ("home-docs", "team-back")]
    front = [k for k in agents if k not in back]
    (T / f"brain/projects/{key}.md").write_text(f"---\ntitle: {key}\ndisplay-name: {name}\nagents:\n" + "".join(f"  {k}: {agents[k]}\n" for k in front)
                                                 + ("  background:\n" + "".join(f"    {k}: {agents[k]}\n" for k in back) if back else "") + f"---\n\n# {key}\n\n## Current state\n\nSTATE-OF-{key.upper()}: the vendor call is open.\n\n<!-- timeline -->\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
STARTED = now0 - 3600.0          # the front pane's process started then: a write by it after this is in "this conversation"
def item(i, project="projects/alpha", mover="home-peer", status="open", updated=None, writer="", **meta):
    up = now0 - 600.0 if updated is None else updated
    base = {"owner": U["home-front"], "project": project, "next": f"{mover}: do the thing"}
    if mover: base["mover"] = mover
    base.update(meta)
    d = {"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": up, "state_updated": up, "confirmed": up, "metadata": base}
    if writer: d["written_by"] = writer; d["written_by_id"] = U[writer]
    (T / f"store/a/{i}.json").write_text(json.dumps(d))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.waits import handoff as H; from stackshot.router import routing; from stackshot.waits import held; from stackshot.waits import quiet as Q
from stackshot.service import telling
from stackshot.web.ui import render as ui_render
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []
_real_tell = telling.tell_woken
def _tell(gid, owner, note, tag="wake", result=None):
    th = _real_tell(gid, owner, note, tag)
    if th: THREADS.append(th)
    return th
telling.tell_woken = _tell
def drain():
    while THREADS: THREADS.pop(0).join(30)
def pushes(): return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
def pushes_to(who, gid=None): return [p for p in pushes() if p[0] == U[who] and (gid is None or gid in p[1])]
server.CLI_SESSIONS = T / "cli"
def cli_row(who, started=STARTED, status="idle"):
    """The CLI's own registry row of a pane on this box: an interactive pane with its sessionId and when its process started (ms)."""
    (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": status, "startedAt": int(started * 1000),
                                                                  "statusUpdatedAt": int((now0 - 75) * 1000), "updatedAt": int((now0 - 75) * 1000)}))
def stamp(who, age=60.0, text=None):
    """The prompt hook's stamp file for a pane: epoch seconds of Oliver's last prompt in it, `age` seconds ago."""
    p = T / "state/prompts" / U[who]; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if text is not None else f"{time.time() - age:.0f}\n")
def unstamp(who): (T / "state/prompts" / U[who]).unlink(missing_ok=True)
def set_presence(**kw):
    if kw: server._cfg.CFG["presence"] = dict(kw)
    else: server._cfg.CFG.pop("presence", None)
server._cfg.CFG["model"] = {}
set_presence()
def tell(gid, who, note, tag="owner", kind=""):
    """One item notice for `who` through the real tell_woken (the gate); `kind` is the sender's hint (tell_kind) -> the pushes it made, the held lines added, the routing-log lines of the project."""
    p0, h0 = len(pushes()), held.count(U[who])
    (telling.tell_kind(kind, gid, U[who], note, tag=tag) if kind else telling.tell_woken(gid, U[who], note, tag=tag)); drain()
    return pushes()[p0:], held.count(U[who]) - h0
def held_log(gid):
    return [n for n in routing.read("projects/alpha") + routing.read("projects/beta") if n.get("ruling") == "held" and str(n.get("reason", "")).startswith("held: front agent") and gid in str(n.get("label", ""))]
def quiet_log(i): return Q.log_of(mt(i))
NOTE = lambda g: f"[stackshot] {g} \"[home] item\" (projects/alpha): a session wrote the item → https://x/items/{g}"

# ================================================================ 1. the hand-off ladder never returns to a front agent
env = server._handoff_env(now0)
r_front = {"from": "home-front", "origin": "home-front", "to": "home-peer"}
it_a = {"metadata": {"project": "projects/alpha"}}; it_b = {"metadata": {"project": "projects/beta"}}
st = H.next_step(it_a, r_front, "home-peer", "its pane is gone", env, gid="a1", cold_ok=False)
check("1 ladder: a front agent origin is not returned to; the project's builder is, first", st.kind == "move" and st.to == "team-back" and st.via == "redirect", st)
st = H.next_step(it_a, {**r_front, "tried": ["team-back"]}, "home-peer", "its pane is gone", env, gid="a1", cold_ok=False)
check("1 ladder: …builder tried: not the front origin either: the recovery request", st.kind == "recover" and st.to == "", st)
st = H.next_step(it_b, r_front, "home-peer", "its pane is gone", env, gid="a1", cold_ok=False)
check("1 ladder: a project with no builder keeps the item with its current mover and says so: the recovery request, \"the project lists no builder\", no move to the front agent", st.kind == "recover" and "no builder" in st.why, st)
st = H.next_step(it_b, {"from": "home-send", "origin": "home-send", "to": "home-peer"}, "home-peer", "its pane is gone", env, gid="a1", cold_ok=False)
check("1 ladder: …a sender that is no front agent is still returned to (the rule is only about front agents)", st.kind == "move" and st.to == "home-send" and st.via == "return", st)
st = H.next_step(it_b, r_front, "home-peer", "its pane is gone", env, gid="a1")
check("1 ladder: …the cold call is still the step before the recovery request (it may name a background agent)", st.kind == "cold", st)
env2 = H.Env(now=now0, derive=lambda i: None, is_front=lambda w, p: False, background=lambda p: [])
st = H.next_step(it_b, r_front, "home-peer", "gone", env2, gid="a1", cold_ok=False)
check("1 ladder: …with the old test (nobody is front) the return happens: the Env flag is what changes it", st.kind == "move" and st.to == "home-front", st)

# ================================================================ 2. stackshot's own picks
check("2 pick: a front agent becomes the project's builder", telling.no_front("home-front", "projects/alpha") == "team-back", telling.no_front("home-front", "projects/alpha"))
check("2 pick: …a project without a builder: \"\" (the caller keeps the item where it is)", telling.no_front("home-beta-front", "projects/beta") == "", telling.no_front("home-beta-front", "projects/beta"))
check("2 pick: …a session that is no front agent is as given", telling.no_front("home-send", "projects/alpha") == "home-send" and telling.no_front("", "projects/alpha") == "")
check("2 auto mover: front -> builder; builderless keeps its own (the item model's default); non-front as given",
      telling.auto_mover("home-front", "projects/alpha") == "team-back" and telling.auto_mover("home-beta-front", "projects/beta") == "home-beta-front" and telling.auto_mover("home-send", "projects/alpha") == "home-send")
names = [a["name"] for a in server._handoff_agents("projects/alpha")]
check("2 cold call: the agents it may hand to are the background ones; the front agent is not offered", sorted(names) == ["home-docs", "team-back"], names)
check("2 cold call: a project with no background agent offers none", server._handoff_agents("projects/beta") == [], server._handoff_agents("projects/beta"))

# ================================================================ 3. an explicit front mover is left as written
item(60, mover="home-front", writer="home-send")
check("3 explicit: a front agent set as mover by a session stays the mover (no automatic move)", mt(60)["mover"] == "home-front" and H.plan({"a60": rd(60)}, server._handoff_env(now0)) == [], H.plan({"a60": rd(60)}, server._handoff_env(now0)))

# ================================================================ 4. presence
cli_row("home-front")
check("4 presence: no stamp file: not there", telling.presence_here("home-front") is False)
stamp("home-front", 60)
check("4 presence: a stamp 1 minute old: there", telling.presence_here("home-front") is True)
stamp("home-front", 29 * 60)
check("4 presence: 29 minutes: there (the default is 30)", telling.presence_here("home-front") is True)
stamp("home-front", 31 * 60)
check("4 presence: 31 minutes (stale): not there", telling.presence_here("home-front") is False)
set_presence(minutes=60)
check("4 presence: [presence] minutes = 60 makes the same stamp fresh", telling.presence_here("home-front") is True)
set_presence(minutes=5); stamp("home-front", 10 * 60)
check("4 presence: [presence] minutes = 5 makes a 10 minute stamp stale", telling.presence_here("home-front") is False)
set_presence(); stamp("home-front", 31 * 60)
check("4 presence: …a missing [presence] section is the default 30", telling.presence_here("home-front") is False and telling.presence_minutes() == 30.0)
set_presence(minutes="soon")
check("4 presence: …an unreadable value is the default too", telling.presence_minutes() == 30.0)
set_presence()
stamp("home-front", text="not a number\n"); a = telling.presence_here("home-front")
stamp("home-front", text=""); b = telling.presence_here("home-front")
stamp("home-front", -600.0); c = telling.presence_here("home-front")
check("4 presence: an unreadable, an empty or a future stamp: not there", (a, b, c) == (False, False, False), (a, b, c))
unstamp("home-front"); no_pane = telling.presence_here("home-send")
check("4 presence: a session this box has no pane for: not there", no_pane is False)
stamp("home-front", 60)
example = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
check("4 presence: the example config documents [presence] minutes = 30", re.search(r"(?m)^\[presence\]", example) and re.search(r"(?m)^minutes = 30\b", example[example.index("[presence]"):]))

# ================================================================ 5. touched: the writer since the pane's start
item(10, writer="home-front", updated=now0 - 600)
check("5 touched: the item on disk was last written by the agent after its process started", telling.touched("a10", "home-front", STARTED) is True)
item(11, writer="home-send", updated=now0 - 600)
check("5 touched: …written by another session: not touched", telling.touched("a11", "home-front", STARTED) is False)
item(12, writer="home-front", updated=STARTED - 600)
check("5 touched: …written by it before this conversation began (a relaunch, a resume, a recycle): not touched", telling.touched("a12", "home-front", STARTED) is False)
item(13)
check("5 touched: …a revision with no writer (a server write): not touched", telling.touched("a13", "home-front", STARTED) is False)
check("5 touched: …a notice naming several items: any one counts", telling.touched("a11,a10", "home-front", STARTED) is True and telling.touched("a11,a13", "home-front", STARTED) is False)
# the store's git revisions: the agent wrote it in this conversation, another session wrote it since
def git(*a, when=None):
    env_ = {**os.environ, **({"GIT_AUTHOR_DATE": f"{int(when)} +0000", "GIT_COMMITTER_DATE": f"{int(when)} +0000"} if when else {})}
    return subprocess.run(["git", "-C", str(T / "store"), *a], capture_output=True, text=True, env=env_)
git("init", "-q"); git("config", "commit.gpgsign", "false")
item(14, writer="home-front", updated=now0 - 1800); git("add", "a/14.json"); git("commit", "-q", "-m", "front writes", when=now0 - 1800)
item(14, writer="home-send", updated=now0 - 300); git("add", "a/14.json"); git("commit", "-q", "-m", "send writes", when=now0 - 300)
check("5 touched: …the file's last writer is another session, but the agent wrote an earlier revision in this conversation (store git): touched", telling.touched("a14", "home-front", STARTED) is True, telling.writers_since("a14", STARTED))
item(15, writer="home-front", updated=STARTED - 900); git("add", "a/15.json"); git("commit", "-q", "-m", "front writes before", when=STARTED - 900)
item(15, writer="home-send", updated=now0 - 300); git("add", "a/15.json"); git("commit", "-q", "-m", "send writes", when=now0 - 300)
check("5 touched: …its only revision is from before the pane started: not touched", telling.touched("a15", "home-front", STARTED) is False, telling.writers_since("a15", STARTED))

# ================================================================ 6. what the agent hears
stamp("home-front", 60); held.mark_client(U["home-front"], "home-front")
# absent: nothing
unstamp("home-front"); item(20, writer="home-front")
p, h = tell("a20", "home-front", NOTE("a20"))
check("6 absent: Oliver is not there: no push, no held line, nothing told", p == [] and h == 0, (p, h))
check("6 absent: …logged as held in the routing log, with the reason", held_log("a20") and "not there" in held_log("a20")[-1]["reason"], routing.read("projects/alpha"))
# present, not touched
stamp("home-front", 60); item(21, writer="home-send")
p, h = tell("a21", "home-front", NOTE("a21"))
check("6 not touched: Oliver is there but the agent did not touch the item: nothing, logged held", p == [] and h == 0 and held_log("a21") and "did not touch" in held_log("a21")[-1]["reason"], (p, h, held_log("a21")))
# present and touched: fyi
item(22, writer="home-front")
p, h = tell("a22", "home-front", NOTE("a22"))
check("6 fyi: present and touched: an ordinary progress notice rides the next turn as one held fyi line, no push", p == [] and h == 1, (p, h))
check("6 fyi: …logged as held (rides his next turn)", held_log("a22") and "next turn (fyi" in held_log("a22")[-1]["reason"], held_log("a22"))
txt = held.take(U["home-front"])
check("6 fyi: …the line is the notice's own words", "a22" in txt and "a session wrote the item" in txt, txt)
# a stale stamp
stamp("home-front", 31 * 60); item(23, writer="home-front")
p, h = tell("a23", "home-front", NOTE("a23"))
check("6 stale: a stamp older than [presence] minutes counts as absent: nothing", p == [] and h == 0 and held_log("a23"), (p, h))
set_presence(minutes=60)
p, h = tell("a23", "home-front", NOTE("a23") + " again")
check("6 config: [presence] minutes = 60 and the same stamp: present: the fyi line", p == [] and h == 1, (p, h)); held.take(U["home-front"]); set_presence()
# a hook that cannot fetch held lines: nothing is delivered
cli_row("home-beta-front"); stamp("home-beta-front", 60); item(24, project="projects/beta", mover="home-peer", writer="home-beta-front")
p, h = tell("a24", "home-beta-front", NOTE("a24"))
check("6 no hook: present and touched, but its hook does not fetch held lines: nothing is pushed (a new turn is not worth an fyi), logged held", p == [] and h == 0 and held_log("a24") and "cannot fetch" in held_log("a24")[-1]["reason"], (p, h, held_log("a24")))
# a close and a stuck notice: the normal push
stamp("home-front", 60); item(25, writer="home-front")
p, h = tell("a25", "home-front", NOTE("a25") + " closed", tag="close")
check("6 close: present and touched: a close is told as a normal notice (a push)", len(p) == 1 and p[0][0] == U["home-front"] and h == 0, (p, h))
item(26, writer="home-front")
p, h = tell("a26", "home-front", NOTE("a26") + " closed", kind="close")
check("6 close: …the sender's own hint says the same", len(p) == 1 and h == 0, (p, h))
unstamp("home-front"); item(27, writer="home-front")
p, h = tell("a27", "home-front", NOTE("a27") + " closed", tag="close")
check("6 close: Oliver not there: nothing told, logged held", p == [] and h == 0 and held_log("a27"), (p, h))
stamp("home-front", 60); item(28, writer="home-send")
p, h = tell("a28", "home-front", NOTE("a28") + " closed", tag="close")
check("6 close: there, but the agent did not touch the item: nothing told", p == [] and h == 0 and held_log("a28"), (p, h))
item(29, writer="home-front")
p, h = tell("a29", "home-front", NOTE("a29") + " stuck", kind="stuck")
check("6 stuck: present and touched: told as a normal notice (a push)", len(p) == 1 and h == 0, (p, h))

# ================================================================ 7. not gated
unstamp("home-front"); item(30, writer="home-send")
item(31, writer="home-send")
p, h = tell("a31", "home-front", "[for Oliver] " + NOTE("a31"))
check("7 gated: a [for Oliver] mark exempts nothing (review round): a progress notice carrying it, Oliver away, is held like any other", p == [] and h == 0 and held_log("a31"), (p, h))
p, h = tell("a30", "home-front", NOTE("a30") + " (his answer)", tag="answer")
check("7 not gated: his board answer relayed (tag answer) is pushed", len(p) == 1, (p, h))
p, h = tell("a30", "home-front", NOTE("a30") + " (a message)", kind="exempt")
check("7 not gated: a notice its sender marks exempt (a message sent on purpose, a hand-off) is pushed", len(p) == 1, (p, h))
for t in ("wake", "watch", "idle", "wait", "comment"):
    p, h = tell("a30", "home-front", NOTE("a30") + f" ({t})", tag=t)
    check(f"7 not gated: a {t} notice asks its mover to act, so it is pushed without presence", len(p) == 1 and h == 0, (t, p, h))
cli_row("team-back")
p, h = tell("a30", "team-back", NOTE("a30") + " by a session")
check("7 not gated: a background agent is told as before", len(p) == 1 and p[0][0] == U["team-back"], (p, h))
check("7 not gated: …none of these left a front-agent board line", not quiet_log(30), quiet_log(30))

# ================================================================ 8. the board always reaches him
def history(i):
    """The item's History as the board shows it, from two stubbed revisions: the item as it was before the notice, and as it is now."""
    now_ = rd(i)
    before = json.loads(json.dumps(now_)); before["metadata"].pop("front_quiet", None)
    bd = ui_render.Board(str(T / "store")); row = bd.item(f"a{i}")
    bd.item_versions = lambda r: [(now0 - 500, before), (now0 - 400, now_)]
    evs, _more = bd.item_events(row)
    return evs
# (a) a progress notice that is told on the next turn leaves a History line
stamp("home-front", 60); item(40, writer="home-front")
p, h = tell("a40", "home-front", NOTE("a40"))
ql = quiet_log(40)
check("8 board: an fyi that reaches the pane leaves a line on the item in the same pass: \"<agent> hears of it on his next turn: <news>\"", p == [] and h == 1 and len(ql) == 1 and ql[0]["text"].startswith("home-front hears of it on his next turn:") and "a session wrote the item" in ql[0]["text"], (p, h, ql))
ev = [x for x in history(40) if x[1] == "front"]
check("8 board: …and the History shows it (a \"front\" line from stackshot)", len(ev) == 1 and "stackshot:" in ev[0][2] and "hears of it on his next turn" in ev[0][2], history(40))
check("8 board: …written by the server: no writer, no clock moved, the writer of record is still the agent", rd(40)["written_by"] == "home-front" and rd(40)["updated"] == now0 - 600 and rd(40)["state_updated"] == now0 - 600, rd(40))
# (b) a held case leaves it too
unstamp("home-front"); item(41, writer="home-front")
p, h = tell("a41", "home-front", NOTE("a41"))
ql = quiet_log(41)
check("8 board: a held notice (Oliver not there) leaves its line: \"<agent> was not told (<why>): <news>\"", p == [] and h == 0 and len(ql) == 1 and ql[0]["text"].startswith("home-front was not told (") and "not there" in ql[0]["text"] and "a session wrote the item" in ql[0]["text"], (p, h, ql))
ev = [x for x in history(41) if x[1] == "front"]
check("8 board: …and the History shows it", len(ev) == 1 and "was not told" in ev[0][2], history(41))
stamp("home-front", 60); item(42, writer="home-send")
p, h = tell("a42", "home-front", NOTE("a42"))
check("8 board: …held because the agent did not touch the item: the line says why", p == [] and len(quiet_log(42)) == 1 and "did not touch" in quiet_log(42)[0]["text"], quiet_log(42))
p, h = tell("a24", "home-beta-front", NOTE("a24") + " second")
check("8 board: …held because its hook cannot fetch held lines: the line says why", len(quiet_log(24)) >= 1 and "cannot fetch" in quiet_log(24)[-1]["text"], quiet_log(24))
# (c) the same notice twice is one line; a different one is a second line
p, h = tell("a40", "home-front", NOTE("a40"))
check("8 board: the same news twice is one line", len(quiet_log(40)) == 1, quiet_log(40))
p, h = tell("a40", "home-front", NOTE("a40") + " and then more")
check("8 board: …different news is another line", len(quiet_log(40)) == 2, quiet_log(40)); held.take(U["home-front"])
# (d) more than the item keeps: the newest stay
for k in range(Q.KEEP + 3): tell("a40", "home-front", NOTE("a40") + f" n{k}")
check("8 board: an item keeps its newest lines (bounded)", len(quiet_log(40)) == Q.KEEP and quiet_log(40)[-1]["text"].endswith(f"n{Q.KEEP + 2}"), [x["text"][-6:] for x in quiet_log(40)]); held.take(U["home-front"])
# (e) a close: the close revision is the board record; told or held, it stands
stamp("home-front", 60); item(43, writer="home-front")
before = rd(43)
(T / "store/a/43.json").write_text(json.dumps({**before, "status": "completed", "updated": now0 - 75, "metadata": {**before["metadata"], "outcome": "done"}}))
p, h = tell("a43", "home-front", NOTE("a43") + " closed", tag="close")
bd = ui_render.Board(str(T / "store")); row = bd.item("a43"); bd.item_versions = lambda r: [(now0 - 500, before), (now0 - 75, rd(43))]
evs, _m = bd.item_events(row)
check("8 board: a close that reaches the pane (a push) has the item's own close in the History, and no extra line is written for it", len(p) == 1 and rd(43)["status"] == "completed" and any(k == "completed" for _t, k, _h in evs) and not quiet_log(43), (p, evs, quiet_log(43)))
unstamp("home-front"); item(44, writer="home-front")
before = rd(44)
(T / "store/a/44.json").write_text(json.dumps({**before, "status": "completed", "updated": now0 - 75, "metadata": {**before["metadata"], "outcome": "done"}}))
p, h = tell("a44", "home-front", NOTE("a44") + " closed", tag="close")
bd = ui_render.Board(str(T / "store")); row = bd.item("a44"); bd.item_versions = lambda r: [(now0 - 500, before), (now0 - 75, rd(44))]
evs, _m = bd.item_events(row)
check("8 board: a close that is held (Oliver not there) is in the History all the same", p == [] and held_log("a44") and rd(44)["status"] == "completed" and any(k == "completed" for _t, k, _h in evs), (p, evs))
# a progress notice about a closed item writes no line (its close is the record)
p, h = tell("a44", "home-front", NOTE("a44") + " late news")
check("8 board: …a progress notice about an item already closed adds no line", not quiet_log(44), quiet_log(44))
# (f) a stuck notice: the stuck mark is the board record, written before the notice and kept whether it is told or held
real_keeper = telling.project_keeper
telling.project_keeper = lambda project, owner="": "home-beta-front"       # a project whose keeper is its -main agent (no builder, no steward)
def stuck_case(i, writer):
    item(i, project="projects/beta", mover="home-peer", writer=writer, check=f"item_closed a{i + 75}")
    it = server._load(f"a{i}"); t0 = len(pushes_to("home-beta-front", f"a{i}"))
    server._check_fail(f"a{i}", it, f"item_closed a{i + 75}", "the item it waits for was dropped", time.time()); drain()
    return len(pushes_to("home-beta-front", f"a{i}")) - t0
try:
    stamp("home-beta-front", 60)
    n = stuck_case(50, "home-beta-front")
    check("8 board: a stuck notice that reaches the pane (present and touched) is a push, and the item carries the stuck mark: wait_failed on the item", n == 1 and (mt(50).get("wait_failed") or {}).get("why") == "the item it waits for was dropped", (n, mt(50)))
    unstamp("home-beta-front")
    n = stuck_case(51, "home-beta-front")
    check("8 board: …the same stuck notice held (Oliver not there) tells nobody, and the mark is all the same", n == 0 and held_log("a51") and (mt(51).get("wait_failed") or {}).get("why"), (n, mt(51), held_log("a51")))
    stamp("home-beta-front", 60)
    n = stuck_case(52, "home-send")
    check("8 board: …held because the agent did not touch the item: the mark stays", n == 0 and held_log("a52") and (mt(52).get("wait_failed") or {}).get("what"), (n, mt(52)))
finally:
    telling.project_keeper = real_keeper
# (g) the pass that tells a front pane is never the only record: for every told case above there is a record on the item
told_cases = {"fyi": quiet_log(40), "close": rd(43)["status"] == "completed", "stuck": mt(50).get("wait_failed")}
check("8 board: every case that reached a front pane (fyi, close, stuck) left its board record", all(told_cases.values()), told_cases)
held_cases = {"fyi/absent": quiet_log(41), "fyi/untouched": quiet_log(42), "close": rd(44)["status"] == "completed", "stuck": mt(51).get("wait_failed")}
check("8 board: every held case left it too", all(held_cases.values()), held_cases)

# ================================================================ 9. the senders are wired to the gate, and nothing returns an item to a front agent behind its back
import inspect
# (a) written_at: a write by a session stamps it; a server save leaves it (and so "touched") alone
d71 = {"metadata": {}}
writes.record_writer(d71, U["home-front"], None)
check("9 written_at: a write by a session stamps written_by and written_at (now)", d71.get("written_by") == "home-front" and abs(d71.get("written_at", 0) - time.time()) < 5, d71)
d72 = {"metadata": {}, "written_by": "home-send", "written_at": 123.0}
writes.record_writer(d72, "", None)
check("9 written_at: …a server write (no writer) leaves the stamp and written_at as the last real writer left them", d72["written_by"] == "home-send" and d72["written_at"] == 123.0, d72)
item(71, writer="home-front", updated=STARTED - 75); d = rd(71); d["written_at"] = STARTED - 75; (T / "store/a/71.json").write_text(json.dumps(d))
it71 = server._load("a71"); it71["updated"] = time.time(); writes.save("a71", it71)      # a server save: `updated` moves, the writer stamp does not
check("9 written_at: …so a server save after the pane started is no touch by the agent whose earlier write predates it", rd(71)["updated"] > STARTED and rd(71)["written_at"] == STARTED - 75 and telling.touched("a71", "home-front", STARTED) is False, rd(71))
# (b) every sender of a close or a stuck notice gives the gate its kind
src = lambda fn: inspect.getsource(fn)
for name in ("tell_owner_close", "tell_owner_check_closed", "close_owner_notice", "tell_close_mentions"):
    check(f"9 wiring: {name} tells a close as kind close", 'tell_kind("close"' in src(getattr(telling, name)) or 'tell_kind("close" if' in src(getattr(telling, name)), name)
check("9 wiring: tell_wait_failed tells a stuck item as kind stuck", 'tell_kind("stuck"' in src(telling.tell_wait_failed))
# (c) tag coverage: a tag passed to tell_woken / tell_kind is in the map (owner and observer are mapped to progress, no exemption by name), so a new tag is a decision
sv = pathlib.Path(STACK, "stackshot/web/server.py").read_text(encoding="utf-8")
tags = set(re.findall(r'tag="([a-z_]+)"', sv))
missing = sorted(t for t in tags if t not in telling.FRONT_TAG_KIND)
check("9 tags: every tag the server passes to the gate is in FRONT_TAG_KIND; a new tag names its kind", not missing, missing)
check("9 tags: …owner and observer are mapped (to progress), not exempted by name", telling.FRONT_TAG_KIND.get("owner") == "progress" and telling.FRONT_TAG_KIND.get("observer") == "progress", telling.FRONT_TAG_KIND)
# (d) a hand-back "back with you alone" never goes to a front mover: to the project's builder, or to nobody
def rec_for(oid, project, wid):
    return {"gid": "a73", "oid": U[oid], "olabel": oid, "project": project, "who": "home-send", "wid": U[wid], "subject": "[home] item 73", "line": "[stackshot] a73 is back with you alone (handed back by home-send): [home] item 73 \u2192 https://x/items/a73"}
item(73, writer="home-send")
p0 = len(pushes()); telling.handback_send(rec_for("home-front", "projects/alpha", "home-send")); drain()
got = pushes()[p0:]
check("9 hand-back: a front agent mover is not told: its builder is, in words that say so", not [x for x in got if x[0] == U["home-front"]] and len([x for x in got if x[0] in (U["team-back"], "team-back")]) == 1
      and "is back with home-front, a front agent, alone" in got[0][1] and "told to you, not to home-front" in got[0][1], got)
p0 = len(pushes()); telling.handback_send(rec_for("home-front", "projects/alpha", "team-back")); drain()
check("9 hand-back: …the builder that wrote the hand-back itself is told nothing, and the routing log says it was held", pushes()[p0:] == [] and held_log("a73"), (pushes()[p0:], held_log("a73")))
item(74, project="projects/beta", writer="home-send")
p0 = len(pushes()); telling.handback_send({**rec_for("home-beta-front", "projects/beta", "home-send"), "gid": "a74"}); drain()
check("9 hand-back: …a project with no builder tells nobody (the item stays with its mover, the board shows it)", pushes()[p0:] == [] and any("no builder" in str(n.get("reason", "")) for n in routing.read("projects/beta") if "a74" in str(n.get("label", ""))), (pushes()[p0:], routing.read("projects/beta")[-2:]))

# ================================================================ 10. the review round
import inspect as _insp
from stackshot.core import config as _config
# (1) the owner-change fallback: progress, so the gate applies
check("10 fallback: tell_owner_change's last resort (the notice could not be recorded for the router) is a progress notice, not exempt", 'tell_kind("progress", gid, kept or stew' in _insp.getsource(telling.tell_owner_change) and 'tell_kind("exempt"' not in _insp.getsource(telling.tell_owner_change))
_saved = (telling.stand_in_keeper, server._anc.pilot_root, server._routing.record)
try:
    telling.stand_in_keeper = lambda *a, **k: U["home-front"]; server._anc.pilot_root = lambda p, *a, **k: "projects/alpha"; server._routing.record = lambda *a, **k: ""      # the page's stand-in is the front agent home-front; the routing record fails (no nid)
    unstamp("home-front"); item(75, mover="home-beta-front", writer="home-send", next="home-beta-front: do the thing"); it = server._load("a75"); telling.OWNER_HEARD.clear()
    p0, h0 = len(pushes()), held.count(U["home-front"])
    reply = telling.tell_owner_change("a75", it, {**it["metadata"], "next": "home-beta-front: the old thing"}, "home-send", False, False); drain()
    check("10 fallback: …with Oliver away from the keeper's pane it is held (no push), not sent as an exempt notice", pushes()[p0:] == [] and held.count(U["home-front"]) == h0 and telling.gate_result()[0] == "held", (reply, pushes()[p0:], telling.gate_result()))      # the routing log line is not asserted here: record is patched out
finally:
    (telling.stand_in_keeper, server._anc.pilot_root, server._routing.record) = _saved

# (2) a reply never says "told" for a notice the gate held
unstamp("home-front"); item(16, mover="home-front", writer="home-front"); it = server._load("a16"); hl = []
r = telling.tell_owner_close("a16", it, "home-send", True, hl); drain()
check("10 reply: a close of a front agent mover's item, Oliver away: the reply says it was not told, and that the close is on the board", "not told that it was closed" in r and "told at once" not in r and "on the board" in r, r)
stamp("home-front", 60); item(17, mover="home-front", writer="home-front"); it = server._load("a17"); hl = []; p0 = len(pushes())
r = telling.tell_owner_close("a17", it, "home-send", True, hl); drain()
check("10 reply: …present and touched: it is told at once, and the reply says so", "told at once that it was closed" in r and len(pushes()[p0:]) == 1, (r, pushes()[p0:]))
_saved2 = (telling.front_keeper, server._anc.pilot_root)
try:
    server._anc.pilot_root = lambda p, *a, **k: "projects/alpha"
    telling.front_keeper = lambda who, project="": (True, U["home-front"])      # the mover is a front agent, its project's keeper is home-front
    for i_, is_present, close_, want, label in ((103, False, False, "was not told (", "held, Oliver away"), (104, True, False, "hears of it on his next turn", "fyi, present and touched"),
                                                (105, True, True, "has been told", "close, present and touched"), (106, False, True, "was not told (", "close held, Oliver away")):
        stamp("home-front", 60) if is_present else unstamp("home-front")
        item(i_, mover="home-beta-front", writer="home-front"); it = server._load(f"a{i_}"); telling.OWNER_HEARD.clear()
        r = telling.tell_owner(f"a{i_}", it, "was completed (done)" if close_ else "changed", "home-send", close=close_); drain()
        check(f"10 reply: a front keeper's line, {label}: the reply says what became of it", want in r and ("has been told" not in r if "not told" in want else True), r)
        held.take(U["home-front"])
finally:
    telling.front_keeper, server._anc.pilot_root = _saved2
# a close that names another item: the mover (a front agent) is listed as told only when the gate let it through
item(19, status="completed", outcome="done"); item(108, mover="home-front", writer="home-front", next="home-front: wait for a19")
unstamp("home-front"); p0 = len(pushes()); got = telling.tell_close_mentions("a19", "done", "", "home-send"); drain()
check("10 reply: tell_close_mentions does not list a front mover the gate held (Oliver away) as told", got == [] and pushes()[p0:] == [], (got, pushes()[p0:]))
stamp("home-front", 60); p0 = len(pushes()); got = telling.tell_close_mentions("a19", "done", "", "home-send"); drain()
check("10 reply: …present and touched: it is listed, and the close was pushed", got == [U["home-front"]] and len(pushes()[p0:]) == 1, (got, pushes()[p0:]))

# (3) the hand-back line to the builder: held path, a close inside the hold drops it, an old record with no writer tells nobody
def hb_item(i, needs):
    item(i, mover="home-front", writer="home-send", needs=needs); return server._load(f"a{i}")
server._cfg.CFG["board"] = {"handback_hold_seconds": 180}
held.mark_client(U["team-back"], "team-back"); cli_row("team-back")
it = hb_item(76, [U["home-front"]]); p0, h0 = len(pushes()), held.count(U["team-back"])
r = telling.tell_handback("a76", it, ["team-back", "home-front"], "home-send"); drain()
rec = telling.handback_read().get(f"a76|{U['home-front']}")
check("10 hand-back: a front mover's hand-back is held for 180 s (nothing sent yet), and the reply says when and that a close first cancels it", rec and 175 <= rec["due"] - time.time() <= 181 and pushes()[p0:] == [] and held.count(U["team-back"]) == h0 and "in 3 minutes unless you close" in r and "a note for its next turn" in r, (r, rec))
n = telling.handback_drop("a76", "closed")
check("10 hand-back: …a close inside the hold drops the line: nothing is left to send, and the tick sends nothing", n == 1 and not telling.handback_read() and telling.handback_tick(time.time() + 400) == [] and pushes()[p0:] == [] and held.count(U["team-back"]) == h0, (n, telling.handback_read()))
it = hb_item(32, [U["home-front"]]); r = telling.tell_handback("a32", it, ["team-back", "home-front"], "home-send"); drain()
sent = telling.handback_tick(time.time() + 400); drain()
check("10 hand-back: …no close: after the hold the tick passes the line to the builder through the held path (a held line for its next turn, no new turn)", sent == ["a32"] and pushes()[p0:] == [] and held.count(U["team-back"]) == h0 + 1 and not telling.handback_read(), (sent, pushes()[p0:], held.count(U["team-back"]), h0))
txt = held.take(U["team-back"])
check("10 hand-back: …the held line says it is back with the front agent, not the builder", "is back with home-front, a front agent, alone" in txt and "told to you, not to home-front" in txt, txt)
telling.handback_write({})
rec_old = {"gid": "a33", "oid": U["home-front"], "olabel": "home-front", "project": "projects/alpha", "who": "team-back", "subject": "[home] item 33", "line": "[stackshot] a33 is back with you alone (handed back by team-back): [home] item 33 → https://x/items/a33"}      # a record held before this release: no wid
item(33, mover="home-front", writer="team-back"); p0, h0 = len(pushes()), held.count(U["team-back"])
ok = telling.handback_send(rec_old); drain()
check("10 hand-back: a held record with no writer on file (from before this release) tells nobody, so the builder is not told about its own write; the routing log says why", ok is False and pushes()[p0:] == [] and held.count(U["team-back"]) == h0 and any("not on record" in str(n.get("reason", "")) for n in routing.read("projects/alpha") if "a33" in str(n.get("label", ""))), (ok, routing.read("projects/alpha")[-2:]))
check("10 hand-back: …the board carries it too (a History line on the item)", quiet_log(33) and "was not told" in quiet_log(33)[-1]["text"], quiet_log(33))
it = hb_item(34, [U["home-front"]]); server._cfg.CFG["board"] = {"handback_hold_seconds": 0}; p0 = len(pushes())
r = telling.tell_handback("a34", it, ["team-back", "home-front"], "team-back"); drain()
check("10 hand-back: the builder wrote it itself: nobody is told and the reply says so (no 'is passed a note')", pushes()[p0:] == [] and "nobody is told" in r and "passed a note" not in r, r)
it = hb_item(77, [U["home-front"]]); h0 = held.count(U["team-back"])
r = telling.tell_handback("a77", it, ["team-back", "home-front"], "home-send"); drain()
check("10 hand-back: with no hold ([board] handback_hold_seconds = 0) the builder's line is held at once for its next turn, and the reply says it is passed a note", held.count(U["team-back"]) == h0 + 1 and "passed a note" in r and "unless you close" not in r, (r, held.count(U["team-back"])))
held.take(U["team-back"]); server._cfg.CFG["board"] = {}

# (4) no start time is no touch
item(35, writer="home-front")
check("10 touched: no start time (0) is not a touch, though the agent wrote the item", telling.touched("a35", "home-front", 0) is False and telling.touched("a35", "home-front", -5.0) is False and telling.touched("a35", "home-front", STARTED) is True)
stamp("home-front", 60); (T / f"cli/{os.getpid()}-home-front.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U["home-front"], "name": "home-front", "status": "idle"}))      # a registry row with no startedAt
v = telling.front_verdict("a35", "home-front", "progress")
check("10 touched: …a pane whose registry row has no startedAt: the verdict is hold (fails closed, like presence), with the reason", v[0] == "hold" and "start time" in v[1], v)
cli_row("home-front")

# (5) [presence] minutes that is no number above 0 is said at load, and still reads as 30
for bad in (0, -5, 0.0, "soon", True, [1]):
    nn = _config.notes({"instance": {"owner": "Oliver"}, "page_gate": {"keeper_currency": "keepers"}, "presence": {"minutes": bad}}); set_presence(minutes=bad)
    check(f"10 presence minutes: {bad!r} is named in config.notes() and still reads as 30", len(nn) == 1 and "[presence] minutes" in nn[0] and "30" in nn[0] and telling.presence_minutes() == 30.0, (nn, telling.presence_minutes()))
for good in (1, 5, 30, 60, 0.5):
    check(f"10 presence minutes: {good!r} says nothing", _config.notes({"instance": {"owner": "Oliver"}, "page_gate": {"keeper_currency": "keepers"}, "presence": {"minutes": good}}) == [], good)
check("10 presence minutes: no [presence] section says nothing", _config.notes({"instance": {"owner": "Oliver"}, "page_gate": {"keeper_currency": "keepers"}}) == [])
set_presence()

# ================================================================ end
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
