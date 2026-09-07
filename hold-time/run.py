#!/usr/bin/env python3
"""
Measure throughput ceiling for SELECT ... FOR UPDATE vs alternatives.

Patterns:
  for_update:  SELECT ... FOR UPDATE, sleep(hold), UPDATE
  conditional: UPDATE SET stock = stock - 1 WHERE stock > 0

Each worker loops for the duration of the measurement window (stop_event driven),
so TPS emerges from system behavior rather than being defined by thread count x hold.
"""
import argparse
import os
import threading
import time
import psutil
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


def worker_for_update(latencies, stop_event, hold_sec):
    with psycopg.connect(DSN) as conn:
        while not stop_event.is_set():
            t0 = time.monotonic()
            try:
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
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass


def worker_conditional(latencies, stop_event, hold_sec):
    with psycopg.connect(DSN) as conn:
        while not stop_event.is_set():
            t0 = time.monotonic()
            try:
                with conn.cursor() as cur:
                    cur.execute("BEGIN")
                    cur.execute(
                        "UPDATE items SET stock = stock - 1 WHERE id = 1 AND stock > 0"
                    )
                    if cur.rowcount == 0:
                        conn.commit()
                        return
                    cur.execute(
                        "INSERT INTO orders (item_id, worker) VALUES (1, %s)",
                        (threading.get_ident() % 10 ** 9,),
                    )
                    conn.commit()
                latencies.append(time.monotonic() - t0)
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass


PATTERNS = {
    "for_update": worker_for_update,
    "conditional": worker_conditional,
}


def _observe(stop_event):
    psutil.cpu_percent()
    with psycopg.connect(DSN) as conn:
        conn.autocommit = True
        while not stop_event.wait(0.5):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND state = 'active'"
                )
                n = cur.fetchone()[0]
                cpu = psutil.cpu_percent()
                print(f"  lock_waiters={n} cpu_pct={cpu:.1f}", flush=True)


def run_once(pattern, concurrency, hold_sec, duration_sec, init_stock, observe=False):
    fn = PATTERNS[pattern]
    latencies = []
    lock = threading.Lock()
    stop = threading.Event()

    def wrapper():
        local = []
        fn(local, stop, hold_sec)
        with lock:
            latencies.extend(local)

    init_db(init_stock)

    obs_stop = threading.Event()
    if observe:
        threading.Thread(target=_observe, args=(obs_stop,), daemon=True).start()

    threads = [threading.Thread(target=wrapper) for _ in range(concurrency)]
    t_start = time.monotonic()
    for t in threads:
        t.start()

    time.sleep(duration_sec)
    stop.set()

    for t in threads:
        t.join()

    obs_stop.set()
    elapsed = time.monotonic() - t_start

    if not latencies:
        return {"tps": 0.0, "p99_ms": 0.0, "elapsed_s": elapsed, "count": 0}

    latencies.sort()
    n = len(latencies)
    p99 = latencies[min(int(n * 0.99), n - 1)] * 1000
    tps = n / elapsed
    return {"tps": tps, "p99_ms": p99, "elapsed_s": elapsed, "count": n}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pattern", required=True, choices=["for_update", "conditional"])
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--hold", type=float, default=0.0, help="seconds between read and write")
    p.add_argument("--duration", type=int, default=30, help="measurement window in seconds")
    p.add_argument("--init-stock", type=int, default=500)
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--observe", action="store_true", help="sample lock waiters during run")
    args = p.parse_args()

    print(
        f"pattern={args.pattern} concurrency={args.concurrency} "
        f"hold={args.hold}s duration={args.duration}s init_stock={args.init_stock}"
    )
    print(f"{'run':>4}  {'tps':>8} {'p99_ms':>9} {'count':>6} {'elapsed_s':>10}")
    for r in range(1, args.runs + 1):
        res = run_once(
            args.pattern, args.concurrency, args.hold,
            args.duration, args.init_stock, args.observe,
        )
        print(
            f"{r:>4}  {res['tps']:>8.2f} "
            f"{res['p99_ms']:>9.1f} {res['count']:>6} {res['elapsed_s']:>10.3f}"
        )


if __name__ == "__main__":
    main()
