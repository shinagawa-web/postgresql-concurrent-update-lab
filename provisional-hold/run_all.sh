#!/bin/sh
set -e
cd "$(dirname "$0")"

echo "=== sim.py ==="
python3 sim.py --runs 30

docker compose up -d --wait
docker compose exec -T postgres psql -U postgres -d lab -f /dev/stdin < schema.sql

echo "=== run.py ==="
docker compose run --rm runner --runs 3

docker compose down
