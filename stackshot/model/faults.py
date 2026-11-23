"""model/faults.py — one refusal for every fault a write's form can find, not the first one alone.

A create or an update used to be refused at the first fault its gates met, so a writer fixed that one, sent the call again and was refused at the next. The gates
of a write now run on, each fault is kept, and the write is refused once with all of them, each with its own plain line (and the corrected call, where its gate shows
one). Nothing is refused or allowed that was not before: a call with one fault is refused with that fault's text exactly as it was, and a call with none is judged as ever.

    faults = Faults()                 # the write's collector (`collected` makes one for the call; `current()` reads it)
    x = faults.call(gate, a, b, default=x0)       # a gate that refuses: its fault is kept and the write goes on with `x0`
    faults.add("Refused: ...")                    # a fault the caller found itself
    faults.skip("tell_him", "it reads said, which is refused above")     # a check that could not be judged because an earlier fault leaves it nothing to read
    faults.raise_now()                # at the point where the gates that read the call as it would be stored begin: raises when any fault was kept

A gate that finds several faults of its own (a said list with two bad entries, two long lines of next) raises `refusals(parts)`: the collector keeps each part as a fault of its own.
With two faults or more the refusal is `Refused: N problems in this call; …` with each fault numbered on its own line and, last, the checks that were not run (the ones that read the
write as it would be stored run only once the faults above are fixed). Stdlib, fastmcp's ToolError and the call log (a refused write takes back the fixes its checks noted on the way)."""
from __future__ import annotations

import contextvars
import functools
from typing import Any, Callable, TypeVar

from fastmcp.exceptions import ToolError

from stackshot.core import call_log as _calls

T = TypeVar("T")
HEAD = "problems in this call"          # the words the first line of a combined refusal carries (core/call_log.kind_of, which sits below this module, reads the first fault past them with its own pattern)
_OWN = "Refused: "


class Refusals(ToolError):
    """A refusal that holds several faults of one gate (said: two bad entries; next: two long lines). `parts` are the faults, each as its own gate would have raised it alone; `str` is
    the combined text, so an unfamiliar caller still sees every one. The collector keeps the parts as faults of the write, one each."""

    def __init__(self, parts: list[str], text: str | None = None) -> None:
        self.parts = [str(p) for p in parts]
        self.own_text = text            # the words this gate gave its faults before they were collected, kept as the refusal when it is the only gate that refused
        super().__init__(text or combine(self.parts))


def refusals(parts: list[str], text: str | None = None) -> ToolError:
    """The ToolError for a gate's faults: the one fault as it is (so a single fault reads as it ever did), several as `Refusals` (`text`: the words the gate used for the several before, kept when no other gate refuses)."""
    parts = [str(p) for p in parts if str(p).strip()]
    return ToolError(parts[0]) if len(parts) == 1 else Refusals(parts, text)


def parts_of(e: BaseException) -> list[str]:
    """The faults a ToolError holds: its parts when it is a `Refusals`, else its text."""
    got = getattr(e, "parts", None)
    return list(got) if got else [str(e)]


def _bare(text: str) -> str:
    return text[len(_OWN):] if text.startswith(_OWN) else text


def combine(parts: list[str], skipped: list[str] | None = None) -> str:
    """The text of a refusal that holds `parts`: the one fault as it is (when nothing was skipped), else the count, each fault numbered on its own line, then the checks not run."""
    skipped = skipped or []
    if len(parts) == 1 and not skipped:
        return parts[0]
    n = len(parts)
    out = f"{_OWN}{n} {HEAD}; fix all of them and send the call once more.\n" + "\n".join(f"({i}) {_bare(p)}" for i, p in enumerate(parts, 1))
    if skipped:
        out += "\nNot checked yet, because they read what the faults above leave out: " + "; ".join(skipped) + ". They run on the next send, once these are fixed."
    return out


class Faults:
    """The faults one write has found so far, and the checks it could not make."""

    def __init__(self) -> None:
        self.found: list[str] = []
        self.skipped: list[str] = []
        self.state_bad = False                            # a fault that leaves what the write would store unknown (any but the text-only ones, `add(text=True)`)
        self._own: dict[str, BaseException] = {}          # the exception a fault came in, so a lone fault is raised as it was
        self._family: set[str] = set()                    # the families of checks that read one thing (the decision's ask and options): after one faults the rest are not run
        self._sole: "Refusals | None" = None             # the first gate that refused with several faults and its own words for them: its refusal stands when no other fault comes
        self._marks: set[str] = set()                     # the mistakes already kept as a fault, by name (`mark`): a second opinion on the same mistake reads this and keeps no fault of its own

    @property
    def count(self) -> int:
        return len(self.found)

    def add(self, fault: "str | BaseException", text: bool = False) -> None:
        """Keep a fault: a text, or a ToolError (a `Refusals` is kept as its parts). `text`: the fault is in the words of one field (a description, a subject, a line of next) and changes nothing the write would store but those words, so the checks
        that read the stored state (the mover, the wait's reason, the decision) can still be judged beside it; any other fault leaves that state unknown."""
        if not text:
            self.state_bad = True
        if not self.found and getattr(fault, "own_text", None):
            self._sole = fault          # type: ignore[assignment]
        for p in (parts_of(fault) if isinstance(fault, BaseException) else [str(fault)]):
            if p not in self.found:
                self.found.append(p)
                if isinstance(fault, BaseException) and not hasattr(fault, "parts"):
                    self._own[p] = fault

    def mark(self, what: str) -> None:
        """Note that the mistake `what` (the mover, the event a wait names) is kept as a fault: a gate that only says the same mistake again from another side reads `marked` and keeps nothing, so one mistake is one fault."""
        self._marks.add(what)

    def marked(self, what: str) -> bool:
        return what in self._marks

    def call(self, fn: Callable[..., T], *args: Any, default: Any = None, **kwargs: Any) -> Any:
        """`fn(*args, **kwargs)`; a ToolError it raises is kept as a fault and `default` comes back instead."""
        try:
            return fn(*args, **kwargs)
        except ToolError as e:
            self.add(e)
            return default

    def call_family(self, family: str, what: str, because: str, fn: Callable[..., T], *args: Any, default: Any = None, **kwargs: Any) -> Any:
        """`call`, for one of a family of checks that all read the same fields and whose faults are the same fault said from several sides (the decision's ask and options): once one refuses, the rest are named as not made (`skip`),
        since they read what that fault leaves open and one fix changes what each of them finds."""
        if family in self._family:
            self.skip(what, because)
            return default
        try:
            return fn(*args, **kwargs)
        except ToolError as e:
            self.add(e)
            self._family.add(family)
            return default

    def call_depending(self, what: str, because: str, depends: bool, fn: Callable[..., T], *args: Any, default: Any = None, **kwargs: Any) -> Any:
        """`call`, for a gate that reads what an earlier fault left out (`depends`): when it refuses then, the refusal may only echo that fault, so the check is named as not made (`skip`) instead of kept as a fault."""
        try:
            return fn(*args, **kwargs)
        except ToolError as e:
            if depends:
                self.skip(what, because)
            else:
                self.add(e)
            return default

    def skip(self, what: str, because: str) -> None:
        """A check that could not be made: it reads what an earlier fault leaves out. Named in a refusal of two faults or more."""
        line = f"{what} ({because})"
        if line not in self.skipped:
            self.skipped.append(line)

    def error(self) -> ToolError:
        if len(self.found) == 1:                              # one fault is the refusal it always was (as it was raised): the checks not run are not listed beside it
            e = self._own.get(self.found[0])
            return e if isinstance(e, ToolError) else ToolError(self.found[0])
        if self._sole is not None and self.found == self._sole.parts:
            return self._sole                                 # one gate, its several faults, its own words
        return _Combined(self.found, self.skipped)

    def raise_now(self) -> None:
        """Refuse the write now when any fault was kept."""
        if self.found:
            raise self.error()


class _Combined(Refusals):
    def __init__(self, parts: list[str], skipped: list[str]) -> None:
        self.parts = list(parts)
        ToolError.__init__(self, combine(parts, skipped))


EVENT = "wait_event"          # marks: the event phrase of a wait is no event (the wait's own gate refused it)
UNTIL = "until"              # marks: the call's until was refused (no date, or not ahead) and is not read: a waits list that needs it for its backstop day is not judged on it
NEXT = "next_line"            # marks: a line of next names no one and the model guards refused it (the same mistake: the check that an open step is left reads next as it was sent, which that fault already refuses)
MOVER = "mover"               # marks: the model guards refused the item's mover (no session the registry knows)
MOVER_HANDOFF = ("the check that the mover has a pane to be handed the item", "it reads the mover, which the fault above refuses")
MOVER_FRONT_STEP = ("the check of a step that opens with a front agent", "it reads the mover, which the fault above refuses")
DECISION = ("decision", "the other checks of the decision's wording and options (one decision, alternatives, open question, Recommend, mockup, own action)", "they read the ask and the options, which the fault above leaves open")
_CURRENT: "contextvars.ContextVar[Faults | None]" = contextvars.ContextVar("write_faults", default=None)


def current() -> Faults:
    """The collector of the write in progress (a gate called outside a collected write gets one nobody reads: it keeps nothing the caller sees, so the caller must raise on its own)."""
    fc = _CURRENT.get()
    return fc if fc is not None else Faults()


def collected(fn: Callable[..., T]) -> Callable[..., T]:
    """Run a write's body with a collector in place. A ToolError the body raises once faults were kept (a gate nobody collected) is one more fault and the refusal holds all; any other error after a fault is the
    faults' refusal, since a body that went on past a fault on stand-in values may stumble on them; with no fault kept, every error goes on as it was."""
    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> T:
        fc = Faults()
        tok = _CURRENT.set(fc)
        mark = _calls.mark()
        try:
            return fn(*args, **kwargs)
        except ToolError as e:
            if not fc.found:
                raise
            fc.add(e)
            _calls.rewind(mark)                      # the checks that ran on past a fault noted fixes of a write that is not made
            raise fc.error() from None
        except Exception:
            if not fc.found:
                raise
            _calls.rewind(mark)
            raise fc.error() from None
        finally:
            _CURRENT.reset(tok)
    return run
