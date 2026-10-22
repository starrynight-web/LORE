'use client';

import React, { useState, useRef } from 'react';
import { 
  Scan, 
  Upload, 
  FileText, 
  Zap, 
  ShieldCheck, 
  AlertTriangle, 
  CheckCircle2, 
  Copy, 
  Download, 
  Eye, 
  ChevronLeft, 
  ChevronRight,
  Database,
  ArrowRight,
  Sparkles,
  RefreshCw
} from 'lucide-react';
import { api, DocumentPage, Collection } from '@/lib/api';
import { SAMPLE_DEED_BASE64, SAMPLE_MEMO_BASE64 } from '@/lib/sampleDocs';
import { useI18n } from '@/lib/i18n';

interface RealtimeOCRStudioProps {
  workspaceId?: string;
  collections?: Collection[];
  onDocumentSaved?: (docId: string) => void;
  onNavigateToRAG?: () => void;
}

export const RealtimeOCRStudio: React.FC<RealtimeOCRStudioProps> = ({
  workspaceId,
  collections = [],
  onDocumentSaved,
  onNavigateToRAG
}) => {
  const { t } = useI18n();

  // File & Execution State
  const [file, setFile] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Result State
  const [ocrResult, setOcrResult] = useState<{
    status: string;
    filename: string;
    file_hash: string;
    document_type: string;
    pages: DocumentPage[];
    page_count: number;
    ocr_confidence: number;
    total_words: number;
    timings_ms: number;
    document_id: string | null;
  } | null>(null);

  const [activePageIndex, setActivePageIndex] = useState<number>(0);
  const [hoveredBox, setHoveredBox] = useState<any | null>(null);
  const [selectedWord, setSelectedWord] = useState<string | null>(null);

  // Options
  const [bengaliRepair, setBengaliRepair] = useState<boolean>(true);
  const [arabicDigits, setArabicDigits] = useState<boolean>(false);
  const [showBoundingBoxes, setShowBoundingBoxes] = useState<boolean>(true);
  const [viewMode, setViewMode] = useState<'text' | 'tokens'>('text');

  // Persistence to Workspace
  const [targetCollectionId, setTargetCollectionId] = useState<string>('');
  const [authorityLevel, setAuthorityLevel] = useState<number>(3);
  const [docTitle, setDocTitle] = useState<string>('');
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [savedSuccessDocId, setSavedSuccessDocId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const canvasContainerRef = useRef<HTMLDivElement>(null);

  // Helper to convert base64 data URI to a File object
  const dataURLtoFile = (dataurl: string, filename: string): File => {
    const arr = dataurl.split(',');
    const mime = arr[0].match(/:(.*?);/)![1];
    const bstr = atob(arr[1]);
    let n = bstr.length;
    const u8arr = new Uint8Array(n);
    while (n--) {
      u8arr[n] = bstr.charCodeAt(n);
    }
    return new File([u8arr], filename, { type: mime });
  };

  // Run live OCR when file changes
  const executeLiveOCR = async (selectedFile: File) => {
    setIsProcessing(true);
    setErrorMsg(null);
    setSavedSuccessDocId(null);
    setDocTitle(selectedFile.name.replace(/\.[^/.]+$/, ''));

    // Create a local blob url for preview if image
    if (selectedFile.type.startsWith('image/')) {
      const url = URL.createObjectURL(selectedFile);
      setImagePreviewUrl(url);
    } else {
      setImagePreviewUrl(null);
    }

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('bengali_repair', String(bengaliRepair));
      formData.append('arabic_digits', String(arabicDigits));

      const res = await api.liveOCR(formData);
      setOcrResult(res);
      setActivePageIndex(0);
    } catch (err: any) {
      console.error("Live OCR failed:", err);
      setErrorMsg(err.message || 'Realtime OCR failed to process document.');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setFile(f);
      executeLiveOCR(f);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if (f) {
      setFile(f);
      executeLiveOCR(f);
    }
  };

  const loadSample = (type: 'deed' | 'memo') => {
    const base64Data = type === 'deed' ? SAMPLE_DEED_BASE64 : SAMPLE_MEMO_BASE64;
    const filename = type === 'deed' ? 'saf_kabla_land_deed_2026.png' : 'corporate_memo_procurement.png';
    const sampleFile = dataURLtoFile(base64Data, filename);
    setFile(sampleFile);
    executeLiveOCR(sampleFile);
  };

  const handleSaveToWorkspace = async () => {
    if (!file || !workspaceId) return;
    setIsSaving(true);
    setErrorMsg(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('bengali_repair', String(bengaliRepair));
      formData.append('arabic_digits', String(arabicDigits));
      formData.append('save_to_workspace', 'true');
      formData.append('workspace', workspaceId);
      formData.append('title', docTitle || file.name);
      formData.append('authority_level', String(authorityLevel));
      if (targetCollectionId) {
        formData.append('collection', targetCollectionId);
      }

      const res = await api.liveOCR(formData);
      if (res.document_id) {
        setSavedSuccessDocId(res.document_id);
        if (onDocumentSaved) onDocumentSaved(res.document_id);
      }
    } catch (err: any) {
      console.error("Failed to save OCR document to workspace:", err);
      setErrorMsg(err.message || 'Failed to save document to workspace.');
    } finally {
      setIsSaving(false);
    }
  };

  const currentPage = ocrResult?.pages?.[activePageIndex] || null;
  const bboxes = currentPage?.bounding_boxes || [];

  return (
    <div className="space-y-6">
      {/* Studio Header */}
      <div 
        className="rounded-2xl p-6 border shadow-sm transition-all duration-200"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <div 
                className="w-8 h-8 rounded-xl border flex items-center justify-center"
                style={{
                  backgroundColor: 'var(--accent-light)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--brand-accent)',
                }}
              >
                <Scan className="w-4 h-4" />
              </div>
              <h1 className="text-lg sm:text-xl font-extrabold text-[var(--text-primary)]">
                {t('ocr.title')}
              </h1>
              <span 
                className="text-[10px] font-bold px-2 py-0.5 rounded-full border flex items-center gap-1"
                style={{
                  backgroundColor: 'var(--accent-light)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--brand-accent)',
                }}
              >
                <Zap className="w-3 h-3" /> SUB-SECOND REALTIME
              </span>
            </div>
            <p className="text-xs sm:text-sm text-[var(--text-secondary)] max-w-3xl leading-relaxed">
              {t('ocr.subtitle')}
            </p>
          </div>

          {/* Quick Demo Buttons */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-[var(--text-muted)] font-semibold">{t('ocr.load_sample')}</span>
            <button
              onClick={() => loadSample('deed')}
              className="px-3 py-1.5 rounded-xl border text-xs font-semibold transition cursor-pointer active:scale-95 shadow-sm"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-primary)',
              }}
            >
              <FileText className="w-3.5 h-3.5 text-[var(--warning)] inline mr-1" />
              <span>{t('ocr.sample_deed')}</span>
            </button>
            <button
              onClick={() => loadSample('memo')}
              className="px-3 py-1.5 rounded-xl border text-xs font-semibold transition cursor-pointer active:scale-95 shadow-sm"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-primary)',
              }}
            >
              <ShieldCheck className="w-3.5 h-3.5 text-[var(--brand-accent)] inline mr-1" />
              <span>{t('ocr.sample_contract')}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Main Drag & Drop / Upload Strip */}
      <div 
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className="border-2 border-dashed rounded-2xl p-6 text-center cursor-pointer transition-all duration-200"
        style={{
          backgroundColor: file ? 'var(--accent-light)' : 'var(--bg-surface)',
          borderColor: file ? 'var(--brand-accent)' : 'var(--border-color)',
        }}
      >
        <input 
          ref={fileInputRef}
          type="file" 
          accept="image/*,application/pdf"
          onChange={handleFileChange}
          className="hidden" 
        />
        <div className="flex flex-col items-center justify-center gap-2">
          <div 
            className="w-12 h-12 rounded-2xl border flex items-center justify-center mb-1"
            style={{
              backgroundColor: 'var(--accent-light)',
              borderColor: 'var(--border-color)',
              color: 'var(--brand-accent)',
            }}
          >
            <Upload className="w-6 h-6" />
          </div>
          <div className="text-xs sm:text-sm font-bold text-[var(--text-primary)]">
            {file ? file.name : t('ocr.drop_hint')}
          </div>
          <p className="text-xs text-[var(--text-muted)]">
            {file ? `${(file.size / 1024).toFixed(1)} KB — Ready to extract` : "Processed synchronously in memory; no queuing latency"}
          </p>
        </div>
      </div>

      {errorMsg && (
        <div 
          className="p-4 rounded-xl border text-xs sm:text-sm flex items-center gap-2"
          style={{
            backgroundColor: 'var(--error-bg)',
            borderColor: 'var(--border-color)',
            color: 'var(--error)',
          }}
        >
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Control Bar */}
      <div 
        className="flex flex-wrap items-center justify-between gap-4 border rounded-2xl p-3.5 px-5 shadow-sm"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="flex flex-wrap items-center gap-5 text-xs">
          <label className="flex items-center gap-2 cursor-pointer text-[var(--text-secondary)] hover:text-[var(--text-primary)] select-none">
            <input 
              type="checkbox" 
              checked={bengaliRepair} 
              onChange={(e) => {
                setBengaliRepair(e.target.checked);
                if (file) executeLiveOCR(file);
              }}
              className="rounded accent-[var(--brand-accent)]" 
            />
            <span className="font-medium">Phonetic Unicode Repair (Bengali)</span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer text-[var(--text-secondary)] hover:text-[var(--text-primary)] select-none">
            <input 
              type="checkbox" 
              checked={arabicDigits} 
              onChange={(e) => {
                setArabicDigits(e.target.checked);
                if (file) executeLiveOCR(file);
              }}
              className="rounded accent-[var(--brand-accent)]" 
            />
            <span className="font-medium">Bangla to Arabic Numerals</span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer text-[var(--text-secondary)] hover:text-[var(--text-primary)] select-none">
            <input 
              type="checkbox" 
              checked={showBoundingBoxes} 
              onChange={(e) => setShowBoundingBoxes(e.target.checked)}
              className="rounded accent-[var(--brand-accent)]" 
            />
            <span className="font-medium">Show Word Bounding Boxes</span>
          </label>
        </div>

        {ocrResult && (
          <div className="flex items-center gap-3">
            <span 
              className="text-xs px-2.5 py-1 rounded-xl border font-mono font-bold flex items-center gap-1"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              <Zap className="w-3.5 h-3.5 text-[var(--warning)]" />
              <span>{ocrResult.timings_ms} ms</span>
            </span>
            <span 
              className="text-xs px-2.5 py-1 rounded-xl font-mono font-bold border"
              style={{
                backgroundColor: ocrResult.ocr_confidence >= 0.70 ? 'var(--success-bg)' : 'var(--warning-bg)',
                borderColor: 'var(--border-color)',
                color: ocrResult.ocr_confidence >= 0.70 ? 'var(--success)' : 'var(--warning)',
              }}
            >
              {(ocrResult.ocr_confidence * 100).toFixed(1)}% {t('ocr.confidence')}
            </span>
          </div>
        )}
      </div>

      {/* Main Dual Workspace: Canvas (Left) + Text & Metadata (Right) */}
      {isProcessing ? (
        <div 
          className="border rounded-2xl p-16 flex flex-col items-center justify-center gap-3 min-h-[420px]"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div 
            className="w-10 h-10 border-3 border-t-transparent rounded-full animate-spin"
            style={{
              borderColor: 'var(--brand-accent)',
              borderTopColor: 'transparent',
            }}
          />
          <div className="text-sm sm:text-base font-bold text-[var(--text-primary)]">Running Synchronous OCR Engine...</div>
          <p className="text-xs text-[var(--text-muted)]">
            Applying EXIF alignment, 300 DPI rasterization, token spatial extraction, and Bengali phonetic normalization
          </p>
        </div>
      ) : ocrResult && currentPage ? (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left: Document Visual Preview & Interactive Bounding Boxes */}
          <div 
            className="lg:col-span-7 border rounded-2xl p-4 flex flex-col shadow-sm"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
            }}
          >
            <div 
              className="flex items-center justify-between pb-3 border-b mb-3"
              style={{ borderColor: 'var(--border-color)' }}
            >
              <div className="flex items-center gap-2">
                <Eye className="w-4 h-4 text-[var(--brand-accent)]" />
                <span className="text-xs font-bold text-[var(--text-primary)] uppercase tracking-wider">
                  {t('ocr.original_doc')} {imagePreviewUrl ? '(Scan Canvas)' : '(PDF Layout)'}
                </span>
              </div>

              {ocrResult.page_count > 1 && (
                <div className="flex items-center gap-2">
                  <button 
                    disabled={activePageIndex === 0}
                    onClick={() => setActivePageIndex(p => Math.max(0, p - 1))}
                    className="p-1 rounded-lg border transition disabled:opacity-30 cursor-pointer"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="text-xs text-[var(--text-muted)]">
                    Page {activePageIndex + 1} of {ocrResult.page_count}
                  </span>
                  <button 
                    disabled={activePageIndex >= ocrResult.page_count - 1}
                    onClick={() => setActivePageIndex(p => Math.min(ocrResult.page_count - 1, p + 1))}
                    className="p-1 rounded-lg border transition disabled:opacity-30 cursor-pointer"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>

            {/* Canvas Viewport */}
            <div 
              ref={canvasContainerRef}
              className="relative w-full rounded-xl overflow-hidden flex items-center justify-center min-h-[460px] border p-2"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
              }}
            >
              {imagePreviewUrl ? (
                <div className="relative inline-block max-w-full">
                  <img 
                    src={imagePreviewUrl} 
                    alt="Scan preview" 
                    className="max-h-[520px] w-auto object-contain rounded-lg shadow-sm block"
                  />
                  {/* Bounding box layer normalized to 0-1000 scale */}
                  {showBoundingBoxes && bboxes.map((box, idx) => {
                    const [ymin, xmin, ymax, xmax] = box.normalized_box || [0, 0, 0, 0];
                    const topPct = (ymin / 10).toFixed(2);
                    const leftPct = (xmin / 10).toFixed(2);
                    const widthPct = ((xmax - xmin) / 10).toFixed(2);
                    const heightPct = ((ymax - ymin) / 10).toFixed(2);

                    const conf = box.confidence || 0.8;
                    const isHovered = hoveredBox === box || selectedWord === box.word;

                    return (
                      <div
                        key={idx}
                        onMouseEnter={() => setHoveredBox(box)}
                        onMouseLeave={() => setHoveredBox(null)}
                        onClick={() => setSelectedWord(box.word)}
                        style={{
                          top: `${topPct}%`,
                          left: `${leftPct}%`,
                          width: `${widthPct}%`,
                          height: `${heightPct}%`,
                          borderColor: conf >= 0.85 ? 'var(--success)' : conf >= 0.7 ? 'var(--warning)' : 'var(--error)',
                          backgroundColor: conf >= 0.85 ? 'rgba(21, 128, 61, 0.15)' : 'rgba(180, 83, 9, 0.15)',
                        }}
                        className={`absolute border transition-all cursor-pointer rounded-[2px] ${
                          isHovered ? 'ring-2 ring-[var(--border-focus)] z-30 scale-105' : 'z-10'
                        }`}
                        title={`${box.word} (${(conf * 100).toFixed(0)}%)`}
                      />
                    );
                  })}
                </div>
              ) : (
                /* PDF Visual representation */
                <div 
                  className="w-full h-full min-h-[460px] p-6 font-mono text-xs flex flex-col justify-between"
                  style={{ color: 'var(--text-primary)' }}
                >
                  <div 
                    className="p-4 rounded-xl border space-y-2"
                    style={{
                      backgroundColor: 'var(--bg-surface)',
                      borderColor: 'var(--border-color)',
                    }}
                  >
                    <div className="flex items-center gap-2 text-[var(--brand-accent)] font-bold">
                      <FileText className="w-4 h-4" />
                      <span>Dual-Stream Digital PDF Extraction Active</span>
                    </div>
                    <p className="text-[var(--text-secondary)] leading-relaxed text-[11px]">
                      Extracted via pdfplumber character layer with visual Bengali normalization.
                      Tokens extracted: <strong className="text-[var(--text-primary)]">{bboxes.length} words</strong>.
                    </p>
                  </div>
                  <div className="text-center text-xs py-12 text-[var(--text-muted)]">
                    To inspect pixel-accurate visual bounding box overlays, upload a scanned document image (PNG, JPG, TIFF).
                  </div>
                  <div className="text-right text-[11px] text-[var(--text-muted)]">
                    Engine: {currentPage.engine || 'native'} ({currentPage.engine_version})
                  </div>
                </div>
              )}

              {/* Floating Tooltip when hovering a box */}
              {hoveredBox && (
                <div 
                  className="absolute bottom-4 left-4 right-4 backdrop-blur-md border p-3 rounded-xl shadow-xl flex items-center justify-between text-xs z-40 animate-in fade-in duration-150"
                  style={{
                    backgroundColor: 'var(--bg-surface)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="flex items-center gap-3">
                    <span 
                      className="font-bold text-sm px-2.5 py-1 rounded-lg border text-[var(--text-primary)]"
                      style={{
                        backgroundColor: 'var(--bg-surface-soft)',
                        borderColor: 'var(--border-color)',
                      }}
                    >
                      &quot;{hoveredBox.word}&quot;
                    </span>
                    <div className="space-y-0.5">
                      <div className="text-[var(--text-muted)] text-[11px]">
                        Normalized: <span className="font-mono text-[var(--brand-accent)]">[{hoveredBox.normalized_box?.join(', ')}]</span>
                      </div>
                      <div className="text-[var(--text-muted)] text-[11px]">
                        Pixel size: <span className="font-mono text-[var(--text-primary)]">{hoveredBox.w} × {hoveredBox.h} px</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-[var(--text-muted)]">{t('ocr.confidence')}:</span>
                    <span 
                      className="font-bold font-mono px-2 py-0.5 rounded text-xs border"
                      style={{
                        backgroundColor: (hoveredBox.confidence || 0) >= 0.85 ? 'var(--success-bg)' : 'var(--warning-bg)',
                        borderColor: 'var(--border-color)',
                        color: (hoveredBox.confidence || 0) >= 0.85 ? 'var(--success)' : 'var(--warning)',
                      }}
                    >
                      {((hoveredBox.confidence || 0) * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Right: Extracted Clean Text, Token Inspector & Workspace Persistence */}
          <div className="lg:col-span-5 flex flex-col gap-4">
            {/* Stats Card */}
            <div 
              className="border rounded-2xl p-4 shadow-sm"
              style={{
                backgroundColor: 'var(--bg-surface)',
                borderColor: 'var(--border-color)',
              }}
            >
              <div className="grid grid-cols-3 gap-2 text-center">
                <div 
                  className="p-2.5 rounded-xl border"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="text-[11px] text-[var(--text-muted)]">Total Words</div>
                  <div className="text-base font-bold text-[var(--text-primary)]">{currentPage.words_count || ocrResult.total_words}</div>
                </div>
                <div 
                  className="p-2.5 rounded-xl border"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="text-[11px] text-[var(--text-muted)]">{t('ocr.confidence')}</div>
                  <div className="text-base font-bold text-[var(--brand-accent)]">{(currentPage.confidence * 100).toFixed(1)}%</div>
                </div>
                <div 
                  className="p-2.5 rounded-xl border"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="text-[11px] text-[var(--text-muted)]">{t('common.status')}</div>
                  <div className="text-xs font-semibold mt-1">
                    {currentPage.confidence >= 0.70 ? (
                      <span className="text-[var(--success)] flex items-center justify-center gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5" /> High Trust
                      </span>
                    ) : (
                      <span className="text-[var(--warning)] flex items-center justify-center gap-1">
                        <AlertTriangle className="w-3.5 h-3.5" /> {t('common.needs_review')}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Extracted Text Box */}
            <div 
              className="border rounded-2xl p-4 flex-1 flex flex-col shadow-sm min-h-[300px]"
              style={{
                backgroundColor: 'var(--bg-surface)',
                borderColor: 'var(--border-color)',
              }}
            >
              <div 
                className="flex items-center justify-between pb-3 border-b mb-3"
                style={{ borderColor: 'var(--border-color)' }}
              >
                <div className="flex items-center gap-2">
                  <button 
                    onClick={() => setViewMode('text')}
                    className="text-xs font-semibold px-2.5 py-1 rounded-lg transition-all cursor-pointer"
                    style={{
                      backgroundColor: viewMode === 'text' ? 'var(--brand-accent)' : 'transparent',
                      color: viewMode === 'text' ? 'var(--cta-text)' : 'var(--text-secondary)',
                    }}
                  >
                    {t('ocr.extracted_text')}
                  </button>
                  <button 
                    onClick={() => setViewMode('tokens')}
                    className="text-xs font-semibold px-2.5 py-1 rounded-lg transition-all cursor-pointer"
                    style={{
                      backgroundColor: viewMode === 'tokens' ? 'var(--brand-accent)' : 'transparent',
                      color: viewMode === 'tokens' ? 'var(--cta-text)' : 'var(--text-secondary)',
                    }}
                  >
                    Token Badges ({bboxes.length})
                  </button>
                </div>

                <div className="flex items-center gap-1">
                  <button
                    onClick={() => navigator.clipboard.writeText(currentPage.text)}
                    className="p-1.5 rounded-lg border transition-all text-xs flex items-center gap-1 cursor-pointer"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--text-secondary)',
                    }}
                    title="Copy text"
                  >
                    <Copy className="w-3.5 h-3.5" />
                    <span>Copy</span>
                  </button>
                  <button
                    onClick={() => {
                      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(ocrResult, null, 2));
                      const downloadAnchor = document.createElement('a');
                      downloadAnchor.setAttribute("href", dataStr);
                      downloadAnchor.setAttribute("download", `ocr_${ocrResult.filename}.json`);
                      downloadAnchor.click();
                    }}
                    className="p-1.5 rounded-lg border transition-all text-xs flex items-center gap-1 cursor-pointer"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--text-secondary)',
                    }}
                    title="Export JSON"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>JSON</span>
                  </button>
                </div>
              </div>

              {viewMode === 'text' ? (
                <div 
                  className="flex-1 p-3.5 rounded-xl border font-mono text-xs overflow-y-auto whitespace-pre-wrap leading-relaxed select-text max-h-[320px]"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--text-primary)',
                  }}
                >
                  {currentPage.text || <span className="text-[var(--text-muted)] italic">No text recognized</span>}
                </div>
              ) : (
                <div 
                  className="flex-1 p-3.5 rounded-xl border overflow-y-auto max-h-[320px] flex flex-wrap gap-1.5 content-start"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  {bboxes.map((b, i) => (
                    <span
                      key={i}
                      onMouseEnter={() => setHoveredBox(b)}
                      onMouseLeave={() => setHoveredBox(null)}
                      className="text-xs px-2 py-0.5 rounded cursor-pointer transition-all border"
                      style={{
                        backgroundColor: (b.confidence || 0) >= 0.85 
                          ? 'var(--success-bg)' 
                          : (b.confidence || 0) >= 0.70 
                          ? 'var(--warning-bg)' 
                          : 'var(--error-bg)',
                        borderColor: 'var(--border-color)',
                        color: (b.confidence || 0) >= 0.85 
                          ? 'var(--success)' 
                          : (b.confidence || 0) >= 0.70 
                          ? 'var(--warning)' 
                          : 'var(--error)',
                      }}
                    >
                      {b.word}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Save to Knowledge Workspace Panel */}
            {workspaceId && (
              <div 
                className="border rounded-2xl p-4 shadow-sm"
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  borderColor: 'var(--border-color)',
                }}
              >
                <div className="flex items-center gap-2 mb-3">
                  <Database className="w-4 h-4 text-[var(--brand-accent)]" />
                  <span className="text-xs font-bold text-[var(--text-primary)] uppercase tracking-wider">
                    {t('ocr.save_to_grid')}
                  </span>
                </div>

                <div className="space-y-3">
                  <div>
                    <label className="text-[11px] text-[var(--text-muted)] block mb-1 font-semibold">{t('docs.title')}</label>
                    <input 
                      type="text" 
                      value={docTitle}
                      onChange={(e) => setDocTitle(e.target.value)}
                      className="w-full border rounded-xl px-3 py-1.5 text-xs text-[var(--text-primary)] focus:outline-none"
                      style={{
                        backgroundColor: 'var(--input-bg)',
                        borderColor: 'var(--input-border)',
                      }}
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="text-[11px] text-[var(--text-muted)] block mb-1 font-semibold">Authority Rank</label>
                      <select
                        value={authorityLevel}
                        onChange={(e) => setAuthorityLevel(Number(e.target.value))}
                        className="w-full border rounded-xl px-2 py-1.5 text-xs text-[var(--text-primary)] focus:outline-none cursor-pointer"
                        style={{
                          backgroundColor: 'var(--input-bg)',
                          borderColor: 'var(--input-border)',
                        }}
                      >
                        <option value={1}>Rank 1: Working Draft</option>
                        <option value={2}>Rank 2: Team Wiki</option>
                        <option value={3}>Rank 3: Procedure</option>
                        <option value={4}>Rank 4: Statutory Policy</option>
                        <option value={5}>Rank 5: Legal Deed</option>
                      </select>
                    </div>

                    <div>
                      <label className="text-[11px] text-[var(--text-muted)] block mb-1 font-semibold">{t('docs.collection')}</label>
                      <select
                        value={targetCollectionId}
                        onChange={(e) => setTargetCollectionId(e.target.value)}
                        className="w-full border rounded-xl px-2 py-1.5 text-xs text-[var(--text-primary)] focus:outline-none cursor-pointer"
                        style={{
                          backgroundColor: 'var(--input-bg)',
                          borderColor: 'var(--input-border)',
                        }}
                      >
                        <option value="">(Default Collection)</option>
                        {collections.map(c => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {savedSuccessDocId ? (
                    <div 
                      className="p-3 border rounded-xl flex items-center justify-between"
                      style={{
                        backgroundColor: 'var(--success-bg)',
                        borderColor: 'var(--border-color)',
                      }}
                    >
                      <div className="flex items-center gap-2 text-xs font-semibold text-[var(--success)]">
                        <CheckCircle2 className="w-4 h-4" />
                        <span>Indexed into Qdrant & Ready for RAG!</span>
                      </div>
                      {onNavigateToRAG && (
                        <button
                          onClick={onNavigateToRAG}
                          className="px-2.5 py-1 rounded-xl text-white text-xs font-semibold flex items-center gap-1 transition-all cursor-pointer shadow-sm active:scale-95"
                          style={{ backgroundColor: 'var(--brand-accent)' }}
                        >
                          <span>{t('ocr.ask_rag')}</span>
                          <ArrowRight className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  ) : (
                    <button
                      onClick={handleSaveToWorkspace}
                      disabled={isSaving}
                      className="w-full py-2.5 rounded-xl text-white font-semibold text-xs transition-all shadow-sm flex items-center justify-center gap-2 cursor-pointer active:scale-95 disabled:opacity-50"
                      style={{ backgroundColor: 'var(--brand-accent)' }}
                    >
                      {isSaving ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          <span>Chunking, Embedding & Indexing Vectors...</span>
                        </>
                      ) : (
                        <>
                          <Sparkles className="w-3.5 h-3.5" />
                          <span>{t('ocr.save_to_grid')}</span>
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        /* Empty State */
        <div 
          className="border rounded-2xl p-12 text-center flex flex-col items-center justify-center gap-3 shadow-sm"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div 
            className="w-16 h-16 rounded-2xl border flex items-center justify-center"
            style={{
              backgroundColor: 'var(--accent-light)',
              borderColor: 'var(--border-color)',
              color: 'var(--brand-accent)',
            }}
          >
            <Scan className="w-8 h-8" />
          </div>
          <div className="text-base font-bold text-[var(--text-primary)]">No Document Loaded Yet</div>
          <p className="text-xs text-[var(--text-muted)] max-w-md">
            Click one of the quick test buttons above or drop a document image or PDF to experience real-time token extraction and phonetic repair.
          </p>
        </div>
      )}
    </div>
  );
};
