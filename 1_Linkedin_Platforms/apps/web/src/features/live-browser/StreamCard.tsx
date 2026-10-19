'use client';

import React, { useState } from 'react';

export interface StreamCardProps {
  cardId: 'card-linkedin' | 'card-platform';
  title: string;
  subtitle: string;
  statusBadge: string;
  badgeType: 'linkedin' | 'platform';
  imageSrc?: string;
  placeholderText: string;
  logs: Array<{ time: string; text: string }>;
  onViewTab?: () => void;
  onClearLogs?: () => void;
}

export const StreamCard: React.FC<StreamCardProps> = ({
  cardId,
  title,
  subtitle,
  statusBadge,
  badgeType,
  imageSrc,
  placeholderText,
  logs,
  onViewTab,
  onClearLogs,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);

  const badgeColorClass =
    badgeType === 'linkedin'
      ? 'bg-cyan-950/80 text-cyan-400 border-cyan-800/60'
      : 'bg-purple-950/80 text-purple-400 border-purple-800/60';

  return (
    <div
      id={cardId}
      className={`flex flex-col rounded-xl border border-slate-800 bg-slate-900/90 shadow-xl overflow-hidden transition-all duration-300 ${
        isExpanded ? 'fixed inset-4 z-50 bg-slate-950 max-w-none max-h-none' : 'h-full min-h-[380px]'
      }`}
    >
      {/* Stream Card Header */}
      <div className="flex items-center justify-between border-b border-slate-800/80 px-4 py-2.5 bg-slate-950/80">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`px-2 py-0.5 text-[10px] font-bold uppercase rounded border ${badgeColorClass}`}>
            {statusBadge}
          </span>
          <span className="text-xs font-semibold text-slate-200 truncate">{title}</span>
          <span className="text-[10px] text-slate-500 font-mono hidden sm:inline">{subtitle}</span>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {onViewTab && (
            <button
              onClick={onViewTab}
              className="px-2 py-1 text-[11px] rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
              title="Bring Chrome Tab to front"
            >
              👁️ View
            </button>
          )}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition-colors text-xs"
            title="Toggle Maximize"
          >
            {isExpanded ? '🗗' : '⛶'}
          </button>
        </div>
      </div>

      {/* Viewport */}
      <div className="relative flex-1 bg-black/60 flex items-center justify-center overflow-hidden min-h-[200px]">
        {imageSrc ? (
          <img src={imageSrc} alt={`${title} Stream`} className="w-full h-full object-contain" />
        ) : (
          <div className="text-center p-6 space-y-2">
            <span className="text-3xl opacity-30">🌐</span>
            <p className="text-xs font-medium text-slate-500 tracking-wide">{placeholderText}</p>
          </div>
        )}
      </div>

      {/* Agent Live Console */}
      <div className="h-32 border-t border-slate-800/80 bg-slate-950/90 flex flex-col">
        <div className="flex items-center justify-between px-3 py-1 border-b border-slate-800/60 bg-slate-950 text-[10px] text-slate-400">
          <span className="font-semibold uppercase tracking-wider flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full ${badgeType === 'linkedin' ? 'bg-cyan-400' : 'bg-purple-400'}`} />
            Live Logs
          </span>
          <div className="flex items-center gap-2">
            <span>{logs.length} events</span>
            {onClearLogs && (
              <button onClick={onClearLogs} className="hover:text-white" title="Clear Console">
                🧹
              </button>
            )}
          </div>
        </div>
        <div className="flex-1 p-2.5 overflow-y-auto space-y-1 font-mono text-[11px]">
          {logs.map((lg, i) => (
            <div key={i} className="leading-snug text-slate-300">
              <span className="text-slate-500 mr-2">{lg.time}</span>
              <span>{lg.text}</span>
            </div>
          ))}
          {logs.length === 0 && (
            <div className="text-slate-600 italic">Standby. No logs recorded yet.</div>
          )}
        </div>
      </div>
    </div>
  );
};
