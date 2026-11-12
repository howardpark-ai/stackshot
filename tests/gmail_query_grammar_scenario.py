"""Scenario test for the terms of a Gmail query anchor (stackshot/anchors/gmail_query.py) — pure: header fixtures, no Google, no server, no config.

`gmail:q:<terms>` matches the headers of each new mail. Covered:

  * every operator: a space and AND (both terms), OR, parentheses, `key:(a OR b)` for one key over several values, and a bare word (a subject term);
    AND binds tighter than OR (told apart from the other precedence by a query whose answer changes); nesting; a quoted phrase, also one that holds OR,
    a colon or a parenthesis; a lowercase `or` and `and` are words, not operators; matching ignores case; a missing header matches nothing.
  * the query as the matcher reads it (`describe`), the line the add reply shows.
  * a query that worked before the grammar means what it meant: a corpus of such queries is run against a verbatim copy of the old matcher over a grid of
    headers, and the answers are the same on every header.
  * a query the grammar refuses (and so the add refuses) names what is wrong in one line; the limits (query length, nesting) hold; nothing a Gmail user
    would not think twice about is refused (a Re: in a subject, a URL, a hyphenated word).
  * a stored query the grammar refuses keeps the meaning it always had (`matches` falls back to the old matcher), so an anchor stored before the grammar
    does not change.

    tests/run-suite gmail_query_grammar        → exit 0 / 1"""
import os, re, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, STACK)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.anchors import gmail_query as gq

def LEGACY(q, hdr):
    """The matcher before the grammar (anchorhub/gworkspace.py header_match), copied verbatim: the oracle for 'a query that worked means what it meant'."""
    terms = re.findall(r'\s*(?:(from|to|cc|subject|person):)?\s*("[^"]*"|[^\s"][^"]*?)(?=\s+(?:from|to|cc|subject|person):|$)', q.strip())
    if not terms: return False
    for k, v in terms:
        v = v.strip().strip('"').lower(); k = k or "subject"
        if not v: continue
        if k == "person":
            if not any(v in hdr.get(h, "").lower() for h in ("from", "to", "cc")): return False
        elif v not in hdr.get(k, "").lower(): return False
    return True

GRID = {
    "H1": {"from": "Pat Lee <pat@example.test>", "to": "ada@example.test", "subject": "Quarterly numbers"},
    "H2": {"from": "Sam <sam@example.test>", "to": "Pat Lee <pat@example.test>", "cc": "bo@example.test", "subject": "Re: anchor test notes"},
    "H3": {"from": "billing@vendor.test", "to": "ada@example.test", "subject": "Invoice 42 (March)"},
    "H4": {"from": "news@list.test", "cc": "pat@example.test", "subject": "War or Peace"},
    "H5": {},
    "H6": {"from": "Pat Lee <pat@example.test>", "to": "ada@example.test", "subject": "quarterly  numbers"},
    "H7": {"from": "x@y.test", "subject": "War OR Peace"},
    "H8": {"from": "Pat <pat@example.test>", "to": "bo@example.test", "cc": "sam@example.test", "subject": "Fwd: Quarterly numbers (final)"},
    "H13": {"from": "x@y.test", "subject": "Peace talks"},
}
def hit(q): return sorted(n for n, h in GRID.items() if gq.matches(q, h))
def says(name, q, *want): got = hit(q); check(f"{name}: {q}", got == sorted(want), got)

# ---- the operators
says("term", "from:pat", "H1", "H6", "H8")
says("term: to", "to:ada", "H1", "H3", "H6")
says("term: cc", "cc:bo", "H2")
says("term: person is from, to or cc", "person:pat", "H1", "H2", "H4", "H6", "H8")
says("term: a bare word is a subject term", "quarterly", "H1", "H6", "H8")
says("term: matching ignores case in the query and the header", "FROM-NOT-A-KEY OR subject:QUARTERLY", "H1", "H6", "H8")
says("term: a missing header matches nothing", "cc:pat", "H4")
check("term: an empty header set matches nothing", not gq.matches("subject:a", {}) and not gq.matches("person:a OR from:b", {}))
says("and: a space between keyed terms", "from:pat subject:quarterly", "H1", "H6", "H8")
says("and: AND is the same", "from:pat AND subject:quarterly", "H1", "H6", "H8")
says("and: three terms", "from:pat to:ada subject:numbers", "H1", "H6")
says("and: AND between bare words", "quarterly AND final", "H8")
says("and: plain words run together are one phrase, as they always were", "quarterly numbers", "H1", "H8")
says("and: …so two words that are not adjacent in the subject do not match as a phrase", "invoice march")
says("or: two values", "from:pat OR from:sam", "H1", "H2", "H6", "H8")
says("or: three terms", "from:billing OR cc:bo OR subject:war", "H2", "H3", "H4", "H7")
says("or: on different keys", "to:bo OR subject:invoice", "H3", "H8")
says("precedence: AND binds tighter than OR (a query whose answer would change)", "from:billing OR from:pat subject:numbers", "H1", "H3", "H6", "H8")
says("precedence: …also written with AND", "from:billing OR from:pat AND subject:numbers", "H1", "H3", "H6", "H8")
says("precedence: OR first, then AND", "from:pat subject:numbers OR from:billing", "H1", "H3", "H6", "H8")
says("precedence: parentheses change it", "(from:billing OR from:pat) subject:invoice", "H3")
says("parentheses: around the whole query", "(from:pat)", "H1", "H6", "H8")
says("parentheses: a group beside a term, in either order", "subject:numbers (from:pat OR from:sam)", "H1", "H6", "H8")
says("parentheses: two groups", "(from:pat OR from:sam) AND (subject:anchor OR subject:numbers)", "H1", "H2", "H6", "H8")
says("nesting: a group in a group", "from:pat AND (subject:final OR (subject:quarterly AND to:ada))", "H1", "H6", "H8")
says("nesting: deeper", "((((from:billing))) OR ((from:sam)))", "H2", "H3")
says("key group: one key over two values", "subject:(quarterly OR invoice)", "H1", "H3", "H6", "H8")
says("key group: is the same as the long form", "subject:quarterly OR subject:invoice", "H1", "H3", "H6", "H8")
says("key group: with another term after it", "from:(pat OR billing) to:ada", "H1", "H3", "H6")
says("key group: person", "person:(sam OR bo)", "H2", "H8")
says("key group: a group inside a key group", "subject:(invoice OR (war AND peace))", "H3", "H4", "H7")
says("key group: AND inside", "subject:(quarterly AND final)", "H8")
says("key group: a space between quoted values is an AND", 'subject:("quarterly" "numbers")', "H1", "H6", "H8")
says("key group: one value in it", "from:(pat)", "H1", "H6", "H8")
says("key group: a bare group with no key after a keyed term", "to:ada (quarterly OR invoice)", "H1", "H3", "H6")
says("quote: a phrase with a space", 'subject:"quarterly numbers"', "H1", "H8")
says("quote: a bare quoted phrase is a subject term", '"war or peace"', "H4", "H7")
says("quote: a quoted OR is text, not an operator (the mail with only peace in it does not match)", 'subject:"war OR peace"', "H4", "H7")
says("quote: …the same words with OR unquoted are an operator", "subject:war OR peace", "H4", "H7", "H13")
says("quote: …and a lowercase or in an unquoted phrase is text too", "subject:war or peace", "H4", "H7")
says("quote: …so is a lowercase and", "subject:war and peace")
says("quote: a quoted parenthesis is text", 'subject:"invoice 42 (march)"', "H3")
says("quote: a quoted colon is text", 'subject:"re: anchor"', "H2")
says("quote: key:value with a quoted value and an unquoted one", 'from:"pat lee" subject:numbers', "H1", "H6")
says("quote: phrases in an OR", '"war or peace" OR "invoice 42"', "H3", "H4", "H7")
says("value: runs to the next key, spaces kept", "subject:anchor test person:sam@example.test", "H2")
says("value: a double space inside is kept as typed", "subject:quarterly  numbers", "H6")
says("value: a colon in the value is text", "subject:re: anchor", "H2")
says("value: an address", "from:pat@example.test", "H1", "H6", "H8")
says("value: after a space following the key", "from: pat", "H1", "H6", "H8")
says("value: an attached key remainder and the next word are one phrase", "subject:Fwd: Quarterly", "H8")
says("value: a hyphen and a URL are text", "subject:well-known OR subject:https://x.test")
says("limits: twenty nested parentheses are read", "(" * 20 + "from:pat" + ")" * 20, "H1", "H6", "H8")

# ---- the reading the add reply shows
D = gq.describe
check("describe: a term", D("from:pat") == 'from contains "pat"', D("from:pat"))
check("describe: a bare word is a subject term, and the value is lower-cased", D("Invoice") == 'subject contains "invoice"', D("Invoice"))
check("describe: AND over OR is shown with the parentheses it reads as", D("a OR b AND c") == 'subject contains "a" OR (subject contains "b" AND subject contains "c")', D("a OR b AND c"))
check("describe: parentheses are kept where they change the reading", D("(a OR b) c") == '(subject contains "a" OR subject contains "b") AND subject contains "c"', D("(a OR b) c"))
check("describe: a key group is spelled out", D("from:(a OR b)") == 'from contains "a" OR from contains "b"', D("from:(a OR b)"))
check("describe: a phrase is one term", D("subject:anchor test person:sam") == 'subject contains "anchor test" AND person contains "sam"', D("subject:anchor test person:sam"))
check("describe: a quoted phrase", D('from:"Pat Lee"') == 'from contains "pat lee"', D('from:"Pat Lee"'))
check("describe: a query it cannot read is empty", D("(a") == "" and D("") == "", (D("(a"), D("")))

# ---- a query that worked keeps its meaning (the old matcher is the oracle)
OLD = [
    "from:pat", "to:ada", "cc:bo", "subject:quarterly", "person:pat", "quarterly", "Quarterly Numbers", "pat", "from:pat subject:quarterly", "from: pat", "from:  pat",
    "from:pat to:ada subject:numbers", "subject:anchor test person:sam@example.test", "subject:quarterly numbers", "subject:quarterly  numbers",
    'subject:"quarterly numbers"', '"quarterly numbers"', 'from:"pat lee" to:ada', 'from:"pat lee"', 'subject:"war or peace"', "subject:re: anchor", "subject:re:",
    "person:sam person:bo", "cc:bo person:pat", "from:pat@example.test", "from:billing@vendor.test", "subject:invoice 42", "subject:Fwd: Quarterly",
    "subject:war or peace", "subject:war and peace", "  from:pat  ", "FROM-NOT-A-KEY", "subject:well-known", "subject:https://x.test", "to:ada from:pat",
    "subject:a", "from:x@y.test", 'subject:"war OR peace"', "subject:Quarterly numbers cc:bo", "person:pat subject:quarterly numbers",
]
bad = [(q, [n for n, h in GRID.items() if gq.matches(q, h) != LEGACY(q, h)]) for q in OLD]
check("old: every query that worked before the grammar answers as the old matcher did, on every header", not [x for x in bad if x[1]], [x for x in bad if x[1]])
check("old: …and the corpus is read by the grammar itself (the fallback is not what keeps it)", not [q for q in OLD if gq.problem(q)], [q for q in OLD if gq.problem(q)])
check("old: the corpus is not trivial (some queries match some headers, none match all)", all(0 < len([1 for h in GRID.values() if LEGACY(q, h)]) < len(GRID) for q in ("from:pat", "person:pat", "subject:anchor test person:sam@example.test")))

# ---- a query the grammar refuses
REFUSED = [
    ("(from:a", "opening parenthesis is never closed"), ("(from:a OR from:b", "opening parenthesis is never closed"), ("from:a)", "closing parenthesis has no opening"),
    (") from:a", "closing parenthesis has no opening"), ("(a OR b) )", "closing parenthesis has no opening"), ("a OR", "OR has nothing after it"), ("a OR )", "OR has nothing after it"),
    ("(a OR)", "OR has nothing after it"), ("OR a", "OR has nothing before it"), ("a OR OR b", "OR has nothing before it"), ("a AND", "AND has nothing after it"),
    ("AND a", "AND has nothing before it"), ("a AND OR b", "OR has nothing before it"), ("a OR AND b", "AND has nothing before it"), ("()", "nothing inside"),
    ("a ()", "nothing inside"), ("subject:()", "subject:( ) has nothing inside"), ("from:", "from: has no value"), ("from: OR to:x", "from: has no value"),
    ("to:x from:", "from: has no value"), ("from: to:x", "from: has no value"), ("subject:(from:a)", "sits inside the parentheses of subject:("),
    ("subject:(a OR cc:b)", "sits inside the parentheses of subject:("), ("label:inbox", "label: is not supported"), ("from:a has:attachment", "has: is not supported"),
    ("after:2026/01/01", "after: is not supported"), ("in:inbox from:a", "in: is not supported"), ("LABEL:x", "LABEL: is not supported"), ("bcc:a", "bcc: is not supported"),
    ("fom:pat", "fom: is not a key the matcher knows"), ("From:pat", "From: is not a key the matcher knows"), ("xfrom:pat", "xfrom: is not a key"),
    ("-from:pat", "negation (-from) is not supported"), ("-pat", "negation (-pat) is not supported"), ("from:a -subject:b", "negation (-subject) is not supported"),
    ("-(a OR b)", "negation (-) is not supported"), ('-"a b"', "negation (-) is not supported"), ("{a b}", "{ } is not supported"), ("{from:a from:b}", "{ } is not supported"),
    ('"abc', "quotation mark is never closed"), ('from:"abc', "quotation mark is never closed"), ('""', "quoted phrase is empty"), ('subject:"  "', "quoted phrase is empty"),
    ("", "no terms"), ("   ", "no terms"), ("a(b)", "runs straight into"), ("subject:foo(bar)", "runs straight into"), ('a"b"', "runs straight into"),
    ('"a"b', "follows a closing quotation mark"), ("(a)b", "follows a closing parenthesis"), ("(a)(b)", "follows a closing parenthesis"), ('subject:a"b"', "runs straight into"),
    ("(" * 21 + "a" + ")" * 21, "nested more than 20"), ("a" * 1001, "longer than 1000"),
]
for q, why in REFUSED:
    p = gq.problem(q)
    check(f"refused: {q[:40]!r} says {why!r}", why in p and "\n" not in p and p, p)
ACCEPTED = ["from:pat", "Re: x", "https://example.test/x", "subject:Fwd:Quarterly", "well-known", "a - b", "subject:re:", "10:30", "(a)", "((a) OR (b))", "from:a OR from:b",
            "subject:(a OR b)", "to:ada (from:pat OR from:sam)", 'subject:"x (y)"', "orange android", "or and", "a" * 1000, "(" * 20 + "a" + ")" * 20,
            'from:(a OR "b c")', "http://x.test OR https://y.test", "Order #12", "a/b", "50% off", "q&a"]
check("accepted: ordinary text and every form above reads", not [(q[:30], gq.problem(q)) for q in ACCEPTED if gq.problem(q)], [(q[:30], gq.problem(q)) for q in ACCEPTED if gq.problem(q)])

# ---- a stored query the grammar refuses keeps the meaning it had
STORED = ["subject:foo(bar)", "(a OR b", "label:inbox", "From:pat", "fom:pat", "-from:pat", "{a b}", "a(b)", 'subject:"unclosed', "(from:pat)(subject:x)", "from:", "a OR", '""']
GRID2 = dict(GRID, H9={"subject": "foo(bar) baz", "from": "From:pat <x@y.test>"}, H10={"subject": "(a or b)"}, H11={"subject": "label:inbox"}, H12={"subject": "a or"})
diff = [(q, n) for q in STORED for n, h in GRID2.items() if gq.matches(q, h) != LEGACY(q, h)]
check("fallback: every query the grammar refuses answers as the old matcher did, on every header", not diff, diff)
check("fallback: …and the grammar does refuse them", all(gq.problem(q) for q in STORED), [q for q in STORED if not gq.problem(q)])
check("fallback: …so a stored `subject:foo(bar)` still matches a subject holding it", gq.matches("subject:foo(bar)", GRID2["H9"]) and not gq.matches("subject:foo(bar)", GRID2["H1"]))
check("fallback: an unclosed group reads as text, as before", gq.matches("(a OR b", {"subject": "a b"}) is False and gq.matches("(a OR b", {"subject": "x (a or b"}) is True)
check("fallback: the old matcher in the module is the one copied here", all(gq.legacy_match(q, h) == LEGACY(q, h) for q in OLD + STORED for h in GRID2.values()))

print(f"{len(ran)} checks, {len(fails)} failed")
sys.exit(1 if fails else 0)
