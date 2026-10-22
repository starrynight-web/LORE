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
  Cpu
} from 'lucide-react';
import { GovernedResult, api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface GovernedRAGViewProps {
  workspaceId: string;
}

export const GovernedRAGView: React.FC<GovernedRAGViewProps> = ({
  workspaceId
}) => {
  const { t, language } = useI18n();
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<GovernedResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeModel, setActiveModel] = useState('gpt-oss-120B');
  const [hasGroqKey, setHasGroqKey] = useState(false);

  React.useEffect(() => {
    if (typeof window !== 'undefined') {
      const k = localStorage.getItem('lore_groq_api_key');
      const m = localStorage.getItem('lore_llm_model') || 'gpt-oss-120B';
      setHasGroqKey(Boolean(k));
      setActiveModel(m);
    }
  }, []);

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
      const res = await api.governedQuery(workspaceId, q);
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
