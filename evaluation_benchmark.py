"""Thin CLI wrapper for scripts.evaluation_benchmark."""
from __future__ import annotations

import asyncio

from scripts.evaluation_benchmark import main


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
