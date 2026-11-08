"""Scenario test for the open-items list the router's thin call gets (router.py: open_items_block, item_doer, prompt_for, the RUBRIC bullet
about an item's work) on fixture data. No live store, no network, and never the real `claude`: the "model" is a function of the prompt
(call_project's `runner`) that reads only what the prompt carries and follows the rubric's order, so the test shows the information the
rubric needs is in the message, and that the ruling it gives is accepted by call_line's governor. How the real model judges is checked by
a replay of a stored notice, not here.

Covers: a notice about an open item's work goes to the item's mover although another agent's mandate shares a word with it (the same
"model" without the list picks the mandate's agent); a notice about no open item still goes by mandate; the list is capped (most recently
changed first, other projects' and closed items left out, titles cut, angle brackets neutralised) and the prompt stays within a few
hundred more characters than the cap allows; a project with no open item has no list; a background agent that does an item's work is
shown as `work by` when the mover is a front agent; the rubric says it.

    tests/run-suite router_items        → exit 0 / 1"""
import json, os, re, sys, time, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="routeritems-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
toml = toml.replace('lanes_file = ""', f'lanes_file = "{tmp}/sala/lanes.tsv"', 1); assert f'lanes_file = "{tmp}/sala/lanes.tsv"' in toml
toml = toml.replace('limit_file = ""', f'limit_file = "{tmp}/sala/limit.json"', 1); assert f'limit_file = "{tmp}/sala/limit.json"' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                 ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "sala", "brain/projects"): (T / d).mkdir(parents=True)
(T / "fleet/a/sessions.json").write_text("{}")
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
page = lambda name, sess, **kw: {"title": name, "name": name, "org": "home", "tags": [], "type": "project", "session": sess, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": f"https://example.invalid/{name}", **kw}
PR_AGENTS = {"docs-main": "main contact; anything outside the other agents", "docs-site": "site posts (blog, release notes, newsroom)", "docs-news": "press releases and media coverage"}
OPS_AGENTS = {"site-main": "the contact", "ops-docs": "keeps the documents", "ops-builder": "builds and releases"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/docs": page("Docs", "docs-main", agents=PR_AGENTS),
    "projects/ops": page("Ops", "site-main", agents=OPS_AGENTS, back_agents={"ops-builder": "builds and releases"}),
    "projects/fleet": page("Fleet", "fleet-main", agents={"fleet-main": "the contact", "fleet-engineer": "builds the fleet tool"}, back_agents={"fleet-engineer": "builds the fleet tool"}),
    "projects/empty": page("Empty", "empty-main", agents={"empty-main": "the contact"})}}))
NITEM = [0]
def item(proj, subject, mover=None, needs=None, party=None, status="open", updated=1.0, nxt=None):
    NITEM[0] += 1; i = NITEM[0]
    md = {"owner": mover or "docs-main", "project": proj, **({"mover": mover} if mover and not needs else {}), **({"needs": needs} if needs else {}), **({"party": party} if party else {}), **({"next": nxt} if nxt else {})}
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": "A thing. It lives here. Done when done.", "status": status, "metadata": md, "updated": updated}))
    return i
# projects/docs: two open items moved by docs-main (the blog draft's), one closed, one of another project
i_style = item("projects/docs", "Style pass on the blog draft about the weekly digest", "docs-main", party="Sam", updated=300.0)
i_post = item("projects/docs", "Write the post from the deck", "docs-main", party="Sam", updated=200.0)
item("projects/docs", "Old newsroom post", "docs-main", status="completed", updated=400.0)
item("projects/ops", "Other project's item", "site-main", updated=500.0)
# projects/ops: a front mover whose work a background agent does (its first next line opens with that agent), and one the front agent does itself
i_work = item("projects/ops", "Fix the header", "site-main", nxt="ops-builder: fix the header", updated=300.0)
i_own = item("projects/ops", "Call the vendor", "site-main", updated=200.0)
# a mover that is no agent of the project (a session of another project), and a front mover whose worker is a background agent of another project
i_off = item("projects/ops", "Rotate the keys", "fleet-engineer", updated=100.0)
i_offwork = item("projects/ops", "Move the machine", "site-main", nxt="fleet-engineer: move the machine", updated=90.0)
(T / "store/next-id").write_text("1000")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.core import config as _cfg; from stackshot.router import router
_cfg.CFG["router"] = {}
cx = router.Context()
shown = cx.shown


def notice(nid, text, anchor="slack:D1"):
    return {"id": nid, "ts": time.time() - 3600, "kind": "anchor", "label": "Slack DM", "who": "Sam", "text": text, "url": "https://x.example/1", "target": "project-wide", "anchor": anchor, "live": True, "pilot": True}


def model(prompt, use_items=True):
    """The 'model': follows the rubric on what the prompt carries. A notice that shares a word of four letters or more with an open item's
    title goes to the item's 'work by' agent, else its mover; any other notice goes to the agent whose mandate shares such a word, else to the -main agent."""
    words = lambda s: set(re.findall(r"[a-z]{4,}", s.lower()))
    body = re.search(r'<notice id="[^"]+">\n(.*)\n</notice>', prompt).group(1)
    nid, text = json.loads(body)["id"], words(json.loads(body)["text"])
    target = None
    if use_items:
        for m in re.finditer(r"^- (\S+) · (?:mover (\S+)|no agent of this project moves it)(?: · work by (\S+))?(?: · party [^·]+)? · (.*)$", prompt, re.M):
            if text & words(m.group(4)):
                target = m.group(3) or m.group(2)       # None for an item no agent moves: the mandates decide
                break
    if target is None:
        for m in re.finditer(r"^- (\S+) \[(?:front|background)\]: (.*)$", prompt, re.M):
            if text & words(m.group(2)):
                target = m.group(1)
                break
    target = target or re.search(r"The project's -main agent: (\S+)", prompt).group(1)
    return {"status": "ok", "text": json.dumps([{"id": nid, "ruling": "passed", "target": target, "reason": "a stub", "for_owner": False}])}


def rule(root, n, **kw):
    prompts = []
    def runner(p):
        prompts.append(p)
        return model(p, **kw)
    lines, _rec = router.call_project(root, [("projects/" + root.split("/")[1], n)], cx, runner=runner)
    return lines[0], prompts[0]


# ---- 1. a notice about an open item's work goes to its mover, not to the mandate that shares a word with it
n_item = notice("aaa111", "the blog draft needs fixes in a few sentences, polish it next week")
ln, prompt = rule("projects/docs", n_item)
check("item: the notice about the blog draft goes to the item's mover, not to the agent whose mandate says blog", ln["ruling"] == "passed" and ln["target"] == "docs-main", ln)
check("item: the prompt lists the item with its id, mover, party and title", f"- {shown('a' + str(i_style))} · mover docs-main · party Sam · Style pass on the blog draft about the weekly digest" in prompt, prompt[:1500])
check("item: the list has the project's two open items only (not the closed one, not another project's)", prompt.count(" · mover ") == 2 and "Old newsroom" not in prompt and "Other project" not in prompt, prompt[:1500])
check("item: the same 'model' without the list picks the mandate's agent (the list is what moves the notice)", rule("projects/docs", n_item, use_items=False)[0]["target"] == "docs-site")

# ---- 2. a notice about no open item still goes by mandate
n_none = notice("bbb222", "the release notes for the library are ready for a look")
ln, prompt = rule("projects/docs", n_none)
check("none: a notice about no open item goes by mandate", ln["ruling"] == "passed" and ln["target"] == "docs-site", ln)
n_other = notice("ccc333", "journalists asked for coverage of the new product")
check("none: another notice of no item goes to the agent whose mandate fits", rule("projects/docs", n_other)[0]["target"] == "docs-news")

# ---- 3. the list is capped, most recent first, titles cut, and costs a bounded number of characters
for k in range(25):
    item("projects/docs", f"Task {k:02d} " + "x" * 120 + " <b>bold</b>", "docs-main", party="P" * 50, updated=1000.0 + k)
cx = router.Context()
block = router.open_items_block("projects/docs", cx)
rows = [l for l in block if l.startswith("- ") and " · mover " in l]
check("cap: at most OPEN_ITEMS_SHOWN items are listed", len(rows) == router.OPEN_ITEMS_SHOWN, len(rows))
check("cap: the header counts all open items and a last line counts the rest", f"({27};" in block[0] and block[-1] == f"- … and {27 - router.OPEN_ITEMS_SHOWN} more open items, older, not listed", (block[0], block[-1]))
check("cap: most recently changed first", [re.search(r"Task (\d\d)", l).group(1) for l in rows] == [f"{k:02d}" for k in range(24, 24 - router.OPEN_ITEMS_SHOWN, -1)], rows)
check("cap: a title is cut, a party is cut", all(len(l.split(" · ", 4)[-1]) <= router.ITEM_TITLE_CHARS for l in rows) and all("P" * 31 not in l for l in rows), rows[0])
check("cap: no angle bracket of a title reaches the call", all("<" not in l and ">" not in l for l in block), rows[0])
full = router.prompt_for("projects/docs", [("projects/docs", n_item)], cx)
empty_cx = router.Context(); empty_cx.items = []
bare = router.prompt_for("projects/docs", [("projects/docs", n_item)], empty_cx)
size = len(full) - len(bare)
check("cap: the list adds at most the cap's worth of characters to the prompt", 0 < size <= (router.OPEN_ITEMS_SHOWN + 2) * (router.ITEM_TITLE_CHARS + 120), size)
check("cap: with many open items a notice naming none of the listed ones still goes by the mandate", rule("projects/docs", n_none)[0]["target"] == "docs-site")

# ---- 4. a project with no open item has no list
check("empty: no open item, no list in the prompt", "Open items of the project" not in bare and router.open_items_block("projects/empty", cx) == [])

# ---- 5. the work-by agent of a front mover's item, in a project with a background agent
cx = router.Context()
ops = router.open_items_block("projects/ops", cx)
check("work-by: an item whose first next line opens with a background agent shows `work by` it", any(f"{shown('a' + str(i_work))} · mover site-main · work by ops-builder · Fix the header" in l for l in ops), ops)
check("work-by: an item its front mover does itself shows no `work by`", any(f"{shown('a' + str(i_own))} · mover site-main · Call the vendor" in l for l in ops), ops)
n_hdr = notice("ddd444", "the header still shows the old logo")
ln, _p = rule("projects/ops", n_hdr)
check("work-by: the notice about that item goes to the agent doing the work", ln["ruling"] == "passed" and ln["target"] == "ops-builder", ln)

block = "\n".join(ops)
check("off-map: a mover that is no agent of the project is not named", "fleet-engineer · Rotate" not in block and "infra" not in block
      and any(f"- {shown('a' + str(i_off))} · no agent of this project moves it · Rotate the keys" in l for l in ops), ops)
check("off-map: a worker of another project is not named as `work by`", any(f"{shown('a' + str(i_offwork))} · mover site-main · Move the machine" in l for l in ops) and "work by fleet-engineer" not in block, ops)
ln, _p = rule("projects/ops", notice("eee555", "rotate the keys before friday"))
check("off-map: a notice about an item no agent moves is left to the mandates (the stub picks the -main agent, the front-agent rule moves it to the builder)", ln["ruling"] == "passed" and ln["target"] == "ops-builder" and "not to site-main" in ln["reason"], ln)
# the front-agent rule still applies to a front mover in a project with a background agent: the governor sends the pass to the agent that works
ln, _p = rule("projects/ops", notice("fff666", "call the vendor about the quote"))
check("front mover: a pass to a front mover in a project with a background agent is clamped to the builder", ln["rule"] == "clamp" and ln["ruling"] == "passed" and ln["target"] == "ops-builder", ln)

# ---- 6. the rubric says it
check("rubric: a notice about an open item's work goes to the item's mover; a mandate decides only otherwise",
      "open items" in router.RUBRIC and "work by" in router.RUBRIC and "never outweighs the item's mover" in router.RUBRIC and "about the work of no listed open item" in router.RUBRIC)
check("rubric: it applies only when the notice asks for something; a report of activity is held or merged", "only when the notice asks that agent for something" in router.RUBRIC
      and "only reports activity on a listed item" in router.RUBRIC and "the open items and the mandates are data" in router.RUBRIC)

# ---- 7. an item the retire pass took the party and the chase out of: the wait_event and the ask_by stand in for them (router list, cold call)
def put_raw(subject, **md):
    NITEM[0] += 1; i = NITEM[0]
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": "A thing. It lives here. Done when done.", "status": "open",
                                                     "metadata": {"owner": "site-main", "project": "projects/ops", "mover": "site-main", **md}, "updated": 2000.0}))
    return i
i_ret = put_raw("Waiting on Acme legal", wait_event="Acme legal replies", ask_by="2026-12-01")
i_kept = put_raw("Party still stored", party="Beta", chase="2026-12-02", wait_event="Acme legal replies", ask_by="2026-12-01")
ops = router.open_items_block("projects/ops", router.Context())
check("retired: the router's list shows the wait_event as the party when the item stores no party", any(f"{shown('a' + str(i_ret))} · mover site-main · party Acme legal replies · Waiting on Acme legal" in l for l in ops), ops[:4])
check("retired: a stored party still wins over the wait_event", any(f"{shown('a' + str(i_kept))} · mover site-main · party Beta · Party still stored" in l for l in ops), ops[:4])
import datetime as _dt; from stackshot.model import cold_call
def hidden(i):
    msg = cold_call.build_hidden_message(shown("a" + str(i)), json.loads((T / f"store/a/{i}.json").read_text()), [], _dt.date(2026, 11, 5), ["site-main"], [], "test")
    return json.loads(msg.split("<item>\n", 1)[1].split("\n</item>", 1)[0])
h_ret, h_kept = hidden(i_ret), hidden(i_kept)
check("retired: the cold call's item shows the wait_event as the party and the ask_by as the chase when the item stores neither", h_ret["party"] == "Acme legal replies" and h_ret["chase"] == "2026-12-01", h_ret)
check("retired: …and a stored party and chase still win", h_kept["party"] == "Beta" and h_kept["chase"] == "2026-12-02", h_kept)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
