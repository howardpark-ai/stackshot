"""Scenario: a board's lists, reads, calls and instructions text answer members only (web/middleware.py `_MembersOnly`), over real HTTP, in both of the FastMCP client's connect modes (`legacy`: the
initialize handshake; `auto`: server/discover). A throwaway instance for each part, local sockets only; no live store, no network.

Part `google` is a board with `[auth] mode = "google"` (a made-up client) and no `[behind_frontdoor]`, so the board's own sign-in says who the caller is. The Google check of a token is a stand-in
(no call reaches Google); the portal's machine token is the real one.
  * a member, a second member and the machine token: the instructions text, every list, the read of the rulebook and the calls are answered, an unknown address stays an unknown address;
  * an identity that is no member, and a token that names no address: no instructions text, every list, read, other request and call refused with the board's one sentence (a call that passes a
    retired input included: its refusal names the owner), a ping answered;
  * a member removed while a session is open is refused at the next request of that session, and let in again when listed again;
  * no token and a token nobody knows: HTTP 401, as before;
  * the standby copy: a member lists and reads as before and its writes are refused as a copy's; someone who is no member is refused as no member.

Part `door` is a board behind a front door (`[behind_frontdoor] identity_secret_file`): the same for the signed identity, and the front door in front of it with a members file of its own that lists
someone the board does not: that caller gets the board's sentence for the tool list, never "did not answer", and never the instructions text read for a member.
With a second board that is down, the tool list ends in "none of your boards answered" and the warnings tell the refusing board from the down one.

Part `off` is a board with auth off: anyone is answered, with no token or any.

    tests/run-suite members_only        -> exit 0 / 1"""
import os, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
PARTS = ("google", "door", "off")
MODES = ("legacy", "auto")
RULE = "a rule the connector serves"      # a line of the fixture's rulebook
ITEM = "door fixture item"                # the subject of the fixture's item
PERSON = "Pat Example"
READ_TOOLS = {"rules", "get", "brief", "create", "update"}


def sentence(who):
    return f"Refused: {who or 'unknown identity'} is not allowed on this board"


class Board:
    """One part's checks against one MCP endpoint."""
    def __init__(self, F, url, text):
        self.check, self.url, self.text = F.check, url, text      # text: the start of the board's own instructions

    def client(self, headers, mode):
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport
        return Client(StreamableHttpTransport(self.url, headers=headers), mode=mode)


async def outcome(coro):
    try:
        return await coro
    except Exception as e:      # noqa: BLE001  (the refusal is what is checked)
        return e


async def entries(listing, field):
    return getattr(await listing, field)


def asks(c):
    """Every list and read, and a request the board has nothing for: name -> the awaitable. The lists pass the client's response cache by, so each one asks the board."""
    return {"tools/list": entries(c.list_tools_mcp(cache_mode="bypass"), "tools"), "resources/list": entries(c.list_resources_mcp(cache_mode="bypass"), "resources"),
            "resources/templates/list": entries(c.list_resource_templates_mcp(cache_mode="bypass"), "resource_templates"),
            "prompts/list": entries(c.list_prompts_mcp(cache_mode="bypass"), "prompts"),
            "resources/read": c.read_resource("stackshot://rules"), "resources/read of an unknown address": c.read_resource("stackshot://nothing"),
            "prompts/get": c.get_prompt("nothing")}


async def answers(c):
    return {name: await outcome(a) for name, a in asks(c).items()}


def is_refusal(e, who):
    from mcp.shared.exceptions import MCPError
    from stackshot.core import frontdoor_identity as ident
    return isinstance(e, MCPError) and e.code == ident.NOT_MEMBER_CODE and e.message == sentence(who)


async def member_is_answered(B, label, headers, mode):
    from fastmcp.exceptions import ToolError
    from mcp.shared.exceptions import MCPError
    async with B.client(headers, mode) as c:
        L = f"{label} ({mode})"
        B.check(f"{L}: the client connected in the era of its mode", (c.initialize_result is None) == (mode == "auto"), (c.protocol_version,))
        B.check(f"{L}: gets the board's instructions text", B.text in (c.instructions or ""), c.instructions)
        got = await answers(c)
        tools = got["tools/list"]
        B.check(f"{L}: lists the tools", isinstance(tools, list) and READ_TOOLS <= {t.name for t in tools}, tools)
        res = got["resources/list"]
        B.check(f"{L}: lists the resources", isinstance(res, list) and "stackshot://rules" in [str(r.uri) for r in res], res)
        B.check(f"{L}: lists the resource templates and the prompts", isinstance(got["resources/templates/list"], list) and isinstance(got["prompts/list"], list), got)
        read = got["resources/read"]
        B.check(f"{L}: reads the rulebook", isinstance(read, list) and RULE in read[0].text, read)
        for name in ("resources/read of an unknown address", "prompts/get"):
            e = got[name]
            B.check(f"{L}: {name} is answered as the board answers what it does not have, not as a refusal of the caller", isinstance(e, MCPError) and "not allowed" not in str(e), repr(e))
        r = await outcome(c.call_tool("rules", {}))
        B.check(f"{L}: calls a tool with no argument", not isinstance(r, Exception) and RULE in r.content[0].text, repr(r)[:300])
        r = await outcome(c.call_tool("get", {"item_id": "a1"}))
        B.check(f"{L}: calls a tool with an argument", not isinstance(r, Exception) and ITEM in r.content[0].text, repr(r)[:300])
        e = await outcome(c.call_tool("update", {"item_id": "a1", "state": "doing"}))
        B.check(f"{L}: a retired input is refused as one", isinstance(e, ToolError) and "retired input" in str(e), repr(e)[:300])
        if mode == "legacy":      # the modern protocol has no ping
            B.check(f"{L}: a ping is answered", await outcome(c.ping()) is True)


async def stranger_is_refused(B, label, headers, mode, who):
    from fastmcp.exceptions import ToolError
    async with B.client(headers, mode) as c:
        L = f"{label} ({mode})"
        B.check(f"{L}: the client connected in the era of its mode", (c.initialize_result is None) == (mode == "auto"), (c.protocol_version,))
        B.check(f"{L}: gets no instructions text at all", c.instructions is None, c.instructions)
        for name, e in (await answers(c)).items():
            B.check(f"{L}: {name} is refused with the board's sentence", is_refusal(e, who), repr(e)[:300])
        for tool, args in (("rules", {}), ("get", {"item_id": "a1"}), ("update", {"item_id": "a1", "state": "doing"}), ("get", {"no_such_argument": 1}), ("no_such_tool", {})):
            e = await outcome(c.call_tool(tool, args))
            B.check(f"{L}: a call of {tool} with {sorted(args)} is refused with that sentence and nothing else", isinstance(e, ToolError) and str(e) == sentence(who), repr(e)[:300])
        if mode == "legacy":      # the modern protocol has no ping
            B.check(f"{L}: a ping is answered", await outcome(c.ping()) is True)


async def removed_on_an_open_session(B, label, headers, mode, who, remove, restore):
    from fastmcp.exceptions import ToolError
    async with B.client(headers, mode) as c:
        L = f"{label} ({mode})"
        before = await answers(c)
        B.check(f"{L}: while listed, the open session lists and reads", isinstance(before["tools/list"], list) and isinstance(before["resources/read"], list), before)
        remove()
        try:
            for name, e in (await answers(c)).items():
                B.check(f"{L}: once removed, {name} on the same session is refused", is_refusal(e, who), repr(e)[:300])
            e = await outcome(c.call_tool("get", {"item_id": "a1"}))
            B.check(f"{L}: and so is a call", isinstance(e, ToolError) and str(e) == sentence(who), repr(e)[:300])
            async with B.client(headers, mode) as again:
                B.check(f"{L}: and a new session gets no instructions text", again.instructions is None, again.instructions)
                e = await outcome(entries(again.list_tools_mcp(cache_mode="bypass"), "tools"))
                B.check(f"{L}: ... and no tool list", is_refusal(e, who), repr(e)[:300])
        finally:
            restore()
        after = await answers(c)
        B.check(f"{L}: listed again, the session lists and reads", isinstance(after["tools/list"], list) and isinstance(after["resources/read"], list), after)


class Skipped:
    """The records of the MCP library's logger that says a tool call's header check was skipped because its own tool listing failed."""
    def __init__(self):
        import logging
        got = self.got = []
        class Keep(logging.Handler):
            def emit(self, record): got.append(record.getMessage())
        log = logging.getLogger("mcp.server._streamable_http_modern")
        log.addHandler(Keep()); log.propagate = False


# ================================================================ part google: the board's own sign-in
def part_google():
    import asyncio, re
    sys.path.insert(0, SCR); sys.path.insert(0, STACK)
    from frontdoor_board_scenario import Fixture, exchange, serve, setup, stop
    T, _secret, _paths = setup("off")
    F = Fixture(); check = F.check
    OWNER, SECOND, STRANGER, PORTAL = "owner@example.test", "second@example.test", "stranger@example.test", "portal-" + "p" * 40
    conf = T / "stackshot.toml"
    toml, n = re.subn(r'(?m)^portal_identity = ""', f'portal_identity = "{OWNER}"', conf.read_text(encoding="utf-8")); assert n == 1
    toml += f'\n[[members]]\nname = "{PERSON}"\nemails = ["{OWNER}"]\n\n[[members]]\nname = "Sam Example"\nemails = ["{SECOND}"]\n'
    conf.write_text(toml, encoding="utf-8")
    os.environ.update(STACKSHOT_AUTH="google", STACKSHOT_GOOGLE_CLIENT_ID="client.example.test", STACKSHOT_GOOGLE_CLIENT_SECRET="made-up", STACKSHOT_PORTAL_TOKEN=PORTAL)
    import logging; logging.disable(logging.INFO)
    from fastmcp.server.auth import AccessToken
    from fastmcp.server.auth.providers.google import GoogleProvider
    KNOWN = {"token-owner": OWNER, "token-second": SECOND, "token-stranger": STRANGER, "token-no-address": ""}
    async def stand_in(self, token):
        if token not in KNOWN:
            return None
        return AccessToken(token=token, client_id="test", scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"], expires_at=None,
                           claims={"email": KNOWN[token]} if KNOWN[token] else {})
    GoogleProvider.verify_token = stand_in
    from stackshot.core import config as cfgmod, readonly as ro
    from stackshot.web import server
    skipped = Skipped()
    srv, th, sock, port = serve(server.mcp.http_app())
    B = Board(F, f"http://127.0.0.1:{port}/mcp", server.mcp.instructions[:80])
    bearer = lambda t: {"authorization": "Bearer " + t}
    try:
        assert len(B.text) == 80
        for mode in MODES:
            for label, token in (("a member", "token-owner"), ("a second member", "token-second"), ("the machine token", PORTAL)):
                asyncio.run(member_is_answered(B, label, bearer(token), mode))
        check("members: no call of a member had the library's own tool listing fail", skipped.got == [], skipped.got[:3])
        everyone = list(cfgmod.CFG["members"])
        # the empty list of the library's own listing inside a call is no way in: a request that only claims to be a call gets nothing by it
        async def claims_a_call():
            async with B.client({**bearer("token-stranger"), "mcp-method": "tools/call"}, "legacy") as c:
                return await answers(c)
        got = asyncio.run(claims_a_call())
        check("a stranger whose requests claim to be tool calls gets an empty tool list at most", got.pop("tools/list") == [], got)
        check("... and is refused everything else", all(is_refusal(e, STRANGER) for e in got.values()), got)
        for mode in MODES:
            asyncio.run(stranger_is_refused(B, "a stranger", bearer("token-stranger"), mode, STRANGER))
            asyncio.run(stranger_is_refused(B, "a token that names no address", bearer("token-no-address"), mode, ""))
            asyncio.run(removed_on_an_open_session(B, "a removed member", bearer("token-second"), mode, SECOND,
                                                   lambda: cfgmod.CFG.__setitem__("members", everyone[:1]), lambda: cfgmod.CFG.__setitem__("members", everyone)))
            cfgmod.CFG["members"] = everyone[:1]
            try:
                asyncio.run(stranger_is_refused(B, "a member removed before the session", bearer("token-second"), mode, SECOND))
            finally:
                cfgmod.CFG["members"] = everyone

        check("no refused call, a stranger's included, had the library's own tool listing fail", skipped.got == [], skipped.got[:3])

        # the bytes of the handshake
        st, body, _h = exchange(B.url, bearer("token-owner"))
        check("raw: a member's initialize reply carries the instructions", st == 200 and '"instructions"' in body, (st, body[:300]))
        st, body, _h = exchange(B.url, bearer("token-stranger"))
        check("raw: a stranger's initialize reply names the server and carries no instructions, no name and no rule", st == 200 and '"serverInfo"' in body and '"instructions"' not in body and PERSON not in body and RULE not in body, (st, body[:600]))

        # no token, and one nobody knows
        for label, headers in (("no token", {}), ("an unknown token", bearer("token-nobody"))):
            st, body, h = exchange(B.url, headers)
            check(f"{label}: HTTP 401 and nothing of the board", st == 401 and len(h) == 1 and '"instructions"' not in body and RULE not in body, (st, body[:200], h))
            for mode in MODES:
                async def connect():
                    async with B.client(headers, mode) as c:
                        return await c.list_tools()
                e = asyncio.run(outcome(connect()))
                check(f"{label} ({mode}): no client session lists anything", isinstance(e, Exception), repr(e)[:300])

        # the standby copy
        was = ro.is_read_only()
        ro._reload_for_test(True)
        try:
            async def copy(headers, mode):
                async with B.client(headers, mode) as c:
                    return await answers(c), await outcome(c.call_tool("create", {"subject": "[home] x", "description": "y"}))
            for mode in MODES:
                got, e = asyncio.run(copy(bearer("token-owner"), mode))
                check(f"standby copy ({mode}): a member lists and reads", isinstance(got["tools/list"], list) and isinstance(got["resources/read"], list) and RULE in got["resources/read"][0].text, got)
                check(f"standby copy ({mode}): and a member's write is refused as the copy refuses it", isinstance(e, Exception) and "not allowed" not in str(e) and "read-only" in str(e).lower(), repr(e)[:300])
                got, e = asyncio.run(copy(bearer("token-stranger"), mode))
                check(f"standby copy ({mode}): a stranger is refused every list and read", all(is_refusal(x, STRANGER) for x in got.values()), got)
                check(f"standby copy ({mode}): and a stranger's write is refused as a stranger's", isinstance(e, Exception) and str(e) == sentence(STRANGER), repr(e)[:300])
        finally:
            ro._reload_for_test(was)
    finally:
        stop(srv, th, sock)
    return F.ran, F.fails


# ================================================================ part door: behind a front door, and the front door itself
def part_door():
    import asyncio, json, socket
    sys.path.insert(0, SCR); sys.path.insert(0, STACK)
    from frontdoor_board_scenario import Fixture, serve, setup, stop
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    T, secret, paths = setup("on")
    F = Fixture(); check = F.check
    import logging; logging.disable(logging.WARNING)
    from stackshot.core import frontdoor_config as fc, frontdoor_identity as ident
    from stackshot.frontdoor import app as fdapp
    from stackshot.web import server
    ALICE, BOB, CAROL, DAVE = "alice@example.test", "bob@example.test", "carol@example.test", "dave@example.test"
    KEY = b"door-secret-0123456789abcdef"
    listed = {ALICE: ["main", "side"], BOB: ["side"], CAROL: ["main"]}
    members = T / "members.json"
    def write(d): members.write_text(json.dumps(d))
    signed = lambda who: {ident.HEADER: ident.sign(KEY, who)}
    skipped = Skipped()
    srv, th, sock, port = serve(server.mcp.http_app())
    BASE = f"http://127.0.0.1:{port}"
    B = Board(F, BASE + "/mcp", server.mcp.instructions[:80])
    front = None
    try:
        for mode in MODES:
            asyncio.run(member_is_answered(B, "behind a door: a member", signed(ALICE), mode))
        check("behind a door: no call of a member had the library's own tool listing fail", skipped.got == [], skipped.got[:3])
        for mode in MODES:
            asyncio.run(stranger_is_refused(B, "behind a door: a member of another board", signed(BOB), mode, BOB))
            asyncio.run(stranger_is_refused(B, "behind a door: an identity the file does not list", signed(DAVE), mode, DAVE))
            asyncio.run(removed_on_an_open_session(B, "behind a door: a removed member", signed(CAROL), mode, CAROL,
                                                   lambda: write({ALICE: ["main"]}), lambda: write(listed)))

        check("behind a door: no refused call had the library's own tool listing fail", skipped.got == [], skipped.got[:3])

        # the front door, whose members file lists on "main" someone the board does not
        door_members = T / "door-members.json"
        door_members.write_text(json.dumps({ALICE: ["main"], BOB: ["main"]}))
        settings, problems = fc.parse({"frontdoor": {"identity_header": "x-forwarded-user", "identity_secret_file": paths["secret"], "members_file": str(door_members),
                                                     "backends": [{"name": "main", "kind": "board", "url": B.url, "health_url": BASE + "/healthz",
                                                                   "token_file": secret("board.token", "BOARDTOKEN-0123456789abcdef")}]}})
        assert not problems, problems
        app, door = fdapp.build(settings)
        front = serve(fdapp.asgi_app(app, door))
        D = Board(F, f"http://127.0.0.1:{front[3]}/mcp", B.text)

        async def through(who):
            async with D.client({"x-forwarded-user": who}, "legacy") as c:
                return c.instructions or "", await outcome(entries(c.list_tools_mcp(cache_mode="bypass"), "tools")), await outcome(c.call_tool("get", {"item_id": "a1"}))
        def refused(label):
            ins, tools, got = asyncio.run(through(BOB))
            check(f"front door: {label}: no text of the board's instructions", "You are on: board main." in ins and B.text not in ins and "--- instructions of" not in ins, ins[:600])
            check(f"front door: {label}: the tool list ends in the board's sentence, not in a board that did not answer", isinstance(tools, Exception) and sentence(BOB) in str(tools) and "none of your boards answered" not in str(tools), repr(tools)[:300])
            check(f"front door: {label}: a call ends in it too", isinstance(got, Exception) and sentence(BOB) in str(got), repr(got)[:300])
        def answered(label, who):
            ins, tools, got = asyncio.run(through(who))
            check(f"front door: {label}: the board's instructions, its tools and a call", B.text in ins and isinstance(tools, list) and "get" in {t.name for t in tools}
                  and not isinstance(got, Exception) and ITEM in got.content[0].text, (ins[:200], repr(tools)[:200], repr(got)[:200]))
        refused("someone the board does not list, first to ask")
        answered("a member after them", ALICE)
        refused("someone the board does not list, after a member")
        write({**listed, BOB: ["main"]})
        try:
            answered("listed by the board a moment later", BOB)
        finally:
            write(listed)

        # a second board, which is down: the two reasons are told apart, and the list does not end in one board's refusal when another did not answer
        door_members.write_text(json.dumps({BOB: ["main", "side"]}))
        gone = socket.socket(); gone.bind(("127.0.0.1", 0)); down = f"http://127.0.0.1:{gone.getsockname()[1]}"      # bound and never listening: a connection is refused
        two = [{"name": n, "kind": "board", "url": u + "/mcp", "health_url": u + "/healthz", "token_file": secret(f"{n}.token", "BOARDTOKEN-0123456789abcdef")}
               for n, u in (("main", BASE), ("side", down))]
        settings, problems = fc.parse({"frontdoor": {"identity_header": "x-forwarded-user", "identity_secret_file": paths["secret"], "members_file": str(door_members), "backends": two}})
        assert not problems, problems
        stop(*front[:3]); front = None
        app, door = fdapp.build(settings)
        front = serve(fdapp.asgi_app(app, door))
        async def both():
            warned = []
            async def hear(m): warned.append(str(m.data))
            transport = StreamableHttpTransport(f"http://127.0.0.1:{front[3]}/mcp", headers={"x-forwarded-user": BOB})
            async with Client(transport, mode="legacy", log_handler=hear) as c:
                return await outcome(c.list_tools_mcp(cache_mode="bypass")), warned
        try:
            e, warned = asyncio.run(both())
        finally:
            gone.close()
        check("front door, one board refusing and one down: the list says no board answered", isinstance(e, Exception) and "none of your boards answered (main, side)" in str(e), repr(e)[:300])
        check("front door, one board refusing and one down: the warnings say which refused the caller, in its own words, and which is down",
              any("board 'main' refused this caller" in w and sentence(BOB) in w for w in warned) and any("board 'side' did not list its tools" in w for w in warned)
              and not any("board 'main' did not" in w for w in warned), warned)
    finally:
        if front:
            stop(*front[:3])
        stop(srv, th, sock)
    return F.ran, F.fails


# ================================================================ part off: auth off
def part_off():
    import asyncio
    sys.path.insert(0, SCR); sys.path.insert(0, STACK)
    from frontdoor_board_scenario import Fixture, serve, setup, stop
    setup("off")
    F = Fixture()
    import logging; logging.disable(logging.INFO)
    from stackshot.web import server
    skipped = Skipped()
    srv, th, sock, port = serve(server.mcp.http_app())
    B = Board(F, f"http://127.0.0.1:{port}/mcp", server.mcp.instructions[:80])
    try:
        for mode in MODES:
            asyncio.run(member_is_answered(B, "auth off: no token", {}, mode))
            asyncio.run(member_is_answered(B, "auth off: any token", {"authorization": "Bearer anything"}, mode))
        F.check("auth off: no call had the library's own tool listing fail", skipped.got == [], skipped.got[:3])
        tools = asyncio.run(server.mcp.list_tools())
        F.check("auth off: the listing a program makes in its own process (tools/tool_text.py) is answered", READ_TOOLS <= {t.name for t in tools}, tools[:3])
    finally:
        stop(srv, th, sock)
    return F.ran, F.fails


MARK = "@@members_only part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"google": part_google, "door": part_door, "off": part_off}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0)      # nothing a thread of the part left behind holds the process (tests/_scratch.py removes the scratch folder first)
    total = bad = 0
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], stdout=subprocess.PIPE, text=True, timeout=600)
        seen = [l for l in r.stdout.splitlines() if l.startswith(MARK + " ")]
        print("\n".join(l for l in r.stdout.splitlines() if not l.startswith(MARK + " ")))
        if r.returncode != 0 or len(seen) != 1:
            print(f"FAIL part {name} did not end cleanly (exit {r.returncode})"); bad += 1; continue
        _, _, _, n, f = seen[0].split(); total += int(n); bad += int(f)
        print(f"part {name}: {int(n) - int(f)}/{n} checks passed")
    if bad:
        print(f"\n{bad} failures in {total} checks"); sys.exit(1)
    print(f"ok: members only scenario, {total} checks")
