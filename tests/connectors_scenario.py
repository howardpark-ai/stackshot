#!/usr/bin/env python3
"""Scenario test for connectors.py: one name for a call to the instance's own connectors by either route — the
direct claude.ai connector tool, or a call inside the MCP portal's Code Mode script — and for what pages.py does with it.
Fixture data only: a catalog in a temp dir, a temp config, a fake Cloudflare API and CLI list for `build`; no network.

Covers: the CLI's tool-name rule; the direct route by the hook's mcp_server name and by prefix; foreign servers; the portal's
meta-tools; scripts as sessions write them (object literals, loops with variables, shorthand, try/catch, returns); what makes
a script unreadable (an alias, codemode[…], a spread, a computed key, eval, a non-object argument, a call inside a template,
an unknown entry) and that its calls are still returned; strings and comments that mention codemode; matches(); the CLI
verbs; build (the join on the upstream host, kept direct names when the CLI list is unavailable, unchanged → no write, the
commit into a git checkout); aliases (a server's or the portal's second CLI name, e.g. an API-key session's local
`mcp-portal`): resolve by an alias name or prefix, `claude mcp list` run in a fresh empty directory with the claude.ai name as
primary, build collecting aliases from that list and ~/.claude.json (the previous catalog's kept when it cannot be read); and
pages.py: touch, other_write and turn_activity seeing the same calls by both routes and by an alias.

    tests/run-suite connectors        → exit 0 / 1"""
import json, os, re, shutil, subprocess, sys, pathlib, tempfile, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="connectorstest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                 ("timezone", "Asia/Dubai"), ("catalog_file", f"{tmp}/connectors.json")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^writer_owes_page = false', 'writer_owes_page = true', toml); assert n == 1     # every project page is the router's since a pane owes a page only where the writer does
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
for d in ("store/a", "fleet/a", "state", "secrets", "touch", "brain/projects"): (T / d).mkdir(parents=True)
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "session": "x", "status": "active", "board": [], "updated": 1, "mirror": ""}}}))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

from stackshot.fleet import connectors as c

# ---- 1. the CLI's rule for a server's name inside a tool name (claude 2.1.296, In()), against names seen live
check("claude.ai name: the apostrophe and the parentheses", c.cli_name("claude.ai Oliver's MCP Portal (Cloudflare)") == "claude_ai_Oliver_s_MCP_Portal_Cloudflare", c.cli_name("claude.ai Oliver's MCP Portal (Cloudflare)"))
check("claude.ai name: hyphens stay", c.cli_name("claude.ai Brain-main") == "claude_ai_Brain-main")
check("claude.ai name: spaces", c.prefix_of("claude.ai Google Workspace acme") == "mcp__claude_ai_Google_Workspace_acme__")
check("a plugin name: no collapse, no trim", c.cli_name("plugin:small-business:gmail") == "plugin_small-business_gmail")
check("a non-claude.ai name keeps double underscores", c.cli_name("my (x)") == "my__x_")
check("host of a URL and of a bare host", c.host_of("https://gw-acme.example.org/mcp") == "gw-acme.example.org" and c.host_of("mcp-portal.example.org") == "mcp-portal.example.org")

# ---- 2. a catalog as build writes it (the names are a fixture; production's come from the portal and the CLI)
def server(name, url, tools, ro=()):
    return {"name": name.split(" ", 1)[-1], "url": url, "auth": "bearer", "connector": name, "prefix": c.prefix_of(name),
            "tools": {t: {"read_only": t in ro} for t in tools}}
CAT = {"generated": "2026-06-09T11:00:00Z", "instance": "stackshot",
       "portal": {"id": "mcp-portal", "name": "Oliver's MCP Portal", "url": "mcp-portal.example.org",
                  "connector": "claude.ai Oliver's MCP Portal (Cloudflare)", "prefix": c.prefix_of("claude.ai Oliver's MCP Portal (Cloudflare)"),
                  "aliases": [{"connector": "mcp-portal", "prefix": c.prefix_of("mcp-portal")}]},
       "servers": {
           "stackshot": server("claude.ai Stackshot", "https://board.example.org/mcp", ["brief", "get", "create", "update", "complete", "message", "anchors", "route", "confirm"], ro=("brief", "get")),
           "gbrain": server("claude.ai Brain-main", "https://gbrain.example.org/mcp", ["search", "get_page", "put_page", "edit_page", "add_timeline_entry", "capture", "query"], ro=("search", "get_page", "query")),
           "gacme": server("claude.ai Google Workspace acme", "https://gw-acme.example.org/mcp", ["search_gmail_messages", "send_gmail_message", "list_calendars"], ro=("search_gmail_messages", "list_calendars")),
           "gdelta": server("claude.ai Google Workspace delta", "https://gw-delta.example.org/mcp", ["search_gmail_messages", "send_gmail_message"]),
           "gbeta": server("claude.ai Google Workspace beta", "https://gw-beta.example.org/mcp", ["search_gmail_messages", "send_gmail_message"]),
       }}
CAT["servers"]["stackshot"]["aliases"] = [{"connector": "stackshot-local", "prefix": c.prefix_of("stackshot-local")}]
(T / "connectors.json").write_text(json.dumps(CAT, indent=1), encoding="utf-8")
check("the catalog loads from [portal] catalog_file", (c.load_catalog() or {}).get("instance") == "stackshot", c.catalog_path())
ST, GB, GD, NO = "mcp__claude_ai_Stackshot__", "mcp__claude_ai_Brain-main__", "mcp__claude_ai_Google_Workspace_acme__", "mcp__claude_ai_Notion__"
PX = "mcp__claude_ai_Oliver_s_MCP_Portal_Cloudflare__portal_codemode_execute"
PS = "mcp__claude_ai_Oliver_s_MCP_Portal_Cloudflare__portal_codemode_search"
names = lambda r: [x.name for x in r.calls]

# ---- 3. the direct route
r = c.resolve(ST + "update", {"item_id": "s1", "next": "x"})
check("direct: stackshot.update by prefix", r.route == "direct" and r.ok and r.own and names(r) == ["stackshot.update"] and r.calls[0].args == {"item_id": "s1", "next": "x"}, r)
r = c.resolve(ST + "update", {"item_id": "s1"}, {"name": "claude.ai Stackshot", "source": "claudeai"})
check("direct: the hook's mcp_server name is the key when given", r.route == "direct" and names(r) == ["stackshot.update"], r)
r = c.resolve("mcp__claude_ai_Stackshot_renamed__update", {}, {"name": "claude.ai Stackshot", "source": "claudeai"})
check("direct: the server name wins over an unrecognized prefix", r.route == "direct" and names(r) == ["stackshot.update"], r)
r = c.resolve(GD + "send_gmail_message", {"to": "a@b"})
check("direct: gacme.send_gmail_message", r.own and names(r) == ["gacme.send_gmail_message"], r)
r = c.resolve(GB + "get_page", {"slug": "projects/alpha"})
check("direct: gbrain.get_page", r.own and names(r) == ["gbrain.get_page"], r)
r = c.resolve(NO + "notion-fetch", {"id": "x"})
check("direct: a foreign connector is not ours", r.route is None and not r.calls and not r.own, r)
r = c.resolve("Bash", {"command": "ls"})
check("not an MCP tool", r.route is None and not r.own, r)
check("no catalog → None", c.resolve(ST + "update", {}, catalog={}) is None)

# ---- 4. the portal's own meta-tools
r = c.resolve(PS, {"query": "board"})
check("portal: search is a call to the portal itself", r.route == "portal" and r.own and names(r) == ["portal.portal_codemode_search"], r)
r = c.resolve(PX, {"code": ""})
check("portal: an empty script is nothing (not own)", r.route == "portal" and r.ok and not r.calls and not r.own, r)

# ---- 4b. a second name for the same server: the API-key session's local `mcp-portal`, a server's CLI alias
AX, AS = "mcp__mcp-portal__portal_codemode_execute", "mcp__mcp-portal__portal_codemode_search"
CODE = 'async () => { await codemode.stackshot_update({item_id: "s1", next: "x"}); return codemode.gbrain_get_page({slug: "projects/alpha"}); }'
via = lambda r: [(x.server, x.tool, c.plain(x.args), x.route) for x in r.calls]
r0 = c.resolve(PX, {"code": CODE}, {"name": "claude.ai Oliver's MCP Portal (Cloudflare)", "source": "claudeai"})
r = c.resolve(AX, {"code": CODE}, {"name": "mcp-portal", "source": "local"})
check("alias: a portal script by the alias name resolves to the same calls as by the claude.ai name", r.route == "portal" and r.own and via(r) == via(r0) and names(r) == ["stackshot.update", "gbrain.get_page"], (r, r0))
r = c.resolve(AX, {"code": CODE})
check("alias: the same script by the alias prefix only (no mcp_server)", r.route == "portal" and r.own and via(r) == via(r0), r)
r = c.resolve(AS, {"query": "board"})
check("alias: the portal's search by the alias prefix is the portal's own tool", r.route == "portal" and r.own and names(r) == ["portal.portal_codemode_search"], r)
r = c.resolve("mcp__mcp_portal_renamed__portal_codemode_execute", {"code": CODE}, {"name": "mcp-portal"})
check("alias: the alias name wins over an unrecognized prefix", r.route == "portal" and r.own and via(r) == via(r0), r)
r = c.resolve("mcp__stackshot-local__update", {"item_id": "s1", "next": "x"})
check("alias: a direct server by its alias prefix", r.route == "direct" and r.own and names(r) == ["stackshot.update"] and r.calls[0].args == {"item_id": "s1", "next": "x"}, r)
r = c.resolve("mcp__stackshot-local__get", {"id": "s1"}, {"name": "stackshot-local", "source": "user"})
check("alias: a direct server by its alias name", r.route == "direct" and names(r) == ["stackshot.get"], r)
r = c.resolve(ST + "brief", {}, {"name": "stackshot-local"})
check("alias: the alias name with the primary's prefix strips the primary's", r.route == "direct" and names(r) == ["stackshot.brief"], r)
r = c.resolve("mcp__mcp-portal-other__portal_codemode_execute", {"code": CODE}, {"name": "mcp-portal-other"})
check("alias: a name that is no alias is not ours", r.route is None and not r.calls, r)
old_cat = json.loads(json.dumps(CAT)); del old_cat["portal"]["aliases"]; del old_cat["servers"]["stackshot"]["aliases"]
r = c.resolve(PX, {"code": CODE}, catalog=old_cat)
check("alias: a catalog without aliases (the old shape) still resolves the primary", r.own and via(r) == via(r0), r)
check("alias: names_of lists the primary first", c.names_of(CAT["portal"]) == [("claude.ai Oliver's MCP Portal (Cloudflare)", PX.rsplit("__", 1)[0] + "__"), ("mcp-portal", "mcp__mcp-portal__")])

# ---- 5. scripts as sessions write them
ex = lambda code: c.resolve(PX, {"code": code})
r = ex('async () => await codemode.stackshot_update({item_id: "s24", sender: "ops-x", next: "Fri: measure it", wake: "2026-10-16", hold: true})')
check("portal: one update, its args as literals", r.own and names(r) == ["stackshot.update"] and r.calls[0].args == {"item_id": "s24", "sender": "ops-x", "next": "Fri: measure it", "wake": "2026-10-16", "hold": True} and r.calls[0].clean, r)
r = ex('async () => {\n  const r = await codemode.gbrain_query({ question: "What is an owner?", limit: 6 }).catch(e => String(e));\n  const t = typeof r === "string" ? r : JSON.stringify(r);\n  return t.slice(0, 5000);\n}')
check("portal: a read with a .catch chain and a return", r.own and names(r) == ["gbrain.query"] and r.calls[0].args == {"question": "What is an owner?", "limit": 6}, r)
r = ex("async () => { try { const r = await codemode.gacme_list_calendars({}); return r; } catch (e) { return { error: String(e) }; } }")
check("portal: try/catch, an empty object", r.own and names(r) == ["gacme.list_calendars"] and r.calls[0].args == {}, r)
r = ex('async () => { const m={s11:["s17"],s13:["s14","s15"]}; const out={}; for (const [id,a] of Object.entries(m)) { const r = await codemode.stackshot_update({item_id:id, after:a, sender:"falcon-engineer"}); out[id]=JSON.stringify(r).slice(0,250); } return out; }')
check("portal: a loop with variable values is read with confidence", r.own and names(r) == ["stackshot.update"] and r.calls[0].args["item_id"] is c.DYNAMIC and r.calls[0].args["after"] is c.DYNAMIC and r.calls[0].args["sender"] == "falcon-engineer", r)
check("DYNAMIC is truthy and not a str", bool(c.DYNAMIC) and not isinstance(c.DYNAMIC, str) and str(c.DYNAMIC) == "<dynamic>")
r = ex("async () => { const id = 's1'; return await codemode.stackshot_get({id}); }")
check("portal: shorthand {id} is a plain key with a dynamic value", r.own and r.calls[0].args == {"id": c.DYNAMIC} and r.calls[0].clean, r)
r = ex("async () => codemode.stackshot_complete({item_id: 's2', outcome: 'done', reason: \"it's live\", description: 'A, B; C'})")
check("portal: quotes, commas and an apostrophe inside strings", r.own and r.calls[0].args == {"item_id": "s2", "outcome": "done", "reason": "it's live", "description": "A, B; C"}, r)
r = ex('async () => codemode.gbrain_add_timeline_entry({slug: "projects/alpha", entry: `2026-10-12 | x — a line with "quotes"`, source: "t"})')
check("portal: a template without ${} is a string", r.own and r.calls[0].args["entry"] == '2026-10-12 | x — a line with "quotes"', r)
r = ex('async () => codemode.gbrain_add_timeline_entry({slug: "projects/alpha", entry: `${new Date().toISOString()} | x`, source: "t"})')
check("portal: a template with ${} is dynamic, still confident", r.own and r.calls[0].args["entry"] is c.DYNAMIC and r.calls[0].clean, r)
r = ex('async () => { const a = await codemode.stackshot_get({id: "s1"}); const b = await codemode.gbrain_get_page({slug: "projects/alpha", include_content: true}); return [a, b]; }')
check("portal: two calls to two servers, in order", r.own and names(r) == ["stackshot.get", "gbrain.get_page"] and r.calls[1].args == {"slug": "projects/alpha", "include_content": True}, r)
r = ex('async () => codemode.stackshot_update({item_id: "s1", next: "a" + b, due: null, n: -3.5e2, h: 0x10, nested: {k: [1, "two", {three: 3}]}, f: false})')
check("portal: nested literals, numbers, null, an expression value", r.own and r.calls[0].args == {"item_id": "s1", "next": c.DYNAMIC, "due": None, "n": -350.0, "h": 16, "nested": {"k": [1, "two", {"three": 3}]}, "f": False}, r)
r = ex('async () => codemode.stackshot_update({item_id: "s1", next: x ? "a" : "b", needs: cond && "decision", "quoted key": 1, \'single\': 2, 3: "n"})')
check("portal: ternary and && values are dynamic; quoted and numeric keys are plain", r.own and r.calls[0].args == {"item_id": "s1", "next": c.DYNAMIC, "needs": c.DYNAMIC, "quoted key": 1, "single": 2, "3": "n"}, r)
r = ex('async () => codemode.stackshot_message({to: "x", text: "call codemode.gbrain_put_page() later", /* codemode.stackshot_create({}) */ sender: "me"}) // codemode.stackshot_complete({})')
check("portal: codemode inside strings and comments is not a call", r.own and names(r) == ["stackshot.message"] and r.calls[0].args == {"to": "x", "text": "call codemode.gbrain_put_page() later", "sender": "me"}, r)
r = ex('async () => codemode.stackshot_update({item_id: "s1", next: "line one\\nline \\"two\\"", k: \'it\\\'s\'})')
check("portal: escapes are decoded", r.own and r.calls[0].args == {"item_id": "s1", "next": 'line one\nline "two"', "k": "it's"}, r)
r = ex('async () => await codemode.stackshot_update({item_id: "s1", next: "x", fn: (a, b) => a + b, arr: [1, 2].map(x => x * 2), o: {a: 1}.a})')
check("portal: arrow functions and chained literals are dynamic values", r.own and r.calls[0].args == {"item_id": "s1", "next": "x", "fn": c.DYNAMIC, "arr": c.DYNAMIC, "o": c.DYNAMIC}, r)
r = ex('async () => codemode.stackshot_update({item_id: "s1", next: "x",})')
check("portal: a trailing comma", r.own and r.calls[0].args == {"item_id": "s1", "next": "x"}, r)
r = ex("async () => codemode.stackshot_update( { item_id : 's1' , status : 'open' } , extra )")
check("portal: whitespace and a second argument", r.own and r.calls[0].args == {"item_id": "s1", "status": "open"}, r)
r = ex("async () => codemode\n  .stackshot_brief({})")
check("portal: a line break before the member", r.own and names(r) == ["stackshot.brief"], r)

# ---- 6. what the reader will not vouch for (the calls it read are still there)
r = ex("async () => { const c = codemode; return c.stackshot_update({item_id: 's1', next: 'x'}); }")
check("unreadable: an alias of codemode", r.route == "portal" and not r.ok and not r.own and "other than" in r.why and not r.calls, r)
r = ex("async () => codemode['stackshot_' + t]({item_id: 's1'})")
check("unreadable: codemode[…]", not r.ok and "other than" in r.why, r)
r = ex("async () => codemode.stackshot_update({...base, item_id: 's1'})")
check("unreadable: a spread, the call still returned", not r.ok and "spread" in r.why and names(r) == ["stackshot.update"] and r.calls[0].args == {"item_id": "s1"} and not r.calls[0].clean, r)
r = ex("async () => codemode.stackshot_update({[key]: 'v', item_id: 's1'})")
check("unreadable: a computed key", not r.ok and "computed key" in r.why and r.calls[0].args == {"item_id": "s1"}, r)
r = ex("async () => { eval('x'); return codemode.stackshot_get({id: 's1'}); }")
check("unreadable: eval", not r.ok and "eval/Function" in r.why and names(r) == ["stackshot.get"], r)
r = ex("async () => { const f = new Function('a', 'return a'); return codemode.stackshot_get({id: 's1'}); }")
check("unreadable: new Function", not r.ok and "eval/Function" in r.why, r)
r = ex("async () => codemode.stackshot_get(args)")
check("unreadable: the argument is not an object literal", not r.ok and "not an object literal" in r.why and names(r) == ["stackshot.get"] and r.calls[0].args == {}, r)
r = ex("async () => codemode.stackshot_get('s1')")
check("unreadable: a string argument", not r.ok and "not an object literal" in r.why, r)
r = ex("async () => codemode.board_stackshot_get({id: 's1'})")
check("unreadable: an unknown entry (a stale name), server None", not r.ok and "unknown entry" in r.why and r.calls[0].server is None and not r.calls[0].known and r.calls[0].tool == "board_stackshot_get", r)
r = ex("async () => codemode.brain_search({query: 'x'})")
check("unreadable: another unknown entry", not r.ok and "unknown entry" in r.why, r)
r = ex("async () => `${await codemode.stackshot_get({id: 's1'})}`")
check("unreadable: a call inside a template literal", not r.ok and "template" in r.why, r)
r = ex("async () => codemode.stackshot_update({item_id: 's1', m() { return 1 }, next: 'x'})")
check("unreadable: a method in the object", not r.ok and "method" in r.why and r.calls[0].args.get("next") == "x", r)
r = ex("async () => codemode.stackshot_update({item_id: 's1'")
check("unreadable: an unbalanced call", not r.ok and "unbalanced" in r.why, r)
r = ex("async () => codemode.stackshot_update({item_id: 's1', next: [...xs]})")
check("unreadable: a spread inside an array value", not r.ok and "spread" in r.why, r)
r = ex("async () => codemode?.stackshot_get({id: 's1'})")
check("unreadable: optional chaining", not r.ok, r)
r = ex("async () => { const x = codemode.stackshot_get; return x({id: 's1'}); }")
check("unreadable: a method taken as a value", not r.ok and "other than" in r.why, r)
r = ex("async () => mycodemode.stackshot_get({id: 's1'}) + obj.codemode.x({})")
check("a longer or qualified identifier is not codemode", r.ok and not r.calls, r)

# ---- 7. matches, own, plain
r = ex('async () => { await codemode.gbrain_put_page({slug: "projects/alpha", content: "x"}); await codemode.gacme_send_gmail_message({to: "a"}); await codemode.stackshot_brief({}); }')
m = c.matches(r.calls, ("gbrain.put_page", "gbrain.edit_page", "gbrain.add_timeline_entry"))
check("matches: exact server.tool", [x.name for x in m] == ["gbrain.put_page"], m)
check("matches: a wildcard tool", [x.name for x in c.matches(r.calls, "*.send_gmail_message")] == ["gacme.send_gmail_message"])
check("matches: a wildcard server", [x.name for x in c.matches(r.calls, ["g*.*"])] == ["gbrain.put_page", "gacme.send_gmail_message"])
check("matches: nothing", c.matches(r.calls, "stackshot.update") == [])
r2 = ex("async () => codemode.board_stackshot_get({id: 's1'})")
check("matches: an unknown entry never matches", c.matches(r2.calls, "*.*") == [])
check("plain renders DYNAMIC", c.plain({"a": c.DYNAMIC, "b": [c.DYNAMIC, 1]}) == {"a": "<dynamic>", "b": ["<dynamic>", 1]})
j = r.to_json()
check("to_json", j["route"] == "portal" and j["own"] and [x["server"] for x in j["calls"]] == ["gbrain", "gacme", "stackshot"], j)

# ---- 8. the CLI
ENV = dict(os.environ)
run = lambda *a, inp=None: subprocess.run([sys.executable, os.path.join(STACK, "stackshot/fleet/connectors.py"), *a], input=inp, capture_output=True, text=True, env=ENV)
p = run("resolve", inp=json.dumps({"tool_name": PX, "tool_input": {"code": "async () => codemode.stackshot_update({item_id: 's1', next: n})"}, "mcp_server": {"name": "claude.ai Oliver's MCP Portal (Cloudflare)", "source": "claudeai"}}))
try: out = json.loads(p.stdout)
except Exception: out = None
check("cli resolve prints the resolution with <dynamic>", p.returncode == 0 and out and out["own"] and out["calls"][0]["args"] == {"item_id": "s1", "next": "<dynamic>"}, p.stdout[-400:] + p.stderr[-300:])
p = run("prefix", "gbrain"); check("cli prefix", p.returncode == 0 and p.stdout.strip() == GB, p.stdout + p.stderr)
p = run("prefix", "portal"); check("cli prefix portal", p.returncode == 0 and p.stdout.strip() == PX.rsplit("__", 1)[0] + "__", p.stdout)
p = run("prefix", "nope"); check("cli prefix: unknown exits 1", p.returncode == 1 and not p.stdout.strip())
p = run("prefixes", "portal"); check("cli prefixes portal: the primary, then the alias", p.returncode == 0 and p.stdout.split() == [PX.rsplit("__", 1)[0] + "__", "mcp__mcp-portal__"], p.stdout + p.stderr)
p = run("prefixes", "gbrain"); check("cli prefixes: a server without aliases", p.returncode == 0 and p.stdout.split() == [GB], p.stdout)
p = run("prefixes", "nope"); check("cli prefixes: unknown exits 1", p.returncode == 1 and not p.stdout.strip())
p = run("resolve", inp=json.dumps({"tool_name": AX, "tool_input": {"code": "async () => codemode.stackshot_get({id: 's1'})"}, "mcp_server": {"name": "mcp-portal", "source": "local"}}))
try: out = json.loads(p.stdout)
except Exception: out = None
check("cli resolve by the alias", p.returncode == 0 and out and out["own"] and out["calls"][0]["server"] == "stackshot", p.stdout[-300:] + p.stderr[-300:])
p = run("servers"); check("cli servers", p.returncode == 0 and p.stdout.split() == ["gacme", "gbeta", "gbrain", "gdelta", "stackshot"], p.stdout)
p = run(); check("cli usage", p.returncode != 0 and "usage" in p.stderr)
os.replace(T / "connectors.json", T / "connectors.json.away")
p = run("prefix", "gbrain"); check("cli prefix without a catalog exits 1", p.returncode == 1)
check("resolve without a catalog → None", c.resolve(ST + "update", {}) is None)
os.replace(T / "connectors.json.away", T / "connectors.json")

# ---- 8b. cli_connectors: `claude mcp list` in a fresh empty directory, never the caller's; the claude.ai name is primary
(T / "bin").mkdir()
(T / "bin" / "claude").write_text(f'''#!/bin/sh
pwd > {tmp}/mcp-list-cwd; ls -A > {tmp}/mcp-list-ls
echo "Checking MCP server health…"
echo ""
echo "mcp-portal: https://mcp-portal.example.org/mcp (HTTP) - ✔ Connected"
echo "claude.ai Oliver's MCP Portal (Cloudflare): https://mcp-portal.example.org/mcp - ✔ Connected"
echo "plugin:productivity:notion: https://mcp.notion.com/mcp (HTTP) - ✔ Connected"
echo "claude.ai Notion: https://mcp.notion.com/mcp - ✔ Connected"
echo "a-stdio: npx some-server - ✔ Connected"
echo "plugin:x:gmail:  (HTTP) - - Not configured"
''', encoding="utf-8")
os.chmod(T / "bin" / "claude", 0o755)
old_path = os.environ["PATH"]; os.environ["PATH"] = f"{tmp}/bin:{old_path}"
here = os.getcwd()
listed, lerr = c.cli_connectors()
os.environ["PATH"] = old_path
ran_in = (T / "mcp-list-cwd").read_text().strip() if (T / "mcp-list-cwd").exists() else ""
check("cli_connectors: run in a directory other than the process cwd, empty, and removed after", ran_in and os.path.realpath(ran_in) != os.path.realpath(here) and os.path.basename(ran_in).startswith("stackshot-mcp-list-") and (T / "mcp-list-ls").read_text() == "" and not os.path.exists(ran_in), (ran_in, here))
check("cli_connectors: a host's names, the claude.ai one first", listed.get("mcp-portal.example.org") == ["claude.ai Oliver's MCP Portal (Cloudflare)", "mcp-portal"] and listed.get("mcp.notion.com") == ["claude.ai Notion", "plugin:productivity:notion"] and lerr == "", (listed, lerr))
check("cli_connectors: a stdio server and an unconfigured one are not read", set(listed) == {"mcp-portal.example.org", "mcp.notion.com"}, listed)
check("cli_connectors: the process cwd is unchanged", os.getcwd() == here)

# ---- 9. build: the join of the portal's entries and the CLI's connector list, on the upstream host
portal_api = [{"id": "mcp-portal", "name": "Oliver's MCP Portal", "hostname": "mcp-portal.example.org", "servers": [
    {"id": "stackshot", "name": "Stackshot", "hostname": "https://board.example.org/mcp", "auth_type": "bearer",
     "tools": [{"name": "brief", "annotations": {"readOnlyHint": True}}, {"name": "update"}]},
    {"id": "gbrain", "name": "gbrain", "hostname": "https://gbrain.example.org/mcp", "auth_type": "bearer",
     "tools": [{"name": "search", "annotations": {"readOnlyHint": True}}, {"name": "put_page", "annotations": {"readOnlyHint": False}}]},
    {"id": "gnew", "name": "Google Workspace new", "hostname": "https://gw-new.example.org/mcp", "auth_type": "oauth", "tools": [{"name": "send_gmail_message"}]},
]}, {"id": "other", "name": "Another portal", "hostname": "x.example.com", "servers": [{"id": "foo", "hostname": "https://foo.example.com/mcp", "tools": []}]}]
cli_list = {"board.example.org": ["claude.ai Stackshot"],
            "gbrain.example.org": ["claude.ai Brain-main", "gbrain-cli"],
            "mcp-portal.example.org": ["claude.ai Oliver's MCP Portal (Cloudflare)"],
            "mcp.notion.com": ["claude.ai Notion"]}
CJ = T / "claude.json"; c.CLAUDE_JSON = str(CJ)
CJ.write_text(json.dumps({"mcpServers": {"stackshot-user": {"type": "http", "url": "https://board.example.org/mcp", "headers": {"Authorization": "x"}},
                                         "a-stdio": {"type": "stdio", "command": "npx", "args": ["x"]}},
                          "projects": {"/home/user/api-session": {"mcpServers": {"mcp-portal": {"type": "http", "url": "https://mcp-portal.example.org/mcp"},
                                                                               "github-mcp": {"type": "http", "url": "https://api.githubcopilot.com/mcp"}}},
                                       "/home/user/other": {"mcpServers": {"portal-sse": {"type": "sse", "url": "https://MCP-PORTAL.example.org/sse"}}},
                                       "/home/user/empty": {"allowedTools": []}}}), encoding="utf-8")
calls_seen = []
c.cf_get = lambda path, token: (calls_seen.append((path, token)), portal_api)[1]
c.cli_connectors = lambda: (cli_list, "")
(T / "cf-token").write_text("tok-secret-never-printed\n")
c._cfg.CFG["portal"] = {"account_id": "acct1", "server_id": "stackshot", "token_file": f"{tmp}/cf-token", "catalog_file": f"{tmp}/connectors.json", "catalog_commit": False}
summary = c.build(quiet=True)
cat = json.loads((T / "connectors.json").read_text(encoding="utf-8"))
check("build: the portal that carries this instance, its servers", sorted(cat["servers"]) == ["gbrain", "gnew", "stackshot"] and cat["portal"]["id"] == "mcp-portal", summary)
check("build: direct names and prefixes joined on the host", cat["servers"]["stackshot"]["connector"] == "claude.ai Stackshot" and cat["servers"]["stackshot"]["prefix"] == ST and cat["servers"]["gbrain"]["prefix"] == GB, cat["servers"])
check("build: a portal entry with no direct connector yet", cat["servers"]["gnew"]["connector"] is None and cat["servers"]["gnew"]["prefix"] == "" and "no direct name for gnew" in summary, summary)
check("build: the portal's own connector and prefix", cat["portal"]["connector"] == "claude.ai Oliver's MCP Portal (Cloudflare)" and cat["portal"]["prefix"] == PX.rsplit("__", 1)[0] + "__", cat["portal"])
check("build: the portal's aliases from ~/.claude.json (a project's local server, an sse one), sorted, the primary kept",
      cat["portal"]["connector"] == "claude.ai Oliver's MCP Portal (Cloudflare)" and cat["portal"]["aliases"] == [{"connector": "mcp-portal", "prefix": "mcp__mcp-portal__"}, {"connector": "portal-sse", "prefix": "mcp__portal-sse__"}], cat["portal"])
check("build: a user-scope alias, and a second name the CLI list printed", cat["servers"]["stackshot"]["aliases"] == [{"connector": "stackshot-user", "prefix": "mcp__stackshot-user__"}]
      and cat["servers"]["gbrain"]["aliases"] == [{"connector": "gbrain-cli", "prefix": "mcp__gbrain-cli__"}] and cat["servers"]["gnew"]["aliases"] == [], cat["servers"])
check("build: the summary counts the aliases", "4 aliases" in summary, summary)
r = c.resolve(AX, {"code": "async () => codemode.gnew_send_gmail_message({to: 'x'})"}, {"name": "mcp-portal"})
check("build: a call through the alias resolves on the built catalog", r.own and names(r) == ["gnew.send_gmail_message"], r)
check("build: tools with their read-only hint", cat["servers"]["stackshot"]["tools"] == {"brief": {"read_only": True}, "update": {"read_only": False}}, cat["servers"]["stackshot"]["tools"])
check("build: the token is read from the file and never printed", calls_seen and calls_seen[0][1] == "tok-secret-never-printed" and "tok-secret" not in summary, summary)
check("build: the summary names the servers and the file", summary.startswith("connectors: 3 servers (gbrain 2, gnew 1, stackshot 2)") and summary.endswith("(written)"), summary)
r = c.resolve(PX, {"code": "async () => codemode.gnew_send_gmail_message({to: 'x'})"})
check("build: a new entry resolves at once, by its id", r.own and names(r) == ["gnew.send_gmail_message"], r)
s2 = c.build(quiet=True)
check("build: a second run changes nothing", s2.endswith("(unchanged)") and json.loads((T / "connectors.json").read_text())["generated"] == cat["generated"], s2)
c.cli_connectors = lambda: ({}, "claude mcp list: TimeoutExpired")
cli_list2 = dict(cli_list); cli_list2.pop("gbrain.example.org")
s3 = c.build(quiet=True)
cat3 = json.loads((T / "connectors.json").read_text(encoding="utf-8"))
check("build: without the CLI list the direct names are kept from the previous catalog", cat3["servers"]["gbrain"]["connector"] == "claude.ai Brain-main" and "TimeoutExpired" in s3 and "kept from the previous catalog" in cat3["sources"]["direct"], s3)
check("build: without the CLI list the aliases come from ~/.claude.json, and one only the list knew is kept", [a["connector"] for a in cat3["portal"]["aliases"]] == ["mcp-portal", "portal-sse"] and [a["connector"] for a in cat3["servers"]["gbrain"]["aliases"]] == ["gbrain-cli"], (cat3["portal"], cat3["servers"]["gbrain"]))
c.cli_connectors = lambda: (cli_list, "")
c.build(quiet=True)
CJ.write_text("{not json", encoding="utf-8")
s3b = c.build(quiet=True)
cat3b = json.loads((T / "connectors.json").read_text(encoding="utf-8"))
check("build: an unreadable ~/.claude.json keeps the previous catalog's aliases", [a["connector"] for a in cat3b["portal"]["aliases"]] == ["mcp-portal", "portal-sse"]
      and [a["connector"] for a in cat3b["servers"]["stackshot"]["aliases"]] == ["stackshot-user"] and "previous catalog" in cat3b["sources"]["aliases"] and "JSONDecodeError" in s3b, (s3b, cat3b["portal"]))
CJ.unlink()
s3c = c.build(quiet=True)
cat3c = json.loads((T / "connectors.json").read_text(encoding="utf-8"))
check("build: a missing ~/.claude.json keeps them too", [a["connector"] for a in cat3c["portal"]["aliases"]] == ["mcp-portal", "portal-sse"] and "not found" in s3c, s3c)
CJ.write_text(json.dumps({"projects": {"/home/user/api-session": {"mcpServers": {"claude.ai Oliver's MCP Portal (Cloudflare)": {"type": "http", "url": "https://mcp-portal.example.org/mcp"}}}}}), encoding="utf-8")
c.build(quiet=True)
cat3d = json.loads((T / "connectors.json").read_text(encoding="utf-8"))
check("build: a config name equal to the primary is no alias; an alias gone from the config is dropped", cat3d["portal"]["aliases"] == [] and cat3d["servers"]["stackshot"]["aliases"] == [], cat3d["portal"])
check("build: after a full read the CLI-only alias is settled by the list again", [a["connector"] for a in cat3d["servers"]["gbrain"]["aliases"]] == ["gbrain-cli"], cat3d["servers"]["gbrain"])
c.cli_connectors = lambda: (cli_list, "")
c._cfg.CFG["portal"]["server_id"] = "nowhere"
try: c.build(quiet=True); nop = ""
except SystemExit as e: nop = str(e)
check("build: no portal carries the instance → a refusal, nothing written", "no portal" in nop and "acct" not in nop.replace("acct1"[:4], "") or "no portal" in nop, nop)
c._cfg.CFG["portal"]["server_id"] = "stackshot"
# the commit: the catalog inside a git checkout with a bare origin
(T / "origin.git").mkdir(); subprocess.run(["git", "init", "-q", "--bare", str(T / "origin.git")], check=True)
repo = T / "cfg-repo"; repo.mkdir()
g = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a], capture_output=True, text=True)
g("init", "-q", "-b", "main"); (repo / "README").write_text("x\n"); g("add", "README"); g("commit", "-q", "-m", "init"); g("remote", "add", "origin", str(T / "origin.git")); g("push", "-q", "-u", "origin", "main")
(repo / "other.txt").write_text("unrelated, staged, must not ride along\n"); g("add", "other.txt")
(repo / "ctx").mkdir()
c._cfg.CFG["portal"].update({"catalog_file": f"{repo}/ctx/connectors.json", "catalog_commit": True})
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
s4 = c.build(quiet=True)
log = g("log", "--oneline", "origin/main").stdout
check("build: the catalog is committed by pathspec and pushed", "committed and pushed" in s4 and "connectors: catalog regenerated by portal-sync (3 servers)" in log, s4 + log)
check("build: the unrelated staged file stayed staged and uncommitted", "other.txt" in g("diff", "--cached", "--name-only").stdout and "other.txt" not in g("show", "--name-only", "HEAD").stdout, g("status", "--short").stdout)
s5 = c.build(quiet=True)
check("build: unchanged → no commit", s5.endswith("(unchanged)") and g("log", "--oneline").stdout.count("\n") == 2, s5 + g("log", "--oneline").stdout)
c._cfg.CFG["portal"].update({"catalog_file": f"{tmp}/connectors.json", "catalog_commit": False})
(T / "connectors.json").write_text(json.dumps(CAT, indent=1), encoding="utf-8")   # the fixture back, for pages

# ---- 10. pages.py sees the same calls by both routes
from stackshot.projects import pages as pg
wrap = lambda text: {"result": text}                    # the portal's response: the script's return, JSON-wrapped
REPLY = "updated s1.\ns1 [open] [home] Alpha thing\nproject: projects/alpha\n"
sid = lambda n: f"{n}{n}{n}{n}{n}{n}{n}{n}-{n}{n}{n}{n}-4{n}{n}{n}-8{n}{n}{n}-{n}{n}{n}{n}{n}{n}{n}{n}{n}{n}{n}{n}"
def touch(payload):
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "touch"], input=json.dumps(payload), capture_output=True, text=True, env=ENV)
    return r.returncode, r.stdout, r.stderr
state = lambda s: pg.load_state(s).get("touches", {})
rc, out, err = touch({"session_id": sid("1"), "tool_name": ST + "update", "tool_input": {"item_id": "s1", "next": "x"}, "tool_response": REPLY})
check("touch: a direct update with a state field owes its project", rc == 0 and "projects/alpha" in state(sid("1")) and state(sid("1"))["projects/alpha"]["tool"] == "update", (rc, err[-300:], state(sid("1"))))
rc, out, err = touch({"session_id": sid("2"), "tool_name": PX, "tool_input": {"code": 'async () => codemode.stackshot_update({item_id: "s1", next: "x", sender: "me"})'}, "tool_response": wrap(REPLY)})
check("touch: the same update inside a portal script owes the same", rc == 0 and "projects/alpha" in state(sid("2")) and state(sid("2"))["projects/alpha"]["task"] == "s1", (rc, err[-300:], state(sid("2"))))
rc, out, err = touch({"session_id": sid("3"), "tool_name": PX, "tool_input": {"code": 'async () => codemode.stackshot_update({item_id: "s1", owner: "x"})'}, "tool_response": wrap(REPLY)})
check("touch: a portal update that only files owes nothing", rc == 0 and not state(sid("3")), state(sid("3")))
rc, out, err = touch({"session_id": sid("4"), "tool_name": PX, "tool_input": {"code": 'async () => codemode.stackshot_get({id: "s1"})'}, "tool_response": wrap("s1 [open] …")})
check("touch: a portal read owes nothing", rc == 0 and not state(sid("4")), state(sid("4")))
rc, out, err = touch({"session_id": sid("5"), "tool_name": PX, "tool_input": {"code": 'async () => codemode.stackshot_update({item_id: "s1", next: "x"})'}, "tool_response": wrap("Refused: not yours")})
check("touch: the portal's wrapped refusal owes nothing", rc == 0 and not state(sid("5")), state(sid("5")))
rc, out, err = touch({"session_id": sid("6"), "tool_name": PX, "tool_input": {"code": 'async () => { for (const k of keys) await codemode.stackshot_complete({item_id: k, outcome: "done", reason: why}); }'}, "tool_response": wrap("updated s7.\nproject: projects/alpha\n")})
check("touch: a loop's complete with dynamic values owes, the id from the reply", rc == 0 and state(sid("6")).get("projects/alpha", {}).get("task") == "s7", state(sid("6")))
rc, out, err = touch({"session_id": sid("7"), "tool_name": PX, "tool_input": {"code": 'async () => codemode.stackshot_create({subject: "[home] x", project: key, description: "d"})'}, "tool_response": wrap("created s9.\nproject: projects/alpha\n")})
check("touch: a dynamic project is read from the reply", rc == 0 and "projects/alpha" in state(sid("7")) and state(sid("7"))["projects/alpha"]["task"] == "s9", state(sid("7")))
rc, out, err = touch({"session_id": sid("8"), "tool_name": NO + "notion-update-page", "tool_input": {}, "tool_response": "ok"})
check("touch: a foreign connector write owes nothing and exits 0", rc == 0 and not state(sid("8")), (rc, err[-200:]))
check("refused(): both shapes", pg.refused("Refused: x") and pg.refused('{"result": "Refused: x"}') and pg.refused('{"isError": true}') and not pg.refused('{"result": "updated s1"}'))
ow = lambda tool, inp, inbound=False: pg.other_write({"tool_name": tool, "tool_input": inp, "tool_response": "ok"}, inbound=inbound)
check("other_write: a stackshot message by either route", ow(ST + "message", {"to": "x"}) and ow(PX, {"code": "async () => codemode.stackshot_message({to: 'x', text: 't', sender: 'me'})"}))
check("other_write: anchors with an add, not without", ow(PX, {"code": "async () => codemode.stackshot_anchors({item_id: 's1', add: ['x']})"}) and not ow(PX, {"code": "async () => codemode.stackshot_anchors({item_id: 's1'})"}))
check("other_write: a gbrain page write counts in an inbound turn only, by either route", ow(GB + "put_page", {}, True) and ow(PX, {"code": "async () => codemode.gbrain_capture({slug: 's'})"}, True) and not ow(PX, {"code": "async () => codemode.gbrain_capture({slug: 's'})"}, False))
check("other_write: a route ruling is no write", not ow(PX, {"code": "async () => codemode.stackshot_route({notice: 'n', ruling: 'passed'})"}))
check("other_write: a foreign write is not counted here", not ow(NO + "notion-update-page", {}))
check("own_calls: a foreign call is server ''; no catalog is None", pg.own_calls(NO + "notion-fetch", {}) == [] and pg.own_calls(ST + "get", {"id": "s1"}) == [("stackshot", "get", {"id": "s1"})])
def transcript(prompt, tools, final="done"):
    f = T / f"t-{len(ran)}.jsonl"
    rows = [{"type": "user", "timestamp": "2026-06-09T00:00:00Z", "message": {"content": prompt}}]
    for n, inp in tools:
        rows.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": n, "input": inp}]}})
        rows.append({"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}})
    rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}})
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n"); return str(f)
act = lambda prompt, tools: pg.turn_activity(transcript(prompt, tools))
a = act("go", [(PX, {"code": 'async () => codemode.stackshot_update({item_id: "s1", next: "x", sender: "me"})'})])
check("turn_activity: a portal update is a stackshot write and names its item", a["writes"] and a["why"] == ["stackshot update"] and a["items"] == {"s1": True}, a)
a = act("go", [(ST + "update", {"item_id": "S2", "next": "x"})])
check("turn_activity: the direct update, the same", a["writes"] and a["items"] == {"s2": False}, a)
a = act("go", [(AX, {"code": 'async () => codemode.stackshot_update({item_id: "s4", next: "x", sender: "me"})'})])
check("turn_activity: a portal update through the alias prefix is the same stackshot write", a["writes"] and a["why"] == ["stackshot update"] and a["items"] == {"s4": True}, a)
check("other_write: a stackshot message through the alias, by name and by prefix", pg.other_write({"tool_name": AX, "tool_input": {"code": "async () => codemode.stackshot_message({to: 'x', text: 't'})"}, "tool_response": "ok", "mcp_server": {"name": "mcp-portal"}}) and ow(AX, {"code": "async () => codemode.stackshot_message({to: 'x', text: 't'})"}))
rc, out, err = touch({"session_id": sid("a"), "tool_name": AX, "tool_input": {"code": 'async () => codemode.stackshot_update({item_id: "s1", next: "x"})'}, "tool_response": wrap(REPLY), "mcp_server": {"name": "mcp-portal", "source": "local"}})
check("touch: a portal update through the alias owes its project", rc == 0 and "projects/alpha" in state(sid("a")), (rc, err[-300:], state(sid("a"))))
a = act("look", [(PX, {"code": 'async () => { const a = await codemode.stackshot_brief({}); const b = await codemode.gbrain_search({query: "x"}); return [a, b]; }'})])
check("turn_activity: portal reads of the board and the brain are nothing", not a["writes"] and a["why"] == [], a)
a = act("look", [(PX, {"code": 'async () => codemode.gacme_send_gmail_message({to: "a@b"})'})])
check("turn_activity: a portal send is a write by its verb", a["writes"] and a["why"] == ["send_gmail_message"], a)
a = act("look", [(PX, {"code": 'async () => codemode.gacme_search_gmail_messages({q: "x"})'})])
check("turn_activity: a portal Workspace read is no write", not a["writes"] and a["why"] == [], a)
a = act('[anchor] Slack #x: new message from Dana: "hi"', [(PX, {"code": 'async () => codemode.gbrain_add_timeline_entry({slug: "projects/alpha", entry: "x"})'})])
check("turn_activity: a portal timeline line in a notice's turn asks", a["writes"] and a["why"] == ["gbrain add_timeline_entry"], a)
a = act("please", [(PX, {"code": 'async () => codemode.gbrain_put_page({slug: "projects/alpha", content: "x"})'})])
check("turn_activity: a portal page write in Oliver's own turn does not", not a["writes"], a)
a = act("go", [(PX, {"code": 'async () => { for (const id of ids) await codemode.stackshot_update({item_id: id, next: "x"}); }'})])
check("turn_activity: a dynamic item id names no item but counts as a write", a["writes"] and a["items"] == {}, a)
a = act("go", [(PX, {"code": 'async () => codemode.board_stackshot_update({item_id: "s1", next: "x"})'})])
check("turn_activity: an unknown entry's call is classed by its verb", a["writes"] and a["why"] == ["board_stackshot_update"], a)
a = act("go", [(PS, {"query": "x"})])
check("turn_activity: the portal's search is no write", not a["writes"] and a["why"] == [], a)
a = act("go", [(NO + "notion-update-page", {})])
check("turn_activity: a foreign write still counts", a["writes"] and a["why"] == ["notion-update-page"], a)
os.replace(T / "connectors.json", T / "connectors.json.away")
a = act("go", [(ST + "update", {"item_id": "s3", "next": "x"}), (PX, {"code": 'async () => codemode.stackshot_update({item_id: "s1", next: "x"})'})])
check("turn_activity without a catalog: the direct names as before, the portal call unseen", a["writes"] and a["items"] == {"s3": False} and a["why"] == ["stackshot update"], a)
rc, out, err = touch({"session_id": sid("9"), "tool_name": ST + "complete", "tool_input": {"item_id": "s1", "outcome": "done"}, "tool_response": REPLY})
check("touch without a catalog: the direct complete owes as before", rc == 0 and "projects/alpha" in state(sid("9")), state(sid("9")))
os.replace(T / "connectors.json.away", T / "connectors.json")

shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": connectors scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""))
sys.exit(1 if fails else 0)
