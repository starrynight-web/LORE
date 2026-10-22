'use client';

import React, { useState } from 'react';
import { 
  Search, 
  Send, 
  Shield, 
  AlertTriangle, 
  CheckCircle2, 
  FileText, 
  Sparkles, 
  Layers, 
  Quote, 
  ExternalLink,
  ChevronRight,
  Info,
  Scale
} from 'lucide-react';
import { GovernedResult, api } from '@/lib/api';

interface GovernedRAGViewProps {
  workspaceId: string;
}

export const GovernedRAGView: React.FC<GovernedRAGViewProps> = ({
  workspaceId
}) => {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<GovernedResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sampleQueries = [
    "Can engineering use CloudBox for sensitive customer data?",
    "What conditions are required for third-party cloud vendors?",
    "What is our data sovereignty and residency policy?",
    "What are the requirements for ISO 27001 vendor compliance?"
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
            <span className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>SUPPORTED</span>
            </span>
            <span className="text-xs font-mono text-emerald-400 font-semibold bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
              DIRECTIVE: {directive.toUpperCase()}
            </span>
          </div>
        );
      case 'qualified':
        return (
          <div className="flex items-center gap-2">
            <span className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-amber-500/20 text-amber-400 border border-amber-500/30 flex items-center gap-1.5">
              <Scale className="w-3.5 h-3.5" />
              <span>QUALIFIED BY GOVERNANCE</span>
            </span>
            <span className="text-xs font-mono text-amber-400 font-semibold bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">
              DIRECTIVE: {directive.toUpperCase()}
            </span>
          </div>
        );
      case 'insufficient':
        return (
          <div className="flex items-center gap-2">
            <span className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-rose-500/20 text-rose-400 border border-rose-500/30 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" />
              <span>INSUFFICIENT EVIDENCE</span>
            </span>
            <span className="text-xs font-mono text-rose-400 font-semibold bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20">
              DIRECTIVE: {directive.toUpperCase()}
            </span>
          </div>
        );
      case 'conflicting':
        return (
          <div className="flex items-center gap-2">
            <span className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-purple-500/20 text-purple-400 border border-purple-500/30 flex items-center gap-1.5">
              <Scale className="w-3.5 h-3.5" />
              <span>CONFLICT DETECTED</span>
            </span>
            <span className="text-xs font-mono text-purple-400 font-semibold bg-purple-500/10 px-2 py-0.5 rounded border border-purple-500/20">
              DIRECTIVE: {directive.toUpperCase()}
            </span>
          </div>
        );
      default:
        return (
          <div className="flex items-center gap-2">
            <span className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-slate-800 text-slate-300">
              {state.toUpperCase()}
            </span>
            <span className="text-xs font-mono text-slate-400">
              DIRECTIVE: {directive.toUpperCase()}
            </span>
          </div>
        );
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-indigo-400" />
          <span>Governed Knowledge RAG & Decision Intelligence</span>
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Ask questions against enterprise documents. LORE verifies source authority, checks evidence completeness, and explicitly refuses to guess if evidence is insufficient.
        </p>
      </div>

      {/* Query Input Box */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl focus-within:border-indigo-500/60 transition">
        <div className="flex items-center gap-3">
          <Search className="w-5 h-5 text-indigo-400 flex-shrink-0" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleExecute()}
            placeholder="Ask a question or enter a decision inquiry..."
            className="w-full bg-transparent focus:outline-none text-white text-base placeholder:text-slate-500"
          />
          <button
            onClick={() => handleExecute()}
            disabled={isLoading || !query.trim()}
            className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white p-2.5 rounded-xl font-semibold shadow-md shadow-indigo-600/30 transition cursor-pointer flex-shrink-0"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>

        {/* Suggested Queries */}
        <div className="flex flex-wrap items-center gap-2 mt-4 pt-3 border-t border-slate-800">
          <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
            Benchmark Queries:
          </span>
          {sampleQueries.map((sq, idx) => (
            <button
              key={idx}
              onClick={() => {
                setQuery(sq);
                handleExecute(sq);
              }}
              className="text-xs bg-slate-800 hover:bg-slate-700 hover:text-white text-slate-300 px-2.5 py-1 rounded-md border border-slate-700/60 transition cursor-pointer"
            >
              {sq}
            </button>
          ))}
        </div>
      </div>

      {isLoading && (
        <div className="p-8 text-center text-slate-400 space-y-2">
          <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto" />
          <div className="text-sm font-semibold text-white">Running 10-Stage Retrieval Pipeline...</div>
          <div className="text-xs text-slate-500">
            Evaluating hybrid vectors, checking authority dominance, and testing evidence sufficiency...
          </div>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm">
          {error}
        </div>
      )}

      {/* Result Card */}
      {result && !isLoading && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
          {/* State & Directive Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
            {getStateBadge(result.state, result.directive)}
            <div className="text-xs font-mono text-slate-400">
              Decision ID: <span className="text-slate-200">{result.decision_id}</span> • Trace: {result.trace_id}
            </div>
          </div>

          {/* Answer Narrative */}
          <div className="p-4 rounded-xl bg-slate-950/40 border border-slate-800/80 leading-relaxed text-slate-200 text-sm whitespace-pre-line">
            {result.answer}
          </div>

          {/* Missing Evidence Section */}
          {result.evidence_missing && result.evidence_missing.length > 0 && (
            <div className="p-4 rounded-xl bg-rose-950/20 border border-rose-800/40 space-y-2">
              <div className="text-xs font-bold text-rose-400 uppercase tracking-wider flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" />
                <span>Mandatory Evidence Deficit (LORE L3)</span>
              </div>
              <div className="space-y-1.5 pt-1">
                {result.evidence_missing.map((me, idx) => (
                  <div key={idx} className="text-xs text-rose-200 flex items-start gap-2">
                    <span className="font-mono font-bold text-rose-400">• [{me.requirement}]:</span>
                    <span>{me.description}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Resolved Conflicts Section */}
          {result.conflicts_resolved && result.conflicts_resolved.length > 0 && (
            <div className="p-4 rounded-xl bg-amber-950/20 border border-amber-800/40 space-y-2">
              <div className="text-xs font-bold text-amber-400 uppercase tracking-wider flex items-center gap-2">
                <Scale className="w-4 h-4" />
                <span>Source Conflict Resolved (LORE L6 Authority Dominance)</span>
              </div>
              <div className="space-y-1 pt-1 text-xs text-amber-200">
                {result.conflicts_resolved.map((cr, idx) => (
                  <div key={idx}>
                    <p className="font-semibold">{cr.resolution}: {cr.note}</p>
                    <p className="text-amber-300/80 text-[11px] mt-0.5">
                      Subordinate claim overridden: "{cr.informal_claim}"
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Citations List */}
          <div className="space-y-3 pt-2">
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-2">
              <Quote className="w-4 h-4 text-indigo-400" />
              <span>Verified Citations ({result.citations.length})</span>
            </div>

            <div className="grid grid-cols-1 gap-2.5">
              {result.citations.map((cit, idx) => (
                <div 
                  key={cit.citation_id || idx}
                  className="p-3.5 rounded-xl bg-slate-800/50 border border-slate-700/50 space-y-1.5 text-xs"
                >
                  <div className="flex items-center justify-between text-slate-300 font-semibold">
                    <div className="flex items-center gap-2">
                      <FileText className="w-3.5 h-3.5 text-indigo-400" />
                      <span>{cit.document_title}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300">
                        Page {cit.page_number}
                      </span>
                    </div>
                    <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                      Authority Rank {cit.authority_level}
                    </span>
                  </div>
                  <div className="text-slate-400 text-xs italic pl-2 border-l-2 border-indigo-500/50 leading-relaxed">
                    "{cit.passage}"
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
