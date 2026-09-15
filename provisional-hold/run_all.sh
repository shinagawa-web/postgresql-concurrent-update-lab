#!/bin/sh
set -e
cd "$(dirname "$0")"

docker compose up -d --wait
docker compose exec -T postgres psql -U postgres -d lab -f /dev/stdin < schema.sql

run() {
  echo "=== $* ==="
  docker compose run --rm runner "$@"
}

# Grid: timer x abandon_rate, purchase=2s fixed, concurrency=20, duration=40s
# 1s = 1min scaled (T/P ratio preserved)
for timer in 1 5 10; do
  for abandon in 0.2 0.5 0.7; do
    run --abandon-rate "$abandon" --timer "$timer" --purchase 2 \
        --concurrency 20 --duration 40 --init-stock 100000 --runs 2
  done
done

docker compose down
