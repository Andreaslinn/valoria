from __future__ import annotations

import subprocess
import sys


def test_cli_rejects_unknown_engine() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_valuation_engines.py",
            "--engines",
            "missing",
            "--output-dir",
            "reports/valuation_engine_benchmark/test_invalid",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "not registered" in result.stderr
