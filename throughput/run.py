#!/usr/bin/env python3
"""
Measure throughput ceiling for SELECT ... FOR UPDATE vs alternatives.

Patterns:
  sfu: SELECT ... FOR UPDATE, sleep(hold), UPDATE
  ol:  SELECT (no lock), sleep(hold), UPDATE WHERE stock = old (optimistic, retry on conflict)
  du:  UPDATE SET stock = stock - 1 WHERE stock > 0 (no hold)
"""
import argparse
import os
import threading
import time
import psycopg

DSN = (
    f"host={os.getenv('PGHOST', 'localhost')} "
    f"port={os.getenv('PGPORT', '15432')} "
    f"dbname={os.getenv('PGDATABASE', 'lab')} "
    f"user={os.getenv('PGUSER', 'postgres')} "
    f"password={os.getenv('PGPASSWORD', 'test')}"
)


def init_db(init_stock):
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE items, orders RESTART IDENTITY")
            cur.execute("INSERT INTO items (id, stock) VALUES (1, %s)", (init_stock,))
        conn.commit()


def worker_sfu(latencies, hold_sec):
    t0 = time.monotonic()
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SELECT stock FROM items WHERE id = 1 FOR UPDATE")
            stock = cur.fetchone()[0]
            if stock <= 0:
                conn.commit()
                return
            if hold_sec > 0:
                cur.execute("SELECT pg_sleep(%s)", (hold_sec,))
            cur.execute("UPDATE items SET stock = stock - 1 WHERE id = 1")
            cur.execute(
                "INSERT INTO orders (item_id, worker) VALUES (1, %s)",
                (threading.get_ident() % 10 ** 9,),
            )
            conn.commit()
    latencies.append(time.monotonic() - t0)


def worker_ol(latencies, hold_sec):
    while True:
        t0 = time.monotonic()
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute("BEGIN")
                cur.execute("SELECT stock FROM items WHERE id = 1")
                stock = cur.fetchone()[0]
                if stock <= 0:
                    conn.commit()
                    latencies.append(time.monotonic() - t0)
                    return
                if hold_sec > 0:
                    cur.execute("SELECT pg_sleep(%s)", (hold_sec,))
                cur.execute(
                    "UPDATE items SET stock = %s WHERE id = 1 AND stock = %s",
                    (stock - 1, stock),
                )
                if cur.rowcount == 0:
                    conn.rollback()
                    continue
                cur.execute(
                    "INSERT INTO orders (item_id, worker) VALUES (1, %s)",
                    (threading.get_ident() % 10 ** 9,),
                )
                conn.commit()
        latencies.append(time.monotonic() - t0)
        return


def worker_du(latencies, hold_sec):
    t0 = time.monotonic()
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("UPDATE items SET stock = stock - 1 WHERE id = 1 AND stock > 0")
            if cur.rowcount == 0:
                conn.commit()
                latencies.append(time.monotonic() - t0)
                return
            cur.execute(
                "INSERT INTO orders (item_id, worker) VALUES (1, %s)",
                (threading.get_ident() % 10 ** 9,),
            )
            conn.commit()
    latencies.append(time.monotonic() - t0)


PATTERNS = {"sfu": worker_sfu, "ol": worker_ol, "du": worker_du}


def run_once(pattern, concurrency, hold_sec, init_stock):
    fn = PATTERNS[pattern]
    latencies = []
    lock = threading.Lock()

    def wrapper():
        local = []
        fn(local, hold_sec)
        with lock:
            latencies.extend(local)

    init_db(init_stock)
    threads = [threading.Thread(target=wrapper) for _ in range(concurrency)]
    t_start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t_start

    if not latencies:
        return {"tps": 0.0, "p50_ms": 0.0, "p99_ms": 0.0, "elapsed_s": elapsed, "count": 0}

    latencies.sort()
    n = len(latencies)
    p50 = latencies[n // 2] * 1000
    p99 = latencies[min(int(n * 0.99), n - 1)] * 1000
    tps = n / elapsed
    return {"tps": tps, "p50_ms": p50, "p99_ms": p99, "elapsed_s": elapsed, "count": n}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pattern", required=True, choices=["sfu", "ol", "du"])
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--hold", type=float, default=0.0, help="seconds between read and write")
    p.add_argument("--init-stock", type=int, default=500)
    p.add_argument("--runs", type=int, default=1)
    args = p.parse_args()

    print(
        f"pattern={args.pattern} concurrency={args.concurrency} "
        f"hold={args.hold}s init_stock={args.init_stock}"
    )
    print(f"{'run':>4}  {'tps':>8} {'p50_ms':>8} {'p99_ms':>9} {'count':>6} {'elapsed_s':>10}")
    for r in range(1, args.runs + 1):
        res = run_once(args.pattern, args.concurrency, args.hold, args.init_stock)
        print(
            f"{r:>4}  {res['tps']:>8.2f} {res['p50_ms']:>8.1f} "
            f"{res['p99_ms']:>9.1f} {res['count']:>6} {res['elapsed_s']:>10.3f}"
        )


if __name__ == "__main__":
    main()
