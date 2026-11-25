"""identity.py: the front door's name for `core/frontdoor_identity.py` (the signing and checking of the caller's identity, which a board uses too).

The code lives in core/ so that a board can verify what the front door signs without importing this package; nothing is changed here."""
from stackshot.core.frontdoor_identity import HEADER, MAX_AGE, MAX_FUTURE, VERSION, _b64, _mac, _unb64, sign, verify

__all__ = ["HEADER", "MAX_AGE", "MAX_FUTURE", "VERSION", "sign", "verify"]
