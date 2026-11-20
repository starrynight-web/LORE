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

// Official Brand Logos (Pixel-perfect authentic SVGs)
const ConfluenceLogo: React.FC<{ className?: string }> = ({ className = "w-6 h-6" }) => (
  <svg viewBox="0 0 32 32" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M5.14 22.36a6.05 6.05 0 01.8-3.03l5.52-9.56a1.73 1.73 0 012.36-.63c.75.43 1 1.38.57 2.13l-4.22 7.3a4.34 4.34 0 003.76 6.51h.05c.86 0 1.56.7 1.56 1.56v.05c0 .86-.7 1.56-1.56 1.56h-.05a7.46 7.46 0 01-6.46-3.73l-2.37-2.16z"
      fill="#2684FF"
    />
    <path
      d="M26.86 9.64a6.05 6.05 0 01-.8 3.03l-5.52 9.56a1.73 1.73 0 01-2.36.63 1.73 1.73 0 01-.57-2.13l4.22-7.3a4.34 4.34 0 00-3.76-6.51h-.05c-.86 0-1.56-.7-1.56-1.56v-.05c0-.86.7-1.56 1.56-1.56h.05a7.46 7.46 0 016.46 3.73l2.37 2.16z"
      fill="#0052CC"
    />
  </svg>
);

const SharePointLogo: React.FC<{ className?: string }> = ({ className = "w-6 h-6" }) => (
  <svg viewBox="0 0 32 32" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <ellipse cx="20.5" cy="11.5" rx="6.5" ry="6.5" fill="#00A99D" fillOpacity="0.85" />
    <ellipse cx="14.5" cy="20.5" rx="7.5" ry="7.5" fill="#038387" fillOpacity="0.95" />
    <ellipse cx="21" cy="20" rx="5.5" ry="5.5" fill="#004E8C" fillOpacity="0.75" />
    <rect x="3" y="7" width="16" height="18" rx="3.5" fill="#008272" />
    <path
      d="M13.2 12.3c-.4-.5-1.1-.8-1.9-.8-1.3 0-2.3.8-2.3 2 0 1.2.9 1.7 2 2l.5.1c.9.3 1.4.6 1.4 1.2 0 .8-.7 1.4-1.8 1.4-.9 0-1.6-.3-2.1-.8l-.6 1.2c.7.6 1.7.9 2.7.9 2 0 3.2-1.1 3.2-2.6 0-1.3-.9-2-2.3-2.3l-.5-.1c-.8-.2-1.2-.5-1.2-1 0-.6.5-1.1 1.4-1.1.7 0 1.4.3 1.8.7l.7-1.1z"
      fill="#FFFFFF"
    />
  </svg>
);

const JiraLogo: React.FC<{ className?: string }> = ({ className = "w-6 h-6" }) => (
  <svg viewBox="0 0 32 32" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M27.67 15.02L16.98 4.33a1.39 1.39 0 00-1.96 0L4.33 15.02a1.39 1.39 0 000 1.96l10.69 10.69c.54.54 1.42.54 1.96 0l10.69-10.69a1.39 1.39 0 000-1.96z"
      fill="#0052CC"
    />
    <path
      d="M16 11.23L11.23 16 16 20.77 20.77 16 16 11.23z"
      fill="#FFFFFF"
    />
    <path
      d="M16 6.57L6.57 16 16 25.43 25.43 16 16 6.57zm0 13.06L12.37 16 16 12.37 19.63 16 16 19.63z"
      fill="#2684FF"
    />
  </svg>
);

const GitHubLogo: React.FC<{ className?: string }> = ({ className = "w-6 h-6" }) => (
  <svg viewBox="0 0 24 24" className={className} fill="#24292F" xmlns="http://www.w3.org/2000/svg">
    <path
      fillRule="evenodd"
      clipRule="evenodd"
      d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
    />
  </svg>
);

const WebScraperLogo: React.FC<{ className?: string }> = ({ className = "w-6 h-6" }) => (
  <svg viewBox="0 0 32 32" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="16" cy="16" r="13" stroke="var(--lavender-deep)" strokeWidth="2" strokeDasharray="3 3" />
    <circle cx="16" cy="16" r="7.5" fill="var(--lavender-deep)" />
    <path d="M16 3v4M16 25v4M3 16h4M25 16h4M6.8 6.8l2.8 2.8M22.4 22.4l2.8 2.8M6.8 25.2l2.8-2.8M22.4 9.6l2.8-2.8" stroke="var(--lavender-active)" strokeWidth="2" strokeLinecap="round" />
    <circle cx="16" cy="16" r="3" fill="#ffffff" />
  </svg>
);

const LiveEvidenceLogo: React.FC<{ className?: string }> = ({ className = "w-6 h-6" }) => (
  <svg viewBox="0 0 32 32" className={className} fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M16 4.5l8.5 3.8v7.2c0 5.8-3.6 11.2-8.5 12.5-4.9-1.3-8.5-6.7-8.5-12.5V8.3L16 4.5z"
      fill="var(--lavender)"
    />
    <path
      d="M16 10a5 5 0 00-5 5c0 2.2 1.4 4.1 3.5 4.7v-2.2a2.8 2.8 0 01-1.3-2.5 2.8 2.8 0 015.6 0c0 1.1-.6 2.1-1.5 2.5v2.2c2.1-.6 3.7-2.5 3.7-4.7a5 5 0 00-5-5z"
      fill="var(--sage)"
    />
    <circle cx="16" cy="21.5" r="1.3" fill="#ffffff" />
  </svg>
);

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

  const getConnectorLogo = (id: string) => {
    switch (id) {
      case 'github':
        return <GitHubLogo className="w-6 h-6" />;
      case 'confluence':
        return <ConfluenceLogo className="w-6 h-6" />;
      case 'sharepoint':
        return <SharePointLogo className="w-6 h-6" />;
      case 'jira':
        return <JiraLogo className="w-6 h-6" />;
      case 'web_scraper':
        return <WebScraperLogo className="w-6 h-6" />;
      case 'live_evidence':
        return <LiveEvidenceLogo className="w-6 h-6" />;
      default:
        return <Server className="w-6 h-6 text-slate-400" />;
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
                    className="w-10 h-10 rounded-xl border flex items-center justify-center flex-shrink-0 bg-white dark:bg-zinc-900 shadow-xs"
                    style={{
                      borderColor: 'var(--border-color)',
                    }}
                  >
                    {getConnectorLogo(c.id)}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span 
                      className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                        c.status === 'ONLINE' || c.status === 'CONNECTED'
                          ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20'
                          : 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border-zinc-500/20'
                      }`}
                    >
                      {c.status}
                    </span>
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                      c.freshness === 'FRESH' || c.freshness === 'ACTIVE'
                        ? 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20'
                        : 'bg-zinc-500/10 text-zinc-500 border-zinc-500/20'
                    }`}>
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
                    <span className="font-mono font-bold text-[var(--text-primary)]">{c.items_count ?? 0} records</span>
                  </div>
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-[var(--text-muted)]">Last Synchronized:</span>
                    <span className="font-mono text-[var(--text-secondary)]">
                      {c.last_sync && (c.items_count ?? 0) > 0
                        ? new Date(c.last_sync).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                        : 'Never'}
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
