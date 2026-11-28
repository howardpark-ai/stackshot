"""glossary_line.py: the reply text of a save that went through the glossary (model/glossary_words.py): the rewrite line, then one line naming each word that stands for several terms.

The many-term line is a page string table text (keys `glossary.*`), in the language of the saved text: the English text when that language has no catalog. Never raises."""
from __future__ import annotations

from stackshot.model import glossary_words as _g
from stackshot.web import i18n as _i18n


def apply(subject: str, description: str, path: str | None = None) -> tuple[str, str, str]:
    """(subject, description, the text to add to the reply): single-term words rewritten, many-term words saved as written and named."""
    subject, description, line, unclear, lang = _g.apply(subject, description, path)
    try:
        t = lambda k, **f: _i18n.t(k, lang, **f)
        parts = [t("glossary.unclear", word=w, where=t(f"glossary.in.{where}"), terms=", ".join(terms[:-1]) + t("glossary.or") + terms[-1]) for w, terms, where in unclear]
        if parts:
            line += "\n" + "; ".join(parts)
    except Exception:  # noqa: BLE001 - the feature fails open
        pass
    return subject, description, line
