"""Minimal Polymarket CLOB market-data client (public endpoints).

We only use this for *market data* (bid/ask/depth), not trading.
Docs:
- https://docs.polymarket.com/api-reference/clob-subset-openapi.yaml

Endpoints:
- POST /prices  [{token_id, side: BUY|SELL}]
- POST /books   [{token_id}]

Gotchas:
- /book arrays may not be sorted; always compute best bid/ask yourself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests


@dataclass
class TopOfBook:
    best_bid: Optional[float]
    best_ask: Optional[float]


class PolymarketCLOB:
    def __init__(self, base_url: str = "https://clob.polymarket.com"):
        self.base_url = base_url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "pm-weather-scanner/0.1", "Accept": "application/json"})

    def post(self, path: str, json: Any) -> Any:
        url = f"{self.base_url}{path}"
        r = self.s.post(url, json=json, timeout=30)
        r.raise_for_status()
        return r.json()

    def prices(self, token_ids: List[str]) -> Dict[str, Dict[str, str]]:
        body = []
        for tid in token_ids:
            body.append({"token_id": str(tid), "side": "BUY"})  # best bid
            body.append({"token_id": str(tid), "side": "SELL"})  # best ask
        out: Dict[str, Dict[str, str]] = {}
        for i in range(0, len(body), 500):
            chunk = body[i : i + 500]
            out.update(self.post("/prices", json=chunk))
        return out

    def books(self, token_ids: List[str]) -> List[Dict[str, Any]]:
        body = [{"token_id": str(t)} for t in token_ids]
        out: List[Dict[str, Any]] = []
        for i in range(0, len(body), 500):
            chunk = body[i : i + 500]
            res = self.post("/books", json=chunk)
            if isinstance(res, list):
                out.extend(res)
            else:
                # defensive
                out.append(res)
        return out


def _to_float(x) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def best_bid_ask_from_book(book: Dict[str, Any]) -> TopOfBook:
    bids = [_to_float(b.get("price")) for b in (book.get("bids") or [])]
    asks = [_to_float(a.get("price")) for a in (book.get("asks") or [])]
    bids = [b for b in bids if b is not None]
    asks = [a for a in asks if a is not None]
    return TopOfBook(best_bid=max(bids) if bids else None, best_ask=min(asks) if asks else None)


def walk_cost_from_asks(book: Dict[str, Any], notional_usd: float) -> Optional[Tuple[float, float]]:
    """Approximate average price + shares when buying with USD notional.

    Uses asks levels; assumes size is in shares.
    Returns (avg_price, shares).
    """
    asks = book.get("asks") or []
    levels = []
    for a in asks:
        p = _to_float(a.get("price"))
        s = _to_float(a.get("size"))
        if p is None or s is None:
            continue
        levels.append((p, s))
    if not levels:
        return None
    # best ask first
    levels.sort(key=lambda x: x[0])

    remaining = float(notional_usd)
    got_shares = 0.0
    spent = 0.0
    for price, size in levels:
        if remaining <= 0:
            break
        max_cost = price * size
        take_cost = min(max_cost, remaining)
        take_shares = take_cost / price if price > 0 else 0.0
        remaining -= take_cost
        spent += take_cost
        got_shares += take_shares

    if got_shares <= 0 or spent <= 0:
        return None
    return (spent / got_shares, got_shares)
