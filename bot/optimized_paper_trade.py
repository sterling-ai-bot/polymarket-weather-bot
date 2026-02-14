"""Optimized paper trade executor with improved filtering.

Key improvements:
1. Tighter min_div threshold (0.10) based on backtest data
2. Spread-based execution quality filter
3. Time-to-resolution filtering
4. Price-spread-adjusted ranking
5. Expanded city coverage
"""
from __future__ import annotations
import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from dateutil.parser import isoparse

from .simmer_client import SimmerClient

DEFAULT_MIN_DIV = 0.10
DEFAULT_MAX_ENTRY_PRICE = 0.20
DEFAULT_MAX_SPREAD = 0.05
DEFAULT_MIN_HOURS = 12
DEFAULT_COOLDOWN_MIN = 360


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


@dataclass
class TradeCandidate:
    market_id: str
    question: str
    divergence: float
    price: float
    spread: Optional[float]
    hours: float
    url: Optional[str]


def load_state(state_path: Path) -> dict:
    if state_path.exists():
        try:
            return json.loads(state_path.read_text("utf-8"))
        except Exception:
            pass
    return {"last_trade": {}}


def in_cooldown(mid: str, state: dict, now: datetime, cooldown: int) -> bool:
    last = state.get("last_trade", {}).get(mid)
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        cutoff = now - timedelta(minutes=cooldown)
        return last_dt > cutoff
    except Exception:
        return False


def matches_city(q: str, cities: list[str]) -> bool:
    ql = q.lower()
    return any(c in ql for c in cities)


def hours_to_resolve(ts: Optional[str], now: datetime) -> float:
    if not ts:
        return float("inf")
    try:
        r = isoparse(ts)
        return (r - now).total_seconds() / 3600
    except Exception:
        return float("inf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--cities", type=str, default=None)
    ap.add_argument("--min-div", type=float, default=DEFAULT_MIN_DIV)
    ap.add_argument("--max-price", type=float, default=DEFAULT_MAX_ENTRY_PRICE)
    ap.add_argument("--max-spread", type=float, default=DEFAULT_MAX_SPREAD)
    ap.add_argument("--min-hours", type=float, default=DEFAULT_MIN_HOURS)
    ap.add_argument("--amount", type=float, default=10.0)
    ap.add_argument("--max-trades", type=int, default=1)
    ap.add_argument("--cooldown-min", type=int, default=DEFAULT_COOLDOWN_MIN)
    args = ap.parse_args()

    base = Path(__file__).resolve().parent.parent
    state_path = base / "data" / "paper_state.json"
    state = load_state(state_path)

    cities = [c.strip().lower() for c in (args.cities or "nyc,new york,chicago,la,los angeles,miami").split(",") if c.strip()]
    now = datetime.now(timezone.utc)

    c = SimmerClient()
    data = c.list_markets(tags="weather", limit=args.limit)
    markets = data.get("markets", [])

    candidates = []
    for m in markets:
        q = (m.get("question") or "").strip()
        if not matches_city(q, cities):
            continue

        mid = m.get("id")
        if not mid or in_cooldown(mid, state, now, args.cooldown_min):
            continue

        div = safe_float(m.get("divergence"))
        price = safe_float(m.get("current_probability"))
        if div is None or price is None:
            continue
        if div < args.min_div or price > args.max_price:
            continue

        hrs = hours_to_resolve(m.get("resolves_at"), now)
        if hrs < args.min_hours:
            continue

        # Spread check if orderbook available
        spread = None
        ob = m.get("orderbook")
        if isinstance(ob, dict):
            ba = safe_float(ob.get("best_ask"))
            bb = safe_float(ob.get("best_bid"))
            if ba is not None and bb is not None:
                spread = ba - bb
                if spread > args.max_spread:
                    continue

        candidates.append(TradeCandidate(
            market_id=mid,
            question=q,
            divergence=div,
            price=price,
            spread=spread,
            hours=hrs,
            url=m.get("url"),
        ))

    # Rank: highest divergence, lowest spread
    def score(tc: TradeCandidate) -> float:
        s = tc.spread if tc.spread else 0.01
        return tc.divergence / (tc.price * s + 0.001)

    candidates.sort(key=score, reverse=True)
    picks = candidates[: max(0, args.max_trades)]

    print(f"optimized_paper_trade: picks={len(picks)} from {len(candidates)} candidates")

    trades = []
    for p in picks:
        r = c.trade(
            market_id=p.market_id,
            side="yes",
            amount=args.amount,
            venue="simmer",
            reasoning=f"div={p.divergence:.3f} price={p.price:.3f}",
            source="sdk:optimized",
            dry_run=False,
        )
        trades.append({"market": p.question, "response": r})
        print(f"  - traded: {p.question[:60]}")
        state.setdefault("last_trade", {})[p.market_id] = now.isoformat()

    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
