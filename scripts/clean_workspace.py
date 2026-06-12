"""Safely inspect or clean generated workspace artifacts.

By default this script only reports candidates. Use --apply to delete safe
generated artifacts inside the current repository.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".pycache_compile",
}
FILE_NAMES = {".DS_Store", ".coverage"}
VENV_NAMES = {".venv", ".venv-win", "venv"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or clean generated files.")
    parser.add_argument("--apply", action="store_true", help="Actually delete safe artifacts.")
    parser.add_argument(
        "--include-venv",
        action="store_true",
        help="Also remove .venv/.venv-win when they are clearly virtualenvs.",
    )
    args = parser.parse_args()

    candidates = _find_candidates(include_venv=args.include_venv)
    if not candidates:
        print("No cleanup candidates found.")
        return 0

    action = "Deleting" if args.apply else "Would delete"
    for path in candidates:
        print(f"{action}: {path.relative_to(ROOT)}")
        if args.apply:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    if not args.apply:
        print("Dry run only. Re-run with --apply to delete these generated artifacts.")
    return 0


def _find_candidates(*, include_venv: bool) -> list[Path]:
    candidates: list[Path] = []
    stack = [ROOT]
    while stack:
        current = stack.pop()
        for path in current.iterdir():
            if path.name == ".git":
                continue
            if path.is_dir() and path.name in VENV_NAMES:
                continue
            if path.is_dir() and path.name in DIR_NAMES:
                candidates.append(path)
                continue
            if path.is_file() and path.name in FILE_NAMES:
                candidates.append(path)
                continue
            if path.is_dir():
                stack.append(path)

    if include_venv:
        for name in (".venv", ".venv-win", "venv"):
            path = ROOT / name
            if _is_virtualenv(path):
                candidates.append(path)

    return _dedupe_nested(candidates)


def _is_virtualenv(path: Path) -> bool:
    return path.is_dir() and (path / "pyvenv.cfg").is_file()


def _dedupe_nested(paths: list[Path]) -> list[Path]:
    sorted_paths = sorted(paths, key=lambda p: len(p.parts))
    result: list[Path] = []
    for path in sorted_paths:
        if not any(parent in path.parents for parent in result):
            result.append(path)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
