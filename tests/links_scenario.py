"""Scenario test for linked item ids in tool replies (server.py `_LinkIds`) — fixture data, no live store, no network.

Every tool is called once through fastmcp's in-memory client, the way a session calls it. Covers: an item id in a reply, its
subject, description and next, a relay or nag line and a refusal, written as [id](<board_url>/items/<id>); the base taken from
[instance] board_url; an id already linked, inside a URL or inline code, glued to a word, a hyphen or a version, or naming no
item (p1) left alone; a JSON reply left as it is.

    tests/run-suite links        → exit 0 / 1"""
import asyncio, json, logging, os, pathlib, re, sys, tempfile
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="linkstest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^board_url = "[^"]*"', 'board_url = "https://board.example.org/"', toml); assert n == 1
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "secrets", "touch", "brain/projects"): (T / d).mkdir(parents=True)
S, A = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
(T / "fleet/a/sessions.json").write_text(json.dumps({S: {"name": "home-x", "machine": "a", "url": "", "seen": "x"}, A: {"name": "home-x-main", "machine": "a", "url": "", "seen": "x"}}))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
page = {"title": "X", "name": "X", "org": "home", "tags": [], "type": "project", "session": "home-x", "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": "https://example.invalid/x"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/x": page}})); (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def item(i, **kw): (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": A, "project": "projects/x"}, "updated": 1.0, **kw}))
item(1); item(2, subject="[home] item 2, after a1", description="- Follows a1.\n- It lives here\n- Done when a1 is a1.")
push_log = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\nopen({str(push_log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\nprint('delivered → ' + sys.argv[-2])\n")
sys.path.insert(0, STACK); logging.disable(logging.CRITICAL)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

import server
server._publish = lambda: None; server._PUSH = [sys.executable, str(T / "fakepush.py")]
from fastmcp import Client
L = lambda gid: f"[{gid}](https://board.example.org/items/{gid})"

STRUCT = []      # every reply's structuredContent: claude.ai shows that copy of a `-> str` tool's reply ({"result": <text>}), not the text

async def call(name, args):
    async with Client(server.mcp) as c:
        r = await c.session.call_tool(name, args)        # the raw MCP reply, as a connector receives it
        text = "".join(getattr(x, "text", "") for x in r.content)
        STRUCT.append((name, text, r.structured_content))
        return bool(r.is_error), text

def run(tool, **args): return asyncio.run(call(tool, args))

# ---- the link itself (_link_ids)
lk = server._link_ids
check("an item id → a link to its page, from [instance] board_url (its trailing slash dropped)", lk("see a1 now") == f"see {L('a1')} now", lk("see a1 now"))
check("each id in a line; punctuation around it kept", lk("a1, a2. (a1)") == f"{L('a1')}, {L('a2')}. ({L('a1')})", lk("a1, a2. (a1)"))
check("an id already linked is left alone (no double link)", lk(f"see {L('a1')}") == f"see {L('a1')}" and lk(lk("a1")) == L("a1"), lk(f"see {L('a1')}"))
check("…as is a markdown link with other text", lk("[the first](https://x.example/a1)") == "[the first](https://x.example/a1)")
check("an id inside a URL is left alone", lk("https://board.example.org/items/a1 and https://x.example/#task-a-1?q=a1") == "https://board.example.org/items/a1 and https://x.example/#task-a-1?q=a1")
check("an id inside inline code is left alone", lk("run `client.py recycle-due --item a1`") == "run `client.py recycle-due --item a1`")
check("an id-like string glued to a word, a hyphen, a path or a version is left alone",
      lk("ba1 a1b a1-x x-a1 /a1 w1.2 a1.5 a1_x") == "ba1 a1b a1-x x-a1 /a1 w1.2 a1.5 a1_x", lk("ba1 a1b a1-x x-a1 /a1 w1.2 a1.5 a1_x"))
check("a token that names no item stays plain (priority p1, an unknown s99)", lk("p1 s99 a1") == f"p1 s99 {L('a1')}", lk("p1 s99 a1"))
check("a JSON reply is left as it is", lk('{"id": "a1"}') == '{"id": "a1"}' and lk('[{"gid": "a1"}]') == '[{"gid": "a1"}]')
check("a reply that only starts with a bracket is still linked", lk("[nag] a1 owes") == f"[nag] {L('a1')} owes", lk("[nag] a1 owes"))
_bu = server.BOARD_URL; server.BOARD_URL = ""
check("no board_url configured: the text unchanged", lk("a1") == "a1"); server.BOARD_URL = _bu

# ---- one call of each tool, through the MCP client
err, out = run("get", item_id="a2")
check("get: the id, and an id in the subject and description, linked", not err and out.startswith(f"{L('a2')} [open] [home] item 2, after {L('a1')}") and f"Follows {L('a1')}." in out and f"Done when {L('a1')} is {L('a1')}." in out, out)
err, out = run("create", subject="[home] made after a1", description="- Goal: Made after a1\n- It lives here\n- Done when done", project="projects/x", owner="home-x-main", next="home-x-main: ask about a2")
gid = re.search(r"created \[([a-z]\d+)\]", out); gid = gid.group(1) if gid else ""
check("create: the new id and the ids in subject, description and next linked", not err and gid and out.startswith(f"created {L(gid)}") and f"made after {L('a1')}" in out and f"home-x-main: ask about {L('a2')}" in out, out)
check("create: the owner's page-debt line links the id too", f"({L(gid)}," in out or f"{L(gid)}" in out.split("[nag]")[-1], out)
err, out = run("update", item_id="a1", next="home-x-main: then close a2", sender="home-x-main")
check("update: the id and an id in next linked", not err and out.startswith(f"updated {L('a1')}.") and f"home-x-main: then close {L('a2')}" in out, out)
check("update: the relay line to the writer links nothing that is no item, and keeps its URL whole", "https://board.example.org/items/a1)" in out and "](https://board.example.org/items/[" not in out, out)
err, out = run("update", item_id="a1", description=f"- Goal: Copied from a reply: see {L('a2')}.\n- It lives here\n- Done when done", sender="home-x-main")
check("a linked id copied back into a write is stored plain", json.loads((T / "store/a/1.json").read_text())["description"] == "- Goal: Copied from a reply: see a2.\n- It lives here\n- Done when done", (T / "store/a/1.json").read_text())
check("…and shown linked again in the reply", f"see {L('a2')}." in out, out)
check("an unrelated markdown link in a write is kept", server._unlink_ids("[a2](https://x.example/items/a2) and [x](https://board.example.org/items/a3)") == "[a2](https://x.example/items/a2) and [x](https://board.example.org/items/a3)")
err, out = run("confirm", item_id="a2", sender="home-x")
check("confirm: linked", not err and out.startswith(f"confirmed {L('a2')} at"), out)
err, out = run("complete", item_id="a2")
check("complete: a refusal links the id it names", err and f"closing {L('a2')} needs" in out, out)
err, out = run("complete", item_id="a2", outcome="superseded", superseded_by="a1", reason="folded into a1", description="- Folded into a1 with its work", sender="home-x")
check("complete: the id, superseded_by and the reason linked", not err and L("a2") in out and f"folded into {L('a1')}" in out, out)
err, out = run("brief")
check("brief: item ids linked", not err and L("a1") in out, out[:600])
err, out = run("sessions", name="home-x-main")
check("sessions: answers, and a version or machine name is never taken for an id", not err and "home-x-main" in out and "](" not in out, out[:600])
err, out = run("anchors", project="projects/x", add=["https://github.com/example/repo/issues/1"], items=["a1"])
check("anchors: the scoped id linked, the anchor URL whole", not err and L("a1") in out and "https://github.com/example/repo/issues/1" in out, out)
import routing
nid = routing.record("projects/x", kind="board", to=S, label="board a1", who="home-x-main", text="changed: a1", url="", target="for home-x-main", pilot=True)
err, out = run("route", notice=nid, ruling="dropped", reason="a1 is already handled", sender="home-x")
check("route: an id in the ruling's reason linked", not err and f"{L('a1')} is already handled" in out, out)
err, out = run("message", to="home-x", text="about a1", sender="home-x-main")
check("message: the reply comes back (no id in it to link, nothing broken)", not err and "home-x" in out, out)
sent = [json.loads(l) for l in push_log.read_text().splitlines()] if push_log.exists() else []
check("message: what is delivered keeps the sender's own text (only tool replies are linked)", any(a[-1].count("about a1") == 1 and "](https://" not in a[-1].split("\n")[1] for a in sent), sent[-1:])
err, out = run("rules")
check("rules: answers", not err and len(out) > 0, out[:300])
err, out = run("bump_versions")
check("bump_versions: answers", len(out) > 0, out[:300])

bad = [(n, sc) for n, t, sc in STRUCT if sc is not None and sc.get("result") != t]
check("every reply's structuredContent result carries the same linked text (claude.ai shows that copy)", STRUCT and not bad, bad[:2])
check("…and one was actually checked with a link in it", any(sc and L("a1") in str(sc.get("result")) for n, t, sc in STRUCT), [n for n, t, sc in STRUCT if sc])

print(("ok" if not fails else "FAILED") + f": links scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
