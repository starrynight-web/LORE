'use client';

import React, { useState } from 'react';
import { 
  AlertTriangle, 
  CheckCircle, 
  XCircle, 
  Shield, 
  FileText, 
  RotateCw,
  Eye,
  Check,
  X
} from 'lucide-react';
import { SourceDocument, api } from '@/lib/api';

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
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-amber-400" />
            <span>Human-in-the-Loop Review Queue</span>
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Documents routed here have low OCR confidence (&lt; 70%), conflicting claims, or require human promotion to live context.
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

      <div className="space-y-4">
        {documents.length === 0 ? (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-12 text-center text-slate-500 text-sm">
            <CheckCircle className="w-8 h-8 text-emerald-500/40 mx-auto mb-2" />
            <span>All documents are verified. No items currently require human review.</span>
          </div>
        ) : (
          documents.map((doc) => (
            <div
              key={doc.id}
              className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4 hover:border-slate-700 transition"
            >
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <FileText className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-semibold text-white text-sm">{doc.title}</h4>
                  <div className="text-xs text-slate-400 mt-0.5 space-x-2">
                    <span>{doc.original_filename}</span>
                    <span>•</span>
                    <span>Pages: {doc.page_count}</span>
                    <span>•</span>
                    <span className="font-mono text-amber-400">
                      OCR Confidence: {(doc.ocr_confidence * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="mt-2 text-xs text-slate-300 bg-slate-800/60 px-3 py-1.5 rounded-lg border border-slate-700/40 inline-block">
                    <b>Routing Reason:</b> Rule X001 flagged OCR confidence &lt; 70% for human inspection.
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={() => onInspectDocument(doc)}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
                >
                  <Eye className="w-3.5 h-3.5" />
                  <span>Inspect Scan</span>
                </button>
                <button
                  onClick={() => handleApprove(doc.id)}
                  disabled={processingId === doc.id}
                  className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white shadow-md shadow-emerald-600/20 transition cursor-pointer"
                >
                  <Check className="w-3.5 h-3.5" />
                  <span>Approve & Promote</span>
                </button>
                <button
                  onClick={() => handleReject(doc.id)}
                  disabled={processingId === doc.id}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/30 transition cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                  <span>Reject</span>
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
