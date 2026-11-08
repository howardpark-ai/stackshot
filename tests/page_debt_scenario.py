"""Scenario test for the page-debt call the audit run makes (page_debt.py, server.py _page_debt_pass; stackshot.toml [router] page_debt) on fixture data
- no live store, no network, never the real `claude` (the call's command is a fake script that returns canned JSON) and never the gbrain
CLI (live mode writes through a fake page store with a revision check).

Two pilot projects (`projects/alpha`: keeper, -main agent, a background agent; `projects/gamma`). Covers: with page_debt off nothing runs;
a debt past the grace moves to the keeper as before, now marked as moved with its item, what changed and its writer; the pass has no
start hour; a pass names the audit run it is for and calls one page once per run (two items of one page in one call), again at the next
run; a deadline stops the pages not yet begun and leaves them unmarked; a page whose call raises does not stop the next; the call's argv, environment and message
(the items with their `said` lines, the Current state, the timeline tail); SHADOW writes only page_debt.jsonl (the proposal and whether
it would apply), changes no page, no debt and no routing log, and the 30-minute relay to the keeper is the one it was; LIVE applies a
matching edit to the Current state only with a revision-checked put, reads it back and settles the debt; a `cannot`, JSON that does not
parse, a timeout, a non-zero exit, an old_text that matches none or two places, a new_text that adds a heading, a put refused for a stale
revision, a read back that shows no edit and a page that cannot be read all go to the -main agent in today's relay words, never dropped,
and the debt becomes theirs; the fallback goes first to the page's own agent (frontmatter `agent:`, when it is a live session; the plain relay text
when it is a background agent, the [for Oliver] mark when it is a front one), else to the -main agent (marked), else to the keeper (plain); a
put that times out is read back before anything is decided (the edit on the page = applied and settled; not there = the fallback), while an
explicit refusal falls back at once with no read back; GbrainIO.put tells ok, refused and unknown apart; live stops the 30-minute relay to the keeper; the unit checks of apply_edits; the router's comparison leaves
the page-debt calls out.

    tests/run-suite page_debt        -> exit 0 / 1"""
import json, os, re, sys, time, pathlib, tempfile, logging, subprocess, datetime as dt
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="pagedebttest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
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
S, A, B, X, G = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
                 "44444444-4444-4444-8444-444444444444", "55555555-5555-4555-8555-555555555555")
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "sala", "brain/projects"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/sessions.json").write_text(json.dumps({S: {"name": "work-osprey", "machine": "a", "url": "", "seen": "x"}, A: {"name": "work-osprey-main", "machine": "a", "url": "", "seen": "x"},
                                                      B: {"name": "home-beta", "machine": "a", "url": "", "seen": "x"}, X: {"name": "work-osprey-x", "machine": "a", "url": "", "seen": "x"},
                                                      G: {"name": "work-gamma", "machine": "a", "url": "", "seen": "x"}}))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
page = lambda name, sess, **kw: {"title": name, "name": name, "org": "home", "tags": [], "type": "project", "session": sess, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": f"https://example.invalid/{name}", **kw}
ALPHA_AGENTS = {"work-osprey-main": "Oliver's point of contact", "work-osprey-x": "releases and deploys"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": page("Alpha", "work-osprey", agents=ALPHA_AGENTS, back_agents={"work-osprey-x": "releases and deploys"}),
    "projects/gamma": page("Gamma", "work-gamma", agents={"work-gamma-main": "the contact"}),
    # sub-pages that name an `agent:` as their keeper (pages.keeper_of: role "agent"): a background agent, a front one, and one no session carries
    "projects/alpha/vendor": page("Vendor", "work-osprey-x", role="agent"), "projects/alpha/ops": page("Ops", "work-osprey-main", role="agent"),
    "projects/alpha/old": page("Old", "work-osprey-gone", role="agent"),
    # a project with no agents at all: only its keeper
    "projects/delta": page("Delta", "work-delta"),
    # a page with no agent of its own, served by its hub's -main agent
    "projects/epsilon": page("Epsilon", "work-epsilon", hub="projects/gamma")}}))
FM = "---\ntitle: Alpha\ntype: project\n---\n"
def alpha_page(vendor="- Vendor: the call is open, waiting on the quote."):
    return (FM + "# Alpha\n\n## Current state\n\n" + vendor + "\n- Docs: the draft is with Dana.\n- Docs: the draft is with Dana, second reading.\n\n"
            "## Decisions\n\n- Vendor is chosen by price.\n\n<!-- timeline -->\n- **2026-10-01** | ops-alpha - the vendor call was opened\n- **2026-10-02** | ops-alpha - a quote was asked for\n")
GAMMA = "---\ntitle: Gamma\ntype: project\n---\n# Gamma\n\n## Current state\n\n- Launch: planned for the 20th.\n- Budget: open.\n\n<!-- timeline -->\n- **2026-10-03** | ops-gamma - started\n"
(T / "brain/projects/alpha.md").write_text(alpha_page()); (T / "brain/projects/gamma.md").write_text(GAMMA)
def item(i, proj, owner, status="open", **meta): (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.", "status": status, "metadata": {"owner": owner, "project": proj, **meta}, "updated": 1.0}))
item(1, "projects/alpha", A, next="sign the vendor\nthen tell Dana", needs=["decision"], ask="Sign with the vendor?",
     said=[{"tag": "Acked-by", "quote": "go with the vendor", "msg": "m1", "session": "s", "ts": 1.0, "checked": True}])
item(2, "projects/alpha", X); item(3, "projects/gamma", B)
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
push_log = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered -> ' + a[0])\n")

# the fake `claude`: logs what it was started with, then answers as the control file says (an answer per page, else the default)
CTL, CALLS = T / "fake-control.json", T / "fake-calls.jsonl"
(T / "fake_claude.py").write_text(f'''import sys, os, json, time
ctl = json.load(open({str(CTL)!r}))
stdin = sys.stdin.read()
with open({str(CALLS)!r}, "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "stdin": stdin, "env": sorted(os.environ), "cwd": os.getcwd(), "ls": os.listdir("."), "pid": os.getpid()}}) + "\\n")
mode = ctl["mode"]
if mode == "sleep": time.sleep(30)
if mode == "exit": sys.stderr.write("boom"); sys.exit(3)
if mode == "garbage": print("this is not json at all")
else:
    text = ctl.get("text", "")
    for page, t in (ctl.get("answers") or {{}}).items():
        if "Page: " + page + "\\n" in stdin: text = t
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "duration_ms": 900, "duration_api_ms": 700, "num_turns": 1, "result": text,
                      "total_cost_usd": 0.0123, "usage": {{"input_tokens": 1500, "output_tokens": 120, "cache_read_input_tokens": 40, "service_tier": "standard"}}}}))
''')
def fake(mode, text="", **answers): CTL.write_text(json.dumps({"mode": mode, "text": text, "answers": answers}))
def calls(): return [json.loads(l) for l in CALLS.read_text().splitlines()] if CALLS.exists() else []
def pushes(): return [json.loads(l) for l in push_log.read_text().splitlines()] if push_log.exists() else []
def wait_push(n, t=8.0):
    end = time.time() + t
    while time.time() < end and len(pushes()) < n: time.sleep(0.05)
    return pushes()

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

os.environ.update(ANTHROPIC_API_KEY="[masked secret]", ANTHROPIC_AUTH_TOKEN="tok-test", ANTHROPIC_BASE_URL="http://invalid.test", ANTHROPIC_FOO="x", CLAUDE_CODE_USE_BEDROCK="1", ANTHROPIC_CUSTOM_HEADERS="x-test: 1", CLAUDE_CODE_ENTRYPOINT="cli")
from stackshot.core import config as _cfg; from stackshot.router import routing; from stackshot.router import router; from stackshot.router import page_debt; from stackshot.projects import pages as _pg
_ct_changed_since = _pg.ct_changed_since       # the real one: section 9 patches it
from stackshot.web import server
server._publish = lambda: None; server._PUSH = [sys.executable, str(T / "fakepush.py")]; server._page_ts = lambda key: 0.0
server._cfg.CFG.setdefault("pilot", {})["writer_owes_page"] = True
ZONE = _cfg.tz()
DAY = lambda h, m=0, d=16: dt.datetime(2026, 10, d, h, m, tzinfo=ZONE).timestamp()
def rcfg(**kw): _cfg.CFG["router"] = {"command": [sys.executable, str(T / "fake_claude.py")], "timeout_seconds": 20, **kw}
def brain(k): return (T / f"brain/{k}.md").read_bytes()
def routing_bytes(): return {p.name: p.read_bytes() for p in sorted(routing.DIR.glob("*.jsonl"))}
def reset(): server._owed_save({}); page_debt.write_days({})
def owe(key, writer, gid, what, settle="ct", moves="work-osprey"):
    d = server._owed_load(); d.setdefault(key, {})[writer] = {"ts": time.time() - 31 * 60, "item": gid, "settle": settle, "moves": moves, "what": what}; server._owed_save(d)
def dlog(): return page_debt.read_log()

class FakeIO:
    """gbrain, as the server box would reach it: whole pages with a revision; a put with another revision than the page's is refused."""
    def __init__(self, **pages): self.pages = {k: [v, "r1"] for k, v in pages.items()}; self.puts = []; self.mode = ""; self.gets = 0
    def get(self, slug):
        self.gets += 1
        if self.mode == "unreadable": return None, None
        c, r = self.pages[slug]
        if self.mode == "race": self.pages[slug][1] = r + "x"          # someone else edits the page after this read
        if self.mode == "lost" and self.puts: return c.replace("quote came in", "gone"), r   # the page reads back without the edit
        return c, r
    def put(self, slug, content, rev):
        """→ (state, note) as GbrainIO.put: ok · refused (an explicit error) · unknown (a timeout: the page may or may not have been written)."""
        self.puts.append((slug, rev))
        if rev != self.pages[slug][1]: return "refused", '{"error":"revision conflict: expected ' + rev + '"}'
        if self.mode in ("timeout_lands", "timeout_lost"):
            if self.mode == "timeout_lands": self.pages[slug] = [content, rev + "n"]      # the write got through; only the answer was lost
            return "unknown", "the put timed out"
        self.pages[slug] = [content, rev + "n"]
        return "ok", '{"status":"ok"}'

EDIT_A = json.dumps({"edits": [{"old_text": "- Vendor: the call is open, waiting on the quote.", "new_text": "- Vendor: the quote came in; signing is next."}], "reason": "the quote arrived"})
CANNOT = json.dumps({"cannot": "the items do not say what the vendor decided"})

# ---- 1. the settings: off by default, shadow by default, no start hour
check("[router] page_debt is off, shadow on in the example config, which carries no page_debt_hour", page_debt.enabled() is False and page_debt.shadow() is True
      and _cfg.get("router", "page_debt") is False and _cfg.get("router", "page_debt_shadow") is True and _cfg.get("router", "page_debt_hour") is None and not hasattr(page_debt, "hour"))
_cfg.CFG.pop("router", None)
check("a config with no [router] section reads as off, shadow", (page_debt.enabled(), page_debt.shadow(), page_debt.mode()) == (False, True, "shadow"))
check("a file that still has page_debt_hour is told once that the key is retired", len([n for n in _cfg.notes({"router": {"page_debt_hour": 9}}) if "page_debt_hour is retired" in n]) == 1
      and not any("page_debt_hour" in n for n in _cfg.notes({"router": {"page_debt": True}})))
_pd_note = lambda router, audit: [n for n in _cfg.notes({"router": router, "audit": audit}) if "no pass runs" in n]
check("page_debt on with the audit off, or in agent mode, is told (the audit run makes the call); with the audit on in script mode, or page_debt off, it is not",
      len(_pd_note({"page_debt": True}, {"enabled": False})) == 1 and len(_pd_note({"page_debt": True}, {"enabled": True, "mode": "agent"})) == 1
      and not _pd_note({"page_debt": True}, {"enabled": True}) and not _pd_note({"page_debt": True}, {"enabled": True, "mode": "script"}) and not _pd_note({"page_debt": False}, {"enabled": False}))

# ---- 2. today's move to the keeper, now marked: the relay text is the one it was (page_debt off)
rcfg(); fake("good", EDIT_A)
owe("projects/alpha", A, "a1", "changed (description)"); owe("projects/alpha", X, "a2", "changed (next)", settle="any"); owe("projects/gamma", B, "a3", "closed (done)", moves="work-gamma")
n0 = len(pushes()); k = server._pilot_fallback_tick(); p = wait_push(n0 + 2)[n0:]
lv_a = [n for n in routing.read("projects/alpha") if n.get("kind") == "board" and n.get("live")]; lv_g = [n for n in routing.read("projects/gamma") if n.get("kind") == "board" and n.get("live")]; lv = lv_a + lv_g
check("off: three debts past the grace move; every project is the router's, so they are recorded for the router, one notice each, and pushed to no keeper",
      k == 3 and not p and len(lv) == 3 and all(not n.get("to") for n in lv) and len(lv_a) == 2 and len(lv_g) == 1, (p, lv))
led = server._owed_load()
check("the moved entries are marked (moved), with each debt's item, what changed and its writer",
      led["projects/alpha"]["work-osprey"].get("moved") is True and [(x["item"], x["what"], x["writer"]) for x in led["projects/alpha"]["work-osprey"]["debts"]] == [("a1", "changed (description)", A), ("a2", "changed (next)", X)]
      and led["projects/alpha"]["work-osprey"]["settle"] == "ct" and "moves" not in led["projects/alpha"]["work-osprey"], led["projects/alpha"])
check("off: the pass runs nothing and returns {}", server._page_debt_pass(now=DAY(10)) == {} and not calls() and not (T / "state/router/page_debt.jsonl").exists())

# ---- 3. shadow: one call per page for an audit run, once per run
_cfg.CFG["router"].update(page_debt=True)
check("page_debt on, no shadow key: shadow", page_debt.mode() == "shadow")
before = (brain("projects/alpha"), brain("projects/gamma"), json.dumps(server._owed_load(), sort_keys=True), routing_bytes(), len(pushes()))
fake("good", EDIT_A, **{"projects/gamma": json.dumps({"edits": [{"old_text": "- Launch: planned for the 15th.", "new_text": "- Launch: moved to the 22nd."}], "reason": "moved"})})
RUN1 = "2026-10-16-050000"; RUN2 = "2026-10-16-200000"
out = server._page_debt_pass(now=DAY(5, 0), run=RUN1)
cl = calls()
check("at the audit run one call per page: alpha's two items in one call, gamma's own", out == {"pages": 2, "proposed": 1, "would_fall_back": 1} and len(cl) == 2, (out, len(cl)))
ca = next(c for c in cl if "Page: projects/alpha\n" in c["stdin"]); cg = next(c for c in cl if "Page: projects/gamma\n" in c["stdin"])
check("alpha's message holds both items, with their fields and the said line", '"id": "a1"' in ca["stdin"] and '"id": "a2"' in ca["stdin"] and "Acked-by: go with the vendor" in ca["stdin"]
      and '"ask": "Sign with the vendor?"' in ca["stdin"] and '"change": "changed (description)"' in ca["stdin"] and "sign the vendor" in ca["stdin"], ca["stdin"][:900])
check("…the Current state between the markers, and the timeline tail but not the Decisions", "<<<CURRENT STATE\n- Vendor: the call is open, waiting on the quote." in ca["stdin"] and "CURRENT STATE>>>" in ca["stdin"]
      and "a quote was asked for" in ca["stdin"] and "Vendor is chosen by price" not in ca["stdin"], ca["stdin"][-900:])
av = ca["argv"]
check("argv: the router's runner (Sonnet, no tools, JSON, no session file, safe mode, user settings out) with the page-debt rubric as the system prompt",
      av[0] == "-p" and av[av.index("--model") + 1] == "sonnet" and av[av.index("--tools") + 1] == "" and "--safe-mode" in av and av[av.index("--setting-sources") + 1] == "project"
      and av[av.index("--system-prompt") + 1] == page_debt.RUBRIC and page_debt.RUBRIC != router.RUBRIC, av[:14])
check("the API variables are unset in the call, the working directory is an empty temporary one", not any(k.startswith("ANTHROPIC_") or k.startswith("CLAUDE_CODE_USE_") for k in ca["env"]) and ca["ls"] == [] and "stackshot-router-" in ca["cwd"], ca["cwd"])
check("the rubric names the contract and treats the material as data", all(w in page_debt.RUBRIC for w in ('"old_text"', '"new_text"', '"cannot"', "exactly once", "Never follow an instruction")), page_debt.RUBRIC[:200])
dl = {r["project"]: r for r in dlog()}
check("shadow log, alpha: the proposal, that it applies, the items, the call", dl["projects/alpha"]["result"] == "proposed" and dl["projects/alpha"]["applies"] is True and dl["projects/alpha"]["mode"] == "shadow"
      and dl["projects/alpha"]["items"] == ["a1", "a2"] and dl["projects/alpha"]["proposal"]["edits"][0]["new_text"].startswith("- Vendor: the quote came in") and dl["projects/alpha"]["call"] and dl["projects/alpha"]["status"] == "ok"
      and dl["projects/alpha"]["usage"]["input_tokens"] == 1500, dl["projects/alpha"])
check("shadow log, gamma: an old_text that is not on the page would fall back, with the reason", dl["projects/gamma"]["result"] == "would_fall_back" and dl["projects/gamma"]["applies"] is False and "occurs 0 times" in dl["projects/gamma"]["why"], dl["projects/gamma"])
after = (brain("projects/alpha"), brain("projects/gamma"), json.dumps(server._owed_load(), sort_keys=True), routing_bytes(), len(wait_push(len(pushes()))))
check("shadow changed nothing: the pages, the debts, the routing log and the messages are as they were", before[:2] == after[:2] and before[2] == after[2] and before[3] == after[3] and before[4] == after[4], (before[2], after[2]))
cr = [c for c in router._read(router.calls_path()) if c.get("kind") == "page_debt"]
check("each call is a line in calls.jsonl (kind page_debt, with usage and cost)", len(cr) == 2 and all(c["status"] == "ok" and c["usage"]["input_tokens"] == 1500 and c["cost_usd"] == 0.0123 for c in cr), cr)
check("a second pass for the same run calls nothing", server._page_debt_pass(now=DAY(5, 30), run=RUN1) == {"pages": 0} and len(calls()) == 2)
out = server._page_debt_pass(now=DAY(20, 0), run=RUN2)
check("the next run, the same day, calls again for the debts still unsettled", out["pages"] == 2 and len(calls()) == 4 and page_debt.read_days() == {"projects/alpha": RUN2 + ":shadow", "projects/gamma": RUN2 + ":shadow"}, (out, page_debt.read_days()))

# ---- 4. shadow: the 30-minute relay is unchanged: a new debt moves at once, to the router (every project is the router's since)
from stackshot.router import router_live
reset(); owe("projects/alpha", A, "a1", "changed (next)", settle="any")
n0 = len(pushes()); server._pilot_fallback_tick(); time.sleep(0.4); p = pushes()[n0:]
nb = [n for n in routing.read("projects/alpha") if n.get("kind") == "board" and n.get("live") and not n.get("ruling")][-1:]
check("shadow: the 30-minute move is recorded for the router in today's words and pushed to no keeper", not p and len(nb) == 1 and not nb[0].get("to") and re.match(r"\[board\] a1 changed \(next\) by work-osprey-main — \[home\] item 1 \(projects/alpha\) → https://stackshot\.example\.com/items/a1 — work-osprey-main left its page update undone past 30 min, so the page update is owed$", router_live.stashed(nb[0]["id"]) or ""), (p, nb))

# ---- 5. live: a matching edit is applied, revision-checked, read back, the debt settled
_cfg.CFG["router"].update(page_debt_shadow=False)
check("page_debt_shadow = false is live", page_debt.live() and page_debt.mode() == "live")
reset(); owe("projects/alpha", A, "a1", "changed (description)"); owe("projects/alpha", X, "a2", "changed (next)", settle="any")
n0 = len(pushes()); server._pilot_fallback_tick(); time.sleep(0.5)
check("live: the 30-minute move marks the debt and tells the keeper nothing", len(pushes()) == n0 and server._owed_load()["projects/alpha"]["work-osprey"].get("moved") is True, pushes()[n0:])
io = FakeIO(**{"projects/alpha": alpha_page()}); fake("good", EDIT_A); nc = len(calls()); n0 = len(pushes()); r0 = routing_bytes()
out = server._page_debt_pass(now=DAY(9, 30), io=io)
want = alpha_page("- Vendor: the quote came in; signing is next.")
check("live: applied once, one call", out == {"pages": 1, "applied": 1} and len(calls()) == nc + 1, out)
check("live: one put, with the revision that was read; the page holds the edit in its Current state and is otherwise byte for byte the same", io.puts == [("projects/alpha", "r1")] and io.pages["projects/alpha"][0] == want, (io.puts, io.pages["projects/alpha"][0][:300]))
time.sleep(0.4)
check("live: the debts are settled and nobody is told", "projects/alpha" not in server._owed_load() and len(pushes()) == n0 and routing_bytes() == r0, (server._owed_load(), pushes()[n0:]))
last = dlog()[-1]
check("live: the log says applied", last["result"] == "applied" and last["mode"] == "live" and last["applies"] is True and last["items"] == ["a1", "a2"], last)
check("live: the pages checkout is untouched by the pass (the coordinator owns it)", brain("projects/alpha") == alpha_page().encode())

# ---- 6. live: whatever cannot be applied goes to -main, in today's words, never dropped
def fallback_case(name, mode, text, why_has, *, io_mode="", timeout=20, page=None, key="projects/alpha", writer=A, gid="a1", main="work-osprey-main", writes=False, no_call=False):
    reset(); rcfg(page_debt=True, page_debt_shadow=False, timeout_seconds=timeout)
    owe(key, writer, gid, "changed (description)", moves="work-osprey" if key.endswith("alpha") else "work-gamma"); server._pilot_fallback_tick(); time.sleep(0.4)
    io = FakeIO(**{"projects/alpha": page or alpha_page(), "projects/gamma": GAMMA}); io.mode = io_mode
    fake(mode, text); n0, nc = len(pushes()), len(calls())
    out = server._page_debt_pass(now=DAY(9, 40), io=io); p = wait_push(n0 + 1)[n0:]
    last = dlog()[-1]; led = server._owed_load().get(key, {})
    orig = page or (GAMMA if key.endswith("gamma") else alpha_page())
    check(f"{name}: falls back" + ("" if writes else ", nothing is written to the page"), out.get("fallback") == 1 and last["result"] == "fallback" and last["applies"] is False and (writes or io.pages[key][0] == orig), (out, last))
    if no_call: check(f"{name}: no call was started", len(calls()) == nc, len(calls()) - nc)
    check(f"{name}: the reason is logged ({why_has!r}) and -main is named", why_has in last["why"] and last["to"] == main, last)
    check(f"{name}: -main gets one message in today's relay words, marked for the owner, with the reason, the item and its notice",
          len(p) == 1 and p[0][0] == main and p[0][1].startswith(f"{server._FOR_OWNER} [board] 1 page update on {key} is yours to write: the writer left it undone past 30 min and the audit's page call could not write it (")
          and "or hand it to the agent that keeps the page." in p[0][1].split("\n")[0]
          and why_has in p[0][1].split("\n")[0] and re.search(rf"^- {gid} changed \(description\) by \S+ — \[home\] item \d+ \({key}\) → https://stackshot\.example\.com/items/{gid} · notice [0-9a-f]{{6}}$", p[0][1], re.M), p)
    check(f"{name}: the debt is the -main agent's now (not dropped, not moved again), the keeper is not told", list(led) == [main] and "moved" not in led[main] and led[main]["item"] == gid and led[main]["settle"] == "ct"
          and not any(m[0] in ("work-osprey", "work-gamma") for m in pushes()[n0:]), (led, pushes()[n0:]))
    nid = re.search(r"notice ([0-9a-f]{6})", p[0][1]).group(1) if p else ""
    n = next((x for x in routing.read(key) if x["id"] == nid), {})
    check(f"{name}: the routing-log notice is ruled passed to -main, so no keeper is reminded", n.get("ruling") == "passed" and n.get("ruled_to") == main and n.get("ruled_by") == "stackshot (auto)", n)
    return io, last
fallback_case("cannot", "good", CANNOT, "the items do not say what the vendor decided")
fallback_case("bad JSON", "garbage", "", "did not parse")
fallback_case("prose, no JSON object", "good", "I would change the vendor line.", "did not parse")
fallback_case("timeout", "sleep", "", "timed out", timeout=3)
fallback_case("non-zero exit", "exit", "", "the call failed")
fallback_case("old_text on no line", "good", json.dumps({"edits": [{"old_text": "- Vendor: the call is shut.", "new_text": "x"}], "reason": "r"}), "occurs 0 times")
fallback_case("old_text on two lines", "good", json.dumps({"edits": [{"old_text": "- Docs: the draft is with Dana", "new_text": "- Docs: done"}], "reason": "r"}), "occurs 2 times")
fallback_case("old_text in the timeline, not the Current state", "good", json.dumps({"edits": [{"old_text": "a quote was asked for", "new_text": "x"}], "reason": "r"}), "occurs 0 times")
fallback_case("a new_text that adds a heading", "good", json.dumps({"edits": [{"old_text": "- Vendor: the call is open, waiting on the quote.", "new_text": "## Decisions\n- x"}], "reason": "r"}), "adds a heading")
fallback_case("no edit and no cannot", "good", json.dumps({"edits": [], "reason": "nothing"}), "holds no edit")
fallback_case("a page without a Current state", "good", EDIT_A, "no Current state", page="---\ntitle: Alpha\n---\n# Alpha\n\nNo sections.\n\n<!-- timeline -->\n- x\n")
io, last = fallback_case("a put refused for a stale revision", "good", EDIT_A, "the page write was refused", io_mode="race")
check("…and the refused put changed nothing, and the page was not read back (an explicit refusal is not an unknown outcome)", io.pages["projects/alpha"][0] == alpha_page() and len(io.puts) == 1 and io.gets == 1, (io.gets, len(io.puts)))
check("…its reason in the log says refused, not applied", last["why"].startswith("the page write was refused") and last["result"] == "fallback" and last["applies"] is False, last)
io, last = fallback_case("a read back without the edit", "good", EDIT_A, "check the page", io_mode="lost", writes=True)
fallback_case("a page that cannot be read", "good", EDIT_A, "the page could not be read", io_mode="unreadable", no_call=True)
fallback_case("gamma, whose -main agent is its own", "good", CANNOT, "the items do not say", key="projects/gamma", writer=B, gid="a3", main="work-gamma-main")

# ---- 6b. who a fallback goes to: the page's own agent (its frontmatter `agent:`, when live), else the -main agent, else the keeper; the
#          [for Oliver] mark only when the recipient is a front agent
def route_case(name, key, to, marked, *, moves="work-osprey", mode="good", text=CANNOT, io_mode="", ruled=True):
    reset(); rcfg(page_debt=True, page_debt_shadow=False)
    owe(key, A, "a1", "changed (description)", moves=moves); server._pilot_fallback_tick(); time.sleep(0.4)
    io = FakeIO(**{key: alpha_page()}); io.mode = io_mode
    fake(mode, text); n0 = len(pushes())
    out = server._page_debt_pass(now=DAY(9, 45), io=io); p = wait_push(n0 + 1)[n0:]
    last = dlog()[-1]; led = server._owed_load().get(key, {}); first = p[0][1].split("\n")[0] if p else ""
    check(f"{name}: falls back to {to}, in one message", out.get("fallback") == 1 and last["to"] == to and len(p) == 1 and p[0][0] == to, (out, last, p))
    check(f"{name}: the message {'opens with the [for Oliver] mark' if marked else 'is the plain relay text, no mark'}",
          first.startswith(server._FOR_OWNER + f" [board] 1 page update on {key} is yours to write") if marked else first.startswith(f"[board] 1 page update on {key} is yours to write"), first)
    check(f"{name}: the debt is {to}'s now, not moved again", list(led) == [to] and "moved" not in led[to] and led[to]["settle"] == "ct", led)
    nid = re.search(r"notice ([0-9a-f]{6})", p[0][1]).group(1) if p else ""
    n = next((x for x in routing.read(key) if x["id"] == nid), {})
    check(f"{name}: the routing-log notice is " + ("ruled passed to the recipient by stackshot (auto)" if ruled else "left for the keeper to rule"),
          (n.get("ruling") == "passed" and n.get("ruled_to") == to and n.get("ruled_by") == "stackshot (auto)") if ruled else not n.get("ruling"), n)
    return p, io, last
p, _io, _l = route_case("a page that names a live background agent", "projects/alpha/vendor", "work-osprey-x", False)
check("…and its message says the agent keeps the page", "Write the Current state: you keep this page." in p[0][1].split("\n")[0], p[0][1][:300])
route_case("a page that names a front agent", "projects/alpha/ops", "work-osprey-main", True)
route_case("a page whose agent is not a live session: the -main agent", "projects/alpha/old", "work-osprey-main", True)
route_case("a page with no agent: the -main agent", "projects/alpha", "work-osprey-main", True)
route_case("a page with no agent of its own: its hub's -main agent", "projects/epsilon", "work-gamma-main", True, moves="work-epsilon")
# no agent on the page, none on a hub, and no general -main agent on any page: nobody can take the debts; they stay moved for the next audit run's call, and no keeper is told
reset(); rcfg(page_debt=True, page_debt_shadow=False)
owe("projects/delta", A, "a1", "changed (description)", moves="work-delta"); server._pilot_fallback_tick(); time.sleep(0.4)
io = FakeIO(**{"projects/delta": alpha_page()}); fake("good", CANNOT); n0 = len(pushes())
out = server._page_debt_pass(now=DAY(9, 45), io=io); time.sleep(0.4); last = dlog()[-1]; led = server._owed_load().get("projects/delta", {})
check("no agent anywhere: the page and its hub list none and no general -main agent exists: the fallback tells nobody, a keeper included", out.get("fallback") == 1 and last["to"] == "" and len(pushes()) == n0, (out, last, pushes()[n0:]))
check("…and the debt stays moved (to the keeper's name, which nobody reads), for the next audit run's call", list(led) == ["work-delta"] and led["work-delta"].get("moved") is True, led)
route_case("a page's agent also gets a failed write (a put that timed out and left no edit)", "projects/alpha/vendor", "work-osprey-x", False, text=EDIT_A, io_mode="timeout_lost")
check("_page_agent: a live agent's name, '' for a hub page, a page with no agent, a sub-page of a keeper and an agent no session carries",
      (server._page_agent("projects/alpha/vendor"), server._page_agent("projects/alpha"), server._page_agent("projects/delta"), server._page_agent("projects/alpha/none"), server._page_agent("projects/alpha/old"))
      == ("work-osprey-x", "", "", "", ""))

# ---- 6c. a put that timed out: the page is read back before anything is decided
reset(); rcfg(page_debt=True, page_debt_shadow=False)
owe("projects/alpha", A, "a1", "changed (description)"); server._pilot_fallback_tick(); time.sleep(0.4)
io = FakeIO(**{"projects/alpha": alpha_page()}); io.mode = "timeout_lands"; fake("good", EDIT_A); n0 = len(pushes())
out = server._page_debt_pass(now=DAY(9, 50), io=io); time.sleep(0.4); last = dlog()[-1]
check("a put that timed out and whose read back shows the edit: applied, the page is read back (two reads)", out == {"pages": 1, "applied": 1} and last["result"] == "applied" and io.gets == 2 and len(io.puts) == 1
      and io.pages["projects/alpha"][0] == alpha_page("- Vendor: the quote came in; signing is next."), (out, last, io.gets))
check("…the debts are settled, nobody is told, the log notes that the answer was missing", "projects/alpha" not in server._owed_load() and len(pushes()) == n0 and "got no answer" in last["why"] and "taken as written" in last["why"], (server._owed_load(), last["why"]))
io, last = fallback_case("a put that timed out and whose read back shows no edit", "good", EDIT_A, "got no answer", io_mode="timeout_lost")
check("…the page was read back before the fallback, and the log says the edit is not on the page", io.gets == 2 and "a read back does not show the edit" in last["why"] and last["result"] == "fallback", (io.gets, last["why"]))

# GbrainIO.put tells a refusal from an unknown outcome (the CLI is faked)
import subprocess as _sp; from stackshot.projects import rename_page as _rp
_gb = _rp.gb
def gbio(rc_out=None, exc=None):
    def f(args, stdin=None):
        if exc: raise exc
        return rc_out
    _rp.gb = f
    try: return page_debt.GbrainIO().put("projects/alpha", "x", "r1")
    finally: _rp.gb = _gb
check("GbrainIO.put: a clean answer is ok", gbio((0, '{"status":"ok"}'))[0] == "ok")
check("GbrainIO.put: an error in the answer, or a non-zero exit, is a refusal", gbio((0, '{"error": "revision conflict"}'))[0] == "refused" and gbio((1, "revision conflict"))[0] == "refused")
check("GbrainIO.put: a timeout, a kill by a signal and an unexpected failure are unknown, not refusals",
      gbio(exc=_sp.TimeoutExpired("gbrain", 120))[0] == "unknown" and gbio((-9, ""))[0] == "unknown" and gbio(exc=OSError("boom"))[0] == "unknown")
check("put_state: the older (bool, note) form still reads", page_debt.put_state((True, "x"))[0] == "ok" and page_debt.put_state((False, "x"))[0] == "refused" and page_debt.put_state(("unknown", "x"))[0] == "unknown")

# ---- 7. live: several debts of one page, all of them go in the one message
reset(); rcfg(page_debt=True, page_debt_shadow=False)
owe("projects/alpha", A, "a1", "changed (description)"); owe("projects/alpha", X, "a2", "changed (next)", settle="any"); server._pilot_fallback_tick(); time.sleep(0.4)
fake("good", CANNOT); n0 = len(pushes()); server._page_debt_pass(now=DAY(10), io=FakeIO(**{"projects/alpha": alpha_page()})); p = wait_push(n0 + 1)[n0:]
check("two debts of one page: one message for the two, listing each with its notice", len(p) == 1 and p[0][1].startswith(f"{server._FOR_OWNER} [board] 2 page updates on projects/alpha are yours to write: the writers left them undone") and "- a1 changed (description)" in p[0][1] and "- a2 changed (next)" in p[0][1], p)

# ---- 8. the mark (the day when a pass names no run): shadow and live count apart; a crash before the call does not repeat it
reset(); rcfg(page_debt=True, page_debt_shadow=True); owe("projects/alpha", A, "a1", "changed (description)"); server._pilot_fallback_tick(); time.sleep(0.3)
fake("good", EDIT_A); nc = len(calls()); server._page_debt_pass(now=DAY(11)); server._page_debt_pass(now=DAY(12))
check("shadow: one call that day", len(calls()) == nc + 1)
_cfg.CFG["router"].update(page_debt_shadow=False)
io = FakeIO(**{"projects/alpha": alpha_page()}); out = server._page_debt_pass(now=DAY(13), io=io)
check("switching shadow to live the same day calls again, and applies", out == {"pages": 1, "applied": 1} and len(calls()) == nc + 2, out)
check("the day marks are in the state dir, per page and mode", page_debt.read_days() == {"projects/alpha": "2026-10-16:live"}, page_debt.read_days())

# ---- 9. the debts a keeper already settled are not called for
reset(); owe("projects/alpha", A, "a1", "changed (description)"); server._pilot_fallback_tick(); time.sleep(0.3)
server._page_ts = lambda key: time.time() + 500; _pg.ct_changed_since = lambda key, ts: True
nc = len(calls()); out = server._page_debt_pass(now=DAY(14, d=18))
check("a debt whose page changed meanwhile is settled by the ledger and costs no call", out == {"pages": 0} and len(calls()) == nc and "projects/alpha" not in server._owed_load(), (out, server._owed_load()))
server._page_ts = lambda key: 0.0; _pg.ct_changed_since = lambda key, ts: False
reset(); owe("projects/alpha", A, "a1", "changed (description)"); server._pilot_fallback_tick(); time.sleep(0.3)
d = server._owed_load(); d["projects/gamma"] = {"work-gamma": {"ts": time.time(), "item": "a3"}}; server._owed_save(d)
nc = len(calls()); out = server._page_debt_pass(now=DAY(14, d=19), io=FakeIO(**{"projects/alpha": alpha_page()}))
check("only moved debts are called for: the keeper's own debt is not", out == {"pages": 1, "applied": 1} and "projects/gamma" in server._owed_load(), (out, server._owed_load()))

# ---- 10. off again
reset(); rcfg(page_debt=False); owe("projects/alpha", A, "a1", "changed (description)"); server._pilot_fallback_tick(); time.sleep(0.3)
nc = len(calls()); check("off again: nothing runs", server._page_debt_pass(now=DAY(10, d=20)) == {} and len(calls()) == nc)

# ---- 10b. the audit run's pass: a deadline leaves the pages unmarked, a page whose call raises does not stop the next, the server's write for the pages stage
class BoomIO(FakeIO):
    """alpha's page cannot be read (the read raises); gamma's is fine."""
    def get(self, slug):
        if slug == "projects/alpha": raise RuntimeError("boom")
        return super().get(slug)
def two_debts():
    reset(); owe("projects/alpha", A, "a1", "changed (description)"); owe("projects/gamma", B, "a3", "closed (done)", moves="work-gamma"); server._pilot_fallback_tick(); time.sleep(0.4)
rcfg(page_debt=True, page_debt_shadow=False); fake("good", EDIT_A); two_debts()
nc = len(calls()); out = server._page_debt_pass(now=DAY(5), run="r-late", deadline=time.time() - 1, io=FakeIO(**{"projects/alpha": alpha_page()}))
check("a deadline already past: no page is begun, both are counted as left, no call and no mark", out == {"pages": 0, "left": 2} and len(calls()) == nc and page_debt.read_days() == {}, (out, page_debt.read_days()))
import io as _io, contextlib
buf = _io.StringIO()
with contextlib.redirect_stderr(buf):
    out = server._page_debt_pass(now=DAY(5), run="r-boom", deadline=time.time() + 600, io=BoomIO(**{"projects/alpha": alpha_page(), "projects/gamma": brain("projects/gamma").decode()}))
check("a page whose call raises is counted as error and the next page is still called", out["pages"] == 2 and out.get("error") == 1 and sum(v for k, v in out.items() if k not in ("pages", "error")) == 1, out)
check("…the failure is logged and the failed page keeps its mark, so it is not called again in this run", "page-debt call for projects/alpha failed: RuntimeError: boom" in buf.getvalue() and page_debt.read_days().get("projects/alpha") == "r-boom:live", (buf.getvalue(), page_debt.read_days()))
reset()           # no debt left: the server's own page store (the gbrain CLI) is never reached
st, d = server._client_post("m", "page-debt", {"run": "2026-10-16-050000"})
check("POST /client/page-debt runs the pass for the named run and answers its mode and counts", st == 200 and d == {"enabled": True, "mode": "live", "counts": {"pages": 0}}, (st, d))
GOOD = "2026-10-16-050000"
check("…a body with no run, an empty run, a run that is not the audit's stamp shape, or a bad deadline is refused", [server._client_post("m", "page-debt", b)[0] for b in ({}, {"run": " "}, {"run": "x" * 41}, {"run": "r-http"}, {"run": GOOD + "\n"}, {"run": " " + GOOD}, {"run": 20261016050000}, {"run": GOOD, "deadline": "soon"})] == [400] * 8)
check("…a deadline of NaN or infinity is refused, not read as no deadline", [server._client_post("m", "page-debt", {"run": GOOD, "deadline": v})[0] for v in ("nan", "inf", "-inf", float("nan"), float("inf"))] == [400] * 5)
check("…the stamp the audit run writes passes the route's check", server._client_post("m", "page-debt", {"run": __import__("stackshot.audit.audit_run", fromlist=["_"])._stamp_of(1.8e9), "deadline": time.time() + 60})[0] == 200)
rcfg(page_debt=False)
st, d = server._client_post("m", "page-debt", {"run": "2026-10-16-200000"})
check("…with [router] page_debt off it makes no call and says so", st == 200 and d == {"enabled": False, "mode": "", "counts": {}}, (st, d))

# ---- 11. apply_edits, unit checks
P = alpha_page()
def ap(edits, content=P): return page_debt.apply_edits(content, edits)
ok, why = ap([{"old_text": "- Vendor: the call is open, waiting on the quote.", "new_text": "- Vendor: signed."}, {"old_text": "second reading", "new_text": "third"}])
check("apply_edits: two edits in one section apply, the rest of the page byte for byte", ok == P.replace("- Vendor: the call is open, waiting on the quote.", "- Vendor: signed.").replace("second reading", "third") and why == "", (why, ok))
check("apply_edits: two edits that overlap are refused", ap([{"old_text": "the call is open", "new_text": "a"}, {"old_text": "open, waiting", "new_text": "b"}])[0] is None)
check("apply_edits: an old_text outside the Current state (Decisions) is refused", "occurs 0 times" in ap([{"old_text": "Vendor is chosen by price", "new_text": "x"}])[1])
check("apply_edits: a new_text with the timeline marker or a fence is refused", ap([{"old_text": "Budget", "new_text": "<!-- timeline -->"}], GAMMA)[0] is None and ap([{"old_text": "Budget", "new_text": "<!-- gbrain:facts:begin -->"}], GAMMA)[0] is None)
check("apply_edits: an empty old_text, an identical text, a non-string and more than six edits are refused", all(ap(e)[0] is None for e in (
      [{"old_text": " ", "new_text": "x"}], [{"old_text": "Budget: open.", "new_text": "Budget: open."}], [{"old_text": 3, "new_text": "x"}], [{"old_text": f"w{k}", "new_text": "x"} for k in range(7)], "no", [])))
FENCED = GAMMA.replace("- Budget: open.\n", "- Budget: open.\n<!-- gbrain:facts:begin -->\n| a | b |\n<!-- gbrain:facts:end -->\n")
check("apply_edits: text inside a facts fence is refused", ap([{"old_text": "| a | b |", "new_text": "| c |"}], FENCED)[0] is None)
check("apply_edits: a '###' line in a new_text is allowed, a sub-heading is not a section of the page", ap([{"old_text": "- Budget: open.", "new_text": "### Budget\n- open"}], GAMMA)[0] is not None)
check("section_span: the Current state ends at the next ## heading and never reaches the timeline", (lambda s: alpha_page()[s[0]:s[1]].startswith("\n- Vendor") and "## Decisions" not in alpha_page()[s[0]:s[1]])(page_debt.section_span(alpha_page())))
check("parse_proposal: a fence and a line of prose around the JSON are fine; both forms; neither is None", page_debt.parse_proposal("On testbox.\n```json\n" + EDIT_A + "\n```")[0] == "edits" and page_debt.parse_proposal(CANNOT) == ("cannot", "the items do not say what the vendor decided")
      and page_debt.parse_proposal("[1,2]") is None and page_debt.parse_proposal('{"edits": "x"}') is None and page_debt.parse_proposal("") is None)

# ---- 12. what settles a debt: the compiled truth is everything above the `## Timeline` heading (a stray marker above the last Current-state bullets does not hide them)
STRAY = ("---\ntitle: Stray\ntype: project\ningested_at: 'x'\n---\n\n# Stray\n\n## Current state\n\n- Open: the link opens a tab.\n\n<!-- timeline -->\n\n"
         "- **Mobile app:** manifest live.\n- **Open: help link:** clicking opens a tab.\n\n## Timeline\n\n- **2026-10-21** | ops-alpha - started\n")
ct = _pg.compiled_truth
check("compiled_truth: a bullet between the marker and `## Timeline` counts, the marker line and the timeline do not",
      "clicking opens a tab" in ct(STRAY) and "<!-- timeline -->" not in ct(STRAY) and "started" not in ct(STRAY) and "Timeline" not in ct(STRAY), ct(STRAY))
check("compiled_truth: a page with the marker and no `## Timeline` heading still ends at the marker",
      ct(GAMMA).endswith("- Budget: open.") and "started" not in ct(GAMMA), ct(GAMMA))
check("compiled_truth: moving the marker alone, or a line under `## Timeline`, changes nothing",
      ct(STRAY.replace("<!-- timeline -->\n\n", "").replace("## Current state\n", "## Current state\n<!-- timeline -->\n")) == ct(STRAY) and ct(STRAY + "- **2026-10-22** | x - y\n") == ct(STRAY))
brain = T / "brain"; key = "projects/stray"; t0 = 1_800_000_000
def git(*a, at=None):
    env = dict(os.environ, GIT_AUTHOR_DATE=f"{at} +0000", GIT_COMMITTER_DATE=f"{at} +0000") if at else None
    return subprocess.run(["git", "-C", str(brain), "-c", "user.name=t", "-c", "user.email=t@t.invalid", *a], capture_output=True, text=True, env=env)
git("init", "-q"); (brain / "projects/stray.md").write_text(STRAY, encoding="utf-8"); git("add", "-A"); git("commit", "-qm", "first", at=t0 - 3000)
stray_edit = STRAY.replace("clicking opens a tab.", "clicking is the design.")
(brain / "projects/stray.md").write_text(stray_edit, encoding="utf-8"); git("add", "-A"); git("commit", "-qm", "second", at=t0 - 14)
check("ct_changed_since: an edit below the marker made 14 s before the board change settles it (a page write up to five minutes before counts)",
      _ct_changed_since(key, t0) is True)
check("ct_changed_since: the same edit seen from a board change an hour later is not this change's page write (before the slack window)",
      _ct_changed_since(key, t0 + 3600) is False)
(brain / "projects/stray.md").write_text(stray_edit + "- **2026-10-22** | ops-alpha - a timeline line\n", encoding="utf-8"); git("add", "-A"); git("commit", "-qm", "v3", at=t0 + 20)
check("ct_changed_since: a line under `## Timeline` alone does not settle a later change",
      _ct_changed_since(key, t0 + 3600) is False)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
