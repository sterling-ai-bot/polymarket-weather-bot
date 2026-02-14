"""Daily summary of executed paper trades ($SIM) and other activity.

Posts a concise digest: count, net $SIM cost, and list of trades (most recent first).

Run under op:
  SIMMER_API_KEY='op://SterlingArcherVault/Simmer API Key/password' \
    op run -- python -m bot.daily_summary --venue simmer --limit 50
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .simmer_client import SimmerClient


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--venue", type=str, default="simmer", help="simmer|polymarket|kalshi (or empty for all)")
    ap.add_argument("--source", type=str, default="sdk:weather:paper", help="filter to our paper-trade source tag")
    args = ap.parse_args()

    c = SimmerClient()
    me = c.me()

    venue = args.venue.strip() if args.venue else None
    data = c.trades(limit=args.limit, venue=venue or None)
    trades = data.get("trades", []) or []

    # Filter to our paper trade source by default
    if args.source:
        trades = [t for t in trades if (t.get("source") == args.source)]

    total = len(trades)
    net_cost = sum(safe_float(t.get("cost")) for t in trades if t.get("action") == "buy")

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    print(f"Daily trade summary (UTC {now})")
    print(f"agent={me.get('name')} venue={venue or 'all'} source={args.source} trades={total} buy_cost_sum={net_cost:.2f}")

    for t in trades[:20]:
        q = t.get("market_question") or t.get("market") or "?"
        created = t.get("created_at") or "?"
        action = t.get("action")
        side = t.get("side")
        shares = t.get("shares")
        cost = t.get("cost")
        print(f"- {created} {action} {side} shares={shares} cost={cost} :: {q}")


if __name__ == "__main__":
    main()
