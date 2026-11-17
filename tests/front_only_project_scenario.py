"""Scenario test for ONE front-only project, walked through the real tool entry points: a project page that lists front agents only (no builder, no background agent) next to a project with a builder, on a
throwaway instance (fixture pages and sessions in a temporary store, the push replaced by a recorder, no network, no model call). Each change made for such a project is walked in order, each with what the
tool returns (accepted, or the exact refusal and the path it names) and, for contrast, the same call on a project that has a builder, where the answer must differ.

  0  one predicate: `anchors.front_only` is exactly "no builder" (`handoff_builder` empty), for a page of front agents only, a page whose only background agent does not build, a sub-page with a front map of its own
     under a hub that has a builder, a builder shared by two pages
  1  `mover=` hand-over (update and create): a peer, a front agent or a background agent of another project hands an item to a live front agent of the project; the target is told by a hand-off notice and the reply
     says so; the refusals (a session no page lists, another project's front agent as target) name the half that failed and `message(to=<page key>)` with the first line `For <peer>,`. With a builder: the builder is
     substituted
  2  `then=` and `post_wake_mover=` take the same exception, tell nobody (the owner's answer or the wake moves the item), refuse the same way; with a builder both are substituted
  3  a step may open with a live peer: accepted on an item another session moves when an open step comes before it; refused as the first open step (with the ways out), for another project's front agent, and in a
     project with a builder; marking the step before it done hands the item to the peer, told once
  4  messages: an unmarked message from a front agent to a peer is refused and names `For <peer>,` to the page key; that form is accepted; a message that says nothing is needed from the owner stays refused
     without the form; a sender that is no front agent is not offered it
  5  `needs=` naming a peer: refused with `mover=<peer>` or its own item with `after=`; with a builder the refusal names the builder
  6  a script's item-open: filed with the project's -main agent as mover and the item says so; a project with a builder files it for the background agent; a sub-page under a hub with a builder is refused
  7  orphan hand-over: an alive item whose mover's session is gone goes to a live front agent, which is told once by the hand-off notice; with a builder the builder takes it and the front agents are not pushed to
  8  hand-back: a write by another session that leaves `needs` naming the front mover alone tells that mover, marked for the owner; with a builder the builder is told and the front mover is not
  9  take clock: a peer hand-off is clocked (one reminder to the new mover after the take minutes, then the project's -main agent is asked), the hander is told nothing at any step; with a builder a hand-off to a
     front agent is never clocked

Everything runs through the tools' own functions (`stackshot_update`, `stackshot_create`, `stackshot_message`, the item-open route, the handover and the passes the server runs on a timer: `handoff_tick`,
`orphan_handover`), on the in-process server module, as the other scenarios do; none reaches a live server or a live board. The hand-back check (8) reports the router as not live, so it pins the decision logic and the direct-push fallback (who is told, and marked for the owner), not the path every deployment takes
through the router; that path is covered in tests/router_live_scenario.py.

    tests/run-suite front_only_project        -> exit 0 / 1"""
import json, os, re, socket, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="foproject-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "brain/projects/bd", "transcripts/-home-x", "cli", "state"): (T / d).mkdir(parents=True)

# The pages. fo: the front-only project (three front agents, -main first). bd: a project with a builder. nb: its one background agent only watches (no builder, so front-only too).
# bd/side: a sub-page with a front map of its own under bd. tw1 and tw2: two pages that list the same builder.
FM, FD, FS = "home-fo-main", "home-fo-desk", "home-fo-side"
BM, BD, BB, BS = "home-bd-main", "home-bd-desk", "home-bd-builder", "home-bd-side"
NM, ND, NW = "home-nb-main", "home-nb-desk", "home-nb-watch"
T1M, T1D, T2M, T2D, SHARED = "home-t1-main", "home-t1-desk", "home-t2-main", "home-t2-desk", "home-shared-builder"
LONER = "home-loner"
NAMES = (FM, FD, FS, BM, BD, BB, BS, NM, ND, NW, T1M, T1D, T2M, T2D, SHARED, LONER)
U = {n: f"00000000-0000-4000-8000-0000000000{i:02d}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DEAD_ISO = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now0 - 3 * 3600))      # gone three hours: past [client] dead_after_minutes
def heartbeat(*gone):
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": "2026-01-01T00:00:00Z"}}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", **({"gone": DEAD_ISO} if n in gone else {})} for n, u in U.items()}))
heartbeat()
BUILDS, WATCHES = "builds, merges and releases the code", "watches the clock"
PAGES = {"projects/fo": ({FM: "the front", FD: "answers questions", FS: "answers other questions"}, {}),
         "projects/bd": ({BM: "the front", BD: "answers questions", BB: BUILDS}, {BB: BUILDS}),
         "projects/bd/side": ({BS: "front for the side page"}, {}),
         "projects/nb": ({NM: "the front", ND: "answers questions", NW: WATCHES}, {NW: WATCHES}),
         "projects/t1": ({T1M: "the front", T1D: "answers questions", SHARED: BUILDS}, {SHARED: BUILDS}),
         "projects/t2": ({T2M: "the front", T2D: "answers questions", SHARED: BUILDS}, {SHARED: BUILDS})}
def proj(agents, back):
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, "agents": agents, "back_agents": back}
(T / "store/projects.json").write_text(json.dumps({"pages": {k: proj(a, b) for k, (a, b) in PAGES.items()}}))
for key, (agents, back) in PAGES.items():
    path = T / f"brain/{key}.md"; path.parent.mkdir(parents=True, exist_ok=True)
    front = [k for k in agents if k not in back]
    path.write_text(f"---\ntitle: {key}\ndisplay-name: {key.replace('/', '-')}\nagents:\n" + "".join(f"  {k}: {agents[k]}\n" for k in front)
                    + ("  background:\n" + "".join(f"    {k}: {agents[k]}\n" for k in back) if back else "") + f"---\n\n# {key}\n\n## Current state\n\nSTATE-OF-{key.upper()}: the vendor call is open.\n\n<!-- timeline -->\n")
(T / "store/next-id").write_text("200"); (T / "store/anchors.json").write_text("{}")
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
B = now0 - 900.0
def put(i, project="projects/fo", mover=FM, status="open", updated=None, **meta):
    up = B if updated is None else updated
    base = {"owner": U[FM], "project": project, "next": f"{mover}: do the thing"}
    if mover: base["mover"] = mover
    base.update(meta)
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": up, "state_updated": up, "confirmed": up, "metadata": base}))
def sid(i):
    """the store id of an item named as the board shows it (`a12`, `12`, `s201`)"""
    g = str(i); g = _model_ids._norm_id(g) if not g.isdigit() else f"a{g}"
    return f"store/{g[0]}/{g[1:]}.json"
def rd(i): return json.loads((T / sid(i)).read_text())
def mt(i): return rd(i)["metadata"]
def close(*ids):
    for i in ids:
        d = rd(i); d["status"] = "completed"; (T / sid(i)).write_text(json.dumps(d))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1800]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import update as _wt_update, create as _wt_create, message as _wt_message
from stackshot.web.routes import client_api as _rt_client
from stackshot.fleet import client as _client
from stackshot.waits import handoff as H
from stackshot.service import handoff as handoff_svc, telling
from stackshot.core import instance as _core_instance, config as _cfg
from stackshot.router import routing as _routing, router as _router
from stackshot.anchors import anchors as _anc
from stackshot.web import publish as _web_publish, page_debts as _web_page_debts
from stackshot.model import ids as _model_ids
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
OWN = _core_instance.OWNER
# every push to a session the server would make goes to a recorder: [session id, text]
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []
_real_tell = telling.tell_woken
def _tell(gid, owner, note, tag="wake", **kw):
    th = _real_tell(gid, owner, note, tag, **kw)
    if th: THREADS.append(th)
    return th
telling.tell_woken = _tell
def drain():
    from stackshot.service import handoff_cold as hcold_svc
    while THREADS: THREADS.pop(0).join(30)
    while hcold_svc.HO_COLD_THREADS: hcold_svc.HO_COLD_THREADS.pop(0).join(30)
    while THREADS: THREADS.pop(0).join(30)
def pushes(): return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
def pushes_to(who, gid=None): return [p for p in pushes() if p[0] == U[who] and (gid is None or gid in p[1])]
def texts(who, gid=None): return [p[1] for p in pushes_to(who, gid)]
_cfg.CFG["model"] = {}; _cfg.CFG["stall"] = {}
from stackshot.service import handoff_cold as _hc
_hc.COLD_RUNNER = lambda msg: {"status": "spawn", "note": "no call expected"}
_cfg.CFG["model"] = {"cold_call": False}
def cli_row(who, status, at):
    (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": U[who], "name": who, "status": status, "statusUpdatedAt": int(at * 1000), "updatedAt": int(at * 1000)}))
handoff_svc.CLI_SESSIONS = T / "cli"
for w in (FM, FD, FS, BM, BD, BB, NM, ND): cli_row(w, "busy", now0)
WAKE = time.strftime("%Y-%m-%d", time.gmtime(now0 + 5 * 86400))
ASK = "Decide: a or b - Recommend: a - Stakes: none - By: no date"
def call(fn):
    """the tool's reply, or the refusal's text when it refuses"""
    try: return fn()
    except Exception as e: return str(e)    # noqa: BLE001
def refusal(fn):
    try: return fn() and ""
    except Exception as e: return str(e)    # noqa: BLE001
def held(i): return telling.holder({**rd(i), "gid": _model_ids._norm_id(str(i)) if not str(i).isdigit() else f"a{i}"})
def upd(i, sender, **kw): return _wt_update.stackshot_update(item_id=f"a{i}", sender=sender, **kw)
def FOR(peer, page): return f'message(to=\'{page}\') with the first line "For {peer}, ..."'
HANDOFF = lambda who, gid: [t for t in texts(who, gid) if "handed to you by" in t]

# ---- 0. one predicate
from stackshot.service import handoff as _h
KEYS = ("projects/fo", "projects/bd", "projects/bd/side", "projects/nb", "projects/t1", "projects/t2", "projects/ghost", "")
check("0.1 front_only is exactly 'no builder' (handoff_builder empty) on every page of the fixture", all(_anc.front_only(k) == (not _h.handoff_builder(k)) for k in KEYS), [(k, _anc.front_only(k), _h.handoff_builder(k)) for k in KEYS])
check("0.2 a page of front agents only is front-only; a page that lists a builder is not", _anc.front_only("projects/fo") is True and _anc.front_only("projects/bd") is False, None)
check("0.3 a page whose only background agent does not build is front-only", _anc.front_only("projects/nb") is True and _h.handoff_builder("projects/nb") == [], _h.handoff_builder("projects/nb"))
check("0.4 a sub-page with a front map of its own under a hub that has a builder is not front-only (it reads its hub's builder)", _anc.front_only("projects/bd/side") is False and _h.handoff_builder("projects/bd/side") == [BB], _h.handoff_builder("projects/bd/side"))
check("0.5 a builder listed on two pages is the builder of both", _anc.front_only("projects/t1") is False and _anc.front_only("projects/t2") is False and _h.handoff_builder("projects/t2") == [SHARED], None)


# ---- 1. mover= hand-over
NOBUILD = "has no builder to hand it to, so the item stays with its current mover"
put(1, mover=FM)
r = call(lambda: upd(1, FM, mover=FD, next=f"{FD}: take it from here")); drain()
check("1.1 a peer's mover= to another front agent of the front-only project is accepted: the mover changes, the reply says there is no builder and that the target is told", "Refused" not in r and held(1) == FD and mt(1).get("mover") == FD
      and f"projects/fo has no builder, so mover={FD} stays as sent" in r and f"{FD} has been told it is handed a1" in r, r)
check("1.2 …the target is told once by a hand-off notice that names the hander, and the hand-off is recorded", len(HANDOFF(FD, "a1")) == 1 and f"handed to you by {FM}" in HANDOFF(FD, "a1")[0] and mt(1)["handoff"]["to"] == FD and mt(1)["handoff"]["from"] == FM, (texts(FD), mt(1).get("handoff")))
check("1.3 …nothing is substituted: no server_fixed mark for the front-mover rule", "front_mover" not in json.dumps(mt(1).get("server_fixed") or ""), mt(1).get("server_fixed"))
put(2, mover=FM)
r = call(lambda: upd(2, BB, mover=FD, next=f"{FD}: take it from here", check="item_closed a1")); drain()
check("1.4 the sender need not belong to the project: a background agent of another project hands it over too, and the target is told", "Refused" not in r and held(2) == FD and len(HANDOFF(FD, "a2")) == 1, (r, texts(FD, "a2")))
r = call(lambda: _wt_create.stackshot_create(subject="[home] handed on create", description=DESC, project="projects/fo", sender=BB, mover=FD, next=f"{FD}: take it", check="item_closed a1")); drain()
gid = r.split()[1]
check("1.5 a create hands it over the same way", r.startswith("created") and held(gid) == FD and any("handed to you by" in t for t in texts(FD, gid)) and "Refused" not in r, r)
put(3, mover=FM)
r = call(lambda: upd(3, LONER, mover=FD, next=f"{FD}: take it"))
check("1.6 a session no page lists is refused, naming that half and the path to the peer: the page key with `For <peer>,` on its first line; the item stays", r.startswith("Refused:") and NOBUILD in r and "this call was refused because home-loner is not a session any project page lists." in r
      and f"To ask {FD} for a check or an answer, {FOR(FD, 'projects/fo')}." in r and held(3) == FM, r)
put(4, mover=FM)
r = call(lambda: upd(4, BB, mover=BM, next=f"{BM}: take it", check="item_closed a1"))
check("1.7 another project's front agent as the target is refused, naming that half, and the path names that agent's own page", r.startswith("Refused:") and NOBUILD in r and f"this call was refused because {BM} is not a live front agent of projects/fo." in r
      and f"To ask {BM} for a check or an answer, {FOR(BM, 'projects/bd')}." in r and held(4) == FM, r)
put(5, project="projects/bd", mover=BB)
r = call(lambda: upd(5, BM, mover=BD, next=f"{BB}: take it"))
check("1.8 contrast, a project with a builder: the same hand-over to a front agent is replaced by the builder, and the reply says so and names the `For <peer>,` path", f"mover={BB}, the project's builder, was used instead" in r and held(5) == BB and mt(5).get("mover") == BB
      and f'message(to=\'projects/bd\') with the first line "For {BD}, ..."' in r and "front_mover" in json.dumps(mt(5).get("server_fixed") or ""), (r, mt(5).get("server_fixed")))
put(6, project="projects/nb", mover=NM)
r = call(lambda: upd(6, NM, mover=ND, next=f"{ND}: take it")); drain()
check("1.9 a project whose only background agent does not build is front-only: the hand-over passes and the peer is told", "Refused" not in r and held(6) == ND and len(HANDOFF(ND, "a6")) == 1, r)
put(7, project="projects/bd/side", mover=BB)
r = call(lambda: upd(7, BS, mover=BM, next=f"{BB}: take it"))
check("1.10 a sub-page with a front map of its own under a builder's hub takes the builder's path: the front agent is replaced by the builder", f"mover={BB}, the project's builder, was used instead" in r and held(7) == BB, r)
close(1, 2, 3, 4, 5, 6, 7, gid)

# ---- 2. then= and post_wake_mover= take the same exception
put(10, mover=OWN, needs=["decision"], ask=ASK, then=FM, state="your-call")
drain(); pn = len(pushes())
r = call(lambda: upd(10, BB, then=FD)); drain()
check("2.1 then=<front agent> from a listed session of another project is accepted in the front-only project, and nobody is told by this write (the owner's answer moves the item)", "Refused" not in r and mt(10).get("then") == FD
      and f"projects/fo has no builder, so then={FD} is not replaced by one" in r and len(pushes()) == pn and "handoff" not in mt(10), (r, pushes()[pn:]))
put(11, mover=OWN, needs=["decision"], ask=ASK, then=FM, state="your-call")
r = call(lambda: upd(11, LONER, then=FD))
check("2.2 …from a session no page lists it is refused as mover= is, naming the half and the `For <peer>,` path; then is unchanged", r.startswith("Refused:") and NOBUILD in r and "this call was refused because home-loner is not a session any project page lists." in r
      and f"To ask {FD} for a check or an answer, {FOR(FD, 'projects/fo')}." in r and mt(11).get("then") == FM, r)
put(12, mover=FM, state="your-step", step="run it", hold=True, wake=WAKE, wait_kind="time", post_wake_mover=FM, next=f"{OWN}: run it")
drain(); pn = len(pushes())
r = call(lambda: upd(12, BB, post_wake_mover=FD, wait_basis=f"the vendor's reply is due {WAKE}")); drain()
check("2.3 post_wake_mover=<front agent> is accepted the same way (stored as the mover that picks it up when the wait ends), with no hand-off notice", "Refused" not in r and mt(12).get("mover") == FD and f"post_wake_mover={FD} is not replaced by one" in r
      and not HANDOFF(FD, "a12") and len(pushes()) == pn, (r, mt(12).get("mover"), pushes()[pn:]))
put(13, mover=FM, state="your-step", step="run it", hold=True, wake=WAKE, wait_kind="time", post_wake_mover=FM, next=f"{OWN}: run it")
r = call(lambda: upd(13, LONER, post_wake_mover=FD, wait_basis=f"the vendor's reply is due {WAKE}"))
check("2.4 …and refused from a session no page lists, as mover= is, the item untouched", r.startswith("Refused:") and "post_wake_mover=" + FD in r and "this call was refused because home-loner is not a session any project page lists." in r and mt(13).get("post_wake_mover") == FM, r)
put(14, project="projects/bd", mover=OWN, needs=["decision"], ask=ASK, then=BB, state="your-call")
r = call(lambda: upd(14, BM, then=BD))
check("2.5 contrast, a project with a builder: then=<front agent> is replaced by the builder", f"then={BB}, the project's builder, was used instead" in r and mt(14).get("then") == BB, r)
put(15, project="projects/bd", mover=BM, state="your-step", step="run it", hold=True, wake=WAKE, wait_kind="time", post_wake_mover=BM, next=f"{OWN}: run it")
r = call(lambda: upd(15, BM, post_wake_mover=BD, wait_basis=f"the vendor's reply is due {WAKE}"))
check("2.6 …and post_wake_mover=<front agent> likewise", f"post_wake_mover={BB}, the project's builder, was used instead" in r and mt(15).get("mover") == BB, (r, mt(15).get("mover")))
close(10, 11, 12, 13, 14, 15)

# ---- 3. a step may open with a live peer
SP = "Put an open step before it"
put(20, mover=FM, owner=U[FM], needs=[], next=f"{FM}: draft it")
r = refusal(lambda: upd(20, FS, next=f"{FM}: draft it\n{FD}: check it"))
check("3.1 in the front-only project a step opening with a live front peer passes on an item another session moves, with an open step before it", r == "" and mt(20)["next"].splitlines()[-1] == f"{FD}: check it" and held(20) == FM, (r, mt(20).get("next")))
drain(); pn = len(pushes())
out = call(lambda: upd(20, FM, done=[1])); drain()
check("3.2 marking the step before it done hands the item to the peer: the reply says so, the mover changes and the peer is told once, by the hand-off notice", f"the next step is {FD}'s" in out and held(20) == FD and mt(20).get("mover") == FD
      and len(pushes()) == pn + 1 and len(pushes_to(FD, "a20")) == 1 and "is yours" in texts(FD, "a20")[-1] and f"{FD}: check it" in texts(FD, "a20")[-1], (out[-400:], pushes()[pn:]))
put(21, mover=FM, owner=U[FM], needs=[], next=f"{FM}: draft it")
before = (T / sid(21)).read_bytes()
r = call(lambda: upd(21, FM, reword={"1": f"{FD}: draft it"}))
check("3.3 a peer's step as the FIRST open step is refused (nothing would move the item to it): the refusal names the ways out (mover=<peer>, or `For <peer>,` to the page key); the item is untouched", r.startswith("Refused:") and SP in r and f"mover={FD}" in r
      and f'starts "For {FD},"' in r and (T / sid(21)).read_bytes() == before, r)
put(22, mover=FM, owner=U[FM], needs=[], next=f"{FM}: draft it")
r = call(lambda: upd(22, FM, next=f"{FM}: draft it\n{BM}: check it"))
check("3.4 another project's front agent as the opener is refused, and the tail names what works: mover=<it> (between front agents of one project that has no builder) or `For <it>,` to the page key", r.startswith("Refused:")
      and f'the step "{BM}: check it" opens with {BM}' in r and f"mover={BM} (only between front agents of one project that has no builder)" in r and f'a message to projects/bd whose first line starts "For {BM},"' in r and mt(22)["next"] == f"{FM}: draft it", r)
put(23, project="projects/bd", mover=BB, owner=U[BM], needs=[], next=f"{BB}: draft it")
r = call(lambda: upd(23, BM, next=f"{BB}: draft it\n{BD}: check it"))
check("3.5 contrast, a project with a builder: a front agent's step on an item another session moves is refused, and the tail says to give the step to the builder", r.startswith("Refused:") and f'the step "{BD}: check it" opens with {BD}' in r and f'Give the step to {BB} (open it with "{BB}:")' in r
      and "mover=" not in r and mt(23)["next"] == f"{BB}: draft it", r)
close(20, 21, 22, 23)

# ---- 4. messages between front agents
MARK = f"[for {OWN}]"
r = call(lambda: _wt_message.stackshot_message(to=FD, text="Can you check the vendor call before noon?", sender=FM))
check("4.1 an unmarked message from a front agent to a peer is refused, naming the working form: a message to the page key whose first line is `For <peer>,`", r.startswith("Refused:") and f"{FD} is a front agent of projects/fo" in r
      and f"to reach {FD} from a front agent of the project, make the message's first line `For {FD},` and send it to='projects/fo'" in r, r)
r = call(lambda: _wt_message.stackshot_message(to="projects/fo", text=f"For {FD}, can you check the vendor call before noon?", sender=FM))
m42 = re.match(r"held for the router \u2014 the router rules notice (\w+) within about 60 s and passes it to the agent of projects/fo it fits", r)
rec42 = next((n for n in _routing.read("projects/fo") if m42 and n.get("id") == m42.group(1)), {})
first42 = (rec42.get("text") or "").splitlines()[0] if rec42.get("text") else ""
tgt42 = _router._FOR_AGENT.match(first42)
check("4.2 …and that form is accepted: held for the router, which rules the notice and passes it to the agent of the page it fits; the recorded notice is addressed to the project page and its first line names the peer, which the router's for-agent rule reads as that front agent", bool(m42) and rec42.get("label") == "message to projects/fo"
      and first42.startswith(f"For {FD},") and bool(tgt42) and tgt42.group(1) == FD and _anc.session_roles()[FD]["role"] == "front" and _anc.session_roles()[FD]["project"] == "projects/fo", (r, rec42))
r = call(lambda: _wt_message.stackshot_message(to=FD, text=f"{MARK} nothing is needed from you, this is only an FYI", sender=FM))
check("4.3 a marked message that says nothing is needed from the owner stays refused, and does not offer the `For <peer>,` form (it would route around the refusal)", r.startswith("Refused:") and "marks only what" in r and "nothing is needed from him" in r and "For " + FD not in r, r)
r = call(lambda: _wt_message.stackshot_message(to=FM, text="Can you check the vendor call before noon?", sender=BB))
check("4.4 contrast: a sender that is no front agent (another project's builder) is refused too, but is not offered the `For <peer>,` form", r.startswith("Refused:") and f"{FM} is a front agent of projects/fo" in r and "to=" in r and "For " + FM not in r, r)
r = call(lambda: _wt_message.stackshot_message(to=BD, text="Can you check the vendor call before noon?", sender=BM))
check("4.5 contrast, a project with a builder: a front agent's unmarked message to its peer is refused with the same form named", r.startswith("Refused:") and f"make the message's first line `For {BD},` and send it to='projects/bd'" in r, r)

# ---- 5. needs= naming a peer
put(30, mover=FM)
r = call(lambda: upd(30, FM, needs=[FD]))
check("5.1 needs=[<peer>] is refused with the two ways that work: mover=<peer> (it is told) or the peer's own item linked with after=; it no longer points at an empty list of background agents", r.startswith("Refused:") and f"{FD} is a front agent of projects/fo" in r
      and f"set mover={FD} (it is told)" in r and "after=[" in r and "no background agent named" not in r and mt(30).get("needs") in (None, []), (r, mt(30).get("needs")))
put(31, project="projects/bd", mover=BB)
r = call(lambda: upd(31, BB, needs=[BD]))
check("5.2 contrast, a project with a builder: the refusal names the builder (and the peer's own item with after=), not mover=<peer>", r.startswith("Refused:") and f"For projects/bd: {BB}" in r and "after=[" in r and "set mover=" not in r, r)
close(30, 31)

# ---- 6. a script's item-open
me = socket.gethostname(); _client.mint(me)
def io_(project, mover, marker, **kw):
    b = {"marker": marker, "project": project, "subject": "Deep-scan the suites", "mover": mover, "step": f"{mover}: deep-scan the suites, report", "description": ["- A scan is due", "- It is the first step"], "sender": "scan-job"}
    b.update(kw)
    return _rt_client._client_post(me, "item-open", b)
def store_files(): return sorted(f for f in (T / "store").glob("*/*.json") if f.stem.isdigit())
def store_ids(): return [f"{f.parent.name}{f.stem}" for f in store_files()]
def close_all():
    for f in store_files():
        d = json.loads(f.read_text())
        if d.get("status") == "open": d["status"] = "completed"; f.write_text(json.dumps(d))
close_all()
n0 = len(store_ids())
st, out = io_("projects/fo", "home-fo-builder", "scan:fo")
fit = rd(out["item"]) if st == 200 else {"metadata": {}, "description": ""}; fm = fit["metadata"]
check("6.1 a script's item-open for the front-only project (the page lists no background agent) is filed, not refused: the mover is the project's -main agent, the reply says fallback", st == 200 and out["mover"] == FM and out["owner"] == FM and out["fallback"] is True and out["repeat"] is False
      and len(store_ids()) == n0 + 1, (st, out))
check("6.2 …the item is held by the -main agent, names no one in needs, the step keeps its words under the -main agent's name, and the description says why", held(out["item"]) == FM and not fm.get("needs") and fm.get("item_open_fallback") is True
      and fm.get("next", "").strip() == f"{FM}: deep-scan the suites, report" and fit["description"].splitlines()[-2:] == [f"- projects/fo lists no background agent, so this is with {FM}, its front agent", "- Opened by scan-job (a script on a client machine)"], (fm, fit["description"]))
st, again = io_("projects/fo", "home-fo-builder", "scan:fo")
check("6.3 a repeat call answers the open item (repeat, fallback) and files nothing", st == 200 and again["item"] == out["item"] and again["repeat"] is True and again["fallback"] is True and len(store_ids()) == n0 + 1, (st, again))
st, e = io_("projects/fo", "x", "scan:fo2", description=[f"- line {i}" for i in range(7)])
check("6.4 the extra line leaves one fewer for the caller: seven lines are refused, never cut", st == 400 and "lists no background agent" in e["error"] and len(store_ids()) == n0 + 1, (st, e))
st, ok_ = io_("projects/bd", BB, "scan:bd")
check("6.5 contrast, a project with a builder: the named background agent is the mover, needs name it, no fallback", st == 200 and ok_["mover"] == BB and ok_["fallback"] is False and [telling._session_label(x) for x in rd(ok_["item"])["metadata"].get("needs") or []] == [BB]
      and "item_open_fallback" not in rd(ok_["item"])["metadata"], (st, ok_))
st, e = io_("projects/bd", BM, "scan:bd2", step=f"{BM}: scan")
check("6.6 …and a front agent as the mover is refused, the page's background agent named", st == 400 and "not a background agent" in e["error"] and BB in e["error"], (st, e))
for who in (BS, BB):
    st, e = io_("projects/bd/side", who, "scan:side", step=f"{who}: scan")
    check(f"6.7 a sub-page of front agents under a hub with a builder is no front-only project: mover {who} is refused, the page lists none, nothing filed", st == 400 and "not a background agent listed on projects/bd/side" in e["error"] and e["error"].endswith("the page lists none") and "fallback" not in e, (st, e))
close_all()

# ---- 7. orphan hand-over
_cfg.CFG.setdefault("audit", {})["orphan_handover"] = "apply"
put(40, mover=FM)
put(41, project="projects/bd", mover=BB)
for i in range(100, 130): put(i, mover=FD, project="projects/fo")      # a board of live movers around the two orphans (the pass reads more than a few gone sessions as a partial view of the fleet)
heartbeat(FM, BB)
drain(); pn = len(pushes())
got = handoff_svc.orphan_handover(apply=True, now=now0); drain()
from stackshot.waits import stall as ST
rows = {m["id"]: m for m in got["moved"]}
check("7.1 the pass moves both alive items whose mover's session is gone, each to the closest live agent of its project", got["applied"] and sorted(rows) == ["a40", "a41"] and rows["a40"]["to"] == FD and rows["a41"]["to"] == BM and mt(40).get("mover") == FD and mt(41).get("mover") == BM, got)
check("7.2 the front-only project's new holder is told once, by the hand-off notice, and its History line says it is told", len(pushes_to(FD, "a40")) == 1 and "it came to you" in texts(FD, "a40")[0] and "is sent the one hand-off notice" in ST.log_of(mt(40))[0]["text"]
      and "no notice is sent" not in ST.log_of(mt(40))[0]["text"], (texts(FD, "a40"), ST.log_of(mt(40))))
check("7.3 contrast, a project with a builder: its front agent that takes an item is sent nothing, and its History line says so", not pushes_to(BM) and "no notice is sent" in ST.log_of(mt(41))[0]["text"] and "sent the one hand-off notice" not in ST.log_of(mt(41))[0]["text"], (pushes_to(BM), ST.log_of(mt(41))))
close_all(); heartbeat()

# ---- 8. a hand-back to a front mover
_cfg.CFG["board"] = {"handback_hold_seconds": 0}
from stackshot.service import telling as _tl
_real_live = _tl._router_live.is_live
_tl._router_live.is_live = lambda project: False      # the router is not live for the project: the line is pushed at once, marked
try:
    put(50, mover=FD, needs=[FM, FD], writer=FM)
    drain(); pn = len(pushes())
    r = call(lambda: upd(50, FM, needs=[FD])); drain()
    got = [x for x in pushes()[pn:] if x[0] == U[FD]]
    # the router is reported not live above: this pins the direct-push fallback and the decision (who is told); the router path is covered in router_live_scenario
    check("8.1 (direct-push fallback; the router path is in router_live_scenario) a write by another session that leaves needs naming the front mover alone tells that mover once, marked for the owner (the presence gate does not hold it), with the writer and the next line; the reply says so", len(got) == 1 and len(pushes()) == pn + 1
          and got[0][1].startswith(f"{MARK} [stackshot] a50 is back with you alone (handed back by {FM})") and f"next: {FD}: do the thing" in got[0][1] and f"{FD} is a front agent: told it is back with them alone" in r, (r[-300:], pushes()[pn:]))
    put(51, project="projects/bd", mover=BD, needs=[BB, BD], writer=BB)
    drain(); pn = len(pushes())
    r = call(lambda: upd(51, BM, needs=[BD])); drain()
    new = pushes()[pn:]
    check("8.2 contrast, a project with a builder: the builder is told the item is back with the front agent, and the front mover itself is not pushed to", not [x for x in new if x[0] == U[BD]] and len([x for x in new if x[0] in (U[BB], BB)]) == 1
          and f"is back with {BD}, a front agent, alone" in new[-1][1] and f"its builder {BB} is told it is back with them alone, not them" in r, (r[-300:], new))
finally:
    _tl._router_live.is_live = _real_live

# ---- 9. the take clock on a peer hand-off
MIN = 60.0
def tick(at, *ids): return handoff_svc.handoff_tick(now=at, only=[f"a{i}" for i in ids])
def ho(i): return mt(i).get("handoff") or {}
def main_asked(gid): return [p for p in pushes_to(FM, gid) if "has gone quiet" in p[1]]
close_all()
put(60, mover=FS)
upd(60, FS, mover=FD, next=f"{FD}: do the thing"); drain()
d = float(ho(60)["delivered_at"])
cli_row(FD, "idle", d + 60)      # its turn has ended: with the ladder off the -main agent is asked only of a pane that is not running a turn
check("9.1 the hand-off is recorded for the new mover and its notice reached it once", ho(60).get("to") == FD and ho(60).get("from") == FS and len(HANDOFF(FD, "a60")) == 1, (ho(60), pushes()))
check("9.2 before the take minutes the pass does nothing", tick(d + 5 * MIN, 60) == [] and len(texts(FD, "a60")) == 1, texts(FD, "a60"))
done = tick(d + 11 * MIN, 60); drain()
check("9.3 after the take minutes the new mover is reminded once, and only it; the hander and the -main agent are told nothing", done == ["a60"] and len(texts(FD, "a60")) == 2 and texts(FD, "a60")[1].startswith("[stackshot] reminder: a60 ")
      and bool(ho(60).get("reminded_at")) and not pushes_to(FS) and not pushes_to(FM, "a60"), (done, ho(60), pushes()))
d2 = float(ho(60)["delivered_at"])
done = tick(d2 + 22 * MIN, 60); drain()
ask = main_asked("a60")
check("9.4 after another take minutes the last rung asks the project's -main agent once, marked for the owner, naming the item and the quiet mover; the item stays with its mover and the hander is still told nothing", done == ["a60"] and len(ask) == 1
      and ask[0][1].startswith(f"{MARK}\n[stackshot] a60 ") and FD in ask[0][1] and mt(60).get("mover") == FD and not pushes_to(FS), (done, ask, pushes()))
check("9.5 …later passes send nothing more", tick(d2 + 5 * 3600, 60) == [] and len(main_asked("a60")) == 1, pushes())
# contrast: a project with a builder keeps a front agent's hand-off exempt (a front-to-front record the hand-over rule would refuse there, written as the machinery would have)
put(61, project="projects/bd", mover=BD, handoff=H.new_record(BD, U[BD], BM, now0 - 3600, **{"delivered_at": now0 - 3500}))
view = {**rd(61), "gid": "a61"}
pn = len(pushes())
check("9.6 contrast, a project with a builder: a hand-off to a front agent is exempt and is never clocked, however late", handoff_svc.handoff_exempt(view, BD) and not handoff_svc.handoff_peer(view, BD) and tick(time.time() + 86400, 61) == [] and len(pushes()) == pn, (ho(61), pushes()[pn:]))
close_all()

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
