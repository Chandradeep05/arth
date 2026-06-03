"""
Risk Intelligence Engine (Module 05 — Phase 1 Basic).

Computes composite risk scores across dimensions:
- Volatility risk (30-day standard deviation)
- Liquidity risk (average volume analysis)
- Financial health risk (debt-to-equity, current ratio)

Each dimension scored 0-100, composite is weighted average.
All outputs include confidence scores and contributing factors.

D/E Ratio Normalization:
    yfinance ALWAYS returns debtToEquity as a percentage
    (e.g., 36.65 means D/E ratio of 0.3665x).
    We always divide by 100 to get the true ratio.

    Different sectors have fundamentally different capital structures:
    - Banks/NBFCs: D/E of 4-10x is normal (they lend deposits)
    - Utilities/Power: D/E of 2-5x is normal (capital-intensive, regulated)
    - IT/FMCG/Pharma: D/E above 1x is a yellow flag

    We use sector-aware thresholds so HDFCBANK at D/E 7x
    doesn't get flagged as "Critical Risk" when that's standard
    for its business model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.logging import get_logger
from app.data.adapters.yahoo import YahooFinanceAdapter

logger = get_logger(__name__)

# ── Sector-Aware D/E Thresholds ──
# Each tuple: (low_max, moderate_max, high_max)
# Anything above high_max → "Very high leverage"
_DE_THRESHOLDS: Dict[str, tuple] = {
    # Financial sector: banks make money by leveraging deposits
    "financial_services": (4.0, 8.0, 12.0),
    "financials":         (4.0, 8.0, 12.0),
    "banks":              (5.0, 10.0, 15.0),
    # Utilities: capital-intensive, regulated, stable cash flows
    "utilities":          (2.0, 4.0, 6.0),
    # Real estate: asset-heavy, mortgage-backed
    "real_estate":        (2.0, 4.0, 7.0),
    # Energy / industrials: moderate leverage is normal
    "energy":             (1.0, 2.5, 4.0),
    "industrials":        (1.0, 2.0, 3.5),
    # Default for tech, FMCG, pharma, consumer — low leverage expected
    "_default":           (0.5, 1.5, 3.0),
}


def _get_de_thresholds(sector: Optional[str]) -> tuple:
    """Get sector-appropriate D/E thresholds."""
    if not sector:
        return _DE_THRESHOLDS["_default"]
    key = sector.lower().replace(" ", "_")
    # Check exact match first, then partial matches
    if key in _DE_THRESHOLDS:
        return _DE_THRESHOLDS[key]
    # Partial keyword matching for yfinance sector strings
    for keyword, thresholds in _DE_THRESHOLDS.items():
        if keyword != "_default" and keyword in key:
            return thresholds
    return _DE_THRESHOLDS["_default"]


class RiskEngine:
    """Computes multi-dimensional risk scores for stocks."""

    def __init__(self):
        self._yahoo = YahooFinanceAdapter()

    async def compute_risk(self, symbol: str) -> Dict[str, Any]:
        """Compute composite risk score for a symbol."""
        dimensions = []
        factors_all: List[str] = []

        # Fetch data
        company = await self._yahoo.get_company_info(symbol)
        ohlcv = await self._yahoo.get_ohlcv(symbol, period="3mo", interval="1d")

        metrics = company.get("metrics", {}) if company else {}
        sector = company.get("sector") if company else None

        # ── Volatility Risk ──
        vol_score, vol_factors = self._compute_volatility_risk(ohlcv)
        dimensions.append({
            "dimension": "volatility",
            "score": vol_score,
            "label": self._risk_label(vol_score),
            "factors": vol_factors,
        })
        factors_all.extend(vol_factors)

        # ── Liquidity Risk ──
        liq_score, liq_factors = self._compute_liquidity_risk(ohlcv)
        dimensions.append({
            "dimension": "liquidity",
            "score": liq_score,
            "label": self._risk_label(liq_score),
            "factors": liq_factors,
        })
        factors_all.extend(liq_factors)

        # ── Financial Health Risk (sector-aware) ──
        fin_score, fin_factors = self._compute_financial_risk(metrics, sector)
        dimensions.append({
            "dimension": "financial_health",
            "score": fin_score,
            "label": self._risk_label(fin_score),
            "factors": fin_factors,
        })
        factors_all.extend(fin_factors)

        # ── Composite Score (weighted average) ──
        weights = {"volatility": 0.35, "liquidity": 0.25, "financial_health": 0.40}
        composite = sum(
            d["score"] * weights.get(d["dimension"], 0.33)
            for d in dimensions
        )

        return {
            "symbol": symbol.upper(),
            "composite_score": round(composite, 1),
            "composite_label": self._risk_label(composite),
            "dimensions": dimensions,
            "sector": sector,
            "confidence": 60.0,  # Base confidence for Phase 1
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": (
                "⚠ Risk scores are probabilistic assessments, not guarantees. "
                "Past risk patterns may not predict future outcomes."
            ),
        }

    def _compute_volatility_risk(
        self, ohlcv: Optional[List[Dict[str, Any]]]
    ) -> tuple[float, List[str]]:
        """Volatility risk from 30-day price standard deviation."""
        factors = []

        if not ohlcv or len(ohlcv) < 20:
            return 50.0, ["Insufficient data for volatility calculation"]

        closes = [bar["close"] for bar in ohlcv[-30:]]
        returns = np.diff(np.log(closes))

        daily_vol = float(np.std(returns))
        annualized_vol = daily_vol * np.sqrt(252) * 100

        # Score: 0-10% vol = low risk, >40% = high risk
        if annualized_vol < 15:
            score = 20.0
            factors.append(f"Low volatility ({annualized_vol:.1f}% annualized)")
        elif annualized_vol < 25:
            score = 40.0
            factors.append(f"Moderate volatility ({annualized_vol:.1f}% annualized)")
        elif annualized_vol < 35:
            score = 65.0
            factors.append(f"High volatility ({annualized_vol:.1f}% annualized)")
        else:
            score = 85.0
            factors.append(f"Very high volatility ({annualized_vol:.1f}% annualized)")

        # Check for large recent moves
        max_daily = float(np.max(np.abs(returns))) * 100
        if max_daily > 5:
            score = min(score + 10, 100)
            factors.append(f"Large single-day move: {max_daily:.1f}%")

        return round(score, 1), factors

    def _compute_liquidity_risk(
        self, ohlcv: Optional[List[Dict[str, Any]]]
    ) -> tuple[float, List[str]]:
        """Liquidity risk from average trading volume."""
        factors = []

        if not ohlcv or len(ohlcv) < 10:
            return 50.0, ["Insufficient data for liquidity analysis"]

        volumes = [bar["volume"] for bar in ohlcv[-20:]]
        avg_vol = float(np.mean(volumes))

        # Higher volume = lower liquidity risk
        if avg_vol > 10_000_000:
            score = 10.0
            factors.append(f"Very high liquidity (avg vol: {avg_vol/1e6:.1f}M)")
        elif avg_vol > 1_000_000:
            score = 25.0
            factors.append(f"Good liquidity (avg vol: {avg_vol/1e6:.1f}M)")
        elif avg_vol > 100_000:
            score = 50.0
            factors.append(f"Moderate liquidity (avg vol: {avg_vol/1e3:.0f}K)")
        else:
            score = 80.0
            factors.append(f"Low liquidity (avg vol: {avg_vol/1e3:.0f}K)")

        # Volume trend
        recent_vol = float(np.mean(volumes[-5:]))
        if avg_vol > 0 and recent_vol / avg_vol < 0.5:
            score = min(score + 15, 100)
            factors.append("Volume declining — potential liquidity concern")

        return round(score, 1), factors

    def _compute_financial_risk(
        self, metrics: Dict[str, Any], sector: Optional[str] = None
    ) -> tuple[float, List[str]]:
        """
        Financial health risk from fundamentals.

        Uses sector-aware D/E thresholds because capital structure
        norms differ wildly by industry:
        - HDFCBANK (Financial Services): D/E ~7x is business-as-usual
        - POWERGRID (Utilities): D/E ~3x is expected for regulated utility
        - INFY (Technology): D/E ~0.1x is normal for asset-light IT
        """
        factors = []
        score = 50.0  # Default medium risk

        # Debt-to-Equity — sector-aware scoring
        de = metrics.get("debt_to_equity")
        if de is not None:
            # yfinance ALWAYS returns debtToEquity as percentage.
            # e.g., Reliance → 36.65 (means 0.3665x), HDFCBANK → 700+ (means 7x)
            # We unconditionally divide by 100.
            de_ratio = de / 100.0

            # Get sector-appropriate thresholds
            low_max, mod_max, high_max = _get_de_thresholds(sector)
            sector_label = f" [sector: {sector}]" if sector else ""

            if de_ratio < low_max:
                score -= 15
                factors.append(
                    f"Low leverage (D/E: {de_ratio:.2f}, threshold <{low_max}){sector_label}"
                )
            elif de_ratio < mod_max:
                factors.append(
                    f"Moderate leverage (D/E: {de_ratio:.2f}, normal for sector){sector_label}"
                )
            elif de_ratio < high_max:
                score += 15
                factors.append(
                    f"High leverage (D/E: {de_ratio:.2f}, above sector norm){sector_label}"
                )
            else:
                score += 25
                factors.append(
                    f"Very high leverage (D/E: {de_ratio:.2f}, "
                    f"sector threshold: {high_max}x) — debt concern{sector_label}"
                )

        # Current Ratio
        cr = metrics.get("current_ratio")
        if cr is not None:
            if cr > 2.0:
                score -= 10
                factors.append(f"Strong short-term liquidity (CR: {cr:.2f})")
            elif cr > 1.0:
                factors.append(f"Adequate short-term liquidity (CR: {cr:.2f})")
            else:
                score += 20
                factors.append(f"Weak short-term liquidity (CR: {cr:.2f}) — risk flag")

        # Profit Margin
        pm = metrics.get("profit_margin")
        if pm is not None:
            if pm > 0.15:
                score -= 10
                factors.append(f"Strong profitability (margin: {pm*100:.1f}%)")
            elif pm > 0:
                factors.append(f"Positive but thin margin ({pm*100:.1f}%)")
            else:
                score += 20
                factors.append(f"Negative margin ({pm*100:.1f}%) — profitability concern")

        # PE Ratio
        pe = metrics.get("pe_ratio")
        if pe is not None:
            if pe < 0:
                score += 15
                factors.append(f"Negative P/E ({pe:.1f}) — company not profitable")
            elif pe > 50:
                score += 10
                factors.append(f"Very high P/E ({pe:.1f}) — may be overvalued")

        if not factors:
            factors.append("Limited fundamental data available")

        return round(max(0, min(100, score)), 1), factors

    @staticmethod
    def _risk_label(score: float) -> str:
        if score < 25:
            return "Low Risk"
        elif score < 50:
            return "Medium Risk"
        elif score < 75:
            return "High Risk"
        return "Critical Risk"
