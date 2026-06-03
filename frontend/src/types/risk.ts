/**
 * Risk Assessment Type Definitions
 * Interfaces for risk scoring, anomaly detection, and governance flags
 */

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

export interface RiskDimension {
  name: string;
  score: number; // 0-100
  level: RiskLevel;
  description: string;
  weight: number;
  factors: string[];
}

export interface RiskScore {
  symbol: string;
  companyName: string;
  overallScore: number; // 0-100
  overallLevel: RiskLevel;
  dimensions: RiskDimension[];
  timestamp: string;
  model: string;
}

export interface AnomalyAlert {
  id: string;
  symbol: string;
  type: 'price_spike' | 'volume_surge' | 'volatility_breakout' | 'pattern_deviation' | 'correlation_break';
  severity: RiskLevel;
  title: string;
  description: string;
  detectedAt: string;
  metric: string;
  currentValue: number;
  expectedValue: number;
  deviation: number;
  acknowledged: boolean;
}

export interface GovernanceFlag {
  id: string;
  symbol: string;
  companyName: string;
  category: 'insider_trading' | 'regulatory' | 'audit' | 'board_change' | 'litigation' | 'compliance';
  severity: RiskLevel;
  title: string;
  description: string;
  source: string;
  detectedAt: string;
  url: string;
}

export interface PortfolioRisk {
  totalExposure: number;
  concentration: number;
  sectorConcentration: Record<string, number>;
  betaWeighted: number;
  valueAtRisk: number;
  maxDrawdown: number;
  sharpeRatio: number;
  correlationMatrix: Record<string, Record<string, number>>;
}

export interface RiskDashboard {
  portfolioRisk: PortfolioRisk;
  stockRisks: RiskScore[];
  activeAlerts: AnomalyAlert[];
  governanceFlags: GovernanceFlag[];
  lastUpdated: string;
}
