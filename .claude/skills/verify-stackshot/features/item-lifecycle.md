# Item lifecycle

A session creates an item on a project, reads it, changes its next step and closes it with how it ended. A person sees it on the item page and the project page while it is open, and on the closed page afterwards.

## Sub-features

- `item.refuse`: a create naming no existing project is refused and writes nothing.
- `item.create`: a create answers with the new item's id.
- `item.read`: `get` returns the subject and the next step.
- `item.update`: a new next step is stored and shown on the item page and its project page.
- `item.close`: `complete` closes the item and it appears on the closed page.

## How to get to it (user POV)

- A session calls the `create`, `get`, `update` and `complete` tools of the connector.
- A person opens `/items/<id>`, `/projects/<slug>` and `/closed`.

## Driving it with verify_app_check

Preconditions: the baseline. Command: `tests/run-suite verify_app_check item`.

- Refused create: `create` with `project="projects/none"` replies with a refusal that says the project `names no page`; the stored files are the same as before.
- Create: `create` with `project="projects/alpha"`, a next step and `mover="sparrow"` replies `created [<id>]`.
- Read: `get` with that id shows the subject and the step.
- Update: `update` with `next` is accepted; `app.item(id)` holds the new step; `/items/<id>` and `/projects/alpha` show it.
- Close: `complete` with `outcome="done"`, a `reason` and an `outcome_text` bullet is accepted; the stored status is `completed`; `/closed` shows the subject.

## Gotchas

- `update` with a new `next` keeps an earlier open step unless the call marks it done or dropped; the reply says so.
- Every write names its `sender`; the seeded instance's session is `sparrow`.
- A refusal can list several faults at once. Read all of it before changing the journey.
- Ids in new items start with the instance's own letter; take the id from the reply, never guess it.
