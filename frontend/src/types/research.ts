/**
 * Research Data Type Definitions
 * Interfaces for AI-generated research reports and company analysis
 */

export interface FinancialMetrics {
  pe: number;
  pb: number;
  eps: number;
  roe: number;
  debtToEquity: number;
  currentRatio: number;
  dividendYield: number;
  marketCap: number;
  revenue: number;
  revenueGrowth: number;
  netIncome: number;
  netIncomeGrowth: number;
  operatingMargin: number;
  freeCashFlow: number;
}

export interface BullBearThesis {
  bull: string[];
  bear: string[];
  catalysts: string[];
  risks: string[];
}

export interface CompanyOverview {
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  description: string;
  website: string;
  employees: number;
  headquarters: string;
  ceo: string;
  founded: string;
  metrics: FinancialMetrics;
}

export interface ResearchSection {
  title: string;
  content: string;
  confidence: number;
}

export interface ResearchReport {
  id: string;
  symbol: string;
  companyName: string;
  generatedAt: string;
  model: string;
  overview: CompanyOverview;
  thesis: BullBearThesis;
  sections: ResearchSection[];
  financialMetrics: FinancialMetrics;
  overallConfidence: number;
  disclaimer: string;
  sources: string[];
}

export interface ResearchListItem {
  id: string;
  symbol: string;
  companyName: string;
  generatedAt: string;
  overallConfidence: number;
  summary: string;
}
