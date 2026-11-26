"""config.py: what the front door reads from disk: its settings, the files of credentials and the members file.

    load(cfg=None)           → the Settings of the config (`core/frontdoor_config.py` parses and judges them), or ConfigError saying why the front door
                               cannot start; a line for each smaller fault is left to the config notes (`notes()` in `core/config.py`) and printed at start
    read_secret(path, ...)   → the one value in a secret file, or FileError naming the path and the reason (never the content)
    read_members(path)       → {member: [backend names]} from the members file, read at each call
                               (both are `core/frontdoor_files.py`, shared with a board behind the front door, and are re-exported here)

A secret file is read through one opened descriptor, as a brain's `secret_file` is (`projects/brains.py: secret`): it must be a regular file, private
to its owner (a file group or others can read is refused, the one wording of `core/config.py: secret_mode_text`), at most MAX_BYTES, text whose first
non-empty line is the value, with no control character and at least `min_len` characters. Nothing it holds is ever put in a message or a log.
"""
from __future__ import annotations

from typing import Any

from stackshot.core import frontdoor_config as _fc
from stackshot.core.frontdoor_config import Backend, Settings
from stackshot.core.frontdoor_files import FileError, MAX_BYTES, MIN_SECRET, _read_text, read_members, read_secret   # noqa: F401  (re-exported: the front door's own names for them)


class ConfigError(Exception):
    """The front door cannot start: the message says what is missing, in words a person can act on."""


def load(cfg: dict[str, Any] | None = None) -> Settings:
    """The settings of `cfg` (the running config when None); ConfigError when the front door cannot serve with them."""
    settings, problems = _fc.parse(cfg)
    why = _fc.blocking(settings)
    if why:
        raise ConfigError("the front door does not start: " + "; ".join(why) + ("\n" + "\n".join(problems) if problems else ""))
    return settings


def credentials(b: Backend) -> dict[str, str]:
    """The values of a backend's credential files, read now: {"token": ...} or {"client_id": ..., "client_secret": ..., "scopes": ...}. FileError when one cannot be used."""
    if b.oauth:
        return {"client_id": read_secret(b.client_id_file, "oauth client_id_file", 1), "client_secret": read_secret(b.client_secret_file, "oauth client_secret_file"),
                "scopes": b.scopes}
    return {"token": read_secret(b.token_file, "token_file")}
