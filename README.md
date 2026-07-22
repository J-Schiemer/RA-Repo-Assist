# ra - repo assist

A command line tool that generates compact markdown overviews of repositories for LLMs, using ctags to extract structure and symbols.

## Why

When working with LLMs on large codebases, you waste tokens sending file contents that could be summarized. `ra` generates a structured overview of a repository — directory tree, key symbols, dependencies — so the LLM gets context without the bloat.

## Install

### Homebrew

```bash
brew tap J-Schiemer/ra
brew install ra
```

### uv

```bash
uv tool install ra
```

### pip

```bash
pip install ra
```

## Usage

```bash
# Initialize ra in current directory
ra init

# Initialize in a specific directory
ra init -d ./my-project

# Generate overview (output goes to .ra/out/)
ra overview
ra overview ./src
ra overview -o overview.md
```

### Output

Generated overviews are saved to `.ra/out/` by default (created during `ra init`).

## Development

```bash
# Clone
git clone git@github.com:J-Schiemer/RA-Repo-Assist.git
cd RA-Repo-Assist

# Install deps
uv sync

# Run
uv run ra .
```

## License

MIT
