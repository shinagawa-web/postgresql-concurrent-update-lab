# postgresql-concurrent-update-lab

Experiments measuring lock contention and throughput characteristics of `SELECT ... FOR UPDATE` in PostgreSQL.

## Articles and CI runs

| Article | CI run |
|:---|:---|
| [PostgreSQL SELECT FOR UPDATE: Throughput Limit Is the Inverse of Lock Hold Time](https://zenn.dev/shinagawa_web/articles/select-for-update-throughput-ceiling?locale=en) | [34204971520](https://github.com/shinagawa-web/postgresql-concurrent-update-lab/actions/runs/34204971520) |
| [Two Causes of Inventory Discrepancies in PostgreSQL: Differentiating by Symptoms](https://zenn.dev/shinagawa_web/articles/read-committed-lost-update-patterns?locale=en) | [33240985617](https://github.com/shinagawa-web/postgresql-concurrent-update-lab/actions/runs/33240985617) |
