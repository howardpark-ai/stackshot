"""Scenario test for the script post kind a pane waiting in its terminal is filed with (`client.py post terminal-prompt open|clear`, POST /client/terminal-prompt;
) — fixture data, no live store, no network, no server process (the server module is imported and called in-process, on a temporary config; the session
registry is a fixture file in a temporary directory, never the host's).

Covers: open (the item id alone on stdout, exit 0; one open item, marked metadata.terminal_prompt with the session's name, subject "<session> is waiting for your answer
in its terminal", the owner the mover and the item in his Your move list, state your-step with the step "Answer <session>'s question in its terminal", p1, next "<owner>: open
<the pane's address> and answer: <question>", under the session's project from the registry, else projects/example-two, the project's -main agent the keeper of record, the script
recorded as creator); a second open for the session changes the question and files nothing, the same question again writes nothing; a session id, a transcript id, an old name
and the current name reach one item; clear (closes the session's open item: outcome done, reason "the pane stopped waiting", a state dropped, a description rewritten to the end
state), clear with none open or for an unknown session a no-op that answers 200, an open again after a clear files a new item; one session's item never touched by another's calls;
the question refused when empty, over 200 characters or over several lines, a missing or owner-named sender, a bad action, with nothing filed; a question with alarming words and
one that overruns the next-line limit (cut at a word with an ellipsis) filed; the page-debt rules (the script owes no page, the owner and the -main agent are charged none, and
nothing is told to any session); a failed state write closes the item again rather than leaving it half made; client.py (usage, exit codes, no token, a server not reached) and its docs.

    tests/run-suite terminal_prompt        → exit 0 / 1"""
import contextlib, io, json, os, re, socket, sys, pathlib, logging, threading
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="terminaltest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = ""', f'session_links = "{tmp}/sala"', 1); assert f'session_links = "{tmp}/sala"' in toml   # the fixture registry, never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1       # the person the tools speak of
toml, n = re.subn(r'(?m)^session_view = ""', 'session_view = "https://sala.example.org/#s={name}"', toml, count=1); assert n == 1       # the example-owner instance links a pane to sala's web view (its live config)
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "sala/a", "state/anchor-hub", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")

def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
# sala ids (S) and claude transcript ids (Tr). The builder of alpha carries two transcript ids (eng_old, eng_new), one per run.
S = {"eng": uid(101), "main": uid(102), "loner": uid(103), "nofront": uid(104), "other": uid(105), "slug": uid(106), "longname": uid(107)}
Tr = {"eng_old": uid(201), "eng_new": uid(202), "main": uid(203), "loner": uid(204), "nofront": uid(205), "other": uid(206), "slug": uid(207), "longname": uid(208)}
def row(key, name, project_key=None, aliases=(), transcripts=(), **kw):
    return {"id": S[key], "name": name, "aliases": list(aliases), "project": None, "project_key": project_key, "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": name,
            "cwd": "/home/user", "state": "live", "created": "2026-10-21T21:00:00Z", "retired_at": None,
            "transcripts": [{"id": Tr[t], "machine": "a", "at": f"2026-10-21T2{i}:00:00Z", "why": "import" if i == 1 else "fresh"} for i, t in enumerate(transcripts, 1)], **kw}
LONGNAME = "home-sparrow-" + "n" * 60            # a pane name that would make the server's own subject over the 80-character limit
ROWS = [row("eng", "home-sparrow-builder", "projects/alpha", aliases=["home-sparrow-eng"], transcripts=["eng_old", "eng_new"]),
        row("main", "home-sparrow-main", "projects/alpha", transcripts=["main"]),
        row("loner", "home-loner", None, transcripts=["loner"]),                         # no project: filed under projects/example-two
        row("nofront", "home-nofront", "projects/gamma", transcripts=["nofront"]),       # a project that lists no front agent: projects/example-two as well
        row("other", "home-other", "projects/alpha", transcripts=["other"]),
        row("slug", "home-slug", None, transcripts=["slug"], project="alpha"),
        row("longname", LONGNAME, "projects/alpha", transcripts=["longname"])]            # the project by its bare name only
(T / "sala/a/session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {r["id"]: r for r in ROWS}}), encoding="utf-8")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-docs: keeps the docs\n  home-sparrow-main: talks to Oliver\n  background:\n    home-sparrow-builder: builds\nstatus: active")
page("projects/example-two.md", "type: project\ntitle: Example Two\ndisplay-name: example-two\nagents:\n  example-two-main: talks to Oliver\nstatus: active")
page("projects/gamma.md", "type: project\ntitle: Gamma\ndisplay-name: home-gamma\nstatus: active")
import time
for pg in (T / "brain").rglob("*.md"): os.utime(pg, (time.time() - 8 * 3600, time.time() - 8 * 3600))      # the pages are older than any debt (and the 5-minute slack), so a debt charged by a write would stand
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

import pages as p
p.cmd_registry(quiet=True)
import sessions_registry as sr
sr.TTL = 0
import server, client, model as M, home as H_
server._publish = lambda: None
pushed = []                           # every delivery to a session the server would make (a notice to the keeper, a relay): none is expected
class _FakePush:
    pass
_orig_run = server.subprocess.run
def _fake_run(cmd, *a, **kw):
    if isinstance(cmd, list) and any(str(x).endswith("push.py") or str(x).endswith("fakepush.py") for x in cmd):
        pushed.append(list(cmd)[-2:]); return server.subprocess.CompletedProcess(cmd, 0, "delivered\n", "")
    return _orig_run(cmd, *a, **kw)
server.subprocess.run = _fake_run
from starlette.testclient import TestClient
me = socket.gethostname(); tok = open(client.mint(me)).read().strip(); HD = {"Authorization": "Bearer " + tok}
SALA = "https://sala.example.org/#s="
def items(): return sorted(p_.stem for d in (T / "store").iterdir() if d.is_dir() for p_ in d.glob("*.json") if p_.stem.isdigit())
def item(shown): return server._load(server._norm_id(shown))
def tp(action, session="home-sparrow-builder", question="May I run the migration against the staging database?", sender="sala-hook", machine=None, **kw):
    b = {"action": action, "session": session, "sender": sender}
    if question is not None: b["question"] = question
    b.update(kw)
    return server._client_post(machine or me, "terminal-prompt", {k: v for k, v in b.items() if v is not None})
def nxt(name, question): return f"Oliver: open {SALA}{name} and answer: `{question}`"
def open_for(session): return [g for g in server._terminal_open_items(session)]
n0 = len(items())

# ---- 1. open: the item and its shape
Q = "May I run the migration against the staging database?"
st, out = tp("open", "home-sparrow-builder", Q)
check("open: 200 with the item id as shown, the session's name, the project, repeat false", st == 200 and out["session"] == "home-sparrow-builder" and out["project"] == "projects/alpha" and out["repeat"] is False
      and out["item"] == server._gh.shown(server._norm_id(out["item"])), (st, out))
it = item(out["item"]); m = it["metadata"]
check("the item is open, filed under the session's project from the registry, marked with the resolved session name", it["status"] == "open" and m["project"] == "projects/alpha" and m["terminal_prompt"] == "home-sparrow-builder", (it["status"], m))
check("…the subject names the session and what it waits for", it["subject"] == "[home] home-sparrow-builder is waiting for your answer in its terminal", it["subject"])
check("…priority p1; the owner is the mover; state your-step with the one-line step, no command", m.get("priority") == "p1" and m.get("mover") == "Oliver" and m.get("state") == "your-step"
      and m.get("step") == "Answer home-sparrow-builder's question in its terminal" and "`" not in m["step"], m)
check("…next is the one line that links the pane and carries the question", m.get("next") == nxt("home-sparrow-builder", Q), m.get("next"))
check("…the keeper of record is the project's -main agent (not the background builder that is asking), the script is the creator", server._session_label(m["owner"]) == "home-sparrow-main"
      and it["filed_by"] == f"sala-hook via a script on {me}", (m["owner"], it.get("filed_by")))
check("…the description is bullets that say who waits and who opened it", it["description"].splitlines()[0] == "- home-sparrow-builder is waiting in its terminal for Oliver's answer"
      and it["description"].splitlines()[-1] == f"- Opened by sala-hook (a script on {me}); it closes when the pane stops waiting", it["description"])
mod = M.derive(it)
check("…the item is alive with the owner as the mover: it is in his Your move list", H_.list_of(mod) == H_.YOUR_MOVE and mod.state == M.ALIVE, (mod.state, mod.mover))
check("…and nothing else is made or told: one item, no message to any session", len(items()) == n0 + 1 and pushed == [], (len(items()) - n0, pushed))
check("…the row owes no page: no debt is charged to the script, the keeper of record, the page's keeper or anyone (the page is older than the item, so a debt would stand)", server._owed_load() == {}, server._owed_load())
check("…the item is in the brief as the owner's", out["item"] in server.stackshot_get(out["item"]) and "your-step" in server.stackshot_get(out["item"]), server.stackshot_get(out["item"])[:300])

# ---- 1b. a long pane name: the server's own subject is cut to the limit, never refused
st, outl = tp("open", LONGNAME, Q)
itl = item(outl["item"]) if st == 200 else {"subject": ""}
check("a pane name too long for the subject limit still opens: 200, a subject of at most 80 characters that keeps the scope prefix and the words after the name",
      st == 200 and len(itl["subject"]) <= 80 and itl["subject"].startswith("[home] home-sparrow-n") and itl["subject"].endswith(" …" + " is waiting for your answer in its terminal"), (st, outl, itl["subject"]))
check("…the marker keeps the whole name", itl["metadata"]["terminal_prompt"] == LONGNAME if st == 200 else False)
st, _c = tp("clear", LONGNAME, None)
check("…and it clears", st == 200 and _c["cleared"], (st, _c))

# ---- 2. a second open: the question changes, nothing is created
n1 = len(items()); Q2 = "Run it now, or wait for the nightly window?"
st, out2 = tp("open", "home-sparrow-builder", Q2)
check("a second open for the session answers the same item, marked a repeat, and files nothing", st == 200 and out2["item"] == out["item"] and out2["repeat"] is True and len(items()) == n1, (st, out2))
m2 = item(out["item"])["metadata"]
check("…its next line is the new question, one line only (the old one is replaced, not kept beside it)", m2["next"] == nxt("home-sparrow-builder", Q2) and len([l for l in m2["next"].splitlines() if l.strip()]) == 1, m2.get("next"))
check("…the state, step, mover and mark are as they were", m2["state"] == "your-step" and m2["mover"] == "Oliver" and m2["terminal_prompt"] == "home-sparrow-builder" and m2["step"] == m["step"], m2)
upd = item(out["item"]).get("updated")
st, out2b = tp("open", "home-sparrow-builder", Q2)
check("the same question again writes nothing (the item's clock does not move)", st == 200 and out2b["repeat"] is True and item(out["item"]).get("updated") == upd and len(items()) == n1, (st, out2b))
check("…and no message went to any session", pushed == [], pushed)

# ---- 3. the session through the registry: an id, a transcript id, an old name and the current name are one session
for how, ref in (("a sala id", S["eng"]), ("an old transcript id", Tr["eng_old"]), ("the current transcript id", Tr["eng_new"]), ("an old name (an alias)", "home-sparrow-eng"), ("the current name", "home-sparrow-builder")):
    st, o = tp("open", ref, f"asked through {how}")
    check(f"open through {how}: the same item, the question changed, nothing created", st == 200 and o["item"] == out["item"] and o["repeat"] is True and len(items()) == n1
          and item(out["item"])["metadata"]["next"] == nxt("home-sparrow-builder", f"asked through {how}"), (st, o, len(items()) - n1))
check("…the mark is still the resolved name, not the reference the call used", item(out["item"])["metadata"]["terminal_prompt"] == "home-sparrow-builder")
# another session of the same project has its own item
st, oo = tp("open", "home-other", "Is the plan right?")
check("another session has its own item, under the same project, owned by the same -main agent", st == 200 and oo["item"] != out["item"] and oo["repeat"] is False and len(items()) == n1 + 1
      and item(oo["item"])["metadata"]["terminal_prompt"] == "home-other", (st, oo))
# the session found by an old name when it was renamed after the item was filed: the mark is the old name, the call uses the new one
rn = server._load(server._norm_id(oo["item"])); rn["metadata"]["terminal_prompt"] = "home-sparrow-eng"; server._save(server._norm_id(oo["item"]), rn)
check("a mark that holds an old name (a rename since) still matches the session by the registry", server._terminal_open_items("home-sparrow-builder") == [server._norm_id(out["item"]), server._norm_id(oo["item"])]
      or server._terminal_open_items("home-sparrow-builder") == sorted([server._norm_id(out["item"]), server._norm_id(oo["item"])]), server._terminal_open_items("home-sparrow-builder"))
rn["metadata"]["terminal_prompt"] = "home-other"; server._save(server._norm_id(oo["item"]), rn)
st, c2 = tp("clear", "home-other", None)
check("…and a clear of one session closes only its own item", c2["cleared"] == [oo["item"]] and item(oo["item"])["status"] == "completed" and item(out["item"])["status"] == "open", (c2, item(out["item"])["status"]))

# ---- 4. the project: the registry's, else projects/example-two
st, ol = tp("open", "home-loner", "Which branch?")
check("a session the registry gives no project is filed under projects/example-two, owned by its -main agent, with the subject prefix of the instance", st == 200 and ol["project"] == "projects/example-two"
      and server._session_label(item(ol["item"])["metadata"]["owner"]) == "example-two-main" and item(ol["item"])["subject"].startswith("[home] home-loner is waiting"), (st, ol))
st, onf = tp("open", "home-nofront", "Which branch?")
check("…and so is a session whose project lists no front agent", st == 200 and onf["project"] == "projects/example-two", (st, onf))
st, osl = tp("open", "home-slug", "Which branch?")
check("a project given by its bare name only is found as the question route finds one", st == 200 and osl["project"] == "projects/alpha", (st, osl))
st, ou = tp("open", "home-unknown-pane", "Which branch?")
check("a session no registry holds is filed too, under projects/example-two, by the name it was given", st == 200 and ou["project"] == "projects/example-two" and item(ou["item"])["metadata"]["terminal_prompt"] == "home-unknown-pane", (st, ou))
for who in ("home-loner", "home-nofront", "home-slug", "home-unknown-pane"): tp("clear", who, None)

# ---- 5. clear
n2 = len(items()); gid = out["item"]
st, cl = tp("clear", "home-sparrow-eng", None)           # by the old name
it = item(gid)
check("clear (by an old name): 200, names the closed item", st == 200 and cl["cleared"] == [gid] and cl["session"] == "home-sparrow-builder", (st, cl))
check("…the item is completed with outcome done and the reason \"the pane stopped waiting\"", it["status"] == "completed" and it["metadata"]["outcome"] == "done" and it["metadata"]["reason"] == "the pane stopped waiting", it["metadata"])
check("…it keeps no state, mover or next (a closed item is dead), and the end state goes in outcome_text, the description stays as it was", "state" not in it["metadata"] and "mover" not in it["metadata"] and not it["metadata"].get("next")
      and it["metadata"]["outcome_text"].splitlines()[0] == "- home-sparrow-builder stopped waiting in its terminal" and "pane stopped waiting" in it["metadata"]["outcome_text"]
      and "stopped waiting" not in it["description"].splitlines()[-1], it)
check("…it is in no list (dead)", M.derive(it).state == M.DEAD, M.derive(it).state)
check("…nothing was told to any session (the keeper of record, the builder, the router), no debt, and no item was made", pushed == [] and server._owed_load() == {} and len(items()) == n2, (pushed, server._owed_load(), len(items()) - n2))
upd = it.get("updated")
st, cl2 = tp("clear", "home-sparrow-builder", None)
check("clear with none open is a no-op: 200, nothing cleared, the closed item untouched", st == 200 and cl2["cleared"] == [] and item(gid).get("updated") == upd and len(items()) == n2, (st, cl2))
st, cl3 = tp("clear", "home-never-seen", None)
check("clear for a session that has no item and is in no registry: 200, nothing", st == 200 and cl3["cleared"] == [], (st, cl3))
st, o3 = tp("open", "home-sparrow-builder", "A new question after the first cleared")
check("an open after a clear files a new item (the closed one stays closed)", st == 200 and o3["repeat"] is False and o3["item"] != gid and item(gid)["status"] == "completed" and item(o3["item"])["status"] == "open", (st, o3))
tp("clear", "home-sparrow-builder", None)

# ---- 6. refused: nothing filed
def refused(name, needle, action="open", **kw):
    before = len(items()); st, o = tp(action, **kw)
    check(name, st == 400 and needle in o.get("error", "") and len(items()) == before, (st, o)); return o.get("error", "")
refused("an empty question is refused", "question is required", question="  ")
refused("a question missing is refused", "question is required", question=None)
refused("a question of 201 characters is refused with its length", "at most 200 characters (201 now)", question="x" * 201)
st, ok_a = tp("open", question="y" * 200); check("…200 characters exactly is taken", st == 200 and ok_a["repeat"] is False, (st, ok_a)); tp("clear", "home-sparrow-builder", None)
refused("a question of several lines is refused", "one line", question="first line\nsecond line")
refused("a question with a control character is refused", "one line", question="tab\there")
refused("no sender is refused", "sender", sender="")
refused("a sender that names the owner is refused", "Only the board writes as", sender="Oliver")
refused("a sender with a line break is refused", "sender", sender="a\nb")
refused("a session missing is refused", "session", session="")
refused("a session of more than 120 characters is refused", "session", session="s" * 121)
refused("an action that is neither open nor clear is refused", "action = open | clear", action="reopen")
refused("a clear with no sender is refused", "sender", action="clear", question=None, sender="")
st, o = server._client_post(me, "terminal-prompt", {"action": "open", "session": "home-sparrow-builder", "sender": "s", "question": 5}); check("a question that is not a string is refused", st == 400, (st, o))
check("…the refusals left no item and no part of one", server._terminal_open_items("home-sparrow-builder") == [], server._terminal_open_items("home-sparrow-builder"))

# ---- 7. what a pane writes: alarming words, a long line, characters
ALARM = "Shall I kill the stuck run and rotate the credentials, or leave the quota alone?"
st, oa = tp("open", question=ALARM)
check("a question with alarming words (kill, credentials, quota) is filed: a pane's own words are not judged", st == 200 and item(oa["item"])["metadata"]["next"] == nxt("home-sparrow-builder", ALARM), (st, oa))
create_says = ""
try: server.stackshot_create(subject="[home] Kill the run?", description="- Goal: A thing", project="projects/alpha", owner="home-sparrow-main", next="Oliver: kill it and rotate the credentials")
except server.ToolError as e: create_says = str(e)
check("…while the create tool refuses the same words (the exemption is that route's only)", "uses \"" in create_says and not getattr(server._QUESTION, "on", False), create_says[:200])
tp("clear", "home-sparrow-builder", None)
LONG = "Should I " + " ".join(f"word{i}" for i in range(1, 40)) + " end?"
LONG = LONG[:200]
st, ol2 = tp("open", question=LONG)
nl = item(ol2["item"])["metadata"]["next"]
check("a question that overruns the next-line limit is filed, cut at a word with an ellipsis (the link does not count)", st == 200 and nl.endswith(" …`") and len(nl.replace(SALA + "home-sparrow-builder", "")) <= 200 and nl.startswith(f"Oliver: open {SALA}home-sparrow-builder and answer: `Should I word1"), (st, nl, len(nl)))
st, ol3 = tp("open", question=LONG[:150])
check("…one that fits is kept whole", ol3["repeat"] is True and item(ol2["item"])["metadata"]["next"] == nxt("home-sparrow-builder", LONG[:150]), item(ol2["item"])["metadata"]["next"])
# another writer's line beside the question survives a changed question; the old question is a dropped step
server._update(ol2["item"], next=item(ol2["item"])["metadata"]["next"] + "\nhome-sparrow-builder: check the nightly run", sender="home-sparrow-builder")
st, ol4 = tp("open", question="Another question?")
m4 = item(ol2["item"])["metadata"]
check("a changed question replaces only the terminal's own line: another session's line stays, the old question is a dropped step",
      st == 200 and "home-sparrow-builder: check the nightly run" in m4["next"] and "Another question?" in m4["next"] and LONG[:40] not in m4["next"]
      and any(s["status"] == "dropped" and "and answer:" in s["text"] for s in m4.get("steps", [])), m4)
tp("clear", "home-sparrow-builder", None)
st, ou2 = tp("open", question="Which one: a/b? 100% sure — `rm -rf` (yes/no) [x] \"quoted\" ünïcode 日本語?")
check("punctuation and non-ASCII are kept in the next line, a backtick in the question becomes an apostrophe (the question stands as a code span)", st == 200 and item(ou2["item"])["metadata"]["next"].endswith("'rm -rf' (yes/no) [x] \"quoted\" ünïcode 日本語?`"), (st, item(ou2["item"])["metadata"]["next"] if st == 200 else ou2))
tp("clear", "home-sparrow-builder", None)
st, ow = tp("open", session="pane/odd?name", question="Q")
check("a session name with a slash and a question mark is url-quoted in the link", st == 200 and f"{SALA}pane%2Fodd%3Fname and answer: `Q`" in item(ow["item"])["metadata"]["next"], (st, ow))
tp("clear", "pane/odd?name", None)
cfg_view = server._cfg.CFG["client"]
cfg_view["session_view"] = "https://sala.example.org/view?name={name}"
try:
    st, ov = tp("open", question="Q")
    check("[client] session_view, when set, is the pane's address", st == 200 and item(ov["item"])["metadata"]["next"] == "Oliver: open https://sala.example.org/view?name=home-sparrow-builder and answer: `Q`", (st, ov))
finally: cfg_view["session_view"] = "https://sala.example.org/#s={name}"
tp("clear", "home-sparrow-builder", None)

# ---- 8. the page-debt rules: the script owes no page; the owner is never made to answer for it
import os as _os
old = time.time() - 8 * 3600; _os.utime(T / "brain/projects/alpha.md", (old, old))     # the page is older than any debt, so nothing settles it
d = server._owed_load(); d.setdefault("projects/alpha", {})[server._session_id("home-sparrow-main")] = {"ts": time.time() - 4 * 3600, "item": "s5"}; server._owed_save(d)
st, od = tp("open", question="Debt check")
check("a keeper of record who owes a page past the grace does not stop a script's open", st == 200, (st, od))
server._owed_save({})
for i in range(3):
    tp("open", question=f"burst {i}"); tp("clear", "home-sparrow-builder", None); tp("open", question=f"burst again {i}")
owed = server._owed_load()
OWNER_ID = server._session_id("home-sparrow-main")
check("a burst of opens and clears leaves the keeper of record owing nothing (its own board writes are not blocked)", not any(server._same_sess(o, OWNER_ID) for os_ in owed.values() for o in os_), owed)
check("…and no script label is made to owe a page either", not any(("sala-hook" in o or "script" in o) for os_ in owed.values() for o in os_), owed)
tp("clear", "home-sparrow-builder", None); server._owed_save({}); _os.utime(T / "brain/projects/alpha.md", None)

# ---- 9. a state write that is refused closes the item again
real_update = server._update
def failing_update(gid_, *a, **kw):
    if kw.get("step"): raise server.ToolError("Refused: a pretend refusal of the state")
    return real_update(gid_, *a, **kw)
server._update = failing_update
try:
    before = len(items()); st, of = tp("open", question="Will this half-made item be left?")
finally: server._update = real_update
check("a refused state write answers 400 with the refusal", st == 400 and "pretend refusal" in of.get("error", ""), (st, of))
check("…and the item that was made for it is closed again, not left half made, so the next open files a clean one", len(items()) == before + 1 and server._terminal_open_items("home-sparrow-builder") == []
      and server._load("s" + str(int(items()[-1])))["metadata"]["outcome"] == "dropped", (items()[-3:], server._terminal_open_items("home-sparrow-builder")))
st, og = tp("open", question="Will this one be whole?")
check("…the next open is a clean item in your-step", st == 200 and og["repeat"] is False and item(og["item"])["metadata"]["state"] == "your-step", (st, og))
tp("clear", "home-sparrow-builder", None)

# ---- 9b. a state write that fails with any error (not only a refusal) closes the item; a crash between the two writes is repaired by the next open
def oserror_state(gid_, *a, **kw):
    if kw.get("step"): raise OSError("disk went away")
    return real_update(gid_, *a, **kw)
server._update = oserror_state
try:
    try: tp("open", question="OSError on the state"); raised = None
    except OSError as e: raised = e
finally: server._update = real_update
last = server._load("s" + str(int(items()[-1])))
check("an OSError on the state write propagates and the half-made item is closed (dropped), not left open", raised is not None and last["status"] == "completed" and last["metadata"]["outcome"] == "dropped"
      and server._terminal_open_items("home-sparrow-builder") == [], (raised, last["status"]))
st, og2 = tp("open", question="After the OSError")
check("…and the next open files a clean item in your-step", st == 200 and og2["repeat"] is False and item(og2["item"])["metadata"]["state"] == "your-step", (st, og2))
tp("clear", "home-sparrow-builder", None)
real_state = server._terminal_state
def crash_state(*a, **kw): raise KeyboardInterrupt()       # not an Exception: nothing between the two writes can close the item
server._terminal_state = crash_state
try:
    try: tp("open", question="Crash between the writes")
    except KeyboardInterrupt: pass
finally: server._terminal_state = real_state
half = server._terminal_open_items("home-sparrow-builder")
hm = item(half[0])["metadata"] if half else {}
check("fixture: a crash between the create and the state write leaves an open item with the owner as mover and no state", len(half) == 1 and "state" not in hm and hm.get("mover") == "Oliver", (half, hm))
st, og3 = tp("open", question="Crash between the writes")
fm = item(og3["item"])["metadata"]
check("the next open (same question) repairs it: the same item, repeat true, now your-step with its step, nothing new filed", st == 200 and og3["repeat"] is True and og3["item"] == server._gh.shown(half[0]) and fm.get("state") == "your-step"
      and fm.get("step") == "Answer home-sparrow-builder's question in its terminal" and server._terminal_open_items("home-sparrow-builder") == half, (st, og3, fm))
tp("clear", "home-sparrow-builder", None)

# ---- 9c. a question with no space in it overruns the next line: a hard cut with an ellipsis, never an empty question
for n_ in (173, 185, 200):
    st, ox = tp("open", question="x" * n_); nl = item(ox["item"])["metadata"]["next"]
    check(f"a {n_}-character question with no space (it overruns the line) is cut hard with an ellipsis and keeps its start; the line fits the limit", st == 200 and re.fullmatch(r"Oliver: open \S+ and answer: `x{20,}…`", nl) and len(nl.replace(SALA + "home-sparrow-builder", "")) <= 200, (st, nl))
    tp("clear", "home-sparrow-builder", None)

# ---- 9d. a session name that would render as markup or notify is refused; a plain name the registry does not know yet is taken
for bad in ("[x](https://evil.example) @example-owner", "a b", "a\tb", "x@y", "<b>x</b>", "a`b", "a(b", "a]b", "a>b", "a\u00a0b"):
    before = len(items()); st, o = tp("open", session=bad, question="Q")
    check(f"a session name {bad!r} is refused with a clear message, nothing filed", st == 400 and "without spaces or any of" in o.get("error", "") and len(items()) == before, (st, o))
st, o = tp("clear", session="a b", question=None); check("…a clear refuses it the same way", st == 400 and "without spaces" in o.get("error", ""), (st, o))
for plain in ("brand-new_pane.1", "dir/pane-2", "日本語-pane"):
    st, o = tp("open", session=plain, question="Q")
    check(f"an unknown but plain name {plain!r} is taken", st == 200 and o["session"] == plain and o["project"] == "projects/example-two", (st, o)); tp("clear", plain, None)

# ---- 10. concurrency: one session, many calls, one item
n3 = len(items()); res = []
ths = [threading.Thread(target=lambda i=i: res.append(tp("open", question=f"racing {i}"))) for i in range(8)]
[t.start() for t in ths]; [t.join() for t in ths]
check("eight threads opening for one session at once file one item and all get its id", len(items()) == n3 + 1 and len({r[1]["item"] for r in res}) == 1 and all(r[0] == 200 for r in res)
      and sum(1 for r in res if not r[1]["repeat"]) == 1, [r for r in res][:3])
ths = [threading.Thread(target=lambda: res.append(tp("clear", question=None))) for _ in range(4)]
[t.start() for t in ths]; [t.join() for t in ths]
check("…and four clears at once close it once, the others find none", all(r[0] == 200 for r in res[8:]) and sum(len(r[1]["cleared"]) for r in res[8:]) == 1 and server._terminal_open_items("home-sparrow-builder") == [], res[8:])

# ---- 11. over HTTP and through client.py
app = server.mcp.http_app()
with TestClient(app) as c:
    r = c.post("/client/terminal-prompt", json={"action": "open", "session": "home-sparrow-builder", "sender": "s", "question": "q"}); check("http: without a token -> 401", r.status_code == 401, r.status_code)
    r = c.post("/client/terminal-prompt", json={"action": "open", "session": "home-sparrow-builder", "sender": "http-script", "question": "Via http?"}, headers=HD)
    check("http: with a machine token -> 200 and the item", r.status_code == 200 and r.json()["repeat"] is False and r.headers["cache-control"] == "no-store", r.text)
    gid_http = r.json()["item"]
    r = c.post("/client/terminal-prompt", json={"action": "open", "session": "home-sparrow-builder", "sender": "http-script", "question": "x" * 201}, headers=HD)
    check("http: a refusal is 400 with the reason", r.status_code == 400 and "at most 200" in r.json()["error"], r.text)
    r = c.post("/client/terminal-prompt", json={"action": "clear", "session": "home-sparrow-builder", "sender": "http-script"}, headers=HD)
    check("http: clear -> 200 and the closed item", r.status_code == 200 and r.json()["cleared"] == [gid_http], r.text)
    import urllib.request, urllib.error
    class _Resp:
        def __init__(s, r): s.status = r.status_code; s._b = r.content
        def read(s): return s._b
        def __enter__(s): return s
        def __exit__(s, *a): return False
    down = {"on": False}
    def fake_urlopen(req, timeout=0):
        if down["on"]: raise urllib.error.URLError("connection refused")
        path = req.full_url.replace(client.server_url(), "")
        r = c.post(path, content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(path, headers=dict(req.header_items()))
        if r.status_code >= 400: raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
        return _Resp(r)
    client.urllib.request.urlopen = fake_urlopen
    def run(*argv):
        so, se = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se): rc = client.main(["client.py", *argv])
        return rc, so.getvalue(), se.getvalue()
    before = len(items())
    rc, o, e = run("post", "terminal-prompt", "open", "--session", "home-sparrow-builder", "--question", Q, "--sender", "sala-hook")
    gid_cli = o.strip()
    check("client.py open: exactly the item id on stdout, nothing on stderr, exit 0, one item filed", rc == 0 and re.fullmatch(r"\S+\n", o) and e == "" and len(items()) == before + 1, (rc, o, e))
    check("…the item is the session's open terminal prompt", item(gid_cli)["metadata"]["terminal_prompt"] == "home-sparrow-builder" and item(gid_cli)["status"] == "open")
    rc, o2, e = run("post", "terminal-prompt", "open", "--session", S["eng"], "--question", "Same pane, new words", "--sender", "sala-hook")
    check("client.py open again (by the pane's id): the same id printed, exit 0, nothing filed, the question changed", rc == 0 and o2 == o and e == "" and len(items()) == before + 1
          and item(gid_cli)["metadata"]["next"].endswith("`Same pane, new words`"), (rc, o2, e))
    rc, o, e = run("post", "terminal-prompt", "clear", "--session", "home-sparrow-eng", "--sender", "sala-hook")
    check("client.py clear: nothing on stdout, exit 0, the item closed with its reason", rc == 0 and o == "" and e == "" and item(gid_cli)["status"] == "completed" and item(gid_cli)["metadata"]["reason"] == "the pane stopped waiting", (rc, o, e))
    rc, o, e = run("post", "terminal-prompt", "clear", "--session", "home-sparrow-builder", "--sender", "sala-hook")
    check("client.py clear with none open: exit 0, nothing on either stream (a no-op)", rc == 0 and o == "" and e == "", (rc, o, e))
    before = len(items())
    for name, argv, needle in (("no verb", [], "usage: client.py post terminal-prompt"), ("a wrong verb", ["reopen", "--session", "x", "--sender", "s"], "usage: client.py post terminal-prompt"),
                               ("open without --question", ["open", "--session", "x", "--sender", "s"], "usage:"), ("open without --session", ["open", "--question", "q", "--sender", "s"], "usage:"),
                               ("open without --sender", ["open", "--session", "x", "--question", "q"], "usage:"), ("clear without --session", ["clear", "--sender", "s"], "usage:"),
                               ("clear without --sender", ["clear", "--session", "x"], "usage:"), ("clear with a --question", ["clear", "--session", "x", "--sender", "s", "--question", "q"], "usage:"),
                               ("a flag with no value", ["open", "--session"], "needs a value"), ("a stray word", ["open", "--session", "x", "--question", "q", "--sender", "s", "stray"], "usage:"),
                               ("a question over 200 characters", ["open", "--session", "x", "--question", "q" * 201, "--sender", "s"], "at most 200"),
                               ("a question over several lines", ["open", "--session", "x", "--question", "a\nb", "--sender", "s"], "one line")):
        rc, o, e = run("post", "terminal-prompt", *argv)
        check(f"client.py misuse, {name}: usage or reason on stderr, nothing on stdout, exit 1", rc == 1 and o == "" and needle in e, (rc, o, e))
    check("…and none of them filed an item", len(items()) == before, (len(items()), before))
    rc, o, e = run("post", "terminal-prompt", "open", "--session", "x", "--question", "q", "--sender", "Oliver")
    check("client.py open with a sender that names the owner: the server's refusal on stderr, exit 1, nothing on stdout", rc == 1 and o == "" and "[400]" in e and "Only the board writes as" in e, (rc, o, e))
    tokfile = pathlib.Path(client.TOKEN); hold = tokfile.with_suffix(".held"); tokfile.rename(hold)
    try:
        rc, o, e = run("post", "terminal-prompt", "open", "--session", "home-sparrow-builder", "--question", "q", "--sender", "s")
        check("client.py open with no token on the machine: exit 1, the reason on stderr, nothing filed", rc == 1 and o == "" and "no token on this machine" in e and len(items()) == before, (rc, o, e))
        rc, o, e = run("post", "terminal-prompt", "clear", "--session", "home-sparrow-builder", "--sender", "s")
        check("client.py clear with no token: exit 1", rc == 1 and "no token on this machine" in e, (rc, o, e))
    finally: hold.rename(tokfile)
    down["on"] = True
    rc, o, e = run("post", "terminal-prompt", "open", "--session", "home-sparrow-builder", "--question", "q", "--sender", "s")
    check("client.py open with the server not reached: exit 1, [0] and the reason on stderr, nothing on stdout", rc == 1 and o == "" and "[0]" in e and "URLError" in e, (rc, o, e))
    rc, o, e = run("post", "terminal-prompt", "clear", "--session", "home-sparrow-builder", "--sender", "s")
    check("client.py clear with the server not reached: exit 1", rc == 1 and o == "" and "[0]" in e, (rc, o, e))
    down["on"] = False

# ---- 12. the docs
help_text = " ".join(client.__doc__.split())    # the help wraps its lines
check("the client help documents both verbs, the key, the shape and the exit codes", "client.py post terminal-prompt open" in help_text and "client.py post terminal-prompt clear" in help_text
      and "terminal_prompt" in help_text and "the pane stopped waiting" in help_text and "Your move" in help_text and "200 characters" in help_text, help_text[help_text.find("post terminal-prompt") - 50:][:300])
import _docs
readme = _docs.page("client-contract")
check("the docs document the post kind: both verbs, the route, the item's shape, the idempotency and the page-debt rule", "POST /client/terminal-prompt" in readme and "post terminal-prompt open" in readme
      and "post terminal-prompt clear" in readme and "metadata.terminal_prompt" in readme and "the pane stopped waiting" in readme)
check("the 404 list of the client API names the new write", "terminal-prompt" in server._client_post(me, "nope", {})[1]["error"])
check("the server's docstring and the client's usage line carry the shape", "terminal-prompt" in client.TERMINAL_PROMPT_USAGE and "Answer <session>'s question in its terminal" in " ".join(server._terminal_prompt.__doc__.split()))

# [subject] fallback_prefix: the prefix of an item no session wrote when the project's scope has none of its own
_cfgsub = server._cfg.CFG["subject"]; _was = dict(_cfgsub)
try:
    _cfgsub["prefixes"] = ["[work] ", "[home] "]
    _cfgsub.pop("fallback_prefix", None)
    check("no fallback_prefix set: the scope's prefix when the instance has it, else the first prefix", server._terminal_subject_prefix("home") == "[home] " and server._terminal_subject_prefix("zzz") == "[work] ", server._terminal_subject_prefix("zzz"))
    _cfgsub["fallback_prefix"] = "[home] "
    check("fallback_prefix set: a scope with no prefix of its own gets it, a scope with one keeps its own", server._terminal_subject_prefix("zzz") == "[home] " and server._terminal_subject_prefix("work") == "[work] ", server._terminal_subject_prefix("zzz"))
    _cfgsub["fallback_prefix"] = "[away] "
    check("a fallback_prefix that is not one of the prefixes is ignored: the first prefix", server._terminal_subject_prefix("zzz") == "[work] ", server._terminal_subject_prefix("zzz"))
    _cfgsub["fallback_prefix"] = ""
    check("an empty fallback_prefix is none", server._terminal_subject_prefix("zzz") == "[work] ")
finally:
    _cfgsub.clear(); _cfgsub.update(_was)

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks FAILED"); sys.exit(1)
print(f"ok: {len(ran)} checks"); sys.exit(0)
