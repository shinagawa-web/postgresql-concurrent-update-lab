# provisional-hold

Simulations for measuring how hold timer length affects confirmed sales, checkout expirations, and lost sales under finite stock.

Two scripts share the same parameters and produce the same output format. `sim.py` runs without a database; `run.py` runs against PostgreSQL.

## sim.py — in-memory simulation

No database required. Runs fast; useful for sweeping parameter space.

```
python sim.py [options]
```

| Option | Default | Description |
|---|---|---|
| `--stock` | 100 | Initial inventory |
| `--customers` | 300 | Number of arrivals |
| `--window` | 30.0 | Arrival window in minutes |
| `--purchase` | 2.0 | p50 checkout duration (minutes) |
| `--p95` | 3× purchase | p95 checkout duration (minutes) |
| `--abandon-rate` | 0.7 | Fraction of customers who abandon |
| `--timers` | `1,2,3,5,7,10,15,20` | Hold timer values to sweep (minutes) |
| `--sweep` | 10s | Expiry sweep interval (minutes) |
| `--remove-rate` | 0.0 | Fraction of abandoners who actively remove their hold |
| `--runs` | 30 | Seeds to average over |

Example:

```
python sim.py --customers 500 --stock 150
```

## run.py — PostgreSQL simulation

Runs the same scenario against a real database. Each timer value gets its own `product_id`; all run in parallel.

Start the database first:

```
docker compose up -d
```

Then:

```
python run.py [options]
```

| Option | Default | Description |
|---|---|---|
| `--stock` | 100 | Initial inventory per product |
| `--customers` | 300 | Number of arrivals |
| `--window` | 30.0 | Arrival window in seconds (1 s here = 1 min real) |
| `--purchase` | 2.0 | p50 checkout duration (seconds) |
| `--p95` | 3× purchase | p95 checkout duration (seconds) |
| `--abandon-rate` | 0.7 | Fraction of customers who abandon |
| `--timers` | `1,2,3,5,7,10,15,20` | Hold timer values to sweep (seconds) |
| `--runs` | 30 | Rounds to average over |

Database connection is read from environment variables: `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`. Defaults point to the `docker-compose.yml` instance.

Example:

```
python run.py --customers 500 --stock 150
```

## Output

Both scripts print a table with one row per timer value:

```
T(min)   confirmed  exp_during_co  lost_sale dead_ratio
     1      ...            ...        ...        ...
     2      ...            ...        ...        ...
```

- `confirmed` — customers who completed checkout before their hold expired
- `exp_during_co` — customers whose hold expired while they were checking out
- `lost_sale` — buyers who found no stock but an abandoned hold existed
- `dead_ratio` — mean fraction of reserved holds that belong to abandoners, sampled during the arrival window
