"""Scenario test for the item model (model.py, step 1, PR 1: the data layer) — fixture data, no live store, no network, no server socket.

An item is dead (closed), alive (someone in the perimeter is working: one mover) or waiting (nothing happens until something outside arrives). The model is additive: new
optional fields (goal; mover and then; wait_kind with wait_anchor, wait_event and ask_by; post_wake_mover) beside the ones an item already had, and a pure reading of them.

  * model.derive: dead | alive | waiting for every state an item can still store (fixture data here: no call sets or clears a state any more, tests/retired_inputs_scenario.py) (your-call and your-step → alive, the owner the mover; doing → alive, the agent; queued → alive, the
    builder; outside → waiting on an anchor event or the owner's relay; blocked → waiting on an item's close; parked and verifying → waiting on a time; completed →
    dead), for an item with no stored state (states.derive's reading), and the effective mover, `then` and post-wake mover: what is stored (marked explicit) or section 3's
    defaults (marked as such); a wake on an alive item is the mover's check-back; a clash between fields is listed, not hidden.
  * The `model:` line of get and the brief, and `goal:`; `derived: …` names what the item does not store.
  * The fields through create and update (and get): stored as given, "none" and the clear_ flags drop them, a bad kind or date is refused with nothing written, they are
    filing edits (no clock moves), a close drops the mover and the wait and keeps the goal.
  * The mirror's History line for a change of these fields.
  * Every revision records its author: written_by (a name: the session, the owner for his board answer, a script's label, or `server`) and written_by_id (the session's id,
    or `board`), set by every save.

    tests/run-suite model        → exit 0 / 1"""
import asyncio, contextlib, datetime, importlib.util, io, json, os, re, sys, pathlib, tempfile, time, logging, hashlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="modeltest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the item model's data layer, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", subject=None, desc=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su,
                                                              "metadata": {"owner": owner or U["home-front"], "project": "projects/alpha", "next": "do the thing", **meta}}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.waits import waiting as W; from stackshot.web import render; from stackshot.github import ghsync; from stackshot.model import states; from stackshot.model import model
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda gid, owner, note, tag="wake": None
FB = server._fallback_mover("projects/alpha")      # the project's builder, else its -main agent (here its first front agent): what an item nothing else names is moved by, never its creator
assert FB == "home-front", FB
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
ZONE_OFFSET = 4 * 3600      # the instance zone is Asia/Dubai: UTC+4, no daylight saving
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
BACK, OTHER, GONE = "team-back", "home-other", "home-gone"      # as the update path stores a name the registry does not know
UB, UO = U["team-back"], U["home-other"]

from stackshot.model.model import Model, Wait   # noqa: E402
OWN = model.owner_display()            # the owner as the instance names him ("the owner" in the example config)
NOW = now0
FUT, PAST = day(5), day(-3)
ASK = "Decide: ship the thing now · Recommend: yes · Stakes: a week of delay · By: no date"
mt = lambda i, letter="a": rd(i, letter)["metadata"]
raw = lambda i, letter="a": (T / f"store/{letter}/{i}.json").read_text()
def upd(i, **kw): return server._update(f"a{i}", sender="home-front", **kw)
def refused_nw(name, i, f, *want):
    was = raw(i); refused(name, f, *want); check(name + " (nothing written)", raw(i) == was, None)
def I(status="open", **meta):
    """an item dict for the pure functions"""
    return {"status": status, "metadata": {"owner": U["home-front"], "project": "projects/alpha", **meta}}
def D(**meta): return model.derive(I(**meta), NOW)

# ================================================================ the derived state, for every state today has (design section 2)
m_ = D(state="your-call", needs=["decision", BACK], ask=ASK)
check("map: your-call (stored) → alive, the owner the mover", m_.state == "alive" and m_.today == "your-call" and not m_.today_derived and model.is_owner(m_.mover) and m_.mover == OWN, m_)
check("map: …defaulted (nothing stored), and `then` the first session in needs", not m_.mover_explicit and m_.then == BACK and not m_.then_explicit, m_)
check("map: …with only a decision in needs, then is none (the creator takes no part; the default mover answers after his call)", D(state="your-call", needs=["decision"], ask=ASK).then == "", D(state="your-call", needs=["decision"], ask=ASK))
m_ = D(state="your-step", step="gh pr merge 1", needs=[])
check("map: your-step (no decision in needs) → alive, the owner the mover, no then (never the creator)", m_.state == "alive" and m_.mover == OWN and m_.then == "" and not m_.mover_explicit, m_)
m_ = D(state="doing", expected_by=day(2), needs=[BACK, OTHER])
check("map: doing → alive, the agent the mover (the first session in needs)", m_.state == "alive" and m_.mover == BACK and not m_.mover_explicit and m_.then == "", m_)
m_ = D(state="doing", expected_by=day(2), needs=[])
check("map: …with no session in needs, the project's builder, else its -main agent, never the creator", m_.state == "alive" and m_.mover == FB, m_)
m_ = D(state="queued", needs=[OTHER, BACK])
check("map: a stored queued (retired) loads as doing → alive, the first session in needs the mover", m_.state == "alive" and m_.mover == OTHER and m_.today == "doing", m_)
m_ = D(state="outside", needs=["external"], party="Acme legal", chase=day(4))
check("map: outside (no anchor) → waiting on the owner's relay: the party, the chase day as ask-by, the owner post-wake", m_.state == "waiting" and m_.wait.kind == "relay" and not m_.wait.kind_explicit
      and m_.wait.event == "Acme legal" and m_.wait.until == day(4) and m_.wait.post_wake_mover == OWN and not m_.wait.post_explicit and m_.mover == "", m_)
m_ = model.derive(I(state="outside", needs=["external"], party="Acme legal", chase=day(4)), NOW, anchored=lambda it: True)
check("map: …an anchor scoped to the item → waiting on an anchor event", m_.state == "waiting" and m_.wait.kind == "anchor" and m_.wait.event == "Acme legal", m_)
m_ = D(state="outside", needs=["external"], party="Acme legal", chase=day(4), wait_anchor="https://x/pull/1", wait_event="PR merged", wake=FUT)
check("map: …a stored wait_anchor (and event) → an anchor wait, the wake its backstop", m_.wait.kind == "anchor" and m_.wait.anchor == "https://x/pull/1" and m_.wait.event == "PR merged" and m_.wait.backstop == FUT and m_.wait.until == "", m_)
m_ = D(state="blocked", needs=[BACK], after=["a18", "a19"], supplies="the schema")
check("map: blocked → waiting on an item's close (the after list), the first session post-wake", m_.state == "waiting" and m_.wait.kind == "item" and m_.wait.after == ("a18", "a19") and m_.wait.post_wake_mover == BACK, m_)
m_ = D(state="parked", needs=[BACK], hold=True, wake=FUT, cap_ok={"wake": FUT, "by": "the owner", "quote": "park it"})
check("map: parked → waiting on a time (the wake), with his words noted", m_.state == "waiting" and m_.wait.kind == "time" and m_.wait.until == FUT and m_.wait.owner_words and not m_.wait.due and m_.wait.post_wake_mover == BACK, m_)
m_ = D(state="parked", needs=[], hold=True, wake=FUT, wait_basis={"text": "visit booked", "wake": FUT, "by": "x", "at": 1.0})
check("map: …a wait_basis is the reason (and with no session in needs the post-wake mover is the project's default mover, never the creator)", m_.wait.basis == "visit booked" and not m_.wait.owner_words and m_.wait.post_wake_mover == FB, m_)
m_ = D(state="verifying", needs=[BACK], proof="uptime", end=day(6))
check("map: verifying → waiting on a time (the end date)", m_.state == "waiting" and m_.wait.kind == "time" and m_.wait.until == day(6) and m_.wait.post_wake_mover == BACK, m_)
m_ = model.derive(I(status="completed", outcome="done", state="doing"), NOW)
check("map: completed → dead, with nothing else", m_ == Model("dead") and not m_.mover and m_.wait is None, m_)
# no stored state: states.derive's reading
check("derived: needs decision → alive, the owner", D(needs=["decision"]).state == "alive" and D(needs=["decision"]).today_derived and D(needs=["decision"]).mover == OWN, D(needs=["decision"]))
check("derived: needs external → waiting (relay)", D(needs=["external"]).state == "waiting" and D(needs=["external"]).wait.kind == "relay" and D(needs=["external"]).today == "outside", D(needs=["external"]))
check("derived: a hold with a wake → waiting on a time", D(needs=[BACK], hold=True, wake=FUT).wait.kind == "time", D(needs=[BACK], hold=True, wake=FUT))
check("derived: an open after link → waiting on an item; a closed one blocks nothing → alive",
      D(needs=[BACK], after=["a18"]).wait.kind == "item" and model.derive(I(needs=[BACK], after=["a18"]), NOW, after_open=lambda it: []).state == "alive", None)
check("derived: a session in needs → alive, that session; nothing else → alive, the builder / the keeper",
      D(needs=[BACK]).mover == BACK and D(needs=[]).mover == FB and D().state == "alive", None)
check("derived: a stored value that is no state is ignored: read from the fields", D(state="bogus", needs=[BACK]).state == "alive" and D(state="bogus", needs=[BACK]).today_derived, D(state="bogus", needs=[BACK]))

# ================================================================ explicit fields: what is stored wins, and says so
m_ = D(state="doing", expected_by=day(2), needs=[BACK], mover=OTHER, then="ops-x")
check("explicit: a stored mover is the mover, marked explicit", m_.mover == OTHER and m_.mover_explicit, m_)
check("explicit: …then is not read beside a mover that is not the owner (it stands only while he moves the item), and no conflict is named", m_.then == "" and not m_.then_explicit and not m_.conflicts, m_)
m_ = D(state="your-call", needs=["decision", BACK], ask=ASK, mover="oliver", then="ops-x")
check("explicit: mover=oliver is stored as the owner's name and is the owner; then explicit", m_.mover == OWN and m_.mover_explicit and m_.then == "ops-x" and m_.then_explicit and not m_.conflicts, m_)
check("explicit: …owner_moves and next_mover read it", m_.owner_moves and m_.next_mover == "ops-x", m_)
m_ = D(state="parked", needs=[BACK], hold=True, wake=FUT, wait_basis={"text": "x", "wake": FUT, "by": "x", "at": 1.0}, post_wake_mover=OTHER)
check("explicit: a stored post_wake_mover is the one, marked explicit", m_.wait.post_wake_mover == OTHER and m_.wait.post_explicit and m_.next_mover == OTHER, m_)
m_ = D(needs=[BACK], wait_kind="time", wake=FUT)
check("explicit: a stored wait_kind makes the item waiting whatever its fields say", m_.state == "waiting" and m_.wait.kind == "time" and m_.wait.kind_explicit and m_.wait.until == FUT, m_)
m_ = D(state="doing", expected_by=day(2), needs=[BACK], wait_kind="item", after=["a18"])
check("explicit: …on an item whose stored state is alive the wait wins and the clash is listed", m_.state == "waiting" and m_.wait.kind == "item" and any("wait_kind=item" in c for c in m_.conflicts), m_)
m_ = D(needs=[BACK], wait_kind="anchor", wait_anchor="https://x/issues/9", wait_event="a reply", wake=FUT, post_wake_mover=OTHER)
check("explicit: an anchor wait: the anchor, its event, the wake as backstop", m_.wait.anchor == "https://x/issues/9" and m_.wait.event == "a reply" and m_.wait.backstop == FUT and m_.wait.until == "", m_)
m_ = D(needs=[BACK], wait_kind="relay", wait_event="Robin's reply on the contract", ask_by=day(9), post_wake_mover=BACK)
check("explicit: a relay wait: the party or event, the ask-by day, and a stored post-wake mover over the owner default", m_.wait.until == day(9) and m_.wait.event == "Robin's reply on the contract" and m_.wait.post_wake_mover == BACK and m_.wait.post_explicit, m_)
m_ = D(needs=[BACK], wait_kind="relay", wait_event="Robin's reply")
check("explicit: …a relay with no post_wake_mover: the owner (section 4: the ask-by day turns the item to him), defaulted", m_.wait.post_wake_mover == OWN and not m_.wait.post_explicit, m_)
m_ = D(needs=[BACK], wait_kind="nonsense", wake=FUT)
check("explicit: a wait_kind that is no kind is ignored", m_.state == "alive" and not m_.conflicts, m_)
m_ = D(state="doing", expected_by=day(2), needs=[BACK], wake=FUT)
check("alive + a wake: the wake is the mover's check-back, the item stays alive", m_.state == "alive" and m_.checkback == FUT and m_.wait is None and not m_.conflicts, m_)
m_ = D(needs=[BACK], hold=True, wake=FUT, mover=OTHER)
check("mover on a waiting item: the one who picks it up when the wait ends, no conflict; the item's own mover stays empty while it waits", m_.state == "waiting" and m_.wait.mover == OTHER and m_.wait.mover_explicit and m_.picker == OTHER and m_.mover == "" and not m_.conflicts, m_)
m_ = D(state="doing", expected_by=day(2), needs=[BACK], ask_by=day(3), post_wake_mover=OTHER)
check("conflict: wait fields stored on an alive item are named", m_.state == "alive" and any("ask_by" in c and "post_wake_mover" in c for c in m_.conflicts), m_)

# ================================================================ the time (due), and the words
ago, ahead = (datetime.datetime.fromtimestamp(NOW) - datetime.timedelta(days=3)).strftime("%Y-%m-%d"), day(5)
check("due: a wake that has come is due, one ahead is not", D(needs=[BACK], hold=True, wake=ago).wait.due and not D(needs=[BACK], hold=True, wake=ahead).wait.due, (D(needs=[BACK], hold=True, wake=ago).wait, D(needs=[BACK], hold=True, wake=ahead).wait))
check("due: a relay's ask-by day that has passed is due; an item wait whose items are all closed is due; a verifying end that passed is due",
      D(needs=[BACK], wait_kind="relay", wait_event="x", ask_by=ago).wait.due and not D(needs=[BACK], wait_kind="relay", wait_event="x", ask_by=ahead).wait.due
      and model.derive(I(needs=[BACK], wait_kind="item", after=["a18"]), NOW, after_open=lambda it: []).wait.due and not D(needs=[BACK], wait_kind="item", after=["a18"]).wait.due
      and D(state="verifying", needs=[BACK], proof="x", end=ago).wait.due, None)
lab = lambda w: {BACK: "ops-back", OTHER: "ops-other"}.get(w, w)
shown = lambda g: "board#" + g[1:]
W_ = lambda mod: model.words(mod, lab, shown)
check("words: alive, the owner the mover, with then", W_(D(state="your-call", needs=["decision", BACK], ask=ASK, mover="oliver", then=OTHER)) == f"model: alive · mover {OWN} (then ops-other)", W_(D(state="your-call", needs=["decision", BACK], ask=ASK, mover="oliver", then=OTHER)))
check("words: …defaulted fields are named at the end", W_(D(state="your-call", needs=["decision", BACK], ask=ASK)) == f"model: alive · mover {OWN} (then ops-back) · derived: mover, then", W_(D(state="your-call", needs=["decision", BACK], ask=ASK)))
check("words: alive with an agent mover and a check-back", W_(D(state="doing", expected_by=day(2), needs=[BACK], mover=BACK, wake=FUT)) == f"model: alive · mover ops-back · check-back {FUT}", W_(D(state="doing", expected_by=day(2), needs=[BACK], mover=BACK, wake=FUT)))
check("words: waiting on a time", W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", post_wake_mover=BACK)) == f"model: waiting on a time (wake {FUT}) · mover ops-back", W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", post_wake_mover=BACK)))
check("words: …derived kind and post-wake mover named", W_(D(state="blocked", needs=[BACK], after=["a18"], supplies="x")) == "model: waiting on the close of board#18 · mover ops-back · derived: wait_kind, post_wake_mover", W_(D(state="blocked", needs=[BACK], after=["a18"], supplies="x")))
check("words: an anchor wait, a relay wait, a closed item",
      W_(D(wait_kind="anchor", wait_anchor="https://x/pull/1", wait_event="PR merged", wake=FUT, post_wake_mover=BACK, needs=[BACK])) == f"model: waiting on an anchor (https://x/pull/1: PR merged; backstop wake {FUT}) · mover ops-back"
      and W_(D(wait_kind="relay", wait_event="Robin's reply", ask_by=FUT, post_wake_mover=OWN, needs=[BACK])) == f"model: waiting on news only {OWN} relays (Robin's reply; ask by {FUT}) · mover {OWN}"
      and W_(model.derive(I(status="completed"), NOW)) == "model: dead", None)
check("words: a wait with no date or anchor says so", "no wake set" in W_(D(state="parked", needs=[BACK], hold=True)) and "wait_anchor not set" in W_(D(wait_kind="anchor", needs=[BACK])) and "no anchor stored" not in W_(D(wait_kind="anchor", needs=[BACK])) and "no ask-by date" in W_(D(wait_kind="relay", needs=[BACK])), None)
check("form: check_fields: what a write may not say", model.check_fields({"wait_kind": "sometime"}) and model.check_fields({"ask_by": "next week"}) and model.check_fields({"ask_by": "2099-02-30"}) and model.check_fields({"goal": "x" * 301})
      and not model.check_fields({"wait_kind": "Relay", "ask_by": "2099-03-02", "goal": "x" * 300, "mover": "oliver"}), None)
check("form: norm_who: oliver and the owner's name are the owner; a session stays as written; blanks collapse", model.norm_who(" Oliver ") == OWN and model.norm_who(OWN.upper()) == OWN and model.norm_who("ops  x") == "ops x" and model.norm_who("") == "", None)

# ================================================================ the fields through create, update and get
NEW_GOAL = "The model's fields are stored and shown."
out = server._create(subject="[home] model fields", description=DESC, project="projects/alpha", owner="home-front", next="home-front: write it", needs=["decision"], ask=ASK,
                     goal=NEW_GOAL, mover="oliver", then="home-front")
cid = int(re.search(r"created s(\d+)", out)[1])
m = mt(cid, "s")
check("create: goal, mover and then are stored in the item's metadata (the owner's name normalised)", m.get("goal") == NEW_GOAL and m.get("mover") == OWN and m.get("then") == "home-front", m)
check("create: the reply shows the goal and the model line", f"goal: {NEW_GOAL}" in out and f"model: alive · mover {OWN} (then home-front)" in out and "model conflict" not in out, out)
check("create: …no wait field stored that was not given", not any(k in m for k in ("wait_kind", "wait_anchor", "wait_event", "ask_by", "post_wake_mover")), m)
refused("create: a wait_kind that is none of the kinds is refused", lambda: server._create(subject="[home] bad kind", description=DESC, project="projects/alpha", owner="home-front", wait_kind="soon"), "wait_kind is one of time | anchor | item | relay")
check("create: …and wrote nothing", not any(json.loads(p.read_text())["subject"] == "[home] bad kind" for p in (T / "store").glob("*/*.json")), None)
item(1, needs=["decision"], ask=ASK, subject="[home] plain item")
item(4, needs=[BACK], subject="[home] derived item")
g = server.stackshot_get("a4")
check("get: an item with none of the fields shows its model line, derived, and no goal line", "model: alive · mover team-back · derived: mover" in g and "goal:" not in g, g)
before = rd(1)
out = upd(1, goal=NEW_GOAL, mover="OLIVER", then="team-back")
m = mt(1)
check("update: goal, mover and then are stored", m["goal"] == NEW_GOAL and m["mover"] == OWN and m["then"] == "team-back", m)
check("update: …filing edits like a rank: no state clock, no confirm; only `updated` moves", rd(1)["state_updated"] == before["state_updated"] and rd(1)["confirmed"] == before["confirmed"] and rd(1)["updated"] > before["updated"], None)
check("update: …every other field stays (the stored phase apart: every save of an open item writes it)", {k: v for k, v in m.items() if k not in ("goal", "mover", "then", "phase")} == before["metadata"], (m, before["metadata"]))
check("update: …the reply and get show the goal and the model line", f"goal: {NEW_GOAL}" in out and f"model: alive · mover {OWN} (then team-back)" in out and f"model: alive · mover {OWN} (then team-back)" in server.stackshot_get("a1"), out)
check("update: …no page is owed for it", "page update" not in out.lower().replace("(pilot", ""), out[-300:])
check("update: …a goal alone names no session in needs (it is filing)", mt(1)["needs"] == ["decision"], mt(1))
item(2, needs=[BACK], subject="[home] goal only")
upd(2, goal=NEW_GOAL)
check("update: a goal alone is stored and leaves needs as it was", mt(2)["goal"] == NEW_GOAL and mt(2)["needs"] == [BACK], mt(2))
out = upd(1, wait_kind="relay", wait_event="Robin's reply on the contract", ask_by=FUT, post_wake_mover="home-front", mover="none")
m = mt(1)
check("update: a relay wait is stored (kind, event, ask-by day, post-wake mover), and mover=none drops the mover", m["wait_kind"] == "relay" and m["wait_event"] == "Robin's reply on the contract" and ab_(m) == FUT and m["post_wake_mover"] == "home-front" and "mover" not in m, m)
check("update: …get reads the item as waiting on the owner's relay, then the post-wake mover", f"model: waiting on news only {OWN} relays (Robin's reply on the contract; until {FUT}) · mover home-front" in server.stackshot_get("a1"), server.stackshot_get("a1"))
check("update: …the brief carries the model line of the item too", "model: waiting on news only" in server.stackshot_brief() and "model: alive · mover team-back" in server.stackshot_brief(), None)
server._anc.save({"projects/alpha": [{"url": "https://example.org/pull/7", "items": None, "added": now0, "by": "x"}]})      # the anchor is on the project's list (a wait on an unlisted one is refused: anchor_wait_refusal)
out = upd(1, wait_kind="anchor", wait_anchor="https://example.org/pull/7", wait_event="merged", wake=FUT)
m = mt(1)
check("update: the kind can change; the old inputs stay stored until cleared, the new ones are read", m["wait_kind"] == "anchor" and m["wait_anchor"] == "https://example.org/pull/7" and "model: waiting on an anchor (https://example.org/pull/7: merged; until" in out, out)
upd(1, clear_wait=True)
m = mt(1)
check("update: clear_wait drops the wait's fields, its until with them (the one date the wait ends on is part of the wait; after keeps its own flag)", not any(k in m for k in ("wait_kind", "wait_anchor", "wait_event", "ask_by", "post_wake_mover", "until", "wake")), m)
refused_nw("update: clear_wait does not go with a new wait field", 1, lambda: upd(1, clear_wait=True, wait_kind="time"), "clear_wait drops", "wait_kind")
import inspect as _inspect
_params, _doc = _inspect.signature(server.stackshot_update).parameters, server._MODEL_FORM
check("update: wait_anchor and wait_event are real parameters of the tool and each is listed in its description with its own line, as ask_by and post_wake_mover are",
      all(f in _params for f in ("wait_anchor", "wait_event", "ask_by", "post_wake_mover")) and "; wait_anchor=<" in _doc and "; wait_event=<" in _doc and "; ask_by=YYYY-MM-DD" in _doc and "; post_wake_mover=<" in _doc, _doc[:900])
refused_nw("update: …clear_goal does not go with a new goal", 1, lambda: upd(1, clear_goal=True, goal="x"), "clear_goal drops goal")
refused_nw("update: a wait_kind that is no kind is refused", 1, lambda: upd(1, wait_kind="eventually"), "wait_kind is one of")
refused_nw("update: an ask_by that is no date is refused", 1, lambda: upd(1, wait_kind="relay", ask_by="soon"), "ask_by is YYYY-MM-DD")
refused_nw("update: a goal over 300 characters is refused", 1, lambda: upd(1, goal="g" * 301), "goal is one line of at most 300")
upd(1, clear_goal=True, clear_then=True, clear_mover=True)
check("update: clear_goal, clear_then and clear_mover each drop theirs", not any(k in mt(1) for k in ("goal", "mover", "then")), mt(1))
upd(1, goal="again", then="none")
check("update: \"none\" clears one field and leaves the others", mt(1)["goal"] == "again" and "then" not in mt(1), mt(1))
item(3, needs=[BACK], subject="[home] closing", mover="team-back", then="home-front", goal="The close drops the mover", wait_kind="time", wait_event="x", ask_by=FUT, post_wake_mover="team-back")
server._update("a3", sender="home-front", status="completed", outcome="done", reason="finished", description="- Goal: The thing is done and closed")
m = mt(3)
check("close: the mover and the wait are dropped, the goal stays", m["goal"] == "The close drops the mover" and not any(k in m for k in ("mover", "then", "wait_kind", "wait_event", "ask_by", "post_wake_mover")) and m["outcome"] == "done", m)
check("close: get shows the goal and `model: dead`", "goal: The close drops the mover" in server.stackshot_get("a3") and "model: dead" in server.stackshot_get("a3"), server.stackshot_get("a3"))
refused_nw("close: a mover on a closed item is refused (a goal alone may be set)", 3, lambda: server._update("a3", sender="home-front", mover="team-back"), "has no mover and waits on nothing")
server._update("a3", sender="home-front", goal="The close drops the mover and keeps the goal")
check("close: …a goal on a closed item is allowed", mt(3)["goal"].endswith("keeps the goal"), mt(3))
server._update("a3", sender="home-front", status="open", next="home-front: reopened")
check("close: a reopen keeps the goal", mt(3)["goal"].endswith("keeps the goal") and "outcome" not in mt(3), mt(3))

# ================================================================ review fixes
# a write of the model fields alone is filing: it does not name the writer in needs
item(20, needs=[BACK], subject="[home] filing only")
server._update("a20", sender="home-other", mover="team-back", then="home-front", wait_kind="relay", wait_event="x", ask_by=FUT, post_wake_mover="team-back")
server._update("a20", sender="home-other", clear_wait=True, clear_then=True)
server._update("a20", sender="home-other", goal=NEW_GOAL)
check("filing: a write of the model fields alone (and the clear flags) does not add its writer to needs", mt(20)["needs"] == [BACK], mt(20))
server._update("a20", sender="home-other", next="home-other: do the thing")
check("filing: ...the control: a plain write of next by that background agent does name it", len(mt(20)["needs"]) == 2, mt(20))
# a done-check close drops what a session's close drops
item(21, needs=[BACK], subject="[home] check close", goal="Closed by its check", mover="team-back", then="home-front", wait_kind="anchor", wait_anchor="https://x/pull/1", wait_event="merged", ask_by=FUT, post_wake_mover="team-back", check="item_closed a3")
server._check_close("a21", server._load("a21"), "item_closed a3", time.time())
m = mt(21)
check("check close: the mover, then and the wait are dropped, the goal stays, the item is closed", rd(21)["status"] == "completed" and m["goal"] == "Closed by its check" and not any(k in m for k in model.DROP_ON_CLOSE) and m["outcome"] == "done", (rd(21)["status"], m))
check("check close: ...the check close is a server save: the last real writer stays and nothing is added", "written_by_server" not in rd(21), rd(21))
# a stored mover against the state it stands in
m_ = D(state="your-call", needs=["decision", BACK], ask=ASK, mover=BACK)
check("conflict: an agent mover on a your-call item is listed", any(c.startswith(f"mover={BACK} on an item whose state is your-call") and f"{OWN}'s move" in c for c in m_.conflicts) and m_.mover == BACK and m_.mover_explicit, m_)
m_ = D(needs=["decision"], mover=BACK)
check("conflict: ...also when the state is derived from needs", any("your-call" in c for c in m_.conflicts), m_)
m_ = D(state="doing", expected_by=day(2), needs=[BACK], mover="oliver")
check("conflict: the owner as mover on a doing item is listed", any("an agent's move" in c for c in m_.conflicts), m_)
m_ = D(state="doing", expected_by=day(2), needs=[BACK], mover=OTHER)
check("conflict: an agent mover on a doing item raises none; nor does the owner on your-call/your-step",
      not m_.conflicts and not D(state="your-step", step="x", mover="oliver").conflicts and not D(state="your-call", needs=["decision"], ask=ASK, mover="oliver").conflicts, m_)
# the brief carries one short line
item(22, needs=[BACK], subject="[home] brief line", goal="x")
b = server.stackshot_brief()
check("brief: one short model line per open item: no `derived:` tail, no conflict lines", "model: alive · mover team-back" in b and "derived:" not in b and "model conflict" not in b, [l for l in b.splitlines() if l.startswith("model")][:6])
g = server.stackshot_get("a22")
check("brief: ...get keeps the full line", "model: alive · mover team-back · derived: mover" in g, g)
check("brief: ...none for a closed item in a brief format", not any(l.startswith("model:") for l in server._fmt({**rd(21), "gid": "a21"}, brief=True).splitlines()) and "model: dead" in server._fmt({**rd(21), "gid": "a21"}), None)


# ================================================================ every revision records its author
def wb(i): r = rd(i); return r.get("written_by"), r.get("written_by_id")
item(10, needs=[BACK], subject="[home] who wrote")
server._update("a10", sender="home-front", next="team-back: look at it")
check("author: an update by a session records its name and its id", wb(10) == ("home-front", U["home-front"]), wb(10))
server._update("a10", sender="home-other", next="team-back: look at it again")
check("author: …the next writer replaces the last in the file (the store's history keeps each revision's)", wb(10) == ("home-other", U["home-other"]), wb(10))
server.stackshot_confirm("a10", sender="team-back")
check("author: a confirm records its sender", wb(10) == ("team-back", U["team-back"]), wb(10))
it_ = server._load("a10"); server._save("a10", it_)
before_srv = raw(10); it_ = server._load("a10"); server._save("a10", it_)
check("author: a server act (no writer) leaves the item byte for byte as it was: the last real writer stays", wb(10) == ("team-back", U["team-back"]) and raw(10) == before_srv and "written_by_server" not in rd(10), rd(10))
it_ = server._load("a10"); server._save("a10", it_)
it_ = server._load("a10"); server._save("a10", it_)
check("author: ...a second server save changes nothing either", raw(10) == before_srv, rd(10))
server._update("a10", sender="home-front", next="team-back: after a server act")
server._update("a10", sender="home-front", next="team-back: after a server act")
check("author: ...the next real write names its writer", wb(10) == ("home-front", U["home-front"]), rd(10))
item(11, needs=[BACK], subject="[home] never written by a session"); server._save("a11", server._load("a11"))
item(11, needs=[BACK], subject="[home] never written by a session"); before11 = raw(11); server._save("a11", server._load("a11"))
check("author: a server save of an item no session wrote adds nothing: no writer, the file as it was (but for the activity and progress clocks an item from before those fields gains at its first save, seeded with its last update: activity.py, progress.py, and the stored phase every save of an open item writes)",
      {k: ({kk: vv for kk, vv in v.items() if kk != "phase"} if k == "metadata" else v) for k, v in rd(11).items() if k not in ("activity", "progress")} == json.loads(before11) and rd(11).get("written_by") is None
      and rd(11).get("activity") == max(json.loads(before11)["updated"], json.loads(before11)["state_updated"]) and rd(11).get("progress") == rd(11).get("activity"), rd(11))
it_ = server._load("a10"); server._save("a10", it_, note="answered", author=(server.OWNER, "board"))
check("author: the owner's answer on the board records his name and `board`", wb(10) == (server.OWNER, "board"), wb(10))
server._update("a10", sender="home-front", status="completed", outcome="done", reason="finished", description="- Goal: The thing is done and closed")
check("author: a close records its writer", wb(10) == ("home-front", U["home-front"]), wb(10))
check("author: a create records the owner (the writer of a create)", rd(cid, "s").get("written_by") == "home-front" and rd(cid, "s").get("written_by_id") == U["home-front"], rd(cid, "s"))
it_ = server._load("a10"); it_["written_by"] = "someone else"; server._save("a10", it_, writer=U["home-other"])
check("author: the field is the save's own: a value carried in on the item is overwritten", wb(10) == ("home-other", U["home-other"]), wb(10))
it_ = server._load("a10"); server._save("a10", it_, writer="a script label (a script on box)")
check("author: a writer that is no session id (a script's label) is recorded by name, with no id", wb(10) == ("a script label (a script on box)", None), wb(10))
check("author: a stored revision is plain JSON a later step reads: written_by is a string", all(isinstance(rd(i).get("written_by"), str) for i in (1, 2, 3, 10)), None)


# ================================================================ step 4b: the tools say mover, never owner
PAGE_ = "docs/design"
import datetime as _dt; from stackshot.web import whatschanged
_mc = lambda **kw: {"subject": "[home] mover create", "description": DESC, "project": "projects/alpha", "needs": [BACK], "next": "team-back: take it up", **kw}
nfiles = lambda: len(list((T / "store").glob("*/*.json")))
# create: the sender is the creator, mover names who moves it; owner is accepted with a note until [model] owner_param_until, then refused
out = server.stackshot_create(**_mc(sender="home-front", mover="team-back"))
sid = re.search(r"created (?:board#|s)(\d+)", out)[1]
check("create: sender alone is the creator: stored as metadata.owner, with no owner note", rd(sid, "s")["metadata"]["owner"] == U["home-front"] and rd(sid, "s")["metadata"]["mover"] == "team-back" and "owner is going away" not in out, out[-400:])
check("create: …the reply leads with mover: and shows no creator line (History says created by), never `owner:`", out.split("\n")[2] == "mover: team-back" and not re.search(r"(?m)^keeper of record: ", out) and not re.search(r"(?m)^owner:", out), out[:500])
out = server.stackshot_create(**_mc(subject="[home] owner create", owner="home-front", mover="team-back"))
check("create: an owner still accepted before the cut-off is stored as the creator, with a note that names mover and the model page",
      "(note: owner is going away: it is accepted until " in out and "mover=" in out and PAGE_ in out and rd(re.search(r"created (?:board#|s)(\d+)", out)[1], "s")["metadata"]["owner"] == U["home-front"], out[-500:])
refused("create: no sender and no owner is refused, with sender and mover named", lambda: server.stackshot_create(**_mc()), "pass sender=", "mover=", PAGE_)
refused("create: a sender that names the owner is refused as on update", lambda: server.stackshot_create(**_mc(sender=server.OWNER)), "Only the board writes as")
_CUT = server._cfg.CFG["model"].get("owner_param_until")
n0 = nfiles()
server._cfg.CFG["model"]["owner_param_until"] = (_dt.datetime.now(server._cfg.tz()).date() - _dt.timedelta(days=1)).isoformat()      # patch the date: yesterday was the last day
refused("create: after the cut-off owner is refused, with a pointer to sender and mover", lambda: server.stackshot_create(**_mc(subject="[home] late owner", owner="home-front")), "owner is not a parameter of create any more", "sender=", "mover=", PAGE_)
check("create: …and wrote nothing", nfiles() == n0, None)
out = server.stackshot_create(**_mc(subject="[home] late sender", sender="home-front", mover="team-back"))
check("create: …sender and mover still work", "created" in out and "owner is going away" not in out, out[:200])
was = raw(1)
refused("update: after the cut-off owner is refused, with a pointer to mover", lambda: server.stackshot_update(item_id="a1", sender="home-front", owner="team-back"), "owner is not a parameter of update any more", "mover=", PAGE_)
check("update: …and wrote nothing", raw(1) == was, None)
check("update: without owner it goes through after the cut-off", "updated" in server.stackshot_update(item_id="a1", sender="home-front", goal="Say mover"), None)
server._cfg.CFG["model"]["owner_param_until"] = (_dt.datetime.now(server._cfg.tz()).date()).isoformat()                                  # today is the last day: still accepted
out = server.stackshot_update(item_id="a1", sender="home-front", owner="home-front")
check("update: on the last day owner is accepted, with a note that names mover", "(note: owner is going away: it is accepted until " in out and "set mover=<session>" in out and PAGE_ in out, out[-400:])
server._cfg.CFG["model"]["owner_param_until"] = "not a date"
check("a value that is no date reads as the default cut-off", server._owner_param_until() == _dt.date(2099, 3, 3), server._owner_param_until())
if _CUT is None: server._cfg.CFG["model"].pop("owner_param_until", None)
else: server._cfg.CFG["model"]["owner_param_until"] = _CUT
# get: leads with mover and then; the keeper of record among the details
item(31, needs=["decision"], ask=ASK, subject="[home] get leads"); upd(31, mover="OLIVER", then="team-back")
g = server.stackshot_get("a31").split("\n")
check("get: leads with mover: and then: right after the heading line", g[1] == f"mover: {OWN}" and g[2] == "then: team-back" and g[0].endswith("[home] get leads"), g[:4])
check("get: no creator line, never `owner:` nor `keeper of record:`", not any(l.startswith("keeper of record: ") for l in g) and not any(l.startswith("owner:") for l in g), g)
item(32, subject="[home] derived lead", needs=[BACK]); g = server.stackshot_get("a32").split("\n")
check("get: a mover the item does not store reads (derived)", g[1] == "mover: team-back (derived)", g[:3])
item(33, subject="[home] waiting lead", wait_kind="time", wake=FUT, post_wake_mover="team-back", needs=[BACK]); g = server.stackshot_get("a33").split("\n")
check("get: a waiting item's mover line says who picks it up when the wait ends, and there is no `then:` line (it stands only beside the owner)", g[1] == "mover: team-back (picks it up when the wait ends)" and not any(l.startswith("then:") for l in g), g[:4])
check("get: a closed item has no mover line", not any(l.startswith("mover:") for l in server.stackshot_get("a21").split("\n")), server.stackshot_get("a21")[:200])
check("brief: the open items carry the model line that names the mover; the brief's items show `keeper of record:` too", "model: alive · mover team-back" in server.stackshot_brief() and not re.search(r"(?m)^owner:", server.stackshot_brief()), None)
check("the tool descriptions say mover, name the model page and say owner only to say it is going", all(PAGE_ in str(f) for f in (server._MODEL_FORM, server.stackshot_get.__doc__)) and "mover" in server._UPDATE_DESC
      and not re.findall(r"(?<![A-Za-z_{<])owner(?![A-Za-z_}:/=-])", server._NEEDS_FORM.replace(server.OWNER, "")), re.findall(r".{30}(?<![A-Za-z_{<])owner(?![A-Za-z_}:/=-]).{30}", server._NEEDS_FORM.replace(server.OWNER, "")))
check("create's schema takes sender and no longer requires owner", "sender" in _inspect.signature(server.stackshot_create).parameters and _inspect.signature(server.stackshot_create).parameters["owner"].default == "", None)
_sw = server._cfg.CFG["model"].get("switchover")
server._cfg.CFG["model"]["switchover"] = True
md_ = render.render(str(T / "store"), "full")
check("board.md: after the switchover each open item names its mover, and none says `session:`", re.search(r"(?m)^- mover: `", md_) is not None and re.search(r"(?m)^- session: ", md_) is None, md_[md_.find("## Needs"):][:600])
server._cfg.CFG["model"]["switchover"] = False
md_ = render.render(str(T / "store"), "full")
check("board.md: …and the switchover setting no longer changes it (the board speaks of the mover)", re.search(r"(?m)^- mover: `", md_) is not None and re.search(r"(?m)^- session: ", md_) is None, None)
server._cfg.CFG["model"]["switchover"] = _sw
facts_ = json.loads(server._client_item_facts("home-front", "a32")[2])["items"]["a32"]
check("item-facts says who moves the item, for the hook's note on a Board line about another session's item", facts_["mover"] == "team-back", facts_)
# the what-changed line: shown for 7 days after its date, then gone
cf = T / "history.json"; cf.write_text(json.dumps([{"date": "2099-03-03", "text": "the tools say mover."}, {"date": "2098-12-01", "text": "an old change"}, {"date": "bad", "text": "x"}, {"text": "no date"}]))
want = f"stackshot changed on Tue Mar 3rd: the tools say mover; see {PAGE_}"
check("what changed: an entry shows on its date, with the date in words, one line, the closing period gone", whatschanged.lines(_dt.date(2099, 3, 3), cf) == [want], whatschanged.lines(_dt.date(2099, 3, 3), cf))
check("what changed: …still on the 7th day after (date + 7 days is today)", whatschanged.lines(_dt.date(2099, 3, 10), cf) == [want], None)
check("what changed: …gone on the 8th day, and not shown before its date", whatschanged.lines(_dt.date(2099, 3, 11), cf) == [] and whatschanged.lines(_dt.date(2099, 3, 2), cf) == [], None)
check("what changed: a missing file or a malformed one shows nothing", whatschanged.lines(_dt.date(2099, 3, 3), T / "nope.json") == [] and whatschanged.entries(T / "RULES.md") == [], None)
whatschanged.PATH = cf
_today = _dt.datetime.now(server._cfg.tz()).date()
cf.write_text(json.dumps([{"date": _today.isoformat(), "text": "a tool changed"}]))
check("what changed: the brief tool carries the line at its top while the entry is live", server.stackshot_brief().split("\n")[0].startswith(f"stackshot changed on {whatschanged.day_words(_today)}: a tool changed; see {PAGE_}"), server.stackshot_brief()[:200])
check("what changed: …and the session-start brief too", render.render(str(T / "store"), "brief").split("\n")[1].startswith("stackshot changed on "), render.render(str(T / "store"), "brief")[:300])
cf.write_text(json.dumps([{"date": (_today - _dt.timedelta(days=8)).isoformat(), "text": "a tool changed"}]))
check("what changed: …and neither once the entry is 8 days old", "stackshot changed on" not in server.stackshot_brief() and "stackshot changed on" not in render.render(str(T / "store"), "brief"), None)
check("what changed: the seed (the two hand-written entries of Tue Mar 3rd, before the snapshot) is in the entry shape", whatschanged.SEED and all(set(e) == {"date", "text"} and _dt.date.fromisoformat(e["date"]) for e in whatschanged.SEED) and "mover" in whatschanged.SEED[0]["text"], whatschanged.SEED)
check("what changed: changes.json is gone (the line is generated from tests/tool_text.snapshot.json)", not (pathlib.Path(STACK) / "changes.json").exists())

# ================================================================ the way to drop a wait is named (clear_wait=true) where a session meets the wait
ANC = "https://example.org/pull/9"
WAITK = dict(wait_kind="anchor", wait_anchor=ANC, wait_event="the PR merges", ask_by=FUT, post_wake_mover="team-back")
item(40, needs=[BACK], subject="[home] waits on an anchor", **WAITK)
item(41, needs=["decision", BACK], ask=ASK, state="your-call", subject="[home] wait beside a your-call", **WAITK)
g41 = server.stackshot_get("a41")
check("hint: get's model conflict (a wait beside a your-call state) ends with how to resolve it: clear_wait=true, or park the item with hold=true",
      any(l.startswith("model conflict: wait_kind=anchor") and "the wait wins" in l and "update clear_wait=true" in l and "park the item: update hold=true" in l for l in g41.splitlines()), g41)
refused_nw("hint: wait_event=none on an anchor wait is refused 'input is missing' and names clear_wait=true", 40, lambda: upd(40, wait_event="none"), "input is missing", "clear_wait=true")
refused_nw("hint: wait_anchor=none on an anchor wait: the same refusal and the same hint", 40, lambda: upd(40, wait_anchor="none"), "input is missing", "clear_wait=true")
item(42, needs=[BACK], subject="[home] wait derived from the state", state="outside", party="Acme", chase=day(4))
item(43, needs=[BACK], subject="[home] no ask_by", wait_kind="relay", wait_event="Acme's reply", post_wake_mover="team-back")
refused_nw("hint: a stored wait with no end names clear_wait=true too", 43, lambda: upd(43, wait_event="Acme replies"), "has no end", "clear_wait=true")
check("hint: …a stored wait is dropped by clear_wait=true in one write", (upd(43, clear_wait=True), "wait_kind" not in mt(43))[1], mt(43))
# asking the owner on an item that still waits: refused with the hint, nothing written; clear_wait=true in the same update goes through
ASK2 = "Decide: merge now · Recommend: yes · Stakes: a day · By: no date"
refused_nw("ask: needs=decision on an item that stores a wait is refused, naming the wait and clear_wait=true", 40, lambda: upd(40, needs=["decision"], ask=ASK2),
           "a40 still waits on an anchor event (the PR merges)", "pass clear_wait=true with this update", "do not ask")
out40 = upd(40, needs=["decision"], ask=ASK2, clear_wait=True)
check("ask: …with clear_wait=true the same update drops the wait and asks", "wait_kind" not in mt(40) and "decision" in mt(40)["needs"] and "model conflict" not in server.stackshot_get("a40"), (mt(40), out40))
item(44, needs=[BACK], subject="[home] derived wait, then ask", state="outside", party="Acme", chase=day(4))
upd(44, needs=["decision"], ask=ASK2)
check("ask: …an item whose wait is only read from its state (no wait_kind stored) is not refused", "decision" in mt(44)["needs"], mt(44))
item(45, needs=["decision"], ask=ASK2, state="your-call", subject="[home] already asked, with a wait", **WAITK)
upd(45, goal="Merge the thing")
check("ask: …an item that already holds the decision and a wait (stored before) is not refused for an unrelated write", mt(45)["goal"] == "Merge the thing", mt(45))
upd(45, needs=["decision"], ask=ASK2)
check("ask: …a decision restated on an item that already holds it (and a wait, stored before) is not refused", mt(45)["state"] == "your-call" and "decision" in mt(45)["needs"] and "wait_kind" in mt(45), mt(45))
check("hint: update's text says what clear_wait is for and when a decision is refused; create's shared text makes no update-only claim",
      "clear_wait=true is how an update drops a stored wait" in server._WAIT_FORM and "newly adds needs=decision to an item that stores a wait is refused unless it also passes clear_wait=true" in server._WAIT_FORM
      and "is how an update drops" not in server._MODEL_FORM and "clear_wait" in _inspect.signature(server.stackshot_update).parameters, None)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": model scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
