from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.create_release_zip import (
    ReleaseOptions,
    ReleaseZipError,
    build_release_plan,
    create_release,
)


def write_file(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_minimal_project(root: Path) -> None:
    for rel_path in [
        "pyproject.toml",
        "README.md",
        "api/main.py",
        "ui/app.py",
        "config/settings.py",
        "alembic.ini",
        "alembic/env.py",
        ".env.example",
        "core/__init__.py",
        "domain/__init__.py",
        "infrastructure/__init__.py",
        "services/__init__.py",
        "workers/__init__.py",
        "scripts/__init__.py",
        "audits/__init__.py",
    ]:
        write_file(root / rel_path)


def test_excludes_env_file(tmp_path: Path) -> None:
    make_minimal_project(tmp_path)
    write_file(tmp_path / ".env", "JWT_SECRET_KEY=real-secret")

    plan = build_release_plan(tmp_path, ReleaseOptions(mode="beta"))

    assert ".env" in plan.excluded
    assert ".env" not in {entry.arcname.as_posix() for entry in plan.included}


def test_excludes_ds_store(tmp_path: Path) -> None:
    make_minimal_project(tmp_path)
    write_file(tmp_path / ".DS_Store")

    plan = build_release_plan(tmp_path, ReleaseOptions(mode="beta"))

    assert ".DS_Store" in plan.excluded
    assert ".DS_Store" not in {entry.arcname.as_posix() for entry in plan.included}


def test_excludes_avm_egg_info(tmp_path: Path) -> None:
    make_minimal_project(tmp_path)
    write_file(tmp_path / "avm.egg-info/PKG-INFO")

    plan = build_release_plan(tmp_path, ReleaseOptions(mode="beta"))

    assert "avm.egg-info" in plan.excluded
    assert not any(entry.arcname.as_posix().startswith("avm.egg-info/") for entry in plan.included)


def test_demo_mode_rejects_database_without_demo_name(tmp_path: Path) -> None:
    make_minimal_project(tmp_path)
    write_file(tmp_path / "data/tasador.db")

    with pytest.raises(ReleaseZipError, match="must contain 'demo'"):
        build_release_plan(
            tmp_path,
            ReleaseOptions(mode="demo", demo_db_path=Path("data/tasador.db")),
        )


def test_demo_mode_allows_demo_database(tmp_path: Path) -> None:
    make_minimal_project(tmp_path)
    write_file(tmp_path / "data/tasador_demo.db")

    plan = build_release_plan(
        tmp_path,
        ReleaseOptions(mode="demo", demo_db_path=Path("data/tasador_demo.db")),
    )

    included = {entry.arcname.as_posix() for entry in plan.included}
    assert "data/tasador_demo.db" in included
    assert plan.demo_db_included is True
    assert plan.warnings


def test_creates_manifest_inside_zip(tmp_path: Path) -> None:
    make_minimal_project(tmp_path)

    zip_path = create_release(tmp_path, ReleaseOptions(mode="beta"))

    assert zip_path is not None
    with zipfile.ZipFile(zip_path) as archive:
        manifest = json.loads(archive.read("release_manifest.json"))
    assert manifest["project"] == "AVM v2"
    assert manifest["mode"] == "beta"
    assert manifest["included_files_count"] > 0
    assert manifest["zip_size_bytes"] == zip_path.stat().st_size


def test_dry_run_does_not_create_zip(tmp_path: Path) -> None:
    make_minimal_project(tmp_path)

    result = create_release(tmp_path, ReleaseOptions(mode="beta", dry_run=True))

    assert result is None
    assert not (tmp_path / "releases").exists()
