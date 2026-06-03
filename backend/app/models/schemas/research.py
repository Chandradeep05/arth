"""
Pydantic schemas for AI Research API responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.schemas.market import FreshnessMetadata


class FinancialMetrics(BaseModel):
    """Key financial metrics for a company."""
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    eps: Optional[float] = None
    revenue: Optional[float] = None
    revenue_growth: Optional[float] = None
    profit_margin: Optional[float] = None
    debt_to_equity: Optional[float] = None
    dividend_yield: Optional[float] = None
    book_value: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    current_ratio: Optional[float] = None


class CompanyOverview(BaseModel):
    """Basic company information."""
    symbol: str
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    exchange: str
    market: str
    description: Optional[str] = None
    website: Optional[str] = None
    metrics: FinancialMetrics


class ResearchReport(BaseModel):
    """AI-generated company research report."""
    symbol: str
    company_name: str
    generated_at: datetime
    report_sections: dict = Field(
        description="Report content keyed by section: overview, financials, bull_case, bear_case, risk_factors"
    )
    confidence_score: float = Field(ge=0, le=100, description="Overall confidence in the analysis")
    data_sources: List[str] = Field(default_factory=list, description="Sources used for this report")
    disclaimer: str = Field(
        default="⚠ This is AI-generated analysis for informational purposes only. "
        "This is NOT financial advice. Always consult a qualified financial advisor."
    )
    llm_provider: str = Field(description="LLM used for generation (transparency)")
    llm_model: str = Field(description="Specific model version used")


class ResearchReportResponse(BaseModel):
    success: bool = True
    data: ResearchReport
    freshness: FreshnessMetadata
    trace_id: str | None = None


class ResearchGenerateRequest(BaseModel):
    """Request to generate a research report."""
    symbol: str
    depth: str = Field(default="standard", description="Report depth: quick, standard, deep")
