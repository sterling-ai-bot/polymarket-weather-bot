#!/usr/bin/env python3
"""Backtest PnL comparison with cooldown.

Per user request:
- Load data/sim_log.jsonl
- Simulate trades with cooldown=360min, max_trades_per_snapshot=1
- Scenario A (current): min_div=0.12, max_price=0.20
- Scenario B (proposed): min_div=0.10, max_price=0.20
- Fetch current market info via Simmer API (/api/sdk/markets?ids=...)
- Realized value uses final outcome (yes/no) if available, else current_probability

Trade model (matches existing bot/backtest.py + historical_backtest.py):
- Consider only target city questions (NYC, Chicago)
- Consider only positive divergence (div >= min_div)
- Filter by simmer_price <= max_price (the Simmer prob in the snapshot)
- Execute a BUY-YES with notional $10 using orderbook walk closest to $10

Outputs a plain-text summary.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

LOG_PATH = Path(__file__).resolve().parent / "data" / "sim_log.jsonl"
TRADE_NOTIONAL = 10.0
COOLDOWN_MINUTES = 360
MAX_TRADES_PER_SNAPSHOT = 1


def safe_float(x) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def parse_ts(ts: str) -> datetime:
    # log uses RFC3339 with Z
    ts = (ts or "").strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def is_target_city(question: str) -> Tuple[bool, Optional[str]]:
    q = (question or "").lower()
    if ("nyc" in q) or ("new york" in q):
        return True, "nyc"
    if "chicago" in q:
        return True, "chicago"
    return False, None


def closest_walk_for_notional(walks: Any, target_notional: float) -> Optional[Dict[str, Any]]:
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


@dataclass
class Trade:
    ts: datetime
    market_id: str
    question: str
    city: str
    divergence: float
    simmer_price: float
    fill_price: float
    shares: float
    cost: float


def load_snapshots() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    # sort just in case
    rows.sort(key=lambda r: r.get("ts") or "")
    return rows


def simulate_trades(
    snapshots: List[Dict[str, Any]],
    *,
    min_div: float,
    max_price: float,
    cooldown_minutes: int,
    max_trades_per_snapshot: int,
) -> List[Trade]:
    cooldown = timedelta(minutes=cooldown_minutes)
    last_trade_by_market: Dict[str, datetime] = {}
    trades: List[Trade] = []

    for snap in snapshots:
        ts_raw = snap.get("ts")
        if not ts_raw:
            continue
        snap_ts = parse_ts(ts_raw)

        picks = snap.get("picks") or []
        if not isinstance(picks, list):
            continue

        placed = 0
        for p in picks:
            if placed >= max_trades_per_snapshot:
                break

            q = p.get("question") or ""
            ok, city = is_target_city(q)
            if not ok or not city:
                continue

            div = safe_float(p.get("divergence"))
            simmer = safe_float(p.get("simmer_price"))
            if div is None or simmer is None:
                continue

            # Only take positive divergence, as in existing backtest scripts.
            if div < min_div:
                continue
            if simmer > max_price:
                continue

            mid = p.get("market_id")
            if not mid:
                continue

            prev = last_trade_by_market.get(mid)
            if prev is not None and (snap_ts - prev) < cooldown:
                continue

            ob = p.get("orderbook") or {}
            walks = ob.get("walks") if isinstance(ob, dict) else None
            walk = closest_walk_for_notional(walks, TRADE_NOTIONAL)
            if not walk:
                continue

            fill = safe_float(walk.get("avg_price"))
            shares = safe_float(walk.get("shares"))
            if fill is None or shares is None:
                continue

            t = Trade(
                ts=snap_ts,
                market_id=mid,
                question=q,
                city=city,
                divergence=div,
                simmer_price=simmer,
                fill_price=fill,
                shares=shares,
                cost=TRADE_NOTIONAL,
            )
            trades.append(t)
            last_trade_by_market[mid] = snap_ts
            placed += 1

    return trades


def fetch_markets_by_ids(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    api_key = os.environ.get("SIMMER_API_KEY")
    if not api_key:
        raise RuntimeError("Missing SIMMER_API_KEY")

    # API supports ids=csv
    url = "https://api.simmer.markets/api/sdk/markets"

    out: Dict[str, Dict[str, Any]] = {}
    batch = 50
    for i in range(0, len(ids), batch):
        sub = ids[i : i + batch]
        params = {"ids": ",".join(sub)}
        r = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        markets = data.get("markets") if isinstance(data, dict) else None
        if not isinstance(markets, list):
            continue
        for m in markets:
            mid = (m or {}).get("id")
            if mid:
                out[mid] = m

    return out


def trade_value(trade: Trade, market: Optional[Dict[str, Any]]) -> Tuple[float, str]:
    """Returns (value_usd, valuation_source)."""
    if not market:
        # no market info; assume 0.5 as a last resort
        return trade.shares * 0.5, "fallback_prob=0.5"

    outcome = (market.get("outcome") or "").lower().strip() if market.get("outcome") is not None else None
    cp = safe_float(market.get("current_probability"))

    if outcome == "yes":
        return trade.shares * 1.0, "outcome=yes"
    if outcome == "no":
        return 0.0, "outcome=no"

    # unresolved
    if cp is None:
        return trade.shares * 0.5, "fallback_prob=0.5"
    return trade.shares * cp, "current_probability"


def summarize(trades: List[Trade], markets: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    per_market: Dict[str, Dict[str, Any]] = {}
    total_cost = 0.0
    total_value = 0.0

    for t in trades:
        m = markets.get(t.market_id)
        v, src = trade_value(t, m)
        total_cost += t.cost
        total_value += v

        row = per_market.setdefault(
            t.market_id,
            {
                "market_id": t.market_id,
                "question": t.question,
                "trades": 0,
                "cost": 0.0,
                "value": 0.0,
                "shares": 0.0,
                "avg_fill_price": 0.0,
                "_fill_cost": 0.0,
                "valuation_sources": {},
                "outcome": (m.get("outcome") if m else None),
                "current_probability": (safe_float(m.get("current_probability")) if m else None),
            },
        )
        row["trades"] += 1
        row["cost"] += t.cost
        row["value"] += v
        row["shares"] += t.shares
        row["_fill_cost"] += t.fill_price * t.shares
        row["valuation_sources"][src] = row["valuation_sources"].get(src, 0) + 1

    for mid, row in per_market.items():
        shares = row["shares"]
        row["avg_fill_price"] = (row["_fill_cost"] / shares) if shares else 0.0
        row["pnl"] = row["value"] - row["cost"]
        del row["_fill_cost"]

    pnl = total_value - total_cost
    roi = (pnl / total_cost) if total_cost else 0.0

    return {
        "trades": len(trades),
        "total_cost": total_cost,
        "total_value": total_value,
        "total_pnl": pnl,
        "roi": roi,
        "per_market": per_market,
    }


def fmt_usd(x: float) -> str:
    return f"${x:,.2f}"


def main():
    snapshots = load_snapshots()

    scenarios = [
        ("current", 0.12, 0.20),
        ("proposed", 0.10, 0.20),
    ]

    trades_by_name: Dict[str, List[Trade]] = {}
    all_market_ids: List[str] = []

    for name, min_div, max_price in scenarios:
        trades = simulate_trades(
            snapshots,
            min_div=min_div,
            max_price=max_price,
            cooldown_minutes=COOLDOWN_MINUTES,
            max_trades_per_snapshot=MAX_TRADES_PER_SNAPSHOT,
        )
        trades_by_name[name] = trades
        all_market_ids.extend([t.market_id for t in trades])

    unique_ids = sorted(set(all_market_ids))
    markets = fetch_markets_by_ids(unique_ids) if unique_ids else {}

    summaries = {name: summarize(trades, markets) for name, trades in trades_by_name.items()}

    # Print summary
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    print(f"Backtest PnL comparison (run_at={now})")
    print(f"Log: {LOG_PATH}")
    print(f"Rules: cooldown={COOLDOWN_MINUTES}min, max_trades_per_snapshot={MAX_TRADES_PER_SNAPSHOT}, notional=${TRADE_NOTIONAL:.0f}, side=BUY-YES")
    print("")

    for name, min_div, max_price in scenarios:
        s = summaries[name]
        print(f"=== Scenario: {name} (min_div={min_div:.2f}, max_price={max_price:.2f}) ===")
        print(f"Trades: {s['trades']}")
        print(f"Total cost:  {fmt_usd(s['total_cost'])}")
        print(f"Total value: {fmt_usd(s['total_value'])}")
        print(f"Total PnL:   {fmt_usd(s['total_pnl'])}")
        print(f"ROI:         {s['roi']*100:.2f}%")
        print("Per-market breakdown:")
        pm = list(s["per_market"].values())
        pm.sort(key=lambda r: r["pnl"], reverse=True)
        if not pm:
            print("  (no trades)")
        for r in pm:
            outcome = r.get("outcome")
            cp = r.get("current_probability")
            outcome_s = (str(outcome).lower() if outcome is not None else f"prob={cp:.3f}" if cp is not None else "unknown")
            print(
                "  - "
                + r["market_id"]
                + f" | trades={r['trades']} | cost={fmt_usd(r['cost'])} | value={fmt_usd(r['value'])} | pnl={fmt_usd(r['pnl'])} | avg_fill={r['avg_fill_price']:.4f} | {outcome_s}"
            )
            q = (r.get("question") or "").strip()
            if q:
                print(f"      {q}")
        print("")

    # Conclusion
    cur = summaries["current"]["total_pnl"]
    prop = summaries["proposed"]["total_pnl"]
    if prop > cur:
        winner = "proposed"
    elif cur > prop:
        winner = "current"
    else:
        winner = "tie"

    print("=== Conclusion ===")
    if winner == "tie":
        print(f"Tie: both scenarios returned the same total PnL ({fmt_usd(cur)}).")
    else:
        diff = prop - cur
        print(f"Winner: {winner}")
        print(f"PnL difference (proposed - current): {fmt_usd(diff)}")


if __name__ == "__main__":
    main()
