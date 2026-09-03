#!/bin/sh
set -e

docker compose up -d
docker compose exec -T postgres sh -c 'until pg_isready -U postgres; do sleep 1; done'
docker compose exec -T postgres psql -U postgres -d lab -f /dev/stdin < schema.sql

run() {
  echo "=== $* ==="
  docker compose run --rm runner "$@"
}

run --pattern A --concurrency 1  --keys 1    --init-stock 20 --runs 3
run --pattern B --concurrency 1  --keys 1    --init-stock 20 --runs 3
run --pattern A --concurrency 50 --keys 1    --init-stock 20 --wait 0.1 --runs 5
run --pattern B --concurrency 50 --keys 1    --init-stock 20 --wait 0.1 --runs 5
run --pattern C --concurrency 50 --keys 1    --init-stock 20 --wait 0.1 --runs 5
run --pattern CB --concurrency 50 --keys 1   --init-stock 20 --wait 0.1 --runs 5
run --pattern D --concurrency 50 --keys 1    --init-stock 20 --wait 0.1 --runs 5
run --pattern A --concurrency 50 --keys 1000 --init-stock 5  --wait 0.1 --runs 5
run --pattern B --concurrency 50 --keys 1000 --init-stock 5  --wait 0.1 --runs 5

docker compose down
