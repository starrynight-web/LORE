'use client';

import React from 'react';
import { 
  FileText, 
  Cpu, 
  AlertTriangle, 
  Search, 
  ShieldCheck, 
  CheckCircle2, 
  Upload,
  ArrowRight,
  TrendingUp,
  Layers,
  Sparkles
} from 'lucide-react';
import { SourceDocument, IngestionJob } from '@/lib/api';

interface OverviewViewProps {
  documents: SourceDocument[];
  jobs: IngestionJob[];
  onOpenUpload: () => void;
  onNavigate: (tab: string) => void;
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  documents,
  jobs,
  onOpenUpload,
  onNavigate
}) => {
  const readyDocs = documents.filter(d => d.status === 'ready').length;
  const reviewDocs = documents.filter(d => d.status === 'needs_review' || d.status === 'quarantined').length;
  const activeJobs = jobs.filter(j => j.status !== 'ready' && j.status !== 'failed').length;

  return (
    <div className="space-y-8">
      {/* Hero Welcome */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-indigo-900/60 via-slate-900 to-slate-900 p-8 border border-indigo-500/20 shadow-2xl">
        <div className="relative z-10 max-w-2xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 mb-4">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Northstar Digital Workspace • Active</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight leading-tight">
            Enterprise Knowledge Workspace & Governed RAG
          </h1>
          <p className="mt-2 text-sm text-slate-300 leading-relaxed">
            Welcome to LORE Enterprise. Your unstructured documents, scanned deeds, and contracts are normalized through dual-stream OCR, structure-aware chunking, and deterministic governance.
          </p>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              onClick={onOpenUpload}
              className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-xl text-sm font-semibold shadow-lg shadow-indigo-600/30 transition cursor-pointer"
            >
              <Upload className="w-4 h-4" />
              <span>Upload Document</span>
            </button>
            <button
              onClick={() => onNavigate('rag')}
              className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded-xl text-sm font-semibold border border-slate-700 transition cursor-pointer"
            >
              <Search className="w-4 h-4 text-indigo-400" />
              <span>Ask Governed RAG</span>
            </button>
          </div>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
          <div className="flex items-center justify-between text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">
            <span>Total Documents</span>
            <FileText className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="text-2xl font-bold text-white">{documents.length}</div>
          <div className="text-xs text-slate-400 mt-1 flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            <span>{readyDocs} Ready & Searchable</span>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
          <div className="flex items-center justify-between text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">
            <span>Processing Jobs</span>
            <Cpu className="w-4 h-4 text-blue-400" />
          </div>
          <div className="text-2xl font-bold text-white">{jobs.length}</div>
          <div className="text-xs text-slate-400 mt-1">
            {activeJobs > 0 ? (
              <span className="text-blue-400 animate-pulse font-semibold">{activeJobs} active workers</span>
            ) : (
              <span className="text-slate-400">Pipeline idle / ready</span>
            )}
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
          <div className="flex items-center justify-between text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">
            <span>Review Queue</span>
            <AlertTriangle className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-white">{reviewDocs}</div>
          <div className="text-xs text-slate-400 mt-1">
            {reviewDocs > 0 ? (
              <span className="text-amber-400 font-semibold">Requires human verification</span>
            ) : (
              <span className="text-emerald-400">All sources verified</span>
            )}
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
          <div className="flex items-center justify-between text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">
            <span>Governance State</span>
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-base font-bold text-emerald-400">9-State Active</div>
          <div className="text-xs text-slate-400 mt-1">
            Explicit Refusal & Evidence Gating
          </div>
        </div>
      </div>

      {/* Quick Access Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Recent Ingested Documents */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <FileText className="w-4 h-4 text-indigo-400" />
              <span>Recent Knowledge Documents</span>
            </h3>
            <button
              onClick={() => onNavigate('documents')}
              className="text-xs text-indigo-400 hover:text-indigo-300 font-semibold flex items-center gap-1"
            >
              <span>View All</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="space-y-2">
            {documents.slice(0, 4).map((doc) => (
              <div
                key={doc.id}
                onClick={() => onNavigate('documents')}
                className="p-3 rounded-lg bg-slate-800/40 hover:bg-slate-800 border border-slate-700/40 flex items-center justify-between cursor-pointer transition"
              >
                <div>
                  <div className="text-xs font-semibold text-white truncate max-w-xs">{doc.title}</div>
                  <div className="text-[11px] text-slate-400 mt-0.5">
                    Authority Rank: {doc.authority_level} • Status: {doc.status}
                  </div>
                </div>
                <span className="text-xs font-mono text-indigo-400">
                  {doc.page_count} pg
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Governance Architecture Preview */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Layers className="w-4 h-4 text-indigo-400" />
              <span>LORE 9-Layer Architecture Status</span>
            </h3>
            <span className="text-xs text-emerald-400 font-mono">100% OPERATIONAL</span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="p-2.5 rounded-lg bg-slate-800/40 border border-slate-700/40 flex justify-between items-center">
              <span className="text-slate-300">L7 Permission Layer (Multi-Tenant RBAC)</span>
              <span className="text-emerald-400 font-semibold">Active</span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-800/40 border border-slate-700/40 flex justify-between items-center">
              <span className="text-slate-300">L6 Authority Ladder (Config Ranks 1 to 7)</span>
              <span className="text-emerald-400 font-semibold">Active</span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-800/40 border border-slate-700/40 flex justify-between items-center">
              <span className="text-slate-300">L3 Evidence Sufficiency (Deficit Checking)</span>
              <span className="text-emerald-400 font-semibold">Active</span>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-800/40 border border-slate-700/40 flex justify-between items-center">
              <span className="text-slate-300">L2 Answer-State Machine (9 States + Directives)</span>
              <span className="text-emerald-400 font-semibold">Active</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
