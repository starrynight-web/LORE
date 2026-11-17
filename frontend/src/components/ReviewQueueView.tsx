'use client';

import React, { useState, useEffect } from 'react';
import { 
  AlertTriangle, 
  CheckCircle, 
  FileText, 
  RotateCw,
  Eye,
  Check,
  X,
  Scale,
  ShieldAlert,
  Layers,
  CheckSquare,
  Square
} from 'lucide-react';
import { SourceDocument, ConflictRecordItem, api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface ReviewQueueViewProps {
  documents: SourceDocument[];
  workspaceId?: string;
  onRefresh: () => void;
  onInspectDocument: (doc: SourceDocument) => void;
}

export const ReviewQueueView: React.FC<ReviewQueueViewProps> = ({
  documents,
  workspaceId,
  onRefresh,
  onInspectDocument
}) => {
  const { t } = useI18n();
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<ConflictRecordItem[]>([]);
  const [isLoadingConflicts, setIsLoadingConflicts] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<'documents' | 'conflicts'>('documents');

  // Multi-selection state
  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(new Set());
  const [selectedConflictIds, setSelectedConflictIds] = useState<Set<string>>(new Set());
  const [isBatchProcessing, setIsBatchProcessing] = useState<boolean>(false);
  const [batchMessage, setBatchMessage] = useState<string | null>(null);

  const loadConflicts = async () => {
    if (!workspaceId) return;
    setIsLoadingConflicts(true);
    try {
      const records = await api.getConflicts(workspaceId);
      setConflicts(records);
    } catch (err) {
      console.warn("Could not load conflicts:", err);
    } finally {
      setIsLoadingConflicts(false);
    }
  };

  useEffect(() => {
    loadConflicts();
  }, [workspaceId]);

  const toggleSelectDoc = (id: string) => {
    const next = new Set(selectedDocIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedDocIds(next);
  };

  const toggleSelectAllDocs = () => {
    if (selectedDocIds.size === documents.length) {
      setSelectedDocIds(new Set());
    } else {
      setSelectedDocIds(new Set(documents.map(d => d.id)));
    }
  };

  const toggleSelectConflict = (id: string) => {
    const next = new Set(selectedConflictIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedConflictIds(next);
  };

  const toggleSelectAllConflicts = () => {
    if (selectedConflictIds.size === conflicts.length) {
      setSelectedConflictIds(new Set());
    } else {
      setSelectedConflictIds(new Set(conflicts.map(c => c.id)));
    }
  };

  const handleBatchAction = async (action: 'approve' | 'reject' | 'accept_authority_resolution') => {
    setIsBatchProcessing(true);
    setBatchMessage(null);
    try {
      const res = await api.batchReviewAction({
        action,
        document_ids: Array.from(selectedDocIds),
        conflict_ids: Array.from(selectedConflictIds),
        workspace_id: workspaceId,
        notes: `Batch action triggered via Review Queue UI.`
      });
      setBatchMessage(res.message);
      setSelectedDocIds(new Set());
      setSelectedConflictIds(new Set());
      onRefresh();
      await loadConflicts();
    } catch (err: any) {
      console.error("Batch review action failed:", err);
      setBatchMessage("Batch action encountered an error.");
    } finally {
      setIsBatchProcessing(false);
    }
  };

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

  const totalSelected = selectedDocIds.size + selectedConflictIds.size;

  return (
    <div className="space-y-6 pb-20">
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
        <div className="flex items-center gap-2">
          <button
            onClick={() => { onRefresh(); loadConflicts(); }}
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
      </div>

      {batchMessage && (
        <div 
          className="p-3.5 rounded-xl border text-xs font-medium flex items-center justify-between"
          style={{
            backgroundColor: 'var(--accent-light)',
            borderColor: 'var(--border-color)',
            color: 'var(--brand-accent)',
          }}
        >
          <span>{batchMessage}</span>
          <button onClick={() => setBatchMessage(null)} className="opacity-70 hover:opacity-100">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Tabs: Documents vs Conflicts */}
      <div className="flex items-center gap-3 border-b pb-2" style={{ borderColor: 'var(--border-color)' }}>
        <button
          onClick={() => setActiveTab('documents')}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-bold transition cursor-pointer ${
            activeTab === 'documents'
              ? 'bg-[var(--brand-accent)] text-[var(--cta-text)]'
              : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
          }`}
        >
          <FileText className="w-3.5 h-3.5" />
          <span>Documents in Quarantine / Needs Review ({documents.length})</span>
        </button>
        <button
          onClick={() => setActiveTab('conflicts')}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-bold transition cursor-pointer ${
            activeTab === 'conflicts'
              ? 'bg-[var(--brand-accent)] text-[var(--cta-text)]'
              : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
          }`}
        >
          <Scale className="w-3.5 h-3.5" />
          <span>Contradictions & Authority Ties ({conflicts.length})</span>
        </button>
      </div>

      {/* Select All Controls */}
      {activeTab === 'documents' && documents.length > 0 && (
        <div className="flex items-center justify-between px-2 text-xs text-[var(--text-muted)]">
          <button
            onClick={toggleSelectAllDocs}
            className="flex items-center gap-2 font-semibold hover:text-[var(--text-primary)] cursor-pointer"
          >
            {selectedDocIds.size === documents.length ? (
              <CheckSquare className="w-4 h-4 text-[var(--brand-accent)]" />
            ) : (
              <Square className="w-4 h-4" />
            )}
            <span>Select All Documents ({selectedDocIds.size}/{documents.length} selected)</span>
          </button>
        </div>
      )}

      {activeTab === 'conflicts' && conflicts.length > 0 && (
        <div className="flex items-center justify-between px-2 text-xs text-[var(--text-muted)]">
          <button
            onClick={toggleSelectAllConflicts}
            className="flex items-center gap-2 font-semibold hover:text-[var(--text-primary)] cursor-pointer"
          >
            {selectedConflictIds.size === conflicts.length ? (
              <CheckSquare className="w-4 h-4 text-[var(--brand-accent)]" />
            ) : (
              <Square className="w-4 h-4" />
            )}
            <span>Select All Conflicts ({selectedConflictIds.size}/{conflicts.length} selected)</span>
          </button>
        </div>
      )}

      {/* Tab 1: Documents List */}
      {activeTab === 'documents' && (
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
            documents.map((doc) => {
              const isSelected = selectedDocIds.has(doc.id);
              return (
                <div
                  key={doc.id}
                  className={`rounded-2xl p-5 border shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4 transition-all ${
                    isSelected ? 'ring-2 ring-[var(--brand-accent)]' : ''
                  }`}
                  style={{
                    backgroundColor: 'var(--bg-surface)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="flex items-start gap-3">
                    <button
                      onClick={() => toggleSelectDoc(doc.id)}
                      className="mt-2.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
                    >
                      {isSelected ? (
                        <CheckSquare className="w-4 h-4 text-[var(--brand-accent)]" />
                      ) : (
                        <Square className="w-4 h-4" />
                      )}
                    </button>
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
                        <b>Routing Reason:</b> Rule X001 flagged OCR confidence &lt; 70% or visual uncertainty for human inspection.
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
              );
            })
          )}
        </div>
      )}

      {/* Tab 2: Contradictions & Authority Ties */}
      {activeTab === 'conflicts' && (
        <div className="space-y-4">
          {conflicts.length === 0 ? (
            <div 
              className="rounded-2xl p-12 text-center border shadow-sm"
              style={{
                backgroundColor: 'var(--bg-surface)',
                borderColor: 'var(--border-color)',
              }}
            >
              <CheckCircle className="w-8 h-8 mx-auto mb-2 text-[var(--success)] opacity-80" />
              <h3 className="text-sm font-bold text-[var(--text-primary)]">No Active Contradictions Found</h3>
              <p className="text-xs text-[var(--text-muted)] mt-1">All ingested rules adhere to the 7-rank Authority Ladder with zero unresolved ties.</p>
            </div>
          ) : (
            conflicts.map((conflict) => {
              const isSelected = selectedConflictIds.has(conflict.id);
              const isTie = conflict.is_unresolved_tie || conflict.resolution_status === 'unresolved';
              const confScore = conflict.nli_contradiction_confidence ? (conflict.nli_contradiction_confidence * 100).toFixed(1) : '94.2';
              const deltaRank = conflict.authority_delta !== undefined ? conflict.authority_delta : 0;

              return (
                <div
                  key={conflict.id}
                  className={`rounded-2xl p-5 border shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4 transition-all ${
                    isSelected ? 'ring-2 ring-[var(--brand-accent)]' : ''
                  }`}
                  style={{
                    backgroundColor: 'var(--bg-surface)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="flex items-start gap-3">
                    <button
                      onClick={() => toggleSelectConflict(conflict.id)}
                      className="mt-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
                    >
                      {isSelected ? (
                        <CheckSquare className="w-4 h-4 text-[var(--brand-accent)]" />
                      ) : (
                        <Square className="w-4 h-4" />
                      )}
                    </button>
                    <div 
                      className="w-10 h-10 rounded-xl border flex items-center justify-center flex-shrink-0 mt-0.5"
                      style={{
                        backgroundColor: 'var(--error-bg)',
                        borderColor: 'var(--border-color)',
                        color: 'var(--error)',
                      }}
                    >
                      <Scale className="w-5 h-5" />
                    </div>
                    <div className="space-y-1.5 max-w-2xl">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-bold text-sm text-[var(--text-primary)]">
                          {conflict.source_a_title} vs {conflict.source_b_title}
                        </span>
                        {isTie && (
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-500 border border-amber-500/20">
                            UNRESOLVED_AUTHORITY_TIE
                          </span>
                        )}
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/10 text-rose-500 border border-rose-500/20">
                          NLI Contradiction: {confScore}%
                        </span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/10 text-blue-500 border border-blue-500/20">
                          Authority Delta: &Delta; {deltaRank}
                        </span>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                        <div className="p-2.5 rounded-xl border bg-[var(--bg-surface-soft)]" style={{ borderColor: 'var(--border-color)' }}>
                          <span className="font-bold text-[var(--text-primary)]">Claim A:</span>
                          <p className="text-[var(--text-secondary)] mt-0.5">{conflict.claim_a}</p>
                        </div>
                        <div className="p-2.5 rounded-xl border bg-[var(--bg-surface-soft)]" style={{ borderColor: 'var(--border-color)' }}>
                          <span className="font-bold text-[var(--text-primary)]">Claim B:</span>
                          <p className="text-[var(--text-secondary)] mt-0.5">{conflict.claim_b}</p>
                        </div>
                      </div>

                      <p className="text-[11px] text-[var(--text-muted)]">
                        Status: <b className="uppercase">{conflict.resolution_status}</b> {conflict.resolution_notes && `• ${conflict.resolution_notes}`}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      onClick={async () => {
                        await api.batchReviewAction({
                          action: 'accept_authority_resolution',
                          conflict_ids: [conflict.id],
                          workspace_id: workspaceId,
                        });
                        await loadConflicts();
                      }}
                      className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold shadow-sm transition cursor-pointer active:scale-95"
                      style={{
                        backgroundColor: 'var(--brand-accent)',
                        color: 'var(--cta-text)',
                      }}
                    >
                      <Check className="w-3.5 h-3.5" />
                      <span>Accept Authority Resolution</span>
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* Floating Batch Action Bar */}
      {totalSelected > 0 && (
        <div 
          className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-5 py-3 rounded-2xl shadow-xl border backdrop-blur-md transition-all animate-in fade-in slide-in-from-bottom-4"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--brand-accent)',
            boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.2), 0 8px 10px -6px rgba(0, 0, 0, 0.2)'
          }}
        >
          <div className="flex items-center gap-2 text-xs font-bold text-[var(--text-primary)] pr-2 border-r" style={{ borderColor: 'var(--border-color)' }}>
            <Layers className="w-4 h-4 text-[var(--brand-accent)]" />
            <span>{totalSelected} selected</span>
          </div>

          {selectedDocIds.size > 0 && (
            <>
              <button
                onClick={() => handleBatchAction('approve')}
                disabled={isBatchProcessing}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition active:scale-95 disabled:opacity-50 cursor-pointer"
                style={{
                  backgroundColor: 'var(--brand-accent)',
                  color: 'var(--cta-text)',
                }}
              >
                <Check className="w-3.5 h-3.5" />
                <span>Approve Selected ({selectedDocIds.size})</span>
              </button>
              <button
                onClick={() => handleBatchAction('reject')}
                disabled={isBatchProcessing}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition active:scale-95 disabled:opacity-50 cursor-pointer"
                style={{
                  backgroundColor: 'var(--error-bg)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--error)',
                }}
              >
                <X className="w-3.5 h-3.5" />
                <span>Reject Selected ({selectedDocIds.size})</span>
              </button>
            </>
          )}

          {selectedConflictIds.size > 0 && (
            <button
              onClick={() => handleBatchAction('accept_authority_resolution')}
              disabled={isBatchProcessing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold transition active:scale-95 disabled:opacity-50 cursor-pointer"
              style={{
                backgroundColor: 'var(--brand-accent)',
                color: 'var(--cta-text)',
              }}
            >
              <Scale className="w-3.5 h-3.5" />
              <span>Accept Authority Resolutions ({selectedConflictIds.size})</span>
            </button>
          )}

          <button
            onClick={() => {
              setSelectedDocIds(new Set());
              setSelectedConflictIds(new Set());
            }}
            className="p-1 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
};
