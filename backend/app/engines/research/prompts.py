"""
AI Research Engine prompts.

All prompts enforce ARTH's core principles:
- Probabilistic language only (never "will", "guaranteed")
- All numbers from provided data, never from LLM memory
- Mandatory risk disclaimer
- Confidence scoring
- Citation of data sources
"""

from __future__ import annotations

RESEARCH_SYSTEM_PROMPT = """You are ARTH's AI Financial Research Analyst. You generate institutional-grade company research reports.

STRICT RULES:
1. Use ONLY the financial data provided in the user message. NEVER use numbers from your training data.
2. Use probabilistic language: "suggests", "likely", "approximately", "based on available data"
3. NEVER say: "will go up", "guaranteed", "certain to", "buy signal", "sell signal"
4. Include confidence levels for all assessments (low/moderate/high)
5. Every numerical claim must reference the data source
6. End with a risk disclaimer

REPORT STRUCTURE:
## Company Overview
Brief description of the company, its sector, and market position.

## Key Financial Metrics
Present the provided metrics with context (how they compare to sector norms).

## Bull Case (Factors Supporting Growth)
3-5 factors that suggest positive outlook, with data backing each point.
Assign a confidence level to the overall bull case.

## Bear Case (Risk Factors & Concerns)
3-5 factors that suggest caution, with data backing each point.
Assign a confidence level to the overall bear case.

## Technical Summary
Brief assessment of current technical indicators if provided.

## Risk Assessment
Overall risk level with contributing factors.

---
⚠ DISCLAIMER: This is AI-generated analysis for informational purposes only. This is NOT financial advice. Past performance does not indicate future results. Always consult a qualified financial advisor before making investment decisions.
"""

QUICK_SUMMARY_PROMPT = """You are ARTH's AI analyst. Generate a brief 3-4 sentence summary of this company based on the provided data.

RULES:
- Use ONLY the provided data
- Probabilistic language only
- Include the key risk/opportunity in one sentence
- End with confidence level

Data: {data}
"""


def build_research_prompt(
    symbol: str,
    company_info: dict,
    metrics: dict,
    indicators: dict | None = None,
) -> str:
    """Build the research prompt with real data injected."""

    data_section = f"""
COMPANY DATA FOR ANALYSIS:
Symbol: {symbol}
Company Name: {company_info.get('name', 'Unknown')}
Sector: {company_info.get('sector', 'N/A')}
Industry: {company_info.get('industry', 'N/A')}
Exchange: {company_info.get('exchange', 'N/A')}

FINANCIAL METRICS (from Yahoo Finance, current):
- Market Cap: {_fmt_large_num(metrics.get('market_cap'))}
- P/E Ratio: {_fmt(metrics.get('pe_ratio'))}
- EPS: {_fmt(metrics.get('eps'))}
- Revenue: {_fmt_large_num(metrics.get('revenue'))}
- Revenue Growth: {_fmt_pct(metrics.get('revenue_growth'))}
- Profit Margin: {_fmt_pct(metrics.get('profit_margin'))}
- Debt-to-Equity: {_fmt(metrics.get('debt_to_equity'))}
- Dividend Yield: {_fmt_pct(metrics.get('dividend_yield'))}
- Book Value: {_fmt(metrics.get('book_value'))}
- ROE: {_fmt_pct(metrics.get('roe'))}
- ROA: {_fmt_pct(metrics.get('roa'))}
- Current Ratio: {_fmt(metrics.get('current_ratio'))}

DATA SOURCE: Yahoo Finance (all data is delayed ~15 seconds)
"""

    if indicators:
        data_section += f"""
TECHNICAL INDICATORS (latest):
- RSI (14): {_fmt(indicators.get('rsi_14'))} — Signal: {indicators.get('rsi_signal', 'N/A')}
- MACD Signal: {indicators.get('macd_signal_type', 'N/A')}
- Bollinger Band Position: {indicators.get('bb_position', 'N/A')}
- VWAP: {_fmt(indicators.get('vwap'))}
- SMA 20: {_fmt(indicators.get('sma_20'))}
- SMA 50: {_fmt(indicators.get('sma_50'))}
"""

    data_section += """
Generate a comprehensive research report based ONLY on the data above.
"""

    return data_section


def build_quick_summary_prompt(symbol: str, company_info: dict, metrics: dict) -> str:
    """Build a quick summary prompt."""
    data = (
        f"Symbol: {symbol}, "
        f"Name: {company_info.get('name', 'Unknown')}, "
        f"Sector: {company_info.get('sector', 'N/A')}, "
        f"Market Cap: {_fmt_large_num(metrics.get('market_cap'))}, "
        f"P/E: {_fmt(metrics.get('pe_ratio'))}, "
        f"EPS: {_fmt(metrics.get('eps'))}, "
        f"Revenue Growth: {_fmt_pct(metrics.get('revenue_growth'))}, "
        f"Profit Margin: {_fmt_pct(metrics.get('profit_margin'))}, "
        f"D/E: {_fmt(metrics.get('debt_to_equity'))}"
    )
    return QUICK_SUMMARY_PROMPT.format(data=data)


# ── Formatting Helpers ──

def _fmt(val) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{val:.2f}"
    return str(val)


def _fmt_pct(val) -> str:
    if val is None:
        return "N/A"
    return f"{val * 100:.1f}%" if isinstance(val, float) and abs(val) < 1 else f"{val:.1f}%"


def _fmt_large_num(val) -> str:
    if val is None:
        return "N/A"
    val = float(val)
    if val >= 1e12:
        return f"₹{val/1e12:.2f}T"
    if val >= 1e9:
        return f"₹{val/1e9:.2f}B"
    if val >= 1e7:
        return f"₹{val/1e7:.2f}Cr"
    if val >= 1e5:
        return f"₹{val/1e5:.2f}L"
    return f"₹{val:,.0f}"
