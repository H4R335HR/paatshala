#!/usr/bin/env bash
# cron_trigger.sh — Hit the dashboard API to run all enabled pipelines.
# Add to crontab, e.g.:  0 22 * * * /path/to/paatshala/cron_trigger.sh
#
# Assumes the dashboard is running on localhost:8099.

set -euo pipefail

DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:8099}"

response=$(curl -s -w "\n%{http_code}" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"trigger_type":"cron"}' \
  "${DASHBOARD_URL}/api/trigger-all")

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" = "200" ]; then
  echo "[$(date)] Pipeline triggered successfully: $body"
else
  echo "[$(date)] Pipeline trigger failed (HTTP $http_code): $body" >&2
  exit 1
fi
