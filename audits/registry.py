"""Central registry for audit checks."""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypedDict

CheckStatus = Literal["OK", "WARNING", "ERROR"]


class CheckResult(TypedDict, total=False):
    name: str
    status: CheckStatus
    message: str
    details: dict[str, Any]


CheckCallable = Callable[[], CheckResult | Awaitable[CheckResult]]
_CHECKS: list[CheckCallable] = []


def register_check(func: CheckCallable) -> CheckCallable:
    """Register an audit check.

    Checks must take no arguments and return a dict with name/status/message.
    Both sync and async functions are supported.
    """
    if func not in _CHECKS:
        _CHECKS.append(func)
    return func


def registered_checks() -> list[CheckCallable]:
    return list(_CHECKS)


async def run_all_checks() -> list[CheckResult]:
    """Run every registered check, isolating failures per check."""
    results: list[CheckResult] = []
    for check in registered_checks():
        try:
            result = check()
            if inspect.isawaitable(result):
                result = await result
            results.append(_normalize_result(result, check.__name__))
        except Exception as e:
            results.append(
                {
                    "name": check.__name__,
                    "status": "ERROR",
                    "message": f"Check failed unexpectedly: {type(e).__name__}",
                    "details": {"error": str(e)},
                }
            )
    return results


def summarize_status(results: list[CheckResult]) -> CheckStatus:
    statuses = {item.get("status") for item in results}
    if "ERROR" in statuses:
        return "ERROR"
    if "WARNING" in statuses:
        return "WARNING"
    return "OK"


def _normalize_result(result: CheckResult, fallback_name: str) -> CheckResult:
    status = str(result.get("status", "ERROR")).upper()
    if status not in {"OK", "WARNING", "ERROR"}:
        status = "ERROR"
    return {
        "name": str(result.get("name") or fallback_name),
        "status": status,  # type: ignore[typeddict-item]
        "message": str(result.get("message") or ""),
        "details": dict(result.get("details") or {}),
    }
