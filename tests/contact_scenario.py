"""Scenario test for: an item's contact, the front agent the person the board is for talks to about it — fixture data, no live store, no network.

Covers: create and update store `metadata.contact`; a front agent that creates an item is its contact; a background agent names one of the project's front agents or the contact is the
project's -main agent; any other name is refused with the project's front agents and their mandates (nothing is written); an update changes it with the same check; filing the item under
another project makes that project's -main agent the contact (unless the contact is a front agent there too, or contact is passed); a retired contact falls to the project's -main agent
and a renamed one is followed; get shows `contact:` (not the brief); the client JSON rows carry it; the backfill (dry run first, counts by rule, second run changes nothing);
the same through the retire and rename endpoints; a front agent of another project that created the item stays its contact; the item page through the routes; no notice is sent; the item page's side column: the Owner row right after Mover, the hover text as a title, the value linked to the fleet tool's view, no explanatory line, no row without a contact.

    tests/run-suite contact        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="contact-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's fleet store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects"): (T / d).mkdir(parents=True)
MAIN, SIDE, BUILD, REVIEW, ECHO, LONE = "home-delta-main", "home-delta-desk", "home-delta-builder", "home-delta-review", "home-echo-main", "home-golf-builder"
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate((MAIN, SIDE, BUILD, REVIEW, ECHO, LONE), 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
REG = {"pages": {
    "projects/delta": page(title="Delta", name="Delta", agents={MAIN: "talks to the owner about the delta project", SIDE: "answers questions at the side desk", BUILD: "builds it", REVIEW: "reviews it"},
                           back_agents={BUILD: "builds it", REVIEW: "reviews it"}),
    "projects/delta/sub": page(title="Delta sub", name="Delta sub", hub="projects/delta"),
    "projects/echo": page(title="Echo", name="Echo", agents={ECHO: "the echo front"}),
    "projects/golf": page(title="Golf", name="Golf", agents={LONE: "builds golf"}, back_agents={LONE: "builds golf"})}}
(T / "store/projects.json").write_text(json.dumps(REG))
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def rd(g):
    g = str(g); g = g if not g[:1].isdigit() else "a" + g
    return json.loads((T / f"store/{g[0]}/{g[1:]}.json").read_text())
def ct(g):
    c = rd(g)["metadata"].get("contact")
    return server._session_label(c) if c else ""
def bytes_of(g): return (T / f"store/a/{str(g)[1:]}.json").read_bytes()
now0 = time.time()
def put(i, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing\n- It lives here\n- Done when done", "status": status,
        "updated": now0 - 60, "state_updated": now0 - 60, "confirmed": now0 - 60, "metadata": {"owner": BUILD, "project": "projects/delta", **meta}}))

from stackshot.web import server
sh = server._gh.shown
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
told = []                                              # every notice the server would send: recorded, never sent
server._tell_woken = lambda *a, **k: told.append((a, k))
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
OWNER = server.OWNER

def refusal(fn):
    try:
        return fn() and ""
    except Exception as e:  # noqa: BLE001
        return str(e)
def made(r): return r.split()[1] if r.startswith("created") else ""
def mk(**kw):
    base = dict(subject="[home] a contact test", description=DESC, project="projects/delta", sender=BUILD, mover=BUILD, next=f"{BUILD}: build it")
    base.update(kw)
    return server.stackshot_create(**base)

# ---- create: who is the contact
r = mk(sender=MAIN, mover=MAIN, next=f"{MAIN}: carry on")
check("create by a front agent: the creator is the contact", ct(made(r)) == MAIN, r)
r = mk(sender=SIDE, mover=SIDE, next=f"{SIDE}: carry on")
check("create by another front agent (not -main): that agent is the contact", ct(made(r)) == SIDE, r)
r = mk()
check("create by a background agent naming nobody: the project's -main agent", ct(made(r)) == MAIN, r)
r = mk(contact=SIDE)
check("create by a background agent naming a front agent of the project: that agent", ct(made(r)) == SIDE, r)
r = mk(contact=SIDE.upper())
check("create: the name is matched case-folded", ct(made(r)) == SIDE, r)
r = mk(sender=MAIN, mover=MAIN, next=f"{MAIN}: carry on", contact=SIDE)
check("create by a front agent that names another front agent of the project: the named one", ct(made(r)) == SIDE, r)
cid = made(mk(contact=SIDE))
check("create: the reply carries a contact line", f"contact: {SIDE}" in server.stackshot_get(item_id=cid), server.stackshot_get(item_id=cid)[:600])

# ---- create: refusals list the project's front agents with their mandates, and write nothing
nxt = int((T / "store/next-id").read_text())
for what, name in (("a background agent of the project", REVIEW), ("the creator itself, a background agent", BUILD), ("a front agent of another project", ECHO),
                   ("a name no page lists", "home-delta-nobody"), ("the owner himself", OWNER), ("none", "none")):
    msg = refusal(lambda: mk(contact=name))
    check(f"create: contact={what} is refused and lists the front agents with their mandates",
          msg.startswith("Refused:") and "projects/delta" in msg and f"{MAIN} (talks to the owner about the delta project)" in msg and f"{SIDE} (answers questions at the side desk)" in msg
          and "(builds it)" not in msg and "(reviews it)" not in msg, msg)
check("create: a refused create writes no item and takes no id", int((T / "store/next-id").read_text()) == nxt and not (T / f"store/a/{nxt}.json").exists(), sorted(os.listdir(T / "store/a"))[-3:])
msg = refusal(lambda: mk(project="projects/golf", sender=LONE, mover=LONE, next=f"{LONE}: build it", contact="home-golf-other"))
check("create: a project that lists no front agent says so", msg.startswith("Refused:") and "lists none of its own" in msg, msg)
r = mk(project="projects/golf", sender=LONE, mover=LONE, next=f"{LONE}: build it")
check("create: a project with no front agent and no -main agent leaves the item without a contact", r.startswith("created") and "contact" not in rd(made(r))["metadata"], r)

# ---- update
put(1, contact=MAIN)
mv0 = rd(1)["metadata"].get("mover"); told.clear()
r = server.stackshot_update(item_id="a1", sender=BUILD, contact=SIDE)
m1 = rd(1)["metadata"]
check("update: contact changes the contact", "Refused" not in r and m1.get("contact") == SIDE and f"contact: {SIDE}" in r, r)
check("update: contact is a filing field (no state clock moved, no session named in needs, no mover change)", rd(1)["state_updated"] == now0 - 60 and not m1.get("needs") and m1.get("mover") == mv0, m1)
check("update: setting the contact sends no notice", told == [], told)
check("update: …and it is the one field that moved `updated`, as any update does", rd(1)["updated"] > now0 - 60, rd(1)["updated"])
before = bytes_of("a1")
msg = refusal(lambda: server.stackshot_update(item_id="a1", sender=BUILD, contact=REVIEW))
check("update: a background agent as contact is refused with the list, and the item is untouched", msg.startswith("Refused:") and MAIN in msg and SIDE in msg and bytes_of("a1") == before, msg)
msg = refusal(lambda: server.stackshot_update(item_id="a1", sender=BUILD, priority="p1", contact=REVIEW))
check("update: a bad contact beside another field (priority) refuses the whole write: nothing is written", msg.startswith("Refused:") and bytes_of("a1") == before and rd(1)["metadata"].get("priority") != "p1", msg)
msg = refusal(lambda: server.stackshot_update(item_id="a1", sender=BUILD, contact=ECHO))
check("update: a front agent of another project is refused", msg.startswith("Refused:") and "projects/delta" in msg, msg)
put(2, status="completed", contact=SIDE, outcome="done", reason="done")
before = bytes_of("a2")
msg = refusal(lambda: server.stackshot_update(item_id="a2", sender=BUILD, contact=MAIN))
check("update: a completed item keeps its contact as its record", msg.startswith("Refused:") and "reopen" in msg and bytes_of("a2") == before, msg)

# ---- the project changes
put(3, contact=SIDE)
r = server.stackshot_update(item_id="a3", sender=BUILD, project="projects/echo")
check("project move: the contact falls to the new project's -main agent", "Refused" not in r and ct(3) == ECHO and rd(3)["metadata"]["project"] == "projects/echo", r)
r = server.stackshot_update(item_id="a3", sender=BUILD, project="projects/delta", contact=SIDE)
check("project move with contact passed: the contact is checked against the new project and kept", "Refused" not in r and ct(3) == SIDE, r)
msg = refusal(lambda: server.stackshot_update(item_id="a3", sender=BUILD, project="projects/echo", contact=REVIEW))
check("project move with a contact that is no front agent anywhere: refused, item untouched", msg.startswith("Refused:") and rd(3)["metadata"]["project"] == "projects/delta", msg)
msg = refusal(lambda: server.stackshot_update(item_id="a3", sender=BUILD, project="projects/echo", contact=ECHO.upper()))
check("project move naming the new project's front agent: accepted", msg == "" and ct(3) == ECHO and rd(3)["metadata"]["project"] == "projects/echo", msg)
msg = refusal(lambda: server.stackshot_update(item_id="a3", sender=BUILD, project="projects/delta", contact=SIDE))
check("…and back to the first project with its front agent again", msg == "" and ct(3) == SIDE, msg)
r = server.stackshot_update(item_id="a3", sender=BUILD, project="projects/delta/sub")
check("project move to a page of the same project (a sub-page): a contact that is a front agent there stays", "Refused" not in r and ct(3) == SIDE, r)
# a front agent of another project made the item: it stays the contact wherever the item is filed, and can be set back to
r = mk(sender=ECHO, mover=ECHO, next=f"{ECHO}: carry on")
check("cross-project: a front agent of another project that creates an item is its contact", ct(made(r)) == ECHO, r)
xid = made(r)
r = server.stackshot_update(item_id=xid, sender=BUILD, contact=SIDE)
check("cross-project: the contact can be changed to a front agent of the item's project", "Refused" not in r and ct(xid) == SIDE, r)
msg = refusal(lambda: server.stackshot_update(item_id=xid, sender=BUILD, contact=ECHO))
check("cross-project: …and set back to the creator, a front agent of another project", msg == "" and ct(xid) == ECHO, msg)
msg = refusal(lambda: server.stackshot_update(item_id=xid, sender=BUILD, contact="home-golf-builder"))
check("cross-project: …but a background agent of another project is still refused", msg.startswith("Refused:"), msg)
r = server.stackshot_update(item_id=xid, sender=BUILD, project="projects/delta/sub")
check("cross-project: the item re-filed under another project keeps its creator as the contact", "Refused" not in r and ct(xid) == ECHO, r)
r = mk(sender=ECHO, mover=ECHO, next=f"{ECHO}: carry on", contact=ECHO)
check("cross-project: a creator naming itself in contact= is accepted", ct(made(r)) == ECHO, r)
put(4)                                                  # an item made before the field: no contact at all
r = server.stackshot_update(item_id="a4", sender=BUILD, project="projects/echo")
check("project move of an item with no contact: it gets the new project's -main agent", ct(4) == ECHO, r)
put(5, contact=SIDE)
r = server.stackshot_update(item_id="a5", sender=BUILD, project="projects/golf")
check("project move to a project with no -main agent: the contact is dropped", "Refused" not in r and "contact" not in rd(5)["metadata"], r)
put(6, contact=SIDE)
r = server.stackshot_update(item_id="a6", sender=BUILD, priority="p2")
check("an update that does not re-file the item leaves the contact", ct(6) == SIDE, r)

# ---- the contact retires, or is renamed
for p_ in (T / "store").glob("?/*.json"): p_.unlink()
put(7, contact=SIDE); put(8, contact=SIDE, project="projects/delta/sub"); put(9, status="completed", contact=SIDE, outcome="done", reason="done"); put(10, contact=MAIN)
moved = server._contact_fall_retired(SIDE)
check("retire: an open item whose contact retired falls to its project's -main agent", ct(7) == MAIN and ct(8) == MAIN, (rd(7)["metadata"], rd(8)["metadata"]))
check("retire: the answer names the items changed; a closed item and another contact are left", sorted(moved) == [sh("a7"), sh("a8")] and ct(9) == SIDE and ct(10) == MAIN, moved)
check("retire: it is a filing write (no clock moved)", rd(7)["state_updated"] == now0 - 60 and rd(7)["updated"] == now0 - 60, rd(7))
put(11, contact=MAIN)
moved = server._contact_fall_retired(MAIN)
check("retire of the -main agent itself: the next front agent of the page (the page is read without it)", ct(11) == SIDE, rd(11)["metadata"])
check("retire: the endpoint's answer gains contact_moved only when items moved", server._contact_after_agent((200, {"result": "line removed"}), "retire", "nobody-here") == (200, {"result": "line removed"})
      and server._contact_after_agent((409, {"error": "x"}), "retire", SIDE) == (409, {"error": "x"}))
put(12, contact=SIDE)
st, body = server._contact_after_agent((200, {"result": "line removed"}), "retire", SIDE)
check("retire: contact_moved lists the items", st == 200 and sh("a12") in body.get("contact_moved", []) and ct(12) == MAIN, (st, body))
put(13, contact="home-delta-oldname")
moved = server._contact_follow_rename("home-delta-oldname", SIDE)
check("rename: a contact stored as the old plain name is followed to the new name", moved == [sh("a13")] and ct(13) == SIDE, (moved, rd(13)["metadata"]))
put(14, status="completed", contact="home-delta-oldname", outcome="done", reason="done")
check("rename: a closed item is left", server._contact_follow_rename("home-delta-oldname", SIDE) == [] and rd(14)["metadata"].get("contact") == "home-delta-oldname")

# ---- the same through the two endpoints (sala's retire and rename of a session, which edit the project's page)
class PageIO:
    """A fake gbrain page store with revisions: get(slug) -> (text, "r<n>"), put(slug, text, rev) -> (state, note), add_timeline(...) -> "" when added."""
    def __init__(s, pages): s.pages = dict(pages); s.revs = {k: 1 for k in pages}; s.timeline = []
    def add_timeline(s, slug, date, summary, detail, source, request_id=""): s.timeline.append((slug, summary)); return ""
    def get(s, slug): return (s.pages[slug], f"r{s.revs[slug]}") if slug in s.pages else (None, None)
    def put(s, slug, text, rev):
        if rev != f"r{s.revs[slug]}": return "refused", "stale revision"
        s.pages[slug] = text; s.revs[slug] += 1; return "ok", "{}"
DELTA_PAGE = (f"---\ntype: project\ntitle: Delta\norg: home\ndisplay-name: home-delta\nagents:\n  {MAIN}: talks to the owner about the delta project\n  {SIDE}: answers questions at the side desk\n"
              f"  background:\n    {BUILD}: builds it\n    {REVIEW}: reviews it\nstatus: active\n---\n# Delta\n")
server.PAGE_IO = PageIO({"projects/delta": DELTA_PAGE})
server._cfg.CFG["project_agent"] = {"form_senders": ["fleet-web", "sala-retire"], "form_machines": ["box-a"]}
for p_ in (T / "store").glob("?/*.json"): p_.unlink()
put(50, contact=SIDE); put(51, contact=SIDE, project="projects/delta/sub"); put(52, contact=MAIN); put(53, status="completed", contact=SIDE, outcome="done", reason="done")
told.clear()
st, out = server._client_post("box-a", "project-agent-retire", {"project": "projects/delta", "name": SIDE, "sender": "sala-retire"})
check("endpoint retire: the page's line is removed (200) and the answer lists the items whose contact fell", st == 200 and out.get("result") == "line removed" and sorted(out.get("contact_moved", [])) == [sh("a50"), sh("a51")], (st, out))
check("endpoint retire: …to the project's -main agent; another contact and a closed item stay", ct(50) == MAIN and ct(51) == MAIN and ct(52) == MAIN and ct(53) == SIDE and SIDE not in server.PAGE_IO.pages["projects/delta"], (rd(50)["metadata"], rd(53)["metadata"]))
check("endpoint retire: nobody is told, and the filing write keeps both clocks", told == [] and rd(50)["state_updated"] == now0 - 60 and rd(50)["updated"] == now0 - 60, (told, rd(50)))
put(54, contact=MAIN)
st, out = server._client_post("box-a", "project-agent-rename", {"project": "projects/delta", "old": MAIN, "new": "delta-lead", "sender": "fleet-web"})
check("endpoint rename: the page's key is renamed (200) and the answer lists the items that followed", st == 200 and out.get("result") == "renamed" and sh("a54") in out.get("contact_moved", []), (st, out))
check("endpoint rename: the contact stored as the old plain name is the new name; nobody is told", rd(54)["metadata"]["contact"] == "delta-lead" and told == [], (rd(54)["metadata"], told))
st, out = server._client_post("box-a", "project-agent-retire", {"project": "projects/delta", "name": "home-delta-nobody", "sender": "sala-retire"})
check("endpoint retire: a name on no page → 200 'not listed', no contact_moved in the answer", st == 200 and out.get("result") == "not listed" and "contact_moved" not in out, (st, out))
server.PAGE_IO = None
(T / "store" / "project-record.json").unlink(missing_ok=True)       # the endpoints above wrote the RECORD (an entry for projects/delta made from the page, then its renamed agents); the sections below read the REG fixture, so the record goes with the fake page

# ---- reading: a stored contact that is no front agent any more reads as the project's -main agent; get shows the line, the brief does not
put(15, contact="home-delta-gone")
g = server.stackshot_get(item_id="a15")
check("get: a stored contact that no page lists reads as the project's -main agent", f"contact: {MAIN}" in g and "home-delta-gone" not in g, g[:500])
put(16)
check("get: an item with no stored contact shows the project's -main agent", f"contact: {MAIN}" in server.stackshot_get(item_id="a16"))
put(17, status="completed", contact=SIDE, outcome="done", reason="done")
check("get: a closed item shows the contact it had", f"contact: {SIDE}" in server.stackshot_get(item_id="a17"))
check("brief: the line is left out (the brief loads into every session)", "contact:" not in server._fmt(server._load("a15"), brief=True))
st, _t, body = server._client_item_facts("some-session", "a15,a17")
facts = json.loads(body)["items"]
check("client JSON: item-facts carries the contact", st == 200 and facts["a15"]["contact"] == MAIN and facts["a17"]["contact"] == SIDE, facts)

# ---- the backfill
for p in (T / "store").glob("?/*.json"): p.unlink()
put(20, owner=SIDE)                                     # created by a front agent, no contact
put(21, owner=BUILD)                                    # created by a background agent
put(22, owner=BUILD, contact=SIDE)                      # has a live contact
put(23, owner=BUILD, contact="home-delta-gone")         # its contact is no front agent any more
put(24, owner=SIDE, status="completed", outcome="done", reason="done")   # closed: a record
put(25, owner=BUILD, project="projects/golf")           # a project with no -main agent
put(26, owner=ECHO, project="projects/delta")           # created by a front agent of another project
snap = {i: bytes_of(f"a{i}") for i in range(20, 27)}
out = server._contact_backfill(dry=True)
check("backfill dry run: counts by rule", out["counts"] == {"creator_front": 2, "main": 1, "retired_contact": 1, "has_contact": 1, "no_main": 1, "closed": 1} and out["dry_run"] is True and out["written"] == 0, out["counts"])
check("backfill dry run: writes nothing", all(bytes_of(f"a{i}") == snap[i] for i in range(20, 27)))
rows = {r["item"]: r for r in out["items"]}
check("backfill dry run: one row per item that would change, naming the rule and the contact",
      rows[sh("a20")]["rule"] == "creator_front" and rows[sh("a20")]["to"] == SIDE and rows[sh("a21")]["to"] == MAIN and rows[sh("a23")]["rule"] == "retired_contact" and rows[sh("a23")]["to"] == MAIN
      and rows[sh("a26")]["rule"] == "creator_front" and rows[sh("a26")]["to"] == ECHO and sh("a22") not in rows and sh("a24") not in rows, rows)
out = server._contact_backfill(dry=False)
check("backfill: written", out["written"] == 4 and ct(20) == SIDE and ct(21) == MAIN and ct(22) == SIDE
      and ct(23) == MAIN and ct(26) == ECHO and "contact" not in rd(25)["metadata"] and "contact" not in rd(24)["metadata"], out)
check("backfill: a filing write (clocks, status and the rest stay)", rd(20)["state_updated"] == now0 - 60 and rd(20)["updated"] == now0 - 60 and rd(20)["status"] == "open")
snap2 = {i: bytes_of(f"a{i}") for i in range(20, 27)}
out = server._contact_backfill(dry=False)
check("backfill: a second run writes nothing", out["written"] == 0 and all(bytes_of(f"a{i}") == snap2[i] for i in range(20, 27)) and out["counts"]["has_contact"] == 5, out["counts"])

# ---- the item page: the side column's second row, "Owner" (the Mover row is the first)
from stackshot.web.ui import render as r2
for p in (T / "store").glob("?/*.json"): p.unlink()
put(30, contact=SIDE); put(31); put(32, contact="home-delta-gone"); put(33, status="completed", contact=SIDE, outcome="done", reason="done")
server._cfg.CFG["client"]["session_view"] = "https://sala.example.org/#s={name}"; server._cfg.CFG.setdefault("fleet", {})["tool_name"] = "sala"
def side_of(h): return h.split('<aside class="iside"', 1)[1].split("</aside>", 1)[0]
def board(): return r2.Board(str(T / "store"))
def dts_of(h): return [re.sub(r"<[^>]+>", "", d) for d in re.findall(r"<dt>(.*?)</dt>", side_of(h))]
TIP = "the front agent to talk to about this item"
s30 = side_of(board().item_html("a30", answer=None, watch=None))
dts = re.findall(r"<dt>(.*?)</dt>", s30)
check("item page: the Owner row is the side column's second row, right after Mover and above Creator and Project", len(dts) > 3 and dts[0] == "Mover" and dts[1].startswith("<span") and re.sub(r"<[^>]+>", "", dts[1]) == "Owner" and [re.sub(r"<[^>]+>", "", d) for d in dts][2:4] == ["Creator", "Project"], dts)
check("item page: the label carries the hover text as a title", f'<dt><span title="{TIP}">Owner</span></dt>' in s30, s30[:400])
check("item page: the value is the contact's session name linked to sala", f'<a href="https://sala.example.org/#s={SIDE}"' in s30 and f">{SIDE} ↗</a>" in s30, s30[:600])
grp0 = re.search(r"<dt><span title=\"[^\"]*\">Owner</span></dt><dd>.*?</dd>", s30, re.S).group(0)      # the Owner row alone (the Mover row above it carries the machine in a dim span)
check("item page: no explanatory line under the row (the text is only the title)", grp0.count(TIP) == 1 and "<p" not in grp0 and 'class="dim"' not in grp0 and s30.count(TIP) == 1, grp0)
s31 = side_of(board().item_html("a31", answer=None, watch=None))
check("item page: an item with no contact shows no Owner row (the Creator row follows Mover)", "Owner" not in s31 and TIP not in s31 and [re.sub(r"<[^>]+>", "", x) for x in re.findall(r"<dt>(.*?)</dt>", s31)[:3]] == ["Mover", "Creator", "Project"], re.findall(r"<dt>(.*?)</dt>", s31)[:3])
s32 = side_of(board().item_html("a32", answer=None, watch=None, contact=MAIN))
check("item page: the contact the server passes (the derived one) is the row's value", f"#s={MAIN}" in s32 and "home-delta-gone" not in s32, s32[:500])
check("item page: an empty contact from the server (nobody to name) draws no row", "Owner" not in side_of(board().item_html("a32", answer=None, watch=None, contact="")))
check("item page: a closed item shows the contact it had", f"#s={SIDE}" in side_of(board().item_html("a33", answer=None, watch=None)))
server._cfg.CFG["client"]["session_view"] = ""
check("item page: with no fleet tool set the name is plain text", f">{SIDE}</dd>" in side_of(board().item_html("a30", answer=None, watch=None)) and "#s=" not in side_of(board().item_html("a30", answer=None, watch=None)))
server._cfg.CFG["client"]["session_view"] = "https://sala.example.org/#s={name}"
g_ = board().item_html("a30", answer=None, watch=None, contact="home-delta-nopane")
check("item page: a contact whose session has no live pane is plain text, as every session on the page (no link)", "<dd>home-delta-nopane</dd>" in side_of(g_) and "#s=home-delta-nopane" not in g_, side_of(g_)[:400])
# the routes: the item page through the server, whichever renderer draws it
from starlette.testclient import TestClient
with TestClient(server.mcp.http_app(), base_url="http://localhost") as c:
    ra32, ra31 = c.get("/items/a32"), c.get("/items/a31")
    check("route: /items/<n> answers 200 with the Owner row, the derived contact (a stored one that is no front agent any more reads as the project's -main agent)",
          ra32.status_code == 200 and dts_of(ra32.text)[:3] == ["Mover", "Owner", "Creator"] and f"#s={MAIN}" in side_of(ra32.text) and "home-delta-gone" not in side_of(ra32.text), (ra32.status_code, dts_of(ra32.text)[:3]))
    check("route: an item with no contact (a31 stores none; its project has a -main agent) shows the -main agent as its Owner", ra31.status_code == 200 and f"#s={MAIN}" in side_of(ra31.text), ra31.status_code)
server._cfg.CFG["client"]["session_view"] = ""; server._cfg.CFG["fleet"]["tool_name"] = ""

# ---- the tool text says it
snap_s = json.dumps(json.loads(pathlib.Path(SCR, "tool_text.snapshot.json").read_text(encoding="utf-8")))
check("tool text: create and update carry the contact parameter and its rule (snapshot)", snap_s.count('"contact": {') >= 2 and snap_s.count("any other name is refused, and the refusal lists the project's front agents with their mandates") >= 2, snap_s[:200])
check("tool text: get names the contact line", "`contact:`" in snap_s)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
