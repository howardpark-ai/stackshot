"""Scenario test for which anchors count for an item (anchor_scope.py) — fixture data, no live store, no network, no server socket.

An anchor is held by one project's page and that page keeps it, but an item reads the anchors scoped to it from every project's page, not only its own project's.
Covers: an anchor on another project's page counts, and says which page holds it; the item's own project's page is read first; the same anchor on two pages (also through
a [github.moved] rename of its repository) counts once, with every page in `pages`, the later `added` and the union of the item lists; an item with no anchor anywhere
gets nothing; a project-wide anchor counts for no item (and `wide` lists the item's own project's); an anchor scoped to another item does not count; a hand-edited store
(a page that is no list, an entry that is no dict, an items that is a number, an `added` that is no time, a url that is no string) steps over the junk; scoped_map reads
the same rule for the whole board in one pass; completion_due asks each page about the anchors it holds; and the readers built on it agree: the server's `_scoped_anchors`
and the guard pass (model_guards.report) read an anchor held by another page, the migration planner's `scoped`, the board's `scoped_urls` and the hold reasons.

    tests/run-suite anchor_counts        → exit 0 / 1"""
import json, os, pathlib, re, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="anchcnt-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
sys.path.insert(0, STACK)

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

from stackshot.anchors import anchor_scope as AS
from stackshot.web import render
from stackshot.model import model_guards as MG

A, B, C = "projects/alpha", "projects/beta", "projects/gamma"
DM = "https://acme.slack.com/archives/D0000000001"      # a Slack DM: its receivers sit in more than one project
PR = "https://github.com/o/r/pull/9"
SOLO = "https://example.invalid/solo"
store = {
    A: [{"url": SOLO, "items": ["a1"], "added": 10, "by": "t"}, {"url": "https://example.invalid/wide", "items": None, "added": 11, "by": "t"}],
    B: [{"url": DM, "items": ["a1", "b2"], "added": 20, "by": "t"}, {"url": PR, "items": ["b2"], "added": 21, "by": "t"}, {"url": "https://example.invalid/bwide", "items": None, "added": 22, "by": "t"}],
    C: [{"url": DM, "items": ["b2", "c3"], "added": 30, "by": "t"}],
}
urls = lambda es: [e["url"] for e in es]

# ---- the helper
got = AS.anchor_scope(store, "a1", A)
check("an anchor on another project's page counts for the item, with the page that holds it", urls(got) == [SOLO, DM] and [e["page"] for e in got] == [A, B], got)
check("the item's own project's page is read first, whatever the keys sort like", urls(AS.anchor_scope(store, "a1", B))[0] == DM and AS.anchor_scope(store, "a1", B)[0]["page"] == B, AS.anchor_scope(store, "a1", B))
check("an item with no project (or an unknown one) still reads every page", urls(AS.anchor_scope(store, "a1")) == urls(AS.anchor_scope(store, "a1", "projects/nowhere")) == [SOLO, DM], AS.anchor_scope(store, "a1"))
two = [e for e in AS.anchor_scope(store, "b2", B) if e["url"] == DM]
check("the same anchor on two pages counts once", len(two) == 1 and len(AS.anchor_scope(store, "b2", B)) == 2, AS.anchor_scope(store, "b2", B))
check("...with the page it comes first from, every page that holds it, the later added and the union of the item lists",
      two[0]["page"] == B and two[0]["pages"] == [B, C] and two[0]["added"] == 30 and two[0]["items"] == ["a1", "b2", "c3"] and two[0]["scoped"] is True, two)
check("...and the copy of the entry in the store is not changed by it", store[B][0]["items"] == ["a1", "b2"] and store[B][0]["added"] == 20 and "pages" not in store[B][0], store[B][0])
check("an item with no anchor anywhere gets nothing, and a project-wide anchor is not one scoped to it", AS.anchor_scope(store, "z9", A) == [] and AS.anchor_scope(store, "z9", B) == [], AS.anchor_scope(store, "z9", A))
check("an empty or missing id, and a store that is no dict, count nothing", AS.anchor_scope(store, "", A) == [] and AS.anchor_scope(None, "a1", A) == [] and AS.anchor_scope([], "a1", A) == [])
wide = AS.anchor_scope(store, "z9", A, wide=True)
check("wide lists the item's own project's project-wide anchors, flagged not scoped, and no other project's", urls(wide) == ["https://example.invalid/wide"] and wide[0]["scoped"] is False and wide[0]["items"] is None, wide)
check("an anchor scoped to another item does not count", PR not in urls(AS.anchor_scope(store, "a1", A)) and urls(AS.anchor_scope(store, "c3", C)) == [DM], urls(AS.anchor_scope(store, "c3", C)))

# a [github.moved] rename: one repository under two names is one anchor
from stackshot.core import config as cfg
moved = {"https://github.com/o/r/pull/9": "https://github.com/o/r2/pull/9"}
old_canon = cfg.canon_name
cfg.canon_name = lambda n: "o/r" if n in ("o/r", "o/r2") else old_canon(n)
try:
    renamed = AS.anchor_scope({A: [{"url": "https://github.com/o/r/pull/9", "items": ["a1"], "added": 1}], B: [{"url": "https://github.com/o/r2/pull/9", "items": ["a1"], "added": 2}]}, "a1", A)
finally:
    cfg.canon_name = old_canon
check("one repository under its old and its new name is one anchor", len(renamed) == 1 and renamed[0]["pages"] == [A, B] and renamed[0]["url"] == "https://github.com/o/r/pull/9", renamed)

junk = {A: ["junk", 7, None, {"url": "https://example.invalid/items-int", "items": 5, "added": "yesterday"}, {"url": ["x"], "items": ["a1"]}, {"url": "https://example.invalid/odd", "items": ["a1"], "added": "not a time"}],
        B: "junk", C: {"url": "x"}, "projects/delta": None}
check("a hand-edited store: junk is stepped over, the real anchor counts, an added that is no time is none", urls(AS.anchor_scope(junk, "a1", A)) == ["https://example.invalid/odd"] and AS.anchor_scope(junk, "a1", A)[0]["added"] is None
      and AS.clean_entries("junk") == [] and AS.clean_entries(None) == [], AS.anchor_scope(junk, "a1", A))

# ---- the whole board in one pass
sm = AS.scoped_map(store)
check("scoped_map: every item's anchors from every page, each once, in the order added", sm == {"a1": [SOLO, DM], "b2": [DM, PR], "c3": [DM]}, sm)
check("scoped_map agrees with anchor_scope for every item", all(sm[g] == urls(sorted(AS.anchor_scope(store, g), key=lambda e: e["added"] or 0)) or set(sm[g]) == set(urls(AS.anchor_scope(store, g))) for g in sm), sm)
check("scoped_map: junk is stepped over", AS.scoped_map(junk) == {"a1": ["https://example.invalid/odd"]} and AS.scoped_map(None) == {}, AS.scoped_map(junk))

# ---- a completion asks each page about its own
items = [{"gid": g, "status": s} for g, s in (("a1", "completed"), ("b2", "open"), ("c3", "open"))]
due = AS.completion_due(store, "a1", items)
check("completion_due: an anchor whose other listed items are all closed is asked about, on the page that holds it; one with an open item left is not", [(p, e["url"]) for p, e in due] == [(A, SOLO)], due)
items2 = [{"gid": g, "status": "completed"} for g in ("a1", "b2", "c3")]
due2 = AS.completion_due(store, "b2", items2)
check("completion_due: the same anchor on two pages is asked about on each (each page keeps its own)", [(p, e["url"]) for p, e in due2] == [(B, DM), (B, PR), (C, DM)], due2)

# ---- the readers built on it
from stackshot.web import server
server._anc.save({k: v for k, v in store.items()})
check("the server reads an anchor held by another project's page (_scoped_anchors)", urls(server._scoped_anchors(A, "a1")) == [SOLO, DM] and urls(server._scoped_anchors(A, "b2")) == [DM, PR]
      and server._scoped_anchors(A, "z9") == [], (urls(server._scoped_anchors(A, "a1")), urls(server._scoped_anchors(A, "b2"))))
check("...and from the anchors a pass already loaded", urls(server._scoped_anchors(A, "a1", store)) == [SOLO, DM] and server._scoped_anchors(A, "a1", None) == server._scoped_anchors(A, "a1"))
check("the note a hold owes sees it: an outside item whose thread is anchored on another page is not told to anchor it", server._scoped_anchor_exists("b2", {"project": A}) and not server._scoped_anchor_exists("z9", {"project": A}))
check("a hold that waits on a notice from an anchor on another page is held by it (_hold_held_by)", server._hold_held_by("b2", {"project": A}) == ["anchor"] and server._hold_held_by("z9", {"project": A}) == [])

shown = server._fmt({"gid": "a1", "id": "a1", "subject": "[home] item a1", "description": "- A thing, finished when it works", "status": "open", "metadata": {"project": A, "owner": "Oliver"}})
line = next((x for x in shown.splitlines() if x.startswith("anchors (any project):")), "")
check("get lists the anchors that count for the item, naming the page of one held by another project, and its own project's project-wide anchors",
      f"{SOLO} [items: a1]" in line and f"{DM} [items: a1, b2; held by {B}]" in line and "https://example.invalid/wide [project-wide]" in line and "bwide" not in line, line)

# the guard pass: an anchor wait that stores no wait_anchor is complete when an anchor is scoped to the item on any page, and incomplete when none is
def anchor_wait(gid, project):
    return {"gid": gid, "id": gid, "subject": f"[home] item {gid}", "description": "- A thing, finished when it works", "status": "open",
            "metadata": {"project": project, "state": "outside", "needs": ["external"], "wait_kind": "anchor", "wait_event": "the review lands", "party": "Acme",
                         "wake": "2099-01-01", "post_wake_mover": "home-agent", "next": "home-agent: read the thread when it moves"}}
flagged = lambda anchors: any("b2" in ids for ids in MG.report({"b2": anchor_wait("b2", A)}, anchors=anchors).ids.values())
check("model_guards.report: an anchor wait whose anchor is held by another page names its anchor; with no anchor anywhere it is flagged", flagged({}) and not flagged(store), (flagged({}), flagged(store)))
from stackshot.model import migration as MIG
env = MIG.Env.__new__(MIG.Env)
env.anchors = store
check("migration's planner reads it the same way (scoped, anchored)", env.scoped(A, "a1") == [SOLO, DM] and env.anchored("b2", A)({}) and not env.anchored("z9", A)({}), env.scoped(A, "a1"))

# the board: one rule for the lists, the item page and the hold reasons
os.makedirs(T / "store/a", exist_ok=True)
(T / "store/anchors.json").write_text(json.dumps(store))
def put(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": "open", "updated": 1.0,
                                                    "metadata": {"owner": "Oliver", "project": A, **meta}}))
put(1, state="parked", hold=True, needs=["external"], wake="2099-01-01", next="home-agent: look again")
(T / "store/next-id").write_text("10")
b = render.Board(str(T / "store"))
check("the board's scoped_urls reads every page (render.py)", b.scoped_urls("a1") == [SOLO, DM] and b.scoped_urls("b2") == [DM, PR] and b.scoped_urls() == sm, (b.scoped_urls("a1"), b.scoped_urls()))
check("the hold reasons name an anchor held by another page, and none for an item with no anchor", render.hold_whys({"gid": "b2", "metadata": {}}, b.scoped_urls("b2")) == [render.HOLD_WHY["anchor"]]
      and render.hold_whys({"gid": "z9", "metadata": {}}, b.scoped_urls("z9")) == [], "")
from stackshot.web.ui import render as ur
ub = ur.Board(str(T / "store"))
check("the board pages' scoped_urls reads every page too (ui/render.py), the same lists", ub.scoped_urls("a1") == b.scoped_urls("a1") and ub.scoped_urls() == sm, ub.scoped_urls())
html = ub.item_html("a1")
check("the item page names the anchor held by another project's page, and says whose it is", f'href="{DM}"' in html and f'href="{SOLO}"' in html and f"on {B}" in html, re.findall(r'<li><b>.{0,200}', html))
check("the item page lists the anchors scoped to this item and no other", PR not in html and "https://example.invalid/bwide" not in html and 'Anchors <span class="count">2</span>' in html, re.findall(r"Anchors.{0,80}", html))

# ---- the minute pass, the wait-set note, the receivers and the completion prompt read the anchor from the page that holds it
# Pages: alpha and gamma have a keeper, beta has none (nobody rules its notices). Every item below is of alpha or gamma; the anchors sit on other pages.
import time, threading
from stackshot.anchors import anchors as ANC; from stackshot.router import routing
(T / "store/a/1.json").unlink()
PAGE = lambda sess: {"title": "p", "name": "p", "org": "home", "tags": [], "type": "project", "session": sess, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": "https://example.invalid/p"}
REG = {"pages": {A: PAGE("keep-alpha"), B: PAGE(""), C: PAGE("keep-gamma")}}
(T / "store/projects.json").write_text(json.dumps(REG))
def item2(i, project, status="open", mover="mv-alpha", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": status, "updated": 1.0, "state_updated": 1.0,
                                                    "metadata": {"owner": "Oliver", "mover": mover, "project": project, **meta}}))
held_meta = dict(state="parked", hold=True, needs=["external"], wake="2099-01-01", next="mv-alpha: look again")
def is_held(g): return bool(json.loads((T / f"store/{g[0]}/{g[1:]}.json").read_text())["metadata"].get("hold"))
server._publish = lambda: None
woke = []; server._wake_notify = lambda g, it, what, *a, **k: woke.append((g, what))
URL_B = "https://acme.slack.com/archives/D0000000009"       # held by beta only
URL_C = "https://github.com/o/r/pull/4"                    # held by gamma only (a keeper there)
item2(20, A, **held_meta); item2(21, A, **held_meta)
(T / "store/anchors.json").write_text(json.dumps({A: [], B: [{"url": URL_B, "items": ["a20"], "added": 5, "by": "t"}], C: [{"url": URL_C, "items": ["a21"], "added": 5, "by": "t"}]}))

# _anchor_pass: a held item of alpha whose anchor only beta holds is released by the notice in beta's log (beta has no keeper), not by one in alpha's
check("the pass reads the page that holds the anchor: a notice in the item's own page's log, where the anchor is not held, releases nothing",
      (routing.record(A, kind="anchor", to="x", label="Slack", who="hub", text="in the wrong log", target="for mv-alpha", anchor=URL_B), server._anchor_pass())[1] == [] and is_held("a20"))
routing.record(B, kind="anchor", to="x", label="Slack", who="hub", text="Kim wrote", target="", anchor=URL_B)
rel = server._anchor_pass()
check("...a notice in the log of the keeperless page that holds it releases the held item of another project", rel == ["a20"] and not is_held("a20") and [g for g, _w in woke] == ["a20"]
      and "arrived (nobody rules this project's notices)" in woke[0][1], (rel, woke))
check("...once", server._anchor_pass() == [] and len(woke) == 1)

# a page with a keeper: the keeper's ruling releases (_route calls _anchor_release with the page that holds the anchor), the pass only a line the hub ruled itself
n_k = routing.record(C, kind="anchor", to="keep-gamma", label="PR 4", who="hub", text="merged", target="for mv-alpha", anchor=URL_C)
with open(routing._file(C), "a", encoding="utf-8") as f:
    f.write(json.dumps({"id": n_k, "ruling": "passed", "to": "mv-alpha", "reason": "theirs", "by": "keep-gamma", "ts": time.time()}) + "\n")
check("the pass leaves a held item whose anchor's page has a keeper to the keeper's ruling", server._anchor_pass() == [] and is_held("a21"))
rel = server._anchor_release(C, next(n for n in routing.read(C) if n["id"] == n_k), by="keep-gamma")
check("...and the keeper's passed ruling, given the page that holds the anchor, releases the item of another project", rel == ["a21"] and not is_held("a21"), rel)
item2(21, A, **held_meta)
time.sleep(0.05); routing.record_auto(C, "merged", "a routine event on the fleet's own pull request", kind="anchor", label="PR 4", who="CI", text="CI passed", target="for mv-alpha", anchor=URL_C)
check("...and a line the hub ruled itself (a routine event) releases it from the pass, whatever project the item is of", server._anchor_pass() == ["a21"] and not is_held("a21"))
item2(21, A, **held_meta)
check("...and an anchor scoped to nobody held releases nothing (a project-wide anchor is for no item)", (
    (T / "store/anchors.json").write_text(json.dumps({A: [], B: [{"url": URL_B, "items": None, "added": 5, "by": "t"}], C: []})), routing.record(B, kind="anchor", to="x", label="Slack", who="hub", text="again", target="", anchor=URL_B),
    server._anchor_pass())[2] == [] and is_held("a21"))

# _watch_anchor_seen: an anchor any page holds is watched (no "add it" warning), the log of the page that holds it is read; one no page holds is the warning
(T / "store/anchors.json").write_text(json.dumps({A: [], B: [{"url": URL_B, "items": ["a20"], "added": 5, "by": "t"}], C: []}))
seen = server._watch_anchor_seen(A, URL_B, 0.0)
check("wait-set note: an anchor held by another project's page is watched (no warning) and the notices in that page's log are reported", "does not watch" not in seen and "Kim wrote" in seen and "again" in seen, seen)       # the item's own page's log is read as before; beta's, which holds the anchor, is read too
unheld = server._watch_anchor_seen(A, "https://example.invalid/nobody", 0.0)
check("...an anchor no page holds is still the warning, saying how to add it", "anchor-hub does not watch https://example.invalid/nobody for projects/alpha" in unheld and 'add=["https://example.invalid/nobody"]' in unheld, unheld)

# _watch_anchor_notice: an item of another project whose stored wait is on an anchor a keeperless page holds is turned by that page's notice, even if the item's own page has a keeper
told = []; server._watch_tell = lambda sid, rows: told.append((sid, [r[0] for r in rows]))
item2(40, A, wait_kind="anchor", wait_anchor=URL_B, wait_event="a reply", ask_by="2099-01-01", post_wake_mover="mv-alpha", needs=[], next="mv-alpha: read it", watch={"set_at": 1.0})
item2(41, A, wait_kind="anchor", wait_anchor="https://example.invalid/not-held-anywhere", wait_event="a reply", ask_by="2099-01-01", post_wake_mover="mv-alpha", needs=[], next="mv-alpha: read it", watch={"set_at": 1.0})
n_w = {"id": "w1", "ts": time.time(), "kind": "anchor", "label": "Slack", "who": "hub", "text": "Kim answered", "to": "x", "target": "", "anchor": URL_B}
rel = server._anchor_release(B, n_w)
m40 = json.loads((T / "store/a/40.json").read_text())["metadata"]
check("watch: a stored anchor wait of an item of alpha (which has a keeper) on a URL keeperless beta also holds is turned by beta's notice", rel == ["a40"] and "wait_kind" not in m40 and m40.get("mover") == "mv-alpha", (rel, m40))
check("...an item waiting on an anchor no page holds is not touched by it", json.loads((T / "store/a/41.json").read_text())["metadata"].get("wait_kind") == "anchor")

# the receivers: the movers of every item an anchor is scoped to, from any project, are bound; a project-wide anchor binds only its own project's
items = [{"gid": "a30", "id": "30", "status": "open", "metadata": {"project": A, "mover": "mv-alpha"}}, {"gid": "a31", "id": "31", "status": "open", "metadata": {"project": C, "mover": "mv-gamma"}},
         {"gid": "a32", "id": "32", "status": "completed", "metadata": {"project": C, "mover": "mv-done"}}, {"gid": "a33", "id": "33", "status": "open", "metadata": {"project": B, "mover": "mv-beta"}}]
rstore = {B: [{"url": URL_B, "items": ["a30", "a31", "a32"], "added": 1}, {"url": "https://example.invalid/bwide", "items": None, "added": 2}], A: [], C: []}
nm = {}
got_b = ANC.sessions_for(B, rstore[B][0], items, REG["pages"], nm)
check("receivers: sessions_for binds the movers of the open items an anchor is scoped to, of any project (a closed one is not bound)", got_b == {"mv-alpha", "mv-gamma"}, got_b)
got_w = ANC.sessions_for(B, rstore[B][1], items, REG["pages"], nm)
check("...a project-wide anchor binds its own project's open items' movers only", got_w == {"mv-beta"}, got_w)
rt = ANC.routes(rstore, items, REG["pages"])
rb = rt.get(ANC.anchor_id(URL_B)) or []
check("routes: on a page with no keeper the notice goes to those movers, for the page that holds the anchor", sorted((r["session"], r["project"]) for r in rb if r["filter"] == "") == [("mv-alpha", B), ("mv-gamma", B)], rb)
kstore = {C: [{"url": URL_C, "items": ["a30", "a31"], "added": 1}], A: [], B: []}
rk = ANC.routes(kstore, items, REG["pages"]).get(ANC.anchor_id(URL_C)) or []
check("...and on a page with a keeper the keeper gets it, the target naming only the movers of scoped items of the page's own project (the router reads the target against this page's roster)",
      len(rk) == 1 and rk[0]["session"] == "keep-gamma" and rk[0]["target"] == "for mv-gamma" and rk[0]["project"] == C, rk)
fstore = {C: [{"url": URL_C, "items": ["a30"], "added": 1}], A: [], B: []}
rf = ANC.routes(fstore, items, REG["pages"]).get(ANC.anchor_id(URL_C)) or []
check("...and for an anchor scoped to an item of another project alone, it is a project-wide notice to the keeper (as before), not 'for' that project's mover",
      len(rf) == 1 and rf[0]["session"] == "keep-gamma" and rf[0]["target"] == "project-wide", rf)

# _completion_anchor_prompt: asks each page's keeper about the anchors it holds, the item's own project's page first; the completing keeper is not notified
sent = []; server._push_noted = lambda to, note: sent.append((to, note))
for g, p in (("20", C), ("21", C)): item2(g, p, status="completed", mover="keep-gamma")
(T / "store/anchors.json").write_text(json.dumps({A: [{"url": SOLO, "items": ["a20"], "added": 1}], B: [{"url": URL_B, "items": ["a20", "a21"], "added": 2}], C: [{"url": URL_C, "items": ["a20"], "added": 3}]}))
done = json.loads((T / "store/a/20.json").read_text()); done["gid"] = "a20"
txt = server._completion_anchor_prompt("a20", done)
deadline = time.time() + 5
while len(sent) < 2 and time.time() < deadline: time.sleep(0.05)
pos = {p: txt.find(f"these {p} anchors") for p in (A, B, C)}
check("completion: every page that holds an anchor scoped to the item is asked about, the item's own project's page first, then the others by key", all(v >= 0 for v in pos.values()) and pos[C] < pos[A] < pos[B], (pos, txt))
check("...with its own anchors under each", f"- {SOLO}" in txt[pos[A]:pos[B]] and f"- {URL_B}" in txt[pos[B]:] and f"- {URL_C}" in txt[pos[C]:pos[A]] and f"anchors(project={B!r}, remove=[url])" in txt, txt)
check("...each page's keeper is told, except the one that completed the item", sorted(t for t, _n in sent) == ["keep-alpha"] and "(keeper keep-alpha notified)" in txt and "keep-gamma notified" not in txt and "(keeper " not in txt[pos[B]:], (sent, txt))
check("...the keeper is told which page's anchors they are", sent and f"{A} anchors scoped to it with no open item left: {SOLO}" in sent[0][1], sent)

print(("ok" if not fails else "FAILED") + f": anchor counts scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
