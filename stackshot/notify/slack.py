"""slack.py: what the For you list's Slack post says: the line a row makes, and the reasons and log lines of a post that did not go through.

An urgent row (a due date within 24 h) is also posted once to Slack by service/foryou_slack.py, which owns the configured command, the queue, the worker thread and the process that runs the command.
The words are here: they read no config, no clock and no process, so they are checked without any of them. A reason is what the hook returns for a post that failed ("" is a post that went through)."""
from __future__ import annotations

from typing import Any

from stackshot.notify import foryou as _fy

NO_PATH = "no Slack path configured ([for_you] slack_command is empty)"


def message(row: dict[str, Any]) -> str:
    """The text posted for a row: the item as a session reads it, the row's line and the item's page."""
    return f"[stackshot] For you (urgent): {row['item'] + ' ' if row.get('item') else ''}{row['what']}" + (f" → {row['url']}" if row.get("url") else "")


def not_posted(rid: int, tries: int, err: str) -> str:
    """The stderr line for a row whose post failed, with what happens next: it is tried again on a later pass until SLACK_TRIES in all."""
    left = "tried again on a later pass" if tries < _fy.SLACK_TRIES else "no more tries"
    return f"for-you: row {rid} not posted to Slack (try {tries} of {_fy.SLACK_TRIES}, {left}): {err}"


def timed_out(cmd: str, seconds: float) -> str:
    """The reason for a command that ran past its time and was killed."""
    return f"{cmd.split()[0]} did not finish in {seconds:g} s; killed"


def exited(cmd: str, returncode: int, tail: list[str]) -> str:
    """The reason for a command that exited with a status other than 0; `tail` is the lines it wrote to its standard error (the last is shown)."""
    return f"{cmd.split()[0]} exited {returncode}" + (f": {tail[-1]}" if tail else "")
