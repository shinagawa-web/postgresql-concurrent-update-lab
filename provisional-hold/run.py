#!/usr/bin/env python3
"""
Finite-cohort simulation: N customers arrive via Poisson process over a window,
competing for finite stock. All T values run in parallel (one product_id per T).

1s here = 1min real (same scaling as previous steady-state script).
"""
import argparse
import math
import os
import random
import threading
import time

import psycopg

DSN = (
    f"host={os.getenv('PGHOST', 'localhost')} "
    f"port={os.getenv('PGPORT', '15433')} "
    f"dbname={os.getenv('PGDATABASE', 'lab')} "
    f"user={os.getenv('PGUSER', 'postgres')} "
    f"password={os.getenv('PGPASSWORD', 'test')}"
)


def _lognormal(p50, p95):
    mu = math.log(p50)
    sigma = (math.log(p95) - mu) / 1.645
    return random.lognormvariate(mu, sigma)


def init_db(stock, n_products):
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE holds, inventory RESTART IDENTITY CASCADE")
            for pid in range(1, n_products + 1):
                cur.execute(
                    "INSERT INTO inventory (product_id, stock) VALUES (%s, %s)",
                    (pid, stock),
                )
        conn.commit()


class _Scenario:
    def __init__(self, product_id, T):
        self.product_id = product_id
        self.T = T
        self.lock = threading.Lock()
        self.confirmed = 0
        self.expired_during_checkout = 0
        self.lost_sale = 0
        self.abandoned_ids = set()


def _sweeper(stop, scenarios):
    product_ids = [sc.product_id for sc in scenarios]
    by_pid = {sc.product_id: sc for sc in scenarios}
    with psycopg.connect(DSN) as conn:
        while not stop.wait(0.5):
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "WITH expired AS ("
                        "  UPDATE holds SET status = 'expired'"
                        "   WHERE product_id = ANY(%s) AND status = 'reserved'"
                        "     AND expires_at <= NOW()"
                        "  RETURNING hold_id, product_id, quantity"
                        "), inv_update AS ("
                        "  UPDATE inventory i"
                        "    SET stock = i.stock + e.total"
                        "    FROM (SELECT product_id, SUM(quantity) AS total"
                        "          FROM expired GROUP BY product_id) e"
                        "    WHERE i.product_id = e.product_id"
                        ")"
                        "SELECT hold_id, product_id FROM expired",
                        (product_ids,),
                    )
                    rows = cur.fetchall()
                conn.commit()
                if rows:
                    for hold_id, pid in rows:
                        sc = by_pid[pid]
                        with sc.lock:
                            sc.abandoned_ids.discard(hold_id)
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass


def _customer(sc, abandon_rate, purchase_sec, p95_sec):
    try:
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "WITH dec AS ("
                    "  UPDATE inventory SET stock = stock - 1"
                    "   WHERE product_id = %s AND stock >= 1"
                    "  RETURNING product_id"
                    ")"
                    "INSERT INTO holds (product_id, user_id, quantity, expires_at)"
                    " SELECT product_id, %s, 1,"
                    "  NOW() + make_interval(secs => %s) FROM dec"
                    " RETURNING hold_id",
                    (sc.product_id, threading.get_ident() % 10**9, sc.T),
                )
                row = cur.fetchone()
            conn.commit()
    except Exception:
        return

    if row is None:
        with sc.lock:
            if sc.abandoned_ids:
                sc.lost_sale += 1
        return

    hold_id = row[0]

    if random.random() < abandon_rate:
        with sc.lock:
            sc.abandoned_ids.add(hold_id)
        return

    time.sleep(_lognormal(purchase_sec, p95_sec))

    try:
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE holds SET status = 'paying', paying_at = NOW()"
                    " WHERE hold_id = %s AND status = 'reserved' AND expires_at > NOW()",
                    (hold_id,),
                )
                expired = cur.rowcount == 0
            conn.commit()
    except Exception:
        return

    if expired:
        with sc.lock:
            sc.expired_during_checkout += 1
        return

    try:
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE holds SET status = 'confirmed'"
                    " WHERE hold_id = %s AND status = 'paying'",
                    (hold_id,),
                )
            conn.commit()
        with sc.lock:
            sc.confirmed += 1
    except Exception:
        pass


def _arrival_generator(sc, abandon_rate, purchase_sec, p95_sec, n_customers, arrival_rate):
    threads = []
    for _ in range(n_customers):
        time.sleep(random.expovariate(arrival_rate))
        t = threading.Thread(
            target=_customer,
            args=(sc, abandon_rate, purchase_sec, p95_sec),
            daemon=True,
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


def run_round(T_values, abandon_rate, purchase_sec, p95_sec, n_customers, arrival_rate, stock):
    scenarios = [_Scenario(i + 1, T) for i, T in enumerate(T_values)]
    init_db(stock, len(scenarios))

    stop = threading.Event()
    threading.Thread(target=_sweeper, args=(stop, scenarios), daemon=True).start()

    gen_threads = [
        threading.Thread(
            target=_arrival_generator,
            args=(sc, abandon_rate, purchase_sec, p95_sec, n_customers, arrival_rate),
        )
        for sc in scenarios
    ]
    for t in gen_threads:
        t.start()
    for t in gen_threads:
        t.join()

    stop.set()

    return {
        sc.T: {
            "confirmed": sc.confirmed,
            "expired_during_checkout": sc.expired_during_checkout,
            "lost_sale": sc.lost_sale,
        }
        for sc in scenarios
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--abandon-rate", type=float, default=0.5)
    p.add_argument("--purchase", type=float, default=2.0, help="p50 checkout seconds (1s = 1min)")
    p.add_argument("--p95", type=float, default=None, help="p95 checkout seconds (default: 3x --purchase)")
    p.add_argument("--customers", type=int, default=300)
    p.add_argument("--window", type=float, default=30.0, help="arrival window seconds")
    p.add_argument("--stock", type=int, default=100)
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--timers", type=str, default="1,2,3,5,7,10,15,20")
    args = p.parse_args()

    P95 = args.p95 if args.p95 is not None else args.purchase * 3
    arrival_rate = args.customers / args.window
    T_values = [float(t) for t in args.timers.split(",")]
    R = args.abandon_rate

    print(
        f"customers={args.customers} window={args.window}s stock={args.stock}"
        f" abandon_rate={R} p50={args.purchase}s p95={P95}s runs={args.runs}"
    )
    print(f"{'T(s)':>6}  {'confirmed':>10} {'exp_during_co':>14} {'lost_sale':>10}")

    totals = {T: {"confirmed": 0, "expired_during_checkout": 0, "lost_sale": 0} for T in T_values}
    for _ in range(args.runs):
        res = run_round(T_values, R, args.purchase, P95, args.customers, arrival_rate, args.stock)
        for T in T_values:
            for k in totals[T]:
                totals[T][k] += res[T][k]

    for T in T_values:
        n = args.runs
        print(
            f"{T:>6.0f}  {totals[T]['confirmed']/n:>10.1f}"
            f" {totals[T]['expired_during_checkout']/n:>14.1f}"
            f" {totals[T]['lost_sale']/n:>10.1f}"
        )


if __name__ == "__main__":
    main()
