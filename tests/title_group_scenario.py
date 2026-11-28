"""Scenario test for one group per item, from its project, with no title tag: the write side (create, update), the title_label strip, and every place a title is shown — fixture data, a scratch store, no network, no server.

An item's group (work, home, ops: the scope of the board row its page rolls up to) is read from its project, never from a tag typed at the start of its title. Covers:

  1  the write       a create or an update without a tag is accepted and stored as written, no tag is added, none is asked for (no "subject-prefix" fix, no refusal for a missing or an unknown tag); a title that
                     still carries a tag is stored as written, not refused, not stacked; a long title without a tag is cut at a word like any other, the limit text names no tag
  2  title_label     `bare` hides every leading tag of the instance's list (and of the scopes' names), only at the start, never a title that is nothing but a tag, never changes what is stored
  3  the item page   its title and its page title are shown without the tag, the group row names the project's group once (never the tag's word), a closed item's stored title is kept as it was and shown without it, the
                     History's created and renamed lines show it without the tag
  4  the lists       home's row, the project page's header and the text digest and markdown show the group from the project once and the title without the tag; a title without a tag shows the same group
  5  the reads        the get tool's first line and the brief's waiting lines carry the same group and the same bare title; the client reads keep the stored subject and the group

    tests/run-suite title_group        -> exit 0 / 1"""
import contextlib, json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="titlegroup-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=str(T)); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/s1", "brain/projects", "brain/infra"): (T / d).mkdir(parents=True)
NAMES = ("falcon-main", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/dsl.md", "type: project\ntitle: Dsl\norg: work\nagents:\n  falcon-main: builds it\nstatus: active")      # a project of the work group
page("projects/hmp.md", "type: project\ntitle: Hmp\norg: home\nagents:\n  falcon-main: builds it\nstatus: active")     # a project of the home group
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
from stackshot.service import update as _update_svc
from stackshot.service import store as _service_store
from stackshot.core import config as _cfg
from stackshot.core import call_log as CL
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.model import ids as _model_ids
from stackshot.model import field_gates as _fg
from stackshot.model import title_label as TL
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import update as _wt_update
from stackshot.web.tools import get as _wt_get
from fastmcp.exceptions import ToolError
_cfg.CFG.setdefault("model", {})["guards"] = False      # fixture owners the fleet does not know; the write guards have their own suite
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""

MAIN = "falcon-main"; WORK, HOME = "projects/dsl", "projects/hmp"
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
NOW = time.time()
def item(i, subject, project, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": DESC, "status": status, "updated": NOW - 3600, "state_updated": NOW - 3600, "confirmed": NOW - 3600,
                                                     "metadata": {"owner": U[MAIN], "project": project, "needs": [MAIN], "next": "falcon-main: build it", **meta}}))
def rd(i): return _service_store._load(i) if isinstance(i, str) and not i.isdigit() else json.loads((T / f"store/a/{i}.json").read_text())
def fx(fn):
    tok = CL.begin()
    try: res = fn()
    except ToolError as e: res = e
    finally: made = CL.end(tok)
    return res, made
kinds = lambda made: [k for k, _ in made]
def create(subject, project=WORK, **kw):
    kw.setdefault("next", f"{MAIN}: carry on")
    return fx(lambda: _wt_create.stackshot_create(subject=subject, description=DESC, project=project, owner=MAIN, **kw))
def upd(i, **kw): return fx(lambda: _wt_update.stackshot_update(f"a{i}", sender=kw.pop("sender", MAIN), **kw))
def gid_of(res): return _model_ids._norm_id(res.split()[1]) if isinstance(res, str) else ""
strip = lambda h: re.sub(r"<[^>]+>", " ", h)

# ================================================================ 1. the write: no tag asked for, none added
res, made = create("Make the export finish in a minute")
g1 = gid_of(res)
check("1 a create with no tag is accepted", not isinstance(res, ToolError) and g1, res)
check("1 …stored as written, no tag put before it", rd(g1)["subject"] == "Make the export finish in a minute", rd(g1)["subject"] if g1 else res)
check("1 …and no fix is counted for a tag", "subject-prefix" not in kinds(made), made)
res, made = create("[home] Keep the old tag on this one")
g2 = gid_of(res)
check("1 a create whose title still opens with a tag of the list is accepted, stored as written, not stacked with another", not isinstance(res, ToolError) and rd(g2)["subject"] == "[home] Keep the old tag on this one" and "subject-prefix" not in kinds(made), (res, rd(g2)["subject"] if g2 else ""))
res, made = create("[mine] A tag that is in no list")
check("1 a title that opens with a tag of no list is no refusal either", not isinstance(res, ToolError) and rd(gid_of(res))["subject"] == "[mine] A tag that is in no list", res)
res, made = create("topic: a word and a colon")
check("1 …nor one that opens with a word and a colon", not isinstance(res, ToolError), res)
item(1, "Old title no tag", WORK)
res, made = upd(1, subject="Renamed with no tag")
check("1 an update that sets a title with no tag is accepted and stores it as written", not isinstance(res, ToolError) and rd(1)["subject"] == "Renamed with no tag", (res, rd(1)["subject"]))
res, made = upd(1, subject="[work] Renamed with an old tag")
check("1 an update that sets a title with an old tag is accepted and stores it as written", not isinstance(res, ToolError) and rd(1)["subject"] == "[work] Renamed with an old tag", (res, rd(1)["subject"]))
LONG = " ".join(["finishing"] * 12)
res, made = create(LONG)
gl = gid_of(res)
check("1 a long title with no tag is cut at a word, with an ellipsis, within the limit", gl and len(rd(gl)["subject"]) <= 80 and rd(gl)["subject"].endswith(" …") and kinds(made).count("subject-cut") == 1, (rd(gl)["subject"] if gl else res, made))
res, made = create("w" * 90)
check("1 a title with no word that fits is refused for its length; the text names no tag", isinstance(res, ToolError) and "limit is 80" in str(res) and "prefix" not in str(res), res)
check("1 the form gate has no tag rule: subject_faults of a bare title is empty, and a long one has only the length fault", _fg.subject_faults("A title with no tag") == [] and len(_fg.subject_faults("x" * 90)) == 1)

# ------- a title that is empty once any tag is taken off is refused, not stored (removing the tag rule must not open the door to a blank title)
for bad_subj in ("", "   ", "\n\n", "[work]", "[work] ", "[work]   "):
    check(f"1 subject_faults refuses {bad_subj!r} (empty once bared)", _fg.subject_faults(bad_subj) and "empty" in _fg.subject_faults(bad_subj)[0], _fg.subject_faults(bad_subj))
res, made = create("")
check("1 a create with an empty subject is refused, not filed as a blank title", isinstance(res, ToolError) and "empty" in str(res), res)
res, made = create("   ")
check("1 a create with a whitespace-only subject is refused", isinstance(res, ToolError) and "empty" in str(res), res)
res, made = create("\n\n")
check("1 a create with a newline-only subject is refused", isinstance(res, ToolError) and "empty" in str(res), res)
res, made = create("[work]")
check("1 a create whose subject is only a tag (no space, nothing after) is refused, not stored as a blank title", isinstance(res, ToolError) and "empty" in str(res), res)
item(2, "Old title no tag", WORK)
res, made = upd(2, subject="   ")
check("2 an update that sets a whitespace-only subject is refused, the stored title untouched", isinstance(res, ToolError) and "empty" in str(res) and rd(2)["subject"] == "Old title no tag", (res, rd(2)["subject"]))
check("1 subject_faults exempts the stored subject itself: a write that sends back the very text it already has is not a new change, even one that is empty once bared (a record from before this rule, kept as it was)",
      _fg.subject_faults("[work]", current="[work]") == [] and _fg.subject_faults("[work]", current="something else") != [] and _fg.subject_faults("[work] ", current="[work] ") == [])

# ================================================================ 2. title_label.bare
check("2 a leading tag of the list is hidden", TL.bare("[work] Fix the export") == "Fix the export" and TL.bare("[home] Fix") == "Fix")
check("2 the scopes' names are tags too, and several stacked ones go", TL.bare("[ops] Fix the box") == "Fix the box" and TL.bare("[work] [home] Fix twice") == "Fix twice")
check("2 only at the start: a bracket word inside the title, or one with no space after it, stays", TL.bare("Fix [work] later") == "Fix [work] later" and TL.bare("[work]-style fix") == "[work]-style fix")
check("2 a title that is only a tag is shown as stored, never empty", TL.bare("[work] ") == "[work] " and TL.bare("") == "" and TL.bare(None) == "")
check("2 a tag with leading whitespace before it is hidden too (a title stored '  [work] Fix', a space ahead of the tag)", TL.bare("  [work] Fix") == "Fix" and TL.bare("\t[home]  Fix twice") == "Fix twice")
check("2 adjacent stacked tags with no space between them come off too, one at a time", TL.bare("[work][home] Fix") == "Fix" and TL.bare("[WORK][Home]Fix") == "Fix")
check("2 adjacent stacked tags with nothing after the last one: shown as stored (the whole original), not a partly-stripped remainder", TL.bare("[work][home]") == "[work][home]" and TL.bare("[work][home]", or_blank=True) == "")
_subj_cfg = _cfg.CFG.setdefault("subject", {}); _had_prefixes = "prefixes" in _subj_cfg; _prefixes_old = _subj_cfg.get("prefixes")
try:
    _subj_cfg["prefixes"] = ["WIP "]
    check("2 a bracketless configured prefix only comes off with real whitespace (or the end of the string) after it: it does not match inside an ordinary word that starts with the same letters",
          TL.bare("Wipe the report") == "Wipe the report" and TL.bare("WIP Fix the report") == "Fix the report" and TL.bare("WIPFix") == "WIPFix")
finally:
    if _had_prefixes: _subj_cfg["prefixes"] = _prefixes_old
    else: _subj_cfg.pop("prefixes", None)
check("2 no tag, no change", TL.bare("Make X work") == "Make X work")

# ================================================================ 3. the item page
from stackshot.web.ui import render as ui_render
item(10, "[home] Fix the export", WORK)                    # a tag that says home on a project that is work: the group is work
item(11, "Fix the report", HOME)
item(12, "[work] Closed with an old tag", WORK, status="completed", needs=[], next="", outcome="done", close_reason="shipped it", outcome_text="- shipped")
item(13, "[work] Hold a question", WORK, needs=["decision"], ask="Decide: ship it? · Recommend: yes · Stakes: low · By: Fri", next="Oliver: answer the ask")
import datetime
item(14, "[work] Waits on the vendor", WORK, needs=["falcon-main"], wait_kind="relay", wait_event="the vendor reply", ask_by=(datetime.date.today() + datetime.timedelta(days=5)).isoformat(), post_wake_mover=MAIN)
bd = ui_render.Board(f"{tmp}/store")
h10, h11, h12 = (bd.item_html(f"a{i}") for i in (10, 11, 12))
def side(h): return strip(h[h.find('<aside class="iside"'):h.find("</aside>")])
def grp_rows(h): return re.findall(r"<dt>Group</dt><dd>(.*?)</dd>", h)
def proj_rows(h): return re.findall(r"<dt>Project</dt><dd>(.*?)</dd>", h)
check("3 the page title and the h1 show the title without the tag", '<h1><span class="hid">a10</span> Fix the export</h1>' in h10 and "<title>a10 · Fix the export</title>" in h10 and "[home]" not in h10.split("<aside")[0], h10[:700])
check("3 the group row names the project's group once, from the project (work), not the tag's word (home): here the Project row already carries it (dsl has a page, on a multi-scope instance), so the sidebar's own Group row is left out — the group is read once, not twice",
      grp_rows(h10) == [] and any("work" in r_ for r_ in proj_rows(h10)) and h10.count("<dt>Group</dt>") == 0, (grp_rows(h10), proj_rows(h10)))
check("3 an item with no tag in a home project shows home, once (again through the Project row, not a duplicate Group row)",
      grp_rows(h11) == [] and any("home" in r_ for r_ in proj_rows(h11)) and '<h1><span class="hid">a11</span> Fix the report</h1>' in h11, (grp_rows(h11), proj_rows(h11)))
check("3 a closed item with an old tag: its stored title is kept as it was, the page shows it without the tag and with its group (through Project, not a duplicate Group row)",
      rd(12)["subject"] == "[work] Closed with an old tag" and "Closed with an old tag" in h12 and "[work]" not in h12.split("<aside")[0] and grp_rows(h12) == [] and any("work" in r_ for r_ in proj_rows(h12)), (grp_rows(h12), proj_rows(h12)))
LOGP = T / "store/a/10.json"
d = json.loads(LOGP.read_text()); d["subject"] = "[home] Fix the export, renamed"; LOGP.write_text(json.dumps(d))
import subprocess
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "one")
d["subject"] = "Fix the export, again"; LOGP.write_text(json.dumps(d)); git("add", "-A"); git("commit", "-q", "-m", "two")
hl = ui_render.Board(f"{tmp}/store").item_html("a10")
check("3 …a rename's 'was' shows the old title without its tag", "subject edited (was “Fix the export, renamed”)" in hl and "[home]" not in strip(hl.split('class="hist"')[1].split("</ul>")[0]) if 'class="hist"' in hl else False, hl[hl.find("hist"):][:500])
d["subject"] = "[home] Fix the export"; LOGP.write_text(json.dumps(d)); git("add", "-A"); git("commit", "-q", "-m", "three")

# ================================================================ 4. the lists, the project page, the text renderers
bd = ui_render.Board(f"{tmp}/store")
hh = bd.html()
check("4 home draws the row with the title without the tag, under its project's group", "Fix the export" in hh and "[home] Fix the export" not in strip(hh) and "Fix the export" in hh[hh.find('class="iscope">work'):], hh[:300] if "Fix the export" not in hh else "")
check("4 the project page's header names the project's group once, in the h1 itself (work/dsl, home/hmp: proj_title already carries the scope on a multi-scope instance), not a second time on a pjgroup sub-line, and its rows show the titles without a tag",
      "<h1>work/dsl</h1>" in bd.routing_html(WORK) and 'class="sub pjgroup"' not in bd.routing_html(WORK)
      and "<h1>home/hmp</h1>" in bd.routing_html(HOME) and 'class="sub pjgroup"' not in bd.routing_html(HOME)
      and "[work] Hold" not in strip(bd.routing_html(WORK)), bd.routing_html(WORK)[:400])
from stackshot.web.ui import search as ui_search
from stackshot.web import search as web_search
web_search.sync(ui_render.Board(f"{tmp}/store"))
sh = ui_search.results_html(ui_render.Board(f"{tmp}/store"), "export")
rows = re.findall(r'<li class="irow srow"[^>]*>(.*?)</li>', sh, re.S)
row = next((x for x in rows if re.search(r"Fix the\s+export", strip(x)) and 'ktag">Item<' in x and "a10" in strip(x)), "")
who = (re.search(r'<div class="ir-who">(.*?)</div>', row, re.S) or [0, ""])[1]
check("4 a search hit shows the title without the tag, and its who line the group from the project once (through the scoped project label \"work/dsl\", not a second, plain \"work\")",
      bool(row) and "[home]" not in strip(row) and "work/dsl" in strip(who) and strip(who).count(" · work ·") == 0 and "home" not in strip(who), [strip(x)[:120] for x in rows])
from stackshot.web import render as text_render
tb = text_render.Board(f"{tmp}/store")
md = tb.markdown()
check("4 board.md shows the group once, then the title without the tag", "**a10 · work · Fix the export**" in md and "**a11 · home · Fix the report**" in md and "[home] Fix" not in md, [l for l in md.splitlines() if "a10" in l][:3])
check("4 …the closed record with its old tag is listed without it, its group the project's", "work · Closed with an old tag" in md and "[work] Closed" not in md, [l for l in md.splitlines() if "a12" in l][:3])
br = tb.brief()
check("4 the digest's your-move line carries the group and the bare title", "your move: a13 work · Hold a question" in br and "[work] Hold" not in br, br)
from stackshot.web.tools import brief as _wt_brief2
wt = _wt_brief2._world_waits_text()
check("4 the brief's waiting-on-the-world line carries the group and the title without the tag", " a14 work · Waits on the vendor:" in wt.replace("- ", " ", 1) or "a14 work · Waits on the vendor" in wt, wt)
check("4 …a title with a tag is never shown raw there", "[work] Waits" not in wt, wt)
ub = ui_render.Board(f"{tmp}/store")
check("4 the ui Board's item_group is the home page's reading (a work project, a home project)", ub.item_group(ub.rows[0]) in ("work", "home") and {ub.item_group(r) for r in ub.rows} == {"work", "home"}, [ub.item_group(r) for r in ub.rows])

# ================================================================ 5. the reads
out = _wt_get.stackshot_get("a10")
check("5 get's first line: the id, the state, the group once and the title without the tag", out.splitlines()[0].endswith("[open] work · Fix the export") and "[home] Fix" not in out.splitlines()[0], out.splitlines()[0])
out11 = _wt_get.stackshot_get("a11")
check("5 …a title that had no tag reads the same way, with its own group", out11.splitlines()[0].endswith("[open] home · Fix the report"), out11.splitlines()[0])
check("5 the stored title is untouched by every read above", rd(10)["subject"] == "[home] Fix the export" and rd(12)["subject"] == "[work] Closed with an old tag", (rd(10)["subject"], rd(12)["subject"]))

# ================================================================ 6. other reaches: for-you rows, the similar-items note, a bare-id close note, the holds report, page debt, search's schema
check("2 bare is case-insensitive and tolerates extra whitespace after a tag", TL.bare("[Work]  Fix the export") == "Fix the export" and TL.bare("[HOME]\tFix") == "Fix")

from stackshot.notify import foryou_rows as _fr
GRP = lambda it: "work · " + TL.bare(str(it.get("subject") or ""))
before6 = {"status": "open", "metadata": {"project": WORK}, "subject": "[work] Ship the thing"}
after6 = {"status": "completed", "metadata": {"project": WORK, "outcome": "done"}, "subject": "[work] Ship the thing"}
rows6 = _fr.changes(before6, after6, "falcon-main", lambda g: g, lambda a: None, grp=GRP)
check("6 a for-you close row carries the caller's group_title, never the raw tagged subject", rows6 and "[work] Ship" not in rows6[0][1] and "work · Ship the thing" in rows6[0][1], rows6)
dw = _fr.due_what("due", "Thu Mar 5th", "work · Fix the export")
check("6 due_what's line is built from the caller's already-grouped title, not a raw subject", dw == "due Thu Mar 5th: work · Fix the export", dw)

from stackshot.model import similar as _sim
rowsx = [("a20", {"subject": "[work] Fix the export pipeline", "status": "open", "metadata": {"project": WORK}})]
note = _sim._similar_note("a99", "Fix the export pipeline soon", WORK, rowsx, lambda p: "", NOW)
check("6 the similar-items note shows a matched item's title without its tag", "a20" in note and "[work] Fix" not in note and "Fix the export pipeline" in note, note)

log_tok = CL.begin()
_model_ids._read_note("10", "a10")
_model_ids.name_read("a10", {"subject": "[home] Fix the export", "metadata": {"project": HOME}})
_calls_made = CL.end(log_tok)
_id_note = next((v for k, v in _calls_made if k == "item-id"), "")
check("6 name_read's close note strips the subject's tag and shows the item's group", "home · Fix the export" in _id_note and "[home]" not in _id_note, _calls_made)

from stackshot.web.tools import notes as _wt_notes
item(15, "[home] An item on hold for no reason", HOME, hold=True)
holds = _wt_notes._holds_unexplained()
h15 = next((r for r in holds if r["gid"] == "a15"), None)
check("6 the unexplained-holds report shows the item's group and its title without the tag", h15 is not None and h15["subject"] == "home · An item on hold for no reason", holds)

from stackshot.service import page_debt as _pd
item(16, "[work] A page-debt row", WORK)
row16 = _pd.page_debt_item("a16", "opened")
check("6 a page-debt row carries the item's title without its tag, with its group (the row has no scope field of its own to carry it instead)", row16["subject"] == "work · A page-debt row", row16)

check("6 search's SCHEMA is bumped past the tagged-title index (an older index with a tag in it is rebuilt)", web_search.SCHEMA >= 2, web_search.SCHEMA)

tb17 = ui_render.Board(f"{tmp}/store")
row17 = {"subject": "[work] No group reads here"}
tb17.item_group = lambda r: ""
check("6 titled() falls back to the bare title alone (no dangling ' · ') when an item's group reads empty", tb17.titled(row17) == "No group reads here", tb17.titled(row17))

tagonly_subj = "[work] " + "y" * 74      # 81 characters: only "[work]" fits before the limit, so the cut must not leave the tag alone
tagonly_cut = _fg.fix_long_subject(tagonly_subj, None)
check("6 fix_long_subject's tag-only guard: a cut that would leave only the tag standing is skipped, so the gate below refuses the whole title for its length instead of storing the tag alone",
      tagonly_cut == tagonly_subj, tagonly_cut)

res, made = create("[work] Recycle the panes")
check("6 the recycle gate reads past a leading tag too: a tagged subject that is only a recycle is refused the same as a bare one", isinstance(res, ToolError) and "a recycle is not an item" in str(res), res)
# the check above passes even with no stripping at all (the regex's unanchored branch matches "recycle the panes" wherever it sits in the string);
# this one only passes when the leading tag really is taken off first, since the anchored branch needs the bare text to start with the word
res, made = create("[work] Recycle")
check("6 …and the tag really is stripped first: a start-anchored word ('Recycle' alone, no 'panes/sessions/fleet' after it) is seen only once the tag in front of it is gone", isinstance(res, ToolError) and "a recycle is not an item" in str(res), res)

from stackshot.service import item_sync as _isync
from stackshot.core.instance import OWNER as _ISOWNER
plan, err = _isync._itemsync_plan({"project": WORK, "subject": "[work] Ship the feature", "step": "ship it", "mover": _ISOWNER, "then": MAIN})
check("6 item_sync's open strips a leading tag off the subject before it is stored (the group comes from the project)", err is None and plan.get("subject") == "Ship the feature", (plan, err))
plan2, err2 = _isync._itemsync_plan({"project": WORK, "subject": "[work] ", "step": "ship it", "mover": _ISOWNER, "then": MAIN})
check("6 …a subject that is only a tag is refused, not filed as an empty title", err2 is not None and err2[0] == 400 and "only a tag" in err2[1]["error"], (plan2, err2))

# ================================================================ 7. notices: no site builds a message line from the raw tagged subject any more
from stackshot.anchors import anchors as _anc2
from stackshot.service import telling as _telling2
item10b = rd(10)      # "[home] Fix the export" stored in a WORK project: the tag says home, the group is work
check("7 anchors.notice_title hides the tag and shows the item's own group, not the tag's word", _anc2.notice_title(item10b) == "work · Fix the export", _anc2.notice_title(item10b))
class _BoomOnMeta(dict):   # a registry/id-file read that fails mid-lookup (a damaged page, an id file mid-write): group_title's own read of it raises
    def get(self, k, default=None):
        if k == "metadata": raise RuntimeError("boom: a damaged page")
        return dict.get(self, k, default)
_it_boom = _BoomOnMeta({"subject": "[home] Fix the broken one"})
check("7 notice_title's own fallback: group_title raising (a registry read gone bad) is caught, not propagated to the notice; the bare stored title is still shown, with no group rather than stop the notice",
      _anc2.notice_title(_it_boom) == "Fix the broken one", _anc2.notice_title(_it_boom))
check("7 telling._title is the same one helper (not a second copy of the wording)", _telling2._title is _anc2.notice_title, _telling2._title)

NOTICE_SITES = [
    ("stackshot/service/telling.py", ["item.get('subject')", 'item.get("subject")', "it.get('subject')", 'it.get("subject")', "closed.get('subject')"]),
    ("stackshot/service/wakes.py", ["it.get('subject')", 'it.get("subject")']),
    ("stackshot/service/handoff.py", ["item.get('subject')", 'item.get("subject")']),
    ("stackshot/service/handoff_cold.py", ["item.get('subject')", 'item.get("subject")']),
    ("stackshot/service/ladder.py", ["item.get('subject')", 'item.get("subject")']),
    ("stackshot/service/stall.py", ["item.get('subject')"]),
    ("stackshot/service/watching.py", ["it.get('subject')"]),
    ("stackshot/service/audit_ticks.py", ["items[gid].get('subject')"]),
    ("stackshot/service/pane_recovery.py", ["item.get('subject')"]),
    ("stackshot/service/github_events.py", ["item.get('subject')"]),
    ("stackshot/service/event_waits.py", ['it.get("subject")']),
]
for relpath, patterns in NOTICE_SITES:
    body_lines = [ln for ln in (pathlib.Path(STACK) / relpath).read_text(encoding="utf-8").splitlines() if "file=sys.stderr" not in ln]      # a stderr debug print is a developer's line, not a notice; it is left alone
    hit = next((p for ln in body_lines for p in patterns if p in ln), None)
    check(f"7 {relpath} never builds a notice line straight off a raw tagged subject again", hit is None, hit)
    del hit

# 8  the leftovers of the first round: every other place a title is shown reads it the same way
check("8 bare: a dash that stands alone after the tag is the tag's own punctuation, taken off with it",
      TL.bare("[work] - Fix the export") == "Fix the export" and TL.bare("[work]  \u2013  Fix") == "Fix" and TL.bare("[work][home] \u2014 Fix") == "Fix" and TL.bare("[work] : Fix") == "Fix", TL.bare("[work] - Fix the export"))
check("8 bare: a minus or a dash with no space after it stays, and a title with no tag keeps its own leading dash",
      TL.bare("[work] -5 degrees in the lab") == "-5 degrees in the lab" and TL.bare("- Fix the export") == "- Fix the export" and TL.bare("[work] --force the push") == "--force the push", TL.bare("[work] -5 degrees in the lab"))
check("8 bare: a title that is only a tag and a dash is shown as stored, and blank for a write that checks it",
      TL.bare("[work] - ") == "[work] - " and TL.bare("[work] - ", or_blank=True) == "" and TL.bare("[work] -") == "-", (TL.bare("[work] - "), TL.bare("[work] -")))
from stackshot.github import ghsync as _ghs
check("8 the GitHub mirror's issue title is the title as screens show it, with no tag; a blank one reads as no subject",
      _ghs.title_of({"subject": "[home] Fix the export"}) == "Fix the export" and _ghs.title_of({"subject": "Fix the export"}) == "Fix the export" and _ghs.title_of({"subject": ""}) == "(no subject)"
      and _ghs.title_of({"subject": "[work] - Fix it"}) == "Fix it", _ghs.title_of({"subject": "[home] Fix the export"}))
from stackshot.model import rebullet as _rebullet
check("8 the rebullet call's context names the title with no tag", '"subject": "Fix the export"' in _rebullet.build_message("a1", {"subject": "[home] Fix the export", "description": "- a", "metadata": {}}), _rebullet.build_message("a1", {"subject": "[home] Fix the export", "description": "- a", "metadata": {}}))
from stackshot.notify import foryou_rows as _fyr
_closed_before = {"status": "open", "metadata": {}}; _closed_now = {"status": "completed", "subject": "[home] Fix the export", "metadata": {"outcome": "done"}, "updated": NOW}
_rows8 = _fyr.changes(_closed_before, _closed_now, "falcon-main", lambda g: g, lambda a: None)
check("8 a For you row built with no project reading shows the title with no tag", len(_rows8) == 1 and "Fix the export" in _rows8[0][1] and "[home]" not in _rows8[0][1], _rows8)
from stackshot.service import ask_named as _ask_named
_ask_row = {"gid": "a900", "subject": "[home] Fix the export", "scope": "home", "ask": "Decide: a thing"}
_ask_txt = p.asked_lines([_ask_row])
check("8 the end-of-turn ask line shows the group from the row's scope and the title with no tag", '"home \u00b7 Fix the export"' in _ask_txt and "[home]" not in _ask_txt, _ask_txt)
_ask_txt2 = p.asked_lines([{**_ask_row, "scope": "work"}])
check("8 …the row's own group, not the default one", '"work \u00b7 Fix the export"' in _ask_txt2, _ask_txt2)
item(901, "[home] Fix the export", HOME, ask="Decide: a thing")
check("8 an asks-named row carries the group ready-made as scope", _anc2.item_group({**rd(901), "gid": "a901"}) == "home", _anc2.item_group({**rd(901), "gid": "a901"}))
_real_gt = _anc2.group_title
def _boom_gt(*a, **k): raise RuntimeError("boom: a damaged page")
_anc2.group_title = _boom_gt
try:
    _got8 = _wt_get._fmt({**rd(901), "gid": "a901"})
finally:
    _anc2.group_title = _real_gt
check("8 the get tool's first line falls back to the bare title when the group cannot be read, as a notice does", _got8.splitlines()[0].endswith("] Fix the export"), _got8.splitlines()[0])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
