"""tests/_twobox.py — two folders that stand for two boxes, with a fake `ssh` between them, for the suites that run `pages.py clear` on a box that is not the server host.

The server host is the suite's own config (its state folder holds the owed list). The sessions' box is a copy of that config with a state folder and a reminder folder
of its own and a [release] deploy_ssh that names the server host. Nothing here connects anywhere: the fake `ssh`, first on PATH, notes the words it was given and runs
the last of them with `sh -c`, as the shell ssh starts on the far side would: in a HOME whose ~/stackshot is this checkout, with the server's config, without the
caller's session id and with no session store of the caller's. FAKE_SSH_MODE: run (the default) | down (ssh's own failure, 255) | silent (exit 0, nothing said) |
hang (no answer) | said (the stdout, stderr and exit status the suite gives). When the caller was given an input, ssh also notes what it could read of it.
Everything is made under the folder the suite passes, which the suite removes."""
import json, os, pathlib, re, shlex, subprocess, sys

HOST = "server-host"        # the name [release] deploy_ssh gives the server host here: no machine's


class TwoBoxes:
    def __init__(self, root, checkout, server_config):
        self.root = pathlib.Path(root) / "twobox"; self.checkout = str(checkout); self.server_config = pathlib.Path(server_config)
        self.state = self.root / "client-state"; self.touch = self.root / "client-touch"
        self.home = self.root / "server-home"; self.old_home = self.root / "old-home"; self.bin = self.root / "bin"; self.log = self.root / "ssh.log"
        self.read = self.root / "ssh.stdin"; self.no_ssh = self.root / "no-ssh"        # what ssh read of the caller's input · a PATH with no ssh on it
        for d in (self.state, self.touch, self.home, self.old_home / "stackshot/stackshot/projects", self.bin, self.no_ssh, self.root / "no-fleet"): d.mkdir(parents=True)
        os.symlink(self.checkout, self.home / "stackshot")
        # a checkout older than the forwarded call: a verb it does not know prints its help and exits 1
        (self.old_home / "stackshot/stackshot/projects/pages.py").write_text("import sys\nprint('usage: pages.py clear <key> [--force]')\nsys.exit(1)\n", encoding="utf-8")
        (self.root / "fake_ssh.py").write_text(
            "import json, os, sys\n"
            "with open(os.environ['FAKE_SSH_LOG'], 'a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "mode = os.environ.get('FAKE_SSH_MODE', 'run')\n"
            "if os.environ.get('FAKE_SSH_STDIN'):\n"
            "    with open(os.environ['FAKE_SSH_STDIN'], 'w') as f: f.write(sys.stdin.read())\n"
            "if mode == 'said':\n"
            "    out, err, rc = json.loads(os.environ['FAKE_SSH_SAID']); sys.stdout.write(out); sys.stderr.write(err); sys.exit(rc)\n"
            "if mode == 'down':\n"
            "    print('ssh: connect to host server-host port 22: Connection refused', file=sys.stderr); sys.exit(255)\n"
            "if mode == 'silent': sys.exit(0)\n"
            "if mode == 'hang': os.execvp('sleep', ['sleep', '30'])\n"
            "env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CODE_SESSION_ID'}\n"
            "env.update(HOME=os.environ['FAKE_SSH_HOME'], STACKSHOT_CONFIG=os.environ['FAKE_SSH_CONFIG'], STACKSHOT_FLEET_DIR=os.environ['FAKE_SSH_FLEET'])\n"
            "print('welcome to the server host', flush=True)\n"
            "os.execvpe('sh', ['sh', '-c', sys.argv[-1]], env)\n", encoding="utf-8")
        for name, line in (("ssh", f"exec {shlex.quote(sys.executable)} {shlex.quote(str(self.root / 'fake_ssh.py'))} \"$@\""),
                           ("python3", f"exec {shlex.quote(sys.executable)} \"$@\"")):
            (self.bin / name).write_text(f"#!/bin/sh\n{line}\n", encoding="utf-8"); (self.bin / name).chmod(0o755)
        os.symlink(self.bin / "python3", self.no_ssh / "python3")

    def config(self, name, base=None, **values):
        """A config of its own made from the server's (or `base`): each keyword is a key of the file, set to the value; box_false adds [server] box = false."""
        text = pathlib.Path(base or self.server_config).read_text(encoding="utf-8")
        if values.pop("box_false", False):
            text, n = re.subn(r"(?m)^(\[server\].*)$", r"\1\nbox = false", text, count=1); assert n == 1
        for key, value in values.items():
            text, n = re.subn(rf'(?m)^{key} = "[^"]*"', lambda _m: f"{key} = {json.dumps(str(value))}", text, count=1); assert n == 1, key
        path = self.root / name; path.write_text(text, encoding="utf-8")
        return path

    def client_config(self, name="client.toml", deploy_ssh=HOST, **values):
        return self.config(name, state=self.state, project_touch=self.touch, deploy_ssh=deploy_ssh, **values)

    def env(self, sid="", mode="run", config=None, home=None, server=None, fleet=None, server_fleet=None, said=None, path=None):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
        env.update(PATH=f"{self.bin}{os.pathsep}{env.get('PATH', '')}", STACKSHOT_CONFIG=str(config or self.root / "client.toml"), FAKE_SSH_LOG=str(self.log), FAKE_SSH_MODE=mode,
                   FAKE_SSH_HOME=str(home or self.home), FAKE_SSH_CONFIG=str(server or self.server_config), FAKE_SSH_FLEET=str(server_fleet or self.root / "no-fleet"))
        if sid: env["CLAUDE_CODE_SESSION_ID"] = sid
        if fleet: env["STACKSHOT_FLEET_DIR"] = str(fleet)
        if said: env.update(FAKE_SSH_MODE="said", FAKE_SSH_SAID=json.dumps(said))
        if path: env["PATH"] = str(path)
        return env

    def calls(self):
        """The words of every ssh call since the last run began."""
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").split("\n") if x] if self.log.exists() else []

    def run(self, words, typed=None, **how):
        """`words` run as a command on the sessions' box → (exit status, stdout, the ssh calls it made). `typed`: its standard input; ssh notes in
        `read` what reached it of that."""
        self.log.unlink(missing_ok=True); self.read.unlink(missing_ok=True)
        env = self.env(**how)
        if typed is not None: env["FAKE_SSH_STDIN"] = str(self.read)
        r = subprocess.run(words, capture_output=True, text=True, env=env, input=typed, timeout=90)
        return r.returncode, r.stdout, self.calls()

    def clear(self, *args, **how):
        return self.run([sys.executable, os.path.join(self.checkout, "stackshot/projects/pages.py"), "clear", *args], **how)

    def owe(self, key, sid):
        """A reminder of `sid` on the sessions' box."""
        (self.touch / f"{sid}.json").write_text(json.dumps({"touches": {key: {"ts": 1, "task": "s11"}}}), encoding="utf-8")

    def reminded(self, key, sid):
        try: return key in json.loads((self.touch / f"{sid}.json").read_text(encoding="utf-8")).get("touches", {})
        except FileNotFoundError: return False


def given_command(out):
    """The command a `clear` that could not reach the server printed (between the backticks of its line)."""
    line = next(x for x in out.split("\n") if x.startswith("The server's entry for "))
    return line[line.index("`") + 1:line.rindex("`")]
