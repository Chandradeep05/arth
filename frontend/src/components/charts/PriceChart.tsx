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
        background: { type: ColorType.Solid, color: '#070b09' },
        textColor: '#6b7c76',
        fontFamily: "'DM Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.025)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.025)' },
      },
      crosshair: {
        mode: 0,
        vertLine: {
          color: 'rgba(255, 255, 255, 0.15)',
          labelBackgroundColor: '#121a16',
        },
        horzLine: {
          color: 'rgba(255, 255, 255, 0.15)',
          labelBackgroundColor: '#121a16',
        },
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.06)',
        scaleMargins: { top: 0.1, bottom: 0.25 },
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.06)',
        timeVisible: true,
        secondsVisible: false,
      },
      width: container.clientWidth,
      height: height,
    });

    // Candlestick series — strictly green and red
    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderDownColor: '#ef4444',
      borderUpColor: '#10b981',
      wickDownColor: '#ef4444',
      wickUpColor: '#10b981',
    });

    const candleData = data.map((bar) => ({
      time: (new Date(bar.date).getTime() / 1000) as number,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));

    candlestickSeries.setData(candleData as any);

    // Volume series (using HistogramSeries)
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    const volumeData = data.map((bar) => ({
      time: (new Date(bar.date).getTime() / 1000) as number,
      value: bar.volume,
      color: bar.close >= bar.open
        ? 'rgba(16, 185, 129, 0.3)'
        : 'rgba(239, 68, 68, 0.3)',
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
      {/* Timeframe selector & header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/[0.06]">
        <div className="flex items-center gap-2">
          <span className="font-heading text-xs font-bold uppercase tracking-wider text-white">
            {symbol}
          </span>
          <span className="text-[11px] font-mono text-[var(--text-dim)]">
            Candlestick &amp; Volume
          </span>
        </div>

        {/* Polished Capsule Segmented Control */}
        <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-white/[0.03] border border-white/[0.06]">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf.label}
              onClick={() => setActiveTimeframe(tf.label)}
              className={`
                px-2.5 py-1 text-[11px] font-mono rounded-md cursor-pointer transition-all
                ${activeTimeframe === tf.label
                  ? 'bg-white/[0.1] text-white font-semibold shadow-sm border border-white/[0.08]'
                  : 'text-[var(--text-dim)] hover:text-[var(--text)] hover:bg-white/[0.03] border border-transparent'
                }
              `}
            >
              {tf.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart container */}
      <div ref={chartContainerRef} className="bg-[#070b09]" />
    </div>
  );
}
