"""Hourly runner that logs scan + sims + orderbook enrichment to JSONL.

Dry-run only.

Writes: data/sim_log.jsonl (one JSON object per run)

Run under op:
  SIMMER_API_KEY='op://SterlingArcherVault/Simmer API Key/password' \
    op run -- python -m bot.hourly_log
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .simmer_client import SimmerClient
from .polymarket_clob import PolymarketCLOB, best_bid_ask_from_book, walk_cost_from_asks


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def main():
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    base = Path(__file__).resolve().parent.parent
    data_dir = base / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "sim_log.jsonl"

    cities = ["nyc", "new york", "chicago"]
    limit = 80
    min_div = 0.02
    top = 3
    notionals = [2.0, 5.0, 10.0]

    c = SimmerClient()
    me = c.me()

    markets = c.list_markets(tags="weather", limit=limit).get("markets", [])

    cands = []
    for m in markets:
        q = (m.get("question") or "").strip()
        q_l = q.lower()
        if not any(t in q_l for t in cities):
            continue
        div = safe_float(m.get("divergence"))
        if div is None or abs(div) < min_div:
            continue
        token_id = m.get("polymarket_token_id")
        cands.append(
            {
                "market_id": m.get("id"),
                "question": q,
                "divergence": div,
                "simmer_price": safe_float(m.get("current_probability")),
                "opportunity_score": safe_float(m.get("opportunity_score")),
                "resolves_at": m.get("resolves_at"),
                "url": m.get("url"),
                "polymarket_token_id": str(token_id) if token_id else None,
            }
        )

    cands.sort(key=lambda r: abs(r["divergence"]), reverse=True)
    picks = [x for x in cands if x.get("market_id")][:top]

    # dry-run sims + orderbook
    clob = PolymarketCLOB()
    token_ids = [p["polymarket_token_id"] for p in picks if p.get("polymarket_token_id")]
    books = clob.books(token_ids) if token_ids else []
    by_tid = {}
    for b in books:
        tid = str(b.get("asset_id") or b.get("token_id") or "")
        if tid:
            by_tid[tid] = b

    enriched = []
    for p in picks:
        sims = []
        for amt in notionals:
            res = c.dry_run_trade(
                market_id=p["market_id"],
                side="yes",
                amount=amt,
                venue="polymarket",
                reasoning=f"hourly dry_run: div={p['divergence']:+.3f} price={p['simmer_price']} amt={amt}",
                source="sdk:weather:dry_run",
            )
            sims.append(
                {
                    "amount": amt,
                    "fee_rate_bps": res.get("fee_rate_bps"),
                    "est_shares": res.get("shares_bought") or res.get("shares") or res.get("estimated_shares"),
                    "cost": res.get("cost") or res.get("amount"),
                }
            )

        ob = None
        tid = p.get("polymarket_token_id")
        if tid and tid in by_tid:
            book = by_tid[tid]
            tob = best_bid_ask_from_book(book)
            walks = []
            for n in notionals:
                walked = walk_cost_from_asks(book, n)
                if walked:
                    avg_price, shares = walked
                    walks.append({"notional": n, "avg_price": avg_price, "shares": shares})
            ob = {
                "best_bid": tob.best_bid,
                "best_ask": tob.best_ask,
                "spread": (tob.best_ask - tob.best_bid) if (tob.best_bid is not None and tob.best_ask is not None) else None,
                "walks": walks,
            }

        enriched.append({**p, "sims": sims, "orderbook": ob})

    row = {
        "ts": now,
        "agent": {"name": me.get("name"), "agent_id": me.get("agent_id"), "status": me.get("status")},
        "params": {"cities": cities, "limit": limit, "min_div": min_div, "top": top, "notionals": notionals},
        "picks": enriched,
    }

    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # concise stdout for cron
    print(f"Status=OK logged={log_path} picks={len(enriched)}")
    for p in enriched[:3]:
        print(f"- |div|={abs(p['divergence']):.3f} price={p['simmer_price']} {p['question']}")
        if p.get("url"):
            print(f"  {p['url']}")


if __name__ == "__main__":
    main()
