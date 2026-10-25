'use client';

import React, { useState } from 'react';
import { 
  MessageSquare, 
  Plus, 
  Search, 
  Trash2, 
  Edit3, 
  Check, 
  X, 
  Clock, 
  FileText, 
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  AlertCircle
} from 'lucide-react';
import { ConversationSummary } from '@/lib/api';

interface ConversationHistoryPanelProps {
  workspaceId: string;
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  isLoading: boolean;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  onRenameConversation: (id: string, newTitle: string) => Promise<void>;
  onDeleteConversation: (id: string) => Promise<void>;
  isOpen: boolean;
  onToggleOpen: () => void;
  isMobile?: boolean;
}

export const ConversationHistoryPanel: React.FC<ConversationHistoryPanelProps> = ({
  workspaceId,
  conversations,
  activeConversationId,
  isLoading,
  searchQuery,
  onSearchChange,
  onSelectConversation,
  onNewConversation,
  onRenameConversation,
  onDeleteConversation,
  isOpen,
  onToggleOpen,
  isMobile = false
}) => {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [isSubmittingRename, setIsSubmittingRename] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const startRename = (conv: ConversationSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(conv.id);
    setEditTitle(conv.title);
    setConfirmDeleteId(null);
  };

  const handleSaveRename = async (id: string, e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!editTitle.trim() || isSubmittingRename) return;
    setIsSubmittingRename(true);
    try {
      await onRenameConversation(id, editTitle.trim());
      setEditingId(null);
    } catch (err) {
      console.error('Rename failed:', err);
    } finally {
      setIsSubmittingRename(false);
    }
  };

  const cancelRename = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingId(null);
    setEditTitle('');
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirmDeleteId !== id) {
      setConfirmDeleteId(id);
      return;
    }
    setIsDeleting(true);
    try {
      await onDeleteConversation(id);
      setConfirmDeleteId(null);
    } catch (err) {
      console.error('Delete failed:', err);
    } finally {
      setIsDeleting(false);
    }
  };

  const formatRelativeTime = (isoString?: string) => {
    if (!isoString) return '';
    try {
      const date = new Date(isoString);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / (1000 * 60));
      const diffHours = Math.floor(diffMins / 60);
      const diffDays = Math.floor(diffHours / 24);

      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays === 1) return 'Yesterday';
      if (diffDays < 7) return `${diffDays}d ago`;
      return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch (e) {
      return '';
    }
  };

  // Content of panel
  const panelContent = (
    <div 
      className="flex flex-col h-full rounded-2xl border overflow-hidden shadow-sm transition-all duration-200"
      style={{
        backgroundColor: 'var(--bg-surface)',
        borderColor: 'var(--border-color)',
      }}
    >
      {/* Top Header */}
      <div 
        className="p-3.5 border-b flex items-center justify-between gap-2"
        style={{ borderColor: 'var(--border-color)' }}
      >
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-[var(--brand-accent)]" />
          <span className="text-xs font-bold text-[var(--text-primary)] uppercase tracking-wider">
            Conversations ({conversations.length})
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            id="lore-new-conversation-btn"
            onClick={onNewConversation}
            className="px-2.5 py-1.5 rounded-xl text-xs font-bold border flex items-center gap-1.5 transition active:scale-95 cursor-pointer shadow-xs"
            style={{
              backgroundColor: 'var(--brand-accent)',
              borderColor: 'var(--brand-accent)',
              color: 'var(--cta-text)',
            }}
            title="Start a new governed inquiry conversation"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New</span>
          </button>

          <button
            onClick={onToggleOpen}
            className="p-1.5 rounded-lg border text-[var(--text-muted)] hover:text-[var(--text-primary)] transition"
            style={{
              borderColor: 'var(--border-color)',
              backgroundColor: 'var(--bg-surface-soft)'
            }}
            title="Collapse history"
          >
            <PanelLeftClose className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Search Input */}
      <div className="p-3 border-b" style={{ borderColor: 'var(--border-color)' }}>
        <div 
          className="flex items-center gap-2 px-3 py-1.5 rounded-xl border text-xs"
          style={{
            backgroundColor: 'var(--bg-surface-soft)',
            borderColor: 'var(--border-color)',
          }}
        >
          <Search className="w-3.5 h-3.5 text-[var(--text-muted)] shrink-0" />
          <input
            id="lore-search-conversations-input"
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search history or queries..."
            className="w-full bg-transparent focus:outline-none text-xs text-[var(--text-primary)] placeholder-[var(--text-muted)]"
          />
          {searchQuery && (
            <button
              onClick={() => onSearchChange('')}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1.5 scrollbar-thin">
        {isLoading && conversations.length === 0 ? (
          <div className="p-6 text-center space-y-2 text-[var(--text-muted)]">
            <div 
              className="w-5 h-5 border-2 border-t-transparent rounded-full animate-spin mx-auto"
              style={{
                borderColor: 'var(--brand-accent)',
                borderTopColor: 'transparent',
              }}
            />
            <div className="text-xs">Loading conversations...</div>
          </div>
        ) : conversations.length === 0 ? (
          <div className="p-6 text-center space-y-2 text-[var(--text-muted)]">
            <MessageSquare className="w-8 h-8 mx-auto opacity-30 text-[var(--brand-accent)]" />
            <div className="text-xs font-semibold text-[var(--text-secondary)]">
              {searchQuery ? 'No matching conversations' : 'No previous conversations'}
            </div>
            <p className="text-[11px] leading-relaxed">
              {searchQuery ? 'Try a different search term.' : 'Every question you ask is saved with full governance audit trails.'}
            </p>
          </div>
        ) : (
          conversations.map((conv) => {
            const isActive = conv.id === activeConversationId;
            const isEditing = conv.id === editingId;
            const isConfirming = conv.id === confirmDeleteId;

            return (
              <div
                key={conv.id}
                onClick={() => !isEditing && onSelectConversation(conv.id)}
                className={`group relative p-2.5 rounded-xl border text-xs cursor-pointer transition-all duration-150 flex flex-col gap-1.5 ${
                  isActive ? 'shadow-xs' : 'hover:border-[var(--brand-accent)]/40'
                }`}
                style={{
                  backgroundColor: isActive ? 'var(--accent-light)' : 'var(--bg-surface-soft)',
                  borderColor: isActive ? 'var(--brand-accent)' : 'var(--border-color)',
                }}
              >
                {/* Title or Edit Input */}
                {isEditing ? (
                  <form 
                    onSubmit={(e) => handleSaveRename(conv.id, e)}
                    onClick={(e) => e.stopPropagation()}
                    className="flex items-center gap-1.5"
                  >
                    <input
                      type="text"
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Escape') cancelRename(e as any);
                      }}
                      className="w-full px-2 py-1 rounded border text-xs bg-[var(--bg-surface)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--brand-accent)]"
                      style={{ borderColor: 'var(--border-color)' }}
                    />
                    <button
                      type="submit"
                      disabled={isSubmittingRename}
                      className="p-1 rounded bg-[var(--brand-accent)] text-[var(--cta-text)] hover:opacity-90 transition shrink-0"
                      title="Save title"
                    >
                      <Check className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={cancelRename}
                      className="p-1 rounded border bg-[var(--bg-surface)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition shrink-0"
                      style={{ borderColor: 'var(--border-color)' }}
                      title="Cancel"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </form>
                ) : (
                  <div className="flex items-start justify-between gap-1.5">
                    <span 
                      className={`font-semibold line-clamp-2 leading-snug ${
                        isActive ? 'text-[var(--brand-accent)]' : 'text-[var(--text-primary)]'
                      }`}
                      title={conv.title}
                    >
                      {conv.title}
                    </span>

                    {/* Action buttons (Rename, Delete) */}
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition shrink-0">
                      <button
                        onClick={(e) => startRename(conv, e)}
                        className="p-1 rounded hover:bg-[var(--bg-surface)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition"
                        title="Rename conversation"
                      >
                        <Edit3 className="w-3 h-3" />
                      </button>

                      <button
                        onClick={(e) => handleDelete(conv.id, e)}
                        className={`p-1 rounded transition ${
                          isConfirming 
                            ? 'bg-[var(--error-bg)] text-[var(--error)] border border-[var(--error)]' 
                            : 'hover:bg-[var(--bg-surface)] text-[var(--text-muted)] hover:text-[var(--error)]'
                        }`}
                        title={isConfirming ? 'Click again to confirm delete' : 'Delete conversation'}
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                )}

                {/* Confirm Delete Warning Banner */}
                {isConfirming && (
                  <div 
                    onClick={(e) => e.stopPropagation()}
                    className="p-1.5 rounded-lg border flex items-center justify-between text-[11px] animate-in fade-in"
                    style={{
                      backgroundColor: 'var(--error-bg)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--error)',
                    }}
                  >
                    <span className="flex items-center gap-1 font-semibold">
                      <AlertCircle className="w-3 h-3" />
                      Delete conversation?
                    </span>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={(e) => handleDelete(conv.id, e)}
                        disabled={isDeleting}
                        className="px-1.5 py-0.5 rounded font-bold uppercase text-[10px] bg-[var(--error)] text-white hover:opacity-90"
                      >
                        Yes
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDeleteId(null);
                        }}
                        className="px-1.5 py-0.5 rounded text-[10px] border border-[var(--border-color)] bg-[var(--bg-surface)] text-[var(--text-muted)]"
                      >
                        No
                      </button>
                    </div>
                  </div>
                )}

                {/* Metadata Row: Time & Message Count */}
                <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)] font-mono pt-0.5">
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3 opacity-60" />
                    <span>{formatRelativeTime(conv.last_activity_at || conv.updated_at)}</span>
                  </span>

                  <div className="flex items-center gap-1.5">
                    {conv.document_id && (
                      <span 
                        className="flex items-center gap-0.5 px-1.5 py-0.2 rounded border bg-[var(--bg-surface)]"
                        style={{ borderColor: 'var(--border-color)' }}
                        title="Scoped to single document"
                      >
                        <FileText className="w-2.5 h-2.5 text-[var(--brand-accent)]" />
                        <span>PDF</span>
                      </span>
                    )}

                    <span 
                      className="px-1.5 py-0.2 rounded border"
                      style={{
                        backgroundColor: 'var(--bg-surface)',
                        borderColor: 'var(--border-color)',
                      }}
                    >
                      {conv.message_count} {conv.message_count === 1 ? 'msg' : 'msgs'}
                    </span>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );

  // If mobile drawer
  if (isMobile) {
    if (!isOpen) return null;
    return (
      <div className="fixed inset-0 z-50 flex">
        <div 
          className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity" 
          onClick={onToggleOpen} 
        />
        <div className="relative w-80 max-w-[85vw] h-full z-10 p-3 flex flex-col">
          {panelContent}
        </div>
      </div>
    );
  }

  // Desktop view
  if (!isOpen) {
    return (
      <div className="shrink-0 flex items-start">
        <button
          id="lore-open-history-sidebar-btn"
          onClick={onToggleOpen}
          className="p-2.5 rounded-xl border flex items-center gap-2 text-xs font-bold transition shadow-xs cursor-pointer active:scale-95"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
            color: 'var(--text-primary)',
          }}
          title="Open Conversation History"
        >
          <PanelLeftOpen className="w-4 h-4 text-[var(--brand-accent)]" />
          <span className="hidden xl:inline">History</span>
          <span 
            className="text-[10px] font-mono px-1.5 py-0.2 rounded-full border"
            style={{
              backgroundColor: 'var(--accent-light)',
              borderColor: 'var(--border-color)',
              color: 'var(--brand-accent)',
            }}
          >
            {conversations.length}
          </span>
        </button>
      </div>
    );
  }

  return (
    <aside className="w-72 xl:w-80 shrink-0 h-[640px] sticky top-4">
      {panelContent}
    </aside>
  );
};
