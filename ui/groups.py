"""ui/groups.py — rows in one foldable subsection per scope: the one grouping and the one subsection markup that home's four lists and the Closed page (New and Last 14 days) all draw.

Why a module of its own: home and the Closed page showed their rows in two shapes (home a plain div per scope, Closed a scope heading with a heading per project under it). Both now
call this, so the order of the scopes, the heading, the count and the fold are one piece of code. Nothing here reads the store; render.py's Board says which scope an item is in
(Board.scope_groups) and how a row is drawn, and this puts them in the one shape.

A subsection is a native `<details class="fold sfold hscope" open>` whose `<summary>` holds the same `h3.iscope` the project page's lists use (the name and the count of its rows), then the
rows as one `ul.ir-rows`. It renders open: a viewer closes it by a tap, and nothing is remembered (home's fold script keeps no state; the live swap on home carries a subsection's open state over
by its data-fold key, so each key here names its list and its scope)."""
from __future__ import annotations

from ui.kit import esc, rows


def group(items, scope_of, order):
    """`items` grouped by scope → [(scope, [item])], the scopes in `order` (the configured scopes, team, lab, infra, say), each group keeping the order the items came in.

    scope_of(item) → (scope, rank), the rank the scope's place in `order` (len(order) for a scope that is not one of them). A scope with no item has no group. An item whose scope is not
    one of the configured scopes is not dropped: its scope's own name is a last group (several such, by name)."""
    groups = {}
    for it in items: groups.setdefault(scope_of(it), []).append(it)
    return [(sc, groups[sc, rank]) for sc, rank in sorted(groups, key=lambda g: (g[1], g[0] if g[1] >= len(order) else ""))]


def fold_block(key, title, count, body, opened=True, cls="fold sfold hscope"):
    """The one foldable heading: a native `<details>` whose summary holds `h3.iscope` (the title and its count), then `body` (html). `opened` False draws it closed.
    The scope subsections (fold, below) and the Projects page's Archived group are both this, so the heading, the count and the fold are one piece of markup."""
    return (f'<details class="{esc(cls)}" data-fold="{esc(key)}"{" open" if opened else ""}><summary><h3 class="iscope">{esc(title)} <span class="count">{count}</span></h3></summary>'
            + body + '</details>')


def fold(key, scope, lis, cls=""):
    """One subsection: the scope's name and the count of its rows (`lis`, the rows' `<li>` html) in the summary, the rows under it. `key` is its data-fold key (unique on the page)."""
    return fold_block(key, scope, len(lis), rows(lis, cls))


def sections(prefix, grouped, draw):
    """The subsections of one list: `grouped` is group()'s result, draw(item) → the item's `<li>`; the fold keys are `<prefix>.<scope>`."""
    return "".join(fold(f"{prefix}.{sc}", sc, [draw(x) for x in grp]) for sc, grp in grouped)
