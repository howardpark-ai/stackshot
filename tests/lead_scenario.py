"""Scenario test for the "call rules first" lead on every tool description (server.py `_lead`, 2026-10-04) — fixture data,
no live store, no network.

A session behind the Cloudflare MCP portal (cloud, Cowork) never receives the server's `instructions=` paragraph, only the
tool descriptions it lists, so every tool but `rules` opens its description with the directive. Checked through an MCP
`tools/list` against the server (fastmcp's in-memory client), the way a session discovers the tools.

    tests/run-suite lead        → exit 0 / 1"""
import asyncio, json, logging, os, pathlib, re, sys, tempfile
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="leadtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off"); os.environ.pop("STACKSHOT_FLEET_DIR", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "secrets", "touch", "brain/projects"): (T / d).mkdir(parents=True)
(T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

from stackshot.web import server
from fastmcp import Client
LEAD = "If your session did not load"   # only a session without the rulebook (cloud, Cowork) is told to call rules

async def listed():
    async with Client(server.mcp) as c:
        return {t.name: t.description or "" for t in await c.list_tools()}

tools = asyncio.run(listed())
check("tools/list answers with the board's tools, rules among them", "rules" in tools and len(tools) >= 10, sorted(tools))
missing = sorted(n for n, d in tools.items() if n != "rules" and not d.startswith(LEAD))
check("every tool but rules opens its description with the rules lead", not missing, missing)
check("rules does not carry the lead (its own text already says to call it)", not tools.get("rules", "").startswith(LEAD) and tools.get("rules", "").count(LEAD) == 0, tools.get("rules"))
check("no description carries the lead twice", all(d.count(LEAD) <= 1 for d in tools.values()), [n for n, d in tools.items() if d.count(LEAD) > 1])
check("the lead is addressed to sessions without the rulebook only", all("call the rules tool first" in d[:200] and "FIRST, once per task" not in d for n, d in tools.items() if n != "rules"), [n for n, d in tools.items() if "FIRST, once per task" in d])
check("the lead names the owner, not a placeholder", all(server.OWNER in d[:200] for n, d in tools.items() if n != "rules"), server.OWNER)
check("the text after the lead is each tool's own description (get: the lead, then its own text from \"Read one item by id as shown\", ending with the stall form)", tools.get("get", "").startswith(server._lead("Read one item by id as shown")) and tools.get("get", "").endswith(server._STALL_FORM), tools.get("get"))

instr = server.mcp.instructions or ""
check("the instructions teach the shown id form: board#<n>, the temporary one, and the older letter ids, never a store id",
      "board#<n>" in instr and f"{server._gh.local_prefix()}#<n>" in instr and "<letter><n> for older items" in instr
      and f"never a store id such as {server._gh.letter()}7" in instr and "new items are" not in instr, instr)

print(("ok" if not fails else "FAILED") + f": lead scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
