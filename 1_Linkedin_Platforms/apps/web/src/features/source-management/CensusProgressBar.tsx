'use client';

import React from 'react';

export interface PlatformCensusItem {
  name: string;
  total: number;
  scraped: number;
  color?: string;
  icon?: string;
}

interface CensusProgressBarProps {
  items: PlatformCensusItem[];
}

export const CensusProgressBar: React.FC<CensusProgressBarProps> = ({ items }) => {
  if (!items || items.length === 0) return null;

  return (
    <div className="w-full rounded-xl border border-slate-800 bg-slate-950/60 p-4 space-y-3">
      <div className="flex items-center justify-between text-xs">
        <span className="font-bold text-slate-300 uppercase tracking-wider flex items-center gap-2">
          <span>📊</span> Proximity Directory Census
        </span>
        <span className="text-slate-500 text-[11px]">
          {items.reduce((acc, it) => acc + it.scraped, 0)} / {items.reduce((acc, it) => acc + it.total, 0)} listings
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {items.map((it) => {
          const pct = it.total > 0 ? Math.min(100, Math.round((it.scraped / it.total) * 100)) : 0;
          return (
            <div key={it.name} className="p-2.5 rounded-lg border border-slate-800/80 bg-slate-900/50 space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-200 flex items-center gap-1.5">
                  <span>{it.icon || '🟣'}</span> {it.name}
                </span>
                <span className="text-[11px] text-slate-400 font-mono">
                  {it.scraped}/{it.total}
                </span>
              </div>
              <div className="w-full h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: `${pct}%`,
                    backgroundColor: it.color || '#a855f7'
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
