"""Scenario test for the read-first gate of the router (router.py: trivial_kind, message_like, machine_reason, person_notice, person_place, gate_rule,
trivial_rule, twin_line, the person guard of code_rule and call_line; router_live.py: the person hold kind, a person's pass to a front agent, the twin plan
of tick, the wake of a person's notice; the anchor listener's record of ekind/bot/thread) on fixture data. No live store, no network and never the real `claude`: the thin
call is a function of the prompt (tick's `runner`), and a delivery is a function that logs what it was asked to push.

Covers: the anchor listener records the kind, bot and thread marks of an event; machine news (a bot's post, a routine pull request event, the owner's own edit of a document)
is archived by rule with its reason and no call, unless it is for the owner or an item hangs on its anchor (then the rules before the gate act, a CI result still
goes to the builder); a person's message that asks, names the owner or replies in a thread is passed to the scoped item's mover when it is a background agent, else
to the item's doer or the page's background agent, and to a front agent only as a held line and only when it needs the owner; a bare laugh, ack or emoji (jamo
written as code points) is read and recorded, passed to no agent, wakes no wait; a message the gate cannot place goes to the call, whose archive, drop or merge answer is
overridden into a hold for the background agent (the `person` kind), as is a failed or timed-out call (no second try); a notice that carries no author kind is a
person's; a project with no background agent holds a person's message for its contact front agent and starts no turn (and never archives it when the gate cannot
file it); a picture of a person is held; one event on an anchor two pages hold is ruled once, for the page it is about (the call is shown both pages' agents), and
the other follows, also when it arrives after the first was ruled; an item waiting on an anchor wakes on any ruling of a person's notice (also through the route
tool), not on a trivial one; the rubric no longer says "when unsure, archive it"; the held store never drops a person's line and a retired agent is never the target; a repeat is dropped only after a passed or held one; a failing fallback never escapes the tick; the near-misses of a bare laugh (one laugh letter, a thumbs down, a bare mention, a burst) reach an agent.

    tests/run-suite router_gate        → exit 0 / 1"""
import json, os, re, sys, time, pathlib, logging, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="routergate-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), gbrain=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
toml = toml.replace('lanes_file = ""', f'lanes_file = "{tmp}/sala/lanes.tsv"', 1); assert f'lanes_file = "{tmp}/sala/lanes.tsv"' in toml
toml = toml.replace('limit_file = ""', f'limit_file = "{tmp}/sala/limit.json"', 1); assert f'limit_file = "{tmp}/sala/limit.json"' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                 ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml = _instance.set_person(toml)
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
for d in ("store/a", "fleet/a", "state/site", "secrets", "touch", "repo", "sala", "brain/projects"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
NAMES = ("al-name", "al-main", "al-builder", "al-docs", "br-name", "br-main", "ch-name", "ch-main", "ch-eng", "de-name", "de-main", "de-eng")
UU = lambda i: f"{i:08x}-0000-4000-8000-{i:012x}"
(T / "fleet/a/sessions.json").write_text(json.dumps({UU(i + 1): {"name": nm, "machine": "a", "url": "", "seen": "x"} for i, nm in enumerate(NAMES)}))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
page = lambda name, sess, **kw: {"title": name, "name": name, "org": "home", "tags": [], "type": "project", "session": sess, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": f"https://example.invalid/{name}", **kw}
AL = {"al-main": "Oliver's point of contact", "al-builder": "builds, merges and releases the code", "al-docs": "keeps the pages and the documents"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": page("Alpha", "al-name", agents=AL, back_agents={k: AL[k] for k in ("al-builder", "al-docs")}, lead_agents=["al-docs"]),
    "projects/bravo": page("Bravo", "br-name", agents={"br-main": "Oliver's point of contact"}),
    "projects/charlie": page("Charlie", "ch-name", agents={"ch-main": "the contact", "ch-eng": "builds the charlie code"}, back_agents={"ch-eng": "builds the charlie code"}),
    "projects/delta": page("Delta", "de-name", agents={"de-main": "the contact", "de-eng": "builds the delta code"}, back_agents={"de-eng": "builds the delta code"})}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE-MARK: the vendor call is open.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
def item(i, proj, mover, **meta): (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": mover, "mover": mover, "project": proj, **meta}, "updated": 1.0, "state_updated": 1.0}))
item(1, "projects/alpha", "al-builder")                      # scoped to gmail A: moved by a background agent
item(2, "projects/alpha", "al-main")                         # scoped to gmail B: moved by a front agent, whose notices ask nothing of him
item(4, "projects/alpha", "al-main", hold=True)              # waiting on gmail E (with item 5)
item(5, "projects/alpha", "al-main", hold=True)
item(12, "projects/alpha", "Oliver")                         # scoped to gmail C: his own move, so a reply on it needs him
item(11, "projects/charlie", "ch-eng")                       # scoped to the shared Slack channel on charlie's page only
(T / "store/next-id").write_text("30")
G = lambda ch: f"https://mail.google.com/mail/u/0/#all/{ch * 16}"
URL_A, URL_B, URL_E = G("a"), G("b"), "https://x.slack.com/archives/C0000000005"
SLACK_AL, SLACK_BR, SLACK_SH, SLACK_SH2 = "https://x.slack.com/archives/C0000000001", "https://x.slack.com/archives/C0000000002", "https://x.slack.com/archives/C0000000009", "https://x.slack.com/archives/C0000000008"
GH_PR, DRIVE = "https://github.com/example-owner/repo/pull/8", "https://drive.google.com/drive/folders/FILE1"
add = lambda url, items=None: {"url": url, "items": items, "added": 1, "by": "t"}
(T / "store/anchors.json").write_text(json.dumps({
    "projects/alpha": [add(SLACK_AL), add(URL_A, ["a1"]), add(URL_B, ["a2"]), add(G("c"), ["a12"]), add(URL_E, ["a4", "a5"]), add(GH_PR), add(DRIVE)],
    "projects/bravo": [add(SLACK_BR)],
    "projects/charlie": [add(SLACK_SH, ["a11"]), add(SLACK_SH2)], "projects/delta": [add(SLACK_SH), add(SLACK_SH2)]}))

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.core import config as _cfg; from stackshot.router import routing; from stackshot.router import router; from stackshot.router import router_live as live; from stackshot.anchors import anchors as a; from stackshot.waits import held
from stackshot.service import gates
from stackshot.web import server
from stackshot.web import wiring
from stackshot.web import publish as _web_publish
from stackshot.web.tools import route as _wt_route
from stackshot.service import store as _service_store
from stackshot.service import wakes as wakes_svc
from stackshot.anchors.anchorhub import core
os.makedirs(core.ADIR, exist_ok=True)      # the listener keeps its own state folder under the configured state directory
_web_publish._publish = _wt_route._publish = lambda: None
_cfg.CFG["router"] = {"timeout_seconds": 20}
for _bg in ("al-builder", "al-docs", "ch-eng", "de-eng"): held.mark_client(_bg)      # the rollout gate: these background agents' hooks fetch held lines
PUSHED, FYI = [], []
FYI_ANSWER = [("fyi", "")]
live._HOOKS["deliver"] = lambda target, text: (PUSHED.append((target, text)) or f"delivered → {target}")
live._HOOKS["front_turn"] = lambda target, subject, needs=True: True
live._HOOKS["after_rule"] = wiring._router_live_after
def _front_fyi(target, text, gid="", nid="", log=True, kind="fyi", whole=False): FYI.append((target, kind, nid)); return FYI_ANSWER[0]
live._HOOKS["front_fyi"] = _front_fyi
_wt_route._anchor_release = lambda *a_, **k_: wakes_svc.anchor_release(*a_, **k_); _wt_route._watch_label = lambda x: x

hub = core.Hub(); hub.deliver = lambda anchor, session, text: None; hub.write_status = lambda: None
core._ROUTES.clear()
for anchor, rs in {"slack:C0000000001": [("projects/alpha", "al-name")], "slack:C0000000002": [("projects/bravo", "br-name")], "slack:C0000000009": [("projects/charlie", "ch-name"), ("projects/delta", "de-name")],
                   "slack:C0000000008": [("projects/charlie", "ch-name"), ("projects/delta", "de-name")],
                   "gmail:" + "a" * 16: [("projects/alpha", "al-name")], "gmail:" + "b" * 16: [("projects/alpha", "al-name")], "gmail:" + "c" * 16: [("projects/alpha", "al-name")], "slack:C0000000005": [("projects/alpha", "al-name")],
                   "github:example-owner/repo#8": [("projects/alpha", "al-name")], "drive:FILE1": [("projects/alpha", "al-name")]}.items():
    tgt = {"gmail:" + "a" * 16: "for al-builder", "gmail:" + "b" * 16: "for al-main", "gmail:" + "c" * 16: "for al-main", "slack:C0000000005": "for al-main"}.get(anchor, "project-wide")      # an anchor scoped to one item is addressed to its mover
    core._ROUTES[anchor] = [{"project": p, "session": s, "target": tgt, "pilot": True, "filter": ""} for p, s in rs]
SESSION = {"projects/alpha": "al-name", "projects/bravo": "br-name", "projects/charlie": "ch-name", "projects/delta": "de-name"}

def post(anchor, who, text, kind="slack", bot=False, etype="", thread=False, sessions=None, head=""):
    """One event on an anchor, sent to the (anchor, session) pairs bound to it like the hub does → the notices it made, one per page: {project key: notice}."""
    ev = types.SimpleNamespace(label=anchor, who=who, url="https://u/" + str(len(ran)), kind=kind, bot=bot, etype=etype, meta={"thread_ts": "1.5"} if thread else {}, head=head, author="", text=text)
    out = {}
    for r in core._ROUTES[anchor]:
        if sessions and r["session"] not in sessions: continue
        hub.send(anchor, r["session"], f"[anchor] {text}", ev, text)
        out[r["project"]] = routing.read(r["project"])[-1]
    return out
def one(anchor, who, text, **kw): return list(post(anchor, who, text, **kw).values())[0]
def rec(i, key="projects/alpha"): return next(n for n in routing.read(key) if n["id"] == i)
def lines(): return router._read(live.live_path())
class _NoLine(dict):
    """What lv() gives for a notice with no ruling line: every field reads None, so a check on it fails by name instead of the run stopping on an IndexError."""
    def __missing__(self, k): return None
def lv(i): return ([l for l in lines() if l["id"] == i and l.get("status") == "ruled"] or [_NoLine()])[-1]
CALLS, PLAN = [], {}
def runner(prompt):
    """The 'call': answers what PLAN says for each notice id of the prompt (default: archived)."""
    CALLS.append(prompt)
    ids = re.findall(r'<notice id="([^"]+)">', prompt)
    return {"status": "ok", "text": json.dumps([{"id": i, **PLAN.get(i, {"ruling": "archived", "target": "", "reason": "a stub: nothing in it", "for_owner": False})} for i in ids])}
def tick(r=runner):
    p0, c0 = len(PUSHED), len(CALLS); res = live.tick(runner=r); return res, PUSHED[p0:], len(CALLS) - c0

# ---- 0. units: the trivial reader (jamo as code points, no literal), the structured machine/person reading
J = lambda *cp: "".join(chr(c) for c in cp)
UP, DOWN, CHECK, ARROW, HEART, VS16, CLAP, PARTY, LAUGHING, TONE = (chr(c) for c in (0x1F44D, 0x1F44E, 0x2714, 0x2192, 0x2764, 0xFE0F, 0x1F44F, 0x1F389, 0x1F602, 0x1F3FD))
LAUGH_K, LAUGH_H, YES_JAMO = 0x314B, 0x314E, 0x3147      # the two laugh letters, and a jamo that is a word (yes)
KINDS_OF = lambda *ts: [router.trivial_kind(t) for t in ts]
check("trivial: a run of laughter letters, haha, lol, ok, thanks, +1, a thumbs up and a :shortcode: are trivial; each is read for its kind",
      KINDS_OF(J(LAUGH_K, LAUGH_K, LAUGH_K), "haha", "lol", "ok", "Thanks!", "+1", UP, ":thumbsup:", "<@U123> ok") == ["laughter", "laughter", "laughter", "ack", "ack", "ack", "emoji", "emoji", "ack"],
      KINDS_OF(J(LAUGH_K, LAUGH_K, LAUGH_K), "haha", "lol", "ok", "Thanks!", "+1", UP, ":thumbsup:", "<@U123> ok"))
check("trivial: more than a laugh is not (a question, the owner's name, an ack with a reason, a decision word, a plain yes, no text at all)",
      not any(router.trivial_kind(t) for t in ("ok?", "ok Oliver", "ok but the vendor moved the date", "haha, that decision is mine", "yes", "", "   ")), KINDS_OF("ok?", "ok Oliver", "ok but the vendor moved the date", "yes", ""))
check("trivial (F3a): only the two laugh letters are laughter, mixed or repeated; a jamo that is a word, or one laugh letter alone, is not",
      KINDS_OF(J(LAUGH_K, LAUGH_H, LAUGH_K), J(LAUGH_H, LAUGH_H), J(LAUGH_K, LAUGH_K) + "~", "ok " + J(LAUGH_K)) == ["laughter"] * 4
      and not any(KINDS_OF(J(YES_JAMO, YES_JAMO), J(YES_JAMO), J(LAUGH_K), J(0x3161, 0x3161), J(LAUGH_K, YES_JAMO))), KINDS_OF(J(LAUGH_K, LAUGH_H, LAUGH_K), J(YES_JAMO, YES_JAMO), J(LAUGH_K), J(LAUGH_K, YES_JAMO)))
check("trivial (F3b): the positive reactions (laughing, clapping, a heart with its selector, a thumbs up with a skin tone, a party, :tada:, :+1:) are emoji; a thumbs down, a check mark, an arrow, a lone + or ~ and an unknown :x: are not",
      KINDS_OF(LAUGHING, CLAP, HEART + VS16, UP + TONE, PARTY + PARTY, ":tada:", ":+1:", UP + " ok", "ok~") == ["emoji", "emoji", "emoji", "emoji", "emoji", "emoji", "emoji", "ack", "ack"]
      and not any(KINDS_OF(DOWN, ":-1:", CHECK, ARROW, "+", "~", "...", ":x:", UP + DOWN, "ok " + CHECK, "ok " + DOWN)), (KINDS_OF(LAUGHING, CLAP, HEART + VS16, UP + TONE, ":tada:", ":+1:"), KINDS_OF(DOWN, ":-1:", CHECK, ARROW, "+", "~", "...", ":x:")))
check("trivial (F3c, F3d): a bare mention of someone is a ping, not trivial; a lone ok or okay still is", not any(KINDS_OF("<@U0123ABCD>", "<@U0123ABCD> <@U0456EFGH>", "@dana")) and KINDS_OF("ok", "okay", "Okay.") == ["ack"] * 3, KINDS_OF("<@U0123ABCD>", "ok", "okay"))
check("trivial (F4): a notice that folds two or more messages is never trivial (the gist shows only the last one); one folded message is read as it is",
      router.trivial_of({"text": "1 more, the last: thx"}) == "ack" and router.trivial_of({"text": "2 more, the last: thx"}) == "" and router.trivial_of({"text": "5 more, earlier: ok | a plan | the last: ok"}) == ""
      and router.trivial_of({"text": "thx"}) == "ack" and router.folded({"text": "3 more, the last: x"}) == 3 and router.folded({"text": "3 more, please"}) == 0, None)
N = lambda **kw: {"id": "x1", "ts": time.time(), "kind": "anchor", "anchor": "slack:C1", "who": "Dana", "text": "the file is ready", **kw}
check("reading: a notice with no author kind is a person's; a bot flag, a bot login, a CI result, a routine PR event and the owner's own document edit are machine news; a mixed burst is a person's",
      router.person_notice(N()) and not router.machine_reason(N()) and router.machine_reason(N(bot=True)) and router.machine_reason(N(who="ci-app[bot]", anchor="github:o/r#1", etype="comment")) and router.machine_reason(N(who="CI", etype="ci_failed", anchor="github:o/r#1"))
      and router.machine_reason(N(anchor="github:o/r#1", etype="pr_merged")) and router.machine_reason(N(anchor="drive:F", who="Oliver")) and not router.machine_reason(N(anchor="drive:F", who="Dana"))
      and not router.machine_reason(N(anchor="github:o/r#1", etype="ci_passed+comment", who="ci-app[bot], Dana")) and router.person_notice(N(anchor="github:o/r#1", etype="ci_passed+comment", who="ci-app[bot], Dana"))
      and not router.person_notice(N(who=router.SYSTEM_SENDERS[0])) and not router.person_notice(N(anchor="drive:F", who="Dana")), None)
check("reading (F1): a sender whose display name looks like a bot login or CI is a person on a mail, Slack or Notion notice; a GitHub bot login is a machine, and so is any source's own bot flag",
      all(router.person_notice(N(anchor=a_, who=w_)) and not router.machine_reason(N(anchor=a_, who=w_)) for a_ in ("gmail:" + "d" * 16, "slack:C1", "notion:abc") for w_ in ("deploy[bot]", "CI", "ci-app[bot], other[bot]"))
      and router.machine_reason(N(anchor="github:o/r#1", who="ci-app[bot]", etype="comment")) and router.machine_reason(N(anchor="gmail:" + "d" * 16, who="Dana", bot=True))
      and router.machine_reason(N(anchor="github:o/r#1", who="CI")) and not router.is_ci_notice(N(anchor="slack:C1", who="CI")) and router.is_ci_notice(N(anchor="github:o/r#1", who="CI")), None)
check("reading (F2): the listener's own notice (the system sender, no event kind) is neither person nor machine; a person of that display name with an event kind is a person",
      router.system_notice(N(who=router.SYSTEM_SENDERS[0])) and not router.person_notice(N(who=router.SYSTEM_SENDERS[0])) and not router.machine_reason(N(who=router.SYSTEM_SENDERS[0]))
      and not router.system_notice(N(who=router.SYSTEM_SENDERS[0], ekind="slack")) and router.person_notice(N(who=router.SYSTEM_SENDERS[0], ekind="slack")) and not router.machine_reason(N(who=router.SYSTEM_SENDERS[0], ekind="slack", bot=False)), None)
check("reading: person_wakes is true for a person's message and false for machine news, a laugh and a burst of one is read as it is",
      router.person_wakes(N()) and not router.person_wakes(N(bot=True)) and not router.person_wakes(N(anchor="github:o/r#1", etype="pr_merged", who="someone")) and not router.person_wakes(N(text="ok"))
      and router.person_wakes(N(text="2 more, the last: ok")), None)
# ---- 1. the anchor listener records the marks the gate reads
n_rec = one("slack:C0000000001", "Dana", "a thread reply from a bot", bot=True, thread=True)
n_plain = one("slack:C0000000001", "Dana", "a plain post")
check("the anchor listener records the event's kind, bot flag and thread flag on the notice (and none for a plain post)", n_rec.get("ekind") == "slack" and n_rec.get("bot") is True and n_rec.get("thread") is True
      and n_plain.get("ekind") == "slack" and "bot" not in n_plain and "thread" not in n_plain, (n_rec, n_plain))
res, pushed, ncalls = tick()   # rules both away so the next checks start clean
CALLS.clear(); PUSHED.clear()

# ---- 2. machine news: archived by rule with its reason, no call; unless it is for the owner or an item hangs on its anchor
m_bot = one("slack:C0000000001", "deploybot", "build 41 finished", bot=True)
m_pr = one("github:example-owner/repo#8", "someone", "merged the pull request", kind="github", etype="pr_merged")
m_own = one("drive:FILE1", "Oliver", "edited the plan", kind="drive")
m_ci = one("github:example-owner/repo#8", "CI", "checks failed on the pull request", kind="github", etype="ci_failed")
m_strong = one("slack:C0000000001", "deploybot", "[for Oliver] the release needs a yes", bot=True)
m_busy = one("gmail:" + "a" * 16, "mailer", "an automatic reply", kind="gmail", bot=True)
res, pushed, ncalls = tick()
check("machine news (a bot's post, a routine pull request event, the owner's own edit of a document) is archived by the gate's rule, with its reason, no call and no delivery",
      all(lv(x["id"])["rule"] == "gate-machine" and lv(x["id"])["ruling"] == "archived" and lv(x["id"])["source"] == "code" and rec(x["id"])["ruling"] == "archived" for x in (m_bot, m_pr, m_own))
      and "bot" in lv(m_bot["id"])["reason"] and "pull request" in lv(m_pr["id"])["reason"] and "own edit" in lv(m_own["id"])["reason"], [lv(x["id"]) for x in (m_bot, m_pr, m_own)])
check("a CI result still goes to the project's builder (the rule before the gate)", lv(m_ci["id"])["rule"] == "anchor-ci" and lv(m_ci["id"])["target"] == "al-builder", lv(m_ci["id"]))
check("machine news that is for the owner is not archived by the gate (it goes to the call as before); neither is a bot's post on an anchor an open item hangs on (its rule passes it, so the wait ends)",
      lv(m_strong["id"])["rule"] != "gate-machine" and lv(m_busy["id"])["rule"] != "gate-machine" and lv(m_busy["id"])["ruling"] == "passed", (lv(m_strong["id"]), lv(m_busy["id"])))
check("…and the only call of that tick is the one for the notice that is for the owner", ncalls == 1 and m_strong["id"] in CALLS[-1] and m_bot["id"] not in CALLS[-1], ncalls)
check("a notice that is no message and no machine's (someone else's edit of a document) is neither archived by the gate nor held: the call rules it as before, and may archive it",
      (lambda x: (tick(), lv(x["id"]))[1])(one("drive:FILE1", "Dana", "edited the plan", kind="drive"))["ruling"] == "archived", None)

# ---- 3. a person's message the gate can place
BACK = a.background_agent("projects/alpha", a.registry())
CALLS.clear(); PUSHED.clear()
p_ask = one("gmail:" + "a" * 16, "Dana", "can you send the file by Friday?", kind="gmail")
p_name = one("slack:C0000000001", "Dana", "Oliver, the vendor wrote back")
p_front_item = one("gmail:" + "b" * 16, "Dana", "is the draft final?", kind="gmail")
p_needs = one("gmail:" + "b" * 16, "Dana", "Oliver, I need your yes on the draft, can you decide?", kind="gmail")
p_thread = one("slack:C0000000001", "Dana", "that works for me", thread=True)
res, pushed, ncalls = tick()
check("a person's question on an anchor scoped to one item whose mover is a background agent goes to that mover, by the gate, no call", lv(p_ask["id"])["rule"] == "gate-person" and lv(p_ask["id"])["target"] == "al-builder" and lv(p_ask["id"])["ruling"] == "passed"
      and ("al-builder" in [x[0] for x in pushed]) and ncalls == 0, (lv(p_ask["id"]), ncalls))
check("a person's message that names the owner, on a project-wide anchor, goes to the page's background agent (the one the message tool uses)", lv(p_name["id"])["rule"] == "gate-person" and lv(p_name["id"])["target"] == BACK == "al-builder", (lv(p_name["id"]), BACK))
check("a question about an item a front agent moves goes to the background agent that does its work (the page's), never to the front agent", lv(p_front_item["id"])["target"] == BACK and lv(p_front_item["id"])["ruling"] == "passed" and not any(x[0] == "al-main" for x in pushed), (lv(p_front_item["id"]), pushed))
check("a message that needs the owner goes to the front mover as a held line: ruled held for its next turn (`person`), the front gate filled, nothing pushed to it, no turn",
      lv(p_needs["id"])["ruling"] == "held" and lv(p_needs["id"])["held_for"] == "al-main" and lv(p_needs["id"])["rule"] == "gate-person" and ("al-main", "person", p_needs["id"]) in FYI
      and not any(x[0] == "al-main" for x in pushed) and rec(p_needs["id"])["ruling"] == "held", (lv(p_needs["id"]), FYI))
p_his = one("gmail:" + "c" * 16, "Dana", "is the draft final?", kind="gmail")
p_self = one("gmail:" + "a" * 16, "al-builder", "can you send the file by Friday?", kind="gmail")
res, pushed, ncalls = tick()
check("a question on an item that is the owner's own move needs him: a held line for the front agent, nothing pushed to it", lv(p_his["id"])["rule"] == "gate-person" and lv(p_his["id"])["ruling"] == "held" and lv(p_his["id"])["held_for"] == "al-main" and ("al-main", "person", p_his["id"]) in FYI, lv(p_his["id"]))
check("a notice an agent wrote itself is never passed back to its own sender by the gate (the rules after it route it)", not (lv(p_self["id"])["rule"] == "gate-person" and lv(p_self["id"])["target"] == "al-builder"), lv(p_self["id"]))
check("a reply in a Slack thread goes to the page's background agent", lv(p_thread["id"])["rule"] == "gate-person" and lv(p_thread["id"])["target"] == BACK, lv(p_thread["id"]))

# ---- 4. a trivial message is read and recorded, never passed, never a turn
CALLS.clear(); PUSHED.clear()
triv = [one("slack:C0000000001", "Dana", t, thread=th) for t, th in ((J(0x314B, 0x314B, 0x314B), False), ("haha", True), ("ok", False), (":thumbsup:", False), (UP, True))]
not_triv = [one("slack:C0000000001", "Dana", t) for t in ("ok?", "ok, Oliver", "ok but the vendor moved the date")]
res, pushed, ncalls = tick()
check("trivial messages are archived by the gate's rule with the reason 'trivial: <kind>', passed to nobody, no call", all(lv(x["id"])["rule"] == "gate-trivial" and lv(x["id"])["ruling"] == "archived" and lv(x["id"])["reason"].startswith("trivial: ") for x in triv), [lv(x["id"]) for x in triv])
check("…and not a message of them reached an agent, and the near-misses (a question, the owner's name, an ack with a reason) were not read as trivial", not any(x["id"] in t for x in triv for _, t in pushed) and all(lv(x["id"])["rule"] != "gate-trivial" for x in not_triv)
      and all(lv(x["id"])["ruling"] != "archived" for x in not_triv), [lv(x["id"]) for x in not_triv])

# ---- 5. a message the gate cannot place goes to the call; the call can never archive it
CALLS.clear(); PUSHED.clear(); held.take("al-builder"); held.take("al-docs")
u1 = one("slack:C0000000001", "Dana", "the quarterly numbers are in the sheet")
u2 = one("slack:C0000000001", "Dana", "we could also move the call to the 3rd")
u3 = one("slack:C0000000001", "Dana", "I changed the invoice template yesterday")
u4 = one("slack:C0000000001", "Dana", "the sheet got a new tab for March")
PLAN.update({u1["id"]: {"ruling": "archived", "target": "", "reason": "nothing in it", "for_owner": False}, u2["id"]: {"ruling": "dropped", "target": "", "reason": "chatter", "for_owner": False},
             u3["id"]: {"ruling": "merged", "target": "", "reason": "folded", "for_owner": False}, u4["id"]: {"ruling": "passed", "target": "al-docs", "reason": "it is about the pages", "for_owner": False}})
res, pushed, ncalls = tick()
check("an unplaceable person's message goes to one call", ncalls == 1 and all(x["id"] in CALLS[-1] for x in (u1, u2, u3, u4)), ncalls)
check("the call's archived, dropped and merged answers are overridden into a hold for the page's background agent: ruled held, kind person, filed in its held lines, nothing pushed",
      all(lv(x["id"])["ruling"] == "held" and lv(x["id"])["held_for"] == BACK and lv(x["id"])["hold"] == "person" and rec(x["id"])["ruling"] == "held" for x in (u1, u2, u3)) and held.count(BACK) == 3
      and not any(x["id"] in t for x in (u1, u2, u3) for _, t in pushed), [lv(x["id"]) for x in (u1, u2, u3)])
check("…the held line is of the person kind (the routing log says so), and a call's pass to an agent stands", "(person)" in lv(u1["id"])["reason"] and rec(u1["id"])["reason"].endswith("(person)") and lv(u4["id"])["ruling"] == "passed" and lv(u4["id"])["target"] == "al-docs", (lv(u1["id"])["reason"], lv(u4["id"])))
check("the prompt marks a person's notice `author: person`, names the page's background agent, and the rubric no longer says to archive what it is unsure of",
      '"author": "person"' in CALLS[-1] and f"background agent, for a person's message nobody else fits: {BACK}" in CALLS[-1] and "When you are unsure, or the notice is off-topic, archive it" not in router.RUBRIC
      and "never archived, dropped or merged" in router.RUBRIC, CALLS[-1][:600])
held.take("al-builder"); held.take("al-docs")
PLAN.clear()

# ---- 6. a failed or timed-out call holds a person's message at once (no second try); a notice carrying no author kind is a person's
CALLS.clear(); PUSHED.clear()
f1 = one("slack:C0000000001", "Dana", "the vendor changed the price list")
old = routing.record("projects/alpha", kind="anchor", to="", label="Slack", who="Dana", text="an older record with no author kind", url="https://u/old", target="project-wide", pilot=True, anchor="slack:C0000000001", live=True)
res, pushed, ncalls = tick(lambda p: {"status": "timeout", "note": "killed after 20 s", "text": ""})
check("a timed-out call: the person's messages are held for the background agent on the first tick, not left for another try, no attempts kept", lv(f1["id"])["ruling"] == "held" and lv(f1["id"])["source"] == "fallback" and lv(f1["id"])["held_for"] == BACK
      and lv(old)["ruling"] == "held" and not router._load_attempts(), (lv(f1["id"]), router._load_attempts()))
f2 = one("slack:C0000000001", "Dana", "another price list change")
res, pushed, ncalls = tick(lambda p: {"status": "ok", "text": "not json at all"})
check("an answer that does not parse is the same: held", lv(f2["id"])["ruling"] == "held" and lv(f2["id"])["held_for"] == BACK, lv(f2["id"]))
held.take("al-builder")

# ---- 7. a project with no background agent: a held line for its contact front agent, no turn; never archived when the hook cannot file it
CALLS.clear(); PUSHED.clear(); FYI.clear()
b1 = one("slack:C0000000002", "Dana", "the shop closes early today")
b2 = one("slack:C0000000002", "Dana", "can we meet on Monday?")
res, pushed, ncalls = tick()
check("no background agent: an unplaceable person's message (the call said archived) and a placed one are held for the contact front agent, through the front gate, and start no turn",
      all(lv(x["id"])["ruling"] == "held" and lv(x["id"])["held_for"] == "br-main" for x in (b1, b2)) and not any(x[0] == "br-main" for x in pushed) and {x[2] for x in FYI} == {b1["id"], b2["id"]}, ([lv(x["id"]) for x in (b1, b2)], FYI, pushed))
FYI_ANSWER[0] = ("held", "its hook cannot fetch held lines")
b3 = one("slack:C0000000002", "Dana", "can we meet on Tuesday?")
res, pushed, ncalls = tick()
check("when the front gate cannot file it, the person's message is delivered to the front agent as before, never archived", lv(b3["id"])["ruling"] == "passed" and rec(b3["id"], "projects/bravo")["ruling"] == "passed" and any(x[0] == "br-main" for x in pushed), (lv(b3["id"]), pushed))
FYI_ANSWER[0] = ("fyi", "")
img = one("slack:C0000000001", "Dana", "[files: scan.png]")
res, pushed, ncalls = tick()
check("a person's picture (no words) is held for the background agent, not archived as 'image not read'", lv(img["id"])["rule"] == "image" and lv(img["id"])["ruling"] == "held" and lv(img["id"])["held_for"] == BACK, lv(img["id"]))
held.take("al-builder")

# ---- 8. one event, one ruling
CALLS.clear(); PUSHED.clear()
pair = post("slack:C0000000009", "Dana", "can the charlie export run before Friday?")
res, pushed, ncalls = tick()
ch, de = pair["projects/charlie"], pair["projects/delta"]
check("an event on an anchor two pages hold is ruled once: to the page it is about (the anchor is scoped to an item of charlie's), one delivery, no call", ncalls == 0 and len([x for x in pushed if "export" in x[1]]) == 1 and lv(ch["id"])["target"] == "ch-eng" and lv(ch["id"])["rule"] == "gate-person", (pushed, lv(ch["id"])))
check("…the other page's notice follows it: merged by the rule one-ruling, naming the ruled one, nothing delivered for it", lv(de["id"])["rule"] == "one-ruling" and lv(de["id"])["ruling"] == "merged" and ch["id"] in lv(de["id"])["reason"] and rec(de["id"], "projects/delta")["ruling"] == "merged", lv(de["id"]))
CALLS.clear(); PUSHED.clear()
PLAN.clear()
pair2 = post("slack:C0000000008", "Dana", "the delta rollout notes are in the folder")
c2, d2 = pair2["projects/charlie"], pair2["projects/delta"]
PLAN.update({d2["id"]: {"ruling": "passed", "target": "ch-eng", "reason": "it is about the export", "for_owner": False}, c2["id"]: {"ruling": "passed", "target": "ch-eng", "reason": "it is about the export", "for_owner": False}})
res, pushed, ncalls = tick()
check("an event neither page's rules place: one call for both, the prompt shows each notice the other page's agents (also_held_by), the call may name an agent of the other page, one delivery",
      ncalls == 1 and "also_held_by" in CALLS[-1] and "ch-eng [background]" in CALLS[-1] and len([x for x in pushed if "delta rollout" in x[1]]) == 1, (ncalls, CALLS[-1][:900] if CALLS else None, pushed))
check("…the notice for the page it is about (the one whose name is in the words, delta's) is the one ruled, and charlie's follows", lv(d2["id"])["source"] == "call" and lv(d2["id"])["target"] == "ch-eng" and lv(c2["id"])["rule"] == "one-ruling", (lv(d2["id"]), lv(c2["id"])))
PLAN.clear(); CALLS.clear(); PUSHED.clear()
first = post("slack:C0000000009", "Dana", "will the delta numbers change again?", sessions=("de-name",))
res, pushed, ncalls = tick()
second = post("slack:C0000000009", "Dana", "will the delta numbers change again?", sessions=("ch-name",))
res, pushed2, ncalls2 = tick()
fc, sc = first["projects/delta"], second["projects/charlie"]
check("a twin that comes in after the first was ruled follows that ruling (merged, one-ruling), with no second delivery or call", lv(sc["id"])["rule"] == "one-ruling" and lv(sc["id"])["ruling"] == "merged" and fc["id"] in lv(sc["id"])["reason"] and pushed2 == [] and ncalls2 == 0, (lv(sc["id"]), pushed2))

# ---- 9. an item that waits on an anchor wakes on any ruling of a person's notice, a bare ack on that anchor included (an ack where no item hangs is archived: section 4)
def held_items(): return [bool(_service_store._load(g)["metadata"].get("hold")) for g in ("a4", "a5")]
CALLS.clear(); PUSHED.clear()
check("setup: both items wait", held_items() == [True, True], held_items())
t_triv = one("slack:C0000000005", "Dana", "ok")
res, pushed, ncalls = tick()
check("an ack on an anchor two open items wait on is no trivial notice: it goes the person path to the page's background agent and wakes both items",
      lv(t_triv["id"])["rule"] == "gate-person" and lv(t_triv["id"])["ruling"] in ("held", "passed") and lv(t_triv["id"])["target"] == BACK and held_items() == [False, False], (lv(t_triv["id"]), held_items()))
for g in ("a4", "a5"): item(int(g[1:]), "projects/alpha", "al-main", hold=True)
held.take("al-builder")
w1 = one("slack:C0000000005", "Dana", "the vendor sent the signed file")
PLAN.update({w1["id"]: {"ruling": "archived", "target": "", "reason": "nothing in it", "for_owner": False}})
res, pushed, ncalls = tick()
check("a person's notice the call archived is held for the background agent, and that wakes both items (any ruling of a person's notice wakes)", lv(w1["id"])["ruling"] == "held" and held_items() == [False, False], (lv(w1["id"]), held_items()))
PLAN.clear(); held.take("al-builder")
for g in ("a4", "a5"): item(int(g[1:]), "projects/alpha", "al-main", hold=True)
w2 = one("slack:C0000000005", "Dana", "one more thing on the file")
_wt_route._route(w2["id"], "archived", "", "nothing in it", "")
check("the route tool wakes on an archived ruling of a person's notice too, but not on an archived trivial one", held_items() == [False, False], held_items())
for g in ("a4", "a5"): item(int(g[1:]), "projects/alpha", "al-main", hold=True)
w3 = one("slack:C0000000005", "Dana", "lol")
rec_ = routing.rule(w3["id"], "archived", reason="trivial", by="t")[1]
wiring._router_live_after("projects/alpha", {**rec_, "ruling": "archived"})
check("…and a laugh ruled archived wakes nothing", held_items() == [True, True], held_items())
wiring._router_live_after("projects/alpha", {**rec_, "ruling": "archived", "person_wake": True})
check("…while the same ruling with the person's mark wakes both", held_items() == [False, False], held_items())

# ---- 10. a repeat of a person's message is dropped (the first was passed); mixed-case: a drop of a repeat is no archive of a message
CALLS.clear(); PUSHED.clear(); PLAN.clear(); held.take("al-builder")
r1 = one("slack:C0000000001", "Dana", "can you check the invoice numbers for March before the call?")
res, pushed, ncalls = tick()
r2 = one("slack:C0000000001", "Dana", "can you check the invoice numbers for March before the call?")
res, pushed2, ncalls2 = tick()
check("an identical repeat of a message within the hour is dropped as a repeat of the first, which was passed", lv(r1["id"])["ruling"] == "passed" and lv(r2["id"])["rule"] == "repeat" and lv(r2["id"])["ruling"] == "dropped" and pushed2 == [], (lv(r1["id"]), lv(r2["id"])))
# ---- 11. the held store never drops a person's line (age, count, sweep of an untouched file), and a gone agent is never the target
HK, OLD = "zz-person-hold-test", time.time() - 30 * 86400
held.add(HK, "closed", "an old closed line", nid="c-old", now=OLD)
held.add(HK, "person", "a person's words, kept", nid="p-old", now=OLD, whole=True)
os.utime(held._file(held.key_of(HK)), (OLD, OLD))
held.add("zz-other-session", "closed", "something else")      # any add sweeps the folder: this file has been untouched for 30 days
left = [r["text"] for r in held._read(held._file(held.key_of(HK)))]
check("held (F5): the sweep of a session's untouched file keeps a person's line and drops the expired others", left == ["a person's words, kept"], left)
for i in range(held.KEEP_MAX + 5): held.add(HK, "closed", f"c{i}", now=time.time())
rows_ = held._read(held._file(held.key_of(HK)))
check("held (F5): the count limit never drops a person's line, however old it is: KEEP_MAX other lines and the person's one stay", len(rows_) == held.KEEP_MAX + 1 and rows_[0]["kind"] == "person" and sum(r["kind"] == "closed" for r in rows_) == held.KEEP_MAX, [r["kind"] for r in rows_][:3])
shown_, ids_ = held.lease(HK, shown_max=held.KEEP_MAX + 5)
check("held (F5): a person's line past KEEP_DAYS is handed over, not dropped by the age limit", "a person's words, kept" in shown_, shown_[:200])
held.ack(HK, ids=ids_)
while held.count(HK): held.take(HK)
held.take("zz-other-session")
from stackshot.fleet import sessions_registry as _sr
DEAD = set(); _sr_retired = _sr.retired; _sr.retired = lambda x: str(x) in DEAD
try:
    CALLS.clear(); PUSHED.clear(); FYI.clear(); PLAN.clear(); held.take("al-builder"); held.take("al-docs")
    DEAD.update({"al-builder"})
    d1 = one("slack:C0000000001", "Dana", "the quarterly figures moved again")                 # nothing places it: the call (it says archived)
    d2 = one("gmail:" + "a" * 16, "Dana", "can you resend the file?", kind="gmail")            # an item whose mover is the retired builder
    res, pushed, ncalls = tick()
    check("a retired background agent is never the target (F5): an unplaceable person's message is held for the page's next live background agent, one placed on an item its mover was is passed to that agent too",
          lv(d1["id"])["ruling"] == "held" and lv(d1["id"])["held_for"] == "al-docs" and lv(d2["id"])["target"] == "al-docs" and rec(d2["id"])["ruling"] in ("held", "passed") and not any(x[0] == "al-builder" for x in pushed), (lv(d1["id"]), lv(d2["id"])))
    held.take("al-docs"); PUSHED.clear(); FYI.clear()
    DEAD.update({"al-docs"})
    d3 = one("slack:C0000000001", "Dana", "the quarterly figures moved a third time")
    d4 = one("gmail:" + "a" * 16, "Dana", "can you resend the file once more?", kind="gmail")
    res, pushed, ncalls = tick()
    check("with every background agent gone (F5) the person's message is held for the page's contact front agent as a held line that starts no turn, never archived",
          all(lv(x["id"])["ruling"] == "held" and lv(x["id"])["held_for"] == "al-main" and rec(x["id"])["ruling"] == "held" and ("al-main", "person", x["id"]) in FYI for x in (d3, d4)) and not any(x[0] == "al-main" for x in pushed), ([lv(x["id"]) for x in (d3, d4)], FYI))
finally:
    _sr.retired = _sr_retired; DEAD.clear()
held.take("al-builder"); held.take("al-docs")
sr_dir = T / "links"; (sr_dir / "a").mkdir(parents=True)
(sr_dir / "a" / "session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "sessions": {
    UU(201): {"id": UU(201), "name": "gone-agent", "aliases": ["old-name"], "state": "retired"}, UU(202): {"id": UU(202), "name": "live-agent", "aliases": ["gone-agent"], "state": "live"},
    UU(203): {"id": UU(203), "name": "other-gone", "state": "retired"}}}))
_sr_dir = _sr._dir; _sr._dir = lambda: sr_dir; _sr.reset()
try: got_ = (_sr.retired("other-gone"), _sr.retired("old-name"), _sr.retired("gone-agent"), _sr.retired("live-agent"), _sr.retired("nobody-knows"), _sr.retired(""))
finally: _sr._dir = _sr_dir; _sr.reset()
check("the session registry reads a name as retired only when it holds rows for it and none is live (a name a live row also carries, an unknown name and no name are not)", got_ == (True, True, False, False, False, False), got_)

# ---- 12. the person guard around the rules in code, and a repeat's earlier ruling
cx = router.Context(); now_ = time.time()
mk = lambda i, ts, **kw: {"id": i, "ts": ts, "kind": "anchor", "anchor": "slack:C0000000001", "who": "Dana", "text": "can you check the March numbers?", "url": "https://u/rp", "label": "Slack", "ekind": "slack", **kw}
stub = lambda rule, ruling: (lambda key, n, root, cx_, peers: {"id": n["id"], "key": key, "project": root, "kind": "anchor", "ts": now_, "source": "code", "rule": rule, "ruling": ruling, "target": "", "reason": "a stub", "for_owner": False, "item": "", "call": "", "label": "", "text": "", "note": ""})
_real_code = router._code_rule
try:
    wrapped = {}
    for ruling_ in ("archived", "dropped", "merged"):
        router._code_rule = stub("quiet", ruling_)
        wrapped[ruling_] = (router.code_rule("projects/alpha", mk("w1", now_), "projects/alpha", cx, []), router.code_rule("projects/alpha", mk("w2", now_, bot=True), "projects/alpha", cx, []))
    router._code_rule = stub("gate-trivial", "archived"); trivial_kept = router.code_rule("projects/alpha", mk("w3", now_, text="ok"), "projects/alpha", cx, [])
    router._code_rule = stub("auto", "merged"); auto_kept = router.code_rule("projects/alpha", mk("w4", now_), "projects/alpha", cx, [])
    reps = {}
    router._code_rule = stub("repeat", "dropped")
    for er in ("passed", "held", "archived", "merged", "dropped", None):
        reps[er] = router.code_rule("projects/alpha", mk("e2", now_), "projects/alpha", cx, [mk("e1", now_ - 60, **({"ruling": er} if er else {}))])
    reps["machine"] = router.code_rule("projects/alpha", mk("e2", now_, bot=True), "projects/alpha", cx, [mk("e1", now_ - 60, bot=True)])
finally: router._code_rule = _real_code
check("the person guard of code_rule: a rule that would archive, drop or merge a person's message (the quiet-hour archive here) holds it for the page's background agent instead; the same ruling of machine news stands",
      all(p_["ruling"] == "passed" and p_["hold"] == "person" and p_["target"] == BACK and p_.get("person") is True and m_["ruling"] == ruling_ and m_["rule"] == "quiet" for ruling_, (p_, m_) in wrapped.items()), wrapped)
check("…and the two exceptions stand: a bare laugh archived by gate-trivial, and the log-only copy of a ruling made elsewhere (auto)", trivial_kept["ruling"] == "archived" and auto_kept["ruling"] == "merged", (trivial_kept, auto_kept))
check("a repeat of a person's message is dropped only when the earlier one was ruled passed or held; an earlier one archived, merged, dropped or with no ruling makes it a hold for the background agent; machine news repeats as before",
      all(reps[e]["ruling"] == "dropped" and reps[e]["rule"] == "repeat" for e in ("passed", "held")) and all(reps[e]["ruling"] == "passed" and reps[e]["hold"] == "person" and reps[e]["target"] == BACK for e in ("archived", "merged", "dropped", None))
      and reps["machine"]["ruling"] == "dropped", {k: (v["ruling"], v.get("hold")) for k, v in reps.items()})
tl = lambda n_, ruling_: router.twin_line(n_, "projects/delta", "projects/delta", "r1", "projects/charlie", ruling_, "x")["ruling"]
check("one-ruling: a person's message that follows an archive or a drop is merged into it (never archived or dropped), a bare laugh keeps the archive, machine news follows as before",
      tl(mk("t1", now_), "archived") == "merged" and tl(mk("t1", now_), "dropped") == "merged" and tl(mk("t1", now_), "passed") == "merged" and tl(mk("t2", now_, text="ok"), "archived") == "archived"
      and tl(mk("t3", now_, bot=True), "archived") == "archived" and tl(mk("t3", now_, bot=True), "passed") == "merged", None)

# ---- 13. a person's message does not follow an archive of its twin; the twin plan reads each holding page's log once
CALLS.clear(); PUSHED.clear(); PLAN.clear()
first = post("slack:C0000000009", "Dana", "will the charlie export be late again?", sessions=("de-name",))
routing.rule(first["projects/delta"]["id"], "archived", reason="an earlier archive", by="t")
second = post("slack:C0000000009", "Dana", "will the charlie export be late again?", sessions=("ch-name",))
res, pushed, ncalls = tick()
sc2 = second["projects/charlie"]
check("a person's notice never follows the earlier archive of its twin on the other page: it is ruled on its own, and reaches an agent", lv(sc2["id"])["rule"] == "gate-person" and lv(sc2["id"])["ruling"] in ("passed", "held") and lv(sc2["id"])["target"] == "ch-eng", lv(sc2["id"]))
evs = [post("slack:C0000000009", "Dana", t_, sessions=("de-name",))["projects/delta"] for t_ in ("is delta point one done?", "is delta point two done?", "is delta point three done?")]
groups_ = {a.pilot_root("projects/delta"): [("projects/delta", n_) for n_ in evs]}
reads, _real_read = [], routing.read
routing.read = lambda project, since=0.0: (reads.append(project), _real_read(project, since))[1]
try: live._twin_plan(groups_, live._last(), router.Context())
finally: routing.read = _real_read
check("the twin plan reads and folds each holding page's routing log once per tick, however many notices it checks (L3)", reads.count("projects/charlie") == 1, reads)
res, pushed, ncalls = tick()

# ---- 14. F1, F2, F3, F4 through the live tick: the near-misses reach an agent, never the archive
CALLS.clear(); PUSHED.clear(); PLAN.clear(); held.take("al-builder"); held.take("al-docs")
sysn = one("slack:C0000000001", router.SYSTEM_SENDERS[0], "the quarterly numbers moved once more")
botlike = one("slack:C0000000001", "deploy[bot]", "the vendor sent the signed file")
gh_bot = one("github:example-owner/repo#8", "ci-app[bot]", "left a comment on the pull request", kind="github", etype="comment")
down, mention = one("slack:C0000000001", "Dana", DOWN), one("slack:C0000000001", "Dana", "<@U0123ABCD>")
burst, jamo_yes = one("slack:C0000000001", "Dana", "2 more, the last: thx"), one("slack:C0000000001", "Dana", J(YES_JAMO, YES_JAMO))
check_ = one("slack:C0000000001", "Dana", CHECK)
res, pushed, ncalls = tick()
check("F2: a person whose display name is the system sender, with an event kind, is a person: held for the background agent when the call archives it, never archived", lv(sysn["id"])["ruling"] == "held" and lv(sysn["id"])["rule"] == "gate-person" and rec(sysn["id"])["ruling"] == "held", lv(sysn["id"]))
check("F1: a Slack sender named like a bot login is a person (held, not archived by gate-machine); a GitHub bot login is machine news, archived by rule",
      lv(botlike["id"])["rule"] != "gate-machine" and lv(botlike["id"])["ruling"] == "held" and lv(gh_bot["id"])["rule"] == "gate-machine" and lv(gh_bot["id"])["ruling"] == "archived", (lv(botlike["id"]), lv(gh_bot["id"])))
check("F3, F4: a thumbs down, a bare mention, a check mark, a jamo that is a word and a burst of two folded messages are not trivial: each is held for the background agent, none archived",
      all(lv(x["id"])["rule"] != "gate-trivial" and lv(x["id"])["ruling"] == "held" and rec(x["id"])["ruling"] == "held" for x in (down, mention, check_, jamo_yes, burst)), [(lv(x["id"])["rule"], lv(x["id"])["ruling"]) for x in (down, mention, check_, jamo_yes, burst)])
held.take("al-builder")

# ---- 15. a machine's archived notice wakes no wait, through the route tool too (person_wakes)
for g in ("a4", "a5"): item(int(g[1:]), "projects/alpha", "al-main", hold=True)
mw = one("slack:C0000000005", "deploybot", "build 42 finished", bot=True)
_wt_route._route(mw["id"], "archived", "", "nothing in it", "")
check("an archived notice of a bot wakes nothing on its anchor through the route tool (a person's would): both items still wait", held_items() == [True, True], held_items())

# ---- 16. a failing fallback never escapes the tick (L2): a hold for the background agent, else the notice stays unruled for the next tick
CALLS.clear(); PUSHED.clear(); FYI.clear(); PLAN.clear(); held.take("al-builder")
l2a = one("slack:C0000000001", "Dana", "the vendor revised the plan again")
l2b = one("slack:C0000000002", "Dana", "the shop opens late on Friday")
l2c = post("slack:C0000000009", "Dana", "can the charlie report wait for Monday?")["projects/charlie"]
_real_cp, _real_fb = router.call_project, router.fallback_line
def _boom(*a_, **k_): raise RuntimeError("it broke")
router.call_project, router.fallback_line, raised = _boom, _boom, None
try: res, pushed, ncalls = tick()
except Exception as e_: raised = e_
finally: router.call_project, router.fallback_line = _real_cp, _real_fb
check("a judging that fails with a failing fallback does not escape the tick: the person's message of a page with a background agent is held for it, a later project is still ruled", raised is None and lv(l2a["id"])["ruling"] == "held" and lv(l2a["id"])["held_for"] == BACK and lv(l2a["id"])["source"] == "fallback"
      and lv(l2c["id"])["rule"] == "gate-person", (raised, [x for x in lines() if x["id"] == l2a["id"]]))
check("…and the one of a page with no background agent stays unruled for the next tick, which rules it (held for the contact front agent)", not rec(l2b["id"], "projects/bravo").get("ruling") and (tick(), lv(l2b["id"]))[1]["held_for"] == "br-main", rec(l2b["id"], "projects/bravo"))
held.take("al-builder")
# ---- 17. M-1: a bare ack on an anchor an open item hangs on is no trivial notice: it goes the person path to the item's mover; where no item hangs it is still recorded and passed to nobody
CALLS.clear(); PUSHED.clear(); FYI.clear(); PLAN.clear(); held.take("al-builder"); held.take("al-docs")
_anchors = json.loads((T / "store/anchors.json").read_text())
_anchors["projects/alpha"].append(add("https://github.com/example-owner/repo/pull/9", ["a1"]))      # a pull request the builder's item hangs on
(T / "store/anchors.json").write_text(json.dumps(_anchors))
core._ROUTES["github:example-owner/repo#9"] = [{"project": "projects/alpha", "session": "al-name", "target": "for al-builder", "pilot": True, "filter": ""}]
ack_mail = one("gmail:" + "a" * 16, "Dana", "ok", kind="gmail")
ack_pr = one("github:example-owner/repo#9", "Dana", "+1", kind="github", etype="comment")
ack_free = [one("slack:C0000000001", "Dana", t_) for t_ in ("thx", "Thanks!", UP)]
res, pushed, ncalls = tick()
check("M-1: an ack ('ok') on a mail the builder's open item is scoped to goes the person path to that item's mover, not the archive",
      lv(ack_mail["id"])["rule"] == "gate-person" and lv(ack_mail["id"])["target"] == "al-builder" and lv(ack_mail["id"])["ruling"] in ("held", "passed") and rec(ack_mail["id"])["ruling"] in ("held", "passed"), (lv(ack_mail["id"]), rec(ack_mail["id"])))
check("M-1: a '+1' on a builder's pull request an open item hangs on is no trivial notice either: it is passed to the item's mover",
      lv(ack_pr["id"])["rule"] != "gate-trivial" and lv(ack_pr["id"])["ruling"] != "archived" and rec(ack_pr["id"])["ruling"] in ("held", "passed"), (lv(ack_pr["id"]), rec(ack_pr["id"])))
check("M-1: an ack on an anchor no open item hangs on is still read and recorded as archived (gate-trivial) and passed to nobody",
      all(lv(x["id"])["rule"] == "gate-trivial" and lv(x["id"])["ruling"] == "archived" and rec(x["id"])["ruling"] == "archived" for x in ack_free) and not any(x["id"] in t_ for x in ack_free for _, t_ in pushed), [lv(x["id"]) for x in ack_free])
check("M-1: _anchor_busy reads the mail anchor as busy and the free Slack anchor as not", router._anchor_busy("projects/alpha", {"anchor": "gmail:" + "a" * 16}, router.Context()) and not router._anchor_busy("projects/alpha", {"anchor": "slack:C0000000001"}, router.Context()), None)
held.take("al-builder"); held.take("al-docs")

# ---- 18. L-1: a person's message with no live background agent and a retired contact agent is never archived: unruled, counted as a retry, ruled when an agent is back
from stackshot.fleet import sessions_registry as _sr
DEAD2 = {"br-main"}; _sr_ret2 = _sr.retired; _sr.retired = lambda x: str(x) in DEAD2
try:
    CALLS.clear(); PUSHED.clear(); FYI.clear(); PLAN.clear()
    nb1 = one("slack:C0000000002", "Dana", "can the shop move the meeting to Friday?")
    nb2 = one("slack:C0000000002", "Dana", "the shop changed the delivery slot")      # nothing places it: the call (it says archived)
    res, pushed, ncalls = tick()
    check("L-1: a person's message of a page whose only agent has retired is neither ruled nor archived: no line, no routing ruling, no turn, counted as a retry",
          all(not [l for l in lines() if l["id"] == x["id"] and l.get("status") == "ruled"] and not rec(x["id"], "projects/bravo").get("ruling") for x in (nb1, nb2)) and res.get("retry", 0) >= 2 and not any(x[0] == "br-main" for x in pushed) and not FYI, (res, [x for x in lines() if x["id"] in (nb1["id"], nb2["id"])]))
    DEAD2.clear()
    res, pushed, ncalls = tick()
    check("…and when the contact agent is there again the next tick holds both for it, never archived", all(lv(x["id"])["ruling"] == "held" and lv(x["id"])["held_for"] == "br-main" and rec(x["id"], "projects/bravo")["ruling"] == "held" for x in (nb1, nb2)), [lv(x["id"]) for x in (nb1, nb2)])
    DEAD2.add("br-main")
    nb3 = one("slack:C0000000002", "Dana", "is the shop open on Sunday?")
    cx_none = router.Context(); cx_none.main_agent = lambda root: ""      # a page that lists no agent at all
    backstop = live._act(nb3, "projects/bravo", "projects/bravo", {"id": nb3["id"], "ruling": "passed", "target": "", "reason": "x", "person": True, "rule": "gate-person"}, cx_none, {})
    check("L-1: the act step itself never archives a person's pass that has no target: an error line, and the notice stays unruled", backstop["status"] == "error" and backstop["ruling"] != "archived" and not rec(nb3["id"], "projects/bravo").get("ruling"), backstop)
finally: _sr.retired = _sr_ret2
held.take("br-main")
res, pushed, ncalls = tick(); held.take("br-main")

# ---- 19. L-2: a held person line of an agent that retired after the hold is moved to the page's live background agent, else its contact agent, at the next tick (only to one whose hook fetches held lines; the line keeps its time)
held.take("al-builder"); held.take("al-docs"); held.take("al-main")
T_OLD = time.time() - 3 * 3600
held.add(held.key_of("al-builder"), "person", "a person's words, held before the builder retired", sender="Dana", nid="rh-1", whole=True, now=T_OLD)
held.add(held.key_of("al-builder"), "closed", "an item closed", nid="rh-2")
DEAD3 = {"al-builder"}; _sr.retired = lambda x: str(x) in DEAD3
FETCH = {"al-docs", "al-main"}; _real_fetch = held.can_fetch; held.can_fetch = lambda t, now=None: t in FETCH
try:
    moved1 = live.rehome_person(router.Context())
    docs_rows = held._read(held._file(held.key_of("al-docs"))); builder_left = [r["kind"] for r in held._read(held._file(held.key_of("al-builder")))]
    DEAD3.add("al-docs")
    held.add(held.key_of("al-docs"), "person", "a second person's message", sender="Dana", nid="rh-3", whole=True)
    moved2 = live.rehome_person(router.Context())
    main_rows = held._read(held._file(held.key_of("al-main"))); main_has = held.take("al-main"); docs_left = held.count("al-docs")
    held.add(held.key_of("al-docs"), "person", "a third person's message", sender="Dana", nid="rh-5", whole=True)
    FETCH.discard("al-main"); moved3 = live.rehome_person(router.Context()); stays3 = held.count("al-docs"); FETCH.add("al-main")      # the contact's hook fetches no held lines: the line stays
    DEAD3.update({"al-main"}); moved4 = live.rehome_person(router.Context()); stays4 = held.count("al-docs")      # every agent of the page is gone: nowhere to move it
finally: _sr.retired = _sr_ret2; held.can_fetch = _real_fetch
check("L-2: a person line held for a retired background agent moves to the page's other live background agent (the other kinds stay: nobody asked for them), keeping its own time; with that one gone too, to the contact agent",
      moved1 == 1 and len(docs_rows) == 1 and docs_rows[0]["ts"] == T_OLD and builder_left == ["closed"] and moved2 == 2 and "a second person's message" in main_has and "held before the builder retired" in main_has and docs_left == 0 and [r["ts"] for r in main_rows if "builder retired" in r["text"]] == [T_OLD], (moved1, docs_rows[0]["ts"] == T_OLD, builder_left, moved2, "a second person's message" in main_has, "held before the builder retired" in main_has, docs_left))
check("L-2: a destination whose hook fetches no held lines (the rollout gate) is not chosen, and with every agent of the page gone nothing moves", moved3 == 0 and stays3 == 1 and moved4 == 0 and stays4 == 1, (moved3, stays3, moved4, stays4))
held.take("al-docs"); held.take("al-builder")
check("L-2: nothing moves when no agent is gone", live.rehome_person(router.Context()) == 0, None)
held.add(held.key_of("al-builder"), "person", "a person's words, held before the next tick", sender="Dana", nid="rh-4", whole=True)
one("slack:C0000000001", "Dana", "the vendor confirmed Monday")      # any notice: the tick that rules it re-homes first
DEAD3 = {"al-builder"}; _sr.retired = lambda x: str(x) in DEAD3
try: res, pushed, ncalls = tick()
finally: _sr.retired = _sr_ret2
check("L-2: the tick itself re-homes it (before it rules), so a line never waits for an agent that is not coming back", not [r for r in held._read(held._file(held.key_of("al-builder"))) if r["kind"] == "person"] and "held before the next tick" in held.take("al-docs"), held._read(held._file(held.key_of("al-builder"))))
held.take("al-builder"); held.take("al-docs"); held.take("al-main")

# ---- 20. L-3: a surface agent is never a place for a held line; a burst is a bot's only when every event it folds is; a repeat prefers an earlier one that reached somebody
cxs = router.Context()
cxs.reg = {**cxs.reg, "projects/echo": {**cxs.reg["projects/alpha"], "agents": {"ec-main": "contact", "ec-slack": "builds and answers the Slack app", "ec-eng": "keeps the pages"}, "back_agents": {"ec-slack": "builds and answers the Slack app", "ec-eng": "keeps the pages"},
                                        "surface_agents": {"ec-slack": "slack"}}}
cxs._surface = None
check("L-3: a surface agent is gone (no hook of it reads held lines) and is skipped as the page's background agent, the live one after it is chosen; a contact agent is not gone",
      cxs.gone("ec-slack") and not cxs.gone("ec-eng") and not cxs.gone("ec-main") and not cxs.gone("") and cxs.live_background("projects/echo") == "ec-eng", (cxs.gone("ec-slack"), cxs.live_background("projects/echo")))
def burst(bots):
    ev_ = core.Event(anchor="slack:C0000000001", kind="slack", title="#x", who="Dana", text="the last one", url="https://u/burst-" + "".join(map(str, map(int, bots))), bot=bots[-1])
    hub.send_burst("slack:C0000000001", "al-name", {"count": len(bots), "first": time.time(), "last_at": time.time(), "label": "slack:C0000000001", "last": ev_, "kind": "slack", "etypes": [], "whos": [], "texts": [], "bots": list(bots)})
    return routing.read("projects/alpha")[-1]
mixed, allbot = burst([True, False]), burst([True, True])
check("L-3: a follow-up that folds a bot's post and a person's is a person's (bot false); one that folds only bots' posts is a bot's", not mixed.get("bot") and allbot.get("bot") is True, (mixed.get("bot"), allbot.get("bot")))
nowx = time.time(); cx_ = router.Context(); _real_code = router._code_rule
mk2 = lambda i, ts, **kw: {"id": i, "ts": ts, "kind": "anchor", "anchor": "slack:C0000000001", "who": "Dana", "text": "can you check the April numbers?", "url": "https://u/rp2", "label": "Slack", "ekind": "slack", **kw}
try:
    router._code_rule = lambda key, n, root, cx_x, peers: {"id": n["id"], "key": key, "project": root, "kind": "anchor", "ts": nowx, "source": "code", "rule": "repeat", "ruling": "dropped", "target": "", "reason": "a stub", "for_owner": False, "item": "", "call": "", "label": "", "text": "", "note": ""}
    rep_two = router.code_rule("projects/alpha", mk2("f3", nowx), "projects/alpha", cx_, [mk2("f1", nowx - 120, ruling="archived"), mk2("f2", nowx - 60, ruling="passed")])
    rep_one = router.code_rule("projects/alpha", mk2("f3", nowx), "projects/alpha", cx_, [mk2("f2", nowx - 60, ruling="passed"), mk2("f1", nowx - 120, ruling="archived")])
finally: router._code_rule = _real_code
check("L-3: of several identical earlier messages the repeat rule looks at one that reached somebody (passed), whatever their order: the repeat is dropped", rep_two["ruling"] == "dropped" and rep_one["ruling"] == "dropped", (rep_two, rep_one))
# ---- 21. an ack on an anchor an item waits on wakes it when the person path ends in a held line for a front agent (mover a front agent that needs the owner), and through the route tool
def held2(): return bool(_service_store._load("a2")["metadata"].get("hold"))
CALLS.clear(); PUSHED.clear(); FYI.clear(); PLAN.clear(); held.take("al-builder"); held.take("al-docs")
DEAD7 = {"al-builder", "al-docs"}; _sr.retired = lambda x: str(x) in DEAD7      # the page's background agents are gone: its contact agent is the one place left
item(2, "projects/alpha", "al-main", hold=True)      # a front agent's item on the mail anchor B that waits on a reply, parked
try:
    fk = one("gmail:" + "b" * 16, "Dana", "ok", kind="gmail")
    res, pushed, ncalls = tick()
    r_fk = (lv(fk["id"]), held2())
    item(2, "projects/alpha", "al-main", hold=True)
    fk2 = one("gmail:" + "b" * 16, "Dana", "sounds good, go ahead", kind="gmail")
    res, pushed, ncalls = tick()
    r_fk2 = (lv(fk2["id"]), held2())
finally: _sr.retired = _sr_ret2
check("a bare ack on a mail a front agent's item waits on, with no background agent left to pass it to, is held for that front agent, and the held line wakes the parked item", r_fk[0]["rule"] == "gate-person" and r_fk[0]["ruling"] == "held" and r_fk[0]["held_for"] == "al-main" and not r_fk[1], r_fk)
check("…the same as any other reply of the person does (the reply with words wakes it too)", r_fk2[0]["ruling"] == "held" and r_fk2[0]["held_for"] == "al-main" and not r_fk2[1], r_fk2)
item(2, "projects/alpha", "al-main", hold=True)
item(2, "projects/alpha", "al-main", hold=True)
fk3 = one("gmail:" + "b" * 16, "Dana", "thx", kind="gmail")
_wt_route._route(fk3["id"], "archived", "", "nothing in it", "")
check("the route tool wakes the parked item on an archived ruling of a bare ack on an anchor the item waits on", not held2(), held2())
item(2, "projects/alpha", "al-main", hold=True)
fk4 = one("slack:C0000000001", "Dana", "thx")      # an anchor no item hangs on: a bare ack wakes nothing, as before
_wt_route._route(fk4["id"], "archived", "", "nothing in it", "")
check("…and an ack on an anchor no item hangs on wakes nothing", held2() and router.person_wakes(fk4, False) is False and router.person_wakes(fk4, True) is True, held2())
item(2, "projects/alpha", "al-main"); held.take("al-builder"); held.take("al-docs"); held.take("al-main")

# ---- 22. a person's message on an anchor scoped to an item goes to a LIVE agent: the mover, else the page's live background agent, else its contact agent, else it stays unruled (anchor-item)
_anchors = json.loads((T / "store/anchors.json").read_text())
_anchors["projects/alpha"].append(add("https://x.slack.com/archives/C0000000010", ["a1"]))      # a channel scoped to the builder's item
(T / "store/anchors.json").write_text(json.dumps(_anchors))
core._ROUTES["slack:C0000000010"] = [{"project": "projects/alpha", "session": "al-name", "target": "for al-builder", "pilot": True, "filter": ""}]
DEAD4 = set(); _sr.retired = lambda x: str(x) in DEAD4
def ai_case(words):
    CALLS.clear(); PUSHED.clear(); FYI.clear(); held.take("al-builder"); held.take("al-docs"); held.take("al-main")
    x = one("slack:C0000000010", "Dana", words)
    res_, pushed_, ncalls_ = tick()
    return x, res_, pushed_, ncalls_
try:
    x_a, r_a, p_a, c_a = ai_case("the file is ready")
    DEAD4.add("al-builder"); x_b, r_b, p_b, c_b = ai_case("the file is ready again")
    x_b2, r_b2, p_b2, c_b2 = ai_case("ok")
    DEAD4.add("al-docs"); x_c, r_c, p_c, c_c = ai_case("the file is ready once more")
    DEAD4.add("al-main"); x_d, r_d, p_d, c_d = ai_case("the file is ready, last time")
    d_unruled = (not [l for l in lines() if l["id"] == x_d["id"] and l.get("status") == "ruled"], not rec(x_d["id"]).get("ruling"), c_d, r_d.get("retry"), [l for l in lines() if l["id"] == x_d["id"]])
    DEAD4.clear(); ai_case("a message written while nobody was there is read when somebody is back")
finally: _sr.retired = _sr_ret2
check("anchor-item, mover live: a person's message on the channel scoped to the builder's item goes to the builder, as before", lv(x_a["id"])["rule"] == "anchor-item" and lv(x_a["id"])["target"] == "al-builder" and lv(x_a["id"])["ruling"] in ("held", "passed"), lv(x_a["id"]))
check("anchor-item, mover retired: it goes to the page's live background agent (held for it), and a bare ack on the same page too (passed to it), nothing is pushed to the retired mover",
      lv(x_b["id"])["rule"] == "anchor-item" and lv(x_b["id"])["ruling"] == "held" and lv(x_b["id"])["held_for"] == "al-docs" and lv(x_b2["id"])["target"] == "al-docs" and any(t == "al-docs" for t, _ in p_b2) and not any(t == "al-builder" for t, _ in p_b + p_b2), (lv(x_b["id"]), lv(x_b2["id"]), p_b2))
check("anchor-item, every background agent retired: it is held for the page's contact agent (a held line, no turn started)", lv(x_c["id"])["ruling"] == "held" and lv(x_c["id"])["held_for"] == "al-main" and not any(t in ("al-builder", "al-docs", "al-main") for t, _ in p_c), (lv(x_c["id"]), FYI, p_c))
check("anchor-item, every agent of the page retired: unruled and never sent to anyone (no line, no routing ruling, no model call, counted once)", all(d_unruled[:2]) and d_unruled[2] == 0 and not any(t in ("al-builder", "al-docs", "al-main") for t, _ in p_d), d_unruled)
check("…and it is ruled like any other the tick an agent is back (the mover, live again)", lv(x_d["id"])["rule"] == "anchor-item" and lv(x_d["id"])["target"] == "al-builder", lv(x_d["id"]))
held.take("al-builder"); held.take("al-docs"); held.take("al-main")

# ---- 23. a page with no live place for a person's message parks its person notices: no model call, no use of the batch cap that a later notice needs, one line each
_real_router_cfg = dict(_cfg.CFG["router"]); _cfg.CFG["router"]["max_notices"] = 2
DEAD5 = {"br-main"}; _sr.retired = lambda x: str(x) in DEAD5
try:
    CALLS.clear(); PUSHED.clear(); FYI.clear(); PLAN.clear()
    st = [one("slack:C0000000002", "Dana", t_) for t_ in ("is the shop open on Monday?", "can the shop change the slot?", "the shop moved the delivery")]
    bot_late = one("slack:C0000000002", "deploybot", "build 43 finished", bot=True)
    res1, pushed1, ncalls1 = tick(); res2, pushed2, ncalls2 = tick(); res3, pushed3, ncalls3 = tick()
    parked_lines = [l for l in lines() if l.get("status") == "parked" and l["id"] in {x["id"] for x in st}]
    check("L-1/M-3: three parked person notices and a later bot notice with a batch of two: the bot notice is ruled (the parked ones use no place in the batch)", lv(bot_late["id"])["rule"] == "gate-machine" and lv(bot_late["id"])["ruling"] == "archived", [l for l in lines() if l["id"] == bot_late["id"]])
    check("…no model call is made for a page with no live place for a person's message, on any of the ticks", not CALLS and ncalls1 == ncalls2 == ncalls3 == 0, (len(CALLS), ncalls1, ncalls2, ncalls3))
    check("…each parked notice is surfaced once (one line each, one count in `retry` the first tick and none after), stays unruled, nothing is pushed or held for the retired contact",
          len(parked_lines) == 3 and len({l["id"] for l in parked_lines}) == 3 and res1["retry"] == 3 and res2["retry"] == 0 and res3["retry"] == 0 and all(not rec(x["id"], "projects/bravo").get("ruling") for x in st) and not FYI and not pushed1 + pushed2 + pushed3,
          (len(parked_lines), res1, res2, res3))
    DEAD5.clear(); res4, pushed4, ncalls4 = tick(); res5, pushed5, ncalls5 = tick()
    check("…and the ticks after the contact agent is back rule them as any other notice (two a tick), held for it", all(lv(x["id"])["ruling"] == "held" and lv(x["id"])["held_for"] == "br-main" for x in st), [lv(x["id"])["ruling"] for x in st])
finally: _sr.retired = _sr_ret2; _cfg.CFG["router"].clear(); _cfg.CFG["router"].update(_real_router_cfg)
held.take("br-main")

# ---- 24. only the contact agent retired: the needs path never picks it, and another live front agent takes its place
DEAD6 = {"al-main"}; _sr.retired = lambda x: str(x) in DEAD6
try:
    CALLS.clear(); PUSHED.clear(); FYI.clear(); held.take("al-builder"); held.take("al-docs")
    item(2, "projects/alpha", "al-main", needs="decision")
    nd = one("gmail:" + "b" * 16, "Dana", "Oliver, I need your yes on the draft, can you decide?", kind="gmail")
    res, pushed, ncalls = tick()
    item(2, "projects/alpha", "al-main")
    cxf = router.Context(); cxf.reg = {**cxf.reg, "projects/foxtrot": {**cxf.reg["projects/alpha"], "agents": {"fo-main": "contact", "fo-front": "the second contact", "fo-eng": "keeps the pages"}, "back_agents": {"fo-eng": "keeps the pages"}}}
    DEAD6.clear(); DEAD6.add("fo-main"); contact_fb = cxf.contact("projects/foxtrot"); DEAD6.add("fo-front"); contact_none = cxf.contact("projects/foxtrot")
finally: _sr.retired = _sr_ret2
check("L-1: a message that needs the owner, with the page's only contact agent retired, goes to the page's live background agent, never to the retired contact", lv(nd["id"])["target"] != "al-main" and lv(nd["id"])["held_for"] in ("al-builder", "al-docs") and ("al-main", "person", nd["id"]) not in FYI and not any(t == "al-main" for t, _ in pushed), (lv(nd["id"]), FYI))
check("L-1: a retired -main agent gives way to another live front agent of the page, and with every front agent gone there is none", contact_fb == "fo-front" and contact_none == "", (contact_fb, contact_none))
held.take("al-builder"); held.take("al-docs")
# ---- 25. anchor-item, the build-side branch: a person's comment on a repository's notifications (no thread of its own) scoped to a front agent's item goes to the builder; with the builder retired it goes to a live agent of the page, never to the retired one
GH9 = "github:example-owner/repo@notifications"
_anchors = json.loads((T / "store/anchors.json").read_text())
_anchors["projects/alpha"].append(add(GH9, ["a2"]))
(T / "store/anchors.json").write_text(json.dumps(_anchors))
core._ROUTES[GH9] = [{"project": "projects/alpha", "session": "al-name", "target": "for al-main", "pilot": True, "filter": ""}]
DEAD8 = set(); _sr.retired = lambda x: str(x) in DEAD8
def bs_case(words):
    CALLS.clear(); PUSHED.clear(); FYI.clear(); held.take("al-builder"); held.take("al-docs"); held.take("al-main")
    x = one(GH9, "Dana", words, kind="github", etype="comment")
    res_, pushed_, ncalls_ = tick()
    return x, pushed_
try:
    b_a, pb_a = bs_case("the change reads fine to me")
    DEAD8.add("al-builder"); b_b, pb_b = bs_case("the change still reads fine to me")
    DEAD8.add("al-docs"); b_c, pb_c = bs_case("the change reads fine to me, once more")
finally: _sr.retired = _sr_ret2
check("anchor-item, build-side: a person's comment on a repository's notifications scoped to a front agent's item goes to the builder, as before", lv(b_a["id"])["rule"] == "anchor-item" and lv(b_a["id"])["target"] == "al-builder" and lv(b_a["id"])["ruling"] in ("held", "passed"), lv(b_a["id"]))
check("anchor-item, build-side, builder retired: it is held for the page's other live background agent, nothing is pushed to the retired builder",
      lv(b_b["id"])["rule"] == "anchor-item" and lv(b_b["id"])["ruling"] == "held" and lv(b_b["id"])["held_for"] == "al-docs" and not any(t == "al-builder" for t, _ in pb_b), (lv(b_b["id"]), pb_b))
check("anchor-item, build-side, every background agent retired: it is held for the page's contact agent (a held line, no turn started)",
      lv(b_c["id"])["rule"] == "anchor-item" and lv(b_c["id"])["ruling"] == "held" and lv(b_c["id"])["held_for"] == "al-main" and not any(t in ("al-builder", "al-docs") for t, _ in pb_c), (lv(b_c["id"]), pb_c))
held.take("al-builder"); held.take("al-docs"); held.take("al-main")

# ---- 26. a person's message is never passed to an agent that is gone, by ANY rule that names a target: anchor-builder, anchor-work, watch, anchor-item, the gate and the thin call (live_place_line)
_anchors = json.loads((T / "store/anchors.json").read_text())
_anchors["projects/alpha"] += [add("https://x.slack.com/archives/C0000000020#mention=ship"), add("https://x.slack.com/archives/C0000000021")]
(T / "store/anchors.json").write_text(json.dumps(_anchors))
for _a in ("slack:C0000000020", "slack:C0000000021"): core._ROUTES[_a] = [{"project": "projects/alpha", "session": "al-name", "target": "project-wide", "pilot": True, "filter": ""}]
router.WATCH[("projects/alpha", "slack:C0000000021")] = "al-docs"
import itertools; _U = itertools.count(1000)
DEADR = set(); _sr.retired = lambda x: str(x) in DEADR
ALL3 = {"al-builder", "al-docs", "al-main"}
def rc(dead, mk, plan=None):
    DEADR.clear(); DEADR.update(dead)
    CALLS.clear(); PUSHED.clear(); FYI.clear(); PLAN.clear(); [held.take(a_) for a_ in sorted(ALL3)]
    x = mk()
    if plan: PLAN[x["id"]] = plan
    res_, pushed_, ncalls_ = tick()
    return x, pushed_
def parked_of(x): return [l for l in lines() if l["id"] == x["id"] and l.get("status") == "parked"]
def class_checks(name, rule, tgt, other, mk, plan=None, source="code", live_rule=None, held_rule=None):
    held_rule = held_rule or rule
    try:
        x1, p1 = rc(set(), mk, plan); x2, p2 = rc({tgt}, mk, plan); x3, p3 = rc({"al-builder", "al-docs"}, mk, plan); x4, p4 = rc(ALL3, mk, plan)
    finally: DEADR.clear()
    check(f"{name}: the target live: the rule passes it there, as before", lv(x1["id"])["rule"] == (live_rule if live_rule is not None else rule) and lv(x1["id"])["target"] == tgt and lv(x1["id"])["source"] == source and lv(x1["id"])["ruling"] in ("held", "passed"), lv(x1["id"]))
    check(f"{name}: the target retired: held for the page's other live background agent, nothing pushed to the retired one",
          lv(x2["id"])["rule"] == held_rule and lv(x2["id"])["ruling"] == "held" and lv(x2["id"])["held_for"] == other and not any(t == tgt for t, _ in p2), (lv(x2["id"]), p2))
    check(f"{name}: every background agent retired: held for the page's contact agent, a held line that starts no turn",
          lv(x3["id"])["rule"] == held_rule and lv(x3["id"])["ruling"] == "held" and lv(x3["id"])["held_for"] == "al-main" and not any(t in ("al-builder", "al-docs") for t, _ in p3), (lv(x3["id"]), p3))
    check(f"{name}: every agent of the page retired: parked, never ruled and never sent to anyone",
          len(parked_of(x4)) == 1 and not [l for l in lines() if l["id"] == x4["id"] and l.get("status") == "ruled"] and not rec(x4["id"]).get("ruling") and not p4, (parked_of(x4), p4))
    tick(); PUSHED.clear(); [held.take(a_) for a_ in sorted(ALL3)]      # the parked one is ruled once its agents are back: no notice of this section is left for a later one
try:
    class_checks("anchor-builder (a pull request on a builder's branch)", "anchor-builder", "al-builder", "al-docs", lambda: one("github:example-owner/repo#8", "Dana", f"the change looks right {next(_U)}", kind="github", etype="comment", head="al-builder/topic"))
    class_checks("anchor-work (an anchor with a mention filter, the page's work agent)", "anchor-work", "al-docs", "al-builder", lambda: one("slack:C0000000020", "Dana", f"the file shipped {next(_U)}"))
    class_checks("watch (a standing watch on an anchor)", "watch", "al-docs", "al-builder", lambda: one("slack:C0000000021", "Dana", f"the file moved {next(_U)}"), held_rule="gate-person")      # a watch keeps its own delivery, so a person's message the watch cannot deliver is a gate-person line
    class_checks("anchor-item (an anchor scoped to an item, its mover)", "anchor-item", "al-builder", "al-docs", lambda: one("slack:C0000000010", "Dana", f"the file is ready {next(_U)}"))
    class_checks("the thin call (it names an agent that is gone)", "gate-person", "al-builder", "al-docs", lambda: one("slack:C0000000001", "Dana", f"the vendor confirmed a new date {next(_U)}"),
                 plan={"ruling": "passed", "target": "al-builder", "reason": "the builder should read it", "for_owner": False}, source="call", live_rule="")
finally: del router.WATCH[("projects/alpha", "slack:C0000000021")]; _sr.retired = _sr_ret2
held.take("al-builder"); held.take("al-docs"); held.take("al-main")

# ---- 27. one event on two pages, the page it is about has nobody alive: the other page's agent takes it (the leader is chosen among the pages with a live place; a follower never waits for a parked leader)
DEAD9 = {"ch-main", "ch-eng"}; _sr.retired = lambda x: str(x) in DEAD9
_real_plan = live._twin_plan
try:
    CALLS.clear(); PUSHED.clear(); FYI.clear(); PLAN.clear(); held.take("de-eng"); held.take("de-main")
    ev = post("slack:C0000000009", "Dana", "can the charlie export wait for the delta numbers?")
    res, pushed, ncalls = tick(); res2, pushed2, ncalls2 = tick()
    ch_n, de_n = ev["projects/charlie"], ev["projects/delta"]
    check("one event on two pages, the page it is about (a scoped item) has no live agent: the other page's agent is the leader and takes it (never left unruled)",
          lv(de_n["id"])["ruling"] in ("held", "passed") and lv(de_n["id"])["held_for" if lv(de_n["id"])["ruling"] == "held" else "target"] == "de-eng" and not parked_of(de_n), (lv(de_n["id"]), parked_of(de_n)))
    check("…the notice of the dead page follows that ruling (it is not parked behind it), and nothing was pushed to a retired agent",
          lv(ch_n["id"])["rule"] == "one-ruling" and not parked_of(ch_n) and not any(t in DEAD9 for t, _ in pushed + pushed2) and res["retry"] == 0, (lv(ch_n["id"]), parked_of(ch_n), res))
    held.take("de-eng"); held.take("de-main")
    # a plan that makes the dead page the leader anyway (the safety net): the follower rules itself, and the leader is parked
    PUSHED.clear(); FYI.clear()
    ev2 = post("slack:C0000000009", "Dana", "will the charlie export reach the delta shop on Friday?")
    ch2, de2 = ev2["projects/charlie"], ev2["projects/delta"]
    live._twin_plan = lambda g, l, c: ({str(de2["id"]): (str(ch2["id"]), "projects/charlie", "projects/charlie")}, {}, {})
    res3, pushed3, ncalls3 = tick(); res4, pushed4, ncalls4 = tick()
    check("a follower whose leader is parked (no live agent on its page) rules itself: the live page's notice is ruled, the dead page's stays parked, once",
          lv(de2["id"])["rule"] != "one-ruling" and lv(de2["id"])["ruling"] in ("held", "passed") and len(parked_of(ch2)) == 1 and not [l for l in lines() if l["id"] == ch2["id"] and l.get("status") == "ruled"] and res3["retry"] == 1 and res4["retry"] == 0,
          (lv(de2["id"]), parked_of(ch2), res3, res4))
    live._twin_plan = _real_plan; held.take("de-eng"); held.take("de-main")
    # a follower on a dead page, its live leader (the delta notice) ruled: it follows, it is not parked
    PUSHED.clear(); FYI.clear()
    ev3 = post("slack:C0000000009", "Dana", "is the delta quote final?")
    ch3, de3 = ev3["projects/charlie"], ev3["projects/delta"]
    live._twin_plan = lambda g, l, c: ({str(ch3["id"]): (str(de3["id"]), "projects/delta", "projects/delta")}, {}, {})
    res5, pushed5, ncalls5 = tick()
    check("a follower on a dead page whose leader is live follows the leader's ruling, and is not parked", lv(ch3["id"])["rule"] == "one-ruling" and not parked_of(ch3) and lv(de3["id"])["ruling"] in ("held", "passed"), (lv(ch3["id"]), parked_of(ch3), lv(de3["id"])))
finally: live._twin_plan = _real_plan; _sr.retired = _sr_ret2
held.take("de-eng"); held.take("de-main")
DEAD9.clear(); tick(); PUSHED.clear(); held.take("de-eng"); held.take("de-main"); held.take("ch-eng"); held.take("ch-main")

# ---- 28. the lows of round 4: a bare ack goes where its own page has an item waiting (not another page's); a person's line on a retired agent is re-homed on every tick and to any live agent of the page; one `stranded` line when there is none; anchor-item and the gate agree on the item's doer
item(40, "projects/bravo", "br-main", wait_anchor="slack:C0000000009")      # another page's item waits on the same anchor too
x_ack = post("slack:C0000000009", "Dana", "ok", sessions=("de-name",))["projects/delta"]
res, pushed, ncalls = tick()
(T / "store/a/40.json").unlink()
check("an ack on a page where no item hangs on the anchor (another page's item does) is read as trivial: archived, passed to nobody", lv(x_ack["id"])["rule"] == "gate-trivial" and lv(x_ack["id"])["ruling"] == "archived" and not pushed, (lv(x_ack["id"]), pushed))
x_ack2 = post("slack:C0000000009", "Dana", "ok", sessions=("ch-name",))["projects/charlie"]
res, pushed, ncalls = tick()
check("…and on the page whose item is scoped to the anchor it is the answer the item waits for: the ordinary person path", lv(x_ack2["id"])["rule"] != "gate-trivial" and lv(x_ack2["id"])["ruling"] in ("held", "passed"), lv(x_ack2["id"]))
held.take("ch-eng"); held.take("ch-main")

T_OLD2 = time.time() - 7200
FETCH2 = {"fo-c", "fo-main"}; _real_fetch = held.can_fetch; held.can_fetch = lambda t, now=None: t in FETCH2
cxf = router.Context(); cxf.reg = {**cxf.reg, "projects/foxtrot": {**cxf.reg["projects/alpha"], "agents": {"fo-main": "contact", "fo-a": "builds", "fo-b": "keeps the pages", "fo-c": "reviews"}, "back_agents": {"fo-a": "builds", "fo-b": "keeps the pages", "fo-c": "reviews"}}}
DEAD10 = {"fo-a"}; _sr.retired = lambda x: str(x) in DEAD10
try:
    for _k in ("fo-a", "fo-b", "fo-c", "fo-main"): held.take(_k)
    held.add(held.key_of("fo-a"), "person", "a person's words for a builder that retired", sender="Dana", nid="rh-7", whole=True, now=T_OLD2)
    mv1 = live.rehome_person(cxf); left1 = [k for k in ("fo-b", "fo-c", "fo-main") if held.count(k)]
    FETCH2.clear(); FETCH2.add("fo-b")      # the other order: whichever of the two live background agents is ranked first, the one that fetches gets it
    for _k in ("fo-b", "fo-c", "fo-main"): held.take(_k)
    held.add(held.key_of("fo-a"), "person", "a second person's words for a builder that retired", sender="Dana", nid="rh-8", whole=True, now=T_OLD2)
    mv2 = live.rehome_person(cxf); left2 = [k for k in ("fo-b", "fo-c", "fo-main") if held.count(k)]
    for _k in ("fo-b", "fo-c", "fo-main"): held.take(_k)
    FETCH2.clear()      # no live agent of the page fetches held lines: the line stays, one `stranded` line says so, and only once
    held.add(held.key_of("fo-a"), "person", "a third person's words, nobody to take them", sender="Dana", nid="rh-9", whole=True, now=T_OLD2)
    mv3 = live.rehome_person(cxf); mv3b = live.rehome_person(cxf)
    stranded = [l for l in lines() if l.get("status") == "stranded" and "nobody to take them" in l["text"]]
finally: _sr.retired = _sr_ret2; held.can_fetch = _real_fetch
check("L-2/L-3: a person's line of a retired agent goes to the first live agent of its page that fetches held lines, whichever of the page's background agents that is (not only the top-ranked one and the contact agent)",
      mv1 == 1 and left1 == ["fo-c"] and mv2 == 1 and left2 == ["fo-b"], (mv1, left1, mv2, left2))
check("L-3: with no live agent that fetches held lines the line stays and one `stranded` line says so, once, however many ticks look at it", mv3 == 0 and mv3b == 0 and held.count("fo-a") == 1 and len(stranded) == 1 and "gone" in stranded[0]["reason"], (mv3, mv3b, held.count("fo-a"), stranded))
for _k in ("fo-a", "fo-b", "fo-c", "fo-main"): held.take(_k)
held.add(held.key_of("al-builder"), "person", "a person's words, held before the builder retired (no notice comes in)", sender="Dana", nid="rh-10", whole=True)
_real_projects = live._routing.projects; live._routing.projects = lambda: []      # no unruled notice anywhere: the tick has nothing to judge
DEAD11 = {"al-builder"}; _sr.retired = lambda x: str(x) in DEAD11
try: res_empty = tick()
finally: live._routing.projects = _real_projects; _sr.retired = _sr_ret2
check("L-2: a tick with no notice to judge still re-homes a person's line of a retired agent", not [r for r in held._read(held._file(held.key_of("al-builder"))) if r["kind"] == "person"] and held.count("al-docs") == 1, (res_empty, held.count("al-docs")))
held.take("al-builder"); held.take("al-docs"); held.take("al-main")

_anchors = json.loads((T / "store/anchors.json").read_text()); _anchors["projects/alpha"].append(add("https://x.slack.com/archives/C0000000022", ["a2"])); (T / "store/anchors.json").write_text(json.dumps(_anchors))
core._ROUTES["slack:C0000000022"] = [{"project": "projects/alpha", "session": "al-name", "target": "for al-main", "pilot": True, "filter": ""}]
item(2, "projects/alpha", "al-main", next="al-docs: review the draft")      # a front agent moves it, the pages' agent does the work (its first next line)
DEAD12 = {"al-main"}; _sr.retired = lambda x: str(x) in DEAD12
try:
    CALLS.clear(); PUSHED.clear(); FYI.clear(); PLAN.clear()
    q_ = one("slack:C0000000022", "Dana", "is the draft ready for the review?"); s_ = one("slack:C0000000022", "Dana", "the draft is ready for the review")
    res, pushed, ncalls = tick()
finally: _sr.retired = _sr_ret2; item(2, "projects/alpha", "al-main")
check("L-5: a question (the gate) and a statement (anchor-item) on an item's anchor, its front mover retired, go to the same live agent with the same item: the one that does the item's work",
      lv(q_["id"])["rule"] == "gate-person" and lv(s_["id"])["rule"] == "anchor-item" and lv(q_["id"])["target"] == lv(s_["id"])["target"] == "al-docs" and lv(q_["id"])["item"] == lv(s_["id"])["item"] == "a2", (lv(q_["id"]), lv(s_["id"])))
held.take("al-builder"); held.take("al-docs"); held.take("al-main")


if os.environ.get("ROUTER_GATE_STAGED"):      # the staged dry run: one line per path, as the live tick ruled each notice above (tests/run-suite router_gate with ROUTER_GATE_STAGED=1)
    for path, nid in (("machine: a bot's post", m_bot), ("machine: a routine pull request event", m_pr), ("machine: the owner's own document edit", m_own), ("machine: a CI result", m_ci),
                      ("machine, for the owner (strong text): not archived", m_strong), ("machine, on an anchor an item hangs on: not archived", m_busy),
                      ("person: question, item moved by a background agent", p_ask), ("person: names the owner, project-wide anchor", p_name), ("person: question about a front agent's item", p_front_item),
                      ("person: needs the owner, front mover", p_needs), ("person: thread reply", p_thread), ("person: item that is his own move", p_his), ("person: written by an agent itself", p_self),
                      ("unplaceable, call said archived", u1), ("unplaceable, call said dropped", u2), ("unplaceable, call said merged", u3), ("unplaceable, call passed to an agent", u4),
                      ("unplaceable, call timed out", f1), ("unplaceable, answer did not parse", f2), ("a record with no author kind", old),
                      ("no background agent, unplaceable", b1), ("no background agent, placed", b2), ("no background agent, front gate cannot file it", b3), ("a person's picture", img),
                      ("two pages, one anchor: ruled page", pair["projects/charlie"]["id"] and pair["projects/charlie"]), ("two pages, one anchor: the follower", pair["projects/delta"]),
                      ("trivial: a run of laughter jamo", triv[0]), ("trivial: haha, in a thread", triv[1]), ("trivial: :thumbsup:", triv[3]), ("trivial: an emoji", triv[4]), ("an ack on an anchor items wait on", t_triv), ("a person's notice the call archived (wake)", w1), ("an identical repeat", r2)):
        nid = nid["id"] if isinstance(nid, dict) else nid
        l = lv(nid)
        print(f"STAGED {path:<58} rule={l.get('rule') or '-':<13} ruling={l['ruling']:<8} target={l.get('target') or l.get('held_for') or '-':<10} hold={l.get('hold') or '-':<7} source={l.get('source')}")
sys.exit(1 if fails else (print(f"{len(ran)} checks, all passed") or 0))
