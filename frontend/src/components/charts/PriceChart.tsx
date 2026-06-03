'use client';

import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries, HistogramSeries } from 'lightweight-charts';

interface OHLCVBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface PriceChartProps {
  data: OHLCVBar[];
  symbol: string;
  height?: number;
}

const TIMEFRAMES = [
  { label: '1D', period: '1d', interval: '5m' },
  { label: '1W', period: '5d', interval: '15m' },
  { label: '1M', period: '1mo', interval: '1d' },
  { label: '3M', period: '3mo', interval: '1d' },
  { label: '1Y', period: '1y', interval: '1wk' },
  { label: '5Y', period: '5y', interval: '1mo' },
] as const;

export default function PriceChart({ data, symbol, height = 420 }: PriceChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const [activeTimeframe, setActiveTimeframe] = useState('3M');

  useEffect(() => {
    if (!chartContainerRef.current || data.length === 0) return;

    const container = chartContainerRef.current;

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: '#0d1318' },
        textColor: '#637080',
        fontFamily: "'DM Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(30, 45, 61, 0.5)' },
        horzLines: { color: 'rgba(30, 45, 61, 0.5)' },
      },
      crosshair: {
        mode: 0,
        vertLine: {
          color: 'rgba(0, 212, 255, 0.3)',
          labelBackgroundColor: '#111920',
        },
        horzLine: {
          color: 'rgba(0, 212, 255, 0.3)',
          labelBackgroundColor: '#111920',
        },
      },
      rightPriceScale: {
        borderColor: '#1e2d3d',
        scaleMargins: { top: 0.1, bottom: 0.25 },
      },
      timeScale: {
        borderColor: '#1e2d3d',
        timeVisible: true,
        secondsVisible: false,
      },
      width: container.clientWidth,
      height: height,
    });

    // Candlestick series
    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#00d4a0',
      downColor: '#ff4444',
      borderDownColor: '#ff4444',
      borderUpColor: '#00d4a0',
      wickDownColor: '#ff4444',
      wickUpColor: '#00d4a0',
    });

    const candleData = data.map((bar) => ({
      time: (new Date(bar.date).getTime() / 1000) as number,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));

    candlestickSeries.setData(candleData as any);

    // Volume series (using HistogramSeries in v5)
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    const volumeData = data.map((bar) => ({
      time: (new Date(bar.date).getTime() / 1000) as number,
      value: bar.volume,
      color: bar.close >= bar.open
        ? 'rgba(0, 212, 160, 0.3)'
        : 'rgba(255, 68, 68, 0.3)',
    }));

    volumeSeries.setData(volumeData as any);

    chart.timeScale().fitContent();

    // Resize handler
    const handleResize = () => {
      chart.applyOptions({ width: container.clientWidth });
    };
    const observer = new ResizeObserver(handleResize);
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [data, height]);

  return (
    <div className="card overflow-hidden">
      {/* Timeframe selector */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--border)]">
        <h3 className="font-heading text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
          {symbol} Price Chart
        </h3>
        <div className="flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf.label}
              onClick={() => setActiveTimeframe(tf.label)}
              className={`
                px-2.5 py-1 text-[10px] font-mono rounded cursor-pointer transition-colors
                ${activeTimeframe === tf.label
                  ? 'bg-[var(--accent)]/15 text-[var(--accent)] border border-[var(--accent)]/30'
                  : 'text-[var(--text-dim)] hover:text-[var(--text-muted)] hover:bg-[var(--surface-2)]'
                }
              `}
            >
              {tf.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart container */}
      <div ref={chartContainerRef} />
    </div>
  );
}
