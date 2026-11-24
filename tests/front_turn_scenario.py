"""Scenario tests for what starts a turn of a front agent, in two parts that each run in a process of their own (formerly the suites front_turn and front_digest): an inbound notice or message, and the digest a pane is handed when it comes back.

Part `front_turn` - an inbound notice or message starts a turn of a front agent in two cases only (service/front_turn.py): (1) it needs the person and he is talking with that agent now (telling.present_fronts),
or (2) he asked that agent, in his own words, to tell him about the notice's subject (the agent is in the `tell_him` of an open item the notice names; written only by a write that carries his words in `said`). Any
other notice never reaches the front agent, NOT EVEN HELD: it goes, unmarked, to the background agent whose work it is, else it is archived (a row of the digest). A message is refused and logged instead. Fixture
data, no live store, no network, never the real `claude` (a fake script answers the thin call), never a real pane (push.py is a fake that logs what it was asked to deliver).

Fixture: projects/alpha (a front agent, home-front, and a builder, team-back); items a30 to a40.

  0  the record: what the second case reads (`tell_him`), and what it does not (`observers`, a closed item, a background agent's listing); the request is written only with his words
  1  staged through the router's real entry: marked messages for home-front that name an item of his: while he is talking with it (case 1), about an item he asked it to tell him about (case 2), and the rest: about a builder's item (goes to
     the builder, unmarked), about an item it only observes (archived: an old observer asked nothing); one that names no item of his is routed like an unmarked message (to the builder); nothing is held for the front agent in any of them
  2  a notice on an item that waits on his decision: no presence and no request: archived; while he is there: a turn; the call's drop or merge of an anchor notice on such an item is still a turn while he is there, else archived
  3  what no longer escapes the gate: a hand-back, a fallback pass, an audit batch finding (a finding never needs him: his ask warrants it, and a split batch tells the other recipient), a wake of a decision item;
     what does: a background agent's notice, a standing watch of the config, a retry of a pass already delivered; a presence that cannot be read counts as none
  4  the message tool: a message carrying the person's mark must name an open item of his (needs hold decision, or his step: `front_turn.his_items`), else it is held for the agent's next turn and starts none (a script's too; his own is exempt; a read that fails
     counts as none; refused with the hold off); naming one, it starts a turn only in the same two cases, otherwise it is refused, naming the builder, and the refusal is in the message log; the router's message of a session needs him by the same test
  5  the item notices' gate: a close of an item the agent has in `tell_him` is told with no presence, staged through the real close; an observer that asked nothing is not told
  6  the request: written only with his words (refused without `said`, with an unchecked entry, with a kind acted one), honored while he is away, keyed to its item (not another subject), taken back without words;
     the old `observers` start no turn
  7  nothing archived is invisible (a row of the digest); an exception in the gate or in the message gate fails closed (nothing delivered, nothing held); the edges of the guards

Part `front_digest` - the digest a pane is handed when it comes back ("N queued earlier", inbox.take and push.flush): a front agent's turn starts only for what is the person's, so the digest goes through
front_turn.warranted (messaging.digest_fyi). Fixture data, no live store, no network, never a real pane.

Fixture: projects/alpha (a front agent, home-front, and a builder, team-back); items 30 (the builder's) and 31 (home-front is in its `tell_him`: he asked it to tell him about it); home-lone, a front agent whose hook
cannot fetch held lines.

  1  no line carries his mark and he is away: no delivery, the lines are removed from the inbox and filed as fyi lines (one each), the board line is written on the item a line names
  2  the same without the server's hook (`digest` not given): one delivery, "N queued earlier", the lines stay leased: nothing changes for a caller that has no hook
  3  a line carries his mark: a turn while he is talking with that agent now, an fyi while he is not
  4  no line carries his mark and he is there: still an fyi (presence alone is not a need); a line about an item he asked the agent to tell him about is a turn, there or not
  5  what is never filed: the digest of a background agent, of a front agent whose hook cannot fetch held lines, a single line, a hook that fails: handed out as before, no line lost
  6  push.flush takes the same hook: filed lines are dropped from the queue and no send is made; a digest that is a turn is sent as before (not live here: exit 3, the queue kept)
  7  the server's two paths into inbox.take (the drain and the poll) give it the hook and the filed-lines report (the hand-off's delivery)
  8  a line of an exempt kind (hand-off, wake, answer, stall, comment) is never filed: a digest with one is a turn, marked or not, he there or not; by the kind stored with the line or, with none, by the shape of the notice;
     the kind reaches the line (tell_woken gives push.py the gate's kind, put and enqueue keep it)
  9  filing is no all-or-nothing: a line that cannot be filed ends the filing, the lines before it are gone and never handed out again, the others go out as one turn; the filed lines are reported (on_filed, the hand-off's ack)

The two parts set up two different instances, and each part changes module state of the code under test that the other would meet, so each part runs in a process of its own;
the file runs them one after the other, adds their check counts and exits 1 when a part fails.

    tests/run-suite front_turn        -> exit 0 / 1"""
import os, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
PARTS = ("front_turn", "front_digest")


# ================================================================ part front_turn: an inbound notice or message and the turn of a front agent
def part_front_turn():
    import json, os, re, sys, threading, time, pathlib, logging, types
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="frontturn-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml(), gbrain=True)
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    toml = toml.replace('lanes_file = ""', f'lanes_file = "{tmp}/sala/lanes.tsv"', 1); assert f'lanes_file = "{tmp}/sala/lanes.tsv"' in toml
    toml = toml.replace('limit_file = ""', f'limit_file = "{tmp}/sala/limit.json"', 1); assert f'limit_file = "{tmp}/sala/limit.json"' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                     ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
    toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
    F, B, P, N = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444")
    SO = "55555555-5555-4555-8555-555555555555"
    UID = {"home-front": F, "team-back": B, "home-peer": P, "home-name": N, "solo-front": SO}
    for d in ("store/a", "fleet/a", "state/s1", "state/site", "secrets", "touch", "repo", "sala", "brain/projects", "cli"): (T / d).mkdir(parents=True)
    (T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in UID.items()}))
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    AGENTS = {"home-front": "Oliver's point of contact", "team-back": "builds, merges and releases the code"}
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {
        "title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-name", "status": "active", "board": [], "board_row": False, "updated": 1,
        "mirror": "https://example.invalid/alpha", "agents": AGENTS, "back_agents": {"team-back": AGENTS["team-back"]}},
        "projects/solo": {"title": "Solo", "name": "Solo", "org": "home", "tags": [], "type": "project", "session": "home-name", "status": "active", "board": [], "board_row": False, "updated": 1,
        "mirror": "https://example.invalid/solo", "agents": {"solo-front": "Oliver's point of contact"}, "back_agents": {}}}}))      # a front-only project: its keeper is the front agent itself
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nThe vendor call is open.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
    def item(i, status="open", mover="team-back", **meta):
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.", "status": status,
                                                          "metadata": {"owner": F, "mover": mover, "project": "projects/alpha", **meta}, "updated": 1.0, "state_updated": 1.0}))
    item(30); item(31, tell_him=["home-front"]); item(32, needs=["decision"]); item(33, needs=["decision"], mover="home-front"); item(34, needs=["decision"]); item(35, observers=["home-front"], mover="home-front", needs=["decision"]); item(36, observers=["team-back"])      # a marked message names an open item of his (needs decision), else it is held / not a turn: a30, a36 and the rest are the builder's own work
    item(37, status="completed", tell_him=["home-front"]); item(38, mover="home-front"); item(39, mover="home-front", tell_him=["home-front"]); item(40, mover="home-front")
    item(49, status="completed", needs=["decision"]); item(47, mover="Oliver", state="your-step", step="sign the vendor form"); item(48, mover="Oliver", hold=True, wake="2099-01-01")      # a step that is his, and a call parked with him as the one who picks it up
    item(41, tell_him=["home-other"])      # he asked another front agent about it, not home-front
    item(60, mover="home-peer", project="projects/solo", observers=["solo-front"], tell_him=["solo-front"]); item(61, mover="home-peer", project="projects/solo")
    item(62, mover="home-peer", project="projects/solo", observers=["solo-front"])
    (T / "store/next-id").write_text("50")
    (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [
        {"url": "https://mail.google.com/mail/u/0/#all/1111111111111111", "items": ["a33", "a34"], "added": 1, "by": "t"}]}))
    push_log = T / "push.log"
    (T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
    CTL, CALLS = T / "fake-control.json", T / "fake-calls.jsonl"
    (T / "fake_claude.py").write_text(f'''import sys, os, json
ctl = json.load(open({str(CTL)!r}))
stdin = sys.stdin.read()
with open({str(CALLS)!r}, "a") as f: f.write(json.dumps({{"stdin": stdin}}) + "\\n")
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "duration_api_ms": 700, "num_turns": 1, "result": ctl.get("text", ""), "total_cost_usd": 0.01, "usage": {{"input_tokens": 100, "output_tokens": 10}}}}))
''')
    def fake(text=""): CTL.write_text(json.dumps({"mode": "good", "text": text}))
    def settle(until=30):
        end = time.time() + until
        while time.time() < end and any(t is not threading.main_thread() and t.is_alive() for t in threading.enumerate()):
            time.sleep(0.02)
    def pushes(): return [json.loads(l) for l in push_log.read_text().splitlines()] if push_log.exists() else []
    def pushes_to(who, needle=""): return [x for x in pushes() if x[0] in (who, UID[who]) and needle in x[1]]

    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

    from stackshot.core import config as _cfg; from stackshot.router import routing; from stackshot.router import router; from stackshot.router import router_live as live; from stackshot.anchors import anchors as a; from stackshot.waits import held
    from stackshot.web import server
    from stackshot.web import wiring
    from stackshot.service import messaging as _messaging
    from stackshot.service import telling
    from stackshot.service import front_turn
    from stackshot.service import handoff as handoff_svc
    from stackshot.web import publish as _web_publish
    from stackshot.web.tools import anchors as _wt_anchors
    from stackshot.web.tools import route as _wt_route
    from stackshot.anchors.anchorhub import core
    from stackshot.web.tools import complete as _wt_complete
    from stackshot.web import page_debts as _web_page_debts
    _web_page_debts._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
    held.mark_client("home-front")      # the rollout gate: its hook fetches held lines (a notice is held only for such a session)
    held.mark_client("team-back")
    held.mark_client("solo-front")      # the front-only project's agent fetches held lines too, so a hold for it could be filed
    _web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None; telling.PUSH = [sys.executable, str(T / "fakepush.py")]
    handoff_svc.CLI_SESSIONS = T / "cli"
    STARTED = time.time() - 3600.0
    def cli_row(who):
        """The CLI's own registry row of a pane on this box (an interactive pane, its sessionId): what presence reads to find the pane."""
        (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": UID[who], "name": who, "status": "idle", "startedAt": int(STARTED * 1000)}))
    def stamp(who, age=60.0):
        """The prompt hook's stamp file: epoch seconds of Oliver's last prompt in that pane, `age` seconds ago."""
        p = T / "state/prompts" / UID[who]; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(f"{time.time() - age:.0f}\n")
    def unstamp(who): (T / "state/prompts" / UID[who]).unlink(missing_ok=True)
    cli_row("home-front"); cli_row("team-back")
    CMD = [sys.executable, str(T / "fake_claude.py")]
    def cfg(): _cfg.CFG["router"] = {"command": CMD, "timeout_seconds": 20, "general_home": "home-front"}
    def rule_of(i): return next(n for n in routing.read("projects/alpha") if n["id"] == i)
    def lines(): return router._read(live.live_path())
    def answer(rows): return json.dumps([{"id": i, "ruling": r, "target": t, "reason": f"canned {i}", "for_owner": fo} for i, r, t, fo in rows])
    def stage(text, sender="home-peer"):
        _messaging._message("projects/alpha", text, sender)
        return routing.read("projects/alpha")[-1]
    cfg(); fake("[]")
    hub = core.Hub(); hub.deliver = lambda anchor, session, text: None; hub.write_status = lambda: None
    core._ROUTES.clear(); core._ROUTES["gmail:1111111111111111"] = [{"project": "projects/alpha", "session": "home-name", "target": "for home-front", "pilot": True, "filter": ""}]
    ev = lambda label="Gmail anchor", who="Vee", url="https://u/1": types.SimpleNamespace(label=label, who=who, url=url)
    MARK = "[for Oliver]"


    check("0 the fixture: home-front is a front agent, team-back a background one; nobody is talking with home-front yet", telling.front_sender("home-front") and not telling.front_sender("team-back")
          and telling.present_fronts() == [] and not front_turn.present("home-front"), telling.present_fronts())
    check("0 the record: home-front is in the tell_him of a31 (open) and of nothing else: not of a30 or a32, not of a35 (it only observes it: observers hear a close, they asked nothing), not of a closed item (a37), not of an item he asked another agent about (a41), "
          "and a background agent's listing (a36's observers) is no ask for the front agent",
          front_turn.asked("home-front", ["a31"]) and front_turn.asked("home-front", "a30, a31") and not front_turn.asked("home-front", ["a30", "a32"]) and not front_turn.asked("home-front", ["a35"])
          and not front_turn.asked("home-front", ["a37"]) and not front_turn.asked("home-front", ["a36"]) and not front_turn.asked("home-front", [])
          and not front_turn.asked("home-front", ["a41"]) and front_turn.asked("home-other", ["a41"]), None)
    check("0 …unless the notice is about the closed item's own close (`closed`): then a37's request matches", front_turn.asked("home-front", ["a37"], closed=True) and not front_turn.asked("home-front", ["a30"], closed=True), None)

    check("0 his_items: an open item whose needs hold decision is his (a33, a32), whatever its mover; so is one whose step is his (a47: your-step, the model reads him as the mover) and a parked one he picks up (a48)",
          front_turn.his_items(["a33"]) == ["a33"] and front_turn.his_items("a32, a47 a48") == ["a32", "a47", "a48"], (front_turn.his_items(["a33"]), front_turn.his_items("a32, a47 a48")))
    check("0 …a builder's item (a30, a36) or the front agent's own work (a38, a40) is not his; neither is a closed one (a37, nor a49, which still carries needs: decision), one that does not exist or a subject that is no item id",
          front_turn.his_items(["a30", "a36", "a38", "a40", "a37", "a49", "a999", "../a33", "33", "A33", ""]) == [] and front_turn.his_items([]) == [], front_turn.his_items(["a30", "a36", "a38", "a40", "a37", "a999"]))
    _real_load_h, _real_model_of = front_turn._load, None
    def _boom_load(g): raise OSError("the store cannot be read")
    front_turn._load = _boom_load
    try: unreadable = front_turn.his_items(["a33", "a47"])
    finally: front_turn._load = _real_load_h
    from stackshot.service import item_read as _item_read_h
    _real_model_of = _item_read_h._model_of
    def _boom_model(i): raise RuntimeError("the model cannot read it")
    _item_read_h._model_of = _boom_model
    try: unmodeled = front_turn.his_items(["a47", "a48"])
    finally: _item_read_h._model_of = _real_model_of
    check("0 …a read that fails (the store, the model) counts as no item of his: [] and no exception, so what depends on it fails closed", unreadable == [] and unmodeled == [] and front_turn.his_items(["a33"]) == ["a33"], (unreadable, unmodeled))
    _item_read_h._model_of = _boom_model
    try: plain_dec = front_turn.his_items(["a33", "a47", "a32"])
    finally: _item_read_h._model_of = _real_model_of
    check("0 …but a model that cannot be derived hides no plain needs: decision item (a33, a32 stay his; a47, whose step only the model reads, drops out)", plain_dec == ["a33", "a32"], plain_dec)
    check("0 names_his: an item of his (a33) or one he asked this agent to tell him about (a31: a builder moves it, no decision, no step of his) is named; a builder's item (a30), one asked of another agent (a41) and a closed one (a37) are not",
          front_turn.his_items(["a31"]) == [] and front_turn.names_his("home-front", ["a31"]) and front_turn.names_his("home-front", "a33") and not front_turn.names_his("home-front", ["a30"])
          and not front_turn.names_his("home-front", ["a41"]) and not front_turn.names_his("home-front", ["a37"]) and not front_turn.names_his("home-front", []) and front_turn.names_his("home-other", ["a41"]), None)
    def routed(i): return next((l for l in lines() if l["id"] == i), {})
    def held_row(who="home-front"): return held.count(who)

    # ================================================================ 1. marked notices, staged through the router's real entry
    # case 1: he is talking with home-front now (his prompt in its pane a minute ago); the notice needs him
    stamp("home-front", 60)
    check("1 presence: his prompt in home-front's pane a minute ago puts it among the fronts he is talking with", telling.present_fronts() == ["home-front"] and front_turn.present("home-front"), telling.present_fronts())
    n_c1 = stage(f"For home-front: {MARK} a33: the vendor wants a yes on the quote today")
    p0 = len(pushes()); h0 = held_row(); res = live.tick(); settle()
    check("1 case 1 (needs him, and he is talking with it now): a turn: delivered to home-front, marked for him, ruled passed", rule_of(n_c1["id"])["ruling"] == "passed" and rule_of(n_c1["id"])["ruled_to"] == "home-front"
          and len(pushes_to("home-front", n_c1["id"])) == 1 and pushes_to("home-front", n_c1["id"])[0][1].startswith(MARK) and held_row() == h0, (rule_of(n_c1["id"]), pushes()[p0:]))
    unstamp("home-front")
    check("1 …and without his prompt in that pane (no stamp) he is not talking with it", telling.present_fronts() == [], telling.present_fronts())

    # case 2: no presence, but he asked home-front to tell him about a31 (it is in its tell_him); the notice names a31
    n_c2 = stage(f"For home-front: {MARK} a31: the vendor wants a yes on the quote today")
    # neither case, about the work of a background agent (a32's mover is team-back); about no item; about an item home-front only observes (a35)
    n_no = stage(f"For home-front: {MARK} a32: the vendor wants a yes on the quote today")
    n_none = stage(f"For home-front: {MARK} the vendor wants a yes on the quote today")
    n_obs = stage(f"For home-front: {MARK} a35: the vendor wants a yes on the quote today")
    p0 = len(pushes()); h0 = held_row(); res = live.tick(); settle()
    check("1 case 2 (he asked home-front to tell him about a31): a turn: delivered to home-front, marked, ruled passed, with no presence", rule_of(n_c2["id"])["ruling"] == "passed" and rule_of(n_c2["id"])["ruled_to"] == "home-front"
          and len(pushes_to("home-front", n_c2["id"])) == 1 and pushes_to("home-front", n_c2["id"])[0][1].startswith(MARK), (rule_of(n_c2["id"]), pushes()[p0:]))
    rn = rule_of(n_no["id"]); ln_no = routed(n_no["id"])
    check("1 neither case, about a builder's item (a32): it never reaches home-front, not even held: it goes to team-back, unmarked, and the reason says it was not for the person",
          not pushes_to("home-front", n_no["id"]) and held_row() == h0 and rn["ruling"] == "passed" and rn.get("ruled_to") == "team-back" and "not for the person" in (ln_no.get("reason") or "")
          and not [x for x in pushes_to("team-back", n_no["id"]) if x[1].startswith(MARK)], (rn, ln_no, pushes()[p0:]))
    rx = rule_of(n_none["id"]); ln_x = routed(n_none["id"])
    check("1 a marked message about no item at all names no open item of his: no turn, nothing held for the front agent; it is routed as an unmarked one is: to team-back, unmarked, and the reason says it names no open item of his",
          rx["ruling"] == "passed" and rx.get("ruled_to") == "team-back" and not pushes_to("home-front", n_none["id"]) and held_row() == h0 and ln_x.get("marked") is False and not ln_x.get("held_for")
          and "names no open item of his" in (ln_x.get("reason") or "") and not [x for x in pushes_to("team-back", n_none["id"]) if x[1].startswith(MARK)], (rx, ln_x))
    ro = rule_of(n_obs["id"])
    check("1 an item the agent only observes (a35: observers hear a close, they asked nothing) is no request: no turn, archived (its mover is the front agent itself: no builder)",
          ro["ruling"] == "archived" and not pushes_to("home-front", n_obs["id"]) and held_row() == h0, (ro, pushes()[p0:]))
    check("1 …and in none of them is a line left for home-front's next turn (nothing held for it, not through the held store either)", held_row() == h0 and held.take("home-front") == "", held.take("home-front"))

    # ================================================================ 2. an item that waits on his decision: no presence, no request
    n_dec = stage("For home-front: a33 needs: decision on the vendor quote")      # a33 waits on his decision, its mover is the front agent; the text names it
    p0 = len(pushes()); h0 = held_row(); live.tick(); settle()
    check("2 a notice on an item that waits on his decision (its mover is the front agent), with no presence and no request: no turn: archived, not delivered, not held", rule_of(n_dec["id"])["ruling"] == "archived"
          and not pushes_to("home-front", n_dec["id"]) and held_row() == h0, (rule_of(n_dec["id"]), pushes()[p0:]))
    stamp("home-front", 120)
    n_dec2 = stage("For home-front: a33 needs: decision on the vendor quote, again")
    p0 = len(pushes()); live.tick(); settle()
    check("2 …and the same notice while he is talking with home-front is a turn", rule_of(n_dec2["id"])["ruling"] == "passed" and len(pushes_to("home-front", n_dec2["id"])) == 1, (rule_of(n_dec2["id"]), pushes()[p0:]))
    unstamp("home-front")
    # a person's reply on an anchor scoped to two items that wait on his decision: the read-first gate places it before any call (the call's answer here is never read), for the page's background agent: never dropped, never archived, no front turn
    def anchor_notice(text, url, gist):
        hub.send("gmail:1111111111111111", "home-name", f"[anchor] Gmail thread: {text} → {url}", ev(url=url), gist)
        return routing.read("projects/alpha")[-1]
    n_anc = anchor_notice("new reply", "https://mail.google.com/x", "new reply")
    fake(answer([(n_anc["id"], "dropped", "", False)]))
    p0 = len(pushes()); h0 = held_row(); live.tick(); settle()
    ra = rule_of(n_anc["id"]); la = routed(n_anc["id"])
    check("2 a person's reply on an anchor scoped to two items that wait on his decision, he is not there: no drop, no archive, no turn: the gate passes it to the page's background agent team-back, nothing delivered to home-front, not held for it",
          not [x for x in pushes()[p0:] if x[0] in ("home-front", F)] and held_row() == h0 and ra["ruling"] == "passed" and ra.get("ruled_to") == "team-back" and la.get("rule") == "gate-person",
          (ra, la, pushes()[p0:]))
    stamp("home-front", 60)
    n_anc2 = anchor_notice("another reply", "https://mail.google.com/y", "another reply")
    fake(answer([(n_anc2["id"], "dropped", "", False)]))
    p0 = len(pushes()); live.tick(); settle()
    ra2 = rule_of(n_anc2["id"]); la2 = routed(n_anc2["id"])
    unstamp("home-front")
    check("2 …the same reply while he is talking with home-front goes the same way: the gate's pass to team-back, no turn for home-front", ra2["ruling"] == "passed" and ra2.get("ruled_to") == "team-back"
          and not pushes_to("home-front", n_anc2["id"]), (ra2, la2, pushes()[p0:]))
    n_anc3 = anchor_notice("a third reply", "https://mail.google.com/z", "a third reply")
    fake(answer([(n_anc3["id"], "merged", "", False)]))
    p0 = len(pushes()); h0 = held_row(); live.tick(); settle()
    ra3 = rule_of(n_anc3["id"])
    check("2 a third reply, a call that would merge it is never asked: never silent, never held for the front agent: passed to team-back", ra3["ruling"] == "passed" and ra3.get("ruled_to") == "team-back" and not [x for x in pushes()[p0:] if x[0] in ("home-front", F)] and held_row() == h0, (ra3, pushes()[p0:]))
    fake("[]")

    # ================================================================ 3. what is gated now, and what is not
    n_bg = stage("For team-back: a30: please look at the vendor quote and answer it")
    p0 = len(pushes()); live.tick(); settle()
    check("3 a notice for a background agent is delivered as before (no presence needed), unmarked", rule_of(n_bg["id"])["ruling"] == "passed" and len(pushes_to("team-back", n_bg["id"])) == 1
          and not pushes_to("team-back", n_bg["id"])[0][1].startswith(MARK), (rule_of(n_bg["id"]), pushes()[p0:]))
    n_bg2 = stage(f"For team-back: {MARK} a32: please look at the vendor quote and answer it")
    p0 = len(pushes()); live.tick(); settle()
    check("3 …also one that carries the person's mark", rule_of(n_bg2["id"])["ruling"] == "passed" and len(pushes_to("team-back", n_bg2["id"])) == 1, (rule_of(n_bg2["id"]), pushes()[p0:]))

    (T / "fleet/a/sessions.json").write_text(json.dumps({**{u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in UID.items()}, "66666666-6666-4666-8666-666666666666": {"name": _cfg.audit_agent(), "machine": "a", "url": "", "seen": "x"}}))
    cx = router.Context()
    def rec(text, **kw):
        nid = routing.record("projects/alpha", kind=kw.pop("kind", "board"), to="", label=kw.pop("label", "board item"), who=kw.pop("who", "home-peer"), text=text, target="for home-front", pilot=True, live=True, **kw)
        live.stash(nid, text)
        return next(n for n in routing.read("projects/alpha") if n["id"] == nid)
    def act(n, target="home-front", **ln):
        line = {"id": n["id"], "ruling": "passed", "target": target, "reason": "r", "for_owner": False, "source": "code", "rule": "test", "item": "", **ln}
        return live._act(n, "projects/alpha", "projects/alpha", line, cx, {})
    def audit(body):
        nid_ = routing.record("projects/alpha", kind="message", to="", label="message to projects/alpha", who=_cfg.audit_agent(), text=body, target="project-wide", pilot=True, live=True); live.stash(nid_, body)
        n_ = next(x for x in routing.read("projects/alpha") if x["id"] == nid_)
        return n_, router.audit_rule("projects/alpha", n_, "projects/alpha", cx)
    # an audit batch finding to a front mover: a task, never a need of his: no turn unless he asked that agent to tell him about the item
    n_aud, ln_aud = audit("[stackshot] Audit of Thu Oct 29th: 1 finding\na33 · stale · no update for 9 days")
    check("3 the audit batch finding is one group to one agent, the front agent (no split)", bool(ln_aud) and ln_aud.get("rule") == "audit-owners" and ln_aud.get("target") == "home-front" and not ln_aud.get("split"), ln_aud)
    p0 = len(pushes()); h0 = held_row(); res = live._act(n_aud, "projects/alpha", "projects/alpha", ln_aud, cx, {}); settle()
    check("3 …about an item he did not ask it to tell him about (a33), with no presence: no turn: archived, not delivered, not held (a finding never needs him, so even his presence would not warrant it)",
          res["ruling"] == "archived" and not pushes()[p0:] and held_row() == h0, (res, pushes()[p0:]))
    n_aud2, ln_aud2 = audit("[stackshot] Audit of Thu Oct 29th: 1 finding\na39 · stale · no update for 9 days")
    p0 = len(pushes()); res = live._act(n_aud2, "projects/alpha", "projects/alpha", ln_aud2, cx, {}); settle()
    check("3 …about an item he asked it to tell him about (a39 is in its tell_him): a turn, delivered", res["ruling"] == "passed" and len(pushes()[p0:]) == 1 and pushes()[p0][0] in ("home-front", F), (res, pushes()[p0:]))
    stamp("home-front", 30)
    n_aud3, ln_aud3 = audit("[stackshot] Audit of Thu Oct 29th: 1 finding\na40 · stale · no update for 9 days")
    p0 = len(pushes()); res = live._act(n_aud3, "projects/alpha", "projects/alpha", ln_aud3, cx, {}); settle()
    unstamp("home-front")
    check("3 …and his presence alone does not warrant it (a40, he is talking with home-front): still archived: the finding asks nothing of him", res["ruling"] == "archived" and not pushes()[p0:], (res, pushes()[p0:]))
    n_aud4, ln_aud4 = audit("[stackshot] Audit of Thu Oct 29th: 2 findings\na38 · stale · no update for 9 days\na30 · stale · no update for 9 days")
    p0 = len(pushes()); h0 = held_row(); res = live._act(n_aud4, "projects/alpha", "projects/alpha", ln_aud4, cx, {}); settle()
    check("3 a batch of two movers' findings: the background mover's lines are told (team-back), the front mover's lines (a38, not asked about) are archived: never held for it, never delivered to it",
          bool(ln_aud4.get("split")) and res["ruling"] == "passed" and any(x[0] in ("team-back", B) for x in pushes()[p0:]) and not any(x[0] in ("home-front", F) for x in pushes()[p0:]) and held_row() == h0
          and "home-front (archived)" in str(res.get("target") or "") + str(rule_of(n_aud4["id"]).get("ruled_to") or ""), (ln_aud4.get("split"), res, pushes()[p0:], rule_of(n_aud4["id"])))
    n_aud5, ln_aud5 = audit("[stackshot] Audit of Thu Oct 29th: 2 findings\na38 · stale · no update for 9 days\na40 · stale · no update for 9 days")
    p0 = len(pushes()); res = live._act(n_aud5, "projects/alpha", "projects/alpha", ln_aud5, cx, {}); settle()
    check("3 a batch whose every mover is a front agent he did not ask about: nobody is told: ruled archived, not held", res["ruling"] == "archived" and not pushes()[p0:] and held_row() == h0 and rule_of(n_aud5["id"])["ruling"] == "archived", (res, rule_of(n_aud5["id"])))

    p0 = len(pushes()); h0 = held_row(); n_hb = rec("handed back to you: a38 is yours again", handback=True); res = act(n_hb, rule="hand-back"); settle()
    check("3 a hand-back to the front agent is gated like any pass (no exemption): no presence and no request: archived, not delivered, not held", res["ruling"] == "archived" and not pushes_to("home-front", "handed back to you") and held_row() == h0, (res, pushes()[p0:]))
    stamp("home-front", 30)
    n_hb2 = rec("handed back to you: a38 is yours again, once more", handback=True); res = act(n_hb2, rule="hand-back"); settle()
    unstamp("home-front")
    check("3 …and with him talking with that agent it is a turn", res["ruling"] == "passed" and res["marked"] is True and len(pushes_to("home-front", "once more")) == 1, (res, pushes()[-2:]))
    p0 = len(pushes()); n_fb = rec(f"a38: the vendor wants a yes on the quote today {MARK}"); res = act(n_fb, source="fallback"); settle()
    n_pl = rec(f"a38: the vendor wants a yes on the quote today {MARK}"); res_pl = act(n_pl); settle()
    check("3 a fallback pass to -main is gated like a plain pass of the same text (no exemption for the path): both archived, nothing delivered, nothing held", res["ruling"] == "archived" and res_pl["ruling"] == "archived"
          and not pushes_to("home-front", n_fb["id"]) and not pushes_to("home-front", n_pl["id"]) and held_row() == h0, (res, res_pl))

    # a standing watch of the config is his explicit standing ask, recorded in the config: it goes to its agent with no presence and no entry in tell_him, delivered, marked
    n_w = anchor_notice("a fourth reply", "https://mail.google.com/w", "a fourth reply")
    _cfg.CFG["router"]["watch"] = [{"page": "projects/alpha", "anchor": n_w["anchor"], "agent": "home-front"}]
    p0 = len(pushes()); h0 = held_row(); live.tick(); settle()
    check("3 a standing [[router.watch]] ruling to a front agent: delivered, marked, with no presence and no request, nothing held (his standing ask)", rule_of(n_w["id"])["ruling"] == "passed" and rule_of(n_w["id"])["ruled_to"] == "home-front"
          and len(pushes_to("home-front", n_w["id"])) == 1 and pushes_to("home-front", n_w["id"])[0][1].startswith(MARK) and held_row() == h0, (rule_of(n_w["id"]), pushes()[p0:]))
    check("3 …it is the watch rule that ruled it", routed(n_w["id"]).get("rule") == "watch", routed(n_w["id"]))
    cfg()      # the watch row away again
    # a wake for the front mover of an item that waits on his decision needs him: a turn only while he talks with that agent (case 1)
    n_wk = rec("woke home-front: a33 waits on your decision", label="wake a33", who="stackshot")
    p0 = len(pushes()); h0 = held_row(); live.tick(); settle()
    ln_wk = routed(n_wk["id"])
    check("3 a wake for the front mover of an item that waits on his decision, with no presence: no turn, nothing held: archived (the rule wake stands)", ln_wk.get("rule") == "wake" and not pushes_to("home-front", n_wk["id"])
          and held_row() == h0 and rule_of(n_wk["id"])["ruling"] == "archived" and not ln_wk.get("held_for"), (ln_wk, rule_of(n_wk["id"]), pushes()[p0:]))
    stamp("home-front", 30)
    n_wk2 = rec("woke home-front: a33 waits on your decision, again", label="wake a33", who="stackshot")
    p0 = len(pushes()); live.tick(); settle()
    check("3 …and the same wake while he is talking with that agent is a turn: delivered", rule_of(n_wk2["id"])["ruling"] == "passed" and len(pushes_to("home-front", n_wk2["id"])) == 1, (rule_of(n_wk2["id"]), pushes()[p0:]))
    unstamp("home-front")
    # a retry: a pass that was delivered earlier and only lacks its ruling is not gated again (it would drop what already reached the agent)
    n_rt = rec(f"a38: the vendor wants a yes on the quote today {MARK}")
    p0 = len(pushes()); h0 = held_row()
    res = live._act(n_rt, "projects/alpha", "projects/alpha", {"id": n_rt["id"], "ruling": "passed", "target": "home-front", "reason": "r", "for_owner": False, "source": "code", "rule": "test", "item": ""}, cx,
                    {"status": "delivered", "outcome": "delivered → home-front"}); settle()
    check("3 a retry of a pass delivered earlier (no presence, no request): ruled passed as delivered, not archived and not pushed again", res["ruling"] == "passed" and res["outcome"] == "delivered → home-front"
          and held_row() == h0 and not pushes()[p0:], (res, pushes()[p0:]))
    # a presence that cannot be read is no presence: nothing is delivered as a turn, nothing is held
    _real_present = telling.present_fronts
    def _boom(*a, **k): raise RuntimeError("no index")
    telling.present_fronts = _boom
    stamp("home-front", 30)
    try:
        n_pf = rec(f"a38: the vendor wants a yes on the quote today {MARK}"); res_pf = act(n_pf); settle(); present_fail = front_turn.present("home-front")
    finally:
        telling.present_fronts = _real_present
    unstamp("home-front")
    check("3 presence that cannot be read fails closed: it counts as no presence, so the marked pass is archived, not delivered as a turn and not held", present_fail is False and res_pf["ruling"] == "archived"
          and not pushes_to("home-front", n_pf["id"]) and held_row() == h0, (present_fail, res_pf))

    # ================================================================ 4. the message tool: the person's mark starts a turn in the same two cases only
    def send(to, text, sender="home-peer", **kw):
        p0 = len(pushes())
        try: out = _messaging._message(to, text, sender, **kw)
        except Exception as e: out = f"REFUSED {e}"
        settle()
        return out, pushes()[p0:], held_row()
    def log_rows(): return [json.loads(l) for l in _messaging.MSG_LOG.read_text().splitlines()] if _messaging.MSG_LOG.exists() else []
    n_log0 = len(log_rows())
    out_n, push_n, hd_n = send("home-front", f"{MARK} a32: the vendor wants a yes on the quote today")
    rows_n = log_rows()[n_log0:]
    check("4 a message marked for him, to a front agent he is not talking with and did not ask about a32: no turn and nothing held: refused, naming team-back, whose item a32 is", out_n.startswith("REFUSED") and not push_n and hd_n == 0
          and "starts no turn" in out_n and "nothing is held" in out_n and "team-back" in out_n and "not talking with" in out_n, (out_n[:500], push_n, hd_n))
    check("4 …and the refused message is in the message log, its row saying it was not delivered", any("not delivered" in str(r.get("outcome")) and r.get("to") == "home-front" and "a32" in str(r.get("text")) for r in rows_n), rows_n)
    h_n2 = held_row()
    out_n2, push_n2, hd_n2 = send("home-front", f"{MARK} the vendor wants a yes on the quote today")
    took_n2 = held.take("home-front")
    check("4 …a marked message that names no open item of his is held for the agent's next turn and starts none: the sender's reply says why and what to do, the held store has its words, nothing is pushed",
          out_n2.startswith("held for home-front's next turn") and not push_n2 and hd_n2 == h_n2 + 1 and "must name an open item of his" in out_n2 and "names none" in out_n2 and "starts no turn" in out_n2
          and "plain id" in out_n2 and "the vendor wants a yes on the quote today" in took_n2, (out_n2[:600], push_n2, hd_n2, took_n2))
    check("4 …and its row in the message log says it was held for the next turn", any(str(r.get("outcome")).startswith("held for its next turn") and r.get("to") == "home-front" and "vendor wants a yes" in str(r.get("text")) for r in log_rows()), log_rows()[-2:])
    out_n3, push_n3, hd_n3 = send("home-front", f"{MARK} a30: the vendor wants a yes on the quote today")
    took_n3 = held.take("home-front")
    stamp("home-front", 60)
    out_n4, push_n4, hd_n4 = send("home-front", f"{MARK} a30: the vendor wants a yes on the quote today")
    took_n4 = held.take("home-front"); unstamp("home-front")
    check("4 …a30 named, no turn at all, though he is talking with home-front: held, not delivered", out_n3.startswith("held for home-front's next turn") and not push_n3 and "a30" in took_n3
          and out_n4.startswith("held for home-front's next turn") and not push_n4 and "a30" in took_n4, (out_n3[:300], push_n3, out_n4[:300], push_n4))
    out_o, push_o, hd_o = send("home-front", f"{MARK} a35: the vendor wants a yes on the quote today")
    check("4 …about a35, which home-front only observes: refused too (an old observer asked nothing)", out_o.startswith("REFUSED") and not push_o and hd_o == 0, (out_o[:300], push_o))
    out_f = _messaging._message("home-front", "a32: the PR is merged, nothing for you to do", "team-back", fyi=True); settle()
    took_f = held.take("home-front")
    check("4 …while an fyi message keeps its own path (held for the next turn, asks nothing, starts no turn)", " · fyi · " in took_f and "they asked nothing of you" in took_f, (out_f[:200], took_f))
    out_2, push_2, hd_2 = send("home-front", f"{MARK} a31: the vendor wants a yes on the quote today")
    check("4 …the same about a31, which he asked home-front to tell him about (it is no decision and no step of his, a builder moves it): it names an item the agent was asked about, so a turn is warranted: delivered, nothing held", not out_2.startswith("held") and not out_2.startswith("REFUSED") and len(push_2) == 1 and hd_2 == 0, (out_2[:300], push_2, hd_2))
    stamp("home-front", 60)
    out_1, push_1, hd_1 = send("home-front", f"{MARK} a32: the vendor wants a yes on the quote today")
    check("4 …and about a32 while he is talking with home-front: a turn too", not out_1.startswith("held") and not out_1.startswith("REFUSED") and len(push_1) == 1 and hd_1 == 0, (out_1[:300], push_1, hd_1))
    unstamp("home-front")
    out_s, push_s, hd_s = send("home-front", f"{MARK} a32: the vendor wants a yes on the quote today", sender="Oliver")
    check("4 …a message from him himself is always a turn", not out_s.startswith("held") and not out_s.startswith("REFUSED") and len(push_s) == 1, (out_s[:300], push_s))
    out_sc, push_sc, hd_sc = send("home-front", f"{MARK} a32: the vendor wants a yes on the quote today", sender="deploy-watch", origin="box-a")
    check("4 a script's marked message (no sender session) to the front agent is tested like any other, no exemption: refused, nothing delivered, nothing held", out_sc.startswith("REFUSED") and not push_sc and hd_sc == 0, (out_sc[:300], push_sc))
    out_b, push_b, hd_b = send("team-back", "a32: please look at the vendor quote", sender="home-peer")
    check("4 a message to a background agent is delivered as before", not out_b.startswith("held") and not out_b.startswith("REFUSED") and any(x[0] == "team-back" and "[stackshot message]" in x[1] for x in push_b), (out_b[:300], push_b))
    # a marked message names an open item of his: a step that is his (a47), a parked call he picks up (a48); his own message and a script's; a read that fails; the hold switch
    out_st, push_st, hd_st = send("home-front", f"{MARK} a47: sign the vendor form, please")
    took_st = held.take("home-front")
    check("4 a marked message naming a step that is his (a47, your-step) is a turn only when warranted like any other: with no presence and no ask it is refused (the item is his, no turn), not held", out_st.startswith("REFUSED") and "starts no turn" in out_st and not push_st and hd_st == 0 and took_st == "", (out_st[:400], push_st, hd_st))
    stamp("home-front", 60)
    out_st2, push_st2, hd_st2 = send("home-front", f"{MARK} a47: sign the vendor form, please")
    out_pk, push_pk, hd_pk = send("home-front", f"{MARK} a48: the parked call is back with you")
    check("4 …while he is talking with home-front a marked message naming a47, or a48 (parked, he picks it up), is delivered: a turn, nothing held", not out_st2.startswith(("held", "REFUSED")) and len(push_st2) == 1 and hd_st2 == 0
          and not out_pk.startswith(("held", "REFUSED")) and len(push_pk) == 1 and hd_pk == 0, (out_st2[:300], push_st2, out_pk[:300], push_pk))
    out_q, push_q, hd_q = send("home-front", f"{MARK} `a33` needs your yes on the quote")
    took_q = held.take("home-front")
    out_ds, push_ds, hd_ds = send("home-front", f"{MARK} a33: the vendor wants a yes on the quote today", sender="Oliver")
    out_ow, push_ow, hd_ow = send("home-front", f"{MARK} a note for the page, no item", sender="Oliver")
    check("4 …an id in backticks names no item, so a marked message that cites a33 only that way is held, even with him there", out_q.startswith("held for home-front's next turn") and not push_q and "needs your yes" in took_q, (out_q[:300], push_q, took_q))
    check("4 …his own marked message is exempt: delivered with no item named", not out_ow.startswith(("held", "REFUSED")) and len(push_ow) == 1 and hd_ow == 0, (out_ow[:300], push_ow, hd_ow))
    out_scn, push_scn, hd_scn = send("home-front", f"{MARK} the vendor wants a yes on the quote today", sender="deploy-watch", origin="box-a")
    took_scn = held.take("home-front")
    check("4 …a script's marked message that names no item is held like a session's (no exemption), nothing pushed", out_scn.startswith("held for home-front's next turn") and not push_scn and "the vendor wants a yes" in took_scn, (out_scn[:300], push_scn, took_scn))
    _real_load_t = front_turn._load
    front_turn._load = _boom_load
    try:
        out_re, push_re, hd_re = send("home-front", f"{MARK} a33: the vendor wants a yes on the quote today")
    finally:
        front_turn._load = _real_load_t
    took_re = held.take("home-front")
    check("4 …a read of the item that fails counts as no item of his: held, never delivered, though he is talking with the agent", out_re.startswith("held for home-front's next turn") and not push_re and "a33" in took_re, (out_re[:300], push_re, took_re))
    _cfg.CFG["router"]["hold_notices"] = False
    out_hs, push_hs, hd_hs = send("home-front", f"{MARK} the vendor wants a yes on the quote today")
    _cfg.CFG["router"].pop("hold_notices")
    check("4 …with the hold switched off nothing can hold it: refused in one line that names the rule, nothing held or pushed", out_hs.startswith("REFUSED") and "must name an open item of" in out_hs and "plain id" in out_hs and not push_hs and hd_hs == 0 and "\n" not in out_hs, (out_hs[:400], push_hs, hd_hs))
    unstamp("home-front")

    # the router: a message a session wrote needs him only by naming an open item of his; the model call's for_owner guess and a mark in its text are no source (any other kind of notice keeps them)
    stamp("home-front", 30)
    n_g1 = rec("the vendor quote is ready for a look", kind="message", who="home-peer (33333333…)"); p0 = len(pushes()); h0 = held_row(); res_g1 = act(n_g1, for_owner=True); settle()
    n_g2 = rec(f"{MARK} the vendor wants a yes on the quote today", kind="message", who="home-peer (33333333…)"); res_g2 = act(n_g2, for_owner=False); settle()
    n_g3 = rec("a33: the vendor wants a yes on the quote today", kind="message", who="home-peer (33333333…)"); res_g3 = act(n_g3, for_owner=False); settle()
    n_g4 = rec("a47: sign the vendor form", kind="message", who="home-peer (33333333…)"); res_g4 = act(n_g4, for_owner=False); settle()
    n_g5 = rec("the vendor quote is ready for a look", kind="board", who="home-peer (33333333…)"); res_g5 = act(n_g5, for_owner=True); settle()
    unstamp("home-front")
    check("4 router: a message with the model's for_owner guess and no item named starts no turn though he is talking with home-front: not delivered or held for it, passed to team-back unmarked, its reason names no open item of his",
          res_g1["ruling"] == "passed" and res_g1["target"] == "team-back" and res_g1["marked"] is False and not pushes_to("home-front", n_g1["id"]) and "names no open item of his" in res_g1["reason"] and held_row() == h0, (res_g1, pushes()[p0:]))
    check("4 router: …the mark in its text with no item named does not either", res_g2["target"] == "team-back" and res_g2["marked"] is False and not pushes_to("home-front", n_g2["id"]) and "names no open item of his" in res_g2["reason"], (res_g2, pushes()[p0:]))
    check("4 router: …one naming an item of his (a33: decision; a47: his step) is a turn while he is there, marked", all(r["ruling"] == "passed" and r["target"] == "home-front" and r["marked"] is True for r in (res_g3, res_g4))
          and len(pushes_to("home-front", n_g3["id"])) == 1 and len(pushes_to("home-front", n_g4["id"])) == 1, (res_g3, res_g4, pushes()[p0:]))
    n_g6 = rec("a31: the vendor wants a yes on the quote today", kind="message", who="home-peer (33333333…)"); p6 = len(pushes()); res_g6 = act(n_g6, for_owner=False); settle()
    check("4 router: …and one naming only an item he asked home-front to tell him about (a31: a builder moves it, no decision, no step of his) is a turn with no presence, marked, as before",
          res_g6["ruling"] == "passed" and res_g6["target"] == "home-front" and res_g6["marked"] is True and len(pushes_to("home-front", n_g6["id"])) == 1, (res_g6, pushes()[p6:]))
    check("4 router: …a notice that is no session's message (a board notice) keeps the ruling's for_owner as its signal: marked, a turn while he is there", res_g5["ruling"] == "passed" and res_g5["target"] == "home-front" and res_g5["marked"] is True and len(pushes_to("home-front", n_g5["id"])) == 1, (res_g5, pushes()[p0:]))

    # ================================================================ 5. the item notices' gate: a close of an item in its tell_him is told with no presence
    check("5 the gate: a close of a31 (home-front has it in its tell_him) is sent with no presence; of a30 (no ask) and of a35 (only observed) it is not told, since he is not there",
          telling.front_verdict("a31", "home-front", "close") == ("send", "") and telling.front_verdict("a30", "home-front", "close")[0] == "hold" and telling.front_verdict("a35", "home-front", "close")[0] == "hold",
          (telling.front_verdict("a31", "home-front", "close"), telling.front_verdict("a30", "home-front", "close"), telling.front_verdict("a35", "home-front", "close")))
    check("5 …a progress notice about a31 is a turn too; a peer's fyi message (kind message) rides its next turn", telling.front_verdict("a31", "home-front", "progress") == ("send", "") and telling.front_verdict("a31", "home-front", "message") == ("fyi", ""), None)
    check("5 …the fixture: the project's keeper is the front agent itself, and a60 is open with no presence for it", telling.page_keeper("projects/solo") == "solo-front" and telling.present_fronts() == [], (telling.page_keeper("projects/solo"), telling.present_fronts()))
    p0 = len(pushes()); res = _wt_complete.stackshot_complete("a60", sender="team-back", outcome="done", reason="landed", description="- Goal: Done"); settle()
    told_c = [x for x in pushes()[p0:] if x[0] in ("solo-front", SO) and "observer solo-front" in x[1]]
    check("5 a real close of a60 (saved as completed first; solo-front observes it and has it in its tell_him): the notice is a turn of the front agent, with no presence", json.loads((T / "store/a/60.json").read_text())["status"] == "completed" and len(told_c) == 1
          and "was completed (done: landed)" in told_c[0][1] and "(observers told: solo-front for solo-front)" in res, (res[-500:], pushes()[p0:]))
    check("5 …and the same item, now closed, no longer matches a plain notice about it", not front_turn.asked("solo-front", ["a60"]) and front_turn.asked("solo-front", ["a60"], closed=True), None)
    p0 = len(pushes()); res = _wt_complete.stackshot_complete("a62", sender="team-back", outcome="done", reason="landed", description="- Goal: Done"); settle()
    check("5 a real close of a62 (solo-front only observes it, asked nothing): no turn of the front agent, nothing delivered to it", not [x for x in pushes()[p0:] if x[0] in ("solo-front", SO)] and "solo-front for solo-front" not in res, (res[-300:], pushes()[p0:]))

    # ================================================================ 6. the request: written only with his words, keyed to its item, taken back without them; the old observers start no turn
    from stackshot.service import gates as _gates
    from stackshot.service import update as _update_svc
    def upd(item_id, **kw):
        try: return _update_svc._update(item_id, sender="team-back", **kw)
        except Exception as e: return f"REFUSED {e}"
    ACK = {"tag": "Acked-by", "quote": "ask home-front to tell me about a32", "msg": "11111111-1111-4111-8111-000000000002", "session": F, "checked": True, "ts": time.time()}
    def refused_gate(said_l):
        try: _gates.gate_tell_him("home-front", said_l); return False
        except Exception as e: return "his own words" in str(e)
    check("6 the gate refuses a request that carries no words of his, an unchecked entry, a kind acted entry and another tag; it accepts a checked Acked-by one",
          refused_gate([]) and refused_gate([{**ACK, "checked": False}]) and refused_gate([{**ACK, "kind": "acted"}]) and refused_gate([{**ACK, "tag": "Co-decided-by"}]) and _gates.gate_tell_him("home-front", [ACK]) == ["home-front"], None)
    out_w = upd("a32", tell_him="home-front")
    check("6 a write of tell_him with no `said` is refused, and nothing is recorded: a session cannot record it for him", str(out_w).startswith("REFUSED") and "his own words" in str(out_w)
          and not front_turn.asked("home-front", ["a32"]) and "tell_him" not in json.loads((T / "store/a/32.json").read_text())["metadata"], out_w)
    _real_said = _gates.gate_said
    _gates.gate_said = lambda said, *a, **k: [ACK] if said else []      # his words checked against the transcript: that check has its own suites (said, said_acted); here only what the request does with it
    try:
        out_w2 = upd("a32", tell_him="home-front", said=[{"tag": "Acked-by", "quote": ACK["quote"], "msg": ACK["msg"]}])
    finally:
        _gates.gate_said = _real_said
    check("6 the same write with his words (a checked Acked-by): recorded on the item's own field", not str(out_w2).startswith("REFUSED") and json.loads((T / "store/a/32.json").read_text())["metadata"].get("tell_him") == ["home-front"], out_w2)
    n_away = stage(f"For home-front: {MARK} a32: the vendor wants a yes on the quote today, he is away")
    n_other = stage(f"For home-front: {MARK} a30: the vendor wants a yes on the quote today, another subject")
    p0 = len(pushes()); h0 = held_row(); live.tick(); settle()
    check("6 …honored while he is away: the notice about a32 is a turn of home-front, with no presence", rule_of(n_away["id"])["ruling"] == "passed" and rule_of(n_away["id"])["ruled_to"] == "home-front" and len(pushes_to("home-front", n_away["id"])) == 1, (rule_of(n_away["id"]), pushes()[p0:]))
    check("6 …and not for another subject: the notice about a30 (not in any tell_him) is no turn: it goes to the builder, unmarked", not pushes_to("home-front", n_other["id"]) and held_row() == h0 and rule_of(n_other["id"]).get("ruled_to") == "team-back", (rule_of(n_other["id"]), pushes()[p0:]))
    out_x = upd("a30", observers="home-front")
    check("6 listing home-front among a30's observers (no words of his, an ordinary write) makes no request: a notice about a30 still starts no turn", not str(out_x).startswith("REFUSED") and not front_turn.asked("home-front", ["a30"])
          and "home-front" in json.loads((T / "store/a/30.json").read_text())["metadata"].get("observers", []), out_x)
    n_obs2 = stage(f"For home-front: {MARK} a30: the vendor wants a yes on the quote today, an observer now")
    p0 = len(pushes()); live.tick(); settle()
    check("6 …a marked notice about it is not delivered to home-front: the old observers start no turns", not pushes_to("home-front", n_obs2["id"]) and rule_of(n_obs2["id"]).get("ruled_to") == "team-back", (rule_of(n_obs2["id"]), pushes()[p0:]))
    out_back = upd("a32", tell_him="none")
    check("6 tell_him=\"none\" takes the request back with no words of his: it is gone, and a notice about a32 starts no turn again", not str(out_back).startswith("REFUSED") and not front_turn.asked("home-front", ["a32"])
          and "tell_him" not in json.loads((T / "store/a/32.json").read_text())["metadata"], out_back)

    # ================================================================ 7. nothing archived is invisible; a failing gate fails closed; the edges of the guards
    import datetime
    D0 = datetime.datetime.now(_cfg.tz()).replace(hour=12, minute=0, second=0, microsecond=0).timestamp()      # a time after [router] digest_hour, in the instance's timezone
    ids_arch = [i["id"] for i in (n_obs, n_dec)]      # the ones the live tick archived
    res_d = live.digest_tick(now=D0)
    lg_all = [l for l in lines() if l.get("kind") == "digest_logged" and l.get("group") == "main"]
    lg_main = [l for l in lg_all if n_obs["id"] in l["ids"]]      # the project's own line (a notice of another project's would be on its own)
    check("7 a pass the gate archives is a row of the digest: every pass of this scenario the live tick archived is listed once, in the main group, and nothing is pushed to an agent for it",
          len(lg_main) == 1 and all(i in lg_main[0]["ids"] for i in ids_arch) and not [x for x in pushes() if "router digest" in x[1]], ([(l.get("project"), l["ids"]) for l in lg_all], lg_main and lg_main[0]["ids"], ids_arch, [x for x in pushes() if "router digest" in x[1]][:1]))
    check("7 …and a later tick the same day lists nothing again", live.digest_tick(now=D0 + 3600)["logged"] == 0 and len([l for l in lines() if l.get("kind") == "digest_logged" and l.get("group") == "main"]) == len(lg_all), None)

    # an exception inside the gate fails closed, as a presence that cannot be read does (he is talking with the agent, so a failing-open gate would deliver)
    _real_hook = live._HOOKS["front_turn"]
    def _boom_hook(*a, **k): raise RuntimeError("the hook failed")
    live._HOOKS["front_turn"] = _boom_hook
    stamp("home-front", 30)
    try:
        n_ex = rec(f"a38: the vendor wants a yes on the quote today {MARK}"); res_ex = act(n_ex); settle()
    finally:
        live._HOOKS["front_turn"] = _real_hook
    unstamp("home-front")
    check("7 an exception inside the front-turn gate archives the pass (fails closed): it does not deliver it, and holds nothing for the agent", res_ex["ruling"] == "archived" and not pushes_to("home-front", n_ex["id"]) and held_row() == h0, res_ex)
    _real_warranted = front_turn.warranted
    def _boom_warranted(*a, **k): raise RuntimeError("the test failed")
    front_turn.warranted = _boom_warranted
    stamp("home-front", 30)
    try:
        out_xx, push_xx, hd_xx = send("home-front", f"{MARK} a32: the vendor wants a yes on the quote today")
    finally:
        front_turn.warranted = _real_warranted
    unstamp("home-front")
    check("7 …and an exception in the message gate refuses the message too (nothing delivered, nothing held), the sender is told", out_xx.startswith("REFUSED") and not push_xx and hd_xx == 0, (out_xx[:300], push_xx, hd_xx))

    # the edges of the guards
    _real_load, loaded = front_turn._load, []
    front_turn._load = lambda g: (loaded.append(g), _real_load(g))[1]
    try:
        ask_bad = front_turn.asked("home-front", ["../a31", "a31/x", "31", "A31", "a31x", ""])
        ask_ok = front_turn.asked("home-front", "a31")
    finally:
        front_turn._load = _real_load
    check("7 a subject that is no item id (a path, a bare number, capitals, trailing letters) is never looked up in the store; an id is", ask_bad is False and ask_ok is True and loaded == ["a31"], (ask_bad, ask_ok, loaded))
    # a pass the router could not place (its route test fails: unsure, so as before) and that carries no need of his is no turn, even while he is talking with the agent: `needs` is the router's own test
    _real_route = live._front_route
    live._front_route = lambda *a, **k: ("", "")
    stamp("home-front", 30)
    try:
        n_nn = rec("a38: the vendor quote is ready for review", who="home-peer"); res_nn = act(n_nn, rule="test"); settle()
    finally:
        live._front_route = _real_route
    unstamp("home-front")
    check("7 a pass with no need of his (no mark, no words, no decision item) that nothing placed is archived, not delivered marked, though he is talking with that agent (with a need it is delivered: see 1, case 1)",
          res_nn["ruling"] == "archived" and not pushes_to("home-front", n_nn["id"]) and held_row() == h0, (res_nn, pushes()[-2:]))

    # ================================================================ 8. a background agent that cannot be reached; a project with no background agent
    # the notice went to team-back, every delivery failed, and the fallback after three tries is a pass to the front agent: gated like any pass, and never routed back to the agent that already failed
    FAILED = {"tries": 3, "target": "team-back", "status": "error"}
    def fallback_act(n): return live._act(n, "projects/alpha", "projects/alpha", {"id": n["id"], "ruling": "passed", "target": "team-back", "reason": "r", "for_owner": False, "source": "code", "rule": "test", "item": "a32"}, cx, FAILED)
    unstamp("home-front"); p0 = len(pushes()); h0 = held_row()
    n_f1 = rec("a32: the vendor quote is ready for review", who="home-peer"); res_f1 = fallback_act(n_f1); settle()
    check("8 team-back fails three times, he is not there, the notice asks nothing: the fallback archives it (a row of the digest), it is not sent back to team-back, and it is out of the error state",
          res_f1["ruling"] == "archived" and res_f1.get("status") != "error" and not pushes_to("team-back", n_f1["id"]) and not pushes_to("home-front", n_f1["id"]) and held_row() == h0 and rule_of(n_f1["id"])["ruling"] == "archived", (res_f1, pushes()[p0:]))
    stamp("home-front", 30); p0 = len(pushes())
    n_f2 = rec(f"a32: the vendor wants a yes on the quote today {MARK}", who="home-peer"); res_f2 = fallback_act(n_f2); settle()
    unstamp("home-front")
    check("8 …and the same with him talking with home-front and the notice needing him: the fallback passes it to the front agent, marked, as before",
          res_f2["ruling"] == "passed" and res_f2.get("target") == "home-front" and len(pushes_to("home-front", n_f2["id"])) == 1 and not pushes_to("team-back", n_f2["id"]), (res_f2, pushes()[p0:]))
    n_f3 = rec("a31: the vendor quote is ready for review", who="home-peer"); p0 = len(pushes()); res_f3 = fallback_act(n_f3); settle()
    check("8 …and when he asked home-front to tell him about the item (a31 is in its tell_him), with no presence: the fallback passes it to the front agent too", res_f3["ruling"] == "passed" and res_f3.get("target") == "home-front"
          and len(pushes_to("home-front", n_f3["id"])) == 1 and not pushes_to("team-back", n_f3["id"]), (res_f3, pushes()[p0:]))

    # a project with no background agent: an unmarked notice that asks nothing, he absent, is archived like the marked one, never held for the front agent
    def solo_act(text):
        nid_s = routing.record("projects/solo", kind="board", to="", label="board item", who="home-peer", text=text, target="for solo-front", pilot=True, live=True); live.stash(nid_s, text)
        n_s = next(x for x in routing.read("projects/solo") if x["id"] == nid_s)
        return n_s, live._act(n_s, "projects/solo", "projects/solo", {"id": nid_s, "ruling": "passed", "target": "solo-front", "reason": "r", "for_owner": False, "source": "code", "rule": "test", "item": "a61"}, cx, {})
    hs0 = held.count("solo-front"); p0 = len(pushes())
    n_s1, res_s1 = solo_act("a61: the vendor quote is ready for review")
    check("8 a front-only project, an unmarked notice that asks nothing, he absent: archived (a row of the digest), nothing is filed for the front agent and nothing is delivered",
          res_s1["ruling"] == "archived" and held.count("solo-front") == hs0 and not [x for x in pushes()[p0:] if x[0] in ("solo-front", SO)], (res_s1, held.count("solo-front"), pushes()[p0:]))
    n_s2, res_s2 = solo_act(f"a61: the vendor wants a yes on the quote today {MARK}")
    check("8 …the marked notice of the same kind is archived too: the mark makes no difference to where it goes", res_s2["ruling"] == "archived" and held.count("solo-front") == hs0, (res_s2,))

    # the request is bound to the agent's name: an agent that is renamed is not the one he asked (a31 lists home-front only)
    check("8 the request names the agent: a31 is asked of home-front, not of a session by another name", front_turn.asked("home-front", ["a31"]) and not front_turn.asked("home-front-renamed", ["a31"]), None)

    # ================================================================ 9. a notice is never handed back to the session that wrote it
    # the builder (team-back) moves a32 and wrote the notice; he is not talking with home-front: no turn is owed, and the builder is no place for its own words
    unstamp("home-front"); p0 = len(pushes()); h0 = held_row()
    n_s1 = rec(f"For home-front: {MARK} a32: please decide today whether to ship", who="team-back"); res_s1 = act(n_s1, rule="test"); settle()
    check("9 a marked notice the builder (the item's mover) wrote about its own item, he absent: archived (a row of the digest), not passed back to team-back, nothing for home-front, nothing held",
          res_s1["ruling"] == "archived" and not pushes_to("team-back", n_s1["id"]) and not pushes_to("home-front", n_s1["id"]) and held_row() == h0, (res_s1, pushes()[p0:]))
    n_s2 = rec("a30: the vendor quote is ready for review", who="team-back"); res_s2 = act(n_s2, rule="test"); settle()
    check("9 …the same from the builder when it asks nothing: its plain word to its front agent is the channel between them (held for its next turn, a known exception, starts no turn): never passed back to team-back, no push to home-front",
          res_s2["ruling"] == "held" and not pushes_to("team-back", n_s2["id"]) and not pushes_to("home-front", n_s2["id"]), (res_s2, pushes()[p0:]))
    stamp("home-front", 30); p0 = len(pushes())
    n_s3 = rec(f"For home-front: {MARK} a32: please decide today whether to ship", who="team-back"); res_s3 = act(n_s3, rule="test"); settle()
    unstamp("home-front")
    check("9 …but with him talking with home-front and the notice needing him, the builder's notice is a turn of the front agent, marked, as before",
          res_s3["ruling"] == "passed" and len(pushes_to("home-front", n_s3["id"])) == 1 and pushes_to("home-front", n_s3["id"])[0][1].startswith(MARK) and not pushes_to("team-back", n_s3["id"]), (res_s3, pushes()[p0:]))
    p0 = len(pushes())
    n_s4 = rec("a32: the vendor quote is ready for review", who="home-peer"); res_s4 = act(n_s4, rule="test"); settle()
    check("9 a peer's notice about the builder's item (a32), he absent: goes to team-back, unmarked, as before", res_s4["ruling"] == "passed" and res_s4.get("ruled_to", res_s4.get("target")) == "team-back"
          and len(pushes_to("team-back", n_s4["id"])) == 1 and not pushes_to("home-front", n_s4["id"]) and not pushes_to("team-back", n_s4["id"])[0][1].startswith(MARK), (res_s4, pushes()[p0:]))
    p0 = len(pushes())
    n_s5 = rec("a32: the vendor quote is ready for review", who="home-front"); res_s5 = act(n_s5, rule="test"); settle()
    check("9 the front agent's own notice about the builder's item, he absent: goes to team-back (the sender is not the builder), never back to home-front", res_s5["ruling"] == "passed" and len(pushes_to("team-back", n_s5["id"])) == 1 and not pushes_to("home-front", n_s5["id"]), (res_s5, pushes()[p0:]))
    p0 = len(pushes())
    n_s6 = rec(f"For home-front: {MARK} a31: the vendor wants a yes on the quote today", who="team-back"); res_s6 = act(n_s6, rule="test"); settle()
    check("9 …and a notice the builder wrote about an item he asked home-front to tell him about (a31), he absent: still case 2, a turn of home-front", res_s6["ruling"] == "passed" and len(pushes_to("home-front", n_s6["id"])) == 1, (res_s6, pushes()[p0:]))
    return ran, fails


# ================================================================ part front_digest: the digest a pane is handed when it comes back
def part_front_digest():
    import json, os, re, sys, time, pathlib, logging
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="frontdigest-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml(), gbrain=True)
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    toml = toml.replace('lanes_file = ""', f'lanes_file = "{tmp}/sala/lanes.tsv"', 1); assert f'lanes_file = "{tmp}/sala/lanes.tsv"' in toml
    toml = toml.replace('limit_file = ""', f'limit_file = "{tmp}/sala/limit.json"', 1); assert f'limit_file = "{tmp}/sala/limit.json"' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                     ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
    toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=str(T / "home")); os.environ.pop("STACKSHOT_URL", None)
    F, B, L = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333")
    UID = {"home-front": F, "team-back": B, "home-lone": L}
    for d in ("store/a", "fleet/a", "state/s1", "state/site", "secrets", "touch", "repo", "sala", "brain/projects", "cli", "home"): (T / d).mkdir(parents=True)
    (T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
    (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in UID.items()}))
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    AGENTS = {"home-front": "Oliver's point of contact", "home-lone": "a second point of contact", "team-back": "builds, merges and releases the code"}
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {
        "title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-front", "status": "active", "board": [], "board_row": False, "updated": 1,
        "mirror": "https://example.invalid/alpha", "agents": AGENTS, "back_agents": {"team-back": AGENTS["team-back"]}}}}))
    (T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nThe vendor call is open.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
    def item(i, **meta):
        (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.", "status": "open",
                                                          "metadata": {"owner": F, "mover": "team-back", "project": "projects/alpha", **meta}, "updated": 1.0, "state_updated": 1.0}))
    item(30); item(31, tell_him=["home-front"])
    (T / "store/next-id").write_text("50"); (T / "store/anchors.json").write_text("{}")
    shown = lambda n: f"a{n}"      # an item as a notice names it: the store's own id (the fixture's items are a30 and a31)

    sys.path.insert(0, STACK); logging.disable(logging.INFO)
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

    from stackshot.core import config as _cfg; from stackshot.waits import held; from stackshot.fleet import inbox, push
    from stackshot.web import server
    from stackshot.service import messaging as _messaging
    from stackshot.service import telling
    from stackshot.service import front_turn
    from stackshot.service import handoff as handoff_svc
    held.mark_client("home-front"); held.mark_client("team-back")      # the rollout gate: their hooks fetch held lines (home-lone's does not)
    handoff_svc.CLI_SESSIONS = T / "cli"
    STARTED = time.time() - 3600.0
    def cli_row(who):
        (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": UID[who], "name": who, "status": "idle", "startedAt": int(STARTED * 1000)}))
    def stamp(who, age=60.0):
        p = T / "state/prompts" / UID[who]; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(f"{time.time() - age:.0f}\n")
    def unstamp(who): (T / "state/prompts" / UID[who]).unlink(missing_ok=True)
    for w in UID: cli_row(w)
    MARK = "[for Oliver]"
    HOOK = _messaging.digest_fyi


    def reset():
        """Nothing left of an earlier case: the inbox, the leases, the held lines (the clients file stays), the presence stamps, the queue."""
        for src in inbox.SOURCES:
            for p in (inbox.DIR / src).glob("*.json"): p.unlink()
        (inbox.DIR / "leases.json").unlink(missing_ok=True)
        for p in held.dir_().glob("*"):
            if p.name != "clients.json": p.unlink()
        for w in UID: unstamp(w)
        for p in pathlib.Path(push.Q).glob("*"): p.unlink()
    def put(who, *texts, kind=""):
        return [inbox.put(UID[who], t, "msg", sender="home-peer", kind=kind) for t in texts]
    def take(who, digest=HOOK):
        return inbox.take({UID[who]: who}, known={UID[who]}, only_src="msg", digest=digest)
    def held_text(who="home-front"):
        out = []
        for p in held.dir_().glob("*"):
            if p.name != "clients.json" and p.is_file(): out.append(p.read_text(encoding="utf-8"))
        return "\n".join(out)
    def quiet_log(i): return [x.get("text", "") for x in (json.loads((T / f"store/a/{i}.json").read_text())["metadata"].get("front_quiet") or {}).get("log", [])]

    check("0 the fixture: home-front is a front agent, team-back is not; nobody is talking with home-front", telling.front_sender("home-front") and not telling.front_sender("team-back") and not front_turn.present("home-front"))
    check("0 …home-front's hook fetches held lines, home-lone's does not", held.can_fetch("home-front") and not held.can_fetch("home-lone"))

    PLAIN = [f"{shown(30)}: the build finished, nothing to do", f"a notice about nothing at all", f"{shown(30)}: the release went out"]
    # ---- 1. no line is his, he is away
    reset(); ids = put("home-front", *PLAIN)
    tk = take("home-front")
    check("1 no line carries his mark and he is away: no delivery", tk == [], tk)
    check("1 …the lines are gone from the inbox (not leased, not waiting)", inbox.waiting() == {} and not (inbox.DIR / "leases.json").exists() or not json.loads((inbox.DIR / "leases.json").read_text() or "{}"), (inbox.waiting(), inbox._leases()))
    ht = held_text()
    check("1 …each line is filed as an fyi for the agent's next turn", held.count("home-front") == 3 and "the build finished" in ht and "the release went out" in ht and "a notice about nothing at all" in ht, (held.count("home-front"), ht))
    check("1 …and the item a line names has its board line", any("hears of it on his next turn" in x and "the build finished" in x for x in quiet_log(30)), quiet_log(30))
    check("1 a second poll finds nothing to hand out (the lines are not offered again)", take("home-front") == [], inbox.waiting())

    # ---- 2. no hook given: as before
    reset(); ids = put("home-front", *PLAIN)
    tk = take("home-front", digest=None)
    check("2 without the server's hook: one delivery of the whole digest, as it always was", len(tk) == 1 and tk[0]["text"].startswith("[stackshot] 3 queued earlier:\n") and tk[0]["ids"] == ids and held.count("home-front") == 0, tk)

    # ---- 3. a line carries his mark
    reset(); stamp("home-front"); put("home-front", PLAIN[0], f"{MARK} {shown(30)}: sign the form")
    tk = take("home-front")
    check("3 a line carries his mark and he is talking with that agent now: a turn, the whole digest, nothing filed", len(tk) == 1 and tk[0]["text"].count("queued earlier") == 1 and MARK in tk[0]["text"] and held.count("home-front") == 0, (tk, held.count("home-front")))
    reset(); put("home-front", PLAIN[0], f"{MARK} {shown(30)}: sign the form")
    tk = take("home-front")
    check("3 …the same digest while he is away: no turn, both lines filed as fyi lines (the marked one too), none lost", tk == [] and held.count("home-front") == 2 and "sign the form" in held_text() and inbox.waiting() == {}, (tk, held.count("home-front"), inbox.waiting()))
    reset(); put("home-front", PLAIN[0], f"{shown(30)}: it needs: decision before Friday")
    check("3 a line that says needs: decision counts as his mark: a turn while he is there", (stamp("home-front"), len(take("home-front")) == 1)[1] and held.count("home-front") == 0)

    # ---- 4. presence alone is no need; his ask is a turn
    reset(); stamp("home-front"); put("home-front", *PLAIN)
    tk = take("home-front")
    check("4 no line is marked and he is there: still no turn, the lines are filed", tk == [] and held.count("home-front") == 3, (tk, held.count("home-front")))
    reset(); put("home-front", PLAIN[0], f"{shown(31)}: the vendor wrote back")
    tk = take("home-front")
    check("4 a line names an item he asked this agent to tell him about (tell_him), and he is away: a turn", len(tk) == 1 and held.count("home-front") == 0 and shown(31) in tk[0]["text"], (tk, held.count("home-front")))
    reset(); put("home-front", PLAIN[0], f"{shown(30)}: the vendor wrote back")
    check("4 …an item he asked about no one: filed", take("home-front") == [] and held.count("home-front") == 2)

    # ---- 5. what is never filed
    reset(); put("team-back", *PLAIN)
    tk = take("team-back")
    check("5 a background agent's digest is handed out as before (the rule is for a front agent's turn)", len(tk) == 1 and tk[0]["text"].count("queued earlier") == 1 and held.count("team-back") == 0, (tk, held.count("team-back")))
    reset(); put("home-lone", *PLAIN)
    tk = take("home-lone")
    check("5 a front agent whose hook cannot fetch held lines gets the digest as a turn: nothing would carry the lines, none is lost", len(tk) == 1 and held.count("home-lone") == 0 and len(tk[0]["ids"]) == 3, (tk, held.count("home-lone")))
    reset(); put("home-front", PLAIN[0])
    tk = take("home-front")
    check("5 a single line is no digest: handed out as it always was", len(tk) == 1 and tk[0]["text"].startswith("from: home-peer") and held.count("home-front") == 0, tk)
    def broken(name, lines, kinds): raise RuntimeError("the hook failed")
    reset(); ids = put("home-front", *PLAIN)
    tk = take("home-front", digest=broken)
    check("5 a hook that fails hands the digest out as before: nothing lost", len(tk) == 1 and tk[0]["ids"] == ids and held.count("home-front") == 0, tk)
    reset(); put("home-front", *PLAIN)
    tk = take("home-front", digest=lambda name, lines, kinds: [])
    check("5 a hook that says no hands the digest out", len(tk) == 1 and len(tk[0]["ids"]) == 3, tk)

    # ---- 6. push.flush takes the same hook
    def queue(name, *texts):
        pathlib.Path(push.Q).mkdir(parents=True, exist_ok=True)
        with open(pathlib.Path(push.Q) / f"{name}.jsonl", "a", encoding="utf-8") as f:
            for t in texts: f.write(json.dumps({"t": time.time(), "text": t, "from": "home-peer"}) + "\n")
    qf = lambda name: pathlib.Path(push.Q) / f"{name}.jsonl"
    reset(); queue("home-front", *PLAIN)
    rc = push.flush("home-front", digest=HOOK)
    check("6 push.flush: the queued lines of no concern to him are filed as fyi lines, the queue is removed and nothing is sent", rc == 0 and not qf("home-front").exists() and held.count("home-front") == 3, (rc, held.count("home-front")))
    reset(); queue("home-front", *PLAIN)
    rc = push.flush("home-front")
    check("6 …without the hook it tries to send the digest, as it always did (no pane here: exit 3, the queue is kept)", rc == 3 and qf("home-front").exists() and held.count("home-front") == 0, rc)
    reset(); queue("home-front", PLAIN[0], f"{MARK} {shown(30)}: sign the form"); stamp("home-front")
    rc = push.flush("home-front", digest=HOOK)
    check("6 …a digest that is a turn (marked, and he is there) is sent: not filed, exit 3 here, the queue is kept", rc == 3 and qf("home-front").exists() and held.count("home-front") == 0, rc)

    # ---- 7. the server's two delivery paths give the hook
    import inspect
    from stackshot.web.routes import client_api
    check("7 the puller's drain and its poll both give inbox.take the server's hook", inspect.getsource(client_api).count("digest=_messaging.digest_fyi") == 2)
    check("7 …and both report the filed lines to the hand-off's ack (a filed hand-off notice is a delivered one)", inspect.getsource(client_api).count("on_filed=_handoff.handoff_acked") == 2)

    # ---- 8. a line of an exempt kind is never filed
    HANDOFF = f"[stackshot] {shown(30)} it came to you: its sender moved it, take it from here"
    WAKE = f"[stackshot] {shown(30)} is yours now: its wait ended"
    STALL = "[stackshot] you have had no turn running for 40 minutes on an open item"
    ANSWER = f"{shown(30)}: his answer, relayed: go with the second option"       # no mark, no known shape: only its stored kind says what it is
    COMMENT = f"{shown(30)}: a comment on your item, nothing more"
    def turn_of(texts, kinds, away=True):
        """Put the lines (each with the kind it is stored with, "" = none) in the inbox of home-front, take them with the server's hook → (deliveries, fyi lines filed)."""
        reset()
        if not away: stamp("home-front")
        for t, k in zip(texts, kinds): inbox.put(UID["home-front"], t, "msg", sender="home-peer", kind=k)
        tk = take("home-front")
        return tk, held.count("home-front")
    for label, text, kind in (("a hand-off notice", HANDOFF, ""), ("a wake notice", WAKE, ""), ("a stall notice", STALL, ""),
                              ("a relayed board answer", ANSWER, "exempt"), ("a comment notice", COMMENT, "exempt"), ("a hand-off notice with its kind stored", HANDOFF, "exempt")):
        tk, n = turn_of([PLAIN[0], text], ["", kind])
        check(f"8 {label} in a digest, no mark, he is away: a turn, nothing filed", len(tk) == 1 and len(tk[0]["ids"]) == 2 and text in tk[0]["text"] and n == 0 and inbox.waiting() != {}, (tk, n))
        tk, n = turn_of([text, PLAIN[2]], [kind, ""], away=False)
        check(f"8 …the same with him there for the pane: a turn, nothing filed", len(tk) == 1 and len(tk[0]["ids"]) == 2 and n == 0, (tk, n))
    tk, n = turn_of([f"{MARK} {PLAIN[0]}", COMMENT], ["", "exempt"])
    check("8 an exempt line beside a marked one while he is away: still a turn: the exempt line is never filed", len(tk) == 1 and n == 0, (tk, n))
    for kind in ("progress", "close", "message", "", "stuck"):
        tk, n = turn_of([PLAIN[0], PLAIN[2]], [kind, ""])
        check(f"8 control: lines of kind {kind or 'none'!r} that ask nothing are still filed (the hook files what asks nothing of him)", tk == [] and n == 2, (tk, n))
    reset()
    check("8 the hook reads a tag as well as a kind: a line stored as 'handoff' or 'comment' is exempt", all(HOOK("home-front", PLAIN[:2], [tg, ""]) == [] for tg in ("handoff", "wake", "answer", "stall", "comment")) and held.count("home-front") == 0)
    check("8 inbox.kind_of: the stored kind first; the shape of a stall, wake or hand-off notice is exempt; anything else is unknown", (inbox.kind_of({"kind": "close", "text": HANDOFF}), inbox.kind_of({"text": HANDOFF}), inbox.kind_of({"text": WAKE}), inbox.kind_of({"text": STALL}),
           inbox.kind_of({"text": PLAIN[0]}), inbox.kind_of({"kind": "Bad Kind!", "text": PLAIN[0]})) == ("close", "exempt", "exempt", "exempt", "", ""))
    # the kind reaches the line: put and enqueue keep it, tell_woken gives push.py the gate's kind
    reset(); iid = inbox.put(UID["home-front"], PLAIN[0], "msg", sender="home-peer", kind="exempt"); iid2 = inbox.put(UID["home-front"], PLAIN[1], "msg", sender="home-peer")
    stored = {r["id"]: r for r in inbox.peek([iid, iid2])}
    check("8 inbox.put stores the kind with the line, and no key when none is given (a line as it always was)", stored[iid].get("kind") == "exempt" and "kind" not in stored[iid2], stored)
    check("8 push.py reads $ANCHOR_PUSH_KIND through the same cleaning (a word, never free text)", push._inbox.clean_kind("exempt") == "exempt" and push._inbox.clean_kind("a b; rm") == "" and push._inbox.clean_kind(None) == "")
    import subprocess as _sp, threading
    class _Done:
        returncode = 0; stdout = "inbox → x\n"; stderr = ""
    seen_env = []
    def fake_run(cmd, **kw):
        seen_env.append(kw.get("env", {}).get("ANCHOR_PUSH_KIND")); return _Done()
    real_run = _sp.run; _sp.run = fake_run
    try:
        for tag, hint, want in (("handoff", "", "exempt"), ("wake", "", "exempt"), ("answer", "", "exempt"), ("stall", "", "exempt"), ("comment", "", "exempt"),
                                ("owner", "close", "close"), ("owner", "", "progress"), ("wake", "progress", "progress")):
            seen_env.clear()
            telling.FRONT_HINT.kind = hint
            try: th = telling.tell_woken(shown(30), "team-back", f"[stackshot] {shown(30)} a notice", tag=tag)
            finally: telling.FRONT_HINT.kind = ""
            if th: th.join(20)
            check(f"8 tell_woken gives push.py the gate's kind: tag {tag!r}{' hint ' + repr(hint) if hint else ''} → {want}", seen_env == [want], seen_env)
    finally:
        _sp.run = real_run

    # ---- 9. filing is no all-or-nothing, and a line is never delivered twice
    real_fyi = telling.front_fyi
    def fyi_failing_at(n, how="refuse"):
        """front_fyi as it is, but the n-th call (0-based) cannot file its line."""
        calls = []
        def f(agent, note, *a, **kw):
            calls.append(note)
            if len(calls) - 1 == n:
                if how == "raise": raise RuntimeError("the held store failed")
                return ("held", "its hook cannot fetch held lines")
            return real_fyi(agent, note, *a, **kw)
        return f
    LINES = [f"{shown(30)}: line one, nothing to do", "line two, a notice about nothing", f"{shown(30)}: line three, the release went out"]
    for how in ("refuse", "raise"):
        reset(); ids = put("home-front", *LINES)
        telling.front_fyi = fyi_failing_at(1, how)
        try: tk = take("home-front")
        finally: telling.front_fyi = real_fyi
        check(f"9 filing line 2 fails ({how}): line 1 is filed and gone, lines 2 and 3 go out as one turn, line 1 is not in it", len(tk) == 1 and tk[0]["ids"] == ids[1:] and "line one" not in tk[0]["text"] and "line two" in tk[0]["text"] and "line three" in tk[0]["text"]
              and held.count("home-front") == 1 and "line one" in held_text() and "line two" not in held_text(), (tk, held.count("home-front"), held_text()))
        check(f"9 …the filed line is out of the inbox, the others stay leased until the puller confirms them", set(x["id"] for x in inbox._items()) == set(ids[1:]) and set(inbox._leases()) == set(ids[1:]), (inbox._items(), inbox._leases()))
        check(f"9 …a second poll hands nothing out again (no line twice)", take("home-front") == [], inbox.waiting())
    reset(); ids = put("home-front", *LINES)
    telling.front_fyi = fyi_failing_at(0)
    try: tk = take("home-front")
    finally: telling.front_fyi = real_fyi
    check("9 filing line 1 fails: nothing is filed and the whole digest is a turn", len(tk) == 1 and tk[0]["ids"] == ids and held.count("home-front") == 0, tk)
    reset(); ids = put("home-front", *LINES)
    telling.front_fyi = fyi_failing_at(2)
    try: tk = take("home-front")
    finally: telling.front_fyi = real_fyi
    check("9 filing line 3 fails: lines 1 and 2 are filed, the third goes out alone as itself (no digest header)", len(tk) == 1 and tk[0]["ids"] == ids[2:] and tk[0]["text"].startswith("from: home-peer") and "queued earlier" not in tk[0]["text"] and held.count("home-front") == 2, (tk, held.count("home-front")))
    # push.flush: the same
    reset(); queue("home-front", *LINES)
    telling.front_fyi = fyi_failing_at(1)
    try: rc = push.flush("home-front", digest=HOOK)
    finally: telling.front_fyi = real_fyi
    rest = [json.loads(ln)["text"] for ln in qf("home-front").read_text().splitlines()] if qf("home-front").exists() else []
    check("9 push.flush: line 1 filed and gone from the queue, lines 2 and 3 are what it tries to send (not live here: exit 3, the queue keeps those two)", rc == 3 and rest == LINES[1:] and held.count("home-front") == 1, (rc, rest, held.count("home-front")))
    # the report of the filed lines (the hand-off's ack)
    reset(); ids = put("home-front", *LINES); reported = []
    tk = inbox.take({UID["home-front"]: "home-front"}, known={UID["home-front"]}, only_src="msg", digest=HOOK, on_filed=lambda lines: reported.append([x["id"] for x in lines]))
    check("9 every filed line is reported to on_filed once, as stored (the hand-off's delivery is marked as the ack route marks it)", tk == [] and reported == [ids], (tk, reported))
    reset(); ids = put("home-front", *LINES); reported = []
    telling.front_fyi = fyi_failing_at(2)
    try: tk = inbox.take({UID["home-front"]: "home-front"}, known={UID["home-front"]}, only_src="msg", digest=HOOK, on_filed=lambda lines: reported.append([x["id"] for x in lines]))
    finally: telling.front_fyi = real_fyi
    check("9 …only the lines that were filed are reported, never the one handed out", reported == [ids[:2]] and tk[0]["ids"] == ids[2:], (reported, tk))
    def bad_report(lines): raise RuntimeError("the report failed")
    reset(); ids = put("home-front", *LINES)
    tk = inbox.take({UID["home-front"]: "home-front"}, known={UID["home-front"]}, only_src="msg", digest=HOOK, on_filed=bad_report)
    check("9 a report that fails changes nothing: the lines are filed and gone", tk == [] and held.count("home-front") == 3 and inbox.waiting() == {}, (tk, held.count("home-front")))
    reset(); put("home-front", *LINES); reported = []
    tk = inbox.take({UID["home-front"]: "home-front"}, known={UID["home-front"]}, only_src="msg", digest=lambda n, l, k: [], on_filed=lambda lines: reported.append(1))
    check("9 nothing filed, nothing reported", len(tk) == 1 and reported == [], (tk, reported))

    reset()
    return ran, fails


MARK = "@@front_turn part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"front_turn": part_front_turn, "front_digest": part_front_digest}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        sys.exit(0)
    total = bad = 0
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], stdout=subprocess.PIPE, text=True)
        seen = [l for l in r.stdout.splitlines() if l.startswith(MARK + " ")]
        print("\n".join(l for l in r.stdout.splitlines() if not l.startswith(MARK + " ")))
        if r.returncode != 0 or len(seen) != 1:
            print(f"FAIL part {name} did not end cleanly (exit {r.returncode})"); bad += 1; continue
        _, _, _, n, f = seen[0].split(); total += int(n); bad += int(f)
        print(f"part {name}: {int(n) - int(f)}/{n} checks passed")
    if bad:
        print(f"\n{bad} failures in {total} checks"); sys.exit(1)
    print(f"ok: front_turn scenario, {total} checks")
