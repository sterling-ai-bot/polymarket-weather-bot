import os
from typing import Optional, Dict, Any

import requests


class SimmerClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.simmer.markets"):
        self.api_key = api_key or os.environ.get("SIMMER_API_KEY")
        if not self.api_key:
            raise RuntimeError("Missing SIMMER_API_KEY env var")
        self.base_url = base_url.rstrip("/")

    @property
    def headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        r = requests.get(url, headers=self.headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, json: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        r = requests.post(url, headers={**self.headers, "Content-Type": "application/json"}, json=json, timeout=30)
        r.raise_for_status()
        return r.json()

    def me(self):
        return self.get("/api/sdk/agents/me")

    def list_markets(
        self,
        *,
        status: str = "active",
        tags: Optional[str] = None,
        q: Optional[str] = None,
        venue: Optional[str] = None,
        limit: int = 50,
    ) -> Any:
        params: Dict[str, Any] = {"status": status, "limit": limit}
        if tags:
            params["tags"] = tags
        if q:
            params["q"] = q
        if venue:
            params["venue"] = venue
        return self.get("/api/sdk/markets", params=params)

    def briefing(self, since_iso: Optional[str] = None) -> Any:
        params: Dict[str, Any] = {}
        if since_iso:
            params["since"] = since_iso
        return self.get("/api/sdk/briefing", params=params)

    def trades(self, *, limit: int = 50, venue: Optional[str] = None) -> Any:
        params: Dict[str, Any] = {"limit": limit}
        if venue:
            params["venue"] = venue
        return self.get("/api/sdk/trades", params=params)

    def trade(
        self,
        *,
        market_id: str,
        side: str,
        amount: float,
        venue: str = "simmer",
        reasoning: Optional[str] = None,
        source: Optional[str] = None,
        dry_run: bool = False,
    ) -> Any:
        payload: Dict[str, Any] = {
            "market_id": market_id,
            "side": side,
            "amount": amount,
            "venue": venue,
        }
        if dry_run:
            payload["dry_run"] = True
        if reasoning:
            payload["reasoning"] = reasoning
        if source:
            payload["source"] = source
        return self.post("/api/sdk/trade", json=payload)

    def dry_run_trade(
        self,
        *,
        market_id: str,
        side: str,
        amount: float,
        venue: str = "polymarket",
        reasoning: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Any:
        return self.trade(
            market_id=market_id,
            side=side,
            amount=amount,
            venue=venue,
            reasoning=reasoning,
            source=source,
            dry_run=True,
        )
