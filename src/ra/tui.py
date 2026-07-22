"""Textual TUI for ra interactive commands."""

from __future__ import annotations

import json
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    RadioSet,
    Static,
    TextArea,
)

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

STEP_TITLES = [
    "Select Languages",
    "Project Type",
    "Source Roots",
    "Exclude Patterns",
    "Summary",
]

DEFAULT_EXCLUDES = [
    "node_modules",
    "__pycache__",
    ".venv",
    ".git",
    "dist/**",
    "build/**",
    "*.min.js",
    ".mypy_cache",
    ".pytest_cache",
]


def _parse_languages(raw: str) -> list[str]:
    """Parse comma-separated language names, matching against known languages."""
    if not raw.strip():
        return list(LANGUAGES)

    raw_lower = raw.strip().lower()
    if raw_lower == "all":
        return list(LANGUAGES)

    picked: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        matched = [lang for lang in LANGUAGES if lang.lower() == part.lower()]
        if matched:
            picked.append(matched[0])
        else:
            picked.append(part)
    return picked or list(LANGUAGES)


class InitWizard(App):
    """Textual app for the ra init wizard."""

    BUTTON_BACK = "← Back"
    BUTTON_NEXT = "Next →"
    BUTTON_FINISH = "✓ Finish"

    CSS = """
    Screen {
        layout: vertical;
    }

    #step-container {
        height: 1fr;
        padding: 1 2;
    }

    .step {
        height: 1fr;
    }

    #step-title {
        dock: top;
        padding: 0 0 1 0;
        text-style: bold;
        color: $accent;
    }

    #nav-buttons {
        dock: bottom;
        height: auto;
        padding: 1 0;
        align: center middle;
    }

    #nav-buttons Button {
        margin: 0 1;
        min-width: 14;
    }

    .step-instructions {
        margin: 0 0 1 0;
        width: 100%;
    }

    #lang-input {
        width: 100%;
    }

    #lang-preview {
        margin: 1 0 0 0;
        height: auto;
        max-height: 12;
        overflow-y: auto;
        border: solid $accent;
        padding: 0 1;
    }

    RadioSet {
        width: 100%;
    }

    Input {
        width: 100%;
    }

    #excludes-input {
        height: 1fr;
        max-height: 15;
    }

    #summary-content {
        height: 1fr;
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
    ]

    def __init__(self, target: Path) -> None:
        self.target = target
        self.current_step = 0
        self.total_steps = len(STEP_TITLES)
        self.selected_languages: list[str] = []
        self.is_monorepo: bool = False
        self.source_roots: list[dict[str, str]] = []
        self.excludes: list[str] = []
        self._sr_count = 1
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header()

        with Vertical(id="step-container"):
            yield Static("", id="step-title")

            # Step 0: Languages
            with Vertical(id="step-0", classes="step"):
                yield Static(
                    "[bold]Which languages does your project use?[/]\n"
                    "[dim]Enter comma-separated names, or 'all' for every language.[/]",
                    classes="step-instructions",
                )
                yield Input(placeholder="e.g. Python, JavaScript, TypeScript", id="lang-input")
                yield Static(self._lang_list_text(), id="lang-preview")

            # Step 1: Monorepo
            with Vertical(id="step-1", classes="step"):
                yield Static(
                    "[bold]Is this a monorepo with multiple separate projects?[/]",
                    classes="step-instructions",
                )
                yield RadioSet(
                    "No — single project",
                    "Yes — multiple projects",
                    id="monorepo-radio",
                )

            # Step 2: Source Roots
            with Vertical(id="step-2", classes="step"):
                yield Static("[bold]Source root(s):[/]", classes="step-instructions")
                yield Label("Source root (path relative to project):", id="sr-label")
                yield Input(placeholder=".", id="sr-input-0")
                yield Static(
                    "[dim]Use '.' for the project root itself.[/]",
                    id="sr-hint",
                )

            # Step 3: Excludes
            with Vertical(id="step-3", classes="step"):
                yield Static(
                    "[bold]Folders/files to exclude:[/]\n"
                    "[dim]Common patterns are pre-filled. Edit as needed, one per line.[/]\n"
                    "[dim]Supports: [bold]*[/][dim] (single level), "
                    "[bold]**[/][dim] (multiple levels).[/]",
                    classes="step-instructions",
                )
                yield TextArea("\n".join(DEFAULT_EXCLUDES), id="excludes-input")

            # Step 4: Summary
            with Vertical(id="step-4", classes="step"):
                yield Static("[bold]Configuration Summary[/]\n", classes="step-instructions")
                yield Static("Loading...", id="summary-content")

        yield Horizontal(
            Button(self.BUTTON_BACK, id="btn-back", variant="default"),
            Button(self.BUTTON_NEXT, id="btn-next", variant="primary"),
            id="nav-buttons",
        )
        yield Footer()

    def _lang_list_text(self) -> str:
        """Render the available languages as a compact grid."""
        cols = 4
        lines = []
        for i in range(0, len(LANGUAGES), cols):
            chunk = LANGUAGES[i : i + cols]
            lines.append("  ".join(f"[dim]{l}[/]" for l in chunk))
        return "\n".join(lines)

    def on_mount(self) -> None:
        self._update_ui()

    def _show_step(self, step: int) -> None:
        for i in range(self.total_steps):
            widget = self.query_one(f"#step-{i}")
            widget.display = i == step

    def _update_ui(self) -> None:
        title = self.query_one("#step-title")
        title.update(
            f"Step {self.current_step + 1}/{self.total_steps}: "
            f"{STEP_TITLES[self.current_step]}"
        )
        self._show_step(self.current_step)

        btn_back = self.query_one("#btn-back")
        btn_next = self.query_one("#btn-next")
        btn_back.disabled = self.current_step == 0

        if self.current_step == self.total_steps - 1:
            btn_next.label = self.BUTTON_FINISH
            btn_next.variant = "success"
            self._update_summary()
        else:
            btn_next.label = self.BUTTON_NEXT
            btn_next.variant = "primary"

    def _update_summary(self) -> None:
        self._gather_data()
        lines = [
            f"[bold]Languages:[/] {', '.join(self.selected_languages) or '(all)'}",
            f"[bold]Monorepo:[/] {'Yes' if self.is_monorepo else 'No'}",
            "[bold]Source roots:[/]",
        ]
        for sr in self.source_roots:
            lines.append(f"  {sr['name']}: [dim]{sr['root']}[/]")
        if self.excludes:
            lines.append("[bold]Excludes:[/]")
            for pat in self.excludes:
                lines.append(f"  [dim]{pat}[/]")
        else:
            lines.append("[bold]Excludes:[/] (none)")
        self.query_one("#summary-content").update("\n".join(lines))

    def _gather_data(self) -> None:
        # Languages
        lang_input = self.query_one("#lang-input", Input)
        self.selected_languages = _parse_languages(lang_input.value)

        # Monorepo
        try:
            radio = self.query_one("#monorepo-radio", RadioSet)
            self.is_monorepo = radio.pressed_index == 1
        except Exception:
            self.is_monorepo = False

        # Source roots
        self.source_roots = []
        inputs = [inp for inp in self.query(Input) if inp.id and inp.id.startswith("sr-input-")]
        for inp in inputs:
            val = inp.value.strip() or "."
            idx = inp.id.removeprefix("sr-input-")
            self.source_roots.append({"name": f"project-{idx}", "root": val})

        # Excludes
        try:
            textarea = self.query_one("#excludes-input", TextArea)
            self.excludes = [
                line.strip()
                for line in textarea.text.splitlines()
                if line.strip()
            ]
        except Exception:
            self.excludes = []

    async def _update_source_roots(self) -> None:
        """Rebuild source root inputs based on monorepo setting."""
        container = self.query_one("#step-2")

        count = 2 if self.is_monorepo else 1
        self._sr_count = count
        hint = container.query_one("#sr-hint")

        async with container.batch():
            await container.remove_children(Input)
            for i in range(count):
                await container.mount(
                    Input(placeholder=".", id=f"sr-input-{i}"),
                    before=hint,
                )

    @on(Button.Pressed, "#btn-back")
    def on_back(self) -> None:
        if self.current_step > 0:
            self.current_step -= 1
            self._update_ui()

    @on(Button.Pressed, "#btn-next")
    async def on_next(self) -> None:
        if self.current_step < self.total_steps - 1:
            if self.current_step == 1:
                await self._update_source_roots()
            self.current_step += 1
            self._update_ui()
        else:
            self._finish()

    @on(RadioSet.Changed, "#monorepo-radio")
    def on_monorepo_changed(self, event: RadioSet.Changed) -> None:
        self.is_monorepo = event.radio_set.pressed_index == 1

    @on(Input.Changed, "#lang-input")
    def on_lang_changed(self, event: Input.Changed) -> None:
        picked = _parse_languages(event.value)
        preview = self.query_one("#lang-preview")
        if picked == LANGUAGES:
            preview.update(f"[bold green]All {len(LANGUAGES)} languages selected[/]")
        else:
            preview.update(f"[bold]{len(picked)} languages:[/] {', '.join(picked)}")

    def _finish(self) -> None:
        self._gather_data()

        if self.source_roots and len(self.source_roots) == 1:
            self.source_roots[0]["name"] = self.target.name

        ra_dir = self.target / ".ra"
        ra_dir.mkdir(parents=True, exist_ok=True)
        (ra_dir / "out").mkdir(exist_ok=True)

        config = {
            "languages": self.selected_languages or list(LANGUAGES),
            "source_roots": self.source_roots,
            "output_dir": ".ra/out",
        }

        config_path = ra_dir / ".raconfig"
        config_path.write_text(json.dumps(config, indent=2) + "\n")

        ignore_path = ra_dir / ".raignore"
        if self.excludes:
            ignore_path.write_text("\n".join(self.excludes) + "\n")
        else:
            ignore_path.write_text("")

        self.notify(
            f"Initialized ra in {ra_dir}",
            title="Success",
            severity="information",
            timeout=3,
        )
        self.exit(result=config)
