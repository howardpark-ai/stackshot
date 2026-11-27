"""config.py: what the front door reads from disk: its settings, the files of credentials and the members file.

    load(cfg=None)           → the Settings of the config (`core/frontdoor_config.py` parses and judges them), or ConfigError saying why the front door
                               cannot start; a line for each smaller fault is left to the config notes (`notes()` in `core/config.py`) and printed at start
    read_secret(path, ...)   → the one value in a secret file, or FileError naming the path and the reason (never the content)
    read_members(path)       → {member: [backend names]} from the members file, read at each call
                               (both are `core/frontdoor_files.py`, shared with a board behind the front door, and are re-exported here)
    is_own_board(url)        → whether a url is this machine's own board: the loopback address on the port of `[server] port`
    own_boards(settings)     → the board backends that are this machine's own board
    unusable_files(settings) → why a file the front door reads at each request cannot be used now (`--check` says it)

A secret file is read through one opened descriptor, as a brain's `secret_file` is (`projects/brains.py: secret`): it must be a regular file, private
to its owner (a file group or others can read is refused, the one wording of `core/config.py: secret_mode_text`), at most MAX_BYTES, text whose first
non-empty line is the value, with no control character and at least `min_len` characters. Nothing it holds is ever put in a message or a log.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from stackshot.core import config as _cfg
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


def is_own_board(url: str, cfg: dict[str, Any] | None = None) -> bool:
    """Whether `url` is the board of this config: on the loopback address, on the port `[server] port` names."""
    try:
        port = int(_cfg.get("server", "port", cfg=cfg))
        u = urlsplit(url)
        return (u.hostname or "").lower() in _fc._LOOPBACK and (u.port or (443 if u.scheme == "https" else 80)) == port
    except (TypeError, ValueError):
        return False


def own_boards(settings: Settings, cfg: dict[str, Any] | None = None) -> list[Backend]:
    """The board backends that are this machine's own board (`is_own_board`), in the config's order."""
    return [b for b in settings.boards() if is_own_board(b.url, cfg)]


def unusable_files(settings: Settings) -> list[str]:
    """Why a file the front door reads at each request cannot be used now ([] when all can): the identity secret (when one is named), the members file and every
    backend's credential files, each read as a request reads it. Every one is tried. The lines name paths and keys, never a value."""
    reads: list[tuple[str, Any]] = []
    if settings.identity_secret_file:
        reads.append(("", lambda: read_secret(settings.identity_secret_file, "identity_secret_file")))
    reads.append(("", lambda: read_members(settings.members_file)))
    reads += [(f"backend {b.name}: ", lambda b=b: credentials(b)) for b in settings.backends]
    out = []
    for label, read in reads:
        try:
            read()
        except FileError as e:
            out.append(f"{label}{e}")
    return out
