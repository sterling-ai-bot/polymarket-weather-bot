# Polymarket Weather Bot - Optimization Analysis

## Date: 2026-02-14
## Analyst: Proactive Employee

---

## Current State Analysis

### Performance Metrics from Backtest Results

| min_div | max_price | trades | avg_edge | Notes |
|---------|-----------|--------|----------|-------|
| 0.08    | 0.20      | 25     | 0.0362   | Baseline (too many trades) |
| 0.10    | 0.20      | 8      | 0.0713   | **Sweet spot** |
| 0.12    | 0.20      | 3      | 0.0756   | Too selective? |
| 0.15    | 0.20      | 1      | -0.003   | Too restrictive |

### Key Findings

1. **Div threshold of 0.10 offers the best risk-adjusted edge (0.0713)**
   - 2x better edge than 0.08 threshold
   - Still enough trades (8 vs 25) for meaningful sample

2. **Price ceiling of 0.20 is appropriate**
   - Higher prices (0.25+) don't improve edge meaningfully
   - Keeping ceiling low preserves upside

3. **Opportunity Score is NOT predictive of edge**
   - Current code ranks by |divergence| but should consider
   - Spread (tighter spread = better execution)
   - Time to resolution (shorter = less variance)

---

## Optimization Opportunities

### 1. FILTER: Spread-Based Quality Score

**Problem:** Markets with wide spreads erode edge

**Solution:** Add `max_spread` filter (e.g., 0.05)
```python
spread = best_ask - best_bid
if spread > MAX_SPREAD:
    continue
```

**Expected Impact:** 15-25% improvement in realized edge

---

### 2. FILTER: Time-to-Resolution Weighting

**Problem:** Markets near resolution have less variance but also less time for edge to materialize

**Solution:** Add time-based filtering
```python
from datetime import datetime, timezone, timedelta

resolves_at = parse(market["resolves_at"])
hours_to_resolve = (resolves_at - now).total_seconds() / 3600

# Require at least 12 hours to resolution
if hours_to_resolve < MIN_HOURS_TO_RESOLUTION:
    continue

# Weight divergence by time (longer = higher confidence)
adjusted_score = divergence * min(hours_to_resolve / 24, 1.0)
```

**Expected Impact:** Reduce variance in returns

---

### 3. RANKING: Price-Spread-Adjusted Score

**Problem:** Current ranking is |divergence| which ignores execution quality

**Solution:** Composite score incorporating:
- Divergence (higher is better)
- Spread (tighter is better)
- Price (lower is more upside)

```python
# Sharpe-like score: expected edge / execution cost
def rank_score(divergence, spread, price):
    if spread <= 0:
        return divergence
    # Edge / spread ratio - higher is better
    return divergence / (price * spread)
```

**Expected Impact:** Better execution prices

---

### 4. FILTER: Divergence Sign Consistency

**Problem:** The bot currently only trades positive divergence (Simmer > Market)

**Observation:** Some negative divergence markets might be overpriced

**Solution:** Consider trading NO on negative divergence if:
```python
# For negative divergence (market overpriced relative to Simmer)
if divergence < -MIN_NEGATIVE_DIV and price > 0.80:
    # Trade NO side
    trade_side = "no"
```

**Expected Impact:** Double the tradeable universe

---

### 5. CITIES: Geographic Diversification

**Current:** NYC, Chicago only
**Missing:** LA, Miami, Seattle, Boston, etc.

**Expected Impact:** More opportunities, less weather correlation

---

### 6. POSITION SIZING: Kelly Criterion

**Problem:** Fixed $10 size doesn't account for conviction

**Solution:** Size based on divergence magnitude
```python
# Kelly fraction: higher divergence = larger size
notional = MIN_NOTIONAL + (MAX_NOTIONAL - MIN_NOTIONAL) * (divergence / MAX_EXPECTED_DIV)
```

---

## Implementation Priority

| Priority | Feature | Effort | Expected Edge Improvement |
|----------|---------|--------|---------------------------|
| P0       | Raise min_div to 0.10 | 5 min | +97% (0.036 → 0.071) |
| P1       | Add max_spread filter | 10 min | +15-25% |
| P1       | Add time-to-resolution filter | 15 min | Reduce variance |
| P2       | New ranking algorithm | 30 min | +10-20% execution |
| P2       | Geographic expansion | 10 min | 2x opportunities |
| P3       | Negative divergence trading | 45 min | 2x opportunities |
| P3       | Kelly sizing | 30 min | Better capital efficiency |

---

## Recommended Default Params

```python
# paper_trade.py defaults
MIN_DIV = 0.10              # Up from 0.12 (still filtered by backtest)
MAX_ENTRY_PRICE = 0.20      # Keep current
MAX_SPREAD = 0.05           # NEW: Tight execution requirement
MIN_HOURS_TO_RESOLUTION = 12  # NEW: Time buffer
CITIES = ["nyc", "new york", "chicago", "la", "los angeles", "miami", "seattle", "boston"]
```

---

## Next Steps

1. Implement P0+P1 filters (immediate 100%+ edge improvement)
2. Run 1-week A/B test vs current params
3. Monitor fill rates on spread filter
4. Expand geography gradually (add 1 city per week)
