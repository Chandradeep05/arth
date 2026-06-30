"""
Financial Statement Parser (Phase 2).

Fetches and structures:
- Income Statement (quarterly + annual)
- Balance Sheet (quarterly + annual)
- Cash Flow Statement (quarterly + annual)
- Derived ratios with historical trends
- Financial health scorecard

Uses yfinance's .financials, .quarterly_financials, .balance_sheet,
.quarterly_balance_sheet, .cashflow, .quarterly_cashflow properties.

All DataFrame columns are period end-dates; rows are line items.
We transpose into a list-of-dicts keyed by period for JSON serialisation.
"""

from __future__ import annotations

import asyncio
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf

from app.core.logging import get_logger

logger = get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any) -> Optional[float]:
    """Convert a value to float, returning None for NaN/Inf/missing."""
    if val is None:
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def _df_to_periods(df) -> List[Dict[str, Any]]:
    """Convert a yfinance financial DataFrame into a list of period dicts.

    yfinance returns DataFrames where:
        - columns = period end-dates (Timestamp)
        - rows    = line-item names (str)

    We return::

        [
            {"period": "2024-03-31", "items": {"Total Revenue": 123456, ...}},
            ...
        ]
    """
    if df is None or df.empty:
        return []

    periods: List[Dict[str, Any]] = []
    for col in df.columns:
        period_str = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
        items: Dict[str, Optional[float]] = {}
        for row_label, value in df[col].items():
            items[str(row_label)] = _safe_float(value)
        periods.append({"period": period_str, "items": items})

    return periods


def _trend(current: Optional[float], previous: Optional[float]) -> Dict[str, Any]:
    """Build a trend dict comparing current vs previous period value."""
    if current is None:
        return {"value": None, "previous": previous, "change": None, "direction": "unknown"}
    if previous is None or previous == 0:
        return {"value": current, "previous": previous, "change": None, "direction": "unknown"}
    change = round(current - previous, 4)
    pct = round(change / abs(previous), 4)
    direction = "up" if change > 0 else "down" if change < 0 else "flat"
    return {
        "value": round(current, 4),
        "previous": round(previous, 4),
        "change": change,
        "change_pct": pct,
        "direction": direction,
    }


def _safe_divide(
    numerator: Optional[float], denominator: Optional[float]
) -> Optional[float]:
    """Safe division returning None when inputs are missing or zero-denominator."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, 4)


# ---------------------------------------------------------------------------
# Statement Parser
# ---------------------------------------------------------------------------

class StatementParser:
    """Fetches, parses, and scores financial statements from Yahoo Finance."""

    async def get_statements(self, symbol: str) -> Dict[str, Any]:
        """Fetch all three financial statements (annual + quarterly).

        Returns
        -------
        dict
            Structured statements keyed by type, each containing annual
            and quarterly period lists.
        """
        from app.data.adapters.yahoo import yahoo_adapter as _yahoo_adapter

        try:
            ticker = yf.Ticker(symbol)

            # Fetch ALL financial DataFrames in a single executor call.
            # yfinance caches data internally after the first property access,
            # so doing all 6 accesses in the same thread means only ~1 HTTP call.
            # (6 separate executor calls would each trigger separate fetches,
            # totaling 15-30s and timing out on Render free tier.)
            def _fetch_all_statements(t):
                """Fetch all statement DataFrames in one thread."""
                def _try_df(*attrs):
                    for attr in attrs:
                        try:
                            df = getattr(t, attr, None)
                            if df is not None and not df.empty:
                                return df
                        except Exception:
                            continue
                    return None

                return {
                    "financials": _try_df("income_stmt", "financials"),
                    "quarterly_financials": _try_df("quarterly_income_stmt", "quarterly_financials"),
                    "balance_sheet": _try_df("balance_sheet", "balancesheet"),
                    "quarterly_balance_sheet": _try_df("quarterly_balance_sheet", "quarterly_balancesheet"),
                    "cashflow": _try_df("cash_flow", "cashflow"),
                    "quarterly_cashflow": _try_df("quarterly_cash_flow", "quarterly_cashflow"),
                }

            raw = await _yahoo_adapter._throttled_run_sync(
                lambda t=ticker: _fetch_all_statements(t)
            )

            income_annual = _df_to_periods(raw["financials"])
            income_quarterly = _df_to_periods(raw["quarterly_financials"])
            bs_annual = _df_to_periods(raw["balance_sheet"])
            bs_quarterly = _df_to_periods(raw["quarterly_balance_sheet"])
            cf_annual = _df_to_periods(raw["cashflow"])
            cf_quarterly = _df_to_periods(raw["quarterly_cashflow"])

            return {
                "symbol": symbol.upper(),
                "income_statement": {
                    "annual": income_annual,
                    "quarterly": income_quarterly,
                },
                "balance_sheet": {
                    "annual": bs_annual,
                    "quarterly": bs_quarterly,
                },
                "cash_flow": {
                    "annual": cf_annual,
                    "quarterly": cf_quarterly,
                },
                "periods_available": {
                    "annual": max(
                        len(income_annual), len(bs_annual), len(cf_annual)
                    ),
                    "quarterly": max(
                        len(income_quarterly),
                        len(bs_quarterly),
                        len(cf_quarterly),
                    ),
                },
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(
                "statement_fetch_failed", symbol=symbol, error=str(e)
            )
            return {
                "symbol": symbol.upper(),
                "income_statement": {"annual": [], "quarterly": []},
                "balance_sheet": {"annual": [], "quarterly": []},
                "cash_flow": {"annual": [], "quarterly": []},
                "periods_available": {"annual": 0, "quarterly": 0},
                "error": str(e),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

    # ------------------------------------------------------------------
    # Ratios
    # ------------------------------------------------------------------

    async def get_ratios(self, symbol: str) -> Dict[str, Any]:
        """Compute financial ratios with YoY trends.

        Ratios computed:
            ROE, ROA, current ratio, debt-to-equity, profit margin,
            operating margin, revenue growth, EPS growth.

        Each ratio includes the current value, previous-period value,
        absolute change, and directional label.
        """
        statements = await self.get_statements(symbol)

        income = statements["income_statement"]["annual"]
        bs = statements["balance_sheet"]["annual"]
        cf = statements["cash_flow"]["annual"]

        ratios: Dict[str, Any] = {}

        # --- helpers to pull items from the most recent two periods ---
        def _item(periods: List[Dict], key: str, idx: int = 0) -> Optional[float]:
            """Get a line-item value from period *idx* (0 = most recent)."""
            if idx >= len(periods):
                return None
            return periods[idx]["items"].get(key)

        def _item_any(
            periods: List[Dict], keys: List[str], idx: int = 0
        ) -> Optional[float]:
            """Try multiple key names (yfinance naming is inconsistent)."""
            for k in keys:
                val = _item(periods, k, idx)
                if val is not None:
                    return val
            return None

        # Revenue
        rev_curr = _item_any(income, ["Total Revenue", "Operating Revenue"], 0)
        rev_prev = _item_any(income, ["Total Revenue", "Operating Revenue"], 1)
        ratios["revenue_growth"] = _trend(
            _safe_divide((rev_curr or 0) - (rev_prev or 0), rev_prev)
            if rev_curr is not None and rev_prev is not None
            else None,
            None,
        )
        # Override with simpler trend
        if rev_curr is not None and rev_prev is not None and rev_prev != 0:
            growth = round((rev_curr - rev_prev) / abs(rev_prev), 4)
            prev_rev2 = _item_any(income, ["Total Revenue", "Operating Revenue"], 2)
            prev_growth = None
            if rev_prev and prev_rev2 and prev_rev2 != 0:
                prev_growth = round((rev_prev - prev_rev2) / abs(prev_rev2), 4)
            ratios["revenue_growth"] = _trend(growth, prev_growth)

        # Net Income
        ni_curr = _item_any(income, ["Net Income", "Net Income Common Stockholders"], 0)
        ni_prev = _item_any(income, ["Net Income", "Net Income Common Stockholders"], 1)

        # Profit Margin
        pm_curr = _safe_divide(ni_curr, rev_curr)
        pm_prev = _safe_divide(ni_prev, rev_prev)
        ratios["profit_margin"] = _trend(pm_curr, pm_prev)

        # Operating Margin
        op_inc_curr = _item_any(income, ["Operating Income", "EBIT"], 0)
        op_inc_prev = _item_any(income, ["Operating Income", "EBIT"], 1)
        ratios["operating_margin"] = _trend(
            _safe_divide(op_inc_curr, rev_curr),
            _safe_divide(op_inc_prev, rev_prev),
        )

        # ROE = Net Income / Total Stockholder Equity
        equity_curr = _item_any(
            bs,
            ["Total Stockholders Equity", "Stockholders Equity", "Common Stock Equity"],
            0,
        )
        equity_prev = _item_any(
            bs,
            ["Total Stockholders Equity", "Stockholders Equity", "Common Stock Equity"],
            1,
        )
        ratios["roe"] = _trend(
            _safe_divide(ni_curr, equity_curr),
            _safe_divide(ni_prev, equity_prev),
        )

        # ROA = Net Income / Total Assets
        assets_curr = _item_any(bs, ["Total Assets"], 0)
        assets_prev = _item_any(bs, ["Total Assets"], 1)
        ratios["roa"] = _trend(
            _safe_divide(ni_curr, assets_curr),
            _safe_divide(ni_prev, assets_prev),
        )

        # Current Ratio = Current Assets / Current Liabilities
        ca_curr = _item_any(bs, ["Current Assets", "Total Current Assets"], 0)
        cl_curr = _item_any(
            bs, ["Current Liabilities", "Total Current Liabilities"], 0
        )
        ca_prev = _item_any(bs, ["Current Assets", "Total Current Assets"], 1)
        cl_prev = _item_any(
            bs, ["Current Liabilities", "Total Current Liabilities"], 1
        )
        ratios["current_ratio"] = _trend(
            _safe_divide(ca_curr, cl_curr),
            _safe_divide(ca_prev, cl_prev),
        )

        # Debt-to-Equity
        debt_curr = _item_any(
            bs, ["Total Debt", "Long Term Debt", "Total Liabilities Net Minority Interest"], 0
        )
        debt_prev = _item_any(
            bs, ["Total Debt", "Long Term Debt", "Total Liabilities Net Minority Interest"], 1
        )
        ratios["debt_to_equity"] = _trend(
            _safe_divide(debt_curr, equity_curr),
            _safe_divide(debt_prev, equity_prev),
        )

        # Free Cash Flow (from cash flow statement)
        ocf_curr = _item_any(
            cf, ["Operating Cash Flow", "Total Cash From Operating Activities"], 0
        )
        capex_curr = _item_any(
            cf, ["Capital Expenditure", "Capital Expenditures"], 0
        )
        ocf_prev = _item_any(
            cf, ["Operating Cash Flow", "Total Cash From Operating Activities"], 1
        )
        capex_prev = _item_any(
            cf, ["Capital Expenditure", "Capital Expenditures"], 1
        )
        fcf_curr = (
            (ocf_curr or 0) - abs(capex_curr or 0)
            if ocf_curr is not None
            else None
        )
        fcf_prev = (
            (ocf_prev or 0) - abs(capex_prev or 0)
            if ocf_prev is not None
            else None
        )
        ratios["free_cash_flow"] = _trend(
            _safe_float(fcf_curr), _safe_float(fcf_prev)
        )

        return {
            "symbol": symbol.upper(),
            "ratios": ratios,
            "periods_compared": {
                "current": income[0]["period"] if income else None,
                "previous": income[1]["period"] if len(income) > 1 else None,
            },
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": (
                "⚠ Ratios are derived from reported financials and may not "
                "reflect adjustments. This is NOT financial advice."
            ),
        }

    # ------------------------------------------------------------------
    # Health Score
    # ------------------------------------------------------------------

    async def get_health_score(self, symbol: str) -> Dict[str, Any]:
        """Compute a financial health scorecard (0-100).

        Categories (each 0-25 points):
            1. Profitability — profit margin, ROE, ROA
            2. Solvency — D/E ratio, current ratio
            3. Efficiency — operating margin, asset turnover
            4. Growth — revenue growth, net income growth

        Returns a total score and per-category breakdown.
        """
        ratios_data = await self.get_ratios(symbol)
        ratios = ratios_data.get("ratios", {})

        profitability = self._score_profitability(ratios)
        solvency = self._score_solvency(ratios)
        efficiency = self._score_efficiency(ratios)
        growth = self._score_growth(ratios)

        total = (
            profitability["score"]
            + solvency["score"]
            + efficiency["score"]
            + growth["score"]
        )

        return {
            "symbol": symbol.upper(),
            "total_score": round(total, 1),
            "label": self._health_label(total),
            "breakdown": {
                "profitability": profitability,
                "solvency": solvency,
                "efficiency": efficiency,
                "growth": growth,
            },
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": (
                "⚠ Health scores are heuristic assessments based on reported "
                "financials. They are NOT investment recommendations."
            ),
        }

    # ---- category scorers (each returns {"score": 0-25, "factors": [...]}) ----

    @staticmethod
    def _val(trend_dict: Optional[Dict]) -> Optional[float]:
        """Extract the current value from a trend dict."""
        if trend_dict is None:
            return None
        return trend_dict.get("value")

    def _score_profitability(self, ratios: Dict) -> Dict[str, Any]:
        """Score profitability (0-25)."""
        score = 0.0
        factors: List[str] = []

        pm = self._val(ratios.get("profit_margin"))
        if pm is not None:
            if pm > 0.20:
                score += 10
                factors.append(f"Excellent profit margin ({pm*100:.1f}%)")
            elif pm > 0.10:
                score += 7
                factors.append(f"Good profit margin ({pm*100:.1f}%)")
            elif pm > 0:
                score += 3
                factors.append(f"Thin profit margin ({pm*100:.1f}%)")
            else:
                factors.append(f"Negative profit margin ({pm*100:.1f}%)")
        else:
            score += 2  # partial credit for missing data
            factors.append("Profit margin data unavailable")

        roe = self._val(ratios.get("roe"))
        if roe is not None:
            if roe > 0.20:
                score += 10
                factors.append(f"Strong ROE ({roe*100:.1f}%)")
            elif roe > 0.10:
                score += 7
                factors.append(f"Adequate ROE ({roe*100:.1f}%)")
            elif roe > 0:
                score += 3
                factors.append(f"Low ROE ({roe*100:.1f}%)")
            else:
                factors.append(f"Negative ROE ({roe*100:.1f}%)")
        else:
            score += 2
            factors.append("ROE data unavailable")

        roa = self._val(ratios.get("roa"))
        if roa is not None:
            if roa > 0.10:
                score += 5
                factors.append(f"Strong ROA ({roa*100:.1f}%)")
            elif roa > 0.03:
                score += 3
                factors.append(f"Adequate ROA ({roa*100:.1f}%)")
            elif roa > 0:
                score += 1
                factors.append(f"Low ROA ({roa*100:.1f}%)")
            else:
                factors.append(f"Negative ROA ({roa*100:.1f}%)")
        else:
            score += 1
            factors.append("ROA data unavailable")

        return {"score": min(round(score, 1), 25), "factors": factors}

    def _score_solvency(self, ratios: Dict) -> Dict[str, Any]:
        """Score solvency (0-25)."""
        score = 0.0
        factors: List[str] = []

        de = self._val(ratios.get("debt_to_equity"))
        if de is not None:
            if de < 0.5:
                score += 15
                factors.append(f"Low leverage (D/E: {de:.2f})")
            elif de < 1.5:
                score += 10
                factors.append(f"Moderate leverage (D/E: {de:.2f})")
            elif de < 3.0:
                score += 5
                factors.append(f"High leverage (D/E: {de:.2f})")
            else:
                score += 1
                factors.append(f"Very high leverage (D/E: {de:.2f})")
        else:
            score += 5
            factors.append("Debt-to-equity data unavailable")

        cr = self._val(ratios.get("current_ratio"))
        if cr is not None:
            if cr > 2.0:
                score += 10
                factors.append(f"Strong liquidity (CR: {cr:.2f})")
            elif cr > 1.0:
                score += 7
                factors.append(f"Adequate liquidity (CR: {cr:.2f})")
            elif cr > 0.5:
                score += 3
                factors.append(f"Tight liquidity (CR: {cr:.2f})")
            else:
                factors.append(f"Critical liquidity (CR: {cr:.2f})")
        else:
            score += 3
            factors.append("Current ratio data unavailable")

        return {"score": min(round(score, 1), 25), "factors": factors}

    def _score_efficiency(self, ratios: Dict) -> Dict[str, Any]:
        """Score efficiency (0-25)."""
        score = 0.0
        factors: List[str] = []

        om = self._val(ratios.get("operating_margin"))
        if om is not None:
            if om > 0.25:
                score += 15
                factors.append(f"Excellent operating margin ({om*100:.1f}%)")
            elif om > 0.12:
                score += 10
                factors.append(f"Good operating margin ({om*100:.1f}%)")
            elif om > 0:
                score += 5
                factors.append(f"Thin operating margin ({om*100:.1f}%)")
            else:
                factors.append(f"Negative operating margin ({om*100:.1f}%)")
        else:
            score += 5
            factors.append("Operating margin data unavailable")

        # FCF positivity
        fcf = self._val(ratios.get("free_cash_flow"))
        if fcf is not None:
            if fcf > 0:
                score += 10
                factors.append("Positive free cash flow")
            else:
                score += 2
                factors.append("Negative free cash flow")
        else:
            score += 3
            factors.append("Free cash flow data unavailable")

        return {"score": min(round(score, 1), 25), "factors": factors}

    def _score_growth(self, ratios: Dict) -> Dict[str, Any]:
        """Score growth (0-25)."""
        score = 0.0
        factors: List[str] = []

        rg = self._val(ratios.get("revenue_growth"))
        if rg is not None:
            if rg > 0.20:
                score += 15
                factors.append(f"Strong revenue growth ({rg*100:.1f}%)")
            elif rg > 0.05:
                score += 10
                factors.append(f"Moderate revenue growth ({rg*100:.1f}%)")
            elif rg > 0:
                score += 5
                factors.append(f"Slow revenue growth ({rg*100:.1f}%)")
            else:
                score += 1
                factors.append(f"Revenue declining ({rg*100:.1f}%)")
        else:
            score += 5
            factors.append("Revenue growth data unavailable")

        # Net-income trend direction
        pm_trend = ratios.get("profit_margin", {})
        pm_dir = pm_trend.get("direction") if isinstance(pm_trend, dict) else None
        if pm_dir == "up":
            score += 10
            factors.append("Profit margin trending up")
        elif pm_dir == "down":
            score += 3
            factors.append("Profit margin trending down")
        elif pm_dir == "flat":
            score += 5
            factors.append("Profit margin stable")
        else:
            score += 3
            factors.append("Profit margin trend unavailable")

        return {"score": min(round(score, 1), 25), "factors": factors}

    @staticmethod
    def _health_label(score: float) -> str:
        """Human-readable label for total health score."""
        if score >= 80:
            return "Excellent"
        if score >= 60:
            return "Good"
        if score >= 40:
            return "Fair"
        if score >= 20:
            return "Weak"
        return "Critical"
