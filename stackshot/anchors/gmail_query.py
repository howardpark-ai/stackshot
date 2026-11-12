"""The terms of a Gmail query anchor (`gmail:q:<terms>`, `gmail:q@<mailbox>:<terms>`): the grammar, the check an add runs and the matcher the Gmail reader runs.

A term is `key:value` with a key of from, to, cc, subject or person (person = from, to or cc), or a bare value, which is a subject term. A value is a quoted
phrase or the words up to the next key, operator or parenthesis (so `subject:anchor test person:sam` is two terms). Matching is a case-insensitive substring of the
header. Terms combine with:

    a b          implicit AND between terms (at a key, a quoted phrase or a parenthesis; plain words run together form one phrase, as they always did)
    a AND b      AND
    a OR b       OR
    ( ... )      grouping
    key:(a OR b) the key applies to every term inside: the same as key:a OR key:b

AND binds tighter than OR. `OR` and `AND` are operators only in capitals, as in Gmail's own search; `or` and `and` are words. There is no negation and no
other Gmail operator (label:, has:, after:, ...): a query that uses one is refused when the anchor is added (`problem`), never accepted to match nothing.

The matcher before this grammar knew only a sequence of terms that all had to match. `matches` keeps that meaning exactly for a query the grammar cannot read
(a stored anchor whose text the grammar refuses, such as a parenthesis glued to a word): `legacy_match` is that matcher, unchanged."""
import re
from functools import lru_cache

KEYS = ("from", "to", "cc", "subject", "person")
# Gmail search operators the matcher has no header for: a query that uses one would match nothing, so it is refused (any other `word:value` is refused too, as an unknown key)
UNSUPPORTED = ("bcc", "label", "in", "is", "has", "after", "before", "older", "newer", "older_than", "newer_than", "category", "filename", "size", "larger", "smaller",
               "deliveredto", "list", "rfc822msgid", "replyto", "around")
MAX_QUERY = 1000      # characters; a longer query is refused (nothing legitimate is)
MAX_DEPTH = 20        # nested parentheses; the parser recurses once per level


class QueryError(ValueError):
    """A query the grammar cannot read; the message is one line that names what is wrong."""


_WORD_END = re.compile(r'[\s"()]')
_KEYLIKE = re.compile(r"([A-Za-z][A-Za-z0-9_]*):(.*)$", re.S)


def _plain(word: str, nxt: str) -> None:
    """A word that reads as something Gmail has and the matcher does not, or that runs into a quotation mark or parenthesis. `nxt` is the character after it."""
    if word == "-" and nxt in ("(", '"'):
        raise QueryError("negation (-) is not supported: the matcher has no NOT")
    if word.startswith("-") and len(word) > 1 and word[1].isalpha():
        raise QueryError(f"negation ({word.split(':')[0]}) is not supported: the matcher has no NOT")
    if word.startswith("{") or word.endswith("}"):
        raise QueryError("{ } is not supported: write OR between the terms")
    if nxt in ("(", '"'):
        raise QueryError(f"{word!r} runs straight into a quotation mark or parenthesis: put a space or a key (subject:) before it")


def _tokens(q: str) -> list[tuple]:
    """q → [(kind, text, start, end)], kind one of Q (a quoted phrase), LP, RP, OR, AND, KEY (text = the key), WORD. Raises QueryError."""
    out: list[tuple] = []
    i, n = 0, len(q)
    while i < n:
        c = q[i]
        if c.isspace():
            i += 1
        elif c == '"':
            j = q.find('"', i + 1)
            if j < 0:
                raise QueryError("a quotation mark is never closed")
            if j + 1 < n and not (q[j + 1].isspace() or q[j + 1] == ")"):
                raise QueryError("text follows a closing quotation mark with no space between them")
            out.append(("Q", q[i + 1:j], i, j + 1))
            i = j + 1
        elif c == "(":
            out.append(("LP", "(", i, i + 1))
            i += 1
        elif c == ")":
            if i + 1 < n and not (q[i + 1].isspace() or q[i + 1] == ")"):
                raise QueryError("text follows a closing parenthesis with no space between them")
            out.append(("RP", ")", i, i + 1))
            i += 1
        else:
            m = _WORD_END.search(q, i)
            j = m.start() if m else n
            word = q[i:j]
            nxt = q[j] if j < n else ""
            km = _KEYLIKE.match(word)
            if km and km.group(1) in KEYS:
                at = i + len(km.group(1)) + 1
                out.append(("KEY", km.group(1), i, at))
                if km.group(2):
                    _plain(km.group(2), nxt)
                    out.append(("WORD", km.group(2), at, j))
            else:
                if km and km.group(1).lower() in UNSUPPORTED:
                    raise QueryError(f"{km.group(1)}: is not supported: the matcher reads from:, to:, cc:, subject: and person: only")
                if km and km.group(2) and not km.group(2).startswith("//"):
                    raise QueryError(f"{km.group(1)}: is not a key the matcher knows (it reads from:, to:, cc:, subject: and person:, in lowercase); "
                                     "put the text in quotation marks to match it as text")
                _plain(word, nxt)
                out.append(("OR" if word == "OR" else "AND" if word == "AND" else "WORD", word, i, j))
            i = j
    return out


class _Parser:
    def __init__(self, q: str):
        self.q, self.toks, self.i, self.depth = q, _tokens(q), 0, 0

    def peek(self) -> str:
        return self.toks[self.i][0] if self.i < len(self.toks) else "END"

    def take(self) -> tuple:
        t = self.toks[self.i]
        self.i += 1
        return t

    def parse(self):
        if not self.toks:
            raise QueryError("the query has no terms")
        if self.toks[0][0] == "RP":
            raise QueryError("a closing parenthesis has no opening one")
        node = self.or_(None, "the query has no terms")
        if self.peek() == "RP":
            raise QueryError("a closing parenthesis has no opening one")
        return node

    def or_(self, key, need: str):
        parts = [self.and_(key, need)]
        while self.peek() == "OR":
            self.take()
            parts.append(self.and_(key, "OR has nothing after it"))
        return parts[0] if len(parts) == 1 else ("or", parts)

    def and_(self, key, need: str):
        parts = [self.unit(key, need)]
        while True:
            k = self.peek()
            if k == "AND":
                self.take()
                parts.append(self.unit(key, "AND has nothing after it"))
            elif k in ("KEY", "WORD", "Q", "LP"):
                parts.append(self.unit(key, need))
            else:
                break
        return parts[0] if len(parts) == 1 else ("and", parts)

    def unit(self, key, need: str):
        k = self.peek()
        if k == "END" or k == "RP":
            raise QueryError(need)
        if k in ("OR", "AND"):
            raise QueryError(f"{self.toks[self.i][1]} has nothing before it")
        if k == "KEY":
            name = self.take()[1]
            if key:
                raise QueryError(f"{name}: sits inside the parentheses of {key}:( ): write the keys outside, or one key for the whole group")
            n = self.peek()
            if n == "LP":
                return self.group(name, f"{name}:( ) has nothing inside")
            if n in ("Q", "WORD"):
                return self.value(name)
            raise QueryError(f"{name}: has no value")
        if k == "LP":
            return self.group(key, "( ) has nothing inside")
        return self.value(key)

    def group(self, key, empty: str):
        self.take()
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise QueryError(f"parentheses are nested more than {MAX_DEPTH} deep")
        if self.peek() == "RP":
            raise QueryError(empty)
        node = self.or_(key, empty)
        if self.peek() != "RP":
            raise QueryError("an opening parenthesis is never closed")
        self.take()
        self.depth -= 1
        return node

    def value(self, key):
        t = self.take()
        if t[0] == "Q":
            if not t[1].strip():
                raise QueryError("a quoted phrase is empty")
            return ("leaf", key or "subject", t[1].lower())
        end = t[3]
        while self.peek() == "WORD":
            end = self.take()[3]
        return ("leaf", key or "subject", self.q[t[2]:end].lower())


@lru_cache(maxsize=512)
def _compile(q: str):
    """(tree, None) for a query the grammar reads, (None, reason) for one it does not."""
    if len(q) > MAX_QUERY:
        return None, f"the query is longer than {MAX_QUERY} characters"
    try:
        return _Parser(q.strip()).parse(), None
    except QueryError as e:
        return None, str(e)


def problem(q: str) -> str:
    """"" for a query the matcher can evaluate, else one line naming what is wrong with it."""
    return _compile(str(q or ""))[1] or ""


def _leaf(key: str, text: str, hdr: dict) -> bool:
    if key == "person":
        return any(text in hdr.get(h, "").lower() for h in ("from", "to", "cc"))
    return text in hdr.get(key, "").lower()


def _eval(node, hdr: dict) -> bool:
    if node[0] == "leaf":
        return _leaf(node[1], node[2], hdr)
    if node[0] == "and":
        return all(_eval(x, hdr) for x in node[1])
    return any(_eval(x, hdr) for x in node[1])


def matches(q: str, hdr: dict) -> bool:
    """Whether a mail with the lower-cased headers `hdr` ({"from": ..., "subject": ...}) matches the query. A query the grammar cannot read keeps the meaning it had before the grammar."""
    tree, _why = _compile(q)
    if tree is None:
        return legacy_match(q, hdr)
    return _eval(tree, hdr)


def _show(node, top: bool = True) -> str:
    if node[0] == "leaf":
        return f'{node[1]} contains "{node[2]}"'
    s = (" AND " if node[0] == "and" else " OR ").join(_show(x, False) for x in node[1])
    return s if top else f"({s})"


def describe(q: str) -> str:
    """The query as the matcher reads it, one line (`from contains "pat" AND (subject contains "a" OR subject contains "b")`); "" for a query it cannot read."""
    tree, _why = _compile(str(q or ""))
    return "" if tree is None else _show(tree)


def legacy_match(q: str, hdr: dict) -> bool:
    """The matcher as it was before the grammar: every term must match, a value runs until the next key. Kept for the query `matches` cannot read."""
    terms = re.findall(r'\s*(?:(from|to|cc|subject|person):)?\s*("[^"]*"|[^\s"][^"]*?)(?=\s+(?:from|to|cc|subject|person):|$)', q.strip())
    if not terms:
        return False
    for k, v in terms:
        v = v.strip().strip('"').lower(); k = k or "subject"
        if not v: continue
        if k == "person":
            if not any(v in hdr.get(h, "").lower() for h in ("from", "to", "cc")): return False
        elif v not in hdr.get(k, "").lower(): return False
    return True
