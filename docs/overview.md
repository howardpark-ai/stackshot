# What stackshot is and how it fits together

What this page covers: what stackshot is, how one board write flows through the server, the hooks and the page debt, and what a typical deployment looks like. Back to the [README](../README.md).

stackshot is a coordination board for one person and the Claude sessions that work for them. Every session, whether a
Claude Code pane on one of your machines or a claude.ai or Cowork session in the cloud, reads and writes the same board
through one MCP connector. Each item belongs to a project page, and the board keeps a ledger of which session still owes
its page an update, so the pages stay the place a fresh session can pick up from. Optionally, anchor-hub watches external
things (Slack channels, Notion pages, Drive files, Gmail threads, GitHub issues) on behalf of a project and drops a
one-line notice into the sessions that care. It runs on one Linux box with systemd; other machines run a small client.

## How a write flows

1. A session calls `create`, `update` or `complete` through the connector, signed in with Google.
2. The server checks the gates: subject prefix, description shape (short `- ` bullets), next lines, an existing project page, the enums, the date, an owner.
3. It allocates the id, writes the item file and, for a state-changing write, records a page debt against the writer.
4. About five seconds later the publisher renders `board.md` and the site, commits the store and pushes the data repository.
5. The board at `/` and the next `brief` show the change.
6. In the writer's pane, the PostToolUse hook (`stackshot/projects/pages.py touch`) remembers which page the write belongs to.
7. At the next prompt `stackshot/projects/pages.py nag` reminds the session if the page has not changed; at the turn's end `stackshot/projects/pages.py check` nags or blocks once.
8. The debt settles by itself when the page is newer than the write; for a page's keeper only a change to its current state counts.
9. After `page_rule.grace_minutes` the server refuses that session's next state-changing write until the page is updated.
10. Another session's write on a project page is also charged to the page's keeper (the router holds the notice and passes the page update to the agent that keeps the page). With `[pilot] writer_owes_page = true` the writer owes that page update itself (its Current state; any page write for a next-only change or a hold) and is never refused for it; still missing after `[page_rule] grace_minutes`, it moves to the keeper with the board notice. Debts that move to one keeper in the same tick go in one message, each with its own notice (the turn rule's fourth build); a debt is never held back for that, so it still moves at the first tick past the grace. The same goes for wakes: the items one wake pass releases for a session reach it in one message.
11. The server names a background agent in an item's needs when a message hands the item to it or when it updates or closes the item. A message never leaves the item with a second mover: it names the agent only when the model guards would not refuse the needs that result (`model_guards.second_mover_in`: a background agent of the item's project is never counted, any other session counts, and decision beside a session counts) or when the item stores another session as its mover, and otherwise the reply says in one line who already moves the item and that `update(mover=<agent>)` hands it over, with the item as it was (`[model] one_mover = false` turns the check off). `[pilot] never_named` lists the background agents it never names this way, for mandates that never work items (e.g. `["my-audit"]`: the daily board audit); they can still be named by hand with `needs=`.
12. Every save also settles the item's `activity` clock (`stackshot/model/activity.py`, stamped in `stackshot/service/writes.py`'s `save`): the time something real last happened on the work. A session's or the owner's write (create, update, a step, an answer or comment; the owner's GitHub comment counts at its own time, never after now and never before the clock already read), a message written onto the item and an event on one of its anchors (a step its proof ticked, a done check met) move it; a bare `confirm` (which moves `confirmed` only), a write by the audit (its agent, its push label, the instance's own name, the router's ruling name, the migration's label) and the server's own bookkeeping (a wake, a nudge of the stall or hand-off ladder, a repair) do not, so a nudge never resets the clock that decides whether to nudge. An item from before the field has none and reads as its last state change or update; its first save that does not count seeds the field from that value, and no pass rewrites the store. Nothing reads the clock yet and no page or tool text shows it.

## A typical deployment

A typical instance runs on one Linux server box that hosts the server, the publisher, anchor-hub and most Claude Code panes,
with further client machines (Linux or Windows). Its page store can be a gbrain brain whose pages are mirrored to a GitHub
repository; `paths.brain` points at the mirror's checkout and `gbrain.mirror_url` at GitHub. A tunnel or reverse proxy carries
the public name, with an access gate in front of the board. sala, a separate tool, can operate the fleet of sessions (spawning,
relaunching, the CLI updates) and is named as the fleet operator; it plugs in through the keys of [The fleet tool](fleet-tool.md#the-fleet-tool).
An MCP portal is a second connector path to the same tools, through the portal's machine token.
