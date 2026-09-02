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
for hold in 0.001 0.01 0.1 0.5; do
  run --pattern sfu --concurrency 20 --hold "$hold" --init-stock 500 --runs 2
done

# Round 2: concurrency sweep at hold=0.1 — ceiling should not move
for conc in 1 5 10 20 50; do
  run --pattern sfu --concurrency "$conc" --hold 0.1 --init-stock 500 --runs 2
done

# Round 3: pattern comparison at hold=0.1, concurrency=20
run --pattern sfu --concurrency 20 --hold 0.1 --init-stock 500 --runs 3
run --pattern ol  --concurrency 20 --hold 0.1 --init-stock 500 --runs 3
run --pattern du  --concurrency 20 --hold 0   --init-stock 500 --runs 3

docker compose down
