"""Scenario test for the hub's debounce (anchorhub/core.py): a fake clock drives Hub.event / Hub.tick and every delivery is
recorded. Covers the 60-s collapse (Slack), the Drive quiet window (one follow-up after 30 min of silence, naming the span),
the maximum hold for a burst that never goes quiet, and a fresh burst after the follow-up (a shared plan edited by one person fires many notices in an hour).

    tests/run-suite debounce     → exit 0 / 1"""
import sys, os, re, pathlib, tempfile, types, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="hubtest-")
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
toml, n1 = re.subn(r'(?m)^state = "[^"]*"', f'state = "{tmp}/state"', toml); toml, n2 = re.subn(r'(?m)^secrets = "[^"]*"', f'secrets = "{tmp}/secrets"', toml)
assert n1 == 1 and n2 == 1
toml, n3 = re.subn(r'(?m)^timezone = "[^"]*"', 'timezone = "Asia/Dubai"', toml); assert n3 == 1   # the expected strings are in the instance timezone (UTC+4, abbreviated +04)
pathlib.Path(tmp, "stackshot.toml").write_text(toml, encoding="utf-8"); os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
os.makedirs(f"{tmp}/state/anchor-hub"); sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.anchors.anchorhub import core
ZONE_OFFSET = 4 * 3600                 # Asia/Dubai: UTC+4, no DST
T0 = 1790812800.0 - ZONE_OFFSET        # 2026-10-01 00:00 +04 (1790812800 is 2026-10-01 00:00 UTC) = 2026-09-30 20:00 UTC
clock = types.SimpleNamespace(t=T0)
core.time = types.SimpleNamespace(time=lambda: clock.t, sleep=lambda s: None)
hub = core.Hub(); out = []
hub.deliver = lambda anchor, session, text: out.append((round(clock.t - T0), session, text)); hub.write_status = lambda: None; hub.persist = lambda: "saved"
hub.bindings = {"drive:plan": {"example-site"}, "slack:C1": {"ops"}, "drive:busy": {"example-site"}}
def at(t, anchor, kind, who, text):
    clock.t = T0 + t; hub.event(anchor, {"title": f"L {anchor}", "who": who, "text": text, "url": f"https://u/{anchor}", "ts": str(t)}, kind=kind); hub.tick()
def tick(t): clock.t = T0 + t; hub.tick()
# Drive: an editing session — first notice at once, then silence until the plan has been quiet 30 min
at(0, "drive:plan", "drive", "Alex Example", 'changed "plan"')
for m in range(5, 65, 5): at(m * 60, "drive:plan", "drive", "Alex Example", 'changed "plan"')       # 12 more edits over an hour
tick(60 * 60 + 29 * 60 + 59)                                                                       # quiet 29:59 → nothing yet
tick(60 * 60 + 30 * 60)                                                                            # quiet 30:00 → one follow-up
at(3 * 3600, "drive:plan", "drive", "Alex Example", 'changed "plan"')                                 # a fresh burst later → at once again
# Drive: a burst that never goes quiet reports at the maximum hold
for m in range(0, 200, 10): at(4 * 3600 + m * 60, "drive:busy", "drive", "Someone", 'changed "sheet"')
# Slack: unchanged — 60 s after the first
at(6 * 3600, "slack:C1", "slack", "Dana", "hi"); at(6 * 3600 + 30, "slack:C1", "slack", "Dana", "again"); tick(6 * 3600 + 59); tick(6 * 3600 + 60)
want = [
    (0, "example-site", '[anchor] Drive L drive:plan: Alex Example changed "plan" → https://u/drive:plan'),
    (5400, "example-site", '[anchor] Drive L drive:plan: 12 more between 00:00 and 01:00 +04, last from Alex Example: "changed "plan"" → https://u/drive:plan'),
    (10800, "example-site", '[anchor] Drive L drive:plan: Alex Example changed "plan" → https://u/drive:plan'),
    (14400, "example-site", '[anchor] Drive L drive:busy: Someone changed "sheet" → https://u/drive:busy'),
    (25200, "example-site", '[anchor] Drive L drive:busy: 18 more between 04:00 and 07:00 +04, last from Someone: "changed "sheet"" → https://u/drive:busy'),
    (25800, "example-site", '[anchor] Drive L drive:busy: Someone changed "sheet" → https://u/drive:busy'),      # after a maximum-hold report the next change opens a new window, at once
    (21600, "ops", '[anchor] Slack L slack:C1: new message from Dana: "hi" → https://u/slack:C1'),
    (21660, "ops", '[anchor] Slack L slack:C1: 1 more since 06:00 +04, last from Dana: "again" → https://u/slack:C1'),
]
got = sorted(out); want = sorted(want)
if got == want: print(f"ok: debounce, {len(got)} deliveries as expected"); sys.exit(0)
for g, w in zip(got, want):
    if g != w: print("expected:", w, "\ngot:     ", g); break
else: print("length differs", len(got), len(want), got)
sys.exit(1)
