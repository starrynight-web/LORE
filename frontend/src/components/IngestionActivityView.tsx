'use client';

import React from 'react';
import { 
  Cpu, 
  CheckCircle2, 
  Clock, 
  AlertCircle, 
  RotateCw, 
  FileText, 
  ArrowRight,
  Sparkles,
  Zap
} from 'lucide-react';
import { IngestionJob, api } from '@/lib/api';

interface IngestionActivityViewProps {
  jobs: IngestionJob[];
  onRefresh: () => void;
}

export const IngestionActivityView: React.FC<IngestionActivityViewProps> = ({
  jobs,
  onRefresh
}) => {
  const stages = [
    { id: 'inspection', label: '1. Magic Byte Inspection' },
    { id: 'extraction', label: '2. Text & OCR Extraction' },
    { id: 'normalization', label: '3. Unicode Phonetic Normalization' },
    { id: 'chunking', label: '4. Structure-Aware Chunking' },
    { id: 'embedding', label: '5. Vector Embedding' },
    { id: 'indexing', label: '6. Qdrant & Lexical Indexing' },
  ];

  const handleRetry = async (jobId: string) => {
    try {
      await api.retryJob(jobId);
      onRefresh();
    } catch (err) {
      console.error("Retry failed:", err);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Cpu className="w-5 h-5 text-indigo-400" />
            <span>Ingestion Pipeline Activity</span>
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Asynchronous background workers executing UNBhumi dual-stream OCR, structural normalization, and vector indexing.
          </p>
        </div>
        <button
          onClick={onRefresh}
          className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white px-3.5 py-2 rounded-lg text-xs font-semibold border border-slate-700 transition cursor-pointer"
        >
          <RotateCw className="w-3.5 h-3.5" />
          <span>Refresh Queue</span>
        </button>
      </div>

      {/* Jobs Stream */}
      <div className="space-y-4">
        {jobs.length === 0 ? (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-12 text-center text-slate-500 text-sm">
            No processing jobs recorded in this workspace. Upload a document to start asynchronous extraction.
          </div>
        ) : (
          jobs.map((job) => {
            const isDone = job.status === 'ready';
            const isFailed = job.status === 'failed';
            const isReview = job.status === 'needs_review';
            const isProcessing = !isDone && !isFailed && !isReview;

            return (
              <div 
                key={job.id} 
                className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg space-y-4 hover:border-slate-700 transition"
              >
                {/* Job Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800/80 pb-3">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-indigo-500/10 text-indigo-400 flex items-center justify-center flex-shrink-0">
                      <FileText className="w-4 h-4" />
                    </div>
                    <div>
                      <span className="font-semibold text-white text-sm block">
                        {job.document_title}
                      </span>
                      <span className="text-[11px] font-mono text-slate-400">
                        Job ID: {job.id.substring(0, 16)}... • Type: {job.document_type.toUpperCase()} • Attempt: {job.attempt_count}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {isDone && (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>Ready & Indexed</span>
                      </span>
                    )}
                    {isReview && (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                        <AlertCircle className="w-3.5 h-3.5" />
                        <span>Needs Human Review</span>
                      </span>
                    )}
                    {isProcessing && (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 animate-pulse">
                        <Clock className="w-3.5 h-3.5" />
                        <span className="capitalize">{job.current_stage}...</span>
                      </span>
                    )}
                    {isFailed && (
                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
                          <AlertCircle className="w-3.5 h-3.5" />
                          <span>Pipeline Failed</span>
                        </span>
                        <button
                          onClick={() => handleRetry(job.id)}
                          className="px-2.5 py-1 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-md transition"
                        >
                          Retry
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                {/* State Machine Step Pipeline */}
                <div className="grid grid-cols-2 md:grid-cols-6 gap-2 pt-1">
                  {stages.map((st, idx) => {
                    const isPassed = isDone || (job.stage_timings && `${st.id}_ms` in job.stage_timings);
                    const isCurrent = job.current_stage === st.id && isProcessing;
                    return (
                      <div
                        key={st.id}
                        className={`p-2.5 rounded-lg border text-left text-xs transition ${
                          isPassed
                            ? 'bg-emerald-500/5 border-emerald-500/30 text-emerald-300'
                            : isCurrent
                            ? 'bg-indigo-500/10 border-indigo-500/40 text-indigo-300 animate-pulse ring-1 ring-indigo-500/50'
                            : 'bg-slate-800/30 border-slate-800 text-slate-500'
                        }`}
                      >
                        <div className="font-semibold text-[11px] mb-0.5">{st.label}</div>
                        <div className="text-[10px] font-mono">
                          {isPassed
                            ? `${job.stage_timings?.[`${st.id}_ms`] || 0} ms`
                            : isCurrent
                            ? 'Processing...'
                            : 'Pending'}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Error diagnostics if any */}
                {job.error_message && (
                  <div className="p-3 rounded-lg bg-rose-950/20 border border-rose-800/40 text-rose-300 text-xs font-mono">
                    <b>Failure Diagnostic:</b> {job.error_message}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
