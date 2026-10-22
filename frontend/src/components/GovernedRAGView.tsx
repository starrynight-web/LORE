'use client';

import React, { useState } from 'react';
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
  Shield
} from 'lucide-react';
import { GovernedResult, api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

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
  const [result, setResult] = useState<GovernedResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeModel, setActiveModel] = useState('gpt-oss-120B');
  const [hasGroqKey, setHasGroqKey] = useState(false);
  const [showLayersInspector, setShowLayersInspector] = useState(true);

  React.useEffect(() => {
    if (typeof window !== 'undefined') {
      const k = localStorage.getItem('lore_groq_api_key');
      const m = localStorage.getItem('lore_llm_model') || 'gpt-oss-120B';
      setHasGroqKey(Boolean(k));
      setActiveModel(m);
    }
  }, []);

  React.useEffect(() => {
    if (initialDocumentId) {
      setSelectedDocId(initialDocumentId);
    }
  }, [initialDocumentId]);

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

  const handleExecute = async (textToRun?: string) => {
    const q = textToRun || query;
    if (!q.trim()) return;

    setIsLoading(true);
    setError(null);

    try {
      const docId = selectedDocId === 'all' ? undefined : selectedDocId;
      const res = await api.governedQuery(workspaceId, q, undefined, docId);
      setResult(res);
    } catch (err: any) {
      setError(err.message || 'Error executing governed query.');
    } finally {
      setIsLoading(false);
    }
  };

  const getStateBadge = (state: string, directive: string) => {
    switch (state) {
      case 'supported':
        return (
          <div className="flex items-center gap-2">
            <span 
              className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--success-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--success)',
              }}
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>SUPPORTED</span>
            </span>
            <span 
              className="text-xs font-mono font-semibold px-2 py-0.5 rounded border"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              DIRECTIVE: {directive.toUpperCase()}
            </span>
          </div>
        );
      case 'qualified':
        return (
          <div className="flex items-center gap-2">
            <span 
              className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--warning-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--warning)',
              }}
            >
              <Scale className="w-3.5 h-3.5" />
              <span>QUALIFIED BY GOVERNANCE</span>
            </span>
            <span 
              className="text-xs font-mono font-semibold px-2 py-0.5 rounded border"
              style={{
                backgroundColor: 'var(--warning-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--warning)',
              }}
            >
              DIRECTIVE: {directive.toUpperCase()}
            </span>
          </div>
        );
      case 'insufficient':
        return (
          <div className="flex items-center gap-2">
            <span 
              className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--error-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--error)',
              }}
            >
              <AlertTriangle className="w-3.5 h-3.5" />
              <span>INSUFFICIENT EVIDENCE</span>
            </span>
            <span 
              className="text-xs font-mono font-semibold px-2 py-0.5 rounded border"
              style={{
                backgroundColor: 'var(--error-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--error)',
              }}
            >
              DIRECTIVE: {directive.toUpperCase()}
            </span>
          </div>
        );
      case 'conflicting':
        return (
          <div className="flex items-center gap-2">
            <span 
              className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              <Scale className="w-3.5 h-3.5" />
              <span>CONFLICT DETECTED</span>
            </span>
            <span 
              className="text-xs font-mono font-semibold px-2 py-0.5 rounded border"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-secondary)',
              }}
            >
              DIRECTIVE: {directive.toUpperCase()}
            </span>
          </div>
        );
      default:
        return (
          <div className="flex items-center gap-2">
            <span 
              className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider border"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-secondary)',
              }}
            >
              {state.toUpperCase()}
            </span>
            <span className="text-xs font-mono text-[var(--text-muted)]">
              DIRECTIVE: {directive.toUpperCase()}
            </span>
          </div>
        );
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg sm:text-xl font-extrabold text-[var(--text-primary)] flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-[var(--brand-accent)]" />
            <span>{t('rag.title')}</span>
          </h2>
          <p className="text-xs sm:text-sm text-[var(--text-muted)] mt-1 leading-relaxed">
            {t('rag.subtitle')}
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
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

      {/* Document Context Scope Selector (PDF / Entire Knowledge Base) */}
      <div 
        className="rounded-2xl p-4 sm:p-5 border shadow-sm space-y-3.5 transition-all duration-200"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
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

        <div className="flex flex-col sm:flex-row items-center gap-3">
          <div className="relative w-full">
            <select
              value={selectedDocId}
              onChange={(e) => setSelectedDocId(e.target.value)}
              className="w-full border rounded-xl px-3.5 py-2.5 text-xs sm:text-sm font-semibold focus:outline-none cursor-pointer"
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
              className="px-3.5 py-2.5 rounded-xl text-xs font-semibold border transition cursor-pointer flex-shrink-0 active:scale-95 whitespace-nowrap"
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

      {/* Query Input Box */}
      <div 
        className="rounded-2xl p-4 sm:p-5 border shadow-sm transition-all duration-200"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="flex items-center gap-3">
          <Search className="w-5 h-5 text-[var(--brand-accent)] flex-shrink-0" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleExecute()}
            placeholder={t('rag.input_placeholder')}
            className="w-full bg-transparent focus:outline-none text-xs sm:text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)]"
          />
          <button
            onClick={() => handleExecute()}
            disabled={isLoading || !query.trim()}
            className="p-2.5 rounded-xl font-semibold shadow-sm transition cursor-pointer flex-shrink-0 active:scale-95 disabled:opacity-40"
            style={{
              backgroundColor: 'var(--brand-accent)',
              color: 'var(--cta-text)',
            }}
          >
            <Send className="w-4 h-4" />
          </button>
        </div>

        {/* Suggested Queries */}
        <div 
          className="flex flex-wrap items-center gap-2 mt-4 pt-3 border-t"
          style={{ borderColor: 'var(--border-color)' }}
        >
          <span className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">
            {t('rag.sample_questions')}
          </span>
          {sampleQueries.map((sq, idx) => (
            <button
              key={idx}
              onClick={() => {
                setQuery(sq);
                handleExecute(sq);
              }}
              className="text-xs px-2.5 py-1 rounded-xl border transition cursor-pointer active:scale-95 text-left"
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

      {isLoading && (
        <div className="p-8 text-center space-y-2">
          <div 
            className="w-6 h-6 border-2 border-t-transparent rounded-full animate-spin mx-auto"
            style={{
              borderColor: 'var(--brand-accent)',
              borderTopColor: 'transparent',
            }}
          />
          <div className="text-sm font-bold text-[var(--text-primary)]">{t('rag.searching')}</div>
          <div className="text-xs text-[var(--text-muted)]">
            Evaluating hybrid vectors, checking authority dominance, and testing evidence sufficiency...
          </div>
        </div>
      )}

      {error && (
        <div 
          className="p-4 rounded-xl border text-xs sm:text-sm"
          style={{
            backgroundColor: 'var(--error-bg)',
            borderColor: 'var(--border-color)',
            color: 'var(--error)',
          }}
        >
          {error}
        </div>
      )}

      {/* Result Card */}
      {result && !isLoading && (
        <div 
          className="rounded-2xl p-6 border shadow-sm space-y-6 animate-in fade-in duration-200"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          {/* State & Directive Header */}
          <div 
            className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-4"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <div className="flex items-center gap-2 flex-wrap">
              {getStateBadge(result.state, result.directive)}
              {result.llm_model && (
                <span 
                  className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold border flex items-center gap-1"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--brand-accent)',
                  }}
                >
                  <Cpu className="w-3 h-3 text-[var(--brand-accent)]" />
                  {result.llm_provider === 'groq' ? 'Groq Inference' : 'Internal Engine'}: {result.llm_model}
                </span>
              )}
            </div>

            <div className="text-xs font-mono text-[var(--text-muted)] flex items-center gap-2">
              <span className="hidden sm:inline">Trace: {result.trace_id}</span>
              <span 
                className="px-2 py-0.5 rounded-full text-[10px] font-semibold border flex items-center gap-1"
                style={{
                  backgroundColor: 'var(--accent-light)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--brand-accent)',
                }}
              >
                <ShieldCheck className="w-3 h-3" />
                Anti-Hallucination Verified
              </span>
            </div>
          </div>

          {/* Scoped Context Banner */}
          {selectedDocId !== 'all' && selectedDocObj ? (
            <div 
              className="p-3 rounded-xl border flex items-center justify-between text-xs font-semibold"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              <div className="flex items-center gap-2 truncate">
                <FileText className="w-4 h-4 shrink-0" />
                <span className="truncate">
                  {language === 'bn' ? 'শুধুমাত্র এই নথির নির্যাস থেকে উত্তর প্রদান করা হয়েছে:' : 'Answer strictly synthesized from extracted context of:'} <strong>{selectedDocObj.title}</strong>
                </span>
              </div>
              <span className="text-[10px] font-mono font-bold shrink-0 hidden sm:inline px-2 py-0.5 rounded bg-[var(--bg-surface)] border border-[var(--border-color)]">
                Zero Extrapolation
              </span>
            </div>
          ) : (
            <div 
              className="p-3 rounded-xl border flex items-center justify-between text-xs font-semibold"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-secondary)',
              }}
            >
              <div className="flex items-center gap-2 truncate">
                <Sparkles className="w-4 h-4 text-[var(--brand-accent)] shrink-0" />
                <span className="truncate">
                  {language === 'bn' ? 'হাইব্রিড অনুসন্ধান: কিউড্রান্ট ডেন্স ভেক্টর + লেক্সিক্যাল বিএম২৫ + আরআরএফ রি-র‍্যাঙ্কিং' : 'Hybrid Retrieval: Qdrant Dense Vectors + Lexical BM25 + Reciprocal Rank Fusion Reranker'}
                </span>
              </div>
              <span className="text-[10px] font-mono font-bold shrink-0 hidden sm:inline px-2 py-0.5 rounded bg-[var(--bg-surface)] border border-[var(--border-color)]">
                Multi-Document Knowledge Base
              </span>
            </div>
          )}

          {/* Answer Narrative */}
          <div 
            className="p-4 rounded-xl border leading-relaxed text-xs sm:text-sm whitespace-pre-line shadow-sm"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-primary)',
            }}
          >
            <div className="font-bold text-xs uppercase tracking-wider text-[var(--brand-accent)] mb-1">
              {t('rag.governed_answer')}
            </div>
            {result.answer}
          </div>

          {/* Missing Evidence Section */}
          {result.evidence_missing && result.evidence_missing.length > 0 && (
            <div 
              className="p-4 rounded-xl border space-y-2"
              style={{
                backgroundColor: 'var(--error-bg)',
                borderColor: 'var(--border-color)',
              }}
            >
              <div className="text-xs font-bold text-[var(--error)] uppercase tracking-wider flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" />
                <span>Mandatory Evidence Deficit (LORE L3)</span>
              </div>
              <div className="space-y-1.5 pt-1">
                {result.evidence_missing.map((me, idx) => (
                  <div key={idx} className="text-xs flex items-start gap-2 text-[var(--text-primary)]">
                    <span className="font-mono font-bold text-[var(--error)]">• [{me.requirement}]:</span>
                    <span>{me.description}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Resolved Conflicts Section */}
          {result.conflicts_resolved && result.conflicts_resolved.length > 0 && (
            <div 
              className="p-4 rounded-xl border space-y-2"
              style={{
                backgroundColor: 'var(--warning-bg)',
                borderColor: 'var(--border-color)',
              }}
            >
              <div className="text-xs font-bold text-[var(--warning)] uppercase tracking-wider flex items-center gap-2">
                <Scale className="w-4 h-4" />
                <span>Source Conflict Resolved (LORE L6 Authority Dominance)</span>
              </div>
              <div className="space-y-1 pt-1 text-xs text-[var(--text-primary)]">
                {result.conflicts_resolved.map((cr, idx) => (
                  <div key={idx}>
                    <p className="font-semibold">{cr.resolution}: {cr.note}</p>
                    <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
                      Subordinate claim overridden: &quot;{cr.informal_claim}&quot;
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* L4 Scoped Exceptions Section */}
          {result.exceptions_applied && result.exceptions_applied.length > 0 && (
            <div 
              className="p-4 rounded-xl border space-y-2"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
              }}
            >
              <div className="text-xs font-bold text-[var(--brand-accent)] uppercase tracking-wider flex items-center gap-2">
                <Key className="w-4 h-4 text-[var(--accent-parrot)]" />
                <span>L4 Scoped Exception Override Active ({result.exceptions_applied.length})</span>
              </div>
              <div className="space-y-2 pt-1">
                {result.exceptions_applied.map((exc, idx) => (
                  <div 
                    key={idx} 
                    className="p-2.5 rounded-lg border text-xs space-y-1" 
                    style={{ backgroundColor: 'var(--bg-surface)', borderColor: 'var(--border-color)' }}
                  >
                    <div className="flex items-center justify-between font-bold">
                      <span className="text-[var(--text-primary)]">{exc.name} ({exc.rule_code})</span>
                      <span 
                        className="px-2 py-0.5 rounded text-[10px] font-mono uppercase border"
                        style={{
                          backgroundColor: 'var(--accent-light)',
                          borderColor: 'var(--border-color)',
                          color: 'var(--brand-accent)',
                        }}
                      >
                        Scope: {exc.scope_type} = {exc.scope_value}
                      </span>
                    </div>
                    <p className="text-[var(--text-secondary)] leading-relaxed">{exc.justification}</p>
                    {exc.override_state && (
                      <div className="text-[10px] font-mono text-[var(--text-muted)]">
                        Governed state override: <strong className="text-[var(--brand-accent)]">{exc.override_state}</strong> (approved by {exc.approved_by || 'Admin'})
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* L5 Temporal Validity Notice */}
          {result.layers_breakdown?.l5_temporal?.temporal_notes && result.layers_breakdown.l5_temporal.temporal_notes.length > 0 && (
            <div 
              className="p-3.5 rounded-xl border flex items-center justify-between text-xs"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--warning)',
              }}
            >
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 shrink-0" />
                <span>{result.layers_breakdown.l5_temporal.temporal_notes.join(' · ')}</span>
              </div>
              <span 
                className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border"
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-muted)',
                }}
              >
                L5 Temporal Gate
              </span>
            </div>
          )}

          {/* 9-Layer Enterprise Governance Stack Inspector */}
          {result.layers_breakdown && (
            <div 
              className="rounded-xl border overflow-hidden transition-all duration-200"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
              }}
            >
              <button
                type="button"
                onClick={() => setShowLayersInspector(!showLayersInspector)}
                className="w-full px-4 py-3 flex items-center justify-between text-left cursor-pointer transition hover:bg-[var(--accent-light)]"
              >
                <div className="flex items-center gap-2.5">
                  <Layers className="w-4 h-4 text-[var(--brand-accent)]" />
                  <span className="text-xs font-bold uppercase tracking-wider text-[var(--text-primary)]">
                    9-Layer Enterprise Governance Stack Audit (LORE v3.0 §3, §4, §10)
                  </span>
                  <span 
                    className="px-2 py-0.5 rounded-full text-[10px] font-bold border"
                    style={{
                      backgroundColor: 'var(--success-bg)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--success)',
                    }}
                  >
                    9/9 Active
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono text-[var(--text-muted)]">
                    Latency: {Object.values(result.layers_breakdown.l0_observability?.timings_ms || {}).reduce((a, b) => a + b, 0).toFixed(2)}ms
                  </span>
                  {showLayersInspector ? <ChevronUp className="w-4 h-4 text-[var(--text-muted)]" /> : <ChevronDown className="w-4 h-4 text-[var(--text-muted)]" />}
                </div>
              </button>

              {showLayersInspector && (
                <div className="p-4 border-t space-y-3" style={{ borderColor: 'var(--border-color)' }}>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                    {/* L7 */}
                    <div className="p-3 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L7: PERMISSION</span>
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${result.layers_breakdown.l7_permission.status === 'passed' ? 'text-[var(--success)] bg-[var(--success-bg)]' : 'text-[var(--error)] bg-[var(--error-bg)]'}`}>
                          {result.layers_breakdown.l7_permission.status.toUpperCase()}
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-secondary)]">Zero-leakage clearance & pre-retrieval role filtering</p>
                      <div className="text-[10px] font-mono text-[var(--text-muted)]">Latency: {(result.layers_breakdown.l0_observability?.timings_ms?.l7_permission_ms || 0).toFixed(3)}ms</div>
                    </div>

                    {/* L1 */}
                    <div className="p-3 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L1: DECISION INTEL</span>
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded text-[var(--brand-accent)] bg-[var(--accent-light)]">
                          {(result.layers_breakdown.l1_decision_intelligence.risk || 'NORMAL').toUpperCase()} RISK
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-secondary)]">Type: <strong>{result.layers_breakdown.l1_decision_intelligence.decision_type}</strong></p>
                      <div className="text-[10px] font-mono text-[var(--text-muted)]">Escalates: {result.layers_breakdown.l1_decision_intelligence.escalation}</div>
                    </div>

                    {/* L6 */}
                    <div className="p-3 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L6: AUTHORITY</span>
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded text-[var(--text-secondary)] bg-[var(--bg-surface-soft)]">
                          {result.layers_breakdown.l6_authority.conflicts_count} Resolved
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-secondary)]">7-rank authority ladder precedence & tie arbitration</p>
                      <div className="text-[10px] font-mono text-[var(--text-muted)]">Unresolved tie: {result.layers_breakdown.l6_authority.unresolved_tie ? 'YES' : 'NO'}</div>
                    </div>

                    {/* L5 */}
                    <div className="p-3 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L5: TEMPORAL</span>
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${result.layers_breakdown.l5_temporal.stale_data ? 'text-[var(--warning)] bg-[var(--warning-bg)]' : 'text-[var(--success)] bg-[var(--success-bg)]'}`}>
                          {result.layers_breakdown.l5_temporal.stale_data ? 'STALE DETECTED' : 'FRESH'}
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-secondary)]">Effective date bounds & document aging verification</p>
                      <div className="text-[10px] font-mono text-[var(--text-muted)]">Latency: {(result.layers_breakdown.l0_observability?.timings_ms?.l5_temporal_ms || 0).toFixed(3)}ms</div>
                    </div>

                    {/* L4 */}
                    <div className="p-3 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L4: SCOPED EXCEPTION</span>
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded text-[var(--brand-accent)] bg-[var(--accent-light)]">
                          {result.layers_breakdown.l4_exceptions.applied_count} Matched
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-secondary)]">Tenant/project/vendor scoped rule overrides</p>
                      <div className="text-[10px] font-mono text-[var(--text-muted)]">Latency: {(result.layers_breakdown.l0_observability?.timings_ms?.l4_exception_ms || 0).toFixed(3)}ms</div>
                    </div>

                    {/* L3 */}
                    <div className="p-3 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L3: SUFFICIENCY</span>
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${result.layers_breakdown.l3_sufficiency.is_sufficient ? 'text-[var(--success)] bg-[var(--success-bg)]' : 'text-[var(--error)] bg-[var(--error-bg)]'}`}>
                          {result.layers_breakdown.l3_sufficiency.is_sufficient ? 'SATISFIED' : 'DEFICIT'}
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-secondary)]">Mandatory checklist evidence completeness</p>
                      <div className="text-[10px] font-mono text-[var(--text-muted)]">Missing items: {result.layers_breakdown.l3_sufficiency.missing_count}</div>
                    </div>

                    {/* L2 */}
                    <div className="p-3 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L2: ANSWER STATE</span>
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded text-[var(--brand-accent)] bg-[var(--accent-light)]">
                          {result.layers_breakdown.l2_answer_state.final_state.toUpperCase()}
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-secondary)]">Strict 9-state precedence ladder arbitration</p>
                      <div className="text-[10px] font-mono text-[var(--text-muted)]">Directive: {result.layers_breakdown.l2_answer_state.directive}</div>
                    </div>

                    {/* L0 */}
                    <div className="p-3 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L0: OBSERVABILITY</span>
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded text-[var(--success)] bg-[var(--success-bg)]">
                          RECORDED
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-secondary)]">Decision ledger entry, audit trace & token metering</p>
                      <div className="text-[10px] font-mono text-[var(--text-muted)]">Tokens: {result.token_count}</div>
                    </div>

                    {/* Core Retrieval */}
                    <div className="p-3 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">CORE RETRIEVAL</span>
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded text-[var(--brand-accent)] bg-[var(--accent-light)]">
                          HYBRID RRF
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-secondary)]">Qdrant dense vectors + BM25 lexical + Context Reranker</p>
                      <div className="text-[10px] font-mono text-[var(--text-muted)]">Evidence chunks: {result.evidence_found?.length || 0}</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Citations List */}
          <div className="space-y-3 pt-2">
            <div className="text-xs font-bold text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-2">
              <Quote className="w-4 h-4 text-[var(--brand-accent)]" />
              <span>{t('rag.evidence_citations')} ({result.citations.length})</span>
            </div>

            <div className="grid grid-cols-1 gap-2.5">
              {result.citations.map((cit, idx) => (
                <div 
                  key={cit.citation_id || idx}
                  className="p-3.5 rounded-xl border space-y-1.5 text-xs transition"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="flex items-center justify-between font-semibold text-[var(--text-primary)]">
                    <div className="flex items-center gap-2">
                      <FileText className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                      <span>{cit.document_title}</span>
                      <span 
                        className="text-[10px] px-1.5 py-0.5 rounded border"
                        style={{
                          backgroundColor: 'var(--bg-surface)',
                          borderColor: 'var(--border-color)',
                          color: 'var(--text-muted)',
                        }}
                      >
                        Page {cit.page_number}
                      </span>
                    </div>
                    <span 
                      className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded border"
                      style={{
                        backgroundColor: 'var(--accent-light)',
                        borderColor: 'var(--border-color)',
                        color: 'var(--brand-accent)',
                      }}
                    >
                      Authority Rank {cit.authority_level}
                    </span>
                  </div>
                  <div 
                    className="text-xs italic pl-2 border-l-2 leading-relaxed text-[var(--text-secondary)]"
                    style={{ borderColor: 'var(--brand-accent)' }}
                  >
                    &quot;{cit.passage}&quot;
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
