'use client';

import { useState, useEffect } from 'react';

/**
 * 6 Determined Atmospheric Visuals:
 * 1. Mountains (Volcanic obsidian mountains with twilight glow - designated for Nifty & market cards)
 * 2. Topography (Topographic elevation contour lines)
 * 3. Aurora Emerald (Fluid dark emerald smoked glass wave)
 * 4. Aurora Crimson (Fluid deep oxblood smoked glass wave)
 * 5. Flow Bullish (Directional emerald particle streaks)
 * 6. Flow Bearish (Directional crimson particle flow)
 */
export const DETERMINED_ATMOSPHERES = [
  'card-atmosphere-mountains',
  'card-atmosphere-topography',
  'card-atmosphere-aurora-emerald',
  'card-atmosphere-aurora-crimson',
  'card-atmosphere-flow-bullish',
  'card-atmosphere-flow-bearish',
] as const;

export type AtmosphericVisual = typeof DETERMINED_ATMOSPHERES[number];

/**
 * Deterministic seed based on symbol for initial SSR hydration match,
 * followed by dynamic random selection on client mount.
 */
export function getInitialAtmosphere(symbol?: string): AtmosphericVisual {
  if (!symbol) return 'card-atmosphere-mountains';
  const clean = symbol.toUpperCase();
  if (clean.includes('NIFTY') || clean === '^NSEI') {
    return 'card-atmosphere-mountains';
  }
  let hash = 0;
  for (let i = 0; i < clean.length; i++) {
    hash = (hash << 5) - hash + clean.charCodeAt(i);
    hash |= 0;
  }
  const index = Math.abs(hash) % DETERMINED_ATMOSPHERES.length;
  return DETERMINED_ATMOSPHERES[index];
}

/**
 * React hook to assign an atmospheric subsurface.
 * On every opening/mount of a stock card, it randomly inherits one of our 6 determined visuals.
 * If symbol is NIFTY, it honors the mountain atmosphere.
 */
export function useStockAtmosphere(symbol?: string): AtmosphericVisual {
  const [atmosphere, setAtmosphere] = useState<AtmosphericVisual>(() => getInitialAtmosphere(symbol));

  useEffect(() => {
    const clean = symbol?.toUpperCase();
    if (clean && (clean.includes('NIFTY') || clean === '^NSEI')) {
      setAtmosphere('card-atmosphere-mountains');
      return;
    }
    // Random inheritance across the 6 determined visuals
    const randomIdx = Math.floor(Math.random() * DETERMINED_ATMOSPHERES.length);
    setAtmosphere(DETERMINED_ATMOSPHERES[randomIdx]);
  }, [symbol]);

  return atmosphere;
}
