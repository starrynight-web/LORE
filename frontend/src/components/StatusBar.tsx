'use client';

import React, { useState, useEffect } from 'react';

interface StatusBarProps {
  isSyncing?: boolean;
  lastSynced?: Date | null;
  layersCount?: number;
  totalLayers?: number;
}

export const StatusBar: React.FC<StatusBarProps> = ({
  isSyncing = false,
  lastSynced,
  layersCount = 9,
  totalLayers = 9,
}) => {
  const [timeStr, setTimeStr] = useState<string>('');

  useEffect(() => {
    const updateTime = () => {
      const now = lastSynced || new Date();
      setTimeStr(
        now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      );
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, [lastSynced]);

  return (
    <footer 
      className="h-6 w-full border-t px-4 flex items-center justify-between text-[10px] font-mono select-none shrink-0 transition-colors z-20"
      style={{
        backgroundColor: 'var(--canvas)',
        borderColor: 'var(--hairline)',
        color: 'var(--text-secondary)'
      }}
    >
      {/* Left cluster */}
      <div className="flex items-center gap-2">
        <span 
          className={`w-1.5 h-1.5 rounded-full bg-[#34C759] ${isSyncing ? 'animate-ping' : ''}`}
          style={{
            backgroundColor: isSyncing ? '#007AFF' : '#34C759'
          }}
        />
        <span className="font-semibold text-[var(--text-primary)]">Connected</span>
        <span className="text-[#86868B]">·</span>
        <span>Kùzu/SQLite ⇄ Neo4j/pgvector</span>
      </div>

      {/* Right cluster */}
      <div className="flex items-center gap-2">
        <span className="font-semibold text-[var(--text-primary)]">
          {layersCount}/{totalLayers} layers
        </span>
        <span className="text-[#86868B]">·</span>
        <span>v3.0</span>
        <span className="text-[#86868B]">·</span>
        <span className="tabular-nums">synced {timeStr || 'just now'}</span>
      </div>
    </footer>
  );
};
