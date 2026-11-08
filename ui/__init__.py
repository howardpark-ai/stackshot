"""Forwarder package for stackshot.web.ui: the modules in this folder forward one by one (kept until 2026-11-22). No code lives here."""
import importlib
import os
import sys

_TARGET = "stackshot.web.ui"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def __getattr__(name):   # a name of the real package (PREFIX ...)
    if name.startswith("__"):
        raise AttributeError(name)
    return getattr(importlib.import_module(_TARGET), name)
