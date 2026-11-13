"""Scenario test for an ask that is wrong leaving the owner's move, a dropped dependency reminding its author, and the server applying what he said (ask_leaves.py, note_read.py;
server._ask_after_write, _ask_leave, _answer). Fixture data, direct calls to the update tool and the board's answer, no live store, no network.

Covers: (2) a write while an ask stands on an item its author moves or wrote ends with a one-line reminder (not for another session, not once the ask is cleared); (3a) a write that
sets an ask shows the owner's comments and notes since the item's last ask; (3b) the author's own plain sentence, alone as the whole new text of a write of that item ("The ask is wrong.",
"My question is moot.", "This ask is no longer needed."), takes the ask off his move: the ask, its options and decision leave, the item goes back to its author, History says so, the late
answer is kept as a comment and nothing is closed or answered for him; any other new line or sentence in the write (a hedge, a label, a quote, a disagreement, another language), a reported
phrase, another session's word, a sender-less write and a watcher's ask change nothing; (3c) the record removes nothing: an ask gated on a board item (after/once/when/until it lands, waiting
for it to land, depends on it landing) that is closed as dropped after the ask was written stands, on a write and on the close of that item, with and without a stored `after`, for every
shape the earlier rounds tried; the one thing the server does is add a line to the reminder of the ask's author on his next write, naming the dropped item once; the item goes
back to the ask's author also when the owner is its stored mover and a `then` is stored; `[ask] leaves = false` in the config file turns the removal off; (4) his note "ran it" ticks the
step, a first-person future with a later time holds the item until then with his words behind the wake, while a negation, a deadline, "go ahead", a question, "run it" or a longer note
does neither; the pure readers in note_read.py and ask_leaves.py.

    tests/run-suite ask_leaves        → exit 0 / 1"""
import datetime as dt, json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="askleaves-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"


def write_toml(extra=""):
    toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                     (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml + extra, encoding="utf-8")


write_toml()
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER_S = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
OTHER = "00000000-0000-4000-8000-000000000003"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER_S: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now},
                                                     OTHER: {"name": "home-other", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-other", "agents": {"home-here": "builds it", "home-agent": "builds it too"},
                                                                                "back_agents": {"home-here": "builds it", "home-agent": "builds it too"}, "status": "active", "board": [], "board_open": 0}}}))
DESC = "- Goal: A thing\n- It lives here\n- Finished when it works"
ASK = "Decide: whether to ship the export · Recommend: yes · Stakes: none either way · By: no date"
ASK2 = "Decide: whether to ship the report · Recommend: yes · Stakes: none either way · By: no date"
OPTS = [{"label": "Ship", "line": "Ship it now as it is", "recommended": True}, {"label": "Wait", "line": "Wait for the next release", "recommended": False}]
STEP = "run the one line in a terminal"


def item(i, status="open", L="a", rec_at=None, **meta):
    if rec_at is not None and meta.get("ask"):      # the ask was written at rec_at by home-agent (its record)
        meta["ask_rec"] = {"by": "home-agent", "at": rec_at, "text": meta["ask"]}
    desc = meta.pop("description", DESC)
    (T / f"store/{L}/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": desc, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"project": "projects/alpha", "next": "home-agent: the next step", **meta}}))


for i in (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13):
    item(i, mover="home-agent")
item(2, mover="home-agent", answers=[{"ts": now - 1800, "kind": "comment", "text": "I think we should wait for the release", "via": "board"},
                                     {"ts": now - 7 * 86400, "kind": "comment", "text": "an old remark long before", "via": "board"}])
item(20, status="completed", L="g", outcome="dropped", reason="no longer wanted")
item(21, status="completed", L="g", outcome="superseded", reason="replaced")
item(22, status="completed", L="g", outcome="done", reason="finished")
item(47, status="completed", L="g", outcome="dropped", reason="no longer wanted")
item(70, status="completed", L="g", outcome="superseded", superseded_by="g71", reason="replaced")      # superseded by an open item: the question goes on there
item(71, L="g", mover="home-agent")
item(72, status="completed", L="g", outcome="superseded", superseded_by="g73", reason="replaced")      # superseded by an item that was then dropped
item(73, status="completed", L="g", outcome="dropped", reason="no longer wanted")
item(80, status="completed", L="g", outcome="superseded", superseded_by="g81", reason="replaced")      # a cycle: 80 -> 81 -> 80
item(81, status="completed", L="g", outcome="superseded", superseded_by="g80", reason="replaced")
item(82, status="completed", L="g", outcome="superseded", reason="replaced")      # superseded with no replacement named
item(83, status="completed", L="g", outcome="superseded", superseded_by="g99", reason="replaced")      # its replacement does not exist
item(84, L="g", mover="home-agent")      # reopened: open, with no outcome
item(85, L="g", mover="home-agent", outcome="dropped")      # reopened with a stale outcome left in the file
item(30, state="your-step", step=STEP, needs=["home-agent"], mover="Oliver", then="home-agent")
item(31, state="your-step", step=STEP, needs=["home-agent"], mover="Oliver", then="home-agent")
item(32, state="your-step", step=STEP, needs=["home-agent"], mover="Oliver", then="home-agent")
item(33, state="your-step", step=STEP, needs=["home-agent"], mover="Oliver", then="home-agent")
item(34, state="your-step", step=STEP, needs=["home-agent"], mover="Oliver", then="home-agent")
for i in (50, 51, 52, 53, 54, 55, 56, 60, 61, 62, 63, 64, 65, 66):      # items for the later sections; written here so the store is complete before the first commit
    item(i, mover="home-agent")
(T / "store/next-id").write_text("90"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
X = lambda t: t.replace("{B}", "board" + "#")      # an item id as a session writes it, spelled apart so the file holds no literal id
logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def rd(i, L="a"): return json.loads((T / f"store/{L}/{i}.json").read_text())


from stackshot.service import gates; from stackshot.web import server; from stackshot.service import runner as runner_svc; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.web.tools import complete as _wt_complete; from stackshot.web.tools import text as _wt_text; from stackshot.web.tools import update as _wt_update; from stackshot.model import ask_leaves as AL; from stackshot.model import note_read as NR; from stackshot.waits import watchers; from stackshot.model import needs as _model_needs
from stackshot.service import telling
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((gid, owner, note, tag))
D = lambda t: f"- Goal: {t}\n- It lives here\n- Finished when it works"
DW = lambda t: DESC + f"\n- {t}"      # the author's own sentence as a new bullet of its own, the only new line of the description
upd = lambda i, **kw: _wt_update.stackshot_update(i, **{"sender": "home-agent", **kw})
history = lambda i: [str(x.get("text") if isinstance(x, dict) else x) for x in (rd(i)["metadata"].get("stall") or {}).get("log", [])]
stood = lambda i: bool(rd(i)["metadata"].get("ask")) and "decision" in _model_needs._needs_kinds(rd(i)["metadata"])

check("the fixture: the owner is Oliver", server.OWNER == "Oliver")

# ---- 0. the pure readers
S = AL.author_says_wrong
PLAIN = ("The ask is wrong.", "My question is moot.", "This ask is no longer needed.", "- The ask is wrong.", "- My question is moot.", "- This ask is no longer needed.", "the ask is wrong", "this ask is no longer needed",
         "The ask is stale", "the ask is void", "The ask is obsolete", "the ask is no longer valid", "My question is moot now", "This question is stale anymore", "This ask is moot")
check("author_says_wrong: the three plain sentences, alone or as one bullet, count (and the shorter variants)", all(S([t]) for t in PLAIN), [t for t in PLAIN if not S([t])])
check("author_says_wrong: the NEW text of the whole write is read: blank lines and empty texts around the sentence change nothing", bool(S(["The ask is wrong.", "", "  "]) and S(["", "- My question is moot.\n"]) and S(["The ask is wrong.\n\n"])))
HEDGED_CORE = ("the ask is wrong, rewrite it", "My question is moot after the merge", "the ask has become obsolete", "My question is now moot", "The question is stale now", "The question is stale", "The ask is wrong?",
               "Probably the ask is moot", "It seems the ask is moot", "Looks like the ask is moot", "Likely the ask is moot", "Most likely the ask is moot", "Apparently the ask is moot", "Possibly the ask is moot",
               "Presumably the ask is moot", "Hopefully the ask is moot", "Pretty sure the ask is moot", "Chances are the ask is moot", "The ask is moot for now", "The ask is moot today", "The ask is moot this week",
               "The ask is moot assuming the vendor stays", "The ask is wrong, the date is Friday", "The ask is wrong in one detail only: the price", "The ask is wrong, Oliver, please confirm",
               "The ask is stale. Oliver still needs to choose.", "The ask is wrong. Oliver, please confirm", "the ask is wrong, I'll fix the date.", "Pat: the ask is wrong")
REPORTED = ("Pat says: the ask is wrong", "Pat replied: the ask is wrong", 'Pat wrote "the ask is wrong"', 'Pat: "the ask is wrong"', "Pat: the ask is wrong", "Lee commented that the ask is wrong",
            "Pat answered that the ask is wrong", "Pat flagged the ask is wrong", "The reviewer pointed out that the ask is wrong", "Per Pat, the ask is wrong", "> the ask is wrong",
            "line one\n> the ask is wrong", "Lee noted the ask is wrong", "Pat said: 'the question is moot'", "Pat says the ask is wrong", "Pat said the question is moot", "Sam thinks that the ask is stale", "according to Pat the ask is wrong")
ABOUT = ("the question is wrong for the vendor, not for him", "this ask is stale in the vendor's inbox", "the ask is moot for the team")
MORE_BEFORE = ("The ask may be wrong", "I doubt the ask is wrong", "I suppose the ask is wrong", "Assuming the ask is wrong, we rewrite it", "In case the ask is wrong, ping Pat", "Although the question is moot, keep it",
               "Even though the ask is wrong, ship", "It is unlikely the ask is wrong", "There is no evidence the ask is wrong", "Nobody has shown the question is moot")
MORE_AFTER = ("The ask is probably wrong", "The ask is wrong, I think", "The ask is wrong, I am not sure", "My question is moot as long as Pat agrees", "The ask is wrong per Pat", "The ask is wrong - Lee differs",
              "The ask is possibly moot", "The question is wrong, otherwise Pat would have replied", "I guess the ask is wrong", "The ask is wrong, I suppose")
MORE_LABELS = ("Slack from Pat: the ask is wrong", "Email from the vendor: the ask is wrong", "Pat in Slack - the ask is wrong", "As Pat put it, the ask is wrong", "Message from Lee Kim: the ask is wrong",
               "Pat in the thread: the ask is wrong", "As Lee said, the ask is wrong")
AFTER_HEDGED = ("The ask is moot unless Pat replies", "The ask is moot if Pat replies", "the ask is wrong; Lee disagrees", "The ask is wrong, but only because the date moved", "my question is moot until Friday",
                "the ask is wrong when read literally", "the ask is wrong, however Lee wants it kept", "the question is moot, although Pat may object", "the ask is stale provided the vendor agrees",
                "the ask is moot, depending on the answer", "the ask is wrong once the vendor replies", "the ask is wrong pending Lee's review")
SOURCES = ("Pat's note: the ask is wrong", "Lee's email: the ask is wrong", "Lee's email - the ask is wrong", "Reviewer feedback: the ask is wrong", "Customer reply: the ask is wrong", "From Pat - the ask is wrong",
           "From Pat: the ask is wrong", "Pat (the vendor): the ask is wrong", "- Lee's note: the ask is wrong", "Pat's first reply: the ask is wrong")
PLAINTEXT = ("if the ask is wrong, say so", "the ask is not wrong", "check whether the ask is moot", "might be that the question is stale", "the ask is about the wrong export", "ship the export", "",
             "asked the wrong question of the vendor", "the stale ask is still showing", "I considered withdrawing the ask but kept it", "withdrawing the ask", "I withdrew the ask", "the ask was wrong, so I replaced it",
             "my question was moot after the merge", "a wrong ask would be worse", "the moot ask stays until Friday", "the ask is wrong-headed", "the ask is wrong (the date), the decision stands")
LABELS = ("Note: the ask is wrong", "Update: the ask is wrong", "- Status: the ask is wrong", "My note: the ask is wrong", "Todo: the ask is wrong", "Fix: the ask is wrong", "Decision: the ask is wrong",
          "Pat's review: the ask is wrong", "Reviewer feedback: the ask is wrong", "infra-reviewer: the ask is wrong", "home-agent: the ask is wrong", "Note: The ask is wrong.", "> The ask is wrong.", "- - The ask is wrong.",
          "-- The ask is wrong.", "* The ask is wrong.", "1. The ask is wrong.", "(The ask is wrong.)", '"The ask is wrong."', "The ask is wrong!", "The ask is wrong..", "The ask is wrong.  Thanks.",
          "Check the logs. The ask is wrong.", "Done with the export. My question is moot.", "Thanks. The ask is wrong", "The ask is wrong. Slack is down.", "The ask is wrong. Pat disagrees about the date.")
NOT_WORD = HEDGED_CORE + REPORTED + ABOUT + MORE_BEFORE + MORE_AFTER + MORE_LABELS + AFTER_HEDGED + SOURCES + PLAINTEXT + LABELS
check("author_says_wrong: the grammar is closed: a hedge, a clause, a question, a name and a colon, a label (Note:, Todo:, Fix:, Decision:, Pat's review:, Reviewer feedback:, infra-reviewer:), a quote, a double bullet, "
      "reported speech, a second sentence or another language is no word (%d inputs)" % len(NOT_WORD), not [t for t in NOT_WORD if S([t])], [t for t in NOT_WORD if S([t])])
REPAIR_NEXT = ("fix the date", "Fixing the date", "I will redo it", "rewriting it", "Replace it with the second", "Correct the number", "Refresh it", "The decision stands", "It is still open", "But the date moved", "However Pat differs",
               "Though Pat differs", "Unless Pat replies", "Please confirm", "Confirm with Pat", "Oliver needs to choose", "Wait for Pat", "Waiting for the vendor", "Oliver to choose")
EXTRAS = REPAIR_NEXT + ("I disagree", "The ask is right", "I might be wrong", "Not yet", "Maybe", "Keep it", "Retract", "Re-ask", "\ud558\uc9c0\ub9cc \uc5ec\uc804\ud788 \ud544\uc694\ud569\ub2c8\ub2e4", "Pat to decide", "Note: see the thread", "Todo: ping Pat",
                        "Fix: the date", "Decision: keep", "Pat's review: fine", "Reviewer feedback: none", "infra-reviewer: ok", "> a quote", "Thanks.", "Check the logs.", "Done with the export.", "I replied to Pat.")
around = lambda t, e: ([f"{t} {e}"], [f"{t}\n{e}"], [f"{e} {t}"], [f"{e}\n{t}"], [t, e], [e, t])      # the same words on one line, on the next line, before it, and as a second text of the write
EXTRA_BAD = [(t, e) for t in ("The ask is wrong.", "- My question is moot.", "This ask is no longer needed.") for e in EXTRAS for w in around(t, e) if S(w)]
check("author_says_wrong: any other new sentence or line in the write (%d: a disagreement, a hedge, 'Not yet', 'Maybe', 'Keep it', 'Retract', 'Re-ask', Korean, 'Pat to decide', a label, a quote), before or after, on the same line, the next line "
      "or in another text, means no word" % len(EXTRAS), not EXTRA_BAD, EXTRA_BAD[:5])
check("new_lines: a line the item already held is not new (whatever its bullet or case), a new one is",
      AL.new_lines(["- Goal: the ask is wrong\nnew line", "x"], "old\ngoal: the ask is wrong\n") == ["new line", "x"], AL.new_lines(["- Goal: the ask is wrong\nnew line"], "old\ngoal: the ask is wrong\n"))
check("author_says_wrong: a line re-sent from before is not new, so the sentence it holds is not his word again", not S(AL.new_lines(["The ask is wrong."], "old\n- The ask is wrong.\n")) and S(AL.new_lines(["The ask is wrong."], "old\n")))
# (round 11) a hedge is held only as a WHOLE old line; as a part of a longer old line it is new text
HEDGES = ("Not yet", "Maybe", "No", "Wait", "Keep it", "Keep", "I disagree")
INSIDE = lambda h: (f"- Status: migration is {h.lower()} done", f"- Pat answered: {h}, later", f"{h} later today", f"x {h.lower()}", f"- Note: {h.lower()}, said Pat")
STAND_OLD = [(h, o) for h in HEDGES for o in INSIDE(h) if S(AL.new_lines([o + "\n- The ask is wrong.\n- " + h], o)) or S(AL.new_lines([o + "\n- The ask is wrong.\n" + h], o))]
check("new_lines: a hedge that is only a PART of a longer old line (%d forms) is new text, so the sentence beside it is not the whole new text and the ask stands" % (len(HEDGES) * 5), not STAND_OLD, STAND_OLD[:5])
check("new_lines: the old blob 'Status: migration is not yet done' re-sent with the sentence and a new 'Not yet' line returns both new lines",
      AL.new_lines(["- Status: migration is not yet done\n- The ask is wrong.\n- Not yet"], "- Status: migration is not yet done") == ["- The ask is wrong.", "- Not yet"],
      AL.new_lines(["- Status: migration is not yet done\n- The ask is wrong.\n- Not yet"], "- Status: migration is not yet done"))
WHOLE_OLD = [h for h in HEDGES if AL.new_lines([f"- {h}\n- The ask is wrong."], f"- Goal: x\n- {h}\n") != ["- The ask is wrong."] or not S(AL.new_lines([f"- {h}\n- The ask is wrong."], f"- Goal: x\n- {h}\n"))]
check("new_lines: a hedge that is a WHOLE old line, re-sent unchanged (any bullet or case), is not new: the sentence alone is the new text", not WHOLE_OLD
      and AL.new_lines(["not yet\n* THE ASK IS WRONG."], "- Not yet\n") == ["* THE ASK IS WRONG."], WHOLE_OLD)
check("text_leaves: a string, a mapping, a list and nested values give each string inside once, in order; numbers and None give none",
      AL.text_leaves("a") == ["a"] and AL.text_leaves({"x": "a", "y": ["b", {"z": "c"}], "n": 3, "m": None}) == ["a", "b", "c"] and AL.text_leaves(None) == [] and AL.text_leaves(7) == [] and AL.text_leaves({1: "q"}) == ["q"])

# the dependency reader and the dropped-dependency clause (a reminder only): the lookup gives (status, outcome, closed at); the ask was written at 100
LK = lambda table: (lambda n: table.get(n))
AFTER, BEFORE = 200.0, 50.0
DROPPED = lambda n: ("completed", "dropped", AFTER)
GATED = ("Decide: ship after {B}20 lands", "Decide: ship once {B}20 lands", "Decide: ship once {B}20 is merged", "Decide: ship once {B}20 is released", "Decide: approve the export when {B}20 is live",
         "Decide: approve the export until {B}20 completes", "Decide: approve the export once {B}20 ships", "Decide: approve the export after {B}20 is ready", "Decide: approve the export following {B}20 is merged",
         "Decide: approve the export waiting for {B}20 to land", "Decide: approve the export waiting on {B}20 to merge", "Decide: approve the export waits for {B}20 to finish",
         "Decide: approve the export depends on {B}20 landing", "Decide: approve the export depends on {B}20 merging", "Decide: approve the export until {B}20 is merged", "Decide: approve the export when {B}20 is done",
         "Decide: approve the export when {B}20 is completed", "Decide: approve the export when {B}20 is shipped", "Decide: approve the export after {B}20 and {B}21 land", "Approve the export after {B}20 lands.",
         "Decide: ship {B}8 once {B}20 lands", "Decide: Sign the contract when {B}20 is released.", "Decide: please approve the export after {B}20 lands", "Decide: ok to merge the fix once {B}20 lands",
         "Decide: go ahead with the plan after {B}20 lands", "Once {B}20 lands, approve the export", "Decide: once {B}20 lands, approve the export")
check("depends_on: after|once|when|until|following <id> lands|is merged|is live|is done..., waiting for <id> to land, depends on <id> landing name the item (%d forms)" % len(GATED), all("20" in AL.depends_on(X(t)) for t in GATED),
      [t for t in GATED if "20" not in AL.depends_on(X(t))])
BARE = ("Decide: whether to revive {B}20 (dropped in Oct) as a smaller export", "Decide: whether to revive {B}20 as a smaller export", "Decide: x, as {B}20 did", "Decide: x when {B}20 gets reviewed", "Decide: x, see {B}20 and {B}21",
        "Decide: x pending {B}20", "Decide: x, which hinges on {B}20", "Decide: x, dependent on {B}20", "Decide: x after item-20", "Decide: ship after {B}20", "Decide: x, waits on {B}20", "Decide: x, waiting for {B}20",
        "Decide: x, depends on {B}20", "Decide: x, blocked by {B}20", "Decide: x, blocked on {B}20", "Decide: x with the schema of {B}20")
TRIGGER = ("Decide: delete staging data when {B}20 is closed", "Decide: whether to revive {B}21 after {B}20 is dropped", "Decide: x once {B}20 is dropped", "Decide: x after {B}20 fails", "Decide: x after {B}20 failed",
           "Decide: x after {B}20 was cancelled", "Decide: x after {B}20 is canceled", "Decide: x after {B}20 gets dropped", "Decide: x until {B}20 is abandoned", "Decide: x after {B}20 was dropped or superseded",
           "Decide: x once {B}20 lands or is dropped")
check("depends_on: a bare citation, a bare 'after|waits on|depends on|blocked by <id>', a looser phrase, 'closed' and a drop as the trigger name no dependency", not [t for t in BARE + TRIGGER if t != "Decide: x once {B}20 lands or is dropped" and AL.depends_on(X(t))],
      [t for t in BARE + TRIGGER if AL.depends_on(X(t))])
check("dropped_deps: the items the ask waits on that were closed as dropped AFTER the ask was written, each once, in the ask's order",
      [d[0] for d in AL.dropped_deps(X("Decide: approve the export after {B}20 and {B}21 land, once {B}20 is done"), LK({"20": ("completed", "dropped", AFTER), "21": ("completed", "dropped", AFTER)}), 100.0)] == ["20", "21"]
      and [d[0] for d in AL.dropped_deps(X("Decide: approve the export after {B}20 and {B}22 land"), LK({"20": ("completed", "dropped", AFTER), "22": ("completed", "done", AFTER)}), 100.0)] == ["20"])
check("dropped_deps: done, superseded, open, unreadable and closed-BEFORE-the-ask items are left out, and with no ask time nothing is found",
      not AL.dropped_deps(X("Decide: ship once {B}20 lands"), lambda n: ("completed", "done", AFTER), 100.0) and not AL.dropped_deps(X("Decide: ship once {B}20 lands"), lambda n: ("completed", "superseded", AFTER), 100.0)
      and not AL.dropped_deps(X("Decide: ship once {B}20 lands"), lambda n: ("open", "", 0), 100.0) and not AL.dropped_deps(X("Decide: ship once {B}20 lands"), lambda n: None, 100.0)
      and not AL.dropped_deps(X("Decide: ship once {B}20 lands"), lambda n: ("completed", "dropped", BEFORE), 100.0) and not AL.dropped_deps(X("Decide: ship once {B}20 lands"), DROPPED)
      and not AL.dropped_deps("Decide: no ids", DROPPED, 100.0))
found = AL.dropped_deps(X("Decide: approve the export after {B}20 lands"), lambda n: ("completed", "dropped", AFTER, "superseded by X, which was dropped"), 100.0)
line = AL.dropped_line(found, lambda ts: "Thu Nov 5th")
check("dropped_line: names each dropped item once with the date and says to withdraw the ask if it is moot, otherwise it stands; nothing found, no line",
      line.count(X("{B}20, which this ask waits on, was superseded by X, which was dropped on Thu Nov 5th")) == 1 and line.endswith("; if the ask is moot withdraw it now (clear_ask=true), otherwise it stands")
      and AL.dropped_line([], str) == "", line)
rem = AL.reminder("a1", "Oliver", "", line)
check("reminder: the one line, with the dropped-dependency clause inside it once, and without a clause as before",
      rem.startswith("\n(reminder: an ask stands on a1 for Oliver") and rem.count("which this ask waits on") == 1 and rem.endswith(")") and "which this ask waits on" not in AL.reminder("a1", "Oliver", ""), rem)

nz = dt.datetime(2026, 11, 7, 15, 0, tzinfo=dt.timezone.utc)
pd = lambda t, today: watchers.parse_date(t, today)
check("note_read: done phrases", all(NR.read(t, nz, pd) == {"done": True, "until": ""} for t in ("ran it", "Done", "I did it already", "ok, I've run it", "it's done", "I have run it")),
      [NR.read(t, nz, pd) for t in ("ran it", "Done", "I did it already", "I have run it")])
check("note_read: a stray span in a note keeps the older readers' day (tomorrow, next week, a weekday), the table of relative phrases is not consulted",
      [NR.read(t, nz, pd)["until"] for t in ("I'll look at it next week, it is a month-end task", "I'll do it on Friday, it takes a day", "I will do it tomorrow, took two weeks to get here")]
      == ["2026-11-14T09:00", "2026-11-13T09:00", "2026-11-08T09:00"], [NR.read(t, nz, pd) for t in ("I'll look at it next week, it is a month-end task", "I'll do it on Friday, it takes a day")])
check("note_read: 'run it' is a request, not a tick",
      not any(NR.read(t, nz, pd)["done"] for t in ("run it", "Run it now", "run them", "run")), [NR.read(t, nz, pd) for t in ("run it", "Run it now")])
check("note_read: not done when it asks, negates or says more",
      not any(NR.read(t, nz, pd)["done"] for t in ("did it work?", "didn't run it", "ran it but it says forbidden", "")), None)
check("note_read: 'I ran it and will check tomorrow' ticks the step and holds nothing",
      all(NR.read(t, nz, pd) == {"done": True, "until": ""} for t in ("I ran it and will check tomorrow", "ran it, will look tomorrow evening")), NR.read("I ran it and will check tomorrow", nz, pd))
u1, u2 = NR.read("I'll do it tomorrow evening", nz, pd)["until"], NR.read("I'm going to do it in 3 days", nz, pd)["until"]
u3, u4 = NR.read("I will do this next week", nz, pd)["until"], NR.read("I'll look at it tonight", nz, pd)["until"]
check("note_read: a first-person future with a later time", u1 == "2026-11-08T19:00" and u2.startswith("2026-11-10") and u3 and u4 == "2026-11-07T21:00", (u1, u2, u3, u4))
check("note_read: no time for a question, a past time, a long message or no cue",
      not any(NR.read(t, nz, pd)["until"] for t in ("can I do it tomorrow evening?", "I ran it yesterday evening", "looks fine", "I will do it " + "x" * 300 + " tomorrow")), None)
check("note_read: no time for a note that is not a first-person future (a bare time, a request, someone else)",
      not any(NR.read(t, nz, pd)["until"] for t in ("tomorrow evening", "in 3 days", "next week", "please do it tomorrow evening", "Pat will do it tomorrow evening", "do it tomorrow evening")),
      [NR.read(t, nz, pd) for t in ("tomorrow evening", "Pat will do it tomorrow evening")])
check("note_read: no time for a negation",
      not any(NR.read(t, nz, pd)["until"] for t in ("not tomorrow", "I will not do it tomorrow evening", "I can't do it tomorrow", "I cannot do it tomorrow evening", "I won't get to it tomorrow",
                                                  "I'll do it next week, not tomorrow", "I'll never do it tomorrow")), None)
check("note_read: no time when the step is done now, or the note is no action of the step",
      not any(NR.read(t, nz, pd)["until"] for t in ("I'll do it now, then check tomorrow", "I'm going to do it now and report tomorrow", "I'll do it today and check next week", "I'll let you know tomorrow",
                                                  "I'll be traveling tomorrow", "I will be away next week", "I'm out of office tomorrow, I'll do it then")),
      [NR.read(t, nz, pd) for t in ("I'll do it now, then check tomorrow", "I'll let you know tomorrow", "I'll be traveling tomorrow")])
check("note_read: no time for a deadline, 'go ahead' or a condition",
      not any(NR.read(t, nz, pd)["until"] for t in ("by tomorrow evening", "I need this by next week", "I'll do it by tomorrow evening", "I will finish before next week", "go ahead until tomorrow evening",
                                                  "go ahead, I'll wait until tomorrow evening", "I'll go ahead and do it tomorrow", "if I can, I'll do it tomorrow", "maybe I'll do it next week")), None)

# ---- 1. the reminder (part 2)
r = upd("a1", ask=ASK, needs=["decision"], options=OPTS)
check("setting an ask records who wrote it (metadata.ask_rec) and adds no reminder to the write that sets it", rd(1)["metadata"].get("ask_rec", {}).get("by") == "home-agent" and "reminder" not in r, r)
r = upd("a1", priority="p2")
check("a write by the ask's author while the ask stands ends with the one-line reminder", "(reminder: an ask stands on a1 for Oliver" in r and "clear_ask=true" in r and r.count("reminder") == 1, r)
r = upd("a1", priority="p3", sender="home-other")
check("another session's write gets no reminder (it neither wrote the ask nor moves the item)", "reminder" not in r, r)
r = upd("a1", clear_ask=True, needs=["home-agent"])
check("a write that clears the ask adds no reminder and leaves nothing standing", "reminder" not in r and not stood(1) and "ask_rec" not in rd(1)["metadata"], r)

# ---- 2. the ask-time check (part 3a)
r = upd("a2", ask=ASK, needs=["decision"], options=OPTS)
ck = r[r.find("(check:"):] if "(check:" in r else ""
check("setting an ask shows the owner's comment since the item's last ask (the older remark, before the look-back, is not shown)", "(check: Oliver has written on this item" in ck and "wait for the release" in ck and "old remark" not in ck, r)
check("the check line says what to do with a note that answers the ask", "update(clear_ask=true)" in r, r)

# ---- 3. the author says the ask is wrong (part 3b): his own plain sentence, alone in the write
upd("a3", ask=ASK, needs=["decision"], options=OPTS); told.clear()
r = upd("a3", description=DW("The ask is wrong."))
m = rd(3)["metadata"]
check("the author's plain sentence takes the ask off his move: ask, options, decision and the stored your-call are gone", not stood(3) and "ask" not in m and "options" not in m and "decision" not in _model_needs._needs_kinds(m), m)
check("the item goes back to its author and stays open; the server closed nothing", m.get("mover") == "home-agent" and rd(3)["status"] == "open" and rd(3).get("outcome") is None, m)
check("History says what the server did and why; the reply says so; the ask and options are kept in ask_left",
      any("ask taken off Oliver's move by the server" in h and "its author said so" in h for h in history(3)) and "the server took the ask off Oliver's move" in r
      and m.get("ask_left", {}).get("ask") == ASK and m["ask_left"].get("options") and m["ask_left"].get("how") == "word", (history(3), r, m.get("ask_left")))
check("the write's own description is kept as written (the server altered no words)", "The ask is wrong." in rd(3)["description"], rd(3)["description"])
before_answers = len(m.get("answers") or [])
res = server._answer("a3", "Ship", "", "answer")
m = rd(3)["metadata"]
check("his late option click is kept as a comment, applies nothing and is not stale-refused",
      res == "comment" and len(m.get("answers", [])) == before_answers + 1 and m["answers"][-1]["kind"] == "comment" and "late" in m["answers"][-1]["text"] and "Ship" in m["answers"][-1]["text"]
      and rd(3)["status"] == "open" and not stood(3), (res, m.get("answers")))
res = server._answer("a3", "", "actually ship it", "answer")
check("his late note is a comment too (a stale tab's Send as an answer)", res == "comment" and rd(3)["metadata"]["answers"][-1]["kind"] == "comment", res)

# the same on the three plain sentences, the bullet in next, and a step; everything around the sentence leaves the ask standing
for k, t in zip((701, 702, 703), ("My question is moot.", "This ask is no longer needed.", "The ask is stale")):
    item(k, mover="home-agent"); upd(f"a{k}", ask=ASK, needs=["decision"], options=OPTS)
    r = upd(f"a{k}", description=DW(t))
    check(f"the plain sentence {t!r} alone in a description write takes the ask off", not stood(k) and "took the ask off" in r, r)
item(704, mover="home-agent"); upd("a704", ask=ASK, needs=["decision"], options=OPTS)
r = upd("a704", next="home-agent: the next step\n- The ask is wrong.")
check("a bullet of its own under the named step in next is the whole new text: it takes the ask off", not stood(704) and "took the ask off" in r, r)
item(705, mover="home-agent"); upd("a705", ask=ASK, needs=["decision"], options=OPTS)
r = upd("a705", description=DESC + "\n- The ask is wrong.\n- I disagree")
check("a second new line beside the sentence (a disagreement) leaves the ask standing", stood(705) and "took the ask off" not in r, r)
item(706, mover="home-agent"); upd("a706", ask=ASK, needs=["decision"], options=OPTS)
r = upd("a706", description=DESC + "\n- The ask is wrong.\n- \ud558\uc9c0\ub9cc \uc5ec\uc804\ud788 \ud544\uc694\ud569\ub2c8\ub2e4")
check("... the same in Korean", stood(706) and "took the ask off" not in r, r)
item(707, mover="home-agent"); upd("a707", ask=ASK, needs=["decision"], options=OPTS)
r = upd("a707", description=DW("The ask is wrong."), next="home-agent: the next step\nhome-agent: also wait")
check("the sentence in the description beside a new line in next is not the whole new text of the write: the ask stands", stood(707) and "took the ask off" not in r, r)
item(708, mover="home-agent"); upd("a708", ask=ASK, needs=["decision"], options=OPTS)
r = upd("a708", description=DW("Note: The ask is wrong."))
check("a label before the sentence (Note:) leaves the ask standing", stood(708) and "took the ask off" not in r, r)

# a hedged phrase, another session's word and a watcher's ask change nothing
upd("a4", ask=ASK, needs=["decision"])
r = upd("a4", description=DW("check whether the ask is wrong before he sees it"))
check("a hedged phrase takes nothing off", stood(4) and "took the ask off" not in r, r)
r = upd("a4", description=DW("The ask is wrong."), sender="home-other")
check("another session's word that the ask is wrong takes nothing off (the server acts on the author's own word)", stood(4) and "took the ask off" not in r, r)
r = upd("a4", description=DW("The ask is not wrong"))
check("a negated phrase in the author's write takes nothing off", stood(4), r)
r = upd("a4", description=DW("withdrawing the ask"))
check("'withdrawing the ask' is no word (a gerund, not a statement of the ask's state)", stood(4) and "took the ask off" not in r, r)
r = upd("a4", description=DW("Pat says the ask is wrong"))
check("a reported phrase in the author's write takes nothing off", stood(4) and "took the ask off" not in r, r)
r = upd("a4", description=DW("the ask was wrong, so I replaced it"))
check("a past-tense phrase takes nothing off", stood(4) and "took the ask off" not in r, r)
r = upd("a4", description=DESC + "\n- Check the logs.\n- The ask is wrong.")
check("(flipped in round 10) the sentence after another new line is not the whole new text: the ask stands", stood(4) and "took the ask off" not in r, r)

# the author's word counts in the item's mover when the ask has no record
item(14, mover="home-agent", needs=["decision"], ask=ASK)       # an ask stored before the record: no ask_rec
r = upd("a14", description=DW("My question is moot"))
check("an ask stored before the record has no author on file: the item's mover counts as its author", not stood(14) and "took the ask off" in r, r)
item(15, mover="home-other", needs=["decision"], ask=ASK)       # not the author's item and no record: another session's word is nothing
r = upd("a15", description=DW("The ask is wrong"), sender="home-agent")
check("a session that neither moves the item nor wrote the ask cannot take it off", stood(15) and "took the ask off" not in r, r)

# a stale line re-sent with a later write is not the author's word again (next, and description)
item(60, mover="home-agent")
upd("a60", ask=ASK, needs=["decision"], options=OPTS)
LINES = "home-agent: the next step\n- The ask is wrong."
r = upd("a60", next=LINES)
check("a new bullet 'The ask is wrong.' in next takes the ask off", not stood(60) and "took the ask off" in r, r)
upd("a60", ask=ASK2, needs=["decision"], options=OPTS)
check("a new ask on the item stands", stood(60))
r = upd("a60", priority="p2", next=LINES)
check("the same next lines re-sent with a later write do not take the NEW ask off", stood(60) and rd(60)["metadata"].get("ask") == ASK2 and "took the ask off" not in r, r)
r = upd("a60", priority="p3", next=LINES + "\nhome-agent: also wait")
check("... and a new line beside them that does not say it changes nothing either", stood(60) and "took the ask off" not in r, r)
r = upd("a60", priority="p2", next=LINES + "\nhome-agent: also wait\n- The ask is moot.")
check("... while a new line that alone says it does take the new ask off", not stood(60) and "took the ask off" in r, r)
item(61, mover="home-agent")
upd("a61", ask=ASK, needs=["decision"], options=OPTS)
r = upd("a61", description=DW("The ask is wrong."))
check("a new description line 'The ask is wrong.' takes the ask off", not stood(61) and "took the ask off" in r, r)
upd("a61", ask=ASK2, needs=["decision"], options=OPTS)
r = upd("a61", priority="p2", description=DW("The ask is wrong."))
check("the same description re-sent with a later write does not take the NEW ask off", stood(61) and "took the ask off" not in r, r)
# a write with no sender is nobody's own word: it takes nothing off (the update tool refuses an empty sender; the tail itself is checked here)
item(50, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK})
r = server._ask_after_write(gates.ask_pre("a50"), "", "", False, ["the ask is wrong"])
check("a sender-less write never takes the ask off, though its text says the ask is wrong, and gets no reminder", stood(50) and r == "", r)
check("the same words from the ask's author do", "took the ask off" in server._ask_after_write(gates.ask_pre("a50"), "home-agent", "", False, ["the ask is wrong"]) and not stood(50))

# the real shape: the owner is the stored mover while a decision stands, and a `then` is stored; the item goes back to the ask's author
item(51, mover="Oliver", then="home-agent", needs=["decision"], ask=ASK, state="your-call", ask_rec={"by": "home-agent", "at": now - 600, "text": ASK})
r = upd("a51", description=DW("The ask is wrong"))
m = rd(51)["metadata"]
check("owner as stored mover and a stored then (the author): the ask is off, the item is back with the author, and the stored then is not left behind",
      not stood(51) and m.get("mover") == "home-agent" and "then" not in m and "your-call" not in str(m.get("state")) and rd(51)["status"] == "open" and "took the ask off" in r, (m, r))
item(52, mover="Oliver", then="home-other", needs=["decision"], ask=ASK, state="your-call", ask_rec={"by": "home-agent", "at": now - 600, "text": ASK})
r = upd("a52", description=DW("The ask is wrong"))
m = rd(52)["metadata"]
check("owner as stored mover and another session stored as then: the item still goes back to the ask's author, not to the stored then", m.get("mover") == "home-agent" and "then" not in m, m)
item(53, mover="Oliver", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK})
r = upd("a53", description=DW("The ask is wrong"))
m = rd(53)["metadata"]
check("owner as stored mover and no then stored: the author takes the item back, the owner is not left as its mover", m.get("mover") == "home-agent" and "then" not in m and not stood(53), m)

# a new ask, or his answer, drops the record of the ask taken off (a late pick on the old one reads stale)
check("the ask taken off is kept as ask_left", rd(51)["metadata"].get("ask_left", {}).get("ask") == ASK)
upd("a51", ask=ASK2, needs=["decision"], options=OPTS)
check("a new ask drops ask_left", "ask_left" not in rd(51)["metadata"] and stood(51), rd(51)["metadata"])
upd("a52", ask=ASK2, needs=["decision"], options=OPTS)
res = server._answer("a52", "Ship", "", "answer")
check("his answer to the new ask is applied (a decision) and leaves no ask_left", res != "stale" and "ask_left" not in rd(52)["metadata"] and rd(52)["metadata"]["answers"][-1]["kind"] == "decision", (res, rd(52)["metadata"].get("answers")))
res = server._answer("a52", "Wait", "", "answer")
check("a pick on an ask that is gone and was not taken off by the server reads stale", res == "stale", res)

# ---- 4. a dependency dropped: the ask STANDS and its author is reminded (the server removes nothing on the record)
SEP = ' · Stakes: none · By: no date'
ALTS = ("Keep item 8 once {B}20 lands, or drop it?", "Once {B}20 lands - should we ship it?", "Waiting for {B}20 to land, or should we switch to item 7?", "Wait for {B}20 to land or cancel it?", "Ship item 7 until {B}20 completes, still worth it",
        "Keep item 8, waiting on {B}20 to land, or drop it", "Ship item 7 once {B}20 lands, or ship it without", "Item 8 waits for {B}20 to land; ship it instead", "Ship item 7 after {B}20 lands, still worth it", "Wait for {B}20 to land, otherwise cancel")
WHETHER_VERBS = ("drop", "cancel", "close", "abandon", "retire", "delete", "revive", "re-plan", "replan", "rescope", "remove", "defer", "postpone", "park", "pause", "split", "merge", "reopen", "also drop")
WHETHER = [f"Decide: whether to {v} the export once {{B}}20 lands" + " · Recommend: yes" + SEP for v in WHETHER_VERBS]
WHETHER += ["Decide: whether to drop {B}8 once {B}20 lands · Recommend: yes" + SEP, "Decide: whether to cancel {B}8 after {B}20 is merged · Recommend: yes" + SEP, "Decide: whether to close {B}8 when {B}20 is done · Recommend: yes" + SEP]
STAKES = ("legal is still reviewing it", "see https://x.io/a?id=3", "otherwise nothing changes", "ship it instead of waiting", "should we worry? no", "whether to drop it later, no", "it waits on {B}20")
STK = [f"Decide: approve the export once {{B}}20 lands · Recommend: approve · Stakes: {w} · By: no date" for w in STAKES]
IN_DECIDE = ("Decide: whether to approve the export once {B}20 lands, or instead wait · Recommend: approve" + SEP, "Decide: approve the export once {B}20 lands, still · Recommend: approve" + SEP,
             "Decide: approve the export once {B}20 lands? · Recommend: approve" + SEP, "Decide: approve the export once {B}20 lands, otherwise cancel · Recommend: approve" + SEP)
IN_RECOMMEND = ("drop it instead", "ship it, or wait", "cancel it otherwise", "wait and see, should we", "ship without it", "keep it, it comes back")
REC = [f"Decide: approve the export once {{B}}20 lands · Recommend: {w}" + SEP for w in IN_RECOMMEND]
FINDING1 = ("Decide: keep {B}8 · Recommend: drop it instead · Stakes: it waits on {B}20 · By: no date", "Decide: keep {B}8 · Recommend: drop it instead · Stakes: it waits for {B}20 to land · By: no date",
            "Decide: keep the export once {B}20 lands · Recommend: drop it instead" + SEP)
FINDING2 = ("Decide: drop {B}8, which waits on {B}20 · Recommend: drop" + SEP, "Decide: what to do with {B}8, which waits on {B}20 · Recommend: Drop it" + SEP,
            "Decide: how to handle {B}8 now that it waits on {B}20 · Recommend: drop" + SEP, "Decide: approve closing {B}8, which depends on {B}20 · Recommend: yes" + SEP,
            "Decide: drop {B}8, which waits for {B}20 to land · Recommend: drop" + SEP, "Decide: drop {B}8 (blocked until {B}20 lands) · Recommend: drop" + SEP,
            "Decide: drop {B}8, which waits until {B}20 lands · Recommend: drop" + SEP, "Decide: close {B}8, since it depends on {B}20 landing · Recommend: close" + SEP,
            "Decide: close {B}8 waits for {B}20 to land · Recommend: close" + SEP)
H1_ASKS = ("Decide: whether to ship the fix now · Recommend: ship now, don't wait for {B}20 to land · Stakes: a day's delay · By: no date", "Decide: renew, not waiting for {B}20 to land · Recommend: yes" + SEP,
           "Decide: renew the contract · Recommend: yes, no need to wait for {B}20 to land" + SEP, "Decide: approve the plan · Recommend: approve; start now and do not wait for {B}20 to land" + SEP,
           "Decide: approve the plan; this does not depend on {B}20 landing · Recommend: approve" + SEP, "Decide: approve this plan, which does not depend on {B}20 landing · Recommend: approve" + SEP,
           "Decide: approve the plan · Recommend: sign, regardless of {B}20" + SEP, "Decide: approve the plan · Recommend: sign, even if {B}20 gets cancelled" + SEP,
           "Decide: approve the plan · Recommend: sign, {B}20 is not required" + SEP, "Decide: renew without waiting for {B}20 to land · Recommend: yes" + SEP,
           "Decide: ship the fix and don't wait for {B}20 to land · Recommend: ship" + SEP, "Decide: approve, there is no need to wait for {B}20 to land · Recommend: yes" + SEP,
           "Approve the plan, never waiting for {B}20 to land.", "Approve the plan, independent of {B}20 landing.")
H2_ASKS = ("Decide: approve the Q1 plan · Recommend: approve now and revisit once {B}20 lands" + SEP, "Decide: which region to deploy to · Recommend: eu · Stakes: the deploy happens once {B}20 lands · By: no date",
           "Decide: which region to deploy to · Recommend: eu · Stakes: signing waits for {B}20 to finish legal review · By: no date", "Decide: which region to deploy to · Recommend: eu · Stakes: none · By: once {B}20 is done",
           "Decide: approve the hire · Recommend: approve; we can announce when {B}20 is live" + SEP, "Decide: pick vendor A or B; once {B}20 is done we sign · Recommend: A" + SEP,
           "Decide: pick vendor A or B, once {B}20 is done we sign · Recommend: A" + SEP, "Decide: pick vendor A or B. Once {B}20 is done we sign · Recommend: A" + SEP,
           "Decide: approve the export once {B}20 lands, the team signs · Recommend: approve" + SEP, "Decide: pick vendor A or B; waiting for {B}20 to land, we sign · Recommend: A" + SEP)
COORD = ("Approve release 1 now, release 2 after {B}20 lands", "Approve release 1 now and release 2 after {B}20 lands", "Approve release 1 now - release 2 after {B}20 lands", "Approve release 1 now (release 2 after {B}20 lands)",
         "Approve both: A now, B once {B}20 lands", "Approve the budget now (owner: pat), the rest once {B}20 lands", "Pick the color now to be ready once {B}20 lands", "Pick the color now, ready for when {B}20 is done",
         "Pick the color now - applied when {B}20 is live", "Pick the color now and it is applied once {B}20 lands", "Approve the refund, the post is waiting for {B}20 to land", "Approve the price, I am waiting on {B}20 to land",
         "Approve now, waiting for {B}20 to land", "Approve the export while waiting for {B}20 to land", "Approve release 2 after {B}20 lands; release 1 goes now", "Stop waiting for {B}20 to land and approve the export.",
         "Approve the export, no point waiting for {B}20 to land", "Approve the export, there is little reason to keep waiting for {B}20 to land", "Approve the export before waiting for {B}20 to land",
         "Approve the export: was waiting for {B}20 to land, no longer relevant", "Approve the export after {B}20 lands. Also pick the price now.", "Approve the export after {B}20 lands. Separately choose the vendor.",
         "Approve the export once {B}20 lands, unless you prefer to go now", "Approve the export once {B}20 lands, or tell me to go now", "Approve the export after {B}20 lands or Pat says go",
         "Approve phase 2 once {B}20 lands or Pat waives it", "Approve the export after {B}20 lands, or counter at 5", "Approve the export after {B}20 lands and decide the price now", "Approve the export after {B}20 lands and Pat is back")
CTRL = ("Approve the export after {B}20 lands.", "Decide: approve the export once {B}20 lands", "Approve the export once {B}20 is merged · Recommend: approve · Stakes: legal is still reviewing it",
        "Once {B}20 lands, approve the export", "Sign the contract when {B}20 is released.")
LIMITS = ("Approve the export after {B}20 lands because the team asked", "Approve the export after {B}20 lands, thanks", "Approve the export and send the invoice after {B}20 lands", "Please do approve the whole export for the east region after {B}20 lands",
          "Review the export after {B}20 lands", "Decide the export after {B}20 lands", "Approve the export after {B}20 lands?", "Approve the export after {B}20 lands (the east region)", "Approve the export - after {B}20 lands",
          "Do not approve the export after {B}20 lands", "Approve the export, after {B}20 lands", "Approve the export after {B}20 lands, then sign", "Approve the export after {B}20 lands. Pat agrees.")
NEW5 = ("Decide: sign the contract when {B}20 is released", "Hire Pat once {B}20 is done", "Ship the fix after {B}20 is merged", "Approve the stopgap until {B}20 ships", "Merge {B}13 after {B}20 is merged")
NEW5 += tuple(t + " · Recommend: yes" + SEP for t in NEW5)
ALL_ASKS = list(dict.fromkeys(list(GATED) + list(ALTS) + ["Decide: " + t + " · Recommend: keep" + SEP for t in ALTS] + WHETHER + STK + list(IN_DECIDE) + REC + list(FINDING1) + list(FINDING2) + list(H1_ASKS) + list(H2_ASKS)
                              + list(COORD) + list(CTRL) + list(LIMITS) + list(BARE) + list(TRIGGER) + list(NEW5)))
item(600, L="g", mover="home-agent")      # an open item the asks below wait on; closed as dropped further down (the close path)
CASES = []
for j, t in enumerate(ALL_ASKS):
    for w in (0, 1):      # 0: the ask alone, 1: the item's stored after names the item too
        k = 1000 + 2 * j + w
        txt = X(t.replace("{B}20", "{B}600"))
        item(k, rec_at=now - 7200, mover="home-other", needs=["decision"], ask=txt, **({"after": ["g600"]} if w else {}))
        CASES.append((k, txt, w))
KS = [k for k, _, _ in CASES]
gone = lambda k: [h for h in history(k) if "ask taken off" in h] + ([] if "ask_left" not in rd(k)["metadata"] else ["ask_left"])
told.clear()
r = _wt_complete.stackshot_complete("g600", outcome="dropped", reason="no longer wanted", outcome_text="- It was dropped, nobody wants it", sender="home-agent")
check("the fixture close: g600 is closed as dropped", rd(600, "g")["status"] == "completed" and rd(600, "g")["metadata"].get("outcome") == "dropped", r)
check("the close path: closing the item as dropped leaves every ask standing (%d asks, with and without a stored after), no History line, nothing kept as taken off, nobody told of one" % len(KS),
      all(stood(k) for k in KS) and not [k for k in KS if gone(k)] and not [x for x in told if x[3] == "ask"], ([k for k in KS if not stood(k)], [k for k in KS if gone(k)][:5], [x for x in told if x[3] == "ask"][:3]))
check("... and the ones that wait on the closed item are still on his move, with the same ask", all(rd(k)["metadata"].get("ask") == txt for k, txt, w in CASES), None)
told.clear()
rs = {k: upd(f"a{k}", priority="p2", sender="home-other") for k in KS}
check("the write path, by the item's mover (not the ask's author): every ask stands, nothing is taken off, and its reminder carries no dropped-dependency fact",
      all(stood(k) for k in KS) and not [k for k in KS if gone(k)] and not [k for k, r in rs.items() if "took the ask off" in r or "which this ask waits on" in r] and all("(reminder: an ask stands on" in r for r in rs.values())
      and not [x for x in told if x[3] == "ask"], ([k for k in KS if not stood(k)], [k for k, r in rs.items() if "which this ask waits on" in r][:5]))
ra = {k: upd(f"a{k}", priority="p3") for k in KS}
fact = X("{B}600, which this ask waits on, was dropped on ")
wrong = [(k, txt) for k, txt, w in CASES if ra[k].count(fact) != (1 if "600" in AL.depends_on(txt) else 0)]
check("the write path, by the ask's author: every ask stands and the reminder carries the dropped-dependency fact exactly once when the ask's text names the item after/once/when/until/waiting for/depends on, and not otherwise",
      all(stood(k) for k in KS) and not [k for k in KS if gone(k)] and not wrong and all("clear_ask=true), otherwise it stands" in ra[k] for k, txt, w in CASES if "600" in AL.depends_on(txt)), wrong[:5])
check("... and every gated form, the five reviewer examples and the plain shapes got the fact (the reminder is the one thing the server does)",
      all(ra[k].count(fact) == 1 for k, txt, w in CASES if any(txt == X(t.replace("{B}20", "{B}600")) for t in list(GATED) + list(CTRL) + list(NEW5) + list(COORD))), [k for k, txt, w in CASES if ra[k].count(fact) != 1][:8])
a600 = rd(1000)["metadata"]
check("the author's write leaves the item as it was: same mover, same ask, still a decision, not closed", rd(1000)["status"] == "open" and a600.get("mover") == "home-other" and "decision" in _model_needs._needs_kinds(a600) and a600.get("ask") == CASES[0][1], a600)

# the reminder reaches the author only, and only for a drop after the ask was written
item(710, rec_at=now - 7200, mover="home-agent", needs=["decision"], ask=X("Decide: approve the export once {B}20 lands · Recommend: ship · Stakes: none · By: no date"))
r = upd("a710", priority="p2")
check("an ask gated on an item closed as dropped after the ask was written: it stands, History is silent, the author's reminder names the item and the date once",
      stood(710) and not gone(710) and r.count(X("{B}20, which this ask waits on, was dropped on ")) == 1 and r.count("reminder") == 1 and "if the ask is moot withdraw it now (clear_ask=true), otherwise it stands" in r, (history(710), r))
r = upd("a710", priority="p3", sender="home-other")
check("another session's write gets no reminder at all (it neither wrote the ask nor moves the item)", "reminder" not in r and "which this ask waits on" not in r and stood(710), r)
item(54, rec_at=now - 7200, mover="home-agent", needs=["decision"], ask=X("Decide: whether to revive {B}20 (dropped in Oct) as a smaller export · Recommend: revive · Stakes: none · By: no date"))
r = upd("a54", priority="p2")
check("an ask that only cites an item closed as dropped stands, and its reminder names no dependency", stood(54) and "took the ask off" not in r and "which this ask waits on" not in r and "reminder" in r, r)
for k, t in zip((62, 63, 64), ("Decide: whether to also drop the export, blocked by {B}20, now dropped · Recommend: drop" + SEP, "Decide: whether to ship the report, which depends on {B}20, which was dropped · Recommend: ship" + SEP,
                               "Decide: whether to ship the report (waits on {B}20, dropped yesterday) · Recommend: ship" + SEP)):
    item(k, rec_at=now - 1800, mover="home-agent", needs=["decision"], ask=X(t))      # written after item 20 was closed (an hour ago)
rs2 = [upd(f"a{k}", priority="p2") for k in (62, 63, 64)]
item(65, rec_at=now - 1800, mover="home-agent", needs=["decision"], ask=X("Decide: approve the export once {B}20 lands · Recommend: ship" + SEP))      # gated, but written after the drop
rs2.append(upd("a65", priority="p2"))
check("an ask written about a dependency that was already dropped (three phrasings, and a gated one) stands and its reminder says nothing of it: a drop before the ask is the ask's fallout",
      all(stood(k) for k in (62, 63, 64, 65)) and not any("which this ask waits on" in r or "took the ask off" in r for r in rs2), rs2)
item(41, rec_at=now - 7200, mover="home-agent", needs=["decision"], ask=X("Decide: approve the export once {B}20 and {B}22 land · Recommend: ship · Stakes: none · By: no date"))
r = upd("a41", priority="p2")
check("one item dropped and one done: the ask stands and the reminder names the dropped one only", stood(41) and r.count("which this ask waits on") == 1 and X("{B}20, which this ask waits on") in r and X("{B}22, which") not in r, r)
item(74, rec_at=now - 7200, mover="home-agent", needs=["decision"], ask=X("Decide: approve the export once {B}70 lands · Recommend: ship · Stakes: none · By: no date"))
item(75, rec_at=now - 7200, mover="home-agent", needs=["decision"], ask=X("Decide: approve the export once {B}72 lands · Recommend: ship · Stakes: none · By: no date"))
r74, r75 = upd("a74", priority="p2"), upd("a75", priority="p2")
check("an ask that waits on an item superseded by an open one stands with no mention; one whose replacement chain ends in a dropped item stands and the reminder says how it ended",
      stood(74) and "which this ask waits on" not in r74 and stood(75) and not gone(75) and X("{B}72, which this ask waits on, was superseded by") in r75 and X("{B}73") in r75, (r74, r75))
for k, n in ((86, 80), (87, 82), (88, 83), (89, 84), (90, 85)):
    item(k, rec_at=now - 7200, mover="home-agent", needs=["decision"], ask=X(f"Decide: approve the export once {{B}}{n} lands · Recommend: ship" + SEP))
rs3 = [upd(f"a{k}", priority="p2") for k in (86, 87, 88, 89, 90)]
check("an ask on a superseded cycle, a superseded item with no replacement named, a missing replacement, a reopened item and one reopened with a stale outcome stands and its reminder names nothing",
      all(stood(k) for k in (86, 87, 88, 89, 90)) and not any("which this ask waits on" in r or "took the ask off" in r for r in rs3), rs3)
check("... and the lookup gives up on each of them (a cycle ends nowhere, a missing replacement is unread, an open item is not closed)",
      server._ask_lookup("80") is None and server._ask_lookup("82") is None and server._ask_lookup("83") is None and server._ask_lookup("84")[0] == "open" and server._ask_lookup("85")[0] == "open",
      [server._ask_lookup(n) for n in ("80", "82", "83", "84", "85")])
check("the lookup follows a superseded item to the end of its chain (and gives up on a chain it cannot read)",
      server._ask_lookup("72")[:2] == ("completed", "dropped") and server._ask_lookup("70")[:2] == ("open", "") and server._ask_lookup("21") is None and server._ask_lookup("20")[:2] == ("completed", "dropped"),
      [server._ask_lookup(n) for n in ("72", "70", "21", "20")])
# an ask stored before the record was kept has no time to compare a drop with: its reminder names nothing
item(160, mover="home-agent", needs=["decision"], ask=X("Decide: approve the export once {B}47 lands · Recommend: approve" + SEP))
item(161, mover="home-agent", needs=["decision"], ask=X("Decide: approve the export once {B}20 and {B}47 land · Recommend: approve" + SEP))
item(162, rec_at=now - 7200, mover="home-agent", needs=["decision"], ask=X("Decide: approve the export once {B}20 and {B}47 land · Recommend: approve" + SEP))
r160, r161, r162 = upd("a160", priority="p2"), upd("a161", priority="p2"), upd("a162", priority="p2")
check("an ask with no record names no dropped dependency in its reminder; one with a record names both",
      all(stood(k) for k in (160, 161, 162)) and "which this ask waits on" not in r160 + r161 and r162.count("which this ask waits on") == 2 and "reminder" in r160 and "reminder" in r161, (r160, r161, r162))
# the item's mover is not the ask's author: the reminder it gets carries no dropped-dependency fact (asked above with 1000+); the author who wrote the ask on a hold or a wait gets the same line
item(711, rec_at=now - 7200, mover="home-agent", needs=["decision"], ask=X("Decide: approve the export once {B}20 lands · Recommend: ship" + SEP), after=["g20"])
r = upd("a711", priority="p2")
check("a stored after naming the dropped item adds nothing and takes nothing away: the ask's own text is what is read", stood(711) and r.count("which this ask waits on") == 1, r)
item(712, rec_at=now - 7200, mover="home-agent", needs=["decision"], after=["g20"], ask="Decide: Acme or Beta vendor · Recommend: Acme" + SEP)
r = upd("a712", priority="p2")
check("an ask that names no id stands and names no dependency though the item's stored after names the dropped item", stood(712) and "which this ask waits on" not in r, r)
check("a close seen as superseded or as done leaves asks alone too (the close path has no ask step any more)",
      server._ask_lookup("22")[:2] == ("completed", "done") and stood(711) and stood(712), None)

# the author's word, on the write's new text: the plain sentence counts, anything around it stands (every stand-case of the pure reader, through the server's own tail)
item(500, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK})
tail = lambda texts, k=500: server._ask_after_write(gates.ask_pre(f"a{k}"), "home-agent", "", False, texts)
STAND_W = [[t] for t in NOT_WORD] + [w for t in ("The ask is wrong.", "- My question is moot.", "This ask is no longer needed.") for e in EXTRAS for w in around(t, e)]
bad = [t for t in STAND_W if "took the ask off" in tail(t) or not stood(500)]
check("the author's word on a write (%d inputs): a hedge, a clause, a question, a label, a quote, a name and a colon, another sentence or line before or after, a disagreement, Korean, 'Pat to decide', a second text: the ask stands" % len(STAND_W), not bad, bad[:5])
for k, t in zip((501, 502, 503, 504, 505), ("The ask is wrong.", "My question is moot.", "This ask is no longer needed.", "- The ask is wrong.", "- My question is moot.")):
    item(k, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK})
    r = tail([t], k)
    check(f"the author's word on a write: {t!r} alone takes the ask off", not stood(k) and "took the ask off" in r, r)
item(506, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK})
r = server._ask_after_write(gates.ask_pre("a506"), "home-other", "", False, ["The ask is wrong."])
check("the same plain sentence from a session that is not the ask's author takes nothing off", stood(506) and "took the ask off" not in r, r)

# (round 11, M1) through the update tool: a hedge inside a longer old line rides along with the sentence and the ask stands; a hedge held as a whole old line is not new, so the sentence alone removes the ask
for k, h in zip(range(720, 727), HEDGES):
    old_d = f"- Goal: A thing\n- Status: migration is {h.lower()} done\n- Finished when it works"
    item(k, mover="home-agent", description=old_d); upd(f"a{k}", ask=ASK, needs=["decision"], options=OPTS)
    r = upd(f"a{k}", description=old_d + f"\n- The ask is wrong.\n- {h}")
    check(f"a hedge {h!r} beside the sentence, while the old description holds it inside a longer line: the ask stands", stood(k) and "took the ask off" not in r, r)
for k, h in zip(range(730, 737), HEDGES):
    old_d = f"- Goal: A thing\n- {h}\n- Finished when it works"
    item(k, mover="home-agent", description=old_d); upd(f"a{k}", ask=ASK, needs=["decision"], options=OPTS)
    r = upd(f"a{k}", description=old_d + "\n- The ask is wrong.")
    check(f"the old description holds {h!r} as a whole line, sent again unchanged beside the sentence: the sentence is the whole new text and takes the ask off", not stood(k) and "took the ask off" in r, r)

# (round 11, M2) every text parameter of update is read: the sentence in the description beside any other new text, in any text parameter, leaves the ask standing
SAY = "Keep the ask, it is still right"
PVAL = {"options": [{"label": "Keep", "line": SAY}], "said": [{"quote": SAY, "kind": "comment"}], "work": {"note": SAY}, "reword": {1: SAY}, "step_proof": [{"step": 1, "proof": SAY}], "observers": [SAY]}
import inspect
SIG = set(inspect.signature(_wt_update.stackshot_update).parameters)
TP, NP = list(_wt_update._ASK_TEXT_PARAMS), list(_wt_update._ASK_NONTEXT_PARAMS)
check("every parameter of update is placed in exactly one of the two ask lists (text read, or not read), so a parameter added later forces a decision",
      SIG == set(TP) | set(NP) and not set(TP) & set(NP) and len(TP) == len(set(TP)) and len(NP) == len(set(NP)), (sorted(SIG - set(TP) - set(NP)), sorted((set(TP) | set(NP)) - SIG), sorted(set(TP) & set(NP))))
check("the texts of a call: each text parameter's strings are found (a mapping or list gives each string inside it), the fixed-word and switch parameters give none",
      all(SAY in _wt_update._ask_write_texts({p: PVAL.get(p, SAY)}) for p in TP) and not any(_wt_update._ask_write_texts({p: PVAL.get(p, SAY)}) for p in NP), [p for p in TP if SAY not in _wt_update._ask_write_texts({p: PVAL.get(p, SAY)})])
item(799, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK})
check("the control: the sentence alone in the description, through the server's own tail, takes the ask off", "took the ask off" in tail(_wt_update._ask_write_texts({"description": DW("The ask is wrong.")}), 799) and not stood(799))
bad_p = []
for j, p in enumerate(TP):
    k = 800 + j
    item(k, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK})
    r = tail(_wt_update._ask_write_texts({"description": DW("The ask is wrong."), p: PVAL.get(p, SAY)}), k)
    if "took the ask off" in r or not stood(k): bad_p.append(p)
check("the sentence in the description plus new text in any one of the %d text parameters of update (%s) leaves the ask standing" % (len(TP), ", ".join(TP)), not bad_p, bad_p)
# the same through the update tool, on the parameters whose write is accepted as sent here, with the write's effect read back
REAL = {"subject": ("[home] Keep the ask, it is still right", lambda m, i: i["subject"] == "[home] Keep the ask, it is still right"), "goal": (SAY, lambda m, i: m.get("goal") == SAY),
        "draft": (SAY, lambda m, i: m.get("draft") == SAY), "owner_name": (SAY, lambda m, i: m.get("owner_name") == SAY), "next": ("home-agent: the next step\nhome-agent: Keep the ask", lambda m, i: "Keep the ask" in str(m.get("next")))}
bad_r = []
for j, (p, (v, took)) in enumerate(REAL.items()):
    k = 830 + j
    item(k, mover="home-agent"); upd(f"a{k}", ask=ASK, needs=["decision"], options=OPTS)
    r = upd(f"a{k}", description=DW("The ask is wrong."), **{p: v})
    if not (stood(k) and "took the ask off" not in r and took(rd(k)["metadata"], rd(k))): bad_r.append((p, r[:200]))
check("through the update tool: the sentence in the description plus a new subject, goal, draft, owner_name or next line leaves the ask standing, and the write itself was accepted", not bad_r, bad_r)
item(840, mover="home-agent"); upd("a840", ask=ASK, needs=["decision"], options=OPTS)
r = upd("a840", description=DW("The ask is wrong."), next="home-agent: the next step", subject=rd(840)["subject"])
check("... while the same fields sent again unchanged (next as stored, the subject as stored) are not new text: the sentence takes the ask off", not stood(840) and "took the ask off" in r, r)

# (round 12, M1) every parameter left on the non-text list is tried through the REAL update with a free-text hedge: it must be refused or not stored, so a parameter that starts to accept text fails here
SKIP_NP = {"item_id", "sender", "ask", "clear_ask"}      # the item's id; the sender's own name; the ask itself (a write that sets one takes the ask-time check, and replaces the ask by design)
DEFAULTS = {n: p.default for n, p in inspect.signature(_wt_update.stackshot_update).parameters.items()}
NP_REAL = [p for p in NP if p not in SKIP_NP and not isinstance(DEFAULTS[p], bool)]
def real(k, **kw):
    try:
        return "accepted", upd(f"a{k}", description=DW("The ask is wrong."), **kw)
    except Exception as e:  # noqa: BLE001  — a refusal is a ToolError; any error is the write not made
        return "refused", str(e)[:160]
leak, took_off = [], []
for j, p in enumerate(NP_REAL):
    k = 900 + j
    item(k, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK})
    how, r = real(k, **{p: SAY})
    if how == "accepted" and "still right" in json.dumps(rd(k)).lower(): leak.append(p)
check("every parameter on the non-text list (%d: %s), sent a free-text hedge through the real update beside the author's sentence, is refused or not stored" % (len(NP_REAL), ", ".join(NP_REAL)), not leak, leak)
# a real-update stand-case for every text parameter: the sentence in the description plus a new value of that parameter leaves the ask standing (the write may also be refused: then nothing was written)
acc, ref, bad_t = [], [], []
for j, p in enumerate(TP):
    k = 950 + j
    item(k, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK})
    how, r = real(k, **{p: ("[home] " + SAY) if p == "subject" else PVAL.get(p, SAY)})
    (acc if how == "accepted" else ref).append(p)
    if not stood(k) or "took the ask off" in r: bad_t.append(p)
print(f"real update, text parameters accepted as sent: {acc}; refused as sent: {ref}")
check("through the real update, the sentence in the description plus a new value of any one of the %d text parameters leaves the ask standing" % len(TP), not bad_t, bad_t)
check("... wait_anchor, post_wake_mover and then, which store a free string as written, are among the text parameters", {"wait_anchor", "post_wake_mover", "then"} <= set(TP), None)

# (round 12, L1) from the records of lines only the `text` is held: status words ("open", "done", "dropped") are not the item's text
item(980, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK}, wait_basis={"text": "waiting for the vendor", "wake": "2026-11-20", "by": "home-agent", "at": now},
     steps=[{"text": "home-agent: the next step", "status": "open"}, {"text": "home-agent: an old step", "status": "done", "by": "home-agent", "at": now - 100}, {"text": "home-agent: a dropped step", "status": "dropped", "by": "home-agent", "at": now - 90}])
held = gates.ask_pre("a980")["old"].split("\n")
check("the lines an item holds: the text of each step and of the wait basis, and not its status, its marker's name or its time",
      "home-agent: the next step" in held and "home-agent: an old step" in held and "waiting for the vendor" in held and not [x for x in held if x.strip().lower() in ("open", "done", "dropped", "2026-11-20", "home-agent")], held)
bad_s = []
for j, w in enumerate(("Open", "Done", "Dropped", "open", "- done")):
    k = 981 + j
    item(k, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK}, steps=[{"text": "home-agent: the next step", "status": "open"}, {"text": "home-agent: an old step", "status": "done", "by": "home-agent", "at": now - 100}])
    r = upd(f"a{k}", description=DESC + "\n- The ask is wrong.\n- " + w.lstrip("- "))
    if not stood(k) or "took the ask off" in r: bad_s.append(w)
check("a status word beside the sentence (Open, Done, Dropped) is new text, not a held line: the ask stands", not bad_s, bad_s)

# (round 12, L3) a damaged stamp (a time that is no number) never fails a write
item(990, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": "soon", "text": ASK})
item(991, mover="home-agent", ask_left={"at": "never", "ask": ASK, "how": "word"})
item(992, mover="home-agent", needs=["decision"], ask=ASK, ask_rec={"by": "home-agent", "at": now - 600, "text": ASK}, ask_left={"at": {"x": 1}, "ask": ASK})
res_c = []
for k in (990, 991, 992):
    try:
        r = upd(f"a{k}", priority="p2"); res_c.append((k, rd(k)["metadata"].get("priority") == "p2"))
    except Exception as e:  # noqa: BLE001
        res_c.append((k, f"raised {e.__class__.__name__}: {str(e)[:100]}"))
check("a corrupt ask_rec.at or ask_left.at never fails the write: the update is saved (three damaged shapes)", all(ok is True for _, ok in res_c) and gates.ask_pre("a990") == {}, res_c)

# (round 12, L4) the writer's label is read only when a save changes the ask
labels = []
_label0 = server._session_label
server._session_label = _wt_route._session_label = lambda w: (labels.append(w), _label0(w))[1]
try:
    it0 = rd(1000); before0 = json.loads(json.dumps(it0))
    server._ask_stamp(it0, before0, "home-agent"); n_same = len(labels)
    it1 = json.loads(json.dumps(it0)); it1["metadata"]["ask"] = ASK2
    server._ask_stamp(it1, before0, "home-agent"); n_changed = len(labels) - n_same
    it2 = json.loads(json.dumps(it0)); it2["metadata"].pop("ask", None)
    server._ask_stamp(it2, before0, "home-agent"); n_gone = len(labels) - n_same - n_changed
finally:
    server._session_label = _wt_route._session_label = _label0
check("a save that leaves the ask as it was, or removes it, does not look the writer up; one that changes it does, once, and records who wrote it",
      n_same == 0 and n_gone == 0 and n_changed == 1 and it1["metadata"]["ask_rec"]["by"] and "ask_rec" not in it2["metadata"] and it0["metadata"]["ask_rec"] == before0["metadata"]["ask_rec"], (n_same, n_changed, n_gone))
check("changed(): a new ask, the same ask with other spacing, none", AL.changed({"ask": "a b"}, {"ask": "a  c"}) and not AL.changed({"ask": "a  b"}, {"ask": "a b"}) and not AL.changed({}, {"ask": "a"}) and AL.changed({"ask": "a"}, None))

# (round 11, L1) the dropped-dependency clause comes with each write of the ask's author while the dependency stays dropped and the ask stands; the server keeps no state of it
item(713, rec_at=now - 7200, mover="home-agent", needs=["decision"], ask=X("Decide: approve the export once {B}20 lands · Recommend: ship" + SEP))
r1 = upd("a713", priority="p2"); keys1 = set(rd(713)["metadata"])
r2 = upd("a713", priority="p3"); m713 = rd(713)["metadata"]
check("the clause repeats: two writes by the ask's author in a row each carry the dropped-dependency clause once, the ask stands, and the second write stores nothing new about having said it",
      r1.count("which this ask waits on") == 1 and r2.count("which this ask waits on") == 1 and stood(713) and set(m713) == keys1 and "waits on" not in json.dumps(m713), (r1.count("which this ask waits on"), r2.count("which this ask waits on"), stood(713), sorted(set(m713) ^ keys1)))


# ---- 5. what the server never does
check("nothing in the leave closes an item, writes an ask or answers for him: no decision answer was recorded by the server",
      all(a.get("kind") != "decision" for i in (3, 4, 14, 710) for a in (rd(i)["metadata"].get("answers") or [])), None)

# ---- 6. the off switch, in the config file
from stackshot.core import config as _cfg
cfgfile = T / "stackshot.toml"; on_text = cfgfile.read_text(encoding="utf-8")
assert re.search(r"(?m)^leaves = true", on_text), "the example config carries [ask] leaves"
check("[ask] leaves defaults to on", _cfg.ask_leaves_on() is True)
cfgfile.write_text(re.sub(r"(?m)^leaves = true", "leaves = false", on_text, count=1), encoding="utf-8")
check("the config file's [ask] leaves = false is read on reload", _cfg.reload() is not None and _cfg.ask_leaves_on() is False)
try:
    item(45, mover="home-agent", needs=["decision"], ask=ASK)
    r = upd("a45", description=DW("The ask is wrong"))
    check("[ask] leaves = false: the author's plain sentence changes nothing, the reminder still comes", stood(45) and "reminder" in r and "took the ask off" not in r, r)
    item(46, rec_at=now - 7200, mover="home-agent", needs=["decision"], ask=X("Decide: ship once {B}20 lands · Recommend: ship · Stakes: none · By: no date"))
    r = upd("a46", priority="p2")
    check("[ask] leaves = false: a dropped dependency still only reminds its author (the record removed nothing before either)", stood(46) and "reminder" in r and "took the ask off" not in r, r)
finally:
    cfgfile.write_text(on_text, encoding="utf-8"); _cfg.reload()
check("the switch is back on", _cfg.ask_leaves_on() is True)

# ---- 7. the server applies what he said (part 4)
told.clear()
res = server._answer("a30", "", "ran it", "send"); m = rd(30)["metadata"]
check("his note 'ran it' ticks his step as a Done does", res == "stepreply" and "step" not in m and "state" not in m and m["answers"][-1].get("applied"), (res, m))
check("the item goes to the then-mover and the notice says what was applied, not 'judge the note'", m.get("mover") == "home-agent" and told and "Judge the note" not in told[-1][2] and "ticked his step" in told[-1][2], told)
told.clear()
tomorrow_ = (__import__("stackshot.projects.pages", fromlist=["_"]).zone_now() + dt.timedelta(days=1)).strftime("%Y-%m-%d")
runner_svc.WAKE_EVENT.clear()
res = server._answer("a31", "", "I'll do it tomorrow evening", "send"); m = rd(31)["metadata"]
check("his note 'tomorrow evening' wakes the minute loop and stores the one until date, with no hold and no old wake", runner_svc.WAKE_EVENT.is_set() and m.get("until") == f"{tomorrow_}T19:00" and "hold" not in m and "wake" not in m, (runner_svc.WAKE_EVENT.is_set(), m))
tomorrow = (__import__("stackshot.projects.pages", fromlist=["_"]).zone_now() + dt.timedelta(days=1)).strftime("%Y-%m-%d")
check("his note 'tomorrow evening' holds the item until then: hold, wake, his words behind the wake", hd_(m) is True and str(wk_(m)) == f"{tomorrow}T19:00" and (m.get("cap_ok") or {}).get("quote") == "I'll do it tomorrow evening", (hd_(m), wk_(m), m.get("cap_ok")))
check("the notice names the hold and the time, and asks nothing before then", told and "Judge the note" not in told[-1][2] and f"on hold until {tomorrow}T19:00" in told[-1][2] and "nothing is asked of you before then" in told[-1][2], told)
told.clear()
res = server._answer("a32", "", "can I do it tomorrow evening?", "send"); m = rd(32)["metadata"]
check("a question naming a time is neither a tick nor a hold: it goes to the session to judge", res == "stepreply" and not hd_(m) and not wk_(m) and not (m["answers"][-1].get("applied")) and told and "Judge the note" in told[-1][2], (m, told))
told.clear()
res = server._answer("a33", "", "ran it but it says forbidden", "send"); m = rd(33)["metadata"]
check("a longer note that goes on is not a tick", not m["answers"][-1].get("applied") and told and "Judge the note" in told[-1][2], (m, told))
res = server._answer("a34", "", "", "done")
check("Done with an empty box still finishes the step as before", res == "done" and "step" not in rd(34)["metadata"], res)

# ---- 8. the texts agents learn it from
d = _wt_update._UPDATE_DESC
check("the update text says it: the reminder, the one plain sentence, what stands, the dropped dependency as a reminder only, the late answer, what it never does, and the notes it applies",
      all(x in d for x in ("reminder", "in one case only: its author's own plain sentence", "whose whole new text", "exactly one sentence", "The ask is wrong.", "My question is moot.", "This ask is no longer needed.",
                           "Any other new line or sentence in that write", "A dropped dependency removes nothing", "a dropped gate often makes the ask more live", "names an item after/once/when/until/waiting for/depends on",
                           "reminded on each of his writes to the item while that item stays dropped and the ask stands", "in every text parameter of the call", "and only \"now\", \"anymore\" or a full stop after it", "clear_ask=true", "late answer as a comment", "never writes an ask, closes an item or answers for", "ran it", "tomorrow evening"))
      and not any(x in d for x in ("two plain shapes", "shape (2)", "approve-type request", "replacement chain", "taken off by the record")), [x for x in ("reminder", "in one case only") if x not in d])
cf = _wt_text._CLOSE_FORM
check("the close text carries the same words as the update text (one rule, one paragraph) and no longer says a close acts on asks", _wt_text._ASK_RULE in cf and _wt_text._ASK_RULE in d and "applies shape" not in cf and "A dropped dependency removes nothing" in cf, None)
import _docs
readme = _docs.page("asks-and-answers")
check("the docs state the limit with its After wording", "Never by the server: closing an item, writing an ask, answering for the owner, altering his words" in readme, None)
check("the docs say the server removes an ask only on the author's own plain sentence, a dropped dependency only reminds the author, and names the reader's words",
      "only on its author's own plain sentence" in readme and "a dropped dependency only reminds" in readme and "after/once/when/until/waiting for/depends on" in readme and "two plain shapes" not in _docs.pages(), None)
check("the docs say which parameters are read (every one of the text list, by name), which are not and why, that a part of a longer held line is new, and that the clause repeats on each write",
      all(f"`{p}`" in readme for p in _wt_update._ASK_TEXT_PARAMS + _wt_update._ASK_NONTEXT_PARAMS if not p.startswith("clear_") and p not in ("item_id", "hold", "recycle"))
      and "a line that only appears inside a longer held line is new" in readme and "with each of his writes to the item for as long as the dependency stays dropped and the ask stands" in readme
      and "an ask stored before the record has none, and then the item's mover and creator count as its author" in readme and "naming each such item once in the clause" in readme, [p for p in _wt_update._ASK_TEXT_PARAMS + _wt_update._ASK_NONTEXT_PARAMS if f"`{p}`" not in readme][:6])
check("the ask rule never says 'nothing after it' and the config's own help says the same as the docs", "nothing after it" not in _wt_text._ASK_RULE
      and "its author's write is, whole, one plain sentence" in pathlib.Path(STACK, "stackshot/core/config.py").read_text(encoding="utf-8") and "the record shows it moot" not in pathlib.Path(STACK, "stackshot/core/config.py").read_text(encoding="utf-8"), None)
check("the example config says the same", "only on its author's own plain sentence" in pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), None)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
