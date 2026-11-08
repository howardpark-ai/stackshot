"""Scenario test for the Slack receiver's own-posts opt-in (anchorhub/slack.py: the owner's own posts in a briefing channel reach its agent) on fixture data: a fake slack_sdk, a fake Web API, no network.

Covers: in a channel listed in [anchor_hub] slack_allow_self_channels the hub's own user's post, edit, caught-up post and
seen() count like anyone's; elsewhere they stay dropped; a bot's post (bot_id, or subtype bot_message) stays dropped even in
the opted-in channel; the list also reads as one comma- or whitespace-separated string; ANCHOR_HUB_ALLOW_SELF still opens
every channel; someone else's post is delivered as before.

    tests/run-suite slack_self      → exit 0 / 1"""
import sys, os, re, pathlib, tempfile, types, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="slackselftest-")
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
toml, n1 = re.subn(r'(?m)^state = "[^"]*"', f'state = "{tmp}/state"', toml); toml, n2 = re.subn(r'(?m)^secrets = "[^"]*"', f'secrets = "{tmp}/secrets"', toml)
toml, n3 = re.subn(r'(?m)^timezone = "[^"]*"', 'timezone = "Asia/Dubai"', toml)
toml, n4 = re.subn(r'(?m)^slack_allow_self_channels = .*$', 'slack_allow_self_channels = ["COPTIN"]', toml)
assert (n1, n2, n3, n4) == (1, 1, 1, 1), (n1, n2, n3, n4)
pathlib.Path(tmp, "stackshot.toml").write_text(toml, encoding="utf-8"); os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
os.environ.pop("ANCHOR_HUB_ALLOW_SELF", None)
os.makedirs(f"{tmp}/state/anchor-hub"); os.makedirs(f"{tmp}/secrets/anchor-hub")
pathlib.Path(tmp, "secrets/anchor-hub/env").write_text("SLACK_USER_TOKEN=xoxp-fixture\nSLACK_APP_TOKEN=xapp-fixture\n")
sys.path.insert(0, STACK); logging.disable(logging.WARNING)

ME, DANA = "UME", "UDANA"
HISTORY: dict[str, list[dict]] = {}          # channel → its messages, newest first (as conversations_history answers)
class Web:
    def __init__(self, token=None): pass
    def auth_test(self): return {"user_id": ME, "url": "https://fixture.slack.com/"}
    def conversations_info(self, channel): return {"channel": {"name": {"COPTIN": "team-briefing", "COTHER": "general"}.get(channel, channel.lower())}}
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
fake = {"slack_sdk": types.SimpleNamespace(WebClient=Web), "slack_sdk.socket_mode": types.SimpleNamespace(SocketModeClient=_socket),
        "slack_sdk.socket_mode.request": types.SimpleNamespace(SocketModeRequest=object),
        "slack_sdk.socket_mode.response": types.SimpleNamespace(SocketModeResponse=lambda envelope_id: envelope_id)}
sys.modules.update(fake)

from stackshot.anchors.anchorhub import core, slack
from stackshot.core import config
slack.threading = types.SimpleNamespace(Thread=lambda **k: types.SimpleNamespace(start=lambda: None))   # no watch loop
hub = core.Hub(); out: list[tuple] = []
hub.event = lambda anchor, s, kind="slack": out.append((anchor, kind, s["who"], s["text"]))
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

# the new-message branch
got = post({"channel": "COPTIN", "user": ME, "text": "morning note", "ts": "1790780400.000100"})
check("a self post in the opted-in channel is delivered", [g[:3] for g in got] == [("slack:COPTIN", "slack", "Oliver Quinn")] and "morning note" in got[0][3], got)
got = post({"channel": "COTHER", "user": ME, "text": "elsewhere", "ts": "1790780400.000200"})
check("a self post elsewhere is dropped", got == [], got)
got = post({"channel": "COPTIN", "user": ME, "bot_id": "B0HOOK", "text": "briefing", "ts": "1790780400.000300"})
check("a bot_id post in the opted-in channel is dropped (no loop)", got == [], got)
got = post({"channel": "COPTIN", "subtype": "bot_message", "bot_id": "B0HOOK", "username": "home-digest", "text": "briefing", "ts": "1790780400.000400"})
check("a bot_message post in the opted-in channel is dropped", got == [], got)
got = post({"channel": "COPTIN", "user": ME, "subtype": "bot_message", "text": "briefing", "ts": "1790780400.000450"})
check("a self-attributed bot_message in the opted-in channel is dropped", got == [], got)
got = post({"channel": "COTHER", "user": DANA, "text": "hi", "ts": "1790780400.000500"})
check("someone else's post elsewhere is delivered as before", [g[:3] for g in got] == [("slack:COTHER", "slack", "Dana")], got)

# the edit branch: the inner (new) message decides
got = edit("COPTIN", {"user": ME, "text": "morning note, fixed"})
check("a self edit in the opted-in channel is delivered", [g[:3] for g in got] == [("slack:COPTIN", "slack-edit", "Oliver Quinn")], got)
got = edit("COTHER", {"user": ME, "text": "elsewhere, fixed"})
check("a self edit elsewhere is dropped", got == [], got)
got = edit("COPTIN", {"user": ME, "bot_id": "B0HOOK", "text": "briefing, fixed"})
check("a self edit carrying a bot_id in the opted-in channel is dropped", got == [], got)

# catch_up
T = 1790780400.0
HISTORY["COPTIN"] = [{"user": ME, "bot_id": "B0HOOK", "text": "bot as me", "ts": f"{T + 30:.6f}"},
                     {"subtype": "bot_message", "bot_id": "B0HOOK", "text": "briefing", "ts": f"{T + 20:.6f}"},
                     {"user": ME, "text": "caught self", "ts": f"{T + 10:.6f}"}]
HISTORY["COTHER"] = [{"user": ME, "text": "caught elsewhere", "ts": f"{T + 15:.6f}"}]
hub.bindings = {"slack:COPTIN": {"briefing"}, "slack:COTHER": {"ops"}}
out.clear(); n = hub.catchups["slack"](T)
check("catch_up delivers a self post in the opted-in channel, and only it", n == 1 and [g[:3] for g in out] == [("slack:COPTIN", "slack", "Oliver Quinn")] and "caught self" in out[0][3], (n, out))

# seen(): the resolver's newest post that counts
res = hub.resolvers["slack"]
HISTORY["COPTIN"] = [{"user": ME, "text": "newest, mine", "ts": f"{T + 300:.6f}"}, {"user": DANA, "text": "older", "ts": f"{T + 100:.6f}"}]
HISTORY["COTHER"] = [{"user": ME, "text": "newest, mine", "ts": f"{T + 300:.6f}"}, {"user": DANA, "text": "older", "ts": f"{T + 100:.6f}"}]
check("seen() in the opted-in channel counts a self post", res("slack:COPTIN").get("seen") == core.now_iso_at(T + 300), res("slack:COPTIN"))
check("seen() elsewhere still skips a self post", res("slack:COTHER").get("seen") == core.now_iso_at(T + 100), res("slack:COTHER"))

# the setting's forms, and the env switch
config.CFG["anchor_hub"]["slack_allow_self_channels"] = "CA, CB\tCC  COPTIN"
check("the list reads as one comma- or whitespace-separated string", slack.self_channels() == {"CA", "CB", "CC", "COPTIN"}, slack.self_channels())
config.CFG["anchor_hub"]["slack_allow_self_channels"] = []
got = post({"channel": "COPTIN", "user": ME, "text": "after the list is emptied", "ts": "1790780400.000600"})
check("an emptied list drops self posts again, read live", got == [], got)
os.environ["ANCHOR_HUB_ALLOW_SELF"] = "1"
got = post({"channel": "COTHER", "user": ME, "text": "with the env switch", "ts": "1790780400.000700"})
check("ANCHOR_HUB_ALLOW_SELF still opens every channel", [g[:3] for g in got] == [("slack:COTHER", "slack", "Oliver Quinn")], got)
os.environ.pop("ANCHOR_HUB_ALLOW_SELF")

print(f"ok: slack self-channels scenario, {checks} checks" if not fails else f"{fails} of {checks} check(s) failed")
sys.exit(1 if fails else 0)
