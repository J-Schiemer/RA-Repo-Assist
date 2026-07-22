"""Command line interface for ra."""

import argparse
import shutil
import subprocess
import sys

from ra.ctags import _find_ctags


def _check_ctags() -> None:
    """Check if ctags is installed and is universal-ctags."""
    ctags_bin = _find_ctags()
    if ctags_bin == "ctags" and shutil.which("ctags") is None:
        print("Error: ctags is not installed or not in PATH", file=sys.stderr)
        print("Please install universal-ctags to use ra:", file=sys.stderr)
        print("  macOS: brew install universal-ctags", file=sys.stderr)
        print("  Ubuntu/Debian: sudo apt-get install universal-ctags", file=sys.stderr)
        print("  Fedora/RHEL: sudo dnf install ctags", file=sys.stderr)
        sys.exit(1)

    # Verify it's universal-ctags, not BSD ctags
    try:
        result = subprocess.run(
            [ctags_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version_output = result.stdout.lower()
        if "universal" not in version_output and "uctags" not in version_output:
            print("Error: found BSD ctags, but ra requires universal-ctags", file=sys.stderr)
            print("", file=sys.stderr)
            print("macOS has two ctags versions. Install universal-ctags:", file=sys.stderr)
            print("  brew install universal-ctags", file=sys.stderr)
            print("", file=sys.stderr)
            print("After installing, ensure it's first in your PATH:", file=sys.stderr)
            print("  export PATH=\"/opt/homebrew/opt/universal-ctags/bin:$PATH\"", file=sys.stderr)
            sys.exit(1)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ra",
        description="Generate compact repository overviews for LLMs using ctags",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )

    sub = parser.add_subparsers(dest="command")

    # --- help ---
    sub.add_parser(
        "help",
        help="Show help message",
        description="Show help message for ra",
    )

    # --- init ---
    init_parser = sub.add_parser(
        "init",
        help="Initialize ra configuration in a project",
        description="Set up .ra folder with config and ignore files for a project",
    )
    init_parser.add_argument(
        "-d", "--dir",
        default=".",
        help="Directory to initialize in (default: current directory)",
    )

    # --- overview (future, kept as placeholder) ---
    overview_parser = sub.add_parser(
        "overview",
        help="Generate a repository overview (default command)",
        description="Generate a compact markdown overview of a repository",
    )
    overview_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to repository (default: current directory)",
    )
    overview_parser.add_argument(
        "-o", "--output",
        help="Output file (default: .ra/out/overview.md)",
    )
    overview_parser.add_argument(
        "-t", "--type",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    args = parser.parse_args()

    if args.command == "init":
        _check_ctags()
        from ra.commands.init import run_init
        run_init(args)
    elif args.command == "overview":
        _check_ctags()
        from ra.commands.overview import run_overview
        run_overview(args)
    elif args.command == "help":
        parser.print_help()
        # Show ctags warning when displaying help (but don't exit with failure)
        ctags_bin = _find_ctags()
        if ctags_bin == "ctags" and shutil.which("ctags") is None:
            print("\nWarning: ctags is not installed or not in PATH", file=sys.stderr)
            print("ra requires universal-ctags to generate repository overviews.", file=sys.stderr)
            print("Install universal-ctags to use ra commands:", file=sys.stderr)
            print("  macOS: brew install universal-ctags", file=sys.stderr)
            print("  Ubuntu/Debian: sudo apt-get install universal-ctags", file=sys.stderr)
            print("  Fedora/RHEL: sudo dnf install ctags", file=sys.stderr)
    else:
        parser.print_help()
        sys.exit(1)
