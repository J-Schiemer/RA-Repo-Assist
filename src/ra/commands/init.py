"""ra init command — interactive project setup."""

from __future__ import annotations

import sys
from pathlib import Path


LANGUAGES: list[str] = [
    "C", "C++", "C#", "Clojure", "CoffeeScript", "CSS",
    "Dart", "Elixir", "Elm", "Erlang", "F#", "Fortran",
    "Go", "Haskell", "HTML", "Java", "JavaScript", "JSON",
    "Julia", "Kotlin", "Lisp", "Lua", "Makefile", "Markdown",
    "MATLAB", "Objective-C", "OCaml", "Perl", "PHP",
    "Protocol Buffers", "Python", "R", "Ruby", "Rust",
    "Scala", "Shell", "SQL", "Swift", "Tcl", "TypeScript",
    "V", "VHDL", "Verilog", "Vim script", "XML", "YAML",
]


def run_init(args: object) -> None:
    """Execute the `ra init` command using the TUI wizard."""
    target = Path(getattr(args, "dir", ".")).resolve()

    if not target.is_dir():
        print(f"Error: '{target}' is not a directory")
        sys.exit(1)

    ra_dir = target / ".ra"

    if ra_dir.exists():
        print(f"Warning: '{ra_dir}' already exists and will be overwritten.")

    from ra.tui import InitWizard
    app = InitWizard(target=target)
    result = app.run()

    if result:
        print(f"\nInitialized ra in {ra_dir}")
        print(f"  Config:   {ra_dir / '.raconfig'}")
        print(f"  Ignore:   {ra_dir / '.raignore'}")
        print(f"  Output:   {ra_dir / 'out'}")
    else:
        print("Aborted.")
        sys.exit(1)
