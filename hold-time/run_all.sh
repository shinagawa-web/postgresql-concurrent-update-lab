#!/bin/sh
set -e

docker compose up -d --wait
docker compose exec -T postgres psql -U postgres -d lab -f /dev/stdin < hold-time/schema.sql

run() {
  echo "=== $* ==="
  docker compose run --rm throughput-runner "$@"
}

# Round 1: hold time sweep, concurrency fixed at 20, 30s steady-state window
# Theoretical ceiling: TPS = 1/hold. Emerges from system behavior, not thread × hold math.
for hold in 0.1 1.0 5.0; do
  run --pattern for_update --concurrency 20 --hold "$hold" --duration 30 --init-stock 1000 --runs 2
done

# Round 2: concurrency sweep at hold=0.1 — ceiling should not move as concurrency grows
for conc in 1 5 10 20 50; do
  run --pattern for_update --concurrency "$conc" --hold 0.1 --duration 30 --init-stock 1000 --runs 2 --observe
done

# Round 3: pattern comparison at concurrency=20, 30s window
# conditional needs large stock: 200+ TPS × 30s = 6000+ commits
run --pattern for_update  --concurrency 20 --hold 0.1 --duration 30 --init-stock 1000  --runs 2
run --pattern conditional --concurrency 20             --duration 30 --init-stock 50000 --runs 2

docker compose down
