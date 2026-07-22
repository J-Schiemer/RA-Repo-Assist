"""Async ctags interface for ra."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

_HOMEBREW_PATHS = [
    Path("/opt/homebrew/bin/ctags"),       # Apple Silicon
    Path("/usr/local/bin/ctags"),          # Intel
    Path("/opt/homebrew/opt/universal-ctags/bin/ctags"),
]


def _find_ctags() -> str:
    """Resolve the universal-ctags binary, preferring homebrew on macOS."""
    if sys.platform == "darwin":
        for p in _HOMEBREW_PATHS:
            if p.exists():
                return str(p)
    found = shutil.which("ctags")
    if found:
        return found
    return "ctags"


_CTAGS_BIN: str | None = None


def _get_ctags_bin() -> str:
    global _CTAGS_BIN
    if _CTAGS_BIN is None:
        _CTAGS_BIN = _find_ctags()
    return _CTAGS_BIN


@dataclass
class Tag:
    """A single ctags tag entry."""

    name: str
    path: Path
    line: int | None = None
    kind: str | None = None
    pattern: str | None = None
    fields: dict[str, str | int] = field(default_factory=dict)


class CtagsError(Exception):
    """Raised when ctags exits with a non-zero status."""


class Ctags:
    """Async interface to universal-ctags.

    Usage::

        ctags = Ctags(Path("."))
        tags = await ctags.run()
        file_tags = await ctags.run_on_file(Path("main.py"))
    """

    def __init__(self, path: Path, *, extra_args: list[str] | None = None) -> None:
        self._path = path
        self._extra_args = extra_args or []

    async def run(self) -> list[Tag]:
        """Run ctags recursively on the path and return parsed tags."""
        return await self._execute("-R")

    async def run_on_file(self, path: Path) -> list[Tag]:
        """Run ctags on a single file and return parsed tags."""
        return await self._execute(str(path))

    async def _execute(self, *extra: str) -> list[Tag]:
        cmd = (
            _get_ctags_bin(),
            "--output-format=json",
            "--fields=+n",
            "-f",
            "-",
            *self._extra_args,
            *extra,
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            if "illegal option" in error_msg or "unknown option" in error_msg:
                hint = (
                    "Install with: brew install universal-ctags\n"
                    "Then ensure it's first in PATH:\n"
                    '  export PATH="/opt/homebrew/opt/universal-ctags/bin:$PATH"'
                    if sys.platform == "darwin"
                    else "Install with: brew install universal-ctags"
                )
                raise CtagsError(
                    "BSD ctags detected. ra requires universal-ctags.\n"
                    f"{hint}\n"
                    f"Original error: {error_msg}"
                )
            raise CtagsError(
                f"ctags exited with code {proc.returncode}: {error_msg}"
            )
        return _parse_json(stdout)


def _parse_json(data: bytes) -> list[Tag]:
    """Parse ctags JSON output into Tag objects."""
    raw: list[dict[str, object]] = [
        json.loads(line) for line in data.splitlines() if line.strip()
    ]
    tags: list[Tag] = []
    for entry in raw:
        fields = {
            k: v
            for k, v in entry.items()
            if k not in {"_type", "name", "path", "line", "_line", "kind", "pattern"}
        }
        line_val = entry.get("line") or entry.get("_line")
        tags.append(
            Tag(
                name=str(entry["name"]),
                path=Path(str(entry["path"])),
                line=line_val if isinstance(line_val, int) else None,
                kind=str(entry.get("kind")) if entry.get("kind") else None,
                pattern=str(entry["pattern"]) if entry.get("pattern") else None,
                fields=fields,
            )
        )
    return tags
