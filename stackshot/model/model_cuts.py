"""model_cuts.py: the cut to the stall pass's model calls, held in one place so it can be put back by editing one line here.

  STALL_COLD_SKIP   True: the stall ladder's second step (the cold call, which asks the model who takes an item whose mover has had no turn) is not made; the item goes straight to the project's
                    builder, the step that follows it. False is the old behavior. The hand-off ladder's own cold call (`[model] cold_call`) is not touched.

The audit's cuts are not here: a retired judgment kind is out of `audit_run.CHECKS_MODEL` and `audit_rubric.txt` (docs/audit.md, "Turning a check back on", says how each comes back).

See docs/stall-and-ladder.md."""
from __future__ import annotations

STALL_COLD_SKIP: bool = True
