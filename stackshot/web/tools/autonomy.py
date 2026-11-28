"""autonomy.py: the `autonomy` tool: the autonomy profile of a person, read only (core/autonomy.py). One kind gives its level word; no kind gives the person's whole table.
There is no write tool: the file is edited by hand and committed in the data repo."""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from stackshot.core import autonomy as _autonomy
from stackshot.web.auth import oauth as _oauth
from stackshot.web.tools.text import _lead, load_text

_T = load_text("autonomy")


def stackshot_autonomy(person: Annotated[str, Field(description=_T.param("person"))],
                       kind: Annotated[str, Field(description=_T.param("kind"))] = "") -> str:
    _oauth._who()
    return answer(person, kind)


def answer(person: str, kind: str = "") -> str:
    """The tool's reply: `<kind>: <level>` for one kind, else one such line per kind, in the order of the kinds."""
    kind = (kind or "").strip()
    if kind:
        if kind not in _autonomy.KIND_NAMES:
            return f"{kind}: {_autonomy.FALLBACK} (not a kind of action; the kinds are {', '.join(_autonomy.KIND_NAMES)})"
        return f"{kind}: {_autonomy.level(person, kind)}"
    meaning = dict(_autonomy.KINDS)
    return "\n".join(f"{k}: {v} · {meaning[k]}" for k, v in _autonomy.table(person).items())


def register(mcp) -> None:
    """Adds the tool of this module to `mcp`."""
    mcp.tool(name="autonomy", description=_lead(_T.description("autonomy")))(stackshot_autonomy)
