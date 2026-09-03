#!/bin/sh
set -e

docker compose up -d --wait
docker compose exec -T postgres psql -U postgres -d lab -f /dev/stdin < throughput/schema.sql

run() {
  echo "=== $* ==="
  docker compose run --rm throughput-runner "$@"
}

# Round 1: hold time sweep, concurrency fixed at 20
# Theoretical ceiling: TPS = 1/hold
for hold in 0.01 0.1 1.0 5.0; do
  run --pattern for_update --concurrency 20 --hold "$hold" --init-stock 500 --runs 2
done

# Round 2: concurrency sweep at hold=0.1 — ceiling should not move
for conc in 1 5 10 20 50; do
  run --pattern for_update --concurrency "$conc" --hold 0.1 --init-stock 500 --runs 2
done

# Round 3: pattern comparison at concurrency=20
run --pattern for_update  --concurrency 20 --hold 0.1 --init-stock 500 --runs 3
run --pattern conditional --concurrency 20             --init-stock 500 --runs 3

docker compose down
