## param description
Deprecated, pass outcome_text. Still accepted for callers that predate it: what is passed here with a close is stored
as the outcome text and never replaces the item's description (a text equal to the stored description is ignored).

## description complete
Close an item; it works on an item on hold too. Right call (item_id is board#N, never the bare number):
complete(item_id="board#N", sender="my-x", outcome="done", reason="Export shipped in PR 12", outcome_text="- PR 12
merged\n- live on the box") (outcome_text: short `- ` bullets, every line `- ` included at most {{DESC_LINE_MAX}} characters); not
planned: complete(item_id="board#N", sender="my-x", outcome="dropped", reason="No longer needed", outcome_text="- The
export moved to another team"); replaced: complete(item_id="board#N", sender="my-x", outcome="superseded",
superseded_by="board#M", reason="Merged into board#M", outcome_text="- Scope moved to board#M"); outcome, reason and
outcome_text are all required. {{CLOSE_FORM}}A close settles no mover and ends no hand-off line: it drops the mover,
then and any wait, and a closed item shows no hand-off. Never delete items. The reply shows the closed item and lists
the project anchors that were scoped to this item and now have no open item left, for the project's builder, else its
-main agent, to keep (project-wide) or drop — nothing is removed by a completion. sender = your own session (name or
cse_… id) when you close an item you do not own; a session named in the item's needs always passes sender=<itself>, so
that the mover is told of the close. {{SENDER_MIRROR_STRIPPED}}

## description confirm
Mark an item still true, as it stands: confirm(item_id="board#N", sender="my-x") and it reads fresh again. An active
item reads stale after {{CALL_DAYS}} d without a state change or a confirm when it needs {{OWNER}}'s call,
{{AGENT_DAYS}} d on agent, {{EXTERNAL_DAYS}} d when it waits on others; an item on hold never does. Changes nothing
else: no field, no state clock, no page owed, nobody told. Stale means unverified, not wrong: re-read the item against
its project page, then confirm, update or complete it. sender = your own session (name or cse_… id). item_id = board#N
(a bare number N is read as board#N). {{SENDER_MIRROR_STRIPPED}}
