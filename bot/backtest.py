"""Backtest paper-trade heuristic from hourly JSONL snapshots.

Reads data/sim_log.jsonl written by bot.hourly_log and sweeps:
- min_div
- max_entry_price
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_SWEEP_DIVS = [0.08, 0.10, 0.12, 0.15, 0.20]
DEFAULT_SWEEP_PRICES = [0.15, 0.20, 0.25, 0.30, 0.50]
TRADE_NOTIONAL = 10.0


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def parse_float_csv(raw: str | None, default_vals: list[float]) -> list[float]:
    if not raw:
        return list(default_vals)
    vals = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        vals.append(float(part))
    return vals


def is_target_city(question: str) -> tuple[bool, str | None]:
    q = (question or "").lower()
    if ("nyc" in q) or ("new york" in q):
        return True, "nyc"
    if "chicago" in q:
        return True, "chicago"
    return False, None


def closest_walk_for_notional(walks, target_notional: float):
    if not isinstance(walks, list) or not walks:
        return None
    best = None
    best_dist = None
    for w in walks:
        n = safe_float((w or {}).get("notional"))
        if n is None:
            continue
        dist = abs(n - target_notional)
        if best is None or dist < best_dist:
            best = w
            best_dist = dist
    return best


def load_snapshots(log_path: Path):
    rows = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def run_backtest(log_path: Path, sweep_divs: list[float], sweep_prices: list[float]):
    snapshots = load_snapshots(log_path)

    results = []
    for min_div in sweep_divs:
        for max_price in sweep_prices:
            trades = 0
            sum_div = 0.0
            sum_fill = 0.0
            sum_edge = 0.0
            total_shares = 0.0
            nyc_count = 0
            chicago_count = 0

            for snap in snapshots:
                picks = snap.get("picks") or []
                if not isinstance(picks, list):
                    continue

                for p in picks:
                    q = p.get("question") or ""
                    city_ok, city = is_target_city(q)
                    if not city_ok:
                        continue

                    div = safe_float(p.get("divergence"))
                    simmer_price = safe_float(p.get("simmer_price"))
                    if div is None or simmer_price is None:
                        continue
                    if div < min_div:
                        continue
                    if simmer_price > max_price:
                        continue

                    ob = p.get("orderbook") or {}
                    walks = ob.get("walks") if isinstance(ob, dict) else None
                    walk = closest_walk_for_notional(walks, TRADE_NOTIONAL)
                    if not walk:
                        continue
                    fill_price = safe_float(walk.get("avg_price"))
                    shares = safe_float(walk.get("shares"))
                    if fill_price is None or shares is None:
                        continue

                    edge = simmer_price - fill_price
                    trades += 1
                    sum_div += div
                    sum_fill += fill_price
                    sum_edge += edge
                    total_shares += shares
                    if city == "nyc":
                        nyc_count += 1
                    elif city == "chicago":
                        chicago_count += 1

            row = {
                "min_div": min_div,
                "max_price": max_price,
                "trades": trades,
                "avg_divergence": (sum_div / trades) if trades else 0.0,
                "avg_fill_price": (sum_fill / trades) if trades else 0.0,
                "avg_edge": (sum_edge / trades) if trades else 0.0,
                "total_shares": total_shares,
                "nyc_count": nyc_count,
                "chicago_count": chicago_count,
            }
            results.append(row)

    return results


def print_table(rows):
    headers = [
        "min_div",
        "max_price",
        "trades",
        "avg_divergence",
        "avg_fill_price",
        "avg_edge",
        "total_shares",
        "nyc_count",
        "chicago_count",
    ]
    print(" ".join(headers))
    for r in rows:
        print(
            f"{r['min_div']:.2f} "
            f"{r['max_price']:.2f} "
            f"{r['trades']} "
            f"{r['avg_divergence']:.6f} "
            f"{r['avg_fill_price']:.6f} "
            f"{r['avg_edge']:.6f} "
            f"{r['total_shares']:.6f} "
            f"{r['nyc_count']} "
            f"{r['chicago_count']}"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep-divs", type=str, default=None, help="comma-separated min_div values")
    ap.add_argument("--sweep-prices", type=str, default=None, help="comma-separated max_entry_price values")
    ap.add_argument("--output", type=str, default=None, help="results json path")
    ap.add_argument("--log-path", type=str, default=None, help="input sim_log.jsonl path")
    args = ap.parse_args()

    base = Path(__file__).resolve().parent.parent
    log_path = Path(args.log_path) if args.log_path else (base / "data" / "sim_log.jsonl")
    output_path = Path(args.output) if args.output else (base / "data" / "backtest_results.json")

    sweep_divs = parse_float_csv(args.sweep_divs, DEFAULT_SWEEP_DIVS)
    sweep_prices = parse_float_csv(args.sweep_prices, DEFAULT_SWEEP_PRICES)

    results = run_backtest(log_path=log_path, sweep_divs=sweep_divs, sweep_prices=sweep_prices)
    print_table(results)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "log_path": str(log_path),
        "trade_notional": TRADE_NOTIONAL,
        "sweep_divs": sweep_divs,
        "sweep_prices": sweep_prices,
        "results": results,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote results to {output_path}")


if __name__ == "__main__":
    main()
