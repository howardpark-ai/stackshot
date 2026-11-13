"""rules.py: the `rules` tool, the `stackshot://rules` resource and the `bump_versions` tool: the rulebook served to a session and the version bump of the tool set."""
from __future__ import annotations

from stackshot.core import config as _cfg
from stackshot.web.auth import oauth as _oauth
from stackshot.web.publish import _publish_now
from stackshot.web.tools.text import _lead, load_text

_T = load_text("rules", {"RULES_NAME": _cfg.path("paths", "rules").name})

_rules_text = None      # set by register: the server's own, looked up at each call


def stackshot_rules(profile: str = "cowork") -> str:
    _oauth._who()
    return _rules_text("full" if profile == "full" else "cowork")


def rules_resource() -> str:
    return _rules_text("cowork")


def stackshot_bump_versions(host: str = "") -> str:
    """Refresh the latest-available versions (npm claude-code, gbrain releases) and republish the board now. Installed versions come from each machine's heartbeat (the fleet tool pushes it before calling this after a CLI update). `host` is accepted and ignored."""
    _oauth._who()
    return "published: " + _publish_now(force_versions=True, host=host)


def register(mcp, *, rules_text) -> None:
    """Adds the tools of this module to `mcp`, and takes the server's callables the bodies use."""
    global _rules_text
    _rules_text = rules_text
    mcp.tool(name="rules", description=_T.description("rules"))(stackshot_rules)
    mcp.resource("stackshot://rules", name="standing-rules", description=_T.description("rules_resource"), mime_type="text/markdown")(rules_resource)
    mcp.tool(name="bump_versions", description=_lead(_T.description("bump_versions")))(stackshot_bump_versions)
