"""Scenario test for the write gate that refuses an option label opening with a lone letter — fixture data, no live store, no network, no server process (the gate is
called in-process, on a temporary config).

The board letters a decision's options itself (A, B, C by place in the list), so a label that opens with a letter of its own can cross the board's: the card
lettered A would read "B full panel". The gate (wait_gates._gate_options, over option_labels.lone_letter_lead) refuses such a label on a new write and says why.

Covers, one group each: a letter followed by a separator (`A: x`, `A) x`, `A. x`, `A - x`, an em dash, the board's own middle dot with the articles A and I too), a letter in parentheses, a bare letter, a
lone Hangul syllable then `)`, `.` or `:`, the prefixes Option / Choice / Design / Mockup / Variant / Alt / Alternative / Version / Layout / Style (and Plan with a separator) with any white space after them,
and the labels that must pass (a letter then a plain word, as in "A one-line strip", "I think so", "B full panel", "X Corp", a letter then a Hangul word spaced or not, a lower-case article after a prefix,
hyphenated and dotted words such as X-ray and U.S. plan, a letter in parentheses with no space after it, an ordinary label); the refusal text carrying its reason, its example and the order the letters
follow; a list of three with a label shaped like the board's own lettering; the create tool refusing the same label with the same text; an accepted label still matching the ask's Recommend part
(no note), a stored option read back unchanged; the cold call's rubric telling its model a label carries no letter.

    tests/run-suite option_label_letter        → exit 0 / 1"""
import json, os, re, sys, pathlib, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="optletter-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "state/s1", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text("{}")
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server  # noqa: F401  (wires the write hooks the gate reads)
from stackshot.service import wait_gates as _wg
from stackshot.model import option_labels as _ol
from stackshot.model import decision_gates as _dg
from fastmcp.exceptions import ToolError


def opts(label, rec_label="Keep"):
    """Two options, the first with the label under test (recommended), the second an ordinary one."""
    return [{"label": label, "line": "Take the first way and go on.", "recommended": True}, {"label": rec_label, "line": "Take the second way and wait.", "recommended": False}]


def gate(label):
    """"" when the label passes the options gate, else the refusal text."""
    try:
        _wg._gate_options(opts(label)); return ""
    except ToolError as e:
        return str(e)


REFUSED = {
    "separator": ["A: one-line strip", "B: full panel", "c: x", "A) strip", "B) full panel", "A. strip", "B. Full panel", "A - strip", "B - full panel", "A — strip", "B—full panel", "A - ", "C: ", "A : strip", "A – strip", "I: ship", "A- strip", "A.", "Design B.", "Version A.", "b."],
    "the board's own middle dot, articles included": ["A · Beta", "B · Full panel", "I · x", "a · x", "b·x", "A ·", "A· x"],
    "parentheses": ["(A) strip", "(b) full panel", "(C)"],
    "bare letter": ["A", "B", "I", "a", "z"],
    "a Hangul list syllable then ) . or :": ["\uac00) x", "\ub098. x", "\ub2e4: x", "\uac00 ) x", "(\uac00) x", "(\ub098)", "\ub2e4 - x", "\ub2e4 \u00b7 x"],
    "prefix": ["Option A", "Option C: strip", "option b", "Option B full panel", "Choice B", "choice c: x", "Choice A strip", "Design A", "Design B full panel", "Mockup C", "Mockup b: x", "Mockup B - full", "Option (A)", "Design I think", "Option A) x"],
    "the other designating words": ["Variant B", "Variant B: full panel", "variant c", "Alt B", "Alt C full", "Alternative B", "Version B", "Layout C", "Style B", "Style b: x", "Plan B: x", "Plan B) x", "plan c - x", "Plan A. x", "Plan A · x"],
    "a prefix, then any white space": ["Option B\tfull", "Option B\u00a0full", "Option B\u3000full", "Option\tC", "Option\u00a0C", "Design\u00a0A strip", "Mockup\u3000B", "Variant\tB", "Option  B full"],
}
ACCEPTED = {
    "the articles A and I with a word": ["A one-line strip", "A full panel", "I think so", "I will wait", "A new way"],
    "a letter then a plain word, no separator (an article, an initial, a name)": ["a strip", "b full panel", "c level", "B full panel", "C level", "X marks the spot", "D plan", "X Corp", "K Pop", "E Ink", "V plan", "B Smith"],
    "a letter then a Hangul word, spaced or not, judged alike": ["C\ubc29\uc2dd", "C \ubc29\uc2dd", "X \ud50c\ub79c", "A \ubc29\uc2dd", "A\uc0ac", "B\uc548"],
    "a single Hangul syllable alone, or before a word": ["\uac00", "\ub098 \uc548", "\ub2e4\uc74c"],
    "a Hangul word of one syllable that is no list syllable (yes, no), then a separator": ["\uc608: \uc9c4\ud589", "\uc608 - \uc9c4\ud589", "\ub124. \uc88b\uc544\uc694", "\uc608) \uc9c4\ud589", "(\uc608) \uc9c4\ud589", "\uc608", "\uc548: \ub300\uae30"],
    "a letter in parentheses with no space after it": ["(a)x", "(S)ave", "(B)eta", "Option (A)x", "Design (b)y", "(\uac00)x"],
    "lower-case article after a prefix": ["Design a strip", "Mockup a one-line strip", "Option a la carte", "Choice a or b"],
    "the designating words used as words, and a plan named by letter": ["Plan B", "Plan B full panel", "plan a la carte", "Alt Rock", "Style Guide", "Layout Tool", "Version 2", "Alternative energy", "Variant"],
    "a hyphen or dot that is part of a word": ["X-ray", "A-frame", "B-tree plan", "T-shirt", "K-12", "U.S. plan", "A.I. tools", "E-mail", "B2B", "A–Z index", "A -x"],
    "an ordinary label": ["Approve", "Decline", "Cut", "One-line strip", "Full panel", "Option", "Optional B", "Optionally C d", "Design", "Choice: A", "Option: C", "Park until Monday", "Bigger panel", "Alpha"],
}

# ---- 1. refused, per rule
for rule, labels in REFUSED.items():
    for lab in labels:
        e = gate(lab)
        check(f"refused ({rule}): {lab!r}", e.startswith("Refused: option 1 ") and "opens with a lone letter" in e, e)

# the fourteen syllables Korean lists run in, each as a marker with each of the endings
LIST_SYLLABLES = "\uac00\ub098\ub2e4\ub77c\ub9c8\ubc14\uc0ac\uc544\uc790\ucc28\uce74\ud0c0\ud30c\ud558"
check("the Hangul list syllables are the fourteen of the consonant order", len(LIST_SYLLABLES) == 14 and len(set(LIST_SYLLABLES)) == 14, LIST_SYLLABLES)
for ch in LIST_SYLLABLES:
    for form in ("{c})", "{c}. x", "{c}: x", "({c}) x", "{c} - x"):
        lab = form.format(c=ch); e = gate(lab)
        check(f"refused (a Hangul list syllable, {lab!r})", e.startswith("Refused: option 1 ") and "opens with a lone letter" in e, e)
# any other syllable (yes, no, and others across the block) is a word, whatever follows it
for ch in "\uc608\ub124\uc751\uc548\ub0b4\ub2f5\ud574\uac01\ud7a3\ub2eb":
    check(f"accepted (a Hangul syllable that is no list syllable, {ch!r}: and ) and . then a word)", all(gate(f"{ch}{s} x") == "" for s in (":", ")", ".")), [gate(f"{ch}{s} x") for s in (":", ")", ".")])

# ---- 2. accepted, per rule
for rule, labels in ACCEPTED.items():
    for lab in labels:
        e = gate(lab)
        check(f"accepted ({rule}): {lab!r}", e == "", e)
        check(f"accepted ({rule}): {lab!r} is stored as given", _wg._gate_options(opts(lab)) == [{"label": lab, "line": "Take the first way and go on.", "recommended": True}, {"label": "Keep", "line": "Take the second way and wait.", "recommended": False}], lab)

# ---- 3. the refusal says why, in plain words, and what to do instead
e = gate("B: full panel")
check("the refusal names the option, its label and the opening it objected to", "option 1 (B: full panel)" in e and "(B:)" in e, e)
check("…says the board letters the options itself", "The board letters the options itself" in e, e)
check("…says to name a mockup's designs by name and use the same words in the mockup and the options", "Name each design of a mockup by name" in e and "same words in the mockup and in the options" in e, e)
check("…carries an example of the fix", 'label="One-line strip"' in e, e)
check("…says the letters follow the order of the list the session gives, and never tells it to put the recommended option first",
      "(A, B, C by place in the list you give)" in e and "recommended one first" not in e and "reorder" not in e, e)
e2 = None
try:
    _wg._gate_options([{"label": "Keep", "line": "x", "recommended": True}, {"label": "Option C", "line": "y", "recommended": False}])
except ToolError as ex:
    e2 = str(ex)
check("…and names the place of a later option (option 2)", e2 is not None and e2.startswith("Refused: option 2 (Option C)"), e2)
check("a refused label is refused whatever the case or the surrounding spaces", gate("  b: x  ") != "" and gate("OPTION B") != "" and gate("\tB: full") != "")

# ---- 4. the other label checks keep their order and text
check("a label with a link is still refused by the link check", "carries a link" in gate("Keep [x](http://a.b)"), gate("Keep [x](http://a.b)"))
check("a too-long ordinary label is still refused by the length check", "is longer than" in gate("Keep " + "x" * 60), gate("Keep " + "x" * 60))
try:
    _wg._gate_options([{"label": "Keep", "line": "x", "recommended": True}, {"label": "keep", "line": "y", "recommended": False}]); dup = ""
except ToolError as ex:
    dup = str(ex)
check("…the same label twice: the same-label refusal", "two options are labelled" in dup, dup)

# ---- 5. an accepted label still matches the ask's Recommend part
ASK = "Decide: which strip to build · Recommend: A one-line strip · Stakes: the page layout waits either way · By: no date"
stored = _wg._gate_options([{"label": "A one-line strip", "line": "Draw a single line above the cards.", "recommended": True}, {"label": "Full panel", "line": "Draw a panel under the title.", "recommended": False}])
meta = {"ask": ASK, "options": stored}
check("Recommend names the recommended label exactly: no note from the write path", _dg._options_note(meta) == "", _dg._options_note(meta))
check("…and a Recommend that names the other option speaks (the match is live, not skipped)", _dg._options_note({"ask": ASK.replace("Recommend: A one-line strip", "Recommend: Full panel"), "options": stored}) != "", _dg._options_note({"ask": ASK.replace("Recommend: A one-line strip", "Recommend: Full panel"), "options": stored}))

# ---- 6. the tool text teaches the rule
from stackshot.web.tools import text as _wt_text
OPT_TEXT = _wt_text._T.param("OPTIONS")
check("the option parameter's text says a label never opens with a lone letter, that the board letters the options, and, with a mockup linked, that options are drawn by name in the order given",
      "never opens with a lone letter" in OPT_TEXT and "the board letters options itself" in OPT_TEXT and "with a mockup linked" in OPT_TEXT and "in the order given" in OPT_TEXT and "name them as the mockup does" in OPT_TEXT, OPT_TEXT[-260:])

# ---- 7. the helper itself
check("lone_letter_lead returns the opening it found, stripped", _ol.lone_letter_lead("B: full panel") == "B:" and _ol.lone_letter_lead("Option C") == "Option C" and _ol.lone_letter_lead("Approve") == "", (_ol.lone_letter_lead("B: full panel"), _ol.lone_letter_lead("Option C")))
check("…and an empty or missing label has none", _ol.lone_letter_lead("") == "" and _ol.lone_letter_lead(None) == "")

# ---- 8. a label shaped like the board's own lettering on a list of three: the card for "A · Beta" would be read as place A, whose label is Beta
def gate_list(*labels):
    """"" when a list of these labels (the first recommended) passes the options gate, else the refusal text."""
    try:
        _wg._gate_options([{"label": lab, "line": f"Take way {i}.", "recommended": i == 0} for i, lab in enumerate(labels)]); return ""
    except ToolError as e:
        return str(e)


for lab in ("A · Beta", "I · Beta", "a · Beta", "B · Beta"):
    e = gate_list("Beta", lab, "Gamma")
    check(f"three options Beta, {lab!r}, Gamma: the second is refused, naming its place", e.startswith(f"Refused: option 2 ({lab}) opens with a lone letter"), e)
check("…the same three options without the lettered shape pass", gate_list("Beta", "Alpha", "Gamma") == "", gate_list("Beta", "Alpha", "Gamma"))

# ---- 9. the cold call's rubric tells the model its labels carry no letter, since its options go through the same gate
from stackshot.model import cold_call as _cc
check("the cold call's rubric says a label is a name with no letter in front", "A label is a name with no letter in front" in _cc.RUBRIC, _cc.RUBRIC[-300:])
check("…and the stall call, which never asks, is unchanged", "A label is a name" not in _cc.STALL_RUBRIC)

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks FAILED"); sys.exit(1)
print(f"ok: {len(ran)} checks"); sys.exit(0)
