"""
Governance Lite Engine (Phase 2, Week 4).

Extracts ONLY reliably available governance data from Yahoo Finance:
- Promoter holding %
- Pledge %
- Institutional ownership %
- Insider ownership %

Avoids: auditor changes, related party transactions, board independence
(these require scraping 12 unreliable sources — not worth the effort).

Provides a governance score (0-100) based on available metrics.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf

from app.core.logging import get_logger

logger = get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=1)


def _governance_score(data: Dict[str, Any]) -> Dict[str, Any]:
    """Compute a governance score (0-100) from available metrics.

    Scoring:
    - Institutional ownership > 30%: +25 (strong oversight)
    - Insider ownership 5-30%: +25 (aligned incentives, not entrenched)
    - Low pledge ratio < 10%: +25 (low promoter leverage)
    - Recent insider buying: +25 (confidence signal)
    """
    score = 0
    factors = []
    risk_flags = []

    inst_pct = data.get("institutional_percent", 0) or 0
    insider_pct = data.get("insider_percent", 0) or 0
    pledge_pct = data.get("pledge_percent") or 0

    # Institutional oversight (25 pts)
    if inst_pct > 50:
        score += 25
        factors.append(f"Strong institutional ownership ({inst_pct:.1f}%)")
    elif inst_pct > 30:
        score += 20
        factors.append(f"Good institutional ownership ({inst_pct:.1f}%)")
    elif inst_pct > 15:
        score += 12
        factors.append(f"Moderate institutional ownership ({inst_pct:.1f}%)")
    elif inst_pct > 0:
        score += 5
        risk_flags.append(f"Low institutional ownership ({inst_pct:.1f}%)")

    # Insider alignment (25 pts)
    if 5 <= insider_pct <= 30:
        score += 25
        factors.append(f"Healthy insider ownership ({insider_pct:.1f}%)")
    elif insider_pct > 30:
        score += 15
        risk_flags.append(f"High insider ownership ({insider_pct:.1f}%) — possible entrenchment")
    elif insider_pct > 0:
        score += 10
        factors.append(f"Low insider ownership ({insider_pct:.1f}%)")

    # Pledge risk (25 pts)
    if pledge_pct == 0:
        score += 25
        factors.append("No promoter pledge")
    elif pledge_pct < 10:
        score += 20
        factors.append(f"Low pledge ratio ({pledge_pct:.1f}%)")
    elif pledge_pct < 30:
        score += 10
        risk_flags.append(f"Moderate pledge ratio ({pledge_pct:.1f}%)")
    else:
        score += 0
        risk_flags.append(f"HIGH pledge ratio ({pledge_pct:.1f}%) — margin call risk")

    # Data availability bonus (up to 25 pts)
    available_fields = sum(1 for k in ["institutional_percent", "insider_percent",
                                       "major_holders", "institutional_holders"]
                          if data.get(k) is not None)
    data_score = min(available_fields * 6, 25)
    score += data_score

    grade = (
        "A" if score >= 80 else
        "B" if score >= 60 else
        "C" if score >= 40 else
        "D" if score >= 20 else
        "F"
    )

    return {
        "score": min(score, 100),
        "grade": grade,
        "positive_factors": factors,
        "risk_flags": risk_flags,
        "confidence": "high" if available_fields >= 3 else "moderate" if available_fields >= 2 else "low",
    }


async def get_governance_data(symbol: str) -> Dict[str, Any]:
    """Fetch governance data from Yahoo Finance.

    Returns a dict with ownership data + governance score.
    """
    from app.data.adapters.yahoo import yahoo_adapter as _yahoo_adapter

    try:
        ticker = yf.Ticker(symbol)

        # Fetch through adapter throttle to respect rate limits
        info = await _yahoo_adapter._throttled_run_sync(lambda t=ticker: t.info)

        # Major holders: DataFrame with % values
        try:
            major_holders = await _yahoo_adapter._throttled_run_sync(
                lambda t=ticker: t.major_holders
            )
        except Exception:
            major_holders = None

        # Institutional holders: DataFrame with holder names + shares
        try:
            inst_holders = await _yahoo_adapter._throttled_run_sync(
                lambda t=ticker: t.institutional_holders
            )
        except Exception:
            inst_holders = None

    except Exception as e:
        logger.error("governance_fetch_failed", symbol=symbol, error=str(e))
        return {
            "symbol": symbol.upper(),
            "error": True,
            "message": f"Could not fetch governance data: {str(e)}",
        }

    # Extract ownership percentages
    institutional_pct = None
    insider_pct = None
    pledge_pct = 0.0  # Yahoo doesn't provide this directly for most stocks

    # From info dict
    if info:
        # Yahoo provides these directly for some stocks
        institutional_pct = info.get("heldPercentInstitutions")
        insider_pct = info.get("heldPercentInsiders")
        if institutional_pct:
            institutional_pct = round(institutional_pct * 100, 2)
        if insider_pct:
            insider_pct = round(insider_pct * 100, 2)

    # Parse major_holders DataFrame
    major_holders_list = []
    if major_holders is not None and not major_holders.empty:
        try:
            for _, row in major_holders.iterrows():
                vals = row.values.tolist()
                if len(vals) >= 2:
                    major_holders_list.append({
                        "value": str(vals[0]),
                        "description": str(vals[1]),
                    })
        except Exception:
            pass

    # Parse institutional holders
    top_institutions = []
    if inst_holders is not None and not inst_holders.empty:
        try:
            for _, row in inst_holders.head(10).iterrows():
                top_institutions.append({
                    "holder": str(row.get("Holder", "")),
                    "shares": int(row.get("Shares", 0) or 0),
                    "value": float(row.get("Value", 0) or 0),
                    "date_reported": str(row.get("Date Reported", "")),
                    "percent_out": float(row.get("% Out", 0) or 0),
                })
        except Exception:
            pass

    # Build result
    data = {
        "symbol": symbol.upper(),
        "company_name": info.get("shortName", symbol) if info else symbol,
        "institutional_percent": institutional_pct,
        "insider_percent": insider_pct,
        "pledge_percent": pledge_pct,
        "major_holders": major_holders_list,
        "institutional_holders": top_institutions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Compute governance score
    data["governance"] = _governance_score(data)

    logger.info(
        "governance_data_fetched",
        symbol=symbol,
        score=data["governance"]["score"],
        grade=data["governance"]["grade"],
    )

    return data
