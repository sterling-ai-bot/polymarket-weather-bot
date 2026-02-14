"""Dry-run scanner for Simmer weather markets.

Usage:
  python -m bot.scan_weather --limit 30

Notes:
- Uses GET /api/sdk/markets?tags=weather
- Ranks by absolute divergence when available.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from dateutil.parser import isoparse

from .simmer_client import SimmerClient


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--min-div", type=float, default=0.10, help="minimum abs(divergence) to show")
    ap.add_argument("--since-hours", type=int, default=24, help="for briefing endpoint")
    ap.add_argument(
        "--cities",
        type=str,
        default="new york,nyc,chicago",
        help="comma-separated city keywords to filter questions (case-insensitive). empty=disable",
    )
    args = ap.parse_args()

    c = SimmerClient()
    me = c.me()

    print(f"agent: {me.get('name')}  status={me.get('status')}  sim_balance={me.get('balance')}  real_trading_enabled={me.get('real_trading_enabled')}")

    # Briefing (good single-call heartbeat)
    since = (datetime.now(timezone.utc) - timedelta(hours=args.since_hours)).isoformat().replace("+00:00", "Z")
    briefing = c.briefing(since)
    opps = briefing.get("opportunities", {})
    hd = opps.get("high_divergence", []) or []
    print(f"briefing.checked_at={briefing.get('checked_at')}  high_divergence={len(hd)}")

    # Weather market list
    data = c.list_markets(tags="weather", limit=args.limit)
    markets = data.get("markets", [])

    city_terms = [c.strip().lower() for c in (args.cities or "").split(",") if c.strip()]

    rows = []
    for m in markets:
        q = (m.get("question") or "").strip()
        if city_terms:
            q_l = q.lower()
            if not any(t in q_l for t in city_terms):
                continue

        div = safe_float(m.get("divergence"))
        if div is None:
            continue
        if abs(div) < args.min_div:
            continue
        resolves_at = m.get("resolves_at")
        try:
            resolves_dt = isoparse(resolves_at) if resolves_at else None
        except Exception:
            resolves_dt = None

        rows.append(
            {
                "id": m.get("id"),
                "question": q,
                "div": div,
                "score": safe_float(m.get("opportunity_score")),
                "price": safe_float(m.get("current_probability")),
                "resolves_at": resolves_dt,
                "url": m.get("url"),
            }
        )

    rows.sort(key=lambda r: abs(r["div"]), reverse=True)

    print("\nTop weather markets by |divergence|:\n")
    for r in rows[: min(len(rows), 20)]:
        ra = r["resolves_at"].isoformat() if r["resolves_at"] else "?"
        print(f"- |div|={abs(r['div']):.3f}  div={r['div']:+.3f}  price={r['price']}  score={r['score']}  resolves={ra}")
        print(f"  {r['question']}")
        if r.get("url"):
            print(f"  {r['url']}")


if __name__ == "__main__":
    main()
