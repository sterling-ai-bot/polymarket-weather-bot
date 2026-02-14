"""Simulate trades for top candidates using Simmer dry_run.

This does NOT place real trades.

Example:
  SIMMER_API_KEY='op://SterlingArcherVault/Simmer API Key/password' \
    op run -- python -m bot.sim_trades --cities "nyc,new york,chicago" --limit 50 --min-div 0.02 --amount 5
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .simmer_client import SimmerClient


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--min-div", type=float, default=0.02)
    ap.add_argument("--cities", type=str, default="nyc,new york,chicago")
    ap.add_argument("--amount", type=float, default=5.0, help="USD amount for dry-run buy (deprecated; use --amounts)")
    ap.add_argument("--amounts", type=str, default="2,5,10", help="comma-separated USD notionals for dry-run buys")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--venue", type=str, default="polymarket", choices=["polymarket", "simmer", "kalshi"])
    args = ap.parse_args()

    city_terms = [c.strip().lower() for c in (args.cities or "").split(",") if c.strip()]

    c = SimmerClient()
    data = c.list_markets(tags="weather", limit=args.limit)
    markets = data.get("markets", [])

    candidates = []
    for m in markets:
        q = (m.get("question") or "").strip()
        if city_terms:
            q_l = q.lower()
            if not any(t in q_l for t in city_terms):
                continue
        div = safe_float(m.get("divergence"))
        if div is None or abs(div) < args.min_div:
            continue
        candidates.append(
            {
                "id": m.get("id"),
                "question": q,
                "div": div,
                "price": safe_float(m.get("current_probability")),
                "url": m.get("url"),
            }
        )

    candidates.sort(key=lambda r: abs(r["div"]), reverse=True)
    picks = candidates[: max(0, args.top)]

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    print(f"sim_trades_at={now} picks={len(picks)}")

    amounts = []
    for part in (args.amounts or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            amounts.append(float(part))
        except Exception:
            pass
    if not amounts:
        amounts = [float(args.amount)]

    for p in picks:
        market_id = p["id"]
        if not market_id:
            continue

        print(f"- {p['question']}")
        if p.get("url"):
            print(f"  {p['url']}")
        print(f"  div={p['div']:+.3f} price={p['price']}")

        for amt in amounts:
            reasoning = f"dry_run sim: divergence={p['div']:+.3f} price={p['price']} amount={amt}"
            res = c.dry_run_trade(
                market_id=market_id,
                side="yes",
                amount=amt,
                venue=args.venue,
                reasoning=reasoning,
                source="sdk:weather:dry_run",
            )
            est_shares = res.get("shares_bought") or res.get("shares") or res.get("estimated_shares")
            cost = res.get("cost") or res.get("amount")
            fee_bps = res.get("fee_rate_bps")
            print(f"    sim amount={amt} venue={args.venue} est_shares={est_shares} fee_bps={fee_bps} cost={cost}")


if __name__ == "__main__":
    main()
