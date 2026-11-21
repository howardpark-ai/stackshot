"""Scenario test for the want for a background agent: a message to a project that lists a front agent and no background agent records that the project could use one, and the fleet tool reads the wants
(stackshot/service/background_want.py, GET /client/background-wanted, client.py background-wanted) - fixture pages and sessions in a temporary store, the push replaced by a recorder, no network, no model call.

  1  the switch: [background_agent] enabled is off by default (the example config), and a switch that is off writes no state file and no lock file and answers an empty list
  2  who is eligible: one fixture per reason for none (retired, moved, hidden, no front agent, a one-session project, a sub-page, a page with a hub line, a project with a builder, one with other background agents,
     a front agent that is no session of the fleet) and the kinds (a board or anchor notice never wants one), then the project that does want one; the want is keyed by the project's id and set only when absent
  3  the routes: every ruling path of a message records the want, and the ruling is the same with the want as without it (a plain message, an fyi, a pass that needs the person, an answer to the agent's question, the router's own
     call ruling archived, merged or dropped, a rule in code, and in the message tool every branch of the front gate, its refusals included: yes; a board or anchor notice, the server's own line, the audit's and the filing passes' messages (marked, unmarked, fyi), a front agent's word (a peer's or its own
     project's), the person's own message (by name or to the key), an audit finding, a message the tool refuses for its recipient (a pane gone, an unknown name), a project with a background agent: no;
     a component page with no agents records its hub's want)
  4  races: eight threads and two processes set one project's want once (the lock)
  5  wanted(): a want drops out once the project lists a background agent (and is marked served); after the agent is retired a new message wants again only after the cooldown; a project that turned ineligible is left out
  6  the cap on open wants, the cooldown from the want itself, a setting that is no number
  7  a failing state directory: nothing raises and the message is routed exactly as it was
  8  the endpoint and the client read: the shape of a line, the machine token, an empty answer with the switch off, client.py background-wanted prints the lines and nothing when the server cannot be asked

    tests/run-suite background_want        -> exit 0 / 1"""
import contextlib, io, json, logging, os, pathlib, re, subprocess, sys, textwrap, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="bgwant-"); T = pathlib.Path(tmp)
EXAMPLE = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
example_section = re.search(r"(?ms)^\[background_agent\].*?^(?=\[)", EXAMPLE).group(0)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml, n = re.subn(r'(?m)^session_links = "[^"]*"', 'session_links = ""', toml); assert n == 1      # never the host's fleet store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^ui_open = true', 'ui_open = false'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', 'allowed_emails = ["oliver@example.org"]'), (r'(?m)^require_marks = true', 'require_marks = false'),
                 (r'(?m)^enabled = false(?=\s+# false: no want)', 'enabled = true')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat      # the instance under test has the switch on (a child process reads this file); the example's own default is checked in part 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "secrets", "touch", "brain/projects", "cli"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")

# ---- the pages: one project per reason for a want or none. A name is <project>-<role>.
BUILDS, TIDIES, FRONT = "builds, merges and releases the code", "tidies the notes", "Oliver's point of contact"
def page(front=(), back=None, **kw):
    back = back or {}
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": kw.pop("type", "project"), "session": kw.pop("session", ""), "status": kw.pop("status", "active"), "board": [], "board_row": False,
            "updated": 1, "mirror": "", "agents": {**{f: FRONT for f in front}, **back}, "back_agents": dict(back), **kw}
PAGES = {
    "projects/solo": page(["solo-main"], session="solo"),                          # eligible: a front agent, no background agent
    "projects/other": page(["other-main", "other-desk"], session="other"),         # eligible: two front agents (the -main one is named)
    "projects/third": page(["third-main"], session="third"),                       # eligible: the third at the cap
    "projects/alpha": page(["alpha-main"], {"alpha-builder": BUILDS}, session="alpha"),          # a builder
    "projects/duo": page(["duo-main"], {"duo-a": TIDIES, "duo-b": TIDIES}, session="duo"),       # two background agents, neither builds
    "projects/old": page(["old-main"], status="archived", session="old"),          # retired
    "projects/moved": page(["moved-main"], status="moved", session="moved"),       # moved
    "projects/memo": page(["memo-main"], type="note", session="memo"),             # a note page: never listed
    "projects/backonly": page([], {"backonly-docs": TIDIES}, session="backonly"),  # background agents only: no front agent
    "projects/loner": page([], session="loner"),                                   # a one-session project: a name line and no agents map
    "projects/solo/side": page(["side-main"], session="side"),                     # a sub-page of solo
    "projects/comp": page(["comp-main"], session="comp", hub="projects/alpha"),    # a component page of alpha (a hub line)
    "projects/slackonly": page(["slackonly-bot"], session="slackonly"),            # its one front agent is no session of the fleet (a surface agent)
}
def publish(pages=None, **changes):
    """Write the registry. `changes` = {project: page or None}; the registry is replaced through a temp file, so the reader sees a new file at once."""
    pg = dict(PAGES if pages is None else pages)
    for k, v in changes.items():
        if v is None: pg.pop(k, None)
        else: pg[k] = v
    p = T / "store/projects.json"; tp = T / "store/projects.json.new"
    tp.write_text(json.dumps({"pages": pg})); os.replace(tp, p)
    for key, e in pg.items():
        f = T / f"brain/{key}.md"; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(f"---\ntitle: {key}\n---\n# {key}\n\n## Current state\n\nx\n\n<!-- timeline -->\n")
publish()
RECORD = {"schema": 1, "ids": {}, "pending_agents": {}, "marks": {}}
(T / "store/project-record.json").write_text(json.dumps(RECORD))
NAMES = ("solo-main", "other-main", "other-desk", "third-main", "alpha-main", "alpha-builder", "duo-main", "home-beta", "side-main", "comp-main", "slackonly-bot", "kept-main", "solo")
U = {n: "%08x-0000-4000-8000-%012x" % (i, i) for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
push_log = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
def pushes(): return [json.loads(l) for l in push_log.read_text().splitlines()] if push_log.exists() else []

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.core import config as _cfg
from stackshot.router import routing, router as _router, router_live as _live
from stackshot.waits import held
from stackshot.fleet import client, clients as _clients
from stackshot.web import server, publish as _web_publish, page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route
from stackshot.service import messaging as _messaging, telling, background_want as bw, handoff as handoff_svc
from stackshot.projects import projects as _prj
from fastmcp.exceptions import ToolError
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None; telling.PUSH = [sys.executable, str(T / "fakepush.py")]
_web_page_debts._refuse_if_owing = lambda debtor: None
handoff_svc.CLI_SESSIONS = T / "cli"
_cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
MACH = "home-test"
for n_, u_ in U.items(): _clients.register(MACH, {"uuid": u_, "name": n_}); held.mark_client(u_, n_)      # the rollout gate: every hook has fetched held lines
U["audit"] = "%08x-0000-4000-8000-%012x" % (len(NAMES) + 1, len(NAMES) + 1)      # the configured audit agent's session (its name is the instance's, read from the config)
_rows = json.loads((T / "fleet/a/sessions.json").read_text()); _rows[U["audit"]] = {"name": _cfg.audit_agent(), "machine": "a", "url": "", "seen": "x"}; (T / "fleet/a/sessions.json").write_text(json.dumps(_rows))
SOLO, SOLO_KEY, ALPHA_KEY = "solo-main", "projects/solo", "projects/alpha"
def pane(who):
    (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": "idle", "startedAt": int((time.time() - 7200) * 1000),
                                                                  "statusUpdatedAt": int(time.time() * 1000), "updatedAt": int(time.time() * 1000)}))
for w in ("solo-main", "alpha-main"): pane(w)
def stamp(who, minutes_ago):
    p = T / "state/prompts" / U[who]; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(f"{time.time() - minutes_ago * 60:.0f}\n")
def unstamp(who): (T / "state/prompts" / U[who]).unlink(missing_ok=True)

SETTINGS = {"enabled": True, "max_open": 3, "cooldown_minutes": 60}
STATE, LOCK = T / "state/background-wanted.json", T / "state/background-wanted.lock"
def reset(**kw):
    """The switch on (or as `kw` says), an empty state, the push log and the held store emptied, the registry as the fixture has it."""
    _cfg.CFG["background_agent"] = {**SETTINGS, **kw}
    STATE.unlink(missing_ok=True); LOCK.unlink(missing_ok=True)
    for p in held.dir_().glob("*.jsonl"): p.unlink()
    push_log.unlink(missing_ok=True)
def wants(): return json.loads(STATE.read_text())["wants"] if STATE.exists() else {}
def keys(): return sorted(w["key"] for w in wants().values())
def prj_id(key): return _prj.ref(key)["id"]
def sink(fn):
    with contextlib.redirect_stderr(io.StringIO()):      # the module's own stderr lines
        return fn()

# ---- 1. the switch
check("1a: the example config ships the section with the switch off, and a default for the cap and the cooldown", re.search(r"(?m)^enabled = false", example_section) and re.search(r"(?m)^max_open = 3", example_section)
      and re.search(r"(?m)^cooldown_minutes = 60", example_section), example_section[:300])
_cfg.CFG.pop("background_agent", None)
check("1b: with no section at all the switch is off and the limits are the defaults", bw.enabled() is False and bw.max_open() == 3 and bw.cooldown_seconds() == 3600.0)
reset(enabled=False)
check("1c: a switch that is off records nothing: no want, no state file, no lock file, an empty list", bw.want_background(SOLO_KEY, "message") is False and not STATE.exists() and not LOCK.exists()
      and bw.wanted() == [] and bw.wanted_lines() == "", (STATE.exists(), LOCK.exists()))
for off in ("false", "no", "off", 0, None):
    reset(enabled=off); check(f"1d: enabled = {off!r} is off", bw.enabled() is False)
for on in ("true", "yes", "on", 1, True):
    reset(enabled=on); check(f"1e: enabled = {on!r} is on", bw.enabled() is True)

# ---- 2. who is eligible
reset()
NOT = {"projects/old": "a retired project", "projects/moved": "a moved project", "projects/memo": "a hidden project (a note page is never listed)", "projects/backonly": "a project with no front agent",
       "projects/loner": "a one-session project", "projects/solo/side": "a sub-page", "projects/comp": "a page with a hub line", ALPHA_KEY: "a project with a builder",
       "projects/duo": "a project with background agents that build nothing", "projects/slackonly": "a project whose one front agent is no session of the fleet",
       "projects/nowhere": "a key no page has", "": "an empty key"}
_surface = page(["slackonly-bot"], session="slackonly"); _surface["surface_agents"] = {"slackonly-bot": "slack"}
publish(**{"projects/slackonly": _surface})
for k, why in NOT.items():
    check(f"2a: no want for {why}", bw.want_background(k, "message") is False and wants() == {}, (k, wants()))
for kind in ("board", "anchor", "", "Message", "fyi"):
    check(f"2b: no want for a notice of kind {kind!r} to an eligible project", bw.want_background(SOLO_KEY, kind) is False and wants() == {}, kind)
t0 = 1_000_000.0
check("2c: a message to a project with a front agent and no background agent records one want", bw.want_background(SOLO_KEY, "message", now=t0) is True and keys() == [SOLO_KEY], wants())
w = wants()
check("2d: it is keyed by the project's permanent id and carries the key and the time", list(w) == [prj_id(SOLO_KEY)] and w[prj_id(SOLO_KEY)] == {"key": SOLO_KEY, "at": t0} and json.loads(STATE.read_text())["schema"] == 1, w)
check("2e: set only when absent: the same project again (or its key spelled with a slash) changes nothing", bw.want_background(SOLO_KEY, "message", now=t0 + 5) is False and bw.want_background(SOLO_KEY + "/", "message", now=t0 + 6) is False
      and wants() == w, wants())
check("2f: another eligible project is a second want (the project with two front agents too)", bw.want_background("projects/other", "message", now=t0 + 7) is True and keys() == ["projects/other", SOLO_KEY], keys())
check("2g: the lock file sits beside the state file and the state is one JSON document", LOCK.exists() and STATE.read_text().endswith("}\n"))
rows = bw.wanted(now=t0 + 8)
check("2h: wanted() lists each project once, oldest want first, with its name prefix and its front agent (the -main one)", rows == [{"key": SOLO_KEY, "prefix": "solo", "front": "solo-main"}, {"key": "projects/other", "prefix": "other", "front": "other-main"}], rows)
check("2i: wanted_lines() is one line per project: key, prefix, front agent", bw.wanted_lines() == f"{SOLO_KEY} solo solo-main\nprojects/other other other-main\n", bw.wanted_lines())

# ---- 3. the routes
cx = _router.Context()
def recp(text, key=SOLO_KEY, kind="message", who="home-beta (00000008…)", hold="", **kw):
    nid = routing.record(key, kind=kind, to="", label="message to " + key, who=who, text=text, target="project-wide", pilot=True, live=True, hold=hold, **kw)
    _live.stash(nid, text)
    return next(n for n in routing.read(key) if n["id"] == nid)
def act(n, target, key=SOLO_KEY, **ln):
    line = {"id": n["id"], "ruling": "passed", "target": target, "reason": "it fits", "source": "code", "rule": "test", "item": "", **ln}
    return _live._act(n, key, key, line, _router.Context(), {})
def shape(res): return {k: res.get(k) for k in ("status", "ruling", "target", "marked", "reason", "hold", "held_for")}
def msg(*a, **k):
    try: return _messaging._message(*a, **k)
    except ToolError as e: return str(e)
    except Exception as e: return f"RAISED {e!r}"      # a check then fails, the suite goes on
def who_of(name): return f"{name} ({U[name][:8]}…)"
def routed(label, key, text, target, want, expect_ruling, ln=None, **rec_kw):
    """One notice through the router's own pass, with the switch on: its ruling, and whether it recorded a want for `key`; the same notice with the switch off must be ruled the same.
    `expect_ruling` None = the ruling is not what the check is about (only that it is the same with the switch off)."""
    reset(); n = recp(text, key=key, **rec_kw); res = act(n, target, key=key, **(ln or {}))
    got = (key in keys(), res["ruling"]); on = shape(res)
    reset(enabled=False); n2 = recp(text, key=key, **rec_kw); off = shape(act(n2, target, key=key, **(ln or {})))
    ok = got[0] == want and (expect_ruling is None or got[1] == expect_ruling)
    check(f"3: {label}: {'a want is recorded' if want else 'no want'}, ruled {expect_ruling or 'as it is'}, and the ruling is the one the switch off gives", ok and on == off and not STATE.exists(), (got, on, off))
    return res
publish()
routed("a plain message to a project with a front agent and no background agent (the pass is archived)", SOLO_KEY, "the export page reads fine", SOLO, True, "archived")
routed("an fyi to it (filed for the front agent's next turn)", SOLO_KEY, "the export page reads fine", SOLO, True, "held", hold="fyi")
routed("an fyi from a peer front agent (the channel between them)", SOLO_KEY, "the export page reads fine", SOLO, False, "held", hold="fyi", who=who_of("other-main"))
routed("a board notice (kind board) to it", SOLO_KEY, "the export page reads fine", SOLO, False, "archived", kind="board")
routed("an anchor notice to it", SOLO_KEY, "the export page reads fine", SOLO, False, "archived", kind="anchor")
routed("the server's own line about an item (a message whose text opens [board])", SOLO_KEY, "[board] item nine: someone changed next", SOLO, False, "archived", who="stackshot")
routed("a peer front agent's word (held for the front agent, the channel between them)", SOLO_KEY, "the export page reads fine", SOLO, False, "held", who=who_of("other-main"))
routed("a pass that needs the person (his mark in the text; the front gate archives it, he is not with the agent)", SOLO_KEY, "the export page reads fine - it now needs: decision", SOLO, True, "archived")
routed("an audit finding (rule audit-owners)", SOLO_KEY, "the export page reads fine", SOLO, False, None, ln={"rule": "audit-owners"})
routed("a plain message to a project WITH a builder (it goes to the builder)", ALPHA_KEY, "the export page reads fine", "alpha-main", False, "passed")
routed("an fyi to a project with a builder (filed for the front agent)", ALPHA_KEY, "the export page reads fine", "alpha-main", False, "held", hold="fyi")
routed("a plain message to a project whose background agents build nothing (the first of them takes it)", "projects/duo", "the export page reads fine", "duo-main", False, "passed")
# an answer to the front agent's own question: delivered while he is in that conversation (no want), held otherwise (no want)
def log_row(frm, to, ago_min):
    _messaging.MSG_LOG.parent.mkdir(parents=True, exist_ok=True)
    import datetime
    t = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=ago_min)).isoformat(timespec="seconds")
    with open(_messaging.MSG_LOG, "a", encoding="utf-8") as f: f.write(json.dumps({"t": t, "from": frm, "auth": "", "to": to, "outcome": "delivered", "error": "", "text": "is it ready?"}) + "\n")
_messaging.MSG_LOG.unlink(missing_ok=True); log_row(SOLO, "home-beta", 5); stamp(SOLO, 5)
routed("an answer to the front agent's own question while he is in that conversation (delivered)", SOLO_KEY, "yes, the export is ready", SOLO, True, "passed")
unstamp(SOLO)
routed("…and the same answer while he is not (held for the agent's next turn)", SOLO_KEY, "yes, the export is ready", SOLO, True, "held")
_messaging.MSG_LOG.unlink(missing_ok=True)
# a ruling that is no pass never reaches the front agent's route: the router's own call (a model ruling) and a rule in code settle a message before it, and the want is recorded all the same
CALL, TXT = {"ruling": "archived", "source": "call", "rule": ""}, "a staged test of the start-an-agent path; nothing to do"
routed("the router's own call rules the message archived (a model ruling: no pass, no front route)", SOLO_KEY, TXT, "", True, "archived", ln=CALL)
routed("the router's own call rules an fyi archived", SOLO_KEY, TXT, "", True, "archived", ln=CALL, hold="fyi")
routed("the router's own call rules it merged (into an earlier notice)", SOLO_KEY, TXT, "", True, "merged", ln={**CALL, "ruling": "merged"})
routed("the router's own call rules it dropped", SOLO_KEY, TXT, "", True, "dropped", ln={**CALL, "ruling": "dropped"})
routed("a rule in code rules it archived (a page pass, an image: source code, no pass)", SOLO_KEY, TXT, "", True, "archived", ln={"ruling": "archived", "source": "code", "rule": "page-pass"})
routed("a rule in code rules it merged (the writer's own relay)", SOLO_KEY, TXT, "", True, "merged", ln={"ruling": "merged", "source": "code", "rule": "message-item"})
routed("a message to a project WITH a builder that the call rules archived records none (the project has a background agent)", ALPHA_KEY, TXT, "", False, "archived", ln=CALL)
routed("a board notice the call rules archived records none", SOLO_KEY, TXT, "", False, "archived", ln=CALL, kind="board")
routed("an anchor notice the call rules archived records none", SOLO_KEY, TXT, "", False, "archived", ln=CALL, kind="anchor")
routed("the server's own line about an item, ruled archived by the call, records none", SOLO_KEY, "[board] item nine: someone changed next", "", False, "archived", ln=CALL, who="stackshot")
routed("a peer front agent's word ruled archived by the call records none (the channel between front agents)", SOLO_KEY, TXT, "", False, "archived", ln=CALL, who=who_of("other-main"))
routed("an audit finding ruled archived records none", SOLO_KEY, TXT, "", False, "archived", ln={**CALL, "rule": "audit-owners"})
routed("a script's message ruled archived by the call records a want (a script is no peer front agent)", SOLO_KEY, TXT, "", True, "archived", ln=CALL, who="nightly-check (a script on box-a)")
routed("a message with his mark in the text, ruled archived by the call", SOLO_KEY, "the export page reads fine - needs: decision", "", True, "archived", ln=CALL)
# who writes: a front agent to its own project's key is no call for a background agent (the project's own front agent, with a target of the ruling or none: the target is no part of the test), nor is the person or the audit
routed("the project's own front agent writes to its own key (ruled archived by the call, no target): the agent is no call for another agent", SOLO_KEY, TXT, "", False, "archived", ln=CALL, who=who_of(SOLO))
routed("…the same with the ruling's target naming it", SOLO_KEY, TXT, SOLO, False, "archived", ln=CALL, who=who_of(SOLO))
routed("…and a pass (a rule in code) from the project's own front agent", SOLO_KEY, TXT, SOLO, False, None, ln={"ruling": "passed", "source": "code", "rule": "test"}, who=who_of(SOLO))
routed("a front agent of another project writes to the key (ruled archived by the call, no target): the channel between front agents", SOLO_KEY, TXT, "", False, "archived", ln=CALL, who=who_of("alpha-main"))
routed("the person's own message to the key, ruled archived by the call, records none (as by name)", SOLO_KEY, TXT, "", False, "archived", ln=CALL, who=_messaging.OWNER)
routed("…and ruled dropped", SOLO_KEY, TXT, "", False, "dropped", ln={**CALL, "ruling": "dropped"}, who=_messaging.OWNER)
routed("the audit's own line (the label its cue is pushed as, a script) ruled archived records none", SOLO_KEY, TXT, "", False, "archived", ln=CALL, who="stackshot audit (a script on box-a)")
routed("…and under the audit agent's name", SOLO_KEY, TXT, "", False, "archived", ln=CALL, who=_cfg.audit_agent())
routed("a session that is no front agent (a home session) ruled archived with no target still records one", SOLO_KEY, TXT, "", True, "archived", ln=CALL, who=who_of("home-beta"))
# a component page with no agents of its own, part of a front-only hub: the want is the hub's (the agents that serve the page), never the component's own, which is no eligible project
COMP_KEY = "projects/solo-parts"
reset(); publish(**{COMP_KEY: page([], session="soloparts", hub=SOLO_KEY)}); n = recp(TXT, key=COMP_KEY); res = act(n, "", key=COMP_KEY, **CALL)
check("3k: a message to an agentless component page of a front-only hub records the hub's want", res["ruling"] == "archived" and keys() == [SOLO_KEY], (res["ruling"], keys()))
reset(); n = recp(TXT, key=COMP_KEY, who=who_of(SOLO)); res = act(n, "", key=COMP_KEY, **CALL)
check("3k2: …and the hub's own front agent writing to the component page is no call", res["ruling"] == "archived" and keys() == [], (res["ruling"], keys()))
publish()
# the router with no hook wired (a CLI run, a test): nothing is recorded and nothing raises
reset(); hook = _live._HOOKS["want_background"]; _live._HOOKS["want_background"] = None
n = recp("the export page reads fine"); res = act(n, SOLO); _live._HOOKS["want_background"] = hook
check("3b: the router with no hook wired rules the same and records nothing", res["ruling"] == "archived" and not STATE.exists(), (res["ruling"], STATE.exists()))
def boom(project, kind): raise RuntimeError("the record is gone")
_live._HOOKS["want_background"] = boom; reset(); n = recp("the export page reads fine"); res = act(n, SOLO); _live._HOOKS["want_background"] = hook
check("3c: a hook that raises leaves the ruling as it was", res["status"] == "ruled" and res["ruling"] == "archived", res)
# the message tool
reset(); r_ = msg(SOLO, "can you look at the export page when you have a minute?", "home-beta"); n_on = keys()
reset(enabled=False); r_off = msg(SOLO, "can you look at the export page when you have a minute?", "home-beta")
check("3d: the message tool's front gate holds a message to a front agent of a project with no background agent, records the want, and the reply is the one the switch off gives",
      r_.startswith("held for solo-main's next turn") and n_on == [SOLO_KEY] and r_ == r_off and not STATE.exists(), (r_, n_on, r_off))
reset(); r_ = msg(SOLO, "can you look at the export page when you have a minute?", "alpha-main")
check("3e: a peer front agent's message to it is held and records none", r_.startswith("held for solo-main's next turn") and keys() == [], (r_, keys()))
reset(); r_ = msg("alpha-main", "can you look at the export page when you have a minute?", "home-beta")
check("3f: a message to a front agent of a project WITH a builder is refused (naming the builder) and records none", r_.startswith("Refused") and "alpha-builder" in r_ and keys() == [], (r_, keys()))
reset(); r_ = msg(SOLO, "the export page reads fine", "home-beta", fyi=True); n_on = keys()
reset(enabled=False); r_off = msg(SOLO, "the export page reads fine", "home-beta", fyi=True)
check("3g: an fyi by name to a front agent of a project with no background agent is filed for its next turn, records the want, and the reply is the one the switch off gives",
      r_.startswith("held for solo-main's next turn (fyi") and n_on == [SOLO_KEY] and r_ == r_off and not STATE.exists(), (r_, n_on, r_off))
reset(); r_ = msg("alpha-main", "the export page reads fine", "home-beta", fyi=True)
check("3h: …and an fyi by name to the front agent of a project WITH a builder records none", r_.startswith("held for alpha-main's next turn") and keys() == [], (r_, keys()))
reset(); r_ = msg(SOLO, "the export page reads fine", "other-main", fyi=True)
check("3i: an fyi from a peer front agent is the channel between them: filed, and records none", r_.startswith("held for solo-main's next turn") and keys() == [], (r_, keys()))
# every branch of the front gate records the want: its refusals and its other holds were skipped once, as the router's non-pass rulings were
def by_name(label, text, want, sender="home-beta", starts=None, **kw):
    reset(); r_on = msg(SOLO, text, sender, **kw); n_on = keys()
    reset(enabled=False); r_off = msg(SOLO, text, sender, **kw)
    check(f"3j: the message tool, {label}: {'a want is recorded' if want else 'no want'}, and the reply is the one the switch off gives",
          n_on == ([SOLO_KEY] if want else []) and r_on == r_off and (starts is None or r_on.startswith(starts)) and not STATE.exists(), (r_on, n_on, r_off))
by_name("a marked message the person is not with the agent for (refused, nothing held)", f"{_messaging._FOR_OWNER}\nplease look at the export page", True, starts="Refused")
by_name("a marked message that says nothing is needed from him (refused as a note)", f"{_messaging._FOR_OWNER}\nthe export page is fine, no action needed", True, starts="Refused")
by_name("a done or no-action note with no mark (refused: write it on the item)", "the export page is fine, no action needed", True, starts="Refused")
by_name("a message with needs: decision away from the first line (refused: the mark goes on the first line)", "the export page reads fine\nit now needs: decision", True, starts="Refused")
by_name("the person's own message (refused: no mark; he is no session)", "the export page reads fine", False, sender=_messaging.OWNER, starts="Refused")
_messaging.MSG_LOG.unlink(missing_ok=True); log_row(SOLO, "home-beta", 5)
by_name("an answer to a question the front agent itself put to the sender", "yes, the export is ready", True)
_messaging.MSG_LOG.unlink(missing_ok=True)
by_name("a script's message (origin set, no session sender)", "the export page reads fine", True, origin="box-a")
# the server's own sends (the audit's findings and the filing and date passes: `auth` "server", a script on this box) are no call for an agent, marked, unmarked or fyi
SRV = dict(sender="stackshot audit", auth="server", origin="box-a")
by_name("the server's own message, unmarked (the filing pass's line)", "the export page reads fine", False, **SRV)
by_name("the server's own message, marked for the person", f"{_messaging._FOR_OWNER}\nthe export page needs a date", False, **SRV)
by_name("the server's own fyi", "the export page reads fine", False, fyi=True, **SRV)
by_name("a server send under any other label (the auth is what marks it)", "the export page reads fine", False, sender="a-server-pass", auth="server", origin="box-a")
by_name("a script that is no server send (the same script, no server auth) still records a want", "the export page reads fine", True, sender="nightly-check", origin="box-a")
# the audit's own run sends by name as a script on some machine (`client.message`: auth "machine:<m>", origin <m>, the label "stackshot audit"): the label counts as written, though a script's sender is blanked for the role tests
AUD = dict(sender=_cfg.AUDIT_SENDER, auth="machine:box-a", origin="box-a")
by_name("the audit's own run by name (a script on a machine, label stackshot audit), unmarked", "the export page reads fine", False, **AUD)
by_name("…the same, an fyi (a held note)", "the export page reads fine", False, fyi=True, **AUD)
by_name("…the same, marked for the person (a finding)", f"{_messaging._FOR_OWNER}\nthe export page needs a date", False, **AUD)
by_name("the configured audit agent's own session writing by name", "the export page reads fine", False, sender=_cfg.audit_agent())
by_name("…the same with a uuid suffix on its label", "the export page reads fine", False, sender=f"{_cfg.audit_agent()} ({U['home-beta'][:8]}…)")
by_name("…and a script that is no audit (another label, the same machine auth) still records a want", "the export page reads fine", True, sender="nightly-check", auth="machine:box-a", origin="box-a")
check("3n: the label the audit sends as is the one the router and the message tool test (audit_run.SENDER is the configured constant)", __import__("stackshot.audit.audit_run", fromlist=["SENDER"]).SENDER == _cfg.AUDIT_SENDER == "stackshot audit"
      and _cfg.is_audit_sender("stackshot audit (a script on box-a)") and _cfg.is_audit_sender(_cfg.audit_agent().upper()) and not _cfg.is_audit_sender("") and not _cfg.is_audit_sender("nightly-check"))
# the audit agent's own session sends with its SESSION ID as the sender (the documented form for the message tool): the id is resolved to the session's name, as the router resolves a notice's, and the audit's exclusion holds
AUDIT_ID, BETA_ID = U["audit"], U["home-beta"]
check("3q0: the fixture's audit agent is a session of the fleet under the configured audit agent's name (the session id below is its)", _messaging._sr._sessions_index().get(AUDIT_ID, {}).get("name") == _cfg.audit_agent() != "", _messaging._sr._sessions_index().get(AUDIT_ID))
by_name("the audit agent's own session by its SESSION ID, unmarked", "the export page reads fine", False, sender=AUDIT_ID)
by_name("…the same, an fyi", "the export page reads fine", False, fyi=True, sender=AUDIT_ID)
by_name("…the same, marked for the person (refused as it always was)", f"{_messaging._FOR_OWNER}\nthe export page needs a date", False, sender=AUDIT_ID, starts="Refused")
by_name("the session id of a session that is no audit (a home session), unmarked, still records a want", "the export page reads fine", True, sender=BETA_ID)
by_name("…the same, an fyi", "the export page reads fine", True, fyi=True, sender=BETA_ID)
routed("the audit agent's session by bare id on the router path (a notice's who is an id)", SOLO_KEY, TXT, "", False, "archived", ln=CALL, who=AUDIT_ID)
routed("…and a bare id of a session that is no audit still records the want", SOLO_KEY, TXT, "", True, "archived", ln=CALL, who=BETA_ID)
# a label with a bracketed tag (`name [abc]`) is its name, as one with a parenthesis is
by_name("the audit agent's label with a bracketed tag", "the export page reads fine", False, sender=f"{_cfg.audit_agent()} [abc]")
by_name("the audit's own label with a bracketed tag", "the export page reads fine", False, sender=f"{_cfg.AUDIT_SENDER} [abc]")
routed("the audit agent's label with a bracketed tag on the router path", SOLO_KEY, TXT, "", False, "archived", ln=CALL, who=f"{_cfg.audit_agent()} [abc]")
routed("the audit's own label with a bracketed tag on the router path", SOLO_KEY, TXT, "", False, "archived", ln=CALL, who=f"{_cfg.AUDIT_SENDER} [abc]")
check("3r: the helper strips a parenthesis, a bracketed tag and both, and only then compares the name", all(_cfg.is_audit_sender(x) for x in (f"{_cfg.audit_agent()} [abc]", f"{_cfg.AUDIT_SENDER} (a script on box-a)",
      f"{_cfg.audit_agent()} (00000001…) [abc]", f"{_cfg.AUDIT_SENDER}[abc]")) and not _cfg.is_audit_sender("[abc]") and not _cfg.is_audit_sender(f"x {_cfg.audit_agent()} [abc]"))
# the label is the audit's only when it IS the name: a label that merely contains it is a session of its own, and records the want
for lab in ("stackshot audit bot", "my-stackshot audit", f"{_cfg.audit_agent()}-2", f"x{_cfg.audit_agent()}"):
    by_name(f"a sender whose label only contains the audit's ({lab!r}) still records a want", "the export page reads fine", True, sender=lab)
    routed(f"a notice whose who only contains the audit's ({lab!r}) still records a want", SOLO_KEY, TXT, "", True, "archived", ln=CALL, who=lab)
check("3s: the helper compares the whole name: nothing that merely contains the audit's name or label is the audit", not any(_cfg.is_audit_sender(x) for x in ("stackshot audit bot", "my-stackshot audit", f"{_cfg.audit_agent()}-2", f"x{_cfg.audit_agent()}", "audit")))
# a script's label is blanked for the role tests (it is no session): a script that is labeled with a front agent's name, or the person's, is no peer and no person, so its message records the want
by_name("a script labeled with a front agent's name (the label is blanked: no peer front agent)", "the export page reads fine", True, sender="other-main", origin="box-a")
by_name("a script labeled with the person's name (the label is blanked: no person)", "the export page reads fine", True, sender=_messaging.OWNER, origin="box-a")
# a recipient that is no front agent records none: the name-line session of a front-only project (a retired one, its pane running) is addressable but is no front agent
pane("solo")
reset(); r_nl = msg("solo", "the export page reads fine", "home-beta"); k_nl = keys(); reset(enabled=False); r_nl_off = msg("solo", "the export page reads fine", "home-beta")
check("3t: a message to the name-line session of a front-only project (no front agent) records none, and the reply is the one the switch off gives", k_nl == [] and r_nl == r_nl_off and not str(r_nl).startswith("RAISED"), (k_nl, r_nl, r_nl_off))
# the router path, wired as production wires its hooks: the project's own keeper writing to its own key, the audit's label, and the switch asked first
prod_is_front = lambda who, project: telling.front_keeper(who, project)[0]; was_front = _live._HOOKS["is_front"]
KEPT_KEY = "projects/kept"      # a page whose name line is its front agent: that agent is the page's keeper, for whom production's is_front answers False
reset(); publish(**{KEPT_KEY: page(["kept-main"], session="kept-main")})
check("3o0: production's is_front answers False for a project's own keeper (the case _front_anywhere's second test is for)",
      prod_is_front("kept-main", KEPT_KEY) is False, prod_is_front("kept-main", KEPT_KEY))
_live._HOOKS["is_front"] = prod_is_front
try:
    reset(); n = recp(TXT, key=KEPT_KEY, who=who_of("kept-main")); res = act(n, "", key=KEPT_KEY, **CALL)
    check("3o: production's is_front hook wired: the project's own keeper writing to its own key (ruled archived, no target) records none", res["ruling"] == "archived" and keys() == [], (res["ruling"], keys()))
    reset(); n = recp(TXT, key=KEPT_KEY, who=who_of("home-beta")); res = act(n, "", key=KEPT_KEY, **CALL)
    check("3o2: …and a session that is no front agent still records the project's want", res["ruling"] == "archived" and keys() == [KEPT_KEY], (res["ruling"], keys()))
    routed("…and a front agent of another project writing to solo's key", SOLO_KEY, TXT, "", False, "archived", ln=CALL, who=who_of("alpha-main"))
finally:
    _live._HOOKS["is_front"] = was_front
    publish()
# the switch is asked first: off (the default) does no role lookup, in the router or the message tool
class Lookups:
    """Counts the role lookups (session_roles, the person's-name tests) while the want functions run."""
    def __enter__(self):
        self.n = 0; self.saved = (_anc_mod.session_roles, _router._is_owner_name, _messaging._model.is_owner)
        def counted(fn):
            def w(*a, **k): self.n += 1; return fn(*a, **k)
            return w
        _anc_mod.session_roles = counted(self.saved[0]); _router._is_owner_name = counted(self.saved[1]); _messaging._model.is_owner = counted(self.saved[2]); return self
    def __exit__(self, *e): _anc_mod.session_roles, _router._is_owner_name, _messaging._model.is_owner = self.saved
from stackshot.anchors import anchors as _anc_mod
def lookups(enabled):
    reset(enabled=enabled); n = recp(TXT, who=who_of("home-beta"))
    with Lookups() as c: _live._want_background(n, SOLO_KEY, CALL, cx); r = c.n
    with Lookups() as c: _messaging._want_for_front(SOLO, {}, "home-beta", "", False); m = c.n
    return r, m
off_r, off_m = lookups(False); off_state = STATE.exists(); on_r, on_m = lookups(True)
check("3p: with the switch off the router's want makes no role lookup and the message tool's makes none", (off_r, off_m) == (0, 0) and not off_state, (off_r, off_m, off_state))
check("3p2: …and with it on both look (the control: the counted lookups are the ones on the way)", on_r > 0 and on_m > 0 and keys() == [SOLO_KEY], (on_r, on_m, keys()))
# a message the tool refuses because its recipient cannot receive it records none: a pane gone for hours on a machine that is online
FJ = T / "fleet/a/sessions.json"; FJ0 = FJ.read_text(); MJ = T / "fleet/a/machine.json"; MJ0 = MJ.read_text()
import datetime
_gone = datetime.datetime.fromtimestamp(time.time() - 7200, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
try:
    rows_ = json.loads(FJ0); rows_[U[SOLO]] = {**rows_[U[SOLO]], "gone": _gone}
    FJ.write_text(json.dumps(rows_)); MJ.write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": datetime.datetime.fromtimestamp(time.time() - 48, datetime.timezone.utc).isoformat().replace("+00:00", "Z")}}))
    reset(); r_dead = msg(SOLO, "the export page reads fine", "home-beta"); k_dead = keys()
    reset(); r_dead_fyi = msg(SOLO, "the export page reads fine", "home-beta", fyi=True); k_dead_fyi = keys()
    reset(); r_dead_marked = msg(SOLO, f"{_messaging._FOR_OWNER}\nplease look at the export page", "home-beta"); k_dead_marked = keys()
finally:
    FJ.write_text(FJ0); MJ.write_text(MJ0)
check("3l: a message to a front agent whose pane is long gone is refused as the tool always refused it, and records none", r_dead.startswith("Refused: 'solo-main' cannot receive this") and k_dead == [], (r_dead, k_dead))
check("3l2: …an fyi to it too", r_dead_fyi.startswith("Refused: 'solo-main' cannot receive this") and k_dead_fyi == [], (r_dead_fyi, k_dead_fyi))
check("3l3: …and a marked one (the front gate refuses it first, as it always did; the dead recipient is no call either)", r_dead_marked.startswith("Refused") and k_dead_marked == [], (r_dead_marked, k_dead_marked))
by_name("the same agent once its pane is back (the rows restored): a want again", "the export page reads fine", True)
reset(); r_ = msg("solo-ghost", "the export page reads fine", "home-beta")
check("3m: a name no session carries is refused and records none", r_.startswith("Refused") and keys() == [], (r_, keys()))
# a front agent of the page whose row the heartbeat has forgotten: refused ("no session"), and it records none
try:
    rows_ = json.loads(FJ0); rows_.pop(U[SOLO]); FJ.write_text(json.dumps(rows_))
    reset(); err_gone = io.StringIO()
    with contextlib.redirect_stderr(err_gone): r_gone = msg(SOLO, "the export page reads fine", "home-beta")
    k_gone = keys()
finally:
    FJ.write_text(FJ0)
check("3m2: a message to a front agent the page and sala list but the heartbeat has forgotten is refused (no session), records none, and the want fails nothing on the way (its failures are logged)",
      r_gone.startswith("Refused: no session 'solo-main'") and k_gone == [] and "want for a background agent failed" not in err_gone.getvalue(), (r_gone, k_gone, err_gone.getvalue()[:300]))

# a name two rows carry (the pane came back under a new id): its newest row is gone and the other runs, so the message is sent, and so the want is recorded (the dead-recipient test reads every row of the name)
try:
    rows_ = json.loads(FJ0); rows_[U[SOLO]] = {**rows_[U[SOLO]], "gone": _gone, "seen": "z"}; rows_["ffffffff-0000-4000-8000-0000000000ff"] = {"name": SOLO, "machine": "a", "url": "", "seen": "a"}
    FJ.write_text(json.dumps(rows_)); MJ.write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": datetime.datetime.fromtimestamp(time.time() - 48, datetime.timezone.utc).isoformat().replace("+00:00", "Z")}}))
    reset(); r_two = msg(SOLO, "the export page reads fine", "home-beta"); k_two = keys()
    reset(enabled=False); r_two_off = msg(SOLO, "the export page reads fine", "home-beta")
    rows_.pop("ffffffff-0000-4000-8000-0000000000ff"); FJ.write_text(json.dumps(rows_))
    reset(); r_two_dead = msg(SOLO, "the export page reads fine", "home-beta"); k_two_dead = keys()
finally:
    FJ.write_text(FJ0); MJ.write_text(MJ0)
check("3u: a name whose newest row is gone but another row runs is sent to, so it records the want, and the reply is the one the switch off gives", k_two == [SOLO_KEY] and r_two == r_two_off and r_two.startswith("held for solo-main"), (k_two, r_two, r_two_off))
check("3u2: …and the same name with only its gone row is refused and records none", r_two_dead.startswith("Refused: 'solo-main' cannot receive this") and k_two_dead == [], (r_two_dead, k_two_dead))
# the want itself fails inside the message tool (the recorder, the roles, a closed stderr): the message is sent as it was, and the failure is named on stderr
def _send_with(break_it, what="the export page reads fine"):
    reset(); err = io.StringIO(); saved = (bw.want_background, _anc_mod.session_roles)
    try:
        break_it()
        with contextlib.redirect_stderr(err): r = msg(SOLO, what, "home-beta")
    finally:
        bw.want_background, _anc_mod.session_roles = saved
    return r, err.getvalue()
reset(); r_ok = msg(SOLO, "the export page reads fine", "home-beta")
def _no_record(project, kind, now=None): raise RuntimeError("the record is gone")
r_f, e_f = _send_with(lambda: setattr(bw, "want_background", _no_record))
check("3v: a want that raises inside the message tool leaves the reply as it was and names the failure on stderr", r_f == r_ok and "want for a background agent failed" in e_f and "RuntimeError" in e_f and "the record is gone" in e_f, (r_f, e_f[:300]))
_real_roles = _anc_mod.session_roles; _roles_calls = []
def _no_roles(*a, **k):      # fails once, in the want (the first call of the send): the gate that follows reads the roles as it always did
    _roles_calls.append(1)
    if len(_roles_calls) == 1: raise RuntimeError("the roles are unreadable")
    return _real_roles(*a, **k)
r_f2, e_f2 = _send_with(lambda: setattr(_anc_mod, "session_roles", _no_roles))
check("3v2: …a failure on the way to the call (the roles cannot be read) is the same: the send takes the route it takes, no raise", not r_f2.startswith("RAISED") and "want for a background agent failed" in e_f2 and "roles are unreadable" in e_f2, (r_f2, e_f2[:300]))
class _BrokenStderr:
    def write(self, *a): raise BrokenPipeError("stderr is gone")
    def flush(self): raise BrokenPipeError("stderr is gone")
    def isatty(self): return False
reset(); saved_ = bw.want_background; bw.want_background = _no_record
try:
    with contextlib.redirect_stderr(_BrokenStderr()): r_f3 = msg(SOLO, "the export page reads fine", "home-beta")
finally:
    bw.want_background = saved_
check("3v3: …and with stderr itself broken the log line is lost and the message still goes (the failure handler raises nothing)", r_f3 == r_ok, (r_f3, r_ok))

# ---- 4. races: the lock
reset(); real_read = bw._read
def slow_read():
    d = real_read(); time.sleep(0.15); return d      # the window between a read and a write, wide enough that an unlocked pair would both see an empty state
bw._read = slow_read
bar = threading.Barrier(8); got = []
def worker():
    bar.wait(); got.append(bw.want_background(SOLO_KEY, "message", now=t0))
ths = [threading.Thread(target=worker) for _ in range(8)]
for t in ths: t.start()
for t in ths: t.join(60)
bw._read = real_read
check("4a: eight threads asking at once record one want and exactly one of them is told so", got.count(True) == 1 and len(got) == 8 and keys() == [SOLO_KEY], (got, wants()))
reset()
child = T / "child.py"
child.write_text(textwrap.dedent(f"""
    import glob, os, sys, time
    sys.path.insert(0, {STACK!r})
    from stackshot.service import background_want as bw
    real = bw._read
    def slow():
        # after its read, a process waits (at most 6 s) until both have read: without the lock both see no want; with it the second reads only after the first wrote
        d = real(); open(f"{{sys.argv[3]}}.{{os.getpid()}}", "w").close()
        end = time.time() + 6
        while len(glob.glob(sys.argv[3] + ".*")) < 2 and time.time() < end: time.sleep(0.02)
        return d
    bw._read = slow
    open(sys.argv[1], "w").close()
    while not os.path.exists(sys.argv[2]): time.sleep(0.01)
    print(bw.want_background({SOLO_KEY!r}, "message", now=5.0), flush=True)
"""))
go = T / "go"; go.unlink(missing_ok=True)
procs = [subprocess.Popen([sys.executable, str(child), str(T / f"ready{i}"), str(go), str(T / "readmark")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(2)]
try:
    end = time.time() + 60
    while time.time() < end and not all((T / f"ready{i}").exists() for i in range(2)): time.sleep(0.02)
    go.write_text("go"); outs = [p.communicate(timeout=60) for p in procs]
finally:
    for p in procs:
        if p.poll() is None: p.kill()
said = sorted(o[0].strip() for o in outs)
check("4b: two processes asking at once record one want and exactly one of them is told so", said == ["False", "True"] and keys() == [SOLO_KEY], (said, [o[1][-300:] for o in outs], wants()))

# ---- 5. wanted(): self-healing and the cooldown
reset(); publish()
bw.want_background(SOLO_KEY, "message", now=t0)
check("5a: the want is listed while the project has no background agent", [r["key"] for r in bw.wanted(now=t0 + 10)] == [SOLO_KEY])
publish(**{SOLO_KEY: page(["solo-main"], {"solo-docs": TIDIES}, session="solo")})
check("5b: an agent got listed: the project drops from the list at once", bw.wanted(now=t0 + 100) == [] and bw.wanted_lines() == "")
sv = wants()[prj_id(SOLO_KEY)]
check("5c: …and the want is marked served, from that time (the cooldown starts there)", sv["served"] == t0 + 100 and sv["at"] == t0, sv)
check("5d: a message to a project that has an agent records nothing", bw.want_background(SOLO_KEY, "message", now=t0 + 200) is False and wants()[prj_id(SOLO_KEY)] == sv)
publish()
check("5e: the agent is retired: the project is not listed again by itself (nothing asked for it after the retire)", bw.wanted(now=t0 + 300) == [])
check("5f: a new message inside the cooldown records nothing", bw.want_background(SOLO_KEY, "message", now=t0 + 100 + 3599) is False and bw.wanted(now=t0 + 3700) == [], wants())
check("5g: a new message after the cooldown (from the agent's showing up) wants again", bw.want_background(SOLO_KEY, "message", now=t0 + 100 + 3601) is True
      and wants()[prj_id(SOLO_KEY)] == {"key": SOLO_KEY, "at": t0 + 3701}, wants())
check("5h: …and the project is listed again", [r["key"] for r in bw.wanted(now=t0 + 3800)] == [SOLO_KEY])
# the cooldown counts from the later of the want and the serving
reset(); bw.want_background(SOLO_KEY, "message", now=t0); wants_ = wants(); wants_[prj_id(SOLO_KEY)]["served"] = t0 - 10_000; STATE.write_text(json.dumps({"schema": 1, "wants": wants_}))
check("5i: a want older than its serving counts the cooldown from the want (the later of the two)", bw.want_background(SOLO_KEY, "message", now=t0 + 3599) is False and bw.want_background(SOLO_KEY, "message", now=t0 + 3601) is True)
# a project that turns ineligible while its want is open is left out, and comes back when it is eligible again
reset(); bw.want_background(SOLO_KEY, "message", now=t0)
for why, pg in (("retired", page(["solo-main"], status="archived", session="solo")), ("with no front agent left", page([], session="solo")), ("hidden (a note page)", page(["solo-main"], type="note", session="solo"))):
    publish(**{SOLO_KEY: pg}); check(f"5j: a want whose project turned {why} is left out of the list", bw.wanted(now=t0 + 5) == [] and "served" not in wants()[prj_id(SOLO_KEY)], wants())
publish(); check("5k: …and is listed again once it is eligible (it was not served: no agent ever showed)", [r["key"] for r in bw.wanted(now=t0 + 6)] == [SOLO_KEY])
publish(**{SOLO_KEY: None}); check("5l: a project whose page is gone is left out", bw.wanted(now=t0 + 7) == [], wants()); publish()
# a project that gets an agent while it is wanted by a pending entry only (the New session form lists it in the record before its page line): the agent counts
reset(); bw.want_background(SOLO_KEY, "message", now=t0)
_prj.add_pending(prj_id(SOLO_KEY), "solo-engineer", {"front": False, "role": "engineer", "mandate_line": TIDIES}, by="test")
check("5m: an agent only registered in the record (its page line still owed) counts as listed", bw.wanted(now=t0 + 5) == [], wants())
_prj.drop_pending(prj_id(SOLO_KEY), "solo-engineer")

# ---- 6. the cap, and settings that are no numbers
reset(max_open=2); publish()
r1, r2, r3 = (bw.want_background(k, "message", now=t0 + i) for i, k in enumerate((SOLO_KEY, "projects/other", "projects/third")))
check("6a: max_open = 2: the third project's message records none while two wants are open", (r1, r2, r3) == (True, True, False) and keys() == ["projects/other", SOLO_KEY], (r1, r2, r3, keys()))
publish(**{"projects/other": page(["other-main"], {"other-docs": TIDIES}, session="other")})
r3b = bw.want_background("projects/third", "message", now=t0 + 10)
check("6b: …once one project got an agent the cap has room: the third records a want, and the list holds the two still without one", r3b is True and [r["key"] for r in bw.wanted(now=t0 + 11)] == [SOLO_KEY, "projects/third"], (r3b, wants()))
publish()
reset(max_open=0)
check("6c: max_open = 0 records none", bw.want_background(SOLO_KEY, "message", now=t0) is False and wants() == {})
for bad in ("x", None, -4, [], {}):
    reset(max_open=bad, cooldown_minutes=bad); check(f"6d: a setting that is no number ({bad!r}) reads as the default", bw.max_open() == 3 and bw.cooldown_seconds() == 3600.0, (bw.max_open(), bw.cooldown_seconds()))
reset(cooldown_minutes=0); bw.want_background(SOLO_KEY, "message", now=t0); wants_ = wants(); wants_[prj_id(SOLO_KEY)]["served"] = t0 + 1; STATE.write_text(json.dumps({"schema": 1, "wants": wants_}))
check("6e: cooldown_minutes = 0 lets a served project want again at once", bw.want_background(SOLO_KEY, "message", now=t0 + 2) is True)
reset(); STATE.write_text("not json at all {")
check("6f: a damaged state file reads as no wants: the next message records one (a lost want is only asked for again)", bw.want_background(SOLO_KEY, "message", now=t0) is True and keys() == [SOLO_KEY], STATE.read_text())

def asked(key, t):
    """want_background, with an exception it raised handed back as the answer (a check then fails, the suite goes on)."""
    try: return bw.want_background(key, "message", now=t)
    except Exception as e: return e
# ---- 7. a failing state directory: nothing raises, the message is routed exactly as before
reset(enabled=False); n = recp("the export page reads fine"); base_router = shape(act(n, SOLO))
reset(enabled=False); base_tool = msg(SOLO, "can you look at the export page when you have a minute?", "home-beta")
reset(); LOCK.mkdir()      # a directory where the lock file must be: opening it fails
err = io.StringIO()
with contextlib.redirect_stderr(err): r_direct = asked(SOLO_KEY, t0)
check("7a: want_background does not raise when the state cannot be locked: it answers False and says so on stderr", r_direct is False and "not recorded" in err.getvalue() and not STATE.exists(), err.getvalue())
with contextlib.redirect_stderr(io.StringIO()):
    n = recp("the export page reads fine"); r_router = shape(act(n, SOLO)); r_tool = msg(SOLO, "can you look at the export page when you have a minute?", "home-beta")
    r_rows = bw.wanted(); r_lines = bw.wanted_lines()
check("7b: the router rules the message exactly as before, with the state directory failing", r_router == base_router and r_router["ruling"] == "archived", (r_router, base_router))
check("7c: the message tool answers exactly as before, with the state directory failing", r_tool == base_tool and r_tool.startswith("held for solo-main's next turn"), (r_tool, base_tool))
check("7d: wanted() and the endpoint's text answer empty and do not raise", r_rows == [] and r_lines == "")
LOCK.rmdir()
reset(); STATE.mkdir()      # the state file is a directory: the read finds no wants, the write fails
with contextlib.redirect_stderr(io.StringIO()): r_direct = asked(SOLO_KEY, t0); r_tool = msg(SOLO, "can you look at the export page when you have a minute?", "home-beta")
check("7e: a state file that cannot be written does not raise either, and the message is still held", r_direct is False and r_tool == base_tool, (r_direct, r_tool))
STATE.rmdir()
reset(); real_look = bw._look
def bad_look(project): raise ValueError("the registry cannot be read")
bw._look = bad_look
with contextlib.redirect_stderr(io.StringIO()): r_direct = asked(SOLO_KEY, t0); r_rows = bw.wanted(); r_tool = msg(SOLO, "can you look at the export page when you have a minute?", "home-beta")
bw._look = real_look
check("7f: a project that cannot be read records none, lists none and the message is held as before", r_direct is False and r_rows == [] and r_tool == base_tool and not STATE.exists(), (r_direct, r_rows, r_tool))
import stackshot.core.readonly as _ro
_ro._reload_for_test(True)
try:
    reset()
    with contextlib.redirect_stderr(io.StringIO()): r_direct = asked(SOLO_KEY, t0)
finally: _ro._reload_for_test(False)
check("7g: a read-only standby copy writes no want", r_direct is False and not STATE.exists())

# ---- 8. the endpoint and the client read
from starlette.testclient import TestClient
reset(); publish()
tok = open(client.mint("testbox")).read().strip(); H = {"Authorization": "Bearer " + tok}
bw.want_background(SOLO_KEY, "message", now=t0); bw.want_background("projects/other", "message", now=t0 + 1)
app = server.mcp.http_app()
with TestClient(app) as c:
    r = c.get("/client/background-wanted"); check("8a: no token: 401, and the list is not read", r.status_code == 401 and "solo" not in r.text, r.status_code)
    r = c.get("/client/background-wanted", headers={"Authorization": "Bearer " + "x" * 43}); check("8b: a wrong token: 401", r.status_code == 401 and "solo" not in r.text, r.status_code)
    r = c.post("/client/background-wanted", headers=H, json={}); check("8c: it is a read: a POST to it is no write", r.status_code in (400, 404, 405), (r.status_code, r.text[:100]))
    r = c.get("/client/background-wanted", headers=H)
    check("8d: with the machine's token: 200, plain text, one line per project (key, name prefix, front agent), no cache", r.status_code == 200 and r.headers["content-type"].startswith("text/plain") and r.headers["cache-control"] == "no-store"
          and r.text == f"{SOLO_KEY} solo solo-main\nprojects/other other other-main\n", (r.status_code, r.headers.get("content-type"), r.text))
    check("8e: every line has three words and the first is a page key", all(len(l.split()) == 3 and l.split()[0] in PAGES for l in r.text.splitlines()), r.text)
    publish(**{SOLO_KEY: page(["solo-main"], {"solo-docs": TIDIES}, session="solo")})
    r = c.get("/client/background-wanted", headers=H); check("8f: a project that got an agent drops out of the answer", r.status_code == 200 and r.text == "projects/other other other-main\n", r.text)
    _cfg.CFG["background_agent"] = {**SETTINGS, "enabled": False}
    r = c.get("/client/background-wanted", headers=H); check("8g: with the switch off the answer is 200 and empty, whatever the state file holds", r.status_code == 200 and r.text == "", (r.status_code, r.text))
    _cfg.CFG["background_agent"] = dict(SETTINGS)
    r = c.get("/client/recycle-wanted", headers=H); check("8h: the neighboring reads are as before", r.status_code == 200 and r.text.split()[0].isdigit(), r.text)
check("8i: client.py knows the read", "background-wanted" in client.READS)
buf = io.StringIO(); client.get = lambda what, key="", timeout=10.0: (200, "projects/solo solo solo-main\n") if what == "background-wanted" else (404, "")
with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "background-wanted"])
check("8j: client.py background-wanted prints the lines", rc == 0 and buf.getvalue() == "projects/solo solo solo-main\n", buf.getvalue())
for label, fn in (("nothing wanted", lambda *a, **k: (200, "")), ("the server cannot be asked", lambda *a, **k: (0, "URLError: refused")), ("a refusal", lambda *a, **k: (401, "unauthorized"))):
    buf = io.StringIO(); client.get = fn
    with contextlib.redirect_stdout(buf): rc = client.main(["client.py", "background-wanted"])
    check(f"8k: {label}: prints nothing, exit 0", rc == 0 and buf.getvalue() == "", buf.getvalue())

# ---- 9. the text
docs = {p: (pathlib.Path(STACK) / "docs" / p).read_text() for p in ("router.md", "fleet-tool.md", "projects.md", "configuration-integrations.md")}
check("9a: the docs say it: the router's bullet, the fleet tool's contact point, the project page, the config table", "background_want.py" in docs["router.md"] and "background-wanted" in docs["fleet-tool.md"]
      and "A want for a background agent" in docs["projects.md"] and all(f"`background_agent.{k}`" in docs["configuration-integrations.md"] for k in ("enabled", "max_open", "cooldown_minutes")))
check("9b: the example config names the fleet tool and no fleet product", not re.search(r"(?i)\bsala\b|salamander", example_section) and "fleet tool" in example_section, example_section[:300])
check("9c: the module never starts or lists an agent: no subprocess, no project verb, no push", not re.search(r"subprocess|agent_add|agent_retire|telling|push", pathlib.Path(STACK, "stackshot/service/background_want.py").read_text().split('"""', 2)[2]))

# ---- 10. a renamed page, a line the endpoint cannot trust, a state file that is odd, a standby copy, the router's guard
def safely(fn, *a, **k):
    """fn's answer, or the exception it raised handed back (a check then fails and the suite goes on)."""
    try: return fn(*a, **k)
    except Exception as e: return e
reset(); publish(); bw.want_background(SOLO_KEY, "message", now=t0); PID = prj_id(SOLO_KEY); NEW = "projects/solo-new"
_prj.rename(SOLO_KEY, NEW)      # the page moves: the project's id follows it, the old key becomes a stub
publish(**{NEW: PAGES[SOLO_KEY], SOLO_KEY: page([], status="moved", session="solo")})
rows = safely(bw.wanted, now=t0 + 5)
check("10a: a want whose page was renamed is listed under the new key (it is looked up by the project's id), its prefix still the front agent's", rows == [{"key": NEW, "prefix": "solo", "front": "solo-main"}] and bw.wanted_lines() == f"{NEW} solo solo-main\n", rows)      # no name line: the prefix follows the front agent, not the page's new slug
check("10b: a message to the new key finds the want open (it records none) and refreshes its stored key",
      bw.want_background(NEW, "message", now=t0 + 6) is False and wants()[PID]["key"] == NEW and wants()[PID]["at"] == t0, wants())
publish(**{NEW: page(["solo-main"], {"solo-docs": TIDIES}, session="solo"), SOLO_KEY: page([], status="moved", session="solo")})
check("10c: …it is served once the agent is listed under the new key", bw.wanted(now=t0 + 100) == [] and wants().get(PID, {}).get("served") == t0 + 100, wants())
publish(**{NEW: PAGES[SOLO_KEY], SOLO_KEY: page([], status="moved", session="solo")})
check("10d: …and after the agent was lost a new message to the new key wants one again past the cooldown, not before it", bw.want_background(NEW, "message", now=t0 + 200) is False and bw.want_background(NEW, "message", now=t0 + 100 + 3601) is True
      and [r["key"] for r in bw.wanted(now=t0 + 3800)] == [NEW], wants())
_prj.rename(NEW, SOLO_KEY); publish()

# a line of the endpoint is three plain words: a project whose name prefix has a space, or whose front agent's name holds a newline, is left out
reset(); publish(**{"projects/spaced": page(["spaced-main"], session="has space", role="name"), "projects/forged": page(["forged-main\nprojects/other other other-main"], session="forged")})
ID_SPACED, ID_FORGED = prj_id("projects/spaced"), prj_id("projects/forged")
check("10e: a project whose display name has a space records no want", bw.want_background("projects/spaced", "message", now=t0) is False and wants() == {}, wants())
check("10f: a project whose front agent's name holds a newline records no want", bw.want_background("projects/forged", "message", now=t0) is False and wants() == {}, wants())
STATE.write_text(json.dumps({"schema": 1, "wants": {ID_SPACED: {"key": "projects/spaced", "at": 1}, ID_FORGED: {"key": "projects/forged", "at": 2}, prj_id(SOLO_KEY): {"key": SOLO_KEY, "at": 3}}}))
lines_ = bw.wanted_lines()
check("10g: …and a want already in the file for such a project is left out of the answer: every line is three plain words", lines_ == f"{SOLO_KEY} solo solo-main\n" and all(len(l.split()) == 3 for l in lines_.splitlines()), lines_)
publish()

# a state file that is odd
reset(); bw.want_background("projects/other", "message", now=5.0)
STATE.write_text(json.dumps({"schema": 1, "wants": {prj_id(SOLO_KEY): {"key": SOLO_KEY, "at": "yesterday"}, "junk": "not an object", "junk2": [1], prj_id("projects/other"): {"key": "projects/other", "at": 5}}}))
rows = safely(bw.wanted)
check("10h: an entry whose time is a string does not empty the list: it is read as time 0, the entry that is no object is skipped", isinstance(rows, list) and [r["key"] for r in rows] == [SOLO_KEY, "projects/other"], rows)
check("10i: …and a message to a project whose own entry is odd is told the want is open (nothing raises)", safely(bw.want_background, SOLO_KEY, "message", now=t0) is False)
reset(); STATE.write_text("[" * 200000 + "]" * 200000)
rd = safely(bw._read)
check("10j: a state file nested too deep to parse reads as no wants", rd == {}, rd)
check("10k: …a message then records its want, which replaces the damaged file, and the list shows it", safely(bw.want_background, SOLO_KEY, "message", now=t0) is True and keys() == [SOLO_KEY]
      and [r["key"] for r in safely(bw.wanted, now=t0 + 1)] == [SOLO_KEY], STATE.read_text()[:100])

# a standby copy reads quietly and marks nothing
reset(); bw.want_background(SOLO_KEY, "message", now=t0); publish(**{SOLO_KEY: page(["solo-main"], {"solo-docs": TIDIES}, session="solo")})
_ro._reload_for_test(True)
try:
    err = io.StringIO()
    with contextlib.redirect_stderr(err): r_rows = safely(bw.wanted, now=t0 + 10); r_one = safely(bw.want_background, "projects/other", "message", now=t0 + 11)
finally: _ro._reload_for_test(False)
check("10l: on a read-only standby copy wanted() and want_background print nothing to stderr, mark no want served and record none", err.getvalue() == "" and r_rows == [] and r_one is False
      and "served" not in wants()[prj_id(SOLO_KEY)] and keys() == [SOLO_KEY], (err.getvalue(), wants()))
publish()

# a want already open is not recorded again, whatever the time: the cooldown is for a served want
reset(); bw.want_background(SOLO_KEY, "message", now=t0)
check("10m: a second message to an open want past the cooldown leaves it as it was (its time does not move)", bw.want_background(SOLO_KEY, "message", now=t0 + 7200) is False and wants()[prj_id(SOLO_KEY)] == {"key": SOLO_KEY, "at": t0}, wants())

# nothing raises out of wanted(): not out of the whole read, not out of the marking of a served want
reset(); bw.want_background(SOLO_KEY, "message", now=t0); bw.want_background("projects/other", "message", now=t0 + 1)
real_open = bw._open
def bad_open(*a, **k): raise ValueError("the wants cannot be worked out")
bw._open = bad_open
with contextlib.redirect_stderr(io.StringIO()): r_rows = safely(bw.wanted); r_lines = safely(bw.wanted_lines)
bw._open = real_open
check("10n: wanted() and the endpoint's text answer empty when the wants cannot be worked out", r_rows == [] and r_lines == "", (r_rows, r_lines))
publish(**{SOLO_KEY: page(["solo-main"], {"solo-docs": TIDIES}, session="solo")})
real_write = bw._write
def bad_write(*a, **k): raise OSError("the disk is full")
bw._write = bad_write
with contextlib.redirect_stderr(io.StringIO()): r_rows = safely(bw.wanted, now=t0 + 5)
bw._write = real_write
check("10o: a served want that cannot be marked still leaves the list as it is: the other project is listed, nothing raises", isinstance(r_rows, list) and [r["key"] for r in r_rows] == ["projects/other"], r_rows)
publish()

# the router's call is guarded: a hook that raises changes nothing the message does, with the person talking to the front agent
def route_once(text, **kw):
    reset(); n = recp(text, **kw); res = act(n, SOLO); return shape(res), pushes(), held.count(U[SOLO])
stamp(SOLO, 5)
base_plain, base_fyi = route_once("the export page reads fine"), route_once("the export page reads fine", hold="fyi")
_live._HOOKS["want_background"] = boom
got_plain, got_fyi = route_once("the export page reads fine"), route_once("the export page reads fine", hold="fyi")
_live._HOOKS["want_background"] = hook
unstamp(SOLO)
check("10p: a hook that raises changes neither the ruling nor the delivery of a plain message or an fyi (nothing is sent to the front agent), the person talking to it or not",
      got_plain == base_plain and got_fyi == base_fyi and base_plain[0]["ruling"] == "archived" and base_plain[1] == [] and base_fyi[0]["ruling"] == "held", (got_plain, base_plain, got_fyi, base_fyi))

# a front agent that is only registered in the record (its page line still owed) does not count
publish(**{"projects/pendonly": page([], session="pendonly")}); PEND = prj_id("projects/pendonly"); reset()
_prj.add_pending(PEND, "pendonly-main", {"front": True, "role": "main", "mandate_line": FRONT}, by="test")
check("10q: a project whose only front agent is registered in the record, its page line still owed, records no want", bw.want_background("projects/pendonly", "message", now=t0) is False and wants() == {}, wants())
_prj.drop_pending(PEND, "pendonly-main"); publish()

# ---- 11. the name prefix: the page's name line, else the front agent's name (the -main one without -main), else the page's slug
from stackshot.projects import project_verbs as _pverbs
NOTE = {"projects/app": (["team-app-main"], {}), "projects/desk": (["desk-lead"], {}), "projects/multi": (["multi-a", "multi-b"], {}), "projects/awkward": (["bad name-main"], {})}
reset(); publish(**{k: page(f, b) for k, (f, b) in NOTE.items()}, **{"projects/styled": page(["styled-main"], session="styled-pre", role="name"),
                                                                    "projects/slacky": page(["slacky-main"], session="", surface_agents={"slacky-main": "slack"})})
def want_row(key):
    reset(); ok = bw.want_background(key, "message", now=t0); rows = bw.wanted(now=t0 + 1); return ok, rows
ok, rows = want_row("projects/app")
check("11a: no name line and a -main front agent: the prefix is the front agent's name without -main (the agent is team-app-engineer)", ok is True and rows == [{"key": "projects/app", "prefix": "team-app", "front": "team-app-main"}], rows)
check("11b: the endpoint's line shows it: <key> <prefix> <front>", bw.wanted_lines() == "projects/app team-app team-app-main\n", bw.wanted_lines())
ok, rows = want_row("projects/desk")
check("11c: no name line and a front agent that does not end in -main: the prefix is its whole name", ok is True and rows == [{"key": "projects/desk", "prefix": "desk-lead", "front": "desk-lead"}], rows)
ok, rows = want_row("projects/multi")
check("11d: no name line, several front agents and none -main: the prefix is the page's slug, as before", ok is True and rows == [{"key": "projects/multi", "prefix": "multi", "front": "multi-a"}], rows)
ok, rows = want_row("projects/styled")
check("11e: a page with a name line keeps that line's prefix, not the front agent's stem", ok is True and rows == [{"key": "projects/styled", "prefix": "styled-pre", "front": "styled-main"}], rows)
ok, rows = want_row("projects/awkward")
check("11f: a front agent whose name is no plain name (so its stem is none) records no want", ok is False and rows == [] and wants() == {}, (ok, rows, wants()))
ok, rows = want_row("projects/slacky")
check("11g: a front agent that is no session of the fleet makes no want, however its stem reads", ok is False and rows == [], (ok, rows))
# the ordered list itself, which the project verbs share
AP = lambda agents, entry=None: _prj.agent_prefixes("projects/demo-page", entry or {}, {}, agents)
check("11h: the list is the front agent's name first and the page's slug last; the slug alone with nothing to take a name from", AP({"team-x-main": {"front": True}}) == ["team-x", "demo-page"] and AP({}) == ["demo-page"] and AP(None) == ["demo-page"]
      and AP({"a-main": {"front": False}}) == ["demo-page"], (AP({"team-x-main": {"front": True}}), AP({}), AP(None)))
check("11i: a name line stands alone, as before (no front stem, no slug)", AP({"team-x-main": {"front": True}}, {"session": "line-name", "role": "name"}) == ["line-name"], AP({"team-x-main": {"front": True}}, {"session": "line-name", "role": "name"}))
check("11j: an agent only the record holds (its page line owed) and a surface agent give no name; the -main one is the one named when there are several", AP({"p-main": {"front": True, "page_owed": True}}) == ["demo-page"]
      and AP({"s-main": {"front": True, "surface": "slack"}}) == ["demo-page"] and AP({"b-desk": {"front": True}, "c-main": {"front": True}}) == ["c", "demo-page"] and AP({"only-desk": {"front": True}}) == ["only-desk", "demo-page"])
check("11k: the project verbs take the same list (the want's prefix is its first element) and a page with no agents keeps the slug",
      _pverbs.project_prefixes({"key": "projects/app", "agents": {"team-app-main": {"front": True}}}, {}, {}) == ["team-app", "app"]
      and _pverbs.project_prefixes({"key": "projects/app", "agents": {}}, {}, {}) == ["app"] and _pverbs.project_prefixes({"key": "projects/app", "pageless": True, "keeper": "k-name"}, {}, {}) == ["k-name"])
with TestClient(server.mcp.http_app()) as c:
    reset(); bw.want_background("projects/app", "message", now=t0)
    r = c.get("/client/background-wanted", headers=H)
    check("11l: GET /client/background-wanted answers the line with the new prefix", r.status_code == 200 and r.text == "projects/app team-app team-app-main\n", (r.status_code, r.text))
publish()

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
