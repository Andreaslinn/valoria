"""Shared user-facing warning semantics used by V2 and downloadable reports."""
import json
from pathlib import Path

DEFINITIONS = json.loads(Path(__file__).with_name("warning_definitions.json").read_text(encoding="utf-8"))


def warning_detail(code: str) -> dict:
    return {"code": code, **DEFINITIONS.get(code, {
        "label": "Señal adicional no clasificada", "severity": "warning", "category": "datos",
        "description": "Valoria encontró una señal adicional. Revisa su implicación antes de utilizar la estimación.",
    })}
