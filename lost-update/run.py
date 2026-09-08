#!/usr/bin/env python3
import argparse
import os
import threading
import psycopg
from psycopg import sql

DSN = (
    f"host={os.getenv('PGHOST', 'localhost')} "
    f"port={os.getenv('PGPORT', '15432')} "
    f"dbname={os.getenv('PGDATABASE', 'lab')} "
    f"user={os.getenv('PGUSER', 'postgres')} "
    f"password={os.getenv('PGPASSWORD', 'test')}"
)

def init_db(conn, keys, init_stock):
    with conn.cursor() as cur:
        cur.execute("TRUNCATE items, orders RESTART IDENTITY")
        cur.execute(
            "INSERT INTO items (id, stock) SELECT g, %s FROM generate_series(1, %s) g",
            (init_stock, keys),
        )
    conn.commit()

def measure(conn, keys, init_stock):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              sum(stock)                                            AS stock_sum,
              %s * %s - sum(stock)                                 AS decremented,
              (SELECT count(*) FROM orders)                        AS orders_ok,
              (SELECT count(*) FROM orders)
                - (%s * %s - sum(stock))                          AS lost_decrements,
              count(*) FILTER (WHERE stock < 0)                   AS negative_rows,
              min(stock)                                           AS min_stock
            FROM items
            """,
            (keys, init_stock, keys, init_stock),
        )
        row = cur.fetchone()
    return dict(zip(
        ["stock_sum", "decremented", "orders_ok", "lost_decrements", "negative_rows", "min_stock"],
        row,
    ))

def worker_a(item_id, worker_id, wait_sec, retries_box):
    with psycopg.connect(DSN) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
            cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
            stock = cur.fetchone()[0]
            if stock <= 0:
                conn.commit()
                return
            if wait_sec:
                cur.execute("SELECT pg_sleep(%s)", (wait_sec,))
            cur.execute("UPDATE items SET stock = stock - 1 WHERE id = %s", (item_id,))
            cur.execute("INSERT INTO orders (item_id, worker) VALUES (%s, %s)", (item_id, worker_id))
            conn.commit()

def worker_b(item_id, worker_id, wait_sec, retries_box):
    with psycopg.connect(DSN) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
            cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
            v = cur.fetchone()[0]
            if v <= 0:
                conn.commit()
                return
            if wait_sec:
                cur.execute("SELECT pg_sleep(%s)", (wait_sec,))
            cur.execute("UPDATE items SET stock = %s WHERE id = %s", (v - 1, item_id))
            cur.execute("INSERT INTO orders (item_id, worker) VALUES (%s, %s)", (item_id, worker_id))
            conn.commit()

def worker_c(item_id, worker_id, wait_sec, retries_box):
    with psycopg.connect(DSN) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
            cur.execute(
                "UPDATE items SET stock = stock - 1 WHERE id = %s AND stock > 0",
                (item_id,),
            )
            if cur.rowcount == 0:
                conn.commit()
                return
            cur.execute("INSERT INTO orders (item_id, worker) VALUES (%s, %s)", (item_id, worker_id))
            conn.commit()

def worker_d(item_id, worker_id, wait_sec, retries_box):
    retries = 0
    while True:
        with psycopg.connect(DSN) as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                cur.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
                cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
                v = cur.fetchone()[0]
                if v <= 0:
                    conn.commit()
                    return
                if wait_sec:
                    cur.execute("SELECT pg_sleep(%s)", (wait_sec,))
                cur.execute(
                    "UPDATE items SET stock = %s WHERE id = %s AND stock = %s",
                    (v - 1, item_id, v),
                )
                if cur.rowcount == 0:
                    conn.rollback()
                    retries += 1
                    continue
                cur.execute("INSERT INTO orders (item_id, worker) VALUES (%s, %s)", (item_id, worker_id))
                conn.commit()
                retries_box[worker_id] = retries
                return

def worker_cb(item_id, worker_id, wait_sec, retries_box):
    with psycopg.connect(DSN) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
            cur.execute("SELECT stock FROM items WHERE id = %s", (item_id,))
            v = cur.fetchone()[0]
            if v <= 0:
                conn.commit()
                return
            if wait_sec:
                cur.execute("SELECT pg_sleep(%s)", (wait_sec,))
            cur.execute(
                "UPDATE items SET stock = %s WHERE id = %s AND stock > 0",
                (v - 1, item_id),
            )
            if cur.rowcount == 0:
                conn.commit()
                return
            cur.execute("INSERT INTO orders (item_id, worker) VALUES (%s, %s)", (item_id, worker_id))
            conn.commit()

PATTERNS = {"A": worker_a, "B": worker_b, "C": worker_c, "D": worker_d, "CB": worker_cb}

def run_once(pattern, concurrency, keys, init_stock, wait_sec):
    fn = PATTERNS[pattern]
    retries_box = {}
    with psycopg.connect(DSN) as conn:
        init_db(conn, keys, init_stock)

    threads = []
    for i in range(concurrency):
        item_id = (i % keys) + 1
        t = threading.Thread(target=fn, args=(item_id, i, wait_sec, retries_box))
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with psycopg.connect(DSN) as conn:
        result = measure(conn, keys, init_stock)
    result["retries"] = sum(retries_box.values())
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pattern", required=True, choices=["A", "B", "C", "D", "CB"])
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--keys", type=int, default=1)
    parser.add_argument("--init-stock", type=int, default=20)
    parser.add_argument("--wait", type=float, default=0.0, help="sleep sec between read and write")
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    print(f"pattern={args.pattern} concurrency={args.concurrency} keys={args.keys} init_stock={args.init_stock} wait={args.wait}s")
    print(f"{'run':>4}  {'stock_sum':>10} {'decremented':>12} {'orders_ok':>10} {'lost_decrements':>16} {'negative_rows':>14} {'min_stock':>10} {'retries':>8}")
    for r in range(1, args.runs + 1):
        res = run_once(args.pattern, args.concurrency, args.keys, args.init_stock, args.wait)
        print(f"{r:>4}  {res['stock_sum']:>10} {res['decremented']:>12} {res['orders_ok']:>10} {res['lost_decrements']:>16} {res['negative_rows']:>14} {res['min_stock']:>10} {res['retries']:>8}")

if __name__ == "__main__":
    main()
