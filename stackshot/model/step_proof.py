"""step_proof.py — a step of an item's `next` that names the event which completes it (the proof), and how the words of a step are read for one.

A step "release PR #4" is finished by one event: PR #4 going live. Before this, nothing tied the two, so the step sat open after the release and the item read
"doing" while its only work was done. A proof is the tie. Two kinds, each an event the server can see for itself:

    pr_merged <owner>/<repo>#<n>     the pull request is merged (GitHub says so; the done check's own read, `checks.pr_merged`)
    pr_released <owner>/<repo>#<n>   the pull request is merged AND live: its merge is in the last-good commit release.sh records and in the checkout's HEAD
                                     (`released_live.released_is_live`); this repository's pull requests, and those of a repository [released.repos] lists (live when their merge is an ancestor of that
                                     checkout's HEAD)

Where a step's proof comes from, in the order the server looks:
  1. The explicit form, `metadata.step_proof`: {<the step's key (steps.key): "pr_merged owner/repo#n" | "pr_released owner/repo#n">}, written by `update`/`create`'s `step_proof`
     parameter. The author states that this event completes the step: the step is ticked when it arrives, whatever the step's words say after it.
  2. The step's words, read by the patterns below. A step is a *pure* proof step only when the phrase is all the step does: "release PR #4", "release #4", "release <the PR's URL>",
     "merge PR #4", "merge #4", each optionally followed by one short parenthetical naming nothing to do ("(in its turn)") and a closing full stop, and nothing else in the step but its session prefix. Anything else (words after the phrase, words before it, a second phrase, a gate such as "(after #7)") makes the phrase a follow-up ("and verify the pages", ", restart x", " - check prod", "(needs an ok)", "then ...", "release PR #5 after release PR #4"): the step is never ticked by the words alone, the mover is told once
     that the event happened. When unsure, it is a follow-up. A *gate* ("once #4 is released ...", "when PR #4 is merged, ...", "after #4 lands", "release it after #4", the last
     only on a step that says "release") is a condition on the step, never its proof: it is never ticked, the mover is told once that the condition is met.
  Never matched: a negated or undecided phrase ("do not release PR #4 yet", "do not yet release", "cannot release", "Do NOT, before the freeze lifts, release", "don't merge #4", "pre-release #4", "decide whether to release PR #4"), a step that only mentions a PR ("review PR #4", "verify #4 is live"), "released"/"merged"
  after a PR that is not named by number or URL.

Pure functions of strings: no server import, so the server, the backfill tool and the tests share one copy of what a step's words say."""
from __future__ import annotations

import re
from typing import Any, Callable, Iterator, NamedTuple

PR_MERGED, PR_RELEASED = "pr_merged", "pr_released"
KINDS = (PR_MERGED, PR_RELEASED)
VERB = {PR_RELEASED: "release", PR_MERGED: "merge"}
WORD = {PR_RELEASED: "live", PR_MERGED: "merged"}          # what the notice says of the pull request

_NEG = re.compile(      # words before the verb, in the same sentence, that say the step is not (yet) doing it: "do not yet release", "cannot release", "Do NOT, before the freeze lifts, release", "pre-release", "decide whether to release"
    r"\b(?:not|never|no|cannot|can['’]?t|don['’]?t|doesn['’]?t|won['’]?t|shouldn['’]?t|without|whether|decide|decides|consider|should)\b|n['’]t\b|\bpre[\s-]*$", re.I)
_PREFIX = re.compile(r"\s*(?:[-*•]\s+|\d+[.)]\s+)?(?:\*\*)?[A-Za-z0-9][\w.\-]*(?: [\w.\-]+){0,2}(?:\s*\([^()\n]{0,40}\))?\s*:(?!//)(?:\*\*)?[ \t]*")      # the session prefix: "<name>:" or "<name> (role):", up to three words
_PAREN = re.compile(     # the only words after a phrase that leave it pure: a short parenthetical naming nothing to do
    r"(?:\s*\(\s*(?:in (?:its|his|her|their|the) turn|in turn|in order|queued)\s*\))?\s*\.?\s*", re.I)
_REF = r"(?:(?:PR|pull request)\s*)?#(\d+)(?!\d)"
_URL = r"(https?://github\.com/\S+?)"
_LEAD = r"(?:once|when|after|until|till|as soon as|if|now that)"
_HAS = r"(?:(?:is|are|has been|have been|gets|got|was|were)\s+)?"
_GATE_KIND = {"released": PR_RELEASED, "live": PR_RELEASED, "deployed": PR_RELEASED, "merged": PR_MERGED, "lands": PR_MERGED, "landed": PR_MERGED}
_GATE_WORD = r"(released|live|deployed|merged|lands|landed)\b"


def prefix_end(text: Any) -> int:
    """Where a step's words start after its session prefix ("ci-builder: ", "x (builder): "), 0 when it has none."""
    m = _PREFIX.match(str(text or ""))
    return m.end() if m else 0


def negated(text: Any, start: int) -> bool:
    """Does the sentence of `text` before position `start` (after the session prefix) say the verb at `start` is not being done: not, never, cannot, don't, without, pre-, whether, decide, consider, should…?"""
    t = str(text or "")
    lo = prefix_end(t)
    seg = re.split(r"[.;!?\n]", t[lo:start] if start >= lo else "")[-1]
    return bool(_NEG.search(seg))


class Proof(NamedTuple):
    """One event a step's words name. `n` is the number for "#n" (url ""), 0 for a URL form; `pure`: the phrase is all the step does; `via`: release | merge | gate."""
    kind: str
    n: int
    url: str
    pure: bool
    via: str


def phrases(text: Any, verb: str) -> Iterator[tuple[re.Match[str], int, str]]:
    """Every "<verb> PR #n" / "<verb> #n" / "<verb> <PR URL>" in `text` as (match, n or 0, the URL or ""); a negated one is left out. `verb` is "release" or "merge"."""
    t = str(text or "")
    for m in re.finditer(rf"\b{verb}\s+{_REF}", t, re.I):
        if not negated(t, m.start()):
            yield m, int(m.group(1)), ""
    for m in re.finditer(rf"\b{verb}\s+(?:(?:PR|pull request)\s+)?(https?://github\.com/\S+)", t, re.I):
        if not negated(t, m.start()):
            yield m, 0, m.group(1)


def is_sole(text: Any, m: re.Match[str]) -> bool:
    """Is the phrase `m` all the step does: the text is the session prefix, the phrase, at most one short parenthetical naming nothing to do, and a closing full stop, with nothing else (no second
    phrase, no gate, nothing before the phrase, no sub-lines)? When unsure, it is not."""
    t = str(text or "")
    return t[:m.start()].strip() == t[:prefix_end(t)].strip() and bool(_PAREN.fullmatch(t[m.end():]))


def gates(text: Any) -> Iterator[tuple[str, int, str]]:
    """The conditions a step's words state: (kind, n or 0, URL or "") for "once #n is released", "when PR #n is merged", "after #n lands", "until <URL> is merged", and, on a step that says
    "release", a bare "after #n" (read as released: a release waits for the one before it)."""
    t = str(text or "")
    seen: set[tuple[int, str]] = set()
    for m in re.finditer(rf"\b{_LEAD}\s+{_REF}\s+{_HAS}{_GATE_WORD}", t, re.I):
        if not negated(t, m.start()):
            seen.add((int(m.group(1)), "")); yield _GATE_KIND[m.group(2).lower()], int(m.group(1)), ""
    for m in re.finditer(rf"\b{_LEAD}\s+{_URL}\s+{_HAS}{_GATE_WORD}", t, re.I):
        if not negated(t, m.start()):
            seen.add((0, m.group(1))); yield _GATE_KIND[m.group(2).lower()], 0, m.group(1)
    rel = re.search(r"\brelease\b", t, re.I)
    if rel and not negated(t, rel.start()):
        for m in re.finditer(rf"\bafter\s+{_REF}", t, re.I):
            if (int(m.group(1)), "") not in seen:
                yield PR_RELEASED, int(m.group(1)), ""


def text_proofs(text: Any) -> list[Proof]:
    """Every proof a step's words name, in the order: release phrases, merge phrases, gates. A phrase is *pure* only when it is all the step does (`is_sole`)."""
    out = [Proof(kind, n, u, is_sole(text, m), VERB[kind]) for kind in (PR_RELEASED, PR_MERGED) for m, n, u in phrases(text, VERB[kind])]
    out += [Proof(kind, n, u, False, "gate") for kind, n, u in gates(text)]
    return out


def hits(proofs: list[Proof], kind: str, n: int, key: str, keyf: Callable[[str], str]) -> list[Proof]:
    """The proofs of `proofs` that name pull request `key` (#`n`) for the event `kind`. `keyf` turns a PR URL into its "owner/repo#n" key."""
    return [p for p in proofs if p.kind == kind and ((p.n == n and not p.url) or (p.url and keyf(p.url) == key))]


def pure_step(proofs: list[Proof], kind: str, n: int, key: str, keyf: Callable[[str], str]) -> bool:
    """Is the step, for this event, a pure proof step: it has a release/merge phrase for the PR and every phrase and gate naming it is pure (a gate never is)."""
    h = hits(proofs, kind, n, key, keyf)
    return bool(h) and all(p.pure for p in h)


def other_pure(proofs: list[Proof], kind: str, n: int, key: str, keyf: Callable[[str], str]) -> bool:
    """Is the step a pure proof step of some other pull request than `key`/#`n` (any kind)? Then it has nothing for the mover to do until that one's event."""
    for p in proofs:
        if p.pure and p.via != "gate" and not ((p.n == n and not p.url) or (p.url and keyf(p.url) == key)):
            return True
    return False


# ------------------------------------------------------------------------------------------------------ a delivery step with no proof
_DELIVER_EXTRA = ("ship", "deploy", "land")      # verbs beside release and merge that deliver a pull request; no proof phrase of their own, so only the explicit form ticks such a step


_FILLER = re.compile(r"(?:(?:then|next|now|first|finally|also|please|and)\b[\s,]*)*", re.I)      # words that may stand before the verb of a step that still opens with it


def leads(text: Any, start: int) -> bool:
    """Is the verb at `start` the step's own leading action: only the session prefix and a filler word (then, now, please…) before it? "review the release PR #7" and "wait for the release PR #7 to merge" are not."""
    t = str(text or "")
    return bool(_FILLER.fullmatch(t[prefix_end(t):start].strip()))


def delivers(text: Any) -> tuple[str, str]:
    """(the proof kind its verb suggests, the pull request as the step writes it: "#7" or a URL) for the step's leading action when it delivers a pull request: `release|ship|deploy PR #n` → pr_released,
    `merge|land PR #n` → pr_merged; a negated phrase, a step that only mentions a pull request (review, verify, wait for, check) and one whose delivery is not its opening verb deliver nothing. ("", "") when none."""
    t = str(text or "")
    found: list[tuple[int, str, str]] = []
    for verb in ("release", "merge"):
        found += [(m.start(), PR_RELEASED if verb == "release" else PR_MERGED, f"#{n}" if n else u) for m, n, u in phrases(t, verb)]
    for verb in _DELIVER_EXTRA:
        for m in re.finditer(rf"\b{verb}\s+{_REF}", t, re.I):
            if not negated(t, m.start()):
                found.append((m.start(), PR_MERGED if verb == "land" else PR_RELEASED, f"#{m.group(1)}"))
        for m in re.finditer(rf"\b{verb}\s+(?:(?:PR|pull request)\s+)?(https?://github\.com/\S+)", t, re.I):
            if not negated(t, m.start()):
                found.append((m.start(), PR_MERGED if verb == "land" else PR_RELEASED, m.group(1).rstrip(".,;)")))
    found = [f for f in found if leads(t, f[0])]
    if not found:
        return "", ""
    _, kind, ref = min(found)
    return kind, ref


def has_proof(text: Any, proofs: dict[str, Any], keyf: Callable[[Any], str]) -> bool:
    """Does a step carry a proof the server can tick it by: an explicit one stored under its key (`keyf(text)`, steps.key), or words that are all a release/merge phrase (a pure step)?"""
    return keyf(text) in (proofs or {}) or any(p.pure and p.via != "gate" for p in text_proofs(text))


def proof_gaps(steps: list[dict[str, Any]], proofs: dict[str, Any], opener: Callable[[Any], str], same: Callable[[str, str], bool], keyf: Callable[[Any], str],
               skip: Callable[[str], bool] = lambda nm: False, own: str = "", released: Any = ()) -> list[tuple[int, str, str]]:
    """[(the step's 1-based position in the checklist, the pull request it delivers, the proof to give it)] for every open step that delivers a pull request, has no proof, and has another session's open step
    after it: when its event happens nothing ticks it, so the session named on the step after it is never handed the item. `steps` is the checklist (steps.view), `proofs` metadata.step_proof, `opener(text)` the name
    that opens a step, `skip(name)` true for a name that is no session to hand to (the owner, nobody). A step with no opener, and a sub-step that names no one, is left out. `own` = this repository ("owner/repo"):
    a release of a URL that names another repository is given a pr_merged proof, since only this repository's pull requests are released, unless that repository is one of `released` (lower-case names: [released.repos])."""
    named = [(i, opener(s["text"])) for i, s in enumerate(steps) if s["status"] == "open" and opener(s["text"])]
    out = []
    for i, nm in named:
        kind, ref = delivers(steps[i]["text"])
        if not kind or has_proof(steps[i]["text"], proofs, keyf) or skip(nm):
            continue
        if any(j > i and not skip(nm2) and not same(nm, nm2) for j, nm2 in named):
            m = re.search(r"github\.com/([^/\s]+/[^/\s]+)/pull/\d+", ref)
            if kind == PR_RELEASED and own and m and m.group(1).lower() != own.lower() and m.group(1).lower() not in released:
                kind = PR_MERGED
            out.append((i + 1, ref, f"{kind} {ref}"))
    return out


# ------------------------------------------------------------------------------------------------------ the explicit form
EXPLICIT_HOW = ("step_proof=[{\"step\": <position or the step's exact first line>, \"proof\": \"pr_merged <owner>/<repo>#<n> | pr_released <owner>/<repo>#<n>\"}, …] "
                "(a bare #<n> or the PR's URL names a pull request too; \"proof\": \"none\" clears a step's proof; step_proof=\"none\" clears them all)")


class ProofError(ValueError):
    """A step_proof value the server refuses; the message says what to pass instead."""


def parse_spec(spec: Any) -> list[tuple[Any, str]] | None:
    """The `step_proof` parameter → [(step ref, proof text)], None when the call passes none, [] for "none" (clear all). Accepts a list of {"step", "proof"} or a JSON string of one."""
    import json
    if spec is None:
        return None
    if isinstance(spec, str):
        s = spec.strip()
        if not s:
            return None
        if s.lower() == "none":
            return []
        try:
            spec = json.loads(s)
        except ValueError:
            raise ProofError(f"step_proof {s[:80]!r} is not a list of steps and proofs. Pass {EXPLICIT_HOW}")
    if isinstance(spec, dict):
        spec = [spec]
    if not isinstance(spec, list):
        raise ProofError(f"step_proof takes a list of steps and proofs. Pass {EXPLICIT_HOW}")
    out: list[tuple[Any, str]] = []
    for e in spec:
        if not isinstance(e, dict) or "step" not in e or not str(e.get("proof") or "").strip():
            raise ProofError(f"each step_proof entry names a step and its proof ({e!r}). Pass {EXPLICIT_HOW}")
        out.append((e["step"], " ".join(str(e["proof"]).split())))
    return out


_PROOF_RX = re.compile(r"^(pr_merged|pr_released)\s+(\S+)$", re.I)


def split_proof(text: str) -> tuple[str, str]:
    """A proof as written ("pr_merged #4", "pr_released owner/repo#4", "pr_merged <URL>") → (kind, the PR ref as written); "none" → ("none", ""); refused with the forms otherwise."""
    s = " ".join(str(text or "").split())
    if s.lower() == "none":
        return "none", ""
    m = _PROOF_RX.match(s)
    if not m:
        raise ProofError(f"step proof {text!r} is not one of: pr_merged <owner>/<repo>#<n>, pr_released <owner>/<repo>#<n> (a bare #<n> or the PR's URL works too), none")
    return m.group(1).lower(), m.group(2)


def stored(kind: str, key: str) -> str:
    return f"{kind} {key}"


def read_stored(v: Any) -> tuple[str, str]:
    """A stored proof "pr_merged owner/repo#n" → (kind, key), ("", "") when it is none."""
    m = _PROOF_RX.match(" ".join(str(v or "").split()))
    return (m.group(1).lower(), m.group(2)) if m else ("", "")
