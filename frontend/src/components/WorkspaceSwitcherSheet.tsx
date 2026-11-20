'use client';

import React, { useState } from 'react';
import { Building2, Check, Search, X, ShieldCheck, ChevronRight, Plus, Loader2, Copy } from 'lucide-react';
import { Workspace, Organization, api } from '@/lib/api';

interface WorkspaceSwitcherSheetProps {
  isOpen: boolean;
  onClose: () => void;
  workspaces: Workspace[];
  currentWorkspace: Workspace | null;
  currentOrg: Organization | null;
  onSelectWorkspace: (ws: Workspace) => void;
  onWorkspaceCreated?: (ws: Workspace) => void;
}

export const WorkspaceSwitcherSheet: React.FC<WorkspaceSwitcherSheetProps> = ({
  isOpen,
  onClose,
  workspaces,
  currentWorkspace,
  currentOrg,
  onSelectWorkspace,
  onWorkspaceCreated
}) => {
  const [search, setSearch] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [newWsName, setNewWsName] = useState('');
  const [newWsDesc, setNewWsDesc] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  if (!isOpen) return null;

  // Group workspaces by organization
  const grouped: Record<string, Workspace[]> = {};
  workspaces.forEach(ws => {
    const orgName = ws.organization_name || 'Organization';
    if (!grouped[orgName]) grouped[orgName] = [];
    grouped[orgName].push(ws);
  });

  const filteredGrouped: Record<string, Workspace[]> = {};
  Object.keys(grouped).forEach(org => {
    const matches = grouped[org].filter(ws => 
      ws.name.toLowerCase().includes(search.toLowerCase()) ||
      org.toLowerCase().includes(search.toLowerCase())
    );
    if (matches.length > 0) filteredGrouped[org] = matches;
  });

  const handleCreateWorkspace = async (e: React.FormEvent) => {
    e.preventDefault();
    const orgId = currentOrg?.id || currentWorkspace?.organization;
    if (!orgId) {
      setCreateError('No active organization found to attach workspace.');
      return;
    }
    if (!newWsName.trim()) {
      setCreateError('Workspace name is required.');
      return;
    }

    setIsSubmitting(true);
    setCreateError(null);
    const computedSlug = newWsName.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || 'workspace';
    try {
      const newWs = await api.createWorkspace({
        organization: orgId,
        name: newWsName.trim(),
        slug: computedSlug,
        description: newWsDesc.trim() || 'Enterprise sovereign partition',
      });
      setNewWsName('');
      setNewWsDesc('');
      setIsCreating(false);
      if (onWorkspaceCreated) {
        onWorkspaceCreated(newWs);
      } else {
        onSelectWorkspace(newWs);
      }
      onClose();
    } catch (err: any) {
      setCreateError(err.message || 'Failed to create workspace.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div 
      className="fixed inset-0 z-50 flex items-start justify-center sm:justify-end"
      style={{ backgroundColor: 'var(--modal-overlay)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div 
        className="w-full sm:w-[420px] h-full sonoma-card sonoma-elevation flex flex-col border-l transition-transform duration-200 animate-in slide-in-from-right"
        style={{
          backgroundColor: 'var(--bg-card)',
          borderColor: 'var(--border)',
        }}
      >
        {/* Header */}
        <div 
          className="h-[52px] px-5 border-b flex items-center justify-between shrink-0"
          style={{ borderColor: 'var(--border)' }}
        >
          <div className="flex items-center gap-2">
            <Building2 className="w-4 h-4 text-[var(--lavender-deep)]" />
            <h2 className="sonoma-section text-[var(--text-primary)]">
              {isCreating ? 'Create Workspace' : 'Switch Workspace'}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {!isCreating && (
              <button
                onClick={() => { setIsCreating(true); setCreateError(null); }}
                className="h-7 px-2.5 rounded-lg text-xs font-semibold flex items-center gap-1 cursor-pointer transition-opacity hover:opacity-90"
                style={{
                  backgroundColor: 'var(--accent)',
                  color: 'var(--accent-fg)'
                }}
                title="Create a new workspace"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>New</span>
              </button>
            )}
            <button
              onClick={onClose}
              className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--hover)] transition-colors cursor-pointer"
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {isCreating ? (
          /* Inline Creation Form */
          <div className="p-5 flex-1 overflow-y-auto">
            <form onSubmit={handleCreateWorkspace} className="space-y-4">
              <div>
                <p className="text-xs text-[var(--text-secondary)] mb-3 leading-relaxed">
                  Workspaces provide sovereign knowledge partitions, isolated vector collections, and dedicated RBAC governance ladders.
                </p>
              </div>

              {createError && (
                <div 
                  className="p-3 rounded-lg text-xs border"
                  style={{
                    backgroundColor: 'var(--red-tint)',
                    color: 'var(--red-text)',
                    borderColor: 'var(--red-tint)'
                  }}
                >
                  {createError}
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-[var(--text-primary)] mb-1.5">
                  Workspace Name <span className="text-[var(--red)]">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Legal & Regulatory Compliance"
                  value={newWsName}
                  onChange={(e) => setNewWsName(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border text-xs focus:outline-none focus:ring-2 focus:ring-[var(--lavender-deep)]"
                  style={{
                    backgroundColor: 'var(--bg-muted)',
                    borderColor: 'var(--border)',
                    color: 'var(--text-primary)'
                  }}
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--text-primary)] mb-1.5">
                  Description
                </label>
                <textarea
                  rows={3}
                  placeholder="e.g. Policy repository, audit trail records, and statutory verification."
                  value={newWsDesc}
                  onChange={(e) => setNewWsDesc(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border text-xs focus:outline-none focus:ring-2 focus:ring-[var(--lavender-deep)]"
                  style={{
                    backgroundColor: 'var(--bg-muted)',
                    borderColor: 'var(--border)',
                    color: 'var(--text-primary)'
                  }}
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--text-primary)] mb-1.5">
                  Organization
                </label>
                <div 
                  className="px-3 py-2 rounded-lg border text-xs text-[var(--text-secondary)] font-medium"
                  style={{
                    backgroundColor: 'var(--bg-muted)',
                    borderColor: 'var(--border)'
                  }}
                >
                  {currentOrg?.name || currentWorkspace?.organization_name || 'Current Organization'}
                </div>
              </div>

              <div className="pt-3 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => { setIsCreating(false); setCreateError(null); }}
                  className="px-3.5 py-1.5 rounded-lg border text-xs font-semibold text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--hover)] transition-colors cursor-pointer"
                  style={{ borderColor: 'var(--border)' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!newWsName.trim() || isSubmitting}
                  className="h-8 px-4 rounded-lg text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50 transition-colors cursor-pointer"
                  style={{
                    backgroundColor: 'var(--accent)',
                    color: 'var(--accent-fg)'
                  }}
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Creating...</span>
                    </>
                  ) : (
                    <>
                      <Plus className="w-3.5 h-3.5" />
                      <span>Create & Open</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        ) : (
          <>
            {/* Search */}
            <div className="p-4 border-b" style={{ borderColor: 'var(--border)' }}>
              <div 
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs"
                style={{
                  backgroundColor: 'var(--bg-muted)',
                  borderColor: 'var(--border)'
                }}
              >
                <Search className="w-3.5 h-3.5 text-[var(--text-muted)]" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Filter workspaces by name or org..."
                  className="bg-transparent w-full text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none"
                />
              </div>
            </div>

            {/* Workspace Groups */}
            <div className="flex-1 overflow-y-auto p-4 space-y-6">
              {Object.keys(filteredGrouped).length === 0 ? (
                <div className="py-12 text-center text-xs text-[var(--text-muted)] space-y-2">
                  <div>No workspaces found matching "{search}".</div>
                  <button
                    onClick={() => { setIsCreating(true); setNewWsName(search); }}
                    className="text-xs font-semibold text-[var(--lavender-deep)] hover:underline"
                  >
                    + Create workspace "{search}"
                  </button>
                </div>
              ) : (
                Object.entries(filteredGrouped).map(([orgName, orgWorkspaces]) => (
                  <div key={orgName} className="space-y-2">
                    <div className="flex items-center justify-between px-1">
                      <span className="sonoma-overline text-[var(--text-muted)]">
                        {orgName}
                      </span>
                      <span className="text-[10px] font-mono text-[var(--text-muted)]">
                        {orgWorkspaces.length} {orgWorkspaces.length === 1 ? 'workspace' : 'workspaces'}
                      </span>
                    </div>

                    <div 
                      className="rounded-xl border overflow-hidden divide-y divide-[var(--border)]"
                      style={{
                        backgroundColor: 'var(--bg-card)',
                        borderColor: 'var(--border)',
                      }}
                    >
                      {orgWorkspaces.map(ws => {
                        const isSelected = currentWorkspace?.id === ws.id;
                        return (
                          <div
                            key={ws.id}
                            onClick={() => {
                              onSelectWorkspace(ws);
                              onClose();
                            }}
                            className="p-3 flex items-center justify-between cursor-pointer transition-colors hover:bg-[var(--hover)]"
                            style={{
                              backgroundColor: isSelected ? 'var(--well-lavender-bg)' : 'transparent',
                            }}
                          >
                            <div className="min-w-0 pr-2">
                              <div className="flex items-center gap-2">
                                <span className="sonoma-row-primary text-[var(--text-primary)] truncate">
                                  {ws.name}
                                </span>
                                {ws.is_default && (
                                  <span className="text-[9px] font-semibold uppercase px-1.5 py-0.2 rounded border text-[var(--text-muted)] bg-[var(--bg-muted)] shrink-0">
                                    Default
                                  </span>
                                )}
                              </div>
                              <div className="flex items-center gap-1.5 mt-1">
                                <span className="text-[10px] font-mono text-[var(--text-muted)] bg-black/5 dark:bg-white/5 px-1.5 py-0.5 rounded border border-[var(--border)] truncate max-w-[240px]" title={`Full UUID: ${ws.id}`}>
                                  UUID: {ws.id}
                                </span>
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    navigator.clipboard.writeText(ws.id);
                                    setCopiedId(ws.id);
                                    setTimeout(() => setCopiedId(null), 1500);
                                  }}
                                  className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--lavender-deep)] hover:bg-black/5 dark:hover:bg-white/10 transition-colors shrink-0"
                                  title="Copy Workspace UUID"
                                >
                                  {copiedId === ws.id ? <Check className="w-3 h-3 text-[var(--sage-deep)]" /> : <Copy className="w-3 h-3" />}
                                </button>
                              </div>
                              <div className="text-[11px] text-[var(--text-secondary)] mt-1 flex items-center gap-2">
                                <span>Role: <strong className="capitalize font-medium text-[var(--text-primary)]">{ws.role || 'Member'}</strong></span>
                                <span>•</span>
                                <span className="truncate">{ws.description || 'Enterprise sovereign partition'}</span>
                              </div>
                            </div>

                            {isSelected ? (
                              <div 
                                className="w-5 h-5 rounded-full flex items-center justify-center shrink-0"
                                style={{
                                  backgroundColor: 'var(--lavender-active)',
                                  color: '#ffffff',
                                }}
                              >
                                <Check className="w-3 h-3 stroke-[3]" />
                              </div>
                            ) : (
                              <ChevronRight className="w-4 h-4 text-[var(--text-muted)] shrink-0" />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))
              )}
            </div>
          </>
        )}

        {/* Footer info */}
        <div 
          className="p-4 border-t bg-[var(--bg-muted)] text-[11px] text-[var(--text-secondary)] flex items-center justify-between shrink-0"
          style={{ borderColor: 'var(--border)' }}
        >
          <div className="flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-[var(--sage-deep)]" />
            <span>Multi-Tenant Sovereign Partitioning</span>
          </div>
          <span className="font-mono text-[10px]">LORE v3.0</span>
        </div>
      </div>
    </div>
  );
};
