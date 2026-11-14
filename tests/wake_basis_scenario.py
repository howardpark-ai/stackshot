"""Scenario test for a doing item whose wake stands on a stated real-world reason (metadata.wait_basis): the board lists it as waiting until the wake — fixture data, no live store, no network, no server socket.

A wake is a backstop when it carries no reason, and the item stays active. A wake that carries a wait_basis names what the item waits for ("the subscription renews on <date>"), so until that wake
the item reads as waiting on a time, with the basis as the reason, whether or not it is on hold. model.view is the one place this is decided (dated_wait.basis_wait); the home page's lists, the brief,
get and the wire `list` all read it, and derive (the guards, the router) is unchanged: the stored state stays doing.

  1. doing + wake in the future + wait_basis + no hold  → waiting on a time (kind time) until the wake, the basis shown, the mover kept for after it; listed under waiting on the home page (the Board's lists
     and the server's wire word), the brief's model line says so and why, the row names the basis, who set it and the end date; the sort puts it by its wake
  2. the same item with the wake in the past (or a basis written for another wake) → as stored: alive, listed on agents
  3. a wake with no wait_basis → unchanged (a backstop: alive, agents)
  4. hold=true variants unchanged: a held doing item with a wake is still a held wait whose reason is the hold, with a basis or without; a hold with no wake stays alive
  5. needs=decision beside a wait_basis wake keeps its decision state; so does an open after link; a stored wait_kind is already a wait
  6. a verifying item is unchanged (it waits on its end date already, with no change to its model)
  7. the status line's advice about doing items with dated steps does not count an item that states its basis

    tests/run-suite wake_basis        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="wakebasis-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other", "home-gone")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
ZONE_OFFSET = 4 * 3600.0                             # the instance timezone (the config's `timezone` above): UTC+4, no DST
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other", "home-gone": "the third"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other", "home-gone": "the third"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n    home-gone: the third\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=None, status="open", su=None, letter="a", subject=None, desc=None, **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/{letter}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status,
                                                              "updated": su, "state_updated": su, "confirmed": su,
                                                              "metadata": {"owner": owner or U["home-front"], **({} if {"mover", "then", "hold", "after"} & set(meta) or meta.get("needs") else {"mover": owner or U["home-front"]}), "project": "projects/alpha", "next": "do the thing", **meta}}))
def rd(i, letter="a"): return json.loads((T / f"store/{letter}/{i}.json").read_text())
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.waits import waiting as W; from stackshot.web import render; from stackshot.model import states; from stackshot.model import model as _model; from stackshot.waits import dated_wait as _dw; from stackshot.audit import audit_run as AR
from stackshot.github import ghsync as _gh
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.service import fleet_events as fleetev
from stackshot.service import migrations as migsvc
from stackshot.service import page_debt as pdebt_svc
from stackshot.service import handoff as handoff_svc
from stackshot.service import handoff_cold as hcold_svc
from stackshot.service import checks as checks_svc, proofs as proofs_svc, released as released_svc
from stackshot.service import pane_recovery as _pane_recovery
from stackshot.web.ui import render as ui_render
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
mt = lambda i, letter="a": rd(i, letter)["metadata"]
hrs = lambda n: time.strftime("%Y-%m-%d %H:%M", time.gmtime(now0 + n * 3600 + ZONE_OFFSET))      # n hours after the suite started, in the instance timezone
wk = lambda h: hrs(h).replace(" ", "T")
iso = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_OFFSET))
BACK = "team-back"
now_ = time.time()
def g(n, subject=None, **kw): item(n, letter="g", subject=subject, **kw)
def basis(wake, text="the subscription renews on 2099-01-20", by="team-back"): return {"text": text, "wake": wake, "by": by, "at": now0}
def it_of(n): return dict(rd(n, "g"), gid=f"g{n}")
def AO(i):                      # the items an item waits after that are still open, read from the store as the server reads them
    return [x for x in W.after_of(i["metadata"]) if (T / f"store/g/{x[1:]}.json").exists() and rd(int(x[1:]), "g")["status"] == "open"]
def derive_of(n): return _model.derive(it_of(n), now_, after_open=AO, anchored=lambda i: False)
def view_of(n): return _model.view(it_of(n), derive_of(n), now_, AO)
lst = lambda n: server._item_list(it_of(n))
brief = lambda n: server._fmt(it_of(n), brief=True)
NEXT = "team-back: check the build later and report back to the owner"     # no date a step could be read for
BASIS = "the subscription renews on 2099-01-20"

W1 = wk(24 * 30)
g(1, needs=[BACK], state="doing", wake=W1, wait_basis=basis(W1), next=NEXT)                       # the case: doing, a far wake, a basis, no hold
g(2, needs=[BACK], wake=W1, wait_basis=basis(W1), next=NEXT)                                      # no stored state: a mover and a wake read as doing
g(3, needs=[BACK], state="doing", wake=wk(-5), wait_basis=basis(wk(-5)), next=NEXT)               # the wake has passed
g(4, needs=[BACK], state="doing", wake=W1, wait_basis=basis(wk(24 * 31)), next=NEXT)              # a basis written for another wake: not read
g(5, needs=[BACK], state="doing", wake=W1, next=NEXT)                                             # a plain reminder: no basis
g(6, needs=[BACK], state="doing", wake=wk(0.5), wait_basis=basis(wk(0.5)), next=NEXT)             # a wake 30 minutes out is still ahead
g(7, needs=[BACK], state="doing", wake=W1, hold=True, wait_basis=basis(W1), next=NEXT)            # on hold, with a basis
g(8, needs=[BACK], state="doing", wake=W1, hold=True, next=NEXT)                                  # on hold, no basis
g(9, needs=[BACK], state="doing", hold=True, wait_basis=basis(W1), next=NEXT)                     # on hold with no wake (the basis has no wake to stand for)
g(10, needs=["decision", BACK], wake=W1, wait_basis=basis(W1), ask="Decide: renew · Recommend: renew · Stakes: a lapse · By: no date", next=NEXT)       # no stored state: his decision is asked
g(11, needs=["decision", BACK], state="doing", wake=W1, wait_basis=basis(W1), next=NEXT)          # stored doing beside a decision in needs
g(12, needs=[BACK], state="doing", after=["g5"], wake=W1, wait_basis=basis(W1), next=NEXT)         # an open after link
g(13, needs=["external"], wake=W1, wait_basis=basis(W1), next=NEXT)                               # an outside party
g(14, needs=[BACK], state="doing", wait_kind="time", wake=W1, wait_basis=basis(W1), next=NEXT)    # a stored wait
g(15, needs=[BACK], state="verifying", wake=W1, wait_basis=basis(W1), end=iso(5), proof="the run lands", next=NEXT)   # a verifying item
g(16, needs=[BACK], state="doing", wake=W1, wait_basis=basis(W1), mover="home-front", next="home-front: write it up")   # the mover is another session
g(17, needs=[BACK], state="doing", wake=wk(24 * 20), wait_basis=basis(wk(24 * 20)), next=NEXT)    # a sooner end date, for the sort
g(18, needs=[BACK], state="doing", next="team-back: write the thing")                             # plain doing, no wake
g(19, status="completed", needs=[BACK], state="doing", next="team-back: done")                    # a closed item
g(22, needs=[BACK], state="doing", after=["g19"], wake=W1, wait_basis=basis(W1), next=NEXT)       # a closed after link: it waits for nothing but its wake

# ---- 1. doing + a future wake + a wait_basis + no hold
m1 = view_of(1)
check("1 a doing item with a future wake and a wait_basis (no hold) reads as waiting on a time until the wake, the mover kept for after it",
      m1.state == _model.WAITING and m1.wait.kind == "time" and m1.wait.until == W1 and m1.wait.post_wake_mover == BACK and not m1.wait.due and m1.today == "doing", m1)
check("1 …the basis is the wait's reason (the text of the wait_basis)", m1.wait.basis == BASIS, m1.wait.basis)
check("1 …an item with no stored state (a mover and a wake read as doing) is the same", view_of(2).state == _model.WAITING and view_of(2).wait.basis == BASIS and "state" not in mt(2, "g"), view_of(2))
check("1 …a wake 30 minutes ahead is still ahead: the basis names the wait (no hour floor, unlike a dated step)", view_of(6).state == _model.WAITING, view_of(6))
check("1 …derive and the stored state are unchanged: the guards and the router still read it as stored", derive_of(1).state == _model.ALIVE and mt(1, "g").get("state") == "doing", derive_of(1))
check("1 …the wire word puts it under waiting, and a plain doing item stays on agents", lst(1) == "waiting" and lst(2) == "waiting" and lst(18) == "agents", (lst(1), lst(2), lst(18)))
bd = ui_render.Board(str(T / "store"))
hl = bd.home_lists()
ids = lambda which: {p[0]["gid"] for p in hl[which]}
check("1 …on the home page it is in the Waiting list, not On agent", {"g1", "g2"} <= ids("waiting") and not ({"g1", "g2"} & ids("agents")) and "g18" in ids("agents"), {k: sorted(ids(k)) for k in hl})
pair = next(p for p in hl["waiting"] if p[0]["gid"] == "g1")
row_txt = re.sub(r"<[^>]+>", "", bd.home_wait(pair[0], pair[1]) + " " + bd.wait_who(pair[0], pair[1]) + " " + bd.wait_end_slot(pair[1], None))
check("1 …its row names the basis, who set it, who picks it up and the end date", BASIS in row_txt and "set by" in row_txt and "picks it up" in row_txt and "until" in row_txt, row_txt)
order = [p[0]["gid"] for p in hl["waiting"] if p[0]["gid"] in ("g1", "g17")]
check("1 …the Waiting sort orders it by its wake (the sooner wake first)", order == ["g17", "g1"], order)
mls = "\n".join(server._model_lines(it_of(1), short=True))
check("1 …the brief and get say the board lists it as waiting until the wake, and why (the basis)", f"the board lists it as waiting until {W1} ({BASIS})" in mls and "model: alive" in mls, mls)
check("1 …the brief's item block carries that line", "the board lists it as waiting until" in brief(1), brief(1)[-400:])
check("1 …a plain doing item carries no such note", "the board lists it as waiting" not in brief(18), None)

# ---- 2. the wake has passed, or the basis is for another wake
check("2 the wake in the past → not waiting: alive, listed on agents (as a spent wake with no hold reads today)", view_of(3).state == _model.ALIVE and lst(3) == "agents", view_of(3))
check("2 …a basis written for another wake is not read (basis_of): alive", view_of(4).state == _model.ALIVE and W.basis_of(mt(4, "g")) == "" and lst(4) == "agents", view_of(4))
check("2 …the same item flips by the clock alone: a minute before the wake it waits, a minute after it does not",
      _model.view(it_of(1), derive_of(1), W.wake_epoch(W1) - 60).state == _model.WAITING and _model.view(it_of(1), derive_of(1), W.wake_epoch(W1) + 60).state == _model.ALIVE, None)

# ---- 3. a wake with no wait_basis is a backstop
check("3 a wake with no wait_basis → unchanged: alive, listed on agents, no board note", view_of(5).state == _model.ALIVE and lst(5) == "agents" and "the board lists it as waiting" not in brief(5), view_of(5))

# ---- 4. hold=true variants
m7, m8 = view_of(7), view_of(8)
check("4 on hold with a wake and a basis: a held wait as before, its reason the hold (the hold is the park), not the basis",
      m7.state == _model.WAITING and m7.wait.until == W1 and m7.wait.basis == "on hold until its wake" and _dw.basis_wait(it_of(7), now_) is None and _dw.held_wait(it_of(7), now_) is not None, m7)
check("4 …on hold with a wake and no basis: the same held wait", m8.state == _model.WAITING and m8.wait.basis == "on hold until its wake", m8)
check("4 …on hold with no wake: unchanged, alive", view_of(9).state == _model.ALIVE and _dw.basis_wait(it_of(9), now_) is None, view_of(9))

# ---- 5. needs, after, a stored wait
check("5 needs=decision beside a wait_basis wake keeps its decision state (your-call, his move, listed on your-move)",
      derive_of(10).today == "your-call" and view_of(10).state == _model.ALIVE and _model.is_owner(view_of(10).mover) and lst(10) == "your-move", (derive_of(10), lst(10)))
check("5 …a stored doing item with a decision in needs, an open after link or an outside party: no basis wait from this rule",
      all(_dw.basis_wait(it_of(n), now_, AO) is None for n in (11, 12, 13)) and view_of(11).state == _model.ALIVE and view_of(12).state == _model.ALIVE, [view_of(n).state for n in (11, 12, 13)])
check("5 …a closed after link is no wait (the open-link test derive uses): the item waits on its basis wake, listed as waiting; without a callback every link counts as open",
      view_of(22).state == _model.WAITING and view_of(22).wait.basis == BASIS and lst(22) == "waiting" and lst(12) == "agents" and _dw.basis_wait(it_of(22), now_) is None, (view_of(22), lst(22), lst(12)))
check("5 …a stored wait_kind is a wait already: derive says waiting, with the kind it stores", derive_of(14).state == _model.WAITING and derive_of(14).wait.kind == "time" and _dw.basis_wait(it_of(14), now_) is None, derive_of(14))
check("5 …another session as the mover is still a session: waiting, then that session moves it", view_of(16).state == _model.WAITING and view_of(16).wait.post_wake_mover == "home-front", view_of(16))

# ---- 6. a verifying item
d15 = derive_of(15)
check("6 a verifying item is unchanged: model.view returns derive's reading as it is and basis_wait never reads it",
      d15.today == "verifying" and _model.view(it_of(15), d15, now_) is d15 and _dw.basis_wait(it_of(15), now_) is None, d15)

# ---- 7. the status line's advice does not count an item that states its basis
step40 = f"team-back: after {iso(40)} check the result"
g(20, needs=[BACK], state="doing", wake=W1, wait_basis=basis(W1), next=step40)      # a dated step and a basis
g(21, needs=[BACK], state="doing", wake=W1, next=step40)                            # a dated step, no basis
check("7 an item with dated steps and a basis reads as waiting on the basis (the stated reason), one without on its dated steps",
      view_of(20).wait.basis == BASIS and "dated for later" in view_of(21).wait.basis, (view_of(20), view_of(21)))
for cls in (render, ui_render):
    bdx = cls.Board(str(T / "store"))
    st_ = bdx.brief()
    check(f"7 {cls.__name__}: the brief's advice counts the dated-step item only", "1 of the doing items have a wake more than 1 h out and every open step dated" in st_, [l for l in st_.splitlines() if "doing items" in l])
    # counted from the store files, not from the renderer and not from a fixed list: every open item that stores a wait_basis and that dated_wait reads as a basis wait now
    basis_ids = [p_.stem for p_ in sorted((T / "store" / "g").glob("*.json"))
                 if json.loads(p_.read_text()).get("status") == "open" and isinstance((json.loads(p_.read_text()).get("metadata") or {}).get("wait_basis"), dict)
                 and _dw.basis_wait(it_of(int(p_.stem)), time.time(), AO) is not None]
    nb_ = len(basis_ids)
    nwait_ = re.search(r"(\d+) waiting\)", st_.splitlines()[0])
    md_ = bdx.markdown(); wsec_ = md_[md_.find("\n## Waiting\n"):md_.find("\n## On agents\n")]
    check(f"8 {cls.__name__}: the store holds the seven basis waits, and the first line and board.md's head count them among the waiting (each is listed as waiting) without setting them apart",
          nb_ == 7 and nwait_ and int(nwait_[1]) >= nb_ and re.search(rf" · (\d+) waiting · machines:", md_) and int(re.search(r" · (\d+) waiting · machines:", md_)[1]) == int(nwait_[1])
          and "listed as waiting until a stated date" not in st_.splitlines()[0], (basis_ids, st_.splitlines()[0]))
    check(f"8 {cls.__name__}: …every one of them is under Waiting in board.md, and none under Your move or On agents",
          all(f'<a id="task-g-{i}"></a>' in wsec_ for i in basis_ids) and not any(f'<a id="task-g-{i}"></a>' in md_.replace(wsec_, "") for i in basis_ids), (basis_ids, wsec_[:200]))
    check(f"8 {cls.__name__}: …and a line says how many doing items the board lists as waiting for a wake that states its reason, the count the store gives",
          any(l.startswith(f"  {nb_} of the doing items have a wake that states its reason (wait_basis): the board lists them as waiting until the wake") for l in st_.splitlines()), [l for l in st_.splitlines() if "states its reason" in l])

# ---- 9. the end-of-turn board question skips a basis wait, as it skips a held item
rows = {x["shown"]: x for x in json.loads(server._client_items(U["team-back"])[2])["items"]}
sh = lambda n: _gh.shown(f"g{n}")
check("9 the items the client reads carry held: true for a basis wait (the hook skips held rows), and false for a plain doing item, a spent wake and a reminder",
      all(rows[sh(n)]["held"] for n in (1, 2, 6, 17, 22)) and not any(rows[sh(n)]["held"] for n in (3, 4, 5, 18)) and rows[sh(1)]["list"] == "waiting", {n: rows.get(sh(n), {}).get("held") for n in (1, 2, 3, 4, 5, 6, 17, 18, 22)})
from stackshot.projects import pages as _pages
due = [it for it in rows.values() if not it.get("held")]
check("9 …so the question lists no basis wait and still lists the plain doing item", sh(18) in {x["shown"] for x in due} and not ({sh(1), sh(2), sh(6), sh(17), sh(22)} & {x["shown"] for x in due}), sorted(x["shown"] for x in due))

# ---- 10. the audit's why-not-now call leaves a basis wait alone
g(23, needs=[BACK], state="doing", wake=W1, wait_basis=basis(W1), next=step40)           # dated steps beside a basis
check("10 audit: a doing item with dated steps and no basis is a why-not-now suspect, one that states its basis is not",
      AR.dated_wait_evidence(it_of(21), now_, AO)[0] != "" and AR.dated_wait_evidence(it_of(20), now_, AO) == ("", [], "") and AR.dated_wait_evidence(it_of(23), now_, AO) == ("", [], ""),
      (AR.dated_wait_evidence(it_of(21), now_, AO)[0][:60], AR.dated_wait_evidence(it_of(20), now_, AO)))
g(24, needs=[BACK], state="doing", wake=wk(24 * 30), wait_basis=basis(wk(24 * 31)), next=step40)    # a basis for another wake is no basis: the audit still asks
check("10 …a basis written for another wake does not exempt it", AR.dated_wait_evidence(it_of(24), now_, AO)[0] != "", AR.dated_wait_evidence(it_of(24), now_, AO))

# ---- 11. the wake notes ("a wake alone ... stays on agent") do not fire for a wake that carries a basis
WD = iso(30)
NX_W = f"team-back: collect logs until {WD}, then review"
m_plain = {"owner": U["home-front"], "mover": BACK, "needs": [BACK], "wake": WD, "next": NX_W, "project": "projects/alpha"}
m_basis = dict(m_plain, wait_basis=basis(WD))
check("11 control: a wake alone whose next waits for its day draws the window note", "alone is a wait until that date" in server._wake_window_note(m_plain) and server._wake_alone_on_agent(m_plain), server._wake_window_note(m_plain))
check("11 a wake that carries a basis draws neither the window note nor the timed-step note: the item is listed as waiting, not on agent",
      server._wake_window_note(m_basis) == "" and not server._wake_alone_on_agent(m_basis) and server._wake_step_note(dict(it_of(1), metadata=m_basis), (BACK,)) == "", server._wake_window_note(m_basis))
class _Clock:                    # the server's clock stopped at the wake itself
    def __init__(self, at): self.at = at
    def time(self): return self.at
    def __getattr__(self, k): return getattr(time, k)
real_time = server.time
server.time = fleetev.time = migsvc.time = pdebt_svc.time = handoff_svc.time = hcold_svc.time = checks_svc.time = proofs_svc.time = released_svc.time = _pane_recovery.time = _Clock(W.wake_epoch(WD))
try:
    at_wake = (server._wake_alone_on_agent(m_basis), "alone is a wait until that date" in server._wake_window_note(m_basis))
finally:
    server.time = fleetev.time = migsvc.time = pdebt_svc.time = handoff_svc.time = hcold_svc.time = checks_svc.time = proofs_svc.time = released_svc.time = _pane_recovery.time = real_time
check("11 …a wake exactly now is not waiting any more: the basis no longer exempts it, so the note rules apply again (alone, and the window note fires)", at_wake == (True, True), at_wake)
bw = dict(it_of(1), metadata=dict(mt(1, "g")))
ep = W.wake_epoch(W1)
check("11 …the model agrees at the boundary: waiting one second before the wake, alive at the wake itself",
      _model.view(bw, derive_of(1), ep - 1, AO).state == _model.WAITING and _model.view(bw, derive_of(1), ep, AO).state == _model.ALIVE and _dw.basis_wait(bw, ep) is None, None)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": wake_basis scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
