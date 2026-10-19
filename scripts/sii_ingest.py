"""python -m scripts.sii_ingest <job>; disabled by default, local Postgres only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.sii.settings import enabled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "job",
        choices=["sii_f2890_fetch", "sii_catastro_import", "sii_rebuild", "health", "schedule"],
    )
    parser.add_argument(
        "--f2890-zip", type=Path, help="Replay an existing public ZIP without network"
    )
    args = parser.parse_args()
    if not enabled():
        print(json.dumps({"enabled": False, "status": "disabled"}))
        return
    from services.sii.jobs import catastro_import, f2890_fetch, rebuild
    from services.sii.reporting import health

    jobs = {
        "sii_f2890_fetch": lambda: f2890_fetch(args.f2890_zip),
        "sii_catastro_import": catastro_import,
        "sii_rebuild": rebuild,
        "health": health,
    }
    if args.job == "schedule":
        from apscheduler.schedulers.blocking import BlockingScheduler

        from services.sii.settings import Settings

        Settings.load()  # reject nonlocal configuration before starting a scheduler
        scheduler = BlockingScheduler(timezone="America/Santiago")
        scheduler.add_job(
            f2890_fetch,
            "cron",
            day_of_week="sun",
            hour=3,
            minute=0,
            id="sii_f2890_fetch",
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
    else:
        try:
            print(json.dumps(jobs[args.job](), default=str, ensure_ascii=True))
        except Exception as exc:
            # Avoid printing DSNs from driver exceptions.
            result = {"status": "failed", "error": type(exc).__name__}
            if isinstance(exc, ValueError):
                result["detail"] = str(exc)  # strict layout/row diagnostics, no driver DSN
            print(json.dumps(result))
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
