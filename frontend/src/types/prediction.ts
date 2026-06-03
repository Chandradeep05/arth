/**
 * Prediction / Forecast Type Definitions
 * Interfaces for ML-based price predictions and SHAP explanations
 */

export interface ConfidenceBand {
  date: string;
  predicted: number;
  upperBound: number;
  lowerBound: number;
  confidence: number;
}

export interface SHAPFeature {
  feature: string;
  value: number;
  impact: number; // positive = bullish contribution, negative = bearish
  description: string;
}

export interface SHAPExplanation {
  baseValue: number;
  outputValue: number;
  features: SHAPFeature[];
  model: string;
  timestamp: string;
}

export interface Forecast {
  symbol: string;
  companyName: string;
  currentPrice: number;
  predictedPrice: number;
  predictedChange: number;
  predictedChangePercent: number;
  horizon: '1d' | '5d' | '1m' | '3m';
  confidence: number;
  bands: ConfidenceBand[];
  shapExplanation: SHAPExplanation;
  model: string;
  generatedAt: string;
  disclaimer: string;
}

export interface ForecastSummary {
  symbol: string;
  companyName: string;
  direction: 'up' | 'down' | 'neutral';
  predictedChangePercent: number;
  confidence: number;
  horizon: string;
}

export interface ModelPerformance {
  model: string;
  accuracy: number;
  mae: number;
  rmse: number;
  sharpeRatio: number;
  backtestPeriod: string;
  lastUpdated: string;
}
