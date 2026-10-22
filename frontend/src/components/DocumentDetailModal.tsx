'use client';

import React, { useState, useEffect } from 'react';
import { 
  X, 
  FileText, 
  Layers, 
  Hash, 
  Eye, 
  RefreshCw, 
  Shield, 
  CheckCircle2, 
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Sparkles
} from 'lucide-react';
import { SourceDocument, DocumentPage, api } from '@/lib/api';

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
  const [activeTab, setActiveTab] = useState<'text' | 'pages' | 'chunks'>('text');
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 w-full max-w-5xl rounded-2xl shadow-2xl flex flex-col h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/40">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 flex items-center justify-center flex-shrink-0">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-white tracking-wide">{document.title}</h2>
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 uppercase">
                  {document.document_type}
                </span>
              </div>
              <div className="text-xs text-slate-400 font-mono mt-0.5 flex items-center gap-2">
                <span>SHA-256: {document.file_hash.substring(0, 24)}...</span>
                <span>•</span>
                <span>{(document.file_size / 1024).toFixed(1)} KB</span>
                <span>•</span>
                <span>Authority Rank: {document.authority_level}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleReprocess}
              disabled={isReprocessing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isReprocessing ? 'animate-spin' : ''}`} />
              <span>Reprocess OCR</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center px-6 border-b border-slate-800 bg-slate-900/90 text-sm">
          <button
            onClick={() => setActiveTab('text')}
            className={`py-3 px-4 font-semibold border-b-2 transition flex items-center gap-2 ${
              activeTab === 'text'
                ? 'border-indigo-500 text-indigo-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <FileText className="w-4 h-4" />
            <span>Extracted Text</span>
          </button>
          <button
            onClick={() => setActiveTab('pages')}
            className={`py-3 px-4 font-semibold border-b-2 transition flex items-center gap-2 ${
              activeTab === 'pages'
                ? 'border-indigo-500 text-indigo-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Eye className="w-4 h-4" />
            <span>Pages & OCR Bounding Boxes ({pages.length})</span>
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-hidden p-6 bg-slate-950/20">
          {activeTab === 'text' && (
            <div className="h-full overflow-y-auto bg-slate-900/90 border border-slate-800 rounded-xl p-6 font-mono text-xs leading-relaxed text-slate-200 whitespace-pre-wrap select-text">
              {pages.length > 0 ? (
                pages.map((p) => (
                  <div key={p.id} className="mb-8 pb-6 border-b border-slate-800/80 last:border-none">
                    <div className="flex items-center justify-between text-[11px] font-sans font-semibold text-slate-400 mb-3 bg-slate-800/40 px-3 py-1.5 rounded-lg border border-slate-700/40">
                      <span>PAGE {p.page_number} • {p.extraction_type.toUpperCase()} ({p.engine})</span>
                      <span className={p.confidence >= 0.7 ? 'text-emerald-400' : 'text-amber-400'}>
                        Confidence: {(p.confidence * 100).toFixed(1)}%
                      </span>
                    </div>
                    {p.text}
                  </div>
                ))
              ) : (
                <div className="text-center text-slate-500 py-12">
                  No text extracted yet or processing in progress.
                </div>
              )}
            </div>
          )}

          {activeTab === 'pages' && (
            <div className="h-full flex flex-col gap-4">
              {/* Page Carousel Bar */}
              <div className="flex items-center justify-between bg-slate-900 p-3 rounded-xl border border-slate-800">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setSelectedPageIndex(Math.max(0, selectedPageIndex - 1))}
                    disabled={selectedPageIndex === 0}
                    className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="text-xs font-semibold text-white px-2">
                    Page {selectedPageIndex + 1} of {pages.length || 1}
                  </span>
                  <button
                    onClick={() => setSelectedPageIndex(Math.min(pages.length - 1, selectedPageIndex + 1))}
                    disabled={selectedPageIndex >= pages.length - 1}
                    className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>

                {currentPage && (
                  <div className="text-xs text-slate-400 flex items-center gap-3">
                    <span>Engine: <b className="text-slate-200">{currentPage.engine}</b></span>
                    <span>Tokens: <b className="text-slate-200">{currentPage.words_count}</b></span>
                    <span>Confidence: <b className={currentPage.confidence >= 0.7 ? 'text-emerald-400' : 'text-amber-400'}>{(currentPage.confidence * 100).toFixed(1)}%</b></span>
                  </div>
                )}
              </div>

              {/* Interactive Bounding Box Stage */}
              <div className="flex-1 flex gap-4 overflow-hidden">
                {/* Visualizer Canvas */}
                <div className="flex-1 bg-slate-900 border border-slate-800 rounded-xl relative p-4 flex flex-col items-center justify-center overflow-auto">
                  {currentPage ? (
                    <div className="relative w-full h-full max-w-2xl bg-slate-950 border border-slate-800 rounded-lg overflow-hidden flex flex-col">
                      <div className="p-3 bg-slate-900 border-b border-slate-800 text-xs font-semibold text-slate-300 flex items-center justify-between">
                        <span>OCR Token Spatial Grid (0-1000 Normalized Scale)</span>
                        <span className="text-[11px] text-indigo-400">Hover token to inspect coordinates</span>
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
                                className={`px-1.5 py-0.5 rounded text-xs transition cursor-pointer ${
                                  selectedBox === box
                                    ? 'bg-indigo-600 text-white font-bold ring-2 ring-indigo-400'
                                    : box.confidence >= 0.8
                                    ? 'bg-slate-800/80 hover:bg-indigo-900/50 text-slate-200'
                                    : 'bg-amber-950/40 hover:bg-amber-900/60 text-amber-300 border border-amber-800/40'
                                }`}
                              >
                                {box.word}
                              </span>
                            ))
                          ) : (
                            <div className="text-xs text-slate-300 whitespace-pre-wrap">
                              {currentPage.text || "No tokens extracted."}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-slate-500 text-sm">No page selected.</div>
                  )}
                </div>

                {/* Token Provenance Inspector */}
                <div className="w-72 bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col text-xs text-slate-300 overflow-y-auto">
                  <div className="font-bold text-white mb-3 pb-2 border-b border-slate-800 flex items-center gap-1.5">
                    <Shield className="w-3.5 h-3.5 text-indigo-400" />
                    <span>OCR Provenance Inspector</span>
                  </div>

                  {selectedBox ? (
                    <div className="space-y-3">
                      <div>
                        <span className="text-slate-400 block text-[11px]">Selected Token</span>
                        <span className="text-base font-bold text-indigo-400 break-words">{selectedBox.word}</span>
                      </div>

                      <div className="bg-slate-800/60 p-2.5 rounded-lg space-y-1.5">
                        <div className="flex justify-between">
                          <span className="text-slate-400">OCR Confidence:</span>
                          <span className="font-semibold text-emerald-400 font-mono">
                            {(selectedBox.confidence * 100).toFixed(1)}%
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">Pixel Left (X):</span>
                          <span className="font-mono text-slate-200">{selectedBox.x} px</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">Pixel Top (Y):</span>
                          <span className="font-mono text-slate-200">{selectedBox.y} px</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">Dimensions (WxH):</span>
                          <span className="font-mono text-slate-200">{selectedBox.w} x {selectedBox.h}</span>
                        </div>
                      </div>

                      {selectedBox.normalized_box && (
                        <div>
                          <span className="text-slate-400 block text-[11px] mb-1">
                            Normalized Box [ymin, xmin, ymax, xmax]
                          </span>
                          <div className="bg-slate-950 p-2 rounded border border-slate-800 font-mono text-[11px] text-indigo-300">
                            [{selectedBox.normalized_box.join(', ')}]
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="text-slate-500 py-8 text-center leading-relaxed">
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
