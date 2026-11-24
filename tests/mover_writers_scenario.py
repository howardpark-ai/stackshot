"""Scenario tests for the picker of a waiting item (who takes the item when its wait ends: stored as `mover`, in the older form as `post_wake_mover`), in three parts that each run in a process of their own: fixture data, no live store, no network, no server socket.
Three parts, formerly three suites (mover_writers, picker_one_reader, mover_picker). They set up different instances (the first two switch the audit on and give the process a HOME of their own, and replace the senders of a wake and the fleet's liveness; the third leaves the audit off
and replaces neither), and the server modules read their config and keep module state when they are imported, so each part runs in a process of its own (this file started again with `--part <name>`), as the three suites did, and the parent adds their checks up:
the final line is the sum. Every check of the three suites is kept, under the same name and condition.

Part `mover_writers` (formerly the suite mover_writers):

Scenario test for the server's own writers of a waiting item's picker — fixture data, no live store, no network, no server socket.

Every place that stores who picks a waiting item up when the wait ends stores it as `mover`, no longer as the old key `post_wake_mover`: the state migration's plan, the cold call's answer, the save rule, the wait-end fix,
the answer hand-over and `remember`/`restore_wait`. Every read of the picker is as before (the same picker, the same session told, the same arrival), and an item that still stores the old key reads and ends as it did. On every
save that names the picker, a write that sets a different `mover` on a waiting item drops a stored old key (the old key reads first, so it would outvote the new mover), `clear_mover` and `clear_wait` drop both keys, and
`clear_wait` also drops a stored `mover` that is he (the pick-up went with the wait) while an agent's `mover` stays as the live mover. A wait or a hold never changes who moves the item: `clear_wait` and `clear_hold` leave
the agent the item was handed to as the mover, whichever key stored it. Covered:

  1  wait-end fix    each op of the filing pass's wait fix (after, event, anchor) stores the picker as `mover` and drops an old key it finds
  2  hand-over       a decision's hand-over of a time wait (a hold with a wake, a wait on a date alone) stores the picker as `mover`; the shapes that store nothing (external, an open after, a hold with no wake, a dead then,
                     he as then) are as they were
  3  snapshot        a watch.was snapshot holds the picker as `mover`, an old snapshot is put back as `mover`; was_picker reads every form
  4  plan            the cold call's answer key stays post_wake_mover, the validated answer carries `mover`; the state migration's plan sets `mover` and drops a stored old key; its route applies the save rule
  5  save rule       an update that sets mover on a waiting item with an old key stored; clear_mover and clear_wait on each form (old key, mover, both, he, an agent); an alive item; an item with external in needs
  6  differential    an item stored under the old key against the same stored as `mover`: the picker, the session told, the arrival, the item after the wake — equal, but for the word held_by gives
  9  clears          each writer's wait, ended by clear_wait or clear_hold, leaves the agent it was handed to as the live mover (the picker stored as `mover` and an old item that stores the old key alike)

Part `picker_one_reader` (formerly the suite picker_one_reader):

Scenario test for the one reader of a waiting item's stored picker, and the safe `settle` — fixture data, no live store, no network, no server socket.

A waiting item's picker (who takes it when the wait ends) is stored under `mover`, or, in the older form, under `post_wake_mover`. Every reader goes through `model.stored_picker` (and
`watchers.was_picker` for a `watch.was` snapshot), so the two forms read the same everywhere. `model.settle`'s waiting branch (a stored mover that is he, on an item that stood his and now waits)
runs only from the update path (`waiting=True`): the on-save backstop and the start repair leave a waiting item's stored mover alone, since that is where "he picks it up when the wait ends" is written. Covered:

  1  one reader     the picker table through stored_picker, derive, Wait.mover, the view-only wait, waiting.mover_of, telling.held_by, the orphan hand-over's keys and was_picker (old and new snapshot)
  2  end of a wait  a wait on a date alone with a stored mover (no legacy key) ends through turn_alive; with nothing stored through end_date; with the legacy key through turn_alive
  3  settle         the waiting branch only with waiting=True; the alive branches as they were; the on-save backstop and the start repair leave a waiting item's stored mover alone
  4  writers        each writer that turns an item that stood his into a waiting one, and what it leaves stored: the update path, a decision's hand-over, the watchers' turn to him, the board answer, the wait-end fix
  5  phase          waiting before your move before on agent, for a table of items

Part `mover_picker` (formerly the suite mover_picker):

Scenario test for the picker: on a waiting item `mover` is who picks it up when the wait ends (the read side of "one mover") — fixture data, no live store, no network, no server socket.

An item has one mover field. While it is alive it says who moves the item now; while it waits it says who picks the item up when the wait ends. The old name of the second reading,
post_wake_mover, is still read, and while it is stored (not yet moved into mover) it wins over a stored mover. `then` stands only while the owner is the effective mover (an alive item he moves, a waiting one he picks up). Covered:

  * model.derive: the picker is the stored post_wake_mover, else the stored mover (the word none is no mover), else the default (the builder or -main agent; the owner for a relay); both stored and different → the
    post_wake_mover wins and one conflict line says so; the item's own `mover` stays empty while it waits; no conflict is named for a mover on a waiting item or a `then` beside an agent.
  * `then`: read beside the owner (alive, or the waiting item he picks up), not beside an agent, not stored-and-ignored into a conflict.
  * model.words: `· mover X`, `· mover <owner> (then Y)`; the derived tail still names post_wake_mover.
  * model.settle (waiting=True, the update path's call): a wait that replaces his state makes the agent in `then` the picker; a stored agent mover on a waiting item is never dropped; with a post_wake_mover stored only his mover goes.
  * the server readers: `held_by`, get's mover and then lines, the model-conflict lines.
  * the watchers: a wake the owner picks up keeps the stored `then`; "not yet" keeps the picker (mover) the wait had; a record of the wait written under the old name is still read.
  * the renderer's who line.

    tests/run-suite mover_writers        -> exit 0 / 1"""
import datetime, json, logging, os, pathlib, re, shutil, subprocess, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
_made = []      # the scratch folder of the part this process runs, removed in the finally of _run_part (and by _scratch at exit, whatever ends the process)
NAMES = ("zed-stew", "zed-back", "zed-helper", "zed-front")
DAY = 86400.0
DESC = "- A thing\n- It lives here\n- Done when done"


def _setup(prefix, *, audit, home):
    """The part's scratch folder with its instance (stackshot.toml, every path inside the folder, the fixtures' timezone and prefixes, transcripts inside the folder, the marks switch off; audit: the audit on),
    RULES.md, the environment the server reads (home: the process gets a HOME of its own in the folder), the fleet, the project page and the registry. Returns (tmp, T, U, now0)."""
    tmp = _scratch.mkdtemp(prefix=prefix); T = pathlib.Path(tmp); _made.append(tmp)
    toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), owner=True)
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[zed] "]', toml); assert n == 1
    toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
    toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
    if audit:
        toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    env = dict(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
    if home:
        (T / "home/.claude/sessions").mkdir(parents=True); env["HOME"] = str(T / "home")
    os.environ.update(env); os.environ.pop("STACKSHOT_URL", None)
    for d in ("store/a", "store/g", "fleet/a", "brain/projects", "transcripts/-zed"): (T / d).mkdir(parents=True)
    U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
    now0 = time.time()
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/zedwork": {"title": "Zedwork", "name": "Zedwork", "org": "zed", "tags": [], "type": "project",
                                                                                       "session": "zed-stew", "status": "active", "board": [], "board_open": 0,
                                                                                       "agents": {"zed-front": "the front", "zed-back": "the back", "zed-helper": "the helper"},
                                                                                       "back_agents": {"zed-back": "the back", "zed-helper": "the helper"}}}}))
    (T / "brain/projects/zedwork.md").write_text("---\ntitle: Zedwork\ndisplay-name: zed-stew\nagents:\n  zed-front: the front\n  background:\n    zed-back: the back\n    zed-helper: the helper\n---\n\n# Zedwork\n")
    (T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
    return tmp, T, U, now0


def _store_helpers(T, now0, U):
    """item(i, ...) writes an item of the fixture store (store a, or `store`), rd(i) reads it back, mt(i) is its metadata."""
    def item(i, status="open", subject=None, store="a", **meta):
        su = now0 - 10 * DAY
        (T / f"store/{store}/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[zed] item {i}", "description": DESC, "status": status,
                                                                 "updated": su, "state_updated": su, "confirmed": su,
                                                                 "metadata": {"owner": U["zed-front"], "project": "projects/zedwork", "next": "zed-back: do the thing", **meta}}))
    def rd(i, store="a"): return json.loads((T / f"store/{store}/{i}.json").read_text())
    def mt(i, store="a"): return rd(i, store)["metadata"]
    return item, rd, mt


def _checker():
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
    return check, fails, ran


# ================================================================ part mover_writers
def part_mover_writers():
    tmp, T, U, now0 = _setup("moverwriters-", audit=True, home=True)
    item, rd, mt = _store_helpers(T, now0, U)
    check, fails, ran = _checker()
    logging.disable(logging.INFO)
    from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import model; from stackshot.waits import waiting, watchers as wk
    from stackshot.model import cold_call as cold
    from stackshot.model import holders as _holders
    from stackshot.model import migration as M
    from stackshot.audit import audit_run as AR
    from stackshot.core import config as _cfg
    from stackshot.service import store as _service_store
    from stackshot.service import update as _update_svc
    from stackshot.service import migrations as migsvc
    from stackshot.service import watching as watching_svc
    from stackshot.service import wakes as wakes_svc
    from stackshot.service import event_waits as evwaits_svc
    from stackshot.service import telling
    from stackshot.service import answer_handover as handover_svc
    from stackshot.service import wait_gates as wait_gates_svc, released as released_svc
    from stackshot.service import wait_fixes as _wait_fixes_svc
    from stackshot.fleet import liveness as LV
    from stackshot.web import home
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    _web_page_debts._owing_note = lambda debtor: ""
    SENT = []
    telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
    telling.front_sender = lambda who: False
    released_svc._own_repo = lambda: "acme/widgets"
    wait_gates_svc._evwait_preread = lambda kind, phrase: None
    evwaits_svc.evw_boxes = lambda: {}
    LV.puller_online = lambda rec: bool(rec)
    (T / "state").mkdir(parents=True, exist_ok=True); (T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
    CFG = _cfg.CFG.setdefault("model", {}); CFG.update(guards=False, watchers=True, pause=False)
    ZONE_HOURS = 4
    day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
    BACK, HELP, FRONT = "zed-back", "zed-helper", "zed-front"
    OWN = model.owner_display()
    LEG = model.LEGACY_PICKER_KEY
    FUT = day(5)
    D = lambda **m: model.derive({"status": "open", "metadata": {"project": "projects/zedwork", **m}}, now0)
    def its(**meta): return {"status": "open", "metadata": {"project": "projects/zedwork", **meta}}
    def guards(on): CFG["guards"] = on
    def old_form(meta):
        """the item as main stored it: the picker under the old key (a `mover` that was popped there is not carried over)."""
        m = dict(meta)
        if "mover" in m: m[LEG] = m.pop("mover")
        return m
    def stores_mover(meta, who): return meta.get("mover") == who and LEG not in meta
    def stores_old(meta, who): return meta.get(LEG) == who and "mover" not in meta

    # ================================================================ 1. the wait-end fix (the filing pass)
    ROLES = {BACK: {"role": "background"}, HELP: {"role": "background"}, FRONT: {"role": "front"}}
    def env(**kw): return AR.Env(roles=ROLES, fallback=lambda p: FRONT, builder=lambda p: BACK, page_of=lambda p: ("", None), deliver=lambda to, text, fyi=False: (True, "[200] ok"), sessions=lambda: None,
                                 pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}}, **kw)
    OLD = now0 - 3 * 3600.0
    def gitem(i, nxt, **meta):
        (T / f"store/g/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[zed] item {i}", "description": DESC, "status": "open", "updated": OLD, "written_at": OLD, "written_by": BACK,
                                                        "state_updated": OLD, "confirmed": OLD,
                                                        "metadata": {"owner": U[FRONT], "project": "projects/zedwork", "state": "doing", "needs": [BACK], "next": nxt, **meta}}))
    ref = lambda n: f"board#{n}"      # an item reference built at run time, so no literal id sits in the file
    gid = lambda n: f"g{n}"
    def fix_pass():
        items_ = {f"g{p.stem}": json.loads(p.read_text()) for p in (T / "store/g").glob("*.json")}
        return AR.filing_pass(now=now0, items=items_, anchors={}, env=env(wait_end=_wait_fixes_svc._wait_end_fix, wait_facts=_wait_fixes_svc._wait_end_facts))
    def clear_g():
        for p in (T / "store/g").glob("*.json"): p.unlink()
    (T / "state/audit").mkdir(parents=True, exist_ok=True)
    gitem(9202, "zed-helper: build the thing")
    gitem(9201, f"zed-back: wait for {ref(9202)} to close, then write the summary")
    gitem(9203, f"zed-back: wait for {ref(9202)} to close, then write the summary", mover=BACK)
    gitem(9204, f"zed-back: wait for {ref(9202)} to close, then write the summary", **{LEG: HELP})         # an old key left on an alive item: the new picker replaces it
    r = fix_pass()
    for n in (9201, 9203, 9204):
        m_ = mt(n, "g"); mod_ = model.derive(rd(n, "g"), now0)
        check(f"1 after (g{n}): the item waits on the item's close, with the picker stored as `mover` and no old key", m_.get("wait_kind") == "item" and stores_mover(m_, BACK) and mod_.state == "waiting" and mod_.wait.mover == BACK and mod_.wait.mover_explicit, m_)
        check(f"1 after (g{n}): the session it is told is the mover, worded mover", telling.held_by(rd(n, "g"))[0] == BACK, telling.held_by(rd(n, "g")))
    check("1 after: the pass said it fixed them", len(r.get("wait_end", {}).get("fixed", [])) == 3, r.get("wait_end"))
    clear_g()
    gitem(9211, "zed-back: wait for other/repo#7 to be merged, then write the summary")
    gitem(9213, "zed-back: wait for the reply in https://github.com/acme/widgets/issues/5")
    gitem(9214, "zed-back: wait for other/repo#7 to be merged, then write the summary", **{LEG: HELP}, wait_kind="event", wait_event="pr_merged other/repo#7", state=None)
    r = fix_pass()
    for n, what in ((9211, "event"), (9213, "anchor")):
        m_ = mt(n, "g")
        check(f"1 {what} wait (g{n}): the picker is stored as `mover`", m_.get("wait_kind") == what and stores_mover(m_, BACK) and model.derive(rd(n, "g"), now0).state == "waiting" and model.derive(rd(n, "g"), now0).wait.mover == BACK, (m_, r.get("wait_end")))
    check("1 a stored event wait that only lacks its backstop (the fix writes a day): the old key left on it stays", mt(9214, "g").get(LEG) == HELP, mt(9214, "g"))
    clear_g()

    # ================================================================ 2. a decision's hand-over of a time wait
    def hand(meta, mover_in, then_in, **kw):
        m_ = dict(meta); handover_svc._decision_hand_over(m_, mover_in, then_in, now=now0, **kw); return m_
    BASE = {"project": "projects/zedwork", "needs": [BACK]}
    m_ = hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT}, OWN, HELP, waiting=True)
    check("2 a hold with a wake and an agent in then: a time wait, the picker = then stored as `mover`, then cleared, the stamp set", m_.get("wait_kind") == "time" and stores_mover(m_, HELP) and "then" not in m_ and m_["watch"]["set_at"] == now0, m_)
    m_ = hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT}, OWN, HELP, parked=True)
    check("2 …a parked item is the same", m_.get("wait_kind") == "time" and stores_mover(m_, HELP) and "then" not in m_, m_)
    m_ = hand({**BASE, "mover": OWN, "then": HELP, "until": FUT}, OWN, HELP, waiting=True)
    check("2 a wait on a date alone: no kind, the picker = then stored as `mover`, then cleared", "wait_kind" not in m_ and stores_mover(m_, HELP) and "then" not in m_ and m_["until"] == FUT, m_)
    m_ = hand({**BASE, "then": HELP, LEG: BACK, "hold": True, "wake": FUT}, "", HELP, waiting=True)
    check("2 an old key stored on the item is replaced by the then (the one picker, never two)", stores_mover(m_, HELP), m_)
    m_ = hand({**BASE, "mover": BACK, "then": HELP, "until": FUT}, BACK, HELP, waiting=True)
    check("2 a stored agent mover: the then takes it (the one picker is `mover`, no old key appears)", stores_mover(m_, HELP) and D(**m_).wait.mover == HELP, m_)
    # the shapes that store no picker are as they were
    item(1, subject="[zed] an open item the others wait after")
    for label, meta, kw in (("a hold with no wake", {**BASE, "mover": OWN, "then": HELP, "hold": True}, dict(waiting=True)),
                            ("a then that is no live session", {**BASE, "mover": OWN, "then": "nobody-here", "hold": True, "wake": FUT}, dict(waiting=True)),
                            ("he as then", {**BASE, "mover": OWN, "then": OWN, "hold": True, "wake": FUT}, dict(waiting=True))):
        m_ = hand(meta, OWN, meta.get("then", ""), **kw)
        check(f"2 {label}: no picker is stored, as before", "mover" not in m_ and LEG not in m_ and "wait_kind" not in m_, m_)
    m_ = hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT, "after": ["a1"]}, OWN, HELP, waiting=True)
    check("2 an open after link: no time wait is stored, the picker = then is stored as `mover` for the release of the after (the release finds it with no then), then cleared, no stamp (the last prerequisite's close releases it)",
          stores_mover(m_, HELP) and "then" not in m_ and LEG not in m_ and "wait_kind" not in m_ and "watch" not in m_, m_)
    # external in needs: exactly as on main (then dropped, nothing stored), for the wait on a date alone and for the hold with a wake
    for label, extra in (("a wait on a date alone", {"until": FUT}), ("a hold with a wake", {"hold": True, "wake": FUT})):
        meta = {"project": "projects/zedwork", "needs": [BACK, "external"], "mover": OWN, "then": HELP, **extra}
        m_ = hand(meta, OWN, HELP, waiting=True)
        check(f"2 external in needs, {label}: then is dropped, the mover he goes, no picker and no kind stored: the item is as main left it", m_ == {k: v for k, v in meta.items() if k not in ("mover", "then")}, m_)
        m_ = hand({**meta, LEG: BACK}, OWN, HELP, waiting=True)
        check(f"2 …with the old key stored on it: it stays as it was, never moved", m_.get(LEG) == BACK and "mover" not in m_ and "then" not in m_, m_)
    # a wait stored as a kind, with no relay, no external, no session in needs and no stored picker: the then it carried stands in for the picker
    STORED = {"project": "projects/zedwork", "needs": [], "until": FUT}
    for kind, extra in (("event", {"wait_event": "pr_merged other/repo#7"}), ("anchor", {"wait_anchor": "https://github.com/acme/widgets/issues/5", "wait_event": "the reply"}), ("item", {"after": ["a1"]}), ("time", {"hold": True, "wake": FUT})):
        meta = {**STORED, "wait_kind": kind, **extra, "mover": OWN, "then": HELP}
        m_ = hand(meta, OWN, HELP, waiting=True)
        check(f"2 a {kind} wait stored as a kind, nothing else naming a picker: the then becomes `mover`, then is gone, the kind and the rest stay as they were", m_.get("mover") == HELP and "then" not in m_ and LEG not in m_
              and m_.get("wait_kind") == kind and {k: v for k, v in m_.items() if k not in ("mover", "then")} == {k: v for k, v in meta.items() if k not in ("mover", "then")}, m_)
    RELAYED = {**STORED, "wait_kind": "relay", "wait_event": "the reply", "ask_by": FUT}
    m_ = hand({**RELAYED, "mover": OWN, "then": HELP}, OWN, HELP, waiting=True)
    check("2 …a relay (the owner picks it up): the then stays beside him, nothing is stored as the picker", m_.get("then") == HELP and "mover" not in m_ and LEG not in m_ and m_.get("wait_kind") == "relay", m_)
    m_ = hand({**RELAYED, "then": HELP}, "", HELP, waiting=True)
    check("2 …a relay with no mover stored: the then stays, nothing is stored as the picker", m_.get("then") == HELP and "mover" not in m_ and LEG not in m_, m_)
    meta = {**STORED, "wait_kind": "event", "wait_event": "pr_merged other/repo#7", "needs": [BACK, "external"], "mover": OWN, "then": HELP}
    m_ = hand(meta, OWN, HELP, waiting=True)
    check("2 …an external wait: the then is left alone, nothing is stored as the picker", m_.get("then") == HELP and "mover" not in m_ and LEG not in m_ and m_.get("wait_kind") == "event", m_)
    for label, meta in (("a session in needs", {**STORED, "needs": [BACK], "wait_kind": "event", "wait_event": "pr_merged other/repo#7", "mover": OWN, "then": HELP}),
                        ("a picker stored as mover", {**STORED, "wait_kind": "event", "wait_event": "pr_merged other/repo#7", "mover": BACK, "then": HELP}),
                        ("a picker stored under the old key", {**STORED, "wait_kind": "event", "wait_event": "pr_merged other/repo#7", LEG: BACK, "then": HELP})):
        m_ = hand(meta, OWN if meta.get("mover") == OWN else "", HELP, waiting=True)
        check(f"2 …{label}: the item is left as it was (only a stored mover that is he goes), the then does not take a picker's place", m_ == {k: v for k, v in meta.items() if not (k == "mover" and v == OWN)}, m_)

    # ================================================================ 3. the snapshot of a wait, and its restore
    def remembered(meta):
        m_ = dict(meta); wk.remember(m_, "relay", now0); return m_
    RW = {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), "needs": [BACK]}
    for label, meta, want in (("a wait stored as mover", {**RW, "mover": HELP}, {"mover": HELP}), ("a wait stored under the old key", {**RW, LEG: HELP}, {"mover": HELP}),
                              ("both stored (the old key reads first)", {**RW, LEG: HELP, "mover": BACK}, {"mover": HELP}), ("the old key with the word none", {**RW, LEG: "none"}, {LEG: "none"}),
                              ("a wait on a date alone under the old key", {"until": FUT, "needs": [BACK], LEG: HELP}, {"mover": HELP})):
        m_ = remembered(meta)
        check(f"3 remember, {label}: the snapshot holds the picker as `mover` (an old key is folded into it; the word none under the old key stays as stored)", {k: m_["watch"]["was"].get(k) for k in (LEG, "mover") if k in m_["watch"]["was"]} == want, m_["watch"])
    check("3 was_picker reads every form (old snapshot, new snapshot, both)", wk.was_picker({LEG: HELP}) == wk.was_picker({"mover": HELP}) == HELP and wk.was_picker({LEG: BACK, "mover": HELP}) == BACK, None)
    check("3 was_picker: a snapshot's word none under the old key is a session of that name, under `mover` nobody (as on main)", wk.was_picker({LEG: "none"}) == "none" and wk.was_picker({"mover": "none"}) == "", None)
    def restored(was, **now_meta):
        m_ = {"project": "projects/zedwork", "needs": ["decision"], "ask": "x", "watch": {"asked": "relay", "was": was, "at": now0}, **now_meta}
        wk.restore_wait(m_, day(9), True, now0); return m_
    for label, was, ok in (("an old snapshot (the old key)", {"wait_kind": "relay", "wait_event": "the reply", LEG: HELP}, lambda m: stores_mover(m, HELP)),
                           ("a new snapshot (mover)", {"wait_kind": "relay", "wait_event": "the reply", "mover": HELP}, lambda m: stores_mover(m, HELP)),
                           ("both keys", {"wait_kind": "relay", "wait_event": "the reply", LEG: HELP, "mover": HELP}, lambda m: stores_mover(m, HELP)),
                           ("the old key with the word none", {"wait_kind": "relay", "wait_event": "the reply", LEG: "none"}, lambda m: m.get(LEG) == "none" and "mover" not in m)):
        m_ = restored(was)
        check(f"3 restore_wait, {label}: the wait is back with its picker stored as `mover` (the word none under the old key as stored)", ok(m_) and m_.get("wait_kind") == "relay" and m_.get("ask_by") == day(9), m_)
    m_ = restored({"wait_kind": "relay", "wait_event": "the reply", LEG: HELP}, **{LEG: BACK})
    check("3 restore_wait: an old key still on the item is replaced by the snapshot's picker, stored as `mover`", stores_mover(m_, HELP), m_)
    m_ = restored({"until": FUT, "needs": [BACK, "external"], LEG: HELP})
    check("3 restore_wait: a wait on a date alone with external in needs and the old key goes back as `mover`", stores_mover(m_, HELP), m_)
    # the server reads the snapshot either way
    for n, was in ((6, {LEG: HELP}), (7, {"mover": HELP})):
        item(n, subject=f"[zed] was {n}", needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}], watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), **was}, "at": now0})
        m_ = dict(mt(n)); r = wait_gates_svc._watch_answer(rd(n), m_, {"do": "arrived", "text": "", "date": ""}, now0)
        check(f"3 _watch_answer arrived, snapshot {sorted(was)[0]}: the agent it names has the item", m_.get("mover") == HELP and m_.get("needs") == [HELP] and HELP in r, (r, m_))
        item(n + 10, subject=f"[zed] was again {n}", needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}], watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), **was}, "at": now0})
        m_ = dict(mt(n + 10)); r = wait_gates_svc._watch_answer(rd(n + 10), m_, {"do": "wait", "text": "", "date": day(9)}, now0)
        check(f"3 _watch_answer not yet, snapshot {sorted(was)[0]}: the wait is back with its picker stored as `mover`", stores_mover(m_, HELP) and m_.get("ask_by") == day(9) and "waits again" in r, (r, m_))

    # ================================================================ 4. the plan: the cold call's edge and the migration
    TODAY = __import__("datetime").date.today()
    iso = lambda n: (TODAY + __import__("datetime").timedelta(days=n)).isoformat()
    MOV = [BACK, HELP]
    ans = {"wait": "yes", "kind": "item", "input": {"after": [ref(23)]}, "end": iso(5), "post_wake_mover": "ZED-BACK", "reason": "r", "confidence": "high"}
    res, why = cold.validate_hidden(ans, TODAY, MOV, gid(22), lambda s: gid(23) if s == ref(23) else "", [], "")
    check("4 cold call: the validated answer carries the picker as `mover` (copied from the list), never the old key", res is not None and res.get("mover") == BACK and LEG not in res, (res, why))
    res2, why2 = cold.validate_hidden({**ans, "post_wake_mover": "somebody"}, TODAY, MOV, gid(22), lambda s: gid(23), [], "")
    check("4 cold call: a name that is not on the list is still refused", res2 is None and "post-wake mover" in why2, (res2, why2))
    check("4 cold call: the model-facing prompt still names post_wake_mover as the answer key", any(LEG in str(v) for v in vars(cold).values() if isinstance(v, str) and '"wait": "yes"' in v), None)
    check("4 migration: the route's fields take mover and may drop the old key", "mover" in M.OPEN_SET_FIELDS and LEG in M.DROP_FIELDS, None)
    # the route applies the save rule: a write that sets mover on an item with an old key stored drops it (the plan itself drops it too: migration_scenario)
    guards(True)
    try:
        for n, sets, drops, label in ((30, {"mover": BACK}, [], "the old key goes beside a mover the write sets"), (31, {"mover": BACK}, [LEG], "…and the plan's own drop of it passes the route"), (32, {"wait_kind": "relay"}, [], "a write that sets no mover leaves the old key"), (33, {"mover": BACK, LEG: BACK}, [], "a write that names both keys is stored as written")):
            item(n, subject=f"[zed] migrate {n}", needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=day(5), **{LEG: HELP})
            it_ = rd(n)
            out = migsvc.migrate_one({"item": f"a{n}", "set": sets, "drop": drops, "expect": it_["updated"], "expect_sig": list(migsvc.migrate_sig(f"a{n}", it_)), "kind": "test", "note": "t"})
            want_gone = "mover" in sets and LEG not in sets
            check(f"4 migration route: {label}", out["action"] in ("set", "already") and (stores_mover(mt(n), BACK) if want_gone else (mt(n).get(LEG) == (BACK if LEG in sets else HELP))), (out, mt(n)))
    finally:
        guards(False)

    # ================================================================ 5. the save rule (the update path)
    def upd(n, **kw): return _update_svc._update(f"a{n}", sender=BACK, **kw)
    def ruled(n, start, **kw):
        item(n, subject=f"[zed] rule {n}", **start)
        upd(n, **kw)
        return mt(n)
    WAITING_KEYS = dict(needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=FUT)
    for g_ in (False, True):
        guards(g_)
        tag = f"(guards {'on' if g_ else 'off'})"
        m_ = ruled(100, {**WAITING_KEYS, LEG: HELP}, mover=BACK)
        check(f"5 a mover set on a waiting item that stores the old key: the old key goes, the new mover is the picker {tag}", stores_mover(m_, BACK) and D(**m_).wait.mover == BACK, m_)
        m_ = ruled(101, {**WAITING_KEYS, LEG: HELP, "mover": HELP}, mover=BACK)
        check(f"5 …with both stored {tag}", stores_mover(m_, BACK) and D(**m_).wait.mover == BACK, m_)
        m_ = ruled(102, {**WAITING_KEYS, "mover": HELP}, mover=BACK)
        check(f"5 …with only a mover stored: replaced, no old key appears {tag}", stores_mover(m_, BACK), m_)
        m_ = ruled(103, {**WAITING_KEYS, LEG: HELP}, clear_mover=True)
        check(f"5 clear_mover on a waiting item with the old key: both go, so the old key cannot become the picker {tag}", "mover" not in m_ and LEG not in m_ and D(**m_).wait.mover == OWN and not D(**m_).wait.mover_explicit, m_)      # a relay's default picker is he
        m_ = ruled(104, {**WAITING_KEYS, LEG: HELP, "mover": BACK}, clear_mover=True)
        check(f"5 clear_mover with both stored: both go {tag}", "mover" not in m_ and LEG not in m_, m_)
        m_ = ruled(105, {**WAITING_KEYS, "mover": HELP}, clear_mover=True)
        check(f"5 clear_mover with a mover only: it goes {tag}", "mover" not in m_ and LEG not in m_, m_)
        m_ = ruled(106, {**WAITING_KEYS, LEG: HELP}, clear_wait=True)
        check(f"5 clear_wait with the old key: the wait and the old key go, the agent it named stays as the live mover {tag}", "wait_kind" not in m_ and LEG not in m_ and m_.get("mover") == HELP and D(**m_).state == "alive" and D(**m_).mover == HELP, m_)
        m_ = ruled(107, {**WAITING_KEYS, "mover": HELP}, clear_wait=True)
        check(f"5 clear_wait with an agent's mover: the wait goes, the agent stays as the live mover {tag}", "wait_kind" not in m_ and m_.get("mover") == HELP and LEG not in m_ and D(**m_).state == "alive" and D(**m_).mover == HELP, m_)
        m_ = ruled(108, {**WAITING_KEYS, "mover": OWN, "then": HELP}, clear_wait=True)
        check(f"5 clear_wait with a stored mover that is he (he picked the item up when the wait ended): it goes with the wait {tag}", "wait_kind" not in m_ and "mover" not in m_ and LEG not in m_, m_)
        m_ = ruled(109, {**WAITING_KEYS, "mover": HELP, LEG: BACK}, clear_wait=True)
        check(f"5 clear_wait with both stored: the picker the reader answered first (the old key) is the one kept as mover, the old key goes {tag}", "wait_kind" not in m_ and m_.get("mover") == BACK and LEG not in m_, m_)
        m_ = ruled(110, {**WAITING_KEYS, LEG: OWN, "mover": HELP}, clear_wait=True)
        check(f"5 clear_wait with the old key that is he beside an agent mover: the old key goes, the agent stays {tag}", "wait_kind" not in m_ and m_.get("mover") == HELP and LEG not in m_, m_)
    guards(False)
    # alive items and writes that name nothing
    item(120, subject="[zed] alive his", needs=["decision"], ask="Decide: x", mover=OWN, then=HELP)
    upd(120, clear_wait=True)
    check("5 clear_wait on an alive item that is his: nothing waited, so his mover stays", mt(120).get("mover") == OWN and mt(120).get("then") == HELP, mt(120))
    item(121, subject="[zed] alive agent", needs=[BACK], mover=BACK)
    upd(121, mover=HELP)
    check("5 a mover set on an alive item: the plain write, no old key appears", stores_mover(mt(121), HELP), mt(121))
    item(122, subject="[zed] alive stray", needs=[BACK], **{LEG: HELP})
    upd(122, mover=BACK)
    check("5 a mover set on an alive item that stores a stray old key: the rule is for a wait, the stray stays as it was (the model lists it)", mt(122).get(LEG) == HELP and mt(122).get("mover") == BACK, mt(122))
    item(123, subject="[zed] other write", **{**WAITING_KEYS, LEG: HELP})
    upd(123, next="zed-back: a note")
    check("5 a write that names no mover leaves the old key where it was (no migration of stored items here)", mt(123).get(LEG) == HELP and "mover" not in mt(123), mt(123))
    item(124, subject="[zed] clear both", **{**WAITING_KEYS, LEG: HELP})
    try:
        upd(124, clear_wait=True, post_wake_mover=HELP)
        check("5 clear_wait with the old parameter in the same call is refused as before", False, mt(124))
    except Exception as e:  # noqa: BLE001
        check("5 clear_wait with the old parameter in the same call is refused as before", "does not go with" in str(e), str(e))
    item(125, subject="[zed] the old parameter", needs=[BACK])
    upd(125, wait_kind="time", hold=True, wake=FUT, post_wake_mover=HELP)
    check("5 the old parameter is read as mover: the picker is stored as mover and the old key is not stored", mt(125).get("mover") == HELP and LEG not in mt(125), mt(125))
    # the rule on the write's own sets and drops (model.settle_picker_keys, which the update path calls after it applies a write's fields)
    def applied(meta, setv=None, drop=()):
        m_ = dict(meta); _holders._model_apply(m_, "open", dict(setv or {}), set(drop)); model.settle_picker_keys(m_, dict(setv or {}), set(drop), model.waits_stored(meta)); return m_
    RELAY = {"wait_kind": "relay", "wait_event": "the reply", "ask_by": FUT, "needs": [BACK]}
    m_ = applied({**RELAY, "mover": OWN, "then": HELP}, drop={"ask_by"})
    check("5 one wait field dropped is no clear_wait: a mover that is he stays", m_.get("mover") == OWN and "ask_by" not in m_, m_)
    m_ = applied({**RELAY, "mover": OWN, "then": HELP}, setv={"mover": OWN}, drop=set(model.WAIT_GROUP))
    check("5 clear_wait beside a mover the same write sets: the mover the write names stays, whoever it is", m_.get("mover") == OWN and "wait_kind" not in m_, m_)
    m_ = applied({**RELAY, LEG: HELP}, setv={"mover": BACK, LEG: FRONT})
    check("5 a write that names the old key itself (the old parameter) is stored as written, beside its mover", m_.get("mover") == BACK and m_.get(LEG) == FRONT, m_)
    m_ = applied({**RELAY, LEG: HELP}, setv={"mover": BACK})
    check("5 …and one that names only the mover drops the old key", stores_mover(m_, BACK), m_)
    m_ = applied({**RELAY, LEG: HELP, "mover": HELP}, drop={"mover"})
    check("5 clear_mover drops both keys at the function too", "mover" not in m_ and LEG not in m_, m_)
    # external in needs: the rule is the same, and the end of a wait on a date alone is the one the earlier rule decided (only the old key turns it)
    item(126, subject="[zed] external, date only", needs=[BACK, "external"], until=FUT, **{LEG: HELP})
    upd(126, mover=BACK)
    check("5 external in needs, a wait on a date alone, the old key stored, an update sets mover: the old key goes (the one picker is the new mover)", stores_mover(mt(126), BACK), mt(126))
    item(128, subject="[zed] date only, old key", needs=[BACK], until=FUT, **{LEG: HELP})
    upd(128, mover=BACK)
    check("5 a wait on a date alone (stored as an until, folded for the write): a mover set drops the old key like any wait", stores_mover(mt(128), BACK) and mt(128).get("until") == FUT, mt(128))
    item(129, subject="[zed] date only, he picks it up", needs=[BACK], until=FUT, mover=OWN, then=HELP)
    upd(129, clear_wait=True)
    check("5 clear_wait on a wait on a date alone that he picks up: the date, the pick-up and nothing else go", "until" not in mt(129) and "mover" not in mt(129) and mt(129).get("then") == HELP, mt(129))
    item(127, subject="[zed] external, with a kind", **{**WAITING_KEYS, "needs": [BACK, "external"], LEG: HELP})
    upd(127, mover=BACK)
    check("5 external in needs, a wait with a kind: the same", stores_mover(mt(127), BACK), mt(127))

    # ================================================================ 6. the differential: an item stored under the old key against the same stored as `mover`, read by every reader
    def readers(n, meta):
        """what each reader returns for the item stored as `meta`: the picker, the session told, its word, the arrival and the item after the wake pass (the date moved into the past)."""
        item(n, subject=f"[zed] twin {n}", **meta)
        mod_ = model.derive(rd(n), now0)
        held = telling.held_by(rd(n))
        picker = (mod_.wait.mover, mod_.wait.mover_explicit, mod_.picker) if mod_.wait else (mod_.mover,)
        past = dict(meta)
        for k in ("wake", "until", "ask_by"):
            if k in past: past[k] = day(-1)
        item(n + 500, subject=f"[zed] twin fired {n}", **past)
        SENT.clear(); watching_svc.watch_pass()
        after = mt(n + 500)
        woke = after.get("woke", {})
        return {"picker": picker, "told": held[0], "word": held[1], "state": mod_.state,
                "after": {"mover": after.get("mover"), "needs": after.get("needs"), "woke_to": woke.get("to"), "then": after.get("then"), "decision": "decision" in (after.get("needs") or [])},
                "messages": sorted(x[1] for x in SENT)}
    DIFFS = []
    def compare(label, new_meta, n):
        a, b = readers(n, old_form(new_meta)), readers(n + 20, new_meta)
        same = {k: a[k] == b[k] for k in a}
        differs = [k for k, v in same.items() if not v]
        # the stored key is the one difference; the word held_by gives the session is `then` for the old key, `mover` for the new, never a different session
        check(f"6 {label}: the same picker, session told, arrival and item after the wake (differences: {differs or 'none'})", set(differs) <= {"word"} and a["told"] == b["told"], (a, b))
        if differs: DIFFS.append((label, differs))
        return a, b
    for label, meta in (("time wait stored as mover", {**BASE, "mover": HELP, "wait_kind": "time", "hold": True, "wake": FUT}),
                        ("wait on a date alone stored as mover", {**BASE, "mover": HELP, "until": FUT}),
                        ("item wait stored as mover", {**BASE, "mover": BACK, "wait_kind": "item", "after": ["a9"], "until": FUT}),
                        ("event wait stored as mover", {**BASE, "mover": BACK, "wait_kind": "event", "wait_event": "pr_merged other/repo#7", "until": FUT}),
                        ("relay wait", {**BASE, "mover": HELP, "wait_kind": "relay", "wait_event": "the reply", "ask_by": FUT}),
                        ("a snapshot restore (relay) with a mover", restored({"wait_kind": "relay", "wait_event": "the reply", "mover": HELP}, needs=[BACK]))):
        compare(label, meta, 200 + 3 * len(DIFFS) + len(ran) % 7)
    # he is the picker: a relay turns to him, the then beside him is read
    a, b = compare("relay wait he picks up, then beside him", {**BASE, "mover": OWN, "then": HELP, "wait_kind": "relay", "wait_event": "the reply", "ask_by": FUT}, 300)
    check("6 …he picks it up, and then stands beside him", a["after"]["decision"] and b["after"]["decision"] and a["after"]["then"] == b["after"]["then"], (a, b))
    # external in needs, a wait on a date alone: the stored picker's key decides the end (PR one's rule): only the old key turns it. A hand-over stores no picker for it, so the shape does not arise from a writer here.
    a = readers(310, {**BASE, "needs": [BACK, "external"], LEG: HELP, "until": FUT})
    b = readers(311, {**BASE, "needs": [BACK, "external"], "mover": HELP, "until": FUT})
    check("6 external in needs, a date-only wait, stored under the old key versus mover: the earlier rule still holds (only the old key turns the item to its picker; a stored mover alone ends on the date)",
          a["after"]["needs"] == [HELP] and b["after"]["needs"] == [BACK, "external"] and a["picker"] == b["picker"], (a, b))

    # ================================================================ 7. a stored old key the save rule drops is no change to the wait: its chases and its clock stay
    SET_AT = now0 - 5000.0
    CHASES = [{"at": now0 - 100, "by": "the server", "note": "a chase"}]
    WAITS = {"relay": dict(wait_kind="relay", wait_event="the reply", ask_by=FUT),
             "anchor": dict(wait_kind="anchor", wait_anchor="https://github.com/acme/widgets/issues/5", wait_event="the reply", ask_by=FUT),
             "time": dict(wait_kind="time", hold=True, wake=FUT)}
    SHAPES = {"old key": {LEG: HELP}, "both": {LEG: HELP, "mover": BACK}, "mover": {"mover": HELP}, "nothing": {}}
    WRITES = {"mover=": dict(mover=FRONT), "clear_mover": dict(clear_mover=True), "a plain note": dict(next="zed-back: a note")}
    n7 = 700
    for wl, wmeta in WAITS.items():
        for sl, smeta in SHAPES.items():
            for ol, kw in WRITES.items():
                n7 += 1
                item(n7, subject=f"[zed] clock {n7}", needs=[BACK], watch={"set_at": SET_AT}, chases=CHASES, **wmeta, **smeta)
                try:
                    upd(n7, **kw); err = ""
                except Exception as e:  # noqa: BLE001
                    err = str(e)[:200]
                m_ = mt(n7)
                check(f"7 {wl} wait, {sl} stored, {ol}: the chases and the wait's clock stay as they were{(' (refused: ' + err + ')') if err else ''}", not err and m_.get("chases") == CHASES and (m_.get("watch") or {}).get("set_at") == SET_AT, m_)
    # what does change the wait still restarts it: a moved date, and the old key named on purpose
    for wl, kw in (("relay", dict(ask_by=day(9))), ("relay", dict(post_wake_mover=BACK))):
        n7 += 1
        item(n7, subject=f"[zed] clock {n7}", needs=[BACK], watch={"set_at": SET_AT}, chases=CHASES, **WAITS[wl], **{LEG: HELP})
        upd(n7, **kw)
        m_ = mt(n7)
        check(f"7 {wl} wait, an update of {sorted(kw)[0]}: the wait is new, so its clock is stamped and its chases start over (as on main)", "chases" not in m_ and (m_.get("watch") or {}).get("set_at", 0) > SET_AT, m_)

    # the old parameter written with the very value the old key already holds is no change to the wait (as on main); the same session in another spelling (another letter case, its id) is a different text there, so it is a change, as on main
    for wl, wmeta in WAITS.items():
        for stored, given in ((HELP, HELP), (HELP, HELP.upper()), (HELP.upper(), HELP), (HELP, U[HELP])):
            n7 += 1
            item(n7, subject=f"[zed] clock {n7}", needs=[BACK], watch={"set_at": SET_AT}, chases=CHASES, **wmeta, **{LEG: stored})
            try:
                upd(n7, post_wake_mover=given); err = ""
            except Exception as e:  # noqa: BLE001
                err = str(e)[:200]
            m_ = mt(n7)
            stays = stored == given
            check(f"7 {wl} wait, old key {stored!r}, the old parameter written as {given!r}: the chases and the wait's clock {'stay' if stays else 'start over, as on main'}{(' (refused: ' + err + ')') if err else ''}",
                  not err and (m_.get("chases") == CHASES and (m_.get("watch") or {}).get("set_at") == SET_AT) == stays, (m_, err))
    n7 += 1
    item(n7, subject=f"[zed] clock {n7}", needs=[BACK], watch={"set_at": SET_AT}, chases=CHASES, **WAITS["relay"], **{LEG: HELP})
    try:
        upd(n7, mover=FRONT, post_wake_mover="none"); err = ""
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    m_ = mt(n7)
    check(f"7 relay wait, the old key cleared (post_wake_mover=none) beside a differing mover: refused, naming mover, and the wait is untouched{(' (' + err + ')') if err else ''}", "mover" in err and m_.get(LEG) == HELP and (m_.get("watch") or {}).get("set_at") == SET_AT, (m_, err))

    # ================================================================ 8. a mover that restates the old key changes nothing
    def after_wake(n, meta):
        """the stored item, one day on: what the wake pass makes of it (readers' twin with its date in the past)."""
        return readers(n, {k: v for k, v in meta.items() if k not in ("owner", "project")})
    EXT = dict(needs=[BACK, "external"], until=FUT)
    for label, extra, kw, keeps in (("the same session as the old key", {LEG: HELP}, dict(mover=HELP), True), ("…named in another case", {LEG: HELP}, dict(mover=HELP.upper()), True),
                                    ("another session", {LEG: HELP}, dict(mover=BACK), False)):
        n7 += 1
        item(n7, subject=f"[zed] external {n7}", **EXT, **extra)
        upd(n7, **kw)
        m_ = mt(n7)
        r_ = after_wake(n7 + 100, m_)
        check(f"8 external in needs, a wait on a date alone, the old key stored, an update sets mover to {label}: the old key {'stays' if keeps else 'goes'}", (m_.get(LEG) == HELP) == keeps and (LEG not in m_) == (not keeps), m_)
        check(f"8 …and the item ends as {'it did on main (turned alive to the old key agent)' if keeps else 'the new mover has it (a choice of this change: it ends on its date, external still in needs)'}",
              (r_["after"]["needs"] == [HELP]) if keeps else (r_["after"]["needs"] == [BACK, "external"]), r_)
    for label, stored, given in (("its id, the update gives its name", U[HELP], HELP), ("its name, the update gives its id", HELP, U[HELP])):
        n7 += 1
        item(n7, subject=f"[zed] by id {n7}", **EXT, **{LEG: stored})
        upd(n7, mover=given)
        m_ = mt(n7)
        r_ = after_wake(n7 + 100, m_)
        check(f"8 external in needs, a wait on a date alone, the old key holds {label}: the same session, so the old key stays and the item ends as on main", m_.get(LEG) == stored and r_["after"]["needs"] == [stored], (m_, r_))
    n7 += 1
    item(n7, subject=f"[zed] relay by id {n7}", **{**WAITING_KEYS, LEG: U[HELP]})
    upd(n7, mover=HELP)
    check("8 a relay wait whose old key holds the session's id: an update of mover to its name leaves the old key", mt(n7).get(LEG) == U[HELP] and mt(n7).get("mover") == HELP, mt(n7))
    check("8 the rule at the function: the same session by id and name is one only when the caller says so; the same name in any case always is",
          applied({**RELAY, LEG: U[HELP]}, setv={"mover": HELP}).get(LEG) is None and model.settle_picker_keys.__defaults__ is not None, None)
    m_ = dict({**RELAY, LEG: U[HELP], "mover": HELP}); model.settle_picker_keys(m_, {"mover": HELP}, set(), True, True, same=lambda a, b: {a, b} == {U[HELP], HELP})
    check("8 …and with the caller's comparison of ids and names the old key stays", m_.get(LEG) == U[HELP], m_)
    n7 += 1
    item(n7, subject=f"[zed] both, equal {n7}", **{**WAITING_KEYS, LEG: HELP, "mover": BACK})
    upd(n7, mover=HELP)
    check("8 both keys stored with different values, an update sets mover to the old key's session: both name it, the old key stays", mt(n7).get(LEG) == HELP and mt(n7).get("mover") == HELP, mt(n7))
    n7 += 1
    item(n7, subject=f"[zed] then another {n7}", **{**WAITING_KEYS, LEG: HELP})
    upd(n7, mover=HELP); upd(n7, mover=BACK)
    check("8 …and a later write of another mover drops it", stores_mover(mt(n7), BACK), mt(n7))
    check("8 the rule at the function: a mover equal to the old key (any case) leaves it, a different one drops it",
          applied({**RELAY, LEG: HELP}, setv={"mover": HELP}).get(LEG) == HELP and applied({**RELAY, LEG: HELP}, setv={"mover": HELP.upper()}).get(LEG) == HELP and LEG not in applied({**RELAY, LEG: HELP}, setv={"mover": BACK}), None)
    # the migration route, too: a write that sets the mover the old key already names leaves the old key
    guards(True)
    try:
        for n_, sets, label, gone, stored in ((40, {"mover": HELP}, "a set mover equal to the old key leaves it", False, HELP), (41, {"mover": BACK}, "a different one drops it", True, HELP),
                                              (42, {"mover": HELP}, "a set mover that is the old key's session by id leaves it", False, U[HELP])):
            item(n_, subject=f"[zed] migrate {n_}", needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=day(5), **{LEG: stored})
            it_ = rd(n_)
            out = migsvc.migrate_one({"item": f"a{n_}", "set": sets, "drop": [], "expect": it_["updated"], "expect_sig": list(migsvc.migrate_sig(f"a{n_}", it_)), "kind": "test", "note": "t"})
            check(f"8 migration route: {label}", out["action"] in ("set", "already") and ((LEG not in mt(n_)) == gone) and mt(n_).get("mover") == sets["mover"], (out, mt(n_)))
    finally:
        guards(False)

    # ================================================================ 9. a clear leaves the agent the item was handed to as the live mover, for every writer of a wait's picker
    # A wait or a hold never changes who moves the item: clear_wait and clear_hold end the wait and the agent it was handed to stays the mover, never the default mover (the project's builder), whether the picker was stored
    # as `mover` or an old item still stores it under the old key.
    def cleared(n, meta, **kw):
        item(n, subject=f"[zed] clear {n}", **{k: v for k, v in meta.items() if k not in ("next",)})
        SENT.clear(); upd(n, **kw)
        m_ = mt(n); mod_ = model.derive(rd(n), now0)
        return m_, mod_, list(SENT)
    def fixed(n, nxt, **meta):
        clear_g(); gitem(9202, "zed-helper: build the thing"); gitem(n, nxt, **meta); fix_pass(); return mt(n, "g")
    CASES = (("the wait-end fix (after), another session stored as the mover", fixed(9205, f"zed-helper: wait for {ref(9202)} to close, then write the summary", mover=HELP), dict(clear_wait=True), HELP, False),
             ("the wait-end fix (event), another session stored as the mover", fixed(9215, "zed-helper: wait for other/repo#7 to be merged, then write the summary", mover=HELP), dict(clear_wait=True), HELP, True),
             ("the wait-end fix (anchor), another session stored as the mover", fixed(9216, "zed-back: wait for the reply in https://github.com/acme/widgets/issues/5", mover=HELP), dict(clear_wait=True), HELP, True),
             ("a hand-over (a hold with a wake)", hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT}, OWN, HELP, waiting=True), dict(clear_hold=True), HELP, True),
             ("a hand-over (a parked item)", hand({**BASE, "mover": OWN, "then": HELP, "hold": True, "wake": FUT}, OWN, HELP, parked=True), dict(clear_hold=True), HELP, True),
             ("a hand-over (a wait on a date alone)", hand({**BASE, "mover": OWN, "then": HELP, "until": FUT}, OWN, HELP, waiting=True), dict(clear_wait=True), HELP, True),
             ("a hand-over (a wait on a date alone), clear_hold", hand({**BASE, "mover": OWN, "then": HELP, "until": FUT}, OWN, HELP, waiting=True), dict(clear_hold=True), HELP, True),
             ("a restored wait (old snapshot)", restored({"wait_kind": "relay", "wait_event": "the reply", LEG: HELP}, needs=[BACK]), dict(clear_wait=True), HELP, True),
             ("a restored wait (new snapshot)", restored({"wait_kind": "relay", "wait_event": "the reply", "mover": HELP}, needs=[BACK]), dict(clear_wait=True), HELP, True),
             ("an old item that stores the picker under the old key (a relay wait)", {**BASE, "wait_kind": "relay", "wait_event": "the reply", "ask_by": FUT, LEG: HELP}, dict(clear_wait=True), HELP, True),
             ("an old item that stores the picker under the old key (a time wait)", {**BASE, "wait_kind": "time", "hold": True, "wake": FUT, LEG: HELP}, dict(clear_hold=True), HELP, True),
             ("an old item that stores the picker under the old key (a wait on a date alone)", {**BASE, "until": FUT, LEG: HELP}, dict(clear_hold=True), HELP, True),
             ("an old item that stores the picker under the old key (a wait on a date alone), clear_wait", {**BASE, "until": FUT, LEG: HELP}, dict(clear_wait=True), HELP, True))
    n9 = 800
    for label, meta, kw, who, alive in CASES:
        n9 += 1
        clear_g()
        m0 = {k: v for k, v in meta.items() if k not in ("watch",)}
        if label.startswith("the wait-end fix") or label.startswith("a hand-over") or label.startswith("a restored wait"):
            check(f"9 {label}: the picker is stored as `mover`, no old key", stores_mover(m0, who), m0)
        m_, mod_, sent = cleared(n9, m0, **kw)
        op = sorted(kw)[0]
        check(f"9 {label}, {op}: the wait and the old key are gone and {who} stays the mover, not the default mover ({BACK})", m_.get("mover") == who and LEG not in m_ and "wait_kind" not in m_ and not any(k in m_ for k in ("until", "hold", "wake")), m_)
        if alive:
            check(f"9 {label}, {op}: the item reads alive, moved by {who}", mod_.state == "alive" and mod_.mover == who, (mod_.state, mod_.mover))
        else:
            check(f"9 {label}, {op}: the open after link still holds the item, and {who} is its mover", (mod_.wait.mover if mod_.wait else mod_.mover) == who, (mod_.state, mod_.mover))

    return ran, fails


# ================================================================ part picker_one_reader
def part_picker_one_reader():
    tmp, T, U, now0 = _setup("pickerone-", audit=True, home=True)
    item, rd, mt = _store_helpers(T, now0, U)
    check, fails, ran = _checker()
    OLD = now0 - 3 * 3600.0          # last written three hours ago: past the settle window
    logging.disable(logging.INFO)
    from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import model; from stackshot.waits import waiting, watchers as wk
    from stackshot.service import answer as answer_svc
    from stackshot.service import wait_fixes as _wait_fixes_svc
    from stackshot.service import mover_steps as _mover_steps
    from stackshot.waits import handoff as _ho
    from stackshot.audit import audit_run as AR
    from stackshot.core import config as _cfg
    from stackshot.service import store as _service_store
    from stackshot.service import handoff as handoff_svc
    from stackshot.service import migrations as migsvc
    from stackshot.service import watching as watching_svc
    from stackshot.service import wakes as wakes_svc
    from stackshot.service import writes
    from stackshot.service import event_waits as evwaits_svc
    from stackshot.service import telling
    from stackshot.service import wait_gates as wait_gates_svc, released as released_svc
    from stackshot.service import answer_handover as handover_svc
    from stackshot.fleet import liveness as LV
    from stackshot.web import home
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    _web_page_debts._owing_note = lambda debtor: ""
    SENT = []
    telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
    telling.front_sender = lambda who: False
    released_svc._own_repo = lambda: "acme/widgets"
    wait_gates_svc._evwait_preread = lambda kind, phrase: None
    evwaits_svc.evw_boxes = lambda: {}
    LV.puller_online = lambda rec: bool(rec)
    (T / "state").mkdir(parents=True, exist_ok=True); (T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
    CFG = _cfg.CFG.setdefault("model", {}); CFG.update(guards=False, watchers=True, pause=False)
    ZONE_HOURS = 4
    day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
    BACK, HELP, FRONT = "zed-back", "zed-helper", "zed-front"
    OWN = model.owner_display()
    FB = telling.fallback_mover("projects/zedwork")
    assert FB, FB
    FUT = day(5)
    D = lambda **m: model.derive({"status": "open", "metadata": {"project": "projects/zedwork", **m}}, now0)
    def its(**meta): return {"status": "open", "metadata": {"project": "projects/zedwork", **meta}}
    def guards(on):
        CFG["guards"] = on

    # ================================================================ 1. one reader
    # the picker as stored → what every reader says. (legacy key, stored mover) → the picker; "" is no stored picker.
    TABLE = [
        ("legacy key only",                      dict(post_wake_mover=HELP),                       HELP),
        ("mover only",                           dict(mover=HELP),                                 HELP),
        ("both stored and equal",                dict(post_wake_mover=HELP, mover=HELP),           HELP),
        ("both stored and different: the legacy key wins", dict(post_wake_mover=BACK, mover=HELP), BACK),
        ("a legacy key that is he, beside an agent mover", dict(post_wake_mover=OWN, mover=HELP),  OWN),
        ("a mover that is he, beside an agent legacy key", dict(post_wake_mover=HELP, mover=OWN),  HELP),
        ("a mover that is he, no legacy key",    dict(mover=OWN),                                  OWN),
        ("the word none as a mover",             dict(mover="None"),                               ""),
        ("the word none beside a legacy key",    dict(mover="none", post_wake_mover=HELP),         HELP),
        ("neither",                              dict(),                                           ""),
        ("whitespace is collapsed",              dict(mover="  zed-helper  "),                     HELP),
    ]
    for label, st, want in TABLE:
        check(f"1 stored_picker: {label}", model.stored_picker(st) == want, model.stored_picker(st))
    check("1 stored_picker: a missing metadata reads as nothing stored", model.stored_picker({}) == "" and model.stored_picker(None) == "", None)
    check("1 the legacy key's name is one constant", model.LEGACY_PICKER_KEY == "post_wake_mover", model.LEGACY_PICKER_KEY)

    BASE = dict(needs=[BACK], hold=True, wake=FUT, wait_kind="time")
    for label, st, want in TABLE:
        mod = D(**BASE, **st)
        exp = want or BACK        # the default picker when none is stored: the first session in needs
        check(f"1 derive: {label}: the wait's mover is the picker, explicit exactly when one is stored", mod.wait.mover == exp and mod.wait.mover_explicit == bool(want) and mod.picker == exp, mod)
        check(f"1 derive: {label}: the item's own mover stays empty while it waits", mod.mover == "", mod)
        both = st.get("post_wake_mover") and st.get("mover") and model.pick_who(st["mover"]) and model.norm_who(st["post_wake_mover"]) != model.pick_who(st["mover"])
        check(f"1 derive: {label}: one conflict line exactly when both are stored and differ", len(mod.conflicts) == (1 if both else 0), mod.conflicts)
        # the reading of a stored wait the clock has outdated (a view-only wait), read by the same helper
        alive_mod = D(needs=[BACK], **st)
        wm = model._wait_of(its(needs=[BACK], **st), alive_mod, "time")
        check(f"1 view-only wait: {label}", wm.wait.mover == (want or alive_mod.mover) and wm.wait.mover_explicit == bool(want), wm)
        mo = waiting.mover_of({"needs": [], "project": "projects/zedwork", **st})
        exp_mo = (want if want and want != OWN else (model.pick_who(st.get("mover")) if model.pick_who(st.get("mover")) and model.pick_who(st.get("mover")) != OWN else "")) or waiting.fallback_mover("projects/zedwork")
        check(f"1 mover_of: {label}", mo == {"kind": "session", "who": exp_mo}, mo)
        check(f"1 mover_of: {label}: the owner is never returned as a session name", not model.is_owner(mo["who"]), mo)

    # a stored picker the item never names in needs is who holds a waiting item (held_by): the legacy key reads as `then`, a stored mover as `mover`, as before
    item(1, needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP, subject="[zed] a picker by mover")
    item(2, needs=[BACK], hold=True, wake=FUT, wait_kind="time", post_wake_mover=HELP, subject="[zed] a picker by the old name")
    item(3, needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP, post_wake_mover=BACK, subject="[zed] two pickers")
    item(4, needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=OWN, then=HELP, subject="[zed] he picks it up")
    HB = lambda n: telling.held_by(_service_store._load(f"a{n}"))
    check("1 held_by: a picker stored as mover holds the item, worded mover (the notice text does not change)", HB(1) == (HELP, "mover"), HB(1))
    check("1 held_by: …stored under the old name, worded then", HB(2) == (HELP, "then"), HB(2))
    check("1 held_by: …both stored and different: the old name is read first", HB(3) == (BACK, "then"), HB(3))
    check("1 held_by: …he picks it up: the then beside him holds it", HB(4) == (HELP, "then"), HB(4))
    check("1 held_by: the same agent through either key", HB(1)[0] == HB(2)[0] == HELP, (HB(1), HB(2)))

    # the audit's hand-over to the closest live agent follows the stored keys: the legacy key too
    def orphan(**meta):
        it = {"id": "950", "gid": "a950", "subject": "[zed] orphan", "status": "open", "metadata": {"project": "projects/zedwork", "needs": [BACK], **meta}}
        handoff_svc.handoff_write_move(it, _ho.Step("move", "a950", "its holder is gone", frm=BACK, to=HELP, via="orphan"), now0)
        return it["metadata"]
    m_ = orphan(post_wake_mover=BACK, hold=True, wake=FUT, wait_kind="time")
    check("1 orphan keys: the legacy key that named the old holder follows to the new one", m_.get("post_wake_mover") == HELP and m_["needs"][0] == HELP, m_)
    m_ = orphan(mover=BACK, hold=True, wake=FUT, wait_kind="time")
    check("1 orphan keys: …a stored mover that named it follows too, and no legacy key appears", m_.get("mover") == HELP and "post_wake_mover" not in m_, m_)
    m_ = orphan(mover=BACK, then=BACK, post_wake_mover=BACK, hold=True, wake=FUT, wait_kind="time")
    check("1 orphan keys: …all three follow", (m_.get("mover"), m_.get("then"), m_.get("post_wake_mover")) == (HELP, HELP, HELP), m_)

    # a watch.was snapshot: written by older code under the legacy key, by newer code under mover
    check("1 was_picker: an old snapshot (the legacy key)", wk.was_picker({"post_wake_mover": HELP, "wait_kind": "relay"}) == HELP, None)
    check("1 was_picker: …a new one (mover)", wk.was_picker({"mover": HELP, "wait_kind": "relay"}) == HELP, None)
    check("1 was_picker: …both: the legacy key first, as everywhere", wk.was_picker({"post_wake_mover": BACK, "mover": HELP}) == BACK, None)
    check("1 was_picker: …none, or no snapshot, names nobody", wk.was_picker({"mover": "none"}) == "" and wk.was_picker({}) == "" and wk.was_picker(None) == "", None)
    # and the server's read of it: his "arrived" or his words on a relay go to the agent the snapshot names, either form
    for n, was in ((6, {"post_wake_mover": HELP}), (7, {"mover": HELP})):
        key = sorted(was)[0]
        ASKED = dict(needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}],
                     watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), **was}, "at": now0})
        item(n, subject=f"[zed] was {n}", **ASKED)
        m_ = dict(mt(n))
        r = wait_gates_svc._watch_answer(rd(n), m_, {"do": "arrived", "text": "", "date": ""}, now0)
        check(f"1 _watch_answer arrived: a snapshot under {key}: the item goes to the agent it names, alive", m_.get("mover") == HELP and m_.get("needs") == [HELP] and HELP in r, (r, m_))
        item(n + 10, subject=f"[zed] was words {n}", **ASKED)
        m_ = dict(mt(n + 10))
        r = wait_gates_svc._watch_answer(rd(n + 10), m_, {"do": "words", "text": "not yet", "date": ""}, now0)
        check(f"1 _watch_answer words: a snapshot under {key}: the agent it names has the item", m_.get("mover") == HELP and m_.get("needs") == [HELP] and HELP in r, (r, m_))

    # ================================================================ 2. the end of a wait on a date alone
    def fire(n, **meta):
        """an item that waits on a date alone (no wait_kind), the date passed: run the watchers' pass and return what was stored."""
        item(n, needs=[BACK], until=day(-1), **meta)
        SENT.clear(); moved = watching_svc.watch_pass()
        return f"a{n}" in moved, mt(n)
    ok_, m_ = fire(20, mover=HELP)
    check("2 a date-only wait with a stored mover (no legacy key) ends through turn_alive: the mover has it, needs is the mover, then is popped, the arrival is recorded",
          ok_ and m_.get("mover") == HELP and m_.get("needs") == [HELP] and "then" not in m_ and m_.get("woke", {}).get("to") == HELP and "until" not in m_, m_)
    ok_, m_ = fire(21, mover=HELP, then=FRONT)
    check("2 …a then stored beside it goes with the wait, as turn_alive drops it", ok_ and m_.get("mover") == HELP and "then" not in m_, m_)
    ok_, m_ = fire(22)
    check("2 a date-only wait with nothing stored ends through end_date: needs stays as stored, the arrival is recorded, no mover is written",
          ok_ and m_.get("needs") == [BACK] and "mover" not in m_ and m_.get("woke", {}).get("to") == BACK and "until" not in m_, m_)
    ok_, m_ = fire(23, post_wake_mover=HELP)
    check("2 a date-only wait with the legacy key ends through turn_alive: the agent has it, the legacy key is gone", ok_ and m_.get("mover") == HELP and m_.get("needs") == [HELP] and "post_wake_mover" not in m_, m_)
    ok_, m_ = fire(24, mover="none")
    check("2 …the word none as a mover is no stored picker: end_date, needs stays", ok_ and m_.get("needs") == [BACK] and m_.get("mover") == "none", m_)
    ok_, m_ = fire(25, mover=OWN, then=HELP)
    check("2 a date-only wait he picks up turns to him with his ask, the then kept beside him (unchanged)", ok_ and m_.get("needs") == ["decision"] and m_.get("then") == HELP and "mover" not in m_, m_)
    item(26, needs=[BACK], wait_kind="time", wake=day(-1), mover=HELP, hold=True)
    moved = watching_svc.watch_pass()
    check("2 a wait with a kind and a stored mover still ends through turn_alive (unchanged)", "a26" in moved and mt(26).get("needs") == [HELP] and mt(26).get("mover") == HELP, mt(26))

    # the end of a wait on a date alone, by what the item stores and whether `external` is in its needs. With external the item goes back to others at its date, as it always did: only the old key turns it
    # (turn_alive); a stored mover alone ends it on the date (end_date, needs as stored). Without external a picker under either key turns it. Two forms of the date: until, and a hold with a wake.
    PICKERS = (("legacy key", dict(post_wake_mover=HELP), True, True), ("stored mover only", dict(mover=HELP), True, False), ("both", dict(post_wake_mover=HELP, mover=HELP), True, True), ("neither", dict(), False, False))
    NUM = 200
    for ext_, needs_ in ((True, ["external"]), (False, [BACK])):
        for plabel, st, has_any, has_legacy in PICKERS:
            for dlabel, date in (("until", dict(until=day(-1))), ("wake", dict(hold=True, wake=day(-1)))):
                NUM += 1
                item(NUM, needs=list(needs_), **date, **st)
                SENT.clear(); moved = watching_svc.watch_pass() if dlabel == "until" else wakes_svc.wake_pass(); m_ = mt(NUM)      # a stored until is the watchers' pass; a hold with a wake is the wake pass's
                turns = has_legacy if ext_ else has_any          # main's result for external; the new rule (a stored mover turns it too) only without external
                want_needs = [HELP] if turns else list(needs_)
                if dlabel == "until":
                    check(f"2 external={ext_}, {plabel}, a kind-less until: {'turns to the picker (needs is the picker)' if turns else 'ends on the date (needs stays as stored)'}",
                          f"a{NUM}" in moved and m_.get("needs") == want_needs and "woke" in m_ and "until" not in m_ and "post_wake_mover" not in m_
                          and (m_.get("mover") == HELP if turns else m_.get("mover") == st.get("mover")), m_)
                else:      # a hold with a wake and no kind is the wake pass's (no watcher owns it): the hold and wake go, and needs and the stored picker keys stay exactly as stored, on main and here
                    check(f"2 external={ext_}, {plabel}, a kind-less hold with a wake: released by the wake pass, needs and the stored keys as stored",
                          f"a{NUM}" in moved and m_.get("needs") == list(needs_) and "hold" not in m_ and "wake" not in m_ and m_.get("post_wake_mover") == st.get("post_wake_mover") and m_.get("mover") == st.get("mover"), m_)
    check("2 _ends_on_the_date: a wait with a kind never ends on the date; a missing needs reads as no external",
          not watching_svc._ends_on_the_date({"wait_kind": "time"}, D(needs=[BACK], hold=True, wake=FUT, wait_kind="time")) and watching_svc._ends_on_the_date({}, D(hold=True, wake=FUT)), None)

    # ================================================================ 3. settle
    WAITING_HIS = lambda **m: its(mover=OWN, until=FUT, **m)
    check("3 settle: the waiting branch is off by default: a waiting item that stood his keeps its stored mover=he (mover only)", model.settle(WAITING_HIS(needs=[BACK]), True) is None, None)
    check("3 settle: …also with an agent in then", model.settle(WAITING_HIS(needs=[BACK], then=BACK), True) is None, None)
    check("3 settle: …and with a legacy key stored the mover is left, and only the then goes (an agent is the picker: the then stands beside no one)", model.settle(WAITING_HIS(needs=[BACK], then=BACK, post_wake_mover=HELP), True) == {"then": ""}, None)
    check("3 settle: waiting=True, an agent in then: it picks the item up, then goes", model.settle(WAITING_HIS(needs=[BACK], then=BACK), True, waiting=True) == {"mover": BACK, "then": ""}, None)
    check("3 settle: waiting=True, no agent in then: only the mover goes", model.settle(WAITING_HIS(needs=[BACK]), True, waiting=True) == {"mover": ""}, None)
    check("3 settle: waiting=True, a legacy key stored: the mover goes, and the then with it", model.settle(WAITING_HIS(needs=[BACK], then=BACK, post_wake_mover=HELP), True, waiting=True) == {"mover": "", "then": ""}, None)
    check("3 settle: waiting=True still needs the proof that it stood his, and leaves an agent's stored mover alone", model.settle(WAITING_HIS(needs=[BACK], then=BACK), False, waiting=True) is None
          and model.settle(its(mover=HELP, needs=[BACK], until=FUT), True, waiting=True) is None, None)
    # the alive branches are as they were, with the parameter either way
    for w_ in (False, True):
        check(f"3 settle alive (waiting={w_}): an agent mover on an item in his state becomes he, the agent in then", model.settle(its(mover=BACK, needs=["decision"], ask="Decide: x"), False, waiting=w_) == {"mover": OWN, "then": BACK}, None)
        check(f"3 settle alive (waiting={w_}): the hand-back: he as mover on an agent's item that stood his: the agent in then is the mover, then goes", model.settle(its(mover=OWN, then=BACK, needs=[BACK]), True, waiting=w_) == {"mover": BACK, "then": ""}, None)
        check(f"3 settle alive (waiting={w_}): …with no agent in then only the mover goes", model.settle(its(mover=OWN, needs=[BACK]), True, waiting=w_) == {"mover": ""}, None)
        check(f"3 settle alive (waiting={w_}): …and with no proof it stood his nothing changes", model.settle(its(mover=OWN, then=BACK, needs=[BACK]), False, waiting=w_) is None, None)

    # the on-save backstop: an item that stood his is saved as a waiting one with his stored mover: it is left alone
    guards(True)
    try:
        before = its(needs=["decision"], mover=OWN, then=BACK, ask="Decide: x")
        after_ = its(needs=[BACK], mover=OWN, then=BACK, until=FUT)
        check("3 _settle_mover_on_save: a waiting item that stood his keeps its stored mover and then (nothing settled)", _mover_steps._settle_mover_on_save(after_, before) is False and after_["metadata"]["mover"] == OWN and after_["metadata"]["then"] == BACK, after_)
        alive_ = its(needs=[BACK], mover=OWN, then=BACK)
        check("3 _settle_mover_on_save: …an alive agent's item still hands back as before", _mover_steps._settle_mover_on_save(alive_, before) is True and alive_["metadata"].get("mover") == BACK and "then" not in alive_["metadata"], alive_)
        inhis = its(needs=["decision"], mover=BACK, ask="Decide: x")
        check("3 _settle_mover_on_save: …and an agent mover on his item still becomes he", _mover_steps._settle_mover_on_save(inhis, None) is True and inhis["metadata"]["mover"] == OWN and inhis["metadata"]["then"] == BACK, inhis)
        # the real save path
        item(30, needs=[BACK], mover=BACK)
        it_ = _service_store._load("a30"); it_["metadata"]["needs"] = ["decision", BACK]; it_["metadata"]["ask"] = "Decide: x"
        writes.save("a30", it_)
        check("3 writes.save: (probe) his state makes him the mover, the agent in then", mt(30).get("mover") == OWN and mt(30).get("then") == BACK, mt(30))
        it_ = _service_store._load("a30"); it_["metadata"].update(needs=[BACK], until=FUT); it_["metadata"].pop("ask", None)
        writes.save("a30", it_)
        check("3 writes.save: a save where a wait replaces his state leaves his stored mover and then (he picks it up when the wait ends)", mt(30).get("mover") == OWN and mt(30).get("then") == BACK, mt(30))
        # the start repair
        AN = [{"ts": now0 - 3600, "text": "ok", "choice": "Approve"}]
        item(31, needs=[BACK], mover=OWN, then=BACK, until=FUT, answers=AN, subject="[zed] waiting, his stored mover")
        item(32, needs=[BACK], mover=OWN, then=BACK, answers=AN, subject="[zed] alive, his stale mover")
        before31 = (T / "store/a/31.json").read_bytes()
        done = migsvc.migrate_owner_mover()
        check("3 the start repair: a waiting item's stored mover=he is left byte for byte", (T / "store/a/31.json").read_bytes() == before31 and "a31" not in done, (done, mt(31)))
        check("3 the start repair: …an alive agent's item with his stale mover is still handed back", "a32" in done and mt(32).get("mover") == BACK and "then" not in mt(32), (done, mt(32)))
    finally:
        guards(False)

    # ================================================================ 4. the writers: each ends with no stray stored mover
    # the update path: a write that leaves an item that stood his as a waiting one and names no mover (_owner_state_mover → settle(waiting=True))
    guards(True)
    try:
        was_ = {"id": "40", "status": "open", "metadata": {"project": "projects/zedwork", "needs": ["decision"], "mover": OWN, "then": BACK, "ask": "Decide: x"}}
        now_ = {"id": "40", "status": "open", "metadata": {"project": "projects/zedwork", "needs": [BACK], "mover": OWN, "then": BACK, "until": FUT}}
        meta_ = dict(now_["metadata"])
        note = _mover_steps._owner_state_mover({**now_, "metadata": meta_}, meta_, False, was_)
        check("4 update path: the stale mover=he is replaced by the agent in then, then goes, and the model reads the agent as the picker", meta_.get("mover") == BACK and "then" not in meta_ and "mover" in note
              and model.derive({**now_, "metadata": meta_}).wait.mover == BACK, (meta_, note))
        meta_ = {**now_["metadata"], "post_wake_mover": HELP}
        _mover_steps._owner_state_mover({**now_, "metadata": meta_}, meta_, False, was_)
        check("4 update path: …with the legacy key stored, the mover goes and the then with it (an agent is the picker)", "mover" not in meta_ and meta_.get("post_wake_mover") == HELP and "then" not in meta_, meta_)
        meta_ = dict(now_["metadata"])
        note = _mover_steps._owner_state_mover({**now_, "metadata": meta_}, meta_, True, was_)
        check("4 update path: a write that names a mover itself is left alone (named)", note == "" and meta_["mover"] == OWN and meta_["then"] == BACK, (meta_, note))
        meta_ = {k: v for k, v in now_["metadata"].items() if k != "then"}
        _mover_steps._owner_state_mover({**now_, "metadata": meta_}, meta_, False, was_)
        check("4 update path: …no agent in then: only the mover goes", "mover" not in meta_, meta_)
    finally:
        guards(False)

    # a decision's hand-over: his answer on an item that now waits (a park, a pick carrying a wake) pops the mover itself
    for label, kw in (("waiting", dict(waiting=True)), ("parked", dict(parked=True))):
        meta_ = {"project": "projects/zedwork", "needs": [BACK], "mover": OWN, "then": BACK, "hold": True, "wake": FUT, "wait_kind": "time"}
        handover_svc._decision_hand_over(meta_, OWN, BACK, now=now0, **kw)
        check(f"4 _decision_hand_over ({label}): no stored mover=he is left, and the item reads as waiting with an agent picker", "mover" not in meta_ and model.derive(its(**meta_), now0).state == "waiting", meta_)
    meta_ = {"project": "projects/zedwork", "needs": [BACK], "mover": OWN, "then": OWN, "until": FUT}
    handover_svc._decision_hand_over(meta_, OWN, OWN, waiting=True, now=now0)
    check("4 _decision_hand_over: …he as then too: both go", "mover" not in meta_ and "then" not in meta_, meta_)
    meta_ = {"project": "projects/zedwork", "needs": [BACK], "mover": OWN, "then": BACK, "until": FUT}
    handover_svc._decision_hand_over(meta_, OWN, BACK, waiting=True, now=now0)
    check("4 _decision_hand_over: a date-only wait with an agent in then stores the picker (stored as mover)", meta_.get("mover") == BACK and "post_wake_mover" not in meta_ and "then" not in meta_, meta_)

    # the watchers' turn to him: a wait that ends on a question to him leaves no stored mover (he is the mover by needs=decision), the agent that picks it up after is `then`
    meta_ = {"project": "projects/zedwork", "needs": [BACK], "mover": HELP, "wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1)}
    wk.turn_to_owner(meta_, HELP, "Did it arrive?", [{"label": "Arrived"}], "it is due", now0)
    check("4 turn_to_owner: the stored mover goes, the picker is the then beside him, needs is decision alone", "mover" not in meta_ and meta_.get("then") == HELP and meta_.get("needs") == ["decision"], meta_)

    # the board answer: a watcher ask answered "not yet" puts the wait back with its picker (no stray mover=he), "arrived" gives the item to the picker
    item(41, needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}], subject="[zed] relay answered",
         watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), "mover": HELP}, "at": now0}, then=HELP, mover=OWN)
    m_ = dict(mt(41))
    r = wait_gates_svc._watch_answer(rd(41), m_, {"do": "wait", "text": "", "date": day(9)}, now0)
    check("4 _watch_answer (not yet): the wait is back with its own picker as mover, then goes, no stray mover=he", m_.get("mover") == HELP and "then" not in m_ and m_.get("ask_by") == day(9) and "waits again" in r, (r, m_))
    item(42, needs=["decision"], ask="Did it arrive?", options=[{"label": "Arrived"}], subject="[zed] relay arrived", then=HELP, mover=OWN,
         watch={"asked": "relay", "was": {"wait_kind": "relay", "wait_event": "the reply", "ask_by": day(-1), "post_wake_mover": HELP}, "at": now0})
    m_ = dict(mt(42))
    r = wait_gates_svc._watch_answer(rd(42), m_, {"do": "arrived", "text": "", "date": ""}, now0)
    check("4 _watch_answer (arrived): the agent has it, alive, no stray mover=he", m_.get("mover") == HELP and m_.get("needs") == [HELP], (r, m_))
    # a decision item parked by his answer through the board's own entry
    item(43, needs=["decision"], mover=OWN, then=BACK, ask="Decide: whether to go ahead \u00b7 Recommend: go \u00b7 Stakes: a day either way \u00b7 By: no date",
         options=[{"label": "Approve", "line": "Go ahead as proposed", "recommended": True}, {"label": "Decline", "line": "Do not go ahead", "recommended": False}],
         hold=True, wake=day(30), hold_set={"by": "t", "at": now0}, subject="[zed] a decision on a parked item")
    r = answer_svc._answer("a43", "Approve", "", "")
    check("4 the board's answer on a parked decision: the stored mover=he does not survive his answer, the agent in then is the picker through the wait", r == "decision" and mt(43).get("mover") == BACK and "post_wake_mover" not in mt(43) and "decision" not in (mt(43).get("needs") or [])
          and model.derive(rd(43), now0).state == "waiting" and model.derive(rd(43), now0).wait.mover == BACK, (r, mt(43)))

    # the wait-end fix: a step in words that waits for another item gets its wait stored with the mover as the picker, never a mover=he
    for p in (T / "store/g").glob("*.json"): p.unlink()
    ROLES = {BACK: {"role": "background"}, HELP: {"role": "background"}, FRONT: {"role": "front"}}
    def env(**kw): return AR.Env(roles=ROLES, fallback=lambda p: FRONT, builder=lambda p: BACK, page_of=lambda p: ("", None), deliver=lambda to, text, fyi=False: (True, "[200] ok"), sessions=lambda: None,
                                 pages=lambda run, deadline: {"enabled": False, "mode": "", "counts": {}}, **kw)
    def gitem(i, nxt, **meta):
        (T / f"store/g/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[zed] item {i}", "description": DESC, "status": "open", "updated": OLD, "written_at": OLD, "written_by": BACK,
                                                        "state_updated": OLD, "confirmed": OLD,
                                                        "metadata": {"owner": U[FRONT], "project": "projects/zedwork", "state": "doing", "needs": [BACK], "next": nxt, **meta}}))
    gitem(9202, "zed-helper: build the thing")
    gitem(9201, "zed-back: wait for board#" "9202 to close, then write the summary")
    (T / "state/audit").mkdir(parents=True, exist_ok=True)
    items_ = {f"g{p.stem}": json.loads(p.read_text()) for p in (T / "store/g").glob("*.json")}
    r = AR.filing_pass(now=now0, items=items_, anchors={}, env=env(wait_end=_wait_fixes_svc._wait_end_fix, wait_facts=_wait_fixes_svc._wait_end_facts))
    m_ = mt(9201, "g")
    check("4 _wait_end_fix: the wait is stored with the mover as the picker and no stored mover=he; the model reads it as waiting on the agent",
          m_.get("after") == ["g9202"] and m_.get("mover") == BACK and "post_wake_mover" not in m_ and model.derive(rd(9201, "g"), now0).state == "waiting" and model.derive(rd(9201, "g"), now0).wait.mover == BACK, (m_, r.get("wait_end")))

    # ================================================================ 5. the phase reads
    PH = [
        ("until set, mover he",                 dict(until=FUT, mover=OWN, needs=[BACK]),                      home.WAITING),
        ("until set, an agent's picker",        dict(until=FUT, mover=HELP, needs=[BACK]),                     home.WAITING),
        ("legacy key, until set",               dict(until=FUT, post_wake_mover=HELP, needs=[BACK]),           home.WAITING),
        ("a wait with a kind and mover he",     dict(hold=True, wake=FUT, wait_kind="time", mover=OWN, needs=[BACK]), home.WAITING),
        ("alive, mover he",                     dict(mover=OWN, needs=[BACK]),                                 home.YOUR_MOVE),
        ("alive, needs decision",               dict(needs=["decision"], ask="Decide: x"),                     home.YOUR_MOVE),
        ("alive, an agent",                     dict(mover=HELP, needs=[HELP]),                                home.AGENTS),
        ("alive, nothing stored",               dict(needs=[BACK]),                                            home.AGENTS),
    ]
    for label, st, want in PH:
        got = home.list_of(D(**st))
        check(f"5 phase: {label}: {want}", got == want, got)

    return ran, fails


# ================================================================ part mover_picker
def part_mover_picker():
    tmp, T, U, now0 = _setup("moverpicker-", audit=False, home=False)
    item, rd, mt = _store_helpers(T, now0, U)
    check, fails, ran = _checker()
    logging.disable(logging.INFO)
    from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import model; from stackshot.waits import waiting, watchers as wk; from stackshot.web import render
    from stackshot.service import answer as answer_svc
    from stackshot.service import client_reads as client_reads_svc
    from stackshot.service import item_read as _item_read
    from stackshot.core import config as _cfg
    from stackshot.service import store as _service_store
    from stackshot.web import publish as _web_publish
    from stackshot.web import page_debts as _web_page_debts
    from stackshot.service import watching as watching_svc
    from stackshot.web.tools import get as _wt_get
    from stackshot.service import telling
    from stackshot.web.ui import render as ui_render
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
    _web_page_debts._owing_note = lambda debtor: ""
    SENT = []
    telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
    (T / "state").mkdir(parents=True, exist_ok=True); (T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
    CFG = _cfg.CFG.setdefault("model", {}); CFG.update(guards=False, watchers=True, pause=False)
    ZONE_HOURS = 4
    day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
    BACK, HELP, FRONT = "zed-back", "zed-helper", "zed-front"
    OWN = model.owner_display()
    FB = telling.fallback_mover("projects/zedwork")
    assert FB, FB
    D = lambda **m: model.derive({"status": "open", "metadata": {"project": "projects/zedwork", **m}}, now0)
    W_ = lambda mod: model.words(mod)
    FUT = day(5)

    # ================================================================ derive: the picker
    m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP)
    check("picker: a stored mover on a waiting item is who picks it up; it is explicit, no conflict is named, and the item's own mover stays empty while it waits",
          m_.state == "waiting" and m_.wait.mover == HELP and m_.wait.mover_explicit and m_.picker == HELP and m_.mover == "" and not m_.conflicts, m_)
    m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", post_wake_mover=HELP)
    check("picker: …the old name post_wake_mover is read when no mover is stored, and is explicit too", m_.wait.mover == HELP and m_.wait.mover_explicit and m_.wait.post_wake_mover == HELP and m_.picker == HELP and not m_.conflicts, m_)
    m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP, post_wake_mover=HELP)
    check("picker: …both stored and equal: no conflict", m_.wait.mover == HELP and not m_.conflicts, m_)
    m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP, post_wake_mover=BACK)
    check("picker: …both stored and different: the old name wins while it is stored, and one conflict line says so", m_.wait.mover == BACK and m_.picker == BACK and len(m_.conflicts) == 1 and "mover=zed-helper" in m_.conflicts[0] and "post_wake_mover=zed-back" in m_.conflicts[0] and "post_wake_mover picks it up" in m_.conflicts[0], m_.conflicts)
    m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=BACK, post_wake_mover=OWN, then=HELP)
    check("picker: …a stored post_wake_mover that is he beats a stored agent mover, and his then stands (the case main reads the same way)", m_.wait.mover == OWN and m_.then == HELP and len(m_.conflicts) == 1, m_)
    m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=OWN, post_wake_mover=HELP, then=BACK)
    check("picker: …a stored agent post_wake_mover beats a stored mover that is he, and no then stands", m_.wait.mover == HELP and m_.then == "" and m_.picker == HELP, m_)
    m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover="none")
    check("picker: the literal word none stored as a mover is no picker: the default takes it, not explicit, no conflict", m_.wait.mover == BACK and not m_.wait.mover_explicit and not m_.conflicts, m_)
    m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover="None", post_wake_mover=HELP)
    check("picker: …nor does it conflict with a stored post_wake_mover, which is the picker", m_.wait.mover == HELP and not m_.conflicts, m_)
    check("waiting.mover_of agrees with the picker: an agent post_wake_mover beats a stored mover, and an owner one is skipped for the mover", waiting.mover_of({"needs": [], "mover": BACK, "post_wake_mover": HELP})["who"] == HELP and waiting.mover_of({"needs": [], "mover": HELP, "post_wake_mover": OWN})["who"] == HELP, waiting.mover_of({"needs": [], "mover": BACK, "post_wake_mover": HELP}))
    m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time")
    check("picker: …neither stored: the default (the first session in needs), not explicit", m_.wait.mover == BACK and not m_.wait.mover_explicit and not m_.conflicts, m_)
    m_ = D(hold=True, wake=FUT, wait_kind="time")
    check("picker: …neither stored and no session in needs: the project's builder or -main agent", m_.wait.mover == FB and not m_.wait.mover_explicit, m_)
    m_ = D(needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=FUT)
    check("picker: a relay with nothing stored: the owner (the ask-by day turns the item to him)", m_.wait.mover == OWN and not m_.wait.mover_explicit, m_)
    m_ = D(needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=FUT, mover=HELP)
    check("picker: …a relay with a stored mover: that agent picks it up after his answer", m_.wait.mover == HELP and m_.wait.mover_explicit, m_)
    m_ = D(needs=[BACK], mover=HELP)
    check("picker: an alive item: the picker is the mover (an agent), or `then` while the owner moves it", m_.picker == HELP and D(needs=["decision"], ask="Decide: x", then=BACK).picker == BACK, m_)
    check("picker: next_mover reads the same", D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP).next_mover == HELP, None)

    # ================================================================ `then` stands only beside the owner
    m_ = D(needs=["decision"], ask="Decide: x", then=BACK)
    check("then: an alive item the owner moves reads its stored then", m_.mover == OWN and m_.then == BACK and m_.then_explicit and not m_.conflicts, m_)
    m_ = D(needs=[BACK], mover=HELP, then=BACK)
    check("then: …an alive item an agent moves reads none (a stored one is not read), and no conflict is named", m_.mover == HELP and m_.then == "" and not m_.then_explicit and not m_.conflicts, m_)
    m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=OWN, then=BACK)
    check("then: a waiting item he picks up reads its stored then", m_.wait.mover == OWN and m_.then == BACK and m_.then_explicit and m_.picker == OWN, m_)
    m_ = D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP, then=BACK)
    check("then: …a waiting item an agent picks up reads none", m_.wait.mover == HELP and m_.then == "" and not m_.conflicts, m_)
    m_ = D(needs=[BACK], wait_kind="relay", wait_event="the reply", ask_by=FUT, then=HELP)
    check("then: …a relay (he is the default picker) reads its then", m_.wait.mover == OWN and m_.then == HELP, m_)

    # ================================================================ words
    check("words: a waiting item says who picks it up as its mover", W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP)) == f"model: waiting on a time (wake {FUT}) · mover zed-helper", W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=HELP)))
    check("words: …he picks it up, with the then beside him", W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=OWN, then=BACK)) == f"model: waiting on a time (wake {FUT}) · mover {OWN} (then zed-back)", W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=OWN, then=BACK)))
    check("words: …a mover the item does not store is named in the derived tail", W_(D(needs=[BACK], hold=True, wake=FUT)).endswith("· derived: wait_kind, mover") and "derived" not in W_(D(needs=[BACK], hold=True, wake=FUT, wait_kind="time", mover=BACK)), W_(D(needs=[BACK], hold=True, wake=FUT)))
    check("words: an alive item an agent moves shows no then", W_(D(needs=[BACK], mover=HELP, then=BACK)) == "model: alive · mover zed-helper", W_(D(needs=[BACK], mover=HELP, then=BACK)))

    # ================================================================ settle
    def S(meta, was_his=True, waiting=True): return model.settle({"status": "open", "metadata": {"project": "projects/zedwork", **meta}}, was_his, waiting=waiting)      # a waiting item settles only from the update path (waiting=True)
    check("settle: a wait replaces his state (mover him, an agent in then): the agent picks it up, then goes", S({"mover": OWN, "then": BACK, "hold": True, "wake": FUT, "wait_kind": "time"}) == {"mover": BACK, "then": ""}, S({"mover": OWN, "then": BACK, "hold": True, "wake": FUT, "wait_kind": "time"}))
    check("settle: …with no agent in then only the stale mover goes", S({"mover": OWN, "hold": True, "wake": FUT, "wait_kind": "time"}) == {"mover": ""}, None)
    check("settle: …a post_wake_mover stored beside his mover and an agent in then: the mover goes, and so does the then (an agent picks the item up, so the then stands beside no one); the old name stays as stored",
          S({"mover": OWN, "then": BACK, "post_wake_mover": HELP, "hold": True, "wake": FUT, "wait_kind": "time"}) == {"mover": "", "then": ""}, S({"mover": OWN, "then": BACK, "post_wake_mover": HELP, "hold": True, "wake": FUT, "wait_kind": "time"}))
    check("settle: …a stored agent mover on a waiting item is never dropped", S({"mover": HELP, "needs": [BACK], "hold": True, "wake": FUT, "wait_kind": "time"}) is None and S({"mover": HELP, "needs": [BACK], "hold": True, "wake": FUT, "wait_kind": "time"}, False) is None, None)
    check("settle: …nor a mover he stored on a waiting item that never stood in his state", S({"mover": OWN, "then": BACK, "hold": True, "wake": FUT, "wait_kind": "time"}, False) is None, None)

    # ================================================================ the server's readers
    item(1, needs=[BACK], hold=True, wake=day(5), wait_kind="time", mover=HELP, subject="[zed] a picker by mover")
    item(2, needs=[BACK], hold=True, wake=day(5), wait_kind="time", post_wake_mover=HELP, subject="[zed] a picker by the old name")
    item(3, needs=[BACK], hold=True, wake=day(5), wait_kind="time", mover=OWN, then=HELP, subject="[zed] he picks it up")
    item(4, needs=[BACK], hold=True, wake=day(5), wait_kind="time", mover=HELP, post_wake_mover=BACK, subject="[zed] two pickers")
    item(5, needs=[BACK], mover=HELP, then=BACK, subject="[zed] an agent moves it, with a then")
    L = lambda n: _wt_get.stackshot_get(f"a{n}").split("\n")
    check("held_by: the picker holds a waiting item, as its mover when it is stored under that name", telling.held_by(_service_store._load("a1")) == (HELP, "mover"), telling.held_by(_service_store._load("a1")))
    check("held_by: …under the old name it reads as before, the word then", telling.held_by(_service_store._load("a2")) == (HELP, "then"), telling.held_by(_service_store._load("a2")))
    check("held_by: …when he picks it up, the then beside him holds it", telling.held_by(_service_store._load("a3")) == (HELP, "then"), telling.held_by(_service_store._load("a3")))
    check("held_by: …both stored and different, the old name is read first, as the hand-over writers read it", telling.held_by(_service_store._load("a4")) == (BACK, "then"), telling.held_by(_service_store._load("a4")))
    check("held_by: an alive item an agent moves is held by its mover", telling.held_by(_service_store._load("a5")) == (HELP, "mover"), telling.held_by(_service_store._load("a5")))
    g1, g3, g4, g5 = L(1), L(3), L(4), L(5)
    check("get: a waiting item shows who picks it up as its mover, and no then line", "mover: zed-helper (picks it up when the wait ends)" in g1 and not any(x.startswith("then:") for x in g1), g1[:6])
    check("get: …with the owner as picker, the then is shown", f"mover: {OWN} (picks it up when the wait ends)" in g3 and "then: zed-helper" in g3, g3[:6])
    check("get: …the model line says so, and no model-conflict line is printed for a mover on a waiting item", any(x.startswith("model: waiting") and x.endswith("· mover zed-helper") for x in g1) and not any("model conflict" in x for x in g1), g1)
    check("get: …two different pickers stored: one conflict line", sum("model conflict" in x for x in g4) == 1, g4)
    check("get: an alive item an agent moves shows no then line and no conflict", "mover: zed-helper" in g5 and not any(x.startswith("then:") for x in g5) and not any("model conflict" in x for x in g5), g5)
    check("roles: a waiting item's picker has the role then; with him as picker, the then beside him", client_reads_svc._then_label_raw({**rd(1), "gid": "a1"}) == HELP and client_reads_svc._then_label_raw({**rd(3), "gid": "a3"}) == HELP and client_reads_svc._then_label_raw({**rd(5), "gid": "a5"}) == "", None)
    check("then label: the notice's then names the picker of a waiting item", telling.then_label({**rd(1), "gid": "a1"}) != "" and telling.then_label({**rd(5), "gid": "a5"}) == "", None)

    # ================================================================ the renderer's who line
    strip = lambda s: re.sub(r"<[^>]+>", "", s)
    bd = ui_render.Board(str(T / "store"), now=datetime.datetime.now(datetime.timezone.utc))
    r_ = {"gid": "a1", "metadata": {}}
    mk = lambda **kw: model.Model(model.WAITING, then=kw.pop("then", ""), wait=model.Wait(kind="time", kind_explicit=True, until=FUT, **kw))
    check("who line: an agent picks it up", strip(bd.wait_who(r_, mk(mover=HELP))) == "zed-helper picks it up · watched by the scheduler", strip(bd.wait_who(r_, mk(mover=HELP))))
    check("who line: the owner picks it up, with the then", strip(bd.wait_who(r_, mk(mover=OWN, then=BACK))) == f"{OWN}, then zed-back · watched by the scheduler", strip(bd.wait_who(r_, mk(mover=OWN, then=BACK))))
    check("who line: …the owner alone", strip(bd.wait_who(r_, mk(mover=OWN))).startswith(f"{OWN} picks it up"), strip(bd.wait_who(r_, mk(mover=OWN))))
    check("who line: nobody", strip(bd.wait_who(r_, mk(mover=""))).startswith("nobody set to pick it up"), strip(bd.wait_who(r_, mk(mover=""))))

    # ================================================================ the watchers
    # a wake the owner picks up keeps the then stored beside him
    item(10, needs=[BACK], hold=True, wake=day(-1), wait_kind="time", mover=OWN, then=HELP, subject="[zed] he picks it up after the wake")
    item(11, needs=[BACK], hold=True, wake=day(-1), wait_kind="time", mover=HELP, subject="[zed] an agent picks it up after the wake")
    SENT.clear(); moved = watching_svc.watch_pass()
    m = mt(10)
    check("watch fire: a time wait the owner picks up turns to him and keeps the then stored beside it", "a10" in moved and m.get("needs") == ["decision"] and m.get("then") == HELP and "mover" not in m and "wait_kind" not in m, m)
    m = mt(11)
    check("watch fire: …one an agent picks up turns alive with him as mover", "a11" in moved and m.get("mover") == HELP and m.get("needs") == [HELP] and "then" not in m, m)

    # a relay: the agent stored as its mover picks it up after his answer; "not yet" keeps the wait's picker
    item(20, wait_kind="relay", wait_event="the parcel", ask_by=day(-1), mover=HELP, needs=[], subject="[zed] relay with a mover")
    item(21, wait_kind="relay", wait_event="the quote", ask_by=day(-1), post_wake_mover=HELP, needs=[], subject="[zed] relay with the old name")
    SENT.clear(); moved = watching_svc.watch_pass()
    m = mt(20)
    check("relay fire: the question goes to him with the picker as then; the record of the wait keeps the mover", "a20" in moved and m.get("needs") == ["decision"] and m.get("then") == HELP and m["watch"]["was"].get("mover") == HELP, m)
    m = mt(21)
    check("relay fire: …a wait stored under the old name records its picker as mover", "a21" in moved and m["watch"]["was"].get("mover") == HELP and "post_wake_mover" not in m["watch"]["was"] and m.get("then") == HELP, m)
    answer_svc._answer("a20", "not yet, ask again on <date>", f"ask again on {day(9)}", "answer")
    m = mt(20)
    check("relay not yet: the wait is back on the date he gave with its picker kept as the mover", m.get("wait_kind") == "relay" and m.get("ask_by") == day(9) and m.get("mover") == HELP and "then" not in m and "ask" not in m, m)
    check("relay not yet: …and the model reads the picker", _item_read._model_of({**rd(20), "gid": "a20"}).wait.mover == HELP and _item_read._model_of({**rd(20), "gid": "a20"}).mover == "", None)
    SENT.clear(); answer_svc._answer("a21", "arrived", "", "answer")
    m = mt(21)
    check("relay arrived: a record of the wait under the old name is still read: the item goes to that agent", m.get("mover") == HELP and m.get("needs") == [HELP] and "ask" not in m, m)
    item(22, wait_kind="relay", wait_event="the contract", ask_by=day(-1), mover=BACK, needs=[], subject="[zed] relay, arrived")
    watching_svc.watch_pass(); SENT.clear(); answer_svc._answer("a22", "arrived", "", "answer")
    m = mt(22)
    check("relay arrived: …and one stored under mover goes to the mover", m.get("mover") == BACK and m.get("needs") == [BACK], m)
    check("fields: a record of the wait remembers the mover and the then", "mover" in wk.WAS_FIELDS and "then" in wk.WAS_FIELDS and "post_wake_mover" in wk.WAS_FIELDS, wk.WAS_FIELDS)

    return ran, fails


PARTS = {"mover_writers": (part_mover_writers, "mover writers"), "picker_one_reader": (part_picker_one_reader, "picker one reader"), "mover_picker": (part_mover_picker, "mover picker")}


def _run_part(name):
    fn, label = PARTS[name]; code = 1
    try:
        ran, fails = fn()
        print(("ok" if not fails else "FAILED") + f": {label} scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
        code = 1 if fails else 0
    finally:      # the folder goes whatever happened (a failing check, an exception); _scratch removes it at exit as well
        for d in _made: shutil.rmtree(d, ignore_errors=True)
    os._exit(code)      # as the suites always ended: nothing a thread of the part left behind holds the process


def _run_all():
    total = 0; failed = []
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], capture_output=True, text=True, timeout=1500)
        sys.stdout.write(r.stdout); sys.stdout.flush(); sys.stderr.write(r.stderr); sys.stderr.flush()
        m = re.search(r"^(ok|FAILED): .*? scenario, (\d+) checks", r.stdout, re.M)
        if m: total += int(m.group(2))
        if r.returncode != 0 or not m or m.group(1) != "ok":
            failed.append(name); print(f"FAIL part {name}: exit {r.returncode}, summary {m.group(0) if m else 'missing'}" + (f"\n{r.stderr[-600:]}" if not m else ""))
    print(("ok" if not failed else "FAILED") + f": mover writers scenario, {total} checks in {len(PARTS)} parts" + (f", failed: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--part"]: _run_part(sys.argv[2])
    else: _run_all()
