#!/bin/sh
set -e
cd "$(dirname "$0")"

docker compose up -d --wait
docker compose exec -T postgres psql -U postgres -d lab -f /dev/stdin < schema.sql

run() {
  echo "=== $* ==="
  docker compose run --rm runner "$@"
}

# Reduced grid for CI speed during development.
# Full 9-case grid (timer 1/5/10 x abandon 0.2/0.5/0.7, duration=40, runs=2)
# will be restored before final merge — see PR TODO.
for args in \
  "--abandon-rate 0.2 --timer 1" \
  "--abandon-rate 0.5 --timer 5" \
  "--abandon-rate 0.7 --timer 10"; do
  run $args --purchase 2 --concurrency 20 --duration 15 --init-stock 100000 --runs 1
done

docker compose down
