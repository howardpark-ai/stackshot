#!/usr/bin/env python3
"""Forwarder: this program moved to stackshot/fleet/puller.py (module stackshot.fleet.puller). The old path stays so that units, hooks, allow rules and scripts
that name it keep working until 2026-11-22; callers move to `stackshot puller`. No code lives here."""
import importlib
import os
import sys

_TARGET = "stackshot.fleet.puller"
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

VERSION = "11"   # an older puller reads this line of the file on disk to decide whether to reload; keep it equal to stackshot/fleet/puller.py

if __name__ == "__main__":
    import runpy
    runpy.run_module(_TARGET, run_name="__main__", alter_sys=True)
else:
    _real = importlib.import_module(_TARGET)
    if __name__ != "puller":   # an older puller reloads itself with runpy.run_path(puller.py) and takes main() from the globals it gets back
        globals().update({k: v for k, v in vars(_real).items() if not k.startswith("__")})
    sys.modules[__name__] = _real


def __getattr__(name):   # a caller that loaded this file by path still reaches the module's names
    return getattr(importlib.import_module(_TARGET), name)
