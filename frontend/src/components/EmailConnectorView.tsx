'use client';

import React, { useState, useEffect } from 'react';
import { 
  Mail, 
  RefreshCw, 
  Shield, 
  ShieldCheck, 
  AlertCircle, 
  CheckCircle2, 
  Trash2, 
  ExternalLink, 
  Lock, 
  Inbox, 
  FileText, 
  Clock, 
  X, 
  Plus,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Paperclip
} from 'lucide-react';
import { EmailAccountConnection, EmailSyncJob, api } from '@/lib/api';

interface EmailConnectorViewProps {
  workspaceId: string;
  onNavigateToDocs?: () => void;
}

export const EmailConnectorView: React.FC<EmailConnectorViewProps> = ({
  workspaceId,
  onNavigateToDocs
}) => {
  const [connections, setConnections] = useState<EmailAccountConnection[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [successBanner, setSuccessBanner] = useState<string | null>(null);

  // Connect Account Modal
  const [isConnectModalOpen, setIsConnectModalOpen] = useState<boolean>(false);
  const [isAuthorizing, setIsAuthorizing] = useState<boolean>(false);
  const [authUrlData, setAuthUrlData] = useState<{ url: string; state: string } | null>(null);

  // Disconnect Modal
  const [disconnectTarget, setDisconnectTarget] = useState<EmailAccountConnection | null>(null);
  const [retainContent, setRetainContent] = useState<boolean>(true);
  const [isDisconnecting, setIsDisconnecting] = useState<boolean>(false);

  // Job History Modal / Drawer
  const [selectedConnForJobs, setSelectedConnForJobs] = useState<EmailAccountConnection | null>(null);
  const [jobsList, setJobsList] = useState<EmailSyncJob[]>([]);
  const [isLoadingJobs, setIsLoadingJobs] = useState<boolean>(false);

  const loadConnections = async () => {
    if (!workspaceId) return;
    setIsLoading(true);
    try {
      const data = await api.getEmailConnections(workspaceId);
      setConnections(data);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to load email account connections.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadConnections();
  }, [workspaceId]);

  const handleInitiateOAuth = async () => {
    setIsAuthorizing(true);
    setErrorBanner(null);
    try {
      const res = await api.getEmailOAuthAuthorizeUrl(workspaceId, 'gmail');
      setAuthUrlData({ url: res.authorization_url, state: res.state });
      // Open provider consent in new window/tab
      window.open(res.authorization_url, '_blank', 'noopener,noreferrer');
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to initiate Google OAuth.');
    } finally {
      setIsAuthorizing(false);
    }
  };

  const handleTriggerSync = async (connId: string, fullSync: boolean = false) => {
    setSyncingId(connId);
    setErrorBanner(null);
    setSuccessBanner(null);
    try {
      const res = await api.triggerEmailSync(connId, fullSync);
      setSuccessBanner(
        `Sync completed: ${res.messages_imported} new email(s) and ${res.attachments_imported} attachment(s) ingested.`
      );
      await loadConnections();
    } catch (err: any) {
      setErrorBanner(err.message || 'Email synchronization failed.');
      await loadConnections();
    } finally {
      setSyncingId(null);
    }
  };

  const handleConfirmDisconnect = async () => {
    if (!disconnectTarget) return;
    setIsDisconnecting(true);
    setErrorBanner(null);
    try {
      const res = await api.disconnectEmailConnection(disconnectTarget.id, retainContent);
      setSuccessBanner(
        retainContent
          ? `Disconnected ${disconnectTarget.email_address}. Existing indexed documents were retained.`
          : `Disconnected ${disconnectTarget.email_address}. ${res.documents_purged} indexed email document(s) purged.`
      );
      setDisconnectTarget(null);
      await loadConnections();
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to disconnect email account.');
    } finally {
      setIsDisconnecting(false);
    }
  };

  const handleInspectJobs = async (conn: EmailAccountConnection) => {
    setSelectedConnForJobs(conn);
    setIsLoadingJobs(true);
    try {
      const jobs = await api.getEmailConnectionJobs(conn.id);
      setJobsList(jobs);
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to load sync jobs.');
    } finally {
      setIsLoadingJobs(false);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Header & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-xl sm:text-2xl font-bold tracking-tight text-[var(--text-primary)]">
              Email Connectors
            </h2>
            <span 
              className="px-2 py-0.5 rounded-full text-[10px] font-bold border uppercase tracking-wider"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)'
              }}
            >
              OAuth 2.0 Read-Only
            </span>
          </div>
          <p className="text-xs sm:text-sm text-[var(--text-muted)] mt-1">
            Securely synchronize email messages and supported attachments into the LORE Knowledge Grid with full L7 private mailbox isolation.
          </p>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          <button
            type="button"
            onClick={loadConnections}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold border transition cursor-pointer hover:border-[var(--brand-accent)] active:scale-95 disabled:opacity-50"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-primary)'
            }}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>

          <button
            type="button"
            onClick={() => setIsConnectModalOpen(true)}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold shadow-sm transition cursor-pointer active:scale-95"
            style={{
              backgroundColor: 'var(--brand-accent)',
              color: 'var(--cta-text)'
            }}
          >
            <Plus className="w-4 h-4" />
            <span>Connect Email Account</span>
          </button>
        </div>
      </div>

      {/* Banners */}
      {errorBanner && (
        <div 
          className="p-3.5 rounded-2xl border text-xs flex items-center justify-between gap-3 animate-in fade-in"
          style={{
            backgroundColor: 'var(--error-bg)',
            borderColor: 'var(--border-color)',
            color: 'var(--error)'
          }}
        >
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{errorBanner}</span>
          </div>
          <button 
            type="button" 
            onClick={() => setErrorBanner(null)}
            className="p-1 rounded-lg hover:bg-black/10 transition cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {successBanner && (
        <div 
          className="p-3.5 rounded-2xl border text-xs flex items-center justify-between gap-3 animate-in fade-in"
          style={{
            backgroundColor: 'var(--success-bg)',
            borderColor: 'var(--success)',
            color: 'var(--success)'
          }}
        >
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            <span>{successBanner}</span>
          </div>
          <button 
            type="button" 
            onClick={() => setSuccessBanner(null)}
            className="p-1 rounded-lg hover:bg-black/10 transition cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Governance & Privacy Notice Card */}
      <div 
        className="p-4 rounded-2xl border flex items-start gap-3 text-xs"
        style={{
          backgroundColor: 'var(--bg-surface-soft)',
          borderColor: 'var(--border-color)',
        }}
      >
        <ShieldCheck className="w-5 h-5 text-[var(--brand-accent)] flex-shrink-0 mt-0.5" />
        <div className="space-y-1">
          <span className="font-bold text-[var(--text-primary)] block">
            Mailbox Privacy & Settlement Gate Isolation
          </span>
          <p className="text-[var(--text-muted)] leading-relaxed">
            Connected mailboxes are treated as private user content. In compliance with Step 4, imported email content is automatically locked to <strong>Authority Rank 1 (informal_note)</strong> and restricted via LORE’s L7 Permission Layer so other workspace members cannot search or query your private mailbox by default.
          </p>
        </div>
      </div>

      {/* Connection List */}
      {isLoading && connections.length === 0 ? (
        <div className="p-12 text-center border rounded-2xl space-y-3" style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-surface)' }}>
          <RefreshCw className="w-6 h-6 animate-spin mx-auto text-[var(--brand-accent)]" />
          <span className="text-xs text-[var(--text-muted)] block">Loading workspace email connections...</span>
        </div>
      ) : connections.length === 0 ? (
        <div 
          className="p-10 border-2 border-dashed rounded-2xl text-center space-y-4"
          style={{
            borderColor: 'var(--border-color)',
            backgroundColor: 'var(--bg-surface)'
          }}
        >
          <div 
            className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto border"
            style={{
              backgroundColor: 'var(--accent-light)',
              borderColor: 'var(--border-color)',
              color: 'var(--brand-accent)'
            }}
          >
            <Inbox className="w-7 h-7" />
          </div>
          <div className="max-w-md mx-auto">
            <h3 className="font-bold text-sm sm:text-base text-[var(--text-primary)]">
              No Email Accounts Connected
            </h3>
            <p className="text-xs text-[var(--text-muted)] mt-1">
              Connect a Google Workspace or Gmail account to automatically index relevant business correspondence and extract supported attachments into your knowledge workspace.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setIsConnectModalOpen(true)}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold shadow-sm transition cursor-pointer active:scale-95"
            style={{
              backgroundColor: 'var(--brand-accent)',
              color: 'var(--cta-text)'
            }}
          >
            <Plus className="w-4 h-4" />
            <span>Connect Gmail Account</span>
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {connections.map(conn => {
            const isSyncing = syncingId === conn.id || conn.status === 'syncing';
            return (
              <div 
                key={conn.id}
                className="border rounded-2xl p-5 space-y-4 flex flex-col justify-between transition-all duration-200 hover:border-[var(--brand-accent)]/40 shadow-xs"
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  borderColor: 'var(--border-color)'
                }}
              >
                {/* Account Header */}
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div 
                      className="w-11 h-11 rounded-2xl border flex items-center justify-center flex-shrink-0 shadow-xs"
                      style={{
                        backgroundColor: conn.provider === 'gmail' ? 'rgba(234, 67, 53, 0.1)' : 'var(--accent-light)',
                        borderColor: 'var(--border-color)',
                        color: conn.provider === 'gmail' ? '#EA4335' : 'var(--brand-accent)'
                      }}
                    >
                      <Mail className="w-5 h-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm block truncate text-[var(--text-primary)]">
                          {conn.email_address}
                        </span>
                        <span 
                          className="px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider border flex items-center gap-1"
                          style={{
                            backgroundColor: 'var(--bg-surface-soft)',
                            borderColor: 'var(--border-color)',
                            color: 'var(--brand-accent)'
                          }}
                        >
                          {conn.provider}
                        </span>
                      </div>
                      <span className="text-[11px] text-[var(--text-muted)] block truncate mt-0.5">
                        Connected by @{conn.user_username} • Scope: Read-Only
                      </span>
                    </div>
                  </div>

                  {/* Status Badge */}
                  <div>
                    {conn.status === 'connected' && (
                      <span 
                        className="px-2.5 py-1 rounded-lg text-xs font-semibold border flex items-center gap-1"
                        style={{
                          backgroundColor: 'var(--success-bg)',
                          borderColor: 'var(--success)',
                          color: 'var(--success)'
                        }}
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>Connected</span>
                      </span>
                    )}
                    {conn.status === 'syncing' && (
                      <span 
                        className="px-2.5 py-1 rounded-lg text-xs font-semibold border flex items-center gap-1 text-blue-500 bg-blue-500/10 border-blue-500/20"
                      >
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                        <span>Syncing</span>
                      </span>
                    )}
                    {conn.status === 'error' && (
                      <span 
                        className="px-2.5 py-1 rounded-lg text-xs font-semibold border flex items-center gap-1"
                        style={{
                          backgroundColor: 'var(--error-bg)',
                          borderColor: 'var(--error)',
                          color: 'var(--error)'
                        }}
                      >
                        <AlertCircle className="w-3.5 h-3.5" />
                        <span>Error</span>
                      </span>
                    )}
                    {conn.status === 'disconnected' && (
                      <span className="px-2.5 py-1 rounded-lg text-xs font-semibold border bg-slate-500/10 text-slate-500 border-slate-500/20">
                        Disconnected
                      </span>
                    )}
                  </div>
                </div>

                {/* Metrics & Last Error */}
                <div 
                  className="p-3 rounded-xl border grid grid-cols-2 gap-2 text-xs"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)'
                  }}
                >
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] block uppercase font-bold">Total Ingested</span>
                    <span className="font-mono font-bold text-sm text-[var(--text-primary)]">
                      {conn.total_messages_synced} emails
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[var(--text-muted)] block uppercase font-bold">Last Synced</span>
                    <span className="text-[11px] text-[var(--text-secondary)] font-medium">
                      {conn.last_sync_at ? new Date(conn.last_sync_at).toLocaleString() : 'Never'}
                    </span>
                  </div>
                </div>

                {conn.last_error && (
                  <div 
                    className="p-2.5 rounded-xl border text-[11px] flex items-center gap-2"
                    style={{
                      backgroundColor: 'var(--error-bg)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--error)'
                    }}
                  >
                    <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                    <span className="truncate">{conn.last_error}</span>
                  </div>
                )}

                {/* Actions Bar */}
                <div className="pt-2 border-t flex items-center justify-between gap-2" style={{ borderColor: 'var(--border-color)' }}>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => handleTriggerSync(conn.id, false)}
                      disabled={isSyncing || conn.status === 'disconnected'}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold border flex items-center gap-1.5 transition cursor-pointer hover:border-[var(--brand-accent)] active:scale-95 disabled:opacity-50"
                      style={{
                        backgroundColor: 'var(--accent-light)',
                        borderColor: 'var(--border-color)',
                        color: 'var(--brand-accent)'
                      }}
                    >
                      <RefreshCw className={`w-3 h-3 ${isSyncing ? 'animate-spin' : ''}`} />
                      <span>{isSyncing ? 'Syncing...' : 'Sync Now'}</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => handleInspectJobs(conn)}
                      className="px-2.5 py-1.5 rounded-lg text-xs font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)] transition cursor-pointer"
                    >
                      View History
                    </button>
                  </div>

                  <button
                    type="button"
                    onClick={() => {
                      setDisconnectTarget(conn);
                      setRetainContent(true);
                    }}
                    className="px-2.5 py-1.5 rounded-lg text-xs font-semibold text-rose-500 hover:bg-rose-500/10 transition cursor-pointer"
                  >
                    Disconnect
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ===================================================================== */}
      {/* MODAL 1: CONNECT EMAIL ACCOUNT MODAL */}
      {/* ===================================================================== */}
      {isConnectModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 backdrop-blur-sm" style={{ backgroundColor: 'var(--modal-overlay)' }}>
          <div 
            className="w-full max-w-lg rounded-2xl border shadow-2xl overflow-hidden p-6 space-y-5 animate-in fade-in zoom-in-95 duration-150"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
            }}
          >
            <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: 'var(--border-color)' }}>
              <div className="flex items-center gap-2.5">
                <div 
                  className="w-9 h-9 rounded-xl flex items-center justify-center border"
                  style={{
                    backgroundColor: 'var(--accent-light)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--brand-accent)'
                  }}
                >
                  <Mail className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-base text-[var(--text-primary)]">Connect Email Account</h3>
                  <p className="text-xs text-[var(--text-muted)]">Select provider to initiate OAuth authorization</p>
                </div>
              </div>
              <button 
                type="button" 
                onClick={() => {
                  setIsConnectModalOpen(false);
                  setAuthUrlData(null);
                }}
                className="p-1 rounded-lg hover:bg-black/10 transition cursor-pointer text-[var(--text-muted)]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Provider Cards */}
            <div className="space-y-3">
              {/* Google Workspace / Gmail */}
              <div 
                className="p-4 rounded-xl border flex items-center justify-between gap-3 cursor-pointer transition hover:border-[var(--brand-accent)]"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)'
                }}
                onClick={handleInitiateOAuth}
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-[#EA4335]/10 border border-[#EA4335]/20 flex items-center justify-center text-[#EA4335] font-bold">
                    G
                  </div>
                  <div>
                    <span className="font-bold text-sm text-[var(--text-primary)] block">
                      Google Workspace / Gmail
                    </span>
                    <span className="text-[11px] text-[var(--text-muted)]">
                      Official OAuth 2.0 • Scope: gmail.readonly
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  disabled={isAuthorizing}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold border shadow-xs transition"
                  style={{
                    backgroundColor: 'var(--brand-accent)',
                    color: 'var(--cta-text)'
                  }}
                >
                  {isAuthorizing ? 'Opening...' : 'Connect'}
                </button>
              </div>

              {/* Microsoft 365 (Upcoming) */}
              <div 
                className="p-4 rounded-xl border flex items-center justify-between gap-3 opacity-60"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)'
                }}
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-[#0078D4]/10 border border-[#0078D4]/20 flex items-center justify-center text-[#0078D4] font-bold">
                    M
                  </div>
                  <div>
                    <span className="font-bold text-sm text-[var(--text-primary)] block">
                      Microsoft Outlook / 365
                    </span>
                    <span className="text-[11px] text-[var(--text-muted)]">
                      Microsoft Graph API (Coming soon in next connector sprint)
                    </span>
                  </div>
                </div>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded border text-[var(--text-muted)] border-[var(--border-color)]">
                  Upcoming
                </span>
              </div>
            </div>

            {/* Scope & Security Notice */}
            <div 
              className="p-3.5 rounded-xl border text-[11px] text-[var(--text-muted)] space-y-1.5"
              style={{
                backgroundColor: 'var(--bg-surface)',
                borderColor: 'var(--border-color)'
              }}
            >
              <div className="flex items-center gap-1.5 font-bold text-[var(--text-primary)]">
                <Lock className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                <span>Zero-Trust Credential Security Guarantee</span>
              </div>
              <p>
                LORE requests strictly <strong>read-only access</strong>. LORE will never ask for or store your email password. OAuth tokens are encrypted at rest with authenticated Fernet AES-128-CBC encryption and are never exposed in serialized responses.
              </p>
            </div>

            <div className="pt-2 flex justify-end">
              <button
                type="button"
                onClick={() => {
                  setIsConnectModalOpen(false);
                  setAuthUrlData(null);
                }}
                className="px-4 py-2 rounded-xl text-xs font-semibold border cursor-pointer hover:border-[var(--brand-accent)]"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-primary)'
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* MODAL 2: DISCONNECT & RETENTION POLICY MODAL (Step 4 & 5) */}
      {/* ===================================================================== */}
      {disconnectTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 backdrop-blur-sm" style={{ backgroundColor: 'var(--modal-overlay)' }}>
          <div 
            className="w-full max-w-md rounded-2xl border shadow-2xl p-6 space-y-4 animate-in fade-in zoom-in-95 duration-150"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
            }}
          >
            <div className="flex items-center gap-3 text-rose-500">
              <AlertTriangle className="w-6 h-6 flex-shrink-0" />
              <h3 className="font-bold text-base text-[var(--text-primary)]">
                Disconnect {disconnectTarget.email_address}
              </h3>
            </div>

            <p className="text-xs text-[var(--text-muted)] leading-relaxed">
              Disconnecting stops future email synchronization and revokes the OAuth connection. Please select how you want LORE to handle previously indexed messages from this account:
            </p>

            {/* Retention Choice Options */}
            <div className="space-y-2.5 pt-1">
              <label 
                className={`p-3 rounded-xl border flex items-start gap-3 cursor-pointer transition ${
                  retainContent ? 'border-[var(--brand-accent)] bg-[var(--accent-light)]' : 'border-[var(--border-color)] bg-[var(--bg-surface-soft)]'
                }`}
              >
                <input 
                  type="radio" 
                  name="retention_choice" 
                  checked={retainContent} 
                  onChange={() => setRetainContent(true)}
                  className="mt-0.5 text-[var(--brand-accent)]"
                />
                <div>
                  <span className="font-bold text-xs block text-[var(--text-primary)]">
                    Retain Indexed Documents (Recommended)
                  </span>
                  <span className="text-[11px] text-[var(--text-muted)] block mt-0.5">
                    Preserves previously synchronized email records and evidence citations in your workspace under their restricted visibility policy.
                  </span>
                </div>
              </label>

              <label 
                className={`p-3 rounded-xl border flex items-start gap-3 cursor-pointer transition ${
                  !retainContent ? 'border-rose-500 bg-rose-500/10' : 'border-[var(--border-color)] bg-[var(--bg-surface-soft)]'
                }`}
              >
                <input 
                  type="radio" 
                  name="retention_choice" 
                  checked={!retainContent} 
                  onChange={() => setRetainContent(false)}
                  className="mt-0.5 text-rose-500"
                />
                <div>
                  <span className="font-bold text-xs block text-rose-500">
                    Purge All Indexed Content From This Account
                  </span>
                  <span className="text-[11px] text-[var(--text-muted)] block mt-0.5">
                    Completely deletes all email documents and attachments imported from this mailbox. Unrelated documents in the workspace remain untouched.
                  </span>
                </div>
              </label>
            </div>

            <div className="pt-3 flex items-center justify-end gap-2.5 border-t" style={{ borderColor: 'var(--border-color)' }}>
              <button
                type="button"
                onClick={() => setDisconnectTarget(null)}
                disabled={isDisconnecting}
                className="px-4 py-2 rounded-xl text-xs font-semibold border cursor-pointer hover:border-[var(--brand-accent)] disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-primary)'
                }}
              >
                Cancel
              </button>

              <button
                type="button"
                onClick={handleConfirmDisconnect}
                disabled={isDisconnecting}
                className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 transition cursor-pointer disabled:opacity-50"
              >
                {isDisconnecting ? 'Disconnecting...' : 'Confirm Disconnect'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* DRAWER / MODAL 3: SYNC JOB HISTORY INSPECTOR */}
      {/* ===================================================================== */}
      {selectedConnForJobs && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 backdrop-blur-sm" style={{ backgroundColor: 'var(--modal-overlay)' }}>
          <div 
            className="w-full max-w-xl rounded-2xl border shadow-2xl p-6 space-y-4 animate-in fade-in zoom-in-95 duration-150"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
            }}
          >
            <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: 'var(--border-color)' }}>
              <div>
                <h3 className="font-bold text-base text-[var(--text-primary)]">
                  Sync History: {selectedConnForJobs.email_address}
                </h3>
                <p className="text-xs text-[var(--text-muted)]">Checkpoints and synchronization run logs</p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedConnForJobs(null)}
                className="p-1 rounded-lg hover:bg-black/10 transition cursor-pointer text-[var(--text-muted)]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {isLoadingJobs ? (
              <div className="p-8 text-center text-xs text-[var(--text-muted)]">
                <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-[var(--brand-accent)]" />
                Loading synchronization history...
              </div>
            ) : jobsList.length === 0 ? (
              <div className="p-6 text-center text-xs text-[var(--text-muted)] border rounded-xl" style={{ borderColor: 'var(--border-color)' }}>
                No recorded synchronization runs yet.
              </div>
            ) : (
              <div className="max-h-64 overflow-y-auto space-y-2.5 divide-y" style={{ borderColor: 'var(--border-color)' }}>
                {jobsList.map(job => (
                  <div key={job.id} className="pt-2 text-xs flex items-center justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold capitalize text-[var(--text-primary)]">
                          Status: {job.status}
                        </span>
                        <span className="text-[10px] text-[var(--text-muted)] font-mono">
                          {job.duration_ms}ms
                        </span>
                      </div>
                      <span className="text-[11px] text-[var(--text-muted)] block mt-0.5">
                        {job.messages_imported} message(s) imported • {job.attachments_imported} attachment(s)
                      </span>
                      {job.errors.length > 0 && (
                        <span className="text-[10px] text-[var(--error)] block mt-0.5">
                          {job.errors[0]}
                        </span>
                      )}
                    </div>
                    <span className="text-[10px] text-[var(--text-muted)] font-mono flex-shrink-0">
                      {new Date(job.created_at).toLocaleTimeString()}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div className="pt-3 flex justify-end border-t" style={{ borderColor: 'var(--border-color)' }}>
              <button
                type="button"
                onClick={() => setSelectedConnForJobs(null)}
                className="px-4 py-2 rounded-xl text-xs font-semibold border cursor-pointer hover:border-[var(--brand-accent)]"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-primary)'
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
