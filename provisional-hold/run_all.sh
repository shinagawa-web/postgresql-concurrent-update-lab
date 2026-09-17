#!/bin/sh
set -e
cd "$(dirname "$0")"

docker compose up -d --wait
docker compose exec -T postgres psql -U postgres -d lab -f /dev/stdin < schema.sql

run() {
  echo "=== $* ==="
  docker compose run --rm runner "$@"
}

for abandon_rate in 0.2 0.5 0.7; do
  run --abandon-rate "$abandon_rate" \
      --purchase 2 --p95 6 \
      --customers 300 --window 30 --stock 100 \
      --timers 1,3,5,10 \
      --runs 1
done

docker compose down
