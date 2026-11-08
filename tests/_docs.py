"""tests/_docs.py: the text of the docs pages the suites read (a module, not a suite).

The README is a short guide; the detail it once held is in docs/ pages, one per topic (docs/README.md lists them). A suite that checks a
documented sentence reads the page that holds it: `page("audit")` is docs/audit.md. `pages()` is every docs page joined, for a check that
asserts a sentence is nowhere in the docs, or that the docs as a whole name something."""
import pathlib

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"


def page(name):
    """The text of docs/<name>.md (name without the extension)."""
    return (DOCS / f"{name}.md").read_text(encoding="utf-8")


def pages():
    """Every docs page, sorted by file name, joined with a blank line."""
    return "\n\n".join(p.read_text(encoding="utf-8") for p in sorted(DOCS.glob("*.md")))
