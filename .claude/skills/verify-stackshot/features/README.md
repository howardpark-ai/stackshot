# Stackshot verification map

What a user can do with stackshot, and how to drive it. Read this index, then the feature file that matches the change.

## Baseline preconditions

- A scratch instance that this run started (see [../SKILL.md](../SKILL.md), Launch). Never drive another instance.
- The seeded data: project `projects/alpha`, session `sparrow`, the open item `a1` with the subject `[home] door fixture item`.
- The doctor's checks pass.

## Driving conventions

- Each journey creates the items it needs and does not rely on another journey having run.
- Reach pages by route and forms by their class (`form.ianswer`, `form.iwatch`) and field names, not by position.
- Make new items with `sample(...)` for subject and description: the store refuses an item whose subject and first bullet do not open with a finished outcome.
- Run every command from the checkout root, through `tests/run-suite`.

## Proof and skip reporting

- Proof is the action and the resulting state: the tool call or request, the reply, the page text, the stored record.
- Name the feature ID and the entry point next to each result.
- Report an entry point that could not be reached, with the command and the unmet precondition. Do not count it as verified through another path.

## Feature entry contract

An H1 title, one paragraph on what the user sees, then exactly four H2 sections in this order: `Sub-features`, `How to get to it (user POV)`, `Driving it with verify_app_check` (opens with `Preconditions:`, then labeled bullets pairing an action with its command and the observable result), `Gotchas`.

## Features

- [Item lifecycle](./item-lifecycle.md): create, read, update and close an item through the tools, and see it on the pages (journey `item`).
- [Answer a decision](./answer-decision.md): a person answers an item's question from its page (journey `answer`).
- [Board pages and reads](./board-pages.md): the pages and the read tools on the seeded data (journey `pages`).

Not mapped yet: watch and mute, the For you list, the home page's inline answer forms, audits, runners, the search tool, the front door and members' sign-in (they have scenario suites in `tests/`).
