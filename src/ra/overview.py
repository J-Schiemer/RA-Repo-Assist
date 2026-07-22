"""Async overview generation for ra."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

from ra.ctags import Ctags, Tag

_CODE_BLOCK_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".php": "php",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown",
    ".r": "r",
    ".R": "r",
    ".lua": "lua",
    ".vim": "vim",
    ".el": "elisp",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".clj": "clojure",
    ".scala": "scala",
    ".dart": "dart",
}

_IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".ra", ".raignore"}


async def _get_project_name(path: Path) -> str:
    """Get project name from git remote or fall back to directory name."""
    if shutil.which("git") is None:
        return path.name

    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(path),
        "remote",
        "get-url",
        "origin",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode == 0:
        url = stdout.decode().strip()
        name = url.rstrip("/").rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[:-4]
        return name

    return path.name


def _load_config(path: Path) -> list[dict[str, str]] | None:
    """Load source roots from .raconfig, or None if not found."""
    config_path = path / ".ra" / ".raconfig"
    if not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text())
        return data.get("source_roots")
    except (json.JSONDecodeError, KeyError):
        return None


def _load_raignore(root: Path) -> set[str]:
    """Load ignore patterns from .ra/.raignore."""
    ignore_path = root / ".ra" / ".raignore"
    if not ignore_path.exists():
        return set()
    return {
        line.strip().replace("\\", "/")
        for line in ignore_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def _matches_pattern(rel: str, pattern: str) -> bool:
    """Check if a relative path matches an ignore pattern.

    Handles ** (recursive wildcard), * (single component), and exact names.
    """
    if "**" in pattern:
        prefix, suffix = pattern.split("**", 1)
        prefix = prefix.rstrip("/")
        suffix = suffix.lstrip("/")
        if prefix and not rel.startswith(prefix):
            return False
        if suffix:
            remainder = rel[len(prefix):].lstrip("/")
            if "**" in suffix:
                return _matches_pattern(remainder, suffix)
            return fnmatch.fnmatch(remainder, suffix) or any(
                fnmatch.fnmatch(part, suffix) for part in remainder.split("/")
            )
        return True
    return fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel.rsplit("/", 1)[-1], pattern)


def _is_ignored(rel: str, ignore: set[str] | None) -> bool:
    """Check if a relative path should be ignored."""
    parts = rel.split("/")
    for part in parts:
        if part in _IGNORED_DIRS or part.startswith("."):
            return True
    if ignore:
        for pattern in ignore:
            if _matches_pattern(rel, pattern):
                return True
    return False


def _build_tree(
    root: Path, prefix: str = "", ignore: set[str] | None = None, _rel: str = "",
) -> list[str]:
    """Build a directory tree listing, skipping ignored directories."""
    lines: list[str] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        return lines

    for i, entry in enumerate(entries):
        entry_rel = f"{_rel}/{entry.name}" if _rel else entry.name
        if _is_ignored(entry_rel, ignore):
            continue
        is_last = i == len(entries) - 1 or all(
            _is_ignored(
                f"{_rel}/{e.name}" if _rel else e.name, ignore
            )
            for e in entries[i + 1 :]
        )
        connector = "└── " if is_last else "├── "
        if entry.is_dir():
            lines.append(f"{prefix}{connector}{entry.name}/")
            extension = "    " if is_last else "│   "
            lines.extend(_build_tree(entry, prefix + extension, ignore, entry_rel))
        else:
            lines.append(f"{prefix}{connector}{entry.name}")
    return lines


def _extract_docstrings(path: Path, tags: list[Tag]) -> dict[int, str]:
    """Extract documentation from docstrings and comments near definitions.

    Handles:
      - Python triple-quoted docstrings after def/class
      - Javadoc/JSDoc (block comments) before def/class/method
      - Single-line comment docs (//, #, --) before definitions

    Returns a mapping of line number -> docstring text.
    """
    try:
        raw = path.read_text()
    except (OSError, UnicodeDecodeError):
        return {}
    lines = raw.splitlines()

    docstrings: dict[int, str] = {}
    for tag in tags:
        if tag.kind not in {"function", "class", "method"} or tag.line is None:
            continue
        def_line_idx = tag.line - 1
        if def_line_idx < 0 or def_line_idx >= len(lines):
            continue

        # --- Try 1: look backward for comment block before definition ---
        found_comment = _extract_leading_comment(lines, def_line_idx)
        if found_comment:
            docstrings[tag.line] = found_comment
            continue

        # --- Try 2: look forward for triple-quoted docstring after definition ---
        found_docstring = _extract_trailing_docstring(lines, def_line_idx)
        if found_docstring:
            docstrings[tag.line] = found_docstring

    return docstrings


def _extract_leading_comment(lines: list[str], def_line_idx: int) -> str | None:
    """Extract a documentation comment block immediately before a definition.

    Supports multi-line block comments (/** */ and /* */) and
    consecutive single-line comments (// or #).
    """
    idx = def_line_idx - 1
    while idx >= 0 and not lines[idx].strip():
        idx -= 1
    if idx < 0:
        return None

    stripped = lines[idx].strip()

    # Multi-line block comment ending on this line (e.g. Javadoc /** ... */)
    if stripped.endswith("*/"):
        end = idx
        # Find matching opening /*
        while idx >= 0:
            if "/*" in lines[idx]:
                # Handle single-line: /** ... */
                if lines[idx].strip().startswith("/*"):
                    return _clean_block_comment("\n".join(lines[idx : end + 1]))
                # Opening /* is on a different line from */
                return _clean_block_comment("\n".join(lines[idx : end + 1]))
            idx -= 1
        return None

    # Consecutive single-line comment block (// or #)
    if stripped.startswith("//") or stripped.startswith("#") or stripped.startswith("--"):
        delimiter = "//" if stripped.startswith("//") else (
            "#" if stripped.startswith("#") else "--"
        )
        block_lines: list[str] = []
        while idx >= 0 and lines[idx].strip().startswith(delimiter):
            line = lines[idx].strip()
            text = line[len(delimiter) :]
            # Strip leading/trailing space and trailing # or / chars from ctags patterns
            text = text.strip().rstrip("#").rstrip("/").strip()
            if text:
                block_lines.append(text)
            idx -= 1
        if block_lines:
            block_lines.reverse()
            return "\n".join(block_lines)
    return None


def _clean_block_comment(text: str) -> str:
    """Extract meaningful text from a block comment (/** */, /* */, etc.)."""
    lines = text.splitlines()
    cleaned: list[str] = []
    for line in lines:
        line = line.strip()
        # Strip leading comment markers
        for prefix in ("/**", "/*", "*/", " * ", "* "):
            if line.startswith(prefix):
                line = line[len(prefix) :]
                break
        # Strip trailing */
        if line.endswith("*/"):
            line = line[:-2].rstrip()
        line = line.strip()
        # Skip empty lines or lines that are just asterisks
        if line and line != "*":
            cleaned.append(line)
    return "\n".join(cleaned)


def _extract_trailing_docstring(lines: list[str], def_line_idx: int) -> str | None:
    """Extract a Python triple-quoted docstring after a definition."""
    idx = def_line_idx
    paren_depth = 0
    found_colon = False
    while idx < len(lines) and idx < def_line_idx + 20:
        line = lines[idx]
        for ch in line:
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth -= 1
            elif ch == ":" and paren_depth <= 0:
                found_colon = True
                break
        if found_colon:
            break
        idx += 1

    if not found_colon:
        return None

    idx += 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    if idx >= len(lines):
        return None

    first_line = lines[idx].strip()
    docstring_lines: list[str] = []

    for quote in ('"""', "'''"):
        if first_line.startswith(quote):
            if first_line.endswith(quote) and len(first_line) > 3:
                docstring_lines = [first_line[3:-3].strip()]
            else:
                docstring_lines.append(first_line[3:].strip())
                idx += 1
                while idx < len(lines):
                    line = lines[idx]
                    if quote in line:
                        before = line.split(quote, 1)[0].strip()
                        if before:
                            docstring_lines.append(before)
                        break
                    docstring_lines.append(line.strip())
                    idx += 1
            break

    if docstring_lines:
        return "\n".join(docstring_lines)
    return None


def _format_markdown(
    project_name: str,
    source_roots: list[dict[str, str]],
    root: Path,
    file_tags: dict[str, list[Tag]],
    docstrings: dict[str, dict[int, str]],
) -> str:
    """Format tags into a markdown overview."""
    parts: list[str] = []
    parts.append(f"# {project_name}\n")

    ignore = _load_raignore(root)

    # Project structure section.
    parts.append("## Project Structure\n")
    for sr in source_roots:
        sr_path = root / sr["root"]
        if sr_path.is_dir():
            parts.append(f"- **{sr['name']}/**")
            tree = _build_tree(sr_path, ignore=ignore)
            for line in tree:
                parts.append(f"  {line}")
    parts.append("")

    # Per-source-root sections.
    for sr in source_roots:
        sr_name = sr["name"]
        sr_path = root / sr["root"]
        if not sr_path.is_dir():
            continue

        parts.append(f"## {sr_name}/\n")

        tree = _build_tree(sr_path, ignore=ignore)
        if tree:
            parts.append("```")
            parts.append(f"{sr_name}/")
            for line in tree:
                parts.append(line)
            parts.append("```\n")

        for file_path_str in sorted(file_tags):
            if _is_ignored(file_path_str, ignore):
                continue
            tags_for_file = sorted(
                file_tags[file_path_str],
                key=lambda t: t.line or 0,
            )
            parts.append(f"### {file_path_str}\n")

            ext = Path(file_path_str).suffix
            lang = _CODE_BLOCK_LANG.get(ext, "")
            block = f"```{lang}" if lang else "```"
            parts.append(block)

            for tag in tags_for_file:
                signature = tag.pattern or tag.name
                # Clean up ctags pattern markers.
                if signature.startswith("/^"):
                    signature = signature[2:]
                if signature.endswith("$/"):
                    signature = signature[:-2]
                signature = signature.strip()
                parts.append(signature)

                # Add docstring if available.
                abs_path = root / sr["root"] / file_path_str
                ds_map = docstrings.get(str(abs_path.resolve()), {})
                if tag.line and tag.line in ds_map:
                    parts.append(f'    """{ds_map[tag.line]}"""')

            parts.append("```\n")

    return "\n".join(parts)


async def generate_overview(path: Path, output_type: str) -> str:
    """Generate a repository overview.

    Args:
        path: Root directory of the project.
        output_type: "markdown" or "json".

    Returns:
        The overview as a string.
    """
    project_name = await _get_project_name(path)
    source_roots = _load_config(path)
    if source_roots is None:
        source_roots = [{"name": path.name, "root": "."}]

    ctags = Ctags(path)
    all_tags_raw = await ctags.run()

    # Pre-resolve all tag paths once to avoid repeated filesystem calls.
    resolved: dict[Path, list[Tag]] = defaultdict(list)
    for tag in all_tags_raw:
        resolved[tag.path.resolve()].append(tag)

    # Group tags by source root and build file-level tag dict.
    all_tags: dict[str, list[Tag]] = defaultdict(list)
    file_tags: dict[str, list[Tag]] = defaultdict(list)
    docstrings: dict[str, dict[int, str]] = {}

    for sr in source_roots:
        sr_path = (path / sr["root"]).resolve()
        sr_tags: list[Tag] = []
        for fpath, tags_at_file in resolved.items():
            try:
                rel = fpath.relative_to(sr_path)
            except ValueError:
                continue
            sr_tags.extend(tags_at_file)
            file_key = str(rel)
            file_tags[file_key].extend(tags_at_file)
            # Extract docstrings for files with function/class/method tags.
            if any(t.kind in {"function", "class", "method"} for t in tags_at_file):
                ds = _extract_docstrings(fpath, tags_at_file)
                if ds:
                    docstrings[str(fpath)] = ds
        all_tags[sr["root"]] = sr_tags

    if output_type == "json":
        return _format_json(project_name, source_roots, all_tags, docstrings)

    return _format_markdown(project_name, source_roots, path, file_tags, docstrings)


def _format_json(
    project_name: str,
    source_roots: list[dict[str, str]],
    all_tags: dict[str, list[Tag]],
    docstrings: dict[str, dict[int, str]],
) -> str:
    """Format tags into a JSON overview."""
    tags_data: dict[str, list[dict[str, object]]] = {}
    for root, tags in all_tags.items():
        tags_list: list[dict[str, object]] = []
        for t in tags:
            entry: dict[str, object] = {
                "name": t.name,
                "path": str(t.path),
                "line": t.line,
                "kind": t.kind,
                "pattern": t.pattern,
                "fields": t.fields,
            }
            # Include docstring if available.
            file_ds = docstrings.get(str(t.path.resolve()), {})
            if t.line and t.line in file_ds:
                entry["docstring"] = file_ds[t.line]
            tags_list.append(entry)
        tags_data[root] = tags_list

    data: dict[str, object] = {
        "project_name": project_name,
        "source_roots": source_roots,
        "tags": tags_data,
    }
    return json.dumps(data, indent=2)
