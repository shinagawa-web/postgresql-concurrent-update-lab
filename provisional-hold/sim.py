#!/usr/bin/env python3
"""
In-memory discrete-event simulation (no DB required).
Same parameter names as run.py. Time unit: 1 = 1 minute.
"""
import argparse
import heapq
import math
import random
import statistics


def _lognormal(rng, p50, p95):
    mu = math.log(p50)
    sigma = (math.log(p95) - mu) / 1.645
    return rng.lognormvariate(mu, sigma)


def simulate(stock, n_customers, window, abandon_rate, timer, sweep, purchase, p95, remove_rate, seed):
    D = window * 60
    T = timer * 60
    delta = sweep * 60
    p50_s = purchase * 60
    p95_s = p95 * 60

    rng = random.Random(seed)
    ev, seq = [], 0

    def push(t, kind, data=None):
        nonlocal seq
        heapq.heappush(ev, (t, seq, kind, data))
        seq += 1

    for _ in range(n_customers):
        push(rng.uniform(0, D), "cart", rng.random() < abandon_rate)
    t = 0.0
    while t <= D + 3 * T + p95_s * 3:
        push(t, "sweep")
        t += delta

    stock_left = stock
    holds = {}
    res = dict(confirmed=0, expired_during_checkout=0, lost_sale=0)
    hid = 0

    while ev:
        now, _, kind, data = heapq.heappop(ev)
        if kind == "cart":
            is_abandoner = data
            if stock_left == 0:
                if not is_abandoner:
                    if any(h["abandoner"] and h["state"] == "reserved" for h in holds.values()):
                        res["lost_sale"] += 1
                continue
            stock_left -= 1
            hid += 1
            holds[hid] = dict(expires=now + T, abandoner=is_abandoner, state="reserved")
            if not is_abandoner:
                push(now + _lognormal(rng, p50_s, p95_s), "checkout", hid)
            elif rng.random() < remove_rate:
                push(now + rng.uniform(0, T), "remove", hid)
        elif kind == "checkout":
            h = holds[data]
            if h["state"] == "reserved" and now < h["expires"]:
                h["state"] = "confirmed"
                res["confirmed"] += 1
            else:
                res["expired_during_checkout"] += 1
        elif kind == "remove":
            h = holds[data]
            if h["state"] == "reserved":
                h["state"] = "released"
                stock_left += 1
        elif kind == "sweep":
            for h in holds.values():
                if h["state"] == "reserved" and h["expires"] <= now:
                    h["state"] = "expired"
                    stock_left += 1

    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stock", type=int, default=100)
    p.add_argument("--customers", type=int, default=300)
    p.add_argument("--window", type=float, default=30.0, help="arrival window (min)")
    p.add_argument("--purchase", type=float, default=2.0, help="p50 checkout (min)")
    p.add_argument("--p95", type=float, default=None, help="p95 checkout (min, default: 3x --purchase)")
    p.add_argument("--abandon-rate", type=float, default=0.5)
    p.add_argument("--timers", type=str, default="1,2,3,5,7,10,15,20", help="comma-separated T values (min)")
    p.add_argument("--sweep", type=float, default=10 / 60, help="sweep interval (min, default: 10s)")
    p.add_argument("--remove-rate", type=float, default=0.0)
    p.add_argument("--runs", type=int, default=30)
    args = p.parse_args()

    P95 = args.p95 if args.p95 is not None else args.purchase * 3
    T_values = [float(t) for t in args.timers.split(",")]
    R = args.abandon_rate

    print(
        f"customers={args.customers} window={args.window}min stock={args.stock}"
        f" abandon_rate={R} p50={args.purchase}min p95={P95}min runs={args.runs}"
    )
    print(f"{'T(min)':>7}  {'confirmed':>10} {'exp_during_co':>14} {'lost_sale':>10}")

    for T in T_values:
        rs = [
            simulate(args.stock, args.customers, args.window, R, T,
                     args.sweep, args.purchase, P95, args.remove_rate, seed)
            for seed in range(args.runs)
        ]
        m = lambda k: statistics.mean(r[k] for r in rs)
        print(
            f"{T:>7.0f}  {m('confirmed'):>10.1f}"
            f" {m('expired_during_checkout'):>14.1f}"
            f" {m('lost_sale'):>10.1f}"
        )


if __name__ == "__main__":
    main()
