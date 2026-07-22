"""Overview generation command for ra."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from ra.overview import generate_overview


def run_overview(args: object) -> None:
    """Run the overview generation command."""
    path = Path(args.path).resolve()  # type: ignore[attr-defined]
    output_type: str = getattr(args, "type", "markdown")  # type: ignore[attr-defined]
    output_file: str | None = getattr(args, "output", None)  # type: ignore[attr-defined]

    try:
        result = asyncio.run(generate_overview(path, output_type))
    except Exception as e:
        print(f"Error generating overview: {e}", file=sys.stderr)
        sys.exit(1)

    if output_file:
        out_path = Path(output_file)
    else:
        out_path = path / ".ra" / "out" / f"overview.{'md' if output_type == 'markdown' else 'json'}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result)
    print(f"Overview written to {out_path}")
