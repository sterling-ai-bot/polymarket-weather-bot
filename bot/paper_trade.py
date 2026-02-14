"""Place *paper* trades using Simmer venue (virtual $SIM).

Safety:
- Trades are on venue="simmer" only (virtual currency).
- Hard caps: max_trades_per_run and amount.
- Only trades if divergence is positive (Simmer thinks probability > market yes price).
- Avoid repeat-trading same market within a cooldown window.

Run under op:
  SIMMER_API_KEY='op://SterlingArcherVault/Simmer API Key/password' \
    op run -- python -m bot.paper_trade --cities "nyc,new york,chicago" --limit 80 --min-div 0.12 --max-entry-price 0.20 --amount 10 --max-trades 1
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .simmer_client import SimmerClient


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--cities", type=str, default="nyc,new york,chicago")
    ap.add_argument("--min-div", type=float, default=0.12, help="min divergence to trade (must be positive)")
    ap.add_argument("--max-entry-price", type=float, default=0.20, help="max market yes price to enter")
    ap.add_argument("--amount", type=float, default=10.0, help="$SIM notional to buy")
    ap.add_argument("--max-trades", type=int, default=1)
    ap.add_argument("--cooldown-min", type=int, default=360, help="avoid re-trading same market within cooldown")
    args = ap.parse_args()

    cities = [c.strip().lower() for c in (args.cities or "").split(",") if c.strip()]

    base = Path(__file__).resolve().parent.parent
    state_path = base / "data" / "paper_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {"last_trade": {}}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text("utf-8"))
        except Exception:
            state = {"last_trade": {}}

    c = SimmerClient()
    data = c.list_markets(tags="weather", limit=args.limit)
    markets = data.get("markets", [])

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=args.cooldown_min)

    candidates = []
    for m in markets:
        q = (m.get("question") or "").strip()
        q_l = q.lower()
        if cities and not any(t in q_l for t in cities):
            continue
        div = safe_float(m.get("divergence"))
        price = safe_float(m.get("current_probability"))
        if div is None or price is None:
            continue
        if div < args.min_div:
            continue
        if price > args.max_entry_price:
            continue
        market_id = m.get("id")
        if not market_id:
            continue
        last = state.get("last_trade", {}).get(market_id)
        if last:
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if last_dt > cutoff:
                    continue
            except Exception:
                pass
        candidates.append({"id": market_id, "q": q, "div": div, "price": price, "url": m.get("url")})

    candidates.sort(key=lambda r: r["div"], reverse=True)
    picks = candidates[: max(0, args.max_trades)]

    print(f"paper_trade_at={now.isoformat().replace('+00:00','Z')} picks={len(picks)}")

    trades = []
    for p in picks:
        reasoning = f"paper trade ($SIM): div={p['div']:+.3f} yes_price={p['price']:.3f}"
        res = c.trade(
            market_id=p["id"],
            side="yes",
            amount=float(args.amount),
            venue="simmer",
            reasoning=reasoning,
            source="sdk:weather:paper",
            dry_run=False,
        )
        trades.append({"market_id": p["id"], "url": p.get("url"), "question": p["q"], "amount": args.amount, "response": res})
        state.setdefault("last_trade", {})[p["id"]] = now.isoformat().replace("+00:00", "Z")
        print(f"- TRADED: div={p['div']:+.3f} price={p['price']:.3f} amount={args.amount} $SIM")
        print(f"  {p['q']}")
        if p.get("url"):
            print(f"  {p['url']}")

    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
