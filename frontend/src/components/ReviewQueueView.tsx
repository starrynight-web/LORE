'use client';

import React, { useState } from 'react';
import { 
  AlertTriangle, 
  CheckCircle, 
  FileText, 
  RotateCw,
  Eye,
  Check,
  X
} from 'lucide-react';
import { SourceDocument, api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface ReviewQueueViewProps {
  documents: SourceDocument[];
  onRefresh: () => void;
  onInspectDocument: (doc: SourceDocument) => void;
}

export const ReviewQueueView: React.FC<ReviewQueueViewProps> = ({
  documents,
  onRefresh,
  onInspectDocument
}) => {
  const { t } = useI18n();
  const [processingId, setProcessingId] = useState<string | null>(null);

  const handleApprove = async (docId: string) => {
    setProcessingId(docId);
    try {
      await api.approveDocument(docId);
      onRefresh();
    } catch (err) {
      console.error("Error approving document:", err);
    } finally {
      setProcessingId(null);
    }
  };

  const handleReject = async (docId: string) => {
    setProcessingId(docId);
    try {
      await api.rejectDocument(docId);
      onRefresh();
    } catch (err) {
      console.error("Error rejecting document:", err);
    } finally {
      setProcessingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg sm:text-xl font-extrabold flex items-center gap-2 text-[var(--text-primary)]">
            <AlertTriangle className="w-5 h-5 text-[var(--warning)]" />
            <span>{t('review.title')}</span>
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            {t('review.subtitle')}
          </p>
        </div>
        <button
          onClick={onRefresh}
          className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold border transition cursor-pointer active:scale-95 shadow-sm"
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

      <div className="space-y-4">
        {documents.length === 0 ? (
          <div 
            className="rounded-2xl p-12 text-center border shadow-sm"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
            }}
          >
            <CheckCircle className="w-8 h-8 mx-auto mb-2 text-[var(--success)] opacity-80" />
            <h3 className="text-sm font-bold text-[var(--text-primary)]">{t('review.empty_title')}</h3>
            <p className="text-xs text-[var(--text-muted)] mt-1">{t('review.empty_desc')}</p>
          </div>
        ) : (
          documents.map((doc) => (
            <div
              key={doc.id}
              className="rounded-2xl p-5 border shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4 transition-all"
              style={{
                backgroundColor: 'var(--bg-surface)',
                borderColor: 'var(--border-color)',
              }}
            >
              <div className="flex items-start gap-3">
                <div 
                  className="w-10 h-10 rounded-xl border flex items-center justify-center flex-shrink-0 mt-0.5"
                  style={{
                    backgroundColor: 'var(--warning-bg)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--warning)',
                  }}
                >
                  <FileText className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-sm text-[var(--text-primary)]">{doc.title}</h4>
                  <div className="text-xs text-[var(--text-muted)] mt-0.5 space-x-2">
                    <span>{doc.original_filename}</span>
                    <span>•</span>
                    <span>Pages: {doc.page_count}</span>
                    <span>•</span>
                    <span className="font-mono font-bold text-[var(--warning)]">
                      OCR Confidence: {(doc.ocr_confidence * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div 
                    className="mt-2 text-xs px-3 py-1.5 rounded-xl border inline-block"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    <b>Routing Reason:</b> Rule X001 flagged OCR confidence &lt; 70% for human inspection.
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={() => onInspectDocument(doc)}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold border transition cursor-pointer"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--text-primary)',
                  }}
                >
                  <Eye className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                  <span>Inspect Scan</span>
                </button>
                <button
                  onClick={() => handleApprove(doc.id)}
                  disabled={processingId === doc.id}
                  className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold shadow-sm transition cursor-pointer active:scale-95 disabled:opacity-50"
                  style={{
                    backgroundColor: 'var(--brand-accent)',
                    color: 'var(--cta-text)',
                  }}
                >
                  <Check className="w-3.5 h-3.5" />
                  <span>{t('review.approve_btn')}</span>
                </button>
                <button
                  onClick={() => handleReject(doc.id)}
                  disabled={processingId === doc.id}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold border transition cursor-pointer active:scale-95 disabled:opacity-50"
                  style={{
                    backgroundColor: 'var(--error-bg)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--error)',
                  }}
                >
                  <X className="w-3.5 h-3.5" />
                  <span>{t('review.quarantine_btn')}</span>
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
