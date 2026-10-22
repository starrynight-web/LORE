'use client';

import React from 'react';
import { 
  Cpu, 
  CheckCircle2, 
  Clock, 
  AlertCircle, 
  RotateCw, 
  FileText
} from 'lucide-react';
import { IngestionJob, api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface IngestionActivityViewProps {
  jobs: IngestionJob[];
  onRefresh: () => void;
}

export const IngestionActivityView: React.FC<IngestionActivityViewProps> = ({
  jobs,
  onRefresh
}) => {
  const { t } = useI18n();

  const stages = [
    { id: 'inspection', label: '1. Magic Byte' },
    { id: 'extraction', label: '2. Text & OCR' },
    { id: 'normalization', label: '3. Normalization' },
    { id: 'chunking', label: '4. Chunking' },
    { id: 'embedding', label: '5. Vector Embedding' },
    { id: 'indexing', label: '6. Qdrant Index' },
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
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg sm:text-xl font-extrabold flex items-center gap-2 text-[var(--text-primary)]">
            <Cpu className="w-5 h-5 text-[var(--brand-accent)]" />
            <span>{t('activity.title')}</span>
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            {t('activity.subtitle')}
          </p>
        </div>
        <button
          onClick={onRefresh}
          className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold border transition cursor-pointer active:scale-95"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
            color: 'var(--text-primary)',
          }}
        >
          <RotateCw className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
          <span>{t('common.refresh')}</span>
        </button>
      </div>

      {/* Jobs Stream */}
      <div className="space-y-4">
        {jobs.length === 0 ? (
          <div 
            className="rounded-2xl p-12 text-center text-sm border shadow-sm"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-muted)',
            }}
          >
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
                className="rounded-2xl p-5 border shadow-sm space-y-4 transition-all duration-200"
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  borderColor: 'var(--border-color)',
                }}
              >
                {/* Job Header */}
                <div 
                  className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b pb-3"
                  style={{ borderColor: 'var(--border-color)' }}
                >
                  <div className="flex items-center gap-3">
                    <div 
                      className="w-9 h-9 rounded-xl border flex items-center justify-center flex-shrink-0"
                      style={{
                        backgroundColor: 'var(--accent-light)',
                        borderColor: 'var(--border-color)',
                        color: 'var(--brand-accent)',
                      }}
                    >
                      <FileText className="w-4 h-4" />
                    </div>
                    <div>
                      <span className="font-bold text-sm block text-[var(--text-primary)]">
                        {job.document_title}
                      </span>
                      <span className="text-[11px] font-mono text-[var(--text-muted)]">
                        Job ID: {job.id.substring(0, 16)}... • Type: {job.document_type.toUpperCase()} • Attempt: {job.attempt_count}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {isDone && (
                      <span 
                        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border"
                        style={{
                          backgroundColor: 'var(--success-bg)',
                          borderColor: 'var(--border-color)',
                          color: 'var(--success)',
                        }}
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>Ready & Indexed</span>
                      </span>
                    )}
                    {isReview && (
                      <span 
                        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border"
                        style={{
                          backgroundColor: 'var(--warning-bg)',
                          borderColor: 'var(--border-color)',
                          color: 'var(--warning)',
                        }}
                      >
                        <AlertCircle className="w-3.5 h-3.5" />
                        <span>Needs Human Review</span>
                      </span>
                    )}
                    {isProcessing && (
                      <span 
                        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border animate-pulse"
                        style={{
                          backgroundColor: 'var(--accent-light)',
                          borderColor: 'var(--border-color)',
                          color: 'var(--brand-accent)',
                        }}
                      >
                        <Clock className="w-3.5 h-3.5" />
                        <span className="capitalize">{job.current_stage}...</span>
                      </span>
                    )}
                    {isFailed && (
                      <div className="flex items-center gap-2">
                        <span 
                          className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border"
                          style={{
                            backgroundColor: 'var(--error-bg)',
                            borderColor: 'var(--border-color)',
                            color: 'var(--error)',
                          }}
                        >
                          <AlertCircle className="w-3.5 h-3.5" />
                          <span>Pipeline Failed</span>
                        </span>
                        <button
                          onClick={() => handleRetry(job.id)}
                          className="px-2.5 py-1 text-xs font-semibold rounded-lg border transition cursor-pointer"
                          style={{
                            backgroundColor: 'var(--bg-surface-soft)',
                            borderColor: 'var(--border-color)',
                            color: 'var(--text-primary)',
                          }}
                        >
                          {t('common.retry')}
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                {/* State Machine Step Pipeline */}
                <div className="grid grid-cols-2 md:grid-cols-6 gap-2 pt-1">
                  {stages.map((st) => {
                    const isPassed = isDone || (job.stage_timings && `${st.id}_ms` in job.stage_timings);
                    const isCurrent = job.current_stage === st.id && isProcessing;
                    return (
                      <div
                        key={st.id}
                        className="p-2.5 rounded-xl border text-left text-xs transition-all"
                        style={{
                          backgroundColor: isPassed
                            ? 'var(--accent-light)'
                            : isCurrent
                            ? 'var(--bg-surface-soft)'
                            : 'var(--bg-surface-soft)',
                          borderColor: isPassed
                            ? 'var(--border-focus)'
                            : isCurrent
                            ? 'var(--brand-accent)'
                            : 'var(--border-color)',
                          color: isPassed
                            ? 'var(--brand-accent)'
                            : isCurrent
                            ? 'var(--text-primary)'
                            : 'var(--text-muted)',
                        }}
                      >
                        <div className="font-bold text-[11px] mb-0.5">{st.label}</div>
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
                  <div 
                    className="p-3 rounded-xl border text-xs font-mono"
                    style={{
                      backgroundColor: 'var(--error-bg)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--error)',
                    }}
                  >
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
