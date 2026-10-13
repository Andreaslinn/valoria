"""Selective persistent queue worker; independent of ingestion and scheduler."""
import logging
import signal
import threading
import time

from services.thumbnails import get_store
from infrastructure.thumbnails.pipeline import work_one


def main():
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    store = get_store()
    cleanup_at = 0
    try:
        while not stop.is_set():
            try:
                if time.monotonic() >= cleanup_at:
                    store.gc()
                    cleanup_at = time.monotonic() + 3600
                if not work_one(store):
                    stop.wait(1)
            except Exception:
                logging.exception('thumbnail_worker_degraded')
                stop.wait(5)
    finally:
        store.close()


if __name__ == '__main__':
    main()
