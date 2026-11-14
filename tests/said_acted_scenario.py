"""Scenario test for said entries of kind acted (said.py, gates.gate_said, tools/next_report.py N4) — fixture data, no live store, no network, no server socket
(the server module is imported and called in-process, on a temporary config; the transcripts are fixture files in a temporary directory, never the host's).

A message the owner sends while a session is working (a reply he got elsewhere, pasted in) is recorded in the transcript as an attachment entry of type
queued_command, attachment.origin.kind human, chained after a tool result (or a meta user entry) inside the session's turn, not as a typed message.
Covers: the said gate refuses that entry as his words (and the refusal says how to cite it as acted); {kind: acted} accepts it wherever it sits (after a
tool result, after a meta entry), checked and stored as Done-by with kind acted, the quote read from attachment.prompt only and compared whitespace aside;
it refuses a queued_command of peer origin, one of task-notification origin, one with no origin, a hook_additional_context right after an owner prompt, a
hook_additional_context in the session's turn followed by the owner's next prompt (no entry counts by its position), an entry that is not in the
transcript, his typed message, a quote the prompt does not hold (even when another field of the attachment holds it); an acted entry with a words tag is
refused; an unreadable transcript stores it unchecked. A queued_command of human origin whose text a tool typed in (the marker, a configured prefix or phrase) is refused
with the injected code, as his typed words are. The check streams the transcript (a large file is never held in memory). An acted entry never counts as his words or decision
(owner_words_by, the server's cap words and close words). N4 stays quiet on his ticked step backed by a checked acted entry at or before the mark and within 24 hours before it,
and still flags one with no evidence, an acted entry after the mark, one longer than 24 hours before it, or an unchecked one.

    tests/run-suite said_acted        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time, tracemalloc
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="saidacted-"); T = pathlib.Path(tmp)
MARK = "<!-- fleet -->"
toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1      # never the host's transcripts
toml, n = re.subn(r'(?m)^injected_marker = ""', f'injected_marker = "{MARK}"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
from stackshot.service import gates; from stackshot.web import server; from stackshot.model import said; from stackshot.tools import next_report as NR

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
SESS, AWAY, BIG = uid(1), uid(2), uid(4)          # a session whose transcript is on this box, one whose is not, and one with a large transcript
PASTE = "Thanks for writing in. Your refund of 12 dollars was sent today."
TS = lambda n: f"2026-11-01T01:{n:02d}:00Z"
def u(n, text, kind="human", parent=None, **kw): return {"type": "user", "uuid": uid(n), "parentUuid": parent and uid(parent), "origin": {"kind": kind}, "message": {"role": "user", "content": text}, "timestamp": TS(n), **kw}
def tool_result(n, parent): return {"type": "user", "uuid": uid(n), "parentUuid": uid(parent), "toolUseResult": {"stdout": "ok"}, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}, "timestamp": TS(n)}
def meta(n, parent): return {"type": "user", "uuid": uid(n), "parentUuid": uid(parent), "isMeta": True, "message": {"role": "user", "content": "context the CLI added"}, "timestamp": TS(n)}
def queued(n, parent, origin="human", text=PASTE, **extra):
    a = {"type": "queued_command", "prompt": text, "commandMode": "prompt", **extra}
    if origin is not None: a["origin"] = {"kind": origin}
    return {"type": "attachment", "uuid": uid(n), "parentUuid": uid(parent), "attachment": a, "timestamp": TS(n)}
def hook(n, parent, text=PASTE): return {"type": "attachment", "uuid": uid(n), "parentUuid": uid(parent), "attachment": {"type": "hook_additional_context", "content": [text], "hookName": "UserPromptSubmit"}, "timestamp": TS(n)}
def asst(n, parent, text="I will tick the step."): return {"type": "assistant", "uuid": uid(n), "parentUuid": uid(parent), "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}, "timestamp": TS(n)}
rows = [
    u(10, "chase the refund in the support chat"), asst(11, 10), tool_result(12, 11),
    queued(13, 12),                                                           # his message sent while the session worked: after a tool result, in the session's turn
    queued(14, 13, origin="peer"), queued(15, 14, origin="task-notification"), queued(16, 15, origin=None),
    asst(17, 16), meta(18, 17), queued(19, 18, text="second note: " + PASTE),   # his message after a meta user entry
    u(20, "here is what the support bot said", parent=19), hook(21, 20),     # hook context right after an owner prompt
    asst(22, 21), hook(23, 22), u(24, "and this is my next prompt", parent=23),   # hook context in the session's turn, then his next prompt
    queued(25, 24, text="nothing about money", note=PASTE),                  # his queued message; the quote sits in another field only
    queued(26, 25, text=MARK + " " + PASTE),                                  # human origin, but the text starts with the marker a fleet tool types
    queued(27, 26, text="relay text " + PASTE),                               # human origin; refused only through a configured prefix or phrase
]
(T / "transcripts/-home-x" / f"{SESS}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

def gate(*specs, sess=SESS):
    try: return gates.gate_said(list(specs), sess, "home-agent"), ""
    except Exception as e: return None, str(e)
words = lambda msg, quote="refund of 12 dollars": {"tag": "Acked-by", "quote": quote, "msg": uid(msg)}
acted = lambda msg, quote="refund of 12 dollars", **kw: {"kind": "acted", "quote": quote, "msg": uid(msg), **kw}

# ---- the said gate
got, why = gate(words(13))
check("a queued message of his is refused as his words, and the refusal says to cite it with kind: acted", got is None and "Refused" in why and "attachment entry" in why and "kind: acted" in why, why)
got, why = gate(acted(13))
check("a human queued_command after a tool result is accepted as acted: checked, tag Done-by, kind acted, the entry's time",
      got and got[0]["checked"] and got[0]["tag"] == "Done-by" and got[0]["kind"] == "acted" and got[0]["ts"] == said.entry_ts(queued(13, 12)) and got[0]["session"] == SESS, (got, why))
check("the reply line says it is proof he did a step, not his words", "kind acted" in server._said_note(got or []) and "not his words" in server._said_note(got or []), server._said_note(got or []))
got, why = gate(acted(19, quote="second note:   Thanks for\nwriting   in."))
check("a human queued_command after a meta user entry is accepted too (and the quote is compared whitespace aside)", got and got[0]["checked"], (got, why))
for n, how, frag in ((14, "a queued_command of peer origin", "origin is peer"), (15, "a queued_command of task-notification origin", "origin is task-notification"),
                     (16, "a queued_command with no origin", "no origin"),
                     (21, "a hook_additional_context right after an owner prompt", "hook_additional_context attachment"),
                     (23, "a hook_additional_context in the session's turn followed by the owner's next prompt", "hook_additional_context attachment")):
    got, why = gate(acted(n))
    check(f"{how} is refused as acted: not a message Oliver sent", got is None and "is not a message Oliver sent" in why and frag in why, why)
got, why = gate(acted(25))
check("the quote is read from attachment.prompt only: one held by another field of the attachment is refused", got is None and "quote is not in the queued message's prompt" in why, why)
got, why = gate(acted(99))
check("a forged citation (no entry with that uuid in the transcript) is refused", got is None and "no message" in why, why)
got, why = gate(acted(10, quote="support chat"))
check("his typed message cannot be cited as acted (it is cited as his words)", got is None and "not an attachment entry" in why, why)
got, why = gate(acted(13, quote="refund of 99 dollars"))
check("a quote the prompt does not hold is refused", got is None and "quote is not in the queued message's prompt" in why, why)
got, why = gate(acted(13, tag="Acked-by"))
check("an acted entry with a words tag is refused: it is never his words", got is None and "never his words" in why, why)
got, why = gate(acted(26))
check("a marker-prefixed queued message of human origin is refused as acted: text a tool typed into the pane", got is None and "typed into the pane" in why and MARK in why, why)
check("…with the injected code from verify_acted", said.verify_acted(SESS, uid(26), "refund of 12 dollars", [str(T / "transcripts")], marker=MARK)["code"] == "injected")
check("…and the same message passes verify_acted when no marker is configured", said.verify_acted(SESS, uid(26), "refund of 12 dollars", [str(T / "transcripts")])["code"] == "ok")
check("a configured prefix refuses a queued message too", said.check_acted(queued(27, 26, text="relay text " + PASTE), "refund of 12 dollars", prefixes=("relay text",))[0] == "injected")
check("a configured phrase refuses a queued message too", said.check_acted(queued(27, 26, text="relay text " + PASTE), "refund of 12 dollars", phrases=("relay text",))[0] == "injected")
check("a message that merely quotes the marker further down is his", said.check_acted(queued(27, 26, text=PASTE + " " + MARK), "refund of 12 dollars", marker=MARK)[0] == "ok")
got, why = gate(acted(13), sess=AWAY)
check("a transcript this box cannot read stores the acted entry unchecked", got and not got[0]["checked"] and got[0]["kind"] == "acted", (got, why))
tpath = T / "transcripts/-home-x" / f"{SESS}.jsonl"
check("check_acted tests the one entry find_entry returns, and a missing entry is missing", [said.check_acted(said.find_entry(tpath, uid(n)), "refund of 12 dollars")[0] for n in (13, 14, 21, 99)]
      == ["ok", "not_human", "not_queued", "missing"])

# ---- a large transcript is streamed, never read into memory: 40 MB of lines, the cited entry at the end, peak Python memory held under a fraction of the file
big = T / "transcripts/-home-x" / f"{BIG}.jsonl"
filler = json.dumps({"type": "assistant", "uuid": uid(900), "message": {"role": "assistant", "content": [{"type": "text", "text": "x" * 8000}]}}) + "\n"
with open(big, "w", encoding="utf-8") as f:
    for _ in range(5000): f.write(filler)
    f.write(json.dumps(queued(28, 27)) + "\n")
size_mb = big.stat().st_size / 1e6
tracemalloc.start()
r = said.verify_acted(BIG, uid(28), "refund of 12 dollars", [str(T / "transcripts")])
peak_mb = tracemalloc.get_traced_memory()[1] / 1e6; tracemalloc.stop()
check("a large transcript is checked (the entry at its end is found)", r["code"] == "ok" and r["checked"], r)
check(f"…and not read into memory: a {size_mb:.0f} MB transcript peaks at {peak_mb:.1f} MB", size_mb > 35 and peak_mb < 5, (size_mb, peak_mb))
big.unlink()

# ---- an acted entry is never his words or his decision
ACT_TS = said.entry_ts(queued(13, 12))
acted_rec = {"tag": "Done-by", "kind": "acted", "quote": "refund of 12 dollars", "session": SESS, "msg": uid(13), "ts": ACT_TS, "checked": True, "by": "home-agent"}
check("owner_words_by (N4's words) does not read an acted entry", NR.owner_words_by({"said": [acted_rec]}, ACT_TS + 60) == "")
check("…even one stored with a words tag beside kind acted: entries_of reads it as Done-by, kind acted",
      said.entries_of({"said": [{**acted_rec, "tag": "Acked-by"}]})[0]["tag"] == "Done-by" and NR.owner_words_by({"said": [{**acted_rec, "tag": "Acked-by"}]}, ACT_TS + 60) == "")
check("the server's decision words (a wake past the cap) are not satisfied by an acted entry", server._owner_words_on({"metadata": {}}, [{**acted_rec, "ts": time.time() - 60}], 30.0) == "")
check("the server's close words are not satisfied by an acted entry", said._owner_words({"metadata": {"said": [acted_rec]}}) == "")

# ---- N4
DONE_AT = NR.PART1_LIVE + 1000
def item(**meta):
    return {"id": "1", "status": "open", "subject": "[home] chase the refund", "metadata": {"owner": uid(3), "project": "projects/alpha", "needs": ["home-agent"], "next": "home-agent: close it out",
            "steps": [{"text": "Oliver: send the chase message in the support chat", "status": "done", "by": "home-agent", "at": DONE_AT},
                      {"text": "home-agent: close it out", "status": "open"}], **meta}}
n4 = lambda it: [r for r, _ in NR.check_item(it) if r == "N4"]
check("N4 is quiet on his ticked step backed by a checked acted entry at or before the mark", n4(item(said=[{**acted_rec, "ts": DONE_AT - 60}])) == [], NR.check_item(item(said=[{**acted_rec, "ts": DONE_AT - 60}])))
check("N4 still flags his ticked step with no evidence", n4(item()) == ["N4"], NR.check_item(item()))
check("N4 still flags it when the acted entry comes after the mark", n4(item(said=[{**acted_rec, "ts": DONE_AT + 60}])) == ["N4"])
H = 3600.0
check("N4 is quiet when the acted entry is a little under 24 hours before the mark", n4(item(said=[{**acted_rec, "ts": DONE_AT - 24 * H + 60}])) == [], NR.check_item(item(said=[{**acted_rec, "ts": DONE_AT - 24 * H + 60}])))
check("N4 flags the step when the acted entry is more than 24 hours before the mark", n4(item(said=[{**acted_rec, "ts": DONE_AT - 24 * H - 60}])) == ["N4"])
check("the window is a constant of 24 hours", NR.ACTED_WINDOW == 24 * H)
check("N4 still flags it when the acted entry is unchecked", n4(item(said=[{**acted_rec, "ts": DONE_AT - 60, "checked": False}])) == ["N4"])

print(("ok" if not fails else "FAILED") + f": said_acted scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
