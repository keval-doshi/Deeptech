#!/bin/sh
# Runs the maintenance jobs: bids every 5 minutes, payment reconciliation every 10.
# A failed run is logged and retried on the next pass.
n=0
while true; do
  flask --app wsgi bids maintain
  if [ $((n % 2)) -eq 0 ]; then
    flask --app wsgi payments reconcile
  fi
  n=$((n + 1))
  sleep 300
done
