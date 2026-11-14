"""Scenario test for the create reply's similar-items note (the board item duplicated an open item) — fixture data, no live store, no network.

Covers: a near-duplicate subject in the same project is listed, with its link form and its state; an unrelated subject lists
nothing; a completed item older than 14 days is not listed, one completed lately is, marked completed; the same hub page
(a sub-page) adds a smaller bonus than the same page, and a borderline subject in another hub is not listed; at most 3 are
listed, the closest first; the new item is never listed against itself; the line's form; and in every case the item is
still created (a note, never a block).

    tests/run-suite similar        → exit 0 / 1"""
import json, os, re, sys, pathlib, tempfile, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="similartest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra"): (T / d).mkdir(parents=True)
NAMES = ("falcon-main", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/example.md", "type: project\ntitle: Example\ndisplay-name: falcon\nagents:\n  falcon-main: builds it\nstatus: active")
page("projects/example/queue-notes.md", "type: project\ntitle: Queue notes")
page("projects/other.md", "type: project\ntitle: Other\ndisplay-name: home-other\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.model import ids as _model_ids
from stackshot.web import publish as _web_publish
from stackshot.model import similar as _sim
from stackshot.web.tools import create as _wt_create
server._cfg.CFG.setdefault("model", {})["guards"] = False      # fixture owners the fleet does not know; the write guards have their own suite
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
MAIN, OTHER = "falcon-main", "home-other"
STK, ATT, OTH = "projects/example", "projects/example/queue-notes", "projects/other"
def create(subject, project=STK, owner=MAIN):
    r = _wt_create.stackshot_create(subject=subject, description="- Goal: A thing\n- It lives here\n- Done when done", project=project, owner=owner, next=f"{owner}: carry on")
    gid = r.split()[1]
    return r, _model_ids._norm_id(gid)
def note(r):
    m = re.search(r"\n\(similar items, [^\n]*\)", r)
    return m.group(0) if m else ""
def age(gid, days, status="completed"):
    it = server._load(gid); it["status"] = status
    it["state_updated"] = it["updated"] = time.time() - days * 86400
    writes.save(gid, it)
def created(r, gid):
    return r.startswith("created ") and server._load(gid)["status"] == "open"

# ---- the words and the score
W = getattr(_sim, "_subject_words", lambda s: None)   # absent before the feature: the checks below then fail, they do not crash
check("words: the prefix, case, short and filler words dropped, a plural folded",
      W("[home] Add the Similar items to a Create reply") == frozenset({"similar", "create", "reply"}) and W("[work] Fix it") == frozenset(), W("[home] Add the Similar items to a Create reply"))
S = getattr(_sim, "_similar_score", lambda *a: None)
check("score: one shared word never matches, the same single word does, no overlap is 0",
      S(W("[home] backup"), W("[home] backup"), False, False) == 1.0 and S(W("[home] backup nightly"), W("[home] backup weekly"), True, True) == 0.0
      and S(W("[home] alpha beta"), W("[home] gamma delta"), True, True) == 0.0)

# ---- (a) a near-duplicate in the same project is listed; (d) the item is created
r, seed = create("[home] Add similar-items note to the create reply")
check("first create: nothing similar yet, a plain create", created(r, seed) and not note(r), r)
r, dup = create("[home] List similar items as a note in the create reply")
n = note(r)
check("(a) a near-duplicate subject in the same project is listed, open, in the reply's link form",
      f'{server._gh.shown(seed)} "[home] Add similar-items note to the create reply" [open]' in n, r)
check("(a) the line has the asked form: the lead, the list, the supersede advice, one line",
      n.startswith("\n(similar items, check before working this one: ") and n.endswith("; if one already carries this, update it and close the new one as superseded)") and n.count("\n") == 1, n)
check("(d) the near-duplicate is still created, open", created(r, dup), r)
check("the new item is never listed against itself", server._gh.shown(dup) not in n, n)

# ---- (b) an unrelated subject lists nothing
r, unrel = create("[home] Renew the TLS certificate for the mail relay")
check("(b) an unrelated subject in the same project lists nothing", not note(r), r)
check("(d) the unrelated item is created", created(r, unrel), r)
r, unrel2 = create("[home] Reply to the vendor invoice question")
check("(b) a lone shared common word lists nothing", not note(r) and created(r, unrel2), r)

# ---- (c) a completed item: older than 14 days is not listed, a recent one is
r, old = create("[home] Migrate nightly backup rotation schedule", project=OTH, owner=OTHER)
age(old, 20)
r, new = create("[home] Migrate nightly backup rotation schedule again", project=OTH, owner=OTHER)
check("(c) an item completed 20 days ago is not listed", not note(r), r)
check("(d) the item is created", created(r, new), r)
r, fresh = create("[home] Rotate signing keys every quarter", project=OTH, owner=OTHER)
age(fresh, 2)
r, new = create("[home] Rotate the signing keys quarterly", project=OTH, owner=OTHER)
check("(c) an item completed 2 days ago is listed, marked completed", f'{server._gh.shown(fresh)} "[home] Rotate signing keys every quarter" [completed]' in note(r), r)
check("(d) the item is created", created(r, new), r)
r, dropped = create("[home] Archive stale vendor contracts folder", project=OTH, owner=OTHER)
age(dropped, 13.9)
r, new = create("[home] Archive stale vendor contracts folder again", project=OTH, owner=OTHER)
check("(c) 13.9 days ago is still inside the window", server._gh.shown(dropped) in note(r), r)

# ---- the hub bonus: same page 0.10, same hub 0.05, another hub none
r, base = create("[home] Rebuild search index nightly", project=STK)
r, same_page = create("[home] Rebuild search cache weekly", project=STK)
check("bonus: two shared words of four, the same project page: listed", server._gh.shown(base) in note(r), r)
r, same_hub = create("[home] Rebuild search cache weekly", project=ATT)
check("bonus: the same hub page (a sub-page of the project): listed", server._gh.shown(base) in note(r) and created(r, same_hub), r)
r, other_hub = create("[home] Rebuild search cache weekly", project=OTH, owner=OTHER)
check("bonus: the same borderline subject in another hub: nothing, the item still created", server._gh.shown(base) not in note(r) and created(r, other_hub), r)

# ---- at most 3, the closest first
for i in range(4):
    create(f"[home] Publish quarterly newsletter archive batch{i}")
r, last = create("[home] Publish quarterly newsletter archive batch9")
check("at most 3 items are listed", len(re.findall(r'\[open\]', note(r))) == 3, note(r))
listed = re.findall(r'(?:: |, )(\S+) "', note(r))
check("the closest first: equal scores go to the newer item", len(listed) == 3 and [int(_model_ids._norm_id(g)[1:]) for g in listed] == sorted((int(_model_ids._norm_id(g)[1:]) for g in listed), reverse=True), note(r))
check("(d) created", created(r, last), r)

print(("ok" if not fails else "FAILED") + f": similar scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
