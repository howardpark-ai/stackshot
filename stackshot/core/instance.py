"""instance.py: who this stackshot is, read once from the [instance] settings: the owner's name, the instance's own name and the board's URL.

Every layer above core/ reads these three (a notice names the owner, a link starts at the board's URL). They are read once, at import: [instance] owner, name and board_url are among the settings
config.RESTART_ONLY keeps for the run, so a reload (SIGHUP) does not change them. A suite that needs another board URL sets `BOARD_URL` on this module (`instance.BOARD_URL = ...`), the one place it is read from."""
from __future__ import annotations

from stackshot.core import config as _cfg

OWNER = str(_cfg.get("instance", "owner") or "the owner")
NAME = str(_cfg.get("instance", "name") or "stackshot")
BOARD_URL = str(_cfg.get("instance", "board_url") or "")
