"""Scenario test for the machine anchor (machine_anchor.py, evwaits_svc.machine_anchor_poll, _machine_note, the anchors tool's `machine:<name>`) — fixture data, no live store, no network, no server socket.

An item that needs a machine of the fleet used to sit on a dated backstop after the machine was back; only a `box_online <machine>` event wait turned an item. A machine anchor is the standing form: the
anchors tool takes `machine:<name>`, and the mover of each item the anchor counts for is told, once, each time that machine checks in again. Covered:

  * the pure half: the spelling (`machine:<name>`, any case), the store (add, scope union, remove, prune of closed items, what counts for an item), whole-word names in a step, the words of both lines.
  * the anchors tool: a machine is stored under its fleet name (a hostname and any case resolve), in its own file and not in anchors.json; an unknown machine or an empty name is refused naming the machines the
    fleet knows; URLs and machines in one call each take their own path; the list shows the machine anchors and whether each machine is online; remove drops it.
  * the check-in: nothing for a machine that is online when the anchor is added, nothing while it stays online or offline; at its next check-in (offline to online) the mover of each item in scope is told in
    one message that names the machine, the items and the step, and the next pass tells nothing more; another check-in tells again; an item with two machines hears of each by name; a project-wide anchor tells
    only the items whose open step names the machine; not told: a closed item, an item the owner moves, an item with its own box_online wait on that machine (that wait tells it); no item turns or is saved.
  * the write note: a create or update that leaves an open step naming an offline machine, with no machine anchor and no box_online wait for it, ends with one note naming the anchors call; never for an online
    machine, a done step, a name inside a longer one, an item that has the anchor or the wait; the write itself goes through.
  * the tool text names the form.

    tests/run-suite machine_anchor      → exit 0 / 1"""
import asyncio, datetime, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="machanchor-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/clients", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
PAGE = {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active", "board": [], "board_open": 0,
        "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
        "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": PAGE, "projects/beta": {**PAGE, "title": "Beta", "name": "Beta"}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n\n## Current state\n\nthe state.\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
# the fleet: box-a is online and stays so, box-b, box-c and box-d are named in the table, box-b checked in hours ago, box-c and box-d have never checked in
(T / "names.tsv").write_text("host-a\tbox-a\ta\nhost-b\tbox-b\tb\nhost-c\tbox-c\tc\nhost-d\tbox-d\td\n")
def iso(ts): return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
REC = {"host-a": {"fleet": "box-a", "letter": "b", "puller": now0 - 30.0, "online_since": now0 - 9 * DAY}, "host-b": {"fleet": "box-b", "letter": "d", "puller": now0 - 3 * 3600.0, "online_since": now0 - 4 * 3600.0}}
def write_state():
    REC["host-a"]["puller"] = time.time() - 30.0      # box-a keeps checking in, however long the suite takes
    (T / "state/clients/state.json").write_text(json.dumps({"machines": {h: {"letter": r["letter"], "fleet": r["fleet"], "first": iso(now0 - 9 * DAY), "puller": iso(r["puller"]), "online_since": iso(r["online_since"])} for h, r in REC.items()}, "sessions": {}}))
LAST = [0.0]
def checkin(host, at=None):
    """The machine's puller checks in again after being offline (clients.checkin stamps online_since then). The state file keeps whole seconds, so each check-in of the suite is a second after the one before."""
    at = max(time.time(), LAST[0] + 1.0) if at is None else at; LAST[0] = max(LAST[0], at)
    REC[host] = {**REC.get(host, {"fleet": host.replace("host", "box"), "letter": "e"}), "puller": at, "online_since": at}; write_state()
def go_offline(host, ago=3 * 3600.0): REC[host]["puller"] = time.time() - ago; write_state()
write_state()
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, subject=None, project="projects/alpha", **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": owner or U["home-front"], "project": project, "next": "team-back: do the thing", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import route as _wt_route; from stackshot.anchors import machine_anchor as MA; from stackshot.anchors import anchors as ANC; from stackshot.service import create as create_svc
from stackshot.service import update as _update_svc
from stackshot.github import ghsync as _gh
from stackshot.core import instance as _core_instance
from stackshot.core import config as _cfg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import event_waits as evwaits_svc
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
SENT: list[tuple[str, str, str, str]] = []
telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 56 * DAY, "seen": {}, "reported": []}))
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
BACK, FRONT = "team-back", "home-front"
UB = U["team-back"]
CFG = _cfg.CFG.setdefault("model", {})
CFG.update(guards=False, watchers=True, pause=False)
def reset(): SENT.clear()
R = _gh.shown
def anchors(**kw): return _wt_anchors._anchors("projects/alpha", who=BACK, **kw)
def tick(): return evwaits_svc.evwait_poll(time.time())
def mstore(): return json.loads((T / "store/machine-anchors.json").read_text()) if (T / "store/machine-anchors.json").exists() else {}
def notices(): return [x for x in SENT if x[3] == "watch"]

# ================================================================ the pure half
check("spelling: machine:<name> in any case, the name as written", MA.is_machine("machine:box-a") and MA.is_machine(" MACHINE: Box-A ") and MA.name_of(" MACHINE: Box-A ") == "Box-A"
      and not MA.is_machine("https://example.com/machine:x") and not MA.is_machine("slack:C123") and not MA.is_machine(7), None)
check("names_in: a whole word only, case ignored, the order given", MA.names_in("run it on Box-B tonight", ["box-a", "box-b"]) == ["box-b"] and MA.names_in("box-b, then box-a.", ["box-a", "box-b"]) == ["box-a", "box-b"]
      and MA.names_in("on box-bx or my-box-b or box-b2", ["box-b"]) == [] and MA.names_in("box-b's disk", ["box-b"]) == ["box-b"] and MA.names_in("", ["box-b"]) == [], None)
S: dict = {}
MA.add(S, "projects/alpha", ["box-b"], ["a1", "a2"], "x"); MA.add(S, "projects/alpha", ["box-b"], ["a3"], "x"); MA.add(S, "projects/alpha", ["box-c"], None, "x")
check("store: a machine already there takes the new items into its scope; no items is project-wide", sorted(S["projects/alpha"][0]["items"]) == ["a1", "a2", "a3"] and S["projects/alpha"][1]["items"] is None, S)
MA.add(S, "projects/alpha", ["BOX-B"], None, "x")
check("store: ...adding it project-wide widens it, the case ignored", len(S["projects/alpha"]) == 2 and S["projects/alpha"][0]["items"] is None, S)
S = {"projects/alpha": [{"machine": "box-b", "items": ["a1", "a2"], "added": 1.0}, {"machine": "box-c", "items": None, "added": 2.0}], "projects/beta": [{"machine": "box-c", "items": ["a1"], "added": 3.0}]}
check("counts: the entries that list the item (any page) and the project-wide ones of its own page, each machine once, scoped says which", MA.counts(S, "a1", "projects/alpha") == {"box-b": ("box-b", True), "box-c": ("box-c", True)}
      and MA.counts(S, "a2", "projects/alpha") == {"box-b": ("box-b", True), "box-c": ("box-c", False)} and MA.counts(S, "a9", "projects/beta") == {} and MA.counts(S, "a9", "projects/alpha") == {"box-c": ("box-c", False)}, MA.counts(S, "a2", "projects/alpha"))
check("prune: closed items leave a scope, an entry with none left goes, a project-wide one stays", MA.prune(S, lambda g: g == "a2") is True and S["projects/alpha"][0]["items"] == ["a2"] and "projects/beta" not in S and S["projects/alpha"][1]["items"] is None, S)
MA.remove(S, "projects/alpha", ["BOX-B"]); MA.remove(S, "projects/alpha", ["box-c"])
check("remove: by name, the case ignored; the last one takes its page away", S == {}, S)
check("words: the notice names the machine, each item and its link; the note names the anchors call for every machine",
      "box-b checked in at 10:00" in MA.notice("box-b", "10:00", [("a1", "[x] s", "http://l/1")]) and "a1" in MA.notice("box-b", "10:00", [("a1", "s", "l")]) and "machine:box-b" in MA.notice("box-b", "", [])
      and "add=[\"machine:box-b\", \"machine:box-c\"]" in MA.missing_note("a7", "projects/alpha", ["box-b", "box-c"], {}) and MA.missing_note("a7", "p", [], {}) == "", None)

# ================================================================ the anchors tool
for i in (30, 31, 32, 33, 34, 35, 36, 37):
    (T / f"store/a/{i}.json").unlink(missing_ok=True)
item(30, mover=BACK, subject="[home] needs box-b (one)")
item(31, mover=BACK, subject="[home] needs box-b and box-c (two)")
item(32, mover=BACK, subject="[home] project-wide: its step names box-b", next="team-back: run the sync on host-b once it is back")
item(33, mover=BACK, subject="[home] project-wide: no step names a machine", next="team-back: write the report")
item(34, mover=BACK, subject="[home] has its own box_online wait")
item(35, mover=BACK, subject="[home] closed", status="completed")
item(36, mover=_core_instance.OWNER, subject="[home] his step", next=f"{_core_instance.OWNER}: plug box-b in")
item(37, mover=BACK, subject="[home] needs box-a, which stays online")
before = (T / "store/anchors.json").read_text()
out = anchors(add=["machine:BOX-B"], items=["a30", "a31"])
check("tool: a machine is stored under its fleet name, scoped to the items, in a file of its own", mstore().get("projects/alpha") and mstore()["projects/alpha"][0]["machine"] == "box-b" and sorted(mstore()["projects/alpha"][0]["items"]) == ["a30", "a31"]
      and (T / "store/anchors.json").read_text() == before and ANC.load() == {}, (mstore(), out))
check("tool: ...the reply lists it with whether the machine is online, and says what happens at its next check-in", "machine:box-b" in out and "offline now" in out and "items: a30, a31" in out and "told at the machine's next check-in" in out, out)
out = anchors(add=["machine:host-c"], items=["a31"])
check("tool: a hostname resolves to the fleet name; a machine that never checked in is accepted (offline)", "machine:box-c" in out and mstore()["projects/alpha"][1]["machine"] == "box-c", (out, mstore()))
out = anchors(add=["machine:Box-A"], items=["a37"])
check("tool: a machine that is online now is accepted (an anchor stays, unlike a wait) and listed online", "machine:box-a" in out and "online now" in out, out)
refused("tool: an unknown machine is refused naming the machines the fleet knows", lambda: anchors(add=["machine:box-zz"], items=["a30"]), "names no machine of the fleet", "box-a, box-b, box-c, box-d")
refused("tool: an empty name is refused with the form", lambda: anchors(add=["machine:"]), "machine:<name>")
refused("tool: an item of another project is refused as for a URL", lambda: _wt_anchors._anchors("projects/beta", add=["machine:box-b"], items=["a30"], who=BACK), "belongs to")
refused("tool: a completed item is refused as for a URL", lambda: anchors(add=["machine:box-b"], items=["a35"]), "completed")
check("tool: nothing was stored by the refusals", len(mstore()["projects/alpha"]) == 3, mstore())
out = anchors(add=["https://github.com/acme/widgets/pull/12", "machine:box-b"], items=["a32"])
check("tool: URLs and machines in one call each take their own path (the URL in anchors.json, the machine in its own file, its scope widened)",
      "https://github.com/acme/widgets/pull/12" in ANC.load()["projects/alpha"][0]["url"] and "machine:" not in json.dumps(ANC.load()) and sorted(mstore()["projects/alpha"][0]["items"]) == ["a30", "a31", "a32"], (ANC.load(), mstore()))
anchors(remove=["https://github.com/acme/widgets/pull/12"])
anchors(add=["machine:box-c"])
out = anchors()
check("tool: a list call shows the machine anchors after the URLs, a machine added with no items as project-wide", "machine anchors" in out and "- machine:box-c  [project-wide]" in out and "- machine:box-b  [items: a30, a31, a32]" in out, out)
anchors(remove=["MACHINE:Box-C"])
check("tool: remove drops it by any spelling and leaves the others", [e["machine"] for e in mstore()["projects/alpha"]] == ["box-b", "box-a"], mstore())
# the scoped scenario of the check-in below: box-b for 30, 31 and the owner's 36; box-c for 31; box-a (online) for 37
anchors(remove=["machine:box-a", "machine:box-c", "machine:box-b"])
anchors(add=["machine:box-b"], items=["a30", "a31", "a36"]); anchors(add=["machine:box-c"], items=["a31"]); anchors(add=["machine:box-a"], items=["a37"])
MA.save({**mstore(), "projects/alpha": mstore()["projects/alpha"] + [{"machine": "box-b", "items": ["a35"], "added": time.time(), "by": "x"}]})       # a closed item in a scope
MA.save({**mstore(), "projects/beta": [{"machine": "box-b", "items": None, "added": time.time(), "by": "x"}]})       # a project-wide anchor of another page counts for that page's own items only
item(38, mover=BACK, subject="[home] other project's item that names box-b", project="projects/beta", next="team-back: run the sync on host-b")
check("counts: a project-wide anchor of one page counts for no item of another", MA.counts(mstore(), "a38", "projects/alpha") == {} and "box-b" in MA.counts(mstore(), "a38", "projects/beta"), MA.counts(mstore(), "a38", "projects/alpha"))
MA.save({k: v for k, v in mstore().items() if k != "projects/beta"})

# ================================================================ the check-in
reset()
check("check-in: nothing is told while the machines stay as they are, pass after pass, and for a machine that was online when its anchor was added", tick() == [] and tick() == [] and not notices(), SENT)
marks = MA.seen_load()
check("check-in: the mark of each machine was set when its anchor was added (box-a online: its check-in; box-c never: 0)", marks.get("box-b") is not None and marks.get("box-c") == 0.0 and marks.get("box-a", 0) > 0, marks)
before_items = {i: rd(i) for i in (30, 31, 32, 33, 34, 36, 37)}
checkin("host-b")
reset()
told = tick()
n = notices()
body = n[0][2] if n else ""
check("check-in: box-b checking in again tells the mover once, in one message, naming the machine and the items it counts for", len(n) == 1 and n[0][1] == UB and "box-b checked in" in body, n)
check("check-in: ...the items told are 30 and 31, each with its link and step; not the owner's 36, the closed 35, box-a's 37 or box-c's alone", set(n[0][0].split(",")) == {"a30", "a31"} and "- a30:" in body and "- a31:" in body and "step: team-back: do the thing" in body, n)
check("check-in: ...a closed item left the scope", all("a35" not in (e.get("items") or []) for e in mstore()["projects/alpha"]), mstore())
check("check-in: no item was turned or saved", all(rd(i) == before_items[i] for i in before_items), None)
check("check-in: the next pass tells nothing more", tick() == [] and len(notices()) == 1, SENT)
reset()
go_offline("host-b"); tick()
check("check-in: going offline tells nothing", not notices(), SENT)
checkin("host-b"); tick()
check("check-in: the next check-in tells again, once", len(notices()) == 1 and "box-b checked in" in notices()[0][2], SENT)
# two machines: 31 has box-b and box-c, each check-in says which came back
reset()
go_offline("host-b"); tick(); reset()
checkin("host-c"); tick()
only_c = notices()
check("two machines: box-c checking in tells only what box-c counts for (31), naming box-c, not box-b", len(only_c) == 1 and only_c[0][0] == "a31" and "box-c checked in" in only_c[0][2] and "box-b checked in" not in only_c[0][2], only_c)
reset()
checkin("host-b"); tick()
check("two machines: ...and box-b's later check-in says box-b, for 30 and 31", len(notices()) == 1 and "box-b checked in" in notices()[0][2] and set(notices()[0][0].split(",")) == {"a30", "a31"}, notices())
reset()
go_offline("host-b"); go_offline("host-c"); tick(); reset()
checkin("host-b"); checkin("host-c"); tick()
by_machine = {("box-b" if "box-b checked in" in x[2] else "box-c"): x for x in notices()}
check("two machines: both checking in in one pass give the mover one message for each, each naming its machine", len(notices()) == 2 and set(by_machine) == {"box-b", "box-c"} and by_machine["box-c"][0] == "a31", notices())

# a project-wide machine anchor tells only the items whose open step names the machine
anchors(remove=["machine:box-b", "machine:box-c", "machine:box-a"]); anchors(add=["machine:box-b"])
go_offline("host-b"); tick(); reset()
checkin("host-b"); tick()
n = notices()
check("project-wide: tells the open items of the project whose open step names the machine (32), not those whose steps do not (30, 31, 33), not the owner's (36), not another project's (38)",
      len(n) == 1 and set(n[0][0].split(",")) == {"a32"} and "run the sync on host-b" in n[0][2], n)

# an item with its own box_online wait on the machine is told by the wait, not twice
reset()
item(34, mover=BACK, subject="[home] has its own box_online wait", wait_kind="event", wait_event="box_online box-b", ask_by=day(5), post_wake_mover=BACK, needs=[])
anchors(remove=["machine:box-b"]); anchors(add=["machine:box-b"], items=["a34", "a30"])
go_offline("host-b"); tick(); reset()
checkin("host-b")
fired = tick()
told_gids = [g for x in SENT for g in x[0].split(",")]
check("own wait: the box_online wait turns the item and tells its mover; the machine anchor adds no second notice for it, and still tells the other item",
      "a34" in fired and mt(34).get("mover") == BACK and told_gids.count("a34") == 1 and told_gids.count("a30") == 1 and not any("machine anchor" in x[2] and "a34" in x[0].split(",") for x in SENT), (fired, SENT))
# a wait that is open on another machine only skips that machine
reset()
item(34, mover=BACK, subject="[home] has its own box_online wait on box-c", wait_kind="event", wait_event="box_online box-c", ask_by=day(5), post_wake_mover=BACK, needs=[])
go_offline("host-b"); tick(); reset()
checkin("host-b"); tick()
check("own wait: a wait on another machine does not stop the notice for this one", any("a34" in x[0].split(",") and "machine anchor" in x[2] for x in notices()), SENT)

# an item that waits on someone else and is moved after its wait by the owner is never told, however a notice could be routed (`then`, the stored mover): his queue is the board
reset()
for i in (60, 61, 62, 63):
    (T / f"store/a/{i}.json").unlink(missing_ok=True)
item(60, mover=BACK, then=BACK, subject="[home] waits on box-d, then his", next="team-back: run the sync on box-b", wait_kind="event", wait_event="box_online box-d", ask_by=day(5), post_wake_mover=_core_instance.OWNER, needs=[])
item(63, mover=_core_instance.OWNER, then=BACK, subject="[home] waits on box-d, his by the mover", next="team-back: run the sync on box-b", wait_kind="event", wait_event="box_online box-d", ask_by=day(5), needs=[])
item(61, mover=BACK, then=BACK, subject="[home] waits on box-d, then the back agent", next="team-back: run the sync on box-b", wait_kind="event", wait_event="box_online box-d", ask_by=day(5), post_wake_mover=BACK, needs=[])
anchors(add=["machine:box-b"], items=["a60", "a61", "a63"])
go_offline("host-b"); tick(); reset()
checkin("host-b"); tick()
told_gids = [g for x in notices() for g in x[0].split(",")]
check("waiting item: one whose post-wake mover is the owner gets no notice, though `then` and its stored mover are sessions; the same item with a session after the wait still does",
      "a60" not in told_gids and "a61" in told_gids, (SENT, mt(60)))
check("waiting item: ...and the owner's item stays as it was (nothing turned, nothing saved)", mt(60).get("post_wake_mover") and mt(60).get("wait_kind") == "event", mt(60))
check("waiting item: one the owner picks up by its mover (no post_wake_mover) gets no notice either, and stays as it was", "a63" not in told_gids and mt(63).get("mover") == _core_instance.OWNER and mt(63).get("wait_kind") == "event", (SENT, mt(63)))

# a box_online wait on machine A that turns an item and an anchor on machine B for it: A is told by the wait only, B is still told
reset()
item(62, mover=BACK, subject="[home] waits on box-c, anchored on box-b and box-c", next="team-back: run the sync on box-b", wait_kind="event", wait_event="box_online box-c", ask_by=day(5), post_wake_mover=BACK, needs=[])
anchors(add=["machine:box-b", "machine:box-c"], items=["a62"])
go_offline("host-b"); go_offline("host-c"); tick(); reset()
checkin("host-b"); checkin("host-c")
fired = tick()
mine = [x for x in SENT if "a62" in x[0].split(",")]
check("per machine: the wait on box-c turns the item and tells its mover once; the anchor adds no box-c notice but tells box-b's check-in, in the same pass",
      "a62" in fired and mt(62).get("mover") == BACK and any("box-b checked in" in x[2] for x in mine) and not any("box-c checked in" in x[2] for x in mine) and len(mine) == 2, (fired, mine))
reset()
check("per machine: ...and the next pass tells nothing more for either", tick() == [] and not [x for x in SENT if "a62" in x[0].split(",")], SENT)

# the marks are changed under the lock the anchors tool's seed() takes: a pass waits for it, and a mark raised meanwhile is not overwritten with an older reading
import threading
reset()
go_offline("host-b"); tick(); reset()
checkin("host-b")
since_b = evwaits_svc.machine_state("box-b")[1]
raised = since_b + 5000.0
with MA.LOCK:
    th = threading.Thread(target=tick, daemon=True); th.start()
    th.join(0.5)
    waited = th.is_alive()
    MA.seed("box-b", raised)
th.join(10)
check("lock: the pass does not read the marks while the lock is held, and ends after it is let go", waited and not th.is_alive(), (waited, th.is_alive()))
check("lock: a mark raised by seed() meanwhile survives the pass, and the check-in it covers is not told", MA.seen_load().get("box-b") == raised and not notices(), (MA.seen_load(), SENT))
MA.seed("box-b", since_b)      # the mark only ever rises
check("lock: seed() never lowers a mark", MA.seen_load().get("box-b") == raised, MA.seen_load())
MA.seen_save({**MA.seen_load(), "box-b": since_b}); tick()      # put the mark back for what follows
check("lock: no temp file is left behind by the writers", not [f.name for f in (T / "state").glob(".machine-anchor*.tmp")] and not [f.name for f in (T / "store").glob(".machine-anchors*.tmp")], list((T / "state").iterdir()))

# the mark: a lost state tells nothing for the past; a machine that checks in later does
reset()
(T / "state/machine-anchor.json").unlink()
check("mark: a lost state is read as 'what is past is told' and tells nothing", tick() == [] and not notices(), SENT)
go_offline("host-b"); tick(); checkin("host-b"); tick()
check("mark: ...and the next check-in is told", any("a30" in x[0].split(",") for x in notices()), SENT)

# prune: a closed item leaves its scope, an entry with no item left goes
item(30, mover=BACK, status="completed", subject="[home] needs box-b (one)")
tick()
check("prune: a closed item is dropped from the scopes at the next pass", all("a30" not in (e.get("items") or []) for e in mstore()["projects/alpha"]), mstore())

# ================================================================ the write note
write_state()
for i in (40, 41, 42, 43, 44, 45, 46):
    (T / f"store/a/{i}.json").unlink(missing_ok=True)
MA.save({}); go_offline("host-b"); go_offline("host-c")
item(40, mover=BACK, subject="[home] a step names an offline machine", next="team-back: wait")
out = _update_svc._update("a40", sender=BACK, next="team-back: run the nightly sync on host-b")
check("note: an open step naming an offline machine (by hostname) with no anchor ends the reply with one note naming the fix; the write went through",
      "(note: an open step of " + R("a40") + " names box-b" in out and "anchors(project=\"projects/alpha\", add=[\"machine:box-b\"], items=[\"" + R("a40") + "\"])" in out and "run the nightly sync on host-b" in mt(40)["next"] and out.count("(note: an open step of") == 1, out[-700:])
out = _update_svc._update("a40", sender=BACK, next="team-back: run the nightly sync on box-b and box-c")
check("note: two machines in the steps are one note, each named, once per write", out.count("(note: an open step of") == 1 and "box-b" in out.split("(note: an open step of")[1] and "box-c" in out.split("(note: an open step of")[1] and "box-c (last checked in" in out
      and "machine:box-b\", \"machine:box-c\"" in out, out[-700:])
anchors(add=["machine:box-b"], items=["a40"])
out = _update_svc._update("a40", sender=BACK, next="team-back: run the nightly sync on box-b and box-c")
check("note: an item with a machine anchor for box-b is told about box-c only", "(note: an open step of" in out and "names box-c" in out and "names box-b" not in out, out[-500:])
anchors(add=["machine:box-c"])
out = _update_svc._update("a40", sender=BACK, next="team-back: run the nightly sync on box-b and box-c")
check("note: ...a project-wide anchor on box-c counts too: no note", "(note: an open step of" not in out, out[-500:])
anchors(remove=["machine:box-b", "machine:box-c"])
out = _update_svc._update("a40", sender=BACK, next="team-back: run it on box-a")
check("note: a machine that is online now is not named", "(note: an open step of" not in out, out[-400:])
out = _update_svc._update("a40", sender=BACK, next="team-back: run it on box-bx and my-box-b")
check("note: a name inside a longer one is not a match", "(note: an open step of" not in out, out[-400:])
out = _update_svc._update("a40", sender=BACK, next="team-back: run the sync on box-b", description="- A thing\n- box-c is mentioned only here\n- Done when done")
check("note: only open steps are read, not the description", "names box-b" in out and "box-c" not in out.split("(note: an open step of")[1], out[-500:])
# a done step is not read
item(41, mover=BACK, subject="[home] steps", next="team-back: first\nteam-back: run it on box-c\nteam-back: last")
out = _update_svc._update("a41", sender=BACK, done=[1])
check("note: marking another step done leaves the named open step noted", "names box-c" in out, out[-400:])
out = _update_svc._update("a41", sender=BACK, done=[2])
check("note: a step marked done is no longer read (only the open ones are)", "(note: an open step of" not in out, out[-400:])
# a box_online wait on that machine is the other way to be told
item(42, mover=BACK, subject="[home] doing, will wait for box-b", next="team-back: run it on box-b")
out = _update_svc._update("a42", sender=BACK, wait_kind="event", wait_event="box_online box-b", ask_by=day(5), post_wake_mover=BACK, mover="none")
out2 = _update_svc._update("a42", sender=BACK, subject="[home] doing, will wait for box-b (reworded)")
check("note: an item with a box_online wait on the machine needs no anchor, and gets no note", "(note: an open step of" not in out2, out2[-400:])
out = _update_svc._update("a40", sender=BACK, next="team-back: run it on box-d")
check("note: a machine that has never checked in is offline and says so", "names box-d (has not checked in yet)" in out, out[-500:])
# a create
cout = create_svc.create_item(subject="[home] new item for box-b", description=DESC, project="projects/alpha", owner=U["home-front"], mover=BACK, next="team-back: run the sync on host-b", goal="Done when box-b ran it.", request_id="machanchor-create-1")[1]
check("note: a create takes the same note, with the new item's id", "(note: an open step of" in cout and "names box-b" in cout and "machine:box-b" in cout, cout[-600:])
cout = create_svc.create_item(subject="[home] new item with no machine", description=DESC, project="projects/alpha", owner=U["home-front"], mover=BACK, next="team-back: write the report", goal="Done when written.", request_id="machanchor-create-2")[1]
check("note: ...and none when no step names a machine", "(note: an open step of" not in cout, cout[-400:])
# a closed item is never noted
item(43, mover=BACK, subject="[home] closing", next="team-back: run it on box-b")
out = _update_svc._update("a43", sender=BACK, status="completed", outcome="done", reason="it ran", outcome_text="- it ran")
check("note: a close is not noted", "(note: an open step of" not in out, out[-400:])
# an unreadable clients state is no failure of the write
(T / "state/clients/state.json").write_text("not json")
out = _update_svc._update("a40", sender=BACK, next="team-back: run it on host-b")
check("note: a clients state that cannot be read leaves the write as it was (no note, no error)", out.startswith("updated"), out[:200])
write_state()

# ================================================================ the tool text
tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
check("tool text: anchors names machine:<name>, what is told, that no item turns, and the unknown machine's refusal",
      all(w in tools["anchors"].description for w in ("machine:<name>", "checks in again", "an unknown name is refused", "not a wait", "project-wide machine anchor")) and "machine:<name>" in tools["anchors"].parameters["properties"]["add"]["description"]
      and "machine:<name>" in tools["anchors"].parameters["properties"]["remove"]["description"], tools["anchors"].description[-900:])
check("tool text: create and update tell that a step naming an offline machine gets a note and what fixes it",
      all("names a machine of the fleet which is offline now" in tools[n].description and "note, never a refusal" in tools[n].description for n in ("create", "update")), None)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
