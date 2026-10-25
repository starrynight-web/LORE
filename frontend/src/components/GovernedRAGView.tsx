'use client';

import React, { useState, useEffect, useRef } from 'react';
import { 
  Search, 
  Send, 
  AlertTriangle, 
  CheckCircle2, 
  FileText, 
  Sparkles, 
  Quote, 
  Scale,
  Zap,
  ShieldCheck, 
  Cpu, 
  Filter, 
  Check, 
  Layers, 
  ShieldAlert, 
  Clock, 
  Key, 
  FileCheck, 
  Activity, 
  ChevronDown, 
  ChevronUp, 
  Shield,
  MessageSquare,
  Plus,
  PanelLeftOpen,
  PanelLeftClose,
  Edit3,
  RotateCcw,
  X
} from 'lucide-react';
import { 
  GovernedResult, 
  api, 
  ConversationSummary, 
  ConversationDetail, 
  ChatMessage 
} from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { ConversationHistoryPanel } from './chat/ConversationHistoryPanel';
import { GovernedMessageCard } from './chat/GovernedMessageCard';

interface GovernedRAGViewProps {
  workspaceId: string;
  documents?: any[];
  initialDocumentId?: string;
}

export const GovernedRAGView: React.FC<GovernedRAGViewProps> = ({
  workspaceId,
  documents = [],
  initialDocumentId
}) => {
  const { t, language } = useI18n();
  const [query, setQuery] = useState('');
  const [selectedDocId, setSelectedDocId] = useState<string>(initialDocumentId || 'all');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeModel, setActiveModel] = useState('gpt-oss-120B');
  const [hasGroqKey, setHasGroqKey] = useState(false);

  // Persistent Conversation History State
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [activeConversation, setActiveConversation] = useState<ConversationDetail | null>(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [historySearch, setHistorySearch] = useState('');
  const [isHistoryOpen, setIsHistoryOpen] = useState(true);
  const [isMobileHistoryOpen, setIsMobileHistoryOpen] = useState(false);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editingTitleText, setEditingTitleText] = useState('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const searchDebounceRef = useRef<NodeJS.Timeout | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const k = localStorage.getItem('lore_groq_api_key');
      const m = localStorage.getItem('lore_llm_model') || 'gpt-oss-120B';
      setHasGroqKey(Boolean(k));
      setActiveModel(m);
    }
  }, []);

  useEffect(() => {
    if (initialDocumentId) {
      setSelectedDocId(initialDocumentId);
    }
  }, [initialDocumentId]);

  // Load conversations on workspace change
  useEffect(() => {
    if (workspaceId) {
      loadConversations();
    }
  }, [workspaceId]);

  // Auto-resize textarea to fit full paragraphs
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const scrollH = textareaRef.current.scrollHeight;
      textareaRef.current.style.height = `${Math.min(Math.max(scrollH, 38), 240)}px`;
    }
  }, [query]);

  // Scroll to bottom when messages update
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [activeConversation?.messages, isLoading]);

  const loadConversations = async (search?: string) => {
    setIsLoadingHistory(true);
    try {
      if (typeof api?.getConversations === 'function') {
        const list = await api.getConversations(workspaceId, search);
        setConversations(list);
      } else {
        const token = typeof window !== 'undefined' ? localStorage.getItem('lore_token') : null;
        let url = `http://localhost:8000/api/v1/decisions/conversations/?workspace=${workspaceId}`;
        if (search && search.trim()) url += `&search=${encodeURIComponent(search.trim())}`;
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Token ${token}`;
        const res = await fetch(url, { headers });
        if (res.ok) {
          const data = await res.json();
          setConversations(Array.isArray(data) ? data : data.results || []);
        }
      }
    } catch (err: any) {
      console.error('Failed to load conversations:', err);
    } finally {
      setIsLoadingHistory(false);
    }
  };

  const handleSearchHistory = (search: string) => {
    setHistorySearch(search);
    if (searchDebounceRef.current) {
      clearTimeout(searchDebounceRef.current);
    }
    searchDebounceRef.current = setTimeout(() => {
      loadConversations(search);
    }, 250);
  };

  const handleSelectConversation = async (id: string) => {
    if (id === activeConversationId && activeConversation) {
      setIsMobileHistoryOpen(false);
      return;
    }
    setIsLoadingHistory(true);
    setError(null);
    try {
      const detail = await api.getConversation(id);
      setActiveConversationId(id);
      setActiveConversation(detail);
      if (detail.document_id) {
        setSelectedDocId(detail.document_id);
      }
      setIsMobileHistoryOpen(false);
    } catch (err: any) {
      setError(err.message || 'Failed to load conversation details.');
    } finally {
      setIsLoadingHistory(false);
    }
  };

  const handleNewConversation = () => {
    setActiveConversationId(null);
    setActiveConversation(null);
    setError(null);
    setQuery('');
    setIsMobileHistoryOpen(false);
  };

  const handleRenameConversation = async (id: string, newTitle: string) => {
    try {
      await api.renameConversation(id, newTitle);
      setConversations(prev => prev.map(c => c.id === id ? { ...c, title: newTitle } : c));
      if (activeConversation && activeConversation.id === id) {
        setActiveConversation(prev => prev ? { ...prev, title: newTitle } : null);
      }
      setIsEditingTitle(false);
    } catch (err: any) {
      setError(err.message || 'Failed to rename conversation.');
    }
  };

  const handleDeleteConversation = async (id: string) => {
    try {
      await api.deleteConversation(id);
      setConversations(prev => prev.filter(c => c.id !== id));
      if (activeConversationId === id) {
        setActiveConversationId(null);
        setActiveConversation(null);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to delete conversation.');
    }
  };

  const handleSaveActiveTitle = async () => {
    if (!activeConversationId || !editingTitleText.trim()) return;
    await handleRenameConversation(activeConversationId, editingTitleText.trim());
  };

  const selectedDocObj = documents.find((d: any) => d.id === selectedDocId);

  const sampleQueries = language === 'bn' ? [
    "উক্ত সাফ কবলা দলিলে সম্পত্তির তফসিল এবং সিএস খতিয়ান নম্বর কত?",
    "সম্পাদনের পক্ষগণ কারা এবং সাফ কবলা মূল্যের পরিমাণ কত?",
    "দলিলে কোনো দায়বদ্ধতা বা স্বত্বাধিকারের শর্ত উল্লেখ আছে কি?",
    "ক্লাউড স্টোরেজ ও তৃতীয় পক্ষের সেবাদাতা ব্যবহারের আইনি শর্ত কী?"
  ] : [
    "What is the schedule of property and CS khatian number in the deed?",
    "Who are the executing parties and what is the consideration amount?",
    "Are there any encumbrances, easements, or caveats registered?",
    "What are the compliance requirements for third-party cloud vendors?"
  ];

  // Submit Turn to Governed RAG Pipeline
  const handleExecute = async (textToRun?: string) => {
    const q = textToRun || query;
    if (!q.trim() || isLoading) return;

    setIsLoading(true);
    setError(null);
    setQuery('');

    const clientMsgId = `client_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    const docId = selectedDocId === 'all' ? undefined : selectedDocId;

    try {
      if (activeConversationId) {
        // Multi-turn continuation on existing conversation
        const optimisticUserMsg: ChatMessage = {
          id: clientMsgId,
          conversation: activeConversationId,
          role: 'user',
          content: q,
          sequence_number: (activeConversation?.messages.length || 0) + 1,
          status: 'completed',
          created_at: new Date().toISOString()
        };

        setActiveConversation(prev => prev ? {
          ...prev,
          messages: [...prev.messages, optimisticUserMsg]
        } : null);

        const res = await api.sendConversationMessage(activeConversationId, q, {
          clientMessageId: clientMsgId,
          documentId: docId
        });

        setActiveConversation(prev => {
          if (!prev) return null;
          // Replace optimistic user msg with canonical backend msg, plus append assistant msg
          const filtered = prev.messages.filter(m => m.id !== clientMsgId);
          return {
            ...prev,
            title: res.conversation_title || prev.title,
            messages: [...filtered, res.user_message, res.assistant_message]
          };
        });

        // Refresh list metadata
        loadConversations(historySearch);

      } else {
        // Turn 1: Auto-creates a new conversation on backend with deterministic title
        const res = await api.governedQuery(
          workspaceId,
          q,
          undefined,
          docId,
          undefined,
          undefined,
          undefined,
          clientMsgId
        );

        if (res.conversation_id) {
          setActiveConversationId(res.conversation_id);
          // Fetch full conversation with persisted turns
          const detail = await api.getConversation(res.conversation_id);
          setActiveConversation(detail);
          loadConversations();
        }
      }
    } catch (err: any) {
      console.error('Governed turn execution failed:', err);
      setError(err.message || 'Error executing governed query.');

      // If active conversation, append failed turn indicator
      if (activeConversationId) {
        const failedUserMsg: ChatMessage = {
          id: clientMsgId,
          conversation: activeConversationId,
          role: 'user',
          content: q,
          sequence_number: (activeConversation?.messages.length || 0) + 1,
          status: 'completed',
          created_at: new Date().toISOString()
        };
        const failedAsstMsg: ChatMessage = {
          id: `err_${Date.now()}`,
          conversation: activeConversationId,
          role: 'assistant',
          content: 'Governed query execution failed.',
          sequence_number: (activeConversation?.messages.length || 0) + 2,
          status: 'failed',
          error_message: err.message || 'Error communicating with retrieval or governance model.',
          created_at: new Date().toISOString()
        };
        setActiveConversation(prev => prev ? {
          ...prev,
          messages: [...prev.messages.filter(m => m.id !== clientMsgId), failedUserMsg, failedAsstMsg]
        } : null);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const renderQueryInput = (isSticky: boolean = false) => (
    <div 
      className={`rounded-2xl p-3.5 sm:p-4 border transition-all duration-200 focus-within:ring-2 focus-within:ring-[var(--brand-accent)] focus-within:border-[var(--brand-accent)] shadow-sm hover:shadow-md ${
        isSticky 
          ? 'sticky bottom-4 z-10 mt-4 backdrop-blur-md' 
          : 'w-full shadow-xs'
      }`}
      style={{
        backgroundColor: 'var(--bg-surface)',
        borderColor: 'var(--border-color)',
      }}
    >
      <div className="flex items-start gap-3">
        <Search className="w-5 h-5 text-[var(--brand-accent)] flex-shrink-0 mt-2" />
        <textarea
          id="lore-chat-query-input"
          ref={textareaRef}
          rows={1}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              if (!isLoading && query.trim()) {
                handleExecute();
              }
            }
          }}
          placeholder={
            activeConversation 
              ? (language === 'bn' ? 'এই কথোপকথনে সম্পূরক প্রশ্ন করুন...' : 'Ask follow-up question in this conversation (context bounded)...')
              : (language === 'bn' ? 'নথি বা দলিলের ভিত্তিতে প্রশ্ন জিজ্ঞাসা করুন...' : t('rag.input_placeholder', 'Ask a question across policy documents or scanned deeds...'))
          }
          style={{ outline: 'none', border: 'none', boxShadow: 'none', resize: 'none' }}
          className="w-full bg-transparent border-0 outline-none ring-0 focus:outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0 text-xs sm:text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] py-1.5 leading-relaxed break-words whitespace-pre-wrap overflow-y-auto min-h-[38px] max-h-[240px]"
        />
        <button
          id="lore-chat-send-btn"
          onClick={() => handleExecute()}
          disabled={isLoading || !query.trim()}
          className="p-2.5 rounded-xl font-semibold shadow-sm transition cursor-pointer flex-shrink-0 active:scale-95 disabled:opacity-40 self-end mb-0.5"
          style={{
            backgroundColor: 'var(--brand-accent)',
            color: 'var(--cta-text)',
          }}
          title="Send inquiry"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>

      {/* Keyboard Hint */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between text-[10px] text-[var(--text-muted)] font-mono mt-2 pt-2 border-t border-[var(--border-color)] gap-1">
        <span>Press <strong className="text-[var(--text-primary)]">Enter ↵</strong> to submit · <strong className="text-[var(--text-primary)]">Shift+Enter</strong> for newline</span>
        <span>All turns persisted with zero-extrapolation citations</span>
      </div>
    </div>
  );

  return (
    <div className="space-y-4 max-w-6xl mx-auto">
      {/* Top Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg sm:text-xl font-extrabold text-[var(--text-primary)] flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-[var(--brand-accent)]" />
            <span>{t('rag.title', 'Governed Search & RAG')}</span>
          </h2>
          <p className="text-xs sm:text-sm text-[var(--text-muted)] mt-1 leading-relaxed">
            Persistent, citation-verified conversational RAG with strict 9-state governance arbitration.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Mobile History Toggle */}
          <button
            onClick={() => setIsMobileHistoryOpen(true)}
            className="sm:hidden px-3 py-1.5 rounded-xl text-xs font-bold border flex items-center gap-1.5 bg-[var(--bg-surface)] border-[var(--border-color)] text-[var(--text-primary)]"
          >
            <Clock className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
            <span>History ({conversations.length})</span>
          </button>

          {hasGroqKey ? (
            <span 
              className="px-2.5 py-1 rounded-full text-[11px] font-semibold border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              <Zap className="w-3 h-3 text-[var(--brand-accent)]" />
              <span>Groq: {activeModel}</span>
            </span>
          ) : (
            <span 
              className="px-2.5 py-1 rounded-full text-[11px] font-semibold border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-muted)',
              }}
            >
              <ShieldCheck className="w-3 h-3 text-[var(--brand-accent)]" />
              <span>Deterministic Anti-Hallucination Engine</span>
            </span>
          )}

          <span 
            className="px-2.5 py-1 rounded-full text-[11px] font-semibold border flex items-center gap-1.5"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-primary)',
            }}
          >
            <CheckCircle2 className="w-3 h-3 text-[var(--success)]" />
            <span>Hybrid Reranker Active</span>
          </span>
        </div>
      </div>

      {/* Main Grid: Left History Panel + Right Chat Stream */}
      <div className="flex items-start gap-4">
        {/* Desktop History Panel */}
        <div className="hidden sm:block">
          <ConversationHistoryPanel
            workspaceId={workspaceId}
            conversations={conversations}
            activeConversationId={activeConversationId}
            isLoading={isLoadingHistory}
            searchQuery={historySearch}
            onSearchChange={handleSearchHistory}
            onSelectConversation={handleSelectConversation}
            onNewConversation={handleNewConversation}
            onRenameConversation={handleRenameConversation}
            onDeleteConversation={handleDeleteConversation}
            isOpen={isHistoryOpen}
            onToggleOpen={() => setIsHistoryOpen(!isHistoryOpen)}
            isMobile={false}
          />
        </div>

        {/* Mobile History Panel Drawer */}
        <ConversationHistoryPanel
          workspaceId={workspaceId}
          conversations={conversations}
          activeConversationId={activeConversationId}
          isLoading={isLoadingHistory}
          searchQuery={historySearch}
          onSearchChange={handleSearchHistory}
          onSelectConversation={handleSelectConversation}
          onNewConversation={handleNewConversation}
          onRenameConversation={handleRenameConversation}
          onDeleteConversation={handleDeleteConversation}
          isOpen={isMobileHistoryOpen}
          onToggleOpen={() => setIsMobileHistoryOpen(!isMobileHistoryOpen)}
          isMobile={true}
        />

        {/* Main Conversation Stream & Input Area */}
        <div className="flex-1 min-w-0 space-y-4">
          {/* Active Conversation Top Banner */}
          <div 
            className="p-3.5 rounded-2xl border shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3 transition-all"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
            }}
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <MessageSquare className="w-4 h-4 text-[var(--brand-accent)] shrink-0" />
              {activeConversation ? (
                isEditingTitle ? (
                  <div className="flex items-center gap-1.5">
                    <input
                      type="text"
                      autoFocus
                      value={editingTitleText}
                      onChange={(e) => setEditingTitleText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleSaveActiveTitle();
                        if (e.key === 'Escape') setIsEditingTitle(false);
                      }}
                      className="px-2.5 py-1 rounded-lg border text-xs sm:text-sm font-bold bg-[var(--bg-surface-soft)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--brand-accent)]"
                      style={{ borderColor: 'var(--border-color)' }}
                    />
                    <button
                      onClick={handleSaveActiveTitle}
                      className="p-1.5 rounded-lg bg-[var(--brand-accent)] text-[var(--cta-text)]"
                      title="Save"
                    >
                      <Check className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => setIsEditingTitle(false)}
                      className="p-1.5 rounded-lg border bg-[var(--bg-surface-soft)] text-[var(--text-muted)]"
                      style={{ borderColor: 'var(--border-color)' }}
                      title="Cancel"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 truncate">
                    <span className="font-extrabold text-sm sm:text-base text-[var(--text-primary)] truncate">
                      {activeConversation.title}
                    </span>
                    <button
                      onClick={() => {
                        setEditingTitleText(activeConversation.title);
                        setIsEditingTitle(true);
                      }}
                      className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--text-primary)] transition"
                      title="Rename conversation"
                    >
                      <Edit3 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )
              ) : (
                <div className="flex items-center gap-2">
                  <span className="font-extrabold text-sm sm:text-base text-[var(--text-primary)]">
                    New Governed Inquiry
                  </span>
                  <span className="text-[11px] font-mono text-[var(--text-muted)] hidden sm:inline">
                    (Auto-persists with citations)
                  </span>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              {activeConversation && (
                <button
                  onClick={handleNewConversation}
                  className="px-3 py-1.5 rounded-xl text-xs font-bold border flex items-center gap-1.5 transition active:scale-95 cursor-pointer"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--text-primary)',
                  }}
                >
                  <Plus className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                  <span>Start New</span>
                </button>
              )}
            </div>
          </div>

          {/* Document Context Scope Selector */}
          <div 
            className="rounded-2xl p-3.5 sm:p-4 border shadow-xs space-y-3 transition-all duration-200"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
            }}
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
              <div className="flex items-center gap-2">
                <Filter className="w-4 h-4 text-[var(--brand-accent)]" />
                <span className="text-xs font-bold text-[var(--text-primary)] uppercase tracking-wider">
                  {language === 'bn' ? 'নথির প্রাসঙ্গিক পরিধি (Context Scope)' : 'Document Context Scope'}
                </span>
              </div>

              <span 
                className="text-[11px] font-semibold px-2.5 py-1 rounded-full border flex items-center gap-1.5"
                style={{
                  backgroundColor: selectedDocId !== 'all' ? 'var(--accent-light)' : 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: selectedDocId !== 'all' ? 'var(--brand-accent)' : 'var(--text-secondary)',
                }}
              >
                <ShieldCheck className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                <span>
                  {selectedDocId !== 'all' 
                    ? (language === 'bn' ? 'শুধুমাত্র এই পিডিএফ-এর ভিত্তিতে উত্তর দেবে • জিরো হ্যালুসিনেশন' : `Strictly Scoped to PDF: ${selectedDocObj?.title || 'Selected Document'} • Zero Hallucination`)
                    : (language === 'bn' ? 'হাইব্রিড সার্চ ও রি-র‍্যাঙ্কিং (সমস্ত জ্ঞানভাণ্ডার)' : 'Hybrid Search & Reranking across Entire Knowledge Base')}
                </span>
              </span>
            </div>

            <div className="flex flex-col sm:flex-row items-center gap-2.5">
              <div className="relative w-full">
                <select
                  value={selectedDocId}
                  onChange={(e) => setSelectedDocId(e.target.value)}
                  className="w-full border rounded-xl px-3.5 py-2 text-xs sm:text-sm font-semibold focus:outline-none cursor-pointer"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    borderColor: 'var(--input-border)',
                    color: 'var(--text-primary)',
                  }}
                >
                  <option value="all">
                    🌐 {language === 'bn' ? 'সম্পূর্ণ ওয়ার্কস্পেস (সমস্ত পিডিএফ ও নথি — হাইব্রিড ভেক্টর + লেক্সিক্যাল রি-র‍্যাঙ্কার)' : 'Entire Workspace (All PDFs & Docs — Hybrid Qdrant Vector + Lexical RRF)'}
                  </option>
                  {documents && documents.map((doc: any) => (
                    <option key={doc.id} value={doc.id}>
                      📄 [PDF] {doc.title} ({doc.page_count || 1} pg • Auth Rank {doc.authority_level || 3} • Status: {doc.status})
                    </option>
                  ))}
                </select>
              </div>

              {selectedDocId !== 'all' && (
                <button
                  onClick={() => setSelectedDocId('all')}
                  className="px-3 py-2 rounded-xl text-xs font-semibold border transition cursor-pointer flex-shrink-0 active:scale-95 whitespace-nowrap"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--text-secondary)',
                  }}
                >
                  {language === 'bn' ? 'সকল নথিতে রিসেট' : 'Reset to All Docs'}
                </button>
              )}
            </div>
          </div>

          {/* Chat Messages Stream or Welcome Hero */}
          <div className="min-h-[280px] space-y-4">
            {(!activeConversation || activeConversation.messages.length === 0) ? (
              /* Welcome Hero State when starting a fresh inquiry */
              <div 
                className="p-6 sm:p-8 rounded-2xl border text-center space-y-6 shadow-xs"
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  borderColor: 'var(--border-color)',
                }}
              >
                <div 
                  className="w-12 h-12 rounded-2xl border flex items-center justify-center mx-auto shadow-xs"
                  style={{
                    backgroundColor: 'var(--accent-light)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <ShieldCheck className="w-6 h-6 text-[var(--brand-accent)]" />
                </div>
                <div className="space-y-1.5 max-w-lg mx-auto">
                  <h3 className="font-extrabold text-base sm:text-lg text-[var(--text-primary)]">
                    Ask Governed Questions with Proof
                  </h3>
                  <p className="text-xs sm:text-sm text-[var(--text-secondary)] leading-relaxed">
                    Submit any compliance question, policy inquiry, or legal deed verification. LORE arbitrates contradictory sources, verifies authority dominance, and provides immutable citations.
                  </p>
                </div>

                {/* Integrated Query Box right in the center */}
                <div className="max-w-2xl mx-auto text-left">
                  {renderQueryInput(false)}
                </div>

                {/* In-Flight Query Spinner for Turn 1 */}
                {isLoading && (
                  <div 
                    className="p-6 rounded-2xl border text-center space-y-2 animate-in fade-in max-w-2xl mx-auto"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                    }}
                  >
                    <div 
                      className="w-6 h-6 border-2 border-t-transparent rounded-full animate-spin mx-auto"
                      style={{
                        borderColor: 'var(--brand-accent)',
                        borderTopColor: 'transparent',
                      }}
                    />
                    <div className="text-sm font-bold text-[var(--text-primary)]">
                      {t('rag.searching', 'Evaluating Governed RAG Pipeline...')}
                    </div>
                    <div className="text-xs text-[var(--text-muted)] max-w-md mx-auto">
                      Arbitrating 9-state precedence ladder, checking document authority dominance, and verifying citations...
                    </div>
                  </div>
                )}

                {/* Error Banner for Turn 1 */}
                {error && (
                  <div 
                    className="p-4 rounded-xl border text-xs sm:text-sm flex items-center justify-between gap-3 max-w-2xl mx-auto text-left"
                    style={{
                      backgroundColor: 'var(--error-bg)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--error)',
                    }}
                  >
                    <span>{error}</span>
                    <button
                      onClick={() => setError(null)}
                      className="p-1 rounded text-[var(--error)] hover:opacity-80"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                )}

                {/* Suggested Queries */}
                <div className="pt-1 max-w-2xl mx-auto space-y-2.5">
                  <div className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">
                    {t('rag.sample_questions', 'Recommended Inquiries')}
                  </div>
                  <div className="flex flex-wrap items-center justify-center gap-2">
                    {sampleQueries.map((sq, idx) => (
                      <button
                        key={idx}
                        onClick={() => {
                          setQuery(sq);
                          handleExecute(sq);
                        }}
                        className="text-xs px-3 py-1.5 rounded-xl border transition cursor-pointer active:scale-95 text-left hover:border-[var(--brand-accent)] hover:text-[var(--text-primary)]"
                        style={{
                          backgroundColor: 'var(--bg-surface-soft)',
                          borderColor: 'var(--border-color)',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        {sq}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              /* Chat Messages Stream */
              <div className="space-y-4 pb-2">
                {activeConversation.messages.map((msg, idx) => (
                  <GovernedMessageCard
                    key={msg.id || idx}
                    message={msg}
                    onRetry={(text) => handleExecute(text)}
                    language={language}
                  />
                ))}

                {/* In-Flight Query Spinner for follow-up turns */}
                {isLoading && (
                  <div 
                    className="p-6 rounded-2xl border text-center space-y-2 animate-in fade-in"
                    style={{
                      backgroundColor: 'var(--bg-surface)',
                      borderColor: 'var(--border-color)',
                    }}
                  >
                    <div 
                      className="w-6 h-6 border-2 border-t-transparent rounded-full animate-spin mx-auto"
                      style={{
                        borderColor: 'var(--brand-accent)',
                        borderTopColor: 'transparent',
                      }}
                    />
                    <div className="text-sm font-bold text-[var(--text-primary)]">
                      {t('rag.searching', 'Evaluating Governed RAG Pipeline...')}
                    </div>
                    <div className="text-xs text-[var(--text-muted)] max-w-md mx-auto">
                      Arbitrating 9-state precedence ladder, checking document authority dominance, and verifying citations...
                    </div>
                  </div>
                )}

                {/* Error Banner for follow-up turns */}
                {error && (
                  <div 
                    className="p-4 rounded-xl border text-xs sm:text-sm flex items-center justify-between gap-3"
                    style={{
                      backgroundColor: 'var(--error-bg)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--error)',
                    }}
                  >
                    <span>{error}</span>
                    <button
                      onClick={() => setError(null)}
                      className="p-1 rounded text-[var(--error)] hover:opacity-80"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                )}

                <div ref={messagesEndRef} />

                {/* Sticky Query Input for follow-up turns */}
                {renderQueryInput(true)}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
