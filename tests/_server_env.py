"""_server_env.py: the interpreter of an environment that holds what the project's `server` extra installs and nothing of the `tests` group.

The suites run in the `tests` environment (tests/run-suite), which holds more than an installation does, so a program that imports a module the `server` extra does not bring passes
there and fails where it is installed. A suite starts such a program with this interpreter instead: the program then sees what `uv run --extra server` gives it.

    py = _server_env.python(STACK, T / "server-env")      # T: the suite's scratch folder, which is removed with the environment when the suite ends

The checkout itself is not installed (as for the suites): the program is run from it, with PYTHONPATH naming it. `--locked` fails on a stale uv.lock."""
import os, pathlib, shutil, subprocess


def python(root, into) -> str:
    """The path of the interpreter of a `server`-extra environment of the project at `root`, made in the folder `into`. RuntimeError with uv's own words when it cannot be made."""
    uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(into)}      # never the shared test environment the suite itself runs in
    env.pop("VIRTUAL_ENV", None)
    r = subprocess.run([uv, "sync", "--locked", "--project", str(root), "--extra", "server", "--no-default-groups", "--no-install-project"],
                       env=env, capture_output=True, text=True, timeout=600)
    exe = pathlib.Path(into) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if r.returncode != 0 or not exe.exists():
        raise RuntimeError(f"the server environment cannot be made (uv sync exit {r.returncode}): {r.stderr[-800:]}")
    return str(exe)
