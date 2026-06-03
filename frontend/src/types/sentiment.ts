/**
 * Sentiment Analysis Type Definitions
 * Interfaces for news sentiment scoring and tracking
 */

export type SentimentLabel = 'very_bullish' | 'bullish' | 'neutral' | 'bearish' | 'very_bearish';

export interface SentimentScore {
  overall: number; // -1 to 1
  label: SentimentLabel;
  confidence: number; // 0 to 100
  bullishCount: number;
  bearishCount: number;
  neutralCount: number;
  totalArticles: number;
  timestamp: string;
}

export interface NewsItem {
  id: string;
  title: string;
  source: string;
  url: string;
  publishedAt: string;
  summary: string;
  sentiment: number; // -1 to 1
  sentimentLabel: SentimentLabel;
  relevanceScore: number;
  symbols: string[];
}

export interface SentimentSource {
  name: string;
  articleCount: number;
  averageSentiment: number;
  reliability: number;
}

export interface SentimentTrend {
  date: string;
  sentiment: number;
  volume: number;
}

export interface SymbolSentiment {
  symbol: string;
  companyName: string;
  sentiment: SentimentScore;
  recentNews: NewsItem[];
  sources: SentimentSource[];
  trend: SentimentTrend[];
}
