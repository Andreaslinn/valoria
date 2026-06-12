#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${AVM_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/scraper_cron.log"
LOCK_FILE="$LOG_DIR/scraper_cron.lock"

mkdir -p "$LOG_DIR"
touch "$LOG_FILE"

exec >>"$LOG_FILE" 2>&1

echo "[$(date -Is)] AVM scraper cron starting"

cd "$PROJECT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "[$(date -Is)] ERROR: docker is not installed or not in PATH"
  exit 127
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "[$(date -Is)] ERROR: docker compose plugin is not available"
  exit 127
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -Is)] Another scraper run is still active; skipping"
  exit 0
fi

docker compose up -d postgres redis
docker compose run --rm --no-deps api python -m workers.scraper_job

echo "[$(date -Is)] AVM scraper cron finished"
