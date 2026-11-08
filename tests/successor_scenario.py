"""Scenario test for the hand-over of open items left with a session that is gone (successor.py, server._orphan_handover over the hand-off pass's write) — fixture data, no live store, no network, no server socket.

A project's last agent is retired, or a mover's pane is gone for good: its open items must reach the closest live agent, found and moved by the audit.

  1  pure (successor.py): the closeness order. A retired project with two open items: one has a live parent page (its -main agent takes it: tier parent), one has only the scope's general -main agent
     (tier scope). A project with a live front agent gives its item to that agent (tier own) before any parent; a project whose own front agent is gone but whose background agent is live gives it
     to the background agent; a hub page's agent comes before the scope's; a mover that is no session at all (the project has no live agent) is an orphan too
  2  pure: an item with no live successor is a row with `to` "" and a reason that says so; an item the owner moves, or waits on, is never a row; a live mover is no row; a closed item is none
  3  pure: determinism and idempotence (the same input gives the same rows, rows are sorted by item; once the movers are the successors a second plan has no rows)
  4  server: the dry run reads and writes nothing (files byte for byte), and lists the moves with their reasons; `report` mode lists and moves nothing even when asked to apply; `off` and an empty
     heartbeat check nothing
  5  server: the apply moves an alive item through the hand-off pass's write: the new mover heads `needs`, a stored mover, `then` follow, the hand-off record names the new mover (via orphan, with the
     reason), the History line (the stall log, one entry that is new to History) reads `handed to X: Y is gone (...); closest live agent: ...`; a waiting item takes the successor as its post-wake
     mover and in `needs`, keeps no hand-off record, and gets the same History line; a background successor is told once, a front agent is not pushed to
  6  server: an item the owner moves, an owner's wait, and an item of a live mover are left as they were; a second call finds nothing to do and writes nothing (idempotent); a move is checked again under the
     item lock (an item written since it was found is left and counted `skipped`)
  7  server: an item with no live successor is not touched and is listed under `left` with the reason; it stays listed at the next call (and is moved once an agent is live)

    tests/run-suite successor        → exit 0 / 1"""
import contextlib, datetime, io, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="successor-"); T = pathlib.Path(tmp)
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
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=str(T)); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x", "cli"): (T / d).mkdir(parents=True)

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.waits import successor as S; from stackshot.model import model as M; from stackshot.waits import handoff as H; from stackshot.waits import stall as ST; from stackshot.audit import audit_run  # noqa: E402
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
TOLD = []
server._tell_woken = lambda gid, owner, note, tag="wake": TOLD.append((gid, owner, note)) and None      # no push leaves this suite: what would be told is recorded

# ---------------------------------------------------------------- 1-3. pure: successor.py on a fake registry
def page(front=(), back=(), **kw):
    agents = {n: "the front" for n in front} | {n: ("builds the code" if i == 0 else "keeps the pages") for i, n in enumerate(back)}
    return {"agents": agents, "back_agents": {n: agents[n] for n in back}, **kw}
REG = {"projects/par": page(["par-main"]),
       "projects/par/kid": page(["kid-main"], ["kid-back"]),
       "projects/solo": page(["solo-main"]),
       "projects/live": page(["live-front", "live-main"], ["live-back"]),
       "projects/bgp": page(["bgp-main"], ["bgp-build", "bgp-docs"]),
       "projects/onehub": page(["onehub-main"], hub="projects/hubpage"),
       "projects/hubpage": page(["hubpage-main"]),
       "projects/both": page(["both-main"], ["both-build"]),
       "projects/gen": page(["gen-main"])}
GEN = lambda project, reg: ("gen-main", "projects/gen")
alive = lambda mover, **m: {"status": "open", "_m": M.Model(M.ALIVE, mover=mover), "metadata": {"project": m.pop("project", "projects/par/kid"), **m}}
waiting = lambda post, **m: {"status": "open", "_m": M.Model(M.WAITING, wait=M.Wait(kind="time", kind_explicit=True, post_wake_mover=post)), "metadata": {"project": m.pop("project", "projects/par/kid"), **m}}
derive = lambda it: it["_m"]
LIVE = {"par-main", "live-main", "bgp-build", "bgp-docs", "hubpage-main", "gen-main", "live-front", "both-main", "both-build"}           # the sessions with a pane
gone = lambda who: "" if who in LIVE else f"{who} has no pane"
ITEMS = {"a1": alive("kid-main", project="projects/par/kid"),                       # the retired project with a live parent
         "a2": alive("solo-main", project="projects/solo"),                          # the retired project with only the scope's general agent
         "a3": alive("live-back", project="projects/live"),                          # the project with a live front agent
         "a4": alive("Oliver", project="projects/solo"),                             # his: never touched
         "a5": waiting("Oliver", project="projects/solo"),                           # waiting on him: never touched
         "a6": waiting("solo-main", project="projects/solo"),                        # a wait whose post-wake mover is gone
         "a7": alive("live-main", project="projects/live"),                          # a live mover: not an orphan
         "a8": alive("bgp-docs", project="projects/bgp"),                            # live background mover: nothing
         "a9": {**alive("kid-back", project="projects/par/kid"), "status": "completed"},     # closed: nothing
         "a10": alive("onehub-main", project="projects/onehub"),                     # its project's only agent is gone; the hub page has a live one
         "a11": alive("", project="projects/solo"),                                  # no session named, the project has no live agent
         "a12": alive("bgp-old", project="projects/bgp"),                            # alive, the front agent is gone, a builder is live: the builder
         "a13": alive("both-old", project="projects/both"),                          # alive, a front agent AND a builder are live: the builder (a front agent is told nothing)
         "a14": waiting("both-old", project="projects/both"),                        # waiting: the post-wake mover judges an arrival, the table's order: the -main agent
         "a15": alive("stackshot", project="projects/par/kid"),                      # the server's own label: no session, never read as gone
         "a16": alive("home-x via a script on box-a", project="projects/par/kid"),   # a script's label: the same
         "a17": alive("kid-main", project="projects/par/kid", hold=True, wake="2027-03-01"),      # a held item waits on its wake: not moved
         "a18": waiting("solo-main", project="projects/solo", hold=True)}            # …a held wait too
rows = {r["gid"]: r for r in S.plan(ITEMS, REG, derive, gone, str, general=GEN)}
check("1 pure: a retired project with a live parent hands its item to the parent's -main agent (tier parent), with the reason", rows["a1"]["to"] == "par-main" and rows["a1"]["tier"] == "parent"
      and "kid-main is gone (kid-main has no pane)" in rows["a1"]["why"] and "parent project projects/par" in rows["a1"]["why"], rows.get("a1"))
check("1 pure: a retired project with nothing above it hands its item to the scope's general -main agent (tier scope)", rows["a2"]["to"] == "gen-main" and rows["a2"]["tier"] == "scope" and "scope's general -main agent" in rows["a2"]["why"], rows.get("a2"))
check("1 pure: a project with a live front agent and no live background agent gives it to the -main agent (tier own), before another front agent, and says it is a front agent", rows["a3"]["to"] == "live-main" and rows["a3"]["tier"] == "own"
      and rows["a3"]["front"] is True and S.FRONT_NOTE in rows["a3"]["why"], rows.get("a3"))
check("1 pure: an alive item goes to a live background agent before any front agent (tier back, the builder first), and its line does not say front agent", rows["a12"]["to"] == "bgp-build" and rows["a12"]["tier"] == "back" and rows["a13"]["to"] == "both-build"
      and rows["a13"]["tier"] == "back" and rows["a13"]["front"] is False and "front agent" not in rows["a13"]["why"], (rows.get("a12"), rows.get("a13")))
check("1 pure: …a back_of hint (the server's builder-first list) sets the order among background agents; a waiting item keeps the table's order (the -main agent first)", S.pick("projects/bgp", REG, lambda n: True, GEN, alive=True, back_of=lambda p: ["bgp-docs", "bgp-build"]).name == "bgp-docs"
      and rows["a14"]["to"] == "both-main" and rows["a14"]["front"] is False and S.FRONT_NOTE not in rows["a14"]["why"], rows.get("a14"))
check("1 pure: a front agent takes an alive item (parent, hub, scope) only when no background agent is live, and every such line says it is a front agent", all(rows[g]["front"] and S.FRONT_NOTE in rows[g]["why"] for g in ("a1", "a2", "a10", "a11")), [rows[g]["why"] for g in ("a1", "a2", "a10", "a11")])
check("1 pure: a hub page's agent comes before the scope's (tier hub)", rows["a10"]["to"] == "hubpage-main" and rows["a10"]["tier"] == "hub", rows.get("a10"))
check("1 pure: a waiting item's post-wake mover that is gone is an orphan, and its row says it waits", rows["a6"]["state"] == "waiting" and rows["a6"]["from"] == "solo-main" and rows["a6"]["to"] == "gen-main", rows.get("a6"))
check("1 pure: an item with no session named is an orphan only when its project has no live agent (solo has none: a row; a project with one is none)",
      rows["a11"]["from"] == "" and rows["a11"]["to"] == "gen-main" and not S.orphans({"x": alive("", project="projects/live")}, derive, gone, lambda p: p == "projects/solo"), rows.get("a11"))
check("2 pure: the owner's item, the owner's wait, a live mover and a closed item are no rows", set(rows) == {"a1", "a2", "a3", "a6", "a10", "a11", "a12", "a13", "a14"}, sorted(rows))
check("2 pure: a server or script label stored as a mover is no session and is never read as gone; a held item (alive with a wake, or a held wait) is left, a parked one with a gone post-wake mover is not (a6)",
      not ({"a15", "a16", "a17", "a18"} & set(rows)) and rows["a6"]["state"] == "waiting", sorted(rows))
check("1 pure: the order inside a page is -main, other front agents, then background agents with the builder first",
      S.agents_of(REG["projects/live"]) == [("live-main", "main"), ("live-front", "front"), ("live-back", "back")] and S.agents_of(page(["x-main"], ["x-docs", "x-build"]))[1:] == [("x-docs", "back"), ("x-build", "back")]
      and S.agents_of({"agents": {"b": "x", "a": "y"}, "back_agents": {"b": "builds the code"}})[0] == ("a", "main"), S.agents_of(REG["projects/live"]))
check("1 pure: a background agent is the successor when the project's front agents are gone (tier own), the builder before the page keeper",
      S.pick("projects/bgp", REG, lambda n: n in ("bgp-docs", "bgp-build", "gen-main"), GEN).name == "bgp-build" and S.pick("projects/bgp", REG, lambda n: n in ("bgp-docs", "gen-main"), GEN).name == "bgp-docs")
nolive = lambda who: f"{who} has no pane"
r2 = {r["gid"]: r for r in S.plan(ITEMS, REG, derive, nolive, str, general=GEN)}
check("2 pure: with no live session at all, every orphan is a row with `to` empty and a reason that says no live successor was found, and nothing is invented",
      r2 and all(r["to"] == "" and "no live successor was found" in r["why"] for r in r2.values()) and "a7" in r2 and "a8" in r2, r2)
check("2 pure: a generic fallback that names a session with no pane is no successor", S.pick("projects/solo", REG, lambda n: False, GEN) is None and S.pick("projects/nowhere", {}, lambda n: n == "gen-main", GEN).tier == "scope")
check("3 pure: the same input gives the same rows twice, sorted by item", S.plan(ITEMS, REG, derive, gone, str, general=GEN) == S.plan(ITEMS, REG, derive, gone, str, general=GEN) and list(rows) == sorted(rows), list(rows))
after = {g: (alive(rows[g]["to"], project=it["metadata"]["project"]) if g in rows and it["_m"].state == M.ALIVE else
            waiting(rows[g]["to"], project=it["metadata"]["project"]) if g in rows else it) for g, it in ITEMS.items()}
check("3 pure: once each item's mover is its successor a second plan has nothing to do", S.plan(after, REG, derive, gone, str, general=GEN) == [], S.plan(after, REG, derive, gone, str, general=GEN))

# ---------------------------------------------------------------- 4-7. the server half: a store, a heartbeat, a registry
now0 = time.time()
DEAD_ISO = datetime.datetime.fromtimestamp(now0 - 3 * 3600, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
LIVE_NAMES = ["par-main", "live-main", "bgp-back", "gen-main", "both-main", "both-build"]
GONE_NAMES = ["kid-main", "kid-back", "solo-main", "live-back", "bgp-main", "both-old"]
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(LIVE_NAMES + GONE_NAMES, 10)}
def heartbeat(gone_names):
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": DEAD_ISO}}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({U[n]: {"name": n, "machine": "a", **({"gone": DEAD_ISO} if n in gone_names else {})} for n in U}))
heartbeat(GONE_NAMES)
def proj(agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0,
            "agents": {n: "builds the code" if n in back else "the front" for n in agents}, "back_agents": {n: "builds the code" for n in back}}
PAGES = {"projects/par": (["par-main"], []), "projects/par/kid": (["kid-main", "kid-back"], ["kid-back"]), "projects/solo": (["solo-main"], []),
         "projects/live": (["live-main", "live-back"], ["live-back"]), "projects/bgp": (["bgp-main", "bgp-back"], ["bgp-back"]), "projects/gen": (["gen-main"], []),
         "projects/both": (["both-main", "both-build"], ["both-build"])}
(T / "store/projects.json").write_text(json.dumps({"pages": {k: proj(*v) for k, v in PAGES.items()}}))
for key, (agents, back) in PAGES.items():
    path = T / f"brain/{key}.md"; path.parent.mkdir(parents=True, exist_ok=True)
    front = [a for a in agents if a not in back]
    path.write_text(f"---\ntitle: {key}\ndisplay-name: {key.replace('/', '-')}\nagents:\n" + "".join(f"  {a}: the front\n" for a in front)
                    + ("  background:\n" + "".join(f"    {a}: builds the code\n" for a in back) if back else "") + f"---\n\n# {key}\n\n## Current state\n\nx\n\n<!-- timeline -->\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
for sc in server._prj.scopes():
    server._cfg.CFG.setdefault("router", {})[f"general_{sc}"] = "projects/gen"          # the scope's general -main agent, whatever scope the fixture's pages derive
server._cfg.CFG.setdefault("audit", {})["orphan_handover"] = "apply"
DESC = "- A thing\n- It lives here\n- Done when done"
OWNER_ID = U["gen-main"]
def item(i, project, status="open", **meta):
    base = {"owner": OWNER_ID, "project": project, "next": "do the thing"}
    base.update(meta)
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": now0 - 3600, "state_updated": now0 - 3600,
                                                      "confirmed": now0 - 3600, "metadata": base}))
B = lambda i: server._gh.shown(f"a{i}")      # how the board writes the item id in this instance
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def raw(i): return (T / f"store/a/{i}.json").read_bytes()
WAKE = "2027-03-01"
item(101, "projects/par/kid", mover="kid-main", then="kid-main")                                   # alive, a live parent
item(102, "projects/solo", mover="solo-main")                                                      # alive, only the scope's general agent
item(103, "projects/live", mover="live-back")                                                      # alive, the project's front agent is live
item(104, "projects/solo", mover="Oliver")                                                         # his
item(105, "projects/solo", state="parked", wake=WAKE, wait_kind="time", post_wake_mover="Oliver")  # waiting on him
item(106, "projects/solo", state="parked", wake=WAKE, wait_kind="time", post_wake_mover="solo-main")      # waiting, post-wake mover gone
item(107, "projects/live", mover="live-main")                                                      # a live mover
item(108, "projects/bgp", mover="bgp-main")                                                        # a background agent takes it (told)
item(109, "projects/par/kid", status="completed", mover="kid-main")                                # closed
item(112, "projects/both", mover="both-old")                                                       # alive, a front agent and a builder are both live: the builder
item(113, "projects/par/kid", mover="kid-main", hold=True, wake=WAKE)                              # held on a wake: not moved
item(114, "projects/par/kid", mover="stackshot")                                                   # the server's own label: no session
item(115, "projects/solo", state="parked", wake=WAKE, wait_kind="time", post_wake_mover="solo-main", hold=True)      # a held wait: not moved
for i in range(200, 225):
    item(i, "projects/live", mover="live-main")                                                    # a board of live movers around the few orphans
for i in (101, 102, 103, 104, 105, 106, 107, 108, 109, 112, 113, 114, 115):
    check(f"4 fixture: item {i} reads as the fixture meant it", server._ho_derive({**rd(i), "gid": f"a{i}"}).state in (M.ALIVE, M.WAITING, M.DEAD), rd(i))
before = {i: raw(i) for i in [*range(101, 110), 112, 113, 114, 115]}
dry = server._orphan_handover(apply=False, now=now0)
ids = lambda rows_: sorted(r["id"] for r in rows_)
check("4 server: a dry run reads and writes nothing — every file is byte for byte as it was, nobody is told", all(raw(i) == before[i] for i in before) and not TOLD, TOLD)
check("4 server: …and lists what would move: the six orphans, each with its target, tier and reason; checked, not applied", dry["checked"] and not dry["applied"] and dry["found"] == 6 and dry["read"] == 37
      and {m["id"]: (m["to"], m["tier"]) for m in dry["moved"]} == {B(101): ("par-main", "parent"), B(102): ("gen-main", "scope"), B(103): ("live-main", "own"), B(112): ("both-build", "back"),
                                                                       B(106): ("gen-main", "scope"), B(108): ("bgp-back", "back")} and dry["left"] == [], dry)
check("4 server: every listed move carries its reason, naming the gone session and the successor", all(m["from"] in m["why"] and "is gone" in m["why"] and m["to"] in m["why"] for m in dry["moved"]), dry["moved"][:2])
server._cfg.CFG["audit"]["orphan_handover"] = "report"
rep = server._orphan_handover(apply=True, now=now0)
check("4 server: [audit] orphan_handover = report lists the same moves and moves nothing even when asked to apply", not rep["applied"] and "nothing was moved" in rep["note"] and "apply" in rep["note"] and ids(rep["moved"]) == ids(dry["moved"]) and all(raw(i) == before[i] for i in before), rep)
server._cfg.CFG["audit"]["orphan_handover"] = "off"
off = server._orphan_handover(apply=True, now=now0)
check("4 server: [audit] orphan_handover = off checks nothing", not off["checked"] and off["found"] == 0 and "off" in off["note"] and all(raw(i) == before[i] for i in before), off)
server._cfg.CFG["audit"]["orphan_handover"] = "apply"
real_idx = server._sessions_index
server._sessions_index = lambda *a, **k: {}
empty = server._orphan_handover(apply=True, now=now0)
server._sessions_index = real_idx
check("4 server: an empty heartbeat (every session would look gone) checks nothing and moves nothing", not empty["checked"] and "heartbeat is empty" in empty["note"] and all(raw(i) == before[i] for i in before), empty)

# 5/6: the apply
got = server._orphan_handover(apply=True, now=now0)
check("5 server: the apply reports six moves and no skip", got["applied"] and ids(got["moved"]) == sorted([B(101), B(102), B(103), B(106), B(108), B(112)]) and got["skipped"] == 0, got)
m_c, m_d, m_e, m_f, m_g = (mt(i) for i in (101, 102, 103, 106, 108))
check("5 server: the alive item's mover and `then` follow the retired session to its successor, which heads `needs`", m_c["mover"] == "par-main" and m_c["then"] == "par-main" and (m_c["needs"] or [""])[0] == "par-main"
      and "kid-main" not in json.dumps(m_c.get("needs")), m_c)
check("5 server: …the hand-off record names the new mover, comes from the server, and carries the orphan reason", m_c["handoff"]["to"] == "par-main" and m_c["handoff"]["via"] == "orphan" and "kid-main is gone" in m_c["handoff"]["reason"]
      and m_c["handoff"]["redirected_from"] == "kid-main", m_c.get("handoff"))
log_b = ST.log_of(m_c)
check("5 server: the History line: one new stall-log entry, `handed to par-main: kid-main is gone (...); closest live agent: ...`", len(log_b) == 1 and log_b[0]["text"].startswith("handed to par-main: kid-main is gone (")
      and "closest live agent" in log_b[0]["text"] and ST.new_entries({"stall": {"log": []}}, m_c) == log_b, log_b)
check("5 server: History shows it once (an old version holding the entry has no new one)", ST.new_entries(m_c, m_c) == [], None)
check("5 server: the scope's general agent takes the other alive item (needs, mover, record)", m_d["mover"] == "gen-main" and m_d["needs"][0] == "gen-main" and m_d["handoff"]["to"] == "gen-main", m_d)
check("5 server: the project's own live front agent takes the third, when no background agent is live, and the History line says it is a front agent (it is sent no notice)", m_e["mover"] == "live-main"
      and ST.log_of(m_e)[0]["text"].startswith("handed to live-main: live-back is gone") and "a front agent" in ST.log_of(m_e)[0]["text"] and "a front agent" in ST.log_of(m_c)[0]["text"], ST.log_of(m_e))
m_h = mt(112)
check("5 server: an alive item whose project has a live front agent AND a live builder goes to the builder, who is told, and its line does not say front agent", m_h["mover"] == "both-build"
      and "a front agent" not in ST.log_of(m_h)[0]["text"] and [t[1] for t in TOLD if "112" in t[0]] in ([U["both-build"]], ["both-build"]), (m_h, TOLD))
check("5 server: a waiting item takes the successor as its post-wake mover and in `needs`, keeps its wait and its date, and gets no hand-off record", m_f["post_wake_mover"] == "gen-main" and m_f["needs"][0] == "gen-main"
      and m_f.get("wake") == WAKE and m_f.get("wait_kind") == "time" and not m_f.get("handoff") and m_f.get("mover") in (None, ""), m_f)
check("5 server: …and the same History line, with the reason", len(ST.log_of(m_f)) == 1 and ST.log_of(m_f)[0]["text"].startswith("handed to gen-main: solo-main is gone"), ST.log_of(m_f))
check("5 server: the background successor is told once, in one message that names its item; the front agents are not pushed to", [t[1] for t in TOLD if "108" in t[0]] in ([U["bgp-back"]], ["bgp-back"])
      and not any(("101" in t[0] or "102" in t[0] or "103" in t[0]) for t in TOLD), TOLD)
check("6 server: the owner's item, his wait, a live mover's item, a closed item, a held item, a held wait and a server-labelled mover are as they were, byte for byte", all(raw(i) == before[i] for i in (104, 105, 107, 109, 113, 114, 115)),
      [i for i in (104, 105, 107, 109, 113, 114, 115) if raw(i) != before[i]])
snap = {i: raw(i) for i in [*range(101, 110), 112, 113, 114, 115]}; TOLD.clear()
again = server._orphan_handover(apply=True, now=now0 + 60)
check("6 server: a second call finds nothing, moves nothing, writes nothing, tells nobody (idempotent)", again["checked"] and again["found"] == 0 and again["moved"] == [] and again["left"] == [] and again["applied"]
      and all(raw(i) == snap[i] for i in snap) and not TOLD, again)

# 6: a move is checked again under the lock
item(110, "projects/par/kid", mover="kid-main")
orig_plan = S.plan
def plan_then_write(*a, **k):
    out = orig_plan(*a, **k)
    item(110, "projects/par/kid", mover="par-main", note="written since")          # somebody took the item between the find and the move
    return out
server._succ.plan = plan_then_write
skipped = server._orphan_handover(apply=True, now=now0 + 120)
server._succ.plan = orig_plan
check("6 server: an item written since it was found (its mover changed) is left, counted `skipped`, not moved over the write", skipped["skipped"] == 1 and skipped["moved"] == [] and mt(110)["mover"] == "par-main"
      and not ST.log_of(mt(110)) and mt(110).get("note") == "written since", skipped)

# 7: no live successor
item(111, "projects/solo", mover="solo-main")
heartbeat(GONE_NAMES + ["gen-main", "par-main"])
snap = rd(111)
left = server._orphan_handover(apply=True, now=now0 + 180)
check("7 server: an item whose scope's general agent is gone as well has no live successor: it is not touched and is listed under `left` with the reason, nothing is claimed moved",
      (L_a := [m for m in left["left"] if m["id"] == B(111)]) and "no live successor was found" in L_a[0]["why"] and L_a[0]["from"] == "solo-main" and left["moved"] == []
      and rd(111) == snap, left)
check("7 server: …other items of those two sessions are listed the same way (a mover that was live a minute ago is gone now)", {B(101), B(102), B(106), B(110)} <= {m["id"] for m in left["left"]}, [m["id"] for m in left["left"]])
heartbeat(GONE_NAMES + ["par-main"])
last = server._orphan_handover(apply=True, now=now0 + 240)
check("7 server: once an agent is live again the item is handed over at the next call", B(111) in ids(last["moved"]) and mt(111)["mover"] == "gen-main", last)

# 8: the minute pass is unchanged: it follows the stored mover only, writes no stall line, and its record is not an orphan's
item(120, "projects/par/kid", mover="kid-main", then="kid-main", post_wake_mover="kid-main")
item(121, "projects/par/kid", mover="kid-main", then="kid-main", post_wake_mover="kid-main")
done_m = server._handoff_exec([H.Step("move", f"a{120}", "kid-main did not take it", "kid-main", "bgp-back", via="redirect")], now0 + 300, verify=False)
m_i = mt(120)
check("8 minute pass: a move by the minute pass changes the stored mover and `needs` and records the hand-off, and leaves `then` and a post-wake mover as they were, with no stall line (as on main)",
      done_m == [f"a{120}"] and m_i["mover"] == "bgp-back" and m_i["needs"][0] == "bgp-back" and m_i["then"] == "kid-main" and m_i["post_wake_mover"] == "kid-main" and "stall" not in m_i
      and m_i["handoff"]["to"] == "bgp-back" and m_i["handoff"].get("via") == "redirect", m_i)
done_o = server._handoff_exec([H.Step("move", f"a{121}", "kid-main is gone", "kid-main", "bgp-back", via="orphan")], now0 + 301, verify=False)
check("8 minute pass: …the same move as the audit's hand-over (via orphan) also follows `then` and the post-wake mover, which is why the keys are limited to it", done_o == [f"a{121}"] and mt(121)["then"] == "bgp-back"
      and mt(121)["post_wake_mover"] == "bgp-back" and ST.log_of(mt(121)), mt(121))

# 9: a partial view of the fleet moves nothing it cannot prove
import shutil
(T / "fleet/b").mkdir()
(T / "fleet/b/sessions.json").write_text(json.dumps({"00000000-0000-4000-8000-0000000000f1": {"name": "mb-pane", "machine": "b", "gone": DEAD_ISO}}))      # machine b: a session list, no machine.json
item(130, "projects/solo", mover="mb-pane"); item(131, "projects/solo", mover="ghost-x")
p1 = server._orphan_handover(apply=False, now=now0 + 400)
listed = {m["id"] for m in p1["moved"] + p1["left"]}
check("9 partial view: a mover whose machine has no readable machine.json is not read as gone, and neither is a name with no row at all while a machine's view is partial", p1["checked"] and B(130) not in listed and B(131) not in listed, p1)
(T / "fleet/b/machine.json").write_text(json.dumps({"letter": "b", "fleet": "testbox-b", "claude": "1.0.0", "online": {"ok": True, "since": DEAD_ISO}}))
p2 = server._orphan_handover(apply=False, now=now0 + 401)
listed2 = {m["id"] for m in p2["moved"] + p2["left"]}
check("9 partial view: …with the machine's file readable and its session list whole, both are gone as before (the guard is the missing view, not the names)", {B(130), B(131)} <= listed2, p2)
shutil.rmtree(T / "fleet/b")
for i in (130, 131): (T / f"store/a/{i}.json").unlink()

# 10: a count that is more likely a partial view than that many gone sessions is reported and nothing is moved
for i in range(140, 152):
    item(i, "projects/solo", mover="solo-main")
snapc = {i: raw(i) for i in range(140, 152)}; TOLD.clear()
c1 = server._orphan_handover(apply=True, now=now0 + 500)
check("10 ceiling: more than ORPHAN_CEILING orphans are reported and nothing is moved, even when asked to apply: the answer says ceiling and why, the files and the messages show nothing", c1["ceiling"] and not c1["applied"] and c1["found"] == 12
      and "partial view" in c1["note"] and all(raw(i) == snapc[i] for i in snapc) and not TOLD and len(c1["moved"]) == 12, c1)
check("10 ceiling: …and the audit run puts it in the summary line", "partial view" in audit_run.orphan_text({**audit_run.orphan_stage(audit_run.Env(roles={}, fallback=lambda p: "", builder=lambda p: "", page_of=lambda p: ("", None), orphans=lambda apply: c1), apply=True)}), c1["note"])
for i in range(140, 152): (T / f"store/a/{i}.json").unlink()
server.ORPHAN_CEILING = 1000                       # the absolute number out of the way: the quarter of the board is what trips
for i in range(200, 225): item(i, "projects/live", status="completed", mover="live-main")       # a small board
tripped = 0
for j in range(1, 40):
    item(300 + j, "projects/solo", mover="solo-main")
    cj = server._orphan_handover(apply=False, now=now0 + 600 + j)            # a dry run: the orphans pile up, the stop is the same
    if cj.get("ceiling"):
        tripped = j; break
    check(f"10 ceiling: below a quarter of the open items ({cj['found']} of {cj['read']}) the hand-over lists its moves", not cj.get("ceiling") and cj["found"] <= cj["read"] // 4 and len(cj["moved"]) == cj["found"], cj)
snapq = {300 + j: raw(300 + j) for j in range(1, tripped + 1)}; TOLD.clear()
cq = server._orphan_handover(apply=True, now=now0 + 700)
check("10 ceiling: more than a quarter of the open items trips the same stop (nothing moved even when asked to apply, the note says why)", tripped > 1 and cq["ceiling"] and cq["found"] > cq["read"] // 4 and not cq["applied"] and "partial view" in cq["note"]
      and all(raw(k) == snapq[k] for k in snapq) and not TOLD, (tripped, cq))
server.ORPHAN_CEILING = 10

# the audit's own side, at the seam: the HTTP route answers what the function does
status, ans = server._client_post("a", "orphan-handover", {"apply": False})
check("the route `orphan-handover` answers 200 with the check (a dry run unless the body says apply)", status == 200 and ans["checked"] and not ans["applied"], (status, ans))
check("the audit run reads the same fields the server writes (orphan_stage over the route's answer)", audit_run.orphan_stage(audit_run.Env(roles={}, fallback=lambda p: "", builder=lambda p: "", page_of=lambda p: ("", None), orphans=lambda apply: ans), apply=False)["checked"], ans)

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: successor scenario, {len(ran)} checks")
