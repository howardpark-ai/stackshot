"""paths.py: where the checkout is, for the modules that read a file or start a program that sits beside the package.

The package lives in `stackshot/` at the root of the checkout; the data the code reads at run time stays at that root, where `deploy.sh`,
`install.sh` and the units look for it: `stackshot.example.toml`, `audit_rubric.txt`, `icons/`, `fonts/`, `shared/`, `client/hooks/`, `tests/`.
`ROOT` is that folder. Standard library only (the puller, the client and `config` import this on every box).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent        # the checkout: the folder that holds the stackshot/ package


def program(area: str, name: str) -> str:
    """The path of a module that is also a program (`stackshot/fleet/push.py`), for a child process: [sys.executable, program("fleet", "push"), ...].
    A module run this way puts the checkout on sys.path itself (the few lines at its top), so the child needs no PYTHONPATH."""
    return str(ROOT / "stackshot" / area / f"{name}.py")
