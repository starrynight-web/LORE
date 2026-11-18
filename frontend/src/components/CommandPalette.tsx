'use client';

import React, { useState, useEffect, useRef } from 'react';
import { 
  Search, 
  FileText, 
  Layers, 
  Network, 
  Shield, 
  Upload, 
  ArrowRight, 
  Building2, 
  Zap, 
  Check, 
  CornerDownLeft,
  X
} from 'lucide-react';
import { Workspace, SourceDocument } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  workspaces: Workspace[];
  currentWorkspace: Workspace | null;
  documents: SourceDocument[];
  onSelectWorkspace: (ws: Workspace) => void;
  onNavigate: (tab: string) => void;
  onOpenUpload: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  workspaces,
  currentWorkspace,
  documents,
  onSelectWorkspace,
  onNavigate,
  onOpenUpload
}) => {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Actions list
  const actions = [
    { id: 'act-upload', label: 'Upload / Ingest Document', hint: '⌘U', icon: Upload, run: onOpenUpload },
    { id: 'act-rag', label: 'Governed Search & RAG', hint: 'G', icon: Search, run: () => onNavigate('rag') },
    { id: 'act-grid', label: 'Knowledge Grid & RAPTOR Visualizer', hint: 'K', icon: Network, run: () => onNavigate('knowledge_grid') },
    { id: 'act-overview', label: 'Workspace Overview', hint: 'O', icon: Layers, run: () => onNavigate('overview') },
    { id: 'act-docs', label: 'All Documents', hint: 'D', icon: FileText, run: () => onNavigate('documents') },
    { id: 'act-layers', label: '9 Governance Layers', hint: '9', icon: Shield, run: () => onNavigate('governance_layers') },
    { id: 'act-review', label: 'Review Queue & Quarantined Sources', hint: 'R', icon: Shield, run: () => onNavigate('review') },
    { id: 'act-audit', label: 'Audit Ledger & Zero-Knowledge Attestations', hint: 'A', icon: Zap, run: () => onNavigate('audit') },
  ];

  const filteredWorkspaces = workspaces.filter(ws => 
    ws.name.toLowerCase().includes(query.toLowerCase()) || 
    ws.organization_name.toLowerCase().includes(query.toLowerCase())
  );

  const filteredDocuments = documents.filter(doc =>
    doc.title.toLowerCase().includes(query.toLowerCase()) ||
    doc.original_filename.toLowerCase().includes(query.toLowerCase())
  ).slice(0, 5);

  const filteredActions = actions.filter(act =>
    act.label.toLowerCase().includes(query.toLowerCase())
  );

  // Flattened list for keyboard navigation
  type Item = 
    | { type: 'workspace'; item: Workspace }
    | { type: 'document'; item: SourceDocument }
    | { type: 'action'; item: typeof actions[0] };

  const allItems: Item[] = [
    ...filteredWorkspaces.map(w => ({ type: 'workspace' as const, item: w })),
    ...filteredDocuments.map(d => ({ type: 'document' as const, item: d })),
    ...filteredActions.map(a => ({ type: 'action' as const, item: a }))
  ];

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => (prev + 1) % Math.max(1, allItems.length));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => (prev - 1 + allItems.length) % Math.max(1, allItems.length));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const current = allItems[selectedIndex];
      if (!current) return;
      if (current.type === 'workspace') {
        onSelectWorkspace(current.item);
        onClose();
      } else if (current.type === 'document') {
        onNavigate('documents');
        onClose();
      } else if (current.type === 'action') {
        current.item.run();
        onClose();
      }
    }
  };

  if (!isOpen) return null;

  return (
    <div 
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4"
      style={{ backgroundColor: 'var(--modal-overlay)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div 
        className="w-full max-w-[560px] sonoma-card sonoma-elevation overflow-hidden border transition-all animate-in fade-in zoom-in-95 duration-150"
        style={{
          backgroundColor: 'var(--card)',
          borderColor: 'var(--hairline)',
        }}
        onKeyDown={handleKeyDown}
      >
        {/* Search Input Bar */}
        <div 
          className="flex items-center gap-3 px-4 py-3 border-b"
          style={{ borderColor: 'var(--hairline)' }}
        >
          <Search className="w-4 h-4 text-[#86868B] shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command or search workspace, docs..."
            className="flex-1 bg-transparent text-sm text-[var(--text-primary)] placeholder-[#86868B] focus:outline-none"
          />
          <kbd 
            className="px-1.5 py-0.5 text-[10px] font-mono font-medium rounded border text-[#86868B] bg-[var(--inset)] shrink-0"
            style={{ borderColor: 'var(--hairline)' }}
          >
            ESC
          </kbd>
        </div>

        {/* Results Body */}
        <div className="max-h-[380px] overflow-y-auto p-2 space-y-3">
          {allItems.length === 0 ? (
            <div className="py-8 text-center text-xs text-[#86868B]">
              No matching commands or documents found.
            </div>
          ) : (
            <>
              {/* Workspaces Group */}
              {filteredWorkspaces.length > 0 && (
                <div>
                  <div className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-[#86868B]">
                    Workspaces
                  </div>
                  <div className="space-y-0.5">
                    {filteredWorkspaces.map((ws, i) => {
                      const itemIdx = i;
                      const isSelected = selectedIndex === itemIdx;
                      const isCurrent = currentWorkspace?.id === ws.id;
                      return (
                        <div
                          key={ws.id}
                          onClick={() => {
                            onSelectWorkspace(ws);
                            onClose();
                          }}
                          className="flex items-center justify-between px-2.5 py-2 rounded-lg cursor-pointer text-xs transition-colors"
                          style={{
                            backgroundColor: isSelected ? 'var(--hover)' : 'transparent',
                          }}
                        >
                          <div className="flex items-center gap-2.5 min-w-0">
                            <div className="w-6 h-6 rounded-md bg-[#007AFF] text-white flex items-center justify-center shrink-0">
                              <Building2 className="w-3.5 h-3.5" />
                            </div>
                            <div className="truncate">
                              <div className="font-semibold text-[var(--text-primary)] truncate">{ws.name}</div>
                              <div className="text-[11px] text-[#6E6E73] truncate">{ws.organization_name} · {ws.role}</div>
                            </div>
                          </div>
                          {isCurrent ? (
                            <span className="text-[10px] font-medium text-[#007AFF] px-2 py-0.5 rounded-full bg-[rgba(0,122,255,0.08)]">
                              Current
                            </span>
                          ) : (
                            <CornerDownLeft className="w-3 h-3 text-[#86868B] opacity-0 group-hover:opacity-100" />
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Documents Group */}
              {filteredDocuments.length > 0 && (
                <div>
                  <div className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-[#86868B]">
                    Documents
                  </div>
                  <div className="space-y-0.5">
                    {filteredDocuments.map((doc, i) => {
                      const itemIdx = filteredWorkspaces.length + i;
                      const isSelected = selectedIndex === itemIdx;
                      return (
                        <div
                          key={doc.id}
                          onClick={() => {
                            onNavigate('documents');
                            onClose();
                          }}
                          className="flex items-center justify-between px-2.5 py-2 rounded-lg cursor-pointer text-xs transition-colors"
                          style={{
                            backgroundColor: isSelected ? 'var(--hover)' : 'transparent',
                          }}
                        >
                          <div className="flex items-center gap-2.5 min-w-0">
                            <div className="w-6 h-6 rounded-md bg-[#5E5CE6] text-white flex items-center justify-center shrink-0">
                              <FileText className="w-3.5 h-3.5" />
                            </div>
                            <div className="truncate">
                              <div className="font-semibold text-[var(--text-primary)] truncate">{doc.title}</div>
                              <div className="text-[11px] text-[#6E6E73]">
                                Rank {doc.authority_level} · {doc.status} · {doc.page_count} pg
                              </div>
                            </div>
                          </div>
                          <span className="text-[10px] font-mono text-[#86868B]">
                            {doc.document_type || 'doc'}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Actions Group */}
              {filteredActions.length > 0 && (
                <div>
                  <div className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-[#86868B]">
                    Quick Actions
                  </div>
                  <div className="space-y-0.5">
                    {filteredActions.map((act, i) => {
                      const itemIdx = filteredWorkspaces.length + filteredDocuments.length + i;
                      const isSelected = selectedIndex === itemIdx;
                      const Icon = act.icon;
                      return (
                        <div
                          key={act.id}
                          onClick={() => {
                            act.run();
                            onClose();
                          }}
                          className="flex items-center justify-between px-2.5 py-2 rounded-lg cursor-pointer text-xs transition-colors"
                          style={{
                            backgroundColor: isSelected ? 'var(--hover)' : 'transparent',
                          }}
                        >
                          <div className="flex items-center gap-2.5">
                            <div className="w-6 h-6 rounded-md bg-[#007AFF] text-white flex items-center justify-center shrink-0">
                              <Icon className="w-3.5 h-3.5" />
                            </div>
                            <span className="font-semibold text-[var(--text-primary)]">{act.label}</span>
                          </div>
                          <kbd 
                            className="px-1.5 py-0.5 text-[10px] font-mono font-medium rounded border text-[#86868B] bg-[var(--inset)]"
                            style={{ borderColor: 'var(--hairline)' }}
                          >
                            {act.hint}
                          </kbd>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer with Keyboard Hints */}
        <div 
          className="px-4 py-2 bg-[var(--inset)] border-t flex items-center justify-between text-[11px] text-[#86868B]"
          style={{ borderColor: 'var(--hairline)' }}
        >
          <div className="flex items-center gap-3">
            <span><kbd className="font-mono">↑↓</kbd> navigate</span>
            <span><kbd className="font-mono">↵</kbd> select</span>
            <span><kbd className="font-mono">esc</kbd> close</span>
          </div>
          <span className="font-mono text-[10px]">macOS Sonoma System Settings DNA</span>
        </div>
      </div>
    </div>
  );
};

