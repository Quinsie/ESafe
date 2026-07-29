#!/bin/sh
set -eu

mkdir -p /backups/runtime
touch /backups/runtime/backup-loop.ready

while :; do
  now_epoch=$(date +%s)
  today=$(date +%F)
  target_epoch=$(date -d "$today 03:30:00" +%s)
  if [ "$target_epoch" -le "$now_epoch" ]; then
    target_epoch=$(date -d "tomorrow 03:30:00" +%s)
  fi
  wait_seconds=$((target_epoch - now_epoch))
  sleep "$wait_seconds"

  if /opt/esafe/scripts/backup-now.sh; then
    rm -f /backups/runtime/last-failure
    date -u +%Y-%m-%dT%H:%M:%SZ > /backups/runtime/last-success
  else
    status=$?
    {
      date -u +%Y-%m-%dT%H:%M:%SZ
      printf 'exit_code=%s\n' "$status"
    } > /backups/runtime/last-failure
  fi

  # Avoid a second run inside the same 03:30 minute after clock adjustments.
  sleep 60
done
