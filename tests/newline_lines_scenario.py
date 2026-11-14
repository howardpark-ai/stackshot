"""Scenario test for reading a one-record-per-line file at newlines only (core/lines.py `newline_lines`) - fixture data, no live store, no network, no server.

`str.splitlines()` also cuts at a vertical tab, a form feed, U+0085, U+2028 and U+2029. JSON leaves U+0085, U+2028 and U+2029 raw inside a string (the logs and stores
write with `ensure_ascii=False`), so a record that holds one was cut in two and neither half read. The readers of those files cut at "\\n" now.

Covers:
  1. The helper: for ordinary text it returns what `splitlines()` returns (a differential over a table: empty, no trailing newline, a trailing newline, blank lines,
     "\\r\\n" endings, a lone newline); a string that holds each hostile character stays one line; only "\\n" cuts.
  2. Each reader, with a record that holds each hostile character in a field the writer does not fold: a transcript's last turn (said.transcript_error), the held store
     (held.add and held.count), the router's notice log (routing.record and routing.read), the router's own log (router._append, router._read) and the page keeper's
     turn read (pages.turn_activity). Each reader finds the record whole, and the neighbours of the record are read as before.

    tests/run-suite newline_lines        → exit 0 / 1"""
import json, os, pathlib, re, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="nll-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store", "state", "secrets", "brain"): (T / d).mkdir(parents=True)
sys.path.insert(0, STACK)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.core.lines import newline_lines
from stackshot.model import said
from stackshot.waits import held
from stackshot.router import routing
from stackshot.router import router as _router
from stackshot.projects import pages

HOSTILE = {"U+2028": " ", "U+2029": " ", "U+0085": "\x85", "vertical tab": "\x0b", "form feed": "\x0c", "file separator": "\x1c"}

# ================================================================ 1. the helper
for text in ("", "a", "a\n", "a\nb", "a\nb\n", "a\n\nb\n", "\n", "\n\n", "a\r\nb\r\n", "a\r\n\r\nb", '{"x": 1}\n{"y": 2}\n', "  a  \n b\n"):
    check(f"1 differential: {text!r} reads as splitlines() reads it", newline_lines(text) == text.splitlines(), (newline_lines(text), text.splitlines()))
for name, ch in HOSTILE.items():
    check(f"1 {name} inside a line is no line end", newline_lines(f"a{ch}b\nc{ch}\n{ch}d") == [f"a{ch}b", f"c{ch}", f"{ch}d"], newline_lines(f"a{ch}b\nc{ch}\n{ch}d"))
check("1 a lone carriage return is no line end (a record never ends at one: JSON escapes it)", newline_lines("a\rb\n") == ["a\rb"])

# ================================================================ 2. the readers
def tr(rows, name):
    f = T / name; f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"); return f

for name, ch in HOSTILE.items():
    # a transcript whose last turn ended in an API error that holds the character (the reader folds the text to one line of words)
    p = tr([{"type": "user", "message": {"content": "go"}},
            {"type": "assistant", "isApiErrorMessage": True, "message": {"content": [{"type": "text", "text": f"API Error: 400 first{ch}second"}]}}], f"t-{len(ran)}.jsonl")
    got = said.transcript_error(p)
    # U+0085 etc. are white space to `str.split()`: they fold to a space; vertical tab and form feed are escaped by JSON itself, so the record is whole under either cut
    check(f"2 said.transcript_error: the last turn's error with a {name} in it is read whole", got.startswith("API Error: 400 first") and got.endswith("second"), got)

    # the held store: a notice whose group id holds the character (the text and the sender are folded to one line, the id is not)
    key = f"sess-{len(ran)}"
    held.add(key, "closed", "a thing closed", sender="Dana", gid=f"g{ch}1")
    held.add(key, "closed", "another thing closed", sender="Dana", gid="g2")
    check(f"2 held: a notice whose group id holds a {name} is stored whole and counted with its neighbour", held.count(key) == 2, held.count(key))

    # the router's notice log: a label that holds the character
    proj = f"projects/nll{len(ran)}"
    n1 = routing.record(proj, kind="message", to="work-a", label=f"label{ch}one", who="Dana", text="first", pilot=True)
    n2 = routing.record(proj, kind="message", to="work-a", label="plain", who="Dana", text="second", pilot=True)
    got = {n["id"]: n for n in routing.read(proj)}
    check(f"2 routing.read: a notice whose label holds a {name} is read whole, and the one after it too", set(got) == {n1, n2} and got[n1]["label"] == f"label{ch}one", got)

    # the router's own log (the page-debt log, the live log, the calls log)
    lp = T / f"rlog-{len(ran)}.jsonl"
    _router._append(lp, {"call": "c1", "note": f"before{ch}after"}); _router._append(lp, {"call": "c2", "note": "plain"})
    got = _router._read(lp)
    check(f"2 router._read: a line whose field holds a {name} is read whole, and the one after it too", [d["call"] for d in got] == ["c1", "c2"] and got[0]["note"] == f"before{ch}after", got)

    # the page keeper's read of the turn: the prompt that opened it holds the character
    tp = tr([{"type": "user", "timestamp": "2026-06-09T00:00:00Z", "message": {"content": f"[anchor] a notice{ch}with a break"}},
             {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}], f"turn-{len(ran)}.jsonl")
    act = pages.turn_activity(str(tp))
    check(f"2 pages.turn_activity: a prompt with a {name} in it is the turn's start (an anchor notice reads as inbound)", act["start"] > 0 and act["inbound"] is True, act)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" + ("" if not fails else f"; FAILED: {len(fails)}"))
sys.exit(1 if fails else 0)
