#!/usr/bin/env python3
"""Forwarder: this program moved to stackshot/fleet/push.py (module stackshot.fleet.push). The old path stays so that units, hooks, allow rules and scripts
that name it keep working until 2026-11-22; callers move to `stackshot push`. No code lives here."""
import importlib
import os
import sys

_TARGET = "stackshot.fleet.push"
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

if __name__ == "__main__":
    import runpy
    runpy.run_module(_TARGET, run_name="__main__", alter_sys=True)
else:
    _real = importlib.import_module(_TARGET)
    sys.modules[__name__] = _real


def __getattr__(name):   # a caller that loaded this file by path still reaches the module's names
    return getattr(importlib.import_module(_TARGET), name)
