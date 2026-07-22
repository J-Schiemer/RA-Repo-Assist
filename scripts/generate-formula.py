#!/usr/bin/env python3
"""Generate a Homebrew formula for ra from pyproject.toml and uv.lock."""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

TEMPLATE = '''\
class Ra < Formula
  include Language::Python::Virtualenv

  desc "{description}"
  homepage "{homepage}"
  url "https://github.com/{repo}/archive/refs/tags/v{version}.tar.gz"
  sha256 "{source_sha}"
  license "{license}"

  depends_on "python@3.12"
  depends_on "universal-ctags"

{resources}
  def install
    virtualenv_install_with_resources
  end

  test do
    system bin/"ra", "--version"
  end
end
'''

RESOURCE_TEMPLATE = """\
  resource "{name}" do
    url "{url}"
    sha256 "{sha}"
  end
"""


def run(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, **kwargs)


def parse_pyproject(path: Path) -> dict:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    proj = data["project"]

    repo = _guess_repo()
    if not repo:
        sys.exit("Could not determine GitHub repo URL from git remote")

    deps = []
    for dep_spec in proj.get("dependencies", []):
        deps.append(re.split(r"[<>=!~;]", dep_spec.strip())[0].strip())

    desc = _sanitize_desc(proj.get("description", ""))

    return {
        "name": proj["name"],
        "version": proj["version"],
        "description": desc,
        "license": "MIT",
        "homepage": repo,
        "repo": repo.rstrip("/").removeprefix("https://github.com/"),
        "requires_python": proj.get("requires-python", ">=3.11"),
        "deps": deps,
    }


def _sanitize_desc(desc: str) -> str:
    desc = desc.strip()
    for article in ("A ", "An ", "The "):
        if desc.startswith(article):
            desc = desc[len(article):]
            break
    desc = desc.replace("command line", "command-line").replace("Command line", "Command-line")
    desc = desc[0].upper() + desc[1:]
    return desc


def _guess_repo() -> str:
    try:
        remote = run(["git", "remote", "get-url", "origin"], cwd=REPO_DIR).stdout.strip()
        m = re.match(r"(?:git@github\.com:|https://github\.com/)(.+)", remote)
        if m:
            return "https://github.com/" + m.group(1).removesuffix(".git")
    except subprocess.CalledProcessError:
        pass
    return ""


def parse_uv_lock(path: Path) -> list[dict]:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    packages = {}
    for pkg in data.get("package", []):
        pkg_name = pkg["name"]
        sdist = pkg.get("sdist", {})
        packages[pkg_name] = {
            "name": pkg_name,
            "version": pkg.get("version", ""),
            "sdist_url": sdist.get("url", ""),
            "sdist_sha": sdist.get("hash", "").removeprefix("sha256:"),
            "deps": pkg.get("dependencies", []),
            "optional_deps": pkg.get("optional-dependencies", {}),
        }

    ra_pkg = packages.get("ra")
    if not ra_pkg:
        sys.exit("Package 'ra' not found in uv.lock")

    dep_queue = list(ra_pkg["deps"])
    seen = {"ra"}
    resources: list[dict] = []

    while dep_queue:
        dep_spec = dep_queue.pop(0)
        dep_name = dep_spec["name"] if isinstance(dep_spec, dict) else dep_spec
        extras = dep_spec.get("extra", []) if isinstance(dep_spec, dict) else []

        if dep_name in seen:
            continue
        seen.add(dep_name)

        pkg = packages.get(dep_name)
        if not pkg or not pkg["sdist_url"]:
            continue

        resources.append({
            "name": pkg["name"],
            "url": pkg["sdist_url"],
            "sha": pkg["sdist_sha"],
        })

        for d in pkg["deps"]:
            d_name = d["name"] if isinstance(d, dict) else d
            if d_name not in seen:
                dep_queue.append(d)

        for extra_name in extras:
            for opt_dep in pkg.get("optional_deps", {}).get(extra_name, []):
                opt_name = opt_dep["name"] if isinstance(opt_dep, dict) else opt_dep
                if opt_name not in seen:
                    dep_queue.append({"name": opt_name})

    return _topo_sort(
        resources,
        {r["name"]: [d["name"] if isinstance(d, dict) else d for d in packages.get(r["name"], {}).get("deps", [])] for r in resources},
    )


def _topo_sort(resources: list[dict], dep_graph: dict) -> list[dict]:
    name_to_res = {r["name"]: r for r in resources}
    visited = set()
    result = []

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        for d in dep_graph.get(name, []):
            if d in name_to_res:
                visit(d)
        result.append(name_to_res[name])

    for r in resources:
        visit(r["name"])
    return result


def compute_source_sha(version: str, create_tag: bool = False) -> str:
    tag = f"v{version}"
    try:
        run(["git", "rev-parse", tag], cwd=REPO_DIR, check=False)
    except subprocess.CalledProcessError:
        if create_tag:
            run(["git", "tag", "-a", tag, "-m", f"v{version} release"], cwd=REPO_DIR)
        else:
            sys.exit(f"Tag {tag} does not exist. Create it first or use --tag.")

    result = subprocess.run(
        ["git", "archive", "--format=tar.gz", f"--prefix=ra-{version}/", tag],
        cwd=REPO_DIR,
        capture_output=True,
        check=True,
    )
    return hashlib.sha256(result.stdout).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Homebrew formula for ra")
    parser.add_argument(
        "--tap-dir", type=Path, default=None,
        help="Path to homebrew tap repo (e.g. ~/homebrew-ra). Writes formula and commits.",
    )
    parser.add_argument(
        "--tag", action=argparse.BooleanOptionalAction, default=False,
        help="Create git tag if missing (default: --no-tag)",
    )
    parser.add_argument(
        "--push", action=argparse.BooleanOptionalAction, default=False,
        help="Push tag and tap repo commit (default: --no-push)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print formula to stdout, do not write any files",
    )
    args = parser.parse_args()

    meta = parse_pyproject(REPO_DIR / "pyproject.toml")
    version = meta["version"]
    print(f"[1/3] Version: {version}")

    resources = parse_uv_lock(REPO_DIR / "uv.lock")
    print(f"[2/3] Resources: {len(resources)} packages")

    source_sha = compute_source_sha(version, create_tag=args.tag)
    print(f"[3/3] Source SHA256: {source_sha}")

    formula = TEMPLATE.format(
        description=meta["description"],
        homepage=meta["homepage"],
        repo=meta["repo"],
        version=meta["version"],
        source_sha=source_sha,
        license=meta["license"],
        resources="\n".join(RESOURCE_TEMPLATE.format(**r) for r in resources),
    )

    if args.dry_run:
        print("\n--- Formula ---\n")
        print(formula)
        return

    output_path = REPO_DIR / "Formula" / "ra.rb"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(formula)
    print(f"  Written: {output_path}")

    if args.tag:
        tag = f"v{version}"
        try:
            run(["git", "push", "origin", tag], cwd=REPO_DIR)
            print(f"  Pushed tag: {tag}")
        except subprocess.CalledProcessError as e:
            print(f"  Warning: could not push tag: {e.stderr.strip()}")

    if args.tap_dir:
        tap_dir = args.tap_dir.resolve()
        dest = tap_dir / "Formula" / "ra.rb"
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(formula)
        run(["git", "add", "Formula/ra.rb"], cwd=tap_dir)
        try:
            run(["git", "commit", "-m", f"ra {version}"], cwd=tap_dir)
            print(f"  Committed in: {tap_dir}")
        except subprocess.CalledProcessError:
            print("  Nothing to commit (formula unchanged)")
        if args.push:
            run(["git", "push"], cwd=tap_dir)
            print(f"  Pushed: {tap_dir}")
    else:
        print(f"\nTo publish, copy {output_path} to your tap repo or re-run with --tap-dir.")


if __name__ == "__main__":
    main()
