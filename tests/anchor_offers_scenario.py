"""Scenario test for the anchor offers (stackshot/service/anchor_offers.py) — fixture data, no live store, no network, no server socket.

A create or update reply that meets a moment where an anchor would catch the news an item waits on carries one `(anchor offer: …)` line with the ready `anchors` call; the answer of `post project` for a new page
carries one sentence of the same kind. An offer never refuses a write. Covered:

  * a relay wait with no anchor scoped to the item, set by a create or an update: the line says no anchor watches the thread and carries the call (project and item id filled in); the call carries the link of
    a thread the item's text holds, else a Gmail query on an address in it, else a placeholder for the thread; a different party offers again, an unchanged relay wait does not;
  * no relay offer when an anchor is scoped to the item, or when every link the item's text holds is watched already;
  * a source link (Slack, Gmail, Drive, Notion) in a description that no anchor watches for the item: a create, or an update whose description holds a link the old one did not; one call adds up to 3 links; a link already
    held project-wide on the item's page or scoped to it on any page, a pull request link and a link that is no anchor shape are not offered; the same update sent twice offers once;
  * at most one offer line to a reply (the relay offer first); none for a closed item;
  * a new project's page: one sentence naming the project's own key; none for a project made with no page;
  * `[anchors] offers = false` turns every offer off, live; a value that is not true or false reads as true and is named in the config notes;
  * every reply still starts as it always did and the item is stored: an offer is a note, never a refusal.

    tests/run-suite anchor_offers        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="ao3-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), gbrain=True)
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
for d in ("store/a", "store/g", "fleet/a", "state/ao3","brain/projects", "secrets", "transcripts/-scratch-t"): (T / d).mkdir(parents=True)
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
def item(i, status="open", project="projects/alpha", desc=DESC, **meta):
    su = now0 - 10 * DAY
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": desc, "status": status,
                                                       "updated": su, "state_updated": su, "confirmed": su,
                                                       "metadata": {"owner": U["home-front"], "project": project, "next": "team-back: do the thing", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server
from stackshot.service import update as _update_svc
from stackshot.service import projects as _psvc
from stackshot.service import anchor_offers as _offers
from stackshot.core import config as _cfg
from stackshot.anchors import anchors as _anc
from stackshot.github import ghsync as _gh
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import create as _wt_create
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda gid, owner, note, tag="wake": None
_cfg.CFG.setdefault("model", {}).update(guards=False, watchers=True, pause=False)       # the write guards have their own suite
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
BACK, FRONT = "team-back", "home-front"
SL1, SL2 = "https://example-team.slack.com/archives/C0AAAA1111/p1700000000000100", "https://example-team.slack.com/archives/C0BBBB2222"
GM1 = "https://mail.google.com/mail/u/0/#inbox/18c0ffee12345678"
DR1 = "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
NO1 = "https://www.notion.so/Some-page-0123456789abcdef0123456789abcdef"
PR1 = "https://github.com/example-org/example-repo/pull/7"
def anchors(**pages): _anc.save({k.replace("_", "/", 1): v for k, v in pages.items()})
def entry(url, items=None): return {"url": url, "items": items, "added": now0, "by": "x"}
OFFER = "(anchor offer:"
def count(s): return s.count(OFFER)
def create(subject, desc=DESC, **kw):
    return _wt_create._create(subject=f"[home] {subject}", description=desc, project="projects/alpha", owner=FRONT, next="team-back: do it", needs=[BACK], **kw)
def gid_of(reply): return re.search(r"created (\S+) —", reply).group(1)
def stored(g): return json.loads(next(T.glob(f"store/*/{re.sub(r'[^0-9]', '', g)}.json")).read_text())
def relay(gid, event="the countersigned NDA from the lawyer", **kw):
    return _update_svc._update(gid, sender=FRONT, wait_kind="relay", wait_event=event, ask_by=day(6), post_wake_mover=BACK, mover="none", **kw)
def call(gid, *adds, project="projects/alpha"):
    return f'anchors(project="{project}", add=[' + ", ".join(f'"{a}"' for a in adds) + f'], items=["{_gh.shown(gid)}"])'

# ================================================================ a relay wait, set by an update
item(60, needs=[BACK])
r = relay("a60")
check("relay update: the reply still starts as an update's does and the wait is stored (an offer is no refusal)", r.startswith("updated ") and rd(60)["metadata"].get("wait_kind") == "relay", r[:200])
check("relay update: one offer line, naming the item and that no anchor watches the thread", count(r) == 1 and _gh.shown("a60") in r.split(OFFER)[1] and "no anchor watches their thread" in r, r)
check("relay update: …with the ready call, the thread a placeholder", call("a60", "<their Slack thread or Drive file link, or gmail:q:from:<their address>>") in r, r)
r2 = _update_svc._update("a60", sender=FRONT, ask_by=day(9))
check("relay update: a later write that leaves the wait as it is offers nothing", count(r2) == 0, r2)
r3 = relay("a60", event="the lawyer's reply on the amendment")
check("relay update: a different party is offered again", count(r3) == 1 and "the lawyer's reply on the amendment" in r3, r3)

item(61, needs=[BACK])
r = relay("a61", event="Pat Example (pat@example.invalid) sends the signed form")
check("relay update: an address in the party's words becomes a Gmail query on it", count(r) == 1 and call("a61", "gmail:q:from:pat@example.invalid") in r, r)
LONG = "x" * 1001 + "@example.invalid"     # an address whose Gmail query the matcher refuses (a query is at most 1000 characters)
item(67, desc=DESC + f"\n- Contacts: {LONG}, kim@example.invalid", needs=[BACK])
r = relay("a67")
check("relay update: an address whose query the matcher refuses is passed over for the next one", count(r) == 1 and call("a67", "gmail:q:from:kim@example.invalid") in r and "x" * 50 not in r.split(OFFER)[1], r[-600:])
anchors(projects_alpha=[entry("gmail:q:from:kim@example.invalid")])
item(68, needs=[BACK])
r = relay("a68", event="Kim (kim@example.invalid) or Lee (lee@example.invalid)")
check("relay update: an address whose query is anchored already is passed over for the next one", count(r) == 1 and call("a68", "gmail:q:from:lee@example.invalid") in r and "kim@" not in r.split("To watch it:")[1], r[-600:])
item(69, needs=[BACK])
r = relay("a69", event="Kim (kim@example.invalid)")
check("relay update: …and with no other address, the placeholder stands", count(r) == 1 and "<their Slack thread or Drive file link" in r, r[-600:])
anchors()
item(77, desc=DESC + f"\n- {SL1}\n- {GM1}\n- {DR1}\n- {NO1}", needs=[BACK])
r = relay("a77")
check("relay update: at most 3 links go into the call", count(r) == 1 and call("a77", SL1, GM1, DR1) in r and NO1 not in r.split(OFFER)[1], r[-700:])
item(62, desc=DESC + f"\n- The thread: {SL1}.", needs=[BACK])
r = relay("a62")
check("relay update: a link the description holds is the call's anchor (trailing full stop cut)", count(r) == 1 and call("a62", SL1) in r, r)
anchors(projects_alpha=[entry(SL2)])
item(63, desc=DESC + f"\n- The thread: {SL2}", needs=[BACK])
r = relay("a63")
check("relay update: a thread that is anchored project-wide already is no offer", count(r) == 0, r)
anchors(projects_alpha=[entry(PR1, ["a64"])])
item(64, needs=[BACK])
r = relay("a64")
check("relay update: an anchor scoped to the item (on its page) is no offer", count(r) == 0, r)
anchors(projects_beta=[entry(PR1, ["a65"])])
item(65, needs=[BACK])
r = relay("a65")
check("relay update: …nor one scoped to it on another project's page", count(r) == 0, r)
anchors(projects_alpha=[entry(PR1)])
item(66, needs=[BACK])
r = relay("a66")
check("relay update: a project-wide anchor of its page is no thread of this item's party, so the offer stands", count(r) == 1, r)
anchors()

# ================================================================ a relay wait, set by a create
r = create("created with a relay wait", wait_kind="relay", wait_event="the signed form from Kim", ask_by=day(6), post_wake_mover=BACK, mover="none")
g = gid_of(r)
check("relay create: the reply starts as a create's and carries one offer line with the ready call", r.startswith("created ") and count(r) == 1 and call(g, "<their Slack thread or Drive file link, or gmail:q:from:<their address>>") in r, r)
check("relay create: …and the item is stored", stored(g)["metadata"].get("wait_kind") == "relay", stored(g)["metadata"])
r = create("created with no wait and no link")
check("relay create: an item with no relay wait and no source link is offered nothing", r.startswith("created ") and count(r) == 0, r)

# ================================================================ a source link in a description
r = create("one slack link", desc=DESC + f"\n- Thread: {SL1}")
g = gid_of(r)
check("link create: a Slack link no anchor watches is offered, with the ready call for this item", count(r) == 1 and call(g, SL1) in r and "Slack link" in r, r)
r = create("two links", desc=DESC + f"\n- Thread: {SL1}\n- Mail: {GM1}")
g = gid_of(r)
check("link create: two links are one call that adds both, scoped to the item", count(r) == 1 and call(g, SL1, GM1) in r and "Slack, Gmail links" in r, r)
r = create("four links", desc=DESC + f"\n- {SL1}\n- {GM1}\n- {DR1}\n- {NO1}")
g = gid_of(r)
check("link create: at most 3 links go into the call", count(r) == 1 and call(g, SL1, GM1, DR1) in r and NO1 not in r.split(OFFER)[1], r)
r = create("pull request link", desc=DESC + f"\n- Review: {PR1}\n- Notes: https://example.invalid/some/page")
check("link create: a pull request link and a link that is no anchor shape are not offered", count(r) == 0, r)
r = create("repository links", desc=DESC + "\n- Releases: https://github.com/example-org/example-repo/releases\n- Repo: https://github.com/example-org/example-repo")
check("link create: a repository's release or root link is no source link either (a GitHub anchor is never offered)", count(r) == 0, r)
anchors(projects_alpha=[entry(SL1)])
r = create("slack held project-wide", desc=DESC + f"\n- Thread: {SL2.replace('C0BBBB2222', 'C0AAAA1111')}")
check("link create: a link whose anchor the item's page holds project-wide is not offered (the channel is the anchor)", count(r) == 0, r)
anchors(projects_beta=[entry(GM1, ["a70"])])
item(70, desc=DESC + f"\n- Mail: {GM1}", needs=[BACK])
r = _update_svc._update("a70", sender=FRONT, subject="[home] item 70, renamed")
check("link update: a write that does not touch the description offers nothing, links or not", count(r) == 0, r)
anchors()
item(71, needs=[BACK])
r = _update_svc._update("a71", sender=FRONT, description=DESC + f"\n- The file: {DR1}")
check("link update: a description that gains a link is offered it, with the ready call", r.startswith("updated ") and count(r) == 1 and call("a71", DR1) in r and "Drive link" in r, r)
r = _update_svc._update("a71", sender=FRONT, description=DESC + f"\n- The file: {DR1}\n- More words")
check("link update: the same link sent again is not new, so no second offer", count(r) == 0, r)
r = _update_svc._update("a71", sender=FRONT, description=DESC + f"\n- The file: {DR1}\n- The page: {NO1}")
check("link update: a second, new link is offered alone", count(r) == 1 and call("a71", NO1) in r and DR1 not in r.split(OFFER)[1], r)
anchors(projects_beta=[entry(NO1, ["a72"])])
item(72, needs=[BACK])
r = _update_svc._update("a72", sender=FRONT, description=DESC + f"\n- The page: {NO1}")
check("link update: a link anchored on another page and scoped to the item is not offered", count(r) == 0, r)
anchors()

# ================================================================ one line a reply; a closed item
item(73, needs=[BACK])
r = relay("a73", description=DESC + f"\n- Thread: {SL1}")
check("one line: a relay wait and a new link in one write make one offer line, the relay's, naming the link", count(r) == 1 and "waits on" in r and call("a73", SL1) in r, r)
closed = {**rd(60), "status": "completed"}
check("closed: an item that is closed is offered nothing", _offers.item_line("a60", closed) == "" and _offers.item_line("a60", {**closed, "status": "open", "metadata": {**closed["metadata"], "project": ""}}) == "", None)
check("closed: an offer asked for no item id is none", _offers.item_line("", rd(60)) == "", None)

# ================================================================ a new project's page
class FakeIO:
    def __init__(s): s.pages = {}; s.creates = []
    def get(s, slug): return (s.pages[slug], "r1") if slug in s.pages else (None, None)
    def create(s, slug, content): s.creates.append(slug); s.pages[slug] = content; return "ok", "{}"
    def put(s, slug, content, rev): s.pages[slug] = content; return "ok", ""
    def add_timeline(s, slug, date, summary, detail, source, request_id=""): return ""
class RefusingIO(FakeIO):
    def create(s, slug, content): return "refused", "the store says no"
_psvc.PAGE_IO = FakeIO()
def mk(key, **kw): return _psvc._new_project("box-c", {"key": key, "scope": "home", "title": "T", "sender": "fleet-web", **kw})
st, out = mk("projects/fresh")
check("new project: made, and its note carries the offer naming the project's own key", st == 200 and out["page"]["state"] == "ok" and out["note"].count("Anchor offer:") == 1
      and 'anchors(project="projects/fresh", add=["https://github.com/<owner>/<repo>/releases", "<the project\'s Slack channel link>"])' in out["note"], (st, out.get("note")))
check("new project: …after the sentence that asks for the first agent", out["note"].index("Add the first agent") < out["note"].index("Anchor offer:"), out.get("note"))
_psvc.PAGE_IO = RefusingIO()
st, out = mk("projects/refused")
check("new project: a page the store refused is no project, so no offer either", st != 200 and "Anchor offer" not in json.dumps(out), (st, out))
_psvc.PAGE_IO = FakeIO()
_real_answer = _psvc._verbs.new_project_answer       # a shared brain's page is not made and the project is (state "retired"): the answer is a 200 whose page is not there
def _retired(*a, **k):
    status, answer = _real_answer(*a, **k); answer["page"]["state"] = "retired"; return status, answer
_psvc._verbs.new_project_answer = _retired
st, out = mk("projects/shared-page")
_psvc._verbs.new_project_answer = _real_answer
check("new project: a 200 whose page was not made is offered nothing (the anchors tool refuses a project with no page)", st == 200 and out["page"]["state"] == "retired" and "Anchor offer" not in out["note"], (st, out.get("note")))
check("new project: no key, no sentence", _offers.project_line("") == "" and _offers.project_line("projects/x").startswith(" Anchor offer:"), None)
st, out = _psvc._new_project("box-c", {"name": "Pageless", "scope": "home", "sender": "fleet-web"})
check("new project: a project made with no page is offered nothing (the anchors tool needs a page)", st == 200 and "Anchor offer" not in out["note"], (st, out.get("note")))

# ================================================================ the switch, live; a value that is no boolean
_cfg.CFG["anchors"] = {"offers": False}
item(74, needs=[BACK]); item(75, needs=[BACK])
r_up = relay("a74"); r_cr = create("switched off", desc=DESC + f"\n- Thread: {SL1}", wait_kind="relay", wait_event="Kim", ask_by=day(6), post_wake_mover=BACK, mover="none")
r_up2 = _update_svc._update("a75", sender=FRONT, description=DESC + f"\n- File: {DR1}")
st, out = mk("projects/switched-off")
check("off: [anchors] offers = false ends every offer: a relay update, a create, a link update and a new project", count(r_up) == 0 and count(r_cr) == 0 and count(r_up2) == 0 and "Anchor offer" not in out["note"]
      and not _offers.enabled() and r_cr.startswith("created ") and rd(74)["metadata"].get("wait_kind") == "relay", (r_up, r_cr, r_up2, out.get("note")))
check("off: no config note while the key is a boolean", not [n for n in _cfg.notes({**_cfg.CFG}) if n.startswith("[anchors]")], _cfg.notes({**_cfg.CFG}))
_cfg.CFG["anchors"] = {"offers": True}
item(76, needs=[BACK])
check("on: the same switch back on (live, no restart) offers again", count(relay("a76")) == 1 and _offers.enabled(), None)
for bad in ("no", 0, "false", [True]):
    _cfg.CFG["anchors"] = {"offers": bad}
    notes = [n for n in _cfg.notes({**_cfg.CFG}) if n.startswith("[anchors]")]
    check(f"malformed {bad!r}: reads as true (offers stay on) and the config notes name the key", _offers.enabled() is True and len(notes) == 1 and "offers" in notes[0] and "true or false" in notes[0], (notes, _offers.enabled()))
_cfg.CFG.pop("anchors", None)
check("no [anchors] table: offers are on, and the config notes say nothing", _offers.enabled() is True and not [n for n in _cfg.notes({**_cfg.CFG}) if n.startswith("[anchors]")], None)

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
