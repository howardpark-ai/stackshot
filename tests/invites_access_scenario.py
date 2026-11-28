"""Scenario: what each signed-in caller of a board that can invite reads and writes, over real HTTP, in both of the FastMCP client's connect modes: a signed-in stranger, an invited person before
and after the registration, an invited address whose sign-in the registration refuses, the same person once removed, and a member written by hand who is removed. A throwaway instance for each part,
local sockets only; the check of a Google token is a table (no call reaches Google).

Part `direct` is a board with `[invites]`, `[auth] mode = "google"` (a made-up client) and no `identity_secret_file`, so the board's own sign-in says who the caller is.
Part `door` is the same board behind a front door (`identity_secret_file`), with the real sign-in service and front door in front of it; the test sends the front door the header the proxy would copy
from the service's answer.

Whoever is not let in gets no text of the board's instructions, no list, no read (the rulebook included), no tool call and no write: the store and the brain stay byte for byte as they were.
A member and a joined invitee read the rulebook, the tool list and an item, and write; only an admin invites.

    tests/run-suite invites_access        -> exit 0 / 1"""
import os, subprocess, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
from members_only_scenario import ITEM, MODES, READ_TOOLS, RULE, Board, answers, entries, member_is_answered, outcome, removed_on_an_open_session, sentence

PARTS = ("direct", "door")
ADMIN, MEMBER, NEW, STRANGER = "alice@example.com", "bob@example.com", "new@example.com", "stranger@example.com"
HAND = {"alice": {"boards": ["main"], "emails": [ADMIN]}, "bob": {"boards": ["main"], "emails": [MEMBER]}}
# token -> what Google's check says of it
TOKENS = {"token-alice": (ADMIN, "900", "true"), "token-bob": (MEMBER, "901", "true"), "token-stranger": (STRANGER, "902", "true"),
          "token-new": (NEW, "111", "true"), "token-new-unverified": (NEW, "111", "false"), "token-new-second": (NEW, "222", "true")}
# one call of each tool that writes, with arguments that would write something were it let through
WRITES = (("create", {"subject": "[home] an item of someone not let in", "description": "- Goal: a thing that lives here", "next": "- sparrow: write the thing",
                     "project": "projects/alpha", "sender": "sparrow"}),
          ("update", {"item_id": "a1", "description": "- Goal: changed by someone not let in", "sender": "sparrow"}),
          ("complete", {"item_id": "a1", "outcome": "done", "reason": "someone not let in", "outcome_text": "- someone not let in closed it", "sender": "sparrow"}),
          ("confirm", {"item_id": "a1"}), ("message", {"to": "sparrow", "text": "hello", "sender": "sparrow"}), ("route", {"text": "hello"}),
          ("anchors", {"project": "projects/alpha", "add": ["github:example/example#1"]}), ("bump_versions", {}), ("invite", {"address": "friend@example.com"}),
          ("invite", {"address": MEMBER, "remove": True}))


def build(part):
    """The instance of a part → (T, the verify secret, the identity secret's file, the members file, the paths, put) where put(entries) writes the members file."""
    import json, re
    from frontdoor_board_scenario import setup
    T, secret, paths = setup("off")      # a store with one item, a rulebook
    members = T / "members.json"

    def put(d):
        members.write_text(json.dumps(d), encoding="utf-8")
    put(HAND)
    paths["verify"] = secret("verify.key", "verify-secret-0123456789abcdef")
    paths["bearer"] = secret("board.token", "portal-token-for-this-test-" + "0" * 16)
    conf = T / "stackshot.toml"
    toml = conf.read_text(encoding="utf-8")
    toml, n = re.subn(r'(?m)^base_url = "[^"]*"', 'base_url = "https://board.example.com"', toml); assert n == 1
    toml, n = re.subn(r'(?m)^mode = "google"', 'mode = "google"', toml); assert n == 1
    toml, n = re.subn(r'(?m)^portal_identity = ""', f'portal_identity = "{ADMIN}"', toml); assert n == 1      # the machine token, which the front door calls with
    # no publish pass during the test: it writes the project record a few seconds after a member's write, and would show up as a change made while someone else was being refused
    toml, n = re.subn(r'(?m)^debounce_seconds = \d+', 'debounce_seconds = 3600', toml); assert n == 1
    toml += f'\n[behind_frontdoor]\nverify_secret_file = "{paths["verify"]}"\nmembers_file = "{members}"\nboard_name = "main"\n'
    if part == "door":
        toml += f'identity_secret_file = "{paths["secret"]}"\n'
    toml += '\n[invites]\nadmins = ["alice"]\n'
    conf.write_text(toml, encoding="utf-8")
    os.environ.update(STACKSHOT_AUTH="google", STACKSHOT_GOOGLE_CLIENT_ID="client.example.com", STACKSHOT_GOOGLE_CLIENT_SECRET="made-up",
                      STACKSHOT_PORTAL_TOKEN="portal-token-for-this-test-" + "0" * 16)
    from fastmcp.server.auth import AccessToken
    from fastmcp.server.auth.providers.google import GoogleProvider

    async def stand_in(self, token):
        if token not in TOKENS:
            return None
        email, sub, verified = TOKENS[token]
        return AccessToken(token=token, client_id="test", scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"], expires_at=None,
                           claims={"email": email, "sub": sub, "email_verified": verified})
    GoogleProvider.verify_token = stand_in
    return T, members, paths, put


def held(T):
    """Every file of the board's store and brain, byte for byte."""
    return {str(p.relative_to(T)): p.read_bytes() for root in ("store", "brain") for p in sorted((T / root).rglob("*")) if p.is_file()}


def changed(T, before):
    """The files of the store and the brain that differ from `before`."""
    now = held(T)
    return sorted(k for k in {*before, *now} if before.get(k) != now.get(k))


def account(members):
    import json
    return json.loads(members.read_text(encoding="utf-8")).get(NEW, {}).get("invited", {}).get("google_sub")


async def text_of(c, tool, args):
    r = await outcome(c.call_tool(tool, args))
    return r if isinstance(r, Exception) else r.content[0].text


async def writes_and_does_not_invite(B, T, label, headers, mode):
    """A member who is no admin changes an item and is refused the invite tool."""
    from fastmcp.exceptions import ToolError
    from stackshot.web.tools import invite
    async with B.client(headers, mode) as c:
        L = f"{label} ({mode})"
        words = f"- Goal: written in {mode} mode, mark {len(B.check.__self__.ran)}"
        r = await text_of(c, "update", {"item_id": "a1", "description": words, "sender": "sparrow"})
        B.check(f"{L}: writes: the item holds the new words", not isinstance(r, Exception) and words in (T / "store/a/1.json").read_text(encoding="utf-8"), r)
        r = await text_of(c, "get", {"item_id": "a1"})
        B.check(f"{L}: ... and reads them back", isinstance(r, str) and words in r, r)
        for args in ({"address": "friend@example.com"}, {"address": ADMIN, "remove": True}):
            e = await text_of(c, "invite", args)
            B.check(f"{L}: is no admin: invite with {sorted(args)} is refused", isinstance(e, ToolError) and str(e) == invite.NOT_ADMIN, e)


async def admin_invites(B, label, headers, mode, args):
    async with B.client(headers, mode) as c:
        r = await text_of(c, "invite", args)
        want = "Removed the registration of" if args.get("remove") else "Registered"
        B.check(f"{label} ({mode}): the admin's invite is taken", isinstance(r, str) and r.startswith(want), r)


# ================================================================ part direct: the board's own sign-in
def part_direct():
    import asyncio
    from frontdoor_board_scenario import Fixture, serve, stop
    T, members, paths, put = build("direct")
    F = Fixture(); check = F.check
    import logging; logging.disable(logging.WARNING)
    from fastmcp.exceptions import ToolError
    from mcp.shared.exceptions import MCPError
    from stackshot.core import frontdoor_identity as ident, invites
    from stackshot.web import server
    S = invites.settings()
    assert S.on, invites.notes()
    srv, th, sock, port = serve(server.mcp.http_app())
    B = Board(F, f"http://127.0.0.1:{port}/mcp", server.mcp.instructions[:80])
    bearer = lambda t: {"authorization": "Bearer " + t}
    barred = lambda why: f"Refused: {NEW} is not let in. {ident.REFUSALS[why]}"
    try:
        async def tool_names():
            async with B.client(bearer("token-bob"), "legacy") as c:
                return sorted(t.name for t in await c.list_tools())
        tools = asyncio.run(tool_names())
        check("the tool list a member gets has the read tools, the write tools and invite", READ_TOOLS | {n for n, _a in WRITES} <= set(tools), tools)

        async def not_let_in(c, L, said):
            for name, e in (await answers(c)).items():
                check(f"{L}: {name} is refused", isinstance(e, MCPError) and e.code == ident.NOT_MEMBER_CODE and e.message == said, repr(e)[:300])
            before = held(T)
            for tool, args in [(n, {}) for n in tools] + list(WRITES):
                e = await outcome(c.call_tool(tool, args))
                check(f"{L}: a call of {tool} with {sorted(args)} is refused", isinstance(e, ToolError) and str(e) == said, repr(e)[:300])
            check(f"{L}: nothing in the store or the brain changed", not changed(T, before), changed(T, before))

        def refused(label, token, mode, said):
            async def run():
                async with B.client(bearer(token), mode) as c:
                    L = f"{label} ({mode})"
                    check(f"{L}: gets no instructions text", c.instructions is None, c.instructions)
                    await not_let_in(c, L, said)
            file_before = members.read_bytes()
            asyncio.run(run())
            check(f"{label} ({mode}): the members file is as it was", members.read_bytes() == file_before, members.read_text())

        async def removed_while_open(mode):
            async with B.client(bearer("token-new"), mode) as c:
                L = f"an invitee removed on an open session ({mode})"
                check(f"{L}: lists and reads while registered", isinstance((await answers(c))["resources/read"], list))
                await admin_invites(B, L, bearer("token-alice"), mode, {"address": NEW, "remove": True})
                await not_let_in(c, L, sentence(NEW))

        async def would_write():
            """The refused writes above are worth refusing: from a member, the same create, update and complete change the store."""
            async with B.client(bearer("token-alice"), "legacy") as c:
                for tool, args in sorted((w for w in WRITES if w[0] in ("create", "update", "complete")), key=lambda w: ("update", "create", "complete").index(w[0])):
                    before = held(T)
                    r = await text_of(c, tool, args)
                    check(f"the same call of {tool} from a member writes", not isinstance(r, Exception) and bool(changed(T, before)), r)

        for mode in MODES:
            put(HAND)
            asyncio.run(member_is_answered(B, "a member written by hand", bearer("token-bob"), mode))
            refused("a signed-in stranger", "token-stranger", mode, sentence(STRANGER))
            refused("an invitee before being added", "token-new", mode, sentence(NEW))
            asyncio.run(writes_and_does_not_invite(B, T, "a member written by hand", bearer("token-bob"), mode))
            check(f"a member who is no admin registers nobody ({mode})", account(members) is None)
            asyncio.run(admin_invites(B, "adding the invitee", bearer("token-alice"), mode, {"address": NEW}))
            check(f"added, not signed in yet: no account is recorded ({mode})", account(members) == "", members.read_text())
            refused("an invitee whose address Google does not report as verified", "token-new-unverified", mode, barred("unverified"))
            refused("a signed-in stranger, once someone is invited", "token-stranger", mode, sentence(STRANGER))
            asyncio.run(member_is_answered(B, "an invitee after being added", bearer("token-new"), mode))
            check(f"the first verified sign-in records its account ({mode})", account(members) == "111", members.read_text())
            asyncio.run(writes_and_does_not_invite(B, T, "an invitee after being added", bearer("token-new"), mode))
            refused("another Google account of the invited address", "token-new-second", mode, barred("other_account"))
            asyncio.run(removed_on_an_open_session(B, "a removed invitee", bearer("token-new"), mode, NEW, lambda: invites.remove(NEW, S), lambda: invites.register(NEW, "alice", S)))
            asyncio.run(removed_while_open(mode))
            refused("a removed invitee, on a new session", "token-new", mode, sentence(NEW))
            asyncio.run(member_is_answered(B, "a member, after the invitee's removal", bearer("token-bob"), mode))
            put({"alice": HAND["alice"]})
            refused("a removed member written by hand", "token-bob", mode, sentence(MEMBER))
        put(HAND)
        asyncio.run(would_write())      # last: it closes the fixture's item
    finally:
        stop(srv, th, sock)
    return F.ran, F.fails


# ================================================================ part door: the sign-in service and the front door in front of the board
def part_door():
    import asyncio, time
    from dataclasses import replace
    from frontdoor_board_scenario import Fixture, serve, stop
    T, members, paths, put = build("door")
    F = Fixture(); check = F.check
    import logging; logging.disable(logging.WARNING)
    import httpx
    from fastmcp.exceptions import ToolError
    from mcp.shared.exceptions import MCPError
    from stackshot.core import frontdoor_config as fc, frontdoor_identity as ident, frontdoor_signin_config as sc
    from stackshot.frontdoor import app as fdapp, signin
    from stackshot.web import server
    board = serve(server.mcp.http_app())
    base = f"http://127.0.0.1:{board[3]}"
    own = server.mcp.instructions[:80]
    started = [board]
    try:
        settings, problems = fc.parse({"frontdoor": {"identity_header": "x-verified-user", "identity_secret_file": paths["secret"], "members_file": str(members),
                                                     "backends": [{"name": "main", "kind": "board", "url": base + "/mcp", "health_url": base + "/healthz", "token_file": paths["bearer"]}]}})
        assert not problems, problems
        front, door_rt = fdapp.build(settings)
        started.append(serve(fdapp.asgi_app(front, door_rt)))
        D = Board(F, f"http://127.0.0.1:{started[-1][3]}/mcp", own)
        sapp, _svc = signin.build(replace(sc.parse({})[0], present=True, port=1, board_verify_url=base + "/frontdoor/verify", verify_secret_file=paths["verify"], members_file=str(members),
                                          timeout_seconds=20.0, cache_seconds=60.0))
        started.append(serve(sapp))
        later = [0.0]
        signin.CLOCK = lambda: time.monotonic() + later[0]      # the sign-in service's cache clock, which the test moves past the window between its rounds
        signer = f"http://127.0.0.1:{started[-1][3]}"

        def proxy(token):
            """The header the proxy sends the front door for this token, from the sign-in service's answer."""
            r = httpx.get(signer + "/verify", headers={"authorization": "Bearer " + token}, timeout=30)
            check(f"the sign-in service answers for {token}", r.status_code == 200 and r.headers.get("x-verified-user"), (r.status_code, r.text[:200]))
            return {"x-verified-user": r.headers.get("x-verified-user", "-")}

        async def tool_names():
            async with D.client(proxy("token-bob"), "legacy") as c:
                return sorted(t.name for t in await c.list_tools())
        tools = asyncio.run(tool_names())
        check("the tool list a member gets through the door has the read tools, the write tools and invite", READ_TOOLS | {n for n, _a in WRITES} <= set(tools), tools)

        async def not_let_in(c, L, says):
            got = await answers(c)
            e = got["tools/list"]
            check(f"{L}: the tool list is refused in the door's words", isinstance(e, MCPError) and says in e.message, repr(e)[:300])
            for name, e in got.items():      # whatever the door answers to the rest, it holds nothing of the board
                check(f"{L}: {name} gives nothing of the board", (isinstance(e, Exception) or e == []) and RULE not in str(e) and ITEM not in str(e), repr(e)[:300])
            before = held(T)
            for tool, args in [(n, {}) for n in tools] + list(WRITES):
                e = await outcome(c.call_tool(tool, args))
                check(f"{L}: a call of {tool} with {sorted(args)} is refused", isinstance(e, ToolError) and says in str(e) and RULE not in str(e), repr(e)[:300])
            check(f"{L}: nothing in the store or the brain changed", not changed(T, before), changed(T, before))

        def refused(label, token, mode, says):
            headers = proxy(token)

            async def run():
                async with D.client(headers, mode) as c:
                    L = f"{label} ({mode})"
                    text = c.instructions or ""
                    check(f"{L}: gets no text of the board's instructions", own not in text and "--- instructions of" not in text, text[:600])
                    await not_let_in(c, L, says)
            file_before = members.read_bytes()
            asyncio.run(run())
            check(f"{label} ({mode}): the members file is as it was", members.read_bytes() == file_before, members.read_text())

        def answered(label, token, mode):
            headers = proxy(token)

            async def run():
                async with D.client(headers, mode) as c:
                    L = f"{label} ({mode})"
                    check(f"{L}: gets the board's instructions text", own in (c.instructions or ""), (c.instructions or "")[:600])
                    got = await outcome(entries(c.list_tools_mcp(cache_mode="bypass"), "tools"))
                    check(f"{L}: lists the tools", isinstance(got, list) and READ_TOOLS <= {t.name for t in got}, repr(got)[:300])
                    r = await text_of(c, "rules", {})
                    check(f"{L}: reads the rulebook", isinstance(r, str) and RULE in r, r)
                    r = await text_of(c, "get", {"item_id": "a1"})
                    check(f"{L}: reads an item", isinstance(r, str) and ITEM in r, r)
            asyncio.run(run())

        nobody = lambda who: f"you are not a member of any board. The address that signed in: {who}."
        barred = lambda why: f"you are not a member of any board. {NEW} signed in and is not let in. {ident.REFUSALS[why]}"

        for mode in MODES:
            put(HAND)
            later[0] += 61      # the invitee's token of the round before is out of the cache (a removal and a new registration inside the window is tests/invites_scenario.py's and the docs')
            L = "through the door:"
            answered(f"{L} a member written by hand", "token-bob", mode)
            refused(f"{L} a signed-in stranger", "token-stranger", mode, nobody(STRANGER))
            refused(f"{L} an invitee before being added", "token-new", mode, nobody(NEW))
            asyncio.run(writes_and_does_not_invite(D, T, f"{L} a member written by hand", proxy("token-bob"), mode))
            asyncio.run(admin_invites(D, f"{L} adding the invitee", proxy("token-alice"), mode, {"address": NEW}))
            refused(f"{L} an invitee whose address Google does not report as verified", "token-new-unverified", mode, barred("unverified"))
            check(f"{L} nothing recorded by an unverified sign-in ({mode})", account(members) == "", members.read_text())
            answered(f"{L} an invitee after being added", "token-new", mode)
            check(f"{L} the first verified sign-in records its account ({mode})", account(members) == "111", members.read_text())
            asyncio.run(writes_and_does_not_invite(D, T, f"{L} an invitee after being added", proxy("token-new"), mode))
            refused(f"{L} another Google account of the invited address", "token-new-second", mode, barred("other_account"))

            async def removed_while_open():
                headers = proxy("token-new")
                async with D.client(headers, mode) as c:
                    R = f"{L} an invitee removed on an open session ({mode})"
                    got = await outcome(entries(c.list_tools_mcp(cache_mode="bypass"), "tools"))
                    check(f"{R}: lists the tools while registered", isinstance(got, list), repr(got)[:300])
                    await admin_invites(D, R, proxy("token-alice"), mode, {"address": NEW, "remove": True})
                    await not_let_in(c, R, nobody(NEW))
            asyncio.run(removed_while_open())
            refused(f"{L} a removed invitee, with the token used before", "token-new", mode, nobody(NEW))
            answered(f"{L} a member, after the invitee's removal", "token-bob", mode)
            put({"alice": HAND["alice"]})
            refused(f"{L} a removed member written by hand", "token-bob", mode, nobody(MEMBER))
    finally:
        for s in reversed(started):
            stop(*s[:3])
    return F.ran, F.fails


MARK = "@@invites_access part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"direct": part_direct, "door": part_door}[name]()
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
    print(f"ok: invites access scenario, {total} checks")
