"""rules.py: the `rules` tool, the `stackshot://rules` resource and the `bump_versions` tool: the rulebook served to a session and the version bump of the tool set."""
from __future__ import annotations

from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.web.auth import oauth as _oauth
from stackshot.web.publish import _publish_now
from stackshot.web.tools.text import _lead

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
    mcp.tool(name="rules", description=f"{OWNER}'s standing rules — the rulebook every Claude Code session on the owner's machines loads through CLAUDE.md ({_cfg.path('paths', 'rules').name}, git-synced). A session that did not load it at start (cloud, Cowork) calls this once at the start of a task and follows it; a session that has it does not. profile=\"cowork\" (default) = the Cowork view: CLI-only sections replaced by their Cowork equivalents, incident notes stripped; profile=\"full\" = the whole file. The rulebook parts named in config (skill files that CLI sessions load through hooks) are appended after the rulebook, each under \"## Part: <name>\".")(stackshot_rules)
    mcp.resource("stackshot://rules", name="standing-rules", description=f"{OWNER}'s standing rules ({_cfg.path('paths', 'rules').name}, git-synced), with the rulebook parts named in config appended", mime_type="text/markdown")(rules_resource)
    mcp.tool(name="bump_versions", description=_lead("Refresh the latest-available versions (npm claude-code, gbrain releases) and republish the board now. Installed versions come from each machine's heartbeat (the fleet tool pushes it before calling this after a CLI update). `host` is accepted and ignored."))(stackshot_bump_versions)
