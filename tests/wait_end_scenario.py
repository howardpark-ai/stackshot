"""tests/wait_end_scenario.py: an open item whose next line waits in words for something nothing tells the item has happened (wait_end.py).

The ten-minute filing pass reads the lines of an open item's next that say "wait for board#N to close", "once other/repo#7 merges", "when hp-box is back online", "wait for the reply in <link>", and finds the ones
the item stores no wait for (no `after`, event wait, anchor wait or step proof). Where the server can set the wait with certainty it does (`server._wait_end_fix`, a History line, one message to the mover), and where
it cannot it asks the mover a specific question; a wait for an event no type reports goes to the builder once. Checked against a scratch store and config (no port, no real server, no model call, no network):

  1  detect     each kind of gap, and what is no gap: a negated wait, an "or", several items, another session's step, the owner's step, a held item, an item that already names the wait
  2  findings   the wait-end finding names the line and what to say; the settle window; modes fix | ask | off; the event-missing finding goes to the builder
  3  fix        the pass sets `after`, an event wait (pull request, machine), an anchor wait, a step proof, a backstop day: stored waiting, the mover as post_wake_mover, History, one message
  4  send back  clear_after, clear_wait and step_proof "none" are the mover's no: the server leaves that line alone, a changed line is a new fact
  5  never      nothing closed, no ask written, an item the owner moves or a front agent's item is left alone, at most ten fixes a pass, a second pass changes nothing
  6  after      a line the server fixed is not asked about again once the wait ended; a stored day that is no date is no backstop; a refused gate leaves the anchors list as it was;
             the facts are built once per pass; an odd or missing [audit] key reads as the default
  7  handled     a line the server fixed or the mover sent back does not hide a new waiting line; one item's failure is skipped; a project-wide anchor; the backstop guard
  8  whole step  a handled step is its whole text (a new continuation line or an edited first line is new); an item line stays handled when its target closes; broad words of other lines stay
  9  same step   a handled step stays handled when the facts read it differently later (a bare #n no longer anchored, a machine with no fleet view): one key, the step's hash

    tests/run-suite wait_end        -> exit 0 / 1"""
import datetime as dt, json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))
tmp = _scratch.mkdtemp(prefix="waitend-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-echo-main")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now = time.time()
DAY, HOUR = 86400.0, 3600.0
ZONE_OFFSET = 4 * HOUR
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("9000"); (T / "store/anchors.json").write_text("{}")
OLD = now - 3 * HOUR                          # an item last written three hours ago: past the settle window
DESC = "- A thing, finished when it works"
def item(i, nxt, mover="team-back", status="open", updated=None, **meta):
    up = OLD if updated is None else updated
    d = {"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": up, "written_at": up, "written_by": mover,
         "state_updated": up, "confirmed": up,
         "metadata": {"owner": U["home-front"], "project": "projects/alpha", "state": "doing", "needs": [mover], "next": nxt, **meta}}
    (T / f"store/g/{i}.json").write_text(json.dumps(d))
    return f"g{i}", d
def rd(i): return json.loads((T / f"store/g/{i}.json").read_text())
mt = lambda i: rd(i)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.audit import audit_checks as AC; from stackshot.audit import audit_run as AR; from stackshot.model import model as MODEL; from stackshot.waits import server_fixes as SF; from stackshot.waits import wait_end as WE; from stackshot.core import config as CFG; from stackshot.waits import watchers as WATCH
from stackshot.service import event_waits as evwaits_svc
from stackshot.service import telling
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
telling.front_sender = lambda who: False
server._evwait_preread = lambda kind, phrase: None                       # no GitHub call
server._own_repo = lambda: "acme/widgets"
BOXES = {"hp-box": ("hp-box", {}), "hp-up": ("hp-up", {"puller": time.time()})}
evwaits_svc.evw_boxes = lambda: dict(BOXES)
from stackshot.fleet import liveness as LV
LV.puller_online = lambda rec: bool(rec)
BACK = "team-back"
log = lambda i: [e["text"] for e in ((mt(i).get("stall") or {}).get("log") or [])]
ROLES = {"team-back": {"role": "background"}, "home-other": {"role": "background"}, "home-front": {"role": "front"}, "alpha-builder": {"role": "background"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(**kw): return AR.Env(roles=ROLES, fallback=lambda p: "home-front", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None), deliver=deliver, sessions=lambda: None,
                             pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}}, **kw)
FIXING = dict(wait_end=server._wait_end_fix, wait_facts=server._wait_end_facts)
def wipe(): (T / "state/audit/filing.json").unlink(missing_ok=True); sent.clear()
def cats(findings, cat): return sorted(re.sub(r"\D", "", f["id"]) for f in findings if f["category"] == cat)
def store_items(): return {f"g{p.stem}": json.loads(p.read_text()) for p in (T / "store/g").glob("*.json")}

# ================================================================ 1. detect
FACTS = WE.Facts(machines={"hp-box": "hp-box", "hp-up": "hp-up"}, online=frozenset({"hp-up"}), own_repo="acme/widgets", released=frozenset(),
                 item_prs=lambda gid: (), item_anchors=lambda gid: (), anchor_url=lambda u: u.startswith("https://github.com/"))
OPEN = {"board#" "812": "g812", "board#" "813": "g813"}
def gaps(nxt, mover="team-back", state="alive", **meta):
    i = 8001
    _gid, d = item(i, nxt, mover, **meta)
    return WE.item_gaps("g8001", d["metadata"], mover, state, FACTS, lambda ref: OPEN.get(ref, ""), lambda a, b: a == b, now)
g = gaps("team-back: wait for board#" "812 to close, then write the summary")
check("1 an open item the line waits for, named in no after: an after fix", len(g) == 1 and g[0].kind == WE.ITEM and g[0].plan.get("op") == "after" and g[0].plan["ids"] == ["g812"], g)
g = gaps("team-back: wait for board#" "812 to close, then write the summary", after=["g812"])
check("1 …an item that already names it in after is no gap", g == [], g)
g = gaps("team-back: wait for board#" "812 or board#" "813 to close")
check("1 …an alternative is a question, not a fix", len(g) == 1 and g[0].kind == WE.ITEM and g[0].plan == {} and "alternative" in g[0].evidence, g)
g = gaps("team-back: wait for board#" "812 and board#" "813 to close")
check("1 …two items are a question", len(g) == 1 and g[0].plan == {} and "several" in g[0].evidence, g)
g = gaps("team-back: write the notes\nteam-back: wait for board#" "812 to close")
check("1 …a line among other open work is a question (an item waits only wholly)", len(g) == 1 and g[0].plan == {} and "other work" in g[0].evidence, g)
g = gaps("team-back: wait for board#" "999 to close")
check("1 …a closed or unknown item is nothing to wait for", g == [], g)
g = gaps("home-other: wait for board#" "812 to close")
check("1 …another session's step is not read", g == [], g)
g = gaps(f"{server.OWNER}: wait for board#" "812 to close")
check("1 …nor is the owner's", g == [], g)
g = gaps("team-back: do not wait for board#" "812 to close; write the summary now")
check("1 …a negated wait is no wait", g == [], g)
g = gaps("team-back: wait for board#" "812 to close", hold=True)
check("1 …a held item is never touched", g == [], g)
g = gaps("team-back: once other/repo#7 is merged, write the summary")
check("1 pull request: the line is the item's only step, so an event wait pr_merged on the repository named", len(g) == 1 and g[0].kind == WE.PR and g[0].plan.get("op") == "event" and g[0].plan["phrase"] == "pr_merged other/repo#7", g)
g = gaps("team-back: wait for acme/widgets#7 to be released")
check("1 …an own-repository release is pr_released", len(g) == 1 and g[0].plan.get("phrase") == "pr_released acme/widgets#7", g)
g = gaps("team-back: wait for other/repo#7 to be released")
check("1 …a repository release.sh does not release is waited on for its merge", len(g) == 1 and g[0].plan.get("phrase") == "pr_merged other/repo#7", g)
g = gaps("team-back: write the notes\nteam-back: wait for other/repo#7 to merge")
check("1 …a pure wait step among other work gets a step proof, not an item wait", len(g) == 1 and g[0].plan.get("op") == "proof" and g[0].plan["proof"] == "pr_merged other/repo#7" and g[0].plan["pos"] == 2, g)
g = gaps("team-back: wait for #7 to merge")
check("1 …a bare #n the item is not anchored to is a question naming the form", len(g) == 1 and g[0].plan == {} and "owner/repo#7" in g[0].evidence, g)
g = gaps("team-back: wait for other/repo#7 and other/repo#8 to merge")
check("1 …two pull requests are a question", len(g) == 1 and g[0].plan == {}, g)
g = gaps("team-back: wait for other/repo#7")
check("1 …a pull request with no merge or release word is no gap (the line may wait for anything about it)", g == [], g)
g = gaps("team-back: wait for other/repo#7 to be merged and released")
check("1 …one that names both is a question: which one ends the wait is the mover's to say", len(g) == 1 and g[0].plan == {} and "whether" in g[0].evidence, g)
g = gaps("team-back: wait for hp-box to come back online")
check("1 machine: a box_online event wait on the fleet name", len(g) == 1 and g[0].kind == WE.BOX and g[0].plan.get("phrase") == "box_online hp-box", g)
g = gaps("team-back: wait for hp-up to come back online")
check("1 …a machine online now: the wait has already ended, a question and no fix", len(g) == 1 and g[0].plan == {} and "already ended" in g[0].evidence, g)
g = gaps("team-back: wait for hp-nope-1 to come back online")
check("1 …a machine the server does not know is a question that lists the machines", len(g) == 1 and g[0].plan == {} and "hp-box" in g[0].evidence, g)
g = gaps("team-back: wait for the reply in https://github.com/acme/widgets/issues/5")
check("1 link: an anchor wait on the link", len(g) == 1 and g[0].kind == WE.URL and g[0].plan.get("op") == "anchor" and g[0].plan["url"].endswith("/issues/5"), g)
g = gaps("team-back: ship PR #7")
check("1 delivery: a step that is only `ship PR #7` gets its proof", len(g) == 1 and g[0].kind == WE.DELIVERY and g[0].plan == {"op": "proof", "proof": "pr_released acme/widgets#7", "pos": 1}, g)
g = gaps("team-back: ship PR #7 and then tell the users about it")
check("1 …a delivery inside a longer step is a question", len(g) == 1 and g[0].kind == WE.DELIVERY and g[0].plan == {}, g)
g = gaps("team-back: wait for the nightly run to finish")
check("1 an event no type reports: a gap of the event kind, never a fix", len(g) == 1 and g[0].kind == WE.EVENT and g[0].plan == {} and "scheduled job" in g[0].cls, g)
g = gaps("team-back: write the summary")
check("1 a step that waits for nothing is no gap", g == [], g)
w = gaps("x", state="waiting", wait_kind="event", wait_event="pr_merged other/repo#7", post_wake_mover="team-back", needs=[])
check("1 a stored event wait with no backstop gets a backstop day", len(w) == 1 and w[0].kind == WE.STORED and w[0].plan == {"op": "backstop"}, w)
w = gaps("x", state="waiting", wait_kind="event", wait_event="pr_merged other/repo#7", post_wake_mover="team-back", until="2099-01-01", needs=[])
check("1 …a stored event wait whose until is its backstop has none to fix (the wait's end date is read from until, not only from ask_by and wake)", w == [], w)
w = gaps("x", state="waiting", wait_kind="event", wait_event="pr_merged other/repo#7", post_wake_mover="team-back", until="someday", needs=[])
check("1 …an until that is no date is no backstop: the stored event wait is asked for one", len(w) == 1 and w[0].plan == {"op": "backstop"}, w)
w = gaps("x", state="waiting", wait_kind="event", wait_event="nonsense words", post_wake_mover="team-back", ask_by="2099-01-01", needs=[])
check("1 …a stored event the server cannot read is a question", len(w) == 1 and w[0].plan == {}, w)
w = gaps("x", state="waiting", wait_kind="event", wait_event="job_run nightly", post_wake_mover="team-back", ask_by="2099-01-01", needs=[])
check("1 …a stored job_run wait (no type reports it) goes to the builder", len(w) == 1 and w[0].kind == WE.EVENT, w)
check("1 tokens: a changed line is a new token, a kind is read back from it", WE.token("item", "a1", "team-back: wait for board#" "1") != WE.token("item", "a1", "team-back: wait for board#" "1 to close") and WE.kind_of_token(WE.token("pr", "x#1", "t")) == "pr")

# ================================================================ 2. findings
item(9101, "team-back: wait for board#" "9102 to close, then write the summary")
item(9102, "home-other: build the thing")
S = {"g9101": rd(9101), "g9102": rd(9102)}
fs, _fl = AC.filing_findings(S, {}, now, env())
w101 = [f for f in fs if f["category"] == "wait-end" and f["id"].endswith("9101")]
check("2 the wait-end finding names the line, what is missing and what to say", len(w101) == 1 and "waits for" in w101[0]["detail"] and "no `after`" in w101[0]["detail"] and "after=" in w101[0]["fix"], fs)
check("2 …and replaces the generic reads-as-wait finding for the same line", not [f for f in fs if f["category"] == "reads-as-wait" and f["id"].endswith("9101")], fs)
fresh = {"g9101": rd(9101)}; fresh["g9101"]["updated"] = fresh["g9101"]["written_at"] = fresh["g9101"]["state_updated"] = now - 600
fs, _fl = AC.filing_findings({**S, **fresh}, {}, now, env())
check("2 a mover still at work on its next (written ten minutes ago) is left alone before the pass fixes anything", not [f for f in fs if f["category"] == "wait-end"], fs)
orig_mode = CFG.audit_wait_end
try:
    CFG.audit_wait_end = lambda: "ask"
    fs, _fl = AC.filing_findings({**S, **fresh}, {}, now, env())
    check("2 [audit] wait_end = ask: the question goes at once, as a finding with no fix", len([f for f in fs if f["category"] == "wait-end"]) == 1 and not [f for f in fs if f.get("gap")], fs)
    CFG.audit_wait_end = lambda: "off"
    fs, _fl = AC.filing_findings(S, {}, now, env())
    check("2 [audit] wait_end = off: the rule finds nothing", not [f for f in fs if f["category"] in ("wait-end", "event-missing")], fs)
finally:
    CFG.audit_wait_end = orig_mode
item(9103, "team-back: wait for the nightly run to finish and then report")
fs, _fl = AC.filing_findings({"g9103": rd(9103)}, {}, now, env())
em = [f for f in fs if f["category"] == "event-missing"]
check("2 an event no type reports: an event-missing finding for the builder, and no wait-end question to the mover", len(em) == 1 and em[0].get("to") == CFG.audit_builder() and "event type" in em[0]["fix"] and not [f for f in fs if f["category"] == "wait-end"], fs)
wipe()
r = AR.filing_pass(now=now, items={"g9103": rd(9103)}, anchors={}, env=env())
n_sent = len([m for m in sent if m[0] == CFG.audit_builder() and "event-missing" in m[1]])
r = AR.filing_pass(now=now + 12 * HOUR, items={"g9103": rd(9103)}, anchors={}, env=env())
r = AR.filing_pass(now=now + 40 * HOUR, items={"g9103": rd(9103)}, anchors={}, env=env())
check("2 …it is sent to the builder once and never repeated or escalated", n_sent == 1 and len([m for m in sent if m[0] == CFG.audit_builder() and "event-missing" in m[1]]) == 1, [(m[0], m[1][:100]) for m in sent])
check("2 nothing is set on the item and the pass writes nothing for it", "after" not in mt(9103) and mt(9103).get("state") == "doing" and not log(9103), mt(9103))

# ================================================================ 3. fix: the pass sets the wait
for p in (T / "store/g").glob("*.json"): p.unlink()
item(9201, "team-back: wait for board#" "9202 to close, then write the summary")
item(9202, "home-other: build the thing")
wipe()
r = AR.filing_pass(now=now, items=store_items(), anchors={}, env=env(**FIXING))
m = mt(9201)
check("3 after: the pass sets after on the item it waits for", m.get("after") == ["g9202"], m)
check("3 …the item waits on an item's close, with the mover as post_wake_mover and no stored mover", MODEL.derive(rd(9201)).state == MODEL.WAITING and m.get("post_wake_mover") == BACK and "mover" not in m and m.get("wait_kind") == "item", m)
check("3 …a backstop day is set (now plus cap_days), and the stored phase is waiting on an item", bool(ab_(m)) and (m.get("phase"), m.get("waits_on")) == ("waiting", "item"), m)
check("3 …History has one line saying what was set and how to send it back", len(log(9201)) == 1 and "after=" in log(9201)[0] and "clear_after" in log(9201)[0], log(9201))
check("3 …the fix is recorded, and the wait-end finding is not sent (the message is the audit's retired)", any(SF.mark_tokens(m, SF.WAIT_END)) and not [x for x in sent if "· wait-end ·" in x[1]], (m.get(SF.MARK), sent))
check("3 …one fyi message to the mover names the item and the way back", len([x for x in sent if x[0] == BACK]) == 1 and sent[0][2] is True and "clear_after" in sent[0][1] and "9201" in sent[0][1], sent)
check("3 …the record says what the pass did", [re.sub(r"\D", "", x) for x in r.get("wait_end", {}).get("fixed", [])] == ["9201"], r)
check("3 …nothing closed and no ask written", rd(9201)["status"] == "open" and not mt(9201).get("ask") and not mt(9201).get("needs") == ["decision"], mt(9201))
sent.clear()
r = AR.filing_pass(now=now + 600, items=store_items(), anchors={}, env=env(**FIXING))
check("3 a second pass changes nothing and sends nothing about it", r["fresh"] == 0 and not [x for x in sent if x[0] == BACK] and len(log(9201)) == 1 and not r["wait_end"]["fixed"], (r, sent))

item(9211, "team-back: wait for other/repo#7 to be merged, then write the summary")
item(9212, "team-back: wait for hp-box to come back online")
item(9213, "team-back: wait for the reply in https://github.com/acme/widgets/issues/5")
item(9214, "team-back: write the notes\nteam-back: wait for other/repo#8 to merge")
item(9215, "team-back: ship PR #9")
item(9216, "x", needs=[], wait_kind="event", wait_event="pr_merged other/repo#7", post_wake_mover=BACK, state=None)
for i in (9211, 9212, 9213, 9214, 9215, 9216):
    mt_ = rd(i); mt_["metadata"].pop("state", None) if i == 9216 else None; (T / f"store/g/{i}.json").write_text(json.dumps(mt_))
wipe()
r = AR.filing_pass(now=now, items=store_items(), anchors={}, env=env(**FIXING))
check("3 pull request: an event wait pr_merged on the pull request, mover as post_wake_mover", mt(9211).get("wait_kind") == "event" and mt(9211).get("wait_event") == "pr_merged other/repo#7" and mt(9211).get("post_wake_mover") == BACK and MODEL.derive(rd(9211)).state == MODEL.WAITING, mt(9211))
check("3 machine: a box_online event wait", mt(9212).get("wait_kind") == "event" and mt(9212).get("wait_event") == "box_online hp-box", mt(9212))
check("3 link: an anchor wait, with the link added to the anchors scoped to the item", mt(9213).get("wait_kind") == "anchor" and mt(9213).get("wait_anchor", "").endswith("/issues/5")
      and any(e["url"].endswith("/issues/5") and "g9213" in (e.get("items") or []) for e in json.loads((T / "store/anchors.json").read_text()).get("projects/alpha", [])), (mt(9213), (T / "store/anchors.json").read_text()))
check("3 step proof: the step carries its proof and the item stays alive", list((mt(9214).get("step_proof") or {}).values()) == ["pr_merged other/repo#8"] and MODEL.derive(rd(9214)).state == MODEL.ALIVE, mt(9214))
check("3 delivery: a step that is only `ship PR #9` gets its proof", list((mt(9215).get("step_proof") or {}).values()) == ["pr_released acme/widgets#9"], mt(9215))
check("3 a stored event wait with no backstop gets one", bool(ab_(mt(9216))) and mt(9216).get("wait_event") == "pr_merged other/repo#7" and len(log(9216)) == 1 and "backstop" in log(9216)[0], (mt(9216), log(9216)))
check("3 each fix has a History line and a record", all(len(log(i)) == 1 and SF.mark_tokens(mt(i), SF.WAIT_END) for i in (9211, 9212, 9213, 9214, 9215, 9216)), [(i, log(i)) for i in (9211, 9212, 9213, 9214, 9215, 9216)])
check("3 …the mover gets one message for all the items", len([x for x in sent if x[0] == BACK]) == 1 and all(str(i) in sent[0][1] for i in (9211, 9212, 9213, 9214, 9215, 9216)), sent)

# ================================================================ 4. send back
sent.clear()
server._update("g9201", sender=BACK, clear_after=True, clear_wait=True, mover=BACK)
check("4 clear_after sends the server's after back: the line is recorded as declined and no longer marked", not mt(9201).get("after") and any(SF.declined(mt(9201), SF.WAIT_END, t) for t in [WE.token("item", "board#" "9202", "team-back: wait for board#" "9202 to close, then write the summary")] + list((mt(9201).get(SF.DECLINED) or {}).get(SF.WAIT_END, []))) and not SF.mark_tokens(mt(9201), SF.WAIT_END), mt(9201))
fix_len = len(log(9201))
r = AR.filing_pass(now=now + 900, items=store_items(), anchors={}, env=env(**FIXING))
check("4 …the next pass leaves that line alone and asks nothing about it", not mt(9201).get("after") and len(log(9201)) == fix_len and not [x for x in sent if "9201" in x[1] and "wait-end" in x[1]], (mt(9201), sent))
d9201 = rd(9201); d9201["metadata"]["next"] = "team-back: wait for board#" "9202 to close, then write the final summary"; (T / "store/g/9201.json").write_text(json.dumps(d9201))      # a legacy line: a write of this shape is refused now
r = AR.filing_pass(now=now + 4 * HOUR, items=store_items(), anchors={}, env=env(**FIXING))
check("4 …a changed line is a new fact: the server sets the wait again", mt(9201).get("after") == ["g9202"], mt(9201))
server._update("g9212", sender=BACK, clear_wait=True, mover=BACK)
check("4 clear_wait sends a server-set event wait back: declined, wait gone", not mt(9212).get("wait_kind") and any(t.startswith("box:") for t in (mt(9212).get(SF.DECLINED) or {}).get(SF.WAIT_END, [])), mt(9212))
r = AR.filing_pass(now=now + 900, items=store_items(), anchors={}, env=env(**FIXING))
check("4 …and is not set again", not mt(9212).get("wait_kind"), mt(9212))
server._update("g9215", sender=BACK, step_proof=[{"step": 1, "proof": "none"}])
check("4 step_proof none sends a server-set proof back: no proof, declined", not mt(9215).get("step_proof") and any(t.startswith("delivery:") for t in (mt(9215).get(SF.DECLINED) or {}).get(SF.WAIT_END, [])), mt(9215))
r = AR.filing_pass(now=now + 900, items=store_items(), anchors={}, env=env(**FIXING))
check("4 …and is not set again", not mt(9215).get("step_proof"), mt(9215))

# ================================================================ 5. never
for p in (T / "store/g").glob("*.json"): p.unlink()
item(9301, f"{server.OWNER}: wait for board#" "9302 to close", mover=server.OWNER, needs=[server.OWNER])
item(9302, "home-other: build the thing")
item(9303, "home-front: wait for board#" "9302 to close", mover="home-front", needs=["home-front"])
item(9304, "team-back: wait for board#" "9302 to close", hold=True, wake=(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)).strftime("%Y-%m-%d"))
wipe()
r = AR.filing_pass(now=now, items=store_items(), anchors={}, env=env(**FIXING))
check("5 an item the owner moves, a front agent's item and a held item are not touched", all(not mt(i).get("after") and not log(i) for i in (9301, 9303, 9304)), [(i, mt(i)) for i in (9301, 9303, 9304)])
for p in (T / "store/g").glob("*.json"): p.unlink()
item(9400, "home-other: build the thing")
for k in range(12):
    item(9410 + k, "team-back: wait for board#" "9400 to close, then report")
wipe()
r = AR.filing_pass(now=now, items=store_items(), anchors={}, env=env(**FIXING))
done = [k for k in range(12) if mt(9410 + k).get("after")]
check("5 at most ten fixes a pass", len(done) == WE.FIX_CAP and len(r["wait_end"]["fixed"]) == WE.FIX_CAP, (len(done), r.get("wait_end")))
r = AR.filing_pass(now=now + 600, items=store_items(), anchors={}, env=env(**FIXING))
check("5 …the rest wait for the next pass", len([k for k in range(12) if mt(9410 + k).get("after")]) == 12, [k for k in range(12) if mt(9410 + k).get("after")])
check("5 a fix closes nothing and writes no ask on any item", all(rd(9410 + k)["status"] == "open" and not mt(9410 + k).get("ask") for k in range(12)))
try:
    CFG.audit_wait_end = lambda: "ask"
    for p in (T / "store/g").glob("*.json"): p.unlink()
    item(9501, "team-back: wait for board#" "9502 to close, then report"); item(9502, "home-other: build the thing")
    wipe()
    r = AR.filing_pass(now=now, items=store_items(), anchors={}, env=env(**FIXING))
    check("5 [audit] wait_end = ask: the question is sent and nothing is set", not mt(9501).get("after") and [x for x in sent if "wait-end" in x[1] and x[0] == BACK], (mt(9501), sent))
finally:
    CFG.audit_wait_end = orig_mode

# ================================================================ 6. after the fix, a stored day that is no date, a refused gate, one set of facts, an odd key
for p in (T / "store/g").glob("*.json"): p.unlink()
item(9601, "team-back: wait for other/repo#31 to be merged, then write the summary")
before = rd(9601)
wipe()
r = AR.filing_pass(now=now, items=store_items(), anchors={}, env=env(**FIXING))
fixed = rd(9601)
check("6 setup: the pass set an event wait on the pull request and marked the line", mt(9601).get("wait_event") == "pr_merged other/repo#31" and SF.mark_tokens(mt(9601), SF.WAIT_END), mt(9601))
back_alive = json.loads(json.dumps(before)); back_alive["metadata"][SF.MARK] = fixed["metadata"][SF.MARK]; back_alive["metadata"]["next"] = fixed["metadata"]["next"]
(T / "store/g/9601.json").write_text(json.dumps(back_alive))             # the wait ended (the pull request merged): alive again, the same open line, the server's mark kept
check("6 …the wait ended: the item is alive again with the line unchanged", MODEL.derive(rd(9601)).state == MODEL.ALIVE and mt(9601)["next"] == before["metadata"]["next"], mt(9601))
wipe()
fs, _fl = AC.filing_findings(store_items(), {}, now + 4 * HOUR, env(**FIXING))
check("6 a line the server already fixed is no gap when the item is alive again: no wait-end finding", not [f for f in fs if f["category"] in ("wait-end", "event-missing")], fs)
r1 = AR.filing_pass(now=now + 4 * HOUR, items=store_items(), anchors={}, env=env(**FIXING))
r2 = AR.filing_pass(now=now + 16 * HOUR, items=store_items(), anchors={}, env=env(**FIXING))
check("6 …two passes later still no question to the mover or the builder, and nothing changed on the item", not [x for x in sent if "9601" in x[1]] and not r1["wait_end"]["fixed"] and not r2["wait_end"]["fixed"]
      and not mt(9601).get("wait_kind") and not log(9601), (sent, r1.get("wait_end"), r2.get("wait_end")))
d = rd(9601); d["metadata"]["next"] = "team-back: wait for other/repo#32 to be merged, then write the summary"; (T / "store/g/9601.json").write_text(json.dumps(d))
fs, _fl = AC.filing_findings(store_items(), {}, now + 4 * HOUR, env(**FIXING))
check("6 …a changed line is a new fact: it is a gap again", [f["category"] for f in fs if f["id"].endswith("9601")].count("wait-end") == 1, fs)

for p in (T / "store/g").glob("*.json"): p.unlink()
ISO = re.compile(r"^\d{4}-\d\d-\d\d")
item(9611, "x", needs=[], wait_kind="event", wait_event="pr_merged other/repo#7", post_wake_mover=BACK, ask_by="nonsense")
d = rd(9611); d["metadata"].pop("state", None); (T / "store/g/9611.json").write_text(json.dumps(d))
item(9612, "team-back: wait for board#" "9613 to close, then report", wake="sometime")
item(9613, "home-other: build the thing")
item(9614, "team-back: wait for the reply in https://github.com/acme/widgets/issues/9", wake="whenever")
wipe()
r = AR.filing_pass(now=now, items=store_items(), anchors={}, env=env(**FIXING))
check("6 a stored ask_by that is no date is no backstop: the pass writes a real day and says so", ISO.match(str(ab_(mt(9611)))) and len(log(9611)) == 1 and ab_(mt(9611)) in log(9611)[0], (mt(9611), log(9611)))
check("6 …an item wait set beside a wake that is no date gets a real backstop day", mt(9612).get("after") == ["g9613"] and ISO.match(str(ab_(mt(9612)))), mt(9612))
check("6 …an anchor wait too", mt(9614).get("wait_kind") == "anchor" and ISO.match(str(ab_(mt(9614)))), mt(9614))
check("6 …and none of them is left as a wait nothing can end", all(WATCH.can_end(mt(i)) for i in (9611, 9612, 9614)), [mt(i) for i in (9611, 9612, 9614)])
item(9615, "x", needs=[], wait_kind="event", wait_event="pr_merged other/repo#7", post_wake_mover=BACK, wake="2099-01-01")
d = rd(9615); d["metadata"].pop("state", None); (T / "store/g/9615.json").write_text(json.dumps(d))
wipe()
r = AR.filing_pass(now=now + 4 * HOUR, items=store_items(), anchors={}, env=env(**FIXING))
check("6 a wake that is a date is the backstop as it stands (nothing to fix)", wk_(mt(9615)) == "2099-01-01" and not ab_(mt(9615)) and not log(9615), mt(9615))

for p in (T / "store/g").glob("*.json"): p.unlink()
item(9621, "team-back: wait for the reply in https://github.com/acme/widgets/issues/21")
anchors_before = (T / "store/anchors.json").read_text()
real_wow = server._watch_on_write
def refusing(*a, **k): raise server.ToolError("Refused: the wait is refused by a later gate")
server._watch_on_write = refusing
try:
    wipe()
    r = AR.filing_pass(now=now, items=store_items(), anchors={}, env=env(**FIXING))
finally:
    server._watch_on_write = real_wow
check("6 a gate that refuses after the anchor was added leaves the item as it was", not mt(9621).get("wait_kind") and not mt(9621).get("wait_anchor") and not log(9621) and not SF.mark_tokens(mt(9621), SF.WAIT_END), mt(9621))
check("6 …and the anchors list as it was", json.loads((T / "store/anchors.json").read_text()) == json.loads(anchors_before), (T / "store/anchors.json").read_text())
wipe()
r = AR.filing_pass(now=now + 4 * HOUR, items=store_items(), anchors={}, env=env(**FIXING))
check("6 …and with the gate working the same pass sets the wait and the anchor", mt(9621).get("wait_kind") == "anchor"
      and any(e["url"].endswith("/issues/21") for e in json.loads((T / "store/anchors.json").read_text()).get("projects/alpha", [])), (mt(9621), (T / "store/anchors.json").read_text()))

# the facts are built once per pass, and a pull request lookup is made only for a line that names one
for p in (T / "store/g").glob("*.json"): p.unlink()
for k in range(6):
    item(9630 + k, "team-back: write the notes, then report" if k % 2 else "team-back: wait for board#" "9640 to close, then report")
item(9640, "home-other: build the thing"); item(9641, "team-back: wait for other/repo#41 to be merged")
calls = {"facts": 0, "prs": 0}
def counting_facts():
    calls["facts"] += 1
    f = server._wait_end_facts()
    def prs(gid): calls["prs"] += 1; return f.item_prs(gid)
    return WE.Facts(machines=f.machines, online=f.online, own_repo=f.own_repo, released=f.released, item_prs=prs, item_anchors=f.item_anchors, anchor_url=f.anchor_url)
fs, _fl = AC.filing_findings(store_items(), {}, now, env(wait_end=server._wait_end_fix, wait_facts=counting_facts))
check("6 filing_findings builds the facts once for all the open items", calls["facts"] == 1, calls)
check("6 …and asks for the pull requests an item is anchored to only for the one line that names a bare or foreign pull request", calls["prs"] <= 1, calls)
def failing_facts(): raise RuntimeError("fleet view unreadable")
fs, _fl = AC.filing_findings(store_items(), {}, now, env(wait_end=server._wait_end_fix, wait_facts=failing_facts))
check("6 …facts that cannot be read leave the rule reading the items themselves, not the whole pass failing", [f for f in fs if f["category"] == "wait-end"], fs)

# an odd or missing [audit] key reads as the default
real_get = CFG.get
def with_audit(**vals):
    def get(sect, key=None, *a, **k):
        if sect == "audit" and key in vals: return vals[key]
        return real_get(sect, key, *a, **k)
    return get
try:
    for odd in (None, "", 5, True, ["fix"], "BOGUS", " Off "):
        CFG.get = with_audit(wait_end=odd)
        want = "off" if odd == " Off " else "fix"
        if CFG.audit_wait_end() != want: check(f"6 [audit] wait_end = {odd!r} reads as {want}", False, CFG.audit_wait_end())
    check("6 [audit] wait_end: missing, empty, a number, a boolean, a list or an unknown word read as fix; the mode word is case and space blind", True)
    for odd, want in ((None, 60.0), ("", 60.0), (True, 60.0), ("x", 60.0), (-3, 60.0), ("30", 30.0), (0, 0.0), (float("nan"), 60.0)):
        CFG.get = with_audit(wait_end_settle_minutes=odd)
        if CFG.audit_wait_end_settle_minutes() != want: check(f"6 [audit] wait_end_settle_minutes = {odd!r} reads as {want}", False, CFG.audit_wait_end_settle_minutes())
    check("6 [audit] wait_end_settle_minutes: missing, empty, a boolean, a word, a negative number or NaN read as 60; a number or numeric text as given", True)
    CFG.get = with_audit(wait_end="BOGUS", wait_end_settle_minutes="x")
    item(9650, "team-back: wait for board#" "9651 to close, then report"); item(9651, "home-other: build the thing")
    fs, _fl = AC.filing_findings({"g9650": rd(9650), "g9651": rd(9651)}, {}, now, env())
    check("6 …and a pass with both odd still finds the gap", len([f for f in fs if f["category"] == "wait-end"]) == 1, fs)
finally:
    CFG.get = real_get

# ================================================================ 7. a handled line does not hide a new one; one item's failure; a project-wide anchor; the backstop guard
for p in (T / "store/g").glob("*.json"): p.unlink()
PR_LINE = "team-back: wait for other/repo#31 to be merged, then write the summary"
VENDOR = "team-back: wait for the vendor to answer, then reply"
item(9701, PR_LINE + "\n" + VENDOR)
item(9702, VENDOR)
item(9703, PR_LINE)
fs, _fl = AC.filing_findings({"g9701": rd(9701)}, {}, now, env(**FIXING))
first = [f for f in fs if f["category"] == "wait-end"]
check("7 setup: the pull request line is a wait-end gap, and the vendor line (a kind the rule has no fix for) reads as a wait", len(first) == 1 and "other/repo#31" in first[0]["detail"]
      and any(f["category"] == "reads-as-wait" and "vendor" in f["detail"] for f in fs), fs)
check("7 …the generic finding speaks only of the vendor line while the rule words the other", not any(f["category"] == "reads-as-wait" and "other/repo#31" in f["detail"] for f in fs), fs)
tokens = [g.token for g in WE.item_gaps("g9701", mt(9701), "team-back", "alive", server._wait_end_facts(), lambda ref: "", lambda a, b: a == b, now)]
check("7 setup: one token for the pull request line", len(tokens) == 1, tokens)
d = rd(9701); SF.mark(d["metadata"], SF.WAIT_END, tokens[0]); (T / "store/g/9701.json").write_text(json.dumps(d))        # the server fixed that line (the wait since ended)
fs, _fl = AC.filing_findings(store_items(), {}, now, env(**FIXING))
mine = [f for f in fs if f["id"].endswith("9701")]
check("7 a line the server fixed and a new unrelated waiting line: the new line still gets reads-as-wait", [f["category"] for f in mine] == ["reads-as-wait"] and "vendor" in mine[0]["detail"], mine)
check("7 …and nothing is said of the handled line", not any("other/repo#31" in f["detail"] for f in mine), mine)
d = rd(9701); d["metadata"].pop(SF.MARK); SF.decline(d["metadata"], SF.WAIT_END, tokens[0]); (T / "store/g/9701.json").write_text(json.dumps(d))
fs, _fl = AC.filing_findings(store_items(), {}, now, env(**FIXING))
mine = [f for f in fs if f["id"].endswith("9701")]
check("7 a line the mover sent back is handled the same way", [f["category"] for f in mine] == ["reads-as-wait"] and "vendor" in mine[0]["detail"], mine)
check("7 the vendor line alone is a reads-as-wait finding", [f["category"] for f in fs if f["id"].endswith("9702")] == ["reads-as-wait"], fs)
d = rd(9703); SF.mark(d["metadata"], SF.WAIT_END, WE.item_gaps("g9703", mt(9703), "team-back", "alive", server._wait_end_facts(), lambda ref: "", lambda a, b: a == b, now)[0].token)
(T / "store/g/9703.json").write_text(json.dumps(d))
fs, _fl = AC.filing_findings(store_items(), {}, now, env(**FIXING))
check("7 the handled line alone gives nothing", not [f for f in fs if f["id"].endswith("9703")], fs)

# one item's failure is skipped, the rest of the pass goes on
for p in (T / "store/g").glob("*.json"): p.unlink()
item(9711, "team-back: wait for the reply in https://github.com/acme/widgets/issues/11"); item(9712, "team-back: wait for board#" "9713 to close, then report"); item(9713, "home-other: build the thing")
item(9714, "x", needs=[], wait_kind="anchor", post_wake_mover=BACK, state=None)
d = rd(9714); d["metadata"].pop("state", None); (T / "store/g/9714.json").write_text(json.dumps(d))
def raising_anchors(gid): raise RuntimeError("anchors file unreadable")
def bad_facts():
    f = server._wait_end_facts()
    return WE.Facts(machines=f.machines, online=f.online, own_repo=f.own_repo, released=f.released, item_prs=f.item_prs, item_anchors=raising_anchors, anchor_url=f.anchor_url)
fs, _fl = AC.filing_findings(store_items(), {}, now, env(wait_end=server._wait_end_fix, wait_facts=bad_facts))
check("7 a Facts whose item_anchors raises: the item that asks for it (a stored anchor wait) is skipped, the pass goes on and finds the other items", not [f for f in fs if f["id"].endswith("9714")]
      and len([f for f in fs if f["category"] == "wait-end"]) >= 1, fs)

# a project-wide anchor for the link already exists: the add is a no-op and the undo changes nothing
for p in (T / "store/g").glob("*.json"): p.unlink()
from stackshot.anchors import anchors as ANC
LINK = "https://github.com/acme/widgets/issues/12"
st = {}; ANC.add(st, "projects/alpha", [LINK], None, by="team-back"); ANC.save(st)
wide = json.loads((T / "store/anchors.json").read_text())
item(9721, f"team-back: wait for the reply in {LINK}")
real_wow = server._watch_on_write
server._watch_on_write = refusing
try:
    wipe()
    r = AR.filing_pass(now=now, items=store_items(), anchors={}, env=env(**FIXING))
finally:
    server._watch_on_write = real_wow
check("7 a project-wide anchor already on the list: a refused gate leaves it, and the item as it was", json.loads((T / "store/anchors.json").read_text()) == wide and not mt(9721).get("wait_kind"), mt(9721))
wipe()
r = AR.filing_pass(now=now + 4 * HOUR, items=store_items(), anchors={}, env=env(**FIXING))
check("7 …and the same pass with the gate working sets the anchor wait without adding a second anchor", mt(9721).get("wait_kind") == "anchor" and json.loads((T / "store/anchors.json").read_text()) == wide, (mt(9721), (T / "store/anchors.json").read_text()))

# a backstop day that would not end the wait is refused, not recorded as a fix
for p in (T / "store/g").glob("*.json"): p.unlink()
item(9731, "x", needs=[], wait_kind="event", wait_event="pr_merged other/repo#7", post_wake_mover=BACK)
d = rd(9731); d["metadata"].pop("state", None); (T / "store/g/9731.json").write_text(json.dumps(d))
real_can_end = WATCH.can_end
WATCH.can_end = lambda meta: False
try:
    wipe()
    r = AR.filing_pass(now=now, items=store_items(), anchors={}, env=env(**FIXING))
finally:
    WATCH.can_end = real_can_end
check("7 a backstop that does not make the wait endable is refused: nothing written, no record of a fix", not ab_(mt(9731)) and not log(9731) and not SF.mark_tokens(mt(9731), SF.WAIT_END) and not r["wait_end"]["fixed"], (mt(9731), r.get("wait_end")))

# ================================================================ 8. a handled step is its whole text; a handled item line stays handled when its target closes; broad words of other lines
def toks_of(i, items_open=lambda ref: ""):
    return [g.token for g in WE.item_gaps(f"g{i}", mt(i), "team-back", "alive", server._wait_end_facts(), items_open, lambda a, b: a == b, now)]
def mark_all(i, toks, how="mark"):
    d = rd(i)
    for t in toks: (SF.mark if how == "mark" else SF.decline)(d["metadata"], SF.WAIT_END, t)
    (T / f"store/g/{i}.json").write_text(json.dumps(d))
def mine_of(i, extra=None):
    fs, fl = AC.filing_findings({**store_items(), **(extra or {})}, {}, now, env(**FIXING))
    return [f for f in fs if f["id"].endswith(str(i))], [x for x in fl if x["id"].endswith(str(i))]

for p in (T / "store/g").glob("*.json"): p.unlink()
PR_LINE = "team-back: wait for other/repo#31 to be merged, then write the summary"
SUB = "  also wait for the vendor to answer"
item(9801, PR_LINE)
t = toks_of(9801)
check("8 setup: the pull request line has one gap", len(t) == 1, t)
mark_all(9801, t)
check("8 …handled, it gives nothing", not mine_of(9801)[0], mine_of(9801))
d = rd(9801); d["metadata"]["next"] = PR_LINE + "\n" + SUB; (T / "store/g/9801.json").write_text(json.dumps(d))
got, _x = mine_of(9801)
check("8 a continuation line added under a handled step is a new fact: the step is read again", got and any(f["category"] in ("wait-end", "reads-as-wait") for f in got), got)
t2 = toks_of(9801)
check("8 …its token is not the old one (the token covers the whole step)", t2 and t2[0] != t[0], (t, t2))
mark_all(9801, t2)
check("8 a handled step with its continuation gives nothing", not mine_of(9801)[0], mine_of(9801))
d = rd(9801); d["metadata"]["next"] = PR_LINE + "\n  also wait for the vendor to reply"; (T / "store/g/9801.json").write_text(json.dumps(d))
check("8 …and an edit of the continuation only is a new fact again", mine_of(9801)[0], mine_of(9801))

d = rd(9801); d["metadata"]["next"] = "team-back: wait for other/repo#31 to be merged, then write the final summary"; (T / "store/g/9801.json").write_text(json.dumps(d))
check("8 a handled step whose first line is edited is a new fact", [f["category"] for f in mine_of(9801)[0]].count("wait-end") == 1, mine_of(9801))

# the item-kind line: marked, then its target closes
for p in (T / "store/g").glob("*.json"): p.unlink()
ITEM_LINE = "team-back: wait for board#" "9812 to close, then write the summary"
isopen = lambda ref: "g9812" if str(ref).endswith("9812") else ""
for how in ("mark", "decline"):
    for p in (T / "store/g").glob("*.json"): p.unlink()
    item(9811, ITEM_LINE); item(9812, "home-other: build the thing")
    t = toks_of(9811, isopen)
    check(f"8 setup ({how}): the item line has one gap while its target is open", len(t) == 1 and t[0].startswith(WE.ITEM), t)
    mark_all(9811, t, how)
    closed = rd(9812); closed["status"] = "closed"
    got, _x = mine_of(9811, {"g9812": closed})
    check(f"8 an item line the server fixed ({how}) and whose target has closed: the item is alive again and nothing is asked about the line", MODEL.derive(rd(9811), now, lambda x: False).state == MODEL.ALIVE and not got, got)
    got, _x = mine_of(9811, {"g9812": closed})
    d = rd(9811); d["metadata"]["next"] += "\nteam-back: wait for the vendor to answer, then reply"; (T / "store/g/9811.json").write_text(json.dumps(d))
    got, _x = mine_of(9811, {"g9812": closed})
    check(f"8 …and a new waiting line beside it ({how}) still gets its own reads-as-wait finding", [f["category"] for f in got] == ["reads-as-wait"] and "vendor" in got[0]["detail"], got)

# two handled steps and one new
for p in (T / "store/g").glob("*.json"): p.unlink()
item(9821, PR_LINE + "\nteam-back: wait for hp-box to come back online\nteam-back: wait for the vendor to answer, then reply")
tt = [x for x in toks_of(9821) if x.startswith((WE.PR, WE.BOX))]
check("8 setup: the pull request and the machine lines have a gap each", len(tt) == 2, toks_of(9821))
mark_all(9821, tt)
got, _x = mine_of(9821)
check("8 two handled steps and one new: only the new line gets a finding", [f["category"] for f in got] == ["reads-as-wait"] and "vendor" in got[0]["detail"], got)

# the broad words of the other lines are kept
for p in (T / "store/g").glob("*.json"): p.unlink()
item(9831, PR_LINE + "\nteam-back: send the notes when they are ready")
tt = [x for x in toks_of(9831) if x.startswith(WE.PR)]
mark_all(9831, tt)
got, flags = mine_of(9831)
check("8 a handled step leaves the broad-word candidates of the other lines (a flag for the model check), not a finding", not got and flags and flags[0]["words"], (got, flags))
for p in (T / "store/g").glob("*.json"): p.unlink()
item(9832, PR_LINE)
mark_all(9832, [x for x in toks_of(9832) if x.startswith(WE.PR)])
got, flags = mine_of(9832)
check("8 …and with no other line there is no flag", not got and not flags, (got, flags))

# ================================================================ 9. a handled step stays handled when the facts read differently later (an empty Facts)
EMPTY = lambda: WE.Facts()
anch = WE.Facts(machines={"hp-box": "hp-box"}, online=frozenset(), own_repo="acme/widgets", released=frozenset(), item_prs=lambda gid: ("other/repo#7",), item_anchors=lambda gid: (), anchor_url=lambda u: False)
def first_tokens(i, facts, kinds):
    return [g.token for g in WE.item_gaps(f"g{i}", mt(i), "team-back", "alive", facts, lambda ref: "", lambda a, b: a == b, now) if g.token.startswith(kinds)]
for label, i, line, kinds in (("a bare #n the item is anchored to", 9901, "team-back: wait for #7 to merge, then write the summary", (WE.PR,)),
                              ("a machine the fleet view knows", 9902, "team-back: wait for hp-box to come back online", (WE.BOX,))):
    for p in (T / "store/g").glob("*.json"): p.unlink()
    item(i, line)
    fs, _fl = AC.filing_findings(store_items(), {}, now, env(wait_end=server._wait_end_fix, wait_facts=EMPTY))
    check(f"9 setup ({label}): with an empty Facts the line is a wait-end question", [f["category"] for f in fs if f["id"].endswith(str(i))].count("wait-end") == 1, fs)
    tk = first_tokens(i, anch, kinds)
    check(f"9 setup: with the facts it was fixed under, the line has a token", len(tk) == 1, tk)
    mark_all(i, tk)
    wipe()
    fs, _fl = AC.filing_findings(store_items(), {}, now, env(wait_end=server._wait_end_fix, wait_facts=EMPTY))
    check(f"9 {label}, marked, read with an empty Facts: no finding", not [f for f in fs if f["id"].endswith(str(i))], fs)
    r = AR.filing_pass(now=now + 4 * HOUR, items=store_items(), anchors={}, env=env(wait_end=server._wait_end_fix, wait_facts=EMPTY))
    check(f"9 …and no message, no fix, nothing written", not [x for x in sent if str(i) in x[1]] and not r["wait_end"]["fixed"] and not mt(i).get("wait_kind") and not log(i), (sent, r.get("wait_end")))
    d = rd(i); d["metadata"].pop(SF.MARK); SF.decline(d["metadata"], SF.WAIT_END, tk[0]); (T / f"store/g/{i}.json").write_text(json.dumps(d))
    fs, _fl = AC.filing_findings(store_items(), {}, now, env(wait_end=server._wait_end_fix, wait_facts=EMPTY))
    check(f"9 {label}, sent back by the mover, read with an empty Facts: no finding", not [f for f in fs if f["id"].endswith(str(i))], fs)

print(f"{'FAILED' if fails else 'ok'}: wait end scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
