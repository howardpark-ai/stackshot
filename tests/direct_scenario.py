"""Scenario test for the direct lane (anchorhub/core.py emit_direct, anchorhub/slack.py) on fixture data: a fake slack_sdk, a fake Web API, a fake clock, no network.

Covers: on an anchor in [anchor_hub] direct every event goes at once to that one session, one notice each, never to the
anchor's keeper, nothing held for a follow-up; the notice carries the whole text (newlines kept), clipped at 4,000 chars
with the marker; ts and thread_ts in the header (thread_ts only for a thread reply); an edit and a caught-up post go direct
too; a bot's post and a bot's edit are dropped there; the routing log gets target "direct", pilot False and no notice id;
a non-direct anchor still debounces with one-line notices; an emptied `direct` restores the normal routing, read live;
the value "none" makes an anchor log only (a routing-log line with no recipient and the reason "direct: log only", nothing
delivered, nothing pending, no warning, never read as a session).

    tests/run-suite direct      → exit 0 / 1"""
import sys, os, re, json, pathlib, tempfile, types, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="directtest-")
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
toml, n1 = re.subn(r'(?m)^state = "[^"]*"', f'state = "{tmp}/state"', toml); toml, n2 = re.subn(r'(?m)^secrets = "[^"]*"', f'secrets = "{tmp}/secrets"', toml)
toml, n3 = re.subn(r'(?m)^timezone = "[^"]*"', 'timezone = "Asia/Dubai"', toml)
toml, n4 = re.subn(r'(?m)^slack_allow_self_channels = .*$', 'slack_allow_self_channels = ["CDIRECT"]', toml)
toml, n5 = re.subn(r'(?m)^direct = \{\}', 'direct = { "slack:CDIRECT" = "plover-briefing" }', toml)
assert (n1, n2, n3, n4, n5) == (1, 1, 1, 1, 1), (n1, n2, n3, n4, n5)
pathlib.Path(tmp, "stackshot.toml").write_text(toml, encoding="utf-8"); os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
os.environ["STACKSHOT_FLEET_DIR"] = f"{tmp}/fleet"           # no live fleet: a session name stays a name (anchors.canonical)
os.environ.pop("ANCHOR_HUB_ALLOW_SELF", None)
os.makedirs(f"{tmp}/state/anchor-hub"); os.makedirs(f"{tmp}/secrets/anchor-hub")
pathlib.Path(tmp, "secrets/anchor-hub/env").write_text("SLACK_USER_TOKEN=xoxp-fixture\nSLACK_APP_TOKEN=xapp-fixture\n")
sys.path.insert(0, STACK); logging.disable(logging.WARNING)

ME, DANA = "UME", "UDANA"
HISTORY: dict[str, list[dict]] = {}
class Web:
    def __init__(self, token=None): pass
    def auth_test(self): return {"user_id": ME, "url": "https://fixture.slack.com/"}
    def conversations_info(self, channel): return {"channel": {"name": {"CDIRECT": "team-briefing", "COTHER": "general"}.get(channel, channel.lower())}}
    def conversations_members(self, channel): return {"members": []}
    def users_info(self, user): return {"user": {"real_name": {ME: "Oliver Quinn", DANA: "Dana"}.get(user, user), "name": user}}
    def chat_getPermalink(self, channel, message_ts): return {"permalink": f"https://fixture.slack.com/archives/{channel}/p{message_ts}"}
    def conversations_history(self, channel, limit=100, oldest=None):
        ms = HISTORY.get(channel, [])
        if oldest is not None: ms = [m for m in ms if float(m["ts"]) >= float(oldest)]
        return {"messages": ms[:limit]}
class Socket:
    def __init__(self, app_token=None, web_client=None): self.socket_mode_request_listeners = []
    def connect(self): pass
    def is_connected(self): return True
    def send_socket_mode_response(self, r): pass
SOCK: list[Socket] = []
def _socket(*a, **k): s = Socket(*a, **k); SOCK.append(s); return s
sys.modules.update({"slack_sdk": types.SimpleNamespace(WebClient=Web), "slack_sdk.socket_mode": types.SimpleNamespace(SocketModeClient=_socket),
                    "slack_sdk.socket_mode.request": types.SimpleNamespace(SocketModeRequest=object),
                    "slack_sdk.socket_mode.response": types.SimpleNamespace(SocketModeResponse=lambda envelope_id: envelope_id)})

from stackshot.anchors.anchorhub import core, slack
from stackshot.core import config; from stackshot.router import routing
ZONE_OFFSET = 4 * 3600                 # the pinned instance timezone, Asia/Dubai: UTC+4, no DST
T0 = 1790812800.0 - ZONE_OFFSET        # 2026-10-01 00:00 +04 (1790812800 is 2026-10-01 00:00 UTC) = 2026-09-30 20:00 UTC
clock = types.SimpleNamespace(t=T0)
core.time = types.SimpleNamespace(time=lambda: clock.t, sleep=lambda s: None)
slack.threading = types.SimpleNamespace(Thread=lambda **k: types.SimpleNamespace(start=lambda: None))   # no watch loop
hub = core.Hub(); out: list[tuple] = []
hub.deliver = lambda anchor, session, text: out.append((anchor, session, text)); hub.write_status = lambda: None
# both channels belong to a project in the pilot: the keeper would get every notice, tagged with its id
PROJECT = "ops/sala"
ROUTES = {a: [{"project": PROJECT, "session": "plover-main", "target": "project-wide", "pilot": True, "filter": ""}] for a in ("slack:CDIRECT", "slack:COTHER")}
core._ROUTES.clear(); core._ROUTES.update(ROUTES)
hub.bindings = {"slack:CDIRECT": {"plover-main"}, "slack:COTHER": {"plover-main"}}
slack.run(hub)
handle = SOCK[0].socket_mode_request_listeners[0]

fails = checks = 0
def check(name, ok, got=None):
    global fails, checks
    checks += 1
    print(("ok:   " if ok else "FAIL: ") + name + ("" if ok else f"\n      got: {got!r}"))
    if not ok: fails += 1
def post(ev):
    out.clear()
    handle(SOCK[0], types.SimpleNamespace(type="events_api", envelope_id="e1", payload={"event": {"type": "message", **ev}}))
    return list(out)
def edit(cid, new, old_text="before"):
    return post({"channel": cid, "subtype": "message_changed", "ts": "1790780500.000100",
                 "message": {"ts": "1790780400.000100", **new}, "previous_message": {"ts": "1790780400.000100", "text": old_text}})
URL = "https://fixture.slack.com/archives/CDIRECT/p"

# two quick messages: two notices at once, to the direct session only, nothing pending
a = post({"channel": "CDIRECT", "user": ME, "text": "first", "ts": "1790780400.000100"})
clock.t += 5
b = post({"channel": "CDIRECT", "user": DANA, "text": "second", "ts": "1790780405.000100"})
check("two quick messages give two notices at once, to the direct session alone",
      [(x[0], x[1]) for x in a + b] == [("slack:CDIRECT", "plover-briefing")] * 2, a + b)
check("the first notice: header with ts and the permalink, then the text",
      a and a[0][2] == f"[anchor] Slack #team-briefing: new message from Oliver Quinn (ts 1790780400.000100) → {URL}1790780400.000100\nfirst", a)
check("nothing is held for a follow-up", not any(k[0] == "slack:CDIRECT" for k in hub.pending), hub.pending)
out.clear(); clock.t += 120; hub.tick()
check("no follow-up comes later", out == [], out)
check("no notice id: the keeper has nothing to rule on", all("· notice" not in x[2] for x in a + b), a + b)

# full text over 140 chars, newlines kept; over 4,000 clipped
long = "line one of a long note\n" + "x" * 300 + "\nlast line"
got = post({"channel": "CDIRECT", "user": ME, "text": long, "ts": "1790780410.000100"})
check("a text over 140 chars arrives whole, newlines kept", got and got[0][2].split("\n", 1)[1] == long, got)
huge = "y" * 4500
got = post({"channel": "CDIRECT", "user": ME, "text": huge, "ts": "1790780420.000100"})
body = got[0][2].split("\n", 1)[1] if got else ""
check("a text over 4,000 chars is clipped with the marker",
      body == "y" * 4000 + " [… truncated, 4,500 chars — fetch message ts 1790780420.000100]", body[-80:])

# thread ids
got = post({"channel": "CDIRECT", "user": ME, "text": "a reply", "ts": "1790780430.000200", "thread_ts": "1790780400.000100"})
check("a thread reply carries ts and thread_ts", got and "(ts 1790780430.000200 · thread_ts 1790780400.000100) →" in got[0][2].split("\n")[0], got)
got = post({"channel": "CDIRECT", "user": ME, "text": "a parent", "ts": "1790780440.000100", "thread_ts": "1790780440.000100"})
check("a top-level post (thread_ts = its own ts) carries no thread_ts", got and "(ts 1790780440.000100) →" in got[0][2] and "thread_ts" not in got[0][2], got)

# an edit
got = edit("CDIRECT", {"user": ME, "text": "first, fixed\nwith a second line", "thread_ts": "1790780300.000100"})
check("an edit is delivered direct, whole, with the inner message's ids",
      got == [("slack:CDIRECT", "plover-briefing", f"[anchor] Slack #team-briefing: EDITED message from Oliver Quinn (ts 1790780400.000100 · thread_ts 1790780300.000100) → {URL}1790780400.000100\nfirst, fixed\nwith a second line")], got)
got = edit("CDIRECT", {"user": ME, "text": "before"})
check("an edit with the same text stays silent", got == [], got)

# bots
got = post({"channel": "CDIRECT", "user": "UWEBHOOK", "bot_id": "B0000000001", "text": "the session's reply", "ts": "1790780450.000100"})
check("a bot_id post on a direct anchor is dropped", got == [], got)
got = post({"channel": "CDIRECT", "user": ME, "bot_id": "B0000000001", "text": "as me", "ts": "1790780451.000100"})
check("a bot_id post attributed to the hub's user is dropped", got == [], got)
got = edit("CDIRECT", {"user": "UWEBHOOK", "bot_id": "B0000000001", "text": "reply, edited"})
check("a bot's edit on a direct anchor is dropped", got == [], got)
got = edit("CDIRECT", {"subtype": "bot_message", "username": "home-briefing", "text": "briefing, edited"})
check("a bot_message edit on a direct anchor is dropped", got == [], got)
got = post({"channel": "COTHER", "user": DANA, "bot_id": "B0OTHER", "text": "an app posting as Dana", "ts": "1790780452.000100"})
check("off the direct lane a bot_id post is delivered as before", len(got) == 1 and got[0][1] == "plover-main", got)
hub.pending.clear()

# catch-up
T = 1790780460.0
HISTORY["CDIRECT"] = [{"user": "UWEBHOOK", "bot_id": "B0000000001", "text": "bot reply", "ts": f"{T + 30:.6f}"},
                      {"user": DANA, "text": "caught two\nlines", "ts": f"{T + 20:.6f}"},
                      {"user": ME, "text": "caught one", "ts": f"{T + 10:.6f}"}]
out.clear(); n = hub.catchups["slack"](T)
check("catch-up: one direct notice per item, the bot's reply dropped",
      n == 2 and [x[1] for x in out] == ["plover-briefing"] * 2, (n, out))
check("a caught-up notice says so in its header and carries the whole text",
      len(out) == 2 and out[1][2] == f"[anchor] Slack #team-briefing: new message from Dana (caught up) (ts {T + 20:.6f}) → {URL}{T + 20:.6f}\ncaught two\nlines", out)
check("nothing pending after the catch-up", not hub.pending, hub.pending)

# the routing log
log = [r for r in routing.read(PROJECT) if r.get("anchor") == "slack:CDIRECT"]
check("each direct notice is in the project's routing log (2 + 2 + 2 + 1 edit + 2 caught up)", len(log) == 9, len(log))
check("…with to the direct session, target direct, pilot False",
      log and all((r["to"], r["target"], r["pilot"]) == ("plover-briefing", "direct", False) for r in log), log[:1])
owed = [n for n in routing.read(PROJECT) if n.get("anchor") == "slack:CDIRECT" and n.get("pilot") and not n.get("ruling")]
check("…so none waits for a ruling (the router never has one to rule)", owed == [], owed)

# an anchor bound to no project still goes direct
config.CFG["anchor_hub"]["direct"] = {"slack:CDIRECT": "plover-briefing", "slack:CLONE": "solo"}
got = post({"channel": "CLONE", "user": DANA, "text": "unbound", "ts": "1790780500.000100"})
check("a direct anchor bound to no project is still delivered", [(x[0], x[1]) for x in got] == [("slack:CLONE", "solo")], got)

# the value "none": log only (gbrain releases must wake no session)
CANON: list[str] = []; _canon = core._anc.canonical
core._anc.canonical = lambda s: (CANON.append(s), _canon(s))[1]
WARN: list[str] = []
class _Catch(logging.Handler):
    def emit(self, rec): WARN.append(rec.getMessage())
_h = _Catch(level=logging.WARNING); core.log.addHandler(_h); logging.disable(logging.NOTSET)
hub.pending.clear()
config.CFG["anchor_hub"]["direct"] = {"slack:CDIRECT": "none"}
check("direct(): a 'none' value is kept as it is, never resolved", core.direct() == {"slack:CDIRECT": "none"}, core.direct())
n_log = len(routing.read(PROJECT))
got = post({"channel": "CDIRECT", "user": DANA, "text": "a release\nwith notes", "ts": "1790780600.000100"})
got += post({"channel": "CDIRECT", "user": ME, "text": "and another", "ts": "1790780601.000100"})
check("a 'none' entry delivers nothing, to no session and not to the keeper", got == [], got)
new = routing.read(PROJECT)[n_log:]
check("…and writes one routing-log line per event for the anchor's project",
      len(new) == 2 and all(r.get("anchor") == "slack:CDIRECT" and r.get("kind") == "anchor" for r in new), new)
check("…with no recipient, target direct, pilot False and the reason 'direct: log only'",
      new and all((r["to"], r["target"], r["pilot"], r.get("reason")) == ("", "direct", False, "direct: log only") for r in new), new[:1])
check("…the line keeps the event's gist and link", new and new[0]["text"] == "a release with notes" and new[0]["url"].startswith(URL), new[:1])
check("nothing is pending after a 'none' event", not hub.pending, hub.pending)
out.clear(); clock.t += 3 * 3600; hub.tick()
check("…and nothing goes out later (no follow-up)", out == [], out)
owed = [n for n in routing.read(PROJECT) if n.get("anchor") == "slack:CDIRECT" and not n.get("to") and n.get("pilot") and not n.get("ruling")]
check("…and none waits for a ruling", owed == [], owed)
c = routing.counts([PROJECT], now=clock.t)
check("…and it is not counted as pending on the board", c["pending"] == sum(1 for n in routing.read(PROJECT) if n.get("pilot") and not n.get("ruling")) and not any(n.get("pilot") for n in new), c)
check("'none' is never canonicalised or looked up as a session", "none" not in [str(x).lower() for x in CANON], CANON)
check("'none' raises no warning (no unknown session, no failed delivery)", WARN == [], WARN)
config.CFG["anchor_hub"]["direct"] = {"slack:CDIRECT": " None "}
got = post({"channel": "CDIRECT", "user": DANA, "text": "mixed case", "ts": "1790780602.000100"})
check("'None' (any case, padded) is log only too", got == [] and routing.read(PROJECT)[-1].get("reason") == "direct: log only", got)
config.CFG["anchor_hub"]["direct"] = {"slack:CLONE": "none"}
got = post({"channel": "CLONE", "user": DANA, "text": "unbound, log only", "ts": "1790780603.000100"})
check("a 'none' anchor bound to no project delivers nothing and raises nothing", got == [] and WARN == [], (got, WARN))
config.CFG["anchor_hub"]["direct"] = {"slack:CDIRECT": "plover-briefing"}
got = post({"channel": "CDIRECT", "user": DANA, "text": "named again", "ts": "1790780604.000100"})
check("a named session is still delivered as before, whole, after a 'none' entry is replaced",
      [(x[0], x[1]) for x in got] == [("slack:CDIRECT", "plover-briefing")] and got[0][2].endswith("\nnamed again")
      and routing.read(PROJECT)[-1]["to"] == "plover-briefing" and "reason" not in routing.read(PROJECT)[-1], got)
check("…and the named session is canonicalised as before", CANON and CANON[-1] == "plover-briefing", CANON[-1:])
core._anc.canonical = _canon; core.log.removeHandler(_h); logging.disable(logging.WARNING); hub.pending.clear()

# a non-direct anchor still debounces, one-line notices
out.clear(); clock.t = T0 + 3600
got = post({"channel": "COTHER", "user": DANA, "text": "hi\nthere", "ts": "1790784000.000100"})
check("a non-direct anchor's first notice goes at once to the keeper, one line, with its notice id",
      len(got) == 1 and got[0][1] == "plover-main" and got[0][2].startswith('[anchor] Slack #general: new message from Dana: "hi there" → ') and "· notice " in got[0][2], got)
clock.t += 10; a = post({"channel": "COTHER", "user": DANA, "text": "z" * 200, "ts": "1790784010.000100"})
clock.t += 10; b = post({"channel": "COTHER", "user": DANA, "text": "third", "ts": "1790784020.000100"})
check("a non-direct anchor holds the later events for the follow-up", a + b == [] and hub.pending.get(("slack:COTHER", "plover-main"), {}).get("count") == 2, (a + b, hub.pending))
out.clear(); clock.t += 60; hub.tick()
check("…and sends one follow-up after the debounce, to the keeper, with its notice id",
      len(out) == 1 and out[0][1] == "plover-main" and " 2 more since " in out[0][2] and "· notice " in out[0][2] and "\n" not in out[0][2], out)
clock.t += 600
got = post({"channel": "COTHER", "user": DANA, "text": "w" * 200, "ts": "1790784700.000100"})
check("a non-direct notice is one line, clipped at 140", len(got) == 1 and "\n" not in got[0][2] and "w" * 140 + " [… truncated, 200 chars" in got[0][2], got)
hub.pending.clear()

# emptying `direct` restores the normal routing, read live
config.CFG["anchor_hub"]["direct"] = {}
got = post({"channel": "CDIRECT", "user": ME, "text": "back to normal", "ts": "1790784800.000100"})
got += post({"channel": "CDIRECT", "user": DANA, "text": "and again", "ts": "1790784801.000100"})
check("an emptied `direct` routes to the keeper again, one line, debounced",
      len(got) == 1 and got[0][1] == "plover-main" and "\n" not in got[0][2] and "· notice " in got[0][2]
      and hub.pending.get(("slack:CDIRECT", "plover-main"), {}).get("count") == 1, (got, hub.pending))

print(f"ok: direct-lane scenario, {checks} checks" if not fails else f"{fails} of {checks} check(s) failed")
sys.exit(1 if fails else 0)
