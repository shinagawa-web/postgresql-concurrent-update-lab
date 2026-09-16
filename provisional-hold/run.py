#!/usr/bin/env python3
"""
Measure dead-inventory ratio under provisional-hold design.

Two formulas under test:
  exact  = R*T / ((1-R)*P + R*T)   Little's Law
  approx = R*T / P                  issue #347 approximation

Time is scaled: 1s here = 1min real (ratio identical, runs in seconds not hours).
"""
import argparse
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

_lock = threading.Lock()
_confirmed = 0
_rejected = 0
_abandoned = 0
_immediate_released = 0
_payment_failed = 0
_expired_during_checkout = 0
_released = 0
_abandoned_ids: set = set()
_dead_samples: list = []
_total_samples: list = []


def _reset():
    global _confirmed, _rejected, _abandoned, _immediate_released, _payment_failed
    global _expired_during_checkout, _released
    global _abandoned_ids, _dead_samples, _total_samples
    _confirmed = _rejected = _abandoned = _immediate_released = _payment_failed = 0
    _expired_during_checkout = _released = 0
    _abandoned_ids = set()
    _dead_samples = []
    _total_samples = []


def init_db(stock):
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE holds, inventory RESTART IDENTITY CASCADE")
            cur.execute(
                "INSERT INTO inventory (product_id, stock) VALUES (1, %s)", (stock,)
            )
        conn.commit()


def _release_hold(conn, hold_id, status_filter):
    with conn.cursor() as cur:
        cur.execute(
            "WITH cancelled AS ("
            "  UPDATE holds SET status = 'expired'"
            "   WHERE hold_id = %s AND status = %s"
            "  RETURNING product_id, quantity"
            ")"
            "UPDATE inventory i SET stock = i.stock + e.quantity"
            "  FROM cancelled e WHERE i.product_id = e.product_id",
            (hold_id, status_filter),
        )
        conn.commit()


def _worker(stop, abandon_rate, immediate_release_rate, payment_fail_rate, timer_sec, purchase_sec):
    global _confirmed, _rejected, _abandoned, _immediate_released
    global _payment_failed, _expired_during_checkout
    with psycopg.connect(DSN) as conn:
        while not stop.is_set():
            hold_id = None
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "WITH dec AS ("
                        "  UPDATE inventory SET stock = stock - 1"
                        "   WHERE product_id = 1 AND stock >= 1"
                        "  RETURNING product_id"
                        ")"
                        "INSERT INTO holds (product_id, user_id, quantity, expires_at)"
                        " SELECT product_id, %s, 1,"
                        "  NOW() + make_interval(secs => %s) FROM dec"
                        " RETURNING hold_id",
                        (threading.get_ident() % 10**9, timer_sec),
                    )
                    row = cur.fetchone()
                    conn.commit()
                if row is None:
                    with _lock:
                        _rejected += 1
                    time.sleep(0.05)
                    continue
                hold_id = row[0]
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue

            if random.random() < abandon_rate:
                if random.random() < immediate_release_rate:
                    try:
                        _release_hold(conn, hold_id, 'reserved')
                        with _lock:
                            _immediate_released += 1
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        with _lock:
                            _abandoned += 1
                            _abandoned_ids.add(hold_id)
                else:
                    with _lock:
                        _abandoned += 1
                        _abandoned_ids.add(hold_id)
                continue

            time.sleep(purchase_sec * (0.5 + random.random()))

            if stop.is_set():
                break

            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE holds SET status = 'paying'"
                        " WHERE hold_id = %s"
                        "   AND status = 'reserved'"
                        "   AND expires_at > NOW()",
                        (hold_id,),
                    )
                    if cur.rowcount == 0:
                        conn.commit()
                        with _lock:
                            _expired_during_checkout += 1
                        continue
                    conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue

            if random.random() < payment_fail_rate:
                try:
                    _release_hold(conn, hold_id, 'paying')
                    with _lock:
                        _payment_failed += 1
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
            else:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE holds SET status = 'confirmed'"
                            " WHERE hold_id = %s AND status = 'paying'",
                            (hold_id,),
                        )
                        conn.commit()
                    with _lock:
                        _confirmed += 1
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass


def _sweeper(stop):
    global _released
    with psycopg.connect(DSN) as conn:
        while not stop.wait(0.5):
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "WITH expired AS ("
                        "  UPDATE holds SET status = 'expired'"
                        "   WHERE status = 'reserved' AND expires_at <= NOW()"
                        "  RETURNING hold_id, product_id, quantity"
                        "),"
                        "inv_update AS ("
                        "  UPDATE inventory i SET stock = i.stock + e.total"
                        "    FROM (SELECT product_id, SUM(quantity) AS total"
                        "          FROM expired GROUP BY product_id) e"
                        "    WHERE i.product_id = e.product_id"
                        ")"
                        "SELECT hold_id FROM expired"
                    )
                    rows = cur.fetchall()
                    conn.commit()
                if rows:
                    hold_ids = [r[0] for r in rows]
                    with _lock:
                        _released += len(hold_ids)
                        _abandoned_ids.difference_update(hold_ids)
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass


def _observer(stop):
    with psycopg.connect(DSN) as conn:
        conn.autocommit = True
        while not stop.wait(0.5):
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM holds WHERE status = 'reserved'"
                    )
                    total = cur.fetchone()[0]
                with _lock:
                    dead = len(_abandoned_ids)
                _dead_samples.append(dead)
                _total_samples.append(total)
                print(f"  reserved={total} dead={dead}", flush=True)
            except Exception:
                pass


def run_once(abandon_rate, immediate_release_rate, payment_fail_rate,
             timer_sec, purchase_sec, concurrency, duration_sec, init_stock):
    _reset()
    init_db(init_stock)

    stop = threading.Event()
    threads = [
        threading.Thread(
            target=_worker,
            args=(stop, abandon_rate, immediate_release_rate, payment_fail_rate,
                  timer_sec, purchase_sec),
        )
        for _ in range(concurrency)
    ]
    threading.Thread(target=_sweeper, args=(stop,), daemon=True).start()
    threading.Thread(target=_observer, args=(stop,), daemon=True).start()

    t0 = time.monotonic()
    for t in threads:
        t.start()
    time.sleep(duration_sec)
    stop.set()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0

    mean_dead = sum(_dead_samples) / len(_dead_samples) if _dead_samples else 0.0
    mean_total = sum(_total_samples) / len(_total_samples) if _total_samples else 0.0
    measured = mean_dead / mean_total if mean_total > 0 else 0.0
    eff_R = abandon_rate * (1 - immediate_release_rate)
    pred_exact = (eff_R * timer_sec) / (
        (1 - eff_R) * purchase_sec + eff_R * timer_sec
    )
    pred_approx = eff_R * timer_sec / purchase_sec

    return {
        "confirmed": _confirmed,
        "rejected": _rejected,
        "abandoned": _abandoned,
        "immediate_released": _immediate_released,
        "payment_failed": _payment_failed,
        "expired_during_checkout": _expired_during_checkout,
        "released": _released,
        "mean_dead": mean_dead,
        "mean_total": mean_total,
        "measured": measured,
        "pred_exact": pred_exact,
        "pred_approx": pred_approx,
        "elapsed_s": elapsed,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--abandon-rate", type=float, required=True)
    p.add_argument("--immediate-release-rate", type=float, default=0.0,
                   help="fraction of abandons that explicitly delete from cart (default: 0)")
    p.add_argument("--payment-fail-rate", type=float, default=0.0,
                   help="fraction of payments that fail (default: 0)")
    p.add_argument("--timer", type=float, required=True, help="hold expiry seconds (1s = 1min scaled)")
    p.add_argument("--purchase", type=float, default=2.0, help="mean checkout seconds")
    p.add_argument("--concurrency", type=int, default=20)
    p.add_argument("--duration", type=int, default=30)
    p.add_argument("--init-stock", type=int, default=100000)
    p.add_argument("--runs", type=int, default=1)
    args = p.parse_args()

    R, I, F, T, P = (
        args.abandon_rate, args.immediate_release_rate, args.payment_fail_rate,
        args.timer, args.purchase,
    )
    eff_R = R * (1 - I)
    pred_exact = eff_R * T / ((1 - eff_R) * P + eff_R * T)
    pred_approx = eff_R * T / P

    print(
        f"abandon_rate={R} immediate_release_rate={I} payment_fail_rate={F}"
        f" timer={T}s purchase={P}s"
        f" concurrency={args.concurrency} duration={args.duration}s"
    )
    print(f"pred_exact={pred_exact:.3f}  pred_approx={pred_approx:.3f}")
    print(
        f"{'run':>4}  {'confirmed':>10} {'rejected':>9} {'abandoned':>10}"
        f" {'imm_rel':>8} {'pay_fail':>9} {'exp_co':>7} {'sweeper':>8}"
        f" {'mean_dead':>10} {'mean_total':>11} {'measured':>9}"
    )

    for r in range(1, args.runs + 1):
        res = run_once(R, I, F, T, P, args.concurrency, args.duration, args.init_stock)
        print(
            f"{r:>4}  {res['confirmed']:>10} {res['rejected']:>9} {res['abandoned']:>10}"
            f" {res['immediate_released']:>8} {res['payment_failed']:>9}"
            f" {res['expired_during_checkout']:>7} {res['released']:>8}"
            f" {res['mean_dead']:>10.1f} {res['mean_total']:>11.1f} {res['measured']:>9.3f}"
        )


if __name__ == "__main__":
    main()
