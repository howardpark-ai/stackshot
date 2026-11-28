---
name: verify-item-phase
description: Model-check that a closed item stores no `phase` and no `waits_on`, with TLC (TLA+), against the real save-time stamp in stackshot/service/stamp.py. Use when a change touches `_phase_stamp`, `_stamp_values`, `model.stamp_values`, `model.shown_pair`, or how a close, a reopen or a save writes `metadata.phase` / `metadata.waits_on`.
---

# Verify that a closed item stores no phase

**The property.** An item that is closed stores neither `metadata.phase` nor `metadata.waits_on`, whatever it stored while it was open and whatever the save that closed it carried.

**The harm if it breaks.** The documented model (`docs/item-model.md`, the stored phase) is that a closed item is dead and stores neither key, and the close is what drops them. The readers that go through `model.stored_phase` ignore a closed item's keys, but a closed item that kept `phase: waiting` and a kind would sit in the store as a waiting item for any reader of the raw file (a count, a script, an audit that reads `metadata`), and nothing would clear it: the phase sweep leaves closed items alone.

## Run

Where tests run (the way `docs/development.md` sends them, not an interactive work session), from the root of the checkout under test:

```sh
.claude/skills/verify-item-phase/check; echo "exit=$?"
```

Exit 0: the property holds. Exit 1: TLC printed a counterexample. Exit 2: the check could not run (no java, no network on the first run, a failed extraction). It needs `java` 17 or later and `uv`. The first run fetches TLC `v1.8.0` (`tla2tools.jar`, pinned by sha256 in `check`) into `${XDG_CACHE_HOME:-~/.cache}/stackshot/tlc`. A run takes a few seconds. Where a machine sends its test runs elsewhere (`docs/development.md`), run the command through that route.

Read a result with the `/statechart` skill: it shows a counterexample as the shortest path in plain words, and a pass as a chart of how an item moves between open and closed.

## How the spec is tied to the code

`spec/ItemPhase.tla` models an item as four values: its `status` (open or closed), what its fields read as (`shown`: alive, waiting on a time, waiting on a relay), and the stored `phase` and `waits_on`. Its actions are a save that changes what the fields read as, the close, the reopen, and the clock moving what an open item's fields read as with no save.

The spec never says what a save stores. `extract_stamp.py` asks the code: for each of the 24 cases (status x stored pair x shown reading) it builds an item, runs the real `stamp._phase_stamp` on it and reads back the two keys. It writes the answers as `StampTable.tla`, which `check` puts beside the spec on every run (nothing generated is committed, so it cannot drift). The single stand-in is `stamp._stamp_values`, which derives the shown model from the item's fields and needs a store; it is replaced by a Model built in the script and passed through the real `model.stamp_values` and `model.shown_pair`. So a change to the closed-item branch of `_phase_stamp`, to `stamp_values` or to `shown_pair` changes the table and therefore TLC's answer.

Covered code (confirmed against the spec at commit `fe7e5dc59aab836139b1e571594a95b06518f4d2`):

| File | Function | Role in the model |
| --- | --- | --- |
| `stackshot/service/stamp.py` | `_phase_stamp` | what every save stores (run as is) |
| `stackshot/service/stamp.py` | `_stamp_values` | the derivation of the shown model (stood in for) |
| `stackshot/model/model.py` | `stamp_values`, `shown_pair` | phase and kind from a shown model (run as is) |

## Not covered

- The kinds of wait are two (`time`, `relay`) of the six, and the domain of stored pairs is the four a save can leave. The branch under test does not look at the kind.
- `stamp._stamp_one` (the stamp pass and the phase sweep) refuses a closed item before writing; it is not modeled. A writer that bypasses `writes.save` and `_phase_stamp` is not modeled either.
- The derivation of what an item's fields read as (`model.derive`, `model.view`) is not checked: the spec treats it as an input that can change at any time.
- A pass covers this model, not the whole system.

## When it fails

1. A counterexample is a short path, for example: an open item stores `phase: alive`; it is closed; the closed item still stores `phase: alive`. Replay it on the real code: save an open item that stores the pair through `writes.save` with `status` set to `closed`, then read `metadata`.
2. If the replay shows the keys, it is a real bug: fix `_phase_stamp` (or whatever now writes the pair), not the property.
3. If the replay does not, the model is wrong: fix the extraction or the spec, and say so in the PR.

## When the change is intended

If the property itself changes (a closed item is meant to keep a phase), change `ClosedStoresNone` in `spec/ItemPhase.tla` and the sentence at the top of this file together. If `_phase_stamp` gains a new input that decides the stored pair, add it to the cases in `extract_stamp.py` and to the variables of the spec. Then run the check, and run the mutation below to see that it can still fail. Move the commit in *Covered code* forward only after you confirm that the spec and the table describe the code at the new commit. If `git diff <that commit>.. -- stackshot/service/stamp.py stackshot/model/model.py` shows changes in the covered functions that nobody rechecked, the verification is out of date.

## Prove that it can fail

In a scratch worktree (never the production checkout), make a closed item keep its keys: in `_phase_stamp`, delete the two `meta.pop` lines in the `status != "open"` branch, leaving `return`. Run `check`: it must exit 1 and print `Invariant ClosedStoresNone is violated`, with a two-state path (an open item that stores a phase, then `Close`, still storing it). Restore the lines and it must exit 0 again.
