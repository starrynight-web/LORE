'use client';

import React, { useState, useEffect } from 'react';
import { 
  X, 
  FileText, 
  Eye, 
  RefreshCw, 
  Shield, 
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { SourceDocument, DocumentPage, api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface DocumentDetailModalProps {
  document: SourceDocument | null;
  onClose: () => void;
  onReprocessSuccess: () => void;
}

export const DocumentDetailModal: React.FC<DocumentDetailModalProps> = ({
  document,
  onClose,
  onReprocessSuccess
}) => {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<'text' | 'pages'>('text');
  const [pages, setPages] = useState<DocumentPage[]>([]);
  const [selectedPageIndex, setSelectedPageIndex] = useState(0);
  const [selectedBox, setSelectedBox] = useState<any | null>(null);
  const [isLoadingPages, setIsLoadingPages] = useState(false);
  const [isReprocessing, setIsReprocessing] = useState(false);

  useEffect(() => {
    if (document) {
      setIsLoadingPages(true);
      api.getDocumentPages(document.id)
        .then((data) => {
          setPages(data);
          setSelectedPageIndex(0);
        })
        .catch((err) => console.error("Error loading document pages:", err))
        .finally(() => setIsLoadingPages(false));
    }
  }, [document]);

  if (!document) return null;

  const handleReprocess = async () => {
    setIsReprocessing(true);
    try {
      await api.reprocessDocument(document.id);
      onReprocessSuccess();
      onClose();
    } catch (err) {
      console.error("Error triggering reprocessing:", err);
    } finally {
      setIsReprocessing(false);
    }
  };

  const currentPage = pages[selectedPageIndex] || null;

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-sm"
      style={{ backgroundColor: 'var(--modal-overlay)' }}
    >
      <div 
        className="w-full max-w-5xl rounded-2xl border shadow-2xl flex flex-col h-[90vh] overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        {/* Header */}
        <div 
          className="px-6 py-4 border-b flex items-center justify-between"
          style={{ 
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)' 
          }}
        >
          <div className="flex items-center gap-3">
            <div 
              className="w-10 h-10 rounded-xl border flex items-center justify-center flex-shrink-0"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm sm:text-base font-bold text-[var(--text-primary)] tracking-wide">
                  {document.title}
                </h2>
                <span 
                  className="text-[10px] font-bold px-2 py-0.5 rounded border uppercase"
                  style={{
                    backgroundColor: 'var(--accent-light)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--brand-accent)',
                  }}
                >
                  {document.document_type}
                </span>
              </div>
              <div className="text-[11px] text-[var(--text-muted)] font-mono mt-0.5 flex items-center gap-2">
                <span>SHA-256: {document.file_hash.substring(0, 20)}...</span>
                <span>•</span>
                <span>{(document.file_size / 1024).toFixed(1)} KB</span>
                <span>•</span>
                <span>Rank: {document.authority_level}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleReprocess}
              disabled={isReprocessing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border transition cursor-pointer active:scale-95"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-primary)',
              }}
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isReprocessing ? 'animate-spin' : ''}`} />
              <span>{t('docs.reprocess')}</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-xl border transition cursor-pointer hover:border-[var(--brand-accent)]"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-muted)',
              }}
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div 
          className="flex items-center px-6 border-b text-xs sm:text-sm font-semibold"
          style={{
            backgroundColor: 'var(--bg-surface-soft)',
            borderColor: 'var(--border-color)',
          }}
        >
          <button
            onClick={() => setActiveTab('text')}
            className="py-3 px-4 border-b-2 transition-colors flex items-center gap-2 cursor-pointer"
            style={{
              borderColor: activeTab === 'text' ? 'var(--brand-accent)' : 'transparent',
              color: activeTab === 'text' ? 'var(--brand-accent)' : 'var(--text-muted)',
            }}
          >
            <FileText className="w-4 h-4" />
            <span>Extracted Text</span>
          </button>
          <button
            onClick={() => setActiveTab('pages')}
            className="py-3 px-4 border-b-2 transition-colors flex items-center gap-2 cursor-pointer"
            style={{
              borderColor: activeTab === 'pages' ? 'var(--brand-accent)' : 'transparent',
              color: activeTab === 'pages' ? 'var(--brand-accent)' : 'var(--text-muted)',
            }}
          >
            <Eye className="w-4 h-4" />
            <span>Pages & OCR Bounding Boxes ({pages.length})</span>
          </button>
        </div>

        {/* Content Body */}
        <div 
          className="flex-1 overflow-hidden p-6"
          style={{ backgroundColor: 'var(--bg-primary)' }}
        >
          {activeTab === 'text' && (
            <div 
              className="h-full overflow-y-auto border rounded-2xl p-6 font-mono text-xs leading-relaxed whitespace-pre-wrap select-text shadow-sm"
              style={{
                backgroundColor: 'var(--bg-surface)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-primary)',
              }}
            >
              {pages.length > 0 ? (
                pages.map((p) => (
                  <div key={p.id} className="mb-8 pb-6 border-b last:border-none" style={{ borderColor: 'var(--border-color)' }}>
                    <div 
                      className="flex items-center justify-between text-[11px] font-sans font-semibold mb-3 px-3.5 py-1.5 rounded-xl border"
                      style={{
                        backgroundColor: 'var(--bg-surface-soft)',
                        borderColor: 'var(--border-color)',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      <span>PAGE {p.page_number} • {p.extraction_type.toUpperCase()} ({p.engine})</span>
                      <span className={p.confidence >= 0.7 ? 'text-[var(--success)] font-bold' : 'text-[var(--warning)] font-bold'}>
                        Confidence: {(p.confidence * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="leading-relaxed">{p.text}</div>
                  </div>
                ))
              ) : (
                <div className="text-center py-12 text-sm text-[var(--text-muted)]">
                  {isLoadingPages ? 'Loading extracted text...' : 'No text extracted yet or processing in progress.'}
                </div>
              )}
            </div>
          )}

          {activeTab === 'pages' && (
            <div className="h-full flex flex-col gap-4">
              {/* Page Carousel Bar */}
              <div 
                className="flex items-center justify-between p-3 rounded-xl border shadow-sm"
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  borderColor: 'var(--border-color)',
                }}
              >
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setSelectedPageIndex(Math.max(0, selectedPageIndex - 1))}
                    disabled={selectedPageIndex === 0}
                    className="p-1 rounded-lg border transition disabled:opacity-40 cursor-pointer"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="text-xs font-semibold px-2 text-[var(--text-primary)]">
                    Page {selectedPageIndex + 1} of {pages.length || 1}
                  </span>
                  <button
                    onClick={() => setSelectedPageIndex(Math.min(pages.length - 1, selectedPageIndex + 1))}
                    disabled={selectedPageIndex >= pages.length - 1}
                    className="p-1 rounded-lg border transition disabled:opacity-40 cursor-pointer"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>

                {currentPage && (
                  <div className="text-xs text-[var(--text-muted)] flex items-center gap-3">
                    <span>Engine: <b className="text-[var(--text-primary)]">{currentPage.engine}</b></span>
                    <span>Tokens: <b className="text-[var(--text-primary)]">{currentPage.words_count}</b></span>
                    <span>Confidence: <b className={currentPage.confidence >= 0.7 ? 'text-[var(--success)]' : 'text-[var(--warning)]'}>{(currentPage.confidence * 100).toFixed(1)}%</b></span>
                  </div>
                )}
              </div>

              {/* Interactive Bounding Box Stage */}
              <div className="flex-1 flex gap-4 overflow-hidden">
                {/* Visualizer Canvas */}
                <div 
                  className="flex-1 border rounded-xl relative p-4 flex flex-col items-center justify-center overflow-auto shadow-sm"
                  style={{
                    backgroundColor: 'var(--bg-surface)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  {currentPage ? (
                    <div 
                      className="relative w-full h-full max-w-2xl border rounded-lg overflow-hidden flex flex-col"
                      style={{
                        backgroundColor: 'var(--bg-surface-soft)',
                        borderColor: 'var(--border-color)',
                      }}
                    >
                      <div 
                        className="p-3 border-b text-xs font-semibold flex items-center justify-between"
                        style={{
                          backgroundColor: 'var(--bg-surface)',
                          borderColor: 'var(--border-color)',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        <span>OCR Token Spatial Grid</span>
                        <span className="text-[11px] text-[var(--brand-accent)] font-medium">Hover token to inspect provenance</span>
                      </div>
                      
                      {/* Interactive Token Mesh */}
                      <div className="relative flex-1 p-6 overflow-y-auto">
                        <div className="flex flex-wrap gap-1.5 leading-relaxed">
                          {currentPage.bounding_boxes && currentPage.bounding_boxes.length > 0 ? (
                            currentPage.bounding_boxes.map((box, bIdx) => (
                              <span
                                key={bIdx}
                                onMouseEnter={() => setSelectedBox(box)}
                                onMouseLeave={() => setSelectedBox(null)}
                                className="px-1.5 py-0.5 rounded text-xs transition cursor-pointer"
                                style={{
                                  backgroundColor: selectedBox === box
                                    ? 'var(--brand-accent)'
                                    : box.confidence >= 0.8
                                    ? 'var(--bg-surface)'
                                    : 'var(--warning-bg)',
                                  color: selectedBox === box
                                    ? 'var(--cta-text)'
                                    : box.confidence >= 0.8
                                    ? 'var(--text-primary)'
                                    : 'var(--warning)',
                                  border: selectedBox === box
                                    ? '1px solid var(--border-focus)'
                                    : '1px solid var(--border-color)',
                                }}
                              >
                                {box.word}
                              </span>
                            ))
                          ) : (
                            <div className="text-xs text-[var(--text-primary)] whitespace-pre-wrap">
                              {currentPage.text || "No tokens extracted."}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-sm text-[var(--text-muted)]">No page selected.</div>
                  )}
                </div>

                {/* Token Provenance Inspector */}
                <div 
                  className="w-72 border rounded-xl p-4 flex flex-col text-xs overflow-y-auto shadow-sm"
                  style={{
                    backgroundColor: 'var(--bg-surface)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--text-primary)',
                  }}
                >
                  <div 
                    className="font-bold mb-3 pb-2 border-b flex items-center gap-1.5 text-[var(--text-primary)]"
                    style={{ borderColor: 'var(--border-color)' }}
                  >
                    <Shield className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                    <span>OCR Provenance Inspector</span>
                  </div>

                  {selectedBox ? (
                    <div className="space-y-3">
                      <div>
                        <span className="text-[var(--text-muted)] block text-[11px]">Selected Token</span>
                        <span className="text-base font-bold text-[var(--brand-accent)] break-words">{selectedBox.word}</span>
                      </div>

                      <div 
                        className="p-3 rounded-xl border space-y-2"
                        style={{
                          backgroundColor: 'var(--bg-surface-soft)',
                          borderColor: 'var(--border-color)',
                        }}
                      >
                        <div className="flex justify-between">
                          <span className="text-[var(--text-muted)]">OCR Confidence:</span>
                          <span className="font-bold text-[var(--success)] font-mono">
                            {(selectedBox.confidence * 100).toFixed(1)}%
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[var(--text-muted)]">Pixel Left (X):</span>
                          <span className="font-mono text-[var(--text-primary)]">{selectedBox.x} px</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[var(--text-muted)]">Pixel Top (Y):</span>
                          <span className="font-mono text-[var(--text-primary)]">{selectedBox.y} px</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[var(--text-muted)]">Dimensions (WxH):</span>
                          <span className="font-mono text-[var(--text-primary)]">{selectedBox.w} x {selectedBox.h}</span>
                        </div>
                      </div>

                      {selectedBox.normalized_box && (
                        <div>
                          <span className="text-[var(--text-muted)] block text-[11px] mb-1">
                            Normalized Box [ymin, xmin, ymax, xmax]
                          </span>
                          <div 
                            className="p-2 rounded-xl border font-mono text-[11px] text-[var(--brand-accent)]"
                            style={{
                              backgroundColor: 'var(--bg-surface-soft)',
                              borderColor: 'var(--border-color)',
                            }}
                          >
                            [{selectedBox.normalized_box.join(', ')}]
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="text-[var(--text-muted)] py-8 text-center leading-relaxed">
                      Hover over any word in the token mesh to view its exact coordinate provenance and confidence score.
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
