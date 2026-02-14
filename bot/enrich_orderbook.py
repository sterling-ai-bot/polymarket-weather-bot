"""Enrich Simmer weather candidates with Polymarket CLOB top-of-book + slippage curve.

This is read-only market data.

Example:
  SIMMER_API_KEY='op://SterlingArcherVault/Simmer API Key/password' \
    op run -- python -m bot.enrich_orderbook --cities "nyc,new york,chicago" --limit 50 --min-div 0.02 --notionals 2,5,10
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .simmer_client import SimmerClient
from .polymarket_clob import PolymarketCLOB, best_bid_ask_from_book, walk_cost_from_asks


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
    ap.add_argument("--notionals", type=str, default="2,5,10")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    city_terms = [c.strip().lower() for c in (args.cities or "").split(",") if c.strip()]
    notionals = []
    for p in (args.notionals or "").split(","):
        p = p.strip()
        if not p:
            continue
        try:
            notionals.append(float(p))
        except Exception:
            pass
    if not notionals:
        notionals = [2.0, 5.0, 10.0]

    c = SimmerClient()
    data = c.list_markets(tags="weather", limit=args.limit)
    markets = data.get("markets", [])

    cands = []
    for m in markets:
        q = (m.get("question") or "").strip()
        if city_terms:
            q_l = q.lower()
            if not any(t in q_l for t in city_terms):
                continue
        div = safe_float(m.get("divergence"))
        if div is None or abs(div) < args.min_div:
            continue
        token_id = m.get("polymarket_token_id")
        if not token_id:
            continue
        cands.append(
            {
                "id": m.get("id"),
                "question": q,
                "div": div,
                "price": safe_float(m.get("current_probability")),
                "url": m.get("url"),
                "token_id": str(token_id),
            }
        )

    cands.sort(key=lambda r: abs(r["div"]), reverse=True)
    cands = cands[: max(0, args.top)]

    clob = PolymarketCLOB()
    books = clob.books([x["token_id"] for x in cands])
    # books are in same order as request per docs, but be defensive with token_id key
    by_tid = {}
    for b in books:
        tid = str(b.get("asset_id") or b.get("token_id") or "")
        if tid:
            by_tid[tid] = b

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    print(f"enrich_at={now} candidates={len(cands)}")

    for cand in cands:
        tid = cand["token_id"]
        book = by_tid.get(tid)
        print(f"- {cand['question']}")
        if cand.get("url"):
            print(f"  {cand['url']}")
        print(f"  div={cand['div']:+.3f} simmer_price={cand['price']} token_id={tid}")
        if not book:
            print("  orderbook: MISSING")
            continue
        tob = best_bid_ask_from_book(book)
        spread = None
        if tob.best_bid is not None and tob.best_ask is not None:
            spread = tob.best_ask - tob.best_bid
        print(f"  tob bid={tob.best_bid} ask={tob.best_ask} spread={spread}")
        for n in notionals:
            walked = walk_cost_from_asks(book, n)
            if not walked:
                print(f"    walk ${n}: unavailable")
                continue
            avg_price, shares = walked
            print(f"    walk ${n}: avg_price={avg_price:.4f} shares={shares:.2f}")


if __name__ == "__main__":
    main()
