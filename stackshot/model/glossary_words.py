"""glossary_words.py: a retired role word in an item's subject or description, put right when the item is saved.

The word list is a glossary file (`[glossary] terms` in the config; the same JSON a reply hook reads): its "avoid" entries that carry `hook: true` and a `regex` are the retired words, each with the
`use` terms that replace it. The matching is the reply hook's own (role-term-note.py): fenced and inline code, URLs, link targets, `>` quote lines and quoted spans of up to 200 characters are
skipped, then each regex is applied, so one list and one rule serve the board and the hook.

On a save (create and update, the subject and the description only), and never a refusal:
  * a word with one `use` term is rewritten to it, and the reply says which words were rewritten;
  * a word with two or more `use` terms, while the file's `ask_writer_when_unclear` is true, is never guessed and never refused: the text is saved as written and the reply gets one line naming the word
    and its candidate terms, in the language of the saved text (web/glossary_line.py: the page string table, keys `glossary.*`; the English text when the language has no catalog);
  * a word with two or more terms and `ask_writer_when_unclear` false is left as written, with no line;
  * no match, no file, no `[glossary] terms` setting or a file that cannot be read: the text is untouched.

Pure but for the config read and the file read (through filecache). No Hangul in this file: the words come from the glossary."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import filecache as _fc

MAX_QUOTE = 200
_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
_INLINE = re.compile(r"`[^`\n]+`")
_URL = re.compile(r"\S*://\S+")
_LINK_TARGET = re.compile(r"\]\([^)\s]*\)")
_QUOTE_LINE = re.compile(r"^[ \t]*>.*$", re.M)
_QUOTED = re.compile(r'"[^"\n]{0,%d}"|“[^”\n]{0,%d}”|‘[^’\n]{0,%d}’|「[^」\n]{0,%d}」'
                     r"|(?<!\w)'[^'\n]{0,%d}'(?!\w)" % ((MAX_QUOTE,) * 5))
_NOISE = (_FENCE, _INLINE, _URL, _LINK_TARGET, _QUOTE_LINE, _QUOTED)

_HANGUL = re.compile(r"[\uac00-\ud7a3]")      # the text is in the second language when it holds a Hangul letter (an escape: this file holds no Hangul)


def _noise_spans(text: str) -> list[tuple[int, int]]:
    """The spans of text the matching skips: what each noise pattern finds, the hook's order and kinds."""
    spans: list[tuple[int, int]] = []
    for rx in _NOISE:
        spans += [m.span() for m in rx.finditer(text)]
    return spans


def entries(path: str | None = None) -> tuple[list[dict[str, Any]], bool]:
    """(the retired-word entries, ask_writer_when_unclear); ([], False) with no file or one that cannot be read. An entry: word, regex (compiled), use (list of terms)."""
    p = str(_cfg.get("glossary", "terms", default="") or "") if path is None else path
    if not p:
        return [], False
    try:
        data = _fc.read_json(Path(p).expanduser())
        out = []
        for a in (data.get("avoid") or []):
            if a.get("hook") and a.get("regex") and a.get("use"):
                out.append({"word": str(a["word"]), "rx": re.compile(a["regex"]), "use": [str(u) for u in a["use"]]})
        return out, bool(data.get("ask_writer_when_unclear"))
    except Exception:  # noqa: BLE001 - a broken glossary never stops a save
        return [], False


def rewrite(text: str, ents: list[dict[str, Any]], ask: bool) -> tuple[str, list[tuple[str, str]], list[tuple[str, list[str]]]]:
    """(the text with each single-term word rewritten, [(word, term)] rewritten, [(word, terms)] that need the writer's choice). A match inside a skipped span stays as written."""
    spans = _noise_spans(text)
    todo: list[tuple[int, int, str]] = []; rewritten: list[tuple[str, str]] = []; unclear: list[tuple[str, list[str]]] = []
    for e in ents:
        hits = [m for m in e["rx"].finditer(text) if not any(a <= m.start() and m.end() <= b for a, b in spans)]
        if not hits:
            continue
        if len(e["use"]) >= 2:
            if ask:
                unclear.append((e["word"], e["use"]))
            continue
        todo += [(m.start(), m.end(), e["use"][0]) for m in hits]
        rewritten.append((e["word"], e["use"][0]))
    pieces, last = [], 0
    for s, t, term in sorted(todo):
        if s < last:
            continue
        pieces += [text[last:s], term]; last = t
    pieces.append(text[last:])
    return "".join(pieces), rewritten, unclear


def apply(subject: str, description: str, path: str | None = None) -> tuple[str, str, str, list[tuple[str, list[str], str]], str]:
    """(subject, description, the rewrite line "", the many-term words, the language of the text) of a save. Single-term words are rewritten and named in the rewrite line; each many-term word is
    (word, terms, where it stands: subject, description or both) and the text keeps it as written (the web layer words the line, stackshot/web/glossary_line.py). Never raises for the list."""
    try:
        ents, ask = entries(path)
        if not ents or not (subject or description):
            return subject, description, "", [], "en"
        done: list[tuple[str, str]] = []; unclear: dict[str, tuple[list[str], set[str]]] = {}; res = []
        for where, text in (("subject", subject), ("description", description)):
            new, did, unc = rewrite(text, ents, ask) if text else (text, [], [])
            res.append(new); done += did
            for w, terms in unc:
                unclear.setdefault(w, (terms, set()))[1].add(where)
        line = ""
        if done:
            words = "; ".join(f"{w} -> {t}" for w, t in dict.fromkeys(done))
            line = f"\n(glossary: rewrote a retired word in the subject or description: {words})"
        lang = "ko" if _HANGUL.search(res[0] + res[1]) else "en"
        return res[0], res[1], line, [(w, terms, "both" if len(wh) == 2 else next(iter(wh))) for w, (terms, wh) in unclear.items()], lang
    except Exception:  # noqa: BLE001 - the feature fails open: a fault here never stops a save
        return subject, description, "", [], "en"
