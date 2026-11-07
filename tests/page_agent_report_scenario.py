"""Scenario test for the daily audit's page agent lines check (tools/page_agent_report.py, audit.py page-agents) — made-up pages and sessions, a fake `sala`, no live store, no network, no server.

A leftover is a name of a page's `agents:` map (user-facing or background), of a sub-page's `agent:` line or of its `display-name:` line that sala does not know. An `agents:` name is known when it is a live
session or an alias of one (an old name folding into a live one); a `display-name:` is known when a live session is named so, or its alias is, or a live session's own name starts with `<name>-` — an alias
that starts so does not excuse it (the page was not renamed when its sessions were). Retired, done and moved pages are skipped, so is a line that holds a session id. Each leftover names whom it goes to: the page's
own -main agent, else the top-level page's, else the scope's general one, the first that is live. Nothing is flagged when sala's session list cannot be read (no sala, a failing call, no fleet store) or lists no
session, and the report says so. `anchors.sala_live` is what it was (live names and aliases as one set), `sala_sessions` gives the two apart. The CLI is read only: `--line`, `--json`, the listing and `--sessions`
agree, and `audit.py page-agents` runs the same report.

    tests/run-suite page_agent_report       → exit 0 / 1"""
import json, os, pathlib, re, subprocess, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="partest-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai"), ("session_links", f"{tmp}/fleet")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "store").mkdir(); (T / "fleet").mkdir(); (T / "home").mkdir()

# ---- a fake `sala`: prints the sessions file it is given, or fails, or prints nothing useful
SESS = T / "sessions.json"
(T / "fake_sala.sh").write_text(f'#!/bin/sh\nif [ -f {T}/sala-fails ]; then exit 3; fi\ncat {SESS}\n')
os.chmod(T / "fake_sala.sh", 0o755)
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_SALA=str(T / "fake_sala.sh"), HOME=str(T / "home"))

def row(name, *aliases): return {"name": name, "aliases": list(aliases), "state": "live"}
LIVE = [row("acme-main", "acme-lead"), row("acme-builder"), row("beta-main", "beta-old-main"), row("gamma"), row("delta-front", "delta-lead"), row("zeta-main"), row("eta-front", "eta-main"),
        row("kappa-main"), row("lambda-main", "lambda-old-main"), row("lambda-builder")]
def write_sessions(rows): SESS.write_text(json.dumps({"schema": 1, "sessions": rows}))
write_sessions(LIVE)

def page(session="", role="name", status="active", agents=None, back=None, **kw):
    return {"session": session, "role": role, "status": status, "agents": agents, "back_agents": back, "title": kw.pop("title", ""), **kw}
REG = {
    "projects/acme": page("acme", agents={"acme-main": "x", "acme-builder": "y", "acme-gone": "an agent that was renamed", "acme-gone-builder": "a builder that was retired"}, back={"acme-builder": "y", "acme-gone-builder": "z"}),
    "projects/beta": page("beta-old"),                                       # display-name: only an alias starts with it: flagged
    "projects/gamma": page("gamma"),                                         # a one-session project: a live session named so
    "projects/delta": page("delta-lead"),                                    # the display-name is an alias of a live session
    "projects/epsilon": page("epsilon-old", status="done", agents={"epsilon-gone": "x"}),   # retired: skipped
    "projects/zeta": page("zeta", agents={"zeta-main": "x"}),
    "projects/zeta/sub": page("zeta-gone", role="agent"),                    # a sub-page's agent: line naming nobody live
    "projects/eta": page("eta", agents={"eta-main": "an alias of a live session", "eta-extra": "a leftover"}),
    "projects/theta": page("theta", agents={"theta-old": "x"}),              # a leftover and no live -main agent anywhere
    "projects/iota": page("00000000-0000-4000-8000-0000000000b1", agents={"cse_0123abcd": "x"}),   # ids are no names
    "projects/kappa": page("kappa", agents={"kappa-main": "x"}),
    "projects/kappa/inherited": page("kappa", role="inherited"),             # inherited from the parent: not read again
    "projects/lambda": page("lambda-old", agents={"lambda-main": "x", "lambda-builder": "y"}, back={"lambda-builder": "y"}),   # the display-name is stale, only an alias starts with it
    "projects/moved-away": page("moved-old", title="Moved to projects/kappa"),
}
(T / "store/projects.json").write_text(json.dumps({"pages": REG}))

import anchors as A, page_agent_report as PAR
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def key(res): return sorted((f["page"], f["line"], f["name"]) for f in res["findings"])

# ---- 1. sala_sessions and sala_live
names, aliases = A.sala_sessions()
check("sala_sessions gives the live names and the aliases apart", "acme-main" in names and "acme-lead" not in names and "acme-lead" in aliases and len(names) == len(LIVE), (sorted(names), sorted(aliases)))
check("sala_live is the two as one set, as it was", A.sala_live() == names | aliases, A.sala_live())
(T / "sala-fails").write_text("")
check("a failing sala reads as None, for both", A.sala_sessions() is None and A.sala_live() is None, A.sala_sessions())
(T / "sala-fails").unlink()
SESS.write_text("not json")
check("output that is no session list reads as None", A.sala_sessions() is None, A.sala_sessions())
write_sessions(LIVE)

# ---- 2. the leftovers
res = PAR.read()
want = [("projects/acme", "agents line", "acme-gone"), ("projects/acme", "agents line", "acme-gone-builder"), ("projects/beta", "display-name", "beta-old"),
        ("projects/eta", "agents line", "eta-extra"), ("projects/lambda", "display-name", "lambda-old"), ("projects/theta", "agents line", "theta-old"), ("projects/theta", "display-name", "theta"), ("projects/zeta/sub", "agent line", "zeta-gone")]
check("the leftovers: gone agents (user-facing and background), a display-name only an alias starts with, a sub-page's agent: line", res["checked"] and key(res) == sorted(want), key(res))
check("known names are no finding: a live session, an alias of one, a display-name that is a live name or an alias, a display-name with live sessions under it",
      not {"projects/gamma", "projects/delta", "projects/zeta", "projects/kappa", "projects/kappa/inherited"} & {f["page"] for f in res["findings"]}, key(res))
check("a retired page, a moved one and a line that holds an id are skipped", not {"projects/epsilon", "projects/iota", "projects/moved-away"} & {f["page"] for f in res["findings"]}, key(res))
check("the counts: live sessions and active pages read", res["sessions"] == len(LIVE) and res["pages"] == len(REG) - 2, (res["sessions"], res["pages"]))
check("an alias keeps an agents: line alive (eta-main is an alias of eta-front)", ("projects/eta", "agents line", "eta-main") not in key(res), key(res))
check("every finding says what fixes it", all(f["fix"] for f in res["findings"]), res["findings"])

# ---- 3. whom it goes to
to = {(f["page"], f["name"]): f["to"] for f in res["findings"]}
check("a page's own -main agent when it is live", to[("projects/acme", "acme-gone")] == "acme-main" and to[("projects/lambda", "lambda-old")] == "lambda-main", to)
check("a page with no agent of its own and no fallback is told to no one (the audit uses its own -main agent)", to[("projects/beta", "beta-old")] == "", to)
check("a sub-page falls to the top-level page's -main agent", to[("projects/zeta/sub", "zeta-gone")] == "zeta-main", to)
check("a front agent that is itself gone is no one to tell: the first live one after it, else none", to[("projects/theta", "theta-old")] == "", to)

# ---- 4. nothing flagged when sala cannot be read, or lists nothing
(T / "sala-fails").write_text("")
res = PAR.read()
check("sala unreadable: nothing flagged, and it says so", res["checked"] is False and res["findings"] == [] and "not readable" in res["note"], res)
check("…and the one line says so", PAR.summary_line(res).startswith("Page agent lines: not checked") and "not readable" in PAR.summary_line(res), PAR.summary_line(res))
(T / "sala-fails").unlink()
write_sessions([])
res = PAR.read()
check("sala lists no session: nothing flagged, and it says so", res["checked"] is False and res["findings"] == [] and "no session" in res["note"], res)
write_sessions([{"name": "", "aliases": ["a-lone-alias"]}])
res = PAR.read()
check("rows with no name count as no session", res["checked"] is False and res["findings"] == [], res)
write_sessions(LIVE)
check("an empty registry flags nothing", PAR.read({})["findings"] == [] and PAR.read({})["checked"] is True, PAR.read({}))

# ---- 5. the CLI
def run(*a):
    r = subprocess.run([sys.executable, *a], capture_output=True, text=True, env=dict(os.environ)); return r.returncode, r.stdout, r.stderr
tool = os.path.join(STACK, "tools", "page_agent_report.py"); audit_py = os.path.join(STACK, "audit.py")
rc, out, err = run(tool, "--json")
js = json.loads(out) if rc == 0 else {}
check("--json: the same report", rc == 0 and js.get("checked") is True and sorted((f["page"], f["line"], f["name"]) for f in js["findings"]) == sorted(want), (rc, out[:300], err[:300]))
rc, out, _ = run(tool, "--line")
check("--line: the one line", rc == 0 and out.strip() == "Page agent lines: 8 line(s) on 6 page(s)", out)
rc, out, _ = run(tool)
check("the listing: one line per finding with whom it goes to, then the counts", rc == 0 and len([l for l in out.splitlines() if " · tell " in l]) == 8 and "projects/acme · agents line · acme-gone · " in out
      and "tell acme-main" in out and "(no live -main agent" in out and out.splitlines()[-1].startswith("Page agent lines: 8 line(s) on 6 page(s)"), out)
rc, out, _ = run(audit_py, "page-agents", "--line")
check("audit.py page-agents runs the same report", rc == 0 and out.strip() == "Page agent lines: 8 line(s) on 6 page(s)", out)
(T / "sala-fails").write_text("")
rc, out, _ = run(audit_py, "page-agents")
check("the CLI with sala unreadable: exit 0, no finding, says not checked", rc == 0 and "not checked" in out and " · tell " not in out, out)
(T / "sala-fails").unlink()
copy = T / "copy.json"; copy.write_text(json.dumps({"schema": 1, "sessions": [r for r in LIVE if r["name"] != "acme-builder"]}))
rc, out, _ = run(tool, "--sessions", str(copy), "--json")
js = json.loads(out) if rc == 0 else {}
check("--sessions reads the sessions from a file instead of sala", rc == 0 and js.get("sessions") == len(LIVE) - 1 and ("projects/acme", "agents line", "acme-builder") in {(f["page"], f["line"], f["name"]) for f in js["findings"]}, out[:300])
rc, out, _ = run(tool, "--sessions", str(T / "no-such.json"), "--line")
check("a --sessions file that is not there reads as not readable", rc == 0 and out.startswith("Page agent lines: not checked"), out)
rc, _, err = run(audit_py, "bogus")
check("audit.py's usage names page-agents", rc == 2 and "page-agents" in err, (rc, err))
check("the registry file is as it was (read only)", json.loads((T / "store/projects.json").read_text())["pages"] == REG, None)

# ---- 8. a list cut short: mass-unknown names are refused, a few unknowns pass
def many(n, prefix="mu"):
    return {f"projects/{prefix}{i}": {"session": f"{prefix}{i}", "role": "name", "status": "active", "agents": {f"{prefix}{i}-main": "x"}, "back_agents": {}} for i in range(n)}
BIG = many(40)
cut = ({f"mu{i}-main" for i in range(6)}, set())                                   # 34 of 40 names unknown: the list is cut short
r = PAR.scan(BIG, cut)
check("a mass-unknown list is refused: nothing flagged, not checked, the note says the list looks partial", r["checked"] is False and r["findings"] == [] and "partial" in r["note"] and PAR.summary_line(r).startswith("Page agent lines: not checked"), r)
few = ({f"mu{i}-main" for i in range(40) if i >= 3} | {f"mu{i}" for i in range(40)}, set())   # 3 of 40 agent names unknown (the display-names are live): the real shape
r = PAR.scan(BIG, few)
check("a few unknowns pass: they are flagged", r["checked"] is True and sorted(f["name"] for f in r["findings"]) == ["mu0-main", "mu1-main", "mu2-main"], r)
under_min = ({f"mu{i}-main" for i in range(1)} | {f"mu{i}" for i in range(4)}, set())   # 3 of 4 agent names unknown, but under the minimum: the cap does not apply
r = PAR.scan(many(4), under_min)
check("under the minimum of unknown names the cap does not apply, whatever the share", r["checked"] is True and len(r["findings"]) == 3, r)
def flat(n):
    return {f"projects/fl{i}": {"session": "", "role": "inherited", "status": "active", "agents": {f"fl{i}-main": "x"}, "back_agents": {}} for i in range(n)}
r = PAR.scan(flat(40), ({f"fl{i}-main" for i in range(30)}, set()))                 # 10 of 40 names unknown: a quarter exactly, not over it
check("exactly the share is not over it: 10 of 40 passes", r["checked"] is True and len(r["findings"]) == 10, (r["checked"], len(r["findings"]), r["note"]))
r = PAR.scan(flat(40), ({f"fl{i}-main" for i in range(29)}, set()))                 # 11 of 40 unknown: over a quarter
check("just over the share is refused: 11 of 40", r["checked"] is False and r["findings"] == [] and "11 of 40" in r["note"], (r["checked"], r["note"]))
check("the threshold is a module constant: a quarter, from 10 names", PAR.UNKNOWN_SHARE == 0.25 and PAR.UNKNOWN_MIN == 10, (PAR.UNKNOWN_SHARE, PAR.UNKNOWN_MIN))

# ---- 9. a project page with items and no agents map (the the replay of a page that moved)
import time
NOW = time.time(); DAY = 86400
def it(i, project, status="open", age=1):
    return {"id": str(i), "status": status, "updated": NOW - age * DAY, "state_updated": NOW - age * DAY, "metadata": {"project": project}}
def proj(agents=None, back=None, typ="project", **kw): return {"session": "", "role": "", "status": kw.pop("status", "active"), "type": typ, "agents": agents, "back_agents": back, "title": kw.pop("title", ""), **kw}
NREG = {
    "projects/example-three": proj(),                                                                         # the moved page: type project, no agents map, items
    "projects/staffed": proj({"staffed-main": "x"}),
    "projects/hub": proj({"hub-main": "x"}),
    "projects/hub/sub": proj(),                                                                    # a sub-page: its agents are on the page above
    "projects/retired": proj(status="archived"),
    "projects/memo": proj(typ="note"),
    "projects/empty": proj(),                                                                      # no items at all
    "projects/stale": proj(),                                                                      # one completed item, long ago
    "projects/touched": proj(),                                                                    # no open item, one completed 3 days ago
    "projects/bgonly": proj({"bgonly-builder": "builds"}, {"bgonly-builder": "builds"}),           # a background agent is no contact
}
NITEMS = [it(1, "projects/example-three"), it(2, "projects/example-three"), it(3, "projects/example-three", "completed", 5), it(4, "projects/staffed"), it(5, "projects/hub/sub"), it(6, "projects/retired"), it(7, "projects/memo"),
          it(8, "projects/stale", "completed", 90), it(9, "projects/touched", "completed", 3), it(10, "projects/bgonly"), it(11, "example-three")]      # item 11 names the page by its bare slug
NSESS = lambda: ({"staffed-main", "hub-main", "bgonly-builder"}, set())
gaps = lambda r: {f["page"]: f for f in r["findings"] if f["line"] in ("no agents map", "no front agent")}
res = PAR.read(NREG, NSESS, NITEMS, NOW)
g = gaps(res)
check("an agentless project page with open items is flagged: the example-three case", "projects/example-three" in g and g["projects/example-three"]["line"] == "no agents map" and g["projects/example-three"]["name"] == "3 open items", g)
check("…its text says the items have no contact, and what to do", "no contact" in g["projects/example-three"]["fix"] and "add the agents map" in g["projects/example-three"]["fix"] and "-main" in g["projects/example-three"]["fix"] and "general -main" in g["projects/example-three"]["fix"], g["projects/example-three"])
check("…and its line fits the audit's 'page · line · name · fix' with the fix under its clip", len(g["projects/example-three"]["fix"]) <= 240 and " · " not in g["projects/example-three"]["fix"], len(g["projects/example-three"]["fix"]))
check("a page with only a background agent is flagged as having no front agent", g.get("projects/bgonly", {}).get("line") == "no front agent", g)
check("a project with no open item but one touched in the last days is flagged, in those words", g.get("projects/touched", {}).get("name") == "1 item touched in 30 days", g)
check("not flagged: staffed, a sub-page, a retired page, a note, no items, only old completed items", not {"projects/staffed", "projects/hub", "projects/hub/sub", "projects/retired", "projects/memo", "projects/empty", "projects/stale"} & set(g), sorted(g))
check("exactly the three are flagged, and nothing else changed in the leftovers", sorted(g) == ["projects/bgonly", "projects/example-three", "projects/touched"] and res["findings"] == list(g.values()), key(res))
check("a flagged page gets its recipient like any line (the field is there; '' when no agent is live)", all("to" in f for f in res["findings"]), res["findings"])
NREG2 = {**NREG, "projects/example-three": proj({"example-three-main": "keeps it"})}
check("after the agents map with a -main agent is added, the page is not flagged", "projects/example-three" not in gaps(PAR.read(NREG2, NSESS, NITEMS, NOW)), gaps(PAR.read(NREG2, NSESS, NITEMS, NOW)))
check("the same page with the type changed to note is not flagged", "projects/example-three" not in gaps(PAR.read({**NREG, "projects/example-three": proj(typ="note")}, NSESS, NITEMS, NOW)))
check("the type is read case-insensitively", "projects/example-three" in gaps(PAR.read({**NREG, "projects/example-three": proj(typ="Project")}, NSESS, NITEMS, NOW)))
check("the items of a sub-page count for the page above it", "projects/hub" not in gaps(PAR.read(NREG, NSESS, NITEMS, NOW)) and PAR.item_counts(NITEMS, NREG, NOW)["projects/hub"]["open"] == 1, PAR.item_counts(NITEMS, NREG, NOW).get("projects/hub"))
check("an item of another page's name: no agentless page gets another's items", PAR.item_counts([it(1, "projects/other")], NREG, NOW).get("projects/example-three") is None)
r1 = PAR.read({"projects/example-three": proj()}, NSESS, [it(1, "projects/example-three")], NOW)
check("one open item reads '1 open item'", gaps(r1)["projects/example-three"]["name"] == "1 open item", gaps(r1))
check("sala unreadable: this kind is carried with the others (none)", PAR.read(NREG, lambda: None, NITEMS, NOW)["findings"] == [], PAR.read(NREG, lambda: None, NITEMS, NOW))
check("without items given nothing is flagged by it", not gaps(PAR.scan(NREG, NSESS())), gaps(PAR.scan(NREG, NSESS())))
(T / "store/projects.json").write_text(json.dumps({"pages": NREG})); (T / "store/a").mkdir()
for n, ti in enumerate(NITEMS, 1): (T / f"store/a/{n}.json").write_text(json.dumps({**ti, "id": str(n)}))
write_sessions([row("staffed-main"), row("hub-main"), row("bgonly-builder")])
rc, out, err = run(tool, "--json")
js = json.loads(out) if rc == 0 else {}
check("the CLI reads the items of the store: --json carries the same three", rc == 0 and sorted(f["page"] for f in js["findings"]) == ["projects/bgonly", "projects/example-three", "projects/touched"], (rc, out[:400], err[:300]))
rc, out, _ = run(audit_py, "page-agents")
check("the listing shows the line with its page, kind, count and fix", rc == 0 and "projects/example-three · no agents map · 3 open items · its items have no contact" in out and out.splitlines()[-1].startswith("Page agent lines: 3 line(s) on 3 page(s)"), out)
# ---- 10. a one-session page is a page by design; a session named for another project is not its own (example shapes)
def one(name, role="name", **kw): return {"session": name, "role": role, "status": kw.pop("status", "active"), "type": "project", "agents": kw.pop("agents", None), "back_agents": kw.pop("back", None), "title": kw.pop("title", "")}
SREG = {
    "projects/harbor": one("harbor", agents={"harbor-main": "x", "harbor-builder": "y"}, back={"harbor-builder": "y"}),    # a project other sessions are named for
    "projects/harbor/web": one("solo"),                                             # a sub-page's name is no project's name: solo-site is not named for it
    "projects/solo": one("solo-site"),                                                  # one session, a live one of its own name
    "projects/solo-prefix": one("solo-lab"),                                              # the name line starts a live session's name (solo-lab-main)
    "projects/gear": one("gear-design"),
    "projects/lantern": one("harbor-lantern"),                                           # the example-three case: the name line's session belongs to harbor
    "projects/gone-name": one("gone-name"),                                               # a name line no live session answers to
    "projects/no-session": one(""),                                                       # no session of its own at all
    "projects/id-session": one("00000000-0000-4000-8000-0000000000b1"),                  # a session id on the name line is no name
    "projects/agent-line": one("solo-site", role="agent"),                                # an agent: line is no name line
    "projects/bg-keeper": one("bgk", agents={"bgk-builder": "builds"}, back={"bgk-builder": "builds"}),   # background agents only, its keeper a live name line
}
SITEMS = [it(i, k) for i, k in enumerate(SREG, 1)]
SLIVE = lambda: ({"harbor-main", "harbor-builder", "solo-site", "solo-lab-main", "gear-design", "harbor-lantern", "bgk"}, set())
rs = PAR.read(SREG, SLIVE, SITEMS, NOW)
sg = {f["page"]: f for f in rs["findings"] if f["line"] in ("no agents map", "no front agent", "other project's session")}
check("one-session pages whose name line is a live session (or starts a live one) are not flagged, nor is a background-only page with a live keeper",
      not {"projects/solo", "projects/solo-prefix", "projects/gear", "projects/bg-keeper", "projects/harbor"} & set(sg), sorted(sg))
check("the example-three shape is flagged: a session named for another project, said so in the fix, the name is the session", sg.get("projects/lantern", {}).get("line") == "other project's session" and sg["projects/lantern"]["name"] == "harbor-lantern"
      and "named for harbor, not for this page" in sg["projects/lantern"]["fix"] and "1 open item" in sg["projects/lantern"]["fix"] and "general -main agent" in sg["projects/lantern"]["fix"], sg.get("projects/lantern"))
check("a name line no live session answers to, no session at all, a session id and an agent: line are flagged as no agents map", all(sg.get(k, {}).get("line") == "no agents map" for k in ("projects/gone-name", "projects/no-session", "projects/id-session", "projects/agent-line")), sorted(sg))
check("exactly those five are flagged", sorted(sg) == ["projects/agent-line", "projects/gone-name", "projects/id-session", "projects/lantern", "projects/no-session"], sorted(sg))
check("the example-three shape is still flagged when its session is not live", "projects/lantern" in {f["page"] for f in PAR.read(SREG, lambda: ({"harbor-main"}, set()), SITEMS, NOW)["findings"] if f["line"] == "other project's session"})
SREG2 = {**SREG, "projects/lantern": one("harbor-lantern", agents={"lantern-main": "keeps it"})}
check("…and clears when the page gets its own agents map with a -main agent", "projects/lantern" not in {f["page"] for f in PAR.read(SREG2, lambda: (SLIVE()[0] | {"lantern-main"}, set()), SITEMS, NOW)["findings"] if f["line"] != "agents line"}, None)
check("a flagged page with no items is not flagged (items are still the condition)", "projects/lantern" not in {f["page"] for f in PAR.read(SREG, SLIVE, [], NOW)["findings"]})
check("moved and superseded pages are skipped by the one shared predicate", all(not PAR.active(one("x", status=st)) for st in ("moved", "superseded", "archived")) and not PAR.active(one("x", title="Moved to elsewhere")) and PAR.active(one("x")))
import io, contextlib
err = io.StringIO()
with contextlib.redirect_stderr(err): rr = PAR.read(SREG, SLIVE, 5, NOW)
check("items that cannot be read: one note on stderr, no such finding, the leftovers still made", "board items could not be read" in err.getvalue() and err.getvalue().count("\n") == 1 and not [f for f in rr["findings"] if f["line"] in ("no agents map", "other project's session")] and rr["checked"] is True, (err.getvalue(), rr["findings"]))
# sibling-prefix shapes: a name that extends another project's name is its own when it is (or starts with) the page's own slug; a prefix-matched live session of a longer sibling does not cover a shorter page
TREG = {
    "projects/foo": one("foo", agents={"foo-main": "x"}),
    "projects/qux": one("foo-qux-main", agents={"foo-qux-main": "k"}, back={"foo-qux-main": "k"}),     # its keeper is its own background agent: the project name comes from the agents
    "projects/foo-bar": one("foo-bar"),                                                   # one session, named for its own slug next to a shorter project
    "projects/foo-baz": one("foo-baz-engineer", agents={"foo-baz-builder": "b"}, back={"foo-baz-builder": "b"}),   # background only, its keeper starts with its own slug
    "projects/harbor": one("harbor", agents={"harbor-main": "x"}),
    "projects/harbor-lantern": one("harbor-lantern"),                                   # the example-three name on a page of that very slug: its own
    "projects/dock": one("dock"),                                                       # a name that is a shorter project than its sibling's
    "projects/dock-core": one("dock-core", agents={"dock-core-main": "x"}),
    "projects/shared-a": one("zed-shared"), "projects/shared-b": one("zed-shared"),   # two pages sharing one session name
}
TITEMS = [it(i, k) for i, k in enumerate(TREG, 1)]
def tg(live): return sorted(f["page"] for f in PAR.read(TREG, lambda: (set(live), set()), TITEMS, NOW)["findings"] if f["line"] in ("no agents map", "no front agent", "other project's session"))
check("sibling prefixes: foo-bar, a background-only foo-baz with its keeper, harbor-lantern, the shared name: none is named for another project", tg(["foo-main", "foo-bar", "foo-qux-main", "foo-baz-engineer", "harbor-main", "harbor-lantern", "dock-core-main", "dock", "zed-shared"]) == [], tg(["foo-main", "foo-bar", "foo-qux-main", "foo-baz-engineer", "harbor-main", "harbor-lantern", "dock-core-main", "dock", "zed-shared"]))
check("a page `dock` is not covered by `dock-core-engineer` (it belongs to the page `dock-core`), but an exact name or a session of no longer project covers it",
      tg(["foo-main", "foo-bar", "foo-qux-main", "foo-baz-engineer", "harbor-main", "harbor-lantern", "dock-core-main", "dock-core-engineer", "zed-shared"]) == ["projects/dock"]
      and tg(["foo-main", "foo-bar", "foo-qux-main", "foo-baz-engineer", "harbor-main", "harbor-lantern", "dock-core-main", "dock-other-main", "zed-shared"]) == [], tg(["dock-core-engineer"]))
check("a parent: key on an entry makes no sub-page here, as in rename_page.py (one rule: projects.agent_gap)", PAR.agentless("projects/no-session", {**SREG["projects/no-session"], "parent": "projects/harbor"}, SREG, PAR.item_counts(SITEMS, SREG, NOW)) is not None)
err = io.StringIO()
with contextlib.redirect_stderr(err): PAR.read(SREG, SLIVE, SITEMS, NOW)
check("items that read: no note", err.getvalue() == "", err.getvalue())

print(("ok" if not fails else "FAILED") + f": page_agent_report scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
