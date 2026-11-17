'use client';

import React, { useState, useEffect } from 'react';
import { 
  Globe, 
  RotateCw, 
  CheckCircle2, 
  AlertCircle, 
  Server, 
  Database, 
  GitBranch, 
  FileText, 
  ShieldCheck, 
  ExternalLink,
  Layers,
  ArrowRight,
  Clock,
  Sparkles
} from 'lucide-react';
import { EnterpriseConnectorStatus, api } from '@/lib/api';

interface EnterpriseConnectorsViewProps {
  workspaceId?: string;
  onOpenWebScraperModal?: () => void;
}

export const EnterpriseConnectorsView: React.FC<EnterpriseConnectorsViewProps> = ({
  workspaceId,
  onOpenWebScraperModal
}) => {
  const [connectors, setConnectors] = useState<EnterpriseConnectorStatus[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const loadStatuses = async () => {
    setIsLoading(true);
    try {
      const data = await api.getConnectorsStatus(workspaceId);
      setConnectors(data);
    } catch (err) {
      console.warn("Could not load connector statuses:", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadStatuses();
  }, [workspaceId]);

  const handleSyncNow = async (connectorId?: string) => {
    setSyncingId(connectorId || 'all');
    setStatusMessage(null);
    try {
      const res = await api.triggerConnectorSync(connectorId, workspaceId);
      setStatusMessage(res.message);
      await loadStatuses();
    } catch (err: any) {
      console.error("Sync trigger failed:", err);
      setStatusMessage("Failed to initiate connector synchronization.");
    } finally {
      setSyncingId(null);
    }
  };

  const getConnectorIcon = (id: string) => {
    switch (id) {
      case 'github':
        return <GitBranch className="w-5 h-5 text-purple-400" />;
      case 'confluence':
        return <FileText className="w-5 h-5 text-blue-400" />;
      case 'sharepoint':
        return <Database className="w-5 h-5 text-teal-400" />;
      case 'jira':
        return <Layers className="w-5 h-5 text-indigo-400" />;
      case 'web_scraper':
        return <Globe className="w-5 h-5 text-amber-400" />;
      case 'live_evidence':
        return <ShieldCheck className="w-5 h-5 text-emerald-400" />;
      default:
        return <Server className="w-5 h-5 text-slate-400" />;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg sm:text-xl font-extrabold flex items-center gap-2 text-[var(--text-primary)]">
            <Globe className="w-5 h-5 text-[var(--brand-accent)]" />
            <span>Enterprise Connectors & Systems of Record</span>
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            Event-driven ingestion bus connecting Confluence, SharePoint, Jira, GitHub, Web Scrapers, and Vanta/ServiceNow.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {onOpenWebScraperModal && (
            <button
              onClick={onOpenWebScraperModal}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold shadow-sm transition cursor-pointer active:scale-95"
              style={{
                backgroundColor: 'var(--brand-accent)',
                color: 'var(--cta-text)',
              }}
            >
              <Globe className="w-3.5 h-3.5" />
              <span>Scrape Web URL</span>
            </button>
          )}
          <button
            onClick={() => handleSyncNow()}
            disabled={syncingId !== null}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold border transition cursor-pointer active:scale-95 disabled:opacity-50"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-primary)',
            }}
          >
            <RotateCw className={`w-3.5 h-3.5 text-[var(--brand-accent)] ${syncingId === 'all' ? 'animate-spin' : ''}`} />
            <span>Sync All Connectors</span>
          </button>
        </div>
      </div>

      {statusMessage && (
        <div 
          className="p-3.5 rounded-xl border text-xs font-medium flex items-center gap-2"
          style={{
            backgroundColor: 'var(--accent-light)',
            borderColor: 'var(--border-color)',
            color: 'var(--brand-accent)',
          }}
        >
          <Sparkles className="w-4 h-4 flex-shrink-0" />
          <span>{statusMessage}</span>
        </div>
      )}

      {/* Grid of Connectors */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {connectors.map((c) => {
          const isSyncing = syncingId === c.id;
          return (
            <div
              key={c.id}
              className="rounded-2xl p-5 border shadow-sm flex flex-col justify-between gap-4 transition-all"
              style={{
                backgroundColor: 'var(--bg-surface)',
                borderColor: 'var(--border-color)',
              }}
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div 
                    className="w-10 h-10 rounded-xl border flex items-center justify-center flex-shrink-0"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                    }}
                  >
                    {getConnectorIcon(c.id)}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span 
                      className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                        c.status === 'ONLINE' || c.status === 'CONNECTED'
                          ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                          : 'bg-rose-500/10 text-rose-500 border-rose-500/20'
                      }`}
                    >
                      {c.status}
                    </span>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full border bg-blue-500/10 text-blue-500 border-blue-500/20">
                      {c.freshness}
                    </span>
                  </div>
                </div>

                <div>
                  <h4 className="font-bold text-sm text-[var(--text-primary)]">{c.name}</h4>
                  <p className="text-xs text-[var(--text-muted)] mt-0.5">{c.category}</p>
                </div>

                <div 
                  className="p-3 rounded-xl border text-xs space-y-1.5"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-[var(--text-muted)]">Indexed Items:</span>
                    <span className="font-mono font-bold text-[var(--text-primary)]">{c.items_count} records</span>
                  </div>
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-[var(--text-muted)]">Last Synchronized:</span>
                    <span className="font-mono text-[var(--text-secondary)]">
                      {new Date(c.last_sync).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                </div>
              </div>

              <div className="pt-2 border-t flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
                <span className="text-[11px] text-[var(--text-muted)] flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  <span>Cadence: 15m</span>
                </span>
                <button
                  onClick={() => handleSyncNow(c.id)}
                  disabled={isSyncing}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border transition active:scale-95 disabled:opacity-50 cursor-pointer"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--text-primary)',
                  }}
                >
                  <RotateCw className={`w-3 h-3 text-[var(--brand-accent)] ${isSyncing ? 'animate-spin' : ''}`} />
                  <span>{isSyncing ? 'Syncing...' : 'Sync Now'}</span>
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
