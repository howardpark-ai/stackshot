"""model_cuts.py: the two cuts to the audit's and the stall pass's model calls, held in one place so each can be put back by editing one line here.

  AUDIT_MODEL_OFF   the audit's judgment kinds (audit_run.CHECKS_MODEL) that make no model call: no suspect is picked for them and no call is made. Every deterministic check for the same items
                    (the field checks, the filing pass, the wait-end and why-not-now filing kinds, the dates pass) is separate code and runs as before. A kind's old verdicts are dropped when the run
                    carries its record forward, so a "yes" is not sent again. To put a kind back, delete its name from the tuple; `()` is the old behavior.
  STALL_COLD_SKIP   True: the stall ladder's second step (the cold call, which asks the model who takes an item whose mover has had no turn) is not made; the item goes straight to the project's
                    builder, the step that follows it. False is the old behavior. The hand-off ladder's own cold call (`[model] cold_call`) is not touched.

See docs/audit.md ("The two cuts") and docs/stall-and-ladder.md."""
from __future__ import annotations

AUDIT_MODEL_OFF: tuple[str, ...] = ("unneeded-escalation", "obsolete-wait")
STALL_COLD_SKIP: bool = True
