"""Create clean release ZIP files for AVM v2."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import logging
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_NAME = "AVM v2"
RELEASE_PREFIX = "AVM_v2"
MODES = {"beta", "demo", "production"}

DEFAULT_INCLUDE_PATHS = [
    "api",
    "ui",
    "core",
    "domain",
    "infrastructure",
    "services",
    "workers",
    "config",
    "scripts",
    "audits",
    "alembic",
    "pyproject.toml",
    "Dockerfile.api",
    "Dockerfile.streamlit",
    "docker-compose.yml",
    "alembic.ini",
    "README.md",
    ".env.example",
]

REQUIRED_PATHS = [
    "pyproject.toml",
    "README.md",
    "api/main.py",
    "ui/app.py",
    "config/settings.py",
    "alembic.ini",
    "alembic/env.py",
    ".env.example",
]

ALWAYS_EXCLUDE_NAMES = {
    ".env",
    ".git",
    ".venv",
    ".venv-win",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".pytest_tmp",
    ".mypy_cache",
    ".ruff_cache",
    ".DS_Store",
    "logs",
    "reports",
    "htmlcov",
    ".coverage",
    "avm.egg-info",
    "releases",
    "backups",
    "node_modules",
    "dist",
    "build",
}

ALWAYS_EXCLUDE_PATTERNS = [
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
]

SENSITIVE_NAME_MARKERS = ("secret", "token", "key", "password", "credential")
DB_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
FORBIDDEN_DB_NAMES = {"tasador.db", "production.db", "avm.db"}


class ReleaseZipError(RuntimeError):
    """Raised when a release ZIP cannot be created safely."""


@dataclass(frozen=True)
class ReleaseOptions:
    mode: str
    dry_run: bool = False
    include_tests: bool = False
    include_docs: bool = False
    checksum: bool = False
    verbose: bool = False
    demo_db_path: Path | None = None


@dataclass(frozen=True)
class FileEntry:
    source: Path
    arcname: Path
    size: int


@dataclass
class ReleasePlan:
    included: list[FileEntry]
    excluded: list[str]
    warnings: list[str]
    demo_db_included: bool = False


def find_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> ReleaseOptions:
    parser = argparse.ArgumentParser(description="Create a clean AVM v2 release ZIP.")
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument("--include-docs", action="store_true")
    parser.add_argument("--checksum", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--demo-db-path", type=Path)
    args = parser.parse_args(argv)
    return ReleaseOptions(
        mode=args.mode,
        dry_run=args.dry_run,
        include_tests=args.include_tests,
        include_docs=args.include_docs,
        checksum=args.checksum,
        verbose=args.verbose,
        demo_db_path=args.demo_db_path,
    )


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def validate_required_paths(root: Path) -> None:
    missing = [rel for rel in REQUIRED_PATHS if not (root / rel).exists()]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise ReleaseZipError(f"Missing required release files:\n{formatted}")


def normalize_relative(path: Path) -> str:
    return path.as_posix()


def is_database_file(path: Path) -> bool:
    return path.suffix.lower() in DB_SUFFIXES


def is_excluded_path(rel_path: Path) -> bool:
    parts = set(rel_path.parts)
    if parts & ALWAYS_EXCLUDE_NAMES:
        return True
    name = rel_path.name
    return any(fnmatch.fnmatch(name, pattern) for pattern in ALWAYS_EXCLUDE_PATTERNS)


def has_sensitive_name(rel_path: Path) -> bool:
    for part in rel_path.parts:
        name = part.lower()
        if any(marker in name for marker in SENSITIVE_NAME_MARKERS):
            return True
    return False


def iter_files_for_path(root: Path, rel_path: str) -> tuple[list[Path], list[str]]:
    base = root / rel_path
    excluded: list[str] = []
    files: list[Path] = []
    if not base.exists():
        excluded.append(f"{rel_path} (missing optional include)")
        return files, excluded
    if base.is_file():
        return [base], excluded
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(root)
        if path.is_dir():
            if is_excluded_path(rel):
                excluded.append(normalize_relative(rel))
            continue
        files.append(path)
    return files, excluded


def collect_excluded_artifacts(root: Path) -> list[str]:
    excluded: list[str] = []

    def visit(directory: Path) -> None:
        try:
            children = sorted(directory.iterdir())
        except PermissionError:
            excluded.append(normalize_relative(directory.relative_to(root)))
            return
        for path in children:
            rel = path.relative_to(root)
            rel_display = normalize_relative(rel)
            if is_excluded_path(rel):
                excluded.append(rel_display)
                continue
            if path.is_dir():
                visit(path)

    visit(root)
    return excluded


def validate_demo_db(root: Path, options: ReleaseOptions) -> FileEntry | None:
    if options.demo_db_path is None:
        return None
    if options.mode != "demo":
        raise ReleaseZipError("--demo-db-path is only allowed with --mode demo.")

    db_path = options.demo_db_path
    source = db_path if db_path.is_absolute() else root / db_path
    source = source.resolve()
    try:
        source.relative_to(root.resolve())
    except ValueError as exc:
        raise ReleaseZipError("--demo-db-path must stay inside the project directory.") from exc

    if not source.exists() or not source.is_file():
        raise ReleaseZipError(f"Demo DB does not exist: {db_path}")
    if not is_database_file(source):
        raise ReleaseZipError("--demo-db-path must point to a .db, .sqlite, or .sqlite3 file.")
    if "demo" not in source.name.lower():
        raise ReleaseZipError("Demo DB file name must contain 'demo'.")
    if source.name.lower() in FORBIDDEN_DB_NAMES:
        raise ReleaseZipError(f"Forbidden database name for release: {source.name}")

    arcname = Path("data") / source.name
    return FileEntry(source=source, arcname=arcname, size=source.stat().st_size)


def build_release_plan(root: Path, options: ReleaseOptions) -> ReleasePlan:
    include_paths = list(DEFAULT_INCLUDE_PATHS)
    if options.include_tests:
        include_paths.append("tests")
    if options.include_docs:
        include_paths.append("docs")

    included_by_arcname: dict[Path, FileEntry] = {}
    excluded: list[str] = collect_excluded_artifacts(root)
    warnings: list[str] = []

    for include_path in include_paths:
        files, skipped = iter_files_for_path(root, include_path)
        excluded.extend(skipped)
        for source in files:
            rel = source.relative_to(root)
            rel_display = normalize_relative(rel)
            if is_excluded_path(rel):
                excluded.append(rel_display)
                continue
            if has_sensitive_name(rel):
                raise ReleaseZipError(f"Refusing to include sensitive-looking file name: {rel_display}")
            if is_database_file(rel):
                excluded.append(rel_display)
                continue
            included_by_arcname[rel] = FileEntry(source=source, arcname=rel, size=source.stat().st_size)

    demo_db_entry = validate_demo_db(root, options)
    demo_db_included = False
    if demo_db_entry is not None:
        included_by_arcname[demo_db_entry.arcname] = demo_db_entry
        demo_db_included = True
        warnings.append(
            f"Included demo database {normalize_relative(demo_db_entry.arcname)} from "
            f"{normalize_relative(demo_db_entry.source.relative_to(root))}."
        )

    included = sorted(included_by_arcname.values(), key=lambda entry: normalize_relative(entry.arcname))
    return ReleasePlan(
        included=included,
        excluded=sorted(set(excluded)),
        warnings=warnings,
        demo_db_included=demo_db_included,
    )


def get_git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    commit = result.stdout.strip()
    return commit or None


def build_manifest(
    root: Path,
    options: ReleaseOptions,
    plan: ReleasePlan,
    created_at: str,
    zip_size_bytes: int,
) -> dict[str, Any]:
    total_bytes = sum(entry.size for entry in plan.included)
    return {
        "project": PROJECT_NAME,
        "mode": options.mode,
        "created_at": created_at,
        "git_commit": get_git_commit(root),
        "python_version": sys.version.split()[0],
        "included_files_count": len(plan.included),
        "excluded_files_count": len(plan.excluded),
        "total_uncompressed_bytes": total_bytes,
        "zip_size_bytes": zip_size_bytes,
        "include_tests": options.include_tests,
        "include_docs": options.include_docs,
        "demo_db_included": plan.demo_db_included,
        "warnings": plan.warnings,
        "files": [
            {
                "path": normalize_relative(entry.arcname),
                "size_bytes": entry.size,
            }
            for entry in plan.included
        ],
    }


def release_zip_path(root: Path, mode: str, created_at: datetime | None = None) -> Path:
    stamp = (created_at or datetime.now()).strftime("%Y%m%d_%H%M")
    return root / "releases" / f"{RELEASE_PREFIX}_{mode}_{stamp}.zip"


def write_zip(
    root: Path,
    destination: Path,
    options: ReleaseOptions,
    plan: ReleasePlan,
    created_at: str,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {}
    previous_size = -1

    for _ in range(6):
        manifest = build_manifest(root, options, plan, created_at, max(previous_size, 0))
        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for entry in plan.included:
                archive.write(entry.source, normalize_relative(entry.arcname))
            archive.writestr("release_manifest.json", manifest_bytes)
        current_size = destination.stat().st_size
        if current_size == previous_size:
            break
        previous_size = current_size

    manifest = build_manifest(root, options, plan, created_at, destination.stat().st_size)
    return manifest


def write_checksum(zip_path: Path) -> Path:
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return checksum_path


def print_plan(plan: ReleasePlan) -> None:
    print("Files that would be included:")
    for entry in plan.included:
        print(f"  + {normalize_relative(entry.arcname)} ({entry.size} bytes)")
    print("\nFiles that would be excluded:")
    for rel_path in plan.excluded:
        print(f"  - {rel_path}")
    if plan.warnings:
        print("\nWarnings:")
        for warning in plan.warnings:
            print(f"  ! {warning}")


def create_release(root: Path, options: ReleaseOptions) -> Path | None:
    validate_required_paths(root)
    plan = build_release_plan(root, options)

    for warning in plan.warnings:
        logging.warning(warning)

    if options.dry_run:
        print_plan(plan)
        logging.info("Dry-run complete. No ZIP was created.")
        return None

    created_at_dt = datetime.now()
    created_at = datetime.now(UTC).isoformat()
    zip_path = release_zip_path(root, options.mode, created_at_dt)
    manifest = write_zip(root, zip_path, options, plan, created_at)

    logging.info("Created %s", zip_path)
    logging.info("Included %s files", manifest["included_files_count"])
    logging.info("Excluded %s files", manifest["excluded_files_count"])

    if options.checksum:
        checksum_path = write_checksum(zip_path)
        logging.info("Created checksum %s", checksum_path)

    return zip_path


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    configure_logging(options.verbose)
    root = find_project_root()
    try:
        create_release(root, options)
    except ReleaseZipError as exc:
        logging.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
