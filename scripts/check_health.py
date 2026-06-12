"""Run all AVM audit checks from the command line."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import audits.checks  # noqa: E402,F401
from audits.registry import CheckResult, run_all_checks, summarize_status  # noqa: E402


def main() -> int:
    results = asyncio.run(run_all_checks())
    _print_results(results)
    return 1 if summarize_status(results) == "ERROR" else 0


def _print_results(results: list[CheckResult]) -> None:
    overall = summarize_status(results)
    print(f"AVM Audit Summary: {overall}")
    print("=" * 72)
    for item in results:
        print(f"[{item['status']}] {item['name']}")
        print(f"  {item['message']}")
        details = item.get("details") or {}
        for key, value in details.items():
            print(f"  - {key}: {value}")
        print("-" * 72)


if __name__ == "__main__":
    raise SystemExit(main())
