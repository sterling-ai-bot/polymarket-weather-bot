"""Backtest against actual paper trade history."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def is_target_city(q: str):
    qc = (q or "").lower()
    if "nyc" in qc or "new york" in qc:
        return True, "nyc"
    if "chicago" in qc:
        return True, "chicago"
    return False, None


def simulate_from_snapshots(snapshots, *, min_div: float, max_price: float, log_path: Path):
    """Simulate which trades would have occurred with given thresholds using actual data."""
    # Load sim_log to get price/divergence data
    trades = []
    for snap in snapshots:
        ts = snap.get("ts", "")
        for p in (snap.get("picks") or []):
            q = p.get("question", "")
            ok, city = is_target_city(q)
            if not ok:
                continue

            div = safe_float(p.get("divergence"))
            simmer = safe_float(p.get("simmer_price"))
            if div is None or simmer is None:
                continue

            if div < min_div:
                continue
            if simmer > max_price:
                continue

            # Would trade here
            ob = p.get("orderbook") or {}
            walks = ob.get("walks") if isinstance(ob, dict) else None
            walk = None
            if walks:
                # Find closest to $10
                best = None
                best_dist = float("inf")
                for w in walks:
                    n = safe_float(w.get("notional"))
                    if n is None:
                        continue
                    dist = abs(n - 10.0)
                    if dist < best_dist:
                        best = w
                        best_dist = dist
                walk = best

            if not walk:
                continue

            trades.append(
                {
                    "ts": ts,
                    "market_id": p.get("market_id"),
                    "question": q,
                    "city": city,
                    "divergence": div,
                    "simmer_price": simmer,
                    "fill_price": safe_float(walk.get("avg_price")),
                    "shares": safe_float(walk.get("shares")),
                    "cost": 10.0,
                }
            )
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-div", type=float, default=0.12)
    ap.add_argument("--max-price", type=float, default=0.20)
    ap.add_argument("--log-path", type=str, default=str(Path("data") / "sim_log.jsonl"))
    args = ap.parse_args()

    log_path = Path(args.log_path)
    snapshots = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            snapshots.append(json.loads(line))

    # For now just print candidates
    trades = simulate_from_snapshots(snapshots, min_div=args.min_div, max_price=args.max_price, log_path=log_path)
    print(f"Candidates: {len(trades)}")
    for t in trades:
        print(f"  {t['ts'][:10]} | div={t['divergence']:.3f} | price={t['simmer_price']:.3f} | fill={t['fill_price']:.4f} | {t['question'][:60]}...")


if __name__ == "__main__":
    main()
