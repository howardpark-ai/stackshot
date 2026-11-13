"""textfile.py: reads a tool's text file (text/<name>.md) and fills its {{NAME}} placeholders.

A text file is a list of sections. A section starts with a line `## <kind> <name> [lead] [trail]` and its body is the lines up to the
next such line (blank lines may separate sections, never split one); a line break inside a body stands for one space, so a long text can be wrapped at any single space. Kinds:
  description <tool>   the text of one tool's description (before the opener every description carries)
  param <KEY>          the text of one parameter
  text <NAME>          a piece of text other sections or the Python module use by name
`lead` and `trail` on a header say the text starts or ends with one space (a line cannot show it).

{{NAME}} in a body is replaced by the value NAME (a number, a name, a limit: what the code computes), by the piece NAME, or by a late value
the code passes when it asks for the text. Single braces are plain text. A file that names a placeholder nothing defines, passes a value it
never uses, repeats a section or redefines a shared one does not load. The shared pieces (text/shared.md) are one file that the others
read through `parent`. This module imports nothing from stackshot: it is the reading of the files, the words stay in the files."""
from __future__ import annotations

import re
from pathlib import Path

DIR = Path(__file__).with_name("text")
_PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_HEADER = re.compile(r"^## (description|param|text) (\S+)((?: (?:lead|trail))*)$")


class TextFileError(ValueError):
    """A text file that does not load, or a text asked for that it does not hold."""


def _sections(path: Path) -> dict[tuple[str, str], str]:
    """The sections of one file as {(kind, name): text}, flags applied, line breaks turned into the one space they stand for."""
    out: dict[tuple[str, str], str] = {}
    head: tuple[str, str, str] | None = None
    body: list[str] = []
    blank = 0           # the line number of a blank line met inside the body: fine before the next header, an error before more text

    def close() -> None:
        if head is None:
            return
        kind, name, flags = head
        if (kind, name) in out:
            raise TextFileError(f"{path.name}: section {kind} {name} is there twice")
        if not body:
            raise TextFileError(f"{path.name}: section {kind} {name} is empty")
        text = " ".join(body)
        if "lead" in flags.split():
            text = " " + text
        if "trail" in flags.split():
            text += " "
        out[(kind, name)] = text

    for n, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        m = _HEADER.match(line)
        if m:
            close()
            head, body, blank = (m.group(1), m.group(2), m.group(3)), [], 0
        elif line.startswith("## "):
            raise TextFileError(f"{path.name}:{n}: a section header reads `## <description|param|text> <name> [lead] [trail]`")
        elif head is None:
            if line.strip() and not line.startswith("#"):
                raise TextFileError(f"{path.name}:{n}: text before the first section")
        elif line.strip():
            if blank:
                raise TextFileError(f"{path.name}:{blank}: a blank line inside section {head[0]} {head[1]}: a section is one text, wrapped at spaces")
            body.append(line)
        elif body and not blank:
            blank = n
    close()
    return out


class Texts:
    """The sections of one file, with its values, the late names the code passes later and the shared file it reads through."""

    def __init__(self, name: str, values: dict[str, str], late: tuple[str, ...] = (), parent: "Texts | None" = None, directory: Path | None = None, common: bool = False) -> None:
        self.name = name
        self.common = common
        self.values = dict(values)
        self.late = set(late)
        self.parent = parent
        self.sections = _sections((directory or DIR) / f"{name}.md")
        self._asked: set[tuple[str, str]] = set()
        self._cache: dict[tuple[str, str], str] = {}
        self._check()

    # ---- load-time checks
    def _pieces(self) -> set[str]:
        return {n for (k, n) in self.sections if k == "text"}

    def _known(self) -> set[str]:
        names = set(self.values) | self.late | self._pieces()
        if self.parent is not None:
            names |= self.parent._known()
        return names

    def _check(self) -> None:
        if self.parent is not None:
            for key in self.sections:
                if key in self.parent.sections:
                    raise TextFileError(f"{self.name}.md: {key[0]} {key[1]} is in the shared file too: say it once")
        known = self._known()
        used: set[str] = set()
        edges: dict[str, set[str]] = {}
        for (kind, name), body in self.sections.items():
            refs = set(_PLACEHOLDER.findall(body))
            used |= refs
            if kind == "text":
                edges[name] = refs
            for ref in sorted(refs - known):
                raise TextFileError(f"{self.name}.md: {kind} {name} names {{{{{ref}}}}}, which no value or piece defines")
        for name in sorted(set() if self.common else set(self.values) - used):
            raise TextFileError(f"{self.name}.md: the value {name} is passed and no text uses it")
        for name in sorted(self.late - used):
            raise TextFileError(f"{self.name}.md: the late value {name} is declared and no text uses it")
        for name in edges:
            self._no_cycle(name, edges, ())

    def _no_cycle(self, name: str, edges: dict[str, set[str]], path: tuple[str, ...]) -> None:
        if name in path:
            raise TextFileError(f"{self.name}.md: pieces refer to each other in a circle: {' -> '.join(path + (name,))}")
        for ref in edges.get(name, ()):
            if ref in edges:
                self._no_cycle(ref, edges, path + (name,))

    # ---- reading
    def _render(self, body: str, late: dict[str, str]) -> str:
        def fill(m: re.Match[str]) -> str:
            return self._resolve(m.group(1), late)
        return _PLACEHOLDER.sub(fill, body)

    def _resolve(self, name: str, late: dict[str, str]) -> str:
        if name in late:
            return late[name]
        if name in self.values:
            return self.values[name]
        if ("text", name) in self.sections:
            return self._section("text", name, late)
        if self.parent is not None:
            return self.parent._resolve(name, late)
        raise TextFileError(f"{self.name}.md: {{{{{name}}}}} is not given a value where the text is asked for")

    def _section(self, kind: str, name: str, late: dict[str, str]) -> str:
        key = (kind, name)
        self._asked.add(key)
        if not late and key in self._cache:
            return self._cache[key]
        text = self._render(self.sections[key], late)
        if not late:
            self._cache[key] = text
        return text

    def _get(self, kind: str, name: str, late: dict[str, str]) -> str:
        if (kind, name) in self.sections:
            for key in late:
                if key not in self.late:
                    raise TextFileError(f"{self.name}.md: {key} is not a declared late value")
            return self._section(kind, name, late)
        if self.parent is not None:
            return self.parent._get(kind, name, late)
        raise TextFileError(f"{self.name}.md: no {kind} {name}")

    def description(self, tool: str, **late: str) -> str:
        """The text of a tool's description, without the opener."""
        return self._get("description", tool, late)

    def param(self, key: str, **late: str) -> str:
        """The text of a parameter."""
        return self._get("param", key, late)

    def piece(self, name: str, **late: str) -> str:
        """A named piece of text."""
        return self._get("text", name, late)

    def unused(self, files: "list[Texts]" = ()) -> list[str]:
        """The sections of this file (as `<kind> <name>`) that no section of it or of the files given refers to and the code never asked for: leftovers to delete.
        A description or a parameter is only asked for by the code; a piece may also be named by a {{NAME}}."""
        refs = {r for t in [self, *files] for body in t.sections.values() for r in _PLACEHOLDER.findall(body)}
        asked = self._asked.union(*[t._asked for t in files])
        return sorted(f"{k} {n}" for (k, n) in self.sections if (k, n) not in asked and not (k == "text" and n in refs))

    def unused_values(self, files: "list[Texts]") -> list[str]:
        """The values of this file that no text of it or of the files given refers to (for the shared values, which any file may leave unused)."""
        refs = {r for t in [self, *files] for body in t.sections.values() for r in _PLACEHOLDER.findall(body)}
        return sorted(set(self.values) - refs)


def load(name: str, values: dict[str, str] | None = None, *, late: tuple[str, ...] = (), parent: Texts | None = None, directory: Path | None = None, common: bool = False) -> Texts:
    """Reads text/<name>.md and checks it against `values`, the late names and the shared file. `common` marks the shared file, whose values
    any other file may use or leave unused."""
    return Texts(name, values or {}, late, parent, directory, common)
