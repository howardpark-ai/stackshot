"""Scenario test for the anchor-wait refusal (server._anchor_wait_gate) — fixture data, no live store, no network, no server socket.

A create or an update that sets wait_kind=anchor with a wait_anchor that is not on the project's anchors list is refused, and the refusal names the `anchors` call that adds it. Covered:

  * an update with an unlisted anchor is refused: the message names the anchor, the project and anchors(project, add=[url], items=[this item]); nothing is stored.
  * listed anchors are accepted: scoped to the item (on its own project's page, or on another project's page), and project-wide on the item's own project page; the same anchor with a
    #fragment or in another spelling counts as the same. A project-wide anchor of another project's page does not count for the item.
  * the order the refusal asks for works: add the anchor scoped to the item, then the same update is accepted.
  * an anchor wait already stored is not judged again when the write leaves wait_kind and wait_anchor as they are (a new backstop day, an unchanged re-send); a changed wait_anchor is judged.
  * a create with an unlisted anchor is refused (the message offers a project-wide add, or creating without the wait); a create naming a project-wide anchor is accepted.
  * an anchors file that is present but unreadable (corrupt JSON, not an object) lets the write through with a stderr line; a missing file is an empty list and still refuses.
  * a wait_anchor that is no anchor shape (free text, an unparseable URL) is refused with the message that the anchors tool accepts only certain links, not with an add that would be refused too.
  * other wait kinds (time, item, relay) and an anchor wait that names no wait_anchor (its anchor scoped to the item) are not judged by it.

    tests/run-suite anchor_wait_refusal        → exit 0 / 1"""
import contextlib, io, json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="anchrefusal-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "brain/projects", "transcripts/-scratch-t"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
ZONE_HOURS = 4      # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}},
                                                          "projects/beta": {"title": "Beta", "name": "Beta", "org": "home", "tags": [], "type": "project",
                                                                            "session": "", "status": "active", "board": [], "board_open": 0}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n")
(T / "brain/projects/beta.md").write_text("---\ntitle: Beta\n---\n\n# Beta\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", subject=None, project="projects/alpha", **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su,
                                                              "metadata": {"owner": owner or U["home-front"], "project": project, "next": "team-back: do the thing", **meta}}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
def mt(i, letter="a"): return rd(i, letter)["metadata"]
def raw(i, letter="a"): return (T / f"store/{letter}/{i}.json").read_text()
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
def accepted(name, f):
    try:
        f(); check(name, True)
    except Exception as e:
        check(name, False, str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
import server
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda gid, owner, note, tag="wake": None
CFG = server._cfg.CFG.setdefault("model", {})
CFG.update(guards=False, watchers=True, pause=False)       # the write guards have their own suite
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
BACK, FRONT = "team-back", "home-front"
A1, A2, A3, A4, A5 = (f"https://github.com/o/r/pull/{n}" for n in (101, 102, 103, 104, 105))
def anchors(**pages): server._anc.save({k.replace("_", "/", 1): v for k, v in pages.items()})
def entry(url, items=None): return {"url": url, "items": items, "added": now0, "by": "x"}
def wait(gid, url, **kw):
    return server._update(gid, sender=FRONT, wait_kind="anchor", wait_anchor=url, wait_event="PR merged", ask_by=day(6), post_wake_mover=BACK, mover="none", **kw)

# ================================================================ an update
item(60, subject="[home] waits on an unlisted anchor", needs=[BACK])
before = raw(60)
try:
    wait("a60", A1); check("update: an anchor that is not on the project's list is refused", False)
except Exception as e:
    msg = str(e)
    check("update: an anchor that is not on the project's list is refused", "Refused" in msg, msg)
    check("update: …the message names the anchor and the project", A1 in msg and "projects/alpha" in msg and "anchors list" in msg, msg)
    check("update: …and the anchors call that adds it scoped to this item, then the wait again", f'anchors(project="projects/alpha", add=["{A1}"], items=["{server._gh.shown("a60")}"])' in msg and "set the wait again" in msg, msg)
check("update: …nothing was stored", raw(60) == before, mt(60))

anchors(projects_alpha=[entry(A2, ["a60"])])
accepted("update: an anchor scoped to the item is accepted", lambda: wait("a60", A2))
check("update: …and stored as the item's wait", mt(60).get("wait_kind") == "anchor" and mt(60).get("wait_anchor") == A2, mt(60))

item(61, subject="[home] project-wide anchor", needs=[BACK])
anchors(projects_alpha=[entry(A3)])
accepted("update: a project-wide anchor of the item's own project is accepted", lambda: wait("a61", A3))

item(62, subject="[home] another project's project-wide anchor", needs=[BACK])
anchors(projects_beta=[entry(A3)])
refused("update: a project-wide anchor of another project's page does not count", lambda: wait("a62", A3), "anchors list", A3)
anchors(projects_beta=[entry(A3, ["a62"])])
accepted("update: …but an anchor scoped to the item on another project's page does", lambda: wait("a62", A3))

item(63, subject="[home] same anchor, spelled with a fragment", needs=[BACK])
anchors(projects_alpha=[entry(A4)])
accepted("update: the listed anchor with a #fragment is the same anchor", lambda: wait("a63", A4 + "#issuecomment-9"))

item(64, subject="[home] add first, then wait", needs=[BACK])
anchors(projects_alpha=[])
refused("order: the wait is refused before the anchor is added", lambda: wait("a64", A5), "anchors(project=")
server._anchors("projects/alpha", add=[A5], items=["a64"])
accepted("order: …and accepted once the anchors tool has added it scoped to the item", lambda: wait("a64", A5))

# ================================================================ an unchanged re-save, a changed anchor
item(65, subject="[home] stored anchor wait, anchor not listed", wait_kind="anchor", wait_anchor=A1, wait_event="PR merged", ask_by=day(5), post_wake_mover=BACK, needs=[])
anchors(projects_alpha=[])
accepted("re-save: a new backstop day on a stored anchor wait whose anchor is not listed is not refused", lambda: server._update("a65", sender=FRONT, ask_by=day(8)))
check("re-save: …the new day stands", mt(65).get("ask_by") == day(8) and mt(65).get("wait_anchor") == A1, mt(65))
accepted("re-save: the same wait_kind and wait_anchor sent again are not refused", lambda: server._update("a65", sender=FRONT, wait_kind="anchor", wait_anchor=A1, wait_event="PR merged"))
accepted("re-save: the wait_event changed alone is not refused", lambda: server._update("a65", sender=FRONT, wait_event="PR merged and live"))
refused("re-save: a changed wait_anchor is judged", lambda: server._update("a65", sender=FRONT, wait_anchor=A2), "anchors list", A2)
check("re-save: …and the stored anchor stays", mt(65).get("wait_anchor") == A1, mt(65))
item(66, subject="[home] stored time wait, turned into an anchor wait", wait_kind="time", hold=True, wake=day(3), post_wake_mover=BACK, needs=[])
refused("change: a stored wait of another kind turned into an anchor wait on an unlisted anchor is judged", lambda: server._update("a66", sender=FRONT, wait_kind="anchor", wait_anchor=A1, wait_event="PR merged", ask_by=day(6)), "anchors list", A1)

# ================================================================ a create
refused("create: an unlisted anchor is refused, the message offers the project-wide add",
        lambda: server._create(subject="[home] new anchor wait", description=DESC, project="projects/alpha", owner=FRONT, next="team-back: do it", needs=[BACK],
                               wait_kind="anchor", wait_anchor=A1, wait_event="PR merged", ask_by=day(6), post_wake_mover=BACK, mover="none"),
        "Refused", A1, 'anchors(project="projects/alpha", add=["' + A1 + '"])', "without the wait")
anchors(projects_alpha=[entry(A1)])
accepted("create: a project-wide anchor of the project is accepted",
         lambda: server._create(subject="[home] new anchor wait, listed", description=DESC, project="projects/alpha", owner=FRONT, next="team-back: do it", needs=[BACK],
                                wait_kind="anchor", wait_anchor=A1, wait_event="PR merged", ask_by=day(6), post_wake_mover=BACK, mover="none"))

# ================================================================ an unreadable anchors file, a value that is no anchor shape
AF = T / "store/anchors.json"
for label, content in (("corrupt JSON", "{not json"), ("a JSON list", "[1, 2]"), ("an empty file", "")):
    item(80, subject="[home] anchors file unreadable", needs=[BACK]); AF.write_text(content, encoding="utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        accepted(f"unreadable file ({label}): the anchor wait is written", lambda: wait("a80", A1))
    check(f"unreadable file ({label}): …the wait is stored", mt(80).get("wait_kind") == "anchor" and mt(80).get("wait_anchor") == A1, mt(80))
    check(f"unreadable file ({label}): …and a stderr line says it was not judged", "anchor wait: a80 not judged" in err.getvalue(), err.getvalue())
item(81, subject="[home] anchors file unreadable, create", needs=[BACK]); AF.write_text("{not json", encoding="utf-8")
with contextlib.redirect_stderr(io.StringIO()) as err2:
    accepted("unreadable file: a create with an anchor wait is written too",
             lambda: server._create(subject="[home] new anchor wait, file unreadable", description=DESC, project="projects/alpha", owner=FRONT, next="team-back: do it", needs=[BACK],
                                    wait_kind="anchor", wait_anchor=A1, wait_event="PR merged", ask_by=day(6), post_wake_mover=BACK, mover="none"))
check("unreadable file: …with its stderr line", "not judged" in err2.getvalue(), err2.getvalue())
item(82, subject="[home] anchors file missing", needs=[BACK]); AF.unlink()
refused("missing file: is an empty list, the anchor wait is refused", lambda: wait("a82", A1), "Refused", "anchors list", A1)
check("missing file: …nothing was stored", mt(82).get("wait_kind") is None, mt(82))
AF.write_text("{}", encoding="utf-8")
item(83, subject="[home] wait_anchor is free text", needs=[BACK]); before83 = raw(83)
for label, val in (("free text", "the merge of the release PR"), ("an unparseable URL", "https://example.invalid/not/an/anchor"), ("a bare word", "slackish")):
    try:
        wait("a83", val); check(f"no shape: {label} is refused", False)
    except Exception as e:
        msg = str(e)
        check(f"no shape: {label} is refused", "Refused" in msg, msg)
        check(f"no shape: …the message says the anchor must be a link the anchors tool accepts", "not an anchor shape the anchors tool accepts" in msg and "GitHub issue/PR" in msg, msg)
        check(f"no shape: …and advises no anchors(add=...) call", "add=[" not in msg and "anchors(project=" not in msg, msg)
check("no shape: …nothing was stored", raw(83) == before83, mt(83))
refused("no shape: a create with free text is refused the same way",
        lambda: server._create(subject="[home] new anchor wait, free text", description=DESC, project="projects/alpha", owner=FRONT, next="team-back: do it", needs=[BACK],
                               wait_kind="anchor", wait_anchor="the release PR", wait_event="PR merged", ask_by=day(6), post_wake_mover=BACK, mover="none"),
        "not an anchor shape the anchors tool accepts")
anchors(projects_alpha=[])

# ================================================================ other kinds are not judged
anchors(projects_alpha=[])
item(70, subject="[home] time wait", needs=[BACK])
accepted("other kinds: a time wait is not judged", lambda: server._update("a70", sender=FRONT, wait_kind="time", hold=True, wake=day(3), post_wake_mover=BACK, mover="none"))
item(71, subject="[home] relay wait", needs=[BACK])
accepted("other kinds: a relay wait is not judged", lambda: server._update("a71", sender=FRONT, wait_kind="relay", wait_event="the countersigned NDA", ask_by=day(6), post_wake_mover=BACK, mover="none"))
item(72, subject="[home] item wait", needs=[BACK]); item(73, subject="[home] the blocker")
accepted("other kinds: an item wait is not judged", lambda: server._update("a72", sender=FRONT, wait_kind="item", after=["a73"], ask_by=day(6), post_wake_mover=BACK, mover="none"))
item(74, subject="[home] anchor wait standing on a scoped anchor, no wait_anchor", needs=[BACK])
anchors(projects_alpha=[entry(A2, ["a74"])])
accepted("other kinds: an anchor wait that names no wait_anchor (its anchor scoped to the item) is not judged", lambda: server._update("a74", sender=FRONT, wait_kind="anchor", wait_event="PR merged", ask_by=day(6), post_wake_mover=BACK, mover="none"))

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
