# Board pages and reads

A person reads the board's pages: the home page, projects, one project, one item, search results, closed items and audits. A session reads the same board through `brief`, `get` and `rules`.

## Sub-features

- `pages.reads`: `rules`, `brief` and `get` answer with the instance's own data.
- `pages.render`: each page answers 200 and shows the seeded item where it belongs.
- `pages.missing`: an item that does not exist answers 404.

## How to get to it (user POV)

- The routes `/`, `/projects`, `/projects/<slug>`, `/items/<id>`, `/search?q=<words>`, `/closed`, `/audits`.
- The tools `rules`, `brief`, `get`.

## Driving it with verify_app_check

Preconditions: the baseline. Command: `tests/run-suite verify_app_check pages`.

- Reads: `rules` returns the seeded rulebook line; `brief` returns text; `get` with `a1` shows `door fixture item`.
- Pages: `/`, `/projects/alpha`, `/items/a1` and `/search?q=fixture` answer 200 and show `door fixture item`; `/projects`, `/closed` and `/audits` answer 200.
- Missing item: `/items/a999` answers 404.

## Gotchas

- The seeded project belongs to no group, so `/projects` does not list it; look for its items on `/projects/alpha`.
- `[auth]` is off here, so every page is open. Who may read a page is covered by the sign-in and members suites, not by this journey.
- A 200 alone proves little: check the text the change is about with `app.shows`.
